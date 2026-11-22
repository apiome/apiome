"""Background scoring of the export targets list — the deferred ``/export/targets`` mode.

Scoring a source against every export target (each target's fidelity badge) is CPU-bound and
takes seconds on a large spec. This module runs it on a small, dedicated thread pool so a
request never does it inline:

* :meth:`FidelityJobs.submit` starts scoring for a targets-cache key, or joins the job already
  running for it (single-flight), and returns an opaque **token**. The deferred ``/targets``
  response carries the token; the client polls ``/targets/fidelity/{token}`` until it is ready.
* :meth:`FidelityJobs.wait` is the blocking mode's path: the same job, waited on. Two requests
  for one source — one deferred, one blocking — share one computation.
* A finished job writes its list to :func:`app.export_targets_cache.targets_cache`, so the next
  request for the source does not score again.

The pool is bounded (:data:`DEFAULT_WORKERS`, ``APIOME_EXPORT_FIDELITY_WORKERS``): however many
people open the Export screen at once, at most that many scoring threads run, and requests wait
for them instead of each burning a CPU. The threads release the interpreter lock between
bytecodes like any other, so the server keeps answering other requests while they work.

Jobs are per worker process. A token is scoped to the tenant that started it: another tenant
polling it is told it does not exist. A finished job is kept for :data:`JOB_TTL_SECONDS`, after
which its token is unknown and the client falls back to a blocking request (served from the
cache when the list is still there).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from .export_targets_cache import TargetsCacheKey, targets_cache

_logger = logging.getLogger(__name__)

#: Scoring threads per worker process when ``APIOME_EXPORT_FIDELITY_WORKERS`` is unset.
DEFAULT_WORKERS = 2

#: How long a finished job's token keeps answering (seconds).
JOB_TTL_SECONDS = 600.0

JobState = Literal["pending", "ready", "failed"]


@dataclass
class _Job:
    """One scoring job: who started it, and its future."""

    tenant_id: str
    key: Any
    future: "Future[List[Any]]"
    finished_at: Optional[float] = None


def job_token(key: TargetsCacheKey) -> str:
    """The opaque token naming the job for ``key`` (a digest; it reveals nothing about the key).

    Args:
        key: The targets-cache key of the source.

    Returns:
        32 hex characters.
    """
    return hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:32]


def _configured_workers() -> int:
    raw = os.environ.get("APIOME_EXPORT_FIDELITY_WORKERS", "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_WORKERS
    except ValueError:
        return DEFAULT_WORKERS


class FidelityJobs:
    """A bounded pool of scoring jobs, keyed by targets-cache key, single-flight per key."""

    def __init__(self, *, max_workers: Optional[int] = None, ttl_seconds: float = JOB_TTL_SECONDS) -> None:
        """Create an idle pool (threads start on the first job).

        Args:
            max_workers: Scoring threads; ``None`` reads ``APIOME_EXPORT_FIDELITY_WORKERS``.
            ttl_seconds: How long a finished job's token keeps answering.
        """
        self._max_workers = max_workers or _configured_workers()
        self._ttl_seconds = ttl_seconds
        self._executor: Optional[ThreadPoolExecutor] = None
        self._jobs: Dict[str, _Job] = {}
        self._lock = threading.Lock()

    def submit(self, key: TargetsCacheKey, tenant_id: str, compute: Callable[[], List[Any]]) -> str:
        """Start scoring for ``key``, or join the job already running or finished for it.

        A failed job is replaced, so a later request tries again.

        Args:
            key: The targets-cache key of the source.
            tenant_id: The caller's tenant; only it can read the job.
            compute: Builds the scored targets list. Runs on a pool thread.

        Returns:
            The job's token.
        """
        token = job_token(key)
        with self._lock:
            self._purge_locked()
            job = self._jobs.get(token)
            if job is not None and not (job.future.done() and job.future.exception() is not None):
                return token
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers, thread_name_prefix="export-fidelity"
                )
            future = self._executor.submit(self._run, token, key, compute)
            self._jobs[token] = _Job(tenant_id=str(tenant_id), key=key, future=future)
        return token

    def wait(self, key: TargetsCacheKey, tenant_id: str, compute: Callable[[], List[Any]]) -> List[Any]:
        """Score ``key`` (or join its job) and wait for the list.

        Args:
            key: The targets-cache key of the source.
            tenant_id: The caller's tenant.
            compute: Builds the scored targets list.

        Returns:
            The scored targets list.

        Raises:
            Exception: Whatever ``compute`` raised.
        """
        token = self.submit(key, tenant_id, compute)
        with self._lock:
            future = self._jobs[token].future
        return list(future.result())

    def status(self, token: str, tenant_id: str) -> Optional[Tuple[JobState, Optional[List[Any]], Optional[str]]]:
        """The state of the job named by ``token``, as the polling endpoint reports it.

        Args:
            token: A token :meth:`submit` returned.
            tenant_id: The caller's tenant.

        Returns:
            ``(state, targets, error)`` — the list when ``ready``, a message when ``failed`` — or
            ``None`` when this worker has no such job for this tenant (another tenant's token, an
            expired one, or one another worker process started).
        """
        with self._lock:
            self._purge_locked()
            job = self._jobs.get(token)
            if job is None or job.tenant_id != str(tenant_id):
                return None
            future = job.future
        if not future.done():
            return "pending", None, None
        error = future.exception()
        if error is not None:
            return "failed", None, str(error) or type(error).__name__
        return "ready", list(future.result()), None

    def _run(self, token: str, key: TargetsCacheKey, compute: Callable[[], List[Any]]) -> List[Any]:
        try:
            entries = compute()
        except Exception:
            _logger.exception("scoring the export targets list failed (job %s)", token)
            raise
        finally:
            with self._lock:
                job = self._jobs.get(token)
                if job is not None:
                    job.finished_at = time.monotonic()
        targets_cache().put(key, entries)
        return entries

    def _purge_locked(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, job in self._jobs.items()
            if job.finished_at is not None and now - job.finished_at > self._ttl_seconds
        ]
        for token in expired:
            del self._jobs[token]

    def clear(self) -> None:
        """Forget every job (running ones finish, but their tokens stop answering)."""
        with self._lock:
            self._jobs.clear()

    def __len__(self) -> int:
        """Return the number of jobs kept (running or finished)."""
        return len(self._jobs)


_jobs = FidelityJobs()


def fidelity_jobs() -> FidelityJobs:
    """Return the process-wide scoring pool."""
    return _jobs
