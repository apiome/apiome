"""Tests for repository file list filter helpers and table output."""

from __future__ import annotations

import pytest
import typer

from apiome_cli.client.repos_files import (
    build_file_list_query_params,
    emit_repository_files_table,
    format_detected_kind,
    format_file_size_bytes,
    format_importable_verdict,
    normalize_preset_filter,
    validate_file_list_filters,
)

from helpers import strip_ansi


def test_normalize_preset_filter_accepts_rest_values() -> None:
    assert normalize_preset_filter("all_importable") == "all_importable"
    assert normalize_preset_filter("json_schema") == "json_schema"
    assert normalize_preset_filter("sql_ddl") == "sql_ddl"


def test_normalize_preset_filter_normalizes_hyphens() -> None:
    assert normalize_preset_filter("all-importable") == "all_importable"
    assert normalize_preset_filter("JSON-SCHEMA") == "json_schema"


def test_normalize_preset_filter_rejects_unknown_value() -> None:
    with pytest.raises(typer.BadParameter, match="--preset must be one of"):
        normalize_preset_filter("custom")


def test_validate_file_list_filters_rejects_glob_and_regex_together() -> None:
    with pytest.raises(typer.BadParameter, match="mutually exclusive"):
        validate_file_list_filters(glob="**/*.yaml", regex="openapi")


def test_build_file_list_query_params_includes_active_filters() -> None:
    params = build_file_list_query_params(
        glob="**/*.yaml, **/arazzo/*.yaml",
        regex=None,
        preset="openapi",
        detected_kind="openapi-candidate",
        importable=True,
    )
    assert params == [
        ("glob", "**/*.yaml, **/arazzo/*.yaml"),
        ("preset", "openapi"),
        ("detected_kind", "openapi-candidate"),
        ("importable", "true"),
    ]


def test_build_file_list_query_params_omits_blank_values() -> None:
    assert build_file_list_query_params(
        glob="  ",
        regex=None,
        preset=None,
        detected_kind="",
        importable=None,
    ) == []


def test_format_detected_kind_handles_null_and_blank() -> None:
    assert format_detected_kind(None) == "—"
    assert format_detected_kind("  ") == "—"
    assert format_detected_kind("openapi-candidate") == "openapi-candidate"


def test_format_importable_verdict_states() -> None:
    assert format_importable_verdict(None) == "pending"
    assert format_importable_verdict(True) == "yes"
    assert format_importable_verdict(False) == "no"
    assert format_importable_verdict(False, blocked_reason="unsupported kind") == (
        "no (unsupported kind)"
    )


def test_format_file_size_bytes() -> None:
    assert format_file_size_bytes(512) == "512 B"
    assert format_file_size_bytes(2048) == "2.0 KiB"
    assert format_file_size_bytes(5 * 1024 * 1024) == "5.0 MiB"


def test_emit_repository_files_table_renders_columns(capsys: pytest.CaptureFixture[str]) -> None:
    emit_repository_files_table(
        [
            {
                "path": "openapi.yaml",
                "size_bytes": 128,
                "detected_kind": "openapi-candidate",
                "importable": True,
            },
            {
                "path": "README.md",
                "size_bytes": 64,
                "detected_kind": None,
                "importable": None,
            },
        ],
        total=2,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "openapi.yaml" in output
    assert "openapi-candidate" in output
    assert "yes" in output
    assert "README.md" in output
    assert "pending" in output
    assert "Showing 2 of 2" in output


def test_emit_repository_files_table_empty_state(capsys: pytest.CaptureFixture[str]) -> None:
    emit_repository_files_table([], total=0)
    output = strip_ansi(capsys.readouterr().out)
    assert "No items." in output
    assert "Total: 0" in output


def test_emit_repository_files_table_renders_closure_column(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_repository_files_table(
        [
            {
                "path": "openapi.yaml",
                "size_bytes": 128,
                "detected_kind": "openapi-candidate",
                "importable": True,
                "closure_indicator": "2 resolved, 1 missing",
            },
        ],
        total=1,
        show_closure=True,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Closure" in output
    assert "2 resolved" in output
    assert "missing" in output
