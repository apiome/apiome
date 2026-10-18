"""Catalog connector endpoints — CDG-1.1 (#5952).

```
GET    /v1/tenants/{t}/connectors
POST   /v1/tenants/{t}/connectors
GET    /v1/tenants/{t}/connectors/{id}
PATCH  /v1/tenants/{t}/connectors/{id}
DELETE /v1/tenants/{t}/connectors/{id}
POST   /v1/tenants/{t}/connectors/{id}/sync
GET    /v1/tenants/{t}/connectors/{id}/items
GET    /v1/tenants/{t}/connectors/{id}/runs
PUT    /v1/tenants/{t}/connectors/{id}/credentials
```

**Scoped by the authenticated tenant.** As on every ``/v1/tenants/{t}`` surface, the tenant in
the URL is informational; the caller's tenant scopes every read and write, so another tenant's
connector id is a 404.

**Permissions are the existing** ``imports`` **resource**: ``view`` lists and reads,
``create`` registers, ``edit`` updates, syncs and replaces credentials, ``delete`` deletes.

**Credentials are write-only.** ``PUT …/credentials`` seals the fields with the MCP credential
envelope and returns only their names; no route returns a credential, and the router uses
:class:`~app.redacted_validation_route.RedactedValidationRoute` so a malformed request's 422 does
not echo one either.

**Base URLs pass the SSRF rule** (:func:`app.catalog_connectors.check_connector_base_url`): a
private-range URL is a 422 with ``detail.reason = "private-address"`` unless the operator
allowlisted the range.

**Every mutation is audited** to the workflow audit under ``repository.connector.*``, so the
repository audit export carries it; no audit row holds a credential.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Mapping, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from . import catalog_connector_store as store
from .auth import validate_authentication
from .catalog_connector_sync import run_connector_sync, syncable_kinds, validate_connector_scope
from .catalog_connectors import (
    CODE_ENCRYPTION_UNCONFIGURED,
    CODE_INVALID,
    CODE_KIND_UNSUPPORTED,
    CODE_NAME_TAKEN,
    CODE_NOT_FOUND,
    CODE_SYNC_RUNNING,
    ITEM_STATUSES,
    KINDS,
    TRIGGER_MANUAL,
    ConnectorCreate,
    ConnectorCredentialsOut,
    ConnectorCredentialsPut,
    ConnectorError,
    ConnectorItemOut,
    ConnectorItemPage,
    ConnectorListResponse,
    ConnectorOut,
    ConnectorRunOut,
    ConnectorRunPage,
    ConnectorUpdate,
    connector_base_url_from_settings,
    validate_credentials,
    validate_name,
    validate_scope,
)
from .database import db
from .permissions import Action, Resource, enforce_permission
from .redacted_validation_route import RedactedValidationRoute

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_CREATE",
    "AUDIT_CREDENTIALS",
    "AUDIT_DELETE",
    "AUDIT_UPDATE",
    "router",
]

router = APIRouter(prefix="/v1/tenants", tags=["connectors"], route_class=RedactedValidationRoute)

#: Workflow-audit actions this module writes (the sync engine writes ``repository.connector.sync``).
AUDIT_CREATE = "repository.connector.created"
AUDIT_UPDATE = "repository.connector.updated"
AUDIT_DELETE = "repository.connector.deleted"
AUDIT_CREDENTIALS = "repository.connector.credentials_replaced"

_BASE = "/{tenant_slug}/connectors"

#: HTTP status per refusal code; anything else is a 422.
_STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_NAME_TAKEN: 409,
    CODE_SYNC_RUNNING: 409,
    CODE_KIND_UNSUPPORTED: 409,
    CODE_ENCRYPTION_UNCONFIGURED: 503,
}


def _iso(value: Any) -> Optional[str]:
    """ISO text for a timestamp, or ``None``."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _text(value: Any) -> Optional[str]:
    """``str(value)``, or ``None``."""
    return None if value is None else str(value)


def _refusal(exc: ConnectorError) -> HTTPException:
    """Map a connector refusal onto its status."""
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 422), detail=exc.as_detail())


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this connector.")
    return str(tenant_id)


def _connector_out(row: Mapping[str, Any]) -> ConnectorOut:
    """Project a connector row (credentials are never in it, only whether they exist)."""
    return ConnectorOut(
        id=str(row["id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        base_url=row.get("base_url"),
        scope=dict(row.get("scope") or {}),
        refresh_interval_seconds=row.get("refresh_interval_seconds"),
        conflict_policy=str(row.get("conflict_policy")),
        status=str(row.get("status")),
        has_credentials=bool(row.get("has_credentials")),
        syncable=str(row["kind"]) in syncable_kinds(),
        last_run_at=_iso(row.get("last_run_at")),
        created_by=_text(row.get("created_by")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _item_out(row: Mapping[str, Any]) -> ConnectorItemOut:
    """Project an inventory row."""
    return ConnectorItemOut(
        id=str(row["id"]),
        remote_id=str(row["remote_id"]),
        remote_name=row.get("remote_name"),
        environment=row.get("environment"),
        hosts=list(row.get("hosts") or []),
        base_path=row.get("base_path"),
        remote_revision=row.get("remote_revision"),
        remote_updated_at=_iso(row.get("remote_updated_at")),
        imported_revision=row.get("imported_revision"),
        status=str(row.get("status")),
        project_id=_text(row.get("project_id")),
        first_seen_at=_iso(row.get("first_seen_at")),
        last_seen_at=_iso(row.get("last_seen_at")),
        deployment=dict(row.get("deployment") or {}),
    )


def _run_out(row: Mapping[str, Any]) -> ConnectorRunOut:
    """Project a connector run row of the refresh ledger."""
    summary = row.get("run_summary") if isinstance(row.get("run_summary"), dict) else {}
    return ConnectorRunOut(
        id=str(row["id"]),
        connector_id=str(row["connector_id"]),
        refresh_source=str(row.get("refresh_source") or "connector"),
        trigger=summary.get("trigger"),
        status=str(row.get("status")),
        error_class=row.get("error_class"),
        http_status=row.get("http_status"),
        error_message=row.get("error_message"),
        pull_count=int(row.get("pull_count") or 0),
        summary=summary,
        created_by=_text(row.get("created_by")),
        started_at=_iso(row.get("started_at") or row.get("created_at")),
        finished_at=_iso(row.get("finished_at")),
    )


def _require_connector(tenant_id: str, connector_id: UUID) -> Dict[str, Any]:
    """The tenant's live connector, or a 404."""
    row = store.get_connector(db, tenant_id, str(connector_id))
    if row is None:
        raise _refusal(ConnectorError(CODE_NOT_FOUND, "Connector not found."))
    return row


def _audit(tenant_id: str, action: str, actor_id: Optional[str], detail: Dict[str, Any]) -> None:
    """Write one metadata-only workflow-audit row."""
    db.insert_workflow_audit(tenant_id, None, None, action, "success", actor_id, detail)


@router.get(_BASE, response_model=ConnectorListResponse, response_model_by_alias=True)
async def list_connectors(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConnectorListResponse:
    """List the tenant's catalog connectors (``imports:view``).

    Also returns every connector kind and the kinds this deployment can sync.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target="connectors")
    rows = store.list_connectors(db, tenant_id)
    return ConnectorListResponse(
        connectors=[_connector_out(r) for r in rows],
        kinds=list(KINDS),
        syncable_kinds=syncable_kinds(),
    )


@router.post(_BASE, response_model=ConnectorOut, response_model_by_alias=True, status_code=201)
async def create_connector(
    tenant_slug: str,
    body: ConnectorCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConnectorOut:
    """Register a catalog connector (``imports:create``).

    The base URL, when given, must pass the SSRF rule: a private-range URL is a 422 with
    ``detail.reason = "private-address"`` unless the operator allowlisted the range. Credentials
    are not accepted here; store them with ``PUT …/credentials``.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE, target="connectors")
    try:
        name = validate_name(body.name)
        scope = validate_scope(body.scope)
        base_url = connector_base_url_from_settings(body.base_url) if body.base_url else None
        validate_connector_scope(body.kind, scope, base_url)
        row = store.create_connector(
            db,
            tenant_id,
            kind=body.kind,
            name=name,
            base_url=base_url,
            scope=scope,
            refresh_interval_seconds=body.refresh_interval_seconds,
            conflict_policy=body.conflict_policy,
            status=body.status,
            created_by=actor_id,
        )
    except ConnectorError as exc:
        raise _refusal(exc) from exc
    _audit(tenant_id, AUDIT_CREATE, actor_id, {"connectorId": str(row["id"]), "kind": body.kind, "name": name})
    return _connector_out(row)


@router.get(_BASE + "/{connector_id}", response_model=ConnectorOut, response_model_by_alias=True)
async def get_connector(
    tenant_slug: str,
    connector_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConnectorOut:
    """Read one connector (``imports:view``). ``hasCredentials`` says whether one is stored."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"connector:{connector_id}")
    return _connector_out(_require_connector(tenant_id, connector_id))


@router.patch(_BASE + "/{connector_id}", response_model=ConnectorOut, response_model_by_alias=True)
async def update_connector(
    tenant_slug: str,
    connector_id: UUID,
    body: ConnectorUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConnectorOut:
    """Update a connector (``imports:edit``). The kind cannot change.

    ``status`` takes ``active`` or ``paused``; ``failing`` is set by runs only. Setting
    ``baseUrl`` re-runs the SSRF check.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"connector:{connector_id}")
    existing = _require_connector(tenant_id, connector_id)
    sent = body.model_dump(exclude_unset=True)
    changes: Dict[str, Any] = {}
    try:
        if "name" in sent:
            if body.name is None:
                raise ConnectorError(CODE_INVALID, "Connector name cannot be cleared.")
            changes["name"] = validate_name(body.name)
        if "base_url" in sent:
            changes["base_url"] = connector_base_url_from_settings(body.base_url) if body.base_url else None
        if "scope" in sent:
            changes["scope"] = validate_scope(body.scope)
        if "scope" in changes or "base_url" in changes:
            validate_connector_scope(
                str(existing["kind"]),
                changes.get("scope", existing.get("scope") or {}),
                changes.get("base_url", existing.get("base_url")),
            )
        if "refresh_interval_seconds" in sent:
            changes["refresh_interval_seconds"] = body.refresh_interval_seconds
        for field_name in ("conflict_policy", "status"):
            if field_name in sent:
                if sent[field_name] is None:
                    raise ConnectorError(CODE_INVALID, f"{field_name} cannot be cleared.")
                changes[field_name] = sent[field_name]
        row = store.update_connector(db, tenant_id, str(connector_id), changes)
    except ConnectorError as exc:
        raise _refusal(exc) from exc
    if row is None:
        raise _refusal(ConnectorError(CODE_NOT_FOUND, "Connector not found."))
    if changes:
        _audit(
            tenant_id,
            AUDIT_UPDATE,
            actor_id,
            {"connectorId": str(connector_id), "fields": sorted(changes)},
        )
    return _connector_out(row)


@router.delete(_BASE + "/{connector_id}", status_code=204)
async def delete_connector(
    tenant_slug: str,
    connector_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a connector (``imports:delete``).

    The connector stops syncing and its credential is destroyed. Its inventory, its runs and the
    catalog items it imported are kept.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.DELETE, target=f"connector:{connector_id}")
    row = store.soft_delete_connector(db, tenant_id, str(connector_id))
    if row is None:
        raise _refusal(ConnectorError(CODE_NOT_FOUND, "Connector not found."))
    _audit(tenant_id, AUDIT_DELETE, actor_id, {"connectorId": str(connector_id), "name": row.get("name")})
    return Response(status_code=204)


@router.post(_BASE + "/{connector_id}/sync", response_model=ConnectorRunOut, response_model_by_alias=True)
async def sync_connector(
    tenant_slug: str,
    connector_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConnectorRunOut:
    """Sync a connector now (``imports:edit``) and return the finished run.

    A manual sync runs even when the connector is paused and is not limited by the tenant quota
    (like Git "Refresh now"), but its pulls still count against it. A provider failure is not an
    HTTP error: the run comes back ``failed`` with ``errorClass`` and ``httpStatus``. A kind with
    no source on this deployment, or a sync already running, is a 409.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"connector:{connector_id}")
    connector = _require_connector(tenant_id, connector_id)
    try:
        result = await asyncio.to_thread(
            run_connector_sync, db, connector, trigger=TRIGGER_MANUAL, actor_id=actor_id
        )
    except ConnectorError as exc:
        raise _refusal(exc) from exc
    rows = store.list_runs(db, tenant_id, str(connector_id), limit=1, offset=0)
    run = next((r for r in rows if str(r["id"]) == result.run_id), None)
    if run is None:
        raise HTTPException(status_code=500, detail="The run finished but could not be read back.")
    return _run_out(run)


@router.get(_BASE + "/{connector_id}/items", response_model=ConnectorItemPage, response_model_by_alias=True)
async def list_connector_items(
    tenant_slug: str,
    connector_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    status: Optional[str] = Query(None, description="discovered | imported | ignored | missing"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ConnectorItemPage:
    """List the remote APIs a connector has seen (``imports:view``).

    ``catalogItemId`` links an imported API to its catalog item. An API that left the inventory
    is ``missing``; it is never deleted.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"connector:{connector_id}")
    _require_connector(tenant_id, connector_id)
    status_f = (status or "").strip() or None
    if status_f is not None and status_f not in ITEM_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: expected one of {list(ITEM_STATUSES)}")
    rows = store.list_items(db, str(connector_id), status=status_f, limit=limit, offset=offset)
    total = store.count_items(db, str(connector_id), status=status_f)
    return ConnectorItemPage(items=[_item_out(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get(_BASE + "/{connector_id}/runs", response_model=ConnectorRunPage, response_model_by_alias=True)
async def list_connector_runs(
    tenant_slug: str,
    connector_id: UUID,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ConnectorRunPage:
    """List a connector's sync runs, newest first (``imports:view``).

    Runs are rows of the same refresh ledger Git refresh jobs use (``refreshSource:
    "connector"``), and their pulls count against the same tenant quota.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"connector:{connector_id}")
    _require_connector(tenant_id, connector_id)
    rows = store.list_runs(db, tenant_id, str(connector_id), limit=limit, offset=offset)
    total = store.count_runs(db, tenant_id, str(connector_id))
    return ConnectorRunPage(runs=[_run_out(r) for r in rows], total=total, limit=limit, offset=offset)


@router.put(
    _BASE + "/{connector_id}/credentials",
    response_model=ConnectorCredentialsOut,
    response_model_by_alias=True,
)
async def put_connector_credentials(
    tenant_slug: str,
    connector_id: UUID,
    body: ConnectorCredentialsPut,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConnectorCredentialsOut:
    """Store or replace a connector's credential (``imports:edit``).

    The fields are sealed on arrival and the previous credential, if any, is replaced as a whole;
    there is no partial edit. The response names the stored fields and never their values. A 503
    means this deployment has no credential encryption key (``APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS``).
    """
    from .mcp_credential_crypto import CredentialEncryptionError, seal_credential_payload

    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"connector:{connector_id}")
    _require_connector(tenant_id, connector_id)
    try:
        plain = validate_credentials(body.credentials)
    except ConnectorError as exc:
        raise _refusal(exc) from exc
    try:
        sealed, key_version = seal_credential_payload(plain)
    except CredentialEncryptionError as exc:
        raise _refusal(
            ConnectorError(
                CODE_ENCRYPTION_UNCONFIGURED,
                "Credential encryption is not configured on this deployment; set "
                "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS.",
            )
        ) from exc
    finally:
        # Drop the plaintext reference as soon as it is sealed.
        fields = sorted(plain)
        plain = {}
    row = store.put_credentials(
        db, str(connector_id), encrypted_payload=sealed, key_version=key_version, created_by=actor_id
    )
    _audit(
        tenant_id,
        AUDIT_CREDENTIALS,
        actor_id,
        {"connectorId": str(connector_id), "fields": fields, "keyVersion": key_version},
    )
    return ConnectorCredentialsOut(
        connector_id=str(connector_id),
        has_credentials=True,
        fields=fields,
        replaced_at=_iso(row.get("replaced_at")),
    )
