"""Persistence for the Slate deployment control plane — APX-3.1 (private-suite#2456).

Reads and writes the V186 tables. Follows the ``canonical_persistence`` precedent: a small
``_DbLike`` protocol rather than a dependency on the concrete ``Database`` singleton, so the
whole surface can be exercised against a fake connection and every rule below is tested
without a live Postgres.

**The atomic activation.** :func:`activate` is the only function in the codebase that moves a
lane's routing pointer, and it does so with a single conditional UPDATE:

    UPDATE apiome.slate_environments
       SET active_release_id = %s, routing_version = routing_version + 1
     WHERE id = %s AND routing_version = %s

A single-row update is atomic in PostgreSQL, so no reader ever observes a lane between two
releases (criterion 2). The ``routing_version`` predicate is the concurrency control: the
second of two simultaneous promotions matches zero rows and is recorded as a ``conflict``
rather than silently overwriting the first (criterion 4). There is deliberately no
last-write-wins path and no ``ON CONFLICT DO UPDATE`` anywhere near routing.

Everything an activation touches — the pointer, the superseded release's deactivation, the
new release's activation timestamps, the ledger row and the audit entry — commits or rolls
back together. A failed activation therefore leaves the lane serving exactly what it served
before, which is the property that makes rollback trustworthy.

**Promotion never rebuilds** (criterion 3) is structural here: :func:`activate` takes an
``ActivationPlan`` carrying a digest that already exists in ``slate_artifacts``, and there is
no code path from this module to a build. The digest is copied onto the ledger row so the
ledger alone is sufficient evidence that no bytes were produced.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from .slate_releases import ActivationPlan

__all__ = [
    "SlateActivationConflictError",
    "SlateDeploymentStoreError",
    "activate",
    "append_audit",
    "create_environment",
    "create_release",
    "create_site",
    "find_rollback_target",
    "get_environment",
    "get_release",
    "list_releases",
    "list_sites",
    "reap_artifacts",
    "record_artifact",
]


class _DbLike(Protocol):
    """Minimal database surface used by this module."""

    def connect(self) -> Any: ...


class SlateDeploymentStoreError(Exception):
    """A control-plane row was missing or malformed.

    Carries a machine-readable ``code`` so the REST layer maps it to a status without
    string-matching. Codes: ``site_not_found``, ``environment_not_found``,
    ``release_not_found``, ``artifact_not_found``.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SlateActivationConflictError(Exception):
    """Another activation changed the lane's routing first.

    Raised when the conditional UPDATE matched zero rows. The attempt is recorded in the
    ledger with outcome ``conflict`` before this is raised, so a lost promotion is
    reconstructable after the fact rather than merely reported at the time.
    """

    def __init__(self, environment_id: str, expected_routing_version: int, actual: Optional[int]):
        self.environment_id = environment_id
        self.expected_routing_version = expected_routing_version
        self.actual_routing_version = actual
        super().__init__(
            f"Environment {environment_id} routing changed while this activation was being "
            f"prepared (expected routing_version {expected_routing_version}, found {actual})."
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


# ─── Sites and environments ──────────────────────────────────────────────────


def create_site(
    db: _DbLike,
    *,
    tenant_id: str,
    project_id: str,
    name: str,
    slug: str,
    retained_releases: int = 10,
    activation_slo_seconds: int = 300,
) -> Dict[str, Any]:
    """Create a managed Slate site.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        project_id: Project whose documentation the site publishes.
        name: Human-facing site name.
        slug: URL-safe identifier, unique per tenant.
        retained_releases: Superseded releases per environment that keep their artifact.
        activation_slo_seconds: Budget for a full activation.

    Returns:
        The created site row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            row = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_sites
                    (tenant_id, project_id, name, slug, retained_releases, activation_slo_seconds)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
                RETURNING *
                """,
                (tenant_id, project_id, name, slug, retained_releases, activation_slo_seconds),
            )
        conn.commit()
        return row or {}
    except Exception:
        conn.rollback()
        raise


def create_environment(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    kind: str,
    name: str,
    robots_excluded: Optional[bool] = None,
    access_policy: str = "public",
    expires_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create an environment lane for a site.

    Preview lanes default to robots-excluded. That default is applied here rather than
    derived from ``kind`` at read time so a lane that is deliberately made public stays
    public, instead of being silently re-hidden by a later refactor.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the lane belongs to.
        kind: ``production``, ``staging`` or ``preview``.
        name: Lane name, unique per site.
        robots_excluded: Override the crawler-exclusion default.
        access_policy: ``public``, ``tenant``, ``password`` or ``sso``.
        expires_at: Expiry for an ephemeral preview lane.

    Returns:
        The created environment row.
    """
    excluded = (kind == "preview") if robots_excluded is None else robots_excluded
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            row = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_environments
                    (tenant_id, site_id, kind, name, robots_excluded, access_policy, expires_at)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (tenant_id, site_id, kind, name, excluded, access_policy, expires_at),
            )
        conn.commit()
        return row or {}
    except Exception:
        conn.rollback()
        raise


def list_sites(
    db: _DbLike, *, tenant_id: str, project_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List a tenant's managed sites with their environment lanes.

    The Release Center works in terms of a project and a version, not a site id, so this is
    how it resolves what it is looking at. Environments are returned with each site rather
    than through a second call: a site with no lanes and a site whose lanes failed to load
    are different states, and one round trip cannot confuse them.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant.
        project_id: Restrict to one project when given.

    Returns:
        Site rows, each with an ``environments`` list, newest first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        if project_id:
            sites = _fetch_all(
                cursor,
                """
                SELECT * FROM apiome.slate_sites
                 WHERE tenant_id = %s::uuid AND project_id = %s::uuid
                 ORDER BY created_at DESC
                """,
                (tenant_id, project_id),
            )
        else:
            sites = _fetch_all(
                cursor,
                "SELECT * FROM apiome.slate_sites WHERE tenant_id = %s::uuid "
                "ORDER BY created_at DESC",
                (tenant_id,),
            )

        for site in sites:
            site["environments"] = _fetch_all(
                cursor,
                """
                SELECT id, kind, name, active_release_id, routing_version,
                       robots_excluded, access_policy, expires_at
                  FROM apiome.slate_environments
                 WHERE site_id = %s::uuid
                 ORDER BY kind, name
                """,
                (str(site["id"]),),
            )
        return sites


def get_environment(
    db: _DbLike, *, tenant_id: str, environment_id: str
) -> Optional[Dict[str, Any]]:
    """Load one environment, scoped to its tenant.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant; a scope miss returns None so the REST layer can answer
            404 rather than confirming the lane exists to another tenant.
        environment_id: The lane.

    Returns:
        The environment row joined with its site's retention and SLO policy, or None.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT e.*,
                   s.retained_releases,
                   s.activation_slo_seconds
              FROM apiome.slate_environments e
              JOIN apiome.slate_sites s ON s.id = e.site_id
             WHERE e.id = %s::uuid AND e.tenant_id = %s::uuid
            """,
            (environment_id, tenant_id),
        )


# ─── Artifacts ───────────────────────────────────────────────────────────────


def record_artifact(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    content_digest: str,
    source_digest: str,
    config_digest: str,
    signature: str,
    signature_key_id: str,
    manifest: Mapping[str, Any],
    page_count: int,
    size_bytes: int,
    storage_uri: str,
    built_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Record a built artifact, reusing the row when the same bytes already exist.

    Content addressing means an identical rebuild must not create a second identity for one
    artifact. The ``ON CONFLICT`` here is safe precisely because it touches no routing: it
    resolves to the existing row for the same ``(site_id, content_digest)`` rather than
    overwriting anything a release depends on.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the artifact was built for.
        content_digest: Digest of the rendered bytes; the artifact identity.
        source_digest: Digest of the source inputs.
        config_digest: Digest of the build configuration.
        signature: Detached signature over the three digests.
        signature_key_id: Id of the signing key.
        manifest: Build manifest / SBOM.
        page_count: Rendered page count.
        size_bytes: Total artifact size.
        storage_uri: Where the bytes live.
        built_at: When the build finished. Defaults to now.

    Returns:
        The artifact row, new or pre-existing.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            row = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_artifacts
                    (tenant_id, site_id, content_digest, source_digest, config_digest,
                     signature, signature_key_id, manifest, page_count, size_bytes,
                     storage_uri, built_at)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                ON CONFLICT (site_id, content_digest) DO UPDATE
                    SET storage_uri = COALESCE(apiome.slate_artifacts.storage_uri,
                                               EXCLUDED.storage_uri)
                RETURNING *
                """,
                (
                    tenant_id,
                    site_id,
                    content_digest,
                    source_digest,
                    config_digest,
                    signature,
                    signature_key_id,
                    json.dumps(_json(dict(manifest))),
                    page_count,
                    size_bytes,
                    storage_uri,
                    built_at or _now(),
                ),
            )
        conn.commit()
        return row or {}
    except Exception:
        conn.rollback()
        raise


# ─── Releases ────────────────────────────────────────────────────────────────

# Columns every release read needs, joined to the artifact so the promotion gate can check
# digest, retention and signature state without a second round trip.
_RELEASE_SELECT = """
    SELECT r.*,
           a.content_digest AS artifact_digest,
           a.source_digest,
           a.config_digest,
           a.signature,
           a.signature_key_id,
           a.manifest,
           a.page_count,
           a.size_bytes,
           a.storage_uri,
           a.built_at,
           a.reaped_at AS artifact_reaped_at
      FROM apiome.slate_releases r
      LEFT JOIN apiome.slate_artifacts a ON a.id = r.artifact_id
"""


def create_release(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    environment_id: str,
    release_ref: str,
    source_commit: str,
    source_ref: str,
    source_message: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
    artifact_id: Optional[str] = None,
    status: str = "queued",
    impact: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an immutable release record and its first audit entry.

    The release and its audit entry are written in one transaction: a release that exists
    with no record of who created it is exactly the gap the audit trail is meant to close.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the release belongs to.
        environment_id: Lane the release targets.
        release_ref: Short human-quotable id, unique per site.
        source_commit: Full commit sha.
        source_ref: Branch or tag.
        source_message: First line of the commit message.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.
        artifact_id: Artifact when already built; None while queued.
        status: Initial lifecycle state.
        impact: Cache/security consequences of activation.

    Returns:
        The created release row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            row = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_releases
                    (tenant_id, site_id, environment_id, release_ref, artifact_id, status,
                     source_commit, source_ref, source_message,
                     actor_id, actor_name, actor_kind, impact)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING *
                """,
                (
                    tenant_id,
                    site_id,
                    environment_id,
                    release_ref,
                    artifact_id,
                    status,
                    source_commit,
                    source_ref,
                    source_message,
                    actor_id,
                    actor_name,
                    actor_kind,
                    json.dumps(_json(dict(impact or {}))),
                ),
            )
            if row:
                _insert_audit(
                    cursor,
                    tenant_id=tenant_id,
                    release_id=str(row["id"]),
                    actor_id=actor_id,
                    actor_name=actor_name,
                    actor_kind=actor_kind,
                    summary=f"Release {release_ref} created",
                    detail=f"From {source_ref} at {source_commit[:12]}",
                )
        conn.commit()
        return row or {}
    except Exception:
        conn.rollback()
        raise


def get_release(db: _DbLike, *, tenant_id: str, release_id: str) -> Optional[Dict[str, Any]]:
    """Load one release with its artifact facts, scoped to its tenant.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant; a scope miss returns None.
        release_id: The release.

    Returns:
        The release row joined to its artifact, or None.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            _RELEASE_SELECT + " WHERE r.id = %s::uuid AND r.tenant_id = %s::uuid",
            (release_id, tenant_id),
        )


def list_releases(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    environment_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List releases for a site, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant.
        site_id: Site to list.
        environment_id: Restrict to one lane when given.
        limit: Maximum rows.

    Returns:
        Release rows joined to their artifacts, newest first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        if environment_id:
            return _fetch_all(
                cursor,
                _RELEASE_SELECT
                + """ WHERE r.tenant_id = %s::uuid AND r.site_id = %s::uuid
                        AND r.environment_id = %s::uuid
                      ORDER BY r.created_at DESC LIMIT %s""",
                (tenant_id, site_id, environment_id, limit),
            )
        return _fetch_all(
            cursor,
            _RELEASE_SELECT
            + """ WHERE r.tenant_id = %s::uuid AND r.site_id = %s::uuid
                  ORDER BY r.created_at DESC LIMIT %s""",
            (tenant_id, site_id, limit),
        )


def find_rollback_target(
    db: _DbLike, *, tenant_id: str, environment_id: str
) -> Optional[Dict[str, Any]]:
    """Find the most recent retained release a lane can roll back to.

    Only releases that still hold their bytes qualify: an artifact reaped by retention is
    not a rollback target, however recently it served. Returning it anyway would produce a
    rollback that plans successfully and then fails at activation, which is the worst
    possible moment to discover the bytes are gone.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant.
        environment_id: Lane to roll back.

    Returns:
        The rollback target release joined to its artifact, or None.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            _RELEASE_SELECT
            + """ WHERE r.tenant_id = %s::uuid
                    AND r.environment_id = %s::uuid
                    AND r.status IN ('superseded', 'rolled-back')
                    AND r.artifact_id IS NOT NULL
                    AND a.reaped_at IS NULL
                    AND a.storage_uri IS NOT NULL
                  ORDER BY r.deactivated_at DESC NULLS LAST, r.created_at DESC
                  LIMIT 1""",
            (tenant_id, environment_id),
        )


# ─── Audit ───────────────────────────────────────────────────────────────────


def _insert_audit(
    cursor: Any,
    *,
    tenant_id: str,
    release_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
    summary: str,
    detail: Optional[str] = None,
) -> None:
    """Append one audit entry using an existing cursor.

    Takes a cursor rather than opening its own connection so audit entries always commit in
    the same transaction as the thing they describe.
    """
    cursor.execute(
        """
        INSERT INTO apiome.slate_release_audit
            (tenant_id, release_id, actor_id, actor_name, actor_kind, summary, detail)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
        """,
        (tenant_id, release_id, actor_id, actor_name, actor_kind, summary, detail),
    )


def append_audit(
    db: _DbLike,
    *,
    tenant_id: str,
    release_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
    summary: str,
    detail: Optional[str] = None,
) -> None:
    """Append a standalone audit entry.

    Used for events with no accompanying mutation — most importantly a *refused* action,
    which must leave a trace even though nothing changed.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        release_id: Release the entry describes.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.
        summary: What happened.
        detail: Extra context, e.g. the refusal reason.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            _insert_audit(
                cursor,
                tenant_id=tenant_id,
                release_id=release_id,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_kind=actor_kind,
                summary=summary,
                detail=detail,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ─── Activation ──────────────────────────────────────────────────────────────


def activate(
    db: _DbLike,
    plan: ActivationPlan,
    *,
    tenant_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
) -> Dict[str, Any]:
    """Move a lane's routing pointer atomically, or refuse and record why.

    The whole activation is one transaction:

    1. Insert the ledger row recording what is being attempted and the routing token read.
    2. Conditionally update the environment pointer, asserting that token. **Zero rows
       matched means another activation won the race**: the ledger row is marked
       ``conflict`` and :class:`SlateActivationConflictError` is raised. Because the ledger
       write commits with the conflict, a lost promotion is reconstructable afterwards.
    3. Supersede the outgoing release and stamp the incoming one.
    4. Append the audit entry.

    Nothing here builds anything. ``plan.artifact_digest`` names bytes that already exist,
    and it is copied onto the ledger row so the ledger alone evidences that promotion routed
    rather than rebuilt.

    Args:
        db: Database handle exposing ``connect()``.
        plan: The activation decided by ``slate_releases.plan_promotion``/``plan_rollback``.
        tenant_id: Owning tenant.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.

    Returns:
        A mapping with ``activationId``, ``routingVersion`` and ``activatedAt``.

    Raises:
        SlateActivationConflictError: When the lane's routing changed first. The transaction
            is committed with the conflict recorded, and routing is left untouched.
    """
    now = _now()
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            ledger = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_activations
                    (tenant_id, environment_id, from_release_id, to_release_id, kind,
                     actor_id, actor_name, actor_kind, outcome,
                     routing_version_before, artifact_digest, started_at)
                VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s,
                        %s, %s, %s, 'pending', %s, %s, %s)
                RETURNING id
                """,
                (
                    tenant_id,
                    plan.environment_id,
                    plan.replaces_release_id,
                    plan.release_id,
                    plan.action if plan.action == "rollback" else (
                        "promotion" if plan.replaces_release_id else "initial"
                    ),
                    actor_id,
                    actor_name,
                    actor_kind,
                    plan.expected_routing_version,
                    plan.artifact_digest,
                    now,
                ),
            )
            activation_id = str(ledger["id"]) if ledger else None

            # The atomic switch. One row, one statement, guarded by the token the plan was
            # built against.
            cursor.execute(
                """
                UPDATE apiome.slate_environments
                   SET active_release_id = %s::uuid,
                       routing_version = routing_version + 1
                 WHERE id = %s::uuid
                   AND tenant_id = %s::uuid
                   AND routing_version = %s
                RETURNING routing_version
                """,
                (
                    plan.release_id,
                    plan.environment_id,
                    tenant_id,
                    plan.expected_routing_version,
                ),
            )
            switched = _as_dict(cursor.fetchone())

            if switched is None:
                actual = _fetch_one(
                    cursor,
                    "SELECT routing_version FROM apiome.slate_environments WHERE id = %s::uuid",
                    (plan.environment_id,),
                )
                cursor.execute(
                    """
                    UPDATE apiome.slate_activations
                       SET outcome = 'conflict', completed_at = %s, failure_reason = %s
                     WHERE id = %s::uuid
                    """,
                    (
                        now,
                        "Routing changed while this activation was being prepared.",
                        activation_id,
                    ),
                )
                _insert_audit(
                    cursor,
                    tenant_id=tenant_id,
                    release_id=plan.release_id,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    actor_kind=actor_kind,
                    summary=f"{plan.action.capitalize()} refused: concurrent activation",
                    detail=(
                        f"Expected routing version {plan.expected_routing_version}, "
                        f"found {actual.get('routing_version') if actual else 'unknown'}."
                    ),
                )
                # Commit the evidence, not the routing change.
                conn.commit()
                raise SlateActivationConflictError(
                    plan.environment_id,
                    plan.expected_routing_version,
                    actual.get("routing_version") if actual else None,
                )

            # Supersede the outgoing release. Status and deactivation only — the immutability
            # trigger rejects anything that would rewrite its identity.
            if plan.replaces_release_id:
                cursor.execute(
                    """
                    UPDATE apiome.slate_releases
                       SET status = 'superseded', deactivated_at = %s, traffic_percent = NULL,
                           traffic_requests_per_min = NULL
                     WHERE id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (now, plan.replaces_release_id, tenant_id),
                )

            # Stamp the incoming release. activation_completed_at is deliberately NOT set
            # here: activation has started, and it is complete only when every region has
            # reported. Setting both now would make every rollout look instantaneous and
            # leave the SLO with nothing to measure.
            cursor.execute(
                """
                UPDATE apiome.slate_releases
                   SET status = 'active', activated_at = %s, deactivated_at = NULL
                 WHERE id = %s::uuid AND tenant_id = %s::uuid
                """,
                (now, plan.release_id, tenant_id),
            )

            cursor.execute(
                """
                UPDATE apiome.slate_activations
                   SET outcome = 'succeeded', routing_version_after = %s
                 WHERE id = %s::uuid
                """,
                (switched["routing_version"], activation_id),
            )

            _insert_audit(
                cursor,
                tenant_id=tenant_id,
                release_id=plan.release_id,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_kind=actor_kind,
                summary=(
                    "Rolled back" if plan.action == "rollback" else "Promoted"
                ),
                detail=(
                    f"Routed to {plan.artifact_digest} without rebuilding"
                    + (
                        f"; replaced {plan.replaces_release_id}"
                        if plan.replaces_release_id
                        else ""
                    )
                ),
            )

        conn.commit()
        return {
            "activationId": activation_id,
            "routingVersion": switched["routing_version"],
            "activatedAt": now,
        }
    except SlateActivationConflictError:
        raise
    except Exception:
        conn.rollback()
        raise


# ─── Retention ───────────────────────────────────────────────────────────────


def reap_artifacts(
    db: _DbLike, *, tenant_id: str, release_ids: Sequence[str]
) -> int:
    """Reap the artifacts of the given releases, clearing their stored bytes.

    The artifact row is marked rather than deleted, so history keeps its digest: a timeline
    that forgets which bytes a past release served is not a timeline. ``ON DELETE RESTRICT``
    on ``slate_releases.artifact_id`` means deleting it would be refused anyway.

    Never reaps an artifact still referenced by a release that is active, so a retention
    sweep can never take production's bytes out from under it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        release_ids: Releases whose artifacts may be reaped.

    Returns:
        The number of artifacts reaped.
    """
    if not release_ids:
        return 0

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE apiome.slate_artifacts
                   SET reaped_at = %s, storage_uri = NULL
                 WHERE tenant_id = %s::uuid
                   AND reaped_at IS NULL
                   AND id IN (
                        SELECT r.artifact_id FROM apiome.slate_releases r
                         WHERE r.id = ANY(%s::uuid[]) AND r.artifact_id IS NOT NULL
                   )
                   AND id NOT IN (
                        SELECT r.artifact_id FROM apiome.slate_releases r
                         WHERE r.status = 'active' AND r.artifact_id IS NOT NULL
                   )
                """,
                (_now(), tenant_id, list(release_ids)),
            )
            reaped = cursor.rowcount or 0
        conn.commit()
        return reaped
    except Exception:
        conn.rollback()
        raise
