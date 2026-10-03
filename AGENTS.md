# Instructions for agents working from this template

This is a reusable Twynity MCP starter. Replace the sample greeting feature
with the target integration while preserving the shared auth, connection,
secrets, and test contracts.

## Identity and credentials

- Verify bearer JWTs with the configured account-service JWKS. Custom HTTP
  routes must call the explicit verifier in `app/auth.py`; FastMCP's verifier
  alone does not protect custom routes.
- Resolve user identity from verified token claims (`id`, falling back to
  `sub`) and active project/persona from the configured `Persona-Id` request
  header. Never accept a persona ID only as an untrusted tool argument/body.
- Every MongoDB read/write must use the exact `(user_id, persona_id)` pair.
  Never fall back to user-only lookup. The compound unique index and upsert
  pattern are deliberate.
- Encrypt connector secrets before storage. Never return/log secrets or place
  them in tool content, structured UI data, or configuration GET responses.
- Keep persona identity separate from connection display name and upstream URL.
- MCP App `app.callServerTool()` cannot attach arbitrary headers. Document and
  test that the Twynity host forwards `Persona-Id` (and bearer auth) for App
  calls; do not ask the UI to collect the persona ID.

## Extending the starter

- Put one logical tool module per file under `app/tools/`, register it in
  `app/main.py`, and describe when/how an LLM should call it.
- For credentials in a tool, use `await app.tools.connection.get_current_connection()`
  so the call resolves the trusted user/persona context.
- For UI-enabled tools, add a matching `app/ui/<view>/` resource and keep the
  `structured_content` contract in sync with backend tests and frontend code.
- Adapt `/api/v1/schema` and configuration validation for the upstream service
  while retaining encrypted storage and safe metadata-only GET responses.
- Add tests for successes, invalid inputs, missing/invalid auth, missing
  persona, cross-persona isolation, encryption, and upstream failures.
- Preserve Twynity manifest, health, license, usage-reporting, and CORS behavior
  unless the target deployment contract explicitly differs.

## Before committing

- Update `README.md`, this guide, and `.env.example` for the integration.
- Run `uv run pytest -q` and `uv run ruff check app tests`.
- Build each UI and Docker image; verify deployment-specific settings.
- Check `git diff --check` and ensure `.env`, logs, generated bundles, and
  credentials are not committed.
