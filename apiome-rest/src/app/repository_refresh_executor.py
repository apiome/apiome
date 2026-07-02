"""Spec-faithful re-import hydration for repository auto-refresh (RAR-4.1, #3527).

The RAR-3.2 sweep (:mod:`repository_refresh_sweep`) enqueues a self-contained
``apiome.tenant_repository_refresh_jobs`` row per stale file, snapshotting the stored
import spec (source kind, source descriptor, and the verbatim options blob) that
was captured at first import (RAR-1.1/1.2/1.3). This module turns one such row into
the metadata the spec-import worker consumes, stamped with the synthetic
``repository_auto_import`` source kind so the worker hydrates the importer kind,
options, and parsing from the stored spec instead of falling back to importer
defaults.

It is a pure mapping (no DB, no I/O): the EPIC-4 executor (RAR-4.2) and the worker
agree on the envelope here, and a golden-fixture test can assert byte-identical
option application versus the original import.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from .models import (
    REPOSITORY_AUTO_IMPORT_SOURCE_KIND,
    REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION,
    RepositoryRefreshProvenance,
    SpecImportProjectTarget,
    SpecImportStartMetadata,
    SpecImportStoredSpec,
    SpecImportVersionTarget,
)


def _coerce_options_blob(raw: Any) -> Dict[str, Any]:
    """Normalize a stored ``options_json`` value into a plain dict.

    The column is JSONB, but a cursor may surface it either as a dict (the common
    case) or as a JSON-encoded string. An empty/``None`` value yields an empty dict
    so a spec with no options replays as importer defaults rather than failing.

    Args:
        raw: The stored options value (dict, JSON string, or ``None``).

    Returns:
        The options as a plain dict.

    Raises:
        ValueError: If ``raw`` is a non-empty string that is not valid JSON, or a
            type that is neither a mapping nor a string.
    """
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        decoded = json.loads(text)
        if not isinstance(decoded, Mapping):
            raise ValueError("Stored options_json must decode to a JSON object.")
        return dict(decoded)
    raise ValueError(
        f"Unsupported stored options_json type {type(raw).__name__}; expected object or JSON string."
    )


def build_stored_spec_from_refresh_job(job_row: Mapping[str, Any]) -> SpecImportStoredSpec:
    """Build the worker's stored-spec payload from a refresh job row.

    Mirrors the snapshot the RAR-3.2 sweep persisted on the
    ``apiome.tenant_repository_refresh_jobs`` row so the worker replays the original
    import faithfully (RAR-4.1).

    Args:
        job_row: An enqueued refresh job row (or any mapping carrying the same
            ``source_kind`` / ``format_override`` / ``content_type`` /
            ``options_json`` / ``spec_schema_version`` keys).

    Returns:
        The :class:`SpecImportStoredSpec` to carry into the worker metadata.

    Raises:
        ValueError: If the row lacks a ``source_kind`` (nothing to route on), or the
            stored options blob cannot be decoded.
    """
    source_kind = (job_row.get("source_kind") or "").strip()
    if not source_kind:
        raise ValueError(
            "Refresh job row is missing source_kind; cannot replay the original import (RAR-4.1)."
        )

    schema_version = job_row.get("spec_schema_version")
    return SpecImportStoredSpec(
        source_kind=source_kind,
        format_override=job_row.get("format_override"),
        content_type=job_row.get("content_type"),
        options=_coerce_options_blob(job_row.get("options_json")),
        spec_schema_version=(
            int(schema_version)
            if schema_version is not None
            else REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION
        ),
    )


def _clean_str(raw: Any) -> Optional[str]:
    """Return a stripped non-empty string, or ``None`` for blank/missing values."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def build_refresh_provenance_from_job(
    job_row: Mapping[str, Any],
    *,
    parent_version_id: Optional[str] = None,
) -> RepositoryRefreshProvenance:
    """Build the RAR-4.2 refresh provenance for a version from a refresh job row.

    The RAR-3.2 sweep snapshots the remote freshness signals that triggered the
    refresh on the ``apiome.tenant_repository_refresh_jobs`` row
    (``remote_commit_sha`` / ``remote_committed_at``). This maps them onto the
    provenance recorded on the new version, plus the prior version it supersedes.

    Args:
        job_row: The enqueued refresh job row carrying the remote freshness signals.
        parent_version_id: The prior version (versions.id) the refresh supersedes,
            resolved by the caller; the new version's linear parent. ``None`` when
            the refresh produces the first revision in the project.

    Returns:
        The :class:`RepositoryRefreshProvenance` to carry into version creation.
    """
    return RepositoryRefreshProvenance(
        parent_version_id=_clean_str(parent_version_id),
        source_commit_sha=_clean_str(job_row.get("remote_commit_sha")),
        source_committed_at=job_row.get("remote_committed_at"),
    )


def build_auto_refresh_import_metadata(
    job_row: Mapping[str, Any],
    *,
    project: SpecImportProjectTarget,
    version: SpecImportVersionTarget,
    existing_project_id: Optional[str] = None,
    parent_version_id: Optional[str] = None,
) -> SpecImportStartMetadata:
    """Build worker metadata for a repository auto-refresh re-import (RAR-4.1/4.2).

    Stamps the synthetic ``repository_auto_import`` source kind and attaches the
    stored spec snapshot so the worker hydrates kind/options/parsing from it
    (RAR-4.1), plus the refresh provenance (prior version + source commit) recorded
    on the new version (RAR-4.2). The catalog target (project/version) is supplied
    by the caller.

    Args:
        job_row: The enqueued refresh job row carrying the stored spec snapshot and
            the remote freshness signals.
        project: The catalog project target the refresh imports into.
        version: The target catalog revision for the refresh.
        existing_project_id: When set, attach to this existing catalog project id
            instead of creating one (the usual case for a refresh).
        parent_version_id: The prior version (versions.id) the refresh supersedes,
            recorded as the new version's parent in the refresh provenance.

    Returns:
        The :class:`SpecImportStartMetadata` for :func:`schedule_spec_import`.
    """
    return SpecImportStartMetadata(
        source_kind=REPOSITORY_AUTO_IMPORT_SOURCE_KIND,
        project=project,
        version=version,
        existing_project_id=existing_project_id,
        repository_import_spec=build_stored_spec_from_refresh_job(job_row),
        refresh_provenance=build_refresh_provenance_from_job(
            job_row, parent_version_id=parent_version_id
        ),
    )
