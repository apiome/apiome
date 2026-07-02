"""Unit tests for repository batch import CLI helpers."""

from __future__ import annotations

import json

from pathlib import Path

import pytest
import typer

from apiome_cli.client.repos_import_batch import (
    batch_import_has_failures,
    build_batch_import_items,
    build_batch_import_request_body,
    build_global_batch_item_template,
    emit_batch_import_result,
    load_repository_import_map,
    resolve_mapping_for_path,
    validate_batch_selection_mode,
)
from apiome_cli.exit_codes import EXIT_USAGE

_PROJECT_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
_VERSION_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
_FILE_A = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_FILE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_validate_batch_selection_mode_single() -> None:
    assert (
        validate_batch_selection_mode(
            file_id=_FILE_A,
            files_glob=None,
            files_regex=None,
            resume_run_id=None,
        )
        == "single"
    )


def test_validate_batch_selection_mode_batch_files() -> None:
    assert (
        validate_batch_selection_mode(
            file_id=None,
            files_glob="**/*.yaml",
            files_regex=None,
            resume_run_id=None,
        )
        == "batch"
    )


def test_validate_batch_selection_mode_resume() -> None:
    assert (
        validate_batch_selection_mode(
            file_id=None,
            files_glob=None,
            files_regex=None,
            resume_run_id="99999999-9999-4999-8999-999999999999",
        )
        == "resume"
    )


def test_validate_batch_selection_mode_rejects_mixed_single_and_files() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        validate_batch_selection_mode(
            file_id=_FILE_A,
            files_glob="**/*.yaml",
            files_regex=None,
            resume_run_id=None,
        )
    assert exc_info.value.exit_code == EXIT_USAGE


def test_validate_batch_selection_mode_requires_target() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        validate_batch_selection_mode(
            file_id=None,
            files_glob=None,
            files_regex=None,
            resume_run_id=None,
        )
    assert exc_info.value.exit_code == EXIT_USAGE


def test_load_repository_import_map_items_array(tmp_path: Path) -> None:
    map_path = tmp_path / "map.yaml"
    map_path.write_text(
        """
items:
  - path: openapi/petstore.yaml
    mapping: new_project
    version_name: "1.0.0"
  - path: "**/users.yaml"
    mapping: existing_version
    project_id: {project}
    version_id: {version}
""".format(project=_PROJECT_ID, version=_VERSION_ID),
        encoding="utf-8",
    )
    entries, default = load_repository_import_map(str(map_path))
    assert default is None
    assert "openapi/petstore.yaml" in entries
    assert entries["openapi/petstore.yaml"]["mapping"] == "new_project"


def test_load_repository_import_map_path_keyed_and_default(tmp_path: Path) -> None:
    map_path = tmp_path / "map.json"
    map_path.write_text(
        json.dumps(
            {
                "default": {"mapping": "new_project"},
                "openapi/users.yaml": {
                    "mapping": "existing_version",
                    "project_id": _PROJECT_ID,
                    "version_id": _VERSION_ID,
                },
            },
        ),
        encoding="utf-8",
    )
    entries, default = load_repository_import_map(str(map_path))
    assert default == {"mapping": "new_project"}
    assert entries["openapi/users.yaml"]["mapping"] == "existing_version"


def test_resolve_mapping_for_path_exact_and_glob() -> None:
    entries = {
        "openapi/petstore.yaml": {"mapping": "new_project"},
        "**/users.yaml": {
            "mapping": "existing_version",
            "project_id": _PROJECT_ID,
            "version_id": _VERSION_ID,
        },
    }
    exact = resolve_mapping_for_path(
        "openapi/petstore.yaml",
        map_entries=entries,
        default_entry=None,
    )
    assert exact["mapping"] == "new_project"

    globbed = resolve_mapping_for_path(
        "services/users.yaml",
        map_entries=entries,
        default_entry=None,
    )
    assert globbed["mapping"] == "existing_version"
    assert globbed["project_id"] == _PROJECT_ID


def test_build_global_batch_item_template_existing_version() -> None:
    template = build_global_batch_item_template(
        new_project=False,
        project_id=_PROJECT_ID,
        version_id=_VERSION_ID,
        version_name=None,
    )
    assert template == {
        "mapping": "existing_version",
        "project_id": _PROJECT_ID,
        "version_id": _VERSION_ID,
    }


def test_build_batch_import_items_with_global_template() -> None:
    files = [
        {"id": _FILE_A, "path": "openapi/petstore.yaml"},
        {"id": _FILE_B, "path": "openapi/users.yaml"},
    ]
    items = build_batch_import_items(
        files,
        map_entries=None,
        default_entry=None,
        global_template={"mapping": "new_project"},
    )
    assert items == [
        {"file_id": _FILE_A, "mapping": "new_project"},
        {"file_id": _FILE_B, "mapping": "new_project"},
    ]


def test_build_batch_import_items_with_map_entries() -> None:
    files = [{"id": _FILE_A, "path": "openapi/petstore.yaml"}]
    items = build_batch_import_items(
        files,
        map_entries={"openapi/petstore.yaml": {"mapping": "new_project"}},
        default_entry=None,
        global_template=None,
    )
    assert items == [{"file_id": _FILE_A, "mapping": "new_project"}]


def test_build_batch_import_request_body_resume() -> None:
    body = build_batch_import_request_body(
        items=None,
        dry_run=True,
        resume_run_id="99999999-9999-4999-8999-999999999999",
    )
    assert body == {
        "dry_run": True,
        "resume_run_id": "99999999-9999-4999-8999-999999999999",
    }


def test_batch_import_has_failures_detects_partial_and_failed() -> None:
    assert batch_import_has_failures({"status": "partial", "counts": {"failed": 0}})
    assert batch_import_has_failures({"status": "completed", "counts": {"failed": 1}})
    assert not batch_import_has_failures({"status": "completed", "counts": {"failed": 0}})


def test_emit_batch_import_result_human_summary(capsys: pytest.CaptureFixture[str]) -> None:
    emit_batch_import_result(
        {
            "run_id": "99999999-9999-4999-8999-999999999999",
            "status": "partial",
            "counts": {"total": 2, "succeeded": 1, "failed": 1, "skipped": 0},
            "items": [
                {
                    "file_id": _FILE_A,
                    "status": "succeeded",
                    "result": {
                        "project": {"name": "Pet Store"},
                        "version": {"version": "1.0.0"},
                    },
                },
                {
                    "file_id": _FILE_B,
                    "status": "failed",
                    "failure": {"message": "import failed"},
                },
            ],
        },
        json_mode=False,
        dry_run=False,
        path_by_file_id={
            _FILE_A: "openapi/petstore.yaml",
            _FILE_B: "openapi/broken.yaml",
        },
    )
    output = capsys.readouterr().out
    assert "Batch import completed." in output
    assert "Status: partial" in output
    assert "Succeeded: 1" in output
    assert "openapi/petstore.yaml" in output
    assert "import failed" in output
