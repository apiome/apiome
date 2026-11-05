"""Endpoint tests for the toolchain check console — MFX-44.6 (#4372).

Pins the contract Export Studio's **Toolchain checks** tab depends on:

* ``POST /v1/export/{tenant}/verify/tool-checks/{tool}`` streams NDJSON: ``start``, ``output`` per
  chunk, and a closing ``result`` with the exit status;
* the artifact is the source **re-emitted server-side** (looked up within the caller's tenant) or a
  completed job's artifact of the same target — never bytes from the browser;
* only a check the target's registry entry declares can run (``404`` otherwise), and one whose tool
  is not installed answers ``503`` with the registry's reason (the conftest pins every tool as not
  installed; tests that need one installed patch the same seam);
* runs are rate-limited per user (``429`` with ``Retry-After``).

The source loader is faked; the emitter runs for real. ``run_tool_check`` is faked except in the
``buf`` acceptance test, which runs where the binary is installed.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from app import export_tool_check_routes
from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.config import settings
from app.export_job_engine import ExportDownloadArtifact
from app.export_source import ExportSource, ExportSourceError
from app.export_tool_checks import ExportToolCheckResult, ToolCheckStatus
from app.main import app
from app.rate_limit import FixedWindowRateLimiter
from fastapi import HTTPException
from fastapi.testclient import TestClient

client = TestClient(app)

TENANT = "acme"
TENANT_ID = "tenant-1"
URL = f"/v1/export/{TENANT}/verify/tool-checks"
BODY = {"artifact": "artifact-1", "target": "protobuf", "check": "lint"}

_AUTH = {"tenant_id": TENANT_ID, "user_id": "user-1", "auth_method": "jwt"}


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    """Authenticate as one tenant and give every test a fresh rate-limit budget."""
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    monkeypatch.setattr(export_tool_check_routes, "_tool_check_limiter", FixedWindowRateLimiter())
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def installed():
    """Report every toolchain as installed (the conftest default is not installed)."""
    with patch("app.export_test_tools._tool_installed", return_value=True):
        yield


def _source() -> ExportSource:
    """A loaded source: one RPC over one record type."""
    widget = Type(key="Widget", name="Widget", kind=TypeKind.RECORD,
                  fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))])
    op = Operation(key="GetWidget", name="GetWidget", kind=OperationKind.QUERY)
    api = CanonicalApi(paradigm=ApiParadigm.RPC, format="proto3", identity=ApiIdentity(name="widgets"),
                       services=[Service(key="Widgets", name="Widgets", operations=[op])], types=[widget])
    return ExportSource(api=api, artifact_id="artifact-1", version_record_id="rev-1", version_label="1.0.0")


def _events(response) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


async def _fake_check(command, files, *, label, on_event, runner=None, timeout=None):
    """Stand-in for the toolchain: one start, one output chunk, a failed result."""
    on_event({"event": "start", "tool": command.tool, "check": command.check, "label": label,
              "command": "buf lint", "files": sorted(files)})
    on_event({"event": "output", "stream": "stdout", "text": "widgets.proto:1:1:finding\n"})
    return ExportToolCheckResult(tool=command.tool, check=command.check, label=label,
                                 status=ToolCheckStatus.FAILED, exit_code=100, command="buf lint",
                                 files=sorted(files), message="buf lint exited 100.")


def test_streams_start_output_and_result_from_a_server_side_emit(installed):
    with patch("app.export_tool_check_routes.load_export_source", return_value=_source()) as load, \
            patch("app.export_tool_check_routes.run_tool_check", side_effect=_fake_check) as run:
        response = client.post(f"{URL}/buf", json=BODY)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = _events(response)
    assert [e["event"] for e in events] == ["start", "output", "result"]
    assert events[-1]["status"] == "failed" and events[-1]["exit_code"] == 100
    # Tenant-scoped: the source is loaded within the caller's tenant, then re-emitted here.
    load.assert_called_once_with(TENANT_ID, "artifact-1", None)
    staged = run.call_args.args[1]
    assert any(path.endswith(".proto") for path in staged)
    assert run.call_args.kwargs["label"] == "buf lint"


def test_an_unexpected_failure_still_closes_the_stream_with_a_result(installed):
    with patch("app.export_tool_check_routes.load_export_source", return_value=_source()), \
            patch("app.export_tool_check_routes.run_tool_check", AsyncMock(side_effect=RuntimeError("boom"))):
        response = client.post(f"{URL}/buf", json=BODY)
    events = _events(response)
    assert events[-1]["event"] == "result" and events[-1]["status"] == "error"
    assert "boom" in events[-1]["message"]


def test_missing_tool_is_503_with_the_registry_reason():
    # The conftest pins every toolchain as not installed.
    response = client.post(f"{URL}/buf", json=BODY)
    assert response.status_code == 503
    assert response.json()["detail"] == "The buf toolchain is not installed on this server."


def test_a_check_the_target_does_not_declare_is_404(installed):
    response = client.post(f"{URL}/buf", json={**BODY, "check": "breaking"})
    assert response.status_code == 404
    assert "does not declare a buf breaking check" in response.json()["detail"]
    # A real check of another target is not this target's either.
    response = client.post(f"{URL}/tsp", json={**BODY, "check": "compile"})
    assert response.status_code == 404


def test_unknown_target_is_refused(installed):
    response = client.post(f"{URL}/buf", json={**BODY, "target": "no-such-target"})
    assert 400 <= response.status_code < 500


def test_a_declared_check_without_a_command_is_422(installed):
    with patch("app.export_tool_check_routes.tool_check_command", return_value=None):
        response = client.post(f"{URL}/buf", json=BODY)
    assert response.status_code == 422


def test_source_errors_keep_their_status(installed):
    with patch("app.export_tool_check_routes.load_export_source",
               side_effect=ExportSourceError("Artifact not found", status_code=404)):
        response = client.post(f"{URL}/buf", json=BODY)
    assert response.status_code == 404


def test_runs_are_rate_limited_per_user(installed, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "export_tool_check_rate_limit_per_minute", 1)
    with patch("app.export_tool_check_routes.load_export_source", return_value=_source()), \
            patch("app.export_tool_check_routes.run_tool_check", side_effect=_fake_check):
        assert client.post(f"{URL}/buf", json=BODY).status_code == 200
        refused = client.post(f"{URL}/buf", json=BODY)
    assert refused.status_code == 429
    # (The global middleware stamps its own ``X-RateLimit-*`` on every response; ``Retry-After`` is ours.)
    assert "Retry-After" in refused.headers
    assert "Too many toolchain checks" in json.dumps(refused.json())


def _completed(target: str = "proto3"):
    status = AsyncMock()
    status.return_value.state = "completed"
    status.return_value.result.target = target
    return status


def test_checks_a_completed_jobs_artifact(installed):
    download = ExportDownloadArtifact(filename="widgets.proto", media_type="text/plain",
                                      body='syntax = "proto3";\n', content_sha256="sha256:0")
    with patch("app.export_job_engine.get_export_job_status", _completed()) as status, \
            patch("app.export_job_engine.resolve_export_download", return_value=download) as resolve, \
            patch("app.export_tool_check_routes.load_export_source") as load, \
            patch("app.export_tool_check_routes.run_tool_check", side_effect=_fake_check) as run:
        response = client.post(f"{URL}/buf", json={**BODY, "jobId": "job-1"})

    assert response.status_code == 200
    status.assert_awaited_once_with(TENANT, "job-1")
    resolve.assert_called_once_with(TENANT, "job-1")
    load.assert_not_called()  # the job's own bytes, no re-emit
    assert run.call_args.args[1] == {"widgets.proto": 'syntax = "proto3";\n'}


def test_a_job_of_another_target_is_409(installed):
    with patch("app.export_job_engine.get_export_job_status", _completed("openapi-3.1")):
        response = client.post(f"{URL}/buf", json={**BODY, "jobId": "job-1"})
    assert response.status_code == 409


def test_another_tenants_job_is_404(installed):
    unknown = AsyncMock(side_effect=HTTPException(status_code=404, detail="Export job not found"))
    with patch("app.export_job_engine.get_export_job_status", unknown):
        response = client.post(f"{URL}/buf", json={**BODY, "jobId": "job-of-someone-else"})
    assert response.status_code == 404


def test_extra_body_fields_are_rejected(installed):
    response = client.post(f"{URL}/buf", json={**BODY, "files": {"evil.proto": "x"}})
    assert response.status_code == 422


def _buf_installed() -> bool:
    from app.toolchain_packaging import register_bundled_tools
    from app.toolchain_runner import is_tool_available

    register_bundled_tools()
    return is_tool_available("buf")


@pytest.mark.skipif(not _buf_installed(), reason="buf is not installed in this runtime")
def test_buf_lint_on_an_emitted_proto_bundle_streams_and_reports_exit_status(installed):
    """The acceptance case, end to end: re-emit → stage → ``buf lint`` → NDJSON console."""
    with patch("app.export_tool_check_routes.load_export_source", return_value=_source()):
        response = client.post(f"{URL}/buf", json=BODY)
    assert response.status_code == 200
    events = _events(response)
    assert events[0]["event"] == "start" and events[0]["command"] == "buf lint"
    result = events[-1]
    assert result["event"] == "result"
    assert result["status"] in {"passed", "failed"}
    assert isinstance(result["exit_code"], int)
    if result["status"] == "failed":
        assert any(e["event"] == "output" for e in events)
