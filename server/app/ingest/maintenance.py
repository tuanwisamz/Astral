"""Housekeeping jobs: refresh priority components, clean up abandoned photos, prune old
snapshots, and live traffic for the top roads (T5.4, P1)."""

import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings
from app.ingest import JobResult, job
from app.queries import priority as ranking
from app.services import storage, usage

TOMTOM_FLOW = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
TOP_SEGMENTS = 50  # FR-ING-04: about 1,200 of TomTom's 2,500 free calls a day when run hourly
TOP_UTP_SEGMENTS = 20  # plan A2: plus the focus area, about 1,680 calls a day in all
SNAPSHOT_RETENTION_DAYS = 90  # plan §6 database budget


@job("priority")
async def priority(session: AsyncSession) -> JobResult:
    """Refresh the slow priority components (plan D1). The ranking itself is live."""
    await session.execute(text("refresh materialized view concurrently segment_components"))
    await session.commit()
    count = await db.scalar(session, "select count(*) from segment_components")
    return JobResult(items=int(count))


@job("cleanup")
async def cleanup(session: AsyncSession) -> JobResult:
    """Delete photos whose analysis never became a report (plan §6), and prune old snapshots.
    Also keeps the free Supabase project from pausing (spec §11)."""
    stale = await db.rows(
        session,
        """
        delete from report_analyses where incident_id is null and created_at < now() - interval '24 hours'
        returning photo_path""",
    )
    await storage.delete([r["photo_path"] for r in stale if r["photo_path"]])
    await session.execute(
        text(f"delete from traffic_snapshots where ts < now() - interval '{SNAPSHOT_RETENTION_DAYS} days'")
    )
    await session.execute(text("delete from usage_daily where day < current_date - 60"))
    await session.commit()
    return JobResult(items=len(stale))


@job("traffic")
async def traffic(session: AsyncSession) -> JobResult:
    key = get_settings().tomtom_api_key
    if not key:
        return JobResult(note="TOMTOM_API_KEY is not set")
    profile = await ranking.default_profile(session)
    top, _ = await ranking.rank(
        session, profile["weights"], "s.road_class <> 'MUNICIPAL'", "true", {}, limit=TOP_SEGMENTS
    )
    # The focus area around UTP is sampled too, whatever its Peninsula-wide rank (plan A2).
    utp, _ = await ranking.rank(session, profile["weights"], "s.pilot = 'UTP'", "true", {}, limit=TOP_UTP_SEGMENTS)
    ids = list(dict.fromkeys(t["segment_id"] for t in top + utp))
    points = await db.rows(
        session,
        """
        select id, ST_Y(ST_LineInterpolatePoint(geom, 0.5)) as lat, ST_X(ST_LineInterpolatePoint(geom, 0.5)) as lng
        from road_segments where id = any(:ids)""",
        ids=ids,
    )
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    stored = calls = 0
    async with httpx.AsyncClient(timeout=20) as c:
        for p in points:
            r = await c.get(TOMTOM_FLOW, params={"point": f"{p['lat']},{p['lng']}", "key": key, "unit": "KMPH"})
            calls += 1
            if r.status_code != 200:
                continue
            fs = r.json().get("flowSegmentData", {})
            await session.execute(
                text("""
                insert into traffic_snapshots (segment_id, ts, current_speed, freeflow_speed, confidence)
                values (:sid, :ts, :cur, :free, :conf) on conflict do nothing"""),
                {
                    "sid": p["id"],
                    "ts": now,
                    "cur": fs.get("currentSpeed"),
                    "free": fs.get("freeFlowSpeed"),
                    "conf": fs.get("confidence"),
                },
            )
            stored += 1
            await asyncio.sleep(0.2)
    await usage.bump(session, "tomtom", by=calls)
    await session.commit()
    return JobResult(items=stored, quota_used=calls)
