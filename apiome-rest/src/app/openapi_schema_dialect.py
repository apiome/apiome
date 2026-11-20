"""The JSON Schema dialect an OpenAPI document's schemas are written in — COA-2.3 (#7046).

OpenAPI's Schema Object is not one language across versions:

* **OpenAPI 3.0** schemas are a draft-04-like *subset* with OpenAPI's own extensions:
  ``nullable`` instead of a ``"null"`` type, boolean ``exclusiveMinimum`` /
  ``exclusiveMaximum`` paired with ``minimum`` / ``maximum``, a single ``type``. There is no
  ``jsonSchemaDialect`` and no ``$schema``; the dialect is fixed by the version.
* **OpenAPI 3.1 / 3.2** schemas are JSON Schema 2020-12 under an OpenAPI *dialect* (the
  ``…/dialect/base`` vocabulary set). A document may declare another default with the root
  ``jsonSchemaDialect`` field, and any Schema Object may declare its own with ``$schema``.

This module answers "which dialect is this schema in?" so import keeps the declared dialect
(:func:`document_dialect`, stored by :func:`app.openapi_source_preservation.capture_source`)
and the JSON Schema projection can report it (:func:`app.canonical_json_schema.build_type_json_schema`).
The schema *rewrites* between the 3.0 subset and 2020-12 live with the code that performs them:
:func:`app.openapi_source_preservation.upgrade_schema_30_to_31` (3.0 → 3.1+) and
:mod:`app.openapi_downgrade` (3.1+ → 3.0); both record every change they make.

**Every change is recorded** (:func:`record_schema_rewrites`): a conversion between the 3.0
subset and 2020-12 that is faithful (``nullable: true`` ⇄ a ``"null"`` type, a boolean exclusive
bound ⇄ a numeric one) is noted as an inferred :class:`~app.emitter.Provenance` record at the
rewritten object, so the emitted document says where it differs from the source; a rewrite
that is not faithful is recorded as a :class:`~app.emitter.Loss` by the code that makes it.

Everything here is pure (no I/O); only :func:`record_schema_rewrites` appends to the tracker
it is given.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from .emitter import Loss, LossKind, LossTracker, Provenance, ProvenanceTracker

__all__ = [
    "changed_objects",
    "record_schema_rewrites",
    "OPENAPI_30_SCHEMA_DIALECT",
    "OPENAPI_31_DEFAULT_DIALECT",
    "OPENAPI_32_DEFAULT_DIALECT",
    "declared_type_dialect",
    "default_dialect",
    "document_dialect",
    "is_default_dialect",
    "record_declared_dialect_loss",
    "schema_dialect",
]

#: OpenAPI 3.0 has no dialect URI of its own. Its Schema Object is defined by the 3.0
#: meta-schema, so that definition's location names the dialect.
OPENAPI_30_SCHEMA_DIALECT = "https://spec.openapis.org/oas/3.0/schema/2021-09-28#/definitions/Schema"
#: The ``jsonSchemaDialect`` default of OpenAPI 3.1 (its published meta-schema's default).
OPENAPI_31_DEFAULT_DIALECT = "https://spec.openapis.org/oas/3.1/dialect/base"
#: The ``jsonSchemaDialect`` default of OpenAPI 3.2 (its published meta-schema's default).
OPENAPI_32_DEFAULT_DIALECT = "https://spec.openapis.org/oas/3.2/dialect/2025-09-17"

_DEFAULTS = {
    "3.0": OPENAPI_30_SCHEMA_DIALECT,
    "3.1": OPENAPI_31_DEFAULT_DIALECT,
    "3.2": OPENAPI_32_DEFAULT_DIALECT,
}


def _family(version: Any) -> Optional[str]:
    """``3.0`` / ``3.1`` / ``3.2`` for an ``openapi`` version string, else ``None``."""
    text = str(version or "")
    for family in ("3.0", "3.1", "3.2"):
        if text == family or text.startswith(family + "."):
            return family
    return None


def default_dialect(version: Any) -> Optional[str]:
    """The dialect a schema of an OpenAPI ``version`` is in when nothing is declared.

    Args:
        version: An ``openapi`` version string (``3.0.3``, ``3.1.2``, ``3.2.0``).

    Returns:
        The dialect URI, or ``None`` for a version that is not OpenAPI 3.0 / 3.1 / 3.2.
    """
    family = _family(version)
    return _DEFAULTS.get(family) if family else None


def is_default_dialect(dialect: Optional[str]) -> bool:
    """Whether ``dialect`` is one of the OpenAPI defaults (no explicit choice by the author).

    Args:
        dialect: A dialect URI, or ``None``.

    Returns:
        ``True`` for ``None`` and for the 3.0 / 3.1 / 3.2 defaults.
    """
    return dialect is None or dialect in _DEFAULTS.values()


def document_dialect(document: Any) -> Dict[str, Any]:
    """The default dialect of an OpenAPI document's schemas, and whether it was declared.

    A 3.1 / 3.2 document's ``jsonSchemaDialect`` wins over the version default. A 3.0
    document always uses :data:`OPENAPI_30_SCHEMA_DIALECT`; a ``jsonSchemaDialect`` key in a 3.0
    document is not part of 3.0 and is ignored here.

    Args:
        document: A parsed OpenAPI document.

    Returns:
        ``{"dialect": <uri or None>, "declared": <bool>}``. ``dialect`` is ``None`` only when the
        document is not OpenAPI 3.x.
    """
    if not isinstance(document, dict):
        return {"dialect": None, "declared": False}
    version = document.get("openapi")
    family = _family(version)
    declared = document.get("jsonSchemaDialect")
    if family in ("3.1", "3.2") and isinstance(declared, str) and declared:
        return {"dialect": declared, "declared": True}
    return {"dialect": default_dialect(version), "declared": False}


def schema_dialect(schema: Any, document_default: Optional[str], version: Any) -> Optional[str]:
    """The dialect one Schema Object is in.

    A 3.1 / 3.2 Schema Object's own ``$schema`` overrides the document default; OpenAPI 3.0
    has no ``$schema``, so a 3.0 schema is always in the document's dialect.

    Args:
        schema: The Schema Object (a ``dict``; anything else uses the document default).
        document_default: The document's dialect (see :func:`document_dialect`).
        version: The document's ``openapi`` version string.

    Returns:
        The dialect URI, or ``None`` when neither the schema nor the document names one.
    """
    if _family(version) in ("3.1", "3.2") and isinstance(schema, dict):
        own = schema.get("$schema")
        if isinstance(own, str) and own:
            return own
    return document_default


def _unescape(pointer: str) -> str:
    """A JSON Pointer with its ``~1`` / ``~0`` escapes undone (for loose comparison)."""
    return pointer.lstrip("#").replace("~1", "/").replace("~0", "~")


def changed_objects(before: Any, after: Any, pointer: str = "") -> List[str]:
    """The pointers of the objects whose own keywords differ between ``before`` and ``after``.

    A keyword added, removed or given another value is attributed to the object that holds
    it (``/components/schemas/Pet`` when its ``nullable`` changed), so one rewritten schema is
    one entry. A list whose length changed counts as a change of the object holding it.

    Args:
        before: The document (or fragment) before a rewrite.
        after: The same document after it.
        pointer: The pointer of ``before`` / ``after`` within the document (``""`` at the root).

    Returns:
        Escaped JSON Pointers in document order, without duplicates.
    """
    found: List[str] = []
    seen: Set[str] = set()

    def note(target: str) -> None:
        if target not in seen:
            seen.add(target)
            found.append(target)

    def walk(old: Any, new: Any, at: str, parent: str) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in list(old) + [k for k in new if k not in old]:
                child = at + "/" + ProvenanceTracker.escape(str(key))
                if key not in old or key not in new:
                    note(at)
                else:
                    walk(old[key], new[key], child, at)
            return
        if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
            for index, (left, right) in enumerate(zip(old, new)):
                walk(left, right, f"{at}/{index}", at)
            return
        if old != new or type(old) is not type(new):
            note(parent)

    walk(before, after, pointer, pointer)
    return found


def record_schema_rewrites(
    before: Dict[str, Any],
    after: Dict[str, Any],
    tracker: ProvenanceTracker,
    losses: Iterable[Loss],
    detail: str,
    *,
    ignore: Iterable[str] = ("/openapi",),
) -> List[str]:
    """Record an inferred provenance note for every object a dialect rewrite changed.

    An object already named by a loss (at it, inside it, or around it) is not noted again:
    the loss is its record. ``ignore`` lists pointers that change on purpose and carry their
    own provenance (the ``openapi`` version string).

    Args:
        before: The document before the rewrite (not mutated).
        after: The document after the rewrite (not mutated).
        tracker: The emitter's provenance tracker; one record is appended per changed object.
        losses: The losses recorded so far for this emission.
        detail: What the rewrite was, e.g. ``"OpenAPI 3.0 schema rewritten into JSON Schema
            2020-12"``.
        ignore: Pointers whose change is expected and recorded elsewhere.

    Returns:
        The pointers recorded.
    """
    loss_pointers = [_unescape(loss.pointer) for loss in losses if loss.pointer]
    skipped = {_unescape(pointer) for pointer in ignore}
    recorded: List[str] = []
    for pointer in changed_objects(before, after):
        plain = _unescape(pointer)
        if plain in skipped:
            continue
        if any(
            plain == target or plain.startswith(target + "/") or target.startswith(plain + "/")
            for target in loss_pointers
        ):
            continue
        tracker.record(pointer, Provenance.INFERRED, detail)
        recorded.append(pointer)
    return recorded


def record_declared_dialect_loss(bag: Optional[Dict[str, Any]], losses: LossTracker) -> bool:
    """Record that a declared, non-default dialect cannot be kept at OpenAPI 3.0.

    A 3.1 / 3.2 source whose ``jsonSchemaDialect`` names a dialect other than the OpenAPI
    default (draft-07, a custom vocabulary) has its schemas written in the OpenAPI 3.0 subset
    instead: the keywords 3.0 shares are kept with 3.0's meaning, and the dialect itself is
    gone. The removal of the ``jsonSchemaDialect`` key is recorded by the version gate; this
    names the dialect that was lost.

    Args:
        bag: The document-level preservation bag (``capture_source``), or ``None``.
        losses: Tracker the loss is recorded on.

    Returns:
        ``True`` when a loss was recorded.
    """
    info = (bag or {}).get("schemaDialect")
    if not isinstance(info, dict) or not info.get("declared"):
        return False
    dialect = info.get("dialect")
    if is_default_dialect(dialect):
        return False
    losses.record(
        LossKind.INFERRED,
        "openapi-30-schema-dialect",
        f"schemas declared in the JSON Schema dialect {dialect} are written in the OpenAPI 3.0 "
        "schema dialect; keywords that dialect defines differently or that 3.0 lacks are not "
        "kept with their declared meaning",
        pointer="#/jsonSchemaDialect",
    )
    return True


#: ``extras`` key of the OpenAPI preservation bag (mirrors
#: :data:`app.openapi_source_preservation.OPENAPI_SOURCE_EXTRA`, which imports this module).
_SOURCE_EXTRA = "openapiSource"


def declared_type_dialect(api: Any, type_: Any) -> Optional[str]:
    """The dialect a canonical type was declared in by its OpenAPI source, if known.

    Reads the preservation bags :func:`app.openapi_source_preservation.capture_source` wrote:
    the type's own Schema Object (its ``$schema``) and the document's ``schemaDialect``.

    Args:
        api: The :class:`~app.canonical_model.CanonicalApi` the type belongs to.
        type_: The :class:`~app.canonical_model.Type`.

    Returns:
        The dialect URI, or ``None`` when the model did not come from an OpenAPI document.
    """
    bag = (getattr(api, "extras", None) or {}).get(_SOURCE_EXTRA)
    if not isinstance(bag, dict):
        return None
    info = bag.get("schemaDialect")
    document_default = info.get("dialect") if isinstance(info, dict) else default_dialect(bag.get("version"))
    type_bag = (getattr(type_, "extras", None) or {}).get(_SOURCE_EXTRA)
    schema = type_bag.get("object") if isinstance(type_bag, dict) else None
    return schema_dialect(schema, document_default, bag.get("version"))
