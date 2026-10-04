# Codex Harness MCP V1: deployment handover

This runbook is for deploying the first Twynity Codex Harness MCP on the Linux
GPU/Docker host and connecting it to Twynity for a controlled end-to-end test.

## What V1 does

- Twynity sends a bearer JWT and `Persona-Id`; the MCP verifies the JWT and
  scopes configuration, session, workspace, and task state to that user/persona.
- The persona has one configured GitHub repository and one long-lived Codex
  session.
- The MCP checks out the repository into an opaque workspace directory. A
  Docker executor runs `codex exec-server` with only that workspace mounted.
- The MCP uses the saved GitHub token to publish agent-created commits to a
  generated `twynity/<opaque-id>` branch. The agent container never receives
  the GitHub token or the shared application OpenAI key.

V1 supports Codex only. It does not push to the repository's default branch.

## Host requirements

- Linux host with Docker Engine and the Docker Compose plugin.
- Outbound HTTPS access to Docker Hub, Debian package repositories, npm,
  GitHub, OpenAI, the Twynity account service, license service, and usage
  reporting endpoint.
- A DNS name and HTTPS reverse proxy for Twynity to reach the MCP. Only the MCP
  needs inbound access. The executor connects outbound to OpenAI.
- Disk space for Docker images and repository workspaces.

The MCP service needs access to `/var/run/docker.sock` to create executor
containers. Docker socket access is effectively host-level control; restrict
host and MCP access to the deployment operator.

## 1. Pull the deployment branch

```bash
git clone https://github.com/nanabrownsnr/codex-mcp.git
cd codex-mcp
git checkout main
git pull --ff-only origin main
```

## 2. Prepare Docker and the workspace volume

The MCP and executor processes use UID 1000. The workspace mount must be
writable by this UID and visible to the Docker daemon at the same absolute
path:

```bash
sudo mkdir -p /srv/twynity-workspaces
sudo chown 1000:1000 /srv/twynity-workspaces
export DOCKER_GID="$(stat -c '%g' /var/run/docker.sock)"
```

Keep `WORKSPACE_HOST_ROOT` and `WORKSPACE_ROOT` set to
`/srv/twynity-workspaces` in `.env`. Compose mounts that same path into the MCP
container and the MCP bind-mounts individual persona workspaces into executor
containers.

## 3. Obtain and configure secrets

Copy the template and edit it on the host. Do not commit or send the populated
file in chat:

```bash
cp .env.example .env
chmod 600 .env
```

Set these values in `.env`:

| Setting | What to provide |
| --- | --- |
| `ENCRYPTION_KEY` | Fresh Fernet key. Generate one with Python's standard library: `python3 -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`. Back it up securely alongside MongoDB. |
| `OPENAI_API_KEY` | Shared OpenAI Platform project API key for Agents API session creation and events. |
| `OPENAI_EXECUTOR_API_KEY` | Separate restricted environment-connection key from the same OpenAI project. Do not use the shared API key here. |
| `CODEX_MODEL` | Model enabled for the OpenAI project; V1 default is `gpt-6-astra`. |
| `ACCOUNT_SERVICE_URL` | Twynity account service base URL. |
| `ACCOUNT_SERVICE_JWKS_ENDPOINT` | Account-service JWKS path used to verify Twynity JWTs. |
| `LICENSE_KEY` | Valid license for service ID `codex-harness_mcp`. |
| `LICENSE_SERVER_BASE_URL` | Twynity license service base URL. |
| `LICENSE_SERVER_JWKS_ENDPOINT` | License-service JWKS path. |
| `LICENSE_SERVER_ACTIVATION_ENDPOINT` | License activation path. |
| `USAGE_REPORT_ENDPOINT` | Twynity usage reporting endpoint. |
| `PUBLIC_URL` | Public HTTPS origin for this MCP, for example `https://codex-mcp.example.com`. |
| `ALLOWED_ORIGINS` | Twynity web app origin(s), comma-separated. |
| `DOCKER_GID` | Docker socket group ID from the command above. |
| `WORKSPACE_ROOT`, `WORKSPACE_HOST_ROOT` | Same absolute Linux host path, normally `/srv/twynity-workspaces`. |

For Compose, `MONGODB_URI` is overridden inside the MCP container to
`mongodb://mongo:27017`; MongoDB data persists in the `mongo-data` volume.
Leave `DATABASE_NAME` as `twynity_mcp` unless there is a reason to change it.

The MCP JWT audience is `codex-harness_mcp` by default. Confirm Twynity issues a
token with that audience and a user identity claim named `id` or `sub`. Twynity
must send the selected persona as the `Persona-Id` header on MCP and MCP App
requests.

## 4. Build and start

Build the executor image first. This installs the current Codex CLI alpha,
which provides `codex exec-server` for the self-hosted Agents API flow:

```bash
docker build -f Dockerfile.executor -t twynity-codex-executor:local .
```

Then build and start the MCP service and MongoDB:

```bash
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 harness-mcp
```

Configure the reverse proxy to forward HTTPS requests to host port `8000` and
preserve the `Authorization` and `Persona-Id` headers. The MCP transport URL is
`https://<your-host>/mcp`.

## 5. Check service health

From the host, these routes should respond:

```bash
curl -fsS https://<your-host>/api/v1/health
curl -fsS https://<your-host>/api/v1/.well-known/mcp.json
```

The health route only confirms the web process is serving. Also check
`docker compose logs harness-mcp` for MongoDB startup, license activation, and
account-service connectivity. The license watcher requires a valid license;
repeated validation failure eventually terminates the process.

## 6. Connect Twynity and configure a test project

1. In Twynity, add an MCP connection to `https://<your-host>/mcp` using the
   normal Twynity JWT connection settings.
2. Ensure Twynity forwards the user's bearer JWT and selected `Persona-Id`.
3. Configure that Twyn's project connection with:
   - a display `project_name`;
   - a credential-free GitHub URL such as `https://github.com/owner/repo`;
   - a fine-grained GitHub token with repository Contents read/write access.
     The token is saved encrypted in MongoDB and must not be added to MCP tool
     arguments.
4. Use a disposable test repository for the first run. Each Twyn binds to one
   repository in V1; use a different Twyn to connect a different repository.
5. Call `run_task` with a small, reviewable change. The tool should report the
   generated work branch and commit. Confirm the branch exists in GitHub and
   that the default branch was not changed.
6. Call `get_task_status` and verify it reports state only for the selected
   Twyn.

The branch name is `twynity/<opaque-id>`, not the project name. The opaque ID is
derived from the verified user and persona and is stable for that pair.

## Troubleshooting

- **Container cannot access Docker:** check that `DOCKER_GID` matches
  `/var/run/docker.sock`, the MCP container has the socket mounted, and its
  user belongs to that group. Restart Compose after changing the GID.
- **Executor cannot start:** confirm the executor image exists with
  `docker image inspect twynity-codex-executor:local`, and inspect MCP logs.
- **OpenAI key or environment errors:** verify both keys are from the same
  project, the application key has Agents API permissions, and the executor
  key has environment-connection permission.
- **JWT rejected:** check account-service URL/JWKS, token audience
  `codex-harness_mcp`, token expiry, and the `id`/`sub` identity claim.
- **Persona missing:** confirm Twynity sends `Persona-Id` on both tool and App
  requests.
- **GitHub checkout/push fails:** verify the token grants repository access
  and Contents read/write permission. The setup check confirms repository read
  access; the first branch push confirms write access.
- **No branch appears:** Codex must make and commit a change. Check the tool
  result and MCP logs for the publisher error.
- **Task hangs or times out:** inspect logs and the executor container with
  `docker ps --filter label=twynity.managed=codex-executor`.

## Data and cleanup

MongoDB contains encrypted GitHub tokens and persona-scoped Codex session
records. The workspace root contains each Twyn's checkout. Back up MongoDB and
the Fernet key together. `docker compose down` stops services but keeps the
MongoDB volume; do not use `down -v` or delete workspace directories unless
you intend to erase test data. Executor containers and workspaces persist
between tasks to continue the Codex session.

This is a first test deployment, not a production hardening checklist. Before
broader exposure, agree on executor/workspace retention, resource limits,
monitoring, backup, and recovery procedures.
