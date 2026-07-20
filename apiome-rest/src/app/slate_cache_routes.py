"""Slate Edge cache control REST API — UXE-3.1 (private-suite#2473).

The cache control plane the authoring Cache surface consumes:

* ``GET  /v1/slate/cache/presets``
  — the four presets as data: every TTL, every eligibility, the rationale and what each one
  forbids. The UI prints what this returns rather than holding a second copy of the numbers,
  because two copies would eventually disagree and the screen would be the one that lied.

* ``GET  /v1/slate/environments/{environment_id}/cache``
  — the lane's policy: preset, overrides, expert rules, concurrency token, purge history, and
  an ``enforcement`` block stating plainly that no delivery tier is attached.

* ``PUT  /v1/slate/environments/{environment_id}/cache/preset``
  — change the preset. Bypass without an expiry is refused, by this layer and again by V187.

* ``POST``/``PUT``/``DELETE /v1/slate/environments/{environment_id}/cache/rules[/{rule_id}]``
  — expert rules. Every write runs :func:`app.slate_cache.evaluate_cache_safety` first, so a
  rule that would serve one reader's page to another is refused with a named reason rather
  than stored and discovered later.

* ``POST /v1/slate/environments/{environment_id}/cache/trace``
  — evaluate a test request against the lane's policy and explain the result: eligibility,
  cache key, TTLs, bypass and winning rule, plus every rule that was considered and why it did
  not win.

* ``POST /v1/slate/environments/{environment_id}/cache/purge``
  — estimate a purge's scope, and record it. See the honesty note below.

* ``GET  /v1/slate/environments/{environment_id}/cache/purges`` and ``.../cache/audit``
  — purge history and the append-only audit trail.

Every mutating route accepts ``dryRun``, which runs every gate and returns the plan without
writing, matching the promote/rollback contract in :mod:`app.slate_routes`. That is what lets
the UI show an accurate impact sheet before an operator confirms rather than describing an
action it has not validated. A *refused* action still writes audit — but only when it is not a
dry run, because a rejected preview is not an event.

**What a purge does, stated plainly.** ``deploy/`` is a single Caddyfile with no CDN behind it,
so there is nothing to evict. A purge records who asked, for what scope, with what estimated
blast radius computed from which table, and why. Its ``outcome`` is ``estimated`` or
``recorded``, never ``dispatched``; V187's ``outcome <> 'dispatched' OR edge_attached`` CHECK
makes that a database guarantee. Every purge response carries a ``delivery`` block saying so in
words, and ``GET .../cache`` carries an ``enforcement`` block saying the rules shape no response
headers yet. The delivery tier is APX-3.2; this is the control plane it will report into.

Authorization: reads require VERSIONS/VIEW; preset, rule and purge writes require
VERSIONS/PUBLISH. As in :mod:`app.slate_routes` there is no separate ``cache`` resource,
because changing what production serves *is* a publish action and inventing a permission
dimension the roles matrix does not render would leave it ungrantable in the UI.

Scope misses answer 404 (not 403) so cross-tenant probes cannot confirm a lane exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id
from .database import db
from .permissions import Action, Resource, enforce_permission
from .slate_auth import validate_slate_authentication
from .slate_cache import (
    PRESETS,
    CacheRefusal,
    SlateCacheRefusedError,
    TraceRequest,
    apply_preset,
    evaluate_cache_safety,
    evaluate_trace,
    matches_route,
    normalize_rule,
    plan_purge_scope,
    rules_digest,
)
from .slate_cache_store import (
    SlateCachePolicyConflictError,
    SlateCacheStoreError,
    append_audit,
    delete_rule,
    ensure_policy,
    list_audit,
    list_purges,
    list_rules,
    record_purge,
    record_trace,
    routes_for_host,
    routes_for_release,
    rules_for_tag,
    set_preset,
    upsert_rule,
)
from .slate_deployment_store import get_environment

router = APIRouter(prefix="/v1/slate", tags=["slate-cache"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


#: Stated on every purge response. The endpoint is honest about intent; this is honest about
#: effect, and the two are different things worth saying separately.
_NO_DELIVERY_SENTENCE = (
    "No managed delivery tier is attached to this environment, so nothing was evicted. This "
    "records the purge intent, the scope it would cover, its estimated size and who asked for "
    "it."
)

#: Stated on every policy read, for the same reason.
_NO_ENFORCEMENT_SENTENCE = (
    "These rules are recorded policy. No delivery tier is attached to this environment, so "
    "they do not yet shape response headers."
)


# ─── Request/response models ─────────────────────────────────────────────────


class PresetRuleBody(_CamelModel):
    """One rule a preset contributes, with every field stated."""

    label: str = Field(description="Operator-facing rule name.")
    matcher_kind: str = Field(description="exact, prefix, glob or regex.")
    matcher_value: str = Field(description="The route pattern.")
    eligibility: str = Field(description="cacheable, private or no-store.")
    browser_ttl_seconds: int = Field(description="Browser TTL.")
    edge_ttl_seconds: int = Field(description="Shared-tier TTL.")
    stale_while_revalidate_seconds: int = Field(description="Stale-while-revalidate window.")
    stale_if_error_seconds: int = Field(description="Stale-if-error window.")


class PresetBody(_CamelModel):
    """A preset as data, so the UI never holds a second copy of the numbers."""

    key: str = Field(description="standard, aggressive, bypass or personalized.")
    label: str = Field(description="Operator-facing preset name.")
    intent: str = Field(description="One-line intent, from the roadmap table.")
    rationale: str = Field(description="Why an operator would choose this, and what it costs.")
    requires_expiry: bool = Field(description="Whether the preset must carry an end date.")
    unsafe_if: List[str] = Field(description="What this preset forbids.")
    rules: List[PresetRuleBody] = Field(description="The rules the preset contributes.")


class PresetsResponse(_CamelModel):
    """Every available preset."""

    presets: List[PresetBody] = Field(description="The four presets.")


class CacheRuleBody(_CamelModel):
    """An expert cache rule."""

    id: Optional[str] = Field(default=None, description="Rule id, absent for preset rules.")
    ordinal: int = Field(description="Precedence; lower wins.")
    enabled: bool = Field(default=True, description="Whether the rule participates.")
    label: str = Field(description="Operator-facing rule name.")
    matcher_kind: str = Field(default="prefix", description="exact, prefix, glob or regex.")
    matcher_value: str = Field(default="/", description="The route pattern.")
    matcher_methods: List[str] = Field(default_factory=lambda: ["GET", "HEAD"])
    matcher_hosts: List[str] = Field(default_factory=list)
    eligibility: str = Field(default="cacheable", description="cacheable, private or no-store.")
    browser_ttl_seconds: int = Field(default=0)
    edge_ttl_seconds: int = Field(default=0)
    stale_while_revalidate_seconds: int = Field(default=0)
    stale_if_error_seconds: int = Field(default=0)
    cache_key_base: str = Field(default="host-url")
    vary_query_mode: str = Field(default="none")
    vary_query_keys: List[str] = Field(default_factory=list)
    vary_headers: List[str] = Field(default_factory=list)
    vary_cookies: List[str] = Field(default_factory=list)
    bypass_conditions: List[Dict[str, Any]] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    expires_at: Optional[str] = Field(default=None)
    acknowledged_warnings: List[str] = Field(default_factory=list)


class CacheWarningBody(_CamelModel):
    """A concern that does not block the write."""

    code: str = Field(description="Named warning reason.")
    message: str = Field(description="Operator-facing sentence, rendered verbatim by the UI.")
    field: str = Field(default="", description="Rule field the warning attaches to.")
    severity: Literal["warn", "block"] = Field(
        default="warn", description="warn never blocks; block is returned only on a 409."
    )


class EnforcementBody(_CamelModel):
    """Whether the recorded policy shapes anything on the wire."""

    enforced: bool = Field(description="False until a delivery tier is attached.")
    sentence: str = Field(description="What that means, in words.")


class CachePolicyResponse(_CamelModel):
    """A lane's complete cache policy."""

    environment_id: str = Field(description="The lane.")
    preset: str = Field(description="Active preset.")
    preset_expires_at: Optional[str] = Field(default=None)
    preset_overrides: Dict[str, Any] = Field(default_factory=dict)
    policy_version: int = Field(description="Optimistic-concurrency token.")
    edge_attached: bool = Field(description="Whether a delivery tier serves this lane.")
    edge_provider: Optional[str] = Field(default=None)
    enforcement: EnforcementBody = Field(description="Whether the policy shapes responses.")
    rules: List[CacheRuleBody] = Field(description="Expert rules, in precedence order.")
    preset_rules: List[CacheRuleBody] = Field(
        description="The preset's own rules, which decide where no expert rule matches."
    )
    updated_at: Optional[str] = Field(default=None)
    updated_by: Optional[str] = Field(default=None)


class SetPresetRequest(_CamelModel):
    """Change a lane's preset."""

    preset: str = Field(description="standard, aggressive, bypass or personalized.")
    preset_expires_at: Optional[str] = Field(
        default=None, description="Required for bypass, which is an incident mode."
    )
    overrides: Dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", description="Why the preset changed; recorded in audit.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")


class SetPresetResponse(_CamelModel):
    """The outcome of a preset change."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    preset: str = Field(description="The preset now in effect, or that would be.")
    policy_version: int = Field(description="The version after the change.")
    resolved_rules: List[CacheRuleBody] = Field(description="What the preset resolves to.")
    warnings: List[CacheWarningBody] = Field(default_factory=list)


class WriteRuleRequest(CacheRuleBody):
    """Create or replace an expert rule."""

    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")
    reason: str = Field(default="", description="Why the rule changed; recorded in audit.")


class WriteRuleResponse(_CamelModel):
    """The outcome of a rule write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    rule: Optional[CacheRuleBody] = Field(default=None)
    policy_version: int = Field(description="The version after the write.")
    warnings: List[CacheWarningBody] = Field(default_factory=list)


class DeleteRuleResponse(_CamelModel):
    """The outcome of a rule deletion."""

    deleted: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    policy_version: int = Field(description="The version after the write.")


class TraceRequestBody(_CamelModel):
    """The test request to evaluate."""

    method: str = Field(default="GET")
    host: str = Field(default="")
    path: str = Field(default="/")
    query: Dict[str, str] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)


class TraceCommandBody(_CamelModel):
    """A trace request, optionally over a what-if ruleset."""

    request: TraceRequestBody = Field(description="The test request.")
    rules: Optional[List[CacheRuleBody]] = Field(
        default=None,
        description="What-if overlay. When absent, the lane's stored rules are used.",
    )
    persist: bool = Field(default=False, description="Record the trace as evidence.")


class TraceStepBody(_CamelModel):
    """One rule the trace considered, and what became of it."""

    rule_id: Optional[str] = Field(default=None)
    label: str = Field(description="The rule's name.")
    ordinal: int = Field(description="Its precedence.")
    matched: bool = Field(description="Whether it selected the request.")
    outcome: str = Field(description="matched, skipped or not-reached.")
    reason: str = Field(description="Why, in a sentence.")


class TraceKeyComponentBody(_CamelModel):
    """One contribution to the cache key."""

    source: str = Field(description="host, path, query, header or cookie.")
    name: str = Field(description="The component name.")
    value: str = Field(description="Its value for this request.")
    contributed_because: str = Field(description="Why it is in the key.")


class TraceResponse(_CamelModel):
    """What the policy decides for a test request, and why.

    One field per clause of the acceptance criterion, so a partial answer is impossible.
    """

    eligibility: str = Field(description="cacheable, private or no-store.")
    eligibility_reason: str = Field(description="Why, naming what decided.")
    cache_key: str = Field(description="The resolved cache key.")
    cache_key_components: List[TraceKeyComponentBody] = Field(description="How it was built.")
    browser_ttl_seconds: int = Field(description="Browser TTL.")
    edge_ttl_seconds: int = Field(description="Shared-tier TTL.")
    stale_while_revalidate_seconds: int = Field(description="Stale-while-revalidate window.")
    stale_if_error_seconds: int = Field(description="Stale-if-error window.")
    ttl_source: str = Field(description="Which rule or preset set the TTLs.")
    bypassed: bool = Field(description="Whether a bypass condition fired.")
    bypass_reason: Optional[str] = Field(default=None)
    winning_rule_id: Optional[str] = Field(
        default=None, description="Null when the preset default decided, which is an answer."
    )
    winning_rule_label: str = Field(description="What decided.")
    considered: List[TraceStepBody] = Field(description="Every rule, and why it did not win.")
    warnings: List[CacheWarningBody] = Field(default_factory=list)
    rules_digest: str = Field(description="Determinism receipt over the evaluated ruleset.")
    policy_version: int = Field(description="Which policy generation answered.")
    basis: Literal["policy-evaluation"] = Field(
        default="policy-evaluation",
        description=(
            "This is an evaluation of recorded policy against a test request, not a replay of "
            "an observed edge hit. When a delivery tier lands, 'edge-observed' becomes the "
            "second value of this field rather than a change of meaning for the first."
        ),
    )
    observed: bool = Field(
        default=False, description="False: no delivery tier reported this request."
    )
    trace_id: Optional[str] = Field(default=None, description="Set when the trace was recorded.")
    basis_release_id: Optional[str] = Field(default=None)


class PurgeRequest(_CamelModel):
    """Estimate and record a purge."""

    scope_kind: Literal["release", "tag", "prefix", "host", "url"] = Field(
        description="One of the five roadmap scopes."
    )
    scope_value: str = Field(description="Release id, tag, prefix, host or URL.")
    reason: str = Field(description="Why. Recorded, because a purge must be explicable later.")
    dry_run: bool = Field(default=False, description="Estimate without recording a purge.")
    confirm_estimated_objects: Optional[int] = Field(
        default=None,
        description=(
            "The estimate the operator confirmed. When it disagrees with the server's "
            "recomputed estimate the purge is refused: they approved a different blast radius."
        ),
    )


class DeliveryBody(_CamelModel):
    """Whether anything was actually evicted."""

    dispatched: bool = Field(description="False: no delivery tier is attached.")
    sentence: str = Field(description="What that means, in words.")


class PurgeEstimateBody(_CamelModel):
    """An estimated purge scope and the basis of that estimate."""

    scope_kind: str = Field(description="The scope kind.")
    scope_value: str = Field(description="The scope itself.")
    estimated_objects: int = Field(description="How many objects the scope covers.")
    estimate_basis: str = Field(description="Which table produced the number.")
    sample_routes: List[str] = Field(description="A bounded sample of what is in scope.")
    truncated: bool = Field(description="Whether the sample is shorter than the scope.")
    coverage: str = Field(description="What the basis does and does not include.")


class PurgeResponse(_CamelModel):
    """The outcome of a purge."""

    outcome: str = Field(description="estimated (dry run) or recorded.")
    dry_run: bool = Field(description="Whether this was a preview.")
    estimate: PurgeEstimateBody = Field(description="The scope and its provenance.")
    purge_id: Optional[str] = Field(default=None)
    edge_attached: bool = Field(description="Whether a delivery tier serves this lane.")
    delivery: DeliveryBody = Field(description="Whether anything was evicted.")


class PurgeRecordBody(_CamelModel):
    """One row of purge history."""

    id: str
    at: Optional[str] = None
    actor_name: str = ""
    scope_kind: str = ""
    scope_value: str = ""
    reason: str = ""
    estimated_objects: int = 0
    estimate_basis: str = ""
    sample_routes: List[str] = Field(default_factory=list)
    dry_run: bool = False
    outcome: str = ""
    refusal_reason: Optional[str] = None
    edge_attached: bool = False


class PurgeHistoryResponse(_CamelModel):
    """A lane's purge history."""

    purges: List[PurgeRecordBody] = Field(description="Most recent first.")


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
    """A lane's cache audit trail."""

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
        HTTPException: 404 when the lane does not exist in this tenant. Deliberately not 403:
            a cross-tenant probe must not be able to confirm the lane exists.
    """
    environment = get_environment(db, tenant_id=tenant_id, environment_id=environment_id)
    if not environment:
        raise HTTPException(
            status_code=404,
            detail={"code": "environment_not_found", "message": "Environment not found."},
        )
    return environment


def _refusal_http(error: SlateCacheRefusedError) -> HTTPException:
    """Map a cache refusal to a 409 carrying its named reason and sentence."""
    return HTTPException(
        status_code=409,
        detail={
            "code": error.refusal.reason,
            "message": error.refusal.sentence,
            "reason": error.refusal.reason,
        },
    )


def _conflict_http(error: SlateCachePolicyConflictError) -> HTTPException:
    """Map a lost update to the ``policy-version-conflict`` refusal."""
    refusal = CacheRefusal.of("policy-version-conflict")
    return HTTPException(
        status_code=409,
        detail={
            "code": refusal.reason,
            "message": refusal.sentence,
            "reason": refusal.reason,
            "actualPolicyVersion": error.actual_policy_version,
        },
    )


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


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp as ISO-8601, tolerating a string that already is one."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _rule_body(row: Mapping[str, Any]) -> CacheRuleBody:
    """Map a rule row onto its wire model.

    Args:
        row: A rule row, or a resolved preset rule.

    Returns:
        The wire model, with tags and bypass conditions defaulted rather than absent.
    """
    return CacheRuleBody(
        id=str(row["id"]) if row.get("id") else None,
        ordinal=int(row.get("ordinal") or 0),
        enabled=bool(row.get("enabled", True)),
        label=str(row.get("label") or ""),
        matcher_kind=str(row.get("matcher_kind") or "prefix"),
        matcher_value=str(row.get("matcher_value") or "/"),
        matcher_methods=list(row.get("matcher_methods") or ["GET", "HEAD"]),
        matcher_hosts=list(row.get("matcher_hosts") or []),
        eligibility=str(row.get("eligibility") or "cacheable"),
        browser_ttl_seconds=int(row.get("browser_ttl_seconds") or 0),
        edge_ttl_seconds=int(row.get("edge_ttl_seconds") or 0),
        stale_while_revalidate_seconds=int(row.get("stale_while_revalidate_seconds") or 0),
        stale_if_error_seconds=int(row.get("stale_if_error_seconds") or 0),
        cache_key_base=str(row.get("cache_key_base") or "host-url"),
        vary_query_mode=str(row.get("vary_query_mode") or "none"),
        vary_query_keys=list(row.get("vary_query_keys") or []),
        vary_headers=list(row.get("vary_headers") or []),
        vary_cookies=list(row.get("vary_cookies") or []),
        bypass_conditions=list(row.get("bypass_conditions") or []),
        tags=list(row.get("tags") or []),
        expires_at=_iso(row.get("expires_at")),
        acknowledged_warnings=list(row.get("acknowledged_warnings") or []),
    )


def _warning_bodies(warnings: Any) -> List[CacheWarningBody]:
    """Map planner warnings onto their wire model."""
    bodies: List[CacheWarningBody] = []
    for warning in warnings:
        if isinstance(warning, Mapping):
            bodies.append(
                CacheWarningBody(
                    code=str(warning.get("code") or ""),
                    message=str(warning.get("message") or ""),
                    field=str(warning.get("field") or ""),
                )
            )
        else:
            bodies.append(
                CacheWarningBody(
                    code=warning.code, message=warning.message, field=warning.field or ""
                )
            )
    return bodies


def _policy_for(tenant_id: str, environment: Mapping[str, Any], actor: tuple) -> Dict[str, Any]:
    """Load or create the lane's cache policy."""
    actor_id, actor_name = actor
    return ensure_policy(
        db,
        tenant_id=tenant_id,
        site_id=str(environment["site_id"]),
        environment_id=str(environment["id"]),
        actor_id=actor_id,
        actor_name=actor_name,
    )


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get("/cache/presets", response_model=PresetsResponse, response_model_by_alias=True)
async def get_cache_presets(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> PresetsResponse:
    """Return the four presets as data.

    The UI renders what this returns. A preset whose numbers lived in the client as well as
    here would drift, and the copy that drifted silently would be the one on screen.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return PresetsResponse(
        presets=[
            PresetBody(
                key=preset.key,
                label=preset.label,
                intent=preset.intent,
                rationale=preset.rationale,
                requires_expiry=preset.requires_expiry,
                unsafe_if=list(preset.unsafe_if),
                rules=[
                    PresetRuleBody(
                        label=rule.label,
                        matcher_kind=rule.matcher_kind,
                        matcher_value=rule.matcher_value,
                        eligibility=rule.eligibility,
                        browser_ttl_seconds=rule.browser_ttl_seconds,
                        edge_ttl_seconds=rule.edge_ttl_seconds,
                        stale_while_revalidate_seconds=rule.stale_while_revalidate_seconds,
                        stale_if_error_seconds=rule.stale_if_error_seconds,
                    )
                    for rule in preset.rules
                ],
            )
            for preset in PRESETS.values()
        ]
    )


@router.get(
    "/environments/{environment_id}/cache",
    response_model=CachePolicyResponse,
    response_model_by_alias=True,
)
async def get_cache_policy(
    environment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CachePolicyResponse:
    """Return a lane's cache policy, its expert rules and what it actually enforces."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    policy = _policy_for(tenant_id, environment, _actor(auth_data))

    rules = list_rules(db, tenant_id=tenant_id, environment_id=environment_id)
    preset_key = str(policy["preset"])
    preset_rules = apply_preset(preset_key, policy.get("preset_overrides") or {})

    return CachePolicyResponse(
        environment_id=environment_id,
        preset=preset_key,
        preset_expires_at=_iso(policy.get("preset_expires_at")),
        preset_overrides=dict(policy.get("preset_overrides") or {}),
        policy_version=int(policy["policy_version"]),
        edge_attached=bool(policy.get("edge_attached")),
        edge_provider=policy.get("edge_provider"),
        enforcement=EnforcementBody(
            enforced=bool(policy.get("edge_attached")),
            sentence=(
                "These rules shape responses at the attached delivery tier."
                if policy.get("edge_attached")
                else _NO_ENFORCEMENT_SENTENCE
            ),
        ),
        rules=[_rule_body(rule) for rule in rules],
        preset_rules=[_rule_body(rule) for rule in preset_rules],
        updated_at=_iso(policy.get("updated_at")),
        updated_by=policy.get("updated_by_actor_name"),
    )


@router.put(
    "/environments/{environment_id}/cache/preset",
    response_model=SetPresetResponse,
    response_model_by_alias=True,
)
async def set_cache_preset(
    environment_id: str,
    request: SetPresetRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SetPresetResponse:
    """Change a lane's preset.

    Bypass without an expiry is refused here and again by V187's CHECK, because an incident
    mode that outlives its incident becomes the configuration.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor_id, actor_name = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, (actor_id, actor_name))

    try:
        if request.preset not in PRESETS:
            raise SlateCacheRefusedError(CacheRefusal.of("preset-unknown"))
        if PRESETS[request.preset].requires_expiry and not request.preset_expires_at:
            raise SlateCacheRefusedError(CacheRefusal.of("bypass-without-expiry"))
        resolved = apply_preset(request.preset, request.overrides)
    except SlateCacheRefusedError as exc:
        if not request.dry_run:
            append_audit(
                db,
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_kind="user",
                subject_kind="preset",
                subject_id=None,
                summary="Preset change refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return SetPresetResponse(
            applied=False,
            dry_run=True,
            preset=request.preset,
            policy_version=int(policy["policy_version"]),
            resolved_rules=[_rule_body(rule) for rule in resolved],
            warnings=[],
        )

    try:
        updated = set_preset(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            preset=request.preset,
            preset_expires_at=_parse_moment(request.preset_expires_at),
            overrides=request.overrides,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor_id,
            actor_name=actor_name,
        )
    except SlateCachePolicyConflictError as exc:
        raise _conflict_http(exc) from exc

    append_audit(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_kind="user",
        subject_kind="preset",
        subject_id=None,
        summary=f"Preset set to {request.preset}",
        detail=request.reason or None,
    )

    return SetPresetResponse(
        applied=True,
        dry_run=False,
        preset=request.preset,
        policy_version=int(updated["policy_version"]),
        resolved_rules=[_rule_body(rule) for rule in resolved],
        warnings=[],
    )


def _parse_moment(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, treating an unparseable one as absent.

    Args:
        value: The timestamp, or None.

    Returns:
        The parsed datetime, or None. A bad expiry becoming None means a bypass without an
        expiry, which the caller has already refused — so this fails toward the safe answer.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _write_rule(
    *,
    environment_id: str,
    rule_id: Optional[str],
    request: "WriteRuleRequest",
    auth_data: Mapping[str, Any],
) -> WriteRuleResponse:
    """Shared body of rule create and rule replace.

    Both verbs run the same gates in the same order, so they live in one function rather than
    two that could drift.

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
    actor_id, actor_name = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, (actor_id, actor_name))

    candidate = request.model_dump()
    candidate["id"] = rule_id or ""
    siblings = list_rules(db, tenant_id=tenant_id, environment_id=environment_id)

    try:
        warnings = evaluate_cache_safety(candidate, siblings=siblings)
        _refuse_ordinal_conflict(candidate, siblings, rule_id)
    except SlateCacheRefusedError as exc:
        if not request.dry_run:
            append_audit(
                db,
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_kind="user",
                subject_kind="rule",
                subject_id=rule_id,
                summary="Cache rule refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteRuleResponse(
            applied=False,
            dry_run=True,
            rule=_rule_body(normalize_rule(candidate) | {"tags": request.tags}),
            policy_version=int(policy["policy_version"]),
            warnings=_warning_bodies(warnings),
        )

    values = normalize_rule(candidate)
    values["expires_at"] = _parse_moment(request.expires_at)
    values["bypass_conditions"] = request.bypass_conditions

    try:
        written = upsert_rule(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            rule_id=rule_id,
            values=values,
            tags=request.tags,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor_id,
            actor_name=actor_name,
        )
    except SlateCachePolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateCacheStoreError as exc:
        raise HTTPException(
            status_code=404, detail={"code": exc.code, "message": str(exc)}
        ) from exc

    append_audit(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_kind="user",
        subject_kind="rule",
        subject_id=str(written["id"]),
        summary=f"Cache rule {'updated' if rule_id else 'created'}: {request.label}",
        detail=request.reason or None,
    )

    refreshed = _policy_for(tenant_id, environment, (actor_id, actor_name))
    return WriteRuleResponse(
        applied=True,
        dry_run=False,
        rule=_rule_body(written),
        policy_version=int(refreshed["policy_version"]),
        warnings=_warning_bodies(warnings),
    )


def _refuse_ordinal_conflict(
    candidate: Mapping[str, Any], siblings: Any, rule_id: Optional[str]
) -> None:
    """Refuse a precedence another rule already holds.

    ``UNIQUE (environment_id, ordinal)`` would refuse this at the database anyway, but as an
    integrity error rather than a sentence. Catching it here means the operator is told which
    constraint they hit and why it exists.

    Args:
        candidate: The rule being written.
        siblings: The lane's existing rules.
        rule_id: The rule being replaced, which does not conflict with itself.

    Raises:
        SlateCacheRefusedError: When another rule holds this ordinal.
    """
    ordinal = int(candidate.get("ordinal") or 0)
    for sibling in siblings:
        if rule_id and str(sibling["id"]) == rule_id:
            continue
        if int(sibling["ordinal"]) == ordinal:
            raise SlateCacheRefusedError(CacheRefusal.of("ordinal-conflict"))


@router.post(
    "/environments/{environment_id}/cache/rules",
    response_model=WriteRuleResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_cache_rule(
    environment_id: str,
    request: WriteRuleRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteRuleResponse:
    """Create an expert cache rule, refusing an unsafe variant by name."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_rule(
        environment_id=environment_id, rule_id=None, request=request, auth_data=auth_data
    )


@router.put(
    "/environments/{environment_id}/cache/rules/{rule_id}",
    response_model=WriteRuleResponse,
    response_model_by_alias=True,
)
async def replace_cache_rule(
    environment_id: str,
    rule_id: str,
    request: WriteRuleRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteRuleResponse:
    """Replace an expert cache rule, running the same gates as a create."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_rule(
        environment_id=environment_id, rule_id=rule_id, request=request, auth_data=auth_data
    )


@router.delete(
    "/environments/{environment_id}/cache/rules/{rule_id}",
    response_model=DeleteRuleResponse,
    response_model_by_alias=True,
)
async def remove_cache_rule(
    environment_id: str,
    rule_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteRuleResponse:
    """Remove an expert cache rule."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor_id, actor_name = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, (actor_id, actor_name))

    if dry_run:
        return DeleteRuleResponse(
            deleted=False, dry_run=True, policy_version=int(policy["policy_version"])
        )

    try:
        delete_rule(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            rule_id=rule_id,
            expected_policy_version=expected_policy_version,
        )
    except SlateCachePolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateCacheStoreError as exc:
        raise HTTPException(
            status_code=404, detail={"code": exc.code, "message": str(exc)}
        ) from exc

    append_audit(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_kind="user",
        subject_kind="rule",
        subject_id=rule_id,
        summary="Cache rule removed",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, (actor_id, actor_name))
    return DeleteRuleResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed["policy_version"])
    )


@router.post(
    "/environments/{environment_id}/cache/trace",
    response_model=TraceResponse,
    response_model_by_alias=True,
)
async def trace_cache_request(
    environment_id: str,
    request: TraceCommandBody,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> TraceResponse:
    """Explain what this lane's policy decides for a test request.

    A read, not a write, unless ``persist`` is set. The verdict answers eligibility, cache key,
    TTLs, bypass and the winning rule, and reports every rule that was considered together with
    the reason it did not win — because "why did my rule not fire" is the question that brings
    an operator here.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor_id, actor_name = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, (actor_id, actor_name))

    if request.rules is not None:
        rules: List[Dict[str, Any]] = [rule.model_dump() for rule in request.rules]
    else:
        rules = list_rules(db, tenant_id=tenant_id, environment_id=environment_id)

    verdict = evaluate_trace(
        request=TraceRequest(
            method=request.request.method,
            host=request.request.host,
            path=request.request.path,
            query=request.request.query,
            headers=request.request.headers,
            cookies=request.request.cookies,
        ),
        preset_key=str(policy["preset"]),
        rules=rules,
        now=datetime.now(timezone.utc),
    )

    basis_release_id = environment.get("active_release_id")
    trace_id: Optional[str] = None
    if request.persist:
        written = record_trace(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_kind="user",
            release_id=str(basis_release_id) if basis_release_id else None,
            request=request.request.model_dump(),
            policy_version=int(policy["policy_version"]),
            rules_digest=verdict.rules_digest,
            winning_rule_id=verdict.winning_rule_id,
            verdict=verdict.__dict__,
        )
        trace_id = str(written["id"]) if written.get("id") else None

    return TraceResponse(
        eligibility=verdict.eligibility,
        eligibility_reason=verdict.eligibility_reason,
        cache_key=verdict.cache_key,
        cache_key_components=[
            TraceKeyComponentBody(
                source=component["source"],
                name=component["name"],
                value=component["value"],
                contributed_because=component["contributed_because"],
            )
            for component in verdict.cache_key_components
        ],
        browser_ttl_seconds=verdict.browser_ttl_seconds,
        edge_ttl_seconds=verdict.edge_ttl_seconds,
        stale_while_revalidate_seconds=verdict.stale_while_revalidate_seconds,
        stale_if_error_seconds=verdict.stale_if_error_seconds,
        ttl_source=verdict.ttl_source,
        bypassed=verdict.bypassed,
        bypass_reason=verdict.bypass_reason,
        winning_rule_id=verdict.winning_rule_id,
        winning_rule_label=verdict.winning_rule_label,
        considered=[
            TraceStepBody(
                rule_id=step.get("rule_id"),
                label=str(step.get("label") or ""),
                ordinal=int(step.get("ordinal") or 0),
                matched=bool(step.get("matched")),
                outcome=str(step.get("outcome") or ""),
                reason=str(step.get("reason") or ""),
            )
            for step in verdict.considered
        ],
        warnings=_warning_bodies(verdict.warnings),
        rules_digest=verdict.rules_digest,
        policy_version=int(policy["policy_version"]),
        trace_id=trace_id,
        basis_release_id=str(basis_release_id) if basis_release_id else None,
    )


def _resolve_purge_routes(
    *, tenant_id: str, environment_id: str, environment: Mapping[str, Any], request: PurgeRequest
) -> tuple[List[str], str, Optional[str]]:
    """Resolve a purge scope to a candidate route set and name the table it came from.

    Args:
        tenant_id: Owning tenant.
        environment_id: The lane.
        environment: The environment row, for its active release.
        request: The purge request.

    Returns:
        The candidate routes, the estimate basis, and the release the estimate is based on.

    Raises:
        SlateCacheRefusedError: When a named release does not belong to this lane.
    """
    active_release_id = environment.get("active_release_id")
    basis_release = str(active_release_id) if active_release_id else None

    if request.scope_kind == "release":
        routes = routes_for_release(db, release_id=request.scope_value)
        if not routes:
            # A release with no changed pages is indistinguishable here from a release on
            # another lane. Both answer the same way, so the refusal leaks nothing.
            raise SlateCacheRefusedError(CacheRefusal.of("purge-release-not-found"))
        return routes, "changed-pages", request.scope_value

    if request.scope_kind == "host":
        return (
            routes_for_host(
                db,
                tenant_id=tenant_id,
                environment_id=environment_id,
                host=request.scope_value,
                release_id=basis_release,
            ),
            "domain-inventory",
            basis_release,
        )

    if request.scope_kind == "tag":
        tagged = rules_for_tag(
            db, tenant_id=tenant_id, environment_id=environment_id, tag=request.scope_value
        )
        inventory = routes_for_release(db, release_id=basis_release) if basis_release else []
        matched = [
            route
            for route in inventory
            if any(
                matches_route(normalize_rule(rule), TraceRequest(path=route).normalized())
                for rule in tagged
            )
        ]
        return matched, "rule-tags", basis_release

    inventory = routes_for_release(db, release_id=basis_release) if basis_release else []
    basis = "single-url" if request.scope_kind == "url" else "changed-pages"
    return inventory, basis, basis_release


@router.post(
    "/environments/{environment_id}/cache/purge",
    response_model=PurgeResponse,
    response_model_by_alias=True,
)
async def purge_cache(
    environment_id: str,
    request: PurgeRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> PurgeResponse:
    """Estimate a purge's scope and record it.

    **Nothing is evicted.** No delivery tier is attached to this environment, so what this
    writes is evidence: who asked, for what scope, with what estimated blast radius computed
    from which table, and why. The response says so in ``delivery``, and V187 refuses at the
    database any row claiming otherwise.

    A refused purge still writes a purge record and an audit entry when it is not a dry run:
    refusing to purge during an incident is precisely the event that needs to be in the
    timeline afterwards.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor_id, actor_name = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, (actor_id, actor_name))
    edge_attached = bool(policy.get("edge_attached"))

    try:
        routes, basis, basis_release = _resolve_purge_routes(
            tenant_id=tenant_id,
            environment_id=environment_id,
            environment=environment,
            request=request,
        )
        plan = plan_purge_scope(
            scope_kind=request.scope_kind,
            scope_value=request.scope_value,
            routes=routes,
            basis=basis,
        )
        if (
            request.confirm_estimated_objects is not None
            and request.confirm_estimated_objects != plan.estimated_objects
        ):
            raise SlateCacheRefusedError(CacheRefusal.of("purge-estimate-changed"))
    except SlateCacheRefusedError as exc:
        if not request.dry_run:
            record_purge(
                db,
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_kind="user",
                scope_kind=request.scope_kind,
                scope_value=request.scope_value,
                release_id=None,
                reason=request.reason,
                estimated_objects=0,
                estimate_basis="none",
                sample_routes=[],
                dry_run=False,
                outcome="refused",
                refusal_reason=exc.refusal.reason,
                edge_attached=edge_attached,
            )
            append_audit(
                db,
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_kind="user",
                subject_kind="purge",
                subject_id=None,
                summary="Purge refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    outcome = "estimated" if request.dry_run else "recorded"
    written = record_purge(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor_id=actor_id,
        actor_name=actor_name,
        actor_kind="user",
        scope_kind=plan.scope_kind,
        scope_value=plan.scope_value,
        release_id=basis_release,
        reason=request.reason,
        estimated_objects=plan.estimated_objects,
        estimate_basis=plan.estimate_basis,
        sample_routes=plan.sample_routes,
        dry_run=request.dry_run,
        outcome=outcome,
        refusal_reason=None,
        edge_attached=edge_attached,
    )

    if not request.dry_run:
        append_audit(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_kind="user",
            subject_kind="purge",
            subject_id=str(written["id"]) if written.get("id") else None,
            summary=f"Purged by {plan.scope_kind}: {plan.scope_value}",
            detail=(
                f"{plan.estimated_objects} objects estimated from {plan.estimate_basis}. "
                f"{request.reason}"
            ),
        )

    return PurgeResponse(
        outcome=outcome,
        dry_run=request.dry_run,
        estimate=PurgeEstimateBody(
            scope_kind=plan.scope_kind,
            scope_value=plan.scope_value,
            estimated_objects=plan.estimated_objects,
            estimate_basis=plan.estimate_basis,
            sample_routes=plan.sample_routes,
            truncated=plan.truncated,
            coverage=plan.coverage,
        ),
        purge_id=str(written["id"]) if written.get("id") else None,
        edge_attached=edge_attached,
        delivery=DeliveryBody(dispatched=False, sentence=_NO_DELIVERY_SENTENCE),
    )


@router.get(
    "/environments/{environment_id}/cache/purges",
    response_model=PurgeHistoryResponse,
    response_model_by_alias=True,
)
async def get_purge_history(
    environment_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    scope_kind: Optional[str] = Query(default=None, alias="scopeKind"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> PurgeHistoryResponse:
    """Return a lane's purge history, most recent first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_purges(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        limit=limit,
        scope_kind=scope_kind,
    )
    return PurgeHistoryResponse(
        purges=[
            PurgeRecordBody(
                id=str(row["id"]),
                at=_iso(row.get("at")),
                actor_name=str(row.get("actor_name") or ""),
                scope_kind=str(row.get("scope_kind") or ""),
                scope_value=str(row.get("scope_value") or ""),
                reason=str(row.get("reason") or ""),
                estimated_objects=int(row.get("estimated_objects") or 0),
                estimate_basis=str(row.get("estimate_basis") or ""),
                sample_routes=list(row.get("sample_routes") or []),
                dry_run=bool(row.get("dry_run")),
                outcome=str(row.get("outcome") or ""),
                refusal_reason=row.get("refusal_reason"),
                edge_attached=bool(row.get("edge_attached")),
            )
            for row in rows
        ]
    )


@router.get(
    "/environments/{environment_id}/cache/audit",
    response_model=AuditResponse,
    response_model_by_alias=True,
)
async def get_cache_audit(
    environment_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> AuditResponse:
    """Return a lane's append-only cache audit trail, most recent first."""
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
