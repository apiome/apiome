"""Deleting, restoring, purging and labelling pacticipants — PFX-1.11 (#6924).

:mod:`app.pacticipant_store` reads and writes the *live* registry; this module is the only place a
pacticipant or a version stops being live, comes back, or goes for good (apiome-db V437):

**A delete is a stamp.** :func:`delete_pacticipant` and :func:`delete_version` set ``deleted_at``
(with who, why, and for a version the cause), and every read of apiome-rest then ignores the row —
its pacts, verification results, deployments and branch membership with it. Deleting a pacticipant
stamps its live versions too (cause ``pacticipant``), so the version filter alone hides everything
a consumer published.

**A delete can be undone until it is purged.** :func:`restore_pacticipant` and
:func:`restore_version` clear the stamp — refused when a live row has taken the handle or the number
since. A pacticipant's restore brings back the versions deleted *with* it, not the ones deleted on
their own before.

**A branch head follows.** A head that is deleted moves back to the branch's latest live version
(:func:`move_heads_tx`); a restore moves it forward again. A branch with no live version keeps its
deleted head and is hidden until a version is recorded on it.

**The purge is the only hard delete.** :func:`purge_deleted` removes rows stamped longer ago than
the tenant's restore window in bounded batches, on the retention tick. The window is the
workspace's Clean-up setting (``pact_retention_policy.restore_window_days``, PFX-8.14), or
``APIOME_PACT_DELETION_GRACE_DAYS`` for a workspace that never saved one.

**Every change is audited.** Each delete, restore, label change and purge appends an
``access_audit`` row inside the same transaction (``pacts.*`` actions), so nothing changes without a
trail.

**Something in use is not deleted by accident.** A version that is currently deployed or released,
or a pacticipant with one, is refused (``pacticipant-version-in-use``) unless the caller forces it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg2

from .config import settings
from .consumer_contract_store import ConsumerActor
from .keyset_lists import ListOrder, SortColumn
from .pacticipant import (
    CODE_LABEL_NOT_FOUND,
    CODE_NOT_DELETED,
    CODE_NOT_FOUND,
    CODE_RESTORE_CONFLICT,
    CODE_VERSION_IN_USE,
    CODE_VERSION_NOT_FOUND,
    PacticipantLabelRecord,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionRecord,
    label_record_from_row,
    pacticipant_record_from_row,
    slugify_pacticipant_name,
    validate_label,
    validate_reason,
    version_record_from_row,
)
from .pacticipant_store import PACTICIPANT_COLUMNS, VERSION_COLUMNS, get_version
from .revision_deprecation import is_uuid_string

__all__ = [
    "AUDIT_ACTIONS",
    "LABELS_ORDER",
    "PURGE_BATCH",
    "add_label",
    "audit_tx",
    "delete_pacticipant",
    "delete_version",
    "get_label",
    "grace_days",
    "list_labels",
    "list_pacticipant_labels",
    "move_heads_tx",
    "purge_after",
    "purge_deleted",
    "remove_label",
    "restore_pacticipant",
    "restore_version",
    "restore_window_sql",
    "tenant_grace_days",
    "soft_delete_versions_tx",
    "with_purge_after",
]

#: The ``access_audit`` actions this module (and the retention run) writes.
AUDIT_ACTIONS = (
    "pacts.pacticipant.delete",
    "pacts.pacticipant.restore",
    "pacts.version.delete",
    "pacts.version.restore",
    "pacts.label.add",
    "pacts.label.remove",
    "pacts.retention.apply",
    "pacts.retention.policy",
    "pacts.retention.nightly",
    "pacts.purge",
)

#: Rows one purge batch removes per table; a tick runs at most :data:`PURGE_MAX_BATCHES` of them.
PURGE_BATCH = 500
PURGE_MAX_BATCHES = 20

#: The order of :func:`list_labels`: by name.
LABELS_ORDER = ListOrder("pacticipant-labels", (SortColumn("name", "text", ("name",)),))

#: The labels of one pacticipant, by name (PFX-6.6): a page of them, so no list is unbounded.
PACTICIPANT_LABELS_ORDER = ListOrder("pacticipant-label", (SortColumn("l.name", "text", ("name",)),))


# ---------------------------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------------------------


def grace_days() -> int:
    """The deployment's default restore window: days a deleted item can be restored before the purge."""
    return max(1, int(settings.pact_deletion_grace_days))


def _window(days: Any) -> int:
    """A stored restore window, or the deployment's default when there is none (or it is unreadable)."""
    if isinstance(days, int) and not isinstance(days, bool) and days >= 1:
        return days
    return grace_days()


def restore_window_sql(tenant_column: str) -> str:
    """A select-list item reading the tenant's stored restore window as ``restore_window_days``.

    Args:
        tenant_column: The SQL expression of the row's tenant id (e.g. ``pacticipant.tenant_id``).

    Returns:
        ``(SELECT … ) AS restore_window_days`` — NULL when the workspace never saved a window.
    """
    return (
        "(SELECT rp.restore_window_days FROM apiome.pact_retention_policy rp "
        f"WHERE rp.tenant_id = {tenant_column}) AS restore_window_days"
    )


def tenant_grace_days(fetch: Any, tenant_id: str) -> int:
    """The tenant's restore window (PFX-8.14), or the deployment's default.

    Args:
        fetch: The database's ``execute_query`` (or any callable with that shape).
        tenant_id: The tenant.

    Returns:
        Days a deleted pacticipant or version of this tenant stays restorable.
    """
    if not is_uuid_string(str(tenant_id or "")):
        return grace_days()
    try:
        rows = fetch(
            "SELECT restore_window_days FROM apiome.pact_retention_policy WHERE tenant_id = %s::uuid",
            (tenant_id,),
        )
        row = rows[0] if isinstance(rows, (list, tuple)) and rows else None
        return _window(row.get("restore_window_days") if isinstance(row, dict) else None)
    except (psycopg2.Error, LookupError, TypeError, AttributeError, StopIteration):
        # An unreadable setting never blocks a read or a purge: the default window applies.
        return grace_days()


def purge_after(deleted_at: Optional[str], days: Optional[int] = None) -> Optional[str]:
    """When a row deleted at ``deleted_at`` is purged.

    Args:
        deleted_at: The ISO-8601 deletion time, as a record carries it, or ``None``.
        days: The tenant's restore window; the deployment's default when ``None``.

    Returns:
        The ISO-8601 purge time, or ``None`` for a live row (or an unreadable time).
    """
    if not deleted_at:
        return None
    try:
        stamp = datetime.fromisoformat(str(deleted_at))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (stamp + timedelta(days=_window(days))).isoformat()


def with_purge_after(record: Any, days: Optional[int] = None) -> Any:
    """The record with ``purge_after`` filled in from its ``deleted_at``.

    Args:
        record: A :class:`~app.pacticipant.PacticipantRecord` or
            :class:`~app.pacticipant.PacticipantVersionRecord`.
        days: The tenant's restore window; the deployment's default when ``None``.

    Returns:
        A copy carrying ``purge_after`` (unchanged when the record is live).
    """
    return record.model_copy(update={"purge_after": purge_after(record.deleted_at, days)})


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def audit_tx(
    db: Any,
    cursor: Any,
    tenant_id: Optional[str],
    action: str,
    actor: Optional[ConsumerActor],
    target: str,
    detail: Dict[str, Any],
) -> None:
    """Append one ``access_audit`` row inside the caller's transaction.

    Args:
        db: The database (its ``_append_access_audit`` writes the hash-chained row).
        cursor: The open transaction's cursor; the row commits or rolls back with the change.
        tenant_id: The tenant whose chain the row extends.
        action: One of :data:`AUDIT_ACTIONS`.
        actor: Who acted; ``None`` for the purge, which the system performs.
        target: What was acted on (``pacticipant/billing-service``).
        detail: Structured context (reason, cause, counts).
    """
    db._append_access_audit(
        cursor,
        tenant_id=tenant_id,
        action=action,
        actor_id=_user_id(actor) if actor else None,
        actor_label=actor.label if actor else "system",
        target=target,
        source="api_key" if actor and actor.kind == "api_key" else "web",
        detail=detail,
    )


def _in_use_sql(version_filter: str) -> str:
    """A query listing the version numbers currently deployed or released, among ``version_filter``.

    Args:
        version_filter: A condition on ``v`` choosing the versions to check.

    Returns:
        SQL selecting ``number`` of every such version in use, at most 20.
    """
    return f"""
        SELECT v.number
        FROM apiome.pacticipant_version v
        WHERE {version_filter} AND v.deleted_at IS NULL
          AND (EXISTS (SELECT 1 FROM apiome.deployed_version d
                       WHERE d.version_id = v.id AND d.pacticipant_id = v.pacticipant_id
                         AND d.currently_deployed)
               OR EXISTS (SELECT 1 FROM apiome.released_version r
                          WHERE r.version_id = v.id AND r.pacticipant_id = v.pacticipant_id
                            AND r.currently_supported))
        ORDER BY v.seq DESC
        LIMIT 20
    """


def _refuse_in_use(numbers: Sequence[str], what: str) -> None:
    """Raise ``pacticipant-version-in-use`` naming the versions that are deployed or released.

    Args:
        numbers: The version numbers in use (nothing happens when empty).
        what: What the caller tried to delete, for the message.

    Raises:
        PacticipantValidationError: ``pacticipant-version-in-use`` when ``numbers`` is not empty.
    """
    if numbers:
        raise PacticipantValidationError(
            CODE_VERSION_IN_USE,
            f"cannot delete {what}: version(s) {', '.join(numbers)} are currently deployed or released. "
            f"Record the undeployment first, or pass force=true to delete anyway.",
        )


def move_heads_tx(cursor: Any, pacticipant_id: str, version_ids: Optional[Sequence[str]] = None) -> int:
    """Point every affected branch's head at its latest live version.

    Run after versions are deleted (a deleted head moves back) or restored (a restored version
    later than the head moves it forward). A branch with no live version keeps its head, which is
    then deleted, and :func:`app.pacticipant_store.list_branches` hides it.

    Args:
        cursor: The open transaction's cursor.
        pacticipant_id: The pacticipant whose branches to fix.
        version_ids: Only the branches these versions are on; ``None`` for every branch.

    Returns:
        How many heads moved.
    """
    scope = ""
    params: List[Any] = [pacticipant_id]
    if version_ids is not None:
        if not version_ids:
            return 0
        scope = """
          AND bv.branch_id IN (SELECT sb.branch_id FROM apiome.pacticipant_branch_version sb
                               WHERE sb.pacticipant_id = %s::uuid AND sb.version_id = ANY(%s::uuid[]))"""
        params += [pacticipant_id, list(version_ids)]
    cursor.execute(
        f"""
        UPDATE apiome.pacticipant_branch b
        SET head_version_id = latest.version_id, updated_at = CURRENT_TIMESTAMP
        FROM (
            SELECT DISTINCT ON (bv.branch_id) bv.branch_id, v.id AS version_id
            FROM apiome.pacticipant_branch_version bv
            JOIN apiome.pacticipant_version v ON v.id = bv.version_id AND v.pacticipant_id = bv.pacticipant_id
            WHERE bv.pacticipant_id = %s::uuid AND v.deleted_at IS NULL{scope}
            ORDER BY bv.branch_id, v.seq DESC
        ) latest
        WHERE b.id = latest.branch_id AND b.head_version_id <> latest.version_id
        """,
        tuple(params),
    )
    return int(cursor.rowcount or 0)


def soft_delete_versions_tx(
    cursor: Any,
    pacticipant_id: str,
    version_ids: Sequence[str],
    *,
    cause: str,
    reason: Optional[str],
    actor: Optional[ConsumerActor],
) -> List[str]:
    """Stamp live versions deleted and move the heads they leave.

    Args:
        cursor: The open transaction's cursor.
        pacticipant_id: The owning pacticipant.
        version_ids: The versions; one that is already deleted is left as it is.
        cause: ``version``, ``pacticipant`` or ``retention``.
        reason: Why, already validated, or ``None``.
        actor: Who is deleting them.

    Returns:
        The ids actually stamped by this call.
    """
    if not version_ids:
        return []
    cursor.execute(
        """
        UPDATE apiome.pacticipant_version
        SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s::uuid, deleted_by_label = %s,
            delete_reason = %s, delete_cause = %s
        WHERE pacticipant_id = %s::uuid AND id = ANY(%s::uuid[]) AND deleted_at IS NULL
        RETURNING id::text AS id
        """,
        (
            _user_id(actor) if actor else None,
            actor.label if actor else None,
            reason,
            cause,
            pacticipant_id,
            list(version_ids),
        ),
    )
    stamped = [row["id"] for row in cursor.fetchall() or []]
    move_heads_tx(cursor, pacticipant_id, stamped)
    return stamped


def _read_pacticipant_tx(cursor: Any, pacticipant_id: str) -> PacticipantRecord:
    """Re-read one pacticipant row (live or deleted) inside a transaction."""
    cursor.execute(
        f"SELECT {PACTICIPANT_COLUMNS}, {restore_window_sql('pacticipant.tenant_id')} "
        "FROM apiome.pacticipant WHERE id = %s::uuid",
        (pacticipant_id,),
    )
    row = dict(cursor.fetchone())
    return with_purge_after(pacticipant_record_from_row(row), row.get("restore_window_days"))


def _read_version_by_id_tx(cursor: Any, version_id: str) -> PacticipantVersionRecord:
    """Re-read one version row (live or deleted) inside a transaction."""
    window = restore_window_sql(
        "(SELECT wp.tenant_id FROM apiome.pacticipant wp WHERE wp.id = v.pacticipant_id)"
    )
    cursor.execute(
        f"SELECT {VERSION_COLUMNS}, {window} FROM apiome.pacticipant_version v WHERE v.id = %s::uuid",
        (version_id,),
    )
    row = dict(cursor.fetchone())
    return with_purge_after(version_record_from_row(row), row.get("restore_window_days"))


# ---------------------------------------------------------------------------------------------
# Pacticipants
# ---------------------------------------------------------------------------------------------


def delete_pacticipant(
    db: Any,
    tenant_id: str,
    pacticipant: PacticipantRecord,
    *,
    actor: ConsumerActor,
    reason: Optional[str] = None,
    force: bool = False,
) -> PacticipantRecord:
    """Soft-delete a pacticipant and its live versions.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant: The live pacticipant, already resolved in the caller's tenant.
        actor: Who is deleting it.
        reason: Why (at most 500 characters); stored and audited.
        force: Delete even when one of its versions is currently deployed or released.

    Returns:
        The deleted pacticipant, with ``deleted_at`` and ``purge_after``.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-reason``; ``pacticipant-version-in-use``
            without ``force``; ``pacticipant-not-found`` when it was deleted meanwhile.
    """
    why = validate_reason(reason)
    if not force:
        rows = db.execute_query(_in_use_sql("v.pacticipant_id = %s::uuid"), (pacticipant.id,)) or []
        _refuse_in_use([row["number"] for row in rows], f"pacticipant '{pacticipant.slug}'")

    def work(cursor: Any) -> Optional[Tuple[PacticipantRecord, int]]:
        cursor.execute(
            """
            UPDATE apiome.pacticipant
            SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s::uuid, deleted_by_label = %s,
                delete_reason = %s
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL
            RETURNING id::text AS id
            """,
            (_user_id(actor), actor.label, why, pacticipant.id, tenant_id),
        )
        if cursor.fetchone() is None:
            return None
        cursor.execute(
            "SELECT id::text AS id FROM apiome.pacticipant_version"
            " WHERE pacticipant_id = %s::uuid AND deleted_at IS NULL",
            (pacticipant.id,),
        )
        live = [row["id"] for row in cursor.fetchall() or []]
        stamped = soft_delete_versions_tx(
            cursor, pacticipant.id, live, cause="pacticipant", reason=why, actor=actor
        )
        record = _read_pacticipant_tx(cursor, pacticipant.id)
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.pacticipant.delete",
            actor,
            f"pacticipant/{pacticipant.slug}",
            {"pacticipant_id": pacticipant.id, "reason": why, "versions": len(stamped), "forced": force},
        )
        return record, len(stamped)

    outcome = db._guarded_tx(work)
    if outcome is None:
        raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant '{pacticipant.slug}' in this tenant")
    return outcome[0]


def _find_deleted_pacticipant(db: Any, tenant_id: str, ref: str) -> PacticipantRecord:
    """The most recently deleted pacticipant matching an id, handle or name.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        ref: Its id, handle or display name.

    Returns:
        The deleted record.

    Raises:
        PacticipantValidationError: ``pacticipant-not-deleted`` when a live one matches and no
            deleted one does; ``pacticipant-not-found`` when nothing matches.
    """
    candidate = (ref or "").strip()
    if not candidate or not is_uuid_string(str(tenant_id or "")):
        raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant '{candidate}' in this tenant")
    by_id = "id = %s::uuid OR " if is_uuid_string(candidate) else ""
    params = (tenant_id, *([candidate] if by_id else []), slugify_pacticipant_name(candidate))
    rows = db.execute_query(
        f"""
        SELECT {PACTICIPANT_COLUMNS}, {restore_window_sql("pacticipant.tenant_id")}
        FROM apiome.pacticipant
        WHERE tenant_id = %s::uuid AND ({by_id}slug = %s)
        ORDER BY (deleted_at IS NULL), deleted_at DESC
        """,
        params,
    ) or []
    deleted = [dict(row) for row in rows if row.get("deleted_at") is not None]
    if deleted:
        return with_purge_after(pacticipant_record_from_row(deleted[0]), deleted[0].get("restore_window_days"))
    if rows:
        raise PacticipantValidationError(CODE_NOT_DELETED, f"pacticipant '{candidate}' is not deleted")
    raise PacticipantValidationError(CODE_NOT_FOUND, f"no deleted pacticipant '{candidate}' in this tenant")


def restore_pacticipant(db: Any, tenant_id: str, ref: str, *, actor: ConsumerActor) -> PacticipantRecord:
    """Undo a pacticipant's delete, with the versions deleted along with it.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        ref: The deleted pacticipant's id, handle or name. With several deleted ones of the same
            handle, the most recently deleted is restored; pass the id to choose.
        actor: Who is restoring it.

    Returns:
        The live pacticipant.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``, ``pacticipant-not-deleted``, or
            ``pacticipant-restore-conflict`` when a live pacticipant has taken its handle since.
    """
    deleted = _find_deleted_pacticipant(db, tenant_id, ref)
    taken = db.execute_query(
        "SELECT 1 FROM apiome.pacticipant WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL",
        (tenant_id, deleted.slug),
    )
    if taken:
        raise PacticipantValidationError(
            CODE_RESTORE_CONFLICT,
            f"cannot restore pacticipant '{deleted.slug}': a live pacticipant has that handle now. "
            f"Delete that one first.",
        )

    def work(cursor: Any) -> Optional[Tuple[PacticipantRecord, int]]:
        cursor.execute(
            """
            SELECT deleted_at FROM apiome.pacticipant
            WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NOT NULL
            FOR UPDATE
            """,
            (deleted.id, tenant_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        stamp = row["deleted_at"]
        cursor.execute(
            """
            UPDATE apiome.pacticipant
            SET deleted_at = NULL, deleted_by = NULL, deleted_by_label = NULL, delete_reason = NULL,
                updated_at = CURRENT_TIMESTAMP, updated_by = %s::uuid
            WHERE id = %s::uuid
            """,
            (_user_id(actor), deleted.id),
        )
        # Only the versions deleted *with* it (same stamp, same cause) come back.
        cursor.execute(
            """
            UPDATE apiome.pacticipant_version
            SET deleted_at = NULL, deleted_by = NULL, deleted_by_label = NULL, delete_reason = NULL,
                delete_cause = NULL
            WHERE pacticipant_id = %s::uuid AND delete_cause = 'pacticipant' AND deleted_at = %s
            """,
            (deleted.id, stamp),
        )
        restored = int(cursor.rowcount or 0)
        move_heads_tx(cursor, deleted.id)
        record = _read_pacticipant_tx(cursor, deleted.id)
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.pacticipant.restore",
            actor,
            f"pacticipant/{deleted.slug}",
            {"pacticipant_id": deleted.id, "versions": restored},
        )
        return record, restored

    try:
        outcome = db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise PacticipantValidationError(
            CODE_RESTORE_CONFLICT,
            f"cannot restore pacticipant '{deleted.slug}': a live pacticipant has that handle now. "
            f"Delete that one first.",
        ) from exc
    if outcome is None:
        raise PacticipantValidationError(CODE_NOT_DELETED, f"pacticipant '{deleted.slug}' is not deleted")
    return outcome[0]


# ---------------------------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------------------------


def delete_version(
    db: Any,
    tenant_id: str,
    pacticipant: PacticipantRecord,
    number: str,
    *,
    actor: ConsumerActor,
    reason: Optional[str] = None,
    force: bool = False,
) -> PacticipantVersionRecord:
    """Soft-delete one version, with its pacts, results, deployments, branch membership and tags.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant: The live pacticipant, already resolved in the caller's tenant.
        number: The version number, exactly as recorded.
        actor: Who is deleting it.
        reason: Why (at most 500 characters).
        force: Delete even when the version is currently deployed or released.

    Returns:
        The deleted version, with ``deleted_at`` and ``purge_after``.

    Raises:
        PacticipantValidationError: ``pacticipant-version-not-found``, ``pacticipant-invalid-reason``,
            or ``pacticipant-version-in-use`` without ``force``.
    """
    why = validate_reason(reason)
    version = get_version(db, pacticipant, number)
    if not force:
        rows = db.execute_query(_in_use_sql("v.id = %s::uuid"), (version.id,)) or []
        _refuse_in_use([row["number"] for row in rows], f"version '{version.number}'")

    def work(cursor: Any) -> Optional[PacticipantVersionRecord]:
        stamped = soft_delete_versions_tx(
            cursor, pacticipant.id, [version.id], cause="version", reason=why, actor=actor
        )
        if not stamped:
            return None
        record = _read_version_by_id_tx(cursor, version.id)
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.version.delete",
            actor,
            f"pacticipant/{pacticipant.slug}/version/{version.number}",
            {"version_id": version.id, "reason": why, "forced": force},
        )
        return record

    deleted = db._guarded_tx(work)
    if deleted is None:
        raise PacticipantValidationError(
            CODE_VERSION_NOT_FOUND, f"pacticipant '{pacticipant.slug}' has no version '{number}'"
        )
    return deleted


def restore_version(
    db: Any, tenant_id: str, pacticipant: PacticipantRecord, number: str, *, actor: ConsumerActor
) -> PacticipantVersionRecord:
    """Undo a version's delete (by itself or by a retention run).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant: The live pacticipant, already resolved in the caller's tenant.
        number: The version number. With several deleted versions of that number, the most
            recently deleted is restored.
        actor: Who is restoring it.

    Returns:
        The live version.

    Raises:
        PacticipantValidationError: ``pacticipant-version-not-found`` when no deleted version has
            that number, ``pacticipant-not-deleted`` when only a live one does, or
            ``pacticipant-restore-conflict`` when a live version has taken the number since.
    """
    rows = db.execute_query(
        """
        SELECT id::text AS id, deleted_at
        FROM apiome.pacticipant_version
        WHERE pacticipant_id = %s::uuid AND number = %s
        ORDER BY (deleted_at IS NULL), deleted_at DESC
        """,
        (pacticipant.id, number or ""),
    ) or []
    deleted = [row for row in rows if row.get("deleted_at") is not None]
    if not deleted:
        if rows:
            raise PacticipantValidationError(CODE_NOT_DELETED, f"version '{number}' is not deleted")
        raise PacticipantValidationError(
            CODE_VERSION_NOT_FOUND, f"pacticipant '{pacticipant.slug}' has no deleted version '{number}'"
        )
    if len(rows) > len(deleted):
        raise PacticipantValidationError(
            CODE_RESTORE_CONFLICT,
            f"cannot restore version '{number}' of '{pacticipant.slug}': a live version has that number now",
        )
    version_id = deleted[0]["id"]

    def work(cursor: Any) -> Optional[PacticipantVersionRecord]:
        cursor.execute(
            """
            UPDATE apiome.pacticipant_version
            SET deleted_at = NULL, deleted_by = NULL, deleted_by_label = NULL, delete_reason = NULL,
                delete_cause = NULL
            WHERE id = %s::uuid AND pacticipant_id = %s::uuid AND deleted_at IS NOT NULL
            RETURNING id::text AS id
            """,
            (version_id, pacticipant.id),
        )
        if cursor.fetchone() is None:
            return None
        move_heads_tx(cursor, pacticipant.id, [version_id])
        record = _read_version_by_id_tx(cursor, version_id)
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.version.restore",
            actor,
            f"pacticipant/{pacticipant.slug}/version/{number}",
            {"version_id": version_id},
        )
        return record

    try:
        restored = db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise PacticipantValidationError(
            CODE_RESTORE_CONFLICT,
            f"cannot restore version '{number}' of '{pacticipant.slug}': a live version has that number now",
        ) from exc
    if restored is None:
        raise PacticipantValidationError(CODE_NOT_DELETED, f"version '{number}' is not deleted")
    return restored


# ---------------------------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------------------------

_LABEL_SELECT = """
    SELECT l.name, l.pacticipant_id::text AS pacticipant_id, p.slug AS pacticipant_slug,
           p.name AS pacticipant_name, l.created_at
    FROM apiome.pacticipant_label l
    JOIN apiome.pacticipant p ON p.id = l.pacticipant_id AND p.tenant_id = l.tenant_id
"""


def list_labels(
    db: Any, tenant_id: str, *, limit: Optional[int] = None, cursor: Optional[Sequence[Any]] = None
) -> List[Dict[str, str]]:
    """Every distinct label of the tenant's live pacticipants, by name.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        limit: Names to read; ``None`` reads every one.
        cursor: :data:`LABELS_ORDER` values of the last name already seen.

    Returns:
        One ``{"name": …}`` per label (a mapping, so :meth:`LABELS_ORDER.page` can cut a cursor).
    """
    if not is_uuid_string(str(tenant_id or "")):
        return []
    after_sql, after_params, limit_sql, limit_params = LABELS_ORDER.window(limit, cursor)
    rows = db.execute_query(
        f"""
        SELECT name FROM (
            SELECT DISTINCT l.name
            FROM apiome.pacticipant_label l
            JOIN apiome.pacticipant p ON p.id = l.pacticipant_id AND p.tenant_id = l.tenant_id
            WHERE l.tenant_id = %s::uuid AND p.deleted_at IS NULL
        ) names
        WHERE TRUE{after_sql}
        ORDER BY {LABELS_ORDER.order_by}{limit_sql}
        """,
        (tenant_id, *after_params, *limit_params),
    ) or []
    return [{"name": str(row["name"])} for row in rows]


def list_pacticipant_labels(
    db: Any,
    pacticipant: PacticipantRecord,
    *,
    limit: Optional[int] = None,
    cursor: Optional[Sequence[Any]] = None,
) -> List[PacticipantLabelRecord]:
    """The labels of one pacticipant, by name.

    Args:
        db: The database.
        pacticipant: The live pacticipant, already resolved in the caller's tenant.
        limit: Labels to read; ``None`` reads every one (the purge and the HAL documents).
        cursor: :data:`PACTICIPANT_LABELS_ORDER` values of the last label already seen.

    Returns:
        The labels.
    """
    after_sql, after_params, limit_sql, limit_params = PACTICIPANT_LABELS_ORDER.window(limit, cursor)
    rows = db.execute_query(
        _LABEL_SELECT
        + f" WHERE l.pacticipant_id = %s::uuid{after_sql} ORDER BY {PACTICIPANT_LABELS_ORDER.order_by}{limit_sql}",
        (pacticipant.id, *after_params, *limit_params),
    ) or []
    return [label_record_from_row(dict(row)) for row in rows]


def get_label(db: Any, pacticipant: PacticipantRecord, name: str) -> PacticipantLabelRecord:
    """One label of a pacticipant.

    Args:
        db: The database.
        pacticipant: The live pacticipant.
        name: The label.

    Returns:
        The label.

    Raises:
        PacticipantValidationError: ``pacticipant-label-not-found``.
    """
    rows = db.execute_query(
        _LABEL_SELECT + " WHERE l.pacticipant_id = %s::uuid AND l.name = %s",
        (pacticipant.id, name or ""),
    ) or []
    if not rows:
        raise PacticipantValidationError(
            CODE_LABEL_NOT_FOUND, f"pacticipant '{pacticipant.slug}' has no label '{name}'"
        )
    return label_record_from_row(dict(rows[0]))


def add_label(
    db: Any, tenant_id: str, pacticipant: PacticipantRecord, name: str, *, actor: ConsumerActor
) -> Tuple[PacticipantLabelRecord, bool]:
    """Put a label on a pacticipant. Adding it again changes nothing.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant: The live pacticipant.
        name: The label.
        actor: Who is adding it.

    Returns:
        The label, and whether this call added it.

    Raises:
        PacticipantValidationError: ``pacticipant-invalid-label``, or ``pacticipant-not-found``
            when the pacticipant was deleted meanwhile.
    """
    label = validate_label(name)

    def work(cursor: Any) -> Optional[Tuple[PacticipantLabelRecord, bool]]:
        cursor.execute(
            """
            INSERT INTO apiome.pacticipant_label (pacticipant_id, tenant_id, name, created_by)
            SELECT p.id, p.tenant_id, %s, %s::uuid
            FROM apiome.pacticipant p
            WHERE p.id = %s::uuid AND p.tenant_id = %s::uuid AND p.deleted_at IS NULL
            ON CONFLICT (pacticipant_id, name) DO NOTHING
            RETURNING name
            """,
            (label, _user_id(actor), pacticipant.id, tenant_id),
        )
        created = cursor.fetchone() is not None
        cursor.execute(
            _LABEL_SELECT + " WHERE l.pacticipant_id = %s::uuid AND l.name = %s AND p.deleted_at IS NULL",
            (pacticipant.id, label),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        if created:
            audit_tx(
                db,
                cursor,
                tenant_id,
                "pacts.label.add",
                actor,
                f"pacticipant/{pacticipant.slug}/label/{label}",
                {"pacticipant_id": pacticipant.id, "label": label},
            )
        return label_record_from_row(dict(row)), created

    outcome = db._guarded_tx(work)
    if outcome is None:
        raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant '{pacticipant.slug}' in this tenant")
    return outcome


def remove_label(
    db: Any, tenant_id: str, pacticipant: PacticipantRecord, name: str, *, actor: ConsumerActor
) -> PacticipantLabelRecord:
    """Take a label off a pacticipant.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant: The live pacticipant.
        name: The label.
        actor: Who is removing it.

    Returns:
        The label that was removed.

    Raises:
        PacticipantValidationError: ``pacticipant-label-not-found``.
    """
    existing = get_label(db, pacticipant, name)

    def work(cursor: Any) -> Optional[PacticipantLabelRecord]:
        cursor.execute(
            """
            DELETE FROM apiome.pacticipant_label
            WHERE pacticipant_id = %s::uuid AND tenant_id = %s::uuid AND name = %s
            RETURNING name
            """,
            (pacticipant.id, tenant_id, existing.name),
        )
        if cursor.fetchone() is None:
            return None
        audit_tx(
            db,
            cursor,
            tenant_id,
            "pacts.label.remove",
            actor,
            f"pacticipant/{pacticipant.slug}/label/{existing.name}",
            {"pacticipant_id": pacticipant.id, "label": existing.name},
        )
        return existing

    removed = db._guarded_tx(work)
    if removed is None:
        raise PacticipantValidationError(
            CODE_LABEL_NOT_FOUND, f"pacticipant '{pacticipant.slug}' has no label '{name}'"
        )
    return removed


# ---------------------------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------------------------


#: A row of a tenant is past its restore window: deleted before ``now - window`` (PFX-8.14).
_PAST_WINDOW = """{column} < %s::timestamptz - make_interval(days => COALESCE(
        (SELECT rp.restore_window_days FROM apiome.pact_retention_policy rp WHERE rp.tenant_id = {tenant}),
        %s))"""


def _purge_versions_tx(db: Any, cursor: Any, now: datetime, batch: int) -> Dict[str, int]:
    """Hard-delete one batch of versions deleted longer ago than their tenant's restore window.

    (Their pacticipant still live.)

    A branch whose head is purged gets the latest version it still has; a branch left with none is
    removed. The version delete then cascades to its pacts, results, deployments, tags and branch
    membership (V433–V436).

    Args:
        db: The database (for the audit rows).
        cursor: The open transaction's cursor.
        now: The current time; each tenant's window counts back from it.
        batch: The most versions this batch removes.

    Returns:
        Versions removed per tenant id.
    """
    past = _PAST_WINDOW.format(column="v.deleted_at", tenant="p.tenant_id")
    cursor.execute(
        f"""
        SELECT v.id::text AS id, v.pacticipant_id::text AS pacticipant_id, p.tenant_id::text AS tenant_id
        FROM apiome.pacticipant_version v
        JOIN apiome.pacticipant p ON p.id = v.pacticipant_id
        WHERE v.deleted_at IS NOT NULL AND {past} AND p.deleted_at IS NULL
        ORDER BY v.deleted_at
        LIMIT %s
        FOR UPDATE OF v SKIP LOCKED
        """,
        (now, grace_days(), batch),
    )
    rows = cursor.fetchall() or []
    if not rows:
        return {}
    ids = [row["id"] for row in rows]
    # A branch headed by a purged version: point it at the latest version it keeps, or drop it.
    cursor.execute(
        """
        UPDATE apiome.pacticipant_branch b
        SET head_version_id = keep.version_id, updated_at = CURRENT_TIMESTAMP
        FROM (
            SELECT DISTINCT ON (bv.branch_id) bv.branch_id, v.id AS version_id
            FROM apiome.pacticipant_branch_version bv
            JOIN apiome.pacticipant_version v ON v.id = bv.version_id AND v.pacticipant_id = bv.pacticipant_id
            WHERE NOT (v.id = ANY(%s::uuid[]))
              AND bv.branch_id IN (SELECT hb.id FROM apiome.pacticipant_branch hb
                                   WHERE hb.head_version_id = ANY(%s::uuid[]))
            ORDER BY bv.branch_id, (v.deleted_at IS NULL) DESC, v.seq DESC
        ) keep
        WHERE b.id = keep.branch_id
        """,
        (ids, ids),
    )
    cursor.execute(
        "DELETE FROM apiome.pacticipant_branch WHERE head_version_id = ANY(%s::uuid[])",
        (ids,),
    )
    cursor.execute("DELETE FROM apiome.pacticipant_version WHERE id = ANY(%s::uuid[])", (ids,))
    per_tenant: Dict[str, int] = {}
    for row in rows:
        per_tenant[row["tenant_id"]] = per_tenant.get(row["tenant_id"], 0) + 1
    return per_tenant


def _purge_pacticipants_tx(cursor: Any, now: datetime, batch: int) -> Dict[str, List[str]]:
    """Hard-delete one batch of pacticipants deleted longer ago than their tenant's restore window.

    Args:
        cursor: The open transaction's cursor.
        now: The current time; each tenant's window counts back from it.
        batch: The most pacticipants this batch removes.

    Returns:
        The handles removed, per tenant id.
    """
    past = _PAST_WINDOW.format(column="dp.deleted_at", tenant="dp.tenant_id")
    cursor.execute(
        f"""
        DELETE FROM apiome.pacticipant
        WHERE id IN (SELECT dp.id FROM apiome.pacticipant dp
                     WHERE dp.deleted_at IS NOT NULL AND {past}
                     ORDER BY dp.deleted_at
                     LIMIT %s
                     FOR UPDATE SKIP LOCKED)
        RETURNING id::text AS id, tenant_id::text AS tenant_id, slug
        """,
        (now, grace_days(), batch),
    )
    rows = cursor.fetchall() or []
    per_tenant: Dict[str, List[str]] = {}
    for row in rows:
        per_tenant.setdefault(row["tenant_id"], []).append(row["slug"])
    _purge_owner_rows_tx(cursor, [row["id"] for row in rows if row.get("id")])
    return per_tenant


def _purge_owner_rows_tx(cursor: Any, pacticipant_ids: List[str]) -> None:
    """Remove the owner rows and unowned findings of pacticipants purged for good (PFX-6.4).

    ``entity_owners`` and ``unowned_findings`` name their entity by kind and id, with no foreign
    key, so the purge removes them in the same transaction. A soft-deleted pacticipant keeps its
    owner, so a restore brings it back.

    Args:
        cursor: The open transaction's cursor.
        pacticipant_ids: The purged pacticipants; nothing happens for an empty list.
    """
    if not pacticipant_ids:
        return
    for table in ("entity_owners", "unowned_findings"):
        cursor.execute(
            f"DELETE FROM apiome.{table} WHERE entity_kind = 'pacticipant' AND entity_id = ANY(%s::uuid[])",
            (pacticipant_ids,),
        )


def purge_deleted(
    db: Any,
    *,
    now: Optional[datetime] = None,
    batch: int = PURGE_BATCH,
    max_batches: int = PURGE_MAX_BATCHES,
) -> Dict[str, int]:
    """Remove for good what was deleted longer ago than its tenant's restore window.

    Each batch is its own transaction and appends one ``pacts.purge`` audit row per tenant it
    touched. Concurrent replicas are safe: rows are claimed ``FOR UPDATE SKIP LOCKED``.

    Args:
        db: The sweep's database handle.
        now: The current time (tests pin it).
        batch: Rows per batch, per table.
        max_batches: The most batches per table this call runs.

    Returns:
        ``{"versions": n, "pacticipants": m}`` removed.
    """
    moment = now or datetime.now(timezone.utc)
    totals = {"versions": 0, "pacticipants": 0}

    def run(kind: str) -> int:
        """One batch of ``kind``; returns how many rows it removed."""

        def work(cursor: Any) -> int:
            if kind == "versions":
                counts = _purge_versions_tx(db, cursor, moment, batch)
                details = {tenant: {"versions": count} for tenant, count in counts.items()}
                removed = sum(counts.values())
            else:
                slugs = _purge_pacticipants_tx(cursor, moment, batch)
                details = {tenant: {"pacticipants": names} for tenant, names in slugs.items()}
                removed = sum(len(names) for names in slugs.values())
            for tenant, detail in details.items():
                audit_tx(
                    db,
                    cursor,
                    tenant,
                    "pacts.purge",
                    None,
                    kind,
                    {**detail, "default_grace_days": grace_days(), "restore_window": "per workspace"},
                )
            return removed

        return int(db._guarded_tx(work) or 0)

    for kind in ("versions", "pacticipants"):
        for _ in range(max_batches):
            removed = run(kind)
            totals[kind] += removed
            if removed < batch:
                break
    return totals
