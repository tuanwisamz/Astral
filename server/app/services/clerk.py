"""Clerk Backend API calls for admin user management (spec-api §4.20, plan D9).

Clerk's publicMetadata is the source of truth for role and scope (plan D4).
"""

import time

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError

CLERK_API = "https://api.clerk.com/v1"
SCOPE_KEYS = ("role", "state_code", "district_id", "agency_id")


def _headers() -> dict[str, str]:
    key = get_settings().clerk_secret_key
    if not key:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "User management needs CLERK_SECRET_KEY on the server")
    return {"Authorization": f"Bearer {key}"}


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(base_url=CLERK_API, timeout=10) as client:
            res = await client.request(method, path, headers=_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Clerk can't be reached right now") from exc
    if res.status_code == 404:
        raise ApiError(404, "NOT_FOUND", "No such user in Clerk")
    if res.status_code >= 400:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", f"Clerk returned {res.status_code}")
    return res


def to_user(raw: dict) -> dict:
    """The fields the Admin page needs; nothing else leaves the server."""
    emails = {e["id"]: e["email_address"] for e in raw.get("email_addresses", [])}
    meta = raw.get("public_metadata") or {}
    return {
        "clerk_id": raw["id"],
        "email": emails.get(raw.get("primary_email_address_id")) or next(iter(emails.values()), None),
        "role": meta.get("role") or "public",
        "state_code": meta.get("state_code"),
        "district_id": meta.get("district_id"),
        "agency_id": meta.get("agency_id"),
        "created_at": raw.get("created_at"),
    }


async def list_users(query: str | None, limit: int, offset: int) -> list[dict]:
    params = {"limit": limit, "offset": offset, "order_by": "-created_at"}
    if query:
        params["query"] = query
    res = await _request("GET", "/users", params=params)
    return [to_user(u) for u in res.json()]


async def update_scope(clerk_id: str, scope: dict) -> dict:
    """Merges into publicMetadata; a None value removes that key (Clerk's merge semantics)."""
    res = await _request("PATCH", f"/users/{clerk_id}/metadata", json={"public_metadata": scope})
    _metadata_cache.pop(clerk_id, None)  # a promotion takes effect on the next request
    return to_user(res.json())


# clerk_id -> (expires_at, publicMetadata). Only used when tokens lack the role claim.
_metadata_cache: dict[str, tuple[float, dict]] = {}
METADATA_TTL_S = 60


async def public_metadata(clerk_id: str) -> dict:
    now = time.monotonic()
    hit = _metadata_cache.get(clerk_id)
    if hit and hit[0] > now:
        return hit[1]
    res = await _request("GET", f"/users/{clerk_id}")
    meta = res.json().get("public_metadata") or {}
    _metadata_cache[clerk_id] = (now + METADATA_TTL_S, meta)
    return meta
