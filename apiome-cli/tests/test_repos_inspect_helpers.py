"""Tests for repository file sniff inspect helpers."""

from __future__ import annotations

import json

import pytest

from apiome_cli.client.repos_inspect import (
    emit_repository_file_deep_verdict_result,
    emit_repository_file_sniff_result,
    format_bundle_member,
    format_deep_verdict_finding,
    format_deep_verdict_findings,
    format_detected_version,
    format_fidelity_status,
    format_sniff_confidence,
    format_sniff_reasons,
)

from helpers import strip_ansi

_FILE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def test_format_detected_version_missing() -> None:
    assert format_detected_version(None) == "—"
    assert format_detected_version("") == "—"


def test_format_detected_version_value() -> None:
    assert format_detected_version("3.1.0") == "3.1.0"


def test_format_sniff_confidence_value() -> None:
    assert format_sniff_confidence("content_sniffed") == "content_sniffed"


def test_format_sniff_reasons_filters_empty_entries() -> None:
    assert format_sniff_reasons([" Top-level openapi key is 3.1.0. ", "", 42]) == [
        "Top-level openapi key is 3.1.0.",
    ]
    assert format_sniff_reasons(None) == []


def test_emit_repository_file_sniff_result_importable_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_repository_file_sniff_result(
        {
            "file_id": _FILE_ID,
            "detected_kind": "openapi",
            "detected_confidence": "content_sniffed",
            "detected_version": "3.1.0",
            "importable": True,
            "import_blocked_reason": None,
            "reasons": ["Top-level openapi key is 3.1.0."],
        },
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Content sniff completed." in output
    assert _FILE_ID in output
    assert "Kind: openapi" in output
    assert "Version: 3.1.0" in output
    assert "Importable: yes" in output
    assert "Confidence: content_sniffed" in output
    assert "Top-level openapi key is 3.1.0." in output


def test_emit_repository_file_sniff_result_not_importable_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_repository_file_sniff_result(
        {
            "file_id": _FILE_ID,
            "detected_kind": None,
            "detected_confidence": "content_sniffed",
            "detected_version": None,
            "importable": False,
            "import_blocked_reason": "No supported import kind found.",
            "reasons": ["No supported import kind found."],
        },
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Kind: —" in output
    assert "Version: —" in output
    assert "Importable: no (No supported import kind found.)" in output
    assert "No supported import kind found." in output


def test_emit_repository_file_sniff_result_json_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "file_id": _FILE_ID,
        "detected_kind": "openapi",
        "detected_confidence": "content_sniffed",
        "detected_version": "3.1.0",
        "importable": True,
        "import_blocked_reason": None,
        "reasons": ["Top-level openapi key is 3.1.0."],
    }
    emit_repository_file_sniff_result(payload, json_mode=True)
    assert json.loads(capsys.readouterr().out) == payload


def test_emit_repository_file_sniff_result_json_mode_with_closure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "file_id": _FILE_ID,
        "detected_kind": "openapi",
        "detected_confidence": "content_sniffed",
        "detected_version": "3.1.0",
        "importable": True,
        "import_blocked_reason": None,
        "reasons": ["Top-level openapi key is 3.1.0."],
    }
    closure = {
        "entrypoint": "openapi.yaml",
        "members": [],
        "has_unresolved": False,
        "total": 0,
        "resolved_count": 0,
        "missing_count": 0,
    }
    emit_repository_file_sniff_result(payload, json_mode=True, closure=closure)
    output = json.loads(capsys.readouterr().out)
    assert output["detected_kind"] == "openapi"
    assert output["closure"] == closure


def test_emit_repository_file_sniff_result_human_with_closure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_repository_file_sniff_result(
        {
            "file_id": _FILE_ID,
            "detected_kind": "openapi",
            "detected_confidence": "content_sniffed",
            "detected_version": "3.1.0",
            "importable": True,
            "import_blocked_reason": None,
            "reasons": [],
        },
        json_mode=False,
        closure={
            "entrypoint": "openapi.yaml",
            "members": [
                {
                    "path": "schemas/user.yaml",
                    "blob_sha": "abc1234567890",
                    "status": "resolved",
                    "ref": "./schemas/user.yaml",
                    "source_path": "openapi.yaml",
                },
            ],
            "has_unresolved": False,
            "total": 1,
            "resolved_count": 1,
            "missing_count": 0,
        },
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Content sniff completed." in output
    assert "$ref closure" in output
    assert "[resolved] schemas/user.yaml (abc1234)" in output


_DEEP_VERDICT_CLEAN = {
    "file_id": _FILE_ID,
    "deep_verdict_at": "2026-06-11T12:00:00Z",
    "validation_status": "valid",
    "validation_errors": [],
    "lint_findings": [],
    "fidelity": "exact",
    "fidelity_nodes": [],
    "secrets_findings": [],
    "detected_kind": "openapi",
    "bundle_members": [
        {
            "file_id": _FILE_ID,
            "path": "openapi.yaml",
            "blob_sha": "abc1234567890",
            "size_bytes": 128,
        },
    ],
    "blocking": False,
    "blocking_reasons": [],
    "_links": {
        "self": {"href": f"/files/{_FILE_ID}"},
        "verify": {"href": f"/files/{_FILE_ID}/verify"},
    },
}


def test_format_deep_verdict_finding() -> None:
    assert (
        format_deep_verdict_finding(
            {
                "code": "dangling_ref",
                "message": "Unresolved reference target.",
                "path": "/paths/~1items/get/x-model/$ref",
                "severity": "warning",
            }
        )
        == "[warning] (dangling_ref) at /paths/~1items/get/x-model/$ref: "
        "Unresolved reference target."
    )


def test_format_deep_verdict_findings_filters_invalid_entries() -> None:
    assert format_deep_verdict_findings(
        [
            {
                "code": "duplicate_operation_id",
                "message": "Duplicate operationId.",
                "path": "/paths/~1items/get/operationId",
                "severity": "error",
            },
            "ignored",
        ]
    ) == [
        "[error] (duplicate_operation_id) at /paths/~1items/get/operationId: "
        "Duplicate operationId."
    ]


def test_format_fidelity_status() -> None:
    assert format_fidelity_status("exact") == "exact"
    assert format_fidelity_status(None) == "—"


def test_format_bundle_member() -> None:
    assert (
        format_bundle_member(
            {
                "file_id": _FILE_ID,
                "path": "openapi.yaml",
                "blob_sha": "abc1234567890",
                "size_bytes": 128,
            }
        )
        == "openapi.yaml (abc1234)"
    )


def test_emit_repository_file_deep_verdict_result_clean_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        emit_repository_file_deep_verdict_result(_DEEP_VERDICT_CLEAN, json_mode=False)
        is False
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Deep pre-import verdict completed." in output
    assert _FILE_ID in output
    assert "Kind: openapi" in output
    assert "Validation: valid" in output
    assert "Fidelity: exact" in output
    assert "Blocking: no" in output
    assert "Validation errors:" in output
    assert "Lint findings:" in output
    assert "Secrets findings:" in output
    assert "Bundle members:" in output
    assert "openapi.yaml (abc1234)" in output


def test_emit_repository_file_deep_verdict_result_blocking_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        **_DEEP_VERDICT_CLEAN,
        "validation_status": "invalid",
        "blocking": True,
        "blocking_reasons": ["Structural validation failed."],
        "validation_errors": [
            {
                "code": "invalid_document",
                "message": "Document failed structural validation.",
                "path": "/paths",
                "severity": "error",
            },
        ],
    }
    assert emit_repository_file_deep_verdict_result(payload, json_mode=False) is True
    output = strip_ansi(capsys.readouterr().out)
    assert "Blocking: yes" in output
    assert "Structural validation failed." in output
    assert "invalid_document" in output


def test_emit_repository_file_deep_verdict_result_json_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        emit_repository_file_deep_verdict_result(_DEEP_VERDICT_CLEAN, json_mode=True)
        is False
    )
    assert json.loads(capsys.readouterr().out) == _DEEP_VERDICT_CLEAN
