"""The document migration job without a database — COA-5.8 (#7084).

Covers the parts that need no Postgres: option checks, the rate limiter, the shape of the
document a database copy becomes (and that its digest is known before writing), the report,
the command-line script and the platform-admin ops routes. The job itself runs against Postgres
in ``tests/test_document_migration_db.py``.
"""

from __future__ import annotations

import base64
import io
import json
import threading
import zipfile
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.document_migration_routes as routes
from app.auth import validate_authentication
from app.document_migration import (
    ADAPTER_SOURCE,
    FROZEN_SCHEMA,
    SOURCES,
    STEP_COPY,
    STEP_PURGE,
    MigrationBusy,
    MigrationOptions,
    MigrationRefused,
    MigrationReport,
    RateLimiter,
    SourceTotals,
    _adapter_document,
    _Context,
    _expected_original_sha,
    _snapshot_document,
    _store_document,
    check_options,
    run_document_migration,
)
from app.document_store import FilesystemDocumentStore
from app.main import app
from app.original_documents import MANIFEST_MEDIA_TYPE
from scripts import migrate_documents_to_store as script

TENANT = "11111111-1111-1111-1111-111111111111"
_AUTH = {"tenant_id": TENANT, "user_id": "22222222-2222-2222-2222-222222222222", "auth_method": "jwt"}


def _store(backend: str) -> SimpleNamespace:
    return SimpleNamespace(backend=backend)


# ───────────────────────────── options ─────────────────────────────


def test_options_default_to_the_copy_step_over_every_source_with_one_worker() -> None:
    options = MigrationOptions().validated()
    assert (options.step, options.scope, options.sources, options.workers) == (STEP_COPY, "all", SOURCES, 1)


def test_options_clamp_the_knobs_and_keep_source_order() -> None:
    options = MigrationOptions(batch_size=10_000, workers=99, sources=(FROZEN_SCHEMA, ADAPTER_SOURCE)).validated()
    assert (options.batch_size, options.workers) == (500, 4)
    assert options.sources == (ADAPTER_SOURCE, FROZEN_SCHEMA)
    assert MigrationOptions(batch_size=0, workers=0).validated().batch_size == 1


def test_options_refuse_an_unknown_source_and_a_tenant_that_is_not_a_uuid() -> None:
    with pytest.raises(MigrationRefused, match="Unknown source"):
        MigrationOptions(sources=("bogus",)).validated()
    with pytest.raises(MigrationRefused, match="UUID"):
        MigrationOptions(tenant_id="acme").validated()
    assert MigrationOptions(tenant_id=f" {TENANT.upper()} ").validated().scope == TENANT


def test_purge_is_refused_on_the_db_backend_and_allowed_on_an_object_store() -> None:
    with pytest.raises(MigrationRefused, match="purge-db-copies"):
        check_options(_store("db"), MigrationOptions(purge_db_copies=True))
    assert check_options(_store("s3"), MigrationOptions(purge_db_copies=True)).step == STEP_PURGE
    assert check_options(_store("db"), MigrationOptions()).step == STEP_COPY


# ───────────────────────────── rate limiter ─────────────────────────────


def test_the_rate_limiter_spaces_rows_out() -> None:
    now = [100.0]
    slept: List[float] = []

    def sleep(seconds: float) -> None:
        slept.append(round(seconds, 6))
        now[0] += seconds

    limiter = RateLimiter(4, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.wait()
    assert slept == [0.25, 0.25]


def test_a_rate_of_zero_never_sleeps() -> None:
    limiter = RateLimiter(0, clock=lambda: 0.0, sleep=lambda _: pytest.fail("slept"))
    limiter.wait()
    limiter.wait()


# ───────────────────────────── documents ─────────────────────────────


def _zip(members: Dict[str, str]) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, text in members.items():
            archive.writestr(path, text)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def test_an_adapter_source_keeps_its_media_type_from_the_label() -> None:
    document = _adapter_document({"content": "{\"a\": 1}", "source_label": "orders.json"})
    assert (document.media_type, document.members) == ("application/json", None)
    assert _adapter_document({"content": "type Query { a: Int }"}).media_type == "text/plain"


def test_an_archive_source_becomes_a_fileset_and_a_broken_one_stays_text() -> None:
    archive = _zip({"a/root.proto": "syntax = \"proto3\";\n", "a/b.proto": "message B {}\n"})
    document = _adapter_document(
        {"content": archive, "intake_kind": "archive", "source_encoding": "base64", "fileset_root": "a/root.proto"}
    )
    assert document.media_type == MANIFEST_MEDIA_TYPE and document.root == "a/root.proto"
    assert set(document.members) == {"a/root.proto", "a/b.proto"}

    broken = _adapter_document({"content": "not base64!", "intake_kind": "archive", "source_encoding": "base64"})
    assert broken.members is None and broken.content == b"not base64!"


def test_a_snapshot_is_yaml_unless_recorded_as_json() -> None:
    assert _snapshot_document({"content": "a: 1", "snapshot_format": "yaml"}).media_type == "application/yaml"
    assert _snapshot_document({"content": "{}", "snapshot_format": "json"}).media_type == "application/json"


class _FakeDb:
    """Just enough of the database layer for :func:`_store_document`."""

    def __init__(self) -> None:
        self.objects: Dict[str, str] = {}

    def upsert_document_object(self, **row: Any) -> str:
        return self.objects.setdefault(row["sha256"], f"obj-{len(self.objects)}")

    def execute_query(self, sql: str, params: Any = None) -> list:
        return [{"id": "x"}]


@pytest.mark.parametrize(
    "row",
    [
        {"content": "openapi: 3.1.0\n" + "x: y\n" * 40_000},  # large enough to be gzip-coded
        {"content": _zip({"r.proto": "syntax = \"proto3\";\n", "s.proto": "message S {}\n"}),
         "intake_kind": "archive", "source_encoding": "base64", "fileset_root": "r.proto"},
    ],
)
def test_the_original_digest_is_known_before_writing(row, tmp_path) -> None:
    document = _adapter_document(row)
    ctx = _Context(db=_FakeDb(), store=FilesystemDocumentStore(path=str(tmp_path)), options=MigrationOptions())

    object_id, parts, pointer = _store_document(ctx, TENANT, document)

    assert pointer["sha256"] == _expected_original_sha(document)
    assert len(parts) == (2 if document.members else 0)


# ───────────────────────────── report ─────────────────────────────


def test_the_report_counts_the_step_outcome_and_lists_a_bounded_number_of_rows() -> None:
    report = MigrationReport(step=STEP_PURGE, dry_run=True, backend="s3", scope="all")
    totals = report.sources.setdefault(ADAPTER_SOURCE, SourceTotals())
    totals.add("would-purge", 10)
    totals.add("skipped", 5)
    for index in range(150):
        report.note_row(ADAPTER_SOURCE, str(index), "skipped", "original-differs")

    body = report.as_dict()
    assert (body["scanned"], body["done"], body["skipped"]) == (2, 1, 1)
    assert body["sources"][ADAPTER_SOURCE]["counts"]["bytes"] == 15
    assert len(body["rows"]) == 100


def test_a_non_dry_run_raises_busy_when_another_run_holds_the_lock() -> None:
    db = SimpleNamespace(execute_query=lambda sql, params=None: [{"locked": False}])
    with pytest.raises(MigrationBusy):
        run_document_migration(db, _store("s3"), MigrationOptions(rate=0))


# ───────────────────────────── script ─────────────────────────────


def test_the_script_passes_its_flags_through_and_exits_by_outcome(capsys) -> None:
    seen: Dict[str, Any] = {}

    def fake_run(db, store, options):
        seen["options"] = options
        report = MigrationReport(step=options.step, dry_run=options.dry_run, backend="s3", scope=options.scope)
        report.sources[ADAPTER_SOURCE] = SourceTotals()
        report.sources[ADAPTER_SOURCE].add("failed")
        return report

    with patch.object(script, "run_document_migration", fake_run), patch.object(script, "get_document_store"):
        status = script.main(["--purge-db-copies", "--dry-run", "--tenant", TENANT, "--source", "frozen_schema",
                              "--rate", "5", "--batch-size", "10", "--workers", "2"])

    options = seen["options"]
    assert status == 1
    assert (options.purge_db_copies, options.dry_run, options.tenant_id) == (True, True, TENANT)
    assert (options.sources, options.rate, options.batch_size, options.workers) == (("frozen_schema",), 5.0, 10, 2)
    assert json.loads(capsys.readouterr().out)["failed"] == 1


def test_the_script_exits_2_when_the_run_is_refused(capsys) -> None:
    def refuse(db, store, options):
        raise MigrationRefused("no")

    with patch.object(script, "run_document_migration", refuse), patch.object(script, "get_document_store"):
        assert script.main([]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "no"}


# ───────────────────────────── ops routes ─────────────────────────────


@pytest.fixture
def client():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    routes._state = routes._RunState()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
        routes._state = routes._RunState()


def test_the_routes_require_a_platform_admin(client) -> None:
    with patch.object(routes, "db") as mdb:
        mdb.is_platform_admin.return_value = False
        assert client.get("/v1/ops/document-migration").status_code == 403
        assert client.post("/v1/ops/document-migration", json={}).status_code == 403


def test_a_purge_on_the_db_backend_answers_409_refused(client) -> None:
    with patch.object(routes, "db") as mdb, patch.object(routes, "get_document_store", return_value=_store("db")):
        mdb.is_platform_admin.return_value = True
        response = client.post("/v1/ops/document-migration", json={"purgeDbCopies": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document-migration-refused"


def test_start_runs_in_the_background_and_a_second_start_answers_409(client) -> None:
    release = threading.Event()
    seen: Dict[str, Any] = {}

    def slow_run(db, store, options):
        seen["options"] = options
        release.wait(5)
        return MigrationReport(step=options.step, dry_run=options.dry_run, backend="s3", scope=options.scope)

    with patch.object(routes, "db") as mdb, patch.object(routes, "get_document_store", return_value=_store("s3")), \
            patch.object(routes, "run_document_migration", slow_run), \
            patch.object(routes, "list_checkpoints", return_value=[{"scope": "all"}]):
        mdb.is_platform_admin.return_value = True
        started = client.post("/v1/ops/document-migration",
                              json={"dryRun": True, "tenantId": TENANT, "sources": ["frozen_schema"], "batchSize": 5})
        again = client.post("/v1/ops/document-migration", json={})
        running = client.get("/v1/ops/document-migration").json()
        release.set()
        routes._state.thread.join(5)
        done = client.get("/v1/ops/document-migration").json()

    assert started.status_code == 202 and started.json()["running"] is True
    options = seen["options"]
    assert (options.dry_run, options.sources, options.batch_size) == (True, ("frozen_schema",), 5)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "document-migration-running"
    assert running["running"] is True and running["backend"] == "s3" and running["checkpoints"] == [{"scope": "all"}]
    assert done["running"] is False and done["report"]["step"] == "copy" and done["error"] is None


def test_a_busy_run_is_reported_as_an_error(client) -> None:
    def busy(db, store, options):
        raise MigrationBusy("Another document migration run is in progress.")

    with patch.object(routes, "db") as mdb, patch.object(routes, "get_document_store", return_value=_store("s3")), \
            patch.object(routes, "run_document_migration", busy), \
            patch.object(routes, "list_checkpoints", return_value=[]):
        mdb.is_platform_admin.return_value = True
        client.post("/v1/ops/document-migration", json={})
        routes._state.thread.join(5)
        body = client.get("/v1/ops/document-migration").json()

    assert body["error"] == "Another document migration run is in progress." and body["report"] is None


def test_the_request_rejects_out_of_range_knobs(client) -> None:
    with patch.object(routes, "db") as mdb:
        mdb.is_platform_admin.return_value = True
        assert client.post("/v1/ops/document-migration", json={"workers": 9}).status_code == 422
        assert client.post("/v1/ops/document-migration", json={"sources": ["bogus"]}).status_code == 422
