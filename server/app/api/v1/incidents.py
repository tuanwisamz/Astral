from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.common import csv_param
from app.core import db
from app.core.auth import STAFF, CurrentUser, require_role
from app.core.db import get_session
from app.core.errors import ApiError
from app.queries import incidents, segments
from app.services import scope, storage

router = APIRouter(prefix="/incidents", tags=["incidents"])

SORTS = {
    "-reported_at": "i.reported_at desc",
    "-severity": "i.severity desc, i.reported_at desc",
    "sla_due_at": "coalesce(i.sla_temp_due_at, i.sla_perm_due_at) asc nulls last",
}


class IncidentPatch(BaseModel):
    status: str | None = None
    severity: int | None = Field(default=None, ge=1, le=5)
    assigned_agency_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class IncidentCreate(BaseModel):
    hazard_type: str = Field(pattern="^(POTHOLE|FALLEN_TREE|SINKHOLE)$")
    severity: int = Field(ge=1, le=5)
    lat: float
    lng: float
    description: str | None = Field(default=None, max_length=2000)


class MergeRequest(BaseModel):
    into_id: str


@router.get("")
async def list_incidents(
    state: str | None = None,
    district: str | None = None,
    types: str | None = None,
    status: str | None = None,
    source: str | None = None,
    road_class: str | None = None,
    owner_agency_id: str | None = None,
    sla_overdue: bool | None = None,
    since: date | None = None,
    until: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    sort: str = "-reported_at",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1),
    user: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    sc = await scope.for_user(session, user)
    req_sql, req_params = scope.requested(state, district, road_class, owner_agency_id)
    where, params = [sc.incidents_sql(), req_sql], {**sc.params, **req_params}
    for name, column, value in (
        ("types", "i.hazard_type", types),
        ("statuses", "i.status", status),
        ("sources", "i.source", source),
    ):
        if csv_param(value):
            where.append(f"{column} = any(:{name})")
            params[name] = sorted(csv_param(value))
    if sla_overdue is not None:
        where.append(f"{'' if sla_overdue else 'not '}({incidents.OPEN_SQL} and {incidents.OVERDUE_SQL})")
    if since:
        where.append("i.reported_at >= :since")
        params["since"] = since
    if until:
        where.append("i.reported_at < cast(:until as date) + 1")
        params["until"] = until
    if q:
        where.append("(i.ref_no ilike :q or s.name ilike :q or s.ref ilike :q)")
        params["q"] = f"%{q.strip()}%"
    page_size = min(page_size, 200)
    sql_where = " and ".join(where)
    total = await db.scalar(session, f"select count(*) {incidents.FROM} where {sql_where}", **params)
    found = await db.rows(
        session,
        f"""
        select {incidents.SELECT} {incidents.FROM} where {sql_where}
        order by {SORTS.get(sort, SORTS["-reported_at"])}
        limit :limit offset :offset""",
        limit=page_size,
        offset=(page - 1) * page_size,
        **params,
    )
    return {
        "items": [incidents.view(r, True, user.role) for r in found],
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


@router.post("", status_code=201)
async def create_incident(
    body: IncidentCreate,
    user: CurrentUser = Depends(require_role("officer", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """An officer logs a hazard directly (source OFFICER); it starts verified."""
    seg, _ = await segments.nearest(session, body.lat, body.lng)
    sc = await scope.for_user(session, user)
    await scope.ensure_segment_in_scope(session, sc, seg["segment_id"])
    created = await incidents.create(
        session,
        hazard_type=body.hazard_type,
        severity=body.severity,
        lat=body.lat,
        lng=body.lng,
        segment=seg,
        source="OFFICER",
        actor=user.clerk_id,
        description=body.description,
        status="VERIFIED",
    )
    await session.commit()
    return incidents.view(await incidents.get(session, created["id"]), True, user.role)


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    sc = await scope.for_user(session, user)
    return incidents.view(await incidents.get(session, incident_id, sc.incidents_sql(), **sc.params), True, user.role)


@router.patch("/{incident_id}")
async def patch_incident(
    incident_id: str,
    body: IncidentPatch,
    user: CurrentUser = Depends(require_role("officer", "admin")),
    session: AsyncSession = Depends(get_session),
):
    sc = await scope.for_user(session, user)
    inc = await incidents.get(session, incident_id, sc.incidents_sql(), for_update=True, **sc.params)
    await incidents.change(
        session,
        inc,
        user,
        status=body.status,
        severity=body.severity,
        assigned_agency_id=body.assigned_agency_id,
        note=body.note,
    )
    await session.commit()
    return incidents.view(await incidents.get(session, incident_id), True, user.role)


@router.post("/{incident_id}/undo")
async def undo(
    incident_id: str,
    user: CurrentUser = Depends(require_role("officer", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """Reverts your own status change within 10 seconds (spec §9.1, plan §6)."""
    sc = await scope.for_user(session, user)
    inc = await incidents.get(session, incident_id, sc.incidents_sql(), for_update=True, **sc.params)
    await incidents.undo(session, inc, user)
    await session.commit()
    return incidents.view(await incidents.get(session, incident_id), True, user.role)


@router.post("/{incident_id}/merge")
async def merge(
    incident_id: str,
    body: MergeRequest,
    user: CurrentUser = Depends(require_role("officer", "admin")),
    session: AsyncSession = Depends(get_session),
):
    sc = await scope.for_user(session, user)
    inc = await incidents.get(session, incident_id, sc.incidents_sql(), for_update=True, **sc.params)
    try:
        primary = await incidents.get(session, body.into_id, sc.incidents_sql(), for_update=True, **sc.params)
    except ApiError as exc:
        raise ApiError(422, "VALIDATION_ERROR", "The incident to merge into wasn't found in your area") from exc
    await incidents.merge(session, inc, primary, user)
    await session.commit()
    return incidents.view(await incidents.get(session, body.into_id), True, user.role)


@router.get("/{incident_id}/photo")
async def photo(
    incident_id: str, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    """A 10-minute signed link to the report photo. Photos are for officers only (NFR-03)."""
    sc = await scope.for_user(session, user)
    inc = await incidents.get(session, incident_id, sc.incidents_sql(), **sc.params)
    if not inc["photo_path"]:
        raise ApiError(404, "NOT_FOUND", "This incident has no photo")
    return {"url": await storage.signed_url(inc["photo_path"]), "expires_in": storage.SIGNED_URL_SECONDS}


@router.get("/{incident_id}/events")
async def events(
    incident_id: str, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    sc = await scope.for_user(session, user)
    await incidents.get(session, incident_id, sc.incidents_sql(), **sc.params)
    return {"items": await incidents.events(session, incident_id, public=False)}
