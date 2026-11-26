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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .contract_protocols import PACT_VERIFICATION
from .contract_runner import AuthResolutionError, materialize_auth_headers, run_suite
from .contract_suite import ContractSuiteManifest, PactSuiteOptions, SuiteSourceInfo, SuiteUnsupportedOperation
from .contract_suite_pact import compile_pact_suite
from .mcp_credentials import load_endpoint_auth_headers
from .pact_broker_verification_routes import _result_url
from .pact_commit_status_store import post_verification_statuses
from .pact_pending_store import load_pending_evidence
from .pact_provider_state import registry_of
from .pact_provider_state_handler import RegistryStateHandler
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
    OUTCOME_FAILED,
    OUTCOME_INCOMPLETE,
    OUTCOME_NO_PACTS,
    OUTCOME_PASSED,
    VERIFIER_NAME,
    VERIFIER_VERSION,
    InteractionCounts,
    InteractionVerification,
    PactVerificationOptions,
    ProviderStateHandler,
    interaction_counts,
    interaction_results,
    pact_outcome,
    pact_test_results,
    plan_pact_run,
    state_hooks,
)
from .pact_webhook_events import fire_verification_events
from .pact_wip import select_wip_pacts
from .pacticipant import PacticipantRecord, validate_branch, validate_url, validate_version_number
from .verification_evidence import VerificationRunInput, duration_ms_between
from .verification_evidence_store import record_run
from .verification_result import TRIGGER_HOSTED, VerificationRequest, VerificationResultRecord
from .verification_result_store import publish_verification_result, record_broker_version
from .verification_target import AUTH_KIND_STORED, ResolvedTarget
from .verification_target_store import TargetActor, resolve_target

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_TARGET_AUTH_UNAVAILABLE",
    "CODE_TOO_MANY_PACTS",
    "NOT_PUBLISHED_DISABLED",
    "NOT_PUBLISHED_INCOMPLETE",
    "PactVerification",
    "PactVerifierError",
    "PactVerifyRequest",
    "PactVerifyResponse",
    "PublishedResult",
    "VerificationSession",
    "VerifiedTarget",
    "compile_stored_pact",
    "open_verification_session",
    "provider_state_handler",
    "select_provider_pacts",
    "verify_provider_pacts",
]

#: The selectors chose more pacts than one run verifies (HTTP 422).
CODE_TOO_MANY_PACTS = "pact-verify-too-many-pacts"
#: The target's credential reference could not be turned into request headers (HTTP 422).
CODE_TARGET_AUTH_UNAVAILABLE = "pact-verify-target-auth-unavailable"

#: Why a pact's result was not published: the request said ``publish: false``.
NOT_PUBLISHED_DISABLED = "publish-disabled"
#: Why a pact's result was not published: the run was inconclusive.
NOT_PUBLISHED_INCOMPLETE = "run-incomplete"


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
        description="`run-incomplete` or `publish-disabled` when `published` is false.",
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
            "that is not pending `passed`."
        )
    )
    outcome: str = Field(
        description=(
            "`passed`, `failed` (a non-pending pact failed), `incomplete` (none failed, but one "
            "could not be fully replayed) or `no-pacts` (the selectors chose nothing)."
        )
    )
    pacts: List[PactVerification] = Field(default_factory=list, description="One entry per pact verified.")


# =============================================================================================
# The provider-state seam
# =============================================================================================


def provider_state_handler(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    target: ResolvedTarget,
    auth_headers: Optional[Dict[str, str]] = None,
) -> Optional[RegistryStateHandler]:
    """The handler that sets this provider's registered states up on this target (PFX-3.3).

    A provider with no registered state gets ``None``: an interaction with a provider state is
    then skipped with ``provider-state-not-set-up`` unless the run sets
    ``replay_without_state_setup`` (:func:`app.pact_verifier.plan_pact_run`).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider being verified.
        target: The resolved verification target.
        auth_headers: The target's materialised credential headers.

    Returns:
        The registry's handler, or ``None`` when the provider has registered no state.
    """
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
    run = run_suite(
        manifest,
        target,
        auth_headers=auth_headers,
        decisions=plan.decisions,
        hooks=state_hooks(handler, plan.states_assumed),
    )
    drain = getattr(handler, "drain_teardown_failures", None)
    teardown_failures: List[str] = list(drain()) if callable(drain) else []
    interactions = interaction_results(manifest, run.operations, states_assumed=plan.states_assumed)
    outcome = pact_outcome(interactions, manifest.unsupported)
    evidence_run_id = _record_evidence(tenant_id, request, manifest, run, target_actor, pact)

    published: Optional[PublishedResult] = None
    reason: Optional[str] = None
    if outcome == OUTCOME_INCOMPLETE:
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
    """Verify a provider against the pacts its selectors choose.

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
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown provider; a malformed
            provider version, branch or build URL.
        PactPublicationError: ``pact-selector-invalid`` for a malformed selection.
        TargetValidationError: ``target-not-found``, ``target-disabled``,
            ``target-protocol-mismatch`` or a URL code — the target could not be resolved.
        PactVerifierError: :data:`CODE_TOO_MANY_PACTS` or :data:`CODE_TARGET_AUTH_UNAVAILABLE`.
    """
    version = validate_version_number(request.provider_version)
    branch = validate_branch(request.provider_branch) if request.provider_branch else None
    build_url = validate_url(request.build_url, what="build URL")
    request = request.model_copy(update={"provider_version": version})

    query = _selection(request, branch)
    provider, selected = select_provider_pacts(db, tenant_id, provider_ref, query)
    if len(selected) > MAX_PACTS_PER_RUN:
        raise PactVerifierError(
            CODE_TOO_MANY_PACTS,
            f"the selectors choose {len(selected)} pacts; one run verifies at most {MAX_PACTS_PER_RUN}. "
            "Narrow the selection (a `consumer` on each selector, or fewer selectors) and run again.",
        )

    session = open_verification_session(db, tenant_id, provider, request, actor=actor, state_handler=state_handler)
    try:
        if selected and request.publish and branch:
            # A verifier records the provider version's branch before it publishes, so each result
            # carries it; the version itself is recorded by the publication.
            record_broker_version(db, tenant_id, provider.slug, version, actor=actor, branch=branch)
        pacts = [
            session.verify(pact, pending=_excused(pact, query), broker_base=broker_base, build_url=build_url)
            for pact in selected
        ]
    finally:
        session.close()
    return session.response(version, branch, pacts)


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
    ) -> PactVerification:
        """Verify one pact on this session's target (see :func:`_verify_one`).

        Args:
            pact: The pact, with whether it is pending.
            pending: Whether its failure is excused for this run.
            broker_base: The Pact Broker base URL for result links and webhooks.
            build_url: The checked build URL.
            trigger: What started the run (stored on the published result).
            description: Why the pact is verified, when no selector chose it.

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
        )

    def close(self) -> None:
        """Release the provider-state handler, if it holds anything."""
        close = getattr(self.handler, "close", None)
        if callable(close):
            close()

    def response(self, version: str, branch: Optional[str], pacts: List[PactVerification]) -> PactVerifyResponse:
        """The run's answer: the target as resolved, the verdict and every pact.

        Args:
            version: The checked provider version.
            branch: The checked provider branch.
            pacts: The pacts verified.

        Returns:
            The response.
        """
        outcome = _run_outcome(pacts)
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
            success=outcome == OUTCOME_PASSED,
            outcome=outcome,
            pacts=pacts,
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
        PactVerifierError: :data:`CODE_TARGET_AUTH_UNAVAILABLE`.
    """
    target_actor = TargetActor(user_id=actor.user_id, label=actor.label, kind=actor.kind)
    # An http target replays HTTP interactions, a grpc / connect one the gRPC calls (PFX-3.7).
    target = resolve_target(tenant_id, request.target_ref, actor=target_actor, protocol=PACT_VERIFICATION)
    stored_headers: Optional[Dict[str, str]] = None
    if target.auth.kind == AUTH_KIND_STORED and target.auth.ref:
        stored_headers = load_endpoint_auth_headers(target.auth.ref)
    try:
        auth_headers = materialize_auth_headers(target.auth, stored_headers=stored_headers)
    except AuthResolutionError as exc:
        raise PactVerifierError(CODE_TARGET_AUTH_UNAVAILABLE, str(exc)) from exc
    handler = state_handler or provider_state_handler(db, tenant_id, provider, target, auth_headers)
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
