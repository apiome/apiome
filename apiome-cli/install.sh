#!/usr/bin/env bash
#
# Apiome CLI installer — served at https://get.apio.me
#
#   curl -fsSL https://get.apio.me | bash
#
# Installs the `apiome` command with uv (https://docs.astral.sh/uv/) as an isolated tool:
# its own virtual environment and its own Python 3.12+, so nothing touches the system Python.
# uv is installed first (Astral's official installer) when it is not already on the machine.
#
# Options — pass flags after `bash -s --`, or set the environment variables:
#
#   curl -fsSL https://get.apio.me | bash -s -- --version v1.2.0
#   curl -fsSL https://get.apio.me | APIOME_VERSION=v1.2.0 bash
#
#   --version <ref>    Git tag, branch or commit to install        (APIOME_VERSION, default: main)
#   --repo <url>       Git repository to install from              (APIOME_REPO)
#   --no-modify-path   Do not let the uv installer edit shell rc   (APIOME_NO_MODIFY_PATH=1)
#   --uninstall        Remove the apiome CLI (leaves uv in place)
#   -h, --help         Show this help
#
# Requirements: Linux or macOS (Windows: use WSL), curl, git.

# Everything runs inside main(), called on the last line: if the download is cut off part-way,
# bash reaches end-of-input before the call and nothing half-written is executed.

set -euo pipefail

APIOME_DEFAULT_REPO="https://github.com/apiome/apiome"
APIOME_PACKAGE="apiome-cli"
APIOME_SUBDIRECTORY="apiome-cli"
APIOME_PYTHON="3.12"
UV_INSTALLER_URL="https://astral.sh/uv/install.sh"

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

usage() {
  # Inline rather than read from this file: under `curl | bash` there is no file to read.
  cat <<'EOF_USAGE'
Apiome CLI installer

  curl -fsSL https://get.apio.me | bash
  curl -fsSL https://get.apio.me | bash -s -- [options]

Options (or the environment variable in parentheses):
  --version <ref>    Git tag, branch or commit to install   (APIOME_VERSION, default: main)
  --repo <url>       Git repository to install from         (APIOME_REPO)
  --no-modify-path   Do not let the uv installer edit your shell profile (APIOME_NO_MODIFY_PATH=1)
  --uninstall        Remove the apiome CLI (leaves uv in place)
  -h, --help         Show this help

Installs `apiome` with uv as an isolated tool (its own Python 3.12+); installs uv first if needed.
Re-run to upgrade. Requires Linux or macOS (Windows: WSL), curl and git.
EOF_USAGE
}

has() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

check_platform() {
  case "$(uname -s)" in
    Linux | Darwin) ;;
    MINGW* | MSYS* | CYGWIN*)
      die "Windows is not supported by this installer. Run it inside WSL, or install uv and run: uv tool install \"${APIOME_PACKAGE} @ git+${APIOME_DEFAULT_REPO}#subdirectory=${APIOME_SUBDIRECTORY}\"" ;;
    *) die "Unsupported operating system: $(uname -s). Linux and macOS are supported." ;;
  esac
}

check_requirements() {
  has curl || die "curl is required."
  has git || die "git is required to fetch the Apiome CLI source. Install it (e.g. 'sudo apt install git' or 'xcode-select --install') and run the installer again."
}

# ---------------------------------------------------------------------------
# uv
# ---------------------------------------------------------------------------

# Find uv on PATH or in the places its installer puts it, even before a new shell picks it up.
find_uv() {
  if has uv; then
    command -v uv
    return 0
  fi
  local candidate
  for candidate in \
    "${XDG_BIN_HOME:-}/uv" \
    "${HOME}/.local/bin/uv" \
    "${CARGO_HOME:-${HOME}/.cargo}/bin/uv"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_uv() {
  if UV_BIN="$(find_uv)"; then
    step "Using uv at ${UV_BIN} ($("$UV_BIN" --version 2>/dev/null || echo 'version unknown'))"
    return 0
  fi
  step "Installing uv (${UV_INSTALLER_URL})"
  if [ "${NO_MODIFY_PATH}" = "1" ]; then
    curl -fsSL "$UV_INSTALLER_URL" | env UV_NO_MODIFY_PATH=1 sh
  else
    curl -fsSL "$UV_INSTALLER_URL" | sh
  fi
  UV_BIN="$(find_uv)" || die "uv was installed but could not be found. Open a new shell and run the installer again."
}

# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

# Fetch only the CLI's directory at ${VERSION} (a tag, branch or commit) into "$1".
fetch_source() {
  local dest="$1"
  mkdir -p "$dest"
  git -C "$dest" init -q
  git -C "$dest" remote add origin "$REPO"
  # Sparse + blob-less: the repository also holds the web app, docs and images; only the CLI's
  # files are downloaded. Older gits without sparse-checkout simply fetch the whole tree.
  git -C "$dest" sparse-checkout set --no-cone "/${APIOME_SUBDIRECTORY}/" >/dev/null 2>&1 || true
  if ! git -C "$dest" fetch -q --depth 1 --filter=blob:none origin "$VERSION" 2>/dev/null; then
    git -C "$dest" fetch -q --depth 1 origin "$VERSION" \
      || die "Could not fetch '${VERSION}' from ${REPO}. Check the tag, branch or commit."
  fi
  git -C "$dest" checkout -q FETCH_HEAD || die "Could not check out '${VERSION}'."
  [ -f "${dest}/${APIOME_SUBDIRECTORY}/pyproject.toml" ] \
    || die "'${VERSION}' has no ${APIOME_SUBDIRECTORY}/pyproject.toml; is it an Apiome CLI release?"
}

install_cli() {
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/apiome-install.XXXXXX")"
  trap 'rm -rf "$WORK_DIR"' EXIT

  step "Fetching the Apiome CLI from ${REPO} (${VERSION})"
  fetch_source "${WORK_DIR}/src"
  local project="${WORK_DIR}/src/${APIOME_SUBDIRECTORY}"

  # Install with the exact dependency versions the CLI is tested against (its uv.lock), not
  # whatever is newest on PyPI today: `uv tool install` does not read a project's lockfile,
  # so the lock is exported as constraints.
  local constraints="${WORK_DIR}/constraints.txt"
  local -a pin=()
  if [ -f "${project}/uv.lock" ] && (cd "$project" && "$UV_BIN" export --frozen --no-dev \
      --no-hashes --no-emit-project --quiet -o "$constraints") ; then
    pin=(--constraints "$constraints")
  else
    warn "No usable uv.lock at '${VERSION}'; installing the newest compatible dependencies."
  fi

  step "Installing the Apiome CLI"
  # --force replaces an earlier install, so re-running the installer is how you upgrade.
  "$UV_BIN" tool install --force --python "$APIOME_PYTHON" "${pin[@]}" "$project" \
    || die "Installation failed."
}

uninstall_cli() {
  UV_BIN="$(find_uv)" || die "uv is not installed, so there is no Apiome CLI to remove."
  step "Removing the Apiome CLI"
  if "$UV_BIN" tool uninstall "$APIOME_PACKAGE"; then
    say "${GREEN}Removed.${RESET} uv itself was left in place (remove it with: uv self uninstall)."
  else
    die "The Apiome CLI does not appear to be installed with uv."
  fi
}

# ---------------------------------------------------------------------------
# After install
# ---------------------------------------------------------------------------

report() {
  local bin_dir apiome_bin
  bin_dir="$("$UV_BIN" tool dir --bin 2>/dev/null || printf '%s' "${HOME}/.local/bin")"
  apiome_bin="${bin_dir}/apiome"

  if [ ! -x "$apiome_bin" ]; then
    die "The install finished but ${apiome_bin} is missing."
  fi
  # Prove the command actually runs, rather than reporting success on an install that cannot
  # start (a missing or incompatible dependency).
  local version
  if ! version="$("$apiome_bin" --version 2>&1)"; then
    printf '%s\n' "$version" >&2
    die "apiome was installed but does not start. Please report this, with the output above."
  fi
  say ""
  say "${GREEN}${BOLD}Apiome CLI installed${RESET} ${version:+(${version})}"
  say "  ${apiome_bin}"

  case ":${PATH}:" in
    *":${bin_dir}:"*) ;;
    *)
      say ""
      warn "${bin_dir} is not on your PATH yet."
      say "  Open a new terminal, or add it for this shell:"
      say "    export PATH=\"${bin_dir}:\$PATH\""
      [ "${NO_MODIFY_PATH}" = "1" ] && say "  (or run: uv tool update-shell)"
      ;;
  esac

  say ""
  say "Next steps:"
  say "  apiome --help                 # every command"
  say "  apiome doctor                 # check you can reach your Apiome server"
  say "  apiome config --help          # set the server URL, tenant and API key"
  say ""
  say "Upgrade by running the installer again; uninstall with:"
  say "  curl -fsSL https://get.apio.me | bash -s -- --uninstall"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
  VERSION="${APIOME_VERSION:-main}"
  REPO="${APIOME_REPO:-$APIOME_DEFAULT_REPO}"
  NO_MODIFY_PATH="${APIOME_NO_MODIFY_PATH:-0}"
  local action="install"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --version) [ "$#" -ge 2 ] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
      --version=*) VERSION="${1#*=}"; shift ;;
      --repo) [ "$#" -ge 2 ] || die "--repo needs a value"; REPO="$2"; shift 2 ;;
      --repo=*) REPO="${1#*=}"; shift ;;
      --no-modify-path) NO_MODIFY_PATH=1; shift ;;
      --uninstall) action="uninstall"; shift ;;
      -h | --help) usage; exit 0 ;;
      *) die "Unknown option: $1 (see --help)" ;;
    esac
  done

  [ -n "$VERSION" ] || die "--version cannot be empty"
  case "$REPO" in
    https://* | ssh://*) ;;
    *) die "--repo must be an https:// or ssh:// URL, e.g. ssh://git@github.com/apiome/apiome (got: ${REPO})" ;;
  esac

  check_platform
  if [ "$action" = "uninstall" ]; then
    uninstall_cli
    return 0
  fi

  check_requirements
  ensure_uv
  install_cli
  report
}

main "$@"
