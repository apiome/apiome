"""Change report between two revisions of a catalog item — CDG-1.2 (#5953).

A connector sync that finds a remote API changed adds a new revision to the API's catalog item.
Like an auto-refresh (RAR-4.3, :mod:`app.repository_refresh_change_report`), that new revision
should say *what* changed. The refresh path builds each side's OpenAPI from the designer tables,
which a catalog item does not have: a catalog revision holds only its captured source (a Kong
declarative file, a GraphQL SDL, ...). So this module rebuilds each revision's canonical model
from its captured source (the same parse + normalize the convert flow uses,
:func:`app.catalog_conversion.build_conversion_source`), projects both through the reference
OpenAPI emitter, and hands the pair to the shared change-report builder.

The shared builder diffs schemas, properties and documentation; it notes an added or removed
operation only as ``skipped``. A gateway configuration carries no schemas — its changes *are*
operations — so the report also carries the CTG-1.1 classified diff
(:func:`app.change_taxonomy.classify_openapi_changes`) under ``classifiedChanges``, counts it
in ``noChanges``, and appends its markdown changelog to the rendered body. A Kong route whose
path moved therefore reports a removed and an added path, with their severities.

A format whose contract the OpenAPI projection cannot show opts into its own classifier instead
(``grades_classified_diff``): an Arazzo revision's ``classifiedChanges`` are the Arazzo workflow
rules (COA-1.6, :mod:`app.arazzo_change_rules`) — a required input, a removed output or source
description — each with its rationale.

The report is stored on ``change_reports`` keyed by the new revision (one row per revision;
an existing row is kept unchanged) and audited as ``catalog.connector.change_report.generated``.

Best-effort, like every change-report hook: a revision whose source cannot be rebuilt, or any
other failure, is logged and audited as a ``failure`` and never fails the sync.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .database import db
from .revision_source import SOURCE_ROW_KEY, attach_revision_source, sourceless_format_metadata_sql

logger = logging.getLogger(__name__)

__all__ = [
    "CHANGE_REPORT_ACTION",
    "generate_catalog_revision_change_report",
    "openapi_for_catalog_revision",
]

#: Workflow-audit action for a catalog revision change report.
CHANGE_REPORT_ACTION = "catalog.connector.change_report.generated"


def _revision_row(tenant_id: str, project_id: str, version_id: str) -> Optional[Dict[str, Any]]:
    """The revision's label, source format and captured source, scoped to the tenant's item."""
    rows = db.execute_query(
        f"""
        SELECT v.id, v.version_id, v.source_format, v.protocol,
               {sourceless_format_metadata_sql("v")} AS format_metadata, v.created_at,
               p.metadata
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.id = %s::uuid AND v.project_id = %s::uuid AND p.tenant_id = %s::uuid
          AND v.deleted_at IS NULL
        """,
        (version_id, project_id, tenant_id),
    )
    if not rows:
        return None
    # The source text is read through the one helper (COA-5.4): the store, then legacy columns.
    return attach_revision_source(rows[0], tenant_id=tenant_id, version_id=version_id, db=db)


def openapi_for_catalog_revision(project_id: str, revision: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild a catalog revision's canonical model from its captured source and emit OpenAPI.

    Args:
        project_id: The catalog item id.
        revision: The revision row (``source_format``, ``format_metadata``, ``metadata``).

    Returns:
        The OpenAPI 3.1 document the reference emitter produces for the revision.

    Raises:
        app.catalog_conversion.ConversionError: When the revision has no captured source or it
            cannot be parsed.
    """
    from .openapi_emitter import OpenApiEmitter

    return OpenApiEmitter().emit(_canonical_for_catalog_revision(project_id, revision)).document


def _canonical_for_catalog_revision(project_id: str, revision: Dict[str, Any]) -> Any:
    """Rebuild a catalog revision's canonical model from its captured source.

    Args:
        project_id: The catalog item id.
        revision: The revision row (``source_format``, ``format_metadata``, ``metadata``).

    Returns:
        The revision's :class:`~app.canonical_model.CanonicalApi`.

    Raises:
        app.catalog_conversion.ConversionError: When the revision has no captured source or it
            cannot be parsed.
    """
    from .catalog_conversion import build_conversion_source

    item = {
        "id": project_id,
        "source_format": revision.get("source_format"),
        "protocol": revision.get("protocol"),
        "format_metadata": revision.get("format_metadata"),
        "metadata": revision.get("metadata"),
        SOURCE_ROW_KEY: revision.get(SOURCE_ROW_KEY),
    }
    return build_conversion_source(item).api


def _classify(
    baseline_api: Any, candidate_api: Any, baseline_openapi: Dict[str, Any], candidate_openapi: Dict[str, Any]
) -> Any:
    """The classified diff for the report: the format's own classifier when it opts in, else CTG-1.1.

    A format whose contract lives outside the OpenAPI projection (Arazzo workflows, COA-1.6) sets
    ``grades_classified_diff`` on its breaking-change classifier; its canonical grades are mapped
    onto CTG changes (with their rationale). Every other format keeps the OpenAPI taxonomy.

    Args:
        baseline_api: The baseline revision's canonical model.
        candidate_api: The new revision's canonical model.
        baseline_openapi: The baseline's emitted OpenAPI document.
        candidate_openapi: The new revision's emitted OpenAPI document.

    Returns:
        A :class:`~app.change_taxonomy.ClassifiedDiff`.
    """
    from .breaking_change import classify_models, get_breaking_change_classifier
    from .change_taxonomy import classify_openapi_changes, summarize_changes
    from .compatibility_modes import ctg_changes

    classifier = get_breaking_change_classifier(candidate_api.format)
    if classifier is not None and classifier.grades_classified_diff:
        return summarize_changes([change for change, _ in ctg_changes(classify_models(baseline_api, candidate_api))])
    return classify_openapi_changes(baseline_openapi, candidate_openapi)


def generate_catalog_revision_change_report(
    *,
    tenant_id: str,
    project_id: str,
    revision_version_id: str,
    parent_version_id: str,
    actor_id: Optional[str],
    action: str = CHANGE_REPORT_ACTION,
) -> Optional[Dict[str, Any]]:
    """Diff a catalog item's new revision against the one before it and store the report.

    Best-effort: never raises.

    Args:
        tenant_id: The owning tenant.
        project_id: The catalog item (a ``projects`` row with ``publishable = false``).
        revision_version_id: The new revision (``versions.id``) the report is keyed to.
        parent_version_id: The revision it supersedes, the diff baseline.
        actor_id: Who the audit row is attributed to.
        action: The workflow-audit action; a live refresh (MFI-31.2) passes its own so the audit
            says which flow added the revision.

    Returns:
        The stored ``change_reports`` row (the existing one when the revision already has a
        report), or ``None`` when generation failed.
    """
    try:
        return _generate(
            tenant_id=tenant_id,
            project_id=project_id,
            revision_version_id=revision_version_id,
            parent_version_id=parent_version_id,
            actor_id=actor_id,
            action=action,
        )
    except Exception as exc:  # noqa: BLE001 - a report problem must never fail the sync
        logger.warning(
            "catalog revision change report failed project_id=%s revision=%s error=%s",
            project_id,
            revision_version_id,
            exc,
        )
        try:
            db.insert_workflow_audit(
                tenant_id,
                project_id,
                revision_version_id,
                action,
                "failure",
                actor_id,
                {"error": str(exc)[:500], "parentVersionId": parent_version_id},
            )
        except Exception:  # noqa: BLE001 - the audit write is best-effort too
            logger.exception("could not audit the failed catalog revision change report")
        return None


def _generate(
    *,
    tenant_id: str,
    project_id: str,
    revision_version_id: str,
    parent_version_id: str,
    actor_id: Optional[str],
    action: str = CHANGE_REPORT_ACTION,
) -> Optional[Dict[str, Any]]:
    """:func:`generate_catalog_revision_change_report` without the safety net."""
    from .change_report_render import build_render_metadata, render_from_template_row
    from .changelog_generator import build_changelog, render_changelog_markdown
    from .openapi_change_report import build_change_report, change_report_change_counts, change_report_is_noop
    from .openapi_emitter import OpenApiEmitter
    from .publication_change_report import _resolve_template_row

    candidate = _revision_row(tenant_id, project_id, revision_version_id)
    baseline = _revision_row(tenant_id, project_id, parent_version_id)
    if candidate is None or baseline is None:
        raise LookupError("revision not found in the catalog item")

    baseline_api = _canonical_for_catalog_revision(project_id, baseline)
    candidate_api = _canonical_for_catalog_revision(project_id, candidate)
    baseline_openapi = OpenApiEmitter().emit(baseline_api).document
    candidate_openapi = OpenApiEmitter().emit(candidate_api).document
    change_model = build_change_report(baseline_openapi, candidate_openapi)
    classified = _classify(baseline_api, candidate_api, baseline_openapi, candidate_openapi)
    change_model["classifiedChanges"] = {
        "changes": [change.model_dump() for change in classified.changes],
        "counts": dict(classified.counts),
        "maxSeverity": classified.max_severity,
    }
    counts = change_report_change_counts(change_model)
    counts["operations"] = len(classified.changes)
    change_model["noChanges"] = change_report_is_noop(change_model) and not classified.changes
    from_label = str(baseline.get("version_id") or "—")
    to_label = str(candidate.get("version_id") or "—")

    project = db.get_project_by_id(project_id, tenant_id) or {}
    template_row = _resolve_template_row(tenant_id, project_id)
    created_at = candidate.get("created_at")
    metadata = build_render_metadata(
        product_name=str(project.get("name") or "API"),
        from_version_label=from_label,
        to_version_label=to_label,
        publish_timestamp=created_at.isoformat() if hasattr(created_at, "isoformat") else "—",
    )
    header, body, footnote = render_from_template_row(change_model, template_row, metadata=metadata)
    changelog = render_changelog_markdown(build_changelog(classified, from_version=from_label, to_version=to_label))
    body = f"{body.rstrip()}\n\n{changelog}" if body.strip() else changelog
    template_id = str(template_row["id"]) if template_row.get("id") else None

    stored = db.insert_change_report_if_absent(
        tenant_id,
        project_id,
        revision_version_id,
        baseline_revision_id=parent_version_id,
        change_model_json=change_model,
        rendered_body=body,
        header_snapshot=header,
        footnote_snapshot=footnote,
        template_version_id=template_id,
    )
    db.insert_workflow_audit(
        tenant_id,
        project_id,
        revision_version_id,
        action,
        "success",
        actor_id,
        {
            "revisionVersionId": revision_version_id,
            "parentVersionId": parent_version_id,
            "templateVersionId": template_id,
            "noChanges": change_model["noChanges"],
            "maxSeverity": classified.max_severity,
            "changeCounts": counts,
            "totalChanges": sum(counts.values()),
        },
    )
    return stored
