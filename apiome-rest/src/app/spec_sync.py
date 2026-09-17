"""Three-way spec synchronization — the shared vocabulary and engine of GNC-2.3 (#4739).

Three documents describe the same API and drift apart independently:

* the **base** — the repository selection at the commit the binding
  (:mod:`app.draft_bindings`) is synchronized with, which is the last point the two sides agreed;
* **Git** — the same selection at the commit the ref has since moved to;
* the **draft** — the version as it stands in this platform, which somebody may have been editing
  and which reviewers may already have decided about.

Copying either repository side over the draft destroys work; copying the draft over the repository
is not this ticket's to do. What is safe is a **semantic three-way merge**: measure both sides
against the base, apply the incoming changes that touch nothing the draft touched, and hand back
every overlap as an explicit conflict that names where it is — in the document *and* in the
repository file — with all three values side by side.

This module is pure. It holds the refusal codes, the wire models, the plan fingerprint, the merge
itself (:func:`merge_documents`), and the two helpers that turn a pointer into a place a person can
open (:func:`locate_pointer_lines`, :func:`source_location_url`). There is no storage, no network
and no clock here; :mod:`app.spec_sync_store` owns those, :mod:`app.spec_sync_routes` the HTTP
surface, and apiome-db V266 the tables.

**Nothing here writes to a draft, and nothing it returns is an instruction to.** A merge result is a
reading of three documents. That is the whole reason a provider delivery can never overwrite work:
there is no code path from one to the other, only to a row somebody reads.

The diff underneath is :func:`app.source_change_review.diff_documents` — the same engine the
source-to-model review uses — so a change reads identically wherever the product shows one, and the
grouping is :func:`app.source_change_review.scope_for_pointer`.
"""

from __future__ import annotations

import bisect
import copy
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .preservation_envelope import format_pointer, parse_pointer
from .source_change_review import diff_documents, scope_for_pointer

__all__ = [
    "AUDIT_CONFLICT_RESOLVED",
    "AUDIT_PLANNED",
    "CODE_BASE_DRIFTED",
    "CODE_CONFLICT",
    "CODE_CONFLICT_NOT_FOUND",
    "CODE_CONFLICT_RESOLVED",
    "CODE_INVALID_DOCUMENT",
    "CODE_NOT_BOUND",
    "CODE_NOTHING_TO_MERGE",
    "CODE_PLAN_NOT_FOUND",
    "GUARDS",
    "GUARD_NONE",
    "GUARD_REVIEW_DECIDED",
    "GUARD_VERSION_PUBLISHED",
    "KINDS",
    "KIND_ADDITION",
    "KIND_DELETION",
    "KIND_UPDATE",
    "MAX_CONFLICTS",
    "MAX_NOTE_LENGTH",
    "MAX_VALUE_BYTES",
    "MergeChange",
    "MergeConflict",
    "MergeOutcome",
    "RESOLUTIONS",
    "RESOLUTION_DRAFT",
    "RESOLUTION_GIT",
    "STATUSES",
    "STATUS_CLEAN",
    "STATUS_CONFLICTED",
    "STATUS_MERGEABLE",
    "STATUS_RESOLVED",
    "SpecSyncValidationError",
    "SyncConflictRecord",
    "SyncConflictResolve",
    "SyncPlanCompute",
    "SyncPlanDetail",
    "SyncPlanRecord",
    "VersionSyncStatus",
    "bounded_value",
    "locate_pointer_lines",
    "merge_documents",
    "plan_fingerprint",
    "pointer_segments",
    "resolve_pointer",
    "source_location_url",
]

# ---------------------------------------------------------------------------------------------
# Vocabulary — mirrors the V266 CHECK constraints
# ---------------------------------------------------------------------------------------------

#: The repository changed nothing since the base; there is nothing to merge.
STATUS_CLEAN = "clean"
#: Incoming changes exist and none of them overlap the draft's own.
STATUS_MERGEABLE = "mergeable"
#: At least one overlap is outstanding.
STATUS_CONFLICTED = "conflicted"
#: Every conflict has been settled towards one side.
STATUS_RESOLVED = "resolved"
STATUSES = (STATUS_CLEAN, STATUS_MERGEABLE, STATUS_CONFLICTED, STATUS_RESOLVED)

#: The merge result may be acted on.
GUARD_NONE = "none"
#: An open review on this version already holds a recorded decision, which a merge would invalidate.
GUARD_REVIEW_DECIDED = "review_decided"
#: The version is no longer a draft.
GUARD_VERSION_PUBLISHED = "version_published"
GUARDS = (GUARD_NONE, GUARD_REVIEW_DECIDED, GUARD_VERSION_PUBLISHED)

#: What one side did to the base at a pointer. Mirrors the V266 CHECK and
#: :class:`app.source_change_review.SourceChange`'s first three kinds.
KIND_ADDITION = "addition"
KIND_UPDATE = "update"
KIND_DELETION = "deletion"
KINDS = (KIND_ADDITION, KIND_UPDATE, KIND_DELETION)

#: Take the repository's value.
RESOLUTION_GIT = "git"
#: Keep what the draft has.
RESOLUTION_DRAFT = "draft"
RESOLUTIONS = (RESOLUTION_GIT, RESOLUTION_DRAFT)

#: ``workflow_audit`` actions, written inside the transaction of the change they record.
AUDIT_PLANNED = "sync.planned"
AUDIT_CONFLICT_RESOLVED = "sync.conflict_resolved"

# Stable refusal codes. A client branches on the code, never on the message.
#: The version has no active binding, so there is no repository to merge against.
CODE_NOT_BOUND = "sync-not-bound"
#: The binding's synchronized commit no longer holds the bytes its digest describes — somebody
#: rewrote history under the merge base, and a merge against it would be a guess.
CODE_BASE_DRIFTED = "sync-base-drifted"
#: One of the three documents could not be read as a spec document.
CODE_INVALID_DOCUMENT = "sync-invalid-document"
#: There is nothing to merge: the ref is exactly where the binding already is.
CODE_NOTHING_TO_MERGE = "sync-nothing-to-merge"
CODE_PLAN_NOT_FOUND = "sync-plan-not-found"
CODE_CONFLICT_NOT_FOUND = "sync-conflict-not-found"
#: The conflict already settled; settlements are final.
CODE_CONFLICT_RESOLVED = "sync-conflict-resolved"
#: Someone else changed the plan between the read and the write; read it again and retry.
CODE_CONFLICT = "sync-conflict"

#: The longest resolution note, in characters. Matches the binding store's bound.
MAX_NOTE_LENGTH = 2_000

#: How many conflicts one plan records. A merge that collides in more places than this is not a
#: merge anybody resolves one row at a time, and storing thousands of subtrees would make the row
#: the problem; the plan says so with ``conflicts_truncated``.
MAX_CONFLICTS = 200

#: How large a single stored value may be, serialized. Beyond it the value is replaced by a marker
#: (:func:`bounded_value`), because a conflict row is read straight into a browser response and one
#: enormous subtree would make every other conflict unreadable.
MAX_VALUE_BYTES = 32_768

#: Longest document text :func:`locate_pointer_lines` will compose. Above it the merge still works;
#: conflicts simply carry no line number.
MAX_LOCATED_BYTES = 4_000_000

Guard = Literal["none", "review_decided", "version_published"]
PlanStatus = Literal["clean", "mergeable", "conflicted", "resolved"]
ChangeKind = Literal["addition", "update", "deletion"]
Resolution = Literal["git", "draft"]

#: Sentinel for "this pointer resolves to nothing". ``None``, ``False`` and empty containers are all
#: legal JSON values, so absence needs a value none of them can be mistaken for.
_ABSENT = object()


class SpecSyncValidationError(Exception):
    """A refusal from the synchronization store, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
        """
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Pointer helpers
# ---------------------------------------------------------------------------------------------


def pointer_segments(pointer: str) -> Tuple[str, ...]:
    """Return a pointer's unescaped segments, treating an invalid pointer as the root.

    Args:
        pointer: An RFC 6901 pointer.

    Returns:
        The segments; ``()`` for the root pointer or for anything unparseable.
    """
    try:
        return tuple(parse_pointer(pointer))
    except ValueError:
        return ()


def resolve_pointer(document: Any, segments: Sequence[str]) -> Any:
    """Return the value a pointer addresses, or the absence sentinel.

    Args:
        document: The document to walk.
        segments: Unescaped pointer segments.

    Returns:
        The addressed value, or :data:`_ABSENT` when any segment does not resolve.
    """
    current: Any = document
    for segment in segments:
        if isinstance(current, dict):
            if segment not in current:
                return _ABSENT
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit():
                return _ABSENT
            index = int(segment)
            if index >= len(current):
                return _ABSENT
            current = current[index]
        else:
            return _ABSENT
    return current


def _kind_at(base_present: bool, side_present: bool) -> str:
    """Classify what one side did to the base at a pointer.

    Args:
        base_present: Whether the base resolves the pointer.
        side_present: Whether the side resolves it.

    Returns:
        ``addition``, ``deletion``, or ``update``.
    """
    if not base_present and side_present:
        return KIND_ADDITION
    if base_present and not side_present:
        return KIND_DELETION
    return KIND_UPDATE


def _apply_order(segments: Tuple[str, ...]) -> Tuple[Any, ...]:
    """Deterministic apply order: parents before children, numeric-aware within a parent.

    Args:
        segments: The change's pointer segments.

    Returns:
        A sort key that orders shallow pointers first and ``/a/2`` before ``/a/10``.
    """
    key: List[Tuple[int, Any]] = []
    for segment in segments:
        if segment.isdigit():
            key.append((0, int(segment)))
        else:
            key.append((1, segment))
    return (len(segments), tuple(key))


def _set_pointer(document: Any, segments: Sequence[str], value: Any) -> None:
    """Write ``value`` at ``segments``, creating missing containers by segment shape.

    A numeric segment makes a list, anything else a dict. A list index at or past the end appends,
    which is how a trailing array addition lands deterministically.

    Args:
        document: The document to modify in place.
        segments: Unescaped pointer segments; must be non-empty.
        value: The value to write.
    """
    current: Any = document
    for index, segment in enumerate(segments[:-1]):
        nxt = segments[index + 1]
        if isinstance(current, list):
            if not segment.isdigit():
                return
            position = int(segment)
            if position >= len(current):
                return
            if current[position] is None:
                current[position] = [] if nxt.isdigit() else {}
            current = current[position]
        elif isinstance(current, dict):
            if segment not in current or not isinstance(current[segment], (dict, list)):
                current[segment] = [] if nxt.isdigit() else {}
            current = current[segment]
        else:
            return
    last = segments[-1]
    if isinstance(current, list):
        if not last.isdigit():
            return
        position = min(int(last), len(current))
        if position == len(current):
            current.append(value)
        else:
            current[position] = value
    elif isinstance(current, dict):
        current[last] = value


def _delete_pointer(document: Any, segments: Sequence[str]) -> None:
    """Remove whatever ``segments`` addresses, if anything does.

    Args:
        document: The document to modify in place.
        segments: Unescaped pointer segments; must be non-empty.
    """
    parent = resolve_pointer(document, segments[:-1])
    if parent is _ABSENT:
        return
    last = segments[-1]
    if isinstance(parent, dict):
        parent.pop(last, None)
    elif isinstance(parent, list) and last.isdigit():
        index = int(last)
        if index < len(parent):
            parent.pop(index)


# ---------------------------------------------------------------------------------------------
# Merge results
# ---------------------------------------------------------------------------------------------


class MergeChange(BaseModel):
    """One incoming change the merge applied because nothing in the draft touched it."""

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(description="RFC 6901 pointer of the changed value.")
    kind: ChangeKind = Field(description="`addition`, `update`, or `deletion`.")
    scope: str = Field(description="`document`, `path`, `operation`, `component`, or `schema`.")
    group: str = Field(description="Stable group key within the scope, e.g. `GET /pets`.")
    label: str = Field(description="One line describing the change.")
    before: Any = Field(default=None, description="The base value; null for an addition.")
    after: Any = Field(default=None, description="The incoming value; null for a deletion.")
    source_file: str = Field(default="", description="Repository file the incoming value is in.")
    source_line: Optional[int] = Field(
        default=None, ge=1, description="1-based line in `source_file`, when it could be located."
    )


class MergeConflict(BaseModel):
    """One place both sides moved away from the base, in different directions."""

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(description="RFC 6901 pointer of the collision.")
    scope: str = Field(description="`document`, `path`, `operation`, `component`, or `schema`.")
    group: str = Field(description="Stable group key within the scope.")
    label: str = Field(description="One line describing the collision.")
    git_kind: ChangeKind = Field(description="What the repository did here.")
    draft_kind: ChangeKind = Field(description="What the draft did here.")
    base_value: Any = Field(default=None, description="The value at the merge base.")
    git_value: Any = Field(default=None, description="The repository's value.")
    draft_value: Any = Field(default=None, description="The draft's value.")
    source_file: str = Field(default="", description="Repository file the incoming value is in.")
    source_line: Optional[int] = Field(
        default=None, ge=1, description="1-based line in `source_file`, when it could be located."
    )


class MergeOutcome(BaseModel):
    """What a three-way merge found, and the document it would produce.

    ``merged`` is the draft with every :attr:`changes` entry applied — nothing else. It is returned
    so a caller can show or verify the deterministic result; writing it anywhere is deliberately
    not this module's business.
    """

    model_config = ConfigDict(extra="forbid")

    status: PlanStatus = Field(description="`clean`, `mergeable`, or `conflicted`.")
    changes: List[MergeChange] = Field(
        default_factory=list, description="Incoming changes applied deterministically."
    )
    conflicts: List[MergeConflict] = Field(
        default_factory=list, description="Overlaps left for a person, in pointer order."
    )
    agreed_count: int = Field(
        default=0, ge=0, description="Places both sides changed to the same value."
    )
    local_count: int = Field(
        default=0, ge=0, description="Places only the draft changed; the merge leaves them alone."
    )
    conflicts_truncated: bool = Field(
        default=False, description="True when more than `MAX_CONFLICTS` collisions were found."
    )
    merged: Dict[str, Any] = Field(
        default_factory=dict, description="The draft with `changes` applied; never written anywhere."
    )


# ---------------------------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------------------------


def _overlapping(
    pointer_key: Tuple[str, ...], others: Dict[Tuple[str, ...], str], ordered: List[Tuple[str, ...]]
) -> List[Tuple[str, ...]]:
    """Return every pointer in ``others`` that is, contains, or is contained by ``pointer_key``.

    Both sides' deltas are pairwise non-overlapping within themselves (the diff stops recursing
    once it has emitted a change), so overlap only ever happens across the two sides — and it is
    exactly what "these two changes are about the same place" means.

    Args:
        pointer_key: The segments of the pointer being classified.
        others: The other side's deltas, keyed by segments.
        ordered: ``others``' keys, sorted — descendants of a pointer are contiguous in that order.

    Returns:
        The overlapping keys, shallowest first.
    """
    hits: List[Tuple[str, ...]] = []
    # Ancestors, including the pointer itself: a handful of dictionary lookups.
    for depth in range(len(pointer_key) + 1):
        prefix = pointer_key[:depth]
        if prefix in others:
            hits.append(prefix)
    # Descendants: sorted tuples put every key starting with pointer_key in one run.
    start = bisect.bisect_right(ordered, pointer_key)
    for index in range(start, len(ordered)):
        candidate = ordered[index]
        if candidate[: len(pointer_key)] != pointer_key:
            break
        hits.append(candidate)
    return hits


def _describe(pointer: str, kind: str) -> Tuple[str, str, str]:
    """Return ``(scope, group, label)`` for a pointer, in the product's change vocabulary.

    Args:
        pointer: The RFC 6901 pointer.
        kind: ``addition``, ``update``, or ``deletion``.

    Returns:
        The scope, the stable group key, and a one-line human label.
    """
    scope, group = scope_for_pointer(pointer)
    verb = {KIND_ADDITION: "Added", KIND_UPDATE: "Changed", KIND_DELETION: "Removed"}[kind]
    where = pointer or "/"
    if scope == "document":
        return scope, group, f"{verb} {where}"
    return scope, group, f"{verb} {scope} {group} at {where}"


def merge_documents(
    base: Mapping[str, Any],
    git: Mapping[str, Any],
    draft: Mapping[str, Any],
    *,
    lines: Optional[Mapping[str, int]] = None,
    source_file: str = "",
    max_conflicts: int = MAX_CONFLICTS,
) -> MergeOutcome:
    """Merge the repository's changes into the draft, against their common base.

    Both sides are diffed against the base. An incoming change whose place the draft left alone is
    applied; one that lands where the draft also moved is a **conflict**, reported at the widest
    pointer the two changes share so the reader sees the whole collision rather than a fragment of
    it. Where both sides made the same change there is nothing to do, and where only the draft
    moved the merge keeps out of the way.

    The result is a function of the three inputs alone: the same trio always produces the same
    changes, in the same order, and the same merged document. None of the inputs is modified.

    Args:
        base: The document at the merge base — the last point the two sides agreed.
        git: The document as the repository now has it.
        draft: The document as this platform now has it.
        lines: Pointer -> 1-based line in the incoming source, from
            :func:`locate_pointer_lines`; optional.
        source_file: Repository-relative path of the incoming document, for the locations.
        max_conflicts: How many conflicts to report before truncating.

    Returns:
        The :class:`MergeOutcome`.
    """
    located = dict(lines or {})
    git_deltas = {
        pointer_segments(delta["pointer"]): delta for delta in diff_documents(base, git)
    }
    draft_deltas = {
        pointer_segments(delta["pointer"]): delta for delta in diff_documents(base, draft)
    }
    git_keys = sorted(git_deltas)
    draft_keys = sorted(draft_deltas)

    applied: List[MergeChange] = []
    conflicts: Dict[Tuple[str, ...], MergeConflict] = {}
    # Places, not deltas: two incoming changes under one replaced draft subtree are one agreement
    # and one collision, not two of each.
    agreed: Dict[Tuple[str, ...], bool] = {}
    # Every draft delta an incoming change collided with; the rest are the draft's alone.
    entangled: Dict[Tuple[str, ...], bool] = {}

    for key in git_keys:
        delta = git_deltas[key]
        pointer = str(delta["pointer"])
        overlaps = _overlapping(key, draft_deltas, draft_keys)
        if not overlaps:
            scope, group, label = _describe(pointer, str(delta["kind"]))
            applied.append(
                MergeChange(
                    pointer=pointer,
                    kind=str(delta["kind"]),
                    scope=scope,
                    group=group,
                    label=label,
                    before=delta.get("before"),
                    after=delta.get("after"),
                    source_file=source_file,
                    source_line=located.get(pointer),
                )
            )
            continue

        entangled.update({overlap: True for overlap in overlaps})
        # The widest place the two sides both touched: a draft change *above* the incoming one is
        # the real collision, and reporting the narrower incoming pointer would hide it.
        widest = min([key, *overlaps], key=len)
        git_value = resolve_pointer(git, widest)
        draft_value = resolve_pointer(draft, widest)
        if git_value is draft_value or (
            git_value is not _ABSENT and draft_value is not _ABSENT and git_value == draft_value
        ):
            # Both sides arrived at the same place. There is nothing to apply and nothing to decide.
            agreed[widest] = True
            continue

        base_value = resolve_pointer(base, widest)
        conflict_pointer = format_pointer(list(widest))
        git_kind = _kind_at(base_value is not _ABSENT, git_value is not _ABSENT)
        draft_kind = _kind_at(base_value is not _ABSENT, draft_value is not _ABSENT)
        scope, group, label = _describe(conflict_pointer, git_kind)
        conflicts[widest] = MergeConflict(
            pointer=conflict_pointer,
            scope=scope,
            group=group,
            label=label,
            git_kind=git_kind,
            draft_kind=draft_kind,
            base_value=None if base_value is _ABSENT else base_value,
            git_value=None if git_value is _ABSENT else git_value,
            draft_value=None if draft_value is _ABSENT else draft_value,
            source_file=source_file,
            source_line=located.get(conflict_pointer),
        )

    local = len([key for key in draft_keys if key not in entangled])

    ordered_conflicts = [conflicts[key] for key in sorted(conflicts)]
    truncated = len(ordered_conflicts) > max_conflicts
    if truncated:
        ordered_conflicts = ordered_conflicts[:max_conflicts]

    merged = _merge_document(draft, applied)
    # A merge with no incoming deltas at all is the only truly clean one; V266 says so as a CHECK,
    # because "clean" must mean "the repository changed nothing", not "nothing needed doing".
    if conflicts:
        status: str = STATUS_CONFLICTED
    elif git_keys:
        status = STATUS_MERGEABLE
    else:
        status = STATUS_CLEAN

    return MergeOutcome(
        status=status,
        changes=applied,
        conflicts=ordered_conflicts,
        agreed_count=len(agreed),
        local_count=local,
        conflicts_truncated=truncated,
        merged=merged,
    )


def _merge_document(draft: Mapping[str, Any], changes: Sequence[MergeChange]) -> Dict[str, Any]:
    """Return the draft with every applied change written into a copy of it.

    Order is what makes this deterministic and correct for arrays: parents before children, and
    within one parent, deletions from the highest index down so earlier removals never shift a
    later one, then additions and updates from the lowest index up so a trailing append lands where
    the repository put it.

    Args:
        draft: The document to start from; not modified.
        changes: The changes to apply.

    Returns:
        The merged document.
    """
    merged = copy.deepcopy(dict(draft))
    deletions = [c for c in changes if c.kind == KIND_DELETION]
    writes = [c for c in changes if c.kind != KIND_DELETION]
    for change in sorted(
        deletions, key=lambda c: _apply_order(pointer_segments(c.pointer)), reverse=True
    ):
        segments = pointer_segments(change.pointer)
        if segments:
            _delete_pointer(merged, segments)
    for change in sorted(writes, key=lambda c: _apply_order(pointer_segments(c.pointer))):
        segments = pointer_segments(change.pointer)
        if segments:
            _set_pointer(merged, segments, change.after)
    return merged


# ---------------------------------------------------------------------------------------------
# Locating a pointer in the repository source
# ---------------------------------------------------------------------------------------------


def locate_pointer_lines(text: str, *, max_bytes: int = MAX_LOCATED_BYTES) -> Dict[str, int]:
    """Map every pointer in a JSON or YAML document to the 1-based line it starts on.

    A conflict that only says ``/paths/~1pets/get/summary`` makes a reader search; one that says
    ``openapi.yaml:42`` makes it a link. The document is composed rather than loaded, so the node
    marks survive, and a mapping entry reports its **key's** line — in block YAML the value of
    ``summary:`` on its own line starts on the next one, which is not where anybody would look.

    JSON is a subset of YAML for every construct a spec document uses, so one composer serves both.
    Anything that cannot be composed simply yields no locations: a merge without line numbers is
    still a merge.

    Args:
        text: The document source.
        max_bytes: Above this size the document is not composed at all.

    Returns:
        Pointer -> line. Empty when the text is absent, oversized, or not composable.
    """
    if not text or len(text.encode("utf-8", errors="replace")) > max_bytes:
        return {}
    try:
        root = yaml.compose(text)
    except (yaml.YAMLError, RecursionError, ValueError):
        return {}
    if root is None:
        return {}
    out: Dict[str, int] = {}
    _locate_into(root, [], root.start_mark.line + 1, out)
    return out


def _locate_into(node: Any, segments: List[str], line: int, out: Dict[str, int]) -> None:
    """Record ``node``'s line and recurse into its children.

    Args:
        node: A composed YAML node.
        segments: The pointer segments that address it.
        line: The 1-based line to record for it.
        out: The accumulating pointer -> line map.
    """
    out.setdefault(format_pointer(segments), line)
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key = getattr(key_node, "value", None)
            if not isinstance(key, str):
                continue
            _locate_into(value_node, segments + [key], key_node.start_mark.line + 1, out)
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            _locate_into(item, segments + [str(index)], item.start_mark.line + 1, out)


def source_location_url(
    provider: str, repo_url: str, commit_sha: str, file_path: str, line: Optional[int]
) -> str:
    """Build the human URL for one line of one file at one commit.

    Args:
        provider: The provider key.
        repo_url: The canonical repository URL.
        commit_sha: The commit to link at — never a branch, which moves.
        file_path: The repository-relative file.
        line: The 1-based line, when there is one.

    Returns:
        The URL, or ``""`` for a provider whose blob layout is not known here or when the file is
        unknown.
    """
    base = (repo_url or "").rstrip("/")
    sha = (commit_sha or "").strip()
    path = (file_path or "").strip().strip("/")
    if not base or not sha or not path:
        return ""
    if provider == "github":
        url = f"{base}/blob/{sha}/{path}"
        return f"{url}#L{line}" if line else url
    if provider == "gitlab":
        url = f"{base}/-/blob/{sha}/{path}"
        return f"{url}#L{line}" if line else url
    if provider == "bitbucket":
        url = f"{base}/src/{sha}/{path}"
        return f"{url}#lines-{line}" if line else url
    return ""


# ---------------------------------------------------------------------------------------------
# Fingerprints and bounds
# ---------------------------------------------------------------------------------------------


def plan_fingerprint(
    binding_id: str, base_commit_sha: str, git_commit_sha: str, draft_digest: str
) -> str:
    """Return the idempotency key of a merge of one binding's three documents.

    Every input is known *before* any repository read, which is what makes a rerun free as well as
    idempotent: the same trio finds the stored plan instead of fetching two commits again to
    recompute an answer nobody's inputs have changed.

    The draft is identified by its content digest rather than by its revision id, because a
    revision that has been edited is a different document and must not reuse an older merge.

    Args:
        binding_id: The binding the merge belongs to.
        base_commit_sha: The commit the binding is synchronized with.
        git_commit_sha: The commit the ref moved to.
        draft_digest: The draft document's content fingerprint.

    Returns:
        ``"sha256:<hex>"``.
    """
    digest = hashlib.sha256()
    for part in (binding_id, base_commit_sha, git_commit_sha, draft_digest):
        blob = str(part or "").encode("utf-8")
        digest.update(str(len(blob)).encode("ascii"))
        digest.update(b"\0")
        digest.update(blob)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def bounded_value(value: Any, *, max_bytes: int = MAX_VALUE_BYTES) -> Any:
    """Return a value fit to store and to send to a browser, or a marker standing in for it.

    Args:
        value: Any JSON-compatible value.
        max_bytes: The serialized size above which the value is replaced.

    Returns:
        The value unchanged, or ``{"$truncated": True, "bytes": n}`` when it is too large or
        cannot be serialized at all.
    """
    try:
        blob = json.dumps(value, separators=(",", ":"), default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive; inputs are parsed JSON
        return {"$truncated": True, "bytes": 0}
    size = len(blob.encode("utf-8"))
    if size <= max_bytes:
        return value
    return {"$truncated": True, "bytes": size}


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------


class SyncConflictRecord(BaseModel):
    """One stored conflict — outstanding or settled."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The conflict id.")
    plan_id: str
    pointer: str = Field(description="RFC 6901 pointer of the collision.")
    scope: str = Field(description="`document`, `path`, `operation`, `component`, or `schema`.")
    group_key: str = Field(default="", description="Stable group key within the scope.")
    label: str = Field(default="", description="One line describing the collision.")
    git_kind: ChangeKind = Field(description="What the repository did here.")
    draft_kind: ChangeKind = Field(description="What the draft did here.")
    base_value: Any = Field(default=None, description="The value at the merge base.")
    git_value: Any = Field(default=None, description="The repository's value.")
    draft_value: Any = Field(default=None, description="The draft's value.")
    source_file: str = Field(default="", description="Repository file the incoming value is in.")
    source_line: Optional[int] = Field(
        default=None, ge=1, description="1-based line in `source_file`, when it could be located."
    )
    source_url: str = Field(default="", description="Human URL for that file and line.")
    resolution: Optional[Resolution] = Field(
        default=None, description="`git`, `draft`, or null while outstanding."
    )
    resolved_at: Optional[datetime] = Field(default=None, description="When it settled.")
    resolved_by: Optional[str] = Field(default=None, description="Who settled it.")
    resolved_by_name: Optional[str] = Field(default=None, description="Their display name.")
    resolution_note: Optional[str] = Field(default=None, description="Why, in their words.")
    created_at: datetime


class SyncPlanRecord(BaseModel):
    """One stored three-way merge result."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The plan id.")
    tenant_id: str
    binding_id: str
    project_id: str
    version_id: str
    candidate_id: Optional[str] = Field(
        default=None, description="The ref movement that prompted the merge, when one did."
    )
    base_commit_sha: str = Field(description="The commit the binding is synchronized with.")
    base_digest: str = Field(description="Fileset digest of the selection at `base_commit_sha`.")
    git_commit_sha: str = Field(description="The commit the ref moved to.")
    git_digest: str = Field(description="Fileset digest of the selection read at `git_commit_sha`.")
    draft_digest: str = Field(description="Content fingerprint of the reconstructed draft document.")
    plan_fingerprint: str = Field(description="The rerun idempotency key.")
    status: PlanStatus = Field(description="`clean`, `mergeable`, `conflicted`, or `resolved`.")
    auto_applied_count: int = Field(ge=0, description="Incoming changes applied deterministically.")
    local_count: int = Field(ge=0, description="Places only the draft changed.")
    agreed_count: int = Field(ge=0, description="Places both sides changed to the same value.")
    conflict_count: int = Field(ge=0, description="Collisions the merge found and stored.")
    unresolved_count: int = Field(ge=0, description="Collisions still waiting on somebody.")
    conflicts_truncated: bool = Field(
        default=False,
        description=(
            "True when the merge found more collisions than a plan stores, so the ones below are "
            "a page of a longer list."
        ),
    )
    changes: List[MergeChange] = Field(
        default_factory=list, description="The applied incoming changes."
    )
    source_file: str = Field(default="", description="Repository file the incoming document is.")
    source_member_count: int = Field(default=0, ge=0, description="Files the selection resolved to.")
    guard: Guard = Field(
        description="Why the result may not become an edit of the draft, when it may not."
    )
    stale: bool = Field(
        default=False,
        description=(
            "True when the draft has been edited since the merge ran, so the result describes a "
            "document that no longer exists."
        ),
    )
    computed_by: Optional[str] = Field(default=None, description="Who ran the merge.")
    computed_by_name: Optional[str] = Field(default=None, description="Their display name.")
    created_at: datetime
    updated_at: datetime


class SyncPlanDetail(BaseModel):
    """A merge result with its conflicts."""

    model_config = ConfigDict(extra="forbid")

    plan: SyncPlanRecord
    conflicts: List[SyncConflictRecord] = Field(
        default_factory=list, description="Every conflict, outstanding ones first."
    )


class VersionSyncStatus(BaseModel):
    """Where one version stands with respect to merging its repository ref."""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    version_label: Optional[str] = None
    bound: bool = Field(description="Whether the version has an active binding to merge against.")
    latest: Optional[SyncPlanDetail] = Field(
        default=None, description="The most recent merge result, with its conflicts."
    )
    history: List[SyncPlanRecord] = Field(
        default_factory=list, description="Earlier merge results, newest first."
    )


# ---------------------------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------------------------


class SyncPlanCompute(BaseModel):
    """Compute a three-way merge of a bound draft against its repository ref."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: Optional[str] = Field(
        default=None,
        description=(
            "The outstanding sync candidate to merge. Defaults to the binding's oldest pending "
            "candidate, which is the one a reader is looking at."
        ),
    )
    refresh: bool = Field(
        default=False,
        description=(
            "Re-read both commits even when a merge of the same three documents is already "
            "stored. The stored result is still what is returned when the inputs are unchanged, "
            "because the same inputs cannot produce a different merge."
        ),
    )


class SyncConflictResolve(BaseModel):
    """Settle one conflict towards one side.

    Attributes:
        resolution: ``git`` takes the repository's value, ``draft`` keeps the version's. There is
            no third option: a merge result records a decision, it does not edit a document.
        note: Why, kept with the settled row.
    """

    model_config = ConfigDict(extra="forbid")

    resolution: Resolution
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH)
