#!/bin/sh
#
# Apiome CLI installer — served at https://get.apiome.dev
#
#   curl -fsSL https://get.apiome.dev -o get-apiome.sh
#   sh ./get-apiome.sh
#
# or piped:  curl -fsSL https://get.apiome.dev | sh
#
# Installs the `apiome` command with uv (https://docs.astral.sh/uv/) as an isolated tool: its own
# virtual environment and its own Python 3.12+, so nothing touches the system Python. uv is
# installed first (Astral's official installer) when it is not already on the machine.
#
# By default the install is system-wide: the tool and its Python live in /opt/apiome and `apiome`
# is linked into /usr/bin (/usr/local/bin on macOS, where /usr/bin is read-only). That needs root,
# so the installer uses sudo when it is not already running as root. Pass --user to install for
# the current user only, into ~/.local/bin, with no sudo.
#
# Options — pass flags after the script name (or after `sh -s --` when piped), or set the
# environment variables:
#
#   sh ./get-apiome.sh --version v1.2.0
#   curl -fsSL https://get.apiome.dev | sh -s -- --user
#   curl -fsSL https://get.apiome.dev | APIOME_VERSION=v1.2.0 sh
#
#   --version <ref>    Git tag, branch or commit to install        (APIOME_VERSION, default: main)
#   --repo <url>       Git repository to install from              (APIOME_REPO)
#   --user             Install for this user only, into ~/.local/bin (APIOME_USER_INSTALL=1)
#   --bin-dir <dir>    Where a system install links `apiome`       (APIOME_BIN_DIR)
#   --no-modify-path   Do not let the uv installer edit shell rc   (APIOME_NO_MODIFY_PATH=1)
#   --uninstall        Remove the apiome CLI (leaves uv in place)
#   -h, --help         Show this help
#
# Requirements: Linux or macOS (Windows: use WSL), curl, git; sudo or root for a system install.
#
# POSIX sh: Debian and Ubuntu run `sh` as dash, so no bash-only syntax ($'…', arrays, [[ ]],
# pipefail). tests/test_install_script.py checks the script under dash.

# Everything runs inside main(), called on the last line: if the download is cut off part-way,
# the shell reaches end-of-input before the call and nothing half-written is executed.

set -eu

APIOME_DEFAULT_REPO="https://github.com/apiome/apiome"
APIOME_PACKAGE="apiome-cli"
APIOME_SUBDIRECTORY="apiome-cli"
APIOME_PYTHON="3.12"
APIOME_SYSTEM_HOME="/opt/apiome"
UV_INSTALLER_URL="https://astral.sh/uv/install.sh"

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  ESC="$(printf '\033')"
  BOLD="${ESC}[1m"; RED="${ESC}[31m"; GREEN="${ESC}[32m"; YELLOW="${ESC}[33m"; RESET="${ESC}[0m"
else
  BOLD=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi

say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

usage() {
  # Inline rather than read from this file: under `curl | sh` there is no file to read.
  cat <<'EOF_USAGE'
Apiome CLI installer

  curl -fsSL https://get.apiome.dev -o get-apiome.sh
  sh ./get-apiome.sh [options]

  curl -fsSL https://get.apiome.dev | sh
  curl -fsSL https://get.apiome.dev | sh -s -- [options]

Options (or the environment variable in parentheses):
  --version <ref>    Git tag, branch or commit to install   (APIOME_VERSION, default: main)
  --repo <url>       Git repository to install from         (APIOME_REPO)
  --user             Install for this user only, into ~/.local/bin, without sudo
                     (APIOME_USER_INSTALL=1)
  --bin-dir <dir>    Where a system install links apiome    (APIOME_BIN_DIR,
                     default: /usr/bin, or /usr/local/bin on macOS)
  --no-modify-path   Do not let the uv installer edit your shell profile (APIOME_NO_MODIFY_PATH=1)
  --uninstall        Remove the apiome CLI (leaves uv in place); add --user for a user install
  -h, --help         Show this help

Installs `apiome` with uv as an isolated tool (its own Python 3.12+); installs uv first if needed.
A system install keeps the tool in /opt/apiome and uses sudo unless run as root.
Re-run to upgrade. Requires Linux or macOS (Windows: WSL), curl and git.
EOF_USAGE
}

has() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

check_platform() {
  OS="$(uname -s)"
  case "$OS" in
    Linux | Darwin) ;;
    MINGW* | MSYS* | CYGWIN*)
      die "Windows is not supported by this installer. Run it inside WSL, or install uv and run: uv tool install \"${APIOME_PACKAGE} @ git+${APIOME_DEFAULT_REPO}#subdirectory=${APIOME_SUBDIRECTORY}\"" ;;
    *) die "Unsupported operating system: ${OS}. Linux and macOS are supported." ;;
  esac
}

check_requirements() {
  has curl || die "curl is required."
  has git || die "git is required to fetch the Apiome CLI source. Install it (e.g. 'sudo apt install git' or 'xcode-select --install') and run the installer again."
}

# ---------------------------------------------------------------------------
# Install scope: system-wide (default) or --user
# ---------------------------------------------------------------------------

# The folder a system install links `apiome` into: /usr/bin on Linux; /usr/local/bin on macOS,
# where System Integrity Protection keeps /usr/bin read-only even for root.
default_bin_dir() {
  if [ "$OS" = "Darwin" ]; then
    printf '%s\n' "/usr/local/bin"
  else
    printf '%s\n' "/usr/bin"
  fi
}

# Decide how a system install gets root, before anything is downloaded: directly when already
# root, through sudo otherwise. Sets ROOT_RUNNER to "direct" or "sudo".
check_root() {
  if [ "$(id -u)" = "0" ]; then
    ROOT_RUNNER="direct"
  elif has sudo; then
    ROOT_RUNNER="sudo"
    step "A system install writes to ${APIOME_SYSTEM_HOME} and ${BIN_DIR}; sudo may ask for your password"
  else
    die "A system install needs root, and sudo is not available. Run the installer as root, or install for this user only with --user (into ~/.local/bin)."
  fi
}

# Run "$@" as root, with a umask that leaves the installed files readable by every user.
as_root() {
  if [ "$ROOT_RUNNER" = "sudo" ]; then
    sudo sh -c 'umask 022 && exec "$@"' apiome-install "$@"
  else
    sh -c 'umask 022 && exec "$@"' apiome-install "$@"
  fi
}

# Run uv for the chosen scope. A system install points uv's tool, Python and cache folders at
# /opt/apiome and its bin folder at BIN_DIR, so the result belongs to no one's home directory.
run_uv() {
  if [ "$SCOPE" = "user" ]; then
    "$UV_BIN" "$@"
  else
    as_root env \
      UV_TOOL_DIR="${APIOME_SYSTEM_HOME}/tools" \
      UV_TOOL_BIN_DIR="$BIN_DIR" \
      UV_PYTHON_INSTALL_DIR="${APIOME_SYSTEM_HOME}/python" \
      UV_PYTHON_BIN_DIR="${APIOME_SYSTEM_HOME}/python/bin" \
      UV_CACHE_DIR="${APIOME_SYSTEM_HOME}/cache" \
      "$UV_BIN" "$@"
  fi
}

# ---------------------------------------------------------------------------
# uv
# ---------------------------------------------------------------------------

# Find uv on PATH or in the places its installer puts it, even before a new shell picks it up.
# Prints the path; returns 1 when there is none.
find_uv() {
  if has uv; then
    command -v uv
    return 0
  fi
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
  # Downloaded to a file rather than piped, so a failed download stops here (no pipefail in sh).
  local uv_installer
  uv_installer="${WORK_DIR}/uv-install.sh"
  curl -fsSL "$UV_INSTALLER_URL" -o "$uv_installer" || die "Could not download the uv installer."
  if [ "${NO_MODIFY_PATH}" = "1" ]; then
    env UV_NO_MODIFY_PATH=1 sh "$uv_installer" || die "The uv installer failed."
  else
    sh "$uv_installer" || die "The uv installer failed."
  fi
  UV_BIN="$(find_uv)" || die "uv was installed but could not be found. Open a new shell and run the installer again."
}

# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

make_work_dir() {
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/apiome-install.XXXXXX")"
  trap 'rm -rf "$WORK_DIR"' EXIT
}

# Fetch only the CLI's directory at ${VERSION} (a tag, branch or commit) into "$1".
fetch_source() {
  local dest
  dest="$1"
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
  step "Fetching the Apiome CLI from ${REPO} (${VERSION})"
  fetch_source "${WORK_DIR}/src"
  local project constraints
  project="${WORK_DIR}/src/${APIOME_SUBDIRECTORY}"

  # Install with the exact dependency versions the CLI is tested against (its uv.lock), not
  # whatever is newest on PyPI today: `uv tool install` does not read a project's lockfile,
  # so the lock is exported as constraints. The export runs as you, even for a system install.
  constraints="${WORK_DIR}/constraints.txt"
  if [ -f "${project}/uv.lock" ] && (cd "$project" && "$UV_BIN" export --frozen --no-dev \
      --no-hashes --no-emit-project --quiet -o "$constraints") ; then
    :
  else
    warn "No usable uv.lock at '${VERSION}'; installing the newest compatible dependencies."
    constraints=""
  fi

  if [ "$SCOPE" = "user" ]; then
    step "Installing the Apiome CLI for $(id -un 2>/dev/null || echo 'this user')"
  else
    step "Installing the Apiome CLI system-wide (${APIOME_SYSTEM_HOME}, linked into ${BIN_DIR})"
  fi
  # --force replaces an earlier install, so re-running the installer is how you upgrade.
  if [ -n "$constraints" ]; then
    run_uv tool install --force --python "$APIOME_PYTHON" --constraints "$constraints" "$project" \
      || die "Installation failed."
  else
    run_uv tool install --force --python "$APIOME_PYTHON" "$project" \
      || die "Installation failed."
  fi
}

uninstall_cli() {
  UV_BIN="$(find_uv)" || die "uv is not installed, so there is no Apiome CLI to remove."
  step "Removing the Apiome CLI"
  if [ "$SCOPE" = "user" ]; then
    "$UV_BIN" tool uninstall "$APIOME_PACKAGE" \
      || die "The Apiome CLI does not appear to be installed for this user. For a system install, run --uninstall without --user."
  else
    [ -d "${APIOME_SYSTEM_HOME}/tools" ] \
      || die "There is no system install in ${APIOME_SYSTEM_HOME}. For a user install, run --uninstall --user."
    run_uv tool uninstall "$APIOME_PACKAGE" || die "uv could not remove the system install."
    # The tool, its Python and uv's cache all live under the installer's own folder.
    as_root rm -rf "$APIOME_SYSTEM_HOME"
  fi
  say "${GREEN}Removed.${RESET} uv itself was left in place (remove it with: uv self uninstall)."
}

# ---------------------------------------------------------------------------
# After install
# ---------------------------------------------------------------------------

report() {
  local bin_dir apiome_bin version
  if [ "$SCOPE" = "user" ]; then
    bin_dir="$("$UV_BIN" tool dir --bin 2>/dev/null || printf '%s' "${HOME}/.local/bin")"
  else
    bin_dir="$BIN_DIR"
  fi
  apiome_bin="${bin_dir}/apiome"

  if [ ! -x "$apiome_bin" ]; then
    die "The install finished but ${apiome_bin} is missing."
  fi
  # Prove the command actually runs — as you, not root — rather than reporting success on an
  # install that cannot start (a missing dependency, or files other users cannot read).
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
      if [ "$SCOPE" = "user" ] && [ "${NO_MODIFY_PATH}" = "1" ]; then
        say "  (or run: uv tool update-shell)"
      fi
      ;;
  esac

  local uninstall_flags
  uninstall_flags="--uninstall"
  [ "$SCOPE" = "user" ] && uninstall_flags="--uninstall --user"
  say ""
  say "Next steps:"
  say "  apiome --help                 # every command"
  say "  apiome doctor                 # check you can reach your Apiome server"
  say "  apiome config --help          # set the server URL, tenant and API key"
  say ""
  say "Upgrade by running the installer again; uninstall with:"
  say "  curl -fsSL https://get.apiome.dev | sh -s -- ${uninstall_flags}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
  VERSION="${APIOME_VERSION:-main}"
  REPO="${APIOME_REPO:-$APIOME_DEFAULT_REPO}"
  NO_MODIFY_PATH="${APIOME_NO_MODIFY_PATH:-0}"
  BIN_DIR="${APIOME_BIN_DIR:-}"
  SCOPE="system"
  [ "${APIOME_USER_INSTALL:-0}" = "1" ] && SCOPE="user"
  ROOT_RUNNER=""
  local action
  action="install"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --version) [ "$#" -ge 2 ] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
      --version=*) VERSION="${1#*=}"; shift ;;
      --repo) [ "$#" -ge 2 ] || die "--repo needs a value"; REPO="$2"; shift 2 ;;
      --repo=*) REPO="${1#*=}"; shift ;;
      --bin-dir) [ "$#" -ge 2 ] || die "--bin-dir needs a value"; BIN_DIR="$2"; shift 2 ;;
      --bin-dir=*) BIN_DIR="${1#*=}"; shift ;;
      --user) SCOPE="user"; shift ;;
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
  if [ -n "$BIN_DIR" ]; then
    [ "$SCOPE" = "system" ] || die "--bin-dir applies to a system install; drop --user, or drop --bin-dir."
    case "$BIN_DIR" in
      /*) ;;
      *) die "--bin-dir must be an absolute path, e.g. /usr/local/bin (got: ${BIN_DIR})" ;;
    esac
  fi

  check_platform
  if [ "$SCOPE" = "system" ]; then
    [ -n "$BIN_DIR" ] || BIN_DIR="$(default_bin_dir)"
    check_root
  fi

  if [ "$action" = "uninstall" ]; then
    uninstall_cli
    return 0
  fi

  check_requirements
  make_work_dir
  ensure_uv
  install_cli
  report
}

main "$@"
