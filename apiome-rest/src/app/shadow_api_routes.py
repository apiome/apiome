"""Shadow-API report endpoint — CDG-1.6 (#5957).

```
GET /v1/tenants/{t}/shadow-report?connector=&environment=
```

What connected gateways serve, against what the catalog describes (:mod:`app.shadow_api_report`):
**Shadow**, **Possible matches** (with tier and confidence; never linked automatically),
**Undeployed**, **Drift** and the **Ignored** rows with their reasons. A connector whose last run
failed is listed under ``stale`` with the time of its last successful run.

The actions on a row (link, ignore, unignore, import) live with the connector inventory in
:mod:`app.catalog_connector_routes`. Readable with ``imports:view``; scoped by the authenticated
tenant like every ``/v1/tenants/{t}`` surface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from . import shadow_api_store
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .shadow_api_report import build_shadow_report

__all__ = ["ShadowReport", "router"]

router = APIRouter(prefix="/v1/tenants", tags=["connectors"])


class _CamelModel(BaseModel):
    """Snake-case fields, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ShadowMatchTarget(_CamelModel):
    """The catalog item or Project a row may be."""

    project_id: str
    name: Optional[str] = None
    kind: str = Field(description="`catalog-item` or `project`.")
    version_id: Optional[str] = None
    version_label: Optional[str] = None


class ShadowMatch(_CamelModel):
    """A possible match: never applied until a person links the row."""

    tier: str = Field(description="`remote-id`, `host` or `title`, strongest first.")
    confidence: float = Field(description="0-1: remote-id 1.0, host 0.9 (with path) or 0.7, title up to 0.5.")
    reason: str
    target: ShadowMatchTarget


class ShadowIgnored(_CamelModel):
    """Why a row was ignored, and whether it has reappeared since."""

    reason: Optional[str] = None
    at: Optional[str] = None
    by: Optional[str] = None
    hosts: List[str] = Field(default_factory=list, description="Where the API was served when it was ignored.")
    base_path: Optional[str] = None
    reappeared: bool = Field(description="True when the API is now served on another host or base path.")


class ShadowItem(_CamelModel):
    """One gateway inventory row in a report section."""

    item_id: str
    connector_id: str
    connector_name: Optional[str] = None
    connector_kind: Optional[str] = None
    remote_id: Optional[str] = None
    name: Optional[str] = None
    environment: Optional[str] = None
    hosts: List[str] = Field(default_factory=list)
    base_path: Optional[str] = None
    status: Optional[str] = None
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    stale: bool = Field(default=False, description="From a connector whose last sync failed.")
    ignored: Optional[ShadowIgnored] = None
    match: Optional[ShadowMatch] = Field(default=None, description="Possible matches: the best candidate.")
    alternatives: List[ShadowMatch] = Field(default_factory=list)
    catalog_item_id: Optional[str] = Field(default=None, description="Drift: the linked catalog item or Project.")
    deployed_revision: Optional[str] = None
    deployed_updated_at: Optional[str] = None
    catalog_revision: Optional[str] = None
    catalog_version_label: Optional[str] = None
    reason_code: Optional[str] = Field(default=None, description="Drift: the RAR-2.2 comparator's reason.")


class ShadowUndeployed(_CamelModel):
    """A catalog item or published Project with HTTP servers that no connected gateway serves."""

    project_id: str
    name: Optional[str] = None
    kind: str
    version_id: Optional[str] = None
    version_label: Optional[str] = None
    servers: List[str] = Field(default_factory=list)


class ShadowConnector(_CamelModel):
    """A connector in the report's scope."""

    id: str
    name: Optional[str] = None
    kind: Optional[str] = None
    status: Optional[str] = None
    item_count: int = 0
    stale: bool = False
    stale_since: Optional[str] = None


class ShadowStale(_CamelModel):
    """A connector whose inventory may be out of date."""

    connector_id: str
    connector_name: Optional[str] = None
    since: Optional[str] = Field(default=None, description="Its last successful sync; null if it never had one.")
    message: str


class ShadowSummary(_CamelModel):
    """Row counts per section."""

    shadow: int = 0
    possible_matches: int = 0
    undeployed: int = 0
    drift: int = 0
    ignored: int = 0


class ShadowReport(_CamelModel):
    """``GET /v1/tenants/{t}/shadow-report``."""

    generated_at: str
    filters: Dict[str, Optional[str]]
    connectors: List[ShadowConnector]
    stale: List[ShadowStale]
    summary: ShadowSummary
    shadow: List[ShadowItem]
    possible_matches: List[ShadowItem]
    undeployed: List[ShadowUndeployed]
    drift: List[ShadowItem]
    ignored: List[ShadowItem]


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this report.")
    return str(tenant_id)


@router.get("/{tenant_slug}/shadow-report", response_model=ShadowReport, response_model_by_alias=True)
async def get_shadow_report(
    tenant_slug: str,
    connector: Optional[UUID] = Query(None, description="Only this connector's inventory."),
    environment: Optional[str] = Query(None, max_length=200, description="Only inventory rows in this environment."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """The shadow-API report (``imports:view``).

    **Shadow** lists gateway APIs with no catalog item and no plausible match; **possibleMatches**
    lists those that look like a catalog item or published Project, with the match tier and
    confidence (link one with ``POST …/connectors/{id}/items/{itemId}/link``); **undeployed** lists
    described APIs with HTTP servers that no connected gateway serves; **drift** lists linked APIs
    whose deployed revision the catalog does not have; **ignored** lists ignored rows with their
    reasons. An unknown connector id is a 404.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target="shadow-report")
    connector_id = str(connector) if connector else None
    env = (environment or "").strip() or None
    connectors = shadow_api_store.load_report_connectors(db, tenant_id, connector_id)
    if connector_id and not connectors:
        raise HTTPException(status_code=404, detail={"code": "connector-not-found", "message": "Connector not found."})
    items = shadow_api_store.load_report_items(db, [str(c["id"]) for c in connectors], env)
    entries = shadow_api_store.load_catalog_entries(db, tenant_id)
    return build_shadow_report(
        connectors=connectors, items=items, entries=entries, connector_filter=connector_id, environment=env
    )
