"""Scaffold tests for the apiome-cli package."""

from pathlib import Path

import pytest
import typer

from apiome_cli import __version__
from apiome_cli.config import CliSettings
from apiome_cli.main import app


def test_version_is_semver_string() -> None:
    """Package version is a non-empty dotted string."""
    parts = __version__.split(".")
    assert len(parts) >= 2
    assert all(part.isdigit() for part in parts)


def test_app_is_typer_instance() -> None:
    """Root command is a Typer application."""
    assert isinstance(app, typer.Typer)


def test_cli_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings model exposes expected default base URL."""
    monkeypatch.delenv("APIOME_BASE_URL", raising=False)
    monkeypatch.delenv("APIOME_TENANT_ID", raising=False)
    monkeypatch.delenv("APIOME_API_KEY", raising=False)
    settings = CliSettings(_env_file=None)
    assert settings.base_url_str == "http://localhost:8000"
    assert settings.tenant_id is None
    assert settings.api_key is None


def test_expected_scaffold_paths_exist() -> None:
    """Package layout matches the issue scaffold."""
    root = Path(__file__).resolve().parents[1]
    expected = [
        ".gitignore",
        "AGENTS.md",
        "package.json",
        "pyproject.toml",
        "README.md",
        "src/apiome_cli/__init__.py",
        "src/apiome_cli/main.py",
        "src/apiome_cli/config.py",
        "src/apiome_cli/client/__init__.py",
        "src/apiome_cli/commands/__init__.py",
        "src/apiome_cli/import_/__init__.py",
        "src/apiome_cli/import_/openapi.py",
        "src/apiome_cli/import_/detect.py",
        "src/apiome_cli/import_/json_schema.py",
        "src/apiome_cli/extract/__init__.py",
        "src/apiome_cli/extract/openapi_info.py",
        "src/apiome_cli/commands/repos.py",
        "src/apiome_cli/client/repos_add.py",
        "src/apiome_cli/client/repos_files.py",
        "src/apiome_cli/client/repos_scan.py",
        "src/apiome_cli/client/repos_inspect.py",
        "src/apiome_cli/client/repos_closure.py",
        "src/apiome_cli/client/repos_import.py",
        "src/apiome_cli/client/repos_verify.py",
    ]
    for relative in expected:
        assert (root / relative).is_file(), f"expected {relative} to exist"


def test_repos_command_test_modules_exist() -> None:
    """Repository Store CLI commands have per-command pytest coverage modules."""
    root = Path(__file__).resolve().parents[1]
    expected = [
        "tests/test_repos_commands.py",
        "tests/test_repos_add_helpers.py",
        "tests/test_repos_files_helpers.py",
        "tests/test_repos_scan_helpers.py",
        "tests/test_repos_inspect_helpers.py",
        "tests/test_repos_closure_helpers.py",
        "tests/test_repos_import_helpers.py",
        "tests/test_repos_verify_helpers.py",
    ]
    for relative in expected:
        assert (root / relative).is_file(), f"expected {relative} to exist"
