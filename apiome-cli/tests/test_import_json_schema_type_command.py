"""Tests for ``apiome import json-schema-type``.

The type-import command is not yet wired to the ``/v1`` REST API. Every
invocation (regardless of source, flags, or document contents) prints a fixed
"not supported" message to stderr and exits ``EXIT_USAGE``. These tests pin
that behavior across the supported input sources and flag combinations so the
command keeps failing loudly until the REST endpoint exists.
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

_TYPE_LIBRARY = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.com/schemas/common-types.json",
    "$defs": {
        "Email": {
            "type": "string",
            "title": "Email",
            "format": "email",
        },
        "Timestamp": {
            "type": "string",
            "title": "Timestamp",
            "format": "date-time",
        },
    },
}

_SINGLE_TYPE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "string",
    "title": "Email",
    "format": "email",
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Type import requires an API key but not tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")


def _write_document(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _assert_not_supported(result: object) -> None:
    """The command exits ``EXIT_USAGE`` with the not-supported message only."""
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert strip_ansi(result.stderr).strip() == _NOT_SUPPORTED


def test_import_json_schema_type_from_file(tmp_path: Path) -> None:
    """A local file path reports the import is not supported yet."""
    schema_path = tmp_path / "common-types.json"
    _write_document(schema_path, _TYPE_LIBRARY)

    result = runner.invoke(app, ["import", "json-schema-type", str(schema_path)])

    _assert_not_supported(result)


def test_import_json_schema_type_from_url() -> None:
    """An HTTP(S) URL source reports the import is not supported yet."""
    schema_url = "https://example.com/common-types.json"

    result = runner.invoke(app, ["import", "json-schema-type", schema_url])

    _assert_not_supported(result)


def test_import_json_schema_type_from_stdin() -> None:
    """A ``-`` (stdin) source reports the import is not supported yet."""
    result = runner.invoke(
        app,
        ["import", "json-schema-type", "-"],
        input=json.dumps(_TYPE_LIBRARY),
    )

    _assert_not_supported(result)


def test_import_json_schema_type_json_output(tmp_path: Path) -> None:
    """``--json`` still reports the import is not supported yet."""
    schema_path = tmp_path / "common-types.json"
    _write_document(schema_path, _TYPE_LIBRARY)

    result = runner.invoke(
        app,
        ["--json", "import", "json-schema-type", str(schema_path)],
    )

    _assert_not_supported(result)


def test_import_json_schema_type_dry_run(tmp_path: Path) -> None:
    """``--dry-run`` still reports the import is not supported yet."""
    schema_path = tmp_path / "common-types.json"
    _write_document(schema_path, _TYPE_LIBRARY)

    result = runner.invoke(
        app,
        ["import", "json-schema-type", "--dry-run", str(schema_path)],
    )

    _assert_not_supported(result)


def test_import_json_schema_type_name_override(tmp_path: Path) -> None:
    """``--name`` still reports the import is not supported yet."""
    schema_path = tmp_path / "email.json"
    _write_document(schema_path, _SINGLE_TYPE)

    result = runner.invoke(
        app,
        ["import", "json-schema-type", "--name", "contact_email", str(schema_path)],
    )

    _assert_not_supported(result)


def test_import_json_schema_type_description_override(tmp_path: Path) -> None:
    """``--description`` still reports the import is not supported yet."""
    schema_path = tmp_path / "email.json"
    _write_document(schema_path, _SINGLE_TYPE)

    result = runner.invoke(
        app,
        [
            "import",
            "json-schema-type",
            "--description",
            "Primary contact email",
            str(schema_path),
        ],
    )

    _assert_not_supported(result)


def test_import_json_schema_type_publish_public(tmp_path: Path) -> None:
    """``--publish public`` still reports the import is not supported yet."""
    schema_path = tmp_path / "common-types.json"
    _write_document(schema_path, _TYPE_LIBRARY)

    result = runner.invoke(
        app,
        ["import", "json-schema-type", "--publish", "public", str(schema_path)],
    )

    _assert_not_supported(result)


def test_import_json_schema_type_publish_private(tmp_path: Path) -> None:
    """``--publish private`` still reports the import is not supported yet."""
    schema_path = tmp_path / "common-types.json"
    _write_document(schema_path, _TYPE_LIBRARY)

    result = runner.invoke(
        app,
        ["import", "json-schema-type", "--publish", "private", str(schema_path)],
    )

    _assert_not_supported(result)


def test_import_json_schema_type_help_lists_flags() -> None:
    """Subcommand documents PATH and type-import options."""
    result = runner.invoke(app, ["import", "json-schema-type", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "PATH" in help_text
    assert "--name" in help_text
    assert "--description" in help_text
    assert "--dry-run" in help_text
    assert "--publish" in help_text
    assert "--visibility" in help_text
