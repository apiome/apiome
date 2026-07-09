# syntax=docker/dockerfile:1

# Multi-stage image for apiome-mock (FastAPI).
#
# Build from the repository root:
#   docker build -f apiome-mock/Dockerfile .

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /build

COPY apiome-rest/pyproject.toml /build/apiome-rest/pyproject.toml
COPY apiome-rest/README.md /build/apiome-rest/README.md
COPY apiome-rest/src /build/apiome-rest/src
COPY apiome-mcp/pyproject.toml /build/apiome-mcp/pyproject.toml
COPY apiome-mcp/README.md /build/apiome-mcp/README.md
COPY apiome-mcp/src /build/apiome-mcp/src
COPY apiome-mock/pyproject.toml /build/apiome-mock/pyproject.toml
COPY apiome-mock/README.md /build/apiome-mock/README.md
COPY apiome-mock/uv.lock /build/apiome-mock/uv.lock
COPY apiome-mock/src /build/apiome-mock/src

WORKDIR /build/apiome-mock

ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --compile-bytecode --no-editable

FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mock \
    && mkdir -p /app \
    && chown mock:mock /app

WORKDIR /app

COPY --from=builder --chown=mock:mock /app/.venv /app/.venv

USER mock

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv

ENV APIOME_MOCK_HTTP_HOST=0.0.0.0 \
    APIOME_MOCK_HTTP_PORT=8775

EXPOSE 8775

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('APIOME_MOCK_HTTP_PORT','8775')}/health\", timeout=4)"

CMD ["apiome-mock", "serve"]
