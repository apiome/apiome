"""Unit tests for cataloger note validation (V2-MCP-36.3 / MCAT-22.3, #4666)."""

import pytest

from app.mcp_endpoint_notes import (
    MAX_ENDPOINT_NOTE_CHARS,
    EndpointNoteValidationError,
    normalize_endpoint_note_body,
)


def test_normalize_trims_body():
    assert normalize_endpoint_note_body("  hello  ") == "hello"


def test_normalize_rejects_empty():
    with pytest.raises(EndpointNoteValidationError, match="required"):
        normalize_endpoint_note_body("   ")


def test_normalize_rejects_over_limit():
    with pytest.raises(EndpointNoteValidationError, match=str(MAX_ENDPOINT_NOTE_CHARS)):
        normalize_endpoint_note_body("x" * (MAX_ENDPOINT_NOTE_CHARS + 1))
