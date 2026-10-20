import csv
import io
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import STAFF, CurrentUser, require_role
from app.core.db import get_session
from app.core.errors import ApiError
from app.queries import incidents
from app.queries import priority as ranking
from app.queries.incidents import iso
from app.services import scope
from app.services.priority import COMPONENTS, normalise_weights

router = APIRouter(tags=["priority", "zones"])

MAX_EXPORT = 500


class SimulateRequest(BaseModel):
    scope: dict = {}
    weights: dict[str, float]
    limit: int = Field(default=20, ge=1, le=200)


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    weights: dict[str, float]
    is_default: bool | None = None


class ZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(default="CUSTOM", pattern="^(CUSTOM|KARST|EX_MINING|FLOOD)$")
    geometry: dict


async def _profile(session: AsyncSession, profile_id: str | None) -> dict:
    if profile_id:
        found = await db.row(
            session,
            "select id::text as id, name, weights from priority_profiles where id = cast(:id as uuid)",
            id=profile_id,
        )
        if found is None:
            raise ApiError(404, "NOT_FOUND", "Weight profile not found")
        return found
    return await ranking.default_profile(session)


async def _ranked(session, user, weights, state, district, road_class, owner_agency_id, limit, offset):
    sc = await scope.for_user(session, user)
    req_sql, req_params = scope.requested(state, district, road_class, owner_agency_id)
    return await ranking.rank(session, weights, sc.sql, req_sql, {**sc.params, **req_params}, limit, offset)


@router.get("/priority")
async def priority(
    state: str | None = None,
    district: str | None = None,
    owner_agency_id: str | None = None,
    road_class: str | None = None,
    profile_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    user: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    profile = await _profile(session, profile_id)
    items, total = await _ranked(
        session, user, profile["weights"], state, district, road_class, owner_agency_id, limit, (page - 1) * limit
    )
    return {
        "profile": {**profile, "weights": normalise_weights(profile["weights"])},
        "items": items,
        "total": total,
        "page": page,
        "page_size": limit,
        "computed_at": iso(datetime.now(UTC)),
    }


@router.post("/priority/simulate")
async def simulate(
    body: SimulateRequest,
    user: CurrentUser = Depends(require_role("officer", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """What-if (FR-PR-04): the same ranking with other weights. Nothing is saved."""
    s = body.scope
    args = (s.get("state"), s.get("district"), s.get("road_class"), s.get("owner_agency_id"))
    weights = normalise_weights(body.weights)
    items, total = await _ranked(session, user, weights, *args, body.limit, 0)
    default = await ranking.default_profile(session)
    # Rank change versus the default profile, for the rows shown.
    base, _ = await _ranked(session, user, default["weights"], *args, 1000, 0)
    base_rank = {b["segment_id"]: b["rank"] for b in base}
    for item in items:
        before = base_rank.get(item["segment_id"])
        item["rank_change"] = None if before is None else before - item["rank"]
    return {
        "profile": {"id": None, "name": "What-if", "weights": weights},
        "items": items,
        "total": total,
        "page": 1,
        "page_size": body.limit,
        "computed_at": iso(datetime.now(UTC)),
    }


@router.get("/priority/profiles")
async def profiles(_: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)):
    return await db.rows(
        session, "select id::text as id, name, weights, is_default from priority_profiles order by name"
    )


@router.put("/priority/profiles/{profile_id}")
async def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    user: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    weights = normalise_weights(body.weights)
    if body.is_default:
        await session.execute(text("update priority_profiles set is_default = false"))
    found = await db.row(
        session,
        """
        update priority_profiles set weights = cast(:w as jsonb), name = coalesce(:name, name),
               is_default = coalesce(:d, is_default)
        where id = cast(:id as uuid)
        returning id::text as id, name, weights, is_default""",
        w=weights,
        name=body.name,
        d=body.is_default,
        id=profile_id,
    )
    if found is None:
        raise ApiError(404, "NOT_FOUND", "Weight profile not found")
    await session.commit()
    return found


@router.get("/priority/export")
async def export(
    format: str = "csv",
    state: str | None = None,
    district: str | None = None,
    road_class: str | None = None,
    profile_id: str | None = None,
    user: CurrentUser = Depends(require_role("officer", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """CSV of the ranking for meetings (FR-PR-05). The printable PDF is the browser's print view."""
    if format != "csv":
        raise ApiError(422, "VALIDATION_ERROR", "Only format=csv is supported; print the page for a PDF")
    profile = await _profile(session, profile_id)
    items, _ = await _ranked(session, user, profile["weights"], state, district, road_class, None, MAX_EXPORT, 0)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "rank",
            "segment_id",
            "road",
            "route",
            "class",
            "district",
            "owner",
            "maintainer",
            "score",
            *[f"{c}_contribution" for c in COMPONENTS],
            "recommended_action",
            "refer_to",
        ]
    )
    for i in items:
        w.writerow(
            [
                i["rank"],
                i["segment_id"],
                i["name"] or "",
                i["ref"] or "",
                i["road_class"],
                i["district"] or "",
                i["owner"] or "",
                i["maintainer"] or "",
                i["score"],
                *[i["components"][c]["contribution"] for c in COMPONENTS],
                i["recommended_action"] or "",
                "; ".join(i["refer_to"]),
            ]
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="priority-{stamp}.csv"'},
    )


# --- zones ------------------------------------------------------------------------------------


@router.get("/zones")
async def zones(
    type: str = "DISTRICT",
    state: str | None = None,
    _: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    """STATE and DISTRICT zones are served from states/districts; special zones from the zones table."""
    if type == "DISTRICT":
        return await db.rows(
            session,
            """
            select d.id::text as id, 'DISTRICT' as type, d.name, d.state_code as state from districts d
            where (cast(:state as text) is null or d.state_code = :state) order by d.state_code, d.name""",
            state=state,
        )
    if type == "STATE":
        return await db.rows(
            session, "select code as id, 'STATE' as type, name, code as state from states order by name"
        )
    return await db.rows(
        session,
        """
        select z.id::text as id, z.type, z.name, z.state_code as state from zones z
        where z.type = :type and (cast(:state as text) is null or z.state_code = :state) order by z.name""",
        type=type,
        state=state,
    )


def _zone_sql(zone_id: str) -> tuple[str, dict]:
    if len(zone_id) <= 3 and zone_id.isalpha():
        return "s.state_code = :zone_state", {"zone_state": zone_id.upper()}
    return (
        "(s.district_id = cast(:zone_id as uuid) or exists(select 1 from zones z where z.id = cast(:zone_id as uuid)"
        " and ST_Intersects(z.geom, s.geom)))"
    ), {"zone_id": zone_id}


async def _zone_summary(session: AsyncSession, user: CurrentUser, zone_id: str) -> dict:
    zone = await db.row(
        session,
        """
        select id::text as id, 'DISTRICT' as type, name, state_code as state from districts where id::text = :id
        union all select id::text, type, name, state_code from zones where id::text = :id
        union all select code, 'STATE', name, code from states where code = upper(:id)""",
        id=zone_id,
    )
    if zone is None:
        raise ApiError(404, "NOT_FOUND", "Zone not found")
    sc = await scope.for_user(session, user)
    zsql, zparams = _zone_sql(zone_id)
    params = {**sc.params, **zparams}
    counts = await db.row(
        session,
        f"""
        select count(*) filter (where i.hazard_type = 'POTHOLE') as pothole,
               count(*) filter (where i.hazard_type = 'FALLEN_TREE') as fallen_tree,
               count(*) filter (where i.hazard_type = 'SINKHOLE') as sinkhole,
               count(*) filter (where {incidents.OVERDUE_SQL}) as overdue
        from incidents i join road_segments s on s.id = i.segment_id
        where {incidents.OPEN_SQL} and {sc.incidents_sql()} and {zsql}""",
        **params,
    )
    high = await db.scalar(
        session,
        f"""
        select count(distinct p.segment_id) from predictions p join road_segments s on s.id = p.segment_id
        where p.horizon_days = 30 and p.risk_level in ('HIGH', 'VERY_HIGH') and {sc.sql} and {zsql}""",
        **params,
    )
    top, total = await ranking.rank(
        session, (await ranking.default_profile(session))["weights"], sc.sql, zsql, params, limit=5
    )
    avg = await db.scalar(
        session,
        f"""
        select count(*) from road_segments s where {sc.sql} and {zsql}""",
        **params,
    )
    agencies = await db.rows(
        session,
        f"""
        select distinct a.name from road_segments s join agencies a on a.id in (s.owner_agency_id, s.maintainer_agency_id)
        where {sc.sql} and {zsql} order by a.name limit 12""",
        **params,
    )
    return {
        "zone": zone,
        "open_incidents": {
            "POTHOLE": counts["pothole"],
            "FALLEN_TREE": counts["fallen_tree"],
            "SINKHOLE": counts["sinkhole"],
        },
        "overdue_sla": counts["overdue"],
        "high_risk_segments": int(high or 0),
        "segments": int(avg or 0),
        "avg_top_priority": round(sum(t["score"] for t in top) / len(top), 1) if top else None,
        "top_roads": [
            {k: t[k] for k in ("segment_id", "name", "ref", "road_class", "owner", "score", "recommended_action")}
            for t in top
        ],
        "agencies": [a["name"] for a in agencies],
    }


@router.get("/zones/compare")
async def compare(
    ids: str, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    zone_ids = [z for z in ids.split(",") if z][:3]
    return [await _zone_summary(session, user, z) for z in zone_ids]


@router.get("/zones/{zone_id}/summary")
async def zone_summary(
    zone_id: str, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    return await _zone_summary(session, user, zone_id)


@router.post("/zones", status_code=201)
async def create_zone(
    body: ZoneCreate, user: CurrentUser = Depends(require_role("admin")), session: AsyncSession = Depends(get_session)
):
    if body.geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise ApiError(422, "VALIDATION_ERROR", "Zone geometry must be a GeoJSON Polygon or MultiPolygon")
    found = await db.row(
        session,
        """
        insert into zones (type, name, geom, created_by)
        values (:type, :name, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)), :by)
        returning id::text as id, type, name""",
        type=body.type,
        name=body.name,
        g=json.dumps(body.geometry),
        by=user.clerk_id,
    )
    await session.commit()
    return found


@router.delete("/zones/{zone_id}", status_code=204)
async def delete_zone(
    zone_id: str, _: CurrentUser = Depends(require_role("admin")), session: AsyncSession = Depends(get_session)
):
    deleted = await db.scalar(
        session, "delete from zones where id = cast(:id as uuid) and type = 'CUSTOM' returning 1", id=zone_id
    )
    if not deleted:
        raise ApiError(404, "NOT_FOUND", "Custom zone not found")
    await session.commit()
