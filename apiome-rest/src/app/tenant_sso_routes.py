"""Single sign-on for one workspace, run by its owners — EID-1.2 (#5012).

```
GET    /v1/tenants/{t}/sso/providers
POST   /v1/tenants/{t}/sso/providers
GET    /v1/tenants/{t}/sso/providers/{id}
PATCH  /v1/tenants/{t}/sso/providers/{id}
DELETE /v1/tenants/{t}/sso/providers/{id}
POST   /v1/tenants/{t}/sso/providers/{id}/domains
DELETE /v1/tenants/{t}/sso/providers/{id}/domains/{domain}
POST   /v1/tenants/{t}/sso/providers/{id}/domains/{domain}/verify
```

The same providers the installation admin manages at ``/v1/admin/sso/providers``
(:mod:`app.sso_provider_routes`, whose models and builders this module reuses), with three
differences that make it safe to hand to a customer:

* **Owners and tenant admins only, by session.** Every route — reads included, since a provider's
  configuration is nobody else's business — goes through :func:`require_tenant_admin_session`. An
  API key cannot register an identity provider. No new RBAC resource is added.
* **Scoped to the caller's workspace.** As on every ``/v1/tenants/{t}`` surface the tenant in the
  URL is informational; the authenticated tenant scopes every read and write. A provider of
  another workspace is a ``404``, and a provider created here always belongs to the caller's
  workspace.
* **A domain is proved, not asserted.** ``verify`` looks up the DNS TXT record
  ``_apiome-challenge.<domain>`` and marks the domain verified only when it holds the domain's
  token (:mod:`app.sso_domain_verification`). Until then the domain routes no sign-in. Public
  mailbox domains are refused (``sso-domain-public``); a domain another workspace has verified is
  refused (``sso-domain-claimed``); a lookup that fails reports ``could-not-check`` with what the
  resolver said, and changes nothing. Three checks an hour per domain.

Secrets stay write-only and sealed, exactly as on the admin surface. Every change is written to the
workspace's access audit as ``sso.provider.created`` / ``updated`` / ``deleted`` or
``sso.domain.verified``, source ``web``, with no secret in it.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import sso_provider_store as store
from .auth import get_authenticated_user_id, require_tenant_admin_session, validate_authentication
from .database import db
from .redacted_validation_route import RedactedValidationRoute
from .sso_domain_verification import (
    STATUS_VERIFIED,
    DnsCheck,
    challenge_record_name,
    check_domain_challenge,
    enforce_verify_budget,
    refuse_public_domain,
)
from .sso_metadata import CODE_DOMAIN_CLAIMED, SsoConfigError, normalize_domain
from .sso_provider_routes import (
    SsoDomainCreateRequest,
    SsoProviderView,
    _refuse,
    _view,
    audited_fields,
    build_create_values,
    build_updates,
    domain_conflict_status,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_DOMAIN_VERIFIED",
    "AUDIT_PROVIDER_CREATED",
    "AUDIT_PROVIDER_DELETED",
    "AUDIT_PROVIDER_UPDATED",
    "router",
]

router = APIRouter(prefix="/v1/tenants", tags=["sso"], route_class=RedactedValidationRoute)

#: Audit actions this module writes to ``apiome.access_audit``.
AUDIT_PROVIDER_CREATED = "sso.provider.created"
AUDIT_PROVIDER_UPDATED = "sso.provider.updated"
AUDIT_PROVIDER_DELETED = "sso.provider.deleted"
AUDIT_DOMAIN_VERIFIED = "sso.domain.verified"

CODE_DEFAULT_ROLE_INVALID = "sso-default-role-invalid"

#: The role nobody receives just by signing in.
OWNER_ROLE_SLUG = "owner"

_BASE = "/{tenant_slug}/sso/providers"

_ADMIN_ONLY = "Requires a signed-in owner or tenant administrator; API keys are refused."

_ERRORS = {
    403: {"description": "Not a signed-in owner or tenant administrator of this workspace."},
    422: {"description": "Refused with a stable `sso-*` code: `{error, message}`."},
}
_NOT_FOUND = {404: {"description": "No such provider in this workspace."}}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TenantSsoProviderView(SsoProviderView):
    """A provider as its workspace's owners see it. Never carries a secret."""

    member_count: int = Field(0, description="Members of this workspace who have signed in through this provider.")


class TenantSsoProviderListResponse(BaseModel):
    """Payload of ``GET /v1/tenants/{t}/sso/providers``."""

    providers: List[TenantSsoProviderView] = Field(default_factory=list)


class TenantSsoProviderCreateRequest(BaseModel):
    """Body of ``POST /v1/tenants/{t}/sso/providers``.

    OIDC needs ``issuer`` + ``client_id`` + ``client_secret``; SAML needs ``metadata_url`` or
    ``metadata_xml`` plus ``email_source`` (and ``email_attribute`` when that is ``attribute``).
    Secrets are write-only. The provider belongs to the caller's workspace.
    """

    model_config = {"extra": "forbid"}

    protocol: str = Field(..., description="`oidc` or `saml`.")
    slug: str = Field(..., description="2–28 lower-case letters, digits and hyphens. Unique installation-wide.")
    display_name: str = Field(..., min_length=1, max_length=120)
    preset: Optional[str] = Field(None, max_length=32)
    default_role_slug: Optional[str] = Field(
        None, max_length=64, description="A role of this workspace, other than `owner`."
    )
    issuer: Optional[str] = Field(None, description="OIDC issuer URL (https).")
    client_id: Optional[str] = None
    client_secret: Optional[str] = Field(None, description="Write-only; sealed at rest. Never returned.")
    metadata_url: Optional[str] = Field(None, description="SAML IdP metadata URL (https).")
    metadata_xml: Optional[str] = Field(None, description="SAML IdP metadata XML, pasted.")
    email_source: Optional[str] = Field(None, description="SAML: `nameid` or `attribute`.")
    email_attribute: Optional[str] = None
    sp_private_key: Optional[str] = Field(None, description="SAML SP signing key (PEM). Write-only; sealed at rest.")


class TenantSsoProviderUpdateRequest(BaseModel):
    """Body of ``PATCH /v1/tenants/{t}/sso/providers/{id}`` — a partial update, by field presence.

    An omitted field is left as stored. ``client_secret`` / ``sp_private_key`` are write-only: a
    value replaces the sealed secret, ``null`` clears it. Sending ``metadata_url`` or
    ``metadata_xml`` re-reads the SAML metadata; sending ``client_id`` re-runs OIDC discovery.
    """

    model_config = {"extra": "forbid"}

    display_name: Optional[str] = Field(None, min_length=1, max_length=120)
    enabled: Optional[bool] = None
    preset: Optional[str] = Field(None, max_length=32)
    default_role_slug: Optional[str] = Field(None, max_length=64)
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    metadata_url: Optional[str] = None
    metadata_xml: Optional[str] = None
    email_source: Optional[str] = None
    email_attribute: Optional[str] = None
    sp_private_key: Optional[str] = None


class SsoDomainCheckView(BaseModel):
    """What one DNS check found."""

    status: str = Field(..., description="`verified`, `not-found`, `mismatch` or `could-not-check`.")
    verified: bool = Field(..., description="Whether the domain is now verified.")
    record_name: str = Field(..., description="The TXT record that was looked up.")
    expected: str = Field(..., description="The value the record must hold.")
    observed: List[str] = Field(
        default_factory=list,
        description="What the resolver answered: the TXT values found, or why the lookup failed.",
    )
    message: str


class SsoDomainVerifyResponse(BaseModel):
    """Payload of the verify route: the provider as it now stands, and what the check found."""

    provider: TenantSsoProviderView
    check: SsoDomainCheckView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tenant_view(row: Dict[str, Any], tenant_id: str) -> TenantSsoProviderView:
    """Project a stored provider into the owner view, with how many members use it."""
    return TenantSsoProviderView(
        **_view(row).model_dump(),
        member_count=store.count_linked_members(db, tenant_id, row["slug"]),
    )


def _load(tenant_id: str, provider_id: str) -> Dict[str, Any]:
    """A provider of this workspace, or ``404`` — including for another workspace's provider."""
    try:
        UUID(provider_id)
    except ValueError:
        row = None  # a malformed id is "no such provider", not a database error
    else:
        row = store.get_provider(db, provider_id, tenant_id=tenant_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail={"error": "sso-provider-not-found", "message": "No such SSO provider."}
        )
    return row


def _check_default_role(tenant_id: str, slug: Optional[str]) -> None:
    """Refuse a default role the workspace does not have, and ``owner``.

    Raises:
        SsoConfigError: ``sso-default-role-invalid``.
    """
    if slug is None or slug == "":
        return
    if slug == OWNER_ROLE_SLUG:
        raise SsoConfigError(CODE_DEFAULT_ROLE_INVALID, "Owner cannot be a default role. Choose another.")
    if slug not in {role["slug"] for role in db.list_roles(tenant_id)}:
        raise SsoConfigError(CODE_DEFAULT_ROLE_INVALID, f"This workspace has no role “{slug}”.")


def _audit(auth_data: Dict[str, Any], tenant_id: str, action: str, slug: str, **detail: Any) -> None:
    """Append one secret-free access-audit row (best-effort).

    A change that succeeded is not reported as failed because its audit row could not be written.
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=get_authenticated_user_id(auth_data),
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=f"sso:{slug}",
            source="web",
            detail={key: value for key, value in detail.items() if value is not None},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not write %s audit row: %s", action, type(exc).__name__)


def _actor(auth_data: Dict[str, Any]) -> str:
    """The acting user's id, for ``created_by`` / ``updated_by`` / ``verified_by``."""
    return str(get_authenticated_user_id(auth_data))


def _check_view(check: DnsCheck) -> SsoDomainCheckView:
    """Project a :class:`DnsCheck` onto the response model."""
    return SsoDomainCheckView(
        status=check.status,
        verified=check.verified,
        record_name=check.record_name,
        expected=check.expected,
        observed=list(check.observed),
        message=check.message,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    _BASE,
    response_model=TenantSsoProviderListResponse,
    responses=_ERRORS,
    summary="List the workspace's SSO providers",
    description="Every identity provider of this workspace with its domains, newest first. "
    f"Secrets are never included.\n\n{_ADMIN_ONLY}",
)
async def list_tenant_sso_providers(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> TenantSsoProviderListResponse:
    """List this workspace's providers."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    rows = store.list_providers(db, tenant_id=tenant_id)
    return TenantSsoProviderListResponse(providers=[_tenant_view(row, tenant_id) for row in rows])


@router.post(
    _BASE,
    response_model=TenantSsoProviderView,
    status_code=201,
    responses={**_ERRORS, 503: {"description": "Secret encryption not configured."}},
    summary="Register an SSO provider",
    description=(
        "Register this workspace's identity provider: OIDC by issuer (the discovery document is "
        "fetched and checked) or SAML 2.0 by metadata URL or XML. It starts disabled, and routes no "
        "sign-in until it is enabled **and** has a verified domain.\n\n"
        f"Audited as `sso.provider.created`. {_ADMIN_ONLY}"
    ),
)
async def create_tenant_sso_provider(
    tenant_slug: str,
    payload: TenantSsoProviderCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantSsoProviderView:
    """Register a provider for the caller's workspace."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    try:
        _check_default_role(tenant_id, payload.default_role_slug)
        values = await build_create_values(payload, tenant_id=tenant_id)
        row = store.create_provider(db, values, actor=_actor(auth_data))
    except SsoConfigError as exc:
        raise _refuse(exc) from exc
    _audit(auth_data, tenant_id, AUDIT_PROVIDER_CREATED, row["slug"], protocol=row["protocol"])
    return _tenant_view(row, tenant_id)


@router.get(
    _BASE + "/{provider_id}",
    response_model=TenantSsoProviderView,
    responses={**_ERRORS, **_NOT_FOUND},
    summary="Read one SSO provider",
    description=f"One provider with its domains and how many members sign in through it.\n\n{_ADMIN_ONLY}",
)
async def get_tenant_sso_provider(
    tenant_slug: str, provider_id: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> TenantSsoProviderView:
    """Read one provider of the caller's workspace."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    return _tenant_view(_load(tenant_id, provider_id), tenant_id)


@router.patch(
    _BASE + "/{provider_id}",
    response_model=TenantSsoProviderView,
    responses={**_ERRORS, **_NOT_FOUND, 503: {"description": "Secret encryption not configured."}},
    summary="Change an SSO provider",
    description=(
        "Partially update a provider; omitted fields are left alone. `enabled: false` stops sign-ins "
        "reaching the identity provider at once. Enabling an OIDC provider needs its client secret "
        "(`sso-enable-incomplete`).\n\n"
        f"Audited as `sso.provider.updated` with the names of the changed fields. {_ADMIN_ONLY}"
    ),
)
async def update_tenant_sso_provider(
    tenant_slug: str,
    provider_id: str,
    payload: TenantSsoProviderUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantSsoProviderView:
    """Change a provider of the caller's workspace."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    existing = _load(tenant_id, provider_id)
    try:
        if "default_role_slug" in payload.model_fields_set:
            _check_default_role(tenant_id, payload.default_role_slug)
        updates = await build_updates(existing, payload)
    except SsoConfigError as exc:
        raise _refuse(exc) from exc
    if not updates:
        return _tenant_view(existing, tenant_id)
    row = store.update_provider(db, provider_id, updates, actor=_actor(auth_data))
    if row is None:
        raise HTTPException(
            status_code=404, detail={"error": "sso-provider-not-found", "message": "No such SSO provider."}
        )
    _audit(
        auth_data,
        tenant_id,
        AUDIT_PROVIDER_UPDATED,
        existing["slug"],
        fields=audited_fields(updates),
        enabled=updates.get("enabled"),
    )
    return _tenant_view(row, tenant_id)


@router.delete(
    _BASE + "/{provider_id}",
    response_model=TenantSsoProviderView,
    responses={**_ERRORS, **_NOT_FOUND},
    summary="Remove an SSO provider",
    description=(
        "Remove a provider, its domains and its sealed secrets. Members who signed in through it "
        "keep their accounts but can no longer sign in this way; `member_count` in the response "
        "says how many.\n\n"
        f"Audited as `sso.provider.deleted`. {_ADMIN_ONLY}"
    ),
)
async def delete_tenant_sso_provider(
    tenant_slug: str, provider_id: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> TenantSsoProviderView:
    """Remove a provider of the caller's workspace."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    view = _tenant_view(_load(tenant_id, provider_id), tenant_id)
    store.delete_provider(db, provider_id)
    _audit(
        auth_data,
        tenant_id,
        AUDIT_PROVIDER_DELETED,
        view.slug,
        member_count=view.member_count,
        domains=[domain.domain for domain in view.domains],
    )
    return view


@router.post(
    _BASE + "/{provider_id}/domains",
    response_model=TenantSsoProviderView,
    status_code=201,
    responses={
        **_ERRORS,
        **_NOT_FOUND,
        409: {"description": "`sso-domain-claimed` or `sso-domain-exists`."},
    },
    summary="Add an email domain",
    description=(
        "Attach an email domain, unverified, and issue the DNS challenge for it: publish "
        "`verification_token` as a TXT record at `record_name`, then call verify. An unverified "
        "domain routes no sign-in.\n\n"
        "Refused: a public mailbox domain (`sso-domain-public`), a domain another workspace has "
        "verified (`sso-domain-claimed`), a domain already on this provider (`sso-domain-exists`).\n\n"
        f"Audited as `sso.provider.updated`. {_ADMIN_ONLY}"
    ),
)
async def add_tenant_sso_domain(
    tenant_slug: str,
    provider_id: str,
    payload: SsoDomainCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantSsoProviderView:
    """Attach a domain to a provider of the caller's workspace."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    existing = _load(tenant_id, provider_id)
    try:
        domain = normalize_domain(payload.domain)
        refuse_public_domain(domain)
        store.add_domain(db, provider_id, domain, token=secrets.token_urlsafe(24))
    except SsoConfigError as exc:
        raise _refuse(exc, domain_conflict_status(exc)) from exc
    _audit(auth_data, tenant_id, AUDIT_PROVIDER_UPDATED, existing["slug"], domain_added=domain)
    return _tenant_view(_load(tenant_id, provider_id), tenant_id)


@router.delete(
    _BASE + "/{provider_id}/domains/{domain}",
    response_model=TenantSsoProviderView,
    responses={**_ERRORS, 404: {"description": "No such provider or domain in this workspace."}},
    summary="Remove an email domain",
    description=(
        "Detach a domain. Sign-ins from it stop reaching this identity provider at once, and "
        "another workspace may then verify it.\n\n"
        f"Audited as `sso.provider.updated`. {_ADMIN_ONLY}"
    ),
)
async def remove_tenant_sso_domain(
    tenant_slug: str,
    provider_id: str,
    domain: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> TenantSsoProviderView:
    """Detach a domain from a provider of the caller's workspace."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    existing = _load(tenant_id, provider_id)
    try:
        normalized = normalize_domain(domain)
    except SsoConfigError as exc:
        raise _refuse(exc) from exc
    if not store.remove_domain(db, provider_id, normalized):
        raise HTTPException(
            status_code=404,
            detail={"error": "sso-domain-not-found", "message": f"{normalized} is not a domain of this provider."},
        )
    _audit(auth_data, tenant_id, AUDIT_PROVIDER_UPDATED, existing["slug"], domain_removed=normalized)
    return _tenant_view(_load(tenant_id, provider_id), tenant_id)


@router.post(
    _BASE + "/{provider_id}/domains/{domain}/verify",
    response_model=SsoDomainVerifyResponse,
    responses={
        **_ERRORS,
        404: {"description": "No such provider or domain in this workspace."},
        409: {"description": "`sso-domain-claimed`: another workspace has verified this domain."},
        429: {"description": "`sso-verify-rate-limited`: three checks an hour per domain."},
    },
    summary="Verify an email domain by DNS",
    description=(
        "Look up the TXT record `_apiome-challenge.<domain>` and mark the domain verified when it "
        "holds the domain's `verification_token`. Always answers `200` with `check.status`:\n\n"
        "- `verified` — the domain now routes sign-ins (once the provider is enabled);\n"
        "- `not-found` — no TXT record at that name yet;\n"
        "- `mismatch` — a TXT record is there with another value (`check.observed` lists what was "
        "found);\n"
        "- `could-not-check` — the lookup itself failed (`check.observed` says why). Nothing is "
        "changed, and the domain is **not** verified.\n\n"
        "An already verified domain answers `verified` without a lookup. Limited to three checks "
        "an hour per domain.\n\n"
        f"A successful verification is audited as `sso.domain.verified`. {_ADMIN_ONLY}"
    ),
)
async def verify_tenant_sso_domain(
    tenant_slug: str,
    provider_id: str,
    domain: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SsoDomainVerifyResponse:
    """Prove a domain by its DNS TXT challenge."""
    _ = tenant_slug
    tenant_id = require_tenant_admin_session(db, auth_data)
    existing = _load(tenant_id, provider_id)
    try:
        normalized = normalize_domain(domain)
    except SsoConfigError as exc:
        raise _refuse(exc) from exc
    row = next((d for d in existing.get("domains") or [] if d["domain"] == normalized), None)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "sso-domain-not-found", "message": f"{normalized} is not a domain of this provider."},
        )
    token = row["verification_token"]

    if row.get("verified_at") is not None:
        check = DnsCheck(
            status=STATUS_VERIFIED,
            record_name=challenge_record_name(normalized),
            expected=token,
            message=f"{normalized} is verified.",
        )
        return SsoDomainVerifyResponse(provider=_tenant_view(existing, tenant_id), check=_check_view(check))

    claimed = SsoConfigError(CODE_DOMAIN_CLAIMED, f"{normalized} is already verified for another workspace.")
    if store.domain_verified_elsewhere(db, provider_id, normalized):
        raise _refuse(claimed, 409)

    enforce_verify_budget(f"{provider_id}:{normalized}")
    check = await check_domain_challenge(normalized, token)
    if check.verified:
        try:
            store.verify_domain(db, provider_id, normalized, actor=_actor(auth_data))
        except SsoConfigError as exc:
            # Lost a race: another workspace proved the same domain a moment earlier.
            raise _refuse(claimed, 409) from exc
        _audit(
            auth_data,
            tenant_id,
            AUDIT_DOMAIN_VERIFIED,
            existing["slug"],
            domain=normalized,
            method="dns_txt",
            record_name=check.record_name,
        )
    return SsoDomainVerifyResponse(
        provider=_tenant_view(_load(tenant_id, provider_id), tenant_id), check=_check_view(check)
    )
