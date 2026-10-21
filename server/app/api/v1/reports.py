import math
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import CurrentUser, current_user
from app.core.db import get_session
from app.core.errors import ApiError
from app.queries import incidents, segments
from app.queries.incidents import iso
from app.services import gemini, geocode, photos, scope, storage, usage

router = APIRouter(prefix="/reports", tags=["reports"])

MIN_CONFIDENCE = 0.5  # architechture.md §12: below this the user may still submit as uncertain

# Camera-only reports (U3, docs/usability-implementation-plan.md).
CAPTURE_TTL = timedelta(minutes=10)  # a photo must be checked within this long of being taken
MAX_GPS_ACCURACY_M = 100  # coarser fixes are refused: move into the open and try again
MAX_PIN_SHIFT_M = 100  # how far the pin may be dragged from the phone's GPS fix

# Someone is a reporter of incident i if they filed it, or if their report was merged into it as a
# duplicate (FR-REP-03): the merge links their photo check to i. Either way they can track it (FR-REP-04).
IS_REPORTER_SQL = """(i.reported_by = :uid or exists (
    select 1 from report_analyses ra where ra.incident_id = i.id and ra.clerk_id = :uid))"""


class ReportIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    analysis_id: str = Field(max_length=40)  # every report needs a photo check from the in-app camera (U3)
    hazard_type: str = Field(pattern="^(POTHOLE|FALLEN_TREE|SINKHOLE)$")
    severity: int = Field(ge=1, le=5)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    description: str | None = Field(default=None, max_length=500)
    reporter_name: str = Field(min_length=2, max_length=80)
    address: str | None = Field(default=None, max_length=200)
    landmark: str | None = Field(default=None, max_length=120)


def metres_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance, plenty accurate over the 100 m it's used for."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def check_gps(accuracy_m: float) -> None:
    if accuracy_m > MAX_GPS_ACCURACY_M:
        raise ApiError(
            422,
            "GPS_TOO_COARSE",
            f"Your location is only accurate to {round(accuracy_m)} m. Move into the open and take the photo again.",
            {"accuracy_m": round(accuracy_m), "max_m": MAX_GPS_ACCURACY_M},
        )


def check_pin(lat: float, lng: float, gps_lat: float, gps_lng: float) -> None:
    shift = metres_between(lat, lng, gps_lat, gps_lng)
    if shift > MAX_PIN_SHIFT_M:
        raise ApiError(
            422,
            "PIN_TOO_FAR",
            f"The pin is {round(shift)} m from where the photo was taken. Keep it within {MAX_PIN_SHIFT_M} m.",
            {"distance_m": round(shift), "max_m": MAX_PIN_SHIFT_M},
        )


async def _spend_capture_token(session: AsyncSession, token: str, clerk_id: str) -> None:
    """Single use, same account, under CAPTURE_TTL old (U3a). A refusal doesn't say which check failed."""
    spent = await db.scalar(
        session,
        """
        update capture_tokens set used_at = now()
        where token = :t and clerk_id = :uid and used_at is null and issued_at > now() - cast(:ttl as interval)
        returning token""",
        t=token,
        uid=clerk_id,
        ttl=CAPTURE_TTL,
    )
    if spent is None:
        raise ApiError(422, "CAPTURE_EXPIRED", "That photo has expired or was already checked. Take the photo again.")


async def _is_reporter(session: AsyncSession, incident_id: str, clerk_id: str) -> bool:
    return bool(
        await db.scalar(
            session,
            f"select exists(select 1 from incidents i where i.id = cast(:id as uuid) and {IS_REPORTER_SQL})",
            id=incident_id,
            uid=clerk_id,
        )
    )


@router.post("/capture-start", status_code=201)
async def capture_start(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """A single-use token for one photo from the in-app camera (U3a); /reports/analyze spends it."""
    await usage.take(session, "capture", user.clerk_id)
    token = f"cap_{secrets.token_urlsafe(18)}"
    issued = await db.scalar(
        session,
        "insert into capture_tokens (token, clerk_id) values (:t, :uid) returning issued_at",
        t=token,
        uid=user.clerk_id,
    )
    await session.commit()
    return {"capture_token": token, "expires_at": iso(issued + CAPTURE_TTL)}


@router.get("/where")
async def where(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Street address for the report pin (U3b). Null when it can't be found; the reporter types it."""
    return {"address": await geocode.reverse(session, lat, lng)}


@router.post("/analyze")
async def analyze(
    photo: UploadFile = File(...),
    lat: float = Form(..., ge=-90, le=90),
    lng: float = Form(..., ge=-180, le=180),
    capture_token: str = Form(..., max_length=64),
    gps_lat: float = Form(..., ge=-90, le=90),
    gps_lng: float = Form(..., ge=-180, le=180),
    gps_accuracy_m: float = Form(..., ge=0),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """AI photo check (T4.2). Nothing becomes an incident until POST /reports.

    The photo must come from the in-app camera (a fresh capture token) with a good GPS fix, and the
    pin must stay near that fix (U3). lat/lng is the pin; gps_* is the phone's fix at the shutter."""
    check_gps(gps_accuracy_m)
    check_pin(lat, lng, gps_lat, gps_lng)
    seg, distance = await segments.nearest(session, lat, lng)  # OUTSIDE_COVERAGE / NOT_ON_ROAD first: cheap
    await usage.take(session, "analyze", user.clerk_id)
    await _spend_capture_token(session, capture_token, user.clerk_id)  # rolled back if anything below fails
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

    async def save(ai: dict | None) -> None:
        await db.rows(
            session,
            """
            insert into report_analyses (id, clerk_id, photo_path, lat, lng, ai_result, capture_token,
                                         gps_lat, gps_lng, gps_accuracy_m)
            values (:id, :uid, :path, :lat, :lng, cast(:ai as jsonb), :token, :gps_lat, :gps_lng, :acc)
            returning id""",
            id=analysis_id,
            uid=user.clerk_id,
            path=path,
            lat=lat,
            lng=lng,
            ai=ai,
            token=capture_token,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
            acc=gps_accuracy_m,
        )
        await session.commit()

    try:
        result = await gemini.classify_photo(session, image, "image/webp")
    except ApiError as exc:
        # The photo is kept, so the person can still report it with a type they pick (T4.5).
        await save(None)
        exc.details = {**exc.details, "analysis_id": analysis_id, "nearest_road": nearest_road}
        raise

    ai = result.model_dump()
    await save(ai)
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
    """Submit a report (T4.3): check the photo and pin (U3), snap to the road, merge duplicates."""
    analysis = await db.row(
        session,
        """
        select id, photo_path, ai_result, gps_lat, gps_lng, gps_accuracy_m, created_at from report_analyses
        where id = :id and clerk_id = :uid and incident_id is null and created_at > now() - interval '24 hours'
        for update""",
        id=body.analysis_id,
        uid=user.clerk_id,
    )
    if analysis is None:
        raise ApiError(
            422, "VALIDATION_ERROR", "That photo check has expired or was already used. Take the photo again."
        )
    if analysis["gps_lat"] is not None:  # checks made before U3 carry no fix
        check_pin(body.lat, body.lng, analysis["gps_lat"], analysis["gps_lng"])
    seg, _ = await segments.nearest(session, body.lat, body.lng)
    await usage.take(session, "report", user.clerk_id)

    dup = await incidents.find_duplicate(session, body.hazard_type, body.lat, body.lng)
    if dup:
        # One person reporting the same hazard again is still linked (they can track it) but isn't
        # another confirmation: "N others reported this" counts people, not repeat reports.
        if await _is_reporter(session, dup["id"], user.clerk_id):
            count = int(dup["confirmations"])
        else:
            count = await incidents.confirm(session, dup, user.clerk_id)
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

    ai = analysis["ai_result"]
    created = await incidents.create(
        session,
        hazard_type=body.hazard_type,
        severity=body.severity,
        lat=body.lat,
        lng=body.lng,
        segment=seg,
        source="PUBLIC",
        actor=user.clerk_id,
        description=body.description or None,
        photo_path=analysis["photo_path"],
        ai_result=ai,
        confidence=ai.get("confidence") if ai else None,
        reporter_name=body.reporter_name,
        address=body.address or None,
        landmark=body.landmark or None,
        gps_lat=analysis["gps_lat"],
        gps_lng=analysis["gps_lng"],
        gps_accuracy_m=analysis["gps_accuracy_m"],
        captured_at=analysis["created_at"],
    )
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
        where {IS_REPORTER_SQL} order by i.reported_at desc limit 50 offset :off""",
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
    allowed = inc is not None and await _is_reporter(session, inc["id"], user.clerk_id)
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
