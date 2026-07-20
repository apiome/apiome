"""Slate Edge unified observability, residency, usage and budget — UXE-3.4 (private-suite#2476).

The decisions that must hold before an observability policy, a residency lane, an export
destination, a live tail session or a budget is written, and the evaluation that turns stored
signals into the correlated series, rollups, forecasts and alerts a surface charts, kept in one
pure module so they can be tested exhaustively without a database and so the REST layer cannot
implement a second, subtly different copy of them. It is the observability counterpart of
:mod:`app.slate_cache`, :mod:`app.slate_security` and :mod:`app.slate_functions` and deliberately
reads like them: an operator who has learned what ``simulate`` means on the security surface, or
what ``in-region-only`` means on the edge surface, must not have to relearn either here.

The refusal vocabulary is shared with the authoring surface's ``AuthoringInsightsRefusalReason``
for the reason :mod:`app.slate_cache` states: the surface makes ``disabledReason`` the only way to
disable a control, so a backend that invented its own codes would leave the operator with a
greyed-out dead end instead of a sentence explaining what to do.

Five things are worth stating outright, and the first one is the whole ticket.

1. **The dangerous direction here is believing too much.** Its three predecessors each guard
   against doing something: purging too much cache, turning protection off, granting reach. This
   surface guards against *claiming* something. A latency chart that is quietly modelled rather
   than measured is worse than an unenforced rule, because an unenforced rule is inert and a
   fabricated p95 is acted upon — somebody reads it, concludes the release is healthy and promotes
   it. One step further along, where §29.6 asks for spend and overage, a modelled cost presented
   as a bill is not a disappointing estimate but an invented invoice. So every verdict this module
   produces carries ``basis``, ``observed`` and ``enforced`` as fields it always sets to the
   honest value, and there is no code path here able to set them otherwise.

2. **Correlation is a precondition, not a feature.** §29.6 opens by requiring metrics, logs,
   traces, security and cost to share release, environment and region correlation, and the issue
   restates it first because separate provider dashboards are exactly what makes a release
   impossible to connect to its latency. :func:`correlate_signals` therefore refuses to emit a
   point it cannot key, rather than emitting it unkeyed and letting a chart and its drill-down
   disagree about which rows they mean.

3. **A residency promise is only as good as its stated gap.** §29.6 asks the UX to state what a
   residency option does not cover, which is an unusual requirement and the correct one: a claim
   with no stated gap is not a stronger promise, it is the same promise with the gap unwritten,
   and it is the version somebody quotes to a regulator. :data:`RESIDENCY_STAGE_CATALOG` gives
   every one of the six stages a default gap sentence, and writing a lane without one is refused.

4. **Money reconciles or is not money.** ``billable`` requires a metered basis, measured cache
   savings require a metered basis, and a budget compared against usage in another currency is
   refused rather than converted at a rate this module has no business inventing. Forecasts are
   carried in their own fields so a projection can never be summed into a total as though it had
   happened.

5. **Nothing here measures anything.** ``deploy/`` is a single Caddyfile: there is no CDN, no
   collector and no meter behind it. This module correlates, rolls up, forecasts and explains;
   the store records. So :class:`TelemetryVerdict` and :class:`UsageRollup` carry ``observed``
   and ``metered`` as fields this module always sets to ``False``, and :func:`evaluate_budget`
   marks every alert it produces as modelled.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

__all__ = [
    "ANNOTATION_KINDS",
    "BUDGET_PERIODS",
    "DELIVERY_STATES",
    "EVIDENCE_KEYS",
    "LOG_LEVELS",
    "LOG_SOURCES",
    "METRIC_FAMILIES",
    "METRIC_FAMILY_CATALOG",
    "OTLP_PROTOCOLS",
    "RESIDENCY_CLASSES",
    "RESIDENCY_CLASS_CATALOG",
    "RESIDENCY_STAGES",
    "RESIDENCY_STAGE_CATALOG",
    "SERVICES",
    "SERVICE_CATALOG",
    "SIGNAL_CLASSES",
    "SPAN_ATTRIBUTE_KEYS",
    "SYNTHETIC_OUTCOMES",
    "BudgetAlert",
    "BudgetEvaluation",
    "CorrelationKey",
    "InsightRefusal",
    "InsightRefusalReason",
    "InsightWarning",
    "MetricPoint",
    "ResidencyStageDefinition",
    "ServiceDefinition",
    "SlateInsightRefusedError",
    "TelemetryVerdict",
    "UsageRollup",
    "correlate_signals",
    "evaluate_budget",
    "forecast_service",
    "normalize_budget",
    "normalize_export",
    "normalize_policy",
    "normalize_residency_lane",
    "normalize_tail_request",
    "plan_live_tail",
    "redact_evidence",
    "residency_coverage",
    "roll_up_usage",
    "signals_digest",
    "validate_budget",
    "validate_export",
    "validate_policy",
    "validate_residency_lane",
    "validate_synthetic_check",
]


# ─── Closed vocabularies ──────────────────────────────────────────────────────
#
# Each of these mirrors a CHECK constraint in V190 exactly. They are duplicated here rather than
# read from the database for the reason :mod:`app.slate_functions` gives: a pure module that had
# to open a connection to know what a valid value was could not be tested without one, and the
# golden tests below assert the two lists agree so the duplication cannot rot silently.

#: Metric families, matching ``slate_insight_metric_series.metric_family``.
METRIC_FAMILIES: Tuple[str, ...] = (
    "request",
    "cache",
    "origin",
    "function",
    "security",
    "cost",
)

#: Log levels, ordered by increasing urgency so a threshold filter is a comparison.
LOG_LEVELS: Tuple[str, ...] = ("debug", "info", "warn", "error")

#: Emitting subsystems, matching ``slate_insight_logs.source``.
LOG_SOURCES: Tuple[str, ...] = (
    "request",
    "cache",
    "origin",
    "function",
    "security",
    "build",
)

#: The six processing stages §29.6 distinguishes, ordered along the request path.
RESIDENCY_STAGES: Tuple[str, ...] = (
    "ingress",
    "tls-termination",
    "decrypted-processing",
    "cache-storage",
    "function-execution",
    "log-data-storage",
)

#: Residency classes, most restrictive first. Deliberately the same spelling as
#: :data:`app.slate_functions.RESIDENCY_CLASSES`: an operator comparing the function lane on this
#: surface against the function policy on that one must not have to translate between two
#: spellings of the same promise.
RESIDENCY_CLASSES: Tuple[str, ...] = ("in-region-only", "region-pinned", "unrestricted")

#: Billable services, matching ``slate_insight_usage_records.service``.
SERVICES: Tuple[str, ...] = ("delivery", "build", "function", "log", "ai")

#: OpenTelemetry signal classes an export destination may receive.
SIGNAL_CLASSES: Tuple[str, ...] = ("metrics", "logs", "traces")

#: OTLP wire protocols.
OTLP_PROTOCOLS: Tuple[str, ...] = ("grpc", "http/protobuf")

#: Budget periods.
BUDGET_PERIODS: Tuple[str, ...] = ("daily", "weekly", "monthly")

#: Delivery states, ordered from least to most claimed. ``delivered`` is the only member that
#: asserts something arrived.
DELIVERY_STATES: Tuple[str, ...] = ("never-attempted", "pending", "failed", "delivered")

#: Synthetic probe outcomes. ``not-run`` exists separately from ``failed`` because a probe that
#: never executed is a scheduler outage and a probe that failed is a service outage, and paging
#: somebody for the first as though it were the second is how a health surface loses its audience.
SYNTHETIC_OUTCOMES: Tuple[str, ...] = ("healthy", "degraded", "failed", "not-run")

#: Post-promotion annotation kinds.
ANNOTATION_KINDS: Tuple[str, ...] = ("post-promotion-regression", "post-promotion-recovery")

#: The log evidence allowlist, identical to the CHECK on ``slate_insight_logs.evidence``.
#: Redaction here is belt-and-braces over a schema constraint, and deliberately so: the constraint
#: stops a bad write reaching the table, and this stops a bad read reaching an operator if the
#: allowlist is ever widened in SQL without somebody widening it here on purpose.
EVIDENCE_KEYS: Tuple[str, ...] = (
    "method",
    "path",
    "query",
    "userAgent",
    "country",
    "region",
    "clientIpPrefix",
    "statusCode",
    "durationMs",
    "cacheStatus",
    "functionRef",
    "variant",
    "ruleRef",
    "outcome",
)

#: The span attribute allowlist, identical to the CHECK on ``slate_insight_trace_spans``.
SPAN_ATTRIBUTE_KEYS: Tuple[str, ...] = (
    "route",
    "method",
    "statusCode",
    "cacheStatus",
    "functionRef",
    "variant",
    "ruleRef",
    "region",
    "outcome",
)


# ─── Catalogs ─────────────────────────────────────────────────────────────────
#
# Catalogs are values, not adjectives, exactly as in :mod:`app.slate_functions`. Each entry states
# in prose what it measures and — the part that matters on this surface — what it does NOT tell
# you. A metric family that cannot say what it fails to capture fails a golden test, not a code
# review, because the whole failure mode of an observability product is a number read as more
# than it is.


@dataclass(frozen=True)
class MetricFamilyDefinition:
    """One metric family, and the question it cannot answer.

    Attributes:
        family: The family id, one of :data:`METRIC_FAMILIES`.
        label: Operator-facing name.
        answers: What a chart in this family tells you.
        does_not_answer: What it does not, stated so a reader does not infer it.
    """

    family: str
    label: str
    answers: str
    does_not_answer: str


#: What each metric family measures, and what it does not.
METRIC_FAMILY_CATALOG: Tuple[MetricFamilyDefinition, ...] = (
    MetricFamilyDefinition(
        family="request",
        label="Requests",
        answers="How much traffic arrived, how fast it was served and how often it failed.",
        does_not_answer=(
            "Why it failed. A rising error rate here names no cause: the origin, a function, a "
            "security rule and a bad release all look identical from this family alone."
        ),
    ),
    MetricFamilyDefinition(
        family="cache",
        label="Cache",
        answers="Hit ratio, and how much of the traffic never reached the origin.",
        does_not_answer=(
            "Whether the hits were correct. A cache serving one reader's personalized page to "
            "another has an excellent hit ratio, which is why the personalization warnings live "
            "on the Edge surface rather than being inferable from this chart."
        ),
    ),
    MetricFamilyDefinition(
        family="origin",
        label="Origin",
        answers="How the upstream behaved for the requests that reached it.",
        does_not_answer=(
            "How it would behave without the cache in front of it. Origin load is measured after "
            "the cache has absorbed whatever it absorbed."
        ),
    ),
    MetricFamilyDefinition(
        family="function",
        label="Functions",
        answers="How often functions were considered, and what they cost when they ran.",
        does_not_answer=(
            "What a function did to a response. The Edge surface's simulation answers that; this "
            "family counts."
        ),
    ),
    MetricFamilyDefinition(
        family="security",
        label="Security",
        answers="How much traffic was mitigated, by which rule and against which routes.",
        does_not_answer=(
            "How much hostile traffic was missed. A mitigation count is a count of what matched, "
            "and the requests no rule matched are absent from it by construction."
        ),
    ),
    MetricFamilyDefinition(
        family="cost",
        label="Cost",
        answers="What the delivery, build, function, log and AI services consumed and cost.",
        does_not_answer=(
            "What the invoice will say, unless the underlying records are metered. A modelled "
            "cost is an estimate of this platform's own arithmetic, not a statement from billing."
        ),
    ),
)


@dataclass(frozen=True)
class ResidencyStageDefinition:
    """One processing stage, and the gap its residency promise leaves.

    Attributes:
        stage: The stage id, one of :data:`RESIDENCY_STAGES`.
        label: Operator-facing name.
        covers: What pinning this stage to a region actually guarantees.
        default_uncovered: The gap sentence used when an operator writes none. Required by §29.6,
            and a default rather than an empty string because a lane whose gap is blank reads as
            a lane with no gap.
    """

    stage: str
    label: str
    covers: str
    default_uncovered: str


#: The six stages, what each one's residency promise covers, and what it leaves out. These
#: sentences are the product requirement in §29.6 ("The UX states what a residency option does not
#: cover") expressed as data, so the surface renders them rather than inventing its own.
RESIDENCY_STAGE_CATALOG: Tuple[ResidencyStageDefinition, ...] = (
    ResidencyStageDefinition(
        stage="ingress",
        label="Ingress",
        covers="Which region's edge accepts the connection.",
        default_uncovered=(
            "Does not cover the network path before it. A reader's request crosses whatever "
            "networks their provider routes it over before it arrives, and no residency setting "
            "here changes that."
        ),
    ),
    ResidencyStageDefinition(
        stage="tls-termination",
        label="TLS termination",
        covers="Where the connection is decrypted and the private key is held.",
        default_uncovered=(
            "Does not cover certificate issuance or transparency logging, which are public and "
            "global by design."
        ),
    ),
    ResidencyStageDefinition(
        stage="decrypted-processing",
        label="Decrypted processing",
        covers="Where request content exists in the clear while it is being served.",
        default_uncovered=(
            "Does not cover diagnostic capture. A live tail or a trace samples this stage, so "
            "pinning processing without also pinning log and data storage moves nothing."
        ),
    ),
    ResidencyStageDefinition(
        stage="cache-storage",
        label="Cache storage",
        covers="Where responses are held between requests.",
        default_uncovered=(
            "Does not cover cache keys or tags, which are metadata and may be replicated globally "
            "so a purge can reach every region."
        ),
    ),
    ResidencyStageDefinition(
        stage="function-execution",
        label="Function execution",
        covers="Where function code runs and what it may read while running.",
        default_uncovered=(
            "Does not cover what a function reaches. An allowed egress destination is wherever it "
            "is, and pinning execution does not pin the far end of an outbound call."
        ),
    ),
    ResidencyStageDefinition(
        stage="log-data-storage",
        label="Log and data storage",
        covers="Where logs, traces and metrics come to rest, and for how long.",
        default_uncovered=(
            "Does not cover exported copies. An OpenTelemetry destination receives a copy and "
            "stores it wherever that collector lives, outside this promise entirely."
        ),
    ),
)


@dataclass(frozen=True)
class ServiceDefinition:
    """One billable service.

    Attributes:
        service: The service id, one of :data:`SERVICES`.
        label: Operator-facing name.
        unit: The unit its quantity is counted in.
        driver: What makes the number go up, so an operator reading a spike knows where to look.
    """

    service: str
    label: str
    unit: str
    driver: str


#: The five services §29.6 names for daily usage and spend.
SERVICE_CATALOG: Tuple[ServiceDefinition, ...] = (
    ServiceDefinition(
        service="delivery",
        label="Delivery",
        unit="requests",
        driver="Requests served at the edge, and bytes egressed to readers.",
    ),
    ServiceDefinition(
        service="build",
        label="Build",
        unit="build-minutes",
        driver="Deterministic builds run per release, including rebuilt previews.",
    ),
    ServiceDefinition(
        service="function",
        label="Functions",
        unit="invocations",
        driver="Function invocations and the CPU milliseconds they consumed.",
    ),
    ServiceDefinition(
        service="log",
        label="Logs",
        unit="gigabytes",
        driver="Structured log and trace volume retained, which scales with retention days.",
    ),
    ServiceDefinition(
        service="ai",
        label="AI",
        unit="tokens",
        driver="Tokens consumed by Scribe generation and answer resolution.",
    ),
)


#: Residency class descriptions, sharing the edge surface's vocabulary.
RESIDENCY_CLASS_CATALOG: Tuple[Tuple[str, str], ...] = (
    (
        "in-region-only",
        "Data for this stage stays inside the named regions, and a request that cannot be served "
        "there fails rather than travelling.",
    ),
    (
        "region-pinned",
        "This stage prefers the named regions and may fail over outside them during an incident. "
        "That failover is the difference between this and in-region-only, and it is the whole "
        "difference.",
    ),
    (
        "unrestricted",
        "This stage runs wherever capacity is. No residency promise is made, and saying so "
        "plainly is better than a promise nobody can keep.",
    ),
)


# ─── Refusal and warning vocabulary ───────────────────────────────────────────

InsightRefusalReason = Literal[
    "observed-without-collector",
    "billable-without-meter",
    "savings-without-meter",
    "forecast-presented-as-actual",
    "currency-mismatch",
    "residency-gap-unstated",
    "residency-violation",
    "residency-stage-missing",
    "retention-below-floor",
    "privacy-threshold-below-floor",
    "tail-exceeds-ceiling",
    "tail-without-reason",
    "tail-redaction-removed",
    "export-header-inline",
    "export-endpoint-insecure",
    "export-without-signals",
    "budget-without-threshold",
    "budget-not-positive",
    "policy-version-conflict",
]

# One operator-facing sentence per refusal, returned verbatim by the REST layer so the reason a
# control is disabled reaches the operator as words rather than as a code. The reason code is
# ours to style and test against; the words are not, because two copies of these sentences would
# eventually disagree and the copy on screen would be the one an operator trusted.
_REFUSAL_SENTENCES: Dict[str, str] = {
    "observed-without-collector": (
        "This signal claims to have been observed, and nothing is observing this lane. There is "
        "no collector in the request path, so every number here is modelled from policy rather "
        "than measured from traffic. A chart that cannot tell the difference is one somebody will "
        "promote a release against."
    ),
    "billable-without-meter": (
        "This usage record is modelled and cannot be marked billable. A modelled cost is this "
        "platform's own arithmetic about what a lane would consume; presenting it as a charge is "
        "not an estimate but an invented invoice. Chart it, forecast it and export it — do not "
        "bill it."
    ),
    "savings-without-meter": (
        "Measured cache savings require a metered basis. A saving computed from a model is a "
        "discount nobody gave, and it is the number most likely to be quoted back to this "
        "platform later. Leave it unset until something meters it."
    ),
    "forecast-presented-as-actual": (
        "A forecast cannot be written as an observed amount. A projection summed into a total "
        "alongside things that happened produces a figure that is neither, and nobody reading it "
        "afterwards can tell which part was which. Forecasts belong in the forecast field."
    ),
    "currency-mismatch": (
        "This budget is denominated in a different currency from the usage it would be compared "
        "against. Converting at a rate this system invented would make the alert threshold "
        "depend on an exchange rate nobody reviewed. Use one currency, or set a budget per "
        "currency."
    ),
    "residency-gap-unstated": (
        "This residency lane states no gap. Every placement leaves something uncovered — a "
        "network path, a certificate log, an exported copy — and a claim with no stated gap is "
        "not a stronger promise, it is the same promise with the gap unwritten. That is the "
        "version that gets quoted to a regulator. Say what it does not cover."
    ),
    "residency-violation": (
        "This lane is set to unrestricted with no stated reason, or is confined to no region at "
        "all. An unrestricted stage makes no residency promise, which is a legitimate choice and "
        "never an accidental one, so it has to be explained. A confined stage naming no region is "
        "the strictest-sounding setting that means nothing."
    ),
    "residency-stage-missing": (
        "Residency has to be stated for all six stages. A lane that describes where requests "
        "arrive but not where logs come to rest reads as a complete promise and is not one — and "
        "log storage is the stage that most often sits somewhere else."
    ),
    "retention-below-floor": (
        "This shortens log retention below the floor ordinary incident review needs, with no "
        "stated reason. The evidence a later investigation wants is always the evidence somebody "
        "shortened retention on first. Give a reason, or keep the floor."
    ),
    "privacy-threshold-below-floor": (
        "This lowers the privacy threshold below the point where an aggregate can identify the "
        "reader behind it. Below it a chart stops reporting a population and starts reporting a "
        "person. Raise the threshold, or accept the suppressed cells."
    ),
    "tail-exceeds-ceiling": (
        "This live tail asks for a sample rate or an event rate above the lane's ceiling. The "
        "ceiling exists so opening a tail cannot raise the lane's worst case without an audited "
        "policy change, and a tail is the surface where request data is on screen by definition. "
        "Tighten the session, or raise the lane ceiling deliberately."
    ),
    "tail-without-reason": (
        "This live tail has no stated reason. A tail is a capture of live reader traffic in front "
        "of a person, and the question at review is never that one was opened but why. An empty "
        "answer is the one nobody can defend."
    ),
    "tail-redaction-removed": (
        "This live tail asks for fields outside the redaction allowlist. The allowlist is what "
        "makes a tail safe to open at all; a session that could add a cookie or an authorization "
        "header to the stream is a credential capture with a debugging justification."
    ),
    "export-header-inline": (
        "This export supplies an authorization header value inline. Export headers are bearer "
        "tokens, and there is deliberately nowhere in this system to store one — a reference is "
        "resolved at the boundary instead. Name a secret, not a value."
    ),
    "export-endpoint-insecure": (
        "This export endpoint is plaintext HTTP. The stream it would carry is logs and traces, "
        "which is request data, so shipping it unencrypted undoes every residency and redaction "
        "promise this lane makes on the way to the collector. Use HTTPS."
    ),
    "export-without-signals": (
        "This export destination receives no signal classes, so it would be configured, enabled "
        "and silent. Choose at least one of metrics, logs or traces."
    ),
    "budget-without-threshold": (
        "This budget has no alert threshold, so it would never fire. A budget nobody is told "
        "about is a number in a settings page rather than a control."
    ),
    "budget-not-positive": (
        "A budget has to be a positive amount. Zero is not a budget that alerts immediately; it "
        "is a budget whose thresholds have no meaning."
    ),
    "policy-version-conflict": (
        "Another operator changed this lane's observability policy while this edit was being "
        "prepared. Re-read the policy and try again."
    ),
}

#: Refusals with no acknowledgement path. Each one is a false measurement, a false charge, an
#: unstated residency gap or a capture of reader data — never merely a cost. An "I accept the
#: risk" checkbox over these would be a checkbox over a number somebody else will act on, or over
#: the redaction that keeps a credential off an operator's screen. Every refusal this module
#: raises is hard; the set is spelled out in full anyway so a future reason added to
#: :data:`_REFUSAL_SENTENCES` has to decide which side it is on rather than defaulting to one.
_HARD_REFUSALS = frozenset(
    {
        "observed-without-collector",
        "billable-without-meter",
        "savings-without-meter",
        "forecast-presented-as-actual",
        "currency-mismatch",
        "residency-gap-unstated",
        "residency-violation",
        "residency-stage-missing",
        "retention-below-floor",
        "privacy-threshold-below-floor",
        "tail-exceeds-ceiling",
        "tail-without-reason",
        "tail-redaction-removed",
        "export-header-inline",
        "export-endpoint-insecure",
        "export-without-signals",
        "budget-without-threshold",
        "budget-not-positive",
        "policy-version-conflict",
    }
)

#: Warning reasons an operator may acknowledge. These cost fidelity, attribution or notice; none
#: of them states a measurement nothing took, bills a model, or puts reader data on a screen.
_WARNING_SENTENCES: Dict[str, str] = {
    "retention-shortened": (
        "This shortens retention. Anything already past the new window is deleted on the next "
        "sweep, and the incident that wants it will be the one that happens next week."
    ),
    "sampling-sparse": (
        "This sampling rate is low enough that a rare route may produce no traces at all. The "
        "chart will still draw, and the absence of a slow request will look like the absence of a "
        "problem."
    ),
    "residency-partially-unrestricted": (
        "Some stages on this lane are unrestricted while others are pinned. That is a coherent "
        "choice and an easy one to misread: the lane as a whole makes only the weakest promise "
        "any of its stages makes."
    ),
    "export-partial-signals": (
        "This destination receives only some signal classes. A collector holding traces without "
        "the metrics they were sampled against cannot tell a rare event from a rarely sampled one."
    ),
    "budget-near-exhausted": (
        "Spend is already close to this budget for the current period, so the first alert will "
        "fire almost immediately after saving. That is usually the intent when a budget is being "
        "lowered and rarely when one is being created."
    ),
    "threshold-suppresses-most": (
        "At this privacy threshold most cells in the current data would be suppressed. The chart "
        "will be mostly empty, which is a privacy property working correctly and looks like a "
        "broken dashboard."
    ),
    "forecast-wide": (
        "There is too little history to forecast this service confidently. The projection is "
        "drawn from a short window and will move a lot as days arrive."
    ),
    "synthetic-single-region": (
        "This check runs from one region, so it reports that region's health rather than the "
        "lane's. A regional outage elsewhere will not appear here at all."
    ),
}

#: The shortest log retention that does not require a stated reason. **Invented**, not derived
#: from the roadmap: one week is the span that reliably contains "it broke on Friday and somebody
#: looked on Monday", which is the review this retention exists to serve.
_LOG_RETENTION_FLOOR_DAYS = 7

#: The lowest privacy threshold that may be set without refusal. **Invented.** Five is the
#: smallest population conventionally treated as non-identifying in aggregate reporting, and the
#: V190 default of ten sits deliberately above it so the default is not the floor.
_PRIVACY_THRESHOLD_FLOOR = 5

#: Below this fraction of sampled requests, a trace chart is sparse enough to be worth a sentence.
#: **Invented**, and low on purpose: the warning is for a rate that will silently omit rare
#: routes, not for ordinary head sampling.
_SPARSE_SAMPLE_RATE = 0.001

#: Days of history below which a forecast is flagged as wide. **Invented.** Seven days is the
#: shortest window that contains one of every weekday, and traffic is weekly before it is
#: anything else.
_MIN_FORECAST_HISTORY_DAYS = 7

#: Fraction of a budget already consumed at which creating or lowering it warns. **Invented.**
_BUDGET_NEAR_EXHAUSTED_RATIO = 0.8

#: Fraction of cells suppressed at which a privacy threshold is worth a sentence. **Invented.**
_MOSTLY_SUPPRESSED_RATIO = 0.5


@dataclass(frozen=True)
class InsightRefusal:
    """A named, explained refusal to change observability, residency or budget policy."""

    reason: str
    sentence: str

    @staticmethod
    def of(reason: str) -> "InsightRefusal":
        """Build a refusal from its reason code.

        Args:
            reason: One of :data:`InsightRefusalReason`.

        Returns:
            The refusal with its operator-facing sentence attached.
        """
        return InsightRefusal(
            reason=reason,
            sentence=_REFUSAL_SENTENCES.get(
                reason, "This observability change cannot be applied."
            ),
        )


@dataclass(frozen=True)
class InsightWarning:
    """A named concern that does not block the write.

    Attributes:
        code: One of the keys of :data:`_WARNING_SENTENCES`.
        message: The operator-facing sentence.
        field: Which field the warning attaches to, so the UI can place it.
    """

    code: str
    message: str
    field: Optional[str] = None

    @staticmethod
    def of(code: str, field: Optional[str] = None) -> "InsightWarning":
        """Build a warning from its code.

        Args:
            code: One of the keys of :data:`_WARNING_SENTENCES`.
            field: The field the warning is about, when there is one.

        Returns:
            The warning with its sentence attached.
        """
        return InsightWarning(
            code=code,
            message=_WARNING_SENTENCES.get(
                code, "This observability change may not behave as intended."
            ),
            field=field,
        )


class SlateInsightRefusedError(Exception):
    """An observability, residency or budget change was refused.

    Raising rather than returning is deliberate, matching
    :class:`app.slate_functions.SlateFunctionRefusedError`: a refused write must never be able to
    fall through to a persist because a caller forgot to inspect a return value.
    """

    def __init__(self, refusal: InsightRefusal) -> None:
        self.refusal = refusal
        self.code = refusal.reason
        super().__init__(refusal.sentence)


def _refuse(reason: str) -> None:
    """Raise the named refusal.

    Args:
        reason: One of :data:`InsightRefusalReason`.

    Raises:
        SlateInsightRefusedError: Always.
    """
    raise SlateInsightRefusedError(InsightRefusal.of(reason))


# ─── Honesty-carrying verdicts ────────────────────────────────────────────────
#
# These are the observability analogue of :class:`app.slate_functions.InvocationVerdict`. The
# fields that say what the numbers are worth are REQUIRED rather than optional, and defaulted to
# the honest value, so a mapping that dropped them is a type error rather than a screen that
# quietly stopped saying "modelled".


@dataclass(frozen=True)
class CorrelationKey:
    """The three columns every signal in V190 shares.

    A signal that cannot be keyed is not emitted at all — see :func:`correlate_signals` — because
    a point with no release is a point a drill-down cannot land on, and a chart whose drill-down
    lands somewhere else is worse than a chart with a gap in it.

    Attributes:
        environment_id: The lane. Never empty.
        release_id: The release, or None when the point genuinely spans releases.
        region: The region, or ``'auto'``.
    """

    environment_id: str
    release_id: Optional[str]
    region: str


@dataclass(frozen=True)
class MetricPoint:
    """One correlated metric point, carrying what it is worth.

    Attributes:
        key: Release, environment and region correlation.
        family: One of :data:`METRIC_FAMILIES`.
        metric_key: The series within the family, e.g. ``latency-p95``.
        window_start: Inclusive start of the aggregation window.
        window_end: Exclusive end.
        value: The value, or None when suppressed.
        unit: Unit of the value.
        sample_count: Population behind the point.
        suppressed: Whether the value was withheld for falling below the privacy threshold.
        basis: ``modelled`` or ``edge-observed``. Always ``modelled`` from this module.
        observed: Always False. Nothing is in the request path to observe.
    """

    key: CorrelationKey
    family: str
    metric_key: str
    window_start: datetime
    window_end: datetime
    value: Optional[float]
    unit: str
    sample_count: int
    suppressed: bool
    basis: str = "modelled"
    observed: bool = False


@dataclass(frozen=True)
class TelemetryVerdict:
    """The answer to "what does this lane's telemetry actually tell me".

    Attributes:
        environment_id: The lane.
        points: The correlated metric points.
        dropped: Points that could not be correlated and were therefore not emitted, with the
            reason each was dropped. Reported rather than silently discarded: a surface that shows
            a chart with a hole in it and no explanation teaches operators the data is unreliable.
        suppressed_count: How many points were withheld for privacy.
        warnings: Non-blocking concerns.
        basis: Always ``policy-modelled``.
        observed: Always False.
        enforced: Always False.
    """

    environment_id: str
    points: Tuple[MetricPoint, ...]
    dropped: Tuple[Tuple[str, str], ...]
    suppressed_count: int
    warnings: Tuple[InsightWarning, ...]
    basis: str = "policy-modelled"
    observed: bool = False
    enforced: bool = False


@dataclass(frozen=True)
class UsageRollup:
    """Daily usage and spend for one service, rolled up over a period.

    Attributes:
        service: One of :data:`SERVICES`.
        quantity: Total quantity consumed.
        unit: Unit of the quantity.
        amount: Total spend.
        currency: ISO 4217 code.
        included_quantity: How much fell inside the plan quota.
        overage_quantity: How much exceeded it.
        cache_savings_amount: Measured savings, or None. None unless metered.
        forecast_amount: Projected spend for the remainder of the period, or None. Carried
            separately from ``amount`` so a projection is never summed into a total as though it
            had happened.
        days: How many daily records contributed.
        basis: ``modelled`` or ``metered``. Always ``modelled`` from this module.
        metered: Always False.
        billable: Always False. A modelled cost is not a charge.
    """

    service: str
    quantity: float
    unit: str
    amount: float
    currency: str
    included_quantity: float
    overage_quantity: float
    cache_savings_amount: Optional[float]
    forecast_amount: Optional[float]
    days: int
    basis: str = "modelled"
    metered: bool = False
    billable: bool = False


@dataclass(frozen=True)
class BudgetAlert:
    """One threshold crossing, with the arithmetic behind it.

    Attributes:
        budget_id: The budget that fired.
        threshold: The fraction crossed.
        observed_amount: Spend observed when it fired.
        budget_amount: The budget it was compared against, captured so later edits do not rewrite
            history.
        currency: ISO 4217 code, the same for both amounts by refusal.
        period_start: Inclusive start of the period.
        period_end: Inclusive end.
        basis: ``modelled`` or ``metered``. Always ``modelled`` from this module.
        delivery_state: Always ``not-dispatched``. Nothing dispatches.
    """

    budget_id: str
    threshold: float
    observed_amount: float
    budget_amount: float
    currency: str
    period_start: date
    period_end: date
    basis: str = "modelled"
    delivery_state: str = "not-dispatched"


@dataclass(frozen=True)
class BudgetEvaluation:
    """The result of comparing spend against a budget.

    Attributes:
        budget_id: The budget evaluated.
        consumed_ratio: Spend divided by budget.
        alerts: Thresholds crossed, in ascending order.
        warnings: Non-blocking concerns.
        basis: Always ``modelled``.
    """

    budget_id: str
    consumed_ratio: float
    alerts: Tuple[BudgetAlert, ...]
    warnings: Tuple[InsightWarning, ...]
    basis: str = "modelled"


# ─── Normalization ────────────────────────────────────────────────────────────


def _as_str(value: Any, fallback: str = "") -> str:
    """Coerce to a string, falling back when absent or of the wrong type."""
    return value if isinstance(value, str) else fallback


def _as_int(value: Any, fallback: int = 0) -> int:
    """Coerce to an int, falling back on anything non-numeric or boolean."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    return fallback


def _as_float(value: Any, fallback: float = 0.0) -> float:
    """Coerce to a float, falling back on anything non-numeric or boolean."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    return fallback


def _as_opt_str(value: Any) -> Optional[str]:
    """Coerce to a stripped string, or None when it is absent, blank or of the wrong type.

    Whitespace collapses to None rather than surviving as a truthy value. Every caller of this is
    a field a refusal tests for presence — a waiver reason, a residency reason, a stated gap — and
    a lane whose reason is three spaces has stated no reason at all while reading as though it had.
    """
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _as_opt_float(value: Any) -> Optional[float]:
    """Coerce to a float or None.

    None rather than zero for an absent measurement, for the reason the authoring surface's
    ``nullableNum`` states: a zero here would be a measurement, and the absence of one is the
    truth.
    """
    if value is None or isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _as_str_list(value: Any) -> List[str]:
    """Coerce to a list of strings, dropping non-strings rather than failing."""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def normalize_policy(policy: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce an observability policy mapping into the canonical shape V190 assumes.

    Missing fields take their V190 column default. Doing this once, here, is what lets
    :func:`signals_digest` produce the same hash for two policies that differ only in what they
    left unset.

    Args:
        policy: Raw policy mapping from a request body or a database row.

    Returns:
        The canonical policy dict.
    """
    return {
        "telemetry_enabled": bool(policy.get("telemetry_enabled", False)),
        "metric_retention_days": _as_int(policy.get("metric_retention_days"), 90),
        "log_retention_days": _as_int(policy.get("log_retention_days"), 14),
        "trace_retention_days": _as_int(policy.get("trace_retention_days"), 7),
        "default_sample_rate": _as_float(policy.get("default_sample_rate"), 0.05),
        "max_tail_sample_rate": _as_float(policy.get("max_tail_sample_rate"), 0.01),
        "max_tail_events_per_sec": _as_int(policy.get("max_tail_events_per_sec"), 100),
        "privacy_threshold": _as_int(policy.get("privacy_threshold"), 10),
        "retention_waiver_reason": _as_opt_str(policy.get("retention_waiver_reason")),
        "edge_attached": bool(policy.get("edge_attached", False)),
    }


def normalize_residency_lane(lane: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a residency lane mapping into canonical shape.

    The gap sentence falls back to the stage's catalog default rather than to an empty string,
    because a lane whose gap is blank reads as a lane with no gap — which is the one claim §29.6
    exists to prevent.

    Args:
        lane: Raw residency lane mapping.

    Returns:
        The canonical lane dict.
    """
    stage = _as_str(lane.get("stage"))
    default_uncovered = ""
    for definition in RESIDENCY_STAGE_CATALOG:
        if definition.stage == stage:
            default_uncovered = definition.default_uncovered
            break
    return {
        "stage": stage,
        "residency_class": _as_str(lane.get("residency_class"), "in-region-only"),
        "regions": sorted({region for region in _as_str_list(lane.get("regions")) if region}),
        "uncovered_sentence": _as_opt_str(lane.get("uncovered_sentence")) or default_uncovered,
        "residency_waiver_reason": _as_opt_str(lane.get("residency_waiver_reason")),
        "enforced": bool(lane.get("enforced", False)),
    }


def normalize_export(export: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce an OTLP export destination mapping into canonical shape.

    Note what is absent: there is no ``headers`` key in the result, and there is nowhere in V190
    to put one. :func:`validate_export` refuses a body that supplies one rather than dropping it
    silently, because an operator who pasted a bearer token into a form and saw it accepted would
    reasonably believe it had been stored and used.

    Args:
        export: Raw export mapping.

    Returns:
        The canonical export dict.
    """
    signals = [signal for signal in _as_str_list(export.get("signals")) if signal in SIGNAL_CLASSES]
    return {
        "label": _as_str(export.get("label")),
        "endpoint": _as_str(export.get("endpoint")),
        "protocol": _as_str(export.get("protocol"), "http/protobuf"),
        "signals": sorted(set(signals)) or ["metrics", "traces"],
        "header_secret_ref": _as_opt_str(export.get("header_secret_ref")),
        "enabled": bool(export.get("enabled", False)),
    }


def normalize_budget(budget: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a budget mapping into canonical shape.

    Args:
        budget: Raw budget mapping.

    Returns:
        The canonical budget dict.
    """
    thresholds = sorted(
        {
            round(_as_float(threshold), 3)
            for threshold in (budget.get("alert_thresholds") or [])
            if isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
        }
    )
    service = _as_str(budget.get("service")) or None
    return {
        "label": _as_str(budget.get("label")),
        "service": service if service in SERVICES else None,
        "period": _as_str(budget.get("period"), "monthly"),
        "amount": _as_float(budget.get("amount")),
        "currency": _as_str(budget.get("currency"), "USD").upper(),
        "alert_thresholds": thresholds or [0.8, 1.0],
        "notify_channel_ref": _as_opt_str(budget.get("notify_channel_ref")),
        "enabled": bool(budget.get("enabled", True)),
    }


def normalize_tail_request(request: Mapping[str, Any]) -> Dict[str, Any]:
    """Coerce a live tail request into canonical shape.

    The redaction allowlist defaults to :data:`EVIDENCE_KEYS` rather than to an empty list,
    because an empty allowlist would read as "redact nothing" to a careless reader of the stored
    row and as "allow nothing" to a careful one, and the two are opposite.

    Args:
        request: Raw tail request mapping.

    Returns:
        The canonical tail request dict.
    """
    requested = _as_str_list(request.get("redaction_allowlist"))
    return {
        "sample_rate": _as_float(request.get("sample_rate"), 0.001),
        "max_events_per_sec": _as_int(request.get("max_events_per_sec"), 10),
        # Sorted in both branches, not only when the caller supplied a list. Normalizing an
        # already-normalized request must be a no-op, or the digest of a stored session and the
        # digest of the same session read back and re-normalized would disagree.
        "redaction_allowlist": sorted(set(requested)) if requested else sorted(EVIDENCE_KEYS),
        "filter_expression": _as_opt_str(request.get("filter_expression")),
        "reason": _as_str(request.get("reason")).strip(),
    }


# ─── Redaction ────────────────────────────────────────────────────────────────


def redact_evidence(
    evidence: Mapping[str, Any], allowlist: Sequence[str] = EVIDENCE_KEYS
) -> Dict[str, Any]:
    """Drop every key outside the allowlist.

    An allowlist rather than a denylist, matching V188's security events and V189's invocations
    and for the same reason: a denylist has to anticipate every header worth hiding, and it is
    always the one nobody anticipated that turns up in a screenshot. The store calls this itself
    rather than trusting callers to, so there is no path that writes evidence unredacted.

    Args:
        evidence: Raw evidence mapping.
        allowlist: Keys permitted through. Defaults to :data:`EVIDENCE_KEYS`.

    Returns:
        A new mapping containing only permitted keys.
    """
    permitted = set(allowlist)
    return {key: value for key, value in evidence.items() if key in permitted}


# ─── Validation ───────────────────────────────────────────────────────────────


def validate_policy(
    policy: Mapping[str, Any],
    *,
    current: Optional[Mapping[str, Any]] = None,
    suppressed_ratio: Optional[float] = None,
) -> Tuple[InsightWarning, ...]:
    """Validate an observability policy write.

    Args:
        policy: The policy being written, already normalized.
        current: The policy being replaced, when there is one, so retention shortening can be
            detected rather than inferred from the new value alone.
        suppressed_ratio: Fraction of current cells that would be suppressed at the new privacy
            threshold, when the caller has computed it.

    Returns:
        Non-blocking warnings.

    Raises:
        SlateInsightRefusedError: On retention below the floor with no stated reason, or a privacy
            threshold below the identifiability floor.
    """
    warnings: List[InsightWarning] = []

    if (
        policy["log_retention_days"] < _LOG_RETENTION_FLOOR_DAYS
        and not policy["retention_waiver_reason"]
    ):
        _refuse("retention-below-floor")

    if policy["privacy_threshold"] < _PRIVACY_THRESHOLD_FLOOR:
        _refuse("privacy-threshold-below-floor")

    if current is not None:
        for field_name in ("metric_retention_days", "log_retention_days", "trace_retention_days"):
            if policy[field_name] < _as_int(current.get(field_name), policy[field_name]):
                warnings.append(InsightWarning.of("retention-shortened", field_name))
                break

    if 0 < policy["default_sample_rate"] < _SPARSE_SAMPLE_RATE:
        warnings.append(InsightWarning.of("sampling-sparse", "default_sample_rate"))

    if suppressed_ratio is not None and suppressed_ratio > _MOSTLY_SUPPRESSED_RATIO:
        warnings.append(InsightWarning.of("threshold-suppresses-most", "privacy_threshold"))

    return tuple(warnings)


def validate_residency_lane(lane: Mapping[str, Any]) -> Tuple[InsightWarning, ...]:
    """Validate one residency lane write.

    Args:
        lane: The lane being written, already normalized.

    Returns:
        Non-blocking warnings.

    Raises:
        SlateInsightRefusedError: On an unstated gap, an unexplained unrestricted class, or a
            confined class naming no region.
    """
    if not lane["uncovered_sentence"].strip():
        _refuse("residency-gap-unstated")

    if lane["residency_class"] == "unrestricted":
        if not lane["residency_waiver_reason"]:
            _refuse("residency-violation")
    elif not lane["regions"]:
        _refuse("residency-violation")

    return ()


def residency_coverage(
    lanes: Sequence[Mapping[str, Any]],
) -> Tuple[str, Tuple[InsightWarning, ...]]:
    """Summarize a lane set as the single promise it actually makes.

    The lane as a whole makes only the weakest promise any of its stages makes, which is the fact
    an operator most often gets wrong: pinning five stages and leaving log storage unrestricted is
    an unrestricted lane, not a mostly-pinned one.

    Args:
        lanes: All residency lanes for one environment, already normalized.

    Returns:
        A tuple of the effective residency class and any warnings.

    Raises:
        SlateInsightRefusedError: When any of the six stages is missing.
    """
    present = {lane["stage"] for lane in lanes}
    if present != set(RESIDENCY_STAGES):
        _refuse("residency-stage-missing")

    classes = [lane["residency_class"] for lane in lanes]
    effective = "in-region-only"
    for candidate in RESIDENCY_CLASSES:
        if candidate in classes:
            effective = candidate

    warnings: List[InsightWarning] = []
    if "unrestricted" in classes and len(set(classes)) > 1:
        warnings.append(InsightWarning.of("residency-partially-unrestricted", "residency_class"))

    return effective, tuple(warnings)


def validate_export(
    export: Mapping[str, Any], *, raw: Optional[Mapping[str, Any]] = None
) -> Tuple[InsightWarning, ...]:
    """Validate an OTLP export destination write.

    Args:
        export: The destination being written, already normalized.
        raw: The unnormalized body, so an inline header value can be refused rather than silently
            dropped by normalization.

    Returns:
        Non-blocking warnings.

    Raises:
        SlateInsightRefusedError: On an inline header value, a plaintext endpoint, or no signals.
    """
    if raw is not None and (raw.get("headers") or raw.get("header_value")):
        _refuse("export-header-inline")

    endpoint = export["endpoint"].strip()
    if endpoint.lower().startswith("http://"):
        _refuse("export-endpoint-insecure")

    if not export["signals"]:
        _refuse("export-without-signals")

    warnings: List[InsightWarning] = []
    if set(export["signals"]) != set(SIGNAL_CLASSES):
        warnings.append(InsightWarning.of("export-partial-signals", "signals"))

    return tuple(warnings)


def validate_budget(
    budget: Mapping[str, Any],
    *,
    usage_currency: Optional[str] = None,
    consumed_amount: Optional[float] = None,
) -> Tuple[InsightWarning, ...]:
    """Validate a budget write.

    Args:
        budget: The budget being written, already normalized.
        usage_currency: Currency of the usage this budget would be compared against, when known.
        consumed_amount: Spend already recorded in the current period, when known.

    Returns:
        Non-blocking warnings.

    Raises:
        SlateInsightRefusedError: On a non-positive amount, no thresholds, or a currency that does
            not match the usage it would be compared against.
    """
    if budget["amount"] <= 0:
        _refuse("budget-not-positive")

    if not budget["alert_thresholds"]:
        _refuse("budget-without-threshold")

    if usage_currency and usage_currency.upper() != budget["currency"]:
        _refuse("currency-mismatch")

    warnings: List[InsightWarning] = []
    if (
        consumed_amount is not None
        and budget["amount"] > 0
        and consumed_amount / budget["amount"] >= _BUDGET_NEAR_EXHAUSTED_RATIO
    ):
        warnings.append(InsightWarning.of("budget-near-exhausted", "amount"))

    return tuple(warnings)


def validate_synthetic_check(check: Mapping[str, Any]) -> Tuple[InsightWarning, ...]:
    """Validate a synthetic check write.

    Args:
        check: The check being written.

    Returns:
        Non-blocking warnings.
    """
    warnings: List[InsightWarning] = []
    regions = _as_str_list(check.get("regions"))
    if check.get("enabled") and len(regions) == 1:
        warnings.append(InsightWarning.of("synthetic-single-region", "regions"))
    return tuple(warnings)


def plan_live_tail(
    request: Mapping[str, Any], policy: Mapping[str, Any]
) -> Dict[str, Any]:
    """Validate a live tail request against the lane's ceilings and return the session to record.

    The ceilings are checked here rather than clamped, deliberately. Clamping would let an
    operator ask for a rate they do not get and read a stream they believe is complete, which on
    this surface means concluding a route is quiet when it was merely sampled away.

    Args:
        request: The tail request, already normalized.
        policy: The lane policy, already normalized.

    Returns:
        The session fields to persist.

    Raises:
        SlateInsightRefusedError: On no reason, a rate above a ceiling, or an allowlist widened
            beyond :data:`EVIDENCE_KEYS`.
    """
    if not request["reason"]:
        _refuse("tail-without-reason")

    if (
        request["sample_rate"] > policy["max_tail_sample_rate"]
        or request["max_events_per_sec"] > policy["max_tail_events_per_sec"]
    ):
        _refuse("tail-exceeds-ceiling")

    if not set(request["redaction_allowlist"]).issubset(set(EVIDENCE_KEYS)):
        _refuse("tail-redaction-removed")

    # `requested` rather than `attached`: nothing is in the request path, so a session can be asked
    # for and refused but never attached. The store writes this as a literal for the same reason.
    return {
        "sample_rate": request["sample_rate"],
        "max_events_per_sec": request["max_events_per_sec"],
        "redaction_allowlist": request["redaction_allowlist"],
        "filter_expression": request["filter_expression"],
        "reason": request["reason"],
        "stream_state": "requested",
        "events_delivered": 0,
        "edge_attached": False,
    }


# ─── Correlation ──────────────────────────────────────────────────────────────


def correlate_signals(
    environment_id: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    privacy_threshold: int = 10,
) -> TelemetryVerdict:
    """Turn stored metric rows into correlated, privacy-thresholded points.

    A row that cannot be keyed is dropped and reported rather than emitted unkeyed. That choice is
    the acceptance criterion: a chart and the drill-down beneath it must mean the same rows, and
    an unkeyed point is one a drill-down cannot land on. Reporting the drop rather than swallowing
    it matters just as much — a hole in a chart with no explanation teaches operators that the
    data is unreliable, which is a more expensive lesson than the missing point.

    Args:
        environment_id: The lane these rows belong to.
        rows: Stored metric rows.
        privacy_threshold: Minimum population before a value may be shown.

    Returns:
        The verdict, carrying points, drops, the suppressed count and its own honesty fields.
    """
    points: List[MetricPoint] = []
    dropped: List[Tuple[str, str]] = []
    suppressed_count = 0

    for row in rows:
        row_id = _as_str(row.get("id"), "<unidentified>")

        row_environment = _as_str(row.get("environment_id"))
        if not row_environment:
            dropped.append((row_id, "no environment: the point cannot be attributed to a lane"))
            continue
        if row_environment != environment_id:
            dropped.append((row_id, "belongs to another environment"))
            continue

        family = _as_str(row.get("metric_family"))
        if family not in METRIC_FAMILIES:
            dropped.append((row_id, f"unknown metric family {family!r}"))
            continue

        window_start = row.get("window_start")
        window_end = row.get("window_end")
        if not isinstance(window_start, datetime) or not isinstance(window_end, datetime):
            dropped.append((row_id, "no aggregation window: the point cannot be placed in time"))
            continue
        if window_end <= window_start:
            dropped.append((row_id, "aggregation window ends before it starts"))
            continue

        sample_count = _as_int(row.get("sample_count"))
        value = _as_opt_float(row.get("value"))
        suppressed = bool(row.get("suppressed")) or sample_count < privacy_threshold
        if suppressed:
            suppressed_count += 1
            value = None
        elif value is None:
            dropped.append((row_id, "reported point carries no value"))
            continue

        points.append(
            MetricPoint(
                key=CorrelationKey(
                    environment_id=row_environment,
                    release_id=_as_str(row.get("release_id")) or None,
                    region=_as_str(row.get("region"), "auto") or "auto",
                ),
                family=family,
                metric_key=_as_str(row.get("metric_key")),
                window_start=window_start,
                window_end=window_end,
                value=value,
                unit=_as_str(row.get("unit"), "count"),
                sample_count=sample_count,
                suppressed=suppressed,
            )
        )

    warnings: List[InsightWarning] = []
    if points and suppressed_count / (len(points) or 1) > _MOSTLY_SUPPRESSED_RATIO:
        warnings.append(InsightWarning.of("threshold-suppresses-most", "privacy_threshold"))

    points.sort(key=lambda point: (point.family, point.metric_key, point.window_start))

    return TelemetryVerdict(
        environment_id=environment_id,
        points=tuple(points),
        dropped=tuple(dropped),
        suppressed_count=suppressed_count,
        warnings=tuple(warnings),
    )


# ─── Usage, forecast and budget ───────────────────────────────────────────────


def roll_up_usage(
    rows: Sequence[Mapping[str, Any]], *, service: str
) -> UsageRollup:
    """Roll daily usage records up into one period total for a service.

    Two things are deliberately not done here. Forecast amounts are never added into ``amount``,
    because a projection summed alongside things that happened produces a figure that is neither.
    And ``cache_savings_amount`` stays None unless every contributing row is metered, because a
    total savings figure assembled from a mix of measured and modelled parts is a measurement in
    presentation and a model in fact.

    Args:
        rows: Daily usage records for one service.
        service: The service being rolled up.

    Returns:
        The rollup, carrying its own honesty fields.

    Raises:
        SlateInsightRefusedError: When rows disagree about currency, since a total across two
            currencies would require an exchange rate this module has no business inventing.
    """
    quantity = 0.0
    amount = 0.0
    included = 0.0
    overage = 0.0
    savings = 0.0
    forecast = 0.0
    has_forecast = False
    all_metered = bool(rows)
    any_savings = False
    currency = "USD"
    unit = "count"
    seen_currency: Optional[str] = None

    for row in rows:
        row_currency = _as_str(row.get("currency"), "USD").upper()
        if seen_currency is None:
            seen_currency = row_currency
        elif row_currency != seen_currency:
            _refuse("currency-mismatch")

        quantity += _as_float(row.get("quantity"))
        amount += _as_float(row.get("amount"))
        included += _as_float(row.get("included_quantity"))
        overage += _as_float(row.get("overage_quantity"))
        unit = _as_str(row.get("unit"), unit)

        if _as_str(row.get("basis")) != "metered":
            all_metered = False

        row_savings = _as_opt_float(row.get("cache_savings_amount"))
        if row_savings is not None:
            savings += row_savings
            any_savings = True

        row_forecast = _as_opt_float(row.get("forecast_amount"))
        if row_forecast is not None:
            forecast += row_forecast
            has_forecast = True

    if seen_currency:
        currency = seen_currency

    for definition in SERVICE_CATALOG:
        if definition.service == service and unit == "count":
            unit = definition.unit
            break

    return UsageRollup(
        service=service,
        quantity=quantity,
        unit=unit,
        amount=amount,
        currency=currency,
        included_quantity=included,
        overage_quantity=overage,
        # Savings survive only when every contributing row was metered. A mixed total would be a
        # measurement in presentation and a model in fact, which is the exact confusion the
        # billable CHECK exists to prevent one table over.
        cache_savings_amount=savings if (any_savings and all_metered) else None,
        forecast_amount=forecast if has_forecast else None,
        days=len(rows),
        basis="metered" if all_metered else "modelled",
        metered=all_metered,
        # Never billable from this module. Even an all-metered rollup is a rollup this process
        # computed, and billing owns what may be charged.
        billable=False,
    )


def forecast_service(
    rows: Sequence[Mapping[str, Any]], *, days_remaining: int
) -> Tuple[Optional[float], Tuple[InsightWarning, ...]]:
    """Project spend for the remainder of a period from the days already recorded.

    A deliberately simple mean-per-day projection rather than a trend fit. A trend fitted to a
    handful of days produces a confident-looking curve whose slope is mostly noise, and the
    surface would render it identically to one fitted to a quarter. When there is too little
    history the warning says so rather than the arithmetic getting cleverer.

    Args:
        rows: Daily usage records already recorded in the period.
        days_remaining: Days left in the period.

    Returns:
        A tuple of the projected additional amount (None when there is no history) and warnings.
    """
    if not rows or days_remaining <= 0:
        return None, ()

    total = sum(_as_float(row.get("amount")) for row in rows)
    per_day = total / len(rows)
    projection = per_day * days_remaining

    warnings: List[InsightWarning] = []
    if len(rows) < _MIN_FORECAST_HISTORY_DAYS:
        warnings.append(InsightWarning.of("forecast-wide", "forecast_amount"))

    return projection, tuple(warnings)


def evaluate_budget(
    budget: Mapping[str, Any],
    *,
    budget_id: str,
    consumed_amount: float,
    consumed_currency: str,
    period_start: date,
    period_end: date,
    already_fired: Sequence[float] = (),
) -> BudgetEvaluation:
    """Compare spend against a budget and produce the alerts that should fire.

    Thresholds already fired for this budget and period are excluded rather than re-emitted.
    Without that, a scheduler retry re-alerts on every pass and the surface teaches operators to
    ignore it — which is the failure mode of every budget alert anybody has ever turned off.

    Args:
        budget: The budget, already normalized.
        budget_id: Identifier of the budget row.
        consumed_amount: Spend observed in the period.
        consumed_currency: Currency of that spend.
        period_start: Inclusive start of the period.
        period_end: Inclusive end.
        already_fired: Thresholds already alerted for this budget and period.

    Returns:
        The evaluation, carrying alerts in ascending threshold order.

    Raises:
        SlateInsightRefusedError: On a currency mismatch.
    """
    if consumed_currency.upper() != budget["currency"]:
        _refuse("currency-mismatch")

    amount = budget["amount"]
    ratio = consumed_amount / amount if amount > 0 else 0.0
    fired = {round(threshold, 3) for threshold in already_fired}

    alerts = tuple(
        BudgetAlert(
            budget_id=budget_id,
            threshold=threshold,
            observed_amount=consumed_amount,
            # Captured at fire time so a later edit to the budget does not rewrite what this alert
            # was compared against.
            budget_amount=amount,
            currency=budget["currency"],
            period_start=period_start,
            period_end=period_end,
        )
        for threshold in sorted(budget["alert_thresholds"])
        if ratio >= threshold and round(threshold, 3) not in fired
    )

    warnings: List[InsightWarning] = []
    if ratio >= _BUDGET_NEAR_EXHAUSTED_RATIO and not alerts:
        warnings.append(InsightWarning.of("budget-near-exhausted", "amount"))

    return BudgetEvaluation(
        budget_id=budget_id,
        consumed_ratio=ratio,
        alerts=alerts,
        warnings=tuple(warnings),
    )


# ─── Determinism receipt ──────────────────────────────────────────────────────


def signals_digest(
    policy: Mapping[str, Any],
    lanes: Sequence[Mapping[str, Any]],
    exports: Sequence[Mapping[str, Any]],
    budgets: Sequence[Mapping[str, Any]],
) -> str:
    """Hash the observability configuration of a lane.

    The counterpart of :func:`app.slate_functions.functions_digest`: a receipt the surface can
    compare against what it last rendered, so "did anything change while I was reading this" is a
    string comparison rather than a diff. Sorted and canonically separated so two configurations
    that differ only in ordering hash identically.

    Args:
        policy: The lane policy, already normalized.
        lanes: Residency lanes, already normalized.
        exports: Export destinations, already normalized.
        budgets: Budgets, already normalized.

    Returns:
        A ``sha256:``-prefixed hex digest, matching the shape V190's digest CHECKs expect.
    """
    payload = {
        "policy": dict(sorted(policy.items())),
        "lanes": sorted((dict(sorted(lane.items())) for lane in lanes), key=lambda x: x["stage"]),
        "exports": sorted(
            (dict(sorted(export.items())) for export in exports), key=lambda x: x["label"]
        ),
        "budgets": sorted(
            (dict(sorted(budget.items())) for budget in budgets), key=lambda x: x["label"]
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
