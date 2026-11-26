"""Pacticipant owners and the Pact findings routed to them — PFX-6.4 (#6956).

A pacticipant can have an owner team (CDG-2.2 kind ``pacticipant``, apiome-db V450), assigned on its
page in the Contracts workspace or through ``PUT /v1/tenants/{t}/owners/pacticipant/{id}``. This
module decides **which owner a Pact finding about a pacticipant goes to** and routes it with owner
routing (CDG-2.3), so the team's members get an inbox notification and its chat channel a post:

1. the pacticipant's own confirmed owner team;
2. else the confirmed owner of what it is bound to — its consumer-registry entry (``consumer``),
   then its Apiome project (``project``) — the routing PFX-6.2 used before pacticipants had owners;
3. else nobody owns it: the finding is routed under the pacticipant itself, so owner routing
   records it in the **Unowned findings** report (or sends it to the workspace's catch-all team).

Nothing is dropped: every finding ends as ``routed``, ``throttled``, ``unowned``, ``catch_all`` or
``skipped`` (owner routing could not write it, logged there).

Findings:

* the PFX-6.2 remediation sweep's re-publish requests and their escalations
  (:mod:`app.pact_remediation_sweep` calls :func:`route_pacticipant_finding`);
* a **failed verification result** — published by a Pact verifier or run by Apiome's hosted
  verifier — sent to the provider's and the consumer's owners (:func:`notify_failed_verification`).

Every finding uses the inbox type ``owner_verification_drift``, so the notification preferences a
person already set for verification drift apply. Owner routing throttles each (team, entity,
finding type) to one notification an hour.

Routing is advisory: nothing here raises, so a publish or a sweep never fails because a
notification could not be written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

from .owner_routing import (
    OUTCOME_SKIPPED,
    TYPE_OWNER_VERIFICATION_DRIFT,
    OwnerFinding,
    RoutingOutcome,
    owner_recipients,
    route_owner_finding_safely,
)
from .pacticipant import PacticipantRecord, PacticipantValidationError
from .pacticipant_store import get_pacticipant
from .verification_result import VerificationResultRecord

__all__ = [
    "KIND_PACTICIPANT",
    "ROLE_CONSUMER",
    "ROLE_PROVIDER",
    "OwnerTarget",
    "notify_failed_verification",
    "resolve_owner_target",
    "route_pacticipant_finding",
]

logger = logging.getLogger(__name__)

#: The owner kind of a pacticipant (apiome-db V450).
KIND_PACTICIPANT = "pacticipant"
#: The pacticipant a failed verification is told to, by its part in the pact.
ROLE_PROVIDER = "provider"
ROLE_CONSUMER = "consumer"


@dataclass(frozen=True)
class OwnerTarget:
    """Where a finding about a pacticipant is routed.

    Attributes:
        kind: The owner kind routed under: ``pacticipant``, ``consumer`` or ``project``.
        entity_id: The entity of that kind.
        team_id: Its confirmed owner team, or ``None`` when nobody owns it (the finding is then
            recorded as unowned under the pacticipant).
    """

    kind: str
    entity_id: str
    team_id: Optional[str] = None


def _candidates(pacticipant: PacticipantRecord) -> List[Tuple[str, str]]:
    """The entities whose owner may receive a pacticipant's findings, in order of precedence.

    Args:
        pacticipant: The pacticipant.

    Returns:
        ``(kind, id)`` pairs: the pacticipant, then its consumer-registry entry and its project
        when it is bound to them.
    """
    found = [(KIND_PACTICIPANT, pacticipant.id)]
    if pacticipant.consumer_id:
        found.append(("consumer", str(pacticipant.consumer_id)))
    if pacticipant.project_id:
        found.append(("project", str(pacticipant.project_id)))
    return found


def resolve_owner_target(db: Any, tenant_id: str, pacticipant: PacticipantRecord) -> OwnerTarget:
    """Pick the owner a finding about ``pacticipant`` goes to.

    The first of the pacticipant, its consumer-registry entry and its project that has a
    **confirmed** owner team wins (a suggested owner never receives anything). With none, the
    target is the pacticipant itself with no team, so the finding is reported as unowned.

    Args:
        db: Database handle.
        tenant_id: The pacticipant's tenant.
        pacticipant: The pacticipant.

    Returns:
        The target. A failed owner read is logged and treated as "no owner" for that candidate.
    """
    for kind, entity_id in _candidates(pacticipant):
        try:
            owner = owner_recipients(db, tenant_id, kind, entity_id)
        except Exception:  # noqa: BLE001 - a read problem never stops a notification
            logger.exception("pact owners: could not read the owner of %s %s", kind, entity_id)
            continue
        if owner is not None:
            return OwnerTarget(kind=kind, entity_id=entity_id, team_id=owner.team.id)
    return OwnerTarget(kind=KIND_PACTICIPANT, entity_id=pacticipant.id)


def route_pacticipant_finding(
    db: Any,
    tenant_id: str,
    pacticipant: PacticipantRecord,
    *,
    summary: str,
    link: Optional[str],
    finding_id: Optional[str],
    details: Mapping[str, Any],
    target: Optional[OwnerTarget] = None,
) -> RoutingOutcome:
    """Route one Pact finding about a pacticipant to its owner team.

    Args:
        db: Database handle.
        tenant_id: The pacticipant's tenant.
        pacticipant: The pacticipant the finding is about.
        summary: One sentence for the inbox and the chat message.
        link: Relative deep link into the app.
        finding_id: The producer's id (a re-publish request, a verification result).
        details: Extra payload keys; ``pacticipant`` (the handle) and ``ownerSource`` (the kind the
            owner was found on) are added.
        target: A target already resolved by the caller, to avoid reading the owners twice.

    Returns:
        What owner routing did; ``skipped`` when it could not write the finding (logged).
    """
    chosen = target or resolve_owner_target(db, tenant_id, pacticipant)
    payload: Dict[str, Any] = {
        **dict(details),
        "pacticipant": pacticipant.slug,
        "ownerSource": chosen.kind,
    }
    return route_owner_finding_safely(
        db,
        OwnerFinding(
            tenant_id=tenant_id,
            entity_kind=chosen.kind,
            entity_id=chosen.entity_id,
            finding_type=TYPE_OWNER_VERIFICATION_DRIFT,
            summary=summary,
            link=link,
            finding_id=finding_id,
            entity_name=pacticipant.name,
            details=payload,
        ),
    )


def _result_link(result: VerificationResultRecord) -> str:
    """The result's page in the Contracts workspace (PFX-5.5)."""
    provider = quote(result.provider_slug, safe="")
    return f"/ade/dashboard/pacts/pacticipants/{provider}/verification/results/{quote(result.id, safe='')}"


def _failure_summary(result: VerificationResultRecord) -> str:
    """One sentence saying which provider version failed which consumer's pact."""
    consumer_version = f" (version {result.consumer_version})" if result.consumer_version else ""
    summary = (
        f"Verification failed: {result.provider_name} {result.provider_version} did not verify "
        f"{result.consumer_name}'s pact{consumer_version}"
    )
    if result.pact_pending:
        summary += "; the pact is pending, so it does not block deploys"
    return summary


def _failure_details(result: VerificationResultRecord, role: str) -> Dict[str, Any]:
    """The finding payload of a failed verification, for the party in ``role``."""
    return {
        "kind": "pact-verification-failed",
        "role": role,
        "resultId": result.id,
        "provider": result.provider_slug,
        "consumer": result.consumer_slug,
        "providerVersion": result.provider_version,
        "consumerVersion": result.consumer_version,
        "pactVersionSha": result.sha,
        "verificationNumber": result.number,
        "pending": bool(result.pact_pending),
        "buildUrl": result.build_url,
    }


def _party(db: Any, tenant_id: str, slug: str) -> Optional[PacticipantRecord]:
    """Read one party of the result, or ``None`` when it is gone (deleted since)."""
    try:
        return get_pacticipant(db, tenant_id, slug)
    except PacticipantValidationError:
        logger.warning("pact owners: pacticipant %s is gone; its owners are not told", slug)
        return None


def notify_failed_verification(
    db: Any, tenant_id: str, result: VerificationResultRecord
) -> Dict[str, str]:
    """Tell the provider's and the consumer's owners that a verification result failed.

    Call it after the result has committed. A passing result tells nobody. When both parties
    resolve to the same owner team (one team owns both, or both are bound to the same project),
    the team is told once, about the provider.

    Args:
        db: Database handle.
        tenant_id: The result's tenant.
        result: The stored result.

    Returns:
        What happened per role (``provider`` / ``consumer``): an owner-routing outcome, or
        ``same-team`` when the consumer's team was already told about the provider. Empty for a
        passing result. Never raises.
    """
    if result.success:
        return {}
    outcomes: Dict[str, str] = {}
    try:
        told: Optional[str] = None
        for role, slug in ((ROLE_PROVIDER, result.provider_slug), (ROLE_CONSUMER, result.consumer_slug)):
            party = _party(db, tenant_id, slug)
            if party is None:
                outcomes[role] = OUTCOME_SKIPPED
                continue
            target = resolve_owner_target(db, tenant_id, party)
            if target.team_id is not None and target.team_id == told:
                outcomes[role] = "same-team"
                continue
            outcome = route_pacticipant_finding(
                db,
                tenant_id,
                party,
                summary=_failure_summary(result),
                link=_result_link(result),
                finding_id=result.id,
                details=_failure_details(result, role),
                target=target,
            )
            outcomes[role] = outcome.status
            told = target.team_id or told
    except Exception:  # noqa: BLE001 - a notification never fails the verification
        logger.exception("pact owners: failed to notify owners of verification result %s", result.id)
    return outcomes
