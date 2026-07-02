"""Pre-publish validation shared by POST …/publish (#3212)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from .compatibility_engine import CompatibilityCheckEngine, openapi_for_revision
from .database import db
from .models import VersionPublishRequest
from .publication_change_report import resolve_baseline_revision_id_for_change_report
from .schema_compatibility import CompatibilityRules


def enforce_publish_prechecks(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    existing: Dict[str, Any],
    request: VersionPublishRequest,
) -> None:
    """
    Ensure draft revisions satisfy publication gates unless ``skip_publish_checks`` is set.

    Raises:
        HTTPException: 422 for documentation gaps or invalid OpenAPI materialization.
        HTTPException: 409 when compatibility is breaking and ``allow_breaking`` is false.
    """
    if bool(request.skip_publish_checks):
        return

    version_record_id = str(existing["id"])

    try:
        openapi_for_revision(existing, tenant_slug, tenant_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not build OpenAPI for this revision (schema validation): {exc}",
        ) from exc

    classes = db.get_classes_for_version(version_record_id)
    missing = [c for c in classes if not str(c.get("description") or "").strip()]
    if missing:
        first = str(missing[0].get("name") or missing[0].get("id") or "?")
        raise HTTPException(
            status_code=422,
            detail=(
                f"{len(missing)} class(es) are missing required descriptions "
                f"(first: {first!r})."
            ),
        )

    baseline_revision_id = resolve_baseline_revision_id_for_change_report(
        project_id=project_id,
        tenant_id=tenant_id,
        candidate_revision_id=version_record_id,
        mode=request.change_report_baseline_mode,
        manual_baseline_revision_id=request.change_report_baseline_revision_id,
    )
    if not baseline_revision_id:
        return

    base_row = db.get_version_by_id(str(baseline_revision_id), tenant_id)
    if not base_row or not base_row.get("published"):
        return

    rules = CompatibilityRules()
    base_spec = openapi_for_revision(base_row, tenant_slug, tenant_id)
    head_spec = openapi_for_revision(existing, tenant_slug, tenant_id)
    result = CompatibilityCheckEngine.run(base_spec, head_spec, rules)

    if result.overall != "breaking":
        return
    if bool(request.allow_breaking):
        return

    proj = db.get_project_by_id(project_id, tenant_id)
    proj_slug = str((proj or {}).get("slug") or project_id)
    from_label = str(base_row.get("version_id") or baseline_revision_id)
    to_label = str(existing.get("version_id") or version_record_id)
    report_hint = f"/{tenant_slug}/{proj_slug}/changes/{from_label}...{to_label}"

    raise HTTPException(
        status_code=409,
        detail=(
            "Breaking schema changes detected versus the published baseline "
            f"({from_label} → {to_label}). "
            "Review the change report or pass allowBreaking=true on the publish request. "
            f"Change report path: {report_hint}"
        ),
    )
