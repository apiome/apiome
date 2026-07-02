"""Tests for ``apiome import json-schema`` (not supported via /v1 REST yet).

The command no longer performs an import: it makes no HTTP request, does not
parse the document, and ignores every flag and the path argument. It simply
writes a not-supported message to stderr and exits ``EXIT_USAGE`` (2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_NOT_SUPPORTED = "This import command is not supported via the /v1 REST API yet."

_VALID_PROPERTY = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "string",
    "title": "Email",
    "format": "email",
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")


def _write_schema(path: Path, document: dict | None = None) -> None:
    path.write_text(json.dumps(document or _VALID_PROPERTY), encoding="utf-8")


def _assert_not_supported(result: object) -> None:
    """Assert the command emitted the not-supported error and made no import."""
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert _NOT_SUPPORTED in result.stderr


def test_import_json_schema_from_file_not_supported(tmp_path: Path) -> None:
    """A file path argument yields the not-supported error with empty stdout."""
    schema_path = tmp_path / "email.json"
    _write_schema(schema_path)

    result = runner.invoke(app, ["import", "json-schema", str(schema_path)])

    _assert_not_supported(result)


def test_import_json_schema_from_url_not_supported() -> None:
    """An HTTP(S) URL source yields the not-supported error (no fetch happens)."""
    result = runner.invoke(
        app,
        ["import", "json-schema", "https://example.com/email.json"],
    )

    _assert_not_supported(result)


def test_import_json_schema_from_stdin_not_supported() -> None:
    """The ``-`` stdin source yields the not-supported error (no parse happens)."""
    result = runner.invoke(
        app,
        ["import", "json-schema", "-"],
        input=json.dumps(_VALID_PROPERTY),
    )

    _assert_not_supported(result)


def test_import_json_schema_as_schema_not_supported(tmp_path: Path) -> None:
    """``--as schema`` is ignored; the command still reports not supported."""
    schema_path = tmp_path / "user.json"
    _write_schema(
        schema_path,
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "title": "User",
            "properties": {"email": {"type": "string"}},
        },
    )

    result = runner.invoke(
        app,
        ["import", "json-schema", "--as", "schema", str(schema_path)],
    )

    _assert_not_supported(result)


def test_import_json_schema_dry_run_not_supported(tmp_path: Path) -> None:
    """``--dry-run`` is ignored; the command still reports not supported."""
    schema_path = tmp_path / "email.json"
    _write_schema(schema_path)

    result = runner.invoke(
        app,
        ["import", "json-schema", "--dry-run", str(schema_path)],
    )

    _assert_not_supported(result)


def test_import_json_schema_project_link_flags_not_supported(tmp_path: Path) -> None:
    """Project/link flags are ignored; the command still reports not supported."""
    schema_path = tmp_path / "email.json"
    _write_schema(schema_path)
    project_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    result = runner.invoke(
        app,
        [
            "import",
            "json-schema",
            "--name",
            "contact_email",
            "--description",
            "Primary contact email",
            "--as",
            "property",
            "--project-id",
            project_id,
            "--link-project-property",
            str(schema_path),
        ],
    )

    _assert_not_supported(result)


def test_import_json_schema_help_lists_flags() -> None:
    """Subcommand documents PATH and import-specific options."""
    result = runner.invoke(app, ["import", "json-schema", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "PATH" in help_text
    assert "--as" in help_text
    assert "--name" in help_text
    assert "--project-id" in help_text
    assert "--version-id" in help_text
    assert "--link-project-pro" in help_text
    assert "--dry-run" in help_text
    assert "--no-wait" not in help_text
    assert "--poll-interval" not in help_text


def test_import_openapi_suggests_json_schema_command(tmp_path: Path) -> None:
    """OpenAPI command points users at ``import json-schema`` for schema files."""
    schema_path = tmp_path / "schema.json"
    _write_schema(schema_path)

    result = runner.invoke(app, ["import", "openapi", str(schema_path)])

    assert result.exit_code == EXIT_USAGE
    assert "import json-schema" in result.stderr
    assert "not available yet" not in result.stderr
