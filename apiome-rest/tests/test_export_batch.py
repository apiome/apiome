"""Project / batch export jobs — MFX-39.2 (#4334).

Pins one export job over a set of versions × target(s):

* the request shape — ``versions`` / ``all_versions`` instead of ``version``, distinct non-blank
  entries, no acknowledged snapshots, and a bounded item count;
* the pure seams — :func:`~app.export_batch.version_directory` and the archive
  (:func:`~app.export_batch.build_batch_zip`) with its root manifest;
* the pipeline — every item lands in one zip under ``<version>/<target>/``; a failing item
  (unknown version, emitter fault, severe conversion, crash) is reported on the item without
  sinking the batch; only an all-failed batch fails the job;
* ``all_versions`` selection and its size cap, dry-run, duplicate revisions, per-item attestation
  (and the attestation route), and both download paths.

The DB-backed loaders are faked; the emitters run the real registry/SPI.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import zipfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.emitter import EmitResult, EmittedFile
from app.export_batch import (
    BATCH_BUNDLE_FILENAME,
    build_batch_manifest,
    build_batch_zip,
    version_directory,
)
from app.export_job_engine import (
    MAX_BATCH_ITEMS,
    MAX_BATCH_VERSIONS,
    ExportBatchItem,
    ExportJobError,
    ExportJobFile,
    ExportJobStartRequest,
    MultiTargetBundlePart,
    _jobs,
    get_export_job_status,
    resolve_export_download,
    schedule_export_job,
)
from app.export_job_routes import get_export_job_attestation
from app.export_service import ExportError
from app.export_source import ExportSource, ExportSourceError
from tests.test_export_multi_target import _event_source, _fidelity_and_guard, _source

TENANT_SLUG = "acme"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _clear_export_jobs_between_tests():
    _jobs.clear()
    yield
    _jobs.clear()


def _version(label: str, record_id: str) -> ExportSource:
    """The REST fixture source at another revision of ``artifact-1``."""
    return _source().model_copy(update={"version_record_id": record_id, "version_label": label})


#: The fake artifact-1 history: version reference → loaded source.
_VERSIONS = {
    "1.0.0": _version("1.0.0", "rev-1"),
    "2.0.0": _version("2.0.0", "rev-2"),
    "rev-1": _version("1.0.0", "rev-1"),
}


def _load(_tenant_id, _artifact, ref):
    """Fake :func:`load_export_source`: known references load, others are 404."""
    if ref in _VERSIONS:
        return _VERSIONS[ref]
    raise ExportSourceError(f"Version {ref!r} was not found for artifact 'artifact-1'.")


def _batch(*versions: str, targets=("openapi", "graphql"), **kwargs) -> ExportJobStartRequest:
    """A batch request over ``versions`` of artifact-1 (``all_versions`` when none given)."""
    selection = {"versions": list(versions)} if versions else {"all_versions": True}
    return ExportJobStartRequest(
        artifact=kwargs.pop("artifact", "artifact-1"),
        targets=[{"target": t} for t in targets],
        **selection,
        **kwargs,
    )


async def _wait_terminal(job_id: str) -> dict:
    """Poll the engine until the job is terminal."""
    for _ in range(2000):
        status = await get_export_job_status(TENANT_SLUG, job_id)
        if status.state in ("completed", "failed", "canceled"):
            return status.model_dump(mode="json")
        await asyncio.sleep(0.01)
    raise AssertionError("export job did not reach a terminal state")


async def _run(request: ExportJobStartRequest, *, load=_load, version_ids=None) -> tuple:
    """Schedule ``request`` against the fake loaders; return ``(job_id, terminal status)``."""
    with patch("app.export_job_engine.load_export_source", side_effect=load), patch(
        "app.export_batch.list_project_version_ids", return_value=version_ids or []
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)
    return accepted.job_id, status


def _items(status: dict) -> list:
    return status["result"]["batch"]["items"]


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
def test_request_accepts_a_versions_list_or_all_versions():
    listed = _batch("1.0.0", " 2.0.0 ")
    assert listed.is_batch is True
    assert listed.versions == ["1.0.0", "2.0.0"]
    assert _batch().is_batch is True
    assert ExportJobStartRequest(artifact="a", target="openapi").is_batch is False


def test_a_single_target_batch_is_allowed():
    request = ExportJobStartRequest(
        artifact="a", target="openapi", options={"x": 1}, versions=["1.0.0"]
    )
    assert request.is_batch
    assert [(s.target, s.options) for s in request.target_specs] == [("openapi", {"x": 1})]


@pytest.mark.parametrize(
    "payload",
    [
        {"version": "1.0.0", "versions": ["2.0.0"]},
        {"version": "1.0.0", "all_versions": True},
        {"versions": ["1.0.0"], "all_versions": True},
        {"versions": []},
        {"versions": ["1.0.0", " "]},
        {"versions": ["1.0.0", "1.0.0 "]},
        {"versions": ["1.0.0"], "acknowledged_snapshot": "h"},
    ],
)
def test_request_rejects_inconsistent_batch_shapes(payload):
    with pytest.raises(ValidationError):
        ExportJobStartRequest(artifact="a", target="openapi", **payload)


def test_request_rejects_acknowledged_snapshots_on_batch_targets():
    with pytest.raises(ValidationError):
        ExportJobStartRequest(
            artifact="a",
            targets=[{"target": "openapi", "acknowledged_snapshot": "h"}],
            all_versions=True,
        )


def test_request_caps_versions_and_items():
    with pytest.raises(ValidationError):
        ExportJobStartRequest(
            artifact="a", target="openapi", versions=[f"v{i}" for i in range(MAX_BATCH_VERSIONS + 1)]
        )
    per_target = MAX_BATCH_ITEMS // 3 + 1
    with pytest.raises(ValidationError, match="at most"):
        ExportJobStartRequest(
            artifact="a",
            targets=[{"target": "openapi"}, {"target": "graphql"}, {"target": "protobuf"}],
            versions=[f"v{i}" for i in range(per_target)],
        )


async def test_submit_still_rejects_an_unknown_target():
    with pytest.raises(ExportError) as excinfo:
        await schedule_export_job(
            TENANT_SLUG, TENANT_ID, _batch("1.0.0", targets=("openapi", "no-such-format"))
        )
    assert excinfo.value.status_code == 400
    assert not _jobs


# ---------------------------------------------------------------------------
# Pure seams
# ---------------------------------------------------------------------------
def test_version_directory_is_safe_and_unique():
    taken: set = set()
    assert version_directory(_version("1.0.0", "rev-aaaa1111"), taken) == "1.0.0"
    assert version_directory(_version("1.0.0", "rev-bbbb2222"), taken) == "1.0.0-rev-bbbb"
    assert version_directory(_version("../x/y", "r3"), taken) == "x-y"
    assert version_directory(_version(None, "3f2a-uuid"), taken) == "3f2a-uuid"
    assert version_directory(_version("..", "..."), taken) == "version"
    assert taken == {"1.0.0", "1.0.0-rev-bbbb", "x-y", "3f2a-uuid", "version"}


def _archive_inputs():
    fidelity, guard = _fidelity_and_guard(_source(), "openapi")
    part = MultiTargetBundlePart(
        target="openapi-3.1",
        directory="1.0.0/openapi-3.1",
        emit_result=EmitResult(
            files=[EmittedFile(path="openapi.json", content={"openapi": "3.1.0"})],
            media_type="application/json",
        ),
        fidelity=fidelity,
        provenance={"snapshot_hash": "h-1"},
    )
    ok = ExportBatchItem(
        version="1.0.0",
        version_record_id="rev-1",
        version_label="1.0.0",
        target="openapi-3.1",
        directory="1.0.0/openapi-3.1",
        state="completed",
        tier="lossless",
        preserved_percent=100,
        files=[ExportJobFile(path="1.0.0/openapi-3.1/openapi.json", size_bytes=10)],
        media_type="application/json",
    )
    failed = ExportBatchItem(
        version="9.9.9",
        target="openapi",
        state="failed",
        error=ExportJobError(
            code="SOURCE_LOAD_FAILED",
            category="transport",
            message="Version '9.9.9' was not found.",
            remediation="Retry.",
            retriable=True,
        ),
    )
    from app.export_fidelity_rollup import build_fidelity_rollup

    rollup = build_fidelity_rollup([("1.0.0/openapi-3.1", fidelity, guard)])
    return [part], [ok, failed], rollup


def test_batch_zip_has_item_folders_and_a_manifest_listing_every_item():
    parts, items, rollup = _archive_inputs()
    blob = build_batch_zip(parts, items, artifact="artifact-1", rollup=rollup)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.namelist() == ["1.0.0/openapi-3.1/openapi.json", "manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))

    assert manifest["kind"] == "batch"
    assert manifest["artifact"] == "artifact-1"
    assert (manifest["item_count"], manifest["completed_count"], manifest["failed_count"]) == (2, 1, 1)
    assert manifest["version_count"] == 2
    assert manifest["file_count"] == 1
    ok, failed = manifest["items"]
    assert ok["state"] == "completed"
    assert ok["provenance"] == {"snapshot_hash": "h-1"}
    assert ok["fidelity"] == {"tier": "lossless", "preserved_percent": 100}
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "SOURCE_LOAD_FAILED"
    assert "files" not in failed
    assert manifest["fidelity_rollup"]["target_count"] == 1


def test_batch_zip_is_deterministic_and_carries_no_content_in_the_manifest():
    parts, items, rollup = _archive_inputs()
    kwargs = dict(artifact="a", rollup=rollup)
    assert build_batch_zip(parts, items, **kwargs) == build_batch_zip(parts, items, **kwargs)
    manifest = build_batch_manifest(items, provenance={}, **kwargs)
    assert "content" not in json.dumps(manifest["items"])


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
async def test_a_version_set_exports_to_one_archive_with_a_folder_per_item():
    job_id, status = await _run(_batch("1.0.0", "2.0.0"))

    assert status["state"] == "completed", status["error"]
    result = status["result"]
    assert result["version_record_id"] is None and result["targets"] is None
    assert result["media_type"] == "application/zip"
    batch = result["batch"]
    assert (batch["version_count"], batch["target_count"], batch["item_count"]) == (2, 2, 4)
    assert (batch["completed_count"], batch["failed_count"]) == (4, 0)
    items = batch["items"]
    assert [(i["version"], i["target"].split("-")[0]) for i in items] == [
        ("1.0.0", "openapi"), ("1.0.0", "graphql"), ("2.0.0", "openapi"), ("2.0.0", "graphql"),
    ]
    for item in items:
        assert item["state"] == "completed" and item["error"] is None
        assert item["directory"].startswith(f"{item['version_label']}/")
        assert item["files"] and all(
            f["path"].startswith(item["directory"] + "/") for f in item["files"]
        )
        assert item["tier"] and item["delivery"]["attestation"] is not None
    assert len(result["files"]) == sum(len(i["files"]) for i in items)
    assert result["fidelity_rollup"]["target_count"] == 4

    artifact = resolve_export_download(TENANT_SLUG, job_id)
    assert artifact.filename == BATCH_BUNDLE_FILENAME
    with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert names == {f["path"] for f in result["files"]} | {"manifest.json"}
    assert manifest["kind"] == "batch" and manifest["completed_count"] == 4

    codes = [e["code"] for e in status["events"]]
    assert codes[0] == "EXPORT_STARTED" and codes[-1] == "EXPORT_COMPLETED"
    assert "BATCH_PLANNED" in codes and "BATCH_PARTIAL" not in codes
    assert codes.count("DELIVERY_ATTESTED") == 4


async def test_each_item_is_attested_against_the_archive_and_the_route_selects_it():
    job_id, status = await _run(_batch("1.0.0", "2.0.0"))
    digest = hashlib.sha256(resolve_export_download(TENANT_SLUG, job_id).body).hexdigest()
    for item in _items(status):
        statement = json.loads(
            base64.b64decode(item["delivery"]["attestation"]["envelope"]["payload"])
        )
        assert statement["subject"][0]["digest"]["sha256"] == digest
        assert statement["predicate"]["delivery"]["versionRecordId"] == item["version_record_id"]

    item = _items(status)[2]
    for version in ("2.0.0", "rev-2"):
        attestation = await get_export_job_attestation(
            TENANT_SLUG, job_id, auth_data={}, target=item["target"], version=version
        )
        assert attestation.model_dump(mode="json") == item["delivery"]["attestation"]
    with pytest.raises(HTTPException) as excinfo:
        await get_export_job_attestation(
            TENANT_SLUG, job_id, auth_data={}, target=item["target"], version=None
        )
    assert excinfo.value.status_code == 409


async def test_an_unknown_version_fails_its_items_without_sinking_the_batch():
    job_id, status = await _run(_batch("1.0.0", "9.9.9"))

    assert status["state"] == "completed", status["error"]
    batch = status["result"]["batch"]
    assert (batch["completed_count"], batch["failed_count"]) == (2, 2)
    failed = [i for i in batch["items"] if i["state"] == "failed"]
    assert {i["version"] for i in failed} == {"9.9.9"}
    for item in failed:
        assert item["error"]["code"] == "SOURCE_LOAD_FAILED"
        assert item["error"]["context"]["version"] == "9.9.9"
        assert item["directory"] is None and item["files"] == []

    with zipfile.ZipFile(io.BytesIO(resolve_export_download(TENANT_SLUG, job_id).body)) as zf:
        assert all(name.startswith("1.0.0/") for name in zf.namelist() if name != "manifest.json")
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["failed_count"] == 2
    codes = [e["code"] for e in status["events"]]
    assert codes.count("BATCH_ITEM_FAILED") == 2
    assert "BATCH_PARTIAL" in codes


async def test_an_emitter_fault_fails_only_its_item():
    from app.export_service import emit_canonical as real_emit

    def _emit(api, target, **kwargs):
        if target == "graphql":
            raise ExportError("graphql emitter exploded", status_code=500)
        return real_emit(api, target, **kwargs)

    with patch("app.export_job_engine.emit_canonical", side_effect=_emit):
        _job_id, status = await _run(_batch("1.0.0", "2.0.0"))

    assert status["state"] == "completed"
    by_state = {(i["version"], i["state"]) for i in _items(status) if i["target"] == "graphql"}
    assert by_state == {("1.0.0", "failed"), ("2.0.0", "failed")}
    for item in _items(status):
        if item["target"] == "graphql":
            assert item["error"]["code"] == "EMIT_FAILED"
            assert item["tier"] is not None  # fidelity ran before the emit failed
        else:
            assert item["state"] == "completed"


async def test_a_crashing_item_is_reported_and_the_batch_continues():
    from app.export_service import emit_canonical as real_emit

    calls = {"n": 0}

    def _emit(api, target, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_emit(api, target, **kwargs)

    with patch("app.export_job_engine.emit_canonical", side_effect=_emit):
        _job_id, status = await _run(_batch("1.0.0"))

    assert status["state"] == "completed"
    first, second = _items(status)
    assert first["state"] == "failed" and first["error"]["code"] == "EXPORT_EXCEPTION"
    assert "boom" not in first["error"]["message"]  # internal errors are sanitized
    assert second["state"] == "completed"


async def test_a_severe_conversion_fails_its_item_unless_confirmed():
    events = {"2.0.0": _event_source()}
    load = lambda _t, _a, ref: events[ref]  # noqa: E731

    _job_id, status = await _run(
        _batch("2.0.0", targets=("asyncapi", "graphql"), artifact="artifact-2"), load=load
    )
    assert status["state"] == "completed"
    states = {i["target"]: i for i in _items(status)}
    assert states["graphql"]["state"] == "failed"
    assert states["graphql"]["error"]["code"] == "TRANSCODE_CONFIRMATION_REQUIRED"
    assert next(v for k, v in states.items() if k.startswith("asyncapi"))["state"] == "completed"

    _job_id, confirmed = await _run(
        _batch("2.0.0", targets=("asyncapi", "graphql"), artifact="artifact-2", confirm=True),
        load=load,
    )
    assert confirmed["result"]["batch"]["failed_count"] == 0


async def test_when_every_item_fails_the_job_fails_with_each_items_error():
    def _must_not_store(*_args, **_kwargs):
        raise AssertionError("a failed batch must not store an archive")

    with patch("app.export_artifact_store.put_export_artifact", side_effect=_must_not_store):
        job_id, status = await _run(_batch("8.8.8", "9.9.9", targets=("openapi",)))

    assert status["state"] == "failed"
    assert status["result"] is None
    error = status["error"]
    assert error["code"] == "EXPORT_BATCH_FAILED"
    assert [(i["version"], i["code"]) for i in error["context"]["items"]] == [
        ("8.8.8", "SOURCE_LOAD_FAILED"), ("9.9.9", "SOURCE_LOAD_FAILED"),
    ]
    with pytest.raises(HTTPException) as excinfo:
        resolve_export_download(TENANT_SLUG, job_id)
    assert excinfo.value.status_code == 409


async def test_all_versions_exports_every_listed_revision():
    _job_id, status = await _run(_batch(targets=("openapi",)), version_ids=["rev-1", "2.0.0"])
    assert status["state"] == "completed", status["error"]
    assert [i["version_label"] for i in _items(status)] == ["1.0.0", "2.0.0"]


async def test_all_versions_with_no_versions_fails_the_job():
    _job_id, status = await _run(_batch(), version_ids=[])
    assert status["state"] == "failed"
    assert status["error"]["code"] == "SOURCE_LOAD_FAILED"


async def test_all_versions_past_the_item_cap_fails_before_any_item_runs():
    ids = [f"rev-{i}" for i in range(MAX_BATCH_ITEMS // 2 + 1)]

    def _must_not_load(*_args, **_kwargs):
        raise AssertionError("an oversized batch must not load any version")

    _job_id, status = await _run(_batch(), load=_must_not_load, version_ids=ids)
    assert status["state"] == "failed"
    error = status["error"]
    assert error["code"] == "EXPORT_BATCH_TOO_LARGE"
    assert error["category"] == "resource"
    assert error["context"]["item_count"] == len(ids) * 2


async def test_a_revision_named_twice_is_exported_once():
    _job_id, status = await _run(_batch("1.0.0", "rev-1", targets=("openapi",)))
    assert status["state"] == "completed"
    assert [i["version"] for i in _items(status)] == ["1.0.0"]
    assert "BATCH_VERSION_DUPLICATE" in [e["code"] for e in status["events"]]


async def test_dry_run_reports_each_items_fidelity_without_emitting():
    def _must_not_emit(*_args, **_kwargs):
        raise AssertionError("a dry-run must not emit")

    with patch("app.export_job_engine.emit_canonical", side_effect=_must_not_emit):
        job_id, status = await _run(_batch("1.0.0", "9.9.9", dry_run=True))

    assert status["state"] == "completed"
    result = status["result"]
    assert result["dry_run"] is True and result["download_path"] is None
    batch = result["batch"]
    assert (batch["completed_count"], batch["failed_count"]) == (2, 2)
    for item in batch["items"]:
        if item["state"] == "completed":
            assert item["tier"] and item["files"] == [] and item["delivery"] is None
    assert result["fidelity_rollup"]["target_count"] == 2
    assert status["events"][-1]["code"] == "DRY_RUN_COMPLETED"
    with pytest.raises(HTTPException):
        resolve_export_download(TENANT_SLUG, job_id)


async def test_progress_percent_never_drops():
    seen: list = []
    with patch("app.export_job_engine.load_export_source", side_effect=_load):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, _batch("1.0.0", "2.0.0"))
        for _ in range(2000):
            status = await get_export_job_status(TENANT_SLUG, accepted.job_id)
            seen.append(status.percent)
            if status.state in ("completed", "failed", "canceled"):
                break
            await asyncio.sleep(0.001)
    assert status.state == "completed"
    assert seen == sorted(seen)


async def test_non_owning_instance_serves_the_archive_from_the_shared_store():
    from app.export_artifact_store import body_as_bytes

    job_id, status = await _run(_batch("1.0.0", "2.0.0"))
    assert status["state"] == "completed"
    owner = resolve_export_download(TENANT_SLUG, job_id)

    _jobs.clear()  # simulate another REST instance
    remote = resolve_export_download(TENANT_SLUG, job_id)
    assert remote.filename == BATCH_BUNDLE_FILENAME
    assert body_as_bytes(remote.body) == body_as_bytes(owner.body)
    # The shared poll payload still carries every item.
    polled = await get_export_job_status(TENANT_SLUG, job_id)
    assert polled.result.batch.item_count == 4
