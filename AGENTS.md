# Instructions for agents working in this repository

This service is a Twynity MCP that runs the OpenAI-managed Codex harness with
isolated self-hosted executor containers. Preserve the Twynity identity and
credential boundaries in every change.

## Identity and credential rules

- MCP tool calls require a verified Twynity JWT and the `Persona-Id` header.
- Resolve identity only from verified JWT claims (`id`, then `sub`) and the
  trusted request header. Never accept user/persona IDs as tool arguments.
- Every project/session read and write uses the exact `(user_id, persona_id)`
  pair. Never fall back to a user-only query.
- GitHub tokens are encrypted in MongoDB. They may be decrypted only by
  checkout and publishing code. Never pass them to OpenAI, the executor, tool
  output, or logs.
- `OPENAI_API_KEY` stays in the MCP service. The executor receives only the
  restricted `OPENAI_EXECUTOR_API_KEY`, from the same OpenAI project.
- Treat project labels as display data. Use an opaque hash for paths/container
  names and never interpolate labels into filesystem paths or shell commands.
- Keep repository URLs canonical HTTPS GitHub URLs without embedded credentials.
- MCP Apps requests must receive the forwarded bearer token and `Persona-Id`;
  do not ask the UI to collect identity headers.

## Runtime boundaries

- `app/tools/` contains user-facing MCP tools; register them in `app/main.py`.
- `app/codex_runtime.py` coordinates OpenAI sessions and publishing.
- `app/executor.py` starts isolated containers. Do not mount Docker access,
  server secrets, or other users' workspace paths inside an executor.
- `app/workspaces.py` owns repository checkout and workspace paths.
- `app/publisher.py` pushes only the generated work branch using an ephemeral
  askpass helper. Keep the remote URL credential-free and disable repo hooks
  during the push.
- Preserve `app/twynity.py` manifest, schema, configuration, status, and health
  routes, and keep safe configuration responses free of secret values.

## Before changing the external contract

- Update `README.md`, `/api/v1/schema`, the Twynity connection routes, and the
  tool docstrings together.
- Keep session state and credentials scoped to the same authenticated persona.
- Document required OpenAI permission scopes, executor image requirements,
  Docker socket access, and workspace persistence.
- Do not commit `.env`, tokens, generated UI bundles, logs, or workspace data.
