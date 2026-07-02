"""Console script registration and --version behaviour."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from typer.testing import CliRunner

from apiome_cli import __version__
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app, run

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SCRIPT = ROOT / ".venv" / "bin" / "apiome"


def test_console_script_installed_in_venv() -> None:
    """uv sync installs the apiome console script into .venv/bin."""
    assert CONSOLE_SCRIPT.is_file(), (
        "expected .venv/bin/apiome after uv sync; run install:py first"
    )


def test_apiome_version_via_installed_script() -> None:
    """Installed console script prints package version for --version."""
    result = subprocess.run(
        [str(CONSOLE_SCRIPT), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"apiome {__version__}"
    assert result.stderr == ""


def test_apiome_version_short_flag() -> None:
    """Installed console script accepts -V as a version alias."""
    result = subprocess.run(
        [str(CONSOLE_SCRIPT), "-V"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"apiome {__version__}"


def test_version_option_via_cli_runner() -> None:
    """Typer app exposes --version on the root callback."""
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"apiome {__version__}"


# ---------------------------------------------------------------------------
# run() entrypoint – exit code forwarding for failure paths
# ---------------------------------------------------------------------------


def test_run_api_failure_exits_error(httpx_mock: object) -> None:
    """run() raises SystemExit(EXIT_ERROR) when the API returns a failure status.

    With standalone_mode=False, Click swallows typer.Exit internally and returns
    the exit code as an integer.  This test validates that run() forwards that
    value to the OS rather than silently exiting 0.
    """
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url="http://localhost:8000/health",
        status_code=503,
        json={"code": 503, "message": "Service Unavailable"},
    )
    with patch.object(sys, "argv", ["apiome", "health"]):
        with pytest.raises(SystemExit) as exc_info:
            run()
    assert exc_info.value.code == EXIT_ERROR


def test_run_connection_error_exits_error(httpx_mock: object) -> None:
    """run() raises SystemExit(EXIT_ERROR) for transport-layer failures.

    Connection errors are caught by RestClient and converted to typer.Exit(1).
    With standalone_mode=False that integer is the return value of app(); this
    test confirms run() propagates it to sys.exit.
    """
    httpx_mock.add_exception(  # type: ignore[attr-defined]
        httpx.ConnectError("connection refused")
    )
    with patch.object(sys, "argv", ["apiome", "health"]):
        with pytest.raises(SystemExit) as exc_info:
            run()
    assert exc_info.value.code == EXIT_ERROR


def test_run_version_exits_success() -> None:
    """run() raises SystemExit(EXIT_SUCCESS) for --version (sanity check)."""
    with patch.object(sys, "argv", ["apiome", "--version"]):
        with pytest.raises(SystemExit) as exc_info:
            run()
    assert exc_info.value.code == EXIT_SUCCESS
