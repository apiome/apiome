"""OpenAPI spec upgrade assistant — REST routes (COA-2.6, #7049).

POST /v1/openapi-upgrade/{tenant_slug}/plan
POST /v1/openapi-upgrade/{tenant_slug}/apply

**Plan** reviews an upgrade without writing anything. The source is either a document in the
request (``document_text``, JSON or YAML — the CLI's ``apiome upgrade FILE``) or a project /
catalog item version (``project_id`` + optional ``version``, default the latest). A version's
source is the document its import captured; a decomposed OpenAPI import that kept none is
rebuilt from the stored model (which is 3.1, so its only upgrade is to 3.2). The answer is the
:class:`~app.openapi_upgrade.UpgradePlan`: every change with its rule and pointer, a per-rule
count, the upgraded document, and a ``plan_digest``.

**Apply** re-plans the same source and target, refuses a ``plan_digest`` that no longer matches
(the source changed since the review: 409 ``plan-stale``), and imports the upgraded document as
a **new version** of the same project or catalog item through the import pipeline
(:func:`app.import_source_pipeline.run_adapter_import_job`, as a catalog re-upload does). The
new version gets ``version_label`` or a date/time label; an existing label is refused (409
``version-exists``). Every apply writes a workflow-audit row.

Permissions: plan from a version needs ``imports:view`` (it reads the captured source) and plan
from pasted text needs ``projects:view``; apply needs ``imports:create`` and ``projects:edit``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import validate_authentication
from .database import db
from .export_source import ExportSourceError, _is_decomposed_openapi, _reconstructed_openapi_item, resolve_revision_id
from .import_ingestion import IngestionError, parse_document
from .intake_resource_guard import IntakeLimitError
from .openapi_upgrade import UpgradeError, UpgradePlan, plan_upgrade
from .permissions import Action, Resource, enforce_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/openapi-upgrade", tags=["openapi-upgrade"])

#: Workflow-audit action written by every apply.
AUDIT_APPLIED = "openapi.upgrade.applied"

#: Where a plan's source document came from.
SourceOrigin = Literal["request", "captured", "rebuilt"]

_UPGRADE_ERROR_STATUS = {
    "unknown-target": 422,
    "not-openapi": 422,
    "unsupported-version": 422,
    "target-older": 422,
}


class UpgradePlanRequest(BaseModel):
    """What to plan: a pasted document, or a project / catalog item version, and the target."""

    model_config = ConfigDict(extra="forbid")

    target: Literal["3.0", "3.1", "3.2"] = Field(description="Target OpenAPI version family.")
    document_text: Optional[str] = Field(
        default=None,
        description="The document itself (JSON or YAML). Set this or project_id, not both.",
    )
    project_id: Optional[str] = Field(
        default=None, description="Project or catalog item whose version is upgraded. Set this or document_text."
    )
    version: Optional[str] = Field(
        default=None,
        description="The version to upgrade: a version id (UUID) or label (1.0.0). Default: the latest.",
    )
    include_document: bool = Field(default=True, description="Return the upgraded document with the plan.")

    @model_validator(mode="after")
    def _one_source(self) -> "UpgradePlanRequest":
        """Exactly one source: pasted text or a project."""
        if bool(self.document_text) == bool(self.project_id):
            raise ValueError("set exactly one of document_text or project_id")
        if self.version and not self.project_id:
            raise ValueError("version needs project_id")
        return self


class UpgradeApplyRequest(BaseModel):
    """Apply a reviewed plan to a project / catalog item version as a new version."""

    model_config = ConfigDict(extra="forbid")

    target: Literal["3.0", "3.1", "3.2"] = Field(description="Target OpenAPI version family (as planned).")
    project_id: str = Field(description="Project or catalog item to add the upgraded version to.")
    version: Optional[str] = Field(default=None, description="The version that was planned (default: the latest).")
    plan_digest: str = Field(description="The plan_digest of the reviewed plan; a mismatch is refused (409).")
    version_label: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Label of the new version (for example 2.0.0). Default: a date/time label.",
    )


class UpgradeApplyResponse(BaseModel):
    """The version an apply created."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    version_record_id: str = Field(description="The new version's id (versions.id).")
    version_label: str
    source_version_record_id: str = Field(description="The version that was upgraded.")
    target_version: str = Field(description="The OpenAPI version the new version declares.")
    change_count: int


# ---------------------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------------------


def _refuse(status: int, code: str, message: str) -> HTTPException:
    """A structured ``{code, message}`` refusal."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _parse_text(text: str, label: str) -> Dict[str, Any]:
    """Parse a JSON / YAML document, mapping parse and intake-limit failures to 422 / 413."""
    try:
        return parse_document(text, source_label=label)
    except IntakeLimitError as exc:
        raise _refuse(413, "too-large", str(exc)) from exc
    except IngestionError as exc:
        raise _refuse(422, "unparseable", str(exc)) from exc


def load_version_source(
    tenant_id: str, project_id: str, version: Optional[str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load the OpenAPI document of a project / catalog item version.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project or catalog item.
        version: A version UUID or label; ``None`` for the latest.

    Returns:
        ``(document, meta)`` — ``meta`` carries ``version_record_id``, ``version_label``,
        ``project_slug``, ``origin`` (``captured`` / ``rebuilt``) and ``format_metadata``.

    Raises:
        HTTPException: 404 for an unknown project / version; 409 ``unsupported-source`` (an
            archive or fileset), ``source-withheld`` or ``no-source``; 422 ``unparseable``.
    """
    try:
        revision_id = resolve_revision_id(tenant_id, project_id, version)
    except ExportSourceError as exc:
        raise _refuse(exc.status_code, "not-found", str(exc)) from exc
    row = db.get_version_source_projection(revision_id, tenant_id)
    if not row or str(row.get("id")) != str(project_id):
        raise _refuse(404, "not-found", f"Version {version or revision_id!r} was not found for {project_id!r}.")
    fmd = row.get("format_metadata") if isinstance(row.get("format_metadata"), dict) else {}
    meta = {
        "version_record_id": str(revision_id),
        "version_label": row.get("version_label"),
        "project_slug": row.get("project_slug"),
        "format_metadata": fmd,
    }
    if fmd.get("sourceWithheld"):
        raise _refuse(409, "source-withheld", "This version's source was withheld at import (secrets were detected).")
    if fmd.get("sourceEncoding") == "base64" or fmd.get("intakeKind") in ("archive", "fileset"):
        raise _refuse(
            409,
            "unsupported-source",
            "This version was imported from several files. Export it as one bundled document and upgrade that file.",
        )
    text = fmd.get("sourceContent")
    if isinstance(text, str) and text.strip():
        meta["origin"] = "captured"
        return _parse_text(text, str(row.get("version_label") or project_id)), meta
    if _is_decomposed_openapi(row.get("source_format")):
        rebuilt = _reconstructed_openapi_item(row, tenant_id, str(revision_id))
        if rebuilt is not None:
            meta["origin"] = "rebuilt"
            return _parse_text(rebuilt["format_metadata"]["sourceContent"], str(project_id)), meta
    raise _refuse(409, "no-source", "This version has no OpenAPI source to upgrade.")


def _plan(document: Dict[str, Any], target: str) -> UpgradePlan:
    """Plan, mapping :class:`UpgradeError` to its HTTP refusal."""
    try:
        return plan_upgrade(document, target)
    except UpgradeError as exc:
        raise _refuse(_UPGRADE_ERROR_STATUS.get(exc.code, 422), exc.code, str(exc)) from exc


# ---------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------


@router.post("/{tenant_slug}/plan", summary="Plan an OpenAPI version upgrade (no write)")
async def plan_openapi_upgrade(
    tenant_slug: str,
    body: UpgradePlanRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Plan the upgrade of a document or a version to ``target``; nothing is written.

    Returns:
        The plan (:meth:`UpgradePlan.as_dict`) plus ``origin`` and, for a version source,
        ``project_id`` / ``version_record_id`` / ``version_label``.

    Raises:
        HTTPException: 404 unknown project / version; 409 when the version has no single-file
            source; 413 / 422 for a document too large, unparseable, not OpenAPI, of an
            unsupported version, or newer than ``target``.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    meta: Dict[str, Any] = {}
    if body.project_id:
        enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"project:{body.project_id}:upgrade")
        document, meta = await asyncio.to_thread(load_version_source, tenant_id, body.project_id, body.version)
        origin: str = meta["origin"]
    else:
        enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="openapi-upgrade:document")
        document = _parse_text(body.document_text or "", "document")
        origin = "request"
    plan = await asyncio.to_thread(_plan, document, body.target)
    out = plan.as_dict(include_document=body.include_document)
    out["origin"] = origin
    if body.project_id:
        out.update(
            project_id=body.project_id,
            version_record_id=meta["version_record_id"],
            version_label=meta.get("version_label"),
        )
    return out


def _existing_labels(project_id: str, tenant_id: str) -> List[str]:
    """Every version label the project already uses."""
    return [
        str(row.get("version_id"))
        for row in db.get_versions_for_project(project_id, tenant_id)
        if row.get("version_id")
    ]


def upgraded_bytes(plan: UpgradePlan) -> bytes:
    """The upgraded document as the JSON bytes the import receives."""
    import json

    return json.dumps(plan.document, indent=2, ensure_ascii=False).encode("utf-8")


async def _enforce_quality_gate(
    *, tenant_id: str, tenant_slug: str, user_id: str, project_id: str, label: str, raw: bytes
) -> None:
    """Run the tenant's import quality gate over the upgraded document, as an upload would (IXH-2.3).

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
        filename="openapi-upgrade.json",
        content_type="application/json",
    )


def _import_upgraded(
    *,
    tenant_id: str,
    actor_id: Optional[str],
    project_id: str,
    meta: Dict[str, Any],
    plan: UpgradePlan,
    label: str,
    raw: bytes,
) -> str:
    """Import the upgraded document onto the project as a new version; return its id (blocking).

    The import keeps the options the source version's upload recorded (when it recorded any), so a
    catalog item's next re-upload replays the same importer.

    Raises:
        HTTPException: 422 ``upgrade-import-failed`` when the pipeline does not complete.
    """
    from .catalog_upload_reconcile import stored_upload_spec
    from .import_source import get_import_source
    from .import_source_pipeline import run_adapter_import_job

    project = db.get_project_by_id(project_id, tenant_id) or {}
    spec = stored_upload_spec(meta.get("format_metadata"))
    options = dict(spec["options"]) if spec and spec.get("sourceKind") == "openapi" else {}
    slug = project.get("slug") or meta.get("project_slug") or "spec"
    payload = {
        "tenant_id": tenant_id,
        "user_id": actor_id,
        "filename": f"{slug}-openapi-{plan.target_version}.json",
        "document_base64": base64.standard_b64encode(raw).decode("ascii"),
        "rest_job_id": f"openapi-upgrade-{project_id}",
        "metadata": {
            "source_kind": "openapi",
            "project": {"name": project.get("name"), "slug": slug},
            "version": {
                "version_id": label,
                "description": f"Upgraded from OpenAPI {plan.source_version} to {plan.target_version}.",
            },
            "options": {**options, "input_kind": "file"},
            "existing_project_id": project_id,
        },
    }
    adapter = get_import_source("openapi")
    final = asyncio.run(run_adapter_import_job(adapter, payload))
    if final.state != "completed" or final.result is None or not final.result.version_record_id:
        reason = final.error.message if final.error is not None else f"the import ended {final.state}"
        raise _refuse(422, "upgrade-import-failed", f"The upgraded document could not be imported: {reason}")
    return str(final.result.version_record_id)


@router.post("/{tenant_slug}/apply", response_model=UpgradeApplyResponse, summary="Apply a reviewed OpenAPI upgrade")
async def apply_openapi_upgrade(
    tenant_slug: str,
    body: UpgradeApplyRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UpgradeApplyResponse:
    """Apply a reviewed plan: the upgraded document becomes a new version of the same project.

    Raises:
        HTTPException: 404 unknown project / version; 409 ``plan-stale`` (the source plans
            differently now), ``nothing-to-upgrade`` (already at ``target``), ``version-exists``,
            or a source refusal (see :func:`load_version_source`); 422 when the plan or the
            import fails; 409 ``QUALITY_POLICY_BLOCKED`` when the tenant's import policy
            refuses the upgraded document.
    """
    tenant_id = str(auth_data["tenant_id"])
    target = f"project:{body.project_id}:upgrade"
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE, target=target)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=target)
    document, meta = await asyncio.to_thread(load_version_source, tenant_id, body.project_id, body.version)
    plan = await asyncio.to_thread(_plan, document, body.target)
    if plan.already_current:
        raise _refuse(409, "nothing-to-upgrade", f"This version is already OpenAPI {plan.source_version}.")
    if plan.plan_digest != body.plan_digest:
        raise _refuse(
            409, "plan-stale", "The version changed since the plan was made. Review the new plan and apply it."
        )

    from .versioning import mint_version_tag

    existing = await asyncio.to_thread(_existing_labels, body.project_id, tenant_id)
    label = (body.version_label or "").strip() or mint_version_tag(datetime.now(timezone.utc), existing)
    if label in existing:
        raise _refuse(409, "version-exists", f"Version {label!r} already exists; choose another label.")
    raw = upgraded_bytes(plan)
    await _enforce_quality_gate(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=str(actor_id or ""),
        project_id=body.project_id,
        label=label,
        raw=raw,
    )
    version_record_id = await asyncio.to_thread(
        _import_upgraded,
        tenant_id=tenant_id,
        actor_id=str(actor_id) if actor_id else None,
        project_id=body.project_id,
        meta=meta,
        plan=plan,
        label=label,
        raw=raw,
    )
    detail = {
        "projectId": body.project_id,
        "sourceVersionId": meta["version_record_id"],
        "versionId": version_record_id,
        "versionLabel": label,
        "from": plan.source_version,
        "to": plan.target_version,
        "changeCount": len(plan.changes),
    }
    try:
        db.insert_workflow_audit(tenant_id, None, None, AUDIT_APPLIED, "success", actor_id, detail)
    except Exception:  # noqa: BLE001 — an audit failure never fails the request.
        logger.exception("openapi upgrade audit write failed project=%s", body.project_id)
    return UpgradeApplyResponse(
        project_id=body.project_id,
        version_record_id=version_record_id,
        version_label=label,
        source_version_record_id=meta["version_record_id"],
        target_version=plan.target_version,
        change_count=len(plan.changes),
    )
