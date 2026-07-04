"""Unit tests for AsyncAPI fileset bundling — MFI-29.2 (#4389)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.asyncapi_fileset import bundle_asyncapi_fileset
from app.fileset import IntakeFileset
from app.import_source import ImportSourceError

_FIXTURES = Path(__file__).parent / "fixtures" / "asyncapi" / "suite"


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _suite() -> IntakeFileset:
    return IntakeFileset.from_members(
        {
            "api.yaml": _read("api.yaml"),
            "components/messages.yaml": _read("components/messages.yaml"),
            "components/schemas.yaml": _read("components/schemas.yaml"),
        },
        root="api.yaml",
    )


def test_bundle_inlines_external_components() -> None:
    text = bundle_asyncapi_fileset(_suite())
    assert '"UserSignedUp"' in text or "UserSignedUp" in text
    assert "userId" in text
    assert "./components/messages.yaml" not in text


def test_bundle_missing_member_is_named_in_error() -> None:
    fileset = IntakeFileset.from_members(
        {"api.yaml": _read("broken_api.yaml")},
        root="api.yaml",
    )
    with pytest.raises(ImportSourceError, match="missing\\.yaml"):
        bundle_asyncapi_fileset(fileset)


def test_bundle_rejects_path_escape() -> None:
    fileset = IntakeFileset.from_members(
        {
            "sub/api.yaml": (
                "asyncapi: '3.0.0'\ninfo:\n  title: X\n  version: '1'\n"
                "channels:\n  c:\n    address: a\n    messages:\n      M:\n"
                "        $ref: '../../../escape.yaml#/components/messages/M'\n"
            ),
        },
        root="sub/api.yaml",
    )
    with pytest.raises(ImportSourceError, match="escapes"):
        bundle_asyncapi_fileset(fileset)
