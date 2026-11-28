"""Provider test scaffolding: reading what the file needs — PFX-8.19 (#7316).

:func:`scaffold_for_provider` selects the provider's pacts with the recommended selectors
(:data:`app.pact_provider_scaffold.RECOMMENDED_SELECTORS`, pending on — what the generated test
itself will fetch), collects every provider state their interactions name with each parameter
and one example value, marks the states the provider has registered in Apiome (PFX-3.3), and
hands them to the pure generator (:func:`app.pact_provider_scaffold.scaffold_provider_test`).

Every lookup is scoped by the caller's tenant: a provider of another workspace is
``pacticipant-not-found``. Nothing is stored, and the caller's credential never reaches the file.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .pact_provider_scaffold import (
    LANGUAGES,
    RECOMMENDED_SELECTORS,
    ProviderScaffold,
    ScaffoldState,
    scaffold_provider_test,
)
from .pact_provider_state import registry_of
from .pact_provider_state_store import list_states
from .pact_publication_store import get_pact_by_sha
from .pact_selectors import parse_for_verification_request
from .pact_verifier import MAX_PACTS_PER_RUN
from .pact_verifier_service import CODE_TOO_MANY_PACTS, PactVerifierError, compile_stored_pact, select_provider_pacts

__all__ = ["ScaffoldResult", "scaffold_for_provider"]


class ScaffoldResult:
    """A scaffold and what it was made from.

    Attributes:
        provider: The provider's handle.
        provider_name: Its name, as the pacts write it.
        pacts: How many pacts the recommended selectors chose.
        scaffold: The file.
    """

    def __init__(self, provider: str, provider_name: str, pacts: int, scaffold: ProviderScaffold) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.pacts = pacts
        self.scaffold = scaffold

    def as_json(self) -> Dict[str, Any]:
        """The REST response body."""
        info = LANGUAGES[self.scaffold.language]
        return {
            "provider": self.provider,
            "provider_name": self.provider_name,
            "language": self.scaffold.language,
            "label": info.label,
            "library": info.library,
            "dependency": info.dependency,
            "file_name": self.scaffold.file_name,
            "content": self.scaffold.content,
            "selectors": [dict(selector) for selector in RECOMMENDED_SELECTORS],
            "pending": True,
            "pacts": self.pacts,
            "states": [
                {
                    "name": state.name,
                    "params": [name for name, _ in state.params],
                    "example": {name: value for name, value in state.params},
                    "registered": state.registered,
                    "setup_kind": state.setup_kind,
                    "interactions": state.interactions,
                    "consumers": list(state.consumers),
                }
                for state in self.scaffold.states
            ],
            "unregistered": sum(1 for state in self.scaffold.states if not state.registered),
            "notices": [notice.as_json() for notice in self.scaffold.notices],
        }


def scaffold_for_provider(db: Any, tenant_id: str, provider_ref: str, language: str) -> ScaffoldResult:
    """Write a provider's verification test from its pacts.

    Args:
        db: The database.
        tenant_id: The caller's tenant; every lookup is scoped to it.
        provider_ref: The provider's handle, id or name.
        language: One of :data:`app.pact_provider_scaffold.LANGUAGES`.

    Returns:
        The scaffold and its provenance.

    Raises:
        ScaffoldError: ``provider-scaffold-language-unsupported`` (checked before any read).
        PacticipantValidationError: ``pacticipant-not-found``.
        PactVerifierError: ``pact-verify-too-many-pacts`` when the selectors choose more than a run takes.
    """
    # Refuse an unknown language before touching the database.
    scaffold_provider_test("", language, [], pacts=1)
    query = parse_for_verification_request(
        {
            "consumerVersionSelectors": [dict(selector) for selector in RECOMMENDED_SELECTORS],
            "includePendingStatus": True,
        }
    )
    provider, selected = select_provider_pacts(db, tenant_id, provider_ref, query)
    if len(selected) > MAX_PACTS_PER_RUN:
        raise PactVerifierError(
            CODE_TOO_MANY_PACTS,
            f"the recommended selectors choose {len(selected)} pacts; a scaffold reads at most {MAX_PACTS_PER_RUN}",
        )
    registry = registry_of(list_states(db, tenant_id, provider))

    params: Dict[str, Dict[str, Any]] = {}
    interactions: Dict[str, int] = {}
    consumers: Dict[str, List[str]] = {}
    for chosen in selected:
        candidate = chosen.candidate
        pact = get_pact_by_sha(db, tenant_id, provider.slug, candidate.consumer_slug, candidate.sha)
        for case in compile_stored_pact(pact).cases:
            if case.pact is None:
                continue
            for state in case.pact.provider_states:
                seen = params.setdefault(state.name, {})
                for name, value in state.params.items():
                    seen.setdefault(name, value)
                interactions[state.name] = interactions.get(state.name, 0) + 1
                whose = consumers.setdefault(state.name, [])
                if candidate.consumer_slug not in whose:
                    whose.append(candidate.consumer_slug)

    states = []
    for name, found in params.items():
        registered = registry.get(name)
        # A registered parameter the pacts never send still gets its declared default as the example.
        for declared in registered.parameters if registered is not None else []:
            found.setdefault(declared.name, declared.default)
        states.append(
            ScaffoldState(
                name=name,
                params=tuple(sorted(found.items())),
                registered=registered is not None,
                setup_kind=registered.setup.kind if registered is not None else None,
                interactions=interactions[name],
                consumers=tuple(consumers[name]),
            )
        )
    scaffold = scaffold_provider_test(provider.name, language, states, pacts=len(selected))
    return ScaffoldResult(provider.slug, provider.name, len(selected), scaffold)
