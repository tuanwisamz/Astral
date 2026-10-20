"""Supabase Storage for report photos: a private bucket, read through short-lived signed URLs
(architechture.md §13). Only the backend holds the service key."""

import httpx

from app.core.config import get_settings
from app.core.errors import ApiError

BUCKET = "report-photos"
SIGNED_URL_SECONDS = 600


def _base_and_headers() -> tuple[str, dict[str, str]]:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Photo storage isn't configured on this server")
    key = s.supabase_service_key
    return f"{s.supabase_url.rstrip('/')}/storage/v1", {"Authorization": f"Bearer {key}", "apikey": key}


async def upload(path: str, data: bytes, content_type: str) -> None:
    base, headers = _base_and_headers()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{base}/object/{BUCKET}/{path}",
                content=data,
                headers={**headers, "Content-Type": content_type, "x-upsert": "false"},
            )
    except httpx.HTTPError as exc:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Photo storage can't be reached right now") from exc
    if r.status_code >= 400:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", f"Photo storage refused the upload ({r.status_code})")


async def signed_url(path: str, seconds: int = SIGNED_URL_SECONDS) -> str:
    base, headers = _base_and_headers()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{base}/object/sign/{BUCKET}/{path}", json={"expiresIn": seconds}, headers=headers)
    if r.status_code >= 400:
        raise ApiError(404, "NOT_FOUND", "Photo not found")
    signed = r.json().get("signedURL") or r.json().get("signedUrl")
    return f"{base}{signed}" if signed.startswith("/") else signed


async def delete(paths: list[str]) -> None:
    if not paths:
        return
    base, headers = _base_and_headers()
    async with httpx.AsyncClient(timeout=30) as c:
        await c.request("DELETE", f"{base}/object/{BUCKET}", json={"prefixes": paths}, headers=headers)
