"""Apply server/migrations/*.sql in order (plan D7).

Usage (from server/):  python migrate.py
Applied files are recorded in schema_migrations, so re-running is safe.
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

from app.core.config import get_settings

MIGRATIONS = Path(__file__).parent / "migrations"


async def main() -> int:
    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        print("DATABASE_URL is not set (server/.env)")
        return 1
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        await conn.execute(
            "create table if not exists schema_migrations (name text primary key, applied_at timestamptz default now())"
        )
        applied = {r["name"] for r in await conn.fetch("select name from schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in applied:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("insert into schema_migrations (name) values ($1)", path.name)
            print(f"applied {path.name}")
        print("database is up to date")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
