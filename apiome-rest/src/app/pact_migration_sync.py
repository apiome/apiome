"""Keep-in-sync passes — PFX-8.17 (#7314).

Pipelines move from the old broker one by one; until the last one has, pacts and results keep
arriving there. With keep-in-sync on, every ``interval`` (15 minutes unless set otherwise) the
sweep in :mod:`app.main` claims the due syncs (:func:`process_migration_sync_sweep`) and runs one
pass of each (:func:`run_sync_pass`):

1. **Open the credentials** sealed when it was switched on. A blob that cannot be opened (the
   master key changed) stops the sync with the reason.
2. **Ask the source if it is there** (``GET /``). When it is not, the pass is recorded as
   unreachable and nothing is copied. After :data:`UNREACHABLE_LIMIT` (24 hours) of that, the sync
   **stops itself and says so** — the credentials are let go and ``stopped_reason`` names the host,
   how long, and the last error.
3. **Copy what is new.** The migration run is set running again, exactly like a resume: the source
   is read and every record the run already imported is skipped, so its documents are not even
   fetched — only what was published since the last pass is copied. The run's agreement check and
   who-has-moved list are refreshed with it.

A pass never overlaps a running migration of the workspace (it waits for the next interval), and a
pass claimed by one replica is not claimed by another.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from . import pact_migration_run_store as run_store
from . import pact_migration_sync_store as sync_store
from .consumer_contract_store import ConsumerActor
from .pact_migration_job import run_migration
from .pact_migration_source import (
    CODE_SOURCE_REFUSED,
    CODE_SOURCE_UNREADABLE,
    SourceBroker,
    SourceError,
)
from .pact_retention import RetentionError, RetentionKeep
from .pact_retention_policy import keep_of
from .pact_retention_policy_store import read_rules

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_INTERVAL_MINUTES",
    "OUTCOME_BUSY",
    "OUTCOME_COPIED",
    "OUTCOME_FAILED",
    "OUTCOME_STOPPED",
    "OUTCOME_UNREACHABLE",
    "UNREACHABLE_LIMIT",
    "SyncSweepCounts",
    "process_migration_sync_sweep",
    "run_sync_pass",
    "workspace_keep",
]

#: How often a sync copies again unless asked otherwise.
DEFAULT_INTERVAL_MINUTES = 15
#: How long a source may be unreachable before the sync stops itself.
UNREACHABLE_LIMIT = timedelta(hours=24)

#: What one pass came to.
OUTCOME_COPIED = "copied"
OUTCOME_FAILED = "failed"
OUTCOME_UNREACHABLE = "unreachable"
OUTCOME_STOPPED = "stopped"
OUTCOME_BUSY = "busy"

#: Errors of a run that mean the source could not be read (they count toward the 24 hours).
_SOURCE_DOWN = frozenset({CODE_SOURCE_UNREADABLE, CODE_SOURCE_REFUSED})

#: Builds the client for a pass: ``(source URL, credentials) -> SourceBroker`` (tests give a transport).
BrokerFactory = Callable[[str, Dict[str, Any]], SourceBroker]


def _default_broker(source: str, credentials: Dict[str, Any]) -> SourceBroker:
    """A client for ``source`` holding the opened credentials."""
    return SourceBroker(
        source,
        token=credentials.get("token"),
        username=credentials.get("username"),
        password=credentials.get("password"),
    )


def workspace_keep(db: Any, tenant_id: str) -> Optional[RetentionKeep]:
    """The workspace's clean-up selectors, or ``None`` when it has saved no keep-rule.

    Without a keep-rule the clean-up keeps only what is deployed and each pacticipant's latest
    version; thinning a migration by that would leave nearly everything behind, so it is not offered.

    Args:
        db: The database.
        tenant_id: The workspace.

    Returns:
        The selectors, or ``None``.
    """
    rules = read_rules(db, tenant_id)
    if not (rules.keep_main_branch_latest or rules.keep_other_branch_latest or rules.keep_tags):
        return None
    try:
        return keep_of(rules)
    except RetentionError:
        return None


def _hours(span: timedelta) -> int:
    """Whole hours in a span."""
    return int(span.total_seconds() // 3600)


def _stop_message(host: str, since: datetime, now: datetime, error: Optional[str]) -> str:
    """What a sync that stopped itself for an unreachable source says."""
    return (
        f"Keep-in-sync stopped itself: {host} could not be read for {_hours(now - since)} hours"
        + (f" (last: {error})" if error else "")
        + ". Nothing was lost; switch it on again once the old broker answers."
    )


def _unreachable(db: Any, sync: Dict[str, Any], host: str, error: str, now: datetime) -> str:
    """Record an unreachable pass; stop the sync once the source has been gone for a day."""
    row = sync_store.record_pass(db, sync["run_id"], ok=False, error=error, unreachable=True) or {}
    since = run_store.as_utc(row.get("unreachable_since")) or now
    if now - since >= UNREACHABLE_LIMIT:
        sync_store.disable_sync(db, sync["tenant_id"], sync["run_id"], reason=_stop_message(host, since, now, error))
        logger.info("pact migration sync %s stopped: %s unreachable since %s", sync["run_id"], host, since)
        return OUTCOME_STOPPED
    return OUTCOME_UNREACHABLE


def run_sync_pass(
    db: Any,
    sync: Dict[str, Any],
    *,
    broker_factory: BrokerFactory = _default_broker,
    clock: Optional[Callable[[], datetime]] = None,
) -> str:
    """Run one keep-in-sync pass.

    Args:
        db: The database.
        sync: The claimed row (credentials included).
        broker_factory: Builds the source client (tests give a mock transport).
        clock: The current time (tests pin it).

    Returns:
        ``copied``, ``failed``, ``unreachable``, ``stopped`` (the sync switched itself off) or
        ``busy`` (a migration of the workspace is running; the next interval tries again). Never
        raises: a failure is recorded on the sync.
    """
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    tenant_id, run_id = sync["tenant_id"], sync["run_id"]
    run = run_store.get_run(db, tenant_id, run_id)
    if run is None or run["mode"] != "copy":
        sync_store.disable_sync(db, tenant_id, run_id, reason="Keep-in-sync stopped: the migration it copied is gone.")
        return OUTCOME_STOPPED
    credentials = sync_store.unseal_credentials(sync.get("credential_ciphertext"), sync.get("key_version"))
    if credentials is None:
        sync_store.disable_sync(
            db,
            tenant_id,
            run_id,
            reason=(
                "Keep-in-sync stopped: the stored credentials can no longer be opened (the encryption key "
                "changed). Switch it on again with the token."
            ),
        )
        return OUTCOME_STOPPED
    try:
        broker = broker_factory(run["source"], credentials)
    except SourceError as exc:
        sync_store.disable_sync(db, tenant_id, run_id, reason=f"Keep-in-sync stopped: {exc}")
        return OUTCOME_STOPPED

    try:
        broker.get("/")
    except SourceError as exc:
        broker.close()
        return _unreachable(db, sync, broker.host, str(exc), now)

    try:
        row = run_store.reopen_run(db, tenant_id, run_id)
    except run_store.RunActiveError:
        broker.close()
        sync_store.record_pass(db, run_id, ok=False, error="A migration was running; this pass waits for the next.")
        return OUTCOME_BUSY
    if row is None:
        broker.close()
        sync_store.disable_sync(db, tenant_id, run_id, reason="Keep-in-sync stopped: the migration it copied is gone.")
        return OUTCOME_STOPPED

    row["options"] = {**(row.get("options") or {}), "restart": False}
    keep = workspace_keep(db, tenant_id)
    if row["options"].get("versions") == "kept" and keep is None:
        broker.close()
        message = "this migration thins versions by the clean-up rules, which were removed since"
        run_store.finish_run(db, run_id, "failed", error=message)
        sync_store.disable_sync(db, tenant_id, run_id, reason=f"Keep-in-sync stopped: {message}.")
        return OUTCOME_STOPPED

    label = sync.get("enabled_by_label") or "someone"
    actor = ConsumerActor(user_id=sync.get("enabled_by"), label=f"keep-in-sync ({label})")
    status = run_migration(db, row, broker, actor=actor, keep=keep, clock=clock)
    if status == "completed":
        sync_store.record_pass(db, run_id, ok=True)
        return OUTCOME_COPIED
    after = run_store.get_run(db, tenant_id, run_id) or {}
    error = after.get("error") or f"the pass ended {status}"
    if (after.get("facts") or {}).get("source_error") in _SOURCE_DOWN:
        return _unreachable(db, sync, broker.host, error, now)
    sync_store.record_pass(db, run_id, ok=False, error=error)
    return OUTCOME_FAILED


@dataclass
class SyncSweepCounts:
    """What one sweep tick did: ``{outcome: passes}``."""

    outcomes: Dict[str, int] = field(default_factory=dict)


def process_migration_sync_sweep(
    db: Any,
    *,
    limit: int = 2,
    run_pass: Callable[..., str] = run_sync_pass,
) -> SyncSweepCounts:
    """Claim the passes that are due and run them, one after the other.

    Args:
        db: The sweep's database handle.
        limit: The most passes one tick runs (each reads a whole broker).
        run_pass: Runs one pass (tests replace it).

    Returns:
        The outcomes.
    """
    counts = SyncSweepCounts()
    claimed: List[Dict[str, Any]] = sync_store.claim_due(db, limit=limit)
    for sync in claimed:
        try:
            outcome = run_pass(db, sync)
        except Exception:  # noqa: BLE001 — one broken pass does not stop the others
            logger.exception("pact migration sync %s broke", sync.get("run_id"))
            outcome = OUTCOME_FAILED
        counts.outcomes[outcome] = counts.outcomes.get(outcome, 0) + 1
    return counts
