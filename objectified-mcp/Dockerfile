# syntax=docker/dockerfile:1

# Multi-stage image for objectified-mcp (FastMCP streamable HTTP).
#
# Build from the repository root so the path dependency on objectified-rest is available:
#   docker build -f objectified-mcp/Dockerfile .

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /build

COPY objectified-rest /build/objectified-rest
COPY objectified-mcp /build/objectified-mcp

WORKDIR /build/objectified-mcp
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --compile-bytecode --no-editable

FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mcp \
    && mkdir -p /app \
    && chown mcp:mcp /app

WORKDIR /app

COPY --from=builder --chown=mcp:mcp /build/objectified-mcp/.venv /app/.venv

USER mcp

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv

ENV OBJECTIFIED_MCP_HTTP_HOST=0.0.0.0 \
    OBJECTIFIED_MCP_HTTP_PORT=8765

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('OBJECTIFIED_MCP_HTTP_PORT','8765')}/health\", timeout=4)"

CMD ["objectified-mcp", "serve", "--transport", "http", "--host", "0.0.0.0"]
