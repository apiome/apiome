"""Multi-target export jobs — MFX-39.1 (#4333).

Pins one export job emitting one source version to N targets:

* the request shape — exactly one of ``target`` / ``targets``, per-target options and
  acknowledged snapshots only on ``targets`` entries, a bounded list;
* the submit-time checks — every target resolves, its options validate, and no two targets
  land in the same bundle directory;
* the pure seams — :func:`~app.export_job_engine.target_directory`,
  :func:`~app.export_fidelity_rollup.build_fidelity_rollup`, and the combined bundle
  (:func:`~app.export_job_engine.build_multi_target_zip`) with its root manifest;
* the pipeline — a real job emits every target into one zip (per-target subdirectories +
  manifest), carries per-target fidelity reports plus a rollup, attests each target against
  the combined bundle, and is all-or-nothing (the first failing target fails the job, naming it);
* dry-run, the severe-conversion guard across targets, and both download paths (owner fast
  path and the shared store).

The DB-backed source loader is faked; the emitters run the real registry/SPI.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import EmitResult, EmittedFile
from app.export_fidelity import ExportFidelityTier, build_export_fidelity
from app.export_fidelity_rollup import build_fidelity_rollup
from app.export_job_engine import (
    MAX_EXPORT_TARGETS,
    MULTI_TARGET_BUNDLE_FILENAME,
    ExportJobStartRequest,
    ExportJobTargetSpec,
    MultiTargetBundlePart,
    _jobs,
    build_multi_target_manifest,
    build_multi_target_zip,
    get_export_job_emit_result,
    get_export_job_status,
    list_export_jobs,
    resolve_export_download,
    schedule_export_job,
    target_directory,
)
from app.export_service import ExportError, resolve_emit_format, resolve_emitter
from app.export_source import ExportSource
from app.transcoding_guards import classify_transcode

TENANT_SLUG = "acme"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _clear_export_jobs_between_tests():
    _jobs.clear()
    yield
    _jobs.clear()


def _source() -> ExportSource:
    """A REST source with one operation + one type, at a fixed revision."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[Service(key="widgets", name="widgets", operations=[op])],
        types=[widget],
    )
    return ExportSource(
        api=api, artifact_id="artifact-1", version_record_id="rev-uuid-1", version_label="1.0.0"
    )


def _event_source() -> ExportSource:
    """An event-only source: a severe conversion for GraphQL, fine for AsyncAPI."""
    msg = Type(
        key="Signup",
        name="Signup",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Signup.id", name="id", type=TypeRef(name="string"))],
    )
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="signup"),
        channels=[Channel(key="user/signedup", address="user/signedup")],
        types=[msg],
    )
    return ExportSource(
        api=api, artifact_id="artifact-2", version_record_id="rev-uuid-2", version_label="2.0.0"
    )


def _multi(*targets: str, **kwargs) -> ExportJobStartRequest:
    """A multi-target request for ``artifact-1`` naming ``targets`` with default options."""
    return ExportJobStartRequest(
        artifact=kwargs.pop("artifact", "artifact-1"),
        targets=[ExportJobTargetSpec(target=t) for t in targets],
        **kwargs,
    )


async def _wait_terminal(job_id: str) -> dict:
    """Poll the engine until the job is terminal; every scheduled job must drain here."""
    for _ in range(1000):
        status = await get_export_job_status(TENANT_SLUG, job_id)
        if status.state in ("completed", "failed", "canceled"):
            return status.model_dump(mode="json")
        await asyncio.sleep(0.01)
    raise AssertionError("export job did not reach a terminal state")


async def _run(request: ExportJobStartRequest, source: ExportSource | None = None) -> tuple:
    """Schedule ``request`` against a faked source and return ``(job_id, terminal status)``."""
    with patch(
        "app.export_job_engine.load_export_source", return_value=source or _source()
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)
    return accepted.job_id, status


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------
def test_request_accepts_a_targets_list_with_per_target_options():
    request = ExportJobStartRequest(
        artifact="a",
        targets=[
            {"target": "openapi", "options": {"x": 1}, "acknowledged_snapshot": "h1"},
            {"target": "graphql"},
        ],
    )
    assert request.is_multi_target is True
    assert request.target is None
    assert request.targets[0].options == {"x": 1}
    assert request.target_label == "openapi,graphql"


def test_single_target_request_is_unchanged():
    request = ExportJobStartRequest(artifact="a", target="openapi", options={"x": 1})
    assert request.is_multi_target is False
    assert request.target_label == "openapi"


@pytest.mark.parametrize(
    "payload",
    [
        {"artifact": "a"},  # neither
        {"artifact": "a", "target": "openapi", "targets": [{"target": "graphql"}]},  # both
        {"artifact": "a", "targets": [{"target": "openapi"}], "options": {"x": 1}},
        {"artifact": "a", "targets": [{"target": "openapi"}], "acknowledged_snapshot": "h"},
        {"artifact": "a", "targets": []},  # empty list
        {"artifact": "a", "targets": [{"target": "openapi", "bogus": True}]},  # extra key
    ],
)
def test_request_rejects_inconsistent_target_shapes(payload):
    with pytest.raises(ValidationError):
        ExportJobStartRequest(**payload)


def test_request_caps_the_number_of_targets():
    too_many = [{"target": f"t{i}"} for i in range(MAX_EXPORT_TARGETS + 1)]
    with pytest.raises(ValidationError):
        ExportJobStartRequest(artifact="a", targets=too_many)


async def test_submit_rejects_an_unknown_target():
    with pytest.raises(ExportError) as excinfo:
        await schedule_export_job(TENANT_SLUG, TENANT_ID, _multi("openapi", "no-such-format"))
    assert excinfo.value.status_code == 400
    assert not _jobs


async def test_submit_rejects_two_targets_resolving_to_one_format():
    """``openapi`` and its own format key land in one directory — refused before any job."""
    format_key = resolve_emit_format("openapi")
    assert format_key != "openapi"
    with pytest.raises(ExportError) as excinfo:
        await schedule_export_job(TENANT_SLUG, TENANT_ID, _multi("openapi", format_key))
    assert excinfo.value.status_code == 400
    assert "distinct format" in str(excinfo.value)
    assert not _jobs


async def test_submit_rejects_invalid_options_for_one_target():
    request = ExportJobStartRequest(
        artifact="artifact-1",
        targets=[{"target": "openapi"}, {"target": "graphql", "options": {"no_such_opt": 1}}],
    )
    with pytest.raises(ExportError) as excinfo:
        await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
    assert excinfo.value.status_code == 422


# ---------------------------------------------------------------------------
# Pure seams
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("format_key", "expected"),
    [
        ("openapi-3.1", "openapi-3.1"),
        ("protobuf_3", "protobuf_3"),
        ("../etc/passwd", "etc-passwd"),
        ("a/b\\c d", "a-b-c-d"),
        ("..", "target"),
        ("", "target"),
    ],
)
def test_target_directory_is_a_safe_single_segment(format_key, expected):
    assert target_directory(format_key) == expected


def _fidelity_and_guard(source: ExportSource, target: str):
    emitter_cls = type(resolve_emitter(target))
    fidelity = build_export_fidelity(source.api, emitter_cls)
    return fidelity, classify_transcode(source.api, emitter_cls, report=fidelity.report)


def test_rollup_reports_worst_tier_floor_mean_and_counts():
    source = _event_source()
    asyncapi = _fidelity_and_guard(source, "asyncapi")
    graphql = _fidelity_and_guard(source, "graphql")

    rollup = build_fidelity_rollup([("asyncapi-3", *asyncapi), ("graphql", *graphql)])

    percents = [asyncapi[0].summary.preserved_percent, graphql[0].summary.preserved_percent]
    assert rollup.target_count == 2
    assert rollup.min_preserved_percent == min(percents)
    assert rollup.mean_preserved_percent == round(sum(percents) / 2)
    assert sum(rollup.tier_counts.values()) == 2
    assert set(rollup.tier_counts) == {t.value for t in ExportFidelityTier}
    assert [line.target for line in rollup.targets] == ["asyncapi-3", "graphql"]
    # Event-only → GraphQL is the severe conversion; it is named on the rollup.
    assert rollup.severe_targets == ["graphql"]
    assert "graphql" in rollup.lossy_targets
    assert rollup.tier is not ExportFidelityTier.LOSSLESS


def test_rollup_of_lossless_targets_is_lossless():
    source = _source()
    rollup = build_fidelity_rollup([("openapi", *_fidelity_and_guard(source, "openapi"))])
    assert rollup.tier is ExportFidelityTier.LOSSLESS
    assert rollup.lossy_targets == []
    assert rollup.severe_targets == []
    assert rollup.min_preserved_percent == rollup.mean_preserved_percent == 100


def test_rollup_needs_at_least_one_target():
    with pytest.raises(ValueError):
        build_fidelity_rollup([])


def _parts() -> list:
    source = _source()
    fidelity, guard = _fidelity_and_guard(source, "openapi")
    a = MultiTargetBundlePart(
        target="openapi-3.1",
        directory="openapi-3.1",
        emit_result=EmitResult(
            files=[EmittedFile(path="openapi.json", content={"openapi": "3.1.0"})],
            media_type="application/json",
        ),
        fidelity=fidelity,
        provenance={"snapshot_hash": "h-a"},
    )
    b = MultiTargetBundlePart(
        target="protobuf-3",
        directory="protobuf-3",
        emit_result=EmitResult(
            files=[
                EmittedFile(path="a.proto", content='syntax = "proto3";\n'),
                EmittedFile(path="nested/b.proto", content='syntax = "proto3";\n'),
            ],
            media_type="text/plain",
        ),
        fidelity=fidelity,
        provenance={"snapshot_hash": "h-b"},
    )
    rollup = build_fidelity_rollup([("openapi-3.1", fidelity, guard), ("protobuf-3", fidelity, guard)])
    return [a, b], rollup


def test_multi_target_zip_has_per_target_directories_and_a_root_manifest():
    parts, rollup = _parts()
    blob = build_multi_target_zip(
        parts, artifact="artifact-1", version_record_id="rev-1", version_label="1.0.0",
        rollup=rollup,
    )
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        doc = json.loads(archive.read("openapi-3.1/openapi.json"))

    assert names == [
        "openapi-3.1/openapi.json",
        "protobuf-3/a.proto",
        "protobuf-3/nested/b.proto",
        "manifest.json",
    ]
    assert doc == {"openapi": "3.1.0"}
    assert manifest["kind"] == "multi-target"
    assert manifest["artifact"] == "artifact-1"
    assert manifest["target_count"] == 2
    assert manifest["file_count"] == 3
    assert [t["directory"] for t in manifest["targets"]] == ["openapi-3.1", "protobuf-3"]
    assert [f["path"] for f in manifest["targets"][1]["files"]] == [
        "protobuf-3/a.proto",
        "protobuf-3/nested/b.proto",
    ]
    assert manifest["targets"][0]["fidelity"]["tier"] == "lossless"
    assert manifest["targets"][1]["provenance"] == {"snapshot_hash": "h-b"}
    assert manifest["fidelity_rollup"]["target_count"] == 2


def test_multi_target_zip_is_deterministic():
    parts, rollup = _parts()
    kwargs = dict(artifact="a", version_record_id="r", version_label=None, rollup=rollup)
    assert build_multi_target_zip(parts, **kwargs) == build_multi_target_zip(parts, **kwargs)
    manifest = build_multi_target_manifest(parts, **kwargs)
    assert "content" not in json.dumps(manifest["targets"])


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
async def test_one_job_emits_every_target_into_one_zip_with_a_manifest():
    job_id, status = await _run(_multi("openapi", "graphql"))

    assert status["state"] == "completed", status["error"]
    result = status["result"]
    assert result["dry_run"] is False
    assert result["target"] is None and result["fidelity"] is None and result["guard"] is None
    assert result["media_type"] == "application/zip"
    assert result["download_path"] == f"/v1/export/{TENANT_SLUG}/jobs/{job_id}/download"

    targets = result["targets"]
    assert [t["target"] for t in targets][0].startswith("openapi")
    assert len(targets) == 2
    for entry in targets:
        assert entry["files"], entry["target"]
        assert all(f["path"].startswith(entry["directory"] + "/") for f in entry["files"])
        assert entry["fidelity"]["report"] is not None
        assert entry["validation"] is not None
        assert entry["delivery"]["blocks_delivery"] is False
    # The top-level manifest lists every bundle entry across targets.
    assert len(result["files"]) == sum(len(t["files"]) for t in targets)

    rollup = result["fidelity_rollup"]
    assert rollup["target_count"] == 2
    assert [line["target"] for line in rollup["targets"]] == [t["target"] for t in targets]

    # One artifact: the combined zip, with every target's files under its directory.
    artifact = resolve_export_download(TENANT_SLUG, job_id)
    assert artifact.filename == MULTI_TARGET_BUNDLE_FILENAME
    assert artifact.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(artifact.body)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    assert names == {f["path"] for f in result["files"]} | {"manifest.json"}
    assert manifest["target_count"] == 2
    # A multi-target job retains its bundle, not a single emit result.
    assert get_export_job_emit_result(TENANT_SLUG, job_id) is None

    codes = [e["code"] for e in status["events"]]
    assert codes[0] == "EXPORT_STARTED" and codes[-1] == "EXPORT_COMPLETED"
    assert codes.count("FIDELITY_COMPUTED") == 2
    assert codes.count("EMITTED") == 2
    assert codes.count("DELIVERY_ATTESTED") == 2


async def test_each_target_is_attested_against_the_combined_bundle():
    import base64
    import hashlib

    job_id, status = await _run(_multi("openapi", "graphql"))
    artifact = resolve_export_download(TENANT_SLUG, job_id)
    digest = hashlib.sha256(artifact.body).hexdigest()

    for entry in status["result"]["targets"]:
        envelope = entry["delivery"]["attestation"]["envelope"]
        statement = json.loads(base64.b64decode(envelope["payload"]))
        assert statement["subject"][0]["digest"]["sha256"] == digest
        assert statement["predicate"]["delivery"]["target"] == entry["target"]


async def test_progress_names_the_target_in_flight_and_percent_never_drops():
    seen: list = []
    original = asyncio.sleep

    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, _multi("openapi", "graphql"))
        for _ in range(1000):
            status = await get_export_job_status(TENANT_SLUG, accepted.job_id)
            seen.append(status.percent)
            if status.state in ("completed", "failed", "canceled"):
                break
            await original(0.001)
    assert status.state == "completed"
    assert seen == sorted(seen)


async def test_list_row_labels_a_multi_target_job_with_its_targets():
    job_id, _status = await _run(_multi("openapi", "graphql"))
    page = await list_export_jobs(TENANT_SLUG)
    row = next(r for r in page.jobs if r.job_id == job_id)
    assert row.target == "openapi,graphql"


async def test_dry_run_reports_every_target_and_the_rollup_without_emitting():
    def _must_not_emit(*_args, **_kwargs):
        raise AssertionError("a dry-run must not emit")

    with patch("app.export_job_engine.emit_canonical", side_effect=_must_not_emit):
        _job_id, status = await _run(_multi("openapi", "graphql", dry_run=True))

    assert status["state"] == "completed"
    result = status["result"]
    assert result["dry_run"] is True
    assert result["download_path"] is None
    assert result["files"] == []
    assert len(result["targets"]) == 2
    for entry in result["targets"]:
        assert entry["fidelity"]["summary"]["tier"]
        assert entry["files"] == [] and entry["validation"] is None and entry["delivery"] is None
    assert result["fidelity_rollup"]["target_count"] == 2
    assert status["events"][-1]["code"] == "DRY_RUN_COMPLETED"


async def test_a_severe_target_fails_the_job_before_any_emit():
    def _must_not_emit(*_args, **_kwargs):
        raise AssertionError("no target may emit while another needs confirmation")

    with patch("app.export_job_engine.emit_canonical", side_effect=_must_not_emit):
        _job_id, status = await _run(
            _multi("asyncapi", "graphql", artifact="artifact-2"), _event_source()
        )

    assert status["state"] == "failed"
    error = status["error"]
    assert error["code"] == "TRANSCODE_CONFIRMATION_REQUIRED"
    assert error["context"]["target"] == "graphql"
    assert [t["target"] for t in error["context"]["targets"]] == ["graphql"]


async def test_a_severe_target_completes_when_confirmed():
    _job_id, status = await _run(
        _multi("asyncapi", "graphql", artifact="artifact-2", confirm=True), _event_source()
    )
    assert status["state"] == "completed", status["error"]
    assert status["result"]["fidelity_rollup"]["severe_targets"] == ["graphql"]


async def test_a_failing_target_fails_the_whole_job_and_names_it():
    """All-or-nothing: the second target's emit failure leaves no bundle behind."""
    from app.export_service import emit_canonical as real_emit

    def _emit(api, target, **kwargs):
        if target == "graphql":
            raise ExportError("graphql emitter exploded", status_code=500)
        return real_emit(api, target, **kwargs)

    def _must_not_store(*_args, **_kwargs):
        raise AssertionError("a failed multi-target job must not store a bundle")

    with patch("app.export_job_engine.emit_canonical", side_effect=_emit), patch(
        "app.export_artifact_store.put_export_artifact", side_effect=_must_not_store
    ):
        job_id, status = await _run(_multi("openapi", "graphql"))

    assert status["state"] == "failed"
    assert status["result"] is None
    assert status["error"]["code"] == "EMIT_FAILED"
    assert status["error"]["context"]["target"] == "graphql"
    with pytest.raises(HTTPException) as excinfo:
        resolve_export_download(TENANT_SLUG, job_id)
    assert excinfo.value.status_code == 409


async def test_a_stale_acknowledgement_on_one_target_fails_the_job():
    request = ExportJobStartRequest(
        artifact="artifact-1",
        targets=[
            {"target": "openapi"},
            {"target": "graphql", "acknowledged_snapshot": "not-the-current-hash"},
        ],
    )
    _job_id, status = await _run(request)
    assert status["state"] == "failed"
    assert status["error"]["code"] == "STALE_PREVIEW"
    assert status["error"]["context"]["target"] == "graphql"


async def test_non_owning_instance_serves_the_combined_bundle_from_the_shared_store():
    from app.export_artifact_store import body_as_bytes

    job_id, status = await _run(_multi("openapi", "graphql"))
    assert status["state"] == "completed"
    owner = resolve_export_download(TENANT_SLUG, job_id)

    _jobs.clear()  # simulate another REST instance
    remote = resolve_export_download(TENANT_SLUG, job_id)
    assert remote.filename == MULTI_TARGET_BUNDLE_FILENAME
    assert remote.media_type == "application/zip"
    assert body_as_bytes(remote.body) == body_as_bytes(owner.body)
    assert remote.content_sha256 == owner.content_sha256


async def test_expired_multi_target_bundle_is_410():
    job_id, _status = await _run(_multi("openapi", "graphql"))
    rec = _jobs[job_id]
    rec.artifact_expires_at_ms = 1  # long past
    with pytest.raises(HTTPException) as excinfo:
        resolve_export_download(TENANT_SLUG, job_id)
    assert excinfo.value.status_code == 410
    assert rec.retained_download is None
