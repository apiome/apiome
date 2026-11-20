"""Tests for lint-fix plans and the Overlay renderer — GVM-3.2 (#5870).

The corpus is every GVM-3.1 one-defect fixture (``tests/fixtures/lint_fix``) plus
:data:`MULTI_DEFECT`, a document with several defects at once (array removals, a conflict, a
breaking rename). The acceptance criteria are tested over the whole corpus:

* a plan is byte-identical across two runs, in every format;
* applying the ready set then planning again leaves nothing ready (idempotence);
* the overlay rendering, applied with ``apply_overlays``, produces the same document as the patch;
* no breaking fix is ever ready.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.lint_fix import FixError, PatchOp, apply_fix_ops
from app.lint_fix_plan import (
    EXCLUDED_GUIDE_DISABLED,
    EXCLUDED_NOT_SELECTED,
    EXCLUDED_OPT_IN_REQUIRED,
    EXCLUDED_RENAMES_NOT_INCLUDED,
    PLAN_STATUSES,
    STATUS_BREAKING,
    STATUS_CONFLICT,
    STATUS_EXCLUDED,
    STATUS_READY,
    build_fix_plan,
    compose_entries,
    document_fingerprint,
    fix_id_for,
    parse_rules_param,
)
from app.openapi_overlay import PATCH_OVERLAY_VERSION, apply_overlays, render_patch_overlay
from app.schema_lint import LintFinding

FIXTURES = Path(__file__).parent / "fixtures" / "scanner_evaluation" / "fix"

#: Several defects at once: three duplicate tag declarations that repeat their first one (array
#: removals at several indexes), an unused schema that also uses ``example`` (a conflict the removal wins), an
#: operation without an operationId, ``required: []``, and a non-PascalCase schema (a breaking
#: rename when renames are included).
MULTI_DEFECT: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Shop", "version": "1.0.0", "description": "Multi-defect corpus."},
    "tags": [
        {"name": "orders", "description": "Orders."},
        {"name": "items"},
        {"name": "orders", "description": "Orders."},
        {"name": "items"},
        {"name": "orders"},
    ],
    "paths": {
        "/orders": {
            "get": {
                "tags": ["orders"],
                "summary": "List orders",
                "responses": {
                    "200": {
                        "description": "The orders.",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/order_record"}}
                        },
                    }
                },
            }
        },
        "/items": {
            "get": {
                "operationId": "listItems",
                "tags": ["items"],
                "summary": "List items",
                "responses": {"200": {"description": "The items."}},
            }
        },
    },
    "components": {
        "schemas": {
            "order_record": {
                "type": "object",
                "description": "An order.",
                "required": [],
                "properties": {"id": {"type": "string", "description": "Its id."}},
            },
            "Leftover": {
                "type": "string",
                "description": "Nothing references this.",
                "example": "x",
            },
        }
    },
}


def _corpus() -> List[Dict[str, Any]]:
    """Every corpus document: the one-defect fixtures and the multi-defect document."""
    docs = [json.loads(path.read_text(encoding="utf-8"))["before"] for path in sorted(FIXTURES.glob("*/fixture.json"))]
    return docs + [MULTI_DEFECT]


CORPUS = _corpus()


# ---------------------------------------------------------------------------
# Acceptance criteria over the corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("include_renames", [False, True])
@pytest.mark.parametrize("index", range(len(CORPUS)))
def test_plan_is_byte_identical_across_runs(index: int, include_renames: bool) -> None:
    document = CORPUS[index]
    first = build_fix_plan(document, include_renames=include_renames)
    second = build_fix_plan(copy.deepcopy(document), include_renames=include_renames)
    assert json.dumps(first.as_dict()) == json.dumps(second.as_dict())
    assert json.dumps(first.patch()) == json.dumps(second.patch())
    assert json.dumps(first.overlay()) == json.dumps(second.overlay())
    assert first.unified_diff() == second.unified_diff()


@pytest.mark.parametrize("include_renames", [False, True])
@pytest.mark.parametrize("index", range(len(CORPUS)))
def test_applying_the_ready_set_then_planning_again_leaves_nothing_ready(index: int, include_renames: bool) -> None:
    plan = build_fix_plan(CORPUS[index], include_renames=include_renames)
    again = build_fix_plan(plan.fixed_document, include_renames=include_renames)
    # A conflict loser whose finding outlived its winner is ready on the next pass; one more
    # pass settles it.
    while again.counts()[STATUS_READY]:
        assert again.counts()[STATUS_READY] < plan.counts()[STATUS_READY] + plan.counts()[STATUS_CONFLICT]
        plan, again = again, build_fix_plan(again.fixed_document, include_renames=include_renames)
    assert again.patch() == []
    assert again.unified_diff() == ""


@pytest.mark.parametrize("include_renames", [False, True])
@pytest.mark.parametrize("index", range(len(CORPUS)))
def test_overlay_rendering_reproduces_the_patch(index: int, include_renames: bool) -> None:
    document = CORPUS[index]
    plan = build_fix_plan(document, include_renames=include_renames)
    patched = apply_fix_ops(document, [PatchOp(**_op_kwargs(op)) for op in plan.patch()])
    assert patched == plan.fixed_document
    overlay = plan.overlay()
    if not overlay["actions"]:
        assert plan.patch() == []
        return
    result = apply_overlays(document, [("lint-fixes", overlay)])
    assert result.findings == []
    assert result.document == patched


@pytest.mark.parametrize("index", range(len(CORPUS)))
def test_no_breaking_fix_is_ever_ready(index: int) -> None:
    plan = build_fix_plan(CORPUS[index], include_renames=True)
    for entry in plan.entries:
        if entry.status == STATUS_READY:
            assert entry.classification is not None
            assert entry.classification["maxSeverity"] != "breaking"
    assert set(plan.applied_order) == {e.fix_id for e in plan.entries if e.status == STATUS_READY}


def _op_kwargs(op: Dict[str, Any]) -> Dict[str, Any]:
    """PatchOp keyword arguments from an RFC 6902 object."""
    return {"op": op["op"], "path": op["path"], "value": op.get("value"), "from_pointer": op.get("from")}


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------


def _by_rule(plan, rule_id: str):
    return [entry for entry in plan.entries if entry.rule_id == rule_id]


def test_multi_defect_plan_statuses() -> None:
    plan = build_fix_plan(MULTI_DEFECT)
    counts = plan.counts()
    assert set(counts) == set(PLAN_STATUSES)

    duplicates = _by_rule(plan, "structure.duplicate-tag")
    assert [e.status for e in duplicates] == [STATUS_READY] * 3
    unused = _by_rule(plan, "structure.unused-component")
    assert [e.status for e in unused] == [STATUS_READY]
    example = _by_rule(plan, "structure.schema-example-keyword")
    assert [e.status for e in example] == [STATUS_CONFLICT]
    assert example[0].conflicts_with == unused[0].fix_id
    rename = _by_rule(plan, "naming.schema-pascal-case")
    assert [(e.status, e.reason) for e in rename] == [(STATUS_EXCLUDED, EXCLUDED_RENAMES_NOT_INCLUDED)]
    assert rename[0].classification is None
    assert rename[0].ops  # an excluded entry still shows what it would do


def test_composition_removes_every_duplicate_tag_whatever_the_index_shift() -> None:
    plan = build_fix_plan(MULTI_DEFECT)
    assert [t["name"] for t in plan.fixed_document["tags"]] == ["orders", "items"]
    assert "Leftover" not in plan.fixed_document["components"]["schemas"]
    assert "required" not in plan.fixed_document["components"]["schemas"]["order_record"]
    assert plan.fixed_document["paths"]["/orders"]["get"]["operationId"] == "getOrders"


def test_a_breaking_fix_is_downgraded_with_its_classification() -> None:
    plan = build_fix_plan(MULTI_DEFECT, include_renames=True)
    rename = _by_rule(plan, "naming.schema-pascal-case")[0]
    assert rename.status == STATUS_BREAKING
    assert rename.wire_visible is True
    assert rename.classification["maxSeverity"] == "breaking"
    assert any(change["severity"] == "breaking" for change in rename.classification["changes"])
    assert rename.fix_id not in plan.applied_order
    assert "order_record" in plan.fixed_document["components"]["schemas"]


def test_off_by_default_fix_needs_an_opt_in() -> None:
    document = json.loads((FIXTURES / "structure.operation-missing-tags" / "fixture.json").read_text())["before"]
    plan = build_fix_plan(document)
    entry = _by_rule(plan, "structure.operation-missing-tags")[0]
    assert (entry.status, entry.reason) == (STATUS_EXCLUDED, EXCLUDED_OPT_IN_REQUIRED)
    named = build_fix_plan(document, rules=["structure.operation-missing-tags"])
    assert _by_rule(named, "structure.operation-missing-tags")[0].status == STATUS_READY


def test_rules_filter_excludes_the_others() -> None:
    plan = build_fix_plan(MULTI_DEFECT, rules=["structure.empty-required"])
    for entry in plan.entries:
        if entry.rule_id == "structure.empty-required":
            assert entry.status == STATUS_READY
        else:
            assert (entry.status, entry.reason) == (STATUS_EXCLUDED, EXCLUDED_NOT_SELECTED)
    assert plan.rules == ("structure.empty-required",)


def test_guide_disabled_rule_is_excluded_unless_named() -> None:
    def enabled(rule_id: str) -> bool:
        return rule_id != "structure.empty-required"

    plan = build_fix_plan(MULTI_DEFECT, enabled=enabled)
    entry = _by_rule(plan, "structure.empty-required")[0]
    assert (entry.status, entry.reason) == (STATUS_EXCLUDED, EXCLUDED_GUIDE_DISABLED)
    named = build_fix_plan(MULTI_DEFECT, enabled=enabled, rules=["structure.empty-required"])
    assert _by_rule(named, "structure.empty-required")[0].status == STATUS_READY


def test_unknown_rule_and_bad_template_are_refused() -> None:
    with pytest.raises(FixError):
        build_fix_plan(MULTI_DEFECT, rules=["no.such-rule"])
    with pytest.raises(FixError):
        build_fix_plan(MULTI_DEFECT, operation_id_template="{method}")


def test_operation_id_template_is_used() -> None:
    plan = build_fix_plan(MULTI_DEFECT, operation_id_template="{Method}{Path}Op")
    assert plan.fixed_document["paths"]["/orders"]["get"]["operationId"] == "GetOrdersOp"
    assert plan.as_dict()["operationIdTemplate"] == "{Method}{Path}Op"


def test_input_is_not_mutated() -> None:
    before = copy.deepcopy(MULTI_DEFECT)
    plan = build_fix_plan(MULTI_DEFECT, include_renames=True)
    plan.overlay()
    plan.unified_diff()
    assert MULTI_DEFECT == before


def test_a_document_without_defects_has_an_empty_plan() -> None:
    clean = json.loads((FIXTURES / "structure.empty-required" / "fixture.json").read_text())["after"]
    plan = build_fix_plan(clean, include_renames=True)
    assert plan.entries == ()
    assert plan.patch() == []
    assert plan.unified_diff() == ""
    assert plan.overlay()["actions"] == []
    assert plan.document_fingerprint == plan.as_dict()["fixedDocumentFingerprint"]


# ---------------------------------------------------------------------------
# Renderings and helpers
# ---------------------------------------------------------------------------


def test_unified_diff_names_both_sides() -> None:
    diff = build_fix_plan(MULTI_DEFECT).unified_diff()
    assert diff.startswith("--- a/openapi.json\n+++ b/openapi.json\n")
    removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
    assert any('"required": []' in line for line in removed)


def test_overlay_title_names_the_rules() -> None:
    overlay = build_fix_plan(MULTI_DEFECT).overlay()
    assert overlay["overlay"] == PATCH_OVERLAY_VERSION
    assert overlay["info"]["title"].startswith("Apiome lint fixes: ")
    assert "structure.duplicate-tag" in overlay["info"]["title"]
    assert all(action["description"].startswith("fix-") for action in overlay["actions"])


def test_fix_id_is_derived_from_the_finding_id() -> None:
    finding = LintFinding(path="a.b", category="structure", rule="r", severity="info", message="m")
    assert fix_id_for(finding) == "fix-" + finding.id[len("lint-") :]


def test_document_fingerprint_ignores_key_order() -> None:
    assert document_fingerprint({"a": 1, "b": 2}) == document_fingerprint({"b": 2, "a": 1})
    assert document_fingerprint({"a": 1}) != document_fingerprint({"a": 2})


def test_parse_rules_param() -> None:
    assert parse_rules_param(None) is None
    assert parse_rules_param(" , ") is None
    assert parse_rules_param("a, b,a") == ("a", "b")


def test_compose_reports_entries_that_no_longer_apply() -> None:
    plan = build_fix_plan(MULTI_DEFECT)
    unused = _by_rule(plan, "structure.unused-component")[0]
    example = _by_rule(plan, "structure.schema-example-keyword")[0]
    # Forced together, the example fix (the deeper edit of the same node) applies first in
    # reverse order and the removal after it; both apply, so nothing fails.
    fixed, applied, failed = compose_entries(MULTI_DEFECT, [unused, example])
    assert failed == []
    assert [e.fix_id for e in applied] == [example.fix_id, unused.fix_id]
    assert "Leftover" not in fixed["components"]["schemas"]
    # An entry whose ops address nothing is reported as failed.
    broken = type(unused)(**{**unused.__dict__, "ops": (PatchOp.remove("/nowhere"),)})
    _, _, failed = compose_entries(MULTI_DEFECT, [broken])
    assert failed == [broken]


# ---------------------------------------------------------------------------
# render_patch_overlay on its own
# ---------------------------------------------------------------------------

_BASE: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "T", "version": "1"},
    "tags": [{"name": "a"}, {"name": "b"}],
    "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}, "it's": "q"}}},
    "nums": [1, 2, 3],
    "nested": [[1, 2], [3]],
    "obj": {"k": {"deep": 1}, "n": None},
}


@pytest.mark.parametrize(
    "ops",
    [
        [PatchOp.add("/tags/-", {"name": "c"})],
        [PatchOp.add("/tags/0", {"name": "z"})],
        [PatchOp.replace("/tags/1", {"name": "B"})],
        [PatchOp.remove("/tags/0")],
        [PatchOp.replace("/nums/1", 20)],
        [PatchOp.add("/nums/1", 15)],
        [PatchOp.add("/nested/0/1", 9)],
        [PatchOp.replace("/obj/k", {"other": 2})],
        [PatchOp.replace("/obj/n", "now")],
        [PatchOp.add("/obj/new", [1, 2])],
        [PatchOp.add("/nums/-", [4, 5])],
        [PatchOp.replace("/paths/~1x/get/responses/200/description", "fine")],
        [PatchOp.replace("/paths/~1x/get/it's", "r")],
        [PatchOp.move("/obj/k", "/obj/moved")],
        [PatchOp("copy", "/obj/copied", from_pointer="/tags/0")],
        [PatchOp("test", "/info/title", value="T"), PatchOp.replace("/info/title", "U")],
        [PatchOp.remove("/tags/1"), PatchOp.remove("/tags/0"), PatchOp.add("/tags/-", {"name": "only"})],
    ],
)
def test_render_patch_overlay_matches_the_patch(ops: List[PatchOp]) -> None:
    expected = apply_fix_ops(_BASE, ops)
    overlay = render_patch_overlay(_BASE, [("group", ops)], title="t")
    result = apply_overlays(_BASE, [("o", overlay)])
    assert result.findings == []
    assert result.document == expected
    assert all(action["description"] == "group" for action in overlay["actions"])


def test_render_patch_overlay_keeps_a_replaced_primitive_in_place() -> None:
    overlay = render_patch_overlay(_BASE, [("g", [PatchOp.replace("/info/title", "U")])], title="t")
    assert overlay["actions"] == [{"target": "$['info']['title']", "update": "U", "description": "g"}]
    result = apply_overlays(_BASE, [("o", overlay)]).document
    assert list(result["info"]) == ["title", "version"]


def test_render_patch_overlay_rejects_an_op_that_does_not_apply() -> None:
    with pytest.raises(FixError):
        render_patch_overlay(_BASE, [("g", [PatchOp.remove("/missing")])], title="t")
