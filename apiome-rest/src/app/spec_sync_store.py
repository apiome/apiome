"""Three-way spec synchronization store — GNC-2.3 (#4739).

The rules between the HTTP surface (:mod:`app.spec_sync_routes`) and storage (apiome-db V266):

* **Scope.** Every read and write resolves the project inside the caller's tenant first and reads
  the version's *active* binding through it, so an id from another tenant or project is simply "not
  found". The binding is the authorization: GNC-2.1 wrote it only after proving a stored credential
  could read the repository.
* **Three proven reads, never a payload.** A merge needs three documents. Two come from the
  provider — the selection at the binding's synchronized commit (the base) and at the commit the
  ref moved to — and both are fetched here through
  :func:`app.draft_binding_store.read_source_fileset`, the same credential-resolving read binding
  uses. The third is rebuilt from the canonical model. A delivery's assertion about what a commit
  contains is never believed.
* **The base must still be the base.** If the selection at the binding's synchronized commit no
  longer hashes to the digest the binding recorded, history was rewritten underneath the merge
  base, and every "who changed this" answer computed from it would be a guess. That refuses with
  ``sync-base-drifted`` rather than merging against something nobody agreed to.
* **Nothing is written to the draft. Ever.** There is no code path from here to the canonical
  model, to ``versions``, or to a review. A merge result is a row a person reads; what a person
  then does about it is their decision, made somewhere else. That is what makes it safe for a
  webhook to raise a candidate and for anyone to compute a merge for it.
* **Reruns are free, not just idempotent.** The rerun key
  (:func:`app.spec_sync.plan_fingerprint`) is computable from the binding, the two commits and the
  draft's content digest — all known before any network call — so an unchanged trio is answered
  from storage without fetching two commits again.
* **Guards are recorded, not enforced by refusing.** A merge against a version whose review already
  holds a decision, or which has since been published, still computes: knowing *what* would
  collide is exactly what such a reader needs. The result carries the guard that says it may not be
  turned into an edit.

Refusals raise :class:`app.spec_sync.SpecSyncValidationError` with a stable code, except the
repository-read refusals, which stay :class:`app.draft_bindings.DraftBindingValidationError` with
their ``binding-repository-*`` codes — the same answer the binding endpoints already give for the
same failure, so a client learns one vocabulary for "the repository could not be read".
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import draft_binding_store
from .compatibility_engine import openapi_for_revision
from .database import db
from .draft_bindings import CODE_INVALID_SOURCE, DraftBindingValidationError
from .import_ingestion import IngestionError, parse_document
from .intake_resource_guard import IntakeLimitError
from .review_lifecycle import DECISION_PENDING
from .spec_sync import (
    CODE_BASE_DRIFTED,
    CODE_CONFLICT,
    CODE_CONFLICT_NOT_FOUND,
    CODE_CONFLICT_RESOLVED,
    CODE_INVALID_DOCUMENT,
    CODE_NOT_BOUND,
    CODE_NOTHING_TO_MERGE,
    CODE_PLAN_NOT_FOUND,
    GUARD_NONE,
    GUARD_REVIEW_DECIDED,
    GUARD_VERSION_PUBLISHED,
    MergeOutcome,
    SpecSyncValidationError,
    SyncConflictRecord,
    SyncConflictResolve,
    SyncPlanCompute,
    SyncPlanDetail,
    SyncPlanRecord,
    VersionSyncStatus,
    bounded_value,
    locate_pointer_lines,
    merge_documents,
    plan_fingerprint,
    source_location_url,
)
from .version_quality_capture import openapi_source_fingerprint

__all__ = [
    "compute_plan",
    "get_plan",
    "read_draft_document",
    "resolve_conflict",
    "version_sync_status",
]

#: How many merge results a version's status carries behind the newest one.
PLAN_HISTORY_LIMIT = 20

#: How many outstanding candidates are looked at to pick the oldest one to merge. A binding with
#: more than this many unmerged movements has a bigger problem than which one to start with.
PENDING_SCAN_LIMIT = 50

#: The tenant slug the draft document is rebuilt under. The generated document does not depend on
#: it, and a constant keeps the digest independent of the URL a caller used — the same reasoning
#: (and the same value) as :mod:`app.review_store`'s fingerprint.
_DOCUMENT_TENANT_SLUG = "tenant"

#: Columns of a plan row that belong on :class:`app.spec_sync.SyncPlanRecord`.
_PLAN_FIELDS = tuple(SyncPlanRecord.model_fields)

#: Columns of a conflict row that belong on :class:`app.spec_sync.SyncConflictRecord`.
_CONFLICT_FIELDS = tuple(SyncConflictRecord.model_fields)


# ---------------------------------------------------------------------------------------------
# The three documents
# ---------------------------------------------------------------------------------------------


def read_draft_document(tenant_id: str, version: Mapping[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Rebuild a version's document and fingerprint it.

    The document is rebuilt exactly as lint freshness, the compatibility engine and review
    fingerprints rebuild it, so "the draft changed" means the same thing everywhere in the product.
    Both are produced by one rebuild: doing it twice would double the query cost of every merge.

    Args:
        tenant_id: The caller's tenant.
        version: The version row.

    Returns:
        ``(document, "sha256:…")``.
    """
    document = openapi_for_revision(dict(version), _DOCUMENT_TENANT_SLUG, tenant_id)
    return document, openapi_source_fingerprint(document)


def _read_repository_document(
    tenant_id: str,
    actor_id: str,
    binding: Mapping[str, Any],
    commit_sha: str,
) -> Tuple[Dict[str, Any], str, str, str, Dict[str, int], int]:
    """Read the bound selection at one commit and parse its root document.

    Args:
        tenant_id: The caller's tenant.
        actor_id: The acting user, whose stored credential authorizes the read.
        binding: The active binding row.
        commit_sha: The commit to read at.

    Returns:
        ``(document, digest, repository-relative root path, root text, pointer lines, members)``.

    Raises:
        DraftBindingValidationError: When the repository could not be read.
        SpecSyncValidationError: ``sync-invalid-document`` when the selection holds no readable
            spec document.
    """
    try:
        resolved, fileset = draft_binding_store.read_source_fileset(
            tenant_id,
            actor_id,
            repo_url=str(binding["repo_url"]),
            ref=commit_sha,
            path=str(binding["path"] or ""),
            repository_id=(str(binding["repository_id"]) if binding.get("repository_id") else None),
            require_root=True,
        )
    except DraftBindingValidationError as exc:
        # A selection with no recognisable root document is not an unreachable repository; it is a
        # selection a merge cannot be computed from, and saying so is more useful.
        if exc.code == CODE_INVALID_SOURCE:
            raise SpecSyncValidationError(CODE_INVALID_DOCUMENT, str(exc)) from exc
        raise

    root_key = fileset.root_path
    text = fileset.members.get(root_key, "")
    try:
        document = parse_document(text, source_label=root_key)
    except (IngestionError, IntakeLimitError) as exc:
        raise SpecSyncValidationError(
            CODE_INVALID_DOCUMENT,
            f"the repository's {root_key or 'selection'} could not be read as a spec document: {exc}",
        ) from exc

    repository_path = f"{fileset.member_prefix}{root_key}"
    return (
        document,
        resolved.digest,
        repository_path,
        text,
        locate_pointer_lines(text),
        resolved.member_count,
    )


# ---------------------------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------------------------


def _resolve_scope(
    tenant_id: str, project_ref: str, version_ref: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Resolve the project and version a request is about.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.

    Returns:
        ``(project row, version row)``.

    Raises:
        DraftBindingValidationError: ``binding-project-not-found`` / ``binding-version-not-found``.
    """
    project = draft_binding_store.resolve_project(tenant_id, project_ref)
    version = draft_binding_store.resolve_version(tenant_id, str(project["id"]), version_ref)
    return project, version


def _require_binding(
    tenant_id: str, project_id: str, version_id: str
) -> Dict[str, Any]:
    """Read the version's active binding, refusing in this module's vocabulary.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        version_id: The version.

    Returns:
        The active binding row.

    Raises:
        SpecSyncValidationError: ``sync-not-bound`` when the version has no active binding.
    """
    try:
        return draft_binding_store.require_active_binding(tenant_id, project_id, version_id)
    except DraftBindingValidationError as exc:
        raise SpecSyncValidationError(
            CODE_NOT_BOUND,
            "this version is not bound to a repository, so there is nothing to merge against",
        ) from exc


def _guard_for(tenant_id: str, project_id: str, version: Mapping[str, Any]) -> str:
    """Decide why a merge result may not be turned into an edit of this draft.

    The two answers are both about work that already exists: a version that has been published is
    not a draft any more, and an open review whose current round already holds a decision has
    reviewers who said something about a document a merge would change underneath them.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        version: The version row.

    Returns:
        One of :data:`app.spec_sync.GUARDS`.
    """
    if bool(version.get("published")):
        return GUARD_VERSION_PUBLISHED
    review = db.get_open_review_for_version(
        tenant_id=tenant_id, project_id=project_id, version_id=str(version["id"])
    )
    if review:
        reviewers = db.list_review_reviewers(review_id=str(review["id"])) or []
        current = int(review.get("round") or 1)
        for reviewer in reviewers:
            same_round = int(reviewer.get("round") or current) == current
            if same_round and str(reviewer.get("decision") or DECISION_PENDING) != DECISION_PENDING:
                return GUARD_REVIEW_DECIDED
    return GUARD_NONE


# ---------------------------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------------------------


def _plan_record(row: Mapping[str, Any], *, draft_digest: Optional[str] = None) -> SyncPlanRecord:
    """Map a plan row onto its record, marking it stale when the draft has moved on.

    Args:
        row: The plan row.
        draft_digest: The draft's fingerprint now, when it is known. A plan whose stored digest
            differs describes a document that no longer exists, which is the one thing a reader
            must not act on.

    Returns:
        The record.
    """
    data = {key: row.get(key) for key in _PLAN_FIELDS if key in row}
    data["changes"] = list(row.get("changes") or [])
    data["stale"] = bool(draft_digest) and str(row.get("draft_digest")) != str(draft_digest)
    return SyncPlanRecord.model_validate(data)


def _conflict_record(row: Mapping[str, Any]) -> SyncConflictRecord:
    """Map a conflict row onto its record.

    Args:
        row: The conflict row.

    Returns:
        The record.
    """
    return SyncConflictRecord.model_validate({key: row.get(key) for key in _CONFLICT_FIELDS if key in row})


def _detail(
    tenant_id: str, row: Mapping[str, Any], *, draft_digest: Optional[str] = None
) -> SyncPlanDetail:
    """Assemble a plan with its conflicts.

    Args:
        tenant_id: The caller's tenant.
        row: The plan row.
        draft_digest: The draft's fingerprint now, for the staleness flag.

    Returns:
        The detail.
    """
    conflicts = db.list_draft_sync_conflicts(tenant_id=tenant_id, plan_id=str(row["id"]))
    return SyncPlanDetail(
        plan=_plan_record(row, draft_digest=draft_digest),
        conflicts=[_conflict_record(conflict) for conflict in conflicts],
    )


def _stored_conflicts(
    outcome: MergeOutcome, binding: Mapping[str, Any], commit_sha: str
) -> List[Dict[str, Any]]:
    """Turn merge conflicts into the rows V266 stores, bounding every value.

    Args:
        outcome: The merge result.
        binding: The active binding, for the provider coordinates of the source link.
        commit_sha: The incoming commit the link points at.

    Returns:
        JSON-compatible dicts, one per conflict.
    """
    rows: List[Dict[str, Any]] = []
    for conflict in outcome.conflicts:
        rows.append(
            {
                "pointer": conflict.pointer,
                "scope": conflict.scope,
                "group_key": conflict.group[:255],
                "label": conflict.label,
                "git_kind": conflict.git_kind,
                "draft_kind": conflict.draft_kind,
                "base_value": bounded_value(conflict.base_value),
                "git_value": bounded_value(conflict.git_value),
                "draft_value": bounded_value(conflict.draft_value),
                "source_file": conflict.source_file,
                "source_line": conflict.source_line,
                "source_url": source_location_url(
                    str(binding["provider"]),
                    str(binding["repo_url"]),
                    commit_sha,
                    conflict.source_file,
                    conflict.source_line,
                ),
            }
        )
    return rows


def _stored_changes(outcome: MergeOutcome) -> List[Dict[str, Any]]:
    """Turn applied merge changes into the JSON the plan row carries, bounding every value.

    Args:
        outcome: The merge result.

    Returns:
        JSON-compatible dicts, one per applied change.
    """
    return [
        {
            "pointer": change.pointer,
            "kind": change.kind,
            "scope": change.scope,
            "group": change.group,
            "label": change.label,
            "before": bounded_value(change.before),
            "after": bounded_value(change.after),
            "source_file": change.source_file,
            "source_line": change.source_line,
        }
        for change in outcome.changes
    ]


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def version_sync_status(
    tenant_id: str, project_ref: str, version_ref: str
) -> VersionSyncStatus:
    """Read where a version stands with respect to merging its repository ref.

    No provider is contacted: this is what is already known. The newest merge result comes back
    with its conflicts, and is marked stale when the draft has been edited since it ran.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.

    Returns:
        The status.

    Raises:
        DraftBindingValidationError: For an unknown project or version.
    """
    project, version = _resolve_scope(tenant_id, project_ref, version_ref)
    version_id = str(version["id"])
    binding = db.get_active_draft_binding(
        tenant_id=tenant_id, project_id=str(project["id"]), version_id=version_id
    )
    plans = db.list_draft_sync_plans(
        tenant_id=tenant_id, version_id=version_id, limit=PLAN_HISTORY_LIMIT
    )
    latest: Optional[SyncPlanDetail] = None
    history: List[SyncPlanRecord] = []
    if plans:
        _document, draft_digest = read_draft_document(tenant_id, version)
        latest = _detail(tenant_id, plans[0], draft_digest=draft_digest)
        history = [_plan_record(row, draft_digest=draft_digest) for row in plans[1:]]
    return VersionSyncStatus(
        version_id=version_id,
        version_label=version.get("version_id"),
        bound=bool(binding),
        latest=latest,
        history=history,
    )


def get_plan(tenant_id: str, project_ref: str, plan_id: str) -> SyncPlanDetail:
    """Read one merge result with its conflicts.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        plan_id: The plan.

    Returns:
        The detail.

    Raises:
        SpecSyncValidationError: ``sync-plan-not-found``.
        DraftBindingValidationError: For an unknown project.
    """
    project = draft_binding_store.resolve_project(tenant_id, project_ref)
    row = db.get_draft_sync_plan(
        tenant_id=tenant_id, project_id=str(project["id"]), plan_id=plan_id
    )
    if not row:
        raise SpecSyncValidationError(CODE_PLAN_NOT_FOUND, f"no merge result '{plan_id}' here")
    version = db.get_version_by_id(str(row["version_id"]), tenant_id)
    draft_digest = read_draft_document(tenant_id, version)[1] if version else None
    return _detail(tenant_id, row, draft_digest=draft_digest)


# ---------------------------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------------------------


def _target_commit(
    tenant_id: str, binding: Mapping[str, Any], request: SyncPlanCompute
) -> Tuple[str, Optional[str]]:
    """Decide which commit to merge in, and which candidate it settles.

    Args:
        tenant_id: The caller's tenant.
        binding: The active binding row.
        request: What the caller asked for.

    Returns:
        ``(commit sha, candidate id or None)``.

    Raises:
        SpecSyncValidationError: ``sync-nothing-to-merge`` when the binding has no outstanding
            movement, or the named candidate is not one of its pending rows.
    """
    binding_id = str(binding["id"])
    if request.candidate_id:
        candidate = db.get_binding_sync_candidate(
            tenant_id=tenant_id, binding_id=binding_id, candidate_id=request.candidate_id
        )
        if not candidate:
            raise SpecSyncValidationError(
                CODE_NOTHING_TO_MERGE, f"no sync candidate '{request.candidate_id}' on this binding"
            )
        return str(candidate["to_commit_sha"]), str(candidate["id"])

    pending = db.list_binding_sync_candidates(
        tenant_id=tenant_id, binding_id=binding_id, pending_only=True, limit=PENDING_SCAN_LIMIT
    )
    if not pending:
        raise SpecSyncValidationError(
            CODE_NOTHING_TO_MERGE,
            f"{binding['ref']} has not moved since this draft was last synchronized",
        )
    # Oldest first: the earliest unmerged movement is the one a reader is looking at, and merging
    # it first keeps the sequence of decisions in the order the branch actually happened.
    oldest = min(pending, key=lambda row: str(row.get("detected_at") or ""))
    return str(oldest["to_commit_sha"]), str(oldest["id"])


def compute_plan(
    tenant_id: str,
    project_ref: str,
    version_ref: str,
    actor_id: str,
    request: SyncPlanCompute,
) -> SyncPlanDetail:
    """Merge the repository's changes into a bound draft, against their common base.

    Three documents are gathered — the selection at the binding's synchronized commit, the
    selection at the commit the ref moved to, and the draft as this platform has it — and merged.
    Incoming changes that touch nothing the draft touched are recorded as applied; everything that
    overlaps becomes a conflict naming its pointer, its repository file and line, and all three
    values.

    **The draft is not modified, and neither is any review.** The result is a row.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        actor_id: The acting user, whose stored credential authorizes the repository reads.
        request: Which candidate to merge, and whether to re-read.

    Returns:
        The merge result with its conflicts.

    Raises:
        SpecSyncValidationError: ``sync-not-bound``, ``sync-nothing-to-merge``,
            ``sync-base-drifted``, ``sync-invalid-document``, or ``sync-conflict`` when the plan
            could not be read back.
        DraftBindingValidationError: A ``binding-repository-*`` refusal when a commit could not be
            read.
    """
    project, version = _resolve_scope(tenant_id, project_ref, version_ref)
    project_id = str(project["id"])
    version_id = str(version["id"])
    binding = _require_binding(tenant_id, project_id, version_id)
    binding_id = str(binding["id"])

    git_commit, candidate_id = _target_commit(tenant_id, binding, request)
    base_commit = str(binding["commit_sha"])
    base_digest = str(binding["source_digest"])

    draft_document, draft_digest = read_draft_document(tenant_id, version)
    fingerprint = plan_fingerprint(binding_id, base_commit, git_commit, draft_digest)

    if not request.refresh:
        stored = db.find_draft_sync_plan(
            tenant_id=tenant_id, binding_id=binding_id, plan_fingerprint=fingerprint
        )
        if stored:
            # Same binding, same three documents: the merge cannot have a different answer, and
            # recomputing it would cost two provider reads to prove that.
            return _detail(tenant_id, stored, draft_digest=draft_digest)

    base_document, read_base_digest, _base_file, _base_text, _base_lines, _base_members = (
        _read_repository_document(tenant_id, actor_id, binding, base_commit)
    )
    if read_base_digest != base_digest:
        raise SpecSyncValidationError(
            CODE_BASE_DRIFTED,
            (
                f"the selection at {base_commit[:7]} no longer matches the digest this binding "
                "recorded for it, so there is no common base to merge against; check for updates "
                "and re-bind if the branch was rewritten"
            ),
        )

    git_document, git_digest, source_file, _git_text, git_lines, member_count = (
        _read_repository_document(tenant_id, actor_id, binding, git_commit)
    )

    outcome = merge_documents(
        base_document,
        git_document,
        draft_document,
        lines=git_lines,
        source_file=source_file,
    )
    guard = _guard_for(tenant_id, project_id, version)

    written = db.record_draft_sync_plan(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_id,
        binding_id=binding_id,
        candidate_id=candidate_id,
        base_commit_sha=base_commit,
        base_digest=base_digest,
        git_commit_sha=git_commit,
        git_digest=git_digest,
        draft_digest=draft_digest,
        plan_fingerprint=fingerprint,
        status=outcome.status,
        auto_applied_count=len(outcome.changes),
        local_count=outcome.local_count,
        agreed_count=outcome.agreed_count,
        changes=_stored_changes(outcome),
        conflicts=_stored_conflicts(outcome, binding, git_commit),
        conflicts_truncated=outcome.conflicts_truncated,
        source_file=source_file,
        source_member_count=member_count,
        guard=guard,
        actor_id=actor_id,
    )
    if not written:
        raise SpecSyncValidationError(
            CODE_CONFLICT, "the merge result could not be stored; read the binding again and retry"
        )
    row = db.get_draft_sync_plan(
        tenant_id=tenant_id, project_id=project_id, plan_id=str(written["plan_id"])
    )
    if not row:  # pragma: no cover - the row was written moments ago
        raise SpecSyncValidationError(CODE_CONFLICT, "the merge result could not be read back")
    return _detail(tenant_id, row, draft_digest=draft_digest)


def resolve_conflict(
    tenant_id: str,
    project_ref: str,
    plan_id: str,
    conflict_id: str,
    actor_id: str,
    request: SyncConflictResolve,
) -> SyncPlanDetail:
    """Settle one conflict of a merge result towards one side.

    Settling records a decision. It does not edit the draft, take anything from the repository, or
    move the binding: those are separate, explicit acts, and keeping them separate is what stops a
    conflict list from becoming a way to overwrite a draft one pointer at a time.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        plan_id: The plan the conflict belongs to.
        conflict_id: The conflict.
        actor_id: The acting user.
        request: ``git`` or ``draft``, with an optional note.

    Returns:
        The plan, with the conflict now settled.

    Raises:
        SpecSyncValidationError: ``sync-plan-not-found``, ``sync-conflict-not-found``,
            ``sync-conflict-resolved`` when it already settled, or ``sync-conflict`` on a race.
        DraftBindingValidationError: For an unknown project.
    """
    project = draft_binding_store.resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    plan = db.get_draft_sync_plan(tenant_id=tenant_id, project_id=project_id, plan_id=plan_id)
    if not plan:
        raise SpecSyncValidationError(CODE_PLAN_NOT_FOUND, f"no merge result '{plan_id}' here")

    conflict = db.get_draft_sync_conflict(
        tenant_id=tenant_id, plan_id=plan_id, conflict_id=conflict_id
    )
    if not conflict:
        raise SpecSyncValidationError(
            CODE_CONFLICT_NOT_FOUND, f"no conflict '{conflict_id}' on this merge result"
        )
    if conflict.get("resolution"):
        raise SpecSyncValidationError(
            CODE_CONFLICT_RESOLVED,
            f"this conflict was already settled as '{conflict['resolution']}'; settlements are final",
        )

    settled = db.resolve_draft_sync_conflict(
        tenant_id=tenant_id,
        project_id=project_id,
        plan_id=plan_id,
        conflict_id=conflict_id,
        resolution=request.resolution,
        actor_id=actor_id,
        note=request.note,
    )
    if not settled:
        raise SpecSyncValidationError(
            CODE_CONFLICT, "the conflict was settled while this request was in flight"
        )
    row = db.get_draft_sync_plan(tenant_id=tenant_id, project_id=project_id, plan_id=plan_id)
    if not row:  # pragma: no cover - the plan was read moments ago
        raise SpecSyncValidationError(CODE_CONFLICT, "the merge result could not be read back")
    version = db.get_version_by_id(str(row["version_id"]), tenant_id)
    draft_digest = read_draft_document(tenant_id, version)[1] if version else None
    return _detail(tenant_id, row, draft_digest=draft_digest)
