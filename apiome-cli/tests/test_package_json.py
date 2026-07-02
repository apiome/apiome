"""Verify package.json exposes turborepo scripts for build, test, and lint."""

import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_JSON = PACKAGE_ROOT / "package.json"

REQUIRED_SCRIPTS = {
    "install:py": "uv venv",
    "build": "install:py",
    "cli:build": "apiome-cli build complete",
    "test": "pytest tests/",
    "cli:test": "pytest tests/",
    "lint": "ruff check src/ tests/",
    "cli:lint": "ruff check src/ tests/",
    "run": "bash run.sh",
}


def test_package_name() -> None:
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert data["name"] == "@apiome/cli"


def test_turborepo_scripts() -> None:
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    for name, fragment in REQUIRED_SCRIPTS.items():
        assert name in scripts, f"missing script {name!r}"
        assert fragment in scripts[name], (
            f"script {name!r} should include {fragment!r}, got {scripts[name]!r}"
        )
