import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Response
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.errors import ApiError

_engine: AsyncEngine | None = None
_engine_url: str | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _json_codecs(dbapi_conn, _record) -> None:
    """Raw SQL (text()) has no column types, so asyncpg would hand back JSON as strings.
    Decode json/jsonb on every connection instead."""

    async def register(conn):
        for name in ("json", "jsonb"):
            await conn.set_type_codec(name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

    dbapi_conn.run_async(register)


def get_engine() -> AsyncEngine | None:
    global _engine, _engine_url, _sessionmaker
    settings = get_settings()
    url = settings.database_url
    if not url:
        return None
    if _engine is None or _engine_url != url:
        # statement_cache_size=0 keeps asyncpg working if the URL points at the
        # Supabase transaction pooler (port 6543) instead of session mode (plan D3).
        # Tests open a fresh event loop per client, so they can't share pooled connections.
        pool = (
            {"poolclass": NullPool}
            if settings.app_env == "test"
            else {"pool_size": 5, "max_overflow": 5, "pool_pre_ping": True, "pool_recycle": 300}
        )
        _engine = create_async_engine(url, connect_args={"statement_cache_size": 0}, **pool)
        event.listen(_engine.sync_engine, "connect", _json_codecs)
        _engine_url = url
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def get_session() -> AsyncIterator[AsyncSession]:
    if get_engine() is None or _sessionmaker is None:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Database is not configured")
    async with _sessionmaker() as session:
        yield session


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[dict]:
    result = await session.execute(text(sql), params)
    return [dict(r) for r in result.mappings()]


async def row(session: AsyncSession, sql: str, **params: Any) -> dict | None:
    found = await rows(session, sql, **params)
    return found[0] if found else None


async def scalar(session: AsyncSession, sql: str, **params: Any) -> Any:
    return (await session.execute(text(sql), params)).scalar()


def json_response(payload: Any) -> Response:
    """For JSON already built by Postgres (json_agg): skips re-parsing it in Python."""
    body = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    return Response(content=body, media_type="application/json")


async def ping() -> dict:
    engine = get_engine()
    if engine is None:
        return {"configured": False, "ok": False}
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("select postgis_version()"))).scalar_one()
        return {"configured": True, "ok": True, "postgis": version}
    except Exception as exc:  # health check reports, never raises
        return {"configured": True, "ok": False, "error": type(exc).__name__}


async def dispose() -> None:
    if _engine is not None:
        await _engine.dispose()
