"""Deploy-gating verdict — CTG-4.5 (#4502).

A CD pipeline asks one question — *can I promote this API version?* — and until now the answer
lived in five places: the GOV lint grade on the revision, the CTG-3.1 breaking classification of
the publish, the CTG-4.2 per-consumer verdicts, and the CTG-4.4 freshness of the last provider
verification. Every team that wanted a gate wrote its own multi-call script, and every one of them
decided the combination rules differently.

This module is those rules, as a pure function. It knows nothing about the database, HTTP, or where
a signal came from: it takes facts that have already been read and turns them into a status.

Three decisions shape the whole thing.

**Partial inputs are the normal case, not an error.** The four signals land at different times, in
different tenants, for different projects. A signal with nothing behind it reports
:data:`STATUS_NOT_CONFIGURED` and is *excluded* from the verdict rather than failing it — otherwise
the endpoint could not ship before all four sources existed everywhere, which is exactly what the
ticket asks for. A signal that exists but could not be read reports :data:`STATUS_UNKNOWN`, which is
also excluded but counted separately, because "nobody set this up" and "this is set up and I could
not read it" are different facts and a strict pipeline may want to treat them differently.

**Thresholds are two-rung, not an on/off switch.** Each signal carries a *warn* threshold and a
*fail* threshold, either of which may be ``None`` to disable that rung. That is what lets one
vocabulary (``pass``/``warn``/``fail``) come out of four very different measurements without a
per-signal "action" dial, and it is what makes a tenant's configuration legible: "warn below B, fail
below D" says the whole policy in five words.

**The default policy has teeth.** Every other policy surface in the platform defaults to advisory,
because those gates hang off flows that already existed (publish, import) and a blocking default
would break people who never asked for one. Nothing hangs off this one: the endpoint is only reached
by a caller who chose to ask, it always answers ``200``, and it refuses nothing. So the default
fails on a breaking change and on a broken consumer, warns on a mediocre lint grade and on stale
verification, and a tenant that disagrees moves the bar.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .consumer_impact import ConsumerImpactReport

__all__ = [
    "BREAKING_SEVERITIES",
    "DEFAULT_THRESHOLDS",
    "DEPLOY_GATE_POLICY_SCHEMA_VERSION",
    "DEPLOY_GATE_SCHEMA_VERSION",
    "GATE_SIGNALS",
    "GATE_STATUSES",
    "LINT_GRADES",
    "POLICY_SOURCES",
    "POLICY_SOURCE_DEFAULT",
    "POLICY_SOURCE_PROJECT",
    "POLICY_SOURCE_TENANT",
    "SIGNAL_BREAKING",
    "SIGNAL_CONSUMERS",
    "SIGNAL_LINT",
    "SIGNAL_VERIFICATION",
    "STATUS_FAIL",
    "STATUS_NOT_CONFIGURED",
    "STATUS_PASS",
    "STATUS_UNKNOWN",
    "STATUS_WARN",
    "BreakingThresholds",
    "ConsumerThresholds",
    "DeployGatePolicyOut",
    "DeployGateReport",
    "DeployGateThresholds",
    "GateSignal",
    "GateThresholdError",
    "LintThresholds",
    "VerificationThresholds",
    "build_gate_report",
    "canonical_thresholds_body",
    "evaluate_breaking",
    "evaluate_consumers",
    "evaluate_lint",
    "evaluate_verification",
    "gate_summary",
    "overall_status",
    "status_counts",
    "thresholds_content_fingerprint",
    "thresholds_from_body",
    "unavailable_signal",
]

#: Stable identity of the gate response body.
DEPLOY_GATE_SCHEMA_VERSION = "ctg.gate.v1"

#: Stable identity of the stored threshold body.
DEPLOY_GATE_POLICY_SCHEMA_VERSION = "ctg.gate-policy.v1"

# -------------------------------------------------------------------------------------------
# Vocabulary
# -------------------------------------------------------------------------------------------

SIGNAL_LINT = "lint"
SIGNAL_BREAKING = "breaking"
SIGNAL_CONSUMERS = "consumers"
SIGNAL_VERIFICATION = "verification"

#: The four signals, in the order they are reported. Fixed so a diff of two gate responses lines up.
GATE_SIGNALS: Tuple[str, ...] = (
    SIGNAL_LINT,
    SIGNAL_BREAKING,
    SIGNAL_CONSUMERS,
    SIGNAL_VERIFICATION,
)

STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
#: Nothing has produced this signal for this project yet — excluded from the verdict.
STATUS_NOT_CONFIGURED = "not_configured"
#: The signal exists but could not be read or judged — excluded from the verdict, counted apart.
STATUS_UNKNOWN = "unknown"

GATE_STATUSES: Tuple[str, ...] = (
    STATUS_PASS,
    STATUS_WARN,
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_UNKNOWN,
)

#: Only these three take part in the overall verdict; the other two are reported and skipped.
_VERDICT_RANK: Dict[str, int] = {STATUS_PASS: 0, STATUS_WARN: 1, STATUS_FAIL: 2}

#: Letter grades from :mod:`app.schema_lint`, best first.
LINT_GRADES: Tuple[str, ...] = ("A", "B", "C", "D", "F")
_GRADE_RANK: Dict[str, int] = {grade: index for index, grade in enumerate(reversed(LINT_GRADES))}

#: Change severities from :mod:`app.change_taxonomy`, least severe first.
BREAKING_SEVERITIES: Tuple[str, ...] = ("docs-only", "non-breaking", "breaking")
_SEVERITY_RANK: Dict[str, int] = {
    severity: index for index, severity in enumerate(BREAKING_SEVERITIES)
}

POLICY_SOURCE_DEFAULT = "default"
POLICY_SOURCE_TENANT = "tenant"
POLICY_SOURCE_PROJECT = "project"
POLICY_SOURCES: Tuple[str, ...] = (
    POLICY_SOURCE_DEFAULT,
    POLICY_SOURCE_TENANT,
    POLICY_SOURCE_PROJECT,
)

# Stable machine-readable reasons. A caller branches on these; the human `detail` may be reworded.
REASON_LINT_NOT_CAPTURED = "lint-not-captured"
REASON_LINT_GRADE_UNRECOGNISED = "lint-grade-unrecognised"
REASON_LINT_BELOW_FAIL = "lint-grade-below-fail-threshold"
REASON_LINT_BELOW_WARN = "lint-grade-below-warn-threshold"
REASON_LINT_OK = "lint-grade-meets-thresholds"

REASON_BREAKING_NOT_CLASSIFIED = "breaking-not-classified"
REASON_BREAKING_CLASSIFICATION_FAILED = "breaking-classification-failed"
REASON_BREAKING_INITIAL_PUBLICATION = "breaking-initial-publication"
REASON_BREAKING_PRESENT = "breaking-changes-present"
REASON_BREAKING_WARN = "breaking-changes-warn-threshold"
REASON_BREAKING_NONE = "breaking-none"

REASON_CONSUMERS_NONE_REGISTERED = "consumers-none-registered"
REASON_CONSUMERS_NO_CHANGELOG = "consumers-no-changelog"
REASON_CONSUMERS_FORBIDDEN = "consumers-forbidden"
REASON_CONSUMERS_BREAKING = "consumers-breaking"
REASON_CONSUMERS_AFFECTED = "consumers-affected"
REASON_CONSUMERS_UNAFFECTED = "consumers-unaffected"

REASON_VERIFICATION_NEVER_RUN = "verification-never-run"
REASON_VERIFICATION_NEVER_SUCCEEDED = "verification-never-succeeded"
REASON_VERIFICATION_UNHEALTHY = "verification-last-run-unhealthy"
REASON_VERIFICATION_STALE_FAIL = "verification-stale-fail-threshold"
REASON_VERIFICATION_STALE_WARN = "verification-stale-warn-threshold"
REASON_VERIFICATION_FRESH = "verification-fresh"

#: Appended to every "could not read this signal" detail by the service.
REASON_SIGNAL_UNAVAILABLE = "signal-unavailable"

#: Verification outcomes that mean the deployment did not agree with its contract.
_UNHEALTHY_RUN_STATUSES: Tuple[str, ...] = ("failed", "errored")


class GateThresholdError(ValueError):
    """A submitted threshold body is not valid.

    Attributes:
        errors: One message per problem, so a caller fixes everything in one round trip rather
            than discovering the next mistake after correcting the first.
    """

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class _CamelModel(BaseModel):
    """Base for every wire model here: camelCase out, either spelling in."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


# -------------------------------------------------------------------------------------------
# Thresholds
# -------------------------------------------------------------------------------------------


class LintThresholds(_CamelModel):
    """Where the bar sits for the GOV lint grade stored on the revision.

    Attributes:
        warn_below_grade: Warn when the grade is worse than this letter; ``None`` disables the rung.
        fail_below_grade: Fail when the grade is worse than this letter; ``None`` disables the rung.
    """

    warn_below_grade: Optional[str] = Field(
        default="B", description="Warn below this letter grade (`null` disables the rung)."
    )
    fail_below_grade: Optional[str] = Field(
        default="D", description="Fail below this letter grade (`null` disables the rung)."
    )


class BreakingThresholds(_CamelModel):
    """Where the bar sits for the CTG-3.1 breaking classification of the publish.

    Attributes:
        warn_at_severity: Warn when the worst change is at least this severe; ``None`` disables it.
        fail_at_severity: Fail when the worst change is at least this severe; ``None`` disables it.
    """

    warn_at_severity: Optional[str] = Field(
        default=None,
        description=(
            "Warn when the worst classified change is at least this severe "
            "(`docs-only` | `non-breaking` | `breaking`; `null` disables the rung)."
        ),
    )
    fail_at_severity: Optional[str] = Field(
        default="breaking",
        description=(
            "Fail when the worst classified change is at least this severe "
            "(`null` disables the rung — useful when the consumer signal is the gate instead)."
        ),
    )


class ConsumerThresholds(_CamelModel):
    """Where the bar sits for the CTG-4.2 per-consumer verdicts.

    Both are *tolerances*: the count may be this high without tripping the rung.

    Attributes:
        warn_above_affected: Warn when more than this many consumers are touched at all.
        fail_above_breaking: Fail when more than this many consumers are broken.
    """

    warn_above_affected: Optional[int] = Field(
        default=0,
        ge=0,
        description="Warn when more consumers than this are affected (`null` disables the rung).",
    )
    fail_above_breaking: Optional[int] = Field(
        default=0,
        ge=0,
        description="Fail when more consumers than this are broken (`null` disables the rung).",
    )


class VerificationThresholds(_CamelModel):
    """Where the bar sits for CTG-4.4 verification freshness.

    Attributes:
        warn_after_seconds: Warn once the last clean verification is older than this.
        fail_after_seconds: Fail once the last clean verification is older than this.
        fail_on_unhealthy_run: Fail when the most recent run failed or could not run, whatever its
            age. A recent *failure* is worse news than an old success, so it is judged first.
    """

    warn_after_seconds: Optional[int] = Field(
        default=86_400,
        ge=0,
        description="Warn when the last clean verification is older than this many seconds.",
    )
    fail_after_seconds: Optional[int] = Field(
        default=604_800,
        ge=0,
        description="Fail when the last clean verification is older than this many seconds.",
    )
    fail_on_unhealthy_run: bool = Field(
        default=True,
        description="Fail when the most recent verification failed or errored, whatever its age.",
    )


class DeployGateThresholds(_CamelModel):
    """The complete ``ctg.gate-policy.v1`` body: one threshold group per signal."""

    lint: LintThresholds = Field(default_factory=LintThresholds)
    breaking: BreakingThresholds = Field(default_factory=BreakingThresholds)
    consumers: ConsumerThresholds = Field(default_factory=ConsumerThresholds)
    verification: VerificationThresholds = Field(default_factory=VerificationThresholds)


#: What a tenant that has configured nothing is judged against.
DEFAULT_THRESHOLDS = DeployGateThresholds()


def canonical_thresholds_body(thresholds: DeployGateThresholds) -> Dict[str, Any]:
    """Render thresholds as the stable dict that is stored and fingerprinted.

    Always the full body with every key present, even the defaulted ones: a stored policy must
    keep meaning the same thing after a later release changes a default.

    Args:
        thresholds: The thresholds to render.

    Returns:
        A JSON-ready dict with camelCase keys and a ``schemaVersion``.
    """
    body = thresholds.model_dump(by_alias=True, mode="json")
    body["schemaVersion"] = DEPLOY_GATE_POLICY_SCHEMA_VERSION
    return body


def thresholds_content_fingerprint(thresholds: DeployGateThresholds) -> str:
    """Return a stable ``sha256:`` digest of a threshold body.

    Echoed on every gate response so a pipeline can tell "the verdict changed because the API
    changed" from "because somebody moved the bar".

    Args:
        thresholds: The thresholds to digest.

    Returns:
        ``"sha256:<hex>"``.
    """
    blob = json.dumps(
        canonical_thresholds_body(thresholds),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


def _validate_thresholds(thresholds: DeployGateThresholds) -> List[str]:
    """Return every semantic problem with a threshold set (empty when it is coherent).

    Pydantic has already checked types and ranges; this checks the things only a human would
    notice — an unknown grade letter, or a warn rung that can never fire because the fail rung
    sits above it.

    Args:
        thresholds: The parsed thresholds.

    Returns:
        Human-readable problems, one per line.
    """
    errors: List[str] = []

    lint = thresholds.lint
    for field_name, value in (
        ("lint.warnBelowGrade", lint.warn_below_grade),
        ("lint.failBelowGrade", lint.fail_below_grade),
    ):
        if value is not None and value not in _GRADE_RANK:
            errors.append(f"{field_name} must be one of {', '.join(LINT_GRADES)} (got {value!r}).")
    if (
        lint.warn_below_grade in _GRADE_RANK
        and lint.fail_below_grade in _GRADE_RANK
        and _GRADE_RANK[lint.warn_below_grade] < _GRADE_RANK[lint.fail_below_grade]
    ):
        errors.append(
            "lint.warnBelowGrade must not be stricter than lint.failBelowGrade — a warn rung "
            "below the fail rung can never fire."
        )

    breaking = thresholds.breaking
    for field_name, value in (
        ("breaking.warnAtSeverity", breaking.warn_at_severity),
        ("breaking.failAtSeverity", breaking.fail_at_severity),
    ):
        if value is not None and value not in _SEVERITY_RANK:
            errors.append(
                f"{field_name} must be one of {', '.join(BREAKING_SEVERITIES)} (got {value!r})."
            )
    if (
        breaking.warn_at_severity in _SEVERITY_RANK
        and breaking.fail_at_severity in _SEVERITY_RANK
        and _SEVERITY_RANK[breaking.warn_at_severity] > _SEVERITY_RANK[breaking.fail_at_severity]
    ):
        errors.append(
            "breaking.warnAtSeverity must not be more severe than breaking.failAtSeverity — a "
            "warn rung above the fail rung can never fire."
        )

    verification = thresholds.verification
    warn_after = verification.warn_after_seconds
    fail_after = verification.fail_after_seconds
    if warn_after is not None and fail_after is not None and warn_after > fail_after:
        errors.append(
            "verification.warnAfterSeconds must not exceed verification.failAfterSeconds — a "
            "warn rung beyond the fail rung can never fire."
        )

    # The two consumer tolerances are deliberately not cross-checked: they count different things
    # (touched at all, versus broken), so `warnAboveAffected: 5` beside `failAboveBreaking: 0` is
    # a coherent policy, not a rung that can never fire.
    return errors


def thresholds_from_body(body: Optional[Mapping[str, Any]]) -> DeployGateThresholds:
    """Parse and validate a submitted or stored threshold body.

    Args:
        body: The ``ctg.gate-policy.v1`` object, or ``None``/empty for the documented default.

    Returns:
        The thresholds. Absent groups and absent keys take their documented defaults, so a body
        naming one threshold configures exactly that one.

    Raises:
        GateThresholdError: When the body is not an object, names an unknown key, or sets a rung
            that could never fire.
    """
    if body is None:
        return DEFAULT_THRESHOLDS
    if not isinstance(body, Mapping):
        raise GateThresholdError(["The policy body must be a JSON object."])

    payload = {key: value for key, value in body.items() if key != "schemaVersion"}
    try:
        thresholds = DeployGateThresholds.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - pydantic's message is the useful part
        raise GateThresholdError([str(exc)]) from exc

    errors = _validate_thresholds(thresholds)
    if errors:
        raise GateThresholdError(errors)
    return thresholds


# -------------------------------------------------------------------------------------------
# Wire models
# -------------------------------------------------------------------------------------------


class GateSignal(_CamelModel):
    """One of the four inputs, judged.

    Attributes:
        signal: One of :data:`GATE_SIGNALS`.
        status: One of :data:`GATE_STATUSES`.
        satisfied: Whether the signal met its thresholds; ``None`` when it was not judged at all.
        reason: Stable machine-readable code — branch on this, not on ``detail``.
        detail: One human sentence saying what was observed and what the policy makes of it.
        link: API path a reader follows for the underlying evidence.
        data: The facts the judgment was made from, so the verdict is checkable without a
            second request.
    """

    signal: str = Field(description="`lint` | `breaking` | `consumers` | `verification`.")
    status: str = Field(description="`pass` | `warn` | `fail` | `not_configured` | `unknown`.")
    satisfied: Optional[bool] = Field(
        default=None, description="Whether thresholds were met; null when not judged."
    )
    reason: str = Field(description="Stable reason code.")
    detail: str = Field(description="One human sentence.")
    link: Optional[str] = Field(default=None, description="Where to read the evidence.")
    data: Dict[str, Any] = Field(
        default_factory=dict, description="The facts behind the judgment."
    )


class DeployGatePolicyOut(_CamelModel):
    """The threshold policy a gate response was judged under.

    Attributes:
        source: ``default`` (nothing saved), ``tenant``, or ``project``.
        policy_id: Stored row id; ``None`` for the documented default.
        content_fingerprint: Digest of the threshold body.
        thresholds: The thresholds themselves.
        updated_at: When the stored policy last changed.
        updated_by: Who changed it.
        degraded: True when a saved policy could not be read and the default stood in. A gate has
            to answer, so an unreadable policy row falls back rather than failing — but a caller
            must be able to tell "nothing is configured" from "I could not read what is".
    """

    schema_version: str = Field(default=DEPLOY_GATE_POLICY_SCHEMA_VERSION)
    source: str = Field(description="`default` | `tenant` | `project`.")
    policy_id: Optional[str] = Field(default=None)
    content_fingerprint: str = Field(default="")
    thresholds: DeployGateThresholds = Field(default_factory=DeployGateThresholds)
    updated_at: Optional[datetime] = Field(default=None)
    updated_by: Optional[str] = Field(default=None)
    degraded: bool = Field(
        default=False,
        description="True when a saved policy could not be read and the default stood in.",
    )


class DeployGateReport(_CamelModel):
    """The single aggregate verdict a CD pipeline reads.

    Attributes:
        schema_version: :data:`DEPLOY_GATE_SCHEMA_VERSION`.
        status: ``pass`` / ``warn`` / ``fail`` — the worst *evaluated* signal.
        summary: One line a pipeline can print.
        project_id / project_slug: The gated project.
        revision_id / version_label / version_ref / published_at: The gated published revision.
        evaluated_at: When the verdict was computed.
        evaluated_signals: How many of the four took part. ``0`` means nothing could be judged and
            ``status`` is ``pass`` by the partial-inputs rule — branch on this, not on the status,
            if an unconfigured project must not read as a green light.
        counts: Signals per status.
        signals: The four, always all of them, in :data:`GATE_SIGNALS` order.
        policy: The thresholds this verdict was judged under.
    """

    schema_version: str = Field(default=DEPLOY_GATE_SCHEMA_VERSION)
    status: str = Field(description="`pass` | `warn` | `fail`.")
    summary: str = Field(description="One line for a pipeline log.")
    project_id: str
    project_slug: Optional[str] = None
    revision_id: str
    version_label: Optional[str] = None
    version_ref: Optional[str] = Field(
        default=None,
        description="`project/{slug}/{version}` — the reference the other CTG APIs address.",
    )
    published_at: Optional[datetime] = None
    evaluated_at: datetime
    evaluated_signals: int = Field(description="How many signals took part in the verdict.")
    counts: Dict[str, int] = Field(default_factory=dict)
    signals: List[GateSignal] = Field(default_factory=list)
    policy: DeployGatePolicyOut


# -------------------------------------------------------------------------------------------
# Signal evaluation
# -------------------------------------------------------------------------------------------


def unavailable_signal(
    signal: str,
    *,
    status: str,
    reason: str,
    detail: str,
    link: Optional[str] = None,
    data: Optional[Mapping[str, Any]] = None,
) -> GateSignal:
    """Build a signal that was not judged.

    Used for every "there is nothing here" and "I could not read this" case, so those two never
    get mistaken for a ``pass``.

    Args:
        signal: One of :data:`GATE_SIGNALS`.
        status: :data:`STATUS_NOT_CONFIGURED` or :data:`STATUS_UNKNOWN`.
        reason: Stable reason code.
        detail: One human sentence.
        link: Where a reader would go to configure or inspect it.
        data: Any facts worth carrying.

    Returns:
        The signal, with ``satisfied`` left ``None``.
    """
    return GateSignal(
        signal=signal,
        status=status,
        satisfied=None,
        reason=reason,
        detail=detail,
        link=link,
        data=dict(data or {}),
    )


def evaluate_lint(
    *,
    grade: Optional[str],
    score: Optional[int],
    thresholds: LintThresholds,
    link: Optional[str] = None,
) -> GateSignal:
    """Judge the stored GOV lint grade for the gated revision.

    The grade is read from the revision record, never recomputed: since #5259 a lint report is
    captured when a revision changes, and a deploy gate that re-linted would make the cheapest
    call in a pipeline the most expensive one.

    Args:
        grade: The stored letter grade, or ``None`` when the revision has never been linted.
        score: The stored 0-100 score, for the detail line.
        thresholds: The lint rungs in force.
        link: Path to the full lint report.

    Returns:
        The judged signal.
    """
    data: Dict[str, Any] = {
        "grade": grade,
        "score": score,
        "warnBelowGrade": thresholds.warn_below_grade,
        "failBelowGrade": thresholds.fail_below_grade,
    }
    if not grade:
        return unavailable_signal(
            SIGNAL_LINT,
            status=STATUS_NOT_CONFIGURED,
            reason=REASON_LINT_NOT_CAPTURED,
            detail=(
                "This revision has no stored lint report, so its grade cannot be part of the "
                "verdict. Open the revision's lint report once to capture one."
            ),
            link=link,
            data=data,
        )
    if grade not in _GRADE_RANK:
        return unavailable_signal(
            SIGNAL_LINT,
            status=STATUS_UNKNOWN,
            reason=REASON_LINT_GRADE_UNRECOGNISED,
            detail=(
                f"The stored lint grade {grade!r} is not one of "
                f"{', '.join(LINT_GRADES)}, so it cannot be compared with the threshold."
            ),
            link=link,
            data=data,
        )

    scored = f"grade {grade}" + (f" (score {score})" if score is not None else "")
    rank = _GRADE_RANK[grade]

    fail_below = thresholds.fail_below_grade
    if fail_below in _GRADE_RANK and rank < _GRADE_RANK[fail_below]:
        return GateSignal(
            signal=SIGNAL_LINT,
            status=STATUS_FAIL,
            satisfied=False,
            reason=REASON_LINT_BELOW_FAIL,
            detail=f"Lint {scored} is below the failing threshold of {fail_below}.",
            link=link,
            data=data,
        )

    warn_below = thresholds.warn_below_grade
    if warn_below in _GRADE_RANK and rank < _GRADE_RANK[warn_below]:
        return GateSignal(
            signal=SIGNAL_LINT,
            status=STATUS_WARN,
            satisfied=False,
            reason=REASON_LINT_BELOW_WARN,
            detail=f"Lint {scored} is below the warning threshold of {warn_below}.",
            link=link,
            data=data,
        )

    return GateSignal(
        signal=SIGNAL_LINT,
        status=STATUS_PASS,
        satisfied=True,
        reason=REASON_LINT_OK,
        detail=f"Lint {scored} meets the configured thresholds.",
        link=link,
        data=data,
    )


def evaluate_breaking(
    *,
    status: Optional[str],
    max_severity: Optional[str],
    counts: Optional[Mapping[str, int]] = None,
    baseline_version_label: Optional[str] = None,
    thresholds: BreakingThresholds,
    link: Optional[str] = None,
) -> GateSignal:
    """Judge the CTG-3.1 breaking classification stored for the gated revision.

    Args:
        status: The stored classification status (``ready`` / ``initial`` / ``failed``), or
            ``None`` when no classification row exists for this revision.
        max_severity: The worst severity across the classified changes; ``None`` when there were
            no changes at all.
        counts: The per-severity tallies, for the detail line and the payload.
        baseline_version_label: The previously published revision this was compared against.
        thresholds: The breaking rungs in force.
        link: Path to the stored changelog.

    Returns:
        The judged signal.
    """
    tallies = {str(key): int(value) for key, value in (counts or {}).items()}
    data: Dict[str, Any] = {
        "classificationStatus": status,
        "maxSeverity": max_severity,
        "counts": tallies,
        "baselineVersionLabel": baseline_version_label,
        "warnAtSeverity": thresholds.warn_at_severity,
        "failAtSeverity": thresholds.fail_at_severity,
    }

    if not status:
        return unavailable_signal(
            SIGNAL_BREAKING,
            status=STATUS_NOT_CONFIGURED,
            reason=REASON_BREAKING_NOT_CLASSIFIED,
            detail=(
                "No breaking-change classification is stored for this revision yet, so the "
                "publish cannot be part of the verdict."
            ),
            link=link,
            data=data,
        )
    if status == "failed":
        return unavailable_signal(
            SIGNAL_BREAKING,
            status=STATUS_UNKNOWN,
            reason=REASON_BREAKING_CLASSIFICATION_FAILED,
            detail=(
                "Classifying this publish failed, so whether it is breaking is unknown — this is "
                "not the same as knowing it is safe."
            ),
            link=link,
            data=data,
        )
    if status == "initial":
        return GateSignal(
            signal=SIGNAL_BREAKING,
            status=STATUS_PASS,
            satisfied=True,
            reason=REASON_BREAKING_INITIAL_PUBLICATION,
            detail="First publication on this line: there is no earlier contract to break.",
            link=link,
            data=data,
        )

    if max_severity is None:
        return GateSignal(
            signal=SIGNAL_BREAKING,
            status=STATUS_PASS,
            satisfied=True,
            reason=REASON_BREAKING_NONE,
            detail=(
                "No classified changes against "
                f"{baseline_version_label or 'the previous published revision'}."
            ),
            link=link,
            data=data,
        )
    if max_severity not in _SEVERITY_RANK:
        return unavailable_signal(
            SIGNAL_BREAKING,
            status=STATUS_UNKNOWN,
            reason=REASON_BREAKING_CLASSIFICATION_FAILED,
            detail=(
                f"The stored worst severity {max_severity!r} is not one of "
                f"{', '.join(BREAKING_SEVERITIES)}, so it cannot be compared with the threshold."
            ),
            link=link,
            data=data,
        )

    rank = _SEVERITY_RANK[max_severity]
    breaking_count = tallies.get("breaking", 0)
    against = f" against {baseline_version_label}" if baseline_version_label else ""
    observed = f"The worst change{against} is {max_severity}"
    if breaking_count:
        observed += f" ({breaking_count} breaking)"

    fail_at = thresholds.fail_at_severity
    if fail_at in _SEVERITY_RANK and rank >= _SEVERITY_RANK[fail_at]:
        return GateSignal(
            signal=SIGNAL_BREAKING,
            status=STATUS_FAIL,
            satisfied=False,
            reason=REASON_BREAKING_PRESENT,
            detail=f"{observed}; the gate fails at {fail_at}.",
            link=link,
            data=data,
        )

    warn_at = thresholds.warn_at_severity
    if warn_at in _SEVERITY_RANK and rank >= _SEVERITY_RANK[warn_at]:
        return GateSignal(
            signal=SIGNAL_BREAKING,
            status=STATUS_WARN,
            satisfied=False,
            reason=REASON_BREAKING_WARN,
            detail=f"{observed}; the gate warns at {warn_at}.",
            link=link,
            data=data,
        )

    return GateSignal(
        signal=SIGNAL_BREAKING,
        status=STATUS_PASS,
        satisfied=True,
        reason=REASON_BREAKING_NONE,
        detail=f"{observed}, which is within the configured thresholds.",
        link=link,
        data=data,
    )


def evaluate_consumers(
    *,
    report: ConsumerImpactReport,
    thresholds: ConsumerThresholds,
    link: Optional[str] = None,
) -> GateSignal:
    """Judge the CTG-4.2 per-consumer verdicts for the gated publish.

    Args:
        report: The consumer-impact report for this revision's classified changes.
        thresholds: The consumer rungs in force.
        link: Path to the project's consumer registry.

    Returns:
        The judged signal.
    """
    counts = {str(key): int(value) for key, value in report.counts.items()}
    total = counts.get("consumers_total", 0)
    breaking = counts.get("consumers_breaking", 0)
    affected = counts.get("consumers_affected", 0)
    undeclared = counts.get("consumers_undeclared", 0)
    data: Dict[str, Any] = {
        "summary": report.summary,
        "counts": counts,
        "breakingConsumers": list(report.breaking_consumers),
        "warnAboveAffected": thresholds.warn_above_affected,
        "failAboveBreaking": thresholds.fail_above_breaking,
    }

    if total == 0:
        return unavailable_signal(
            SIGNAL_CONSUMERS,
            status=STATUS_NOT_CONFIGURED,
            reason=REASON_CONSUMERS_NONE_REGISTERED,
            detail=(
                "No consumers are registered for this project, so a per-consumer verdict cannot "
                "be part of the gate."
            ),
            link=link,
            data=data,
        )

    # The undeclared count is reported beside the verdict, never folded into it: a consumer that
    # has declared no surface has not been shown to be safe (CTG-4.2's denominator rule).
    caveat = (
        f" {undeclared} registered consumer{'s' if undeclared != 1 else ''} "
        f"{'have' if undeclared != 1 else 'has'} declared no surface."
        if undeclared
        else ""
    )

    fail_above = thresholds.fail_above_breaking
    if fail_above is not None and breaking > fail_above:
        return GateSignal(
            signal=SIGNAL_CONSUMERS,
            status=STATUS_FAIL,
            satisfied=False,
            reason=REASON_CONSUMERS_BREAKING,
            detail=f"{report.summary}.{caveat}",
            link=link,
            data=data,
        )

    warn_above = thresholds.warn_above_affected
    if warn_above is not None and affected > warn_above:
        return GateSignal(
            signal=SIGNAL_CONSUMERS,
            status=STATUS_WARN,
            satisfied=False,
            reason=REASON_CONSUMERS_AFFECTED,
            detail=(
                f"{affected} of {total} registered consumers are affected without being broken."
                f"{caveat}"
            ),
            link=link,
            data=data,
        )

    return GateSignal(
        signal=SIGNAL_CONSUMERS,
        status=STATUS_PASS,
        satisfied=True,
        reason=REASON_CONSUMERS_UNAFFECTED,
        detail=f"{report.summary}.{caveat}",
        link=link,
        data=data,
    )


def evaluate_verification(
    *,
    source: Optional[str],
    freshness_seconds: Optional[int],
    last_status: Optional[str],
    last_success_at: Optional[datetime] = None,
    thresholds: VerificationThresholds,
    link: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> GateSignal:
    """Judge how recently, and how well, this version's deployment was verified.

    ``freshness_seconds`` of ``None`` means *unknown*, never *fresh* — CTG-4.4's rule, kept here
    because a gate is exactly where the difference matters.

    Args:
        source: ``schedule`` when CTG-4.4 is watching this version, ``report`` when the only
            evidence is a manual CTG-4.3 run, ``None`` when there is neither.
        freshness_seconds: Seconds since the last *clean* verification; ``None`` when there has
            never been one.
        last_status: The most recent run's outcome (``passed`` / ``failed`` / ``errored``).
        last_success_at: When it last verified clean, for the payload.
        thresholds: The verification rungs in force.
        link: Path to the schedules or reports behind this.
        extra: Signal-specific facts (which schedules matched, which report was read).

    Returns:
        The judged signal.
    """
    data: Dict[str, Any] = {
        "source": source,
        "freshnessSeconds": freshness_seconds,
        "lastStatus": last_status,
        "lastSuccessAt": last_success_at.isoformat() if last_success_at else None,
        "warnAfterSeconds": thresholds.warn_after_seconds,
        "failAfterSeconds": thresholds.fail_after_seconds,
        "failOnUnhealthyRun": thresholds.fail_on_unhealthy_run,
    }
    data.update(dict(extra or {}))

    if not source:
        return unavailable_signal(
            SIGNAL_VERIFICATION,
            status=STATUS_NOT_CONFIGURED,
            reason=REASON_VERIFICATION_NEVER_RUN,
            detail=(
                "This version's deployment has never been verified, so freshness cannot be part "
                "of the verdict. Register a verification target and schedule to add this signal."
            ),
            link=link,
            data=data,
        )

    if last_status in _UNHEALTHY_RUN_STATUSES and thresholds.fail_on_unhealthy_run:
        return GateSignal(
            signal=SIGNAL_VERIFICATION,
            status=STATUS_FAIL,
            satisfied=False,
            reason=REASON_VERIFICATION_UNHEALTHY,
            detail=(
                f"The most recent verification {last_status}: the deployment does not currently "
                "match this contract."
            ),
            link=link,
            data=data,
        )

    if freshness_seconds is None:
        gated = (
            thresholds.warn_after_seconds is not None
            or thresholds.fail_after_seconds is not None
        )
        if gated:
            return GateSignal(
                signal=SIGNAL_VERIFICATION,
                status=STATUS_WARN,
                satisfied=False,
                reason=REASON_VERIFICATION_NEVER_SUCCEEDED,
                detail=(
                    "Verification is set up for this version but has never completed cleanly, so "
                    "its freshness is unknown — which is not the same as fresh."
                ),
                link=link,
                data=data,
            )
        return GateSignal(
            signal=SIGNAL_VERIFICATION,
            status=STATUS_PASS,
            satisfied=True,
            reason=REASON_VERIFICATION_NEVER_SUCCEEDED,
            detail=(
                "Verification has never completed cleanly, but this policy does not gate on "
                "freshness."
            ),
            link=link,
            data=data,
        )

    age = _humanize_seconds(freshness_seconds)
    fail_after = thresholds.fail_after_seconds
    if fail_after is not None and freshness_seconds > fail_after:
        return GateSignal(
            signal=SIGNAL_VERIFICATION,
            status=STATUS_FAIL,
            satisfied=False,
            reason=REASON_VERIFICATION_STALE_FAIL,
            detail=(
                f"Last verified clean {age} ago, past the failing staleness limit of "
                f"{_humanize_seconds(fail_after)}."
            ),
            link=link,
            data=data,
        )

    warn_after = thresholds.warn_after_seconds
    if warn_after is not None and freshness_seconds > warn_after:
        return GateSignal(
            signal=SIGNAL_VERIFICATION,
            status=STATUS_WARN,
            satisfied=False,
            reason=REASON_VERIFICATION_STALE_WARN,
            detail=(
                f"Last verified clean {age} ago, past the warning staleness limit of "
                f"{_humanize_seconds(warn_after)}."
            ),
            link=link,
            data=data,
        )

    return GateSignal(
        signal=SIGNAL_VERIFICATION,
        status=STATUS_PASS,
        satisfied=True,
        reason=REASON_VERIFICATION_FRESH,
        detail=f"Last verified clean {age} ago, within the configured freshness window.",
        link=link,
        data=data,
    )


def _humanize_seconds(seconds: int) -> str:
    """Render a duration the way a pipeline log should read it.

    Args:
        seconds: A non-negative duration.

    Returns:
        The largest sensible unit, e.g. ``"3 days"`` or ``"42 minutes"``.
    """
    value = max(0, int(seconds))
    for limit, unit, divisor in (
        (60, "second", 1),
        (3600, "minute", 60),
        (86_400, "hour", 3600),
        (None, "day", 86_400),
    ):
        if limit is None or value < limit:
            count = value // divisor
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return f"{value} seconds"  # pragma: no cover - the loop above always returns


# -------------------------------------------------------------------------------------------
# Aggregation
# -------------------------------------------------------------------------------------------


def status_counts(signals: Sequence[GateSignal]) -> Dict[str, int]:
    """Tally signals per status, with every status key present.

    Args:
        signals: The judged signals.

    Returns:
        A dict keyed by :data:`GATE_STATUSES`; a status nothing landed on reads ``0`` rather
        than being absent, so a caller never has to guard a lookup.
    """
    counts = {status: 0 for status in GATE_STATUSES}
    for signal in signals:
        if signal.status in counts:
            counts[signal.status] += 1
    return counts


def overall_status(signals: Sequence[GateSignal]) -> str:
    """Return the worst *evaluated* status.

    ``not_configured`` and ``unknown`` take no part: the endpoint has to ship before all four
    sources exist everywhere, so a signal with nothing behind it must not fail the gate. When no
    signal was evaluated at all the verdict is ``pass`` — read ``evaluated_signals`` rather than
    the status if that must not be a green light.

    Args:
        signals: The judged signals.

    Returns:
        ``pass``, ``warn`` or ``fail``.
    """
    worst = STATUS_PASS
    for signal in signals:
        rank = _VERDICT_RANK.get(signal.status)
        if rank is not None and rank > _VERDICT_RANK[worst]:
            worst = signal.status
    return worst


def gate_summary(
    status: str, signals: Sequence[GateSignal], *, version_label: Optional[str] = None
) -> str:
    """Build the one line a pipeline prints.

    Args:
        status: The overall verdict.
        signals: The judged signals.
        version_label: The gated version, when known.

    Returns:
        A sentence naming the verdict and what drove it.
    """
    subject = f"{version_label} " if version_label else ""
    evaluated = [s for s in signals if s.status in _VERDICT_RANK]
    if not evaluated:
        skipped = ", ".join(s.signal for s in signals) or "no signals"
        return (
            f"{subject}has no gate signal to judge ({skipped} unavailable); "
            "nothing blocks promotion, and nothing vouches for it."
        )

    drivers = [s.signal for s in evaluated if s.status == status]
    if status == STATUS_PASS:
        return (
            f"{subject}passes the deploy gate on "
            f"{len(evaluated)} of {len(signals)} signals."
        )
    verb = "fails" if status == STATUS_FAIL else "warns on"
    return (
        f"{subject}{verb} the deploy gate: {', '.join(drivers)} "
        f"({len(evaluated)} of {len(signals)} signals evaluated)."
    )


def build_gate_report(
    *,
    project_id: str,
    project_slug: Optional[str],
    revision_id: str,
    version_label: Optional[str],
    version_ref: Optional[str],
    published_at: Optional[datetime],
    signals: Sequence[GateSignal],
    policy: DeployGatePolicyOut,
    evaluated_at: Optional[datetime] = None,
) -> DeployGateReport:
    """Assemble the response from already-judged signals.

    Args:
        project_id: The gated project.
        project_slug: Its handle.
        revision_id: The gated published revision.
        version_label: Its version label.
        version_ref: The ``project/{slug}/{version}`` reference the other CTG APIs address.
        published_at: When the revision was published.
        signals: The judged signals, in :data:`GATE_SIGNALS` order.
        policy: The thresholds the verdict was judged under.
        evaluated_at: Override for the timestamp (tests).

    Returns:
        The complete :class:`DeployGateReport`.
    """
    ordered = sorted(
        signals,
        key=lambda s: GATE_SIGNALS.index(s.signal) if s.signal in GATE_SIGNALS else len(
            GATE_SIGNALS
        ),
    )
    status = overall_status(ordered)
    counts = status_counts(ordered)
    return DeployGateReport(
        status=status,
        summary=gate_summary(status, ordered, version_label=version_label),
        project_id=project_id,
        project_slug=project_slug,
        revision_id=revision_id,
        version_label=version_label,
        version_ref=version_ref,
        published_at=published_at,
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
        evaluated_signals=counts[STATUS_PASS] + counts[STATUS_WARN] + counts[STATUS_FAIL],
        counts=counts,
        signals=list(ordered),
        policy=policy,
    )
