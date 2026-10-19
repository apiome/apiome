"""Gateway configs — REST — CDG-5.3 (#5981).

Under ``/v1/tenants/{tenant_slug}``:

* ``GET /gateway-configs?connector=`` — the tenant's gateway configs (one per connector environment);
* ``GET /gateway-configs/{slug}`` — one, by slug or id, with the APIs it serves.

Both need ``imports:view`` (a gateway config is connector data). Connector sync keeps the rows
(:func:`app.gateway_config_store.refresh_gateway_configs`); pushing a catalog item back to the
gateway's format uses the export API (``POST /v1/export/{tenant}/preview`` for the fidelity report,
``…/dispatch`` to emit) with the target ``pushBack.target`` names.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from . import gateway_config_store as store
from .auth import validate_authentication
from .database import db
from .gateway_configs import GatewayConfigList, GatewayConfigOut
from .permissions import Action, Resource, enforce_permission

router = APIRouter(prefix="/v1/tenants", tags=["gateway-configs"])


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


@router.get(
    "/{tenant_slug}/gateway-configs",
    response_model=GatewayConfigList,
    response_model_by_alias=True,
    summary="List gateway configs",
)
async def list_tenant_gateway_configs(
    tenant_slug: str,
    connector: Optional[str] = Query(None, max_length=64, description="Only this connector's environments."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> GatewayConfigList:
    """Every live gateway config: one per (connector, environment), with its API count, auth and
    rate-limit posture, declared losses and push-back target (`imports:view`)."""
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target="gateway-configs")
    return GatewayConfigList(gateway_configs=store.list_gateway_configs(db, _tenant_id(auth_data), connector))


@router.get(
    "/{tenant_slug}/gateway-configs/{ref}",
    response_model=GatewayConfigOut,
    response_model_by_alias=True,
    summary="Read a gateway config",
)
async def read_tenant_gateway_config(
    tenant_slug: str, ref: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> GatewayConfigOut:
    """One gateway config, by slug or id, with the APIs its environment serves (`imports:view`).

    `pushBack.target` is the export target that writes this gateway's format (`kong`), or `null` with
    `pushBack.reason` — `fmt-7.7` for AWS API Gateway, Azure APIM and Apigee, whose emit modes are
    still to come (#5461).
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"gateway-config:{ref}")
    found = store.get_gateway_config(db, _tenant_id(auth_data), ref)
    if found is None:
        raise HTTPException(
            status_code=404, detail={"code": "gateway-config-not-found", "message": f"gateway config '{ref}' not found"}
        )
    return found
