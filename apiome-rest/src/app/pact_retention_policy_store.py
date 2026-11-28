"""Reading, saving, previewing and running a workspace's clean-up rules — PFX-8.14 (#7311).

:mod:`app.pact_retention_policy` holds the models; this module talks to ``pact_retention_policy``
(apiome-db V456) and to the planner of :mod:`app.pact_retention_store`:

* :func:`get_policy` / :func:`save_policy` — the Clean-up tab and ``apiome pact retention show|set``.
  Saving appends one ``pacts.retention.policy`` audit row in the same transaction.
* :func:`preview_policy` — *If it ran now*: the saved rules (or a draft) planned exactly as the
  nightly run plans them, with the pacts and results that go with each version.
* :func:`run_nightly_clean_up` — the retention tick: each workspace with clean-up on runs once a day
  after 02:00 UTC. The row is claimed ``FOR UPDATE SKIP LOCKED``, so two replicas never both run it,
  and the plan is made and applied inside that transaction. A refused run (too many versions) stores
  its reason in ``last_run_error`` and deletes nothing.
* :func:`list_recently_deleted` — the deleted pacticipants and the versions deleted on their own,
  newest first, with when each is purged under the workspace's restore window.

**The preview is the next sweep.** Both call :func:`app.pact_retention_store.plan_tx` with the same
rules → selectors mapping (:func:`app.pact_retention_policy.keep_of`), the same scope (every live
pacticipant) and the same restore window, so what the preview lists is what the sweep deletes when
nothing is published or deployed in between.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .consumer_contract_store import ConsumerActor
from .pact_cleanup_store import audit_tx, grace_days
from .pact_retention import RetentionError
from .pact_retention_policy import (
    NIGHTLY_HOUR_UTC,
    DeletedItem,
    DeletedPage,
    RetentionLastRun,
    RetentionPolicy,
    RetentionPreview,
    RetentionRules,
    is_due,
    keep_of,
    next_run_at,
    rules_from_row,
)
from .pact_retention_store import apply_tx, cursor_fetch, plan_tx, scope_of
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_BAD_CURSOR",
    "NIGHTLY_ACTOR",
    "NIGHTLY_REASON",
    "get_policy",
    "list_recently_deleted",
    "preview_policy",
    "read_rules",
    "run_nightly_clean_up",
    "save_policy",
]

logger = logging.getLogger(__name__)

CODE_BAD_CURSOR = "pact-retention-bad-cursor"

#: Who the nightly clean-up deletes as: the Recently deleted list's *By* column reads "Clean-up".
NIGHTLY_ACTOR = ConsumerActor(user_id=None, label="Clean-up")
#: The reason stored on every version the nightly clean-up deletes.
NIGHTLY_REASON = "Nightly clean-up"
#: The most workspaces one tick runs; the rest run on the next tick (every few minutes).
MAX_TENANTS_PER_TICK = 20
#: The most rows a Recently deleted page holds.
MAX_DELETED_PAGE = 100

_COLUMNS = """
    keep_main_branch_latest, keep_other_branch_latest, keep_other_branch_days, keep_tags,
    nightly_enabled, restore_window_days, last_run_at, last_run_deleted, last_run_remaining,
    last_run_error, updated_by_label, updated_at
"""

_READ = f"SELECT {_COLUMNS} FROM apiome.pact_retention_policy WHERE tenant_id = %s::uuid"

_UPSERT = f"""
    INSERT INTO apiome.pact_retention_policy (
        tenant_id, keep_main_branch_latest, keep_other_branch_latest, keep_other_branch_days,
        keep_tags, nightly_enabled, restore_window_days, updated_by, updated_by_label, updated_at)
    VALUES (%s::uuid, %s, %s, %s, %s::text[], %s, %s, %s::uuid, %s, CURRENT_TIMESTAMP)
    ON CONFLICT (tenant_id) DO UPDATE SET
        keep_main_branch_latest = EXCLUDED.keep_main_branch_latest,
        keep_other_branch_latest = EXCLUDED.keep_other_branch_latest,
        keep_other_branch_days = EXCLUDED.keep_other_branch_days,
        keep_tags = EXCLUDED.keep_tags,
        nightly_enabled = EXCLUDED.nightly_enabled,
        restore_window_days = EXCLUDED.restore_window_days,
        updated_by = EXCLUDED.updated_by,
        updated_by_label = EXCLUDED.updated_by_label,
        updated_at = CURRENT_TIMESTAMP
    RETURNING {_COLUMNS}
"""

_DUE = """
    SELECT tenant_id::text AS tenant_id
    FROM apiome.pact_retention_policy
    WHERE nightly_enabled AND (last_run_at IS NULL OR last_run_at < %s)
    ORDER BY last_run_at NULLS FIRST, tenant_id
    LIMIT %s
"""

_CLAIM = f"""
    SELECT {_COLUMNS} FROM apiome.pact_retention_policy
    WHERE tenant_id = %s::uuid AND nightly_enabled
    FOR UPDATE SKIP LOCKED
"""

_RECORD_RUN = """
    UPDATE apiome.pact_retention_policy
    SET last_run_at = %s, last_run_deleted = %s, last_run_remaining = %s, last_run_error = %s
    WHERE tenant_id = %s::uuid
    RETURNING tenant_id::text AS tenant_id
"""

# The deleted pacticipants of a tenant, newest first (V456 idx_pacticipant_tenant_deleted), with what
# was deleted along with each.
_DELETED_PACTICIPANTS = """
    SELECT 'pacticipant' AS kind, p.id::text AS id, p.id::text AS pacticipant_id,
           p.slug AS pacticipant_slug, p.name AS pacticipant_name, NULL::text AS number,
           p.deleted_at, p.deleted_by_label AS deleted_by, 'pacticipant' AS cause, p.delete_reason AS reason,
           (SELECT count(*) FROM apiome.pacticipant_version v
            WHERE v.pacticipant_id = p.id AND v.delete_cause = 'pacticipant') AS versions,
           (SELECT count(*) FROM apiome.pact_publication pp
            JOIN apiome.pacticipant_version v ON v.id = pp.consumer_version_id AND v.pacticipant_id = pp.consumer_id
            WHERE pp.consumer_id = p.id AND v.delete_cause = 'pacticipant') AS pacts,
           (SELECT count(*) FROM apiome.verification_result r
            JOIN apiome.pacticipant_version v ON v.id = r.provider_version_id AND v.pacticipant_id = r.provider_id
            WHERE r.provider_id = p.id AND v.delete_cause = 'pacticipant') AS results
    FROM apiome.pacticipant p
    WHERE p.tenant_id = %s::uuid AND p.deleted_at IS NOT NULL{after}
    ORDER BY p.deleted_at DESC, p.id DESC
    LIMIT %s
"""

# The versions of a tenant's live pacticipants deleted on their own (by hand or by clean-up), newest
# first (V456 idx_pacticipant_version_deleted_by_pacticipant).
_DELETED_VERSIONS = """
    SELECT 'version' AS kind, v.id::text AS id, p.id::text AS pacticipant_id,
           p.slug AS pacticipant_slug, p.name AS pacticipant_name, v.number,
           v.deleted_at, v.deleted_by_label AS deleted_by, v.delete_cause AS cause, v.delete_reason AS reason,
           0 AS versions,
           (SELECT count(*) FROM apiome.pact_publication pp
            WHERE pp.consumer_version_id = v.id AND pp.consumer_id = v.pacticipant_id) AS pacts,
           (SELECT count(*) FROM apiome.verification_result r
            WHERE r.provider_version_id = v.id AND r.provider_id = v.pacticipant_id) AS results
    FROM apiome.pacticipant p
    JOIN apiome.pacticipant_version v
      ON v.pacticipant_id = p.id AND v.deleted_at IS NOT NULL AND v.delete_cause <> 'pacticipant'
    WHERE p.tenant_id = %s::uuid AND p.deleted_at IS NULL{after}
    ORDER BY v.deleted_at DESC, v.id DESC
    LIMIT %s
"""


def _aware(value: Any) -> Optional[datetime]:
    """A timestamp column as a timezone-aware ``datetime``, or ``None``."""
    if value is None:
        return None
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 text of a timestamp column, or ``None``."""
    stamp = _aware(value)
    return stamp.isoformat() if stamp else None


def _read_row(db: Any, tenant_id: str) -> Optional[Dict[str, Any]]:
    """The tenant's stored policy row, or ``None`` when it never saved one."""
    if not is_uuid_string(str(tenant_id or "")):
        return None
    rows = db.execute_query(_READ, (tenant_id,)) or []
    return dict(rows[0]) if rows else None


def _rules(row: Optional[Dict[str, Any]]) -> RetentionRules:
    """The rules of a stored row; without one, the defaults with the deployment's restore window.

    The purge uses the same default (:func:`app.pact_cleanup_store.tenant_grace_days`), so a
    workspace that never saved rules is told the window it actually gets.
    """
    if row:
        return rules_from_row(row)
    return RetentionRules(restore_window_days=min(365, grace_days()))


def read_rules(db: Any, tenant_id: str) -> RetentionRules:
    """The tenant's saved rules, or the defaults (clean-up off, the deployment's restore window).

    Args:
        db: The database.
        tenant_id: The tenant.

    Returns:
        The rules.
    """
    return _rules(_read_row(db, tenant_id))


def _policy_from_row(row: Optional[Dict[str, Any]], *, can_edit: bool, now: datetime) -> RetentionPolicy:
    """The API answer for a stored row (or the defaults)."""
    rules = _rules(row)
    last_at = _aware((row or {}).get("last_run_at"))
    last_run = None
    if row and last_at:
        last_run = RetentionLastRun(
            at=last_at.isoformat(),
            deleted=row.get("last_run_deleted"),
            remaining=row.get("last_run_remaining"),
            error=row.get("last_run_error"),
        )
    upcoming = next_run_at(now, last_at, rules.nightly_enabled)
    return RetentionPolicy(
        **rules.model_dump(),
        configured=row is not None,
        updated_at=_iso((row or {}).get("updated_at")),
        updated_by=(row or {}).get("updated_by_label"),
        last_run=last_run,
        next_run_at=upcoming.isoformat() if upcoming else None,
        can_edit=can_edit,
    )


def get_policy(db: Any, tenant_id: str, *, can_edit: bool, now: Optional[datetime] = None) -> RetentionPolicy:
    """The tenant's clean-up rules, its last nightly run and its next one.

    Args:
        db: The database.
        tenant_id: The tenant.
        can_edit: Whether the caller may save the rules (copied to the answer).
        now: The current time (tests pin it).

    Returns:
        The policy.
    """
    return _policy_from_row(_read_row(db, tenant_id), can_edit=can_edit, now=now or datetime.now(timezone.utc))


def save_policy(
    db: Any,
    tenant_id: str,
    rules: RetentionRules,
    *,
    actor: ConsumerActor,
    now: Optional[datetime] = None,
) -> RetentionPolicy:
    """Replace the tenant's clean-up rules, audited in the same transaction.

    Args:
        db: The database.
        tenant_id: The tenant.
        rules: The new rules.
        actor: Who is saving them.
        now: The current time (tests pin it).

    Returns:
        The saved policy.

    Raises:
        RetentionError: ``pact-retention-keeps-in-use`` when the rules would remove a deployed or
            released version.
    """
    keep_of(rules)  # refuse before writing anything
    user_id = actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(
            _UPSERT,
            (
                tenant_id,
                rules.keep_main_branch_latest,
                rules.keep_other_branch_latest,
                rules.keep_other_branch_days,
                list(rules.keep_tags),
                rules.nightly_enabled,
                rules.restore_window_days,
                user_id,
                actor.label,
            ),
        )
        row = dict(cursor.fetchone())
        audit_tx(db, cursor, tenant_id, "pacts.retention.policy", actor, "pact-retention/policy", rules.model_dump())
        return row

    row = db._guarded_tx(work)
    return _policy_from_row(row, can_edit=True, now=now or datetime.now(timezone.utc))


def preview_policy(
    db: Any,
    tenant_id: str,
    draft: Optional[RetentionRules] = None,
    *,
    now: Optional[datetime] = None,
) -> RetentionPreview:
    """What the rules would remove if clean-up ran now.

    Args:
        db: The database.
        tenant_id: The tenant.
        draft: Rules not saved yet; the saved rules when ``None``.
        now: The current time (tests pin it).

    Returns:
        The preview: the plan, with the pacts and results that go with each version.

    Raises:
        RetentionError: ``pact-retention-keeps-in-use`` for a draft that turns deployed / released
            off; ``pact-retention-too-many-versions`` for a registry too large to plan at once.
    """
    moment = now or datetime.now(timezone.utc)
    row = _read_row(db, tenant_id)
    rules = draft or _rules(row)
    plan, _ = plan_tx(
        db.execute_query,
        keep_of(rules),
        scope_of(db, tenant_id, None),
        grace=rules.restore_window_days,
        now=moment,
        with_cascade=True,
    )
    upcoming = next_run_at(moment, _aware((row or {}).get("last_run_at")), rules.nightly_enabled)
    return RetentionPreview(
        draft=draft is not None,
        nightly_enabled=rules.nightly_enabled,
        next_run_at=upcoming.isoformat() if upcoming else None,
        plan=plan,
    )


def _run_tenant(db: Any, tenant_id: str, now: datetime) -> Optional[Tuple[int, int]]:
    """Run one workspace's nightly clean-up when it is still due.

    Returns:
        ``(deleted, remaining)``, or ``None`` when another replica holds it or it already ran.

    Raises:
        RetentionError: When the planner refuses (the transaction rolls back; nothing is deleted).
    """
    scope = scope_of(db, tenant_id, None)

    def work(cursor: Any) -> Optional[Tuple[int, int]]:
        cursor.execute(_CLAIM, (tenant_id,))
        claimed = cursor.fetchone()
        if not claimed or not is_due(now, _aware(dict(claimed).get("last_run_at"))):
            return None
        rules = rules_from_row(dict(claimed))
        plan, deletions = plan_tx(
            cursor_fetch(cursor), keep_of(rules), scope, grace=rules.restore_window_days, now=now, dry_run=False
        )
        applied = apply_tx(
            db,
            cursor,
            tenant_id,
            plan,
            deletions,
            scope,
            reason=NIGHTLY_REASON,
            actor=NIGHTLY_ACTOR,
            audit_action="pacts.retention.nightly",
        )
        cursor.execute(_RECORD_RUN, (now, applied.deleted, applied.remaining, None, tenant_id))
        return applied.deleted, applied.remaining

    return db._guarded_tx(work)


def _record_refusal(db: Any, tenant_id: str, now: datetime, message: str) -> None:
    """Store why a nightly run deleted nothing, so it is not retried until tomorrow."""

    def work(cursor: Any) -> bool:
        cursor.execute(_RECORD_RUN, (now, 0, None, message[:500], tenant_id))
        return True

    db._guarded_tx(work)


def run_nightly_clean_up(
    db: Any, *, now: Optional[datetime] = None, max_tenants: int = MAX_TENANTS_PER_TICK
) -> Dict[str, int]:
    """Run every workspace's nightly clean-up that is due (the retention tick).

    Args:
        db: The sweep's database handle.
        now: The current time (tests pin it).
        max_tenants: The most workspaces this call runs.

    Returns:
        ``{"tenants": n, "deleted": m, "refused": r}``.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    totals = {"tenants": 0, "deleted": 0, "refused": 0}
    run_time = moment.replace(hour=NIGHTLY_HOUR_UTC, minute=0, second=0, microsecond=0)
    if moment < run_time:
        return totals  # before today's run time: nothing is due anywhere
    for row in db.execute_query(_DUE, (run_time, max_tenants)) or []:
        tenant_id = str(row["tenant_id"])
        try:
            outcome = _run_tenant(db, tenant_id, moment)
        except RetentionError as exc:
            _record_refusal(db, tenant_id, moment, str(exc))
            totals["refused"] += 1
            continue
        if outcome is not None:
            totals["tenants"] += 1
            totals["deleted"] += outcome[0]
    return totals


def _encode_cursor(item: DeletedItem) -> str:
    """The opaque cursor after ``item``."""
    return base64.urlsafe_b64encode(f"{item.deleted_at}|{item.id}".encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> Tuple[datetime, str]:
    """``(deleted_at, id)`` of a cursor, or a refusal naming what is wrong.

    Raises:
        RetentionError: ``pact-retention-bad-cursor``.
    """
    try:
        text = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        at, _, item_id = text.partition("|")
        stamp = _aware(at)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise RetentionError(CODE_BAD_CURSOR, "the cursor is not one this list returned") from exc
    if stamp is None or not is_uuid_string(item_id):
        raise RetentionError(CODE_BAD_CURSOR, "the cursor is not one this list returned")
    return stamp, item_id


def _item(row: Dict[str, Any], window: int) -> DeletedItem:
    """One Recently deleted row."""
    deleted_at = (_aware(row["deleted_at"]) or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cause = str(row.get("cause") or "version")
    by = row.get("deleted_by") or ("Clean-up" if cause == "retention" else None)
    return DeletedItem(
        kind=row["kind"],
        id=str(row["id"]),
        pacticipant_id=str(row["pacticipant_id"]),
        pacticipant_slug=str(row["pacticipant_slug"]),
        pacticipant_name=str(row["pacticipant_name"]),
        number=row.get("number"),
        deleted_at=deleted_at.isoformat(),
        deleted_by=by,
        cause=cause,
        reason=row.get("reason"),
        purge_after=(deleted_at + timedelta(days=window)).isoformat(),
        versions=int(row.get("versions") or 0),
        pacts=int(row.get("pacts") or 0),
        results=int(row.get("results") or 0),
    )


def list_recently_deleted(
    db: Any,
    tenant_id: str,
    *,
    limit: int = 25,
    after: Optional[str] = None,
    can_restore: bool = False,
) -> DeletedPage:
    """A page of the tenant's deleted pacticipants and versions, newest first.

    Args:
        db: The database.
        tenant_id: The tenant.
        limit: Rows per page (1 … :data:`MAX_DELETED_PAGE`).
        after: The ``next_cursor`` of the previous page.
        can_restore: Whether the caller may restore (copied to the answer).

    Returns:
        The page.

    Raises:
        RetentionError: ``pact-retention-bad-cursor`` for a cursor this list did not return.
    """
    size = max(1, min(int(limit), MAX_DELETED_PAGE))
    window = _rules(_read_row(db, tenant_id)).restore_window_days
    keyset = ""
    params_after: Tuple[Any, ...] = ()
    if after:
        stamp, item_id = _decode_cursor(after)
        params_after = (stamp, item_id)
    rows: List[Dict[str, Any]] = []
    if not is_uuid_string(str(tenant_id or "")):
        return DeletedPage(items=[], count=0, has_more=False, restore_window_days=window, can_restore=can_restore)
    for template, alias in ((_DELETED_PACTICIPANTS, "p"), (_DELETED_VERSIONS, "v")):
        if params_after:
            keyset = f" AND ({alias}.deleted_at, {alias}.id) < (%s::timestamptz, %s::uuid)"
        query = template.format(after=keyset)
        rows.extend(dict(row) for row in db.execute_query(query, (tenant_id, *params_after, size + 1)) or [])
    items = sorted(
        (_item(row, window) for row in rows),
        key=lambda item: (item.deleted_at, item.id),
        reverse=True,
    )
    page, more = items[:size], len(items) > size
    return DeletedPage(
        items=page,
        count=len(page),
        has_more=more,
        next_cursor=_encode_cursor(page[-1]) if more and page else None,
        restore_window_days=window,
        can_restore=can_restore,
    )
