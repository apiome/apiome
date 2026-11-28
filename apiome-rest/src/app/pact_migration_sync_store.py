"""Where keep-in-sync is kept — PFX-8.17 (#7314).

The rows of ``apiome.pact_migration_sync`` (V459): one per migration run that has been kept in sync.
The routes (:mod:`app.pact_migration_run_routes`) switch it on and off; the sweep
(:mod:`app.pact_migration_sync`) claims the passes that are due and records how each went.

**The source's credentials are kept only while it is on, and only sealed.** A scheduled pass has no
one to ask for the token, so it is sealed by the envelope cipher (AES-256-GCM with a per-secret data
key wrapped by a versioned master key — the credential vault's ``APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS``,
under this vault's own magic ``OPMS``) and cleared the moment the sync is switched off or stops
itself. The database refuses an enabled row without it, and a disabled row with it. **Fails closed:**
without a master key nothing can be sealed (:func:`credentials_configured` is ``False`` and the route
answers 503), and a blob that cannot be opened stops the sync with the reason.

Every read and write is scoped to the tenant given, except the sweep's claim, which hands each row
its own tenant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

import psycopg2

from .config import settings
from .consumer_contract_store import ConsumerActor
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError
from .revision_deprecation import is_uuid_string

__all__ = [
    "CODE_SYNC_ACTIVE",
    "CODE_SYNC_UNAVAILABLE",
    "KEYS_SETTING",
    "SyncActiveError",
    "SyncCredentialError",
    "claim_due",
    "credentials_configured",
    "disable_sync",
    "enable_sync",
    "get_sync",
    "record_pass",
    "seal_credentials",
    "unseal_credentials",
]

#: Another migration of the workspace is already kept in sync (HTTP 409).
CODE_SYNC_ACTIVE = "pact-migration-sync-active"
#: No master key is configured, so credentials cannot be kept (HTTP 503).
CODE_SYNC_UNAVAILABLE = "pact-migration-sync-unavailable"

#: The environment variable holding the master keys.
KEYS_SETTING = "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS"

#: Raised when credentials cannot be sealed. Its message never contains secret material.
SyncCredentialError = EnvelopeEncryptionError

#: ``OPMS`` = *apiome Pact Migration Sync*.
_CIPHER = EnvelopeCipher(
    magic=b"OPMS",
    subject="migration source credentials",
    keys_setting=KEYS_SETTING,
    read_keys=lambda: settings.mcp_credential_encryption_keys,
    read_active_version=lambda: settings.mcp_credential_active_key_version,
)

_COLUMNS = """
    run_id::text AS run_id, tenant_id::text AS tenant_id, enabled, interval_seconds, credential_ciphertext,
    key_version, next_run_at, last_pass_at, last_success_at, unreachable_since, passes, last_error, stopped_reason,
    enabled_by::text AS enabled_by, enabled_by_label, created_at, updated_at
"""


class SyncActiveError(Exception):
    """Another migration of the workspace is already kept in sync."""

    code = CODE_SYNC_ACTIVE


def credentials_configured() -> bool:
    """Whether a master key is configured, so credentials can be kept for keep-in-sync."""
    return _CIPHER.configured()


def seal_credentials(credentials: Mapping[str, Optional[str]]) -> Tuple[bytes, int]:
    """Seal the source's credentials for storage.

    Args:
        credentials: ``{"token": …, "username": …, "password": …}``, each optional.

    Returns:
        ``(ciphertext, key_version)``.

    Raises:
        SyncCredentialError: When no master key is configured or the key map is malformed.
    """
    return _CIPHER.seal({name: value for name, value in credentials.items() if value})


def unseal_credentials(ciphertext: Optional[bytes], key_version: Optional[int]) -> Optional[Dict[str, Any]]:
    """Open stored credentials, in memory, for one pass.

    Args:
        ciphertext: The stored blob.
        key_version: The master key version that sealed it.

    Returns:
        The credentials, or ``None`` when there are none or they cannot be opened (no key, wrong
        key, tampered).
    """
    if ciphertext is None:
        return None
    return _CIPHER.unseal(bytes(ciphertext), key_version)


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a uuid (an API key has none)."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def get_sync(db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """The keep-in-sync row of one of the tenant's runs.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        run_id: The run.

    Returns:
        Its row, or ``None`` when the run was never kept in sync (or is not the tenant's).
    """
    if not is_uuid_string(str(run_id or "")) or not is_uuid_string(str(tenant_id or "")):
        return None
    rows = db.execute_query(
        f"SELECT {_COLUMNS} FROM apiome.pact_migration_sync WHERE tenant_id = %s::uuid AND run_id = %s::uuid",
        (tenant_id, run_id),
    )
    return dict(rows[0]) if rows else None


def enable_sync(
    db: Any,
    tenant_id: str,
    run_id: str,
    *,
    ciphertext: bytes,
    key_version: int,
    interval_seconds: int,
    actor: ConsumerActor,
) -> Dict[str, Any]:
    """Switch keep-in-sync on for a run (or on again), with freshly sealed credentials.

    The first pass is due one interval from now: the copy that was just made is the latest.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        run_id: The run (a copy of the tenant's; the route checks).
        ciphertext: The sealed credentials.
        key_version: The key version that sealed them.
        interval_seconds: How often to copy again.
        actor: Who switched it on — the author of everything the passes write.

    Returns:
        The row.

    Raises:
        SyncActiveError: When another run of the tenant is kept in sync.
    """

    def work(cursor: Any) -> Dict[str, Any]:
        cursor.execute(
            f"""
            INSERT INTO apiome.pact_migration_sync (run_id, tenant_id, enabled, interval_seconds, credential_ciphertext,
                                                    key_version, next_run_at, enabled_by, enabled_by_label)
            VALUES (%s::uuid, %s::uuid, TRUE, %s, %s, %s, CURRENT_TIMESTAMP + make_interval(secs => %s), %s::uuid, %s)
            ON CONFLICT (run_id) DO UPDATE
            SET enabled = TRUE, interval_seconds = EXCLUDED.interval_seconds,
                credential_ciphertext = EXCLUDED.credential_ciphertext, key_version = EXCLUDED.key_version,
                next_run_at = EXCLUDED.next_run_at, unreachable_since = NULL, last_error = NULL, stopped_reason = NULL,
                enabled_by = EXCLUDED.enabled_by, enabled_by_label = EXCLUDED.enabled_by_label,
                updated_at = CURRENT_TIMESTAMP
            RETURNING {_COLUMNS}
            """,
            (
                run_id,
                tenant_id,
                interval_seconds,
                psycopg2.Binary(ciphertext),
                key_version,
                interval_seconds,
                _user_id(actor),
                actor.label,
            ),
        )
        return dict(cursor.fetchone())

    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise SyncActiveError(
            "another migration of this workspace is already kept in sync; switch that one off first"
        ) from exc


def disable_sync(db: Any, tenant_id: str, run_id: str, *, reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Switch keep-in-sync off and let go of the credentials.

    Args:
        db: The database.
        tenant_id: The run's tenant.
        run_id: The run.
        reason: Why it stopped itself (``None`` when someone switched it off).

    Returns:
        The row afterwards, or ``None`` when the run was never kept in sync.
    """
    if not is_uuid_string(str(run_id or "")) or not is_uuid_string(str(tenant_id or "")):
        return None

    def work(cursor: Any) -> Any:
        cursor.execute(
            f"""
            UPDATE apiome.pact_migration_sync
            SET enabled = FALSE, credential_ciphertext = NULL, key_version = NULL, stopped_reason = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s::uuid AND run_id = %s::uuid
            RETURNING {_COLUMNS}
            """,
            (reason, tenant_id, run_id),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else False

    row = db._guarded_tx(work)
    return row or None


def claim_due(db: Any, *, limit: int) -> List[Dict[str, Any]]:
    """Claim the passes that are due, oldest first, moving each one's next pass an interval on.

    Rows another replica is claiming are skipped (``FOR UPDATE SKIP LOCKED``), so a pass is claimed
    once.

    Args:
        db: The database.
        limit: The most passes.

    Returns:
        The claimed rows, credentials included.
    """

    def work(cursor: Any) -> List[Dict[str, Any]]:
        cursor.execute(
            f"""
            UPDATE apiome.pact_migration_sync s
            SET next_run_at = CURRENT_TIMESTAMP + make_interval(secs => s.interval_seconds),
                last_pass_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE s.run_id IN (
                SELECT run_id FROM apiome.pact_migration_sync
                WHERE enabled AND next_run_at <= CURRENT_TIMESTAMP
                ORDER BY next_run_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            RETURNING {_COLUMNS}
            """,
            (max(1, int(limit)),),
        )
        return [dict(row) for row in cursor.fetchall() or []]

    return list(db._guarded_tx(work) or [])


def record_pass(
    db: Any, run_id: str, *, ok: bool, error: Optional[str] = None, unreachable: bool = False
) -> Optional[Dict[str, Any]]:
    """Record how a pass went.

    Args:
        db: The database.
        run_id: The run.
        ok: The copy completed.
        error: What went wrong, otherwise.
        unreachable: The source could not be read — starts (or keeps) the 24-hour clock.

    Returns:
        The row afterwards (``unreachable_since`` says since when), or ``None`` when it is gone.
    """

    def work(cursor: Any) -> Any:
        cursor.execute(
            f"""
            UPDATE apiome.pact_migration_sync
            SET passes = passes + CASE WHEN %s THEN 1 ELSE 0 END,
                last_success_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE last_success_at END,
                unreachable_since = CASE WHEN %s THEN NULL
                                         WHEN %s THEN COALESCE(unreachable_since, CURRENT_TIMESTAMP)
                                         ELSE unreachable_since END,
                last_error = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE run_id = %s::uuid
            RETURNING {_COLUMNS}
            """,
            (ok, ok, ok, unreachable, None if ok else error, run_id),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else False

    row = db._guarded_tx(work)
    return row or None
