"""Manage an isolated Codex executor container for a Twyn session."""

from pathlib import Path

import docker
from docker.errors import APIError, DockerException, NotFound

from app.config import settings
from app.workspaces import workspace_key


class ExecutorError(RuntimeError):
    """The local Codex executor could not be started."""


class ExecutorManager:
    def __init__(self):
        self.client = docker.from_env(timeout=30)

    def ensure_running(
        self, *, user_id: str, persona_id: str, workspace: Path,
        environment_id: str, remote_url: str,
    ) -> tuple[str, bool]:
        if not settings.OPENAI_EXECUTOR_API_KEY:
            raise ExecutorError("OPENAI_EXECUTOR_API_KEY is not configured")

        key = workspace_key(user_id, persona_id)
        name = f"twynity-codex-{key}"
        labels = {"twynity.user_scope": key, "twynity.managed": "codex-executor"}
        try:
            try:
                container = self.client.containers.get(name)
                if container.labels.get("twynity.user_scope") != key:
                    raise ExecutorError("Existing executor container has an unexpected owner")
                was_stopped = container.status != "running"
                if was_stopped:
                    container.start()
                return container.id, was_stopped
            except NotFound:
                container = self.client.containers.run(
                    image=settings.EXECUTOR_IMAGE,
                    command=[
                        "codex", "exec-server", "--remote", remote_url,
                        "--environment-id", environment_id,
                    ],
                    name=name,
                    detach=True,
                    environment={"CODEX_API_KEY": settings.OPENAI_EXECUTOR_API_KEY},
                    working_dir="/workspace",
                    volumes={str(workspace.resolve()): {"bind": "/workspace", "mode": "rw"}},
                    labels=labels,
                    network_mode=settings.EXECUTOR_NETWORK,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    pids_limit=512,
                    mem_limit=settings.EXECUTOR_MEMORY_LIMIT,
                    restart_policy={"Name": "unless-stopped"},
                )
                return container.id, True
        except (DockerException, APIError) as exc:
            raise ExecutorError(
                "Could not start the Codex executor. Check Docker access and that "
                "the configured executor image is available."
            ) from exc

    def close(self) -> None:
        self.client.close()
