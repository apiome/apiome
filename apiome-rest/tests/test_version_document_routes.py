"""Read a revision's OpenAPI document as a member — COA-5.13 (#7089).

``GET /v1/versions/{tenant}/{project}/{version}/document`` with the in-memory database of
``tests/test_rendered_documents.py`` and a real filesystem document store. Pinned here: a draft is
readable, the document is the members' one (OpenAPI 3.2, private operations kept), the second
request reads no class or property row, ``If-None-Match`` answers ``304``, and the route cannot
reach another project's or tenant's revision.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.database as database_module
from app import version_document_routes
from app.auth import validate_authentication
from app.document_store import DocumentNotFound, FilesystemDocumentStore, set_document_store
from app.main import app
from app.permissions import Action, Resource
from tests.test_rendered_documents import TENANT, VERSION, FakeDatabase, _with_a_private_operation

client = TestClient(app)

PROJECT = "22222222-2222-4222-8222-222222222222"
OTHER_PROJECT = "33333333-3333-4333-8333-333333333333"
UNKNOWN = "99999999-9999-4999-8999-999999999999"
URL = f"/v1/versions/acme/{PROJECT}/{VERSION}/document"
_AUTH = {"tenant_id": TENANT, "user_id": "u1", "auth_method": "jwt", "user_email": "a@x.io"}


class _Db(FakeDatabase):
    """The cache's database plus the revision read of the route."""

    def get_version_by_id(self, version_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        if version_id != VERSION or tenant_id != TENANT:
            return None
        return {"id": version_id, "project_id": PROJECT, "published": False}
    get_version_core = get_version_by_id


@pytest.fixture
def env(tmp_path, monkeypatch) -> Iterator[Dict[str, Any]]:
    """The fake database (a draft revision), a filesystem store and the route wired to both."""
    database = _Db()
    _with_a_private_operation(database)
    store = FilesystemDocumentStore(path=str(tmp_path), prefix="apiome")
    monkeypatch.setattr(version_document_routes, "db", database)
    monkeypatch.setattr(database_module, "db", database)
    permissions: List[Tuple[Any, Any]] = []
    monkeypatch.setattr(
        version_document_routes,
        "enforce_permission",
        lambda _db, _auth, resource, action, **_kw: permissions.append((resource, action)),
    )
    set_document_store(store)
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield {"db": database, "store": store, "permissions": permissions}
    app.dependency_overrides.pop(validate_authentication, None)
    set_document_store(None)


def test_a_draft_is_served_as_the_members_document(env) -> None:
    response = client.get(URL)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    document = response.json()
    assert document["openapi"] == "3.2.0"
    assert sorted(document["paths"]["/orders"]) == ["delete", "get"]
    assert document["paths"]["/orders"]["delete"]["x-private"] is True
    assert document["components"]["schemas"]["Order"]["properties"]["id"] == {"type": "string"}
    assert env["permissions"] == [(Resource.VERSIONS, Action.VIEW)]


def test_the_headers_carry_the_digest_and_the_cache_status(env) -> None:
    first = client.get(URL)
    digest = hashlib.sha256(first.content).hexdigest()

    assert first.headers["etag"] == f'"{digest}"'
    assert first.headers["x-apiome-content-sha256"] == digest
    assert first.headers["content-length"] == str(len(first.content))
    assert first.headers["cache-control"] == "private, no-cache"
    assert first.headers["x-apiome-document-cache"] == "miss"

    second = client.get(URL)
    assert second.headers["x-apiome-document-cache"] == "hit"
    assert second.content == first.content


def test_the_second_request_reads_no_class_or_property_row(env) -> None:
    client.get(URL)
    env["db"].calls.clear()

    assert client.get(URL).status_code == 200
    assert env["db"].calls == ["context", "find"]


@pytest.mark.parametrize("header", ['"{digest}"', 'W/"{digest}"', '"other", "{digest}"', "*"])
def test_if_none_match_answers_304_without_a_body(env, header: str) -> None:
    digest = client.get(URL).headers["x-apiome-content-sha256"]
    env["db"].calls.clear()

    response = client.get(URL, headers={"If-None-Match": header.format(digest=digest)})

    assert response.status_code == 304 and response.content == b""
    assert response.headers["etag"] == f'"{digest}"'
    assert response.headers["x-apiome-document-cache"] == "hit"
    assert env["db"].renders() == 0


def test_a_stale_etag_gets_the_new_document(env) -> None:
    stale = client.get(URL).headers["etag"]
    env["db"].context["content_stamp"] = 1
    env["db"].classes[0]["description"] = "A changed order"

    response = client.get(URL, headers={"If-None-Match": stale})

    assert response.status_code == 200 and response.headers["etag"] != stale
    assert response.json()["components"]["schemas"]["Order"]["description"] == "A changed order"


@pytest.mark.parametrize(
    "url",
    [
        f"/v1/versions/acme/{OTHER_PROJECT}/{VERSION}/document",
        f"/v1/versions/acme/{PROJECT}/{UNKNOWN}/document",
        f"/v1/versions/acme/{PROJECT}/not-a-uuid/document",
        f"/v1/versions/acme/not-a-uuid/{VERSION}/document",
    ],
)
def test_a_revision_the_caller_cannot_address_is_404(env, url: str) -> None:
    response = client.get(url)
    assert response.status_code == 404
    assert env["db"].renders() == 0


def test_another_tenants_revision_is_404(env) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {**_AUTH, "tenant_id": "tenant-2"}
    assert client.get(URL).status_code == 404
    assert env["db"].renders() == 0


def test_a_caller_without_versions_view_is_refused_before_any_read(env, monkeypatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPException(status_code=403, detail="Permission denied: versions:view")

    monkeypatch.setattr(version_document_routes, "enforce_permission", refuse)

    assert client.get(URL).status_code == 403
    assert env["db"].calls == []


def test_a_stored_document_the_store_lost_after_the_lookup_is_502(env, monkeypatch) -> None:
    digest = client.get(URL).headers["x-apiome-content-sha256"]

    def gone(tenant_id: str, sha256: str) -> Any:
        raise DocumentNotFound(tenant_id, sha256)

    monkeypatch.setattr(env["store"], "open_stream", gone)

    response = client.get(URL)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "document-unreadable"
    assert digest not in response.text


def test_a_revision_that_disappears_between_the_two_reads_is_404(env) -> None:
    env["db"].context = None
    assert client.get(URL).status_code == 404
