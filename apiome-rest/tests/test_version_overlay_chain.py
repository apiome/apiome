"""Stored overlay chain render path — GVM-4.3 (#5878).

Pins :mod:`app.version_overlay_chain` and its consumers:

* the stored chain applies in ``position`` order, before a request's inline overlays, and is
  labelled ``stored:<name>`` in the ledger;
* stored + inline overlays share the export cap;
* the export job and verify apply the stored chain by default and skip it with
  ``apply_stored_overlays: false``;
* **the preview equals the export with the same chain** (one shared code path);
* a stored overlay that no longer matches (after a Studio edit) is an ``overlay.unmatched-target``
  finding on the next render, never a silent no-op;
* the publish render fingerprints the source and the resolved document side by side, and records
  nothing for an empty chain.
"""

from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.export_job_engine import ExportJobStartRequest, _jobs, _load_job_source, schedule_export_job
from app.export_overlay import MAX_EXPORT_OVERLAYS, OVERLAY_INVALID, ExportOverlay, ExportOverlayError
from app.main import app
from app.version_overlay_chain import (
    StoredOverlay,
    document_fingerprint,
    render_for_publish,
    resolve_chain,
    stored_export_overlays,
)
from app.version_quality_capture import openapi_source_fingerprint
from tests.test_export_overlay import (
    _BASE,
    _PARTNER,
    _UNMATCHED,
    TENANT_ID,
    TENANT_SLUG,
    _openapi_source,
    _wait_terminal,
)

PROJECT_ID = "artifact-1"
REVISION_ID = "rev-uuid-1"

_DESCRIBE = {
    "overlay": "1.0.0",
    "info": {"title": "Curation", "version": "1"},
    "actions": [{"target": "$.paths['/widgets'].get", "update": {"description": "Lists every widget."}}],
}

_RETITLE = {
    "overlay": "1.0.0",
    "info": {"title": "Retitle", "version": "1"},
    "actions": [{"target": "$.info", "update": {"title": "Widgets (curated)"}}],
}


def _stored(position: int, name: str, document: dict, source: str = "manual") -> StoredOverlay:
    return StoredOverlay(
        id=f"ov-{position}",
        position=position,
        name=name,
        source=source,
        document=document,
        content_fingerprint=document_fingerprint(document),
    )


@pytest.fixture(autouse=True)
def _clear_export_jobs_between_tests():
    _jobs.clear()
    yield
    _jobs.clear()


def _with_chain(monkeypatch, chain: List[StoredOverlay]) -> List[tuple]:
    """Serve ``chain`` as every revision's stored chain; return the recorded reads."""
    calls: List[tuple] = []

    def _list(tenant_id, version_record_id):
        calls.append((tenant_id, version_record_id))
        return list(chain)

    monkeypatch.setattr("app.version_overlay_store.list_overlays", _list)
    return calls


# ---------------------------------------------------------------------------
# resolve_chain
# ---------------------------------------------------------------------------
def test_fingerprints_are_canonical_and_match_the_quality_fingerprint():
    assert document_fingerprint({"b": 1, "a": [1, 2]}) == document_fingerprint({"a": [1, 2], "b": 1})
    assert document_fingerprint(_BASE) == openapi_source_fingerprint(_BASE)
    assert document_fingerprint(_BASE).startswith("sha256:")


def test_the_stored_chain_applies_in_position_order_before_inline_overlays():
    later = {
        "overlay": "1.0.0",
        "info": {"title": "Later", "version": "1"},
        "actions": [{"target": "$.info", "update": {"title": "Second wins"}}],
    }
    stored = [_stored(1, "second", later), _stored(0, "first", _RETITLE)]
    source, report = resolve_chain(source=_openapi_source(), stored=stored)
    assert report.applied == ["stored:first", "stored:second"]
    assert source.api.raw["info"]["title"] == "Second wins"

    source, report = resolve_chain(
        _openapi_source(), stored, [ExportOverlay(name="inline.yaml", document=_PARTNER)]
    )
    assert report.applied == ["stored:first", "stored:second", "inline.yaml"]
    assert source.api.raw["info"]["title"] == "Widgets for Partners"
    assert {row.overlay for row in report.ledger if row.kind != "truncated"} >= {"stored:first", "inline.yaml"}


def test_an_empty_chain_leaves_the_source_alone():
    original = _openapi_source()
    source, report = resolve_chain(original, [])
    assert source is original
    assert report is None


def test_stored_and_inline_overlays_share_the_export_cap():
    stored = [_stored(i, f"s{i}", _RETITLE) for i in range(MAX_EXPORT_OVERLAYS)]
    with pytest.raises(ExportOverlayError) as exc:
        resolve_chain(_openapi_source(), stored, [ExportOverlay(name="one-more", document=_PARTNER)])
    assert exc.value.code == OVERLAY_INVALID
    assert "applyStoredOverlays" in str(exc.value) or "apply" in str(exc.value)


def test_a_hand_broken_stored_row_is_refused_not_skipped():
    with pytest.raises(ExportOverlayError) as exc:
        stored_export_overlays([_stored(0, "broken", {"info": {"title": "no marker"}})])
    assert exc.value.code == OVERLAY_INVALID


def test_a_stale_overlay_is_a_finding_on_the_next_render():
    """After a Studio edit removed `/gadgets`, the overlay targeting it reports, never no-ops."""
    source, report = resolve_chain(_openapi_source(), [_stored(0, "stale", _UNMATCHED)])
    assert [finding.rule for finding in report.findings] == ["overlay.unmatched-target"]
    assert report.findings[0].overlay == "stored:stale"
    assert source.api.raw["paths"] == _BASE["paths"]


# ---------------------------------------------------------------------------
# Publish render
# ---------------------------------------------------------------------------
def test_the_publish_render_records_source_and_resolved_fingerprints():
    stored = [_stored(0, "describe", _DESCRIBE)]
    render = render_for_publish(_openapi_source(), stored)
    assert render.source_fingerprint == document_fingerprint(_BASE)
    assert render.resolved_fingerprint != render.source_fingerprint
    resolved, _ = resolve_chain(_openapi_source(), stored)
    assert render.resolved_fingerprint == document_fingerprint(resolved.api.raw)
    assert render.overlay_fingerprints == [
        {
            "id": "ov-0",
            "name": "describe",
            "position": 0,
            "contentFingerprint": document_fingerprint(_DESCRIBE),
        }
    ]


def test_an_empty_chain_records_no_publish_render():
    assert render_for_publish(_openapi_source(), []) is None


def test_publish_render_is_recorded_through_the_store(monkeypatch):
    from app import version_overlay_store

    _with_chain(monkeypatch, [_stored(0, "describe", _DESCRIBE)])
    recorded = {}
    monkeypatch.setattr(version_overlay_store, "load_export_source", lambda *a: _openapi_source())
    monkeypatch.setattr(version_overlay_store, "record_render", lambda **kw: recorded.update(kw))
    render = version_overlay_store.render_chain_on_publish(
        tenant_id=TENANT_ID, project_id=PROJECT_ID, version_record_id=REVISION_ID, actor_id="u"
    )
    assert recorded["render"] is render
    assert recorded["version_record_id"] == REVISION_ID
    assert render.source_fingerprint == document_fingerprint(_BASE)


def test_a_failed_publish_render_is_audited_and_never_raises(monkeypatch):
    from app import version_overlay_store

    _with_chain(monkeypatch, [_stored(0, "describe", _DESCRIBE)])
    audits = []

    def _fail(*_a):
        raise ExportOverlayError("nope", code=OVERLAY_INVALID)

    monkeypatch.setattr(version_overlay_store, "load_export_source", _fail)
    monkeypatch.setattr(version_overlay_store.db, "insert_workflow_audit", lambda *a: audits.append(a))
    assert (
        version_overlay_store.render_chain_on_publish(
            tenant_id=TENANT_ID, project_id=PROJECT_ID, version_record_id=REVISION_ID, actor_id="u"
        )
        is None
    )
    assert audits[0][3:5] == ("version.overlay_rendered", "failure")


# ---------------------------------------------------------------------------
# Export job / verify
# ---------------------------------------------------------------------------
async def test_an_export_job_applies_the_stored_chain_by_default(monkeypatch):
    calls = _with_chain(monkeypatch, [_stored(0, "retitle", _RETITLE)])
    request = ExportJobStartRequest(artifact=PROJECT_ID, target="openapi")
    with patch("app.export_job_engine.load_export_source", return_value=_openapi_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)
    assert status["state"] == "completed", status["error"]
    assert status["result"]["overlay"]["applied"] == ["stored:retitle"]
    assert calls == [(TENANT_ID, REVISION_ID)]


async def test_an_export_job_can_opt_out_of_the_stored_chain(monkeypatch):
    calls = _with_chain(monkeypatch, [_stored(0, "retitle", _RETITLE)])
    request = ExportJobStartRequest(artifact=PROJECT_ID, target="openapi", apply_stored_overlays=False)
    with patch("app.export_job_engine.load_export_source", return_value=_openapi_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)
    assert status["state"] == "completed", status["error"]
    assert status["result"]["overlay"] is None
    assert calls == []


def _client() -> TestClient:
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT_ID,
        "user_id": "u",
        "auth_method": "jwt",
    }
    return TestClient(app)


def test_verify_applies_the_stored_chain_and_can_skip_it(monkeypatch):
    _with_chain(monkeypatch, [_stored(0, "retitle", _RETITLE)])
    client = _client()
    try:
        with patch("app.export_routes.load_export_source", return_value=_openapi_source()):
            on = client.post(f"/v1/export/{TENANT_SLUG}/verify", json={"artifact": PROJECT_ID, "target": "openapi"})
            off = client.post(
                f"/v1/export/{TENANT_SLUG}/verify",
                json={"artifact": PROJECT_ID, "target": "openapi", "apply_stored_overlays": False},
            )
    finally:
        app.dependency_overrides.clear()
    assert on.status_code == 200, on.text
    assert on.json()["overlay"]["applied"] == ["stored:retitle"]
    assert off.json()["overlay"] is None


async def test_the_preview_equals_the_export_with_the_same_chain(monkeypatch):
    """One shared path: the preview's document and report are what the export job renders."""
    _with_chain(monkeypatch, [_stored(0, "describe", _DESCRIBE), _stored(1, "stale", _UNMATCHED)])
    monkeypatch.setattr(
        "app.version_overlay_routes.db.get_version_by_id",
        lambda version_id, tenant_id: {"id": version_id, "project_id": PROJECT_ID, "published": False},
    )
    client = _client()
    try:
        with patch("app.version_overlay_routes.load_export_source", return_value=_openapi_source()):
            preview = await asyncio.to_thread(
                client.get, f"/v1/versions/{TENANT_SLUG}/{PROJECT_ID}/{REVISION_ID}/overlays/preview"
            )
    finally:
        app.dependency_overrides.clear()
    assert preview.status_code == 200, preview.text
    body = preview.json()

    request = ExportJobStartRequest(artifact=PROJECT_ID, version=REVISION_ID, target="openapi")
    with patch("app.export_job_engine.load_export_source", return_value=_openapi_source()):
        exported, report = await _load_job_source("job-1", request, TENANT_ID)

    assert body["document"] == exported.api.raw
    assert body["report"] == report.model_dump()
    assert body["resolved_fingerprint"] == document_fingerprint(exported.api.raw)
    assert body["source_fingerprint"] == document_fingerprint(_BASE)
    assert [f["rule"] for f in body["report"]["findings"]] == ["overlay.unmatched-target"]
