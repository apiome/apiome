"""The SQL behind the bounded MCP, Browse, toolset and lint-workspace lists (DBP-1.13, #7196).

Each accessor is run against a captured ``execute_query``: with no ``limit`` it reads the whole
list exactly as before (internal callers), with one it continues after the cursor on the list's
own ``ORDER BY`` and stops at a ``LIMIT`` — never an ``OFFSET`` for the cursor lists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, List, Tuple
from unittest.mock import patch

import pytest

from app.browse_list_paging import BROWSE_VERSIONS_CAP
from app.database import db
from app.mcp_list_paging import MCP_REPORT_SCAN_CAP

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
STAMP = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)


def _capture(call: Callable[[], Any]) -> Tuple[str, Tuple[Any, ...]]:
    with patch.object(db, "execute_query", return_value=[]) as query:
        call()
    sql, params = query.call_args.args
    assert sql.count("%s") == len(params), "placeholders and parameters must line up"
    return " ".join(sql.split()), tuple(params)


def _cases() -> List[Any]:
    return [
        pytest.param(
            lambda **kw: db.list_mcp_endpoints(TENANT, **kw),
            "ORDER BY mcp_endpoints.created_at DESC, mcp_endpoints.id DESC",
            [STAMP, OTHER],
            id="mcp-endpoints",
        ),
        pytest.param(
            lambda **kw: db.list_mcp_discovery_jobs(TENANT, OTHER, **kw),
            "ORDER BY created_at DESC, id DESC",
            [STAMP, OTHER],
            id="mcp-discovery-jobs",
        ),
        pytest.param(
            lambda **kw: db.list_mcp_endpoint_versions(OTHER, **kw),
            "ORDER BY v.version_seq DESC, v.id DESC",
            [7, OTHER],
            id="mcp-endpoint-versions",
        ),
        pytest.param(
            lambda **kw: db.list_mcp_endpoint_sources(OTHER, **kw),
            "ORDER BY created_at DESC, id DESC",
            [STAMP, OTHER],
            id="mcp-endpoint-sources",
        ),
        pytest.param(
            lambda **kw: db.browse_mcp_endpoints(TENANT, **kw),
            "ORDER BY e.name ASC, e.id ASC",
            ["Weather", OTHER],
            id="mcp-browse",
        ),
        pytest.param(
            lambda **kw: db.list_agent_toolsets(TENANT, **kw),
            "ORDER BY ts.created_at DESC, ts.id ASC",
            [STAMP, OTHER],
            id="agent-toolsets",
        ),
        pytest.param(
            lambda **kw: db.list_lint_workspace_saved_views(TENANT, OTHER, **kw),
            "ORDER BY is_pinned DESC, updated_at DESC, name ASC, id ASC",
            [True, STAMP, "View", OTHER],
            id="lint-saved-views",
        ),
        pytest.param(
            lambda **kw: db.list_schema_test_suites(TENANT, **kw),
            "ORDER BY s.created_at DESC, s.id DESC",
            [STAMP, OTHER],
            id="schema-suites",
        ),
        pytest.param(
            lambda **kw: db.list_public_browse_projects_for_tenant(TENANT, **kw),
            "ORDER BY a.slug ASC",
            ["payments"],
            id="browse-projects",
        ),
        pytest.param(
            lambda **kw: db.list_member_browse_projects_for_tenant(TENANT, **kw),
            "ORDER BY pb.slug ASC",
            ["payments"],
            id="browse-member-projects",
        ),
    ]


@pytest.mark.parametrize("accessor,order_by,cursor", _cases())
def test_a_cursor_list_reads_a_window_on_its_own_ordering(accessor, order_by, cursor):
    whole_sql, whole_params = _capture(accessor)
    assert order_by in whole_sql
    assert "LIMIT %s" not in whole_sql, "no limit means the whole list, as before"

    first_sql, first_params = _capture(lambda: accessor(limit=3))
    assert first_sql.rstrip().endswith("LIMIT %s") and first_params[-1] == 3
    assert first_params[:-1] == whole_params

    next_sql, next_params = _capture(lambda: accessor(limit=3, cursor=cursor))
    assert order_by in next_sql and "OFFSET" not in next_sql
    # The cursor's values are bound after the list's own filters and before the limit.
    assert next_params[: len(whole_params)] == whole_params and next_params[-1] == 3
    assert set(map(str, cursor)) <= set(map(str, next_params[len(whole_params) : -1]))
    assert len(next_sql) > len(first_sql)


def test_the_browse_tenant_directory_reads_a_limit_and_offset_window():
    whole_sql, whole_params = _capture(lambda: db.list_public_browse_tenants(sort="projects"))
    assert "LIMIT" not in whole_sql.split("ORDER BY a.project_count DESC")[-1]
    sql, params = _capture(lambda: db.list_public_browse_tenants(sort="projects", limit=11, offset=20))
    assert sql.endswith("ORDER BY a.project_count DESC, a.name ASC, a.slug ASC LIMIT %s OFFSET %s")
    assert params == (*whole_params, 11, 20)


def test_browse_versions_read_counts_instead_of_the_change_model_and_are_capped():
    sql, params = _capture(lambda: db.list_public_browse_versions_for_project(TENANT, "payments"))
    assert "cr.change_model_json," not in sql and "AS change_model_json" not in sql
    assert "AS change_class_count" in sql and "AS change_path_count" in sql
    assert sql.endswith(f"ORDER BY v.published_at DESC NULLS LAST, v.id DESC LIMIT {BROWSE_VERSIONS_CAP}")
    assert "v.visibility = 'public'" in sql and params == (TENANT, "payments")
    member_sql, _ = _capture(lambda: db.list_member_browse_versions_for_project(TENANT, "payments"))
    assert "v.visibility = 'public'" not in member_sql
    assert member_sql.endswith(f"LIMIT {BROWSE_VERSIONS_CAP}")


def test_the_batched_browse_version_read_also_leaves_the_change_model_behind():
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_browse_versions_for_projects(TENANT, ["payments"], public=True)
    select_list = " ".join(query.call_args.args[0].split()).split("FROM apiome.versions")[0]
    assert "cr.change_model_json," not in select_list and "AS change_path_count" in select_list


@pytest.mark.parametrize(
    "accessor",
    [
        lambda: db.list_mcp_duplicate_candidates(TENANT),
        lambda: db.list_published_mcp_duplicate_hints(TENANT),
        lambda: db.list_mcp_freshness_candidates(TENANT),
    ],
    ids=["duplicate-candidates", "duplicate-hints", "freshness-candidates"],
)
def test_the_whole_catalog_mcp_reports_scan_a_capped_number_of_endpoints(accessor):
    sql, _ = _capture(accessor)
    assert sql.endswith(f"e.id ASC LIMIT {MCP_REPORT_SCAN_CAP}")


def test_the_evolution_series_can_be_kept_to_the_most_recent_snapshots():
    whole_sql, whole_params = _capture(lambda: db.get_mcp_evolution_series(OTHER))
    assert "recent.version_seq DESC" not in whole_sql and whole_params == (OTHER,)
    sql, params = _capture(lambda: db.get_mcp_evolution_series(OTHER, limit=50))
    assert "ORDER BY recent.version_seq DESC LIMIT %s" in sql
    assert sql.endswith("ORDER BY v.version_seq ASC") and params == (OTHER, OTHER, 50)
    changes_sql, changes_params = _capture(
        lambda: db.get_mcp_version_changes_for_endpoint(OTHER, limit_versions=50)
    )
    assert "ORDER BY recent.version_seq DESC LIMIT %s" in changes_sql
    assert changes_params == (OTHER, OTHER, 50)
    assert _capture(lambda: db.get_mcp_version_changes_for_endpoint(OTHER))[1] == (OTHER,)


def test_mcp_version_evidence_can_be_kept_to_the_newest_runs():
    assert "LIMIT" not in _capture(lambda: db.list_lint_evidence_runs_for_mcp_version(OTHER))[0]
    sql, params = _capture(lambda: db.list_lint_evidence_runs_for_mcp_version(OTHER, limit=200))
    assert sql.endswith("ORDER BY r.created_at DESC, r.id LIMIT %s") and params == (OTHER, 200)


# --- provider verification reports --------------------------------------------------------------


def test_a_report_list_never_reads_more_than_two_hundred_rows_or_a_report_body():
    sql, params = _capture(lambda: db.list_provider_verification_reports(TENANT, limit=10_000))
    assert params == (TENANT, 200)
    select_list = sql.split("FROM apiome.provider_verification_report")[0]
    assert " report," not in select_list and "fixture_count, created_at" in select_list
    # The single-report read still carries the body.
    assert " report," in " ".join(db._PROVIDER_VERIFICATION_REPORT_COLUMNS.split())


# --- lint workspace evidence --------------------------------------------------------------------


def test_the_workspace_evidence_read_is_unchanged_by_default():
    sql, params = _capture(lambda: db.list_latest_lint_evidence_runs_for_tenant(TENANT))
    assert "SELECT * FROM (" in sql and "jsonb_array_elements" not in sql
    assert params == (TENANT, None, None, TENANT, 2, 2)


@pytest.mark.parametrize(
    "mode,newest_keeps_bodies,slim_keys",
    [
        ("current", True, "'source_fingerprint', f -> 'source_fingerprint', 'id', f -> 'id')"),
        ("summary", False, "'severity', f -> 'severity', 'category', f -> 'category')"),
    ],
)
def test_the_workspace_evidence_read_cuts_findings_down_in_sql(mode, newest_keeps_bodies, slim_keys):
    sql, params = _capture(
        lambda: db.list_latest_lint_evidence_runs_for_tenant(TENANT, findings=mode, row_limit=500)
    )
    assert "SELECT * FROM (" not in sql and slim_keys in sql
    assert ("CASE WHEN c.rn = 1 THEN c.findings ELSE" in sql) is newest_keeps_bodies
    assert "CASE WHEN m.rn = 1 THEN" in sql
    assert sql.endswith("ORDER BY created_at DESC, id LIMIT %s")
    assert params == (TENANT, None, None, TENANT, 2, 2, 500)


def test_trend_evidence_carries_fingerprints_only():
    sql, params = _capture(
        lambda: db.list_latest_lint_evidence_runs_for_tenant(
            TENANT, project_id=OTHER, runs_per_scanner=64, findings="fingerprints", row_limit=9
        )
    )
    assert "c.rn = 1" not in sql and "'severity'" not in sql
    assert "'source_fingerprint', f -> 'source_fingerprint'" in sql
    assert params == (TENANT, OTHER, OTHER, 64, 9)


def test_an_unknown_findings_mode_is_refused():
    with pytest.raises(ValueError):
        db.list_latest_lint_evidence_runs_for_tenant(TENANT, findings="everything")


# --- quality-rank rollup ------------------------------------------------------------------------


def test_quality_rank_observations_are_bucketed_in_three_statements():
    with patch.object(db, "execute_query", return_value=[]) as query:
        parts = db.aggregate_quality_rank_observations(
            TENANT, since=STAMP, project_id=OTHER, scope="import", stage="committed"
        )
    assert parts == {"buckets": [], "drift": [], "attribution": []}
    buckets, drift, attribution = (" ".join(call.args[0].split()) for call in query.call_args_list)
    for call in query.call_args_list:
        assert call.args[0].count("%s") == len(call.args[1])
    filters = (TENANT, STAMP, OTHER, "import", "committed")
    assert query.call_args_list[0].args[1] == (*filters, 20000)
    assert query.call_args_list[1].args[1] == filters
    assert "GROUP BY o.scope, o.format_key, (o.occurred_at AT TIME ZONE 'UTC')::date" in buckets
    assert "COUNT(*)::int AS observations" in buckets and buckets.endswith("LIMIT %s")
    # No per-observation column leaves the database.
    assert "attribution" not in buckets and "o.id," not in buckets
    assert "o.score IS NOT NULL GROUP BY o.scope, o.format_key" in drift
    assert "jsonb_each(o.attribution)" in attribution and "side.key IN ('adapter', 'spec')" in attribution


def test_a_malformed_tenant_aggregates_nothing():
    with patch.object(db, "execute_query") as query:
        assert db.aggregate_quality_rank_observations("nope", since=STAMP) == {
            "buckets": [],
            "drift": [],
            "attribution": [],
        }
    query.assert_not_called()
