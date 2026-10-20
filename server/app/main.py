import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_router
from app.core import db
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.ratelimit import RateLimitMiddleware

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.dev_auth_role and not settings.dev_auth_allowed:
        log.warning("DEV_AUTH_ROLE is set but ignored because APP_ENV=%s", settings.app_env)
    yield
    await db.dispose()


app = FastAPI(title="Smart Analysis Road API", version="0.2.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Retry-After", "Content-Disposition"],
)
install_error_handlers(app)
app.include_router(v1_router)
