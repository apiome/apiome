"""``GET /v1/tenants/{tenant}/projects/{project}/sdk-compatibility`` — SGD-2.1 (#4735).

Serves the generator compatibility manifest (:mod:`app.sdk_compat_manifest`) for one revision of a
project — the document the dashboard's **Export studio → SDK compatibility** tab and
``apiome sdk compatibility`` both render, so the two always show the same thing.

The manifest describes the artifacts of the SDK kit built from that revision — the same kit the
browse **Get SDK** surface serves — so it is built here the same way: the revision's canonical
model (:func:`app.export_source.load_export_source`), the project's SDK settings
(:func:`app.sdk_generation_settings_store.load_settings`), and :func:`app.sdk_kit.build_client_kit`.
Unlike the public kit route, this one is for the API's owners: it needs ``projects:view``, works for
any revision the caller can see (published or not, public or private), and needs no public-SDK
opt-in. The revision's classified changelog (CTG-3.1), when it has one, supplies the semver block.

The manifest is deterministic, so its digest is served as a strong ``ETag`` and an
``If-None-Match`` hit is a ``304``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from .auth import validate_authentication
from .database import db
from .export_source import ExportSourceError, load_export_source
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .sdk_compat_manifest import ChangelogInfo, SdkCompatManifest, build_compat_manifest, manifest_etag
from .sdk_generation_settings import PatternContext, ResolvedBranding
from .sdk_generation_settings_store import load_settings
from .sdk_kit import KitCoordinates, build_client_kit

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["sdk-generation"])


def _project(tenant_id: str, ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id within the tenant, or 404."""
    value = (ref or "").strip()
    row = None
    if value:
        row = db.get_project_core(value, tenant_id) if is_uuid_string(value) else db.get_project_by_slug(value, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "sdk-compat-project-not-found", "message": "No such project."})
    return row


def _changelog(tenant_id: str, project_id: str, revision_id: str) -> Optional[ChangelogInfo]:
    """The revision's classified changelog and its baseline's label, when it has one.

    A failure to read it degrades to "unknown" rather than failing the manifest.
    """
    try:
        row = db.get_version_changelog(revision_id, tenant_id, project_id)
    except Exception:  # noqa: BLE001 — the semver block is optional evidence
        return None
    if not row or row.get("status") not in (None, "ready"):
        return None
    baseline_label = None
    baseline_id = row.get("baseline_revision_id")
    if baseline_id:
        try:
            baseline = db.get_version_core(str(baseline_id), tenant_id)
        except Exception:  # noqa: BLE001
            baseline = None
        baseline_label = (baseline or {}).get("version_id")
    return ChangelogInfo(max_severity=row.get("max_severity"), baseline_version=baseline_label)


@router.get(
    "/{tenant_slug}/projects/{project_ref}/sdk-compatibility",
    response_model=SdkCompatManifest,
    summary="Get the generator compatibility manifest for a revision",
    description=(
        "The `apiome.sdk.compat-manifest/v1` manifest for the SDK kit built from one revision: the "
        "canonical constructs the version contains, and for each generated artifact (snippets, the "
        "Go client, the FastAPI and Express server stubs, the Terraform provider, the MCP server) its "
        "operation coverage, runtime and dependencies, supported and unsupported auth schemes, "
        "pagination handling, generator and artifact digests, and **findings** — every construct the "
        "artifact leaves out or cannot represent, with a stable `code` and the `action` to take. "
        "Source and options digests and the semver compatibility of the revision against its "
        "classified changelog's baseline complete it.\n\n"
        "`version` is a revision id or version label; the latest revision when omitted. Works for "
        "draft and private revisions. Served with a strong `ETag` (`304` on `If-None-Match`).\n\n"
        "Requires `projects:view`."
    ),
    responses={
        304: {"description": "Not modified."},
        404: {"description": "Unknown project or version."},
        422: {"description": "The revision has no usable source to generate from."},
    },
)
def get_sdk_compatibility(
    request: Request,
    response: Response,
    tenant_slug: str,
    project_ref: str,
    version: Optional[str] = Query(default=None, description="Revision id or version label; latest when omitted."),
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """Build and return the compatibility manifest.

    Args:
        request: The request (for the running Apiome version).
        response: The response (for the ``ETag`` header).
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version: Revision id or label.
        if_none_match: The client's cached ``ETag``.
        auth_data: The authenticated principal.

    Returns:
        The manifest, or an empty ``304``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = str(auth_data.get("tenant_id") or "")
    project = _project(tenant_id, project_ref)
    project_id = str(project["id"])
    try:
        source = load_export_source(tenant_id, project_id, version)
    except ExportSourceError as exc:
        code = "sdk-compat-version-not-found" if exc.status_code == 404 else "sdk-compat-no-source"
        raise HTTPException(status_code=exc.status_code, detail={"code": code, "message": str(exc)}) from exc

    label = source.version_label or source.version_record_id
    settings = load_settings(
        tenant_id, project_id, PatternContext(tenant=tenant_slug, project=str(project.get("slug") or project_id), version=label)
    )
    branding = ResolvedBranding(
        package_names=dict(settings.resolved.package_names),
        license_header=settings.resolved.license_header,
        user_agent=settings.resolved.user_agent,
    )
    kit = build_client_kit(
        source.api,
        coordinates=KitCoordinates(
            tenant_slug=tenant_slug,
            project_slug=str(project.get("slug") or project_id),
            version_slug=label,
            version_record_id=source.version_record_id,
            version_label=source.version_label,
        ),
        branding=branding,
        source_text=source.source_text,
        source_format=source.source_format,
        settings_fingerprint=settings.content_fingerprint,
        apiome_version=getattr(request.app, "version", None),
    )
    manifest = build_compat_manifest(
        source.api,
        kit.manifest,
        kit.content,
        source_text=source.source_text,
        settings_fingerprint=settings.content_fingerprint,
        package_names=branding.package_names,
        user_agent=branding.user_agent,
        license_header=branding.license_header,
        changelog=_changelog(tenant_id, project_id, source.version_record_id),
    )
    etag = manifest_etag(manifest)
    if if_none_match and etag in [tag.strip() for tag in if_none_match.split(",")]:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    return manifest
