"""Fix capability of the lint rule SPI — GVM-3.1 (#5869).

Covers the engine half of the issue: RFC 6902 operations, the pointer helpers, the scope bound
(an operation outside the finding's subtree is refused), the off-by-default gate, the options,
the fix declaration on :class:`~app.lint_engine.LintRule` and the patch applier.
"""

from __future__ import annotations

import copy

import pytest

from app.lint_engine import LintRule
from app.lint_fix import (
    DEFAULT_OPERATION_ID_TEMPLATE,
    FIX_CLASSES,
    FIX_OWNER_AGENT,
    FIX_OWNER_ENGINE,
    FIX_OWNER_HUMAN,
    FIX_SCOPE_DOCUMENT,
    FixError,
    FixOptions,
    FixScopeError,
    PatchOp,
    apply_fix_ops,
    fix_owner_for,
    path_from_pointer,
    plan_rule_fix,
    pointer_for_path,
    pointer_within,
    split_pointer,
    validate_fix_ops,
)
from app.schema_lint import LintFinding

DOCUMENT = {
    "info": {"title": "T"},
    "paths": {"/pets.json": {"get": {"tags": ["a", "b"]}}, "/pets": {"json": {"get": {}}}},
    "components": {"schemas": {"api.v1.Pet": {"type": "object"}, "Pet": {"type": "object"}}},
}


def _finding(path: str, rule: str = "test.rule") -> LintFinding:
    return LintFinding(path=path, category="structure", rule=rule, severity="warning", message="m")


def _rule(fix, **overrides) -> LintRule:
    """A fixable test rule whose check is irrelevant to these tests."""
    fields = dict(
        rule_id="test.rule",
        category="structure",
        severity="warning",
        description="A test rule.",
        check=lambda api: [],
        fix=fix,
        fix_class="structural",
        fix_summary="Does a test edit.",
    )
    fields.update(overrides)
    return LintRule(**fields)


# ---------------------------------------------------------------------------
# PatchOp
# ---------------------------------------------------------------------------


def test_patch_ops_render_as_rfc_6902_objects():
    assert PatchOp.add("/a", [1]).as_dict() == {"op": "add", "path": "/a", "value": [1]}
    assert PatchOp.remove("/a").as_dict() == {"op": "remove", "path": "/a"}
    assert PatchOp.replace("/a", None).as_dict() == {"op": "replace", "path": "/a", "value": None}
    assert PatchOp.move("/a", "/b").as_dict() == {"op": "move", "path": "/b", "from": "/a"}


def test_patch_op_dict_does_not_alias_the_value():
    value = {"k": [1]}
    rendered = PatchOp.add("/a", value).as_dict()
    rendered["value"]["k"].append(2)
    assert value == {"k": [1]}


# ---------------------------------------------------------------------------
# Pointers
# ---------------------------------------------------------------------------


def test_split_pointer_unescapes_tokens():
    assert split_pointer("") == []
    assert split_pointer("/paths/~1pets~1{id}/get") == ["paths", "/pets/{id}", "get"]
    assert split_pointer("/a~0b") == ["a~b"]


@pytest.mark.parametrize("bad", ["paths", "#/paths", 7, None])
def test_split_pointer_rejects_what_is_not_a_pointer(bad):
    with pytest.raises(FixError):
        split_pointer(bad)


def test_pointer_within_is_the_subtree_test():
    assert pointer_within("/a/b", "/a/b")
    assert pointer_within("/a/b/c", "/a/b")
    assert not pointer_within("/a/bc", "/a/b")  # a sibling that merely shares a prefix
    assert not pointer_within("/a", "/a/b")
    assert pointer_within("/anything", "")


def test_path_from_pointer_is_the_dotted_finding_path():
    assert path_from_pointer("/paths/~1pets/get") == "paths./pets.get"
    assert path_from_pointer("/tags/1") == "tags.1"


def test_pointer_for_path_resolves_against_the_document():
    assert pointer_for_path(DOCUMENT, "info") == "/info"
    assert pointer_for_path(DOCUMENT, "paths./pets.json.get.tags.1") == "/paths/~1pets.json/get/tags/1"
    assert pointer_for_path(DOCUMENT, "components.schemas.Pet") == "/components/schemas/Pet"
    assert pointer_for_path(DOCUMENT, "") == ""


def test_pointer_for_path_handles_keys_that_contain_dots():
    assert pointer_for_path(DOCUMENT, "components.schemas.api.v1.Pet") == "/components/schemas/api.v1.Pet"
    # The longest key wins, and the shorter split is still reachable when the longer one fails.
    assert pointer_for_path(DOCUMENT, "paths./pets.json.get") == "/paths/~1pets.json/get"


def test_pointer_for_path_round_trips_path_from_pointer():
    for pointer in ("/paths/~1pets.json/get/tags/0", "/components/schemas/api.v1.Pet/type"):
        assert pointer_for_path(DOCUMENT, path_from_pointer(pointer)) == pointer


@pytest.mark.parametrize("path", ["components.schemas.Missing", "paths./pets.json.get.tags.9", "info.title.x"])
def test_pointer_for_path_rejects_a_path_that_addresses_nothing(path):
    with pytest.raises(FixError, match="does not address"):
        pointer_for_path(DOCUMENT, path)


# ---------------------------------------------------------------------------
# The scope bound — the acceptance criterion
# ---------------------------------------------------------------------------


def test_an_op_outside_the_finding_subtree_is_rejected_by_the_engine():
    """Acceptance: an op outside the finding subtree is rejected at engine level."""
    rule = _rule(lambda document, finding, options: [PatchOp.remove("/components/schemas/Pet")])
    with pytest.raises(FixScopeError, match="outside the finding's subtree"):
        rule.plan_fix(DOCUMENT, _finding("components.schemas.api.v1.Pet"))


def test_a_sibling_sharing_a_name_prefix_is_outside_the_subtree():
    rule = _rule(lambda document, finding, options: [PatchOp.replace("/components/schemas/Pets", {})])
    with pytest.raises(FixScopeError):
        rule.plan_fix(DOCUMENT, _finding("components.schemas.Pet"))


def test_the_source_of_a_move_is_bounded_too():
    rule = _rule(
        lambda document, finding, options: [PatchOp.move("/info/title", "/components/schemas/Pet/title")]
    )
    with pytest.raises(FixScopeError, match="/info/title"):
        rule.plan_fix(DOCUMENT, _finding("components.schemas.Pet"))


def test_ops_on_the_finding_pointer_and_below_are_accepted():
    ops = [PatchOp.remove("/components/schemas/Pet/type"), PatchOp.replace("/components/schemas/Pet", {})]
    rule = _rule(lambda document, finding, options: ops)
    assert rule.plan_fix(DOCUMENT, _finding("components.schemas.Pet")) == tuple(ops)


def test_a_rule_that_declares_document_scope_may_reach_anywhere():
    ops = [PatchOp.replace("/info/title", "U"), PatchOp.move("/components/schemas/Pet", "/components/schemas/P")]
    rule = _rule(lambda document, finding, options: ops, fix_scope=FIX_SCOPE_DOCUMENT)
    assert rule.plan_fix(DOCUMENT, _finding("components.schemas.Pet")) == tuple(ops)


def test_a_finding_at_the_root_bounds_nothing():
    validate_fix_ops([PatchOp.remove("/info")], "")


@pytest.mark.parametrize(
    "op",
    [
        PatchOp("merge", "/info"),
        PatchOp("remove", "info"),
        PatchOp("move", "/info/x"),  # no source
        {"op": "remove", "path": "/info"},
    ],
)
def test_malformed_ops_are_rejected(op):
    with pytest.raises(FixError):
        validate_fix_ops([op], "")


def test_planning_does_not_mutate_the_document():
    before = copy.deepcopy(DOCUMENT)
    rule = _rule(lambda document, finding, options: [PatchOp.remove("/info/title")])
    rule.plan_fix(DOCUMENT, _finding("info"))
    assert DOCUMENT == before


def test_a_rule_without_a_fix_plans_nothing():
    rule = LintRule(rule_id="test.rule", category="structure", severity="info", description="d", check=lambda api: [])
    assert rule.fixable is False
    assert rule.plan_fix(DOCUMENT, _finding("info")) == ()


def test_a_finding_of_another_rule_is_refused():
    rule = _rule(lambda document, finding, options: [])
    with pytest.raises(FixError, match="given to rule"):
        plan_rule_fix(rule, DOCUMENT, _finding("info", rule="other.rule"))


def test_a_finding_whose_path_is_gone_is_refused():
    rule = _rule(lambda document, finding, options: [])
    with pytest.raises(FixError, match="does not address"):
        rule.plan_fix(DOCUMENT, _finding("components.schemas.Gone"))


# ---------------------------------------------------------------------------
# Off-by-default fixes and options
# ---------------------------------------------------------------------------


def test_an_off_by_default_fix_plans_nothing_until_opted_in():
    ops = [PatchOp.remove("/info/title")]
    rule = _rule(lambda document, finding, options: ops, fix_default=False)
    assert rule.plan_fix(DOCUMENT, _finding("info")) == ()
    assert rule.plan_fix(DOCUMENT, _finding("info"), FixOptions(opt_in=frozenset({"other.rule"}))) == ()
    assert rule.plan_fix(DOCUMENT, _finding("info"), FixOptions(opt_in=frozenset({"test.rule"}))) == tuple(ops)


def test_the_fix_receives_the_callers_options():
    seen = []
    rule = _rule(lambda document, finding, options: seen.append(options) or [])
    rule.plan_fix(DOCUMENT, _finding("info"))
    rule.plan_fix(DOCUMENT, _finding("info"), FixOptions(operation_id_template="{Method}_{path}"))
    assert seen[0].operation_id_template == DEFAULT_OPERATION_ID_TEMPLATE
    assert seen[1].operation_id_template == "{Method}_{path}"


@pytest.mark.parametrize(
    "template", ["", "   ", "{method}", "{verb}{Path}", "{method}{Path", "{method}}{Path}", 7]
)
def test_invalid_operation_id_templates_are_rejected(template):
    with pytest.raises(FixError):
        FixOptions(operation_id_template=template).validate()


def test_invalid_options_stop_a_plan():
    rule = _rule(lambda document, finding, options: [])
    with pytest.raises(FixError, match="placeholder"):
        rule.plan_fix(DOCUMENT, _finding("info"), FixOptions(operation_id_template="{nope}"))


# ---------------------------------------------------------------------------
# Declaring a fix on a rule
# ---------------------------------------------------------------------------


def test_fix_classes_are_the_four_the_issue_names():
    assert FIX_CLASSES == ("structural", "removal", "fill-in", "rename")


@pytest.mark.parametrize(
    "overrides",
    [
        {"fix_class": None},
        {"fix_class": "semantic"},
        {"fix_summary": "  "},
        {"fix_scope": "everything"},
        {"category": "documentation"},  # inventing meaning is the agent's job
        {"category": "security"},
    ],
)
def test_a_half_declared_fix_fails_when_the_rule_is_built(overrides):
    with pytest.raises(ValueError):
        _rule(lambda document, finding, options: [], **overrides)


@pytest.mark.parametrize("overrides", [{"fix_class": "removal"}, {"fix_summary": "Does something."}])
def test_fix_metadata_without_a_fix_is_rejected(overrides):
    with pytest.raises(ValueError, match="no fix"):
        LintRule(
            rule_id="test.rule",
            category="structure",
            severity="info",
            description="d",
            check=lambda api: [],
            **overrides,
        )


def test_fix_owner_partitions_rules():
    assert fix_owner_for("structure", True) == FIX_OWNER_ENGINE
    assert fix_owner_for("documentation", False) == FIX_OWNER_AGENT
    assert fix_owner_for("security", False) == FIX_OWNER_AGENT
    assert fix_owner_for("validation", False, pack="examples") == FIX_OWNER_AGENT
    assert fix_owner_for("naming", False) == FIX_OWNER_HUMAN


# ---------------------------------------------------------------------------
# Applying operations
# ---------------------------------------------------------------------------


def test_apply_runs_each_operation_in_order_on_a_copy():
    document = {"a": {"b": 1, "c": [1, 2, 3]}, "d": "x"}
    out = apply_fix_ops(
        document,
        [
            PatchOp.replace("/a/b", 2),
            PatchOp.remove("/a/c/0"),
            PatchOp.add("/a/c/-", 4),
            PatchOp.add("/a/c/0", 0),
            PatchOp.add("/e", {"f": True}),
            PatchOp.move("/d", "/a/d"),
            PatchOp("copy", "/g", from_pointer="/a/b"),
            PatchOp("test", "/g", value=2),
        ],
    )
    assert out == {"a": {"b": 2, "c": [0, 2, 3, 4], "d": "x"}, "e": {"f": True}, "g": 2}
    assert document == {"a": {"b": 1, "c": [1, 2, 3]}, "d": "x"}


def test_replace_keeps_the_members_position():
    out = apply_fix_ops({"a": 1, "b": 2, "c": 3}, [PatchOp.replace("/b", 9)])
    assert list(out.items()) == [("a", 1), ("b", 9), ("c", 3)]


def test_applied_values_do_not_alias_the_operation():
    value = {"k": []}
    out = apply_fix_ops({}, [PatchOp.add("/a", value)])
    out["a"]["k"].append(1)
    assert value == {"k": []}


@pytest.mark.parametrize(
    "op",
    [
        PatchOp.remove("/missing"),
        PatchOp.replace("/missing", 1),
        PatchOp.remove("/a/c/7"),
        PatchOp.add("/a/c/9", 1),
        PatchOp.add("/a/b/x", 1),  # parent is a scalar
        PatchOp.add("/nope/x", 1),
        PatchOp.remove(""),
        PatchOp.move("/a", "/a/b/inside"),
        PatchOp("test", "/a/b", value=2),
        PatchOp("merge", "/a"),
    ],
)
def test_an_operation_that_does_not_apply_raises(op):
    with pytest.raises(FixError, match="operation 0"):
        apply_fix_ops({"a": {"b": 1, "c": [1]}}, [op])
