"""Smithy JSON AST → :class:`~app.smithy_parser.SmithyDocument` — MFI-17.1 (#3808).

The Smithy JSON AST is the assembled model: every shape of every file, keyed by its
**absolute shape id** (``example.weather#City``), with each reference already an absolute id —
so no name resolution is needed, it is read straight from ``json``::

    {
      "smithy": "2.0",
      "metadata": {...},
      "shapes": {
        "example.weather#Weather": {"type": "service", "version": "2006-03-01",
                                    "operations": [{"target": "example.weather#GetForecast"}]},
        "example.weather#City": {"type": "resource", "identifiers": {...}, "read": {...}},
        "example.weather#CityId": {"type": "string", "traits": {"smithy.api#pattern": "..."}}
      }
    }

This mapper produces the same :class:`SmithyDocument` the IDL reader does, so the normalizer is
shared. How names are written:

* a shape in the model's **primary namespace** (the namespace of its first service, otherwise
  the namespace most shapes are in) keeps its plain name (``City``);
* a shape in any other namespace keeps its absolute id (``example.common#Money``), so two
  namespaces defining the same name never collide;
* a prelude target (``smithy.api#String``) is its plain name, and a simple shape
  (``CityId: string``) resolves to its base type, as the IDL reader would read a primitive.

The model's identity — its ``$version`` (the AST's ``smithy`` key) and every namespace it
defines shapes in — is recorded on the document.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .import_source import ImportSourceError
from .smithy_parser import (
    SmithyDocument,
    SmithyEnum,
    SmithyField,
    SmithyList,
    SmithyMap,
    SmithyOperation,
    SmithyService,
    SmithyStructure,
)

__all__ = ["PRELUDE_NAMESPACE", "document_from_ast", "is_smithy_ast_document", "shape_namespace"]

#: The namespace of Smithy's built-in shapes and traits.
PRELUDE_NAMESPACE = "smithy.api"

#: Simple shape types, resolved to their prelude name (``bigInteger`` → ``BigInteger``).
_SIMPLE_TYPES = frozenset(
    {
        "blob",
        "boolean",
        "string",
        "byte",
        "short",
        "integer",
        "long",
        "float",
        "double",
        "bigInteger",
        "bigDecimal",
        "timestamp",
        "document",
    }
)

#: Resource properties that bind operations to it (each one target, or a list of targets).
_RESOURCE_OPERATION_KEYS = ("create", "put", "read", "update", "delete", "list")


def is_smithy_ast_document(value: Any) -> bool:
    """Whether ``value`` (a parsed JSON value) is a Smithy JSON AST model.

    Args:
        value: The parsed document.

    Returns:
        ``True`` for an object with a string ``smithy`` version and a ``shapes`` object.
    """
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("smithy"), str)
        and isinstance(value.get("shapes", {}), Mapping)
    )


def shape_namespace(shape_id: str) -> str:
    """The namespace of an absolute shape id (``a.b#C`` → ``a.b``; a member id is fine too)."""
    return shape_id.split("#", 1)[0]


def _local_name(shape_id: str) -> str:
    """The shape name of an absolute shape id (``a.b#C$member`` → ``C``)."""
    return shape_id.split("#", 1)[-1].split("$", 1)[0]


def _target(ref: Any) -> Optional[str]:
    """The ``target`` of a ``{"target": ...}`` reference."""
    if isinstance(ref, Mapping) and isinstance(ref.get("target"), str):
        return ref["target"]
    return None


def _targets(value: Any) -> List[str]:
    """The targets of a reference or a list of references."""
    refs = value if isinstance(value, list) else [value]
    return [t for t in (_target(ref) for ref in refs) if t]


def _trait_names(traits: Any) -> Tuple[str, ...]:
    """The local names of a shape's or member's traits (``smithy.api#required`` → ``required``)."""
    if not isinstance(traits, Mapping):
        return ()
    return tuple(_local_name(trait_id) for trait_id in traits)


def _documentation(node: Mapping[str, Any]) -> Optional[str]:
    """A shape's ``@documentation``."""
    traits = node.get("traits")
    doc = traits.get(f"{PRELUDE_NAMESPACE}#documentation") if isinstance(traits, Mapping) else None
    return doc if isinstance(doc, str) and doc.strip() else None


class _Model:
    """Name resolution over one AST's shapes."""

    def __init__(self, shapes: Mapping[str, Mapping[str, Any]]) -> None:
        self.shapes = shapes
        self.primary = self._primary_namespace()
        self.unresolved: List[str] = []

    def _primary_namespace(self) -> Optional[str]:
        """The namespace of the first service, otherwise the one most shapes are in."""
        services = sorted(sid for sid, shape in self.shapes.items() if shape.get("type") == "service")
        if services:
            return shape_namespace(services[0])
        counts = Counter(shape_namespace(sid) for sid in self.shapes)
        if not counts:
            return None
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def name(self, shape_id: str) -> str:
        """The name a defined shape is written with (plain in the primary namespace)."""
        return _local_name(shape_id) if shape_namespace(shape_id) == self.primary else shape_id

    def ref(self, target: Optional[str]) -> Optional[str]:
        """The type name a reference to ``target`` is written with; ``None`` for ``Unit``."""
        if not target:
            return None
        if shape_namespace(target) == PRELUDE_NAMESPACE:
            local = _local_name(target)
            if local == "Unit":
                return None
            # PrimitiveInteger & co. are Integer with a default of zero.
            return local[len("Primitive"):] if local.startswith("Primitive") else local
        shape = self.shapes.get(target)
        if shape is None:
            if target not in self.unresolved:
                self.unresolved.append(target)
            return target
        shape_type = shape.get("type")
        if shape_type in _SIMPLE_TYPES:
            return shape_type[0].upper() + shape_type[1:]
        return self.name(target)

    def fields(self, members: Any) -> Tuple[SmithyField, ...]:
        """A structure's / union's members as fields, in declaration order."""
        if not isinstance(members, Mapping):
            return ()
        fields: List[SmithyField] = []
        for member_name, member in members.items():
            if not isinstance(member, Mapping):
                continue
            traits = _trait_names(member.get("traits"))
            fields.append(
                SmithyField(
                    name=str(member_name),
                    type_name=self.ref(_target(member)) or "Unit",
                    required="required" in traits,
                    traits=traits,
                )
            )
        return tuple(fields)

    def bound_operations(self, shape: Mapping[str, Any], seen: Set[str]) -> List[str]:
        """The operations a service or resource binds, its resources' included, in order."""
        operation_ids: List[str] = list(_targets(shape.get("operations") or []))
        for key in _RESOURCE_OPERATION_KEYS:
            operation_ids.extend(_targets(shape.get(key)))
        operation_ids.extend(_targets(shape.get("collectionOperations") or []))
        for resource_id in _targets(shape.get("resources") or []):
            if resource_id in seen:
                continue
            resource = self.shapes.get(resource_id)
            if isinstance(resource, Mapping):
                operation_ids.extend(self.bound_operations(resource, seen | {resource_id}))
        return list(dict.fromkeys(operation_ids))


def _identity(ast: Mapping[str, Any], shapes: Iterable[str]) -> Tuple[str, Tuple[str, ...]]:
    """The model's ``$version`` and every namespace it defines shapes in."""
    return str(ast["smithy"]), tuple(sorted({shape_namespace(sid) for sid in shapes}))


def document_from_ast(
    ast: Mapping[str, Any],
    *,
    raw: str,
    model_sha256: Optional[str] = None,
    source_files: Tuple[str, ...] = (),
    source_label: Optional[str] = None,
) -> SmithyDocument:
    """Build a :class:`SmithyDocument` from a Smithy JSON AST.

    Args:
        ast: The JSON AST (``smithy``, ``metadata``, ``shapes``).
        raw: The text kept as the document's ``raw`` (the root model file).
        model_sha256: The AST's hash (:func:`app.smithy_ast.ast_sha256`).
        source_files: The model files it was assembled from.
        source_label: Label used in error messages.

    Returns:
        The document.

    Raises:
        ImportSourceError: ``INPUT_MALFORMED`` when ``ast`` is not a JSON AST;
            ``INPUT_REFERENCE_UNRESOLVED`` when a shape targets one that is neither in the
            model nor in the prelude; ``INPUT_SEMANTIC_INVALID`` when the model has no shapes.
    """
    label = f" ({source_label})" if source_label else ""
    if not is_smithy_ast_document(ast):
        raise ImportSourceError(
            f"Not a Smithy JSON AST model{label}: expected an object with `smithy` and `shapes`.",
            code="INPUT_MALFORMED",
        )
    shapes: Dict[str, Mapping[str, Any]] = {
        sid: shape
        for sid, shape in (ast.get("shapes") or {}).items()
        if isinstance(sid, str) and "#" in sid and isinstance(shape, Mapping)
    }
    if not shapes:
        raise ImportSourceError(f"No Smithy shapes found in model{label}", code="INPUT_SEMANTIC_INVALID")

    model = _Model(shapes)
    structures: List[SmithyStructure] = []
    enums: List[SmithyEnum] = []
    lists: List[SmithyList] = []
    maps: List[SmithyMap] = []
    operations: List[SmithyOperation] = []
    services: List[SmithyService] = []

    for shape_id in sorted(shapes):
        shape = shapes[shape_id]
        shape_type = shape.get("type")
        name = model.name(shape_id)
        doc = _documentation(shape)
        if shape_type in ("structure", "union"):
            fields = model.fields(shape.get("members"))
            structures.append(SmithyStructure(name=name, kind=shape_type, fields=fields, documentation=doc))
        elif shape_type == "resource":
            identifiers = {
                key: {"target": target, "traits": {f"{PRELUDE_NAMESPACE}#required": {}}}
                for key, target in (
                    (key, _target(ref)) for key, ref in (shape.get("identifiers") or {}).items()
                )
                if target
            }
            fields = model.fields(identifiers)
            structures.append(SmithyStructure(name=name, kind="resource", fields=fields, documentation=doc))
        elif shape_type in ("enum", "intEnum"):
            values = tuple(str(member) for member in (shape.get("members") or {}))
            if values:
                enums.append(SmithyEnum(name=name, values=values, documentation=doc))
        elif shape_type in ("list", "set"):
            member = model.ref(_target(shape.get("member")))
            if member:
                lists.append(SmithyList(name=name, member=member, documentation=doc))
        elif shape_type == "map":
            key, value = model.ref(_target(shape.get("key"))), model.ref(_target(shape.get("value")))
            if key and value:
                maps.append(SmithyMap(name=name, key=key, value=value, documentation=doc))
        elif shape_type == "operation":
            operations.append(
                SmithyOperation(
                    name=name,
                    input_type=model.ref(_target(shape.get("input"))),
                    output_type=model.ref(_target(shape.get("output"))),
                    documentation=doc,
                )
            )
        elif shape_type == "service":
            bound = model.bound_operations(shape, {shape_id})
            version = shape.get("version")
            services.append(
                SmithyService(
                    name=name,
                    version=version if isinstance(version, str) else None,
                    operations=tuple(model.name(op) for op in bound),
                    documentation=doc,
                )
            )

    if model.unresolved:
        raise ImportSourceError(
            f"The Smithy model{label} targets shapes it does not define: "
            f"{', '.join(model.unresolved)}. Add the files that define them.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    version, namespaces = _identity(ast, shapes)
    return SmithyDocument(
        version=version,
        namespace=model.primary,
        structures=tuple(structures),
        enums=tuple(enums),
        lists=tuple(lists),
        maps=tuple(maps),
        operations=tuple(operations),
        services=tuple(services),
        raw=raw,
        namespaces=namespaces,
        model_sha256=model_sha256,
        source_files=source_files,
    )
