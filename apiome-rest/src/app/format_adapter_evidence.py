"""Persist Buf / GraphQL ESLint adapter evidence for catalog revisions (CLX-2.4, #4854).

Best-effort capture: never raises into the caller's lint/score path. Unavailable tools
still record evidence so coverage is visible.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Optional, Sequence

from .database import db
from .external_linter_adapter import (
    AdapterInput,
    BufLintAdapter,
    InputFormat,
    ScanMode,
    run_adapter,
)
from .external_linter_runner import default_restricted_runner
from .format_lint_capabilities import normalize_format_key
from .graphql_eslint_adapter import run_graphql_eslint_via_adapter
from .lint_evidence import SUBJECT_CATALOG_REVISION

logger = logging.getLogger(__name__)

__all__ = [
    "capture_buf_lint_evidence",
    "capture_buf_lint_evidence_sync",
    "capture_graphql_eslint_evidence",
    "capture_graphql_eslint_evidence_sync",
    "capture_format_adapters_for_revision",
    "capture_format_adapters_for_revision_sync",
]


async def capture_buf_lint_evidence(
    files: Sequence[Any],
    *,
    version_record_id: str,
    tenant_id: str,
) -> Optional[str]:
    """Run Buf lint via the SPI and persist a CLX-1.1 evidence run.

    Args:
        files: Sequence of objects with ``path`` and ``content`` (``ProtoFile``).
        version_record_id: Catalog revision id (``versions.id``).
        tenant_id: Owning tenant (reserved for future scoping; unused today).

    Returns:
        New evidence-run id, or ``None`` when skipped / soft-failed.
    """
    _ = tenant_id
    try:
        file_map = {str(f.path): str(f.content) for f in files}
        if not file_map:
            return None
        result = await run_adapter(
            BufLintAdapter(),
            AdapterInput(
                files=file_map,
                format=InputFormat.PROTOBUF,
                scan_mode=ScanMode.LINT,
            ),
            runner=default_restricted_runner,
        )
        evidence = result.to_evidence_run(
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id=version_record_id,
            profile="import-capture",
        )
        return db.record_lint_evidence_run(evidence)
    except Exception:  # noqa: BLE001 — evidence capture is best-effort
        logger.warning(
            "Failed to capture Buf lint evidence for %s",
            version_record_id,
            exc_info=True,
        )
        return None


def capture_buf_lint_evidence_sync(
    files: Sequence[Any],
    *,
    version_record_id: str,
    tenant_id: str,
) -> Optional[str]:
    """Sync wrapper for score-capture paths that are not already async."""
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                capture_buf_lint_evidence(
                    files,
                    version_record_id=version_record_id,
                    tenant_id=tenant_id,
                )
            )
        logger.debug(
            "Skipping sync Buf evidence capture inside a running event loop"
        )
        return None
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed sync Buf lint evidence capture for %s",
            version_record_id,
            exc_info=True,
        )
        return None


async def capture_graphql_eslint_evidence(
    sdl: str,
    *,
    version_record_id: str,
    tenant_id: str,
) -> Optional[str]:
    """Run GraphQL ESLint via the SPI and persist a CLX-1.1 evidence run.

    Records ``unavailable`` coverage when the CLI is missing — never silent absence.

    Args:
        sdl: GraphQL SDL text.
        version_record_id: Catalog revision id.
        tenant_id: Owning tenant (reserved for future scoping).

    Returns:
        New evidence-run id, or ``None`` when skipped / soft-failed.
    """
    _ = tenant_id
    try:
        if not (sdl or "").strip():
            return None
        result = await run_graphql_eslint_via_adapter(sdl)
        evidence = result.to_evidence_run(
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id=version_record_id,
            profile="import-capture",
        )
        return db.record_lint_evidence_run(evidence)
    except Exception:  # noqa: BLE001 — evidence capture is best-effort
        logger.warning(
            "Failed to capture GraphQL ESLint evidence for %s",
            version_record_id,
            exc_info=True,
        )
        return None


def capture_graphql_eslint_evidence_sync(
    sdl: str,
    *,
    version_record_id: str,
    tenant_id: str,
) -> Optional[str]:
    """Sync wrapper for GraphQL ESLint evidence capture."""
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                capture_graphql_eslint_evidence(
                    sdl,
                    version_record_id=version_record_id,
                    tenant_id=tenant_id,
                )
            )
        logger.debug(
            "Skipping sync GraphQL ESLint evidence capture inside a running event loop"
        )
        return None
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed sync GraphQL ESLint evidence capture for %s",
            version_record_id,
            exc_info=True,
        )
        return None


def _source_text_from_projection(projection: Any) -> Optional[str]:
    """Extract plain-text source from a version source projection when available."""
    if not projection:
        return None
    fmd = projection.get("format_metadata") or {}
    if not isinstance(fmd, dict):
        return None
    if fmd.get("intakeKind") == "archive" or fmd.get("sourceEncoding") == "base64":
        return None
    content = fmd.get("sourceContent") or fmd.get("rawSource") or fmd.get("source_content")
    if isinstance(content, str) and content.strip():
        return content
    return None


def _scanner_already_evidenced(version_record_id: str, tenant_id: str, scanner_id: str) -> bool:
    """True when the revision already has at least one evidence run for ``scanner_id``."""
    rows = db.list_lint_evidence_runs_for_version(version_record_id, tenant_id)
    return any(str(r.get("scanner_id")) == scanner_id for r in rows)


async def capture_format_adapters_for_revision(
    *,
    version_record_id: str,
    tenant_id: str,
    source_format: Optional[str] = None,
    source_text: Optional[str] = None,
) -> List[Optional[str]]:
    """Capture Buf / GraphQL ESLint evidence for a revision based on its source format.

    Loads the revision's source projection when ``source_format`` / ``source_text`` are
    not provided. Archive / base64 multi-file uploads are skipped (no unpack here).
    Skips a scanner when evidence already exists so GET evidence stays idempotent.
    """
    ids: List[Optional[str]] = []
    try:
        from .external_linter_adapter import BUF_LINT_SCANNER_ID
        from .graphql_eslint_adapter import GRAPHQL_ESLINT_SCANNER_ID

        projection = db.get_version_source_projection(version_record_id, tenant_id)
        fmt = normalize_format_key(source_format or (projection or {}).get("source_format"))
        text = source_text if source_text is not None else _source_text_from_projection(projection)
        if not fmt:
            return ids
        if fmt == "graphql" and text:
            if not _scanner_already_evidenced(
                version_record_id, tenant_id, GRAPHQL_ESLINT_SCANNER_ID
            ):
                ids.append(
                    await capture_graphql_eslint_evidence(
                        text,
                        version_record_id=version_record_id,
                        tenant_id=tenant_id,
                    )
                )
        elif fmt == "protobuf" and text:
            if not _scanner_already_evidenced(
                version_record_id, tenant_id, BUF_LINT_SCANNER_ID
            ):
                # Single-file proto uploads: name stably for Buf's module materializer.
                class _F:
                    path = "schema.proto"
                    content = text

                ids.append(
                    await capture_buf_lint_evidence(
                        [_F()],
                        version_record_id=version_record_id,
                        tenant_id=tenant_id,
                    )
                )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed format-adapter evidence capture for %s",
            version_record_id,
            exc_info=True,
        )
    return ids


def capture_format_adapters_for_revision_sync(
    *,
    version_record_id: str,
    tenant_id: str,
    source_format: Optional[str] = None,
    source_text: Optional[str] = None,
) -> List[Optional[str]]:
    """Sync wrapper for :func:`capture_format_adapters_for_revision`."""
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                capture_format_adapters_for_revision(
                    version_record_id=version_record_id,
                    tenant_id=tenant_id,
                    source_format=source_format,
                    source_text=source_text,
                )
            )
        logger.debug(
            "Skipping sync format-adapter evidence capture inside a running event loop"
        )
        return []
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed sync format-adapter evidence capture for %s",
            version_record_id,
            exc_info=True,
        )
        return []
