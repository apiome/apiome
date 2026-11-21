"""GVM-4.4 (#5879) — Arazzo 1.1 validation rules and the operationRef rule-id alias.

Covers:

* the static runtime-expression grammar (:mod:`app.arazzo_expression_grammar`), including the
  position it reports;
* each of the twelve new ``arazzo.*`` rules (:mod:`app.arazzo_structure_rules`), firing on its
  defect and staying silent on the compliant 1.1 corpus workflow;
* the ``arzzo.unresolvable-operation-ref`` alias in guide compilation and decision matching (the
  ``GET /v1/lint/rules`` half lives in ``tests/test_lint_routes.py``);
* the shipped Arazzo corpus, which the new rules must not flag apart from the reviewed findings.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.arazzo_expression_grammar import (
    condition_expression_errors,
    embedded_expression_errors,
    runtime_expression_error,
    string_expression_errors,
)
from app.arazzo_import_source import ArazzoImportSource
from app.arazzo_lint import ArazzoRulePack, lint_arazzo, lint_arazzo_result
from app.arazzo_spec import allowed_source_types, parameter_locations
from app.lint_rule_aliases import aliases_for, canonical_rule_id, fingerprint_rule_id
from app.lint_rule_registry import registered_rule_ids_with_aliases, resolve_rule_id
from app.policy_evaluate import evaluate_policy, match_decision_for_fingerprint
from app.schema_lint import LintFinding
from app.style_guide_engine import compile_style_guide

CORPUS = Path(__file__).resolve().parent / "fixtures" / "scanner_evaluation" / "catalog"
EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

NEW_RULES = (
    "arazzo.runtime-expression-invalid",
    "arazzo.success-criteria-context-required",
    "arazzo.on-success-target-unresolved",
    "arazzo.on-failure-target-unresolved",
    "arazzo.component-ref-unresolved",
    "arazzo.step-id-duplicate",
    "arazzo.workflow-id-duplicate",
    "arazzo.depends-on-cycle",
    "arazzo.parameter-in-invalid",
    "arazzo.inputs-schema-invalid",
    "arazzo.outputs-expression-invalid",
    "arazzo.source-description-type-invalid",
)

LEGACY_ID = "arzzo.unresolvable-operation-ref"
CANONICAL_ID = "arazzo.unresolvable-operation-ref"


def _compliant() -> Dict[str, Any]:
    """A fresh copy of the corpus's fully compliant Arazzo 1.1 workflow."""
    path = CORPUS / "arazzo-compliant-1-1-workflow" / "fixture.json"
    return copy.deepcopy(json.loads(path.read_text())["document"])


def _findings(document: Dict[str, Any]) -> List[Any]:
    return list(lint_arazzo_result(ArazzoImportSource().normalize(document)).findings)


def _rules(document: Dict[str, Any]) -> List[str]:
    return sorted({finding.rule for finding in _findings(document)})


def _messages(document: Dict[str, Any], rule: str) -> List[str]:
    return [finding.message for finding in _findings(document) if finding.rule == rule]


# =============================================================================================
# Runtime-expression grammar
# =============================================================================================


@pytest.mark.parametrize(
    "expression",
    [
        "$url",
        "$method",
        "$statusCode",
        "$self",
        "$request.header.X-Request-Id",
        "$request.query.page",
        "$request.path.id",
        "$request.body",
        "$request.body#/items/0/sku",
        "$response.body#/a~1b/c~0d",
        "$response.header.Location",
        "$message.payload",
        "$message.payload#/acceptedAt",
        "$message.payload.orderId",
        "$message.header.requestId",
        "$message.header#/traceId",
        "$inputs.sku",
        "$inputs",
        "$outputs.orderId",
        "$steps.createOrder.outputs.orderId",
        "$workflows.sync.outputs.id",
        "$sourceDescriptions.orders.createOrder",
        "$components.parameters.pageSize",
    ],
)
def test_the_grammar_accepts_every_defined_form(expression: str) -> None:
    assert runtime_expression_error(expression) is None


@pytest.mark.parametrize(
    ("expression", "position", "fragment"),
    [
        ("$respons.body", 1, "unknown expression root '$respons'"),
        ("$statusCode.value", 11, "takes nothing after it"),
        ("$response.headers.X", 10, "expected header.NAME"),
        ("$response.body/id", 10, "expected header.NAME"),
        ("$response.body#id", 15, "must be empty or start with '/'"),
        ("$response.body#/a~2", 17, "'~' in a JSON Pointer"),
        ("$response.header.X:Y", 18, "':' is not allowed in a header name"),
        ("$inputs.", 8, "expected a name"),
        ("$steps", 6, "expected '.' after '$steps'"),
        ("$message.data", 9, "expected header, payload or body"),
        ("inputs.sku", 0, "starts with '$'"),
    ],
)
def test_the_grammar_reports_where_it_stops(expression: str, position: int, fragment: str) -> None:
    issue = runtime_expression_error(expression)
    assert issue is not None
    assert issue.position == position
    assert fragment in issue.reason
    assert f"at position {position}" in issue.describe()


def test_embedded_expressions_report_their_offset_in_the_template() -> None:
    issues = embedded_expression_errors("Bearer {$steps.login.outputs.token} {$respnse.body}")
    assert len(issues) == 1
    assert issues[0].expression == "$respnse.body"
    assert issues[0].position == len("Bearer {$steps.login.outputs.token} {$")


def test_a_literal_string_is_never_an_expression_error() -> None:
    assert string_expression_errors("web") == []
    assert string_expression_errors("$100 off") == []
    assert string_expression_errors("req-{$inputs.sku}") == []


def test_simple_conditions_check_operands_but_not_quoted_literals() -> None:
    assert condition_expression_errors("$statusCode == 200 && $response.body#/ok == true") == []
    assert condition_expression_errors("$response.body#/note == '$not an expression'") == []
    issues = condition_expression_errors("$statusCode == 200 && $respons.body#/ok")
    assert [issue.expression for issue in issues] == ["$respons.body#/ok"]
    assert issues[0].position == len("$statusCode == 200 && $")


# =============================================================================================
# Version tables
# =============================================================================================


def test_source_types_and_parameter_locations_follow_the_published_schemas() -> None:
    assert allowed_source_types((1, 0)) == ("openapi", "arazzo")
    assert allowed_source_types((1, 1)) == ("openapi", "arazzo", "asyncapi")
    assert allowed_source_types((1, 9)) == allowed_source_types((1, 1))
    assert parameter_locations((1, 0), "openapi") == ("path", "query", "header", "cookie")
    assert "querystring" in parameter_locations((1, 1), "openapi")
    assert parameter_locations((1, 1), "asyncapi") == ("header", "channel")
    assert parameter_locations((1, 0), "asyncapi") == ()


# =============================================================================================
# The rules
# =============================================================================================


def test_the_pack_registers_all_twelve_new_rules_as_errors() -> None:
    rules = {rule.rule_id: rule for rule in ArazzoRulePack().rules()}
    for rule_id in NEW_RULES:
        assert rules[rule_id].severity == "error", rule_id
    assert CANONICAL_ID in rules and LEGACY_ID not in rules


def test_the_compliant_1_1_workflow_trips_nothing() -> None:
    """AC: one fully compliant 1.1 workflow that trips no rule at all."""
    assert _findings(_compliant()) == []


def test_runtime_expression_invalid_reports_the_position() -> None:
    document = _compliant()
    document["workflows"][0]["steps"][0]["parameters"][0]["value"] = "$respons.header.X-Trace"
    assert _rules(document) == ["arazzo.runtime-expression-invalid"]
    (message,) = _messages(document, "arazzo.runtime-expression-invalid")
    assert "parameters[0].value" in message and "at position 1" in message


def test_runtime_expression_invalid_covers_criteria_and_request_bodies() -> None:
    document = _compliant()
    step = document["workflows"][0]["steps"][0]
    step["requestBody"]["payload"]["sku"] = "$input.sku"
    step["successCriteria"][0]["condition"] = "$statuscode == 201"
    step["successCriteria"][1]["context"] = "$response.bdy"
    messages = _messages(document, "arazzo.runtime-expression-invalid")
    assert len(messages) == 3
    assert any(m.startswith("requestBody") for m in messages)
    assert any("successCriteria[0].condition" in m for m in messages)
    assert any("successCriteria[1].context" in m for m in messages)


def test_jsonpath_and_regex_conditions_are_not_parsed_as_expressions() -> None:
    document = _compliant()
    document["workflows"][0]["steps"][0]["successCriteria"][1]["condition"] = "$.items[0].sku"
    assert _findings(document) == []


def test_success_criteria_context_required() -> None:
    document = _compliant()
    del document["workflows"][0]["steps"][1]["successCriteria"][0]["context"]
    assert _rules(document) == ["arazzo.success-criteria-context-required"]
    assert "regex criterion" in _messages(document, "arazzo.success-criteria-context-required")[0]


def test_a_simple_criterion_needs_no_context() -> None:
    document = _compliant()
    document["workflows"][0]["steps"][0]["successCriteria"][0]["type"] = "simple"
    assert _findings(document) == []


def test_on_success_target_unresolved_for_a_step_and_a_bare_goto() -> None:
    document = _compliant()
    document["workflows"][0]["steps"][0]["onSuccess"] = [
        {"name": "typo", "type": "goto", "stepId": "awaitAcepted"},
        {"name": "nowhere", "type": "goto"},
    ]
    messages = _messages(document, "arazzo.on-success-target-unresolved")
    assert _rules(document) == ["arazzo.on-success-target-unresolved"]
    assert any("'awaitAcepted'" in m for m in messages)
    assert any("neither a stepId nor a workflowId" in m for m in messages)


def test_a_goto_step_id_must_be_in_the_same_workflow() -> None:
    document = _compliant()
    document["workflows"][1]["steps"][0]["onSuccess"] = [{"name": "cross", "type": "goto", "stepId": "createOrder"}]
    assert _rules(document) == ["arazzo.on-success-target-unresolved"]


def test_on_failure_target_unresolved_and_source_workflow_targets() -> None:
    document = _compliant()
    step = document["workflows"][1]["steps"][0]
    step["onFailure"] = [{"name": "back", "type": "goto", "workflowId": "placeOrdr"}]
    assert _rules(document) == ["arazzo.on-failure-target-unresolved"]

    step["onFailure"] = [{"name": "elsewhere", "type": "goto", "workflowId": "$sourceDescriptions.orders.refund"}]
    assert _findings(document) == []
    step["onFailure"] = [{"name": "elsewhere", "type": "goto", "workflowId": "$sourceDescriptions.billing.refund"}]
    assert _rules(document) == ["arazzo.on-failure-target-unresolved"]


def test_workflow_level_failure_actions_are_checked() -> None:
    document = _compliant()
    document["workflows"][0]["failureActions"] = [{"name": "x", "type": "goto", "stepId": "ship"}]
    assert _rules(document) == ["arazzo.on-failure-target-unresolved"]


def test_component_ref_unresolved() -> None:
    document = _compliant()
    document["workflows"][0]["steps"][0]["parameters"][1]["reference"] = "$components.parameters.channelHnt"
    document["workflows"][0]["steps"][0]["onFailure"][0]["reference"] = "$components.failureActions.nope"
    messages = _messages(document, "arazzo.component-ref-unresolved")
    assert _rules(document) == ["arazzo.component-ref-unresolved"]
    assert len(messages) == 2


def test_a_missing_component_kind_is_reported() -> None:
    document = _compliant()
    document["workflows"][0]["steps"][0]["parameters"][1]["reference"] = "$components.inputs.order"
    (message,) = _messages(document, "arazzo.component-ref-unresolved")
    assert "components.inputs, which the document does not declare" in message


def test_step_id_duplicate() -> None:
    document = _compliant()
    steps = document["workflows"][0]["steps"]
    steps[1]["stepId"] = "createOrder"
    steps[0]["onSuccess"][0]["stepId"] = "createOrder"
    steps[1]["correlationId"] = "$inputs.sku"
    assert _rules(document) == ["arazzo.step-id-duplicate"]


def test_workflow_id_duplicate() -> None:
    document = _compliant()
    document["workflows"][1]["workflowId"] = "placeOrder"
    document["workflows"][1]["dependsOn"] = []
    assert _rules(document) == ["arazzo.workflow-id-duplicate"]


def test_depends_on_cycle_is_reported_once_with_its_chain() -> None:
    document = _compliant()
    document["workflows"][0]["dependsOn"] = ["shipOrder"]
    (message,) = _messages(document, "arazzo.depends-on-cycle")
    assert _rules(document) == ["arazzo.depends-on-cycle"]
    assert "placeOrder → shipOrder → placeOrder" in message


def test_a_self_dependency_is_a_cycle_and_a_foreign_dependency_is_not() -> None:
    document = _compliant()
    document["workflows"][1]["dependsOn"] = ["shipOrder", "$sourceDescriptions.orders.other"]
    assert _messages(document, "arazzo.depends-on-cycle") == ["dependsOn forms a cycle: shipOrder → shipOrder."]


def test_parameter_in_invalid_per_source_type() -> None:
    document = _compliant()
    document["workflows"][1]["steps"][0]["parameters"][0]["in"] = "body"
    document["workflows"][0]["steps"][1]["parameters"][0]["in"] = "querystring"
    messages = _messages(document, "arazzo.parameter-in-invalid")
    assert _rules(document) == ["arazzo.parameter-in-invalid"]
    assert any("`in: body`" in m and "openapi step" in m for m in messages)
    assert any("`in: querystring`" in m and "asyncapi step" in m for m in messages)


def test_querystring_is_a_1_1_location_only() -> None:
    document = _compliant()
    document["workflows"][1]["steps"][0]["parameters"][0]["in"] = "querystring"
    assert _findings(document) == []
    document["arazzo"] = "1.0.1"
    document["sourceDescriptions"] = document["sourceDescriptions"][:1]
    document["workflows"] = document["workflows"][1:]
    document["workflows"][0]["dependsOn"] = []
    assert "arazzo.parameter-in-invalid" in _rules(document)


def test_an_operation_step_parameter_must_declare_in() -> None:
    document = _compliant()
    del document["workflows"][1]["steps"][0]["parameters"][0]["in"]
    (message,) = _messages(document, "arazzo.parameter-in-invalid")
    assert "declares no `in`" in message


def test_inputs_schema_invalid() -> None:
    document = _compliant()
    document["workflows"][1]["inputs"]["properties"]["orderId"]["type"] = "text"
    (message,) = _messages(document, "arazzo.inputs-schema-invalid")
    assert _rules(document) == ["arazzo.inputs-schema-invalid"]
    assert "JSON Schema 2020-12" in message and "/properties/orderId/type" in message


def test_outputs_expression_invalid() -> None:
    document = _compliant()
    document["workflows"][1]["steps"][0]["outputs"]["shipmentId"] = "Location"
    document["workflows"][1]["outputs"]["shipmentId"] = "$steps.ship.outputs"
    document["workflows"][0]["outputs"]["orderId"] = "$step.createOrder.outputs.orderId"
    messages = _messages(document, "arazzo.outputs-expression-invalid")
    assert _rules(document) == ["arazzo.outputs-expression-invalid"]
    assert any("literal 'Location'" in m for m in messages)
    assert any("at position 1" in m for m in messages)


def test_selector_outputs_are_a_1_1_form() -> None:
    document = _compliant()
    selector = {"context": "$response.body", "selector": "$.id", "type": "jsonpath"}
    document["workflows"][0]["steps"][0]["outputs"]["orderId"] = selector
    assert _findings(document) == []
    selector["context"] = "$respnse.body"
    assert _rules(document) == ["arazzo.outputs-expression-invalid"]


def test_source_description_type_invalid() -> None:
    document = _compliant()
    document["sourceDescriptions"].append(
        {"name": "catalog", "type": "graphql", "url": "https://api.example.test/schema.graphql"}
    )
    (message,) = _messages(document, "arazzo.source-description-type-invalid")
    assert "'catalog'" in message and "openapi, arazzo, asyncapi" in message


def test_an_asyncapi_source_under_1_0_is_reported_by_the_older_rule_only() -> None:
    """The existing async-source-before-1-1 rule is the AsyncAPI case of the type table."""
    document = json.loads((CORPUS / "arazzo-async-source-before-1-1" / "fixture.json").read_text())["document"]
    rules = _rules(document)
    assert "arazzo.async-source-before-1-1" in rules
    assert "arazzo.source-description-type-invalid" not in rules


# =============================================================================================
# The operationRef rule rename and its alias
# =============================================================================================


def test_the_operation_ref_rule_is_emitted_under_the_corrected_id() -> None:
    document = json.loads((CORPUS / "arazzo-unresolvable-operation-ref" / "fixture.json").read_text())["document"]
    rules = _rules(document)
    assert CANONICAL_ID in rules and LEGACY_ID not in rules


def test_the_alias_table_round_trips() -> None:
    assert canonical_rule_id(LEGACY_ID) == CANONICAL_ID
    assert canonical_rule_id(CANONICAL_ID) == CANONICAL_ID
    assert aliases_for(CANONICAL_ID) == (LEGACY_ID,)
    assert resolve_rule_id(LEGACY_ID).rule_id == CANONICAL_ID
    assert LEGACY_ID in registered_rule_ids_with_aliases()


def test_guide_compilation_resolves_the_alias() -> None:
    """AC: a style-guide row stored under the typo id governs the renamed rule."""
    rows = [{"rule_id": LEGACY_ID, "enabled": True, "severity": "warning", "custom_def": None}]
    guide = compile_style_guide("guide-alias", "Custom", "custom", rows)
    assert guide.severity_for(CANONICAL_ID) == "warning"
    assert guide.is_enabled(LEGACY_ID)

    document = json.loads((CORPUS / "arazzo-unresolvable-operation-ref" / "fixture.json").read_text())["document"]
    result = guide.apply(lint_arazzo_result(ArazzoImportSource().normalize(document)))
    governed = [finding for finding in result.findings if finding.rule == CANONICAL_ID]
    assert governed and all(finding.severity == "warning" for finding in governed)


def test_a_canonical_row_wins_over_an_alias_row() -> None:
    rows = [
        {"rule_id": LEGACY_ID, "enabled": True, "severity": "info", "custom_def": None},
        {"rule_id": CANONICAL_ID, "enabled": True, "severity": "error", "custom_def": None},
    ]
    assert compile_style_guide("both-1", "Both", "custom", rows).severity_for(CANONICAL_ID) == "error"
    assert compile_style_guide("both-2", "Both", "custom", rows[::-1]).severity_for(CANONICAL_ID) == "error"


def test_decision_matching_keeps_a_waiver_recorded_under_the_old_id() -> None:
    """AC: a waiver keyed by a pre-rename finding fingerprint still waives the renamed finding."""
    path = "services.checkout.operations.checkout#badRef"
    message = "Step operationRef '#/sourceDescriptions/missingSource' points at unknown sourceDescription."
    before = LintFinding(path=path, category="reference", rule=LEGACY_ID, severity="error", message=message)
    after = LintFinding(path=path, category="reference", rule=CANONICAL_ID, severity="error", message=message)
    assert fingerprint_rule_id(CANONICAL_ID) == LEGACY_ID
    assert before.id == after.id

    waiver = {
        "source_fingerprint": before.id,
        "project_id": None,
        "state": "waived",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }
    assert match_decision_for_fingerprint([waiver], after.id) is waiver
    evaluation = evaluate_policy(findings=[after.as_dict()], decisions_by_fingerprint={before.id: waiver})
    (decision,) = evaluation.finding_decisions
    assert decision["waived"] is True and decision["rule_id"] == CANONICAL_ID
    assert evaluation.gate_results["unwaived_errors"]["passed"] is True


def test_other_rules_hash_their_own_id() -> None:
    assert fingerprint_rule_id("arazzo.step-id-duplicate") == "arazzo.step-id-duplicate"


# =============================================================================================
# The shipped corpus
# =============================================================================================


#: Corpus documents the new rules flag on purpose, reviewed in the PR: Specmatic's PlaceOrder
#: workflow passes `$specmatic.auth`, a runner-specific root the Arazzo grammar does not define.
_REVIEWED = {"arazzo-1.1/16-specmatic-place-order.arazzo.yaml": {"arazzo.runtime-expression-invalid"}}


@pytest.mark.parametrize(
    "relative",
    sorted(
        str(path.relative_to(EXAMPLES))
        for directory in ("arazzo", "arazzo-1.1")
        for path in (EXAMPLES / directory).glob("*.y*ml")
    ),
)
def test_the_new_rules_do_not_flag_the_shipped_corpus(relative: str) -> None:
    try:
        result = lint_arazzo((EXAMPLES / relative).read_text())
    except Exception:  # noqa: BLE001 - a document the importer rejects is the negative suite's
        pytest.skip("not importable on its own")
    fired = {finding.rule for finding in result.findings if finding.rule in NEW_RULES}
    assert fired == _REVIEWED.get(relative, set())


def _workflow(workflow_id: str, depends_on: List[str]) -> Dict[str, Any]:
    """A minimal valid workflow with one step, depending on ``depends_on``."""
    return {
        "workflowId": workflow_id,
        "dependsOn": depends_on,
        "steps": [
            {
                "stepId": "only",
                "operationId": "$sourceDescriptions.orders.createOrder",
                "successCriteria": [{"condition": "$statusCode == 200"}],
            }
        ],
    }


def test_a_three_workflow_cycle_is_reported_once_from_its_first_member() -> None:
    document = _compliant()
    document["workflows"] = [_workflow("c", ["a"]), _workflow("a", ["b"]), _workflow("b", ["c"])]
    assert _messages(document, "arazzo.depends-on-cycle") == ["dependsOn forms a cycle: a → b → c → a."]


def test_a_dense_acyclic_dependency_graph_is_checked_quickly() -> None:
    """Every workflow depends on every earlier one: no cycle, and no path explosion."""
    document = _compliant()
    names = [f"w{index:02d}" for index in range(40)]
    document["workflows"] = [_workflow(name, names[:index]) for index, name in enumerate(names)]
    assert _messages(document, "arazzo.depends-on-cycle") == []
    document["workflows"][0]["dependsOn"] = [names[-1]]
    (message,) = _messages(document, "arazzo.depends-on-cycle")
    assert message == "dependsOn forms a cycle: w00 → w39 → w00."
