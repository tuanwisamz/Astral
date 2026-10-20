"""Settings (plan A3): GET /me and DELETE /me, with anonymisation and the last-admin rule (D14)."""

import asyncio

import pytest

from app.core.errors import ApiError
from app.services import clerk
from tests.conftest import sql
from tests.test_api import report

# Every column that stores a Clerk user ID (see app/api/v1/me.py ANONYMISE).
IDENTITY_COLUMNS = [
    ("incidents", "reported_by"),
    ("incident_events", "actor"),
    ("report_analyses", "clerk_id"),
    ("priority_profiles", "created_by"),
    ("zones", "created_by"),
    ("jurisdiction_overrides", "created_by"),
    ("usage_daily", "clerk_id"),
    ("app_users", "clerk_id"),
]


def mentions(clerk_id: str) -> dict[str, int]:
    async def count():
        out = {}
        for table, col in IDENTITY_COLUMNS:
            out[f"{table}.{col}"] = (await sql(f"select count(*) as n from {table} where {col} = $1", clerk_id))[0]["n"]
        return out

    return {k: v for k, v in asyncio.run(count()).items() if v}


@pytest.fixture
def clerk_calls(monkeypatch):
    calls = {"deleted": [], "admins": 2}

    async def fake_delete(clerk_id):
        calls["deleted"].append(clerk_id)

    async def fake_count():
        return calls["admins"]

    monkeypatch.setattr(clerk, "delete_user", fake_delete)
    monkeypatch.setattr(clerk, "count_admins", fake_count)
    return calls


def test_me_shows_role_area_and_report_count(api):
    c = api("public")
    assert report(c).status_code == 201
    body = c.get("/api/v1/me").json()
    assert (body["role"], body["reports"], body["state"]) == ("public", 1, None)
    staff = api("officer", "A").get("/api/v1/me").json()
    assert staff["role"] == "officer" and staff["state"] == {"code": "A", "name": "Perak"}


def test_me_needs_sign_in(api):
    assert api().get("/api/v1/me").status_code == 401
    assert api().delete("/api/v1/me").status_code == 401


def test_deleting_an_account_anonymises_and_keeps_the_hazard(api, clerk_calls):
    c = api("public")
    ref = report(c).json()["ref_no"]
    assert mentions("dev-public")  # the report links to the person before deletion

    assert c.delete("/api/v1/me").status_code == 204
    assert clerk_calls["deleted"] == ["dev-public"]
    assert mentions("dev-public") == {}
    # The hazard is still there for officers, just without a reporter.
    rows = asyncio.run(sql("select reported_by from incidents where ref_no = $1", ref))
    assert len(rows) == 1 and rows[0]["reported_by"] is None
    assert c.get("/api/v1/reports/mine").json()["items"] == []


def test_the_last_admin_cannot_delete_their_account(api, clerk_calls):
    clerk_calls["admins"] = 1
    res = api("admin").delete("/api/v1/me")
    assert res.status_code == 409 and res.json()["error"]["code"] == "LAST_ADMIN"
    assert clerk_calls["deleted"] == []
    clerk_calls["admins"] = 2
    assert api("admin").delete("/api/v1/me").status_code == 204


def test_nothing_is_anonymised_if_clerk_fails(api, clerk_calls, monkeypatch):
    async def down(clerk_id):
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Clerk can't be reached right now")

    monkeypatch.setattr(clerk, "delete_user", down)
    c = api("public")
    report(c)
    assert c.delete("/api/v1/me").status_code == 503
    assert mentions("dev-public").get("incidents.reported_by") == 1
