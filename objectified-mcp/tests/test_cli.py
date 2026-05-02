from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_module_help_prints_usage() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "objectified_mcp", "--help"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_ROOT,
        env={**os.environ, "PYTHONPATH": str(_ROOT / "src")},
    )
    assert "objectified-mcp" in result.stdout
    assert result.stderr == ""


def test_package_version_matches_pyproject() -> None:
    from objectified_mcp import __version__

    assert __version__ == "0.1.0"


def test_server_module_exposes_mcp() -> None:
    from objectified_mcp.server import mcp

    assert mcp.name == "Objectified"
