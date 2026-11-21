"""Originals in the document store — COA-5.3 (#7079).

Covers :mod:`app.original_documents` against the ``db`` and ``filesystem`` backends with an
in-memory database, and the two import write points that call it:

* :func:`app.import_source_pipeline.persist_adapter_import` (every in-process importer), and
* :func:`app.spec_import_engine._record_worker_import_snapshot` (OpenAPI through the UI worker).

Pinned acceptance criteria: an import produces one ``original`` object whose SHA-256 matches the
stored (scrubbed) text; re-importing identical bytes reuses the object; a withheld source stores
nothing; the legacy columns are kept for ``db`` and dropped for the other backends; large text is
gzip-coded with the coding recorded.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest

from app.config import settings
from app.document_store import (
    BACKEND_DB,
    BACKEND_FILESYSTEM,
    DbDocumentStore,
    DocumentStoreError,
    FilesystemDocumentStore,
    set_document_store,
)
from app.fileset import IntakeFileset
from app.import_source_pipeline import _ResolvedIntake, persist_adapter_import
from app.original_documents import (
    ENCODING_GZIP,
    ENCODING_IDENTITY,
    MANIFEST_MEDIA_TYPE,
    clear_originals,
    decode_original,
    encode_original,
    fileset_manifest,
    legacy_source_columns_kept,
    media_type_for,
    store_original,
    store_original_fileset,
)
from app.spec_import_engine import _record_worker_import_snapshot
from tests.test_document_store import FakeBlobDatabase
from tests.test_persist_adapter_import import _catalog_routing, _FakeDb, _model, _payload

TENANT = "0b7e6c1e-4a53-4c8e-9d0e-1f2a3b4c5d6e"
OTHER_TENANT = "7c1d2e3f-0000-4c8e-9d0e-1f2a3b4c5d6e"
VERSION = "ver-1"
SECRET = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeDocumentDatabase(FakeBlobDatabase):
    """In-memory ``document_objects`` / ``version_documents`` on top of the blob fake."""

    def __init__(self, versions: Optional[Dict[str, str]] = None) -> None:
        super().__init__()
        #: version id → owning tenant
        self.versions: Dict[str, str] = versions if versions is not None else {VERSION: TENANT, "ver-2": TENANT}
        self.objects: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.documents: Dict[str, Dict[Optional[str], str]] = {}

    def upsert_document_object(self, *, tenant_id, sha256, size_bytes, media_type, encoding, backend, storage_key):
        row = self.objects.setdefault(
            (tenant_id, sha256),
            {
                "id": f"obj-{len(self.objects) + 1}",
                "tenant_id": tenant_id,
                "sha256": sha256,
                "size_bytes": size_bytes,
                "media_type": media_type,
                "encoding": encoding,
            },
        )
        row.update(backend=backend, storage_key=storage_key)
        return row["id"]

    def _object(self, object_id: str) -> Dict[str, Any]:
        return next(row for row in self.objects.values() if row["id"] == object_id)

    def set_version_original_documents(self, *, tenant_id, version_id, original_object_id, parts, keep_existing=False):
        if self.versions.get(version_id) != tenant_id:
            return False
        current = self.documents.get(version_id, {})
        if keep_existing and None in current:
            return False
        self.documents[version_id] = {None: original_object_id, **{path: oid for path, oid in parts}}
        return True

    def clear_version_original_documents(self, *, tenant_id, version_id):
        if self.versions.get(version_id) != tenant_id:
            return 0
        return len(self.documents.pop(version_id, {}))

    def original(self, version_id: str = VERSION) -> Dict[str, Any]:
        """The object row of a revision's ``original``."""
        return self._object(self.documents[version_id][None])

    def parts(self, version_id: str = VERSION) -> Dict[str, Dict[str, Any]]:
        """The object rows of a revision's ``original_part`` rows, by path."""
        return {path: self._object(oid) for path, oid in self.documents[version_id].items() if path is not None}


@pytest.fixture(params=[BACKEND_DB, BACKEND_FILESYSTEM])
def env(request, tmp_path, monkeypatch):
    """A fake database and a store on each backend, installed as the process-wide store."""
    database = FakeDocumentDatabase()
    if request.param == BACKEND_DB:
        store = DbDocumentStore(prefix="apiome", database=database)
    else:
        store = FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome")
    monkeypatch.setattr(settings, "document_store", request.param)
    monkeypatch.setattr("app.database.db", database)
    set_document_store(store)
    return {"db": database, "store": store, "backend": request.param}


class TestEncoding:
    """Gzip above the threshold, recorded and reversible."""

    def test_small_content_is_stored_as_it_is(self):
        assert encode_original(b"openapi: 3.1.0\n", 1024) == (b"openapi: 3.1.0\n", ENCODING_IDENTITY)

    def test_content_at_the_threshold_is_gzip_coded_and_decodes(self):
        data = b"a: 1\n" * 400
        coded, encoding = encode_original(data, len(data))
        assert encoding == ENCODING_GZIP and len(coded) < len(data)
        assert decode_original(coded, encoding) == data

    def test_the_gzip_stream_is_deterministic(self):
        data = b"paths: {}\n" * 500
        assert encode_original(data, 16) == encode_original(data, 16)

    def test_content_gzip_does_not_shrink_stays_identity(self):
        data = hashlib.sha256(b"seed").digest()  # 32 high-entropy bytes
        assert encode_original(data, 1) == (data, ENCODING_IDENTITY)

    def test_zero_turns_the_coding_off(self):
        data = b"a" * 100_000
        assert encode_original(data, 0) == (data, ENCODING_IDENTITY)

    def test_the_default_threshold_comes_from_the_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "document_store_gzip_min_bytes", 8)
        assert encode_original(b"a" * 64)[1] == ENCODING_GZIP

    def test_decode_refuses_an_unknown_coding_and_a_bad_stream(self):
        with pytest.raises(ValueError):
            decode_original(b"x", "br")
        with pytest.raises(ValueError):
            decode_original(b"not gzip", ENCODING_GZIP)
        assert decode_original(b"x", None) == b"x"


class TestHelpers:
    def test_media_type_from_the_name_then_the_content(self):
        assert media_type_for("pets.yaml") == "application/yaml"
        assert media_type_for("PETS.YML") == "application/yaml"
        assert media_type_for("pets.json") == "application/json"
        assert media_type_for("svc.wsdl") == "application/xml"
        assert media_type_for(None, '  {"openapi": "3.1.0"}') == "application/json"
        assert media_type_for("orders.proto", 'syntax = "proto3";') == "text/plain"
        assert media_type_for(None) == "text/plain"

    def test_legacy_columns_are_kept_only_for_the_db_backend(self):
        class Config:
            document_store = "db"

        assert legacy_source_columns_kept(Config) is True
        Config.document_store = ""
        assert legacy_source_columns_kept(Config) is True
        for backend in ("s3", "filesystem", " S3 "):
            Config.document_store = backend
            assert legacy_source_columns_kept(Config) is False

    def test_a_manifest_is_canonical(self):
        a = {"path": "a.proto", "sha256": "1" * 64, "sizeBytes": 1, "mediaType": "text/plain"}
        b = {"path": "b.proto", "sha256": "2" * 64, "sizeBytes": 2, "mediaType": "text/plain"}
        assert fileset_manifest("a.proto", [a, b]) == fileset_manifest("a.proto", [b, a])
        document = json.loads(fileset_manifest("a.proto", [b, a]))
        assert document["kind"] == "fileset" and document["root"] == "a.proto"
        assert [member["path"] for member in document["members"]] == ["a.proto", "b.proto"]


class TestStoreOriginal:
    """One document → one object, one ``original`` row."""

    def test_the_object_digest_matches_the_text(self, env):
        text = "openapi: 3.1.0\ninfo:\n  title: Pets\n"
        stored = store_original(TENANT, VERSION, text, filename="pets.yaml")

        assert stored is not None and stored.created is True
        assert stored.sha256 == stored.content_sha256 == _sha(text.encode())
        assert stored.encoding == ENCODING_IDENTITY and stored.backend == env["backend"]
        assert stored.media_type == "application/yaml" and stored.size_bytes == len(text.encode())
        row = env["db"].original()
        assert row["sha256"] == _sha(text.encode()) and row["backend"] == env["backend"]
        assert row["storage_key"] == env["store"].key_for(TENANT, row["sha256"])
        assert env["store"].get(TENANT, row["sha256"]).decode() == text
        assert stored.pointer() == {
            "sha256": stored.sha256,
            "contentSha256": stored.sha256,
            "sizeBytes": len(text.encode()),
            "mediaType": "application/yaml",
            "encoding": "identity",
        }

    def test_identical_text_reuses_the_object(self, env):
        first = store_original(TENANT, VERSION, "a: 1\n")
        second = store_original(TENANT, "ver-2", "a: 1\n")

        assert first.created is True and second.created is False
        assert first.object_id == second.object_id
        assert len(env["db"].objects) == 1

    def test_a_new_document_replaces_the_revisions_original(self, env):
        store_original(TENANT, VERSION, "a: 1\n")
        store_original(TENANT, VERSION, "a: 2\n")
        assert env["db"].original()["sha256"] == _sha(b"a: 2\n")

    def test_keep_existing_leaves_the_first_original(self, env):
        store_original(TENANT, VERSION, "a: 1\n", keep_existing=True)
        assert store_original(TENANT, VERSION, "a: 2\n", keep_existing=True) is None
        assert env["db"].original()["sha256"] == _sha(b"a: 1\n")

    def test_large_text_is_gzip_coded_and_the_coding_is_recorded(self, env, monkeypatch):
        monkeypatch.setattr(settings, "document_store_gzip_min_bytes", 1024)
        text = "paths:\n" + "  /pets: {}\n" * 2000
        stored = store_original(TENANT, VERSION, text, filename="pets.yaml")

        row = env["db"].original()
        assert stored.encoding == row["encoding"] == ENCODING_GZIP
        assert stored.content_sha256 == _sha(text.encode()) != stored.sha256
        assert stored.size_bytes == len(text.encode()) > row["size_bytes"]
        blob = env["store"].get(TENANT, row["sha256"])
        assert _sha(blob) == row["sha256"]
        assert _sha(decode_original(blob, row["encoding"])) == _sha(text.encode())
        # The same text again is the same object, coded or not.
        assert store_original(TENANT, "ver-2", text).created is False

    def test_a_revision_of_another_tenant_is_not_linked(self, env):
        assert store_original(OTHER_TENANT, VERSION, "a: 1\n") is None
        assert VERSION not in env["db"].documents

    def test_missing_arguments_store_nothing(self, env):
        assert store_original("", VERSION, "a") is None
        assert store_original(TENANT, "", "a") is None
        assert store_original(TENANT, VERSION, None) is None  # type: ignore[arg-type]
        assert env["db"].objects == {}

    def test_a_store_failure_returns_none_and_never_raises(self, env):
        class Broken:
            def put(self, *_args, **_kwargs):
                raise DocumentStoreError("bucket unreachable")

        assert store_original(TENANT, VERSION, "a: 1\n", database=env["db"], store=Broken()) is None
        assert env["db"].documents == {}


class TestStoreFileset:
    """A set of files → a manifest plus one part per file."""

    MEMBERS = {"api/orders.proto": b'syntax = "proto3";\n', "api/common.proto": b"message Id {}\n"}

    def test_stores_a_manifest_and_a_part_per_file(self, env):
        stored = store_original_fileset(TENANT, VERSION, self.MEMBERS, root="api/orders.proto")

        assert stored is not None and stored.parts == 2 and stored.media_type == MANIFEST_MEDIA_TYPE
        assert stored.pointer()["parts"] == 2
        parts = env["db"].parts()
        assert {path: row["sha256"] for path, row in parts.items()} == {
            path: _sha(data) for path, data in self.MEMBERS.items()
        }
        manifest = json.loads(env["store"].get(TENANT, env["db"].original()["sha256"]))
        assert manifest["root"] == "api/orders.proto"
        assert [(m["path"], m["sha256"], m["sizeBytes"]) for m in manifest["members"]] == [
            (path, _sha(self.MEMBERS[path]), len(self.MEMBERS[path])) for path in sorted(self.MEMBERS)
        ]

    def test_the_same_set_again_writes_no_new_object(self, env):
        first = store_original_fileset(TENANT, VERSION, self.MEMBERS, root="api/orders.proto")
        second = store_original_fileset(TENANT, "ver-2", self.MEMBERS, root="api/orders.proto")
        assert second.created is False and second.object_id == first.object_id
        assert len(env["db"].objects) == 3

    def test_a_new_set_drops_parts_it_no_longer_has(self, env):
        store_original_fileset(TENANT, VERSION, self.MEMBERS, root="api/orders.proto")
        store_original_fileset(TENANT, VERSION, {"api/orders.proto": b"syntax = 'proto3';\n"}, root="api/orders.proto")
        assert list(env["db"].parts()) == ["api/orders.proto"]

    def test_no_files_and_failures_store_nothing(self, env):
        assert store_original_fileset(TENANT, VERSION, {}) is None

        class Broken:
            def put(self, *_args, **_kwargs):
                raise DocumentStoreError("bucket unreachable")

        assert store_original_fileset(TENANT, VERSION, self.MEMBERS, database=env["db"], store=Broken()) is None
        assert env["db"].documents == {}


class TestClearOriginals:
    def test_removes_the_rows_and_keeps_the_objects(self, env):
        store_original(TENANT, VERSION, "a: 1\n")
        assert clear_originals(TENANT, VERSION) is True
        assert VERSION not in env["db"].documents and len(env["db"].objects) == 1
        assert clear_originals(TENANT, VERSION) is False

    def test_never_raises(self):
        class Broken:
            def clear_version_original_documents(self, **_kwargs):
                raise RuntimeError("db down")

        assert clear_originals(TENANT, VERSION, database=Broken()) is False
        assert clear_originals("", VERSION, database=Broken()) is False


# ───────────────────────────── the in-process import path ─────────────────────────────


class _ImportDb(_FakeDb, FakeDocumentDatabase):
    """The persist hook's fake database, with the document tables."""

    def __init__(self) -> None:
        _FakeDb.__init__(self)
        FakeDocumentDatabase.__init__(self, versions={"ver-1": TENANT})


def _import_payload() -> Dict[str, Any]:
    payload = _payload()
    payload["tenant_id"] = TENANT
    return payload


def _text_intake(text: str) -> _ResolvedIntake:
    return _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)


def _archive_intake(members: Dict[str, str], root: str) -> _ResolvedIntake:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, text in members.items():
            archive.writestr(path, text)
    return _ResolvedIntake(
        raw_bytes=buffer.getvalue(),
        text=None,
        fileset=IntakeFileset.from_members(members, root=root),
        archive_root=root,
    )


@pytest.fixture(params=[BACKEND_DB, BACKEND_FILESYSTEM])
def import_env(request, tmp_path, monkeypatch):
    """``persist_adapter_import`` wired to a fake database and a store on each backend."""
    database = _ImportDb()
    if request.param == BACKEND_DB:
        store = DbDocumentStore(prefix="apiome", database=database)
    else:
        store = FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome")
    monkeypatch.setattr(settings, "document_store", request.param)
    monkeypatch.setattr("app.database.db", database)
    set_document_store(store)
    return {"db": database, "store": store, "backend": request.param}


class TestAdapterImport:
    """Every in-process importer persists through ``persist_adapter_import``."""

    def test_a_single_document_is_stored_and_pointed_at(self, import_env):
        text = 'syntax = "proto3";'
        persist_adapter_import(_import_payload(), _model(), _text_intake(text), _catalog_routing())

        database = import_env["db"]
        metadata = database.source_format_call["format_metadata"]
        row = database.original("ver-1")
        assert row["sha256"] == _sha(text.encode())
        assert import_env["store"].get(TENANT, row["sha256"]).decode() == text
        assert metadata["sourceDocument"]["sha256"] == row["sha256"]
        assert metadata["sourceDocument"]["mediaType"] == "text/plain"
        if import_env["backend"] == BACKEND_DB:
            assert metadata["sourceContent"] == text
        else:
            assert "sourceContent" not in metadata

    def test_the_stored_text_is_the_scrubbed_text(self, import_env):
        text = f"asyncapi: 2.6.0\ninfo:\n  x-token: {SECRET}\nchannels: {{}}\n"
        persist_adapter_import(_import_payload(), _model(), _text_intake(text), _catalog_routing())

        database = import_env["db"]
        row = database.original("ver-1")
        stored_text = import_env["store"].get(TENANT, row["sha256"]).decode()
        assert SECRET not in stored_text and stored_text != text
        assert row["sha256"] == _sha(stored_text.encode())
        if import_env["backend"] == BACKEND_DB:
            assert database.source_format_call["format_metadata"]["sourceContent"] == stored_text

    def test_importing_the_same_bytes_again_reuses_the_object(self, import_env):
        for _ in range(2):
            persist_adapter_import(_import_payload(), _model(), _text_intake("a: 1\n"), _catalog_routing())
        assert len(import_env["db"].objects) == 1

    def test_an_archive_is_stored_as_a_manifest_and_parts(self, import_env):
        members = {"orders.proto": 'syntax = "proto3";\n', "common.proto": "message Id {}\n"}
        intake = _archive_intake(members, "orders.proto")
        persist_adapter_import(_import_payload(), _model(), intake, _catalog_routing())

        database = import_env["db"]
        metadata = database.source_format_call["format_metadata"]
        assert {path: row["sha256"] for path, row in database.parts("ver-1").items()} == {
            path: _sha(text.encode()) for path, text in members.items()
        }
        assert database.original("ver-1")["media_type"] == MANIFEST_MEDIA_TYPE
        assert metadata["sourceDocument"]["parts"] == 2
        assert metadata["filesetMembers"] == sorted(members)
        if import_env["backend"] == BACKEND_DB:
            assert base64.standard_b64decode(metadata["sourceContent"]) == intake.raw_bytes
            assert metadata["sourceEncoding"] == "base64"
        else:
            assert "sourceContent" not in metadata and "sourceEncoding" not in metadata

    def test_a_withheld_source_stores_nothing_and_drops_an_earlier_original(self, import_env):
        database = import_env["db"]
        persist_adapter_import(_import_payload(), _model(), _text_intake("a: 1\n"), _catalog_routing())
        assert "ver-1" in database.documents

        model = _model().model_copy(
            update={"format": "dicom", "extras": {"source_retention": {"verbatim": False, "reason": "dicom-test"}}}
        )
        before = len(database.objects)
        persist_adapter_import(_import_payload(), model, _text_intake('{"00100010": {"vr": "PN"}}'), _catalog_routing())

        metadata = database.source_format_call["format_metadata"]
        assert metadata["sourceContent"] is None and metadata["sourceWithheld"] == "dicom-test"
        assert "sourceDocument" not in metadata
        assert "ver-1" not in database.documents and len(database.objects) == before

    def test_an_archive_with_secrets_stays_withheld(self, import_env):
        members = {"a.yaml": f"token: {SECRET}\n", "b.yaml": "b: 1\n"}
        persist_adapter_import(_import_payload(), _model(), _archive_intake(members, "a.yaml"), _catalog_routing())

        metadata = import_env["db"].source_format_call["format_metadata"]
        assert metadata["sourceWithheld"] == "secrets-detected" and "sourceDocument" not in metadata
        assert import_env["db"].objects == {} and import_env["db"].documents == {}

    def test_a_store_failure_keeps_the_source_in_the_database(self, import_env):
        class Broken:
            def put(self, *_args, **_kwargs):
                raise DocumentStoreError("bucket unreachable")

        set_document_store(Broken())
        persist_adapter_import(_import_payload(), _model(), _text_intake("a: 1\n"), _catalog_routing())

        metadata = import_env["db"].source_format_call["format_metadata"]
        assert metadata["sourceContent"] == "a: 1\n" and "sourceDocument" not in metadata


# ───────────────────────────── the worker (OpenAPI) import path ─────────────────────────────

OPENAPI = f"openapi: 3.1.0\ninfo:\n  title: Pets\n  x-token: {SECRET}\npaths: {{}}\n"


class _SnapshotDb(FakeDocumentDatabase):
    """The document tables plus the two calls the snapshot hook makes."""

    def __init__(self) -> None:
        super().__init__(versions={"v1": TENANT})
        self.snapshots: List[Dict[str, Any]] = []

    def get_version_by_id(self, version_id, tenant_id):
        return {"id": version_id, "project_id": "p1"}

    def record_import_snapshot(self, **kwargs):
        self.snapshots.append(kwargs)


def _snapshot(database: _SnapshotDb, text: str = OPENAPI, *, mode: str = "enforce") -> None:
    from app.intake_scrub_policy import ScrubResolution

    payload = {
        "tenant_id": TENANT,
        "user_id": "u1",
        "filename": "pets.yaml",
        "document_base64": base64.b64encode(text.encode()).decode(),
    }
    with (
        patch("app.database.db", database),
        patch("app.compatibility_engine.openapi_for_revision", return_value={"openapi": "3.1.0", "paths": {}}),
        patch("app.intake_scrub_policy.resolve_scrub_mode", return_value=ScrubResolution(mode=mode)),
        patch("app.intake_scrub_policy.load_tenant_scrub_policy", return_value=None),
    ):
        _record_worker_import_snapshot(TENANT, "acme", "v1", payload)


@pytest.fixture(params=[BACKEND_DB, BACKEND_FILESYSTEM])
def snapshot_env(request, tmp_path, monkeypatch):
    """The snapshot hook wired to a fake database and a store on each backend."""
    database = _SnapshotDb()
    if request.param == BACKEND_DB:
        store = DbDocumentStore(prefix="apiome", database=database)
    else:
        store = FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome")
    monkeypatch.setattr(settings, "document_store", request.param)
    set_document_store(store)
    return {"db": database, "store": store, "backend": request.param}


class TestWorkerImport:
    """OpenAPI and Swagger imports decomposed by the apiome-ui worker."""

    def test_the_scrubbed_text_is_the_original_and_the_upload_digest_is_kept(self, snapshot_env):
        database = snapshot_env["db"]
        _snapshot(database)

        row = database.original("v1")
        stored_text = snapshot_env["store"].get(TENANT, row["sha256"]).decode()
        assert SECRET not in stored_text
        assert row["sha256"] == _sha(stored_text.encode()) and row["media_type"] == "application/yaml"
        snapshot = database.snapshots[0]
        # The digest is still that of the uploaded bytes, not of the scrubbed text.
        assert snapshot["source_digest"] == "sha256:" + _sha(OPENAPI.encode())
        if snapshot_env["backend"] == BACKEND_DB:
            assert snapshot["source_text"] == stored_text
        else:
            assert snapshot["source_text"] is None

    def test_warn_only_stores_the_text_as_uploaded(self, snapshot_env):
        from app.intake_scrub_policy import MODE_WARN_ONLY

        _snapshot(snapshot_env["db"], mode=MODE_WARN_ONLY)
        assert snapshot_env["db"].original("v1")["sha256"] == _sha(OPENAPI.encode())

    def test_json_is_stored_as_json(self, snapshot_env):
        _snapshot(snapshot_env["db"], '{"openapi": "3.1.0", "paths": {}}')
        assert snapshot_env["db"].original("v1")["media_type"] == "application/json"

    def test_a_second_import_of_the_revision_keeps_the_first_original(self, snapshot_env):
        database = snapshot_env["db"]
        _snapshot(database, "openapi: 3.1.0\npaths: {}\n")
        first = database.original("v1")["sha256"]
        _snapshot(database, "openapi: 3.1.0\npaths: {}\ninfo: {title: Later}\n")
        assert database.original("v1")["sha256"] == first

    def test_a_document_that_is_not_openapi_stores_nothing(self, snapshot_env):
        _snapshot(snapshot_env["db"], "asyncapi: 2.6.0\nchannels: {}\n")
        assert snapshot_env["db"].objects == {} and snapshot_env["db"].snapshots == []

    def test_a_store_failure_keeps_the_text_in_the_snapshot(self, snapshot_env):
        class Broken:
            def put(self, *_args, **_kwargs):
                raise DocumentStoreError("bucket unreachable")

        set_document_store(Broken())
        _snapshot(snapshot_env["db"], "openapi: 3.1.0\npaths: {}\n")
        assert snapshot_env["db"].snapshots[0]["source_text"] == "openapi: 3.1.0\npaths: {}\n"
