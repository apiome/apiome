"""The facts stored on an MCP endpoint version, derived in Python at write time (DBP-1.17, #7200).

These pin the definitions; ``tests/test_mcp_version_facts_db.py`` checks them against the SQL
recomputation on a real database.
"""

from __future__ import annotations

import pytest

from app.mcp_version_facts import VERSION_FACT_COLUMNS, derive_version_facts


def _tool(annotations=None, input_schema=None, **extra):
    return {"item_type": "tool", "annotations": annotations, "input_schema": input_schema, **extra}


def _schema(*properties):
    return {"type": "object", "properties": {name: {"type": "string"} for name in properties}}


def test_an_empty_snapshot_has_zero_counts_no_flags_and_no_complexity():
    assert derive_version_facts([], []) == {
        "tool_count": 0,
        "resource_count": 0,
        "resource_template_count": 0,
        "prompt_count": 0,
        "has_destructive": False,
        "read_only_only": False,
        "max_tool_props": None,
        "change_count": 0,
    }


def test_every_fact_column_has_a_value_in_insert_order():
    facts = derive_version_facts([_tool()], [])
    assert tuple(facts) == VERSION_FACT_COLUMNS


def test_items_are_counted_by_kind_and_unknown_kinds_are_ignored():
    rows = (
        [_tool()] * 3
        + [{"item_type": "resource"}] * 2
        + [{"item_type": "resource_template"}]
        + [{"item_type": "prompt"}] * 4
        + [{"item_type": "elicitation"}, {"item_type": None}, {}]
    )
    facts = derive_version_facts(rows, [])
    assert (facts["tool_count"], facts["resource_count"], facts["resource_template_count"], facts["prompt_count"]) == (
        3,
        2,
        1,
        4,
    )


def test_change_count_is_the_number_of_change_rows():
    changes = [{"change_type": "added"}, {"change_type": "removed"}, {"change_type": "modified"}]
    assert derive_version_facts([], changes)["change_count"] == 3


@pytest.mark.parametrize(
    "annotations,expected",
    [
        ({"destructiveHint": True}, True),
        ({"destructiveHint": False}, False),
        ({"destructiveHint": "true"}, False),  # a string is not the JSON boolean
        ({"destructiveHint": 1}, False),
        ({"readOnlyHint": True}, False),
        ({}, False),
        (None, False),
        (["destructiveHint"], False),  # not an object
        ("destructiveHint", False),
    ],
)
def test_has_destructive_needs_the_json_boolean_true(annotations, expected):
    assert derive_version_facts([_tool(annotations)], [])["has_destructive"] is expected


def test_one_destructive_tool_is_enough():
    rows = [_tool({"readOnlyHint": True}), _tool({"destructiveHint": True}), _tool()]
    assert derive_version_facts(rows, [])["has_destructive"] is True


def test_a_destructive_hint_on_a_resource_does_not_count():
    rows = [{"item_type": "resource", "annotations": {"destructiveHint": True}}]
    assert derive_version_facts(rows, [])["has_destructive"] is False


def test_read_only_only_needs_a_tool_and_every_tool_asserting_it():
    read_only = _tool({"readOnlyHint": True})
    assert derive_version_facts([read_only, read_only], [])["read_only_only"] is True
    # No tool at all: nothing declares the surface read-only.
    assert derive_version_facts([{"item_type": "resource"}], [])["read_only_only"] is False
    # One tool that does not assert it breaks the claim — unannotated, false, or a non-boolean.
    for other in (_tool(), _tool({}), _tool({"readOnlyHint": False}), _tool({"readOnlyHint": "true"})):
        assert derive_version_facts([read_only, other], [])["read_only_only"] is False
    # Non-tool items never break it.
    assert derive_version_facts([read_only, {"item_type": "prompt"}], [])["read_only_only"] is True


@pytest.mark.parametrize(
    "input_schema,expected",
    [
        (_schema("a", "b", "c"), 3),
        (_schema(), 0),
        ({"type": "object"}, 0),  # no properties
        ({"properties": ["a", "b"]}, 0),  # properties is not an object
        ({"properties": "a"}, 0),
        (None, 0),
        (["not", "an", "object"], 0),
        ("{}", 0),
    ],
)
def test_a_tools_property_count_is_its_top_level_properties(input_schema, expected):
    assert derive_version_facts([_tool(input_schema=input_schema)], [])["max_tool_props"] == expected


def test_max_tool_props_is_the_widest_tool_and_null_without_tools():
    rows = [_tool(input_schema=_schema("a")), _tool(input_schema=_schema(*"abcdefg")), _tool()]
    assert derive_version_facts(rows, [])["max_tool_props"] == 7
    assert derive_version_facts([{"item_type": "prompt"}], [])["max_tool_props"] is None


def test_nested_properties_are_not_counted():
    nested = {"properties": {"filter": {"type": "object", "properties": {"a": {}, "b": {}, "c": {}}}}}
    assert derive_version_facts([_tool(input_schema=nested)], [])["max_tool_props"] == 1


def test_a_resources_schema_does_not_count_towards_tool_complexity():
    rows = [{"item_type": "resource", "input_schema": _schema(*"abcdef")}, _tool(input_schema=_schema("a"))]
    assert derive_version_facts(rows, [])["max_tool_props"] == 1


def test_the_rows_may_be_any_iterable_and_are_read_once():
    facts = derive_version_facts((row for row in [_tool({"destructiveHint": True}, _schema("a", "b"))]), [])
    assert facts["tool_count"] == 1 and facts["has_destructive"] is True and facts["max_tool_props"] == 2
