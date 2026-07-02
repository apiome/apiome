"""Dependency lockfile and importability tests for apiome-cli."""

from importlib import import_module
from pathlib import Path

import pytest


def test_uv_lock_exists() -> None:
    """Reproducible installs require a committed uv.lock."""
    root = Path(__file__).resolve().parents[1]
    assert (root / "uv.lock").is_file()


@pytest.mark.parametrize(
    "module_name",
    [
        "typer",
        "httpx",
        "pydantic_settings",
        "yaml",
        "jsonschema",
        "openapi_spec_validator",
    ],
)
def test_runtime_dependencies_importable(module_name: str) -> None:
    """Runtime dependencies declared in pyproject.toml are installed."""
    import_module(module_name)


def test_pytest_httpx_plugin_available() -> None:
    """Dev dependency pytest-httpx is installed for mocked HTTP tests."""
    import_module("pytest_httpx")


def test_ruff_available() -> None:
    """Dev dependency ruff is installed for linting."""
    import_module("ruff")
