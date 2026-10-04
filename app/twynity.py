"""Twynity discovery and project-scoped Codex connection routes.

The active project comes only from the authenticated ``Persona-Id`` request
header. These routes explicitly verify JWTs because FastMCP's auth provider
does not automatically secure Starlette custom routes.
"""

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.auth import get_identity
from app.config import settings
from app.connection_store import get_active_store
from app.workspaces import validate_branch_name, validate_github_repo_url


def register_routes(mcp):
    @mcp.custom_route("/api/v1/.well-known/mcp.json", methods=["GET"])
    async def manifest(request: Request) -> JSONResponse:
        return JSONResponse({
            "name": settings.APP_TITLE,
            "base_url": f"{settings.PUBLIC_URL.rstrip('/')}/mcp",
            "version": settings.APP_VERSION,
            "external_connections": {"project": {"name": "codex_harness_configuration"}},
        })

    @mcp.custom_route("/api/v1/schema", methods=["GET"])
    async def configuration_schema(request: Request) -> JSONResponse:
        return JSONResponse({
            "name": "codex_harness_configuration",
            "endpoint": "/api/v1/configuration",
            "method": "POST",
            # Rename/extend these example fields for the upstream service.
            "schema": {
                "project_name": "string",
                "repo_url": "string",
                "default_branch": "string (optional; uses GitHub default)",
                "github_token": "string (fine-grained token with repository contents read/write)",
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
        if not isinstance(payload, dict):
            return JSONResponse(
                {"detail": "Configuration must be a JSON object"}, status_code=422
            )
        store = get_active_store()
        if store is None:
            raise HTTPException(status_code=503, detail="Connection storage is not available")
        existing = await store.get(identity.user_id, identity.persona_id)
        project_name = str(payload.get("project_name", "")).strip()
        token = str(payload.get("github_token", "")).strip()
        if not project_name or len(project_name) > 80:
            return JSONResponse(
                {"detail": {"invalid_fields": ["project_name"]}}, status_code=422
            )
        try:
            repo_url = validate_github_repo_url(str(payload.get("repo_url", "")))
            requested_branch = str(payload.get("default_branch", "")).strip()
            default_branch = validate_branch_name(requested_branch) if requested_branch else ""
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        if existing and existing.get("repo_url") != repo_url:
            return JSONResponse(
                {
                    "detail": (
                        "A Twyn is bound to one repository in version one. "
                        "Create another Twyn to connect a different repository."
                    )
                },
                status_code=409,
            )
        if not token and existing:
            token = str(existing.get("github_token", ""))
        if not token:
            return JSONResponse(
                {"detail": {"missing_or_invalid_fields": ["github_token"]}},
                status_code=422,
            )

        parsed_repo = repo_url.removeprefix("https://github.com/").removesuffix(".git")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{parsed_repo}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
            if response.status_code != 200:
                return JSONResponse(
                    {"detail": "GitHub could not access that repository with the supplied token"},
                    status_code=422,
                )
            if not default_branch:
                try:
                    default_branch = validate_branch_name(
                        str(response.json().get("default_branch", ""))
                    )
                except ValueError as exc:
                    return JSONResponse({"detail": "GitHub did not return a valid default branch"}, status_code=422)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Could not validate GitHub access") from exc

        await store.save(
            identity.user_id,
            identity.persona_id,
            {
                "project_name": project_name,
                "repo_url": repo_url,
                "default_branch": default_branch,
                "github_token": token,
            },
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
