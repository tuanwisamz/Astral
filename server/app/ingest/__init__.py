"""Scheduled jobs (architechture.md §8). Each job is idempotent and records a job_runs row.

GitHub Actions calls POST /internal/jobs/{name} (cron-jobs.yml). Training and prediction run
in GitHub Actions directly instead (plan D2), so they aren't here.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


@dataclass
class JobResult:
    items: int = 0
    quota_used: int = 0
    note: str | None = None


JobFn = Callable[[AsyncSession], Awaitable[JobResult]]
REGISTRY: dict[str, JobFn] = {}


def job(name: str):
    def register(fn: JobFn) -> JobFn:
        REGISTRY[name] = fn
        return fn

    return register


async def run(session: AsyncSession, name: str) -> dict:
    fn = REGISTRY[name]
    run_id = (
        await session.execute(
            text("""
        insert into job_runs (job, started_at, status) values (:job, now(), 'RUNNING') returning id"""),
            {"job": name},
        )
    ).scalar_one()
    await session.commit()
    started = time.monotonic()
    try:
        result = await fn(session)
        status, error = "OK", result.note
    except Exception as exc:  # recorded for the Admin page, then re-raised as a 503 by the caller
        await session.rollback()
        log.exception("job %s failed", name)
        result, status, error = JobResult(), "ERROR", f"{type(exc).__name__}: {exc}"[:500]
    await session.execute(
        text("""
        update job_runs set finished_at = now(), status = :status, items = :items, quota_used = :quota, error = :error
        where id = :id"""),
        {"status": status, "items": result.items, "quota": result.quota_used, "error": error, "id": run_id},
    )
    await session.commit()
    return {
        "job": name,
        "status": status,
        "items": result.items,
        "quota_used": result.quota_used,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error": error,
    }
