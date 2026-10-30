"""Validation constraints as one line of text — MFX-30.3 (#4180).

A schema language with no validation facets (FlatBuffers, Cap'n Proto) can still keep a field's
constraints for its readers as a comment. :func:`constraint_comment` renders a
:class:`~app.canonical_model.Constraints` as that line — ``constraints: >= 1; <= 100; max length 40`` —
so the emitters write it and the fidelity report can say exactly what became a comment.

A ``format`` that only picks a numeric width (``int32``, ``double`` …) is left out: the emitter's type
already says it.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .canonical_model import Constraints

__all__ = ["constraint_comment", "constraint_phrases"]

#: Formats that pick a number's width; the written type carries them.
_WIDTH_FORMATS = frozenset({
    "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "float", "double",
})


def _number(value: Any) -> str:
    """A number without a needless ``.0`` (``1.0`` → ``1``)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def constraint_phrases(constraints: Optional[Constraints]) -> List[str]:
    """Each set constraint as a short phrase, in a fixed order.

    Args:
        constraints: The field's or type's constraints, or ``None``.

    Returns:
        Phrases such as ``>= 1``, ``max length 40``, ``pattern ^[A-Z]+$``, ``one of: a, b``; empty
        when nothing is set (or only a width ``format``).
    """
    if constraints is None:
        return []
    c = constraints
    phrases: List[str] = []
    for value, phrase in (
        (c.minimum, ">= {}"), (c.exclusive_minimum, "> {}"),
        (c.maximum, "<= {}"), (c.exclusive_maximum, "< {}"),
        (c.multiple_of, "multiple of {}"),
        (c.min_length, "min length {}"), (c.max_length, "max length {}"),
        (c.min_items, "min items {}"), (c.max_items, "max items {}"),
    ):
        if value is not None:
            phrases.append(phrase.format(_number(value)))
    if c.unique_items:
        phrases.append("unique items")
    if c.pattern:
        phrases.append(f"pattern {' '.join(c.pattern.split())}")
    if c.enum:
        phrases.append("one of: " + ", ".join(str(v) for v in c.enum))
    if c.format and c.format.lower() not in _WIDTH_FORMATS:
        phrases.append(f"format {c.format}")
    return phrases


def constraint_comment(constraints: Optional[Constraints]) -> Optional[str]:
    """The constraints as one comment line's text (``constraints: >= 1; max length 40``), or ``None``."""
    phrases = constraint_phrases(constraints)
    return "constraints: " + "; ".join(phrases) if phrases else None
