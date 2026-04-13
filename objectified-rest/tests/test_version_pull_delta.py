"""Delta pull: schemaPullDelta on GET version (#2592 / P2-10)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.version_pull_delta import (
    apply_schema_pull_delta_for_test,
    build_schema_pull_delta,
)

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


def _min_version(rid: str, version_line: str, *, parent: str | None = None):
    return {
        "id": rid,
        "project_id": "proj-1",
        "creator_id": "test-user-id",
        "version_id": version_line,
        "description": "note",
        "change_log": "cl",
        "visibility": "private",
        "published": False,
        "published_at": None,
        "enabled": True,
        "parent_version_id": parent,
        "merge_parent_version_id": None,
        "forked_from_revision_id": None,
        "upstream_project_id": None,
        "revision_locked": False,
        "metadata": {"k": "v"},
        "created_at": None,
        "updated_at": None,
        "creator_name": "A",
        "creator_email": "a@x",
        "project_name": "P",
        "project_slug": "p",
    }


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_build_schema_pull_delta_apply_matches_head_components() -> None:
    since = {
        "components": {
            "schemas": {
                "A": {"type": "object", "properties": {"x": {"type": "string"}}},
                "DropMe": {"type": "object"},
            }
        }
    }
    head = {
        "components": {
            "schemas": {
                "A": {"type": "object", "properties": {"x": {"type": "string"}, "y": {"type": "number"}}},
                "B": {"type": "string"},
            }
        }
    }
    delta = build_schema_pull_delta(
        since,
        head,
        since_revision_id="since-1",
        head_revision_id="head-1",
    )
    assert delta["sinceRevisionId"] == "since-1"
    assert delta["headRevisionId"] == "head-1"
    assert "DropMe" in delta["removedSchemaNames"]
    assert "B" in delta["schemas"]
    merged = apply_schema_pull_delta_for_test(
        since["components"]["schemas"],
        delta,
    )
    assert merged == head["components"]["schemas"]


def test_unknown_since_revision_is_400():
    row = _min_version("rev-head", "1.0.1", parent="rev-parent")
    with patch("app.versions_routes.db") as mdb:

        def _gf(vid, tid):
            if vid == "rev-head":
                return row
            return None

        mdb.get_version_by_id.side_effect = _gf
        r = client.get(
            "/v1/versions/tn/proj-1/rev-head",
            params={"sinceRevisionId": "nope"},
        )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "UNKNOWN_REVISION_ID"


def test_unknown_since_revision_is_400_by_version():
    row = _min_version("rev-head", "1.0.1", parent="rev-parent")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_version_id.return_value = row

        def _gf(vid, tid):
            if vid == "rev-head":
                return row
            return None

        mdb.get_version_by_id.side_effect = _gf
        r = client.get(
            "/v1/versions/tn/proj-1/by-version/1.0.1",
            params={"sinceRevisionId": "nope"},
        )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "UNKNOWN_REVISION_ID"


def test_since_equals_head_empty_delta_by_version():
    row = _min_version("rev-same", "1.0.0")
    spec = {"components": {"schemas": {"Z": {"type": "string"}}}}
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_version_id.return_value = row
        mdb.get_version_by_id.return_value = row
        mdb.collect_revision_ancestors.return_value = {"rev-same"}
        with patch("app.versions_routes.openapi_for_revision", return_value=spec):
            r = client.get(
                "/v1/versions/tn/proj-1/by-version/1.0.0",
                params={"sinceRevisionId": "rev-same"},
            )
    assert r.status_code == 200
    body = r.json()
    d = body["schemaPullDelta"]
    assert d["removedSchemaNames"] == []
    assert d["schemas"] == {}
    assert "guarantee" in d


def test_since_not_ancestor_of_head_is_400():
    head = _min_version("rev-head", "1.0.1", parent="rev-parent")
    cousin = _min_version("rev-cousin", "0.9.0", parent=None)
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            head if vid == "rev-head" else cousin if vid == "rev-cousin" else None
        )
        mdb.collect_revision_ancestors.return_value = {"rev-head", "rev-parent"}
        r = client.get(
            "/v1/versions/tn/proj-1/rev-head",
            params={"sinceRevisionId": "rev-cousin"},
        )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "SINCE_NOT_ANCESTOR_OF_HEAD"


def test_since_equals_head_empty_delta():
    row = _min_version("rev-same", "1.0.0")
    spec = {"components": {"schemas": {"Z": {"type": "string"}}}}
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        mdb.collect_revision_ancestors.return_value = {"rev-same"}
        with patch("app.versions_routes.openapi_for_revision", return_value=spec):
            r = client.get(
                "/v1/versions/tn/proj-1/rev-same",
                params={"sinceRevisionId": "rev-same"},
            )
    assert r.status_code == 200
    body = r.json()
    d = body["schemaPullDelta"]
    assert d["removedSchemaNames"] == []
    assert d["schemas"] == {}
    assert "guarantee" in d


def test_since_revision_project_mismatch_is_400():
    head = _min_version("rev-head", "1.0.0")
    other = dict(_min_version("rev-other", "2.0.0"))
    other["project_id"] = "other-proj"
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            head if vid == "rev-head" else other if vid == "rev-other" else None
        )
        r = client.get(
            "/v1/versions/tn/proj-1/rev-head",
            params={"sinceRevisionId": "rev-other"},
        )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "REVISION_PROJECT_MISMATCH"


def test_redirect_preserves_since_revision_id_query():
    va = _min_version("rev-a", "1.0.0")
    va["metadata"] = {"successorRevisionId": "rev-b"}
    vb = _min_version("rev-b", "1.0.1")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            va if vid == "rev-a" else vb if vid == "rev-b" else None
        )
        mdb.resolve_successor_revision_chain.return_value = ("rev-b", ["rev-b"], "resolved", None)
        r = client.get(
            "/v1/versions/tn/proj-1/rev-a",
            params={
                "successorResolution": "redirect",
                "sinceRevisionId": "rev-a",
            },
            follow_redirects=False,
        )
    assert r.status_code == 307
    loc = r.headers.get("location")
    assert loc is not None
    assert "sinceRevisionId=rev-a" in loc
    assert "successorResolution=none" in loc
