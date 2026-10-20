from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.common import csv_param, parse_bbox
from app.core import db
from app.core.auth import STAFF, CurrentUser, optional_user, require_role
from app.core.db import get_session
from app.queries import incidents
from app.services import scope

router = APIRouter(prefix="/map", tags=["map"])

MAX_INCIDENTS = 2000
MAX_SEGMENTS = 6000
ENVELOPE = "ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"


def _box(bbox: str) -> dict:
    minx, miny, maxx, maxy = parse_bbox(bbox)
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


@router.get("/incidents")
async def map_incidents(
    bbox: str,
    types: str | None = None,
    status: str | None = None,
    source: str | None = None,
    road_class: str | None = None,
    since: date | None = None,
    include_synthetic: bool = True,
    user: CurrentUser | None = Depends(optional_user),
    session: AsyncSession = Depends(get_session),
):
    """Current view (FR-MAP-02). Anyone can call it; staff get officer fields, within their scope."""
    staff = bool(user and user.is_staff)
    sc = await scope.for_user(session, user) if staff else scope.Scope()
    where, params = [f"i.geom && {ENVELOPE}", sc.incidents_sql()], {**_box(bbox), **sc.params}
    status_f = csv_param(status)
    if status_f:
        where.append("i.status = any(:statuses)")
        params["statuses"] = sorted(status_f)
    else:
        where.append(incidents.OPEN_SQL)
    for name, column, value in (
        ("types", "i.hazard_type", types),
        ("sources", "i.source", source),
        ("classes", "s.road_class", road_class),
    ):
        if csv_param(value):
            where.append(f"{column} = any(:{name})")
            params[name] = sorted(csv_param(value))
    if since:
        where.append("i.reported_at >= :since")
        params["since"] = since
    if not include_synthetic:
        where.append("not i.is_synthetic")
    found = await db.rows(
        session,
        f"""
        select {incidents.SELECT} {incidents.FROM}
        where {" and ".join(where)}
        order by i.reported_at desc limit {MAX_INCIDENTS + 1}""",
        **params,
    )
    truncated = len(found) > MAX_INCIDENTS
    role = user.role if user else "public"
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
            "properties": incidents.view(r, staff, role),
        }
        for r in found[:MAX_INCIDENTS]
    ]
    return {"type": "FeatureCollection", "features": features, "meta": {"count": len(features), "truncated": truncated}}


def _segment_filter(zoom: int) -> tuple[str, float]:
    """Fewer, simpler lines when zoomed out, so the map stays under the 500 ms target (NFR-02)."""
    tolerance = 0 if zoom >= 15 else 360 / (256 * 2**zoom)  # about one pixel, in degrees
    if zoom < 9:
        return "s.road_class in ('EXPRESSWAY', 'FEDERAL')", tolerance
    if zoom < 12:
        return "s.road_class in ('EXPRESSWAY', 'FEDERAL', 'STATE')", tolerance
    return "true", tolerance


@router.get("/segments")
async def map_segments(
    bbox: str,
    zoom: int = Query(default=13, ge=0, le=22),
    user: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    """The road layer with class and owner (T2.3). GeoJSON is built in Postgres, not in Python."""
    sc = await scope.for_user(session, user)
    class_sql, tolerance = _segment_filter(zoom)
    body = await db.scalar(
        session,
        f"""
        with q as (
            select s.id, s.name, s.ref, s.road_class, d.name as district, o.name as owner, m.name as maintainer,
                   ST_SimplifyPreserveTopology(s.geom, :tol) as g
            from road_segments s
            left join jurisdiction_overrides jo on jo.segment_id = s.id
            left join districts d on d.id = s.district_id
            left join agencies o on o.id = coalesce(jo.owner_agency_id, s.owner_agency_id)
            left join agencies m on m.id = coalesce(jo.maintainer_agency_id, s.maintainer_agency_id)
            where s.geom && {ENVELOPE} and {class_sql} and {sc.sql}
            limit {MAX_SEGMENTS + 1}
        )
        select json_build_object(
            'type', 'FeatureCollection',
            'features', coalesce(json_agg(json_build_object(
                'type', 'Feature', 'geometry', ST_AsGeoJSON(g, 6)::json,
                'properties', json_build_object('segment_id', id, 'name', name, 'ref', ref, 'road_class', road_class,
                                                'district', district, 'owner', owner, 'maintainer', maintainer)
            )) filter (where rn <= {MAX_SEGMENTS}), '[]'::json),
            'meta', json_build_object('count', least(count(*), {MAX_SEGMENTS}), 'truncated', count(*) > {MAX_SEGMENTS})
        )::text
        from (select *, row_number() over () as rn from q) numbered""",
        tol=tolerance,
        **_box(bbox),
        **sc.params,
    )
    return db.json_response(body)


@router.get("/predictions")
async def map_predictions(
    bbox: str,
    types: str | None = None,
    horizon: int = Query(default=7),
    min_level: str = "MEDIUM",
    user: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    """Prediction view (FR-MAP-03): segments coloured by hazard, width by probability."""
    from app.services.domain import RISK_LEVELS

    sc = await scope.for_user(session, user)
    levels = list(RISK_LEVELS)
    allowed = levels[levels.index(min_level) :] if min_level in levels else levels[1:]
    where, params = (
        [f"s.geom && {ENVELOPE}", sc.sql, "p.horizon_days = :horizon", "p.risk_level = any(:levels)"],
        {**_box(bbox), **sc.params, "horizon": 30 if horizon == 30 else 7, "levels": allowed},
    )
    if csv_param(types):
        where.append("p.hazard_type = any(:types)")
        params["types"] = sorted(csv_param(types))
    body = await db.scalar(
        session,
        f"""
        with q as (
            select p.*, s.name, s.geom, coalesce(mv.synthetic_share, 1) >= 0.5 as demo
            from predictions p
            join road_segments s on s.id = p.segment_id
            left join model_versions mv on mv.version = p.model_version
            where {" and ".join(where)}
            order by p.probability desc
            limit {MAX_SEGMENTS}
        )
        select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
            'type', 'Feature', 'geometry', ST_AsGeoJSON(geom, 6)::json,
            'properties', json_build_object(
                'segment_id', segment_id, 'name', name, 'hazard_type', hazard_type, 'horizon_days', horizon_days,
                'probability', round(probability::numeric, 3), 'risk_level', risk_level, 'top_factors', expand_factors(top_factors),
                'model_version', model_version, 'trained_on_demo_data', demo)
        )), '[]'::json))::text
        from q""",
        **params,
    )
    return db.json_response(body)


@router.get("/layers/warnings")
async def warnings_layer(session: AsyncSession = Depends(get_session)):
    """Active weather and flood warnings (FR-MAP-05). Public, no personal data."""
    body = await db.scalar(
        session,
        """
        select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(json_build_object(
            'type', 'Feature', 'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(w.geom, 0.002), 5)::json,
            'properties', json_build_object('id', w.id, 'kind', w.kind, 'severity', w.severity,
                                            'area', w.area_text, 'valid_from', w.valid_from, 'valid_to', w.valid_to)
        )) filter (where w.geom is not null), '[]'::json),
        'meta', json_build_object('updated_at', (select max(finished_at) from job_runs
                                                 where job in ('warnings', 'flood') and status = 'OK')))::text
        from weather_warnings w
        where now() between coalesce(w.valid_from, now()) and coalesce(w.valid_to, now())""",
    )
    return db.json_response(body)
