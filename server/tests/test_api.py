"""API tests against the PostGIS test database (see conftest.py)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.services import sla
from tests.conftest import sql

ON_FT1 = {"lat": 4.5950, "lng": 101.0850}  # on segment 1, Jalan Sultan Azlan Shah
ON_TAMBUN = {"lat": 4.6125, "lng": 101.1250}  # on segment 2, Jalan Tambun
KINTA_BBOX = "100.9,4.3,101.3,4.9"


def report(client, hazard="POTHOLE", severity=3, at=ON_FT1, **extra):
    return client.post("/api/v1/reports", json={"hazard_type": hazard, "severity": severity, **at, **extra})


# --- basics -------------------------------------------------------------------------------


def test_health_reports_postgis(api):
    body = api().get("/api/v1/health").json()
    assert body["database"]["ok"] and body["database"]["postgis"].startswith("3.")


def test_error_envelope_and_auth(api):
    assert api().get("/api/v1/dashboard/summary").json()["error"]["code"] == "UNAUTHENTICATED"
    assert api("public").get("/api/v1/dashboard/summary").json()["error"]["code"] == "FORBIDDEN"
    assert api().get("/api/v1/map/incidents", params={"bbox": "x"}).json()["error"]["code"] == "VALIDATION_ERROR"


def test_districts_from_database(api):
    assert [d["name"] for d in api().get("/api/v1/meta/districts", params={"state": "A"}).json()] == ["Kinta"]


# --- who owns this road (M2) ----------------------------------------------------------------


def test_locate_returns_owner_and_maintainer(api):
    body = api().get("/api/v1/segments/locate", params=ON_FT1).json()
    assert body["name"] == "Jalan Sultan Azlan Shah" and body["road_class"] == "FEDERAL"
    assert body["owner"]["name"] == "JKR Daerah Kinta"
    assert body["maintainer"]["name"] == "Belati Wangsa (M) Sdn Bhd"
    assert body["distance_m"] < 50


def test_locate_off_road_and_outside_coverage(api):
    c = api()
    far = c.get("/api/v1/segments/locate", params={"lat": 4.70, "lng": 101.20}).json()["error"]
    assert far["code"] == "NOT_ON_ROAD" and far["details"]["distance_m"] > 50
    assert (
        c.get("/api/v1/segments/locate", params={"lat": 1.30, "lng": 103.80}).json()["error"]["code"]
        == "OUTSIDE_COVERAGE"
    )


def test_override_wins_over_computed_owner(api):
    admin = api("admin")
    res = admin.post(
        "/api/v1/admin/jurisdiction-overrides",
        json={
            "segment_id": 3,
            "owner_agency_id": "10000000-0000-4000-8000-000000000002",
            "reason": "Handed over to JKR",
        },
    )
    assert res.status_code == 201
    assert admin.get("/api/v1/segments/3").json()["owner"]["name"] == "JKR Daerah Kinta"


def test_search_by_route_number(api):
    items = api("officer", "A").get("/api/v1/segments/search", params={"q": "FT1"}).json()["items"]
    assert items and items[0]["name"] == "Jalan Sultan Azlan Shah"


def test_map_segments_is_geojson_in_scope(api):
    perak = api("officer", "A").get("/api/v1/map/segments", params={"bbox": "100,1,105,7", "zoom": 15}).json()
    assert {f["properties"]["segment_id"] for f in perak["features"]} == {1, 2, 3}
    kl = api("officer", "KUL").get("/api/v1/map/segments", params={"bbox": "100,1,105,7", "zoom": 15}).json()
    assert {f["properties"]["segment_id"] for f in kl["features"]} == {4}


# --- reporting (M4) -------------------------------------------------------------------------


def test_report_creates_incident_with_sla(api):
    body = report(api("public")).json()
    assert body["ref_no"].startswith("SAR-") and body["status"] == "REPORTED"
    assert body["responsible"] == {"owner": "JKR Daerah Kinta", "maintainer": "Belati Wangsa (M) Sdn Bhd"}
    due = datetime.fromisoformat(body["sla_due_at"])
    assert timedelta(hours=23) < due - datetime.now(UTC) < timedelta(hours=25)  # federal: 24 h


def test_nearby_same_hazard_is_merged(api):
    c = api("public")
    first = report(c).json()
    second = report(c, at={"lat": ON_FT1["lat"] + 0.0001, "lng": ON_FT1["lng"]})
    assert second.status_code == 200 and second.json()["merged_into"] == first["ref_no"]
    assert second.json()["confirmations"] == 2
    assert report(c, hazard="SINKHOLE").status_code == 201  # another hazard type isn't a duplicate


def test_daily_report_limit(api):
    c = api("public")
    for i in range(10):
        assert report(c, at={"lat": 4.5905 + i * 0.0008, "lng": 101.0805 + i * 0.0008}).status_code == 201
    res = report(c, at=ON_TAMBUN)
    assert res.status_code == 429 and res.json()["error"]["code"] == "DAILY_LIMIT"
    assert int(res.headers["retry-after"]) > 0


def test_report_status_only_for_its_reporter_or_staff(api):
    ref = report(api("public")).json()["ref_no"]
    assert api("public").get(f"/api/v1/reports/{ref}").json()["timeline"][0]["status"] == "REPORTED"
    assert api("officer", "A").get(f"/api/v1/reports/{ref}").status_code == 200
    assert api("officer", "KUL").get(f"/api/v1/reports/{ref}").status_code == 404


def test_analyze_falls_back_to_manual_without_ai(api, monkeypatch):
    from app.services import storage

    async def fake_upload(path, data, content_type):
        return None

    monkeypatch.setattr(storage, "upload", fake_upload)
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "grey").save(buf, format="JPEG")
    res = api("public").post(
        "/api/v1/reports/analyze",
        data={"lat": ON_FT1["lat"], "lng": ON_FT1["lng"]},
        files={"photo": ("p.jpg", buf.getvalue(), "image/jpeg")},
    )
    err = res.json()["error"]
    assert res.status_code == 503 and err["code"] == "AI_UNAVAILABLE" and err["details"]["fallback"] == "manual"
    # The photo was kept, so the report can still go in with a manually chosen type (T4.5).
    sub = report(api("public"), analysis_id=err["details"]["analysis_id"])
    assert sub.status_code == 201


# --- incidents (M3) -------------------------------------------------------------------------


def _incident_id(client, ref):
    return next(i["id"] for i in client.get("/api/v1/incidents").json()["items"] if i["ref_no"] == ref)


def test_status_machine_and_timeline(api):
    ref = report(api("public")).json()["ref_no"]
    officer = api("officer", "A")
    inc = _incident_id(officer, ref)
    assert officer.patch(f"/api/v1/incidents/{inc}", json={"status": "VERIFIED"}).json()["status"] == "VERIFIED"
    bad = officer.patch(f"/api/v1/incidents/{inc}", json={"status": "RESOLVED"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "INVALID_TRANSITION"
    actions = [e["action"] for e in officer.get(f"/api/v1/incidents/{inc}/events").json()["items"]]
    assert actions == ["CREATE", "STATUS"]


def test_undo_within_ten_seconds(api):
    ref = report(api("public")).json()["ref_no"]
    officer = api("officer", "A")
    inc = _incident_id(officer, ref)
    officer.patch(f"/api/v1/incidents/{inc}", json={"status": "VERIFIED"})
    assert officer.post(f"/api/v1/incidents/{inc}/undo").json()["status"] == "REPORTED"
    officer.patch(f"/api/v1/incidents/{inc}", json={"status": "VERIFIED"})
    asyncio.run(sql("update incident_events set created_at = now() - interval '11 seconds'"))
    assert officer.post(f"/api/v1/incidents/{inc}/undo").json()["error"]["code"] == "UNDO_EXPIRED"


def test_merge_adds_confirmations(api):
    c = api("public")
    a = report(c).json()["ref_no"]
    b = report(c, at=ON_TAMBUN).json()["ref_no"]
    officer = api("officer", "A")
    a_id, b_id = _incident_id(officer, a), _incident_id(officer, b)
    merged = officer.post(f"/api/v1/incidents/{b_id}/merge", json={"into_id": a_id})
    assert merged.status_code == 200 and merged.json()["confirmations"] == 2
    assert officer.get(f"/api/v1/incidents/{b_id}").json()["status"] == "DUPLICATE"


def test_officer_cannot_touch_another_states_incident(api):
    ref = report(api("public")).json()["ref_no"]
    inc = _incident_id(api("admin"), ref)
    res = api("officer", "KUL").patch(f"/api/v1/incidents/{inc}", json={"status": "VERIFIED"})
    assert res.status_code == 404


def test_public_map_hides_officer_fields(api):
    report(api("public"))
    public = api().get("/api/v1/map/incidents", params={"bbox": KINTA_BBOX}).json()["features"]
    assert public and "refer_to" not in public[0]["properties"] and "description" not in public[0]["properties"]
    staff = api("officer", "A").get("/api/v1/map/incidents", params={"bbox": KINTA_BBOX}).json()["features"]
    assert "refer_to" in staff[0]["properties"] and "allowed_next" in staff[0]["properties"]


@pytest.mark.parametrize(
    ("status", "temp_offset_h", "perm_offset_h"),
    [
        ("REPORTED", -1, 48),
        ("REPORTED", 5, 48),
        ("ASSIGNED", -30, 40),
        ("MITIGATED", -30, 10),
        ("MITIGATED", -30, -2),
        ("RESOLVED", -60, -10),
        ("REJECTED", -60, -10),
    ],
)
def test_overdue_sql_matches_python(api, status, temp_offset_h, perm_offset_h):
    """OVERDUE_SQL is the SQL twin of services.sla.is_overdue; they must never disagree."""
    from app.queries.incidents import OPEN_SQL, OVERDUE_SQL

    now = datetime.now(UTC)
    temp, perm = now + timedelta(hours=temp_offset_h), now + timedelta(hours=perm_offset_h)
    rows = asyncio.run(
        sql(
            f"""
        select ({OPEN_SQL} and {OVERDUE_SQL}) as overdue
        from (select $1::text as status, $2::timestamptz as sla_temp_due_at, $3::timestamptz as sla_perm_due_at) i""",
            status,
            temp,
            perm,
        )
    )
    assert rows[0]["overdue"] == sla.is_overdue(status, temp, perm, now)


# --- priority (M3) --------------------------------------------------------------------------


def test_open_sinkhole_ranks_first_with_explained_score(api):
    report(api("public"), hazard="SINKHOLE", severity=5, at=ON_TAMBUN)
    body = api("officer", "A").get("/api/v1/priority").json()
    top = body["items"][0]
    assert top["name"] == "Jalan Tambun"
    assert top["recommended_action"] == "Close lane; geotechnical investigation"
    assert "Jabatan Mineral dan Geosains Malaysia" in top["refer_to"]
    assert abs(sum(c["contribution"] for c in top["components"].values()) - top["score"]) < 0.2
    assert [i["rank"] for i in body["items"]] == list(range(1, len(body["items"]) + 1))


def test_simulate_reports_rank_change(api):
    report(api("public"), hazard="SINKHOLE", severity=5, at=ON_TAMBUN)
    sim = api("officer", "A").post("/api/v1/priority/simulate", json={"weights": {"usage": 1}}).json()
    assert sim["items"][0]["name"] == "Jalan Sultan Azlan Shah"  # busiest road wins on traffic alone
    assert sim["items"][0]["rank_change"] > 0


def test_dashboard_counts_and_top_roads(api):
    report(api("public"), hazard="SINKHOLE", severity=5, at=ON_TAMBUN)
    body = api("officer", "A").get("/api/v1/dashboard/summary", params={"state": "A"}).json()
    assert body["open_incidents"]["SINKHOLE"] == 1
    assert body["top_roads"][0]["name"] == "Jalan Tambun"


def test_export_csv(api):
    res = api("officer", "A").get("/api/v1/priority/export")
    assert res.status_code == 200 and res.text.splitlines()[0].startswith("rank,segment_id,road")


# --- admin and jobs -------------------------------------------------------------------------


def test_jobs_need_the_cron_secret(api):
    c = api()
    assert c.post("/api/v1/internal/jobs/priority").status_code == 401
    ok = c.post("/api/v1/internal/jobs/priority", headers={"X-Cron-Secret": "test-secret"})
    assert ok.status_code == 200 and ok.json()["status"] == "OK"
    assert c.post("/api/v1/internal/jobs/nope", headers={"X-Cron-Secret": "test-secret"}).status_code == 404


def test_rtvm_import_matches_route(api):
    csv = (
        "station_id,route_ref,state_code,lat,lng,year,adt,heavy_pct\n"
        "PR101,FT1,A,4.5955,101.0855,2024,31000,28\n"
        "PR999,FT5,A,4.70,101.20,2024,9000,10\n"
    )
    body = api("admin").post("/api/v1/admin/import/rtvm", files={"file": ("rtvm.csv", csv, "text/csv")}).json()
    assert body["matched_segments"] == 1 and body["unmatched"][0]["station_id"] == "PR999"
    seg = api("admin").get("/api/v1/segments/1").json()
    assert seg["adt"] == 31000 and seg["adt_source"] == "RTVM 2024"


def test_data_sources_lists_every_job(api):
    jobs = {j["job"] for j in api("admin").get("/api/v1/admin/data-sources").json()["jobs"]}
    assert {"weather", "warnings", "forecast", "news", "priority", "cleanup", "traffic", "flood"} <= jobs


# --- AI guardrails (T7.1, T7.2) -----------------------------------------------------------


def test_explain_falls_back_to_a_template_without_ai(api):
    body = api("officer", "A").post("/api/v1/ai/explain", json={"segment_id": 1, "language": "en"}).json()
    assert body["model"] == "template" and body["ai_suggested"] is False
    assert "Jalan Sultan Azlan Shah" in body["text"]


def test_explain_rejects_invented_numbers():
    from app.api.v1.ai import _numbers_are_grounded

    facts = {"potholes_12m": 7, "adt": 24800, "deaths_3y": 2}
    assert _numbers_are_grounded("7 potholes in a year and 24,800 vehicles a day; 2 deaths.", facts)
    assert not _numbers_are_grounded("About 40 potholes a month.", facts)


def test_assistant_without_ai_says_so(api):
    res = api("officer", "A").post("/api/v1/ai/assistant", json={"message": "Which roads in Kinta first?"})
    assert res.status_code == 503 and res.json()["error"]["code"] == "AI_UNAVAILABLE"


def test_ai_result_is_stored_as_a_json_object(api, monkeypatch):
    """Regression: with the asyncpg JSON codec, pre-serialised strings were stored double-encoded."""
    import io

    from PIL import Image

    from app.services import gemini, storage

    async def fake_upload(path, data, content_type):
        return None

    async def fake_classify(session, image, mime):
        return gemini.PhotoAnalysis(
            is_road_hazard=True,
            hazard_type="POTHOLE",
            severity=4,
            confidence=0.9,
            reasons=["Broken asphalt"],
            faces_visible=False,
            plates_visible=False,
        )

    monkeypatch.setattr(storage, "upload", fake_upload)
    monkeypatch.setattr(gemini, "classify_photo", fake_classify)
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "grey").save(buf, format="JPEG")
    c = api("public")
    analysis = c.post(
        "/api/v1/reports/analyze",
        data={"lat": ON_FT1["lat"], "lng": ON_FT1["lng"]},
        files={"photo": ("p.jpg", buf.getvalue(), "image/jpeg")},
    ).json()
    assert analysis["suggested_type"] == "POTHOLE" and analysis["ai_suggested"]
    assert report(c, severity=4, analysis_id=analysis["analysis_id"]).status_code == 201
    rows = asyncio.run(sql("select jsonb_typeof(ai_result) as t, ai_result->>'hazard_type' as h from incidents"))
    assert (rows[0]["t"], rows[0]["h"]) == ("object", "POTHOLE")


def test_top_factors_read_back_in_the_documented_shape(api):
    """Predictions store factors as compact triples (migration 0006); older rows used objects.
    Both must come back as [{feature, value, direction}]."""
    asyncio.run(
        sql(
            """
            insert into predictions (segment_id, hazard_type, horizon_days, probability, risk_level, top_factors,
                                     model_version)
            values (1, 'POTHOLE', 7, 0.4, 'HIGH', '[["rain_3d", 42.0, 1], ["length_km", 0.5, -1]]', 'test'),
                   (1, 'POTHOLE', 30, 0.5, 'HIGH', '[{"feature": "adt_k", "value": 12, "direction": "up"}]', 'test')"""
        )
    )
    try:
        items = api("admin").get("/api/v1/predictions/segments/1").json()["items"]
        by_horizon = {i["horizon_days"]: i["top_factors"] for i in items}
        assert by_horizon[7] == [
            {"feature": "rain_3d", "value": 42.0, "direction": "up"},
            {"feature": "length_km", "value": 0.5, "direction": "down"},
        ]
        assert by_horizon[30] == [{"feature": "adt_k", "value": 12, "direction": "up"}]
    finally:
        asyncio.run(sql("delete from predictions where model_version = 'test'"))


def test_special_zone_lists_and_summarises_the_roads_inside_it(api):
    """FR-ZON-02: a karst zone is listed by type and its summary covers the segments it touches."""
    rows = asyncio.run(
        sql(
            """
            insert into zones (type, name, geom)
            values ('KARST', 'Test limestone', ST_Multi(ST_Buffer(ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                                                                 300)::geometry))
            returning id::text""",
            ON_FT1["lng"],
            ON_FT1["lat"],
        )
    )
    zone_id = rows[0]["id"]
    try:
        c = api("admin")
        listed = c.get("/api/v1/zones", params={"type": "KARST"}).json()
        assert [z["name"] for z in listed] == ["Test limestone"]
        summary = c.get(f"/api/v1/zones/{zone_id}/summary").json()
        assert summary["zone"]["type"] == "KARST"
        assert summary["segments"] >= 1
        assert 1 in [r["segment_id"] for r in summary["top_roads"]]
    finally:
        asyncio.run(sql("delete from zones where id = cast($1 as uuid)", zone_id))
