"""Stable FlatBuffers field ids — MFX-30.1 (#4178).

Every field of a FlatBuffers ``table`` has an id: its slot in the table's vtable, and so part of the
wire contract. Renumbering a field, or reusing a removed field's id, breaks every reader built from the
earlier schema. A model converted from OpenAPI has no ids, so the emitter assigns them and the MFX-12.2
store (:mod:`app.field_identity_store`, target :data:`~app.field_identity_store.FLATBUFFERS_TARGET`)
keeps them, so every later export writes the same ids.

FlatBuffers' rules differ from Protobuf's and Thrift's, hence this module rather than
:class:`~app.field_identity_store.FieldNumberAllocator`:

* ids start at ``0`` and every table uses **all ids from 0 to its highest** — ``flatc`` refuses a
  table with ids 0 and 2 but no 1;
* a **union** field takes two consecutive ids: ``N - 1`` for its hidden ``<name>_type`` field and ``N``
  (the one written in ``(id: N)``) for its value;
* a field is never removed, only deprecated: when the source drops a field, its id stays taken and the
  emitter writes a ``(deprecated)`` placeholder in its slot.

Store rows for one export target, in one ``field_key → id`` map: ``<field key>`` → the field's id
(for a union, its value id), and ``<field key>_type`` → a union's type id. Field keys are
``<table key>.<field name>``, so a table's own rows share its key as a prefix, and the ``_type`` row
of a removed union is retired with it.

Its Cap'n Proto sibling is :mod:`app.capnproto_identity` (single-width ordinals, layouts and a file id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

__all__ = ["MAX_FIELD_ID", "FieldIdAllocator", "IdSlot", "compact_field_ids"]

#: The highest usable id: a vtable holds 16-bit offsets, so ``flatc`` caps a table's fields well below
#: this. A larger stored number (a corrupt row) is ignored rather than filled up to with placeholders.
MAX_FIELD_ID = 65_534


def _valid_id(value: Any) -> bool:
    """Whether ``value`` is a usable field id (``0`` to :data:`MAX_FIELD_ID`)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_FIELD_ID


def compact_field_ids(widths: List[int]) -> List[int]:
    """The ids ``flatc`` gives fields declared in this order without ``(id: N)``: each its (value) id.

    Args:
        widths: Each field's width in declaration order (``2`` for a union, else ``1``).

    Returns:
        ``[0, 2, 3]`` for widths ``[1, 2, 1]`` — the union's type id (1) is implied.
    """
    ids: List[int] = []
    next_id = 0
    for width in widths:
        ids.append(next_id + width - 1)
        next_id += width
    return ids


@dataclass
class IdSlot:
    """One id position of a table, as the emitter writes it.

    Attributes:
        id: The field id (for a union, its value id; its type id is ``id - 1``).
        key: The store key: the field's canonical key, or for a placeholder the retired key.
        member: What the caller passed to :meth:`FieldIdAllocator.add`; ``None`` for a placeholder.
        width: ``2`` for a union (type and value ids), else ``1``.
        synthesized: Whether the id was assigned here (or by an earlier export), not by the source.
        placeholder: ``True`` for an id no current field holds — a removed field's (``retired``) or a
            gap in the source's own numbering.
        retired: ``True`` when the placeholder keeps the id of a field an earlier export wrote.
    """

    id: int
    key: str
    member: Any = None
    width: int = 1
    synthesized: bool = False
    placeholder: bool = False
    retired: bool = False


@dataclass
class _Pending:
    key: str
    member: Any
    width: int
    source_id: Optional[int]


class FieldIdAllocator:
    """Assign contiguous, stable ids to the fields of one FlatBuffers table.

    Usage: :meth:`add` every field in order, then :meth:`finish` once. The rules, in order:

    1. A source id (a model imported from ``.fbs``) always wins.
    2. A field without one reuses the id stored for it by an earlier export, while its whole span
       (both ids of a union) is still free.
    3. Every other field gets the lowest free span — not a source id, not a stored field's, and not
       one stored for a field the table has since lost (that one is retired).
    4. Every id from ``0`` to the highest one in use that no field holds becomes a placeholder slot,
       so the table has no holes.

    Newly assigned ids are in :attr:`new_assignments` afterwards, for the caller to persist.
    """

    def __init__(self, table_key: str, persisted: Optional[Dict[str, int]] = None) -> None:
        """Start a table.

        Args:
            table_key: The table's canonical key (its fields' keys start with ``<table_key>.``).
            persisted: The store map for this export (all tables; only this table's rows are read).
        """
        self._table_key = table_key
        self._persisted = persisted or {}
        self._pending: List[_Pending] = []
        #: ``store key → id`` rows this table assigned for the first time.
        self.new_assignments: Dict[str, int] = {}

    @staticmethod
    def type_key(field_key: str) -> str:
        """The store key of a union field's type id."""
        return f"{field_key}_type"

    def add(self, key: str, member: Any, *, width: int = 1, source_id: Optional[int] = None) -> None:
        """Queue one field.

        Args:
            key: The field's canonical key (``<table key>.<field name>``).
            member: Anything the caller wants back on the :class:`IdSlot` (the canonical field, …).
            width: ``2`` for a union field, else ``1``.
            source_id: The id the source gave it (its value id for a union), if any.
        """
        valid = _valid_id(source_id) and (width == 1 or source_id >= 1)
        self._pending.append(_Pending(key, member, width, source_id if valid else None))

    def _span(self, last_id: int, width: int) -> range:
        """The ids a field whose (value) id is ``last_id`` occupies."""
        return range(last_id - width + 1, last_id + 1)

    def _stored(self, pending: _Pending) -> Optional[int]:
        """The id stored for ``pending``, when its stored span matches its width."""
        value = self._persisted.get(pending.key)
        if not _valid_id(value):
            return None
        if pending.width == 2:
            return value if self._persisted.get(self.type_key(pending.key)) == value - 1 else None
        return value

    def _retired(self, present: set) -> Dict[int, str]:
        """Ids stored for fields of this table the source no longer has → their store keys."""
        prefix = f"{self._table_key}."
        retired: Dict[int, str] = {}
        for key, value in sorted(self._persisted.items()):
            name = key[len(prefix):] if key.startswith(prefix) else ""
            if not name or "." in name or not _valid_id(value) or key in present:
                continue
            retired.setdefault(value, key)
        return retired

    def finish(self) -> List[IdSlot]:
        """Assign every queued field and return the table's slots, id 0 upward with no holes.

        A union's slot is listed once, at its value id; its type id (``id - 1``) is not a separate slot.
        """
        present = {p.key for p in self._pending} | {self.type_key(p.key) for p in self._pending if p.width == 2}
        retired = self._retired(present)
        taken: Dict[int, IdSlot] = {}
        occupied: set = set()

        def claim(pending: _Pending, last_id: int, *, synthesized: bool) -> None:
            span = self._span(last_id, pending.width)
            occupied.update(span)
            taken[last_id] = IdSlot(last_id, pending.key, pending.member, pending.width, synthesized)

        # 1. Source ids. A field whose span collides with an earlier one is numbered as if it had none.
        unnumbered: List[_Pending] = []
        for pending in self._pending:
            span = self._span(pending.source_id, pending.width) if pending.source_id is not None else None
            if span is not None and not occupied.intersection(span):
                claim(pending, pending.source_id, synthesized=False)
            else:
                unnumbered.append(pending)

        # 2. Ids stored by an earlier export, while the whole span is free.
        fresh: List[_Pending] = []
        for pending in unnumbered:
            stored = self._stored(pending)
            if stored is not None and not occupied.intersection(self._span(stored, pending.width)):
                claim(pending, stored, synthesized=True)
            else:
                fresh.append(pending)

        # 3. The lowest free span, skipping retired ids.
        for pending in fresh:
            last_id = pending.width - 1
            while any(i in occupied or i in retired for i in self._span(last_id, pending.width)):
                last_id += 1
            claim(pending, last_id, synthesized=True)
            self.new_assignments[pending.key] = last_id
            if pending.width == 2:
                self.new_assignments[self.type_key(pending.key)] = last_id - 1

        # 4. Fill every hole up to the highest id in use.
        highest = max([*occupied, *retired], default=-1)
        slots: List[IdSlot] = []
        for slot_id in range(highest + 1):
            if slot_id in taken:
                slots.append(taken[slot_id])
            elif slot_id in occupied:
                continue  # a union's type id, written by its value slot
            elif slot_id in retired:
                slots.append(IdSlot(slot_id, retired[slot_id], placeholder=True, retired=True))
            else:
                slots.append(IdSlot(slot_id, f"{self._table_key}.reserved_{slot_id}", placeholder=True))
        return slots
