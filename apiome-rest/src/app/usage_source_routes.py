"""``POST /v1/tenants/{tenant_slug}/usage/sources/har`` — RDG-1.4 (#5762).

The door ``apiome usage upload file.har`` knocks on before it posts any event: "which source do
this project's HAR uploads in this environment go to?". The answer is found, checked or created
by :func:`app.usage_source_store.resolve_har_source`, and it carries what the CLI needs to decide
locally — above all whether the source's body window is open, because the CLI never sends a body
unless ``--sample-bodies`` is given **and** the source permits it.

**Authentication** is the same as the ingest door's sibling routes: a workspace API key with the
``usage:ingest`` scope (the key a developer already holds to upload) or full access, or a signed-in
session. The tenant is the authenticated principal's; the slug in the URL only names the route,
exactly as on ``…/usage/ingest``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .database import db
from .revision_deprecation import is_uuid_string
from .usage_ingest import UsageIngestError
from .usage_source_store import resolve_har_source

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["usage"])


class HarSourceRequest(BaseModel):
    """Which project and environment a HAR upload reports, and optionally which source."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project: str = Field(min_length=1, max_length=255, description="Project slug or UUID.")
    environment: str = Field(
        min_length=1,
        max_length=32,
        description="The environment the recorded traffic happened in (`prod`, `staging`, ...). `mock` is reserved.",
    )
    source_id: Optional[str] = Field(
        default=None,
        alias="sourceId",
        description="A `har` source of the project to use. Omit it to find the project's source, or create one.",
    )


class HarSourceResponse(BaseModel):
    """The source a HAR upload posts its events to."""

    model_config = ConfigDict(populate_by_name=True)

    source_id: str = Field(alias="sourceId", description="The `usage_source` to name on `…/usage/ingest`.")
    project_id: str = Field(alias="projectId", description="The source's project.")
    kind: str = Field(description="Always `har`.")
    environment: str = Field(description="The source's default environment.")
    sampling_rate: float = Field(alias="samplingRate", description="The source's head-sampling rate.")
    field_capture: bool = Field(
        alias="fieldCapture", description="Whether field presence is counted (on for a source created here)."
    )
    body_samples_open: bool = Field(
        alias="bodySamplesOpen",
        description="Whether the source accepts opt-in body samples right now (its body window is open).",
    )
    created: bool = Field(description="Whether this call created the source.")


def _project_id(tenant_id: str, project_ref: str) -> str:
    """Resolve a project slug or UUID within the tenant.

    Args:
        tenant_id: The authenticated tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project's UUID.

    Raises:
        HTTPException: 404 when the tenant has no such project.
    """
    ref = project_ref.strip()
    row = db.get_project_core(ref, tenant_id) if is_uuid_string(ref) else db.get_project_by_slug(ref, tenant_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "project-not-found", "message": f"Project not found: {ref}"}
        )
    return str(row["id"])


@router.post(
    "/{tenant_slug}/usage/sources/har",
    response_model=HarSourceResponse,
    response_model_by_alias=True,
    summary="Find or create a project's HAR usage source",
    description=(
        "Answers the `har` usage source that `apiome usage upload` posts a HAR file's events to "
        "(RDG-1.4).\n\n"
        "* With `sourceId`, that source is checked: it must belong to the project and be a `har` "
        "source (`409` otherwise).\n"
        "* Without it, the project's oldest `har` source in the environment is answered, or one is "
        "created with field capture on, sampling rate 1 and no body window. A disabled source is "
        "refused with `403`, never replaced.\n\n"
        "Takes a workspace API key with the `usage:ingest` scope (or full access), or a session."
    ),
    responses={
        400: {"description": "Invalid or reserved environment."},
        403: {"description": "The source is disabled."},
        404: {"description": "Unknown project or source."},
        409: {"description": "The named source belongs to another project, or is not a `har` source."},
    },
)
def resolve_har_usage_source(
    tenant_slug: str,
    body: HarSourceRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> HarSourceResponse:
    """Find, check or create the HAR source of a project.

    Args:
        tenant_slug: The tenant in the URL (the principal's tenant is used).
        body: Project, environment and optional source id.
        auth_data: The authenticated principal.

    Returns:
        The source's id and the settings the CLI acts on.

    Raises:
        HTTPException: See the route's documented responses.
    """
    tenant_id = str(auth_data.get("tenant_id") or "")
    project_id = _project_id(tenant_id, body.project)
    source_ref = (body.source_id or "").strip() or None
    try:
        resolved = resolve_har_source(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            environment=body.environment.strip(),
            source_ref=source_ref,
        )
    except UsageIngestError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail()) from exc
    source = resolved.source
    return HarSourceResponse(
        source_id=source.id,
        project_id=source.project_id,
        kind=source.kind,
        environment=source.environment,
        sampling_rate=source.sampling_rate,
        field_capture=source.field_capture,
        body_samples_open=source.body_window_open(datetime.now(timezone.utc)),
        created=resolved.created,
    )
