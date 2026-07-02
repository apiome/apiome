"""Unit tests for platform type list/detail output formatters."""

from __future__ import annotations

import json

import pytest

from apiome_cli.output import emit_type_detail, emit_types_list_response

from helpers import strip_ansi


_LIST_PAYLOAD = {
    "total": 42,
    "page": 1,
    "limit": 20,
    "items": [
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "name": "Email",
            "slug": "email",
            "description": "A valid RFC 5321 email address",
            "ref_path": "#/Email",
            "source_uri": None,
            "created_on": "2025-01-15T10:00:00Z",
        },
    ],
}

_DETAIL_PAYLOAD = {
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "creator_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "name": "Email",
    "slug": "email",
    "description": "A valid RFC 5321 email address",
    "body": {"type": "string", "format": "email"},
    "ref_path": "#/Email",
    "source_uri": None,
    "enabled": True,
    "created_on": "2025-01-15T10:00:00Z",
    "updated_on": None,
}


def test_emit_types_list_response_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON mode emits only the items array."""
    emit_types_list_response(_LIST_PAYLOAD, json_mode=True)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == _LIST_PAYLOAD["items"]


def test_emit_types_list_response_human_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Human mode renders the paginated platform types table."""
    emit_types_list_response(_LIST_PAYLOAD, json_mode=False)
    out = strip_ansi(capsys.readouterr().out)
    assert "Platform Types (page 1 of 3, 42 total)" in out
    assert "Email" in out
    assert "email" in out
    assert "A valid RFC 5321 email address" in out


def test_emit_types_list_response_search_header(capsys: pytest.CaptureFixture[str]) -> None:
    """Search output uses a search-results header."""
    emit_types_list_response(
        _LIST_PAYLOAD,
        json_mode=False,
        search_query="email",
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "Search results (page 1 of 3, 42 total)" in out


def test_emit_type_detail_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """JSON mode emits the full type response."""
    emit_type_detail(_DETAIL_PAYLOAD, json_mode=True)
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == _DETAIL_PAYLOAD


def test_emit_type_detail_human_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """Human mode prints labeled fields and a pretty-printed schema."""
    emit_type_detail(_DETAIL_PAYLOAD, json_mode=False)
    out = capsys.readouterr().out
    assert "Name:        Email" in out
    assert "Slug:        email" in out
    assert "Schema:" in out
    assert '"format": "email"' in out
