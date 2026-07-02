# syntax=docker/dockerfile:1

# Multi-stage image for apiome-mcp (FastMCP streamable HTTP).
#
# Build from the repository root so the path dependency on apiome-rest is available:
#   docker build -f apiome-mcp/Dockerfile .

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /build

# READMEs are copied alongside each pyproject because both packages declare
# `readme = "README.md"`; hatchling reads it while building the (non-editable) wheels.
COPY apiome-rest/pyproject.toml /build/apiome-rest/pyproject.toml
COPY apiome-rest/README.md /build/apiome-rest/README.md
COPY apiome-rest/src /build/apiome-rest/src
COPY apiome-mcp/pyproject.toml /build/apiome-mcp/pyproject.toml
COPY apiome-mcp/README.md /build/apiome-mcp/README.md
COPY apiome-mcp/uv.lock /build/apiome-mcp/uv.lock
COPY apiome-mcp/src /build/apiome-mcp/src

WORKDIR /build/apiome-mcp

# Build the virtualenv at the SAME absolute path it will occupy in the runtime stage
# (/app/.venv). uv bakes that path into the generated console-script shebangs
# (e.g. .venv/bin/apiome-mcp -> #!/app/.venv/bin/python); building under the default
# /build/apiome-mcp/.venv and copying it to /app/.venv leaves a dangling shebang, so
# `apiome-mcp` fails at runtime with "exec ... no such file or directory".
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --compile-bytecode --no-editable

FROM python:3.12-slim-bookworm AS runtime

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mcp \
    && mkdir -p /app \
    && chown mcp:mcp /app

WORKDIR /app

COPY --from=builder --chown=mcp:mcp /app/.venv /app/.venv

USER mcp

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv

ENV APIOME_MCP_HTTP_HOST=0.0.0.0 \
    APIOME_MCP_HTTP_PORT=8765

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('APIOME_MCP_HTTP_PORT','8765')}/health\", timeout=4)"

CMD ["apiome-mcp", "serve", "--transport", "http"]
