"""Persisted field-identity store for export targets — MFX-12.2 (#3880).

Protobuf (and later FlatBuffers, Iceberg, FIX Orchestra) require stable positional field numbers.
Sources converted from OpenAPI, GraphQL, and other formats often lack them. The proto emitter
synthesizes numbers on first export; this module **persists** those assignments per
``(tenant, artifact/project, target, field_key)`` so re-exports reuse them and new fields receive
the next free number that honours message ``reserved`` ranges.

The emitter stays pure: callers pre-load a ``field_key → number`` map via
:func:`load_persisted_field_numbers` and pass it through :class:`~app.proto_emitter.ProtoEmitOptions`;
after emit, :func:`persist_field_number_assignments` writes any newly synthesized numbers.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from .canonical_model import CanonicalField, Type
from .database import db

__all__ = [
    "PROTO3_TARGET",
    "field_number_in_reserved",
    "FieldNumberAllocator",
    "load_persisted_field_numbers",
    "persist_field_number_assignments",
]

PROTO3_TARGET = "proto3"
_PROTO_MAX_FIELD_NUMBER = 536_870_911


def field_number_in_reserved(number: int, ranges: Any, *, enum: bool = False) -> bool:
    """Return whether ``number`` falls inside a message or enum ``reserved`` range.

    Message ranges are half-open ``[start, end)``; enum ranges are inclusive ``[start, end]`` —
    matching :mod:`app.proto_emitter` / :mod:`app.proto_lint`.
    """
    if not isinstance(ranges, list):
        return False
    inclusive_end = enum
    for pair in ranges:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            continue
        start, end = pair
        if not (isinstance(start, int) and isinstance(end, int)):
            continue
        if start <= number and (number <= end if inclusive_end else number < end):
            return True
    return False


class FieldNumberAllocator:
    """Assign protobuf field numbers honouring source, persisted, and reserved constraints."""

    def __init__(
        self,
        type_: Type,
        *,
        persisted: Optional[Dict[str, int]] = None,
    ) -> None:
        reserved_ranges = type_.extras.get("reserved_ranges") or []
        self._reserved_ranges = reserved_ranges
        self._persisted = dict(persisted or {})
        self._used: set[int] = {
            f.field_number
            for f in type_.fields
            if isinstance(f.field_number, int)
        }
        for field in type_.fields:
            if field.field_number is None:
                stored = self._persisted.get(field.key)
                if isinstance(stored, int):
                    self._used.add(stored)
        self._next = 1
        self.assignments: Dict[str, int] = {}
        self.new_assignments: Dict[str, int] = {}

    def allocate(self, field: CanonicalField) -> Tuple[int, bool]:
        """Return ``(field_number, synthesized)`` for ``field``."""
        if isinstance(field.field_number, int):
            self.assignments[field.key] = field.field_number
            return field.field_number, False

        stored = self._persisted.get(field.key)
        if isinstance(stored, int):
            self.assignments[field.key] = stored
            return stored, True

        number = self._next_free()
        self._used.add(number)
        self.assignments[field.key] = number
        self.new_assignments[field.key] = number
        self._persisted[field.key] = number
        return number, True

    def _next_free(self) -> int:
        while self._next in self._used or field_number_in_reserved(
            self._next, self._reserved_ranges
        ):
            self._next += 1
        if self._next > _PROTO_MAX_FIELD_NUMBER:
            raise ValueError(
                f"No free protobuf field number remains for message {self._reserved_ranges!r}."
            )
        number = self._next
        self._next += 1
        return number


def load_persisted_field_numbers(
    tenant_id: str,
    project_id: str,
    target: str,
) -> Dict[str, int]:
    """Load the persisted field-number map for one artifact export target."""
    rows = db.list_export_field_identities(tenant_id, project_id, target)
    return {str(row["field_key"]): int(row["field_number"]) for row in rows}


def persist_field_number_assignments(
    tenant_id: str,
    project_id: str,
    target: str,
    assignments: Dict[str, int],
) -> None:
    """Upsert newly synthesized field numbers after an export emit."""
    if not assignments:
        return
    for field_key, field_number in sorted(assignments.items()):
        db.upsert_export_field_identity(
            tenant_id,
            project_id,
            target,
            field_key,
            field_number,
        )


def merge_persisted_into_options(
    opts: Any,
    persisted: Dict[str, int],
) -> Any:
    """Return ``opts`` with ``persisted_field_numbers`` merged in (proto emit options)."""
    if not persisted:
        return opts
    data = opts.model_dump()
    existing = data.get("persisted_field_numbers") or {}
    merged = {**existing, **persisted}
    return opts.__class__.model_validate({**data, "persisted_field_numbers": merged})
