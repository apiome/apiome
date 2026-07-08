"""API tests for MCP version history, change report & compare (V2-MCP-18.5 / MCAT-4.5, #3672).

Covers the four tenant-scoped read routes added under
``/v1/mcp/{tenant_slug}/endpoints/{id}/versions``:

- ``GET …/versions``                    — newest-first history with score + change counts
- ``GET …/versions/{vid}``              — one version's full surface (capabilities + items)
- ``GET …/versions/{vid}/changes``      — the stored ``previous → this`` diff
- ``GET …/versions/compare?base&target``— on-demand diff between any two versions

The compare tests exercise the real surface-diff engine (MCAT-4.2): the route reconstructs
each version's surface from mocked capability-item rows and diffs them, so order
normalization, the same-version short-circuit, and the add/remove/modify classification are
all verified end-to-end without a database.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)

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


def _version_row(version_id, seq, *, tag, fingerprint, instructions=None, **counts):
    """Build a row shaped like ``get_mcp_endpoint_version`` returns (incl. aggregates)."""
    return {
        "id": version_id,
        "endpoint_id": _EP,
        "version_seq": seq,
        "version_tag": tag,
        "protocol_version": "2025-06-18",
        "server_name": "acme",
        "server_title": None,
        "server_version": "1.0.0",
        "instructions": instructions,
        "capabilities": {"tools": {"listChanged": True}},
        "surface_fingerprint": fingerprint,
        "discovered_at": _NOW,
        "created_at": _NOW,
        "score": counts.get("score"),
        "grade": counts.get("grade"),
        "scored_at": _NOW if counts.get("score") is not None else None,
        "added_count": counts.get("added", 0),
        "removed_count": counts.get("removed", 0),
        "modified_count": counts.get("modified", 0),
        "total_count": counts.get("added", 0)
        + counts.get("removed", 0)
        + counts.get("modified", 0),
    }


def _tool_row(name, description, ordinal=0):
    """A minimal ``mcp_capability_items`` row for a tool."""
    return {
        "version_id": None,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": description,
        "input_schema": {"type": "object"},
        "output_schema": None,
        "annotations": None,
        "uri": None,
        "uri_template": None,
        "raw": {},
        "ordinal": ordinal,
    }


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# LIST versions
# ===========================================================================


def test_list_versions_newest_first_with_counts_and_current_flag():
    rows = [
        _version_row(_V2, 2, tag="2026-06-26T12:00Z", fingerprint="fp2",
                     added=1, modified=1, score=90, grade="A"),
        _version_row(_V1, 1, tag="2026-06-26T11:00Z", fingerprint="fp1", added=2),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_endpoint_versions.return_value = rows
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions")
    assert r.status_code == 200
    body = r.json()
    assert [v["version_seq"] for v in body["versions"]] == [2, 1]
    latest = body["versions"][0]
    assert latest["is_current"] is True
    assert latest["score"] == 90 and latest["grade"] == "A"
    assert latest["change_counts"] == {"added": 1, "removed": 0, "modified": 1, "total": 2}
    assert body["versions"][1]["is_current"] is False
    assert body["versions"][1]["change_counts"]["total"] == 2


def test_list_versions_serializes_provenance_fields():
    """Each history row carries its discovery provenance on the wire (V2-MCP-34.5)."""
    rows = [
        {
            **_version_row(_V2, 2, tag="2026-06-26T12:00Z", fingerprint="fp2"),
            "discovery_trigger": "sweep",
            "discovery_job_id": "99999999-9999-9999-9999-999999999999",
        },
        # A pre-provenance snapshot serializes explicit nulls — unrecorded, not manual.
        _version_row(_V1, 1, tag="2026-06-26T11:00Z", fingerprint="fp1"),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_endpoint_versions.return_value = rows
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions")
    assert r.status_code == 200
    versions = r.json()["versions"]
    assert versions[0]["discovery_trigger"] == "sweep"
    assert versions[0]["discovery_job_id"] == "99999999-9999-9999-9999-999999999999"
    assert versions[1]["discovery_trigger"] is None
    assert versions[1]["discovery_job_id"] is None


def test_list_versions_scoped_to_token_tenant():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_endpoint_versions.return_value = []
        client.get(f"/v1/mcp/other-slug/endpoints/{_EP}/versions")
        mdb.get_mcp_endpoint.assert_called_once_with("t1", _EP)


def test_list_versions_endpoint_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions")
    assert r.status_code == 404
    mdb.list_mcp_endpoint_versions.assert_not_called()


def test_list_versions_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions")
    assert r.status_code == 401


# ===========================================================================
# GET one version (full surface)
# ===========================================================================


def test_get_version_detail_ok():
    version = _version_row(_V2, 2, tag="t2", fingerprint="fp2",
                           instructions="be nice", added=1)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = version
        mdb.get_mcp_capability_items.return_value = [_tool_row("forecast", "Get forecast")]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V2}")
    assert r.status_code == 200
    v = r.json()["version"]
    assert v["instructions"] == "be nice"
    assert v["capabilities"] == {"tools": {"listChanged": True}}
    assert v["is_current"] is True
    assert len(v["items"]) == 1
    assert v["items"][0]["item_type"] == "tool"
    assert v["items"][0]["name"] == "forecast"
    assert v["items"][0]["input_schema"] == {"type": "object"}


def test_get_version_detail_items_carry_lifecycle_assessment():
    """Every item carries the server-computed lifecycle block (V2-MCP-34.4) — a marked
    capability rolls up to its stage; an unmarked one is `unspecified`, never `stable`."""
    version = _version_row(_V2, 2, tag="t2", fingerprint="fp2", added=1)
    deprecated = _tool_row("old_forecast", "Deprecated — superseded by forecast.", 0)
    plain = _tool_row("forecast", "Get forecast", 1)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = version
        mdb.get_mcp_capability_items.return_value = [deprecated, plain]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V2}")
    assert r.status_code == 200
    items = r.json()["version"]["items"]
    flagged = items[0]["lifecycle"]
    assert flagged["stage"] == "deprecated"
    assert flagged["signals_truncated"] == 0
    assert [s["matched"] for s in flagged["signals"]] == ["deprecated", "superseded by"]
    assert all(
        set(s) == {"id", "stage", "kind", "source", "matched", "excerpt"}
        for s in flagged["signals"]
    )
    unmarked = items[1]["lifecycle"]
    assert unmarked["stage"] == "unspecified"
    assert unmarked["signals"] == []


def test_get_version_404_when_not_under_endpoint():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}")
    assert r.status_code == 404
    mdb.get_mcp_capability_items.assert_not_called()


def test_get_version_rejects_non_uuid():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/not-a-uuid")
    assert r.status_code == 422
    mdb.get_mcp_endpoint_version.assert_not_called()


# ===========================================================================
# GET version changes (stored diff)
# ===========================================================================


def test_get_version_changes_ok():
    version = _version_row(_V2, 2, tag="t2", fingerprint="fp2", added=1, modified=1)
    change_rows = [
        {"version_id": _V2, "change_type": "modified", "item_type": "tool",
         "item_name": "forecast", "detail": {"before": {}, "after": {}}},
        {"version_id": _V2, "change_type": "added", "item_type": "tool",
         "item_name": "alerts", "detail": {"after": {}}},
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = version
        mdb.get_mcp_version_changes.return_value = change_rows
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V2}/changes")
    assert r.status_code == 200
    body = r.json()
    assert body["version_seq"] == 2
    assert body["counts"] == {"added": 1, "removed": 0, "modified": 1, "total": 2}
    assert [c["item_name"] for c in body["changes"]] == ["forecast", "alerts"]


def test_get_version_changes_empty_for_first_version():
    version = _version_row(_V1, 1, tag="t1", fingerprint="fp1")
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = version
        mdb.get_mcp_version_changes.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/changes")
    assert r.status_code == 200
    body = r.json()
    assert body["changes"] == []
    assert body["counts"]["total"] == 0


def test_get_version_changes_404_when_version_missing():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/changes")
    assert r.status_code == 404
    mdb.get_mcp_version_changes.assert_not_called()


# ===========================================================================
# COMPARE two versions (on-demand diff via the real engine)
# ===========================================================================


def _compare_db(mdb):
    """Wire a mock ``db`` so v1 → v2 differs (toolA modified, toolB added)."""
    v1 = _version_row(_V1, 1, tag="t1", fingerprint="fp1")
    v2 = _version_row(_V2, 2, tag="t2", fingerprint="fp2")
    versions = {_V1: v1, _V2: v2}
    items = {
        _V1: [_tool_row("toolA", "old desc", 0)],
        _V2: [_tool_row("toolA", "new desc", 0), _tool_row("toolB", "brand new", 1)],
    }
    mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
    mdb.get_mcp_endpoint_version.side_effect = lambda ep, vid: versions.get(vid)
    mdb.get_mcp_capability_items.side_effect = lambda vid: items[vid]
    return versions


def test_compare_adjacent_versions_added_and_modified():
    # Patch both module `db` references: the route reads versions, the engine reads items.
    with patch("app.mcp_catalog_routes.db") as mdb, \
         patch("app.mcp_discovery_engine.db", mdb):
        _compare_db(mdb)
        r = client.get(
            f"/v1/mcp/acme/endpoints/{_EP}/versions/compare?base={_V1}&target={_V2}"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["base"]["version_seq"] == 1
    assert body["target"]["version_seq"] == 2
    assert body["fingerprint_changed"] is True
    assert body["counts"] == {"added": 1, "removed": 0, "modified": 1, "total": 2}
    by_name = {c["item_name"]: c for c in body["changes"]}
    assert by_name["toolA"]["change_type"] == "modified"
    assert by_name["toolB"]["change_type"] == "added"


def test_compare_normalizes_order_older_to_newer():
    """Passing base=newer, target=older still returns older→newer (added, not removed)."""
    with patch("app.mcp_catalog_routes.db") as mdb, \
         patch("app.mcp_discovery_engine.db", mdb):
        _compare_db(mdb)
        r = client.get(
            f"/v1/mcp/acme/endpoints/{_EP}/versions/compare?base={_V2}&target={_V1}"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["base"]["version_seq"] == 1
    assert body["target"]["version_seq"] == 2
    by_name = {c["item_name"]: c for c in body["changes"]}
    assert by_name["toolB"]["change_type"] == "added"


def test_compare_same_version_is_empty():
    with patch("app.mcp_catalog_routes.db") as mdb, \
         patch("app.mcp_discovery_engine.db", mdb):
        _compare_db(mdb)
        r = client.get(
            f"/v1/mcp/acme/endpoints/{_EP}/versions/compare?base={_V2}&target={_V2}"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["fingerprint_changed"] is False
    assert body["changes"] == []
    assert body["counts"]["total"] == 0
    # Same-version short-circuit must not touch the surface store.
    mdb.get_mcp_capability_items.assert_not_called()


def test_compare_404_when_a_version_missing():
    with patch("app.mcp_catalog_routes.db") as mdb, \
         patch("app.mcp_discovery_engine.db", mdb):
        _compare_db(mdb)
        r = client.get(
            f"/v1/mcp/acme/endpoints/{_EP}/versions/compare?base={_V1}"
            "&target=44444444-4444-4444-4444-444444444444"
        )
    assert r.status_code == 404


def test_compare_requires_base_and_target():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/compare?base={_V1}")
    assert r.status_code == 422


def test_compare_endpoint_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(
            f"/v1/mcp/acme/endpoints/{_EP}/versions/compare?base={_V1}&target={_V2}"
        )
    assert r.status_code == 404
