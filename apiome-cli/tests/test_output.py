"""Tests for human/JSON output formatters."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.main import app
from apiome_cli.output import (
    emit_json,
    emit_list_response,
    emit_list_table,
    emit_record_response,
)

from helpers import strip_ansi

runner = CliRunner()

_LIST_COLUMNS = (("Name", "name", None),)
_RECORD_FIELDS = (("Name", "name", None),)

_SAMPLE_LIST = {
    "total": 2,
    "offset": 0,
    "limit": 50,
    "items": [
        {"id": "a", "name": "Alpha"},
        {"id": "b", "name": "Beta"},
    ],
}

_SAMPLE_RECORD = {"id": "a", "name": "Alpha", "enabled": True}


def test_emit_json_writes_compact_raw_payload(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON mode prints compact serialized API data."""
    emit_json(_SAMPLE_LIST)
    out = capsys.readouterr().out.strip()
    assert out == json.dumps(_SAMPLE_LIST, separators=(",", ":"))


def test_emit_list_response_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """List formatter delegates to raw JSON when json_mode is set."""
    emit_list_response(_SAMPLE_LIST, _LIST_COLUMNS, json_mode=True)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == _SAMPLE_LIST


def test_emit_list_response_human_mode_shows_table(capsys: pytest.CaptureFixture[str]) -> None:
    """Default list output renders a readable table with totals."""
    emit_list_response(_SAMPLE_LIST, _LIST_COLUMNS, json_mode=False)
    out = capsys.readouterr().out
    assert "Name" in out
    assert "Alpha" in out
    assert "Beta" in out
    assert "Showing 2 of 2" in out


def test_emit_list_response_empty_items(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty lists print a short message and total."""
    payload = {"total": 0, "offset": 0, "limit": 50, "items": []}
    emit_list_response(payload, _LIST_COLUMNS, json_mode=False)
    out = capsys.readouterr().out
    assert "No items." in out
    assert "Total: 0" in out


def test_emit_record_response_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Get formatter emits raw JSON for a single resource."""
    emit_record_response(_SAMPLE_RECORD, _RECORD_FIELDS, json_mode=True)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == _SAMPLE_RECORD


def test_emit_record_response_human_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Get formatter renders field/value rows for humans."""
    emit_record_response(_SAMPLE_RECORD, _RECORD_FIELDS, json_mode=False)
    out = capsys.readouterr().out
    assert "Field" in out
    assert "Alpha" in out


def test_root_help_documents_json_flag() -> None:
    """--json appears on root help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    help_text = strip_ansi(result.stdout)
    assert "-json" in help_text
    assert "machine-readable" in help_text


def test_emit_list_table_applies_column_formatter(capsys: pytest.CaptureFixture[str]) -> None:
    """Column formatters transform cell values before rendering."""
    columns = (("Enabled", "enabled", lambda value: "yes" if value else "no"),)
    emit_list_table([{"enabled": True}, {"enabled": False}], columns)
    out = capsys.readouterr().out
    assert "yes" in out
    assert "no" in out


def test_emit_list_table_none_cell_renders_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """Missing or null field values render as empty cells."""
    emit_list_table([{"name": None}], _LIST_COLUMNS)
    out = capsys.readouterr().out
    assert "Name" in out
    assert "None" not in out


def test_emit_list_table_custom_empty_message(capsys: pytest.CaptureFixture[str]) -> None:
    """emit_list_table accepts a custom message when items is empty."""
    emit_list_table([], _LIST_COLUMNS, empty_message="Nothing here.")
    out = capsys.readouterr().out
    assert "Nothing here." in out


def test_emit_list_response_non_list_items_emits_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed list payloads fall back to raw JSON output."""
    payload = {"total": 1, "items": "not-a-list"}
    emit_list_response(payload, _LIST_COLUMNS, json_mode=False)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == payload
