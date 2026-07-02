"""Tests for ``apiome import arazzo``.

The Arazzo importer is currently not wired to the ``/v1`` REST API. The command
ignores its path argument and all flags, writes a not-supported message to
stderr, and exits with ``EXIT_USAGE`` (2). These tests assert that real
behavior across the document sources (file, URL, stdin) and representative
flag combinations.
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

_VALID_ARAZZO = {
    "arazzo": "1.0.0",
    "info": {"title": "Checkout Flow", "version": "1.0.0", "summary": "Demo"},
    "sourceDescriptions": [
        {
            "name": "openapi",
            "url": "https://example.test/openapi.json",
            "type": "openapi",
        }
    ],
    "workflows": [
        {
            "workflowId": "checkout",
            "steps": [
                {"stepId": "createCart", "operationId": "createCart"},
            ],
        }
    ],
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")


def _write_spec(path: Path) -> None:
    path.write_text(json.dumps(_VALID_ARAZZO), encoding="utf-8")


def _assert_not_supported(result: object) -> None:
    """The command exits EXIT_USAGE with the not-supported message on stderr."""
    assert result.exit_code == EXIT_USAGE
    assert result.stdout == ""
    assert _NOT_SUPPORTED in result.stderr


def test_import_arazzo_from_file_not_supported(tmp_path: Path) -> None:
    """A valid Arazzo file still exits with the not-supported message."""
    spec_path = tmp_path / "checkout.json"
    _write_spec(spec_path)

    result = runner.invoke(app, ["import", "arazzo", str(spec_path)])

    _assert_not_supported(result)


def test_import_arazzo_from_url_not_supported() -> None:
    """An HTTP(S) URL source exits with the not-supported message."""
    result = runner.invoke(
        app,
        ["import", "arazzo", "https://example.com/checkout.json"],
    )

    _assert_not_supported(result)


def test_import_arazzo_from_stdin_not_supported() -> None:
    """A ``-`` stdin source exits with the not-supported message."""
    result = runner.invoke(
        app,
        ["import", "arazzo", "-"],
        input=json.dumps(_VALID_ARAZZO),
    )

    _assert_not_supported(result)


def test_import_arazzo_json_output_not_supported(tmp_path: Path) -> None:
    """``--json`` does not change the not-supported behavior."""
    spec_path = tmp_path / "checkout.json"
    _write_spec(spec_path)

    result = runner.invoke(app, ["--json", "import", "arazzo", str(spec_path)])

    _assert_not_supported(result)


def test_import_arazzo_dry_run_not_supported(tmp_path: Path) -> None:
    """``--dry-run`` is ignored; the command still reports not-supported."""
    spec_path = tmp_path / "checkout.json"
    _write_spec(spec_path)

    result = runner.invoke(app, ["import", "arazzo", "--dry-run", str(spec_path)])

    _assert_not_supported(result)


def test_import_arazzo_no_wait_not_supported(tmp_path: Path) -> None:
    """``--no-wait`` is ignored; the command still reports not-supported."""
    spec_path = tmp_path / "checkout.json"
    _write_spec(spec_path)

    result = runner.invoke(app, ["import", "arazzo", "--no-wait", str(spec_path)])

    _assert_not_supported(result)


def test_import_arazzo_poll_interval_not_supported(tmp_path: Path) -> None:
    """``--poll-interval`` is ignored; the command still reports not-supported."""
    spec_path = tmp_path / "checkout.json"
    _write_spec(spec_path)

    result = runner.invoke(
        app,
        ["import", "arazzo", "--poll-interval", "2.5", str(spec_path)],
    )

    _assert_not_supported(result)


def test_import_arazzo_override_flags_not_supported(tmp_path: Path) -> None:
    """Targeting/override flags are ignored; not-supported is reported."""
    spec_path = tmp_path / "checkout.json"
    _write_spec(spec_path)

    result = runner.invoke(
        app,
        [
            "import",
            "arazzo",
            "--project-name",
            "Custom Name",
            "--version",
            "9.0.0",
            "--project-slug",
            "custom-slug",
            "--version-slug",
            "9.0.0",
            "--project-id",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "--version-id",
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            str(spec_path),
        ],
    )

    _assert_not_supported(result)


def test_import_arazzo_invalid_spec_not_supported(tmp_path: Path) -> None:
    """The command no longer parses the document; it reports not-supported.

    Even a structurally invalid Arazzo document exits with the not-supported
    message because the document is never read.
    """
    spec_path = tmp_path / "bad.json"
    spec_path.write_text('{"arazzo": "1.0.0", "workflows": []}', encoding="utf-8")

    result = runner.invoke(app, ["import", "arazzo", str(spec_path)])

    _assert_not_supported(result)


def test_import_arazzo_openapi_file_not_supported(tmp_path: Path) -> None:
    """The document is never inspected, so no ``import openapi`` suggestion.

    An OpenAPI document passed to ``import arazzo`` still yields the
    not-supported message rather than a format-detection suggestion.
    """
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "API", "version": "1.0.0"},
                "paths": {},
            },
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["import", "arazzo", str(spec_path)])

    _assert_not_supported(result)
    assert "import openapi" not in result.stderr


def test_import_arazzo_json_schema_file_not_supported(tmp_path: Path) -> None:
    """The document is never inspected, so no ``import json-schema`` suggestion."""
    spec_path = tmp_path / "schema.json"
    spec_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            },
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["import", "arazzo", str(spec_path)])

    _assert_not_supported(result)
    assert "import json-schema" not in result.stderr


def test_import_arazzo_help_lists_flags() -> None:
    """``--help`` still works and documents PATH and import-specific options."""
    result = runner.invoke(app, ["import", "arazzo", "--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "PATH" in help_text
    assert "--dry-run" in help_text
    assert "--project-id" in help_text
    assert "--version-id" in help_text
    assert "--wait" in help_text
    assert "--poll-interval" in help_text


def test_import_openapi_suggests_arazzo_command(tmp_path: Path) -> None:
    """``import openapi`` (still working) suggests ``import arazzo`` for an Arazzo file."""
    spec_path = tmp_path / "workflow.json"
    _write_spec(spec_path)

    result = runner.invoke(app, ["import", "openapi", str(spec_path)])

    assert result.exit_code == EXIT_USAGE
    assert "import arazzo" in result.stderr
