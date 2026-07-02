"""Root help, -h/--help, and clig.dev exit codes for apiome-cli."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli import __version__
from apiome_cli.help_util import CONCISE_HELP_EPILOG, build_command_directory
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

ROOT = Path(__file__).resolve().parents[1]
CONSOLE_SCRIPT = ROOT / ".venv" / "bin" / "apiome"
runner = CliRunner()


def test_help_command_prints_concise_help_and_exits_zero() -> None:
    """``apiome help`` shows the same concise usage as a bare invocation."""
    result = runner.invoke(app, ["help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "apiome — Command-line client" in result.stdout
    assert CONCISE_HELP_EPILOG in result.stdout


def test_help_command_subcommand_exits_zero() -> None:
    """``apiome help health`` shows subcommand help."""
    result = runner.invoke(app, ["help", "health"])
    assert result.exit_code == EXIT_SUCCESS
    assert "GET /health" in result.stdout or "health" in result.stdout.lower()


def test_bare_apiome_prints_concise_help_and_exits_zero() -> None:
    """No args shows short help with examples and exits 0 (not usage error)."""
    result = runner.invoke(app, [])
    assert result.exit_code == EXIT_SUCCESS
    assert "apiome — Command-line client" in result.stdout
    assert CONCISE_HELP_EPILOG in result.stdout
    assert "Examples:" in result.stdout
    assert "Commands:" in result.stdout
    catalog = build_command_directory()
    assert catalog in result.stdout
    assert "import" in result.stdout
    assert "arazzo" in result.stdout
    assert "paths" in result.stdout
    assert "spec" in result.stdout
    assert "json-schema" in result.stdout
    assert "json-schema-type" in result.stdout
    assert "    show" in result.stdout
    assert "    list" in result.stdout
    assert "    openapi" in result.stdout
    assert "    arazzo" in result.stdout
    assert "    json-schema" in result.stdout
    assert "    json-schema-type" in result.stdout


def test_command_directory_lists_all_top_level_groups() -> None:
    """The command catalog includes every Typer group registered on the root app."""
    catalog = build_command_directory()
    for name in (
        "auth",
        "config",
        "doctor",
        "health",
        "help",
        "import",
        "operations",
        "paths",
        "projects",
        "properties",
        "repos",
        "schemas",
        "types",
        "versions",
        "spec",
    ):
        assert name in catalog


def test_root_help_long_option_exits_zero() -> None:
    """--help on root prints full Typer help and exits 0."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Command-line client for the Apiome REST API" in result.stdout
    help_text = strip_ansi(result.stdout)
    assert "doctor" in help_text
    assert "health" in help_text
    assert "projects" in help_text
    assert "import" in help_text
    assert "help" in help_text
    assert "-json" in help_text
    assert "machine-readable" in help_text
    assert "Commands:" in help_text
    assert "    json-schema" in help_text


def test_root_help_short_option_exits_zero() -> None:
    """-h on root is equivalent to --help (clig.dev)."""
    result = runner.invoke(app, ["-h"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Command-line client for the Apiome REST API" in result.stdout


def test_version_exits_zero() -> None:
    """--version and -V exit 0."""
    for args in (["--version"], ["-V"]):
        result = runner.invoke(app, args)
        assert result.exit_code == EXIT_SUCCESS
        assert result.stdout.strip() == f"apiome {__version__}"


def test_unknown_option_exits_usage() -> None:
    """Invalid flags exit 2 (usage) per Typer/Click convention."""
    result = runner.invoke(app, ["--not-a-real-flag"])
    assert result.exit_code == EXIT_USAGE


def test_health_subcommand_help_exits_zero() -> None:
    """--help works on subcommands."""
    for args in (["health", "--help"], ["health", "-h"]):
        result = runner.invoke(app, args)
        assert result.exit_code == EXIT_SUCCESS
        assert "GET /health" in result.stdout or "health" in result.stdout.lower()


_COMMAND_GROUPS: tuple[tuple[str, str], ...] = (
    ("config", "Show or change saved defaults"),
    ("repos", "List tenant Git repositories and inspect repository files"),
    ("projects", "List and fetch tenant projects"),
    ("properties", "List and fetch tenant properties"),
    ("schemas", "List and fetch tenant schemas"),
    ("types", "Browse tenant JSON Schema primitive types"),
    ("versions", "List and fetch project versions"),
    ("paths", "List and inspect OpenAPI path templates"),
    ("operations", "Inspect OpenAPI operations"),
    ("spec", "Export reconstructed OpenAPI/Arazzo specs"),
    (
        "import",
        "Import OpenAPI, Swagger, Arazzo, JSON Schema, and JSON Schema type documents",
    ),
)


@pytest.mark.parametrize(("group", "summary"), _COMMAND_GROUPS)
def test_command_group_without_subcommand_shows_help(group: str, summary: str) -> None:
    """Multi-command groups print help and exit 0 when no subcommand is given."""
    result = runner.invoke(app, [group])
    assert result.exit_code == EXIT_SUCCESS
    help_text = strip_ansi(result.stdout)
    assert "Usage:" in help_text
    assert summary in help_text


_ALL_COMMAND_PATHS: tuple[list[str], ...] = (
    ["help"],
    ["config"],
    ["config", "show"],
    ["config", "set"],
    ["config", "unset"],
    ["doctor"],
    ["health"],
    ["repos"],
    ["repos", "list"],
    ["repos", "add"],
    ["repos", "scan"],
    ["repos", "files"],
    ["repos", "inspect"],
    ["repos", "import"],
    ["repos", "imports"],
    ["projects"],
    ["projects", "list"],
    ["projects", "get"],
    ["properties"],
    ["properties", "list"],
    ["properties", "get"],
    ["schemas"],
    ["schemas", "list"],
    ["schemas", "get"],
    ["types"],
    ["types", "list"],
    ["types", "show"],
    ["types", "search"],
    ["types", "publish"],
    ["types", "unpublish"],
    ["versions"],
    ["versions", "list"],
    ["versions", "get"],
    ["versions", "publish"],
    ["versions", "unpublish"],
    ["import"],
    ["import", "auto"],
    ["import", "openapi"],
    ["import", "swagger"],
    ["import", "arazzo"],
    ["import", "json-schema"],
    ["import", "json-schema-type"],
    ["paths"],
    ["paths", "list"],
    ["paths", "show"],
    ["operations"],
    ["operations", "show"],
    ["spec"],
    ["spec", "export"],
    ["spec", "download-original"],
)


@pytest.mark.parametrize("command_path", _ALL_COMMAND_PATHS)
@pytest.mark.parametrize("help_flag", ("--help", "-h"))
def test_all_commands_support_help_flags(command_path: list[str], help_flag: str) -> None:
    """Every command and group accepts -h and --help (clig.dev)."""
    result = runner.invoke(app, [*command_path, help_flag])
    assert result.exit_code == EXIT_SUCCESS
    assert "Usage:" in strip_ansi(result.stdout)


def test_health_success_exits_zero(httpx_mock: object) -> None:
    """Successful API response exits 0."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        json={"status": "ok", "database": "connected"},
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_SUCCESS
    assert '"status": "ok"' in result.stdout


def test_health_json_mode_outputs_compact_json(httpx_mock: object) -> None:
    """Global --json makes health emit compact machine-readable JSON."""
    payload = {"status": "ok", "database": "connected"}
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        json=payload,
    )
    result = runner.invoke(app, ["--json", "health"])
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout.strip() == '{"status":"ok","database":"connected"}'


def test_health_api_failure_exits_error(httpx_mock: object) -> None:
    """503 exits 1, shows service-unavailable message and hint on stderr."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        status_code=503,
        json={
            "code": 503,
            "message": "Service Unavailable",
            "details": {"status": "error"},
        },
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_ERROR
    assert "Service Unavailable" in result.stderr
    assert "temporarily unavailable" in result.stderr
    assert "Traceback" not in result.stderr + result.stdout


def test_root_verbose_option_in_help() -> None:
    """Global --verbose is documented on root help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == EXIT_SUCCESS
    help_text = strip_ansi(result.stdout)
    assert "--verbose" in help_text
    assert "-v" in help_text


def test_root_help_documents_global_config_flags() -> None:
    """Global config flags appear on root help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == EXIT_SUCCESS
    help_text = strip_ansi(result.stdout)
    assert "--base-url" in help_text
    assert "--tenant" in help_text
    assert "--api-key" in help_text
    assert "--session-token" in help_text
    assert "--env-file" in help_text
    assert "APIOME_BASE_URL" in help_text
    assert "APIOME_TENANT_ID" in help_text
    assert "APIOME_API_KEY" in help_text
    assert "APIOME_SESSION_TOKEN" in help_text


def test_subcommand_help_omits_global_config_flags() -> None:
    """Subcommand help does not repeat root configuration flags."""
    result = runner.invoke(app, ["health", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    help_text = strip_ansi(result.stdout)
    assert "--base-url" not in help_text
    assert "--tenant" not in help_text
    assert "--api-key" not in help_text


def test_global_base_url_overrides_env(httpx_mock: object) -> None:
    """Root --base-url wins over APIOME_BASE_URL."""
    httpx_mock.add_response(url="http://custom:9000/health", json={"status": "ok"})
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"APIOME_BASE_URL", "APIOME_API_KEY"}
    }
    env["APIOME_BASE_URL"] = "http://from-env:8000"
    result = runner.invoke(
        app,
        ["--base-url", "http://custom:9000", "health"],
        env=env,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert httpx_mock.get_requests()[0].url == "http://custom:9000/health"


def test_global_api_key_overrides_env(httpx_mock: object) -> None:
    """Root --api-key wins over APIOME_API_KEY."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp",
        json={"total": 0, "offset": 0, "limit": 50, "items": []},
    )
    env = {
        "APIOME_API_KEY": "env_key",
        "APIOME_BASE_URL": "http://localhost:8000",
        "APIOME_TENANT_ID": "acme-corp",
    }
    result = runner.invoke(
        app,
        ["--api-key", "cli_key", "projects", "list"],
        env=env,
    )
    assert result.exit_code == EXIT_SUCCESS
    assert httpx_mock.get_requests()[0].headers["X-API-Key"] == "cli_key"


def test_bare_apiome_via_installed_script() -> None:
    """Installed console script: bare invocation exits 0 with concise help."""
    if not CONSOLE_SCRIPT.is_file():
        pytest.skip("run yarn cli:build to install .venv/bin/apiome")
    proc = subprocess.run(
        [str(CONSOLE_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_SUCCESS
    assert CONCISE_HELP_EPILOG in proc.stdout


def test_root_h_via_installed_script() -> None:
    """Installed console script accepts -h on root."""
    if not CONSOLE_SCRIPT.is_file():
        pytest.skip("run yarn cli:build to install .venv/bin/apiome")
    proc = subprocess.run(
        [str(CONSOLE_SCRIPT), "-h"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == EXIT_SUCCESS
    assert "health" in proc.stdout
