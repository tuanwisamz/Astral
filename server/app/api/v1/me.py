"""The signed-in person's own account (plan A3): what Settings shows, and deleting the account.

Deleting anonymises before it deletes (plan D14). Hazards the person reported stay on the map,
because the pothole is still there, but nothing links them to the person any more.
"""

import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import db
from app.core.auth import CurrentUser, current_user
from app.core.db import get_session
from app.core.errors import ApiError
from app.services import clerk, storage

router = APIRouter(tags=["me"])
log = logging.getLogger(__name__)

DELETED = "deleted-user"


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    names = await db.row(
        session,
        """
        select (select name from states where code = cast(:s as text)) as state,
               (select name from districts where id::text = cast(:d as text)) as district,
               (select name from agencies where id::text = cast(:a as text)) as agency,
               (select count(*) from incidents where reported_by = :uid) as reports""",
        s=user.state_code,
        d=user.district_id,
        a=user.agency_id,
        uid=user.clerk_id,
    )
    last_admin = False
    if user.role == "admin":
        try:
            last_admin = await clerk.count_admins() <= 1
        except ApiError:
            last_admin = False  # Clerk unreachable: DELETE /me checks again and refuses if needed
    return {
        "clerk_id": user.clerk_id,
        "role": user.role,
        "state": {"code": user.state_code, "name": names["state"]} if user.state_code else None,
        "district": {"id": user.district_id, "name": names["district"]} if user.district_id else None,
        "agency": {"id": user.agency_id, "name": names["agency"]} if user.agency_id else None,
        "reports": int(names["reports"]),
        "last_admin": last_admin,
    }


# Every table that stores a Clerk user ID, and what deleting the account does to it.
ANONYMISE = [
    "update incidents set reported_by = null where reported_by = :uid",
    "update incident_events set actor = :deleted where actor = :uid",
    "update report_analyses set clerk_id = :deleted where clerk_id = :uid and incident_id is not null",
    "update priority_profiles set created_by = :deleted where created_by = :uid",
    "update zones set created_by = :deleted where created_by = :uid",
    "update jurisdiction_overrides set created_by = :deleted where created_by = :uid",
    "delete from usage_daily where clerk_id = :uid",
    "delete from app_users where clerk_id = :uid",
]


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if user.role == "admin" and await clerk.count_admins() <= 1:
        raise ApiError(
            409,
            "LAST_ADMIN",
            "You're the only admin, so this account can't be deleted. Make someone else an admin first.",
        )
    # Unsubmitted photos go with the account; submitted ones stay with their (anonymised) incident.
    unsent = await db.rows(
        session,
        "delete from report_analyses where clerk_id = :uid and incident_id is null returning photo_path",
        uid=user.clerk_id,
    )
    for sql in ANONYMISE:
        await session.execute(text(sql), {"uid": user.clerk_id, "deleted": DELETED})
    try:
        await clerk.delete_user(user.clerk_id)
    except Exception:
        await session.rollback()  # the account still exists, so its data stays linked to it
        raise
    await session.commit()
    paths = [r["photo_path"] for r in unsent if r["photo_path"]]
    if paths:
        try:
            await storage.delete(paths)
        except Exception:
            log.warning("Could not delete %d unsent photos; the cleanup job removes them", len(paths), exc_info=True)
    return Response(status_code=204)
