"""Scheduled provider verification: the definition, the alert machine, the payload — CTG-4.4 (#4501).

CTG-4.3 made a deployment checkable. This module makes the check *recurring* and its failures
*loud*, and — like its sibling :mod:`app.provider_verification` — it is pure: it decides things and
builds things, and touches neither the database nor the network.

Three decisions live here.

**What a schedule is.** A standing instruction: verify one published version against one registered
deployment every ``cadence_seconds``, with the CTG-4.3 run options (mutation opt-in, fixtures) and
the ECA-1.1 compiler options stored alongside. The cadence is an interval, not a cron expression —
the same vocabulary every other periodic worker in the platform speaks (repository refresh, MCP
discovery, catalog digests) — and :data:`CADENCE_PRESETS` names the intervals people actually ask
for. A five-minute floor is the smallest useful spacing against a live deployment; anything shorter
is a load test wearing a monitor's clothes.

**When to notify.** The acceptance criterion is exact: *a pass→fail transition triggers exactly one
alert*. :func:`decide_alert` is that rule as a function of the previous state and this tick's
outcome, with one deliberate addition — an unhealthy tick whose **violation set changed** speaks
again, because "it is still failing" and "it is failing in a new place" are different facts and
swallowing the second is how a second regression hides behind the first. Sameness is decided by
:func:`run_fingerprint`, a digest over the located violations rather than over the report (whose
timestamps and durations differ on every tick).

**What the alert says.** :func:`build_alert_payload` renders the conformance summary and the
violating operations, capped: an alert nobody can read because it carries four hundred operations is
an alert nobody reads. What is dropped is *counted*, never silently omitted.

Delivery, signing, retry, and dead-letter semantics are the standard push-webhook ones and are not
touched here — see :mod:`app.verification_schedule_notifications`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contract_suite import ContractSuiteOptions
from .provider_verification import (
    ConformanceReport,
    DriftFinding,
    OperationConformance,
    ProviderVerificationOptions,
)

__all__ = [
    "ALERT_REASON_NEW_VIOLATIONS",
    "ALERT_REASON_RECOVERED",
    "ALERT_REASON_TRANSITION",
    "ALERT_STATE_ALERTING",
    "ALERT_STATE_OK",
    "CADENCE_PRESETS",
    "CODE_CADENCE_INVALID",
    "CODE_NOT_FOUND",
    "CODE_SLUG_INVALID",
    "CODE_PAIR_TAKEN",
    "CODE_SLUG_TAKEN",
    "CODE_TARGET_UNKNOWN",
    "CODE_VERSION_REF_INVALID",
    "MAX_ALERT_DRIFT_PER_OPERATION",
    "MAX_ALERT_MESSAGE_CHARS",
    "MAX_ALERT_OPERATIONS",
    "MAX_CADENCE_SECONDS",
    "MIN_CADENCE_SECONDS",
    "RUN_STATUSES",
    "STATUS_ERRORED",
    "STATUS_FAILED",
    "STATUS_PASSED",
    "AlertDecision",
    "AlertState",
    "ScheduleValidationError",
    "TickOutcome",
    "VerificationScheduleInput",
    "VerificationSchedulePatch",
    "VerificationScheduleRecord",
    "VerificationScheduleRunRecord",
    "build_alert_payload",
    "decide_alert",
    "freshness_seconds",
    "record_from_row",
    "run_record_from_row",
    "resolve_cadence_seconds",
    "run_fingerprint",
    "summarize_tick",
    "validate_schedule_slug",
    "validate_version_ref",
]

# ---------------------------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------------------------

#: A tick that verified clean.
STATUS_PASSED = "passed"
#: A tick whose deployment contradicted the contract.
STATUS_FAILED = "failed"
#: A tick that produced no verdict to trust — the deployment never answered, or the run could not
#: be executed at all. Distinct from ``failed`` because "we looked and it is wrong" and "we could
#: not look" must not read the same to a gate.
STATUS_ERRORED = "errored"

#: The closed vocabulary a run row may carry, mirroring V253's CHECK constraint.
RUN_STATUSES = (STATUS_PASSED, STATUS_FAILED, STATUS_ERRORED)

#: No alert is outstanding: the last tick was healthy (or none has run).
ALERT_STATE_OK = "ok"
#: An alert is outstanding: the last tick was unhealthy and has been notified.
ALERT_STATE_ALERTING = "alerting"

#: This tick crossed from healthy to unhealthy — the pass→fail transition.
ALERT_REASON_TRANSITION = "transition"
#: Still unhealthy, but the violation set changed: new drift behind the old.
ALERT_REASON_NEW_VIOLATIONS = "new-violations"
#: Healthy again after an outstanding alert.
ALERT_REASON_RECOVERED = "recovered"

#: The smallest spacing a schedule may use. Five minutes, matched to V253's CHECK: shorter than
#: this against a live deployment is load, not monitoring.
MIN_CADENCE_SECONDS = 300
#: The largest. Thirty days — beyond that "scheduled" stops meaning anything.
MAX_CADENCE_SECONDS = 2592000

#: Named cadences, so a caller can ask for what they mean rather than compute seconds. The API
#: accepts either a preset name or an explicit second count.
CADENCE_PRESETS: Dict[str, int] = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "hourly": 3600,
    "6h": 21600,
    "12h": 43200,
    "daily": 86400,
    "weekly": 604800,
}

#: Most operations an alert payload enumerates. An alert carrying every operation of a large API is
#: one nobody reads; the count of what was dropped is always reported beside the list.
MAX_ALERT_OPERATIONS = 20
#: Most located violations reported per operation. The same reasoning, one level down.
MAX_ALERT_DRIFT_PER_OPERATION = 5
#: Longest human message carried into an alert. Bounded here rather than trusted, because the
#: message originates in a response body the deployment controls.
MAX_ALERT_MESSAGE_CHARS = 500

#: The handle shape, borrowed from ECA-1.2 so a schedule handle and a target handle are the same
#: kind of thing. Validated through :func:`validate_schedule_slug` so the error code says
#: "schedule", not "target".
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")

#: A version reference the CTG-4.3 service can resolve: ``project/{slug}/{version}`` or
#: ``catalog/{item}/{version}``. Checked for shape only — whether it *exists* is the resolver's
#: question, asked at run time, because a version can be published after its schedule is defined.
_VERSION_REF_RE = re.compile(r"^(project|catalog)/[^/\s]{1,200}/[^/\s]{1,200}$")

#: The schedule handle is unusable.
CODE_SLUG_INVALID = "schedule-slug-invalid"
#: The handle already belongs to a live schedule in this tenant.
CODE_SLUG_TAKEN = "schedule-slug-taken"
#: The cadence is outside the supported band, or is not a recognised preset.
CODE_CADENCE_INVALID = "schedule-cadence-invalid"
#: The version reference is not shaped like one.
CODE_VERSION_REF_INVALID = "schedule-version-ref-invalid"
#: The named verification target does not exist in this tenant.
CODE_TARGET_UNKNOWN = "schedule-target-unknown"
#: No such schedule in this tenant.
CODE_NOT_FOUND = "schedule-not-found"
#: A live schedule already watches this (version, deployment) pair.
CODE_PAIR_TAKEN = "schedule-pair-taken"


class ScheduleValidationError(ValueError):
    """A schedule was refused, with a stable code a route maps to a status.

    Attributes:
        code: One of the ``schedule-*`` codes in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------


def validate_schedule_slug(slug: str) -> str:
    """Return ``slug`` when it is a usable handle, else refuse.

    Args:
        slug: The proposed handle.

    Returns:
        The trimmed slug.

    Raises:
        ScheduleValidationError: :data:`CODE_SLUG_INVALID` when the shape is unusable.
    """
    candidate = (slug or "").strip()
    if not _SLUG_RE.match(candidate):
        raise ScheduleValidationError(
            CODE_SLUG_INVALID,
            "slug must be 1-128 lowercase letters, digits, or hyphens, starting and ending "
            "with a letter or digit (e.g. 'petstore-staging')",
        )
    return candidate


def validate_version_ref(version_ref: str) -> str:
    """Return ``version_ref`` when it is shaped like a reference the resolver accepts.

    Shape only. Whether the version exists is asked at run time, not at definition time: a team
    may reasonably define the schedule for a version their pipeline is about to publish, and a
    reference that stops resolving later must surface as a failing *tick* — visible in the run
    history — rather than as a schedule that silently could not be saved.

    Args:
        version_ref: The proposed reference.

    Returns:
        The trimmed reference.

    Raises:
        ScheduleValidationError: :data:`CODE_VERSION_REF_INVALID` when the shape is wrong.
    """
    candidate = (version_ref or "").strip()
    if not _VERSION_REF_RE.match(candidate):
        raise ScheduleValidationError(
            CODE_VERSION_REF_INVALID,
            "version_ref must be 'project/{slug}/{version}' or 'catalog/{item}/{version}' "
            "(e.g. 'project/petstore/1.0.0')",
        )
    return candidate


def resolve_cadence_seconds(cadence: Any) -> int:
    """Return the cadence in seconds, accepting a preset name or an explicit count.

    Args:
        cadence: A :data:`CADENCE_PRESETS` key (``"hourly"``), or a number of seconds.

    Returns:
        The cadence in seconds, inside ``[MIN_CADENCE_SECONDS, MAX_CADENCE_SECONDS]``.

    Raises:
        ScheduleValidationError: :data:`CODE_CADENCE_INVALID` for an unknown preset, a
            non-numeric value, or a count outside the supported band.
    """
    if isinstance(cadence, str):
        key = cadence.strip().lower()
        if key in CADENCE_PRESETS:
            return CADENCE_PRESETS[key]
        if not key.isdigit():
            raise ScheduleValidationError(
                CODE_CADENCE_INVALID,
                "cadence must be a number of seconds or one of: "
                + ", ".join(sorted(CADENCE_PRESETS)),
            )
        cadence = int(key)
    if isinstance(cadence, bool) or not isinstance(cadence, (int, float)):
        raise ScheduleValidationError(
            CODE_CADENCE_INVALID,
            "cadence must be a number of seconds or one of: "
            + ", ".join(sorted(CADENCE_PRESETS)),
        )
    seconds = int(cadence)
    if seconds < MIN_CADENCE_SECONDS or seconds > MAX_CADENCE_SECONDS:
        raise ScheduleValidationError(
            CODE_CADENCE_INVALID,
            f"cadence must be between {MIN_CADENCE_SECONDS} and {MAX_CADENCE_SECONDS} seconds "
            f"({MIN_CADENCE_SECONDS // 60} minutes to {MAX_CADENCE_SECONDS // 86400} days)",
        )
    return seconds


# ---------------------------------------------------------------------------------------------
# Definition models
# ---------------------------------------------------------------------------------------------


class VerificationScheduleInput(BaseModel):
    """A complete schedule definition, as a caller supplies it on create."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(
        description="Stable handle CI and the UI address the schedule by.", max_length=128
    )
    name: str = Field(description="Human-readable display name.", min_length=1, max_length=200)
    description: Optional[str] = Field(
        default=None, description="Operator note: what this schedule is watching, and why.",
        max_length=2000,
    )
    version_ref: str = Field(
        description="`project/{slug}/{version}` or `catalog/{item}/{version}` to verify.",
        max_length=500,
    )
    target_ref: str = Field(
        description="Verification target slug or id (ECA-1.2) naming the deployment to check.",
        min_length=1,
        max_length=200,
    )
    cadence: Any = Field(
        default="daily",
        description=(
            "How often to run: a number of seconds, or one of "
            "`5m`, `15m`, `30m`, `hourly`, `6h`, `12h`, `daily`, `weekly`."
        ),
    )
    enabled: bool = Field(
        default=True, description="Whether the schedule ticks. A paused schedule keeps its history."
    )
    alert_on_recovery: bool = Field(
        default=True,
        description="Notify when a drifting deployment verifies clean again.",
    )
    options: ContractSuiteOptions = Field(
        default_factory=ContractSuiteOptions,
        description="ECA-1.1 compiler options, hashed into the suite digest each run records.",
    )
    verification: ProviderVerificationOptions = Field(
        default_factory=ProviderVerificationOptions,
        description=(
            "What each run may send. Safe methods only by default; mutating operations require "
            "both `allow_mutating` and a fixture naming the operation, and a fixture carrying a "
            "credential header is refused before it is stored."
        ),
    )


class VerificationSchedulePatch(BaseModel):
    """A partial update. Every field is optional; only what is set is changed."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    cadence: Optional[Any] = Field(default=None, description="New cadence (seconds or preset).")
    enabled: Optional[bool] = Field(default=None, description="Pause or resume the schedule.")
    alert_on_recovery: Optional[bool] = Field(default=None)
    options: Optional[ContractSuiteOptions] = Field(default=None)
    verification: Optional[ProviderVerificationOptions] = Field(default=None)

    def has_changes(self) -> bool:
        """True when the patch actually sets something."""
        return bool(self.model_dump(exclude_unset=True))


class VerificationScheduleRecord(BaseModel):
    """A stored schedule, as every reader sees it.

    There is no redacted variant: a schedule holds a *reference* to a target, and the target holds
    a *reference* to a credential, so nothing here can be a secret.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Schedule id.")
    tenant_id: str = Field(description="Tenant that owns it.")
    slug: str = Field(description="Stable handle.")
    name: str = Field(description="Display name.")
    description: Optional[str] = Field(default=None, description="Operator note.")
    version_ref: str = Field(description="Version reference verified on each tick.")
    target_id: str = Field(description="The verification target's id.")
    target_slug: str = Field(description="The target's handle at definition time.")
    cadence_seconds: int = Field(description="Interval between ticks, in seconds.")
    enabled: bool = Field(description="Whether the schedule ticks.")
    alert_on_recovery: bool = Field(description="Whether recovery notifies.")
    options: ContractSuiteOptions = Field(
        default_factory=ContractSuiteOptions, description="Compiler options each run uses."
    )
    verification: ProviderVerificationOptions = Field(
        default_factory=ProviderVerificationOptions, description="Run options each tick uses."
    )
    last_run_at: Optional[datetime] = Field(
        default=None, description="When the schedule last ticked, whatever the outcome."
    )
    last_status: Optional[str] = Field(
        default=None, description="`passed`, `failed`, or `errored`; null before the first tick."
    )
    last_success_at: Optional[datetime] = Field(
        default=None, description="When it last verified clean — the freshness anchor."
    )
    last_report_id: Optional[str] = Field(
        default=None, description="The newest conformance report this schedule produced."
    )
    consecutive_failures: int = Field(
        default=0, description="Unhealthy ticks since the last clean one."
    )
    run_count: int = Field(default=0, description="Ticks recorded for this schedule.")
    alert_state: str = Field(
        default=ALERT_STATE_OK, description="`ok`, or `alerting` while drift is outstanding."
    )
    alert_fingerprint: Optional[str] = Field(
        default=None, description="Digest of the violation set last alerted on."
    )
    last_alert_at: Optional[datetime] = Field(
        default=None, description="When an alert was last sent."
    )
    freshness_seconds: Optional[int] = Field(
        default=None,
        description=(
            "Seconds since the last clean verification, computed at read time. Null when this "
            "schedule has never verified clean — which a gate must read as 'unknown', never as "
            "'fresh'."
        ),
    )
    created_at: Optional[datetime] = Field(default=None, description="When it was defined.")
    updated_at: Optional[datetime] = Field(default=None, description="When it last changed.")
    created_by: Optional[str] = Field(default=None, description="User who defined it.")
    updated_by: Optional[str] = Field(default=None, description="User who last changed it.")

    @field_validator("alert_state")
    @classmethod
    def _known_alert_state(cls, value: str) -> str:
        """Reject an alert state outside the closed vocabulary."""
        if value not in (ALERT_STATE_OK, ALERT_STATE_ALERTING):
            raise ValueError(f"alert_state must be '{ALERT_STATE_OK}' or '{ALERT_STATE_ALERTING}'")
        return value


class VerificationScheduleRunRecord(BaseModel):
    """One recorded tick — the write-once history row, as a reader sees it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Run-history row id.")
    tenant_id: str = Field(description="Tenant that owns it.")
    schedule_id: str = Field(description="The schedule that ticked.")
    report_id: Optional[str] = Field(
        default=None, description="The conformance report, when one was produced and stored."
    )
    run_id: Optional[str] = Field(
        default=None, description="The ECA-1.3 evidence run behind the report."
    )
    status: str = Field(description="`passed`, `failed`, or `errored`.")
    error_code: Optional[str] = Field(
        default=None,
        description=(
            "Set only when the run could not be executed at all (the version stopped compiling, "
            "the target was withdrawn). A deployment that answered wrongly is `failed` with no "
            "error code; one that never answered is `errored` with none either."
        ),
    )
    error_message: Optional[str] = Field(default=None, description="Remediation text, when refused.")
    operations_total: int = Field(default=0, description="Operations the specification declares.")
    operations_exercised: int = Field(default=0, description="Operations that received a request.")
    operations_failed: int = Field(default=0, description="Exercised operations that drifted.")
    coverage_percent: float = Field(default=0.0, description="Exercised over total, as a percent.")
    drift_count: int = Field(default=0, description="Located disagreements observed.")
    drift_fingerprint: Optional[str] = Field(
        default=None, description="Digest of the violation set; null for a clean tick."
    )
    alerted: bool = Field(default=False, description="Whether this tick notified.")
    alert_reason: Optional[str] = Field(
        default=None, description="`transition`, `new-violations`, or `recovered`."
    )
    alert_deliveries: int = Field(
        default=0, description="Webhook deliveries enqueued for this tick's alert."
    )
    started_at: Optional[datetime] = Field(default=None, description="When the tick began.")
    finished_at: Optional[datetime] = Field(default=None, description="When it ended.")
    duration_ms: int = Field(default=0, description="Wall-clock duration in milliseconds.")
    created_at: Optional[datetime] = Field(default=None, description="When it was recorded.")


# ---------------------------------------------------------------------------------------------
# The tick: what one execution produced
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TickOutcome:
    """What one scheduled execution produced, before anything is stored or notified.

    Attributes:
        status: ``passed``, ``failed``, or ``errored``.
        report: The conformance report, when the run executed.
        report_id: The stored report's id, when persistence succeeded.
        run_id: The ECA-1.3 evidence run id, when a run was recorded.
        error_code: Taxonomy code, set only when the run could not be executed at all.
        error_message: Remediation text for that refusal.
        started_at: When execution began.
        finished_at: When it ended.
    """

    status: str
    report: Optional[ConformanceReport] = None
    report_id: Optional[str] = None
    run_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def healthy(self) -> bool:
        """True when this tick verified clean."""
        return self.status == STATUS_PASSED

    @property
    def duration_ms(self) -> int:
        """Wall-clock duration, or 0 when the tick was not timed."""
        if self.started_at is None or self.finished_at is None:
            return 0
        delta = (self.finished_at - self.started_at).total_seconds() * 1000.0
        return max(0, int(delta))


def summarize_tick(outcome: TickOutcome) -> Dict[str, Any]:
    """Reduce a tick to the trend columns the history row stores.

    The counts are read from the report rather than accepted separately, so a stored history row
    can never contradict the report it points at — the same rule
    :func:`app.provider_verification_store.save_report` applies one level up.

    Args:
        outcome: The tick.

    Returns:
        ``operations_total`` / ``operations_exercised`` / ``operations_failed`` /
        ``coverage_percent`` / ``drift_count``, all zero when no report was produced.
    """
    report = outcome.report
    if report is None:
        return {
            "operations_total": 0,
            "operations_exercised": 0,
            "operations_failed": 0,
            "coverage_percent": 0.0,
            "drift_count": 0,
        }
    coverage = report.coverage
    return {
        "operations_total": coverage.operations_total,
        "operations_exercised": coverage.operations_exercised,
        "operations_failed": coverage.operations_failed,
        "coverage_percent": coverage.coverage_percent,
        "drift_count": len(report.drift),
    }


# ---------------------------------------------------------------------------------------------
# The alert machine
# ---------------------------------------------------------------------------------------------


def _drift_identity(finding: DriftFinding) -> str:
    """The part of a drift finding that identifies *which* disagreement it is.

    Deliberately excludes ``actual`` and ``message``: a deployment returning a different wrong id
    on every request is the same violation, and folding the value in would make every tick look
    like new drift and reinstate exactly the alert storm this module exists to prevent.

    Args:
        finding: The located violation.

    Returns:
        A stable identity string.
    """
    return "|".join(
        (
            finding.operation_key,
            finding.case_id,
            finding.kind,
            finding.code,
            finding.pointer or "",
            finding.expected or "",
        )
    )


def run_fingerprint(
    *,
    status: str,
    drift: Sequence[DriftFinding] = (),
    error_code: Optional[str] = None,
) -> Optional[str]:
    """A stable digest of *what is wrong* this tick, or ``None`` when nothing is.

    Two unhealthy ticks share a fingerprint exactly when they found the same set of violations, in
    any order. That is what lets a repeat failure stay quiet while a changed one speaks.

    A tick that could not run at all has no violations to digest, so its fingerprint is derived
    from the refusal code: a version that keeps failing to compile notifies once, and a *different*
    refusal is still new news.

    Args:
        status: The tick's status.
        drift: The located violations, when the run executed.
        error_code: The refusal code, when it did not.

    Returns:
        ``sha256:<hex>``, or ``None`` for a healthy tick.
    """
    if status == STATUS_PASSED:
        return None
    parts = sorted(_drift_identity(finding) for finding in drift)
    if not parts and error_code:
        parts = [f"error:{error_code}"]
    material = "\n".join([status, *parts])
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AlertState:
    """The alerting state carried on a schedule between ticks.

    Attributes:
        state: :data:`ALERT_STATE_OK` or :data:`ALERT_STATE_ALERTING`.
        fingerprint: The violation-set digest last alerted on, when alerting.
    """

    state: str = ALERT_STATE_OK
    fingerprint: Optional[str] = None


@dataclass(frozen=True)
class AlertDecision:
    """Whether this tick notifies, and what the schedule's state becomes.

    Attributes:
        notify: Whether to fan an alert out.
        reason: :data:`ALERT_REASON_TRANSITION`, :data:`ALERT_REASON_NEW_VIOLATIONS`, or
            :data:`ALERT_REASON_RECOVERED`; ``None`` when nothing is sent.
        next_state: The alert state to persist.
        next_fingerprint: The fingerprint to persist.
    """

    notify: bool
    reason: Optional[str]
    next_state: str
    next_fingerprint: Optional[str]


def decide_alert(
    *,
    status: str,
    fingerprint: Optional[str],
    previous: AlertState,
    alert_on_recovery: bool = True,
) -> AlertDecision:
    """Decide whether this tick notifies — the "exactly one alert" rule, as a function.

    ==========================  =====================  ===========================================
    Previous state              This tick              Result
    ==========================  =====================  ===========================================
    ``ok``                      healthy                silent, stays ``ok``
    ``ok``                      unhealthy              **alert** (``transition``) → ``alerting``
    ``alerting``                unhealthy, same set    silent, stays ``alerting``
    ``alerting``                unhealthy, new set     **alert** (``new-violations``)
    ``alerting``                healthy                **alert** (``recovered``) → ``ok``
    ==========================  =====================  ===========================================

    **Recovery always clears the state, even when it is not announced.** With
    ``alert_on_recovery`` false the recovery is silent, but the schedule still returns to ``ok`` —
    otherwise the next failure would be filed as "new violations" rather than a transition, and a
    tenant who muted recovery notices would eventually be muted about failures too.

    Args:
        status: This tick's status.
        fingerprint: This tick's violation-set digest (``None`` when healthy).
        previous: The state carried on the schedule row.
        alert_on_recovery: Whether a return to healthy is announced.

    Returns:
        The decision, including the state to persist.
    """
    was_alerting = previous.state == ALERT_STATE_ALERTING
    if status == STATUS_PASSED:
        if was_alerting:
            return AlertDecision(
                notify=bool(alert_on_recovery),
                reason=ALERT_REASON_RECOVERED if alert_on_recovery else None,
                next_state=ALERT_STATE_OK,
                next_fingerprint=None,
            )
        return AlertDecision(
            notify=False, reason=None, next_state=ALERT_STATE_OK, next_fingerprint=None
        )

    if not was_alerting:
        return AlertDecision(
            notify=True,
            reason=ALERT_REASON_TRANSITION,
            next_state=ALERT_STATE_ALERTING,
            next_fingerprint=fingerprint,
        )
    if fingerprint is not None and fingerprint != previous.fingerprint:
        return AlertDecision(
            notify=True,
            reason=ALERT_REASON_NEW_VIOLATIONS,
            next_state=ALERT_STATE_ALERTING,
            next_fingerprint=fingerprint,
        )
    # Same failure as last time: the alert already outstanding says everything this one would.
    return AlertDecision(
        notify=False,
        reason=None,
        next_state=ALERT_STATE_ALERTING,
        next_fingerprint=previous.fingerprint or fingerprint,
    )


# ---------------------------------------------------------------------------------------------
# The alert payload
# ---------------------------------------------------------------------------------------------


def freshness_seconds(
    last_success_at: Optional[datetime], *, now: Optional[datetime] = None
) -> Optional[int]:
    """Seconds since the last clean verification, or ``None`` when there has never been one.

    ``None`` means *unknown*, never *fresh*: a gate that treats "never verified" as "verified
    recently" is worse than no gate.

    Args:
        last_success_at: The freshness anchor.
        now: Reference instant, defaulting to now (UTC).

    Returns:
        A non-negative second count, or ``None``.
    """
    if last_success_at is None:
        return None
    reference = now or datetime.now(timezone.utc)
    anchor = last_success_at
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0, int((reference - anchor).total_seconds()))


def _bounded(text: Optional[str], limit: int = MAX_ALERT_MESSAGE_CHARS) -> Optional[str]:
    """Trim a deployment-controlled string to a length an alert can carry.

    Args:
        text: The value.
        limit: Maximum characters.

    Returns:
        The value, ellipsized when it was too long; ``None`` passes through.
    """
    if text is None:
        return None
    value = str(text)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _drift_payload(finding: DriftFinding) -> Dict[str, Any]:
    """Render one located violation for an alert.

    Args:
        finding: The violation.

    Returns:
        Its JSON-serializable form.
    """
    return {
        "kind": finding.kind,
        "code": finding.code,
        "caseId": finding.case_id,
        "pointer": finding.pointer,
        "expected": _bounded(finding.expected),
        "actual": _bounded(finding.actual),
        "message": _bounded(finding.message),
    }


def _operation_payload(operation: OperationConformance) -> Dict[str, Any]:
    """Render one violating operation for an alert, with its drift capped.

    Args:
        operation: The operation's conformance.

    Returns:
        Its JSON-serializable form, carrying ``driftTruncated`` when the list was cut.
    """
    shown = list(operation.drift[:MAX_ALERT_DRIFT_PER_OPERATION])
    return {
        "operationKey": operation.operation_key,
        "httpMethod": operation.http_method,
        "httpPath": operation.http_path,
        "outcome": operation.outcome,
        "casesFailed": operation.cases_failed,
        "casesErrored": operation.cases_errored,
        "drift": [_drift_payload(finding) for finding in shown],
        "driftTotal": len(operation.drift),
        "driftTruncated": len(operation.drift) > len(shown),
    }


def _violating_operations(report: ConformanceReport) -> List[OperationConformance]:
    """The operations an alert is about, most drift first.

    Ordering by drift count then key puts the operation with the most to say at the top of a
    truncated list, and keeps the order stable for two runs that found the same thing.

    Args:
        report: The conformance report.

    Returns:
        The failed and errored operations.
    """
    violating = [
        operation
        for operation in report.operations
        if operation.outcome in (STATUS_FAILED, STATUS_ERRORED)
    ]
    return sorted(violating, key=lambda op: (-len(op.drift), op.operation_key))


def build_alert_payload(
    *,
    event: str,
    reason: str,
    schedule: VerificationScheduleRecord,
    outcome: TickOutcome,
    previous_status: Optional[str],
    consecutive_failures: int,
    occurred_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Render the webhook body for one alert.

    The payload answers the three questions somebody woken by it asks — *what drifted, where, and
    how long has it been wrong?* — and answers them without requiring a follow-up API call: the
    conformance summary and the violating operations are inline, capped, with the count of what was
    dropped beside the list. ``reportId`` is there for the full picture.

    Args:
        event: The event type stamped on the delivery.
        reason: Why this alert fired (:data:`ALERT_REASON_TRANSITION` and friends).
        schedule: The schedule that ticked, carrying its pre-tick state.
        outcome: What the tick produced.
        previous_status: The schedule's status before this tick, when it had one.
        consecutive_failures: Unhealthy ticks including this one (0 on recovery).
        occurred_at: The alert instant, defaulting to now (UTC).

    Returns:
        A JSON-serializable payload. No credential, request header, or response body reaches it —
        only located violations, whose values are bounded.
    """
    report = outcome.report
    operations: List[Dict[str, Any]] = []
    operations_truncated = False
    coverage: Dict[str, Any] = {}
    target: Dict[str, Any] = {
        "id": schedule.target_id,
        "slug": schedule.target_slug,
    }
    if report is not None:
        violating = _violating_operations(report)
        shown = violating[:MAX_ALERT_OPERATIONS]
        operations = [_operation_payload(operation) for operation in shown]
        operations_truncated = len(violating) > len(shown)
        summary = report.coverage
        coverage = {
            "operationsTotal": summary.operations_total,
            "operationsExercised": summary.operations_exercised,
            "operationsPassed": summary.operations_passed,
            "operationsFailed": summary.operations_failed,
            "operationsErrored": summary.operations_errored,
            "operationsSkipped": summary.operations_skipped,
            "operationsUncompiled": summary.operations_uncompiled,
            "coveragePercent": summary.coverage_percent,
            "casesTotal": summary.cases_total,
            "casesFailed": summary.cases_failed,
            "casesErrored": summary.cases_errored,
        }
        target = {
            "id": report.target.target_id or schedule.target_id,
            "slug": report.target.slug,
            "environment": report.target.environment,
            "networkClass": report.target.network_class,
            "baseUrl": report.target.base_url,
        }
        violating_total = len(violating)
    else:
        violating_total = 0

    payload: Dict[str, Any] = {
        "event": event,
        "reason": reason,
        "scheduleId": schedule.id,
        "scheduleSlug": schedule.slug,
        "scheduleName": schedule.name,
        "versionRef": schedule.version_ref,
        "target": target,
        "status": outcome.status,
        "previousStatus": previous_status,
        "suiteDigest": report.suite_digest if report is not None else None,
        "reportId": outcome.report_id,
        "runId": outcome.run_id,
        "coverage": coverage,
        "driftCount": len(report.drift) if report is not None else 0,
        "operations": operations,
        "operationsTotal": violating_total,
        "operationsTruncated": operations_truncated,
        "consecutiveFailures": consecutive_failures,
        "lastSuccessAt": _iso(schedule.last_success_at),
        "freshnessSeconds": freshness_seconds(schedule.last_success_at, now=occurred_at),
        "errorCode": outcome.error_code,
        "errorMessage": _bounded(outcome.error_message),
        "occurredAt": _iso(occurred_at or datetime.now(timezone.utc)),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _iso(value: Optional[datetime]) -> Optional[str]:
    """Render a datetime as ISO-8601, or ``None``.

    Args:
        value: The instant.

    Returns:
        The ISO string, or ``None``.
    """
    if value is None:
        return None
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.isoformat()


def record_from_row(
    row: Mapping[str, Any], *, now: Optional[datetime] = None
) -> VerificationScheduleRecord:
    """Adapt a ``verification_schedule`` row into a record, computing freshness.

    Args:
        row: The database row.
        now: Reference instant for the freshness computation.

    Returns:
        The record.
    """
    last_success_at = row.get("last_success_at")
    return VerificationScheduleRecord(
        id=str(row.get("id")),
        tenant_id=str(row.get("tenant_id")),
        slug=str(row.get("slug") or ""),
        name=str(row.get("name") or ""),
        description=row.get("description"),
        version_ref=str(row.get("version_ref") or ""),
        target_id=str(row.get("target_id") or ""),
        target_slug=str(row.get("target_slug") or ""),
        cadence_seconds=int(row.get("cadence_seconds") or MIN_CADENCE_SECONDS),
        enabled=bool(row.get("enabled", True)),
        alert_on_recovery=bool(row.get("alert_on_recovery", True)),
        options=_model_or_default(ContractSuiteOptions, row.get("suite_options")),
        verification=_model_or_default(ProviderVerificationOptions, row.get("verification")),
        last_run_at=row.get("last_run_at"),
        last_status=row.get("last_status"),
        last_success_at=last_success_at,
        last_report_id=_text(row.get("last_report_id")),
        consecutive_failures=int(row.get("consecutive_failures") or 0),
        run_count=int(row.get("run_count") or 0),
        alert_state=str(row.get("alert_state") or ALERT_STATE_OK),
        alert_fingerprint=_text(row.get("alert_fingerprint")),
        last_alert_at=row.get("last_alert_at"),
        freshness_seconds=freshness_seconds(last_success_at, now=now),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        created_by=_text(row.get("created_by")),
        updated_by=_text(row.get("updated_by")),
    )


def run_record_from_row(row: Mapping[str, Any]) -> VerificationScheduleRunRecord:
    """Adapt a ``verification_schedule_run`` row into a record.

    Args:
        row: The database row.

    Returns:
        The record.
    """
    return VerificationScheduleRunRecord(
        id=str(row.get("id")),
        tenant_id=str(row.get("tenant_id")),
        schedule_id=str(row.get("schedule_id")),
        report_id=_text(row.get("report_id")),
        run_id=_text(row.get("run_id")),
        status=str(row.get("status") or STATUS_ERRORED),
        error_code=_text(row.get("error_code")),
        error_message=row.get("error_message"),
        operations_total=int(row.get("operations_total") or 0),
        operations_exercised=int(row.get("operations_exercised") or 0),
        operations_failed=int(row.get("operations_failed") or 0),
        coverage_percent=float(row.get("coverage_percent") or 0.0),
        drift_count=int(row.get("drift_count") or 0),
        drift_fingerprint=_text(row.get("drift_fingerprint")),
        alerted=bool(row.get("alerted")),
        alert_reason=_text(row.get("alert_reason")),
        alert_deliveries=int(row.get("alert_deliveries") or 0),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        duration_ms=int(row.get("duration_ms") or 0),
        created_at=row.get("created_at"),
    )


def _model_or_default(model: Any, raw: Any) -> Any:
    """Rebuild a stored options object, falling back to its defaults.

    A stored options blob written by a newer build can carry a key this one does not know. The
    options are *how* a run is executed, not a claim about a deployment, so falling back to the
    defaults keeps the schedule ticking rather than making an unknown key silence the monitor.

    Args:
        model: The pydantic model class.
        raw: The stored JSON, or ``None``.

    Returns:
        The parsed model, or a default instance.
    """
    if not isinstance(raw, Mapping):
        return model()
    try:
        return model.model_validate(dict(raw))
    except Exception:  # noqa: BLE001 - options never justify silencing a monitor
        return model()


def _text(value: Any) -> Optional[str]:
    """Return a non-empty string, or ``None``.

    Args:
        value: The raw column value.

    Returns:
        The string, or ``None``.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None
