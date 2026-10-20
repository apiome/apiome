"""Catalog connector storage — CDG-1.1 (#5952).

SQL over the V281 tables (``catalog_connectors``, ``catalog_connector_items``,
``catalog_connector_credentials``) and over the connector rows of the shared refresh ledger
(``tenant_repository_refresh_jobs`` with ``refresh_source = 'connector'``).

Every function takes the :class:`~app.database.Database` it runs on, so the scheduled sweep can
use its per-tick connection and tests can pass a fake. Every read and write of a connector is
scoped by tenant; an id from another tenant is simply not found. Deleted connectors are invisible
to every read.

Credentials are only ever written sealed (:func:`put_credentials`) and only ever read back sealed
(:func:`get_sealed_credentials`, for the sync engine); no function here returns plaintext.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional

import psycopg2
import psycopg2.errors

from .catalog_connectors import (
    CODE_NAME_TAKEN,
    ITEM_DISCOVERED,
    ITEM_IGNORED,
    ITEM_IMPORTED,
    ITEM_MISSING,
    STATUS_PAUSED,
    ConnectorError,
)
from .refresh_source import RefreshCandidate

__all__ = [
    "count_items",
    "count_refresh_runs",
    "count_runs",
    "create_connector",
    "finish_run",
    "get_connector",
    "get_sealed_credentials",
    "list_connectors",
    "list_due_connectors",
    "list_item_rows",
    "list_items",
    "list_refresh_runs",
    "list_runs",
    "mark_item_imported",
    "mark_item_mcp_server",
    "mark_missing_items",
    "put_credentials",
    "record_connector_outcome",
    "soft_delete_connector",
    "start_run",
    "update_connector",
    "upsert_seen_item",
]

#: A run still ``running`` after this long is treated as abandoned (its process died), so it no
#: longer blocks the connector's single-flight index.
STALE_RUN_SECONDS = 3600

_CONNECTOR_COLUMNS = """
    c.id, c.tenant_id, c.kind, c.name, c.base_url, c.scope, c.refresh_interval_seconds,
    c.conflict_policy, c.status, c.last_run_at, c.created_by, c.created_at, c.updated_at,
    EXISTS (
        SELECT 1 FROM apiome.catalog_connector_credentials cc WHERE cc.connector_id = c.id
    ) AS has_credentials
"""

_ITEM_COLUMNS = """
    i.id, i.connector_id, i.remote_id, i.remote_name, i.environment, i.hosts, i.base_path,
    i.remote_revision, i.remote_updated_at, i.imported_revision, i.imported_remote_updated_at,
    i.imported_sha256, i.status, i.project_id, i.first_seen_at, i.last_seen_at, i.deployment,
    i.ignored_reason, i.ignored_at, i.linked_at, i.mcp_endpoint_id, i.discovered_reason
"""

_RUN_COLUMNS = """
    j.id, j.tenant_id, j.connector_id, j.refresh_source, j.status, j.error_class, j.http_status,
    j.error_message, j.pull_count, j.run_summary, j.created_by, j.created_at, j.started_at,
    j.finished_at
"""

#: Columns a PATCH may set, by request field.
_UPDATABLE = ("name", "base_url", "scope", "refresh_interval_seconds", "conflict_policy", "status")


def _first(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The first row, or ``None``."""
    return dict(rows[0]) if rows else None


def _name_taken(exc: Exception) -> bool:
    """True when ``exc`` is the live-name unique index refusing a duplicate."""
    return isinstance(exc, psycopg2.errors.UniqueViolation) and "uq_catalog_connectors_tenant_name_live" in str(exc)


# ---------------------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------------------


def list_connectors(db: Any, tenant_id: str) -> List[Dict[str, Any]]:
    """The tenant's live connectors, by name."""
    return db.execute_query(
        f"""
        SELECT {_CONNECTOR_COLUMNS}
        FROM apiome.catalog_connectors c
        WHERE c.tenant_id = %s::uuid AND c.deleted_at IS NULL
        ORDER BY lower(c.name), c.id
        """,
        (tenant_id,),
    )


def get_connector(db: Any, tenant_id: str, connector_id: str) -> Optional[Dict[str, Any]]:
    """One live connector of the tenant, or ``None``."""
    return _first(
        db.execute_query(
            f"""
            SELECT {_CONNECTOR_COLUMNS}
            FROM apiome.catalog_connectors c
            WHERE c.tenant_id = %s::uuid AND c.id = %s::uuid AND c.deleted_at IS NULL
            """,
            (tenant_id, connector_id),
        )
    )


def create_connector(
    db: Any,
    tenant_id: str,
    *,
    kind: str,
    name: str,
    base_url: Optional[str],
    scope: Mapping[str, Any],
    refresh_interval_seconds: Optional[int],
    conflict_policy: str,
    status: str,
    created_by: Optional[str],
) -> Dict[str, Any]:
    """Insert a connector and return it.

    Raises:
        ConnectorError: ``connector-name-taken`` when a live connector of the tenant has the name.
    """
    try:
        rows = db.execute_query(
            """
            INSERT INTO apiome.catalog_connectors
              (tenant_id, kind, name, base_url, scope, refresh_interval_seconds, conflict_policy,
               status, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                kind,
                name,
                base_url,
                json.dumps(dict(scope)),
                refresh_interval_seconds,
                conflict_policy,
                status,
                created_by,
            ),
        )
    except psycopg2.Error as exc:
        if _name_taken(exc):
            raise ConnectorError(CODE_NAME_TAKEN, f"A connector named {name!r} already exists.") from exc
        raise
    return get_connector(db, tenant_id, str(rows[0]["id"]))  # type: ignore[return-value]


def update_connector(
    db: Any, tenant_id: str, connector_id: str, changes: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    """Apply a PATCH to a live connector and return it, or ``None`` when it does not exist.

    Args:
        changes: Column → value, for the columns in ``_UPDATABLE`` only; an empty mapping is a
            no-op read.

    Raises:
        ConnectorError: ``connector-name-taken`` on a rename onto a live connector's name.
    """
    sets: List[str] = []
    params: List[Any] = []
    for column in _UPDATABLE:
        if column not in changes:
            continue
        if column == "scope":
            sets.append("scope = %s::jsonb")
            params.append(json.dumps(dict(changes[column] or {})))
        else:
            sets.append(f"{column} = %s")
            params.append(changes[column])
    if not sets:
        return get_connector(db, tenant_id, connector_id)
    sets.append("updated_at = now()")
    try:
        rows = db.execute_query(
            f"""
            UPDATE apiome.catalog_connectors SET {', '.join(sets)}
            WHERE tenant_id = %s::uuid AND id = %s::uuid AND deleted_at IS NULL
            RETURNING id
            """,
            tuple(params) + (tenant_id, connector_id),
        )
    except psycopg2.Error as exc:
        if _name_taken(exc):
            raise ConnectorError(CODE_NAME_TAKEN, f"A connector named {changes.get('name')!r} already exists.") from exc
        raise
    if not rows:
        return None
    return get_connector(db, tenant_id, connector_id)


def soft_delete_connector(db: Any, tenant_id: str, connector_id: str) -> Optional[Dict[str, Any]]:
    """Soft-delete a live connector and destroy its sealed credential.

    The inventory, the runs and the catalog items stay: a deleted connector stops syncing, it
    does not unmake what it imported. The credential is deleted outright because nothing can use
    it any more.

    Returns:
        The deleted connector's id and name, or ``None`` when it did not exist.
    """
    row = _first(
        db.execute_query(
            """
            UPDATE apiome.catalog_connectors
            SET deleted_at = now(), updated_at = now(), status = %s
            WHERE tenant_id = %s::uuid AND id = %s::uuid AND deleted_at IS NULL
            RETURNING id, name, kind
            """,
            (STATUS_PAUSED, tenant_id, connector_id),
        )
    )
    if row is not None:
        db._execute_write(
            "DELETE FROM apiome.catalog_connector_credentials WHERE connector_id = %s::uuid",
            (connector_id,),
        )
    return row


def list_due_connectors(db: Any, *, default_interval_seconds: int, floor_seconds: int) -> List[Dict[str, Any]]:
    """Live connectors due for a scheduled sync, oldest run first.

    A connector is due when it is not paused and its last run is older than its cadence (the
    deployment default when it has none), never less than the floor.
    """
    return db.execute_query(
        f"""
        SELECT {_CONNECTOR_COLUMNS}
        FROM apiome.catalog_connectors c
        WHERE c.deleted_at IS NULL
          AND c.status <> %s
          AND (
            c.last_run_at IS NULL
            OR c.last_run_at <= now() - make_interval(
                 secs => GREATEST(COALESCE(c.refresh_interval_seconds, %s), %s))
          )
        ORDER BY c.last_run_at NULLS FIRST, c.id
        """,
        (STATUS_PAUSED, int(default_interval_seconds), int(floor_seconds)),
    )


def record_connector_outcome(db: Any, connector_id: str, *, status: Optional[str]) -> None:
    """Stamp a run's end on its connector: ``last_run_at`` always, ``status`` when given.

    A paused connector stays paused (a manual sync of a paused connector does not resume it).
    """
    db._execute_write(
        """
        UPDATE apiome.catalog_connectors
        SET last_run_at = now(),
            status = CASE WHEN status = %s OR %s IS NULL THEN status ELSE %s END
        WHERE id = %s::uuid
        """,
        (STATUS_PAUSED, status, status, connector_id),
    )


# ---------------------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------------------


def put_credentials(
    db: Any,
    connector_id: str,
    *,
    encrypted_payload: bytes,
    key_version: int,
    created_by: Optional[str],
) -> Dict[str, Any]:
    """Store (or replace) a connector's sealed credential.

    Returns:
        ``{connector_id, replaced_at}`` — never the payload.
    """
    return _first(
        db.execute_query(
            """
            INSERT INTO apiome.catalog_connector_credentials
              (connector_id, encrypted_payload, key_version, created_by)
            VALUES (%s::uuid, %s, %s, %s)
            ON CONFLICT (connector_id) DO UPDATE
              SET encrypted_payload = EXCLUDED.encrypted_payload,
                  key_version = EXCLUDED.key_version,
                  created_by = EXCLUDED.created_by,
                  replaced_at = now()
            RETURNING connector_id, replaced_at
            """,
            (connector_id, psycopg2.Binary(encrypted_payload), int(key_version), created_by),
        )
    ) or {}


def get_sealed_credentials(db: Any, connector_id: str) -> Optional[Dict[str, Any]]:
    """The sealed credential (``encrypted_payload``, ``key_version``), for the sync engine only."""
    return _first(
        db.execute_query(
            """
            SELECT encrypted_payload, key_version
            FROM apiome.catalog_connector_credentials
            WHERE connector_id = %s::uuid
            """,
            (connector_id,),
        )
    )


# ---------------------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------------------


def list_item_rows(db: Any, connector_id: str) -> List[Dict[str, Any]]:
    """Every inventory row of a connector (the sync engine's view)."""
    return db.execute_query(
        f"SELECT {_ITEM_COLUMNS} FROM apiome.catalog_connector_items i WHERE i.connector_id = %s::uuid",
        (connector_id,),
    )


def list_items(
    db: Any, connector_id: str, *, status: Optional[str], limit: int, offset: int
) -> List[Dict[str, Any]]:
    """A page of a connector's inventory, by remote name."""
    clause, params = ("AND i.status = %s", (status,)) if status else ("", ())
    return db.execute_query(
        f"""
        SELECT {_ITEM_COLUMNS}
        FROM apiome.catalog_connector_items i
        WHERE i.connector_id = %s::uuid {clause}
        ORDER BY lower(COALESCE(i.remote_name, i.remote_id)), i.remote_id
        LIMIT %s OFFSET %s
        """,
        (connector_id,) + params + (int(limit), int(offset)),
    )


def count_items(db: Any, connector_id: str, *, status: Optional[str]) -> int:
    """How many inventory rows :func:`list_items` pages over."""
    clause, params = ("AND status = %s", (status,)) if status else ("", ())
    rows = db.execute_query(
        f"SELECT COUNT(*) AS n FROM apiome.catalog_connector_items WHERE connector_id = %s::uuid {clause}",
        (connector_id,) + params,
    )
    return int(rows[0]["n"]) if rows else 0


def upsert_seen_item(db: Any, connector_id: str, candidate: RefreshCandidate) -> Dict[str, Any]:
    """Record that a sync saw ``candidate``: insert it, or refresh what the remote reports.

    A ``missing`` row that reappears returns to ``imported`` when it has a catalog item (or, for an
    ``mcp-registry`` entry, an MCP server that answered: CDG-4.4) and to ``discovered`` otherwise;
    ``ignored`` stays ignored. ``deployment`` (V282) is replaced with
    what the latest sync saw. The returned row's ``inserted`` is true when this sync saw the API
    for the first time (CDG-1.6 notifies new shadow APIs).
    """
    return _first(
        db.execute_query(
            f"""
            INSERT INTO apiome.catalog_connector_items AS i
              (connector_id, remote_id, remote_name, environment, hosts, base_path,
               remote_revision, remote_updated_at, deployment, status)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (connector_id, remote_id) DO UPDATE
              SET remote_name = EXCLUDED.remote_name,
                  environment = EXCLUDED.environment,
                  hosts = EXCLUDED.hosts,
                  base_path = EXCLUDED.base_path,
                  deployment = EXCLUDED.deployment,
                  remote_revision = EXCLUDED.remote_revision,
                  remote_updated_at = EXCLUDED.remote_updated_at,
                  last_seen_at = now(),
                  status = CASE
                    WHEN i.status = %s THEN i.status
                    WHEN i.project_id IS NOT NULL THEN %s
                    WHEN i.mcp_endpoint_id IS NOT NULL AND i.discovered_reason IS NULL THEN %s
                    ELSE %s
                  END
            RETURNING {_ITEM_COLUMNS}, (i.xmax = 0) AS inserted
            """,
            (
                connector_id,
                candidate.remote_id,
                candidate.name,
                candidate.environment,
                list(candidate.hosts),
                candidate.base_path,
                candidate.revision,
                candidate.updated_at,
                json.dumps(dict(candidate.deployment or {}), sort_keys=True, default=str),
                ITEM_DISCOVERED,
                ITEM_IGNORED,
                ITEM_IMPORTED,
                ITEM_IMPORTED,
                ITEM_DISCOVERED,
            ),
        )
    ) or {}


def mark_missing_items(db: Any, connector_id: str, seen_remote_ids: Iterable[str]) -> int:
    """Mark every row the latest inventory did not include as ``missing``. Never deletes.

    An ``ignored`` row keeps its status: ignoring is the tenant's choice and outlives the API
    briefly leaving the inventory. The catalog item a missing row points at is untouched.

    Returns:
        How many rows became missing in this run.
    """
    return int(
        db._execute_write(
            """
            UPDATE apiome.catalog_connector_items
            SET status = %s
            WHERE connector_id = %s::uuid
              AND status NOT IN (%s, %s)
              AND NOT (remote_id = ANY(%s))
            """,
            (ITEM_MISSING, connector_id, ITEM_MISSING, ITEM_IGNORED, list(seen_remote_ids)),
        )
        or 0
    )


def mark_item_imported(
    db: Any,
    item_id: str,
    *,
    project_id: str,
    revision: Optional[str],
    remote_updated_at: Any,
    content_sha256: str,
) -> None:
    """Record a successful import: the catalog item and the new freshness anchor."""
    db._execute_write(
        """
        UPDATE apiome.catalog_connector_items
        SET status = %s, project_id = %s::uuid, imported_revision = %s,
            imported_remote_updated_at = %s, imported_sha256 = %s
        WHERE id = %s::uuid
        """,
        (ITEM_IMPORTED, project_id, revision, remote_updated_at, content_sha256, item_id),
    )


def mark_item_mcp_server(
    db: Any,
    item_id: str,
    *,
    mcp_endpoint_id: Optional[str],
    discovered_reason: Optional[str],
    revision: Optional[str],
    remote_updated_at: Any,
    project_id: Optional[str] = None,
) -> None:
    """Record the outcome of syncing one entry through a source's ``sync_item`` hook (CDG-4.4).

    Used by ``mcp-registry`` (an MCP server) and ``schema-registry`` (a mirrored subject's catalog
    item, MFI-12.3).

    With no ``discovered_reason`` the server answered: the row is ``imported`` and the freshness
    anchor moves to ``revision``. With a reason the row stays ``discovered`` and keeps no anchor, so
    the next sync tries the entry again; ``mcp_endpoint_id`` is still recorded when a server was
    created for it (discovery could not reach it).

    Args:
        db: Database handle.
        item_id: The inventory row.
        mcp_endpoint_id: The MCP server created or refreshed for the entry, if any.
        discovered_reason: Why the entry is not imported, or ``None`` when it is.
        revision: The entry's remote revision (the anchor when imported).
        remote_updated_at: The registry's ``updatedAt`` for the entry.
        project_id: The catalog item the entry backs, if any; ``None`` keeps the stored one.
    """
    imported = discovered_reason is None
    db._execute_write(
        """
        UPDATE apiome.catalog_connector_items
        SET status = %s, mcp_endpoint_id = %s::uuid, discovered_reason = %s,
            project_id = COALESCE(%s::uuid, project_id),
            imported_revision = CASE WHEN %s THEN %s ELSE NULL END,
            imported_remote_updated_at = CASE WHEN %s THEN %s::timestamptz ELSE NULL END
        WHERE id = %s::uuid
        """,
        (
            ITEM_IMPORTED if imported else ITEM_DISCOVERED,
            mcp_endpoint_id,
            discovered_reason[:1000] if discovered_reason else None,
            project_id,
            imported,
            revision,
            imported,
            remote_updated_at,
            item_id,
        ),
    )


# ---------------------------------------------------------------------------------------
# Runs (the shared refresh ledger)
# ---------------------------------------------------------------------------------------


def start_run(
    db: Any, tenant_id: str, connector_id: str, *, trigger: str, created_by: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Open a ``running`` run for a connector, or return ``None`` when one is already active.

    A run left ``running`` for longer than :data:`STALE_RUN_SECONDS` belonged to a process that
    died; it is closed as failed (``abandoned``) first so it cannot block the connector forever.
    """
    db._execute_write(
        """
        UPDATE apiome.tenant_repository_refresh_jobs
        SET status = 'failed', error_class = 'abandoned', finished_at = now(),
            error_message = 'The run did not finish; its process stopped.'
        WHERE connector_id = %s::uuid AND refresh_source = 'connector'
          AND status IN ('queued', 'running')
          AND COALESCE(started_at, created_at) < now() - make_interval(secs => %s)
        """,
        (connector_id, STALE_RUN_SECONDS),
    )
    try:
        return _first(
            db.execute_query(
                f"""
                INSERT INTO apiome.tenant_repository_refresh_jobs AS j
                  (tenant_id, connector_id, refresh_source, status, started_at, refresh_reason,
                   created_by, run_summary)
                VALUES (%s::uuid, %s::uuid, 'connector', 'running', now(), %s, %s, %s::jsonb)
                RETURNING {_RUN_COLUMNS}
                """,
                (
                    tenant_id,
                    connector_id,
                    trigger,
                    created_by,
                    json.dumps({"trigger": trigger}),
                ),
            )
        )
    except psycopg2.errors.UniqueViolation:
        return None


def finish_run(
    db: Any,
    run_id: str,
    *,
    status: str,
    pull_count: int,
    summary: Mapping[str, Any],
    error_class: Optional[str] = None,
    http_status: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Close a run with its outcome and counts."""
    db._execute_write(
        """
        UPDATE apiome.tenant_repository_refresh_jobs
        SET status = %s, pull_count = %s, run_summary = %s::jsonb, error_class = %s,
            http_status = %s, error_message = %s, finished_at = now()
        WHERE id = %s::uuid
        """,
        (
            status,
            int(pull_count),
            json.dumps(dict(summary), default=str),
            error_class,
            http_status,
            error_message,
            run_id,
        ),
    )


def list_runs(db: Any, tenant_id: str, connector_id: str, *, limit: int, offset: int) -> List[Dict[str, Any]]:
    """A page of a connector's runs, newest first."""
    return db.execute_query(
        f"""
        SELECT {_RUN_COLUMNS}
        FROM apiome.tenant_repository_refresh_jobs j
        WHERE j.tenant_id = %s::uuid AND j.connector_id = %s::uuid AND j.refresh_source = 'connector'
        ORDER BY j.created_at DESC, j.id DESC
        LIMIT %s OFFSET %s
        """,
        (tenant_id, connector_id, int(limit), int(offset)),
    )


def count_runs(db: Any, tenant_id: str, connector_id: str) -> int:
    """How many runs :func:`list_runs` pages over."""
    rows = db.execute_query(
        """
        SELECT COUNT(*) AS n FROM apiome.tenant_repository_refresh_jobs
        WHERE tenant_id = %s::uuid AND connector_id = %s::uuid AND refresh_source = 'connector'
        """,
        (tenant_id, connector_id),
    )
    return int(rows[0]["n"]) if rows else 0


# ---------------------------------------------------------------------------------------
# The unified refresh-run ledger (CDG-1.7)
# ---------------------------------------------------------------------------------------

_LEDGER_FILTER = """
    WHERE j.tenant_id = %s::uuid
      AND (%s::uuid IS NULL OR j.connector_id = %s::uuid)
      AND (%s::text IS NULL OR j.refresh_source = %s)
"""


def list_refresh_runs(
    db: Any,
    tenant_id: str,
    *,
    connector_id: Optional[str],
    source: Optional[str],
    limit: int,
    offset: int,
) -> List[Dict[str, Any]]:
    """Git refresh jobs and connector runs of a tenant, interleaved newest first (CDG-1.7).

    Both live on ``tenant_repository_refresh_jobs`` (``refresh_source`` says which); each row carries
    the repository or the connector it belongs to, so one ledger can show both with a source badge.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        connector_id: Only this connector's runs (implies ``source = 'connector'``).
        source: ``git`` or ``connector``, or ``None`` for both.
        limit: Page size.
        offset: Page start.
    """
    return db.execute_query(
        f"""
        SELECT j.id, j.refresh_source, j.status, j.refresh_reason, j.error_class, j.http_status,
               j.error_message, j.pull_count, j.run_summary, j.created_at, j.started_at, j.finished_at,
               j.connector_id, c.name AS connector_name, c.kind AS connector_kind,
               j.repository_id, r.repository_full_name, j.branch, j.path
        FROM apiome.tenant_repository_refresh_jobs j
        LEFT JOIN apiome.catalog_connectors c ON c.id = j.connector_id
        LEFT JOIN apiome.tenant_repositories r ON r.id = j.repository_id
        {_LEDGER_FILTER}
        ORDER BY j.created_at DESC, j.id DESC
        LIMIT %s OFFSET %s
        """,
        (tenant_id, connector_id, connector_id, source, source, int(limit), int(offset)),
    )


def count_refresh_runs(db: Any, tenant_id: str, *, connector_id: Optional[str], source: Optional[str]) -> int:
    """How many rows :func:`list_refresh_runs` would page through."""
    rows = db.execute_query(
        f"SELECT count(*) AS n FROM apiome.tenant_repository_refresh_jobs j {_LEDGER_FILTER}",
        (tenant_id, connector_id, connector_id, source, source),
    )
    return int(rows[0]["n"]) if rows else 0
