# Dockerfile for Objectified REST (FastAPI)
# Supports: linux/amd64, linux/arm64
#
# Build from the repository ROOT so the objectified-ui workspace is in the build context
# (the REST spec-import worker is a TypeScript script in objectified-ui, run via tsx):
#   docker build -f objectified-rest/Dockerfile .

# ── Stage 1: install the objectified-ui workspace deps (provides tsx + the worker's libs) ──
FROM node:20-bookworm-slim AS uideps
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /repo
RUN corepack enable

# Root workspace metadata + every workspace manifest: yarn needs the whole graph to resolve,
# even though we only install (focus) the objectified-ui workspace below.
COPY package.json yarn.lock .yarnrc.yml ./
COPY objectified-cli/package.json ./objectified-cli/package.json
COPY objectified-db/package.json ./objectified-db/package.json
COPY objectified-mcp/package.json ./objectified-mcp/package.json
COPY objectified-ui/package.json ./objectified-ui/package.json
COPY objectified-browse/package.json ./objectified-browse/package.json
COPY objectified-web/package.json ./objectified-web/package.json
COPY objectified-rest/package.json ./objectified-rest/package.json

# Install only objectified-ui's dependency tree (includes the tsx dev dependency).
RUN --mount=type=cache,target=/root/.yarn/berry/cache \
    yarn workspaces focus objectified-ui

# The worker script and the lib modules it imports (node_modules above is preserved;
# .dockerignore keeps any local node_modules/.next out of the build context).
COPY objectified-ui/ ./objectified-ui/

# ── Stage 1b: polyglot toolchain binaries (MFI-5.2, #3751) ──────────────────────────────
# Bundle the pinned external parser/linter/diff CLIs the multi-format import roadmap shells
# out to via app.toolchain_runner. Everything lands under /opt/objectified-tools so the
# runtime can copy ONE tree and put its bin/ on PATH. Versions are build args whose defaults
# MUST stay in sync with BUNDLED_TOOLS in src/app/toolchain_packaging.py (the single source
# of truth) — see objectified-rest/docs/toolchain_packaging.md. The tools are *optional* at
# runtime: if any are absent the service degrades that format to "unavailable" rather than
# failing, but pinning them here is what makes the image reproducible.
FROM debian:bookworm-slim AS tools

# Pinned versions (mirror src/app/toolchain_packaging.py:BUNDLED_TOOLS).
ARG BUF_VERSION=1.50.0
ARG TSP_VERSION=0.65.0
ARG SMITHY_VERSION=1.53.0
ARG DRAFTER_VERSION=4.0.0
ARG AMF_VERSION=5.7.1
ARG ASYNCAPI_VERSION=2.16.0
ARG ASYNCAPI_PARSER_VERSION=3.6.0
ARG ROVER_VERSION=0.27.0
# buildx populates TARGETARCH ("amd64"/"arm64"); fall back to amd64 for a plain `docker build`.
ARG TARGETARCH=amd64

ENV TOOLS_PREFIX=/opt/objectified-tools
ENV DEBIAN_FRONTEND=noninteractive

# Build/download toolchain: curl+unzip for release archives, node/npm for the JS CLIs,
# git+cmake+g++ to build drafter (no official static release), default-jre for the AMF jar.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip xz-utils tar \
      git cmake build-essential \
      nodejs npm \
      default-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p ${TOOLS_PREFIX}/bin ${TOOLS_PREFIX}/lib

# Normalize arch names once: buf uses x86_64/aarch64; rover uses the Rust triple.
RUN case "${TARGETARCH}" in \
      amd64) echo "x86_64" > /tmp/arch_gnu; echo "x86_64-unknown-linux-gnu" > /tmp/arch_rust ;; \
      arm64) echo "aarch64" > /tmp/arch_gnu; echo "aarch64-unknown-linux-gnu" > /tmp/arch_rust ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac

# buf — single static binary from the GitHub release.
RUN ARCH="$(cat /tmp/arch_gnu)"; \
    curl -fsSL "https://github.com/bufbuild/buf/releases/download/v${BUF_VERSION}/buf-Linux-${ARCH}" \
      -o ${TOOLS_PREFIX}/bin/buf \
    && chmod +x ${TOOLS_PREFIX}/bin/buf

# rover — Apollo GraphQL CLI, prebuilt tarball per Rust target triple.
RUN TRIPLE="$(cat /tmp/arch_rust)"; \
    curl -fsSL "https://github.com/apollographql/rover/releases/download/v${ROVER_VERSION}/rover-v${ROVER_VERSION}-${TRIPLE}.tar.gz" \
      | tar -xz -C /tmp \
    && mv /tmp/dist/rover ${TOOLS_PREFIX}/bin/rover \
    && chmod +x ${TOOLS_PREFIX}/bin/rover

# smithy — official CLI zip ships its own bundled runtime (no separate JRE needed for it).
RUN ARCH="$(cat /tmp/arch_gnu)"; \
    curl -fsSL "https://github.com/smithy-lang/smithy/releases/download/${SMITHY_VERSION}/smithy-cli-linux-${ARCH}.zip" \
      -o /tmp/smithy.zip \
    && unzip -q /tmp/smithy.zip -d /tmp/smithy \
    && mv /tmp/smithy/smithy-cli-linux-${ARCH} ${TOOLS_PREFIX}/lib/smithy \
    && ln -s ${TOOLS_PREFIX}/lib/smithy/bin/smithy ${TOOLS_PREFIX}/bin/smithy \
    && rm -rf /tmp/smithy.zip /tmp/smithy

# AMF — JVM assembly (fat) jar invoked through a thin wrapper so it looks like a native `amf`
# on PATH. aml-org publishes amf-cli to MuleSoft's Nexus (not Maven Central), and only the
# `-assembly` classifier is the self-contained runnable jar; the plain artifact omits its
# dependencies. Needs a JRE at runtime (copied into the runtime stage below).
RUN curl -fsSL "https://repository-master.mulesoft.org/nexus/content/repositories/releases/com/github/amlorg/amf-cli_2.12/${AMF_VERSION}/amf-cli_2.12-${AMF_VERSION}-assembly.jar" \
      -o ${TOOLS_PREFIX}/lib/amf.jar \
    && printf '#!/bin/sh\nexec java -jar %s/lib/amf.jar "$@"\n' "${TOOLS_PREFIX}" > ${TOOLS_PREFIX}/bin/amf \
    && chmod +x ${TOOLS_PREFIX}/bin/amf

# tsp (TypeSpec compiler) + asyncapi CLI + @asyncapi/parser — Node packages installed into the
# tools prefix and wrapped so the runtime invokes them with its own node (no global npm needed at
# runtime). `@asyncapi/parser` backs the MFI-8.1 parse/validate/dereference wrapper below.
RUN npm install --prefix ${TOOLS_PREFIX}/lib/node --no-audit --no-fund \
      "@typespec/compiler@${TSP_VERSION}" "@asyncapi/cli@${ASYNCAPI_VERSION}" \
      "@asyncapi/parser@${ASYNCAPI_PARSER_VERSION}" \
    && printf '#!/bin/sh\nexec node %s/lib/node/node_modules/@typespec/compiler/cmd/tsp.js "$@"\n' "${TOOLS_PREFIX}" > ${TOOLS_PREFIX}/bin/tsp \
    && printf '#!/bin/sh\nexec node %s/lib/node/node_modules/@asyncapi/cli/bin/run.js "$@"\n' "${TOOLS_PREFIX}" > ${TOOLS_PREFIX}/bin/asyncapi \
    && chmod +x ${TOOLS_PREFIX}/bin/tsp ${TOOLS_PREFIX}/bin/asyncapi

# AsyncAPI parse/validate/dereference wrapper (MFI-8.1, #3759). The Node script lives beside the
# installed node_modules so it resolves `@asyncapi/parser` by bare specifier; a thin `asyncapi-parser`
# wrapper on PATH lets app.toolchain_runner invoke it by bare name exactly like the other tools.
COPY objectified-rest/toolchain/asyncapi-parse.mjs ${TOOLS_PREFIX}/lib/node/asyncapi-parse.mjs
RUN printf '#!/bin/sh\nexec node %s/lib/node/asyncapi-parse.mjs "$@"\n' "${TOOLS_PREFIX}" > ${TOOLS_PREFIX}/bin/asyncapi-parser \
    && chmod +x ${TOOLS_PREFIX}/bin/asyncapi-parser ${TOOLS_PREFIX}/lib/node/asyncapi-parse.mjs

# drafter — API Blueprint parser; no official static binary, so build the pinned tag from
# source and install just the resulting CLI. The `drafter` CMake target is the static library
# (libdrafter.a); the command-line tool is the `drafter-cli` target, whose executable is named
# `drafter` (OUTPUT_NAME) and lands in the `src/` subdir of the build tree.
RUN git clone --depth 1 --branch "v${DRAFTER_VERSION}" --recursive \
      https://github.com/apiaryio/drafter.git /tmp/drafter \
    && cmake -S /tmp/drafter -B /tmp/drafter/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/drafter/build --target drafter-cli -j "$(nproc)" \
    && cp /tmp/drafter/build/src/drafter ${TOOLS_PREFIX}/bin/drafter \
    && chmod +x ${TOOLS_PREFIX}/bin/drafter \
    && rm -rf /tmp/drafter

# ── Stage 2: runtime — Python REST API + a Node runtime to execute the TS import worker ──
FROM python:3.12-slim

WORKDIR /app

# libpq5 for psycopg; nodejs to run the tsx-based spec-import worker. Create the non-root
# user up front so the workspace copies below can be chowned in a single layer.
# libpq5 for psycopg; libstdc++6 for native tools (buf/rover/drafter); default-jre-headless
# for the AMF jar wrapper (MFI-5.2). smithy's CLI ships its own runtime, so it needs no JRE.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      libstdc++6 \
      default-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

# Node.js runtime for the tsx spec-import worker. Copy the binary from the Node build stage
# (a real /usr/local/bin/node) rather than relying on Debian's nodejs package, whose layout
# (e.g. /usr/bin/nodejs vs /usr/bin/node) broke the worker's `#!/usr/bin/env node` shebang.
COPY --from=uideps /usr/local/bin/node /usr/local/bin/node

# Python dependencies (requirements.txt + extras from pyproject.toml)
COPY objectified-rest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    bcrypt==4.2.0 \
    email-validator==2.2.0

# Lay the objectified-ui workspace out at "/" so it matches what spec_import_engine resolves:
# _REPO_ROOT = parents[3] of /app/src/app/spec_import_engine.py == "/", so ui_root == /objectified-ui.
# /node_modules holds the hoisted deps (incl. tsx); /objectified-ui/node_modules holds the
# workspace-local .bin/tsx symlink that the worker invocation below points at.
COPY --from=uideps --chown=appuser:appuser /repo/node_modules /node_modules
COPY --from=uideps --chown=appuser:appuser /repo/objectified-ui /objectified-ui

# Polyglot toolchain binaries (MFI-5.2, #3751). Copy the whole bundled-tools tree and put its
# bin/ on PATH so the toolchain runner resolves buf/tsp/smithy/drafter/amf/asyncapi/asyncapi-parser/rover by
# name. The tree is read-only to the app user (owned by root); the runner never writes to it.
COPY --from=tools /opt/objectified-tools /opt/objectified-tools

# Application
COPY --chown=appuser:appuser objectified-rest/src/ /app/src/

USER appuser

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    # Put the bundled toolchain (MFI-5.2) ahead of the system path so the runner resolves
    # buf/tsp/smithy/drafter/amf/asyncapi/asyncapi-parser/rover by bare name. A deployment can still point any
    # OBJECTIFIED_<TOOL>_BIN at a custom binary; an absent tool degrades that format to
    # "unavailable" (surfaced by GET /v1/ops/toolchain) rather than failing the service.
    PATH=/opt/objectified-tools/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    # The worker runs with cwd "/", so tsx can't auto-discover objectified-ui/tsconfig.json;
    # point it there explicitly so the workspace path aliases (@/* -> ./src/*, @lib/* -> ./lib/*)
    # used by the import lib chain resolve.
    TSX_TSCONFIG_PATH=/objectified-ui/tsconfig.json \
    # Pin the spec-import worker invocation (resolver's #1 choice) so it does not depend on
    # yarn/npm being on PATH or on workspace .bin symlink hoisting. cwd for this override is the
    # repo root ("/"): node resolves the bare `tsx` loader from /node_modules, and tsx resolves
    # the worker's relative imports against /objectified-ui and its tsconfig paths.
    SPEC_IMPORT_WORKER_ARGV='["node","--import","tsx","objectified-ui/scripts/rest-spec-import-worker.ts"]'

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
