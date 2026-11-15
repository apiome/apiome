"""SDK compatibility beacon routes — RDG-1.7 / SGD-3.1 (#4736).

* ``POST /v1/tenants/{tenant}/usage/sdk-beacon`` — the door an opted-in generated SDK reports to.
  Authentication is a workspace API key with the ``usage:ingest`` scope (or full access), exactly as
  for the usage ingest door; a browser session is refused. The report names an ``sdk_beacon`` usage
  source (``X-Apiome-Usage-Source`` header or ``source_id``), whose ``enabled`` flag is the tenant's
  off switch.
* ``GET /v1/tenants/{tenant}/usage/sdk-beacons?project=…&days=…`` — the owner's read: beacon counts
  grouped by the keys the SDK kit's compatibility manifest uses (``spec_revision_id``,
  ``api_version``, ``operation_id``), so they can be lined up with the manifest. Requires
  ``consumer_contracts:view``, like the other runtime-usage reads.

See :mod:`app.sdk_beacon` for what a beacon may carry (and everything it may not).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import sdk_beacon_store
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .sdk_beacon import OUTCOMES, SdkBeaconBatch
from .usage_ingest import CODE_BATCH_INVALID, CODE_KEY_REQUIRED, CODE_SOURCE_REQUIRED, UsageIngestError

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["usage"])

#: The header a report may name its source by (the same one the usage ingest door reads).
SOURCE_HEADER = "X-Apiome-Usage-Source"


class SdkBeaconRejection(BaseModel):
    """One rejected event — its index and why, never its content."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="The event's position in the report (0-based).")
    reason: str = Field(description="`revision-unknown`: not a published revision of the source's project.")


class SdkBeaconResponse(BaseModel):
    """What happened to a report."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    received_at: datetime
    accepted: int = Field(description="Events counted.")
    calls: int = Field(description="Calls the counted events stood for.")
    rejected: List[SdkBeaconRejection] = Field(default_factory=list)


class SdkBeaconCount(BaseModel):
    """Beacon calls for one revision, SDK version, operation and outcome."""

    model_config = ConfigDict(extra="forbid")

    spec_revision_id: str = Field(description="The published revision the SDK was generated from.")
    api_version: str
    sdk_name: str
    sdk_version: str
    operation_id: str = Field(description="The SDK kit manifest's operation id.")
    outcome: str = Field(description="One of " + ", ".join(f"`{o}`" for o in OUTCOMES) + ".")
    calls: int
    first_seen_at: datetime
    last_seen_at: datetime


class SdkBeaconCounts(BaseModel):
    """A project's beacon counts over a window."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    days: int
    counts: List[SdkBeaconCount] = Field(default_factory=list, description="Most calls first.")


def _project(tenant_id: str, ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id within the tenant.

    Args:
        tenant_id: The caller's tenant.
        ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        HTTPException: 404 ``usage-project-not-found``.
    """
    value = (ref or "").strip()
    row = None
    if value:
        row = db.get_project_by_id(value, tenant_id) if is_uuid_string(value) else db.get_project_by_slug(value, tenant_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "usage-project-not-found", "message": "no such project in this tenant"}
        )
    return row


def _error(exc: UsageIngestError) -> HTTPException:
    """Translate a refusal into the HTTP error the SDK sees."""
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


@router.post(
    "/{tenant_slug}/usage/sdk-beacon",
    response_model=SdkBeaconResponse,
    status_code=202,
    summary="Report SDK compatibility beacon counts",
    description=(
        "The door an **opted-in** generated SDK reports to (`apiome.sdk.beacon/v1`). Each event is "
        "an aggregated count of calls of one operation with one outcome — `ok`, `client_error`, "
        "`server_error`, `network` or `incompatible` — and names only the SDK and its version, the "
        "API version and published revision the SDK was generated from, and the operation id. There "
        "is no field for a body, header, status code, latency, URL, host, credential or caller "
        "identifier; unknown keys are refused (`422`).\n\n"
        "Counts land on the UTC day the server receives the report. Events naming a revision that "
        "is not a published revision of the source's project are rejected by index.\n\n"
        "Requires a workspace API key with the `usage:ingest` scope (or full access) and an enabled "
        "usage source of kind `sdk_beacon`: `403 usage-source-disabled` when the tenant has switched "
        "it off, `409 usage-source-kind-mismatch` for another kind of source."
    ),
    responses={
        400: {"description": "No source named, or the header and body name different sources."},
        403: {"description": "Not a workspace API key, or the source is disabled."},
        404: {"description": "Unknown source."},
        409: {"description": "`usage-source-kind-mismatch`: the source is not an `sdk_beacon` source."},
    },
)
def report_sdk_beacon(
    tenant_slug: str,
    body: SdkBeaconBatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    source_header: Optional[str] = Header(None, alias=SOURCE_HEADER, description="The `sdk_beacon` usage source."),
) -> SdkBeaconResponse:
    """Count one beacon report.

    Args:
        tenant_slug: The tenant in the URL.
        body: The report.
        auth_data: The authenticated principal — must be an API key.
        source_header: The source id, when the body has none.

    Returns:
        How many events were counted.
    """
    _ = tenant_slug
    if auth_data.get("auth_method") != "api_key":
        raise HTTPException(
            status_code=403,
            detail={
                "code": CODE_KEY_REQUIRED,
                "message": "SDK beacons take a workspace API key with the usage:ingest scope, not a session",
            },
        )
    tenant_id = str(auth_data.get("tenant_id") or "")
    body_source = str(body.source_id) if body.source_id else None
    header_source = (source_header or "").strip() or None
    now = datetime.now(timezone.utc)
    try:
        if header_source and body_source and header_source != body_source:
            raise UsageIngestError(
                400, CODE_BATCH_INVALID, f"the {SOURCE_HEADER} header and source_id name different sources"
            )
        source_ref = header_source or body_source
        if not source_ref:
            raise UsageIngestError(
                400, CODE_SOURCE_REQUIRED, f"name the sdk_beacon source with the {SOURCE_HEADER} header or source_id"
            )
        outcome = sdk_beacon_store.ingest_beacons(
            db, tenant_id=tenant_id, source_ref=source_ref, batch=body, now=now
        )
    except UsageIngestError as exc:
        raise _error(exc) from exc
    return SdkBeaconResponse(
        source_id=source_ref,
        received_at=now,
        accepted=outcome.accepted,
        calls=outcome.calls,
        rejected=[SdkBeaconRejection(index=r.index, reason=r.reason) for r in outcome.rejected],
    )


@router.get(
    "/{tenant_slug}/usage/sdk-beacons",
    response_model=SdkBeaconCounts,
    summary="Read a project's SDK beacon counts",
    description=(
        "Beacon calls over the last `days` UTC days (default 30, at most 400), grouped by "
        "`spec_revision_id`, `api_version`, `sdk_name`, `sdk_version`, `operation_id` and `outcome` — "
        "the keys of the SDK kit's compatibility manifest (`manifest.json` → `operations[].operation_id`, "
        "built for one published revision) — so incompatibilities can be lined up with the manifest "
        "they were generated from.\n\nRequires `consumer_contracts:view`."
    ),
)
def read_sdk_beacons(
    tenant_slug: str,
    project: str = Query(description="Project slug or id."),
    days: int = Query(default=30, ge=1, le=sdk_beacon_store.MAX_READ_DAYS),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkBeaconCounts:
    """Read a project's beacon counts.

    Args:
        tenant_slug: The tenant in the URL.
        project: Project slug or id.
        days: Window length in days.
        auth_data: The authenticated principal.

    Returns:
        The grouped counts.

    Raises:
        HTTPException: 403 without ``consumer_contracts:view``, 404 for an unknown project.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    tenant_id = str(auth_data.get("tenant_id") or "")
    project_row = _project(tenant_id, project)
    rows = sdk_beacon_store.list_beacon_counts(
        db, tenant_id=tenant_id, project_id=str(project_row["id"]), days=days, today=datetime.now(timezone.utc).date()
    )
    return SdkBeaconCounts(project_id=str(project_row["id"]), days=days, counts=[SdkBeaconCount(**row) for row in rows])
