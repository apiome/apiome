"""The refresh-source protocol shared by Git repositories and catalog connectors (CDG-1.1, #5952).

The repository auto-refresh engine (RAR-3.2) was written against one kind of source: a Git
branch whose files carry commit timestamps and blob SHAs. Catalog connectors (API gateways,
schema registries, URLs) are a second kind, and giving them their own scheduler would give a
tenant two cadences, two quotas and two audit trails. Instead both implement
:class:`RefreshSource`:

* :meth:`RefreshSource.list_candidates` — what the source currently holds (files on a branch,
  APIs in a gateway's inventory);
* :meth:`RefreshSource.freshness_key` — the remote and last-imported freshness signals for one
  candidate, which :func:`decide_refresh` feeds to the RAR-2.2 newer-than gate
  (:func:`app.repository_refresh_comparator.evaluate_refresh`), so both kinds share one rule;
* :meth:`RefreshSource.fetch` — what refreshing one candidate needs;
* :meth:`RefreshSource.describe` — a credential-free description for logs, runs and audit rows.

:class:`GitBranchRefreshSource` is the first implementation and wraps the existing Git path
without changing it: candidates are the stored import specs of one branch, rescanned through
the REPO-2 walker, and ``fetch`` returns the spec-faithful re-import job the sweep enqueues
(the EPIC-4 executor downloads the file content later, exactly as before). A connector source
returns a :class:`FetchedDocument` instead, since a connector run imports what it fetched
directly (:mod:`app.catalog_connector_sync`).

A source signals a provider failure by raising :class:`RefreshSourceError` with the provider's
error class and HTTP status, so a run that could not fetch anything is recorded as a failure
with a reason, never as a success with zero changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple, Union, runtime_checkable

from .repository_refresh_comparator import RefreshDecision, evaluate_refresh

_logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_CLASS_AUTH",
    "ERROR_CLASS_NOT_FOUND",
    "ERROR_CLASS_RATE_LIMITED",
    "ERROR_CLASS_UNAVAILABLE",
    "ERROR_CLASS_UNEXPECTED",
    "FetchedDocument",
    "FreshnessKey",
    "GitBranchRefreshSource",
    "RefreshCandidate",
    "RefreshJobRequest",
    "RefreshSource",
    "RefreshSourceError",
    "decide_refresh",
    "error_class_for_status",
]

#: Stable provider error classes recorded on a failed run (``error_class``).
ERROR_CLASS_AUTH = "auth"
ERROR_CLASS_NOT_FOUND = "not-found"
ERROR_CLASS_RATE_LIMITED = "rate-limited"
ERROR_CLASS_UNAVAILABLE = "unavailable"
ERROR_CLASS_UNEXPECTED = "unexpected"


def error_class_for_status(http_status: Optional[int]) -> str:
    """Map a provider HTTP status to its stable error class.

    Args:
        http_status: The status the provider answered with, or ``None`` when the request never
            got an answer (DNS, connect, TLS or timeout failure).

    Returns:
        ``auth`` for 401/403, ``not-found`` for 404, ``rate-limited`` for 429, ``unavailable``
        for 5xx and for no answer at all, and ``unexpected`` for anything else.
    """
    if http_status is None:
        return ERROR_CLASS_UNAVAILABLE
    if http_status in (401, 403):
        return ERROR_CLASS_AUTH
    if http_status == 404:
        return ERROR_CLASS_NOT_FOUND
    if http_status == 429:
        return ERROR_CLASS_RATE_LIMITED
    if 500 <= http_status <= 599:
        return ERROR_CLASS_UNAVAILABLE
    return ERROR_CLASS_UNEXPECTED


class RefreshSourceError(RuntimeError):
    """A source could not list or fetch because the provider refused or failed.

    Attributes:
        error_class: A stable class (see ``ERROR_CLASS_*``); derived from ``http_status`` when
            not given.
        http_status: The provider's HTTP status, or ``None`` when there was no answer.
    """

    def __init__(
        self,
        message: str,
        *,
        http_status: Optional[int] = None,
        error_class: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.error_class = error_class or error_class_for_status(http_status)


@dataclass(frozen=True)
class RefreshCandidate:
    """One thing a source holds that may need refreshing.

    Attributes:
        remote_id: The source's stable id for it (a file path, a gateway service id).
        name: A display name, when the source has one.
        revision: The source's revision marker (a commit SHA, a gateway revision), if any.
        updated_at: When the source says it last changed, if it says.
        environment: The deployment environment it was found in (connectors only).
        hosts: Host names it is served on (connectors only).
        base_path: The path prefix it is served under (connectors only).
        raw: The source-specific row behind the candidate (the Git candidate row, the
            provider's inventory entry). Never contains credentials.
        deployment: Where and how the provider serves it (connectors only; CDG-1.2): for
            example the control plane, tags, protocols, paths and suggested owners. Stored on
            the inventory row as given. Never contains credentials.
    """

    remote_id: str
    name: Optional[str] = None
    revision: Optional[str] = None
    updated_at: Optional[datetime] = None
    environment: Optional[str] = None
    hosts: Tuple[str, ...] = ()
    base_path: Optional[str] = None
    raw: Mapping[str, Any] = field(default_factory=dict)
    deployment: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FreshnessKey:
    """The RAR-2.2 freshness signals for one candidate.

    Attributes:
        remote_updated_at: When the remote last changed (commit time, update time).
        remote_checksum: The remote's content identity (blob SHA, revision, digest).
        last_updated_at: The stored ``remote_updated_at`` at the last import.
        last_checksum: The stored content identity at the last import.
    """

    remote_updated_at: Any = None
    remote_checksum: Optional[str] = None
    last_updated_at: Any = None
    last_checksum: Optional[str] = None


@dataclass(frozen=True)
class FetchedDocument:
    """A document a connector source fetched for one candidate.

    Attributes:
        content: The document bytes, exactly as the provider served them.
        filename: A file name for the import (it labels the source and hints the format).
        import_kind: The import-source key to parse it with (``openapi``, ``graphql``, ...).
        revision: The revision the content belongs to, when the provider says.
        source_uri: A link to the document at the provider, when one exists.
    """

    content: bytes
    filename: str
    import_kind: str = "openapi"
    revision: Optional[str] = None
    source_uri: Optional[str] = None


@dataclass(frozen=True)
class RefreshJobRequest:
    """What refreshing one Git file means: the spec-faithful re-import job to enqueue.

    Attributes:
        fields: Keyword arguments for ``Database.enqueue_repository_refresh_job``, a snapshot
            of the stored import spec plus the remote freshness signals (RAR-3.2/4.1).
    """

    fields: Dict[str, Any]


#: What :meth:`RefreshSource.fetch` returns: a job to enqueue (Git) or a document (connector).
RefreshFetch = Union[RefreshJobRequest, FetchedDocument]


@runtime_checkable
class RefreshSource(Protocol):
    """A source the refresh engine can sync (a Git branch, a catalog connector)."""

    def list_candidates(self) -> Sequence[RefreshCandidate]:
        """Return everything the source currently holds.

        Raises:
            RefreshSourceError: When the provider refuses or fails.
        """
        ...

    def freshness_key(self, candidate: RefreshCandidate) -> FreshnessKey:
        """Return the remote and last-imported freshness signals for ``candidate``."""
        ...

    def fetch(self, candidate: RefreshCandidate) -> RefreshFetch:
        """Return what refreshing ``candidate`` needs.

        Raises:
            RefreshSourceError: When the provider refuses or fails.
        """
        ...

    def describe(self) -> Dict[str, Any]:
        """Return a credential-free description of the source (kind and identifiers)."""
        ...


def decide_refresh(source: RefreshSource, candidate: RefreshCandidate) -> RefreshDecision:
    """Apply the RAR-2.2 newer-than gate to one candidate of any source.

    Args:
        source: The source the candidate came from.
        candidate: The candidate to judge.

    Returns:
        The :class:`~app.repository_refresh_comparator.RefreshDecision` for it.
    """
    key = source.freshness_key(candidate)
    return evaluate_refresh(
        remote_committed_at=key.remote_updated_at,
        last_imported_committed_at=key.last_updated_at,
        remote_checksum=key.remote_checksum,
        last_imported_checksum=key.last_checksum,
    )


class GitBranchRefreshSource:
    """One branch of a tenant repository, as a :class:`RefreshSource` (RAR-3.2 behaviour).

    Candidates are the branch's files that have a stored import spec. Listing them rescans the
    branch first (REPO-2 walker), so the candidate query sees current remote signals; on a large
    monorepo the walk is bounded (REPO-2.5) and a pass that runs out of time resumes next tick.

    Args:
        db: Database handle.
        repo_row: The repository row (from ``get_tenant_repository``).
        branch: The branch to rescan and evaluate.
        path_filter: When set, only the file at this repository-relative path is a candidate
            (per-file "Refresh Now").
    """

    def __init__(
        self,
        db: Any,
        repo_row: Mapping[str, Any],
        branch: str,
        *,
        path_filter: Optional[str] = None,
    ) -> None:
        self._db = db
        self._repo_row = repo_row
        self._branch = branch
        self._path_filter = path_filter
        self.repository_id = str(repo_row["id"])
        self.tenant_id = str(repo_row["tenant_id"])

    def list_candidates(self) -> List[RefreshCandidate]:
        """Rescan the branch and return its files that have a stored import spec."""
        # Imported here so tests can patch the walker on this module's import site.
        from . import repository_refresh_sweep as sweep

        scan = sweep.scan_repository_branch_into_index(self._db, self._repo_row, self._branch)
        if not scan.completed:
            _logger.info(
                "repository refresh evaluating a partially indexed branch (scan resumes next tick) "
                "repository_id=%s branch=%s files_so_far=%s",
                self.repository_id,
                self._branch,
                scan.total_files,
            )
        candidates: List[RefreshCandidate] = []
        for row in self._db.list_repository_refresh_candidates(self.repository_id, self._branch):
            path = str(row.get("path"))
            if self._path_filter is not None and path != self._path_filter:
                continue
            candidates.append(
                RefreshCandidate(
                    remote_id=path,
                    revision=row.get("remote_commit_sha"),
                    updated_at=row.get("remote_committed_at"),
                    raw=row,
                )
            )
        return candidates

    def freshness_key(self, candidate: RefreshCandidate) -> FreshnessKey:
        """Branch-tip commit time and blob SHA, against the stored import anchor."""
        row = candidate.raw
        return FreshnessKey(
            remote_updated_at=row.get("remote_committed_at"),
            remote_checksum=row.get("remote_blob_sha"),
            last_updated_at=row.get("last_imported_committed_at"),
            last_checksum=row.get("last_imported_blob_sha"),
        )

    def fetch(self, candidate: RefreshCandidate) -> RefreshJobRequest:
        """Return the spec-faithful re-import job for one stale file.

        The Git source does not download content here: the job snapshots the stored import
        spec and the EPIC-4 executor downloads the file when it replays the import (RAR-4.1).
        """
        cand = candidate.raw
        decision = decide_refresh(self, candidate)
        return RefreshJobRequest(
            fields={
                "tenant_id": self.tenant_id,
                "repository_id": self.repository_id,
                "branch": self._branch,
                "path": str(cand["path"]),
                "import_spec_id": cand.get("import_spec_id"),
                "project_id": cand.get("project_id"),
                "source_kind": cand.get("source_kind"),
                "format_override": cand.get("format_override"),
                "content_type": cand.get("content_type"),
                "options_json": cand.get("options_json"),
                "spec_schema_version": int(cand.get("spec_schema_version") or 1),
                "created_by": cand.get("created_by"),
                "remote_commit_sha": cand.get("remote_commit_sha"),
                "remote_committed_at": cand.get("remote_committed_at"),
                "remote_blob_sha": cand.get("remote_blob_sha"),
                "refresh_reason": decision.reason.value,
            }
        )

    def describe(self) -> Dict[str, Any]:
        """``{kind: "git", repositoryId, branch}``."""
        return {"kind": "git", "repositoryId": self.repository_id, "branch": self._branch}
