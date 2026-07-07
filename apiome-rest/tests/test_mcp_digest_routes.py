"""API tests for the MCP "changed since last view" digest + seen-marker routes (V2-MCP-30.5, #4640).

Covers the two routes backing the per-user digest:

- ``GET  …/endpoints/{id}/insight/digest`` — the delta between the caller's last-seen version and
  the current one, classified by breaking severity (new-to-you / has-changes / up-to-date).
- ``POST …/endpoints/{id}/views``          — advance the caller's seen-marker ("marker advances on
  view").

The ``db`` module is mocked, so these assert route wiring, the new-to-you / has-changes / up-to-date
branches, tenant-scoped ``404`` behaviour, and the marker-advance contract. The digest's change delta
runs the *real* ``compare_endpoint_versions`` + ``reconstruct_surface`` + severity classifier over
mocked capability rows, so the counts and severities are verified end-to-end without a database.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)

_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"
_V2 = "33333333-3333-3333-3333-333333333333"

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "current_version_id": _V2,
}


def _version_row(version_id, seq):
    """A row shaped like ``get_mcp_endpoint_version`` returns."""
    return {
        "id": version_id,
        "endpoint_id": _EP,
        "version_seq": seq,
        "version_tag": f"2026-07-07T{seq:02d}:00Z",
        "protocol_version": "2025-06-18",
        "server_name": "acme",
        "server_title": None,
        "server_version": "1.0.0",
        "instructions": None,
        "capabilities": {"tools": {"listChanged": True}},
        "surface_fingerprint": f"fp{seq}",
        "discovered_at": _NOW,
        "created_at": _NOW,
        "score": 90,
        "grade": "A",
        "scored_at": _NOW,
        "added_count": 0,
        "removed_count": 0,
        "modified_count": 0,
        "total_count": 0,
    }


def _tool_row(version_id, name, ordinal=0):
    """A minimal ``mcp_capability_items`` tool row for a given version."""
    return {
        "version_id": version_id,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": "does a thing",
        "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
        "output_schema": None,
        "annotations": {"readOnlyHint": True},
        "uri": None,
        "uri_template": None,
        "raw": {},
        "ordinal": ordinal,
    }


# V1 exposes one tool; V2 adds a second — so the V1→V2 delta is a single "added" (additive) change.
_ITEMS = {
    _V1: [_tool_row(_V1, "forecast", 0)],
    _V2: [_tool_row(_V2, "forecast", 0), _tool_row(_V2, "current", 1)],
}


def _version_by_id(_endpoint_id, version_id):
    return {_V1: _version_row(_V1, 1), _V2: _version_row(_V2, 2)}.get(str(version_id))


def _items_by_version(version_id):
    return _ITEMS.get(str(version_id), [])


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# digest — read
# ===========================================================================


def test_digest_first_visit_is_new_to_you_with_current_counts():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_view.return_value = None  # no marker → first visit
        mdb.get_mcp_endpoint_version.side_effect = _version_by_id
        mdb.get_mcp_capability_items.side_effect = _items_by_version
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["new_to_you"] is True
    assert body["has_changes"] is False
    assert body["last_seen_version_id"] is None
    assert body["current_version_id"] == _V2
    # The current surface (V2) exposes two tools — surfaced so the panel can say "new to you — N tools".
    assert body["current_type_counts"]["tools"] == 2
    assert body["current_type_counts"]["total"] == 2
    assert body["changes"] == []


def test_digest_reports_delta_since_last_seen_with_severity():
    # The delta runs through ``compare_endpoint_versions`` (mcp_discovery_engine), so both the
    # route's ``db`` and the engine's ``db`` must resolve to the same mock.
    with patch("app.mcp_catalog_routes.db") as mdb, patch("app.mcp_discovery_engine.db", mdb):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        # Marker points at V1; current is V2 → one added tool since.
        mdb.get_mcp_endpoint_view.return_value = {
            "last_seen_version_id": _V1,
            "seen_at": _NOW,
            "created_at": _NOW,
            "last_seen_version_seq": 1,
            "last_seen_version_tag": "2026-07-07T01:00Z",
        }
        mdb.get_mcp_endpoint_version.side_effect = _version_by_id
        mdb.get_mcp_capability_items.side_effect = _items_by_version
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["new_to_you"] is False
    assert body["has_changes"] is True
    assert body["last_seen_version_id"] == _V1
    assert body["last_seen_version_seq"] == 1
    assert body["change_counts"] == {"added": 1, "removed": 0, "modified": 0, "total": 1}
    # A newly added tool is additive, never breaking.
    assert body["severity_counts"]["additive"] == 1
    assert body["severity_counts"]["breaking"] == 0
    assert body["severity_counts"]["total"] == 1
    assert [c["item_name"] for c in body["changes"]] == ["current"]
    assert body["changes"][0]["change_type"] == "added"
    assert body["changes"][0]["severity"] == "additive"


def test_digest_up_to_date_when_marker_equals_current():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_view.return_value = {
            "last_seen_version_id": _V2,  # already saw the current version
            "seen_at": _NOW,
            "created_at": _NOW,
            "last_seen_version_seq": 2,
            "last_seen_version_tag": "2026-07-07T02:00Z",
        }
        mdb.get_mcp_endpoint_version.side_effect = _version_by_id
        mdb.get_mcp_capability_items.side_effect = _items_by_version
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["new_to_you"] is False
    assert body["has_changes"] is False
    assert body["last_seen_version_id"] == _V2
    assert body["changes"] == []


def test_digest_pruned_last_seen_version_reads_as_new_to_you():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        # Marker exists but its version was pruned → FK SET NULL leaves a NULL pointer.
        mdb.get_mcp_endpoint_view.return_value = {
            "last_seen_version_id": None,
            "seen_at": _NOW,
            "created_at": _NOW,
            "last_seen_version_seq": None,
            "last_seen_version_tag": None,
        }
        mdb.get_mcp_endpoint_version.side_effect = _version_by_id
        mdb.get_mcp_capability_items.side_effect = _items_by_version
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["new_to_you"] is True
    assert body["has_changes"] is False


def test_digest_never_discovered_endpoint_has_no_changes():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {**_ENDPOINT_ROW, "current_version_id": None}
        mdb.get_mcp_endpoint_view.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["new_to_you"] is True
    assert body["has_changes"] is False
    assert body["current_version_id"] is None
    assert body["current_type_counts"]["total"] == 0


def test_digest_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None  # not this tenant's endpoint
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/digest")
    assert r.status_code == 404


# ===========================================================================
# views — advance the marker
# ===========================================================================


def test_record_view_defaults_to_current_version_and_advances_marker():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.record_mcp_endpoint_view.return_value = {
            "last_seen_version_id": _V2,
            "seen_at": _NOW,
        }
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/views")
    assert r.status_code == 200
    body = r.json()
    assert body["last_seen_version_id"] == _V2
    assert body["seen_at"] is not None
    # Marker advanced for the authenticated user to the endpoint's current version.
    mdb.record_mcp_endpoint_view.assert_called_once_with("user-1", _EP, _V2)


def test_record_view_honours_explicit_acknowledged_version():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row(_V1, 1)
        mdb.record_mcp_endpoint_view.return_value = {
            "last_seen_version_id": _V1,
            "seen_at": _NOW,
        }
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/views", json={"version_id": _V1}
        )
    assert r.status_code == 200
    assert r.json()["last_seen_version_id"] == _V1
    mdb.record_mcp_endpoint_view.assert_called_once_with("user-1", _EP, _V1)


def test_record_view_unknown_explicit_version_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/views", json={"version_id": _V1}
        )
    assert r.status_code == 404
    mdb.record_mcp_endpoint_view.assert_not_called()


def test_record_view_on_never_discovered_endpoint_is_400():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {**_ENDPOINT_ROW, "current_version_id": None}
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/views")
    assert r.status_code == 400
    mdb.record_mcp_endpoint_view.assert_not_called()


def test_record_view_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/views")
    assert r.status_code == 404
    mdb.record_mcp_endpoint_view.assert_not_called()


def test_record_view_requires_a_resolvable_user():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": "t1",
        "user_id": None,
        "auth_method": "api_key",
    }
    try:
        with patch("app.mcp_catalog_routes.db") as mdb:
            mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
            # No fallback creator resolvable for this key.
            mdb.get_fallback_creator_user_id_for_tenant.return_value = None
            r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/views")
        assert r.status_code == 403
    finally:
        app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
