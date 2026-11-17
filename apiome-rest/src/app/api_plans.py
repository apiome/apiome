"""API plans — the tiers an API product offers (APX-1.2, #6099).

A gateway holds rate limits per consumer group, but the *intent* — what the Standard tier promises —
lives in wikis and contracts. A **plan** declares it on an API product (:mod:`app.api_products`):

======================  ==========================================================================
Field                   Meaning
======================  ==========================================================================
``auth_strategy``       ``key_auth``, ``oauth2_client_credentials``, ``mtls`` or ``none``
``auth_config``         ``header_name`` (key_auth); ``idp_config_id`` and ``scopes`` (OAuth2)
``limits``              ``[{window, requests}]`` — ``window`` one of second, minute, hour, day, month
``concurrency``         optional cap on requests in flight
``approval``            ``auto`` (a subscription is approved at once) or ``manual`` (a person decides)
``environments``        the gateway configs the plan is provisioned to (``kong-prod-cp``)
``credential_ttl_days`` optional maximum key age
``terms_url`` …         terms, a pricing note and an internal ``billing_ref`` (never exported)
======================  ==========================================================================

**Limits validate**: every count is a positive whole number and every window appears once
(:func:`normalize_limits`).

**Declared only.** Apiome provisions a plan onto a gateway through the gateway's connector. A plan
with no environment, or with an environment whose connector cannot provision, is saved as *declared
only*: the intent is recorded and a notice says so, but nothing is pushed to a gateway
(:func:`is_declared_only`, :func:`declared_only_notice`). No connector can provision until APX-4.1
gives connectors that capability, so :data:`PROVISIONING_CONNECTOR_KINDS` is empty for now.

**Auth must match the members.** A plan's strategy should match a security scheme every member
declares — a ``key_auth`` plan over an API that declares only OAuth2 promises a key nobody checks.
A member that does not is reported as an ``api-plan-auth-mismatch`` *warning* on reads; the write is
not refused (:func:`auth_mismatch_warnings`).

**Export.** An OpenAPI export of a revision a product includes carries that product's plans as the
root ``x-apiome-plans`` extension (:func:`plan_extension_entry`); every other target reports them as
dropped in its fidelity report (:func:`plans_loss_item`).

This module holds the shapes and the pure rules; :mod:`app.api_plan_store` reads and writes them and
:mod:`app.api_plan_routes` serves them. Every refusal is an :class:`ApiPlanValidationError` carrying a
stable ``api-plan-*`` code.
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Iterable, List, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .api_products import resolve_slug

__all__ = [
    "APPROVALS",
    "AUTH_STRATEGIES",
    "CODE_ENVIRONMENT_NOT_FOUND",
    "CODE_INVALID",
    "CODE_NOT_FOUND",
    "CODE_SLUG_TAKEN",
    "LIMIT_WINDOWS",
    "MAX_ENVIRONMENTS",
    "MAX_PLANS",
    "NOTICE_DECLARED_ONLY",
    "PLANS_CARRYING_EMITTERS",
    "PLANS_EXTENSION_KEY",
    "PLANS_EXTRAS_KEY",
    "PROVISIONING_CONNECTOR_KINDS",
    "STATES",
    "WARNING_AUTH_MISMATCH",
    "ApiPlanInput",
    "ApiPlanPatch",
    "ApiPlanRecord",
    "ApiPlanValidationError",
    "PlanAuthConfig",
    "PlanEnvironment",
    "PlanLimit",
    "PlanNotice",
    "auth_mismatch_warnings",
    "connector_can_provision",
    "declared_only_notice",
    "is_declared_only",
    "normalize_auth_config",
    "normalize_limits",
    "normalize_plan_name",
    "normalize_terms_url",
    "plan_extension_entry",
    "plans_loss_item",
    "resolve_plan_slug",
    "scheme_satisfies",
]

#: The product has no live plan with that slug.
CODE_NOT_FOUND = "api-plan-not-found"
#: Another live plan of the product already has that slug.
CODE_SLUG_TAKEN = "api-plan-slug-taken"
#: A field is malformed (a repeated limit window, a header name on an OAuth2 plan, …).
CODE_INVALID = "api-plan-invalid"
#: An environment names no live gateway config of the tenant.
CODE_ENVIRONMENT_NOT_FOUND = "api-plan-environment-not-found"

#: Notice: the plan is recorded, but no environment can be provisioned.
NOTICE_DECLARED_ONLY = "api-plan-declared-only"
#: Warning: a member declares no security scheme the plan's auth strategy can use.
WARNING_AUTH_MISMATCH = "api-plan-auth-mismatch"

AUTH_STRATEGIES = ("key_auth", "oauth2_client_credentials", "mtls", "none")
LIMIT_WINDOWS = ("second", "minute", "hour", "day", "month")
APPROVALS = ("auto", "manual")
STATES = ("draft", "published", "deprecated", "retired")

#: Upper bounds, so one product or plan cannot become an unbounded read.
MAX_PLANS = 50
MAX_ENVIRONMENTS = 20
MAX_SCOPES = 50

#: Connector kinds that can provision a plan onto their gateway. Empty until APX-4.1 (#6115) gives
#: connectors the ``provision`` capability, so every plan with environments is declared only today.
PROVISIONING_CONNECTOR_KINDS: FrozenSet[str] = frozenset()

#: Where :func:`app.export_source.load_export_source` puts a revision's plans on the canonical model.
PLANS_EXTRAS_KEY = "apiome_plans"
#: The OpenAPI root extension the plans are written as.
PLANS_EXTENSION_KEY = "x-apiome-plans"
#: Emitter keys that write :data:`PLANS_EXTENSION_KEY`; every other target drops the plans.
PLANS_CARRYING_EMITTERS: FrozenSet[str] = frozenset({"openapi"})

#: A header name: an HTTP token (RFC 9110), at most 128 characters.
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}$")
#: An OAuth2 scope token (RFC 6749 §3.3): printable ASCII without spaces, quotes or backslashes.
_SCOPE = re.compile(r"^[\x21\x23-\x5B\x5D-\x7E]{1,200}$")

#: The security scheme types (OpenAPI ``type``) each strategy can use.
_SCHEME_TYPES: Mapping[str, FrozenSet[str]] = {
    "key_auth": frozenset({"apikey"}),
    "oauth2_client_credentials": frozenset({"oauth2", "openidconnect"}),
    "mtls": frozenset({"mutualtls"}),
}

#: How each strategy reads in a message.
_STRATEGY_WORDS: Mapping[str, str] = {
    "key_auth": "API key scheme",
    "oauth2_client_credentials": "OAuth2 or OpenID Connect scheme",
    "mtls": "mutual TLS scheme",
}

AuthStrategy = Literal["key_auth", "oauth2_client_credentials", "mtls", "none"]
LimitWindow = Literal["second", "minute", "hour", "day", "month"]
Approval = Literal["auto", "manual"]
State = Literal["draft", "published", "deprecated", "retired"]


class ApiPlanValidationError(ValueError):
    """An API plan refusal carrying a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants (or an ``api-product-*`` code when the
            product itself is unknown).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------------------------


class PlanLimit(BaseModel):
    """One declared request limit: ``requests`` per ``window``."""

    model_config = ConfigDict(extra="forbid")

    window: LimitWindow
    requests: int = Field(ge=1, le=10**12, description="Requests allowed per window; a positive whole number.")


class PlanAuthConfig(BaseModel):
    """How the strategy is configured. Names and ids only — never a secret.

    Attributes:
        header_name: ``key_auth`` only: the header the key travels in (default ``apikey`` at the gateway).
        idp_config_id: ``oauth2_client_credentials`` only: the identity-provider configuration to use.
        scopes: ``oauth2_client_credentials`` only: the scopes a client of this plan is granted.
    """

    model_config = ConfigDict(extra="forbid")

    header_name: Optional[str] = Field(default=None, max_length=128)
    idp_config_id: Optional[str] = Field(default=None, max_length=128)
    scopes: List[str] = Field(default_factory=list, max_length=MAX_SCOPES)


class ApiPlanInput(BaseModel):
    """A plan to create.

    Attributes:
        slug: The handle; derived from ``name`` when omitted. Not editable afterwards.
        name: The display name (``Standard``).
        description: What the plan offers.
        auth_strategy: How a consumer authenticates; ``key_auth`` by default.
        auth_config: The strategy's settings.
        limits: Declared request limits, at most one per window.
        concurrency: Optional cap on requests in flight.
        approval: ``manual`` (default) or ``auto``.
        environments: Gateway config slugs or ids the plan is provisioned to.
        credential_ttl_days: Optional maximum key age, in days.
        terms_url: The plan's terms (http or https).
        pricing_note: A short note on price, shown to consumers.
        billing_ref: An external billing id; internal only.
        state: ``draft`` (default), ``published``, ``deprecated`` or ``retired``.
    """

    model_config = ConfigDict(extra="forbid")

    slug: Optional[str] = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    auth_strategy: AuthStrategy = "key_auth"
    auth_config: PlanAuthConfig = Field(default_factory=PlanAuthConfig)
    limits: List[PlanLimit] = Field(default_factory=list, max_length=len(LIMIT_WINDOWS) * 2)
    concurrency: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    approval: Approval = "manual"
    environments: List[str] = Field(default_factory=list, max_length=MAX_ENVIRONMENTS)
    credential_ttl_days: Optional[int] = Field(default=None, ge=1, le=3650)
    terms_url: Optional[str] = Field(default=None, max_length=2048)
    pricing_note: Optional[str] = Field(default=None, max_length=1000)
    billing_ref: Optional[str] = Field(default=None, max_length=200)
    state: State = "draft"


class ApiPlanPatch(BaseModel):
    """A partial update. Omitted fields are left alone; ``null`` clears an optional field.

    ``limits`` and ``environments`` are replaced as a whole. The slug is deliberately absent: it is
    the handle subscriptions name.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    auth_strategy: Optional[AuthStrategy] = None
    auth_config: Optional[PlanAuthConfig] = None
    limits: Optional[List[PlanLimit]] = Field(default=None, max_length=len(LIMIT_WINDOWS) * 2)
    concurrency: Optional[int] = Field(default=None, ge=1, le=1_000_000)
    approval: Optional[Approval] = None
    environments: Optional[List[str]] = Field(default=None, max_length=MAX_ENVIRONMENTS)
    credential_ttl_days: Optional[int] = Field(default=None, ge=1, le=3650)
    terms_url: Optional[str] = Field(default=None, max_length=2048)
    pricing_note: Optional[str] = Field(default=None, max_length=1000)
    billing_ref: Optional[str] = Field(default=None, max_length=200)
    state: Optional[State] = None


class PlanEnvironment(BaseModel):
    """One gateway config a plan is provisioned to, as a read returns it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slug: Optional[str] = Field(default=None, description="The gateway config's slug; `null` when it is gone.")
    name: Optional[str] = None
    environment: Optional[str] = Field(default=None, description="The connector's environment (`prod-cp`).")
    connector_kind: Optional[str] = Field(default=None, description="The connector's kind (`kong-admin`).")
    can_provision: bool = Field(description="Whether the gateway config's connector can provision plans.")
    missing: bool = Field(default=False, description="True when the gateway config was deleted.")


class PlanNotice(BaseModel):
    """A notice or warning about a plan, with the member it concerns when there is one."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    member: Optional[Dict[str, Any]] = Field(
        default=None, description="`{kind, ref, name}` of the member a warning concerns."
    )


class ApiPlanRecord(BaseModel):
    """A stored plan."""

    model_config = ConfigDict(extra="forbid")

    id: str
    product: str = Field(description="The product's slug.")
    slug: str
    name: str
    description: Optional[str] = None
    auth_strategy: AuthStrategy
    auth_config: PlanAuthConfig
    limits: List[PlanLimit] = Field(default_factory=list)
    concurrency: Optional[int] = None
    approval: Approval
    environments: List[PlanEnvironment] = Field(default_factory=list)
    declared_only: bool = Field(
        description="True while no environment can be provisioned: the plan is recorded, not pushed to a gateway."
    )
    credential_ttl_days: Optional[int] = None
    terms_url: Optional[str] = None
    pricing_note: Optional[str] = None
    billing_ref: Optional[str] = Field(default=None, description="Internal; never exported or shown on the portal.")
    state: State
    notices: List[PlanNotice] = Field(default_factory=list, description="E.g. `api-plan-declared-only`.")
    warnings: List[PlanNotice] = Field(
        default_factory=list, description="E.g. `api-plan-auth-mismatch`, one per member that does not match."
    )
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------------------------
# Field rules
# ---------------------------------------------------------------------------------------------


def resolve_plan_slug(slug: Optional[str], name: str) -> str:
    """Return the handle a new plan is stored under (the product slug's rules).

    Args:
        slug: The handle the caller supplied, or ``None`` to derive one from ``name``.
        name: The plan's display name.

    Returns:
        The trimmed, lowercased handle.

    Raises:
        ApiPlanValidationError: ``api-plan-invalid`` when the handle has the wrong shape.
    """
    try:
        return resolve_slug(slug, name)
    except ValueError as exc:
        raise ApiPlanValidationError(CODE_INVALID, str(exc).replace("product slug", "plan slug")) from exc


def normalize_plan_name(name: Optional[str]) -> str:
    """Return a trimmed display name, or refuse a blank one.

    Args:
        name: The candidate name.

    Returns:
        The trimmed name.

    Raises:
        ApiPlanValidationError: ``api-plan-invalid`` when the name is blank.
    """
    trimmed = (name or "").strip()
    if not trimmed:
        raise ApiPlanValidationError(CODE_INVALID, "a plan needs a name")
    return trimmed


def normalize_limits(limits: Sequence[PlanLimit]) -> List[Dict[str, Any]]:
    """Return the limits as stored, shortest window first, refusing a repeated window.

    Args:
        limits: The declared limits (each already positive, by :class:`PlanLimit`).

    Returns:
        ``[{window, requests}]`` ordered second → month.

    Raises:
        ApiPlanValidationError: ``api-plan-invalid`` when a window appears twice or a count is not
            positive.
    """
    seen: Dict[str, int] = {}
    for limit in limits:
        if limit.requests < 1:
            raise ApiPlanValidationError(CODE_INVALID, f"a {limit.window} limit must allow at least one request")
        if limit.window in seen:
            raise ApiPlanValidationError(
                CODE_INVALID, f"the {limit.window} window is limited twice; give each window one limit"
            )
        seen[limit.window] = limit.requests
    return [{"window": window, "requests": seen[window]} for window in LIMIT_WINDOWS if window in seen]


def normalize_auth_config(strategy: str, config: Optional[PlanAuthConfig]) -> Dict[str, Any]:
    """Return the auth config as stored, refusing a setting the strategy does not use.

    Args:
        strategy: The plan's auth strategy.
        config: The settings sent, or ``None`` for none.

    Returns:
        Only the set keys: ``header_name`` for ``key_auth``; ``idp_config_id`` and ``scopes``
        (trimmed, de-duplicated, in order) for ``oauth2_client_credentials``; ``{}`` otherwise.

    Raises:
        ApiPlanValidationError: ``api-plan-invalid`` for a setting on the wrong strategy, a header
            name that is not an HTTP token, or a malformed scope.
    """
    config = config or PlanAuthConfig()
    header = (config.header_name or "").strip()
    idp = (config.idp_config_id or "").strip()
    scopes: List[str] = []
    for scope in config.scopes:
        trimmed = scope.strip()
        if not trimmed:
            continue
        if not _SCOPE.match(trimmed):
            raise ApiPlanValidationError(CODE_INVALID, f"'{trimmed}' is not a valid OAuth2 scope")
        if trimmed not in scopes:
            scopes.append(trimmed)

    if header and strategy != "key_auth":
        raise ApiPlanValidationError(CODE_INVALID, "a header name belongs to a key_auth plan")
    if (idp or scopes) and strategy != "oauth2_client_credentials":
        raise ApiPlanValidationError(
            CODE_INVALID, "an identity provider and scopes belong to an oauth2_client_credentials plan"
        )
    if header and not _HEADER_NAME.match(header):
        raise ApiPlanValidationError(CODE_INVALID, f"'{header}' is not a valid header name")

    out: Dict[str, Any] = {}
    if header:
        out["header_name"] = header
    if idp:
        out["idp_config_id"] = idp
    if scopes:
        out["scopes"] = scopes
    return out


def normalize_terms_url(url: Optional[str]) -> Optional[str]:
    """Return a trimmed terms URL, ``None`` for none, or refuse one that is not http(s).

    Args:
        url: The candidate URL.

    Returns:
        The trimmed URL, or ``None``.

    Raises:
        ApiPlanValidationError: ``api-plan-invalid`` when it is not an absolute http(s) URL.
    """
    trimmed = (url or "").strip()
    if not trimmed:
        return None
    if not re.match(r"^https?://[^\s/]+", trimmed, re.IGNORECASE) or any(ch.isspace() for ch in trimmed):
        raise ApiPlanValidationError(CODE_INVALID, "the terms URL must be an absolute http or https URL")
    return trimmed


# ---------------------------------------------------------------------------------------------
# Declared only
# ---------------------------------------------------------------------------------------------


def connector_can_provision(connector_kind: Optional[str]) -> bool:
    """Whether a connector of this kind can provision a plan onto its gateway.

    Args:
        connector_kind: The connector's kind, or ``None`` for a gateway config that is gone.

    Returns:
        True only for a kind in :data:`PROVISIONING_CONNECTOR_KINDS`.
    """
    return bool(connector_kind) and connector_kind in PROVISIONING_CONNECTOR_KINDS


def is_declared_only(environments: Sequence[PlanEnvironment]) -> bool:
    """Whether a plan is declared only: no environment, or one Apiome cannot provision.

    Args:
        environments: The plan's resolved environments.

    Returns:
        True when nothing would be provisioned for every environment.
    """
    return not environments or any(env.missing or not env.can_provision for env in environments)


def declared_only_notice(environments: Sequence[PlanEnvironment]) -> Optional[PlanNotice]:
    """The notice a declared-only plan carries, naming the environments that cannot provision.

    Args:
        environments: The plan's resolved environments.

    Returns:
        An ``api-plan-declared-only`` notice, or ``None`` when every environment can provision.
    """
    if not is_declared_only(environments):
        return None
    if not environments:
        message = (
            "Declared only: the plan names no gateway environment, so Apiome records its limits but "
            "provisions nothing."
        )
    else:
        names = [env.slug or env.id for env in environments if env.missing or not env.can_provision]
        message = (
            f"Declared only: {', '.join(names)} cannot be provisioned yet (its connector has no "
            "provisioning), so Apiome records the plan but changes nothing on the gateway."
        )
    return PlanNotice(code=NOTICE_DECLARED_ONLY, message=message)


# ---------------------------------------------------------------------------------------------
# Auth strategy vs member security schemes
# ---------------------------------------------------------------------------------------------


def scheme_satisfies(strategy: str, scheme: Mapping[str, Any]) -> bool:
    """Whether one declared security scheme can carry a plan's auth strategy.

    ``key_auth`` needs an ``apiKey`` scheme, ``oauth2_client_credentials`` an ``oauth2`` or
    ``openIdConnect`` one and ``mtls`` a ``mutualTLS`` one; ``none`` needs nothing.

    Args:
        strategy: The plan's auth strategy.
        scheme: A ``version_security_scheme`` row (``scheme_type`` …) or an OpenAPI scheme (``type``).

    Returns:
        True when the scheme fits the strategy.
    """
    if strategy == "none":
        return True
    kind = str(scheme.get("scheme_type") or scheme.get("type") or "").replace("_", "").lower()
    return kind in _SCHEME_TYPES.get(strategy, frozenset())


def auth_mismatch_warnings(
    strategy: str, members: Iterable[Mapping[str, Any]]
) -> List[PlanNotice]:
    """One ``api-plan-auth-mismatch`` warning per member whose schemes cannot carry the strategy.

    Args:
        strategy: The plan's auth strategy.
        members: ``{kind, ref, name, schemes}`` per member that has a version to check — ``schemes``
            being the security schemes its resolved version declares. MCP servers and members with
            no version are left out by the caller.

    Returns:
        The warnings, in member order; empty for ``none`` or when every member matches.
    """
    if strategy == "none":
        return []
    warnings: List[PlanNotice] = []
    for member in members:
        if any(scheme_satisfies(strategy, scheme) for scheme in member.get("schemes") or []):
            continue
        name = member.get("name") or member.get("ref")
        warnings.append(
            PlanNotice(
                code=WARNING_AUTH_MISMATCH,
                message=f"{name} declares no {_STRATEGY_WORDS[strategy]}, so this plan's auth does not match it.",
                member={"kind": member.get("kind"), "ref": member.get("ref"), "name": member.get("name")},
            )
        )
    return warnings


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------


def plan_extension_entry(product_slug: str, product_name: str, plan: ApiPlanRecord) -> Dict[str, Any]:
    """One plan as an ``x-apiome-plans`` entry.

    What a consumer of the document needs: the product, the plan's handle and name, its auth, limits,
    approval, environments and terms. ``billing_ref`` is internal and the IdP config id is an
    internal id, so neither is written; empty fields are left out.

    Args:
        product_slug: The product's slug.
        product_name: The product's name.
        plan: The plan.

    Returns:
        The entry.
    """
    auth: Dict[str, Any] = {"strategy": plan.auth_strategy}
    if plan.auth_config.header_name:
        auth["header_name"] = plan.auth_config.header_name
    if plan.auth_config.scopes:
        auth["scopes"] = list(plan.auth_config.scopes)
    entry: Dict[str, Any] = {
        "product": product_slug,
        "product_name": product_name,
        "plan": plan.slug,
        "name": plan.name,
        "state": plan.state,
        "auth": auth,
        "limits": [limit.model_dump() for limit in plan.limits],
        "approval": plan.approval,
        "declared_only": plan.declared_only,
    }
    optional = {
        "description": plan.description,
        "concurrency": plan.concurrency,
        "credential_ttl_days": plan.credential_ttl_days,
        "terms_url": plan.terms_url,
        "pricing_note": plan.pricing_note,
    }
    entry.update({key: value for key, value in optional.items() if value is not None})
    environments = [env.slug for env in plan.environments if env.slug and not env.missing]
    if environments:
        entry["environments"] = environments
    return entry


def plans_loss_item(
    extras: Mapping[str, Any], emitter_key: Optional[str], target_label: str
) -> Optional[Dict[str, Any]]:
    """The fidelity item for a revision's plans when exported to ``emitter_key``.

    Args:
        extras: The canonical model's root ``extras``.
        emitter_key: The target emitter's key (``openapi``, ``protobuf`` …).
        target_label: The target's label, for the message.

    Returns:
        ``None`` when the revision carries no plans. Otherwise the root item's fields
        (``kind``, ``severity``, ``message``, ``target_mapping``): ``ok`` for a target that writes
        ``x-apiome-plans``, an ``info`` ``drop`` for every other.
    """
    plans = extras.get(PLANS_EXTRAS_KEY) if isinstance(extras, Mapping) else None
    if not plans:
        return None
    count = len(plans)
    noun = "plan" if count == 1 else "plans"
    if emitter_key in PLANS_CARRYING_EMITTERS:
        return {
            "kind": "ok",
            "severity": "info",
            "message": f"{count} API product {noun} carried as the {PLANS_EXTENSION_KEY} extension.",
            "target_mapping": f"root {PLANS_EXTENSION_KEY}",
        }
    return {
        "kind": "drop",
        "severity": "info",
        "message": f"{count} API product {noun} ({PLANS_EXTENSION_KEY}) dropped: {target_label} has no equivalent.",
        "target_mapping": None,
    }
