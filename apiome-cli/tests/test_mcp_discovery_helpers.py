"""Tests for the ``mcp discover`` trigger/poll helpers."""

from __future__ import annotations

import json

import pytest
import typer

from apiome_cli.client.http import RestClient
from apiome_cli.client.mcp_discovery import (
    _failure_detail,
    emit_discovery_completed,
    emit_discovery_enqueue_result,
    format_discovery_progress,
    wait_for_discovery_job,
)
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_ERROR

from helpers import strip_ansi

_TENANT_SLUG = "acme"
_ENDPOINT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_JOB_URL = (
    f"http://localhost:8000/v1/mcp/{_TENANT_SLUG}/endpoints/{_ENDPOINT_ID}/jobs/{_JOB_ID}"
)


def _envelope(state: str, **extra: object) -> dict[str, object]:
    job: dict[str, object] = {
        "job_id": _JOB_ID,
        "endpoint_id": _ENDPOINT_ID,
        "tenant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "state": state,
        "trigger": "manual",
        "terminal": state in ("completed", "failed"),
        "result": {},
    }
    job.update(extra)
    return {"success": True, "job": job}


def test_format_discovery_progress_message() -> None:
    assert format_discovery_progress("running", elapsed_seconds=7.9) == "Discovery running… (7s)"


def test_failure_detail_prefers_error_summary() -> None:
    assert _failure_detail({"error": " handshake refused "}) == "handshake refused"


def test_failure_detail_falls_back_to_error_code() -> None:
    assert _failure_detail({"error_detail": {"code": "RATE_LIMITED"}}) == "RATE_LIMITED"


def test_failure_detail_none_when_empty() -> None:
    assert _failure_detail({}) is None


def test_wait_for_discovery_job_returns_completed_snapshot(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_JOB_URL, json=_envelope("running"))
    httpx_mock.add_response(
        url=_JOB_URL,
        json=_envelope("completed", version_id=_VERSION_ID, changed=True),
    )
    client = RestClient(CliSettings(), timeout=30.0)
    job = wait_for_discovery_job(
        client,
        _TENANT_SLUG,
        _ENDPOINT_ID,
        _JOB_ID,
        poll_interval=0.01,
        timeout=5.0,
        no_progress=True,
        sleep=lambda _seconds: None,
    )
    assert job["state"] == "completed"
    assert job["version_id"] == _VERSION_ID


def test_wait_for_discovery_job_exits_on_failed(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=_JOB_URL,
        json=_envelope("failed", error="boom"),
    )
    client = RestClient(CliSettings(), timeout=30.0)
    with pytest.raises(typer.Exit) as exc_info:
        wait_for_discovery_job(
            client,
            _TENANT_SLUG,
            _ENDPOINT_ID,
            _JOB_ID,
            poll_interval=0.01,
            timeout=5.0,
            no_progress=True,
            sleep=lambda _seconds: None,
        )
    assert exc_info.value.exit_code == EXIT_ERROR


def test_wait_for_discovery_job_times_out(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_JOB_URL, json=_envelope("running"), is_reusable=True)
    client = RestClient(CliSettings(), timeout=30.0)
    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds + 10.0

    with pytest.raises(typer.Exit) as exc_info:
        wait_for_discovery_job(
            client,
            _TENANT_SLUG,
            _ENDPOINT_ID,
            _JOB_ID,
            poll_interval=0.01,
            timeout=1.0,
            no_progress=True,
            sleep=fake_sleep,
            monotonic=fake_monotonic,
        )
    assert exc_info.value.exit_code == EXIT_ERROR


def test_emit_discovery_enqueue_result_human(capsys: pytest.CaptureFixture[str]) -> None:
    emit_discovery_enqueue_result(
        {
            "deduplicated": False,
            "job": {"id": _JOB_ID, "endpoint_id": _ENDPOINT_ID, "state": "queued"},
        },
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Discovery enqueued." in output
    assert _JOB_ID in output
    assert "queued" in output


def test_emit_discovery_enqueue_result_json(capsys: pytest.CaptureFixture[str]) -> None:
    payload = {"deduplicated": True, "job": {"id": _JOB_ID}}
    emit_discovery_enqueue_result(payload, json_mode=True)
    assert json.loads(capsys.readouterr().out) == payload


def test_emit_discovery_completed_human_with_score(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_discovery_completed(
        {
            "endpoint_id": _ENDPOINT_ID,
            "version_id": _VERSION_ID,
            "changed": True,
            "duration_ms": 1500,
            "result": {"version_seq": 4, "version_tag": "2026-06-28", "change_count": 1},
        },
        deduplicated=False,
        lint={"score": 91, "grade": "A"},
        json_mode=False,
    )
    output = strip_ansi(capsys.readouterr().out)
    assert "Discovery completed." in output
    assert _VERSION_ID in output
    assert "seq 4" in output
    assert "Changed: yes (1 change)" in output
    assert "Duration: 1500 ms" in output
    assert "Score: 91 (grade A)" in output


def test_emit_discovery_completed_json(capsys: pytest.CaptureFixture[str]) -> None:
    job = {"version_id": _VERSION_ID, "changed": False, "result": {}}
    emit_discovery_completed(job, deduplicated=True, lint=None, json_mode=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"deduplicated": True, "job": job, "lint": None}
