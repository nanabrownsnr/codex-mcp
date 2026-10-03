"""Protect the JWT verifier contract and custom-route auth expectations.

Extend these tests when changing account-service authentication or route policy.
"""

import pytest
from fastmcp import FastMCP

from app.auth import get_auth_provider, get_identity_from_headers
from app.twynity import register_routes


@pytest.fixture
def authenticated_app():
    mcp = FastMCP("test_server", auth=get_auth_provider())
    register_routes(mcp)
    return mcp.http_app()


def test_auth_provider_uses_the_configured_jwks_endpoint():
    provider = get_auth_provider()

    assert provider.jwks_uri == "http://account.invalid/.well-known/jwks.json"
    assert provider.algorithm == "RS256"
    assert provider.audience == "starter_mcp"


@pytest.mark.asyncio
async def test_identity_requires_bearer_token_and_persona_header():
    from starlette.exceptions import HTTPException

    with pytest.raises(HTTPException) as missing_token:
        await get_identity_from_headers({"persona-id": "persona-1"})
    assert missing_token.value.status_code == 401

    with pytest.raises(HTTPException) as missing_persona:
        await get_identity_from_headers({"authorization": "Bearer token"})
    assert missing_persona.value.status_code == 400


def test_custom_health_route_is_not_implicitly_jwt_protected(authenticated_app):
    """Custom routes need explicit auth even when FastMCP has a JWT verifier."""
    from starlette.testclient import TestClient

    response = TestClient(authenticated_app).get("/api/v1/health")

    assert response.status_code == 200
