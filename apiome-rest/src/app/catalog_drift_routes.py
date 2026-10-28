"""Catalog drift API — alert settings, an item's drift events, dismissing a banner (MFI-31.3, #4400).

* ``GET  /v1/catalog/{tenant}/drift-notifications`` — the tenant's drift alert settings
  (``projects:view``).
* ``PUT  /v1/catalog/{tenant}/drift-notifications`` — replace them (``imports:edit``, like the
  refresh kill switch).
* ``GET  /v1/catalog/{tenant}/{item_id}/drift`` — the item's drift events, newest first, each with
  its classified changes (``projects:view``).
* ``POST /v1/catalog/{tenant}/{item_id}/drift/{event_id}/dismiss`` — clear the badge and banner
  (``projects:edit``).

A drift event is recorded when a live refresh adds a version (:mod:`app.catalog_drift_service`).
The catalog list and detail carry each item's newest undismissed event as ``drift``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import catalog_drift_store as store
from .auth import validate_authentication
from .catalog_drift import (
    DELIVERY_IMMEDIATE,
    DriftSettings,
    drift_link,
    settings_from_row,
)
from .database import db
from .models import CatalogDriftBadge
from .permissions import Action, Resource, enforce_permission

logger = logging.getLogger(__name__)

__all__ = ["AUDIT_DISMISSED", "AUDIT_SETTINGS", "CatalogDriftBadge", "drift_badges", "router"]

router = APIRouter(prefix="/v1/catalog", tags=["catalog-drift"])

#: Workflow-audit actions.
AUDIT_SETTINGS = "catalog.drift.settings.saved"
AUDIT_DISMISSED = "catalog.drift.dismissed"

SeverityName = Literal["safe", "dangerous", "breaking"]


class CatalogDriftSettings(BaseModel):
    """The tenant's drift alert settings."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    notify_breaking: bool = Field(default=True, alias="notifyBreaking", description="Announce breaking drift.")
    notify_dangerous: bool = Field(default=True, alias="notifyDangerous", description="Announce dangerous drift.")
    notify_safe: bool = Field(
        default=False, alias="notifySafe", description="Announce safe drift. Off: safe drift only shows a badge."
    )
    delivery: Literal["immediate", "daily_digest"] = Field(
        default=DELIVERY_IMMEDIATE,
        description="immediate: one webhook per drift; daily_digest: one webhook a day listing it all.",
    )
    breaking_immediate: bool = Field(
        default=True,
        alias="breakingImmediate",
        description="With daily_digest, still send breaking drift right away.",
    )
    email_enabled: bool = Field(
        default=False,
        alias="emailEnabled",
        description="Opt in to drift email. Stored for a later email channel; no email is sent yet.",
    )


class CatalogDriftSettingsOut(CatalogDriftSettings):
    """The settings plus when they last changed and when the last digest went out."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    configured: bool = Field(description="False when the tenant uses the defaults.")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")
    last_digest_at: Optional[str] = Field(default=None, alias="lastDigestAt")


class CatalogDriftChange(BaseModel):
    """One classified change."""

    severity: SeverityName
    category: Optional[str] = None
    kind: Optional[str] = None
    key: Optional[str] = None
    rule_id: Optional[str] = Field(default=None, alias="ruleId")
    rationale: Optional[str] = None


class CatalogDriftEvent(CatalogDriftBadge):
    """One drift event with its classified changes."""

    parent_version_id: Optional[str] = Field(default=None, alias="parentVersionId")
    parent_version_label: Optional[str] = Field(default=None, alias="parentVersionLabel")
    notification: Literal["none", "sent", "pending_digest", "digested"]
    notified_at: Optional[str] = Field(default=None, alias="notifiedAt")
    dismissed_at: Optional[str] = Field(default=None, alias="dismissedAt")
    changes: List[CatalogDriftChange] = Field(
        default_factory=list, description="Worst first; at most 200 (changeCount is the full count)."
    )


class CatalogDriftEventList(BaseModel):
    """An item's drift events, newest first."""

    events: List[CatalogDriftEvent]


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _badge_fields(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The badge fields of an event row."""
    return {
        "event_id": str(row["id"]),
        "severity": row["severity"],
        "version_id": str(row["version_id"]),
        "version_label": str(row.get("version_label") or ""),
        "change_count": int(row.get("change_count") or 0),
        "counts": dict(row.get("counts") or {}),
        "trigger": row.get("trigger") or "sweep",
        "detected_at": _iso(row.get("created_at")),
        "link": drift_link(str(row["project_id"]), str(row["id"])),
    }


def _event_out(row: Mapping[str, Any]) -> CatalogDriftEvent:
    """An event row as the API returns it."""
    return CatalogDriftEvent(
        **_badge_fields(row),
        parent_version_id=str(row["parent_version_id"]) if row.get("parent_version_id") else None,
        parent_version_label=row.get("parent_version_label"),
        notification=row.get("notification") or "none",
        notified_at=_iso(row.get("notified_at")),
        dismissed_at=_iso(row.get("dismissed_at")),
        changes=[CatalogDriftChange(**change) for change in (row.get("changes") or [])],
    )


def drift_badges(tenant_id: str, item_ids: List[str]) -> Dict[str, CatalogDriftBadge]:
    """Each item's newest undismissed drift, for the catalog list and detail. Never raises.

    Args:
        tenant_id: The caller's tenant.
        item_ids: The items being returned.

    Returns:
        ``{item_id: badge}``; an item without open drift, or any read failure, has no entry.
    """
    try:
        rows = store.latest_open_events(db, tenant_id, item_ids)
    except Exception:  # noqa: BLE001 - a badge must never fail the catalog read
        logger.warning("catalog drift badges unavailable", exc_info=True)
        return {}
    return {item_id: CatalogDriftBadge(**_badge_fields(row)) for item_id, row in rows.items()}


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for the catalog.")
    return str(tenant_id)


def _require_item(tenant_id: str, item_id: str) -> None:
    """404 unless ``item_id`` is a live catalog item in the tenant."""
    if not db.get_catalog_item_by_id(item_id, tenant_id):
        raise HTTPException(status_code=404, detail=f"Catalog item not found: {item_id}")


def _audit(
    tenant_id: str, action: str, actor_id: Optional[str], detail: Dict[str, Any], project_id: Optional[str] = None
) -> None:
    """Write one workflow-audit row (best-effort)."""
    try:
        db.insert_workflow_audit(tenant_id, project_id, None, action, "success", actor_id, detail)
    except Exception:  # noqa: BLE001 — an audit failure never fails the request.
        logger.exception("catalog drift audit write failed action=%s", action)


def _settings_out(row: Optional[Mapping[str, Any]]) -> CatalogDriftSettingsOut:
    """The stored row (or the defaults) as the API returns it."""
    settings = settings_from_row(row)
    return CatalogDriftSettingsOut(
        **settings.as_dict(),
        configured=row is not None,
        updated_at=_iso((row or {}).get("updated_at")) if row else None,
        last_digest_at=_iso((row or {}).get("last_digest_at")) if row else None,
    )


# ---------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------


@router.get("/{tenant_slug}/drift-notifications", response_model=CatalogDriftSettingsOut, response_model_by_alias=True)
async def get_catalog_drift_settings(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogDriftSettingsOut:
    """Read the tenant's catalog drift alert settings (``projects:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="catalog:drift-notifications")
    return _settings_out(store.get_settings_row(db, tenant_id))


@router.put("/{tenant_slug}/drift-notifications", response_model=CatalogDriftSettingsOut, response_model_by_alias=True)
async def put_catalog_drift_settings(
    tenant_slug: str,
    body: CatalogDriftSettings,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogDriftSettingsOut:
    """Replace the tenant's catalog drift alert settings (``imports:edit``).

    Which severities are announced (the rest only badge), immediate or daily-digest delivery,
    whether breaking drift skips the digest, and the stored email opt-in. Announcements go to the
    tenant's push-webhook subscriptions and the item's owner team; a version created by **Check
    now** is never announced.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target="catalog:drift-notifications")
    settings = DriftSettings(**body.model_dump(by_alias=False))
    row = store.put_settings(db, tenant_id, settings, actor_id=actor_id)
    _audit(tenant_id, AUDIT_SETTINGS, actor_id, settings.as_dict())
    return _settings_out(row)


# ---------------------------------------------------------------------------------------
# Item events
# ---------------------------------------------------------------------------------------


@router.get("/{tenant_slug}/{item_id}/drift", response_model=CatalogDriftEventList, response_model_by_alias=True)
async def list_catalog_item_drift(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogDriftEventList:
    """List the item's drift events, newest first, with their classified changes (``projects:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target=f"catalog:{item_id}:drift")
    return CatalogDriftEventList(events=[_event_out(row) for row in store.list_events(db, tenant_id, item_id)])


@router.post(
    "/{tenant_slug}/{item_id}/drift/{event_id}/dismiss",
    response_model=CatalogDriftEvent,
    response_model_by_alias=True,
)
async def dismiss_catalog_item_drift(
    tenant_slug: str,
    item_id: str,
    event_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogDriftEvent:
    """Dismiss a drift event: its badge and banner go away; the event and its changes stay (``projects:edit``).

    Dismissing an already-dismissed event changes nothing.

    Raises:
        HTTPException: 404 when the item or the event is not found.
    """
    from .revision_deprecation import is_uuid_string

    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    actor_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=f"catalog:{item_id}:drift")
    row = store.dismiss_event(db, tenant_id, item_id, event_id, actor_id=actor_id) if is_uuid_string(event_id) else None
    if row is None:
        raise HTTPException(status_code=404, detail=f"Drift event not found: {event_id}")
    _audit(tenant_id, AUDIT_DISMISSED, actor_id, {"itemId": item_id, "eventId": event_id}, project_id=item_id)
    return _event_out(row)
