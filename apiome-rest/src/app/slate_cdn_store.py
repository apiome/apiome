"""Persistence for Slate CDN / edge providers — Slate 10.2 (private-suite#120).

Reads and writes V368's ``apiome.slate_cdn_providers`` and ``apiome.slate_cdn_purge_dispatches``,
following :mod:`app.slate_cache_store`: a small ``_DbLike`` protocol so the module is exercised
against a fake connection, and every read scoped to the caller's tenant.

**Attaching a provider is what attaches the edge.** :func:`save_provider` and
:func:`delete_provider` set ``slate_cache_policies.edge_attached`` / ``edge_provider`` in the same
transaction as the provider row, and write a ``cdn`` audit entry beside it. There is no moment at
which a lane has a provider but reports no edge, or reports an edge it no longer has — so V187's
``outcome <> 'dispatched' OR edge_attached`` CHECK keeps meaning what it says.

Credentials arrive here already sealed (:mod:`app.slate_cdn_crypto`). This module never sees
plaintext, and no function here returns the ciphertext to a caller that renders a response.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

__all__ = [
    "SlateCdnStoreError",
    "delete_provider",
    "get_provider",
    "list_dispatches",
    "record_dispatch",
    "save_provider",
    "verified_hosts",
]


class _DbLike(Protocol):
    """Minimal database surface used by this module."""

    def connect(self) -> Any: ...


class SlateCdnStoreError(Exception):
    """A CDN row was missing when the write needed it.

    Codes: ``provider_not_found`` (an update that kept the stored credential, for a lane with no
    stored credential).
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fetch_all(cursor: Any, query: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    """Execute a query and return every row as a plain dict."""
    cursor.execute(query, params)
    return [dict(row) for row in (cursor.fetchall() or [])]


def _fetch_one(cursor: Any, query: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """Execute a query and return the first row as a plain dict, or None."""
    cursor.execute(query, params)
    row = cursor.fetchone()
    return None if row is None else dict(row)


def get_provider(
    db: _DbLike, *, tenant_id: str, environment_id: str
) -> Optional[Dict[str, Any]]:
    """Load a lane's CDN provider, credential columns included.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant; another tenant's row reads as None.
        environment_id: The lane.

    Returns:
        The provider row, or None when the lane has no CDN.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT *
              FROM apiome.slate_cdn_providers
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
            """,
            (environment_id, tenant_id),
        )


def save_provider(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    environment_id: str,
    provider: str,
    target: str,
    auth_header_name: Optional[str],
    sealed_credential: Optional[Tuple[bytes, int]],
    purge_on_deploy: bool,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Attach or update a lane's CDN provider and mark the lane's edge attached.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the lane belongs to.
        environment_id: The lane.
        provider: ``cloudflare``, ``fastly`` or ``custom``.
        target: Zone id, service id or purge URL.
        auth_header_name: The custom endpoint's header, or None.
        sealed_credential: ``(ciphertext, key_version)`` for a new credential, or None to keep the
            stored one (only valid when a row exists).
        purge_on_deploy: Whether a deploy purges the CDN.
        actor_id: Acting user.
        actor_name: Display name of the actor.

    Returns:
        The written provider row.

    Raises:
        SlateCdnStoreError: ``provider_not_found`` when keeping a credential that does not exist.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            if sealed_credential is None:
                written = _fetch_one(
                    cursor,
                    """
                    UPDATE apiome.slate_cdn_providers
                       SET provider = %s, target = %s, auth_header_name = %s,
                           purge_on_deploy = %s, updated_at = CURRENT_TIMESTAMP,
                           updated_by_actor_id = %s, updated_by_actor_name = %s
                     WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
                    RETURNING *
                    """,
                    (
                        provider,
                        target,
                        auth_header_name,
                        purge_on_deploy,
                        actor_id,
                        actor_name,
                        environment_id,
                        tenant_id,
                    ),
                )
                if written is None:
                    raise SlateCdnStoreError(
                        "provider_not_found",
                        f"Environment {environment_id} has no stored CDN credential to keep.",
                    )
                created = False
            else:
                ciphertext, key_version = sealed_credential
                written = _fetch_one(
                    cursor,
                    """
                    INSERT INTO apiome.slate_cdn_providers
                        (tenant_id, site_id, environment_id, provider, target, auth_header_name,
                         credential_ciphertext, credential_key_version, purge_on_deploy,
                         updated_by_actor_id, updated_by_actor_name)
                    VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (environment_id) DO UPDATE
                       SET provider = EXCLUDED.provider,
                           target = EXCLUDED.target,
                           auth_header_name = EXCLUDED.auth_header_name,
                           credential_ciphertext = EXCLUDED.credential_ciphertext,
                           credential_key_version = EXCLUDED.credential_key_version,
                           purge_on_deploy = EXCLUDED.purge_on_deploy,
                           updated_at = CURRENT_TIMESTAMP,
                           updated_by_actor_id = EXCLUDED.updated_by_actor_id,
                           updated_by_actor_name = EXCLUDED.updated_by_actor_name
                     WHERE apiome.slate_cdn_providers.tenant_id = EXCLUDED.tenant_id
                    RETURNING *, (xmax = 0) AS inserted
                    """,
                    (
                        tenant_id,
                        site_id,
                        environment_id,
                        provider,
                        target,
                        auth_header_name,
                        ciphertext,
                        key_version,
                        purge_on_deploy,
                        actor_id,
                        actor_name,
                    ),
                )
                if written is None:
                    # Only reachable if the lane belongs to another tenant, which the route has
                    # already ruled out; refuse rather than mark an edge on a row we did not write.
                    raise SlateCdnStoreError(
                        "provider_not_found", f"Environment {environment_id} is not writable."
                    )
                created = bool(written.pop("inserted", False))

            _set_edge(
                cursor,
                tenant_id=tenant_id,
                site_id=site_id,
                environment_id=environment_id,
                provider=provider,
                actor_id=actor_id,
                actor_name=actor_name,
            )
            _audit(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor_id=actor_id,
                actor_name=actor_name,
                summary=f"CDN provider {'attached' if created else 'updated'}: {provider}",
                detail=(
                    f"Target {target}; purge on deploy {'on' if purge_on_deploy else 'off'}; "
                    + ("credential replaced." if sealed_credential else "credential kept.")
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def delete_provider(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
) -> bool:
    """Detach a lane's CDN provider, destroying its sealed credential, and detach the edge.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        actor_id: Acting user.
        actor_name: Display name of the actor.

    Returns:
        True when a provider was removed; False when the lane had none.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            removed = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_cdn_providers
                 WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING provider
                """,
                (environment_id, tenant_id),
            )
            if removed is None:
                conn.rollback()
                return False
            cursor.execute(
                """
                UPDATE apiome.slate_cache_policies
                   SET edge_attached = FALSE, edge_provider = NULL,
                       updated_at = CURRENT_TIMESTAMP,
                       updated_by_actor_id = %s, updated_by_actor_name = %s
                 WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (actor_id, actor_name, environment_id, tenant_id),
            )
            _audit(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor_id=actor_id,
                actor_name=actor_name,
                summary=f"CDN provider detached: {removed['provider']}",
                detail="The stored credential was deleted. Purges are recorded, not dispatched.",
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def _set_edge(
    cursor: Any,
    *,
    tenant_id: str,
    site_id: str,
    environment_id: str,
    provider: str,
    actor_id: Optional[str],
    actor_name: str,
) -> None:
    """Mark the lane's cache policy as fronted by ``provider``, creating the policy if needed.

    The policy version is deliberately not bumped: attaching a CDN changes where purges go, not
    the rules, and bumping it would make an operator mid-edit on the Rules tab lose their write.
    """
    cursor.execute(
        """
        INSERT INTO apiome.slate_cache_policies
            (tenant_id, site_id, environment_id, preset, edge_attached, edge_provider,
             updated_by_actor_id, updated_by_actor_name)
        VALUES (%s::uuid, %s::uuid, %s::uuid, 'standard', TRUE, %s, %s, %s)
        ON CONFLICT (environment_id) DO UPDATE
           SET edge_attached = TRUE,
               edge_provider = EXCLUDED.edge_provider,
               updated_at = CURRENT_TIMESTAMP,
               updated_by_actor_id = EXCLUDED.updated_by_actor_id,
               updated_by_actor_name = EXCLUDED.updated_by_actor_name
        """,
        (tenant_id, site_id, environment_id, provider, actor_id, actor_name),
    )


def _audit(
    cursor: Any,
    *,
    tenant_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
    summary: str,
    detail: str,
) -> None:
    """Append a ``cdn`` entry to the lane's cache audit, inside the caller's transaction."""
    cursor.execute(
        """
        INSERT INTO apiome.slate_cache_audit
            (tenant_id, environment_id, actor_id, actor_name, actor_kind, subject_kind,
             subject_id, summary, detail)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, 'cdn', NULL, %s, %s)
        """,
        (
            tenant_id,
            environment_id,
            actor_id,
            actor_name,
            "user" if actor_id else "automation",
            summary,
            detail,
        ),
    )


def verified_hosts(db: _DbLike, *, tenant_id: str, environment_id: str) -> List[str]:
    """List the lane's hosts whose ownership is verified — the URLs a CDN can be serving.

    Args:
        db: Database handle.
        tenant_id: Caller's tenant.
        environment_id: The lane.

    Returns:
        Hostnames, canonical first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        rows = _fetch_all(
            cursor,
            """
            SELECT host
              FROM apiome.slate_domains
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
               AND verification_status = 'verified'
             ORDER BY is_primary DESC, host
            """,
            (environment_id, tenant_id),
        )
    return [str(row["host"]) for row in rows]


def record_dispatch(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    release_id: Optional[str],
    cache_purge_id: Optional[str],
    trigger: str,
    provider: str,
    mode: str,
    url_count: int,
    sample_urls: Sequence[str],
    status: str,
    http_status: Optional[int],
    error_code: Optional[str],
    error_message: Optional[str],
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Append one dispatch to the lane's CDN purge log.

    Args:
        db: Database handle.
        tenant_id: Owning tenant.
        environment_id: The lane.
        release_id: Release the purge was for, when there is one.
        cache_purge_id: The cache-plane purge record, for a manual purge.
        trigger: ``deploy`` or ``manual``.
        provider: The provider it was sent to.
        mode: ``urls`` or ``purge-all``.
        url_count: URLs in scope.
        sample_urls: Bounded sample of them.
        status: ``succeeded``, ``failed`` or ``skipped``.
        http_status: The provider's last HTTP status, when it answered.
        error_code: Why it failed or was skipped; None on success.
        error_message: The redacted explanation.
        actor_id: Acting user.
        actor_name: Display name of the actor.

    Returns:
        The written row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_cdn_purge_dispatches
                    (tenant_id, environment_id, release_id, cache_purge_id, trigger, provider,
                     mode, url_count, sample_urls, status, http_status, error_code,
                     error_message, actor_id, actor_name)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    release_id,
                    cache_purge_id,
                    trigger,
                    provider,
                    mode,
                    url_count,
                    list(sample_urls),
                    status,
                    http_status,
                    error_code,
                    error_message,
                    actor_id,
                    actor_name,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def list_dispatches(
    db: _DbLike, *, tenant_id: str, environment_id: str, limit: int = 20
) -> List[Dict[str, Any]]:
    """Load a lane's CDN purge log, most recent first.

    Args:
        db: Database handle.
        tenant_id: Caller's tenant.
        environment_id: The lane.
        limit: How many rows.

    Returns:
        Dispatch rows.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_cdn_purge_dispatches
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY dispatched_at DESC
             LIMIT %s
            """,
            (environment_id, tenant_id, limit),
        )
