#!/usr/bin/env bash
# Install native dev toolchain binaries into apiome-rest/.tools/bin (MFI-5.2).
#
# The production image bundles buf (and other CLIs) under /opt/apiome-tools/bin. Local
# `yarn dev` / run.sh uses this script so gRPC/Protobuf catalog import can compile .proto
# files without requiring a system-wide buf install.
#
# Usage:
#   ./scripts/install_dev_toolchain.sh [--force]

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOOLS_BIN="${ROOT}/.tools/bin"
BUF_BIN="${TOOLS_BIN}/buf"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    -h|--help)
      cat <<EOF
Usage: $(basename "$0") [--force]

Installs the pinned buf binary into apiome-rest/.tools/bin for local gRPC/Protobuf import.
Run from the apiome-rest directory (or via ./run.sh / yarn dev).

  --force   Re-download buf even when an executable is already present.
EOF
      exit 0
      ;;
  esac
done

mkdir -p "$TOOLS_BIN"

buf_ok() {
  [[ -x "$BUF_BIN" ]] && "$BUF_BIN" --version >/dev/null 2>&1
}

if buf_ok && [[ "$FORCE" -eq 0 ]]; then
  echo "install_dev_toolchain: buf already installed at ${BUF_BIN} ($("$BUF_BIN" --version 2>/dev/null | head -1))"
  echo "install_dev_toolchain: restart the REST API if gRPC import still shows buf as unavailable."
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "install_dev_toolchain: curl is required to download buf" >&2
  exit 1
fi

# Pinned version — read from BUNDLED_TOOLS (single source of truth; no uv/python needed).
BUF_VERSION="$(
  grep -E '^\s+key="buf"' -A5 src/app/toolchain_packaging.py \
    | grep -E 'version=' | head -1 \
    | sed -E 's/.*version="([^"]+)".*/\1/'
)"
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
echo "install_dev_toolchain: restart the REST API (yarn dev) if it is already running."
