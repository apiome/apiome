"""Tests for ``apiome mcp agent-invocations export`` (ATQ-4.5, #5847)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_BASE = "http://localhost:8000/v1/tenants/acme/agent-invocations/export"

#: Two JSON Lines records as the REST route streams them.
_RECORDS = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "tool_name": "listPets",
        "outcome": "success",
        "error_code": None,
        "key_name": "ci-agent",
        "key_fingerprint": "sha256:" + "ab" * 16,
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "tool_name": "listPets",
        "outcome": "upstream_error",
        "error_code": "upstream_timeout",
        "key_name": "ci-agent",
        "key_fingerprint": "sha256:" + "ab" * 16,
    },
]
_JSONL = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in _RECORDS)


@pytest.fixture
def mcp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """API key + base URL + slug tenant scope (no tenants/me round-trip)."""
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme")


def test_export_jsonl_to_stdout(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=f"{_BASE}?day=2026-11-14&format=jsonl", text=_JSONL)
    result = runner.invoke(
        app, ["mcp", "agent-invocations", "export", "--day", "2026-11-14"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == _JSONL
    assert [json.loads(line) for line in result.stdout.splitlines()] == _RECORDS


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_export_round_trips_into_jq(httpx_mock: object, mcp_env: None) -> None:
    httpx_mock.add_response(url=f"{_BASE}?day=2026-11-14&format=jsonl", text=_JSONL)
    result = runner.invoke(
        app, ["mcp", "agent-invocations", "export", "--day", "2026-11-14"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    piped = subprocess.run(
        ["jq", "-c", 'select(.outcome != "success") | {id, error_code}'],
        input=result.stdout,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(piped.stdout) == {
        "id": _RECORDS[1]["id"],
        "error_code": "upstream_timeout",
    }


def test_export_csv_to_file(httpx_mock: object, mcp_env: None, tmp_path: Path) -> None:
    body = "id,outcome\r\n00000000-0000-0000-0000-000000000001,success\r\n"
    httpx_mock.add_response(url=f"{_BASE}?day=2026-11-14&format=csv", text=body)
    target = tmp_path / "day.csv"
    result = runner.invoke(
        app,
        [
            "mcp",
            "agent-invocations",
            "export",
            "--day",
            "2026-11-14",
            "--format",
            "csv",
            "--out",
            str(target),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert target.read_bytes() == body.encode("utf-8")
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (
            409,
            "agent-invocations-day-not-final",
            "2026-11-16 is not final yet: … after 2026-11-17T06:00:00+00:00",
        ),
        (
            410,
            "agent-invocations-day-past-retention",
            "Agent invocations are kept for 7 days on this plan",
        ),
    ],
)
def test_refusals_print_the_code_and_message(
    httpx_mock: object, mcp_env: None, status: int, code: str, message: str
) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}?day=2026-11-16&format=jsonl",
        status_code=status,
        json={"detail": {"code": code, "message": message}},
    )
    result = runner.invoke(
        app, ["mcp", "agent-invocations", "export", "--day", "2026-11-16"]
    )
    assert result.exit_code == EXIT_USAGE
    assert f"HTTP {status} {code}: {message}" in result.output
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args",
    [
        ["--day", "14-11-2026"],
        ["--day", "2026-11-14", "--format", "ndjson"],
        [],
    ],
)
def test_bad_arguments_are_usage_errors(mcp_env: None, args: list[str]) -> None:
    result = runner.invoke(app, ["mcp", "agent-invocations", "export", *args])
    assert result.exit_code == EXIT_USAGE
