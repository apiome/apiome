"""Live hosted verification runs — PFX-8.9 (#7306).

``POST …/verify`` (PFX-3.2) answers when the whole run is over, so a running verification is
invisible until it ends. A **live run** is the same run on a background thread, watched as it
happens:

* :meth:`LiveRuns.start` checks the run exactly as ``…/verify`` does — every refusal (a malformed
  version, too many pacts, an unknown target, mutating requests against production) is the same
  error, raised before anything starts — then replays it on a small, dedicated thread pool and
  returns at once with the run's id.
* :meth:`LiveRuns.snapshot` is what the run drawer polls: one row per pact (queued, running,
  passed, failed, incomplete, stopped) with interactions done of the total, the newest failing
  interaction with expected beside actual, and the log since the reader's cursor. A finished run
  carries the very :class:`~app.pact_verifier_service.PactVerifyResponse` ``…/verify`` returns.
* :meth:`LiveRuns.stop` asks the run to stop. It takes effect before the next interaction is sent:
  a pact cut short publishes nothing, the pacts not reached are listed as skipped
  (``pact-verify-stopped``), and the outcome is ``stopped``. Closing the drawer stops nothing.
* :meth:`LiveRuns.rerun_interaction` replays one interaction of a finished run's pact against the
  same target with the same options and publishes nothing — a quick check after a fix.

Runs are **per worker process** and kept for :data:`FINISHED_TTL_SECONDS` after they end, like the
export-fidelity jobs. A run is scoped to the tenant that started it: another tenant asking for it
is told it does not exist. **Nothing is dropped silently**: a log longer than :data:`MAX_LOG_LINES`
keeps its newest lines and says how many older ones it let go (``log_dropped``).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .consumer_contract_store import ConsumerActor
from .pact_publication_store import get_pact_by_sha
from .pact_selectors import VerifiablePact
from .pact_verifier import InteractionVerification, ProviderStateHandler
from .pact_verifier_service import (
    NOT_PUBLISHED_STOPPED,
    PactVerification,
    PactVerifyRequest,
    PactVerifyResponse,
    SkippedPact,
    compile_stored_pact,
    open_verification_session,
    prepare_verification,
    run_prepared_verification,
)
from .verification_evidence import (
    OPERATION_OUTCOME_ERRORED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    OPERATION_OUTCOME_SKIPPED,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_INTERACTION_NOT_FOUND",
    "CODE_RUN_BUSY",
    "CODE_RUN_LIMIT",
    "CODE_RUN_NOT_FOUND",
    "CODE_RUN_PACT_NOT_FOUND",
    "LiveRunError",
    "LiveRunSnapshot",
    "LiveRuns",
    "RerunRequest",
    "RerunResponse",
    "live_runs",
]

#: No run with that id in this workspace (HTTP 404).
CODE_RUN_NOT_FOUND = "pact-verify-run-not-found"
#: The workspace already has :data:`MAX_ACTIVE_RUNS_PER_TENANT` runs going (HTTP 429).
CODE_RUN_LIMIT = "pact-verify-run-limit"
#: The run is still going, so one of its interactions cannot be re-run yet (HTTP 409).
CODE_RUN_BUSY = "pact-verify-run-busy"
#: The run did not verify that pact version (HTTP 404).
CODE_RUN_PACT_NOT_FOUND = "pact-verify-run-pact-not-found"
#: The pact has no interaction with that case id (HTTP 404).
CODE_INTERACTION_NOT_FOUND = "pact-verify-run-interaction-not-found"

#: A run being prepared or replayed.
STATUS_RUNNING = "running"
#: A run that ended (read ``result.outcome``: passed, failed, stopped, could-not-connect …).
STATUS_FINISHED = "finished"
#: A run that broke on Apiome's side after it started (``error`` says why); nothing more happens.
STATUS_ERRORED = "errored"

#: Per-pact statuses beside a pact's own outcome (passed, failed, incomplete).
PACT_QUEUED = "queued"
PACT_RUNNING = "running"
PACT_STOPPED = "stopped"

#: Runs a workspace may have going at once.
MAX_ACTIVE_RUNS_PER_TENANT = 3
#: Log lines kept per run; older ones are let go and counted.
MAX_LOG_LINES = 2000
#: How long a finished run keeps answering (seconds).
FINISHED_TTL_SECONDS = 1800.0
#: Replay threads per worker process when ``APIOME_PACT_LIVE_RUN_WORKERS`` is unset.
DEFAULT_WORKERS = 2


class LiveRunError(Exception):
    """A live-run request that cannot be served.

    Attributes:
        code: Stable machine code (``pact-verify-run-not-found`` …).
        status: The HTTP status it maps to.
    """

    def __init__(self, code: str, message: str, status: int) -> None:
        """Build the refusal.

        Args:
            code: Stable machine code.
            message: Human explanation.
            status: HTTP status.
        """
        super().__init__(message)
        self.code = code
        self.status = status


# =============================================================================================
# What the drawer reads
# =============================================================================================


class LiveRunPact(BaseModel):
    """One pact of a live run, as its row in the drawer reads."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: str = Field(description="The consumer version of the pact.")
    pact_version_sha: str = Field(description="The pact version.")
    status: str = Field(
        description="`queued`, `running`, then the pact's outcome — `passed`, `failed`, `incomplete` — or `stopped`."
    )
    pending: bool = Field(default=False, description="Whether its failure cannot fail the run.")
    interactions: int = Field(default=0, description="Interactions its suite holds (0 until it is compiled).")
    done: int = Field(default=0, description="Interactions replayed or held back so far.")
    passed: int = Field(default=0, description="Replayed and matched.")
    failed: int = Field(default=0, description="Replayed and did not match.")
    skipped: int = Field(default=0, description="Held back, with a reason.")
    errored: int = Field(default=0, description="Could not be sent or answered.")
    published: Optional[bool] = Field(default=None, description="Whether its result was published, once it ended.")
    not_published_reason: Optional[str] = Field(
        default=None, description="`run-incomplete`, `publish-disabled` or `run-stopped`."
    )


class LiveRunLogLine(BaseModel):
    """One line of a live run's log."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(description="Its number in the run's log (1-based); read on with `log_after`.")
    at: datetime = Field(description="When it happened.")
    kind: str = Field(description="`run`, `pact`, `state`, `interaction` or `rerun`.")
    outcome: Optional[str] = Field(default=None, description="`passed`, `failed`, `skipped`, `errored` or `ok`.")
    text: str = Field(description="The line as the drawer prints it.")


class LiveRunFailure(BaseModel):
    """The newest interaction of the run that did not pass, with expected beside actual."""

    model_config = ConfigDict(extra="forbid")

    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    consumer_version: str = Field(description="The consumer version of the pact.")
    pact_version_sha: str = Field(description="The pact version.")
    interaction: InteractionVerification = Field(description="The interaction, its mismatches included.")


class LiveRunFault(BaseModel):
    """Why a run broke on Apiome's side."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable machine code.")
    message: str = Field(description="The reason.")


class LiveRunSnapshot(BaseModel):
    """A live run as it stands."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="The run's id.")
    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="The provider's display name.")
    provider_version: str = Field(description="The provider version being verified.")
    provider_branch: Optional[str] = Field(default=None, description="Its branch, when stated.")
    target: str = Field(description="The verification target's handle.")
    target_base_url: str = Field(description="Where the interactions are sent.")
    environment: str = Field(description="The target's environment class.")
    status: str = Field(description="`running`, `finished` or `errored`.")
    stop_requested: bool = Field(description="Whether someone asked the run to stop.")
    started_at: datetime = Field(description="When the run started.")
    finished_at: Optional[datetime] = Field(default=None, description="When it ended.")
    interactions: int = Field(description="Interactions of every pact, as far as they are compiled.")
    done: int = Field(description="Interactions replayed or held back so far.")
    pacts: List[LiveRunPact] = Field(default_factory=list, description="One row per pact, in run order.")
    skipped: List[SkippedPact] = Field(default_factory=list, description="Chosen but not verified, each with why.")
    failure: Optional[LiveRunFailure] = Field(default=None, description="The newest interaction that did not pass.")
    log: List[LiveRunLogLine] = Field(default_factory=list, description="Log lines after `log_after`, oldest first.")
    log_next: int = Field(description="The newest line's `seq`: send it as `log_after` to read on.")
    log_dropped: int = Field(default=0, description=f"Older lines let go beyond the {MAX_LOG_LINES} a run keeps.")
    result: Optional[PactVerifyResponse] = Field(
        default=None, description="Once finished: exactly what `POST …/verify` would have answered."
    )
    error: Optional[LiveRunFault] = Field(default=None, description="With status `errored`: why.")


class RerunRequest(BaseModel):
    """Which interaction of the run to replay again."""

    model_config = ConfigDict(extra="forbid")

    pact_version_sha: str = Field(description="The pact version, as the run listed it.", min_length=1, max_length=128)
    case_id: str = Field(
        description="The interaction's suite case (`failure.interaction.case_id`).", min_length=1, max_length=500
    )


class RerunResponse(BaseModel):
    """One interaction replayed again; nothing published."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="The run it belongs to.")
    pact_version_sha: str = Field(description="The pact version.")
    interaction: InteractionVerification = Field(description="What replaying it showed this time.")
    published: bool = Field(default=False, description="Always false: one interaction does not verify a pact.")


# =============================================================================================
# One run
# =============================================================================================


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clock(moment: datetime) -> str:
    return moment.strftime("%H:%M:%S")


def interaction_line(result: InteractionVerification) -> str:
    """The log text for one interaction: method and path, status, and how it went.

    Args:
        result: The interaction's result.

    Returns:
        E.g. ``POST /invoices  201  body differs at /currency`` or ``GET /invoices/42  200  ok  12 ms``.
    """
    status = str(result.actual_status) if result.actual_status is not None else "—"
    if result.outcome == OPERATION_OUTCOME_PASSED:
        how = f"ok  {result.duration_ms} ms"
    elif result.mismatches:
        first = result.mismatches[0]
        where = f" at {first.field}" if first.attribute == "body" else f" ({first.field})"
        how = f"{first.attribute} differs{where}"
        if len(result.mismatches) > 1:
            how += f" (+{len(result.mismatches) - 1} more)"
    else:
        how = result.message or result.code or result.outcome
    return f"{result.operation}  {status}  {how}"


@dataclass
class _Run:
    """One live run's state, guarded by its lock. Implements the verifier's run observer."""

    run_id: str
    tenant_id: str
    provider_record: Any
    provider: str
    provider_name: str
    provider_version: str
    provider_branch: Optional[str]
    target: str
    target_base_url: str
    environment: str
    request: PactVerifyRequest
    started_at: datetime
    rows: List[LiveRunPact]
    skipped: List[SkippedPact]
    lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)
    status: str = STATUS_RUNNING
    finished_at: Optional[datetime] = None
    finished_monotonic: Optional[float] = None
    failure: Optional[LiveRunFailure] = None
    log: List[LiveRunLogLine] = field(default_factory=list)
    log_seq: int = 0
    log_dropped: int = 0
    result: Optional[PactVerifyResponse] = None
    error: Optional[LiveRunFault] = None

    # --- the log -----------------------------------------------------------------------------

    def add_line(self, kind: str, text: str, outcome: Optional[str] = None) -> None:
        """Append a log line, letting the oldest go beyond :data:`MAX_LOG_LINES`."""
        with self.lock:
            self.log_seq += 1
            moment = _now()
            self.log.append(
                LiveRunLogLine(seq=self.log_seq, at=moment, kind=kind, outcome=outcome, text=f"{_clock(moment)} {text}")
            )
            overflow = len(self.log) - MAX_LOG_LINES
            if overflow > 0:
                del self.log[:overflow]
                self.log_dropped += overflow

    def _row(self, sha: str, consumer: str) -> Optional[LiveRunPact]:
        return next((row for row in self.rows if row.pact_version_sha == sha and row.consumer == consumer), None)

    # --- RunObserver -------------------------------------------------------------------------

    def stop_requested(self) -> bool:
        """Whether someone asked the run to stop."""
        return self.stop_event.is_set()

    def pact_started(self, pact: VerifiablePact, interactions: int) -> None:
        """Mark the pact's row running with its interaction count."""
        candidate = pact.candidate
        with self.lock:
            row = self._row(candidate.sha, candidate.consumer_slug)
            if row is not None:
                row.status = PACT_RUNNING
                row.interactions = interactions
        self.add_line("pact", f"pact   {candidate.consumer_name} {candidate.version_number} ({candidate.sha[:7]})")

    def state_set_up(self, states: List[str], problem: Optional[str], duration_ms: int) -> None:
        """Log the provider states set up before an interaction."""
        names = ", ".join(f"“{name}”" for name in states)
        if problem:
            self.add_line("state", f"state  {names}  failed  {problem}", "failed")
        else:
            self.add_line("state", f"state  {names}  ok  {duration_ms} ms", "ok")

    def interaction_done(self, pact: VerifiablePact, result: InteractionVerification) -> None:
        """Count the interaction on its row, log it, and keep it when it did not pass."""
        candidate = pact.candidate
        with self.lock:
            row = self._row(candidate.sha, candidate.consumer_slug)
            if row is not None:
                row.done += 1
                if result.outcome == OPERATION_OUTCOME_PASSED:
                    row.passed += 1
                elif result.outcome == OPERATION_OUTCOME_FAILED:
                    row.failed += 1
                elif result.outcome == OPERATION_OUTCOME_SKIPPED:
                    row.skipped += 1
                else:
                    row.errored += 1
            if result.outcome in (OPERATION_OUTCOME_FAILED, OPERATION_OUTCOME_ERRORED):
                self.failure = LiveRunFailure(
                    consumer=candidate.consumer_slug,
                    consumer_name=candidate.consumer_name,
                    consumer_version=candidate.version_number,
                    pact_version_sha=candidate.sha,
                    interaction=result,
                )
        self.add_line("interaction", interaction_line(result), result.outcome)

    def pact_finished(self, verification: PactVerification) -> None:
        """Set the pact's row to its outcome."""
        with self.lock:
            row = self._row(verification.pact_version_sha, verification.consumer)
            if row is not None:
                stopped = verification.not_published_reason == NOT_PUBLISHED_STOPPED
                row.status = PACT_STOPPED if stopped else verification.outcome
                row.published = verification.published
                row.not_published_reason = verification.not_published_reason
                row.interactions = max(row.interactions, row.done)
        verdict = "stopped" if verification.not_published_reason == NOT_PUBLISHED_STOPPED else verification.outcome
        published = "published" if verification.published else f"not published ({verification.not_published_reason})"
        self.add_line("pact", f"pact   {verification.consumer_name} {verdict} · {published}", verification.outcome)

    # --- the end -----------------------------------------------------------------------------

    def finish(self, result: PactVerifyResponse) -> None:
        """Record the run's answer and mark every row not reached as stopped."""
        reached = {(p.consumer, p.pact_version_sha) for p in result.pacts}
        with self.lock:
            for row in self.rows:
                if (row.consumer, row.pact_version_sha) not in reached and row.status in (PACT_QUEUED, PACT_RUNNING):
                    row.status = PACT_STOPPED
            self.skipped = list(result.skipped)
            self.result = result
            self.status = STATUS_FINISHED
            self.finished_at = _now()
            self.finished_monotonic = time.monotonic()
        detail = f" — {result.connection_error}" if result.connection_error else ""
        self.add_line("run", f"run    {result.outcome}{detail}", result.outcome)

    def fail(self, code: str, message: str) -> None:
        """Record that the run broke on Apiome's side."""
        with self.lock:
            for row in self.rows:
                if row.status in (PACT_QUEUED, PACT_RUNNING):
                    row.status = PACT_STOPPED
            self.error = LiveRunFault(code=code, message=message)
            self.status = STATUS_ERRORED
            self.finished_at = _now()
            self.finished_monotonic = time.monotonic()
        self.add_line("run", f"run    errored — {message}", "errored")

    def snapshot(self, log_after: int = 0) -> LiveRunSnapshot:
        """The run as it stands, with the log lines after ``log_after``."""
        with self.lock:
            rows = [row.model_copy() for row in self.rows]
            return LiveRunSnapshot(
                run_id=self.run_id,
                provider=self.provider,
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                provider_branch=self.provider_branch,
                target=self.target,
                target_base_url=self.target_base_url,
                environment=self.environment,
                status=self.status,
                stop_requested=self.stop_event.is_set(),
                started_at=self.started_at,
                finished_at=self.finished_at,
                interactions=sum(row.interactions for row in rows),
                done=sum(row.done for row in rows),
                pacts=rows,
                skipped=list(self.skipped),
                failure=self.failure,
                log=[line for line in self.log if line.seq > log_after],
                log_next=self.log_seq,
                log_dropped=self.log_dropped,
                result=self.result,
                error=self.error,
            )


def _row_of(pact: VerifiablePact) -> LiveRunPact:
    candidate = pact.candidate
    return LiveRunPact(
        consumer=candidate.consumer_slug,
        consumer_name=candidate.consumer_name,
        consumer_version=candidate.version_number,
        pact_version_sha=candidate.sha,
        status=PACT_QUEUED,
        pending=bool(pact.pending),
    )


def _count_interactions(db: Any, run: _Run, tenant_id: str, selected: List[VerifiablePact]) -> None:
    """Fill each queued row's interaction count so the progress bar has its total from the start.

    A pact that cannot be read here is left at 0; its own replay reports the problem.
    """
    for pact in selected:
        candidate = pact.candidate
        try:
            total = len(
                compile_stored_pact(
                    get_pact_by_sha(db, tenant_id, run.provider, candidate.consumer_slug, candidate.sha)
                ).cases
            )
        except Exception:  # noqa: BLE001 - only the total is missing; the replay will say why
            logger.exception("live run %s: could not count the interactions of %s", run.run_id, candidate.sha)
            continue
        with run.lock:
            row = run._row(candidate.sha, candidate.consumer_slug)
            if row is not None and row.status == PACT_QUEUED:
                row.interactions = total


# =============================================================================================
# The registry
# =============================================================================================


def _configured_workers() -> int:
    raw = os.environ.get("APIOME_PACT_LIVE_RUN_WORKERS", "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_WORKERS
    except ValueError:
        return DEFAULT_WORKERS


class LiveRuns:
    """The live runs of this worker process, by id."""

    def __init__(self, workers: Optional[int] = None) -> None:
        """Build an empty registry.

        Args:
            workers: Replay threads; :data:`DEFAULT_WORKERS` (or the environment's) when ``None``.
        """
        self._runs: Dict[str, _Run] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=workers or _configured_workers(), thread_name_prefix="pact-live-run"
        )

    # --- housekeeping ------------------------------------------------------------------------

    def _evict(self) -> None:
        cutoff = time.monotonic() - FINISHED_TTL_SECONDS
        with self._lock:
            for run_id in [
                key
                for key, run in self._runs.items()
                if run.finished_monotonic is not None and run.finished_monotonic < cutoff
            ]:
                del self._runs[run_id]

    def _get(self, tenant_id: str, run_id: str) -> _Run:
        self._evict()
        with self._lock:
            run = self._runs.get(run_id)
        if run is None or run.tenant_id != tenant_id:
            raise LiveRunError(
                CODE_RUN_NOT_FOUND,
                "No live run with that id in this workspace. A run is kept for 30 minutes after it ends.",
                404,
            )
        return run

    def provider_of(self, tenant_id: str, run_id: str) -> str:
        """The provider a run verifies (for the permission check), or a 404 refusal."""
        return self._get(tenant_id, run_id).provider

    def clear(self) -> None:
        """Forget every run (tests)."""
        with self._lock:
            self._runs.clear()

    # --- start -------------------------------------------------------------------------------

    def start(
        self,
        db: Any,
        tenant_id: str,
        provider_ref: str,
        request: PactVerifyRequest,
        *,
        actor: ConsumerActor,
        broker_base: str,
        state_handler: Optional[ProviderStateHandler] = None,
    ) -> LiveRunSnapshot:
        """Check a run as ``…/verify`` does, then replay it in the background.

        Args:
            db: The database.
            tenant_id: The caller's tenant.
            provider_ref: The provider's handle, id or name.
            request: The body of ``…/verify``, unchanged.
            actor: Who is verifying.
            broker_base: The Pact Broker base URL (result links, webhooks).
            state_handler: A provider-state handler to use instead of the registered one (tests).

        Returns:
            The run as it starts: every pact queued.

        Raises:
            LiveRunError: :data:`CODE_RUN_LIMIT` when the workspace already has
                :data:`MAX_ACTIVE_RUNS_PER_TENANT` runs going.
            PacticipantValidationError, PactPublicationError, TargetValidationError,
            PactVerifierError: Exactly as ``POST …/verify`` refuses the same body.
        """
        self._evict()
        with self._lock:
            active = sum(
                1 for run in self._runs.values() if run.tenant_id == tenant_id and run.status == STATUS_RUNNING
            )
        if active >= MAX_ACTIVE_RUNS_PER_TENANT:
            raise LiveRunError(
                CODE_RUN_LIMIT,
                f"This workspace already has {active} verification runs going; wait for one to finish or stop one.",
                429,
            )
        prepared = prepare_verification(db, tenant_id, provider_ref, request, actor=actor, state_handler=state_handler)
        session = prepared.session
        run = _Run(
            run_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            provider_record=session.provider,
            provider=session.provider.slug,
            provider_name=session.provider.name or session.provider.slug,
            provider_version=prepared.version,
            provider_branch=prepared.branch,
            target=session.target.slug,
            target_base_url=session.target.base_url,
            environment=session.target.environment,
            request=session.request,
            started_at=_now(),
            rows=[_row_of(pact) for pact in prepared.selected],
            skipped=list(prepared.skipped),
        )
        with self._lock:
            self._runs[run.run_id] = run
        run.add_line(
            "run",
            f"run    {len(prepared.selected)} pact(s) against {session.target.slug} ({session.target.base_url})",
        )

        def replay() -> None:
            try:
                _count_interactions(db, run, tenant_id, prepared.selected)
                result = run_prepared_verification(
                    db, tenant_id, prepared, actor=actor, broker_base=broker_base, observer=run
                )
            except Exception as exc:  # noqa: BLE001 - the run's thread must record any end
                logger.exception("live run %s broke", run.run_id)
                prepared.session.close()
                run.fail("pact-verify-run-errored", f"the run stopped on Apiome's side ({exc.__class__.__name__}).")
                return
            run.finish(result)

        started = run.snapshot()
        self._pool.submit(replay)
        return started

    # --- read, stop, re-run ------------------------------------------------------------------

    def snapshot(self, tenant_id: str, run_id: str, log_after: int = 0) -> LiveRunSnapshot:
        """The run as it stands (see :meth:`_Run.snapshot`), or a 404 refusal."""
        return self._get(tenant_id, run_id).snapshot(max(0, log_after))

    def stop(self, tenant_id: str, run_id: str) -> LiveRunSnapshot:
        """Ask a run to stop before its next interaction. Stopping a finished run changes nothing.

        Returns:
            The run as it stands (``stop_requested`` true while it winds down).
        """
        run = self._get(tenant_id, run_id)
        if run.status == STATUS_RUNNING and not run.stop_event.is_set():
            run.stop_event.set()
            run.add_line("run", "run    stop requested — the run ends before its next interaction")
        return run.snapshot()

    def rerun_interaction(
        self,
        db: Any,
        tenant_id: str,
        run_id: str,
        body: RerunRequest,
        *,
        actor: ConsumerActor,
        state_handler: Optional[ProviderStateHandler] = None,
    ) -> RerunResponse:
        """Replay one interaction of a finished run's pact, publishing nothing.

        The target is resolved again and every rule of a run holds — a production target is still
        never sent a mutating request.

        Raises:
            LiveRunError: 404 for an unknown run, pact or interaction; 409 while the run is going.
            TargetValidationError, PactVerifierError: The target can no longer be used.
        """
        run = self._get(tenant_id, run_id)
        if run.status == STATUS_RUNNING:
            raise LiveRunError(
                CODE_RUN_BUSY,
                "The run is still going; re-run one interaction once it has finished or been stopped.",
                409,
            )
        row = next((item for item in run.rows if item.pact_version_sha == body.pact_version_sha), None)
        if row is None:
            raise LiveRunError(CODE_RUN_PACT_NOT_FOUND, "This run did not verify that pact version.", 404)
        session = open_verification_session(
            db, tenant_id, run.provider_record, run.request, actor=actor, state_handler=state_handler
        )
        try:
            result = session.replay_interaction(row.consumer, row.pact_version_sha, body.case_id)
        finally:
            session.close()
        if result is None:
            raise LiveRunError(CODE_INTERACTION_NOT_FOUND, "The pact has no interaction with that case id.", 404)
        run.add_line("rerun", f"re-run {interaction_line(result)}", result.outcome)
        return RerunResponse(run_id=run.run_id, pact_version_sha=row.pact_version_sha, interaction=result)


#: The process's registry.
live_runs = LiveRuns()
