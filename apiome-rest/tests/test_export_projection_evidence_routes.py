"""Endpoint + job tests for the projection-evidence surface — EFP-2.1 (#4813).

Pins the ticket's acceptance criteria:

* **one snapshot across surfaces** — a preview, a verify, and an evidence request with
  matching source, target, and *options* resolve to the same snapshot hash (options are
  now part of the preview contract), while a different option set is a different snapshot;
* **bounded, cursor-paginated, tenant-scoped evidence** — the endpoint pages the manifest's
  outcome edges deterministically, clamps oversized limits to the hard cap, rejects a
  malformed cursor with 422 and an unknown target with an ExportError status, and requires
  authentication;
* **redaction-aware** — ``redact_source: true`` withholds source-native evidence values
  (placeholder, not silence) while leaving edges, counts, cursors, and totals identical;
* **jobs record + reject stale** — a job records its snapshot hash and submitted options in
  the result, completes when the acknowledged snapshot matches, and fails with a structured
  ``STALE_PREVIEW`` error (naming both hashes) when it does not.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from projection_corpus import SENSITIVE_SENTINEL, rich_api

from app.auth import validate_authentication
from app.export_job_engine import (
    ExportJobStartRequest,
    get_export_job_status,
    schedule_export_job,
)
from app.export_projection import MAX_EVIDENCE_PAGE_SIZE
from app.export_routes import SOURCE_EVIDENCE_REDACTED
from app.export_source import ExportSource
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
_TENANT = "test-tenant"
_EVIDENCE_URL = f"/v1/export/{_TENANT}/projection-evidence"


def _source() -> ExportSource:
    """A loaded export source wrapping the corpus's rich model (sentinel included)."""
    return ExportSource(
        api=rich_api(),
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
    )


def _body(**overrides) -> dict:
    """A valid evidence request body targeting the lossy Avro export."""
    body = {"artifact": "artifact-1", "version": "1.0.0", "target": "avro"}
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _post_evidence(body: dict):
    with patch("app.export_routes.load_export_source", return_value=_source()):
        return client.post(_EVIDENCE_URL, json=body)


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


def test_evidence_requires_authentication() -> None:
    app.dependency_overrides.clear()
    response = client.post(_EVIDENCE_URL, json=_body())
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# One snapshot across surfaces (options included)
# ---------------------------------------------------------------------------


def test_preview_verify_and_evidence_share_one_snapshot() -> None:
    """Matching source, target, and options resolve to one snapshot hash everywhere.

    GraphQL is the tri-surface target: verify actually emits, and it is the lossy MVP
    target the corpus proved emit-safe for the rich fixture.
    """
    request = {"artifact": "artifact-1", "version": "1.0.0", "target": "graphql"}
    with patch("app.export_routes.load_export_source", return_value=_source()):
        preview = client.post(f"/v1/export/{_TENANT}/preview", json=request)
        verify = client.post(f"/v1/export/{_TENANT}/verify", json=request)
        evidence = client.post(_EVIDENCE_URL, json=request)
    assert preview.status_code == verify.status_code == evidence.status_code == 200

    hashes = {
        preview.json()["fidelity"]["projection"]["manifest_hash"],
        verify.json()["fidelity"]["projection"]["manifest_hash"],
        evidence.json()["summary"]["manifest_hash"],
        evidence.json()["page"]["manifest_hash"],
    }
    assert len(hashes) == 1, f"surfaces disagree on the snapshot: {hashes}"


def test_preview_folds_options_into_the_snapshot() -> None:
    """The preview now accepts options; a different option set is a different snapshot."""
    options = {"namespace": "corpus.test"}  # a valid, non-default Avro emit option

    with patch("app.export_routes.load_export_source", return_value=_source()):
        default = client.post(f"/v1/export/{_TENANT}/preview", json=_body())
        changed = client.post(f"/v1/export/{_TENANT}/preview", json=_body(options=options))
        evidence_changed = client.post(_EVIDENCE_URL, json=_body(options=options))
    assert default.status_code == changed.status_code == evidence_changed.status_code == 200

    default_hash = default.json()["fidelity"]["projection"]["manifest_hash"]
    changed_hash = changed.json()["fidelity"]["projection"]["manifest_hash"]
    assert default_hash != changed_hash, "an option change must be a different snapshot"
    # And the evidence surface agrees with the preview for the changed options.
    assert evidence_changed.json()["summary"]["manifest_hash"] == changed_hash


# ---------------------------------------------------------------------------
# Bounded, cursor-paginated evidence
# ---------------------------------------------------------------------------


def test_evidence_pages_cover_every_row_exactly_once() -> None:
    """Walking the cursor chain yields every evidence row once, in canonical order."""
    seen: list = []
    cursor = None
    total = None
    for _ in range(50):  # hard stop far above any expected page count
        response = _post_evidence(_body(limit=2, cursor=cursor))
        assert response.status_code == 200, response.text
        page = response.json()["page"]
        seen.extend(edge["id"] for edge in page["edges"])
        total = page["total"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None, "cursor chain did not terminate"
    assert len(seen) == total
    assert len(set(seen)) == total, "a row appeared on more than one page"


def test_evidence_limit_is_clamped_to_the_hard_cap() -> None:
    """An oversized limit is clamped server-side — the page can never exceed the cap."""
    response = _post_evidence(_body(limit=10_000_000))
    assert response.status_code == 200
    page = response.json()["page"]
    assert len(page["edges"]) <= MAX_EVIDENCE_PAGE_SIZE


def test_evidence_rejects_a_non_positive_limit() -> None:
    response = _post_evidence(_body(limit=0))
    assert response.status_code == 422


def test_evidence_rejects_a_malformed_cursor() -> None:
    response = _post_evidence(_body(cursor="not-a-cursor!!"))
    assert response.status_code == 422
    assert "cursor" in response.json()["detail"]


def test_evidence_rejects_an_unknown_target() -> None:
    response = _post_evidence(_body(target="not-a-format"))
    assert response.status_code in (400, 404)


def test_evidence_carries_snapshot_provenance() -> None:
    """The summary's target block carries the emitter/registry versions and documentation."""
    response = _post_evidence(_body())
    assert response.status_code == 200
    target = response.json()["summary"]["target"]
    assert target["emitter_version"]
    assert target["registry_version"]
    assert target["apiome_version"]
    assert "documentation" in target


# ---------------------------------------------------------------------------
# Redaction-aware
# ---------------------------------------------------------------------------


def test_unredacted_evidence_returns_native_values_to_the_owner() -> None:
    """The owning tenant sees its own source-native evidence by default."""
    response = _post_evidence(_body())
    assert response.status_code == 200
    body = response.json()
    assert body["redacted"] is False
    assert SENSITIVE_SENTINEL in json.dumps(body), (
        "the rich fixture plants native evidence that should reach the owner unredacted"
    )


def test_redact_source_withholds_native_values_with_a_placeholder() -> None:
    """redact_source strips values but keeps the page's edges/counts/total identical."""
    clear = _post_evidence(_body())
    redacted = _post_evidence(_body(redact_source=True))
    assert clear.status_code == redacted.status_code == 200

    redacted_body = redacted.json()
    assert redacted_body["redacted"] is True
    text = json.dumps(redacted_body)
    assert SENSITIVE_SENTINEL not in text
    assert SOURCE_EVIDENCE_REDACTED in text, (
        "a captured-but-withheld value must show the placeholder, not silent null"
    )

    # Redaction changes evidence values only — never the evidence itself.
    clear_page = clear.json()["page"]
    redacted_page = redacted_body["page"]
    assert redacted_page["edges"] == clear_page["edges"]
    assert redacted_page["total"] == clear_page["total"]
    assert redacted_page["next_cursor"] == clear_page["next_cursor"]
    assert clear.json()["summary"] == redacted_body["summary"]


# ---------------------------------------------------------------------------
# Jobs: record snapshot + configuration, reject stale acknowledgements
# ---------------------------------------------------------------------------


async def _run_job(request: ExportJobStartRequest) -> dict:
    """Schedule a job against the corpus source and drain it to a terminal state."""
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(_TENANT, _MOCK_AUTH["tenant_id"], request)
        for _ in range(500):
            status = await get_export_job_status(_TENANT, accepted.job_id)
            if status.state in ("completed", "failed", "canceled"):
                return status.model_dump(mode="json")
            await asyncio.sleep(0.01)
    raise AssertionError("export job did not reach a terminal state")


def _current_snapshot_hash() -> str:
    """The snapshot hash a preview of the same inputs returns."""
    with patch("app.export_routes.load_export_source", return_value=_source()):
        preview = client.post(f"/v1/export/{_TENANT}/preview", json=_body())
    assert preview.status_code == 200
    return preview.json()["fidelity"]["projection"]["manifest_hash"]


async def test_job_records_snapshot_hash_and_options() -> None:
    """A completed job's result carries the snapshot hash + submitted configuration."""
    request = ExportJobStartRequest(artifact="artifact-1", target="avro", dry_run=True)
    status = await _run_job(request)
    assert status["state"] == "completed"
    result = status["result"]
    assert result["snapshot_hash"] == result["fidelity"]["projection"]["manifest_hash"]
    assert result["snapshot_hash"] == _current_snapshot_hash()
    assert result["options"] is None


async def test_job_completes_when_the_acknowledged_snapshot_matches() -> None:
    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="avro",
        dry_run=True,
        acknowledged_snapshot=_current_snapshot_hash(),
    )
    status = await _run_job(request)
    assert status["state"] == "completed"
    assert status["error"] is None


async def test_job_rejects_a_stale_acknowledged_snapshot() -> None:
    """A mismatched acknowledgement fails structurally, naming both hashes."""
    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="avro",
        dry_run=True,
        acknowledged_snapshot="0" * 64,
    )
    status = await _run_job(request)
    assert status["state"] == "failed"
    error = status["error"]
    assert error["code"] == "STALE_PREVIEW"
    assert error["context"]["acknowledged_snapshot"] == "0" * 64
    assert error["context"]["current_snapshot"] == _current_snapshot_hash()
    assert "preview" in error["message"].lower()


async def test_job_rejects_stale_ack_when_options_change() -> None:
    """An option change is a different snapshot — the old acknowledgement fails (EFP-3.1)."""
    default_hash = _current_snapshot_hash()
    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="avro",
        dry_run=True,
        options={"namespace": "corpus.test"},
        acknowledged_snapshot=default_hash,
    )
    status = await _run_job(request)
    assert status["state"] == "failed"
    assert status["error"]["code"] == "STALE_PREVIEW"


async def test_job_rejects_stale_ack_after_emitter_version_bump() -> None:
    """An emitter upgrade between preview and generate yields STALE_PREVIEW (EFP-3.1)."""
    from app.avro_emitter import AvroEmitter

    ack = _current_snapshot_hash()
    original = AvroEmitter.version
    try:
        AvroEmitter.version = "999-bumped-for-test"
        request = ExportJobStartRequest(
            artifact="artifact-1",
            target="avro",
            dry_run=True,
            acknowledged_snapshot=ack,
        )
        status = await _run_job(request)
    finally:
        AvroEmitter.version = original
    assert status["state"] == "failed"
    assert status["error"]["code"] == "STALE_PREVIEW"


async def test_job_rejects_stale_ack_after_registry_version_bump() -> None:
    """A capability-registry revision between preview and generate yields STALE_PREVIEW."""
    from app.export_projection import REGISTRY_VERSION

    ack = _current_snapshot_hash()
    with patch("app.export_projection.REGISTRY_VERSION", "999-bumped-registry"):
        request = ExportJobStartRequest(
            artifact="artifact-1",
            target="avro",
            dry_run=True,
            acknowledged_snapshot=ack,
        )
        status = await _run_job(request)
    assert status["state"] == "failed"
    assert status["error"]["code"] == "STALE_PREVIEW"
    assert REGISTRY_VERSION != "999-bumped-registry"


async def test_job_rejects_stale_ack_after_source_revision_change() -> None:
    """A source revision change between preview and generate yields STALE_PREVIEW."""
    from projection_corpus import event_api

    ack = _current_snapshot_hash()
    altered = ExportSource(
        api=event_api(),
        artifact_id="artifact-1",
        version_record_id="rev-uuid-2",
        version_label="2.0.0",
    )
    request = ExportJobStartRequest(
        artifact="artifact-1",
        target="avro",
        dry_run=True,
        acknowledged_snapshot=ack,
    )
    with patch("app.export_job_engine.load_export_source", return_value=altered):
        accepted = await schedule_export_job(_TENANT, _MOCK_AUTH["tenant_id"], request)
        for _ in range(500):
            status = await get_export_job_status(_TENANT, accepted.job_id)
            if status.state in ("completed", "failed", "canceled"):
                payload = status.model_dump(mode="json")
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("export job did not reach a terminal state")
    assert payload["state"] == "failed"
    assert payload["error"]["code"] == "STALE_PREVIEW"
