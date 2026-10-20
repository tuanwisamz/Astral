from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import STAFF, CurrentUser, require_role
from app.core.db import get_session
from app.core.errors import ApiError
from app.queries import incidents
from app.queries import priority as ranking
from app.queries.incidents import iso
from app.services import scope
from app.services.domain import HAZARDS, RISK_LEVELS, STATES
from app.services.sla import SLA_RULES

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health():
    return {"status": "ok", "database": await db.ping()}


@router.get("/meta/config")
async def config(session: AsyncSession = Depends(get_session)):
    fresh = await db.row(
        session,
        """
        select (select max(reported_at) from incidents) as incidents,
               (select max(finished_at) from job_runs where job = 'weather' and status = 'OK') as weather,
               (select max(finished_at) from job_runs where job in ('warnings', 'forecast') and status = 'OK') as warnings,
               (select max(trained_at) from model_versions where is_active) as predictions,
               (select max(finished_at) from job_runs where job = 'news' and status = 'OK') as news,
               exists(select 1 from incidents where is_synthetic) or exists(select 1 from accidents where is_synthetic)
                 as synthetic""",
    )
    return {
        "hazards": HAZARDS,
        "sla_rules": SLA_RULES,
        "risk_levels": {k: list(v) for k, v in RISK_LEVELS.items()},
        "data_freshness": {k: iso(fresh[k]) for k in ("incidents", "weather", "warnings", "predictions", "news")},
        "synthetic_data_present": bool(fresh["synthetic"]),
    }


@router.get("/meta/states")
async def states():
    return [{"code": code, "name": name, "federal_zone": zone} for code, (name, zone) in STATES.items()]


@router.get("/meta/districts")
async def districts(state: str, session: AsyncSession = Depends(get_session)):
    if state not in STATES:
        raise ApiError(404, "NOT_FOUND", f"Unknown state code {state}")
    return await db.rows(
        session,
        """
        select id::text as id, name, state_code as state from districts where state_code = :state order by name""",
        state=state,
    )


@router.get("/meta/agencies")
async def agencies(
    type: str | None = None,
    state: str | None = None,
    _: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    """For assigning incidents and picking a viewer's agency."""
    return await db.rows(
        session,
        """
        select id::text as id, type, name, state_code as state from agencies
        where (cast(:type as text) is null or type = :type) and (cast(:state as text) is null or state_code = :state
              or state_code is null)
        order by type, name""",
        type=type,
        state=state,
    )


@router.get("/dashboard/summary")
async def dashboard_summary(
    state: str | None = None,
    district: str | None = None,
    user: CurrentUser = Depends(require_role(*STAFF)),
    session: AsyncSession = Depends(get_session),
):
    """KPIs and the top 5 roads (architechture.md §4.5), within the person's scope and the one they picked."""
    sc = await scope.for_user(session, user)
    req_sql, req_params = scope.requested(state, district)
    params = {**sc.params, **req_params}
    counts = await db.row(
        session,
        f"""
        select count(*) filter (where i.hazard_type = 'POTHOLE') as pothole,
               count(*) filter (where i.hazard_type = 'FALLEN_TREE') as fallen_tree,
               count(*) filter (where i.hazard_type = 'SINKHOLE') as sinkhole,
               count(*) filter (where {incidents.OVERDUE_SQL}) as overdue
        from incidents i join road_segments s on s.id = i.segment_id
        where {incidents.OPEN_SQL} and {sc.incidents_sql()} and {req_sql}""",
        **params,
    )
    area = (
        "(select geom from districts where id = cast(:req_district as uuid))"
        if district
        else "(select geom from states where code = :req_state)"
        if state
        else None
    )
    warnings = await db.scalar(
        session,
        f"""
        select count(*) from weather_warnings w
        where now() between coalesce(w.valid_from, now()) and coalesce(w.valid_to, now())
          {f"and ST_Intersects(w.geom, {area})" if area else ""}""",
        **req_params,
    )
    high = await db.scalar(
        session,
        f"""
        select count(distinct p.segment_id) from predictions p join road_segments s on s.id = p.segment_id
        where p.horizon_days = 30 and p.risk_level in ('HIGH', 'VERY_HIGH') and {sc.sql} and {req_sql}""",
        **params,
    )
    profile = await ranking.default_profile(session)
    top, _ = await ranking.rank(session, profile["weights"], sc.sql, req_sql, params, limit=5)
    names = await db.row(
        session,
        """
        select (select name from states where code = cast(:s as text)) as state,
               (select name from districts where id::text = cast(:d as text)) as district""",
        s=state,
        d=district,
    )
    return {
        "scope": {
            "state": state,
            "state_name": names["state"],
            "district": district,
            "district_name": names["district"],
        },
        "open_incidents": {
            "POTHOLE": counts["pothole"],
            "FALLEN_TREE": counts["fallen_tree"],
            "SINKHOLE": counts["sinkhole"],
        },
        "overdue_sla": counts["overdue"],
        "active_warnings": int(warnings or 0),
        "high_risk_segments": int(high or 0),
        "top_roads": [
            {
                k: t[k]
                for k in (
                    "segment_id",
                    "name",
                    "ref",
                    "road_class",
                    "district",
                    "owner",
                    "maintainer",
                    "score",
                    "recommended_action",
                    "refer_to",
                )
            }
            for t in top
        ],
    }
