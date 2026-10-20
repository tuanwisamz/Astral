"""Road segment lookups (T2.5): locate, search, detail. All geometry work happens in PostGIS."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.errors import ApiError

MAX_ROAD_DISTANCE_M = 50
NOT_ON_ROAD = "No mapped road within 50 m. Reporting covers all roads in Kinta and KL, main roads elsewhere."

# One segment with everything a drawer or a report needs: names of its owner and maintainer,
# its district and state. Joined once here so every endpoint returns the same shape.
SEGMENT_SELECT = """
    s.id as segment_id, s.name, s.ref, s.road_class, s.federal_category, s.osm_highway, s.surface,
    s.lanes, s.length_m, s.adt, s.heavy_pct, s.adt_source, s.karst, s.ex_mining, s.tree_cover,
    s.criticality, s.jurisdiction_source, s.state_code, st.name as state_name, s.district_id,
    d.name as district, o.id as owner_id, o.name as owner, o.type as owner_type, o.contact as owner_contact,
    m.id as maintainer_id, m.name as maintainer, m.type as maintainer_type,
    m.last_verified as maintainer_last_verified, m.contract_valid_to as maintainer_contract_valid_to
"""
SEGMENT_JOINS = """
    left join states st on st.code = s.state_code
    left join districts d on d.id = s.district_id
    left join agencies o on o.id = coalesce(jo.owner_agency_id, s.owner_agency_id)
    left join agencies m on m.id = coalesce(jo.maintainer_agency_id, s.maintainer_agency_id)
"""
# Officer corrections always win (architechture.md §7 step 5).
OVERRIDES = "left join jurisdiction_overrides jo on jo.segment_id = s.id"


def summary(r: dict) -> dict:
    return {
        "segment_id": r["segment_id"],
        "name": r["name"],
        "ref": r["ref"],
        "road_class": r["road_class"],
        "federal_category": r["federal_category"],
        "district": r["district"],
        "state": {"code": r["state_code"], "name": r["state_name"]},
        "owner": r["owner"],
        "maintainer": r["maintainer"],
        "length_km": round(float(r["length_m"] or 0) / 1000, 2),
    }


async def in_coverage(session: AsyncSession, lat: float, lng: float) -> bool:
    return bool(
        await db.scalar(
            session,
            "select exists(select 1 from states where geom is not null and "
            "ST_Intersects(geom, ST_SetSRID(ST_Point(:lng, :lat), 4326)))",
            lat=lat,
            lng=lng,
        )
    )


async def nearest(session: AsyncSession, lat: float, lng: float) -> tuple[dict, float]:
    """Nearest segment by KNN on the GiST index, then the true distance in metres.
    Raises OUTSIDE_COVERAGE or NOT_ON_ROAD (spec FR-REP-02)."""
    if not await in_coverage(session, lat, lng):
        raise ApiError(422, "OUTSIDE_COVERAGE", "This location is outside Peninsular Malaysia")
    found = await db.row(
        session,
        f"""
        with pt as (select ST_SetSRID(ST_Point(:lng, :lat), 4326) as g)
        select {SEGMENT_SELECT},
               ST_Distance(s.geom::geography, pt.g::geography) as distance_m
        from pt, road_segments s {OVERRIDES} {SEGMENT_JOINS}
        order by s.geom <-> pt.g
        limit 1""",
        lat=lat,
        lng=lng,
    )
    if found is None or found["distance_m"] > MAX_ROAD_DISTANCE_M:
        distance = None if found is None else round(found["distance_m"])
        raise ApiError(422, "NOT_ON_ROAD", NOT_ON_ROAD, {"distance_m": distance})
    return found, float(found["distance_m"])


async def get(session: AsyncSession, segment_id: int, scope_sql: str = "true", **scope_params) -> dict:
    found = await db.row(
        session,
        f"""
        select {SEGMENT_SELECT}, ST_AsGeoJSON(s.geom, 6)::json as geometry
        from road_segments s {OVERRIDES} {SEGMENT_JOINS}
        where s.id = :sid and {scope_sql}""",
        sid=segment_id,
        **scope_params,
    )
    if found is None:
        raise ApiError(404, "NOT_FOUND", f"Road segment {segment_id} not found, or outside your area")
    return found


async def search(session: AsyncSession, q: str, scope_sql: str, limit: int, **params) -> list[dict]:
    """Roads by name or route number. Segments of one road in one district are grouped, so
    "Jalan Gopeng" comes back once per district, not once per kilometre."""
    term = q.strip()
    ref_term = term.upper().replace(" ", "")
    ref_bare = ref_term[2:] if ref_term.startswith("FT") else ref_term
    return await db.rows(
        session,
        f"""
        select min(s.id) as segment_id, s.name, s.ref, s.road_class, d.name as district,
               st.name as state_name, s.state_code, count(*) as segments,
               round(sum(s.length_m)::numeric / 1000, 1) as length_km,
               min(o.name) as owner
        from road_segments s
        left join districts d on d.id = s.district_id
        left join states st on st.code = s.state_code
        left join agencies o on o.id = s.owner_agency_id
        where ({scope_sql})
          and (s.name ilike :pattern
               or upper(replace(coalesce(s.ref, ''), ' ', '')) in (:ref_term, :ref_bare, 'FT' || :ref_bare))
        group by s.name, s.ref, s.road_class, d.name, st.name, s.state_code
        order by (upper(coalesce(s.ref, '')) in (:ref_term, :ref_bare)) desc,
                 (s.name ilike :prefix) desc, sum(s.length_m) desc
        limit :limit""",
        pattern=f"%{term}%",
        prefix=f"{term}%",
        ref_term=ref_term,
        ref_bare=ref_bare,
        limit=limit,
        **params,
    )
