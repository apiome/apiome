"""Branch-to-draft binding store — GNC-2.1 (#4737).

The rules between the HTTP surface (:mod:`app.draft_binding_routes`) and storage (apiome-db V264):

* **Scope.** Every read and write resolves the project inside the caller's tenant first (the same
  resolution comment threads and reviews use), and every binding is read back through that project,
  so an id from another tenant or project is simply "not found".
* **Only drafts.** A version can be bound only while it is unpublished (``binding-version-published``).
  Releasing and reading stay possible after a publish, because a binding is evidence.
* **One active binding per draft** (``binding-already-bound``); re-binding is release-then-bind, and
  the released row stays as history. V264's partial unique index backs it.
* **Authorization is a proven read, not a claim.** Binding resolves a **stored** credential — a
  registered tenant repository's linked account, or the caller's own — and then actually reads the
  ref and the selection through the provider (:func:`app.git_intake.fetch_git_fileset`). A
  repository the credential cannot reach is refused before any row is written; no token is ever
  accepted from the request. The read is also what produces the commit and the
  :func:`app.draft_bindings.source_digest` the binding stores.
* **A ref update never rewrites a draft.** Movement is recorded as a pending **sync candidate**
  (:func:`record_ref_update` from a provider delivery, :func:`check_for_updates` from a person).
  Settling one is explicit: ``applied`` advances the binding's synchronized pair to the new commit
  — and re-reads the source to do it, so the stored digest always describes content that was really
  read — while ``dismissed`` leaves the binding where it is.
* **Races.** Each write re-checks its guard under a row lock; when it loses, the binding is read
  again and the refusal names what changed.

Refusals raise :class:`app.draft_bindings.DraftBindingValidationError` with a stable code. The audit
rows for every bind, release, candidate, and resolution are written by the database accessors, in
the same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from fastapi import HTTPException

from . import comment_store
from .comments import CommentValidationError
from .database import db
from .draft_bindings import (
    CODE_ALREADY_BOUND,
    CODE_CANDIDATE_NOT_FOUND,
    CODE_CANDIDATE_RESOLVED,
    CODE_CONFLICT,
    CODE_INVALID_SOURCE,
    CODE_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_RELEASED,
    CODE_REPOSITORY_FORBIDDEN,
    CODE_REPOSITORY_NOT_FOUND,
    CODE_REPOSITORY_UNREACHABLE,
    CODE_UNCHANGED,
    CODE_VERSION_NOT_FOUND,
    CODE_VERSION_PUBLISHED,
    ORIGIN_MANUAL,
    ORIGIN_WEBHOOK,
    RELEASE_REASON_UNBOUND,
    STATUS_APPLIED,
    DraftBindingCreate,
    DraftBindingDetail,
    DraftBindingRecord,
    DraftBindingValidationError,
    SyncCandidateRecord,
    SyncCandidateResolve,
    VersionBindingStatus,
    browse_url,
    normalize_path,
    normalize_ref,
    normalize_repo_full_name,
    source_digest,
)
from .git_intake import GitIntakeError, GitSelector, fetch_git_fileset

__all__ = [
    "BindingFilters",
    "ResolvedSource",
    "bind_draft",
    "check_for_updates",
    "get_binding",
    "list_bindings",
    "read_source",
    "record_ref_update",
    "release_binding",
    "resolve_candidate",
    "resolve_project",
    "resolve_version",
    "version_binding_status",
]

#: How many settled candidates a binding detail carries. A binding accumulates one per push to its
#: ref, and the panel shows a recent trail, not the whole life of the branch.
CANDIDATE_HISTORY_LIMIT = 50

#: Git-intake taxonomy code -> binding refusal code. Anything unlisted is an invalid selection,
#: which is the caller's to fix.
_INTAKE_CODE_MAP: Dict[str, str] = {
    "SOURCE_NOT_FOUND": CODE_REPOSITORY_NOT_FOUND,
    "SOURCE_AUTH_REQUIRED": CODE_REPOSITORY_FORBIDDEN,
    "SOURCE_UNREACHABLE": CODE_REPOSITORY_UNREACHABLE,
}

#: Columns of a binding row that belong on :class:`DraftBindingRecord`.
_BINDING_FIELDS = tuple(DraftBindingRecord.model_fields)

#: Columns of a candidate row that belong on :class:`SyncCandidateRecord`.
_CANDIDATE_FIELDS = tuple(SyncCandidateRecord.model_fields)


@dataclass(frozen=True)
class BindingFilters:
    """What a binding list read narrows to.

    Attributes:
        version: Only bindings of this version (revision id or version label).
        active: ``True`` for active bindings only, ``False`` for released ones only, ``None`` for
            both.
        limit: Page size.
        offset: Bindings to skip.
    """

    version: Optional[str] = None
    active: Optional[bool] = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class ResolvedSource:
    """One proven read of a repository selection.

    Attributes:
        provider: The provider key the read went through.
        repo_url: The canonical repository URL.
        repo_full_name: Lowercased ``owner/name``.
        ref: The short ref that was resolved.
        commit_sha: The commit the ref pointed at.
        digest: :func:`app.draft_bindings.source_digest` of the selection at that commit.
        member_count: How many files the selection resolved to.
    """

    provider: str
    repo_url: str
    repo_full_name: str
    ref: str
    commit_sha: str
    digest: str
    member_count: int


# ---------------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------------


def resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id to its row, within the tenant.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        DraftBindingValidationError: ``binding-project-not-found`` when nothing matches.
    """
    try:
        return comment_store.resolve_project(tenant_id, project_ref)
    except CommentValidationError as exc:
        raise DraftBindingValidationError(CODE_PROJECT_NOT_FOUND, str(exc)) from exc


def resolve_version(tenant_id: str, project_id: str, version_ref: str) -> Dict[str, Any]:
    """Resolve a revision id or version label to a version of the project.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project the version must belong to.
        version_ref: A revision UUID or a version label such as ``1.0.0``.

    Returns:
        The version row.

    Raises:
        DraftBindingValidationError: ``binding-version-not-found`` when nothing in the project
            matches.
    """
    try:
        return comment_store.resolve_version(tenant_id, project_id, version_ref)
    except CommentValidationError as exc:
        raise DraftBindingValidationError(CODE_VERSION_NOT_FOUND, str(exc)) from exc


def _stored_token(
    tenant_id: str,
    user_id: str,
    *,
    repository_id: Optional[str],
    linked_account_id: Optional[str],
) -> Optional[str]:
    """Resolve the stored credential a repository read is authorized by.

    Reuses the import path's vault lookup (:func:`app.git_import_routes.resolve_stored_git_token`)
    rather than opening a second credential path: a binding must be readable by exactly what an
    import of the same file would be readable by.

    Args:
        tenant_id: The caller's tenant.
        user_id: The acting user; a linked account is only usable by its owner.
        repository_id: Registered repository to borrow credentials from, if any.
        linked_account_id: The user's own linked account, if any.

    Returns:
        The access token, or ``None`` when the read must be anonymous.

    Raises:
        DraftBindingValidationError: ``binding-repository-not-found`` when the named repository is
            not this tenant's.
    """
    from .git_import_routes import resolve_stored_git_token

    try:
        return resolve_stored_git_token(
            tenant_id,
            user_id,
            repository_id=repository_id,
            linked_account_id=linked_account_id,
        )
    except HTTPException as exc:
        raise DraftBindingValidationError(
            CODE_REPOSITORY_NOT_FOUND, "Repository not found for this tenant."
        ) from exc


def _repository_coordinates(
    tenant_id: str, request: DraftBindingCreate
) -> Tuple[Optional[str], str, Optional[str]]:
    """Work out which repository a bind request names.

    Args:
        tenant_id: The caller's tenant.
        request: The bind request.

    Returns:
        ``(repository_id, repo_url, default_branch)``. The default branch is the registration's,
        when there is one; ``None`` lets the provider decide.

    Raises:
        DraftBindingValidationError: ``binding-repository-not-found`` when the registered
            repository is not this tenant's, ``binding-invalid-source`` when neither a registered
            repository nor a URL was given.
    """
    if request.repository_id:
        row = db.get_tenant_repository(tenant_id, str(request.repository_id))
        if not row:
            raise DraftBindingValidationError(
                CODE_REPOSITORY_NOT_FOUND, "Repository not found for this tenant."
            )
        return (
            str(row["id"]),
            str(row.get("clone_url") or ""),
            (str(row["default_branch"]) if row.get("default_branch") else None),
        )
    url = (request.repo_url or "").strip()
    if not url:
        raise DraftBindingValidationError(
            CODE_INVALID_SOURCE,
            "Name either a registered repository (repository_id) or a repository URL (repo_url).",
        )
    return None, url, None


def read_source(
    tenant_id: str,
    user_id: str,
    *,
    repo_url: str,
    ref: Optional[str],
    path: str,
    repository_id: Optional[str] = None,
    linked_account_id: Optional[str] = None,
) -> ResolvedSource:
    """Read a repository selection through a stored credential — the authorization check.

    This is what "binding authorization verifies repository access" means in practice: the ref is
    resolved and the selection downloaded before anything is stored, so a repository the tenant
    cannot actually read can never be bound, and the digest written alongside describes content
    that was really fetched.

    Args:
        tenant_id: The caller's tenant.
        user_id: The acting user.
        repo_url: Repository URL.
        ref: Branch or tag; ``None`` uses the repository's default branch.
        path: Path or glob selecting the source.
        repository_id: Registered repository whose stored credential authorizes the read.
        linked_account_id: The caller's own linked account, when no registration is used.

    Returns:
        The proven read.

    Raises:
        DraftBindingValidationError: With the refusal the provider's answer maps to.
    """
    token = _stored_token(
        tenant_id,
        user_id,
        repository_id=repository_id,
        linked_account_id=linked_account_id,
    )
    selector = GitSelector(repo_url=repo_url, ref=(ref or None), path=normalize_path(path))
    try:
        result = fetch_git_fileset(selector, access_token=token, require_root=False)
    except GitIntakeError as exc:
        code = _INTAKE_CODE_MAP.get(getattr(exc, "code", ""), CODE_INVALID_SOURCE)
        raise DraftBindingValidationError(code, str(exc)) from exc

    provenance = result.provenance
    return ResolvedSource(
        provider=provenance.provider,
        repo_url=provenance.repo_url,
        repo_full_name=normalize_repo_full_name(provenance.owner, provenance.repo),
        ref=normalize_ref(provenance.ref),
        commit_sha=provenance.commit_sha,
        digest=source_digest(result.members),
        member_count=len(result.members),
    )


# ---------------------------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------------------------


def _binding_record(row: Mapping[str, Any]) -> DraftBindingRecord:
    """Map a binding row onto its record, adding the browse URL the row does not store.

    Args:
        row: A row from a binding read.

    Returns:
        The record.
    """
    values = {name: row.get(name) for name in _BINDING_FIELDS if name in row}
    values["browse_url"] = browse_url(
        str(row.get("provider") or ""),
        str(row.get("repo_url") or ""),
        str(row.get("commit_sha") or ""),
        str(row.get("path") or ""),
    )
    return DraftBindingRecord(**values)


def _candidate_record(row: Mapping[str, Any]) -> SyncCandidateRecord:
    """Map a sync-candidate row onto its record.

    Args:
        row: A row from a candidate read.

    Returns:
        The record.
    """
    return SyncCandidateRecord(**{name: row.get(name) for name in _CANDIDATE_FIELDS if name in row})


def _detail(row: Mapping[str, Any]) -> DraftBindingDetail:
    """Build a binding detail: the binding, what is outstanding, and what has settled.

    Args:
        row: A binding row.

    Returns:
        The detail.
    """
    binding_id = str(row["id"])
    tenant_id = str(row["tenant_id"])
    pending = db.list_binding_sync_candidates(
        tenant_id=tenant_id, binding_id=binding_id, pending_only=True, limit=CANDIDATE_HISTORY_LIMIT
    )
    history = db.list_binding_sync_candidates(
        tenant_id=tenant_id,
        binding_id=binding_id,
        pending_only=False,
        limit=CANDIDATE_HISTORY_LIMIT,
    )
    return DraftBindingDetail(
        binding=_binding_record(row),
        pending=[_candidate_record(item) for item in pending],
        history=[_candidate_record(item) for item in history],
    )


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def get_binding(tenant_id: str, project_ref: str, binding_id: str) -> DraftBindingDetail:
    """Read one binding of a project.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        binding_id: The binding.

    Returns:
        The binding with its candidates.

    Raises:
        DraftBindingValidationError: ``binding-project-not-found`` or ``binding-not-found``.
    """
    project = resolve_project(tenant_id, project_ref)
    row = db.get_draft_binding(
        tenant_id=tenant_id, project_id=str(project["id"]), binding_id=binding_id
    )
    if not row:
        raise DraftBindingValidationError(CODE_NOT_FOUND, f"no binding '{binding_id}' in this project")
    return _detail(row)


def list_bindings(
    tenant_id: str, project_ref: str, filters: BindingFilters
) -> Tuple[List[DraftBindingRecord], int]:
    """List a project's bindings, active and released.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        filters: What to narrow to and how to page.

    Returns:
        ``(page, total)``.

    Raises:
        DraftBindingValidationError: ``binding-project-not-found``, or ``binding-version-not-found``
            when the version filter names nothing in the project.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version_id: Optional[str] = None
    if filters.version:
        version_id = str(resolve_version(tenant_id, project_id, filters.version)["id"])
    rows = db.list_draft_bindings(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_id,
        active=filters.active,
        limit=filters.limit,
        offset=filters.offset,
    )
    total = db.count_draft_bindings(
        tenant_id=tenant_id, project_id=project_id, version_id=version_id, active=filters.active
    )
    return [_binding_record(row) for row in rows], total


def version_binding_status(
    tenant_id: str, project_ref: str, version_ref: str
) -> VersionBindingStatus:
    """Read where one version stands with respect to a repository.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.

    Returns:
        The status: the active binding with its candidates, and the bindings it has had before.

    Raises:
        DraftBindingValidationError: ``binding-project-not-found`` or ``binding-version-not-found``.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, version_ref)
    version_id = str(version["id"])
    active = db.get_active_draft_binding(
        tenant_id=tenant_id, project_id=project_id, version_id=version_id
    )
    released = db.list_draft_bindings(
        tenant_id=tenant_id, project_id=project_id, version_id=version_id, active=False, limit=50
    )
    return VersionBindingStatus(
        version_id=version_id,
        version_label=version.get("version_id"),
        published=bool(version.get("published")),
        bound=bool(active),
        binding=(_detail(active) if active else None),
        released=[_binding_record(row) for row in released],
    )


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


def _require_active_binding(
    tenant_id: str, project_id: str, version_id: str
) -> Dict[str, Any]:
    """Read the version's active binding or refuse.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        version_id: The version.

    Returns:
        The active binding row.

    Raises:
        DraftBindingValidationError: ``binding-not-found`` when the version is not bound.
    """
    row = db.get_active_draft_binding(
        tenant_id=tenant_id, project_id=project_id, version_id=version_id
    )
    if not row:
        raise DraftBindingValidationError(CODE_NOT_FOUND, "this version is not bound to a repository")
    return dict(row)


def bind_draft(
    tenant_id: str,
    project_ref: str,
    version_ref: str,
    actor_id: str,
    request: DraftBindingCreate,
) -> DraftBindingDetail:
    """Bind a draft version to a repository ref and source path.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        actor_id: The acting user.
        request: What to bind to.

    Returns:
        The new binding.

    Raises:
        DraftBindingValidationError: ``binding-version-published`` for a published version,
            ``binding-already-bound`` when it is already bound and ``replace`` was not asked for,
            a ``binding-repository-*`` refusal when the repository cannot be read, or
            ``binding-conflict`` when a concurrent bind won the race.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, version_ref)
    version_id = str(version["id"])
    if version.get("published"):
        raise DraftBindingValidationError(
            CODE_VERSION_PUBLISHED, "only a draft (unpublished) version can be bound to a branch"
        )

    existing = db.get_active_draft_binding(
        tenant_id=tenant_id, project_id=project_id, version_id=version_id
    )
    if existing and not request.replace:
        raise DraftBindingValidationError(
            CODE_ALREADY_BOUND,
            "this version is already bound; release it first or bind again with replace",
        )

    repository_id, repo_url, default_branch = _repository_coordinates(tenant_id, request)
    source = read_source(
        tenant_id,
        actor_id,
        repo_url=repo_url,
        ref=(normalize_ref(request.ref) or default_branch or None),
        path=request.path,
        repository_id=repository_id,
        linked_account_id=request.linked_account_id,
    )

    produced = db.insert_draft_binding(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_id,
        repository_id=repository_id,
        provider=source.provider,
        repo_full_name=source.repo_full_name,
        repo_url=source.repo_url,
        ref=source.ref,
        path=normalize_path(request.path),
        commit_sha=source.commit_sha,
        source_digest=source.digest,
        created_by=actor_id,
        replace=bool(request.replace),
    )
    if not produced:
        # The guard did not hold under the lock. Read it back so the refusal names what is there.
        current = db.get_active_draft_binding(
            tenant_id=tenant_id, project_id=project_id, version_id=version_id
        )
        if current:
            raise DraftBindingValidationError(
                CODE_ALREADY_BOUND,
                "this version was bound by someone else while this request was in flight",
            )
        raise DraftBindingValidationError(
            CODE_CONFLICT, "the binding changed while this request was in flight; try again"
        )

    row = db.get_draft_binding(
        tenant_id=tenant_id, project_id=project_id, binding_id=str(produced["binding_id"])
    )
    if not row:  # pragma: no cover - the insert committed, so the read cannot miss
        raise DraftBindingValidationError(CODE_CONFLICT, "the new binding could not be read back")
    return _detail(row)


def release_binding(
    tenant_id: str, project_ref: str, version_ref: str, actor_id: str
) -> DraftBindingRecord:
    """Release a version's active binding, keeping it as history.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        actor_id: The acting user.

    Returns:
        The released binding.

    Raises:
        DraftBindingValidationError: ``binding-not-found`` when the version is not bound, or
            ``binding-conflict`` when it was released concurrently.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, version_ref)
    binding = _require_active_binding(tenant_id, project_id, str(version["id"]))
    binding_id = str(binding["id"])
    released = db.release_draft_binding(
        tenant_id=tenant_id,
        project_id=project_id,
        binding_id=binding_id,
        actor_id=actor_id,
        reason=RELEASE_REASON_UNBOUND,
    )
    if not released:
        raise DraftBindingValidationError(
            CODE_CONFLICT, "the binding was released while this request was in flight"
        )
    row = db.get_draft_binding(
        tenant_id=tenant_id, project_id=project_id, binding_id=binding_id
    )
    if not row:  # pragma: no cover - the update committed, so the read cannot miss
        raise DraftBindingValidationError(CODE_CONFLICT, "the released binding could not be read back")
    return _binding_record(row)


def check_for_updates(
    tenant_id: str, project_ref: str, version_ref: str, actor_id: str
) -> DraftBindingDetail:
    """Ask the provider where the bound ref is now, raising a candidate when it has moved.

    The same read that answers the question is the authorization check: a binding whose repository
    the caller can no longer reach refuses here rather than silently reporting "no change".

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        actor_id: The acting user.

    Returns:
        The binding, now carrying the candidate this check raised.

    Raises:
        DraftBindingValidationError: ``binding-not-found`` when the version is not bound,
            ``binding-unchanged`` when the ref is exactly where the binding already is, or a
            ``binding-repository-*`` refusal when the repository cannot be read.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, version_ref)
    binding = _require_active_binding(tenant_id, project_id, str(version["id"]))
    binding_id = str(binding["id"])

    source = read_source(
        tenant_id,
        actor_id,
        repo_url=str(binding["repo_url"]),
        ref=str(binding["ref"]),
        path=str(binding["path"] or ""),
        repository_id=(str(binding["repository_id"]) if binding.get("repository_id") else None),
    )
    if source.commit_sha == str(binding["commit_sha"]):
        raise DraftBindingValidationError(
            CODE_UNCHANGED,
            f"{binding['ref']} is still at {source.commit_sha[:7]}; there is nothing to synchronize",
        )

    db.raise_binding_sync_candidate(
        tenant_id=tenant_id,
        binding_id=binding_id,
        to_commit_sha=source.commit_sha,
        origin=ORIGIN_MANUAL,
        detected_by=actor_id,
        to_digest=source.digest,
    )
    row = db.get_draft_binding(tenant_id=tenant_id, project_id=project_id, binding_id=binding_id)
    if not row:  # pragma: no cover - the binding was read moments ago
        raise DraftBindingValidationError(CODE_CONFLICT, "the binding could not be read back")
    return _detail(row)


def resolve_candidate(
    tenant_id: str,
    project_ref: str,
    version_ref: str,
    candidate_id: str,
    actor_id: str,
    request: SyncCandidateResolve,
) -> DraftBindingDetail:
    """Settle one outstanding sync candidate of a version's binding.

    Applying re-reads the source at the candidate's commit before advancing the binding, so the
    digest it records is never asserted from a delivery payload — a candidate whose commit has
    since been force-pushed away, or whose repository the caller can no longer read, refuses
    instead of writing a digest nobody verified.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        candidate_id: The candidate.
        actor_id: The acting user.
        request: ``applied`` or ``dismissed``, with an optional note.

    Returns:
        The binding, with the candidate now settled.

    Raises:
        DraftBindingValidationError: ``binding-not-found``, ``binding-candidate-not-found``,
            ``binding-candidate-resolved`` when it already settled, or a ``binding-repository-*``
            refusal when applying could not read the source.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, version_ref)
    binding = _require_active_binding(tenant_id, project_id, str(version["id"]))
    binding_id = str(binding["id"])

    candidate = db.get_binding_sync_candidate(
        tenant_id=tenant_id, binding_id=binding_id, candidate_id=candidate_id
    )
    if not candidate:
        raise DraftBindingValidationError(
            CODE_CANDIDATE_NOT_FOUND, f"no sync candidate '{candidate_id}' on this binding"
        )
    if str(candidate["status"]) != "pending":
        raise DraftBindingValidationError(
            CODE_CANDIDATE_RESOLVED,
            f"this candidate is already {candidate['status']}; settlements are final",
        )

    to_digest: Optional[str] = None
    if request.status == STATUS_APPLIED:
        source = read_source(
            tenant_id,
            actor_id,
            repo_url=str(binding["repo_url"]),
            ref=str(candidate["to_commit_sha"]),
            path=str(binding["path"] or ""),
            repository_id=(str(binding["repository_id"]) if binding.get("repository_id") else None),
        )
        to_digest = source.digest

    settled = db.resolve_binding_sync_candidate(
        tenant_id=tenant_id,
        project_id=project_id,
        binding_id=binding_id,
        candidate_id=candidate_id,
        status=request.status,
        actor_id=actor_id,
        note=request.note,
        to_digest=to_digest,
    )
    if not settled:
        raise DraftBindingValidationError(
            CODE_CONFLICT, "the candidate was settled while this request was in flight"
        )
    row = db.get_draft_binding(tenant_id=tenant_id, project_id=project_id, binding_id=binding_id)
    if not row:  # pragma: no cover - the binding was read moments ago
        raise DraftBindingValidationError(CODE_RELEASED, "the binding could not be read back")
    return _detail(row)


# ---------------------------------------------------------------------------------------------
# Provider-driven updates
# ---------------------------------------------------------------------------------------------


def record_ref_update(
    db_handle: Any,
    *,
    repository_id: str,
    ref: str,
    to_commit_sha: str,
    delivery_id: Optional[str] = None,
) -> int:
    """Raise a sync candidate on every active binding of a repository ref.

    Called from the provider webhook path (:mod:`app.repository_webhook_dispatch`), which owns no
    user identity and no credential — so the candidate names the commit the delivery reported and
    leaves ``to_digest`` unread until somebody applies or checks it. Nothing about any draft
    changes here; that is the whole point of a candidate.

    The database handle is a parameter rather than this module's ``db`` because the ingestion path
    is driven against a double in its tests, exactly as the rest of that module is.

    Args:
        db_handle: The database handle to use.
        repository_id: The registered repository the delivery resolved to.
        ref: The ref the delivery was about, in any spelling (``refs/heads/main`` or ``main``).
        to_commit_sha: The commit the ref now points at.
        delivery_id: The provider delivery id, so a redelivery raises nothing new.

    Returns:
        How many candidates were raised. Zero is the common case: no draft is bound to that ref.
    """
    short_ref = normalize_ref(ref)
    head = (to_commit_sha or "").strip()
    if not short_ref or not head:
        return 0
    bindings = db_handle.find_active_bindings_for_repository_ref(
        repository_id=str(repository_id), ref=short_ref
    )
    raised = 0
    for binding in bindings or []:
        produced = db_handle.raise_binding_sync_candidate(
            tenant_id=str(binding["tenant_id"]),
            binding_id=str(binding["id"]),
            to_commit_sha=head,
            origin=ORIGIN_WEBHOOK,
            delivery_id=delivery_id,
        )
        if produced:
            raised += 1
    return raised
