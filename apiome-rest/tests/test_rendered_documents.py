"""The rendered document cache — COA-5.5 (#7081).

:mod:`app.rendered_documents` with an in-memory database and a real filesystem document store:
the key, hits and misses, single-flight, the failure paths, the HTTP validators and the frozen
schema helpers. The same flow on the real tables, the query count against Postgres and the byte
equality across the OpenAPI corpus are in ``tests/test_rendered_documents_db.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

import app.database as database_module
import app.rendered_documents as rendered
from app.document_store import DocumentNotFound, FilesystemDocumentStore
from app.rendered_documents import (
    CANONICAL_GENERATOR,
    CANONICAL_GENERATOR_VERSION,
    KIND_CANONICAL,
    KIND_OPENAPI,
    KIND_OPENAPI_MEMBERS,
    MEMBERS_OPENAPI_VERSION,
    OPENAPI_GENERATOR,
    ROLE_FROZEN_SCHEMA,
    ROLE_RENDERED_CANONICAL,
    ROLE_RENDERED_OPENAPI,
    ROLE_RENDERED_OPENAPI_MEMBERS,
    etag_for,
    etag_matches,
    iter_stream,
    open_frozen_schema,
    rendered_document,
    store_frozen_schema,
    warm_rendered_documents,
)
from app.spec_snapshot import render_spec_bytes

TENANT = "tenant-1"
VERSION = "11111111-1111-4111-8111-111111111111"


class FakeDatabase:
    """The slice of the database layer the cache and the generator read, with a call log."""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.context: Optional[Dict[str, Any]] = {
            "id": VERSION,
            "version_id": "1.0.0",
            "metadata": None,
            "content_stamp": 0,
            "published": False,
            "project_slug": "orders",
            "project_description": "Orders API",
            "project_metadata": {"team": "payments"},
            "tenant_slug": "acme",
        }
        self.classes: List[Dict[str, Any]] = [
            {"id": "c1", "name": "Order", "description": "An order", "schema": {"type": "object"}}
        ]
        self.properties: Dict[str, List[Dict[str, Any]]] = {
            "c1": [{"id": "p1", "class_id": "c1", "name": "id", "data": {"type": "string"}, "parent_id": None}]
        }
        self.objects: Dict[str, Dict[str, Any]] = {}
        self.documents: Dict[Tuple[Any, ...], str] = {}
        self.canonical: Any = None
        self.paths: List[Dict[str, Any]] = []
        self.operations: Dict[str, List[Dict[str, Any]]] = {}
        self.descriptions: Dict[str, Dict[str, Any]] = {}
        self.render_delay = 0.0
        self.fail_find = False
        self.fail_set = False

    # -- the cache's own reads and writes --

    def get_rendered_document_context(self, *, tenant_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        self.calls.append("context")
        if self.context is None or tenant_id != TENANT or version_id != VERSION:
            return None
        return dict(self.context)

    def find_version_document(self, *, tenant_id, version_id, role, content_stamp=None, generator=None,
                              generator_version=None) -> Optional[Dict[str, Any]]:
        self.calls.append("find")
        if self.fail_find:
            raise RuntimeError("database down")
        object_id = self.documents.get((version_id, role, content_stamp, generator, generator_version))
        return dict(self.objects[object_id], object_id=object_id) if object_id else None

    def upsert_document_object(self, *, tenant_id, sha256, size_bytes, media_type, encoding, backend,
                               storage_key) -> str:
        self.calls.append("upsert_object")
        self.objects[sha256] = {
            "sha256": sha256, "size_bytes": size_bytes, "media_type": media_type, "encoding": encoding,
        }
        return sha256

    def set_version_document(self, *, tenant_id, version_id, role, object_id, content_stamp=None,
                             generator=None, generator_version=None) -> bool:
        self.calls.append("set")
        if self.fail_set:
            raise RuntimeError("database down")
        self.documents[(version_id, role, content_stamp, generator, generator_version)] = object_id
        return True

    # -- what a render reads --

    def get_classes_for_version(self, version_id: str) -> List[Dict[str, Any]]:
        self.calls.append("classes")
        if self.render_delay:
            time.sleep(self.render_delay)
        return [dict(row) for row in self.classes]

    def get_properties_for_classes(self, class_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        self.calls.append("properties")
        return {class_id: list(self.properties.get(class_id, [])) for class_id in class_ids}

    def load_paths_for_version(self, version_id: str) -> list:
        """The set-based path loader (DBP-1.6, #7189): paths with their operations' details."""
        return [
            {
                **path,
                "operations": [
                    {
                        "id": op["id"],
                        "operation": op["operation"],
                        "metadata": op.get("metadata"),
                        "description": self.descriptions.get(op["id"]),
                        "parameters": [],
                        "requestBody": None,
                        "responses": [],
                    }
                    for op in self.operations.get(path["id"], [])
                ],
            }
            for path in self.paths
        ]

    def get_security_schemes_for_version(self, version_id: str) -> list:
        return []

    def get_servers_for_version(self, version_id: str) -> list:
        return []

    def get_materializable_pins_for_version(self, version_id: str) -> list:
        return []

    def load_canonical_api(self, *, tenant_id: str, version_id: str) -> Any:
        self.calls.append("canonical")
        return self.canonical

    def renders(self) -> int:
        """How many times the class rows were loaded: one per OpenAPI render."""
        return self.calls.count("classes")


@pytest.fixture
def db(monkeypatch) -> FakeDatabase:
    """The fake database, also installed as the one the OpenAPI generator reads paths from."""
    fake = FakeDatabase()
    monkeypatch.setattr(database_module, "db", fake)
    return fake


@pytest.fixture
def store(tmp_path) -> FilesystemDocumentStore:
    return FilesystemDocumentStore(path=str(tmp_path), prefix="apiome")


def _get(db: FakeDatabase, store: Any, kind: str = KIND_OPENAPI):
    return rendered_document(VERSION, kind, tenant_id=TENANT, database=db, store=store)


# ───────────────────────────── miss, then hit ─────────────────────────────


def test_a_miss_renders_stores_and_records_the_document(db, store) -> None:
    document = _get(db, store)

    assert document is not None and document.cached is False and document.stored is True
    content = document.content()
    assert json.loads(content)["components"]["schemas"]["Order"]["properties"]["id"] == {"type": "string"}
    assert document.sha256 == hashlib.sha256(content).hexdigest()
    assert document.size_bytes == len(content)
    assert document.etag == f'"{document.sha256}"'
    assert store.get(TENANT, document.sha256) == content
    [(key, object_id)] = db.documents.items()
    assert key[:4] == (VERSION, ROLE_RENDERED_OPENAPI, 0, OPENAPI_GENERATOR)
    assert key[4] == document.generator_version and key[4].startswith("2+")
    assert db.objects[object_id]["encoding"] == "identity"
    assert db.objects[object_id]["media_type"] == "application/json"


def test_the_second_request_reads_no_class_or_property_rows(db, store) -> None:
    first = _get(db, store)
    db.calls.clear()

    second = _get(db, store)

    assert second.cached is True and second.stored is True
    assert db.calls == ["context", "find"]
    assert second.content() == first.content()
    assert (second.sha256, second.size_bytes) == (first.sha256, first.size_bytes)
    assert second.json() == first.json()
    with second.open_stream() as stream:
        assert stream.read() == first.content()


def test_the_bytes_are_what_the_generator_sends(db, store) -> None:
    from app.openapi_generator import generate_openapi_spec

    expected = render_spec_bytes(
        generate_openapi_spec(
            "acme", "orders", "1.0.0", db.classes, db.properties, "Orders API",
            version_db_id=VERSION, revision_metadata=None, project_metadata={"team": "payments"},
        )
    )
    assert _get(db, store).content() == expected
    assert _get(db, store).content() == expected  # and again from the store


def test_a_revision_row_is_accepted_in_place_of_its_id(db, store) -> None:
    document = rendered_document({"id": VERSION}, tenant_id=TENANT, database=db, store=store)
    assert document is not None and document.version_id == VERSION


# ───────────────────────────── what changes the key ─────────────────────────────


def test_an_edit_bumps_the_stamp_and_the_next_read_renders_again(db, store) -> None:
    before = _get(db, store)
    db.properties["c1"].append({"id": "p2", "class_id": "c1", "name": "total", "data": {"type": "number"}})
    db.context["content_stamp"] = 1

    after = _get(db, store)

    assert after.cached is False and after.content_stamp == 1
    assert after.sha256 != before.sha256 and "total" in after.content().decode()
    assert db.renders() == 2
    # The older row and object are left for the lifecycle job.
    assert len(db.documents) == 2
    assert store.exists(TENANT, before.sha256) and store.exists(TENANT, after.sha256)


@pytest.mark.parametrize(
    ("field", "value"),
    [("project_slug", "orders-v2"), ("project_description", "Renamed"), ("project_metadata", {"team": "core"})],
)
def test_a_project_change_misses_although_the_stamp_did_not_move(db, store, field, value) -> None:
    before = _get(db, store)
    db.context[field] = value

    after = _get(db, store)

    assert after.cached is False and after.generator_version != before.generator_version
    assert after.sha256 != before.sha256
    assert _get(db, store).cached is True


def test_a_generator_version_bump_misses_and_deletes_nothing(db, store, monkeypatch) -> None:
    before = _get(db, store)
    monkeypatch.setattr(rendered, "OPENAPI_GENERATOR_VERSION", "next")

    after = _get(db, store)

    assert after.cached is False and after.generator_version.startswith("next+")
    assert len(db.documents) == 2 and store.exists(TENANT, before.sha256)
    # Same rows, same generator code: the bytes are one object, referenced by both rows.
    assert after.sha256 == before.sha256 and len(db.objects) == 1


# ───────────────────────────── single-flight ─────────────────────────────


def test_concurrent_requests_for_one_document_render_once(db, store) -> None:
    db.render_delay = 0.05
    results: List[Any] = []
    start = threading.Barrier(8)

    def read() -> None:
        start.wait()
        results.append(_get(db, store))

    threads = [threading.Thread(target=read) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert db.renders() == 1
    assert len({document.sha256 for document in results}) == 1
    assert sum(1 for document in results if not document.cached) == 1
    assert rendered._flights._entries == {}


def test_different_documents_do_not_wait_for_each_other() -> None:
    flights = rendered._SingleFlight()
    with flights.hold(("a",)):
        with flights.hold(("b",)):
            assert set(flights._entries) == {("a",), ("b",)}
    assert flights._entries == {}


# ───────────────────────────── failure paths ─────────────────────────────


def test_unknown_revisions_tenants_and_kinds(db, store) -> None:
    assert rendered_document(VERSION, tenant_id="another-tenant", database=db, store=store) is None
    assert rendered_document("", tenant_id=TENANT, database=db, store=store) is None
    assert rendered_document(VERSION, tenant_id="", database=db, store=store) is None
    with pytest.raises(ValueError, match="Unknown rendered document kind"):
        rendered_document(VERSION, "yaml", tenant_id=TENANT, database=db, store=store)
    assert db.documents == {}


def test_a_failing_store_still_returns_the_rendered_bytes(db) -> None:
    class BrokenStore:
        def exists(self, tenant_id: str, sha256: str) -> bool:
            raise RuntimeError("bucket unreachable")

        def put(self, tenant_id: str, data: bytes, media_type: str) -> Any:
            raise RuntimeError("bucket unreachable")

    document = _get(db, BrokenStore())

    assert document.stored is False and document.cached is False
    assert json.loads(document.content())["info"]["title"] == "orders API"
    assert db.documents == {}


def test_a_store_that_cannot_be_built_still_returns_the_rendered_bytes(db, monkeypatch) -> None:
    def broken() -> Any:
        raise RuntimeError("APIOME_DOCUMENT_STORE_BUCKET is not set")

    monkeypatch.setattr(rendered, "get_document_store", broken)

    document = rendered_document(VERSION, tenant_id=TENANT, database=db)

    assert document.stored is False and document.content().startswith(b'{"openapi"')


def test_a_failing_cache_table_still_returns_the_rendered_bytes(db, store) -> None:
    db.fail_find = True
    db.fail_set = True

    document = _get(db, store)

    assert document.stored is False and document.cached is False
    assert document.content().startswith(b'{"openapi"')


def test_a_row_whose_object_is_gone_is_rendered_again(db, store) -> None:
    first = _get(db, store)
    assert store.delete(TENANT, first.sha256)

    again = _get(db, store)

    assert again.cached is False and again.stored is True
    assert store.get(TENANT, first.sha256) == again.content()


def test_an_object_removed_after_the_lookup_raises_on_read(db, store) -> None:
    _get(db, store)
    hit = _get(db, store)
    store.delete(TENANT, hit.sha256)
    with pytest.raises(DocumentNotFound):
        hit.content()


def test_a_generator_error_is_raised_and_nothing_is_recorded(db, store, monkeypatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("generator bug")

    monkeypatch.setattr(rendered, "build_live_spec", explode)
    with pytest.raises(RuntimeError, match="generator bug"):
        _get(db, store)
    assert db.documents == {} and rendered._flights._entries == {}


# ───────────────────────────── canonical kind and warming ─────────────────────────────


def test_a_revision_without_a_canonical_model_has_no_canonical_document(db, store) -> None:
    assert _get(db, store, KIND_CANONICAL) is None
    assert db.documents == {}


def test_the_canonical_document_is_cached_under_its_own_role(db, store, monkeypatch) -> None:
    import app.canonical_persistence as canonical_persistence

    db.canonical = object()
    monkeypatch.setattr(
        canonical_persistence, "dump_canonical_tree", lambda _model: {"services": [], "artifact": {"name": "é"}}
    )

    first = _get(db, store, KIND_CANONICAL)
    second = _get(db, store, KIND_CANONICAL)

    assert first.content() == '{"artifact":{"name":"é"},"services":[]}'.encode()
    assert (first.cached, second.cached) == (False, True)
    assert db.calls.count("canonical") == 1
    assert list(db.documents) == [
        (VERSION, ROLE_RENDERED_CANONICAL, 0, CANONICAL_GENERATOR, CANONICAL_GENERATOR_VERSION)
    ]


def test_warming_stores_every_kind_the_revision_has(db, store) -> None:
    assert warm_rendered_documents(TENANT, VERSION, database=db, store=store) == 1  # no canonical model
    db.calls.clear()
    assert _get(db, store).cached is True and db.renders() == 0


def test_warming_never_raises(db, store, monkeypatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("generator bug")

    monkeypatch.setattr(rendered, "build_live_spec", explode)
    assert warm_rendered_documents(TENANT, VERSION, database=db, store=store) == 0
    assert warm_rendered_documents(TENANT, "no-such-version", database=db, store=store) == 0


# ───────────────────────────── the members' document (COA-5.13) ─────────────────────────────


def _with_a_private_operation(db: FakeDatabase) -> None:
    """Give the revision ``GET /orders`` (public) and ``DELETE /orders`` (marked private)."""
    db.paths = [{"id": "path-1", "pathname": "/orders"}]
    db.operations = {"path-1": [{"id": "op-1", "operation": "get"}, {"id": "op-2", "operation": "delete"}]}
    db.descriptions = {
        "op-1": {"summary": "List orders", "operation_id": "listOrders", "x_private": False},
        "op-2": {"summary": "Purge orders", "operation_id": "purgeOrders", "x_private": True},
    }


def test_the_members_document_is_openapi_32_and_keeps_private_operations(db, store) -> None:
    _with_a_private_operation(db)

    members = _get(db, store, KIND_OPENAPI_MEMBERS).json()
    public = _get(db, store).json()

    assert members["openapi"] == MEMBERS_OPENAPI_VERSION == "3.2.0"
    assert sorted(members["paths"]["/orders"]) == ["delete", "get"]
    assert members["paths"]["/orders"]["delete"]["x-private"] is True
    assert members["paths"]["/orders"]["get"]["operationId"] == "listOrders"
    assert public["openapi"] == "3.1.0"
    assert sorted(public["paths"]["/orders"]) == ["get"]


def test_the_members_document_is_cached_under_its_own_role(db, store) -> None:
    public = _get(db, store)
    members = _get(db, store, KIND_OPENAPI_MEMBERS)

    assert members.cached is False and members.stored is True and members.sha256 != public.sha256
    roles = sorted(key[1] for key in db.documents)
    assert roles == [ROLE_RENDERED_OPENAPI, ROLE_RENDERED_OPENAPI_MEMBERS]
    [members_key] = [key for key in db.documents if key[1] == ROLE_RENDERED_OPENAPI_MEMBERS]
    assert members_key[3] == OPENAPI_GENERATOR
    assert members_key[4] == members.generator_version and members_key[4].startswith("3.2.0+2+")

    db.calls.clear()
    again = _get(db, store, KIND_OPENAPI_MEMBERS)
    assert again.cached is True and db.renders() == 0 and again.content() == members.content()
    assert _get(db, store).cached is True  # the public document is untouched


def test_an_edit_renders_the_members_document_again(db, store) -> None:
    before = _get(db, store, KIND_OPENAPI_MEMBERS)
    db.context["content_stamp"] = 1
    db.classes[0]["description"] = "A changed order"

    after = _get(db, store, KIND_OPENAPI_MEMBERS)

    assert after.cached is False and after.sha256 != before.sha256


def test_publishing_does_not_warm_the_members_document(db, store) -> None:
    warm_rendered_documents(TENANT, VERSION, database=db, store=store)
    assert [key[1] for key in db.documents] == [ROLE_RENDERED_OPENAPI]


# ───────────────────────────── HTTP validators ─────────────────────────────


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, False),
        ("", False),
        ('"abc"', True),
        ('"ABC"', True),
        ('W/"abc"', True),
        ('"zzz", "abc"', True),
        (' "zzz" , W/"abc" ', True),
        ("*", True),
        ('"zzz"', False),
        ("abc", False),
        ('"abc', False),
    ],
)
def test_etag_matches(header: Optional[str], expected: bool) -> None:
    assert etag_matches(header, "abc") is expected


def test_etag_for_quotes_the_digest() -> None:
    assert etag_for("ab" * 32 + " ") == '"' + "ab" * 32 + '"'


def test_iter_stream_yields_chunks_and_closes() -> None:
    stream = io.BytesIO(b"abcdefg")
    assert list(iter_stream(stream, 3)) == [b"abc", b"def", b"g"]
    assert stream.closed


def test_iter_stream_closes_when_the_consumer_stops_early() -> None:
    stream = io.BytesIO(b"abcdefg")
    chunks = iter_stream(stream, 3)
    assert next(chunks) == b"abc"
    chunks.close()
    assert stream.closed


# ───────────────────────────── frozen schemas ─────────────────────────────


def test_a_frozen_schema_is_stored_linked_and_read_back(db, store) -> None:
    content = b'{"openapi":"3.1.0","frozen":true}'
    sha256 = hashlib.sha256(content).hexdigest()

    assert store_frozen_schema(TENANT, VERSION, content, database=db, store=store) is True

    assert db.documents == {(VERSION, ROLE_FROZEN_SCHEMA, None, None, None): sha256}
    with open_frozen_schema(TENANT, sha256, store=store) as stream:
        assert stream.read() == content


def test_a_frozen_schema_that_cannot_be_stored_reports_false(db, store) -> None:
    db.fail_set = True
    assert store_frozen_schema(TENANT, VERSION, b"{}", database=db, store=store) is False
    assert store_frozen_schema("", VERSION, b"{}", database=db, store=store) is False


def test_a_missing_frozen_object_reads_as_none(store) -> None:
    assert open_frozen_schema(TENANT, "ab" * 32, store=store) is None
    assert open_frozen_schema("", "ab" * 32, store=store) is None
