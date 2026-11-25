"""Register provider states, and check pacts against them before a run — PFX-3.3 (#6933).

The HTTP face is :mod:`app.pact_provider_state_routes`. This module does two jobs:

**Registering.** A state's body is checked (:func:`app.pact_provider_state.validate_state`), the
provider is resolved in the caller's tenant, and each override's ``target_ref`` is resolved to a
verification target **of the same tenant** — an unknown target is a ``provider-state-invalid``
pointing at the override, never a silent drop — before the store writes it.

**Checking before a run.** :func:`check_provider_states` selects the pacts a verification would
(the same for-verification selection, through
:func:`app.pact_verifier_service.select_provider_pacts`), compiles each as the verifier does, and
reports every provider state their interactions name: whether it is registered, which setup it
would use on the chosen target, and every problem — an unregistered state, a required parameter
an interaction leaves out, a parameter the state does not declare, a setup the target's policy
forbids. ``ready`` is true only when nothing would hold an interaction back. Nothing is sent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .pact_provider_state import (
    CODE_SETUP_BLOCKED,
    CODE_STATE_INVALID,
    CODE_STATE_NOT_REGISTERED,
    SEVERITY_BLOCKING,
    ProviderStateInput,
    ProviderStateRecord,
    StateProblem,
    registry_of,
    setup_for_target,
    state_problems,
    validate_state,
)
from .pact_provider_state_store import (
    ResolvedOverride,
    create_state,
    delete_state,
    get_state,
    list_states,
    replace_state,
)
from .pact_publication import PactPublicationError
from .pact_publication_store import get_pact_by_sha
from .pact_selectors import parse_for_verification_request
from .pact_verifier import MAX_PACTS_PER_RUN
from .pact_verifier_service import (
    CODE_TOO_MANY_PACTS,
    PactVerifierError,
    compile_stored_pact,
    select_provider_pacts,
)
from .pacticipant_store import get_pacticipant
from .verification_target import TargetValidationError
from .verification_target_store import get_target

__all__ = [
    "MAX_USES_LISTED",
    "StateCheckEntry",
    "StateCheckRequest",
    "StateCheckResponse",
    "StateUse",
    "check_provider_states",
    "list_provider_states",
    "read_provider_state",
    "register_provider_state",
    "remove_provider_state",
    "replace_provider_state",
]

#: The most interactions listed under one state in a check (the count is always exact).
MAX_USES_LISTED = 20

#: Problems about the state itself rather than one interaction's use of it.
_STATE_LEVEL = (CODE_STATE_NOT_REGISTERED, CODE_SETUP_BLOCKED)


# =============================================================================================
# Registering
# =============================================================================================


def _resolve_overrides(tenant_id: str, state: ProviderStateInput) -> List[ResolvedOverride]:
    """Resolve each override's target in the caller's tenant.

    Raises:
        PactPublicationError: ``provider-state-invalid`` at ``/overrides/{i}/target_ref`` for a
            target this tenant does not have.
    """
    resolved: List[ResolvedOverride] = []
    seen: List[str] = []
    for index, override in enumerate(state.overrides):
        pointer = f"/overrides/{index}/target_ref"
        try:
            record = get_target(tenant_id, override.target_ref)
        except TargetValidationError as exc:
            raise PactPublicationError(CODE_STATE_INVALID, f"{pointer}: {exc}", pointer=pointer) from exc
        if record.id in seen:
            raise PactPublicationError(
                CODE_STATE_INVALID, f"{pointer}: target '{record.slug}' has two overrides", pointer=pointer
            )
        seen.append(record.id)
        resolved.append(ResolvedOverride(target_id=record.id, target_slug=record.slug, setup=override.setup))
    return resolved


def list_provider_states(db: Any, tenant_id: str, provider_ref: str) -> List[ProviderStateRecord]:
    """A provider's registered states.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    return list_states(db, tenant_id, get_pacticipant(db, tenant_id, provider_ref))


def read_provider_state(db: Any, tenant_id: str, provider_ref: str, state_id: str) -> ProviderStateRecord:
    """One registered state.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``provider-state-not-found``.
    """
    return get_state(db, tenant_id, get_pacticipant(db, tenant_id, provider_ref), state_id)


def register_provider_state(
    db: Any, tenant_id: str, provider_ref: str, body: ProviderStateInput, *, actor: ConsumerActor
) -> ProviderStateRecord:
    """Register a state for a provider.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        body: The state.
        actor: Who is registering it.

    Returns:
        The stored state.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``provider-state-invalid`` (with a pointer) or
            ``provider-state-name-taken``.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    state = validate_state(body)
    return create_state(db, tenant_id, provider, state, _resolve_overrides(tenant_id, state), actor=actor)


def replace_provider_state(
    db: Any, tenant_id: str, provider_ref: str, state_id: str, body: ProviderStateInput, *, actor: ConsumerActor
) -> ProviderStateRecord:
    """Replace a registered state, overrides included.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``provider-state-not-found``, ``provider-state-invalid`` or
            ``provider-state-name-taken``.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    state = validate_state(body)
    overrides = _resolve_overrides(tenant_id, state)
    return replace_state(db, tenant_id, provider, state_id, state, overrides, actor=actor)


def remove_provider_state(db: Any, tenant_id: str, provider_ref: str, state_id: str) -> None:
    """Delete a registered state.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``provider-state-not-found``.
    """
    delete_state(db, tenant_id, get_pacticipant(db, tenant_id, provider_ref), state_id)


# =============================================================================================
# Checking before a run
# =============================================================================================


class StateCheckRequest(BaseModel):
    """Which pacts to check, and on which target."""

    model_config = ConfigDict(extra="forbid")

    selection: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Which pacts — the `selection` of the verify request (the body of `…/for-verification`), "
            "unchanged. Empty selects what a Pact verifier gets by default."
        ),
    )
    target_ref: Optional[str] = Field(
        default=None,
        description=(
            "Slug or id of the verification target the run would use: its overrides are chosen and its "
            "mutating-method policy checked. Omit to check the default setups."
        ),
        max_length=200,
    )


class StateUse(BaseModel):
    """One interaction that names a state."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    pact_version_sha: str = Field(description="The pact version.")
    interaction: str = Field(description="The interaction's description.")
    params: Dict[str, Any] = Field(default_factory=dict, description="The parameters it passes.")


class StateCheckEntry(BaseModel):
    """One provider state the selected pacts name."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="The state, as the interactions write it.")
    registered: bool = Field(description="Whether the provider has registered it.")
    state_id: Optional[str] = Field(default=None, description="The registered state's id.")
    setup_kind: Optional[str] = Field(
        default=None, description="`state_change` or `fixture` — the setup used on the target (or the default)."
    )
    overridden: bool = Field(default=False, description="Whether the target has its own setup for the state.")
    interactions: int = Field(description="How many selected interactions name it.")
    uses: List[StateUse] = Field(default_factory=list, description=f"The interactions, the first {MAX_USES_LISTED}.")
    problems: List[StateProblem] = Field(
        default_factory=list, description="What would hold an interaction back, or is worth knowing."
    )


class StateCheckResponse(BaseModel):
    """Whether a provider can set up every state its pacts name."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="The provider's handle.")
    target: Optional[str] = Field(default=None, description="The target checked against, when one was named.")
    ready: bool = Field(description="True when no interaction would be held back for its provider states.")
    pacts: int = Field(description="How many pacts the selection chose.")
    blocking: int = Field(description="How many blocking problems were found.")
    warnings: int = Field(description="How many warnings were found.")
    states: List[StateCheckEntry] = Field(
        default_factory=list, description="Every state the selected interactions name; unregistered ones first."
    )
    unused: List[str] = Field(default_factory=list, description="Registered states no selected interaction names.")


def check_provider_states(db: Any, tenant_id: str, provider_ref: str, request: StateCheckRequest) -> StateCheckResponse:
    """Check the states a provider's selected pacts name against its registry.

    Args:
        db: The database.
        tenant_id: The caller's tenant; every lookup is scoped to it.
        provider_ref: The provider's handle, id or name.
        request: The selection and the target.

    Returns:
        The report. Nothing is sent to any target.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``.
        PactPublicationError: ``pact-selector-invalid``.
        TargetValidationError: ``target-not-found``.
        PactVerifierError: ``pact-verify-too-many-pacts``.
    """
    query = parse_for_verification_request(dict(request.selection) or None)
    provider, selected = select_provider_pacts(db, tenant_id, provider_ref, query)
    if len(selected) > MAX_PACTS_PER_RUN:
        raise PactVerifierError(
            CODE_TOO_MANY_PACTS,
            f"the selectors choose {len(selected)} pacts; a run verifies at most {MAX_PACTS_PER_RUN}. "
            "Narrow the selection and check again.",
        )
    target = get_target(tenant_id, request.target_ref) if request.target_ref else None
    target_id = target.id if target is not None else None
    allows_mutating = target.policy.allow_mutating_methods if target is not None else None
    registry = registry_of(list_states(db, tenant_id, provider))

    entries: Dict[str, StateCheckEntry] = {}
    for chosen in selected:
        candidate = chosen.candidate
        pact = get_pact_by_sha(db, tenant_id, provider.slug, candidate.consumer_slug, candidate.sha)
        for case in compile_stored_pact(pact).cases:
            if case.pact is None:
                continue
            for state in case.pact.provider_states:
                entry = entries.get(state.name)
                if entry is None:
                    entry = _entry(state.name, registry.get(state.name), target_id)
                    entries[state.name] = entry
                entry.interactions += 1
                if len(entry.uses) < MAX_USES_LISTED:
                    entry.uses.append(
                        StateUse(
                            consumer=candidate.consumer_slug,
                            pact_version_sha=candidate.sha,
                            interaction=case.pact.description,
                            params=dict(state.params),
                        )
                    )
                for problem in state_problems(
                    [state], registry, target_id=target_id, target_allows_mutating=allows_mutating
                ):
                    _add_problem(
                        entry,
                        problem.model_copy(
                            update={"consumer": candidate.consumer_slug, "interaction": case.pact.description}
                        ),
                    )

    states = sorted(entries.values(), key=lambda item: (item.registered, item.name))
    problems = [problem for entry in states for problem in entry.problems]
    blocking = sum(1 for problem in problems if problem.severity == SEVERITY_BLOCKING)
    return StateCheckResponse(
        provider=provider.slug,
        target=target.slug if target is not None else None,
        ready=blocking == 0,
        pacts=len(selected),
        blocking=blocking,
        warnings=len(problems) - blocking,
        states=states,
        unused=sorted(name for name in registry if name not in entries),
    )


def _entry(name: str, registered: Optional[ProviderStateRecord], target_id: Optional[str]) -> StateCheckEntry:
    """A fresh report entry for a state."""
    if registered is None:
        return StateCheckEntry(name=name, registered=False, interactions=0)
    setup, overridden = setup_for_target(registered, target_id)
    return StateCheckEntry(
        name=name,
        registered=True,
        state_id=registered.id,
        setup_kind=setup.kind,
        overridden=overridden,
        interactions=0,
    )


def _add_problem(entry: StateCheckEntry, problem: StateProblem) -> None:
    """Add a problem unless it is already reported.

    A problem with the state itself (not registered, setup blocked) is reported once per state;
    a parameter problem once per interaction, naming it.
    """
    if problem.code in _STATE_LEVEL:
        problem = problem.model_copy(update={"consumer": None, "interaction": None})
    key = (problem.code, problem.parameter, problem.consumer, problem.interaction)
    if any((p.code, p.parameter, p.consumer, p.interaction) == key for p in entry.problems):
        return
    entry.problems.append(problem)
