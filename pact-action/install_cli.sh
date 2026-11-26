#!/usr/bin/env bash
# Install the Apiome CLI for apiome/pact-action (PFX-4.3 / #6940).
#
# Does nothing when an `apiome` command is already on PATH (a self-hosted runner, or an earlier
# step that installed it). Otherwise downloads the installer from https://get.apiome.dev, installs
# for the runner user only (~/.local/bin, no sudo) and adds that folder to GITHUB_PATH so the
# next step finds the command.
#
# Env:
#   APIOME_VERSION      Git tag, branch or commit to install (default: main)
#   APIOME_INSTALLER_URL  Installer URL (default: https://get.apiome.dev) — override in tests
#   GITHUB_PATH         Set by the runner; the install folder is appended to it
#   CURL_BIN            curl binary — override in tests
#
# Exit codes: 0 installed or already present, 1 the download or the install failed.

set -euo pipefail

CURL_BIN="${CURL_BIN:-curl}"
INSTALLER_URL="${APIOME_INSTALLER_URL:-https://get.apiome.dev}"
VERSION="${APIOME_VERSION:-main}"
BIN_DIR="${HOME}/.local/bin"

if command -v apiome >/dev/null 2>&1; then
  echo "pact-action: using the apiome already on PATH ($(command -v apiome))"
  exit 0
fi

installer="$(mktemp)"
trap 'rm -f "${installer}"' EXIT

if ! "${CURL_BIN}" -fsSL "${INSTALLER_URL}" -o "${installer}"; then
  echo "::error::pact-action: could not download the Apiome CLI installer from ${INSTALLER_URL}"
  exit 1
fi
if ! sh "${installer}" --user --no-modify-path --version "${VERSION}"; then
  echo "::error::pact-action: the Apiome CLI installer failed (version ${VERSION})"
  exit 1
fi

if [[ -n "${GITHUB_PATH:-}" ]]; then
  echo "${BIN_DIR}" >>"${GITHUB_PATH}"
fi
echo "pact-action: installed the Apiome CLI ${VERSION} into ${BIN_DIR}"
