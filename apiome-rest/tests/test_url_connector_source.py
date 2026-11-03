"""The catalog ``url`` connector source (RAR-6.1b, #6467).

The real :class:`app.url_connector_source.UrlConnectorSource` runs through
:func:`app.catalog_connector_sync.run_connector_sync` over the in-memory connector store
(:mod:`tests.catalog_connector_fakes`), with a stand-in importer and an ``httpx.MockTransport``
behind the real guarded client (:func:`app.catalog_connectors.build_connector_http_client`). No
network and no Postgres; the V352 backfill and the workspace query are checked on a scratch
database by hand (see the PR).

Covers the acceptance criteria: 304 → an unchanged run, 200 with new content → a new catalog
revision, the same content → no revision; a backfilled (workspace-mode) item is anchored on its
first run without a re-import, then refreshed like any connector item; runs land on the ledger.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

import httpx
import pytest
from catalog_connector_fakes import FakeConnectorStore, FakeDb

from app import catalog_connectors
from app import url_connector_source as src
from app.catalog_connector_sync import (
    connector_accepts_credentials,
    run_connector_sync,
    syncable_kinds,
    validate_connector_scope,
)
from app.catalog_connectors import ConnectorError
from app.config import settings

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"
ITEM_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ITEM_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _openapi(title: str, version: str = "1.0.0") -> bytes:
    doc = {"openapi": "3.0.3", "info": {"title": title, "version": version}, "paths": {}}
    return json.dumps(doc).encode()


class Upstream:
    """URL → document, answering conditional GETs with an ETag of the body's digest."""

    def __init__(self) -> None:
        self.documents: Dict[str, bytes] = {}
        self.status: Dict[str, int] = {}
        self.requests: List[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url in self.status:
            return httpx.Response(self.status[url])
        body = self.documents.get(url)
        if body is None:
            return httpx.Response(404)
        etag = '"' + hashlib.sha256(body).hexdigest()[:12] + '"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        return httpx.Response(200, content=body, headers={"etag": etag, "content-type": "application/json"})


class WorkspaceDb(FakeDb):
    """FakeDb plus the two queries workspace mode runs (URL-sourced items, the acting connector)."""

    def __init__(self, store: FakeConnectorStore) -> None:
        super().__init__()
        self.store = store
        self.url_items: List[Dict[str, Any]] = []

    def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
        if "FROM apiome.projects p" in sql:
            return [dict(i) for i in self.url_items]
        if "FROM apiome.catalog_connectors" in sql:
            rows = [
                c
                for c in self.store.connectors.values()
                if c["tenant_id"] == params[0]
                and c["kind"] == "url"
                and c["deleted_at"] is None
                and not (c.get("base_url") or "").strip()
            ]
            rows.sort(key=lambda c: (c["created_at"], c["id"]))
            return [{"id": c["id"]} for c in rows[:1]]
        raise AssertionError(f"unexpected query: {sql}")


class Importer:
    """Stands in for the catalog import: records each call, returns the item id."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, connector, candidate, document, item_row, actor_id) -> str:
        self.calls.append(
            {
                "remote_id": candidate.remote_id,
                "kind": document.import_kind,
                "content": document.content,
                "revision": document.revision,
                "project_id": item_row.get("project_id"),
                "source_uri": document.source_uri,
            }
        )
        return item_row.get("project_id") or f"item-for-{candidate.remote_id}"


@pytest.fixture
def store(monkeypatch) -> FakeConnectorStore:
    return FakeConnectorStore().install(monkeypatch)


@pytest.fixture
def upstream(monkeypatch) -> Upstream:
    """Route the connector's guarded client to the fake upstream; allow test hosts."""
    up = Upstream()
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    real_build = catalog_connectors.build_connector_http_client
    monkeypatch.setattr(
        catalog_connectors,
        "build_connector_http_client",
        lambda **kw: real_build(transport=httpx.MockTransport(up.handler), **kw),
    )
    return up


def _sync(store: FakeConnectorStore, db: Any, connector: Dict[str, Any], importer: Importer):
    result = run_connector_sync(db, store.connectors[connector["id"]], actor_id=ACTOR, importer=importer)
    return store.runs[result.run_id]["run_summary"]


def _refuse_host(monkeypatch, host: str) -> None:
    """Make the connector rule refuse one host (as it would a private address)."""
    real = catalog_connectors.connector_base_url_from_settings

    def check(raw: str) -> str:
        if host in raw:
            raise ConnectorError(catalog_connectors.CODE_BASE_URL_REFUSED, f"host {host!r} is private")
        return real(raw)

    monkeypatch.setattr(catalog_connectors, "connector_base_url_from_settings", check)


# ---------------------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------------------


def test_url_kind_is_registered_without_credentials():
    assert "url" in syncable_kinds()
    assert connector_accepts_credentials("url") is False


def test_url_kind_takes_no_scope():
    validate_connector_scope("url", {}, None)
    validate_connector_scope("url", {}, "https://specs.example.com/openapi.json")
    with pytest.raises(ConnectorError) as err:
        validate_connector_scope("url", {"organization": "acme"}, None)
    assert "takes no scope" in str(err.value)


# ---------------------------------------------------------------------------------------
# Single-URL mode
# ---------------------------------------------------------------------------------------

SPEC = "https://specs.example.com/openapi.json"


def test_single_url_imports_then_304_is_unchanged(store, upstream):
    upstream.documents[SPEC] = _openapi("Orders")
    connector = store.add_connector(TENANT, kind="url", name="Orders spec", base_url=SPEC)
    importer = Importer()
    db = FakeDb()

    first = _sync(store, db, connector, importer)
    assert first["imported"] == 1
    assert importer.calls[0]["kind"] == "openapi"
    assert importer.calls[0]["source_uri"] == SPEC
    item = store.item(connector["id"], SPEC)
    assert item["status"] == "imported"
    assert item["deployment"]["etag"]

    second = _sync(store, db, connector, importer)
    assert second["unchanged"] == 1 and second["imported"] == 0 and second["fetched"] == 0
    assert len(importer.calls) == 1
    assert upstream.requests[-1].headers.get("if-none-match") == item["deployment"]["etag"]


def test_single_url_new_content_is_a_new_revision_and_same_content_is_not(store, upstream):
    upstream.documents[SPEC] = _openapi("Orders")
    connector = store.add_connector(TENANT, kind="url", name="Orders spec", base_url=SPEC)
    importer = Importer()
    db = FakeDb()
    _sync(store, db, connector, importer)
    project_id = store.item(connector["id"], SPEC)["project_id"]

    upstream.documents[SPEC] = _openapi("Orders", "1.1.0")
    changed = _sync(store, db, connector, importer)
    assert changed["imported"] == 1
    assert importer.calls[-1]["project_id"] == project_id  # a revision of the same item
    assert importer.calls[-1]["content"] == _openapi("Orders", "1.1.0")

    # The server forgets its validators but serves the same bytes: re-anchored, nothing imported.
    store.item(connector["id"], SPEC)["deployment"] = {"url": SPEC}
    same = _sync(store, db, connector, importer)
    assert same["unchanged"] == 1 and same["imported"] == 0
    assert len(importer.calls) == 2


def test_failed_check_is_a_failed_item_and_a_later_304_is_unchanged(store, upstream):
    upstream.documents[SPEC] = _openapi("Orders")
    connector = store.add_connector(TENANT, kind="url", name="Orders spec", base_url=SPEC)
    importer = Importer()
    db = FakeDb()
    _sync(store, db, connector, importer)

    upstream.status[SPEC] = 503
    failed = _sync(store, db, connector, importer)
    assert failed["failed"] == 1

    del upstream.status[SPEC]
    recovered = _sync(store, db, connector, importer)
    assert recovered["unchanged"] == 1 and recovered["failed"] == 0
    assert len(importer.calls) == 1


def test_oversized_document_fails(store, upstream, monkeypatch):
    monkeypatch.setattr(src, "MAX_DOCUMENT_BYTES", 10)
    upstream.documents[SPEC] = _openapi("Orders")
    connector = store.add_connector(TENANT, kind="url", name="Orders spec", base_url=SPEC)
    summary = _sync(store, FakeDb(), connector, Importer())
    assert summary["failed"] == 1 and summary["imported"] == 0


def test_refused_url_fails_without_a_request(store, upstream, monkeypatch):
    connector = store.add_connector(TENANT, kind="url", name="Internal", base_url="https://internal.example/spec")
    _refuse_host(monkeypatch, "internal.example")
    summary = _sync(store, FakeDb(), connector, Importer())
    assert summary["failed"] == 1
    assert upstream.requests == []


# ---------------------------------------------------------------------------------------
# Workspace mode (the backfilled "Catalog URLs" connector)
# ---------------------------------------------------------------------------------------

URL_A = "https://specs.example.com/a.json"
URL_B = "https://specs.example.com/b.json"


def _workspace(store: FakeConnectorStore, *, backfilled: bool = True):
    connector = store.add_connector(TENANT, kind="url", name=src.WORKSPACE_CONNECTOR_NAME, base_url=None)
    db = WorkspaceDb(store)
    db.url_items = [
        {"project_id": ITEM_A, "name": "A", "url": URL_A, "source_format": "openapi"},
        {"project_id": ITEM_B, "name": "B", "url": URL_B, "source_format": "openapi"},
    ]
    if backfilled:
        # What V352 writes: linked, imported, no content anchor.
        for pid, url in ((ITEM_A, URL_A), (ITEM_B, URL_B)):
            store.items[pid] = {
                "id": pid,
                "connector_id": connector["id"],
                "remote_id": pid,
                "remote_name": pid,
                "environment": None,
                "hosts": [],
                "base_path": None,
                "remote_revision": None,
                "remote_updated_at": None,
                "imported_revision": None,
                "imported_remote_updated_at": None,
                "imported_sha256": None,
                "status": "imported",
                "project_id": pid,
                "deployment": {"url": url},
            }
    return connector, db


def test_workspace_first_run_anchors_backfilled_items_without_reimporting(store, upstream):
    upstream.documents[URL_A] = _openapi("A")
    upstream.documents[URL_B] = _openapi("B")
    connector, db = _workspace(store)
    importer = Importer()

    summary = _sync(store, db, connector, importer)
    assert summary["candidates"] == 2
    assert summary["unchanged"] == 2 and summary["imported"] == 0
    assert importer.calls == []
    item = store.item(connector["id"], ITEM_A)
    assert item["imported_sha256"] == hashlib.sha256(_openapi("A")).hexdigest()
    assert item["project_id"] == ITEM_A


def test_workspace_change_is_a_revision_of_the_catalog_item(store, upstream):
    upstream.documents[URL_A] = _openapi("A")
    upstream.documents[URL_B] = _openapi("B")
    connector, db = _workspace(store)
    importer = Importer()
    _sync(store, db, connector, importer)

    upstream.documents[URL_A] = _openapi("A", "2.0.0")
    summary = _sync(store, db, connector, importer)
    assert summary["imported"] == 1 and summary["unchanged"] == 1
    assert importer.calls[0]["remote_id"] == ITEM_A
    assert importer.calls[0]["project_id"] == ITEM_A


def test_workspace_picks_up_a_new_url_import(store, upstream):
    upstream.documents[URL_A] = _openapi("A")
    upstream.documents[URL_B] = _openapi("B")
    connector, db = _workspace(store, backfilled=False)
    importer = Importer()

    summary = _sync(store, db, connector, importer)
    # Not backfilled: inventory rows are new, linked and anchored on the first run.
    assert summary["candidates"] == 2 and summary["imported"] == 0
    assert store.item(connector["id"], ITEM_B)["project_id"] == ITEM_B
    assert store.item(connector["id"], ITEM_B)["status"] == "imported"


def test_second_workspace_connector_lists_nothing(store, upstream):
    upstream.documents[URL_A] = _openapi("A")
    first, db = _workspace(store)
    second = store.add_connector(TENANT, kind="url", name="Another", base_url=None)
    summary = _sync(store, db, second, Importer())
    assert summary["candidates"] == 0
    assert summary["findings"][0]["code"] == src.FINDING_DUPLICATE_WORKSPACE


def test_workspace_reports_a_refused_url_and_checks_the_rest(store, upstream, monkeypatch):
    upstream.documents[URL_A] = _openapi("A")
    connector, db = _workspace(store)
    db.url_items[1]["url"] = "https://internal.example/b.json"
    _refuse_host(monkeypatch, "internal.example")
    summary = _sync(store, db, connector, Importer())
    assert summary["candidates"] == 1
    assert summary["findings"][0] == {
        "code": src.FINDING_URL_REFUSED,
        "remoteId": ITEM_B,
        "detail": summary["findings"][0]["detail"],
    }


def test_import_kind_falls_back_to_the_recorded_format(store, upstream):
    upstream.documents[URL_A] = b"not a recognisable document"
    connector, db = _workspace(store, backfilled=False)
    db.url_items = [{"project_id": ITEM_A, "name": "A", "url": URL_A, "source_format": "asyncapi"}]
    source = src.UrlConnectorSource(store.connectors[connector["id"]])
    source.bind_db(db)
    [candidate] = source.list_candidates()
    assert source.fetch(candidate).import_kind == "asyncapi"


def test_describe_names_the_mode(store):
    workspace = src.UrlConnectorSource({"id": "c", "kind": "url", "base_url": None, "tenant_id": TENANT})
    single = src.UrlConnectorSource({"id": "c", "kind": "url", "base_url": SPEC, "tenant_id": TENANT})
    assert workspace.describe()["mode"] == "workspace"
    assert single.describe()["mode"] == "url"


# ---------------------------------------------------------------------------------------
# The workspace query
# ---------------------------------------------------------------------------------------


def test_list_url_sourced_catalog_items_query_shape():
    seen: Dict[str, Any] = {}

    class Db:
        def execute_query(self, sql: str, params: Any = None) -> List[Dict[str, Any]]:
            seen["sql"], seen["params"] = sql, params
            return []

    assert src.list_url_sourced_catalog_items(Db(), TENANT) == []
    sql: str = seen["sql"]
    assert seen["params"] == (TENANT,)
    for fragment in (
        "p.deleted_at IS NULL",
        "p.publishable = FALSE",
        "'inputKind' = 'url'",
        "'connectorKind' = 'url'",
        "'remoteId' = p.id::text",
        "'^https?://'",
    ):
        assert fragment in sql
