"""Tests for repository file ``$ref`` closure helpers."""

from __future__ import annotations

import json

import pytest

from apiome_cli.client.repos_closure import (
    build_repository_file_closure,
    emit_repository_file_closure_result,
    extract_relative_refs,
    format_closure_indicator,
    resolve_relative_path,
    truncate_blob_sha,
)

from helpers import strip_ansi


def test_resolve_relative_path_sibling_reference() -> None:
    assert resolve_relative_path("openapi.yaml", "./paths/users.yaml") == "paths/users.yaml"


def test_resolve_relative_path_parent_directory() -> None:
    assert (
        resolve_relative_path("specs/openapi.yaml", "../schemas/user.yaml")
        == "schemas/user.yaml"
    )


def test_extract_relative_refs_from_json_document() -> None:
    content = json.dumps(
        {
            "components": {
                "schemas": {
                    "User": {"$ref": "./schemas/user.yaml"},
                },
            },
        },
    )
    refs = extract_relative_refs(content)
    assert refs == [("./schemas/user.yaml", "./schemas/user.yaml")]


def test_extract_relative_refs_from_yaml_with_inline_comment() -> None:
    content = "components:\n  schemas:\n    User:\n      $ref: './schemas/user.yaml' # local\n"
    refs = extract_relative_refs(content)
    assert refs == [("./schemas/user.yaml", "./schemas/user.yaml")]


def test_build_repository_file_closure_resolved_and_missing() -> None:
    closure = build_repository_file_closure(
        source_path="specs/openapi.yaml",
        content=(
            "paths:\n"
            "  /users:\n"
            "    $ref: './paths/users.yaml'\n"
            "components:\n"
            "  schemas:\n"
            "    Error:\n"
            "      $ref: '../schemas/error-missing.yaml'\n"
        ),
        files_by_path={
            "specs/paths/users.yaml": {"blob_sha": "abc1234567890"},
        },
    )
    assert closure["entrypoint"] == "specs/openapi.yaml"
    assert closure["total"] == 2
    assert closure["resolved_count"] == 1
    assert closure["missing_count"] == 1
    assert closure["has_unresolved"] is True
    assert closure["members"][0]["status"] == "missing"
    assert closure["members"][0]["path"] == "schemas/error-missing.yaml"
    assert closure["members"][1]["status"] == "resolved"
    assert closure["members"][1]["path"] == "specs/paths/users.yaml"


def test_build_repository_file_closure_self_contained() -> None:
    closure = build_repository_file_closure(
        source_path="openapi.yaml",
        content='{"openapi": "3.1.0"}',
        files_by_path={},
    )
    assert closure["total"] == 0
    assert closure["has_unresolved"] is False
    assert closure["members"] == []


def test_format_closure_indicator_states() -> None:
    empty = build_repository_file_closure(
        source_path="openapi.yaml",
        content='{"openapi": "3.1.0"}',
        files_by_path={},
    )
    resolved_only = build_repository_file_closure(
        source_path="openapi.yaml",
        content='{"components": {"schemas": {"User": {"$ref": "./user.yaml"}}}}',
        files_by_path={"user.yaml": {"blob_sha": "abc"}},
    )
    missing_only = build_repository_file_closure(
        source_path="openapi.yaml",
        content='{"components": {"schemas": {"User": {"$ref": "./missing.yaml"}}}}',
        files_by_path={},
    )
    mixed = build_repository_file_closure(
        source_path="openapi.yaml",
        content=(
            '{"components": {"schemas": {"User": {"$ref": "./user.yaml"}, '
            '"Error": {"$ref": "./missing.yaml"}}}}'
        ),
        files_by_path={"user.yaml": {"blob_sha": "abc"}},
    )

    assert format_closure_indicator(empty) == "—"
    assert format_closure_indicator(resolved_only) == "1 resolved"
    assert format_closure_indicator(missing_only) == "1 missing"
    assert format_closure_indicator(mixed) == "1 resolved, 1 missing"


def test_truncate_blob_sha() -> None:
    assert truncate_blob_sha("abc1234567890") == "abc1234"
    assert truncate_blob_sha(None) == ""


def test_emit_repository_file_closure_result_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    closure = build_repository_file_closure(
        source_path="specs/openapi.yaml",
        content='{"components": {"schemas": {"User": {"$ref": "./user.yaml"}}}}',
        files_by_path={"specs/user.yaml": {"blob_sha": "abc1234567890"}},
    )
    emit_repository_file_closure_result(closure, json_mode=False)
    output = strip_ansi(capsys.readouterr().out)
    assert "$ref closure" in output
    assert "Entrypoint: specs/openapi.yaml" in output
    assert "[resolved] specs/user.yaml (abc1234)" in output


def test_emit_repository_file_closure_result_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    closure = build_repository_file_closure(
        source_path="openapi.yaml",
        content='{"openapi": "3.1.0"}',
        files_by_path={},
    )
    emit_repository_file_closure_result(closure, json_mode=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["entrypoint"] == "openapi.yaml"
    assert payload["total"] == 0
