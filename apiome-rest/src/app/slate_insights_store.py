"""Persistence for the Slate Edge observability control plane — UXE-3.4 (private-suite#2476).

Reads and writes the V190 tables. Follows :mod:`app.slate_functions_store` exactly, which follows
:mod:`app.slate_security_store` and :mod:`app.slate_cache_store`: a small ``_DbLike`` protocol
rather than a dependency on the concrete ``Database`` singleton, so the whole surface can be
exercised against a fake connection without a live Postgres.

**Concurrency.** Every write that changes observability policy goes through
:func:`bump_policy_version`, whose conditional UPDATE mirrors the cache, security and function
planes':

    UPDATE apiome.slate_insight_policies
       SET policy_version = policy_version + 1
     WHERE environment_id = %s AND policy_version = %s

The second of two simultaneous edits matches zero rows and is refused as
``policy-version-conflict`` rather than silently overwriting the first. Two operators changing
retention or a budget during the same incident is the normal case, not the exotic one, so there is
deliberately no last-write-wins path anywhere in this module.

**Nothing here measures anything, and that is enforced by statement text rather than by argument.**
``deploy/`` is a single Caddyfile: there is no CDN, no collector and no meter behind it. So the
columns that say what a row is worth are written as SQL literals rather than as parameters, and
this module therefore offers no argument by which a caller could ask it to record a measurement:

* :func:`record_metric_point`, :func:`record_log`, :func:`record_trace` and
  :func:`record_synthetic_result` write ``basis = 'modelled'`` and ``edge_attached = FALSE``.
* :func:`record_usage` writes ``basis = 'modelled'``, ``billable = FALSE`` and
  ``edge_attached = FALSE`` — and additionally declines to write ``cache_savings_amount`` at all,
  because V190 permits it only on a metered row.
* :func:`open_tail_session` writes ``stream_state = 'requested'``, ``events_delivered = 0`` and
  ``edge_attached = FALSE``.
* :func:`upsert_export` writes ``last_delivery_state = 'never-attempted'`` and
  ``edge_attached = FALSE``.
* :func:`record_budget_alert` writes ``basis = 'modelled'``, ``delivery_state = 'not-dispatched'``
  and ``edge_attached = FALSE``.

V190 CHECKs the same facts, so a future caller reaching these tables by another route still cannot
claim a measurement. The reason this is stricter here than on the three predecessor surfaces is
that those record controls and this records truth: an unenforced cache rule wastes a purge and an
unenforced WAF rule leaves an attacker unblocked, but a fabricated p95 gets a release promoted and
a fabricated cost becomes an invoice.

**Redaction is this module's job, not the caller's.** V190 constrains ``evidence`` and
``attributes`` to an allowlist of *top-level keys*, which is a backstop and not a mechanism: a
nested object under an allowed key would satisfy that CHECK while carrying an entire request body
into the database. :func:`redact_evidence` is the mechanism, reused from
:mod:`app.slate_insights`, and it is applied here rather than trusted to callers. That matters more
on this surface than on any predecessor, because live tail exists specifically to put live reader
traffic in front of a person.

**Retention is written, never defaulted to forever.** Every request-data table in V190 requires
``retain_until``, and this module derives it from the lane's policy rather than from a constant, so
shortening retention in the policy actually shortens it for rows written afterwards. The audit
table has no retention and is append-only: the record that a capture happened outlives the capture.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from app.slate_insights import EVIDENCE_KEYS, SPAN_ATTRIBUTE_KEYS, redact_evidence

__all__ = [
    "SlateInsightPolicyConflictError",
    "SlateInsightStoreError",
    "acknowledge_budget_alert",
    "append_audit",
    "bump_policy_version",
    "close_tail_session",
    "delete_budget",
    "delete_export",
    "delete_synthetic_check",
    "ensure_policy",
    "ensure_residency_lanes",
    "get_policy",
    "get_trace",
    "list_audit",
    "list_budget_alerts",
    "list_budgets",
    "list_exports",
    "list_logs",
    "list_metric_series",
    "list_residency_lanes",
    "list_synthetic_checks",
    "list_synthetic_results",
    "list_tail_sessions",
    "list_traces",
    "list_usage",
    "open_tail_session",
    "record_budget_alert",
    "record_log",
    "record_metric_point",
    "record_synthetic_result",
    "record_trace",
    "record_usage",
    "update_policy",
    "upsert_budget",
    "upsert_export",
    "upsert_residency_lane",
    "upsert_synthetic_check",
]


class _DbLike(Protocol):
    """Minimal database surface used by this module."""

    def connect(self) -> Any: ...


class SlateInsightStoreError(Exception):
    """An observability control-plane row was missing or malformed.

    Carries a machine-readable ``code`` so the REST layer maps it to a status without
    string-matching. Codes: ``policy_not_found``, ``lane_not_found``, ``export_not_found``,
    ``budget_not_found``, ``alert_not_found``, ``check_not_found``, ``trace_not_found``,
    ``session_not_found``.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SlateInsightPolicyConflictError(Exception):
    """Another operator changed the lane's observability policy first.

    Raised when the conditional UPDATE matched zero rows. The REST layer turns this into the
    ``policy-version-conflict`` refusal, whose sentence tells the operator to re-read.
    """

    def __init__(self, environment_id: str, expected: int, actual: Optional[int]) -> None:
        self.environment_id = environment_id
        self.expected_policy_version = expected
        self.actual_policy_version = actual
        super().__init__(
            f"Environment {environment_id} observability policy changed while this edit was being "
            f"prepared (expected version {expected}, found {actual})."
        )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _as_dict(row: Any) -> Optional[Dict[str, Any]]:
    """Return a row as a plain dict, or None."""
    return dict(row) if row is not None else None


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


#: Retention fallbacks, used only when a lane has no policy row yet. Deliberately the same numbers
#: as V190's column defaults: a row written before a policy exists must not outlive one written
#: after, which is what a longer fallback here would cause.
_FALLBACK_LOG_RETENTION_DAYS = 14
_FALLBACK_TRACE_RETENTION_DAYS = 7
_FALLBACK_METRIC_RETENTION_DAYS = 90


def _retention(policy: Optional[Mapping[str, Any]], key: str, fallback: int) -> datetime:
    """Compute a retention deadline from the lane's policy.

    Derived from the policy rather than from a module constant so that shortening retention
    actually shortens it for rows written afterwards. V190 forbids NULL here, and indefinite
    retention of request data is a liability rather than a feature.

    Args:
        policy: The lane's policy row, when it exists.
        key: Which retention column to read.
        fallback: Days to use when there is no policy row yet.

    Returns:
        The absolute deadline after which the row must be deleted.
    """
    days = fallback
    if policy is not None:
        candidate = policy.get(key)
        if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
            days = candidate
    return _now() + timedelta(days=days)


# ─── Policy ──────────────────────────────────────────────────────────────────


def get_policy(db: _DbLike, *, tenant_id: str, environment_id: str) -> Optional[Dict[str, Any]]:
    """Read the observability policy for one lane.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        The policy row, or None when the lane has never had one.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT * FROM apiome.slate_insight_policies
             WHERE tenant_id = %s::uuid AND environment_id = %s::uuid
            """,
            (tenant_id, environment_id),
        )


def ensure_policy(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    environment_id: str,
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Read the lane's policy, creating it at V190's defaults when absent.

    Creating on read rather than requiring an explicit enable is deliberate and matches the cache
    and security planes: the defaults are the safe posture (collection off, the longest retention
    of the three on metrics and the shortest on traces, the privacy threshold set above its floor),
    so a lane that has never been configured reads as configured-safely rather than as an error.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the environment belongs to.
        environment_id: The lane.
        actor_name: Display name of the acting user.
        actor_key: Immutable identity of the acting user.
        actor_id: The user's id, when still present.

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
                INSERT INTO apiome.slate_insight_policies
                    (tenant_id, site_id, environment_id, edge_attached,
                     updated_by_actor_id, updated_by_actor_name, updated_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s::uuid, FALSE, %s::uuid, %s, %s)
                ON CONFLICT (environment_id) DO NOTHING
                RETURNING *
                """,
                (tenant_id, site_id, environment_id, actor_id, actor_name, actor_key),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if created is not None:
        return created

    # Another request created it between the read and the insert. Re-read rather than raise: two
    # operators opening the surface simultaneously is the ordinary case, not a conflict.
    settled = get_policy(db, tenant_id=tenant_id, environment_id=environment_id)
    if settled is None:
        raise SlateInsightStoreError(
            "policy_not_found",
            f"Observability policy for environment {environment_id} could not be created or read.",
        )
    return settled


def bump_policy_version(
    db: _DbLike, *, environment_id: str, expected_policy_version: int
) -> int:
    """Increment the lane's policy version, refusing a stale expectation.

    Args:
        db: Database handle exposing ``connect()``.
        environment_id: The lane.
        expected_policy_version: The version the caller read before preparing its edit.

    Returns:
        The new policy version.

    Raises:
        SlateInsightPolicyConflictError: When the conditional UPDATE matched zero rows, meaning
            another operator wrote first.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            updated = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_insight_policies
                   SET policy_version = policy_version + 1, updated_at = %s
                 WHERE environment_id = %s::uuid AND policy_version = %s
                 RETURNING policy_version
                """,
                (_now(), environment_id, expected_policy_version),
            )
            if updated is None:
                actual = _fetch_one(
                    cursor,
                    """
                    SELECT policy_version FROM apiome.slate_insight_policies
                     WHERE environment_id = %s::uuid
                    """,
                    (environment_id,),
                )
                conn.rollback()
                raise SlateInsightPolicyConflictError(
                    environment_id,
                    expected_policy_version,
                    (actual or {}).get("policy_version"),
                )
        conn.commit()
    except SlateInsightPolicyConflictError:
        raise
    except Exception:
        conn.rollback()
        raise
    return int(updated["policy_version"])


def update_policy(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    policy: Mapping[str, Any],
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the lane's observability policy.

    ``edge_attached`` is absent from the update list on purpose. It is not an operator setting but
    a statement about whether a collector exists, and no code path in this system sets it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        policy: The normalized policy to write.
        actor_name: Display name of the acting user.
        actor_key: Immutable identity of the acting user.
        actor_id: The user's id, when still present.

    Returns:
        The updated policy row.

    Raises:
        SlateInsightStoreError: When the lane has no policy row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            updated = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_insight_policies
                   SET telemetry_enabled = %s,
                       metric_retention_days = %s,
                       log_retention_days = %s,
                       trace_retention_days = %s,
                       default_sample_rate = %s,
                       max_tail_sample_rate = %s,
                       max_tail_events_per_sec = %s,
                       privacy_threshold = %s,
                       retention_waiver_reason = %s,
                       updated_at = %s,
                       updated_by_actor_id = %s::uuid,
                       updated_by_actor_name = %s,
                       updated_by_actor_key = %s
                 WHERE tenant_id = %s::uuid AND environment_id = %s::uuid
                 RETURNING *
                """,
                (
                    bool(policy["telemetry_enabled"]),
                    policy["metric_retention_days"],
                    policy["log_retention_days"],
                    policy["trace_retention_days"],
                    policy["default_sample_rate"],
                    policy["max_tail_sample_rate"],
                    policy["max_tail_events_per_sec"],
                    policy["privacy_threshold"],
                    policy["retention_waiver_reason"],
                    _now(),
                    actor_id,
                    actor_name,
                    actor_key,
                    tenant_id,
                    environment_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if updated is None:
        raise SlateInsightStoreError(
            "policy_not_found", f"No observability policy for environment {environment_id}."
        )
    return updated


# ─── Residency lanes ─────────────────────────────────────────────────────────


def list_residency_lanes(
    db: _DbLike, *, tenant_id: str, environment_id: str
) -> List[Dict[str, Any]]:
    """Read every residency lane for one environment.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        The residency rows, ordered by stage along the request path rather than alphabetically.
        The ordering matters: the surface renders them as a path, and an alphabetical list would
        put cache storage before ingress.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT * FROM apiome.slate_residency_lanes
             WHERE tenant_id = %s::uuid AND environment_id = %s::uuid
             ORDER BY array_position(
                 ARRAY['ingress','tls-termination','decrypted-processing','cache-storage',
                       'function-execution','log-data-storage']::TEXT[], stage)
            """,
            (tenant_id, environment_id),
        )


def ensure_residency_lanes(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    defaults: Sequence[Mapping[str, Any]],
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Create any of the six stages that do not yet exist, at their catalog defaults.

    All six or none is the point. A lane that describes where requests arrive but not where logs
    come to rest reads as a complete promise and is not one, so the surface must never be able to
    render five stages and leave the reader to notice the sixth is missing.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        defaults: Normalized default lanes, one per stage, carrying the catalog gap sentences.
        actor_name: Display name of the acting user.
        actor_key: Immutable identity of the acting user.
        actor_id: The user's id, when still present.

    Returns:
        All six residency rows, in path order.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            for lane in defaults:
                cursor.execute(
                    """
                    INSERT INTO apiome.slate_residency_lanes
                        (tenant_id, environment_id, stage, residency_class, regions,
                         uncovered_sentence, enforced, residency_waiver_reason,
                         updated_by_actor_id, updated_by_actor_name, updated_by_actor_key)
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s::text[], %s, FALSE, %s, %s::uuid,
                            %s, %s)
                    ON CONFLICT (environment_id, stage) DO NOTHING
                    """,
                    (
                        tenant_id,
                        environment_id,
                        lane["stage"],
                        lane["residency_class"],
                        list(lane["regions"]),
                        lane["uncovered_sentence"],
                        # Carried rather than omitted. A default lane is created `unrestricted`,
                        # because a stage nobody has configured has made no residency promise,
                        # and V190 requires that loosening be explained. Dropping this column
                        # would leave the honest default as the one the database refuses.
                        lane.get("residency_waiver_reason"),
                        actor_id,
                        actor_name,
                        actor_key,
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return list_residency_lanes(db, tenant_id=tenant_id, environment_id=environment_id)


def upsert_residency_lane(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    lane: Mapping[str, Any],
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write one residency stage.

    ``enforced`` is written as a literal FALSE rather than taken from the caller: nothing is in the
    request path, so a stage's placement is a declared intent and not an active control. Storing it
    as a column at all is what lets attaching a real edge later upgrade a promise rather than
    rewrite history.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        lane: The normalized residency lane to write.
        actor_name: Display name of the acting user.
        actor_key: Immutable identity of the acting user.
        actor_id: The user's id, when still present.

    Returns:
        The written residency row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_residency_lanes
                    (tenant_id, environment_id, stage, residency_class, regions,
                     uncovered_sentence, enforced, residency_waiver_reason,
                     updated_by_actor_id, updated_by_actor_name, updated_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s::text[], %s, FALSE, %s, %s::uuid, %s, %s)
                ON CONFLICT (environment_id, stage) DO UPDATE
                   SET residency_class = EXCLUDED.residency_class,
                       regions = EXCLUDED.regions,
                       uncovered_sentence = EXCLUDED.uncovered_sentence,
                       residency_waiver_reason = EXCLUDED.residency_waiver_reason,
                       updated_at = CURRENT_TIMESTAMP,
                       updated_by_actor_id = EXCLUDED.updated_by_actor_id,
                       updated_by_actor_name = EXCLUDED.updated_by_actor_name,
                       updated_by_actor_key = EXCLUDED.updated_by_actor_key
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    lane["stage"],
                    lane["residency_class"],
                    list(lane["regions"]),
                    lane["uncovered_sentence"],
                    lane["residency_waiver_reason"],
                    actor_id,
                    actor_name,
                    actor_key,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if written is None:
        raise SlateInsightStoreError(
            "lane_not_found", f"Residency stage {lane['stage']} could not be written."
        )
    return written


# ─── Metrics ─────────────────────────────────────────────────────────────────


def list_metric_series(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    families: Optional[Sequence[str]] = None,
    release_id: Optional[str] = None,
    region: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Read correlated metric points for one lane.

    The three correlation filters are the same three columns on every signal table, so a caller
    that has narrowed a chart can narrow the logs and the usage beside it with the same arguments.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        families: Restrict to these metric families, or all when None.
        release_id: Restrict to one release.
        region: Restrict to one region.
        since: Inclusive lower bound on the window start.
        until: Exclusive upper bound on the window end.
        limit: Maximum rows.

    Returns:
        Metric rows, oldest first within a series.
    """
    clauses = ["tenant_id = %s::uuid", "environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment_id]

    if families:
        clauses.append("metric_family = ANY(%s::text[])")
        params.append(list(families))
    if release_id:
        clauses.append("release_id = %s::uuid")
        params.append(release_id)
    if region:
        clauses.append("region = %s")
        params.append(region)
    if since:
        clauses.append("window_start >= %s")
        params.append(since)
    if until:
        clauses.append("window_end <= %s")
        params.append(until)

    params.append(max(1, min(int(limit), 5000)))
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT * FROM apiome.slate_insight_metric_series
             WHERE {' AND '.join(clauses)}
             ORDER BY metric_family, metric_key, window_start
             LIMIT %s
            """,
            params,
        )


def record_metric_point(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    metric_family: str,
    metric_key: str,
    window_start: datetime,
    window_end: datetime,
    value: Optional[float],
    unit: str = "count",
    sample_count: int = 0,
    suppressed: bool = False,
    release_id: Optional[str] = None,
    region: str = "auto",
) -> Dict[str, Any]:
    """Persist one modelled metric point.

    ``basis`` and ``edge_attached`` are literals in the statement below rather than parameters.
    Nothing observed this lane, and rather than trusting every caller to pass the honest value,
    this function offers no way to pass a dishonest one. V190 CHECKs the same fact.

    A suppressed point is written with a NULL value regardless of what the caller passed, because
    V190 requires exactly that pairing and because a suppressed row that kept its number in the
    column leaves every future reader to remember not to read it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        metric_family: One of the six families.
        metric_key: The series within the family.
        window_start: Inclusive start of the aggregation window.
        window_end: Exclusive end.
        value: The aggregated value, ignored when suppressed.
        unit: Unit of the value.
        sample_count: Population behind the point.
        suppressed: Whether the value was withheld for privacy.
        release_id: Release the point is attributed to, when there is one.
        region: Region the point is attributed to.

    Returns:
        The written metric row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_metric_series
                    (tenant_id, environment_id, release_id, region, metric_family, metric_key,
                     window_start, window_end, value, unit, sample_count, suppressed,
                     basis, edge_attached)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'modelled', FALSE)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    release_id,
                    region,
                    metric_family,
                    metric_key,
                    window_start,
                    window_end,
                    None if suppressed else value,
                    unit,
                    max(0, int(sample_count)),
                    bool(suppressed),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Logs ────────────────────────────────────────────────────────────────────


def list_logs(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    levels: Optional[Sequence[str]] = None,
    sources: Optional[Sequence[str]] = None,
    release_id: Optional[str] = None,
    region: Optional[str] = None,
    trace_ref: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Read structured logs for one lane, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        levels: Restrict to these levels.
        sources: Restrict to these emitting subsystems.
        release_id: Restrict to one release.
        region: Restrict to one region.
        trace_ref: Restrict to the lines belonging to one trace.
        query: Case-insensitive substring match against the message.
        limit: Maximum rows.

    Returns:
        Log rows, newest first.
    """
    clauses = ["tenant_id = %s::uuid", "environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment_id]

    if levels:
        clauses.append("level = ANY(%s::text[])")
        params.append(list(levels))
    if sources:
        clauses.append("source = ANY(%s::text[])")
        params.append(list(sources))
    if release_id:
        clauses.append("release_id = %s::uuid")
        params.append(release_id)
    if region:
        clauses.append("region = %s")
        params.append(region)
    if trace_ref:
        clauses.append("trace_ref = %s::uuid")
        params.append(trace_ref)
    if query:
        clauses.append("message ILIKE %s")
        params.append(f"%{query}%")

    params.append(max(1, min(int(limit), 1000)))
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT * FROM apiome.slate_insight_logs
             WHERE {' AND '.join(clauses)}
             ORDER BY at DESC
             LIMIT %s
            """,
            params,
        )


def record_log(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    level: str,
    source: str,
    message: str,
    evidence: Mapping[str, Any],
    release_id: Optional[str] = None,
    region: str = "auto",
    trace_ref: Optional[str] = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist one modelled log line.

    ``evidence`` is passed through :func:`redact_evidence` here, not by the caller. A redaction the
    caller could skip is a redaction that will eventually be skipped, and a log line is request
    data by definition.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        level: One of the four levels.
        source: The emitting subsystem.
        message: The log message.
        evidence: Raw request data; redacted here.
        release_id: Release the line is attributed to, when there is one.
        region: Region the line came from.
        trace_ref: Trace the line belongs to, when there is one.
        policy: The lane policy, so retention is derived from it rather than from a constant.

    Returns:
        The written log row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_logs
                    (tenant_id, environment_id, release_id, region, at, level, source, message,
                     trace_ref, evidence, basis, edge_attached, retain_until)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s::jsonb,
                        'modelled', FALSE, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    release_id,
                    region,
                    _now(),
                    level,
                    source,
                    message,
                    trace_ref,
                    json.dumps(redact_evidence(evidence, EVIDENCE_KEYS)),
                    _retention(policy, "log_retention_days", _FALLBACK_LOG_RETENTION_DAYS),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Traces ──────────────────────────────────────────────────────────────────


def list_traces(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    release_id: Optional[str] = None,
    region: Optional[str] = None,
    route: Optional[str] = None,
    min_duration_ms: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read traces for one lane, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        release_id: Restrict to one release.
        region: Restrict to one region.
        route: Restrict to one route pattern.
        min_duration_ms: Only traces at least this slow, which is how an operator finds the ones
            worth opening.
        limit: Maximum rows.

    Returns:
        Trace rows, newest first.
    """
    clauses = ["tenant_id = %s::uuid", "environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment_id]

    if release_id:
        clauses.append("release_id = %s::uuid")
        params.append(release_id)
    if region:
        clauses.append("region = %s")
        params.append(region)
    if route:
        clauses.append("route = %s")
        params.append(route)
    if min_duration_ms is not None:
        clauses.append("duration_ms >= %s")
        params.append(int(min_duration_ms))

    params.append(max(1, min(int(limit), 500)))
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT * FROM apiome.slate_insight_traces
             WHERE {' AND '.join(clauses)}
             ORDER BY started_at DESC
             LIMIT %s
            """,
            params,
        )


def get_trace(
    db: _DbLike, *, tenant_id: str, environment_id: str, trace_id: str
) -> Dict[str, Any]:
    """Read one trace and its spans, ordered as a waterfall.

    Spans come back ordered by start offset rather than by insertion, because the waterfall is
    drawn from offsets and an ordering the renderer has to redo is an ordering the two can
    disagree about.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        trace_id: The W3C trace id.

    Returns:
        A dict with ``trace`` and ``spans``.

    Raises:
        SlateInsightStoreError: When no such trace exists on this lane.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        trace = _fetch_one(
            cursor,
            """
            SELECT * FROM apiome.slate_insight_traces
             WHERE tenant_id = %s::uuid AND environment_id = %s::uuid AND trace_id = %s
            """,
            (tenant_id, environment_id, trace_id),
        )
        if trace is None:
            raise SlateInsightStoreError(
                "trace_not_found", f"No trace {trace_id} on environment {environment_id}."
            )
        spans = _fetch_all(
            cursor,
            """
            SELECT * FROM apiome.slate_insight_trace_spans
             WHERE trace_id = %s::uuid
             ORDER BY start_offset_ms, name
            """,
            (trace["id"],),
        )
    return {"trace": trace, "spans": spans}


def record_trace(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    trace_id: str,
    started_at: datetime,
    duration_ms: int,
    route: str,
    method: str = "GET",
    status_code: Optional[int] = None,
    sample_rate: float = 1.0,
    release_id: Optional[str] = None,
    region: str = "auto",
    spans: Sequence[Mapping[str, Any]] = (),
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist one modelled trace and its spans.

    The trace and every span are written in a single transaction. A trace whose spans failed to
    land would render as an empty waterfall, which reads as a fast request rather than as missing
    data — the one failure mode a performance surface must never have.

    Span attributes go through :func:`redact_evidence` against the span allowlist for the same
    reason log evidence does.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        trace_id: The W3C trace id, 32 lowercase hex characters.
        started_at: When the traced request began.
        duration_ms: Total duration.
        route: Route pattern matched.
        method: HTTP method.
        status_code: Response status, when the request completed.
        sample_rate: Head sampling rate that kept this trace.
        release_id: Release the trace is attributed to.
        region: Region that handled it.
        spans: The spans, each carrying span_id, name, component, start_offset_ms and duration_ms.
        policy: The lane policy, so retention is derived from it.

    Returns:
        The written trace row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_traces
                    (tenant_id, environment_id, release_id, region, trace_id, started_at,
                     duration_ms, route, method, status_code, sample_rate, basis, edge_attached,
                     retain_until)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s,
                        'modelled', FALSE, %s)
                ON CONFLICT (environment_id, trace_id) DO NOTHING
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    release_id,
                    region,
                    trace_id,
                    started_at,
                    max(0, int(duration_ms)),
                    route,
                    method,
                    status_code,
                    sample_rate,
                    _retention(policy, "trace_retention_days", _FALLBACK_TRACE_RETENTION_DAYS),
                ),
            )
            if written is not None:
                for span in spans:
                    cursor.execute(
                        """
                        INSERT INTO apiome.slate_insight_trace_spans
                            (tenant_id, trace_id, span_id, parent_span_ref, name, component,
                             start_offset_ms, duration_ms, status, attributes)
                        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (trace_id, span_id) DO NOTHING
                        """,
                        (
                            tenant_id,
                            written["id"],
                            span["span_id"],
                            span.get("parent_span_ref"),
                            span["name"],
                            span["component"],
                            max(0, int(span.get("start_offset_ms", 0))),
                            max(0, int(span.get("duration_ms", 0))),
                            span.get("status", "ok"),
                            json.dumps(
                                redact_evidence(
                                    span.get("attributes") or {}, SPAN_ATTRIBUTE_KEYS
                                )
                            ),
                        ),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Live tail ───────────────────────────────────────────────────────────────


def open_tail_session(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    session: Mapping[str, Any],
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Record a live tail session.

    ``stream_state``, ``events_delivered`` and ``edge_attached`` are literals in the statement
    below rather than parameters. Nothing is in the request path, so a session can be requested and
    refused but never attached, and it can never have delivered anything — which is what makes
    ``events_delivered`` safe to sum across sessions. V190 CHECKs both.

    The redaction allowlist actually in force is stored on the row rather than being implied by
    today's constant, so a capture reviewed a year later can be checked against the redaction it
    ran under rather than the current one.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        session: The planned session, from :func:`app.slate_insights.plan_live_tail`.
        actor_name: Display name of the operator opening the tail.
        actor_key: Immutable identity of that operator.
        actor_id: The user's id, when still present.
        policy: The lane policy, so retention is derived from it.

    Returns:
        The written session row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_live_tail_sessions
                    (tenant_id, environment_id, sample_rate, max_events_per_sec,
                     redaction_allowlist, filter_expression, stream_state, started_at,
                     events_delivered, opened_by_actor_id, opened_by_actor_name,
                     opened_by_actor_key, reason, edge_attached, retain_until)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s::text[], %s, 'requested', %s, 0,
                        %s::uuid, %s, %s, %s, FALSE, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    session["sample_rate"],
                    session["max_events_per_sec"],
                    list(session["redaction_allowlist"]),
                    session["filter_expression"],
                    _now(),
                    actor_id,
                    actor_name,
                    actor_key,
                    session["reason"],
                    _retention(policy, "log_retention_days", _FALLBACK_LOG_RETENTION_DAYS),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def close_tail_session(
    db: _DbLike, *, tenant_id: str, environment_id: str, session_id: str
) -> Dict[str, Any]:
    """Mark a live tail session closed.

    ``events_delivered`` is deliberately not updated here. Nothing delivered anything, and a close
    that could write a delivery count would be the one path by which this module could claim a
    stream it never had.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        session_id: The session to close.

    Returns:
        The updated session row.

    Raises:
        SlateInsightStoreError: When no such open session exists.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            updated = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_insight_live_tail_sessions
                   SET stream_state = 'closed', ended_at = %s
                 WHERE tenant_id = %s::uuid AND environment_id = %s::uuid AND id = %s::uuid
                 RETURNING *
                """,
                (_now(), tenant_id, environment_id, session_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if updated is None:
        raise SlateInsightStoreError(
            "session_not_found", f"No live tail session {session_id} on this environment."
        )
    return updated


def list_tail_sessions(
    db: _DbLike, *, tenant_id: str, environment_id: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """Read recent live tail sessions, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        limit: Maximum rows.

    Returns:
        Session rows, newest first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT * FROM apiome.slate_insight_live_tail_sessions
             WHERE tenant_id = %s::uuid AND environment_id = %s::uuid
             ORDER BY started_at DESC
             LIMIT %s
            """,
            (tenant_id, environment_id, max(1, min(int(limit), 200))),
        )


# ─── OTLP export destinations ────────────────────────────────────────────────


def list_exports(db: _DbLike, *, tenant_id: str, environment_id: str) -> List[Dict[str, Any]]:
    """Read every export destination for one lane.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Export rows, ordered by label.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT * FROM apiome.slate_insight_otlp_exports
             WHERE tenant_id = %s::uuid AND environment_id = %s::uuid
             ORDER BY label
            """,
            (tenant_id, environment_id),
        )


def upsert_export(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    export: Mapping[str, Any],
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write one OTLP export destination.

    ``last_delivery_state`` and ``edge_attached`` are literals. Nothing collects, so nothing can
    have been delivered, and a destination that read ``delivered`` would be asserting an arrival
    nobody made. V190 CHECKs it.

    Note what is not in the column list: there is no header value anywhere, because V190 has no
    column able to hold one. The insert would fail if this function tried.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        export: The normalized destination to write.
        actor_name: Display name of the acting user.
        actor_key: Immutable identity of the acting user.
        actor_id: The user's id, when still present.

    Returns:
        The written export row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_otlp_exports
                    (tenant_id, environment_id, label, endpoint, protocol, signals,
                     header_secret_ref, enabled, last_delivery_state, edge_attached,
                     updated_by_actor_id, updated_by_actor_name, updated_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::text[], %s, %s,
                        'never-attempted', FALSE, %s::uuid, %s, %s)
                ON CONFLICT (environment_id, label) DO UPDATE
                   SET endpoint = EXCLUDED.endpoint,
                       protocol = EXCLUDED.protocol,
                       signals = EXCLUDED.signals,
                       header_secret_ref = EXCLUDED.header_secret_ref,
                       enabled = EXCLUDED.enabled,
                       updated_at = CURRENT_TIMESTAMP,
                       updated_by_actor_id = EXCLUDED.updated_by_actor_id,
                       updated_by_actor_name = EXCLUDED.updated_by_actor_name,
                       updated_by_actor_key = EXCLUDED.updated_by_actor_key
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    export["label"],
                    export["endpoint"],
                    export["protocol"],
                    list(export["signals"]),
                    export["header_secret_ref"],
                    bool(export["enabled"]),
                    actor_id,
                    actor_name,
                    actor_key,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if written is None:
        raise SlateInsightStoreError(
            "export_not_found", f"Export destination {export['label']} could not be written."
        )
    return written


def delete_export(
    db: _DbLike, *, tenant_id: str, environment_id: str, export_id: str
) -> Dict[str, Any]:
    """Delete one export destination.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        export_id: The destination to delete.

    Returns:
        The deleted row, so the audit entry can name what it was.

    Raises:
        SlateInsightStoreError: When no such destination exists.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            deleted = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_insight_otlp_exports
                 WHERE tenant_id = %s::uuid AND environment_id = %s::uuid AND id = %s::uuid
                 RETURNING *
                """,
                (tenant_id, environment_id, export_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if deleted is None:
        raise SlateInsightStoreError(
            "export_not_found", f"No export destination {export_id} on this environment."
        )
    return deleted


# ─── Synthetic checks ────────────────────────────────────────────────────────


def list_synthetic_checks(
    db: _DbLike, *, tenant_id: str, environment_id: str
) -> List[Dict[str, Any]]:
    """Read every synthetic check for one lane.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Check rows, ordered by label.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT * FROM apiome.slate_insight_synthetic_checks
             WHERE tenant_id = %s::uuid AND environment_id = %s::uuid
             ORDER BY label
            """,
            (tenant_id, environment_id),
        )


def upsert_synthetic_check(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    check: Mapping[str, Any],
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write one synthetic check.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        check: The check to write.
        actor_name: Display name of the acting user.
        actor_key: Immutable identity of the acting user.
        actor_id: The user's id, when still present.

    Returns:
        The written check row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_synthetic_checks
                    (tenant_id, environment_id, label, target_path, method, regions,
                     interval_seconds, expected_status, latency_budget_ms, enabled,
                     updated_by_actor_id, updated_by_actor_name, updated_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::text[], %s, %s, %s, %s,
                        %s::uuid, %s, %s)
                ON CONFLICT (environment_id, label) DO UPDATE
                   SET target_path = EXCLUDED.target_path,
                       method = EXCLUDED.method,
                       regions = EXCLUDED.regions,
                       interval_seconds = EXCLUDED.interval_seconds,
                       expected_status = EXCLUDED.expected_status,
                       latency_budget_ms = EXCLUDED.latency_budget_ms,
                       enabled = EXCLUDED.enabled,
                       updated_at = CURRENT_TIMESTAMP,
                       updated_by_actor_id = EXCLUDED.updated_by_actor_id,
                       updated_by_actor_name = EXCLUDED.updated_by_actor_name,
                       updated_by_actor_key = EXCLUDED.updated_by_actor_key
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    check["label"],
                    check.get("target_path", "/"),
                    check.get("method", "GET"),
                    list(check.get("regions") or []),
                    int(check.get("interval_seconds", 300)),
                    int(check.get("expected_status", 200)),
                    int(check.get("latency_budget_ms", 1000)),
                    bool(check.get("enabled", False)),
                    actor_id,
                    actor_name,
                    actor_key,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if written is None:
        raise SlateInsightStoreError(
            "check_not_found", f"Synthetic check {check['label']} could not be written."
        )
    return written


def delete_synthetic_check(
    db: _DbLike, *, tenant_id: str, environment_id: str, check_id: str
) -> Dict[str, Any]:
    """Delete one synthetic check and, by cascade, its results.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        check_id: The check to delete.

    Returns:
        The deleted row.

    Raises:
        SlateInsightStoreError: When no such check exists.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            deleted = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_insight_synthetic_checks
                 WHERE tenant_id = %s::uuid AND environment_id = %s::uuid AND id = %s::uuid
                 RETURNING *
                """,
                (tenant_id, environment_id, check_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if deleted is None:
        raise SlateInsightStoreError(
            "check_not_found", f"No synthetic check {check_id} on this environment."
        )
    return deleted


def list_synthetic_results(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    check_id: Optional[str] = None,
    release_id: Optional[str] = None,
    annotated_only: bool = False,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Read synthetic results for one lane, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        check_id: Restrict to one probe.
        release_id: Restrict to one release.
        annotated_only: Only rows carrying a post-promotion annotation, which is how the surface
            answers "what regressed after the last promotion".
        limit: Maximum rows.

    Returns:
        Result rows, newest first.
    """
    clauses = ["tenant_id = %s::uuid", "environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment_id]

    if check_id:
        clauses.append("check_id = %s::uuid")
        params.append(check_id)
    if release_id:
        clauses.append("release_id = %s::uuid")
        params.append(release_id)
    if annotated_only:
        clauses.append("annotation_kind IS NOT NULL")

    params.append(max(1, min(int(limit), 1000)))
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT * FROM apiome.slate_insight_synthetic_results
             WHERE {' AND '.join(clauses)}
             ORDER BY at DESC
             LIMIT %s
            """,
            params,
        )


def record_synthetic_result(
    db: _DbLike,
    *,
    tenant_id: str,
    check_id: str,
    environment_id: str,
    outcome: str,
    region: str = "auto",
    status_code: Optional[int] = None,
    latency_ms: Optional[int] = None,
    release_id: Optional[str] = None,
    annotation_kind: Optional[str] = None,
    annotation_note: Optional[str] = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist one modelled synthetic result.

    ``basis`` and ``edge_attached`` are literals. No probe ran, so the row records what a probe
    would report against the stored check rather than what one observed.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        check_id: The probe.
        environment_id: The lane.
        outcome: One of the four outcomes.
        region: Region the probe would have run from.
        status_code: Status, when the probe completed.
        latency_ms: Latency, when the probe completed.
        release_id: Release active at the time. Required by V190 when annotating.
        annotation_kind: Post-promotion annotation kind, when there is one.
        annotation_note: What the annotation observed, paired with the kind by V190.
        policy: The lane policy, so retention is derived from it.

    Returns:
        The written result row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_synthetic_results
                    (tenant_id, check_id, environment_id, release_id, region, at, outcome,
                     status_code, latency_ms, annotation_kind, annotation_note, basis,
                     edge_attached, retain_until)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s,
                        'modelled', FALSE, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    check_id,
                    environment_id,
                    release_id,
                    region,
                    _now(),
                    outcome,
                    status_code,
                    latency_ms,
                    annotation_kind,
                    annotation_note,
                    _retention(policy, "metric_retention_days", _FALLBACK_METRIC_RETENTION_DAYS),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Usage and spend ─────────────────────────────────────────────────────────


def list_usage(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    services: Optional[Sequence[str]] = None,
    release_id: Optional[str] = None,
    region: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Read daily usage records for one lane.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        services: Restrict to these services.
        release_id: Restrict to one release.
        region: Restrict to one region.
        since: Inclusive lower bound on the usage date.
        until: Inclusive upper bound.
        limit: Maximum rows.

    Returns:
        Usage rows, oldest first, so a period reads left to right the way a chart draws it.
    """
    clauses = ["tenant_id = %s::uuid", "environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment_id]

    if services:
        clauses.append("service = ANY(%s::text[])")
        params.append(list(services))
    if release_id:
        clauses.append("release_id = %s::uuid")
        params.append(release_id)
    if region:
        clauses.append("region = %s")
        params.append(region)
    if since:
        clauses.append("usage_date >= %s")
        params.append(since)
    if until:
        clauses.append("usage_date <= %s")
        params.append(until)

    params.append(max(1, min(int(limit), 5000)))
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT * FROM apiome.slate_insight_usage_records
             WHERE {' AND '.join(clauses)}
             ORDER BY usage_date, service
             LIMIT %s
            """,
            params,
        )


def record_usage(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    service: str,
    usage_date: date,
    quantity: float,
    unit: str,
    amount: float,
    currency: str = "USD",
    included_quantity: float = 0.0,
    overage_quantity: float = 0.0,
    forecast_amount: Optional[float] = None,
    release_id: Optional[str] = None,
    region: str = "auto",
) -> Dict[str, Any]:
    """Persist one modelled daily usage record.

    ``basis``, ``billable`` and ``edge_attached`` are literals. This is the single most
    consequential set of literals in the control plane: a modelled cost presented as a charge is
    not a disappointing estimate but an invented invoice, and V190 refuses the row outright if
    ``billable`` were ever true on a modelled basis.

    ``cache_savings_amount`` is deliberately absent from the column list rather than exposed and
    passed as NULL. V190 permits it only on a metered row, nothing meters these lanes, and a
    parameter that can only ever legally be NULL is an invitation to pass something else.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        service: One of the five services.
        usage_date: The day this record covers.
        quantity: Quantity consumed.
        unit: Unit of the quantity.
        amount: Spend for the day.
        currency: ISO 4217 code.
        included_quantity: How much fell inside the plan quota.
        overage_quantity: How much exceeded it.
        forecast_amount: Projected spend, kept in its own column so it is never summed into a
            total as though it had happened.
        release_id: Release the usage is attributed to.
        region: Region the usage is attributed to.

    Returns:
        The written usage row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_usage_records
                    (tenant_id, environment_id, release_id, region, service, usage_date,
                     quantity, unit, amount, currency, included_quantity, overage_quantity,
                     forecast_amount, basis, billable, edge_attached)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'modelled', FALSE, FALSE)
                ON CONFLICT (environment_id, service, usage_date) DO UPDATE
                   SET quantity = EXCLUDED.quantity,
                       unit = EXCLUDED.unit,
                       amount = EXCLUDED.amount,
                       currency = EXCLUDED.currency,
                       included_quantity = EXCLUDED.included_quantity,
                       overage_quantity = EXCLUDED.overage_quantity,
                       forecast_amount = EXCLUDED.forecast_amount
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    release_id,
                    region,
                    service,
                    usage_date,
                    quantity,
                    unit,
                    amount,
                    currency.upper(),
                    included_quantity,
                    overage_quantity,
                    forecast_amount,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Budgets and alerts ──────────────────────────────────────────────────────


def list_budgets(db: _DbLike, *, tenant_id: str, environment_id: str) -> List[Dict[str, Any]]:
    """Read every budget for one lane.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Budget rows, ordered by label.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT * FROM apiome.slate_insight_budgets
             WHERE tenant_id = %s::uuid AND environment_id = %s::uuid
             ORDER BY label
            """,
            (tenant_id, environment_id),
        )


def upsert_budget(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    budget: Mapping[str, Any],
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write one budget.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        budget: The normalized budget to write.
        actor_name: Display name of the acting user.
        actor_key: Immutable identity of the acting user.
        actor_id: The user's id, when still present.

    Returns:
        The written budget row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_budgets
                    (tenant_id, environment_id, label, service, period, amount, currency,
                     alert_thresholds, notify_channel_ref, enabled, updated_by_actor_id,
                     updated_by_actor_name, updated_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::numeric(4,3)[], %s, %s,
                        %s::uuid, %s, %s)
                ON CONFLICT (environment_id, label) DO UPDATE
                   SET service = EXCLUDED.service,
                       period = EXCLUDED.period,
                       amount = EXCLUDED.amount,
                       currency = EXCLUDED.currency,
                       alert_thresholds = EXCLUDED.alert_thresholds,
                       notify_channel_ref = EXCLUDED.notify_channel_ref,
                       enabled = EXCLUDED.enabled,
                       updated_at = CURRENT_TIMESTAMP,
                       updated_by_actor_id = EXCLUDED.updated_by_actor_id,
                       updated_by_actor_name = EXCLUDED.updated_by_actor_name,
                       updated_by_actor_key = EXCLUDED.updated_by_actor_key
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    budget["label"],
                    budget["service"],
                    budget["period"],
                    budget["amount"],
                    budget["currency"],
                    list(budget["alert_thresholds"]),
                    budget["notify_channel_ref"],
                    bool(budget["enabled"]),
                    actor_id,
                    actor_name,
                    actor_key,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if written is None:
        raise SlateInsightStoreError(
            "budget_not_found", f"Budget {budget['label']} could not be written."
        )
    return written


def delete_budget(
    db: _DbLike, *, tenant_id: str, environment_id: str, budget_id: str
) -> Dict[str, Any]:
    """Delete one budget and, by cascade, its alert history.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        budget_id: The budget to delete.

    Returns:
        The deleted row.

    Raises:
        SlateInsightStoreError: When no such budget exists.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            deleted = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_insight_budgets
                 WHERE tenant_id = %s::uuid AND environment_id = %s::uuid AND id = %s::uuid
                 RETURNING *
                """,
                (tenant_id, environment_id, budget_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if deleted is None:
        raise SlateInsightStoreError(
            "budget_not_found", f"No budget {budget_id} on this environment."
        )
    return deleted


def list_budget_alerts(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    budget_id: Optional[str] = None,
    unacknowledged_only: bool = False,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read budget alerts for one lane, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        budget_id: Restrict to one budget.
        unacknowledged_only: Only alerts nobody has acknowledged.
        limit: Maximum rows.

    Returns:
        Alert rows, newest first.
    """
    clauses = ["tenant_id = %s::uuid", "environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment_id]

    if budget_id:
        clauses.append("budget_id = %s::uuid")
        params.append(budget_id)
    if unacknowledged_only:
        clauses.append("acknowledged_at IS NULL")

    params.append(max(1, min(int(limit), 500)))
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT * FROM apiome.slate_insight_budget_alerts
             WHERE {' AND '.join(clauses)}
             ORDER BY at DESC
             LIMIT %s
            """,
            params,
        )


def record_budget_alert(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    alert: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Persist one budget alert.

    ``basis``, ``delivery_state`` and ``edge_attached`` are literals. Nothing dispatches, so an
    alert cannot claim to have arrived anywhere, and the basis says the amount behind it was
    modelled — which matters because "you have exceeded your budget" reads as a statement of fact.

    ``ON CONFLICT DO NOTHING`` against V190's ``UNIQUE (budget_id, threshold, period_start)``, so a
    scheduler retry re-firing the same threshold writes nothing and returns None. Without it the
    surface would show a wall of duplicates and teach operators to ignore the one that mattered.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        alert: The alert to write, from :func:`app.slate_insights.evaluate_budget`.

    Returns:
        The written row, or None when this threshold had already fired for this period.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_budget_alerts
                    (tenant_id, budget_id, environment_id, at, threshold, observed_amount,
                     budget_amount, currency, period_start, period_end, basis, delivery_state,
                     edge_attached)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s,
                        'modelled', 'not-dispatched', FALSE)
                ON CONFLICT (budget_id, threshold, period_start) DO NOTHING
                RETURNING *
                """,
                (
                    tenant_id,
                    alert["budget_id"],
                    environment_id,
                    _now(),
                    alert["threshold"],
                    alert["observed_amount"],
                    alert["budget_amount"],
                    alert["currency"],
                    alert["period_start"],
                    alert["period_end"],
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written


def acknowledge_budget_alert(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    alert_id: str,
    actor_name: str,
    actor_key: str,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Acknowledge one budget alert.

    All three acknowledgement columns are written together, because V190 pairs them by CHECK: an
    acknowledgement is a person and a time together, or neither.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        alert_id: The alert to acknowledge.
        actor_name: Display name of the acknowledging user.
        actor_key: Immutable identity of that user.
        actor_id: The user's id, when still present.

    Returns:
        The updated alert row.

    Raises:
        SlateInsightStoreError: When no such alert exists.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            updated = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_insight_budget_alerts
                   SET acknowledged_at = %s,
                       acknowledged_by_actor_id = %s::uuid,
                       acknowledged_by_actor_name = %s,
                       acknowledged_by_actor_key = %s
                 WHERE tenant_id = %s::uuid AND environment_id = %s::uuid AND id = %s::uuid
                 RETURNING *
                """,
                (
                    _now(),
                    actor_id,
                    actor_name,
                    actor_key,
                    tenant_id,
                    environment_id,
                    alert_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    if updated is None:
        raise SlateInsightStoreError(
            "alert_not_found", f"No budget alert {alert_id} on this environment."
        )
    return updated


# ─── Audit ───────────────────────────────────────────────────────────────────


def append_audit(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    actor_name: str,
    actor_key: str,
    subject_kind: str,
    summary: str,
    subject_id: Optional[str] = None,
    detail: Optional[Mapping[str, Any]] = None,
    actor_id: Optional[str] = None,
    actor_kind: str = "user",
) -> Dict[str, Any]:
    """Append one audit entry.

    The audit is the one table here with no retention: the record that a live tail was opened
    outlives the capture it took, which is the whole point of separating the two.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        actor_name: Display name of the actor.
        actor_key: Immutable identity of the actor.
        subject_kind: What was acted on.
        summary: One-sentence description, as shown to a reader.
        subject_id: Identifier of the subject, as text.
        detail: Structured detail of the change.
        actor_id: The user's id, when still present.
        actor_kind: ``user`` or ``automation``.

    Returns:
        The written audit row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_insight_audit
                    (tenant_id, environment_id, at, actor_id, actor_name, actor_key, actor_kind,
                     subject_kind, subject_id, summary, detail)
                VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    _now(),
                    actor_id,
                    actor_name,
                    actor_key,
                    actor_kind,
                    subject_kind,
                    subject_id,
                    summary,
                    json.dumps(_json(detail) or {}),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def list_audit(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    subject_kind: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read the audit trail for one lane, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        subject_kind: Restrict to one subject kind.
        limit: Maximum rows.

    Returns:
        Audit rows, newest first.
    """
    clauses = ["tenant_id = %s::uuid", "environment_id = %s::uuid"]
    params: List[Any] = [tenant_id, environment_id]

    if subject_kind:
        clauses.append("subject_kind = %s")
        params.append(subject_kind)

    params.append(max(1, min(int(limit), 1000)))
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT * FROM apiome.slate_insight_audit
             WHERE {' AND '.join(clauses)}
             ORDER BY at DESC
             LIMIT %s
            """,
            params,
        )
