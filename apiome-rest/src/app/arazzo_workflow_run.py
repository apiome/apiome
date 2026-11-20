"""Run an Arazzo workflow against a verification target — COA-1.7 (#7043).

The contract runner (ECA-2.1) executes independent cases; an Arazzo workflow is a *chain*: each
step's request reads the workflow inputs and earlier steps' outputs, its ``successCriteria``
decide whether it passed, and its ``onSuccess`` / ``onFailure`` actions decide what runs next.
This module compiles a stored workflow into an ordered run and executes it, reusing what
Executable Contract Assurance already ships:

* the request is sent through the ECA-1.2 target's guarded client, with the target's auth
  headers, timeouts and transport-retry policy (:mod:`app.contract_runner` helpers);
* the CTG-4.3 safety model decides, **before a single request goes out**, whether the run may
  send a mutating step at all — the target policy must allow mutating methods, the run must opt
  in, and a :class:`~app.provider_verification.MutatingFixture` must name the step's operation
  (or the step itself through ``case_id``). Any mutating step that fails one of the three refuses
  the whole run: a workflow that stops half-way through a write chain is worse than one that
  never started;
* every executed step becomes one ECA-1.3 operation record whose assertions are the step's
  success criteria with expected-vs-actual values (:func:`evidence_operations`).

Control flow follows the specification: without actions a passing step moves to the next step
and a failing step ends the run as failed; ``end`` stops, ``goto`` jumps to a step of this
workflow, ``retry`` re-sends the step up to ``retryLimit`` times (default 1) after
``retryAfter`` seconds (capped at :data:`MAX_RETRY_AFTER_SECONDS`). A step that calls another
workflow (``workflowId``), or an action that jumps to one, is not executed — the run is refused
with ``arazzo-step-workflow-unsupported`` / ends ``errored``, never reported as passed. A step
with no ``successCriteria`` is judged by an implicit ``$statusCode`` 2XX check, so a ``500`` is
never a silent pass.

Everything here except :func:`execute_workflow` (which sends HTTP through the client it is
given) is pure; loading, target resolution and evidence recording live in
:mod:`app.arazzo_workflow_run_service`.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .arazzo_runtime_expression import (
    CRITERION_PASSED,
    CriterionResult,
    ExpressionContext,
    ExpressionError,
    evaluate_criterion,
    evaluate_expression,
    is_status_condition,
    render_value,
    resolve_json_pointer,
    resolve_value,
)
from .arazzo_workflow_persistence import STATUS_RESOLVED, WorkflowRow, WorkflowStepRow
from .contract_runner import (
    _FIELD_LIMIT,
    _MESSAGE_LIMIT,
    _SUBJECT_LIMIT,
    MUTATING_METHODS,
    _bounded,
    _is_transport_failure,
    _join_url,
    _parse_json_body,
)
from .provider_verification import (
    FIXTURE_CODE_NOT_MUTATING,
    FIXTURE_CODE_UNMATCHED,
    SKIP_MUTATING_BLOCKED,
    SKIP_MUTATING_FIXTURE_MISSING,
    FixtureFinding,
    MutatingFixture,
    TargetIdentity,
    _substitute_path,
)
from .schema_instance_validation import validate_json_instance
from .verification_evidence import (
    ASSERTION_KIND_CUSTOM,
    ASSERTION_KIND_STATUS_CODE,
    ASSERTION_OUTCOME_FAILED,
    ASSERTION_OUTCOME_PASSED,
    OPERATION_OUTCOME_ERRORED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    RUN_OUTCOME_ERRORED,
    RUN_OUTCOME_FAILED,
    RUN_OUTCOME_PASSED,
    AssertionInput,
    OperationResultInput,
)
from .verification_target import ResolvedTarget

__all__ = [
    "CASE_SOURCE_ARAZZO_STEP",
    "CODE_ACTION_UNSUPPORTED",
    "CODE_CRITERIA_FAILED",
    "CODE_EXPRESSION_UNRESOLVED",
    "CODE_INPUTS_INVALID",
    "CODE_OUTPUT_UNRESOLVED",
    "CODE_RETRIES_EXHAUSTED",
    "CODE_STEP_INVALID",
    "CODE_STEP_LIMIT",
    "CODE_STEP_UNRESOLVED",
    "CODE_STEP_WORKFLOW_UNSUPPORTED",
    "MAX_RETRY_AFTER_SECONDS",
    "MAX_STEP_EXECUTIONS",
    "RUNNER_NAME",
    "RUNNER_SCHEMA_VERSION",
    "RUNNER_VERSION",
    "ArazzoActionTaken",
    "ArazzoCriterionResult",
    "ArazzoRunOptions",
    "ArazzoRunRefusal",
    "ArazzoStepResult",
    "ArazzoWorkflowRunReport",
    "CompiledStep",
    "WorkflowRunPlan",
    "apply_input_defaults",
    "compile_workflow_run",
    "evidence_operations",
    "execute_workflow",
    "plan_mutating_steps",
    "validate_inputs",
]

#: Runner identity written into ECA-1.3 evidence, so a workflow run is distinguishable from a
#: contract run or a provider verification in the same evidence table.
RUNNER_NAME = "apiome-arazzo-runner"
RUNNER_VERSION = "1"
#: Version of the compiled-plan shape hashed into the digest.
RUNNER_SCHEMA_VERSION = 1

#: ``case_source`` of every evidence record a workflow run writes.
CASE_SOURCE_ARAZZO_STEP = "arazzo_step"

#: Hard cap on step executions in one run (``goto`` loops and retries included).
MAX_STEP_EXECUTIONS = 100
#: Cap on one ``retryAfter`` wait, in seconds: a verification run is a check, not a scheduler.
MAX_RETRY_AFTER_SECONDS = 10.0

#: A step whose target never resolved to an operation in this tenant.
CODE_STEP_UNRESOLVED = "arazzo-step-unresolved"
#: A step (or action) that calls another workflow — not executed by this runner.
CODE_STEP_WORKFLOW_UNSUPPORTED = "arazzo-step-workflow-unsupported"
#: A step whose parameters or request body cannot be sent as written.
CODE_STEP_INVALID = "arazzo-step-invalid"
#: The run's inputs do not satisfy the workflow's ``inputs`` schema.
CODE_INPUTS_INVALID = "arazzo-inputs-invalid"
#: A runtime expression in the request could not be evaluated, so nothing was sent.
CODE_EXPRESSION_UNRESOLVED = "arazzo-expression-unresolved"
#: At least one success criterion did not hold (or could not be evaluated).
CODE_CRITERIA_FAILED = "arazzo-criteria-failed"
#: A step output expression could not be evaluated against the response.
CODE_OUTPUT_UNRESOLVED = "arazzo-output-unresolved"
#: A ``retry`` action ran out of attempts.
CODE_RETRIES_EXHAUSTED = "arazzo-retries-exhausted"
#: An action this runner does not execute (``goto`` another workflow, an unknown type).
CODE_ACTION_UNSUPPORTED = "arazzo-action-unsupported"
#: :data:`MAX_STEP_EXECUTIONS` was reached.
CODE_STEP_LIMIT = "arazzo-step-limit"

#: The step's parameter locations this runner sends.
_LOCATIONS = ("path", "query", "header", "cookie")
#: Action type standing in for a ``$components`` action reference that names nothing.
_UNRESOLVED_REFERENCE = "unresolved-reference"
#: Status check applied to a step that declares no success criteria.
_IMPLICIT_CRITERION = {"condition": "$statusCode >= 200 && $statusCode < 300"}


# =============================================================================================
# Request / report models
# =============================================================================================


class ArazzoRunOptions(BaseModel):
    """How much of the target a workflow run may touch — the CTG-4.3 rule, per step."""

    model_config = ConfigDict(extra="forbid")

    allow_mutating: bool = Field(
        default=False,
        description=(
            "Opt in to sending mutating steps (`POST`/`PUT`/`PATCH`/`DELETE`). Off by default. "
            "Even when on, a mutating step runs only when a fixture names its operation (or the "
            "step, through `case_id`), and never when the target policy forbids mutating methods."
        ),
    )
    fixtures: List[MutatingFixture] = Field(
        default_factory=list,
        description=(
            "Per-operation permission for mutating steps. `case_id` narrows a fixture to one "
            "`stepId`. Parameters and a body in the fixture override what the step sends."
        ),
        max_length=100,
    )


class ArazzoRunRefusal(BaseModel):
    """Why the run was refused before any request was sent."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable code (`mutating-method-blocked`, `arazzo-step-unresolved`, …).")
    message: str = Field(description="What blocked the run and how to unblock it.")
    step_id: Optional[str] = Field(default=None, description="The step concerned, when there is one.")
    operation_key: Optional[str] = Field(
        default=None, description="The step's operation (`POST /pets`), when it resolved."
    )


class ArazzoCriterionResult(BaseModel):
    """One success criterion's verdict, with the expected and the observed value."""

    model_config = ConfigDict(extra="forbid")

    condition: str = Field(description="The condition as written.")
    type: str = Field(description="`simple`, `regex`, `jsonpath` or `xpath`.")
    context: Optional[str] = Field(default=None, description="The context expression, when declared.")
    outcome: str = Field(description="`passed`, `failed` or `error` (could not be evaluated).")
    expected: str = Field(description="What the workflow requires.")
    actual: Optional[str] = Field(
        default=None,
        description=(
            "What was observed: the condition with each expression replaced by its value, or the "
            "context value a regex/JSONPath was applied to."
        ),
    )
    message: Optional[str] = Field(default=None, description="Why it failed, when it did.")
    implicit: bool = Field(
        default=False,
        description="True for the 2XX status check applied to a step with no criteria of its own.",
    )


class ArazzoActionTaken(BaseModel):
    """What the run did after a step."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(description="`next`, `end`, `goto` or `retry`.")
    name: Optional[str] = Field(default=None, description="The action's `name`, when declared.")
    step_id: Optional[str] = Field(default=None, description="The `goto` target step.")


class ArazzoStepResult(BaseModel):
    """One executed step: the request sent, the criteria judged, the outputs captured."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(description="The step's `stepId`.")
    execution: int = Field(description="1 for the first time this step ran, 2 after a `goto` back, …")
    operation_key: str = Field(description="The operation the step called (`GET /pets/{petId}`).")
    method: str = Field(description="HTTP method sent.")
    path: str = Field(description="Request path sent (path parameters substituted).")
    query: Dict[str, str] = Field(default_factory=dict, description="Query parameters sent.")
    outcome: str = Field(description="`passed`, `failed` or `errored`.")
    failure_code: Optional[str] = Field(default=None, description="Stable code when not passed.")
    failure_message: Optional[str] = Field(default=None, description="Why it did not pass.")
    status_code: Optional[int] = Field(default=None, description="Status received.")
    attempts: int = Field(default=1, description="Sends, including `retry` actions.")
    duration_ms: int = Field(default=0, description="Time spent on the step, retries included.")
    fixture_applied: bool = Field(
        default=False, description="Whether a mutating fixture supplied part of the request."
    )
    criteria: List[ArazzoCriterionResult] = Field(
        default_factory=list, description="Every success criterion, in declaration order."
    )
    outputs: Dict[str, Any] = Field(
        default_factory=dict, description="The step's outputs, captured when it passed."
    )
    action: Optional[ArazzoActionTaken] = Field(
        default=None, description="What the run did next."
    )
    started_at: datetime = Field(description="When the step's first send began.")
    finished_at: datetime = Field(description="When the step's last send finished.")


class ArazzoWorkflowRunReport(BaseModel):
    """The per-step report of one workflow run."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(description="The workflow's `workflowId`.")
    outcome: str = Field(
        description=(
            "`passed` when every executed step passed; `failed` when a step's criteria failed; "
            "`errored` when a step could not be sent or the run hit a runner limit."
        )
    )
    digest: str = Field(description="`sha256:` digest of the compiled run plan and its inputs.")
    target: TargetIdentity = Field(description="The deployment the run was sent to.")
    started_at: datetime = Field(description="When the run began.")
    finished_at: datetime = Field(description="When the run finished.")
    steps: List[ArazzoStepResult] = Field(
        default_factory=list, description="Every executed step, in execution order."
    )
    not_reached: List[str] = Field(
        default_factory=list,
        description="Steps the run never executed (it ended or jumped past them), in source order.",
    )
    outputs: Dict[str, Any] = Field(
        default_factory=dict, description="The workflow outputs, evaluated when the run passed."
    )
    output_errors: List[str] = Field(
        default_factory=list, description="Workflow outputs that could not be evaluated."
    )
    counts: Dict[str, int] = Field(
        default_factory=dict,
        description="`steps` (declared), `executed`, `passed`, `failed`, `errored`.",
    )


# =============================================================================================
# Compilation
# =============================================================================================


@dataclass
class CompiledStep:
    """One step, resolved to an operation and ready to be sent.

    Attributes:
        step_id: The step's ``stepId``.
        order_index: Its position in the workflow.
        method: HTTP method of the resolved operation, upper-cased.
        path_template: Route template of the resolved operation.
        parameters: Merged parameters (workflow-level first, step-level override), each with
            ``name``, ``in`` and ``value`` (components references already resolved).
        request_body: The step's ``requestBody`` object, or ``None``.
        success_criteria: The step's criteria (the implicit 2XX check when it declares none).
        implicit_criteria: Whether ``success_criteria`` is the implicit check.
        on_success: Success actions — the step's own, then the workflow's not overridden by name.
        on_failure: Failure actions, combined the same way.
        outputs: ``{name: expression}``.
        fixture: The mutating fixture the safety plan matched, once planned.
    """

    step_id: str
    order_index: int
    method: str
    path_template: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    request_body: Optional[Dict[str, Any]] = None
    success_criteria: List[Any] = field(default_factory=list)
    implicit_criteria: bool = False
    on_success: List[Any] = field(default_factory=list)
    on_failure: List[Any] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    fixture: Optional[MutatingFixture] = None

    @property
    def operation_key(self) -> str:
        """The canonical operation key (``POST /pets``) the step calls."""
        return f"{self.method} {self.path_template}"

    @property
    def mutating(self) -> bool:
        """Whether sending the step can change the target's state."""
        return self.method in MUTATING_METHODS


@dataclass
class WorkflowRunPlan:
    """A workflow compiled into an ordered run.

    Attributes:
        workflow_id: The workflow's ``workflowId``.
        steps: Compiled steps in source order (empty when refused).
        inputs_schema: The workflow ``inputs`` schema, ``$ref`` to ``components.inputs`` resolved.
        outputs: Workflow ``outputs`` expressions.
        components: The document's ``components``.
        refusals: Why the run may not start; non-empty means nothing will be sent.
        fixture_findings: Fixtures the safety plan could not use.
    """

    workflow_id: str
    steps: List[CompiledStep] = field(default_factory=list)
    inputs_schema: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    components: Dict[str, Any] = field(default_factory=dict)
    refusals: List[ArazzoRunRefusal] = field(default_factory=list)
    fixture_findings: List[FixtureFinding] = field(default_factory=list)

    def step_index(self, step_id: str) -> Optional[int]:
        """Position of ``step_id`` in :attr:`steps`, or ``None``."""
        for index, step in enumerate(self.steps):
            if step.step_id == step_id:
                return index
        return None


def _list(value: Any) -> List[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return list(value) if isinstance(value, list) else []


def _mapping(value: Any) -> Dict[str, Any]:
    """Return ``value`` when it is a mapping, else an empty dict."""
    return dict(value) if isinstance(value, Mapping) else {}


def _component(components: Mapping[str, Any], reference: str) -> Any:
    """Resolve ``$components.KIND.NAME`` (or ``#/components/KIND/NAME``) to its value.

    Raises:
        ExpressionError: When the reference names nothing.
    """
    if reference.startswith("#/components/"):
        return resolve_json_pointer({"components": dict(components)}, reference)
    return evaluate_expression(reference, ExpressionContext(components=dict(components)))


def _resolve_parameter(raw: Any, components: Mapping[str, Any]) -> Dict[str, Any]:
    """Turn a Parameter Object or a Reusable Object into ``{name, in, value}``.

    Raises:
        ValueError: When the parameter cannot be sent (no name, no location, a bad reference).
    """
    if not isinstance(raw, Mapping):
        raise ValueError("a parameter must be an object")
    parameter = dict(raw)
    if isinstance(parameter.get("reference"), str):
        try:
            target = _component(components, parameter["reference"])
        except ExpressionError as exc:
            raise ValueError(str(exc)) from exc
        if not isinstance(target, Mapping):
            raise ValueError(f"{parameter['reference']} is not a parameter object")
        resolved = dict(target)
        if "value" in parameter:
            resolved["value"] = parameter["value"]
        parameter = resolved
    name = parameter.get("name")
    location = parameter.get("in")
    if not isinstance(name, str) or not name:
        raise ValueError("a parameter has no name")
    if location not in _LOCATIONS:
        raise ValueError(f"parameter {name!r} has no supported 'in' (path, query, header, cookie)")
    if "value" not in parameter:
        raise ValueError(f"parameter {name!r} has no value")
    return {"name": name, "in": location, "value": parameter["value"]}


def _merge_parameters(
    workflow_level: Sequence[Dict[str, Any]], step_level: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Apply workflow-level parameters to a step; a step parameter with the same name+in wins."""
    seen = {(p["name"], p["in"]) for p in step_level}
    merged = [p for p in workflow_level if (p["name"], p["in"]) not in seen]
    return merged + list(step_level)


def _merge_actions(step_actions: Sequence[Any], workflow_actions: Sequence[Any]) -> List[Any]:
    """Step actions first, then workflow actions the step does not override by ``name``."""
    names = {a.get("name") for a in step_actions if isinstance(a, Mapping) and a.get("name")}
    inherited = [
        a for a in workflow_actions if not (isinstance(a, Mapping) and a.get("name") in names)
    ]
    return list(step_actions) + inherited


def _inputs_schema(workflow: WorkflowRow, components: Mapping[str, Any]) -> Dict[str, Any]:
    """The workflow ``inputs`` schema, following a ``$ref`` into ``components.inputs``."""
    schema = _mapping(workflow.inputs)
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/components/"):
        try:
            target = _component(components, reference)
        except ExpressionError:
            return schema
        return _mapping(target)
    return schema


def compile_workflow_run(
    workflow: WorkflowRow,
    *,
    operations: Mapping[str, Mapping[str, Any]],
    components: Optional[Mapping[str, Any]] = None,
) -> WorkflowRunPlan:
    """Compile a stored workflow into an ordered run plan.

    Args:
        workflow: The workflow row (with its ordered steps).
        operations: Summaries of the operations its steps resolved to, keyed by
            ``path_operation.id`` (``method`` and ``path`` are read).
        components: The Arazzo document's ``components`` object.

    Returns:
        The plan. A step that cannot be sent — unresolved, calling another workflow, or with an
        unsendable parameter — becomes a refusal instead of a compiled step, and every refusal is
        collected so the caller sees them all at once.
    """
    comps = _mapping(components)
    extras = _mapping(workflow.extras)
    plan = WorkflowRunPlan(
        workflow_id=workflow.workflow_id,
        inputs_schema=_inputs_schema(workflow, comps),
        outputs=_mapping(workflow.outputs),
        components=comps,
    )

    workflow_parameters: List[Dict[str, Any]] = []
    for raw in _list(extras.get("parameters")):
        try:
            workflow_parameters.append(_resolve_parameter(raw, comps))
        except ValueError as exc:
            plan.refusals.append(
                ArazzoRunRefusal(code=CODE_STEP_INVALID, message=f"workflow parameter: {exc}")
            )

    for step in sorted(workflow.steps, key=lambda s: s.order_index):
        compiled = _compile_step(step, operations, comps, workflow_parameters, extras, plan)
        if compiled is not None:
            plan.steps.append(compiled)
    if not workflow.steps:
        plan.refusals.append(
            ArazzoRunRefusal(code=CODE_STEP_INVALID, message="the workflow has no steps to run")
        )
    return plan


def _compile_step(
    step: WorkflowStepRow,
    operations: Mapping[str, Mapping[str, Any]],
    components: Mapping[str, Any],
    workflow_parameters: Sequence[Dict[str, Any]],
    workflow_extras: Mapping[str, Any],
    plan: WorkflowRunPlan,
) -> Optional[CompiledStep]:
    """Compile one step, or record why it cannot be sent on ``plan.refusals``."""
    step_extras = _mapping(step.extras)
    if isinstance(step_extras.get("workflowId"), str) and step_extras["workflowId"]:
        plan.refusals.append(
            ArazzoRunRefusal(
                code=CODE_STEP_WORKFLOW_UNSUPPORTED,
                step_id=step.step_id,
                message=(
                    f"step {step.step_id!r} calls workflow {step_extras['workflowId']!r}; running "
                    "a nested workflow is not supported — run that workflow on its own."
                ),
            )
        )
        return None

    operation = (
        operations.get(step.resolved_path_operation_id)
        if step.resolved_path_operation_id
        else None
    )
    if step.resolution_status != STATUS_RESOLVED or not operation:
        target = step.operation_ref or step.operation_id or "(no target)"
        plan.refusals.append(
            ArazzoRunRefusal(
                code=CODE_STEP_UNRESOLVED,
                step_id=step.step_id,
                message=(
                    f"step {step.step_id!r} targets {target}, which did not resolve to an "
                    f"operation in this tenant ({step.resolution_reason or step.resolution_status}). "
                    "Import its source description, then re-import the workflow."
                ),
            )
        )
        return None

    try:
        step_parameters = [_resolve_parameter(raw, components) for raw in _list(step.parameters)]
    except ValueError as exc:
        plan.refusals.append(
            ArazzoRunRefusal(
                code=CODE_STEP_INVALID, step_id=step.step_id, message=f"step {step.step_id!r}: {exc}"
            )
        )
        return None

    criteria = _list(step.success_criteria)
    return CompiledStep(
        step_id=step.step_id,
        order_index=step.order_index,
        method=str(operation.get("method") or "GET").upper(),
        path_template=str(operation.get("path") or "/"),
        parameters=_merge_parameters(workflow_parameters, step_parameters),
        request_body=_mapping(step_extras.get("requestBody")) or None,
        success_criteria=criteria or [dict(_IMPLICIT_CRITERION)],
        implicit_criteria=not criteria,
        on_success=_merge_actions(
            _list(step_extras.get("onSuccess")), _list(workflow_extras.get("successActions"))
        ),
        on_failure=_merge_actions(
            _list(step.on_failure), _list(workflow_extras.get("failureActions"))
        ),
        outputs=_mapping(step.outputs),
    )


# =============================================================================================
# Safety — which steps may be sent (CTG-4.3)
# =============================================================================================


def plan_mutating_steps(
    plan: WorkflowRunPlan, options: ArazzoRunOptions, *, target_allows_mutating: bool
) -> None:
    """Apply the CTG-4.3 rule to every mutating step, recording refusals on ``plan``.

    ============================================  ===========================================
    Step                                          Decision
    ============================================  ===========================================
    Safe method (``GET``/``HEAD``/``OPTIONS``)    runs as written
    Mutating, target policy forbids it            refused ``mutating-method-blocked``
    Mutating, run did not opt in                  refused ``mutating-method-blocked``
    Mutating, opted in, no matching fixture       refused ``mutating-fixture-missing``
    Mutating, opted in, fixture matches           runs, fixture values override the step's
    ============================================  ===========================================

    The target policy is checked first and cannot be overridden. A fixture that matched no
    mutating step is reported on ``plan.fixture_findings`` rather than silently dropped.

    Args:
        plan: The compiled plan; ``fixture`` is set on each step a fixture unlocked.
        options: The run's opt-in and fixtures.
        target_allows_mutating: The ECA-1.2 target policy's ``allow_mutating_methods``.
    """
    by_operation: Dict[str, MutatingFixture] = {}
    by_step: Dict[Tuple[str, str], MutatingFixture] = {}
    for fixture in options.fixtures:
        if fixture.case_id:
            by_step[(fixture.operation_key, fixture.case_id)] = fixture
        else:
            by_operation[fixture.operation_key] = fixture
    used: set = set()

    for step in plan.steps:
        if not step.mutating:
            continue
        fixture = by_step.get((step.operation_key, step.step_id)) or by_operation.get(
            step.operation_key
        )
        if not target_allows_mutating:
            code = SKIP_MUTATING_BLOCKED
            message = (
                f"step {step.step_id!r} sends {step.operation_key}; the verification target's "
                "policy has allow_mutating_methods=false, which a run cannot override."
            )
        elif not options.allow_mutating:
            code = SKIP_MUTATING_BLOCKED
            message = (
                f"step {step.step_id!r} sends {step.operation_key}; this run did not opt in to "
                "mutating methods (allow_mutating=false)."
            )
        elif fixture is None:
            code = SKIP_MUTATING_FIXTURE_MISSING
            message = (
                f"step {step.step_id!r} sends {step.operation_key}; the run opted in but supplied "
                f"no fixture for {step.operation_key!r}. Opting in is a permission, not a payload."
            )
        else:
            step.fixture = fixture
            used.add(id(fixture))
            continue
        if fixture is not None:
            used.add(id(fixture))
        plan.refusals.append(
            ArazzoRunRefusal(
                code=code, message=message, step_id=step.step_id, operation_key=step.operation_key
            )
        )

    methods = {step.operation_key: step.method for step in plan.steps}
    for fixture in options.fixtures:
        if id(fixture) in used:
            continue
        method = fixture.operation_key.split(" ", 1)[0].upper()
        if fixture.operation_key in methods and method not in MUTATING_METHODS:
            code, message = (
                FIXTURE_CODE_NOT_MUTATING,
                f"{fixture.operation_key} is not a mutating operation; a fixture only unlocks writes.",
            )
        else:
            code, message = (
                FIXTURE_CODE_UNMATCHED,
                f"no mutating step of workflow {plan.workflow_id!r} calls "
                f"{fixture.operation_key!r}"
                + (f" as step {fixture.case_id!r}" if fixture.case_id else "")
                + ".",
            )
        plan.fixture_findings.append(
            FixtureFinding(
                code=code,
                message=message,
                operation_key=fixture.operation_key,
                case_id=fixture.case_id,
            )
        )


# =============================================================================================
# Inputs and digest
# =============================================================================================


def apply_input_defaults(schema: Mapping[str, Any], inputs: Mapping[str, Any]) -> Dict[str, Any]:
    """Fill top-level ``properties`` defaults the caller did not supply.

    Args:
        schema: The workflow ``inputs`` schema.
        inputs: The caller's inputs.

    Returns:
        A new dict: the caller's inputs plus every property default not already set.
    """
    filled = dict(inputs)
    for name, prop in _mapping(schema.get("properties")).items():
        if name not in filled and isinstance(prop, Mapping) and "default" in prop:
            filled[name] = prop["default"]
    return filled


def validate_inputs(schema: Mapping[str, Any], inputs: Mapping[str, Any]) -> List[str]:
    """Check the run's inputs against the workflow's ``inputs`` schema.

    Args:
        schema: The workflow ``inputs`` schema (empty means anything goes).
        inputs: The inputs, defaults applied.

    Returns:
        One message per violation (``/pointer: message``); empty when they conform.
    """
    if not schema:
        return []
    result = validate_json_instance(dict(schema), dict(inputs))
    if result.valid is not False:
        return []
    messages = [f"{finding.pointer or '/'}: {finding.message}" for finding in result.findings]
    return messages or ["the inputs do not satisfy the workflow's inputs schema"]


def plan_digest(plan: WorkflowRunPlan, inputs: Mapping[str, Any]) -> str:
    """``sha256:`` digest of what the run will send: the compiled steps plus the inputs.

    Two runs with the same digest sent the same requests in the same order (up to what earlier
    responses fed into later steps). Input *values* are hashed, never stored.

    Args:
        plan: The compiled plan.
        inputs: The inputs, defaults applied.

    Returns:
        ``sha256:<64 hex>``.
    """
    canonical = {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "workflow_id": plan.workflow_id,
        "steps": [
            {
                "step_id": step.step_id,
                "operation_key": step.operation_key,
                "parameters": step.parameters,
                "request_body": step.request_body,
                "success_criteria": step.success_criteria,
                "on_success": step.on_success,
                "on_failure": step.on_failure,
                "outputs": step.outputs,
                "fixture": step.fixture.model_dump(mode="json") if step.fixture else None,
            }
            for step in plan.steps
        ],
        "outputs": plan.outputs,
        "inputs": dict(inputs),
    }
    data = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


# =============================================================================================
# Execution
# =============================================================================================


@dataclass
class _BuiltRequest:
    """The request one step sends, after expressions and the fixture were applied."""

    method: str
    path: str
    path_values: Dict[str, str]
    query: Dict[str, str]
    headers: Dict[str, str]
    has_body: bool
    body: Any
    media_type: Optional[str]


def _wire(value: Any) -> str:
    """Serialise a resolved parameter value for the wire (strings bare, booleans lower-case)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value if isinstance(value, str) else render_value(value, 10_000)


def _set_pointer(document: Any, pointer: str, value: Any) -> Any:
    """Return ``document`` with the value at an RFC 6901 pointer replaced (``-`` appends).

    Raises:
        ExpressionError: When the pointer's parent does not exist in the payload.
    """
    text = pointer[1:] if pointer.startswith("#") else pointer
    if text in ("", "/"):
        return value
    segments = [s.replace("~1", "/").replace("~0", "~") for s in text.split("/")[1:]]
    parent = document
    for segment in segments[:-1]:
        if isinstance(parent, dict) and segment in parent:
            parent = parent[segment]
        elif isinstance(parent, list) and segment.isdigit() and int(segment) < len(parent):
            parent = parent[int(segment)]
        else:
            raise ExpressionError(f"replacement target {pointer!r} does not exist in the payload")
    last = segments[-1]
    if isinstance(parent, dict):
        parent[last] = value
    elif isinstance(parent, list) and last.isdigit() and int(last) < len(parent):
        parent[int(last)] = value
    elif isinstance(parent, list) and last == "-":
        parent.append(value)
    else:
        raise ExpressionError(f"replacement target {pointer!r} does not exist in the payload")
    return document


def _build_step_request(step: CompiledStep, context: ExpressionContext) -> _BuiltRequest:
    """Resolve a step's parameters and body, then apply its fixture.

    Raises:
        ExpressionError: When an expression cannot be evaluated or a path parameter is missing.
    """
    values: Dict[str, Dict[str, str]] = {location: {} for location in _LOCATIONS}
    for parameter in step.parameters:
        values[parameter["in"]][parameter["name"]] = _wire(
            resolve_value(parameter["value"], context)
        )

    has_body = False
    body: Any = None
    media_type: Optional[str] = None
    if step.request_body is not None:
        has_body = "payload" in step.request_body
        body = resolve_value(json.loads(json.dumps(step.request_body.get("payload"))), context)
        for replacement in _list(step.request_body.get("replacements")):
            if not isinstance(replacement, Mapping) or not isinstance(replacement.get("target"), str):
                raise ExpressionError("a payload replacement needs a string target")
            body = _set_pointer(
                body, replacement["target"], resolve_value(replacement.get("value"), context)
            )
        content_type = step.request_body.get("contentType")
        media_type = content_type if isinstance(content_type, str) and content_type else None

    fixture = step.fixture
    if fixture is not None:
        for location, supplied in (
            ("path", fixture.path_parameters),
            ("query", fixture.query_parameters),
            ("header", fixture.headers),
        ):
            for name, value in supplied.items():
                values[location][name] = str(value)
        if fixture.declares_body():
            has_body = fixture.sends_body()
            body = fixture.body if has_body else None
            media_type = fixture.media_type or media_type

    path = _substitute_path(step.path_template, values["path"], "")
    if not path:
        missing = sorted(
            name
            for name in _placeholders(step.path_template)
            if name not in values["path"]
        )
        raise ExpressionError(
            f"path parameter(s) {', '.join(missing) or '?'} of {step.path_template} have no value"
        )
    headers = dict(values["header"])
    if values["cookie"]:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in values["cookie"].items())
    return _BuiltRequest(
        method=step.method,
        path=path,
        path_values=values["path"],
        query=values["query"],
        headers=headers,
        has_body=has_body,
        body=body,
        media_type=(media_type or "application/json") if has_body else None,
    )


def _placeholders(template: str) -> List[str]:
    """Names of the ``{placeholders}`` in a route template."""
    names: List[str] = []
    rest = template
    while "{" in rest:
        _, _, tail = rest.partition("{")
        name, closed, rest = tail.partition("}")
        if not closed:
            break
        names.append(name)
    return names


def _httpx_request(built: _BuiltRequest, base_url: str, auth_headers: Mapping[str, str]) -> httpx.Request:
    """Turn a built step request into an httpx request against the target.

    Raises:
        ValueError: When a header name or value carries a line break — a value an expression read
            from a response must never be able to inject a header of its own.
    """
    for name, value in built.headers.items():
        if any(ch in f"{name}{value}" for ch in "\r\n"):
            raise ValueError(f"header {name!r} contains a line break")
    headers = {**built.headers, **auth_headers}
    content: Optional[bytes] = None
    if built.has_body:
        media = built.media_type or "application/json"
        headers.setdefault("Content-Type", media)
        if isinstance(built.body, str):
            content = built.body.encode("utf-8")
        elif media.startswith("application/x-www-form-urlencoded") and isinstance(built.body, Mapping):
            content = urlencode({k: _wire(v) for k, v in built.body.items()}).encode("utf-8")
        else:
            content = json.dumps(built.body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return httpx.Request(
        built.method,
        _join_url(base_url, built.path),
        params=built.query or None,
        headers=headers,
        content=content,
    )


def _criterion_model(result: CriterionResult) -> ArazzoCriterionResult:
    """Copy a :class:`CriterionResult` into its report model."""
    return ArazzoCriterionResult(
        condition=result.condition,
        type=result.type,
        context=result.context,
        outcome=result.outcome,
        expected=result.expected,
        actual=result.actual,
        message=result.message,
        implicit=result.implicit,
    )


def _send(
    client: httpx.Client, request: httpx.Request, target: ResolvedTarget, sleep: Callable[[float], None]
) -> Tuple[Optional[httpx.Response], int, Optional[Tuple[str, str]]]:
    """Send with the target's transport-retry policy (never retrying a received response).

    Returns:
        ``(response, attempts, error)`` — ``error`` is ``(code, message)`` when nothing came back.
    """
    max_attempts = 1 + max(0, int(target.policy.retry_attempts))
    backoff_s = max(0, int(target.policy.retry_backoff_ms)) / 1000.0
    attempts = 0
    while True:
        attempts += 1
        try:
            return client.send(request), attempts, None
        except Exception as exc:  # noqa: BLE001 - classified per attempt
            is_transport, code, message = _is_transport_failure(exc)
            if not is_transport or attempts >= max_attempts:
                return None, attempts, (code, message)
            if backoff_s:
                sleep(backoff_s)


def _choose_action(
    actions: Sequence[Any], context: ExpressionContext, components: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """The first action whose criteria all hold, with a components reference resolved.

    Returns:
        The action object, or ``None`` when no action applies (the default behaviour follows).
    """
    for raw in actions:
        action = _mapping(raw)
        if isinstance(action.get("reference"), str):
            try:
                action = _mapping(_component(components, action["reference"]))
            except ExpressionError:
                return {"type": _UNRESOLVED_REFERENCE, "name": raw.get("reference")}
        criteria = _list(action.get("criteria"))
        if all(evaluate_criterion(c, context).outcome == CRITERION_PASSED for c in criteria):
            return action
    return None


def _response_context(
    base: ExpressionContext, built: _BuiltRequest, request: httpx.Request, response: httpx.Response
) -> ExpressionContext:
    """The evaluation context for one step's criteria and outputs."""
    return ExpressionContext(
        inputs=base.inputs,
        steps=base.steps,
        components=base.components,
        url=str(request.url),
        method=built.method,
        status_code=response.status_code,
        request_headers=dict(built.headers),
        request_query=dict(built.query),
        request_path=dict(built.path_values),
        request_body=built.body if built.has_body else None,
        response_headers={k: v for k, v in response.headers.items()},
        response_body=_parse_json_body(response),
    )


def _run_step(
    step: CompiledStep,
    execution: int,
    base: ExpressionContext,
    *,
    target: ResolvedTarget,
    client: httpx.Client,
    auth_headers: Mapping[str, str],
    sleep: Callable[[float], None],
) -> Tuple[ArazzoStepResult, Optional[ExpressionContext]]:
    """Send one step and judge it.

    Returns:
        ``(result, context)`` — ``context`` is the response context the step's actions are chosen
        in, or ``None`` when nothing was received.
    """
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    def _result(**values: Any) -> ArazzoStepResult:
        return ArazzoStepResult(
            step_id=step.step_id,
            execution=execution,
            operation_key=step.operation_key,
            method=step.method,
            fixture_applied=step.fixture is not None,
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((time.perf_counter() - t0) * 1000),
            **values,
        )

    try:
        built = _build_step_request(step, base)
    except ExpressionError as exc:
        return (
            _result(
                path=step.path_template,
                outcome=OPERATION_OUTCOME_ERRORED,
                failure_code=CODE_EXPRESSION_UNRESOLVED,
                failure_message=f"nothing was sent: {exc}",
            ),
            None,
        )

    try:
        request = _httpx_request(built, target.base_url, auth_headers)
    except (httpx.InvalidURL, ValueError, TypeError) as exc:
        # A value an expression produced can be unsendable (a newline in a header, say): that is
        # this step's fault, recorded as such, not a server error.
        return (
            _result(
                path=built.path,
                query=built.query,
                outcome=OPERATION_OUTCOME_ERRORED,
                failure_code=CODE_STEP_INVALID,
                failure_message=_bounded(f"nothing was sent: the request is invalid ({exc})", _MESSAGE_LIMIT),
            ),
            None,
        )
    response, attempts, error = _send(client, request, target, sleep)
    if response is None:
        code, message = error or ("transport-error", "transport error")
        return (
            _result(
                path=built.path,
                query=built.query,
                outcome=OPERATION_OUTCOME_ERRORED,
                failure_code=code,
                failure_message=message,
                attempts=attempts,
            ),
            None,
        )

    context = _response_context(base, built, request, response)
    criteria = [
        evaluate_criterion(raw, context, implicit=step.implicit_criteria)
        for raw in step.success_criteria
    ]
    failed = [c for c in criteria if c.outcome != CRITERION_PASSED]
    common = dict(
        path=built.path,
        query=built.query,
        status_code=response.status_code,
        attempts=attempts,
        criteria=[_criterion_model(c) for c in criteria],
    )
    if failed:
        first = failed[0]
        return (
            _result(
                outcome=OPERATION_OUTCOME_FAILED,
                failure_code=CODE_CRITERIA_FAILED,
                failure_message=f"{len(failed)} of {len(criteria)} criteria did not hold; "
                f"first: {first.message}",
                **common,
            ),
            context,
        )

    outputs: Dict[str, Any] = {}
    for name, expression in step.outputs.items():
        try:
            outputs[name] = resolve_value(expression, context)
        except ExpressionError as exc:
            return (
                _result(
                    outcome=OPERATION_OUTCOME_FAILED,
                    failure_code=CODE_OUTPUT_UNRESOLVED,
                    failure_message=f"output {name!r} could not be read: {exc}",
                    **common,
                ),
                context,
            )
    return _result(outcome=OPERATION_OUTCOME_PASSED, outputs=outputs, **common), context


def execute_workflow(
    plan: WorkflowRunPlan,
    inputs: Mapping[str, Any],
    *,
    target: ResolvedTarget,
    client: httpx.Client,
    auth_headers: Optional[Mapping[str, str]] = None,
    digest: str = "",
    sleep: Callable[[float], None] = time.sleep,
) -> ArazzoWorkflowRunReport:
    """Execute a planned workflow step by step and report on every step.

    Args:
        plan: A plan with no refusals (the caller refuses the run otherwise).
        inputs: The workflow inputs, defaults applied and validated.
        target: The resolved verification target.
        client: The guarded httpx client to send through.
        auth_headers: Headers from :func:`app.contract_runner.materialize_auth_headers`.
        digest: :func:`plan_digest` of the plan, echoed on the report.
        sleep: Wait function for ``retryAfter`` and transport back-off (injected by tests).

    Returns:
        The :class:`ArazzoWorkflowRunReport`.

    Raises:
        ValueError: When the plan still carries refusals — a refused plan must never be sent.
    """
    if plan.refusals:
        raise ValueError("a refused workflow plan cannot be executed")
    headers = dict(auth_headers or {})
    started_at = datetime.now(timezone.utc)
    base = ExpressionContext(inputs=dict(inputs), components=dict(plan.components))
    results: List[ArazzoStepResult] = []
    executions: Dict[str, int] = {}
    retries: Dict[str, int] = {}
    index: Optional[int] = 0 if plan.steps else None
    sends = 0

    while index is not None and index < len(plan.steps):
        step = plan.steps[index]
        if sends >= MAX_STEP_EXECUTIONS:
            results.append(_limit_result(step, executions.get(step.step_id, 0) + 1))
            break
        sends += 1
        retrying = retries.get(step.step_id, 0) > 0 and results and results[-1].step_id == step.step_id
        if not retrying:
            executions[step.step_id] = executions.get(step.step_id, 0) + 1
        result, context = _run_step(
            step,
            executions[step.step_id],
            base,
            target=target,
            client=client,
            auth_headers=headers,
            sleep=sleep,
        )
        if retrying:
            previous = results.pop()
            result = result.model_copy(
                update={
                    "attempts": previous.attempts + result.attempts,
                    "started_at": previous.started_at,
                    "duration_ms": previous.duration_ms + result.duration_ms,
                }
            )
        results.append(result)

        passed = result.outcome == OPERATION_OUTCOME_PASSED
        if passed:
            retries.pop(step.step_id, None)
            base.steps[step.step_id] = dict(result.outputs)
        action_context = context or base
        action = _choose_action(
            step.on_success if passed else step.on_failure, action_context, plan.components
        )
        index, taken = _next_index(
            plan, index, step, action, passed=passed, result=result, retries=retries, sleep=sleep
        )
        results[-1] = results[-1].model_copy(update=taken)

    outcome = _final_outcome(results)
    workflow_outputs: Dict[str, Any] = {}
    output_errors: List[str] = []
    if outcome == RUN_OUTCOME_PASSED:
        for name, expression in plan.outputs.items():
            try:
                workflow_outputs[name] = resolve_value(expression, base)
            except ExpressionError as exc:
                output_errors.append(f"{name}: {exc}")

    executed = {r.step_id for r in results}
    counts = {
        "steps": len(plan.steps),
        "executed": len(results),
        "passed": sum(1 for r in results if r.outcome == OPERATION_OUTCOME_PASSED),
        "failed": sum(1 for r in results if r.outcome == OPERATION_OUTCOME_FAILED),
        "errored": sum(1 for r in results if r.outcome == OPERATION_OUTCOME_ERRORED),
    }
    return ArazzoWorkflowRunReport(
        workflow_id=plan.workflow_id,
        outcome=outcome,
        digest=digest,
        target=TargetIdentity(
            target_id=target.target_id,
            slug=target.slug,
            environment=target.environment,
            network_class=target.network_class,
            base_url=target.base_url,
        ),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        steps=results,
        not_reached=[s.step_id for s in plan.steps if s.step_id not in executed],
        outputs=workflow_outputs,
        output_errors=output_errors,
        counts=counts,
    )


def _limit_result(step: CompiledStep, execution: int) -> ArazzoStepResult:
    """The record for the step the run refused to send because of :data:`MAX_STEP_EXECUTIONS`."""
    moment = datetime.now(timezone.utc)
    return ArazzoStepResult(
        step_id=step.step_id,
        execution=execution,
        operation_key=step.operation_key,
        method=step.method,
        path=step.path_template,
        outcome=OPERATION_OUTCOME_ERRORED,
        failure_code=CODE_STEP_LIMIT,
        failure_message=(
            f"the run reached {MAX_STEP_EXECUTIONS} step executions; a goto loop never ends"
        ),
        attempts=0,
        started_at=moment,
        finished_at=moment,
    )


def _final_outcome(results: Sequence[ArazzoStepResult]) -> str:
    """The run outcome implied by its step records (``errored`` > ``failed`` > ``passed``).

    Retried sends are merged into one record carrying the last attempt's verdict, so a step that
    passed on retry reads as passed; a failure that a ``goto`` moved past still fails the run.
    """
    outcomes = {result.outcome for result in results}
    if OPERATION_OUTCOME_ERRORED in outcomes:
        return RUN_OUTCOME_ERRORED
    if OPERATION_OUTCOME_FAILED in outcomes:
        return RUN_OUTCOME_FAILED
    return RUN_OUTCOME_PASSED


def _next_index(
    plan: WorkflowRunPlan,
    index: int,
    step: CompiledStep,
    action: Optional[Mapping[str, Any]],
    *,
    passed: bool,
    result: ArazzoStepResult,
    retries: Dict[str, int],
    sleep: Callable[[float], None],
) -> Tuple[Optional[int], Dict[str, Any]]:
    """Decide where the run goes after a step.

    Returns:
        ``(next_index, update)`` — ``next_index`` is ``None`` to stop; ``update`` holds the
        ``action`` (and, for an unsupported action, failure fields) to record on the step's
        result.
    """
    if action is None:
        if passed:
            return index + 1, {"action": ArazzoActionTaken(type="next")}
        return None, {"action": ArazzoActionTaken(type="end")}

    kind = str(action.get("type") or "")
    name = action.get("name") if isinstance(action.get("name"), str) else None
    if kind == "end":
        return None, {"action": ArazzoActionTaken(type="end", name=name)}
    if kind == "goto":
        target_step = action.get("stepId")
        if isinstance(target_step, str) and plan.step_index(target_step) is not None:
            return (
                plan.step_index(target_step),
                {"action": ArazzoActionTaken(type="goto", name=name, step_id=target_step)},
            )
        what = (
            f"workflow {action.get('workflowId')!r}"
            if action.get("workflowId")
            else f"step {target_step!r}, which this workflow does not declare"
        )
        return None, _unsupported(result, f"goto {what} is not executed by this runner", name)
    if kind == "retry" and not passed:
        limit = action.get("retryLimit")
        limit = int(limit) if isinstance(limit, (int, float)) and limit >= 0 else 1
        used = retries.get(step.step_id, 0)
        if used >= limit:
            retries.pop(step.step_id, None)
            return (
                None,
                {
                    "action": ArazzoActionTaken(type="end", name=name),
                    "failure_code": CODE_RETRIES_EXHAUSTED,
                    "failure_message": _bounded(
                        f"retried {used} time(s) (retryLimit {limit}); last: {result.failure_message}",
                        _MESSAGE_LIMIT,
                    ),
                },
            )
        retries[step.step_id] = used + 1
        wait = action.get("retryAfter")
        if isinstance(wait, (int, float)) and wait > 0:
            sleep(min(float(wait), MAX_RETRY_AFTER_SECONDS))
        return index, {"action": ArazzoActionTaken(type="retry", name=name)}
    if kind == _UNRESOLVED_REFERENCE:
        message = f"action reference {name!r} names nothing in the document's components"
    else:
        message = f"action type {kind or '(none)'!r} is not executed by this runner"
    return None, _unsupported(result, message, name)


def _unsupported(result: ArazzoStepResult, message: str, name: Optional[str]) -> Dict[str, Any]:
    """Result fields for a step whose chosen action cannot be followed."""
    update: Dict[str, Any] = {"action": ArazzoActionTaken(type="end", name=name)}
    if result.outcome == OPERATION_OUTCOME_PASSED:
        update.update(
            outcome=OPERATION_OUTCOME_ERRORED,
            failure_code=CODE_ACTION_UNSUPPORTED,
            failure_message=message,
        )
    else:
        update["failure_message"] = _bounded(
            f"{result.failure_message}; then {message}", _MESSAGE_LIMIT
        )
    return update


# =============================================================================================
# Evidence
# =============================================================================================


def _assertion(criterion: ArazzoCriterionResult) -> AssertionInput:
    """One success criterion as an ECA-1.3 assertion."""
    passed = criterion.outcome == CRITERION_PASSED
    status = criterion.type == "simple" and is_status_condition(criterion.condition)
    return AssertionInput(
        kind=ASSERTION_KIND_STATUS_CODE if status else ASSERTION_KIND_CUSTOM,
        outcome=ASSERTION_OUTCOME_PASSED if passed else ASSERTION_OUTCOME_FAILED,
        subject=_bounded(criterion.condition, _SUBJECT_LIMIT),
        expected=_bounded(criterion.expected, _FIELD_LIMIT),
        actual=_bounded(criterion.actual, _FIELD_LIMIT),
        code=None if passed else CODE_CRITERIA_FAILED,
        message=None if passed else _bounded(criterion.message, _MESSAGE_LIMIT),
    )


def evidence_operations(report: ArazzoWorkflowRunReport) -> List[OperationResultInput]:
    """Turn a run report into ECA-1.3 operation records, one per executed step.

    ``case_id`` is the ``stepId`` (``stepId#2`` for a second execution after a ``goto``), so the
    records stay unique within the run and trace back to the workflow.

    Args:
        report: The finished run.

    Returns:
        The operation records, in execution order.
    """
    operations: List[OperationResultInput] = []
    for result in report.steps:
        case_id = result.step_id if result.execution <= 1 else f"{result.step_id}#{result.execution}"
        assertions = [_assertion(c) for c in result.criteria]
        if result.outcome == OPERATION_OUTCOME_PASSED:
            # An unsupported action can flip a passed step to errored; a passed record carries
            # only passed assertions by construction.
            assertions = [a for a in assertions if a.outcome != ASSERTION_OUTCOME_FAILED]
        operations.append(
            OperationResultInput(
                case_id=case_id,
                operation_key=result.operation_key,
                operation_name=result.step_id,
                case_source=CASE_SOURCE_ARAZZO_STEP,
                http_method=result.method,
                http_path=result.path or "/",
                outcome=result.outcome,
                failure_code=result.failure_code,
                failure_message=result.failure_message,
                actual_status=result.status_code,
                started_at=result.started_at,
                finished_at=result.finished_at,
                duration_ms=result.duration_ms,
                attempts=max(1, result.attempts),
                assertions=assertions,
            )
        )
    return operations

