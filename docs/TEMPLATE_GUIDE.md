# Runtime and integration notes

This project keeps the Twynity project-template identity contract and replaces
its sample integration with an OpenAI-managed Codex harness.

## Request identity

MCP transport requests are protected by FastMCP's JWT verifier. Tool handlers
also resolve the verified user and `Persona-Id` header from the request
context. Custom HTTP routes explicitly verify the bearer JWT because FastMCP's
verifier does not secure Starlette custom routes.

MongoDB project and session records are keyed by the exact
`(user_id, persona_id)` pair. The persona selects one configured repository in
version one. The filesystem path and container name use a stable hash of that
pair; a project display name is never used as a path.

## Credential boundaries

- `project_connections.values.github_token` is Fernet-encrypted at rest.
- GitHub credentials are decrypted only during checkout and publishing. Git
  URLs remain credential-free, and askpass files are deleted after each Git
  operation.
- The shared `OPENAI_API_KEY` is used by the trusted MCP process for session
  management and inference. It is never placed in the executor.
- `OPENAI_EXECUTOR_API_KEY` is mounted into one executor container and should
  be restricted to executor/environment connection permission in the same
  OpenAI project as `OPENAI_API_KEY`.
- Executor containers receive only their persona workspace, no Docker socket,
  and no GitHub or application API credentials.

## Workspace and session lifecycle

`run_task` clones the assigned repo once, creates a stable
`twynity/<opaque-id>` branch, starts or resumes the OpenAI session, and waits
for the root turn to complete. A named executor container stays up so its
workspace and session can continue on later calls. A Mongo lock serializes
tasks for one persona. The publisher pushes the local HEAD to the generated
branch only after Codex finishes successfully.

The container runs `codex exec-server` from `@openai/codex@alpha`. It connects
outbound to the OpenAI Agents API. Build the `Dockerfile.executor` image before
starting task work. The MCP service needs Docker socket access and a workspace
root path shared with the Docker daemon.

## Twynity configuration routes

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /api/v1/.well-known/mcp.json` | Public | Manifest declaring the project connection |
| `GET /api/v1/schema` | Public | Setup fields for name, repo, branch, and GitHub token |
| `POST /api/v1/configuration` | JWT + Persona-Id | Validate and encrypt the current Twyn's project connection |
| `GET /api/v1/configuration` | JWT + Persona-Id | Return safe repository metadata only |
| `GET /api/v1/external-connection/me` | JWT + Persona-Id | Return whether the Twyn is configured |
| `GET /api/v1/health` | Public | Liveness response |

The setup route checks that the token can read the selected repository. The
token must also have contents write permission for branch publishing. A Twyn
cannot be rebound to a different repository in version one; create a separate
Twyn for another repo.

## MCP App headers

MCP Apps calls use `app.callServerTool()` and cannot attach arbitrary headers.
Twynity's host must forward the authenticated bearer token and `Persona-Id` to
the MCP service for App-originated calls as well as model-originated calls.

## Configuration and operations

- Set the account-service JWKS URL, audience/service ID, and Persona-Id header
  to match the deployed Twynity environment.
- Keep OpenAI keys, the Fernet key, MongoDB credentials, and license/usage
  settings in deployment secrets. Never commit a populated `.env`.
- Configure Docker socket access deliberately; it grants the MCP process
  substantial control over the host's containers.
- Keep the workspaces volume durable. Removing it discards checkouts; deleting
  an executor container requires starting a new environment/session lifecycle.
- The shared OpenAI Platform project pays for all users' model calls. Record
  tool usage by verified Twynity user/persona in the app if per-user accounting
  is needed.
