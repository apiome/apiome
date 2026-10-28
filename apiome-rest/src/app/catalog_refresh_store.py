"""Catalog item refresh storage — MFI-31.1 (#4398).

SQL over ``apiome.catalog_item_refresh`` and ``apiome.tenants.catalog_refresh_enabled`` (V333).

Every function takes the :class:`~app.database.Database` it runs on, so the scheduled sweep can use
its per-tick connection and tests can pass a fake. Reads for the API are scoped by tenant and never
return the sealed credential (only ``has_credential``); :func:`get_refresh_for_check` is the one
read that returns the sealed blob, for the check runner.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

import psycopg2

from .catalog_refresh import CADENCE_SECONDS, STATUS_FAILED, STATUS_NEVER

__all__ = [
    "KEEP_CREDENTIAL",
    "delete_refresh",
    "get_refresh",
    "get_refresh_for_check",
    "get_tenant_refresh_enabled",
    "list_due",
    "record_failure",
    "record_success",
    "set_tenant_refresh_enabled",
    "upsert_refresh",
]

#: Pass as ``credential`` to :func:`upsert_refresh` to keep the stored credential as it is.
KEEP_CREDENTIAL = object()

#: The columns the API may see. ``has_credential`` stands in for the sealed blob.
_PUBLIC_COLUMNS = """
    r.project_id, r.tenant_id, r.cadence, r.adapter_key, r.endpoint, r.options, r.auth_type,
    (r.encrypted_payload IS NOT NULL) AS has_credential,
    r.status, r.last_checked_at, r.last_success_at, r.last_failure_at, r.last_error,
    r.last_fingerprint, r.consecutive_failures, r.next_check_after, r.created_at, r.updated_at
"""


def _first(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The first row, or ``None``."""
    return dict(rows[0]) if rows else None


def get_refresh(db: Any, project_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """An item's refresh setting and status for the API, or ``None`` when it has none.

    Args:
        db: Database handle.
        project_id: The catalog item id.
        tenant_id: The caller's tenant; a row in another tenant is not found.
    """
    return _first(
        db.execute_query(
            f"""
            SELECT {_PUBLIC_COLUMNS}
            FROM apiome.catalog_item_refresh r
            WHERE r.project_id = %s::uuid AND r.tenant_id = %s::uuid
            """,
            (project_id, tenant_id),
        )
    )


def get_refresh_for_check(db: Any, project_id: str) -> Optional[Dict[str, Any]]:
    """The full row, including the sealed credential, for the check runner only.

    Also carries ``created_by`` / ``updated_by``: a version a scheduled check creates is
    attributed to whoever last saved the setting (MFI-31.2).
    """
    return _first(
        db.execute_query(
            f"""
            SELECT {_PUBLIC_COLUMNS}, r.encrypted_payload, r.key_version, r.created_by, r.updated_by
            FROM apiome.catalog_item_refresh r
            WHERE r.project_id = %s::uuid
            """,
            (project_id,),
        )
    )


def upsert_refresh(
    db: Any,
    *,
    project_id: str,
    tenant_id: str,
    cadence: str,
    adapter_key: str,
    endpoint: str,
    options: Mapping[str, Any],
    credential: Any = KEEP_CREDENTIAL,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or replace an item's refresh setting.

    Changing the adapter or endpoint points the item at a different source, so the check history
    (status, fingerprint, failures, backoff) is reset; changing only the cadence or the credential
    keeps it. Saving always clears the backoff, so a fixed setting is checked on its next due tick.

    Args:
        db: Database handle.
        project_id: The catalog item id.
        tenant_id: The item's tenant.
        cadence: A validated cadence.
        adapter_key: A validated, canonical adapter key.
        endpoint: A validated endpoint.
        options: Adapter options (e.g. ``{"secure": true}`` for gRPC).
        credential: :data:`KEEP_CREDENTIAL` to keep the stored one; ``None`` to clear it; or a
            sealed ``(auth_type, encrypted_payload, key_version)`` tuple to replace it.
        user_id: The acting user, stamped as creator / updater.

    Returns:
        The stored row, in the :func:`get_refresh` shape.
    """
    keep = credential is KEEP_CREDENTIAL
    auth_type, payload, key_version = ("none", None, None)
    if not keep and credential is not None:
        sealed: Tuple[str, bytes, int] = credential
        auth_type, payload, key_version = sealed[0], psycopg2.Binary(sealed[1]), int(sealed[2])

    rows = db.execute_query(
        f"""
        WITH saved AS (
            INSERT INTO apiome.catalog_item_refresh AS r
              (project_id, tenant_id, cadence, adapter_key, endpoint, options,
               auth_type, encrypted_payload, key_version, created_by, updated_by)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id) DO UPDATE SET
              cadence = EXCLUDED.cadence,
              options = EXCLUDED.options,
              auth_type = CASE WHEN %s THEN r.auth_type ELSE EXCLUDED.auth_type END,
              encrypted_payload = CASE WHEN %s THEN r.encrypted_payload ELSE EXCLUDED.encrypted_payload END,
              key_version = CASE WHEN %s THEN r.key_version ELSE EXCLUDED.key_version END,
              status = CASE WHEN (r.adapter_key, r.endpoint) IS DISTINCT FROM
                                 (EXCLUDED.adapter_key, EXCLUDED.endpoint)
                            THEN %s ELSE r.status END,
              last_fingerprint = CASE WHEN (r.adapter_key, r.endpoint) IS DISTINCT FROM
                                           (EXCLUDED.adapter_key, EXCLUDED.endpoint)
                                      THEN NULL ELSE r.last_fingerprint END,
              last_error = CASE WHEN (r.adapter_key, r.endpoint) IS DISTINCT FROM
                                     (EXCLUDED.adapter_key, EXCLUDED.endpoint)
                                THEN NULL ELSE r.last_error END,
              adapter_key = EXCLUDED.adapter_key,
              endpoint = EXCLUDED.endpoint,
              consecutive_failures = 0,
              next_check_after = NULL,
              updated_by = EXCLUDED.updated_by,
              updated_at = now()
            RETURNING r.*
        )
        SELECT {_PUBLIC_COLUMNS} FROM saved r
        """,
        (
            project_id,
            tenant_id,
            cadence,
            adapter_key,
            endpoint,
            json.dumps(dict(options or {})),
            auth_type,
            payload,
            key_version,
            user_id,
            user_id,
            keep,
            keep,
            keep,
            STATUS_NEVER,
        ),
    )
    return _first(rows) or {}


def delete_refresh(db: Any, project_id: str, tenant_id: str) -> bool:
    """Remove an item's refresh setting (and its credential). Returns whether a row was removed."""
    return bool(
        db._execute_write(
            "DELETE FROM apiome.catalog_item_refresh WHERE project_id = %s::uuid AND tenant_id = %s::uuid",
            (project_id, tenant_id),
        )
    )


def list_due(db: Any, *, limit: int = 200) -> List[Dict[str, Any]]:
    """Rows due for a scheduled check, oldest check first, sealed credential included.

    A row is due when its cadence is scheduled (hourly / daily / weekly), it is not backing off,
    its last check is at least one cadence old, its item is a live catalog item (not deleted, not
    publishable), and its tenant has not switched catalog refresh off.
    """
    cadence_case = " ".join(f"WHEN '{name}' THEN {secs}" for name, secs in CADENCE_SECONDS.items())
    return db.execute_query(
        f"""
        SELECT {_PUBLIC_COLUMNS}, r.encrypted_payload, r.key_version, r.created_by, r.updated_by
        FROM apiome.catalog_item_refresh r
        JOIN apiome.projects p ON p.id = r.project_id
        JOIN apiome.tenants t ON t.id = r.tenant_id
        WHERE r.cadence IN ({", ".join(["%s"] * len(CADENCE_SECONDS))})
          AND p.deleted_at IS NULL
          AND p.publishable = false
          AND t.catalog_refresh_enabled
          AND (r.next_check_after IS NULL OR r.next_check_after <= now())
          AND (
            r.last_checked_at IS NULL
            OR r.last_checked_at <= now() - make_interval(secs => CASE r.cadence {cadence_case} END)
          )
        ORDER BY r.last_checked_at NULLS FIRST, r.project_id
        LIMIT %s
        """,
        (*CADENCE_SECONDS.keys(), int(limit)),
    )


def record_success(db: Any, project_id: str, *, status: str, fingerprint: str) -> None:
    """Record a successful check: the new fingerprint and status, failures and backoff cleared."""
    db._execute_write(
        """
        UPDATE apiome.catalog_item_refresh
        SET status = %s,
            last_fingerprint = %s,
            last_checked_at = now(),
            last_success_at = now(),
            last_error = NULL,
            consecutive_failures = 0,
            next_check_after = NULL
        WHERE project_id = %s::uuid
        """,
        (status, fingerprint, project_id),
    )


def record_failure(db: Any, project_id: str, *, error: str, backoff_seconds: float) -> None:
    """Record a failed check: status ``failed``, the reason, one more failure, and the backoff.

    The fingerprint is left as it was, so the next successful check still compares against the
    last surface that was actually seen.
    """
    db._execute_write(
        """
        UPDATE apiome.catalog_item_refresh
        SET status = %s,
            last_error = %s,
            last_checked_at = now(),
            last_failure_at = now(),
            consecutive_failures = consecutive_failures + 1,
            next_check_after = now() + make_interval(secs => %s)
        WHERE project_id = %s::uuid
        """,
        (STATUS_FAILED, error, float(backoff_seconds), project_id),
    )


def get_tenant_refresh_enabled(db: Any, tenant_id: str) -> bool:
    """The tenant kill switch: ``True`` unless the tenant has switched catalog refresh off."""
    row = _first(
        db.execute_query(
            "SELECT catalog_refresh_enabled FROM apiome.tenants WHERE id = %s::uuid",
            (tenant_id,),
        )
    )
    return bool(row["catalog_refresh_enabled"]) if row else True


def set_tenant_refresh_enabled(db: Any, tenant_id: str, enabled: bool) -> bool:
    """Set the tenant kill switch and return the stored value."""
    db._execute_write(
        "UPDATE apiome.tenants SET catalog_refresh_enabled = %s WHERE id = %s::uuid",
        (bool(enabled), tenant_id),
    )
    return bool(enabled)
