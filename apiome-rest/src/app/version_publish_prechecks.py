"""Pre-publish validation shared by POST …/publish (#3212; guide-aware since GOV-1.4)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import HTTPException

from .compatibility_engine import CompatibilityCheckEngine, openapi_for_revision
from .database import db
from .models import VersionPublishRequest
from .publication_change_report import resolve_baseline_revision_id_for_change_report
from .schema_compatibility import CompatibilityRules

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishPrecheckOutcome:
    """What the publish prechecks observed (GOV-1.4, #4430).

    Carries the style-guide lint signal computed at publish time so the publish flow (and,
    with GOV-2.5, a configurable gate) can consume it. All fields are ``None`` when the
    checks were skipped (``skip_publish_checks``) or the lint step faulted — computing the
    signal is best-effort and never blocks a publish by itself.

    Attributes:
        lint_error_count: Number of **error**-severity violations under the resolved style
            guide, or ``None`` when not computed.
        guide_id: The applied guide's id (``None`` for the in-code fallback or when skipped).
        guide_name: The applied guide's display name, when computed.
    """

    lint_error_count: Optional[int] = None
    guide_id: Optional[str] = None
    guide_name: Optional[str] = None


def enforce_publish_prechecks(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    existing: Dict[str, Any],
    request: VersionPublishRequest,
) -> PublishPrecheckOutcome:
    """
    Ensure draft revisions satisfy publication gates unless ``skip_publish_checks`` is set.

    Since GOV-1.4 the prechecks also lint the revision under its resolved style guide
    (project → tenant → default) and report the error-level violation count on the returned
    :class:`PublishPrecheckOutcome` — the signal the GOV-2.5 publish gate will enforce.
    Computing it never blocks a publish on its own.

    Returns:
        The observed :class:`PublishPrecheckOutcome`.

    Raises:
        HTTPException: 422 for documentation gaps or invalid OpenAPI materialization.
        HTTPException: 409 when compatibility is breaking and ``allow_breaking`` is false.
    """
    if bool(request.skip_publish_checks):
        return PublishPrecheckOutcome()

    version_record_id = str(existing["id"])

    try:
        head_spec = openapi_for_revision(existing, tenant_slug, tenant_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not build OpenAPI for this revision (schema validation): {exc}",
        ) from exc

    # GOV-1.4: lint the materialized head under the resolved style guide and count the
    # error-level violations. Best-effort — the count feeds GOV-2.5's gate; a lint fault
    # must not block publishing today.
    outcome = PublishPrecheckOutcome()
    try:
        from .style_guide_engine import guided_lint_openapi_spec

        result, guide = guided_lint_openapi_spec(head_spec, tenant_id, project_id=project_id)
        outcome = PublishPrecheckOutcome(
            lint_error_count=int(result.severity_counts.get("error", 0)),
            guide_id=guide.guide_id,
            guide_name=guide.name,
        )
        logger.info(
            "Publish precheck lint for revision %s: %d error-level violation(s) under "
            "style guide %r",
            version_record_id,
            outcome.lint_error_count,
            guide.name,
        )
    except Exception:  # noqa: BLE001 - the lint signal is advisory until GOV-2.5
        logger.warning(
            "Publish precheck lint failed for revision %s; continuing without the "
            "style-guide signal",
            version_record_id,
            exc_info=True,
        )

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
        return outcome

    base_row = db.get_version_by_id(str(baseline_revision_id), tenant_id)
    if not base_row or not base_row.get("published"):
        return outcome

    rules = CompatibilityRules()
    base_spec = openapi_for_revision(base_row, tenant_slug, tenant_id)
    result = CompatibilityCheckEngine.run(base_spec, head_spec, rules)

    if result.overall != "breaking":
        return outcome
    if bool(request.allow_breaking):
        return outcome

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
