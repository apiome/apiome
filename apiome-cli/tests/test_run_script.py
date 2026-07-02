"""Tests for the run.sh launcher."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from apiome_cli import __version__

ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "run.sh"


def test_run_sh_forwards_arguments_to_cli() -> None:
    """run.sh passes argv through to the installed apiome executable."""
    env = {**os.environ, "APIOME_LOAD_DOTENV": "0"}
    result = subprocess.run(
        [str(RUN_SH), "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert result.stdout.strip() == f"apiome {__version__}"
    assert result.stderr == ""
