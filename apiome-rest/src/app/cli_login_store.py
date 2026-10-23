"""Persistence for `apiome login` (#5501; apiome-db V315 ``cli_login_requests``, ``api_keys.cli_login``).

Every function takes the :class:`~app.database.Database` it runs on. Each write is one statement,
so the state changes (approve, deny, collect) are atomic without a client-side transaction:
collecting a key claims the approved row *and* inserts the key in a single statement, so a key is
minted at most once per approval even when two polls race.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

__all__ = [
    "approve_request",
    "collect_key",
    "create_request",
    "deny_request",
    "find_live_request",
    "purge_stale_requests",
    "record_poll",
    "revoke_cli_login_key",
]

_REQUEST_COLUMNS = """
    r.id::text AS id, r.user_code, r.client_name, r.status, r.user_id::text AS user_id,
    r.tenant_id::text AS tenant_id, r.api_key_id::text AS api_key_id, r.created_at, r.expires_at,
    r.decided_at, r.consumed_at, r.last_polled_at
"""


def _first(rows: Any) -> Optional[Dict[str, Any]]:
    """The first row as a plain dict, or ``None``."""
    return dict(rows[0]) if rows else None


def purge_stale_requests(db) -> None:
    """Delete logins that expired more than a day ago (any status).

    Args:
        db: The database.
    """
    db.execute_query(
        """
        DELETE FROM apiome.cli_login_requests
         WHERE expires_at < CURRENT_TIMESTAMP - INTERVAL '1 day'
        RETURNING id
        """
    )


def create_request(
    db,
    *,
    device_code_hash: str,
    user_code: str,
    client_name: Optional[str],
    expires_at: datetime,
) -> Optional[Dict[str, Any]]:
    """Store a new pending login.

    Args:
        db: The database.
        device_code_hash: SHA-256 hex of the device code.
        user_code: The canonical user code.
        client_name: What the CLI called itself.
        expires_at: When the login lapses.

    Returns:
        The stored row, or ``None`` when the user code is already live (the caller picks another).
    """
    rows = db.execute_query(
        f"""
        INSERT INTO apiome.cli_login_requests AS r (device_code_hash, user_code, client_name, expires_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING {_REQUEST_COLUMNS}
        """,
        (device_code_hash, user_code, client_name, expires_at),
    )
    return _first(rows)


def find_live_request(db, user_code: str) -> Optional[Dict[str, Any]]:
    """The pending, unexpired login with this user code.

    Args:
        db: The database.
        user_code: The canonical user code.

    Returns:
        The row, or ``None`` when there is no such pending login.
    """
    rows = db.execute_query(
        f"""
        SELECT {_REQUEST_COLUMNS}
          FROM apiome.cli_login_requests r
         WHERE r.user_code = %s AND r.status = 'pending' AND r.expires_at > CURRENT_TIMESTAMP
        """,
        (user_code,),
    )
    return _first(rows)


def approve_request(db, *, user_code: str, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Approve a pending login for one workspace.

    Args:
        db: The database.
        user_code: The canonical user code.
        user_id: The approving user (the minted key's creator).
        tenant_id: The workspace the key will belong to.

    Returns:
        The updated row, or ``None`` when the login is no longer pending (or expired).
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.cli_login_requests AS r
           SET status = 'approved', user_id = %s::uuid, tenant_id = %s::uuid,
               decided_at = CURRENT_TIMESTAMP
         WHERE r.user_code = %s AND r.status = 'pending' AND r.expires_at > CURRENT_TIMESTAMP
        RETURNING {_REQUEST_COLUMNS}
        """,
        (user_id, tenant_id, user_code),
    )
    return _first(rows)


def deny_request(db, *, user_code: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Deny a pending login.

    Args:
        db: The database.
        user_code: The canonical user code.
        user_id: The person denying it.

    Returns:
        The updated row, or ``None`` when the login is no longer pending (or expired).
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.cli_login_requests AS r
           SET status = 'denied', user_id = %s::uuid, decided_at = CURRENT_TIMESTAMP
         WHERE r.user_code = %s AND r.status = 'pending' AND r.expires_at > CURRENT_TIMESTAMP
        RETURNING {_REQUEST_COLUMNS}
        """,
        (user_id, user_code),
    )
    return _first(rows)


def record_poll(db, device_code_hash: str) -> Optional[Dict[str, Any]]:
    """Look a login up by its device code and stamp this poll.

    Args:
        db: The database.
        device_code_hash: SHA-256 hex of the device code.

    Returns:
        The row (after the stamp) with ``previous_poll_at`` — the time of the poll before this
        one, or ``None`` — or ``None`` when no login has that device code.
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.cli_login_requests AS r
           SET last_polled_at = CURRENT_TIMESTAMP
          FROM (
                SELECT id, last_polled_at AS previous_poll_at
                  FROM apiome.cli_login_requests
                 WHERE device_code_hash = %s
                 FOR UPDATE
               ) p
         WHERE r.id = p.id
        RETURNING {_REQUEST_COLUMNS}, p.previous_poll_at
        """,
        (device_code_hash,),
    )
    return _first(rows)


def collect_key(
    db,
    *,
    device_code_hash: str,
    key_id: str,
    key_name: str,
    key_hash: str,
    key_prefix: str,
    key_expires_at: datetime,
) -> Optional[Dict[str, Any]]:
    """Claim an approved login and mint its key, in one statement.

    The claim (``approved`` → ``consumed``) and the key insert succeed together or not at all, and
    only one caller can claim a row, so a login yields at most one key. The key is a full-access
    workspace key (``scopes = {*}``) created by the approving user, marked ``cli_login``. The
    workspace must still be active.

    Args:
        db: The database.
        device_code_hash: SHA-256 hex of the device code.
        key_id: The new key's id (generated by the caller so the claim can reference it).
        key_name: The key's name, unique in the workspace.
        key_hash: bcrypt hash of the secret.
        key_prefix: The lookup prefix.
        key_expires_at: When the key stops working.

    Returns:
        ``{key_id, key_name, key_prefix, expires_at, tenant_slug, tenant_name}``, or ``None`` when
        the login is not approved, expired, or its workspace is gone.
    """
    rows = db.execute_query(
        """
        WITH claimed AS (
            UPDATE apiome.cli_login_requests AS r
               SET status = 'consumed', consumed_at = CURRENT_TIMESTAMP, api_key_id = %s::uuid
              FROM apiome.tenants t
             WHERE r.device_code_hash = %s AND r.status = 'approved'
               AND r.expires_at > CURRENT_TIMESTAMP
               AND t.id = r.tenant_id AND t.deleted_at IS NULL AND t.enabled = true
            RETURNING r.tenant_id, r.user_id, t.slug AS tenant_slug, t.name AS tenant_name
        ), minted AS (
            INSERT INTO apiome.api_keys (
                id, tenant_id, name, description, key_hash, key_prefix, expires_at,
                created_by_user_id, scopes, cli_login
            )
            SELECT %s::uuid, c.tenant_id, %s, 'Created by `apiome login`.', %s, %s, %s,
                   c.user_id, ARRAY['*']::text[], true
              FROM claimed c
            RETURNING id::text AS key_id, name AS key_name, key_prefix, expires_at
        )
        SELECT m.key_id, m.key_name, m.key_prefix, m.expires_at, c.tenant_slug, c.tenant_name
          FROM minted m CROSS JOIN claimed c
        """,
        (key_id, device_code_hash, key_id, key_name, key_hash, key_prefix, key_expires_at),
    )
    return _first(rows)


def revoke_cli_login_key(db, key_id: str) -> Optional[bool]:
    """Revoke a key minted by `apiome login` (soft delete, like the API Keys page).

    Args:
        db: The database.
        key_id: The key presenting itself.

    Returns:
        ``True`` when revoked, ``False`` when the key exists but is not a CLI login key (it must be
        revoked from the API Keys page), ``None`` when there is no live key with that id.
    """
    rows = db.execute_query(
        """
        WITH target AS (
            SELECT id, cli_login FROM apiome.api_keys
             WHERE id = %s::uuid AND deleted_at IS NULL
        ), revoked AS (
            UPDATE apiome.api_keys k
               SET deleted_at = CURRENT_TIMESTAMP, enabled = false, updated_at = CURRENT_TIMESTAMP
              FROM target
             WHERE k.id = target.id AND target.cli_login
            RETURNING k.id
        )
        SELECT target.cli_login, (SELECT count(*) FROM revoked) AS revoked FROM target
        """,
        (key_id,),
    )
    if not rows:
        return None
    return bool(rows[0]["revoked"])
