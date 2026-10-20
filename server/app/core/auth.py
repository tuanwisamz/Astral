"""Clerk token verification, roles and jurisdiction scope (architechture.md §13, plan D4)."""

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, Header
from sqlalchemy import text

from app.core import db
from app.core.config import get_settings
from app.core.errors import ApiError

log = logging.getLogger(__name__)

ROLES = ("public", "officer", "viewer", "admin")
STAFF = ("officer", "viewer", "admin")


@dataclass(frozen=True)
class CurrentUser:
    clerk_id: str
    role: str = "public"
    state_code: str | None = None
    district_id: str | None = None
    agency_id: str | None = None

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def decode_token(token: str) -> dict:
    settings = get_settings()
    if not settings.clerk_jwks_url:
        raise ApiError(401, "UNAUTHENTICATED", "Auth is not configured on this server")
    try:
        key = _jwks_client(settings.clerk_jwks_url).get_signing_key_from_jwt(token)
        # Leeway covers clock skew: Clerk's nbf can sit a moment ahead of this server's clock.
        claims = jwt.decode(token, key.key, algorithms=["RS256"], options={"require": ["exp", "sub"]}, leeway=30)
    except jwt.PyJWTError as exc:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token") from exc
    azp = claims.get("azp")
    if azp and settings.authorized_parties and azp not in settings.authorized_parties:
        raise ApiError(401, "UNAUTHENTICATED", "Token was issued for another origin")
    return claims


async def scope_claims(claims: dict) -> dict:
    """Role and scope come from the session-token template (T0.3). If the template isn't set up,
    the token carries none of them, so read publicMetadata from Clerk instead (cached briefly)."""
    if "role" in claims or not get_settings().clerk_secret_key:
        return claims
    from app.services import clerk  # local import: services.clerk imports core modules

    try:
        meta = await clerk.public_metadata(claims["sub"])
    except ApiError:
        log.warning("No role claim and Clerk lookup failed for %s; treating as public", claims["sub"])
        return claims
    return {**claims, **{k: meta.get(k) for k in ("role", "state_code", "district_id", "agency_id")}}


def user_from_claims(claims: dict) -> CurrentUser:
    role = claims.get("role") or "public"
    if role not in ROLES:
        role = "public"
    return CurrentUser(
        clerk_id=claims["sub"],
        role=role,
        state_code=claims.get("state_code") or None,
        district_id=claims.get("district_id") or None,
        agency_id=claims.get("agency_id") or None,
    )


async def mirror_user(user: CurrentUser) -> None:
    """Just-in-time copy of the token's claims into app_users (plan D4). Best effort."""
    engine = db.get_engine()
    if engine is None:
        return
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    insert into app_users (clerk_id, role, state_code, district_id, agency_id)
                    values (:clerk_id, :role, :state_code, cast(:district_id as uuid),
                            cast(:agency_id as uuid))
                    on conflict (clerk_id) do update set
                      role = excluded.role, state_code = excluded.state_code,
                      district_id = excluded.district_id, agency_id = excluded.agency_id
                    """
                ),
                user.__dict__,
            )
    except Exception:
        log.warning("Could not mirror user %s into app_users", user.clerk_id, exc_info=True)


async def optional_user(authorization: str | None = Header(default=None)) -> CurrentUser | None:
    settings = get_settings()
    if not authorization:
        if settings.dev_auth_allowed and settings.dev_auth_role in ROLES:
            return CurrentUser(
                clerk_id=f"dev-{settings.dev_auth_role}",
                role=settings.dev_auth_role,
                state_code=settings.dev_auth_state or None,
            )
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "UNAUTHENTICATED", "Expected 'Authorization: Bearer <token>'")
    user = user_from_claims(await scope_claims(decode_token(token)))
    await mirror_user(user)
    return user


async def current_user(user: CurrentUser | None = Depends(optional_user)) -> CurrentUser:
    if user is None:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in required")
    return user


def require_role(*roles: str):
    async def checker(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN", f"Requires role: {', '.join(roles)}")
        return user

    return checker


def require_cron_secret(x_cron_secret: str | None = Header(default=None)) -> None:
    secret = get_settings().cron_secret
    if not secret or x_cron_secret != secret:
        raise ApiError(401, "UNAUTHENTICATED", "Missing or wrong X-Cron-Secret")
