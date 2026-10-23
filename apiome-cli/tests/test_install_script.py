"""The ``curl -fsSL https://get.apiome.dev | sh`` installer (``apiome-cli/install.sh``).

Offline checks only — nothing here downloads uv or the CLI, or needs root. They pin what a broken
edit would silently ship: the script must parse as POSIX sh (``sh`` is dash on Debian and Ubuntu),
run its whole body from one ``main`` call (so a download cut off mid-way executes nothing), print
its help when piped (no file to read under ``curl | sh``), refuse unknown options, non-git
repository URLs and a relative ``--bin-dir``, stop a system install that cannot get root before
anything is downloaded, and install with the lockfile's constraints.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "install.sh"
SH = shutil.which("sh")
DASH = shutil.which("dash")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(SH is None, reason="sh is not installed")


def _piped(*args: str, path: str = "/usr/bin:/bin") -> subprocess.CompletedProcess[str]:
    """Run the script the way users do: its text on stdin to ``sh -s``.

    Args:
        *args: Installer options, passed after ``sh -s --``.
        path: The ``PATH`` the installer sees.

    Returns:
        The finished process, with text stdout and stderr.
    """
    return subprocess.run(
        [SH, "-s", "--", *args],
        input=SCRIPT.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        env={"PATH": path, "NO_COLOR": "1", "HOME": "/nonexistent"},
        timeout=30,
        check=False,
    )


def test_the_script_parses_as_sh() -> None:
    result = subprocess.run([SH, "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(DASH is None, reason="dash is not installed")
def test_the_script_parses_under_dash() -> None:
    result = subprocess.run([DASH, "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(BASH is None, reason="bash is not installed")
def test_the_script_parses_under_posix_bash() -> None:
    # macOS runs `sh` as bash in POSIX mode.
    result = subprocess.run([BASH, "--posix", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_everything_runs_from_one_main_call_on_the_last_line() -> None:
    lines = [line for line in SCRIPT.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[-1] == 'main "$@"'
    assert lines[0] == "#!/bin/sh"


@pytest.mark.parametrize(
    "pattern",
    [r"pipefail", r"\$'", r"\[\[", r"local -a", r"\bdeclare\b", r"<<<"],
    ids=["pipefail", "ansi-c-quote", "double-bracket", "local-array", "declare", "here-string"],
)
def test_no_bash_only_syntax(pattern: str) -> None:
    code = "\n".join(
        line for line in SCRIPT.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    )
    assert not re.search(pattern, code), f"bash-only syntax {pattern!r} breaks `sh ./get-apiome.sh` on dash"


def test_help_works_when_piped() -> None:
    result = _piped("--help")
    assert result.returncode == 0
    assert "curl -fsSL https://get.apiome.dev -o get-apiome.sh" in result.stdout
    assert "sh ./get-apiome.sh" in result.stdout
    assert "curl -fsSL https://get.apiome.dev | sh" in result.stdout
    for flag in ("--version <ref>", "--repo <url>", "--user", "--bin-dir <dir>", "--no-modify-path", "--uninstall"):
        assert flag in result.stdout


@pytest.mark.parametrize(
    "args,fragment",
    [
        (["--bogus"], "Unknown option: --bogus"),
        (["--version"], "--version needs a value"),
        (["--version="], "--version cannot be empty"),
        (["--repo", "file:///tmp/apiome"], "--repo must be an https:// or ssh:// URL"),
        (["--repo", "git@github.com:apiome/apiome.git"], "--repo must be an https:// or ssh:// URL"),
        (["--bin-dir"], "--bin-dir needs a value"),
        (["--bin-dir", "bin"], "--bin-dir must be an absolute path"),
        (["--user", "--bin-dir", "/usr/local/bin"], "--bin-dir applies to a system install"),
    ],
    ids=[
        "unknown-flag",
        "version-without-value",
        "empty-version",
        "file-repo",
        "scp-style-repo",
        "bin-dir-without-value",
        "relative-bin-dir",
        "bin-dir-with-user",
    ],
)
def test_bad_arguments_fail_before_anything_is_installed(args, fragment) -> None:
    result = _piped(*args)
    assert result.returncode == 1
    assert fragment in result.stderr


def _no_root_path(tmp_path: Path) -> str:
    """A ``PATH`` holding only ``uname`` and an ``id`` that reports a non-root user: no sudo.

    Args:
        tmp_path: A scratch directory for the stub commands.

    Returns:
        The stub directory, to use as the whole ``PATH``.
    """
    uname = shutil.which("uname")
    assert uname is not None
    (tmp_path / "uname").symlink_to(uname)
    stub = tmp_path / "id"
    stub.write_text("#!/bin/sh\necho 1000\n", encoding="utf-8")
    stub.chmod(0o755)
    return str(tmp_path)


@pytest.mark.parametrize("args", [[], ["--uninstall"]], ids=["install", "uninstall"])
def test_a_system_install_without_root_or_sudo_stops_before_downloading(tmp_path: Path, args) -> None:
    # The stub PATH has no curl, git or uv either: the root check must come first.
    result = _piped(*args, path=_no_root_path(tmp_path))
    assert result.returncode == 1
    assert "needs root, and sudo is not available" in result.stderr
    assert "--user" in result.stderr


def test_a_user_install_skips_the_root_check(tmp_path: Path) -> None:
    # Gets past the root check to the next requirement, curl, which the stub PATH lacks.
    result = _piped("--user", path=_no_root_path(tmp_path))
    assert result.returncode == 1
    assert "curl is required" in result.stderr


def test_a_system_install_points_uv_at_opt_apiome_and_the_bin_dir() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'APIOME_SYSTEM_HOME="/opt/apiome"' in text
    for variable in ("UV_TOOL_DIR=", "UV_TOOL_BIN_DIR=\"$BIN_DIR\"", "UV_PYTHON_INSTALL_DIR=", "UV_CACHE_DIR="):
        assert variable in text
    # /usr/bin on Linux; macOS keeps /usr/bin read-only, so /usr/local/bin there.
    assert re.search(r'"Darwin" \]; then\s+printf .%s\\n. "/usr/local/bin"', text)
    assert '"/usr/bin"' in text


def test_it_installs_with_the_lockfile_as_constraints() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "export --frozen --no-dev" in text
    assert "--constraints" in text
    assert "tool install --force" in text
