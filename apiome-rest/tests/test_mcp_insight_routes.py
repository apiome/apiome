"""API tests for the MCP insight aggregation endpoints (V2-MCP-28.2 / MCAT-14.2, #4628).

Covers the four read routes:

- ``GET …/endpoints/{id}/insight/surface``      — 28.1 metrics for a version (default: current)
- ``GET …/endpoints/{id}/insight/evolution``    — per-version series (counts, grade, churn)
- ``GET …/endpoints/{id}/insight/reliability``  — discovery + invocation reliability aggregates
- ``GET …/insight/catalog``                     — tenant-wide catalog roll-up

The ``db`` module is mocked, so these assert route wiring, tenant-scoped ``404`` behaviour, and the
empty-history → empty/zero (never ``500``) contract. The surface route runs the *real*
``reconstruct_surface`` + ``compute_surface_metrics`` (28.1) over mocked capability rows, and the
reliability route runs the real ``mcp_insight_aggregation`` roll-up over mocked telemetry rows, so
the numbers — including latency percentiles — are verified end-to-end without a database.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)

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
        "version_tag": f"2026-07-06T{seq:02d}:00Z",
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


def _tool_row(name, *, required=None, ordinal=0):
    """A minimal ``mcp_capability_items`` tool row with a two-property input schema."""
    return {
        "version_id": _V2,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": "does a thing",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "city name"},
                "units": {"type": "string", "enum": ["c", "f"]},
            },
            "required": required or [],
        },
        "output_schema": None,
        "annotations": {"readOnlyHint": True},
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
# surface
# ===========================================================================


def test_surface_defaults_to_current_version_and_computes_metrics():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row(_V2, 2)
        mdb.get_mcp_capability_items.return_value = [
            _tool_row("forecast", required=["city"], ordinal=0),
            _tool_row("current", ordinal=1),
        ]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/surface")
    assert r.status_code == 200
    body = r.json()
    assert body["version_id"] == _V2
    assert body["is_current"] is True
    metrics = body["metrics"]
    assert metrics["type_counts"]["tools"] == 2
    assert metrics["type_counts"]["total"] == 2
    assert len(metrics["tool_complexity"]) == 2
    assert metrics["tool_complexity"][0]["property_count"] == 2
    assert metrics["tool_complexity"][0]["required_count"] == 1
    assert metrics["tool_complexity"][0]["uses_enum"] is True
    assert metrics["annotation_coverage"]["read_only_hint"] == 2
    assert metrics["metrics_fingerprint"]
    # Default path resolves the endpoint's current_version_id.
    mdb.get_mcp_endpoint_version.assert_called_once_with(_EP, _V2)


def test_surface_explicit_version_id_is_used():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row(_V1, 1)
        mdb.get_mcp_capability_items.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/surface?version_id={_V1}")
    assert r.status_code == 200
    body = r.json()
    assert body["version_id"] == _V1
    assert body["is_current"] is False  # V1 is not the endpoint's current (V2)
    assert body["metrics"]["type_counts"]["total"] == 0
    mdb.get_mcp_endpoint_version.assert_called_once_with(_EP, _V1)


def test_surface_unknown_version_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/surface?version_id={_V1}")
    assert r.status_code == 404


def test_surface_no_current_version_is_404():
    endpoint = dict(_ENDPOINT_ROW, current_version_id=None)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = endpoint
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/surface")
    assert r.status_code == 404


def test_surface_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/surface")
    assert r.status_code == 404


# ===========================================================================
# graph (V2-MCP-29.2 / MCAT-15.2)
# ===========================================================================


def _prompt_row(name, description, ordinal=0):
    """A minimal ``mcp_capability_items`` prompt row."""
    return {
        "version_id": _V2,
        "item_type": "prompt",
        "name": name,
        "title": None,
        "description": description,
        "input_schema": None,
        "output_schema": None,
        "annotations": None,
        "uri": None,
        "uri_template": None,
        "raw": {"name": name, "description": description},
        "ordinal": ordinal,
    }


def test_graph_defaults_to_current_version_and_infers_edges():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row(_V2, 2)
        mdb.get_mcp_capability_items.return_value = [
            _tool_row("forecast", required=["city"], ordinal=0),
            _prompt_row("plan_trip", "First call forecast to get the weather.", ordinal=0),
        ]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/graph")
    assert r.status_code == 200
    body = r.json()
    assert body["version_id"] == _V2
    assert body["is_current"] is True
    graph = body["graph"]
    assert graph["node_count"] == 2
    # The prompt names the tool → one directed prompt_reference edge, no isolated nodes.
    assert graph["edge_count"] == 1
    edge = graph["edges"][0]
    assert edge["kind"] == "prompt_reference"
    assert edge["directed"] is True
    assert edge["label"] == "forecast"
    assert graph["isolated_count"] == 0
    assert graph["graph_fingerprint"]
    mdb.get_mcp_endpoint_version.assert_called_once_with(_EP, _V2)


def test_graph_shows_isolated_nodes_without_inventing_edges():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row(_V1, 1)
        mdb.get_mcp_capability_items.return_value = [
            _tool_row("forecast", ordinal=0),
            _tool_row("current", ordinal=1),
        ]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/graph?version_id={_V1}")
    assert r.status_code == 200
    body = r.json()
    assert body["is_current"] is False
    graph = body["graph"]
    assert graph["node_count"] == 2
    assert graph["edge_count"] == 0
    assert graph["isolated_count"] == 2
    mdb.get_mcp_endpoint_version.assert_called_once_with(_EP, _V1)


def test_graph_unknown_version_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/graph?version_id={_V1}")
    assert r.status_code == 404


def test_graph_no_current_version_is_404():
    endpoint = dict(_ENDPOINT_ROW, current_version_id=None)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = endpoint
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/graph")
    assert r.status_code == 404


def test_graph_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/graph")
    assert r.status_code == 404


# ===========================================================================
# evolution
# ===========================================================================


def _evolution_row(version_id, seq, *, tools, added=0, removed=0, modified=0, score=90, grade="A"):
    return {
        "id": version_id,
        "endpoint_id": _EP,
        "version_seq": seq,
        "version_tag": f"2026-07-06T{seq:02d}:00Z",
        "discovered_at": _NOW,
        "created_at": _NOW,
        "surface_fingerprint": f"fp{seq}",
        "score": score,
        "grade": grade,
        "tool_count": tools,
        "resource_count": 1,
        "resource_template_count": 0,
        "prompt_count": 0,
        "added_count": added,
        "removed_count": removed,
        "modified_count": modified,
    }


def test_evolution_series_oldest_first_with_counts_and_current_flag():
    rows = [
        _evolution_row(_V1, 1, tools=2, added=3),
        _evolution_row(_V2, 2, tools=4, added=2, modified=1),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_evolution_series.return_value = rows
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/evolution")
    assert r.status_code == 200
    series = r.json()["series"]
    assert [p["version_seq"] for p in series] == [1, 2]
    first, second = series
    assert first["type_counts"]["tools"] == 2
    assert first["type_counts"]["total"] == 3  # 2 tools + 1 resource
    assert first["change_counts"]["added"] == 3
    assert first["change_counts"]["total"] == 3
    assert first["is_current"] is False
    assert second["is_current"] is True  # V2 is current
    assert second["change_counts"]["total"] == 3  # 2 added + 1 modified


def test_evolution_empty_history_returns_empty_series():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = dict(_ENDPOINT_ROW, current_version_id=None)
        mdb.get_mcp_evolution_series.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/evolution")
    assert r.status_code == 200
    assert r.json()["series"] == []


def test_evolution_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/evolution")
    assert r.status_code == 404


# ===========================================================================
# reliability
# ===========================================================================


def test_reliability_aggregates_discovery_and_invocation():
    job_rows = [
        {"state": "completed", "duration_ms": 100.0},
        {"state": "completed", "duration_ms": 200.0},
        {"state": "failed", "duration_ms": 50.0},
    ]
    call_rows = [
        {"is_error": False, "latency_ms": 10},
        {"is_error": True, "latency_ms": 20},
        {"is_error": False, "latency_ms": 40},
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_job_stats.return_value = job_rows
        mdb.list_mcp_invocation_stats.return_value = call_rows
        mdb.list_mcp_tool_invocation_stats.return_value = []
        mdb.list_mcp_discovery_job_timeline.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 200
    body = r.json()
    disc = body["discovery"]
    assert disc["job_count"] == 3
    assert disc["completed_count"] == 2
    assert disc["failed_count"] == 1
    assert disc["success_rate"] == pytest.approx(0.6667, abs=0.0001)
    assert disc["latency"]["min_ms"] == 50.0
    assert disc["latency"]["max_ms"] == 200.0
    inv = body["invocation"]
    assert inv["call_count"] == 3
    assert inv["error_count"] == 1
    assert inv["error_rate"] == pytest.approx(0.3333, abs=0.0001)
    assert inv["latency"]["p50_ms"] == pytest.approx(20.0)


def test_reliability_empty_history_is_zeroes_not_500():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_job_stats.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        mdb.list_mcp_tool_invocation_stats.return_value = []
        mdb.list_mcp_discovery_job_timeline.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 200
    body = r.json()
    assert body["discovery"]["job_count"] == 0
    assert body["discovery"]["success_rate"] == 0.0
    assert body["discovery"]["latency"]["p50_ms"] is None
    assert body["invocation"]["call_count"] == 0
    assert body["invocation"]["error_rate"] == 0.0
    assert body["invocation"]["latency"]["avg_ms"] is None


def test_reliability_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# reliability — discovery health timeline (V2-MCP-31.1 / MCAT-17.1)
# ---------------------------------------------------------------------------


def _timeline_row(job_id, state, *, trigger="sweep", error_code=None):
    return {
        "id": job_id,
        "state": state,
        "trigger": trigger,
        "error_code": error_code,
        "duration_ms": None,
        "created_at": _NOW,
        "started_at": None,
        "finished_at": None,
    }


def test_reliability_health_timeline_and_availability_match_seeded_jobs():
    timeline_rows = [
        _timeline_row("j4", "completed"),
        _timeline_row("j3", "failed", error_code="auth_required"),
        _timeline_row("j2", "completed"),
        _timeline_row("j1", "completed"),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_job_stats.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        mdb.list_mcp_tool_invocation_stats.return_value = []
        mdb.list_mcp_discovery_job_timeline.return_value = timeline_rows
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 200
    health = r.json()["health"]
    assert health["event_count"] == 4
    assert health["ok_count"] == 3
    assert health["failed_count"] == 1
    # hand count: 3 ok / (3 ok + 1 failed) = 75%
    assert health["availability_pct"] == pytest.approx(75.0)
    assert [e["outcome"] for e in health["timeline"]] == [
        "ok",
        "auth_required",
        "ok",
        "ok",
    ]
    assert health["quarantined"] is False


def test_reliability_health_flags_quarantined_endpoint():
    quarantined = {
        **_ENDPOINT_ROW,
        "quarantined_at": _NOW,
        "quarantine_reason": "connect_error: connection refused",
        "consecutive_failures": 5,
        "last_discovery_status": "connect_error",
        "last_discovered_at": _NOW,
    }
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = quarantined
        mdb.list_mcp_discovery_job_stats.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        mdb.list_mcp_tool_invocation_stats.return_value = []
        mdb.list_mcp_discovery_job_timeline.return_value = [
            _timeline_row("j1", "failed", error_code="connect_error"),
        ]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 200
    health = r.json()["health"]
    assert health["quarantined"] is True
    assert health["quarantine_reason"].startswith("connect_error")
    assert health["consecutive_failures"] == 5
    assert health["last_status"] == "connect_error"
    assert health["availability_pct"] == pytest.approx(0.0)


def test_reliability_health_empty_history_is_empty_timeline_not_500():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_job_stats.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        mdb.list_mcp_tool_invocation_stats.return_value = []
        mdb.list_mcp_discovery_job_timeline.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 200
    health = r.json()["health"]
    assert health["timeline"] == []
    assert health["event_count"] == 0
    assert health["availability_pct"] is None
    assert health["quarantined"] is False


# ---------------------------------------------------------------------------
# reliability — per-tool latency & error-rate panel (V2-MCP-31.2 / MCAT-17.2)
# ---------------------------------------------------------------------------


def _tool_call_row(item_name, is_error, latency_ms):
    return {"item_name": item_name, "is_error": is_error, "latency_ms": latency_ms}


def test_reliability_tools_percentiles_and_error_rates_match_fixture():
    tool_rows = [
        _tool_call_row("search", False, 10),
        _tool_call_row("search", False, 20),
        _tool_call_row("search", True, 30),
        _tool_call_row("search", False, 40),
        _tool_call_row("write", True, 100),
        _tool_call_row("write", True, 300),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_job_stats.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        mdb.list_mcp_tool_invocation_stats.return_value = tool_rows
        mdb.list_mcp_discovery_job_timeline.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 200
    tools = r.json()["tools"]
    assert tools["tool_count"] == 2
    assert tools["call_count"] == 6
    assert tools["error_count"] == 3
    assert tools["error_rate"] == pytest.approx(0.5)
    assert tools["window_days"] == 30
    by_name = {t["tool_name"]: t for t in tools["tools"]}
    assert by_name["search"]["error_rate"] == pytest.approx(0.25)
    assert by_name["search"]["latency"]["p50_ms"] == pytest.approx(25.0)
    assert by_name["write"]["error_rate"] == pytest.approx(1.0)
    # The distribution has a stable bucket set that sums to the calls with a recorded latency.
    assert sum(b["count"] for b in tools["latency_distribution"]) == 6
    # The window is passed through to the DB helper.
    mdb.list_mcp_tool_invocation_stats.assert_called_once_with(_EP, 30)


def test_reliability_tools_empty_history_is_no_data_not_500():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_job_stats.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        mdb.list_mcp_tool_invocation_stats.return_value = []
        mdb.list_mcp_discovery_job_timeline.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/reliability")
    assert r.status_code == 200
    tools = r.json()["tools"]
    assert tools["tools"] == []
    assert tools["tool_count"] == 0
    assert tools["call_count"] == 0
    assert tools["error_rate"] == 0.0


# ===========================================================================
# trust profile (V2-MCP-31.4 / MCAT-17.4)
# ===========================================================================


def _trust_tool_row(name, annotations, *, ordinal=0):
    """A tool row with caller-supplied annotations, for the trust route's safety cross-reference."""
    row = _tool_row(name, required=["city"], ordinal=ordinal)
    row["annotations"] = annotations
    return row


def test_trust_profile_computes_all_five_axes():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row(_V2, 2)  # score 90, grade A
        mdb.get_mcp_capability_items.return_value = [
            _trust_tool_row("read", {"readOnlyHint": True}, ordinal=0),
            _trust_tool_row("wipe", {"destructiveHint": True}, ordinal=1),
        ]
        # Anonymous (no credential) + a destructive tool → the safety guardedness penalty applies.
        mdb.get_mcp_endpoint_credentials.return_value = {"auth_type": "none"}
        mdb.get_mcp_evolution_series.return_value = [
            _evolution_row(_V1, 1, tools=2),
            _evolution_row(_V2, 2, tools=2),
        ]
        # One additive transition on the current snapshot → non-breaking → full stability.
        mdb.get_mcp_version_changes_for_endpoint.return_value = [
            {"version_id": _V2, "change_type": "added", "item_type": "tool", "item_name": "wipe"},
        ]
        mdb.list_mcp_invocation_stats.return_value = [
            {"is_error": False, "latency_ms": 100},
            {"is_error": True, "latency_ms": 200},
            {"is_error": False, "latency_ms": 150},
        ]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/trust")
    assert r.status_code == 200
    body = r.json()
    assert body["version_id"] == _V2
    assert body["auth_type"] == "none"
    profile = body["profile"]
    axes = {a["key"]: a for a in profile["axes"]}
    assert [a["key"] for a in profile["axes"]] == [
        "quality",
        "safety",
        "documentation",
        "stability",
        "responsiveness",
    ]
    assert profile["axis_count"] == 5
    assert profile["available_count"] == 5
    assert axes["quality"]["value"] == pytest.approx(90.0)
    # 2/2 annotated (transparency 1.0); anonymous + 1 of 2 destructive (guardedness 0.5) → 75.
    assert axes["safety"]["value"] == pytest.approx(75.0)
    # description 100% + title 0% + params 50% → mean 50.
    assert axes["documentation"]["value"] == pytest.approx(50.0)
    assert axes["stability"]["value"] == pytest.approx(100.0)
    assert axes["responsiveness"]["available"] is True
    assert axes["responsiveness"]["value"] > 0
    assert profile["overall"] is not None
    # every axis carries the hover methodology + a detail line.
    assert all(a["methodology"] and a["detail"] for a in profile["axes"])
    mdb.get_mcp_endpoint_version.assert_called_once_with(_EP, _V2)


def test_trust_profile_partial_gaps_excluded_from_overall():
    # An unscored current snapshot → the quality axis is a gap, not a zero.
    unscored = dict(_version_row(_V2, 2), score=None, grade=None)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = unscored
        mdb.get_mcp_capability_items.return_value = [
            _trust_tool_row("read", {"readOnlyHint": True}, ordinal=0),
        ]
        mdb.get_mcp_endpoint_credentials.return_value = {"auth_type": "bearer"}
        mdb.get_mcp_evolution_series.return_value = []
        mdb.get_mcp_version_changes_for_endpoint.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/trust")
    assert r.status_code == 200
    axes = {a["key"]: a for a in r.json()["profile"]["axes"]}
    assert axes["quality"]["available"] is False
    assert axes["quality"]["value"] is None
    # never-tested → responsiveness gap; single snapshot → stability gap.
    assert axes["responsiveness"]["available"] is False
    assert axes["stability"]["available"] is False
    # safety/documentation are still present (there is a surface).
    assert axes["safety"]["available"] is True
    assert axes["documentation"]["available"] is True


def test_trust_profile_never_discovered_is_all_gaps_not_500():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = dict(_ENDPOINT_ROW, current_version_id=None)
        mdb.get_mcp_endpoint_credentials.return_value = None
        mdb.get_mcp_evolution_series.return_value = []
        mdb.get_mcp_version_changes_for_endpoint.return_value = []
        mdb.list_mcp_invocation_stats.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/trust")
    assert r.status_code == 200
    body = r.json()
    assert body["version_id"] is None
    profile = body["profile"]
    assert profile["available_count"] == 0
    assert profile["overall"] is None
    assert all(a["available"] is False and a["value"] is None for a in profile["axes"])
    # a never-discovered endpoint never reads a version surface.
    mdb.get_mcp_endpoint_version.assert_not_called()


def test_trust_profile_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/trust")
    assert r.status_code == 404


# ===========================================================================
# catalog
# ===========================================================================


def test_catalog_insight_rolls_up_tenant_catalog():
    aggregate = {
        "endpoint_count": 5,
        "published_count": 2,
        "public_count": 2,
        "private_count": 3,
        "discovered_count": 4,
        "scored_count": 4,
        "avg_score": 82.5,
        "tool_count": 20,
        "resource_count": 7,
        "resource_template_count": 1,
        "prompt_count": 2,
        "grade_distribution": {"A": 2, "B": 1, "C": 1},
        # composition breakdowns (18.1) — NULL labels exercise the friendly-placeholder projection.
        "category_rows": [
            {"label": "search", "count": 3},
            {"label": None, "count": 2},
        ],
        "transport_rows": [
            {"label": "streamable_http", "count": 4},
            {"label": "sse", "count": 1},
        ],
        "protocol_rows": [
            {"label": "2025-06-18", "count": 3},
            {"label": None, "count": 1},
        ],
        "discovery_rows": [
            {"label": "ok", "count": 4},
            {"label": None, "count": 1},
        ],
        "change_leader_rows": [
            {"endpoint_id": "e1", "name": "Alpha", "change_count": 9},
            {"endpoint_id": "e2", "name": "Beta", "change_count": 4},
        ],
        "top_capability_rows": [
            {"item_type": "tool", "item_name": "search", "endpoint_count": 3},
            {"item_type": "resource", "item_name": "readme", "endpoint_count": 1},
        ],
        "tool_count_rows": [
            {"tool_count": 0},
            {"tool_count": 3},
            {"tool_count": 12},
            {"tool_count": 40},
            {"tool_count": 77},
        ],
    }
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_catalog_insight.return_value = aggregate
        r = client.get("/v1/mcp/acme/insight/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["endpoint_count"] == 5
    assert body["discovered_count"] == 4
    assert body["average_score"] == 82.5
    assert body["type_counts"]["tools"] == 20
    assert body["type_counts"]["total"] == 30  # 20 + 7 + 1 + 2
    assert body["grade_distribution"] == {"A": 2, "B": 1, "C": 1}
    # NULL category / protocol / discovery labels resolve to friendly placeholders.
    assert body["category_distribution"] == [
        {"label": "search", "count": 3},
        {"label": "Uncategorized", "count": 2},
    ]
    assert body["transport_distribution"][0] == {"label": "streamable_http", "count": 4}
    assert body["protocol_version_distribution"][-1] == {"label": "Unknown", "count": 1}
    assert body["discovery_health"][-1] == {"label": "never", "count": 1}
    # the five tool counts fall one into each fixed histogram bucket, in display order.
    assert body["tool_count_distribution"] == [
        {"label": "0", "count": 1},
        {"label": "1–5", "count": 1},
        {"label": "6–20", "count": 1},
        {"label": "21–50", "count": 1},
        {"label": "50+", "count": 1},
    ]
    assert body["change_leaders"][0] == {
        "endpoint_id": "e1",
        "name": "Alpha",
        "change_count": 9,
    }
    assert body["top_capabilities"][0] == {
        "item_type": "tool",
        "item_name": "search",
        "endpoint_count": 3,
    }
    mdb.get_mcp_catalog_insight.assert_called_once_with("t1")


def test_catalog_insight_empty_tenant():
    aggregate = {
        "endpoint_count": 0,
        "published_count": 0,
        "public_count": 0,
        "private_count": 0,
        "discovered_count": 0,
        "scored_count": 0,
        "avg_score": None,
        "tool_count": 0,
        "resource_count": 0,
        "resource_template_count": 0,
        "prompt_count": 0,
        "grade_distribution": {},
    }
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_catalog_insight.return_value = aggregate
        r = client.get("/v1/mcp/acme/insight/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["endpoint_count"] == 0
    assert body["average_score"] is None
    assert body["type_counts"]["total"] == 0
    assert body["grade_distribution"] == {}
    # every composition breakdown is empty — an all-empty body, never a 500.
    assert body["category_distribution"] == []
    assert body["transport_distribution"] == []
    assert body["protocol_version_distribution"] == []
    assert body["discovery_health"] == []
    assert body["change_leaders"] == []
    assert body["top_capabilities"] == []
    # the tool-count histogram still renders its fixed, all-zero set of buckets so the chart is stable.
    assert body["tool_count_distribution"] == [
        {"label": "0", "count": 0},
        {"label": "1–5", "count": 0},
        {"label": "6–20", "count": 0},
        {"label": "21–50", "count": 0},
        {"label": "50+", "count": 0},
    ]


# ===========================================================================
# percentile (peer percentile & category ranking — MCAT-18.3)
# ===========================================================================

_EP_B = "44444444-4444-4444-4444-444444444444"
_EP_C = "55555555-5555-5555-5555-555555555555"
_VB = "66666666-6666-6666-6666-666666666666"
_VC = "77777777-7777-7777-7777-777777777777"

_WEATHER_ENDPOINT = dict(_ENDPOINT_ROW, category="weather")


def _cohort_member(endpoint_id, version_id, *, score, grade, auth_type, tools, invocations):
    """A row shaped like one entry of ``get_mcp_category_cohort``.

    ``version`` + ``items`` reconstruct the surface for the safety/documentation axes; ``score`` /
    ``grade`` drive the grade axis; ``invocation_stats`` drive the latency axis. A ``version_id`` of
    ``None`` models a never-discovered member (surface-derived axes become gaps).
    """
    version = _version_row(version_id, 1) if version_id else None
    if version is not None:
        version["id"] = version_id
    items = [_trust_tool_row(name, ann, ordinal=i) for i, (name, ann) in enumerate(tools)]
    return {
        "endpoint_id": endpoint_id,
        "current_version_id": version_id,
        "score": score,
        "grade": grade,
        "auth_type": auth_type,
        "version": version,
        "items": items if version_id else [],
        "invocation_stats": invocations,
    }


def test_percentile_ranks_target_within_category_cohort():
    # Three weather servers; the target (_EP) leads on grade (90 vs 75 vs 60).
    cohort = [
        _cohort_member(
            _EP,
            _V2,
            score=90,
            grade="A",
            auth_type="bearer",
            tools=[("read", {"readOnlyHint": True}), ("forecast", {"readOnlyHint": True})],
            invocations=[{"is_error": False, "latency_ms": 120}],
        ),
        _cohort_member(
            _EP_B,
            _VB,
            score=60,
            grade="C",
            auth_type="none",
            tools=[("wipe", {"destructiveHint": True})],
            invocations=[{"is_error": True, "latency_ms": 4000}],
        ),
        _cohort_member(
            _EP_C,
            _VC,
            score=75,
            grade="B",
            auth_type="bearer",
            tools=[("lookup", {})],
            invocations=[{"is_error": False, "latency_ms": 900}],
        ),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _WEATHER_ENDPOINT
        mdb.get_mcp_category_cohort.return_value = cohort
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/percentile")
    assert r.status_code == 200
    body = r.json()
    assert body["endpoint_id"] == _EP
    profile = body["profile"]
    assert profile["category"] == "weather"
    assert profile["cohort_size"] == 3
    axes = {a["key"]: a for a in profile["axes"]}
    assert [a["key"] for a in profile["axes"]] == ["grade", "safety", "documentation", "latency"]

    # grade: target 90 is the cohort max → rank 1, percentile 100, top 34% (ceil(100/3)).
    grade = axes["grade"]
    assert grade["available"] is True
    assert grade["value"] == pytest.approx(90.0)
    assert grade["rank"] == 1
    assert grade["percentile"] == 100.0
    assert grade["top_percent"] == 34
    assert grade["cohort_size"] == 3
    assert "top 34%" in grade["detail"]

    # latency: the target (p95 120ms, at the fast floor) is the snappiest → rank 1.
    assert axes["latency"]["available"] is True
    assert axes["latency"]["rank"] == 1
    # the cohort is read once, scoped to the token's tenant + the endpoint's category.
    mdb.get_mcp_category_cohort.assert_called_once_with("t1", "weather")


def test_percentile_single_member_category_is_leader():
    cohort = [
        _cohort_member(
            _EP,
            _V2,
            score=73,
            grade="B",
            auth_type="bearer",
            tools=[("read", {"readOnlyHint": True})],
            invocations=[{"is_error": False, "latency_ms": 300}],
        ),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _WEATHER_ENDPOINT
        mdb.get_mcp_category_cohort.return_value = cohort
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/percentile")
    assert r.status_code == 200
    profile = r.json()["profile"]
    assert profile["cohort_size"] == 1
    grade = {a["key"]: a for a in profile["axes"]}["grade"]
    assert grade["rank"] == 1
    assert grade["percentile"] == 100.0
    assert grade["top_percent"] == 100
    assert "Only server" in grade["detail"]


def test_percentile_uncategorized_endpoint_uses_uncategorized_cohort():
    uncategorized = dict(_ENDPOINT_ROW, category=None)
    cohort = [
        _cohort_member(
            _EP,
            _V2,
            score=80,
            grade="B",
            auth_type="bearer",
            tools=[("read", {"readOnlyHint": True})],
            invocations=[],
        ),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = uncategorized
        mdb.get_mcp_category_cohort.return_value = cohort
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/percentile")
    assert r.status_code == 200
    assert r.json()["profile"]["category"] is None
    mdb.get_mcp_category_cohort.assert_called_once_with("t1", None)


def test_percentile_never_discovered_target_is_all_gaps_not_500():
    # The target has never been discovered or tested → every axis is an explicit gap, but a 200.
    cohort = [
        _cohort_member(
            _EP,
            None,  # never discovered → no surface, no grade
            score=None,
            grade=None,
            auth_type=None,
            tools=[],
            invocations=[],
        ),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = dict(_WEATHER_ENDPOINT, current_version_id=None)
        mdb.get_mcp_category_cohort.return_value = cohort
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/percentile")
    assert r.status_code == 200
    profile = r.json()["profile"]
    assert all(a["available"] is False and a["value"] is None for a in profile["axes"])


def test_percentile_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/insight/percentile")
    assert r.status_code == 404
