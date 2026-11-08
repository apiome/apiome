"""Periodic MCP endpoint re-discovery sweep — cadence-driven, bounded executor (MCAT-5.1/5.2).

The MCP catalog's manual discovery (MCAT-3.2, :mod:`mcp_discovery_engine`) re-handshakes a
single endpoint on demand. This module is the *periodic* counterpart: a background async loop
(wired in :mod:`app.main`) that, on every tick, asks the database for the endpoints whose
discovery cadence has elapsed and runs a fresh discovery for each, mirroring the repository
auto-refresh sweep (:mod:`repository_refresh_sweep`).

Due-selection (:meth:`Database.list_due_mcp_endpoints`) does all the policy work: it returns
only live (``deleted_at IS NULL``), enabled endpoints whose ``last_discovered_at`` is older than
their effective cadence — the per-endpoint ``discovery_cadence_seconds`` override, or the global
``mcp_discovery_default_cadence_seconds`` when the endpoint has none. Endpoints are returned
oldest-first so attention is spread fairly and a never-discovered endpoint is picked up promptly.

Each due endpoint runs through the *same* discovery → diff → version pipeline the manual route
uses (MCAT-3.2/4.x): the sweep enqueues a job tagged ``trigger='sweep'`` via
:func:`mcp_discovery_engine.enqueue_discovery_job`, then drives it with
:func:`mcp_discovery_engine.run_discovery_job`. The shared pipeline is what gives the
acceptance criteria for free — a re-discovery whose surface fingerprint is unchanged creates no
new version (it only stamps ``last_discovered_at``), and a changed surface produces exactly one
new version. Enqueue de-duplication (per-endpoint advisory lock + active-state check) makes the
loop idempotent and singleton-safe: a still-running discovery from a previous tick is never
double-started, and two overlapping sweep ticks never both kick off a run for the same endpoint.

**Bounded execution (MCAT-5.2).** Unlike MCAT-5.1's fire-and-forget dispatch, a tick now *runs*
the due endpoints under two bounds so a large backlog or one hostile server cannot overwhelm the
process:

* **Concurrency cap** — at most ``mcp_discovery_max_concurrency`` discovery runs execute at once
  (a semaphore); the rest queue. The tick awaits all runs before returning, which also provides
  natural backpressure (the next tick cannot pile on more work while this one is still draining).
* **Per-endpoint timeout** — each run is bounded by ``mcp_discovery_endpoint_timeout_seconds``;
  an overrun is recorded as a ``budget_exceeded`` failure (handled inside ``run_discovery_job``)
  so one slow endpoint can never hold a slot indefinitely.

The global ``mcp_discovery_enabled`` kill switch short-circuits the whole tick: when disabled the
sweep selects nothing and runs nothing, so operators can halt all auto-discovery for incident
response without touching per-endpoint state. Manual discovery (MCAT-3.2) does not run through this
sweep and is unaffected.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from .mcp_discovery_engine import enqueue_discovery_job, run_discovery_job

_logger = logging.getLogger(__name__)

#: How long sweep run rows are kept (#3676). At the default 60s tick this is about 43,000 rows;
#: older runs are pruned as each new one is recorded. Their jobs are kept (the link is SET NULL).
SWEEP_RUN_RETENTION_DAYS = 30


async def process_mcp_discovery_sweep(db: Any) -> int:
    """Run one re-discovery sweep tick: discover every due endpoint, bounded (MCAT-5.1/5.2).

    Selects the endpoints due for re-discovery (cadence elapsed; disabled/deleted excluded),
    enqueues a ``trigger='sweep'`` job for each (coalescing onto an already-active job where one
    exists), then drives the freshly-created jobs through the shared discovery→diff→version
    pipeline under a concurrency cap, each bounded by a per-endpoint timeout. A run that
    de-duplicates onto an already-active job (a prior tick still in flight, or a concurrent manual
    run) is not counted and not driven here. One endpoint failing to enqueue never aborts the rest
    of the tick, and one run failing/timing out never aborts the others.

    The tick awaits all dispatched runs before returning, so the concurrency cap is enforced for
    real and the next tick cannot start more work while this one is still draining.

    The global ``mcp_discovery_enabled`` kill switch halts the tick entirely (returns 0 without
    selecting, enqueuing, or running anything).

    **Observability (MCAT-5.4, #3676).** Every tick — including a halted one and one with nothing
    due — is recorded as an ``mcp_discovery_sweep_runs`` row with its timing, bounds and tick
    counters (due, dispatched, coalesced, enqueue failures), and each job it creates is linked to
    that row, so the run's outcome counts (changed / unchanged / failed / in flight) are read from
    the jobs themselves (:meth:`Database.list_mcp_discovery_sweep_runs`). Recording is best-effort:
    a failure to write the run row is logged and never stops discovery. A tick that raises is
    recorded as ``failed`` before the error propagates.

    Args:
        db: Database handle for this tick. The blocking due-selection query is pushed to a worker
            thread (psycopg2 is synchronous); the discovery runs themselves are async (the MCP
            client is asyncio) and push only their blocking DB writes to worker threads.

    Returns:
        The number of endpoints for which a *new* discovery run was dispatched this tick (0 when
        the kill switch is disabled or nothing was due). De-duplicated endpoints are excluded.
    """
    from .config import settings

    if not settings.mcp_discovery_enabled:
        # Global kill switch (MCAT-5.1): halt all periodic discovery for this tick.
        _logger.info(
            "mcp discovery sweep halted: APIOME_MCP_DISCOVERY_ENABLED is disabled"
        )
        run_id = await _start_run(db, max_concurrency=None, timeout_seconds=None)
        await _finish_run(db, run_id, status="halted")
        return 0

    max_concurrency = max(1, int(settings.mcp_discovery_max_concurrency))
    timeout_seconds = float(settings.mcp_discovery_endpoint_timeout_seconds)
    run_id = await _start_run(
        db, max_concurrency=max_concurrency, timeout_seconds=int(timeout_seconds)
    )
    tally = _TickTally()
    try:
        await _run_tick(db, run_id, tally, settings, max_concurrency, timeout_seconds)
    except BaseException:
        await _finish_run(db, run_id, status="failed", tally=tally)
        raise
    await _finish_run(db, run_id, status="completed", tally=tally)
    return tally.dispatched


class _TickTally:
    """The counters one tick accumulates and records on its run row."""

    def __init__(self) -> None:
        self.due = 0
        self.dispatched = 0
        self.deduplicated = 0
        self.enqueue_failed = 0


async def _run_tick(
    db: Any,
    run_id: Optional[str],
    tally: _TickTally,
    settings: Any,
    max_concurrency: int,
    timeout_seconds: float,
) -> None:
    """Select, enqueue and drive one tick's due endpoints, counting into ``tally``.

    Args:
        db: Database handle for the due-selection read.
        run_id: The tick's run row, linked onto every job it creates (``None`` when the run row
            could not be written; the jobs are then simply unlinked).
        tally: Receives the tick counters.
        settings: The application settings.
        max_concurrency: The concurrency cap.
        timeout_seconds: The per-endpoint timeout.
    """
    default_cadence = int(settings.mcp_discovery_default_cadence_seconds)
    due = await asyncio.to_thread(
        db.list_due_mcp_endpoints, default_cadence_seconds=default_cadence
    )
    tally.due = len(due)

    # Enqueue every due endpoint first (de-dup aware) and collect only the freshly-created jobs to
    # drive. Doing this up front means the dedup decision is settled before any run starts, and the
    # queued jobs are immediately visible.
    pending: List[Tuple[str, Dict[str, Any]]] = []
    for endpoint in due:
        endpoint_id = str(endpoint["id"])
        tenant_id = str(endpoint["tenant_id"])
        try:
            job, deduplicated = await enqueue_discovery_job(
                tenant_id, endpoint, trigger="sweep", sweep_run_id=run_id
            )
        except Exception:
            # A single endpoint's enqueue failure (e.g. transient DB error) must not abort the
            # sweep for the remaining due endpoints.
            tally.enqueue_failed += 1
            _logger.exception(
                "mcp discovery sweep enqueue failed endpoint_id=%s", endpoint_id
            )
            continue
        if deduplicated:
            tally.deduplicated += 1
        else:
            pending.append((str(job["id"]), endpoint))

    if not pending:
        return
    # Counted before the runs start, so a tick cancelled while draining still records what it began.
    tally.dispatched = len(pending)

    semaphore = asyncio.Semaphore(max_concurrency)

    async def _bounded_run(job_id: str, endpoint: Dict[str, Any]) -> None:
        """Drive one job, holding a concurrency slot for the duration of its bounded run."""
        async with semaphore:
            await run_discovery_job(
                job_id, endpoint, timeout_seconds=timeout_seconds
            )

    # run_discovery_job records its own terminal failures and never raises, but guard with
    # return_exceptions so an unexpected error in one run can never fail the whole tick.
    await asyncio.gather(
        *(_bounded_run(job_id, endpoint) for job_id, endpoint in pending),
        return_exceptions=True,
    )

    _logger.info(
        "mcp discovery sweep ran %d discovery run(s) over %d due endpoint(s) "
        "(max_concurrency=%d, per_endpoint_timeout=%.0fs)",
        tally.dispatched,
        tally.due,
        max_concurrency,
        timeout_seconds,
    )


async def _start_run(
    db: Any, *, max_concurrency: Optional[int], timeout_seconds: Optional[int]
) -> Optional[str]:
    """Record a tick's start (best-effort) and return its run id, or ``None`` if it failed.

    Args:
        db: Database handle for the write.
        max_concurrency: The tick's concurrency cap (``None`` when halted).
        timeout_seconds: The tick's per-endpoint timeout (``None`` when halted).

    Returns:
        The new run's id, or ``None`` when the row could not be written.
    """
    try:
        row = await asyncio.to_thread(
            db.start_mcp_discovery_sweep_run,
            max_concurrency=max_concurrency,
            endpoint_timeout_seconds=timeout_seconds,
            retention_days=SWEEP_RUN_RETENTION_DAYS,
        )
        return str(row["id"])
    except Exception:
        _logger.exception("mcp discovery sweep could not record its run")
        return None


async def _finish_run(
    db: Any,
    run_id: Optional[str],
    *,
    status: str,
    tally: Optional[_TickTally] = None,
) -> None:
    """Record how a tick ended (best-effort; a no-op when its start was not recorded).

    Args:
        db: Database handle for the write.
        run_id: The run from :func:`_start_run`, or ``None``.
        status: ``completed``, ``halted`` or ``failed``.
        tally: The tick counters; ``None`` records zeros (a halted tick).
    """
    if run_id is None:
        return
    tally = tally or _TickTally()
    try:
        await asyncio.to_thread(
            db.finish_mcp_discovery_sweep_run,
            run_id,
            status=status,
            due_count=tally.due,
            dispatched_count=tally.dispatched,
            deduplicated_count=tally.deduplicated,
            enqueue_failed_count=tally.enqueue_failed,
        )
    except Exception:
        _logger.exception("mcp discovery sweep could not record the end of run %s", run_id)
