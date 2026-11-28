"""A broker migration as a job the product can watch — PFX-8.16 (#7313).

``apiome pact migrate`` (PFX-6.7) reads a Pact Broker or PactFlow workspace and imports it, on the
caller's machine. The Migration wizard runs the same engine here: :func:`run_migration` reads the
source (:mod:`app.pact_migration_source`), builds the same records (:mod:`app.pact_migration_plan`),
and writes them through the same store (:mod:`app.pact_migration_store`) — batch by batch, saving
where it is after each (:mod:`app.pact_migration_run_store`) so the wizard's **Copy** step can show
progress, the page can be left, and a stopped run resumes.

What the wizard adds to the command, all applied before anything is sent:

* **Kinds** — only the chosen record kinds are read and copied.
* **Labels and tags** — left off the pacticipants and versions when not chosen.
* **History depth** — verification results: all, the latest of each pact, or none; versions: all,
  or only those the workspace's clean-up rules would keep (the pacts and results of a version left
  behind stay behind with it).
* **Conflicts** — when Apiome already records a pact or a current deployment differently: keep
  Apiome's (counted as skipped, with a log line) or replace it with the source's.

**Nothing is dropped silently.** A record left behind by a choice is counted as skipped and the log
says why; a refused record is listed with its code and reason; what the source holds that cannot be
carried over is a finding.

**The credentials are never stored.** They live in the :class:`~app.pact_migration_source.SourceBroker`
the job holds while it runs. A resumed run is given them again.

Jobs run on daemon threads of the worker process that started them (:class:`MigrationJobs`); their
state is in the database, so any worker answers for them. A worker that goes away leaves a run the
store closes as ``stopped``, ready to resume.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, Iterator, List, Literal, Optional, Set, Tuple
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import pact_migration_run_store as store
from .config import settings
from .consumer_contract_store import ConsumerActor
from .pact_migration import CODE_MIGRATION_CONFLICT, parse_import_request, parse_timestamp
from .pact_migration_plan import DEFAULT_BATCH_BYTES, DONE_OUTCOMES, KINDS, NOT_READ, Plan, batches
from .pact_migration_source import DEFAULT_MATRIX_LIMIT, SourceBroker, SourceError, fetch_document, read_source
from .pact_migration_store import check_records, import_records
from .pact_retention import RetentionKeep, VersionFacts, plan_retention

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_RUN_BUSY",
    "CODE_RUN_INVALID",
    "MAX_FAILURES",
    "MAX_LOG_LINES",
    "MigrationJobs",
    "PactMigrationRunView",
    "RunOptionError",
    "PactMigrationRunOptions",
    "cleanup_removals",
    "latest_result_removals",
    "migration_jobs",
    "run_migration",
    "run_view",
    "strip_labels_and_tags",
    "validate_options",
]

#: A choice that cannot be honoured (HTTP 422).
CODE_RUN_INVALID = "pact-migration-run-invalid"
#: This worker is already running as many migrations as it may (HTTP 429).
CODE_RUN_BUSY = "pact-migration-run-busy"

#: Refused records kept on a run; more are counted in ``failures_dropped``.
MAX_FAILURES = 500
#: Log lines kept on a run; older ones are let go (``log_seq`` says how many were written).
MAX_LOG_LINES = 300
#: Seconds between progress writes while the source is being read.
_FLUSH_SECONDS = 2.0
#: Migrations one worker process runs at once.
MAX_JOBS_PER_WORKER = 4

#: What the source must also be asked for when versions are thinned by the clean-up rules: main
#: branches and what is deployed or released decide which versions are kept.
_CLEANUP_NEEDS = frozenset({"pacticipant", "environment", "deployment", "release"})


class RunOptionError(ValueError):
    """A choice the run cannot honour (``pact-migration-run-invalid``)."""

    code = CODE_RUN_INVALID


class PactMigrationRunOptions(BaseModel):
    """What the wizard's **Choose** step (and the command's flags) decide."""

    model_config = ConfigDict(extra="forbid")

    kinds: List[str] = Field(
        default_factory=lambda: list(KINDS),
        description="The record kinds to copy: " + ", ".join(f"`{kind}`" for kind in KINDS) + ". All by default.",
    )
    labels_and_tags: bool = Field(
        default=True, description="Copy pacticipant labels and version tags. Off: both are left behind."
    )
    results: Literal["all", "latest", "none"] = Field(
        default="all",
        description="Verification results to copy: every one, the latest of each pact, or none.",
    )
    versions: Literal["all", "kept"] = Field(
        default="all",
        description=(
            "Versions to copy: every one, or only those the workspace's clean-up rules would keep "
            "(`kept` needs saved keep-rules and `version` among `kinds`)."
        ),
    )
    conflicts: Literal["keep", "replace"] = Field(
        default="keep",
        description=(
            "When Apiome already records a pact or a current deployment differently: `keep` Apiome's "
            "(the record is skipped) or `replace` it with the source's. A verification result is never replaced."
        ),
    )
    restart: bool = Field(
        default=False, description="Ignore what earlier runs from this source imported and send everything."
    )
    matrix_limit: int = Field(
        default=DEFAULT_MATRIX_LIMIT, ge=1, le=100_000, description="Matrix rows read per integration."
    )
    batch_bytes: int = Field(
        default=DEFAULT_BATCH_BYTES,
        ge=1024,
        le=32 * 1024 * 1024,
        description="About how many bytes of records are written at a time.",
    )

    @field_validator("kinds")
    @classmethod
    def _known_kinds(cls, kinds: List[str]) -> List[str]:
        """Refuse an unknown or repeated kind, or none at all; answer them in copying order."""
        unknown = sorted(set(kinds) - set(KINDS))
        if unknown:
            raise ValueError(f"unknown kind(s): {', '.join(unknown)}")
        if len(set(kinds)) != len(kinds):
            raise ValueError("a kind is listed more than once")
        if not kinds:
            raise ValueError("choose at least one kind to copy")
        return [kind for kind in KINDS if kind in kinds]


def validate_options(options: PactMigrationRunOptions, *, mode: str, keep: Optional[RetentionKeep]) -> None:
    """Refuse choices that cannot be honoured together.

    Args:
        options: The choices.
        mode: ``dry-run`` or ``copy``.
        keep: The workspace's clean-up selectors, or ``None`` when it has no keep-rules.

    Raises:
        RunOptionError: When ``versions: kept`` is asked without keep-rules or without versions.
    """
    if mode != "copy" or options.versions != "kept":
        return
    if "version" not in options.kinds:
        raise RunOptionError("versions: 'kept' thins the versions copied, so 'version' must be among kinds")
    if keep is None:
        raise RunOptionError(
            "versions: 'kept' needs clean-up rules: save keep-rules under Contracts → Settings → Clean-up first"
        )


# =============================================================================================
# Choices applied to what the source returned
# =============================================================================================


def strip_labels_and_tags(plan: Plan) -> Tuple[int, int]:
    """Leave labels off the pacticipants and tags off the versions.

    Args:
        plan: The records read.

    Returns:
        ``(labels, tags)`` left behind.
    """
    labels = tags = 0
    for _key, record in plan.records["pacticipant"]:
        labels += len(record.get("labels") or [])
        record["labels"] = []
    for _key, record in plan.records["version"]:
        tags += len(record.get("tags") or [])
        record["tags"] = []
    return labels, tags


def latest_result_removals(plan: Plan) -> Set[str]:
    """The source keys of every verification result that is not the latest of its pact.

    Args:
        plan: The records read.

    Returns:
        The keys to leave behind: for each consumer version's pact, all but its highest-numbered result.
    """
    latest: Dict[Tuple[str, str, str], Tuple[int, str]] = {}
    for key, record in plan.records["verification"]:
        pact = (record["provider"], record["consumer"], record["consumer_version"])
        if pact not in latest or record["number"] > latest[pact][0]:
            latest[pact] = (record["number"], key)
    kept = {key for _number, key in latest.values()}
    return {key for key, _record in plan.records["verification"] if key not in kept}


def _moment(value: Any, fallback: datetime) -> datetime:
    """A source timestamp, or ``fallback`` when it has none or it cannot be read."""
    try:
        return parse_timestamp(value) or fallback
    except Exception:  # noqa: BLE001 — an unreadable time is treated as "now": the version is not aged out
        return fallback


def cleanup_removals(plan: Plan, keep: RetentionKeep, *, now: Optional[datetime] = None) -> Set[Tuple[str, str]]:
    """The versions the workspace's clean-up rules would remove if they were copied.

    The same planner the nightly clean-up uses (:func:`app.pact_retention.plan_retention`), fed with
    the source's versions: their branches and tags, their pacticipant's main branch, and whether the
    source has them deployed or released (those are always kept, as is each pacticipant's latest).

    Args:
        plan: The records read — versions, and the pacticipants and placements read beside them.
        keep: The clean-up selectors.
        now: The current time (tests pin it).

    Returns:
        ``(pacticipant, version number)`` of every version to leave behind.
    """
    moment = now or datetime.now(timezone.utc)
    in_use = {
        (record["pacticipant"], record["version"])
        for kind in ("deployment", "release")
        for _key, record in plan.records[kind]
    }
    mains = {record["name"]: record.get("main_branch") for _key, record in plan.records["pacticipant"]}
    facts: List[VersionFacts] = []
    names: List[str] = []
    by_id: Dict[str, Tuple[str, str]] = {}
    for position, (key, record) in enumerate(plan.records["version"]):
        name = record["pacticipant"]
        if name not in names:
            names.append(name)
        by_id[key] = (name, record["number"])
        facts.append(
            VersionFacts(
                id=key,
                pacticipant_id=name,
                number=record["number"],
                seq=position,
                created_at=_moment(record.get("created_at"), moment),
                branches=tuple(record.get("branches") or ()),
                in_use=(name, record["number"]) in in_use,
                tags=tuple(tag["name"] if isinstance(tag, dict) else tag for tag in record.get("tags") or ()),
            )
        )
    if not facts:
        return set()
    _plan, deletions = plan_retention(
        keep,
        [(name, name, name) for name in names],
        facts,
        now=moment,
        max_deletions=len(facts) + 1,
        main_branches=mains,
    )
    return {by_id[version_id] for ids in deletions.values() for version_id in ids}


# =============================================================================================
# What a run looks like from outside
# =============================================================================================


class PactMigrationKindProgress(BaseModel):
    """One record kind of a run."""

    kind: str = Field(description="The record kind.")
    total: int = Field(default=0, description="Records of this kind the source returned.")
    done: int = Field(default=0, description="Records dealt with so far, whatever the outcome.")
    copied: int = Field(default=0, description="Created or updated in Apiome.")
    unchanged: int = Field(default=0, description="Already in Apiome exactly as the source has them.")
    skipped: int = Field(
        default=0, description="Left behind by a choice, copied by an earlier run, or kept as Apiome has them."
    )
    failed: int = Field(default=0, description="Refused; each is listed in `failures` with its reason.")
    exists: int = Field(default=0, description="Dry run: already in Apiome.")
    would_create: int = Field(default=0, description="Dry run: would be created.")


class PactMigrationRunFinding(BaseModel):
    """Something the source holds that cannot be carried over as it is."""

    kind: str
    subject: str
    detail: str


class PactMigrationRunFailure(BaseModel):
    """A refused record."""

    kind: str
    key: str = Field(description="The record's key at the source, without its kind.")
    code: str
    message: str


class PactMigrationRunLogLine(BaseModel):
    """One log line."""

    seq: int = Field(description="Its number; pass the last one seen as `after` to read only newer lines.")
    text: str


class PactMigrationRunView(BaseModel):
    """A migration run, as the wizard and the **Past migrations** drawer read it."""

    id: str
    source: str = Field(description="The source broker's base URL.")
    host: str = Field(description="Its host, for display.")
    auth_kind: str = Field(description="`token`, `basic` or `none` — what a resume must be given again.")
    mode: str = Field(description="`dry-run` (nothing written) or `copy`.")
    status: str = Field(description="`running`, `completed`, `stopped` or `failed`.")
    phase: str = Field(description="`reading`, the record kind being copied, or `done`.")
    percent: int = Field(description="Records dealt with, of those the source returned (0 while it is being read).")
    options: PactMigrationRunOptions
    kinds: List[PactMigrationKindProgress] = Field(description="The chosen kinds, in copying order.")
    facts: Dict[str, Any] = Field(
        description=(
            "What the run learned: `product`, `cleanup_rules_set`, and — from a dry run — "
"`cleanup_would_skip` (versions the keep-rules would leave behind), `results_not_latest` and "
            "`labels_and_tags` (how many the source has)."
        )
    )
    findings: List[PactMigrationRunFinding] = Field(default_factory=list)
    failures: List[PactMigrationRunFailure] = Field(default_factory=list)
    failures_dropped: int = Field(default=0, description="Refused records counted but not listed.")
    log: List[PactMigrationRunLogLine] = Field(default_factory=list, description="Log lines after `after`.")
    log_seq: int = Field(default=0, description="The number of the newest log line.")
    error: Optional[str] = Field(default=None, description="Why a run failed, or how it came to be stopped.")
    stop_requested: bool = False
    can_resume: bool = Field(description="Whether it can be set running again (given the credentials).")
    started_by: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None
    not_read: List[str] = Field(default_factory=list, description="What a migration never reads from a source.")


def _new_counts() -> Dict[str, int]:
    """Zeroed counts of one kind."""
    return dict.fromkeys(("total", "done", "copied", "unchanged", "skipped", "failed", "exists", "would_create"), 0)


def _iso(value: Any) -> Optional[str]:
    """A stored timestamp as ISO 8601 UTC text."""
    moment = store.as_utc(value)
    return moment.isoformat().replace("+00:00", "Z") if moment else None


def run_view(row: Dict[str, Any], *, after: int = 0) -> PactMigrationRunView:
    """A stored run as the API answers it.

    Args:
        row: The run's row.
        after: Only log lines numbered above this are included.

    Returns:
        The view.
    """
    counts = row.get("counts") or {}
    kinds = [
        PactMigrationKindProgress(kind=kind, **{**_new_counts(), **counts[kind]}) for kind in KINDS if kind in counts
    ]
    total = sum(kind.total for kind in kinds)
    done = sum(kind.done for kind in kinds)
    status = row["status"]
    if total:
        percent = min(100, done * 100 // total)
    else:
        percent = 100 if status == "completed" else 0
    failed = sum(kind.failed for kind in kinds)
    try:
        options = PactMigrationRunOptions(**(row.get("options") or {}))
    except ValueError:
        options = PactMigrationRunOptions()
    resumable = status in ("stopped", "failed") or (status == "completed" and failed > 0)
    return PactMigrationRunView(
        id=row["id"],
        source=row["source"],
        host=urlsplit(row["source"]).hostname or row["source"],
        auth_kind=row["auth_kind"],
        mode=row["mode"],
        status=status,
        phase=row["phase"],
        percent=percent,
        options=options,
        kinds=kinds,
        facts=row.get("facts") or {},
        findings=[PactMigrationRunFinding(**finding) for finding in row.get("findings") or []],
        failures=[PactMigrationRunFailure(**failure) for failure in row.get("failures") or []],
        failures_dropped=int(row.get("failures_dropped") or 0),
        log=[PactMigrationRunLogLine(**line) for line in row.get("log") or [] if line.get("seq", 0) > after],
        log_seq=int(row.get("log_seq") or 0),
        error=row.get("error"),
        stop_requested=bool(row.get("stop_requested")),
        can_resume=row["mode"] == "copy" and resumable,
        started_by=row.get("started_by_label"),
        created_at=_iso(row.get("created_at")),
        finished_at=_iso(row.get("finished_at")),
        not_read=list(NOT_READ),
    )


# =============================================================================================
# The run
# =============================================================================================


class _StopRequested(Exception):  # noqa: N818 — a signal, not an error
    """The run was asked to stop."""


def _label(key: str) -> str:
    """A source key without its ``kind:`` prefix."""
    return key.split(":", 1)[1] if ":" in key else key


class _Progress:
    """A run's working state, written to the store as it goes.

    Attributes:
        phase: ``reading``, the kind being copied, or ``done``.
        counts: ``{kind: counts}`` of the chosen kinds.
        facts: What the run learned.
        plan: The plan whose findings are saved (set once the read starts).
    """

    def __init__(self, db: Any, row: Dict[str, Any], clock: Callable[[], datetime]) -> None:
        """Start from the run's row (a resumed run keeps its log).

        Args:
            db: The database.
            row: The run's row.
            clock: The current time (tests pin it).
        """
        self._db = db
        self._run_id = row["id"]
        self._clock = clock
        self._flushed_at = 0.0
        self.phase = "reading"
        self.counts: Dict[str, Dict[str, int]] = {}
        self.facts: Dict[str, Any] = dict(row.get("facts") or {})
        self.plan: Optional[Plan] = None
        self.failures: List[Dict[str, str]] = []
        self.failures_dropped = 0
        self._log: Deque[Dict[str, Any]] = deque(row.get("log") or [], maxlen=MAX_LOG_LINES)
        self._log_seq = int(row.get("log_seq") or 0)

    def say(self, text: str) -> None:
        """Add a log line, and save progress if it has not been saved for a moment."""
        self._log_seq += 1
        self._log.append({"seq": self._log_seq, "text": f"{self._clock().strftime('%H:%M:%S')} {text}"})
        if time.monotonic() - self._flushed_at >= _FLUSH_SECONDS:
            self.flush()

    def fail(self, kind: str, key: str, code: str, message: str) -> None:
        """Count a refused record, keep it for the report and log it."""
        self.counts[kind]["failed"] += 1
        self.counts[kind]["done"] += 1
        if len(self.failures) < MAX_FAILURES:
            self.failures.append({"kind": kind, "key": _label(key), "code": code, "message": message})
        else:
            self.failures_dropped += 1
        self.say(f"{kind}  {_label(key)}  failed: {message}")

    def flush(self) -> None:
        """Save progress.

        Raises:
            _StopRequested: When the run was asked to stop (or is no longer running).
        """
        self._flushed_at = time.monotonic()
        findings = [
            {"kind": finding.kind, "subject": finding.subject, "detail": finding.detail}
            for finding in (self.plan.findings if self.plan else [])
        ]
        stop = store.save_progress(
            self._db,
            self._run_id,
            phase=self.phase,
            counts=self.counts,
            facts=self.facts,
            findings=findings,
            failures=self.failures,
            failures_dropped=self.failures_dropped,
            log=list(self._log),
            log_seq=self._log_seq,
        )
        if stop:
            raise _StopRequested()


def _ready(
    broker: SourceBroker,
    pending: List[Tuple[str, Dict[str, Any]]],
    to_fetch: Dict[str, str],
    progress: _Progress,
    plan: Plan,
    left_behind: Set[Tuple[str, str]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield the pending records of one kind, each pact or result document read just before it is written.

    A document the source no longer returns is a failure with the reason. A result recorded for a
    provider version the clean-up rules leave behind is skipped, with a log line.
    """
    for key, record in pending:
        kind = record["kind"]
        if kind in ("pact", "verification") and key in to_fetch:
            problem = fetch_document(broker, record, to_fetch[key], plan)
            if problem:
                progress.fail(kind, key, "source-unreadable", problem)
                continue
            provider_version = (record.get("result") or {}).get("providerApplicationVersion")
            if kind == "verification" and (record["provider"], provider_version) in left_behind:
                progress.counts[kind]["skipped"] += 1
                progress.counts[kind]["done"] += 1
                progress.say(f"verification  {_label(key)}  skipped: clean-up would remove its provider version")
                continue
        yield key, record


def _choices(
    plan: Plan,
    options: PactMigrationRunOptions,
    keep: Optional[RetentionKeep],
    progress: _Progress,
    *,
    dry_run: bool,
    now: datetime,
) -> Tuple[Dict[str, str], Set[Tuple[str, str]]]:
    """Work out which records the choices leave behind.

    A dry run leaves nothing behind (it checks everything) but records what the choices would do
    (``cleanup_would_skip``, ``results_not_latest``), so the **Choose** step can say so.

    Returns:
        ``{source key: why it is left behind}``, and the versions the clean-up rules leave behind.
    """
    skip: Dict[str, str] = {}
    not_latest = latest_result_removals(plan)
    removed = cleanup_removals(plan, keep, now=now) if keep is not None else set()
    if dry_run:
        progress.facts["results_not_latest"] = len(not_latest)
        progress.facts["cleanup_would_skip"] = len(removed) if keep is not None else None
        progress.facts["labels_and_tags"] = sum(
            len(record.get("labels") or []) for _key, record in plan.records["pacticipant"]
        ) + sum(len(record.get("tags") or []) for _key, record in plan.records["version"])
        return skip, set()

    if not options.labels_and_tags:
        labels, tags = strip_labels_and_tags(plan)
        progress.say(f"Leaving {labels} label(s) and {tags} tag(s) behind: labels and tags were not chosen")
    if options.results == "none":
        skip.update({key: "results were not chosen" for key, _record in plan.records["verification"]})
    elif options.results == "latest":
        skip.update({key: "not the latest result of its pact" for key in not_latest})
    if options.versions != "kept":
        return skip, set()
    for key, record in plan.records["version"]:
        if (record["pacticipant"], record["number"]) in removed:
            skip[key] = "clean-up would remove it"
    for kind in ("pact", "verification"):
        for key, record in plan.records[kind]:
            if (record["consumer"], record["consumer_version"]) in removed:
                skip.setdefault(key, "clean-up would remove its consumer version")
    return skip, removed


def _copy_kind(
    db: Any,
    row: Dict[str, Any],
    kind: str,
    broker: SourceBroker,
    plan: Plan,
    to_fetch: Dict[str, str],
    options: PactMigrationRunOptions,
    progress: _Progress,
    skip: Dict[str, str],
    left_behind: Set[Tuple[str, str]],
    done: Set[str],
    actor: ConsumerActor,
) -> None:
    """Copy (or, in a dry run, check) every record of one kind, batch by batch."""
    dry_run = row["mode"] == "dry-run"
    counts = progress.counts[kind]
    progress.phase = kind
    pending: List[Tuple[str, Dict[str, Any]]] = []
    reasons: Dict[str, int] = {}
    for key, record in plan.records[kind]:
        reason = skip.get(key) or ("an earlier run copied it" if key in done else None)
        if reason is None:
            pending.append((key, record))
            continue
        counts["skipped"] += 1
        counts["done"] += 1
        reasons[reason] = reasons.get(reason, 0) + 1
    for reason, number in reasons.items():
        progress.say(f"{kind}  {number} skipped: {reason}")
    if pending:
        progress.say(f"{'Checking' if dry_run else 'Copying'} {len(pending)} {kind} record(s)")

    replace = options.conflicts == "replace"
    for batch in batches(
        _ready(broker, pending, to_fetch, progress, plan, left_behind), max_bytes=options.batch_bytes
    ):
        raw = json.dumps({"source": row["source"], "records": [record for _key, record in batch]}).encode("utf-8")
        request = parse_import_request(raw, max_pact_bytes=settings.pact_max_bytes)
        if dry_run:
            results = check_records(db, row["tenant_id"], request)
        else:
            results = import_records(db, row["tenant_id"], request, actor=actor, replace_conflicts=replace)
        imported: List[str] = []
        for (key, record), result in zip(batch, results):
            outcome = result.outcome
            if outcome == "refused" and result.code == CODE_MIGRATION_CONFLICT and not replace and not dry_run:
                counts["skipped"] += 1
                counts["done"] += 1
                progress.facts["conflicts_kept"] = int(progress.facts.get("conflicts_kept") or 0) + 1
                progress.say(f"{kind}  {_label(key)}  skipped: kept Apiome's ({result.message})")
            elif outcome == "refused":
                progress.fail(kind, key, result.code or "refused", result.message or "refused without a reason")
            else:
                column = {
                    "created": "copied",
                    "updated": "copied",
                    "unchanged": "unchanged",
                    "exists": "exists",
                    "would-create": "would_create",
                }[outcome]
                counts[column] += 1
                counts["done"] += 1
                if outcome in DONE_OUTCOMES:
                    imported.append(key)
            if kind in ("pact", "verification"):
                record["content" if kind == "pact" else "result"] = None  # free the document
        if imported:
            store.add_done(db, row["id"], imported)
        progress.say(f"{kind}  {counts['done']} of {counts['total']}")
        progress.flush()


def run_migration(
    db: Any,
    row: Dict[str, Any],
    broker: SourceBroker,
    *,
    actor: ConsumerActor,
    keep: Optional[RetentionKeep] = None,
    clock: Optional[Callable[[], datetime]] = None,
) -> str:
    """Run one migration to its end, saving progress as it goes.

    Args:
        db: The database.
        row: The run's row (running).
        broker: The source, holding the credentials; closed when the run ends.
        actor: Who started (or resumed) the run — the author of everything it writes.
        keep: The workspace's clean-up selectors, or ``None`` when it has no keep-rules.
        clock: The current time (tests pin it).

    Returns:
        The status the run ended with: ``completed``, ``stopped`` or ``failed``. Never raises: a
        failure is recorded on the run.
    """
    now = clock or (lambda: datetime.now(timezone.utc))
    progress = _Progress(db, row, now)
    status, error = "completed", None
    try:
        options = PactMigrationRunOptions(**(row.get("options") or {}))
        dry_run = row["mode"] == "dry-run"
        chosen = list(KINDS) if dry_run else options.kinds
        reading = set(chosen)
        if dry_run or options.versions == "kept":
            reading |= _CLEANUP_NEEDS
        plan = Plan()
        progress.plan = plan
        progress.say(f"Reading {broker.host}")
        to_fetch = read_source(broker, plan, kinds=reading, matrix_limit=options.matrix_limit, progress=progress.say)
        progress.counts = {kind: {**_new_counts(), "total": len(plan.records[kind])} for kind in chosen}
        skip, left_behind = _choices(plan, options, keep, progress, dry_run=dry_run, now=now())
        done: Set[str] = set()
        if not dry_run and not options.restart:
            done = store.done_keys(db, row["tenant_id"], row["source"])
        progress.flush()
        for kind in chosen:
            _copy_kind(db, row, kind, broker, plan, to_fetch, options, progress, skip, left_behind, done, actor)
        progress.phase = "done"
        failed = sum(counts["failed"] for counts in progress.counts.values())
        progress.say(
            ("Checked: nothing was written" if dry_run else "Copied")
            + (f"; {failed} record(s) failed" if failed else "")
        )
    except _StopRequested:
        status, error = "stopped", "Stopped. Resume it to carry on where it stopped."
    except SourceError as exc:
        status, error = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001 — a job must end with a status, whatever broke
        logger.exception("pact migration run %s broke", row.get("id"))
        status, error = "failed", f"Apiome could not go on ({type(exc).__name__}). Nothing is lost: resume it."
    finally:
        broker.close()
    try:
        if status != "stopped":
            try:
                progress.flush()
            except _StopRequested:
                pass  # It ended on its own before the stop was seen; the status below says how.
        store.finish_run(db, row["id"], status, error=error)
    except Exception:  # noqa: BLE001 — the row is closed as stale later
        logger.exception("pact migration run %s could not record its end", row.get("id"))
    return status


class MigrationJobs:
    """The migrations this worker process is running, each on its own daemon thread.

    Daemon threads, so a worker that is shut down does not wait for a migration: the run's row stops
    being heard from, is closed as ``stopped``, and resumes when asked.
    """

    def __init__(self, limit: int = MAX_JOBS_PER_WORKER) -> None:
        """Create the registry.

        Args:
            limit: Migrations run at once by this process.
        """
        self._limit = limit
        self._lock = threading.Lock()
        self._active = 0

    def has_room(self) -> bool:
        """Whether this process may start another migration."""
        with self._lock:
            return self._active < self._limit

    def start(self, work: Callable[[], Any]) -> None:
        """Run ``work`` on a daemon thread.

        Args:
            work: The run (it never raises).
        """
        with self._lock:
            self._active += 1

        def target() -> None:
            try:
                work()
            finally:
                with self._lock:
                    self._active -= 1

        threading.Thread(target=target, name="pact-migration", daemon=True).start()


#: The process-wide registry the routes use.
migration_jobs = MigrationJobs()
