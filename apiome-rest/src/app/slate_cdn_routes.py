"""Slate CDN / edge provider REST API — Slate 10.2 (private-suite#120).

What the CDN / edge provider section of the Slate Custom Domain screen consumes:

* ``GET    /v1/slate/environments/{environment_id}/cdn``
  — the lane's provider (Cloudflare, Fastly or a custom purge endpoint), whether a credential is
  stored, whether a deploy purges it, whether this deployment can seal credentials at all, and the
  most recent purge sent to it.

* ``POST   /v1/slate/environments/{environment_id}/cdn``
  — attach or update the provider. The credential is write-only: it is sealed
  (:mod:`app.slate_cdn_crypto`) before it is stored and is never returned. On an update it may be
  left blank to keep the stored one, unless the provider changes.

* ``DELETE /v1/slate/environments/{environment_id}/cdn``
  — detach the provider and delete its credential.

* ``GET    /v1/slate/environments/{environment_id}/cdn/dispatches``
  — every purge sent to the provider, deploy-triggered or manual, with what it answered.

Attaching a provider sets the lane's ``edge_attached``, which is what turns the cache plane's
purges (``POST .../cache/purge``, UXE-3.1) from records of intent into real evictions, and is what
makes :func:`app.slate_routes._run_activation` purge the CDN on every promotion and rollback.

Authorization matches the cache plane: reads require VERSIONS/VIEW; attaching, changing and
detaching require VERSIONS/PUBLISH, because pointing purges at a production CDN is a publish
action. Scope misses answer 404, not 403.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id
from .database import db
from .permissions import Action, Resource, enforce_permission
from .slate_auth import validate_slate_authentication
from .slate_cdn import (
    CODE_NOT_CONFIGURED,
    CODE_VAULT_NOT_CONFIGURED,
    CdnConfigError,
    normalize_config,
)
from .slate_cdn_crypto import (
    KEYS_SETTING,
    CdnCredentialEncryptionError,
    cdn_vault_configured,
    seal_cdn_credential,
    unseal_cdn_credential,
)
from .slate_cdn_dispatch import CdnPurgeOutcome
from .slate_cdn_store import (
    SlateCdnStoreError,
    delete_provider,
    get_provider,
    list_dispatches,
    save_provider,
)
from .slate_domains_store import get_environment_scope

router = APIRouter(prefix="/v1/slate", tags=["slate-cdn"])


class _CamelModel(BaseModel):
    """Wire base: snake_case fields, camelCase JSON, matching the rest of the Slate surface."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ─── Request/response models ─────────────────────────────────────────────────


class SaveCdnProviderRequest(_CamelModel):
    """Attach or update a lane's CDN provider."""

    provider: str = Field(description="cloudflare, fastly or custom.")
    target: str = Field(
        description="Cloudflare zone id, Fastly service id, or the custom https purge URL."
    )
    auth_header_name: Optional[str] = Field(
        default=None, description="Header a custom endpoint reads its credential from."
    )
    credential: Optional[str] = Field(
        default=None,
        description=(
            "Write-only. API token (Cloudflare), API key (Fastly) or header value (custom). "
            "Blank keeps the stored credential when the provider is unchanged."
        ),
    )
    purge_on_deploy: bool = Field(
        default=True, description="Purge the CDN when a release is promoted or rolled back."
    )


class CdnProviderBody(_CamelModel):
    """A lane's provider. Never carries the credential."""

    provider: str = Field(description="cloudflare, fastly or custom.")
    target: str = Field(description="Zone id, service id or purge URL.")
    auth_header_name: Optional[str] = Field(default=None)
    credential_set: bool = Field(description="A credential is stored.")
    credential_readable: bool = Field(
        description="The stored credential opens with this deployment's keys."
    )
    purge_on_deploy: bool = Field(description="Whether a deploy purges the CDN.")
    updated_at: Optional[str] = Field(default=None)
    updated_by: Optional[str] = Field(default=None)


class CdnDispatchBody(_CamelModel):
    """One purge sent to the provider."""

    id: str
    trigger: str = Field(description="deploy or manual.")
    provider: str
    mode: str = Field(description="urls or purge-all.")
    url_count: int
    sample_urls: List[str] = Field(default_factory=list)
    status: str = Field(description="succeeded, failed or skipped.")
    http_status: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    sentence: str = Field(description="What happened, in words.")
    release_id: Optional[str] = None
    cache_purge_id: Optional[str] = None
    actor_name: str = ""
    dispatched_at: Optional[str] = None


class CdnPurgeSummaryBody(_CamelModel):
    """What a purge sent to the CDN did, carried on activation and cache-purge responses."""

    status: str = Field(description="succeeded, failed or skipped.")
    provider: str
    mode: str = Field(description="urls or purge-all.")
    url_count: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    sentence: str = Field(description="What happened, in words.")
    dispatch_id: Optional[str] = None


def purge_summary(outcome: Optional[CdnPurgeOutcome]) -> Optional[CdnPurgeSummaryBody]:
    """Map a purge outcome to its wire summary.

    Args:
        outcome: The outcome, or None when the lane has no CDN.

    Returns:
        The summary, or None.
    """
    if outcome is None:
        return None
    return CdnPurgeSummaryBody(
        status=outcome.status,
        provider=outcome.provider,
        mode=outcome.mode,
        url_count=outcome.url_count,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
        sentence=outcome.sentence,
        dispatch_id=outcome.dispatch_id,
    )


class CdnConfigResponse(_CamelModel):
    """A lane's CDN configuration."""

    environment_id: str
    configured: bool = Field(description="A provider is attached.")
    vault_configured: bool = Field(
        description="This deployment can seal credentials. False means saving is refused."
    )
    edge_attached: bool = Field(description="Purges on this lane are dispatched to the CDN.")
    provider: Optional[CdnProviderBody] = None
    last_dispatch: Optional[CdnDispatchBody] = None


class CdnDispatchHistoryResponse(_CamelModel):
    """A lane's CDN purge log."""

    environment_id: str
    dispatches: List[CdnDispatchBody]


class CdnDetachResponse(_CamelModel):
    """The outcome of detaching a provider."""

    environment_id: str
    detached: bool


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp as ISO-8601, tolerating a string that already is one."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _actor(auth_data: Mapping[str, Any]) -> tuple[Optional[str], str]:
    """Resolve the acting user's id and a display name that is never empty."""
    return (
        get_authenticated_user_id(auth_data),
        str(auth_data.get("email") or auth_data.get("name") or "Unknown"),
    )


def _require_environment(tenant_id: str, environment_id: str) -> Dict[str, Any]:
    """Load a lane or answer 404 (not 403, so another tenant cannot confirm it exists)."""
    environment = get_environment_scope(db, tenant_id=tenant_id, environment_id=environment_id)
    if not environment:
        raise HTTPException(
            status_code=404,
            detail={"code": "environment_not_found", "message": "Environment not found."},
        )
    return environment


def _provider_body(row: Mapping[str, Any]) -> CdnProviderBody:
    """Map a provider row to the wire model, dropping the credential columns."""
    return CdnProviderBody(
        provider=str(row["provider"]),
        target=str(row["target"]),
        auth_header_name=row.get("auth_header_name"),
        credential_set=bool(row.get("credential_ciphertext")),
        credential_readable=unseal_cdn_credential(
            row.get("credential_ciphertext"), row.get("credential_key_version")
        )
        is not None,
        purge_on_deploy=bool(row.get("purge_on_deploy", True)),
        updated_at=_iso(row.get("updated_at")),
        updated_by=row.get("updated_by_actor_name"),
    )


def dispatch_body(row: Mapping[str, Any]) -> CdnDispatchBody:
    """Map a dispatch-log row to the wire model, with the sentence the UI prints.

    Args:
        row: A ``slate_cdn_purge_dispatches`` row.

    Returns:
        The wire model.
    """
    outcome = CdnPurgeOutcome(
        status=str(row["status"]),
        provider=str(row["provider"]),
        mode=str(row["mode"]),
        url_count=int(row.get("url_count") or 0),
        error_code=row.get("error_code"),
    )
    return CdnDispatchBody(
        id=str(row["id"]),
        trigger=str(row["trigger"]),
        provider=outcome.provider,
        mode=outcome.mode,
        url_count=outcome.url_count,
        sample_urls=list(row.get("sample_urls") or []),
        status=outcome.status,
        http_status=row.get("http_status"),
        error_code=outcome.error_code,
        error_message=row.get("error_message"),
        sentence=outcome.sentence,
        release_id=str(row["release_id"]) if row.get("release_id") else None,
        cache_purge_id=str(row["cache_purge_id"]) if row.get("cache_purge_id") else None,
        actor_name=str(row.get("actor_name") or ""),
        dispatched_at=_iso(row.get("dispatched_at")),
    )


def _config_response(tenant_id: str, environment_id: str) -> CdnConfigResponse:
    """Read a lane's provider and latest dispatch into the config response."""
    row = get_provider(db, tenant_id=tenant_id, environment_id=environment_id)
    latest = list_dispatches(db, tenant_id=tenant_id, environment_id=environment_id, limit=1)
    return CdnConfigResponse(
        environment_id=environment_id,
        configured=row is not None,
        vault_configured=cdn_vault_configured(),
        edge_attached=row is not None,
        provider=_provider_body(row) if row else None,
        last_dispatch=dispatch_body(latest[0]) if latest else None,
    )


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get(
    "/environments/{environment_id}/cdn",
    response_model=CdnConfigResponse,
    response_model_by_alias=True,
)
async def get_cdn_config(
    environment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CdnConfigResponse:
    """Return a lane's CDN provider (never its credential) and the last purge sent to it."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    return _config_response(tenant_id, environment_id)


@router.post(
    "/environments/{environment_id}/cdn",
    response_model=CdnConfigResponse,
    response_model_by_alias=True,
)
async def save_cdn_config(
    environment_id: str,
    request: SaveCdnProviderRequest,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CdnConfigResponse:
    """Attach or update a lane's CDN provider, sealing the credential before it is stored.

    Refusals: 422 ``cdn-config-invalid`` (every bad field listed in ``errors``), 422
    ``cdn-credential-required``, 409 ``cdn-vault-not-configured`` when this deployment has no
    key to seal credentials with — a credential is never stored in plaintext as a fallback.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    environment = _require_environment(tenant_id, environment_id)
    actor_id, actor_name = _actor(auth_data)
    existing = get_provider(db, tenant_id=tenant_id, environment_id=environment_id)

    try:
        config = normalize_config(
            provider=request.provider,
            target=request.target,
            auth_header_name=request.auth_header_name,
            credential=request.credential,
            existing_provider=str(existing["provider"]) if existing else None,
        )
    except CdnConfigError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc), "errors": exc.errors},
        ) from exc

    sealed = None
    if config.credential is not None:
        if not cdn_vault_configured():
            raise HTTPException(status_code=409, detail=_vault_refusal())
        try:
            sealed = seal_cdn_credential(config.credential)
        except CdnCredentialEncryptionError as exc:
            raise HTTPException(status_code=409, detail=_vault_refusal()) from exc

    try:
        save_provider(
            db,
            tenant_id=tenant_id,
            site_id=str(environment["site_id"]),
            environment_id=environment_id,
            provider=config.provider,
            target=config.target,
            auth_header_name=config.auth_header_name,
            sealed_credential=sealed,
            purge_on_deploy=request.purge_on_deploy,
            actor_id=actor_id,
            actor_name=actor_name,
        )
    except SlateCdnStoreError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "cdn-credential-required",
                "message": "Enter the credential the CDN authorizes purges with.",
                "errors": [str(exc)],
            },
        ) from exc
    return _config_response(tenant_id, environment_id)


def _vault_refusal() -> Dict[str, Any]:
    """The 409 body for a deployment that cannot seal credentials."""
    return {
        "code": CODE_VAULT_NOT_CONFIGURED,
        "message": (
            "This deployment has no key to encrypt CDN credentials with, so none can be stored. "
            f"An administrator must set {KEYS_SETTING}."
        ),
        "errors": [],
    }


@router.delete(
    "/environments/{environment_id}/cdn",
    response_model=CdnDetachResponse,
    response_model_by_alias=True,
)
async def detach_cdn(
    environment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CdnDetachResponse:
    """Detach a lane's CDN provider and delete its stored credential."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    actor_id, actor_name = _actor(auth_data)
    removed = delete_provider(
        db,
        tenant_id=tenant_id,
        environment_id=environment_id,
        actor_id=actor_id,
        actor_name=actor_name,
    )
    if not removed:
        raise HTTPException(
            status_code=404,
            detail={"code": CODE_NOT_CONFIGURED, "message": "No CDN provider is attached."},
        )
    return CdnDetachResponse(environment_id=environment_id, detached=True)


@router.get(
    "/environments/{environment_id}/cdn/dispatches",
    response_model=CdnDispatchHistoryResponse,
    response_model_by_alias=True,
)
async def get_cdn_dispatches(
    environment_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    auth_data: Dict[str, Any] = Depends(validate_slate_authentication),
) -> CdnDispatchHistoryResponse:
    """Return the purges sent to a lane's CDN, most recent first."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _require_environment(tenant_id, environment_id)
    rows = list_dispatches(db, tenant_id=tenant_id, environment_id=environment_id, limit=limit)
    return CdnDispatchHistoryResponse(
        environment_id=environment_id, dispatches=[dispatch_body(row) for row in rows]
    )
