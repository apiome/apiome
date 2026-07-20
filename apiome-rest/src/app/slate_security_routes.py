"""Slate Edge security control REST API — UXE-3.2 (private-suite#2474).

The security control plane the authoring Security surface consumes:

* ``GET  /v1/slate/security/presets`` and ``GET /v1/slate/security/managed-groups``
  — the managed tiers, bot presets, rate presets and curated WAF groups as data: every mode,
  every budget, and the prose stating what each one does to real traffic. The UI prints what
  this returns rather than holding a second copy, because two copies would eventually disagree
  and the screen would be the one that lied.

* ``GET  /v1/slate/environments/{environment_id}/security``
  — the lane's policy: managed tier, presets, group modes, custom rules, carve-outs, the
  concurrency token, and the ``enforcement`` and ``ddos`` blocks described below.

* ``PUT``/``POST``/``DELETE .../security/rules[/{rule_id}]``, ``.../rollout``, ``.../revert``
  — custom rules and their staged rollout. Every write runs
  :func:`app.slate_security.evaluate_security_safety` first, and every write records the prior
  body as a revision, so "every rule change can be reverted" means applying a stored document.

* ``POST .../security/exceptions``, ``.../security/approvals``
  — scoped, expiring carve-outs, and dual-control approvals of one exact body.

* ``POST .../security/simulate``
  — evaluate a test request against the lane's policy and explain the result, naming the winning
  rule *and every rule that lost and why*.

* ``GET  .../security/events[/{event_id}]``, ``.../security/audit``, ``.../security/audit/export``
  — security events, the append-only audit trail, and CSV evidence.

**The honesty boundary, which is the whole point of this ticket.** ``deploy/`` is a single
Caddyfile: no WAF, no bot management, no CDN. Nothing here inspects a request, challenges one or
blocks one. So:

* every policy response carries ``enforcement``, whose ``enforced`` is a ``Literal[False]``;
* every simulation carries ``basis: "policy-simulation"`` and ``observed: false`` as literal
  pydantic defaults no handler assigns, exactly as ``TraceResponse`` does in
  :mod:`app.slate_cache_routes` — the response is structurally unable to lie;
* DDoS status is reported as *unavailable*, never as a protection state, because §29.4's
  "always-on DDoS status" rendered as a green badge would be a false statement rather than
  merely an inert setting.

An unenforced cache rule wastes a purge. An unenforced WAF rule means somebody believes they are
stopping an attacker and is not, so every sentence here is at least as loud as the cache plane's.

Authorization: reads require VERSIONS/VIEW, writes require VERSIONS/PUBLISH. As in
:mod:`app.slate_cache_routes` there is no separate ``security`` resource — V187 and V188
deliberately did not add one, because inventing a permission dimension the roles matrix does not
render would leave it ungrantable in the UI.

Scope misses answer 404 (not 403) so cross-tenant probes cannot confirm a lane exists.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id
from .database import db
from .permissions import Action, Resource, enforce_permission
from .slate_auth import validate_slate_authentication
from .slate_deployment_store import get_environment
from .slate_security import (
    BOT_PRESETS,
    MANAGED_GROUPS,
    MANAGED_RULESETS,
    RATE_PRESETS,
    SecurityRefusal,
    SimulationRequest,
    SlateSecurityRefusedError,
    body_digest,
    evaluate_exception_safety,
    evaluate_policy_safety,
    evaluate_security_safety,
    normalize_rule,
    rules_digest,
    simulate_request,
)
from .slate_security_store import (
    SlateSecurityPolicyConflictError,
    SlateSecurityStoreError,
    append_audit,
    create_exception,
    delete_exception,
    delete_rule,
    ensure_policy,
    get_event,
    get_rule,
    list_approvals,
    list_audit,
    list_events,
    list_exceptions,
    list_managed_groups,
    list_revisions,
    list_rules,
    record_approval,
    record_event,
    revert_rule,
    rule_evaluation_context,
    set_managed_group,
    set_presets,
    set_rollout,
    upsert_rule,
)

router = APIRouter(prefix="/v1/slate", tags=["slate-security"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


#: Stated on every policy read and every write outcome. Louder than the cache plane's equivalent
#: on purpose: a cache rule that does not apply costs a slow page, and a security rule that does
#: not apply costs the belief that an attacker is being stopped.
_NO_ENFORCEMENT_SENTENCE = (
    "No managed delivery tier is attached to this environment. These rules are recorded "
    "policy: nothing inspects requests, nothing is challenged and nothing is blocked."
)

#: Stated on every simulation and on the event stream.
_NO_OBSERVATION_SENTENCE = (
    "These events are simulations of the recorded policy against sample requests, not traffic "
    "that was observed. No request path exists to observe."
)

#: Stated wherever §29.4's "always-on DDoS status" would otherwise be rendered. The status is
#: *unavailable*, never a protection state: a green badge here would be a false statement rather
#: than an inert setting, and an operator would act on it.
_DDOS_UNAVAILABLE_SENTENCE = (
    "DDoS protection status is unavailable because no delivery tier is attached. This is not a "
    "report that protection is off; it is the absence of anything able to report."
)

#: A cell beginning with one of these is interpreted as a formula by Excel, Numbers and Sheets.
#: An actor display name is attacker-influenced text, so the export prefixes such a cell with an
#: apostrophe. ``access_routes.py``'s exporter does not, which is the defect this one fixes.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# ─── Request/response models ─────────────────────────────────────────────────


class ManagedRulesetBody(_CamelModel):
    """A managed WAF tier as data, so the UI never holds a second copy of the modes."""

    key: str = Field(description="off, core or strict.")
    label: str = Field(description="Operator-facing tier name.")
    intent: str = Field(description="One-line intent, from roadmap §29.4.")
    expected_impact: str = Field(description="What this tier does to ordinary traffic.")
    groups: List[str] = Field(description="Catalog ids of the groups the tier enables.")
    group_modes: Dict[str, str] = Field(description="The mode each enabled group runs in.")
    requires_reason: bool = Field(description="Whether choosing this tier must state why.")
    unsafe_if: List[str] = Field(description="What this tier is a poor fit for.")


class BotPresetBody(_CamelModel):
    """A bot preset as data, naming what happens to each traffic class."""

    key: str = Field(description="off, monitor, balanced or aggressive.")
    label: str = Field(description="Operator-facing preset name.")
    intent: str = Field(description="One-line intent.")
    expected_impact: str = Field(description="What this preset does to real crawlers.")
    verified_bots: str = Field(description="What happens to verified crawlers.")
    likely_automated: str = Field(description="What happens to likely-automated traffic.")
    automated: str = Field(description="What happens to definitely-automated traffic.")
    unsafe_if: List[str] = Field(description="What this preset is a poor fit for.")


class RatePresetBody(_CamelModel):
    """A rate preset as data, with the budget as a number rather than an adjective."""

    key: str = Field(description="off, generous, standard or strict.")
    label: str = Field(description="Operator-facing preset name.")
    intent: str = Field(description="One-line intent.")
    expected_impact: str = Field(description="What this budget means for a reader.")
    requests: int = Field(description="Request budget, or 0 when there is none.")
    window_seconds: int = Field(description="Window the budget applies over.")
    action: str = Field(description="What happens when the budget is exceeded.")
    unsafe_if: List[str] = Field(description="What this preset is a poor fit for.")


class SecurityPresetsResponse(_CamelModel):
    """Every managed tier and safe preset this control plane offers."""

    managed_rulesets: List[ManagedRulesetBody] = Field(description="The three managed tiers.")
    bot_presets: List[BotPresetBody] = Field(description="The four bot presets.")
    rate_presets: List[RatePresetBody] = Field(description="The four rate presets.")


class ManagedGroupBody(_CamelModel):
    """One curated WAF group from the code-side catalog."""

    id: str = Field(description="Catalog identifier.")
    title: str = Field(description="Operator-facing name.")
    description: str = Field(description="What the group detects.")
    default_mode: str = Field(description="The mode the group ships in.")
    false_positive_risk: str = Field(description="low, medium or high.")
    expected_impact: str = Field(description="What to expect once this group acts.")
    mode: Optional[str] = Field(
        default=None, description="The lane's mode, when it deviates from the default."
    )
    reason: Optional[str] = Field(default=None, description="Why the lane deviates.")


class ManagedGroupsResponse(_CamelModel):
    """The curated group catalog."""

    groups: List[ManagedGroupBody] = Field(description="Every group, in catalog order.")


class SecurityWarningBody(_CamelModel):
    """A concern that does not block the write."""

    code: str = Field(description="Named warning reason.")
    message: str = Field(description="Operator-facing sentence, rendered verbatim by the UI.")
    field: str = Field(default="", description="Rule field the warning attaches to.")
    severity: Literal["warn", "block"] = Field(
        default="warn", description="warn never blocks; block is returned only on a 409."
    )


class EnforcementBody(_CamelModel):
    """Whether the recorded policy stops anything on the wire.

    ``enforced`` is a ``Literal[False]`` with a default no handler assigns. That is the point: the
    response is structurally unable to claim an enforcement, in the same way V188's CHECKs make
    the corresponding columns unable to hold one.
    """

    enforced: Literal[False] = Field(
        default=False, description="False. No delivery tier is attached to this environment."
    )
    sentence: str = Field(
        default=_NO_ENFORCEMENT_SENTENCE, description="What that means, in words."
    )


class DdosBody(_CamelModel):
    """DDoS protection status, which is *unavailable* rather than a protection state.

    §29.4 promises always-on DDoS status. With no delivery tier there is nothing able to report
    one, and a green "protected" badge would be a false statement rather than an inert setting —
    so the only value this model can carry is the absence of a report.
    """

    status: Literal["unavailable"] = Field(
        default="unavailable", description="unavailable: nothing is able to report a status."
    )
    sentence: str = Field(
        default=_DDOS_UNAVAILABLE_SENTENCE, description="What that means, in words."
    )


class SecurityRuleBody(_CamelModel):
    """A custom security rule."""

    id: Optional[str] = Field(default=None, description="Rule id, absent before it is written.")
    ordinal: int = Field(default=0, description="Precedence; lower wins.")
    enabled: bool = Field(default=True, description="Whether the rule participates.")
    label: str = Field(default="", description="Operator-facing rule name.")
    matcher_kind: str = Field(default="prefix", description="exact, prefix, glob or regex.")
    matcher_value: str = Field(default="/", description="The route pattern.")
    matcher_methods: List[str] = Field(default_factory=list)
    matcher_hosts: List[str] = Field(default_factory=list)
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    action: str = Field(default="log", description="allow, log, challenge, rate-limit or block.")
    rate_requests: Optional[int] = Field(default=None)
    rate_window_seconds: Optional[int] = Field(default=None)
    rollout_mode: str = Field(default="simulate", description="simulate or enforce.")
    rollout_percent: int = Field(default=0, ge=0, le=100)
    expires_at: Optional[str] = Field(default=None)
    acknowledged_warnings: List[str] = Field(default_factory=list)
    body_digest: str = Field(
        default="", description="Content digest of the decisive fields; what an approval names."
    )
    revision: int = Field(default=1, description="Monotonic revision counter.")


class SecurityExceptionBody(_CamelModel):
    """One scoped, expiring carve-out."""

    id: Optional[str] = Field(default=None)
    subject_kind: str = Field(default="policy", description="managed-group, rule or policy.")
    subject_ref: str = Field(default="")
    matcher_kind: str = Field(default="prefix")
    matcher_value: str = Field(default="")
    expires_at: Optional[str] = Field(default=None)
    reason: str = Field(default="")
    actor_name: str = Field(default="")


class SecurityPolicyResponse(_CamelModel):
    """A lane's complete security policy, and what it actually enforces."""

    environment_id: str = Field(description="The lane.")
    managed_ruleset: str = Field(description="Active managed tier.")
    bot_preset: str = Field(description="Active bot preset.")
    rate_preset: str = Field(description="Active rate preset.")
    challenge_mode: str = Field(description="off, managed or always.")
    preset_overrides: Dict[str, Any] = Field(default_factory=dict)
    managed_off_reason: Optional[str] = Field(default=None)
    policy_version: int = Field(description="Optimistic-concurrency token.")
    edge_attached: bool = Field(description="Whether a delivery tier serves this lane.")
    edge_provider: Optional[str] = Field(default=None)
    enforcement: EnforcementBody = Field(
        default_factory=EnforcementBody, description="Whether the policy stops anything."
    )
    ddos: DdosBody = Field(default_factory=DdosBody, description="DDoS status, or its absence.")
    groups: List[ManagedGroupBody] = Field(description="The catalog with this lane's overrides.")
    rules: List[SecurityRuleBody] = Field(description="Custom rules, in precedence order.")
    exceptions: List[SecurityExceptionBody] = Field(description="Carve-outs, soonest first.")
    rules_digest: str = Field(description="Determinism receipt over the enabled ruleset.")
    updated_at: Optional[str] = Field(default=None)
    updated_by: Optional[str] = Field(default=None)


class SetPresetsRequest(_CamelModel):
    """Change a lane's managed tier and its bot, rate and challenge settings."""

    managed_ruleset: str = Field(default="core", description="off, core or strict.")
    bot_preset: str = Field(default="balanced")
    rate_preset: str = Field(default="standard")
    challenge_mode: str = Field(default="managed")
    overrides: Dict[str, Any] = Field(default_factory=dict)
    managed_off_reason: Optional[str] = Field(
        default=None, description="Required when the managed ruleset is off."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class SetPresetsResponse(_CamelModel):
    """The outcome of a preset change."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    managed_ruleset: str = Field(description="The tier now in effect, or that would be.")
    bot_preset: str = Field(description="The bot preset now in effect.")
    rate_preset: str = Field(description="The rate preset now in effect.")
    policy_version: int = Field(description="The version after the change.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[SecurityWarningBody] = Field(default_factory=list)


class SetManagedGroupRequest(_CamelModel):
    """Move one managed group off, or back onto, its catalog default."""

    mode: str = Field(description="off, log, challenge or block.")
    reason: Optional[str] = Field(
        default=None, description="Required for off and log, which remove protection."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False)


class SetManagedGroupResponse(_CamelModel):
    """The outcome of a managed-group change."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    group: ManagedGroupBody = Field(description="The group as it now stands.")
    policy_version: int = Field(description="The version after the change.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)


class WriteRuleRequest(SecurityRuleBody):
    """Create or replace a custom security rule."""

    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class WriteRuleResponse(_CamelModel):
    """The outcome of a rule write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    rule: Optional[SecurityRuleBody] = Field(default=None)
    body_digest: str = Field(description="What an approval of this body must name.")
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[SecurityWarningBody] = Field(default_factory=list)


class DeleteRuleResponse(_CamelModel):
    """The outcome of a rule deletion."""

    deleted: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    policy_version: int = Field(description="The version after the write.")


class RolloutRequest(_CamelModel):
    """Advance or retreat a rule's staged rollout."""

    rollout_mode: str = Field(description="simulate or enforce.")
    rollout_percent: int = Field(ge=0, le=100, description="Share of traffic, 0 to 100.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False)
    reason: str = Field(default="")


class RevertRequest(_CamelModel):
    """Restore a rule to a stored revision."""

    revision: int = Field(ge=1, description="Which stored revision to apply.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False)
    reason: str = Field(default="")


class RevisionBody(_CamelModel):
    """One recorded rule body."""

    id: str
    revision: int
    change_kind: str = ""
    body_digest: str = ""
    at: Optional[str] = None
    actor_name: str = ""
    body: Dict[str, Any] = Field(default_factory=dict)


class RevisionsResponse(_CamelModel):
    """A rule's revision history."""

    revisions: List[RevisionBody] = Field(description="Newest first.")


class CreateExceptionRequest(_CamelModel):
    """Open a scoped, expiring carve-out."""

    subject_kind: Literal["managed-group", "rule", "policy"] = Field(
        description="What the carve-out applies to."
    )
    subject_ref: str = Field(default="", description="Group catalog id or rule id.")
    matcher_kind: str = Field(default="prefix")
    matcher_value: str = Field(description="The route pattern the exception covers.")
    expires_at: str = Field(description="When it lapses. An exception that cannot lapse is policy.")
    reason: str = Field(description="Why it exists.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False)


class ExceptionResponse(_CamelModel):
    """The outcome of opening a carve-out."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    exception: Optional[SecurityExceptionBody] = Field(default=None)
    policy_version: int = Field(description="The version after the write.")
    warnings: List[SecurityWarningBody] = Field(default_factory=list)


class DeleteExceptionResponse(_CamelModel):
    """The outcome of closing a carve-out early."""

    deleted: bool
    dry_run: bool
    policy_version: int


class ApprovalRequest(_CamelModel):
    """Record a second person's approval of one exact body."""

    subject_kind: Literal["rule", "exception", "policy", "managed-group"] = Field(
        description="What is being approved."
    )
    subject_id: str = Field(description="Id of the subject.")
    digest: str = Field(description="The body that was reviewed, from the write response.")
    author_actor_key: str = Field(description="Immutable identity of whoever proposed it.")
    author_actor_name: str = Field(default="", description="The proposer's display name.")
    note: Optional[str] = Field(default=None)


class ApprovalBody(_CamelModel):
    """One recorded approval."""

    id: str
    subject_kind: str = ""
    subject_id: str = ""
    digest: str = ""
    author_actor_name: str = ""
    approver_actor_name: str = ""
    approved_at: Optional[str] = None
    note: Optional[str] = None


class SimulateRequestBody(_CamelModel):
    """The test request to evaluate.

    ``signals`` is what makes this deterministic without a detection engine: there is no inspector
    in the request path, so the caller states which detections the request is meant to trip and
    the simulation answers what the *policy* does about them. That is a smaller claim than "this
    request is malicious", and it is the one that is actually true.
    """

    method: str = Field(default="GET")
    host: str = Field(default="")
    path: str = Field(default="/")
    query: Dict[str, str] = Field(default_factory=dict)
    signals: List[str] = Field(default_factory=list, description="Managed group ids to trip.")
    bot_class: str = Field(default="human")
    burst_requests: int = Field(default=0)
    country: str = Field(default="")
    asn: str = Field(default="")
    headers: Dict[str, str] = Field(default_factory=dict)


class SimulateCommandBody(_CamelModel):
    """A simulation, optionally over a what-if ruleset."""

    request: SimulateRequestBody = Field(description="The test request.")
    rules: Optional[List[SecurityRuleBody]] = Field(
        default=None, description="What-if overlay. When absent, the lane's stored rules are used."
    )
    persist: bool = Field(default=False, description="Record the outcome as a security event.")


class SimulationStepBody(_CamelModel):
    """One rule, group or preset the simulation considered, and what became of it."""

    kind: str = Field(description="rule, managed-group, bot-preset or rate-preset.")
    ref: Optional[str] = Field(default=None)
    label: str = Field(description="Its name.")
    ordinal: Optional[int] = Field(default=None)
    outcome: str = Field(description="matched, skipped or not-reached.")
    action: Optional[str] = Field(default=None)
    reason: str = Field(description="Why, in a sentence.")


class SimulateResponse(_CamelModel):
    """What the policy decides for a test request, and why every other rule did not.

    ``basis``, ``observed``, ``enforced`` and ``mitigated`` are literal defaults no handler
    assigns. There is no code path able to make this response claim that a request was observed or
    stopped, which is the structural form of the same guarantee V188 expresses as CHECKs.
    """

    action: str = Field(description="allowed, logged, challenged, rate-limited or would-block.")
    action_reason: str = Field(description="One sentence naming the outcome and what produced it.")
    winning_rule_kind: str = Field(description="What decided.")
    winning_rule_ref: Optional[str] = Field(default=None)
    winning_rule_label: str = Field(description="Its name.")
    rollout_mode: str = Field(description="The rollout mode of whatever decided.")
    exception_applied: Optional[Dict[str, str]] = Field(default=None)
    considered: List[SimulationStepBody] = Field(description="Every rule, and why it did not win.")
    warnings: List[SecurityWarningBody] = Field(default_factory=list)
    rules_digest: str = Field(description="Determinism receipt over the evaluated ruleset.")
    policy_version: int = Field(description="Which policy generation answered.")
    basis: Literal["policy-simulation"] = Field(
        default="policy-simulation",
        description=(
            "This is an evaluation of recorded policy against a test request, not a replay of an "
            "observed request. When a delivery tier lands, 'edge-observed' becomes the second "
            "value of this field rather than a change of meaning for the first."
        ),
    )
    observed: bool = Field(
        default=False, description="False: no delivery tier reported this request."
    )
    enforced: Literal[False] = Field(
        default=False, description="False: nothing acted on this request."
    )
    mitigated: Literal[False] = Field(
        default=False, description="False: nothing was stopped, because nothing can be."
    )
    sentence: str = Field(
        default=_NO_OBSERVATION_SENTENCE, description="What all of that means, in words."
    )
    event_id: Optional[str] = Field(default=None, description="Set when the outcome was recorded.")


class SecurityEventBody(_CamelModel):
    """One security event, with its redacted evidence."""

    id: str
    at: Optional[str] = None
    source: str = ""
    rule_kind: str = ""
    rule_ref: str = ""
    rule_label: str = ""
    route: str = ""
    method: str = ""
    release_id: Optional[str] = None
    region: Optional[str] = None
    action: str = ""
    mitigated: bool = False
    edge_attached: bool = False
    evidence: Dict[str, str] = Field(default_factory=dict)
    retain_until: Optional[str] = None


class SecurityEventsResponse(_CamelModel):
    """A lane's security events."""

    events: List[SecurityEventBody] = Field(description="Most recent first.")
    observed: bool = Field(
        default=False, description="False: none of these were observed in a request path."
    )
    sentence: str = Field(default=_NO_OBSERVATION_SENTENCE)


class AuditEntryBody(_CamelModel):
    """One append-only audit entry."""

    id: str
    at: Optional[str] = None
    actor_name: str = ""
    actor_kind: str = ""
    subject_kind: str = ""
    subject_id: Optional[str] = None
    summary: str = ""
    detail: Optional[str] = None


class AuditResponse(_CamelModel):
    """A lane's security audit trail."""

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
            cross-tenant probe must not be able to confirm the lane exists, and on a security
            surface that probe is the reconnaissance step.
    """
    environment = get_environment(db, tenant_id=tenant_id, environment_id=environment_id)
    if not environment:
        raise HTTPException(
            status_code=404,
            detail={"code": "environment_not_found", "message": "Environment not found."},
        )
    return environment


def _refusal_http(error: SlateSecurityRefusedError) -> HTTPException:
    """Map a security refusal to a 409 carrying its named reason and sentence."""
    return HTTPException(
        status_code=409,
        detail={
            "code": error.refusal.reason,
            "message": error.refusal.sentence,
            "reason": error.refusal.reason,
        },
    )


def _conflict_http(error: SlateSecurityPolicyConflictError) -> HTTPException:
    """Map a lost update to the ``policy-version-conflict`` refusal."""
    refusal = SecurityRefusal.of("policy-version-conflict")
    return HTTPException(
        status_code=409,
        detail={
            "code": refusal.reason,
            "message": refusal.sentence,
            "reason": refusal.reason,
            "actualPolicyVersion": error.actual_policy_version,
        },
    )


def _not_found_http(error: SlateSecurityStoreError) -> HTTPException:
    """Map a missing row to a 404 carrying the store's machine-readable code."""
    return HTTPException(status_code=404, detail={"code": error.code, "message": str(error)})


def _actor(auth_data: Mapping[str, Any]) -> tuple[Optional[str], str]:
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
    """The immutable identity dual control compares.

    V188 compares ``author_actor_key`` and ``approver_actor_key`` rather than the nullable user
    ids, because those are ``ON DELETE SET NULL`` and a genuine two-person approval must not
    become two indistinguishable NULLs when somebody is offboarded. This is the value that goes
    into those columns.

    Args:
        auth_data: The auth dict from the dependency.

    Returns:
        A stable identity string, preferring the user id and falling back to the email.
    """
    return str(
        get_authenticated_user_id(auth_data) or auth_data.get("email") or "unknown"
    )


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp as ISO-8601, tolerating a string that already is one."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_moment(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, treating an unparseable one as absent.

    Args:
        value: The timestamp, or None.

    Returns:
        The parsed datetime, or None. For an exception that means a missing expiry, which
        :func:`evaluate_exception_safety` has already refused — so this fails toward the safe
        answer rather than toward a carve-out that never lapses.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _warning_bodies(warnings: Any) -> List[SecurityWarningBody]:
    """Map planner warnings onto their wire model."""
    bodies: List[SecurityWarningBody] = []
    for warning in warnings:
        if isinstance(warning, Mapping):
            bodies.append(
                SecurityWarningBody(
                    code=str(warning.get("code") or ""),
                    message=str(warning.get("message") or ""),
                    field=str(warning.get("field") or ""),
                )
            )
        else:
            bodies.append(
                SecurityWarningBody(
                    code=warning.code, message=warning.message, field=warning.field or ""
                )
            )
    return bodies


def _rule_body(row: Mapping[str, Any]) -> SecurityRuleBody:
    """Map a rule row onto its wire model."""
    return SecurityRuleBody(
        id=str(row["id"]) if row.get("id") else None,
        ordinal=int(row.get("ordinal") or 0),
        enabled=bool(row.get("enabled", True)),
        label=str(row.get("label") or ""),
        matcher_kind=str(row.get("matcher_kind") or "prefix"),
        matcher_value=str(row.get("matcher_value") or "/"),
        matcher_methods=list(row.get("matcher_methods") or []),
        matcher_hosts=list(row.get("matcher_hosts") or []),
        conditions=list(row.get("conditions") or []),
        action=str(row.get("action") or "log"),
        rate_requests=row.get("rate_requests"),
        rate_window_seconds=row.get("rate_window_seconds"),
        rollout_mode=str(row.get("rollout_mode") or "simulate"),
        rollout_percent=int(row.get("rollout_percent") or 0),
        expires_at=_iso(row.get("expires_at")),
        acknowledged_warnings=list(row.get("acknowledged_warnings") or []),
        body_digest=str(row.get("body_digest") or ""),
        revision=int(row.get("revision") or 1),
    )


def _exception_body(row: Mapping[str, Any]) -> SecurityExceptionBody:
    """Map an exception row onto its wire model."""
    return SecurityExceptionBody(
        id=str(row["id"]) if row.get("id") else None,
        subject_kind=str(row.get("subject_kind") or "policy"),
        subject_ref=str(row.get("subject_ref") or ""),
        matcher_kind=str(row.get("matcher_kind") or "prefix"),
        matcher_value=str(row.get("matcher_value") or ""),
        expires_at=_iso(row.get("expires_at")),
        reason=str(row.get("reason") or ""),
        actor_name=str(row.get("actor_name") or ""),
    )


def _group_bodies(overrides: Any) -> List[ManagedGroupBody]:
    """Render the catalog with this lane's deviations attached.

    Args:
        overrides: Rows from ``slate_security_managed_groups``.

    Returns:
        Every catalog group in catalog order. A group with no override carries ``mode = None``,
        which says "as shipped" rather than restating the default as though somebody had chosen
        it.
    """
    by_id = {str(row.get("group_id") or ""): row for row in overrides}
    bodies: List[ManagedGroupBody] = []
    for group in MANAGED_GROUPS.values():
        override = by_id.get(group.id)
        bodies.append(
            ManagedGroupBody(
                id=group.id,
                title=group.title,
                description=group.description,
                default_mode=group.default_mode,
                false_positive_risk=group.false_positive_risk,
                expected_impact=group.expected_impact,
                mode=None if override is None else str(override.get("mode") or ""),
                reason=None if override is None else override.get("reason"),
            )
        )
    return bodies


def _policy_for(tenant_id: str, environment: Mapping[str, Any], actor: tuple) -> Dict[str, Any]:
    """Load or create the lane's security policy."""
    actor_id, actor_name = actor
    return ensure_policy(
        db,
        tenant_id=tenant_id,
        site_id=str(environment["site_id"]),
        environment_id=str(environment["id"]),
        actor_id=actor_id,
        actor_name=actor_name,
    )


def _audit(
    *,
    tenant_id: str,
    environment_id: str,
    actor: tuple,
    subject_kind: str,
    subject_id: Optional[str],
    summary: str,
    detail: Optional[str] = None,
) -> None:
    """Append one audit entry, with the actor already resolved."""
    actor_id, actor_name = actor
    append_audit(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_kind="user",
        subject_kind=subject_kind,
        subject_id=subject_id,
        summary=summary,
        detail=detail,
    )


def _csv_cell(value: Any) -> str:
    """Neutralize a CSV cell that a spreadsheet would evaluate as a formula.

    An actor display name, a refusal detail and an audit summary are all attacker-influenced text,
    and a cell beginning ``=``, ``+``, ``-``, ``@``, a tab or a carriage return is executed by
    Excel, Numbers and Sheets when the export is opened. Prefixing with an apostrophe makes the
    cell literal. ``access_routes.py``'s exporter does not do this; this one does, and the
    difference is whether reading compliance evidence can run code.

    Args:
        value: The cell value.

    Returns:
        The value as text, apostrophe-prefixed when it would otherwise be interpreted.
    """
    text = "" if value is None else str(value)
    if text[:1] in _CSV_INJECTION_PREFIXES:
        return "'" + text
    return text


# ─── Catalog routes ──────────────────────────────────────────────────────────


@router.get(
    "/security/presets", response_model=SecurityPresetsResponse, response_model_by_alias=True
)
async def get_security_presets(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SecurityPresetsResponse:
    """Return every managed tier and safe preset as data.

    A preset is its fields, not its name. "Aggressive" is not a mood the system interprets at
    request time, and an operator choosing it is entitled to read what it will do to their
    readers before they choose — which is why ``expectedImpact`` is a required field on all three
    families rather than documentation somewhere else.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return SecurityPresetsResponse(
        managed_rulesets=[
            ManagedRulesetBody(
                key=tier.key,
                label=tier.label,
                intent=tier.intent,
                expected_impact=tier.expected_impact,
                groups=list(tier.groups),
                group_modes=dict(tier.group_modes),
                requires_reason=tier.requires_reason,
                unsafe_if=list(tier.unsafe_if),
            )
            for tier in MANAGED_RULESETS.values()
        ],
        bot_presets=[
            BotPresetBody(
                key=preset.key,
                label=preset.label,
                intent=preset.intent,
                expected_impact=preset.expected_impact,
                verified_bots=preset.verified_bots,
                likely_automated=preset.likely_automated,
                automated=preset.automated,
                unsafe_if=list(preset.unsafe_if),
            )
            for preset in BOT_PRESETS.values()
        ],
        rate_presets=[
            RatePresetBody(
                key=preset.key,
                label=preset.label,
                intent=preset.intent,
                expected_impact=preset.expected_impact,
                requests=preset.requests,
                window_seconds=preset.window_seconds,
                action=preset.action,
                unsafe_if=list(preset.unsafe_if),
            )
            for preset in RATE_PRESETS.values()
        ],
    )


@router.get(
    "/security/managed-groups",
    response_model=ManagedGroupsResponse,
    response_model_by_alias=True,
)
async def get_managed_group_catalog(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ManagedGroupsResponse:
    """Return the curated WAF group catalog.

    Each group states its false-positive risk and what it will break. A group that cannot say what
    it will break is a group nobody can safely enable, so the catalog is the answer rather than a
    list of names.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return ManagedGroupsResponse(groups=_group_bodies([]))


# ─── Policy routes ───────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/security",
    response_model=SecurityPolicyResponse,
    response_model_by_alias=True,
)
async def get_security_policy(
    environment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SecurityPolicyResponse:
    """Return a lane's security policy, its rules and carve-outs, and what it actually enforces."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    policy = _policy_for(tenant_id, environment, _actor(auth_data))

    rules = list_rules(db, tenant_id=tenant_id, environment_id=environment_id)
    overrides = list_managed_groups(db, tenant_id=tenant_id, environment_id=environment_id)
    exceptions = list_exceptions(db, tenant_id=tenant_id, environment_id=environment_id)

    return SecurityPolicyResponse(
        environment_id=environment_id,
        managed_ruleset=str(policy.get("managed_ruleset") or "core"),
        bot_preset=str(policy.get("bot_preset") or "balanced"),
        rate_preset=str(policy.get("rate_preset") or "standard"),
        challenge_mode=str(policy.get("challenge_mode") or "managed"),
        preset_overrides=dict(policy.get("preset_overrides") or {}),
        managed_off_reason=policy.get("managed_off_reason"),
        policy_version=int(policy.get("policy_version") or 0),
        edge_attached=bool(policy.get("edge_attached")),
        edge_provider=policy.get("edge_provider"),
        groups=_group_bodies(overrides),
        rules=[_rule_body(rule) for rule in rules],
        exceptions=[_exception_body(row) for row in exceptions],
        rules_digest=rules_digest(rules),
        updated_at=_iso(policy.get("updated_at")),
        updated_by=policy.get("updated_by_actor_name"),
    )


@router.put(
    "/environments/{environment_id}/security/presets",
    response_model=SetPresetsResponse,
    response_model_by_alias=True,
)
async def set_security_presets(
    environment_id: str,
    request: SetPresetsRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SetPresetsResponse:
    """Change a lane's managed tier and its bot, rate and challenge settings.

    Turning the managed ruleset off with no stated reason is refused here with a sentence, and
    again by V188's CHECK. Both are deliberate: the operator should meet the explanation, not a
    constraint violation, and no future code path should be able to skip the explanation.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    candidate = {
        "managed_ruleset": request.managed_ruleset,
        "bot_preset": request.bot_preset,
        "rate_preset": request.rate_preset,
        "challenge_mode": request.challenge_mode,
        "preset_overrides": request.overrides,
        "managed_off_reason": request.managed_off_reason,
    }
    try:
        warnings = evaluate_policy_safety(candidate)
    except SlateSecurityRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="policy",
                subject_id=None,
                summary="Security preset change refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return SetPresetsResponse(
            applied=False,
            dry_run=True,
            managed_ruleset=request.managed_ruleset,
            bot_preset=request.bot_preset,
            rate_preset=request.rate_preset,
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        updated = set_presets(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            managed_ruleset=request.managed_ruleset,
            bot_preset=request.bot_preset,
            rate_preset=request.rate_preset,
            challenge_mode=request.challenge_mode,
            preset_overrides=request.overrides,
            managed_off_reason=request.managed_off_reason,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateSecurityStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="policy",
        subject_id=None,
        summary=(
            f"Security presets set to {request.managed_ruleset}/{request.bot_preset}/"
            f"{request.rate_preset}"
        ),
        detail=request.reason or request.managed_off_reason or None,
    )

    return SetPresetsResponse(
        applied=True,
        dry_run=False,
        managed_ruleset=str(updated.get("managed_ruleset") or request.managed_ruleset),
        bot_preset=str(updated.get("bot_preset") or request.bot_preset),
        rate_preset=str(updated.get("rate_preset") or request.rate_preset),
        policy_version=int(updated.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.put(
    "/environments/{environment_id}/security/managed-groups/{group_id}",
    response_model=SetManagedGroupResponse,
    response_model_by_alias=True,
)
async def set_security_managed_group(
    environment_id: str,
    group_id: str,
    request: SetManagedGroupRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SetManagedGroupResponse:
    """Move one managed WAF group off, or back onto, its catalog default.

    ``off`` and ``log`` are the directions that remove protection, so both require a stated
    reason — refused here as ``managed-off-without-reason`` and again by V188's
    ``mode NOT IN ('off','log') OR reason IS NOT NULL``.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    if group_id not in MANAGED_GROUPS:
        raise HTTPException(
            status_code=404,
            detail={"code": "group_not_found", "message": f"Unknown managed group {group_id}."},
        )

    if request.mode in ("off", "log") and not str(request.reason or "").strip():
        refusal = SlateSecurityRefusedError(SecurityRefusal.of("managed-off-without-reason"))
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="managed-group",
                subject_id=group_id,
                summary="Managed group change refused",
                detail=f"{refusal.refusal.reason}: {refusal.refusal.sentence}",
            )
        raise _refusal_http(refusal)

    if request.dry_run:
        return SetManagedGroupResponse(
            applied=False,
            dry_run=True,
            group=_group_bodies([{"group_id": group_id, "mode": request.mode,
                                  "reason": request.reason}])[
                list(MANAGED_GROUPS).index(group_id)
            ],
            policy_version=int(policy.get("policy_version") or 0),
        )

    try:
        written = set_managed_group(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            group_id=group_id,
            mode=request.mode,
            reason=request.reason,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="managed-group",
        subject_id=group_id,
        summary=f"Managed group {group_id} set to {request.mode}",
        detail=request.reason,
    )

    refreshed = _policy_for(tenant_id, environment, actor)
    return SetManagedGroupResponse(
        applied=True,
        dry_run=False,
        group=_group_bodies([written or {"group_id": group_id, "mode": request.mode}])[
            list(MANAGED_GROUPS).index(group_id)
        ],
        policy_version=int(refreshed.get("policy_version") or 0),
    )


# ─── Rule routes ─────────────────────────────────────────────────────────────


def _rule_columns(candidate: Mapping[str, Any], digest: str) -> Dict[str, Any]:
    """Reduce a validated rule body to the V188 columns a write sets.

    Args:
        candidate: The rule body as submitted, already normalized.
        digest: The content digest of its decisive fields.

    Returns:
        Column values. ``expires_at`` is parsed here rather than in the store so the store never
        has to decide what an unparseable timestamp means.
    """
    normalized = normalize_rule(candidate)
    return {
        "ordinal": normalized["ordinal"],
        "enabled": normalized["enabled"],
        "label": normalized["label"],
        "matcher_kind": normalized["matcher_kind"],
        "matcher_value": normalized["matcher_value"],
        "matcher_methods": normalized["matcher_methods"],
        "matcher_hosts": normalized["matcher_hosts"],
        "action": normalized["action"],
        "rate_requests": normalized["rate_requests"],
        "rate_window_seconds": normalized["rate_window_seconds"],
        "rollout_mode": normalized["rollout_mode"],
        "rollout_percent": normalized["rollout_percent"],
        "expires_at": _parse_moment(
            normalized["expires_at"] if isinstance(normalized["expires_at"], str) else None
        )
        or (normalized["expires_at"] if isinstance(normalized["expires_at"], datetime) else None),
        "acknowledged_warnings": normalized["acknowledged_warnings"],
        "body_digest": digest,
    }


def _evaluation_candidate(
    *,
    tenant_id: str,
    environment_id: str,
    rule_id: Optional[str],
    body: Mapping[str, Any],
    auth_data: Mapping[str, Any],
) -> tuple[Dict[str, Any], str]:
    """Assemble the body :func:`evaluate_security_safety` judges, with its history attached.

    Three of the fields that decide a refusal are not in the request and must not be: the author's
    identity, the approvals on file, and whether this rule has ever run in simulate. A client able
    to assert any of them could promote a blocking rule to enforcing without review. So all three
    are resolved here from the authenticated caller and from the database.

    Args:
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: The rule being replaced, or None for a create.
        body: The submitted rule fields.
        auth_data: The auth dict.

    Returns:
        The candidate body, and the digest of its decisive fields — which is what an approval must
        name and what the write records.
    """
    candidate = dict(body)
    candidate["id"] = rule_id or ""
    candidate["author_actor_key"] = _actor_key(auth_data)

    history = rule_evaluation_context(
        db, tenant_id=tenant_id, environment_id=environment_id, rule_id=rule_id
    )
    candidate["simulated_at"] = history["simulated_at"]
    candidate["previous_rollout_percent"] = history["previous_rollout_percent"]

    digest = body_digest(candidate)
    # An edit to an existing rule looks up approvals by subject, so an approval of the *previous*
    # body is found and reported as approval-stale rather than as no approval at all — the two
    # need different actions from the operator. A create has no subject yet, so the digest is the
    # only handle there is.
    if rule_id:
        approvals = list_approvals(
            db, tenant_id=tenant_id, environment_id=environment_id, subject_id=rule_id
        )
    else:
        approvals = list_approvals(
            db, tenant_id=tenant_id, environment_id=environment_id, digest=digest
        )
    candidate["approvals"] = approvals
    return candidate, digest


def _write_rule(
    *,
    environment_id: str,
    rule_id: Optional[str],
    request: WriteRuleRequest,
    auth_data: Mapping[str, Any],
) -> WriteRuleResponse:
    """Shared body of rule create and rule replace.

    Both verbs run the same gates in the same order, so they live in one function rather than two
    that could drift — and on a security surface a drift between create and replace would be a
    rule that could be introduced unsafely by whichever verb had the weaker check.

    Args:
        environment_id: The lane.
        rule_id: Existing rule to replace, or None to create.
        request: The rule body.
        auth_data: The auth dict.

    Returns:
        The write outcome.

    Raises:
        HTTPException: 409 on a refusal or a lost update; 404 when the rule is not on the lane.
    """
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    candidate, digest = _evaluation_candidate(
        tenant_id=tenant_id,
        environment_id=environment_id,
        rule_id=rule_id,
        body=request.model_dump(),
        auth_data=auth_data,
    )
    siblings = list_rules(db, tenant_id=tenant_id, environment_id=environment_id)

    try:
        warnings = evaluate_security_safety(candidate, siblings=siblings, policy=policy)
    except SlateSecurityRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="rule",
                subject_id=rule_id,
                summary="Security rule refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteRuleResponse(
            applied=False,
            dry_run=True,
            rule=_rule_body({**candidate, "body_digest": digest}),
            body_digest=digest,
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        written = upsert_rule(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            rule_id=rule_id,
            values=_rule_columns(candidate, digest),
            conditions=request.conditions,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateSecurityStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="rule",
        subject_id=str(written.get("id")) if written.get("id") else rule_id,
        summary=f"Security rule {'updated' if rule_id else 'created'}: {request.label}",
        detail=request.reason or None,
    )

    refreshed = _policy_for(tenant_id, environment, actor)
    return WriteRuleResponse(
        applied=True,
        dry_run=False,
        rule=_rule_body(written),
        body_digest=digest,
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/security/rules",
    response_model=WriteRuleResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_security_rule(
    environment_id: str,
    request: WriteRuleRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteRuleResponse:
    """Create a custom security rule, refusing an unsafe variant by name."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_rule(
        environment_id=environment_id, rule_id=None, request=request, auth_data=auth_data
    )


@router.put(
    "/environments/{environment_id}/security/rules/{rule_id}",
    response_model=WriteRuleResponse,
    response_model_by_alias=True,
)
async def replace_security_rule(
    environment_id: str,
    rule_id: str,
    request: WriteRuleRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteRuleResponse:
    """Replace a custom security rule, running the same gates as a create."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_rule(
        environment_id=environment_id, rule_id=rule_id, request=request, auth_data=auth_data
    )


@router.delete(
    "/environments/{environment_id}/security/rules/{rule_id}",
    response_model=DeleteRuleResponse,
    response_model_by_alias=True,
)
async def remove_security_rule(
    environment_id: str,
    rule_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteRuleResponse:
    """Remove a custom security rule, keeping its body so the removal can be undone."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    if dry_run:
        return DeleteRuleResponse(
            deleted=False, dry_run=True, policy_version=int(policy.get("policy_version") or 0)
        )

    try:
        delete_rule(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            rule_id=rule_id,
            expected_policy_version=expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateSecurityStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="rule",
        subject_id=rule_id,
        summary="Security rule removed",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, actor)
    return DeleteRuleResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed.get("policy_version") or 0)
    )


@router.post(
    "/environments/{environment_id}/security/rules/{rule_id}/rollout",
    response_model=WriteRuleResponse,
    response_model_by_alias=True,
)
async def set_security_rule_rollout(
    environment_id: str,
    rule_id: str,
    request: RolloutRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteRuleResponse:
    """Advance or retreat a rule's staged rollout.

    This is where dual control actually bites. A rule can be written in simulate freely; the write
    that makes an enforcing ``block`` rule real runs the same
    :func:`app.slate_security.evaluate_security_safety` gate as a body edit, so it is refused as
    ``enforce-without-simulation``, ``enforce-without-approval``, ``approval-stale`` or
    ``approval-self`` rather than succeeding because it happened to arrive by a different route.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    existing = get_rule(
        db, tenant_id=tenant_id, environment_id=environment_id, rule_id=rule_id
    )
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "rule_not_found", "message": f"Security rule {rule_id} not found."},
        )

    merged = {
        **existing,
        "rollout_mode": request.rollout_mode,
        "rollout_percent": request.rollout_percent,
    }
    candidate, digest = _evaluation_candidate(
        tenant_id=tenant_id,
        environment_id=environment_id,
        rule_id=rule_id,
        body=merged,
        auth_data=auth_data,
    )
    siblings = list_rules(db, tenant_id=tenant_id, environment_id=environment_id)

    try:
        warnings = evaluate_security_safety(candidate, siblings=siblings, policy=policy)
    except SlateSecurityRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="rule",
                subject_id=rule_id,
                summary="Security rule rollout refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteRuleResponse(
            applied=False,
            dry_run=True,
            rule=_rule_body(merged),
            body_digest=digest,
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        written = set_rollout(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            rule_id=rule_id,
            rollout_mode=request.rollout_mode,
            rollout_percent=request.rollout_percent,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateSecurityStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="rule",
        subject_id=rule_id,
        summary=(
            f"Security rule rollout set to {request.rollout_mode} at "
            f"{request.rollout_percent}%"
        ),
        detail=request.reason or None,
    )

    refreshed = _policy_for(tenant_id, environment, actor)
    return WriteRuleResponse(
        applied=True,
        dry_run=False,
        rule=_rule_body(written),
        body_digest=digest,
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/security/rules/{rule_id}/revert",
    response_model=WriteRuleResponse,
    response_model_by_alias=True,
)
async def revert_security_rule(
    environment_id: str,
    rule_id: str,
    request: RevertRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteRuleResponse:
    """Restore a rule to a stored revision.

    Reverting applies the recorded document rather than reconstructing intent from an audit
    sentence, which is what makes §29.4's "every rule change can be reverted" a fact about this
    system rather than a claim about it.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    if request.dry_run:
        return WriteRuleResponse(
            applied=False,
            dry_run=True,
            rule=None,
            body_digest="",
            policy_version=int(policy.get("policy_version") or 0),
        )

    try:
        written = revert_rule(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            rule_id=rule_id,
            revision=request.revision,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateSecurityStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="revert",
        subject_id=rule_id,
        summary=f"Security rule reverted to revision {request.revision}",
        detail=request.reason or None,
    )

    refreshed = _policy_for(tenant_id, environment, actor)
    return WriteRuleResponse(
        applied=True,
        dry_run=False,
        rule=_rule_body(written),
        body_digest=str(written.get("body_digest") or ""),
        policy_version=int(refreshed.get("policy_version") or 0),
    )


@router.get(
    "/environments/{environment_id}/security/rules/{rule_id}/revisions",
    response_model=RevisionsResponse,
    response_model_by_alias=True,
)
async def get_security_rule_revisions(
    environment_id: str,
    rule_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> RevisionsResponse:
    """Return a rule's revision history, newest first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_revisions(db, tenant_id=tenant_id, rule_id=rule_id, limit=limit)
    return RevisionsResponse(
        revisions=[
            RevisionBody(
                id=str(row["id"]),
                revision=int(row.get("revision") or 1),
                change_kind=str(row.get("change_kind") or ""),
                body_digest=str(row.get("body_digest") or ""),
                at=_iso(row.get("at")),
                actor_name=str(row.get("actor_name") or ""),
                body=dict(row.get("body") or {}),
            )
            for row in rows
        ]
    )


# ─── Exceptions and approvals ────────────────────────────────────────────────


@router.post(
    "/environments/{environment_id}/security/exceptions",
    response_model=ExceptionResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_security_exception(
    environment_id: str,
    request: CreateExceptionRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ExceptionResponse:
    """Open a scoped, expiring carve-out.

    An exception is a hole. §29.4 wants them possible; keeping them scoped and bounded is what
    stops them becoming the policy, so an unbounded or over-long carve-out is refused with no
    acknowledgement path.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)
    now = datetime.now(timezone.utc)

    candidate = {
        "subject_kind": request.subject_kind,
        "subject_ref": request.subject_ref,
        "matcher_kind": request.matcher_kind,
        "matcher_value": request.matcher_value,
        "expires_at": request.expires_at,
        "reason": request.reason,
    }
    try:
        warnings = evaluate_exception_safety(candidate, now=now)
    except SlateSecurityRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="exception",
                subject_id=None,
                summary="Security exception refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return ExceptionResponse(
            applied=False,
            dry_run=True,
            exception=_exception_body(candidate),
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    expires_at = _parse_moment(request.expires_at)
    if expires_at is None:
        # evaluate_exception_safety has already refused an absent or unparseable expiry; reaching
        # here would mean the two disagreed, and the safe reading is the one that refuses.
        raise _refusal_http(
            SlateSecurityRefusedError(SecurityRefusal.of("exception-unbounded"))
        )

    try:
        written = create_exception(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            subject_kind=request.subject_kind,
            subject_ref=request.subject_ref,
            matcher_kind=request.matcher_kind,
            matcher_value=request.matcher_value,
            expires_at=expires_at,
            reason=request.reason,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="exception",
        subject_id=str(written.get("id")) if written.get("id") else None,
        summary=(
            f"Security exception opened on {request.subject_kind} "
            f"{request.subject_ref or '(lane)'}"
        ),
        detail=f"{request.matcher_kind} {request.matcher_value} until {request.expires_at}: "
        f"{request.reason}",
    )

    refreshed = _policy_for(tenant_id, environment, actor)
    return ExceptionResponse(
        applied=True,
        dry_run=False,
        exception=_exception_body(written),
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.delete(
    "/environments/{environment_id}/security/exceptions/{exception_id}",
    response_model=DeleteExceptionResponse,
    response_model_by_alias=True,
)
async def remove_security_exception(
    environment_id: str,
    exception_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteExceptionResponse:
    """Close a carve-out early."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    if dry_run:
        return DeleteExceptionResponse(
            deleted=False, dry_run=True, policy_version=int(policy.get("policy_version") or 0)
        )

    try:
        delete_exception(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            exception_id=exception_id,
            expected_policy_version=expected_policy_version,
        )
    except SlateSecurityPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateSecurityStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="exception",
        subject_id=exception_id,
        summary="Security exception closed",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, actor)
    return DeleteExceptionResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed.get("policy_version") or 0)
    )


@router.post(
    "/environments/{environment_id}/security/approvals",
    response_model=ApprovalBody,
    response_model_by_alias=True,
    status_code=201,
)
async def record_security_approval(
    environment_id: str,
    request: ApprovalRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ApprovalBody:
    """Record the approving half of dual control.

    The approver is always the *authenticated caller* — there is no field by which one person can
    record somebody else's approval, which is the only version of two-person review that means
    anything. Approving one's own change is refused here as ``approval-self`` and again by V188's
    ``CHECK (approver_actor_key <> author_actor_key)``.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    approver_key = _actor_key(auth_data)

    if approver_key == request.author_actor_key:
        raise _refusal_http(SlateSecurityRefusedError(SecurityRefusal.of("approval-self")))

    written = record_approval(
        db,
        tenant_id=tenant_id,
        environment_id=str(environment["id"]),
        subject_kind=request.subject_kind,
        subject_id=request.subject_id,
        digest=request.digest,
        author_actor_id=None,
        author_actor_name=request.author_actor_name or request.author_actor_key,
        author_actor_key=request.author_actor_key,
        approver_actor_id=actor[0],
        approver_actor_name=actor[1],
        approver_actor_key=approver_key,
        note=request.note,
    )

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="approval",
        subject_id=request.subject_id,
        summary=f"Approved {request.subject_kind} {request.subject_id}",
        detail=request.digest,
    )

    return ApprovalBody(
        id=str(written.get("id") or ""),
        subject_kind=str(written.get("subject_kind") or request.subject_kind),
        subject_id=str(written.get("subject_id") or request.subject_id),
        digest=str(written.get("digest") or request.digest),
        author_actor_name=str(written.get("author_actor_name") or request.author_actor_name),
        approver_actor_name=str(written.get("approver_actor_name") or actor[1]),
        approved_at=_iso(written.get("approved_at")),
        note=written.get("note"),
    )


# ─── Simulation ──────────────────────────────────────────────────────────────


@router.post(
    "/environments/{environment_id}/security/simulate",
    response_model=SimulateResponse,
    response_model_by_alias=True,
)
async def simulate_security_request(
    environment_id: str,
    request: SimulateCommandBody,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SimulateResponse:
    """Explain what this lane's policy decides for a test request, and why every rule lost.

    A read, not a write, unless ``persist`` is set. "Which rule blocked this customer" is the
    question that brings an operator here during an incident, so requiring PUBLISH would put the
    answer out of reach of exactly the person asking.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, actor)

    if request.rules is not None:
        rules: List[Dict[str, Any]] = [rule.model_dump() for rule in request.rules]
    else:
        rules = list_rules(db, tenant_id=tenant_id, environment_id=environment_id)

    overrides = list_managed_groups(db, tenant_id=tenant_id, environment_id=environment_id)
    exceptions = list_exceptions(db, tenant_id=tenant_id, environment_id=environment_id)

    verdict = simulate_request(
        request=SimulationRequest(
            method=request.request.method,
            host=request.request.host,
            path=request.request.path,
            query=request.request.query,
            signals=tuple(request.request.signals),
            bot_class=request.request.bot_class,
            burst_requests=request.request.burst_requests,
            country=request.request.country,
            asn=request.request.asn,
            headers=request.request.headers,
        ),
        policy=policy,
        managed_groups=overrides,
        rules=rules,
        exceptions=exceptions,
        now=datetime.now(timezone.utc),
    )

    event_id: Optional[str] = None
    if request.persist:
        basis_release_id = environment.get("active_release_id")
        written = record_event(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            rule_kind=(
                verdict.winning_rule_kind
                if verdict.winning_rule_kind in ("managed-group", "rule", "bot-preset",
                                                 "rate-preset")
                else "rule"
            ),
            rule_ref=str(verdict.winning_rule_ref or "default"),
            rule_label=verdict.winning_rule_label,
            route=request.request.path,
            method=request.request.method.upper(),
            release_id=str(basis_release_id) if basis_release_id else None,
            region=None,
            action=verdict.action,
            # Raw request data goes in; the store redacts. A caller cannot pass redacted evidence
            # and a caller cannot skip the redaction, because there is no other way in.
            evidence={
                "method": request.request.method.upper(),
                "path": request.request.path,
                "query": ";".join(sorted(request.request.query)),
                "userAgent": request.request.headers.get("user-agent", ""),
                "country": request.request.country,
                "asn": request.request.asn,
                "botClass": request.request.bot_class,
                **request.request.headers,
            },
        )
        event_id = str(written.get("id")) if written.get("id") else None

    return SimulateResponse(
        action=verdict.action,
        action_reason=verdict.action_reason,
        winning_rule_kind=verdict.winning_rule_kind,
        winning_rule_ref=verdict.winning_rule_ref,
        winning_rule_label=verdict.winning_rule_label,
        rollout_mode=verdict.rollout_mode,
        exception_applied=verdict.exception_applied,
        considered=[
            SimulationStepBody(
                kind=str(step.get("kind") or ""),
                ref=step.get("ref"),
                label=str(step.get("label") or ""),
                ordinal=step.get("ordinal"),
                outcome=str(step.get("outcome") or ""),
                action=step.get("action"),
                reason=str(step.get("reason") or ""),
            )
            for step in verdict.considered
        ],
        warnings=_warning_bodies(verdict.warnings),
        rules_digest=verdict.rules_digest,
        policy_version=int(policy.get("policy_version") or 0),
        event_id=event_id,
    )


# ─── Events ──────────────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/security/events",
    response_model=SecurityEventsResponse,
    response_model_by_alias=True,
)
async def get_security_events(
    environment_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    rule_ref: Optional[str] = Query(default=None, alias="ruleRef"),
    action: Optional[str] = Query(default=None),
    route: Optional[str] = Query(default=None),
    release_id: Optional[str] = Query(default=None, alias="releaseId"),
    region: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SecurityEventsResponse:
    """Return a lane's security events, most recent first.

    The filter names are the designer's dimension ids unchanged, so filtering on screen and
    filtering in a query cannot mean different things.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_events(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        limit=limit,
        rule_ref=rule_ref,
        action=action,
        route=route,
        release_id=release_id,
        region=region,
        source=source,
    )
    return SecurityEventsResponse(events=[_event_body(row) for row in rows])


def _event_body(row: Mapping[str, Any]) -> SecurityEventBody:
    """Map an event row onto its wire model."""
    return SecurityEventBody(
        id=str(row["id"]),
        at=_iso(row.get("at")),
        source=str(row.get("source") or ""),
        rule_kind=str(row.get("rule_kind") or ""),
        rule_ref=str(row.get("rule_ref") or ""),
        rule_label=str(row.get("rule_label") or ""),
        route=str(row.get("route") or ""),
        method=str(row.get("method") or ""),
        release_id=str(row["release_id"]) if row.get("release_id") else None,
        region=row.get("region"),
        action=str(row.get("action") or ""),
        mitigated=bool(row.get("mitigated")),
        edge_attached=bool(row.get("edge_attached")),
        evidence={str(k): str(v) for k, v in (row.get("evidence") or {}).items()},
        retain_until=_iso(row.get("retain_until")),
    )


@router.get(
    "/environments/{environment_id}/security/events/{event_id}",
    response_model=SecurityEventBody,
    response_model_by_alias=True,
)
async def get_security_event(
    environment_id: str,
    event_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SecurityEventBody:
    """Return one security event with its redacted evidence."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    row = get_event(db, tenant_id=tenant_id, environment_id=environment_id, event_id=event_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "event_not_found", "message": f"Security event {event_id} not found."},
        )
    return _event_body(row)


# ─── Audit ───────────────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/security/audit",
    response_model=AuditResponse,
    response_model_by_alias=True,
)
async def get_security_audit(
    environment_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> AuditResponse:
    """Return a lane's append-only security audit trail, most recent first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_audit(db, tenant_id=tenant_id, environment_id=environment_id, limit=limit)
    return AuditResponse(
        entries=[
            AuditEntryBody(
                id=str(row["id"]),
                at=_iso(row.get("at")),
                actor_name=str(row.get("actor_name") or ""),
                actor_kind=str(row.get("actor_kind") or ""),
                subject_kind=str(row.get("subject_kind") or ""),
                subject_id=str(row["subject_id"]) if row.get("subject_id") else None,
                summary=str(row.get("summary") or ""),
                detail=row.get("detail"),
            )
            for row in rows
        ]
    )


@router.get("/environments/{environment_id}/security/audit/export")
async def export_security_audit(
    environment_id: str,
    limit: int = Query(default=10000, ge=1, le=100000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> StreamingResponse:
    """Export a lane's security audit trail as CSV.

    Modelled on ``access_routes.py``'s exporter, and fixing the two defects that precedent
    carries.

    **CSV injection is neutralized.** A cell whose first character is ``=``, ``+``, ``-``, ``@``,
    a tab or a carriage return is prefixed with an apostrophe. An actor display name and a
    refusal detail are attacker-influenced text, and the existing exporter writes them raw, so
    opening the evidence in a spreadsheet is a code-execution path.

    **Nothing is silently truncated.** The existing exporter caps at 1000 rows with no signal,
    which in compliance evidence is a correctness bug rather than a performance choice: an
    auditor reading a truncated ledger concludes the missing entries never happened. This one
    reads one row past the cap, and when there are more it emits a final row saying so in words.

    Reading the evidence is itself audit-worthy — who exported the record of who disabled the WAF
    is part of that record — so an ``export`` audit row is written before the download begins.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)

    # One past the cap, so "there was more" is a fact rather than an inference.
    rows = list_audit(db, tenant_id=tenant_id, environment_id=environment_id, limit=limit + 1)
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="export",
        subject_id=None,
        summary="Security audit exported",
        detail=f"{len(rows)} entries exported; truncated={truncated}",
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["when", "actor", "actorKind", "subjectKind", "subjectId", "summary", "detail"])
    for row in rows:
        writer.writerow(
            [
                _csv_cell(_iso(row.get("at"))),
                _csv_cell(row.get("actor_name")),
                _csv_cell(row.get("actor_kind")),
                _csv_cell(row.get("subject_kind")),
                _csv_cell(row.get("subject_id")),
                _csv_cell(row.get("summary")),
                _csv_cell(row.get("detail")),
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
            "Content-Disposition": (
                f'attachment; filename="{environment_id}-security-audit.csv"'
            )
        },
    )
