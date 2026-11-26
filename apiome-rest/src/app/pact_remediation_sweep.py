"""The stale-pact remediation and verification-scheduling worker — PFX-6.2 (#6954).

Wired in :mod:`app.main` beside the other sweeps: every ``APIOME_PACT_REMEDIATION_INTERVAL`` seconds
(default 300) it walks every provider with a pact and, for each consumer's newest pact:

1. **Stale state.** Decides whether the pact is stale (:func:`app.pact_remediation.is_stale`, with
   the pair's effective threshold), records it, and fires ``contract_became_stale`` or
   ``contract_no_longer_stale`` when the state changed.
2. **Re-publish requests.** Moves an open request on — ``republished`` (the consumer published
   again), ``cleared`` (verified meanwhile) or ``expired`` (its window passed: escalated to the
   consumer's and the provider's owners, and ``contract_republish_request_expired`` fired) — or
   opens one for a stale pact (notifying the consumer's owners and firing
   ``contract_republish_requested``).
3. **Scheduling.** Collects the pairs due for a scheduled verification on their cadence
   (:func:`app.pact_remediation.decide_schedule`).

Then it runs the due verifications, at most ``APIOME_PACT_SCHEDULE_BATCH_SIZE`` per tick, each
holding one of the workspace's ``max_concurrent_runs`` slots (session advisory locks shared by every
replica) and the pair's own lock. A pair it cannot run is recorded with the reason — no target, no
provider version known, the target refused — never skipped silently; a pair whose slot or lock is
busy stays due for the next tick.

**Notifying the consumer.** The request goes to the consumer pacticipant's owner team (PFX-6.4,
:mod:`app.pact_owner_routing`) — else the owners of what it is linked to, its consumer-registry
entry, then its project — through owner routing (CDG-2.3), which records it as an unowned finding
under the pacticipant when nobody owns it. The request and its webhooks stand either way.

``APIOME_PACT_REMEDIATION_ENABLED=false`` halts the whole tick, for incident response.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from .db_advisory_lock import SessionAdvisoryLock
from .owner_routing import OUTCOME_ROUTED, OUTCOME_SKIPPED
from .pact_owner_routing import route_pacticipant_finding
from .pact_remediation import (
    ATTEMPT_ERRORED,
    ATTEMPT_FAILED,
    ATTEMPT_SKIPPED,
    ATTEMPT_VERIFIED,
    CODE_NO_PROVIDER_VERSION,
    STATE_EXPIRED,
    EffectiveSettings,
    PairFacts,
    RequestFacts,
    VerificationSettings,
    decide_request,
    decide_schedule,
    is_stale,
    reference_time,
    resolve_settings,
    should_open_request,
)
from .pact_remediation_store import (
    attempts_for_provider,
    close_request,
    get_settings,
    latest_request_at_for_sha,
    open_request,
    open_requests_for_provider,
    override_values_for_provider,
    parse_time,
    providers_with_pacts,
    record_attempt,
    set_escalation_status,
    set_notification_status,
    staleness_for_provider,
    upsert_staleness,
)
from .pact_selectors import PactCandidate
from .pact_webhook import (
    EVENT_BECAME_STALE,
    EVENT_NO_LONGER_STALE,
    EVENT_REPUBLISH_REQUEST_EXPIRED,
    EVENT_REPUBLISH_REQUESTED,
)
from .pact_webhook_events import fire_remediation_event
from .pacticipant import PacticipantRecord
from .pacticipant_store import get_pacticipant

logger = logging.getLogger(__name__)

__all__ = [
    "STATUS_UNLINKED",
    "ScheduledRun",
    "SweepCounts",
    "broker_base_for",
    "execute_scheduled_run",
    "process_pact_remediation_sweep",
    "remediate_provider",
]

#: Before PFX-6.4: the consumer pacticipant was linked to no consumer-registry entry or project.
#: No longer written — an ownerless pacticipant's findings are recorded as unowned — but kept for
#: the requests that carry it.
STATUS_UNLINKED = "unlinked"
#: Routing raised (logged by owner routing).
STATUS_FAILED = "failed"
#: The code of a scheduled run that raised something the verifier does not model.
CODE_INTERNAL = "INTERNAL_ERROR"

#: Builds a session advisory lock (replaced in tests).
LockFactory = Callable[[Any, str], Any]


@dataclass
class SweepCounts:
    """What one tick did."""

    providers: int = 0
    became_stale: int = 0
    no_longer_stale: int = 0
    requests_opened: int = 0
    requests_closed: Dict[str, int] = field(default_factory=dict)
    scheduled_runs: int = 0
    scheduled_recorded_skips: int = 0


@dataclass(frozen=True)
class ScheduledRun:
    """A pair due for a scheduled verification."""

    tenant_id: str
    tenant_slug: str
    provider: PacticipantRecord
    candidate: PactCandidate
    settings: EffectiveSettings
    provider_version: Optional[str]
    provider_branch: Optional[str]


def broker_base_for(tenant_slug: str) -> str:
    """The Pact Broker base URL of a workspace, for links in webhooks fired outside a request.

    Uses ``APIOME_API_PUBLIC_URL`` (else ``APIOME_REPOSITORY_WEBHOOK_BASE_URL``); without either the
    links are relative paths.

    Args:
        tenant_slug: The workspace's handle.

    Returns:
        The base URL, no trailing slash.
    """
    from .config import settings

    root = (settings.api_public_url or settings.repository_webhook_base_url or "").strip().rstrip("/")
    return f"{root}/v1/tenants/{quote(tenant_slug, safe='')}/pact-broker"


def _link(provider: PacticipantRecord) -> str:
    """The provider's Verification page, where the pair's request shows."""
    return f"/ade/dashboard/pacts/pacticipants/{quote(provider.slug, safe='')}/verification"


def _notify(
    db: Any,
    tenant_id: str,
    party: PacticipantRecord,
    *,
    summary: str,
    link: str,
    request_id: str,
    details: Dict[str, Any],
) -> str:
    """Route one finding to a pacticipant's owners (PFX-6.4); returns what routing did.

    The pacticipant's own owner team, else its consumer-registry entry's or project's, else the
    finding is recorded as unowned — see :mod:`app.pact_owner_routing`.
    """
    outcome = route_pacticipant_finding(
        db, tenant_id, party, summary=summary, link=link, finding_id=request_id, details=details
    )
    return STATUS_FAILED if outcome.status == OUTCOME_SKIPPED else outcome.status


def _fire(db: Any, tenant_id: str, tenant_slug: str, event: str, provider: PacticipantRecord, c: PactCandidate) -> int:
    """Fire one remediation event for a pair; returns the deliveries queued."""
    return len(
        fire_remediation_event(
            db,
            tenant_id,
            broker_base_for(tenant_slug),
            event,
            consumer_id=str(c.consumer_id),
            provider_id=provider.id,
            consumer_slug=c.consumer_slug,
            consumer_name=c.consumer_name,
            provider_slug=provider.slug,
            provider_name=provider.name,
            consumer_version=c.version_number,
            sha=c.sha,
        )
    )


def _request_details(provider: PacticipantRecord, c: PactCandidate, threshold: int, request_id: str) -> Dict[str, Any]:
    """The finding payload of a re-publish request: the pact and contract references."""
    return {
        "kind": "pact-republish-request",
        "requestId": request_id,
        "provider": provider.slug,
        "consumer": c.consumer_slug,
        "consumerVersion": c.version_number,
        "pactVersionSha": c.sha,
        "staleThresholdHours": threshold,
    }


def _open_and_notify(
    db: Any,
    tenant_id: str,
    tenant_slug: str,
    provider: PacticipantRecord,
    c: PactCandidate,
    *,
    threshold: int,
    reference_at: datetime,
    window_hours: int,
) -> bool:
    """Open a request for a stale pact, notify the consumer's owners and fire the webhook."""
    request_id = open_request(
        db,
        tenant_id,
        provider.id,
        str(c.consumer_id),
        sha=c.sha,
        consumer_version=c.version_number,
        threshold_hours=threshold,
        reference_at=reference_at,
        window_hours=window_hours,
    )
    if request_id is None:
        return False
    consumer = get_pacticipant(db, tenant_id, str(c.consumer_id))
    status = _notify(
        db,
        tenant_id,
        consumer,
        summary=(
            f"Re-publish requested: {c.consumer_name}'s pact with {provider.name} (version {c.version_number}) "
            f"has not been verified for more than {threshold} h"
        ),
        link=_link(provider),
        request_id=request_id,
        details=_request_details(provider, c, threshold, request_id),
    )
    deliveries = _fire(db, tenant_id, tenant_slug, EVENT_REPUBLISH_REQUESTED, provider, c)
    set_notification_status(db, tenant_id, request_id, status, deliveries)
    return True


def _escalate(
    db: Any,
    tenant_id: str,
    tenant_slug: str,
    provider: PacticipantRecord,
    c: PactCandidate,
    *,
    request_id: str,
    threshold: int,
) -> None:
    """Escalate an expired request to the consumer's and the provider's owners, and fire the webhook."""
    consumer = get_pacticipant(db, tenant_id, str(c.consumer_id))
    summary = (
        f"Re-publish request expired: {c.consumer_name} did not re-publish its pact with {provider.name}, "
        f"unverified for more than {threshold} h"
    )
    details = {**_request_details(provider, c, threshold, request_id), "escalated": True}
    statuses = [
        _notify(db, tenant_id, party, summary=summary, link=_link(provider), request_id=request_id, details=details)
        for party in (consumer, provider)
    ]
    status = OUTCOME_ROUTED if OUTCOME_ROUTED in statuses else statuses[0]
    deliveries = _fire(db, tenant_id, tenant_slug, EVENT_REPUBLISH_REQUEST_EXPIRED, provider, c)
    set_escalation_status(db, tenant_id, request_id, status, deliveries)


def _provider_version(
    db: Any, tenant_id: str, provider: PacticipantRecord, result: Any
) -> Tuple[Optional[str], Optional[str]]:
    """The provider version a scheduled run verifies as: the pact's newest result's, else the provider's newest."""
    from .verification_result_store import list_provider_results

    if result is not None:
        return result.provider_version, result.provider_branch
    newest, _next = list_provider_results(db, tenant_id, provider, limit=1)
    if newest:
        return newest[0].provider_version, newest[0].provider_branch
    return None, None


def remediate_provider(
    db: Any,
    tenant_id: str,
    tenant_slug: str,
    provider_id: str,
    workspace: VerificationSettings,
    *,
    now: datetime,
    counts: SweepCounts,
) -> List[ScheduledRun]:
    """Steps 1–3 of the tick for one provider.

    Args:
        db: The database.
        tenant_id: The provider's workspace.
        tenant_slug: Its handle (for webhook links).
        provider_id: The provider.
        workspace: The workspace's settings.
        now: The tick's time.
        counts: Updated with what was done.

    Returns:
        The pairs due for a scheduled verification.
    """
    from .pact_verification_ops import latest_pacts
    from .verification_result_store import latest_results_by_pact

    provider, latest = latest_pacts(db, tenant_id, provider_id)
    results = latest_results_by_pact(db, tenant_id, provider, [(c.consumer_id, c.sha) for c in latest])
    provider_override, pair_overrides = override_values_for_provider(db, tenant_id, provider.id)
    staleness = staleness_for_provider(db, tenant_id, provider.id)
    requests = open_requests_for_provider(db, tenant_id, provider.id)
    attempts = attempts_for_provider(db, tenant_id, provider.id)
    due: List[ScheduledRun] = []
    for c in latest:
        cid = str(c.consumer_id)
        effective = resolve_settings(workspace, provider_override, pair_overrides.get(cid))
        result = results.get((cid, c.sha))
        last_verified = parse_time(result.created_at) if result is not None else None
        reference = reference_time(last_verified, parse_time(c.published_at))
        if reference is None:
            continue
        threshold = effective.stale_threshold_hours
        stale = is_stale(reference, threshold, now)

        previous = staleness.get(cid)
        if (previous is None and stale) or (previous is not None and bool(previous["stale"]) != stale):
            _fire(db, tenant_id, tenant_slug, EVENT_BECAME_STALE if stale else EVENT_NO_LONGER_STALE, provider, c)
            if stale:
                counts.became_stale += 1
            else:
                counts.no_longer_stale += 1
        upsert_staleness(
            db, tenant_id, provider.id, cid, sha=c.sha, stale=stale, reference_at=reference, threshold_hours=threshold
        )

        pair = PairFacts(
            sha=c.sha,
            consumer_version=c.version_number,
            published_at=parse_time(c.published_at),
            last_verified_at=last_verified,
        )
        has_open = False
        current = requests.get(cid)
        if current is not None:
            facts = RequestFacts(
                sha=current.pact_version_sha,
                requested_at=parse_time(current.requested_at) or now,
                expires_at=parse_time(current.expires_at) or now,
            )
            decision = decide_request(facts, pair, stale, now)
            if decision is None:
                has_open = True
            elif close_request(
                db,
                tenant_id,
                current.id,
                decision,
                resolved_consumer_version=c.version_number if decision != STATE_EXPIRED else None,
            ):
                counts.requests_closed[decision] = counts.requests_closed.get(decision, 0) + 1
                if decision == STATE_EXPIRED:
                    _escalate(db, tenant_id, tenant_slug, provider, c, request_id=current.id, threshold=threshold)
        if should_open_request(
            stale=stale,
            enabled=workspace.republish_requests_enabled,
            has_open_request=has_open,
            last_request_for_sha_at=latest_request_at_for_sha(db, tenant_id, provider.id, cid, c.sha)
            if stale
            else None,
            last_verified_at=last_verified,
        ):
            if _open_and_notify(
                db,
                tenant_id,
                tenant_slug,
                provider,
                c,
                threshold=threshold,
                reference_at=reference,
                window_hours=workspace.request_window_hours,
            ):
                counts.requests_opened += 1

        attempt = attempts.get(cid)
        schedule = decide_schedule(
            effective,
            sha=c.sha,
            has_result=result is not None,
            last_attempt_sha=attempt.pact_version_sha if attempt else None,
            last_attempt_at=parse_time(attempt.attempted_at) if attempt else None,
            last_verified_at=last_verified,
            now=now,
            last_attempt_code=attempt.code if attempt else None,
        )
        if not schedule.due:
            continue
        if schedule.blocked_code:
            record_attempt(
                db,
                tenant_id,
                provider.id,
                cid,
                sha=c.sha,
                status=ATTEMPT_SKIPPED,
                code=schedule.blocked_code,
                reason=schedule.blocked_reason,
            )
            counts.scheduled_recorded_skips += 1
            continue
        version, branch = _provider_version(db, tenant_id, provider, result)
        due.append(ScheduledRun(tenant_id, tenant_slug, provider, c, effective, version, branch))
    return due


def execute_scheduled_run(
    db: Any,
    run: ScheduledRun,
    *,
    lock_factory: LockFactory = SessionAdvisoryLock,
    verify: Optional[Callable[..., Any]] = None,
) -> Optional[str]:
    """Run one due pair and record the attempt; never raises.

    Args:
        db: The database (the tick's dedicated connection).
        run: The due pair.
        lock_factory: Builds the pair's lock (tests).
        verify: Runs the verification (tests); :func:`app.pact_verification_ops.run_scheduled_verification`.

    Returns:
        The recorded status, or ``None`` when the pair was busy and stays due.
    """
    from .pact_publication import PactPublicationError
    from .pact_verification_ops import run_scheduled_verification
    from .pact_verifier_service import PactVerifierError
    from .pacticipant import PacticipantValidationError
    from .verification_target import TargetValidationError

    verify = verify or run_scheduled_verification
    c = run.candidate
    cid = str(c.consumer_id)

    def record(status: str, code: Optional[str] = None, reason: Optional[str] = None) -> str:
        record_attempt(db, run.tenant_id, run.provider.id, cid, sha=c.sha, status=status, code=code, reason=reason)
        return status

    if not run.provider_version:
        return record(
            ATTEMPT_SKIPPED,
            CODE_NO_PROVIDER_VERSION,
            "no provider version is known to verify as: publish a verification result from CI, or Re-run "
            "this pact with a provider version",
        )
    try:
        response = verify(
            db,
            run.tenant_id,
            run.provider,
            c,
            target_ref=run.settings.target,
            provider_version=run.provider_version,
            provider_branch=run.provider_branch,
            broker_base=broker_base_for(run.tenant_slug),
            lock_factory=lock_factory,
        )
    except (PacticipantValidationError, PactVerifierError, TargetValidationError, PactPublicationError) as exc:
        return record(ATTEMPT_ERRORED, getattr(exc, "code", None) or exc.__class__.__name__, str(exc))
    except Exception as exc:  # noqa: BLE001 - one pair never aborts the tick
        logger.exception("scheduled pact verification failed for provider %s", run.provider.slug)
        return record(ATTEMPT_ERRORED, CODE_INTERNAL, str(exc))
    if not response.pacts and response.skipped:
        return None
    if response.success:
        return record(ATTEMPT_VERIFIED)
    return record(ATTEMPT_FAILED, None, f"the verification {response.outcome}")


def _acquire_slot(db: Any, tenant_id: str, limit: int, lock_factory: LockFactory) -> Optional[Any]:
    """One of the workspace's concurrent-run slots, or ``None`` when all are taken."""
    for slot in range(max(1, limit)):
        lock = lock_factory(db, f"apiome.pact_schedule_slot:{tenant_id}:{slot}")
        if lock.acquire():
            return lock
    return None


def process_pact_remediation_sweep(
    db: Any,
    *,
    now: Optional[datetime] = None,
    lock_factory: LockFactory = SessionAdvisoryLock,
    verify: Optional[Callable[..., Any]] = None,
) -> SweepCounts:
    """One tick of the remediation and scheduling worker.

    Args:
        db: The tick's dedicated database handle (the advisory locks are session-scoped).
        now: The tick's time (tests).
        lock_factory: Builds the slot and pair locks (tests).
        verify: Runs a scheduled verification (tests).

    Returns:
        What the tick did.
    """
    from .config import settings

    counts = SweepCounts()
    if not settings.pact_remediation_enabled:
        logger.info("pact remediation sweep halted: APIOME_PACT_REMEDIATION_ENABLED is disabled")
        return counts
    moment = now or datetime.now(timezone.utc)
    try:
        providers = providers_with_pacts(db, limit=max(1, int(settings.pact_remediation_max_providers)))
    except Exception:  # noqa: BLE001 - a failed selection retries on the next tick
        logger.exception("pact remediation sweep: provider selection failed")
        return counts

    workspaces: Dict[str, VerificationSettings] = {}
    due: List[ScheduledRun] = []
    for tenant_id, tenant_slug, provider_id in providers:
        try:
            if tenant_id not in workspaces:
                workspaces[tenant_id] = get_settings(db, tenant_id)
            due += remediate_provider(
                db, tenant_id, tenant_slug, provider_id, workspaces[tenant_id], now=moment, counts=counts
            )
            counts.providers += 1
        except Exception:  # noqa: BLE001 - one provider never aborts the tick
            logger.exception("pact remediation sweep failed for provider %s", provider_id)

    budget = max(0, int(settings.pact_schedule_batch_size))
    for run in due:
        if budget <= 0:
            break
        slot = _acquire_slot(db, run.tenant_id, workspaces[run.tenant_id].max_concurrent_runs, lock_factory)
        if slot is None:
            continue
        try:
            if execute_scheduled_run(db, run, lock_factory=lock_factory, verify=verify) is not None:
                counts.scheduled_runs += 1
                budget -= 1
        finally:
            slot.release()
    logger.info(
        "pact remediation sweep: providers=%d stale+%d stale-%d requests+%d closed=%s scheduled=%d",
        counts.providers,
        counts.became_stale,
        counts.no_longer_stale,
        counts.requests_opened,
        counts.requests_closed,
        counts.scheduled_runs,
    )
    return counts
