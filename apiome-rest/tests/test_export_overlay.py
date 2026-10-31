"""Overlays on export — GVM-4.2 (#5877).

Pins the export overlay seam end to end:

* :func:`app.export_overlay.apply_export_overlays` applies the chain, in order, to the source's
  OpenAPI document and rebuilds the canonical model through the source's own adapter;
* the report carries one ledger row per changed leaf (with the overlay's label), a declared
  truncation row at the 500-row cap, and an ``overlay.unmatched-target`` finding for an action
  that matches nothing — which leaves the document untouched;
* a non-OpenAPI source and an unreadable overlay are refused with stable codes;
* the request models bound the input (marker, size, count, no batch);
* an export job emits the post-overlay document, publishes the overlay events, and its delivery
  gate — the export quality policy, recorded as a ``quality_rank_observations`` row with scope
  ``export`` — judges the post-overlay model;
* ``POST /export/verify`` applies the same chain and reports the same snapshot the job computes.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.export_delivery_gate import lint_delivery_source
from app.export_job_engine import (
    ExportJobStartRequest,
    _jobs,
    get_export_job_emit_result,
    get_export_job_status,
    schedule_export_job,
)
from app.export_overlay import (
    MAX_EXPORT_OVERLAY_BYTES,
    OVERLAY_INVALID,
    OVERLAY_SOURCE_UNSUPPORTED,
    ExportOverlay,
    ExportOverlayError,
    apply_export_overlays,
    overlay_events,
)
from app.export_source import ExportSource
from app.main import app
from app.openapi_import_source import OpenApiImportSource
from app.openapi_overlay import MAX_PROVENANCE_RECORDS

TENANT_SLUG = "acme"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"

_BASE = {
    "openapi": "3.1.0",
    "info": {"title": "Widgets", "version": "1.0.0", "description": "Internal widgets API."},
    "servers": [{"url": "https://internal.example.com"}],
    "paths": {
        "/widgets": {
            "get": {
                "operationId": "listWidgets",
                "summary": "List widgets",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}

_PARTNER = {
    "overlay": "1.0.0",
    "info": {"title": "Partner edition", "version": "1.0.0"},
    "actions": [
        {"target": "$.info", "update": {"title": "Widgets for Partners"}},
        {"target": "$.paths['/widgets'].get", "update": {"x-partner": True}},
    ],
}

_UNMATCHED = {
    "overlay": "1.0.0",
    "info": {"title": "Misses", "version": "1.0.0"},
    "actions": [{"target": "$.paths['/gadgets'].get", "update": {"summary": "Never applied"}}],
}


@pytest.fixture(autouse=True)
def _clear_export_jobs_between_tests():
    _jobs.clear()
    yield
    _jobs.clear()


def _openapi_source(document: dict | None = None) -> ExportSource:
    """An export source built the way the loader builds one: parse + normalize through the adapter."""
    text = json.dumps(document or _BASE)
    adapter = OpenApiImportSource()
    api = adapter.normalize(adapter.parse(text))
    return ExportSource(
        api=api,
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
        source_text=text,
        source_format="openapi",
    )


def _overlay(name: str, document: dict) -> ExportOverlay:
    return ExportOverlay(name=name, document=document)


async def _wait_terminal(job_id: str) -> dict:
    """Poll the engine until the job is terminal; every scheduled job must drain through here."""
    for _ in range(500):
        status = await get_export_job_status(TENANT_SLUG, job_id)
        if status.state in ("completed", "failed", "canceled"):
            return status.model_dump()
        await asyncio.sleep(0.01)
    raise AssertionError("export job did not reach a terminal state")


# ---------------------------------------------------------------------------
# apply_export_overlays
# ---------------------------------------------------------------------------
def test_no_overlays_returns_the_source_unchanged():
    source = _openapi_source()
    same, report = apply_export_overlays(source, None)
    assert same is source and report is None
    assert apply_export_overlays(source, [])[1] is None


def test_overlays_rebuild_the_canonical_model_and_list_every_changed_leaf():
    source = _openapi_source()
    overlaid, report = apply_export_overlays(source, [_overlay("partner.yaml", _PARTNER)])

    assert overlaid.api.identity.name == "Widgets for Partners"
    assert source.api.identity.name == "Widgets"  # the loaded source is never mutated
    assert overlaid.api.raw["paths"]["/widgets"]["get"]["x-partner"] is True
    # Coordinates and captured text are the source's own.
    assert overlaid.version_record_id == "rev-uuid-1" and overlaid.source_text == source.source_text

    assert report.applied == ["partner.yaml"]
    assert report.findings == []
    assert report.truncated is False and report.changes == 2
    pointers = {(row.pointer, row.kind, row.overlay) for row in report.ledger}
    assert pointers == {
        ("/info/title", "replaced", "partner.yaml"),
        ("/paths/~1widgets/get/x-partner", "set", "partner.yaml"),
    }
    assert all("partner.yaml" in row.detail for row in report.ledger)
    # The export's own overlays ride on the report, never on the model's extras.
    assert "overlay" not in overlaid.api.extras


def test_overlays_apply_in_the_order_given():
    later = {
        "overlay": "1.0.0",
        "info": {"title": "Later", "version": "1"},
        "actions": [{"target": "$.info", "update": {"title": "Last writer"}}],
    }
    overlaid, report = apply_export_overlays(
        _openapi_source(), [_overlay("first", _PARTNER), _overlay("second", later)]
    )
    assert overlaid.api.identity.name == "Last writer"
    assert report.applied == ["first", "second"]
    title_rows = [row.overlay for row in report.ledger if row.pointer == "/info/title"]
    assert title_rows == ["first", "second"]


def test_an_unmatched_target_is_a_finding_and_leaves_the_document_untouched():
    source = _openapi_source()
    overlaid, report = apply_export_overlays(source, [_overlay("misses.yaml", _UNMATCHED)])

    assert overlaid.api.raw == source.api.raw
    assert overlaid.api.model_dump(exclude={"raw"}) == source.api.model_dump(exclude={"raw"})
    assert report.ledger == [] and report.changes == 0
    [finding] = report.findings
    assert finding.rule == "overlay.unmatched-target"
    assert finding.severity == "warning"
    assert finding.overlay == "misses.yaml" and finding.action_index == 0
    assert finding.target == "$.paths['/gadgets'].get"


def test_the_ledger_declares_truncation_at_the_cap():
    paths = {
        f"/w{i}": {"get": {"operationId": f"op{i}", "responses": {"200": {"description": "OK"}}}}
        for i in range(MAX_PROVENANCE_RECORDS + 5)
    }
    base = {**_BASE, "paths": paths}
    wide = {
        "overlay": "1.0.0",
        "info": {"title": "Wide", "version": "1"},
        "actions": [{"target": "$.paths.*.get", "update": {"x-tier": "gold"}}],
    }
    _, report = apply_export_overlays(_openapi_source(base), [_overlay("wide", wide)])

    assert report.truncated is True
    assert report.changes == MAX_PROVENANCE_RECORDS + 5
    assert len(report.ledger) == MAX_PROVENANCE_RECORDS + 1
    last = report.ledger[-1]
    assert last.kind == "truncated" and last.pointer == "(truncated)" and last.overlay is None
    assert str(MAX_PROVENANCE_RECORDS + 5) in last.detail


def test_a_source_not_built_from_openapi_is_refused():
    api = CanonicalApi(paradigm=ApiParadigm.GRAPH, format="graphql", identity=ApiIdentity(name="g"))
    source = ExportSource(api=api, artifact_id="a", version_record_id="r", source_format="graphql")
    with pytest.raises(ExportOverlayError) as exc:
        apply_export_overlays(source, [_overlay("partner", _PARTNER)])
    assert exc.value.code == OVERLAY_SOURCE_UNSUPPORTED
    assert exc.value.status_code == 422
    assert exc.value.http_detail()["code"] == OVERLAY_SOURCE_UNSUPPORTED


def test_an_unreadable_overlay_revision_is_refused():
    future = {**_PARTNER, "overlay": "1.3.0"}
    with pytest.raises(ExportOverlayError) as exc:
        apply_export_overlays(_openapi_source(), [_overlay("future", future)])
    assert exc.value.code == OVERLAY_INVALID
    assert "1.3.0" in str(exc.value)


def test_overlay_events_summarize_and_warn_per_finding():
    _, report = apply_export_overlays(
        _openapi_source(), [_overlay("partner", _PARTNER), _overlay("misses", _UNMATCHED)]
    )
    events = overlay_events(report)
    assert [(level, code) for level, code, _, _ in events] == [
        ("info", "OVERLAYS_APPLIED"),
        ("warn", "OVERLAY_FINDING"),
    ]
    assert events[1][3]["rule"] == "overlay.unmatched-target"
    assert overlay_events(None) == []


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
def test_export_overlay_requires_an_overlay_marker_and_a_name():
    with pytest.raises(ValueError, match="not an Overlay document"):
        ExportOverlay(name="base", document=_BASE)
    with pytest.raises(ValueError, match="non-blank"):
        ExportOverlay(name="   ", document=_PARTNER)
    assert ExportOverlay(name="  partner.yaml ", document=_PARTNER).name == "partner.yaml"


def test_export_overlay_is_size_capped():
    huge = {**_PARTNER, "info": {"title": "x" * MAX_EXPORT_OVERLAY_BYTES, "version": "1"}}
    with pytest.raises(ValueError, match="at most"):
        ExportOverlay(name="huge", document=huge)


def test_job_request_refuses_overlays_on_a_batch_export():
    overlay = {"name": "partner", "document": _PARTNER}
    with pytest.raises(ValueError, match="batch export"):
        ExportJobStartRequest(items=[{"artifact": "a"}], target="openapi", overlays=[overlay])
    with pytest.raises(ValueError, match="batch export"):
        ExportJobStartRequest(artifact="a", versions=["1", "2"], target="openapi", overlays=[overlay])
    with pytest.raises(ValueError):
        ExportJobStartRequest(artifact="a", target="openapi", overlays=[overlay] * 11)
    assert ExportJobStartRequest(artifact="a", target="openapi", overlays=[overlay]).overlays


# ---------------------------------------------------------------------------
# The export job
# ---------------------------------------------------------------------------
async def test_a_job_emits_the_post_overlay_document_and_reports_the_ledger():
    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="openapi",
        overlays=[{"name": "partner.yaml", "document": _PARTNER}],
    )
    with patch("app.export_job_engine.load_export_source", return_value=_openapi_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "completed", status["error"]
    overlay = status["result"]["overlay"]
    assert overlay["applied"] == ["partner.yaml"]
    assert {row["pointer"] for row in overlay["ledger"]} == {
        "/info/title",
        "/paths/~1widgets/get/x-partner",
    }
    codes = [event["code"] for event in status["events"]]
    assert codes.index("SOURCE_LOADED") < codes.index("OVERLAYS_APPLIED") < codes.index("FIDELITY_COMPUTED")

    emitted = get_export_job_emit_result(TENANT_SLUG, accepted.job_id).files[0].content
    assert emitted["info"]["title"] == "Widgets for Partners"


async def test_an_unmatched_overlay_exports_the_untouched_document_with_a_finding():
    async def run(overlays):
        request = ExportJobStartRequest(artifact="artifact-1", target="openapi", overlays=overlays)
        with patch("app.export_job_engine.load_export_source", return_value=_openapi_source()):
            accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
            status = await _wait_terminal(accepted.job_id)
        return status, get_export_job_emit_result(TENANT_SLUG, accepted.job_id)

    plain, plain_emit = await run(None)
    missed, missed_emit = await run([{"name": "misses.yaml", "document": _UNMATCHED}])

    assert missed["state"] == "completed"
    assert missed_emit.files[0].content == plain_emit.files[0].content
    assert missed["result"]["snapshot_hash"] == plain["result"]["snapshot_hash"]
    [finding] = missed["result"]["overlay"]["findings"]
    assert finding["rule"] == "overlay.unmatched-target"
    warn = [e for e in missed["events"] if e["code"] == "OVERLAY_FINDING"]
    assert warn and warn[0]["level"] == "warn"
    assert plain["result"]["overlay"] is None


async def test_the_export_quality_policy_judges_the_post_overlay_document():
    """The delivery gate lints the post-overlay model, and that lint is the observation recorded."""
    linted = []
    observed = []

    def spy_lint(api, **kwargs):
        linted.append(api)
        return lint_delivery_source(api, **kwargs)

    def spy_observe(decision, **kwargs):
        observed.append(kwargs)
        return None

    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="openapi",
        overlays=[{"name": "partner.yaml", "document": _PARTNER}],
    )
    with (
        patch("app.export_job_engine.load_export_source", return_value=_openapi_source()),
        patch("app.export_job_engine.lint_delivery_source", side_effect=spy_lint),
        patch("app.export_job_engine.observe_delivery", side_effect=spy_observe),
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "completed", status["error"]
    [api] = linted
    assert api.identity.name == "Widgets for Partners"
    [observation] = observed
    assert observation["lint"].report_fingerprint == lint_delivery_source(
        api, tenant_id=TENANT_ID, project_id="artifact-1"
    ).report_fingerprint


async def test_a_job_over_a_non_openapi_source_fails_with_the_overlay_code():
    api = CanonicalApi(paradigm=ApiParadigm.GRAPH, format="graphql", identity=ApiIdentity(name="g"))
    source = ExportSource(api=api, artifact_id="artifact-1", version_record_id="r", source_format="graphql")
    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="graphql",
        overlays=[{"name": "partner", "document": _PARTNER}],
    )
    with patch("app.export_job_engine.load_export_source", return_value=source):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == OVERLAY_SOURCE_UNSUPPORTED


async def test_a_multi_target_job_applies_overlays_once_for_every_target():
    request = ExportJobStartRequest(
        artifact="artifact-1",
        targets=[{"target": "openapi"}, {"target": "avro"}],
        dry_run=True,
        overlays=[{"name": "partner.yaml", "document": _PARTNER}],
    )
    with patch("app.export_job_engine.load_export_source", return_value=_openapi_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "completed", status["error"]
    assert status["result"]["overlay"]["applied"] == ["partner.yaml"]
    assert [e["code"] for e in status["events"]].count("OVERLAYS_APPLIED") == 1


# ---------------------------------------------------------------------------
# POST /export/verify
# ---------------------------------------------------------------------------
def _verify(body: dict):
    client = TestClient(app)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT_ID,
        "user_id": "u",
        "auth_method": "jwt",
    }
    try:
        with patch("app.export_routes.load_export_source", return_value=_openapi_source()):
            return client.post(f"/v1/export/{TENANT_SLUG}/verify", json=body)
    finally:
        app.dependency_overrides.clear()


async def test_verify_applies_overlays_and_matches_the_job_snapshot():
    overlays = [{"name": "partner.yaml", "document": _PARTNER}]
    response = await asyncio.to_thread(
        _verify, {"artifact": "artifact-1", "target": "openapi", "overlays": overlays}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overlay"]["applied"] == ["partner.yaml"]
    assert body["files"][0]["content"]["info"]["title"] == "Widgets for Partners"

    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="openapi",
        overlays=overlays,
        acknowledged_snapshot=body["fidelity"]["projection"]["manifest_hash"],
    )
    with patch("app.export_job_engine.load_export_source", return_value=_openapi_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)
    assert status["state"] == "completed", status["error"]


def test_verify_without_overlays_reports_no_overlay():
    response = _verify({"artifact": "artifact-1", "target": "openapi"})
    assert response.status_code == 200
    assert response.json()["overlay"] is None


def test_verify_refuses_an_unreadable_overlay_with_its_code():
    future = {**_PARTNER, "overlay": "2.0.0"}
    response = _verify(
        {"artifact": "artifact-1", "target": "openapi", "overlays": [{"name": "f", "document": future}]}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == OVERLAY_INVALID
