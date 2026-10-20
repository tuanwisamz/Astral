"""SLA clocks: temporary patch and permanent repair (spec §2, plan §6)."""

from datetime import datetime, timedelta

# Federal hours come from the spec. The others are placeholders (plan §10 Q3).
SLA_RULES = {
    "FEDERAL": {"temporary_hours": 24, "permanent_hours": 72, "assumed": False},
    "STATE": {"temporary_hours": 48, "permanent_hours": 168, "assumed": True},
    "MUNICIPAL": {"temporary_hours": 72, "permanent_hours": 336, "assumed": True},
    "EXPRESSWAY": {"temporary_hours": 24, "permanent_hours": 72, "assumed": True},
}

_TEMP_MET = {"MITIGATED", "RESOLVED"}
_CLOSED = {"RESOLVED", "REJECTED", "DUPLICATE"}


def deadlines(road_class: str, reported_at: datetime) -> tuple[datetime | None, datetime | None]:
    rule = SLA_RULES.get(road_class)
    if rule is None:
        return None, None
    return (
        reported_at + timedelta(hours=rule["temporary_hours"]),
        reported_at + timedelta(hours=rule["permanent_hours"]),
    )


def next_deadline(status: str, temp_due: datetime | None, perm_due: datetime | None) -> datetime | None:
    """The API's single sla_due_at: the next deadline the incident still has to meet."""
    if status in _CLOSED:
        return None
    if status in _TEMP_MET:
        return perm_due
    return temp_due


def is_overdue(status: str, temp_due: datetime | None, perm_due: datetime | None, now: datetime) -> bool:
    due = next_deadline(status, temp_due, perm_due)
    return due is not None and now > due
