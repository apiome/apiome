"""DBP-1.22 (#7205): the apiome-mcp entries of ``apiome-db/plan-check/hot-queries.json`` are current.

The plan check explains the statements in that file on the scale database; it only protects the
catalog tools while the file holds the statements they really run.
"""

from __future__ import annotations

import json

from plan_check_queries import HOT_QUERIES, REGENERATE, mcp_plan_check_entries, owned, to_dollar


def test_hot_queries_hold_the_statements_the_tools_build() -> None:
    stored = owned(json.loads(HOT_QUERIES.read_text())["queries"])
    expected = mcp_plan_check_entries()
    assert [q["name"] for q in stored] == [q["name"] for q in expected], f"regenerate: {REGENERATE}"
    for have, want in zip(stored, expected, strict=True):
        assert have == want, f"{want['name']} is stale in hot-queries.json; regenerate: {REGENERATE}"


def test_no_listing_entry_is_marked_known_slow() -> None:
    """A ``known`` entry is reported, not failed: these statements must hold their budgets."""
    assert not [q["name"] for q in mcp_plan_check_entries() if "known" in q]


def test_to_dollar_numbers_positional_placeholders_in_order() -> None:
    sql, params = to_dollar("SELECT 1\n  WHERE a = %s AND b %% 2 = %s", [10, 20])
    assert sql == "SELECT 1 WHERE a = $1 AND b % 2 = $2"
    assert params == [10, 20]


def test_to_dollar_gives_a_repeated_named_placeholder_one_number() -> None:
    sql, params = to_dollar("SELECT f(%(q)s), g(%(q)s) LIMIT %(lim)s", {"q": "x", "lim": 5, "unused": 1})
    assert sql == "SELECT f($1), g($1) LIMIT $2"
    assert params == ["x", 5]
