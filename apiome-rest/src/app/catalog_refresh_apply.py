"""Catalog item refresh → import pipeline — MFI-31.2 (#4399).

A live-refresh check (:mod:`app.catalog_refresh`, MFI-31.1) that succeeds hands its discovery to
:func:`apply_refresh_to_catalog`, registered here as the refresh apply hook. The hook makes a sweep
hit behave exactly like a manual re-import of the discovered document, with no pipeline of its own:

1. **Compare.** The item's current version (its newest live revision) is rebuilt from its stored
   source with the same parse + normalize the convert flow uses
   (:func:`app.catalog_conversion.build_conversion_source`). :func:`app.versioning.decide_version`
   (MFI-3.4) compares the discovered model with it: equal → ``SKIP`` (no version), different →
   ``CREATE`` with a minted date/time label such as ``2026-10-27T14:03Z``.
2. **Import.** On ``CREATE`` the discovered document goes through the in-process import pipeline
   (:func:`app.import_source_pipeline.run_adapter_import_job`) onto the existing item
   (``existing_project_id``), so normalize, fingerprint, lint score capture (MFI-4.2), payload
   analysis, search rows and the verbatim source are stored just as a manual import stores them.
   The payload's ``refresh_source`` puts the pipeline in refresh mode: the result always lands in
   the catalog, and the revision's provenance records ``inputKind: discovery``, the endpoint, the
   adapter and ``refreshTrigger`` (``sweep`` or ``manual``).
3. **Diff.** The new revision gets the change report a connector sync writes
   (:func:`app.catalog_revision_change_report.generate_catalog_revision_change_report`): the
   diff and the breaking-change classification against the version it supersedes, rebuilt from
   both revisions' stored sources. Since the report reads only those sources, a refresh and a
   manual re-import of the same document get the same report. It is best-effort, like every
   change report: a report failure never undoes the version.
4. **Drift (MFI-31.3).** The change is classified safe / dangerous / breaking and recorded as a
   drift event (:mod:`app.catalog_drift_service`): the catalog badge and banner show it, and the
   tenant's drift alert settings decide whether it is announced now, in the daily digest, or not.
5. **Retention (MFI-31.5).** Refresh-created versions beyond the setting's ``keep_versions`` are
   pruned (:mod:`app.version_retention`), after the drift is recorded so a breaking version is
   already protected.

An item that was deleted, or is not a catalog item, fails the check (``item-unavailable``) and
nothing is written. A failure anywhere before the pipeline commits fails the check the same way, so
a failed check never leaves a half-written version.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from .catalog_refresh import (
    TRIGGER_MANUAL,
    ApplyOutcome,
    DiscoveryResult,
    RefreshSettingsError,
    register_refresh_apply,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_CHANGE_REPORT",
    "CODE_ITEM_UNAVAILABLE",
    "INPUT_KIND_DISCOVERY",
    "apply_refresh_to_catalog",
    "previous_version",
    "refresh_provenance",
]

#: Workflow-audit action for the change report of a refresh-created revision.
AUDIT_CHANGE_REPORT = "catalog.refresh.change_report.generated"

#: The item can no longer take a refresh version (deleted, or not a catalog item).
CODE_ITEM_UNAVAILABLE = "item-unavailable"

#: The provenance input kind of a refresh-created revision; the catalog UI shows it as
#: "Live discovery" (``CATALOG_SOURCE_KIND_META.discovery``).
INPUT_KIND_DISCOVERY = "discovery"


def refresh_provenance(row: Mapping[str, Any], trigger: str) -> Dict[str, Any]:
    """The provenance a refresh-created revision records in its ``format_metadata``.

    Args:
        row: The ``catalog_item_refresh`` row the check ran for.
        trigger: ``sweep`` or ``manual``.

    Returns:
        The keys merged over the pipeline's own provenance: the input kind, the endpoint as the
        source label, the adapter and the trigger. Never the credential.
    """
    return {
        "inputKind": INPUT_KIND_DISCOVERY,
        "sourceLabel": str(row["endpoint"]),
        "refreshAdapter": str(row["adapter_key"]),
        "refreshTrigger": trigger,
    }


def _catalog_item(db: Any, project_id: str, tenant_id: str) -> Dict[str, Any]:
    """The live catalog item a refresh writes to.

    Raises:
        RefreshSettingsError: ``item-unavailable`` when the item is gone or is a publishable
            Project. A converted item is still a catalog item and takes new versions, as it does
            from a connector sync.
    """
    rows = db.execute_query(
        """
        SELECT p.id, p.name, p.slug, p.publishable, p.deleted_at
        FROM apiome.projects p
        WHERE p.id = %s::uuid AND p.tenant_id = %s::uuid
        """,
        (project_id, tenant_id),
    )
    item = dict(rows[0]) if rows else None
    if item is None or item.get("deleted_at") is not None:
        raise RefreshSettingsError(CODE_ITEM_UNAVAILABLE, "The catalog item no longer exists.")
    if item.get("publishable") is not False:
        raise RefreshSettingsError(CODE_ITEM_UNAVAILABLE, "Only a catalog item can be refreshed.")
    return item


def _revisions(db: Any, project_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    """The item's live revisions, newest first, with what a rebuild needs."""
    rows = db.execute_query(
        """
        SELECT v.id, v.version_id, v.source_format, v.protocol, v.format_metadata, p.metadata
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.project_id = %s::uuid AND p.tenant_id = %s::uuid AND v.deleted_at IS NULL
        ORDER BY v.created_at DESC, v.id DESC
        """,
        (project_id, tenant_id),
    )
    return [dict(row) for row in rows]


def previous_version(project_id: str, revision: Mapping[str, Any]) -> Any:
    """The item's current version as the :func:`~app.versioning.decide_version` baseline.

    The revision's canonical model is rebuilt from its stored source with the convert flow's parse +
    normalize, and fingerprinted with the semantic fingerprint ``decide_version`` compares.

    Args:
        project_id: The catalog item id.
        revision: The newest revision row (``id``, ``version_id``, ``source_format``,
            ``format_metadata``, ``metadata``).

    Returns:
        A :class:`~app.versioning.PreviousVersion` carrying the model, or ``None`` when the
        revision has no source that can be rebuilt (the check then records the live source as a
        new version, which gives later checks a baseline).
    """
    from .catalog_conversion import build_conversion_source
    from .fingerprint import fingerprint
    from .versioning import PreviousVersion

    item = {
        "id": project_id,
        "source_format": revision.get("source_format"),
        "protocol": revision.get("protocol"),
        "format_metadata": revision.get("format_metadata"),
        "metadata": revision.get("metadata"),
    }
    try:
        model = build_conversion_source(item).api
    except Exception as exc:  # noqa: BLE001 - an unreadable baseline is "no baseline", not a failure
        _logger.info(
            "catalog refresh: revision %s has no rebuildable source (%s); recording a new version",
            revision.get("id"),
            exc,
        )
        return None
    return PreviousVersion(
        version_tag=str(revision.get("version_id") or ""),
        fingerprint=fingerprint(model).fingerprint,
        model=model,
    )


def _import_payload(
    row: Mapping[str, Any],
    item: Mapping[str, Any],
    result: DiscoveryResult,
    *,
    version_label: str,
    trigger: str,
    actor_id: Optional[str],
) -> Dict[str, Any]:
    """The import-pipeline payload that adds the discovered document to the item."""
    project_id = str(row["project_id"])
    return {
        "tenant_id": str(row["tenant_id"]),
        "user_id": actor_id,
        "filename": result.filename,
        "document_base64": base64.standard_b64encode(result.document or b"").decode("ascii"),
        "rest_job_id": f"refresh-{project_id}",
        "metadata": {
            "source_kind": str(row["adapter_key"]),
            "project": {"name": item.get("name"), "slug": item.get("slug")},
            "version": {"version_id": version_label},
            "options": {},
            "existing_project_id": project_id,
        },
        "refresh_source": refresh_provenance(row, trigger),
    }


def apply_refresh_to_catalog(
    db: Any,
    row: Mapping[str, Any],
    result: DiscoveryResult,
    changed: bool,
    *,
    trigger: str = TRIGGER_MANUAL,
    actor_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ApplyOutcome:
    """Add a version to the catalog item when the live source differs from its current version.

    The registered refresh apply hook (see the module docstring). Blocking — the check runner calls
    it in a worker thread, and the pipeline runs on a private event loop.

    Args:
        db: Database handle for the reads.
        row: The ``catalog_item_refresh`` row (``project_id``, ``tenant_id``, ``adapter_key``,
            ``endpoint``, ``created_by`` / ``updated_by``).
        result: The discovery, carrying the pipeline model and the discovered document.
        changed: Whether the fingerprint differs from the last check's (unused: the decision is
            made against the item's current version, not the last check).
        trigger: ``sweep`` or ``manual``, recorded on the new revision's provenance.
        actor_id: The user the version is attributed to; defaults to whoever last saved the
            refresh setting.
        now: The time the version label is minted from (tests pin it); defaults to now.

    Returns:
        :class:`~app.catalog_refresh.ApplyOutcome` — ``changed`` and the created version, if any.

    Raises:
        RefreshSettingsError: ``item-unavailable`` (see :func:`_catalog_item`).
        ValueError: When the discovery carries no document to import.
        RuntimeError: When the import pipeline fails.
    """
    from .import_source import get_import_source
    from .import_source_pipeline import run_adapter_import_job
    from .versioning import decide_version

    del changed  # the baseline is the item's current version, read below
    if result.document is None or result.model is None:
        raise ValueError("The discovery produced no document to import.")
    project_id = str(row["project_id"])
    tenant_id = str(row["tenant_id"])
    item = _catalog_item(db, project_id, tenant_id)
    revisions = _revisions(db, project_id, tenant_id)
    previous = previous_version(project_id, revisions[0]) if revisions else None

    decision = decide_version(
        result.model,
        previous=previous,
        when=now or datetime.now(timezone.utc),
        existing_tags=[str(r.get("version_id")) for r in revisions if r.get("version_id")],
    )
    if not decision.created:
        return ApplyOutcome(changed=False)

    actor = actor_id or row.get("updated_by") or row.get("created_by")
    actor = str(actor) if actor else None
    payload = _import_payload(
        row, item, result, version_label=str(decision.version_tag), trigger=trigger, actor_id=actor
    )
    final = asyncio.run(run_adapter_import_job(get_import_source(str(row["adapter_key"])), payload))
    if final.state != "completed" or final.result is None or not final.result.version_record_id:
        reason = final.error.message if final.error is not None else f"the import ended {final.state}"
        raise RuntimeError(f"The changed source could not be imported: {reason}")
    version_id = str(final.result.version_record_id)

    if revisions:
        from .catalog_revision_change_report import generate_catalog_revision_change_report

        generate_catalog_revision_change_report(
            tenant_id=tenant_id,
            project_id=project_id,
            revision_version_id=version_id,
            parent_version_id=str(revisions[0]["id"]),
            actor_id=actor,
            action=AUDIT_CHANGE_REPORT,
        )
    if previous is not None and previous.model is not None:
        # MFI-31.3: classify the drift, badge it and announce it per the tenant's settings.
        from .catalog_drift_service import record_refresh_drift

        record_refresh_drift(
            db,
            item={**item, "tenant_id": tenant_id},
            previous_model=previous.model,
            new_model=result.model,
            version_id=version_id,
            version_label=str(final.result.version_id),
            parent_version_id=str(revisions[0]["id"]),
            parent_version_label=previous.version_tag or None,
            trigger=trigger,
            actor_id=actor,
        )
    # MFI-31.5: keep the newest `keep_versions` refresh-created versions (best-effort).
    from .version_retention import DEFAULT_KEEP_VERSIONS, prune_refresh_versions_safely

    prune_refresh_versions_safely(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        keep=int(row.get("keep_versions") or DEFAULT_KEEP_VERSIONS),
        actor_id=actor,
    )
    _logger.info(
        "catalog refresh created version project_id=%s version=%s trigger=%s",
        project_id,
        decision.version_tag,
        trigger,
    )
    return ApplyOutcome(changed=True, version_id=version_id, version_label=final.result.version_id)


register_refresh_apply(apply_refresh_to_catalog)
