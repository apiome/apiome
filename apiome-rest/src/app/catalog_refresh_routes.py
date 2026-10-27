"""Catalog item refresh API — per-item cadence, check now, tenant kill switch (MFI-31.1, #4398).

* ``GET    /v1/catalog/{tenant}/{item_id}/refresh`` — the item's refresh setting and last check.
* ``PUT    /v1/catalog/{tenant}/{item_id}/refresh`` — create or replace it.
* ``DELETE /v1/catalog/{tenant}/{item_id}/refresh`` — remove it (and its credential).
* ``POST   /v1/catalog/{tenant}/{item_id}/refresh/check`` — run one check now.
* ``GET`` / ``PUT /v1/catalog/{tenant}/refresh-policy`` — the tenant kill switch.

Item routes look the item up first, so an id from another tenant (or a Project's id) is a 404,
then check the permission: ``projects:view`` to read, ``projects:edit`` to change or check. The
kill switch needs ``imports:edit``, like the repository polling quota. The credential is sealed on
arrival and never returned; validation errors are redacted so a rejected body never echoes it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import catalog_refresh_store as store
from .auth import validate_authentication
from .catalog_refresh import (
    AUTH_TYPES,
    CADENCE_OFF,
    CADENCE_SECONDS,
    CADENCES,
    CODE_ENCRYPTION_UNCONFIGURED,
    CODE_REFRESH_DISABLED,
    CODE_REFRESH_OFF,
    STATUS_NEVER,
    RefreshSettingsError,
    refreshable_adapters,
    run_refresh_check,
    validate_refresh_settings,
)
from .database import db
from .permissions import Action, Resource, enforce_permission
from .redacted_validation_route import RedactedValidationRoute

logger = logging.getLogger(__name__)

__all__ = ["AUDIT_CHECKED", "AUDIT_DELETED", "AUDIT_POLICY", "AUDIT_SAVED", "router"]

router = APIRouter(prefix="/v1/catalog", tags=["catalog-refresh"], route_class=RedactedValidationRoute)

#: Workflow-audit actions this module writes (metadata only, never the credential).
AUDIT_SAVED = "catalog.refresh.saved"
AUDIT_DELETED = "catalog.refresh.deleted"
AUDIT_CHECKED = "catalog.refresh.checked"
AUDIT_POLICY = "catalog.refresh.policy_changed"

#: HTTP status per refusal code; anything else is a 422.
_STATUS_BY_CODE = {
    CODE_REFRESH_OFF: 409,
    CODE_REFRESH_DISABLED: 409,
    CODE_ENCRYPTION_UNCONFIGURED: 503,
}

CadenceName = Literal["off", "manual", "hourly", "daily", "weekly"]
AuthTypeName = Literal["none", "bearer", "header", "oauth2"]


# ---------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------


class CatalogRefreshCredential(BaseModel):
    """A credential to seal for the live source. Sealed on arrival and never returned."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    auth_type: AuthTypeName = Field(alias="authType")
    payload: Dict[str, SecretStr] = Field(
        default_factory=dict,
        description=(
            'The credential fields for the type: `bearer` → `{"token"}`, `header` → '
            '`{"name", "value"}`, `oauth2` → `{"access_token"}`, `none` → `{}`.'
        ),
    )


class CatalogRefreshUpdate(BaseModel):
    """``PUT …/{item_id}/refresh``: the whole setting.

    Leave ``credential`` out to keep the stored one, send ``null`` to clear it, or send an object
    to replace it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    cadence: CadenceName = Field(description="off · manual · hourly · daily · weekly.")
    adapter: str = Field(min_length=1, max_length=64, description="The import adapter: `graphql` or `grpc`.")
    endpoint: str = Field(
        min_length=1,
        max_length=2048,
        description="An http(s) URL for GraphQL; a `host:port` target for gRPC.",
    )
    options: Dict[str, Any] = Field(
        default_factory=dict, description="Adapter options; gRPC reads `secure` (TLS, default false)."
    )
    credential: Optional[CatalogRefreshCredential] = None


class CatalogRefreshOut(BaseModel):
    """An item's refresh setting and the outcome of its last check. Never carries a credential."""

    model_config = ConfigDict(populate_by_name=True)

    item_id: str = Field(alias="itemId")
    configured: bool = Field(description="False when the item has no refresh setting (the defaults below).")
    cadence: CadenceName
    adapter: Optional[str] = None
    endpoint: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)
    auth_type: AuthTypeName = Field(default="none", alias="authType")
    has_credential: bool = Field(default=False, alias="hasCredential")
    status: Literal["never", "unchanged", "changed", "failed"] = STATUS_NEVER
    last_checked_at: Optional[str] = Field(default=None, alias="lastCheckedAt")
    last_success_at: Optional[str] = Field(default=None, alias="lastSuccessAt")
    last_failure_at: Optional[str] = Field(default=None, alias="lastFailureAt")
    last_error: Optional[str] = Field(default=None, alias="lastError")
    last_fingerprint: Optional[str] = Field(default=None, alias="lastFingerprint")
    consecutive_failures: int = Field(default=0, alias="consecutiveFailures")
    next_check_at: Optional[str] = Field(
        default=None,
        alias="nextCheckAt",
        description="When the sweep next checks the item (null for off / manual).",
    )
    tenant_enabled: bool = Field(default=True, alias="tenantEnabled")
    cadences: list[str] = Field(default_factory=lambda: list(CADENCES))
    adapters: list[str] = Field(default_factory=list, description="Adapters that can be refreshed.")
    auth_types: list[str] = Field(default_factory=lambda: list(AUTH_TYPES), alias="authTypes")


class CatalogRefreshPolicy(BaseModel):
    """The tenant kill switch for catalog item refresh."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: bool


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _iso(value: Any) -> Optional[str]:
    """ISO text for a timestamp, or ``None``."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _next_check_at(row: Mapping[str, Any]) -> Optional[str]:
    """When the sweep is next due to check a row: the later of cadence-due and backoff.

    ``None`` for off / manual cadences. A never-checked scheduled row is due now.
    """
    seconds = CADENCE_SECONDS.get(str(row.get("cadence")))
    if seconds is None:
        return None
    from datetime import datetime, timedelta, timezone

    last = row.get("last_checked_at")
    due = (last + timedelta(seconds=seconds)) if hasattr(last, "isoformat") else datetime.now(timezone.utc)
    backoff = row.get("next_check_after")
    if hasattr(backoff, "isoformat") and backoff > due:
        due = backoff
    return _iso(due)


def _out(item_id: str, row: Optional[Mapping[str, Any]], *, tenant_enabled: bool) -> CatalogRefreshOut:
    """Project a refresh row (or its absence) for the API."""
    adapters = refreshable_adapters()
    if row is None:
        return CatalogRefreshOut(
            item_id=item_id, configured=False, cadence=CADENCE_OFF, tenant_enabled=tenant_enabled, adapters=adapters
        )
    return CatalogRefreshOut(
        item_id=item_id,
        configured=True,
        cadence=str(row["cadence"]),
        adapter=str(row["adapter_key"]),
        endpoint=str(row["endpoint"]),
        options=dict(row.get("options") or {}),
        auth_type=str(row.get("auth_type") or "none"),
        has_credential=bool(row.get("has_credential")),
        status=str(row.get("status") or STATUS_NEVER),
        last_checked_at=_iso(row.get("last_checked_at")),
        last_success_at=_iso(row.get("last_success_at")),
        last_failure_at=_iso(row.get("last_failure_at")),
        last_error=row.get("last_error"),
        last_fingerprint=row.get("last_fingerprint"),
        consecutive_failures=int(row.get("consecutive_failures") or 0),
        next_check_at=_next_check_at(row),
        tenant_enabled=tenant_enabled,
        adapters=adapters,
    )


def _refusal(exc: RefreshSettingsError) -> HTTPException:
    """Map a refusal onto its status with a ``{code, message}`` detail."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 422), detail={"code": exc.code, "message": exc.message}
    )


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this catalog item.")
    return str(tenant_id)


def _require_item(tenant_id: str, item_id: str) -> None:
    """404 unless ``item_id`` is a live catalog item in the tenant."""
    if not db.get_catalog_item_by_id(item_id, tenant_id):
        raise HTTPException(status_code=404, detail=f"Catalog item not found: {item_id}")


def _audit(tenant_id: str, action: str, actor_id: Optional[str], detail: Dict[str, Any]) -> None:
    """Write one metadata-only workflow-audit row (best-effort)."""
    try:
        db.insert_workflow_audit(tenant_id, None, None, action, "success", actor_id, detail)
    except Exception:  # noqa: BLE001 — an audit failure never fails the request.
        logger.exception("catalog refresh audit write failed action=%s", action)


def _seal(credential: CatalogRefreshCredential) -> Optional[tuple]:
    """Seal a credential into the ``(auth_type, blob, key_version)`` tuple the store takes.

    ``None`` for ``auth_type: none`` (nothing to store).

    Raises:
        RefreshSettingsError: ``encryption-unconfigured`` when the deployment has no key.
    """
    from .mcp_credential_crypto import CredentialEncryptionError, seal_credential_payload

    if credential.auth_type == "none":
        return None
    plain = {key: value.get_secret_value() for key, value in credential.payload.items()}
    try:
        blob, key_version = seal_credential_payload(plain)
    except CredentialEncryptionError as exc:
        raise RefreshSettingsError(
            CODE_ENCRYPTION_UNCONFIGURED,
            "Credential encryption is not configured on this deployment; set APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS.",
        ) from exc
    finally:
        plain = {}
    return (credential.auth_type, blob, key_version)


# ---------------------------------------------------------------------------------------
# Tenant kill switch
# ---------------------------------------------------------------------------------------


@router.get("/{tenant_slug}/refresh-policy", response_model=CatalogRefreshPolicy)
async def get_catalog_refresh_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogRefreshPolicy:
    """Read the tenant kill switch for catalog item refresh (``projects:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="catalog:refresh-policy")
    return CatalogRefreshPolicy(enabled=store.get_tenant_refresh_enabled(db, tenant_id))


@router.put("/{tenant_slug}/refresh-policy", response_model=CatalogRefreshPolicy)
async def set_catalog_refresh_policy(
    tenant_slug: str,
    body: CatalogRefreshPolicy,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogRefreshPolicy:
    """Turn catalog item refresh on or off for the whole tenant (``imports:edit``).

    Off stops the scheduled sweep and manual checks for every item in the tenant; each item's
    setting is kept and resumes when the switch is turned back on.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target="catalog:refresh-policy")
    enabled = store.set_tenant_refresh_enabled(db, tenant_id, body.enabled)
    _audit(tenant_id, AUDIT_POLICY, actor_id, {"enabled": enabled})
    return CatalogRefreshPolicy(enabled=enabled)


# ---------------------------------------------------------------------------------------
# Per-item setting
# ---------------------------------------------------------------------------------------


@router.get("/{tenant_slug}/{item_id}/refresh", response_model=CatalogRefreshOut, response_model_by_alias=True)
async def get_catalog_item_refresh(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogRefreshOut:
    """Read an item's refresh setting and last check (``projects:view``).

    An item with no setting answers ``configured: false`` with cadence ``off``.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target=f"catalog:{item_id}:refresh")
    return _out(
        item_id,
        store.get_refresh(db, item_id, tenant_id),
        tenant_enabled=store.get_tenant_refresh_enabled(db, tenant_id),
    )


@router.put("/{tenant_slug}/{item_id}/refresh", response_model=CatalogRefreshOut, response_model_by_alias=True)
async def put_catalog_item_refresh(
    tenant_slug: str,
    item_id: str,
    body: CatalogRefreshUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogRefreshOut:
    """Create or replace an item's refresh setting (``projects:edit``).

    The adapter must support live discovery and have a refresh runner (``graphql``, ``grpc``);
    the endpoint must pass the SSRF URL policy. Changing the adapter or endpoint resets the check
    history; saving always clears any failure backoff.

    Raises:
        HTTPException: 404 for an unknown item; 422 ``adapter-not-refreshable`` /
            ``invalid-endpoint`` / ``invalid-credential``; 503 when credential encryption is not
            configured and a credential is supplied.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    actor_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=f"catalog:{item_id}:refresh")

    credential: Any = store.KEEP_CREDENTIAL
    try:
        new_auth = body.credential.auth_type if body.credential else None
        new_payload = {k: v.get_secret_value() for k, v in body.credential.payload.items()} if body.credential else None
        adapter_key = validate_refresh_settings(
            cadence=body.cadence,
            adapter_key=body.adapter,
            endpoint=body.endpoint,
            auth_type=new_auth,
            auth_payload=new_payload,
        )
        new_payload = None
        if "credential" in body.model_fields_set:
            credential = _seal(body.credential) if body.credential is not None else None
    except RefreshSettingsError as exc:
        raise _refusal(exc) from exc

    row = store.upsert_refresh(
        db,
        project_id=item_id,
        tenant_id=tenant_id,
        cadence=body.cadence,
        adapter_key=adapter_key,
        endpoint=body.endpoint.strip(),
        options=body.options,
        credential=credential,
        user_id=actor_id,
    )
    _audit(
        tenant_id,
        AUDIT_SAVED,
        actor_id,
        {
            "itemId": item_id,
            "cadence": body.cadence,
            "adapter": adapter_key,
            "credential": "kept"
            if credential is store.KEEP_CREDENTIAL
            else ("cleared" if credential is None else "replaced"),
        },
    )
    return _out(item_id, row, tenant_enabled=store.get_tenant_refresh_enabled(db, tenant_id))


@router.delete("/{tenant_slug}/{item_id}/refresh", status_code=204)
async def delete_catalog_item_refresh(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Remove an item's refresh setting and its credential (``projects:edit``). Idempotent."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    actor_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=f"catalog:{item_id}:refresh")
    if store.delete_refresh(db, item_id, tenant_id):
        _audit(tenant_id, AUDIT_DELETED, actor_id, {"itemId": item_id})
    return Response(status_code=204)


@router.post("/{tenant_slug}/{item_id}/refresh/check", response_model=CatalogRefreshOut, response_model_by_alias=True)
async def check_catalog_item_refresh(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogRefreshOut:
    """Run one live check now and return the recorded outcome (``projects:edit``).

    Works for every cadence except ``off``, including ``manual``. A failed check answers 200 with
    ``status: failed`` and the reason; like a scheduled failure it backs off the next scheduled
    check and never creates a version.

    Raises:
        HTTPException: 404 when the item has no refresh setting; 409 ``refresh-off`` when its
            cadence is off, ``refresh-disabled`` when the tenant or deployment switch is off.
    """
    from .config import settings

    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    actor_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=f"catalog:{item_id}:refresh")

    row = store.get_refresh_for_check(db, item_id)
    if row is None or str(row.get("tenant_id")) != tenant_id:
        raise HTTPException(status_code=404, detail=f"Catalog item has no refresh setting: {item_id}")
    if row["cadence"] == CADENCE_OFF:
        raise _refusal(RefreshSettingsError(CODE_REFRESH_OFF, "Refresh is off for this item; choose a cadence first."))
    if not settings.catalog_refresh_enabled or not store.get_tenant_refresh_enabled(db, tenant_id):
        raise _refusal(
            RefreshSettingsError(CODE_REFRESH_DISABLED, "Catalog refresh is switched off for this workspace.")
        )

    outcome = await run_refresh_check(
        db,
        row,
        timeout_seconds=float(settings.catalog_refresh_timeout_seconds),
        backoff_base_seconds=float(settings.catalog_refresh_backoff_base_seconds),
        backoff_max_seconds=float(settings.catalog_refresh_backoff_max_seconds),
    )
    _audit(tenant_id, AUDIT_CHECKED, actor_id, {"itemId": item_id, "status": outcome.status})
    return _out(item_id, store.get_refresh(db, item_id, tenant_id), tenant_enabled=True)
