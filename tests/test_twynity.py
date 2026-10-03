"""Verify Twynity's public manifest and health custom routes.

Extend this module when adding or changing custom HTTP routes in twynity.py.
"""

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from app.auth import TwynityIdentity
from app.twynity import register_routes


@pytest.fixture
def unauthenticated_app():
    """No auth attached — manifest/health should work without a token."""
    mcp = FastMCP("test_server")
    register_routes(mcp)
    return mcp.http_app()


def test_manifest_returns_expected_shape(unauthenticated_app):
    client = TestClient(unauthenticated_app)
    response = client.get("/api/v1/.well-known/mcp.json")

    assert response.status_code == 200
    body = response.json()
    assert "name" in body
    assert "version" in body

def test_health_endpoint_returns_ok(unauthenticated_app):
    client = TestClient(unauthenticated_app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class FakeStore:
    def __init__(self):
        self.saved = None

    async def save(self, user_id, persona_id, values):
        self.saved = (user_id, persona_id, values)

    async def public_metadata(self, user_id, persona_id):
        if self.saved and self.saved[:2] == (user_id, persona_id):
            values = self.saved[2]
            return {"id": "connection-id", "name": values["name"], "base_url": values["base_url"]}
        return None


def test_manifest_declares_project_connection(unauthenticated_app):
    response = TestClient(unauthenticated_app).get("/api/v1/.well-known/mcp.json")
    assert response.json()["external_connections"] == {
        "project": {"name": "mcp_configuration"}
    }


def test_configuration_schema_describes_required_input(unauthenticated_app):
    response = TestClient(unauthenticated_app).get("/api/v1/schema")
    assert response.status_code == 200
    assert response.json()["schema"]["api_secret"] == "string"


def test_configuration_upsert_get_and_me_are_project_scoped(monkeypatch):
    import app.twynity as routes

    identity = TwynityIdentity(user_id="user-1", persona_id="persona-1")
    store = FakeStore()
    monkeypatch.setattr(routes, "get_identity", lambda _request: _identity(identity))
    monkeypatch.setattr(routes, "get_active_store", lambda: store)
    mcp = FastMCP("test_config")
    register_routes(mcp)
    client = TestClient(mcp.http_app())
    headers = {"Authorization": "Bearer verified-by-test", "Persona-Id": "persona-1"}
    payload = {
        "name": "CRM", "base_url": "https://crm.example", "api_key": "key",
        "api_secret": "secret",
    }

    created = client.post("/api/v1/configuration", json=payload, headers=headers)
    assert created.status_code == 200
    assert created.json() == {"configured": True}
    assert store.saved == ("user-1", "persona-1", payload)
    fetched = client.get("/api/v1/configuration", headers=headers)
    assert fetched.json() == {
        "items": [{"id": "connection-id", "name": "CRM", "base_url": "https://crm.example"}],
        "item_count": 1,
        "next_cursor": None,
    }
    assert "api_secret" not in fetched.text and "api_key" not in fetched.text
    assert client.get("/api/v1/external-connection/me", headers=headers).json() == {"connected": True}


async def _identity(value):
    return value


def test_configuration_rejects_missing_fields(monkeypatch):
    import app.twynity as routes

    monkeypatch.setattr(
        routes,
        "get_identity",
        lambda _request: _identity(TwynityIdentity(user_id="user-1", persona_id="persona-1")),
    )
    monkeypatch.setattr(routes, "get_active_store", lambda: FakeStore())
    mcp = FastMCP("test_config_validation")
    register_routes(mcp)
    response = TestClient(mcp.http_app()).post(
        "/api/v1/configuration",
        json={"name": "CRM"},
        headers={"Authorization": "Bearer test", "Persona-Id": "persona-1"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["missing_or_invalid_fields"] == [
        "base_url", "api_key", "api_secret"
    ]
