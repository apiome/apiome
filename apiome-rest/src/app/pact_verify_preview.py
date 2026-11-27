"""What a hosted verification would do, before it runs — the Run a verification page, PFX-8.8 (#7305).

``POST …/pact-verifier/pacts/provider/{provider}/verify/preview`` takes the body of ``…/verify``
and answers, **without sending anything to any target or storing anything**:

* **rules** — how many pacts each consumer-version selector chooses on its own (the page writes each
  selector as a sentence with its count; duplicates across rules are verified once);
* **pacts** — every pact the whole selection chooses (pending and work-in-progress included, as
  :func:`app.pact_verifier_service.select_provider_pacts` chooses them), each with its interaction
  count, how many of those change data, its newest result, and whether it already has a result
  for this exact provider version (and so would be skipped with ``skip_already_verified``);
* **states** — the provider states those interactions name and how many the chosen strategy can
  set up: the registry (registered states, through the registry's own
  :func:`~app.pact_provider_state.state_issue`), the provider's setup URL (all), or none;
* **target** — the target's environment class and whether its policy allows mutating methods;
* **refusals** — every reason the run would not start, with the run's own codes: mutating requests
  to a production target (:data:`~app.pact_verifier_service.CODE_MUTATING_PRODUCTION`), more pacts
  than one run takes, a target that cannot be found or a malformed provider version.

The preview and the run select with the same functions, so the list is the run's list.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .pact_pending_store import load_pending_evidence
from .pact_provider_state import registry_of, state_issue
from .pact_provider_state_store import list_states
from .pact_publication_store import get_pact_by_sha, list_pact_candidates
from .pact_selectors import (
    ForVerificationQuery,
    VerifiablePact,
    parse_for_verification_request,
    select_verifiable_pacts,
    short_description,
)
from .pact_verifier import (
    MAX_PACTS_PER_RUN,
    PactVerificationOptions,
    is_mutating_case,
)
from .pact_verifier_service import (
    CODE_MUTATING_PRODUCTION,
    CODE_TOO_MANY_PACTS,
    compile_stored_pact,
    mutating_refusal,
)
from .pact_wip import select_wip_pacts
from .pacticipant import PacticipantValidationError, validate_branch, validate_version_number
from .verification_result_store import latest_results_by_pact, results_for_provider_version
from .verification_target import ENVIRONMENT_PRODUCTION, TargetValidationError
from .verification_target_store import get_target

__all__ = [
    "MAX_PREVIEW_PACTS",
    "STRATEGY_NONE",
    "STRATEGY_REGISTRY",
    "STRATEGY_SETUP_URL",
    "PreviewPact",
    "PreviewRefusal",
    "PreviewResult",
    "PreviewRule",
    "PreviewStates",
    "PreviewTarget",
    "VerifyPreviewRequest",
    "VerifyPreviewResponse",
    "preview_verification",
]

#: The most pacts a preview describes one by one (it still counts them all).
MAX_PREVIEW_PACTS = 100

#: Provider states are set up by the registry (PFX-3.3).
STRATEGY_REGISTRY = "registry"
#: Provider states go to the provider's own setup endpoint.
STRATEGY_SETUP_URL = "setup-url"
#: Nothing sets provider states up; the run replays as-is (``replay_without_state_setup``).
STRATEGY_NONE = "none"


class VerifyPreviewRequest(BaseModel):
    """The body of ``…/verify``, with the target and the provider version optional."""

    model_config = ConfigDict(extra="forbid")

    target_ref: Optional[str] = Field(
        default=None,
        description="Slug or id of the verification target the run would use. Omit for a self-run.",
        max_length=200,
    )
    provider_version: Optional[str] = Field(
        default=None,
        description="The provider version the run would verify; needed to say which pacts it already verified.",
        max_length=255,
    )
    provider_branch: Optional[str] = Field(
        default=None,
        description="Its branch — the `providerVersionBranch` of pending pacts and `matchingBranch` selectors.",
        max_length=255,
    )
    selection: Dict[str, Any] = Field(
        default_factory=dict,
        description="The run's `selection` (the body of `…/for-verification`), unchanged.",
    )
    verification: PactVerificationOptions = Field(
        default_factory=PactVerificationOptions,
        description="The run's options: the mutating opt-in and the provider-state choice.",
    )
    skip_already_verified: bool = Field(
        default=False, description="Whether the run would skip pacts already verified for `provider_version`."
    )


class PreviewRule(BaseModel):
    """One consumer-version selector and how many pacts it chooses on its own."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="Its position in `selection.consumerVersionSelectors`.")
    selector: Dict[str, Any] = Field(description="The selector, as sent.")
    pacts: int = Field(description="How many pacts it chooses on its own.")


class PreviewResult(BaseModel):
    """A pact's newest verification result."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(description="Its number among the pact version's results.")
    success: bool = Field(description="Whether it passed.")
    provider_version: str = Field(description="The provider version it verified.")
    verified_at: Optional[str] = Field(default=None, description="When it was published (ISO 8601).")


class PreviewPact(BaseModel):
    """One pact the run would choose."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: str = Field(description="The latest consumer version that published this pact.")
    pact_version_sha: str = Field(description="The pact version.")
    short_description: str = Field(description="Why it was chosen (`latest from branch main`).")
    branches: List[str] = Field(default_factory=list, description="The consumer version's branches.")
    deployed_to: List[str] = Field(default_factory=list, description="Environments the version is deployed to.")
    released_in: List[str] = Field(default_factory=list, description="Environments the version is released in.")
    pending: bool = Field(description="Whether the pact is pending for this provider build.")
    wip: bool = Field(description="Whether it is included as a work-in-progress pact.")
    interactions: int = Field(description="How many interactions it holds.")
    mutating_interactions: int = Field(description="How many of them send POST, PUT, PATCH or DELETE.")
    state_interactions: int = Field(description="How many of them name a provider state.")
    held_back: int = Field(
        description=(
            "How many interactions the run would not send for their provider states — or, when the "
            "run does not opt in, for changing data."
        )
    )
    last_result: Optional[PreviewResult] = Field(default=None, description="Its newest result, if any.")
    already_verified: bool = Field(description="Whether it has a result for this exact provider version.")
    will_run: bool = Field(description="False when `skip_already_verified` would skip it.")


class PreviewStates(BaseModel):
    """The provider states the chosen pacts name, and how many the strategy sets up."""

    model_config = ConfigDict(extra="forbid")

    strategy: str = Field(description="`registry`, `setup-url` or `none`.")
    used: int = Field(description="How many distinct states the chosen interactions name.")
    handled: int = Field(description="How many of them the strategy can set up.")
    missing: List[str] = Field(default_factory=list, description="The states it cannot, by name.")
    registered: int = Field(description="How many states the provider has registered.")


class PreviewTarget(BaseModel):
    """The verification target, as far as the run's rules need it."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="Its handle.")
    name: str = Field(description="Its display name.")
    environment: str = Field(description="Its environment class.")
    production: bool = Field(description="Whether it is marked production: mutating requests are never sent to it.")
    allow_mutating_methods: bool = Field(description="Whether its policy allows mutating methods at all.")
    enabled: bool = Field(description="Whether it can be used.")


class PreviewRefusal(BaseModel):
    """A reason the run would not start."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="The code the run would refuse with.")
    message: str = Field(description="Why, and what to do.")


class VerifyPreviewResponse(BaseModel):
    """What the run would verify."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="Its display name.")
    provider_version: Optional[str] = Field(default=None, description="The provider version, as checked.")
    target: Optional[PreviewTarget] = Field(default=None, description="The target, when one was named and found.")
    rules: List[PreviewRule] = Field(default_factory=list, description="One entry per consumer-version selector.")
    selected: int = Field(description="How many pacts the whole selection chooses.")
    will_run: int = Field(description="How many of them the run would verify.")
    skipped: int = Field(description="How many it would skip as already verified for this provider version.")
    interactions: int = Field(description="How many interactions the pacts it would verify hold.")
    pacts: List[PreviewPact] = Field(
        default_factory=list, description=f"The chosen pacts, the first {MAX_PREVIEW_PACTS}, in the run's order."
    )
    truncated: bool = Field(default=False, description="Whether more pacts were chosen than `pacts` lists.")
    states: PreviewStates = Field(description="Provider-state coverage.")
    max_pacts_per_run: int = Field(default=MAX_PACTS_PER_RUN, description="The most pacts one run verifies.")
    refusals: List[PreviewRefusal] = Field(
        default_factory=list, description="Why the run would not start; empty when it would."
    )


def _query(selection: Dict[str, Any], branch: Optional[str]) -> ForVerificationQuery:
    """Parse a selection as the run does, defaulting its provider branch to the run's.

    Raises:
        PactPublicationError: ``pact-selector-invalid``.
    """
    body = dict(selection)
    if branch and not body.get("providerVersionBranch"):
        body["providerVersionBranch"] = branch
    return parse_for_verification_request(body or None)


def _rule_counts(
    selection: Dict[str, Any], branch: Optional[str], candidates: Sequence[Any], evidence: Any
) -> List[PreviewRule]:
    """How many pacts each selector chooses on its own (no work-in-progress pacts)."""
    selectors = selection.get("consumerVersionSelectors")
    if not isinstance(selectors, list):
        return []
    rules: List[PreviewRule] = []
    for index, selector in enumerate(selectors):
        alone = {key: value for key, value in selection.items() if key != "includeWipPactsSince"}
        alone["consumerVersionSelectors"] = [selector]
        chosen = select_verifiable_pacts(candidates, _query(alone, branch), evidence)
        rules.append(PreviewRule(index=index, selector=dict(selector), pacts=len(chosen)))
    return rules


def _strategy(options: PactVerificationOptions) -> str:
    """Which provider-state strategy the run's options choose."""
    if options.provider_states_setup_url:
        return STRATEGY_SETUP_URL
    if options.replay_without_state_setup:
        return STRATEGY_NONE
    return STRATEGY_REGISTRY


def _describe_pact(
    db: Any,
    tenant_id: str,
    provider_slug: str,
    selected: VerifiablePact,
    *,
    registry: Dict[str, Any],
    strategy: str,
    options: PactVerificationOptions,
    target_id: Optional[str],
    target_allows_mutating: bool,
    used: Set[str],
    unhandled: Set[str],
) -> Tuple[int, int, int, int]:
    """Compile one pact and count its interactions; collect the states it names.

    An interaction is *held back* as the run's planner would hold it back: it changes data and the
    run (or the target) does not allow that, or its states cannot be set up by the strategy — the
    registry's own :func:`~app.pact_provider_state.state_issue`, or a setup URL that is a ``POST``
    to a target whose policy forbids mutating methods. Replaying as-is holds nothing back.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_slug: The provider's handle.
        selected: The pact.
        registry: The provider's registered states, by name (registry strategy only).
        strategy: The provider-state strategy.
        options: The run's options.
        target_id: The target's id, for its state overrides.
        target_allows_mutating: Whether the target's policy allows mutating methods (true without one).
        used: Collects every state named.
        unhandled: Collects every state the strategy cannot set up.

    Returns:
        ``(interactions, mutating, with_states, held_back)``.
    """
    setup_url = options.provider_states_setup_url or ""
    setup_url_blocked = setup_url.startswith("/") and not target_allows_mutating
    candidate = selected.candidate
    stored = get_pact_by_sha(db, tenant_id, provider_slug, candidate.consumer_slug, candidate.sha)
    manifest = compile_stored_pact(stored)
    mutating = with_states = held_back = 0
    for case in manifest.cases:
        changes_data = is_mutating_case(case)
        mutating += 1 if changes_data else 0
        states = list(case.pact.provider_states) if case.pact is not None else []
        if states:
            with_states += 1
            used.update(state.name for state in states)
            if strategy == STRATEGY_REGISTRY:
                unhandled.update(state.name for state in states if state.name not in registry)
            elif strategy == STRATEGY_SETUP_URL and setup_url_blocked:
                unhandled.update(state.name for state in states)
        if changes_data and not (options.allow_mutating and target_allows_mutating):
            held_back += 1
            continue
        if not states:
            continue
        if strategy == STRATEGY_REGISTRY:
            issue = state_issue(states, registry, target_id=target_id, target_allows_mutating=target_allows_mutating)
            held_back += 1 if issue is not None else 0
        elif strategy == STRATEGY_SETUP_URL and setup_url_blocked:
            held_back += 1
    return len(manifest.cases) + len(manifest.unsupported), mutating, with_states, held_back


def _result(record: Any) -> PreviewResult:
    """A stored result as the preview shows it."""
    created = getattr(record, "created_at", None)
    return PreviewResult(
        number=record.number,
        success=record.success,
        provider_version=record.provider_version,
        verified_at=created.isoformat() if hasattr(created, "isoformat") else (str(created) if created else None),
    )


def preview_verification(
    db: Any, tenant_id: str, provider_ref: str, request: VerifyPreviewRequest
) -> VerifyPreviewResponse:
    """Say what ``…/verify`` would do with this body, sending and storing nothing.

    Args:
        db: The database.
        tenant_id: The caller's tenant; every lookup is scoped to it.
        provider_ref: The provider's handle, id or name.
        request: The run's body.

    Returns:
        The preview. A reason the run would refuse to start is a ``refusals`` entry, not an error.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown provider.
        PactPublicationError: ``pact-selector-invalid`` for a malformed selection (the page cannot
            describe a selection it cannot read).
    """
    refusals: List[PreviewRefusal] = []
    version: Optional[str] = None
    if request.provider_version and request.provider_version.strip():
        try:
            version = validate_version_number(request.provider_version)
        except PacticipantValidationError as exc:
            refusals.append(PreviewRefusal(code=exc.code, message=str(exc)))
    branch: Optional[str] = None
    if request.provider_branch and request.provider_branch.strip():
        try:
            branch = validate_branch(request.provider_branch)
        except PacticipantValidationError as exc:
            refusals.append(PreviewRefusal(code=exc.code, message=str(exc)))

    target: Optional[PreviewTarget] = None
    target_id: Optional[str] = None
    if request.target_ref and request.target_ref.strip():
        try:
            record = get_target(tenant_id, request.target_ref.strip())
            target_id = str(record.id)
            target = PreviewTarget(
                slug=record.slug,
                name=record.name or record.slug,
                environment=record.environment,
                production=record.environment == ENVIRONMENT_PRODUCTION,
                allow_mutating_methods=bool(record.policy.allow_mutating_methods),
                enabled=bool(getattr(record, "enabled", True)),
            )
        except TargetValidationError as exc:
            refusals.append(PreviewRefusal(code=exc.code, message=str(exc)))
    if target is not None:
        refusal = mutating_refusal(request.verification.allow_mutating, target.environment)
        if refusal:
            refusals.append(PreviewRefusal(code=CODE_MUTATING_PRODUCTION, message=refusal))

    query = _query(request.selection, branch)
    provider, candidates = list_pact_candidates(db, tenant_id, provider_ref)
    evidence = load_pending_evidence(db, tenant_id, provider.id, query.provider_version_branch)
    selected = select_verifiable_pacts(candidates, query, evidence)
    selected += select_wip_pacts(candidates, selected, query, evidence)
    rules = _rule_counts(request.selection, branch, candidates, evidence)

    keys = [(str(pact.candidate.consumer_id), pact.candidate.sha) for pact in selected]
    latest = latest_results_by_pact(db, tenant_id, provider, keys)
    for_version = results_for_provider_version(db, tenant_id, provider, version, keys) if version else {}

    strategy = _strategy(request.verification)
    states_registered = list_states(db, tenant_id, provider) if strategy == STRATEGY_REGISTRY else []
    registry = registry_of(states_registered) if states_registered else {}
    allows_mutating = bool(target.allow_mutating_methods) if target is not None else True
    used: Set[str] = set()
    unhandled: Set[str] = set()

    pacts: List[PreviewPact] = []
    will_run = skipped = interactions = 0
    for pact in selected:
        key = (str(pact.candidate.consumer_id), pact.candidate.sha)
        already = key in for_version
        runs = not (already and request.skip_already_verified)
        will_run += 1 if runs else 0
        skipped += 0 if runs else 1
        if len(pacts) >= MAX_PREVIEW_PACTS:
            continue
        count, mutating, with_states, held_back = _describe_pact(
            db,
            tenant_id,
            provider.slug,
            pact,
            registry=registry,
            strategy=strategy,
            options=request.verification,
            target_id=target_id,
            target_allows_mutating=allows_mutating,
            used=used,
            unhandled=unhandled,
        )
        interactions += count if runs else 0
        candidate = pact.candidate
        pacts.append(
            PreviewPact(
                consumer=candidate.consumer_slug,
                consumer_name=candidate.consumer_name,
                consumer_version=candidate.version_number,
                pact_version_sha=candidate.sha,
                short_description=short_description(pact),
                branches=list(candidate.branches),
                deployed_to=list(candidate.deployed_to),
                released_in=list(candidate.released_in),
                pending=bool(pact.pending),
                wip=bool(pact.wip),
                interactions=count,
                mutating_interactions=mutating,
                state_interactions=with_states,
                held_back=held_back,
                last_result=_result(latest[key]) if key in latest else None,
                already_verified=already,
                will_run=runs,
            )
        )

    if will_run > MAX_PACTS_PER_RUN:
        refusals.append(
            PreviewRefusal(
                code=CODE_TOO_MANY_PACTS,
                message=(
                    f"the selectors choose {will_run} pacts; one run verifies at most {MAX_PACTS_PER_RUN}. "
                    "Narrow the selection (a consumer on each rule, or fewer rules)."
                ),
            )
        )

    missing = sorted(used) if strategy == STRATEGY_NONE else sorted(unhandled)
    return VerifyPreviewResponse(
        provider=provider.slug,
        provider_name=provider.name or provider.slug,
        provider_version=version,
        target=target,
        rules=rules,
        selected=len(selected),
        will_run=will_run,
        skipped=skipped,
        interactions=interactions,
        pacts=pacts,
        truncated=len(selected) > len(pacts),
        states=PreviewStates(
            strategy=strategy,
            used=len(used),
            handled=len(used) - len(missing),
            missing=missing,
            registered=len(states_registered),
        ),
        refusals=refusals,
    )
