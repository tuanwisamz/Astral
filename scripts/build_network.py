"""T1.2–T1.6: boundaries, agencies, road segments and their enrichment → Supabase.

Reads the GeoParquet files written by extract_osm.py and data/geology.geojson, then replaces
states' geometry, districts, agencies, zones (karst / ex-mining) and road_segments.

    .venv\\Scripts\\python scripts\\build_network.py [--dry-run] [--force]

--force is needed if the database already holds real (non-synthetic) incidents, because
reloading segments cascades into incidents.
"""

import argparse
import math
import time
import uuid
from collections import Counter

import geopandas as gpd
import pandas as pd
import psycopg
import shapely
from shapely.ops import substring

from common import DATA, METRIC_CRS, RAW, WGS84, sync_dsn
from app.services.jurisdiction import (  # noqa: E402  (path set up by common)
    classify,
    jkr_district_key,
    jkr_state_key,
    responsible,
)

NS = uuid.UUID("5a2e1d1c-6a4b-4c1e-9f0e-1b2a3c4d5e6f")
ISO_TO_STATE = {
    "MY-01": "J", "MY-02": "K", "MY-03": "D", "MY-04": "M", "MY-05": "N", "MY-06": "C", "MY-07": "P",
    "MY-08": "A", "MY-09": "R", "MY-10": "B", "MY-11": "T", "MY-14": "KUL", "MY-16": "PJY",
}
STATE_NAMES = {
    "R": "Perlis", "K": "Kedah", "P": "Pulau Pinang", "A": "Perak", "B": "Selangor", "C": "Pahang",
    "T": "Terengganu", "D": "Kelantan", "J": "Johor", "M": "Melaka", "N": "Negeri Sembilan",
    "KUL": "Kuala Lumpur", "PJY": "Putrajaya",
}
PILOT_DISTRICTS = {("A", "Kinta"), ("KUL", "Kuala Lumpur")}
MAX_SEGMENT_M = 1000
HIGHWAY_RANK = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
                "living_street", "service"]

# Assumed ADT where no RTVM census station applies (T1.7). Labelled CLASS_DEFAULT, so the
# priority engine marks usage as estimated.
CLASS_ADT = {"EXPRESSWAY": (40000, 0.15), "FEDERAL": (20000, 0.20), "STATE": (8000, 0.12),
             "MUNICIPAL": (3000, 0.05), "UNKNOWN": (3000, 0.05)}
CLASS_CRITICALITY = {"EXPRESSWAY": 0.6, "FEDERAL": 0.6, "STATE": 0.4, "MUNICIPAL": 0.2, "UNKNOWN": 0.2}


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --- boundaries -----------------------------------------------------------------------------

def load_boundaries():
    b = gpd.read_parquet(RAW / "boundaries.parquet")
    states = b[(b.admin_level == 4) & b.iso.isin(ISO_TO_STATE)].copy()
    states["code"] = states.iso.map(ISO_TO_STATE)
    states = states.dissolve(by="code", as_index=False)[["code", "geometry"]]

    lvl6 = b[(b.admin_level == 6) & b.name.notna()].copy()
    lvl6["pt"] = lvl6.representative_point()
    lvl6 = gpd.sjoin(lvl6.set_geometry("pt"), states, predicate="within").set_geometry("geometry")
    districts = lvl6.dissolve(by=["code", "name"], as_index=False)[["code", "name", "geometry"]]
    # Kuala Lumpur and Putrajaya have no level-6 districts: each territory is its own district.
    ft = states[states.code.isin(["KUL", "PJY"])].copy()
    ft["name"] = ft.code.map(STATE_NAMES)
    districts = pd.concat([districts[~districts.code.isin(["KUL", "PJY"])], ft[["code", "name", "geometry"]]],
                          ignore_index=True)
    districts = gpd.GeoDataFrame(districts, geometry="geometry", crs=WGS84)
    districts["id"] = [uid(f"district:{c}:{n}") for c, n in zip(districts.code, districts.name)]

    councils = b[(b.admin_level == 7) & b.name.fillna("").str.match(r"^(Majlis|Dewan Bandaraya|Perbadanan)")]
    return states, districts, councils


# --- agencies -------------------------------------------------------------------------------

def build_agencies(states, districts, councils, operators: set[str]):
    rows = []

    def add(key, type_, name, state=None, parent=None, geom=None, **extra):
        rows.append({"key": key, "id": uid(f"agency:{key}"), "type": type_, "name": name, "state_code": state,
                     "parent_id": uid(f"agency:{parent}") if parent else None, "geometry": geom, **extra})

    add("JKR_HQ", "JKR_HQ", "JKR Malaysia (HQ)")
    for code in states.code:
        name = f"JKR Wilayah Persekutuan {STATE_NAMES[code]}" if code in ("KUL", "PJY") else f"JKR Negeri {STATE_NAMES[code]}"
        add(jkr_state_key(code), "JKR_STATE", name, code, "JKR_HQ")
    for d in districts.itertuples():
        key = jkr_district_key(d.code, d.name)
        if key.startswith("JKR_DISTRICT"):
            add(key, "JKR_DISTRICT", f"JKR Daerah {d.name}", d.code, jkr_state_key(d.code))

    # Federal maintenance concessionaires (spec §2). Contracts are in transition in 2026, so
    # none is marked verified; an admin confirms them (§5.10).
    add("FED_MAINT:NORTH", "FED_MAINT_CONCESSIONAIRE", "Belati Wangsa (M) Sdn Bhd")
    add("FED_MAINT:CENTRAL_EAST", "FED_MAINT_CONCESSIONAIRE", "Roadcare (M) Sdn Bhd", contract_valid_to="2027-02-16")
    add("FED_MAINT:SOUTH", "FED_MAINT_CONCESSIONAIRE", "Selia Selenggara Selatan Sdn Bhd")
    # Open question §9 Q2: nobody has confirmed who maintains federal roads in KL and Putrajaya.
    add("FED_MAINT:FT", "FED_MAINT_CONCESSIONAIRE", "Federal road maintainer, KL and Putrajaya (to be confirmed)")

    add("LLM", "LLM", "Lembaga Lebuhraya Malaysia")
    add("JMG", "JMG", "Jabatan Mineral dan Geosains Malaysia")
    add("EXPRESSWAY:UNKNOWN", "EXPRESSWAY_CONCESSIONAIRE", "Expressway concessionaire (not recorded)")
    for op in sorted(operators):
        add(f"EXPRESSWAY:{op}", "EXPRESSWAY_CONCESSIONAIRE", op)

    # Councils (PBT) with polygons, for municipal roads in the pilots.
    kinta = districts[(districts.code == "A") & (districts.name == "Kinta")].geometry.iloc[0]
    for c in councils.itertuples():
        add(f"PBT:{c.name}", "PBT", c.name, None, None, c.geometry)
    kl = states[states.code == "KUL"].geometry.iloc[0]
    pjy = states[states.code == "PJY"].geometry.iloc[0]
    add("PBT:Dewan Bandaraya Kuala Lumpur", "PBT", "Dewan Bandaraya Kuala Lumpur", "KUL", None, kl)
    add("PBT:Perbadanan Putrajaya", "PBT", "Perbadanan Putrajaya", "PJY", None, pjy)
    # OSM has no polygon for Majlis Daerah Batu Gajah; plan §6 assumes it covers the rest of Kinta.
    mbi = councils[councils.name == "Majlis Bandaraya Ipoh"]
    if len(mbi):
        rest = kinta.difference(mbi.geometry.union_all())
        add("PBT:Majlis Daerah Batu Gajah", "PBT", "Majlis Daerah Batu Gajah", "A", None, rest,
            contact={"note": "Area derived as Kinta district minus MB Ipoh; confirm the boundary"})

    agencies = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
    for col in ("contract_valid_to", "contact"):
        if col not in agencies:
            agencies[col] = None
    return agencies


# --- segments -------------------------------------------------------------------------------

def cut(line, max_len=MAX_SEGMENT_M):
    n = max(1, math.ceil(line.length / max_len))
    if n == 1:
        return [line]
    step = line.length / n
    return [substring(line, i * step, (i + 1) * step) for i in range(n)]


def authoritative_ref(ref: str | None) -> str:
    """The ref value classify() would pick, used to group ways of the same route."""
    best = classify(ref, None)
    return best.ref or "" if best.source == "REF_TAG" else ""


def build_segments(districts):
    roads = gpd.read_parquet(RAW / "roads.parquet")
    log(f"roads in: {len(roads):,}")
    pieces = gpd.overlay(roads, districts[["code", "name", "id", "geometry"]].rename(
        columns={"name": "district", "id": "district_id"}), how="intersection", keep_geom_type=True)
    pieces = pieces.explode(index_parts=False)
    log(f"pieces after cutting at district borders: {len(pieces):,}")

    pieces["route"] = pieces.ref.map(authoritative_ref)
    pilot = pieces[["code", "district"]].apply(tuple, axis=1).isin(PILOT_DISTRICTS)
    major = pieces.highway.isin({"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"})
    pieces = pieces[pilot | (pieces.route != "") | major]  # pilot clip: bboxes were generous
    log(f"pieces kept (pilots: all roads; elsewhere: routes and major roads): {len(pieces):,}")

    pieces = pieces.to_crs(METRIC_CRS)
    pieces["base_hw"] = pieces.highway.str.replace("_link", "", regex=False)
    pieces["name_key"] = pieces.name.fillna("")
    # Ways with no ref and no name aren't merged: nothing says they are the same road.
    anon = (pieces.route == "") & (pieces.name_key == "")
    pieces["group"] = pieces.osm_id.astype(str).where(anon, "")

    out = []
    keys = ["code", "district", "district_id", "route", "name_key", "base_hw", "group"]
    for key, grp in pieces.groupby(keys, sort=False, dropna=False):
        code, district, district_id, route, name, base_hw, _ = key
        merged = shapely.line_merge(shapely.union_all(grp.geometry.values))
        parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        refs = grp.ref.dropna()
        ref = refs.mode().iloc[0] if len(refs) else None
        surface = grp.surface.dropna().mode().iloc[0] if grp.surface.notna().any() else None
        lanes = pd.to_numeric(grp.lanes, errors="coerce").max()
        operator = grp.operator.dropna().mode().iloc[0] if grp.operator.notna().any() else None
        osm_ids = sorted(set(int(i) for i in grp.osm_id))
        for part in parts:
            if part.length < 5:  # slivers left by the border cut
                continue
            for seg in cut(part):
                out.append({"code": code, "district": district, "district_id": district_id, "ref": ref,
                            "name": name or None, "osm_highway": base_hw, "surface": surface,
                            "lanes": None if pd.isna(lanes) else int(lanes), "operator": operator,
                            "osm_way_ids": osm_ids, "geometry": seg})
    segs = gpd.GeoDataFrame(out, geometry="geometry", crs=METRIC_CRS)
    segs["length_m"] = segs.length.round(1)
    log(f"segments: {len(segs):,}, total {segs.length_m.sum() / 1000:,.0f} km")
    return segs


# --- enrichment -----------------------------------------------------------------------------

def enrich(segs, agencies, councils_keys):
    cls = [classify(r, h) for r, h in zip(segs.ref, segs.osm_highway)]
    segs["road_class"] = [c.road_class for c in cls]
    segs["federal_category"] = [c.federal_category for c in cls]
    segs["jurisdiction_source"] = [c.source for c in cls]

    # Council containing each municipal segment (pilots only have council polygons).
    # agencies["type"], not agencies.type: on a GeoDataFrame, .type is the geometry type.
    pbts = agencies[(agencies["type"] == "PBT") & agencies.geometry.notna()][["key", "geometry"]].to_crs(METRIC_CRS)
    mid = segs.geometry.interpolate(0.5, normalized=True)
    hit = gpd.sjoin(gpd.GeoDataFrame(geometry=mid, crs=METRIC_CRS), pbts, predicate="within", how="left")
    segs["pbt_key"] = hit.groupby(level=0).key.first().reindex(segs.index)

    op_keys = {k[len("EXPRESSWAY:"):]: k for k in agencies.key if k.startswith("EXPRESSWAY:")}
    ids = dict(zip(agencies.key, agencies.id))
    owners, maintainers = [], []
    for row in segs.itertuples():
        r = responsible(row.road_class, row.code, row.district,
                        row.pbt_key if isinstance(row.pbt_key, str) else None,
                        op_keys.get(row.operator) if isinstance(row.operator, str) else None)
        owners.append(ids[r.owner])
        maintainers.append(ids[r.maintainer])
    segs["owner_agency_id"], segs["maintainer_agency_id"] = owners, maintainers

    adt = segs.road_class.map(lambda c: CLASS_ADT[c][0])
    segs["adt"], segs["heavy_pct"] = adt, segs.road_class.map(lambda c: CLASS_ADT[c][1])
    segs["adt_source"] = "CLASS_DEFAULT"

    geo = gpd.read_file(DATA / "geology.geojson").to_crs(METRIC_CRS)
    for kind in ("karst", "ex_mining"):
        polys = geo[geo.kind == kind].geometry.union_all()
        segs[kind] = segs.intersects(polys)

    # Criticality (T1.6): road class plus hospitals, schools and fire stations within 1 km.
    fac = gpd.read_parquet(RAW / "facilities.parquet").to_crs(METRIC_CRS)
    weights = fac.kind.map({"hospital": 3.0, "fire_station": 2.0, "school": 1.0})
    tree = shapely.STRtree(fac.geometry.values)
    near = tree.query(segs.geometry.values, predicate="dwithin", distance=1000)
    score = pd.Series(weights.values[near[1]]).groupby(near[0]).sum().reindex(range(len(segs)), fill_value=0)
    segs["criticality"] = (0.5 * segs.road_class.map(CLASS_CRITICALITY).values
                           + 0.5 * (score.values / 10).clip(max=1)).round(3)

    # Tree cover (T1.6), pilots only: share of a 30 m buffer covered by trees and woods.
    # Intersect each buffer only with nearby canopy shapes (a spatial index), not one huge union:
    # overlapping trees may double-count a little, so the share is capped at 1.
    trees = gpd.read_parquet(RAW / "trees.parquet").to_crs(METRIC_CRS)
    canopy = shapely.make_valid(trees.geometry.where(trees.kind == "wood", trees.geometry.buffer(5)).values)
    pilot = segs[["code", "district"]].apply(tuple, axis=1).isin(PILOT_DISTRICTS).values
    buf = shapely.buffer(segs.geometry.values[pilot], 30)
    pairs = shapely.STRtree(canopy).query(buf, predicate="intersects")
    covered = pd.Series(shapely.area(shapely.intersection(buf[pairs[0]], canopy[pairs[1]]))).groupby(pairs[0]).sum()
    share = (covered.reindex(range(len(buf)), fill_value=0).values / shapely.area(buf)).clip(max=1).round(3)
    segs["tree_cover"] = None
    segs.loc[pilot, "tree_cover"] = share

    wgs = segs.to_crs(WGS84)
    m = mid.to_crs(WGS84)  # midpoint taken in metres, then expressed in degrees
    segs["cell_id"] = [f"{math.floor(p.y * 10) / 10:.1f}_{math.floor(p.x * 10) / 10:.1f}" for p in m]
    return wgs.assign(**{c: segs[c] for c in segs.columns if c != "geometry"})


# --- load -----------------------------------------------------------------------------------

def ewkt(geom) -> str | None:
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        geom = shapely.MultiPolygon([geom])
    return f"SRID=4326;{geom.wkt}"


def clean(value):
    """pandas turns missing values into NaN; Postgres needs NULL."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def copy_rows(cur, table: str, columns: list[str], rows) -> None:
    with cur.copy(f"copy {table} ({', '.join(columns)}) from stdin") as cp:
        for r in rows:
            cp.write_row([clean(v) for v in r])


def load(states, districts, agencies, segs, geo, force: bool) -> None:
    with psycopg.connect(sync_dsn(), prepare_threshold=None, autocommit=False) as conn, conn.cursor() as cur:
        real = cur.execute("select count(*) from incidents where not is_synthetic").fetchone()[0]
        if real and not force:
            raise SystemExit(f"{real} real incidents exist; reloading would delete them. Use --force.")
        cur.execute("truncate road_segments, districts, agencies, zones restart identity cascade")
        for s in states.itertuples():
            cur.execute("update states set geom = ST_Multi(ST_GeomFromEWKT(%s)) where code = %s", (ewkt(s.geometry), s.code))

        copy_rows(cur, "agencies", ["id", "type", "name", "state_code", "parent_id", "contact", "contract_valid_to",
                                     "last_verified", "geom"],
                  ((a.id, a.type, a.name, a.state_code, a.parent_id,
                    None if a.contact is None or (isinstance(a.contact, float)) else psycopg.types.json.Jsonb(a.contact),
                    a.contract_valid_to, None, ewkt(a.geometry)) for a in agencies.itertuples()))
        jkr = dict(zip(agencies.key, agencies.id))
        copy_rows(cur, "districts", ["id", "state_code", "name", "jkr_district_agency_id", "geom"],
                  ((d.id, d.code, d.name, jkr[jkr_district_key(d.code, d.name)], ewkt(d.geometry))
                   for d in districts.itertuples()))
        copy_rows(cur, "zones", ["type", "name", "state_code", "geom"],
                  ((g.kind.upper(), g.name, None, ewkt(g.geometry)) for g in geo.itertuples()))
        cols = ["osm_way_ids", "name", "ref", "road_class", "federal_category", "osm_highway", "surface", "lanes",
                "state_code", "district_id", "owner_agency_id", "maintainer_agency_id", "jurisdiction_source",
                "length_m", "adt", "heavy_pct", "adt_source", "karst", "ex_mining", "tree_cover", "criticality",
                "cell_id", "geom"]
        copy_rows(cur, "road_segments", cols, (
            ([int(w) for w in s.osm_way_ids], s.name, s.ref, s.road_class, s.federal_category, s.osm_highway,
             s.surface, None if pd.isna(s.lanes) else int(s.lanes),
             s.code, s.district_id, s.owner_agency_id, s.maintainer_agency_id, s.jurisdiction_source, s.length_m,
             int(s.adt), float(s.heavy_pct), s.adt_source, bool(s.karst), bool(s.ex_mining),
             None if s.tree_cover is None or pd.isna(s.tree_cover) else float(s.tree_cover), float(s.criticality),
             s.cell_id, f"SRID=4326;{s.geometry.wkt}") for s in segs.itertuples()))
        conn.commit()
        log("committed; refreshing segment_components")
        cur.execute("refresh materialized view segment_components")
        cur.execute("analyze road_segments")
        conn.commit()
        size = cur.execute("select pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
        log(f"database size now {size}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build everything but don't write to the database")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--use-cache", action="store_true", help="reuse data/raw/segments.parquet from the last build")
    args = ap.parse_args()

    log("boundaries")
    states, districts, councils = load_boundaries()
    log(f"states {len(states)}, districts {len(districts)}, councils with polygons {len(councils)}")
    cached = RAW / "segments.parquet"
    segs = gpd.read_parquet(cached) if args.use_cache else build_segments(districts)
    operators = {o for o, c in zip(segs.operator, segs.ref)
                 if isinstance(o, str) and o and classify(c, None).road_class == "EXPRESSWAY"}
    agencies = build_agencies(states, districts, councils, operators)
    log(f"agencies {len(agencies)}")
    if not args.use_cache:
        segs = enrich(segs, agencies, None)
        segs.to_parquet(cached)

    print(segs.road_class.value_counts().to_string())
    print("pilot municipal owners:", Counter(
        agencies.set_index("id").name.reindex(segs[segs.road_class == "MUNICIPAL"].owner_agency_id)).most_common(6))
    print("karst segments:", int(segs.karst.sum()), " ex-mining:", int(segs.ex_mining.sum()))
    geo = gpd.read_file(DATA / "geology.geojson")
    if args.dry_run:
        log("dry run: wrote data/raw/segments.parquet, database untouched")
        return
    load(states, districts, agencies, segs, geo, args.force)


if __name__ == "__main__":
    main()
