"""Incidents in Postgres (T2.4): create with SLA clocks, dedupe, status changes, merge, undo,
timeline. SLA and transition rules come from app.services so the API has one source of truth."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import CurrentUser
from app.core.errors import ApiError
from app.services import sla
from app.services.incident_status import OPEN_STATUSES, allowed_next, check_transition

DEDUPE_RADIUS_M = {"POTHOLE": 30, "FALLEN_TREE": 50, "SINKHOLE": 100}  # spec FR-REP-03
UNDO_WINDOW = timedelta(seconds=10)  # spec §9.1, plan §6
MYT = timezone(timedelta(hours=8))
JMG_NAME = "Jabatan Mineral dan Geosains Malaysia"
STATUS_TIMESTAMP = {
    "VERIFIED": "verified_at",
    "ASSIGNED": "assigned_at",
    "MITIGATED": "mitigated_at",
    "RESOLVED": "resolved_at",
}

SELECT = """
    i.id::text as id, i.ref_no, i.hazard_type, i.severity, i.status, i.source, i.source_url, i.confirmations,
    i.segment_id, i.description, i.photo_path, i.reported_by, i.reported_at, i.verified_at, i.assigned_at,
    i.mitigated_at, i.resolved_at, i.sla_temp_due_at, i.sla_perm_due_at, i.is_synthetic,
    i.duplicate_of::text as duplicate_of, i.ai_result, i.confidence,
    i.assigned_agency_id::text as assigned_agency_id, aa.name as assigned_agency,
    ST_X(i.geom) as lng, ST_Y(i.geom) as lat,
    s.name as road_name, s.ref as road_ref, s.road_class, s.state_code, d.name as district,
    o.name as owner, m.name as maintainer
"""
FROM = """
    from incidents i
    join road_segments s on s.id = i.segment_id
    left join jurisdiction_overrides jo on jo.segment_id = s.id
    left join districts d on d.id = s.district_id
    left join agencies o on o.id = coalesce(jo.owner_agency_id, s.owner_agency_id)
    left join agencies m on m.id = coalesce(jo.maintainer_agency_id, s.maintainer_agency_id)
    left join agencies aa on aa.id = i.assigned_agency_id
"""

# SQL twin of services.sla.is_overdue, for filters and aggregates. Tested against it.
OVERDUE_SQL = """(
    (i.status in ('REPORTED', 'VERIFIED', 'ASSIGNED') and i.sla_temp_due_at < now())
    or (i.status = 'MITIGATED' and i.sla_perm_due_at < now()))"""
OPEN_SQL = "i.status in ('REPORTED', 'VERIFIED', 'ASSIGNED', 'MITIGATED')"


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(MYT).isoformat() if dt else None


def refer_to(r: dict) -> list[str]:
    agencies = [r["owner"], r["maintainer"]] + ([JMG_NAME] if r["hazard_type"] == "SINKHOLE" else [])
    return list(dict.fromkeys(a for a in agencies if a))


def view(r: dict, staff: bool, role: str = "public", now: datetime | None = None) -> dict:
    """An incident as the API returns it. The public never sees reporter, photo or notes (spec-api §4.3)."""
    now = now or datetime.now(UTC)
    due = sla.next_deadline(r["status"], r["sla_temp_due_at"], r["sla_perm_due_at"])
    out = {
        "id": r["id"],
        "ref_no": r["ref_no"],
        "hazard_type": r["hazard_type"],
        "severity": r["severity"],
        "status": r["status"],
        "source": r["source"],
        "confirmations": r["confirmations"],
        "segment_id": r["segment_id"],
        "road_name": r["road_name"],
        "road_ref": r["road_ref"],
        "road_class": r["road_class"],
        "district": r["district"],
        "owner": r["owner"],
        "maintainer": r["maintainer"],
        "sla_due_at": iso(due),
        "sla_overdue": sla.is_overdue(r["status"], r["sla_temp_due_at"], r["sla_perm_due_at"], now),
        "is_synthetic": r["is_synthetic"],
        "reported_at": iso(r["reported_at"]),
    }
    if staff:
        out.update(
            {
                "refer_to": refer_to(r),
                "allowed_next": allowed_next(r["status"], role),
                "description": r["description"],
                "source_url": r["source_url"],
                "has_photo": bool(r["photo_path"]),
                "assigned_agency": r["assigned_agency"],
                "duplicate_of": r["duplicate_of"],
                "verified_at": iso(r["verified_at"]),
                "mitigated_at": iso(r["mitigated_at"]),
                "resolved_at": iso(r["resolved_at"]),
                "lat": r["lat"],
                "lng": r["lng"],
                "ai_suggested": bool(r["ai_result"]),
            }
        )
    return out


async def get(
    session: AsyncSession, incident_id: str, scope_sql: str = "true", for_update: bool = False, **scope_params
) -> dict:
    lock = " for update of i" if for_update else ""
    found = await db.row(
        session,
        f"select {SELECT} {FROM} where i.id = cast(:id as uuid) and {scope_sql}{lock}",
        id=incident_id,
        **scope_params,
    )
    if found is None:
        raise ApiError(404, "NOT_FOUND", "Incident not found, or outside your area")
    return found


async def by_ref(session: AsyncSession, ref_no: str) -> dict | None:
    return await db.row(session, f"select {SELECT} {FROM} where i.ref_no = :ref", ref=ref_no)


async def add_event(
    session: AsyncSession,
    incident_id: str,
    actor: str | None,
    action: str,
    from_status: str | None,
    to_status: str | None,
    note: str | None = None,
) -> None:
    await session.execute(
        text("""
        insert into incident_events (incident_id, actor, action, from_status, to_status, note)
        values (cast(:id as uuid), :actor, :action, :from_s, :to_s, :note)"""),
        {"id": incident_id, "actor": actor, "action": action, "from_s": from_status, "to_s": to_status, "note": note},
    )


async def find_duplicate(session: AsyncSession, hazard_type: str, lat: float, lng: float) -> dict | None:
    """An open incident of the same type within the spec radius is merged as a confirmation."""
    return await db.row(
        session,
        f"""
        select i.id::text as id, i.ref_no, i.status, i.confirmations
        from incidents i
        where i.hazard_type = :hazard and {OPEN_SQL}
          and ST_DWithin(i.geom::geography, ST_SetSRID(ST_Point(:lng, :lat), 4326)::geography, :radius)
        order by i.geom <-> ST_SetSRID(ST_Point(:lng, :lat), 4326)
        limit 1 for update""",
        hazard=hazard_type,
        lat=lat,
        lng=lng,
        radius=DEDUPE_RADIUS_M[hazard_type],
    )


async def confirm(session: AsyncSession, dup: dict, actor: str | None) -> int:
    count = await db.scalar(
        session,
        """
        update incidents set confirmations = confirmations + 1 where id = cast(:id as uuid)
        returning confirmations""",
        id=dup["id"],
    )
    await add_event(
        session, dup["id"], actor, "CONFIRM", dup["status"], dup["status"], "Another report of the same hazard"
    )
    return int(count)


async def create(
    session: AsyncSession,
    *,
    hazard_type: str,
    severity: int,
    lat: float,
    lng: float,
    segment: dict,
    source: str,
    actor: str | None,
    description: str | None = None,
    photo_path: str | None = None,
    ai_result: dict | None = None,
    confidence: float | None = None,
    source_url: str | None = None,
    reported_at: datetime | None = None,
    is_synthetic: bool = False,
    status: str = "REPORTED",
) -> dict:
    reported_at = reported_at or datetime.now(UTC)
    temp_due, perm_due = sla.deadlines(segment["road_class"], reported_at)
    created = await db.row(
        session,
        """
        insert into incidents (ref_no, hazard_type, severity, status, source, source_url, confidence, ai_result,
                               description, photo_path, segment_id, reported_by, reported_at, sla_temp_due_at,
                               sla_perm_due_at, is_synthetic, geom)
        values ('SAR-' || to_char(:reported_at at time zone 'Asia/Kuala_Lumpur', 'YYYY') || '-'
                    || lpad(nextval('incident_ref_seq')::text, 6, '0'),
                :hazard, :severity, :status, :source, :source_url, :confidence, cast(:ai_result as jsonb),
                :description, :photo_path, :segment_id, :actor, :reported_at, :temp_due, :perm_due, :synthetic,
                ST_SetSRID(ST_Point(:lng, :lat), 4326))
        returning id::text as id, ref_no""",
        hazard=hazard_type,
        severity=severity,
        status=status,
        source=source,
        source_url=source_url,
        confidence=confidence,
        ai_result=ai_result,
        description=description,
        photo_path=photo_path,
        segment_id=segment["segment_id"],
        actor=actor,
        reported_at=reported_at,
        temp_due=temp_due,
        perm_due=perm_due,
        synthetic=is_synthetic,
        lat=lat,
        lng=lng,
    )
    await add_event(session, created["id"], actor, "CREATE", None, status)
    return {**created, "sla_temp_due_at": temp_due, "sla_perm_due_at": perm_due}


async def change(
    session: AsyncSession,
    inc: dict,
    user: CurrentUser,
    *,
    status: str | None,
    severity: int | None,
    assigned_agency_id: str | None,
    note: str | None,
) -> None:
    sets, params = [], {"id": inc["id"]}
    action, to_status = "UPDATE", inc["status"]
    if status and status != inc["status"]:
        check_transition(inc["status"], status, user.role)
        sets.append("status = :status")
        params["status"] = status
        if status in STATUS_TIMESTAMP:
            sets.append(f"{STATUS_TIMESTAMP[status]} = coalesce({STATUS_TIMESTAMP[status]}, now())")
        action, to_status = "STATUS", status
    if severity is not None:
        sets.append("severity = :severity")
        params["severity"] = severity
    if assigned_agency_id is not None:
        exists = await db.scalar(
            session, "select exists(select 1 from agencies where id = cast(:a as uuid))", a=assigned_agency_id
        )
        if not exists:
            raise ApiError(422, "VALIDATION_ERROR", "Unknown agency")
        sets += ["assigned_agency_id = cast(:agency as uuid)", "assigned_at = coalesce(assigned_at, now())"]
        params["agency"] = assigned_agency_id
    if not sets and not note:
        raise ApiError(422, "VALIDATION_ERROR", "Nothing to change")
    if sets:
        await session.execute(text(f"update incidents set {', '.join(sets)} where id = cast(:id as uuid)"), params)
    await add_event(session, inc["id"], user.clerk_id, action, inc["status"], to_status, note)


async def merge(session: AsyncSession, inc: dict, primary: dict, user: CurrentUser) -> None:
    if inc["id"] == primary["id"]:
        raise ApiError(422, "VALIDATION_ERROR", "An incident can't be merged into itself")
    if inc["hazard_type"] != primary["hazard_type"]:
        raise ApiError(422, "VALIDATION_ERROR", "Only incidents of the same hazard type can be merged")
    check_transition(inc["status"], "DUPLICATE", user.role)
    await session.execute(
        text("""
        update incidents set status = 'DUPLICATE', duplicate_of = cast(:primary as uuid) where id = cast(:id as uuid);
    """),
        {"id": inc["id"], "primary": primary["id"]},
    )
    await session.execute(
        text("update incidents set confirmations = confirmations + :n where id = cast(:primary as uuid)"),
        {"n": inc["confirmations"], "primary": primary["id"]},
    )
    await add_event(
        session, inc["id"], user.clerk_id, "MERGE", inc["status"], "DUPLICATE", f"Merged into {primary['ref_no']}"
    )
    await add_event(
        session,
        primary["id"],
        user.clerk_id,
        "CONFIRM",
        primary["status"],
        primary["status"],
        f"{inc['ref_no']} merged in",
    )


async def undo(session: AsyncSession, inc: dict, user: CurrentUser) -> str:
    """Reverts the last status change if the same person made it in the last 10 seconds (plan §6)."""
    last = await db.row(
        session,
        """
        select action, actor, from_status, to_status, created_at from incident_events
        where incident_id = cast(:id as uuid) order by id desc limit 1""",
        id=inc["id"],
    )
    if (
        not last
        or last["action"] != "STATUS"
        or last["actor"] != user.clerk_id
        or datetime.now(UTC) - last["created_at"] > UNDO_WINDOW
    ):
        raise ApiError(409, "UNDO_EXPIRED", "There's no recent change of yours to undo. Undo works for 10 seconds.")
    column = STATUS_TIMESTAMP.get(last["to_status"])
    clear = f", {column} = null" if column else ""
    await session.execute(
        text(f"update incidents set status = :s{clear} where id = cast(:id as uuid)"),
        {"s": last["from_status"], "id": inc["id"]},
    )
    await add_event(session, inc["id"], user.clerk_id, "UNDO", last["to_status"], last["from_status"])
    return last["from_status"]


async def events(session: AsyncSession, incident_id: str, public: bool) -> list[dict]:
    found = await db.rows(
        session,
        """
        select action, from_status, to_status, note, actor, created_at from incident_events
        where incident_id = cast(:id as uuid) order by id""",
        id=incident_id,
    )
    out = []
    for e in found:
        item = {
            "action": e["action"],
            "from_status": e["from_status"],
            "to_status": e["to_status"],
            "at": iso(e["created_at"]),
        }
        if not public:
            item.update(note=e["note"], actor=e["actor"])
        out.append(item)
    return out


def is_open(status: str) -> bool:
    return status in OPEN_STATUSES
