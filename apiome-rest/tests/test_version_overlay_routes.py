"""Stored overlay chain routes — GVM-4.3 (#5878).

``/v1/versions/{t}/{p}/{v}/overlays`` over a fake store:

* list returns the chain with its read-only flag and the publish render record;
* add / replace / delete pass through to the store with the actor, and need ``versions:edit``;
* a published revision is read-only: every write is ``409 overlay-version-published``;
* an unknown revision or overlay is 404, a full chain is ``409 overlay-chain-full``, a non-Overlay
  body is 422 and a non-OpenAPI source is ``422 OVERLAY_SOURCE_UNSUPPORTED``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.export_source import ExportSource
from app.main import app
from app.version_overlay_chain import MAX_STORED_OVERLAYS, StoredOverlay, document_fingerprint
from tests.test_export_overlay import _PARTNER, TENANT_ID, _openapi_source

TENANT = "acme"
PROJECT = "11111111-1111-1111-1111-111111111111"
REVISION = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
BASE = f"/v1/versions/{TENANT}/{PROJECT}/{REVISION}/overlays"


class FakeStore:
    """In-memory stand-in for :mod:`app.version_overlay_store`'s chain functions."""

    def __init__(self) -> None:
        self.rows: List[StoredOverlay] = []
        self.render: Optional[Dict[str, Any]] = None
        self.calls: List[tuple] = []
        self._next = 0

    def _new(self, position: int, name: str, source: str, document: dict, actor: Optional[str]) -> StoredOverlay:
        self._next += 1
        return StoredOverlay(
            id=f"ov-{self._next}",
            position=position,
            name=name,
            source=source,
            document=document,
            content_fingerprint=document_fingerprint(document),
            created_by=actor,
        )

    def list_overlays(self, tenant_id, version_record_id):
        return sorted(self.rows, key=lambda r: r.position)

    def get_render(self, tenant_id, version_record_id):
        return self.render

    def insert_overlay(
        self, *, tenant_id, project_id, version_record_id, name, source, document, actor_id, position=None
    ):
        self.calls.append(("insert", name, source, position, actor_id))
        row = self._new(len(self.rows) if position is None else position, name, source, document, actor_id)
        self.rows.append(row)
        return row

    def replace_overlay(
        self, *, tenant_id, project_id, version_record_id, overlay_id, name, source, document, actor_id
    ):
        self.calls.append(("replace", overlay_id, name, actor_id))
        old = next((r for r in self.rows if r.id == overlay_id), None)
        if old is None:
            return None
        self.rows.remove(old)
        row = self._new(old.position, name, source, document, actor_id)
        self.rows.append(row)
        return row

    def delete_overlay(self, *, tenant_id, project_id, version_record_id, overlay_id, actor_id):
        self.calls.append(("delete", overlay_id, actor_id))
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.id != overlay_id]
        return len(self.rows) < before


@pytest.fixture
def store(monkeypatch) -> FakeStore:
    fake = FakeStore()
    for name in ("list_overlays", "get_render", "insert_overlay", "replace_overlay", "delete_overlay"):
        monkeypatch.setattr(f"app.version_overlay_store.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def version(monkeypatch) -> Dict[str, Any]:
    row: Dict[str, Any] = {"id": REVISION, "project_id": PROJECT, "published": False}

    def _get(version_id, tenant_id):
        return dict(row) if version_id == REVISION and tenant_id == TENANT_ID else None

    monkeypatch.setattr("app.version_overlay_routes.db.get_version_by_id", _get)
    monkeypatch.setattr("app.version_overlay_routes.load_export_source", lambda *a: _openapi_source())
    return row


@pytest.fixture
def client():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT_ID,
        "user_id": USER,
        "auth_method": "jwt",
    }
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _body(name: str = "partner.yaml", **extra) -> dict:
    return {"name": name, "document": _PARTNER, **extra}


def test_list_returns_the_chain_and_its_render_record(client, store, version):
    store.rows.append(store._new(0, "partner.yaml", "manual", _PARTNER, USER))
    store.render = {
        "source_fingerprint": "sha256:a",
        "resolved_fingerprint": "sha256:b",
        "overlays": [],
        "findings": [],
        "changes": 2,
        "rendered_by": USER,
        "rendered_at": None,
    }
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["published"] is False
    assert body["max_overlays"] == MAX_STORED_OVERLAYS
    assert [o["name"] for o in body["overlays"]] == ["partner.yaml"]
    assert body["overlays"][0]["action_count"] == 2
    assert body["overlays"][0]["content_fingerprint"] == document_fingerprint(_PARTNER)
    assert body["render"]["resolved_fingerprint"] == "sha256:b"


def test_add_appends_with_the_actor_and_source(client, store, version):
    response = client.post(BASE, json=_body(source="enrichment-export"))
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "enrichment-export"
    assert store.calls == [("insert", "partner.yaml", "enrichment-export", None, USER)]


def test_add_accepts_the_lint_fix_source_for_gvm_3_6(client, store, version):
    assert client.post(BASE, json=_body(source="lint-fix")).status_code == 201


def test_add_refuses_an_unknown_source_and_a_non_overlay(client, store, version):
    assert client.post(BASE, json=_body(source="robot")).status_code == 422
    assert client.post(BASE, json={"name": "x", "document": {"openapi": "3.1.0"}}).status_code == 422
    assert client.post(BASE, json={"name": "  ", "document": _PARTNER}).status_code == 422
    assert store.calls == []


def test_add_refuses_a_full_chain(client, store, version):
    for i in range(MAX_STORED_OVERLAYS):
        store.rows.append(store._new(i, f"o{i}", "manual", _PARTNER, USER))
    response = client.post(BASE, json=_body())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "overlay-chain-full"


def test_add_refuses_a_non_openapi_source(client, store, version, monkeypatch):
    graphql = ExportSource(
        api=CanonicalApi(format="graphql", paradigm=ApiParadigm.GRAPH, identity=ApiIdentity(name="g")),
        artifact_id=PROJECT,
        version_record_id=REVISION,
        source_format="graphql",
    )
    monkeypatch.setattr("app.version_overlay_routes.load_export_source", lambda *a: graphql)
    response = client.post(BASE, json=_body())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "OVERLAY_SOURCE_UNSUPPORTED"
    assert store.calls == []


def test_replace_keeps_the_position_and_gives_a_new_id(client, store, version):
    first = store._new(0, "a", "manual", _PARTNER, USER)
    store.rows.append(first)
    response = client.put(f"{BASE}/{first.id}", json=_body("a-v2"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] != first.id
    assert body["position"] == 0
    assert body["name"] == "a-v2"


def test_replace_and_delete_of_an_unknown_overlay_are_404(client, store, version):
    assert client.put(f"{BASE}/nope", json=_body()).status_code == 404
    assert client.delete(f"{BASE}/nope").status_code == 404


def test_delete_removes_the_overlay(client, store, version):
    row = store._new(0, "a", "manual", _PARTNER, USER)
    store.rows.append(row)
    assert client.delete(f"{BASE}/{row.id}").status_code == 204
    assert store.rows == []


def test_a_published_revision_is_read_only(client, store, version):
    row = store._new(0, "a", "manual", _PARTNER, USER)
    store.rows.append(row)
    version["published"] = True
    for response in (
        client.post(BASE, json=_body()),
        client.put(f"{BASE}/{row.id}", json=_body()),
        client.delete(f"{BASE}/{row.id}"),
    ):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "overlay-version-published"
    assert store.calls == []
    listed = client.get(BASE).json()
    assert listed["published"] is True
    assert len(listed["overlays"]) == 1


def test_an_unknown_or_foreign_revision_is_404(client, store, version):
    other = f"/v1/versions/{TENANT}/{PROJECT}/44444444-4444-4444-4444-444444444444/overlays"
    assert client.get(other).status_code == 404
    wrong_project = f"/v1/versions/{TENANT}/55555555-5555-5555-5555-555555555555/{REVISION}/overlays"
    assert client.get(wrong_project).status_code == 404
    assert client.post(wrong_project, json=_body()).status_code == 404


def test_writes_need_versions_edit(client, store, version, monkeypatch):
    def _deny(_db, _auth, resource, action):
        if action == "edit":
            raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr("app.version_overlay_routes.enforce_permission", _deny)
    assert client.get(BASE).status_code == 200
    assert client.post(BASE, json=_body()).status_code == 403
    assert client.delete(f"{BASE}/x").status_code == 403
    assert store.calls == []


def test_a_concurrent_write_is_a_retryable_409(client, store, version, monkeypatch):
    import psycopg2

    def _race(**_kwargs):
        raise psycopg2.errors.UniqueViolation("duplicate key value violates unique constraint")

    monkeypatch.setattr("app.version_overlay_store.insert_overlay", _race)
    response = client.post(BASE, json=_body())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "overlay-chain-conflict"
