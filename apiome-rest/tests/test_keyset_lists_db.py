"""Keyset pages and the mock data plane against Postgres (DBP-1.13, #7196).

The unit tests check the SQL text; these run it. Each list is walked page by page through the
real app and must return exactly the rows, in exactly the order, of the unpaged read — including
when every row shares one ``created_at`` (the harness writes in one transaction, so the id
tie-breaker does all the work). The mock data plane is held to its statement budget: one narrow
statement per warm request and no write until the flush.

Skips when no database is reachable.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app import mock_routes
from app.keyset_pagination import HAS_MORE_HEADER, NEXT_CURSOR_HEADER
from app.mcp_insight_aggregation import (
    compute_discovery_reliability,
    discovery_aggregate_sql,
    discovery_reliability_from_aggregate,
)
from app.mock_data_plane import ActivityBuffer, SpecCache, flush_activity
from app.mock_routing import extract_operations
from app.statement_stats import capture
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision
from tests.test_query_budgets_db import _guarded, ctx  # noqa: F401 - the app on the test connection

pytestmark = pytest.mark.requires_db

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}, "post": {"responses": {}}, "parameters": []},
        "/pets/{id}": {"get": {"responses": {}}, "x-internal": {"note": "not an operation"}},
        "/broken": "not an object",
    },
}


def _walk(ctx: Dict[str, Any], path: str, limit: int) -> List[Dict[str, Any]]:  # noqa: F811
    """Read a bare-array list to its end through the paging headers."""
    rows: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(100):
        params = {"limit": limit, **({"cursor": cursor} if cursor else {})}
        response = ctx["client"].get(path, headers=ctx["headers"], params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page) <= limit
        rows.extend(page)
        if response.headers[HAS_MORE_HEADER] != "true":
            assert NEXT_CURSOR_HEADER not in response.headers
            return rows
        cursor = response.headers[NEXT_CURSOR_HEADER]
    raise AssertionError("the list never ended")


def test_versions_page_to_the_end_in_the_unpaged_order(ctx) -> None:  # noqa: F811
    db = ctx["db"]
    for label in ("1.1.0", "1.2.0", "2.0.0", "2.1.0"):
        db.create_version(ctx["project"], ctx["user"], label)
    whole = [str(row["id"]) for row in db.get_versions_for_project(ctx["project"], ctx["tenant"])]
    assert len(whole) == 5

    paged = _walk(ctx, f"/v1/versions/{ctx['tenant_slug']}/{ctx['project']}", limit=2)
    assert [row["id"] for row in paged] == whole


def test_projects_and_catalog_page_to_the_end_in_the_unpaged_order(ctx) -> None:  # noqa: F811
    db, conn = ctx["db"], ctx["conn"]
    with conn.cursor() as cur:
        for n in range(4):
            cur.execute(
                "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable) "
                "VALUES (%s, %s, %s, %s, %s)",
                (ctx["tenant"], ctx["user"], f"Paged {n}", f"paged-7196-{n}", n % 2 == 0),
            )
    whole = [str(row["id"]) for row in db.get_projects_for_tenant(ctx["tenant"])]
    assert len(whole) >= 5
    paged = _walk(ctx, f"/v1/projects/{ctx['tenant_slug']}", limit=2)
    assert [row["id"] for row in paged] == whole

    catalog = [str(row["id"]) for row in db.get_catalog_items_for_tenant(ctx["tenant"])]
    assert len(catalog) == 2
    paged = _walk(ctx, f"/v1/catalog/{ctx['tenant_slug']}", limit=1)
    assert [row["id"] for row in paged] == catalog


def test_classes_and_paths_page_to_the_end_by_name(ctx) -> None:  # noqa: F811
    db, conn, version = ctx["db"], ctx["conn"], ctx["version"]
    with conn.cursor() as cur:
        for name in ("Zebra", "apple", "Mango", "banana", "Cherry"):
            cur.execute(
                "INSERT INTO apiome.classes (version_id, name, schema) VALUES (%s, %s, '{}'::jsonb)",
                (version, name),
            )
        for pathname in ("/z", "/a/{id}", "/m", "/b"):
            cur.execute(
                "INSERT INTO apiome.version_path (version_id, pathname) VALUES (%s, %s)", (version, pathname)
            )
    classes = [str(row["id"]) for row in db.get_classes_for_tenant_version(ctx["tenant"], version)]
    paged = _walk(ctx, f"/v1/classes/{ctx['tenant_slug']}?version_id={version}", limit=2)
    assert [row["id"] for row in paged] == classes and len(classes) >= 5

    tenant_wide = [str(row["id"]) for row in db.get_classes_for_tenant(ctx["tenant"])]
    paged = _walk(ctx, f"/v1/classes/{ctx['tenant_slug']}", limit=2)
    assert [row["id"] for row in paged] == tenant_wide

    paths = [str(row["id"]) for row in db.get_paths_for_version_with_tenant(version, ctx["tenant"])]
    paged = _walk(ctx, f"/v1/paths/{ctx['tenant_slug']}/{version}", limit=3)
    assert [row["id"] for row in paged] == paths and len(paths) >= 4


def _mock(ctx: Dict[str, Any], name: str, settings: Any = "{}") -> str:  # noqa: F811
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.mock_instances (tenant_id, tenant_slug, project_slug, version_slug, name, "
            "spec, config, settings, rate_limit_per_minute, expires_at) "
            "VALUES (%s, 't', 'p', 'v', %s, %s::jsonb, %s::jsonb, %s::jsonb, 1000, now() + interval '1 hour') "
            "RETURNING id::text AS id",
            (ctx["tenant"], name, json.dumps(SPEC), json.dumps({"seed": 7, "origin": "x"}), settings),
        )
        return cur.fetchone()["id"]


def test_the_mock_list_counts_operations_in_sql_and_leaves_the_spec_out(ctx, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(mock_routes.settings, "mock_server_enabled", True)
    for n in range(3):
        _mock(ctx, f"mock {n}")
    rows = ctx["db"].list_mock_instances(ctx["tenant"], summary=True, limit=10)
    assert [row["operation_count"] for row in rows] == [len(extract_operations(SPEC))] * 3 == [3] * 3
    assert all(row["spec"] is None for row in rows)

    paged = _walk(ctx, f"/v1/mocks/{ctx['tenant_slug']}", limit=2)
    assert [row["id"] for row in paged] == [str(row["id"]) for row in rows]
    assert {row["operationCount"] for row in paged} == {3}

    only_origin = ctx["db"].list_mock_instances(ctx["tenant"], origin="x")
    assert len(only_origin) == 3 and only_origin[0]["spec"] == SPEC
    assert ctx["db"].list_mock_instances(ctx["tenant"], origin="export-test-drive") == []


def test_a_warm_mock_request_is_one_statement_and_the_flush_one_update(ctx, monkeypatch) -> None:  # noqa: F811
    mock_id = _mock(ctx, "served")
    cache, buffer = SpecCache(), ActivityBuffer()
    monkeypatch.setattr(mock_routes.settings, "mock_server_enabled", True)
    monkeypatch.setattr(mock_routes, "spec_cache", cache)
    monkeypatch.setattr(mock_routes, "activity_buffer", buffer)
    monkeypatch.setattr(mock_routes, "sandbox_is_configured", lambda: True)
    bundles: List[Any] = []

    async def _serve(**kwargs: Any) -> Dict[str, Any]:
        bundles.append(kwargs)
        return {"status": 200, "headers": {}, "mediaType": "application/json", "body": {}, "bodyEncoding": "json"}

    monkeypatch.setattr(mock_routes, "request_sandbox_serve", _serve)
    call = lambda: ctx["client"].get(f"/v1/mock/{mock_id}/pets")  # noqa: E731

    with capture() as cold:
        assert call().status_code == 200
    assert cold.count == 2  # the serving row, then the spec once

    _guarded(ctx, "GET /v1/mock/{mock}/… (warm)", call)
    with capture() as warm:
        assert call().status_code == 200
    assert warm.count == 1
    assert bundles[-1]["request"]["seed"] == 7

    row = ctx["db"].get_mock_instance(mock_id)
    assert row["request_count"] == 0 and row["last_activity_at"] is None  # nothing written yet

    with capture() as flush:
        assert flush_activity(ctx["db"], buffer) == 1
    assert flush.count == 1
    row = ctx["db"].get_mock_instance(mock_id)
    assert row["request_count"] == 3 and row["last_activity_at"] is not None


def test_the_sql_discovery_aggregate_equals_the_python_one(ctx) -> None:  # noqa: F811
    with ctx["conn"].cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE jobs_7196 ON COMMIT DROP AS
            SELECT (ARRAY['queued','running','completed','failed','other'])[1 + (g % 5)] AS state,
                   CASE WHEN g % 7 = 0 THEN NULL ELSE (g * 37 % 5000)::numeric / 3 END AS duration_ms
            FROM generate_series(1, 500) g
            """
        )
        cur.execute("SELECT state, duration_ms FROM jobs_7196")
        rows = [dict(row) for row in cur.fetchall()]
        cur.execute(f"SELECT {discovery_aggregate_sql('duration_ms')} FROM jobs_7196")
        aggregate = dict(cur.fetchone())
    assert discovery_reliability_from_aggregate(aggregate) == compute_discovery_reliability(rows)
