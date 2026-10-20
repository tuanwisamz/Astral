import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import ingest
from app.core import db
from app.core.auth import ROLES, STAFF, CurrentUser, mirror_user, require_cron_secret, require_role
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.ingest import maintenance, news, weather  # noqa: F401  (registers the jobs)
from app.queries.incidents import iso
from app.services import clerk, scope, usage
from app.services.domain import STATES

router = APIRouter(tags=["predictions", "admin", "internal"])

SCOPED_ROLES = ("officer", "viewer")
RTVM_COLUMNS = ["station_id", "route_ref", "state_code", "lat", "lng", "year", "adt", "heavy_pct"]
RTVM_MATCH_M = 1000


class UserPatch(BaseModel):
    role: str | None = None
    state_code: str | None = None
    district_id: str | None = None
    agency_id: str | None = None


class AgencyPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    contact: dict | None = None
    contract_valid_to: date | None = None
    last_verified: date | None = None


class OverrideIn(BaseModel):
    segment_id: int
    owner_agency_id: str | None = None
    maintainer_agency_id: str | None = None
    reason: str = Field(min_length=3, max_length=500)


# --- users (spec §5.10) ---------------------------------------------------------------------


@router.get("/admin/users")
async def list_users(
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1),
    _: CurrentUser = Depends(require_role("admin")),
):
    page_size = min(page_size, 200)
    items = await clerk.list_users(q, page_size, (page - 1) * page_size)
    return {"items": items, "page": page, "page_size": page_size}


@router.patch("/admin/users/{clerk_id}")
async def update_user(clerk_id: str, body: UserPatch, _: CurrentUser = Depends(require_role("admin"))):
    changes = body.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] not in ROLES:
        raise ApiError(422, "VALIDATION_ERROR", f"Role must be one of: {', '.join(ROLES)}")
    if changes.get("state_code") and changes["state_code"] not in STATES:
        raise ApiError(422, "VALIDATION_ERROR", f"Unknown state code {changes['state_code']}")
    if changes.get("role") in SCOPED_ROLES and not changes.get("state_code") and not changes.get("agency_id"):
        raise ApiError(422, "VALIDATION_ERROR", "Officers and viewers need a state_code (or, for viewers, an agency)")
    if changes.get("role") in ("public", "admin"):
        # Public reporters and admins have no jurisdiction scope; clear any left over.
        changes = {"state_code": None, "district_id": None, "agency_id": None, **changes}
    if not changes:
        raise ApiError(422, "VALIDATION_ERROR", "Nothing to change")
    user = await clerk.update_scope(clerk_id, changes)
    await mirror_user(
        CurrentUser(**{k: user[k] for k in ("clerk_id", "role", "state_code", "district_id", "agency_id")})
    )
    return user


# --- predictions (T6.4) ---------------------------------------------------------------------


@router.get("/predictions/segments/{segment_id}")
async def segment_predictions(
    segment_id: int, user: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)
):
    sc = await scope.for_user(session, user)
    await scope.ensure_segment_in_scope(session, sc, segment_id)
    items = await db.rows(
        session,
        """
        select p.hazard_type, p.horizon_days, round(p.probability::numeric, 3)::float as probability, p.risk_level,
               expand_factors(p.top_factors) as top_factors, p.model_version, p.generated_at, coalesce(mv.synthetic_share, 1) >= 0.5 as trained_on_demo_data
        from predictions p left join model_versions mv on mv.version = p.model_version
        where p.segment_id = :sid order by p.hazard_type, p.horizon_days""",
        sid=segment_id,
    )
    for i in items:
        i["generated_at"] = iso(i["generated_at"])
    return {"segment_id": segment_id, "items": items}


@router.get("/predictions/model-card")
async def model_card(_: CurrentUser = Depends(require_role(*STAFF)), session: AsyncSession = Depends(get_session)):
    models = await db.rows(
        session,
        """
        select hazard_type, version, algorithm, trained_at, training_rows, synthetic_share, metrics, features,
               limitations from model_versions where is_active order by hazard_type""",
    )
    for m in models:
        m["trained_at"] = iso(m["trained_at"])
        m["synthetic_share"] = float(m["synthetic_share"]) if m["synthetic_share"] is not None else None
    return {"models": models}


# --- agencies and jurisdiction (spec §5.10) ----------------------------------------------------


@router.get("/admin/agencies")
async def agencies(
    type: str | None = None,
    _: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    found = await db.rows(
        session,
        """
        select a.id::text as id, a.type, a.name, a.state_code, a.contact, a.contract_valid_to, a.last_verified,
               (select count(*) from road_segments s where s.owner_agency_id = a.id or s.maintainer_agency_id = a.id) as segments
        from agencies a where (cast(:type as text) is null or a.type = :type) order by a.type, a.name""",
        type=type,
    )
    for a in found:
        a["contract_valid_to"] = a["contract_valid_to"].isoformat() if a["contract_valid_to"] else None
        a["last_verified"] = a["last_verified"].isoformat() if a["last_verified"] else None
    return found


@router.patch("/admin/agencies/{agency_id}")
async def update_agency(
    agency_id: str,
    body: AgencyPatch,
    _: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(422, "VALIDATION_ERROR", "Nothing to change")
    sets = ", ".join(f"{k} = :{k}" if k != "contact" else "contact = cast(:contact as jsonb)" for k in changes)
    found = await db.row(
        session,
        f"update agencies set {sets} where id = cast(:id as uuid) returning id::text as id, name",
        id=agency_id,
        **changes,
    )
    if found is None:
        raise ApiError(404, "NOT_FOUND", "Agency not found")
    await session.commit()
    return found


@router.get("/admin/jurisdiction-overrides")
async def overrides(_: CurrentUser = Depends(require_role("admin")), session: AsyncSession = Depends(get_session)):
    found = await db.rows(
        session,
        """
        select jo.segment_id, s.name as road, s.ref, o.name as owner, m.name as maintainer, jo.reason, jo.created_by,
               jo.created_at
        from jurisdiction_overrides jo join road_segments s on s.id = jo.segment_id
        left join agencies o on o.id = jo.owner_agency_id left join agencies m on m.id = jo.maintainer_agency_id
        order by jo.created_at desc""",
    )
    for f in found:
        f["created_at"] = iso(f["created_at"])
    return found


@router.post("/admin/jurisdiction-overrides", status_code=201)
async def add_override(
    body: OverrideIn,
    user: CurrentUser = Depends(require_role("admin", "officer")),
    session: AsyncSession = Depends(get_session),
):
    """Correct a segment's owner or maintainer. Officers may only correct roads in their own area."""
    sc = await scope.for_user(session, user)
    await scope.ensure_segment_in_scope(session, sc, body.segment_id)
    if not body.owner_agency_id and not body.maintainer_agency_id:
        raise ApiError(422, "VALIDATION_ERROR", "Give an owner or a maintainer")
    await session.execute(
        text("""
        insert into jurisdiction_overrides (segment_id, owner_agency_id, maintainer_agency_id, reason, created_by)
        values (:sid, cast(:o as uuid), cast(:m as uuid), :reason, :by)
        on conflict (segment_id) do update set owner_agency_id = excluded.owner_agency_id,
            maintainer_agency_id = excluded.maintainer_agency_id, reason = excluded.reason,
            created_by = excluded.created_by, created_at = now()"""),
        {
            "sid": body.segment_id,
            "o": body.owner_agency_id,
            "m": body.maintainer_agency_id,
            "reason": body.reason,
            "by": user.clerk_id,
        },
    )
    await session.execute(
        text("update road_segments set jurisdiction_source = 'OVERRIDE' where id = :sid"), {"sid": body.segment_id}
    )
    await session.commit()
    return {"segment_id": body.segment_id, "status": "saved"}


# --- RTVM import (T1.7) ---------------------------------------------------------------------


@router.post("/admin/import/rtvm")
async def import_rtvm(
    file: UploadFile = File(...),
    _: CurrentUser = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    """Census stations from the JKR Road Traffic Volume Malaysia report, matched to the nearest
    segment on the same route within 1 km. Unmatched stations are listed for a person to check."""
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames is None or set(RTVM_COLUMNS) - set(reader.fieldnames):
        raise ApiError(422, "VALIDATION_ERROR", f"CSV needs the columns: {', '.join(RTVM_COLUMNS)}")
    rows = list(reader)
    matched, unmatched = 0, []
    for r in rows:
        try:
            lat, lng, adt = float(r["lat"]), float(r["lng"]), int(float(r["adt"]))
            heavy = float(r["heavy_pct"]) / (100 if float(r["heavy_pct"]) > 1 else 1)
        except ValueError:
            unmatched.append({"station_id": r.get("station_id"), "reason": "bad number"})
            continue
        ref = r["route_ref"].upper().replace(" ", "").removeprefix("FT")
        updated = await db.scalar(
            session,
            """
            with target as (
                select s.id from road_segments s
                where upper(replace(coalesce(s.ref, ''), ' ', '')) in (:ref, 'FT' || :ref)
                  and ST_DWithin(s.geom::geography, ST_SetSRID(ST_Point(:lng, :lat), 4326)::geography, :m)
                order by s.geom <-> ST_SetSRID(ST_Point(:lng, :lat), 4326) limit 1)
            update road_segments s set adt = :adt, heavy_pct = :heavy, adt_source = 'RTVM ' || :year
            from target where s.id = target.id returning s.id""",
            ref=ref,
            lat=lat,
            lng=lng,
            m=RTVM_MATCH_M,
            adt=adt,
            heavy=heavy,
            year=r["year"],
        )
        if updated:
            matched += 1
        else:
            unmatched.append({"station_id": r.get("station_id"), "reason": "no segment on this route within 1 km"})
    await session.commit()
    return {"rows": len(rows), "matched_segments": matched, "unmatched": unmatched}


# --- data sources and jobs (T5.6) -----------------------------------------------------------

QUOTAS = {"tomtom": 2500, "open_meteo": 10000, "nominatim": None, "gemini": None}


@router.get("/admin/data-sources")
async def data_sources(_: CurrentUser = Depends(require_role("admin")), session: AsyncSession = Depends(get_session)):
    last = await db.rows(
        session,
        """
        select distinct on (job) job, started_at, finished_at, status, items, quota_used, error
        from job_runs order by job, id desc""",
    )
    by_job = {r["job"]: r for r in last}
    jobs = []
    for name in sorted(ingest.REGISTRY):
        r = by_job.get(name)
        jobs.append(
            {
                "job": name,
                "last_run": iso(r["finished_at"] or r["started_at"]) if r else None,
                "status": r["status"] if r else "NEVER_RUN",
                "items": r["items"] if r else 0,
                "quota_used": r["quota_used"] if r else 0,
                "error": r["error"] if r else None,
            }
        )
    quotas = {}
    for counter, limit in QUOTAS.items():
        quotas[f"{counter}_today"] = {
            "used": await usage.today(session, counter),
            "limit": limit if limit is not None else "free tier",
        }
    return {"jobs": jobs, "quotas": quotas}


@router.post("/internal/jobs/{name}", dependencies=[Depends(require_cron_secret)])
async def run_job(name: str, session: AsyncSession = Depends(get_session)):
    if name not in ingest.REGISTRY:
        raise ApiError(404, "NOT_FOUND", f"Unknown job {name}. Known: {', '.join(sorted(ingest.REGISTRY))}")
    result = await ingest.run(session, name)
    if result["status"] != "OK":
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", f"Job {name} failed", result)
    return result


@router.post("/admin/jobs/{name}")
async def run_job_as_admin(
    name: str, _: CurrentUser = Depends(require_role("admin")), session: AsyncSession = Depends(get_session)
):
    """The Admin page's "Run now" button."""
    if name not in ingest.REGISTRY:
        raise ApiError(404, "NOT_FOUND", f"Unknown job {name}")
    return await ingest.run(session, name)


@router.get("/admin/environment")
async def environment(_: CurrentUser = Depends(require_role("admin"))):
    s = get_settings()
    return {
        "app_env": s.app_env,
        "gemini_vision": s.gemini_model_vision,
        "gemini_lite": s.gemini_model_lite,
        "reddit_configured": bool(s.reddit_client_id),
        "tomtom_configured": bool(s.tomtom_api_key),
    }
