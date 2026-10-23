"""Enterprise SSO providers — admin CRUD and the login-time read path (EID-1.1, #5011).

Two routers over apiome-db V312 (``sso_provider``, ``sso_provider_domain``):

* **Admin** — ``/v1/admin/sso/providers`` — gated by :func:`require_super_admin` exactly like
  the installation OAuth providers (``/v1/admin/auth-providers``). An installation admin
  registers a workspace's IdP (OIDC by issuer discovery, SAML 2.0 by metadata URL or XML), attaches
  email domains, marks them verified (DNS verification and the owner-facing page arrive in
  EID-1.2), and enables it.
* **Internal** — ``/v1/internal/sso/providers/resolved`` — gated by the shared
  ``INTERNAL_SERVICE_TOKEN`` (:func:`require_internal_service`), like
  ``/v1/internal/auth-providers/resolved``. apiome-ui reads it at sign-in time to hand the
  **enabled** providers' **verified** domains to Better Auth's SSO plugin; it is the only surface
  that ever returns a decrypted secret, and it is never proxied to a browser.

Security invariants:

* **Secrets are write-only.** The OIDC client secret and the optional SAML SP private key are
  sealed with the OLO-8.3 envelope (:func:`seal_provider_secret`) and stored as ciphertext; admin
  responses report only ``has_client_secret`` / ``has_sp_private_key``. The store never even
  selects the ciphertext for an admin read.
* **Only verified, enabled providers route.** The internal endpoint returns nothing else, and
  apiome-ui's plugin falls back to an always-empty table, so a disabled or unverified provider
  cannot be reached by any path.
* **One domain, one IdP.** A domain is unique across the installation (``sso-domain-claimed``).
* **Every change is audited** in ``auth_events`` (event type ``sso_provider``), secret-free.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import sso_provider_store as store
from .auth_events import EVENT_SSO_PROVIDER, OUTCOME_SUCCESS
from .auth_provider_config_routes import require_super_admin
from .auth_provider_registry import PROVIDER_REGISTRY
from .auth_provider_resolved_routes import require_internal_service
from .auth_provider_secret_crypto import (
    AuthConfigEncryptionError,
    ProviderSecretDecryptionError,
    provider_secret_encryption_configured,
    seal_provider_secret,
    unseal_provider_secret,
)
from .database import db
from .sso_metadata import (
    CODE_ENABLE_INCOMPLETE,
    PROTOCOL_OIDC,
    PROTOCOL_SAML,
    PROTOCOLS,
    SamlIdpMetadata,
    SsoConfigError,
    discover_oidc,
    fetch_saml_metadata,
    normalize_domain,
    normalize_slug,
    parse_saml_metadata,
    provider_identity_kind,
    saml_config_from_metadata,
)

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/v1/admin/sso/providers", tags=["sso"])
internal_router = APIRouter(prefix="/v1/internal/sso", tags=["internal-sso"])

#: The admin console's session names no user, so its changes are attributed to this actor.
ADMIN_ACTOR = "admin"

#: Better Auth's SSO plugin addresses a provider as ``sso-<slug>``: the prefix keeps it out of the
#: OAuth provider namespace in Better Auth's ``account.providerId``.
PLUGIN_PROVIDER_PREFIX = "sso-"

_ERRORS = {
    401: {"description": "No super-admin session presented."},
    403: {"description": "Super-admin session invalid or expired."},
    422: {"description": "Refused with a stable `sso-*` code: `{error, message}`."},
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SsoDomainView(BaseModel):
    """One email domain of a provider."""

    domain: str
    verified: bool = Field(..., description="Whether sign-ins from this domain may route to the IdP.")
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    verification_token: str = Field(..., description="The value EID-1.2's DNS TXT check looks for. Not a secret.")
    created_at: Optional[datetime] = None


class SsoProviderView(BaseModel):
    """A provider as admins see it. Never carries a secret."""

    id: str
    slug: str
    plugin_provider_id: str = Field(..., description="`sso-<slug>`: the id in sign-in URLs.")
    identity_kind: str = Field(..., description="`sso:<slug>`: the provider recorded on identities and auth events.")
    protocol: str = Field(..., description="`oidc` or `saml`.")
    display_name: str
    issuer: str = Field(..., description="OIDC issuer, or the SAML IdP entity id.")
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    oidc_config: Optional[Dict[str, Any]] = Field(None, description="Client id and discovered endpoints; no secret.")
    saml_config: Optional[Dict[str, Any]] = Field(
        None, description="IdP entity id, SSO URL, binding, certificates and email source."
    )
    has_client_secret: bool
    has_sp_private_key: bool
    enabled: bool
    routable: bool = Field(..., description="Enabled and at least one verified domain: sign-ins reach the IdP.")
    preset: Optional[str] = None
    default_role_slug: Optional[str] = None
    domains: List[SsoDomainView] = Field(default_factory=list)
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SsoProviderListResponse(BaseModel):
    """Payload of ``GET /v1/admin/sso/providers``."""

    providers: List[SsoProviderView] = Field(default_factory=list)


class SsoProviderCreateRequest(BaseModel):
    """Body of ``POST /v1/admin/sso/providers``.

    OIDC needs ``issuer`` + ``client_id`` + ``client_secret``; SAML needs ``metadata_url`` or
    ``metadata_xml`` plus ``email_source`` (and ``email_attribute`` when that is ``attribute``).
    Secrets are write-only.
    """

    model_config = {"extra": "forbid"}

    protocol: str = Field(..., description="`oidc` or `saml`.")
    slug: str = Field(..., description="2–28 lower-case letters, digits and hyphens.")
    display_name: str = Field(..., min_length=1, max_length=120)
    tenant_id: Optional[str] = Field(None, description="The workspace this IdP signs in to.")
    preset: Optional[str] = Field(None, max_length=32)
    default_role_slug: Optional[str] = Field(None, max_length=64)
    issuer: Optional[str] = Field(None, description="OIDC issuer URL (https).")
    client_id: Optional[str] = None
    client_secret: Optional[str] = Field(None, description="Write-only; sealed at rest. Never returned.")
    metadata_url: Optional[str] = Field(None, description="SAML IdP metadata URL (https).")
    metadata_xml: Optional[str] = Field(None, description="SAML IdP metadata XML, pasted.")
    email_source: Optional[str] = Field(None, description="SAML: `nameid` or `attribute`.")
    email_attribute: Optional[str] = None
    sp_private_key: Optional[str] = Field(None, description="SAML SP signing key (PEM). Write-only; sealed at rest.")


class SsoProviderUpdateRequest(BaseModel):
    """Body of ``PATCH /v1/admin/sso/providers/{id}`` — a partial update, by field presence.

    An omitted field is left as stored. ``client_secret`` / ``sp_private_key`` are write-only: a
    value replaces the sealed secret, ``null`` clears it. Sending ``metadata_url`` or
    ``metadata_xml`` re-reads the SAML metadata; sending ``client_id`` re-runs OIDC discovery.
    """

    model_config = {"extra": "forbid"}

    display_name: Optional[str] = Field(None, min_length=1, max_length=120)
    tenant_id: Optional[str] = None
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


class SsoDomainCreateRequest(BaseModel):
    """Body of ``POST /v1/admin/sso/providers/{id}/domains``."""

    model_config = {"extra": "forbid"}

    domain: str = Field(..., description="An email domain such as acme.com (an address is accepted).")


class ResolvedSsoProvider(BaseModel):
    """One routable provider for apiome-ui's sign-in resolver. Carries decrypted secrets."""

    id: str
    slug: str
    plugin_provider_id: str
    identity_kind: str
    protocol: str
    display_name: str
    issuer: str
    tenant_id: Optional[str] = None
    domains: List[str] = Field(default_factory=list, description="Verified domains only.")
    oidc_config: Optional[Dict[str, Any]] = None
    saml_config: Optional[Dict[str, Any]] = None
    client_secret: Optional[str] = Field(None, description="Decrypted. Server-to-server only.")
    sp_private_key: Optional[str] = Field(None, description="Decrypted. Server-to-server only.")


class ResolvedSsoProviderResponse(BaseModel):
    """Payload of ``GET /v1/internal/sso/providers/resolved``."""

    providers: List[ResolvedSsoProvider] = Field(default_factory=list)
    fingerprint: str = Field(..., description="Changes whenever any routable provider changes; secret-free hash.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _refuse(exc: SsoConfigError, status: int = 422) -> HTTPException:
    """Turn an :class:`SsoConfigError` into an HTTP error with its stable body."""
    return HTTPException(status_code=status, detail=exc.body())


def _seal(secret: str, *, what: str) -> tuple:
    """Seal a secret with the OLO-8.3 envelope, or refuse with ``503`` when unconfigured."""
    if not provider_secret_encryption_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "encryption_not_configured",
                "message": f"Cannot store the {what}: set AUTH_CONFIG_ENC_KEY (OLO-8.3) and retry.",
            },
        )
    try:
        return seal_provider_secret(secret)
    except AuthConfigEncryptionError as exc:
        logger.warning("failed to seal SSO %s: %s", what, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "encryption_not_configured",
                "message": f"Cannot store the {what}: check AUTH_CONFIG_ENC_KEY.",
            },
        ) from exc


def _secret_updates(raw: Optional[str], *, column: str, what: str) -> Dict[str, Any]:
    """Column updates for a write-only secret: seal a value, clear on blank/``None``."""
    value = (raw or "").strip()
    if not value:
        return {f"{column}_encrypted": None, f"{column}_key_id": None}
    blob, key_id = _seal(value, what=what)
    return {f"{column}_encrypted": blob, f"{column}_key_id": key_id}


def _reserved_slugs() -> List[str]:
    """The installation OAuth provider ids, which an SSO slug may not reuse."""
    return [descriptor.id for descriptor in PROVIDER_REGISTRY]


def _view(row: Dict[str, Any]) -> SsoProviderView:
    """Project a stored provider (no ciphertext) into the admin view."""
    domains = [
        SsoDomainView(
            domain=d["domain"],
            verified=d.get("verified_at") is not None,
            verified_at=d.get("verified_at"),
            verified_by=d.get("verified_by"),
            verification_token=d["verification_token"],
            created_at=d.get("created_at"),
        )
        for d in row.get("domains") or []
    ]
    return SsoProviderView(
        id=row["id"],
        slug=row["slug"],
        plugin_provider_id=f"{PLUGIN_PROVIDER_PREFIX}{row['slug']}",
        identity_kind=provider_identity_kind(row["slug"]),
        protocol=row["protocol"],
        display_name=row["display_name"],
        issuer=row["issuer"],
        tenant_id=row.get("tenant_id"),
        tenant_name=row.get("tenant_name"),
        oidc_config=row.get("oidc_config"),
        saml_config=row.get("saml_config"),
        has_client_secret=bool(row.get("has_client_secret")),
        has_sp_private_key=bool(row.get("has_sp_private_key")),
        enabled=bool(row.get("enabled")),
        routable=bool(row.get("enabled")) and any(d.verified for d in domains),
        preset=row.get("preset"),
        default_role_slug=row.get("default_role_slug"),
        domains=domains,
        created_by=row.get("created_by"),
        updated_by=row.get("updated_by"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _audit(slug: str, action: str, **detail: Any) -> None:
    """Append a secret-free ``sso_provider`` row to ``auth_events`` (best-effort)."""
    db.write_auth_event(
        event_type=EVENT_SSO_PROVIDER,
        outcome=OUTCOME_SUCCESS,
        provider=provider_identity_kind(slug),
        detail={"action": action, "actor_kind": ADMIN_ACTOR, **{k: v for k, v in detail.items() if v is not None}},
    )


async def _saml_config(
    *,
    metadata_url: Optional[str],
    metadata_xml: Optional[str],
    email_source: Optional[str],
    email_attribute: Optional[str],
) -> Dict[str, Any]:
    """Read SAML metadata from a URL or pasted XML and build ``saml_config``."""
    if metadata_xml and metadata_xml.strip():
        metadata = parse_saml_metadata(metadata_xml)
        source_url = None
    elif metadata_url and metadata_url.strip():
        metadata = await fetch_saml_metadata(metadata_url.strip())
        source_url = metadata_url.strip()
    else:
        raise SsoConfigError("sso-metadata-invalid", "Give the IdP's metadata URL or paste its metadata XML.")
    return saml_config_from_metadata(
        metadata, metadata_url=source_url, email_source=email_source or "", email_attribute=email_attribute
    )


def _load(provider_id: str) -> Dict[str, Any]:
    """A stored provider, or ``404``."""
    row = store.get_provider(db, provider_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail={"error": "sso-provider-not-found", "message": "No such SSO provider."}
        )
    return row


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


@admin_router.get("", response_model=SsoProviderListResponse, responses=_ERRORS)
async def list_sso_providers(_: None = Depends(require_super_admin)) -> SsoProviderListResponse:
    """List every SSO provider with its domains, newest first. Secrets are never included."""
    return SsoProviderListResponse(providers=[_view(row) for row in store.list_providers(db)])


@admin_router.post(
    "",
    response_model=SsoProviderView,
    status_code=201,
    responses={**_ERRORS, 503: {"description": "Secret encryption not configured."}},
)
async def create_sso_provider(
    payload: SsoProviderCreateRequest, _: None = Depends(require_super_admin)
) -> SsoProviderView:
    """Register an SSO provider, disabled until it has a verified domain and is enabled.

    OIDC: the issuer's discovery document is fetched and checked (issuer match, HTTPS authorize /
    token / JWKS endpoints) and the endpoints are stored. SAML: the IdP metadata is parsed safely;
    an IdP offering only an unsupported binding is refused with ``sso-binding-unsupported``.

    Raises:
        HTTPException: ``422`` with a stable ``sso-*`` code; ``503`` when a secret is given but
            encryption is unconfigured.
    """
    try:
        slug = normalize_slug(payload.slug, reserved=_reserved_slugs())
        protocol = (payload.protocol or "").strip().lower()
        if protocol not in PROTOCOLS:
            raise SsoConfigError("sso-protocol-invalid", "Choose OIDC or SAML 2.0.")
        values: Dict[str, Any] = {
            "slug": slug,
            "protocol": protocol,
            "display_name": payload.display_name.strip(),
            "tenant_id": payload.tenant_id or None,
            "preset": payload.preset,
            "default_role_slug": payload.default_role_slug,
        }
        if protocol == PROTOCOL_OIDC:
            if not (payload.client_secret or "").strip():
                raise SsoConfigError(CODE_ENABLE_INCOMPLETE, "An OIDC provider needs the client secret the IdP issued.")
            discovered = await discover_oidc(payload.issuer or "", client_id=payload.client_id or "")
            values["issuer"] = discovered["issuer"]
            values["oidc_config"] = discovered["oidc_config"]
            values.update(_secret_updates(payload.client_secret, column="client_secret", what="client secret"))
        else:
            saml_config = await _saml_config(
                metadata_url=payload.metadata_url,
                metadata_xml=payload.metadata_xml,
                email_source=payload.email_source,
                email_attribute=payload.email_attribute,
            )
            values["issuer"] = saml_config["idp_entity_id"]
            values["saml_config"] = saml_config
            if (payload.sp_private_key or "").strip():
                values.update(_secret_updates(payload.sp_private_key, column="sp_private_key", what="SP private key"))
        row = store.create_provider(db, values, actor=ADMIN_ACTOR)
    except SsoConfigError as exc:
        raise _refuse(exc) from exc
    _audit(slug, "created", protocol=protocol, tenant_id=values.get("tenant_id"))
    return _view(row)


@admin_router.get(
    "/{provider_id}", response_model=SsoProviderView, responses={**_ERRORS, 404: {"description": "No such provider."}}
)
async def get_sso_provider(provider_id: str, _: None = Depends(require_super_admin)) -> SsoProviderView:
    """One SSO provider with its domains. Secrets are never included."""
    return _view(_load(provider_id))


@admin_router.patch(
    "/{provider_id}",
    response_model=SsoProviderView,
    responses={
        **_ERRORS,
        404: {"description": "No such provider."},
        503: {"description": "Secret encryption not configured."},
    },
)
async def update_sso_provider(
    provider_id: str, payload: SsoProviderUpdateRequest, _: None = Depends(require_super_admin)
) -> SsoProviderView:
    """Partially update an SSO provider.

    Enabling requires a complete provider: an OIDC provider must hold a client secret
    (``sso-enable-incomplete`` otherwise). A provider with no verified domain may be enabled but is
    not ``routable`` until a domain is verified.
    """
    existing = _load(provider_id)
    provided = payload.model_fields_set
    updates: Dict[str, Any] = {}
    try:
        for column in ("display_name", "preset", "default_role_slug"):
            if column in provided:
                value = getattr(payload, column)
                updates[column] = value.strip() if isinstance(value, str) else value
        if "tenant_id" in provided:
            updates["tenant_id"] = payload.tenant_id or None
        if "enabled" in provided:
            updates["enabled"] = bool(payload.enabled)

        if existing["protocol"] == PROTOCOL_OIDC:
            if "client_id" in provided:
                discovered = await discover_oidc(existing["issuer"], client_id=payload.client_id or "")
                updates["oidc_config"] = discovered["oidc_config"]
            if "client_secret" in provided:
                updates.update(_secret_updates(payload.client_secret, column="client_secret", what="client secret"))
        else:
            current = existing.get("saml_config") or {}
            rereads = {"metadata_url", "metadata_xml"} & provided
            if rereads or {"email_source", "email_attribute"} & provided:
                if rereads:
                    saml_config = await _saml_config(
                        metadata_url=payload.metadata_url,
                        metadata_xml=payload.metadata_xml,
                        email_source=payload.email_source
                        if "email_source" in provided
                        else current.get("email_source"),
                        email_attribute=payload.email_attribute
                        if "email_attribute" in provided
                        else current.get("email_attribute"),
                    )
                else:
                    saml_config = saml_config_from_metadata(
                        SamlIdpMetadata(
                            entity_id=current.get("idp_entity_id", existing["issuer"]),
                            sso_url=current.get("sso_url", ""),
                            sso_binding=current.get("sso_binding", ""),
                            certificates=list(current.get("certificates") or []),
                            name_id_formats=list(current.get("name_id_formats") or []),
                        ),
                        metadata_url=current.get("metadata_url"),
                        email_source=payload.email_source
                        if "email_source" in provided
                        else current.get("email_source", ""),
                        email_attribute=payload.email_attribute
                        if "email_attribute" in provided
                        else current.get("email_attribute"),
                    )
                updates["saml_config"] = saml_config
                updates["issuer"] = saml_config["idp_entity_id"]
            if "sp_private_key" in provided:
                updates.update(_secret_updates(payload.sp_private_key, column="sp_private_key", what="SP private key"))

        will_enable = updates.get("enabled", existing.get("enabled"))
        has_secret = (
            updates["client_secret_key_id"] is not None
            if "client_secret_key_id" in updates
            else bool(existing.get("has_client_secret"))
        )
        if will_enable and existing["protocol"] == PROTOCOL_OIDC and not has_secret:
            raise SsoConfigError(CODE_ENABLE_INCOMPLETE, "Add the client secret before enabling this OIDC provider.")
    except SsoConfigError as exc:
        raise _refuse(exc) from exc

    row = store.update_provider(db, provider_id, updates, actor=ADMIN_ACTOR) if updates else existing
    _audit(
        existing["slug"],
        "updated",
        # Secret columns are named by the secret, never by the ciphertext / key-id column pair.
        fields=sorted(
            {
                "client_secret"
                if k.startswith("client_secret")
                else "sp_private_key"
                if k.startswith("sp_private_key")
                else k
                for k in updates
            }
        ),
    )
    return _view(row)  # type: ignore[arg-type]


@admin_router.delete(
    "/{provider_id}", response_model=SsoProviderView, responses={**_ERRORS, 404: {"description": "No such provider."}}
)
async def delete_sso_provider(provider_id: str, _: None = Depends(require_super_admin)) -> SsoProviderView:
    """Remove an SSO provider and its domains. Its sealed secrets are destroyed with it.

    Identities already linked through it (``external_auth_providers`` rows ``sso:<slug>``) are kept,
    so those users can still sign in another way; the provider simply stops routing.
    """
    row = store.delete_provider(db, provider_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail={"error": "sso-provider-not-found", "message": "No such SSO provider."}
        )
    _audit(row["slug"], "deleted")
    return _view(row)


@admin_router.post(
    "/{provider_id}/domains",
    response_model=SsoProviderView,
    status_code=201,
    responses={**_ERRORS, 404: {"description": "No such provider."}, 409: {"description": "`sso-domain-claimed`."}},
)
async def add_sso_domain(
    provider_id: str, payload: SsoDomainCreateRequest, _: None = Depends(require_super_admin)
) -> SsoProviderView:
    """Attach an email domain, unverified. A domain belongs to one provider installation-wide."""
    existing = _load(provider_id)
    try:
        domain = normalize_domain(payload.domain)
        store.add_domain(db, provider_id, domain, token=secrets.token_urlsafe(24))
    except SsoConfigError as exc:
        raise _refuse(exc, 409 if exc.code == "sso-domain-claimed" else 422) from exc
    _audit(existing["slug"], "domain_added", domain=domain)
    return _view(_load(provider_id))


@admin_router.post(
    "/{provider_id}/domains/{domain}/verify",
    response_model=SsoProviderView,
    responses={**_ERRORS, 404: {"description": "No such provider or domain."}},
)
async def verify_sso_domain(provider_id: str, domain: str, _: None = Depends(require_super_admin)) -> SsoProviderView:
    """Mark a domain verified on the admin's word (DNS verification arrives in EID-1.2)."""
    existing = _load(provider_id)
    try:
        normalized = normalize_domain(domain)
    except SsoConfigError as exc:
        raise _refuse(exc) from exc
    if store.verify_domain(db, provider_id, normalized, actor=ADMIN_ACTOR) is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "sso-domain-not-found", "message": f"{normalized} is not a domain of this provider."},
        )
    _audit(existing["slug"], "domain_verified", domain=normalized, method="admin_attested")
    return _view(_load(provider_id))


@admin_router.delete(
    "/{provider_id}/domains/{domain}",
    response_model=SsoProviderView,
    responses={**_ERRORS, 404: {"description": "No such provider or domain."}},
)
async def remove_sso_domain(provider_id: str, domain: str, _: None = Depends(require_super_admin)) -> SsoProviderView:
    """Detach a domain. Sign-ins from it stop routing to this IdP at once."""
    existing = _load(provider_id)
    try:
        normalized = normalize_domain(domain)
    except SsoConfigError as exc:
        raise _refuse(exc) from exc
    if not store.remove_domain(db, provider_id, normalized):
        raise HTTPException(
            status_code=404,
            detail={"error": "sso-domain-not-found", "message": f"{normalized} is not a domain of this provider."},
        )
    _audit(existing["slug"], "domain_removed", domain=normalized)
    return _view(_load(provider_id))


# ---------------------------------------------------------------------------
# Internal read path
# ---------------------------------------------------------------------------


def _fingerprint(providers: List[ResolvedSsoProvider]) -> str:
    """A secret-free hash that changes whenever any routable provider changes.

    Secrets enter only as their own SHA-256, so a rotated secret changes the fingerprint (and
    rebuilds apiome-ui's auth instance) without the fingerprint revealing anything about it.
    """
    canonical = []
    for provider in providers:
        item = provider.model_dump()
        for key in ("client_secret", "sp_private_key"):
            value = item.pop(key)
            item[f"{key}_sha256"] = hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None
        canonical.append(item)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _unseal(blob: Any, key_id: Optional[str]) -> Optional[str]:
    """Decrypt a sealed secret, or ``None`` when none is stored."""
    if blob is None or key_id is None:
        return None
    return unseal_provider_secret(bytes(blob), key_id)


@internal_router.get(
    "/providers/resolved",
    response_model=ResolvedSsoProviderResponse,
    responses={
        401: {"description": "No internal service token presented."},
        403: {"description": "Internal service token invalid."},
        503: {
            "description": "Internal read path disabled (no INTERNAL_SERVICE_TOKEN), or the database is unavailable."
        },
    },
)
async def get_resolved_sso_providers(_: None = Depends(require_internal_service)):
    """Every enabled provider with a verified domain, secrets decrypted, for the sign-in resolver.

    A provider whose secret cannot be decrypted (rotated-away key, corrupt blob) is omitted and
    logged secret-free, so one bad row cannot take sign-in down for every other provider.
    """
    try:
        rows = store.list_routable_with_secrets(db)
    except Exception as exc:  # noqa: BLE001 — degrade to "no SSO", never a 500 with a trace
        logger.warning("could not read SSO providers: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "SSO providers are unavailable."})

    providers: List[ResolvedSsoProvider] = []
    for row in rows:
        try:
            client_secret = _unseal(row.get("client_secret_encrypted"), row.get("client_secret_key_id"))
            sp_private_key = _unseal(row.get("sp_private_key_encrypted"), row.get("sp_private_key_key_id"))
        except ProviderSecretDecryptionError:
            logger.warning("omitting SSO provider %s: its secret could not be decrypted", row["slug"])
            continue
        if row["protocol"] == PROTOCOL_OIDC and not client_secret:
            logger.warning("omitting SSO provider %s: no client secret", row["slug"])
            continue
        providers.append(
            ResolvedSsoProvider(
                id=row["id"],
                slug=row["slug"],
                plugin_provider_id=f"{PLUGIN_PROVIDER_PREFIX}{row['slug']}",
                identity_kind=provider_identity_kind(row["slug"]),
                protocol=row["protocol"],
                display_name=row["display_name"],
                issuer=row["issuer"],
                tenant_id=row.get("tenant_id"),
                domains=list(row.get("domains") or []),
                oidc_config=row.get("oidc_config") if row["protocol"] == PROTOCOL_OIDC else None,
                saml_config=row.get("saml_config") if row["protocol"] == PROTOCOL_SAML else None,
                client_secret=client_secret,
                sp_private_key=sp_private_key,
            )
        )
    return ResolvedSsoProviderResponse(providers=providers, fingerprint=_fingerprint(providers))
