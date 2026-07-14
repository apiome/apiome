"""Capture oasdiff compatibility evidence (CLX-2.3 / #4853).

Runs the oasdiff adapter against a base/head OpenAPI pair, persists a CLX-1.1
evidence run (with changelog markdown in coverage), and never raises into the
native compatibility / lint path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Mapping, Optional, Tuple

from .database import db
from .external_linter_adapter import AdapterInput, InputFormat, ScanMode, run_adapter
from .openapi_compatibility_adapters import (
    OASDIFF_ADAPTER_ID,
    OASDIFF_ADAPTER_VERSION,
    OasdiffAdapter,
    render_oasdiff_changelog_markdown,
    try_openapi_changes_html,
)

logger = logging.getLogger(__name__)

__all__ = [
    "run_oasdiff_compatibility",
    "capture_oasdiff_compatibility_evidence",
    "capture_oasdiff_compatibility_evidence_sync",
]


async def run_oasdiff_compatibility(
    *,
    base_document: Mapping[str, Any],
    head_document: Mapping[str, Any],
    base_files: Optional[Mapping[str, str]] = None,
    head_files: Optional[Mapping[str, str]] = None,
) -> Tuple[Any, Optional[str], Optional[str]]:
    """Run oasdiff and optional changelog renderers.

    Returns:
        ``(AdapterRunResult, changelog_markdown, changelog_html)``.
    """
    meta: Dict[str, Any] = {}
    if base_files:
        meta["base_files"] = dict(base_files)
    else:
        meta["base_document"] = dict(base_document)
    inputs = AdapterInput(
        document=None if head_files else dict(head_document),
        files=dict(head_files) if head_files else {},
        format=InputFormat.OPENAPI,
        scan_mode=ScanMode.BREAKING,
        metadata=meta,
    )
    result = await run_adapter(OasdiffAdapter(), inputs)
    changelog_md: Optional[str] = None
    changelog_html: Optional[str] = None
    try:
        changelog_md = await render_oasdiff_changelog_markdown(
            base_document=base_document,
            revision_document=head_document,
            base_files=base_files,
            revision_files=head_files,
        )
    except Exception:  # noqa: BLE001
        logger.debug("oasdiff markdown changelog failed", exc_info=True)
    try:
        changelog_html = await try_openapi_changes_html(
            base_document=base_document,
            revision_document=head_document,
            base_files=base_files,
            revision_files=head_files,
        )
    except Exception:  # noqa: BLE001
        logger.debug("HTML changelog render failed", exc_info=True)
    return result, changelog_md, changelog_html


async def capture_oasdiff_compatibility_evidence(
    *,
    base_document: Mapping[str, Any],
    head_document: Mapping[str, Any],
    version_record_id: str,
    base_revision_id: Optional[str] = None,
    head_revision_id: Optional[str] = None,
    base_files: Optional[Mapping[str, str]] = None,
    head_files: Optional[Mapping[str, str]] = None,
    result: Any = None,
    changelog_md: Optional[str] = None,
    changelog_html: Optional[str] = None,
) -> Optional[str]:
    """Run oasdiff (unless ``result`` is provided) and persist evidence. Best-effort.

    Returns:
        New evidence-run id, or ``None`` when skipped / duplicate / soft-failed.
    """
    try:
        if result is None:
            result, changelog_md, changelog_html = await run_oasdiff_compatibility(
                base_document=base_document,
                head_document=head_document,
                base_files=base_files,
                head_files=head_files,
            )
        evidence = result.to_evidence_run(
            subject_id=version_record_id,
            profile="compatibility",
            config={
                "baseRevisionId": base_revision_id,
                "headRevisionId": head_revision_id,
                "adapter": OASDIFF_ADAPTER_ID,
                "adapterVersion": OASDIFF_ADAPTER_VERSION,
            },
        )
        coverage = dict(evidence.get("coverage") or {})
        if base_revision_id:
            coverage["baseRevisionId"] = base_revision_id
        if head_revision_id:
            coverage["headRevisionId"] = head_revision_id
        if changelog_md:
            coverage["changelogMarkdown"] = changelog_md[:200_000]
        if changelog_html:
            coverage["changelogHtml"] = changelog_html[:500_000]
        evidence["coverage"] = coverage
        return db.record_lint_evidence_run(evidence)
    except Exception:  # noqa: BLE001 — evidence must never break callers
        logger.warning(
            "Failed to capture oasdiff compatibility evidence for %s",
            version_record_id,
            exc_info=True,
        )
        return None


def capture_oasdiff_compatibility_evidence_sync(
    *,
    base_document: Mapping[str, Any],
    head_document: Mapping[str, Any],
    version_record_id: str,
    base_revision_id: Optional[str] = None,
    head_revision_id: Optional[str] = None,
) -> Optional[str]:
    """Sync wrapper for non-async score/compat paths."""
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                capture_oasdiff_compatibility_evidence(
                    base_document=base_document,
                    head_document=head_document,
                    version_record_id=version_record_id,
                    base_revision_id=base_revision_id,
                    head_revision_id=head_revision_id,
                )
            )
        logger.debug(
            "Skipping sync oasdiff evidence capture inside a running event loop"
        )
        return None
    except Exception:  # noqa: BLE001
        logger.warning(
            "Sync oasdiff evidence capture failed for %s",
            version_record_id,
            exc_info=True,
        )
        return None
