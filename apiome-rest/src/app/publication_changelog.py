"""Generate and persist classified version changelogs after successful publish (CTG-3.1, #4475).

Runs as a FastAPI BackgroundTasks hook parallel to the Mustache change-report pipeline.
Failures never raise out of the public entrypoint: they upsert ``status='failed'`` and
record ``workflow_audit`` so publish itself always succeeds.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .change_taxonomy import classify_openapi_changes
from .changelog_generator import (
    CHANGELOG_SCHEMA_VERSION,
    build_changelog,
    render_changelog_json,
)
from .compatibility_engine import openapi_for_revision
from .database import db

logger = logging.getLogger(__name__)

_EMPTY_COUNTS = {
    "breaking": 0,
    "non-breaking": 0,
    "docs-only": 0,
    "unclassified": 0,
    "total": 0,
}


def initial_publication_changelog_json(
    *,
    to_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Small marker payload when there is no prior published baseline on the line."""
    return {
        "schemaVersion": CHANGELOG_SCHEMA_VERSION,
        "initialPublication": True,
        "fromVersion": None,
        "toVersion": to_version,
        "counts": dict(_EMPTY_COUNTS),
        "maxSeverity": None,
        "entries": [],
    }


def generate_version_changelog_on_publish(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    published_revision_id: str,
    actor_id: Optional[str],
) -> None:
    """
    Best-effort CTG-1.1 → CTG-1.3 persist after publish.

    Does not raise: failures are logged, upserted as ``status='failed'``, and
    recorded in ``workflow_audit`` with action ``version.changelog.classified``.
    """
    try:
        _generate_version_changelog_on_publish_impl(
            tenant_slug=tenant_slug,
            tenant_id=tenant_id,
            project_id=project_id,
            published_revision_id=published_revision_id,
            actor_id=actor_id,
        )
    except Exception as e:
        logger.warning(
            "version changelog classification failed after publish (revision=%s): %s",
            published_revision_id,
            e,
            exc_info=True,
        )
        try:
            db.upsert_version_changelog(
                tenant_id=tenant_id,
                project_id=project_id,
                published_revision_id=published_revision_id,
                baseline_revision_id=None,
                changelog_json=None,
                max_severity=None,
                status="failed",
                error=str(e),
            )
        except Exception:
            logger.warning(
                "failed to upsert failed version_changelog row (revision=%s)",
                published_revision_id,
                exc_info=True,
            )
        try:
            db.insert_workflow_audit(
                tenant_id,
                project_id,
                published_revision_id,
                "version.changelog.classified",
                "failure",
                actor_id,
                {"error": str(e), "phase": "unexpected"},
            )
        except Exception:
            logger.warning(
                "failed to audit version changelog failure (revision=%s)",
                published_revision_id,
                exc_info=True,
            )


def _generate_version_changelog_on_publish_impl(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    published_revision_id: str,
    actor_id: Optional[str],
) -> None:
    version = db.get_version_by_id(published_revision_id, tenant_id)
    if not version or not version.get("published"):
        return

    to_label = str(version.get("version_id") or "—")
    baseline_revision_id = db.get_prior_published_baseline_revision_id(
        project_id, tenant_id, published_revision_id
    )

    if not baseline_revision_id:
        marker = initial_publication_changelog_json(to_version=to_label)
        db.upsert_version_changelog(
            tenant_id=tenant_id,
            project_id=project_id,
            published_revision_id=published_revision_id,
            baseline_revision_id=None,
            changelog_json=marker,
            max_severity=None,
            status="initial",
            error=None,
        )
        db.insert_workflow_audit(
            tenant_id,
            project_id,
            published_revision_id,
            "version.changelog.classified",
            "success",
            actor_id,
            {
                "publishedRevisionId": published_revision_id,
                "baselineRevisionId": None,
                "status": "initial",
                "initialPublication": True,
            },
        )
        return

    baseline_ver = db.get_version_by_id(baseline_revision_id, tenant_id)
    if not baseline_ver:
        raise LookupError(
            f"baseline revision not found: {baseline_revision_id}"
        )

    from_label = str(baseline_ver.get("version_id") or "—")
    baseline_openapi = openapi_for_revision(baseline_ver, tenant_slug, tenant_id)
    candidate_openapi = openapi_for_revision(version, tenant_slug, tenant_id)

    classified = classify_openapi_changes(baseline_openapi, candidate_openapi)
    changelog = build_changelog(
        classified,
        from_version=from_label,
        to_version=to_label,
    )
    payload = render_changelog_json(changelog)

    db.upsert_version_changelog(
        tenant_id=tenant_id,
        project_id=project_id,
        published_revision_id=published_revision_id,
        baseline_revision_id=baseline_revision_id,
        changelog_json=payload,
        max_severity=changelog.max_severity,
        status="ready",
        error=None,
    )
    db.insert_workflow_audit(
        tenant_id,
        project_id,
        published_revision_id,
        "version.changelog.classified",
        "success",
        actor_id,
        {
            "publishedRevisionId": published_revision_id,
            "baselineRevisionId": baseline_revision_id,
            "status": "ready",
            "maxSeverity": changelog.max_severity,
            "counts": dict(changelog.counts or {}),
        },
    )


def backfill_latest_version_changelogs(
    *,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Classify the latest published revision per project that lacks a changelog row.

    Uses the same generator as the publish hook. Safe to re-run (skips rows that
    already exist via upsert / candidate filter).

    Args:
        limit: Optional max number of projects to process in this run.

    Returns:
        Summary dict with ``processed``, ``ready``, ``initial``, ``failed`` counts
        and a ``failures`` list of ``{projectId, revisionId, error}``.
    """
    candidates = db.list_projects_needing_changelog_backfill(limit=limit)
    summary: Dict[str, Any] = {
        "processed": 0,
        "ready": 0,
        "initial": 0,
        "failed": 0,
        "failures": [],
    }
    for row in candidates:
        tenant_id = str(row["tenant_id"])
        tenant_slug = str(row["tenant_slug"])
        project_id = str(row["project_id"])
        revision_id = str(row["published_revision_id"])
        summary["processed"] += 1
        try:
            generate_version_changelog_on_publish(
                tenant_slug=tenant_slug,
                tenant_id=tenant_id,
                project_id=project_id,
                published_revision_id=revision_id,
                actor_id=None,
            )
            stored = db.get_version_changelog(revision_id, tenant_id, project_id)
            status = (stored or {}).get("status") or "failed"
            if status == "ready":
                summary["ready"] += 1
            elif status == "initial":
                summary["initial"] += 1
            else:
                summary["failed"] += 1
                summary["failures"].append(
                    {
                        "projectId": project_id,
                        "revisionId": revision_id,
                        "error": (stored or {}).get("error") or "unknown",
                    }
                )
        except Exception as e:  # pragma: no cover - generator already swallows
            summary["failed"] += 1
            summary["failures"].append(
                {
                    "projectId": project_id,
                    "revisionId": revision_id,
                    "error": str(e),
                }
            )
    return summary
