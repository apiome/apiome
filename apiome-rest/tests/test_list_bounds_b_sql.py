"""The authoring list accessors read one keyset window (DBP-1.13, #7196).

For each accessor converted in this slice: without ``limit`` the statement is the whole list in
its declared order (internal callers are unchanged); with ``limit`` and ``cursor`` it is a
continuation predicate on the sort key, the same ``ORDER BY`` and a ``LIMIT`` — never an
``OFFSET``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, List, Tuple
from unittest.mock import MagicMock, patch

import pytest

from app import authoring_list_orders as orders
from app import workspace_custom_action_store
from app.database import db

TENANT = "11111111-1111-4111-8111-111111111111"
GUIDE = "22222222-2222-4222-8222-222222222222"
ROW = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
STAMP = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)

# (name, ordering, call(limit=, cursor=), the cursor values, the leading parameters)
CASES: List[Tuple[str, Any, Callable[..., Any], List[Any], Tuple[Any, ...]]] = [
    (
        "unresolved-primitives",
        orders.UNRESOLVED_PRIMITIVES_ORDER,
        lambda **kw: db.get_primitives_with_unresolved_refs(TENANT, **kw),
        ["acme/v1", "Money", ROW],
        (TENANT,),
    ),
    (
        "type-namespaces",
        orders.TYPE_NAMESPACES_ORDER,
        lambda **kw: db.list_type_namespaces(TENANT, root_status="draft", **kw),
        [False, "acme/v1/types", ROW],
        (TENANT, TENANT, "draft"),
    ),
    (
        "classes-with-parts",
        orders.CLASSES_WITH_PARTS_ORDER,
        lambda **kw: db.get_classes_with_properties_and_tags_for_version("v1", **kw),
        ["Order", ROW],
        ("v1",),
    ),
    (
        "project-tags",
        orders.PROJECT_TAGS_ORDER,
        lambda **kw: db.get_tags_for_project("p1", **kw),
        ["billing", ROW],
        ("p1",),
    ),
    (
        "project-conversions",
        orders.PROJECT_CONVERSIONS_ORDER,
        lambda **kw: db.get_conversions_for_project(TENANT, "p1", **kw),
        [STAMP, ROW],
        (TENANT, "p1"),
    ),
    (
        "lint-decisions",
        orders.LINT_DECISIONS_ORDER,
        lambda **kw: db.list_lint_finding_decisions(TENANT, project_id="p1", **kw),
        [STAMP, ROW],
        (TENANT, "p1"),
    ),
    (
        "lint-decision-events",
        orders.LINT_DECISION_EVENTS_ORDER,
        lambda **kw: db.list_lint_finding_decision_events(ROW, TENANT, **kw),
        [STAMP, OTHER],
        (ROW, TENANT),
    ),
    (
        "style-guides",
        orders.STYLE_GUIDES_ORDER,
        lambda **kw: db.list_style_guides(TENANT, **kw),
        [False, "House style", ROW],
        (TENANT,),
    ),
    (
        "style-guide-policy-versions",
        orders.STYLE_GUIDE_POLICY_VERSIONS_ORDER,
        lambda **kw: db.list_style_guide_policy_versions(GUIDE, TENANT, **kw),
        [7, ROW],
        (GUIDE, TENANT),
    ),
    (
        "version-branches",
        orders.VERSION_BRANCHES_ORDER,
        lambda **kw: db.list_version_branches_detailed_for_project("p1", TENANT, **kw),
        ["main", ROW],
        ("p1", TENANT),
    ),
    (
        "project-properties",
        orders.PROJECT_PROPERTIES_ORDER,
        lambda **kw: db.get_properties_for_project("p1", **kw),
        ["amount", ROW],
        ("p1",),
    ),
    (
        "project-properties-with-usage",
        orders.PROJECT_PROPERTIES_ORDER,
        lambda **kw: db.get_properties_for_project("p1", with_usage=True, **kw),
        ["amount", ROW],
        ("p1",),
    ),
    (
        "version-tags",
        orders.VERSION_TAGS_ORDER,
        lambda **kw: db.list_version_tags_for_project("p1", TENANT, **kw),
        ["v1.0.0", ROW],
        ("p1", TENANT),
    ),
    (
        "components",
        orders.COMPONENTS_ORDER,
        lambda **kw: db.list_operational_components(TENANT, "parameter", **kw),
        ["parameter", "PageParam", ROW],
        (TENANT, "parameter"),
    ),
    (
        "component-usage-pins",
        orders.COMPONENT_USAGE_PINS_ORDER,
        lambda **kw: db.get_component_usage_pins(TENANT, [ROW], **kw),
        ["PageParam", OTHER, GUIDE, ROW],
        (TENANT, [ROW]),
    ),
    (
        "component-deprecations",
        orders.COMPONENT_DEPRECATIONS_ORDER,
        lambda **kw: db.list_component_deprecations(TENANT, ROW, **kw),
        [STAMP, "PageParam", "1.0.0", OTHER],
        (TENANT, ROW),
    ),
]
_IDS = [case[0] for case in CASES]


def _flat(sql: str) -> str:
    return " ".join(sql.split())


@pytest.mark.parametrize(("name", "order", "call", "cursor", "leading"), CASES, ids=_IDS)
def test_without_a_limit_the_accessor_reads_the_whole_list_in_order(name, order, call, cursor, leading):
    with patch.object(db, "execute_query", return_value=[]) as query:
        call()
    sql, params = query.call_args.args
    assert f"ORDER BY {order.order_by}" in _flat(sql)
    assert "LIMIT" not in sql and "OFFSET" not in sql
    assert tuple(params) == leading


@pytest.mark.parametrize(("name", "order", "call", "cursor", "leading"), CASES, ids=_IDS)
def test_a_page_is_a_keyset_continuation_with_a_limit(name, order, call, cursor, leading):
    after_sql, after_params, _, _ = order.window(11, cursor)
    with patch.object(db, "execute_query", return_value=[]) as query:
        call(limit=11, cursor=cursor)
    sql, params = query.call_args.args
    flat = _flat(sql)
    assert _flat(after_sql) in flat
    assert flat.endswith(f"ORDER BY {order.order_by} LIMIT %s")
    assert "OFFSET" not in sql
    assert tuple(params) == (*leading, *after_params, 11)


def test_style_guide_revisions_page_on_their_number_and_keep_a_bounded_read():
    cursor = [4, ROW]
    order = orders.STYLE_GUIDE_REVISIONS_ORDER
    after_sql, after_params, _, _ = order.window(1, cursor)
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_style_guide_revisions(GUIDE, TENANT, limit=101, cursor=cursor)
        db.list_style_guide_revisions(GUIDE, TENANT, limit=10_000)
    paged, clamped = query.call_args_list
    assert _flat(after_sql) in _flat(paged.args[0])
    assert _flat(paged.args[0]).endswith("ORDER BY revision_number DESC, id DESC LIMIT %s")
    assert paged.args[1] == (GUIDE, TENANT, *after_params, 101)
    # A 500-row page plus the row that tells the route another page exists.
    assert clamped.args[1] == (GUIDE, TENANT, 501)


def test_the_style_guide_list_selects_the_flag_its_cursor_carries():
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_style_guides(TENANT)
    assert "(g.source = 'builtin') AS is_builtin" in query.call_args.args[0]


def test_the_latest_policy_version_reads_one_row():
    with patch.object(db, "execute_query", return_value=[]) as query:
        assert db.get_latest_style_guide_policy_version(GUIDE, TENANT) is None
    sql, params = query.call_args.args
    assert _flat(sql).endswith("ORDER BY version_number DESC, id DESC LIMIT %s")
    assert params == (GUIDE, TENANT, 1)


def test_lint_evidence_and_the_sunset_timeline_take_a_hard_row_cap():
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_lint_evidence_runs_for_version("v1", TENANT)
        db.list_lint_evidence_runs_for_version("v1", TENANT, limit=200)
        db.list_sunset_timeline_entries(TENANT, "p1")
        db.list_sunset_timeline_entries(TENANT, "p1", limit=10_000)
    whole, capped, timeline, capped_timeline = query.call_args_list
    assert "LIMIT" not in whole.args[0] and whole.args[1] == ("v1", TENANT)
    assert _flat(capped.args[0]).endswith("ORDER BY r.created_at DESC, r.id LIMIT %s")
    assert capped.args[1] == ("v1", TENANT, 200)
    assert "LIMIT" not in timeline.args[0] and timeline.args[1] == (TENANT, "p1")
    assert _flat(capped_timeline.args[0]).endswith("ORDER BY p.name ASC, v.version_id ASC, v.id ASC LIMIT %s")
    assert capped_timeline.args[1] == (TENANT, "p1", 10_000)


def test_custom_actions_page_on_the_lowercased_name_they_sort_by():
    order = orders.CUSTOM_ACTIONS_ORDER
    cursor = ["open runbook", ROW]
    after_sql, after_params, _, _ = order.window(3, cursor)
    database = MagicMock()
    statement = database.connect.return_value.cursor.return_value.__enter__.return_value
    statement.fetchall.return_value = []

    workspace_custom_action_store.list_actions(database, tenant_id=TENANT)
    workspace_custom_action_store.list_actions(database, tenant_id=TENANT, limit=3, cursor=cursor)

    whole, paged = statement.execute.call_args_list
    assert "lower(name) AS name_sort" in whole.args[0]
    assert _flat(whole.args[0]).endswith("ORDER BY lower(name) ASC, id ASC")
    assert tuple(whole.args[1]) == (TENANT,)
    assert _flat(after_sql) in _flat(paged.args[0])
    assert _flat(paged.args[0]).endswith("ORDER BY lower(name) ASC, id ASC LIMIT %s")
    assert tuple(paged.args[1]) == (TENANT, *after_params, 3)
