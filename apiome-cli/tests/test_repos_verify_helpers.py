"""Tests for repository trust verification helpers."""

from __future__ import annotations

import json

import pytest

from apiome_cli.client.repos_verify import (
    assess_repository_file_trust,
    assess_repository_files_trust,
    count_trust_failures,
    emit_repository_verify_results,
    format_integrity_status,
    format_signature_status,
)

from helpers import strip_ansi


def test_format_integrity_status() -> None:
    assert format_integrity_status(True) == "verified"
    assert format_integrity_status(False) == "failed"
    assert format_integrity_status(None) == "pending"


def test_format_signature_status() -> None:
    assert format_signature_status("valid") == "valid"
    assert format_signature_status(None) == "unverified"
    assert format_signature_status("") == "unverified"


def test_assess_repository_file_trust_passes_valid_file() -> None:
    result = assess_repository_file_trust(
        {
            "id": "file-1",
            "path": "openapi.yaml",
            "commit_sha": "abc123",
            "content_integrity_verified": True,
            "signature_status": "valid",
        }
    )
    assert result["passed"] is True
    assert result["failures"] == []
    assert result["integrity_status"] == "verified"


def test_assess_repository_file_trust_fails_on_integrity() -> None:
    result = assess_repository_file_trust(
        {
            "id": "file-1",
            "path": "openapi.yaml",
            "content_integrity_verified": False,
            "signature_status": "valid",
        }
    )
    assert result["passed"] is False
    assert result["failures"] == ["content_integrity_failed"]


def test_assess_repository_file_trust_fails_on_invalid_signature() -> None:
    result = assess_repository_file_trust(
        {
            "id": "file-1",
            "path": "openapi.yaml",
            "content_integrity_verified": True,
            "signature_status": "invalid",
        }
    )
    assert result["passed"] is False
    assert result["failures"] == ["signature_invalid"]


def test_assess_repository_file_trust_pending_is_not_failure() -> None:
    result = assess_repository_file_trust(
        {
            "id": "file-1",
            "path": "openapi.yaml",
            "content_integrity_verified": None,
            "signature_status": "unsigned",
        }
    )
    assert result["passed"] is True
    assert result["integrity_status"] == "pending"
    assert result["signature_status"] == "unsigned"


def test_count_trust_failures() -> None:
    assessments = assess_repository_files_trust(
        [
            {
                "id": "1",
                "path": "a.yaml",
                "content_integrity_verified": True,
                "signature_status": "valid",
            },
            {
                "id": "2",
                "path": "b.yaml",
                "content_integrity_verified": False,
                "signature_status": "valid",
            },
        ]
    )
    assert count_trust_failures(assessments) == 1


def test_emit_repository_verify_results_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_repository_verify_results(
        [
            assess_repository_file_trust(
                {
                    "id": "file-1",
                    "path": "openapi.yaml",
                    "commit_sha": "abc1234567890",
                    "content_integrity_verified": True,
                    "signature_status": "valid",
                }
            ),
            assess_repository_file_trust(
                {
                    "id": "file-2",
                    "path": "broken.yaml",
                    "commit_sha": "def4567890ab",
                    "content_integrity_verified": False,
                    "signature_status": "invalid",
                }
            ),
        ],
        repository_id="repo-1",
        total=2,
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Repository trust verification" in output
    assert "openapi.yaml" in output
    assert "broken.yaml" in output
    assert "Failures: 1" in output


def test_emit_repository_verify_results_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_repository_verify_results(
        [
            assess_repository_file_trust(
                {
                    "id": "file-1",
                    "path": "openapi.yaml",
                    "content_integrity_verified": True,
                    "signature_status": "valid",
                }
            ),
        ],
        repository_id="repo-1",
        total=1,
        json_mode=True,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["repository_id"] == "repo-1"
    assert payload["passed"] is True
    assert payload["failure_count"] == 0
    assert payload["items"][0]["integrity_status"] == "verified"
