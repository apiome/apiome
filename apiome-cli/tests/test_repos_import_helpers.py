"""Unit tests for repository file import CLI helpers."""

from __future__ import annotations

import pytest
import typer

from apiome_cli.client.repos_import import (
    build_repository_file_import_body,
    format_repository_file_import_progress,
    validate_import_mode,
)
from apiome_cli.exit_codes import EXIT_USAGE

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_validate_import_mode_new_project() -> None:
    assert validate_import_mode(
        new_project=True,
        project_id=None,
        version_id=None,
        version_name="1.0.0",
    ) == "new_project"


def test_validate_import_mode_existing_version() -> None:
    assert validate_import_mode(
        new_project=False,
        project_id=_PROJECT_ID,
        version_id=_VERSION_ID,
        version_name=None,
    ) == "existing_version"


def test_validate_import_mode_existing_project_new_version() -> None:
    assert validate_import_mode(
        new_project=False,
        project_id=_PROJECT_ID,
        version_id=None,
        version_name="2.0.0",
    ) == "existing_project_new_version"


def test_validate_import_mode_rejects_new_project_with_project() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        validate_import_mode(
            new_project=True,
            project_id=_PROJECT_ID,
            version_id=None,
            version_name=None,
        )
    assert exc_info.value.exit_code == EXIT_USAGE


def test_validate_import_mode_rejects_both_version_selectors() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        validate_import_mode(
            new_project=False,
            project_id=_PROJECT_ID,
            version_id=_VERSION_ID,
            version_name="2.0.0",
        )
    assert exc_info.value.exit_code == EXIT_USAGE


def test_validate_import_mode_requires_target() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        validate_import_mode(
            new_project=False,
            project_id=None,
            version_id=None,
            version_name=None,
        )
    assert exc_info.value.exit_code == EXIT_USAGE


def test_build_body_new_project_with_version_name() -> None:
    body = build_repository_file_import_body(
        mapping="new_project",
        project_id=None,
        version_id=None,
        version_name="3.0.0-beta",
        dry_run=False,
    )
    assert body == {
        "mapping": "new_project",
        "dry_run": False,
        "version_name": "3.0.0-beta",
    }


def test_build_body_existing_version() -> None:
    body = build_repository_file_import_body(
        mapping="existing_version",
        project_id=_PROJECT_ID,
        version_id=_VERSION_ID,
        version_name=None,
        dry_run=True,
    )
    assert body == {
        "mapping": "existing_version",
        "dry_run": True,
        "project_id": _PROJECT_ID,
        "version_id": _VERSION_ID,
    }


def test_build_body_existing_project_new_version() -> None:
    body = build_repository_file_import_body(
        mapping="existing_project_new_version",
        project_id=_PROJECT_ID,
        version_id=None,
        version_name="2.0.0",
        dry_run=False,
    )
    assert body == {
        "mapping": "existing_project_new_version",
        "dry_run": False,
        "project_id": _PROJECT_ID,
        "version_name": "2.0.0",
    }


def test_format_repository_file_import_progress_includes_path() -> None:
    assert (
        format_repository_file_import_progress(
            file_label="openapi.yaml",
            dry_run=False,
        )
        == "Importing repository file openapi.yaml…"
    )
    assert (
        format_repository_file_import_progress(
            file_label="openapi.yaml",
            dry_run=True,
        )
        == "Planning repository file import of openapi.yaml (dry run)…"
    )
