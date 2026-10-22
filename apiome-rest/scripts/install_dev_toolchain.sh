#!/usr/bin/env bash
# Install dev toolchain binaries into apiome-rest/.tools/bin (MFI-5.2, FMT-1.3, FMT-8.1, FMT-8.2).
#
# The production image bundles buf (and other CLIs) under /opt/apiome-tools/bin. Local
# `yarn dev` / run.sh uses this script so gRPC/Protobuf catalog import can compile .proto
# files without requiring a system-wide buf install.
#
# Two kinds of tool are installed:
#
#   buf              optional — its absence degrades gRPC/Protobuf import to "unavailable".
#   asyncapi-parser  REQUIRED (FMT-1.3, #5414) — the AsyncAPI adapter has no fallback parser,
#                    so a runtime without it loses a shipped format. Its exact version is
#                    pinned in toolchain/package.json (the toolchain manifest), which is what
#                    the container build and CI install from too.
#   typescript-types-extractor
#                    REQUIRED (FMT-8.1, #5462) — TypeScript type declarations are read by the
#                    TypeScript compiler itself; `typescript` is pinned in the same manifest.
#   zod-schema-extractor
#                    REQUIRED (FMT-8.2, #5463) — evaluates a module's Zod schemas with the
#                    pinned `zod` (and transpiles with the pinned `typescript`).
#
# Usage:
#   ./scripts/install_dev_toolchain.sh [--force] [tool ...]
#
# With no tool named, everything above is installed. Name one or more (`buf`,
# `asyncapi-parser`, `typescript-types-extractor`, `zod-schema-extractor`) to install just those — CI uses that to add
# the required Node tools without re-downloading buf.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOOLS_BIN="${ROOT}/.tools/bin"
BUF_BIN="${TOOLS_BIN}/buf"
FORCE=0

SELECTED=()

for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    -h|--help)
      cat <<EOF
Usage: $(basename "$0") [--force] [tool ...]

Installs the pinned buf binary and the required @asyncapi/parser, typescript and zod toolchain
into apiome-rest/.tools/ for local gRPC/Protobuf, AsyncAPI, TypeScript-types and Zod import.
Run from the apiome-rest directory (or via ./run.sh / yarn dev).

  --force   Re-install even when a working tool is already present.
  tool      Install only the named tool(s): buf, asyncapi-parser,
            typescript-types-extractor, zod-schema-extractor. Default: all.
EOF
      exit 0
      ;;
    buf|asyncapi-parser|typescript-types-extractor|zod-schema-extractor) SELECTED+=("$arg") ;;
    *)
      echo "install_dev_toolchain: unknown argument '${arg}' (try --help)" >&2
      exit 1
      ;;
  esac
done

# Whether this run should install the named tool (no selection means "install everything").
wanted() {
  [[ ${#SELECTED[@]} -eq 0 ]] && return 0
  local tool
  for tool in "${SELECTED[@]}"; do
    [[ "$tool" == "$1" ]] && return 0
  done
  return 1
}

mkdir -p "$TOOLS_BIN"

# Pinned version — read from BUNDLED_TOOLS (single source of truth; no uv/python needed).
pinned_buf_version() {
  grep -E '^\s+key="buf"' -A8 src/app/toolchain_packaging.py \
    | grep -E 'version=' | head -1 \
    | sed -E 's/.*version="([^"]+)".*/\1/'
}

# A pre-existing binary counts only when it is the *pinned* version. Checking merely that it
# runs would pin the version in name only: an older buf installed before a pin bump would sit
# there forever and quietly fail the features that bump was for (FMT-3.7 raised the pin to
# 1.72.0 for Protobuf Edition 2024, which 1.50.0 refuses to compile).
buf_ok() {
  [[ -x "$BUF_BIN" ]] || return 1
  local installed wanted
  installed="$("$BUF_BIN" --version 2>/dev/null | head -1 | tr -d '[:space:]')" || return 1
  [[ -n "$installed" ]] || return 1
  wanted="$(pinned_buf_version)"
  # With no pin readable, fall back to "it runs" rather than reinstalling on every invocation.
  [[ -z "$wanted" ]] && return 0
  [[ "$installed" == "$wanted" ]]
}

install_buf() {
  if buf_ok && [[ "$FORCE" -eq 0 ]]; then
    echo "install_dev_toolchain: buf already installed at ${BUF_BIN} ($("$BUF_BIN" --version 2>/dev/null | head -1))"
    echo "install_dev_toolchain: restart the REST API if gRPC import still shows buf as unavailable."
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "install_dev_toolchain: curl is required to download buf" >&2
    exit 1
  fi

  BUF_VERSION="$(pinned_buf_version)"
  if [[ -z "$BUF_VERSION" ]]; then
    echo "install_dev_toolchain: could not read buf version from src/app/toolchain_packaging.py" >&2
    exit 1
  fi

  OS="$(uname -s)"
  ARCH="$(uname -m)"
  case "${OS}" in
    Linux)
      BUF_OS=Linux
      case "${ARCH}" in
        x86_64) BUF_ARCH=x86_64 ;;
        aarch64|arm64) BUF_ARCH=aarch64 ;;
        *)
          echo "install_dev_toolchain: unsupported Linux architecture: ${ARCH}" >&2
          exit 1
          ;;
      esac
      ;;
    Darwin)
      BUF_OS=Darwin
      case "${ARCH}" in
        x86_64) BUF_ARCH=x86_64 ;;
        arm64) BUF_ARCH=arm64 ;;
        *)
          echo "install_dev_toolchain: unsupported macOS architecture: ${ARCH}" >&2
          exit 1
          ;;
      esac
      ;;
    *)
      echo "install_dev_toolchain: unsupported OS: ${OS}" >&2
      exit 1
      ;;
  esac

  URL="https://github.com/bufbuild/buf/releases/download/v${BUF_VERSION}/buf-${BUF_OS}-${BUF_ARCH}"
  echo "install_dev_toolchain: downloading buf ${BUF_VERSION} (${BUF_OS}-${BUF_ARCH})"
  curl -fsSL "${URL}" -o "${BUF_BIN}.tmp"
  chmod +x "${BUF_BIN}.tmp"
  mv "${BUF_BIN}.tmp" "${BUF_BIN}"

  if ! buf_ok; then
    echo "install_dev_toolchain: download finished but '${BUF_BIN} --version' failed" >&2
    exit 1
  fi

  echo "install_dev_toolchain: installed ${BUF_BIN} ($("$BUF_BIN" --version 2>/dev/null | head -1))"
}

# ---------------------------------------------------------------------------------------
# asyncapi-parser — REQUIRED (FMT-1.3, #5414)
# ---------------------------------------------------------------------------------------
#
# `toolchain/asyncapi-parse.mjs` imports `@asyncapi/parser` by bare specifier, so it has to
# sit *beside* the installed node_modules (node resolves from the script's own realpath, which
# is why the script is copied rather than symlinked — exactly what the Dockerfile does). The
# wrapper on .tools/bin then makes it look like any other bundled binary to
# app.toolchain_runner.

NODE_PREFIX="${ROOT}/.tools/node"
PARSER_BIN="${TOOLS_BIN}/asyncapi-parser"

parser_ok() {
  [[ -x "$PARSER_BIN" ]] && "$PARSER_BIN" --version >/dev/null 2>&1
}

install_asyncapi_parser() {
  # Exact pin from the toolchain manifest — the single place the version is written for the
  # container build, CI and local dev alike.
  local pin
  pin="$(
    grep -E '"@asyncapi/parser"' toolchain/package.json \
      | sed -E 's/.*"@asyncapi\/parser"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/'
  )"
  if [[ -z "$pin" ]]; then
    echo "install_dev_toolchain: could not read the @asyncapi/parser pin from toolchain/package.json" >&2
    exit 1
  fi

  if parser_ok && [[ "$FORCE" -eq 0 ]] && "$PARSER_BIN" --version 2>/dev/null | grep -qF " ${pin}"; then
    echo "install_dev_toolchain: asyncapi-parser already installed at ${PARSER_BIN} ($("$PARSER_BIN" --version 2>/dev/null | head -1))"
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "install_dev_toolchain: npm is required to install @asyncapi/parser@${pin}." >&2
    echo "install_dev_toolchain: AsyncAPI import is a REQUIRED format — without it the service" >&2
    echo "install_dev_toolchain: refuses to start when APIOME_REQUIRE_TOOLCHAIN is on." >&2
    exit 1
  fi

  echo "install_dev_toolchain: installing @asyncapi/parser@${pin} into ${NODE_PREFIX}"
  mkdir -p "$NODE_PREFIX"
  npm install --prefix "$NODE_PREFIX" --no-audit --no-fund --silent "@asyncapi/parser@${pin}"
  cp "${ROOT}/toolchain/asyncapi-parse.mjs" "${NODE_PREFIX}/asyncapi-parse.mjs"
  chmod +x "${NODE_PREFIX}/asyncapi-parse.mjs"
  printf '#!/bin/sh\nexec node %s/asyncapi-parse.mjs "$@"\n' "$NODE_PREFIX" > "$PARSER_BIN"
  chmod +x "$PARSER_BIN"

  if ! parser_ok; then
    echo "install_dev_toolchain: install finished but '${PARSER_BIN} --version' failed" >&2
    exit 1
  fi
  echo "install_dev_toolchain: installed ${PARSER_BIN} ($("$PARSER_BIN" --version 2>/dev/null | head -1))"
}

# ---------------------------------------------------------------------------------------
# typescript-types-extractor — REQUIRED (FMT-8.1, #5462)
# ---------------------------------------------------------------------------------------
#
# Same layout as the AsyncAPI parser: `toolchain/typescript-types-extract.mjs` imports the
# `typescript` package by bare specifier, so it is copied beside the shared node_modules and
# fronted by a wrapper on .tools/bin.

EXTRACTOR_BIN="${TOOLS_BIN}/typescript-types-extract"

extractor_ok() {
  [[ -x "$EXTRACTOR_BIN" ]] && "$EXTRACTOR_BIN" --version >/dev/null 2>&1
}

install_typescript_types_extractor() {
  local pin
  pin="$(
    grep -E '"typescript"' toolchain/package.json \
      | sed -E 's/.*"typescript"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/'
  )"
  if [[ -z "$pin" ]]; then
    echo "install_dev_toolchain: could not read the typescript pin from toolchain/package.json" >&2
    exit 1
  fi

  # The script is re-copied even when the package is current, so an edit to the extractor in
  # the source tree reaches the installed copy on the next run.
  if extractor_ok && [[ "$FORCE" -eq 0 ]] && "$EXTRACTOR_BIN" --version 2>/dev/null | grep -qF " ${pin}"; then
    cp "${ROOT}/toolchain/typescript-types-extract.mjs" "${NODE_PREFIX}/typescript-types-extract.mjs"
    echo "install_dev_toolchain: typescript-types-extract already installed at ${EXTRACTOR_BIN} ($("$EXTRACTOR_BIN" --version 2>/dev/null | head -1))"
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "install_dev_toolchain: npm is required to install typescript@${pin}." >&2
    echo "install_dev_toolchain: TypeScript-types import is a REQUIRED format — without it the" >&2
    echo "install_dev_toolchain: service refuses to start when APIOME_REQUIRE_TOOLCHAIN is on." >&2
    exit 1
  fi

  echo "install_dev_toolchain: installing typescript@${pin} into ${NODE_PREFIX}"
  mkdir -p "$NODE_PREFIX"
  npm install --prefix "$NODE_PREFIX" --no-audit --no-fund --silent "typescript@${pin}"
  cp "${ROOT}/toolchain/typescript-types-extract.mjs" "${NODE_PREFIX}/typescript-types-extract.mjs"
  chmod +x "${NODE_PREFIX}/typescript-types-extract.mjs"
  printf '#!/bin/sh\nexec node %s/typescript-types-extract.mjs "$@"\n' "$NODE_PREFIX" > "$EXTRACTOR_BIN"
  chmod +x "$EXTRACTOR_BIN"

  if ! extractor_ok; then
    echo "install_dev_toolchain: install finished but '${EXTRACTOR_BIN} --version' failed" >&2
    exit 1
  fi
  echo "install_dev_toolchain: installed ${EXTRACTOR_BIN} ($("$EXTRACTOR_BIN" --version 2>/dev/null | head -1))"
}

# ---------------------------------------------------------------------------------------
# zod-schema-extractor — REQUIRED (FMT-8.2, #5463)
# ---------------------------------------------------------------------------------------
#
# `toolchain/zod-extract.mjs` loads `zod` and `typescript` from the shared node_modules beside
# it, and re-executes itself under Node's permission model with read access to that directory
# only — which is why it must be *copied* there, not symlinked.

ZOD_BIN="${TOOLS_BIN}/zod-extract"

zod_ok() {
  [[ -x "$ZOD_BIN" ]] && "$ZOD_BIN" --version >/dev/null 2>&1
}

install_zod_schema_extractor() {
  local zod_pin ts_pin
  zod_pin="$(grep -E '"zod"' toolchain/package.json | sed -E 's/.*"zod"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
  ts_pin="$(grep -E '"typescript"' toolchain/package.json | sed -E 's/.*"typescript"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
  if [[ -z "$zod_pin" || -z "$ts_pin" ]]; then
    echo "install_dev_toolchain: could not read the zod / typescript pins from toolchain/package.json" >&2
    exit 1
  fi

  if zod_ok && [[ "$FORCE" -eq 0 ]] && "$ZOD_BIN" --version 2>/dev/null | grep -qF " ${zod_pin}"; then
    cp "${ROOT}/toolchain/zod-extract.mjs" "${NODE_PREFIX}/zod-extract.mjs"
    echo "install_dev_toolchain: zod-extract already installed at ${ZOD_BIN} ($("$ZOD_BIN" --version 2>/dev/null | head -1))"
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "install_dev_toolchain: npm is required to install zod@${zod_pin}." >&2
    echo "install_dev_toolchain: Zod import is a REQUIRED format — without it the service" >&2
    echo "install_dev_toolchain: refuses to start when APIOME_REQUIRE_TOOLCHAIN is on." >&2
    exit 1
  fi

  echo "install_dev_toolchain: installing zod@${zod_pin} and typescript@${ts_pin} into ${NODE_PREFIX}"
  mkdir -p "$NODE_PREFIX"
  npm install --prefix "$NODE_PREFIX" --no-audit --no-fund --silent "zod@${zod_pin}" "typescript@${ts_pin}"
  cp "${ROOT}/toolchain/zod-extract.mjs" "${NODE_PREFIX}/zod-extract.mjs"
  chmod +x "${NODE_PREFIX}/zod-extract.mjs"
  printf '#!/bin/sh\nexec node %s/zod-extract.mjs "$@"\n' "$NODE_PREFIX" > "$ZOD_BIN"
  chmod +x "$ZOD_BIN"

  if ! zod_ok; then
    echo "install_dev_toolchain: install finished but '${ZOD_BIN} --version' failed" >&2
    exit 1
  fi
  echo "install_dev_toolchain: installed ${ZOD_BIN} ($("$ZOD_BIN" --version 2>/dev/null | head -1))"
}

if wanted buf; then
  install_buf
fi
if wanted asyncapi-parser; then
  install_asyncapi_parser
fi
if wanted typescript-types-extractor; then
  install_typescript_types_extractor
fi
if wanted zod-schema-extractor; then
  install_zod_schema_extractor
fi

echo "install_dev_toolchain: restart the REST API (yarn dev) if it is already running."
