"""The ``curl -fsSL https://get.apio.me | bash`` installer (``apiome-cli/install.sh``).

Offline checks only — nothing here downloads uv or the CLI. They pin what a broken edit would
silently ship: the script must parse, run its whole body from one ``main`` call (so a download cut
off mid-way executes nothing), print its help when piped (no file to read under ``curl | bash``),
refuse unknown options and non-git repository URLs, and install with the lockfile's constraints.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")


def _piped(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the script the way users do: its text on stdin to ``bash -s``."""
    return subprocess.run(
        ["bash", "-s", "--", *args],
        input=SCRIPT.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "NO_COLOR": "1", "HOME": "/nonexistent"},
        timeout=30,
        check=False,
    )


def test_the_script_parses() -> None:
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_everything_runs_from_one_main_call_on_the_last_line() -> None:
    lines = [line for line in SCRIPT.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[-1] == 'main "$@"'
    assert lines[0] == "#!/usr/bin/env bash"


def test_help_works_when_piped() -> None:
    result = _piped("--help")
    assert result.returncode == 0
    assert "curl -fsSL https://get.apio.me | bash" in result.stdout
    for flag in ("--version <ref>", "--repo <url>", "--no-modify-path", "--uninstall"):
        assert flag in result.stdout


@pytest.mark.parametrize(
    "args,fragment",
    [
        (["--bogus"], "Unknown option: --bogus"),
        (["--version"], "--version needs a value"),
        (["--version="], "--version cannot be empty"),
        (["--repo", "file:///tmp/apiome"], "--repo must be an https:// or ssh:// URL"),
        (["--repo", "git@github.com:apiome/apiome.git"], "--repo must be an https:// or ssh:// URL"),
    ],
    ids=["unknown-flag", "version-without-value", "empty-version", "file-repo", "scp-style-repo"],
)
def test_bad_arguments_fail_before_anything_is_installed(args, fragment) -> None:
    result = _piped(*args)
    assert result.returncode == 1
    assert fragment in result.stderr


def test_it_installs_with_the_lockfile_as_constraints() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "export --frozen --no-dev" in text
    assert "--constraints" in text
    assert "tool install --force" in text
