"""Helpers for tools that need the active project's stored service credentials."""

from fastmcp.server.dependencies import get_http_headers
from starlette.exceptions import HTTPException

from app.auth import get_identity_from_headers
from app.connection_store import get_active_store


async def get_current_connection() -> dict | None:
    """Return decrypted credentials for the verified user/persona pair.

    Call this inside a tool handler. Never accept user_id/persona_id as tool
    arguments: the MCP host supplies the verified bearer token and Persona-Id
    headers. Raises an actionable auth error if either is missing or invalid.
    """
    identity = await get_identity_from_headers(get_http_headers())
    store = get_active_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Connection storage is not available")
    return await store.get(identity.user_id, identity.persona_id)
