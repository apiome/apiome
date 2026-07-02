"""Tests for repository scan enqueue and poll helpers."""

from __future__ import annotations

import json

import pytest
import typer

from apiome_cli.client.http import RestClient
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.client.repos_scan import (
    emit_scan_completed_counts,
    emit_scan_enqueue_result,
    format_scan_progress,
    wait_for_repository_scan,
)

from helpers import strip_ansi

_TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_REPO_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_SCAN_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_STATUS_URL = (
    f"http://localhost:8000/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/scans/{_SCAN_ID}"
)


def test_format_scan_progress_message() -> None:
    assert format_scan_progress("running", elapsed_seconds=12.7) == "Scan running… (12s)"


def test_wait_for_repository_scan_returns_done_payload(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=_STATUS_URL,
        json={"status": "running", "scan_id": _SCAN_ID},
    )
    httpx_mock.add_response(
        url=_STATUS_URL,
        json={
            "status": "done",
            "scan_id": _SCAN_ID,
            "branch": "main",
            "files_seen": 10,
            "files_added": 3,
            "files_changed": 1,
            "files_removed": 0,
        },
    )
    client = RestClient(CliSettings(), timeout=30.0)
    result = wait_for_repository_scan(
        client,
        _TENANT_ID,
        _REPO_ID,
        _SCAN_ID,
        poll_interval=0.01,
        timeout=5.0,
        no_progress=True,
        sleep=lambda _seconds: None,
    )
    assert result["status"] == "done"
    assert result["files_seen"] == 10


def test_wait_for_repository_scan_exits_on_failed_status(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=_STATUS_URL,
        json={"status": "failed", "error_message": "provider walk failed"},
    )
    client = RestClient(CliSettings(), timeout=30.0)
    with pytest.raises(typer.Exit) as exc_info:
        wait_for_repository_scan(
            client,
            _TENANT_ID,
            _REPO_ID,
            _SCAN_ID,
            poll_interval=0.01,
            timeout=5.0,
            no_progress=True,
            sleep=lambda _seconds: None,
        )
    assert exc_info.value.exit_code == EXIT_ERROR


def test_emit_scan_enqueue_result_human_mode(capsys: pytest.CaptureFixture[str]) -> None:
    emit_scan_enqueue_result(
        {
            "scan_id": _SCAN_ID,
            "branch": "main",
            "status": "queued",
            "created": True,
        },
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Scan enqueued." in output
    assert _SCAN_ID in output
    assert "main" in output
    assert "queued" in output


def test_emit_scan_enqueue_result_idempotent_note(capsys: pytest.CaptureFixture[str]) -> None:
    emit_scan_enqueue_result(
        {
            "scan_id": _SCAN_ID,
            "branch": "main",
            "status": "queued",
            "created": False,
        },
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "idempotent enqueue" in output


def test_emit_scan_enqueue_result_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    payload = {"scan_id": _SCAN_ID, "status": "queued"}
    emit_scan_enqueue_result(payload, json_mode=True)
    assert json.loads(capsys.readouterr().out) == payload


def test_emit_scan_completed_counts_human_mode(capsys: pytest.CaptureFixture[str]) -> None:
    emit_scan_completed_counts(
        {
            "branch": "main",
            "files_seen": 42,
            "files_added": 5,
            "files_changed": 2,
            "files_removed": 1,
        },
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Scan completed." in output
    assert "Files seen: 42" in output
    assert "Files added: 5" in output
    assert "Files changed: 2" in output
    assert "Files removed: 1" in output


def test_emit_scan_completed_counts_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    payload = {"status": "done", "files_seen": 1}
    emit_scan_completed_counts(payload, json_mode=True)
    assert json.loads(capsys.readouterr().out) == payload
