"""T5.2 backfill, moved to M2 by the plan: 12 months of daily rain and wind for the pilot cells
(the synthetic generator and the models need history), then today's forecast for every cell.

    .venv\\Scripts\\python scripts\\backfill_weather.py
"""

import asyncio
from datetime import date, timedelta

import common  # noqa: F401  (puts server/ on the path)
from app.core import db
from app.ingest import weather
from app.services import usage

PILOTS = [("A", "Kinta"), ("KUL", "Kuala Lumpur")]
ARCHIVE_LAG_DAYS = 6  # the archive trails real time by a few days; past_days covers the gap


async def main() -> None:
    db.get_engine()
    async with db._sessionmaker() as session:
        cells = [r["cell_id"] for r in await db.rows(session, """
            select distinct s.cell_id from road_segments s join districts d on d.id = s.district_id
            where (d.state_code, d.name) in (('A', 'Kinta'), ('KUL', 'Kuala Lumpur')) order by 1""")]
        end = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
        start = end - timedelta(days=365)
        print(f"archive {start}..{end} for {len(cells)} pilot cells")
        rows = await weather.fetch_cells(cells, archive=(start, end))
        await weather.save_weather(session, rows)
        # A year per location counts as many calls (about 26 per location per year).
        await usage.bump(session, "open_meteo", by=len(cells) * 26)
        await session.commit()
        print(f"stored {len(rows):,} cell-days of history")
        result = await weather.weather(session)
        print(f"forecast run: {result.items:,} cell-days for all cells, {result.quota_used} calls")


if __name__ == "__main__":
    asyncio.run(main())
