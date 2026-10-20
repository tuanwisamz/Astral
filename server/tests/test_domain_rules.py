from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ApiError
from app.services import sla
from app.services.incident_status import allowed_next, check_transition
from app.services.priority import DEFAULT_WEIGHTS, SegmentState, normalise_weights, recommended_action, score

T0 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)


# --- status machine -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("REPORTED", "VERIFIED"),
        ("VERIFIED", "ASSIGNED"),
        ("ASSIGNED", "MITIGATED"),
        ("MITIGATED", "RESOLVED"),
        ("RESOLVED", "REPORTED"),
        ("VERIFIED", "DUPLICATE"),
    ],
)
def test_valid_transitions(current, target):
    check_transition(current, target, "officer")


@pytest.mark.parametrize(
    ("current", "target"),
    [("REPORTED", "RESOLVED"), ("MITIGATED", "ASSIGNED"), ("REJECTED", "VERIFIED"), ("DUPLICATE", "REPORTED")],
)
def test_invalid_transitions(current, target):
    with pytest.raises(ApiError) as err:
        check_transition(current, target, "officer")
    assert (err.value.status, err.value.code) == (409, "INVALID_TRANSITION")


def test_only_editors_change_status():
    with pytest.raises(ApiError) as err:
        check_transition("REPORTED", "VERIFIED", "viewer")
    assert err.value.status == 403
    assert allowed_next("REPORTED", "public") == []
    assert allowed_next("REPORTED", "officer") == ["DUPLICATE", "REJECTED", "VERIFIED"]


# --- SLA clocks -----------------------------------------------------------------------


def test_federal_deadlines():
    temp, perm = sla.deadlines("FEDERAL", T0)
    assert temp == T0 + timedelta(hours=24)
    assert perm == T0 + timedelta(days=3)


def test_next_deadline_moves_from_temporary_to_permanent():
    temp, perm = sla.deadlines("FEDERAL", T0)
    assert sla.next_deadline("ASSIGNED", temp, perm) == temp
    assert sla.next_deadline("MITIGATED", temp, perm) == perm
    assert sla.next_deadline("RESOLVED", temp, perm) is None


def test_overdue():
    temp, perm = sla.deadlines("FEDERAL", T0)
    later = T0 + timedelta(hours=30)
    assert sla.is_overdue("VERIFIED", temp, perm, later)
    assert not sla.is_overdue("MITIGATED", temp, perm, later)
    assert not sla.is_overdue("REJECTED", temp, perm, later)


def test_unknown_class_has_no_sla():
    assert sla.deadlines("UNKNOWN", T0) == (None, None)


# --- priority maths -------------------------------------------------------------------


def test_default_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_weights_auto_normalise():
    w = normalise_weights({"safety": 2, "usage": 2})
    assert w["safety"] == pytest.approx(0.5)
    assert sum(w.values()) == pytest.approx(1.0)
    assert normalise_weights({}) == DEFAULT_WEIGHTS


def test_contributions_sum_to_score():
    pct = {
        "safety": 0.95,
        "usage": 0.9,
        "severity": 0.97,
        "predicted": 0.88,
        "recurrence": 0.92,
        "criticality": 0.76,
        "sla": 0.8,
    }
    total, components = score(pct, DEFAULT_WEIGHTS, {"criticality"})
    assert total == pytest.approx(sum(c["contribution"] for c in components.values()), abs=0.1)
    assert components["safety"]["contribution"] == pytest.approx(23.75, abs=0.01)
    assert components["criticality"]["estimated"] is True
    assert 0 <= total <= 100


def test_recommended_action_rule_order():
    assert recommended_action(SegmentState("FEDERAL", "JKR Daerah Kinta", open_sinkhole=True, max_pothole_severity=5))[
        1
    ] == ["JKR Daerah Kinta", "JMG"]
    action, refer = recommended_action(
        SegmentState("FEDERAL", "JKR Daerah Kinta", "Belati Wangsa", max_pothole_severity=4)
    )
    assert action.startswith("Temporary patch") and refer == ["Belati Wangsa"]
    assert recommended_action(SegmentState("STATE", potholes_90d=3))[0].startswith("≥3 potholes")
    assert recommended_action(SegmentState("STATE", max_predicted=0.5))[0] == "Preventive inspection"
    assert recommended_action(SegmentState("STATE"))[0] is None


def test_referral_lists_each_agency_once():
    council = "Majlis Bandaraya Ipoh"
    _, refer = recommended_action(SegmentState("MUNICIPAL", council, council, blocking_tree=True, pbt=council))
    assert refer == [council]
