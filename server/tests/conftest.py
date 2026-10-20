"""Test database: a fresh `astral_test` on the local PostGIS (docker-compose; CI runs a PostGIS
service on the same port), built from the migrations plus a tiny fixture network.

External services are blanked out, so no test can reach Gemini, Clerk, Supabase or TomTom.
"""

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings

SERVER = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:54322/postgres")
TEST_DB = "astral_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
RESET_TABLES = (
    "incident_events",
    "incidents",
    "accidents",
    "report_analyses",
    "usage_daily",
    "predictions",
    "weather_warnings",
    "jurisdiction_overrides",
    "job_runs",
    "model_versions",
    "traffic_snapshots",
    "news_items",
    "weather_daily",
)

BLANK = {
    "GEMINI_API_KEY": "",
    "CLERK_SECRET_KEY": "",
    "CLERK_JWKS_URL": "",
    "SUPABASE_URL": "",
    "SUPABASE_SERVICE_KEY": "",
    "TOMTOM_API_KEY": "",
    "REDDIT_CLIENT_ID": "",
    "CRON_SECRET": "test-secret",
}


async def _rebuild() -> None:
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f"drop database if exists {TEST_DB} with (force)")
    await admin.execute(f"create database {TEST_DB}")
    await admin.close()
    conn = await asyncpg.connect(TEST_URL)
    for path in sorted((SERVER / "migrations").glob("*.sql")):
        await conn.execute(path.read_text(encoding="utf-8"))
    await conn.execute((SERVER / "tests" / "fixtures.sql").read_text(encoding="utf-8"))
    await conn.close()


@pytest.fixture(scope="session")
def database() -> str:
    try:
        asyncio.run(_rebuild())
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostGIS test database unavailable ({exc}); run `docker compose up -d`")
    return TEST_URL.replace("postgresql://", "postgresql+asyncpg://")


async def _reset() -> None:
    conn = await asyncpg.connect(TEST_URL)
    await conn.execute(f"truncate {', '.join(RESET_TABLES)} restart identity cascade")
    await conn.execute("refresh materialized view segment_components")
    await conn.close()


async def sql(query: str, *args):
    """Run SQL against the test database (for setting up and checking state)."""
    conn = await asyncpg.connect(TEST_URL)
    try:
        return await conn.fetch(query, *args)
    finally:
        await conn.close()


@pytest.fixture
def api(monkeypatch, database):
    """api(role, state=None) -> a TestClient acting as that role through the dev bypass."""
    asyncio.run(_reset())
    for k, v in {**BLANK, "APP_ENV": "test", "DATABASE_URL": database}.items():
        monkeypatch.setenv(k, v)

    def as_role(role: str | None = None, state: str | None = None) -> TestClient:
        monkeypatch.setenv("DEV_AUTH_ROLE", role or "")
        monkeypatch.setenv("DEV_AUTH_STATE", state or "")
        get_settings.cache_clear()
        from app.main import app

        return TestClient(app)

    yield as_role
    get_settings.cache_clear()
