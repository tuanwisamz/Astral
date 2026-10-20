"""Weather jobs (T5.1, T5.2, T5.5): MET warnings and forecast from data.gov.my, flood stations,
and Open-Meteo rain and wind per 0.1° cell. All free; each records its quota use."""

import asyncio
import hashlib
import re
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.ingest import JobResult, job
from app.services import usage

DATA_GOV = "https://api.data.gov.my"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
CELLS_PER_REQUEST = 40  # hourly data makes each location weigh more against the per-minute limit
PAUSE_BETWEEN_REQUESTS_S = 8
MARINE = re.compile(r"\b(seas?|waters|shipping|nautical)\b", re.I)
FLOOD_LEVELS = {"ALERT": "ALERT", "WARNING": "WARNING", "DANGER": "DANGER"}
FLOOD_BUFFER_M = 3000
STALE_AFTER = timedelta(days=2)
_MYT = timezone(timedelta(hours=8))


async def _get_json(url: str, **params) -> list | dict:
    """GET with patience for per-minute limits: Open-Meteo answers 429 when a minute's quota is used."""
    async with httpx.AsyncClient(
        timeout=90, follow_redirects=True, headers={"User-Agent": "smart-analysis-road/1.0"}
    ) as c:
        for attempt in range(4):
            r = await c.get(url, params=params)
            if r.status_code != 429 or attempt == 3:
                r.raise_for_status()
                return r.json()
            await asyncio.sleep(int(r.headers.get("Retry-After", 0)) or 65)
    raise RuntimeError("unreachable")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("â¢", ",").replace("•", ",")).strip()


# --- warnings (T5.1) -----------------------------------------------------------------------


@job("warnings")
async def warnings(session: AsyncSession) -> JobResult:
    """Land warnings only: marine ones name sea areas, which would wrongly flag the coast.
    Areas are given in text, so district and state names are matched to our polygons (plan M5)."""
    data = await _get_json(f"{DATA_GOV}/weather/warning/", limit=100)
    districts = await db.rows(session, "select id::text as id, name, state_code from districts")
    states = await db.rows(session, "select code, name from states")
    stored = 0
    for w in data:
        issue = w.get("warning_issue") or {}
        title = issue.get("title_en") or w.get("heading_en") or ""
        body = _norm(f"{w.get('text_en') or ''} {w.get('text_bm') or ''}")
        if MARINE.search(title) or body.upper().startswith("SECTION A: FOR MALAYSIAN WATERS"):
            continue
        hits = [d["id"] for d in districts if re.search(rf"\b{re.escape(d['name'])}\b", body, re.I)]
        named_states = [s["code"] for s in states if re.search(rf"\b{re.escape(s['name'])}\b", body, re.I)]
        # A state named with none of its districts listed means the whole state.
        whole = [c for c in named_states if not any(d["state_code"] == c and d["id"] in hits for d in districts)]
        if not hits and not whole:
            continue
        source_id = hashlib.sha1(f"{issue.get('issued')}|{title}|{w.get('valid_from')}".encode()).hexdigest()[:24]
        await session.execute(
            text("""
            insert into weather_warnings (source_id, kind, severity, area_text, valid_from, valid_to, raw, geom)
            select :sid, :kind, :severity, :area, :vf, :vt, cast(:raw as jsonb), ST_Multi(ST_Union(g))
            from (select geom as g from districts where id::text = any(:dids)
                  union all select geom from states where code = any(:codes)) parts
            on conflict (source_id) do update set valid_to = excluded.valid_to, raw = excluded.raw, geom = excluded.geom"""),
            {
                "sid": source_id,
                "kind": title[:120],
                "severity": _severity(title),
                "area": body[:2000],
                "vf": _ts(w.get("valid_from")),
                "vt": _ts(w.get("valid_to")),
                "raw": w,
                "dids": hits,
                "codes": whole,
            },
        )
        stored += 1
    await session.commit()
    return JobResult(items=stored, quota_used=1)


def _severity(title: str) -> str:
    t = title.lower()
    return "DANGER" if "danger" in t or "bahaya" in t else "SEVERE" if "severe" in t or "buruk" in t else "ALERT"


def _ts(value: str | None) -> datetime | None:
    """MET times are Malaysian local time without an offset."""
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=_MYT)


# --- forecast (T5.1) -----------------------------------------------------------------------


@job("forecast")
async def forecast(session: AsyncSession) -> JobResult:
    data = await _get_json(f"{DATA_GOV}/weather/forecast/", limit=2000)
    districts = {
        d["name"].lower(): d["id"] for d in await db.rows(session, "select id::text as id, name from districts")
    }
    for f in data:
        loc = f.get("location") or {}
        await session.execute(
            text("""
            insert into weather_forecasts (location_id, date, location_name, district_id, morning, afternoon, night,
                                           summary, summary_when, min_temp, max_temp, fetched_at)
            values (:lid, :d, :name, cast(:did as uuid), :m, :a, :n, :s, :sw, :tmin, :tmax, now())
            on conflict (location_id, date) do update set morning = excluded.morning, afternoon = excluded.afternoon,
                night = excluded.night, summary = excluded.summary, summary_when = excluded.summary_when,
                min_temp = excluded.min_temp, max_temp = excluded.max_temp, fetched_at = now()"""),
            {
                "lid": loc.get("location_id"),
                "d": date.fromisoformat(f["date"]),
                "name": loc.get("location_name"),
                "did": districts.get((loc.get("location_name") or "").lower()),
                "m": f.get("morning_forecast"),
                "a": f.get("afternoon_forecast"),
                "n": f.get("night_forecast"),
                "s": f.get("summary_forecast"),
                "sw": f.get("summary_when"),
                "tmin": f.get("min_temp"),
                "tmax": f.get("max_temp"),
            },
        )
    await session.execute(text("delete from weather_forecasts where date < current_date - 7"))
    await session.commit()
    return JobResult(items=len(data), quota_used=1)


# --- flood (T5.5, P1) ----------------------------------------------------------------------


@job("flood")
async def flood(session: AsyncSession) -> JobResult:
    data = await _get_json(f"{DATA_GOV}/flood-warning/", limit=2000)
    now = datetime.now(_MYT)
    fresh = stored = 0
    for st in data:
        level = FLOOD_LEVELS.get((st.get("water_level_indicator") or "").upper())
        updated = st.get("water_level_update_datetime")
        if not updated or st.get("latitude") is None:
            continue
        at = datetime.fromisoformat(updated).replace(tzinfo=_MYT)
        if now - at > STALE_AFTER:
            continue  # the feed sometimes serves old readings; never show them as current
        fresh += 1
        if not level:
            continue
        await session.execute(
            text("""
            insert into weather_warnings (source_id, kind, severity, area_text, valid_from, valid_to, raw, geom)
            values (:sid, 'FLOOD', :level, :area, :at, :until, cast(:raw as jsonb),
                    ST_Multi(ST_Buffer(ST_SetSRID(ST_Point(:lng, :lat), 4326)::geography, :buf)::geometry))
            on conflict (source_id) do update set severity = excluded.severity, valid_to = excluded.valid_to,
                raw = excluded.raw"""),
            {
                "sid": f"flood:{st['station_id']}:{at:%Y%m%d%H}",
                "level": level,
                "area": f"{st.get('station_name')}, {st.get('district')}, {st.get('state')}",
                "at": at,
                "until": at + timedelta(hours=6),
                "raw": st,
                "lng": st["longitude"],
                "lat": st["latitude"],
                "buf": FLOOD_BUFFER_M,
            },
        )
        stored += 1
    await session.commit()
    note = None if fresh else "Flood feed returned no readings from the last 2 days"
    return JobResult(items=stored, quota_used=1, note=note)


# --- Open-Meteo rain and wind per cell (T5.2) -----------------------------------------------


def cell_centre(cell_id: str) -> tuple[float, float]:
    lat, lng = (float(v) for v in cell_id.split("_"))
    return round(lat + 0.05, 3), round(lng + 0.05, 3)


async def fetch_cells(cell_ids: list[str], *, archive: tuple[date, date] | None = None) -> list[dict]:
    """Daily rain total, max hourly rain and max gust per cell. Several cells per request;
    Open-Meteo counts each location as a call (plan §6)."""
    rows: list[dict] = []
    for i in range(0, len(cell_ids), CELLS_PER_REQUEST):
        chunk = cell_ids[i : i + CELLS_PER_REQUEST]
        centres = [cell_centre(c) for c in chunk]
        params = {
            "latitude": ",".join(str(c[0]) for c in centres),
            "longitude": ",".join(str(c[1]) for c in centres),
            "daily": "precipitation_sum,wind_gusts_10m_max",
            "hourly": "precipitation",
            "timezone": "Asia/Kuala_Lumpur",
        }
        if archive:
            url = OPEN_METEO_ARCHIVE
            params.update(start_date=archive[0].isoformat(), end_date=archive[1].isoformat())
        else:
            url = OPEN_METEO_FORECAST
            params.update(past_days=7, forecast_days=8)
        if i:
            await asyncio.sleep(PAUSE_BETWEEN_REQUESTS_S)
        data = await _get_json(url, **params)
        results = data if isinstance(data, list) else [data]
        today = date.today()
        for cell, res in zip(chunk, results, strict=True):
            hourly_max: dict[str, float] = {}
            for t, v in zip(res["hourly"]["time"], res["hourly"]["precipitation"], strict=True):
                if v is not None:
                    hourly_max[t[:10]] = max(hourly_max.get(t[:10], 0.0), v)
            for d, rain, gust in zip(
                res["daily"]["time"], res["daily"]["precipitation_sum"], res["daily"]["wind_gusts_10m_max"], strict=True
            ):
                rows.append(
                    {
                        "cell": cell,
                        "date": date.fromisoformat(d),
                        "rain": rain,
                        "rain_hr": hourly_max.get(d),
                        "gust": gust,
                        "forecast": date.fromisoformat(d) > today,
                    }
                )
    return rows


async def save_weather(session: AsyncSession, rows: list[dict]) -> None:
    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        await session.execute(
            text("""
            insert into weather_daily (cell_id, date, rain_mm, rain_max_hr, gust_max_kmh, is_forecast)
            select * from unnest(cast(:cells as text[]), cast(:dates as date[]), cast(:rain as numeric[]),
                                 cast(:rainhr as numeric[]), cast(:gust as numeric[]), cast(:fc as boolean[]))
            on conflict (cell_id, date) do update set rain_mm = excluded.rain_mm, rain_max_hr = excluded.rain_max_hr,
                gust_max_kmh = excluded.gust_max_kmh, is_forecast = excluded.is_forecast"""),
            {
                "cells": [r["cell"] for r in chunk],
                "dates": [r["date"] for r in chunk],
                "rain": [r["rain"] for r in chunk],
                "rainhr": [r["rain_hr"] for r in chunk],
                "gust": [r["gust"] for r in chunk],
                "fc": [r["forecast"] for r in chunk],
            },
        )


@job("weather")
async def weather(session: AsyncSession) -> JobResult:
    cells = [
        r["cell_id"]
        for r in await db.rows(
            session, "select distinct cell_id from road_segments where cell_id is not null order by 1"
        )
    ]
    rows = await fetch_cells(cells)
    await save_weather(session, rows)
    await usage.bump(session, "open_meteo", by=len(cells))
    await session.commit()
    return JobResult(items=len(rows), quota_used=len(cells))
