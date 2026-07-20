"""Slate Edge unified observability, residency, usage and budget REST API — UXE-3.4 (#2476).

The observability control plane the authoring surface consumes:

* ``GET  /v1/slate/insights/metric-families``, ``.../insights/services``,
  ``.../insights/residency-stages``
  — the catalogs as data: every metric family with the question it *cannot* answer, every billable
  service with what drives its number, and every one of the six residency stages with the gap its
  promise leaves. The UI prints what this returns rather than holding a second copy, because two
  copies would eventually disagree and the screen would be the one that lied.

* ``GET  /v1/slate/environments/{environment_id}/insights``
  — the lane: the observability policy, all six residency lanes, the OTLP export destinations, the
  budgets, the synthetic checks, ``policyVersion``, ``signalsDigest`` and the ``enforcement`` block
  described below.

* ``PUT .../insights/policy``, ``PUT .../insights/residency/{stage}``,
  ``POST``/``PUT``/``DELETE .../insights/exports``, ``.../insights/budgets``,
  ``.../insights/checks``
  — the configuration writes. Every one runs the matching gate in :mod:`app.slate_insights` first,
  and every refusal reaches the client as a 409 carrying the module's own sentence.

* ``POST``/``GET .../insights/tail``, ``DELETE .../insights/tail/{session_id}``
  — live tail sessions. A tail is a capture of live reader traffic in front of a person, so it is
  refused without a stated reason, refused above the lane's ceilings, and refused if it asks for a
  field outside the redaction allowlist.

* ``GET .../insights/metrics``, ``.../logs``, ``.../traces[/{trace_id}]``, ``.../usage``,
  ``.../alerts``, ``.../synthetic-results``, ``.../audit``
  — the read surface, correlated on release, environment and region through the same three columns
  on every signal table.

* ``GET .../insights/audit/export`` and ``.../insights/usage/export``
  — CSV evidence, with formula-leading cells neutralized and truncation stated in words.

**The honesty boundary, which is the whole point of this ticket.** ``deploy/`` is a single
Caddyfile: there is no CDN, no collector and no meter behind it. The three predecessor surfaces
guard against *doing* something — purging too much cache, turning protection off, granting reach.
This one guards against *claiming* something, and that is the more dangerous direction: an
unenforced rule is inert, but a fabricated p95 gets a release promoted and a modelled cost
presented as a bill is not a disappointing estimate but an invented invoice. So:

* every policy read and every policy write carries ``enforcement``, whose ``enforced`` is a
  ``Literal[False]``;
* every response that carries a number carries ``basis``, ``observed``, ``metered`` and
  ``billable`` as literal pydantic defaults **no handler assigns** — exactly as ``SimulateResponse``
  does in :mod:`app.slate_functions_routes`. A response model that let a handler set ``billable``
  would be the bug this ticket exists to prevent, so there is no code path here able to write one.

V190 CHECKs the same facts one layer down, and :mod:`app.slate_insights_store` writes them as SQL
literals rather than as parameters. Three independent layers say the same thing because the claim
is the product.

Authorization: reads require VERSIONS/VIEW, writes require VERSIONS/PUBLISH. As in
:mod:`app.slate_cache_routes`, :mod:`app.slate_security_routes` and
:mod:`app.slate_functions_routes` there is no separate ``insights`` resource — inventing a
permission dimension the roles matrix does not render would leave it ungrantable in the UI.

Export is VIEW rather than PUBLISH. "What did this lane cost, and who changed retention" is the
auditor's whole job, and gating it behind the permission to *change* observability would put the
answer out of reach of exactly the person asking.

Scope misses answer 404 (not 403) so cross-tenant probes cannot confirm a lane exists.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id
from .database import db
from .permissions import Action, Resource, enforce_permission
from .slate_auth import validate_slate_authentication
from .slate_deployment_store import get_environment
from .slate_insights import (
    METRIC_FAMILY_CATALOG,
    RESIDENCY_CLASS_CATALOG,
    RESIDENCY_STAGE_CATALOG,
    RESIDENCY_STAGES,
    SERVICE_CATALOG,
    InsightRefusal,
    SlateInsightRefusedError,
    correlate_signals,
    forecast_service,
    normalize_budget,
    normalize_export,
    normalize_policy,
    normalize_residency_lane,
    normalize_tail_request,
    plan_live_tail,
    residency_coverage,
    roll_up_usage,
    signals_digest,
    validate_budget,
    validate_export,
    validate_policy,
    validate_residency_lane,
    validate_synthetic_check,
)
from .slate_insights_store import (
    SlateInsightPolicyConflictError,
    SlateInsightStoreError,
    acknowledge_budget_alert,
    append_audit,
    bump_policy_version,
    close_tail_session,
    delete_budget,
    delete_export,
    delete_synthetic_check,
    ensure_policy,
    ensure_residency_lanes,
    get_trace,
    list_audit,
    list_budget_alerts,
    list_budgets,
    list_exports,
    list_logs,
    list_metric_series,
    list_residency_lanes,
    list_synthetic_checks,
    list_synthetic_results,
    list_tail_sessions,
    list_traces,
    list_usage,
    open_tail_session,
    update_policy,
    upsert_budget,
    upsert_export,
    upsert_residency_lane,
    upsert_synthetic_check,
)

router = APIRouter(prefix="/v1/slate", tags=["slate-insights"])


#: Stated on every policy read and every write outcome. The observability counterpart of
#: :data:`app.slate_functions_routes._NO_EXECUTION_SENTENCE`, and louder than it for the reason the
#: module docstring gives: a function that does not run is inert, and a chart that was never
#: measured is acted upon.
_NO_COLLECTOR_SENTENCE = (
    "No collector is attached to this environment. Nothing sits in the request path to measure "
    "it, so every number on this surface is modelled from the recorded policy rather than "
    "observed from traffic, and no residency lane, export destination or budget here acts on "
    "anything."
)

#: Stated on every signal stream — metrics, logs, traces and synthetic results.
_NO_OBSERVATION_SENTENCE = (
    "These records are modelled from the recorded policy, not observed in a request path. A "
    "chart that cannot tell the difference is one somebody will promote a release against."
)

#: Stated wherever money is rendered. The single most consequential sentence on the surface.
_NO_METER_SENTENCE = (
    "These amounts are modelled and are not a bill. Nothing meters these lanes, so the figures "
    "here may be charted, forecast, compared and exported — they may not be invoiced. A modelled "
    "cost presented as a charge is not a disappointing estimate but an invented invoice."
)

#: Stated wherever a forecast is rendered beside an actual.
_FORECAST_SENTENCE = (
    "A forecast is carried in its own field and is never summed into a total, because a "
    "projection added to things that happened produces a figure that is neither."
)

#: Why a never-configured residency lane is created as ``unrestricted`` rather than at the
#: strictest class.
#:
#: The tempting default is ``in-region-only``, on the reasoning that a surface should start safe.
#: It is wrong here, and the reason is the whole point of §29.6. ``in-region-only`` is not a safe
#: default but a *compliance claim*, and creating six of them for a lane nobody has configured
#: asserts a promise nobody made — which is precisely the overstatement ``uncovered_sentence`` is
#: NOT NULL to prevent. It would also have to name a region to satisfy
#: ``slate_residency_lanes_confined_needs_regions``, and the only available placeholder is
#: ``auto``, so the row would end up claiming confinement to something that is not a region.
#:
#: ``unrestricted`` with this reason is the honest bootstrap: no residency promise has been made
#: for this stage, said plainly, which V190 accepts because
#: ``slate_residency_lanes_unrestricted_needs_reason`` asks only that loosening be explained. It
#: reads as weaker and is more truthful, and nothing is enforced either way while ``enforced`` is
#: FALSE. Configuring a stage is then a deliberate act that tightens it.
_UNCONFIGURED_LANE_REASON = (
    "This stage has not been configured, so no residency promise has been made for it. A lane "
    "created at the strictest class would assert a promise nobody made; this says plainly that "
    "there is none yet."
)

#: A cell beginning with one of these is interpreted as a formula by Excel, Numbers and Sheets.
#: An actor display name is attacker-influenced text, so the export prefixes such a cell with an
#: apostrophe. ``access_routes.py``'s exporter does not, which is the defect this one fixes.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ─── Catalog models ──────────────────────────────────────────────────────────


class MetricFamilyBody(_CamelModel):
    """One metric family, and — the field that matters — the question it cannot answer."""

    family: str = Field(description="request, cache, origin, function, security or cost.")
    label: str = Field(description="Operator-facing family name.")
    answers: str = Field(description="What a chart in this family tells you.")
    does_not_answer: str = Field(
        description="What it does not, stated so a reader does not infer it."
    )


class MetricFamiliesResponse(_CamelModel):
    """The metric family catalog."""

    families: List[MetricFamilyBody] = Field(description="Every family, in request-path order.")


class ServiceBody(_CamelModel):
    """One billable service, and what makes its number go up."""

    service: str = Field(description="delivery, build, function, log or ai.")
    label: str = Field(description="Operator-facing service name.")
    unit: str = Field(description="The unit its quantity is counted in.")
    driver: str = Field(description="What drives the number, so a spike names where to look.")


class ServicesResponse(_CamelModel):
    """The billable service catalog."""

    services: List[ServiceBody] = Field(description="Every service §29.6 names.")
    metered: Literal[False] = Field(
        default=False, description="False. Nothing meters these services."
    )
    billable: Literal[False] = Field(
        default=False, description="False. A modelled cost is not a charge."
    )
    sentence: str = Field(default=_NO_METER_SENTENCE, description="What that means, in words.")


class ResidencyStageBody(_CamelModel):
    """One processing stage, and the gap its residency promise leaves."""

    stage: str = Field(description="One of the six stages along the request path.")
    label: str = Field(description="Operator-facing stage name.")
    covers: str = Field(description="What pinning this stage to a region actually guarantees.")
    default_uncovered: str = Field(
        description=(
            "The gap sentence used when an operator writes none. Required by §29.6: a claim with "
            "no stated gap is not a stronger promise, it is the same promise with the gap "
            "unwritten."
        )
    )


class ResidencyClassBody(_CamelModel):
    """One residency posture, in the edge surface's vocabulary."""

    key: str = Field(description="in-region-only, region-pinned or unrestricted.")
    description: str = Field(description="What choosing it actually promises.")


class ResidencyStagesResponse(_CamelModel):
    """The residency stage catalog, and the postures a stage may take."""

    stages: List[ResidencyStageBody] = Field(description="All six, in request-path order.")
    residency_classes: List[ResidencyClassBody] = Field(
        description="The three postures, most restrictive first."
    )


# ─── Honesty models ──────────────────────────────────────────────────────────


class EnforcementBody(_CamelModel):
    """Whether the recorded observability policy measures or acts on anything.

    ``enforced`` and ``observed`` are ``Literal[False]`` with defaults no handler assigns. That is
    the point: the response is structurally unable to claim a measurement, in the same way V190's
    CHECKs make the corresponding columns unable to hold one.
    """

    enforced: Literal[False] = Field(
        default=False, description="False. No collector is attached to this environment."
    )
    observed: Literal[False] = Field(
        default=False, description="False. Nothing sits in the request path to observe it."
    )
    sentence: str = Field(
        default=_NO_COLLECTOR_SENTENCE, description="What that means, in words."
    )


class InsightWarningBody(_CamelModel):
    """A concern that does not block the write."""

    code: str = Field(description="Named warning reason.")
    message: str = Field(description="Operator-facing sentence, rendered verbatim by the UI.")
    field: str = Field(default="", description="Which field the warning attaches to.")
    severity: Literal["warn", "block"] = Field(
        default="warn", description="warn never blocks; block is returned only on a 409."
    )


# ─── Resource models ─────────────────────────────────────────────────────────


class InsightPolicyBody(_CamelModel):
    """A lane's observability policy: what is collected, for how long, and how coarsely."""

    telemetry_enabled: bool = Field(
        default=False, description="Whether signals are collected on this lane at all."
    )
    metric_retention_days: int = Field(default=90, description="How long metric points are kept.")
    log_retention_days: int = Field(default=14, description="How long log lines are kept.")
    trace_retention_days: int = Field(default=7, description="How long traces are kept.")
    default_sample_rate: float = Field(default=0.05, description="Head sampling rate for traces.")
    max_tail_sample_rate: float = Field(
        default=0.01, description="Ceiling a live tail session may not exceed."
    )
    max_tail_events_per_sec: int = Field(
        default=100, description="Event-rate ceiling a live tail session may not exceed."
    )
    privacy_threshold: int = Field(
        default=10, description="Smallest population an aggregate may report."
    )
    retention_waiver_reason: Optional[str] = Field(
        default=None, description="Why retention sits below the floor, when it does."
    )
    edge_attached: Literal[False] = Field(
        default=False, description="False. No collector serves this lane."
    )
    edge_provider: Optional[str] = Field(default=None, description="Its name, or null.")


class ResidencyLaneBody(_CamelModel):
    """One residency stage, with what it covers and what it explicitly does not."""

    id: Optional[str] = Field(default=None, description="Row id, absent before it is written.")
    stage: str = Field(default="", description="One of the six stages.")
    label: str = Field(default="", description="Operator-facing stage name, from the catalog.")
    covers: str = Field(default="", description="What pinning this stage guarantees.")
    residency_class: str = Field(
        default="in-region-only", description="in-region-only, region-pinned or unrestricted."
    )
    regions: List[str] = Field(default_factory=list, description="Regions the stage is confined to.")
    uncovered_sentence: str = Field(
        default="", description="What this lane's promise does not cover. Never blank."
    )
    residency_waiver_reason: Optional[str] = Field(
        default=None, description="Why the stage is unrestricted, when it is."
    )
    enforced: Literal[False] = Field(
        default=False,
        description="False. A stage's placement is a declared intent, not an active control.",
    )
    updated_by: str = Field(default="", description="Who last changed it.")


class ExportBody(_CamelModel):
    """One OTLP export destination. A secret reference, never a header value."""

    id: Optional[str] = Field(default=None, description="Row id, absent before it is written.")
    label: str = Field(default="", description="Operator-facing name, unique per lane.")
    endpoint: str = Field(default="", description="The collector endpoint. HTTPS by refusal.")
    protocol: str = Field(default="http/protobuf", description="grpc or http/protobuf.")
    signals: List[str] = Field(
        default_factory=list, description="Signal classes this destination receives."
    )
    header_secret_ref: Optional[str] = Field(
        default=None, description="Name of the secret holding the authorization header. Never a value."
    )
    enabled: bool = Field(default=False, description="Whether the destination is active.")
    last_delivery_state: str = Field(
        default="never-attempted", description="never-attempted, pending, failed or delivered."
    )
    last_delivery_at: Optional[str] = Field(default=None, description="When delivery last ran.")
    last_failure_reason: Optional[str] = Field(default=None, description="Why it last failed.")
    edge_attached: Literal[False] = Field(
        default=False, description="False. Nothing collects, so nothing was ever shipped."
    )
    updated_by: str = Field(default="", description="Who last changed it.")


class BudgetBody(_CamelModel):
    """One spend budget and its alert thresholds."""

    id: Optional[str] = Field(default=None, description="Row id, absent before it is written.")
    label: str = Field(default="", description="Operator-facing name, unique per lane.")
    service: Optional[str] = Field(
        default=None, description="Service the budget is scoped to, or null for every service."
    )
    period: str = Field(default="monthly", description="daily, weekly or monthly.")
    amount: float = Field(default=0.0, description="Budget amount for the period.")
    currency: str = Field(default="USD", description="ISO 4217 code.")
    alert_thresholds: List[float] = Field(
        default_factory=list, description="Fractions of the budget at which an alert fires."
    )
    notify_channel_ref: Optional[str] = Field(
        default=None, description="Reference to the notification channel, not its address."
    )
    enabled: bool = Field(default=True, description="Whether the budget is active.")
    updated_by: str = Field(default="", description="Who last changed it.")


class SyntheticCheckBody(_CamelModel):
    """One synthetic probe definition."""

    id: Optional[str] = Field(default=None, description="Row id, absent before it is written.")
    label: str = Field(default="", description="Operator-facing name, unique per lane.")
    target_path: str = Field(default="/", description="The path the probe requests.")
    method: str = Field(default="GET", description="HTTP method.")
    regions: List[str] = Field(default_factory=list, description="Regions the probe runs from.")
    interval_seconds: int = Field(default=300, description="How often it would run.")
    expected_status: int = Field(default=200, description="The status it treats as healthy.")
    latency_budget_ms: int = Field(default=1000, description="Above this it reports degraded.")
    enabled: bool = Field(default=False, description="Whether the probe is active.")
    updated_by: str = Field(default="", description="Who last changed it.")


class TailSessionBody(_CamelModel):
    """One live tail session, recorded whether or not anything ever streamed."""

    id: Optional[str] = Field(default=None, description="Session id.")
    sample_rate: float = Field(default=0.0, description="Requested sampling rate.")
    max_events_per_sec: int = Field(default=0, description="Requested event-rate ceiling.")
    redaction_allowlist: List[str] = Field(
        default_factory=list,
        description=(
            "The allowlist actually in force, stored on the row so a capture reviewed a year "
            "later can be checked against the redaction it ran under."
        ),
    )
    filter_expression: Optional[str] = Field(default=None, description="Server-side filter, or null.")
    stream_state: str = Field(default="requested", description="closed, requested, attached or refused.")
    started_at: Optional[str] = Field(default=None, description="When the session was opened.")
    ended_at: Optional[str] = Field(default=None, description="When it was closed, or null.")
    events_delivered: Literal[0] = Field(
        default=0,
        description="Zero. Nothing is in the request path, so no session can have delivered an event.",
    )
    opened_by: str = Field(default="", description="Who opened it.")
    reason: str = Field(default="", description="Why it was opened. Refused when blank.")
    edge_attached: Literal[False] = Field(
        default=False, description="False. A session can be requested but never attached."
    )
    retain_until: Optional[str] = Field(default=None, description="When the capture is purged.")


# ─── Lane model ──────────────────────────────────────────────────────────────


class InsightsLaneResponse(_CamelModel):
    """A lane's complete observability configuration, and what it actually measures."""

    environment_id: str = Field(description="The lane.")
    policy: InsightPolicyBody = Field(description="What is collected, for how long, how coarsely.")
    residency_lanes: List[ResidencyLaneBody] = Field(
        description="All six stages, in request-path order. Five stages is not a promise."
    )
    residency_complete: bool = Field(
        description="Whether all six stages are stated. False means the promise is incomplete."
    )
    effective_residency_class: Optional[str] = Field(
        default=None,
        description=(
            "The single promise the lane actually makes, which is the weakest any stage makes. "
            "Null when the six stages are not all stated, because an incomplete set has no "
            "effective promise to report."
        ),
    )
    exports: List[ExportBody] = Field(description="OTLP destinations, by label.")
    budgets: List[BudgetBody] = Field(description="Spend budgets, by label.")
    synthetic_checks: List[SyntheticCheckBody] = Field(description="Synthetic probes, by label.")
    policy_version: int = Field(description="Optimistic-concurrency token.")
    signals_digest: str = Field(description="Determinism receipt over the whole configuration.")
    enforcement: EnforcementBody = Field(
        default_factory=EnforcementBody, description="Whether the policy measures anything."
    )
    warnings: List[InsightWarningBody] = Field(
        default_factory=list, description="Non-blocking concerns about the configuration."
    )
    updated_at: Optional[str] = Field(default=None, description="When the policy last changed.")
    updated_by: Optional[str] = Field(default=None, description="Who changed it.")


# ─── Write request and response models ───────────────────────────────────────


class SetInsightPolicyRequest(_CamelModel):
    """Change what a lane collects, for how long, and how coarsely it reports."""

    telemetry_enabled: bool = Field(default=False, description="Whether signals are collected.")
    metric_retention_days: int = Field(default=90, gt=0, description="Metric retention, in days.")
    log_retention_days: int = Field(default=14, gt=0, description="Log retention, in days.")
    trace_retention_days: int = Field(default=7, gt=0, description="Trace retention, in days.")
    default_sample_rate: float = Field(default=0.05, ge=0, le=1, description="Head sampling rate.")
    max_tail_sample_rate: float = Field(default=0.01, ge=0, le=1, description="Tail rate ceiling.")
    max_tail_events_per_sec: int = Field(default=100, gt=0, description="Tail event-rate ceiling.")
    privacy_threshold: int = Field(default=10, ge=1, description="Smallest reportable population.")
    retention_waiver_reason: Optional[str] = Field(
        default=None, description="Required when log retention falls below the floor."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class SetInsightPolicyResponse(_CamelModel):
    """The outcome of an observability policy change."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    policy: InsightPolicyBody = Field(description="The policy as it now reads.")
    policy_version: int = Field(description="The version after the change.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[InsightWarningBody] = Field(default_factory=list)


class WriteResidencyLaneRequest(_CamelModel):
    """State where one processing stage happens, and what that promise does not cover."""

    residency_class: str = Field(
        default="in-region-only", description="in-region-only, region-pinned or unrestricted."
    )
    regions: List[str] = Field(
        default_factory=list, description="Regions the stage is confined to. Required unless unrestricted."
    )
    uncovered_sentence: str = Field(
        default="",
        description="What this promise does not cover. Falls back to the stage's catalog sentence.",
    )
    residency_waiver_reason: Optional[str] = Field(
        default=None, description="Required when the stage is unrestricted."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class WriteResidencyLaneResponse(_CamelModel):
    """The outcome of a residency stage write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    lane: Optional[ResidencyLaneBody] = Field(default=None, description="The stage as written.")
    effective_residency_class: Optional[str] = Field(
        default=None, description="The promise the lane as a whole now makes, when all six are stated."
    )
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[InsightWarningBody] = Field(default_factory=list)


class WriteExportRequest(_CamelModel):
    """Create or replace an OTLP export destination.

    ``extra="allow"`` is deliberate and is the only place on this surface where it appears. There
    is nowhere in V190 to store a header value, and normalization drops one silently — so an
    operator who pasted a bearer token into a form would see it accepted and reasonably believe it
    had been stored and used. Accepting the field and refusing it by name is the honest behaviour,
    and :func:`app.slate_insights.validate_export` is what refuses it.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

    label: str = Field(description="Operator-facing name, unique per lane.")
    endpoint: str = Field(description="The collector endpoint. Plaintext HTTP is refused.")
    protocol: str = Field(default="http/protobuf", description="grpc or http/protobuf.")
    signals: List[str] = Field(
        default_factory=list, description="metrics, logs and/or traces. At least one."
    )
    header_secret_ref: Optional[str] = Field(
        default=None, description="Name of the secret holding the header. A reference, never a value."
    )
    enabled: bool = Field(default=False, description="Whether the destination is active.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class WriteExportResponse(_CamelModel):
    """The outcome of an export destination write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    export: Optional[ExportBody] = Field(default=None, description="The destination as written.")
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[InsightWarningBody] = Field(default_factory=list)


class WriteBudgetRequest(_CamelModel):
    """Create or replace a spend budget."""

    label: str = Field(description="Operator-facing name, unique per lane.")
    service: Optional[str] = Field(
        default=None, description="Service to scope to, or null for every service."
    )
    period: str = Field(default="monthly", description="daily, weekly or monthly.")
    amount: float = Field(default=0.0, description="Budget amount. Must be positive.")
    currency: str = Field(default="USD", description="ISO 4217 code.")
    alert_thresholds: List[float] = Field(
        default_factory=list, description="Fractions at which an alert fires. At least one."
    )
    notify_channel_ref: Optional[str] = Field(
        default=None, description="Reference to the notification channel, not its address."
    )
    enabled: bool = Field(default=True, description="Whether the budget is active.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class WriteBudgetResponse(_CamelModel):
    """The outcome of a budget write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    budget: Optional[BudgetBody] = Field(default=None, description="The budget as written.")
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[InsightWarningBody] = Field(default_factory=list)


class WriteCheckRequest(_CamelModel):
    """Create or replace a synthetic check."""

    label: str = Field(description="Operator-facing name, unique per lane.")
    target_path: str = Field(default="/", description="The path the probe requests.")
    method: str = Field(default="GET", description="HTTP method.")
    regions: List[str] = Field(default_factory=list, description="Regions the probe runs from.")
    interval_seconds: int = Field(default=300, ge=60, description="How often it would run.")
    expected_status: int = Field(default=200, description="The status it treats as healthy.")
    latency_budget_ms: int = Field(default=1000, gt=0, description="Above this it is degraded.")
    enabled: bool = Field(default=False, description="Whether the probe is active.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class WriteCheckResponse(_CamelModel):
    """The outcome of a synthetic check write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    check: Optional[SyntheticCheckBody] = Field(default=None, description="The check as written.")
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[InsightWarningBody] = Field(default_factory=list)


class DeleteInsightResourceResponse(_CamelModel):
    """The outcome of removing an export destination, a budget or a synthetic check."""

    deleted: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    policy_version: int = Field(description="The version after the write.")


class OpenTailRequest(_CamelModel):
    """Open a live tail session.

    ``expectedPolicyVersion`` is optional here and required on every configuration write, because
    opening a tail changes no policy. Consuming a version to read a stream would invalidate every
    other operator's open editor during exactly the incident that made somebody open it.
    """

    sample_rate: float = Field(default=0.001, gt=0, le=1, description="Requested sampling rate.")
    max_events_per_sec: int = Field(default=10, gt=0, description="Requested event-rate ceiling.")
    redaction_allowlist: List[str] = Field(
        default_factory=list,
        description="Fields permitted through. Anything outside the allowlist is refused.",
    )
    filter_expression: Optional[str] = Field(default=None, description="Server-side filter, or null.")
    reason: str = Field(default="", description="Why the tail is being opened. Refused when blank.")
    expected_policy_version: Optional[int] = Field(
        default=None, description="Not consumed: opening a tail changes no policy."
    )
    dry_run: bool = Field(default=False, description="Run every gate and record nothing.")


class OpenTailResponse(_CamelModel):
    """The outcome of opening a live tail session."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    session: Optional[TailSessionBody] = Field(default=None, description="The session as recorded.")
    policy_version: int = Field(description="The lane's policy version, unchanged by this call.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[InsightWarningBody] = Field(default_factory=list)


class CloseTailResponse(_CamelModel):
    """The outcome of closing a live tail session."""

    closed: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    session: Optional[TailSessionBody] = Field(default=None, description="The session as closed.")


class TailSessionsResponse(_CamelModel):
    """A lane's recent live tail sessions."""

    sessions: List[TailSessionBody] = Field(description="Newest first.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)


class AcknowledgeAlertRequest(_CamelModel):
    """Acknowledge one budget alert."""

    note: Optional[str] = Field(default=None, description="Optional note, recorded in audit.")
    expected_policy_version: Optional[int] = Field(
        default=None, description="Not consumed: acknowledging an alert changes no policy."
    )
    dry_run: bool = Field(default=False, description="Validate without writing.")


# ─── Signal models ───────────────────────────────────────────────────────────


class MetricPointBody(_CamelModel):
    """One correlated metric point, carrying what it is worth.

    ``basis`` and ``observed`` are literal defaults no handler assigns.
    """

    release_id: Optional[str] = Field(default=None, description="Release the point is keyed to.")
    region: str = Field(default="auto", description="Region the point is keyed to.")
    family: str = Field(default="", description="Metric family.")
    metric_key: str = Field(default="", description="The series within the family.")
    window_start: Optional[str] = Field(default=None, description="Inclusive start of the window.")
    window_end: Optional[str] = Field(default=None, description="Exclusive end of the window.")
    value: Optional[float] = Field(default=None, description="The value, or null when suppressed.")
    unit: str = Field(default="count", description="Unit of the value.")
    sample_count: int = Field(default=0, description="Population behind the point.")
    suppressed: bool = Field(
        default=False, description="Whether the value was withheld for falling below the threshold."
    )
    basis: Literal["modelled"] = Field(
        default="modelled",
        description=(
            "Always modelled. When a collector lands, 'edge-observed' becomes a second value of "
            "this field rather than a change of meaning for the first."
        ),
    )
    observed: Literal[False] = Field(
        default=False, description="False: nothing in the request path reported this point."
    )


class DroppedPointBody(_CamelModel):
    """One point that could not be correlated, and why it was not emitted."""

    id: str = Field(description="The row that was dropped.")
    reason: str = Field(description="Why it could not be keyed, in a sentence.")


class MetricsResponse(_CamelModel):
    """A lane's correlated metric points, and the ones that could not be keyed.

    Drops are reported rather than silently discarded: a chart with a hole in it and no explanation
    teaches operators the data is unreliable, which is more expensive than the missing point.
    """

    points: List[MetricPointBody] = Field(description="Correlated points, by family and window.")
    dropped: List[DroppedPointBody] = Field(
        default_factory=list, description="Points that could not be keyed, and why."
    )
    suppressed_count: int = Field(default=0, description="How many points were withheld for privacy.")
    privacy_threshold: int = Field(default=10, description="The threshold they were withheld against.")
    warnings: List[InsightWarningBody] = Field(default_factory=list)
    basis: Literal["policy-modelled"] = Field(
        default="policy-modelled", description="This series is modelled from policy, not measured."
    )
    observed: Literal[False] = Field(
        default=False, description="False: no collector reported any of this."
    )
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    sentence: str = Field(default=_NO_OBSERVATION_SENTENCE, description="What that means, in words.")


class LogBody(_CamelModel):
    """One structured log line, with its redacted evidence."""

    id: str = Field(description="Log row id.")
    at: Optional[str] = Field(default=None, description="When the line was recorded.")
    level: str = Field(default="info", description="debug, info, warn or error.")
    source: str = Field(default="", description="The emitting subsystem.")
    message: str = Field(default="", description="The log message.")
    release_id: Optional[str] = Field(default=None, description="Release the line is keyed to.")
    region: str = Field(default="auto", description="Region the line is keyed to.")
    trace_ref: Optional[str] = Field(default=None, description="Trace the line belongs to.")
    evidence: Dict[str, str] = Field(
        default_factory=dict, description="Redacted request evidence, allowlisted by the store."
    )
    basis: Literal["modelled"] = Field(default="modelled", description="Always modelled.")
    observed: Literal[False] = Field(default=False, description="False: nothing observed this line.")
    retain_until: Optional[str] = Field(default=None, description="When the evidence is purged.")


class LogsResponse(_CamelModel):
    """A lane's structured logs."""

    logs: List[LogBody] = Field(description="Newest first.")
    observed: Literal[False] = Field(
        default=False, description="False: none of these were observed in a request path."
    )
    sentence: str = Field(default=_NO_OBSERVATION_SENTENCE, description="What that means.")


class TraceBody(_CamelModel):
    """One trace header."""

    id: str = Field(description="Trace row id.")
    trace_id: str = Field(default="", description="The W3C trace id.")
    started_at: Optional[str] = Field(default=None, description="When the traced request began.")
    duration_ms: int = Field(default=0, description="Total duration.")
    route: str = Field(default="", description="Route pattern matched.")
    method: str = Field(default="GET", description="HTTP method.")
    status_code: Optional[int] = Field(default=None, description="Response status, when it completed.")
    sample_rate: float = Field(default=1.0, description="Head sampling rate that kept this trace.")
    release_id: Optional[str] = Field(default=None, description="Release the trace is keyed to.")
    region: str = Field(default="auto", description="Region that handled it.")
    basis: Literal["modelled"] = Field(default="modelled", description="Always modelled.")
    observed: Literal[False] = Field(default=False, description="False: nothing traced this request.")
    retain_until: Optional[str] = Field(default=None, description="When the trace is purged.")


class TracesResponse(_CamelModel):
    """A lane's traces."""

    traces: List[TraceBody] = Field(description="Newest first.")
    observed: Literal[False] = Field(default=False, description="False: nothing observed these.")
    sentence: str = Field(default=_NO_OBSERVATION_SENTENCE, description="What that means.")


class SpanBody(_CamelModel):
    """One span within a trace, placed by its offset from the trace start."""

    id: str = Field(description="Span row id.")
    span_id: str = Field(default="", description="The W3C span id.")
    parent_span_ref: Optional[str] = Field(default=None, description="Parent span id, or null.")
    name: str = Field(default="", description="Span name.")
    component: str = Field(default="", description="request, cache, origin, function or security.")
    start_offset_ms: int = Field(default=0, description="Offset from the trace start.")
    duration_ms: int = Field(default=0, description="How long the span took.")
    status: str = Field(default="ok", description="ok or error.")
    attributes: Dict[str, str] = Field(
        default_factory=dict, description="Redacted span attributes, allowlisted by the store."
    )


class TraceDetailResponse(_CamelModel):
    """One trace and its spans, ordered as a waterfall."""

    trace: TraceBody = Field(description="The trace header.")
    spans: List[SpanBody] = Field(description="Its spans, by start offset.")
    observed: Literal[False] = Field(default=False, description="False: nothing observed this.")
    sentence: str = Field(default=_NO_OBSERVATION_SENTENCE, description="What that means.")


class UsageRecordBody(_CamelModel):
    """One daily usage record.

    ``basis``, ``metered`` and ``billable`` are literal defaults no handler assigns. This is the
    single most consequential set of literals on the surface.
    """

    id: str = Field(description="Usage row id.")
    usage_date: Optional[str] = Field(default=None, description="The day this record covers.")
    service: str = Field(default="", description="delivery, build, function, log or ai.")
    quantity: float = Field(default=0.0, description="Quantity consumed.")
    unit: str = Field(default="count", description="Unit of the quantity.")
    amount: float = Field(default=0.0, description="Spend for the day.")
    currency: str = Field(default="USD", description="ISO 4217 code.")
    included_quantity: float = Field(default=0.0, description="How much fell inside the quota.")
    overage_quantity: float = Field(default=0.0, description="How much exceeded it.")
    cache_savings_amount: Optional[float] = Field(
        default=None, description="Measured savings, or null. Null unless metered, by refusal."
    )
    forecast_amount: Optional[float] = Field(
        default=None, description="Projection, carried separately so it is never summed into a total."
    )
    release_id: Optional[str] = Field(default=None, description="Release the usage is keyed to.")
    region: str = Field(default="auto", description="Region the usage is keyed to.")
    basis: Literal["modelled"] = Field(default="modelled", description="Always modelled.")
    metered: Literal[False] = Field(default=False, description="False: nothing meters this lane.")
    billable: Literal[False] = Field(
        default=False, description="False: a modelled cost is not a charge."
    )


class UsageRollupBody(_CamelModel):
    """One service's usage rolled up over the period."""

    service: str = Field(description="delivery, build, function, log or ai.")
    label: str = Field(default="", description="Operator-facing service name.")
    quantity: float = Field(default=0.0, description="Total quantity consumed.")
    unit: str = Field(default="count", description="Unit of the quantity.")
    amount: float = Field(default=0.0, description="Total spend.")
    currency: str = Field(default="USD", description="ISO 4217 code.")
    included_quantity: float = Field(default=0.0, description="How much fell inside the quota.")
    overage_quantity: float = Field(default=0.0, description="How much exceeded it.")
    cache_savings_amount: Optional[float] = Field(
        default=None, description="Measured savings, or null. Null unless every row was metered."
    )
    forecast_amount: Optional[float] = Field(
        default=None, description="Projected spend for the remainder, never summed into amount."
    )
    days: int = Field(default=0, description="How many daily records contributed.")
    basis: Literal["modelled"] = Field(default="modelled", description="Always modelled.")
    metered: Literal[False] = Field(default=False, description="False: nothing meters this lane.")
    billable: Literal[False] = Field(
        default=False, description="False: a modelled cost is not a charge."
    )


class UsageResponse(_CamelModel):
    """A lane's daily usage, its per-service rollups and its forecast."""

    records: List[UsageRecordBody] = Field(description="Daily records, oldest first.")
    rollups: List[UsageRollupBody] = Field(description="One per service present in the window.")
    forecast_amount: Optional[float] = Field(
        default=None, description="Projected additional spend for the remainder of the period."
    )
    forecast_days_remaining: int = Field(
        default=0, description="Days the projection covers. Zero means no projection was asked for."
    )
    currency: str = Field(default="USD", description="ISO 4217 code shared by every record.")
    warnings: List[InsightWarningBody] = Field(default_factory=list)
    basis: Literal["modelled"] = Field(default="modelled", description="Always modelled.")
    metered: Literal[False] = Field(default=False, description="False: nothing meters this lane.")
    billable: Literal[False] = Field(
        default=False, description="False: a modelled cost is not a charge."
    )
    sentence: str = Field(default=_NO_METER_SENTENCE, description="What that means, in words.")
    forecast_sentence: str = Field(
        default=_FORECAST_SENTENCE, description="Why the forecast is carried separately."
    )


class BudgetAlertBody(_CamelModel):
    """One threshold crossing, with the arithmetic behind it."""

    id: str = Field(description="Alert row id.")
    budget_id: str = Field(default="", description="The budget that fired.")
    at: Optional[str] = Field(default=None, description="When it fired.")
    threshold: float = Field(default=0.0, description="The fraction crossed.")
    observed_amount: float = Field(default=0.0, description="Spend when it fired.")
    budget_amount: float = Field(
        default=0.0, description="The budget it was compared against, captured at fire time."
    )
    currency: str = Field(default="USD", description="ISO 4217 code, the same for both amounts.")
    period_start: Optional[str] = Field(default=None, description="Inclusive start of the period.")
    period_end: Optional[str] = Field(default=None, description="Inclusive end of the period.")
    delivery_state: str = Field(
        default="not-dispatched", description="not-dispatched, pending, failed or delivered."
    )
    acknowledged_at: Optional[str] = Field(default=None, description="When it was acknowledged.")
    acknowledged_by: Optional[str] = Field(default=None, description="Who acknowledged it.")
    basis: Literal["modelled"] = Field(
        default="modelled",
        description="Always modelled. 'You have exceeded your budget' reads as a statement of fact.",
    )
    dispatched: Literal[False] = Field(
        default=False, description="False: nothing dispatches, so no alert reached anybody."
    )


class BudgetAlertsResponse(_CamelModel):
    """A lane's budget alerts."""

    alerts: List[BudgetAlertBody] = Field(description="Newest first.")
    basis: Literal["modelled"] = Field(default="modelled", description="Always modelled.")
    dispatched: Literal[False] = Field(default=False, description="False: nothing dispatches.")
    sentence: str = Field(default=_NO_METER_SENTENCE, description="What that means, in words.")


class AcknowledgeAlertResponse(_CamelModel):
    """The outcome of acknowledging a budget alert."""

    acknowledged: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    alert: Optional[BudgetAlertBody] = Field(default=None, description="The alert as acknowledged.")


class SyntheticResultBody(_CamelModel):
    """One synthetic probe result, with its post-promotion annotation when it has one."""

    id: str = Field(description="Result row id.")
    check_id: str = Field(default="", description="The probe that produced it.")
    at: Optional[str] = Field(default=None, description="When the probe ran.")
    outcome: str = Field(
        default="not-run",
        description=(
            "healthy, degraded, failed or not-run. not-run is separate from failed because a "
            "scheduler outage is not a service outage."
        ),
    )
    region: str = Field(default="auto", description="Region the probe ran from.")
    status_code: Optional[int] = Field(default=None, description="Status received, or null.")
    latency_ms: Optional[int] = Field(default=None, description="Observed latency, or null.")
    release_id: Optional[str] = Field(default=None, description="Release active at the time.")
    annotation_kind: Optional[str] = Field(
        default=None, description="post-promotion-regression or post-promotion-recovery, or null."
    )
    annotation_note: Optional[str] = Field(default=None, description="What the annotation observed.")
    basis: Literal["modelled"] = Field(default="modelled", description="Always modelled.")
    observed: Literal[False] = Field(default=False, description="False: no probe actually ran.")


class SyntheticResultsResponse(_CamelModel):
    """A lane's synthetic results."""

    results: List[SyntheticResultBody] = Field(description="Newest first.")
    observed: Literal[False] = Field(default=False, description="False: no probe actually ran.")
    sentence: str = Field(default=_NO_OBSERVATION_SENTENCE, description="What that means.")


class AuditEntryBody(_CamelModel):
    """One append-only audit entry."""

    id: str = Field(description="Entry id.")
    at: Optional[str] = Field(default=None, description="When the event happened.")
    actor_name: str = Field(default="", description="Who acted.")
    actor_kind: str = Field(default="", description="user or automation.")
    subject_kind: str = Field(default="", description="What the entry is about.")
    subject_id: Optional[str] = Field(default=None, description="Id of the subject.")
    summary: str = Field(default="", description="What happened.")
    detail: Dict[str, Any] = Field(default_factory=dict, description="Structured detail.")


class AuditResponse(_CamelModel):
    """A lane's observability audit trail.

    The audit is the one table on this surface with no retention: the record that a live tail was
    opened outlives the capture it took, which is the whole point of separating the two.
    """

    entries: List[AuditEntryBody] = Field(description="Most recent first.")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _require_environment(tenant_id: str, environment_id: str) -> Dict[str, Any]:
    """Load an environment or answer 404.

    Args:
        tenant_id: Caller's tenant.
        environment_id: The lane.

    Returns:
        The environment row.

    Raises:
        HTTPException: 404 when the lane does not exist in this tenant. Deliberately not 403: a
            cross-tenant probe must not be able to confirm the lane exists, and on a surface whose
            live tail puts reader traffic on screen that probe is the reconnaissance step.
    """
    environment = get_environment(db, tenant_id=tenant_id, environment_id=environment_id)
    if not environment:
        raise HTTPException(
            status_code=404,
            detail={"code": "environment_not_found", "message": "Environment not found."},
        )
    return environment


def _refusal_http(error: SlateInsightRefusedError) -> HTTPException:
    """Map an observability refusal to a 409 carrying its named reason and sentence.

    The sentence is the domain module's, character for character. Restating it here would produce
    two copies that eventually disagreed, and the copy on screen would be the one an operator
    trusted.
    """
    return HTTPException(
        status_code=409,
        detail={
            "code": error.refusal.reason,
            "message": error.refusal.sentence,
            "reason": error.refusal.reason,
        },
    )


def _conflict_http(error: SlateInsightPolicyConflictError) -> HTTPException:
    """Map a lost update to the ``policy-version-conflict`` refusal."""
    refusal = InsightRefusal.of("policy-version-conflict")
    return HTTPException(
        status_code=409,
        detail={
            "code": refusal.reason,
            "message": refusal.sentence,
            "reason": refusal.reason,
            "actualPolicyVersion": error.actual_policy_version,
        },
    )


def _not_found_http(error: SlateInsightStoreError) -> HTTPException:
    """Map a missing row to a 404 carrying the store's machine-readable code."""
    return HTTPException(status_code=404, detail={"code": error.code, "message": str(error)})


def _actor(auth_data: Mapping[str, Any]) -> Tuple[Optional[str], str]:
    """Resolve the acting user's id and display name.

    Args:
        auth_data: The auth dict from the dependency.

    Returns:
        The user id, when a person acted, and a display name that is never empty — audit rows
        outlive the accounts that wrote them.
    """
    return (
        get_authenticated_user_id(auth_data),
        str(auth_data.get("email") or auth_data.get("name") or "Unknown"),
    )


def _actor_key(auth_data: Mapping[str, Any]) -> str:
    """The immutable identity written beside every actor name.

    V190's actor columns are ``ON DELETE SET NULL``, so a record whose only identity was the user
    id would become an anonymous row when somebody is offboarded — and "who opened a live tail on
    production" is precisely the question asked long after the person has left.

    Args:
        auth_data: The auth dict from the dependency.

    Returns:
        A stable identity string, preferring the user id and falling back to the email.
    """
    return str(get_authenticated_user_id(auth_data) or auth_data.get("email") or "unknown")


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp or date as ISO-8601, tolerating a string that already is one."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _float(value: Any, fallback: float = 0.0) -> float:
    """Coerce a database numeric to a float, falling back on anything unusable."""
    if isinstance(value, bool) or value is None:
        return fallback
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return fallback


def _opt_float(value: Any) -> Optional[float]:
    """Coerce a nullable database numeric to a float or None.

    None rather than zero for an absent measurement: a zero here would be a measurement, and the
    absence of one is the truth.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _int(value: Any, fallback: int = 0) -> int:
    """Coerce a database integer to an int, falling back on anything unusable."""
    if isinstance(value, bool) or value is None:
        return fallback
    if isinstance(value, (int, float, Decimal)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


def _plain(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a row with its ``Decimal`` columns as floats.

    :mod:`app.slate_insights` coerces with ``isinstance(value, (int, float))``, and psycopg2 hands
    back ``NUMERIC`` as ``Decimal`` — which is neither. Converting at the boundary rather than
    widening the pure module keeps that module free of a database detail, and stops a budget amount
    silently normalizing to zero on its way to the digest.
    """
    return {
        key: (float(value) if isinstance(value, Decimal) else value) for key, value in row.items()
    }


def _warning_bodies(warnings: Any) -> List[InsightWarningBody]:
    """Map domain warnings onto their wire model."""
    bodies: List[InsightWarningBody] = []
    for warning in warnings:
        if isinstance(warning, Mapping):
            bodies.append(
                InsightWarningBody(
                    code=str(warning.get("code") or ""),
                    message=str(warning.get("message") or ""),
                    field=str(warning.get("field") or ""),
                )
            )
        else:
            bodies.append(
                InsightWarningBody(
                    code=warning.code, message=warning.message, field=warning.field or ""
                )
            )
    return bodies


def _csv_cell(value: Any) -> str:
    """Neutralize a CSV cell that a spreadsheet would evaluate as a formula.

    An actor display name, an audit summary and a budget label are all attacker-influenced text,
    and a cell beginning ``=``, ``+``, ``-``, ``@``, a tab or a carriage return is executed by
    Excel, Numbers and Sheets when the export is opened. Prefixing with an apostrophe makes the
    cell literal. ``access_routes.py``'s exporter does not do this; this one does, and the
    difference is whether reading cost evidence can run code.

    Args:
        value: The cell value.

    Returns:
        The value as text, apostrophe-prefixed when it would otherwise be interpreted.
    """
    text = "" if value is None else str(value)
    if text[:1] in _CSV_INJECTION_PREFIXES:
        return "'" + text
    return text


def _stage_definition(stage: str) -> Optional[Any]:
    """Find one stage's catalog entry, or None when the id is not a stage."""
    for definition in RESIDENCY_STAGE_CATALOG:
        if definition.stage == stage:
            return definition
    return None


def _default_lanes() -> List[Dict[str, Any]]:
    """The six residency lanes a never-configured environment is created with.

    Every stage gets its catalog gap sentence and an explicit statement that nothing has been
    promised for it yet. See :data:`_UNCONFIGURED_LANE_REASON` for why the default is the weakest
    class rather than the strictest: on this surface a residency class is a claim, and a claim
    nobody made is the one that ends up quoted to a regulator.
    """
    return [
        normalize_residency_lane(
            {
                "stage": definition.stage,
                "residency_class": "unrestricted",
                "regions": [],
                "uncovered_sentence": definition.default_uncovered,
                "residency_waiver_reason": _UNCONFIGURED_LANE_REASON,
            }
        )
        for definition in RESIDENCY_STAGE_CATALOG
    ]


def _policy_for(
    tenant_id: str, environment: Mapping[str, Any], auth_data: Mapping[str, Any]
) -> Dict[str, Any]:
    """Load or create the lane's observability policy.

    Creating on read rather than requiring an explicit enable matches the cache, security and
    function planes: V190's defaults are the safe posture, so a lane that has never been configured
    reads as configured-safely rather than as an error.
    """
    actor_id, actor_name = _actor(auth_data)
    return ensure_policy(
        db,
        tenant_id=tenant_id,
        site_id=str(environment["site_id"]),
        environment_id=str(environment["id"]),
        actor_id=actor_id,
        actor_name=actor_name,
        actor_key=_actor_key(auth_data),
    )


def _lanes_for(
    tenant_id: str, environment_id: str, auth_data: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """Load the lane's six residency stages, creating any that are absent."""
    actor_id, actor_name = _actor(auth_data)
    return ensure_residency_lanes(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        defaults=_default_lanes(),
        actor_id=actor_id,
        actor_name=actor_name,
        actor_key=_actor_key(auth_data),
    )


def _coverage(
    lanes: Sequence[Mapping[str, Any]],
) -> Tuple[bool, Optional[str], List[InsightWarningBody]]:
    """Summarize a lane set as the single promise it actually makes.

    :func:`app.slate_insights.residency_coverage` refuses an incomplete set, which is right on a
    write and wrong on a read: an operator opening a half-created lane must be shown the gap, not
    handed a 409 they cannot act on. So an incomplete set is reported as incomplete with no
    effective class, and a complete one is summarized as the weakest promise any stage makes.

    Args:
        lanes: The residency rows, already database-plain.

    Returns:
        Whether all six stages are stated, the effective class when they are, and any warnings.
    """
    normalized = [normalize_residency_lane(_plain(lane)) for lane in lanes]
    if {lane["stage"] for lane in normalized} != set(RESIDENCY_STAGES):
        return False, None, []
    effective, warnings = residency_coverage(normalized)
    return True, effective, _warning_bodies(warnings)


def _audit(
    *,
    tenant_id: str,
    environment_id: str,
    actor: Tuple[Optional[str], str],
    actor_key: str,
    subject_kind: str,
    subject_id: Optional[str],
    summary: str,
    detail: Optional[Mapping[str, Any]] = None,
) -> None:
    """Append one audit entry, with the actor already resolved."""
    actor_id, actor_name = actor
    append_audit(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_key=actor_key,
        actor_kind="user",
        subject_kind=subject_kind,
        subject_id=subject_id,
        summary=summary,
        detail=dict(detail or {}),
    )


def _bump(environment_id: str, expected_policy_version: int) -> int:
    """Consume the caller's expected policy version, refusing a stale one.

    Every configuration write on this lane goes through here, so two operators changing retention
    or a budget during the same incident — the normal case, not the exotic one — cannot silently
    overwrite each other.

    Args:
        environment_id: The lane.
        expected_policy_version: The version the caller read.

    Returns:
        The new policy version.

    Raises:
        HTTPException: 409 carrying the ``policy-version-conflict`` sentence.
    """
    try:
        return bump_policy_version(
            db, environment_id=environment_id, expected_policy_version=expected_policy_version
        )
    except SlateInsightPolicyConflictError as exc:
        raise _conflict_http(exc) from exc


# ─── Row mappers ─────────────────────────────────────────────────────────────


def _policy_body(row: Mapping[str, Any]) -> InsightPolicyBody:
    """Map an observability policy row onto its wire model."""
    return InsightPolicyBody(
        telemetry_enabled=bool(row.get("telemetry_enabled")),
        metric_retention_days=_int(row.get("metric_retention_days"), 90),
        log_retention_days=_int(row.get("log_retention_days"), 14),
        trace_retention_days=_int(row.get("trace_retention_days"), 7),
        default_sample_rate=_float(row.get("default_sample_rate"), 0.05),
        max_tail_sample_rate=_float(row.get("max_tail_sample_rate"), 0.01),
        max_tail_events_per_sec=_int(row.get("max_tail_events_per_sec"), 100),
        privacy_threshold=_int(row.get("privacy_threshold"), 10),
        retention_waiver_reason=row.get("retention_waiver_reason"),
        edge_provider=row.get("edge_provider"),
    )


def _lane_body(row: Mapping[str, Any]) -> ResidencyLaneBody:
    """Map a residency lane row onto its wire model, with its catalog prose attached."""
    stage = str(row.get("stage") or "")
    definition = _stage_definition(stage)
    return ResidencyLaneBody(
        id=str(row["id"]) if row.get("id") else None,
        stage=stage,
        label=definition.label if definition else stage,
        covers=definition.covers if definition else "",
        residency_class=str(row.get("residency_class") or "in-region-only"),
        regions=[str(region) for region in (row.get("regions") or [])],
        uncovered_sentence=str(row.get("uncovered_sentence") or ""),
        residency_waiver_reason=row.get("residency_waiver_reason"),
        updated_by=str(row.get("updated_by_actor_name") or ""),
    )


def _export_body(row: Mapping[str, Any]) -> ExportBody:
    """Map an OTLP export row onto its wire model. There is no header value to map."""
    return ExportBody(
        id=str(row["id"]) if row.get("id") else None,
        label=str(row.get("label") or ""),
        endpoint=str(row.get("endpoint") or ""),
        protocol=str(row.get("protocol") or "http/protobuf"),
        signals=[str(signal) for signal in (row.get("signals") or [])],
        header_secret_ref=row.get("header_secret_ref"),
        enabled=bool(row.get("enabled")),
        last_delivery_state=str(row.get("last_delivery_state") or "never-attempted"),
        last_delivery_at=_iso(row.get("last_delivery_at")),
        last_failure_reason=row.get("last_failure_reason"),
        updated_by=str(row.get("updated_by_actor_name") or ""),
    )


def _budget_body(row: Mapping[str, Any]) -> BudgetBody:
    """Map a budget row onto its wire model."""
    return BudgetBody(
        id=str(row["id"]) if row.get("id") else None,
        label=str(row.get("label") or ""),
        service=row.get("service"),
        period=str(row.get("period") or "monthly"),
        amount=_float(row.get("amount")),
        currency=str(row.get("currency") or "USD"),
        alert_thresholds=[_float(threshold) for threshold in (row.get("alert_thresholds") or [])],
        notify_channel_ref=row.get("notify_channel_ref"),
        enabled=bool(row.get("enabled", True)),
        updated_by=str(row.get("updated_by_actor_name") or ""),
    )


def _check_body(row: Mapping[str, Any]) -> SyntheticCheckBody:
    """Map a synthetic check row onto its wire model."""
    return SyntheticCheckBody(
        id=str(row["id"]) if row.get("id") else None,
        label=str(row.get("label") or ""),
        target_path=str(row.get("target_path") or "/"),
        method=str(row.get("method") or "GET"),
        regions=[str(region) for region in (row.get("regions") or [])],
        interval_seconds=_int(row.get("interval_seconds"), 300),
        expected_status=_int(row.get("expected_status"), 200),
        latency_budget_ms=_int(row.get("latency_budget_ms"), 1000),
        enabled=bool(row.get("enabled")),
        updated_by=str(row.get("updated_by_actor_name") or ""),
    )


def _session_body(row: Mapping[str, Any]) -> TailSessionBody:
    """Map a live tail session row onto its wire model."""
    return TailSessionBody(
        id=str(row["id"]) if row.get("id") else None,
        sample_rate=_float(row.get("sample_rate")),
        max_events_per_sec=_int(row.get("max_events_per_sec")),
        redaction_allowlist=[str(key) for key in (row.get("redaction_allowlist") or [])],
        filter_expression=row.get("filter_expression"),
        stream_state=str(row.get("stream_state") or "requested"),
        started_at=_iso(row.get("started_at")),
        ended_at=_iso(row.get("ended_at")),
        opened_by=str(row.get("opened_by_actor_name") or ""),
        reason=str(row.get("reason") or ""),
        retain_until=_iso(row.get("retain_until")),
    )


def _log_body(row: Mapping[str, Any]) -> LogBody:
    """Map a log row onto its wire model."""
    return LogBody(
        id=str(row.get("id") or ""),
        at=_iso(row.get("at")),
        level=str(row.get("level") or "info"),
        source=str(row.get("source") or ""),
        message=str(row.get("message") or ""),
        release_id=str(row["release_id"]) if row.get("release_id") else None,
        region=str(row.get("region") or "auto"),
        trace_ref=str(row["trace_ref"]) if row.get("trace_ref") else None,
        evidence={str(k): str(v) for k, v in (row.get("evidence") or {}).items()},
        retain_until=_iso(row.get("retain_until")),
    )


def _trace_body(row: Mapping[str, Any]) -> TraceBody:
    """Map a trace row onto its wire model."""
    return TraceBody(
        id=str(row.get("id") or ""),
        trace_id=str(row.get("trace_id") or ""),
        started_at=_iso(row.get("started_at")),
        duration_ms=_int(row.get("duration_ms")),
        route=str(row.get("route") or ""),
        method=str(row.get("method") or "GET"),
        status_code=row.get("status_code"),
        sample_rate=_float(row.get("sample_rate"), 1.0),
        release_id=str(row["release_id"]) if row.get("release_id") else None,
        region=str(row.get("region") or "auto"),
        retain_until=_iso(row.get("retain_until")),
    )


def _span_body(row: Mapping[str, Any]) -> SpanBody:
    """Map a span row onto its wire model."""
    return SpanBody(
        id=str(row.get("id") or ""),
        span_id=str(row.get("span_id") or ""),
        parent_span_ref=row.get("parent_span_ref"),
        name=str(row.get("name") or ""),
        component=str(row.get("component") or ""),
        start_offset_ms=_int(row.get("start_offset_ms")),
        duration_ms=_int(row.get("duration_ms")),
        status=str(row.get("status") or "ok"),
        attributes={str(k): str(v) for k, v in (row.get("attributes") or {}).items()},
    )


def _usage_body(row: Mapping[str, Any]) -> UsageRecordBody:
    """Map a usage row onto its wire model.

    ``basis``, ``metered`` and ``billable`` are not read from the row and cannot be: they are
    literal defaults on the model. A row that somehow carried a metered basis would still be
    reported honestly here, which is the direction that matters — the failure mode is a modelled
    number rendered as a bill, never the reverse.
    """
    return UsageRecordBody(
        id=str(row.get("id") or ""),
        usage_date=_iso(row.get("usage_date")),
        service=str(row.get("service") or ""),
        quantity=_float(row.get("quantity")),
        unit=str(row.get("unit") or "count"),
        amount=_float(row.get("amount")),
        currency=str(row.get("currency") or "USD"),
        included_quantity=_float(row.get("included_quantity")),
        overage_quantity=_float(row.get("overage_quantity")),
        cache_savings_amount=_opt_float(row.get("cache_savings_amount")),
        forecast_amount=_opt_float(row.get("forecast_amount")),
        release_id=str(row["release_id"]) if row.get("release_id") else None,
        region=str(row.get("region") or "auto"),
    )


def _alert_body(row: Mapping[str, Any]) -> BudgetAlertBody:
    """Map a budget alert row onto its wire model."""
    return BudgetAlertBody(
        id=str(row.get("id") or ""),
        budget_id=str(row.get("budget_id") or ""),
        at=_iso(row.get("at")),
        threshold=_float(row.get("threshold")),
        observed_amount=_float(row.get("observed_amount")),
        budget_amount=_float(row.get("budget_amount")),
        currency=str(row.get("currency") or "USD"),
        period_start=_iso(row.get("period_start")),
        period_end=_iso(row.get("period_end")),
        delivery_state=str(row.get("delivery_state") or "not-dispatched"),
        acknowledged_at=_iso(row.get("acknowledged_at")),
        acknowledged_by=row.get("acknowledged_by_actor_name"),
    )


def _result_body(row: Mapping[str, Any]) -> SyntheticResultBody:
    """Map a synthetic result row onto its wire model."""
    return SyntheticResultBody(
        id=str(row.get("id") or ""),
        check_id=str(row.get("check_id") or ""),
        at=_iso(row.get("at")),
        outcome=str(row.get("outcome") or "not-run"),
        region=str(row.get("region") or "auto"),
        status_code=row.get("status_code"),
        latency_ms=row.get("latency_ms"),
        release_id=str(row["release_id"]) if row.get("release_id") else None,
        annotation_kind=row.get("annotation_kind"),
        annotation_note=row.get("annotation_note"),
    )


def _audit_body(row: Mapping[str, Any]) -> AuditEntryBody:
    """Map an audit row onto its wire model."""
    detail = row.get("detail")
    return AuditEntryBody(
        id=str(row.get("id") or ""),
        at=_iso(row.get("at")),
        actor_name=str(row.get("actor_name") or ""),
        actor_kind=str(row.get("actor_kind") or ""),
        subject_kind=str(row.get("subject_kind") or ""),
        subject_id=str(row["subject_id"]) if row.get("subject_id") else None,
        summary=str(row.get("summary") or ""),
        detail=dict(detail) if isinstance(detail, Mapping) else {},
    )


# ─── Catalog routes ──────────────────────────────────────────────────────────


@router.get(
    "/insights/metric-families",
    response_model=MetricFamiliesResponse,
    response_model_by_alias=True,
)
async def get_metric_families(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> MetricFamiliesResponse:
    """Return the metric families as data, each with the question it cannot answer.

    ``doesNotAnswer`` is a required field rather than documentation somewhere else, because the
    whole failure mode of an observability product is a number read as more than it is. A rising
    error rate names no cause; a hit ratio says nothing about whether the hits were correct.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return MetricFamiliesResponse(
        families=[
            MetricFamilyBody(
                family=definition.family,
                label=definition.label,
                answers=definition.answers,
                does_not_answer=definition.does_not_answer,
            )
            for definition in METRIC_FAMILY_CATALOG
        ]
    )


@router.get("/insights/services", response_model=ServicesResponse, response_model_by_alias=True)
async def get_insight_services(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ServicesResponse:
    """Return the billable services, their units, and what drives each number."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return ServicesResponse(
        services=[
            ServiceBody(
                service=definition.service,
                label=definition.label,
                unit=definition.unit,
                driver=definition.driver,
            )
            for definition in SERVICE_CATALOG
        ]
    )


@router.get(
    "/insights/residency-stages",
    response_model=ResidencyStagesResponse,
    response_model_by_alias=True,
)
async def get_residency_stages(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ResidencyStagesResponse:
    """Return the six processing stages and what each one's residency promise leaves uncovered.

    §29.6 asks the UX to state what a residency option does not cover, which is an unusual
    requirement and the correct one: a claim with no stated gap is the version somebody quotes to a
    regulator. These sentences are that requirement expressed as data, so the surface renders them
    rather than inventing its own.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return ResidencyStagesResponse(
        stages=[
            ResidencyStageBody(
                stage=definition.stage,
                label=definition.label,
                covers=definition.covers,
                default_uncovered=definition.default_uncovered,
            )
            for definition in RESIDENCY_STAGE_CATALOG
        ],
        residency_classes=[
            ResidencyClassBody(key=key, description=description)
            for key, description in RESIDENCY_CLASS_CATALOG
        ],
    )


# ─── Lane read ───────────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/insights",
    response_model=InsightsLaneResponse,
    response_model_by_alias=True,
)
async def get_insights_lane(
    environment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> InsightsLaneResponse:
    """Return a lane's observability policy, residency, exports, budgets and checks together.

    One read rather than five, for the reason V190 stores the residency stages in one table: an
    operator deciding whether a lane is safe is reading its retention, its residency and its export
    destinations at once, and a surface that made that five round trips would let the five drift on
    screen.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    policy = _policy_for(tenant_id, environment, auth_data)

    lanes = _lanes_for(tenant_id, environment_id, auth_data)
    exports = list_exports(db, tenant_id=tenant_id, environment_id=environment_id)
    budgets = list_budgets(db, tenant_id=tenant_id, environment_id=environment_id)
    checks = list_synthetic_checks(db, tenant_id=tenant_id, environment_id=environment_id)

    complete, effective, warnings = _coverage(lanes)
    digest = signals_digest(
        normalize_policy(_plain(policy)),
        [normalize_residency_lane(_plain(lane)) for lane in lanes],
        [normalize_export(_plain(export)) for export in exports],
        [normalize_budget(_plain(budget)) for budget in budgets],
    )

    return InsightsLaneResponse(
        environment_id=environment_id,
        policy=_policy_body(policy),
        residency_lanes=[_lane_body(lane) for lane in lanes],
        residency_complete=complete,
        effective_residency_class=effective,
        exports=[_export_body(export) for export in exports],
        budgets=[_budget_body(budget) for budget in budgets],
        synthetic_checks=[_check_body(check) for check in checks],
        policy_version=_int(policy.get("policy_version")),
        signals_digest=digest,
        warnings=warnings,
        updated_at=_iso(policy.get("updated_at")),
        updated_by=policy.get("updated_by_actor_name"),
    )


# ─── Policy write ────────────────────────────────────────────────────────────


@router.put(
    "/environments/{environment_id}/insights/policy",
    response_model=SetInsightPolicyResponse,
    response_model_by_alias=True,
)
async def set_insight_policy(
    environment_id: str,
    request: SetInsightPolicyRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SetInsightPolicyResponse:
    """Change what a lane collects, for how long, and how coarsely it reports.

    Shortening log retention below the floor with no stated reason is refused here with a sentence,
    and again by V190's CHECK. Both are deliberate: the operator should meet the explanation, not a
    constraint violation, and no future code path should be able to skip the explanation.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    current = _policy_for(tenant_id, environment, auth_data)

    candidate = normalize_policy(
        {
            "telemetry_enabled": request.telemetry_enabled,
            "metric_retention_days": request.metric_retention_days,
            "log_retention_days": request.log_retention_days,
            "trace_retention_days": request.trace_retention_days,
            "default_sample_rate": request.default_sample_rate,
            "max_tail_sample_rate": request.max_tail_sample_rate,
            "max_tail_events_per_sec": request.max_tail_events_per_sec,
            "privacy_threshold": request.privacy_threshold,
            "retention_waiver_reason": request.retention_waiver_reason,
        }
    )

    try:
        warnings = validate_policy(candidate, current=normalize_policy(_plain(current)))
    except SlateInsightRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                actor_key=actor_key,
                subject_kind="policy",
                subject_id=None,
                summary="Observability policy change refused",
                detail={"reason": exc.refusal.reason, "sentence": exc.refusal.sentence},
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return SetInsightPolicyResponse(
            applied=False,
            dry_run=True,
            policy=_policy_body({**_plain(current), **candidate}),
            policy_version=_int(current.get("policy_version")),
            warnings=_warning_bodies(warnings),
        )

    policy_version = _bump(environment_id, request.expected_policy_version)
    try:
        updated = update_policy(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            policy=candidate,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=actor_key,
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="policy",
        subject_id=None,
        summary=(
            f"Observability policy set: logs {candidate['log_retention_days']}d, traces "
            f"{candidate['trace_retention_days']}d, privacy threshold "
            f"{candidate['privacy_threshold']}"
        ),
        detail={"reason": request.reason, "waiver": candidate["retention_waiver_reason"]},
    )

    return SetInsightPolicyResponse(
        applied=True,
        dry_run=False,
        policy=_policy_body(updated),
        policy_version=_int(updated.get("policy_version"), policy_version),
        warnings=_warning_bodies(warnings),
    )


# ─── Residency write ─────────────────────────────────────────────────────────


@router.put(
    "/environments/{environment_id}/insights/residency/{stage}",
    response_model=WriteResidencyLaneResponse,
    response_model_by_alias=True,
)
async def set_residency_lane(
    environment_id: str,
    stage: str,
    request: WriteResidencyLaneRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteResidencyLaneResponse:
    """State where one processing stage happens, and what that promise does not cover.

    A lane with no stated gap is refused rather than warned about. Every placement leaves something
    uncovered — a network path, a certificate log, an exported copy — and a claim with no stated gap
    is not a stronger promise, it is the same promise with the gap unwritten.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if _stage_definition(stage) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "residency_stage_not_found",
                "message": f"{stage} is not one of the six processing stages.",
            },
        )

    candidate = normalize_residency_lane(
        {
            "stage": stage,
            "residency_class": request.residency_class,
            "regions": request.regions,
            "uncovered_sentence": request.uncovered_sentence,
            "residency_waiver_reason": request.residency_waiver_reason,
        }
    )

    try:
        warnings = validate_residency_lane(candidate)
    except SlateInsightRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                actor_key=actor_key,
                subject_kind="residency",
                subject_id=stage,
                summary=f"Residency change refused for {stage}",
                detail={"reason": exc.refusal.reason, "sentence": exc.refusal.sentence},
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteResidencyLaneResponse(
            applied=False,
            dry_run=True,
            lane=_lane_body(candidate),
            effective_residency_class=None,
            policy_version=_int(policy.get("policy_version")),
            warnings=_warning_bodies(warnings),
        )

    policy_version = _bump(environment_id, request.expected_policy_version)
    try:
        written = upsert_residency_lane(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            lane=candidate,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=actor_key,
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="residency",
        subject_id=stage,
        summary=f"Residency for {stage} set to {candidate['residency_class']}",
        detail={
            "reason": request.reason,
            "regions": candidate["regions"],
            "uncovered": candidate["uncovered_sentence"],
        },
    )

    lanes = list_residency_lanes(db, tenant_id=tenant_id, environment_id=environment_id)
    _, effective, coverage_warnings = _coverage(lanes)

    return WriteResidencyLaneResponse(
        applied=True,
        dry_run=False,
        lane=_lane_body(written),
        effective_residency_class=effective,
        policy_version=policy_version,
        warnings=_warning_bodies(warnings) + coverage_warnings,
    )


# ─── Export destinations ─────────────────────────────────────────────────────


def _write_export(
    *,
    environment_id: str,
    export_id: Optional[str],
    request: WriteExportRequest,
    auth_data: Mapping[str, Any],
) -> WriteExportResponse:
    """Shared body of export create and export replace.

    Both verbs run the same gates in the same order, so they live in one function rather than two
    that could drift — and a drift here would mean a plaintext endpoint could be accepted by
    whichever verb had the weaker check, shipping request data unencrypted to a collector.
    """
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    candidate = normalize_export(
        {
            "label": request.label,
            "endpoint": request.endpoint,
            "protocol": request.protocol,
            "signals": request.signals,
            "header_secret_ref": request.header_secret_ref,
            "enabled": request.enabled,
        }
    )
    # An inline header value is refused rather than dropped. The field is accepted onto the request
    # precisely so it can be named in the refusal: an operator who pasted a bearer token and saw it
    # silently accepted would believe it had been stored and used.
    extra = dict(request.model_extra or {})
    raw = {
        "headers": extra.get("headers"),
        "header_value": extra.get("header_value") or extra.get("headerValue"),
    }

    try:
        warnings = validate_export(candidate, raw=raw)
    except SlateInsightRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                actor_key=actor_key,
                subject_kind="export",
                subject_id=export_id,
                summary="Export destination refused",
                detail={"reason": exc.refusal.reason, "sentence": exc.refusal.sentence},
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteExportResponse(
            applied=False,
            dry_run=True,
            export=_export_body({**candidate, "id": export_id}),
            policy_version=_int(policy.get("policy_version")),
            warnings=_warning_bodies(warnings),
        )

    policy_version = _bump(environment_id, request.expected_policy_version)
    try:
        written = upsert_export(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            export=candidate,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=actor_key,
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="export",
        subject_id=str(written.get("id")) if written.get("id") else export_id,
        summary=f"Export destination {'updated' if export_id else 'created'}: {request.label}",
        detail={"reason": request.reason, "signals": candidate["signals"]},
    )

    return WriteExportResponse(
        applied=True,
        dry_run=False,
        export=_export_body(written),
        policy_version=policy_version,
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/insights/exports",
    response_model=WriteExportResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_export(
    environment_id: str,
    request: WriteExportRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteExportResponse:
    """Create an OTLP export destination, refusing an unsafe one by name."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_export(
        environment_id=environment_id, export_id=None, request=request, auth_data=auth_data
    )


@router.put(
    "/environments/{environment_id}/insights/exports/{export_id}",
    response_model=WriteExportResponse,
    response_model_by_alias=True,
)
async def replace_export(
    environment_id: str,
    export_id: str,
    request: WriteExportRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteExportResponse:
    """Replace an OTLP export destination, running the same gates as a create."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_export(
        environment_id=environment_id, export_id=export_id, request=request, auth_data=auth_data
    )


@router.delete(
    "/environments/{environment_id}/insights/exports/{export_id}",
    response_model=DeleteInsightResourceResponse,
    response_model_by_alias=True,
)
async def remove_export(
    environment_id: str,
    export_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteInsightResourceResponse:
    """Remove an OTLP export destination."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteInsightResourceResponse(
            deleted=False, dry_run=True, policy_version=_int(policy.get("policy_version"))
        )

    policy_version = _bump(environment_id, expected_policy_version)
    try:
        deleted = delete_export(
            db, tenant_id=tenant_id, environment_id=environment_id, export_id=export_id
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="export",
        subject_id=export_id,
        summary=f"Export destination removed: {deleted.get('label') or export_id}",
        detail={},
    )
    return DeleteInsightResourceResponse(
        deleted=True, dry_run=False, policy_version=policy_version
    )


# ─── Budgets ─────────────────────────────────────────────────────────────────


def _write_budget(
    *,
    environment_id: str,
    budget_id: Optional[str],
    request: WriteBudgetRequest,
    auth_data: Mapping[str, Any],
) -> WriteBudgetResponse:
    """Shared body of budget create and budget replace.

    The currency check is the reason both verbs share this. A budget denominated differently from
    the usage it would be compared against is refused rather than converted at a rate this system
    has no business inventing, and a create that skipped that check would produce an alert
    threshold depending on an exchange rate nobody reviewed.
    """
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    candidate = normalize_budget(
        {
            "label": request.label,
            "service": request.service,
            "period": request.period,
            "amount": request.amount,
            "currency": request.currency,
            "alert_thresholds": request.alert_thresholds,
            "notify_channel_ref": request.notify_channel_ref,
            "enabled": request.enabled,
        }
    )

    # The currency actually in use on this lane, read rather than asserted by the caller: a client
    # able to state it could make the mismatch refusal unreachable by declaring agreement.
    usage_rows = list_usage(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        services=[candidate["service"]] if candidate["service"] else None,
        limit=500,
    )
    usage_currency = (
        str(usage_rows[0].get("currency") or "").upper() or None if usage_rows else None
    )
    consumed = sum(_float(row.get("amount")) for row in usage_rows) if usage_rows else None

    try:
        warnings = validate_budget(
            candidate, usage_currency=usage_currency, consumed_amount=consumed
        )
    except SlateInsightRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                actor_key=actor_key,
                subject_kind="budget",
                subject_id=budget_id,
                summary="Budget refused",
                detail={"reason": exc.refusal.reason, "sentence": exc.refusal.sentence},
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteBudgetResponse(
            applied=False,
            dry_run=True,
            budget=_budget_body({**candidate, "id": budget_id}),
            policy_version=_int(policy.get("policy_version")),
            warnings=_warning_bodies(warnings),
        )

    policy_version = _bump(environment_id, request.expected_policy_version)
    try:
        written = upsert_budget(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            budget=candidate,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=actor_key,
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="budget",
        subject_id=str(written.get("id")) if written.get("id") else budget_id,
        summary=(
            f"Budget {'updated' if budget_id else 'created'}: {request.label} at "
            f"{candidate['amount']} {candidate['currency']} per {candidate['period']}"
        ),
        detail={"reason": request.reason, "thresholds": candidate["alert_thresholds"]},
    )

    return WriteBudgetResponse(
        applied=True,
        dry_run=False,
        budget=_budget_body(written),
        policy_version=policy_version,
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/insights/budgets",
    response_model=WriteBudgetResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_budget(
    environment_id: str,
    request: WriteBudgetRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteBudgetResponse:
    """Create a spend budget, refusing one that could never alert or never reconcile."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_budget(
        environment_id=environment_id, budget_id=None, request=request, auth_data=auth_data
    )


@router.put(
    "/environments/{environment_id}/insights/budgets/{budget_id}",
    response_model=WriteBudgetResponse,
    response_model_by_alias=True,
)
async def replace_budget(
    environment_id: str,
    budget_id: str,
    request: WriteBudgetRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteBudgetResponse:
    """Replace a spend budget, running the same gates as a create."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_budget(
        environment_id=environment_id, budget_id=budget_id, request=request, auth_data=auth_data
    )


@router.delete(
    "/environments/{environment_id}/insights/budgets/{budget_id}",
    response_model=DeleteInsightResourceResponse,
    response_model_by_alias=True,
)
async def remove_budget(
    environment_id: str,
    budget_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteInsightResourceResponse:
    """Remove a budget and, by cascade, its alert history."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteInsightResourceResponse(
            deleted=False, dry_run=True, policy_version=_int(policy.get("policy_version"))
        )

    policy_version = _bump(environment_id, expected_policy_version)
    try:
        deleted = delete_budget(
            db, tenant_id=tenant_id, environment_id=environment_id, budget_id=budget_id
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="budget",
        subject_id=budget_id,
        summary=f"Budget removed: {deleted.get('label') or budget_id}",
        detail={},
    )
    return DeleteInsightResourceResponse(
        deleted=True, dry_run=False, policy_version=policy_version
    )


# ─── Synthetic checks ────────────────────────────────────────────────────────


def _write_check(
    *,
    environment_id: str,
    check_id: Optional[str],
    request: WriteCheckRequest,
    auth_data: Mapping[str, Any],
) -> WriteCheckResponse:
    """Shared body of synthetic check create and replace."""
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    candidate = {
        "label": request.label,
        "target_path": request.target_path,
        "method": request.method,
        "regions": list(request.regions),
        "interval_seconds": request.interval_seconds,
        "expected_status": request.expected_status,
        "latency_budget_ms": request.latency_budget_ms,
        "enabled": request.enabled,
    }

    try:
        warnings = validate_synthetic_check(candidate)
    except SlateInsightRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                actor_key=actor_key,
                subject_kind="synthetic-check",
                subject_id=check_id,
                summary="Synthetic check refused",
                detail={"reason": exc.refusal.reason, "sentence": exc.refusal.sentence},
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteCheckResponse(
            applied=False,
            dry_run=True,
            check=_check_body({**candidate, "id": check_id}),
            policy_version=_int(policy.get("policy_version")),
            warnings=_warning_bodies(warnings),
        )

    policy_version = _bump(environment_id, request.expected_policy_version)
    try:
        written = upsert_synthetic_check(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            check=candidate,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=actor_key,
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="synthetic-check",
        subject_id=str(written.get("id")) if written.get("id") else check_id,
        summary=f"Synthetic check {'updated' if check_id else 'created'}: {request.label}",
        detail={"reason": request.reason, "regions": candidate["regions"]},
    )

    return WriteCheckResponse(
        applied=True,
        dry_run=False,
        check=_check_body(written),
        policy_version=policy_version,
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/insights/checks",
    response_model=WriteCheckResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_synthetic_check(
    environment_id: str,
    request: WriteCheckRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteCheckResponse:
    """Create a synthetic check.

    A check running from one region reports that region's health rather than the lane's, which is
    a warning rather than a refusal: it is a real limitation and a legitimate configuration, and
    the sentence is what stops it being read as the lane being healthy.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_check(
        environment_id=environment_id, check_id=None, request=request, auth_data=auth_data
    )


@router.put(
    "/environments/{environment_id}/insights/checks/{check_id}",
    response_model=WriteCheckResponse,
    response_model_by_alias=True,
)
async def replace_synthetic_check(
    environment_id: str,
    check_id: str,
    request: WriteCheckRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteCheckResponse:
    """Replace a synthetic check, running the same gates as a create."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_check(
        environment_id=environment_id, check_id=check_id, request=request, auth_data=auth_data
    )


@router.delete(
    "/environments/{environment_id}/insights/checks/{check_id}",
    response_model=DeleteInsightResourceResponse,
    response_model_by_alias=True,
)
async def remove_synthetic_check(
    environment_id: str,
    check_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteInsightResourceResponse:
    """Remove a synthetic check and, by cascade, its results."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteInsightResourceResponse(
            deleted=False, dry_run=True, policy_version=_int(policy.get("policy_version"))
        )

    policy_version = _bump(environment_id, expected_policy_version)
    try:
        deleted = delete_synthetic_check(
            db, tenant_id=tenant_id, environment_id=environment_id, check_id=check_id
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="synthetic-check",
        subject_id=check_id,
        summary=f"Synthetic check removed: {deleted.get('label') or check_id}",
        detail={},
    )
    return DeleteInsightResourceResponse(
        deleted=True, dry_run=False, policy_version=policy_version
    )


# ─── Live tail ───────────────────────────────────────────────────────────────
#
# ``/tail`` is registered before ``/tail/{session_id}`` and the literal-segment routes above are
# registered before any sibling path parameter, because FastAPI matches in registration order. A
# list arriving at the close handler would be an attempt to close a session whose id happened to be
# the empty string, and on this surface the close handler is the one that ends a capture of live
# reader traffic.


@router.post(
    "/environments/{environment_id}/insights/tail",
    response_model=OpenTailResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def open_live_tail(
    environment_id: str,
    request: OpenTailRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> OpenTailResponse:
    """Open a live tail session against the lane's ceilings.

    The ceilings are checked rather than clamped, deliberately. Clamping would let an operator ask
    for a rate they do not get and read a stream they believe is complete, which on this surface
    means concluding a route is quiet when it was merely sampled away.

    A tail with no stated reason is refused. A tail is a capture of live reader traffic in front of
    a person, and the question at review is never that one was opened but why.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    candidate = normalize_tail_request(
        {
            "sample_rate": request.sample_rate,
            "max_events_per_sec": request.max_events_per_sec,
            "redaction_allowlist": request.redaction_allowlist,
            "filter_expression": request.filter_expression,
            "reason": request.reason,
        }
    )

    try:
        session = plan_live_tail(candidate, normalize_policy(_plain(policy)))
    except SlateInsightRefusedError as exc:
        # Audited even on a dry run, unlike every other write on this surface. A refused attempt to
        # capture reader traffic is exactly the attempt a later review wants to see, and a preview
        # flag set by the caller must not be able to keep it out of the record.
        _audit(
            tenant_id=tenant_id,
            environment_id=environment_id,
            actor=actor,
            actor_key=actor_key,
            subject_kind="live-tail",
            subject_id=None,
            summary="Live tail refused",
            detail={"reason": exc.refusal.reason, "sentence": exc.refusal.sentence},
        )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return OpenTailResponse(
            applied=False,
            dry_run=True,
            session=_session_body(session),
            policy_version=_int(policy.get("policy_version")),
        )

    written = open_tail_session(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        session=session,
        actor_id=actor[0],
        actor_name=actor[1],
        actor_key=actor_key,
        policy=policy,
    )

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="live-tail",
        subject_id=str(written.get("id")) if written.get("id") else None,
        summary=f"Live tail opened at {candidate['sample_rate']} sampling",
        detail={"reason": candidate["reason"], "allowlist": candidate["redaction_allowlist"]},
    )

    return OpenTailResponse(
        applied=True,
        dry_run=False,
        session=_session_body(written),
        policy_version=_int(policy.get("policy_version")),
    )


@router.get(
    "/environments/{environment_id}/insights/tail",
    response_model=TailSessionsResponse,
    response_model_by_alias=True,
)
async def get_tail_sessions(
    environment_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> TailSessionsResponse:
    """Return a lane's recent live tail sessions, newest first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_tail_sessions(
        db, tenant_id=tenant_id, environment_id=environment_id, limit=limit
    )
    return TailSessionsResponse(sessions=[_session_body(row) for row in rows])


@router.delete(
    "/environments/{environment_id}/insights/tail/{session_id}",
    response_model=CloseTailResponse,
    response_model_by_alias=True,
)
async def close_live_tail(
    environment_id: str,
    session_id: str,
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CloseTailResponse:
    """Close a live tail session.

    No delivery count is written here and there is no argument by which one could be. Nothing
    delivered anything, and a close that could record a stream is the one path by which this
    surface could claim a capture it never had.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)

    if dry_run:
        return CloseTailResponse(closed=False, dry_run=True, session=None)

    try:
        closed = close_tail_session(
            db, tenant_id=tenant_id, environment_id=environment_id, session_id=session_id
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="live-tail",
        subject_id=session_id,
        summary="Live tail closed",
        detail={},
    )
    return CloseTailResponse(closed=True, dry_run=False, session=_session_body(closed))


# ─── Alerts ──────────────────────────────────────────────────────────────────
#
# ``/alerts`` is registered before ``/alerts/{alert_id}/acknowledge`` for the same reason.


@router.get(
    "/environments/{environment_id}/insights/alerts",
    response_model=BudgetAlertsResponse,
    response_model_by_alias=True,
)
async def get_budget_alerts(
    environment_id: str,
    budget_id: Optional[str] = Query(default=None, alias="budgetId"),
    unacknowledged_only: bool = Query(default=False, alias="unacknowledgedOnly"),
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> BudgetAlertsResponse:
    """Return a lane's budget alerts, newest first, each showing its own arithmetic.

    ``budgetAmount`` is the amount captured when the alert fired rather than the budget's current
    value, so a later edit does not rewrite what the alert was compared against.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_budget_alerts(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        budget_id=budget_id,
        unacknowledged_only=unacknowledged_only,
        limit=limit,
    )
    return BudgetAlertsResponse(alerts=[_alert_body(row) for row in rows])


@router.post(
    "/environments/{environment_id}/insights/alerts/{alert_id}/acknowledge",
    response_model=AcknowledgeAlertResponse,
    response_model_by_alias=True,
)
async def acknowledge_alert(
    environment_id: str,
    alert_id: str,
    request: AcknowledgeAlertRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> AcknowledgeAlertResponse:
    """Acknowledge one budget alert.

    An acknowledgement is a person and a time together, or neither — V190 pairs the columns by
    CHECK and the store writes all three at once. No policy version is consumed: acknowledging an
    alert changes no configuration, and invalidating every open editor to dismiss a notice would be
    the wrong trade during the incident that produced it.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)

    if request.dry_run:
        return AcknowledgeAlertResponse(acknowledged=False, dry_run=True, alert=None)

    try:
        updated = acknowledge_budget_alert(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            alert_id=alert_id,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=actor_key,
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="budget-alert",
        subject_id=alert_id,
        summary="Budget alert acknowledged",
        detail={"note": request.note} if request.note else {},
    )
    return AcknowledgeAlertResponse(
        acknowledged=True, dry_run=False, alert=_alert_body(updated)
    )


# ─── Metrics, logs and traces ────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/insights/metrics",
    response_model=MetricsResponse,
    response_model_by_alias=True,
)
async def get_metrics(
    environment_id: str,
    families: Optional[List[str]] = Query(default=None),
    release_id: Optional[str] = Query(default=None, alias="releaseId"),
    region: Optional[str] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> MetricsResponse:
    """Return a lane's correlated metric points, and the ones that could not be keyed.

    Correlation is a precondition rather than a feature: a point with no release is a point a
    drill-down cannot land on, and a chart whose drill-down lands somewhere else is worse than a
    chart with a gap in it. So an uncorrelatable point is dropped and *reported* rather than emitted
    unkeyed.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    policy = _policy_for(tenant_id, environment, auth_data)
    threshold = _int(policy.get("privacy_threshold"), 10)

    rows = list_metric_series(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        families=families,
        release_id=release_id,
        region=region,
        limit=limit,
    )
    verdict = correlate_signals(
        environment_id, [_plain(row) for row in rows], privacy_threshold=threshold
    )

    return MetricsResponse(
        points=[
            MetricPointBody(
                release_id=point.key.release_id,
                region=point.key.region,
                family=point.family,
                metric_key=point.metric_key,
                window_start=_iso(point.window_start),
                window_end=_iso(point.window_end),
                value=point.value,
                unit=point.unit,
                sample_count=point.sample_count,
                suppressed=point.suppressed,
            )
            for point in verdict.points
        ],
        dropped=[
            DroppedPointBody(id=row_id, reason=reason) for row_id, reason in verdict.dropped
        ],
        suppressed_count=verdict.suppressed_count,
        privacy_threshold=threshold,
        warnings=_warning_bodies(verdict.warnings),
    )


@router.get(
    "/environments/{environment_id}/insights/logs",
    response_model=LogsResponse,
    response_model_by_alias=True,
)
async def get_logs(
    environment_id: str,
    levels: Optional[List[str]] = Query(default=None),
    sources: Optional[List[str]] = Query(default=None),
    release_id: Optional[str] = Query(default=None, alias="releaseId"),
    region: Optional[str] = Query(default=None),
    trace_ref: Optional[str] = Query(default=None, alias="traceRef"),
    query: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> LogsResponse:
    """Return a lane's structured logs, newest first, with allowlisted evidence.

    ``traceRef`` is what connects a log line to the trace it belongs to, which is the whole point of
    the three shared correlation columns: filtering on screen and filtering in a query must not be
    able to mean different things.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_logs(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        levels=levels,
        sources=sources,
        release_id=release_id,
        region=region,
        trace_ref=trace_ref,
        query=query,
        limit=limit,
    )
    return LogsResponse(logs=[_log_body(row) for row in rows])


@router.get(
    "/environments/{environment_id}/insights/traces",
    response_model=TracesResponse,
    response_model_by_alias=True,
)
async def get_traces(
    environment_id: str,
    release_id: Optional[str] = Query(default=None, alias="releaseId"),
    region: Optional[str] = Query(default=None),
    route: Optional[str] = Query(default=None),
    min_duration_ms: Optional[int] = Query(default=None, alias="minDurationMs"),
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> TracesResponse:
    """Return a lane's traces, newest first.

    ``minDurationMs`` is how an operator finds the traces worth opening, which is the only way a
    trace list is usable at all.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_traces(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        release_id=release_id,
        region=region,
        route=route,
        min_duration_ms=min_duration_ms,
        limit=limit,
    )
    return TracesResponse(traces=[_trace_body(row) for row in rows])


@router.get(
    "/environments/{environment_id}/insights/traces/{trace_id}",
    response_model=TraceDetailResponse,
    response_model_by_alias=True,
)
async def get_trace_detail(
    environment_id: str,
    trace_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> TraceDetailResponse:
    """Return one trace and its spans, ordered as a waterfall.

    Spans arrive ordered by start offset rather than by insertion, because the waterfall is drawn
    from offsets and an ordering the renderer has to redo is an ordering the two can disagree about.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    try:
        found = get_trace(
            db, tenant_id=tenant_id, environment_id=environment_id, trace_id=trace_id
        )
    except SlateInsightStoreError as exc:
        raise _not_found_http(exc) from exc

    return TraceDetailResponse(
        trace=_trace_body(found["trace"]),
        spans=[_span_body(span) for span in found.get("spans") or []],
    )


# ─── Usage and spend ─────────────────────────────────────────────────────────
#
# ``/usage`` is registered before ``/usage/export`` — both literals, so order is not load-bearing
# between them, but the pair is kept together and ahead of nothing parameterized, matching the
# ordering discipline the rest of this module follows.


def _usage_window(
    tenant_id: str,
    environment_id: str,
    *,
    services: Optional[List[str]],
    release_id: Optional[str],
    region: Optional[str],
    since: Optional[date],
    until: Optional[date],
    limit: int,
) -> List[Dict[str, Any]]:
    """Read the daily usage records one usage view is built from."""
    return list_usage(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        services=services,
        release_id=release_id,
        region=region,
        since=since,
        until=until,
        limit=limit,
    )


@router.get(
    "/environments/{environment_id}/insights/usage",
    response_model=UsageResponse,
    response_model_by_alias=True,
)
async def get_usage(
    environment_id: str,
    services: Optional[List[str]] = Query(default=None),
    release_id: Optional[str] = Query(default=None, alias="releaseId"),
    region: Optional[str] = Query(default=None),
    since: Optional[date] = Query(default=None),
    until: Optional[date] = Query(default=None),
    days_remaining: int = Query(default=0, ge=0, le=366, alias="daysRemaining"),
    limit: int = Query(default=1000, ge=1, le=5000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> UsageResponse:
    """Return a lane's daily usage, its per-service rollups and its forecast.

    Three things this deliberately does not do. It never sums a forecast into a total, because a
    projection added to things that happened produces a figure that is neither. It never reports
    cache savings assembled from a mix of metered and modelled rows, because that is a measurement
    in presentation and a model in fact. And it never marks anything billable, which is not a
    decision this handler makes but a property of :class:`UsageRollupBody` — the field is a
    ``Literal[False]`` no handler can assign.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = [
        _plain(row)
        for row in _usage_window(
            tenant_id,
            environment_id,
            services=services,
            release_id=release_id,
            region=region,
            since=since,
            until=until,
            limit=limit,
        )
    ]

    by_service: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_service.setdefault(str(row.get("service") or ""), []).append(row)

    labels = {definition.service: definition.label for definition in SERVICE_CATALOG}
    rollups: List[UsageRollupBody] = []
    warnings: List[InsightWarningBody] = []
    try:
        for service in sorted(by_service):
            rollup = roll_up_usage(by_service[service], service=service)
            rollups.append(
                UsageRollupBody(
                    service=rollup.service,
                    label=labels.get(rollup.service, rollup.service),
                    quantity=rollup.quantity,
                    unit=rollup.unit,
                    amount=rollup.amount,
                    currency=rollup.currency,
                    included_quantity=rollup.included_quantity,
                    overage_quantity=rollup.overage_quantity,
                    cache_savings_amount=rollup.cache_savings_amount,
                    forecast_amount=rollup.forecast_amount,
                    days=rollup.days,
                )
            )
        projection, forecast_warnings = forecast_service(rows, days_remaining=days_remaining)
    except SlateInsightRefusedError as exc:
        raise _refusal_http(exc) from exc

    warnings.extend(_warning_bodies(forecast_warnings))
    currency = rollups[0].currency if rollups else "USD"

    return UsageResponse(
        records=[_usage_body(row) for row in rows],
        rollups=rollups,
        forecast_amount=projection,
        forecast_days_remaining=days_remaining,
        currency=currency,
        warnings=warnings,
    )


@router.get("/environments/{environment_id}/insights/usage/export")
async def export_usage(
    environment_id: str,
    services: Optional[List[str]] = Query(default=None),
    since: Optional[date] = Query(default=None),
    until: Optional[date] = Query(default=None),
    limit: int = Query(default=10000, ge=1, le=100000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> StreamingResponse:
    """Export a lane's daily usage as CSV.

    Every row carries ``basis``, ``metered`` and ``billable`` columns, and every one of them is a
    constant written by this function rather than read from the row. A spreadsheet of costs is the
    artifact most likely to be forwarded to somebody who never saw this surface, so the file has to
    say what it is without the page around it.

    VIEW rather than PUBLISH: "what did this lane cost" is the auditor's question, and gating it
    behind the permission to *change* observability would put the answer out of reach.

    **CSV injection is neutralized** — a cell whose first character is ``=``, ``+``, ``-``, ``@``, a
    tab or a carriage return is prefixed with an apostrophe. **Nothing is silently truncated** —
    this reads one row past the cap and says so in words when there was more.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)

    rows = _usage_window(
        tenant_id,
        environment_id,
        services=services,
        release_id=None,
        region=None,
        since=since,
        until=until,
        limit=limit + 1,
    )
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="export",
        subject_id=None,
        summary="Usage exported",
        detail={"rows": len(rows), "truncated": truncated},
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "usageDate",
            "service",
            "quantity",
            "unit",
            "amount",
            "currency",
            "includedQuantity",
            "overageQuantity",
            "forecastAmount",
            "region",
            "basis",
            "metered",
            "billable",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _csv_cell(_iso(row.get("usage_date"))),
                _csv_cell(row.get("service")),
                _csv_cell(_float(row.get("quantity"))),
                _csv_cell(row.get("unit")),
                _csv_cell(_float(row.get("amount"))),
                _csv_cell(row.get("currency")),
                _csv_cell(_float(row.get("included_quantity"))),
                _csv_cell(_float(row.get("overage_quantity"))),
                _csv_cell(_opt_float(row.get("forecast_amount"))),
                _csv_cell(row.get("region")),
                # Constants, not columns. A forwarded spreadsheet has to say what it is.
                "modelled",
                "false",
                "false",
            ]
        )
    if truncated:
        writer.writerow(
            [
                "TRUNCATED",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                _csv_cell(
                    f"This export stopped at the {limit}-row limit and more records exist. "
                    "Raise the limit to export the remainder; do not read this file as the "
                    "complete record."
                ),
                "",
                "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{environment_id}-slate-usage.csv"'
        },
    )


# ─── Synthetic results ───────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/insights/synthetic-results",
    response_model=SyntheticResultsResponse,
    response_model_by_alias=True,
)
async def get_synthetic_results(
    environment_id: str,
    check_id: Optional[str] = Query(default=None, alias="checkId"),
    release_id: Optional[str] = Query(default=None, alias="releaseId"),
    annotated_only: bool = Query(default=False, alias="annotatedOnly"),
    limit: int = Query(default=200, ge=1, le=1000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SyntheticResultsResponse:
    """Return a lane's synthetic results, newest first.

    ``annotatedOnly`` is how the surface answers "what regressed after the last promotion", which is
    why an annotation is a property of the probe run that found it rather than a free-standing
    record: a regression detached from its evidence is an alert nobody can verify.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_synthetic_results(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        check_id=check_id,
        release_id=release_id,
        annotated_only=annotated_only,
        limit=limit,
    )
    return SyntheticResultsResponse(results=[_result_body(row) for row in rows])


# ─── Audit ───────────────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/insights/audit",
    response_model=AuditResponse,
    response_model_by_alias=True,
)
async def get_insights_audit(
    environment_id: str,
    subject_kind: Optional[str] = Query(default=None, alias="subjectKind"),
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> AuditResponse:
    """Return a lane's append-only observability audit trail, most recent first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_audit(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        subject_kind=subject_kind,
        limit=limit,
    )
    return AuditResponse(entries=[_audit_body(row) for row in rows])


@router.get("/environments/{environment_id}/insights/audit/export")
async def export_insights_audit(
    environment_id: str,
    limit: int = Query(default=10000, ge=1, le=100000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> StreamingResponse:
    """Export a lane's observability audit trail as CSV.

    Reading the evidence is itself audit-worthy — who exported the record of who opened a live tail
    on production is part of that record — so an ``export`` audit row is written before the download
    begins.

    Modelled on ``access_routes.py``'s exporter and fixing the two defects that precedent carries:
    formula-leading cells are neutralized, and truncation is stated in words rather than left as an
    inference an auditor reads as "the rest never happened".
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    actor_key = _actor_key(auth_data)

    # One past the cap, so "there was more" is a fact rather than an inference.
    rows = list_audit(db, tenant_id=tenant_id, environment_id=environment_id, limit=limit + 1)
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        actor_key=actor_key,
        subject_kind="export",
        subject_id=None,
        summary="Observability audit exported",
        detail={"entries": len(rows), "truncated": truncated},
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["when", "actor", "actorKind", "subjectKind", "subjectId", "summary", "detail"]
    )
    for row in rows:
        detail = row.get("detail")
        writer.writerow(
            [
                _csv_cell(_iso(row.get("at"))),
                _csv_cell(row.get("actor_name")),
                _csv_cell(row.get("actor_kind")),
                _csv_cell(row.get("subject_kind")),
                _csv_cell(row.get("subject_id")),
                _csv_cell(row.get("summary")),
                _csv_cell("" if not detail else str(detail)),
            ]
        )
    if truncated:
        writer.writerow(
            [
                "",
                "",
                "",
                "",
                "",
                "TRUNCATED",
                _csv_cell(
                    f"This export stopped at the {limit}-row limit and more entries exist. "
                    "Raise the limit to export the remainder; do not read this file as the "
                    "complete record."
                ),
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{environment_id}-insights-audit.csv"'
        },
    )
