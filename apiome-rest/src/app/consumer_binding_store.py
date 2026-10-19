"""Persistence for consumer bindings and the runtime-edge read — RDG-1.8 (#5765).

:mod:`app.consumer_binding` says what a binding is; this module is the only place one is read or
written (apiome-db V292), and the only place the RDG-1.8 reads of ``usage_daily`` live.

**The value is hashed before the transaction opens.** :func:`create_binding` calls
:func:`~app.consumer_binding.consumer_hint_hmac` first, then drops the raw value; the SQL only ever
sees the hash. **A delete is a stamp**: the row stays so the ``usage_hourly`` / ``usage_daily`` rows
that carry its id stay attributed, while :func:`load_live_bindings` (what each ingest batch reads)
stops returning it.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

import psycopg2

from .consumer_binding import (
    CODE_BINDING_EXISTS,
    CODE_BINDING_LIMIT,
    CODE_BINDING_NOT_FOUND,
    KIND_USER_AGENT,
    MAX_BINDINGS_PER_CONSUMER,
    BindingError,
    BindingInput,
    BindingRecord,
    LiveBinding,
    binding_record_from_row,
    consumer_hint_hmac,
    normalize_binding,
)
from .consumer_runtime_edges import UsageRow
from .revision_deprecation import is_uuid_string

__all__ = [
    "create_binding",
    "delete_binding",
    "insert_binding",
    "list_bindings",
    "live_bindings",
    "load_live_bindings",
    "stamp_matches",
    "usage_by_consumer",
]

#: The columns a binding read returns. ``value_hmac`` is never selected for a response.
_COLUMNS = """
    id::text AS id, consumer_id::text AS consumer_id, kind, name, key_version, last_matched_at,
    created_at, deleted_at
"""


def list_bindings(db: Any, tenant_id: str, consumer_id: str, *, include_deleted: bool = False) -> List[BindingRecord]:
    """A consumer's bindings, newest first.

    Args:
        db: The database.
        tenant_id: The tenant.
        consumer_id: The consumer.
        include_deleted: Also return deleted bindings (they still attribute history).

    Returns:
        The bindings.
    """
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS}
        FROM apiome.usage_consumer_binding
        WHERE tenant_id = %s::uuid AND consumer_id = %s::uuid
          AND (%s OR deleted_at IS NULL)
        ORDER BY created_at DESC, id
        """,
        (tenant_id, consumer_id, include_deleted),
    )
    return [binding_record_from_row(dict(row)) for row in rows]


def create_binding(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    consumer_id: str,
    body: BindingInput,
    user_id: Optional[str],
) -> BindingRecord:
    """Store a new binding.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The consumer's project.
        consumer_id: The consumer.
        body: The binding; its value is hashed here and goes no further.
        user_id: The creating user, when the caller is one.

    Returns:
        The stored binding (without its value or hash).

    Raises:
        BindingError: 400 for a malformed name, 409 ``consumer-binding-exists`` when the tenant
            already binds that kind, name and value, 409 ``consumer-binding-limit`` past
            :data:`~app.consumer_binding.MAX_BINDINGS_PER_CONSUMER`, 503 when no key is configured.
    """
    name = normalize_binding(body.kind, body.name)
    value_hmac: Optional[str] = None
    key_version: Optional[int] = None
    if body.kind != KIND_USER_AGENT and body.value is not None:
        value_hmac, key_version = consumer_hint_hmac(tenant_id, body.value.get_secret_value())
    return insert_binding(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        consumer_id=consumer_id,
        kind=body.kind,
        name=name,
        value_hmac=value_hmac,
        key_version=key_version,
        user_id=user_id,
    )


def insert_binding(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    consumer_id: str,
    kind: str,
    name: str,
    value_hmac: Optional[str],
    key_version: Optional[int],
    user_id: Optional[str],
) -> BindingRecord:
    """Insert a binding whose name is already normalized and whose value is already hashed.

    :func:`create_binding` calls it after hashing a value it was given; registering a suggested
    consumer (CDG-3.5) calls it with the HMAC the edge already sent, so no value is ever needed.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The consumer's project.
        consumer_id: The consumer.
        kind: The binding kind.
        name: The normalized name or glob.
        value_hmac: The value's HMAC (``None`` for a user-agent glob).
        key_version: The master-key version of ``value_hmac``.
        user_id: The creating user, when the caller is one.

    Returns:
        The stored binding.

    Raises:
        BindingError: 409 ``consumer-binding-exists`` or ``consumer-binding-limit``.
    """

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(
            """
            SELECT count(*) AS n FROM apiome.usage_consumer_binding
            WHERE consumer_id = %s::uuid AND deleted_at IS NULL
            """,
            (consumer_id,),
        )
        if int(cursor.fetchone()["n"]) >= MAX_BINDINGS_PER_CONSUMER:
            return {"error": "limit"}
        cursor.execute("SAVEPOINT consumer_binding_insert")
        try:
            cursor.execute(
                f"""
                INSERT INTO apiome.usage_consumer_binding (
                    tenant_id, project_id, consumer_id, kind, name, value_hmac, key_version, created_by)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s::uuid)
                RETURNING {_COLUMNS}
                """,
                (
                    tenant_id,
                    project_id,
                    consumer_id,
                    kind,
                    name,
                    value_hmac,
                    key_version,
                    user_id if user_id and is_uuid_string(user_id) else None,
                ),
            )
        except psycopg2.errors.UniqueViolation:
            cursor.execute("ROLLBACK TO SAVEPOINT consumer_binding_insert")
            return {"error": "exists"}
        return {"row": dict(cursor.fetchone())}

    result = db._guarded_tx(work)
    if result.get("error") == "limit":
        raise BindingError(
            CODE_BINDING_LIMIT,
            f"a consumer may hold at most {MAX_BINDINGS_PER_CONSUMER} live bindings",
            status=409,
        )
    if result.get("error") == "exists":
        raise BindingError(
            CODE_BINDING_EXISTS,
            "this workspace already binds that kind, name and value to a consumer",
            status=409,
        )
    return binding_record_from_row(result["row"])


def delete_binding(
    db: Any, *, tenant_id: str, consumer_id: str, binding_id: str, user_id: Optional[str]
) -> BindingRecord:
    """Delete a binding: it stops matching new traffic; attributed history is kept.

    Args:
        db: The database.
        tenant_id: The tenant.
        consumer_id: The consumer the binding must belong to.
        binding_id: The binding.
        user_id: The deleting user, when the caller is one.

    Returns:
        The deleted binding.

    Raises:
        BindingError: 404 ``consumer-binding-not-found`` for an unknown or already deleted binding.
    """
    if not is_uuid_string(binding_id):
        raise BindingError(CODE_BINDING_NOT_FOUND, "no live binding with that id on this consumer", status=404)
    rows = db.execute_query(
        f"""
        UPDATE apiome.usage_consumer_binding
        SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s::uuid
        WHERE id = %s::uuid AND tenant_id = %s::uuid AND consumer_id = %s::uuid AND deleted_at IS NULL
        RETURNING {_COLUMNS}
        """,
        (user_id if user_id and is_uuid_string(user_id) else None, binding_id, tenant_id, consumer_id),
    )
    if not rows:
        raise BindingError(CODE_BINDING_NOT_FOUND, "no live binding with that id on this consumer", status=404)
    return binding_record_from_row(dict(rows[0]))


#: The project's live bindings of live consumers, for :class:`~app.consumer_binding.ConsumerMatcher`.
_LIVE_SQL = """
    SELECT b.id::text AS id, b.consumer_id::text AS consumer_id, b.kind, b.name, b.value_hmac,
           b.created_at
    FROM apiome.usage_consumer_binding b
    JOIN apiome.consumer c ON c.id = b.consumer_id
    WHERE b.tenant_id = %s::uuid AND b.project_id = %s::uuid
      AND b.deleted_at IS NULL AND c.deleted_at IS NULL
"""


def _live_binding(row: Mapping[str, Any]) -> LiveBinding:
    """Adapt one :data:`_LIVE_SQL` row (``value_hmac`` is CHAR(64); the pad is stripped)."""
    return LiveBinding(
        id=row["id"],
        consumer_id=row["consumer_id"],
        kind=row["kind"],
        name=row["name"],
        value_hmac=row["value_hmac"].strip() if row["value_hmac"] else None,
        created_at=row["created_at"],
    )


def load_live_bindings(cursor: Any, tenant_id: str, project_id: str) -> List[LiveBinding]:
    """The project's live bindings, for the ingest matcher.

    Read inside the batch's transaction, so a binding deleted before the batch began is never used.

    Args:
        cursor: A cursor in the ingest transaction.
        tenant_id: The tenant.
        project_id: The source's project.

    Returns:
        The bindings of the project's live consumers.
    """
    cursor.execute(_LIVE_SQL, (tenant_id, project_id))
    return [_live_binding(row) for row in cursor.fetchall()]


def live_bindings(db: Any, tenant_id: str, project_id: str) -> List[LiveBinding]:
    """The project's live bindings, read outside any transaction (the suggestions read, CDG-3.5).

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.

    Returns:
        The bindings of the project's live consumers.
    """
    return [_live_binding(row) for row in db.execute_query(_LIVE_SQL, (tenant_id, project_id)) or []]


def stamp_matches(cursor: Any, matches: Mapping[str, datetime], consumers: Mapping[str, str]) -> None:
    """Advance ``last_matched_at`` and the consumers' ``runtime_last_seen_at``.

    Both only move forward, so a late batch for an older hour never turns them back.

    Args:
        cursor: A cursor in the ingest transaction.
        matches: Binding id → newest observed time this batch attributed to it.
        consumers: Binding id → its consumer id.
    """
    newest: Dict[str, datetime] = {}
    for binding_id, seen in matches.items():
        cursor.execute(
            """
            UPDATE apiome.usage_consumer_binding
            SET last_matched_at = GREATEST(COALESCE(last_matched_at, %s), %s)
            WHERE id = %s::uuid
            """,
            (seen, seen, binding_id),
        )
        consumer_id = consumers.get(binding_id)
        if consumer_id and (consumer_id not in newest or seen > newest[consumer_id]):
            newest[consumer_id] = seen
    for consumer_id, seen in newest.items():
        cursor.execute(
            """
            UPDATE apiome.consumer
            SET runtime_last_seen_at = GREATEST(COALESCE(runtime_last_seen_at, %s), %s)
            WHERE id = %s::uuid
            """,
            (seen, seen, consumer_id),
        )


def usage_by_consumer(
    db: Any, tenant_id: str, project_id: str, *, since: date, until: date, consumer_ids: Optional[Sequence[str]] = None
) -> List[UsageRow]:
    """Per consumer and operation, the window's calls from ``usage_daily``.

    A row's binding is joined **whether or not it is deleted**, so history stays attributed to the
    consumer it was attributed to. Rows with no binding come back with ``consumer_id = None``.

    Args:
        db: The database.
        tenant_id: The tenant.
        project_id: The project.
        since: First UTC day (inclusive).
        until: Last UTC day (inclusive).
        consumer_ids: Only these consumers (and never the anonymous rows) when given.

    Returns:
        The rows, ordered by consumer then operation.
    """
    if not is_uuid_string(tenant_id) or not is_uuid_string(project_id):
        return []
    rows = db.execute_query(
        """
        SELECT b.consumer_id::text AS consumer_id, d.operation_key,
               sum(d.calls)::bigint AS calls, sum(d.errors)::bigint AS errors, max(d.day) AS last_seen
        FROM apiome.usage_daily d
        LEFT JOIN apiome.usage_consumer_binding b ON b.id = d.consumer_binding_id
        WHERE d.tenant_id = %s::uuid AND d.project_id = %s::uuid AND d.day BETWEEN %s AND %s
          AND (%s::uuid[] IS NULL OR b.consumer_id = ANY (%s::uuid[]))
        GROUP BY b.consumer_id, d.operation_key
        HAVING sum(d.calls) > 0
        ORDER BY b.consumer_id NULLS LAST, d.operation_key
        """,
        (
            tenant_id,
            project_id,
            since,
            until,
            list(consumer_ids) if consumer_ids is not None else None,
            list(consumer_ids) if consumer_ids is not None else None,
        ),
    )
    return [
        UsageRow(
            consumer_id=row["consumer_id"],
            operation_key=row["operation_key"],
            calls=int(row["calls"]),
            errors=int(row["errors"]),
            last_seen=row["last_seen"],
        )
        for row in rows
    ]
