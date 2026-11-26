"""Orchestrate load → compile → resolve → plan → run → record for an Arazzo workflow (COA-1.7, #7043).

The run adds no transport or evidence machinery of its own; it composes what is already there:

1. the workflow, its steps and the operations they resolved to are read from the REPO-3.4 records
   (:mod:`app.arazzo_workflow_persistence`, the same reads :mod:`app.arazzo_workflow_routes`
   serves);
2. :func:`app.arazzo_workflow_run.compile_workflow_run` turns them into an ordered plan, and the
   run's inputs are defaulted and validated against the workflow's ``inputs`` schema;
3. :mod:`app.verification_target_store` resolves and audits the ECA-1.2 target (SSRF guard,
   private-network approval, credential *reference*);
4. :func:`app.arazzo_workflow_run.plan_mutating_steps` applies the CTG-4.3 rule — any mutating
   step without policy, opt-in and fixture refuses the run before anything is sent;
5. :func:`app.arazzo_workflow_run.execute_workflow` sends the steps in order;
6. :mod:`app.verification_evidence_store` records the run as immutable ECA-1.3 evidence.

**A refused run sends nothing and records nothing.** Its response is ``ok: false`` with every
refusal listed, so a caller fixes them all in one pass. **An executed run is always recorded**,
including a failing one, and the report is returned beside the evidence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .arazzo_workflow_run import (
    CODE_INPUTS_INVALID,
    RUNNER_NAME,
    RUNNER_SCHEMA_VERSION,
    RUNNER_VERSION,
    ArazzoRunOptions,
    ArazzoRunRefusal,
    ArazzoWorkflowRunReport,
    apply_input_defaults,
    compile_workflow_run,
    evidence_operations,
    execute_workflow,
    plan_digest,
    plan_mutating_steps,
    validate_inputs,
)
from .contract_runner import FAILURE_AUTH_UNAVAILABLE, AuthResolutionError
from .database import db
from .provider_verification import FixtureFinding
from .ssrf_guard import build_guarded_client
from .target_credentials import target_auth_headers
from .verification_evidence import VerificationRunInput, VerificationRunRecord
from .verification_evidence_store import TargetActor, record_run
from .verification_target import NETWORK_CLASS_PRIVATE
from .verification_target_store import resolve_target

__all__ = [
    "ArazzoWorkflowRunRequest",
    "ArazzoWorkflowRunResponse",
    "WorkflowNotFoundError",
    "run_workflow_against_target",
]


class WorkflowNotFoundError(LookupError):
    """The revision stores no workflow with the requested ``workflowId``."""


class ArazzoWorkflowRunRequest(BaseModel):
    """Which target to run a workflow against, with what inputs, and how much it may touch."""

    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(
        description=(
            "Verification target slug or id (ECA-1.2) — a deployment, or a `mock` environment "
            "target pointing at an Apiome mock."
        ),
        min_length=1,
        max_length=200,
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Workflow inputs (`$inputs.…`). Checked against the workflow's `inputs` schema after "
            "its property defaults are applied. The run hashes them into the digest and does not "
            "store them; a criterion that compares with an input quotes its value as evidence."
        ),
    )
    verification: ArazzoRunOptions = Field(
        default_factory=ArazzoRunOptions,
        description=(
            "What the run may send. Safe methods only by default; a mutating step needs the "
            "target policy, `allow_mutating` and a fixture naming its operation."
        ),
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Evidence retry key; forwarded to the verification-runs store.",
        max_length=200,
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret CI context (commit, branch, workflow URL). Never credentials.",
    )


class ArazzoRunErrorOut(BaseModel):
    """Why a run did not execute."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable code of the first refusal (or `auth-unavailable`).")
    message: str = Field(description="What blocked the run.")


class ArazzoWorkflowRunResponse(BaseModel):
    """The outcome of one workflow run attempt."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(description="Whether the workflow executed (whatever its outcome).")
    version_id: str = Field(description="The revision the workflow was read from.")
    workflow_id: str = Field(description="The workflow's `workflowId`.")
    digest: Optional[str] = Field(
        default=None, description="Digest of the compiled run plan and its inputs."
    )
    report: Optional[ArazzoWorkflowRunReport] = Field(
        default=None, description="The per-step report when `ok` is true."
    )
    refusals: List[ArazzoRunRefusal] = Field(
        default_factory=list,
        description="Everything that kept the run from starting; nothing was sent when non-empty.",
    )
    fixture_findings: List[FixtureFinding] = Field(
        default_factory=list, description="Fixtures that matched no mutating step."
    )
    run: Optional[VerificationRunRecord] = Field(
        default=None, description="The immutable ECA-1.3 evidence behind the report."
    )
    created: Optional[bool] = Field(
        default=None, description="True when evidence was newly written; False on replay."
    )
    error: Optional[ArazzoRunErrorOut] = Field(
        default=None, description="Populated when `ok` is false."
    )


def _refused(
    version_id: str,
    workflow_id: str,
    refusals: List[ArazzoRunRefusal],
    *,
    digest: Optional[str] = None,
    findings: Optional[List[FixtureFinding]] = None,
) -> ArazzoWorkflowRunResponse:
    """Build the ``ok: false`` response for a run that sent nothing."""
    first = refusals[0]
    return ArazzoWorkflowRunResponse(
        ok=False,
        version_id=version_id,
        workflow_id=workflow_id,
        digest=digest,
        refusals=refusals,
        fixture_findings=list(findings or []),
        error=ArazzoRunErrorOut(code=first.code, message=first.message),
    )


def run_workflow_against_target(
    version_id: str,
    workflow_id: str,
    request: ArazzoWorkflowRunRequest,
    *,
    tenant_id: str,
    actor: TargetActor,
    client: Optional[httpx.Client] = None,
) -> ArazzoWorkflowRunResponse:
    """Run one stored workflow end to end against one verification target.

    Args:
        version_id: The revision (``versions.id``) holding the workflow; checked by the caller to
            belong to the tenant.
        workflow_id: The workflow's Arazzo ``workflowId``.
        request: Target, inputs, mutation opt-in and fixtures, CI context.
        tenant_id: Authenticated tenant.
        actor: Who is running — for the target resolve audit and the evidence.
        client: Optional httpx client (tests inject a mock transport); a guarded client honouring
            the target policy is built otherwise.

    Returns:
        The :class:`ArazzoWorkflowRunResponse`.

    Raises:
        WorkflowNotFoundError: When the revision stores no such workflow.
        TargetValidationError: When the target cannot be resolved (raised by the store).
        EvidenceValidationError: When the evidence submission is refused.
    """
    workflows = db.load_arazzo_workflows(tenant_id=tenant_id, version_id=version_id)
    workflow = next((w for w in workflows if w.workflow_id == workflow_id), None)
    if workflow is None:
        raise WorkflowNotFoundError(f"Workflow not found: {workflow_id}")

    operations = db.get_arazzo_step_operations(
        tenant_id=tenant_id,
        path_operation_ids=[
            step.resolved_path_operation_id
            for step in workflow.steps
            if step.resolved_path_operation_id
        ],
    )
    components = db.get_arazzo_components(tenant_id=tenant_id, version_id=version_id)
    plan = compile_workflow_run(workflow, operations=operations, components=components)

    inputs = apply_input_defaults(plan.inputs_schema, request.inputs)
    for message in validate_inputs(plan.inputs_schema, inputs):
        plan.refusals.append(ArazzoRunRefusal(code=CODE_INPUTS_INVALID, message=message))
    if plan.refusals:
        return _refused(version_id, workflow_id, plan.refusals)

    resolved = resolve_target(
        tenant_id, request.target_ref, actor=actor, suite_digest=plan_digest(plan, inputs)
    )
    plan_mutating_steps(
        plan,
        request.verification,
        target_allows_mutating=resolved.policy.allow_mutating_methods,
    )
    digest = plan_digest(plan, inputs)
    if plan.refusals:
        return _refused(
            version_id, workflow_id, plan.refusals, digest=digest, findings=plan.fixture_findings
        )

    try:
        auth_headers = target_auth_headers(tenant_id, resolved.auth)
    except AuthResolutionError as exc:
        return _refused(
            version_id,
            workflow_id,
            [ArazzoRunRefusal(code=FAILURE_AUTH_UNAVAILABLE, message=str(exc))],
            digest=digest,
            findings=plan.fixture_findings,
        )

    own_client = client is None
    if client is None:
        client = build_guarded_client(
            allow_private=resolved.network_class == NETWORK_CLASS_PRIVATE,
            timeout=httpx.Timeout(resolved.policy.request_timeout_seconds),
            follow_redirects=resolved.policy.follow_redirects,
            verify=resolved.policy.verify_tls,
        )
    try:
        report = execute_workflow(
            plan,
            inputs,
            target=resolved,
            client=client,
            auth_headers=auth_headers,
            digest=digest,
        )
    finally:
        if own_client:
            client.close()

    recorded = record_run(
        tenant_id,
        VerificationRunInput(
            target_ref=request.target_ref,
            suite_digest=digest,
            suite_schema_version=RUNNER_SCHEMA_VERSION,
            suite_case_count=len(plan.steps),
            runner_name=RUNNER_NAME,
            runner_version=RUNNER_VERSION,
            started_at=report.started_at,
            finished_at=report.finished_at,
            source={
                "artifact_kind": "arazzo_workflow",
                "version_id": version_id,
                "workflow_id": workflow_id,
            },
            context=dict(request.context or {}),
            idempotency_key=request.idempotency_key,
            operations=evidence_operations(report),
        ),
        actor=actor,
    )
    return ArazzoWorkflowRunResponse(
        ok=True,
        version_id=version_id,
        workflow_id=workflow_id,
        digest=digest,
        report=report,
        fixture_findings=plan.fixture_findings,
        run=recorded.record,
        created=recorded.created,
    )
