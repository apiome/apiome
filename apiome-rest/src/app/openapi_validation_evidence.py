"""Capture OpenAPI external validation evidence at score time (CLX-2.2 / #4852).

Runs the parity-selected default bulk runner under the style guide's external lint
profile and persists a CLX-1.1 evidence run. Native score remains authoritative —
external findings are evidence-only unless callers merge ``lint_findings``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping, Optional

from .database import db
from .openapi_validation_pack import run_openapi_validation_pack
from .openapi_validation_profiles import PROFILE_BASELINE, normalize_profile
from .toolchain_packaging import probe_tool

logger = logging.getLogger(__name__)

__all__ = [
    "capture_openapi_external_validation_evidence",
    "capture_openapi_external_validation_evidence_sync",
]


async def capture_openapi_external_validation_evidence(
    document: Mapping[str, Any],
    *,
    version_record_id: str,
    tenant_id: str,
    project_id: Optional[str] = None,
    profile: Optional[str] = None,
) -> Optional[str]:
    """Run the default bulk OpenAPI validation pack and persist evidence.

    Degrades gracefully when the default tool is unavailable. Never raises into
    the caller's lint/score path.

    Returns:
        The new evidence-run id, or ``None`` when skipped / duplicate / failed soft.
    """
    try:
        resolved_profile = normalize_profile(profile)
        if profile is None and tenant_id:
            from .style_guide_engine import resolve_style_guide

            guide = resolve_style_guide(tenant_id, project_id)
            # Prefer DB column when the guide row is still available.
            if guide.guide_id:
                row = db.get_style_guide_by_id(str(guide.guide_id), tenant_id)
                if row and row.get("external_lint_profile"):
                    resolved_profile = normalize_profile(row.get("external_lint_profile"))

        from .openapi_validation_pack import DEFAULT_BULK_RUNNER, _ADAPTER_BY_ID

        tool_key = _ADAPTER_BY_ID[DEFAULT_BULK_RUNNER].tool_key
        avail = probe_tool(tool_key)
        if not getattr(avail, "available", False):
            # Still record unavailable evidence so coverage is visible.
            pack = await run_openapi_validation_pack(
                document=dict(document),
                profile=resolved_profile or PROFILE_BASELINE,
            )
        else:
            guide_rows = None
            custom_rules = None
            if resolved_profile == "tenant_guide" and tenant_id:
                from .style_guide_engine import resolve_style_guide
                from .openapi_validation_profiles import custom_rules_from_guide_rows

                guide = resolve_style_guide(tenant_id, project_id)
                if guide.guide_id:
                    guide_rows = db.get_style_guide_rules(str(guide.guide_id), tenant_id)
                    custom_rules = custom_rules_from_guide_rows(guide_rows)
            pack = await run_openapi_validation_pack(
                document=dict(document),
                profile=resolved_profile or PROFILE_BASELINE,
                custom_rules=custom_rules,
                guide_rows=guide_rows,
            )

        evidence = pack.to_evidence_run(subject_id=version_record_id)
        return db.record_lint_evidence_run(evidence)
    except Exception:  # noqa: BLE001 — evidence capture is best-effort
        logger.warning(
            "Failed to capture OpenAPI external validation evidence for %s",
            version_record_id,
            exc_info=True,
        )
        return None


def capture_openapi_external_validation_evidence_sync(
    document: Mapping[str, Any],
    *,
    version_record_id: str,
    tenant_id: str,
    project_id: Optional[str] = None,
    profile: Optional[str] = None,
) -> Optional[str]:
    """Sync wrapper for score-capture paths that are not already async."""
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                capture_openapi_external_validation_evidence(
                    document,
                    version_record_id=version_record_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    profile=profile,
                )
            )
        # Already inside an event loop — schedule is unsafe from sync score paths; skip.
        logger.debug(
            "Skipping sync OpenAPI external evidence capture inside a running event loop"
        )
        return None
    except Exception:  # noqa: BLE001
        logger.warning(
            "Sync OpenAPI external evidence capture failed for %s",
            version_record_id,
            exc_info=True,
        )
        return None
