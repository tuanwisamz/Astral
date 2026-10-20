"""Daily counters in Postgres (plan D5): external API quotas and per-user limits.

One atomic upsert per call, so the count survives Render restarts and can't race.
Days are Malaysian days, so limits reset at midnight MYT.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.errors import ApiError

MYT = timezone(timedelta(hours=8))

# Per-user daily limits (spec-api §5).
LIMITS = {"report": 10, "analyze": 20, "assistant": 30, "explain": 100}

TODAY = "(now() at time zone 'Asia/Kuala_Lumpur')::date"


def seconds_to_midnight() -> int:
    now = datetime.now(MYT)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds()) + 1


async def bump(session: AsyncSession, counter: str, clerk_id: str = "", by: int = 1) -> int:
    used = await db.scalar(
        session,
        f"""
        insert into usage_daily (day, counter, clerk_id, used) values ({TODAY}, :counter, :clerk_id, :by)
        on conflict (day, counter, clerk_id) do update set used = usage_daily.used + excluded.used
        returning used""",
        counter=counter,
        clerk_id=clerk_id,
        by=by,
    )
    return int(used)


async def take(session: AsyncSession, counter: str, clerk_id: str) -> int:
    """Counts one use against the person's daily limit, refusing when it's used up."""
    used = await bump(session, counter, clerk_id)
    limit = LIMITS[counter]
    if used > limit:
        await bump(session, counter, clerk_id, by=-1)
        await session.commit()
        raise ApiError(
            429,
            "DAILY_LIMIT",
            f"You've reached today's limit of {limit}. It resets at midnight.",
            {"limit": limit},
            headers={"Retry-After": str(seconds_to_midnight())},
        )
    return used


async def today(session: AsyncSession, counter: str, clerk_id: str = "") -> int:
    return int(
        await db.scalar(
            session,
            f"""
        select coalesce(sum(used), 0) from usage_daily
        where day = {TODAY} and counter = :counter and clerk_id = :clerk_id""",
            counter=counter,
            clerk_id=clerk_id,
        )
    )
