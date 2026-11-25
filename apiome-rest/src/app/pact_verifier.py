"""Provider verification of pacts — the judgment half of the hosted verifier, PFX-3.2 (#6932).

Native Pact verification is run by the provider's own test suite, with a Pact library. A team
without one — or one that wants the check to run where the contracts live — needs Apiome to do
it: fetch the pacts a provider must honour, replay each interaction against a registered
verification target, and publish the result where can-i-deploy reads it. This module decides the
two things that make such a run trustworthy. It has no I/O: a compiled suite and case records in,
a plan and a verdict out. :mod:`app.pact_verifier_service` does the fetching, sending and storing.

**Which interactions may this run send?** — :func:`plan_pact_run`

==============================================  ==========================================
Interaction                                     Decision
==============================================  ==========================================
gRPC call, target is not ``grpc``/``connect``   skip ``pact-interaction-protocol-mismatch``
HTTP request, target is ``grpc``/``connect``    skip ``pact-interaction-protocol-mismatch``
Recorded path is not a path on the target       skip ``pact-request-path-not-on-target``
Mutating, target policy forbids it              skip ``mutating-method-blocked``
Mutating, run did not opt in                    skip ``mutating-method-blocked``
Names a provider state, nothing can set it up   skip ``provider-state-not-set-up`` …
Names a state the registry cannot set up        skip with the registry's code (PFX-3.3) …
… and the run asked to replay it anyway         run, without setup
Anything else                                   run (a fixture, if one matches, substituted)
==============================================  ==========================================

A pact is written by a consumer; the target and its credentials belong to the provider. So a
recorded path must be a path — ``/invoices/1042`` — and one that names a scheme or a host
(``https://elsewhere/…``, ``//elsewhere/…``) is never sent: joined onto the target it would leave it,
carrying the target's credentials.

A pact may mix HTTP interactions with gRPC calls the protobuf plugin recorded (PFX-3.7); one
target speaks one protocol, so what it cannot speak is held back with the reason — the pact is
then ``incomplete`` on that target, never silently green. A GraphQL-over-HTTP interaction is an
HTTP interaction whose *operation type* decides whether it is mutating; a gRPC call is mutating
unless its method declares ``idempotency_level = NO_SIDE_EFFECTS``.

A mutating interaction needs **both** the ECA-1.2 target policy to allow mutating methods *and*
the run's ``allow_mutating`` — and the policy is checked first, so a run can only ever be narrower
than the target, never wider. Unlike a CTG-4.3 verification, no fixture is needed to send a
mutating interaction: the consumer recorded the request. A CTG-4.3 :class:`MutatingFixture` is
still honoured when one names the operation, to send a safer query, headers or body.

**Provider states.** An interaction that says "given an invoice 1042 exists" is only meaningful
once the provider is in that state. Setting states up is the provider-state registry's job
(PFX-3.3, :mod:`app.pact_provider_state`); this module defines what it plugs into —
:class:`ProviderStateHandler`. Without a handler an interaction with a state is **skipped, with the
reason**, unless the run sets ``replay_without_state_setup`` because its target already holds the
data. With one, the planner first asks the handler's ``state_issue`` whether the interaction's
states can be set up at all — an unregistered state, a missing required parameter, a setup the
target's policy forbids — and holds back, before anything is sent, every interaction it cannot.

**What does the run say?** — :func:`interaction_results`, :func:`pact_outcome`

A pact is ``passed`` only when every interaction it carries was replayed and matched; ``failed``
when a replayed interaction did not match; and ``incomplete`` when nothing failed but something
was not replayed (skipped, could not be reached, or cannot be replayed at all — a message or
plugin interaction). **Only ``passed`` and ``failed`` are published** as verification results: an
incomplete run proves nothing either way, and a green it did not earn would be read by
can-i-deploy as permission to ship. A Pact 4 interaction the consumer marked ``pending`` is
replayed and reported but never decides the outcome.

Every failure names the interaction, the field (a JSON Pointer into the response body, or the
header) and the rule that failed, with what was expected and what came back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Dict, List, Optional, Protocol, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .contract_protocols import PROTOCOL_CONNECT, PROTOCOL_GRPC, PROTOCOL_HTTP
from .contract_runner import (
    FAILURE_MUTATING_METHOD_BLOCKED,
    FAILURE_PACT_HEADER_MISMATCH,
    CaseDecision,
    CaseHooks,
    is_mutating_case,
)
from .contract_suite import (
    ContractCase,
    ContractSuiteManifest,
    PactProviderState,
    SuiteUnsupportedOperation,
)
from .pact_value_match import RULE_EQUALITY, mismatch_rule
from .provider_verification import MAX_FIXTURES, MutatingFixture, apply_fixture
from .verification_evidence import (
    ASSERTION_KIND_STATUS_CODE,
    ASSERTION_OUTCOME_FAILED,
    OPERATION_OUTCOME_ERRORED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    OPERATION_OUTCOME_SKIPPED,
    OperationResultInput,
)

__all__ = [
    "ATTRIBUTE_BODY",
    "ATTRIBUTE_HEADER",
    "ATTRIBUTE_STATUS",
    "MAX_PACTS_PER_RUN",
    "OUTCOME_FAILED",
    "OUTCOME_INCOMPLETE",
    "OUTCOME_NO_PACTS",
    "OUTCOME_PASSED",
    "SKIP_MUTATING_BLOCKED",
    "SKIP_PATH_NOT_ON_TARGET",
    "SKIP_PROTOCOL_MISMATCH",
    "VERIFIABLE_TARGET_PROTOCOLS",
    "SKIP_STATE_NOT_SET_UP",
    "SKIP_STATE_SETUP_FAILED",
    "VERIFIER_NAME",
    "VERIFIER_VERSION",
    "InteractionCounts",
    "InteractionMismatch",
    "InteractionVerification",
    "PactRunPlan",
    "PactVerificationOptions",
    "ProviderStateHandler",
    "interaction_counts",
    "interaction_results",
    "pact_outcome",
    "pact_test_results",
    "plan_pact_run",
    "state_hooks",
]

#: Recorded as ``verifiedBy`` on every result this verifier publishes, and as the evidence runner.
VERIFIER_NAME = "apiome-pact-verifier"
VERIFIER_VERSION = "1"

#: The most pacts one request verifies. A provider with more narrows its selectors.
MAX_PACTS_PER_RUN = 25

#: A mutating interaction was held back by the target policy or because the run did not opt in.
SKIP_MUTATING_BLOCKED = FAILURE_MUTATING_METHOD_BLOCKED
#: An interaction's recorded path is not a path on the target (it names a scheme or a host).
SKIP_PATH_NOT_ON_TARGET = "pact-request-path-not-on-target"
#: The interaction speaks another protocol than the target: a gRPC call on an HTTP target, or an
#: HTTP request on a gRPC / Connect target (PFX-3.7).
SKIP_PROTOCOL_MISMATCH = "pact-interaction-protocol-mismatch"
#: Target protocols a pact can be verified on: HTTP interactions on ``http``, gRPC calls on
#: ``grpc`` or ``connect``.
VERIFIABLE_TARGET_PROTOCOLS = (PROTOCOL_HTTP, PROTOCOL_GRPC, PROTOCOL_CONNECT)
#: Target protocols that carry gRPC calls.
_RPC_TARGET_PROTOCOLS = frozenset({PROTOCOL_GRPC, PROTOCOL_CONNECT})
#: An interaction names a provider state and nothing is registered that can set it up.
SKIP_STATE_NOT_SET_UP = "provider-state-not-set-up"
#: A provider-state handler was asked to set a state up and could not.
SKIP_STATE_SETUP_FAILED = "provider-state-setup-failed"

#: Every interaction of the pact was replayed and matched.
OUTCOME_PASSED = "passed"
#: A replayed interaction did not match.
OUTCOME_FAILED = "failed"
#: Nothing failed, but something was not replayed — the run proves nothing either way.
OUTCOME_INCOMPLETE = "incomplete"
#: The selectors chose no pact at all (a run's outcome only).
OUTCOME_NO_PACTS = "no-pacts"

ATTRIBUTE_STATUS = "status"
ATTRIBUTE_HEADER = "header"
ATTRIBUTE_BODY = "body"

#: What an uncompiled interaction is reported as in the published test results.
_OUTCOME_UNSUPPORTED = "unsupported"


# =============================================================================================
# The run's options, and the provider-state seam
# =============================================================================================


class PactVerificationOptions(BaseModel):
    """How much of the target this verification is allowed to touch."""

    model_config = ConfigDict(extra="forbid")

    allow_mutating: bool = Field(
        default=False,
        description=(
            "Opt in to replaying interactions with a mutating method (`POST`, `PUT`, `PATCH`, "
            "`DELETE`). Off by default. Even when on, they are sent only if the verification "
            "target's own policy allows mutating methods — a run cannot widen that policy."
        ),
    )
    fixtures: List[MutatingFixture] = Field(
        default_factory=list,
        description=(
            "Optional replacements for the request of a mutating interaction (query, headers, "
            "body), keyed by operation (`POST /invoices`) — to send something safer than the "
            "consumer recorded. The expectation is never changed."
        ),
        max_length=MAX_FIXTURES,
    )
    replay_without_state_setup: bool = Field(
        default=False,
        description=(
            "Replay interactions that name a provider state even though nothing sets the state "
            "up — no state is registered, or the registry cannot set this one up — for a target "
            "that already holds the data the pacts assume. Off by default: such interactions are "
            "skipped with `provider-state-not-set-up` or the registry's reason."
        ),
    )


class ProviderStateHandler(Protocol):
    """What sets a provider up for an interaction — implemented by the registry (PFX-3.3).

    The verifier calls :meth:`setup` immediately before an interaction that names states is sent,
    and :meth:`teardown` after it, one interaction at a time.
    """

    def setup(self, states: Sequence[PactProviderState]) -> Optional[str]:
        """Put the provider into ``states``.

        Args:
            states: The interaction's provider states, in recorded order, with their parameters.

        Returns:
            ``None`` when the provider is ready; otherwise why it is not (an unregistered state, a
            state-change call that failed) — the interaction is then skipped with that reason.
        """
        ...

    def teardown(self, states: Sequence[PactProviderState]) -> None:
        """Undo :meth:`setup` once the interaction has been replayed.

        Args:
            states: The same states.
        """
        ...


@dataclass
class PactRunPlan:
    """What one pact's run will and will not send.

    Attributes:
        decisions: One :class:`~app.contract_runner.CaseDecision` per case the planner had an
            opinion about; a case absent from the map runs as compiled.
        skips: Case id → the reason code it is held back with.
        fixtures_applied: How many cases had a fixture's request substituted in.
        states_assumed: Case ids replayed without their provider states being set up.
    """

    decisions: Dict[str, CaseDecision] = field(default_factory=dict)
    skips: Dict[str, str] = field(default_factory=dict)
    fixtures_applied: int = 0
    states_assumed: List[str] = field(default_factory=list)


def _skip(plan: PactRunPlan, case: ContractCase, code: str, message: str) -> None:
    """Record that a case is held back."""
    plan.decisions[case.case_id] = CaseDecision(run=False, skip_code=code, skip_message=message)
    plan.skips[case.case_id] = code


def _state_names(case: ContractCase) -> List[str]:
    """The names of the provider states a case's interaction assumes."""
    return [state.name for state in case.pact.provider_states] if case.pact is not None else []


def plan_pact_run(
    manifest: ContractSuiteManifest,
    options: PactVerificationOptions,
    *,
    target_allows_mutating: bool,
    has_state_handler: bool = False,
    state_issue: Optional[Callable[[Sequence[PactProviderState]], Optional[Tuple[str, str]]]] = None,
    target_protocol: str = PROTOCOL_HTTP,
) -> PactRunPlan:
    """Decide, interaction by interaction, what this verification is allowed to send.

    The target policy is checked first and cannot be overridden: a run may narrow what the target
    permits, never widen it (the runner re-checks the policy for every case it sends, too).

    Args:
        manifest: The suite compiled from the pact (PFX-3.1).
        options: The run's mutation opt-in, fixtures and provider-state choice.
        target_allows_mutating: The ECA-1.2 target policy's ``allow_mutating_methods``.
        has_state_handler: Whether a :class:`ProviderStateHandler` will set states up.
        state_issue: With a handler, why an interaction's states cannot be set up —
            ``(code, message)`` or ``None`` — asked before anything is sent (the registry's
            :meth:`~app.pact_provider_state_handler.RegistryStateHandler.issue`).
        target_protocol: The target's protocol (``http``, ``grpc`` or ``connect``): a case of
            the other kind is held back with :data:`SKIP_PROTOCOL_MISMATCH`.

    Returns:
        The :class:`PactRunPlan` to hand to :func:`app.contract_runner.run_suite`.
    """
    plan = PactRunPlan()
    by_case = {(f.operation_key, f.case_id): f for f in options.fixtures if f.case_id}
    by_operation = {f.operation_key: f for f in options.fixtures if not f.case_id}

    rpc_target = target_protocol in _RPC_TARGET_PROTOCOLS
    for case in manifest.cases:
        path = case.request.path
        rpc_case = case.protocol == PROTOCOL_GRPC
        if rpc_case != rpc_target:
            _skip(
                plan,
                case,
                SKIP_PROTOCOL_MISMATCH,
                (
                    f"the gRPC call {case.operation_key} was not sent: the verification target speaks "
                    f"'{target_protocol}'; verify it against a grpc or connect target."
                    if rpc_case
                    else f"the HTTP request {case.operation_key} was not sent: the verification target "
                    f"speaks '{target_protocol}'; verify it against an http target."
                ),
            )
            continue
        if not path.startswith("/") or path.startswith("//") or "\\" in path:
            _skip(
                plan,
                case,
                SKIP_PATH_NOT_ON_TARGET,
                f"the recorded path {path!r} is not a path on the target (it must start with a single '/'), "
                "so the request was not sent.",
            )
            continue
        mutating = is_mutating_case(case)
        what = _mutating_subject(case)
        if mutating and not target_allows_mutating:
            _skip(
                plan,
                case,
                SKIP_MUTATING_BLOCKED,
                f"{what} was not sent: the verification target's policy has "
                "allow_mutating_methods=false, which a run cannot override.",
            )
            continue
        if mutating and not options.allow_mutating:
            _skip(
                plan,
                case,
                SKIP_MUTATING_BLOCKED,
                f"{what} was not sent: this run did not opt in to mutating methods (allow_mutating=false).",
            )
            continue

        states = _state_names(case)
        if states and not has_state_handler:
            if not options.replay_without_state_setup:
                named = ", ".join(repr(name) for name in states)
                _skip(
                    plan,
                    case,
                    SKIP_STATE_NOT_SET_UP,
                    f"the interaction assumes the provider state {named} and nothing is registered "
                    "to set it up. Set replay_without_state_setup when the target already holds "
                    "that data.",
                )
                continue
            plan.states_assumed.append(case.case_id)
        elif states and state_issue is not None:
            found = state_issue(case.pact.provider_states if case.pact is not None else [])
            if found is not None:
                if not options.replay_without_state_setup:
                    _skip(plan, case, found[0], f"the interaction was not sent: {found[1]}")
                    continue
                plan.states_assumed.append(case.case_id)

        fixture = by_case.get((case.operation_key, case.case_id)) or by_operation.get(case.operation_key)
        if mutating and fixture is not None:
            plan.decisions[case.case_id] = CaseDecision(run=True, case=apply_fixture(case, fixture))
            plan.fixtures_applied += 1
    return plan


def _mutating_subject(case: ContractCase) -> str:
    """How a held-back mutating case is named in its skip reason.

    Args:
        case: The case.

    Returns:
        ``POST``; ``the GraphQL mutation 'CreateUser'``; or, for a gRPC call, its procedure and
        why it counts as mutating.
    """
    if case.graphql is not None:
        return f"the GraphQL mutation '{case.graphql.operationName or case.graphql.field}'"
    if case.rpc is not None:
        return (
            f"the gRPC call {case.rpc.procedure} (its method does not declare "
            "idempotency_level = NO_SIDE_EFFECTS)"
        )
    return case.request.method.upper()


def state_hooks(
    handler: Optional[ProviderStateHandler], assumed: Collection[str] = ()
) -> Optional[CaseHooks]:
    """Wrap a provider-state handler as the runner's per-case hooks.

    Args:
        handler: The handler, or ``None`` when nothing sets states up.
        assumed: Case ids the plan replays without setting their states up
            (:attr:`PactRunPlan.states_assumed`); the handler is not called for them.

    Returns:
        Hooks that set an interaction's states up before it is sent and tear them down after, or
        ``None`` without a handler (the run then keeps the target's concurrency).
    """
    if handler is None:
        return None

    skip = set(assumed)

    def before(case: ContractCase) -> Optional[CaseDecision]:
        states = case.pact.provider_states if case.pact is not None else []
        if not states or case.case_id in skip:
            return None
        problem = handler.setup(states)
        if problem is None:
            return None
        return CaseDecision(
            run=False,
            skip_code=SKIP_STATE_SETUP_FAILED,
            skip_message=f"the interaction was not sent: its provider state could not be set up ({problem})",
        )

    def after(case: ContractCase, _result: OperationResultInput) -> None:
        states = case.pact.provider_states if case.pact is not None else []
        if states and case.case_id not in skip:
            handler.teardown(states)

    return CaseHooks(before=before, after=after)


# =============================================================================================
# Reading a run back
# =============================================================================================


class InteractionMismatch(BaseModel):
    """One way a provider's response disagreed with the pact."""

    model_config = ConfigDict(extra="forbid")

    attribute: str = Field(description="`status`, `header` or `body`.")
    field: str = Field(
        description=(
            "What disagreed: `status`, the header's name, or the JSON Pointer of the field in the "
            "response body (`/items/0/id`; `$` is the whole body)."
        )
    )
    rule: str = Field(
        description=(
            "The matching rule that failed (`type`, `regex`, `statuscode` …); `equality` where the "
            "pact declares none; `presence` for something missing."
        )
    )
    expected: Optional[str] = Field(default=None, description="What the pact asks for.")
    actual: Optional[str] = Field(default=None, description="What the provider returned.")
    description: str = Field(description="One sentence naming the field, the rule and the difference.")


class InteractionVerification(BaseModel):
    """What replaying one interaction showed."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(description="The suite case replayed (PFX-3.1), so evidence traces back to it.")
    description: str = Field(description="The interaction's description.")
    key: Optional[str] = Field(default=None, description="The Pact 4 interaction `key`, when the pact has one.")
    pointer: str = Field(description="JSON Pointer of the interaction in the pact document.")
    operation: str = Field(description="The request replayed (`GET /invoices/1042`).")
    provider_states: List[str] = Field(
        default_factory=list, description="The provider states the interaction assumes, by name."
    )
    states_set_up: bool = Field(
        default=True,
        description="False when the interaction names provider states and was replayed without their setup.",
    )
    pending: bool = Field(
        default=False,
        description="Whether the consumer marked the interaction `pending` (Pact 4): it never decides the outcome.",
    )
    outcome: str = Field(description="`passed`, `failed`, `skipped` or `errored`.")
    code: Optional[str] = Field(
        default=None,
        description=(
            "Why it did not pass: `status-mismatch`, `pact-header-mismatch`, `pact-body-mismatch`, "
            "`mutating-method-blocked`, `provider-state-not-set-up`, `provider-state-not-registered`, "
            "`provider-state-param-missing`, `provider-state-setup-blocked`, `provider-state-setup-failed`, "
            "`transport-error`, `timeout` …"
        ),
    )
    message: Optional[str] = Field(default=None, description="The reason, in a sentence.")
    expected_status: Optional[str] = Field(default=None, description="The status the pact expects.")
    actual_status: Optional[int] = Field(default=None, description="The status the provider returned.")
    duration_ms: int = Field(default=0, description="How long the request took.")
    mismatches: List[InteractionMismatch] = Field(
        default_factory=list, description="Every expected-versus-actual difference found."
    )


class InteractionCounts(BaseModel):
    """How one pact's interactions went."""

    model_config = ConfigDict(extra="forbid")

    interactions: int = Field(description="Interactions and messages the pact carries.")
    passed: int = Field(default=0, description="Replayed and matched.")
    failed: int = Field(default=0, description="Replayed and did not match.")
    skipped: int = Field(default=0, description="Held back, with a reason.")
    errored: int = Field(default=0, description="Could not be sent or answered (transport, timeout).")
    unsupported: int = Field(default=0, description="Cannot be replayed at all (message, plugin, malformed).")


def _mismatches(case: ContractCase, operation: OperationResultInput) -> List[InteractionMismatch]:
    """Read a case's failed assertions back as mismatches.

    Args:
        case: The compiled case.
        operation: Its evidence record.

    Returns:
        One mismatch per failed assertion, in the order the runner found them.
    """
    status_rule = RULE_EQUALITY
    if case.pact is not None and any(rule.category == ATTRIBUTE_STATUS for rule in case.pact.response.matching_rules):
        status_rule = "statuscode"
    found: List[InteractionMismatch] = []
    for assertion in operation.assertions:
        if assertion.outcome != ASSERTION_OUTCOME_FAILED:
            continue
        if assertion.kind == ASSERTION_KIND_STATUS_CODE:
            attribute, where, rule = ATTRIBUTE_STATUS, ATTRIBUTE_STATUS, status_rule
        elif assertion.code == FAILURE_PACT_HEADER_MISMATCH:
            attribute, where = ATTRIBUTE_HEADER, assertion.subject or ""
            rule = mismatch_rule(assertion.message) or RULE_EQUALITY
        else:
            attribute, where = ATTRIBUTE_BODY, assertion.subject or "$"
            rule = mismatch_rule(assertion.message) or RULE_EQUALITY
        found.append(
            InteractionMismatch(
                attribute=attribute,
                field=where,
                rule=rule,
                expected=assertion.expected,
                actual=assertion.actual,
                description=assertion.message or f"{attribute} did not match",
            )
        )
    return found


def interaction_results(
    manifest: ContractSuiteManifest,
    operations: Sequence[OperationResultInput],
    *,
    states_assumed: Sequence[str] = (),
) -> List[InteractionVerification]:
    """Read a suite run back as one result per interaction.

    Args:
        manifest: The suite compiled from the pact.
        operations: The runner's records, one per case.
        states_assumed: Case ids replayed without their provider states (from the plan).

    Returns:
        The results in the pact's own interaction order. A case with no record (which the runner
        does not produce) is left out rather than invented.
    """
    by_case = {operation.case_id: operation for operation in operations}
    assumed = set(states_assumed)
    results: List[InteractionVerification] = []
    for case in sorted(manifest.cases, key=lambda item: item.pact.index if item.pact is not None else 0):
        operation = by_case.get(case.case_id)
        if operation is None or case.pact is None:
            continue
        results.append(
            InteractionVerification(
                case_id=case.case_id,
                description=case.pact.description,
                key=case.pact.key,
                pointer=case.pact.pointer,
                operation=case.operation_key,
                provider_states=_state_names(case),
                states_set_up=case.case_id not in assumed,
                pending=case.pact.pending,
                outcome=operation.outcome,
                code=operation.failure_code,
                message=operation.failure_message,
                expected_status=operation.expected_status,
                actual_status=operation.actual_status,
                duration_ms=operation.duration_ms,
                mismatches=_mismatches(case, operation),
            )
        )
    return results


def interaction_counts(
    manifest: ContractSuiteManifest, interactions: Sequence[InteractionVerification]
) -> InteractionCounts:
    """Count a pact's interactions by how they went.

    Args:
        manifest: The suite compiled from the pact.
        interactions: The per-interaction results.

    Returns:
        The counts.
    """
    tally: Dict[str, int] = {}
    for interaction in interactions:
        tally[interaction.outcome] = tally.get(interaction.outcome, 0) + 1
    return InteractionCounts(
        interactions=manifest.pact.interaction_count if manifest.pact is not None else len(interactions),
        passed=tally.get(OPERATION_OUTCOME_PASSED, 0),
        failed=tally.get(OPERATION_OUTCOME_FAILED, 0),
        skipped=tally.get(OPERATION_OUTCOME_SKIPPED, 0),
        errored=tally.get(OPERATION_OUTCOME_ERRORED, 0),
        unsupported=len(manifest.unsupported),
    )


def pact_outcome(
    interactions: Sequence[InteractionVerification],
    unsupported: Sequence[SuiteUnsupportedOperation] = (),
) -> str:
    """The verdict on one pact.

    Args:
        interactions: The per-interaction results.
        unsupported: The interactions the suite could not compile.

    Returns:
        :data:`OUTCOME_FAILED` when an interaction the consumer did not mark pending failed;
        :data:`OUTCOME_PASSED` when every such interaction passed, at least one did, and nothing
        was left uncompiled; otherwise :data:`OUTCOME_INCOMPLETE`.
    """
    deciding = [interaction for interaction in interactions if not interaction.pending]
    if any(interaction.outcome == OPERATION_OUTCOME_FAILED for interaction in deciding):
        return OUTCOME_FAILED
    complete = deciding and all(interaction.outcome == OPERATION_OUTCOME_PASSED for interaction in deciding)
    return OUTCOME_PASSED if complete and not unsupported else OUTCOME_INCOMPLETE


def pact_test_results(
    interactions: Sequence[InteractionVerification],
    unsupported: Sequence[SuiteUnsupportedOperation] = (),
) -> List[Dict[str, Any]]:
    """Render a pact's results as the ``testResults`` of a Pact verification result.

    The shape is the one Pact verifiers publish (``interactionDescription``, ``success``,
    ``mismatches`` with ``attribute`` / ``identifier`` / ``description``), with Apiome's ``outcome``,
    ``rule``, ``expected`` and ``actual`` beside them.

    Args:
        interactions: The per-interaction results.
        unsupported: The interactions the suite could not compile — listed, never dropped.

    Returns:
        One entry per interaction, then one per uncompiled interaction.
    """
    entries: List[Dict[str, Any]] = []
    for interaction in interactions:
        entry: Dict[str, Any] = {
            "interactionDescription": interaction.description,
            "success": interaction.outcome == OPERATION_OUTCOME_PASSED,
            "outcome": interaction.outcome,
        }
        if interaction.key:
            entry["interactionId"] = interaction.key
        if interaction.provider_states:
            entry["interactionProviderState"] = ", ".join(interaction.provider_states)
            entry["providerStatesSetUp"] = interaction.states_set_up
        if interaction.pending:
            entry["pending"] = True
        if interaction.mismatches:
            entry["mismatches"] = [
                {
                    "attribute": mismatch.attribute,
                    "identifier": mismatch.field,
                    "description": mismatch.description,
                    "rule": mismatch.rule,
                    "expected": mismatch.expected,
                    "actual": mismatch.actual,
                }
                for mismatch in interaction.mismatches
            ]
        elif interaction.outcome != OPERATION_OUTCOME_PASSED:
            entry["exceptions"] = [{"message": interaction.message or interaction.code or interaction.outcome}]
        if interaction.code:
            entry["code"] = interaction.code
        entries.append(entry)
    for item in unsupported:
        entries.append(
            {
                "interactionDescription": item.operation_key,
                "success": False,
                "outcome": _OUTCOME_UNSUPPORTED,
                "code": item.code,
                "exceptions": [{"message": item.reason}],
            }
        )
    return entries
