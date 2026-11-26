"""Contract health rollup and verification analytics — PFX-6.3 (#6955): the database half.

Reads, per consumer ↔ provider pair of the tenant, what :func:`app.pact_health.fuse` combines:

* the pair's newest pact (its newest publication, as the Verification console reads it);
* the newest verification result of that pact version, whatever its age;
* the window's verification results, aggregated in SQL — runs, passes, verdict flips (``lag`` over
  the pair's results in recording order, so the first result of the window has no predecessor) and
  durations — per pair, or per pair and bucket for the trend;
* the stale-pact sweep's record (``pact_staleness``, PFX-6.2) and the open re-publish request;
* the newest firing in the window of each contract webhook for the pair, and whether it failed.

Nothing is written: health is computed on every read. Every query is scoped to the tenant; a
provider or consumer of another workspace is ``pacticipant-not-found``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .pact_health import (
    CODE_PAIR_NOT_FOUND,
    MAX_HEALTH_PAIRS,
    BucketCounts,
    HealthError,
    LatestVerdict,
    PactHealthCounts,
    PactHealthOverview,
    PactPairHealth,
    PactPairHealthDetail,
    PairSignals,
    StalenessFact,
    WebhookFact,
    fuse,
    metrics_from,
    parse_state,
    resolve_window,
    sort_key,
    total,
    trend_from,
)
from .pacticipant_store import get_pacticipant

__all__ = ["pair_health", "workspace_health"]

Pair = Tuple[str, str]
"""A pair key: ``(provider_id, consumer_id)``."""

# The newest publication of each pair: the one whose consumer version was recorded last.
_PAIRS_SELECT = """
    SELECT DISTINCT ON (p.provider_id, p.consumer_id)
           p.provider_id::text AS provider_id, p.consumer_id::text AS consumer_id,
           pr.slug AS provider_slug, pr.name AS provider_name,
           c.slug AS consumer_slug, c.name AS consumer_name,
           pv.id::text AS pact_version_id, pv.sha, v.number AS consumer_version,
           p.created_at AS published_at
    FROM apiome.pact_publication p
    JOIN apiome.pacticipant pr ON pr.id = p.provider_id
    JOIN apiome.pacticipant c ON c.id = p.consumer_id
    JOIN apiome.pact_version pv ON pv.id = p.pact_version_id
    JOIN apiome.pacticipant_version v ON v.id = p.consumer_version_id
    WHERE pr.tenant_id = %s::uuid AND c.tenant_id = %s::uuid
      AND pr.deleted_at IS NULL AND c.deleted_at IS NULL AND v.deleted_at IS NULL
"""

# The newest result of each listed pact version.
_LATEST_SELECT = """
    SELECT DISTINCT ON (r.pact_version_id)
           r.pact_version_id::text AS pact_version_id, r.success, r.number, r.created_at
    FROM apiome.verification_result r
    WHERE r.tenant_id = %s::uuid AND r.pact_version_id = ANY(%s::uuid[])
    ORDER BY r.pact_version_id, r.seq DESC
"""

# The window's results with each one's predecessor in the window, in recording order. Formatted
# with the extra filter of a one-provider or one-pair read.
_WINDOW_CTE = """
    WITH w AS (
        SELECT r.provider_id, r.consumer_id, r.success, r.duration_ms, r.created_at,
               lag(r.success) OVER (PARTITION BY r.provider_id, r.consumer_id ORDER BY r.seq) AS previous
        FROM apiome.verification_result r
        WHERE r.tenant_id = %s::uuid AND r.created_at >= %s::timestamptz AND r.created_at < %s::timestamptz{filter}
    )
"""

_COUNT_COLUMNS = """
           count(*) AS runs,
           count(*) FILTER (WHERE success) AS passed,
           count(previous) AS transitions,
           count(*) FILTER (WHERE previous IS NOT NULL AND previous <> success) AS flips,
           count(duration_ms) AS timed_runs,
           COALESCE(sum(duration_ms), 0) AS duration_total_ms
"""

_STALENESS_SELECT = """
    SELECT provider_id::text AS provider_id, consumer_id::text AS consumer_id, sha, stale,
           reference_at, threshold_hours, checked_at
    FROM apiome.pact_staleness
    WHERE tenant_id = %s::uuid{filter}
"""

_REQUEST_SELECT = """
    SELECT DISTINCT ON (provider_id, consumer_id)
           provider_id::text AS provider_id, consumer_id::text AS consumer_id, id::text AS id
    FROM apiome.pact_republish_request
    WHERE tenant_id = %s::uuid AND state IN ('requested', 'acknowledged'){filter}
    ORDER BY provider_id, consumer_id, seq DESC
"""

# The newest firing in the window of each webhook for each pair; dead-lettered = failed for good
# (the delivery log's `failure`).
_WEBHOOK_SELECT = """
    SELECT provider_id, consumer_id, count(*) AS webhooks,
           count(*) FILTER (WHERE delivery_status = 'dead_letter') AS failing
    FROM (
        SELECT DISTINCT ON (t.provider_id, t.consumer_id, t.webhook_id)
               t.provider_id::text AS provider_id, t.consumer_id::text AS consumer_id,
               e.status::text AS delivery_status
        FROM apiome.pact_triggered_webhook t
        JOIN apiome.push_webhook_delivery_events e ON e.id = t.delivery_event_id
        WHERE t.tenant_id = %s::uuid AND t.created_at >= %s::timestamptz AND t.created_at < %s::timestamptz{filter}
        ORDER BY t.provider_id, t.consumer_id, t.webhook_id, t.created_at DESC, t.id DESC
    ) newest
    GROUP BY provider_id, consumer_id
"""


def _iso(value: Any) -> Optional[str]:
    """A stored instant as ISO 8601, or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _counts(row: Mapping[str, Any]) -> BucketCounts:
    """The aggregate columns of a window row."""
    return BucketCounts(
        runs=int(row.get("runs") or 0),
        passed=int(row.get("passed") or 0),
        transitions=int(row.get("transitions") or 0),
        flips=int(row.get("flips") or 0),
        timed_runs=int(row.get("timed_runs") or 0),
        duration_total_ms=int(row.get("duration_total_ms") or 0),
    )


def _filter(alias: str, provider_id: Optional[str], consumer_id: Optional[str]) -> Tuple[str, List[Any]]:
    """The extra ``AND`` clauses (and parameters) of a one-provider or one-pair read.

    Args:
        alias: The table alias the columns belong to (``""`` for none).
        provider_id: Only this provider's rows.
        consumer_id: Only this consumer's rows.

    Returns:
        The SQL fragment and its parameters.
    """
    prefix = f"{alias}." if alias else ""
    sql, params = "", []
    if provider_id:
        sql += f" AND {prefix}provider_id = %s::uuid"
        params.append(provider_id)
    if consumer_id:
        sql += f" AND {prefix}consumer_id = %s::uuid"
        params.append(consumer_id)
    return sql, params


def _read_pairs(
    db: Any, tenant_id: str, provider_id: Optional[str], consumer_id: Optional[str]
) -> List[Mapping[str, Any]]:
    """The newest publication of each of the tenant's pairs (optionally one provider's or one pair's)."""
    sql, params = _filter("p", provider_id, consumer_id)
    query = _PAIRS_SELECT + sql + " ORDER BY p.provider_id, p.consumer_id, v.seq DESC"
    return list(db.execute_query(query, tuple([tenant_id, tenant_id] + params)) or [])


def _read_latest(db: Any, tenant_id: str, pact_version_ids: List[str]) -> Dict[str, LatestVerdict]:
    """The newest result of each pact version, by pact version id."""
    if not pact_version_ids:
        return {}
    rows = db.execute_query(_LATEST_SELECT, (tenant_id, pact_version_ids)) or []
    return {
        row["pact_version_id"]: LatestVerdict(
            success=bool(row["success"]), created_at=_iso(row.get("created_at")), number=int(row["number"])
        )
        for row in rows
    }


def _read_window(
    db: Any,
    tenant_id: str,
    since: datetime,
    until: datetime,
    provider_id: Optional[str],
    consumer_id: Optional[str],
) -> Dict[Pair, BucketCounts]:
    """The window's counts per pair."""
    sql, params = _filter("r", provider_id, consumer_id)
    query = (
        _WINDOW_CTE.format(filter=sql)
        + "SELECT provider_id::text AS provider_id, consumer_id::text AS consumer_id,"
        + _COUNT_COLUMNS
        + "FROM w GROUP BY provider_id, consumer_id"
    )
    rows = db.execute_query(query, tuple([tenant_id, since, until] + params)) or []
    return {(row["provider_id"], row["consumer_id"]): _counts(row) for row in rows}


def _read_buckets(
    db: Any,
    tenant_id: str,
    since: datetime,
    until: datetime,
    bucket_seconds: int,
    provider_id: str,
    consumer_id: str,
) -> Dict[int, BucketCounts]:
    """One pair's counts per bucket index (0 = the oldest bucket)."""
    sql, params = _filter("r", provider_id, consumer_id)
    query = (
        _WINDOW_CTE.format(filter=sql)
        + "SELECT floor(extract(epoch FROM (created_at - %s::timestamptz)) / %s)::int AS bucket,"
        + _COUNT_COLUMNS
        + "FROM w GROUP BY 1"
    )
    rows = db.execute_query(query, tuple([tenant_id, since, until] + params + [since, bucket_seconds])) or []
    return {int(row["bucket"]): _counts(row) for row in rows}


def _read_staleness(
    db: Any, tenant_id: str, provider_id: Optional[str], consumer_id: Optional[str]
) -> Dict[Pair, StalenessFact]:
    """The sweep's record per pair."""
    sql, params = _filter("", provider_id, consumer_id)
    rows = db.execute_query(_STALENESS_SELECT.format(filter=sql), tuple([tenant_id] + params)) or []
    facts: Dict[Pair, StalenessFact] = {}
    for row in rows:
        stale = bool(row["stale"])
        stale_since = None
        reference = row.get("reference_at")
        if stale and isinstance(reference, datetime):
            stale_since = (reference + timedelta(hours=int(row["threshold_hours"]))).isoformat()
        facts[(row["provider_id"], row["consumer_id"])] = StalenessFact(
            sha=str(row["sha"]), stale=stale, stale_since=stale_since, checked_at=_iso(row.get("checked_at"))
        )
    return facts


def _read_requests(db: Any, tenant_id: str, provider_id: Optional[str], consumer_id: Optional[str]) -> Dict[Pair, str]:
    """The open re-publish request id per pair."""
    sql, params = _filter("", provider_id, consumer_id)
    rows = db.execute_query(_REQUEST_SELECT.format(filter=sql), tuple([tenant_id] + params)) or []
    return {(row["provider_id"], row["consumer_id"]): row["id"] for row in rows}


def _read_webhooks(
    db: Any,
    tenant_id: str,
    since: datetime,
    until: datetime,
    provider_id: Optional[str],
    consumer_id: Optional[str],
) -> Dict[Pair, WebhookFact]:
    """The webhook firings per pair."""
    sql, params = _filter("t", provider_id, consumer_id)
    rows = db.execute_query(_WEBHOOK_SELECT.format(filter=sql), tuple([tenant_id, since, until] + params)) or []
    return {
        (row["provider_id"], row["consumer_id"]): WebhookFact(
            webhooks=int(row["webhooks"] or 0), failing=int(row["failing"] or 0)
        )
        for row in rows
    }


def _health(
    pair_row: Mapping[str, Any],
    latest: Dict[str, LatestVerdict],
    windows: Dict[Pair, BucketCounts],
    staleness: Dict[Pair, StalenessFact],
    requests: Dict[Pair, str],
    webhooks: Dict[Pair, WebhookFact],
) -> Tuple[PactPairHealth, BucketCounts]:
    """One pair's health from what was read, and its window counts."""
    key = (pair_row["provider_id"], pair_row["consumer_id"])
    verdict = latest.get(pair_row["pact_version_id"])
    counts = windows.get(key, BucketCounts())
    signals = PairSignals(
        pact_version_sha=str(pair_row["sha"]),
        latest=verdict,
        counts=counts,
        staleness=staleness.get(key),
        republish_request_id=requests.get(key),
        webhooks=webhooks.get(key, WebhookFact()),
    )
    state, components, metrics = fuse(signals)
    health = PactPairHealth(
        provider=pair_row["provider_slug"],
        provider_name=pair_row["provider_name"],
        consumer=pair_row["consumer_slug"],
        consumer_name=pair_row["consumer_name"],
        pact_version_sha=str(pair_row["sha"]),
        consumer_version=str(pair_row["consumer_version"]),
        published_at=_iso(pair_row.get("published_at")),
        state=state,
        components=components,
        metrics=metrics,
        latest_success=verdict.success if verdict else None,
        latest_verified_at=verdict.created_at if verdict else None,
        republish_request_id=signals.republish_request_id,
    )
    return health, counts


def _read_all(
    db: Any,
    tenant_id: str,
    since: datetime,
    until: datetime,
    provider_id: Optional[str],
    consumer_id: Optional[str],
) -> List[Tuple[PactPairHealth, BucketCounts]]:
    """Every matching pair's health and window counts, unsorted."""
    pairs = _read_pairs(db, tenant_id, provider_id, consumer_id)
    if not pairs:
        return []
    latest = _read_latest(db, tenant_id, [row["pact_version_id"] for row in pairs])
    windows = _read_window(db, tenant_id, since, until, provider_id, consumer_id)
    staleness = _read_staleness(db, tenant_id, provider_id, consumer_id)
    requests = _read_requests(db, tenant_id, provider_id, consumer_id)
    webhooks = _read_webhooks(db, tenant_id, since, until, provider_id, consumer_id)
    return [_health(row, latest, windows, staleness, requests, webhooks) for row in pairs]


def workspace_health(
    db: Any,
    tenant_id: str,
    *,
    window: Optional[str] = None,
    provider_ref: Optional[str] = None,
    consumer_ref: Optional[str] = None,
    state: Optional[str] = None,
    now: Optional[datetime] = None,
) -> PactHealthOverview:
    """The health of every pair of the workspace (or one provider's, one consumer's) over a window.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        window: ``7d``, ``30d`` or ``90d`` (``None`` for the default).
        provider_ref: Only this provider's pairs (handle, id or name).
        consumer_ref: Only this consumer's pairs.
        state: Only pairs in this state; the counts still cover every matching pair.
        now: The current time (for tests).

    Returns:
        The overview, worst pairs first, at most :data:`app.pact_health.MAX_HEALTH_PAIRS` of them.

    Raises:
        HealthError: ``pact-health-window-invalid`` or ``pact-health-state-invalid``.
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    current = now or datetime.now(timezone.utc)
    spec, since, until = resolve_window(window, current)
    wanted = parse_state(state)
    provider_id = get_pacticipant(db, tenant_id, provider_ref).id if provider_ref else None
    consumer_id = get_pacticipant(db, tenant_id, consumer_ref).id if consumer_ref else None
    rows = _read_all(db, tenant_id, since, until, provider_id, consumer_id)
    states = [health.state for health, _ in rows]
    counts = PactHealthCounts(
        pairs=len(rows),
        healthy=states.count("healthy"),
        degraded=states.count("degraded"),
        failing=states.count("failing"),
        unknown=states.count("unknown"),
    )
    matching = sorted(
        (item for item in rows if wanted is None or item[0].state == wanted), key=lambda i: sort_key(i[0])
    )
    listed = matching[:MAX_HEALTH_PAIRS]
    return PactHealthOverview(
        window=spec.key,
        since=since.isoformat(),
        until=until.isoformat(),
        bucket_days=spec.bucket_days,
        generated_at=current.isoformat(),
        counts=counts,
        totals=metrics_from(total([window_counts for _, window_counts in listed])),
        pairs=[health for health, _ in listed],
        truncated=len(matching) > MAX_HEALTH_PAIRS,
        omitted_pairs=max(0, len(matching) - MAX_HEALTH_PAIRS),
    )


def pair_health(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    consumer_ref: str,
    *,
    window: Optional[str] = None,
    now: Optional[datetime] = None,
) -> PactPairHealthDetail:
    """One pair's health and its trend over a window.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider (handle, id or name).
        consumer_ref: The consumer.
        window: ``7d``, ``30d`` or ``90d`` (``None`` for the default).
        now: The current time (for tests).

    Returns:
        The pair's health and one trend bucket per bucket of the window.

    Raises:
        HealthError: ``pact-health-window-invalid``; ``pact-health-pair-not-found`` when the consumer
            has published no pact for the provider.
        PacticipantValidationError: ``pacticipant-not-found``.
    """
    current = now or datetime.now(timezone.utc)
    spec, since, until = resolve_window(window, current)
    provider = get_pacticipant(db, tenant_id, provider_ref)
    consumer = get_pacticipant(db, tenant_id, consumer_ref)
    rows = _read_all(db, tenant_id, since, until, provider.id, consumer.id)
    if not rows:
        raise HealthError(CODE_PAIR_NOT_FOUND, f"'{consumer.slug}' has published no pact for '{provider.slug}'")
    health, _ = rows[0]
    buckets = _read_buckets(db, tenant_id, since, until, spec.bucket_days * 86400, provider.id, consumer.id)
    return PactPairHealthDetail(
        window=spec.key,
        since=since.isoformat(),
        until=until.isoformat(),
        bucket_days=spec.bucket_days,
        generated_at=current.isoformat(),
        pair=health,
        trend=trend_from(spec, since, buckets),
    )
