"""Backfill a revision's missing captured source — E1-6 (#6221).

Export, conversion and the schema bench rebuild a catalog revision's canonical model from the
source captured at import (``format_metadata.sourceContent``). A revision without one cannot be
exported: the routes answer ``422 source-not-captured`` and the UI offers **Re-import**. This
one-off job repairs the revisions it can, from a copy of the original that is still stored:

1. **A sibling revision** of the same item, in the same format, whose captured source is
   identical to what this revision was imported from.
2. **The linked repository** a repository-imported item came from (``repository_import_spec``):
   the file at its recorded branch and path, re-read from GitHub.

A candidate is used only when it is **proven identical**: it is parsed and normalized exactly as
an import would, and its canonical fingerprint must equal the ``fingerprint`` the revision
recorded at import (MFI-25.8). A revision with no recorded fingerprint cannot be proven and is
left alone (``unverifiable``) — the backfill never stores text that might belong to a different
version. A repository file is scrubbed under the tenant's secret-scrub policy before it is stored,
exactly as at intake (MFI-29.6). A source that was deliberately withheld (``sourceWithheld``) and a
decomposed OpenAPI import (rebuilt from the database, never captured) are not candidates.

Every repair stamps ``sourceBackfilledFrom`` on the revision. The job reports how many revisions it
scanned, repaired, and could not repair, and why — ``scripts/backfill_captured_sources.py`` runs it
(``--dry-run`` reports without writing).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .catalog_conversion import build_conversion_source
from .conversion_job import ConversionError
from .import_source import ImportSourceError, canonical_fingerprint

logger = logging.getLogger(__name__)

__all__ = [
    "BackfillOutcome",
    "BackfillReport",
    "CONTENT_KEYS",
    "backfill_captured_sources",
    "find_missing_source_revisions",
]

#: The ``format_metadata`` keys that make up a captured source (single document or archive).
CONTENT_KEYS: Tuple[str, ...] = ("sourceContent", "sourceEncoding", "intakeKind", "filesetRoot", "filesetMembers")

#: Outcome statuses, in the report's order.
REPAIRED = "repaired"
WOULD_REPAIR = "would-repair"
UNVERIFIABLE = "unverifiable"
NO_COPY = "no-copy"

#: Reads a linked-repository file: ``(tenant_id, project_id) -> [(label, text)]`` candidates.
RepositoryReader = Callable[[Any, str, str], List[Tuple[str, str]]]


@dataclass
class BackfillOutcome:
    """What happened to one revision without a captured source."""

    revision_id: str
    project_id: str
    tenant_id: str
    status: str
    source: Optional[str] = None
    detail: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """JSON-ready form for the report."""
        return {
            "revision_id": self.revision_id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "source": self.source,
            "detail": self.detail,
        }


@dataclass
class BackfillReport:
    """The backfill's totals and per-revision outcomes."""

    dry_run: bool
    outcomes: List[BackfillOutcome] = field(default_factory=list)

    def count(self, status: str) -> int:
        """How many revisions ended with ``status``."""
        return sum(1 for outcome in self.outcomes if outcome.status == status)

    def as_dict(self) -> Dict[str, Any]:
        """JSON-ready report: totals first, then every outcome."""
        repaired = self.count(WOULD_REPAIR if self.dry_run else REPAIRED)
        return {
            "dry_run": self.dry_run,
            "scanned": len(self.outcomes),
            "repaired": repaired,
            "unrepaired": len(self.outcomes) - repaired,
            "unverifiable": self.count(UNVERIFIABLE),
            "no_copy": self.count(NO_COPY),
            "outcomes": [outcome.as_dict() for outcome in self.outcomes],
        }


def _bag(value: Any) -> Dict[str, Any]:
    """A JSONB column as a dict (cursors may surface it as a JSON string)."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except ValueError:
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def find_missing_source_revisions(db: Any, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The live revisions with no captured source that a backfill could repair.

    Excludes decomposed OpenAPI imports (their document is rebuilt from the database) and sources
    that were deliberately withheld.

    Args:
        db: Database handle.
        tenant_id: Limit to one tenant; ``None`` scans every tenant.

    Returns:
        Rows with ``id``, ``project_id``, ``tenant_id``, ``source_format``, ``protocol``,
        ``format_metadata``, ``tool_versions`` and the project ``metadata``, oldest first.
    """
    params: List[Any] = []
    tenant_clause = ""
    if tenant_id:
        tenant_clause = "AND p.tenant_id = %s::uuid"
        params.append(tenant_id)
    rows = db.execute_query(
        f"""
        SELECT v.id, v.project_id, p.tenant_id, v.source_format, v.protocol, v.format_metadata,
               v.source_tool_versions AS tool_versions, p.metadata
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.deleted_at IS NULL AND p.deleted_at IS NULL
          AND coalesce(v.source_format, '') <> ''
          AND lower(v.source_format) NOT LIKE 'openapi%%'
          AND lower(v.source_format) NOT LIKE 'swagger%%'
          AND coalesce(v.format_metadata ->> 'sourceContent', '') = ''
          AND coalesce(v.format_metadata ->> 'sourceWithheld', '') = ''
          {tenant_clause}
        ORDER BY v.created_at, v.id
        """,
        tuple(params),
    )
    return [dict(row) for row in rows]


def _item(row: Mapping[str, Any], format_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """A catalog-item-shaped row for :func:`build_conversion_source`."""
    return {
        "id": str(row["project_id"]),
        "source_format": row.get("source_format"),
        "protocol": row.get("protocol"),
        "format_metadata": format_metadata,
        "tool_versions": row.get("tool_versions"),
        "metadata": row.get("metadata"),
    }


def _fingerprint_of(row: Mapping[str, Any], format_metadata: Dict[str, Any]) -> Optional[str]:
    """The canonical fingerprint of ``row`` rebuilt from ``format_metadata``, or ``None`` if it fails."""
    try:
        source = build_conversion_source(_item(row, format_metadata), source_version_id=str(row["id"]))
    except (ConversionError, ImportSourceError, ValueError, TypeError):
        return None
    return canonical_fingerprint(source.api)


def _sibling_candidates(db: Any, row: Mapping[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """The captured sources of the item's other revisions in the same format, newest first."""
    rows = db.execute_query(
        """
        SELECT v.id, v.format_metadata
        FROM apiome.versions v
        WHERE v.project_id = %s::uuid AND v.id <> %s::uuid AND v.deleted_at IS NULL
          AND v.source_format = %s
          AND coalesce(v.format_metadata ->> 'sourceContent', '') <> ''
        ORDER BY v.created_at DESC, v.id DESC
        """,
        (str(row["project_id"]), str(row["id"]), row.get("source_format")),
    )
    candidates = []
    for sibling in rows:
        fmd = _bag(sibling.get("format_metadata"))
        fields = {key: fmd[key] for key in CONTENT_KEYS if key in fmd}
        candidates.append((f"sibling:{sibling['id']}", fields))
    return candidates


def read_linked_repository_files(db: Any, tenant_id: str, project_id: str) -> List[Tuple[str, str]]:
    """Re-read the files a repository-imported item came from, at their recorded branch and path.

    Args:
        db: Database handle.
        tenant_id: Owning tenant.
        project_id: The item (``repository_import_spec.project_id``).

    Returns:
        ``(label, text)`` pairs — ``label`` is ``repository:<repo id>@<branch>:<path>``. A file
        that cannot be read (repository gone, no token, file moved) is skipped.
    """
    from .repository_file_scan import (
        _github_owner_repo,
        _resolve_scan_token,
        fetch_github_repository_file_text,
    )

    specs = db.execute_query(
        """
        SELECT repository_id, branch, path FROM apiome.repository_import_spec
        WHERE tenant_id = %s::uuid AND project_id = %s::uuid
        ORDER BY updated_at DESC
        """,
        (tenant_id, project_id),
    )
    files: List[Tuple[str, str]] = []
    for spec in specs:
        label = f"repository:{spec['repository_id']}@{spec['branch']}:{spec['path']}"
        try:
            repo = db.get_tenant_repository(tenant_id, str(spec["repository_id"]))
            if not repo:
                continue
            owner, name = _github_owner_repo(repo)
            text, truncated = fetch_github_repository_file_text(
                owner, name, str(spec["path"]), str(spec["branch"]), _resolve_scan_token(db, repo)
            )
        except Exception:  # noqa: BLE001 - an unreadable repository is just "no copy"
            logger.info("source backfill could not read %s", label, exc_info=True)
            continue
        if not truncated:
            files.append((label, text))
    return files


def _scrubbed_fields(tenant_id: str, source_format: Optional[str], text: str) -> Dict[str, Any]:
    """The ``format_metadata`` source fields for a repository file, scrubbed as at intake."""
    from .import_source_pipeline import _ResolvedIntake, scrub_intake_source
    from .intake_scrub_policy import load_tenant_scrub_policy, resolve_scrub_mode

    resolution = resolve_scrub_mode(load_tenant_scrub_policy(tenant_id), format_key=source_format)
    intake = _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)
    fields, _report = scrub_intake_source(intake, resolution)
    return fields


def _write_repair(db: Any, revision_id: str, fields: Dict[str, Any], source: str) -> None:
    """Merge the repaired source fields (and their provenance) into the revision."""
    db.execute_query(
        """
        UPDATE apiome.versions
        SET format_metadata = coalesce(format_metadata, '{}'::jsonb) || %s::jsonb,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s::uuid
        RETURNING id
        """,
        (json.dumps({**fields, "sourceBackfilledFrom": source}), revision_id),
    )


def _repair_one(
    db: Any, row: Mapping[str, Any], *, dry_run: bool, read_repository: RepositoryReader
) -> BackfillOutcome:
    """Try every stored copy for one revision; repair it from the first proven identical."""
    outcome = BackfillOutcome(
        revision_id=str(row["id"]), project_id=str(row["project_id"]), tenant_id=str(row["tenant_id"]),
        status=NO_COPY,
    )
    fmd = _bag(row.get("format_metadata"))
    expected = fmd.get("fingerprint")
    if not expected:
        outcome.status = UNVERIFIABLE
        outcome.detail = "No fingerprint was recorded at import, so no copy can be proven identical."
        return outcome

    for label, fields in _sibling_candidates(db, row):
        if _fingerprint_of(row, {**fmd, **fields}) == expected:
            if not dry_run:
                _write_repair(db, outcome.revision_id, fields, label)
            outcome.status, outcome.source = (WOULD_REPAIR if dry_run else REPAIRED), label
            return outcome

    for label, text in read_repository(db, outcome.tenant_id, outcome.project_id):
        if _fingerprint_of(row, {**fmd, "sourceContent": text, "intakeKind": "file"}) != expected:
            continue
        fields = _scrubbed_fields(outcome.tenant_id, row.get("source_format"), text)
        if not dry_run:
            _write_repair(db, outcome.revision_id, fields, label)
        outcome.status, outcome.source = (WOULD_REPAIR if dry_run else REPAIRED), label
        return outcome

    outcome.detail = "No stored copy matches what this revision was imported from; re-import it."
    return outcome


def backfill_captured_sources(
    db: Any,
    *,
    tenant_id: Optional[str] = None,
    dry_run: bool = False,
    read_repository: RepositoryReader = read_linked_repository_files,
) -> BackfillReport:
    """Repair every revision with no captured source that a stored copy can prove.

    Args:
        db: Database handle.
        tenant_id: Limit to one tenant; ``None`` scans every tenant.
        dry_run: Report what would be repaired without writing.
        read_repository: The linked-repository reader (a test seam).

    Returns:
        The report: how many revisions were scanned, repaired and left, and each outcome.
    """
    report = BackfillReport(dry_run=dry_run)
    for row in find_missing_source_revisions(db, tenant_id):
        try:
            report.outcomes.append(_repair_one(db, row, dry_run=dry_run, read_repository=read_repository))
        except Exception as exc:  # noqa: BLE001 - one revision's fault never stops the job
            logger.warning("source backfill failed for revision %s", row.get("id"), exc_info=True)
            report.outcomes.append(
                BackfillOutcome(
                    revision_id=str(row["id"]), project_id=str(row["project_id"]),
                    tenant_id=str(row["tenant_id"]), status=NO_COPY, detail=f"Backfill failed: {exc}",
                )
            )
    return report
