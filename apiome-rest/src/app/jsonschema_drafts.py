"""JSON Schema dialects for the JSON Schema export — MFX-21.1 (#4126).

The JSON Schema emitter writes draft **2020-12**. :func:`downgrade_schema` rewrites such a document
for an older draft (**draft-07** or **draft-04**) so it validates against that draft's metaschema,
recording on a :class:`~app.emitter.LossTracker` every keyword the older draft cannot carry:

* both: ``$defs`` → ``definitions`` (and every ``#/$defs/…`` reference); a ``$ref`` with sibling
  keywords (which those drafts ignore) is wrapped as ``allOf: [{"$ref": …}]``; ``deprecated`` is
  dropped (it is 2019-09);
* draft-04 only: ``$id`` → ``id``; ``const`` → a one-value ``enum``; a numeric ``exclusiveMinimum`` /
  ``exclusiveMaximum`` → ``minimum`` / ``maximum`` with the boolean flag (when the schema also has
  the inclusive bound, the stricter one is kept); ``contentEncoding`` and ``examples`` are dropped.

The rewrite is schema-aware: only schema positions are visited, so a property *named* ``deprecated``
or ``$id`` is never touched.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from .emitter import LossKind, LossTracker

__all__ = ["DRAFT_URIS", "JsonSchemaDraft", "dialect_of", "downgrade_schema"]

JsonSchemaDraft = Literal["2020-12", "draft-07", "draft-04"]

#: Draft → its ``$schema`` URI.
DRAFT_URIS: Dict[str, str] = {
    "2020-12": "https://json-schema.org/draft/2020-12/schema",
    "draft-07": "http://json-schema.org/draft-07/schema#",
    "draft-04": "http://json-schema.org/draft-04/schema#",
}

#: Keywords whose value is a map of name → schema.
_SCHEMA_MAPS = ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas")
#: Keywords whose value is a list of schemas.
_SCHEMA_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
#: Keywords whose value is one schema.
_SCHEMA_VALUES = ("not", "if", "then", "else", "contains", "propertyNames", "additionalProperties", "items")


def dialect_of(document: Any) -> Optional[str]:
    """The draft a document declares in ``$schema`` (``"2020-12"``, ``"draft-07"`` …), or ``None``."""
    uri = document.get("$schema") if isinstance(document, dict) else None
    if not isinstance(uri, str):
        return None
    wanted = _normalized_uri(uri)
    return next((draft for draft, known in DRAFT_URIS.items() if _normalized_uri(known) == wanted), None)


def _normalized_uri(uri: str) -> str:
    """A ``$schema`` URI without its scheme's ``s``, trailing ``#`` / ``/`` or case."""
    return uri.strip().rstrip("#").rstrip("/").lower().replace("https://", "http://")


def downgrade_schema(document: Dict[str, Any], draft: str, losses: LossTracker) -> Dict[str, Any]:
    """Rewrite a draft 2020-12 document for ``draft`` (a no-op for ``"2020-12"``).

    Args:
        document: The 2020-12 document (not mutated).
        draft: ``"2020-12"``, ``"draft-07"`` or ``"draft-04"``.
        losses: Where each keyword the draft cannot carry is recorded (pointer: the JSON Pointer of
            the schema that had it).

    Returns:
        The rewritten document, with ``$schema`` set to the draft's URI.
    """
    if draft == "2020-12":
        return document
    rewritten = _schema(document, draft, losses, "#")
    rewritten["$schema"] = DRAFT_URIS[draft]
    return rewritten


def _schema(schema: Any, draft: str, losses: LossTracker, pointer: str) -> Any:
    """Rewrite one schema position (and, recursively, the schemas inside it)."""
    if not isinstance(schema, dict):
        return schema
    out: Dict[str, Any] = {}
    for keyword, value in schema.items():
        child = f"{pointer}/{keyword}"
        if keyword in _SCHEMA_MAPS and isinstance(value, dict):
            name = "definitions" if keyword == "$defs" else keyword
            out[name] = {key: _schema(sub, draft, losses, f"{child}/{key}") for key, sub in value.items()}
        elif keyword in _SCHEMA_LISTS and isinstance(value, list):
            out[keyword] = [_schema(sub, draft, losses, f"{child}/{i}") for i, sub in enumerate(value)]
        elif keyword in _SCHEMA_VALUES:
            out[keyword] = (
                [_schema(sub, draft, losses, f"{child}/{i}") for i, sub in enumerate(value)]
                if isinstance(value, list) else _schema(value, draft, losses, child)
            )
        elif keyword == "$ref" and isinstance(value, str):
            out[keyword] = value.replace("#/$defs/", "#/definitions/", 1)
        else:
            out[keyword] = value
    _drop(out, "deprecated", draft, losses, pointer)
    if draft == "draft-04":
        _to_draft_04(out, losses, pointer)
    if "$ref" in out and len(out) > 1:
        # Older drafts ignore every keyword beside `$ref` (the root's `definitions` included): keep them
        # by moving the reference into allOf.
        out["allOf"] = [{"$ref": out.pop("$ref")}, *out.get("allOf", [])]
    return out


def _to_draft_04(schema: Dict[str, Any], losses: LossTracker, pointer: str) -> None:
    """The draft-04 spellings of ``$id``, ``const`` and the exclusive bounds; drop what it lacks."""
    if "$id" in schema:
        schema["id"] = schema.pop("$id")
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]
    for exclusive, inclusive in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        bound = schema.get(exclusive)
        if isinstance(bound, bool) or not isinstance(bound, (int, float)):
            continue
        del schema[exclusive]
        current = schema.get(inclusive)
        stricter = current is None or (bound >= current if inclusive == "minimum" else bound <= current)
        if stricter:
            schema[inclusive], schema[exclusive] = bound, True
        else:
            losses.record(
                LossKind.INFERRED, "exclusive-bound-merged",
                f"draft-04 has one {inclusive} per schema; the looser {exclusive} {bound} at {pointer} is dropped "
                f"in favour of {inclusive} {current}.",
                pointer=pointer,
            )
    for keyword in ("contentEncoding", "examples"):
        _drop(schema, keyword, "draft-04", losses, pointer)


def _drop(schema: Dict[str, Any], keyword: str, draft: str, losses: LossTracker, pointer: str) -> None:
    """Remove ``keyword`` (unknown to ``draft``) and record it."""
    if keyword not in schema:
        return
    schema.pop(keyword)
    losses.record(
        LossKind.NA, "keyword-dropped",
        f"{draft} has no `{keyword}` keyword; it is dropped at {pointer}.",
        pointer=pointer,
    )

