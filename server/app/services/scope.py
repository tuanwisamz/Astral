"""Jurisdiction scope for officers and viewers (spec §3, NFR-08, plan §6 viewer rules).

Each function returns a SQL fragment over `road_segments s` plus its bind parameters, so every
staff query restricts rows the same way. Admins see everything. An officer or viewer whose
account has no scope sees nothing, never everything.
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import CurrentUser
from app.core.errors import ApiError

OWN_OR_MAINTAIN_TYPES = {
    "PBT",
    "FED_MAINT_CONCESSIONAIRE",
    "EXPRESSWAY_CONCESSIONAIRE",
    "JKR_STATE",
    "JKR_DISTRICT",
    "JKR_HQ",
}


@dataclass
class Scope:
    sql: str = "true"
    params: dict = field(default_factory=dict)
    all_sinkholes: bool = False  # JMG sees every sinkhole, wherever it is

    def incidents_sql(self, incident_alias: str = "i") -> str:
        if self.all_sinkholes:
            return f"(({self.sql}) or {incident_alias}.hazard_type = 'SINKHOLE')"
        return self.sql


NOTHING = Scope("false")


async def for_user(session: AsyncSession, user: CurrentUser | None) -> Scope:
    if user is None or user.role in ("admin", "public"):
        return Scope()
    if user.role == "officer":
        if not user.state_code:
            return NOTHING
        sql, params = "s.state_code = :scope_state", {"scope_state": user.state_code}
        if user.district_id:
            sql += " and s.district_id = cast(:scope_district as uuid)"
            params["scope_district"] = user.district_id
        return Scope(sql, params)
    # viewer: scoped by the agency they belong to, else by state
    if user.agency_id:
        agency_type = await db.scalar(
            session, "select type from agencies where id = cast(:id as uuid)", id=user.agency_id
        )
        if agency_type in OWN_OR_MAINTAIN_TYPES:
            return Scope(
                "(s.owner_agency_id = cast(:scope_agency as uuid) or s.maintainer_agency_id = cast(:scope_agency as uuid))",
                {"scope_agency": user.agency_id},
            )
        if agency_type == "LLM":
            return Scope("s.road_class = 'EXPRESSWAY'")
        if agency_type == "JMG":
            return Scope("(s.karst or s.ex_mining)", all_sinkholes=True)
    if user.state_code:
        return Scope("s.state_code = :scope_state", {"scope_state": user.state_code})
    return NOTHING


def requested(
    state: str | None, district: str | None, road_class: str | None = None, owner_agency_id: str | None = None
) -> tuple[str, dict]:
    """The scope the person picked in the UI (State › District), narrowing their own scope."""
    parts, params = [], {}
    if state:
        parts.append("s.state_code = :req_state")
        params["req_state"] = state
    if district:
        parts.append("s.district_id = cast(:req_district as uuid)")
        params["req_district"] = district
    if road_class:
        parts.append("s.road_class = any(:req_classes)")
        params["req_classes"] = [c.strip().upper() for c in road_class.split(",") if c.strip()]
    if owner_agency_id:
        parts.append(
            "(s.owner_agency_id = cast(:req_owner as uuid) or s.maintainer_agency_id = cast(:req_owner as uuid))"
        )
        params["req_owner"] = owner_agency_id
    return (" and ".join(parts) or "true"), params


async def ensure_segment_in_scope(session: AsyncSession, scope: Scope, segment_id: int) -> None:
    ok = await db.scalar(
        session,
        f"select exists(select 1 from road_segments s where s.id = :sid and {scope.sql})",
        sid=segment_id,
        **scope.params,
    )
    if not ok:
        raise ApiError(403, "OUT_OF_SCOPE", "This road is outside the area your account covers")
