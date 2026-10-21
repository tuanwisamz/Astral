"""Street addresses for report pins (U3b), from Nominatim's reverse geocoder.

Results are cached in geocode_cache on an ~11 m grid, and requests are kept to one a second, as
Nominatim's usage policy asks. Any failure returns None, and the reporter types the address.
"""

import asyncio
import logging
import time

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.config import get_settings
from app.services import usage

log = logging.getLogger(__name__)

REVERSE = "https://nominatim.openstreetmap.org/reverse"
MAX_LENGTH = 200

_lock = asyncio.Lock()
_last_call = 0.0


def cache_key(lat: float, lng: float) -> str:
    return f"rev:{lat:.4f},{lng:.4f}"


def label(raw: dict | None) -> str | None:
    """A short address: road, area, town, postcode, state. Falls back to Nominatim's display name."""
    if not raw:
        return None
    a = raw.get("address") or {}
    parts = [
        a.get("road") or a.get("pedestrian") or a.get("path"),
        a.get("suburb") or a.get("neighbourhood") or a.get("village") or a.get("hamlet"),
        a.get("town") or a.get("city") or a.get("municipality"),
        a.get("postcode"),
        a.get("state"),
    ]
    out = ", ".join(dict.fromkeys(p for p in parts if p)) or raw.get("display_name") or ""
    return out[:MAX_LENGTH] or None


async def _fetch(lat: float, lng: float) -> dict | None:
    global _last_call
    async with _lock:
        wait = 1.1 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
        async with httpx.AsyncClient(timeout=8, headers={"User-Agent": get_settings().nominatim_user_agent}) as c:
            r = await c.get(
                REVERSE,
                params={"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 18, "addressdetails": 1,
                        "accept-language": "ms,en"},
            )
    r.raise_for_status()
    raw = r.json()
    return None if not isinstance(raw, dict) or "error" in raw else raw  # e.g. {"error": "Unable to geocode"}


async def reverse(session: AsyncSession, lat: float, lng: float) -> str | None:
    key = cache_key(lat, lng)
    cached = await db.row(session, "select raw from geocode_cache where query = :q", q=key)
    if cached:
        return label(cached["raw"])
    try:
        raw = await _fetch(lat, lng)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Reverse geocoding failed for %s: %s", key, exc)
        return None
    await usage.bump(session, "nominatim")
    keep = None if raw is None else {k: raw.get(k) for k in ("display_name", "address")}
    await session.execute(
        text("""
        insert into geocode_cache (query, lat, lng, raw) values (:q, :lat, :lng, cast(:raw as jsonb))
        on conflict (query) do nothing"""),
        {"q": key, "lat": lat, "lng": lng, "raw": keep},
    )
    await session.commit()
    return label(keep)
