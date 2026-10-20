"""Run one scheduled job locally, the same way the cron endpoint does (job_runs is recorded).

    .venv\\Scripts\\python scripts\\run_job.py weather|warnings|forecast|flood|news|traffic|priority|cleanup
"""

import asyncio
import json
import sys

import common  # noqa: F401  (puts server/ on the path)
from app import ingest
from app.core import db
from app.ingest import maintenance, news, weather  # noqa: F401  (registers the jobs)


async def main(name: str) -> None:
    db.get_engine()
    async with db._sessionmaker() as session:
        print(json.dumps(await ingest.run(session, name), indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ingest.REGISTRY:
        sys.exit(f"usage: run_job.py {{{'|'.join(sorted(ingest.REGISTRY))}}}")
    asyncio.run(main(sys.argv[1]))
