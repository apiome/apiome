"""Tests for running an Arazzo workflow against a target — COA-1.7 (#7043).

Covers the runtime-expression evaluator and criteria (:mod:`app.arazzo_runtime_expression`), the
compiler, CTG-4.3 safety plan and executor (:mod:`app.arazzo_workflow_run`), the orchestration
service and the ``POST …/workflows/{workflow_id}/run`` route. The acceptance criteria are the
``test_acceptance_*`` tests: a 3-step workflow run against a stateful mock (an
``httpx.MockTransport`` standing in for an Apiome mock target) with passing and failing criteria,
and mutating steps refused without policy and opt-in.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.arazzo_runtime_expression import (
    CRITERION_ERROR,
    CRITERION_FAILED,
    CRITERION_PASSED,
    ExpressionContext,
    ExpressionError,
    evaluate_criterion,
    evaluate_expression,
    is_status_condition,
    resolve_json_pointer,
    resolve_value,
)
from app.arazzo_workflow_persistence import WorkflowRow, WorkflowStepRow
from app.arazzo_workflow_run import (
    CODE_ACTION_UNSUPPORTED,
    CODE_CRITERIA_FAILED,
    CODE_EXPRESSION_UNRESOLVED,
    CODE_OUTPUT_UNRESOLVED,
    CODE_RETRIES_EXHAUSTED,
    CODE_STEP_INVALID,
    CODE_STEP_LIMIT,
    CODE_STEP_UNRESOLVED,
    CODE_STEP_WORKFLOW_UNSUPPORTED,
    MAX_STEP_EXECUTIONS,
    RUNNER_NAME,
    ArazzoRunOptions,
    apply_input_defaults,
    compile_workflow_run,
    evidence_operations,
    execute_workflow,
    plan_digest,
    plan_mutating_steps,
    validate_inputs,
)
from app.provider_verification import (
    FIXTURE_CODE_NOT_MUTATING,
    FIXTURE_CODE_UNMATCHED,
    SKIP_MUTATING_BLOCKED,
    SKIP_MUTATING_FIXTURE_MISSING,
    MutatingFixture,
)
from app.verification_evidence import VerificationRunInput, validate_run_input
from app.verification_target import (
    NETWORK_CLASS_PRIVATE,
    ResolvedTarget,
    TargetAuthReference,
    VerificationPolicy,
)

# ---------------------------------------------------------------------------------------------
# Fixtures: a stateful pet-store mock and the workflows that run against it
# ---------------------------------------------------------------------------------------------

_BASE_URL = "http://mock.test/acme/pets/1.0.0"
_OPS = {
    "op-list": {"method": "get", "path": "/pets"},
    "op-get": {"method": "get", "path": "/pets/{petId}"},
    "op-owner": {"method": "get", "path": "/pets/{petId}/owner"},
    "op-create": {"method": "post", "path": "/pets"},
    "op-delete": {"method": "delete", "path": "/pets/{petId}"},
}


class PetStoreMock:
    """A tiny stateful mock of the pet store, recording every request it receives."""

    def __init__(self, *, name: str = "Rex", owner: str = "Ada") -> None:
        self.pets: Dict[str, Dict[str, Any]] = {
            "7": {"id": "7", "name": name, "status": "available"}
        }
        self.owner = owner
        self.requests: List[httpx.Request] = []
        self.fail_next: int = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path[len("/acme/pets/1.0.0") :]
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(503, json={"error": "warming up"})
        if request.method == "GET" and path == "/pets":
            status = request.url.params.get("status")
            pets = [p for p in self.pets.values() if not status or p["status"] == status]
            return httpx.Response(200, json=pets, headers={"X-Total": str(len(pets))})
        if request.method == "POST" and path == "/pets":
            body = json.loads(request.content)
            pet = {"id": str(100 + len(self.pets)), "status": "available", **body}
            self.pets[pet["id"]] = pet
            return httpx.Response(201, json=pet)
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "pets":
            pet = self.pets.get(parts[1])
            if pet is None:
                return httpx.Response(404, json={"error": "not found"})
            if request.method == "DELETE":
                del self.pets[parts[1]]
                return httpx.Response(204)
            if len(parts) == 3 and parts[2] == "owner":
                return httpx.Response(200, json={"name": self.owner})
            return httpx.Response(200, json=pet)
        return httpx.Response(404)


def _target(**policy: Any) -> ResolvedTarget:
    """A resolved ``mock`` environment target."""
    return ResolvedTarget(
        target_id="22222222-2222-4222-8222-222222222222",
        slug="pets-mock",
        name="Pets mock",
        environment="mock",
        network_class=NETWORK_CLASS_PRIVATE,
        base_url=_BASE_URL,
        policy=VerificationPolicy(**policy),
        auth=TargetAuthReference(),
        resolved_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
    )


def _step(step_id: str, op: Optional[str], index: int, **fields: Any) -> WorkflowStepRow:
    """A resolved (or, with ``op=None``, unresolved) step row."""
    extras = fields.pop("extras", {})
    return WorkflowStepRow(
        step_id=step_id,
        order_index=index,
        operation_id=step_id,
        resolved_path_operation_id=op,
        resolution_status="resolved" if op else "unresolved",
        resolution_reason=None if op else "operation-not-found",
        extras=extras,
        **fields,
    )


def _three_step_workflow(*, expect_name: str = "Rex") -> WorkflowRow:
    """find a pet → read it → read its owner, chained through outputs."""
    return WorkflowRow(
        workflow_id="adoptPet",
        inputs={
            "type": "object",
            "properties": {"status": {"type": "string", "default": "available"}},
        },
        outputs={"petName": "$steps.getPet.outputs.name", "owner": "$steps.getOwner.outputs.owner"},
        steps=[
            _step(
                "findPets",
                "op-list",
                0,
                parameters=[{"name": "status", "in": "query", "value": "$inputs.status"}],
                success_criteria=[
                    {"condition": "$statusCode == 200"},
                    {"condition": "$response.header.X-Total >= 1"},
                    {
                        "context": "$response.body",
                        "condition": "$[?(@.status == 'available')]",
                        "type": "jsonpath",
                    },
                ],
                outputs={"petId": "$response.body#/0/id"},
            ),
            _step(
                "getPet",
                "op-get",
                1,
                parameters=[
                    {"name": "petId", "in": "path", "value": "$steps.findPets.outputs.petId"}
                ],
                success_criteria=[
                    {"condition": "$statusCode == 200"},
                    {"condition": f"$response.body#/name == '{expect_name}'"},
                    {"condition": "$response.body#/status != 'sold'"},
                ],
                outputs={"name": "$response.body#/name"},
            ),
            _step(
                "getOwner",
                "op-owner",
                2,
                parameters=[
                    {"name": "petId", "in": "path", "value": "{$steps.findPets.outputs.petId}"}
                ],
                success_criteria=[
                    {"context": "$response.body#/name", "condition": "^[A-Z]", "type": "regex"}
                ],
                outputs={"owner": "$response.body#/name"},
            ),
        ],
    )


def _run(
    workflow: WorkflowRow,
    mock: PetStoreMock,
    *,
    inputs: Optional[Dict[str, Any]] = None,
    options: Optional[ArazzoRunOptions] = None,
    components: Optional[Dict[str, Any]] = None,
    **policy: Any,
):
    """Compile, plan and execute ``workflow`` against ``mock``; return ``(plan, report)``."""
    plan = compile_workflow_run(workflow, operations=_OPS, components=components)
    plan_mutating_steps(
        plan,
        options or ArazzoRunOptions(),
        target_allows_mutating=VerificationPolicy(**policy).allow_mutating_methods,
    )
    if plan.refusals:
        return plan, None
    filled = apply_input_defaults(plan.inputs_schema, inputs or {})
    client = httpx.Client(transport=httpx.MockTransport(mock))
    report = execute_workflow(
        plan,
        filled,
        target=_target(**policy),
        client=client,
        digest=plan_digest(plan, filled),
        sleep=lambda _s: None,
    )
    return plan, report


def _evidence(report) -> Dict[str, int]:
    """Validate the report's evidence exactly as the store would, returning its counts."""
    return validate_run_input(
        VerificationRunInput(
            target_ref="pets-mock",
            suite_digest=report.digest or "sha256:" + "0" * 64,
            runner_name=RUNNER_NAME,
            started_at=report.started_at,
            finished_at=report.finished_at,
            operations=evidence_operations(report),
        )
    )


# ---------------------------------------------------------------------------------------------
# Acceptance criteria
# ---------------------------------------------------------------------------------------------


def test_acceptance_three_step_workflow_passes_against_the_mock():
    mock = PetStoreMock()
    _plan, report = _run(_three_step_workflow(), mock)

    assert report.outcome == "passed"
    assert [s.step_id for s in report.steps] == ["findPets", "getPet", "getOwner"]
    assert all(s.outcome == "passed" for s in report.steps)
    # Outputs fed the later steps through runtime expressions.
    assert [r.url.path for r in mock.requests] == [
        "/acme/pets/1.0.0/pets",
        "/acme/pets/1.0.0/pets/7",
        "/acme/pets/1.0.0/pets/7/owner",
    ]
    assert mock.requests[0].url.params["status"] == "available"  # input default applied
    assert report.steps[0].outputs == {"petId": "7"}
    assert report.outputs == {"petName": "Rex", "owner": "Ada"}
    assert report.not_reached == []
    criteria = report.steps[1].criteria
    assert [c.outcome for c in criteria] == ["passed", "passed", "passed"]
    assert criteria[0].actual == "200 == 200"
    assert _evidence(report)["passed"] == 3


def test_acceptance_failing_criterion_reports_expected_vs_actual_and_stops():
    mock = PetStoreMock(name="Fido")
    _plan, report = _run(_three_step_workflow(expect_name="Rex"), mock)

    assert report.outcome == "failed"
    failed = report.steps[1]
    assert failed.outcome == "failed" and failed.failure_code == CODE_CRITERIA_FAILED
    name_check = failed.criteria[1]
    assert name_check.outcome == CRITERION_FAILED
    assert name_check.expected == "$response.body#/name == 'Rex'"
    assert name_check.actual == "'Fido' == 'Rex'"
    # No onFailure: the run ends at the failing step and says what it never reached.
    assert [s.step_id for s in report.steps] == ["findPets", "getPet"]
    assert report.not_reached == ["getOwner"]
    assert report.outputs == {}
    counts = _evidence(report)
    assert counts == {"total": 2, "passed": 1, "failed": 1, "errored": 0, "skipped": 0}
    assertion = evidence_operations(report)[1].assertions[1]
    assert assertion.outcome == "failed" and assertion.actual == "'Fido' == 'Rex'"


def _mutating_workflow() -> WorkflowRow:
    """create a pet → read it back → delete it."""
    return WorkflowRow(
        workflow_id="petLifecycle",
        steps=[
            _step(
                "createPet",
                "op-create",
                0,
                extras={
                    "requestBody": {
                        "contentType": "application/json",
                        "payload": {"name": "$inputs.name"},
                    }
                },
                success_criteria=[{"condition": "$statusCode == 201"}],
                outputs={"id": "$response.body#/id"},
            ),
            _step(
                "getPet",
                "op-get",
                1,
                parameters=[
                    {"name": "petId", "in": "path", "value": "$steps.createPet.outputs.id"}
                ],
                success_criteria=[{"condition": "$response.body#/name == $inputs.name"}],
            ),
            _step(
                "deletePet",
                "op-delete",
                2,
                parameters=[
                    {"name": "petId", "in": "path", "value": "$steps.createPet.outputs.id"}
                ],
                success_criteria=[{"condition": "$statusCode == 204"}],
            ),
        ],
    )


def test_acceptance_mutating_steps_refused_without_policy():
    mock = PetStoreMock()
    options = ArazzoRunOptions(
        allow_mutating=True,
        fixtures=[
            MutatingFixture(operation_key="POST /pets"),
            MutatingFixture(operation_key="DELETE /pets/{petId}"),
        ],
    )
    plan, report = _run(_mutating_workflow(), mock, options=options, allow_mutating_methods=False)

    assert report is None and mock.requests == []
    assert [(r.step_id, r.code) for r in plan.refusals] == [
        ("createPet", SKIP_MUTATING_BLOCKED),
        ("deletePet", SKIP_MUTATING_BLOCKED),
    ]
    assert "allow_mutating_methods=false" in plan.refusals[0].message


def test_acceptance_mutating_steps_refused_without_opt_in():
    mock = PetStoreMock()
    plan, report = _run(_mutating_workflow(), mock, allow_mutating_methods=True)

    assert report is None and mock.requests == []
    assert {r.code for r in plan.refusals} == {SKIP_MUTATING_BLOCKED}
    assert "did not opt in" in plan.refusals[0].message


def test_mutating_steps_refused_without_fixture():
    mock = PetStoreMock()
    options = ArazzoRunOptions(
        allow_mutating=True, fixtures=[MutatingFixture(operation_key="POST /pets")]
    )
    plan, report = _run(_mutating_workflow(), mock, options=options, allow_mutating_methods=True)

    assert report is None and mock.requests == []
    assert [(r.step_id, r.code) for r in plan.refusals] == [
        ("deletePet", SKIP_MUTATING_FIXTURE_MISSING)
    ]


def test_mutating_steps_run_with_policy_opt_in_and_fixtures():
    mock = PetStoreMock()
    options = ArazzoRunOptions(
        allow_mutating=True,
        fixtures=[
            MutatingFixture(operation_key="POST /pets"),
            MutatingFixture(operation_key="DELETE /pets/{petId}", case_id="deletePet"),
        ],
    )
    _plan, report = _run(
        _mutating_workflow(),
        mock,
        options=options,
        inputs={"name": "Bolt"},
        allow_mutating_methods=True,
    )

    assert report.outcome == "passed", report.model_dump()
    assert [r.method for r in mock.requests] == ["POST", "GET", "DELETE"]
    assert json.loads(mock.requests[0].content) == {"name": "Bolt"}
    assert mock.requests[2].url.path.endswith("/pets/101")
    assert report.steps[0].fixture_applied and not report.steps[1].fixture_applied
    assert "101" not in mock.pets


def test_fixture_overrides_the_step_request():
    mock = PetStoreMock()
    options = ArazzoRunOptions(
        allow_mutating=True,
        fixtures=[
            MutatingFixture(operation_key="POST /pets", body={"name": "Disposable"}),
            MutatingFixture(operation_key="DELETE /pets/{petId}"),
        ],
    )
    _plan, report = _run(
        _mutating_workflow(),
        mock,
        options=options,
        inputs={"name": "Bolt"},
        allow_mutating_methods=True,
    )
    assert json.loads(mock.requests[0].content) == {"name": "Disposable"}
    # The read-back step compares with the input, so the overridden body fails it — honestly.
    assert report.steps[1].outcome == "failed"


def test_unused_fixtures_are_reported():
    plan = compile_workflow_run(_three_step_workflow(), operations=_OPS)
    plan_mutating_steps(
        plan,
        ArazzoRunOptions(
            allow_mutating=True,
            fixtures=[
                MutatingFixture(operation_key="GET /pets"),
                MutatingFixture(operation_key="PUT /nowhere"),
            ],
        ),
        target_allows_mutating=True,
    )
    assert plan.refusals == []
    assert [f.code for f in plan.fixture_findings] == [
        FIXTURE_CODE_NOT_MUTATING,
        FIXTURE_CODE_UNMATCHED,
    ]


# ---------------------------------------------------------------------------------------------
# Compilation refusals
# ---------------------------------------------------------------------------------------------


def test_unresolved_and_nested_workflow_steps_refuse_the_run():
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step("lost", None, 0),
            _step("nested", None, 1, extras={"workflowId": "other"}),
            _step("ok", "op-list", 2),
        ],
    )
    plan = compile_workflow_run(workflow, operations=_OPS)
    assert [(r.step_id, r.code) for r in plan.refusals] == [
        ("lost", CODE_STEP_UNRESOLVED),
        ("nested", CODE_STEP_WORKFLOW_UNSUPPORTED),
    ]
    with pytest.raises(ValueError):
        execute_workflow(plan, {}, target=_target(), client=MagicMock())


def test_a_parameter_without_a_location_refuses_the_run():
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[_step("s", "op-list", 0, parameters=[{"name": "status", "value": "x"}])],
    )
    plan = compile_workflow_run(workflow, operations=_OPS)
    assert [r.code for r in plan.refusals] == [CODE_STEP_INVALID]


def test_an_empty_workflow_is_refused():
    plan = compile_workflow_run(WorkflowRow(workflow_id="w"), operations=_OPS)
    assert [r.code for r in plan.refusals] == [CODE_STEP_INVALID]


def test_components_parameters_workflow_parameters_and_inputs_ref():
    components = {
        "parameters": {"statusFilter": {"name": "status", "in": "query", "value": "sold"}},
        "inputs": {
            "search": {
                "type": "object",
                "required": ["limit"],
                "properties": {"limit": {"type": "integer"}},
            }
        },
    }
    workflow = WorkflowRow(
        workflow_id="w",
        inputs={"$ref": "#/components/inputs/search"},
        extras={"parameters": [{"name": "X-Trace", "in": "header", "value": "wf"}]},
        steps=[
            _step(
                "s",
                "op-list",
                0,
                parameters=[
                    {"reference": "$components.parameters.statusFilter", "value": "available"},
                    {"name": "limit", "in": "query", "value": "$inputs.limit"},
                ],
            )
        ],
    )
    plan = compile_workflow_run(workflow, operations=_OPS, components=components)
    assert plan.refusals == []
    assert validate_inputs(plan.inputs_schema, {}) != []
    assert validate_inputs(plan.inputs_schema, {"limit": 5}) == []
    mock = PetStoreMock()
    client = httpx.Client(transport=httpx.MockTransport(mock))
    report = execute_workflow(plan, {"limit": 5}, target=_target(), client=client)
    assert report.outcome == "passed"
    sent = mock.requests[0]
    assert sent.url.params["status"] == "available" and sent.url.params["limit"] == "5"
    assert sent.headers["X-Trace"] == "wf"
    # No successCriteria: the implicit 2XX check is applied and marked as such.
    assert report.steps[0].criteria[0].implicit is True


def test_implicit_criterion_fails_a_server_error():
    mock = PetStoreMock()
    mock.fail_next = 1
    workflow = WorkflowRow(workflow_id="w", steps=[_step("s", "op-list", 0)])
    _plan, report = _run(workflow, mock)
    assert report.outcome == "failed"
    assert report.steps[0].criteria[0].actual == "503 >= 200 && 503 < 300"


# ---------------------------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------------------------


def test_retry_action_resends_and_merges_attempts():
    mock = PetStoreMock()
    mock.fail_next = 1
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "s",
                "op-list",
                0,
                success_criteria=[{"condition": "$statusCode == 200"}],
                on_failure=[{"name": "again", "type": "retry", "retryAfter": 1, "retryLimit": 2}],
            )
        ],
    )
    waits: List[float] = []
    plan = compile_workflow_run(workflow, operations=_OPS)
    client = httpx.Client(transport=httpx.MockTransport(mock))
    report = execute_workflow(plan, {}, target=_target(), client=client, sleep=waits.append)
    assert report.outcome == "passed"
    assert len(report.steps) == 1 and report.steps[0].attempts == 2
    assert waits == [1.0]
    assert _evidence(report)["passed"] == 1


def test_retry_exhaustion_fails_the_step():
    mock = PetStoreMock()
    mock.fail_next = 5
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "s",
                "op-list",
                0,
                success_criteria=[{"condition": "$statusCode == 200"}],
                on_failure=[{"name": "again", "type": "retry"}],
            )
        ],
    )
    _plan, report = _run(workflow, mock)
    step = report.steps[0]
    assert step.outcome == "failed" and step.failure_code == CODE_RETRIES_EXHAUSTED
    assert step.attempts == 2  # retryLimit defaults to one retry


def test_goto_and_end_actions_with_criteria():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        extras={
            "successActions": [
                {"name": "done", "type": "end", "criteria": [{"condition": "$statusCode == 418"}]}
            ]
        },
        steps=[
            _step(
                "first",
                "op-list",
                0,
                extras={
                    "onSuccess": [
                        {
                            "name": "skip",
                            "type": "goto",
                            "stepId": "third",
                            "criteria": [{"condition": "$statusCode == 200"}],
                        }
                    ]
                },
            ),
            _step("second", "op-owner", 1),
            _step("third", "op-list", 2, extras={"onSuccess": [{"name": "stop", "type": "end"}]}),
        ],
    )
    _plan, report = _run(workflow, mock)
    assert [s.step_id for s in report.steps] == ["first", "third"]
    assert report.steps[0].action.type == "goto" and report.steps[0].action.step_id == "third"
    assert report.steps[1].action.type == "end"
    assert report.not_reached == ["second"]


def test_goto_after_failure_still_fails_the_run():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "check",
                "op-list",
                0,
                success_criteria=[{"condition": "$statusCode == 999"}],
                on_failure=[{"type": "goto", "stepId": "recover"}],
            ),
            _step("recover", "op-list", 1),
        ],
    )
    _plan, report = _run(workflow, mock)
    assert [s.outcome for s in report.steps] == ["failed", "passed"]
    assert report.outcome == "failed"


def test_goto_loop_stops_at_the_step_limit():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step("loop", "op-list", 0, extras={"onSuccess": [{"type": "goto", "stepId": "loop"}]})
        ],
    )
    _plan, report = _run(workflow, mock)
    assert len(mock.requests) == MAX_STEP_EXECUTIONS
    assert report.outcome == "errored"
    assert report.steps[-1].failure_code == CODE_STEP_LIMIT
    ids = [op.case_id for op in evidence_operations(report)]
    assert ids[:2] == ["loop", "loop#2"] and len(set(ids)) == len(ids)
    _evidence(report)


def test_goto_another_workflow_errors_the_step():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "s", "op-list", 0, extras={"onSuccess": [{"type": "goto", "workflowId": "other"}]}
            )
        ],
    )
    _plan, report = _run(workflow, mock)
    assert report.outcome == "errored"
    assert report.steps[0].failure_code == CODE_ACTION_UNSUPPORTED
    _evidence(report)


def test_components_action_reference_is_followed():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "a",
                "op-list",
                0,
                extras={"onSuccess": [{"reference": "$components.successActions.finish"}]},
            ),
            _step("b", "op-list", 1),
        ],
    )
    _plan, report = _run(
        workflow, mock, components={"successActions": {"finish": {"name": "finish", "type": "end"}}}
    )
    assert [s.step_id for s in report.steps] == ["a"]
    assert report.steps[0].action.name == "finish"


def test_unresolvable_request_expression_errors_without_sending():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "s",
                "op-get",
                0,
                parameters=[{"name": "petId", "in": "path", "value": "$inputs.missing"}],
            )
        ],
    )
    _plan, report = _run(workflow, mock)
    assert mock.requests == []
    assert report.steps[0].outcome == "errored"
    assert report.steps[0].failure_code == CODE_EXPRESSION_UNRESOLVED
    _evidence(report)


def test_missing_path_parameter_errors_without_sending():
    mock = PetStoreMock()
    workflow = WorkflowRow(workflow_id="w", steps=[_step("s", "op-get", 0)])
    _plan, report = _run(workflow, mock)
    assert mock.requests == []
    assert "petId" in report.steps[0].failure_message


def test_unreadable_output_fails_the_step():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w", steps=[_step("s", "op-list", 0, outputs={"x": "$response.body#/99/id"})]
    )
    _plan, report = _run(workflow, mock)
    assert report.steps[0].failure_code == CODE_OUTPUT_UNRESOLVED
    _evidence(report)


def test_transport_failure_errors_the_step():
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    workflow = WorkflowRow(workflow_id="w", steps=[_step("s", "op-list", 0)])
    plan = compile_workflow_run(workflow, operations=_OPS)
    client = httpx.Client(transport=httpx.MockTransport(boom))
    report = execute_workflow(
        plan, {}, target=_target(retry_attempts=1), client=client, sleep=lambda _s: None
    )
    assert report.outcome == "errored"
    assert report.steps[0].attempts == 2
    _evidence(report)


def test_request_body_replacements_and_templates():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "create",
                "op-create",
                0,
                extras={
                    "requestBody": {
                        "payload": {
                            "name": "placeholder",
                            "tag": "tag-{$inputs.tag}",
                            "meta": {"n": 0},
                        },
                        "replacements": [
                            {"target": "/name", "value": "$inputs.name"},
                            {"target": "/meta/n", "value": "$inputs.n"},
                        ],
                    }
                },
            )
        ],
    )
    options = ArazzoRunOptions(
        allow_mutating=True, fixtures=[MutatingFixture(operation_key="POST /pets")]
    )
    _plan, report = _run(
        workflow,
        mock,
        options=options,
        inputs={"name": "Bolt", "tag": "x", "n": 3},
        allow_mutating_methods=True,
    )
    assert report.outcome == "passed"
    assert json.loads(mock.requests[0].content) == {
        "name": "Bolt",
        "tag": "tag-x",
        "meta": {"n": 3},
    }
    assert mock.requests[0].headers["Content-Type"] == "application/json"


def test_plan_digest_is_stable_and_input_sensitive():
    plan = compile_workflow_run(_three_step_workflow(), operations=_OPS)
    first = plan_digest(plan, {"status": "available"})
    assert first == plan_digest(plan, {"status": "available"})
    assert first != plan_digest(plan, {"status": "sold"})
    assert first.startswith("sha256:") and len(first) == 71


# ---------------------------------------------------------------------------------------------
# Runtime expressions and criteria
# ---------------------------------------------------------------------------------------------


def _ctx(**fields: Any) -> ExpressionContext:
    base = dict(
        inputs={"user": {"name": "ada"}, "count": 2},
        steps={"login": {"token": "abc", "profile": {"id": 9}}},
        url="http://x/pets",
        method="GET",
        status_code=200,
        request_headers={"Accept": "application/json"},
        request_query={"limit": "5"},
        request_path={"petId": "7"},
        request_body={"a": 1},
        response_headers={"Content-Type": "application/json", "X-Rate": "10"},
        response_body={"items": [{"id": 1, "name": "Rex"}], "ok": True, "a/b": "slash"},
    )
    base.update(fields)
    return ExpressionContext(**base)


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("$url", "http://x/pets"),
        ("$method", "GET"),
        ("$statusCode", 200),
        ("$request.header.accept", "application/json"),
        ("$request.query.limit", "5"),
        ("$request.path.petId", "7"),
        ("$request.body#/a", 1),
        ("$response.header.x-rate", "10"),
        ("$response.body#/items/0/name", "Rex"),
        ("$response.body#/a~1b", "slash"),
        ("$inputs.count", 2),
        ("$inputs.user.name", "ada"),
        ("$inputs.user#/name", "ada"),
        ("$steps.login.outputs.token", "abc"),
        ("$steps.login.outputs.profile#/id", 9),
    ],
)
def test_evaluate_expression(expression: str, expected: Any):
    assert evaluate_expression(expression, _ctx()) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "$response.body#/items/5",
        "$steps.other.outputs.x",
        "$steps.login.token",
        "$inputs.nope",
        "$workflows.other.outputs.x",
        "$sourceDescriptions.pets.url",
        "$request.cookie.x",
        "$nonsense",
        "$response.header.missing",
    ],
)
def test_unresolvable_expressions_raise(expression: str):
    with pytest.raises(ExpressionError):
        evaluate_expression(expression, _ctx())


def test_expressions_before_a_response_raise():
    empty = ExpressionContext()
    for expression in ("$statusCode", "$url", "$method", "$response.body"):
        with pytest.raises(ExpressionError):
            evaluate_expression(expression, empty)


def test_resolve_value_keeps_types_and_fills_templates():
    ctx = _ctx()
    assert resolve_value("$inputs.count", ctx) == 2
    assert resolve_value("Bearer {$steps.login.outputs.token}", ctx) == "Bearer abc"
    assert resolve_value({"a": ["$inputs.count", "plain"]}, ctx) == {"a": [2, "plain"]}
    assert resolve_value(5, ctx) == 5


def test_json_pointer_root_and_errors():
    assert resolve_json_pointer({"a": 1}, "") == {"a": 1}
    assert resolve_json_pointer({"a": 1}, "#/a") == 1
    with pytest.raises(ExpressionError):
        resolve_json_pointer({"a": 1}, "a")
    with pytest.raises(ExpressionError):
        resolve_json_pointer({"a": 1}, "/a/b")


@pytest.mark.parametrize(
    "condition,outcome",
    [
        ("$statusCode == 200", CRITERION_PASSED),
        ("$statusCode != 200", CRITERION_FAILED),
        ("$statusCode >= 200 && $statusCode < 300", CRITERION_PASSED),
        ("$statusCode == 404 || $response.body#/ok == true", CRITERION_PASSED),
        ("!($statusCode == 500)", CRITERION_PASSED),
        ("$response.body#/items/0/name == 'rex'", CRITERION_PASSED),  # case-insensitive
        ("$response.header.X-Rate > 9.5", CRITERION_PASSED),
        ("$response.body#/ok", CRITERION_PASSED),
        ("$response.body#/missing == 1", CRITERION_ERROR),
        ("$statusCode ==", CRITERION_ERROR),
        ("$statusCode == bogus", CRITERION_ERROR),
        ("$response.body#/items < 3", CRITERION_ERROR),
        ("($statusCode == 200", CRITERION_ERROR),
    ],
)
def test_simple_criteria(condition: str, outcome: str):
    assert evaluate_criterion({"condition": condition}, _ctx()).outcome == outcome


def test_simple_criterion_renders_actual_values():
    result = evaluate_criterion({"condition": "$response.body#/items/0/id == 2"}, _ctx())
    assert result.outcome == CRITERION_FAILED
    assert result.expected == "$response.body#/items/0/id == 2"
    assert result.actual == "1 == 2"
    assert "expected" in result.message


def test_string_literal_with_escaped_quote():
    ctx = _ctx(response_body={"name": "O'Neil"})
    assert (
        evaluate_criterion({"condition": "$response.body#/name == 'O''Neil'"}, ctx).outcome
        == CRITERION_PASSED
    )


def test_regex_jsonpath_and_xpath_criteria():
    ctx = _ctx()
    regex = evaluate_criterion(
        {"context": "$response.header.Content-Type", "condition": "json$", "type": "regex"}, ctx
    )
    assert regex.outcome == CRITERION_PASSED and regex.actual == "application/json"
    miss = evaluate_criterion({"context": "$statusCode", "condition": "^5", "type": "regex"}, ctx)
    assert miss.outcome == CRITERION_FAILED and miss.actual == "200"
    jsonpath = evaluate_criterion(
        {
            "context": "$response.body",
            "condition": "$.items[?(@.id == 1)]",
            "type": {"type": "jsonpath", "version": "draft-goessner-dispatch-jsonpath-00"},
        },
        ctx,
    )
    assert jsonpath.outcome == CRITERION_PASSED
    empty = evaluate_criterion(
        {"context": "$response.body", "condition": "$.items[?(@.id == 5)]", "type": "jsonpath"}, ctx
    )
    assert empty.outcome == CRITERION_FAILED
    assert (
        evaluate_criterion(
            {"context": "$response.body", "condition": "/a", "type": "xpath"}, ctx
        ).outcome
        == CRITERION_ERROR
    )
    assert evaluate_criterion({"condition": "x", "type": "regex"}, ctx).outcome == CRITERION_ERROR
    assert (
        evaluate_criterion(
            {"context": "$statusCode", "condition": "(", "type": "regex"}, ctx
        ).outcome
        == CRITERION_ERROR
    )
    assert (
        evaluate_criterion(
            {"context": "$response.body", "condition": "$[?(", "type": "jsonpath"}, ctx
        ).outcome
        == CRITERION_ERROR
    )
    assert evaluate_criterion("not an object", ctx).outcome == CRITERION_ERROR


def test_is_status_condition():
    assert is_status_condition("$statusCode == 200")
    assert not is_status_condition("$statusCode == 200 && $response.body#/ok")


def test_apply_input_defaults_keeps_supplied_values():
    schema = {"properties": {"a": {"default": 1}, "b": {"default": 2}, "c": {}}}
    assert apply_input_defaults(schema, {"a": 5}) == {"a": 5, "b": 2}
    assert validate_inputs({}, {"anything": 1}) == []


# ---------------------------------------------------------------------------------------------
# Service and route
# ---------------------------------------------------------------------------------------------

_TENANT = "11111111-1111-4111-8111-111111111111"
_VERSION = "33333333-3333-4333-8333-333333333333"


def _service_db(workflow: WorkflowRow) -> MagicMock:
    mdb = MagicMock()
    mdb.load_arazzo_workflows.return_value = [workflow]
    mdb.get_arazzo_step_operations.return_value = _OPS
    mdb.get_arazzo_components.return_value = {}
    return mdb


def test_service_runs_and_records_evidence():
    from app import arazzo_workflow_run_service as service
    from app.verification_evidence_store import TargetActor

    recorded = MagicMock()
    recorded.record = None
    recorded.created = True
    mock = PetStoreMock()
    with patch.object(service, "db", _service_db(_three_step_workflow())), patch.object(
        service, "resolve_target", return_value=_target()
    ), patch.object(service, "record_run", return_value=recorded) as record:
        response = service.run_workflow_against_target(
            _VERSION,
            "adoptPet",
            service.ArazzoWorkflowRunRequest(target_ref="pets-mock"),
            tenant_id=_TENANT,
            actor=TargetActor(),
            client=httpx.Client(transport=httpx.MockTransport(mock)),
        )
    assert response.ok and response.report.outcome == "passed"
    submitted = record.call_args.args[1]
    assert submitted.runner_name == RUNNER_NAME and submitted.suite_case_count == 3
    assert submitted.source["workflow_id"] == "adoptPet"
    assert [op.case_id for op in submitted.operations] == ["findPets", "getPet", "getOwner"]
    validate_run_input(submitted)


def test_service_refuses_mutating_run_without_sending_or_recording():
    from app import arazzo_workflow_run_service as service
    from app.verification_evidence_store import TargetActor

    with patch.object(service, "db", _service_db(_mutating_workflow())), patch.object(
        service, "resolve_target", return_value=_target(allow_mutating_methods=False)
    ), patch.object(service, "record_run") as record:
        response = service.run_workflow_against_target(
            _VERSION,
            "petLifecycle",
            service.ArazzoWorkflowRunRequest(target_ref="pets-mock", inputs={"name": "x"}),
            tenant_id=_TENANT,
            actor=TargetActor(),
            client=MagicMock(),
        )
    assert not response.ok and response.error.code == SKIP_MUTATING_BLOCKED
    assert len(response.refusals) == 2 and response.digest
    record.assert_not_called()


def test_service_refuses_invalid_inputs_before_resolving_the_target():
    from app import arazzo_workflow_run_service as service
    from app.verification_evidence_store import TargetActor

    workflow = _three_step_workflow()
    workflow.inputs = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    with patch.object(service, "db", _service_db(workflow)), patch.object(
        service, "resolve_target"
    ) as resolve:
        response = service.run_workflow_against_target(
            _VERSION,
            "adoptPet",
            service.ArazzoWorkflowRunRequest(target_ref="pets-mock", inputs={"status": 5}),
            tenant_id=_TENANT,
            actor=TargetActor(),
        )
    assert not response.ok and response.error.code == "arazzo-inputs-invalid"
    resolve.assert_not_called()


def test_service_unknown_workflow():
    from app import arazzo_workflow_run_service as service
    from app.verification_evidence_store import TargetActor

    with patch.object(service, "db", _service_db(_three_step_workflow())):
        with pytest.raises(service.WorkflowNotFoundError):
            service.run_workflow_against_target(
                _VERSION,
                "nope",
                service.ArazzoWorkflowRunRequest(target_ref="t"),
                tenant_id=_TENANT,
                actor=TargetActor(),
            )


def test_service_auth_unavailable_is_a_refusal():
    from app import arazzo_workflow_run_service as service
    from app.verification_evidence_store import TargetActor

    target = _target().model_copy(
        update={"auth": TargetAuthReference(kind="env", ref="NOPE_UNSET_VAR", scheme="bearer")}
    )
    with patch.object(service, "db", _service_db(_three_step_workflow())), patch.object(
        service, "resolve_target", return_value=target
    ):
        response = service.run_workflow_against_target(
            _VERSION,
            "adoptPet",
            service.ArazzoWorkflowRunRequest(target_ref="t"),
            tenant_id=_TENANT,
            actor=TargetActor(),
        )
    assert not response.ok and response.error.code == "auth-unavailable"


@pytest.fixture
def route_client():
    from app.auth import validate_authentication
    from app.main import app

    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": "u",
        "auth_method": "jwt",
    }
    with patch("app.arazzo_workflow_routes.enforce_permission", return_value="u") as perm:
        yield TestClient(app), perm
    app.dependency_overrides.clear()


_RUN_URL = f"/v1/workflows/acme/versions/{_VERSION}/workflows/adoptPet/run"


def test_route_runs_and_returns_201(route_client):
    from app.arazzo_workflow_run_service import ArazzoWorkflowRunResponse

    client, perm = route_client
    result = ArazzoWorkflowRunResponse(
        ok=True, version_id=_VERSION, workflow_id="adoptPet", created=True
    )
    with patch("app.arazzo_workflow_routes.db") as mdb, patch(
        "app.arazzo_workflow_routes.run_workflow_against_target", return_value=result
    ) as run:
        mdb.get_version_for_tenant.return_value = {"project_id": "p"}
        res = client.post(_RUN_URL, json={"target_ref": "pets-mock", "inputs": {"status": "sold"}})
    assert res.status_code == 201 and res.json()["ok"] is True
    assert run.call_args.args[:2] == (_VERSION, "adoptPet")
    assert run.call_args.args[2].inputs == {"status": "sold"}
    from app.permissions import Resource

    resources = [call.args[2] for call in perm.call_args_list]
    assert resources == [Resource.VERSIONS, Resource.VERIFICATION_EVIDENCE]


def test_route_refusal_is_200(route_client):
    from app.arazzo_workflow_run_service import ArazzoWorkflowRunResponse

    client, _perm = route_client
    result = ArazzoWorkflowRunResponse(ok=False, version_id=_VERSION, workflow_id="adoptPet")
    with patch("app.arazzo_workflow_routes.db") as mdb, patch(
        "app.arazzo_workflow_routes.run_workflow_against_target", return_value=result
    ):
        mdb.get_version_for_tenant.return_value = {"project_id": "p"}
        res = client.post(_RUN_URL, json={"target_ref": "pets-mock"})
    assert res.status_code == 200 and res.json()["ok"] is False


def test_route_errors(route_client):
    from app.arazzo_workflow_run_service import WorkflowNotFoundError
    from app.verification_target import CODE_NOT_FOUND, TargetValidationError

    client, _perm = route_client
    assert (
        client.post(
            "/v1/workflows/acme/versions/not-a-uuid/workflows/w/run", json={"target_ref": "t"}
        ).status_code
        == 400
    )
    with patch("app.arazzo_workflow_routes.db") as mdb:
        mdb.get_version_for_tenant.return_value = None
        assert client.post(_RUN_URL, json={"target_ref": "t"}).status_code == 404
    for exc, status in (
        (WorkflowNotFoundError("Workflow not found: adoptPet"), 404),
        (TargetValidationError(CODE_NOT_FOUND, "no target"), 404),
        (TargetValidationError("target-disabled", "disabled"), 400),
    ):
        with patch("app.arazzo_workflow_routes.db") as mdb, patch(
            "app.arazzo_workflow_routes.run_workflow_against_target", side_effect=exc
        ):
            mdb.get_version_for_tenant.return_value = {"project_id": "p"}
            assert client.post(_RUN_URL, json={"target_ref": "t"}).status_code == status
    assert client.post(_RUN_URL, json={}).status_code == 422


def test_get_arazzo_components_decodes_and_defaults():
    from app.database import Database

    database = Database.__new__(Database)
    database.execute_query = lambda q, p=None: [{"components": '{"inputs": {}}'}]  # type: ignore[assignment]
    assert database.get_arazzo_components(tenant_id=_TENANT, version_id=_VERSION) == {"inputs": {}}
    database.execute_query = lambda q, p=None: []  # type: ignore[assignment]
    assert database.get_arazzo_components(tenant_id=_TENANT, version_id=_VERSION) == {}


def test_unsendable_header_value_errors_the_step_without_sending():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "s",
                "op-list",
                0,
                parameters=[{"name": "X-Note", "in": "header", "value": "$inputs.note"}],
            )
        ],
    )
    _plan, report = _run(workflow, mock, inputs={"note": "line\nbreak"})
    assert mock.requests == []
    assert report.steps[0].outcome == "errored"
    assert report.steps[0].failure_code == CODE_STEP_INVALID
    _evidence(report)


def test_unresolved_components_action_reference_errors_the_step():
    mock = PetStoreMock()
    workflow = WorkflowRow(
        workflow_id="w",
        steps=[
            _step(
                "a",
                "op-list",
                0,
                extras={"onSuccess": [{"reference": "$components.successActions.missing"}]},
            )
        ],
    )
    _plan, report = _run(workflow, mock)
    assert report.steps[0].failure_code == CODE_ACTION_UNSUPPORTED
    assert "names nothing" in report.steps[0].failure_message
