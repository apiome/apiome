"""Draft branches and merge requests — the store of COL-4.3 (#4527).

The rules between the HTTP surface (:mod:`app.merge_request_routes`) and storage (apiome-db V377):

* **Scope.** Every read and write resolves the project inside the caller's tenant first, and every
  branch and merge request is read back through that project, so an id from another tenant or
  project is simply "not found".
* **Draft branches isolate.** Creating a draft branch copies the line's tip (classes and paths)
  into a *new* draft revision, in one transaction with the branch row, and the branch's tip is that
  revision. Edits on the branch land on its own revision, so the line never changes until a merge.
* **No second merge path.** Checking and merging run the existing merge-preview (persisting a
  merge session) and merge routes of :mod:`app.version_merge_routes` — the same three-way engine,
  stale-head lock, immutability guard, and compatibility gate the Versions screen uses. The merge
  request only records which session it ran and drives that session's status
  (``preview → resolving → applied | aborted``).
* **No second review path.** Reviewers decide on the COL-2.1 review of the branch's tip; the merge
  request only attaches it. A merge needs that review approved, its round not stale, and the
  COL-2.3 approval policy (when one applies) satisfied.
* **One open merge request per draft branch**; V377's partial unique index backs it.

Refusals raise :class:`app.merge_requests.MergeRequestValidationError` with a stable code; review
refusals pass through as :class:`app.reviews.ReviewValidationError`. Merge-path refusals (stale
head, immutability, compatibility gate) pass through as the ``HTTPException`` that path raised.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

import psycopg2

from . import review_store
from .approval_publish_gate import assess_approval_gate
from .database import db
from .merge_requests import (
    BLOCKER_APPROVAL_POLICY,
    BLOCKER_CHANGES_REQUESTED,
    BLOCKER_CONFLICTS,
    BLOCKER_NO_REVIEW,
    BLOCKER_REVIEW_OUTDATED,
    BLOCKER_REVIEW_PENDING,
    BLOCKER_REVIEW_STALE,
    BLOCKER_TARGET_IMMUTABLE,
    CODE_ALREADY_OPEN,
    CODE_BRANCH_EXISTS,
    CODE_BRANCH_NOT_FOUND,
    CODE_CONFLICTS,
    CODE_FORBIDDEN,
    CODE_INVALID_BRANCH_NAME,
    CODE_INVALID_LABEL,
    CODE_LABEL_TAKEN,
    CODE_MERGE_REQUEST_NOT_FOUND,
    CODE_NOT_DRAFT_BRANCH,
    CODE_NOT_OPEN,
    CODE_NOT_READY,
    CODE_PROJECT_NOT_FOUND,
    CODE_SAME_BRANCH,
    DraftBranchCreate,
    DraftBranchRecord,
    MergeBlocker,
    MergeConflict,
    MergeReadiness,
    MergeRequestCreate,
    MergeRequestDetail,
    MergeRequestMerge,
    MergeRequestRecord,
    MergeRequestReviewRequest,
    MergeRequestValidationError,
)
from .published_immutability import revision_is_published_immutable
from .review_lifecycle import STATE_IN_REVIEW
from .reviews import CODE_INVALID_REVIEWERS, ReviewDetail, ReviewRequestCreate, ReviewValidationError
from .revision_deprecation import is_uuid_string
from .version_path_copy import copy_paths_between_versions

__all__ = [
    "check_merge_request",
    "close_merge_request",
    "create_draft_branch",
    "get_merge_request",
    "list_draft_branches",
    "list_merge_requests",
    "merge_merge_request",
    "open_merge_request",
    "readiness",
    "request_merge_request_review",
]

logger = logging.getLogger(__name__)

#: The most merge requests one list page returns.
MAX_LIST_LIMIT = 100

#: Merge-session statuses that are still in progress (and so may be superseded or advanced).
_LIVE_SESSION_STATUSES = frozenset({"preview", "resolving"})

_MR_COLUMNS = """
    mr.id::text AS id, mr.tenant_id::text AS tenant_id, mr.project_id::text AS project_id,
    mr.title, mr.description, mr.state,
    mr.source_branch_id::text AS source_branch_id, mr.source_branch_name,
    mr.target_branch_id::text AS target_branch_id, mr.target_branch_name,
    mr.review_id::text AS review_id, mr.merge_session_id::text AS merge_session_id,
    mr.merged_version_id::text AS merged_version_id,
    mr.created_by::text AS created_by,
    (SELECT u.name FROM apiome.users u WHERE u.id = mr.created_by) AS created_by_name,
    mr.created_at, mr.updated_at, mr.merged_by::text AS merged_by, mr.merged_at,
    mr.closed_by::text AS closed_by, mr.closed_at
"""

_DRAFT_COLUMNS = """
    b.id::text AS id, b.project_id::text AS project_id, b.name,
    b.tip_version_id::text AS tip_revision_id, v.version_id AS tip_version_label,
    b.draft_of_branch_id::text AS base_branch_id, base.name AS base_branch_name,
    b.branched_from_revision_id::text AS branched_from_revision_id,
    b.created_by::text AS created_by, b.created_at
"""


# ---------------------------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------------------------


def _project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id inside the tenant, or refuse.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        MergeRequestValidationError: ``mr-project-not-found``.
    """
    try:
        return review_store.resolve_project(tenant_id, project_ref)
    except ReviewValidationError as exc:
        raise MergeRequestValidationError(CODE_PROJECT_NOT_FOUND, str(exc)) from exc


def _require_actor(actor_id: Optional[str]) -> str:
    """Require an attributable acting user.

    Args:
        actor_id: The acting user.

    Returns:
        The user id.

    Raises:
        MergeRequestValidationError: ``mr-forbidden`` when there is none.
    """
    if not actor_id or not is_uuid_string(str(actor_id)):
        raise MergeRequestValidationError(
            CODE_FORBIDDEN, "branch and merge request actions must be attributable to a user"
        )
    return str(actor_id)


def resolve_branch(tenant_id: str, project_id: str, ref: str) -> Dict[str, Any]:
    """Resolve a branch name or id inside the project, or refuse.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project the branch must belong to.
        ref: A branch id or branch name.

    Returns:
        The branch row (``version_branches`` columns plus ``draft_of_branch_id``).

    Raises:
        MergeRequestValidationError: ``mr-branch-not-found``.
    """
    text = str(ref or "").strip()
    rows: List[Dict[str, Any]] = []
    if text:
        column = "b.id" if is_uuid_string(text) else "b.name"
        rows = db.execute_query(
            f"""
            SELECT b.id::text AS id, b.project_id::text AS project_id, b.name,
                   b.tip_version_id::text AS tip_version_id, b.is_default, b.protected,
                   b.draft_of_branch_id::text AS draft_of_branch_id
            FROM apiome.version_branches b
            JOIN apiome.projects p ON p.id = b.project_id
            WHERE {column} = %s AND b.project_id = %s::uuid AND p.tenant_id = %s::uuid
            """,
            (text, project_id, tenant_id),
        )
    if not rows:
        raise MergeRequestValidationError(CODE_BRANCH_NOT_FOUND, f"no branch '{text}' in this project")
    return dict(rows[0])


def _default_branch(tenant_id: str, project_id: str) -> Dict[str, Any]:
    """The project's default branch, or refuse when it has none."""
    rows = db.execute_query(
        """
        SELECT b.id::text AS id FROM apiome.version_branches b
        JOIN apiome.projects p ON p.id = b.project_id
        WHERE b.project_id = %s::uuid AND p.tenant_id = %s::uuid AND b.is_default
        """,
        (project_id, tenant_id),
    )
    if not rows:
        raise MergeRequestValidationError(
            CODE_BRANCH_NOT_FOUND, "this project has no default branch; name the version line to draft off"
        )
    return resolve_branch(tenant_id, project_id, rows[0]["id"])


def _version(tenant_id: str, revision_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Read a revision row, or ``None``."""
    return db.get_version_by_id(revision_id, tenant_id) if revision_id else None


# ---------------------------------------------------------------------------------------------
# Draft branches
# ---------------------------------------------------------------------------------------------


def _draft_record(row: Mapping[str, Any]) -> DraftBranchRecord:
    """Map a draft-branch row onto its record."""
    return DraftBranchRecord(**{key: row.get(key) for key in DraftBranchRecord.model_fields})


def _read_draft(project_id: str, branch_id: str) -> DraftBranchRecord:
    """Read one draft branch by id (already scoped by the caller)."""
    rows = db.execute_query(
        f"""
        SELECT {_DRAFT_COLUMNS}
        FROM apiome.version_branches b
        JOIN apiome.versions v ON v.id = b.tip_version_id
        LEFT JOIN apiome.version_branches base ON base.id = b.draft_of_branch_id
        WHERE b.id = %s::uuid AND b.project_id = %s::uuid
        """,
        (branch_id, project_id),
    )
    return _draft_record(rows[0])


def list_draft_branches(tenant_id: str, project_ref: str) -> List[DraftBranchRecord]:
    """List a project's draft branches, newest first.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.

    Returns:
        The draft branches.

    Raises:
        MergeRequestValidationError: ``mr-project-not-found``.
    """
    project_id = str(_project(tenant_id, project_ref)["id"])
    rows = db.execute_query(
        f"""
        SELECT {_DRAFT_COLUMNS}
        FROM apiome.version_branches b
        JOIN apiome.versions v ON v.id = b.tip_version_id
        LEFT JOIN apiome.version_branches base ON base.id = b.draft_of_branch_id
        WHERE b.project_id = %s::uuid AND b.draft_of_branch_id IS NOT NULL
        ORDER BY b.created_at DESC, b.name ASC
        """,
        (project_id,),
    )
    return [_draft_record(row) for row in rows]


def _draft_label(tenant_id: str, project_id: str, requested: Optional[str]) -> str:
    """The version label of a new draft revision: the requested one, or the next patch.

    Raises:
        MergeRequestValidationError: ``mr-invalid-label`` or ``mr-label-taken``.
    """
    # Lazy: version_merge_routes imports the routers' world; keep this module importable alone.
    from .version_merge_routes import bump_patch_version, parse_semantic_version

    if requested and requested.strip():
        label = requested.strip()
    else:
        latest = db.get_latest_version_for_project(project_id, tenant_id)
        label = bump_patch_version(latest) if latest else "0.1.0"
    if not parse_semantic_version(label):
        raise MergeRequestValidationError(
            CODE_INVALID_LABEL, f"version label '{label}' must follow semantic versioning, e.g. 1.4.1"
        )
    taken = db.execute_query(
        "SELECT 1 FROM apiome.versions WHERE project_id = %s::uuid AND version_id = %s LIMIT 1",
        (project_id, label),
    )
    if taken:
        raise MergeRequestValidationError(CODE_LABEL_TAKEN, f"version {label} already exists in this project")
    return label


def create_draft_branch(
    tenant_id: str, project_ref: str, body: DraftBranchCreate, actor_id: Optional[str]
) -> DraftBranchRecord:
    """Create a draft branch off a version line.

    One transaction: a new draft revision (child of the line's tip, its classes and paths copied)
    and the branch row whose tip is that revision. The line's branch and revisions are only read.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        body: The branch name, the line, and an optional version label.
        actor_id: The creating user.

    Returns:
        The new draft branch.

    Raises:
        MergeRequestValidationError: For an invalid or taken name or label, or an unknown line.
    """
    from .version_merge_routes import _is_valid_version_branch_name

    actor = _require_actor(actor_id)
    project_id = str(_project(tenant_id, project_ref)["id"])
    name = body.name.strip()
    if not _is_valid_version_branch_name(name):
        raise MergeRequestValidationError(
            CODE_INVALID_BRANCH_NAME,
            "branch names start with a letter and use only letters, digits, . _ - / (max 255 characters)",
        )
    base = (
        resolve_branch(tenant_id, project_id, body.base_branch)
        if body.base_branch
        else _default_branch(tenant_id, project_id)
    )
    if db.get_version_branch_by_name(project_id, tenant_id, name):
        raise MergeRequestValidationError(CODE_BRANCH_EXISTS, f"a branch named '{name}' already exists")
    label = _draft_label(tenant_id, project_id, body.version_label)

    conn = db.connect()
    prev_autocommit = db._begin_tx(conn)
    try:
        with conn.cursor() as cursor:
            # Read the line's tip under a share lock so a concurrent merge cannot move it mid-copy.
            cursor.execute(
                "SELECT tip_version_id::text AS tip FROM apiome.version_branches WHERE id = %s::uuid FOR SHARE",
                (base["id"],),
            )
            locked = cursor.fetchone()
            if not locked:
                raise MergeRequestValidationError(CODE_BRANCH_NOT_FOUND, f"no branch '{base['name']}' in this project")
            line_tip = str(locked["tip"])
            cursor.execute(
                """
                INSERT INTO apiome.versions
                    (project_id, creator_id, version_id, description, commit_message, parent_version_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id::text AS id
                """,
                (
                    project_id,
                    actor,
                    label,
                    f"Draft branch {name} off {base['name']}",
                    f"Create draft branch {name} from {base['name']}",
                    line_tip,
                ),
            )
            revision_id = str(cursor.fetchone()["id"])
            db.copy_classes_from_version_for_merge(cursor, line_tip, revision_id)
            copy_paths_between_versions(cursor, line_tip, revision_id)
            cursor.execute(
                """
                INSERT INTO apiome.version_branches
                    (project_id, name, tip_version_id, created_by, branched_from_revision_id, draft_of_branch_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id::text AS id
                """,
                (project_id, name, revision_id, actor, line_tip, base["id"]),
            )
            branch_id = str(cursor.fetchone()["id"])
        conn.commit()
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", "") or ""
        if "branch" in constraint:
            raise MergeRequestValidationError(CODE_BRANCH_EXISTS, f"a branch named '{name}' already exists") from exc
        raise MergeRequestValidationError(CODE_LABEL_TAKEN, f"version {label} already exists in this project") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = prev_autocommit

    db.insert_workflow_audit(
        tenant_id,
        project_id,
        revision_id,
        "branch.draft_created",
        "success",
        actor,
        {"branchName": name, "baseBranch": base["name"], "baseRevisionId": line_tip, "versionLine": label},
    )
    return _read_draft(project_id, branch_id)


# ---------------------------------------------------------------------------------------------
# Merge request reads
# ---------------------------------------------------------------------------------------------


def _record(row: Mapping[str, Any]) -> MergeRequestRecord:
    """Map a merge request row onto its record."""
    return MergeRequestRecord(**{key: row.get(key) for key in MergeRequestRecord.model_fields})


def _mr_row(project_id: str, merge_request_id: str) -> Dict[str, Any]:
    """Read one merge request of a project, or refuse."""
    if not is_uuid_string(str(merge_request_id or "")):
        raise MergeRequestValidationError(CODE_MERGE_REQUEST_NOT_FOUND, "no such merge request in this project")
    rows = db.execute_query(
        f"SELECT {_MR_COLUMNS} FROM apiome.merge_requests mr WHERE mr.id = %s::uuid AND mr.project_id = %s::uuid",
        (merge_request_id, project_id),
    )
    if not rows:
        raise MergeRequestValidationError(CODE_MERGE_REQUEST_NOT_FOUND, "no such merge request in this project")
    return dict(rows[0])


def list_merge_requests(
    tenant_id: str, project_ref: str, *, state: Optional[str] = None, limit: int = 50, offset: int = 0
) -> Tuple[List[MergeRequestRecord], int]:
    """List a project's merge requests, most recently active first.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        state: Only requests in this state.
        limit: Page size (capped at :data:`MAX_LIST_LIMIT`).
        offset: Requests to skip.

    Returns:
        The page of records and the total matching the filter.
    """
    project_id = str(_project(tenant_id, project_ref)["id"])
    where = "mr.project_id = %s::uuid" + (" AND mr.state = %s" if state else "")
    params: Tuple[Any, ...] = (project_id, state) if state else (project_id,)
    rows = db.execute_query(
        f"SELECT {_MR_COLUMNS} FROM apiome.merge_requests mr WHERE {where} "
        "ORDER BY mr.updated_at DESC, mr.id DESC LIMIT %s OFFSET %s",
        params + (max(1, min(limit, MAX_LIST_LIMIT)), max(0, offset)),
    )
    total = db.execute_query(f"SELECT count(*) AS n FROM apiome.merge_requests mr WHERE {where}", params)
    return [_record(row) for row in rows], int(total[0]["n"]) if total else 0


def _review_detail(tenant_id: str, project_id: str, review_id: Optional[str]) -> Optional[ReviewDetail]:
    """Read the attached review, or ``None`` when there is none (or it has been deleted)."""
    if not review_id:
        return None
    try:
        return review_store.get_review(tenant_id, project_id, review_id)
    except ReviewValidationError:
        return None


def _session_view(
    tenant_id: str, project_id: str, session_id: Optional[str], source_tip: Optional[str], target_tip: Optional[str]
) -> Tuple[Optional[Dict[str, Any]], List[MergeConflict], bool]:
    """The merge session, its conflicts, and whether its tips are still the branches' tips.

    Returns:
        ``(session JSON or None, conflicts, current)`` — conflicts are only reported for a
        session whose tips are current, since a moved tip makes them out of date.
    """
    from .version_merge_routes import _merge_session_conflict_json, _merge_session_json

    if not session_id:
        return None, [], False
    detail = db.get_merge_session_detail(session_id, project_id, tenant_id)
    if not detail:
        return None, [], False
    session = detail["session"]
    current = str(session["source_tip_version_id"]) == str(source_tip) and str(session["target_tip_version_id"]) == str(
        target_tip
    )
    conflicts: List[MergeConflict] = []
    if current and session["status"] in _LIVE_SESSION_STATUSES:
        for row in db.list_merge_session_conflicts(session_id, project_id, tenant_id) or []:
            item = _merge_session_conflict_json(row)
            conflicts.append(MergeConflict(path=item["path"], kinds=[str(k) for k in item["kinds"]]))
    return _merge_session_json(session), conflicts, current


def readiness(
    *,
    tenant_id: str,
    project_id: str,
    record: MergeRequestRecord,
    review: Optional[ReviewDetail],
    source_tip: Optional[Mapping[str, Any]],
    target_tip: Optional[Mapping[str, Any]],
    conflicts: List[MergeConflict],
) -> MergeReadiness:
    """Work out whether a merge request can merge now, and every reason it cannot.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        record: The merge request.
        review: The attached review, when there is one.
        source_tip: The draft branch's tip revision row.
        target_tip: The line's tip revision row.
        conflicts: The current merge session's conflicts.

    Returns:
        The readiness, ``can_merge`` only for an open request with no blockers.
    """
    blockers: List[MergeBlocker] = []
    approval: Optional[Dict[str, Any]] = None
    reviewed = review is not None and not review.review.closed_at
    if not reviewed:
        blockers.append(MergeBlocker(code=BLOCKER_NO_REVIEW, message="Request a review of the branch before merging."))
    elif source_tip is not None and str(review.review.version_id) != str(source_tip.get("id")):
        blockers.append(
            MergeBlocker(
                code=BLOCKER_REVIEW_OUTDATED,
                message="The branch moved on after the review was requested. Request a review of its current tip.",
            )
        )
    else:
        state = review.review.state
        if state == "changes_requested":
            blockers.append(MergeBlocker(code=BLOCKER_CHANGES_REQUESTED, message="A reviewer requested changes."))
        if review.spec_changed:
            blockers.append(
                MergeBlocker(
                    code=BLOCKER_REVIEW_STALE,
                    message="The branch changed after this review round was requested. Re-request the review.",
                )
            )
        if state == STATE_IN_REVIEW:
            blockers.append(
                MergeBlocker(
                    code=BLOCKER_REVIEW_PENDING,
                    message=f"{review.review.pending_count} reviewer(s) have not decided yet.",
                )
            )
    if source_tip is not None:
        assessment = assess_approval_gate(tenant_id=tenant_id, project_id=project_id, version=source_tip)
        if assessment.status != "disabled":
            approval = assessment.as_payload()
        if assessment.blocked and reviewed and not blockers:
            blockers.append(MergeBlocker(code=BLOCKER_APPROVAL_POLICY, message=assessment.message()))
    if conflicts:
        blockers.append(
            MergeBlocker(
                code=BLOCKER_CONFLICTS,
                message=(
                    f"{len(conflicts)} conflicting path(s) with {record.target_branch_name}. "
                    "Update the branch, then check again."
                ),
            )
        )
    if target_tip is not None and revision_is_published_immutable(dict(target_tip)):
        blockers.append(
            MergeBlocker(
                code=BLOCKER_TARGET_IMMUTABLE,
                message=(
                    f"The tip of {record.target_branch_name} is published and immutable. Only a tenant "
                    "administrator can merge, with a reason that is recorded in the audit log."
                ),
            )
        )
    return MergeReadiness(can_merge=record.state == "open" and not blockers, blockers=blockers, approval=approval)


def _build_detail(tenant_id: str, project_id: str, row: Mapping[str, Any]) -> MergeRequestDetail:
    """Assemble a merge request's detail from its row and the live branches."""
    record = _record(row)
    source_branch = db.get_version_branch_by_id(record.source_branch_id, tenant_id) if record.source_branch_id else None
    target_branch = db.get_version_branch_by_id(record.target_branch_id, tenant_id) if record.target_branch_id else None
    source_tip = _version(tenant_id, str(source_branch["tip_version_id"]) if source_branch else None)
    target_tip = _version(tenant_id, str(target_branch["tip_version_id"]) if target_branch else None)
    merge_base = None
    if source_tip and target_tip:
        merge_base = _version(
            tenant_id, db.compute_merge_base_revision_id(str(source_tip["id"]), str(target_tip["id"]), tenant_id)
        )
    review = _review_detail(tenant_id, project_id, record.review_id)
    session, conflicts, _current = _session_view(
        tenant_id,
        project_id,
        record.merge_session_id,
        source_tip["id"] if source_tip else None,
        target_tip["id"] if target_tip else None,
    )
    if record.state == "open":
        ready = readiness(
            tenant_id=tenant_id,
            project_id=project_id,
            record=record,
            review=review,
            source_tip=source_tip,
            target_tip=target_tip,
            conflicts=conflicts,
        )
    else:
        ready = MergeReadiness(can_merge=False)
    return MergeRequestDetail(
        merge_request=record,
        source_tip_revision_id=str(source_tip["id"]) if source_tip else None,
        source_tip_version_label=source_tip.get("version_id") if source_tip else None,
        target_tip_revision_id=str(target_tip["id"]) if target_tip else None,
        target_tip_version_label=target_tip.get("version_id") if target_tip else None,
        merge_base_revision_id=str(merge_base["id"]) if merge_base else None,
        merge_base_version_label=merge_base.get("version_id") if merge_base else None,
        review=review,
        review_outdated=bool(
            review
            and source_tip
            and not review.review.closed_at
            and str(review.review.version_id) != str(source_tip["id"])
        ),
        merge_session=session,
        conflicts=conflicts,
        readiness=ready,
    )


def get_merge_request(tenant_id: str, project_ref: str, merge_request_id: str) -> MergeRequestDetail:
    """Read a merge request with its branches, review, merge session, and readiness.

    Raises:
        MergeRequestValidationError: For an unknown project or merge request.
    """
    project_id = str(_project(tenant_id, project_ref)["id"])
    return _build_detail(tenant_id, project_id, _mr_row(project_id, merge_request_id))


# ---------------------------------------------------------------------------------------------
# Merge request writes
# ---------------------------------------------------------------------------------------------


def _attach_review(
    tenant_id: str, project_id: str, tip_revision_id: str, reviewers: Optional[List[str]], actor: str
) -> str:
    """The id of the open review of the tip: the existing one, or a new one asking ``reviewers``.

    Raises:
        ReviewValidationError: For an invalid reviewer list or a published tip.
    """
    existing = db.get_open_review_for_version(tenant_id=tenant_id, project_id=project_id, version_id=tip_revision_id)
    if existing:
        return str(existing["id"])
    if not reviewers:
        raise ReviewValidationError(CODE_INVALID_REVIEWERS, "name at least one reviewer for the branch")
    detail = review_store.request_review(
        tenant_id, project_id, ReviewRequestCreate(version=tip_revision_id, reviewers=reviewers), actor
    )
    return detail.review.id


def open_merge_request(
    tenant_id: str, project_ref: str, body: MergeRequestCreate, actor_id: Optional[str]
) -> MergeRequestDetail:
    """Open a merge request from a draft branch and request (or attach) the review of its tip.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        body: Source, target, title, description, reviewers.
        actor_id: The opening user.

    Returns:
        The new merge request's detail.

    Raises:
        MergeRequestValidationError: For unknown branches, a non-draft source, the same branch on
            both sides, or a source that already has an open merge request.
        ReviewValidationError: For an invalid reviewer list.
    """
    actor = _require_actor(actor_id)
    project_id = str(_project(tenant_id, project_ref)["id"])
    source = resolve_branch(tenant_id, project_id, body.source_branch)
    if not source.get("draft_of_branch_id"):
        raise MergeRequestValidationError(
            CODE_NOT_DRAFT_BRANCH, f"'{source['name']}' is not a draft branch; create a draft branch to propose changes"
        )
    target_ref = body.target_branch or source["draft_of_branch_id"]
    target = resolve_branch(tenant_id, project_id, target_ref)
    if target["id"] == source["id"]:
        raise MergeRequestValidationError(CODE_SAME_BRANCH, "a branch cannot be merged into itself")
    already_open = MergeRequestValidationError(
        CODE_ALREADY_OPEN, f"'{source['name']}' already has an open merge request"
    )
    if db.execute_query(
        "SELECT 1 FROM apiome.merge_requests WHERE source_branch_id = %s::uuid AND state = 'open'", (source["id"],)
    ):
        raise already_open

    review_id = _attach_review(tenant_id, project_id, source["tip_version_id"], body.reviewers, actor)
    try:
        rows = db.execute_query(
            """
            INSERT INTO apiome.merge_requests
                (tenant_id, project_id, title, description, source_branch_id, source_branch_name,
                 target_branch_id, target_branch_name, review_id, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                project_id,
                body.title.strip(),
                (body.description or "").strip() or None,
                source["id"],
                source["name"],
                target["id"],
                target["name"],
                review_id,
                actor,
            ),
        )
    except psycopg2.errors.UniqueViolation as exc:
        raise already_open from exc
    merge_request_id = str(rows[0]["id"])
    db.insert_workflow_audit(
        tenant_id,
        project_id,
        source["tip_version_id"],
        "merge_request.opened",
        "success",
        actor,
        {
            "mergeRequestId": merge_request_id,
            "sourceBranch": source["name"],
            "targetBranch": target["name"],
            "reviewId": review_id,
        },
    )
    return get_merge_request(tenant_id, project_id, merge_request_id)


def _require_open(row: Mapping[str, Any]) -> None:
    """Refuse a merged or closed merge request."""
    if row.get("state") != "open":
        raise MergeRequestValidationError(CODE_NOT_OPEN, f"this merge request is {row.get('state')}")


def _set_fields(merge_request_id: str, fields: Mapping[str, Any], *, only_open: bool = True) -> bool:
    """Update columns of a merge request (and ``updated_at``); returns whether a row changed."""
    assignments = ", ".join(f"{column} = %s" for column in fields)
    sql = (
        f"UPDATE apiome.merge_requests SET {assignments}, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = %s::uuid" + (" AND state = 'open'" if only_open else "") + " RETURNING id"
    )
    return bool(db.execute_query(sql, tuple(fields.values()) + (merge_request_id,)))


def request_merge_request_review(
    tenant_id: str, project_ref: str, merge_request_id: str, body: MergeRequestReviewRequest, actor_id: Optional[str]
) -> MergeRequestDetail:
    """Attach a review of the branch's *current* tip, withdrawing one of an older tip.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        merge_request_id: The merge request.
        body: The reviewers; omitted means the previous review's current-round reviewers.
        actor_id: The acting user.

    Returns:
        The updated detail.
    """
    actor = _require_actor(actor_id)
    project_id = str(_project(tenant_id, project_ref)["id"])
    row = _mr_row(project_id, merge_request_id)
    _require_open(row)
    if not row.get("source_branch_id"):
        raise MergeRequestValidationError(CODE_BRANCH_NOT_FOUND, "the draft branch no longer exists")
    source = resolve_branch(tenant_id, project_id, row["source_branch_id"])
    previous = _review_detail(tenant_id, project_id, row.get("review_id"))
    reviewers = body.reviewers
    if not reviewers and previous is not None:
        reviewers = [r.user_id for r in previous.reviewers if r.user_id]
    if (
        previous is not None
        and not previous.review.closed_at
        and previous.review.version_id != source["tip_version_id"]
    ):
        review_store.withdraw_review(tenant_id, project_id, previous.review.id, actor)
    review_id = _attach_review(tenant_id, project_id, source["tip_version_id"], reviewers, actor)
    _set_fields(str(row["id"]), {"review_id": review_id})
    return get_merge_request(tenant_id, project_id, str(row["id"]))


def _supersede_session(tenant_id: str, project_id: str, session_id: Optional[str], actor: str) -> None:
    """Abort an earlier merge session that is still in progress (best-effort)."""
    if not session_id:
        return
    detail = db.get_merge_session_detail(session_id, project_id, tenant_id)
    if detail and detail["session"]["status"] in _LIVE_SESSION_STATUSES:
        db.update_merge_session_status(session_id, project_id, tenant_id, "aborted", actor)


def _run_merge_session(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    row: Mapping[str, Any],
    auth_data: Dict[str, Any],
    actor: str,
    body: MergeRequestMerge,
) -> Dict[str, Any]:
    """Run the existing merge preview with a persisted merge session and attach the session.

    Returns:
        The preview body (``classification``, ``conflicts``, ``mergeSessionId`` …).

    Raises:
        HTTPException: Whatever the merge-preview path refuses with.
    """
    from .models import VersionBranchMergePreviewRequest
    from .version_merge_routes import version_branch_merge_preview

    if not row.get("source_branch_id") or not row.get("target_branch_id"):
        raise MergeRequestValidationError(CODE_BRANCH_NOT_FOUND, "a branch of this merge request no longer exists")
    preview = version_branch_merge_preview(
        tenant_slug,
        project_id,
        VersionBranchMergePreviewRequest(
            source_branch_name=row["source_branch_name"],
            target_branch_name=row["target_branch_name"],
            include_merged_open_api=False,
            persist_merge_session=True,
            override_published_immutability=body.override_published_immutability,
            override_reason=body.override_reason,
        ),
        auth_data,
    )
    _supersede_session(tenant_id, project_id, row.get("merge_session_id"), actor)
    session_id = str(preview["mergeSessionId"])
    _set_fields(str(row["id"]), {"merge_session_id": session_id})
    if not preview.get("classification", {}).get("canAutoMerge"):
        # Conflicts are being worked on: the session moves to `resolving` and stays there until a
        # later check supersedes it.
        db.update_merge_session_status(session_id, project_id, tenant_id, "resolving", actor)
    return preview


def check_merge_request(
    tenant_slug: str,
    auth_data: Dict[str, Any],
    actor_id: Optional[str],
    project_ref: str,
    merge_request_id: str,
    body: MergeRequestMerge,
) -> MergeRequestDetail:
    """Check for conflicts: run a fresh merge session for the current tips and attach it.

    Args:
        tenant_slug: The tenant slug (the merge path builds documents under it).
        auth_data: The authenticated principal, forwarded to the merge path.
        actor_id: The acting user.
        project_ref: Project slug or id.
        merge_request_id: The merge request.
        body: Immutability-override options, forwarded to the merge preview.

    Returns:
        The updated detail, ``conflicts`` listing what the session found.
    """
    tenant_id = str(auth_data["tenant_id"])
    actor = _require_actor(actor_id)
    project_id = str(_project(tenant_id, project_ref)["id"])
    row = _mr_row(project_id, merge_request_id)
    _require_open(row)
    _run_merge_session(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        project_id=project_id,
        row=row,
        auth_data=auth_data,
        actor=actor,
        body=body,
    )
    return get_merge_request(tenant_id, project_id, str(row["id"]))


def merge_merge_request(
    tenant_slug: str,
    auth_data: Dict[str, Any],
    actor_id: Optional[str],
    project_ref: str,
    merge_request_id: str,
    body: MergeRequestMerge,
) -> MergeRequestDetail:
    """Merge an approved merge request through the existing merge session and merge path.

    1. Refuse unless the request is open and every review blocker is cleared.
    2. Run a fresh merge session for the current tips; refuse with ``mr-conflicts`` (and the
       session's conflicts) when it cannot auto-merge.
    3. Move the session to ``resolving``, run the existing merge with the line's tip as the
       optimistic-lock base, and move the session to ``applied`` (``aborted`` when the merge path
       refuses, whose refusal is then raised as-is).
    4. Record the merge on the request.

    Args:
        tenant_slug: The tenant slug (the merge path builds documents under it).
        auth_data: The authenticated principal, forwarded to the merge path.
        actor_id: The acting user.
        project_ref: Project slug or id.
        merge_request_id: The merge request.
        body: Immutability-override options, forwarded to the merge path.

    Returns:
        The merged request's detail, ``merged_version_id`` naming the new revision on the line.

    Raises:
        MergeRequestValidationError: ``mr-not-open``, ``mr-not-ready`` (with ``blockers``), or
            ``mr-conflicts`` (with ``conflicts`` and ``merge_session_id``).
        HTTPException: Whatever the merge path refuses with (stale head, immutability, gate).
    """
    from fastapi import HTTPException

    from .models import VersionBranchMergeRequest
    from .version_merge_routes import version_branch_merge

    tenant_id = str(auth_data["tenant_id"])
    actor = _require_actor(actor_id)
    project_id = str(_project(tenant_id, project_ref)["id"])
    row = _mr_row(project_id, merge_request_id)
    _require_open(row)

    detail = _build_detail(tenant_id, project_id, row)
    # Conflicts are recomputed below and the immutability guard belongs to the merge path (which
    # honours a tenant administrator's override), so only the review blockers stop us here.
    review_blockers = [
        b for b in detail.readiness.blockers if b.code not in (BLOCKER_CONFLICTS, BLOCKER_TARGET_IMMUTABLE)
    ]
    if review_blockers:
        raise MergeRequestValidationError(
            CODE_NOT_READY,
            "this merge request is not ready to merge",
            {"blockers": [b.model_dump() for b in review_blockers]},
        )

    preview = _run_merge_session(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        project_id=project_id,
        row=row,
        auth_data=auth_data,
        actor=actor,
        body=body,
    )
    session_id = str(preview["mergeSessionId"])
    if not preview.get("classification", {}).get("canAutoMerge"):
        raise MergeRequestValidationError(
            CODE_CONFLICTS,
            f"the branch conflicts with {row['target_branch_name']}; update the branch and try again",
            {"merge_session_id": session_id, "conflicts": list(preview.get("conflicts") or [])},
        )

    db.update_merge_session_status(session_id, project_id, tenant_id, "resolving", actor)
    try:
        result = version_branch_merge(
            tenant_slug,
            project_id,
            VersionBranchMergeRequest(
                source_branch_name=row["source_branch_name"],
                target_branch_name=row["target_branch_name"],
                base_revision_id=str(preview["targetTipVersionId"]),
                override_published_immutability=body.override_published_immutability,
                override_reason=body.override_reason,
            ),
            auth_data,
        )
    except HTTPException:
        db.update_merge_session_status(session_id, project_id, tenant_id, "aborted", actor)
        raise
    db.update_merge_session_status(session_id, project_id, tenant_id, "applied", actor)

    merged_version_id = str((result.get("version") or {}).get("id") or "") or None
    if not _set_fields(
        str(row["id"]),
        {"state": "merged", "merged_version_id": merged_version_id, "merged_by": actor, "merged_at": _now_sql()},
    ):
        logger.warning("merge request %s was no longer open when its merge was recorded", row["id"])
    db.insert_workflow_audit(
        tenant_id,
        project_id,
        merged_version_id,
        "merge_request.merged",
        "success",
        actor,
        {
            "mergeRequestId": str(row["id"]),
            "sourceBranch": row["source_branch_name"],
            "targetBranch": row["target_branch_name"],
            "mergeSessionId": session_id,
            "reviewId": row.get("review_id"),
        },
    )
    return get_merge_request(tenant_id, project_id, str(row["id"]))


def _now_sql() -> datetime:
    """The current time, as a timezone-aware value psycopg2 stores in a timestamptz column."""
    return datetime.now(timezone.utc)


def close_merge_request(
    tenant_id: str, project_ref: str, merge_request_id: str, actor_id: Optional[str]
) -> MergeRequestDetail:
    """Close a merge request without merging; its branch and revisions stay as they are.

    The attached review is withdrawn when the closer may withdraw it (its requester or a tenant
    administrator), and an in-progress merge session is aborted.

    Raises:
        MergeRequestValidationError: ``mr-not-open`` or not-found codes.
    """
    actor = _require_actor(actor_id)
    project_id = str(_project(tenant_id, project_ref)["id"])
    row = _mr_row(project_id, merge_request_id)
    _require_open(row)
    if not _set_fields(str(row["id"]), {"state": "closed", "closed_by": actor, "closed_at": _now_sql()}):
        raise MergeRequestValidationError(CODE_NOT_OPEN, "this merge request was merged or closed meanwhile")
    _supersede_session(tenant_id, project_id, row.get("merge_session_id"), actor)
    review = _review_detail(tenant_id, project_id, row.get("review_id"))
    if review is not None and not review.review.closed_at:
        try:
            review_store.withdraw_review(tenant_id, project_id, review.review.id, actor)
        except ReviewValidationError:
            # Someone else's review stays open; closing the request does not need it withdrawn.
            pass
    db.insert_workflow_audit(
        tenant_id, project_id, None, "merge_request.closed", "success", actor, {"mergeRequestId": str(row["id"])}
    )
    return get_merge_request(tenant_id, project_id, str(row["id"]))
