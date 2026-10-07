"""AGX-2.1 argument validation (#4533): problems are listed per argument and never echo whole values."""

from __future__ import annotations

from typing import Any

from apiome_mcp.agent_argument_validation import MAX_ISSUES, MAX_PROBLEM_CHARS, validate_arguments

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name"],
}


def test_valid_arguments_have_no_issues() -> None:
    assert validate_arguments(SCHEMA, {"name": "Rex", "limit": 5, "tags": ["dog"]}) == []


def test_none_counts_as_no_arguments() -> None:
    assert [issue.argument for issue in validate_arguments(SCHEMA, None)] == ["(arguments)"]


def test_each_problem_points_at_its_argument() -> None:
    issues = validate_arguments(SCHEMA, {"name": "", "limit": 500, "tags": ["ok", 3]})
    assert {issue.argument for issue in issues} == {"name", "limit", "tags[1]"}


def test_a_missing_required_argument_is_reported_on_the_object() -> None:
    issues = validate_arguments(SCHEMA, {"limit": 1})
    assert len(issues) == 1
    assert issues[0].argument == "(arguments)"
    assert "'name' is a required property" in issues[0].problem


def test_unknown_arguments_are_refused_with_the_expected_names() -> None:
    issues = validate_arguments(SCHEMA, {"name": "Rex", "colour": "red"})
    assert [issue.argument for issue in issues] == ["colour"]
    assert "limit, name, tags" in issues[0].problem


def test_unknown_arguments_are_allowed_when_the_schema_allows_extras() -> None:
    schema = {**SCHEMA, "additionalProperties": True}
    assert validate_arguments(schema, {"name": "Rex", "colour": "red"}) == []


def test_a_non_object_is_refused() -> None:
    issues = validate_arguments(SCHEMA, ["Rex"])
    assert [issue.argument for issue in issues] == ["(arguments)"]


def test_problems_never_echo_a_long_value() -> None:
    secret_like = "word " * 400
    issues = validate_arguments({"type": "object", "properties": {"n": {"type": "integer"}}}, {"n": secret_like})
    assert len(issues[0].problem) <= MAX_PROBLEM_CHARS


def test_many_problems_are_capped_with_a_summary() -> None:
    schema = {"type": "object", "properties": {f"p{i}": {"type": "integer"} for i in range(30)}}
    issues = validate_arguments(schema, {f"p{i}": "x" for i in range(30)})
    assert len(issues) == MAX_ISSUES + 1
    assert issues[-1].problem == "10 more problem(s) not shown"
