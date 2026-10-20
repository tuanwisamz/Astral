import pytest

from app.services.jurisdiction import classify, federal_zone, normalise_refs, responsible


@pytest.mark.parametrize(
    ("ref", "highway", "road_class", "category", "state"),
    [
        ("1", "trunk", "FEDERAL", "MAIN", None),
        ("FT1", "trunk", "FEDERAL", "MAIN", None),
        ("FT 5", "primary", "FEDERAL", "MAIN", None),
        ("59A", "primary", "FEDERAL", "MAIN", None),
        ("FT250", "secondary", "FEDERAL", "INSTITUTIONAL", None),
        ("1234", "tertiary", "FEDERAL", "FELDA_FELCRA", None),
        ("3105", "tertiary", "FEDERAL", "INDUSTRIAL", None),
        ("500", "secondary", "FEDERAL", None, None),
        ("A117", "secondary", "STATE", None, "A"),
        ("b34", "secondary", "STATE", None, "B"),
        ("E2", "motorway", "EXPRESSWAY", None, None),
        ("A15;E1", "motorway", "EXPRESSWAY", None, None),  # precedence: expressway first
        ("A15;FT1", "trunk", "FEDERAL", "MAIN", None),
        ("AH2;FT1", "trunk", "FEDERAL", "MAIN", None),  # Asian Highway ref is ignored
        (None, "motorway", "EXPRESSWAY", None, None),
        (None, "residential", "MUNICIPAL", None, None),
        ("", "service", "MUNICIPAL", None, None),
        (None, "living_street", "MUNICIPAL", None, None),
        (None, "primary", "UNKNOWN", None, None),
        ("AH2", "primary", "UNKNOWN", None, None),
    ],
)
def test_classify(ref, highway, road_class, category, state):
    result = classify(ref, highway)
    assert (result.road_class, result.federal_category, result.state_code) == (road_class, category, state)


def test_source_marks_ref_versus_rule():
    assert classify("FT1", "trunk").source == "REF_TAG"
    assert classify(None, "residential").source == "RULE"


def test_normalise_refs():
    assert normalise_refs(" ft 1 ; e1 ") == ["FT1", "E1"]
    assert normalise_refs(None) == []


@pytest.mark.parametrize(
    ("road_class", "state", "district", "pbt", "operator", "owner", "maintainer"),
    [
        ("FEDERAL", "A", "Kinta", None, None, "JKR_DISTRICT:A:Kinta", "FED_MAINT:NORTH"),
        ("FEDERAL", "B", "Petaling", None, None, "JKR_DISTRICT:B:Petaling", "FED_MAINT:CENTRAL_EAST"),
        ("FEDERAL", "J", "Johor Bahru", None, None, "JKR_DISTRICT:J:Johor Bahru", "FED_MAINT:SOUTH"),
        ("FEDERAL", "KUL", "Kuala Lumpur", None, None, "JKR_STATE:KUL", "FED_MAINT:FT"),
        ("STATE", "A", "Kinta", None, None, "JKR_STATE:A", "JKR_DISTRICT:A:Kinta"),
        ("MUNICIPAL", "A", "Kinta", "PBT:MBI", None, "PBT:MBI", "PBT:MBI"),
        ("MUNICIPAL", "A", "Kinta", None, None, "JKR_DISTRICT:A:Kinta", "JKR_DISTRICT:A:Kinta"),
        ("EXPRESSWAY", "B", "Gombak", None, "EXPRESSWAY:PLUS", "LLM", "EXPRESSWAY:PLUS"),
        ("EXPRESSWAY", "B", "Gombak", None, None, "LLM", "EXPRESSWAY:UNKNOWN"),
    ],
)
def test_responsible(road_class, state, district, pbt, operator, owner, maintainer):
    r = responsible(road_class, state, district, pbt, operator)
    assert (r.owner, r.maintainer, r.flagged) == (owner, maintainer, False)


def test_unknown_roads_are_flagged_for_review():
    assert responsible("UNKNOWN", "A", "Kinta").flagged


def test_federal_zones():
    assert federal_zone("A") == "NORTH"
    assert federal_zone("B") == "CENTRAL_EAST"
    assert federal_zone("J") == "SOUTH"
    assert federal_zone("KUL") == "FT"
    assert federal_zone("X") is None
