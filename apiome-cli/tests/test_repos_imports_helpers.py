"""Unit tests for repository import list helpers."""

from __future__ import annotations

from uuid import UUID

import pytest
import typer

from apiome_cli.client.repos_imports import (
    build_import_list_query_params,
    format_blob_sha,
    format_imported_at,
    format_imported_by,
)

_PROJECT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_VERSION_ID = UUID("11111111-1111-4111-8111-111111111111")
_ACTOR_ID = UUID("55555555-5555-4555-8555-555555555555")


def test_build_import_list_query_params_empty() -> None:
    assert build_import_list_query_params(
        project_id=None,
        version_id=None,
        actor_id=None,
        since=None,
        until=None,
    ) == []


def test_build_import_list_query_params_all_filters() -> None:
    params = build_import_list_query_params(
        project_id=_PROJECT_ID,
        version_id=_VERSION_ID,
        actor_id=_ACTOR_ID,
        since="2026-06-01T00:00:00Z",
        until="2026-06-30T23:59:59Z",
    )
    assert params == [
        ("project_id", str(_PROJECT_ID)),
        ("version_id", str(_VERSION_ID)),
        ("actor_id", str(_ACTOR_ID)),
        ("since", "2026-06-01T00:00:00Z"),
        ("until", "2026-06-30T23:59:59Z"),
    ]


def test_build_import_list_query_params_rejects_invalid_since() -> None:
    with pytest.raises(typer.BadParameter, match="--since must be an ISO-8601"):
        build_import_list_query_params(
            project_id=None,
            version_id=None,
            actor_id=None,
            since="not-a-date",
            until=None,
        )


def test_build_import_list_query_params_rejects_since_after_until() -> None:
    with pytest.raises(typer.BadParameter, match="--since must be on or before --until"):
        build_import_list_query_params(
            project_id=None,
            version_id=None,
            actor_id=None,
            since="2026-06-30T23:59:59Z",
            until="2026-06-01T00:00:00Z",
        )


def test_format_blob_sha_truncates() -> None:
    assert format_blob_sha("a" * 40) == "aaaaaaa"


def test_format_imported_at_parses_iso_timestamp() -> None:
    assert format_imported_at("2026-06-07T12:00:00Z") == "2026-06-07 12:00 UTC"


def test_format_imported_by_truncates_uuid() -> None:
    assert format_imported_by("55555555-5555-4555-8555-555555555555") == "55555555…"
