"""Record-the-original API for imports outside the REST import job — COA-5.3 (#7079).

The database and the snapshot hook's collaborators are faked; the store is a real ``db``-backed
document store over an in-memory database. Pinned: the permission and creator guards, the intake
limits, that the stored text is the scrubbed text, and that a revision keeps its first original.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import import_original_routes
from app.auth import validate_authentication
from app.document_store import DbDocumentStore, set_document_store
from app.intake_scrub_policy import DEFAULT_POLICY
from app.main import app
from app.permissions import Action, Resource
from tests.test_original_documents import FakeDocumentDatabase

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_OTHER_USER = "44444444-4444-4444-8444-444444444444"
_VERSION = "55555555-5555-4555-8555-555555555555"
_FOREIGN_VERSION = "99999999-9999-4999-8999-999999999999"
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_URL = "/v1/tenants/acme/import-originals"
_SECRET = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
_DOC = f"openapi: 3.1.0\ninfo:\n  title: Pets\n  x-token: {_SECRET}\npaths: {{}}\n"


class _Db(FakeDocumentDatabase):
    """The document tables plus the calls the route and the snapshot hook make."""

    def __init__(self) -> None:
        super().__init__(versions={_VERSION: _TENANT})
        self.snapshots: list = []
        self.creator = _ACTOR

    def get_version_by_id(self, version_id, tenant_id):
        if version_id != _VERSION or tenant_id != _TENANT:
            return None
        return {"id": _VERSION, "project_id": "p1", "creator_id": self.creator}

    def record_import_snapshot(self, **kwargs):
        self.snapshots.append(kwargs)


@pytest.fixture
def database(monkeypatch):
    fake = _Db()
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    monkeypatch.setattr(import_original_routes, "db", fake)
    monkeypatch.setattr("app.database.db", fake)
    set_document_store(DbDocumentStore(prefix="apiome", database=fake))
    permissions: list = []
    monkeypatch.setattr(
        import_original_routes,
        "enforce_permission",
        lambda _db, _auth, resource, action, **_kw: permissions.append((resource, action)) or _ACTOR,
    )
    fake.permissions = permissions
    with (
        patch("app.compatibility_engine.openapi_for_revision", return_value={"openapi": "3.1.0", "paths": {}}),
        patch("app.intake_scrub_policy.load_tenant_scrub_policy", return_value=DEFAULT_POLICY),
    ):
        yield fake
    app.dependency_overrides.pop(validate_authentication, None)


def _post(content: str = _DOC, **overrides: Any):
    body: Dict[str, Any] = {"versionId": _VERSION, "content": content, "filename": "pets.yaml", **overrides}
    return client.post(_URL, json=body)


def test_stores_the_scrubbed_text_as_the_original(database) -> None:
    response = _post()

    assert response.status_code == 200
    body = response.json()
    row = database.original(_VERSION)
    stored_text = DbDocumentStore(database=database).get(_TENANT, row["sha256"]).decode()
    assert _SECRET not in stored_text
    assert body == {
        "stored": True,
        "sha256": hashlib.sha256(stored_text.encode()).hexdigest(),
        "contentSha256": row["sha256"],
        "sizeBytes": len(stored_text.encode()),
        "mediaType": "application/yaml",
        "encoding": "identity",
    }
    assert database.permissions == [(Resource.IMPORTS, Action.CREATE)]
    snapshot = database.snapshots[0]
    assert snapshot["source_file"] == "pets.yaml" and snapshot["created_by"] == _ACTOR
    assert snapshot["source_digest"] == "sha256:" + hashlib.sha256(_DOC.encode()).hexdigest()


def test_a_revision_keeps_its_first_original(database) -> None:
    assert _post("openapi: 3.1.0\npaths: {}\n").json()["stored"] is True
    first = database.original(_VERSION)["sha256"]

    again = _post("openapi: 3.1.0\npaths: {}\ninfo: {title: Later}\n")
    assert again.status_code == 200 and again.json() == {"stored": False}
    assert database.original(_VERSION)["sha256"] == first


def test_an_arazzo_document_is_stored_without_a_snapshot(database) -> None:
    document = "arazzo: 1.0.1\ninfo: {title: Adopt, version: 1.0.0}\nworkflows: []\n"
    response = _post(document, filename="adopt.arazzo.yaml")
    assert response.json()["stored"] is True
    assert database.snapshots == [] and _VERSION in database.documents


def test_a_document_of_another_kind_stores_nothing(database) -> None:
    assert _post("asyncapi: 2.6.0\nchannels: {}\n").json() == {"stored": False}
    assert database.objects == {}


def test_only_the_creator_of_the_revision_may_record_it(database) -> None:
    database.creator = _OTHER_USER
    response = _post()
    assert response.status_code == 403 and database.objects == {}


def test_an_unknown_or_foreign_revision_is_not_found(database) -> None:
    assert _post(versionId=_FOREIGN_VERSION).status_code == 404
    assert _post(versionId="not-a-uuid").status_code == 404


def test_text_that_does_not_parse_is_refused(database) -> None:
    assert _post("{not json: [").status_code == 422
    assert _post("- a\n- list\n").status_code == 422
    assert database.objects == {}


def test_an_oversized_document_is_refused(database, monkeypatch) -> None:
    from app.intake_resource_guard import IntakeLimitError

    def too_large(*_args: Any, **_kwargs: Any) -> None:
        raise IntakeLimitError("Source document is too large", code="INPUT_TOO_LARGE")

    monkeypatch.setattr(import_original_routes, "guard_payload_bytes", too_large)
    assert _post().status_code == 413 and database.objects == {}


def test_the_body_is_validated(database) -> None:
    assert client.post(_URL, json={"versionId": _VERSION, "content": ""}).status_code == 422
    assert client.post(_URL, json={"versionId": _VERSION, "content": "a: 1", "extra": 1}).status_code == 422
