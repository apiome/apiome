"""Persistence for the Slate cache control plane — UXE-3.1 (private-suite#2473).

Reads and writes the V187 tables. Follows :mod:`app.slate_deployment_store` exactly: a small
``_DbLike`` protocol rather than a dependency on the concrete ``Database`` singleton, so the
whole surface can be exercised against a fake connection without a live Postgres.

**Concurrency.** Every write that changes policy goes through :func:`bump_policy_version`,
whose conditional UPDATE mirrors the routing pointer's:

    UPDATE apiome.slate_cache_policies
       SET policy_version = policy_version + 1
     WHERE environment_id = %s AND policy_version = %s

The second of two simultaneous edits matches zero rows and is refused as
``policy-version-conflict`` rather than silently overwriting the first. During an incident two
operators editing the same lane is the normal case, not the exotic one, so there is deliberately
no last-write-wins path.

**Scope resolution is SQL; scope estimation is not.** These functions fetch the candidate route
inventory for a lane; :func:`app.slate_cache.plan_purge_scope` narrows and counts it. Prefix
narrowing in particular is done in Python rather than with SQL ``LIKE``, because an unescaped
``_`` in a stored route is a single-character wildcard — during an incident, the difference
between purging one section and purging the site.

**Nothing here evicts anything.** ``deploy/`` is a single Caddyfile with no CDN behind it.
:func:`record_purge` writes evidence: the scope, the estimate, the basis of that estimate, the
actor and the reason. ``edge_attached`` is snapshotted onto the row so that attaching a delivery
tier later cannot make historical records look like flushes, and V187's
``outcome <> 'dispatched' OR edge_attached`` CHECK makes that a database guarantee rather than a
convention this module is trusted to keep.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

__all__ = [
    "SlateCachePolicyConflictError",
    "SlateCacheStoreError",
    "append_audit",
    "bump_policy_version",
    "delete_rule",
    "ensure_policy",
    "get_policy",
    "list_audit",
    "list_purges",
    "list_rules",
    "record_purge",
    "record_trace",
    "routes_for_host",
    "routes_for_release",
    "rules_for_tag",
    "set_preset",
    "upsert_rule",
]


class _DbLike(Protocol):
    """Minimal database surface used by this module."""

    def connect(self) -> Any: ...


class SlateCacheStoreError(Exception):
    """A cache control-plane row was missing or malformed.

    Carries a machine-readable ``code`` so the REST layer maps it to a status without
    string-matching. Codes: ``policy_not_found``, ``rule_not_found``.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SlateCachePolicyConflictError(Exception):
    """Another operator changed the lane's cache policy first.

    Raised when the conditional UPDATE matched zero rows. The REST layer turns this into the
    ``policy-version-conflict`` refusal, whose sentence tells the operator to re-read.
    """

    def __init__(self, environment_id: str, expected: int, actual: Optional[int]) -> None:
        self.environment_id = environment_id
        self.expected_policy_version = expected
        self.actual_policy_version = actual
        super().__init__(
            f"Environment {environment_id} cache policy changed while this edit was being "
            f"prepared (expected policy_version {expected}, found {actual})."
        )


def _as_dict(row: Any) -> Optional[Dict[str, Any]]:
    """Normalize a cursor row to a plain dict, preserving None."""
    return None if row is None else dict(row)


def _fetch_all(cursor: Any, query: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    """Execute a query and return every row as a plain dict."""
    cursor.execute(query, params)
    return [dict(row) for row in (cursor.fetchall() or [])]


def _fetch_one(cursor: Any, query: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """Execute a query and return the first row as a plain dict, or None."""
    cursor.execute(query, params)
    return _as_dict(cursor.fetchone())


def _json(value: Any) -> Any:
    """Return a JSON-serializable value; psycopg2 needs plain dict/list for JSONB."""
    return None if value is None else json.loads(json.dumps(value, default=str))


def _now() -> datetime:
    """Current UTC time, isolated so tests can patch one place."""
    return datetime.now(timezone.utc)


# ─── Policy ──────────────────────────────────────────────────────────────────


def get_policy(
    db: _DbLike, *, tenant_id: str, environment_id: str
) -> Optional[Dict[str, Any]]:
    """Load a lane's cache policy, scoped to its tenant.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant. A scope miss returns None so the REST layer can answer 404
            rather than confirming the lane exists to another tenant.
        environment_id: The lane.

    Returns:
        The policy row, or None when the lane has none yet or belongs to another tenant.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT *
              FROM apiome.slate_cache_policies
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
            """,
            (environment_id, tenant_id),
        )


def ensure_policy(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Return a lane's cache policy, creating the Standard default if it has none.

    A lane with no row is not a lane with no policy — it is a lane serving the safe default.
    Materializing that on first read keeps "what is this lane doing" answerable with one query
    and gives the optimistic-concurrency token something to count from.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the environment belongs to.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The existing or newly created policy row.
    """
    existing = get_policy(db, tenant_id=tenant_id, environment_id=environment_id)
    if existing is not None:
        return existing

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            created = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_cache_policies
                    (tenant_id, site_id, environment_id, preset, updated_by_actor_id,
                     updated_by_actor_name)
                VALUES (%s::uuid, %s::uuid, %s::uuid, 'standard', %s, %s)
                ON CONFLICT (environment_id) DO NOTHING
                RETURNING *
                """,
                (tenant_id, site_id, environment_id, actor_id, actor_name),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if created is not None:
        return created
    # A concurrent first read won the insert. Re-reading is correct rather than raising: both
    # callers wanted the same default and both should get it.
    policy = get_policy(db, tenant_id=tenant_id, environment_id=environment_id)
    if policy is None:
        raise SlateCacheStoreError(
            "policy_not_found", f"Cache policy for environment {environment_id} could not be read."
        )
    return policy


def bump_policy_version(
    cursor: Any, *, environment_id: str, expected_policy_version: int
) -> int:
    """Advance a lane's policy version, refusing a stale expectation.

    The conditional UPDATE is the concurrency control, mirroring
    ``slate_environments.routing_version``. Callers run this inside the same transaction as the
    write it guards, so a refused edit leaves nothing behind.

    Args:
        cursor: Open cursor inside the caller's transaction.
        environment_id: The lane.
        expected_policy_version: The version the caller read before preparing this edit.

    Returns:
        The new policy version.

    Raises:
        SlateCachePolicyConflictError: When the expectation was stale, i.e. someone else wrote
            first.
    """
    row = _fetch_one(
        cursor,
        """
        UPDATE apiome.slate_cache_policies
           SET policy_version = policy_version + 1,
               updated_at = CURRENT_TIMESTAMP
         WHERE environment_id = %s::uuid AND policy_version = %s
        RETURNING policy_version
        """,
        (environment_id, expected_policy_version),
    )
    if row is None:
        actual = _fetch_one(
            cursor,
            "SELECT policy_version FROM apiome.slate_cache_policies WHERE environment_id = %s::uuid",
            (environment_id,),
        )
        raise SlateCachePolicyConflictError(
            environment_id,
            expected_policy_version,
            None if actual is None else int(actual["policy_version"]),
        )
    return int(row["policy_version"])


def set_preset(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    preset: str,
    preset_expires_at: Optional[datetime],
    overrides: Optional[Mapping[str, Any]],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Change a lane's preset.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        preset: One of the four preset keys.
        preset_expires_at: When the preset reverts. Required by V187's CHECK for ``bypass``.
        overrides: Fields moved off the preset default.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The updated policy row.

    Raises:
        SlateCachePolicyConflictError: On a stale ``expected_policy_version``.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            updated = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_cache_policies
                   SET preset = %s,
                       preset_expires_at = %s,
                       preset_overrides = %s::jsonb,
                       updated_by_actor_id = %s,
                       updated_by_actor_name = %s
                 WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (
                    preset,
                    preset_expires_at,
                    json.dumps(_json(dict(overrides or {}))),
                    actor_id,
                    actor_name,
                    environment_id,
                    tenant_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if updated is None:
        raise SlateCacheStoreError(
            "policy_not_found", f"Cache policy for environment {environment_id} was not found."
        )
    return updated


# ─── Rules ───────────────────────────────────────────────────────────────────


def list_rules(db: _DbLike, *, tenant_id: str, environment_id: str) -> List[Dict[str, Any]]:
    """Load a lane's expert rules in precedence order, with their tags attached.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Rule rows ordered by ``ordinal``, each carrying a ``tags`` list.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        rules = _fetch_all(
            cursor,
            """
            SELECT r.*,
                   COALESCE(
                       ARRAY(
                           SELECT t.tag
                             FROM apiome.slate_cache_rule_tags t
                            WHERE t.rule_id = r.id
                            ORDER BY t.tag
                       ),
                       ARRAY[]::TEXT[]
                   ) AS tags
              FROM apiome.slate_cache_rules r
             WHERE r.environment_id = %s::uuid AND r.tenant_id = %s::uuid
             ORDER BY r.ordinal, r.id
            """,
            (environment_id, tenant_id),
        )
    return rules


def upsert_rule(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    rule_id: Optional[str],
    values: Mapping[str, Any],
    tags: Sequence[str],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str = "user",
) -> Dict[str, Any]:
    """Create or replace an expert rule, and its tags, in one transaction.

    Tags are replaced wholesale rather than diffed. A rule's tag set is small and is what purge
    scoping reads; a partial update that left a stale tag behind would silently widen a later
    purge-by-tag.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: Existing rule to replace, or None to create one.
        values: Column values, already validated by :mod:`app.slate_cache`.
        tags: The rule's complete tag set.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.

    Returns:
        The written rule row, with its tags attached.

    Raises:
        SlateCachePolicyConflictError: On a stale ``expected_policy_version``.
        SlateCacheStoreError: When ``rule_id`` names no rule on this lane.
    """
    columns = (
        "ordinal",
        "enabled",
        "label",
        "matcher_kind",
        "matcher_value",
        "matcher_methods",
        "matcher_hosts",
        "eligibility",
        "browser_ttl_seconds",
        "edge_ttl_seconds",
        "stale_while_revalidate_seconds",
        "stale_if_error_seconds",
        "cache_key_base",
        "vary_query_mode",
        "vary_query_keys",
        "vary_headers",
        "vary_cookies",
        "expires_at",
        "acknowledged_warnings",
    )
    payload = [values.get(column) for column in columns]

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )

            if rule_id:
                assignments = ", ".join(f"{column} = %s" for column in columns)
                written = _fetch_one(
                    cursor,
                    f"""
                    UPDATE apiome.slate_cache_rules
                       SET {assignments},
                           bypass_conditions = %s::jsonb,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                    RETURNING *
                    """,
                    (
                        *payload,
                        json.dumps(_json(list(values.get("bypass_conditions") or []))),
                        rule_id,
                        environment_id,
                        tenant_id,
                    ),
                )
                if written is None:
                    raise SlateCacheStoreError(
                        "rule_not_found", f"Cache rule {rule_id} was not found on this lane."
                    )
            else:
                placeholders = ", ".join(["%s"] * len(columns))
                written = _fetch_one(
                    cursor,
                    f"""
                    INSERT INTO apiome.slate_cache_rules
                        (tenant_id, environment_id, {", ".join(columns)}, bypass_conditions,
                         created_by_actor_id, created_by_actor_name, created_by_actor_kind)
                    VALUES (%s::uuid, %s::uuid, {placeholders}, %s::jsonb, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        tenant_id,
                        environment_id,
                        *payload,
                        json.dumps(_json(list(values.get("bypass_conditions") or []))),
                        actor_id,
                        actor_name,
                        actor_kind,
                    ),
                )
                if written is None:
                    raise SlateCacheStoreError(
                        "rule_not_found", "The cache rule could not be created."
                    )

            written_id = str(written["id"])
            cursor.execute(
                "DELETE FROM apiome.slate_cache_rule_tags WHERE rule_id = %s::uuid",
                (written_id,),
            )
            for tag in sorted(set(tags)):
                cursor.execute(
                    """
                    INSERT INTO apiome.slate_cache_rule_tags (rule_id, tag)
                    VALUES (%s::uuid, %s)
                    ON CONFLICT (rule_id, tag) DO NOTHING
                    """,
                    (written_id, tag),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    written["tags"] = sorted(set(tags))
    return written


def delete_rule(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    rule_id: str,
    expected_policy_version: int,
) -> bool:
    """Remove an expert rule.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: Rule to remove.
        expected_policy_version: The version the caller read.

    Returns:
        True when a rule was removed.

    Raises:
        SlateCachePolicyConflictError: On a stale ``expected_policy_version``.
        SlateCacheStoreError: When ``rule_id`` names no rule on this lane.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            removed = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_cache_rules
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING id
                """,
                (rule_id, environment_id, tenant_id),
            )
            if removed is None:
                raise SlateCacheStoreError(
                    "rule_not_found", f"Cache rule {rule_id} was not found on this lane."
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def rules_for_tag(
    db: _DbLike, *, tenant_id: str, environment_id: str, tag: str
) -> List[Dict[str, Any]]:
    """Load the enabled rules carrying a tag, for purge-by-tag scoping.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        tag: The tag to resolve.

    Returns:
        Rule rows in precedence order.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT r.*
              FROM apiome.slate_cache_rules r
              JOIN apiome.slate_cache_rule_tags t ON t.rule_id = r.id
             WHERE r.environment_id = %s::uuid
               AND r.tenant_id = %s::uuid
               AND r.enabled = TRUE
               AND t.tag = %s
             ORDER BY r.ordinal, r.id
            """,
            (environment_id, tenant_id, tag),
        )


# ─── Purge scope inputs ──────────────────────────────────────────────────────


def routes_for_release(db: _DbLike, *, release_id: str) -> List[str]:
    """Load the routes a release changed.

    This is what V186 already stores as "pages whose rendered output differs from the previous
    release", which is exactly the set a release purge needs to invalidate. It under-counts —
    unchanged pages are cached too — and the estimate says so rather than quietly rounding up.

    Args:
        db: Database handle exposing ``connect()``.
        release_id: The basis release.

    Returns:
        Route strings, deduplicated by the table's UNIQUE (release_id, route).
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        rows = _fetch_all(
            cursor,
            """
            SELECT route
              FROM apiome.slate_release_changed_pages
             WHERE release_id = %s::uuid
             ORDER BY route
            """,
            (release_id,),
        )
    return [str(row["route"]) for row in rows]


def routes_for_host(
    db: _DbLike, *, tenant_id: str, environment_id: str, host: str, release_id: Optional[str]
) -> List[str]:
    """Load the routes served under a host on this lane.

    The host is confirmed against ``slate_domains`` for this environment first. A host that is
    not on the lane yields nothing, so a cross-tenant probe learns the same thing it would from
    a lane with no matching pages: nothing.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        host: The hostname to scope to.
        release_id: The basis release, or None when the lane serves nothing.

    Returns:
        Route strings, or an empty list when the host is not on this lane.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        known = _fetch_one(
            cursor,
            """
            SELECT id
              FROM apiome.slate_domains
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid AND host = %s
            """,
            (environment_id, tenant_id, host.lower()),
        )
    if known is None or release_id is None:
        return []
    return routes_for_release(db, release_id=release_id)


# ─── Evidence ────────────────────────────────────────────────────────────────


def record_trace(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
    release_id: Optional[str],
    request: Mapping[str, Any],
    policy_version: int,
    rules_digest: str,
    winning_rule_id: Optional[str],
    verdict: Mapping[str, Any],
) -> Dict[str, Any]:
    """Persist a trace as evidence.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.
        release_id: Release the route inventory came from, when the lane serves one.
        request: The test request as evaluated.
        policy_version: Which policy generation answered.
        rules_digest: The determinism receipt.
        winning_rule_id: Rule that decided, or None when the preset default did.
        verdict: The full verdict.

    Returns:
        The written trace row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_cache_traces
                    (tenant_id, environment_id, actor_id, actor_name, actor_kind, release_id,
                     request, policy_version, rules_digest, winning_rule_id, verdict)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    actor_id,
                    actor_name,
                    actor_kind,
                    release_id,
                    json.dumps(_json(dict(request))),
                    policy_version,
                    rules_digest,
                    winning_rule_id,
                    json.dumps(_json(dict(verdict))),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def record_purge(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
    scope_kind: str,
    scope_value: str,
    release_id: Optional[str],
    reason: str,
    estimated_objects: int,
    estimate_basis: str,
    sample_routes: Sequence[str],
    dry_run: bool,
    outcome: str,
    refusal_reason: Optional[str],
    edge_attached: bool,
) -> Dict[str, Any]:
    """Persist a purge record.

    ``outcome`` is never ``dispatched`` today: no delivery tier is attached, and V187's
    ``outcome <> 'dispatched' OR edge_attached`` CHECK refuses the row if it were. What this
    writes is real and auditable — who asked, for what scope, with what estimated blast radius,
    and why — and the API response says in as many words that nothing was evicted.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.
        scope_kind: One of the five purge scopes.
        scope_value: The scope itself.
        release_id: Release the estimate was computed against.
        reason: The operator's stated reason.
        estimated_objects: The estimate.
        estimate_basis: Which table produced it.
        sample_routes: A bounded sample of what is in scope.
        dry_run: Whether this was an estimate only.
        outcome: ``estimated``, ``recorded`` or ``refused``.
        refusal_reason: The named reason when refused, and None otherwise.
        edge_attached: Whether a delivery tier was attached, snapshotted onto the row.

    Returns:
        The written purge row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_cache_purges
                    (tenant_id, environment_id, actor_id, actor_name, actor_kind, scope_kind,
                     scope_value, release_id, reason, estimated_objects, estimate_basis,
                     sample_routes, dry_run, outcome, refusal_reason, edge_attached)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    actor_id,
                    actor_name,
                    actor_kind,
                    scope_kind,
                    scope_value,
                    release_id,
                    reason,
                    estimated_objects,
                    estimate_basis,
                    list(sample_routes),
                    dry_run,
                    outcome,
                    refusal_reason,
                    edge_attached,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def list_purges(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    limit: int = 50,
    scope_kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load a lane's purge history, most recent first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        limit: How many records to return.
        scope_kind: Restrict to one scope kind, or None for all.

    Returns:
        Purge rows, most recent first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        if scope_kind:
            return _fetch_all(
                cursor,
                """
                SELECT *
                  FROM apiome.slate_cache_purges
                 WHERE environment_id = %s::uuid AND tenant_id = %s::uuid AND scope_kind = %s
                 ORDER BY at DESC
                 LIMIT %s
                """,
                (environment_id, tenant_id, scope_kind, limit),
            )
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_cache_purges
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY at DESC
             LIMIT %s
            """,
            (environment_id, tenant_id, limit),
        )


def append_audit(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
    subject_kind: str,
    subject_id: Optional[str],
    summary: str,
    detail: Optional[str] = None,
) -> None:
    """Append a cache audit entry.

    Used for every policy change and, importantly, for *refused* actions, which must leave a
    trace even though nothing changed. Refusing to purge during an incident is exactly the
    event that needs to be in the timeline afterwards.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.
        subject_kind: ``preset``, ``rule``, ``purge`` or ``trace``.
        subject_id: Id of the subject row, when there is one.
        summary: What happened.
        detail: Extra context, e.g. the refusal reason and its sentence.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO apiome.slate_cache_audit
                    (tenant_id, environment_id, actor_id, actor_name, actor_kind, subject_kind,
                     subject_id, summary, detail)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    environment_id,
                    actor_id,
                    actor_name,
                    actor_kind,
                    subject_kind,
                    subject_id,
                    summary,
                    detail,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def list_audit(
    db: _DbLike, *, tenant_id: str, environment_id: str, limit: int = 100
) -> List[Dict[str, Any]]:
    """Load a lane's cache audit trail, most recent first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        limit: How many entries to return.

    Returns:
        Audit rows, most recent first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_cache_audit
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY at DESC
             LIMIT %s
            """,
            (environment_id, tenant_id, limit),
        )
