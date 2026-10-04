"""Orchestrate the OpenAI-managed Codex harness and a local executor."""

import asyncio
import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.executor import ExecutorManager
from app.publisher import publish_branch
from app.workspaces import WorkspaceManager, workspace_key

logger = logging.getLogger(__name__)
_active_runtime: "CodexRuntime | None" = None


def set_active_runtime(runtime: "CodexRuntime | None") -> None:
    global _active_runtime
    _active_runtime = runtime


def get_active_runtime() -> "CodexRuntime | None":
    return _active_runtime

INSTRUCTIONS = """You are Twynity's coding agent for one assigned repository.
Work only in /workspace. Make the requested code changes and run relevant
checks when useful. Commit completed changes locally with a concise message.
Never attempt to push, publish, or change the Git remote. The Twynity publisher
handles branch publishing after your turn completes. Do not ask for or search
for GitHub credentials; they are not available in your workspace.
"""


class CodexRuntimeError(RuntimeError):
    """A Codex session or executor could not complete the requested task."""


class CodexRuntime:
    def __init__(self, connection_store, agent_store, workspace_manager: WorkspaceManager,
                 executor_manager: ExecutorManager, openai_client):
        self.connection_store = connection_store
        self.agent_store = agent_store
        self.workspace_manager = workspace_manager
        self.executor_manager = executor_manager
        self.openai = openai_client
        self._hooks_dir = Path(settings.WORKSPACE_ROOT).expanduser().resolve() / ".empty-hooks"
        self._hooks_dir.mkdir(parents=True, exist_ok=True)

    async def run_task(self, *, user_id: str, persona_id: str, task: str) -> dict:
        if not settings.OPENAI_API_KEY:
            raise CodexRuntimeError("The shared OpenAI API key is not configured")
        if not settings.OPENAI_EXECUTOR_API_KEY:
            raise CodexRuntimeError("The restricted OpenAI executor key is not configured")

        connection = await self.connection_store.get(user_id, persona_id)
        if not connection:
            raise CodexRuntimeError("Set up a project and GitHub connection for this Twyn first")

        if await self.agent_store.get(user_id, persona_id) is None:
            await self.agent_store.save(
                user_id,
                persona_id,
                {
                    "status": "idle",
                    "project_name": connection["project_name"],
                    "repo_url": connection["repo_url"],
                    "default_branch": connection["default_branch"],
                    "workspace_key": workspace_key(user_id, persona_id),
                },
            )
        if not await self.agent_store.acquire_run(
            user_id, persona_id, settings.AGENT_LOCK_SECONDS
        ):
            raise CodexRuntimeError("This Twyn already has a task running")

        try:
            return await asyncio.wait_for(
                self._run_locked(user_id, persona_id, task, connection),
                timeout=settings.AGENT_TASK_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            await self.agent_store.update_status(
                user_id, persona_id, status="timed_out", last_error="Task timed out"
            )
            raise CodexRuntimeError("Codex task timed out; its workspace and session were retained") from exc
        except Exception as exc:
            await self.agent_store.update_status(
                user_id, persona_id, status="failed", last_error=self._safe_error(exc)
            )
            if isinstance(exc, CodexRuntimeError):
                raise
            logger.exception("Codex task failed for Twyn scope %s", workspace_key(user_id, persona_id))
            raise CodexRuntimeError(self._safe_error(exc)) from exc
        finally:
            await self.agent_store.release_run(user_id, persona_id)

    async def _run_locked(self, user_id: str, persona_id: str, task: str,
                          connection: dict) -> dict:
        workspace, branch = await asyncio.to_thread(
            self.workspace_manager.prepare,
            user_id=user_id,
            persona_id=persona_id,
            repo_url=connection["repo_url"],
            default_branch=connection["default_branch"],
            github_token=connection["github_token"],
        )
        state = await self.agent_store.get(user_id, persona_id) or {}
        if state.get("repo_url") and state["repo_url"] != connection["repo_url"]:
            raise CodexRuntimeError(
                "The configured repository changed. Remove the existing Codex session before switching repos."
            )

        session_id = state.get("session_id")
        environment_id = state.get("environment_id")
        remote_url = state.get("remote_url")
        is_new_session = not session_id
        if is_new_session:
            session = await self.openai.beta.agents.sessions.create(
                agent={"model": settings.CODEX_MODEL, "instructions": INSTRUCTIONS},
                environment={"type": "self_hosted", "workspace_directory": "/workspace"},
                metadata={
                    "twynity_scope": workspace_key(user_id, persona_id),
                    "project": connection["project_name"][:100],
                },
            )
            session_data = session.model_dump()
            environment = session_data.get("environment") or {}
            session_id = session_data.get("id")
            environment_id = environment.get("id")
            remote_url = environment.get("remote_url")
            if not all((session_id, environment_id, remote_url)):
                raise CodexRuntimeError("OpenAI did not return the self-hosted executor details")
            await self.agent_store.save(
                user_id,
                persona_id,
                {
                    "session_id": session_id,
                    "environment_id": environment_id,
                    "remote_url": remote_url,
                    "branch": branch,
                    "status": "starting",
                    "repo_url": connection["repo_url"],
                    "project_name": connection["project_name"],
                    "workspace_key": workspace_key(user_id, persona_id),
                },
            )

        # Subscribe before starting a new executor so the environment-connected
        # event cannot be missed. Existing running executors can accept a turn now.
        async with self.openai.beta.agents.sessions.events.stream(session_id) as events:
            container_id, executor_started = await asyncio.to_thread(
                self.executor_manager.ensure_running,
                user_id=user_id,
                persona_id=persona_id,
                workspace=workspace,
                environment_id=environment_id,
                remote_url=remote_url,
            )
            await self.agent_store.save(
                user_id,
                persona_id,
                {"container_id": container_id, "branch": branch, "status": "running"},
            )
            submitted = False
            if not is_new_session and not executor_started:
                await self._submit_message(session_id, task)
                submitted = True

            output_parts: list[str] = []
            async for event in events:
                event_data = event.model_dump()
                event_type = event_data.get("type", "")
                if event_type == "agent.session.environment.connected" and not submitted:
                    await self._submit_message(session_id, task)
                    submitted = True
                elif event_type in {"agent.session.environment.failed", "agent.session.failed"}:
                    raise CodexRuntimeError(f"Codex environment failed: {event_type}")
                elif event_type == "error":
                    error = event_data.get("error") or {}
                    raise CodexRuntimeError(str(error.get("message", "OpenAI session error")))

                if event_type in {
                    "agent.session.turn.output_text.delta",
                    "agent.session.turn.output_text.done",
                }:
                    text = event_data.get("delta") or event_data.get("text")
                    if text:
                        output_parts.append(text)

                turn = event_data.get("turn") or {}
                root_turn = turn.get("subagent_id") is None
                if event_type == "agent.session.turn.failed" and root_turn:
                    error = turn.get("error") or {}
                    raise CodexRuntimeError(str(error.get("message", "Codex turn failed")))
                if event_type == "agent.session.turn.cancelled" and root_turn:
                    raise CodexRuntimeError("Codex turn was cancelled")
                if event_type == "agent.session.turn.completed" and root_turn:
                    break
            else:
                raise CodexRuntimeError("OpenAI event stream closed before the task completed")

        head = await asyncio.to_thread(
            publish_branch,
            workspace=workspace,
            repo_url=connection["repo_url"],
            branch=branch,
            base_branch=connection["default_branch"],
            github_token=connection["github_token"],
            hooks_dir=self._hooks_dir,
        )
        output = "".join(output_parts).strip()
        result = {
            "project_name": connection["project_name"],
            "status": "completed",
            "branch": branch,
            "commit": head,
            "published": bool(head),
            "response": output or "Codex completed the task.",
        }
        await self.agent_store.save(
            user_id,
            persona_id,
            {
                "status": "completed",
                "last_branch": branch,
                "last_commit": head,
                "last_response": output[-12000:],
                "last_task_hash": hashlib.sha256(task.encode()).hexdigest(),
                "last_error": None,
            },
        )
        return result

    async def _submit_message(self, session_id: str, task: str) -> None:
        await self.openai.beta.agents.sessions.events.create(
            session_id,
            idempotency_key=str(uuid4()),
            events=[
                {
                    "type": "agent.session.input.message",
                    "input": [
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": task}],
                        }
                    ],
                }
            ],
        )

    async def task_status(self, *, user_id: str, persona_id: str) -> dict | None:
        state = await self.agent_store.get(user_id, persona_id)
        if not state:
            return None
        return {
            "status": state.get("status", "idle"),
            "project_name": state.get("project_name"),
            "branch": state.get("last_branch") or state.get("branch"),
            "last_commit": state.get("last_commit"),
            "last_response": state.get("last_response"),
            "last_error": state.get("last_error"),
        }

    @staticmethod
    def _safe_error(error: Exception) -> str:
        # Do not return command output or credential-bearing values to the caller.
        text = str(error)
        for secret in (settings.OPENAI_API_KEY, settings.OPENAI_EXECUTOR_API_KEY):
            if secret:
                text = text.replace(secret, "[redacted]")
        return text[:1000] or type(error).__name__
