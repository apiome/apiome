"""Breaking-change classification for MCP surface diffs (V2-MCP-30.3 / MCAT-16.3, #4638).

A surface diff (an ``mcp_version_changes`` row, or the equivalent dict the diff engine
emits) records *that* a capability changed but not *how much it matters*: a ``modified``
tool might be a harmless description tweak or a breaking input-schema tightening. This
module is the pure, deterministic classifier that assigns each change a **severity**, so
consumers — the churn timeline's markers (MCAT-16.1), the grade/surface trend overlay
(MCAT-16.4), and ``insight/evolution`` — can tell safe evolution apart from breaks a
client aligned to the *before* surface would trip over.

Three severities, ordered least → most disruptive (:data:`SEVERITY_ORDER`):

* :data:`SEVERITY_ADDITIVE` — a client built against the *before* surface keeps working:
  a newly added capability, a new optional parameter, a loosened constraint, or a purely
  descriptive edit (``title`` / ``description``).
* :data:`SEVERITY_REVIEW` — the change is real but its impact cannot be decided
  deterministically from the diff alone: an annotation flip, a resource URI / ``mimeType``
  move, a reshaped schema keyword (``pattern`` / ``oneOf`` / …), a protocol or declared-
  capabilities shift, or a schema that appeared / vanished / arrived in an unexpected
  shape. Per the ticket, unknown / edge cases land here rather than being silently called
  additive.
* :data:`SEVERITY_BREAKING` — a client built against the *before* surface can break: a
  removed capability, or a modification that adds a required parameter, removes a
  parameter, narrows an enum, or changes a type.

The design mirrors the diff engine (:mod:`app.mcp_client.diff`, MCAT-4.2): a pure function
of the change payload, deterministic (no clock, no ordering dependence), with JSON-Schema
comparison delegated to the shared :func:`app.schema_compatibility.classify_schema_change`
helper so the MCP and OpenAPI surfaces judge "breaking" the same way.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Mapping, Optional

from app.mcp_client.diff import (
    CHANGE_ADDED,
    CHANGE_MODIFIED,
    CHANGE_REMOVED,
    ITEM_TYPE_SERVER,
)
from app.schema_compatibility import classify_schema_change

# ---------------------------------------------------------------------------
# Severities
# ---------------------------------------------------------------------------

SEVERITY_ADDITIVE = "additive"
SEVERITY_REVIEW = "review"
SEVERITY_BREAKING = "breaking"

#: Severities from least to most disruptive; the index is each severity's rank, so
#: :func:`_max_severity` can fold a set of field verdicts into the worst one.
SEVERITY_ORDER = (SEVERITY_ADDITIVE, SEVERITY_REVIEW, SEVERITY_BREAKING)
_SEVERITY_RANK: Dict[str, int] = {name: rank for rank, name in enumerate(SEVERITY_ORDER)}

# A capability field whose change never breaks a client: purely descriptive text. Every
# other field is decided by a dedicated rule below; anything unrecognized defaults to
# ``review`` (never silent ``additive``).
_DESCRIPTIVE_FIELDS = frozenset({"title", "description"})

# The capability item's stable identity key — present in every fingerprint projection but,
# being the pairing key, never actually differs for a matched (``modified``) item.
_IDENTITY_FIELD = "name"

# Surface-level (``item_type == "server"``) fields that are purely informational: their
# value moving does not break a client. Every other server field (``protocol_version``,
# ``capabilities``, or any future addition) is treated as ``review`` — a structural shift
# a client may need to react to, but not deterministically breaking.
_ADDITIVE_SERVER_FIELDS = frozenset(
    {"server_name", "server_title", "server_version", "instructions"}
)

# JSON-Schema comparison verdict → severity. ``safe`` (identical or only additive/loosening
# edits) is additive; ``breaking`` is breaking; ``unknown`` (manual-review-worthy) is review.
_SCHEMA_CATEGORY_TO_SEVERITY: Dict[str, str] = {
    "breaking": SEVERITY_BREAKING,
    "unknown": SEVERITY_REVIEW,
    "safe": SEVERITY_ADDITIVE,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_change(change: Mapping[str, Any]) -> str:
    """Classify one surface change as ``additive`` / ``review`` / ``breaking``.

    Pure and deterministic: the verdict depends only on ``change`` (a persisted
    ``mcp_version_changes`` row or a dict from :meth:`SurfaceDiff.to_change_rows` — the
    keys are identical). The rules:

    * A **removed** item is always ``breaking`` (a capability disappeared).
    * An **added** item is always ``additive`` (new surface a client need not have used).
    * A **modified** server-metadata field is ``additive`` when purely informational
      (name / title / version / instructions) and ``review`` otherwise.
    * A **modified** capability item is the worst severity across its changed fields:
      descriptive edits are ``additive``; ``inputSchema`` / ``outputSchema`` are judged by
      :func:`app.schema_compatibility.classify_schema_change`; a prompt's ``arguments`` are
      judged param-style (removed / newly-required arg = breaking); every other field, and
      any malformed / half-populated payload, defaults to ``review``.

    Args:
        change: A change record with ``change_type``, ``item_type``, ``item_name``, and a
            ``detail`` object carrying ``before`` / ``after`` fingerprint projections.

    Returns:
        One of :data:`SEVERITY_ADDITIVE`, :data:`SEVERITY_REVIEW`, :data:`SEVERITY_BREAKING`.
    """
    change_type = str(change.get("change_type") or "")
    item_type = str(change.get("item_type") or "")
    detail = change.get("detail")
    if not isinstance(detail, dict):
        detail = {}

    if change_type == CHANGE_REMOVED:
        return SEVERITY_BREAKING
    if change_type == CHANGE_ADDED:
        return SEVERITY_ADDITIVE
    if change_type != CHANGE_MODIFIED:
        # An unrecognized change direction is an edge case, not a safe one.
        return SEVERITY_REVIEW

    if item_type == ITEM_TYPE_SERVER:
        return _classify_server_field(change.get("item_name"))

    before = detail.get("before")
    after = detail.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        # A modification must carry both projections to be judged; without them, review.
        return SEVERITY_REVIEW
    return _classify_item_modification(before, after)


def severity_counts(changes: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Tally a collection of changes by severity, plus a ``total``.

    Args:
        changes: Any iterable of change records (see :func:`classify_change`).

    Returns:
        A dict with ``breaking`` / ``additive`` / ``review`` counts and their ``total``
        (always the number of changes classified).
    """
    counts = {SEVERITY_BREAKING: 0, SEVERITY_ADDITIVE: 0, SEVERITY_REVIEW: 0}
    total = 0
    for change in changes:
        counts[classify_change(change)] += 1
        total += 1
    counts["total"] = total
    return counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _max_severity(current: str, candidate: str) -> str:
    """Return the more disruptive of two severities (by :data:`SEVERITY_ORDER` rank)."""
    return candidate if _SEVERITY_RANK[candidate] > _SEVERITY_RANK[current] else current


def _classify_server_field(field_name: Any) -> str:
    """Classify a modified surface-metadata field by name (see :data:`_ADDITIVE_SERVER_FIELDS`)."""
    return (
        SEVERITY_ADDITIVE
        if str(field_name or "") in _ADDITIVE_SERVER_FIELDS
        else SEVERITY_REVIEW
    )


def _classify_item_modification(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Fold every changed field of a modified capability into its worst severity.

    Walks the union of the two fingerprint projections' keys in a fixed (sorted) order so
    the result is deterministic, skips fields whose canonical value is unchanged, and
    returns the maximum field severity — short-circuiting once ``breaking`` is reached
    (nothing can exceed it).
    """
    severity = SEVERITY_ADDITIVE
    for field in sorted(set(before) | set(after)):
        before_value = before.get(field)
        after_value = after.get(field)
        if _canonical(before_value) == _canonical(after_value):
            continue
        severity = _max_severity(severity, _classify_field(field, before_value, after_value))
        if severity == SEVERITY_BREAKING:
            return severity
    return severity


def _classify_field(field: str, before: Any, after: Any) -> str:
    """Classify a single changed capability field (its before ≠ after already established)."""
    if field == _IDENTITY_FIELD or field in _DESCRIPTIVE_FIELDS:
        return SEVERITY_ADDITIVE
    if field in ("inputSchema", "outputSchema"):
        return _classify_schema(before, after)
    if field == "arguments":
        return _classify_prompt_arguments(before, after)
    # uri / uriTemplate / mimeType / annotations / any unknown field — real but not
    # deterministically decidable, so review (never silent additive).
    return SEVERITY_REVIEW


def _classify_schema(before: Any, after: Any) -> str:
    """Classify a tool ``inputSchema`` / ``outputSchema`` before → after.

    Delegates two object schemas to :func:`classify_schema_change`. A schema that appeared,
    vanished, or arrived as a non-object shape is an edge case whose impact is not
    deterministically decidable, so it is ``review`` rather than silently ``additive``.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        return SEVERITY_REVIEW
    return _SCHEMA_CATEGORY_TO_SEVERITY.get(classify_schema_change(before, after), SEVERITY_REVIEW)


def _classify_prompt_arguments(before: Any, after: Any) -> str:
    """Classify a prompt's ``arguments`` list before → after, param-style.

    A prompt argument is ``{"name", "description"?, "required"?}``. Breaking, mirroring the
    JSON-Schema param rules: a removed argument, a new *required* argument, or an argument
    that went optional → required. Additive: a new optional argument, a required → optional
    loosening, or a description-only edit. A malformed list (a non-object or nameless entry)
    is ``review``.
    """
    if not isinstance(before, list) or not isinstance(after, list):
        return SEVERITY_REVIEW
    before_by = _arguments_by_name(before)
    after_by = _arguments_by_name(after)
    if before_by is None or after_by is None:
        return SEVERITY_REVIEW

    for name in before_by:
        if name not in after_by:
            return SEVERITY_BREAKING  # a parameter was removed
    for name, arg in after_by.items():
        if name not in before_by:
            if _arg_required(arg):
                return SEVERITY_BREAKING  # a new required parameter
            continue  # a new optional parameter — additive
        if _arg_required(arg) and not _arg_required(before_by[name]):
            return SEVERITY_BREAKING  # optional → required
    return SEVERITY_ADDITIVE


def _arguments_by_name(arguments: Iterable[Any]) -> Optional[Dict[str, Mapping[str, Any]]]:
    """Index a prompt ``arguments`` list by ``name``; ``None`` if any entry is malformed.

    An entry that is not an object, or an object without a string ``name``, means the shape
    is not the one this classifier reasons about — the caller falls back to ``review``.
    """
    by_name: Dict[str, Mapping[str, Any]] = {}
    for arg in arguments:
        if not isinstance(arg, Mapping):
            return None
        name = arg.get("name")
        if not isinstance(name, str):
            return None
        by_name[name] = arg
    return by_name


def _arg_required(arg: Mapping[str, Any]) -> bool:
    """Whether a prompt argument is required (a truthy ``required`` flag)."""
    return bool(arg.get("required"))


def _canonical(value: Any) -> str:
    """Byte-stable canonical JSON for equality, matching the diff engine's notion of equal.

    Object keys are sorted recursively so a mere key reshuffle never reads as a change.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
