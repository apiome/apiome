"""MCP surface diff engine (V2-MCP-18.2, #3669).

This layer answers a single question: *what changed between two normalized
capability surfaces?* Given any two :class:`~app.mcp_client.normalize.DiscoverySurface`
objects — a ``base`` and a ``target`` — :func:`diff_surfaces` returns a structured
:class:`SurfaceDiff` describing every item that was **added**, **removed**, or
**modified**, plus any server-metadata change, with before/after detail and counts.

Two consumers drive the design (per the roadmap, MCAT-4.2):

1. **Version-creation (MCAT-4.3).** When discovery produces a new snapshot, the
   ``previous → new`` diff is persisted as ``mcp_version_changes`` rows. Each
   :class:`ItemChange` maps cleanly to one such row via :meth:`ItemChange.to_change_row`.
2. **On-demand compare (MCAT-4.5).** A user may diff *any two* versions ``vX → vY``,
   not only adjacent ones. Because the engine compares the two surfaces *directly*
   (rather than chaining adjacent step-diffs) the result is exact for arbitrary pairs.

**What "changed" means.** The diff compares each surface's *semantic projection* —
exactly the fields that feed the surface fingerprint (V2-MCP-18.1): per item the
allow-listed :meth:`~app.mcp_client.normalize.CapabilityItem.fingerprint_projection`
(name, title, description, schema(s), annotations, prompt arguments, resource
mimeType/uri), and at the surface level the protocol version, server identity,
declared capabilities, and instructions. Volatile/vendor fields excluded from the
fingerprint (the reserved ``_meta`` block, a resource ``size`` hint, unknown
extension keys) are therefore invisible to the diff too. This keeps the engine in
lock-step with change detection: if two surfaces are *identical* their fingerprints
match and the diff is empty (:attr:`SurfaceDiff.fingerprint_unchanged` is ``True``).

**Item identity / stable keys.** Items are keyed by ``(item_type, name)``. ``name``
is required for every MCP capability kind and is the stable identity used to pair an
item across two surfaces — so renaming a tool reads as a remove + add, while editing
its description in place reads as a single modify. The result is fully deterministic:
changes are emitted in a fixed (kind, name) order regardless of discovery order, so
the same pair of surfaces always yields byte-identical output.

**Note on ordering-only changes.** The diff reports *semantic* item/server changes,
not list reordering. Two surfaces whose items are identical but reordered produce an
*empty* diff even though their fingerprints differ (the fingerprint preserves list
order). Callers that gate on "did anything change?" should consult the fingerprint
(or :attr:`SurfaceDiff.fingerprint_unchanged`); callers that render "what changed"
use the structured changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from .normalize import (
    FINGERPRINT_FIELDS,
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_RESOURCE_TEMPLATE,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)

# The three diff directions, mirroring ``mcp_version_changes.change_type`` (its CHECK
# constraint admits exactly these). An item present only in ``target`` is ``added``;
# present only in ``base`` is ``removed``; present in both with a differing semantic
# projection is ``modified``.
CHANGE_ADDED = "added"
CHANGE_REMOVED = "removed"
CHANGE_MODIFIED = "modified"

# The synthetic ``item_type`` used for surface-level (non-capability) changes. The
# ``mcp_version_changes.item_type`` column is deliberately a free VARCHAR (not the four
# capability kinds) precisely so server metadata changes can be recorded here too.
ITEM_TYPE_SERVER = "server"

# Deterministic emission order of changes by item type: server metadata first (it is
# the surface "header"), then the four capability kinds in their canonical order.
_ITEM_TYPE_RANK: Dict[str, int] = {
    ITEM_TYPE_SERVER: 0,
    ITEM_TYPE_TOOL: 1,
    ITEM_TYPE_RESOURCE: 2,
    ITEM_TYPE_RESOURCE_TEMPLATE: 3,
    ITEM_TYPE_PROMPT: 4,
}

# Surface-level fields compared for server-metadata changes, paired with the
# ``mcp_endpoint_versions`` column / ``item_name`` they are recorded under and a reader
# that extracts the field's *semantic* value from a surface's ``canonical_dict()`` (so
# ``capabilities`` is already ``_meta``-stripped and ``serverInfo`` is broken out).
_SERVER_FIELDS: Tuple[Tuple[str, Any], ...] = (
    ("protocol_version", lambda d: d["protocolVersion"]),
    ("server_name", lambda d: d["serverInfo"]["name"]),
    ("server_title", lambda d: d["serverInfo"]["title"]),
    ("server_version", lambda d: d["serverInfo"]["version"]),
    ("instructions", lambda d: d["instructions"]),
    ("capabilities", lambda d: d["capabilities"]),
)


# ===========================================================================
# Field-level change
# ===========================================================================


@dataclass(frozen=True)
class FieldChange:
    """One field that differs between a ``modified`` item's before and after states.

    Emitted only for ``modified`` capability items, one per semantically meaningful
    field whose value changed (e.g. ``description``, ``inputSchema``, ``annotations``).
    The field name is the *wire* spelling used in the fingerprint projection
    (``inputSchema``, not ``input_schema``).

    Attributes:
        field: The changed field's wire name (a key of ``FINGERPRINT_FIELDS[type]``).
        before: The field's value in the base surface (``None`` if absent there).
        after: The field's value in the target surface (``None`` if absent there).
    """

    field: str
    before: Any = None
    after: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """Render as a plain JSON-ready dict (``field``/``before``/``after``)."""
        return {"field": self.field, "before": self.before, "after": self.after}


# ===========================================================================
# Item-level change
# ===========================================================================


@dataclass(frozen=True)
class ItemChange:
    """One added / removed / modified entry in a surface diff.

    Covers both capability items (a tool/resource/resource_template/prompt keyed by
    name) and surface-level server metadata (``item_type == "server"``, ``name`` being
    the field, e.g. ``"instructions"``). Maps one-to-one onto an ``mcp_version_changes``
    row via :meth:`to_change_row`.

    Attributes:
        change_type: One of :data:`CHANGE_ADDED`/:data:`CHANGE_REMOVED`/:data:`CHANGE_MODIFIED`.
        item_type: The changed item's kind, or :data:`ITEM_TYPE_SERVER` for metadata.
        name: The item's ``name`` (capability) or the field name (server metadata).
        before: The item's semantic projection in the base surface; ``None`` for an
            addition. For server metadata, the field's prior value (may be ``None``).
        after: The item's semantic projection in the target surface; ``None`` for a
            removal. For server metadata, the field's new value (may be ``None``).
        fields: For a ``modified`` capability item, the per-field breakdown of what
            changed; empty for additions, removals, and server-metadata changes.
    """

    change_type: str
    item_type: str
    name: str
    before: Any = None
    after: Any = None
    fields: Tuple[FieldChange, ...] = ()

    # -- Serialization ------------------------------------------------------

    def to_detail(self) -> Dict[str, Any]:
        """Build the ``mcp_version_changes.detail`` JSON payload for this change.

        An addition carries only ``after``; a removal only ``before``; a modification
        both, plus a ``fields`` array (the :class:`FieldChange` breakdown) when the
        change is a capability item. Server-metadata modifications carry ``before`` and
        ``after`` (either may be ``null``) and no ``fields`` array.
        """
        if self.change_type == CHANGE_ADDED:
            return {"after": self.after}
        if self.change_type == CHANGE_REMOVED:
            return {"before": self.before}
        detail: Dict[str, Any] = {"before": self.before, "after": self.after}
        if self.fields:
            detail["fields"] = [change.to_dict() for change in self.fields]
        return detail

    def to_change_row(self, version_id: Any) -> Dict[str, Any]:
        """Map this change to an ``mcp_version_changes`` insert row.

        The DB assigns ``id`` and ``created_at``; this payload supplies the rest. The
        ``detail`` value is returned as a Python object (the caller serializes it to
        JSONB).

        Args:
            version_id: The owning ``mcp_endpoint_versions`` snapshot id — the version
                that *introduced* this change.

        Returns:
            A dict keyed by column name, ready to insert.
        """
        return {
            "version_id": version_id,
            "change_type": self.change_type,
            "item_type": self.item_type,
            "item_name": self.name,
            "detail": self.to_detail(),
        }


# ===========================================================================
# Surface-level diff
# ===========================================================================


@dataclass(frozen=True)
class SurfaceDiff:
    """The structured difference between two normalized surfaces.

    Produced by :func:`diff_surfaces`. The :attr:`changes` are deterministically
    ordered (server metadata first, then tools/resources/resource_templates/prompts,
    each by name), so the same pair of surfaces always yields identical output.

    Attributes:
        base_fingerprint: The base surface's :meth:`~app.mcp_client.normalize.DiscoverySurface.fingerprint`.
        target_fingerprint: The target surface's fingerprint.
        changes: Every add/remove/modify, in stable order.
    """

    base_fingerprint: str
    target_fingerprint: str
    changes: Tuple[ItemChange, ...] = ()

    # -- Predicates ---------------------------------------------------------

    @property
    def fingerprint_unchanged(self) -> bool:
        """Whether the two surfaces share a fingerprint (no semantic change at all).

        When ``True`` the surfaces are logically identical and :attr:`changes` is
        empty — the "fingerprint unchanged" signal MCAT-4.3 uses to *not* create a new
        version. (The converse does not strictly hold: a pure reordering of items
        leaves :attr:`changes` empty yet flips the fingerprint.)
        """
        return self.base_fingerprint == self.target_fingerprint

    def is_empty(self) -> bool:
        """Whether the diff records no item or server-metadata changes."""
        return not self.changes

    # -- Aggregates ---------------------------------------------------------

    @property
    def counts(self) -> Dict[str, int]:
        """Tally of changes by direction plus a ``total``.

        Returns a dict with ``added``/``removed``/``modified`` counts and their
        ``total`` (always ``len(changes)``).
        """
        tally = {CHANGE_ADDED: 0, CHANGE_REMOVED: 0, CHANGE_MODIFIED: 0}
        for change in self.changes:
            tally[change.change_type] += 1
        tally["total"] = len(self.changes)
        return tally

    # -- Serialization ------------------------------------------------------

    def to_change_rows(self, version_id: Any) -> List[Dict[str, Any]]:
        """Map every change to an ``mcp_version_changes`` insert row (in stable order).

        Args:
            version_id: The owning ``mcp_endpoint_versions`` snapshot id stamped on
                every row.

        Returns:
            One row per change (see :meth:`ItemChange.to_change_row`).
        """
        return [change.to_change_row(version_id) for change in self.changes]


# ===========================================================================
# Public entry point
# ===========================================================================


def diff_surfaces(base: DiscoverySurface, target: DiscoverySurface) -> SurfaceDiff:
    """Compute the structured diff from ``base`` to ``target``.

    Compares the two surfaces' *semantic projections* (the fingerprint view) and
    returns every capability item added/removed/modified and every server-metadata
    field that changed. The comparison is direction-aware: "added"/"removed" are
    relative to ``base`` (an item only in ``target`` is *added*), and "before"/"after"
    on a modification are ``base``/``target`` respectively. Works for any two surfaces
    — adjacent versions or arbitrarily distant ones — because it compares them directly
    rather than chaining adjacent diffs.

    Args:
        base: The earlier / "from" surface.
        target: The later / "to" surface.

    Returns:
        A :class:`SurfaceDiff` with both fingerprints and the ordered changes. When the
        surfaces are identical the result is empty and
        :attr:`SurfaceDiff.fingerprint_unchanged` is ``True``.
    """
    changes: List[ItemChange] = []
    changes.extend(_diff_server_metadata(base, target))
    changes.extend(_diff_items(ITEM_TYPE_TOOL, base.tools, target.tools))
    changes.extend(_diff_items(ITEM_TYPE_RESOURCE, base.resources, target.resources))
    changes.extend(
        _diff_items(
            ITEM_TYPE_RESOURCE_TEMPLATE,
            base.resource_templates,
            target.resource_templates,
        )
    )
    changes.extend(_diff_items(ITEM_TYPE_PROMPT, base.prompts, target.prompts))

    changes.sort(key=lambda change: (_ITEM_TYPE_RANK[change.item_type], change.name))

    return SurfaceDiff(
        base_fingerprint=base.fingerprint(),
        target_fingerprint=target.fingerprint(),
        changes=tuple(changes),
    )


# ===========================================================================
# Helpers
# ===========================================================================


def _diff_server_metadata(
    base: DiscoverySurface, target: DiscoverySurface
) -> List[ItemChange]:
    """Diff the surface-level identity fields (protocol, server info, capabilities,
    instructions).

    Each field is read from the surface's semantic projection (so ``capabilities`` is
    already ``_meta``-stripped) and compared canonically. A difference is recorded as a
    single ``modified`` :class:`ItemChange` under ``item_type == "server"`` with the
    field name as ``name`` and the before/after values carried in detail (either side
    may be ``None`` — e.g. instructions first appearing). Server fields are never
    classified add/remove: the field always exists on a surface, only its value moves.
    """
    base_dict = base.canonical_dict()
    target_dict = target.canonical_dict()
    changes: List[ItemChange] = []
    for field_name, reader in _SERVER_FIELDS:
        before = reader(base_dict)
        after = reader(target_dict)
        if _canonical(before) != _canonical(after):
            changes.append(
                ItemChange(
                    change_type=CHANGE_MODIFIED,
                    item_type=ITEM_TYPE_SERVER,
                    name=field_name,
                    before=before,
                    after=after,
                )
            )
    return changes


def _diff_items(
    item_type: str,
    base_items: Tuple[CapabilityItem, ...],
    target_items: Tuple[CapabilityItem, ...],
) -> List[ItemChange]:
    """Diff one capability kind's items, keyed by ``name``.

    Items only in ``target`` are additions, only in ``base`` removals, and those in
    both with a differing semantic projection are modifications (carrying the per-field
    :class:`FieldChange` breakdown). Items whose projections match exactly produce no
    change. The returned list is unordered here; :func:`diff_surfaces` applies the
    final stable ordering across all kinds.
    """
    base_by_name = {item.name: item for item in base_items}
    target_by_name = {item.name: item for item in target_items}
    changes: List[ItemChange] = []

    for name, item in target_by_name.items():
        if name not in base_by_name:
            changes.append(
                ItemChange(
                    change_type=CHANGE_ADDED,
                    item_type=item_type,
                    name=name,
                    after=item.fingerprint_projection(),
                )
            )

    for name, item in base_by_name.items():
        if name not in target_by_name:
            changes.append(
                ItemChange(
                    change_type=CHANGE_REMOVED,
                    item_type=item_type,
                    name=name,
                    before=item.fingerprint_projection(),
                )
            )

    for name, base_item in base_by_name.items():
        target_item = target_by_name.get(name)
        if target_item is None:
            continue
        before = base_item.fingerprint_projection()
        after = target_item.fingerprint_projection()
        field_changes = _diff_projection(item_type, before, after)
        if field_changes:
            changes.append(
                ItemChange(
                    change_type=CHANGE_MODIFIED,
                    item_type=item_type,
                    name=name,
                    before=before,
                    after=after,
                    fields=field_changes,
                )
            )
    return changes


def _diff_projection(
    item_type: str, before: Mapping[str, Any], after: Mapping[str, Any]
) -> Tuple[FieldChange, ...]:
    """Compare two same-kind fingerprint projections field by field.

    Walks ``FINGERPRINT_FIELDS[item_type]`` (its canonical field order, which also
    fixes the order of the resulting :class:`FieldChange` tuple) and emits one entry
    per field whose canonical value differs. ``name`` is included in the walk but,
    being the pairing key, never differs for a matched item.
    """
    field_changes: List[FieldChange] = []
    for field_name in FINGERPRINT_FIELDS[item_type]:
        before_value = before.get(field_name)
        after_value = after.get(field_name)
        if _canonical(before_value) != _canonical(after_value):
            field_changes.append(
                FieldChange(field=field_name, before=before_value, after=after_value)
            )
    return tuple(field_changes)


def _canonical(value: Any) -> str:
    """Return a byte-stable canonical JSON string for equality comparison.

    Object keys are sorted recursively so two values that differ only in map ordering
    compare equal — matching the surface fingerprint's notion of equality and ensuring
    a mere key reshuffle is never reported as a change.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
