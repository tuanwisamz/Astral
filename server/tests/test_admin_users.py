import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import clerk

CLERK_USER = {
    "id": "user_123",
    "primary_email_address_id": "em_1",
    "email_addresses": [{"id": "em_1", "email_address": "aminah@example.com"}],
    "public_metadata": {},
    "created_at": 1760000000000,
}


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_AUTH_ROLE", "admin")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("CLERK_SECRET_KEY", "")
    get_settings.cache_clear()
    sent: list[dict] = []

    async def fake_update(clerk_id, scope):
        sent.append(scope)
        meta = {k: v for k, v in scope.items() if v is not None}
        return clerk.to_user({**CLERK_USER, "id": clerk_id, "public_metadata": meta})

    monkeypatch.setattr(clerk, "update_scope", fake_update)
    yield TestClient(app), sent
    get_settings.cache_clear()


def test_promote_public_to_officer(admin):
    client, sent = admin
    res = client.patch("/api/v1/admin/users/user_123", json={"role": "officer", "state_code": "A"})
    assert res.status_code == 200
    assert res.json()["role"] == "officer"
    assert res.json()["email"] == "aminah@example.com"
    assert sent == [{"role": "officer", "state_code": "A"}]


def test_officer_needs_a_state(admin):
    client, _ = admin
    res = client.patch("/api/v1/admin/users/user_123", json={"role": "officer"})
    assert res.status_code == 422
    assert "state_code" in res.json()["error"]["message"]


def test_unknown_role_rejected(admin):
    client, _ = admin
    assert client.patch("/api/v1/admin/users/user_123", json={"role": "superuser"}).status_code == 422


def test_demoting_to_public_clears_scope(admin):
    client, sent = admin
    client.patch("/api/v1/admin/users/user_123", json={"role": "public"})
    assert sent[-1] == {"role": "public", "state_code": None, "district_id": None, "agency_id": None}


def test_listing_without_secret_key_explains_what_is_missing(admin):
    client, _ = admin
    res = client.get("/api/v1/admin/users")
    assert res.status_code == 503
    assert "CLERK_SECRET_KEY" in res.json()["error"]["message"]


def test_non_admin_cannot_change_roles(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEV_AUTH_ROLE", "officer")
    get_settings.cache_clear()
    res = TestClient(app).patch("/api/v1/admin/users/user_123", json={"role": "admin"})
    get_settings.cache_clear()
    assert res.status_code == 403


async def test_role_falls_back_to_clerk_when_token_has_no_claims(monkeypatch):
    from app.core import auth

    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_x")
    get_settings.cache_clear()

    async def fake_meta(clerk_id):
        return {"role": "officer", "state_code": "A"}

    monkeypatch.setattr(clerk, "public_metadata", fake_meta)
    user = auth.user_from_claims(await auth.scope_claims({"sub": "user_1"}))
    assert (user.role, user.state_code) == ("officer", "A")
    # A token that already carries the template's claims is trusted as is.
    assert (await auth.scope_claims({"sub": "user_1", "role": "viewer"}))["role"] == "viewer"
    get_settings.cache_clear()


async def test_failed_clerk_lookup_means_public(monkeypatch):
    from app.core import auth
    from app.core.errors import ApiError

    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_x")
    get_settings.cache_clear()

    async def down(clerk_id):
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "down")

    monkeypatch.setattr(clerk, "public_metadata", down)
    assert auth.user_from_claims(await auth.scope_claims({"sub": "user_1"})).role == "public"
    get_settings.cache_clear()


def test_to_user_reads_primary_email_and_defaults_role():
    user = clerk.to_user(CLERK_USER)
    assert user == {
        "clerk_id": "user_123",
        "email": "aminah@example.com",
        "role": "public",
        "state_code": None,
        "district_id": None,
        "agency_id": None,
        "created_at": 1760000000000,
    }
