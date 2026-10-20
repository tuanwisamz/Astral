"""Per-minute rate limits (spec-api §5, plan D5). In memory, so they reset when Render restarts;
that's fine for per-minute limits. Daily limits live in Postgres (services/usage.py)."""

import hashlib
import time

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.errors import error_body

_limiter = MovingWindowRateLimiter(MemoryStorage())
MAP = parse("120/minute")
DEFAULT = parse("300/minute")


def _who(request: Request) -> str:
    auth = request.headers.get("authorization")
    if auth:
        return hashlib.sha256(auth.encode()).hexdigest()[:24]
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/v1/") or path.startswith(("/api/v1/health", "/api/v1/internal/")):
            return await call_next(request)
        limit = MAP if path.startswith("/api/v1/map/") else DEFAULT
        key = ("map" if limit is MAP else "api", _who(request))
        if not _limiter.hit(limit, *key):
            reset = int(_limiter.get_window_stats(limit, *key).reset_time - time.time()) + 1
            return JSONResponse(
                error_body("RATE_LIMITED", "Too many requests. Wait a moment, then try again."),
                status_code=429,
                headers={"Retry-After": str(max(reset, 1))},
            )
        return await call_next(request)
