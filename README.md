# Twynity MCP Project Template

A reusable Python/FastMCP starter for MCP servers deployed in Twynity. It
combines verified Twynity JWT authentication, project/persona-scoped external
connections stored encrypted in MongoDB, MCP Apps UI scaffolding, and clear
extension instructions.

## What is included

- FastMCP server with account-service JWKS JWT verification.
- Project scope from the `Persona-Id` HTTP header. Connections are keyed by the
  exact `(user_id, persona_id)` pair; there is no user-only fallback.
- MongoDB startup/index setup and Fernet encryption for stored connector
  credentials.
- Twynity manifest, configuration schema, authenticated configuration GET/POST,
  connection status, and health routes.
- Example `say_hello` MCP App, usage reporting, and license watcher.
- Docker build and automated tests.

## Start here

1. Set `mcp_name` in `app/config.py`, rename the Python project in
   `pyproject.toml`, and update tool/UI names and URIs.
2. Copy `.env.example` to `.env`; fill in account service, license, usage,
   MongoDB, public URL, and allowed-origin settings. Generate a Fernet key:

   ```bash
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Back up `ENCRYPTION_KEY` securely. Losing/changing it prevents decrypting
   existing connection secrets. Do not commit `.env`.
3. Install dependencies, build the App bundle, and then run the checks. The
   resource test intentionally verifies the compiled artifact, so the frontend
   build must happen before pytest:

   ```bash
   uv sync --locked
   cd app/ui/say_hello
   npm ci
   npm run build
   cd ../../..
   uv run pytest -q
   uv run ruff check app tests
   ```
4. Run the server:

   ```bash
   uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

See [`docs/TEMPLATE_GUIDE.md`](docs/TEMPLATE_GUIDE.md) for the full setup,
auth contract, routes, tool/UI workflow, and customization checklist. See
[`AGENTS.md`](AGENTS.md) for repository instructions for coding agents.

## Twynity identity contract

Every authenticated request must carry a Twynity bearer JWT and the
`Persona-Id` header. The server verifies the JWT using the configured account
service JWKS and reads the user ID from verified `id` (or `sub`) claims. It
never accepts a persona ID as a tool argument. MongoDB stores one upserted
connection per user/persona pair.

The MCP Apps SDK's `app.callServerTool()` does not let UI code attach arbitrary
HTTP headers. Twynity's host must therefore forward the authenticated bearer
token and `Persona-Id` when proxying UI-originated MCP tool calls as well as
model-originated calls. If the host does not forward the header, requests fail
closed with a clear missing-header error; the UI must not ask the user to type
or choose a persona ID.

## Configuration routes

- `GET /api/v1/.well-known/mcp.json` — public service manifest; declares the
  project external connection.
- `GET /api/v1/schema` — public schema for the example upstream fields.
- `POST /api/v1/configuration` — authenticated upsert for the active
  `(user_id, persona_id)` connection; secrets are encrypted.
- `GET /api/v1/configuration` — authenticated list-style response with safe
  metadata only; never returns API keys/secrets.
- `GET /api/v1/external-connection/me` — authenticated `{"connected": bool}`.
- `GET /api/v1/health` — public liveness response.

The sample fields (`name`, `base_url`, `api_key`, `api_secret`) are generic
placeholders. Adapt the schema, validation, and UI to the upstream integration;
retain the identity scoping and secret-handling guarantees.
