# Builds the MCP App and production Python runtime. Update the UI COPY paths
# when renaming the example; generated dist/ files stay out of source control.
FROM node:22-alpine AS ui-builder

WORKDIR /ui

COPY app/ui/task_result/package.json app/ui/task_result/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY app/ui/task_result/index.html app/ui/task_result/vite.config.js ./
COPY app/ui/task_result/src/ ./src/
RUN npm run build


FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY app/ ./app/
COPY --from=ui-builder /ui/dist/ ./app/ui/task_result/dist/

ARG DOCKER_GID=999
RUN if ! getent group ${DOCKER_GID} >/dev/null; then groupadd -g ${DOCKER_GID} docker; fi \
    && DOCKER_GROUP=$(getent group ${DOCKER_GID} | cut -d: -f1) \
    && useradd -m appuser && usermod -aG ${DOCKER_GROUP} appuser \
    && mkdir -p /srv/twynity-workspaces && chown -R appuser:appuser /app /srv/twynity-workspaces
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
