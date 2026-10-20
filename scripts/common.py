"""Shared paths, areas and database access for the loader scripts.

Run scripts from the repo root:  .venv\\Scripts\\python scripts\\<name>.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PBF = RAW / "malaysia-singapore-brunei-latest.osm.pbf"

# The loaders share classification rules with the API (plan §3 M2: one implementation).
sys.path.insert(0, str(ROOT / "server"))

# Metric CRS for lengths and cutting (plan M2): GDM2000 / Peninsula RSO.
METRIC_CRS = "EPSG:3375"
WGS84 = "EPSG:4326"

# Rough Peninsular Malaysia box; the state polygons make the exact cut.
PENINSULA_BBOX = (99.5, 1.15, 104.65, 6.75)

# Pilot areas get every road class (spec §4). Boxes are generous; district polygons clip them.
PILOT_BBOXES = {
    "Kinta": (100.95, 4.35, 101.30, 4.85),
    "Kuala Lumpur": (101.58, 3.02, 101.77, 3.25),
}

ROAD_HIGHWAYS = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "service", "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link",
}
MAJOR_HIGHWAYS = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}


def in_box(lon: float, lat: float, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= lon <= box[2] and box[1] <= lat <= box[3]


def in_pilot(lon: float, lat: float) -> bool:
    return any(in_box(lon, lat, b) for b in PILOT_BBOXES.values())


def sync_dsn() -> str:
    """psycopg wants a plain postgresql:// URL; the API's setting uses the asyncpg dialect."""
    from app.core.config import get_settings

    url = get_settings().database_url
    if not url:
        raise SystemExit("DATABASE_URL is not set in server/.env")
    return url.replace("postgresql+asyncpg://", "postgresql://")
