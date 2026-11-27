"""Resolving and running a pre-publish pact check — PFX-8.4 (#7301). Reads only.

:mod:`app.pact_check` parses the request and shapes the answer; this module resolves each
provider-version selector inside the caller's tenant, reads the provider contracts it names and
compares the pact with each one through :func:`app.bidirectional_store.compare_with_target` — the
function a publish stores the result of — so the answer for a version is the verdict a publish
would record against it.

**Nothing is written.** Every statement here is a ``SELECT``. A ``draft:`` selector renders the
revision through :func:`app.rendered_documents.rendered_document`, the cache ``GET /v1/schema``
reads through as well; it stores no pact, version, contract or verification result.

**Tenancy.** The provider is resolved in the caller's tenant; every other id comes from its rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bidirectional_store import compare_with_target, list_contract_targets
from .bidirectional_verification import MAX_CONTRACTS_PER_PACT, ContractTarget
from .pact_check import (
    KIND_DEPLOYED,
    KIND_DRAFT,
    KIND_MAIN,
    CheckRequest,
    CheckSelector,
    TargetResult,
    check_summary,
    interaction_entries,
)
from .pact_publication import pact_consumer_name, pact_content_sha, pact_provider_name
from .pacticipant import CODE_NOT_FOUND, PacticipantRecord, PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .provider_contract import ApiomeReference, ProviderContractError
from .provider_contract_source import render_apiome_contract, resolve_apiome_source

__all__ = ["CheckOutcome", "run_check"]

#: Where each published provider version's contract came from, when it was rendered from Apiome.
#: %s: provider id, version ids.
_SOURCES_SELECT = """
    SELECT p.provider_version_id::text AS version_id, p.source_project_id::text AS source_project_id,
           p.source_project_slug, p.source_version_label
    FROM apiome.provider_contract_publication p
    WHERE p.provider_id = %s::uuid AND p.provider_version_id = ANY(%s::uuid[])
      AND p.source_project_slug IS NOT NULL
"""

_CONTRACT_SELECT = "SELECT content FROM apiome.provider_contract WHERE id = %s::uuid AND provider_id = %s::uuid"


@dataclass
class CheckOutcome:
    """Everything one check compared, and everything it could not.

    Attributes:
        consumer: The consumer the pact names.
        provider: The provider the pact names.
        provider_slug: The provider pacticipant's handle, ``None`` when not registered.
        sha: The pact's content address (what a publish would store it under).
        interactions: How many interactions and messages the pact carries.
        results: One entry per provider version compared, newest selector first.
        unresolved: ``{"selector", "reason"}`` for every selector that named nothing.
        skipped: ``{"selector", "providerVersion", "reason"}`` for versions over the limit.
    """

    consumer: Optional[str]
    provider: str
    provider_slug: Optional[str]
    sha: str
    interactions: int
    results: List[TargetResult] = field(default_factory=list)
    unresolved: List[Dict[str, str]] = field(default_factory=list)
    skipped: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for the API."""
        return {
            "consumer": {"name": self.consumer},
            "provider": {
                "name": self.provider,
                "slug": self.provider_slug,
                "registered": self.provider_slug is not None,
            },
            "pactVersionSha": self.sha,
            "interactions": self.interactions,
            "summary": check_summary(self.results, self.unresolved, self.skipped),
            "results": [result.to_dict() for result in self.results],
            "unresolved": list(self.unresolved),
            "skipped": list(self.skipped),
        }


def _unresolved(selector: CheckSelector, reason: str) -> Dict[str, str]:
    """One ``unresolved`` entry."""
    return {"selector": selector.raw, "reason": reason}


def _resolve(
    selector: CheckSelector, provider: PacticipantRecord, targets: Sequence[ContractTarget]
) -> Tuple[List[ContractTarget], Optional[str], str]:
    """The published provider versions a (non-draft) selector names.

    Args:
        selector: A ``main``, ``deployed:`` or ``version:`` selector.
        provider: The provider.
        targets: Its versions with a provider contract, oldest first.

    Returns:
        The versions (newest first), why none matched (``None`` when some did), and the reason
        each matched one is listed under.
    """
    newest = sorted(targets, key=lambda target: target.version_seq, reverse=True)
    if selector.kind == KIND_MAIN:
        branch = provider.main_branch
        if not branch:
            return [], f"{provider.name} has no main branch recorded; set it on its pacticipant page", ""
        head = next((target for target in newest if branch in target.branches), None)
        if head is None:
            return (
                [],
                f"no version of {provider.name} on its main branch '{branch}' has published a provider contract",
                "",
            )
        return [head], None, f"main branch {branch}"
    if selector.kind == KIND_DEPLOYED:
        wanted = (selector.value or "").casefold()
        found = [target for target in newest if any(env.casefold() == wanted for env in target.environments)]
        if not found:
            return (
                [],
                f"no version of {provider.name} with a provider contract is deployed to or "
                f"released in '{selector.value}'",
                "",
            )
        return found, None, f"deployed to {selector.value}"
    match = next((target for target in newest if target.version_number == selector.value), None)
    if match is None:
        return [], f"{provider.name} has no version '{selector.value}' with a provider contract", ""
    return [match], None, f"version {selector.value}"


def _sources(db: Any, provider_id: str, targets: Sequence[ContractTarget]) -> Dict[str, Dict[str, Any]]:
    """The Apiome project and version each target's contract was rendered from, by version id."""
    if not targets:
        return {}
    rows = db.execute_query(_SOURCES_SELECT, (provider_id, [target.version_id for target in targets])) or []
    return {
        row["version_id"]: {
            "projectId": row.get("source_project_id"),
            "projectSlug": row["source_project_slug"],
            "versionLabel": row["source_version_label"],
        }
        for row in rows
    }


def _compare(pact: Dict[str, Any], contract: Any, target: ContractTarget, result: TargetResult) -> TargetResult:
    """Fill ``result`` with the comparison a publish would store for ``target``."""
    stored = compare_with_target(pact, contract, target)
    payload = stored.payload
    result.verdict = stored.verdict
    result.comparison_verdict = payload.get("comparisonVerdict", stored.verdict)
    result.success = stored.success
    result.evidence = (payload.get("providerContractEvidence") or {}).get("status")
    error = payload.get("error")
    if isinstance(error, dict):
        result.error = str(error.get("message") or "the comparison could not run")
    result.interactions = interaction_entries(pact, contract, payload)
    return result


def _draft(
    db: Any, tenant_id: str, provider: PacticipantRecord, pact: Dict[str, Any], selector: CheckSelector
) -> Tuple[Optional[TargetResult], Optional[str]]:
    """Compare the pact with a revision of the provider's bound project, as it stands now.

    Returns:
        The result, or ``None`` and why the selector names nothing.
    """
    if not provider.project_id:
        return None, f"{provider.name} is not bound to an Apiome project, so it has no draft to compare with"
    try:
        source = resolve_apiome_source(
            db, tenant_id, provider.name, ApiomeReference(project=None, version=selector.value or "")
        )
        contract = render_apiome_contract(db, tenant_id, source)
    except ProviderContractError as exc:
        return None, str(exc)
    target = ContractTarget(
        version_id=source.version_id,
        version_number=source.version_label,
        version_seq=0,
        contract_id="",
        contract_sha=contract.sha,
        evidence=None,
    )
    result = TargetResult(
        selectors=[selector.raw],
        reasons=[f"draft {source.version_label} of {source.project_slug}"],
        provider_version=source.version_label,
        draft=True,
        source={
            "projectId": source.project_id,
            "projectSlug": source.project_slug,
            "versionLabel": source.version_label,
        },
    )
    return _compare(pact, contract.document, target, result), None


def run_check(db: Any, tenant_id: str, request: CheckRequest, *, interactions: int) -> CheckOutcome:
    """Run a check.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        request: The parsed request; its pact already validated (:func:`app.pact_publication.validate_pact_document`).
        interactions: How many interactions and messages the pact carries.

    Returns:
        The outcome: one result per provider version (a version two selectors name is compared
        once and lists both), every selector that named nothing, and every version over
        :data:`MAX_CONTRACTS_PER_PACT`.

    Raises:
        PacticipantValidationError: For a provider name that is not valid as a handle.
    """
    pact = request.pact
    provider_name = pact_provider_name(pact) or ""
    outcome = CheckOutcome(
        consumer=pact_consumer_name(pact),
        provider=provider_name,
        provider_slug=None,
        sha=pact_content_sha(pact),
        interactions=interactions,
    )
    try:
        provider = get_pacticipant(db, tenant_id, provider_name)
    except PacticipantValidationError as exc:
        if exc.code != CODE_NOT_FOUND:
            raise
        reason = f"{provider_name} is not registered in this workspace yet, so it has no version to compare with"
        outcome.unresolved = [_unresolved(selector, reason) for selector in request.selectors]
        return outcome
    outcome.provider = provider.name
    outcome.provider_slug = provider.slug
    targets = list_contract_targets(db, provider.id)

    chosen: Dict[str, Tuple[ContractTarget, TargetResult]] = {}
    order: List[str] = []
    drafts: List[TargetResult] = []
    for selector in request.selectors:
        if selector.kind == KIND_DRAFT:
            if len(order) + len(drafts) >= MAX_CONTRACTS_PER_PACT:
                outcome.skipped.append(
                    {"selector": selector.raw, "providerVersion": selector.value or "", "reason": _limit_reason()}
                )
                continue
            result, reason = _draft(db, tenant_id, provider, pact, selector)
            if result is None:
                outcome.unresolved.append(_unresolved(selector, reason or "nothing to compare with"))
            else:
                drafts.append(result)
            continue
        found, reason, why = _resolve(selector, provider, targets)
        if not found:
            outcome.unresolved.append(_unresolved(selector, reason or "nothing to compare with"))
            continue
        for target in found:
            if target.version_id in chosen:
                entry = chosen[target.version_id][1]
                if selector.raw not in entry.selectors:
                    entry.selectors.append(selector.raw)
                if why not in entry.reasons:
                    entry.reasons.append(why)
                continue
            if len(order) + len(drafts) >= MAX_CONTRACTS_PER_PACT:
                outcome.skipped.append(
                    {"selector": selector.raw, "providerVersion": target.version_number, "reason": _limit_reason()}
                )
                continue
            chosen[target.version_id] = (
                target,
                TargetResult(
                    selectors=[selector.raw],
                    reasons=[why],
                    provider_version=target.version_number,
                    branches=target.branches,
                    environments=target.environments,
                ),
            )
            order.append(target.version_id)

    sources = _sources(db, provider.id, [chosen[version_id][0] for version_id in order])
    for version_id in order:
        target, result = chosen[version_id]
        result.source = sources.get(version_id)
        rows = db.execute_query(_CONTRACT_SELECT, (target.contract_id, provider.id)) or []
        contract = rows[0]["content"] if rows else None
        if contract is None:
            outcome.unresolved.append(
                {
                    "selector": result.selectors[0],
                    "reason": f"the provider contract of {target.version_number} could not be read",
                }
            )
            continue
        outcome.results.append(_compare(pact, contract, target, result))
    outcome.results.extend(drafts)
    return outcome


def _limit_reason() -> str:
    """Why a version was not compared."""
    return f"over the limit of {MAX_CONTRACTS_PER_PACT} provider versions compared per check"
