"""Unit tests for repository manifest import CLI helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from apiome_cli.client.repos_import_manifest import (
    build_local_manifest_batch_items,
    build_repo_manifest_import_request_body,
    load_local_repository_import_manifest,
    validate_manifest_import_flags,
)
from apiome_cli.client.repos_import_batch import validate_batch_selection_mode
from apiome_cli.exit_codes import EXIT_USAGE

_PROJECT_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
_VERSION_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
_FILE_A = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_FILE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_validate_batch_selection_mode_manifest_repo() -> None:
    assert (
        validate_batch_selection_mode(
            file_id=None,
            files_glob=None,
            files_regex=None,
            resume_run_id=None,
            manifest="manifest",
            manifest_file=None,
        )
        == "manifest"
    )


def test_validate_batch_selection_mode_manifest_local() -> None:
    assert (
        validate_batch_selection_mode(
            file_id=None,
            files_glob=None,
            files_regex=None,
            resume_run_id=None,
            manifest=None,
            manifest_file="./.apiome.yaml",
        )
        == "manifest_local"
    )


def test_validate_batch_selection_mode_manifest_resume() -> None:
    assert (
        validate_batch_selection_mode(
            file_id=None,
            files_glob=None,
            files_regex=None,
            resume_run_id="99999999-9999-4999-8999-999999999999",
            manifest="manifest",
            manifest_file=None,
        )
        == "manifest"
    )


def test_validate_batch_selection_mode_rejects_manifest_with_file_id() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        validate_batch_selection_mode(
            file_id=_FILE_A,
            files_glob=None,
            files_regex=None,
            resume_run_id=None,
            manifest="manifest",
            manifest_file=None,
        )
    assert exc_info.value.exit_code == EXIT_USAGE


def test_validate_manifest_import_flags_rejects_mapping_flags() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        validate_manifest_import_flags(
            selection_mode="manifest",
            map_file=None,
            new_project=True,
            project_id=None,
            version_id=None,
            version_name=None,
        )
    assert exc_info.value.exit_code == EXIT_USAGE


def test_build_repo_manifest_import_request_body_dry_run() -> None:
    assert build_repo_manifest_import_request_body(
        dry_run=True,
        resume_run_id=None,
    ) == {"dry_run": True}


def test_build_repo_manifest_import_request_body_resume() -> None:
    run_id = "99999999-9999-4999-8999-999999999999"
    assert build_repo_manifest_import_request_body(
        dry_run=False,
        resume_run_id=run_id,
    ) == {"dry_run": False, "resume_run_id": run_id}


def test_load_local_repository_import_manifest_valid_yaml(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".apiome.yaml"
    manifest_path.write_text(
        """
version: 1
imports:
  - path: openapi/petstore.yaml
    project: pet-store
    version: "1.0.0"
""",
        encoding="utf-8",
    )
    document = load_local_repository_import_manifest(str(manifest_path))
    assert document["version"] == 1
    assert document["imports"][0]["project"] == "pet-store"


def test_load_local_repository_import_manifest_invalid_pointer(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".apiome.yaml"
    manifest_path.write_text(
        """
version: 1
imports:
  - path: ""
    project: bad slug
    version: "1.0.0"
""",
        encoding="utf-8",
    )
    with pytest.raises(typer.BadParameter, match="At /imports/0"):
        load_local_repository_import_manifest(str(manifest_path))


def test_build_local_manifest_batch_items_new_project(
    httpx_mock: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")

    httpx_mock.add_response(
        url="http://localhost:8000/projects?offset=0&limit=50",
        json={"items": [], "total": 0, "offset": 0, "limit": 50},
    )
    httpx_mock.add_response(
        url="http://localhost:8000/project-versions?offset=0&limit=50",
        json={"items": [], "total": 0, "offset": 0, "limit": 50},
    )

    from apiome_cli.client.http import RestClient
    from apiome_cli.config import CliSettings

    client = RestClient(CliSettings())
    items = build_local_manifest_batch_items(
        client,
        manifest={
            "version": 1,
            "imports": [
                {
                    "path": "openapi/petstore.yaml",
                    "newProject": {"title": "Pet Store"},
                    "version": "1.0.0",
                },
            ],
        },
        repository_files=[
            {
                "id": _FILE_A,
                "path": "openapi/petstore.yaml",
                "blob_sha": "a" * 40,
            },
        ],
    )
    assert items == [
        {
            "file_id": _FILE_A,
            "mapping": "new_project",
            "version_name": "1.0.0",
        },
    ]


def test_build_local_manifest_batch_items_existing_version(
    httpx_mock: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")

    httpx_mock.add_response(
        url="http://localhost:8000/projects?offset=0&limit=50",
        json={
            "items": [
                {
                    "id": _PROJECT_ID,
                    "slug": "pet-store",
                    "name": "Pet Store",
                },
            ],
            "total": 1,
            "offset": 0,
            "limit": 50,
        },
    )
    httpx_mock.add_response(
        url="http://localhost:8000/project-versions?offset=0&limit=50",
        json={
            "items": [
                {
                    "id": _VERSION_ID,
                    "project_id": _PROJECT_ID,
                    "slug": "1.0.0",
                    "version": "1.0.0",
                },
            ],
            "total": 1,
            "offset": 0,
            "limit": 50,
        },
    )

    from apiome_cli.client.http import RestClient
    from apiome_cli.config import CliSettings

    client = RestClient(CliSettings())
    items = build_local_manifest_batch_items(
        client,
        manifest={
            "version": 1,
            "imports": [
                {
                    "path": "openapi/petstore.yaml",
                    "project": "pet-store",
                    "version": "1.0.0",
                },
            ],
        },
        repository_files=[
            {
                "id": _FILE_A,
                "path": "openapi/petstore.yaml",
                "blob_sha": "a" * 40,
            },
        ],
    )
    assert items == [
        {
            "file_id": _FILE_A,
            "mapping": "existing_version",
            "project_id": _PROJECT_ID,
            "version_id": _VERSION_ID,
        },
    ]


def test_build_local_manifest_batch_items_glob_match(
    httpx_mock: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")

    httpx_mock.add_response(
        url="http://localhost:8000/projects?offset=0&limit=50",
        json={"items": [], "total": 0, "offset": 0, "limit": 50},
    )
    httpx_mock.add_response(
        url="http://localhost:8000/project-versions?offset=0&limit=50",
        json={"items": [], "total": 0, "offset": 0, "limit": 50},
    )

    from apiome_cli.client.http import RestClient
    from apiome_cli.config import CliSettings

    client = RestClient(CliSettings())
    items = build_local_manifest_batch_items(
        client,
        manifest={
            "version": 1,
            "imports": [
                {
                    "path": "openapi/*.yaml",
                    "newProject": {"title": "APIs"},
                    "version": "1.0.0",
                },
            ],
        },
        repository_files=[
            {"id": _FILE_A, "path": "openapi/petstore.yaml", "blob_sha": "a" * 40},
            {"id": _FILE_B, "path": "docs/readme.md", "blob_sha": "b" * 40},
        ],
    )
    assert len(items) == 1
    assert items[0]["file_id"] == _FILE_A
