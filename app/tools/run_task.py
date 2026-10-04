"""Register the Twynity project task tools."""

from fastmcp.server.dependencies import get_http_headers
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from starlette.exceptions import HTTPException

from app.auth import get_identity_from_headers
from app.codex_runtime import get_active_runtime
from app.ui.task_result.resource import VIEW_URI


def register_tools(mcp):
    @mcp.tool(app=AppConfig(resource_uri=VIEW_URI, visibility=["model", "app"]))
    async def run_task(task: str) -> ToolResult:
        """Run or continue the Codex conversation assigned to the active Twyn.

        Use this when the user asks the coding agent to change, investigate, or
        explain code in the repository configured for this Twyn. The authenticated
        Twynity context selects the project; do not ask for or invent a local path,
        repository URL, user ID, persona ID, GitHub token, or OpenAI key.
        The tool starts the Codex session on first use and resumes it on later
        calls. Completed commits are pushed to the Twyn's dedicated work branch.

        Args:
            task: A concrete coding request for the configured repository.

        Returns:
            Project name, completion status, branch, commit, and Codex response.
        """
        identity = await get_identity_from_headers(get_http_headers())
        runtime = get_active_runtime()
        if runtime is None:
            raise HTTPException(status_code=503, detail="Codex runtime is not available")
        if not task.strip():
            raise HTTPException(status_code=422, detail="Task description cannot be empty")
        if len(task) > 20000:
            raise HTTPException(status_code=413, detail="Task description is too long")
        result = await runtime.run_task(
            user_id=identity.user_id,
            persona_id=identity.persona_id,
            task=task.strip(),
        )
        branch_text = f"Published {result['branch']}" if result["published"] else "No new commit to publish"
        return ToolResult(
            content=f"{result['project_name']}: {result['status']}. {branch_text}.\n{result['response']}",
            structured_content=result,
            meta={"ui": {"resourceUri": VIEW_URI}, "ui/resourceUri": VIEW_URI},
        )

    @mcp.tool
    async def get_task_status() -> dict:
        """Show the status of the project assigned to the active Twyn.

        Use this when the user asks whether the last Codex task completed or
        which branch it published. The tool only returns state for the verified
        Twynity user and Persona-Id on this request.
        """
        identity = await get_identity_from_headers(get_http_headers())
        runtime = get_active_runtime()
        if runtime is None:
            raise HTTPException(status_code=503, detail="Codex runtime is not available")
        result = await runtime.task_status(
            user_id=identity.user_id,
            persona_id=identity.persona_id,
        )
        if result is None:
            return {"status": "not_started"}
        return result
