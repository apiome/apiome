"""Revision-note derivation for imported version publish.

Commit policy may require a shortMessage; the import never collects one, so it is
derived from the spec (description, then title) with a slug+version fallback.
"""

from __future__ import annotations

from typing import Any

import pytest

from apiome_cli.commands.import_ import (
    _MAX_REVISION_NOTE_CHARS,
    _derive_revision_note,
    _payload_str,
)


def test_derive_prefers_description_first_line() -> None:
    spec = {"info": {"title": "Pet Store", "description": "\n  Line one.\nLine two.\n"}}
    assert _derive_revision_note(spec) == "Line one."


def test_derive_falls_back_to_title_when_no_description() -> None:
    assert _derive_revision_note({"info": {"title": "Pet Store"}}) == "Pet Store"


def test_derive_ignores_blank_description() -> None:
    spec = {"info": {"title": "Pet Store", "description": "   \n  \n"}}
    assert _derive_revision_note(spec) == "Pet Store"


@pytest.mark.parametrize("spec", [{}, {"info": {}}, {"info": {"title": "  "}}, {"info": "x"}])
def test_derive_returns_none_without_description_or_title(spec: dict[str, Any]) -> None:
    assert _derive_revision_note(spec) is None


def test_derive_truncates_to_policy_limit() -> None:
    long_desc = "x" * (_MAX_REVISION_NOTE_CHARS + 50)
    note = _derive_revision_note({"info": {"description": long_desc}})
    assert note is not None
    assert len(note) == _MAX_REVISION_NOTE_CHARS


def test_payload_str_reads_top_level_then_nested() -> None:
    assert _payload_str({"project_slug": "pet-store"}, "project_slug", "project", "slug") == "pet-store"
    nested = {"version": {"version": "1.0.0"}}
    assert _payload_str(nested, "version_id", "version", "version") == "1.0.0"
    assert _payload_str({}, "version_id", "version", "version") == ""
