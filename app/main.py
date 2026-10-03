"""Compose and expose the FastMCP ASGI application.

Import and register new tools/resources here. Twynity-specific HTTP routes live
in ``twynity.py`` and are separate from FastMCP's JWT-protected MCP transport.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from logging import getLogger

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware as MCPMiddleware
from fastmcp.server.middleware import MiddlewareContext
from pymongo import AsyncMongoClient
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from app.auth import get_auth_provider
from app.config import settings
from app.connection_store import ConnectionStore, set_active_store
from app.license import license_watcher
from app.tools.say_hello import register_tool as register_say_hello
from app.twynity import register_routes
from app.ui.say_hello.resource import register_resource
from app.usage import save_usage_report

logger = getLogger(__name__)

@asynccontextmanager
async def app_lifespan(server):
    mongo = AsyncMongoClient(settings.MONGODB_URI, tz_aware=True)
    task = None
    try:
        store = ConnectionStore(
            mongo[settings.DATABASE_NAME]["project_connections"], settings.ENCRYPTION_KEY
        )
        await store.setup()
        set_active_store(store)
        task = asyncio.create_task(license_watcher())
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        set_active_store(None)
        await mongo.close()

mcp = FastMCP(
    settings.APP_TITLE,
    auth=get_auth_provider(),
    lifespan=app_lifespan,
)


register_say_hello(mcp)

class UsageTrackingMiddleware(MCPMiddleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        try:
            headers = get_http_headers()
            await save_usage_report(
                method="TOOL_CALL",
                endpoint=context.message.name,
                auth_header=headers.get("authorization"),
            )
        except Exception:
            logger.exception("Usage tracking failed — continuing with tool call anyway")

        return await call_next(context)
mcp.add_middleware(UsageTrackingMiddleware())

register_resource(mcp)
register_routes(mcp)


origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "mcp-protocol-version", "mcp-session-id", "Authorization", "Content-Type",
            settings.PERSONA_ID_HEADER,
        ],
        expose_headers=["mcp-session-id"],
    )
]


app = mcp.http_app(middleware=middleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
