"""Twynity discovery and project-scoped external-connection routes.

The active project comes only from the authenticated ``Persona-Id`` request
header. These routes explicitly verify JWTs because FastMCP's auth provider
does not automatically secure Starlette custom routes.
"""

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth import get_identity
from app.config import settings
from app.connection_store import get_active_store


def register_routes(mcp):
    @mcp.custom_route("/api/v1/.well-known/mcp.json", methods=["GET"])
    async def manifest(request: Request) -> JSONResponse:
        return JSONResponse({
            "name": settings.APP_TITLE,
            "base_url": f"{settings.PUBLIC_URL.rstrip('/')}/mcp",
            "version": settings.APP_VERSION,
            "external_connections": {"project": {"name": "mcp_configuration"}},
        })

    @mcp.custom_route("/api/v1/schema", methods=["GET"])
    async def configuration_schema(request: Request) -> JSONResponse:
        return JSONResponse({
            "name": "mcp_configuration",
            "endpoint": "/api/v1/configuration",
            "method": "POST",
            # Rename/extend these example fields for the upstream service.
            "schema": {
                "name": "string",
                "base_url": "string",
                "api_key": "string",
                "api_secret": "string",
            },
        })

    @mcp.custom_route("/api/v1/configuration", methods=["OPTIONS"])
    async def configuration_options(request: Request) -> JSONResponse:
        return JSONResponse({}, headers={"Allow": "GET, POST, OPTIONS"})

    @mcp.custom_route("/api/v1/configuration", methods=["POST"])
    async def save_configuration(request: Request) -> JSONResponse:
        identity = await get_identity(request)
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"detail": "Request body must be valid JSON"}, status_code=400)
        required = ("name", "base_url", "api_key", "api_secret")
        invalid = [key for key in required if not isinstance(payload, dict) or not str(payload.get(key, "")).strip()]
        if invalid:
            return JSONResponse(
                {"detail": {"missing_or_invalid_fields": invalid}}, status_code=422
            )
        store = get_active_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Connection storage is not available")
        await store.save(
            identity.user_id,
            identity.persona_id,
            {key: str(payload[key]).strip() for key in required},
        )
        return JSONResponse({"configured": True})

    @mcp.custom_route("/api/v1/configuration", methods=["GET"])
    async def get_configuration(request: Request) -> JSONResponse:
        identity = await get_identity(request)
        store = get_active_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Connection storage is not available")
        metadata = await store.public_metadata(identity.user_id, identity.persona_id)
        items = [metadata] if metadata else []
        return JSONResponse({"items": items, "item_count": len(items), "next_cursor": None})

    @mcp.custom_route("/api/v1/external-connection/me", methods=["GET"])
    async def external_connection_me(request: Request) -> JSONResponse:
        identity = await get_identity(request)
        store = get_active_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Connection storage is not available")
        connected = await store.public_metadata(identity.user_id, identity.persona_id) is not None
        return JSONResponse({"connected": connected})

    @mcp.custom_route("/api/v1/health", methods=["GET"])
    async def health_status(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})
