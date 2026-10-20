"""Road classification from OSM tags (architechture.md §7 step 3, plan §3 M1).

Pure functions, so the OSM loader script and the API share one implementation.
"""

import re
from dataclasses import dataclass

from app.services.domain import STATES

_EXPRESSWAY = re.compile(r"^E\d+[A-Z]?$")
_FEDERAL = re.compile(r"^(?:FT)?(\d+)[A-Z]?$")
_STATE = re.compile(r"^([ABCDJKMNPRT])\d+[A-Z]?$")

# architechture.md §7 lists residential, service, unclassified and tertiary; living_street is a
# residential street by definition, so it belongs here too.
_MUNICIPAL_HIGHWAYS = {"residential", "service", "unclassified", "tertiary", "living_street"}

# Precedence when a ref holds several values: most authoritative first.
_PRECEDENCE = ("EXPRESSWAY", "FEDERAL", "STATE")


@dataclass(frozen=True)
class Classification:
    road_class: str  # FEDERAL | STATE | MUNICIPAL | EXPRESSWAY | UNKNOWN
    ref: str | None = None
    federal_category: str | None = None  # MAIN | INSTITUTIONAL | FELDA_FELCRA | INDUSTRIAL
    state_code: str | None = None  # from a state route letter
    source: str = "REF_TAG"  # REF_TAG | RULE


def normalise_refs(ref: str | None) -> list[str]:
    if not isinstance(ref, str) or not ref:  # None, or NaN from a pandas column
        return []
    return [part.upper().replace(" ", "") for part in ref.split(";") if part.strip()]


def federal_category(number: int) -> str | None:
    if 1 <= number <= 249:
        return "MAIN"
    if 250 <= number <= 479:
        return "INSTITUTIONAL"
    if 1000 <= number <= 2999:
        return "FELDA_FELCRA"
    if 3000 <= number <= 3999:
        return "INDUSTRIAL"
    return None


def _classify_one(ref: str) -> Classification | None:
    if _EXPRESSWAY.match(ref):
        return Classification("EXPRESSWAY", ref)
    if m := _FEDERAL.match(ref):
        return Classification("FEDERAL", ref, federal_category=federal_category(int(m.group(1))))
    if m := _STATE.match(ref):
        return Classification("STATE", ref, state_code=m.group(1))
    return None


def classify(ref: str | None, highway: str | None) -> Classification:
    found = [c for c in map(_classify_one, normalise_refs(ref)) if c]
    if found:
        return min(found, key=lambda c: _PRECEDENCE.index(c.road_class))
    if highway == "motorway":
        return Classification("EXPRESSWAY", source="RULE")
    if highway in _MUNICIPAL_HIGHWAYS:
        return Classification("MUNICIPAL", source="RULE")
    return Classification("UNKNOWN", source="RULE")


def federal_zone(state_code: str) -> str | None:
    state = STATES.get(state_code)
    return state[1] if state else None


# Agency keys are stable strings; the loader turns them into uuid5 ids, so a reload keeps the
# same ids and the district_id/agency_id stored in Clerk metadata stay valid.
def jkr_state_key(state_code: str) -> str:
    return f"JKR_STATE:{state_code}"


def jkr_district_key(state_code: str, district: str) -> str:
    # The Federal Territories have no JKR Daerah; their JKR office covers the whole territory.
    return (
        jkr_state_key(state_code)
        if STATES.get(state_code, ("", ""))[1] == "FT"
        else f"JKR_DISTRICT:{state_code}:{district}"
    )


def zone_maintainer_key(state_code: str) -> str:
    return f"FED_MAINT:{federal_zone(state_code)}"


@dataclass(frozen=True)
class Responsibility:
    owner: str
    maintainer: str
    flagged: bool = False  # needs an officer's review (UNKNOWN class)


def responsible(
    road_class: str,
    state_code: str,
    district: str,
    pbt_key: str | None = None,
    operator_key: str | None = None,
) -> Responsibility:
    """Owner and maintainer agency keys for a segment (spec §2, architechture.md §7 step 4)."""
    daerah = jkr_district_key(state_code, district)
    if road_class == "FEDERAL":
        return Responsibility(daerah, zone_maintainer_key(state_code))
    if road_class == "STATE":
        return Responsibility(jkr_state_key(state_code), daerah)
    if road_class == "EXPRESSWAY":
        return Responsibility("LLM", operator_key or "EXPRESSWAY:UNKNOWN")
    if road_class == "MUNICIPAL":
        council = pbt_key or daerah  # no council polygon: fall back to the district (§7 step 4)
        return Responsibility(council, council)
    return Responsibility(daerah, daerah, flagged=True)
