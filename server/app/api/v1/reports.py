import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import CurrentUser, current_user
from app.core.db import get_session
from app.core.errors import ApiError
from app.queries import incidents, segments
from app.queries.incidents import iso
from app.services import gemini, photos, scope, storage, usage

router = APIRouter(prefix="/reports", tags=["reports"])

MIN_CONFIDENCE = 0.5  # architechture.md §12: below this the user may still submit as uncertain


class ReportIn(BaseModel):
    analysis_id: str | None = Field(default=None, max_length=40)
    hazard_type: str = Field(pattern="^(POTHOLE|FALLEN_TREE|SINKHOLE)$")
    severity: int = Field(ge=1, le=5)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    description: str | None = Field(default=None, max_length=500)


@router.post("/analyze")
async def analyze(
    photo: UploadFile = File(...),
    lat: float = Form(..., ge=-90, le=90),
    lng: float = Form(..., ge=-180, le=180),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """AI photo check (T4.2). Nothing becomes an incident until POST /reports."""
    seg, distance = await segments.nearest(session, lat, lng)  # OUTSIDE_COVERAGE / NOT_ON_ROAD first: cheap
    await usage.take(session, "analyze", user.clerk_id)
    image = photos.clean(await photo.read())
    analysis_id = f"an_{secrets.token_hex(8)}"
    now = datetime.now(UTC)
    path = f"{now:%Y/%m}/{analysis_id}.webp"
    await storage.upload(path, image, "image/webp")
    nearest_road = {
        "segment_id": seg["segment_id"],
        "name": seg["name"],
        "ref": seg["ref"],
        "road_class": seg["road_class"],
        "distance_m": round(distance),
    }

    try:
        result = await gemini.classify_photo(session, image, "image/webp")
    except ApiError as exc:
        # The photo is kept, so the person can still report it with a type they pick (T4.5).
        await db.rows(
            session,
            """
            insert into report_analyses (id, clerk_id, photo_path, lat, lng, ai_result)
            values (:id, :uid, :path, :lat, :lng, null) returning id""",
            id=analysis_id,
            uid=user.clerk_id,
            path=path,
            lat=lat,
            lng=lng,
        )
        await session.commit()
        exc.details = {**exc.details, "analysis_id": analysis_id, "nearest_road": nearest_road}
        raise

    ai = result.model_dump()
    await db.rows(
        session,
        """
        insert into report_analyses (id, clerk_id, photo_path, lat, lng, ai_result)
        values (:id, :uid, :path, :lat, :lng, cast(:ai as jsonb)) returning id""",
        id=analysis_id,
        uid=user.clerk_id,
        path=path,
        lat=lat,
        lng=lng,
        ai=result.model_dump(),
    )
    await session.commit()
    return {
        "analysis_id": analysis_id,
        "is_road_hazard": ai["is_road_hazard"],
        "suggested_type": ai["hazard_type"],
        "suggested_severity": ai["severity"],
        "confidence": round(ai["confidence"], 2),
        "uncertain": ai["confidence"] < MIN_CONFIDENCE,
        "reasons": ai["reasons"],
        "privacy_flags": {"faces_visible": ai["faces_visible"], "plates_visible": ai["plates_visible"]},
        "nearest_road": nearest_road,
        "ai_suggested": True,
    }


@router.post("", status_code=201)
async def submit(
    body: ReportIn, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    """Submit a report (T4.3): validate the location, snap to the road, merge duplicates."""
    seg, _ = await segments.nearest(session, body.lat, body.lng)
    analysis = None
    if body.analysis_id:
        analysis = await db.row(
            session,
            """
            select id, photo_path, ai_result from report_analyses
            where id = :id and clerk_id = :uid and incident_id is null and created_at > now() - interval '24 hours'
            for update""",
            id=body.analysis_id,
            uid=user.clerk_id,
        )
        if analysis is None:
            raise ApiError(
                422, "VALIDATION_ERROR", "That photo check has expired or was already used. Take the photo again."
            )
    await usage.take(session, "report", user.clerk_id)

    dup = await incidents.find_duplicate(session, body.hazard_type, body.lat, body.lng)
    if dup:
        count = await incidents.confirm(session, dup, user.clerk_id)
        if analysis:
            await db.rows(
                session,
                "update report_analyses set incident_id = cast(:inc as uuid) where id = :id returning id",
                inc=dup["id"],
                id=analysis["id"],
            )
        await session.commit()
        return JSONResponse(
            status_code=200,
            content={
                "ref_no": dup["ref_no"],
                "status": dup["status"],
                "merged_into": dup["ref_no"],
                "confirmations": count,
                "segment": {
                    "id": seg["segment_id"],
                    "name": seg["name"],
                    "ref": seg["ref"],
                    "road_class": seg["road_class"],
                },
                "responsible": {"owner": seg["owner"], "maintainer": seg["maintainer"]},
            },
        )

    ai = analysis["ai_result"] if analysis else None
    created = await incidents.create(
        session,
        hazard_type=body.hazard_type,
        severity=body.severity,
        lat=body.lat,
        lng=body.lng,
        segment=seg,
        source="PUBLIC",
        actor=user.clerk_id,
        description=body.description,
        photo_path=analysis["photo_path"] if analysis else None,
        ai_result=ai,
        confidence=ai.get("confidence") if ai else None,
    )
    if analysis:
        await db.rows(
            session,
            "update report_analyses set incident_id = cast(:inc as uuid) where id = :id returning id",
            inc=created["id"],
            id=analysis["id"],
        )
    await session.commit()
    due = created["sla_temp_due_at"]
    return {
        "ref_no": created["ref_no"],
        "status": "REPORTED",
        "merged_into": None,
        "segment": {"id": seg["segment_id"], "name": seg["name"], "ref": seg["ref"], "road_class": seg["road_class"]},
        "responsible": {"owner": seg["owner"], "maintainer": seg["maintainer"]},
        "sla_due_at": iso(due),
    }


@router.get("/mine")
async def mine(
    page: int = Query(default=1, ge=1),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    found = await db.rows(
        session,
        f"""
        select {incidents.SELECT}, count(*) over () as total {incidents.FROM}
        where i.reported_by = :uid order by i.reported_at desc limit 50 offset :off""",
        uid=user.clerk_id,
        off=(page - 1) * 50,
    )
    return {
        "items": [
            {
                **{
                    k: v
                    for k, v in incidents.view(r, False).items()
                    if k
                    in (
                        "ref_no",
                        "hazard_type",
                        "status",
                        "road_name",
                        "road_ref",
                        "road_class",
                        "owner",
                        "reported_at",
                        "confirmations",
                    )
                }
            }
            for r in found
        ],
        "total": int(found[0]["total"]) if found else 0,
        "page": page,
        "page_size": 50,
    }


@router.get("/{ref_no}")
async def status(ref_no: str, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Status tracking (FR-REP-04): the reporter sees their own report; staff see reports in their area."""
    inc = await incidents.by_ref(session, ref_no)
    allowed = inc is not None and inc["reported_by"] == user.clerk_id
    if inc is not None and not allowed and user.is_staff:
        sc = await scope.for_user(session, user)
        allowed = bool(
            await db.scalar(
                session,
                f"""
            select exists(select 1 from incidents i join road_segments s on s.id = i.segment_id
                          where i.id = cast(:id as uuid) and {sc.incidents_sql()})""",
                id=inc["id"],
                **sc.params,
            )
        )
    if not allowed:
        raise ApiError(404, "NOT_FOUND", f"Report {ref_no} not found")
    timeline = [
        e
        for e in await incidents.events(session, inc["id"], public=True)
        if e["action"] in ("CREATE", "STATUS", "UNDO", "MERGE")
    ]
    view = incidents.view(inc, False)
    return {
        **{
            k: view[k]
            for k in (
                "ref_no",
                "hazard_type",
                "status",
                "road_name",
                "road_ref",
                "road_class",
                "owner",
                "maintainer",
                "sla_due_at",
                "reported_at",
                "confirmations",
            )
        },
        "timeline": [{"status": e["to_status"], "at": e["at"]} for e in timeline],
    }
