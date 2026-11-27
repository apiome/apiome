"""Select → compile → replay → record → publish: the hosted Pact verifier, PFX-3.2 (#6932).

One call verifies a provider against the pacts it must honour, the way a provider's own Pact
verifier would in CI — without a Pact library on the provider's side:

1. **Select** the pacts with the consumer-version selectors of ``for-verification``
   (:mod:`app.pact_selectors`, PFX-1.3), pending and work-in-progress pacts included when asked.
2. **Resolve** the registered verification target (:mod:`app.verification_target_store`, ECA-1.2):
   this is where the SSRF guard, the private-network approval, the credential *reference* and the
   mutating-method policy live. Nothing in a request can change them. An ``http`` target replays
   the HTTP interactions; a ``grpc`` or ``connect`` target the gRPC calls the Pact protobuf
   plugin recorded (PFX-3.7) — whatever the target cannot speak is held back, with the reason.
3. For each pact: **compile** it into a contract suite (:mod:`app.contract_suite_pact`, PFX-3.1 —
   the same manifest, the same digest, as ``POST …/pact-suites/…``), **plan** what may be sent
   (:func:`app.pact_verifier.plan_pact_run`), **replay** it on the ECA-2.1 runner
   (:func:`app.contract_runner.run_suite`), which judges every response under the pact's matching
   rules, and **record** the run as immutable ECA-1.3 evidence.
4. **Publish** a verification result (:mod:`app.verification_result_store`, PFX-1.4) for every
   pact whose run is conclusive — tagged with the provider version and branch, so the matrix and
   can-i-deploy read it like a result a native verifier published — and queue its webhooks.

**An inconclusive run publishes nothing.** A pact with an interaction that was skipped, could not
be reached or cannot be replayed is ``incomplete``: it is reported in full, and no result is
stored for it, because a result is a claim about the provider and the run cannot back one.

**A run that could not start says why.** An unknown provider or target, a malformed selector, a
target whose credential cannot be read, more pacts than one run takes: each is a
:class:`PactVerifierError` (or the store's own refusal) with a stable code, raised before anything
is sent.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .contract_protocols import PACT_VERIFICATION
from .contract_runner import (
    FAILURE_TIMEOUT,
    FAILURE_TRANSPORT_ERROR,
    AuthResolutionError,
    CaseDecision,
    CaseHooks,
    OperationResultInput,
    run_suite,
)
from .contract_suite import (
    ContractCase,
    ContractSuiteManifest,
    PactSuiteOptions,
    SuiteSourceInfo,
    SuiteUnsupportedOperation,
)
from .contract_suite_pact import compile_pact_suite
from .pact_broker_verification_routes import _result_url
from .pact_commit_status_store import post_verification_statuses
from .pact_owner_routing import notify_failed_verification
from .pact_pending_store import load_pending_evidence
from .pact_provider_state import registry_of
from .pact_provider_state_handler import RegistryStateHandler, SetupUrlStateHandler
from .pact_provider_state_store import list_states
from .pact_publication import PactRecord
from .pact_publication_store import get_pact_by_sha, list_pact_candidates
from .pact_selectors import (
    ForVerificationQuery,
    VerifiablePact,
    parse_for_verification_request,
    select_verifiable_pacts,
    short_description,
)
from .pact_suite_routes import pact_suite_reference
from .pact_verifier import (
    MAX_PACTS_PER_RUN,
    OUTCOME_ALREADY_VERIFIED,
    OUTCOME_COULD_NOT_CONNECT,
    OUTCOME_FAILED,
    OUTCOME_INCOMPLETE,
    OUTCOME_NO_PACTS,
    OUTCOME_PASSED,
    OUTCOME_STOPPED,
    SKIP_RUN_STOPPED,
    VERIFIER_NAME,
    VERIFIER_VERSION,
    InteractionCounts,
    InteractionVerification,
    PactVerificationOptions,
    ProviderStateHandler,
    interaction_counts,
    interaction_result,
    interaction_results,
    pact_outcome,
    pact_test_results,
    plan_pact_run,
    state_hooks,
)
from .pact_webhook_events import fire_verification_events
from .pact_wip import select_wip_pacts
from .pacticipant import PacticipantRecord, validate_branch, validate_url, validate_version_number
from .target_credentials import target_auth_headers
from .verification_evidence import OPERATION_OUTCOME_SKIPPED, VerificationRunInput, duration_ms_between
from .verification_evidence_store import record_run
from .verification_result import TRIGGER_HOSTED, VerificationRequest, VerificationResultRecord
from .verification_result_store import (
    publish_verification_result,
    record_broker_version,
    results_for_provider_version,
)
from .verification_target import ENVIRONMENT_PRODUCTION, ResolvedTarget
from .verification_target_store import TargetActor, resolve_target

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_ALREADY_VERIFIED",
    "CODE_MUTATING_PRODUCTION",
    "CODE_STOPPED",
    "CODE_TARGET_AUTH_UNAVAILABLE",
    "CODE_TOO_MANY_PACTS",
    "MUTATING_PRODUCTION_MESSAGE",
    "NOT_PUBLISHED_DISABLED",
    "NOT_PUBLISHED_INCOMPLETE",
    "NOT_PUBLISHED_STOPPED",
    "PactVerification",
    "PactVerifierError",
    "PactVerifyRequest",
    "PactVerifyResponse",
    "PreparedVerification",
    "PublishedResult",
    "RunObserver",
    "SkippedPact",
    "VerificationSession",
    "VerifiedTarget",
    "compile_stored_pact",
    "connection_failure",
    "mutating_refusal",
    "open_verification_session",
    "prepare_verification",
    "provider_state_handler",
    "run_prepared_verification",
    "select_provider_pacts",
    "verify_provider_pacts",
]

#: The selectors chose more pacts than one run verifies (HTTP 422).
CODE_TOO_MANY_PACTS = "pact-verify-too-many-pacts"
#: The target's credential reference could not be turned into request headers (HTTP 422).
CODE_TARGET_AUTH_UNAVAILABLE = "pact-verify-target-auth-unavailable"
#: The run asked to send mutating requests to a target marked production (HTTP 422, PFX-8.8).
CODE_MUTATING_PRODUCTION = "pact-verify-mutating-production"
#: Why a selected pact was skipped: it already has a result for this provider version (PFX-8.8).
CODE_ALREADY_VERIFIED = "pact-verify-already-verified"
#: Why a selected pact was skipped: the live run was stopped before it started (PFX-8.9).
CODE_STOPPED = "pact-verify-stopped"

#: What a run that asks to send mutating requests to a production target is told — the same
#: sentence the Run a verification page shows before anything is sent.
MUTATING_PRODUCTION_MESSAGE = (
    "Requests that change data are never sent to a production target. Turn allow_mutating off, "
    "or verify against a staging or test target."
)

#: Why a pact's result was not published: the request said ``publish: false``.
NOT_PUBLISHED_DISABLED = "publish-disabled"
#: Why a pact's result was not published: the run was inconclusive.
NOT_PUBLISHED_INCOMPLETE = "run-incomplete"
#: Why a pact's result was not published: the run was stopped while it was being replayed (PFX-8.9).
NOT_PUBLISHED_STOPPED = "run-stopped"


class RunObserver(Protocol):
    """Who watches a run as it happens — the live run (PFX-8.9, :mod:`app.pact_verify_runs`).

    Every call is made on the run's own thread, in order. An observer watches and may ask the run
    to stop; it never changes what a replay finds or what is published.
    """

    def stop_requested(self) -> bool:
        """Whether someone asked the run to stop (checked before each pact and each interaction)."""

    def pact_started(self, pact: VerifiablePact, interactions: int) -> None:
        """A pact is about to be replayed; ``interactions`` is how many cases its suite holds."""

    def state_set_up(self, states: List[str], problem: Optional[str], duration_ms: int) -> None:
        """The provider states of the next interaction were set up (``problem`` when they were not)."""

    def interaction_done(self, pact: VerifiablePact, result: InteractionVerification) -> None:
        """One interaction of the pact was replayed, or held back with its reason."""

    def pact_finished(self, verification: PactVerification) -> None:
        """A pact's replay is over and its result was published or not."""


def _stop_decision() -> CaseDecision:
    """What an interaction not sent because the run was stopped is recorded as."""
    return CaseDecision(
        run=False,
        skip_code=SKIP_RUN_STOPPED,
        skip_message="the run was stopped before this interaction was sent",
    )


def observed_hooks(inner: Optional[CaseHooks], observer: RunObserver, *, assumed: Sequence[str] = ()) -> CaseHooks:
    """Wrap a run's provider-state hooks so a live run can stop it and log each state set up.

    With the wrapper the runner sends one case at a time (any hooks do), so a stop takes effect
    before the very next interaction.

    Args:
        inner: The provider-state hooks (:func:`app.pact_verifier.state_hooks`), or ``None``.
        observer: Who watches the run.
        assumed: Case ids replayed without their states set up (the plan's ``states_assumed``);
            ``inner`` does not set those up, so nothing is logged for them.

    Returns:
        Hooks that check for a stop, then set the case's states up exactly as ``inner`` would.
    """
    skip = set(assumed)

    def before(case: ContractCase) -> Optional[CaseDecision]:
        if observer.stop_requested():
            return _stop_decision()
        if inner is None or inner.before is None:
            return None
        started = time.monotonic()
        verdict = inner.before(case)
        states = [state.name for state in case.pact.provider_states] if case.pact is not None else []
        if states and case.case_id not in skip:
            problem = verdict.skip_message if verdict is not None and not verdict.run else None
            observer.state_set_up(states, problem, int((time.monotonic() - started) * 1000))
        return verdict

    return CaseHooks(before=before, after=inner.after if inner is not None else None)


class PactVerifierError(Exception):
    """A verification that could not start.

    Attributes:
        code: Stable machine code (:data:`CODE_TOO_MANY_PACTS`, :data:`CODE_TARGET_AUTH_UNAVAILABLE`).
    """

    def __init__(self, code: str, message: str) -> None:
        """Build the refusal.

        Args:
            code: The stable code.
            message: What went wrong and what to do about it.
        """
        super().__init__(message)
        self.code = code


# =============================================================================================
# Request and response
# =============================================================================================


class SkippedPact(BaseModel):
    """A pact the run chose but did not verify, with the reason."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: str = Field(description="The consumer version of the pact.")
    pact_version_sha: str = Field(description="The pact version.")
    code: str = Field(
        description=(
            "`pact-verify-already-verified`, `pact-verify-in-progress`, `pact-verify-over-limit` or "
            "`pact-verify-stopped` (a live run was stopped before it reached the pact)."
        )
    )
    reason: str = Field(description="Why it was not verified, and what to do.")


class PactVerifyRequest(BaseModel):
    """Which pacts to verify, against which target, as which provider build."""

    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(
        description=(
            "Slug or id of the registered verification target (ECA-1.2) to replay against: an "
            "`http` target for HTTP interactions, a `grpc` or `connect` target for gRPC calls "
            "recorded by the Pact protobuf plugin."
        ),
        min_length=1,
        max_length=200,
    )
    provider_version: str = Field(
        description="The provider application version being verified (a commit SHA). Results are recorded against it.",
        min_length=1,
        max_length=255,
    )
    provider_branch: Optional[str] = Field(
        default=None,
        description=(
            "The branch of that provider version. Recorded on the version before a result is "
            "published, and used as `providerVersionBranch` for pending pacts and `matchingBranch` "
            "selectors when `selection` does not state one."
        ),
        max_length=255,
    )
    build_url: Optional[str] = Field(
        default=None, description="http(s) URL of the CI build, stored on each result.", max_length=2000
    )
    selection: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Which pacts to verify — the body of `POST …/pact-broker/pacts/provider/{provider}/"
            "for-verification`, unchanged: `consumerVersionSelectors`, `providerVersionBranch`, "
            "`providerVersionTags`, `includePendingStatus`, `includeWipPactsSince`. Empty selects "
            "what a Pact verifier gets by default."
        ),
    )
    verification: PactVerificationOptions = Field(
        default_factory=PactVerificationOptions,
        description="What this run may send: the mutating-method opt-in, fixtures and the provider-state choice.",
    )
    publish: bool = Field(
        default=True,
        description=(
            "Publish a verification result for every pact whose run is conclusive (`passed` or "
            "`failed`). `false` is a dry run: everything is replayed and reported, nothing is published."
        ),
    )
    skip_already_verified: bool = Field(
        default=False,
        description=(
            "Skip every selected pact that already has a verification result for this exact "
            "`provider_version` (PFX-8.8): it is listed under `skipped` with "
            "`pact-verify-already-verified` and its newest result, and not replayed. When every "
            "pact is skipped the run's outcome is `already-verified`. Off by default: a Pact "
            "verifier re-verifies whatever its selectors choose."
        ),
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret CI context (commit, workflow URL) stored with the evidence. Never credentials.",
    )


class VerifiedTarget(BaseModel):
    """The target the run replayed against, as it was resolved."""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(description="The target's id.")
    slug: str = Field(description="The target's handle.")
    environment: str = Field(description="Its environment class.")
    base_url: str = Field(description="The base URL the interactions were sent to.")
    protocol: str = Field(
        default="http",
        description=(
            "The target's protocol: `http` replays HTTP interactions (GraphQL-over-HTTP included); "
            "`grpc` or `connect` replays the gRPC calls the Pact protobuf plugin recorded. What the "
            "target cannot speak is skipped with `pact-interaction-protocol-mismatch`."
        ),
    )
    allow_mutating_methods: bool = Field(description="Whether the target's policy allows mutating methods.")


class PublishedResult(BaseModel):
    """The verification result a pact's run was published as."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(description="Its number among the results of the pact version.")
    success: bool = Field(description="Whether the pact was verified.")
    url: str = Field(description="Where the result is read on the Pact Broker surface.")
    triggered_webhooks: int = Field(default=0, description="How many webhooks its publication queued.")


class PactVerification(BaseModel):
    """What verifying one pact showed."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: str = Field(description="The latest consumer version that published this pact.")
    pact_version_sha: str = Field(description="The pact version verified.")
    short_description: str = Field(description="Why the pact was selected (`latest from branch main`).")
    pending: bool = Field(
        description=(
            "Whether the pact's failure is excused for this run: it is pending for this provider "
            "build and `selection.includePendingStatus` was set, or it is a work-in-progress pact."
        )
    )
    wip: bool = Field(default=False, description="Whether it was included as a work-in-progress pact.")
    suite_digest: str = Field(description="Digest of the contract suite compiled from the pact (PFX-3.1).")
    outcome: str = Field(description="`passed`, `failed` or `incomplete`.")
    counts: InteractionCounts = Field(description="How its interactions went.")
    interactions: List[InteractionVerification] = Field(
        default_factory=list, description="One entry per interaction replayed or held back, in the pact's order."
    )
    unsupported: List[SuiteUnsupportedOperation] = Field(
        default_factory=list,
        description="Interactions that cannot be replayed at all (message, plugin, malformed), each with its reason.",
    )
    published: bool = Field(description="Whether a verification result was published for this pact.")
    not_published_reason: Optional[str] = Field(
        default=None,
        description="`run-incomplete`, `publish-disabled` or `run-stopped` when `published` is false.",
    )
    result: Optional[PublishedResult] = Field(default=None, description="The published result.")
    evidence_run_id: Optional[str] = Field(
        default=None,
        description=(
            "The immutable evidence run (ECA-1.3) holding every request's assertions; null if it could not be stored."
        ),
    )
    state_teardown_failures: List[str] = Field(
        default_factory=list,
        description=(
            "Provider-state teardowns that failed after their interaction, each with its reason "
            "(PFX-3.3). The interactions' results stand; the target may still hold the state."
        ),
    )


class PactVerifyResponse(BaseModel):
    """The outcome of one hosted verification."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="The provider's handle.")
    provider_version: str = Field(description="The provider version verified.")
    provider_branch: Optional[str] = Field(default=None, description="Its branch, when stated.")
    target: VerifiedTarget = Field(description="The verification target replayed against.")
    success: bool = Field(
        description=(
            "What a CI job should exit on: true when at least one pact was verified and every pact "
            "that is not pending `passed` — or, for `already-verified`, when every skipped pact's "
            "newest result for this provider version passed."
        )
    )
    outcome: str = Field(
        description=(
            "`passed`, `failed` (a non-pending pact failed), `incomplete` (none failed, but one "
            "could not be fully replayed), `could-not-connect` (no request reached the target — "
            "see `connection_error`), `already-verified` (with `skip_already_verified`, every "
            "selected pact already has a result for this provider version), `no-pacts` (the "
            "selectors chose nothing) or `stopped` (a live run was stopped before it finished; "
            "PFX-8.9)."
        )
    )
    pacts: List[PactVerification] = Field(default_factory=list, description="One entry per pact verified.")
    skipped: List[SkippedPact] = Field(default_factory=list, description="Chosen but not verified, each with why.")
    connection_error: Optional[str] = Field(
        default=None,
        description=(
            "With outcome `could-not-connect`: the target never answered (`Could not connect to "
            "billing.staging.example (timeout)`). Not a failed verification — nothing was published."
        ),
    )


# =============================================================================================
# The provider-state seam
# =============================================================================================


def provider_state_handler(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    target: ResolvedTarget,
    auth_headers: Optional[Dict[str, str]] = None,
    *,
    setup_url: Optional[str] = None,
) -> Optional[RegistryStateHandler]:
    """The handler that sets this provider's states up on this target (PFX-3.3; PFX-8.8).

    With ``setup_url`` (the run's ``provider_states_setup_url``) every state goes to the provider's
    own setup endpoint and the registry is not read. Otherwise a provider with no registered state
    gets ``None``: an interaction with a provider state is then skipped with
    ``provider-state-not-set-up`` unless the run sets ``replay_without_state_setup``
    (:func:`app.pact_verifier.plan_pact_run`).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider being verified.
        target: The resolved verification target.
        auth_headers: The target's materialised credential headers.
        setup_url: The provider's setup endpoint, when the run names one.

    Returns:
        The handler, or ``None`` when there is no setup URL and the provider has registered no state.
    """
    if setup_url:
        return SetupUrlStateHandler(setup_url, target, auth_headers or {})
    states = list_states(db, tenant_id, provider)
    if not states:
        return None
    return RegistryStateHandler(registry_of(states), target, auth_headers or {})


# =============================================================================================
# The run
# =============================================================================================


def _selection(request: PactVerifyRequest, branch: Optional[str]) -> ForVerificationQuery:
    """Parse the request's selection, defaulting its provider branch to the request's.

    Args:
        request: The verification request.
        branch: The checked ``provider_branch``.

    Returns:
        The checked for-verification query.

    Raises:
        PactPublicationError: ``pact-selector-invalid`` for a malformed or ambiguous selector.
    """
    body = dict(request.selection)
    if branch and not body.get("providerVersionBranch"):
        body["providerVersionBranch"] = branch
    return parse_for_verification_request(body or None)


def select_provider_pacts(
    db: Any, tenant_id: str, provider_ref: str, query: ForVerificationQuery
) -> Tuple[PacticipantRecord, List[VerifiablePact]]:
    """The pacts a for-verification query chooses for a provider, work in progress included.

    Shared by the verifier and the provider-state check (PFX-3.3), so both see the same pacts.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        query: The checked for-verification query.

    Returns:
        ``(provider, selected)``.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown provider.
    """
    provider, candidates = list_pact_candidates(db, tenant_id, provider_ref)
    evidence = load_pending_evidence(db, tenant_id, provider.id, query.provider_version_branch)
    selected = select_verifiable_pacts(candidates, query, evidence)
    selected += select_wip_pacts(candidates, selected, query, evidence)
    return provider, selected


def compile_stored_pact(pact: PactRecord) -> ContractSuiteManifest:
    """Compile a stored pact exactly as ``POST …/pact-suites/…`` does, so the digests agree."""
    return compile_pact_suite(
        pact.content,
        consumer=pact.consumer_name,
        provider=pact.provider_name,
        options=PactSuiteOptions(),
        source=SuiteSourceInfo(
            kind="pact",
            reference=pact_suite_reference(pact.provider_slug, pact.consumer_slug, pact.sha),
            artifact_slug=pact.provider_slug,
            source_format=pact.specification_version,
        ),
    )


def _record_evidence(
    tenant_id: str,
    request: PactVerifyRequest,
    manifest: ContractSuiteManifest,
    run: Any,
    actor: TargetActor,
    pact: PactRecord,
) -> Optional[str]:
    """Store one pact's run as ECA-1.3 evidence, degrading to "not stored".

    A storage fault is logged and reported as ``None``: the replay has happened, and turning a
    filing failure into "the provider could not be verified" would be a lie about the provider.

    Args:
        tenant_id: The caller's tenant.
        request: The verification request (target reference, CI context).
        manifest: The suite that ran.
        run: The runner's :class:`~app.contract_runner.SuiteRunResult`.
        actor: Who ran it.
        pact: The pact verified.

    Returns:
        The evidence run id, or ``None`` when it could not be stored.
    """
    source = manifest.source.model_dump(mode="json", exclude_none=True) if manifest.source is not None else {}
    context = dict(request.context or {})
    context.update(
        {
            "pact_consumer": pact.consumer_slug,
            "pact_provider": pact.provider_slug,
            "pact_version_sha": pact.sha,
            "provider_version": request.provider_version,
        }
    )
    try:
        recorded = record_run(
            tenant_id,
            VerificationRunInput(
                target_ref=request.target_ref,
                suite_digest=manifest.digest,
                suite_schema_version=manifest.schema_version,
                suite_compiler_version=manifest.compiler_version,
                suite_case_count=len(manifest.cases),
                runner_name=VERIFIER_NAME,
                runner_version=VERIFIER_VERSION,
                started_at=run.started_at,
                finished_at=run.finished_at,
                source=source,
                context=context,
                operations=run.operations,
            ),
            actor=actor,
        )
    except Exception:  # noqa: BLE001 - the replay succeeded; only its filing did not
        logger.exception("pact verifier: evidence could not be stored for pact version %s", pact.sha)
        return None
    return str(recorded.record.id)


def _verify_one(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    selected: VerifiablePact,
    request: PactVerifyRequest,
    *,
    target: ResolvedTarget,
    auth_headers: Dict[str, str],
    handler: Optional[ProviderStateHandler],
    actor: ConsumerActor,
    target_actor: TargetActor,
    broker_base: str,
    build_url: Optional[str],
    pending: bool,
    trigger: str = TRIGGER_HOSTED,
    description: Optional[str] = None,
    observer: Optional[RunObserver] = None,
) -> PactVerification:
    """Verify one selected pact and, when the run is conclusive, publish its result.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider being verified.
        selected: The pact, with why it was selected and whether it is pending.
        request: The verification request.
        target: The resolved target.
        auth_headers: The target's materialised credential headers.
        handler: The provider-state handler, if any.
        actor: Who is verifying (recorded on the result).
        target_actor: The same principal, for the evidence ledger.
        broker_base: The Pact Broker base URL the result's link starts with.
        build_url: The checked build URL.
        pending: Whether the pact's failure is excused for this run (see :func:`_excused`).
        trigger: What started the run, stored on the published result (PFX-5.5): ``hosted`` for a
            ``…/verify`` request, ``manual`` or ``stale-recheck`` from the Verification console.
        description: Why the pact is verified, when no selector chose it (a console run).
        observer: Who watches the run live (PFX-8.9): told about each interaction as it is done,
            and asked before each one whether to stop. A pact cut short by a stop publishes
            nothing (``run-stopped``).

    Returns:
        The pact's verification.
    """
    candidate = selected.candidate
    pact = get_pact_by_sha(db, tenant_id, provider.slug, candidate.consumer_slug, candidate.sha)
    manifest = compile_stored_pact(pact)
    plan = plan_pact_run(
        manifest,
        request.verification,
        target_allows_mutating=target.policy.allow_mutating_methods,
        has_state_handler=handler is not None,
        state_issue=getattr(handler, "issue", None),
        target_protocol=target.protocol,
    )
    hooks = state_hooks(handler, plan.states_assumed)
    on_result = None
    if observer is not None:
        observer.pact_started(selected, len(manifest.cases))
        hooks = observed_hooks(hooks, observer, assumed=plan.states_assumed)

        def on_result(case: ContractCase, operation: OperationResultInput) -> None:
            if case.pact is not None:
                observer.interaction_done(
                    selected, interaction_result(case, operation, states_assumed=plan.states_assumed)
                )

    run = run_suite(
        manifest,
        target,
        auth_headers=auth_headers,
        decisions=plan.decisions,
        hooks=hooks,
        on_result=on_result,
    )
    drain = getattr(handler, "drain_teardown_failures", None)
    teardown_failures: List[str] = list(drain()) if callable(drain) else []
    interactions = interaction_results(manifest, run.operations, states_assumed=plan.states_assumed)
    outcome = pact_outcome(interactions, manifest.unsupported)
    evidence_run_id = _record_evidence(tenant_id, request, manifest, run, target_actor, pact)

    published: Optional[PublishedResult] = None
    reason: Optional[str] = None
    if any(interaction.code == SKIP_RUN_STOPPED for interaction in interactions):
        # A verifier killed half-way publishes nothing; neither does a stopped run.
        reason = NOT_PUBLISHED_STOPPED
    elif outcome == OUTCOME_INCOMPLETE:
        reason = NOT_PUBLISHED_INCOMPLETE
    elif not request.publish:
        reason = NOT_PUBLISHED_DISABLED
    else:
        stored = publish_verification_result(
            db,
            tenant_id,
            provider.slug,
            candidate.consumer_slug,
            candidate.sha,
            VerificationRequest(
                success=outcome == OUTCOME_PASSED,
                provider_version=request.provider_version,
                build_url=build_url,
                test_results=pact_test_results(interactions, manifest.unsupported),
                verified_by={"implementation": VERIFIER_NAME, "version": VERIFIER_VERSION},
            ),
            actor=actor,
            pact_pending=selected.pending,
            wip=selected.wip,
            trigger=trigger,
            duration_ms=duration_ms_between(run.started_at, run.finished_at),
            evidence_run_id=evidence_run_id,
        )
        published = _published(db, tenant_id, broker_base, stored)

    return PactVerification(
        consumer=candidate.consumer_slug,
        consumer_name=candidate.consumer_name,
        consumer_version=candidate.version_number,
        pact_version_sha=candidate.sha,
        short_description=description if description is not None else short_description(selected),
        pending=pending,
        wip=selected.wip,
        suite_digest=manifest.digest,
        outcome=outcome,
        counts=interaction_counts(manifest, interactions),
        interactions=interactions,
        unsupported=list(manifest.unsupported),
        published=published is not None,
        not_published_reason=reason,
        result=published,
        evidence_run_id=evidence_run_id,
        state_teardown_failures=teardown_failures,
    )


def _published(db: Any, tenant_id: str, broker_base: str, stored: VerificationResultRecord) -> PublishedResult:
    """Queue a stored result's webhooks and describe it for the response."""
    fired = fire_verification_events(db, tenant_id, broker_base, stored)
    post_verification_statuses(db, tenant_id, broker_base, stored)
    notify_failed_verification(db, tenant_id, stored)
    return PublishedResult(
        number=stored.number,
        success=stored.success,
        url=_result_url(broker_base, stored),
        triggered_webhooks=len(fired or []),
    )


def _excused(selected: VerifiablePact, query: ForVerificationQuery) -> bool:
    """Whether a pact's failure is excused for this run.

    The broker works out for every pact whether it is pending for the provider build, but a
    verifier only *acts* on it when it asked — ``includePendingStatus`` — or when the pact was
    included as work in progress. Without either, a failing pact fails the run, as it does for a
    native verifier that did not enable pending pacts.

    Args:
        selected: The selected pact.
        query: The run's for-verification query.

    Returns:
        ``True`` when the pact is pending and the run asked to be told.
    """
    return bool(selected.pending and (query.include_pending_status or selected.wip))


def mutating_refusal(allow_mutating: bool, environment: Optional[str]) -> Optional[str]:
    """Why a run may not start because it would send mutating requests to production (PFX-8.8).

    The rule holds whatever the target's own policy says: a production target that allows mutating
    methods (for its own CTG-4.3 checks) still never receives a *pact's* POST, PUT, PATCH or DELETE.

    Args:
        allow_mutating: The run's ``verification.allow_mutating``.
        environment: The target's environment class.

    Returns:
        :data:`MUTATING_PRODUCTION_MESSAGE`, or ``None`` when the run may start.
    """
    if allow_mutating and environment == ENVIRONMENT_PRODUCTION:
        return MUTATING_PRODUCTION_MESSAGE
    return None


#: The interaction codes that mean the request never reached the target.
_CONNECT_FAILURES = frozenset({FAILURE_TRANSPORT_ERROR, FAILURE_TIMEOUT})


def connection_failure(pacts: Sequence[PactVerification], base_url: str) -> Optional[str]:
    """Whether the target never answered, and the sentence that says so (PFX-8.8).

    A run *could not connect* when at least one interaction was sent and every interaction sent
    ended in a transport error or a timeout — no status came back at all. One answer, even a 500,
    means the provider was reached, and the run is judged as usual.

    Args:
        pacts: The pacts verified.
        base_url: The target's base URL (its host is named).

    Returns:
        ``Could not connect to billing.staging.example (timeout)``, or ``None``.
    """
    sent = [
        interaction
        for pact in pacts
        for interaction in pact.interactions
        if interaction.outcome != OPERATION_OUTCOME_SKIPPED
    ]
    if not sent or any(interaction.actual_status is not None for interaction in sent):
        return None
    if not all(interaction.code in _CONNECT_FAILURES for interaction in sent):
        return None
    host = urlsplit(base_url).netloc or base_url
    first = sent[0]
    why = "timeout" if first.code == FAILURE_TIMEOUT else (first.message or "transport error")
    return f"Could not connect to {host} ({why})"


def _run_outcome(pacts: Sequence[PactVerification]) -> str:
    """The verdict on the whole run: pending pacts never decide it."""
    if not pacts:
        return OUTCOME_NO_PACTS
    deciding = [pact for pact in pacts if not pact.pending]
    if any(pact.outcome == OUTCOME_FAILED for pact in deciding):
        return OUTCOME_FAILED
    if any(pact.outcome == OUTCOME_INCOMPLETE for pact in deciding):
        return OUTCOME_INCOMPLETE
    return OUTCOME_PASSED


@dataclass
class PreparedVerification:
    """A run that has passed every check and is ready to replay (see :func:`prepare_verification`).

    Attributes:
        session: The resolved target, credentials and provider-state handler; closed by the run.
        query: The checked for-verification query.
        version: The checked provider version.
        branch: The checked provider branch.
        build_url: The checked build URL.
        selected: The pacts to replay, in order.
        skipped: The pacts chosen but not replayed, each with why.
        previous: For ``skip_already_verified``: the newest result of each skipped pact.
    """

    session: "VerificationSession"
    query: ForVerificationQuery
    version: str
    branch: Optional[str]
    build_url: Optional[str]
    selected: List[VerifiablePact]
    skipped: List[SkippedPact] = field(default_factory=list)
    previous: Dict[Tuple[str, str], VerificationResultRecord] = field(default_factory=dict)


def prepare_verification(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    request: PactVerifyRequest,
    *,
    actor: ConsumerActor,
    state_handler: Optional[ProviderStateHandler] = None,
) -> PreparedVerification:
    """Check a run and choose its pacts, sending nothing (the first half of a hosted run).

    Everything that can refuse a run refuses here — so a live run (PFX-8.9) that starts in the
    background has already been told every reason it could not.

    Args:
        db: The database.
        tenant_id: The caller's tenant; every lookup is scoped to it.
        provider_ref: The provider's handle, id or name.
        request: Target, provider version, selection and what the run may send.
        actor: Who is verifying.
        state_handler: A provider-state handler to use instead of the registered one (tests).

    Returns:
        The prepared run; :func:`run_prepared_verification` replays it and closes its session.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown provider; a malformed
            provider version, branch or build URL.
        PactPublicationError: ``pact-selector-invalid`` for a malformed selection.
        TargetValidationError: ``target-not-found``, ``target-disabled``,
            ``target-protocol-mismatch`` or a URL code — the target could not be resolved.
        PactVerifierError: :data:`CODE_TOO_MANY_PACTS`, :data:`CODE_TARGET_AUTH_UNAVAILABLE` or
            :data:`CODE_MUTATING_PRODUCTION`.
    """
    version = validate_version_number(request.provider_version)
    branch = validate_branch(request.provider_branch) if request.provider_branch else None
    build_url = validate_url(request.build_url, what="build URL")
    request = request.model_copy(update={"provider_version": version})

    query = _selection(request, branch)
    provider, selected = select_provider_pacts(db, tenant_id, provider_ref, query)
    skipped: List[SkippedPact] = []
    previous: Dict[Tuple[str, str], VerificationResultRecord] = {}
    if request.skip_already_verified and selected:
        previous = results_for_provider_version(
            db, tenant_id, provider, version, [(pact.candidate.consumer_id, pact.candidate.sha) for pact in selected]
        )
        selected, skipped = _split_verified(selected, previous, version)
    if len(selected) > MAX_PACTS_PER_RUN:
        raise PactVerifierError(
            CODE_TOO_MANY_PACTS,
            f"the selectors choose {len(selected)} pacts; one run verifies at most {MAX_PACTS_PER_RUN}. "
            "Narrow the selection (a `consumer` on each selector, or fewer selectors) and run again.",
        )

    session = open_verification_session(db, tenant_id, provider, request, actor=actor, state_handler=state_handler)
    return PreparedVerification(
        session=session,
        query=query,
        version=version,
        branch=branch,
        build_url=build_url,
        selected=selected,
        skipped=skipped,
        previous=previous,
    )


def _stopped_pact(pact: VerifiablePact) -> SkippedPact:
    """A pact a stopped run never reached."""
    candidate = pact.candidate
    return SkippedPact(
        consumer=candidate.consumer_slug,
        consumer_name=candidate.consumer_name,
        consumer_version=candidate.version_number,
        pact_version_sha=candidate.sha,
        code=CODE_STOPPED,
        reason="the run was stopped before this pact was verified; start a new run to verify it.",
    )


def run_prepared_verification(
    db: Any,
    tenant_id: str,
    prepared: PreparedVerification,
    *,
    actor: ConsumerActor,
    broker_base: str,
    observer: Optional[RunObserver] = None,
) -> PactVerifyResponse:
    """Replay a prepared run, publish its results and close its session (the second half).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        prepared: What :func:`prepare_verification` returned.
        actor: Who is verifying.
        broker_base: The Pact Broker base URL the client would use (for result links and webhooks).
        observer: Who watches the run live (PFX-8.9). When it asks to stop, the pacts not yet
            started are listed under ``skipped`` with :data:`CODE_STOPPED` and the outcome is
            ``stopped``.

    Returns:
        The run: one entry per pact, each with its interactions, mismatches and published result.
    """
    session = prepared.session
    if not prepared.selected and prepared.skipped:
        session.close()
        return session.response(
            prepared.version,
            prepared.branch,
            [],
            skipped=prepared.skipped,
            previous_success=_all_passed(prepared.previous),
        )
    pacts: List[PactVerification] = []
    skipped = list(prepared.skipped)
    stopped = False
    try:
        if prepared.selected and session.request.publish and prepared.branch:
            # A verifier records the provider version's branch before it publishes, so each result
            # carries it; the version itself is recorded by the publication.
            record_broker_version(
                db, tenant_id, session.provider.slug, prepared.version, actor=actor, branch=prepared.branch
            )
        for index, pact in enumerate(prepared.selected):
            if observer is not None and observer.stop_requested():
                stopped = True
                skipped.extend(_stopped_pact(rest) for rest in prepared.selected[index:])
                break
            verification = session.verify(
                pact,
                pending=_excused(pact, prepared.query),
                broker_base=broker_base,
                build_url=prepared.build_url,
                observer=observer,
            )
            pacts.append(verification)
            if observer is not None:
                observer.pact_finished(verification)
        if observer is not None and not stopped:
            stopped = any(verification.not_published_reason == NOT_PUBLISHED_STOPPED for verification in pacts)
    finally:
        session.close()
    return session.response(prepared.version, prepared.branch, pacts, skipped=skipped, stopped=stopped)


def verify_provider_pacts(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    request: PactVerifyRequest,
    *,
    actor: ConsumerActor,
    broker_base: str,
    state_handler: Optional[ProviderStateHandler] = None,
) -> PactVerifyResponse:
    """Verify a provider against the pacts its selectors choose, in one request.

    :func:`prepare_verification` then :func:`run_prepared_verification`; a live run (PFX-8.9) runs
    the same two halves with the second on a background thread.

    Args:
        db: The database.
        tenant_id: The caller's tenant; every lookup is scoped to it.
        provider_ref: The provider's handle, id or name.
        request: Target, provider version, selection and what the run may send.
        actor: Who is verifying.
        broker_base: The Pact Broker base URL the client would use (for result links and webhooks).
        state_handler: A provider-state handler to use instead of the registered one (tests).

    Returns:
        The run: one entry per pact, each with its interactions, mismatches and published result.

    Raises:
        PacticipantValidationError, PactPublicationError, TargetValidationError, PactVerifierError:
            As :func:`prepare_verification` documents.
    """
    prepared = prepare_verification(db, tenant_id, provider_ref, request, actor=actor, state_handler=state_handler)
    return run_prepared_verification(db, tenant_id, prepared, actor=actor, broker_base=broker_base)


def _split_verified(
    selected: List[VerifiablePact], previous: Dict[Tuple[str, str], VerificationResultRecord], version: str
) -> Tuple[List[VerifiablePact], List[SkippedPact]]:
    """Set aside the pacts that already have a result for this provider version.

    Args:
        selected: The pacts the selectors chose.
        previous: Their newest result for the version, by ``(consumer_id, sha)``.
        version: The provider version.

    Returns:
        ``(to_run, skipped)``.
    """
    to_run: List[VerifiablePact] = []
    skipped: List[SkippedPact] = []
    for pact in selected:
        candidate = pact.candidate
        found = previous.get((str(candidate.consumer_id), candidate.sha))
        if found is None:
            to_run.append(pact)
            continue
        verdict = "passed" if found.success else "failed"
        skipped.append(
            SkippedPact(
                consumer=candidate.consumer_slug,
                consumer_name=candidate.consumer_name,
                consumer_version=candidate.version_number,
                pact_version_sha=candidate.sha,
                code=CODE_ALREADY_VERIFIED,
                reason=(
                    f"already verified for {version} (result {found.number}, {verdict}); "
                    "turn skip_already_verified off to verify it again."
                ),
            )
        )
    return to_run, skipped


def _all_passed(previous: Dict[Tuple[str, str], VerificationResultRecord]) -> bool:
    """Whether every result a fully skipped run stands on passed."""
    return bool(previous) and all(record.success for record in previous.values())


class VerificationSession:
    """One resolved target, its credentials and its provider-state handler, for a run of pacts.

    Built by :func:`open_verification_session`. The hosted verifier shares it with the
    Verification console's re-run and verify-all-stale (PFX-5.5, #6949), so every path replays,
    records and publishes the same way. :meth:`close` releases the provider-state handler.
    """

    def __init__(
        self,
        db: Any,
        tenant_id: str,
        provider: PacticipantRecord,
        request: PactVerifyRequest,
        *,
        target: ResolvedTarget,
        auth_headers: Dict[str, str],
        handler: Optional[ProviderStateHandler],
        actor: ConsumerActor,
        target_actor: TargetActor,
    ) -> None:
        """Hold what every pact of the run shares (see :func:`open_verification_session`)."""
        self.db = db
        self.tenant_id = tenant_id
        self.provider = provider
        self.request = request
        self.target = target
        self.auth_headers = auth_headers
        self.handler = handler
        self.actor = actor
        self.target_actor = target_actor

    def verify(
        self,
        pact: VerifiablePact,
        *,
        pending: bool,
        broker_base: str,
        build_url: Optional[str],
        trigger: str = TRIGGER_HOSTED,
        description: Optional[str] = None,
        observer: Optional[RunObserver] = None,
    ) -> PactVerification:
        """Verify one pact on this session's target (see :func:`_verify_one`).

        Args:
            pact: The pact, with whether it is pending.
            pending: Whether its failure is excused for this run.
            broker_base: The Pact Broker base URL for result links and webhooks.
            build_url: The checked build URL.
            trigger: What started the run (stored on the published result).
            description: Why the pact is verified, when no selector chose it.
            observer: Who watches the run live (PFX-8.9).

        Returns:
            The pact's verification.
        """
        return _verify_one(
            self.db,
            self.tenant_id,
            self.provider,
            pact,
            self.request,
            target=self.target,
            auth_headers=self.auth_headers,
            handler=self.handler,
            actor=self.actor,
            target_actor=self.target_actor,
            broker_base=broker_base,
            build_url=build_url,
            pending=pending,
            trigger=trigger,
            description=description,
            observer=observer,
        )

    def replay_interaction(self, consumer: str, sha: str, case_id: str) -> Optional[InteractionVerification]:
        """Replay one interaction of one pact on this session's target, publishing nothing (PFX-8.9).

        The interaction is planned exactly as in a full run — the target's policy, the run's
        mutating opt-in and fixtures, its provider states set up and torn down — but no evidence
        is recorded and no verification result is published: one interaction does not verify a
        pact.

        Args:
            consumer: The consumer's handle.
            sha: The pact version.
            case_id: The suite case to replay (``InteractionVerification.case_id``).

        Returns:
            The interaction's result, or ``None`` when the pact has no such case.

        Raises:
            PactPublicationError: ``pact-not-found`` for an unknown pact version.
        """
        pact = get_pact_by_sha(self.db, self.tenant_id, self.provider.slug, consumer, sha)
        manifest = compile_stored_pact(pact)
        case = next((item for item in manifest.cases if item.case_id == case_id), None)
        if case is None:
            return None
        single = manifest.model_copy(update={"cases": [case]})
        plan = plan_pact_run(
            single,
            self.request.verification,
            target_allows_mutating=self.target.policy.allow_mutating_methods,
            has_state_handler=self.handler is not None,
            state_issue=getattr(self.handler, "issue", None),
            target_protocol=self.target.protocol,
        )
        run = run_suite(
            single,
            self.target,
            auth_headers=self.auth_headers,
            decisions=plan.decisions,
            hooks=state_hooks(self.handler, plan.states_assumed),
        )
        if not run.operations:
            return None
        return interaction_result(case, run.operations[0], states_assumed=plan.states_assumed)

    def close(self) -> None:
        """Release the provider-state handler, if it holds anything."""
        close = getattr(self.handler, "close", None)
        if callable(close):
            close()

    def response(
        self,
        version: str,
        branch: Optional[str],
        pacts: List[PactVerification],
        *,
        skipped: Optional[List[SkippedPact]] = None,
        previous_success: bool = False,
        stopped: bool = False,
    ) -> PactVerifyResponse:
        """The run's answer: the target as resolved, the verdict and every pact.

        Args:
            version: The checked provider version.
            branch: The checked provider branch.
            pacts: The pacts verified.
            skipped: The pacts chosen but not verified.
            previous_success: For a run that skipped every pact as already verified: whether
                the results it stands on all passed.
            stopped: Whether a live run was stopped before it finished (PFX-8.9).

        Returns:
            The response.
        """
        connection_error = connection_failure(pacts, self.target.base_url)
        if stopped:
            outcome = OUTCOME_STOPPED
        elif connection_error:
            outcome = OUTCOME_COULD_NOT_CONNECT
        elif not pacts and skipped and all(item.code == CODE_ALREADY_VERIFIED for item in skipped):
            outcome = OUTCOME_ALREADY_VERIFIED
        else:
            outcome = _run_outcome(pacts)
        success = outcome == OUTCOME_PASSED or (outcome == OUTCOME_ALREADY_VERIFIED and previous_success)
        return PactVerifyResponse(
            provider=self.provider.slug,
            provider_version=version,
            provider_branch=branch,
            target=VerifiedTarget(
                target_id=self.target.target_id,
                slug=self.target.slug,
                environment=self.target.environment,
                base_url=self.target.base_url,
                protocol=self.target.protocol,
                allow_mutating_methods=self.target.policy.allow_mutating_methods,
            ),
            success=success,
            outcome=outcome,
            pacts=pacts,
            skipped=list(skipped or []),
            connection_error=connection_error,
        )


def open_verification_session(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    request: PactVerifyRequest,
    *,
    actor: ConsumerActor,
    state_handler: Optional[ProviderStateHandler] = None,
) -> VerificationSession:
    """Resolve the request's target, its credentials and the provider-state handler.

    Nothing is sent to the target here; a run that cannot start fails before any pact is replayed.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider being verified.
        request: The verification request (its ``target_ref``).
        actor: Who is verifying.
        state_handler: A provider-state handler to use instead of the registered one (tests).

    Returns:
        The session; call :meth:`VerificationSession.close` when done.

    Raises:
        TargetValidationError: The target could not be resolved.
        PactVerifierError: :data:`CODE_TARGET_AUTH_UNAVAILABLE`, or :data:`CODE_MUTATING_PRODUCTION`
            for a run that opts in to mutating requests against a production target — every
            path (``…/verify``, the console's re-run and verify-all-stale, a scheduled run) opens
            its target here, so none can send one.
    """
    target_actor = TargetActor(user_id=actor.user_id, label=actor.label, kind=actor.kind)
    # An http target replays HTTP interactions, a grpc / connect one the gRPC calls (PFX-3.7).
    target = resolve_target(tenant_id, request.target_ref, actor=target_actor, protocol=PACT_VERIFICATION)
    refusal = mutating_refusal(request.verification.allow_mutating, target.environment)
    if refusal:
        raise PactVerifierError(CODE_MUTATING_PRODUCTION, refusal)
    try:
        auth_headers = target_auth_headers(tenant_id, target.auth)
    except AuthResolutionError as exc:
        raise PactVerifierError(CODE_TARGET_AUTH_UNAVAILABLE, str(exc)) from exc
    handler = state_handler or provider_state_handler(
        db, tenant_id, provider, target, auth_headers, setup_url=request.verification.provider_states_setup_url
    )
    return VerificationSession(
        db,
        tenant_id,
        provider,
        request,
        target=target,
        auth_headers=auth_headers,
        handler=handler,
        actor=actor,
        target_actor=target_actor,
    )
