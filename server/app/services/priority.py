"""Priority score maths and recommended actions (spec §6, plan D1).

Percentile ranks are computed in SQL per scope; this module combines them.
"""

from dataclasses import dataclass, field

COMPONENTS = ("safety", "usage", "severity", "predicted", "recurrence", "criticality", "sla")

DEFAULT_WEIGHTS = {
    "safety": 0.25,
    "usage": 0.20,
    "severity": 0.20,
    "predicted": 0.15,
    "recurrence": 0.10,
    "criticality": 0.05,
    "sla": 0.05,
}


def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    clean = {k: max(0.0, float(weights.get(k, 0.0))) for k in COMPONENTS}
    total = sum(clean.values())
    if total == 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in clean.items()}


def score(percentiles: dict[str, float], weights: dict[str, float], estimated: frozenset[str] | set[str] = frozenset()):
    """Return (score 0–100, components) where contributions sum to the score."""
    w = normalise_weights(weights)
    components = {}
    for name in COMPONENTS:
        value = min(1.0, max(0.0, percentiles.get(name, 0.0)))
        components[name] = {
            "value": round(value, 4),
            "contribution": round(100 * w[name] * value, 2),
            "estimated": name in estimated,
        }
    total = round(sum(100 * w[n] * components[n]["value"] for n in COMPONENTS), 1)
    return total, components


@dataclass
class SegmentState:
    road_class: str
    owner: str | None = None
    maintainer: str | None = None
    open_sinkhole: bool = False
    blocking_tree: bool = False
    max_pothole_severity: int = 0
    potholes_90d: int = 0
    max_predicted: float = 0.0
    open_incidents: int = 0
    pbt: str | None = None
    refer_extra: list[str] = field(default_factory=list)


HIGH_PREDICTED = 0.4  # HIGH risk level and above


def recommended_action(s: SegmentState) -> tuple[str | None, list[str]]:
    """First matching rule from spec §6, with each agency referred to once."""
    action, refer_to = _first_rule(s)
    return action, list(dict.fromkeys(refer_to))


def _first_rule(s: SegmentState) -> tuple[str | None, list[str]]:
    owner = [s.owner] if s.owner else []
    if s.open_sinkhole:
        return "Close lane; geotechnical investigation", owner + ["JMG"]
    if s.blocking_tree:
        return "Clear immediately", owner + ([s.pbt] if s.pbt else ["PBT / landscape unit"])
    if s.road_class == "FEDERAL" and s.max_pothole_severity >= 4:
        return "Temporary patch ≤24 h, permanent ≤3 days", [s.maintainer or "Zone concessionaire"]
    if s.potholes_90d >= 3:
        return "≥3 potholes in 90 days: investigate base/drainage; resurface instead of patching", owner
    if s.max_predicted >= HIGH_PREDICTED and s.open_incidents == 0:
        return "Preventive inspection", owner
    return None, owner
