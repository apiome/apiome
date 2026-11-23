"""Retention for operational logs that had none: discovery jobs and Slate request data (DBP-1.18, #7201).

Two kinds of rows used to accumulate forever:

* ``apiome.mcp_discovery_jobs`` — the MCP discovery sweep writes one job per due endpoint per tick.
  Finished jobs older than ``APIOME_MCP_DISCOVERY_JOB_RETENTION_DAYS`` (default 30) are deleted,
  except each endpoint's ``APIOME_MCP_DISCOVERY_JOB_KEEP_PER_ENDPOINT`` (default 20) newest finished
  jobs, so its discovery history never empties. Queued and running jobs are never touched.
* Slate request data (logs, traces with their spans, live-tail sessions, synthetic results,
  security events, function invocations) — every row is written with a ``retain_until`` derived
  from its lane's policy, but nothing deleted it. Rows past their ``retain_until`` are deleted.

Each tick deletes in batches (``APIOME_SLATE_RETENTION_BATCH_SIZE``, the async-job batch size for
discovery jobs) up to :data:`MAX_BATCHES_PER_TABLE` batches per table, so a large first backlog is
worked off over several ticks without one long-running delete. Discovery jobs are read in bounded
windows that resume where the previous one stopped — across ticks too, wrapping around at the
newest expired job — so jobs kept as an endpoint's newest never make a tick re-read the same rows.
It runs on the async-job retention tick (every 5 minutes); one table's failure never stops the
others.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from .config import settings

__all__ = ["MAX_BATCHES_PER_TABLE", "process_operational_retention_sweep"]

logger = logging.getLogger(__name__)

#: The most delete batches one tick runs per table.
MAX_BATCHES_PER_TABLE = 20

#: Where this process's discovery-job prune resumes: ``(created_at, id)`` of the last job read, or
#: ``None`` to start from the oldest. Kept between ticks; another replica keeps its own.
_discovery_job_cursor: Optional[Tuple[Any, str]] = None


def _prune_discovery_jobs(database: Any, *, retention_days: int, keep: int, batch: int) -> int:
    """Run up to :data:`MAX_BATCHES_PER_TABLE` bounded prune windows, resuming from the last tick.

    Args:
        database: The sweep's database handle.
        retention_days: Finished jobs older than this go.
        keep: Each endpoint's newest finished jobs kept regardless of age.
        batch: Expired jobs read per window.

    Returns:
        Jobs deleted; what was deleted before a failure still counts.
    """
    global _discovery_job_cursor
    deleted = 0
    try:
        for _ in range(MAX_BATCHES_PER_TABLE):
            result = database.prune_mcp_discovery_jobs(
                retention_days=retention_days, keep_per_endpoint=keep, limit=batch, after=_discovery_job_cursor
            )
            deleted += int(result.get("deleted") or 0)
            _discovery_job_cursor = result.get("next")
            if _discovery_job_cursor is None:
                break
    except Exception:  # noqa: BLE001 - one table's failure never stops the others
        logger.exception("operational retention: pruning mcp_discovery_jobs failed")
    return deleted


def _drain(delete_batch: Callable[[], int], batch_size: int, label: str) -> int:
    """Run ``delete_batch`` until it deletes less than a full batch or the per-tick cap is reached.

    Args:
        delete_batch: Deletes one batch and returns how many rows it deleted.
        batch_size: The batch size ``delete_batch`` uses (a short batch means the backlog is gone).
        label: Names the table in the failure log line.

    Returns:
        Rows deleted; what was deleted before a failure still counts.
    """
    deleted = 0
    try:
        for _ in range(MAX_BATCHES_PER_TABLE):
            n = int(delete_batch() or 0)
            deleted += n
            if n < batch_size:
                break
    except Exception:  # noqa: BLE001 - one table's failure never stops the others
        logger.exception("operational retention: pruning %s failed", label)
    return deleted


def process_operational_retention_sweep(
    database: Any,
    *,
    discovery_job_retention_days: Optional[int] = None,
    discovery_job_keep_per_endpoint: Optional[int] = None,
    discovery_job_batch_size: Optional[int] = None,
    slate_batch_size: Optional[int] = None,
) -> Dict[str, int]:
    """Run one retention tick for discovery jobs and Slate request data.

    Args:
        database: The sweep's database handle.
        discovery_job_retention_days: Defaults to ``settings.mcp_discovery_job_retention_days``;
            ``<= 0`` keeps finished jobs forever.
        discovery_job_keep_per_endpoint: Defaults to
            ``settings.mcp_discovery_job_keep_per_endpoint``.
        discovery_job_batch_size: Defaults to ``settings.async_job_retention_sweep_batch_size``.
        slate_batch_size: Defaults to ``settings.slate_retention_batch_size``.

    Returns:
        ``{"mcp_discovery_jobs": n, "<slate table>": n, ...}`` — rows deleted per table.
    """
    retention_days = int(
        discovery_job_retention_days
        if discovery_job_retention_days is not None
        else settings.mcp_discovery_job_retention_days
    )
    keep = int(
        discovery_job_keep_per_endpoint
        if discovery_job_keep_per_endpoint is not None
        else settings.mcp_discovery_job_keep_per_endpoint
    )
    job_batch = max(
        1,
        int(
            discovery_job_batch_size
            if discovery_job_batch_size is not None
            else settings.async_job_retention_sweep_batch_size
        ),
    )
    slate_batch = max(1, int(slate_batch_size if slate_batch_size is not None else settings.slate_retention_batch_size))

    counts: Dict[str, int] = {"mcp_discovery_jobs": 0}
    if retention_days > 0:
        counts["mcp_discovery_jobs"] = _prune_discovery_jobs(
            database, retention_days=retention_days, keep=keep, batch=job_batch
        )
    for table in database.SLATE_RETAINED_TABLES:
        counts[table] = _drain(
            lambda table=table: database.purge_expired_slate_rows(table, limit=slate_batch),
            slate_batch,
            table,
        )
    if any(counts.values()):
        logger.info(
            "operational retention: %s",
            " ".join(f"{name}={n}" for name, n in counts.items() if n),
        )
    return counts
