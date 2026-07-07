"""Manual MCP endpoint discovery: trigger an async job and run the Epic-2 client.

V2-MCP-17.2 / MCAT-3.2 (#3664). ``POST /v1/mcp/{tenant_slug}/endpoints/{id}/discover``
creates an ``mcp_discovery_jobs`` row (``trigger='manual'``), then — out of band — runs
the MCP client (transport → handshake → paginated discovery → normalize), fingerprints the
surface, diffs it against the previous snapshot via the canonical surface diff engine
(:func:`app.mcp_client.diff.diff_surfaces`, MCAT-4.2), and persists a new
``mcp_endpoint_versions`` row when the surface changed (or version 1 on first run).

Version-on-change (V2-MCP-18.3 / MCAT-4.3, #3670): a re-discovery whose
``surface_fingerprint`` matches the current version creates **no** new version — it only
stamps ``last_discovered_at`` — so an unchanged server never spams the history. When the
fingerprint differs, exactly one new version is inserted (``version_seq+1``) with its
capability items and the ``previous → new`` diff persisted as ``mcp_version_changes`` rows,
and ``mcp_endpoints.current_version_id`` is advanced to it — all in one transaction.

Date/time tagging (V2-MCP-18.4 / MCAT-4.4, #3671): each new version is stamped with a
human-readable, per-endpoint-unique ``version_tag`` (e.g. ``2026-06-26T14:03Z``) derived from
its discovery time, so version history is navigable by date/time. The tag is carried in the
job ``result`` payload (``version_tag``) on both the changed and unchanged paths.

This mirrors the submit→poll shape of :mod:`spec_import_engine`: the route returns a job
reference immediately and the caller polls the job for the terminal state. Unlike the spec
importer, discovery runs entirely in-process (the MCP client is async Python), so there is no
subprocess — the network/normalize work runs as an asyncio task and the (synchronous,
psycopg2) DB writes are pushed to a worker thread.

De-duplication: concurrent discover requests for the same endpoint coalesce onto one job.
:meth:`Database.enqueue_mcp_discovery_job` makes the "is one already active?" check atomic via
a per-endpoint advisory lock; this module additionally short-circuits the in-process task so a
de-duplicated request never starts a second run.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .database import db
from .mcp_client import (
    DiscoveryError,
    DiscoveryErrorCode,
    DiscoverySurface,
    ServerInfo,
    StreamableHttpTransport,
    classify_exception,
    diff_surfaces,
    discover_listings,
    initialize_session,
)
from .mcp_client.diff import ITEM_TYPE_SERVER, SurfaceDiff
from .mcp_client.resilience import BudgetExceededError, TimeBudget
from .mcp_client.transport_meta import TransportMetadata
from .mcp_credentials import load_endpoint_auth_headers

logger = logging.getLogger(__name__)

# Wall-clock ceiling for one discovery run (handshake + all pagination). Generous but
# bounded so a slow/hostile server cannot pin the task forever.
_DISCOVERY_BUDGET_SECONDS = 120.0

# The result of one discovery run: the normalized surface plus the host/transport metadata observed
# from the handshake connection (``None`` when unavailable — e.g. a legacy test runner). Kept as a
# pair rather than folded into the surface because transport facts are volatile (they must not feed
# the surface fingerprint) and persist to the *endpoint*, not the immutable version snapshot.
DiscoveryOutcome = Tuple[DiscoverySurface, Optional[TransportMetadata]]

# Test seam: monkeypatch to an async callable(endpoint_row, headers) -> DiscoverySurface | outcome
# to bypass the real network. When None, :func:`_run_mcp_client` performs the live discovery. A
# runner may return either a bare :class:`DiscoverySurface` (legacy) or a ``DiscoveryOutcome`` pair;
# :func:`_invoke_discovery` normalizes both.
_discovery_runner: Optional[
    Callable[[Dict[str, Any], Dict[str, str]], Awaitable[Any]]
] = None


def _utcnow() -> datetime:
    """Timezone-aware now(); isolated so tests can monkeypatch the clock."""
    return datetime.now(timezone.utc)


async def _run_mcp_client(
    endpoint: Dict[str, Any], headers: Dict[str, str]
) -> DiscoveryOutcome:
    """Connect to the endpoint, run the handshake + discovery, and normalize the surface.

    Alongside the capability surface, the host/transport facts the handshake connection reveals —
    host, TLS certificate summary, notable response headers, connect timing — are read off the
    transport (:attr:`StreamableHttpTransport.observed_transport`, V2-MCP-34.1) without any extra
    network call, and returned for the caller to persist on the endpoint.

    Args:
        endpoint: The ``mcp_endpoints`` row (``endpoint_url`` is used as the target).
        headers: Auth headers to attach to every request (empty when the endpoint has
            no usable credentials).

    Returns:
        ``(surface, transport_metadata)``: the canonical :class:`DiscoverySurface` and the observed
        :class:`TransportMetadata` (``None`` when the transport captured nothing).
    """
    url = str(endpoint["endpoint_url"])
    budget = TimeBudget(total_seconds=_DISCOVERY_BUDGET_SECONDS)
    transport = StreamableHttpTransport(url, headers=dict(headers))
    try:
        initialize = await initialize_session(transport)
        listings = await discover_listings(transport, initialize.capabilities, budget=budget)
        transport_meta = transport.observed_transport
    finally:
        await transport.aclose()
    return DiscoverySurface.from_discovery(initialize, listings), transport_meta


async def _invoke_discovery(
    endpoint: Dict[str, Any], headers: Dict[str, str]
) -> DiscoveryOutcome:
    """Dispatch to the test runner when installed, else the live MCP client.

    Normalizes both runner shapes: a live/tuple result is returned as-is, while a legacy runner
    that yields a bare :class:`DiscoverySurface` is paired with ``None`` transport metadata.
    """
    if _discovery_runner is not None:
        outcome = await _discovery_runner(endpoint, headers)
    else:
        outcome = await _run_mcp_client(endpoint, headers)
    if isinstance(outcome, tuple):
        return outcome
    return outcome, None


# ---------------------------------------------------------------------------
# Diffing (Epic-4): the canonical surface diff engine (MCAT-4.2, #3669) computes
# the previous → new change set persisted as ``mcp_version_changes`` rows.
# ---------------------------------------------------------------------------


def reconstruct_surface(
    version_row: Dict[str, Any], capability_rows: List[Dict[str, Any]]
) -> DiscoverySurface:
    """Rebuild a version's :class:`DiscoverySurface` from its persisted rows.

    The diff engine compares two normalized surfaces, but a stored version lives in the
    store as a ``mcp_endpoint_versions`` row (the surface-level identity fields) plus its
    ``mcp_capability_items`` children. This pairs them back into a surface so both the
    ``previous → new`` version-creation diff and the on-demand compare API (MCAT-4.5)
    are computed by the *same* engine, keeping a single source of truth for "what changed".

    Args:
        version_row: The snapshot's ``mcp_endpoint_versions`` row.
        capability_rows: That snapshot's ``mcp_capability_items`` rows.

    Returns:
        The reconstructed :class:`DiscoverySurface`.
    """
    return DiscoverySurface.from_rows(
        capability_rows,
        protocol_version=version_row.get("protocol_version"),
        server_info=ServerInfo(
            name=version_row.get("server_name"),
            title=version_row.get("server_title"),
            version=version_row.get("server_version"),
        ),
        capabilities=version_row.get("capabilities") or {},
        instructions=version_row.get("instructions"),
    )


def compare_endpoint_versions(
    base_version: Dict[str, Any], target_version: Dict[str, Any]
) -> SurfaceDiff:
    """Compute the on-demand structured diff between two stored version snapshots (MCAT-4.5).

    Reconstructs each snapshot's surface from its persisted rows (loading the
    ``mcp_capability_items`` children for both) and runs the canonical
    :func:`app.mcp_client.diff.diff_surfaces` engine over them. Because the engine compares
    the two surfaces *directly* — not by chaining adjacent step-diffs — the result is exact
    for any pair, adjacent or arbitrarily distant. The caller is responsible for normalizing
    the argument order (older→newer) so "added"/"removed" read in the natural direction.

    Args:
        base_version: The earlier / "from" ``mcp_endpoint_versions`` row.
        target_version: The later / "to" ``mcp_endpoint_versions`` row.

    Returns:
        The :class:`SurfaceDiff` between the two surfaces; empty when they are identical.
    """
    base_surface = reconstruct_surface(
        base_version, db.get_mcp_capability_items(str(base_version["id"]))
    )
    target_surface = reconstruct_surface(
        target_version, db.get_mcp_capability_items(str(target_version["id"]))
    )
    return diff_surfaces(base_surface, target_surface)


def compute_version_change_rows(
    previous: Optional[Dict[str, Any]],
    surface: DiscoverySurface,
) -> List[Dict[str, Any]]:
    """Diff a freshly discovered surface against the previous version, as change rows.

    Delegates to :func:`app.mcp_client.diff.diff_surfaces`, so the comparison runs over
    each surface's *semantic projection* (the same fields that feed the fingerprint): a
    capability only in the new surface is ``added``, one only in the previous version is
    ``removed``, and one in both with a differing projection is ``modified`` (carrying a
    per-field before/after breakdown). Server-metadata changes (server version, protocol
    version, instructions, …) are recorded too. The rows map one-to-one onto
    ``mcp_version_changes`` (``version_id`` is assigned by the DB at insert time, so it is
    left ``None`` here).

    On the **first** version there is no prior surface to compare against, so every
    capability is emitted as ``added`` and the synthetic "server metadata changed from
    null" rows that an empty baseline would otherwise produce are suppressed — the first
    version's change record is exactly the set of capabilities it introduces.

    Args:
        previous: The prior ``mcp_endpoint_versions`` row, or ``None`` on the first run.
        surface: The newly discovered, normalized surface.

    Returns:
        A list of change rows; empty when nothing changed at the surface level.
    """
    if previous is None:
        base = DiscoverySurface()
    else:
        previous_items = db.get_mcp_capability_items(str(previous["id"]))
        base = reconstruct_surface(previous, previous_items)

    rows = diff_surfaces(base, surface).to_change_rows(None)
    if previous is None:
        rows = [row for row in rows if row["item_type"] != ITEM_TYPE_SERVER]
    return rows


# ---------------------------------------------------------------------------
# Persistence — runs in a worker thread (psycopg2 is synchronous and blocking).
# ---------------------------------------------------------------------------


def _capture_mcp_version_score(version_id: str, surface: DiscoverySurface) -> None:
    """Best-effort: lint, score, and persist a quality score for a freshly created version.

    Captured right after a new ``mcp_endpoint_versions`` snapshot is committed so every
    discovered version carries a stored score/grade for the catalog and version-history views,
    the MCP analogue of :func:`app.spec_import_engine._capture_version_quality_score`. The
    surface is already in hand (just persisted), so scoring is pure and in-process — no
    reconstruction from the DB. Strictly best-effort: the version row is already committed, so
    any failure here just leaves the score for an on-demand re-lint (MCAT-7.5) to fill and
    never affects the discovery outcome. Imported lazily to keep the scoring layer off the
    discovery import path.

    Args:
        version_id: The just-persisted snapshot to score.
        surface: The normalized surface that snapshot was built from.
    """
    try:
        from .mcp_score import score_mcp_surface

        result = score_mcp_surface(surface)
        db.set_mcp_version_score(
            version_id,
            score=result.score,
            grade=result.grade,
            report=result.report_dict(),
            report_fingerprint=result.report_fingerprint,
        )
    except Exception:  # noqa: BLE001 - capture is strictly best-effort
        logger.warning(
            "Failed to capture MCP quality score for version %s",
            version_id,
            exc_info=True,
        )


def _persist_transport_metadata(
    endpoint_id: str,
    transport_meta: Optional[TransportMetadata],
    observed_at: datetime,
) -> None:
    """Best-effort: store the latest observed host/transport facts on the endpoint (V2-MCP-34.1).

    Recorded on every successful discovery — changed *or* unchanged — because the facts are volatile
    (connect timing, a rotated cert or header) and endpoint-level, so they refresh independently of
    whether the capability surface produced a new immutable version snapshot. Strictly best-effort:
    a missing observation (``None``) is skipped, and a write failure is logged and swallowed so it
    never turns a completed discovery into a failure (mirrors :func:`_capture_mcp_version_score`).

    Args:
        endpoint_id: The endpoint whose latest transport observation is being stored.
        transport_meta: The captured metadata, or ``None`` when the transport observed nothing.
        observed_at: When the observation was taken (the discovery run time).
    """
    if transport_meta is None:
        return
    try:
        db.set_mcp_endpoint_transport_metadata(
            endpoint_id, transport_meta.to_dict(), observed_at=observed_at
        )
    except Exception:  # noqa: BLE001 - capture is strictly best-effort, never blocks the job
        logger.warning(
            "Failed to persist MCP transport metadata for endpoint %s",
            endpoint_id,
            exc_info=True,
        )


def _surface_counts(surface: DiscoverySurface) -> Dict[str, int]:
    """Per-kind capability tallies for a discovered surface.

    Recorded on the job ``result`` (``counts``) so the import UI can show a small
    "what was discovered" summary on completion. ``total`` is the sum across kinds.
    """
    tool = len(surface.tools)
    resource = len(surface.resources)
    resource_template = len(surface.resource_templates)
    prompt = len(surface.prompts)
    return {
        "tool": tool,
        "resource": resource,
        "resource_template": resource_template,
        "prompt": prompt,
        "total": tool + resource + resource_template + prompt,
    }


def _persist_outcome(
    job_id: str,
    endpoint: Dict[str, Any],
    surface: DiscoverySurface,
    discovered_at: datetime,
    transport_meta: Optional[TransportMetadata] = None,
) -> Dict[str, Any]:
    """Fingerprint/diff the surface, persist a version when changed, and finish the job.

    Synchronous (DB-bound); invoked via :func:`asyncio.to_thread`. Returns the job's
    ``result`` payload (also written to the job row) so the caller can log it. The observed
    host/transport metadata (V2-MCP-34.1), when present, is refreshed on the endpoint on every
    successful run regardless of whether the surface changed.
    """
    endpoint_id = str(endpoint["id"])
    fingerprint = surface.fingerprint()

    # Refresh the endpoint's latest host/transport observation (best-effort; changed or not).
    _persist_transport_metadata(endpoint_id, transport_meta, discovered_at)

    # Per-kind capability tallies for the job result, so the UI can show a small
    # "what was discovered" summary on completion (e.g. "3 tools · 2 resources").
    counts = _surface_counts(surface)

    previous = db.get_latest_mcp_endpoint_version(endpoint_id)
    unchanged = previous is not None and previous.get("surface_fingerprint") == fingerprint

    if unchanged:
        # Same surface as the last snapshot — no new version, keep current_version_id.
        version_id = str(previous["id"])
        version_seq = int(previous["version_seq"])
        db.touch_mcp_endpoint_discovery(
            endpoint_id, status="unchanged", discovered_at=discovered_at
        )
        result = {
            "version_id": version_id,
            "version_seq": version_seq,
            "version_tag": previous.get("version_tag"),
            "changed": False,
            "fingerprint": fingerprint,
            "counts": counts,
        }
        db.finish_mcp_discovery_job(job_id, "completed", result=result)
        return result

    change_rows = compute_version_change_rows(previous, surface)

    version_row = surface.to_version_row()
    persisted = db.record_mcp_discovery_version(
        endpoint_id,
        version_row=version_row,
        capability_rows=surface.to_capability_rows(None),
        change_rows=change_rows,
        discovered_at=discovered_at,
    )
    # Auto-capture the lint score for the new snapshot (best-effort; never blocks the job).
    _capture_mcp_version_score(persisted["version_id"], surface)
    result = {
        "version_id": persisted["version_id"],
        "version_seq": persisted["version_seq"],
        "version_tag": persisted.get("version_tag"),
        "changed": True,
        "change_count": len(change_rows),
        "fingerprint": fingerprint,
        "counts": counts,
    }
    db.finish_mcp_discovery_job(job_id, "completed", result=result)
    return result


def _retry_after_from_error(error: DiscoveryError) -> Optional[float]:
    """Extract a server ``Retry-After`` (seconds) from a rate-limited discovery error.

    Only :attr:`DiscoveryErrorCode.RATE_LIMITED` failures carry one (parsed from the 429
    response in the transport); every other failure returns ``None`` so the backoff falls
    back to its own exponential schedule.
    """
    if error.code is not DiscoveryErrorCode.RATE_LIMITED:
        return None
    value = error.detail.get("retry_after")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _persist_failure(
    job_id: str,
    endpoint: Dict[str, Any],
    error: DiscoveryError,
    discovered_at: datetime,
) -> None:
    """Record a failed run on the job and accumulate the endpoint's failure state (synchronous).

    The endpoint side goes through :meth:`Database.record_mcp_discovery_failure` (MCAT-5.3): the
    consecutive-failure counter is incremented, an exponential backoff anchor is written (honouring
    a 429 ``Retry-After``), and the endpoint is quarantined once it crosses the configured
    threshold. ``last_discovery_status`` is stamped with the *specific* error code (e.g.
    ``connect_error``, ``rate_limited``) so the failure mode is visible via the status API, not just
    a generic "failed". A quarantine transition emits a one-shot event.
    """
    from .config import settings

    endpoint_id = str(endpoint["id"])
    outcome = db.record_mcp_discovery_failure(
        endpoint_id,
        discovered_at=discovered_at,
        status=error.code.value,
        backoff_base_seconds=float(settings.mcp_discovery_backoff_base_seconds),
        backoff_max_seconds=float(settings.mcp_discovery_backoff_max_seconds),
        quarantine_threshold=int(settings.mcp_discovery_quarantine_threshold),
        quarantine_reason=f"{error.code.value}: {error.message}"[:500],
        retry_after_seconds=_retry_after_from_error(error),
    )
    db.finish_mcp_discovery_job(
        job_id,
        "failed",
        result={"error": error.as_dict()},
        error=f"{error.code}: {error.message}"[:2000],
    )
    _log_failure_outcome(endpoint, error, outcome)


def _log_failure_outcome(
    endpoint: Dict[str, Any],
    error: DiscoveryError,
    outcome: Optional[Dict[str, Any]],
) -> None:
    """Emit the failure/quarantine event for one failed discovery run.

    A quarantine *transition* (``newly_quarantined``) is logged at WARNING as the auto-disable
    event the ticket calls for; an ongoing failure is logged at INFO with its backoff so the
    sweep's pacing is observable. Both carry the endpoint id/tenant and the specific error code so
    the structured-log observability layer (RC1-3.2) surfaces them. Best-effort: a logging issue
    never propagates back into the discovery run.
    """
    if outcome is None:
        return
    endpoint_id = str(endpoint.get("id"))
    tenant_id = str(endpoint.get("tenant_id"))
    failures = outcome.get("consecutive_failures")
    backoff = outcome.get("backoff_seconds")
    if outcome.get("newly_quarantined"):
        logger.warning(
            "mcp endpoint quarantined: endpoint=%s tenant=%s consecutive_failures=%s "
            "reason=%s (auto-disabled from the re-discovery sweep until it recovers)",
            endpoint_id,
            tenant_id,
            failures,
            error.code.value,
        )
    else:
        logger.info(
            "mcp endpoint discovery failed: endpoint=%s tenant=%s consecutive_failures=%s "
            "error=%s next_retry_in=%.0fs",
            endpoint_id,
            tenant_id,
            failures,
            error.code.value,
            float(backoff) if backoff is not None else 0.0,
        )


async def _drive_discovery_job(job_id: str, endpoint: Dict[str, Any]) -> None:
    """Run one discovery job end-to-end: running → (client+persist) → completed/failed.

    Never raises: any failure is classified into the stable discovery error taxonomy and
    recorded on the job so a poller always observes a terminal state.
    """
    endpoint_id = str(endpoint["id"])
    running = await asyncio.to_thread(db.mark_mcp_discovery_job_running, job_id)
    if running is None:
        # The job was no longer queued (already started, or vanished) — nothing to do.
        logger.debug("discovery job=%s was not queued; skipping run", job_id)
        return

    try:
        headers = await asyncio.to_thread(load_endpoint_auth_headers, endpoint_id)
        surface, transport_meta = await _invoke_discovery(endpoint, headers)
    except Exception as exc:  # noqa: BLE001 - mapped to the stable error taxonomy below
        error = classify_exception(exc)
        logger.warning(
            "discovery job=%s endpoint=%s failed: %s", job_id, endpoint_id, error.to_record()
        )
        try:
            await asyncio.to_thread(
                _persist_failure, job_id, endpoint, error, _utcnow()
            )
        except Exception:  # noqa: BLE001 - last-resort guard so the task never crashes
            logger.exception("failed to record discovery failure job=%s", job_id)
        return

    try:
        result = await asyncio.to_thread(
            _persist_outcome, job_id, endpoint, surface, _utcnow(), transport_meta
        )
        logger.info(
            "discovery job=%s endpoint=%s completed: %s",
            job_id,
            endpoint_id,
            json.dumps(result),
        )
    except Exception as exc:  # noqa: BLE001 - persistence failure still terminates the job
        error = classify_exception(exc)
        logger.exception("discovery persistence failed job=%s", job_id)
        try:
            await asyncio.to_thread(
                _persist_failure, job_id, endpoint, error, _utcnow()
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to record discovery persistence failure job=%s", job_id)


async def enqueue_discovery_job(
    tenant_id: str, endpoint: Dict[str, Any], *, trigger: str = "manual"
) -> Tuple[Dict[str, Any], bool]:
    """Create (or coalesce onto) a discovery job for an endpoint *without* starting the run.

    The enqueue half of the pipeline, split out so callers that bound or schedule the run
    themselves — the periodic sweep drives jobs under a concurrency cap + per-endpoint timeout
    (MCAT-5.2) — can reuse the same de-duplicating job creation the manual path uses.

    De-duplication lives in :meth:`Database.enqueue_mcp_discovery_job`: a per-endpoint advisory
    lock makes the "is one already active?" check atomic, so if a job is already queued/running
    for the endpoint (a prior sweep tick's run still in flight, or a concurrent manual run) the
    existing row is returned and no second job is created.

    Args:
        tenant_id: Owning tenant (stamped on the job for scoped reads).
        endpoint: The already tenant-validated ``mcp_endpoints`` row to discover.
        trigger: How the run was initiated — ``manual`` (default) or ``sweep``. Recorded on
            the job row so its provenance is auditable.

    Returns:
        ``(job_row, deduplicated)`` — when ``deduplicated`` is ``True`` an already-active job
        was returned; otherwise a fresh ``queued`` job was created (and is the caller's to run).
    """
    endpoint_id = str(endpoint["id"])
    enqueued = await asyncio.to_thread(
        db.enqueue_mcp_discovery_job, endpoint_id, tenant_id, trigger
    )
    return enqueued["job"], bool(enqueued["deduplicated"])


async def run_discovery_job(
    job_id: str,
    endpoint: Dict[str, Any],
    *,
    timeout_seconds: Optional[float] = None,
) -> None:
    """Drive one enqueued job to a terminal state, bounded by an optional wall-clock timeout.

    Wraps :func:`_drive_discovery_job` (which already maps every internal failure into the
    stable discovery-error taxonomy and never raises) with a per-endpoint timeout for the
    sweep (MCAT-5.2). When the whole run — auth load, handshake, pagination, persist — outlasts
    ``timeout_seconds`` the drive is cancelled and the job/endpoint are recorded as a
    ``budget_exceeded`` failure, so a poller always observes a terminal state and the endpoint's
    cadence anchor advances (``last_discovered_at`` is stamped) rather than the endpoint staying
    perpetually due. The discovery client carries its own ~120s network budget
    (``_DISCOVERY_BUDGET_SECONDS``); this timeout is the coarser backstop that also covers the
    non-network phases, so keep it above that network budget.

    Args:
        job_id: The queued job to run (from :func:`enqueue_discovery_job`).
        endpoint: The ``mcp_endpoints`` row being discovered.
        timeout_seconds: Wall-clock ceiling for the whole run; ``None`` or non-positive means
            unbounded (the network budget still applies inside the client).
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        await _drive_discovery_job(job_id, endpoint)
        return

    endpoint_id = str(endpoint["id"])
    try:
        await asyncio.wait_for(
            _drive_discovery_job(job_id, endpoint), timeout=timeout_seconds
        )
    except (asyncio.TimeoutError, TimeoutError):
        # The run overran its per-endpoint budget. Cancellation has already unwound the drive;
        # classify this as a budget timeout and record a terminal failure so the job never hangs
        # in `running` and the endpoint is not immediately due again.
        error = classify_exception(
            BudgetExceededError(elapsed=timeout_seconds, total=timeout_seconds)
        )
        logger.warning(
            "discovery job=%s endpoint=%s timed out after %.1fs (per-endpoint budget)",
            job_id,
            endpoint_id,
            timeout_seconds,
        )
        try:
            await asyncio.to_thread(
                _persist_failure, job_id, endpoint, error, _utcnow()
            )
        except Exception:  # noqa: BLE001 - last-resort guard so the sweep task never crashes
            logger.exception(
                "failed to record discovery timeout failure job=%s", job_id
            )


async def trigger_discovery(
    tenant_id: str, endpoint: Dict[str, Any], *, trigger: str = "manual"
) -> Tuple[Dict[str, Any], bool]:
    """Enqueue a discovery job for an endpoint and start it (in the background) unless de-duplicated.

    The submit→poll entry point for the manual ``POST .../discover`` route (``trigger='manual'``):
    it enqueues the job via :func:`enqueue_discovery_job` and, when a fresh job was created,
    schedules the run as a detached task so the route can return the job reference immediately.
    The periodic sweep does *not* use this (it needs bounded concurrency + per-endpoint timeouts,
    MCAT-5.2); it enqueues with :func:`enqueue_discovery_job` and drives with
    :func:`run_discovery_job` itself.

    Args:
        tenant_id: Owning tenant (stamped on the job for scoped reads).
        endpoint: The already tenant-validated ``mcp_endpoints`` row to discover.
        trigger: How the run was initiated — ``manual`` (default) or ``sweep``. Recorded
            on the job row so its provenance is auditable.

    Returns:
        ``(job_row, deduplicated)`` — when ``deduplicated`` is ``True`` an already-active
        job was returned and no new run was started; otherwise a fresh job was created and
        its discovery task scheduled.
    """
    job, deduplicated = await enqueue_discovery_job(tenant_id, endpoint, trigger=trigger)
    if not deduplicated:
        asyncio.create_task(_drive_discovery_job(str(job["id"]), endpoint))
    return job, deduplicated
