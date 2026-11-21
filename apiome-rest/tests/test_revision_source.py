"""Reading captured sources through the store — COA-5.4 (#7080).

Covers :mod:`app.revision_source` with an in-memory database and each document-store backend
(``db``, ``filesystem`` and ``s3`` through moto):

* :func:`~app.revision_source.revision_source` reads the store first and the legacy columns
  second, for a single document, a gzip-coded one, a set of files and a decomposed import;
* export, conversion and provenance read the same source on all three backends;
* the row helpers, the SQL fragments and the canonical-model cache.
"""

from __future__ import annotations

import base64
import io
import zipfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app import revision_source as module
from app.canonical_model import CanonicalApi
from app.catalog_conversion import build_conversion_source
from app.catalog_detail import derive_catalog_source, resolve_source_payload
from app.config import settings
from app.conversion_job import ConversionError
from app.document_store import (
    BACKEND_DB,
    BACKEND_FILESYSTEM,
    BACKEND_S3,
    DbDocumentStore,
    FilesystemDocumentStore,
    set_document_store,
)
from app.export_source import load_export_source
from app.original_documents import MANIFEST_MEDIA_TYPE, store_original, store_original_fileset
from app.revision_source import (
    ORIGIN_LEGACY,
    ORIGIN_STORE,
    SOURCE_ROW_KEY,
    CanonicalModelCache,
    RevisionSource,
    attach_revision_source,
    canonical_model_cache,
    has_revision_source,
    revision_source,
    row_has_source,
    source_captured_sql,
    source_from_row,
    source_from_text,
    sourceless_format_metadata_sql,
)
from tests.test_document_store import _s3_store, s3_client  # noqa: F401 - the moto fixture
from tests.test_original_documents import FakeDocumentDatabase, _sha

TENANT = "0b7e6c1e-4a53-4c8e-9d0e-1f2a3b4c5d6e"
OTHER_TENANT = "7c1d2e3f-0000-4c8e-9d0e-1f2a3b4c5d6e"
VERSION = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SDL = "type Query { ping: String }"
OPENAPI = "openapi: 3.1.0\ninfo:\n  title: Pets\n  version: 1.0.0\npaths: {}\n"
PROTO_ROOT = 'syntax = "proto3";\nimport "common.proto";\nmessage Order { Money total = 1; }\n'
PROTO_COMMON = 'syntax = "proto3";\nmessage Money { int64 units = 1; }\n'


class SourceDatabase(FakeDocumentDatabase):
    """The fake document database plus the three reads :mod:`app.revision_source` runs."""

    def __init__(self) -> None:
        super().__init__(versions={VERSION: TENANT})
        self.source_format: Optional[str] = "graphql"
        self.format_metadata: Dict[str, Any] = {}
        self.metadata: Dict[str, Any] = {}
        self.snapshot_text: Optional[str] = None
        self.fail_queries = False
        self.queries: List[str] = []

    def _adapter_captured(self) -> bool:
        pointer = self.format_metadata.get("sourceDocument") or {}
        return bool(pointer.get("sha256") or self.format_metadata.get("sourceContent"))

    def execute_query(self, sql, params=()):
        if self.fail_queries:
            raise RuntimeError("connection refused")
        self.queries.append(sql)
        if sql == module._ORIGINALS_SQL:
            version_id, object_tenant, project_tenant = params
            if self.versions.get(version_id) != project_tenant or object_tenant != project_tenant:
                return []
            rows = []
            for path, object_id in self.documents.get(version_id, {}).items():
                obj = self._object(object_id)
                rows.append(
                    {
                        "role": "original" if path is None else "original_part",
                        "part_path": path,
                        "sha256": obj["sha256"],
                        "media_type": obj["media_type"],
                        "encoding": obj["encoding"],
                        "source_format": self.source_format,
                        "adapter_captured": self._adapter_captured(),
                    }
                )
            return sorted(rows, key=lambda row: (row["role"] != "original", row["part_path"] or ""))
        if sql == module._LEGACY_SQL:
            version_id, tenant_id = params
            if self.versions.get(version_id) != tenant_id:
                return []
            return [
                {
                    "source_format": self.source_format,
                    "format_metadata": self.format_metadata,
                    "metadata": self.metadata,
                    "snapshot_text": self.snapshot_text,
                }
            ]
        if sql == module._AVAILABLE_SQL:
            _object_tenant, version_id, tenant_id = params
            if self.versions.get(version_id) != tenant_id:
                return []
            return [
                {
                    "stored": None in self.documents.get(version_id, {}),
                    "adapter_captured": self._adapter_captured(),
                    "snapshot_text": bool(self.snapshot_text),
                }
            ]
        raise AssertionError(f"unexpected query: {sql[:60]}")

    def capture(self, text: str, **kwargs: Any) -> None:
        """Record ``text`` the way an adapter import does: the object, then the pointer."""
        stored = store_original(TENANT, VERSION, text, database=self, **kwargs)
        assert stored is not None
        self.format_metadata["sourceDocument"] = stored.pointer()


@pytest.fixture(params=[BACKEND_DB, BACKEND_FILESYSTEM, BACKEND_S3])
def env(request, tmp_path, monkeypatch):
    """A fake database and a document store on each of the three backends."""
    database = SourceDatabase()
    if request.param == BACKEND_DB:
        store = DbDocumentStore(prefix="apiome", database=database)
    elif request.param == BACKEND_FILESYSTEM:
        store = FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome")
    else:
        store = _s3_store(request.getfixturevalue("s3_client"))
    monkeypatch.setattr(settings, "document_store", request.param)
    monkeypatch.setattr("app.database.db", database)
    set_document_store(store)
    return {"db": database, "store": store, "backend": request.param}


def _zip(members: Dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, text in members.items():
            archive.writestr(path, text)
    return buffer.getvalue()


class TestStoreFirst:
    """The stored original is what a reader gets, on every backend."""

    def test_a_single_document_comes_back_with_its_digest_and_format(self, env):
        env["db"].capture(SDL, filename="schema.graphql")
        source = revision_source(env["db"], env["store"], TENANT, VERSION)
        assert source == RevisionSource(
            text=SDL,
            digest=_sha(SDL.encode()),
            format="graphql",
            media_type="text/plain",
            origin=ORIGIN_STORE,
        )
        assert not source.is_fileset and source.size_bytes == len(SDL)

    def test_a_gzip_coded_document_is_decoded(self, env, monkeypatch):
        monkeypatch.setattr(settings, "document_store_gzip_min_bytes", 64)
        text = SDL + "\n" + "# padding\n" * 200
        env["db"].capture(text)
        assert env["db"].original(VERSION)["encoding"] == "gzip"
        source = revision_source(env["db"], env["store"], TENANT, VERSION)
        assert source.text == text and source.digest == _sha(text.encode())

    def test_the_store_wins_over_a_legacy_column_that_disagrees(self, env):
        env["db"].capture(SDL)
        env["db"].format_metadata["sourceContent"] = "type Query { stale: String }"
        assert revision_source(env["db"], env["store"], TENANT, VERSION).text == SDL

    def test_a_set_of_files_comes_back_with_every_file_and_its_root(self, env):
        database = env["db"]
        database.source_format = "protobuf"
        stored = store_original_fileset(
            TENANT,
            VERSION,
            {"orders.proto": PROTO_ROOT.encode(), "common.proto": PROTO_COMMON.encode(), "logo.bin": b"\xff\xfe"},
            root="orders.proto",
            database=database,
        )
        database.format_metadata["sourceDocument"] = stored.pointer()
        source = revision_source(database, env["store"], TENANT, VERSION)
        assert source.is_fileset and source.root == "orders.proto"
        assert source.text == PROTO_ROOT and source.media_type == MANIFEST_MEDIA_TYPE
        assert source.digest == stored.content_sha256
        assert dict(source.members) == {
            "orders.proto": PROTO_ROOT.encode(),
            "common.proto": PROTO_COMMON.encode(),
            "logo.bin": b"\xff\xfe",
        }
        fileset = source.intake_fileset()
        assert fileset.root == "orders.proto" and fileset.members["common.proto"] == PROTO_COMMON
        assert fileset.binary_members == {"logo.bin": b"\xff\xfe"}

    def test_another_tenant_reads_nothing(self, env):
        env["db"].capture(SDL)
        assert revision_source(env["db"], env["store"], OTHER_TENANT, VERSION) is None

    def test_missing_ids_read_nothing(self, env):
        assert revision_source(env["db"], env["store"], "", VERSION) is None
        assert revision_source(env["db"], env["store"], TENANT, "") is None


class TestLegacyFallback:
    """A revision with no stored original is read from the legacy columns."""

    def test_the_format_metadata_column_is_read_when_the_store_has_nothing(self, env):
        env["db"].format_metadata = {"sourceContent": SDL}
        source = revision_source(env["db"], env["store"], TENANT, VERSION)
        assert (source.text, source.origin, source.format) == (SDL, ORIGIN_LEGACY, "graphql")
        assert source.digest == _sha(SDL.encode()) and not source.decomposed

    def test_the_legacy_column_is_read_when_the_object_is_gone(self, env):
        env["db"].capture(SDL)
        env["store"].delete(TENANT, env["db"].original(VERSION)["sha256"])
        env["db"].format_metadata["sourceContent"] = SDL
        assert revision_source(env["db"], env["store"], TENANT, VERSION).origin == ORIGIN_LEGACY

    def test_a_legacy_archive_is_unpacked_into_its_files(self, env):
        archive = base64.standard_b64encode(
            _zip({"orders.proto": PROTO_ROOT, "common.proto": PROTO_COMMON})
        ).decode()
        env["db"].source_format = "protobuf"
        env["db"].format_metadata = {
            "sourceContent": archive,
            "sourceEncoding": "base64",
            "intakeKind": "archive",
            "filesetRoot": "orders.proto",
        }
        source = revision_source(env["db"], env["store"], TENANT, VERSION)
        assert source.root == "orders.proto" and source.text == PROTO_ROOT
        assert set(source.members) == {"orders.proto", "common.proto"}

    def test_a_legacy_archive_that_does_not_unpack_reads_as_its_text(self, env):
        env["db"].format_metadata = {
            "sourceContent": "not-base64-zip",
            "sourceEncoding": "base64",
            "intakeKind": "archive",
        }
        source = revision_source(env["db"], env["store"], TENANT, VERSION)
        assert source.text == "not-base64-zip" and not source.is_fileset

    def test_nothing_captured_reads_nothing(self, env):
        assert revision_source(env["db"], env["store"], TENANT, VERSION) is None

    def test_a_failing_database_reads_nothing_instead_of_raising(self, env):
        env["db"].capture(SDL)
        env["db"].fail_queries = True
        assert revision_source(env["db"], env["store"], TENANT, VERSION) is None

    def test_a_database_double_that_returns_no_rows_reads_nothing(self):
        assert revision_source(MagicMock(), MagicMock(), TENANT, VERSION) is None


class TestDecomposedImports:
    """A document a decomposing import read is for provenance, not for model rebuilds."""

    def test_the_worker_original_is_hidden_from_model_rebuilds(self, env):
        env["db"].source_format = "openapi"
        assert store_original(TENANT, VERSION, OPENAPI, database=env["db"]) is not None
        assert revision_source(env["db"], env["store"], TENANT, VERSION) is None
        source = revision_source(env["db"], env["store"], TENANT, VERSION, decomposed=True)
        assert source.text == OPENAPI and source.decomposed and source.origin == ORIGIN_STORE

    def test_the_snapshot_column_is_the_legacy_fallback(self, env):
        env["db"].snapshot_text = OPENAPI
        assert revision_source(env["db"], env["store"], TENANT, VERSION) is None
        source = revision_source(env["db"], env["store"], TENANT, VERSION, decomposed=True)
        assert (source.text, source.origin, source.decomposed) == (OPENAPI, ORIGIN_LEGACY, True)

    def test_availability_matches_what_a_read_would_find(self, env):
        database = env["db"]
        assert has_revision_source(database, TENANT, VERSION, decomposed=True) is False
        database.snapshot_text = OPENAPI
        assert has_revision_source(database, TENANT, VERSION) is False
        assert has_revision_source(database, TENANT, VERSION, decomposed=True) is True
        database.capture(SDL)
        assert has_revision_source(database, TENANT, VERSION) is True
        assert has_revision_source(database, OTHER_TENANT, VERSION, decomposed=True) is False
        assert has_revision_source(database, "", VERSION) is False


class TestReadersOnEveryBackend:
    """Export, conversion and provenance read the stored original on all three backends."""

    def _projection(self, database: SourceDatabase) -> Dict[str, Any]:
        return {
            "id": PROJECT,
            "project_slug": "ping",
            "version_label": "1.0.0",
            "source_format": database.source_format,
            "protocol": "graphql",
            # What the projection query returns: the bag without the source text.
            "format_metadata": {k: v for k, v in database.format_metadata.items() if k != "sourceContent"},
            "tool_versions": {},
            "metadata": {},
        }

    def test_export_rebuilds_the_model_from_the_stored_original(self, env):
        database = env["db"]
        database.capture(SDL, filename="schema.graphql")
        database.get_version_source_projection = lambda *_a: self._projection(database)
        with patch("app.export_source.db", database), patch("app.export_source.attach_plans"):
            source = load_export_source(TENANT, PROJECT, VERSION)
        assert source.source_text == SDL and source.api.format == "graphql"

    def test_export_of_a_revision_with_no_source_says_so(self, env):
        database = env["db"]
        database.get_version_source_projection = lambda *_a: self._projection(database)
        with patch("app.export_source.db", database), pytest.raises(Exception) as raised:
            load_export_source(TENANT, PROJECT, VERSION)
        assert raised.value.status_code == 422 and raised.value.code == "source-not-captured"

    def test_conversion_reads_a_stored_single_document(self, env):
        env["db"].capture(SDL)
        item = attach_revision_source(
            {"id": PROJECT, "source_format": "graphql", "format_metadata": {}},
            tenant_id=TENANT,
            version_id=VERSION,
            db=env["db"],
            store=env["store"],
        )
        source = build_conversion_source(item, source_version_id=VERSION)
        assert source.source_text == SDL and source.api.format == "graphql"

    def test_conversion_reads_a_stored_set_of_files(self, env):
        database = env["db"]
        database.source_format = "protobuf"
        stored = store_original_fileset(
            TENANT,
            VERSION,
            {"orders.proto": PROTO_ROOT.encode(), "common.proto": PROTO_COMMON.encode()},
            root="orders.proto",
            database=database,
        )
        database.format_metadata["sourceDocument"] = stored.pointer()
        item = attach_revision_source(
            {"id": PROJECT, "source_format": "protobuf", "format_metadata": {"intakeKind": "archive"}},
            tenant_id=TENANT,
            version_id=VERSION,
            db=database,
            store=env["store"],
        )
        adapter = MagicMock()
        adapter.normalize.return_value = CanonicalApi.model_construct()
        with patch("app.catalog_conversion.resolve_conversion_adapter", return_value=adapter):
            build_conversion_source(item)
        fileset = adapter.parse_fileset.call_args.args[0]
        assert fileset.root == "orders.proto" and set(fileset.members) == {"orders.proto", "common.proto"}
        assert adapter.parse_fileset.call_args.kwargs == {"source_label": "orders.proto"}

    def test_the_source_download_serves_the_stored_text(self, env):
        env["db"].capture(SDL)
        item = attach_revision_source(
            {"id": PROJECT, "slug": "ping", "source_format": "graphql", "format_metadata": {}},
            tenant_id=TENANT,
            version_id=VERSION,
            db=env["db"],
            store=env["store"],
        )
        payload = resolve_source_payload(item)
        assert (payload["mode"], payload["content"], payload["filename"]) == ("content", SDL, "ping.graphql")

    def test_the_served_text_and_its_hash_do_not_depend_on_where_the_source_is_kept(self, env):
        from app.conversion_evidence import current_source_digest

        text = SDL + "\n"
        legacy = {"id": PROJECT, "source_format": "graphql", "format_metadata": {"sourceContent": text}}
        env["db"].capture(text)
        stored = attach_revision_source(
            {"id": PROJECT, "source_format": "graphql", "format_metadata": {}},
            tenant_id=TENANT,
            version_id=VERSION,
            db=env["db"],
            store=env["store"],
        )
        assert source_from_row(stored).text == text  # the helper keeps the exact document
        assert resolve_source_payload(stored)["content"] == resolve_source_payload(legacy)["content"] == SDL
        assert current_source_digest(stored) == current_source_digest(legacy)
        assert build_conversion_source(stored).source_text == build_conversion_source(legacy).source_text

    def test_provenance_reads_the_document_a_decomposed_import_stored(self, env):
        env["db"].source_format = "openapi"
        store_original(TENANT, VERSION, OPENAPI, database=env["db"], keep_existing=True)
        source = revision_source(env["db"], env["store"], TENANT, VERSION, decomposed=True)
        assert source.text == OPENAPI


class TestRows:
    """Reading a source off a row a caller already holds."""

    def test_an_attached_source_wins_over_legacy_keys(self):
        attached = source_from_text(SDL, source_format="graphql")
        row = {SOURCE_ROW_KEY: attached, "format_metadata": {"sourceContent": "stale"}}
        assert source_from_row(row) is attached

    def test_legacy_keys_are_read_from_the_revision_then_the_project(self):
        assert source_from_row({"format_metadata": {"sourceContent": f"  {SDL}\n"}}).text == SDL
        assert source_from_row({"format_metadata": {}, "metadata": {"rawSource": SDL}}).text == SDL
        assert source_from_row({"format_metadata": {"sourceContent": "   "}}) is None
        assert source_from_row({"format_metadata": "not-a-bag"}) is None
        assert source_from_row(None) is None

    def test_a_catalog_item_row_reads_its_latest_revision_from_the_store(self, env):
        env["db"].capture(SDL)
        row = {"tenant_id": TENANT, "latest_version_id": VERSION, "source_captured": True, "format_metadata": {}}
        assert source_from_row(row).text == SDL
        assert source_from_row({**row, "source_captured": False}) is None

    def test_attach_copies_the_row_and_leaves_one_without_a_source_alone(self, env):
        row = {"id": PROJECT, "format_metadata": {"sourceContent": SDL}}
        attached = attach_revision_source(row, tenant_id=TENANT, version_id=VERSION, db=env["db"], store=env["store"])
        assert attached is not row and source_from_row(attached).origin == ORIGIN_LEGACY
        bare = attach_revision_source({"id": PROJECT}, tenant_id=None, version_id=None)
        assert bare == {"id": PROJECT}

    def test_attach_keeps_a_source_already_on_the_row(self, env):
        env["db"].capture(SDL)
        mine = source_from_text("type Query { mine: Int }")
        row = attach_revision_source(
            {SOURCE_ROW_KEY: mine}, tenant_id=TENANT, version_id=VERSION, db=env["db"], store=env["store"]
        )
        assert row[SOURCE_ROW_KEY] is mine

    def test_row_has_source_does_not_need_the_text(self):
        assert row_has_source({"source_captured": True, "format_metadata": {}}) is True
        assert row_has_source({"format_metadata": {"sourceContent": SDL}}) is True
        assert row_has_source({SOURCE_ROW_KEY: source_from_text(SDL)}) is True
        assert row_has_source({"source_captured": False, "format_metadata": {"sourceLabel": "a.graphql"}}) is False
        assert row_has_source(None) is False

    def test_the_catalog_descriptor_uses_the_captured_flag(self):
        assert derive_catalog_source({"sourceLabel": "a.graphql"}, None, True)["has_content"] is True
        assert derive_catalog_source({"sourceLabel": "a.graphql"}, None, False)["has_content"] is False
        assert derive_catalog_source({"sourceContent": SDL}, None)["downloadable"] is True

    def test_a_row_with_no_source_cannot_be_converted(self):
        with pytest.raises(ConversionError) as raised:
            build_conversion_source({"id": PROJECT, "source_format": "graphql", "format_metadata": {}})
        assert raised.value.code == "source-not-captured"


class TestSqlFragments:
    """Version queries leave the source text out and still say whether there is one."""

    def test_the_metadata_expression_drops_only_the_source_text(self):
        assert sourceless_format_metadata_sql("cv") == "(cv.format_metadata - 'sourceContent')"

    def test_the_captured_expression_covers_the_store_and_the_legacy_column(self):
        sql = source_captured_sql("v")
        assert "v.format_metadata -> 'sourceDocument' ->> 'sha256'" in sql
        assert "v.format_metadata ->> 'sourceContent'" in sql

    def test_the_catalog_and_projection_queries_use_them(self):
        from app.database import Database

        lateral = Database._CATALOG_VERSION_LATERAL
        assert "(v.format_metadata - 'sourceContent') AS format_metadata" in lateral
        assert "AS source_captured" in lateral and "AS latest_version_id" in lateral
        assert "v.format_metadata," not in lateral


def _model(title: str = "t") -> CanonicalApi:
    api = CanonicalApi.model_construct()
    object.__setattr__(api, "extras", {"title": title})
    return api


class TestCanonicalModelCache:
    """Parsed models are kept by source digest, bounded in count and in source bytes."""

    def test_a_second_read_does_not_parse_again_and_gets_its_own_copy(self):
        cache = CanonicalModelCache(max_entries=4, max_source_bytes=1000)
        builds = []

        def build():
            builds.append(1)
            return _model()

        first = cache.get_or_build(("d1",), 10, build)
        first.extras["mutated"] = True
        second = cache.get_or_build(("d1",), 10, build)
        assert len(builds) == 1 and (cache.hits, cache.misses) == (1, 1)
        assert second is not first and "mutated" not in second.extras

    def test_the_least_recently_used_model_goes_when_the_count_is_reached(self):
        cache = CanonicalModelCache(max_entries=2, max_source_bytes=1000)
        for key in ("a", "b"):
            cache.get_or_build((key,), 10, _model)
        cache.get_or_build(("a",), 10, _model)  # "a" is now the most recent
        cache.get_or_build(("c",), 10, _model)
        builds = []
        cache.get_or_build(("a",), 10, lambda: builds.append("a") or _model())
        cache.get_or_build(("b",), 10, lambda: builds.append("b") or _model())
        assert builds == ["b"] and len(cache) == 2

    def test_models_go_when_their_sources_pass_the_byte_limit(self):
        cache = CanonicalModelCache(max_entries=10, max_source_bytes=100)
        for key in ("a", "b", "c", "d", "e"):
            cache.get_or_build((key,), 25, _model)
        assert len(cache) == 4 and cache.source_bytes == 100

    def test_a_source_over_a_quarter_of_the_byte_limit_is_not_kept(self):
        cache = CanonicalModelCache(max_entries=10, max_source_bytes=100)
        cache.get_or_build(("big",), 26, _model)
        assert len(cache) == 0 and cache.misses == 1

    @pytest.mark.parametrize("entries,max_bytes", [(0, 100), (10, 0)])
    def test_a_zero_limit_turns_the_cache_off(self, entries, max_bytes):
        cache = CanonicalModelCache(max_entries=entries, max_source_bytes=max_bytes)
        builds = []
        for _ in range(2):
            cache.get_or_build(("a",), 1, lambda: builds.append(1) or _model())
        assert not cache.enabled and len(builds) == 2 and len(cache) == 0

    def test_a_failed_parse_is_not_kept(self):
        cache = CanonicalModelCache(max_entries=4, max_source_bytes=1000)

        def fail():
            raise ValueError("does not parse")

        with pytest.raises(ValueError):
            cache.get_or_build(("a",), 10, fail)
        assert len(cache) == 0

    def test_clear_empties_the_cache(self):
        cache = CanonicalModelCache(max_entries=4, max_source_bytes=1000)
        cache.get_or_build(("a",), 10, _model)
        cache.clear()
        assert (len(cache), cache.source_bytes, cache.hits, cache.misses) == (0, 0, 0, 0)

    def test_the_process_cache_is_sized_from_the_settings(self, monkeypatch):
        monkeypatch.setattr(module, "_cache", None)
        monkeypatch.setattr(settings, "canonical_model_cache_entries", 3)
        monkeypatch.setattr(settings, "canonical_model_cache_max_bytes", 4096)
        cache = canonical_model_cache()
        assert (cache._max_entries, cache._max_bytes) == (3, 4096)
        assert canonical_model_cache() is cache

    def test_conversion_parses_the_same_source_once(self):
        item = {"id": PROJECT, "source_format": "graphql", "format_metadata": {"sourceContent": SDL}}
        first = build_conversion_source(item)
        first.api.extras["plans"] = ["changed by a reader"]
        second = build_conversion_source(item)
        cache = canonical_model_cache()
        assert (cache.hits, cache.misses) == (1, 1)
        assert "plans" not in second.api.extras and second.api.format == "graphql"
