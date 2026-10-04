"""Push a committed Twyn branch without giving GitHub credentials to Codex."""

import os
import subprocess
import tempfile
from pathlib import Path

from app.workspaces import WorkspaceError, validate_branch_name, validate_github_repo_url


class PublishError(RuntimeError):
    """A branch could not be published."""


def publish_branch(
    *, workspace: Path, repo_url: str, branch: str, base_branch: str,
    github_token: str, hooks_dir: Path
) -> str | None:
    """Push the current HEAD to the fixed branch; never use a token-bearing URL."""
    safe_url = validate_github_repo_url(repo_url)
    safe_branch = validate_branch_name(branch)
    safe_base = validate_branch_name(base_branch)
    head = _git(["rev-parse", "HEAD"], workspace).strip()
    commit_count = _git(
        ["rev-list", "--count", f"origin/{safe_base}..HEAD"], workspace
    ).strip()
    if commit_count == "0":
        return None
    upstream = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{safe_branch}"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if upstream.returncode == 0 and upstream.stdout.strip() == head:
        return None

    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GITHUB_TOKEN": github_token})
    askpass_path = None
    if os.name == "nt":
        handle, askpass_path = tempfile.mkstemp(suffix=".cmd", prefix="twynity-push-askpass-")
        script = (
            '@echo off\r\necho %* | findstr /I "Username" >nul\r\n'
            'if not errorlevel 1 (echo x-access-token) else (echo %GITHUB_TOKEN%)\r\n'
        )
    else:
        handle, askpass_path = tempfile.mkstemp(suffix=".sh", prefix="twynity-push-askpass-")
        script = (
            '#!/bin/sh\ncase "$1" in *Username*) printf "x-access-token\\n" ;; '
            '*) printf "%s\\n" "$GITHUB_TOKEN" ;; esac\n'
        )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as askpass:
            askpass.write(script)
        if os.name != "nt":
            os.chmod(askpass_path, 0o700)
        env["GIT_ASKPASS"] = askpass_path
        result = subprocess.run(
            [
                "git", "-c", f"core.hooksPath={hooks_dir}", "-c", "credential.helper=",
                "-c", "credential.interactive=never", "-c", "http.extraheader=",
                "push", "--porcelain", safe_url, f"HEAD:refs/heads/{safe_branch}",
            ],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if result.returncode:
            message = result.stderr.replace(github_token, "[redacted]").strip()
            raise PublishError(message or "GitHub rejected the branch push")
        return head
    except subprocess.TimeoutExpired as exc:
        raise PublishError("Publishing the branch timed out") from exc
    except WorkspaceError as exc:
        raise PublishError(str(exc)) from exc
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode:
        raise PublishError(result.stderr.strip() or "Could not inspect the workspace commit")
    return result.stdout
