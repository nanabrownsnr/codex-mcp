"""Prepare per-persona Git workspaces without exposing GitHub tokens to Codex."""

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse


class WorkspaceError(RuntimeError):
    """A repository could not be prepared safely."""


def workspace_key(user_id: str, persona_id: str) -> str:
    """Return a stable opaque path component; never use caller labels as paths."""
    return hashlib.sha256(f"{user_id}\0{persona_id}".encode()).hexdigest()[:32]


def validate_github_repo_url(value: str) -> str:
    """Accept credential-free HTTPS GitHub repository URLs only."""
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Repository URL must be a credential-free https://github.com/owner/repo URL")
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        raise ValueError("Repository URL must identify one GitHub repository")
    return f"https://github.com/{parts[0]}/{parts[1]}.git"


def validate_branch_name(value: str) -> str:
    branch = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", branch) or ".." in branch:
        raise ValueError("Default branch must be a valid simple Git branch name")
    return branch


class WorkspaceManager:
    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, user_id: str, persona_id: str) -> Path:
        return self.root / workspace_key(user_id, persona_id)

    def prepare(
        self,
        *,
        user_id: str,
        persona_id: str,
        repo_url: str,
        default_branch: str,
        github_token: str,
    ) -> tuple[Path, str]:
        """Clone/update a checkout and return its stable Twynity branch."""
        repo_url = validate_github_repo_url(repo_url)
        default_branch = validate_branch_name(default_branch)
        key = workspace_key(user_id, persona_id)
        path = self.path_for(user_id, persona_id)
        branch = f"twynity/{key}"

        if not (path / ".git").is_dir():
            if path.exists() and any(path.iterdir()):
                raise WorkspaceError("Workspace path exists but is not a Git checkout")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._git(
                ["clone", "--origin", "origin", repo_url, str(path)],
                cwd=path.parent,
                token=github_token,
            )

        configured_url = self._git(["remote", "get-url", "origin"], cwd=path).strip()
        if validate_github_repo_url(configured_url) != repo_url:
            raise WorkspaceError("Saved workspace remote does not match this Twyn's configured repository")

        self._git(["fetch", "origin", default_branch], cwd=path, token=github_token)
        remote_branch = self._git(
            ["ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
            cwd=path,
            token=github_token,
        )
        remote_branch_exists = bool(remote_branch.strip())
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
            cwd=path,
            capture_output=True,
            check=False,
        ).returncode == 0
        if remote_branch_exists:
            self._git(["fetch", "origin", branch], cwd=path, token=github_token)
        if not branch_exists:
            start_point = f"origin/{branch}" if remote_branch_exists else f"origin/{default_branch}"
            self._git(["switch", "--create", branch, start_point], cwd=path)
        else:
            self._git(["switch", branch], cwd=path)

        self._git(["config", "user.name", "Twynity Codex"], cwd=path)
        self._git(["config", "user.email", "codex@twynity.ai"], cwd=path)
        return path, branch

    @staticmethod
    def _git(args: list[str], *, cwd: Path, token: str | None = None) -> str:
        env = os.environ.copy()
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
        askpass_path = None
        if token:
            env["GITHUB_TOKEN"] = token
            if os.name == "nt":
                handle, askpass_path = tempfile.mkstemp(suffix=".cmd", prefix="twynity-askpass-")
                script = (
                    '@echo off\r\necho %* | findstr /I "Username" >nul\r\n'
                    'if not errorlevel 1 (echo x-access-token) else (echo %GITHUB_TOKEN%)\r\n'
                )
            else:
                handle, askpass_path = tempfile.mkstemp(suffix=".sh", prefix="twynity-askpass-")
                script = (
                    '#!/bin/sh\ncase "$1" in *Username*) printf "x-access-token\\n" ;; '
                    '*) printf "%s\\n" "$GITHUB_TOKEN" ;; esac\n'
                )
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as askpass:
                askpass.write(script)
            if os.name != "nt":
                os.chmod(askpass_path, 0o700)
            env["GIT_ASKPASS"] = askpass_path
            env["GIT_USERNAME"] = "x-access-token"
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            if result.returncode:
                # Git may echo a URL or remote error; never include token-bearing data.
                detail = result.stderr.replace(token, "[redacted]") if token else result.stderr
                raise WorkspaceError(detail.strip() or "Git operation failed")
            return result.stdout
        except subprocess.TimeoutExpired as exc:
            raise WorkspaceError("Git operation timed out") from exc
        finally:
            if askpass_path:
                Path(askpass_path).unlink(missing_ok=True)
