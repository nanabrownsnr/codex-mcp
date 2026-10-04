# Twynity Codex Harness MCP

A Twynity MCP server that assigns a long-lived OpenAI-managed Codex session and
isolated workspace to the authenticated Twyn. It follows the
[`twynity-mcp-project-template`](https://github.com/nanabrownsnr/twynity-mcp-project-template)
structure for JWT authentication, persona-scoped configuration, encrypted
connections, manifest/schema routes, usage reporting, and licensing.

## Version one flow

```text
Twynity sends its JWT and Persona-Id
        -> MCP resolves that user's configured repository
        -> GitHub token checks out the repo into an opaque per-Twyn workspace
        -> OpenAI Agents API creates or resumes the Twyn's Codex session
        -> an isolated Docker executor mounts only that workspace
        -> publisher pushes commits to the Twyn's dedicated work branch
```

OpenAI's managed harness owns the model/API key. The Docker executor receives a
restricted environment key from the same OpenAI project and does not receive
the application API key. The GitHub token is used by the MCP service for
checkout and branch publishing; it is not passed into the Codex container.

The MVP stores one project/repository per `(verified user_id, Persona-Id)`.
Project names are display labels. Workspace directory names are hashes of the
verified identity pair, never user-provided strings.

## MCP tools

- `run_task(task)`: start or continue the active Twyn's Codex conversation,
  commit completed changes locally, and publish the work branch.
- `get_task_status()`: return only the current Twyn's latest status and branch.

## Configure

1. Install Docker Engine on the Linux host that will run the service. The
   executor makes outbound connections to OpenAI; no inbound port is opened for
   it. Create the workspace root and give it to UID 1000 (the service and
   executor account):

   ```bash
   sudo mkdir -p /srv/twynity-workspaces
   sudo chown 1000:1000 /srv/twynity-workspaces
   export DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
   ```
2. Create an OpenAI Platform project API key with `api.agents.read`,
   `api.agents.write`, and `api.responses.write`. Create a separate executor
   environment key in that same project with only environment-connection
   permission. Keep both in the server's secret configuration. The API key is
   never mounted into executor containers.
3. Generate a Fernet encryption key:

   ```bash
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Copy `.env.example` to `.env` and set the account, license, usage, MongoDB,
   OpenAI, Docker, and workspace settings. `WORKSPACE_ROOT` must be an absolute
   path visible at the same location to both the MCP process and Docker daemon.
5. Build the isolated executor image:

   ```bash
   docker build -f Dockerfile.executor -t twynity-codex-executor:local .
   ```

6. Build and start the MCP service with Docker Compose:

   ```bash
   docker compose up --build -d
   ```

   Compose mounts the Docker socket into the MCP service so it can create one
   executor container per Twyn. Restrict access to this MCP service because
   Docker socket access grants substantial control over the host.

7. In Twynity's external-connection setup, provide a project name, the
   `https://github.com/owner/repo` URL, and a fine-grained GitHub token with
   Contents read/write access for that repository. The default branch is read
   from GitHub unless explicitly supplied. Credentials are encrypted in
   MongoDB; configuration GET responses expose project metadata only.
8. Add this MCP to Twynity with its standard JWT connection. Twynity must
   forward the bearer JWT and `Persona-Id` header for both model and MCP App
   calls, as required by the project template.

The model is configured with `CODEX_MODEL` (default `gpt-6-astra`). OpenAI model
availability depends on the shared Platform project. ChatGPT subscriptions and
OpenAI API billing are separate.

## Storage and task behavior

- `project_connections` stores encrypted GitHub tokens with project metadata,
  strictly keyed by the verified user and persona.
- `codex_sessions` stores the OpenAI session and executor IDs for that same
  pair. The session and workspace are reused on subsequent task calls.
- Workspaces live under `WORKSPACE_ROOT/<opaque-hash>` and are mounted into
  that Twyn's executor only.
- Codex commits locally. The publisher pushes `HEAD` to a generated branch
  named `twynity/<opaque-hash>`; it never pushes directly to the default branch.
- One task per Twyn runs at a time. Use `get_task_status` to inspect the last
  run. Branch publication requires the agent to create a local commit.

## Operations

- Back up MongoDB and the Fernet key together. Losing the key makes saved GitHub
  tokens unreadable.
- Do not log credentials, pass them in tool arguments, or place them in agent
  instructions. The OpenAI application key and GitHub tokens belong only in
  trusted server-side storage/configuration.
- Executor containers persist across requests to preserve Codex session state.
  Workspace and container cleanup/retention policy should be configured before
  exposing the service broadly.
- The initial executor image uses the Codex CLI alpha package because the
  self-hosted Agents API currently uses `codex exec-server`; pin a tested
  release before production rollout.

## Template adaptation

- `app/auth.py` verifies Twynity identity.
- `app/twynity.py` declares and manages the external project connection.
- `app/connection_store.py` encrypts GitHub credentials.
- `app/agent_store.py` stores session state under the same strict identity pair.
- `app/codex_runtime.py`, `app/executor.py`, `app/workspaces.py`, and
  `app/publisher.py` implement task execution and branch publishing.
- `app/tools/run_task.py` registers the MCP tools.
