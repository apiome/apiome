"""Stable Cap'n Proto ordinals and file ids — MFX-30.2 (#4179).

A ``.capnp`` schema numbers every struct field, union member, enumerant and interface method with an
``@N`` ordinal, and the file itself carries a 64-bit ``@0x…`` id. Both are part of the wire contract:
renumbering a field, or changing the file id, breaks every reader built from the earlier schema. A
model converted from OpenAPI has neither, so the emitter synthesizes them and the MFX-12.2 store
(:mod:`app.field_identity_store`, target :data:`~app.field_identity_store.CAPNP_TARGET`) keeps them,
so every later export writes the same numbers.

Cap'n Proto's rules differ from Protobuf's and Thrift's, hence this module rather than
:class:`~app.field_identity_store.FieldNumberAllocator`:

* ordinals start at ``@0`` and must be **sequential with no holes** — ``capnp`` refuses a struct with
  ``@0`` and ``@2`` but no ``@1``;
* a field can never be removed, only renamed. When the source drops a field, its ordinal stays taken
  and the emitter writes an ``obsolete…`` placeholder of the **same layout** (a pointer stays a
  pointer, a 32-bit value stays 32 bits) so the other fields keep their wire positions;
* the file id must have its top bit set (``capnp id`` output).

Store rows for one export target, all in one ``field_key → number`` map:

* ``<scope key>.<member name>`` → the member's ordinal. The scope is a struct, enum or interface (its
  canonical key) and the member name is the emitted Cap'n Proto identifier, which never contains a
  dot — so a nested struct's rows (``Person.PhoneNumber.number``) are never read as its parent's;
* ``@layout:<scope key>.<member name>`` → the field's :class:`Layout`, used for its placeholder
  once the field is gone;
* :data:`FILE_ID_KEY` → the file id with its top bit cleared (:func:`file_id_to_store`), so it fits
  a signed ``BIGINT``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, List, Optional, Set

__all__ = [
    "FILE_ID_KEY",
    "Layout",
    "MAX_ORDINAL",
    "OrdinalAllocator",
    "Slot",
    "file_id_from_store",
    "file_id_to_store",
    "format_file_id",
    "layout_key",
    "parse_file_id",
    "placeholder_type",
    "synthesize_file_id",
]

#: The store key holding the file id (never a canonical key: those do not start with ``@``).
FILE_ID_KEY = "@file-id"
_LAYOUT_PREFIX = "@layout:"
_TOP_BIT = 1 << 63
_MAX_ID = (1 << 64) - 1
#: Cap'n Proto ordinals are 16-bit; a larger number (a corrupt store row) is ignored rather than
#: filled up to with placeholders.
MAX_ORDINAL = 65_535


class Layout(IntEnum):
    """How much room a struct field takes on the wire — all a placeholder has to preserve.

    Cap'n Proto lays fields out by size class, so a removed field's placeholder of the same class
    leaves every other field where it was.
    """

    VOID = 0
    BOOL = 1
    BITS8 = 2
    BITS16 = 3  # also every enum
    BITS32 = 4
    BITS64 = 5
    POINTER = 6  # Text, Data, List, struct, interface, AnyPointer


_PLACEHOLDER_TYPES: Dict[Layout, str] = {
    Layout.VOID: "Void",
    Layout.BOOL: "Bool",
    Layout.BITS8: "UInt8",
    Layout.BITS16: "UInt16",
    Layout.BITS32: "UInt32",
    Layout.BITS64: "UInt64",
    Layout.POINTER: "AnyPointer",
}


def placeholder_type(layout: Optional[Layout]) -> str:
    """The type a placeholder field of ``layout`` is written with (``Void`` when unknown)."""
    return _PLACEHOLDER_TYPES.get(layout if layout is not None else Layout.VOID, "Void")


def layout_key(ordinal_key: str) -> str:
    """The store key that records the layout of the field stored under ``ordinal_key``."""
    return f"{_LAYOUT_PREFIX}{ordinal_key}"


# ---------------------------------------------------------------------------
# File id
# ---------------------------------------------------------------------------


def synthesize_file_id(seed: str) -> int:
    """Derive a file id from ``seed`` — a valid ``capnp`` id, the same for the same seed.

    Derived rather than random, so an export that is not persisted (a preview, a CLI run without a
    project) still writes the same id every time. The persisted value takes over afterwards, so a
    later rename of the API does not change it.

    Args:
        seed: Text identifying the API, e.g. its namespace and name.

    Returns:
        A 64-bit id with its top bit set.
    """
    digest = hashlib.sha256(f"apiome-capnp-file:{seed}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") | _TOP_BIT


def parse_file_id(value: Any) -> Optional[int]:
    """Read a file id written in a schema (``0xbf5147cbbecf40c1``, with or without ``0x``/``@``).

    Returns:
        The id, or ``None`` when ``value`` is not a valid ``capnp`` file id (top bit set).
    """
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip().lstrip("@")
        text = text[2:] if text.lower().startswith("0x") else text
        if not re.fullmatch(r"[0-9a-fA-F]{1,16}", text):
            return None
        number = int(text, 16)
    else:
        return None
    if not (_TOP_BIT <= number <= _MAX_ID):
        return None
    return number


def format_file_id(file_id: int) -> str:
    """Render ``file_id`` the way ``capnp`` writes it: ``0x`` plus 16 hex digits."""
    return f"0x{file_id:016x}"


def file_id_to_store(file_id: int) -> int:
    """The value stored for ``file_id``: its top bit cleared, so it fits a signed ``BIGINT``.

    Raises:
        ValueError: If ``file_id`` is not a valid file id.
    """
    if parse_file_id(file_id) is None:
        raise ValueError(f"{file_id!r} is not a Cap'n Proto file id (its top bit must be set)")
    return file_id & ~_TOP_BIT


def file_id_from_store(stored: Any) -> Optional[int]:
    """Restore a file id from its stored value (:func:`file_id_to_store`); ``None`` if unusable."""
    if not isinstance(stored, int) or not (0 <= stored < _TOP_BIT):
        return None
    return stored | _TOP_BIT


# ---------------------------------------------------------------------------
# Ordinals
# ---------------------------------------------------------------------------


def _valid_ordinal(value: Any) -> bool:
    """Whether ``value`` is a usable ``@N`` ordinal (``0`` to :data:`MAX_ORDINAL`)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_ORDINAL


@dataclass
class Slot:
    """One ``@N`` position in a scope, as the emitter writes it.

    Attributes:
        ordinal: The ``@N`` number.
        name: The member's emitted identifier (for a placeholder, the removed member's name).
        member: What the caller passed to :meth:`OrdinalAllocator.add`; ``None`` for a placeholder.
        synthesized: Whether the ordinal was assigned here (or by an earlier export) rather than
            taken from the source.
        placeholder: ``True`` for a slot no current member holds — it keeps a removed member's
            ordinal (``retired``) or fills a gap in the source's own numbering.
        layout: For a placeholder field, the removed field's recorded layout (``None`` if unknown).
        retired: ``True`` when the placeholder keeps the ordinal of a member an earlier export wrote.
    """

    ordinal: int
    name: str
    member: Any = None
    synthesized: bool = False
    placeholder: bool = False
    layout: Optional[Layout] = None
    retired: bool = False


@dataclass
class _Pending:
    name: str
    member: Any
    source_ordinal: Optional[int]
    layout: Optional[Layout]


class OrdinalAllocator:
    """Assign contiguous, stable ``@N`` ordinals to the members of one Cap'n Proto scope.

    Usage: :meth:`add` every member in declaration order, then :meth:`finish` once. The rules, in
    order:

    1. A source ordinal (a model imported from ``.capnp``) always wins.
    2. A member without one reuses the ordinal stored for it by an earlier export, unless a source
       ordinal or another member already holds that number.
    3. Every other member gets the lowest number nobody holds — not a source ordinal, not a stored
       member's, and not one stored for a member the scope has since lost (that one is retired).
    4. Every number from ``@0`` to the highest one in use that no member holds becomes a placeholder
       slot, so the scope has no holes.

    Newly assigned ordinals — and the layouts of fields, when they are new or have changed — are in
    :attr:`new_assignments` afterwards, for the caller to persist.
    """

    def __init__(self, scope_key: str, persisted: Optional[Dict[str, int]] = None) -> None:
        """Start a scope.

        Args:
            scope_key: The canonical key of the struct, enum or interface.
            persisted: The store map for this export (all scopes; only this scope's rows are read).
        """
        self._scope_key = scope_key
        self._persisted = persisted or {}
        self._pending: List[_Pending] = []
        #: ``field_key → number`` rows this scope assigned for the first time (or changed).
        self.new_assignments: Dict[str, int] = {}

    def ordinal_key(self, name: str) -> str:
        """The store key of the member named ``name`` (its emitted identifier) in this scope."""
        return f"{self._scope_key}.{name}"

    def add(
        self,
        name: str,
        member: Any,
        *,
        source_ordinal: Optional[int] = None,
        layout: Optional[Layout] = None,
    ) -> None:
        """Queue one member.

        Args:
            name: The member's emitted identifier, unique in the scope (no dots).
            member: Anything the caller wants back on the :class:`Slot` (the canonical field, …).
            source_ordinal: The ordinal the source gave it, if any (``capnp`` imports only).
            layout: For a struct field, its size class; recorded so a later placeholder keeps it.
        """
        ordinal = source_ordinal if _valid_ordinal(source_ordinal) else None
        self._pending.append(_Pending(name, member, ordinal, layout))

    def _stored_ordinal(self, name: str) -> Optional[int]:
        value = self._persisted.get(self.ordinal_key(name))
        return value if _valid_ordinal(value) else None

    def _retired(self, present: Set[str]) -> Dict[int, str]:
        """Ordinals stored for members of this scope that the source no longer has → their names."""
        prefix = f"{self._scope_key}."
        retired: Dict[int, str] = {}
        for key, value in sorted(self._persisted.items()):
            if not key.startswith(prefix) or not _valid_ordinal(value):
                continue
            name = key[len(prefix) :]
            if not name or "." in name or name in present:
                continue
            retired.setdefault(value, name)
        return retired

    def finish(self) -> List[Slot]:
        """Assign every queued member and return the scope's slots, ``@0`` upward with no holes."""
        present = {pending.name for pending in self._pending}
        retired = self._retired(present)
        taken: Dict[int, Slot] = {}

        # 1. Source ordinals. A second member claiming the same source number is numbered as if it
        #    had none (a malformed source; capnp itself would refuse it).
        unnumbered: List[_Pending] = []
        for pending in self._pending:
            if pending.source_ordinal is not None and pending.source_ordinal not in taken:
                taken[pending.source_ordinal] = Slot(
                    pending.source_ordinal, pending.name, pending.member
                )
            else:
                unnumbered.append(pending)

        # 2. Ordinals stored by an earlier export, while still free.
        fresh: List[_Pending] = []
        for pending in unnumbered:
            stored = self._stored_ordinal(pending.name)
            if stored is not None and stored not in taken:
                taken[stored] = Slot(stored, pending.name, pending.member, synthesized=True)
                self._record_layout(pending)
            else:
                fresh.append(pending)

        # 3. The lowest number nobody holds, skipping retired ones.
        next_ordinal = 0
        for pending in fresh:
            while next_ordinal in taken or next_ordinal in retired:
                next_ordinal += 1
            taken[next_ordinal] = Slot(next_ordinal, pending.name, pending.member, synthesized=True)
            self.new_assignments[self.ordinal_key(pending.name)] = next_ordinal
            self._record_layout(pending)
            next_ordinal += 1

        # 4. Fill every hole up to the highest number in use.
        highest = max([*taken, *retired], default=-1)
        slots: List[Slot] = []
        for ordinal in range(highest + 1):
            if ordinal in taken:
                slots.append(taken[ordinal])
            elif ordinal in retired:
                name = retired[ordinal]
                stored_layout = self._persisted.get(layout_key(self.ordinal_key(name)))
                layout = (
                    Layout(stored_layout)
                    if isinstance(stored_layout, int) and stored_layout in Layout._value2member_map_
                    else None
                )
                slots.append(Slot(ordinal, name, placeholder=True, layout=layout, retired=True))
            else:
                slots.append(Slot(ordinal, f"reserved{ordinal}", placeholder=True))
        return slots

    def _record_layout(self, pending: _Pending) -> None:
        """Queue the member's layout row when it is new or differs from the stored one."""
        if pending.layout is None:
            return
        key = layout_key(self.ordinal_key(pending.name))
        if self._persisted.get(key) != int(pending.layout):
            self.new_assignments[key] = int(pending.layout)
