"""Persistence for the git-triggered preview control plane — APX-3.3 (private-suite#2458).

Reads and writes the V191 tables, following the :mod:`app.slate_deployment_store` precedent: a
minimal ``_DbLike`` protocol rather than the concrete ``Database`` singleton, so the whole
surface can be exercised against a fake connection. The pure decisions (signature, digest, URL
derivation, changed-page mapping, alias-advance gate) live in :mod:`app.slate_git_preview`; this
module is the transactions that apply them.

Two guarantees are structural here:

* **One preview per source digest.** :func:`ingest_preview_event` selects an existing build for
  the ``(connection, source_digest)`` pair and short-circuits when it finds one, and its insert
  carries ``ON CONFLICT (connection_id, source_digest) DO NOTHING`` so a concurrent redelivery
  cannot win a second row. Either way the caller learns whether the preview was created or
  already existed, and the ephemeral preview lane is created only for a genuinely new preview.

* **The branch alias advances only through the checks path.** :func:`record_checks` is the only
  function that moves ``slate_branch_aliases.current_build_id``, and it does so only when
  :func:`app.slate_git_preview.evaluate_alias_advance` allows it. Ingestion never advances an
  alias — a freshly-received commit has not been reviewed yet.

The webhook secret and repository token are sealed before they are written
(:func:`app.push_webhook_crypto.encrypt_signing_secret`,
:func:`app.mcp_credential_crypto.seal_credential_payload`) and never projected into a public
read. :func:`find_connections_by_repo` is the one function that returns the encrypted secret,
and only so the receiver can verify a signature with it in memory.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from .mcp_credential_crypto import (
    credential_encryption_configured,
    seal_credential_payload,
)
from .push_webhook_crypto import encrypt_signing_secret
from .slate_git_preview import (
    ParsedGitEvent,
    compute_source_digest,
    derive_branch_alias_url,
    derive_immutable_url,
    evaluate_alias_advance,
    map_changed_files,
)

__all__ = [
    "SlatePreviewStoreError",
    "upsert_connection",
    "get_connection",
    "list_connections",
    "find_connections_by_repo",
    "ingest_preview_event",
    "get_preview",
    "list_previews",
    "record_checks",
    "record_provider_status",
    "retry_build",
    "reap_expired_previews",
]


class _DbLike(Protocol):
    """Minimal database surface used by this module."""

    def connect(self) -> Any: ...


class SlatePreviewStoreError(Exception):
    """A control-plane row was missing or an operation was refused.

    Carries a machine-readable ``code`` so the REST layer maps it to a status without
    string-matching. Codes: ``site_not_found``, ``connection_not_found``,
    ``preview_not_found``.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# ─── Small helpers (mirroring slate_deployment_store) ────────────────────────


def _as_dict(row: Any) -> Optional[Dict[str, Any]]:
    return None if row is None else dict(row)


def _fetch_all(cursor: Any, query: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    cursor.execute(query, params)
    return [dict(row) for row in (cursor.fetchall() or [])]


def _fetch_one(cursor: Any, query: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    cursor.execute(query, params)
    return _as_dict(cursor.fetchone())


def _jsonb(value: Any) -> Optional[str]:
    """Serialise a value for a JSONB column, or None for SQL NULL.

    psycopg2 has no default adapter from ``dict`` to JSONB, so — like the deployment store —
    values destined for a JSONB column are passed as a JSON string, which JSONB accepts. ``None``
    is passed through as SQL NULL rather than the JSON ``null`` literal.
    """
    return None if value is None else json.dumps(value, default=str)


def _now() -> datetime:
    """Current UTC time, isolated so tests can patch one place."""
    return datetime.now(timezone.utc)


#: Columns projected into a public connection read. The encrypted secret and token are
#: deliberately absent — a client is told *whether* they are set, never their value.
_CONNECTION_PUBLIC_SELECT = """
    id, tenant_id, site_id, provider, repo_owner, repo_name, repo_full_name,
    default_branch, preview_host, created_at, updated_at,
    (webhook_secret_enc IS NOT NULL) AS has_webhook_secret,
    (token_ciphertext IS NOT NULL) AS has_token
"""


# ─── Connections ─────────────────────────────────────────────────────────────


def upsert_connection(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    repo_owner: str,
    repo_name: str,
    default_branch: str,
    preview_host: str,
    webhook_secret: Optional[str],
    token: Optional[str],
    provider: str = "github",
) -> Dict[str, Any]:
    """Create or update a git provider connection, sealing its secret and token at rest.

    The webhook secret is Fernet-encrypted and the repository token is envelope-encrypted before
    either is written; a secret or token supplied as ``None`` leaves the stored column unchanged
    on an update (so re-registering a repository without re-entering the secret keeps it). The
    returned row is the public projection — it never contains the sealed secret or token.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the connection builds previews for.
        repo_owner: Repository owner (org or user).
        repo_name: Repository name.
        default_branch: The repository's default branch.
        preview_host: Base host the preview URLs are derived from.
        webhook_secret: The webhook signing secret in plaintext, or ``None`` to keep the stored
            one.
        token: The repository token in plaintext, or ``None`` to keep the stored one.
        provider: Git provider; only ``github`` today.

    Returns:
        The public connection projection.
    """
    repo_full_name = f"{repo_owner}/{repo_name}".lower()
    secret_enc = encrypt_signing_secret(webhook_secret) if webhook_secret else None

    token_ciphertext: Optional[bytes] = None
    token_key_version: Optional[int] = None
    if token and credential_encryption_configured():
        token_ciphertext, token_key_version = seal_credential_payload({"token": token})

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            # COALESCE keeps the stored secret/token when the caller sends None, so a connection
            # can be updated without re-entering credentials.
            row = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_git_connections
                    (tenant_id, site_id, provider, repo_owner, repo_name, repo_full_name,
                     default_branch, preview_host, webhook_secret_enc,
                     token_ciphertext, token_key_version)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, provider, repo_full_name) DO UPDATE SET
                    site_id           = EXCLUDED.site_id,
                    repo_owner        = EXCLUDED.repo_owner,
                    repo_name         = EXCLUDED.repo_name,
                    default_branch    = EXCLUDED.default_branch,
                    preview_host      = EXCLUDED.preview_host,
                    webhook_secret_enc = COALESCE(EXCLUDED.webhook_secret_enc,
                                                  apiome.slate_git_connections.webhook_secret_enc),
                    token_ciphertext   = COALESCE(EXCLUDED.token_ciphertext,
                                                  apiome.slate_git_connections.token_ciphertext),
                    token_key_version  = COALESCE(EXCLUDED.token_key_version,
                                                  apiome.slate_git_connections.token_key_version),
                    updated_at        = CURRENT_TIMESTAMP
                RETURNING """
                + _CONNECTION_PUBLIC_SELECT,
                (
                    tenant_id,
                    site_id,
                    provider,
                    repo_owner,
                    repo_name,
                    repo_full_name,
                    default_branch,
                    preview_host,
                    secret_enc,
                    token_ciphertext,
                    token_key_version,
                ),
            )
        conn.commit()
        return row or {}
    except Exception:
        conn.rollback()
        raise


def get_connection(
    db: _DbLike, *, tenant_id: str, connection_id: str
) -> Optional[Dict[str, Any]]:
    """Load one connection (public projection), scoped to the tenant.

    A scope miss returns ``None`` — the route turns that into a 404, so a cross-tenant probe
    cannot confirm a connection exists.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            "SELECT " + _CONNECTION_PUBLIC_SELECT + """
              FROM apiome.slate_git_connections
             WHERE id = %s::uuid AND tenant_id = %s::uuid
            """,
            (connection_id, tenant_id),
        )


def list_connections(db: _DbLike, *, tenant_id: str) -> List[Dict[str, Any]]:
    """List a tenant's connections (public projection), newest first."""
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            "SELECT " + _CONNECTION_PUBLIC_SELECT + """
              FROM apiome.slate_git_connections
             WHERE tenant_id = %s::uuid
             ORDER BY created_at DESC
            """,
            (tenant_id,),
        )


def find_connections_by_repo(
    db: _DbLike, *, provider: str, repo_full_name: str
) -> List[Dict[str, Any]]:
    """Find every connection for a repository, **including** the encrypted webhook secret.

    The webhook receiver has only the payload's repository, not a tenant, so it resolves all
    connections for that repository and verifies the signature against each secret. This is the
    single function that returns ``webhook_secret_enc``; the caller decrypts it in memory to
    verify and never returns it to a client.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT id, tenant_id, site_id, provider, repo_owner, repo_name, repo_full_name,
                   default_branch, preview_host, webhook_secret_enc
              FROM apiome.slate_git_connections
             WHERE provider = %s AND repo_full_name = %s
             ORDER BY created_at
            """,
            (provider, repo_full_name.lower()),
        )


# ─── Preview ingestion ───────────────────────────────────────────────────────


def _site_slug(cursor: Any, site_id: str) -> str:
    row = _fetch_one(
        cursor,
        "SELECT slug FROM apiome.slate_sites WHERE id = %s::uuid",
        (site_id,),
    )
    if not row:
        raise SlatePreviewStoreError("site_not_found", "Site not found for connection.")
    return str(row["slug"])


def _insert_preview_audit(
    cursor: Any,
    *,
    tenant_id: str,
    preview_build_id: str,
    actor_name: str,
    actor_kind: str,
    summary: str,
    detail: Optional[str] = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO apiome.slate_preview_audit
            (tenant_id, preview_build_id, actor_name, actor_kind, summary, detail)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
        """,
        (tenant_id, preview_build_id, actor_name, actor_kind, summary, detail),
    )


def _insert_provider_status(
    cursor: Any,
    *,
    tenant_id: str,
    preview_build_id: str,
    state: str,
    target_url: str,
    changed_page_count: int,
    description: str = "",
) -> None:
    cursor.execute(
        """
        INSERT INTO apiome.slate_provider_status_deliveries
            (tenant_id, preview_build_id, state, target_url, changed_page_count, description)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
        """,
        (tenant_id, preview_build_id, state, target_url, changed_page_count, description),
    )


def ingest_preview_event(
    db: _DbLike,
    connection: Dict[str, Any],
    event: ParsedGitEvent,
    *,
    delivery_id: Optional[str],
    ttl_hours: int,
    docs_prefix: str = "docs",
    access_policy: str = "tenant",
) -> Tuple[Dict[str, Any], bool]:
    """Turn a verified push event into a preview, exactly once (acceptance criterion 1).

    If a preview already exists for this ``(connection, source_digest)`` pair, it is returned
    unchanged and a redelivery audit entry is appended — a webhook GitHub sent twice does not
    fan out into two previews. Otherwise, in one transaction, an ephemeral preview lane is
    created (robots-excluded, with the configured TTL), the immutable preview row is written, its
    changed pages are recorded with deep links into the immutable URL, and a first audit entry
    and a ``pending`` provider status are appended. The branch alias is **not** advanced here —
    a freshly-received commit has not passed any checks yet.

    Args:
        db: Database handle exposing ``connect()``.
        connection: The resolved connection row (must carry ``id``, ``tenant_id``, ``site_id``,
            ``preview_host``).
        event: The parsed push event.
        delivery_id: The provider's delivery identifier, for the audit trail.
        ttl_hours: Lifetime of the ephemeral preview lane, in hours.
        docs_prefix: Repository directory the documentation lives under.
        access_policy: Preview protection policy for the lane.

    Returns:
        ``(preview_build_row, created)`` — ``created`` is ``False`` for an idempotent redelivery.
    """
    tenant_id = str(connection["tenant_id"])
    connection_id = str(connection["id"])
    site_id = str(connection["site_id"])
    preview_host = str(connection["preview_host"])
    source_digest = compute_source_digest(event.repo_full_name, event.commit)

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            existing = _fetch_one(
                cursor,
                """
                SELECT * FROM apiome.slate_preview_builds
                 WHERE connection_id = %s::uuid AND source_digest = %s
                """,
                (connection_id, source_digest),
            )
            if existing:
                _insert_preview_audit(
                    cursor,
                    tenant_id=tenant_id,
                    preview_build_id=str(existing["id"]),
                    actor_name="git-provider",
                    actor_kind="automation",
                    summary="Redelivered event for an existing preview (no-op)",
                    detail=f"deliveryId={delivery_id}",
                )
                conn.commit()
                return existing, False

            slug = _site_slug(cursor, site_id)
            immutable_url = derive_immutable_url(preview_host, slug, event.commit)
            expires_at = _now() + timedelta(hours=ttl_hours)

            # The ephemeral preview lane, inline in this transaction so it is never orphaned by a
            # lost idempotency race. Reuses slate_environments for expiry/access/robots.
            lane_name = f"preview-{event.branch}-{event.commit[:12]}".lower()[:255]
            lane = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_environments
                    (tenant_id, site_id, kind, name, robots_excluded, access_policy, expires_at)
                VALUES (%s::uuid, %s::uuid, 'preview', %s, TRUE, %s, %s)
                ON CONFLICT (site_id, name) DO UPDATE SET expires_at = EXCLUDED.expires_at
                RETURNING id
                """,
                (tenant_id, site_id, lane_name, access_policy, expires_at),
            )
            environment_id = str(lane["id"]) if lane else None

            build = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_preview_builds
                    (tenant_id, connection_id, site_id, environment_id, delivery_id,
                     source_commit, source_ref, source_message, source_digest,
                     immutable_url, access_policy, robots_excluded, expires_at)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                        %s, %s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (connection_id, source_digest) DO NOTHING
                RETURNING *
                """,
                (
                    tenant_id,
                    connection_id,
                    site_id,
                    environment_id,
                    delivery_id,
                    event.commit,
                    event.branch,
                    event.message,
                    source_digest,
                    immutable_url,
                    access_policy,
                    expires_at,
                ),
            )
            if build is None:
                # A concurrent delivery won the race between our SELECT and INSERT. Roll back
                # (dropping the lane we just made) and return the row it created.
                conn.rollback()
                with conn.cursor() as cursor2:
                    raced = _fetch_one(
                        cursor2,
                        """
                        SELECT * FROM apiome.slate_preview_builds
                         WHERE connection_id = %s::uuid AND source_digest = %s
                        """,
                        (connection_id, source_digest),
                    )
                if raced:
                    return raced, False
                raise SlatePreviewStoreError(
                    "preview_not_found", "Preview vanished during a concurrent ingestion."
                )

            build_id = str(build["id"])
            for page in map_changed_files(event, docs_prefix=docs_prefix):
                cursor.execute(
                    """
                    INSERT INTO apiome.slate_preview_changed_pages
                        (preview_build_id, route, kind, link_url, source_path)
                    VALUES (%s::uuid, %s, %s, %s, %s)
                    ON CONFLICT (preview_build_id, route) DO NOTHING
                    """,
                    (
                        build_id,
                        page.route,
                        page.kind,
                        immutable_url + page.route,
                        page.source_path,
                    ),
                )

            _insert_preview_audit(
                cursor,
                tenant_id=tenant_id,
                preview_build_id=build_id,
                actor_name="git-provider",
                actor_kind="automation",
                summary=f"Preview created from {event.branch}@{event.commit[:12]}",
                detail=f"deliveryId={delivery_id}; digest={source_digest}",
            )
            _insert_provider_status(
                cursor,
                tenant_id=tenant_id,
                preview_build_id=build_id,
                state="pending",
                target_url=immutable_url,
                changed_page_count=0,
                description="Preview queued; awaiting checks.",
            )
        conn.commit()
        return build, True
    except Exception:
        conn.rollback()
        raise


# ─── Preview reads ───────────────────────────────────────────────────────────


def _changed_pages(cursor: Any, build_id: str) -> List[Dict[str, Any]]:
    return _fetch_all(
        cursor,
        """
        SELECT route, kind, link_url, path_id, source_path
          FROM apiome.slate_preview_changed_pages
         WHERE preview_build_id = %s::uuid
         ORDER BY route
        """,
        (build_id,),
    )


def _current_alias_url(cursor: Any, connection_id: str, branch: str, build_id: str) -> Optional[str]:
    """Return the branch alias URL when it currently points at this build, else None."""
    row = _fetch_one(
        cursor,
        """
        SELECT alias_url FROM apiome.slate_branch_aliases
         WHERE connection_id = %s::uuid AND branch = %s AND current_build_id = %s::uuid
        """,
        (connection_id, branch, build_id),
    )
    return str(row["alias_url"]) if row else None


def get_preview(
    db: _DbLike, *, tenant_id: str, build_id: str
) -> Optional[Dict[str, Any]]:
    """Load one preview with its changed pages and alias pointer, scoped to the tenant."""
    conn = db.connect()
    with conn.cursor() as cursor:
        build = _fetch_one(
            cursor,
            """
            SELECT * FROM apiome.slate_preview_builds
             WHERE id = %s::uuid AND tenant_id = %s::uuid
            """,
            (build_id, tenant_id),
        )
        if not build:
            return None
        build["changed_pages"] = _changed_pages(cursor, build_id)
        build["alias_url"] = _current_alias_url(
            cursor, str(build["connection_id"]), str(build["source_ref"]), build_id
        )
        return build


def list_previews(
    db: _DbLike, *, tenant_id: str, connection_id: Optional[str] = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """List a tenant's previews, newest first, optionally scoped to one connection."""
    conn = db.connect()
    with conn.cursor() as cursor:
        rows = _fetch_all(
            cursor,
            """
            SELECT * FROM apiome.slate_preview_builds
             WHERE tenant_id = %s::uuid
               AND (%s::uuid IS NULL OR connection_id = %s::uuid)
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (tenant_id, connection_id, connection_id, limit),
        )
        for build in rows:
            build["changed_pages"] = _changed_pages(cursor, str(build["id"]))
            build["alias_url"] = _current_alias_url(
                cursor, str(build["connection_id"]), str(build["source_ref"]), str(build["id"])
            )
        return rows


# ─── Checks and alias advance ────────────────────────────────────────────────


def record_checks(
    db: _DbLike,
    *,
    tenant_id: str,
    build_id: str,
    passed: bool,
    failure_evidence: Optional[Dict[str, Any]] = None,
    actor_name: str = "checks",
) -> Dict[str, Any]:
    """Record a check outcome and, on success, advance the branch alias to this build.

    On a pass the build's ``checks_state`` becomes ``passed`` and the branch alias is advanced
    (its ``current_build_id`` repointed, ``alias_url`` refreshed and ``routing_version`` bumped)
    — this is the only path that moves an alias, so "the alias advances only after successful
    checks" holds. On a failure the build's ``checks_state`` becomes ``failed`` and its
    ``failure_evidence`` is stored; the alias is left where it is. Either way an audit entry and
    a provider status are appended.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        build_id: The preview to record a check outcome for.
        passed: Whether the checks passed.
        failure_evidence: Evidence to store and surface when the checks failed.
        actor_name: Who recorded the outcome.

    Returns:
        The updated preview row, with ``changed_pages`` and the current ``alias_url``.

    Raises:
        SlatePreviewStoreError: ``preview_not_found`` when no such preview exists for the tenant.
    """
    new_state = "passed" if passed else "failed"
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            build = _fetch_one(
                cursor,
                """
                SELECT b.*, c.preview_host, c.repo_full_name, s.slug AS site_slug
                  FROM apiome.slate_preview_builds b
                  JOIN apiome.slate_git_connections c ON c.id = b.connection_id
                  JOIN apiome.slate_sites s ON s.id = b.site_id
                 WHERE b.id = %s::uuid AND b.tenant_id = %s::uuid
                """,
                (build_id, tenant_id),
            )
            if not build:
                raise SlatePreviewStoreError(
                    "preview_not_found", "Preview not found."
                )

            cursor.execute(
                """
                UPDATE apiome.slate_preview_builds
                   SET checks_state = %s,
                       failure_evidence = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s::uuid
                """,
                (new_state, _jsonb(failure_evidence), build_id),
            )

            decision = evaluate_alias_advance(
                checks_state=new_state,
                status=str(build["status"]),
                cleaned_up=build.get("cleaned_up_at") is not None,
            )

            changed_pages = _changed_pages(cursor, build_id)
            alias_url = derive_branch_alias_url(
                str(build["preview_host"]), str(build["site_slug"]), str(build["source_ref"])
            )

            if decision.advance:
                # Advance the moving alias: create it or repoint it, bumping the concurrency
                # token. UNIQUE (connection_id, branch) keeps one alias per branch.
                cursor.execute(
                    """
                    INSERT INTO apiome.slate_branch_aliases
                        (tenant_id, connection_id, branch, current_build_id, alias_url,
                         routing_version)
                    VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s, 1)
                    ON CONFLICT (connection_id, branch) DO UPDATE SET
                        current_build_id = EXCLUDED.current_build_id,
                        alias_url        = EXCLUDED.alias_url,
                        routing_version  = apiome.slate_branch_aliases.routing_version + 1,
                        updated_at       = CURRENT_TIMESTAMP
                    """,
                    (
                        tenant_id,
                        str(build["connection_id"]),
                        str(build["source_ref"]),
                        build_id,
                        alias_url,
                    ),
                )
                _insert_preview_audit(
                    cursor,
                    tenant_id=tenant_id,
                    preview_build_id=build_id,
                    actor_name=actor_name,
                    actor_kind="automation",
                    summary="Checks passed; branch alias advanced",
                    detail=f"alias={alias_url}",
                )
                _insert_provider_status(
                    cursor,
                    tenant_id=tenant_id,
                    preview_build_id=build_id,
                    state="success",
                    target_url=str(build["immutable_url"]),
                    changed_page_count=len(changed_pages),
                    description="Preview ready; changed pages linked.",
                )
            else:
                _insert_preview_audit(
                    cursor,
                    tenant_id=tenant_id,
                    preview_build_id=build_id,
                    actor_name=actor_name,
                    actor_kind="automation",
                    summary=f"Checks recorded ({new_state}); alias held",
                    detail=decision.reason,
                )
                _insert_provider_status(
                    cursor,
                    tenant_id=tenant_id,
                    preview_build_id=build_id,
                    state="failure" if not passed else "pending",
                    target_url=str(build["immutable_url"]),
                    changed_page_count=len(changed_pages),
                    description=decision.reason or "",
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    updated = get_preview(db, tenant_id=tenant_id, build_id=build_id)
    if updated is None:
        raise SlatePreviewStoreError("preview_not_found", "Preview not found after update.")
    return updated


def record_provider_status(
    db: _DbLike,
    *,
    tenant_id: str,
    build_id: str,
    state: str,
    target_url: str,
    changed_page_count: int = 0,
    description: str = "",
) -> None:
    """Append a provider status delivery record. Never dispatches — see the V191 boundary."""
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            _insert_provider_status(
                cursor,
                tenant_id=tenant_id,
                preview_build_id=build_id,
                state=state,
                target_url=target_url,
                changed_page_count=changed_page_count,
                description=description,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def retry_build(
    db: _DbLike, *, tenant_id: str, build_id: str, actor_name: str
) -> Dict[str, Any]:
    """Request a build retry: bump the retry counter and audit it (acceptance criterion 4).

    There is no build worker to hand the retry to (#3419), so this records the request and
    resets the checks to pending; the honest ``build_dispatched = FALSE`` boundary is unchanged.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            build = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_preview_builds
                   SET retry_count = retry_count + 1,
                       checks_state = 'pending',
                       failure_evidence = NULL,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (build_id, tenant_id),
            )
            if not build:
                raise SlatePreviewStoreError("preview_not_found", "Preview not found.")
            _insert_preview_audit(
                cursor,
                tenant_id=tenant_id,
                preview_build_id=build_id,
                actor_name=actor_name,
                actor_kind="user",
                summary=f"Build retry requested (attempt {int(build['retry_count'])})",
                detail=None,
            )
        conn.commit()
        return build
    except Exception:
        conn.rollback()
        raise


def reap_expired_previews(
    db: _DbLike, *, tenant_id: str, now: Optional[datetime] = None
) -> int:
    """Mark expired previews cleaned up and audit each (acceptance criterion 4).

    Selects previews whose lane expiry has passed and that are not already cleaned up, marks
    them ``expired`` with a ``cleaned_up_at`` stamp, and appends a cleanup audit entry per
    preview. Returns the number reaped. The underlying lane rows are left to the existing
    ephemeral-preview expiry sweep; this reaps the preview record and its audit trail.
    """
    at = now or _now()
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            due = _fetch_all(
                cursor,
                """
                SELECT id FROM apiome.slate_preview_builds
                 WHERE tenant_id = %s::uuid
                   AND cleaned_up_at IS NULL
                   AND expires_at IS NOT NULL
                   AND expires_at <= %s
                """,
                (tenant_id, at),
            )
            for row in due:
                build_id = str(row["id"])
                cursor.execute(
                    """
                    UPDATE apiome.slate_preview_builds
                       SET status = 'expired',
                           cleaned_up_at = %s,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = %s::uuid
                    """,
                    (at, build_id),
                )
                _insert_preview_audit(
                    cursor,
                    tenant_id=tenant_id,
                    preview_build_id=build_id,
                    actor_name="retention",
                    actor_kind="automation",
                    summary="Preview expired and cleaned up",
                    detail=None,
                )
        conn.commit()
        return len(due)
    except Exception:
        conn.rollback()
        raise
