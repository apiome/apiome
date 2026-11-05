"""The export pipeline for the MCP tools — MFX-40.1 (#4339).

``POST /v1/internal/mcp/export/targets`` and ``…/run`` against the real emitter registry and export job
engine (the source loader faked as in ``test_export_job_engine.py``):

* both routes are fail-closed behind ``X-Internal-Service-Token``;
* ``targets`` answers what ``GET /v1/export/{tenant}/targets`` does — every registered emitter;
* ``run`` exports to **any** registered target with no per-format code, answering with the structured
  fidelity report (tier, ``LossinessReport`` items, advisory), the guard and the files inline — or a
  download reference past the inline cap; a running job is collected with ``jobId``; unknown targets,
  invalid options, severe conversions without ``confirm`` and unknown tenants are refused or failed with
  their reasons;
* MFX-40.2 (#4340): a lossy conversion without ``allowLossy`` answers ``blocked`` with the report and the
  canonical advisory and emits nothing; every answer's ``advisory`` is ``ExportAdvisory.message`` verbatim.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

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
from app.emitter import get_emitter
from app.export_fidelity import build_export_fidelity
from app.export_job_engine import _jobs
from app.export_routes import build_target_fidelity_entries
from app.export_service import resolve_emit_format
from app.export_source import ExportSource, ExportSourceError
from app.main import app

client = TestClient(app)

TENANT = "550e8400-e29b-41d4-a716-446655440000"
TOKEN = "internal-token-0123456789"
HEADERS = {"X-Internal-Service-Token": TOKEN}


def _source() -> ExportSource:
    widget = Type(key="Widget", name="Widget", kind=TypeKind.RECORD,
                  fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))])
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="widgets"),
                       services=[Service(key="widgets", name="widgets", operations=[op])], types=[widget])
    return ExportSource(api=api, artifact_id="artifact-1", version_record_id="rev-uuid-1", version_label="1.0.0")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_token", TOKEN)
    _jobs.clear()
    with patch("app.mcp_export_routes.db.get_tenant_slug_by_id", return_value="acme"), \
            patch("app.export_job_engine.load_export_source", return_value=_source()), \
            patch("app.mcp_export_routes.load_export_source", return_value=_source()):
        yield
    _jobs.clear()


def _run(body: Dict[str, Any]) -> Any:
    return client.post("/v1/internal/mcp/export/run", json={"tenantId": TENANT, "waitSeconds": 30, **body},
                       headers=HEADERS)


def test_both_routes_are_fail_closed_behind_the_internal_token(monkeypatch) -> None:
    body = {"tenantId": TENANT, "artifact": "artifact-1"}
    assert client.post("/v1/internal/mcp/export/targets", json=body).status_code == 401
    assert client.post("/v1/internal/mcp/export/targets", json=body,
                       headers={"X-Internal-Service-Token": "wrong"}).status_code == 403
    monkeypatch.setattr(settings, "internal_service_token", None)
    assert client.post("/v1/internal/mcp/export/run", json=body, headers=HEADERS).status_code == 503


def test_targets_lists_what_the_public_targets_route_lists() -> None:
    response = client.post("/v1/internal/mcp/export/targets",
                           json={"tenantId": TENANT, "artifact": "artifact-1"}, headers=HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version_label"] == "1.0.0"
    keys = {entry["descriptor"]["key"] for entry in body["targets"]}
    # Exactly what GET /v1/export/{tenant}/targets lists for the same source.
    assert keys == {entry.descriptor.key for entry in build_target_fidelity_entries(_source().api)}
    assert len(keys) > 40
    assert all("tier" in entry["fidelity"] for entry in body["targets"])


def test_targets_refuses_an_unknown_source_or_tenant() -> None:
    with patch("app.mcp_export_routes.load_export_source", side_effect=ExportSourceError("no such artifact",
                                                                                         status_code=404)):
        response = client.post("/v1/internal/mcp/export/targets", json={"tenantId": TENANT, "artifact": "x"},
                               headers=HEADERS)
    assert response.status_code == 404
    with patch("app.mcp_export_routes.db.get_tenant_slug_by_id", return_value=None):
        response = client.post("/v1/internal/mcp/export/targets", json={"tenantId": TENANT, "artifact": "x"},
                               headers=HEADERS)
    assert response.status_code == 404 and response.json()["detail"]["code"] == "mcp-export-tenant-unknown"


@pytest.mark.parametrize("target", ["openapi", "graphql", "json-schema", "asyncapi"])
def test_any_registered_target_exports_with_its_fidelity_report(target: str) -> None:
    response = _run({"artifact": "artifact-1", "target": target, "confirm": True, "allowLossy": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "completed", body
    assert body["fidelity"]["summary"]["tier"] in ("lossless", "lossy", "types-only")
    assert isinstance(body["fidelity"]["report"]["items"], list)
    assert "advisory" in body["fidelity"]
    assert body["guard"]["verdict"]
    assert body["contentInline"] is True
    assert body["files"] and all(f["content"] for f in body["files"])
    assert body["downloadPath"].endswith(f"/jobs/{body['jobId']}/download")


def test_large_output_is_a_download_reference(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mcp_export_inline_max_bytes", 1)
    body = _run({"artifact": "artifact-1", "target": "openapi"}).json()
    assert body["state"] == "completed" and body["contentInline"] is False
    assert all(f["content"] is None and f["sizeBytes"] > 0 for f in body["files"])
    assert body["downloadPath"]


def test_a_running_job_is_collected_by_job_id() -> None:
    first = _run({"artifact": "artifact-1", "target": "openapi", "waitSeconds": 0}).json()
    assert first["state"] in ("queued", "running", "completed")
    collected = _run({"jobId": first["jobId"]})
    assert collected.status_code == 200 and collected.json()["state"] == "completed"
    assert _run({"jobId": "no-such-job"}).status_code == 404


def test_refusals() -> None:
    assert _run({"artifact": "artifact-1"}).status_code == 400
    unknown = _run({"artifact": "artifact-1", "target": "no-such-format"})
    assert unknown.status_code == 400 and "no-such-format" in unknown.json()["detail"]["message"]
    bad_options = _run({"artifact": "artifact-1", "target": "openapi", "options": {"bogus": 1}})
    assert bad_options.status_code == 422


def test_a_failed_source_answers_with_the_structured_error() -> None:
    with patch("app.export_job_engine.load_export_source", side_effect=ExportSourceError("gone", status_code=404)):
        body = _run({"artifact": "artifact-1", "target": "openapi"}).json()
    assert body["state"] == "failed"
    assert body["error"]["code"]


def _tier(target: str) -> str:
    return build_export_fidelity(_source().api, get_emitter(resolve_emit_format(target))).summary.tier.value


def _canonical_message(target: str) -> str:
    """The MFX-2.4 advisory string the UI, browse and the CLI render for this export."""
    return build_export_fidelity(_source().api, get_emitter(resolve_emit_format(target))).advisory.message


def test_a_lossy_conversion_without_allow_lossy_is_blocked_with_the_report_and_advisory() -> None:
    assert _tier("asyncapi") != "lossless"
    response = _run({"artifact": "artifact-1", "target": "asyncapi", "confirm": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "blocked"
    assert body["jobId"] is None and body["files"] == [] and body["downloadPath"] is None
    assert body["fidelity"]["summary"]["tier"] == _tier("asyncapi")
    assert body["fidelity"]["report"]["items"]
    assert body["advisory"] == body["fidelity"]["advisory"]["message"] == _canonical_message("asyncapi")
    assert body["error"]["code"] == "mcp-export-lossy-not-allowed"
    assert body["guard"]["verdict"]
    assert _jobs == {}  # nothing was scheduled, nothing emitted


def test_allow_lossy_exports_with_the_same_advisory() -> None:
    body = _run({"artifact": "artifact-1", "target": "asyncapi", "confirm": True, "allowLossy": True}).json()
    assert body["state"] == "completed" and body["files"]
    assert body["advisory"] == _canonical_message("asyncapi")


def test_a_lossless_conversion_needs_no_allow_lossy() -> None:
    assert _tier("openapi") == "lossless"
    body = _run({"artifact": "artifact-1", "target": "openapi"}).json()
    assert body["state"] == "completed" and body["files"]
    assert body["advisory"] == _canonical_message("openapi")


def test_the_preflight_refuses_an_unknown_source() -> None:
    with patch("app.mcp_export_routes.load_export_source", side_effect=ExportSourceError("gone", status_code=404)):
        response = _run({"artifact": "artifact-1", "target": "asyncapi"})
    assert response.status_code == 404
