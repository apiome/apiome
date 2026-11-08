"""DCW-2.4 (private-suite#2365) — GET …/provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}
_URL = "/v1/versions/acme/p1/v2/provenance"

SOURCE = "openapi: 3.1.0\npaths:\n  /pets:\n    get:\n      summary: List\n    post:\n      summary: Create\n"
IMPORTED = {
    "openapi": "3.1.0",
    "paths": {"/pets": {"get": {"summary": "List"}, "post": {"summary": "Create"}}},
    "components": {"schemas": {"Pet": {"type": "object"}}},
}
CURRENT = {
    "openapi": "3.1.0",
    "paths": {"/pets": {"get": {"summary": "List all"}, "post": {"summary": "Create"}}, "/owners": {"get": {}}},
    "components": {"schemas": {"Pet": {"type": "object"}}},
}
SNAPSHOT = {
    "version_id": "v1",
    "source_file": "pets.yaml",
    "source_format": "yaml",
    "source_digest": "sha256:abc",
    "source_text": SOURCE,
    "canonical_document": IMPORTED,
    "created_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
}


@pytest.fixture(autouse=True)
def _wired():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    with (
        patch("app.source_provenance_routes.enforce_permission", return_value="u1") as guard,
        patch("app.source_provenance_routes.openapi_for_revision", return_value=CURRENT),
        patch("app.source_provenance_routes.db") as db,
    ):
        db.get_version_by_id.return_value = {"id": "v2", "project_id": "p1", "parent_version_id": "v1"}
        db.get_import_snapshot_lineage.return_value = (SNAPSHOT, ["v2", "v1"])
        db.list_source_edits.return_value = [
            {
                "pointer": "/paths/~1owners",
                "change_kind": "addition",
                "version_id": "v2",
                "created_at": datetime(2026, 11, 5, tzinfo=timezone.utc),
            }
        ]
        db.get_classes_for_version.return_value = [{"id": "class-pet", "name": "Pet"}]
        db.get_paths_for_version.return_value = [
            {"id": "path-pets", "pathname": "/pets"},
            {"id": "path-owners", "pathname": "/owners"},
        ]
        db.get_preservation_claims.return_value = [
            {"pointer": "/x-sdk", "source_file": "pets.yaml", "source_digest": "sha256:abc"},
            {"pointer": "/x-none"},
        ]
        yield db, guard
    app.dependency_overrides.clear()


def _by_pointer(body):
    return {e["pointer"]: e for e in body["elements"]}


def test_reports_each_element_by_pointer_and_entity_id(_wired):
    body = client.get(_URL).json()
    rows = _by_pointer(body)
    assert rows["/paths/~1pets/post"]["status"] == "imported"
    assert rows["/paths/~1pets/get"]["status"] == "local"
    assert rows["/paths/~1owners/get"]["status"] == "source-edited"
    assert rows["/paths/~1owners/get"]["lastSourceEditAt"].startswith("2026-11-05")
    assert rows["/paths/~1pets"]["entityId"] == "path-pets"
    assert rows["/components/schemas/Pet"]["entityId"] == "class-pet"
    assert rows["/paths/~1pets/post"]["sourceFile"] == "pets.yaml"
    assert rows["/paths/~1pets/post"]["sourcePointer"] == "/paths/~1pets/post"
    assert rows["/paths/~1owners/get"]["sourceFile"] is None
    assert body["counts"] == {"imported": 2, "local": 2, "source-edited": 2}
    assert body["snapshot"]["versionRecordId"] == "v1"
    assert body["snapshot"]["textAvailable"] is True
    assert all(e["excerpt"] is None for e in body["elements"])


def test_reads_edits_across_the_lineage_back_to_the_import(_wired):
    db, _ = _wired
    client.get(_URL)
    db.list_source_edits.assert_called_once_with(["v2", "v1"], "t1")


def test_a_pointer_narrows_to_its_owning_element_with_an_excerpt(_wired):
    body = client.get(_URL, params={"pointer": "/paths/~1pets/post/summary"}).json()
    assert [e["pointer"] for e in body["elements"]] == ["/paths/~1pets/post"]
    assert body["elements"][0]["excerpt"] == {
        "startLine": 6,
        "endLine": 7,
        "text": "    post:\n      summary: Create",
        "truncated": False,
    }


def test_no_excerpt_for_an_element_the_import_did_not_have(_wired):
    body = client.get(_URL, params={"pointer": "/paths/~1owners/get"}).json()
    assert body["elements"][0]["excerpt"] is None


def test_without_a_snapshot_only_source_applied_elements_are_not_local(_wired):
    db, _ = _wired
    db.get_import_snapshot_lineage.return_value = (None, ["v2"])
    body = client.get(_URL).json()
    assert body["snapshot"] is None
    rows = _by_pointer(body)
    assert rows["/paths/~1owners/get"]["status"] == "source-edited"
    assert {e["status"] for p, e in rows.items() if not p.startswith("/paths/~1owners")} == {"local"}
    db.list_source_edits.return_value = []
    assert {e["status"] for e in client.get(_URL).json()["elements"]} == {"local"}


def test_returns_preserved_fields_that_recorded_a_source(_wired):
    assert client.get(_URL).json()["preserved"] == [
        {"pointer": "/x-sdk", "sourceFile": "pets.yaml", "sourceDigest": "sha256:abc"}
    ]


def test_requires_projects_view(_wired):
    _, guard = _wired
    client.get(_URL)
    assert guard.call_args.args[2:] == ("projects", "view")
    guard.side_effect = HTTPException(status_code=403, detail="denied")
    assert client.get(_URL).status_code == 403


def test_an_unknown_or_foreign_revision_is_a_404(_wired):
    db, _ = _wired
    db.get_version_by_id.return_value = {"id": "v2", "project_id": "other"}
    assert client.get(_URL).status_code == 404
    db.get_version_by_id.return_value = None
    assert client.get(_URL).status_code == 404


def test_a_malformed_pointer_is_a_422(_wired):
    assert client.get(_URL, params={"pointer": "paths"}).status_code == 422
