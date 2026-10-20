"""Shared by the synthetic generator and the ML jobs: a sync psycopg connection and pilot data
loaders. These run in GitHub Actions or locally, never inside the API process (plan D2)."""

import pandas as pd
import psycopg

from app.core.config import get_settings

PILOT_DISTRICTS = (("A", "Kinta"), ("KUL", "Kuala Lumpur"))


def connect() -> psycopg.Connection:
    url = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    return psycopg.connect(url, prepare_threshold=None)


def frame(conn: psycopg.Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def pilot_segments(conn: psycopg.Connection) -> pd.DataFrame:
    return frame(
        conn,
        """
        select s.id, s.road_class, s.name, s.ref, s.length_m::float as length_m, s.adt, s.heavy_pct::float as heavy_pct,
               s.karst, s.ex_mining, coalesce(s.tree_cover, 0)::float as tree_cover, s.criticality::float as criticality,
               s.cell_id, s.osm_highway, s.surface, coalesce(s.lanes, 0) as lanes, d.name as district, s.state_code
        from road_segments s join districts d on d.id = s.district_id
        where (d.state_code, d.name) in (('A', 'Kinta'), ('KUL', 'Kuala Lumpur'))""",
    )


def weather(conn: psycopg.Connection, cells: list[str]) -> pd.DataFrame:
    w = frame(
        conn,
        """
        select cell_id, date, rain_mm::float as rain, rain_max_hr::float as rain_hr, gust_max_kmh::float as gust,
               is_forecast
        from weather_daily where cell_id = any(%(cells)s) order by cell_id, date""",
        {"cells": cells},
    )
    w["date"] = pd.to_datetime(w["date"])
    return w
