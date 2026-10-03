# Twynity MCP template guide

This guide is for the developer adapting the template and the coding agent
helping them. Preserve the authentication/storage contract while replacing the
example service fields, tools, and UI with the target integration.

## Request identity and security model

1. The Twynity host sends an authenticated bearer JWT. FastMCP's
   `JWTVerifier` checks MCP transport requests against the account-service
   JWKS. Custom HTTP routes are not automatically protected, so
   `app/auth.py:get_identity` independently verifies their bearer token.
2. The active project/persona is the configured `Persona-Id` HTTP header.
   Header values are context, not user input: do not expose a persona argument
   on tools or accept one from a JSON body.
3. Identity is the verified JWT user ID (`id`, falling back to `sub`) plus the
   persona header. Every connection read/write must use both values exactly.
4. The MongoDB collection has a unique compound index on `user_id` and
   `persona_id`. Saving is an upsert for that pair, so saving again replaces
   that same project's connection without affecting another project.
5. Connector fields are Fernet-encrypted before persistence. GET/config status
   responses expose only safe metadata. Never log secrets or return them in
   chat/UI payloads.

Keep the Fernet key stable and secret. Changing it makes existing ciphertext
unreadable. Rotate keys with a deliberate migration, not by replacing the env
value casually.

## Important MCP Apps header limitation

The React App can call tools with `app.callServerTool()`, but the MCP Apps SDK
does not offer a general arbitrary-header option. The Twynity host/proxy must
forward the same authenticated bearer token and `Persona-Id` header on those
tool calls. The UI should not try to collect or inject the persona ID. Test
this with both a model-initiated call and an App-button call before release.

## Routes and payload contract

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /api/v1/.well-known/mcp.json` | Public | Manifest with `external_connections.project` |
| `GET /api/v1/schema` | Public | Describes the fields requested by configuration UI |
| `POST /api/v1/configuration` | JWT + Persona-Id | Validates and upserts current project connection |
| `GET /api/v1/configuration` | JWT + Persona-Id | Returns safe connection metadata in `{items, item_count, next_cursor}` |
| `GET /api/v1/external-connection/me` | JWT + Persona-Id | Returns `{connected: true/false}` |
| `GET /api/v1/health` | Public | Liveness check |

The default schema is an example (`name`, `base_url`, `api_key`, `api_secret`).
Change fields to match the upstream product and keep secrets encrypted. The
manifest connection name, schema name, and POST endpoint must remain in sync
with the Twynity registration contract.

## Adding an upstream tool

- Put one logical tool module per file under `app/tools/` and register it in
  `app/main.py`.
- Write a docstring that tells the model when to use the tool, what arguments
  mean, how to handle ambiguous resource types, and what the result contains.
- For tools needing the active account credentials, call
  `await app.tools.connection.get_current_connection()` from the tool handler.
  It resolves JWT + persona headers and returns only the exact matching
  connection. Do not read MongoDB by user ID alone.
- Give UI-backed tools a stable `ui://` URI, register a matching UI resource,
  return compact model-readable content plus typed `structured_content`, and
  link the tool to the UI with `AppConfig`.
- If the user requests a read-only visualization, avoid sending the entire
  record collection in `content`; return a concise count/summary and send
  display data in structured content.

## Changing the starter

1. Rename `mcp_name`, Python package metadata, UI app identity, resource URI,
   and manifest/configuration labels.
2. Replace `say_hello` with the integration's tool modules. Remove example UI
   assets only after replacing the registered tool/resource references.
3. Adapt config schema, validation, and UI to the upstream connection fields.
   Preserve encrypted persistence and exact pair scope.
4. Set `MONGODB_URI`, `DATABASE_NAME`, `ENCRYPTION_KEY`, `PUBLIC_URL`,
   `ALLOWED_ORIGINS`, and Twynity service settings for each environment.
5. Check CORS permits the Twynity origin and `Persona-Id` header. CORS is not
   authentication; routes still verify bearer JWTs.
6. Update tests for success, malformed/missing inputs, invalid JWT, missing
   persona, cross-persona isolation, encrypted storage, upstream errors, and
   UI result contracts.

## Verification before deploy

```bash
uv sync --locked
uv run pytest -q
uv run ruff check app tests
cd app/ui/say_hello && npm ci && npm run build
docker build -t your-mcp:local .
```

Also check the account service's actual JWT claim naming, JWKS URL, audience
policy, persona header spelling, Twynity manifest expectations, public URL,
and UI-call header forwarding in the target environment. Do not assume the
example environment values are production-ready.
