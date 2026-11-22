"""Import a transformed OpenAPI document as a new version of an existing project — shared helper.

Two features turn a version's OpenAPI document into a new version of the same project or catalog
item: the spec upgrade assistant (COA-2.6, #7049) and the overlay manager's **Apply as version**
(COA-2.7, #7050). Both go through the same steps, kept here so they cannot drift:

1. pick the new version's label (the caller's, or a minted date/time label) and refuse a taken one;
2. run the tenant's import quality gate over the bytes, as an upload would (IXH-2.3);
3. import the bytes through the OpenAPI import pipeline
   (:func:`app.import_source_pipeline.run_adapter_import_job`), replaying the import options the
   source version's upload recorded, so a catalog item's next re-upload uses the same importer.

The pipeline and the gate are imported inside the functions so tests can patch them on their own
modules.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from fastapi import HTTPException

from .database import db

__all__ = [
    "choose_version_label",
    "document_bytes",
    "enforce_openapi_quality_gate",
    "existing_version_labels",
    "import_openapi_as_version",
]


def _refuse(status: int, code: str, message: str) -> HTTPException:
    """A structured ``{code, message}`` refusal."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def existing_version_labels(project_id: str, tenant_id: str) -> List[str]:
    """Every version label the project already uses.

    Args:
        project_id: The project or catalog item.
        tenant_id: The caller's tenant.

    Returns:
        The labels (``versions.version_id``), in the order the database lists them.
    """
    return [
        str(row.get("version_id"))
        for row in db.get_versions_for_project(project_id, tenant_id)
        if row.get("version_id")
    ]


def choose_version_label(requested: Optional[str], existing: List[str]) -> str:
    """The new version's label: the requested one, or a minted date/time label.

    Args:
        requested: The caller's label; blank or ``None`` mints one.
        existing: The labels the project already uses.

    Returns:
        The label to import under.

    Raises:
        HTTPException: 409 ``version-exists`` when the requested label is taken.
    """
    from .versioning import mint_version_tag

    label = (requested or "").strip() or mint_version_tag(datetime.now(timezone.utc), existing)
    if label in existing:
        raise _refuse(409, "version-exists", f"Version {label!r} already exists; choose another label.")
    return label


def document_bytes(document: Mapping[str, Any]) -> bytes:
    """The document as the indented JSON bytes the import receives."""
    return json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8")


async def enforce_openapi_quality_gate(
    *, tenant_id: str, tenant_slug: str, user_id: str, project_id: str, label: str, raw: bytes, filename: str
) -> None:
    """Run the tenant's import quality gate over an OpenAPI document, as an upload would (IXH-2.3).

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug.
        user_id: The acting user.
        project_id: The project the version is added to.
        label: The new version's label.
        raw: The document bytes.
        filename: The file name the gate reports.

    Raises:
        HTTPException: 409 ``QUALITY_POLICY_BLOCKED`` when the policy refuses the document.
    """
    from .models import SpecImportOptions, SpecImportProjectTarget, SpecImportStartMetadata, SpecImportVersionTarget
    from .spec_import_routes import _enforce_quality_gate as enforce

    metadata = SpecImportStartMetadata(
        source_kind="openapi",
        project=SpecImportProjectTarget(project_id=project_id),
        version=SpecImportVersionTarget(version_id=label),
        options=SpecImportOptions(input_kind="file"),
    )
    await enforce(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=user_id,
        raw=raw,
        metadata=metadata,
        filename=filename,
        content_type="application/json",
    )


def import_openapi_as_version(
    *,
    tenant_id: str,
    actor_id: Optional[str],
    project_id: str,
    format_metadata: Optional[Mapping[str, Any]],
    fallback_slug: Optional[str],
    label: str,
    raw: bytes,
    filename_suffix: str,
    description: str,
    rest_job_id: str,
    failure_code: str,
    failure_message: str,
) -> str:
    """Import an OpenAPI document onto a project as a new version; return its id (blocking).

    Args:
        tenant_id: The caller's tenant.
        actor_id: The acting user.
        project_id: The project or catalog item to add the version to.
        format_metadata: The source version's ``format_metadata`` (its recorded upload options
            are replayed when they were an OpenAPI import).
        fallback_slug: The slug to use when the project row has none.
        label: The new version's label.
        raw: The document bytes (:func:`document_bytes`).
        filename_suffix: Appended to the project slug for the import's file name (``-overlaid.json``).
        description: The new version's description.
        rest_job_id: The job id the pipeline records.
        failure_code: The refusal code when the import does not complete.
        failure_message: The refusal's opening words; the pipeline's reason follows a colon.

    Returns:
        The new version's id (``versions.id``).

    Raises:
        HTTPException: 422 ``failure_code`` when the pipeline does not complete.
    """
    from .catalog_upload_reconcile import stored_upload_spec
    from .import_source import get_import_source
    from .import_source_pipeline import run_adapter_import_job

    project = db.get_project_core(project_id, tenant_id) or {}
    spec = stored_upload_spec(dict(format_metadata) if isinstance(format_metadata, Mapping) else None)
    options: Dict[str, Any] = dict(spec["options"]) if spec and spec.get("sourceKind") == "openapi" else {}
    slug = project.get("slug") or fallback_slug or "spec"
    payload = {
        "tenant_id": tenant_id,
        "user_id": actor_id,
        "filename": f"{slug}{filename_suffix}",
        "document_base64": base64.standard_b64encode(raw).decode("ascii"),
        "rest_job_id": rest_job_id,
        "metadata": {
            "source_kind": "openapi",
            "project": {"name": project.get("name"), "slug": slug},
            "version": {"version_id": label, "description": description},
            "options": {**options, "input_kind": "file"},
            "existing_project_id": project_id,
        },
    }
    adapter = get_import_source("openapi")
    final = asyncio.run(run_adapter_import_job(adapter, payload))
    if final.state != "completed" or final.result is None or not final.result.version_record_id:
        reason = final.error.message if final.error is not None else f"the import ended {final.state}"
        raise _refuse(422, failure_code, f"{failure_message}: {reason}")
    return str(final.result.version_record_id)
