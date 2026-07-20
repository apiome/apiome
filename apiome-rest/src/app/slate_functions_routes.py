"""Slate Edge functions and safe personalization REST API — UXE-3.3 (private-suite#2475).

The function control plane the authoring Edge Functions surface consumes:

* ``GET  /v1/slate/functions/presets``, ``.../functions/runtimes``, ``.../functions/capabilities``
  — the residency postures, cache-key effects, execution runtimes and runtime capabilities as
  data: every option, and the prose stating what choosing it costs and what it is unsafe for. The
  UI prints what this returns rather than holding a second copy, because two copies would
  eventually disagree and the screen would be the one that lied.

* ``GET  /v1/slate/environments/{environment_id}/functions``
  — the lane's function policy: region and residency, the CPU, memory and wall-clock ceilings, the
  concurrency token, every function with its capability grants, egress allowances, secret
  references and personalization variants, and the ``enforcement`` block described below.

* ``PUT .../functions/policy``, ``POST``/``PUT``/``DELETE .../functions[/{function_id}]``,
  ``.../versions``, ``.../rollout``, ``.../revert``, ``GET .../revisions``
  — functions, their immutable versions and their staged rollout. Every write runs
  :func:`app.slate_functions.evaluate_function_safety` first, and every write records the prior
  body as a revision, so "every function change can be reverted" means applying a stored document.

* ``PUT``/``DELETE .../secrets``, ``.../capabilities``, ``.../egress``
  — secret references that are references and never values, and the two deny-by-default grants.
  Granting is writing a row and revoking is deleting one; there is no boolean to flip the wrong
  way in either direction.

* ``POST .../functions/variants``, ``PUT``/``DELETE .../functions/variants/{variant_id}``,
  ``POST .../functions/approvals``
  — personalization variants, whose audience rule, fallback, cache-key effect, analytics
  dimension and privacy classification travel together, and dual-control approvals of one exact
  body.

* ``POST .../functions/simulate``
  — evaluate a test request against the lane's policy and explain the result, naming the winning
  function and variant *and every one that lost and why*.

* ``GET  .../functions/invocations[/{invocation_id}]``, ``.../functions/audit``,
  ``.../functions/audit/export``
  — invocation records with redacted evidence, the append-only audit trail, and CSV evidence.

**The honesty boundary, which is the whole point of this ticket.** ``deploy/`` is a single
Caddyfile: no isolate pool, no WASM runtime, no egress proxy. Nothing here executes any code. So:

* every policy response carries ``enforcement``, whose ``enforced`` is a ``Literal[False]``;
* every simulation carries ``basis: "policy-simulation"``, ``observed: false``,
  ``executed: false`` and ``enforced: false`` as literal pydantic defaults no handler assigns,
  exactly as ``TraceResponse`` does in :mod:`app.slate_cache_routes` and ``SimulateResponse`` in
  :mod:`app.slate_security_routes` — the response is structurally unable to lie.

An unenforced cache rule wastes a purge and an unenforced WAF rule leaves an attacker unblocked.
A green "ran" row would be worse than either, because it would be evidence of an isolation
guarantee that was never tested.

Authorization: reads require VERSIONS/VIEW, writes require VERSIONS/PUBLISH. As in
:mod:`app.slate_cache_routes` and :mod:`app.slate_security_routes` there is no separate
``functions`` resource — V187 and V188 deliberately did not add one, because inventing a
permission dimension the roles matrix does not render would leave it ungrantable in the UI.

Simulation and audit export are VIEW rather than PUBLISH. "Which function served this customer" is
the question an operator asks during an incident, and requiring PUBLISH would put the answer out of
reach of exactly the person asking.

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
from .slate_functions import (
    CACHE_KEY_EFFECT_CATALOG,
    CAPABILITY_CATALOG,
    RESIDENCY_CLASS_CATALOG,
    RUNTIME_CATALOG,
    FunctionRefusal,
    InvocationRequest,
    SlateFunctionRefusedError,
    body_digest,
    evaluate_capability_safety,
    evaluate_egress_safety,
    evaluate_function_safety,
    evaluate_policy_safety,
    evaluate_variant_safety,
    functions_digest,
    normalize_function,
    simulate_invocation,
)
from .slate_functions_store import (
    SlateFunctionPolicyConflictError,
    SlateFunctionStoreError,
    add_version,
    append_audit,
    delete_egress_rule,
    delete_function,
    delete_secret_ref,
    delete_variant,
    ensure_policy,
    function_evaluation_context,
    get_function,
    get_invocation,
    grant_capability,
    list_approvals,
    list_audit,
    list_capabilities,
    list_egress_rules,
    list_functions,
    list_invocations,
    list_revisions,
    list_secret_refs,
    list_variants,
    list_versions,
    record_approval,
    record_invocation,
    revert_function,
    revoke_capability,
    set_egress_rule,
    set_policy,
    set_rollout,
    set_secret_ref,
    upsert_function,
    upsert_variant,
)

router = APIRouter(prefix="/v1/slate", tags=["slate-functions"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


#: Stated on every policy read and every write outcome. Louder than the cache plane's equivalent
#: on purpose: a cache rule that does not apply costs a slow page, and a function that does not
#: run means somebody believes untrusted code is being contained and it has never been tried.
_NO_EXECUTION_SENTENCE = (
    "No managed runtime tier is attached to this environment. These functions are recorded "
    "policy: nothing is compiled, nothing is sandboxed and no code runs on any request."
)

#: Stated on every simulation and on the invocation stream.
_NO_OBSERVATION_SENTENCE = (
    "These records are simulations of the recorded policy against sample requests, not traffic "
    "that was observed. No request path exists to observe."
)

#: Stated wherever a resource measurement would otherwise be rendered. A simulation consumed no
#: CPU and held no request open, so the honest report is the absence of a measurement rather than
#: a zero, which would be a measurement.
_NO_RUNTIME_SENTENCE = (
    "No CPU, wall-clock or memory figures accompany these records, because nothing ran to "
    "consume any. A zero here would be a measurement; the absence of one is the truth."
)

#: A cell beginning with one of these is interpreted as a formula by Excel, Numbers and Sheets.
#: An actor display name is attacker-influenced text, so the export prefixes such a cell with an
#: apostrophe. ``access_routes.py``'s exporter does not, which is the defect this one fixes.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# ─── Catalog models ──────────────────────────────────────────────────────────


class RuntimeBody(_CamelModel):
    """One execution environment as data, so the UI never holds a second copy of the sandbox."""

    key: str = Field(description="js-isolate or wasm.")
    label: str = Field(description="Operator-facing runtime name.")
    intent: str = Field(description="One-line intent, from roadmap §29.5.")
    expected_impact: str = Field(description="What this runtime means for the blast radius.")
    sandbox: str = Field(description="What the sandbox does and does not contain.")
    unsafe_if: List[str] = Field(description="What this runtime is a poor fit for.")


class RuntimesResponse(_CamelModel):
    """The execution runtime catalog."""

    runtimes: List[RuntimeBody] = Field(description="Every runtime, narrowest sandbox first.")


class CapabilityBody(_CamelModel):
    """One runtime capability, stated as what granting it actually costs."""

    id: str = Field(description="Catalog identifier, stored on the grant row.")
    title: str = Field(description="Operator-facing name.")
    description: str = Field(description="What the capability lets a function do.")
    expected_impact: str = Field(description="What granting it costs, and what it makes possible.")
    requires_expiry: bool = Field(description="Whether a grant of this must carry an end date.")
    privacy_reach: str = Field(description="none, coarse or identifying.")
    unsafe_if: List[str] = Field(description="What this capability is unsafe alongside.")


class CapabilitiesResponse(_CamelModel):
    """The runtime capability catalog.

    Deny-by-default is the absence of a grant row, so there is no table anywhere listing what the
    capabilities are. This is that list, versioned in code rather than seeded per tenant, which is
    the only way an operator can read what a grant opens before making one.
    """

    capabilities: List[CapabilityBody] = Field(description="Every capability, safest first.")


class ResidencyClassBody(_CamelModel):
    """One residency posture, including what it explicitly does *not* cover."""

    key: str = Field(description="in-region-only, region-pinned or unrestricted.")
    label: str = Field(description="Operator-facing name.")
    intent: str = Field(description="One-line intent.")
    expected_impact: str = Field(description="Where execution and data actually happen.")
    does_not_cover: str = Field(description="What this option leaves outside its promise.")
    permits_personal: bool = Field(description="Whether a personal-class variant may run here.")
    requires_waiver_reason: bool = Field(description="Whether choosing it must state why.")
    unsafe_if: List[str] = Field(description="What this posture is a poor fit for.")


class CacheKeyEffectBody(_CamelModel):
    """What a personalization variant does to the shared cache key."""

    key: str = Field(description="none, vary-on-dimension or bypass-cache.")
    label: str = Field(description="Operator-facing name.")
    intent: str = Field(description="One-line intent.")
    expected_impact: str = Field(description="What it does to hit ratio and to reader safety.")
    fragments_cache: bool = Field(description="Whether it multiplies stored entries.")
    safe_for_personal: bool = Field(description="Whether a variant above non-personal may use it.")
    unsafe_if: List[str] = Field(description="What this effect is a poor fit for.")


class FunctionPresetsResponse(_CamelModel):
    """The safe presets a Publisher may choose between without ever touching a runtime."""

    residency_classes: List[ResidencyClassBody] = Field(description="The three residency postures.")
    cache_key_effects: List[CacheKeyEffectBody] = Field(description="The three cache-key effects.")


# ─── Honesty models ──────────────────────────────────────────────────────────


class EnforcementBody(_CamelModel):
    """Whether the recorded function policy runs anything.

    ``enforced`` is a ``Literal[False]`` with a default no handler assigns. That is the point: the
    response is structurally unable to claim an execution, in the same way V189's CHECKs make the
    corresponding columns unable to hold one.
    """

    enforced: Literal[False] = Field(
        default=False, description="False. No runtime tier is attached to this environment."
    )
    sentence: str = Field(
        default=_NO_EXECUTION_SENTENCE, description="What that means, in words."
    )


class FunctionWarningBody(_CamelModel):
    """A concern that does not block the write."""

    code: str = Field(description="Named warning reason.")
    message: str = Field(description="Operator-facing sentence, rendered verbatim by the UI.")
    field: str = Field(default="", description="Function field the warning attaches to.")
    severity: Literal["warn", "block"] = Field(
        default="warn", description="warn never blocks; block is returned only on a 409."
    )


# ─── Resource models ─────────────────────────────────────────────────────────


class SecretRefBody(_CamelModel):
    """One secret reference. A name, an alias and a scope — never a value."""

    id: Optional[str] = Field(default=None, description="Reference id, absent before it is written.")
    function_id: str = Field(default="", description="Function that declared it.")
    secret_name: str = Field(default="", description="Name of the secret in the vault.")
    alias: str = Field(default="", description="Identifier the function code binds to.")
    scope: str = Field(default="function", description="function or environment.")
    actor_name: str = Field(default="", description="Who declared it.")


class CapabilityGrantBody(_CamelModel):
    """One capability grant. The row is the grant; there is no granted flag."""

    id: Optional[str] = Field(default=None, description="Grant id, absent before it is written.")
    function_id: str = Field(default="", description="Function the capability is granted to.")
    capability: str = Field(default="", description="What the function may do.")
    reason: str = Field(default="", description="Why it was granted.")
    expires_at: Optional[str] = Field(default=None, description="When it lapses, or null.")
    granted_at: Optional[str] = Field(default=None, description="When it was granted.")
    granted_by: str = Field(default="", description="Display name of the granter.")


class EgressRuleBody(_CamelModel):
    """One egress allowlist entry. The row is the allowance; there is no wildcard kind."""

    id: Optional[str] = Field(default=None, description="Entry id, absent before it is written.")
    function_id: str = Field(default="", description="Function permitted to reach it.")
    destination_kind: str = Field(default="exact-host", description="exact-host or host-suffix.")
    destination: str = Field(default="", description="The host or host suffix.")
    scheme: str = Field(default="https", description="https or http.")
    port: Optional[int] = Field(default=None, description="Permitted port, or null for default.")
    methods: List[str] = Field(default_factory=list, description="Methods; empty means every one.")
    reason: str = Field(default="", description="Why this destination is reachable.")
    expires_at: Optional[str] = Field(default=None, description="When it lapses, or null.")
    granted_by: str = Field(default="", description="Display name of the granter.")


class VariantBody(_CamelModel):
    """One personalization variant, with everything §29.5 requires shown together."""

    id: Optional[str] = Field(default=None, description="Variant id, absent before it is written.")
    function_id: str = Field(default="", description="Function that selects between variants.")
    ordinal: int = Field(default=0, description="Precedence among variants; lower wins.")
    enabled: bool = Field(default=True, description="Whether the variant participates.")
    label: str = Field(default="", description="Operator-facing name.")
    audience_kind: str = Field(default="geo", description="geo, language, device, cohort or experiment.")
    audience_matcher: List[Dict[str, Any]] = Field(
        default_factory=list, description="The audience predicates."
    )
    fallback_variant: str = Field(
        default="", description="What every reader the audience rule does not match receives."
    )
    cache_key_effect: str = Field(
        default="none", description="none, vary-on-dimension or bypass-cache."
    )
    vary_dimension: str = Field(default="", description="What the cache key varies on.")
    analytics_dimension: str = Field(default="", description="The dimension it reports under.")
    privacy_class: str = Field(
        default="non-personal", description="non-personal, pseudonymous or personal."
    )
    consent_basis: str = Field(
        default="not-required", description="not-required, explicit-consent or legitimate-interest."
    )


class FunctionVersionBody(_CamelModel):
    """One immutable, content-addressed source version."""

    id: str = Field(description="Version id.")
    revision: int = Field(default=1, description="Which revision of the function this version is.")
    source_digest: str = Field(default="", description="Content address of the source.")
    runtime: str = Field(default="", description="Runtime this version was built for.")
    source_bytes: Optional[int] = Field(default=None, description="Size in bytes, or null.")
    source_origin: str = Field(default="upload", description="upload, build or import.")
    source_ref: Optional[str] = Field(default=None, description="Commit, build id or upload ref.")
    created_at: Optional[str] = Field(default=None, description="When it was recorded.")
    created_by: str = Field(default="", description="Display name of the actor.")
    body: Dict[str, Any] = Field(default_factory=dict, description="The version manifest.")


class FunctionBody(_CamelModel):
    """One route-matched function, with its grants and variants attached."""

    id: Optional[str] = Field(default=None, description="Function id, absent before it is written.")
    ordinal: int = Field(default=0, description="Precedence; lower wins.")
    enabled: bool = Field(default=True, description="Whether the function participates.")
    label: str = Field(default="", description="Operator-facing function name.")
    matcher_kind: str = Field(default="prefix", description="exact, prefix, glob or regex.")
    matcher_value: str = Field(default="/", description="The route pattern.")
    matcher_methods: List[str] = Field(default_factory=list, description="Methods; empty is all.")
    matcher_hosts: List[str] = Field(default_factory=list, description="Hosts; empty is all.")
    runtime: str = Field(default="js-isolate", description="js-isolate or wasm.")
    active_version_id: Optional[str] = Field(default=None, description="The live version, or null.")
    rollout_mode: str = Field(default="simulate", description="simulate or enforce.")
    rollout_percent: int = Field(default=0, ge=0, le=100, description="Share of traffic, 0 to 100.")
    region: Optional[str] = Field(default=None, description="Region override, or null to inherit.")
    residency_class: Optional[str] = Field(
        default=None, description="Residency override, or null to inherit."
    )
    cpu_ms_limit: Optional[int] = Field(default=None, description="CPU override, or null.")
    memory_mb_limit: Optional[int] = Field(default=None, description="Memory override, or null.")
    wall_ms_limit: Optional[int] = Field(default=None, description="Wall-clock override, or null.")
    env_var_names: List[str] = Field(
        default_factory=list, description="Non-secret environment variable names. Names only."
    )
    declared_destinations: List[str] = Field(
        default_factory=list, description="Hosts the version manifest says the code will call."
    )
    acknowledged_warnings: List[str] = Field(
        default_factory=list, description="Warning reasons the operator accepted."
    )
    body_digest: str = Field(
        default="", description="Content digest of the decisive fields; what an approval names."
    )
    revision: int = Field(default=1, description="Monotonic revision counter.")
    capabilities: List[CapabilityGrantBody] = Field(
        default_factory=list, description="Live capability grants. Absence of one is a denial."
    )
    egress: List[EgressRuleBody] = Field(
        default_factory=list, description="Egress allowlist entries. Absence of one is a denial."
    )
    secrets: List[SecretRefBody] = Field(
        default_factory=list, description="Secret references. References only, never values."
    )
    variants: List[VariantBody] = Field(
        default_factory=list, description="Personalization variants, in selection order."
    )


class FunctionPolicyResponse(_CamelModel):
    """A lane's complete function policy, and what it actually runs."""

    environment_id: str = Field(description="The lane.")
    functions_enabled: bool = Field(description="Whether functions may exist on this lane at all.")
    policy_version: int = Field(description="Optimistic-concurrency token.")
    edge_attached: bool = Field(description="Whether a runtime tier serves this lane.")
    edge_provider: Optional[str] = Field(default=None, description="Its name, or null.")
    default_region: str = Field(description="Where functions run by default.")
    default_residency_class: str = Field(description="The lane's residency posture.")
    default_cpu_ms_limit: int = Field(description="CPU ceiling a function may tighten.")
    default_memory_mb_limit: int = Field(description="Memory ceiling a function may tighten.")
    default_wall_ms_limit: int = Field(description="Wall-clock ceiling a function may tighten.")
    residency_waiver_reason: Optional[str] = Field(
        default=None, description="Why residency was loosened, when it was."
    )
    enforcement: EnforcementBody = Field(
        default_factory=EnforcementBody, description="Whether the policy runs anything."
    )
    functions: List[FunctionBody] = Field(description="Functions, in precedence order.")
    functions_digest: str = Field(description="Determinism receipt over the enabled function set.")
    updated_at: Optional[str] = Field(default=None, description="When the policy last changed.")
    updated_by: Optional[str] = Field(default=None, description="Who changed it.")


class SetFunctionPolicyRequest(_CamelModel):
    """Change a lane's function policy: whether functions run, where, and within what ceilings."""

    functions_enabled: bool = Field(default=False, description="Whether functions may exist here.")
    default_region: str = Field(default="auto", description="Where functions run by default.")
    default_residency_class: str = Field(
        default="in-region-only", description="in-region-only, region-pinned or unrestricted."
    )
    default_cpu_ms_limit: int = Field(default=50, gt=0, description="CPU ceiling in milliseconds.")
    default_memory_mb_limit: int = Field(default=128, gt=0, description="Memory ceiling in MB.")
    default_wall_ms_limit: int = Field(default=5000, gt=0, description="Wall-clock ceiling in ms.")
    residency_waiver_reason: Optional[str] = Field(
        default=None, description="Required when residency is unrestricted."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Run every gate and write nothing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class SetFunctionPolicyResponse(_CamelModel):
    """The outcome of a function policy change."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    functions_enabled: bool = Field(description="Whether functions may exist, after the change.")
    default_residency_class: str = Field(description="The residency posture now in effect.")
    policy_version: int = Field(description="The version after the change.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[FunctionWarningBody] = Field(default_factory=list)


class WriteFunctionRequest(FunctionBody):
    """Create or replace a function."""

    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class WriteFunctionResponse(_CamelModel):
    """The outcome of a function write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    function: Optional[FunctionBody] = Field(default=None, description="The function as written.")
    body_digest: str = Field(description="What an approval of this body must name.")
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[FunctionWarningBody] = Field(default_factory=list)


class DeleteFunctionResponse(_CamelModel):
    """The outcome of a function deletion."""

    deleted: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    policy_version: int = Field(description="The version after the write.")


class RolloutRequest(_CamelModel):
    """Advance or retreat a function's staged rollout."""

    rollout_mode: str = Field(description="simulate or enforce.")
    rollout_percent: int = Field(ge=0, le=100, description="Share of traffic, 0 to 100.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class RevertRequest(_CamelModel):
    """Restore a function to a stored revision."""

    revision: int = Field(ge=1, description="Which stored revision to apply.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class AddVersionRequest(_CamelModel):
    """Record a new immutable source version, optionally promoting it."""

    source_digest: str = Field(description="Content address of the source.")
    body: Dict[str, Any] = Field(default_factory=dict, description="The version manifest.")
    runtime: str = Field(default="js-isolate", description="Runtime this version was built for.")
    source_bytes: Optional[int] = Field(default=None, description="Size in bytes, or null.")
    source_origin: str = Field(default="upload", description="upload, build or import.")
    source_ref: Optional[str] = Field(default=None, description="Commit, build id or upload ref.")
    activate: bool = Field(default=False, description="Whether to make this the live version.")
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class AddVersionResponse(_CamelModel):
    """The outcome of adding a version."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    version: Optional[FunctionVersionBody] = Field(default=None, description="The version written.")
    activated: bool = Field(description="Whether it was promoted to live.")
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)


class RevisionBody(_CamelModel):
    """One recorded function body."""

    id: str = Field(description="Revision row id.")
    revision: int = Field(default=1, description="Which revision of the function this body was.")
    change_kind: str = Field(default="", description="What produced this revision.")
    body_digest: str = Field(default="", description="Digest of the recorded body.")
    at: Optional[str] = Field(default=None, description="When the change happened.")
    actor_name: str = Field(default="", description="Who made it.")
    body: Dict[str, Any] = Field(default_factory=dict, description="The complete stored body.")


class RevisionsResponse(_CamelModel):
    """A function's revision history."""

    revisions: List[RevisionBody] = Field(description="Newest first.")
    versions: List[FunctionVersionBody] = Field(
        default_factory=list, description="The immutable versions alongside them."
    )


class SetSecretRefRequest(_CamelModel):
    """Declare a secret reference on a function. There is no value field, by construction."""

    secret_name: str = Field(description="Name of the secret in the vault that holds the material.")
    alias: str = Field(description="Identifier the function code binds to.")
    scope: str = Field(default="function", description="function or environment.")
    owner_tenant_id: str = Field(
        default="", description="Tenant the secret belongs to. A differing value is refused."
    )
    owner_environment_id: str = Field(
        default="", description="Environment the secret belongs to. A differing value is refused."
    )
    owner_function_id: str = Field(
        default="", description="Function the secret belongs to, for a function-scoped reference."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")


class SecretRefResponse(_CamelModel):
    """The outcome of declaring a secret reference."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    secret: Optional[SecretRefBody] = Field(default=None, description="The reference as written.")
    policy_version: int = Field(description="The version after the write.")


class GrantCapabilityRequest(_CamelModel):
    """Grant one runtime capability to a function."""

    capability: str = Field(description="Which capability, from the catalog.")
    reason: str = Field(description="Why the function needs it.")
    expires_at: Optional[str] = Field(
        default=None, description="When the grant lapses. Required for the standing privileges."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")


class CapabilityGrantResponse(_CamelModel):
    """The outcome of a capability grant."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    capability: Optional[CapabilityGrantBody] = Field(default=None, description="The grant.")
    policy_version: int = Field(description="The version after the write.")
    enforcement: EnforcementBody = Field(default_factory=EnforcementBody)
    warnings: List[FunctionWarningBody] = Field(default_factory=list)


class SetEgressRuleRequest(_CamelModel):
    """Allowlist one outbound destination for a function."""

    destination_kind: str = Field(default="exact-host", description="exact-host or host-suffix.")
    destination: str = Field(description="The host or host suffix.")
    scheme: str = Field(default="https", description="https or http.")
    port: Optional[int] = Field(default=None, description="Permitted port, or null for default.")
    methods: List[str] = Field(default_factory=list, description="Methods; empty means every one.")
    reason: str = Field(description="Why this destination is reachable.")
    expires_at: Optional[str] = Field(default=None, description="When it lapses, or null.")
    destinations: List[str] = Field(
        default_factory=list, description="Destinations this entry is meant to cover, checked here."
    )
    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")


class EgressRuleResponse(_CamelModel):
    """The outcome of an egress allowlist write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    egress: Optional[EgressRuleBody] = Field(default=None, description="The entry as written.")
    policy_version: int = Field(description="The version after the write.")
    warnings: List[FunctionWarningBody] = Field(default_factory=list)


class WriteVariantRequest(VariantBody):
    """Create or replace a personalization variant."""

    expected_policy_version: int = Field(description="The version the caller read.")
    dry_run: bool = Field(default=False, description="Validate without writing.")
    reason: str = Field(default="", description="Why; recorded in audit.")


class WriteVariantResponse(_CamelModel):
    """The outcome of a variant write."""

    applied: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    variant: Optional[VariantBody] = Field(default=None, description="The variant as written.")
    policy_version: int = Field(description="The version after the write.")
    warnings: List[FunctionWarningBody] = Field(default_factory=list)


class DeleteVariantResponse(_CamelModel):
    """The outcome of removing a variant."""

    deleted: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    policy_version: int = Field(description="The version after the write.")


class DeleteGrantResponse(_CamelModel):
    """The outcome of revoking a grant, an allowance or a reference.

    Revoking is a DELETE, because the absence of a row is the denial. There is no field here
    reporting a ``granted`` flag, because there is no such column to report.
    """

    deleted: bool = Field(description="False for a dry run.")
    dry_run: bool = Field(description="Whether this was a preview.")
    policy_version: int = Field(description="The version after the write.")


class ApprovalRequest(_CamelModel):
    """Record a second person's approval of one exact body."""

    subject_kind: Literal[
        "policy", "function", "version", "capability", "egress-rule", "variant"
    ] = Field(description="What is being approved.")
    subject_id: str = Field(description="Id of the subject.")
    digest: str = Field(description="The body that was reviewed, from the write response.")
    author_actor_key: str = Field(description="Immutable identity of whoever proposed it.")
    author_actor_name: str = Field(default="", description="The proposer's display name.")
    note: Optional[str] = Field(default=None, description="Optional reviewer note.")


class ApprovalBody(_CamelModel):
    """One recorded approval."""

    id: str = Field(description="Approval id.")
    subject_kind: str = Field(default="", description="What was approved.")
    subject_id: str = Field(default="", description="Id of the subject.")
    digest: str = Field(default="", description="The body that was reviewed.")
    author_actor_name: str = Field(default="", description="Who proposed it.")
    approver_actor_name: str = Field(default="", description="Who approved it.")
    approved_at: Optional[str] = Field(default=None, description="When.")
    note: Optional[str] = Field(default=None, description="Reviewer note, when there is one.")


# ─── Simulation models ───────────────────────────────────────────────────────


class SimulateRequestBody(_CamelModel):
    """The test request to evaluate.

    ``requestedCapabilities`` and ``requestedDestinations`` are what make this deterministic
    without a runtime: there is nothing in the request path to execute code, so the caller states
    what the version manifest declares and the simulation answers what the *policy* does about it.
    That is a smaller claim than "this is what the function did", and it is the one that is true.
    """

    method: str = Field(default="GET", description="HTTP method.")
    host: str = Field(default="", description="Request host.")
    path: str = Field(default="/", description="Request path.")
    country: str = Field(default="", description="Resolved country, for a geo predicate.")
    language: str = Field(default="", description="Resolved language.")
    device: str = Field(default="", description="Resolved device class.")
    cohort: str = Field(default="", description="Cohort assignment.")
    experiment: str = Field(default="", description="Experiment assignment.")
    requested_capabilities: List[str] = Field(
        default_factory=list, description="Capabilities the code would use on this request."
    )
    requested_destinations: List[str] = Field(
        default_factory=list, description="Hosts the code would call on this request."
    )
    estimated_cpu_ms: int = Field(default=0, description="Expected CPU; 0 means no estimate.")
    estimated_wall_ms: int = Field(default=0, description="Expected wall-clock; 0 means none.")
    estimated_memory_mb: int = Field(default=0, description="Expected peak memory; 0 means none.")
    headers: Dict[str, str] = Field(default_factory=dict, description="Request headers.")


class SimulateCommandBody(_CamelModel):
    """A simulation, optionally over a what-if function set."""

    request: SimulateRequestBody = Field(description="The test request.")
    functions: Optional[List[FunctionBody]] = Field(
        default=None,
        description="What-if overlay. When absent, the lane's stored functions are used.",
    )
    persist: bool = Field(default=False, description="Record the outcome as an invocation.")


class SimulationStepBody(_CamelModel):
    """One function or variant the simulation considered, and what became of it."""

    kind: str = Field(description="function or variant.")
    ref: Optional[str] = Field(default=None, description="Its id, when it has one.")
    label: str = Field(description="Its name.")
    ordinal: Optional[int] = Field(default=None, description="Its precedence.")
    outcome: str = Field(description="What became of it.")
    reason: str = Field(description="Why, in a sentence.")


class SimulateResponse(_CamelModel):
    """What the policy decides for a test request, and why every other function did not.

    ``basis``, ``observed``, ``executed`` and ``enforced`` are literal defaults no handler
    assigns. There is no code path able to make this response claim that a request was observed or
    that code ran, which is the structural form of the same guarantee V189 expresses as CHECKs.
    """

    outcome: str = Field(description="What the policy concluded. Never 'ran'.")
    outcome_reason: str = Field(description="One sentence naming the outcome and what produced it.")
    function_ref: Optional[str] = Field(default=None, description="The function that won.")
    function_label: str = Field(description="Its name.")
    version_ref: Optional[str] = Field(default=None, description="The version that would have run.")
    runtime: str = Field(description="The runtime it declares.")
    rollout_mode: str = Field(description="Its rollout mode.")
    rollout_percent: int = Field(description="Its rollout percentage.")
    region: str = Field(description="Where it would have run.")
    residency_class: str = Field(description="The residency posture it would have run under.")
    limits: Dict[str, int] = Field(default_factory=dict, description="The ceilings it runs within.")
    variant_ref: Optional[str] = Field(default=None, description="The variant selected.")
    variant_label: str = Field(description="Its name.")
    fallback_variant: str = Field(description="What every unmatched reader receives.")
    cache_key_effect: str = Field(description="The resolved effect on the shared cache key.")
    privacy_class: str = Field(description="The privacy classification of the selected variant.")
    consent_basis: str = Field(description="Its consent basis.")
    analytics_dimension: str = Field(description="The dimension it reports under.")
    capabilities_granted: List[str] = Field(default_factory=list, description="Held and used.")
    capabilities_denied: List[str] = Field(
        default_factory=list, description="Asked for and not held. Deny-by-default surfaces here."
    )
    egress_allowed: List[str] = Field(default_factory=list, description="Destinations covered.")
    egress_denied: List[str] = Field(default_factory=list, description="Destinations not covered.")
    denial_reason: Optional[str] = Field(default=None, description="Why a denial happened.")
    considered: List[SimulationStepBody] = Field(
        description="Every function and variant, and why it did not win."
    )
    warnings: List[FunctionWarningBody] = Field(default_factory=list)
    functions_digest: str = Field(description="Determinism receipt over the evaluated function set.")
    policy_version: int = Field(description="Which policy generation answered.")
    basis: Literal["policy-simulation"] = Field(
        default="policy-simulation",
        description=(
            "This is an evaluation of recorded policy against a test request, not a replay of an "
            "observed request. When a runtime tier lands, 'edge-observed' becomes the second "
            "value of this field rather than a change of meaning for the first."
        ),
    )
    observed: bool = Field(
        default=False, description="False: no runtime tier reported this request."
    )
    executed: Literal[False] = Field(
        default=False, description="False: no code ran, because there is nothing to run it in."
    )
    enforced: Literal[False] = Field(
        default=False, description="False: nothing acted on this request."
    )
    sentence: str = Field(
        default=_NO_OBSERVATION_SENTENCE, description="What all of that means, in words."
    )
    runtime_sentence: str = Field(
        default=_NO_RUNTIME_SENTENCE, description="Why there are no resource measurements."
    )
    invocation_id: Optional[str] = Field(
        default=None, description="Set when the outcome was recorded."
    )


class InvocationBody(_CamelModel):
    """One invocation record, with its redacted evidence."""

    id: str = Field(description="Invocation id.")
    at: Optional[str] = Field(default=None, description="When it was recorded.")
    source: str = Field(default="", description="policy-simulation or edge-observed.")
    function_ref: str = Field(default="", description="The function that decided.")
    function_label: str = Field(default="", description="Its label as it read at the time.")
    route: str = Field(default="", description="The request path.")
    method: str = Field(default="", description="The request method.")
    release_id: Optional[str] = Field(default=None, description="Release active at the time.")
    region: Optional[str] = Field(default=None, description="Region, when known.")
    variant_ref: Optional[str] = Field(default=None, description="Variant selected, when one was.")
    outcome: str = Field(default="", description="What the evaluation concluded.")
    executed: bool = Field(default=False, description="Whether code actually ran.")
    edge_attached: bool = Field(default=False, description="Whether a runtime tier was attached.")
    cpu_ms: Optional[int] = Field(default=None, description="CPU consumed, or null.")
    wall_ms: Optional[int] = Field(default=None, description="Wall-clock elapsed, or null.")
    memory_peak_mb: Optional[int] = Field(default=None, description="Peak memory, or null.")
    denial_reason: Optional[str] = Field(default=None, description="Why a denial happened.")
    evidence: Dict[str, str] = Field(default_factory=dict, description="Redacted request evidence.")
    retain_until: Optional[str] = Field(default=None, description="When the evidence is purged.")


class InvocationsResponse(_CamelModel):
    """A lane's invocation records."""

    invocations: List[InvocationBody] = Field(description="Most recent first.")
    observed: bool = Field(
        default=False, description="False: none of these were observed in a request path."
    )
    sentence: str = Field(default=_NO_OBSERVATION_SENTENCE, description="What that means.")
    runtime_sentence: str = Field(
        default=_NO_RUNTIME_SENTENCE, description="Why there are no resource measurements."
    )


class AuditEntryBody(_CamelModel):
    """One append-only audit entry."""

    id: str = Field(description="Entry id.")
    at: Optional[str] = Field(default=None, description="When the event happened.")
    actor_name: str = Field(default="", description="Who acted.")
    actor_kind: str = Field(default="", description="user or automation.")
    subject_kind: str = Field(default="", description="What the entry is about.")
    subject_id: Optional[str] = Field(default=None, description="Id of the subject.")
    summary: str = Field(default="", description="What happened.")
    detail: Optional[str] = Field(default=None, description="Extra context.")


class AuditResponse(_CamelModel):
    """A lane's function audit trail."""

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
            cross-tenant probe must not be able to confirm the lane exists, and on a surface that
            grants code the right to read secrets that probe is the reconnaissance step.
    """
    environment = get_environment(db, tenant_id=tenant_id, environment_id=environment_id)
    if not environment:
        raise HTTPException(
            status_code=404,
            detail={"code": "environment_not_found", "message": "Environment not found."},
        )
    return environment


def _refusal_http(error: SlateFunctionRefusedError) -> HTTPException:
    """Map a function refusal to a 409 carrying its named reason and sentence.

    The sentence is the server's, character for character. Restating it here would produce two
    copies that eventually disagreed, and the copy on screen would be the one an operator trusted.
    """
    return HTTPException(
        status_code=409,
        detail={
            "code": error.refusal.reason,
            "message": error.refusal.sentence,
            "reason": error.refusal.reason,
        },
    )


def _conflict_http(error: SlateFunctionPolicyConflictError) -> HTTPException:
    """Map a lost update to the ``policy-version-conflict`` refusal."""
    refusal = FunctionRefusal.of("policy-version-conflict")
    return HTTPException(
        status_code=409,
        detail={
            "code": refusal.reason,
            "message": refusal.sentence,
            "reason": refusal.reason,
            "actualPolicyVersion": error.actual_policy_version,
        },
    )


def _not_found_http(error: SlateFunctionStoreError) -> HTTPException:
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

    V189 compares ``author_actor_key`` and ``approver_actor_key`` rather than the nullable user
    ids, because those are ``ON DELETE SET NULL`` and a genuine two-person approval must not
    become two indistinguishable NULLs when somebody is offboarded. This is the value that goes
    into those columns, and into ``granted_by_actor_key`` for the same reason.

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
        The parsed datetime, or None. For a capability that means a missing expiry, which
        :func:`evaluate_capability_safety` has already refused for the grants that need one — so
        this fails toward the safe answer rather than toward a privilege that never lapses.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _warning_bodies(warnings: Any) -> List[FunctionWarningBody]:
    """Map planner warnings onto their wire model."""
    bodies: List[FunctionWarningBody] = []
    for warning in warnings:
        if isinstance(warning, Mapping):
            bodies.append(
                FunctionWarningBody(
                    code=str(warning.get("code") or ""),
                    message=str(warning.get("message") or ""),
                    field=str(warning.get("field") or ""),
                )
            )
        else:
            bodies.append(
                FunctionWarningBody(
                    code=warning.code, message=warning.message, field=warning.field or ""
                )
            )
    return bodies


def _secret_body(row: Mapping[str, Any]) -> SecretRefBody:
    """Map a secret reference row onto its wire model. There is no value to map."""
    return SecretRefBody(
        id=str(row["id"]) if row.get("id") else None,
        function_id=str(row.get("function_id") or ""),
        secret_name=str(row.get("secret_name") or ""),
        alias=str(row.get("alias") or ""),
        scope=str(row.get("scope") or "function"),
        actor_name=str(row.get("actor_name") or ""),
    )


def _capability_body(row: Mapping[str, Any]) -> CapabilityGrantBody:
    """Map a capability grant row onto its wire model."""
    return CapabilityGrantBody(
        id=str(row["id"]) if row.get("id") else None,
        function_id=str(row.get("function_id") or ""),
        capability=str(row.get("capability") or ""),
        reason=str(row.get("reason") or ""),
        expires_at=_iso(row.get("expires_at")),
        granted_at=_iso(row.get("granted_at")),
        granted_by=str(row.get("granted_by_actor_name") or ""),
    )


def _egress_body(row: Mapping[str, Any]) -> EgressRuleBody:
    """Map an egress allowlist row onto its wire model."""
    return EgressRuleBody(
        id=str(row["id"]) if row.get("id") else None,
        function_id=str(row.get("function_id") or ""),
        destination_kind=str(row.get("destination_kind") or "exact-host"),
        destination=str(row.get("destination") or ""),
        scheme=str(row.get("scheme") or "https"),
        port=row.get("port"),
        methods=list(row.get("methods") or []),
        reason=str(row.get("reason") or ""),
        expires_at=_iso(row.get("expires_at")),
        granted_by=str(row.get("granted_by_actor_name") or ""),
    )


def _variant_body(row: Mapping[str, Any]) -> VariantBody:
    """Map a personalization variant row onto its wire model."""
    return VariantBody(
        id=str(row["id"]) if row.get("id") else None,
        function_id=str(row.get("function_id") or ""),
        ordinal=int(row.get("ordinal") or 0),
        enabled=bool(row.get("enabled", True)),
        label=str(row.get("label") or ""),
        audience_kind=str(row.get("audience_kind") or "geo"),
        audience_matcher=list(row.get("audience_matcher") or []),
        fallback_variant=str(row.get("fallback_variant") or ""),
        cache_key_effect=str(row.get("cache_key_effect") or "none"),
        vary_dimension=str(row.get("vary_dimension") or ""),
        analytics_dimension=str(row.get("analytics_dimension") or ""),
        privacy_class=str(row.get("privacy_class") or "non-personal"),
        consent_basis=str(row.get("consent_basis") or "not-required"),
    )


def _version_body(row: Mapping[str, Any]) -> FunctionVersionBody:
    """Map an immutable version row onto its wire model."""
    return FunctionVersionBody(
        id=str(row.get("id") or ""),
        revision=int(row.get("revision") or 1),
        source_digest=str(row.get("source_digest") or ""),
        runtime=str(row.get("runtime") or ""),
        source_bytes=row.get("source_bytes"),
        source_origin=str(row.get("source_origin") or "upload"),
        source_ref=row.get("source_ref"),
        created_at=_iso(row.get("created_at")),
        created_by=str(row.get("created_by_actor_name") or ""),
        body=dict(row.get("body") or {}),
    )


def _function_body(
    row: Mapping[str, Any],
    *,
    capabilities: Any = (),
    egress: Any = (),
    secrets: Any = (),
    variants: Any = (),
) -> FunctionBody:
    """Map a function row onto its wire model, with its grants and variants attached.

    Grants and variants travel with the function rather than behind separate reads for the reason
    V189 stores the variant fields in one row: an operator deciding whether a function is safe is
    reading its privileges and its personalization together, and a surface that made that two
    round trips would make the two drift on screen.
    """
    function_id = str(row.get("id") or "")
    return FunctionBody(
        id=function_id or None,
        ordinal=int(row.get("ordinal") or 0),
        enabled=bool(row.get("enabled", True)),
        label=str(row.get("label") or ""),
        matcher_kind=str(row.get("matcher_kind") or "prefix"),
        matcher_value=str(row.get("matcher_value") or "/"),
        matcher_methods=list(row.get("matcher_methods") or []),
        matcher_hosts=list(row.get("matcher_hosts") or []),
        runtime=str(row.get("runtime") or "js-isolate"),
        active_version_id=(
            str(row["active_version_id"]) if row.get("active_version_id") else None
        ),
        rollout_mode=str(row.get("rollout_mode") or "simulate"),
        rollout_percent=int(row.get("rollout_percent") or 0),
        region=row.get("region"),
        residency_class=row.get("residency_class"),
        cpu_ms_limit=row.get("cpu_ms_limit"),
        memory_mb_limit=row.get("memory_mb_limit"),
        wall_ms_limit=row.get("wall_ms_limit"),
        env_var_names=list(row.get("env_var_names") or []),
        declared_destinations=list(row.get("declared_destinations") or []),
        acknowledged_warnings=list(row.get("acknowledged_warnings") or []),
        body_digest=str(row.get("body_digest") or ""),
        revision=int(row.get("revision") or 1),
        capabilities=[
            _capability_body(grant)
            for grant in capabilities
            if not function_id or str(grant.get("function_id") or "") == function_id
        ],
        egress=[
            _egress_body(rule)
            for rule in egress
            if not function_id or str(rule.get("function_id") or "") == function_id
        ],
        secrets=[
            _secret_body(ref)
            for ref in secrets
            if not function_id or str(ref.get("function_id") or "") == function_id
        ],
        variants=[
            _variant_body(variant)
            for variant in variants
            if not function_id or str(variant.get("function_id") or "") == function_id
        ],
    )


def _policy_for(tenant_id: str, environment: Mapping[str, Any], auth_data: Mapping[str, Any]):
    """Load or create the lane's function policy."""
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


def _function_columns(candidate: Mapping[str, Any], digest: str) -> Dict[str, Any]:
    """Reduce a validated function body to the V189 columns a write sets.

    Args:
        candidate: The function body as submitted, already normalized.
        digest: The content digest of its decisive fields.

    Returns:
        Column values. ``declared_destinations`` is deliberately absent: it comes from the version
        manifest rather than from the function row, and V189 has no column for it.
    """
    normalized = normalize_function(candidate)
    return {
        "ordinal": normalized["ordinal"],
        "enabled": normalized["enabled"],
        "label": normalized["label"],
        "matcher_kind": normalized["matcher_kind"],
        "matcher_value": normalized["matcher_value"],
        "matcher_methods": normalized["matcher_methods"],
        "matcher_hosts": normalized["matcher_hosts"],
        "runtime": normalized["runtime"],
        "active_version_id": normalized["active_version_id"],
        "rollout_mode": normalized["rollout_mode"],
        "rollout_percent": normalized["rollout_percent"],
        "region": normalized["region"],
        "residency_class": normalized["residency_class"],
        "cpu_ms_limit": normalized["cpu_ms_limit"],
        "memory_mb_limit": normalized["memory_mb_limit"],
        "wall_ms_limit": normalized["wall_ms_limit"],
        "env_var_names": normalized["env_var_names"],
        "acknowledged_warnings": normalized["acknowledged_warnings"],
        "body_digest": digest,
    }


def _evaluation_candidate(
    *,
    tenant_id: str,
    environment_id: str,
    function_id: Optional[str],
    body: Mapping[str, Any],
    auth_data: Mapping[str, Any],
) -> tuple[Dict[str, Any], str]:
    """Assemble the body :func:`evaluate_function_safety` judges, with its history attached.

    Four of the fields that decide a refusal are not in the request and must not be: the tenant
    and lane the function belongs to, the author's identity, the approvals on file, and whether
    this function has ever run in simulate. A client able to assert any of them could promote code
    into the request path without review. So all of them are resolved here from the authenticated
    caller and from the database.

    Args:
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function being replaced, or None for a create.
        body: The submitted function fields.
        auth_data: The auth dict.

    Returns:
        The candidate body, and the digest of its decisive fields — which is what an approval must
        name and what the write records.
    """
    candidate = dict(body)
    candidate["id"] = function_id or ""
    candidate["tenant_id"] = tenant_id
    candidate["environment_id"] = environment_id
    candidate["author_actor_key"] = _actor_key(auth_data)

    history = function_evaluation_context(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )
    candidate["simulated_at"] = history["simulated_at"]
    candidate["previous_rollout_percent"] = history["previous_rollout_percent"]

    digest = body_digest(candidate)
    # An edit to an existing function looks up approvals by subject, so an approval of the
    # *previous* body is found and reported as approval-stale rather than as no approval at all —
    # the two need different actions from the operator. A create has no subject yet, so the digest
    # is the only handle there is.
    if function_id:
        approvals = list_approvals(
            db, tenant_id=tenant_id, environment_id=environment_id, subject_id=function_id
        )
    else:
        approvals = list_approvals(
            db, tenant_id=tenant_id, environment_id=environment_id, digest=digest
        )
    candidate["approvals"] = approvals
    return candidate, digest


# ─── Catalog routes ──────────────────────────────────────────────────────────


@router.get(
    "/functions/presets", response_model=FunctionPresetsResponse, response_model_by_alias=True
)
async def get_function_presets(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> FunctionPresetsResponse:
    """Return the residency postures and cache-key effects as data.

    §29.7 gives the Publisher safe presets and never a runtime, and a preset is its fields rather
    than its name. A residency option that cannot say what it does *not* cover is one nobody can
    honestly choose, which is why ``doesNotCover`` is a required field here rather than
    documentation somewhere else.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return FunctionPresetsResponse(
        residency_classes=[
            ResidencyClassBody(
                key=posture.key,
                label=posture.label,
                intent=posture.intent,
                expected_impact=posture.expected_impact,
                does_not_cover=posture.does_not_cover,
                permits_personal=posture.permits_personal,
                requires_waiver_reason=posture.requires_waiver_reason,
                unsafe_if=list(posture.unsafe_if),
            )
            for posture in RESIDENCY_CLASS_CATALOG.values()
        ],
        cache_key_effects=[
            CacheKeyEffectBody(
                key=effect.key,
                label=effect.label,
                intent=effect.intent,
                expected_impact=effect.expected_impact,
                fragments_cache=effect.fragments_cache,
                safe_for_personal=effect.safe_for_personal,
                unsafe_if=list(effect.unsafe_if),
            )
            for effect in CACHE_KEY_EFFECT_CATALOG.values()
        ],
    )


@router.get("/functions/runtimes", response_model=RuntimesResponse, response_model_by_alias=True)
async def get_function_runtimes(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> RuntimesResponse:
    """Return the execution runtime catalog.

    Each runtime states what its sandbox contains and what escaping it would cost. A runtime that
    cannot say that is a runtime nobody can safely choose.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return RuntimesResponse(
        runtimes=[
            RuntimeBody(
                key=profile.key,
                label=profile.label,
                intent=profile.intent,
                expected_impact=profile.expected_impact,
                sandbox=profile.sandbox,
                unsafe_if=list(profile.unsafe_if),
            )
            for profile in RUNTIME_CATALOG.values()
        ]
    )


@router.get(
    "/functions/capabilities", response_model=CapabilitiesResponse, response_model_by_alias=True
)
async def get_function_capabilities(
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CapabilitiesResponse:
    """Return the runtime capability catalog, with what each grant opens and what it is unsafe for.

    Deny-by-default is modelled as the absence of a row, so no table anywhere lists what the
    capabilities are. This endpoint is that list — versioned in code and reviewable in a diff
    rather than seeded per tenant — and it is the only way an operator can read what a grant costs
    before making one.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    return CapabilitiesResponse(
        capabilities=[
            CapabilityBody(
                id=definition.id,
                title=definition.title,
                description=definition.description,
                expected_impact=definition.expected_impact,
                requires_expiry=definition.requires_expiry,
                privacy_reach=definition.privacy_reach,
                unsafe_if=list(definition.unsafe_if),
            )
            for definition in CAPABILITY_CATALOG.values()
        ]
    )


# ─── Policy routes ───────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/functions",
    response_model=FunctionPolicyResponse,
    response_model_by_alias=True,
)
async def get_function_policy(
    environment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> FunctionPolicyResponse:
    """Return a lane's function policy, every function with its privileges, and what it runs."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    policy = _policy_for(tenant_id, environment, auth_data)

    functions = list_functions(db, tenant_id=tenant_id, environment_id=environment_id)
    capabilities = list_capabilities(db, tenant_id=tenant_id, environment_id=environment_id)
    egress = list_egress_rules(db, tenant_id=tenant_id, environment_id=environment_id)
    secrets = list_secret_refs(db, tenant_id=tenant_id, environment_id=environment_id)
    variants = list_variants(db, tenant_id=tenant_id, environment_id=environment_id)

    return FunctionPolicyResponse(
        environment_id=environment_id,
        functions_enabled=bool(policy.get("functions_enabled")),
        policy_version=int(policy.get("policy_version") or 0),
        edge_attached=bool(policy.get("edge_attached")),
        edge_provider=policy.get("edge_provider"),
        default_region=str(policy.get("default_region") or "auto"),
        default_residency_class=str(policy.get("default_residency_class") or "in-region-only"),
        default_cpu_ms_limit=int(policy.get("default_cpu_ms_limit") or 50),
        default_memory_mb_limit=int(policy.get("default_memory_mb_limit") or 128),
        default_wall_ms_limit=int(policy.get("default_wall_ms_limit") or 5000),
        residency_waiver_reason=policy.get("residency_waiver_reason"),
        functions=[
            _function_body(
                row,
                capabilities=capabilities,
                egress=egress,
                secrets=secrets,
                variants=variants,
            )
            for row in functions
        ],
        functions_digest=functions_digest(functions),
        updated_at=_iso(policy.get("updated_at")),
        updated_by=policy.get("updated_by_actor_name"),
    )


# Registered before ``/functions/{function_id}`` so the literal path wins: FastAPI matches in
# registration order, and a policy write arriving at the function handler would be a write to a
# function whose id happened to be the word "policy".
@router.put(
    "/environments/{environment_id}/functions/policy",
    response_model=SetFunctionPolicyResponse,
    response_model_by_alias=True,
)
async def set_function_policy(
    environment_id: str,
    request: SetFunctionPolicyRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SetFunctionPolicyResponse:
    """Change a lane's function policy: whether functions run, where, and within what ceilings.

    Loosening residency to ``unrestricted`` with no stated reason is refused here with a sentence,
    and again by V189's CHECK. Both are deliberate: the operator should meet the explanation, not
    a constraint violation, and no future code path should be able to skip the explanation.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    candidate = {
        "functions_enabled": request.functions_enabled,
        "default_region": request.default_region,
        "default_residency_class": request.default_residency_class,
        "default_cpu_ms_limit": request.default_cpu_ms_limit,
        "default_memory_mb_limit": request.default_memory_mb_limit,
        "default_wall_ms_limit": request.default_wall_ms_limit,
        "residency_waiver_reason": request.residency_waiver_reason,
    }
    try:
        warnings = evaluate_policy_safety(candidate)
    except SlateFunctionRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="policy",
                subject_id=None,
                summary="Function policy change refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return SetFunctionPolicyResponse(
            applied=False,
            dry_run=True,
            functions_enabled=request.functions_enabled,
            default_residency_class=request.default_residency_class,
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        updated = set_policy(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            functions_enabled=request.functions_enabled,
            default_region=request.default_region,
            default_residency_class=request.default_residency_class,
            default_cpu_ms_limit=request.default_cpu_ms_limit,
            default_memory_mb_limit=request.default_memory_mb_limit,
            default_wall_ms_limit=request.default_wall_ms_limit,
            residency_waiver_reason=request.residency_waiver_reason,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=_actor_key(auth_data),
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="policy",
        subject_id=None,
        summary=(
            f"Function policy set to {request.default_residency_class} in "
            f"{request.default_region}"
        ),
        detail=request.reason or request.residency_waiver_reason or None,
    )

    return SetFunctionPolicyResponse(
        applied=True,
        dry_run=False,
        functions_enabled=bool(updated.get("functions_enabled")),
        default_residency_class=str(
            updated.get("default_residency_class") or request.default_residency_class
        ),
        policy_version=int(updated.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


# ─── Function routes ─────────────────────────────────────────────────────────


def _write_function(
    *,
    environment_id: str,
    function_id: Optional[str],
    request: WriteFunctionRequest,
    auth_data: Mapping[str, Any],
) -> WriteFunctionResponse:
    """Shared body of function create and function replace.

    Both verbs run the same gates in the same order, so they live in one function rather than two
    that could drift — and a drift between create and replace would mean code could be introduced
    into the request path by whichever verb had the weaker check.

    Args:
        environment_id: The lane.
        function_id: Existing function to replace, or None to create.
        request: The function body.
        auth_data: The auth dict.

    Returns:
        The write outcome.

    Raises:
        HTTPException: 409 on a refusal or a lost update; 404 when the function is not on the lane.
    """
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    candidate, digest = _evaluation_candidate(
        tenant_id=tenant_id,
        environment_id=environment_id,
        function_id=function_id,
        body=request.model_dump(),
        auth_data=auth_data,
    )
    siblings = list_functions(db, tenant_id=tenant_id, environment_id=environment_id)
    secrets = list_secret_refs(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )
    egress = list_egress_rules(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )

    try:
        warnings = evaluate_function_safety(
            candidate,
            siblings=siblings,
            policy=policy,
            secret_refs=secrets,
            egress_rules=egress,
            now=datetime.now(timezone.utc),
        )
    except SlateFunctionRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="function",
                subject_id=function_id,
                summary="Function refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteFunctionResponse(
            applied=False,
            dry_run=True,
            function=_function_body({**candidate, "body_digest": digest}),
            body_digest=digest,
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        written = upsert_function(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            values=_function_columns(candidate, digest),
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="function",
        subject_id=str(written.get("id")) if written.get("id") else function_id,
        summary=f"Function {'updated' if function_id else 'created'}: {request.label}",
        detail=request.reason or None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return WriteFunctionResponse(
        applied=True,
        dry_run=False,
        function=_function_body(written),
        body_digest=digest,
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/functions",
    response_model=WriteFunctionResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_function(
    environment_id: str,
    request: WriteFunctionRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteFunctionResponse:
    """Create a function, refusing an unsafe one by name."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_function(
        environment_id=environment_id, function_id=None, request=request, auth_data=auth_data
    )


@router.put(
    "/environments/{environment_id}/functions/{function_id}",
    response_model=WriteFunctionResponse,
    response_model_by_alias=True,
)
async def replace_function(
    environment_id: str,
    function_id: str,
    request: WriteFunctionRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteFunctionResponse:
    """Replace a function, running the same gates as a create."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_function(
        environment_id=environment_id,
        function_id=function_id,
        request=request,
        auth_data=auth_data,
    )


@router.delete(
    "/environments/{environment_id}/functions/{function_id}",
    response_model=DeleteFunctionResponse,
    response_model_by_alias=True,
)
async def remove_function(
    environment_id: str,
    function_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteFunctionResponse:
    """Remove a function, keeping its body so the removal can be undone."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteFunctionResponse(
            deleted=False, dry_run=True, policy_version=int(policy.get("policy_version") or 0)
        )

    try:
        delete_function(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            expected_policy_version=expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="function",
        subject_id=function_id,
        summary="Function removed",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return DeleteFunctionResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed.get("policy_version") or 0)
    )


@router.post(
    "/environments/{environment_id}/functions/{function_id}/versions",
    response_model=AddVersionResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def add_function_version(
    environment_id: str,
    function_id: str,
    request: AddVersionRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> AddVersionResponse:
    """Record a new immutable source version, optionally promoting it to live.

    Versions are written once and never edited: promoting different code moves the function's
    ``activeVersionId`` rather than reshaping a stored artifact. Promoting is still a change to the
    function, so the function's prior body is recorded as a ``version-added`` revision before the
    pointer moves.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if request.dry_run:
        return AddVersionResponse(
            applied=False,
            dry_run=True,
            version=None,
            activated=False,
            policy_version=int(policy.get("policy_version") or 0),
        )

    try:
        written = add_version(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            source_digest=request.source_digest,
            body=request.body,
            runtime=request.runtime,
            source_bytes=request.source_bytes,
            source_origin=request.source_origin,
            source_ref=request.source_ref,
            activate=request.activate,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="version",
        subject_id=str(written.get("id")) if written.get("id") else function_id,
        summary=(
            f"Function version added{' and activated' if request.activate else ''}: "
            f"{request.source_digest}"
        ),
        detail=request.reason or request.source_ref or None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return AddVersionResponse(
        applied=True,
        dry_run=False,
        version=_version_body(written),
        activated=request.activate,
        policy_version=int(refreshed.get("policy_version") or 0),
    )


@router.post(
    "/environments/{environment_id}/functions/{function_id}/rollout",
    response_model=WriteFunctionResponse,
    response_model_by_alias=True,
)
async def set_function_rollout(
    environment_id: str,
    function_id: str,
    request: RolloutRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteFunctionResponse:
    """Advance or retreat a function's staged rollout.

    This is where dual control actually bites. A function can be written in simulate freely; the
    write that puts code into the request path runs the same
    :func:`app.slate_functions.evaluate_function_safety` gate as a body edit, so it is refused as
    ``enforce-without-version``, ``enforce-without-simulation``, ``enforce-without-approval``,
    ``approval-stale`` or ``approval-self`` rather than succeeding because it happened to arrive by
    a different route.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    existing = get_function(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "function_not_found", "message": f"Function {function_id} not found."},
        )

    merged = {
        **existing,
        "rollout_mode": request.rollout_mode,
        "rollout_percent": request.rollout_percent,
    }
    candidate, digest = _evaluation_candidate(
        tenant_id=tenant_id,
        environment_id=environment_id,
        function_id=function_id,
        body=merged,
        auth_data=auth_data,
    )
    siblings = list_functions(db, tenant_id=tenant_id, environment_id=environment_id)
    secrets = list_secret_refs(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )
    egress = list_egress_rules(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )

    try:
        warnings = evaluate_function_safety(
            candidate,
            siblings=siblings,
            policy=policy,
            secret_refs=secrets,
            egress_rules=egress,
            now=datetime.now(timezone.utc),
        )
    except SlateFunctionRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="function",
                subject_id=function_id,
                summary="Function rollout refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteFunctionResponse(
            applied=False,
            dry_run=True,
            function=_function_body(merged),
            body_digest=digest,
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        written = set_rollout(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            rollout_mode=request.rollout_mode,
            rollout_percent=request.rollout_percent,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="function",
        subject_id=function_id,
        summary=(
            f"Function rollout set to {request.rollout_mode} at {request.rollout_percent}%"
        ),
        detail=request.reason or None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return WriteFunctionResponse(
        applied=True,
        dry_run=False,
        function=_function_body(written),
        body_digest=digest,
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/functions/{function_id}/revert",
    response_model=WriteFunctionResponse,
    response_model_by_alias=True,
)
async def revert_function_route(
    environment_id: str,
    function_id: str,
    request: RevertRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteFunctionResponse:
    """Restore a function to a stored revision.

    Reverting applies the recorded document rather than reconstructing intent from an audit
    sentence, which is what makes §29.5's "every function change can be reverted" a fact about this
    system rather than a claim about it.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if request.dry_run:
        return WriteFunctionResponse(
            applied=False,
            dry_run=True,
            function=None,
            body_digest="",
            policy_version=int(policy.get("policy_version") or 0),
        )

    try:
        written = revert_function(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            revision=request.revision,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="revert",
        subject_id=function_id,
        summary=f"Function reverted to revision {request.revision}",
        detail=request.reason or None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return WriteFunctionResponse(
        applied=True,
        dry_run=False,
        function=_function_body(written),
        body_digest=str(written.get("body_digest") or ""),
        policy_version=int(refreshed.get("policy_version") or 0),
    )


@router.get(
    "/environments/{environment_id}/functions/{function_id}/revisions",
    response_model=RevisionsResponse,
    response_model_by_alias=True,
)
async def get_function_revisions(
    environment_id: str,
    function_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> RevisionsResponse:
    """Return a function's revision history and its immutable versions, newest first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_revisions(db, tenant_id=tenant_id, function_id=function_id, limit=limit)
    versions = list_versions(db, tenant_id=tenant_id, function_id=function_id, limit=limit)
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
        ],
        versions=[_version_body(version) for version in versions],
    )


# ─── Secret references ───────────────────────────────────────────────────────


@router.put(
    "/environments/{environment_id}/functions/{function_id}/secrets",
    response_model=SecretRefResponse,
    response_model_by_alias=True,
)
async def set_function_secret_ref(
    environment_id: str,
    function_id: str,
    request: SetSecretRefRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SecretRefResponse:
    """Declare a secret reference on a function.

    There is no value field on this request and no value column in the schema behind it, which is
    §29.5's first flat prohibition made a schema impossibility rather than a validation. The half a
    schema cannot express — that the reference stays inside this function's own boundary — is
    refused here as ``secret-cross-project``, with no acknowledgement path, because a cross-project
    reference is not a cost somebody may accept on their own authority.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    existing = get_function(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "function_not_found", "message": f"Function {function_id} not found."},
        )

    proposed = {
        "function_id": function_id,
        "secret_name": request.secret_name,
        "alias": request.alias,
        "scope": request.scope,
        "owner_tenant_id": request.owner_tenant_id,
        "owner_environment_id": request.owner_environment_id,
        "owner_function_id": request.owner_function_id,
    }
    # The declared destinations are stripped from the probe: whether this function can reach a
    # host is an egress question that this request did not change, and re-deriving it here would
    # refuse a secret declaration for somebody else's unrelated problem.
    probe = {
        **existing,
        "id": function_id,
        "tenant_id": tenant_id,
        "environment_id": environment_id,
        "declared_destinations": [],
    }
    try:
        evaluate_function_safety(
            probe,
            siblings=[],
            policy=policy,
            secret_refs=[proposed],
            now=datetime.now(timezone.utc),
        )
    except SlateFunctionRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="secret-ref",
                subject_id=function_id,
                summary="Secret reference refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return SecretRefResponse(
            applied=False,
            dry_run=True,
            secret=_secret_body(proposed),
            policy_version=int(policy.get("policy_version") or 0),
        )

    try:
        written = set_secret_ref(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            secret_name=request.secret_name,
            alias=request.alias,
            scope=request.scope,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="secret-ref",
        subject_id=str(written.get("id")) if written.get("id") else function_id,
        summary=f"Secret reference {request.alias} declared",
        detail=f"{request.secret_name} at {request.scope} scope",
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return SecretRefResponse(
        applied=True,
        dry_run=False,
        secret=_secret_body(written),
        policy_version=int(refreshed.get("policy_version") or 0),
    )


@router.delete(
    "/environments/{environment_id}/functions/{function_id}/secrets/{ref_id}",
    response_model=DeleteGrantResponse,
    response_model_by_alias=True,
)
async def remove_function_secret_ref(
    environment_id: str,
    function_id: str,
    ref_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteGrantResponse:
    """Withdraw a secret reference."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteGrantResponse(
            deleted=False, dry_run=True, policy_version=int(policy.get("policy_version") or 0)
        )

    try:
        delete_secret_ref(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            ref_id=ref_id,
            expected_policy_version=expected_policy_version,
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="secret-ref",
        subject_id=ref_id,
        summary="Secret reference withdrawn",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return DeleteGrantResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed.get("policy_version") or 0)
    )


# ─── Capabilities ────────────────────────────────────────────────────────────


@router.put(
    "/environments/{environment_id}/functions/{function_id}/capabilities",
    response_model=CapabilityGrantResponse,
    response_model_by_alias=True,
)
async def grant_function_capability(
    environment_id: str,
    function_id: str,
    request: GrantCapabilityRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CapabilityGrantResponse:
    """Grant one runtime capability to a function.

    Writing the row *is* the grant; there is no ``granted`` boolean to set. A grant with no stated
    reason is refused as ``capability-without-reason``, and a grant of a standing privilege with no
    end date — or one so distant it is permanent in practice — as ``capability-unbounded``.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    expires_at = _parse_moment(request.expires_at)
    candidate = {
        "function_id": function_id,
        "capability": request.capability,
        "reason": request.reason,
        "expires_at": expires_at,
    }
    try:
        warnings = evaluate_capability_safety(candidate, now=datetime.now(timezone.utc))
    except SlateFunctionRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="capability",
                subject_id=function_id,
                summary="Capability grant refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return CapabilityGrantResponse(
            applied=False,
            dry_run=True,
            capability=_capability_body(candidate),
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        written = grant_capability(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            capability=request.capability,
            reason=request.reason,
            expires_at=expires_at,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=_actor_key(auth_data),
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="capability",
        subject_id=str(written.get("id")) if written.get("id") else function_id,
        summary=f"Capability {request.capability} granted",
        detail=request.reason,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return CapabilityGrantResponse(
        applied=True,
        dry_run=False,
        capability=_capability_body(written),
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.delete(
    "/environments/{environment_id}/functions/{function_id}/capabilities/{capability}",
    response_model=DeleteGrantResponse,
    response_model_by_alias=True,
)
async def revoke_function_capability(
    environment_id: str,
    function_id: str,
    capability: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteGrantResponse:
    """Revoke one capability by deleting its grant row.

    Deleting rather than flipping a flag is the whole design: the absence of a row is the denial,
    so a revocation cannot half-succeed into a state that still permits something.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteGrantResponse(
            deleted=False, dry_run=True, policy_version=int(policy.get("policy_version") or 0)
        )

    try:
        revoke_capability(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            capability=capability,
            expected_policy_version=expected_policy_version,
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="capability",
        subject_id=function_id,
        summary=f"Capability {capability} revoked",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return DeleteGrantResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed.get("policy_version") or 0)
    )


# ─── Egress ──────────────────────────────────────────────────────────────────


@router.put(
    "/environments/{environment_id}/functions/{function_id}/egress",
    response_model=EgressRuleResponse,
    response_model_by_alias=True,
)
async def set_function_egress_rule(
    environment_id: str,
    function_id: str,
    request: SetEgressRuleRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> EgressRuleResponse:
    """Allowlist one outbound destination for a function.

    Deny-by-default in the same shape as a capability: the row is the allowance, and there is no
    wildcard kind to write. An entry with no stated reason is refused, and an entry that does not
    actually cover the destinations the caller says it is for is refused as ``egress-unapproved``
    rather than written and discovered to be inert in production.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    expires_at = _parse_moment(request.expires_at)
    candidate = {
        "function_id": function_id,
        "destination_kind": request.destination_kind,
        "destination": request.destination,
        "scheme": request.scheme,
        "port": request.port,
        "methods": request.methods,
        "reason": request.reason,
        "expires_at": expires_at,
    }
    try:
        warnings = evaluate_egress_safety(
            candidate,
            destinations=request.destinations,
            now=datetime.now(timezone.utc),
        )
    except SlateFunctionRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="egress-rule",
                subject_id=function_id,
                summary="Egress allowance refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return EgressRuleResponse(
            applied=False,
            dry_run=True,
            egress=_egress_body(candidate),
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        written = set_egress_rule(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            destination_kind=request.destination_kind,
            destination=request.destination,
            scheme=request.scheme,
            port=request.port,
            methods=request.methods,
            reason=request.reason,
            expires_at=expires_at,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
            actor_key=_actor_key(auth_data),
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="egress-rule",
        subject_id=str(written.get("id")) if written.get("id") else function_id,
        summary=f"Egress allowed to {request.destination_kind} {request.destination}",
        detail=request.reason,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return EgressRuleResponse(
        applied=True,
        dry_run=False,
        egress=_egress_body(written),
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.delete(
    "/environments/{environment_id}/functions/{function_id}/egress/{rule_id}",
    response_model=DeleteGrantResponse,
    response_model_by_alias=True,
)
async def remove_function_egress_rule(
    environment_id: str,
    function_id: str,
    rule_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteGrantResponse:
    """Withdraw an egress allowance by deleting its row."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteGrantResponse(
            deleted=False, dry_run=True, policy_version=int(policy.get("policy_version") or 0)
        )

    try:
        delete_egress_rule(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=function_id,
            rule_id=rule_id,
            expected_policy_version=expected_policy_version,
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="egress-rule",
        subject_id=rule_id,
        summary="Egress allowance withdrawn",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return DeleteGrantResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed.get("policy_version") or 0)
    )


# ─── Personalization variants ────────────────────────────────────────────────


def _write_variant(
    *,
    environment_id: str,
    variant_id: Optional[str],
    request: WriteVariantRequest,
    auth_data: Mapping[str, Any],
) -> WriteVariantResponse:
    """Shared body of variant create and variant replace.

    Both verbs run :func:`app.slate_functions.evaluate_variant_safety`, which is where a variant
    that personalizes without saying something safe about the shared cache key is refused rather
    than warned about — the defect that serves one reader's page to another.

    Args:
        environment_id: The lane.
        variant_id: Existing variant to replace, or None to create.
        request: The variant body.
        auth_data: The auth dict.

    Returns:
        The write outcome.
    """
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    function = (
        get_function(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_id=request.function_id,
        )
        if request.function_id
        else None
    )

    candidate = request.model_dump()
    candidate["id"] = variant_id or ""
    try:
        warnings = evaluate_variant_safety(candidate, function=function, policy=policy)
    except SlateFunctionRefusedError as exc:
        if not request.dry_run:
            _audit(
                tenant_id=tenant_id,
                environment_id=environment_id,
                actor=actor,
                subject_kind="variant",
                subject_id=variant_id,
                summary="Personalization variant refused",
                detail=f"{exc.refusal.reason}: {exc.refusal.sentence}",
            )
        raise _refusal_http(exc) from exc

    if request.dry_run:
        return WriteVariantResponse(
            applied=False,
            dry_run=True,
            variant=_variant_body(candidate),
            policy_version=int(policy.get("policy_version") or 0),
            warnings=_warning_bodies(warnings),
        )

    try:
        written = upsert_variant(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            variant_id=variant_id,
            function_id=request.function_id,
            values=candidate,
            expected_policy_version=request.expected_policy_version,
            actor_id=actor[0],
            actor_name=actor[1],
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="variant",
        subject_id=str(written.get("id")) if written.get("id") else variant_id,
        summary=f"Personalization variant {'updated' if variant_id else 'created'}: {request.label}",
        detail=(
            f"{request.privacy_class} on a {request.consent_basis} basis, cache key "
            f"{request.cache_key_effect}"
        ),
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return WriteVariantResponse(
        applied=True,
        dry_run=False,
        variant=_variant_body(written),
        policy_version=int(refreshed.get("policy_version") or 0),
        warnings=_warning_bodies(warnings),
    )


@router.post(
    "/environments/{environment_id}/functions/variants",
    response_model=WriteVariantResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_variant(
    environment_id: str,
    request: WriteVariantRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteVariantResponse:
    """Create a personalization variant, refusing an unsafe one by name."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_variant(
        environment_id=environment_id, variant_id=None, request=request, auth_data=auth_data
    )


@router.put(
    "/environments/{environment_id}/functions/variants/{variant_id}",
    response_model=WriteVariantResponse,
    response_model_by_alias=True,
)
async def replace_variant(
    environment_id: str,
    variant_id: str,
    request: WriteVariantRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> WriteVariantResponse:
    """Replace a personalization variant, running the same gates as a create."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    return _write_variant(
        environment_id=environment_id,
        variant_id=variant_id,
        request=request,
        auth_data=auth_data,
    )


@router.delete(
    "/environments/{environment_id}/functions/variants/{variant_id}",
    response_model=DeleteVariantResponse,
    response_model_by_alias=True,
)
async def remove_variant(
    environment_id: str,
    variant_id: str,
    expected_policy_version: int = Query(alias="expectedPolicyVersion"),
    dry_run: bool = Query(default=False, alias="dryRun"),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> DeleteVariantResponse:
    """Remove a personalization variant."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    policy = _policy_for(tenant_id, environment, auth_data)

    if dry_run:
        return DeleteVariantResponse(
            deleted=False, dry_run=True, policy_version=int(policy.get("policy_version") or 0)
        )

    try:
        delete_variant(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            variant_id=variant_id,
            expected_policy_version=expected_policy_version,
        )
    except SlateFunctionPolicyConflictError as exc:
        raise _conflict_http(exc) from exc
    except SlateFunctionStoreError as exc:
        raise _not_found_http(exc) from exc

    _audit(
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor=actor,
        subject_kind="variant",
        subject_id=variant_id,
        summary="Personalization variant removed",
        detail=None,
    )

    refreshed = _policy_for(tenant_id, environment, auth_data)
    return DeleteVariantResponse(
        deleted=True, dry_run=False, policy_version=int(refreshed.get("policy_version") or 0)
    )


# ─── Approvals ───────────────────────────────────────────────────────────────


@router.post(
    "/environments/{environment_id}/functions/approvals",
    response_model=ApprovalBody,
    response_model_by_alias=True,
    status_code=201,
)
async def record_function_approval(
    environment_id: str,
    request: ApprovalRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> ApprovalBody:
    """Record the approving half of dual control.

    The approver is always the *authenticated caller* — there is no field by which one person can
    record somebody else's approval, which is the only version of two-person review that means
    anything. Approving one's own change is refused here as ``approval-self`` and again by V189's
    ``CHECK (approver_actor_key <> author_actor_key)``.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor = _actor(auth_data)
    approver_key = _actor_key(auth_data)

    if approver_key == request.author_actor_key:
        raise _refusal_http(SlateFunctionRefusedError(FunctionRefusal.of("approval-self")))

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
    "/environments/{environment_id}/functions/simulate",
    response_model=SimulateResponse,
    response_model_by_alias=True,
)
async def simulate_function_invocation(
    environment_id: str,
    request: SimulateCommandBody,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> SimulateResponse:
    """Explain what this lane's policy decides for a test request, and why every function lost.

    A read, not a write, unless ``persist`` is set — and VIEW rather than PUBLISH deliberately.
    "Which function served this customer", or "why did my function not run", is the question that
    brings an operator here during an incident, so requiring PUBLISH would put the answer out of
    reach of exactly the person asking.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    policy = _policy_for(tenant_id, environment, auth_data)

    if request.functions is not None:
        functions: List[Dict[str, Any]] = [fn.model_dump() for fn in request.functions]
    else:
        functions = list_functions(db, tenant_id=tenant_id, environment_id=environment_id)

    variants = list_variants(db, tenant_id=tenant_id, environment_id=environment_id)
    capabilities = list_capabilities(db, tenant_id=tenant_id, environment_id=environment_id)
    egress = list_egress_rules(db, tenant_id=tenant_id, environment_id=environment_id)

    verdict = simulate_invocation(
        request=InvocationRequest(
            method=request.request.method,
            host=request.request.host,
            path=request.request.path,
            country=request.request.country,
            language=request.request.language,
            device=request.request.device,
            cohort=request.request.cohort,
            experiment=request.request.experiment,
            requested_capabilities=tuple(request.request.requested_capabilities),
            requested_destinations=tuple(request.request.requested_destinations),
            estimated_cpu_ms=request.request.estimated_cpu_ms,
            estimated_wall_ms=request.request.estimated_wall_ms,
            estimated_memory_mb=request.request.estimated_memory_mb,
            headers=request.request.headers,
        ),
        policy=policy,
        functions=functions,
        variants=variants,
        capabilities=capabilities,
        egress_rules=egress,
        now=datetime.now(timezone.utc),
    )

    invocation_id: Optional[str] = None
    if request.persist:
        basis_release_id = environment.get("active_release_id")
        written = record_invocation(
            db,
            tenant_id=tenant_id,
            environment_id=environment_id,
            function_ref=str(verdict.function_ref or "none"),
            function_label=verdict.function_label,
            route=request.request.path,
            method=request.request.method.upper(),
            release_id=str(basis_release_id) if basis_release_id else None,
            region=verdict.region or None,
            variant_ref=verdict.variant_ref,
            outcome=verdict.outcome,
            denial_reason=verdict.denial_reason,
            # Raw request data goes in; the store redacts. A caller cannot pass redacted evidence
            # and a caller cannot skip the redaction, because there is no other way in.
            evidence={
                "method": request.request.method.upper(),
                "path": request.request.path,
                "userAgent": request.request.headers.get("user-agent", ""),
                "country": request.request.country,
                "region": verdict.region,
                "variant": verdict.variant_label,
                "outcome": verdict.outcome,
                "denialReason": verdict.denial_reason,
                **request.request.headers,
            },
        )
        invocation_id = str(written.get("id")) if written.get("id") else None

    return SimulateResponse(
        outcome=verdict.outcome,
        outcome_reason=verdict.outcome_reason,
        function_ref=verdict.function_ref,
        function_label=verdict.function_label,
        version_ref=verdict.version_ref,
        runtime=verdict.runtime,
        rollout_mode=verdict.rollout_mode,
        rollout_percent=verdict.rollout_percent,
        region=verdict.region,
        residency_class=verdict.residency_class,
        limits=dict(verdict.limits),
        variant_ref=verdict.variant_ref,
        variant_label=verdict.variant_label,
        fallback_variant=verdict.fallback_variant,
        cache_key_effect=verdict.cache_key_effect,
        privacy_class=verdict.privacy_class,
        consent_basis=verdict.consent_basis,
        analytics_dimension=verdict.analytics_dimension,
        capabilities_granted=list(verdict.capabilities_granted),
        capabilities_denied=list(verdict.capabilities_denied),
        egress_allowed=list(verdict.egress_allowed),
        egress_denied=list(verdict.egress_denied),
        denial_reason=verdict.denial_reason,
        considered=[
            SimulationStepBody(
                kind=str(step.get("kind") or ""),
                ref=step.get("ref"),
                label=str(step.get("label") or ""),
                ordinal=step.get("ordinal"),
                outcome=str(step.get("outcome") or ""),
                reason=str(step.get("reason") or ""),
            )
            for step in verdict.considered
        ],
        warnings=_warning_bodies(verdict.warnings),
        functions_digest=verdict.functions_digest,
        policy_version=int(policy.get("policy_version") or 0),
        invocation_id=invocation_id,
    )


# ─── Invocations ─────────────────────────────────────────────────────────────


def _invocation_body(row: Mapping[str, Any]) -> InvocationBody:
    """Map an invocation row onto its wire model."""
    return InvocationBody(
        id=str(row["id"]),
        at=_iso(row.get("at")),
        source=str(row.get("source") or ""),
        function_ref=str(row.get("function_ref") or ""),
        function_label=str(row.get("function_label") or ""),
        route=str(row.get("route") or ""),
        method=str(row.get("method") or ""),
        release_id=str(row["release_id"]) if row.get("release_id") else None,
        region=row.get("region"),
        variant_ref=row.get("variant_ref"),
        outcome=str(row.get("outcome") or ""),
        executed=bool(row.get("executed")),
        edge_attached=bool(row.get("edge_attached")),
        cpu_ms=row.get("cpu_ms"),
        wall_ms=row.get("wall_ms"),
        memory_peak_mb=row.get("memory_peak_mb"),
        denial_reason=row.get("denial_reason"),
        evidence={str(k): str(v) for k, v in (row.get("evidence") or {}).items()},
        retain_until=_iso(row.get("retain_until")),
    )


@router.get(
    "/environments/{environment_id}/functions/invocations",
    response_model=InvocationsResponse,
    response_model_by_alias=True,
)
async def get_function_invocations(
    environment_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    function_ref: Optional[str] = Query(default=None, alias="functionRef"),
    outcome: Optional[str] = Query(default=None),
    route: Optional[str] = Query(default=None),
    release_id: Optional[str] = Query(default=None, alias="releaseId"),
    region: Optional[str] = Query(default=None),
    variant_ref: Optional[str] = Query(default=None, alias="variantRef"),
    source: Optional[str] = Query(default=None),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> InvocationsResponse:
    """Return a lane's invocation records, most recent first.

    The filter names are the designer's dimension ids unchanged, so filtering on screen and
    filtering in a query cannot mean different things. ``variantRef`` is how "which function served
    this customer" gets narrowed down.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    rows = list_invocations(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        limit=limit,
        function_ref=function_ref,
        outcome=outcome,
        route=route,
        release_id=release_id,
        region=region,
        variant_ref=variant_ref,
        source=source,
    )
    return InvocationsResponse(invocations=[_invocation_body(row) for row in rows])


@router.get(
    "/environments/{environment_id}/functions/invocations/{invocation_id}",
    response_model=InvocationBody,
    response_model_by_alias=True,
)
async def get_function_invocation(
    environment_id: str,
    invocation_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> InvocationBody:
    """Return one invocation record with its redacted evidence."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)

    row = get_invocation(
        db, tenant_id=tenant_id, environment_id=environment_id, invocation_id=invocation_id
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "invocation_not_found",
                "message": f"Function invocation {invocation_id} not found.",
            },
        )
    return _invocation_body(row)


# ─── Audit ───────────────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/functions/audit",
    response_model=AuditResponse,
    response_model_by_alias=True,
)
async def get_function_audit(
    environment_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> AuditResponse:
    """Return a lane's append-only function audit trail, most recent first."""
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


@router.get("/environments/{environment_id}/functions/audit/export")
async def export_function_audit(
    environment_id: str,
    limit: int = Query(default=10000, ge=1, le=100000),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> StreamingResponse:
    """Export a lane's function audit trail as CSV.

    VIEW rather than PUBLISH: §29.7 gives the Auditor read-only policy and exportable audit, and an
    export gated behind the permission to *change* functions would be an export the auditor cannot
    run.

    Modelled on ``access_routes.py``'s exporter, and fixing the two defects that precedent carries.

    **CSV injection is neutralized.** A cell whose first character is ``=``, ``+``, ``-``, ``@``, a
    tab or a carriage return is prefixed with an apostrophe. An actor display name and a refusal
    detail are attacker-influenced text, and the existing exporter writes them raw, so opening the
    evidence in a spreadsheet is a code-execution path.

    **Nothing is silently truncated.** The existing exporter caps at 1000 rows with no signal,
    which in compliance evidence is a correctness bug rather than a performance choice: an auditor
    reading a truncated ledger concludes the missing entries never happened. This one reads one row
    past the cap, and when there are more it emits a final row saying so in words.

    Reading the evidence is itself audit-worthy — who exported the record of who let a function
    read secrets is part of that record — so an ``export`` audit row is written before the download
    begins.
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
        summary="Function audit exported",
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
                f'attachment; filename="{environment_id}-function-audit.csv"'
            )
        },
    )
