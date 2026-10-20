"""News job (T5.3, architechture.md §8.1): RSS → keyword filter → Gemini extraction → geocode →
snap to a road → unverified NEWS incident or accident record. Only the title, URL and extracted
fields are stored, never the article text. Every result waits for an officer to verify it."""

import asyncio
import calendar
import logging
import re
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import quote_plus

import feedparser
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings
from app.core.errors import ApiError
from app.ingest import JobResult, job
from app.queries import incidents
from app.services import gemini, usage

log = logging.getLogger(__name__)

QUERIES = [
    ("jalan berlubang", "ms"),
    ("lubang jalan", "ms"),
    ("pokok tumbang jalan", "ms"),
    ("lubang benam", "ms"),
    ("tanah mendap jalan", "ms"),
    ("kemalangan maut", "ms"),
    ("pothole road Malaysia", "en"),
    ("fallen tree road Malaysia", "en"),
    ("sinkhole Malaysia", "en"),
    ("fatal crash Malaysia road", "en"),
]
KEYWORDS = re.compile(
    r"berlubang|lubang jalan|pokok tumbang|lubang benam|tanah mendap|kemalangan|pothole|"
    r"fallen tree|tree fell|sinkhole|crash|accident|collision|maut",
    re.I,
)
MAX_GEMINI_PER_RUN = 30
SNAP_RADIUS_M = 200
NOMINATIM = "https://nominatim.openstreetmap.org/search"


class NewsExtraction(BaseModel):
    relevant: bool = Field(
        description="True if the item reports a specific road hazard or road accident in Peninsular Malaysia"
    )
    hazard_type: Literal["POTHOLE", "FALLEN_TREE", "SINKHOLE"] | None = None
    is_accident: bool = False
    location_text: str | None = Field(default=None, description="Place as written, without people's names")
    road_name: str | None = None
    route_ref: str | None = Field(default=None, description="Route number such as FT1, A15 or E2 if stated")
    town: str | None = None
    state: str | None = None
    event_date: str | None = Field(default=None, description="YYYY-MM-DD if stated")
    deaths: int = 0
    injuries: int = 0
    severity: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(ge=0, le=1)


PROMPT = """Extract road-hazard facts from this Malaysian news item (Malay or English).
Only the title and summary are given. Report a hazard only if it is a pothole, fallen tree or
sinkhole on or beside a specific road. Report an accident if a road crash is described, with
deaths and injuries as numbers. Never output anyone's name. If unsure, set relevant to false.

Title: {title}
Summary: {summary}"""


def _feed_url(q: str, lang: str) -> str:
    ceid = "MY:ms" if lang == "ms" else "MY:en"
    return f"https://news.google.com/rss/search?q={quote_plus(q + ' when:3d')}&hl={lang}-MY&gl=MY&ceid={ceid}"


async def _geocode(session: AsyncSession, client: httpx.AsyncClient, query: str) -> tuple[float, float] | None:
    cached = await db.row(session, "select lat, lng from geocode_cache where query = :q", q=query)
    if cached:
        return (float(cached["lat"]), float(cached["lng"])) if cached["lat"] is not None else None
    await asyncio.sleep(1.1)  # Nominatim's policy: at most one request per second
    r = await client.get(NOMINATIM, params={"q": query, "format": "json", "countrycodes": "my", "limit": 1})
    await usage.bump(session, "nominatim")
    hit = r.json()[0] if r.status_code == 200 and r.json() else None
    await session.execute(
        text("""
        insert into geocode_cache (query, lat, lng, raw) values (:q, :lat, :lng, cast(:raw as jsonb))
        on conflict (query) do nothing"""),
        {
            "q": query,
            "lat": float(hit["lat"]) if hit else None,
            "lng": float(hit["lon"]) if hit else None,
            "raw": None if hit is None else {k: hit.get(k) for k in ("display_name", "type")},
        },
    )
    return (float(hit["lat"]), float(hit["lon"])) if hit else None


async def _snap(session: AsyncSession, lat: float, lng: float) -> dict | None:
    return await db.row(
        session,
        """
        with pt as (select ST_SetSRID(ST_Point(:lng, :lat), 4326) as g)
        select s.id as segment_id, s.road_class, s.name, s.ref, ST_ClosestPoint(s.geom, pt.g) as snapped,
               ST_Y(ST_ClosestPoint(s.geom, pt.g)) as slat, ST_X(ST_ClosestPoint(s.geom, pt.g)) as slng
        from pt, road_segments s
        where ST_DWithin(s.geom::geography, pt.g::geography, :r)
        order by s.geom <-> pt.g limit 1""",
        lat=lat,
        lng=lng,
        r=SNAP_RADIUS_M,
    )


def _published(entry) -> datetime | None:
    t = entry.get("published_parsed")
    return datetime.fromtimestamp(calendar.timegm(t), UTC) if t else None


@job("news")
async def news(session: AsyncSession) -> JobResult:
    settings = get_settings()
    candidates: dict[str, dict] = {}
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": settings.nominatim_user_agent}
    ) as client:
        for q, lang in QUERIES:
            r = await client.get(_feed_url(q, lang))
            for e in feedparser.parse(r.text).entries:
                title, summary = e.get("title", ""), re.sub(r"<[^>]+>", " ", e.get("summary", ""))
                if e.get("link") and KEYWORDS.search(f"{title} {summary}"):
                    candidates.setdefault(
                        e["link"],
                        {
                            "title": title,
                            "summary": summary[:600],
                            "source": e.get("source", {}).get("title"),
                            "published": _published(e),
                        },
                    )
        seen = {
            r["url"]
            for r in await db.rows(session, "select url from news_items where url = any(:u)", u=list(candidates))
        }
        new = [(u, c) for u, c in candidates.items() if u not in seen][:MAX_GEMINI_PER_RUN]
        linked = calls = 0
        model = settings.gemini_model_lite
        for url, c in new:
            status, incident_id, accident_id, extracted = "IRRELEVANT", None, None, None
            try:
                calls += 1
                ex = await gemini.generate(
                    session, model, [PROMPT.format(title=c["title"], summary=c["summary"])], NewsExtraction
                )
                extracted = ex.model_dump()
                if ex.relevant and (ex.hazard_type or (ex.is_accident and (ex.deaths or ex.injuries))):
                    status = "NEEDS_REVIEW"
                    query = ", ".join(p for p in (ex.road_name or ex.route_ref, ex.town, ex.state, "Malaysia") if p)
                    point = await _geocode(session, client, query) if query != "Malaysia" else None
                    seg = await _snap(session, *point) if point else None
                    if seg:
                        status = "LINKED"
                        if ex.hazard_type:
                            dup = await incidents.find_duplicate(session, ex.hazard_type, seg["slat"], seg["slng"])
                            if dup:
                                await incidents.confirm(session, dup, None)
                                incident_id = dup["id"]
                            else:
                                created = await incidents.create(
                                    session,
                                    hazard_type=ex.hazard_type,
                                    severity=ex.severity,
                                    lat=seg["slat"],
                                    lng=seg["slng"],
                                    segment=seg,
                                    source="NEWS",
                                    actor=None,
                                    source_url=url,
                                    description=c["title"][:300],
                                    confidence=ex.confidence,
                                    reported_at=c["published"] or datetime.now(UTC),
                                )
                                incident_id = created["id"]
                        if ex.is_accident and (ex.deaths or ex.injuries):
                            accident_id = await db.scalar(
                                session,
                                """
                                insert into accidents (segment_id, occurred_on, deaths, injuries, source, source_url, geom)
                                values (:sid, :on, :d, :i, 'NEWS', :url, ST_SetSRID(ST_Point(:lng, :lat), 4326))
                                returning id::text""",
                                sid=seg["segment_id"],
                                on=_date(ex.event_date, c["published"]),
                                d=ex.deaths,
                                i=ex.injuries,
                                url=url,
                                lng=seg["slng"],
                                lat=seg["slat"],
                            )
                        linked += 1
            except ApiError:
                await session.rollback()
                continue  # Gemini unavailable: not stored, so the next run tries this item again
            await session.execute(
                text("""
                insert into news_items (url, title, source, published_at, extracted, status, incident_id, accident_id)
                values (:url, :title, :source, :pub, cast(:ex as jsonb), :status, cast(:inc as uuid), cast(:acc as uuid))
                on conflict (url) do nothing"""),
                {
                    "url": url,
                    "title": c["title"][:500],
                    "source": c["source"],
                    "pub": c["published"],
                    "ex": extracted,
                    "status": status,
                    "inc": incident_id,
                    "acc": accident_id,
                },
            )
            await session.commit()
    note = None if settings.reddit_client_id else "Reddit skipped: REDDIT_CLIENT_ID is not set"
    return JobResult(items=linked, quota_used=calls, note=note)


def _date(value: str | None, fallback: datetime | None) -> date:
    try:
        return date.fromisoformat(value) if value else (fallback or datetime.now(UTC)).date()
    except ValueError:
        return (fallback or datetime.now(UTC)).date()
