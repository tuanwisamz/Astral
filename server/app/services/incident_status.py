"""Incident status machine (spec-api §2, plus VERIFIED → DUPLICATE from plan §7)."""

from app.core.errors import ApiError

TRANSITIONS: dict[str, set[str]] = {
    "REPORTED": {"VERIFIED", "REJECTED", "DUPLICATE"},
    "VERIFIED": {"ASSIGNED", "REJECTED", "DUPLICATE"},
    "ASSIGNED": {"MITIGATED", "RESOLVED"},
    "MITIGATED": {"RESOLVED"},
    "RESOLVED": {"REPORTED"},  # reopen
    "REJECTED": set(),
    "DUPLICATE": set(),
}

OPEN_STATUSES = ("REPORTED", "VERIFIED", "ASSIGNED", "MITIGATED")
_EDITOR_ROLES = {"officer", "admin"}


def allowed_next(status: str, role: str) -> list[str]:
    if role not in _EDITOR_ROLES:
        return []
    return sorted(TRANSITIONS.get(status, set()))


def check_transition(current: str, target: str, role: str) -> None:
    if role not in _EDITOR_ROLES:
        raise ApiError(403, "FORBIDDEN", "Only officers and admins can change status")
    if target not in TRANSITIONS.get(current, set()):
        raise ApiError(
            409,
            "INVALID_TRANSITION",
            f"Cannot move an incident from {current} to {target}",
            {"from": current, "to": target, "allowed": allowed_next(current, role)},
        )
