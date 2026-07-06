"""Engine tests for async export jobs — MFX-3.1 (#3844).

Pins the engine seams and the pipeline outcomes independently of the REST layer:

* the packaging seam (:func:`app.export_job_engine.build_result_manifest`) reduces an
  :class:`~app.emitter.EmitResult` to path/media-type/size metadata (never content);
* the validation seam (:func:`app.export_job_engine.validate_emitted_result`) honestly
  reports *deferred* (not passed) until MFX-5.x lands;
* a scheduled job runs load → fidelity → emit → validate → package to ``completed``,
  with sequenced phase events and the raw emit result retained for delivery (MFX-4.x);
* ``dry_run`` completes with the fidelity report and **no artifact** (the emitter is
  never invoked);
* a source-loader failure surfaces as a ``failed`` state with a structured error event;
* cancellation is honoured at the next stage boundary; terminal jobs ignore it.

The DB-backed source loader is faked (its own logic is covered in
``test_export_source.py``); the emitter path runs the real registry/SPI.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import patch

import pytest

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
from app.emitter import EmitResult, EmittedFile
from app.export_job_engine import (
    ExportJobStartRequest,
    _jobs,
    build_result_manifest,
    cancel_export_job,
    get_export_job_emit_result,
    get_export_job_status,
    list_export_jobs,
    schedule_export_job,
    validate_emitted_result,
)
from app.export_source import ExportSource, ExportSourceError

TENANT_SLUG = "acme"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _clear_export_jobs_between_tests():
    _jobs.clear()
    yield
    _jobs.clear()


def _source() -> ExportSource:
    """A loaded source: a REST API with one operation + one type, at a fixed revision."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    service = Service(key="widgets", name="widgets", operations=[op])
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[service],
        types=[widget],
    )
    return ExportSource(
        api=api,
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
    )


async def _wait_terminal(job_id: str, tenant_slug: str = TENANT_SLUG) -> dict:
    """Poll the engine until the job reaches a terminal state; return the status dict.

    Every scheduled job must be drained through here before its test returns —
    a job task that outlives the test's event loop can die while holding the
    engine's job lock and strand every later test.
    """
    for _ in range(500):
        status = get_export_job_status(tenant_slug, job_id)
        if status.state in ("completed", "failed", "canceled"):
            return status.model_dump()
        await asyncio.sleep(0.01)
    raise AssertionError("export job did not reach a terminal state")


# ---------------------------------------------------------------------------
# Seams
# ---------------------------------------------------------------------------
def test_build_result_manifest_reports_paths_and_serialized_sizes():
    """The manifest carries per-file metadata with the size of the serialized content."""
    doc = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}}
    text = "syntax = \"proto3\";\n"
    result = EmitResult(
        files=[
            EmittedFile(path="openapi.json", content=doc, media_type="application/json"),
            EmittedFile(path="widgets.proto", content=text, media_type="text/plain"),
        ],
        media_type="application/json",
    )

    manifest = build_result_manifest(result)

    assert [f.path for f in manifest] == ["openapi.json", "widgets.proto"]
    expected_doc_size = len(json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8"))
    assert manifest[0].size_bytes == expected_doc_size
    assert manifest[0].media_type == "application/json"
    assert manifest[1].size_bytes == len(text.encode("utf-8"))
    # Metadata only — the manifest model has no content field at all.
    assert "content" not in manifest[0].model_dump()


def test_validate_emitted_result_reports_deferred_not_passed():
    """Until MFX-5.x, the validation seam must say 'deferred', never imply success."""
    result = EmitResult(files=[EmittedFile(path="openapi.json", content={})])
    events = validate_emitted_result(result, "openapi-3.1")
    assert len(events) == 1
    level, code, message, context = events[0]
    assert level == "info"
    assert code == "VALIDATION_DEFERRED"
    assert "not implemented" in message
    assert context == {"target": "openapi-3.1"}


# ---------------------------------------------------------------------------
# Pipeline outcomes
# ---------------------------------------------------------------------------
async def test_job_runs_end_to_end_to_completed():
    """A real (non-dry-run) job completes with fidelity + manifest + retained emit result."""
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi")
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "completed"
    assert status["percent"] == 100

    result = status["result"]
    assert result is not None
    assert result["artifact"] == "artifact-1"
    assert result["version_record_id"] == "rev-uuid-1"
    assert result["version_label"] == "1.0.0"
    assert result["dry_run"] is False
    assert result["target"].startswith("openapi")
    assert result["media_type"] == "application/vnd.oai.openapi+json"
    assert len(result["files"]) == 1
    assert result["files"][0]["size_bytes"] > 0

    # The fidelity envelope matches what /export/preview computes: lossless REST→OpenAPI.
    assert result["fidelity"]["summary"]["tier"] == "lossless"
    assert result["fidelity"]["summary"]["preserved_percent"] == 100
    assert result["fidelity"]["advisory"] is not None

    # Phase events are sequenced and cover the whole pipeline.
    codes = [e["code"] for e in status["events"]]
    assert codes == [
        "EXPORT_STARTED",
        "SOURCE_LOADED",
        "FIDELITY_COMPUTED",
        "EMITTED",
        "VALIDATION_DEFERRED",
        "EXPORT_COMPLETED",
    ]
    assert [e["id"] for e in status["events"]] == [f"export-{i}" for i in range(1, 7)]

    # The raw emit result is retained for the delivery epics.
    emit_result = get_export_job_emit_result(TENANT_SLUG, accepted.job_id)
    assert emit_result is not None
    assert emit_result.files[0].path == result["files"][0]["path"]


async def test_dry_run_completes_with_report_and_no_artifact():
    """Dry-run stops after the fidelity report: no files, no emit, no retained result."""
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi", dry_run=True)

    def _must_not_emit(*args, **kwargs):
        raise AssertionError("emit_canonical must not run for a dry-run job")

    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_must_not_emit
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "completed"
    result = status["result"]
    assert result["dry_run"] is True
    assert result["files"] == []
    assert result["media_type"] is None
    assert result["fidelity"]["summary"]["tier"] == "lossless"
    assert get_export_job_emit_result(TENANT_SLUG, accepted.job_id) is None
    codes = [e["code"] for e in status["events"]]
    assert codes[-1] == "DRY_RUN_COMPLETED"
    assert "EMITTED" not in codes


async def test_source_load_failure_fails_the_job_with_structured_event():
    """The loader's typed error becomes a failed state + error event (job API stays 200)."""
    request = ExportJobStartRequest(artifact="missing", target="openapi")
    with patch(
        "app.export_job_engine.load_export_source",
        side_effect=ExportSourceError("Artifact 'missing' was not found.", status_code=404),
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["result"] is None
    errors = [e for e in status["events"] if e["level"] == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "SOURCE_LOAD_FAILED"
    assert errors[0]["context"] == {"status_code": 404}


async def test_unexpected_exception_fails_the_job():
    """Any unclassified fault is converted to a failed job, never a crashed task."""
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi")
    with patch(
        "app.export_job_engine.load_export_source",
        side_effect=RuntimeError("boom"),
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["events"][-1]["code"] == "EXPORT_EXCEPTION"
    assert "boom" in status["events"][-1]["message"]


async def test_cancel_takes_effect_at_next_stage_boundary():
    """A cancel during a blocking stage finalizes the job as canceled, with no result."""
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _slow_loader(*args, **kwargs):
        # Runs in a worker thread; signal the test, then take long enough that the
        # cancel lands before the next stage boundary.
        loop.call_soon_threadsafe(started.set)
        time.sleep(0.1)
        return _source()

    request = ExportJobStartRequest(artifact="artifact-1", target="openapi")
    with patch("app.export_job_engine.load_export_source", side_effect=_slow_loader):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        await asyncio.wait_for(started.wait(), timeout=5)
        await cancel_export_job(TENANT_SLUG, accepted.job_id)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "canceled"
    assert status["result"] is None


async def test_cancel_of_terminal_job_is_a_noop():
    """Cancelling a completed job leaves its state and result untouched."""
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi")
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        await _wait_terminal(accepted.job_id)

    await cancel_export_job(TENANT_SLUG, accepted.job_id)
    status = get_export_job_status(TENANT_SLUG, accepted.job_id)
    assert status.state == "completed"
    assert status.result is not None


async def test_list_is_tenant_scoped_and_summarized():
    """The list shows only the tenant's jobs, as summary rows without event logs."""
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi", dry_run=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        other = await schedule_export_job("other-tenant", "other-tenant-id", request)
        await _wait_terminal(accepted.job_id)
        await _wait_terminal(other.job_id, tenant_slug="other-tenant")

        listing = await list_export_jobs(TENANT_SLUG)

    assert [j.job_id for j in listing.jobs] == [accepted.job_id]
    row = listing.jobs[0]
    assert row.artifact == "artifact-1"
    assert row.target == "openapi"
    assert row.dry_run is True
    assert row.status_path == f"/v1/export/{TENANT_SLUG}/jobs/{accepted.job_id}"


async def test_status_and_emit_result_are_tenant_scoped():
    """A job id from another tenant is a 404 for both status and emit-result lookups."""
    from fastapi import HTTPException

    request = ExportJobStartRequest(artifact="artifact-1", target="openapi")
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        await _wait_terminal(accepted.job_id)

    with pytest.raises(HTTPException) as excinfo:
        get_export_job_status("other-tenant", accepted.job_id)
    assert excinfo.value.status_code == 404

    with pytest.raises(HTTPException) as excinfo:
        get_export_job_emit_result("other-tenant", accepted.job_id)
    assert excinfo.value.status_code == 404


async def test_status_lookup_returns_a_snapshot():
    """Mutating a returned status must not mutate the shared in-memory job record."""
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi")
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        await _wait_terminal(accepted.job_id)

    status = get_export_job_status(TENANT_SLUG, accepted.job_id)
    status.events.clear()
    assert status.result is not None
    status.result.artifact = "mutated"

    fresh = get_export_job_status(TENANT_SLUG, accepted.job_id)
    assert fresh.events
    assert fresh.result is not None
    assert fresh.result.artifact == "artifact-1"


async def test_emit_result_lookup_returns_a_snapshot():
    """Mutating a returned emit result must not mutate the shared in-memory job record."""
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi")
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        await _wait_terminal(accepted.job_id)

    emit_result = get_export_job_emit_result(TENANT_SLUG, accepted.job_id)
    assert emit_result is not None
    emit_result.files[0].path = "mutated.json"

    fresh = get_export_job_emit_result(TENANT_SLUG, accepted.job_id)
    assert fresh is not None
    assert fresh.files[0].path != "mutated.json"
