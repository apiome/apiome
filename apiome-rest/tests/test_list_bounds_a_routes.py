"""The MCP catalog, Browse, agent-toolset and lint-workspace lists are bounded (DBP-1.13, #7196).

Each converted endpoint shows the same four facts through :func:`check_list_paging`: a page of
``limit`` rows reports has-more and a cursor, the cursor walks the rest in order, a ``limit`` over
the documented maximum is a ``422`` and a malformed cursor is a ``400``. Lists whose order is
computed after the read (Browse versions, the duplicate and freshness reports) page by
``limit`` + ``offset`` instead, and the reads behind them are capped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.browse_list_paging import BROWSE_PROJECTS_ORDER
from app.main import app
from app.mcp_list_paging import (
    MCP_DISCOVERY_JOBS_ORDER,
    MCP_ENDPOINT_SOURCES_ORDER,
    MCP_ENDPOINT_VERSIONS_ORDER,
    MCP_ENDPOINTS_BY_NAME,
    MCP_ENDPOINTS_NEWEST,
)
from app.tenant_list_paging import LINT_SAVED_VIEWS_ORDER
from tests.keyset_paging_fakes import check_list_paging, ordered_rows
from tests.test_mcp_browse_routes import _browse_row
from tests.test_mcp_catalog_routes import _ENDPOINT_ROW
from tests.test_mcp_discovery_jobs import _QUEUED_JOB
from tests.test_mcp_duplicate_routes import _candidate_row
from tests.test_mcp_freshness_routes import _candidate
from tests.test_mcp_insight_routes import _version_row

client = TestClient(app)
T0 = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
EP = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt", "permissions": ["*"]}


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


@pytest.fixture(autouse=True)
def _signed_in():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _newest_first(count: int, base: Dict[str, Any]) -> List[Dict[str, Any]]:
    """``count`` rows, newest first, two rows sharing each instant so the id breaks ties."""
    rows = [
        {**base, "id": _uuid(n), "created_at": T0 - timedelta(minutes=n // 2)}
        for n in range(count)
    ]
    return sorted(rows, key=lambda row: (row["created_at"], row["id"]), reverse=True)


# --- cursor lists of the MCP catalog ------------------------------------------------------------


def _mcp_cases() -> List[Any]:
    endpoints = _newest_first(5, _ENDPOINT_ROW)
    jobs = _newest_first(5, _QUEUED_JOB)
    versions = [{**_version_row(_uuid(n), 10 - n)} for n in range(5)]
    sources = _newest_first(
        5, {"source_kind": "repository", "locator": "https://git.example/acme", "tenant_id": "t1"}
    )
    return [
        pytest.param(
            "/v1/mcp/acme/endpoints", "list_mcp_endpoints", MCP_ENDPOINTS_NEWEST, endpoints,
            "endpoints", 1000, ("has_more", "next_cursor"), id="endpoints",
        ),
        pytest.param(
            f"/v1/mcp/acme/endpoints/{EP}/discover", "list_mcp_discovery_jobs",
            MCP_DISCOVERY_JOBS_ORDER, jobs, "jobs", 200, ("has_more", "next_cursor"), id="discover",
        ),
        pytest.param(
            f"/v1/mcp/acme/endpoints/{EP}/jobs", "list_mcp_discovery_jobs",
            MCP_DISCOVERY_JOBS_ORDER, jobs, "jobs", 200, ("has_more", "next_cursor"), id="jobs",
        ),
        pytest.param(
            f"/v1/mcp/acme/endpoints/{EP}/versions", "list_mcp_endpoint_versions",
            MCP_ENDPOINT_VERSIONS_ORDER, versions, "versions", 200, ("has_more", "next_cursor"),
            id="versions",
        ),
        pytest.param(
            f"/v1/mcp/acme/endpoints/{EP}/sources", "list_mcp_endpoint_sources",
            MCP_ENDPOINT_SOURCES_ORDER, sources, "sources", 1000, ("hasMore", "nextCursor"),
            id="sources",
        ),
    ]


@pytest.mark.parametrize("url,accessor,order,rows,key,maximum,envelope", _mcp_cases())
def test_an_mcp_catalog_list_pages_by_cursor(url, accessor, order, rows, key, maximum, envelope):
    with patch("app.mcp_catalog_routes.db") as db:
        db.get_mcp_endpoint.return_value = {"id": EP, "tenant_id": "t1", "current_version_id": None}
        getattr(db, accessor).side_effect = ordered_rows(order, rows)
        check_list_paging(
            lambda params: client.get(url, params=params),
            key,
            [row["id"] for row in rows],
            maximum=maximum,
            # The job-status snapshot names its id ``job_id``; every other row calls it ``id``.
            id_of=lambda item: item.get("id") or item["job_id"],
            has_more_key=envelope[0],
            next_cursor_key=envelope[1],
        )
        # The accessor is asked for one row more than the page, never for the whole list.
        assert all(call.kwargs["limit"] is not None for call in getattr(db, accessor).call_args_list)


def test_the_private_browse_view_groups_one_page_of_endpoints():
    rows = [
        _browse_row(id=_uuid(n), name=f"Endpoint {n}", slug=f"e{n}", endpoint_url=f"https://h{n % 2}.example/mcp")
        for n in range(5)
    ]
    with patch("app.mcp_catalog_routes.db") as db:
        db.browse_mcp_endpoints.side_effect = ordered_rows(MCP_ENDPOINTS_BY_NAME, rows)
        first = client.get("/v1/mcp/acme/browse", params={"limit": 2}).json()
        assert first["has_more"] is True and first["endpoint_count"] == 2
        seen = [e["id"] for g in first["groups"] for e in g["endpoints"]]
        cursor = first["next_cursor"]
        while cursor:
            page = client.get("/v1/mcp/acme/browse", params={"limit": 2, "cursor": cursor}).json()
            seen += [e["id"] for g in page["groups"] for e in g["endpoints"]]
            cursor = page["next_cursor"]
        assert sorted(seen) == [row["id"] for row in rows]
        assert page["has_more"] is False
        assert client.get("/v1/mcp/acme/browse", params={"limit": 1001}).status_code == 422
        assert client.get("/v1/mcp/acme/browse", params={"cursor": "nope"}).status_code == 400
        # Without a limit the route still reads a bounded page (the maximum plus one).
        client.get("/v1/mcp/acme/browse")
        assert db.browse_mcp_endpoints.call_args.kwargs["limit"] == 1001


# --- computed MCP reports page by offset --------------------------------------------------------


def test_the_duplicate_report_pages_its_groups_by_offset():
    candidates = [
        _candidate_row(id=f"ep-{n}", name=f"E{n}", slug=f"e{n}", endpoint_url=f"https://h{n // 2}.example/sse")
        for n in range(6)
    ]
    with patch("app.mcp_catalog_routes.db") as db:
        db.list_mcp_duplicate_candidates.return_value = candidates
        db.list_published_mcp_duplicate_hints.return_value = []
        whole = client.get("/v1/mcp/acme/data-quality/duplicates").json()
        first = client.get("/v1/mcp/acme/data-quality/duplicates", params={"limit": 1}).json()
        last = client.get(
            "/v1/mcp/acme/data-quality/duplicates",
            params={"limit": 1, "offset": whole["group_count"] - 1},
        ).json()
        over = client.get("/v1/mcp/acme/data-quality/duplicates", params={"limit": 201})
    assert whole["group_count"] >= 2 and whole["has_more"] is False
    assert len(first["groups"]) == 1 and first["has_more"] is True
    # The counts keep describing the whole report, not the window.
    assert first["group_count"] == whole["group_count"]
    assert last["groups"] == whole["groups"][-1:] and last["has_more"] is False
    assert over.status_code == 422


def test_the_freshness_report_pages_its_flagged_endpoints_by_offset():
    stale = [
        _candidate(id=f"ep-{n}", name=f"E{n}", slug=f"e{n}", consecutive_failures=5, last_discovery_status="failed")
        for n in range(3)
    ]
    with patch("app.mcp_catalog_routes.db") as db:
        db.list_mcp_freshness_candidates.return_value = stale
        whole = client.get("/v1/mcp/acme/data-quality/freshness").json()
        first = client.get("/v1/mcp/acme/data-quality/freshness", params={"limit": 2}).json()
        rest = client.get(
            "/v1/mcp/acme/data-quality/freshness", params={"limit": 2, "offset": 2}
        ).json()
        over = client.get("/v1/mcp/acme/data-quality/freshness", params={"limit": 1001})
    assert whole["flagged_endpoint_count"] == 3 and whole["has_more"] is False
    assert len(first["endpoints"]) == 2 and first["has_more"] is True
    assert first["flagged_endpoint_count"] == 3
    assert len(rest["endpoints"]) == 1 and rest["has_more"] is False
    assert over.status_code == 422


# --- hard-capped MCP reads ----------------------------------------------------------------------


def test_the_evolution_series_reads_only_the_most_recent_snapshots():
    with patch("app.mcp_catalog_routes.db") as db:
        db.get_mcp_endpoint.return_value = {"id": EP, "tenant_id": "t1", "current_version_id": None}
        db.get_mcp_evolution_series.return_value = []
        db.get_mcp_version_changes_for_endpoint.return_value = []
        url = f"/v1/mcp/acme/endpoints/{EP}/insight/evolution"
        assert client.get(url).status_code == 200
        assert db.get_mcp_evolution_series.call_args.kwargs == {"limit": 1000}
        assert db.get_mcp_version_changes_for_endpoint.call_args.kwargs == {"limit_versions": 1000}
        assert client.get(url, params={"limit": 5}).status_code == 200
        assert db.get_mcp_evolution_series.call_args.kwargs == {"limit": 5}
        assert client.get(url, params={"limit": 1001}).status_code == 422


def test_version_lint_evidence_reads_at_most_two_hundred_runs():
    version = _uuid(7)
    with patch("app.mcp_catalog_routes.db") as db:
        db.get_mcp_endpoint.return_value = {"id": EP, "tenant_id": "t1", "current_version_id": None}
        db.get_mcp_endpoint_version.return_value = _version_row(version, 1)
        db.list_lint_evidence_runs_for_mcp_version.return_value = []
        url = f"/v1/mcp/acme/endpoints/{EP}/versions/{version}/lint/evidence"
        assert client.get(url).status_code == 200
        assert db.list_lint_evidence_runs_for_mcp_version.call_args.kwargs == {"limit": 200}
        assert client.get(url, params={"limit": 201}).status_code == 422


def test_similar_servers_cannot_be_asked_for_more_than_the_rail_shows():
    with patch("app.mcp_catalog_routes.db") as db:
        db.get_mcp_endpoint.return_value = {"id": EP, "tenant_id": "t1", "current_version_id": None}
        db.get_mcp_similar_servers.return_value = {
            "target_capability_count": 0,
            "overlap_rows": [],
            "embedding_rows": [],
        }
        url = f"/v1/mcp/acme/endpoints/{EP}/insight/similar"
        assert client.get(url).status_code == 200
        assert client.get(url, params={"limit": 11}).status_code == 422


# --- public Browse ------------------------------------------------------------------------------

_TENANT = {"id": "tid-1", "slug": "acme-corp", "name": "Acme Corp"}
_STATS = {"tenant_count": 5, "project_count": 5, "version_count": 5}


def _browse_tenant_rows(count: int) -> List[Dict[str, Any]]:
    return [
        {
            "slug": f"tenant-{n}", "name": f"Tenant {n}", "project_count": 1,
            "published_versions": 1, "latest_version": "1.0.0", "latest_activity_at": None,
        }
        for n in range(count)
    ]


def test_the_browse_tenant_directory_reads_one_window():
    with patch("app.browse_public_routes.db") as db:
        db.get_public_browse_directory_stats.return_value = _STATS
        db.list_public_browse_tenants.return_value = _browse_tenant_rows(3)
        page = client.get("/v1/browse/tenants", params={"limit": 2, "offset": 4, "sort": "projects"})
        assert page.status_code == 200
        body = page.json()
        assert [t["slug"] for t in body["tenants"]] == ["tenant-0", "tenant-1"]
        assert body["has_more"] is True and body["filtered_count"] == 2
        kwargs = db.list_public_browse_tenants.call_args.kwargs
        assert (kwargs["limit"], kwargs["offset"]) == (3, 4)
        db.list_public_browse_tenants.return_value = _browse_tenant_rows(2)
        assert client.get("/v1/browse/tenants", params={"limit": 2}).json()["has_more"] is False
        assert client.get("/v1/browse/tenants", params={"limit": 1001}).status_code == 422
        # No limit still reads a bounded window.
        client.get("/v1/browse/tenants")
        assert db.list_public_browse_tenants.call_args.kwargs["limit"] == 1001


def test_browse_projects_page_by_slug_cursor():
    rows = [
        {
            "slug": f"api-{n}", "name": f"API {n}", "metadata": None, "published_versions": 1,
            "latest_version": "1.0.0", "latest_published_at": None, "protocols": [], "formats": [],
        }
        for n in range(5)
    ]
    with patch("app.browse_public_routes.db") as db:
        db.get_tenant_row_by_slug.return_value = _TENANT
        db.list_public_browse_projects_for_tenant.side_effect = ordered_rows(BROWSE_PROJECTS_ORDER, rows)
        db.get_public_browse_project_facets_for_tenant.return_value = {}
        check_list_paging(
            lambda params: client.get("/v1/browse/tenants/acme-corp/projects", params=params),
            "projects",
            [row["slug"] for row in rows],
            maximum=1000,
            id_of=lambda item: item["slug"],
        )


def test_browse_versions_page_by_offset_over_the_semver_order():
    rows = [
        {
            "id": f"v{n}", "version_id": f"1.{n}.0", "published_at": T0, "description": None,
            "change_log": None, "change_path_count": n, "change_class_count": 0, "tags": [],
        }
        for n in range(5)
    ]
    with patch("app.browse_public_routes.db") as db:
        db.get_tenant_row_by_slug.return_value = _TENANT
        db.get_project_by_slug.return_value = {"id": "p1", "slug": "pay", "name": "Pay"}
        db.project_has_public_published_version.return_value = True
        db.list_public_browse_versions_for_project.return_value = rows
        url = "/v1/browse/tenants/acme-corp/projects/pay/versions"
        first = client.get(url, params={"limit": 2}).json()
        second = client.get(url, params={"limit": 2, "offset": 2}).json()
        last = client.get(url, params={"limit": 2, "offset": 4}).json()
        over = client.get(url, params={"limit": 1001})
    assert [v["version_id"] for v in first["versions"]] == ["1.4.0", "1.3.0"]
    assert first["has_more"] is True and first["filtered_count"] == 2
    # The summary is built from the two counts read in SQL; the baseline is the next version
    # of the whole list, also across a page boundary.
    assert first["versions"][1]["changes_summary"] == "3 paths changed vs v1.2.0"
    assert [v["version_id"] for v in second["versions"]] == ["1.2.0", "1.1.0"]
    assert [v["version_id"] for v in last["versions"]] == ["1.0.0"] and last["has_more"] is False
    assert over.status_code == 422


# --- lint workspace -----------------------------------------------------------------------------


def test_saved_workspace_views_page_by_cursor():
    rows = [
        {
            "id": _uuid(n), "tenant_id": "t1", "user_id": "u1", "name": f"View {n}", "filters": {},
            "query": "", "sort": "severity", "is_pinned": n < 2,
            "created_at": T0, "updated_at": T0 - timedelta(minutes=n // 2),
        }
        for n in range(5)
    ]
    with patch("app.lint_workspace_routes.db") as db:
        db.list_lint_workspace_saved_views.side_effect = ordered_rows(LINT_SAVED_VIEWS_ORDER, rows)
        check_list_paging(
            lambda params: client.get("/v1/lint/workspace/views", params=params),
            "views",
            [row["id"] for row in rows],
            maximum=1000,
            has_more_key="hasMore",
            next_cursor_key="nextCursor",
        )


def test_the_workspace_summary_reads_findings_without_their_bodies():
    with patch("app.lint_workspace.db") as db:
        db.list_latest_lint_evidence_runs_for_tenant.return_value = []
        db.list_latest_axis_evaluations_for_tenant.return_value = []
        db.list_latest_lint_policy_evaluations_for_tenant.return_value = []
        db.list_lint_finding_decisions.return_value = []
        assert client.get("/v1/lint/workspace/summary").status_code == 200
        summary = db.list_latest_lint_evidence_runs_for_tenant.call_args.kwargs
        assert client.get("/v1/lint/workspace/findings").status_code == 200
        queue = db.list_latest_lint_evidence_runs_for_tenant.call_args.kwargs
        db.list_lint_finding_decision_events_for_tenant.return_value = []
        db.list_style_guide_policy_versions_for_tenant.return_value = []
        assert client.get("/v1/lint/workspace/trends").status_code == 200
        trends = db.list_latest_lint_evidence_runs_for_tenant.call_args.kwargs
    assert (summary["findings"], summary["row_limit"]) == ("summary", 10_000)
    assert (queue["findings"], queue["row_limit"]) == ("current", 10_000)
    assert (trends["findings"], trends["row_limit"]) == ("fingerprints", 20_000)


# --- agent toolsets -----------------------------------------------------------------------------


def test_agent_toolsets_page_by_cursor(monkeypatch):
    from app import agent_toolsets as toolsets
    from app.database import db as real_db
    from app.openapi_normalizer import OpenApiNormalizer
    from tests.agent_toolset_fakes import FakeToolsetStore
    from tests.test_agent_toolsets import PETSTORE

    monkeypatch.setattr(
        toolsets, "_load_version_api", lambda *_args: OpenApiNormalizer().normalize(PETSTORE)
    )
    monkeypatch.setattr(real_db, "write_access_audit", lambda **_fields: None)
    tenant = "5b8e2f0a-1c3d-4e5f-8a9b-0c1d2e3f0001"
    app.dependency_overrides[validate_authentication] = lambda: {**_AUTH, "tenant_id": tenant}
    store = FakeToolsetStore().install(monkeypatch, real_db)
    base = "/v1/tenants/acme/agent-toolsets"
    created = [
        client.post(base, json={"versionId": store.seed_version(tenant)}).json()["id"]
        for _ in range(4)
    ]
    expected = [row["id"] for row in store.list_agent_toolsets(tenant)]
    assert sorted(expected) == sorted(created)
    check_list_paging(
        lambda params: client.get(base, params=params),
        "toolsets",
        expected,
        maximum=1000,
        has_more_key="hasMore",
        next_cursor_key="nextCursor",
    )


# --- workspace lists document their ceiling -----------------------------------------------------


def test_the_clamped_workspace_lists_document_their_maximum_page_size():
    """They clamp an over-large ``limit`` rather than refuse it; the schema still states the cap."""
    from app import scoped_catalog_store, workspace_property_store

    paths = app.openapi()["paths"]

    def maximum(path: str) -> int:
        limit = next(p for p in paths[path]["get"]["parameters"] if p["name"] == "limit")
        return limit["schema"]["maximum"]

    base = "/v1/workspace/{tenant_slug}/version/{version_id}"
    assert maximum(f"{base}/classes") == scoped_catalog_store.MAX_PAGE_SIZE
    assert maximum(f"{base}/paths") == scoped_catalog_store.MAX_PAGE_SIZE
    assert maximum(f"{base}/properties") == workspace_property_store.MAX_PROPERTY_LIMIT
