"""Per-refresh change report via the publication change-report pipeline (RAR-4.3, #3529).

A spec-faithful auto-refresh (RAR-4.1) creates a new, provenance-linked version
(RAR-4.2). Silently mutating a version gives the user no insight into *what* changed,
so this module reuses the publication change-report pipeline
(:mod:`publication_change_report`) to diff the prior (parent) version against the new
refresh version, persist the report against the new version, and record a refresh
audit entry — exactly the machinery that already runs on publish, pointed at the
refresh lineage instead.

Unlike publish, a refresh version is *not* published, so this path:

* uses the RAR-4.2 ``parent_version_id`` provenance as the diff baseline (rather than
  the latest published ancestor), and
* tolerates an unpublished candidate (the publish path early-returns on those).

Zero-change refreshes are still reported: the report row is written (so the version
always links to a report) and both the stored change model and the audit entry are
flagged ``noChanges`` so the UI can render the refresh as a no-op.

Like :func:`publication_change_report.generate_change_report_on_publish`, the public
entrypoint is best-effort: failures are logged and recorded in ``workflow_audit`` with
outcome ``failure`` rather than raised, so a report problem never fails the refresh.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .database import db
from .openapi_change_report import (
    change_report_change_counts,
    change_report_is_noop,
)
from .publication_change_report import (
    _resolve_template_row,
    build_publication_change_report_render,
)

logger = logging.getLogger(__name__)

# Workflow-audit action for a refresh change report, distinct from the publish action
# ``schema.change_report.generated`` so refresh history (RAR-5.3) can filter on it.
REFRESH_CHANGE_REPORT_ACTION = "schema.refresh.change_report.generated"


def generate_change_report_on_refresh(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    refresh_version_id: str,
    parent_version_id: Optional[str],
    actor_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Produce, persist, and audit a change report for one auto-refresh (RAR-4.3).

    Best-effort: never raises. On failure the error is logged and a ``failure`` row is
    appended to ``workflow_audit`` so the refresh itself is unaffected.

    Args:
        tenant_slug: The tenant slug used to resolve OpenAPI for each revision.
        tenant_id: The owning tenant id.
        project_id: The catalog project the refresh version belongs to.
        refresh_version_id: The new version created by the refresh (RAR-4.2); the
            change report is keyed to (and thus linked from) this version.
        parent_version_id: The prior version the refresh supersedes (RAR-4.2
            provenance), used as the diff baseline. ``None`` for the first revision on
            the lineage, in which case an initial-style report against the empty
            baseline is produced.
        actor_id: The actor to attribute the audit entry to (the refresh trigger), or
            ``None`` for system-initiated refreshes.

    Returns:
        The persisted ``change_reports`` row (existing row if one was already present
        for this version), or ``None`` if generation was skipped or failed.
    """
    try:
        return _generate_change_report_on_refresh_impl(
            tenant_slug=tenant_slug,
            tenant_id=tenant_id,
            project_id=project_id,
            refresh_version_id=refresh_version_id,
            parent_version_id=parent_version_id,
            actor_id=actor_id,
        )
    except Exception as e:
        logger.warning(
            "change report generation failed after refresh (version=%s): %s",
            refresh_version_id,
            e,
            exc_info=True,
        )
        db.insert_workflow_audit(
            tenant_id,
            project_id,
            refresh_version_id,
            REFRESH_CHANGE_REPORT_ACTION,
            "failure",
            actor_id,
            {"error": str(e), "phase": "unexpected"},
        )
        return None


def _normalize_baseline_revision_id(parent_version_id: Optional[str]) -> Optional[str]:
    """Return a stripped non-empty baseline id, or ``None`` for blank/missing values."""
    if parent_version_id is None:
        return None
    text = str(parent_version_id).strip()
    return text or None


def _generate_change_report_on_refresh_impl(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    refresh_version_id: str,
    parent_version_id: Optional[str],
    actor_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    version = db.get_version_by_id(refresh_version_id, tenant_id)
    if not version:
        logger.warning(
            "refresh version %s not found; skipping change report", refresh_version_id
        )
        return None
    if str(version.get("project_id")) != str(project_id):
        logger.warning(
            "refresh version %s is not in project %s; skipping change report",
            refresh_version_id,
            project_id,
        )
        return None

    baseline_revision_id = _normalize_baseline_revision_id(parent_version_id)

    (
        change_model,
        header,
        body,
        footnote,
        stored_baseline_id,
        _requested_ghost,
        baseline_row_missing,
        _from_label,
    ) = build_publication_change_report_render(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        project_id=project_id,
        candidate_version=version,
        baseline_revision_id=baseline_revision_id,
    )

    counts = change_report_change_counts(change_model)
    is_noop = change_report_is_noop(change_model)
    # Flag the stored model so change-report rendering can show "no changes" without
    # recomputing the diff (mirrors how the publish path flags ``initialPublication``).
    change_model["noChanges"] = is_noop

    template_row = _resolve_template_row(tenant_id, project_id)
    tpl_id = str(template_row["id"]) if template_row.get("id") else None

    stored = db.insert_change_report_if_absent(
        tenant_id,
        project_id,
        refresh_version_id,
        baseline_revision_id=stored_baseline_id,
        change_model_json=change_model,
        rendered_body=body,
        header_snapshot=header,
        footnote_snapshot=footnote,
        template_version_id=tpl_id,
    )

    audit_detail: Dict[str, Any] = {
        "refreshVersionId": refresh_version_id,
        "baselineRevisionId": stored_baseline_id,
        "parentVersionId": baseline_revision_id,
        "templateVersionId": tpl_id,
        "noChanges": is_noop,
        "changeCounts": counts,
        "totalChanges": sum(counts.values()),
        "initialRefresh": baseline_revision_id is None,
    }
    if baseline_row_missing and baseline_revision_id is not None:
        audit_detail["baselineLookupMissing"] = True

    db.insert_workflow_audit(
        tenant_id,
        project_id,
        refresh_version_id,
        REFRESH_CHANGE_REPORT_ACTION,
        "success",
        actor_id,
        audit_detail,
    )

    return stored
