"""Avro 1.12 logical types — MFI-12.2 (#3783).

One table of every logical type the Avro 1.12 specification defines, the underlying
type(s) each one may annotate, and the canonical ``format`` it projects onto; plus
:func:`resolve_logical_type`, which reads one schema fragment against that table.

The specification is explicit that a reader **must ignore** a logical type it does not
know, or one that annotates the wrong underlying type (``{"type": "string",
"logicalType": "date"}``) or carries invalid attributes (a ``decimal`` whose ``scale``
exceeds its ``precision``), and use the underlying type instead. So a resolved logical
type is always *recorded* — the emitters write it back verbatim — but only a valid one
contributes a canonical ``format``.

Sources: https://avro.apache.org/docs/1.12.0/specification/#logical-types
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional

__all__ = [
    "AVRO_LOGICAL_TYPES",
    "AvroLogicalType",
    "ResolvedLogicalType",
    "resolve_logical_type",
    "max_fixed_decimal_precision",
]


@dataclass(frozen=True)
class AvroLogicalType:
    """One logical type the Avro 1.12 specification defines.

    Attributes:
        name: The ``logicalType`` value, for example ``timestamp-micros``.
        bases: The underlying Avro types it may annotate.
        format: The canonical (JSON-Schema-style) ``format`` it projects onto.
        fixed_size: The exact ``fixed`` size it requires, when it requires one
            (``uuid`` on ``fixed`` is 16 bytes; ``duration`` is always 12).
    """

    name: str
    bases: FrozenSet[str]
    format: str
    fixed_size: Optional[int] = None


def _table(*entries: AvroLogicalType) -> Dict[str, AvroLogicalType]:
    return {entry.name: entry for entry in entries}


#: Every logical type of Avro 1.12. ``local-timestamp-*`` has no zone-free JSON-Schema
#: format, so it shares ``date-time`` with ``timestamp-*`` (the ``logicalType`` itself is
#: kept in ``extras``, which is what distinguishes the two).
AVRO_LOGICAL_TYPES: Dict[str, AvroLogicalType] = _table(
    AvroLogicalType("decimal", frozenset({"bytes", "fixed"}), "decimal"),
    AvroLogicalType("big-decimal", frozenset({"bytes"}), "decimal"),
    AvroLogicalType("uuid", frozenset({"string", "fixed"}), "uuid", fixed_size=16),
    AvroLogicalType("date", frozenset({"int"}), "date"),
    AvroLogicalType("time-millis", frozenset({"int"}), "time"),
    AvroLogicalType("time-micros", frozenset({"long"}), "time"),
    AvroLogicalType("timestamp-millis", frozenset({"long"}), "date-time"),
    AvroLogicalType("timestamp-micros", frozenset({"long"}), "date-time"),
    AvroLogicalType("timestamp-nanos", frozenset({"long"}), "date-time"),
    AvroLogicalType("local-timestamp-millis", frozenset({"long"}), "date-time"),
    AvroLogicalType("local-timestamp-micros", frozenset({"long"}), "date-time"),
    AvroLogicalType("local-timestamp-nanos", frozenset({"long"}), "date-time"),
    AvroLogicalType("duration", frozenset({"fixed"}), "duration", fixed_size=12),
)


@dataclass(frozen=True)
class ResolvedLogicalType:
    """A ``logicalType`` read from one schema fragment.

    Attributes:
        name: The ``logicalType`` value as written.
        base: The underlying Avro type it annotates (``long``, ``fixed`` …), or
            ``None`` when the fragment's ``type`` is not a plain name.
        format: The canonical ``format`` it projects onto; ``None`` when ignored.
        precision: A ``decimal``'s declared precision, when it declares one.
        scale: A ``decimal``'s declared scale, when it declares one.
        ignored: Why the specification says to ignore it — ``unknown`` (not an Avro
            1.12 logical type) or ``invalid`` (wrong underlying type, wrong ``fixed``
            size, bad ``precision``/``scale``) — or ``None`` when it is honoured.
    """

    name: str
    base: Optional[str]
    format: Optional[str]
    precision: Optional[int] = None
    scale: Optional[int] = None
    ignored: Optional[str] = None

    def extras(self) -> Dict[str, Any]:
        """Return the canonical ``extras`` that record this logical type.

        ``logicalType``/``avro_type``/``precision``/``scale`` are the keys the Avro
        emitters already read back; ``avro_logical_type_ignored`` is added only when
        the logical type is not honoured, so a valid one records exactly what it did
        before MFI-12.2.

        Returns:
            The extras additions; never empty.
        """
        extras: Dict[str, Any] = {"logicalType": self.name}
        if self.base is not None:
            extras["avro_type"] = self.base
        if self.precision is not None:
            extras["precision"] = self.precision
        if self.scale is not None:
            extras["scale"] = self.scale
        if self.ignored is not None:
            extras["avro_logical_type_ignored"] = self.ignored
        return extras


def max_fixed_decimal_precision(size: int) -> int:
    """Return the largest ``decimal`` precision a ``fixed`` of ``size`` bytes can hold.

    The specification bounds it at ``floor(log10(2^(8*size - 1) - 1))`` — the number
    of whole base-10 digits a signed two's-complement value of that width can store.

    Args:
        size: The ``fixed`` size in bytes; must be positive.

    Returns:
        The maximum precision (``0`` for a size too small to hold any digit).
    """
    if size <= 0:
        return 0
    return int(math.floor(math.log10(2 ** (8 * size - 1) - 1)))


def _decimal_problem(schema: Mapping[str, Any], base: Optional[str]) -> Optional[str]:
    """Return why a ``decimal``'s attributes are invalid, or ``None`` when they are valid."""
    precision = schema.get("precision")
    scale = schema.get("scale", 0)
    if isinstance(precision, bool) or not isinstance(precision, int) or precision <= 0:
        return "invalid"
    if isinstance(scale, bool) or not isinstance(scale, int) or scale < 0 or scale > precision:
        return "invalid"
    if base == "fixed":
        size = schema.get("size")
        if not isinstance(size, int) or precision > max_fixed_decimal_precision(size):
            return "invalid"
    return None


def resolve_logical_type(schema: Any) -> Optional[ResolvedLogicalType]:
    """Read the ``logicalType`` of one Avro schema fragment against the 1.12 table.

    Args:
        schema: An Avro schema fragment — typically a field's ``type`` dict or a named
            ``fixed`` declaration. Anything that is not a dict with a string
            ``logicalType`` has no logical type.

    Returns:
        The resolved logical type, with ``format`` set only when the specification
        says to honour it; ``None`` when the fragment carries no ``logicalType``.
    """
    if not isinstance(schema, Mapping):
        return None
    name = schema.get("logicalType")
    if not isinstance(name, str) or not name:
        return None
    raw_base = schema.get("type")
    base = raw_base if isinstance(raw_base, str) and raw_base else None
    precision = schema.get("precision") if _is_int(schema.get("precision")) else None
    scale = schema.get("scale") if _is_int(schema.get("scale")) else None
    if name != "decimal":
        # Only ``decimal`` defines ``precision``/``scale``; elsewhere they are custom
        # properties and stay out of the logical-type record.
        precision = scale = None

    spec = AVRO_LOGICAL_TYPES.get(name)
    if spec is None:
        return ResolvedLogicalType(name, base, None, precision, scale, ignored="unknown")

    problem: Optional[str] = None
    if base not in spec.bases:
        problem = "invalid"
    elif base == "fixed" and spec.fixed_size is not None and schema.get("size") != spec.fixed_size:
        problem = "invalid"
    elif name == "decimal":
        problem = _decimal_problem(schema, base)

    return ResolvedLogicalType(
        name,
        base,
        None if problem else spec.format,
        precision,
        scale,
        ignored=problem,
    )


def _is_int(value: Any) -> bool:
    """Whether ``value`` is a genuine integer (``bool`` is an ``int`` subclass in Python)."""
    return isinstance(value, int) and not isinstance(value, bool)
