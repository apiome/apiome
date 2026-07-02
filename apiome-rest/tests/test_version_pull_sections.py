"""GET version pull payload section filters (#2591 / P2-09)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


def _min_version(rid: str, version_line: str):
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
        "parent_version_id": None,
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


def test_exclude_sections_omits_governance_and_timestamps():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            params={"excludeSections": "governance,timestamps"},
        )
    assert r.status_code == 200
    body = r.json()
    assert "metadata" not in body
    assert "lifecycle" not in body
    assert "created_at" not in body
    assert body["id"] == "rev-1"
    assert body["version_id"] == "1.0.0"


def test_include_sections_commit_and_core():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            params={"includeSections": "commit"},
        )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"id", "project_id", "version_id", "shortMessage", "changelog"}
    assert "metadata" not in body
    assert body["shortMessage"] == "note"


def test_include_and_exclude_both_set_is_400():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            params={"includeSections": "commit", "excludeSections": "governance"},
        )
    assert r.status_code == 400


def test_unknown_section_is_400():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            params={"includeSections": "not-a-section"},
        )
    assert r.status_code == 400


def test_etag_unchanged_with_exclude_sections():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            params={"excludeSections": "governance"},
        )
    assert r.status_code == 200
    assert r.headers.get("etag") == '"rev-1"'


def test_redirect_preserves_include_sections_query():
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
                "includeSections": "core,commit",
            },
            follow_redirects=False,
        )
    assert r.status_code == 307
    loc = r.headers.get("location")
    assert loc is not None
    assert "includeSections=core%2Ccommit" in loc or "includeSections=core,commit" in loc
    assert "successorResolution=none" in loc


def test_by_version_exclude_sections():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_version_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/by-version/1.0.0",
            params={"excludeSections": "governance,timestamps"},
        )
    assert r.status_code == 200
    body = r.json()
    assert "metadata" not in body
    assert "lifecycle" not in body
    assert "created_at" not in body
    assert body["id"] == "rev-1"
    assert body["version_id"] == "1.0.0"


def test_by_version_include_sections_commit():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_version_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/by-version/1.0.0",
            params={"includeSections": "commit"},
        )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"id", "project_id", "version_id", "shortMessage"}
    assert "metadata" not in body


def test_by_version_invalid_sections_is_400():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_version_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/by-version/1.0.0",
            params={"includeSections": "not-a-section"},
        )
    assert r.status_code == 400


def test_by_version_successor_resolution_headers_preserved_with_section_filter():
    """Successor-resolution headers from ``resolve`` mode are present on partial responses."""
    va = _min_version("rev-a", "1.0.0")
    vb = _min_version("rev-b", "1.0.1")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_version_id.return_value = va
        mdb.get_version_by_id.return_value = vb
        mdb.resolve_successor_revision_chain.return_value = ("rev-b", ["rev-b"], "resolved", None)
        r = client.get(
            "/v1/versions/tn/proj-1/by-version/1.0.0",
            params={"successorResolution": "resolve", "excludeSections": "timestamps"},
        )
    assert r.status_code == 200
    body = r.json()
    assert "created_at" not in body
    assert body["id"] == "rev-b"
    assert r.headers.get("x-apiome-successor-resolution-status") == "resolved"


def test_filter_unit_covers_all_version_schema_keys():
    from app.models import VersionSchema
    from app.version_pull_payload import (
        SECTION_FIELD_KEYS,
        all_wire_keys,
        filter_version_pull_dump,
    )

    vs = VersionSchema.model_construct(
        id="i",
        project_id="p",
        version_id="v",
    )
    dump = vs.model_dump(by_alias=True, mode="json")
    keys = set(dump.keys())
    mapped = all_wire_keys()
    assert keys <= mapped, keys - mapped

    full_round = filter_version_pull_dump(dump, include_sections=None, exclude_sections=None)
    assert set(full_round.keys()) == keys

    for sec, sec_keys in SECTION_FIELD_KEYS.items():
        if sec == "core":
            continue
        ex = filter_version_pull_dump(
            dump,
            include_sections=None,
            exclude_sections={sec},
        )
        for k in sec_keys & keys:
            assert k not in ex
