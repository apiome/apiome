"""Suggested-changes store — COL-4.2 (#4526).

Rules between the HTTP surface (:mod:`app.review_suggestion_routes`) and storage (apiome-db V376):

* **Scope.** A suggestion belongs to an open review of a draft version, and its target must be a
  class or property *of that version*; an id from anywhere else is "not found".
* **Who proposes.** The review's current-round reviewers, its requester, or a project editor.
* **Who decides.** The review's requester or a project editor — but never the suggestion's own
  author applying it (a reviewer cannot rubber-stamp their own edit). The author may reject
  (withdraw) their own.
* **Applying** locks the suggestion and the element, merges the suggestion onto the element as it
  is now (:func:`app.suggestion_patch.rebase_suggestion`, the merge-session engine), and either
  writes the merge and marks it ``applied`` or marks it ``stale`` with the conflicting paths and
  writes nothing — all in one transaction.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .database import db
from .review_suggestions import (
    CODE_FORBIDDEN,
    CODE_INVALID_PATCH,
    CODE_NOT_OPEN,
    CODE_STALE,
    CODE_SUGGESTION_NOT_FOUND,
    CODE_TARGET_NOT_FOUND,
    ELEMENT_FIELDS,
    SuggestionApplyResult,
    SuggestionCreate,
    SuggestionRecord,
    SuggestionValidationError,
)
from .reviews import CODE_CLOSED, CODE_VERSION_PUBLISHED
from .revision_deprecation import is_uuid_string
from .schema_merge import json_equal
from .suggestion_patch import PatchError, apply_patch, rebase_suggestion

__all__ = [
    "apply_suggestion",
    "create_suggestion",
    "list_suggestions",
    "reject_suggestion",
    "validate_element",
]

#: The most suggestions one list returns.
LIST_LIMIT = 200

_COLUMNS = """
    s.id::text AS id, s.review_id::text AS review_id, s.version_id::text AS version_id,
    s.author_id::text AS author_id, (SELECT u.name FROM apiome.users u WHERE u.id = s.author_id) AS author_name,
    s.target_type, s.target_id::text AS target_id, s.target_label, s.note, s.base, s.patch, s.proposed,
    s.status, s.conflict_paths, s.decided_by::text AS decided_by,
    (SELECT u.name FROM apiome.users u WHERE u.id = s.decided_by) AS decided_by_name,
    s.decided_at, s.reason, s.created_at
"""


# ---------------------------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------------------------


def _element_sql(target_type: str, *, for_update: bool) -> str:
    """The query reading one element of a version as ``(label, description, body)``."""
    lock = " FOR UPDATE OF c" if target_type == "class" else " FOR UPDATE OF cp"
    if target_type == "class":
        sql = (
            "SELECT c.name AS label, c.description, c.schema AS body FROM apiome.classes c "
            "WHERE c.id = %s::uuid AND c.version_id = %s::uuid AND c.deleted_at IS NULL"
        )
    else:
        sql = (
            "SELECT c.name || '.' || cp.name AS label, cp.description, cp.data AS body "
            "FROM apiome.class_properties cp JOIN apiome.classes c ON c.id = cp.class_id "
            "WHERE cp.id = %s::uuid AND c.version_id = %s::uuid AND c.deleted_at IS NULL"
        )
    return sql + (lock if for_update else "")


def _as_element(target_type: str, row: Mapping[str, Any]) -> Dict[str, Any]:
    """The canonical JSON of an element row."""
    body = row["body"]
    if isinstance(body, str):
        body = json.loads(body)
    key = ELEMENT_FIELDS[target_type][1]
    return {"description": row["description"], key: body}


def _read_element(target_type: str, target_id: str, version_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Read an element of a version as ``(label, canonical JSON)``, or ``None`` when absent."""
    if not is_uuid_string(str(target_id or "")):
        return None
    rows = db.execute_query(_element_sql(target_type, for_update=False), (target_id, version_id))
    if not rows:
        return None
    return rows[0]["label"], _as_element(target_type, rows[0])


def validate_element(target_type: str, element: Any) -> None:
    """Refuse a patched element whose shape the model cannot store.

    Raises:
        SuggestionValidationError: ``suggestion-invalid-patch`` when the key set changed, the
            description is not text, or the schema/data is not an object.
    """
    fields = ELEMENT_FIELDS[target_type]
    if not isinstance(element, dict) or set(element) != set(fields):
        raise SuggestionValidationError(
            CODE_INVALID_PATCH, f"a {target_type} suggestion may only change {', '.join(fields)}"
        )
    if element["description"] is not None and not isinstance(element["description"], str):
        raise SuggestionValidationError(CODE_INVALID_PATCH, "description must be text or null")
    if not isinstance(element[fields[1]], dict):
        raise SuggestionValidationError(CODE_INVALID_PATCH, f"{fields[1]} must be a JSON object")


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def _record(row: Mapping[str, Any], *, live: bool = True) -> SuggestionRecord:
    """Map a row onto its record, computing the live ``stale`` flag of an open suggestion."""
    data = dict(row)
    for key in ("base", "patch", "proposed"):
        if isinstance(data[key], str):
            data[key] = json.loads(data[key])
    data["conflict_paths"] = list(data.get("conflict_paths") or [])
    stale = False
    if live and data["status"] == "open":
        current = _read_element(data["target_type"], data["target_id"], data["version_id"])
        _merged, conflicts = rebase_suggestion(data["base"], current[1] if current else None, data["proposed"])
        stale = bool(conflicts)
        if stale:
            data["conflict_paths"] = conflicts
    return SuggestionRecord(**data, stale=stale)


def list_suggestions(review: Mapping[str, Any]) -> List[SuggestionRecord]:
    """A review's suggestions, oldest first.

    Args:
        review: The (already scoped) review row.

    Returns:
        Up to :data:`LIST_LIMIT` records, each open one with its live ``stale`` flag.
    """
    rows = db.execute_query(
        f"SELECT {_COLUMNS} FROM apiome.review_suggestions s WHERE s.review_id = %s::uuid "
        "ORDER BY s.created_at ASC, s.id ASC LIMIT %s",
        (str(review["id"]), LIST_LIMIT),
    )
    return [_record(row) for row in rows]


def _suggestion_row(review: Mapping[str, Any], suggestion_id: str, cursor: Any = None) -> Dict[str, Any]:
    """Read (and, with a cursor, lock) one suggestion of a review, or refuse."""
    if not is_uuid_string(str(suggestion_id or "")):
        raise SuggestionValidationError(CODE_SUGGESTION_NOT_FOUND, "no such suggestion on this review")
    sql = (
        f"SELECT {_COLUMNS} FROM apiome.review_suggestions s "
        "WHERE s.id = %s::uuid AND s.review_id = %s::uuid"
    )
    params = (suggestion_id, str(review["id"]))
    if cursor is None:
        rows = db.execute_query(sql, params)
    else:
        cursor.execute(sql + " FOR UPDATE OF s", params)
        rows = cursor.fetchall()
    if not rows:
        raise SuggestionValidationError(CODE_SUGGESTION_NOT_FOUND, "no such suggestion on this review")
    return dict(rows[0])


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


def _refuse_unwritable(review: Mapping[str, Any], version: Mapping[str, Any]) -> None:
    """Suggestions are only made and decided on an open review of a draft version."""
    if review.get("closed_at"):
        raise SuggestionValidationError(CODE_CLOSED, "this review was withdrawn")
    if version.get("published"):
        raise SuggestionValidationError(CODE_VERSION_PUBLISHED, "the version is published; it can no longer change")


def _current_reviewers(review: Mapping[str, Any]) -> set:
    """User ids of the review's current-round reviewers."""
    rows = db.list_review_reviewers(review_id=str(review["id"]))
    return {str(r["user_id"]) for r in rows if r.get("user_id") and r.get("round") == review.get("round")}


def create_suggestion(
    tenant_id: str,
    review: Mapping[str, Any],
    version: Mapping[str, Any],
    actor_id: str,
    body: SuggestionCreate,
    *,
    is_editor: bool,
) -> SuggestionRecord:
    """Record a reviewer's proposed edit.

    Args:
        tenant_id: The caller's tenant.
        review: The (already scoped) review row.
        version: The reviewed version row.
        actor_id: The proposer.
        body: Target, patch, note.
        is_editor: Whether the proposer has ``projects:edit``.

    Returns:
        The stored suggestion.

    Raises:
        SuggestionValidationError: ``suggestion-forbidden`` for someone not part of the review;
            ``suggestion-target-not-found``; ``suggestion-invalid-patch`` when the patch does not
            apply, changes nothing, or reshapes the element; ``review-closed`` /
            ``review-version-published``.
    """
    _refuse_unwritable(review, version)
    allowed = is_editor or actor_id == str(review.get("requested_by") or "") or actor_id in _current_reviewers(review)
    if not allowed:
        raise SuggestionValidationError(CODE_FORBIDDEN, "only the review's reviewers, its requester, or an editor can suggest")
    found = _read_element(body.target_type, body.target_id, str(version["id"]))
    if found is None:
        raise SuggestionValidationError(CODE_TARGET_NOT_FOUND, f"no such {body.target_type} in the reviewed version")
    label, base = found
    try:
        proposed = apply_patch(base, body.patch)
    except PatchError as exc:
        raise SuggestionValidationError(CODE_INVALID_PATCH, str(exc)) from exc
    validate_element(body.target_type, proposed)
    if json_equal(base, proposed):
        raise SuggestionValidationError(CODE_INVALID_PATCH, "the patch changes nothing")
    rows = db.execute_query(
        "INSERT INTO apiome.review_suggestions (tenant_id, project_id, review_id, version_id, author_id, "
        "target_type, target_id, target_label, note, base, patch, proposed) VALUES (%s::uuid, %s::uuid, "
        "%s::uuid, %s::uuid, %s::uuid, %s, %s::uuid, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb) RETURNING id::text AS id",
        (
            tenant_id, str(review["project_id"]), str(review["id"]), str(version["id"]), actor_id,
            body.target_type, body.target_id, label[:512], (body.note or "").strip() or None,
            json.dumps(base), json.dumps(body.patch), json.dumps(proposed),
        ),
    )
    return _record(_suggestion_row(review, rows[0]["id"]))


def _may_decide(review: Mapping[str, Any], row: Mapping[str, Any], actor_id: str, is_editor: bool, *, applying: bool) -> None:
    """Refuse a decision by someone who may not make it."""
    is_author = actor_id == str(row.get("author_id") or "")
    if applying and is_author:
        raise SuggestionValidationError(CODE_FORBIDDEN, "you cannot apply your own suggestion")
    if not (is_editor or actor_id == str(review.get("requested_by") or "") or (is_author and not applying)):
        raise SuggestionValidationError(CODE_FORBIDDEN, "only the review's requester or an editor can decide suggestions")


def _write_element(cursor: Any, target_type: str, target_id: str, element: Mapping[str, Any]) -> None:
    """Write an element's canonical JSON back to its row (inside the open transaction)."""
    if target_type == "class":
        cursor.execute(
            "UPDATE apiome.classes SET description = %s, schema = %s::jsonb, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = %s::uuid",
            (element["description"], json.dumps(element["schema"]), target_id),
        )
    else:
        cursor.execute(
            "UPDATE apiome.class_properties SET description = %s, data = %s::jsonb WHERE id = %s::uuid",
            (element["description"], json.dumps(element["data"]), target_id),
        )


def _decide(cursor: Any, suggestion_id: str, status: str, actor_id: str, *, reason=None, conflicts=()) -> None:
    """Record a decision on a locked suggestion."""
    cursor.execute(
        "UPDATE apiome.review_suggestions SET status = %s, decided_by = %s::uuid, decided_at = CURRENT_TIMESTAMP, "
        "reason = %s, conflict_paths = %s WHERE id = %s::uuid AND status = 'open'",
        (status, actor_id, reason, list(conflicts), suggestion_id),
    )


def apply_suggestion(
    review: Mapping[str, Any],
    version: Mapping[str, Any],
    suggestion_id: str,
    actor_id: str,
    *,
    is_editor: bool,
) -> SuggestionApplyResult:
    """Apply a suggestion in one click.

    Raises:
        SuggestionValidationError: ``suggestion-stale`` (with ``conflict_paths``) when an edit made
            since overlaps it or the element is gone — the suggestion is recorded ``stale`` and
            nothing else is written; ``suggestion-not-open``; ``suggestion-forbidden``.
    """
    _refuse_unwritable(review, version)
    outcome: Dict[str, Any] = {}

    def work(cursor: Any) -> Optional[bool]:
        row = _suggestion_row(review, suggestion_id, cursor)
        _may_decide(review, row, actor_id, is_editor, applying=True)
        if row["status"] != "open":
            raise SuggestionValidationError(CODE_NOT_OPEN, f"this suggestion is already {row['status']}")
        base, proposed = row["base"], row["proposed"]
        cursor.execute(_element_sql(row["target_type"], for_update=True), (row["target_id"], row["version_id"]))
        found = cursor.fetchall()
        current = _as_element(row["target_type"], found[0]) if found else None
        merged, conflicts = rebase_suggestion(base, current, proposed)
        if conflicts:
            _decide(cursor, suggestion_id, "stale", actor_id, conflicts=conflicts)
            outcome["conflicts"] = conflicts
            return True
        validate_element(row["target_type"], merged)
        _write_element(cursor, row["target_type"], row["target_id"], merged)
        _decide(cursor, suggestion_id, "applied", actor_id)
        outcome.update(element=merged, merged_around=not json_equal(current, base))
        return True

    db._guarded_tx(work)
    if "conflicts" in outcome:
        raise SuggestionValidationError(
            CODE_STALE,
            "the element changed since this suggestion was made; it was marked stale and nothing was written",
            outcome["conflicts"],
        )
    record = _record(_suggestion_row(review, suggestion_id), live=False)
    return SuggestionApplyResult(suggestion=record, element=outcome["element"], merged_around=outcome["merged_around"])


def reject_suggestion(
    review: Mapping[str, Any],
    version: Mapping[str, Any],
    suggestion_id: str,
    actor_id: str,
    *,
    is_editor: bool,
    reason: Optional[str] = None,
) -> SuggestionRecord:
    """Reject a suggestion (or, by its author, withdraw it); the rejection is recorded.

    Raises:
        SuggestionValidationError: ``suggestion-not-open``; ``suggestion-forbidden``.
    """
    _refuse_unwritable(review, version)

    def work(cursor: Any) -> Optional[bool]:
        row = _suggestion_row(review, suggestion_id, cursor)
        _may_decide(review, row, actor_id, is_editor, applying=False)
        if row["status"] != "open":
            raise SuggestionValidationError(CODE_NOT_OPEN, f"this suggestion is already {row['status']}")
        _decide(cursor, suggestion_id, "rejected", actor_id, reason=(reason or "").strip() or None)
        return True

    db._guarded_tx(work)
    return _record(_suggestion_row(review, suggestion_id), live=False)
