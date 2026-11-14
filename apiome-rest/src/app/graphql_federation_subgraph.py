"""GraphQL Federation subgraph output mode — MFX-13.6 (#4344).

A plain GraphQL SDL export cannot join a federated supergraph: the subgraph spec needs a
federation ``@link`` header and an ``@key`` on every entity. The GraphQL emitter's
``federation`` option turns its output into Federation v2 **subgraph SDL** with the helpers
here:

* **Entity keys** — :func:`entity_keys` decides which object types are entities and which
  fields key them. A type that already applies ``@key`` (a subgraph source) keeps its own key.
  Otherwise the key is **synthesized** from the type's canonical identity fields, in order:
  its declared primary key (``extras["sql_key"]``, a SQL or dbt source), its ``id`` field, or
  its one field of the ``ID`` scalar. A synthesized key is reported — a ``SYNTH`` verdict in
  the fidelity preview and an ``inferred`` loss on the export — so a reader sees the choice.
  A type with none of these stays a plain value type.
* **Definitions while attaching** — :func:`with_federation_definitions` adds the Federation
  directive definitions the printed SDL lacks, so the emitter can re-attach the source's
  applied ``@key`` / ``@shareable`` / … instead of skipping them as undefined.
* **Subgraph SDL** — :func:`to_subgraph_sdl` turns the attached SDL into what a subgraph
  library or ``rover`` expects: the Federation (and supergraph ``join``) machinery
  definitions are removed, the synthesized ``@key``\\s are applied, and an
  ``extend schema @link(url: …, import: […])`` header imports every Federation directive the
  document uses. The result is re-built through :func:`app.graphql_parser.build_graphql_schema`
  (which supplies the linked definitions) so the export always re-imports.

Everything here is pure over the canonical model and ``graphql-core`` AST nodes; the
optional ``rover supergraph compose`` check lives with the other toolchain checks in
:mod:`app.export_tool_checks`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Mapping, Optional, Sequence, Set, Tuple

from graphql import parse, print_ast
from graphql.language.ast import (
    DirectiveDefinitionNode,
    DirectiveNode,
    DocumentNode,
    ObjectTypeDefinitionNode,
    SchemaDefinitionNode,
    SchemaExtensionNode,
    StringValueNode,
    TypeDefinitionNode,
)

from .canonical_model import CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from .graphql_federation import federation_prelude_definitions, parse_directive_applications

__all__ = [
    "FEDERATION_LINK_URL",
    "EntityKey",
    "KeyBasis",
    "SubgraphSdl",
    "entity_key_for",
    "entity_keys",
    "to_subgraph_sdl",
    "with_federation_definitions",
]

#: The Federation spec version the subgraph links — matches the composition version the
#: ``rover`` check pins (:data:`app.graphql_federation.ROVER_FEDERATION_VERSION`).
FEDERATION_LINK_URL = "https://specs.apollo.dev/federation/v2.9"

#: Schema-level ``@link``\\s to these specs (federation, link, join) are replaced by ours.
_APOLLO_SPEC_PREFIX = "https://specs.apollo.dev/"

#: Machinery names a subgraph never defines itself: the linked spec supplies them, and the
#: supergraph ``join`` machinery has no place in a subgraph.
_MACHINERY_PREFIXES = ("federation__", "link__", "join__")

#: Root type names — never entities.
_ROOT_NAMES = frozenset({"Query", "Mutation", "Subscription"})

#: The GraphQL ID scalar's name in the canonical model.
_ID_SCALAR = "ID"

_KEY_APPLICATION_RE = re.compile(r"^\s*@key\b")


class KeyBasis(str, Enum):
    """Where an entity's ``@key`` comes from."""

    SOURCE = "source"  # the source already applies @key (kept as is)
    DECLARED = "declared"  # synthesized from the declared primary key
    ID_FIELD = "id-field"  # synthesized from the field named ``id``
    ID_TYPE = "id-type"  # synthesized from the one field of the ID scalar


@dataclass(frozen=True)
class EntityKey:
    """One entity of the subgraph and the fields that key it.

    Attributes:
        type_key: The canonical key of the entity type.
        fields: The source field names in the key, in order; empty for a ``SOURCE`` key
            (the source's own ``@key`` application is re-attached verbatim).
        basis: Where the key comes from.
    """

    type_key: str
    fields: Tuple[str, ...]
    basis: KeyBasis

    @property
    def synthesized(self) -> bool:
        """Whether the emitter invents this ``@key`` (every basis but ``SOURCE``)."""
        return self.basis is not KeyBasis.SOURCE

    def describe(self) -> str:
        """A short phrase naming the identity the key was synthesized from (for reports)."""
        listed = ", ".join(self.fields)
        if self.basis is KeyBasis.DECLARED:
            return f"its declared primary key ({listed})"
        if self.basis is KeyBasis.ID_FIELD:
            return f"its `{listed}` field"
        if self.basis is KeyBasis.ID_TYPE:
            return f"its only ID field `{listed}`"
        return "its own @key"


# ---------------------------------------------------------------------------
# Entity keys (canonical model)
# ---------------------------------------------------------------------------


def _is_entity_candidate(type_: Type) -> bool:
    """Whether ``type_`` is emitted as a GraphQL object type that may carry ``@key``.

    Args:
        type_: A canonical type.

    Returns:
        ``True`` for an output ``RECORD`` (GraphQL family ``object``) that is neither a root
        type nor spec machinery.
    """
    if type_.kind is not TypeKind.RECORD:
        return False
    if (type_.extras or {}).get("graphql_type", "object") != "object":
        return False
    return type_.name not in _ROOT_NAMES and not type_.name.startswith(_MACHINERY_PREFIXES)


def _has_source_key(type_: Type) -> bool:
    """Whether the source already applies ``@key`` to ``type_`` (``extras["directives"]``)."""
    applied = (type_.extras or {}).get("directives") or []
    return any(isinstance(item, str) and _KEY_APPLICATION_RE.match(item) for item in applied)


def _leaf_ref(ref: TypeRef, types_by_key: Mapping[str, Type]) -> TypeRef:
    """Follow ``ALIAS`` types from ``ref`` to the reference they stand for (cycle-safe)."""
    seen: Set[str] = set()
    while ref.name is not None and ref.name not in seen:
        target = types_by_key.get(ref.name)
        if target is None or target.kind is not TypeKind.ALIAS or target.aliased is None:
            break
        seen.add(ref.name)
        ref = target.aliased
    return ref


def _key_eligible(field: CanonicalField, types_by_key: Mapping[str, Type]) -> bool:
    """Whether ``field`` can be part of a key: a single scalar or enum value.

    A list, an object, a union, a map or an untyped value cannot key an entity. A name the
    model does not define is a primitive (``string``, ``ID`` …) that the emitter writes as a
    scalar.

    Args:
        field: A field of the candidate entity.
        types_by_key: The model's types by key.

    Returns:
        ``True`` when the field may appear in ``@key(fields:)``.
    """
    ref = _leaf_ref(field.type, types_by_key)
    if ref.is_list() or ref.name is None:
        return False
    target = types_by_key.get(ref.name)
    return target is None or target.kind in (TypeKind.SCALAR, TypeKind.ENUM)


def _declared_key(type_: Type, types_by_key: Mapping[str, Type]) -> Optional[Tuple[str, ...]]:
    """The declared primary key's field names, when every one is a key-eligible field."""
    declared = ((type_.extras or {}).get("sql_key") or {}).get("primary_key") or {}
    columns = declared.get("columns") if isinstance(declared, Mapping) else None
    if not isinstance(columns, list) or not columns:
        return None
    by_name = {field.name: field for field in type_.fields}
    members = [by_name.get(str(column)) for column in columns]
    if any(member is None or not _key_eligible(member, types_by_key) for member in members):
        return None
    return tuple(member.name for member in members if member is not None)


def entity_key_for(type_: Type, types_by_key: Mapping[str, Type]) -> Optional[EntityKey]:
    """Decide whether ``type_`` is an entity and which fields key it.

    Args:
        type_: A canonical type.
        types_by_key: The model's types by key (to resolve field types).

    Returns:
        The entity's key, or ``None`` when the type is not an object type or has no identity
        field (it stays a value type).
    """
    if not _is_entity_candidate(type_):
        return None
    if _has_source_key(type_):
        return EntityKey(type_key=type_.key, fields=(), basis=KeyBasis.SOURCE)
    declared = _declared_key(type_, types_by_key)
    if declared:
        return EntityKey(type_key=type_.key, fields=declared, basis=KeyBasis.DECLARED)
    eligible = [field for field in type_.fields if _key_eligible(field, types_by_key)]
    named_id = next((field for field in eligible if field.name.lower() == "id"), None)
    if named_id is not None:
        return EntityKey(type_key=type_.key, fields=(named_id.name,), basis=KeyBasis.ID_FIELD)
    id_typed = [field for field in eligible if _leaf_ref(field.type, types_by_key).name == _ID_SCALAR]
    if len(id_typed) == 1:
        return EntityKey(type_key=type_.key, fields=(id_typed[0].name,), basis=KeyBasis.ID_TYPE)
    return None


def entity_keys(api: CanonicalApi) -> List[EntityKey]:
    """Every entity of ``api`` in federation mode, in type-key order.

    Args:
        api: The canonical model being exported.

    Returns:
        One :class:`EntityKey` per entity type.
    """
    types_by_key = {type_.key: type_ for type_ in api.types}
    keys = (entity_key_for(type_, types_by_key) for type_ in sorted(api.types, key=lambda t: t.key))
    return [key for key in keys if key is not None]


# ---------------------------------------------------------------------------
# Subgraph SDL (printed document)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubgraphSdl:
    """The result of :func:`to_subgraph_sdl`.

    Attributes:
        sdl: The Federation v2 subgraph SDL.
        imports: The Federation directive names the ``@link`` header imports, sorted.
        keyed: The object type names a synthesized ``@key`` was applied to, sorted.
        entities: Every object type name that carries an ``@key`` (synthesized or the
            source's own), sorted.
    """

    sdl: str
    imports: Tuple[str, ...]
    keyed: Tuple[str, ...]
    entities: Tuple[str, ...]


def _federation_directive_names() -> Set[str]:
    """The Federation directive names a subgraph imports through ``@link`` (``@link`` itself excluded)."""
    return {
        name
        for name, node in federation_prelude_definitions().items()
        if isinstance(node, DirectiveDefinitionNode) and name != "link"
    }


def with_federation_definitions(sdl: str) -> str:
    """Append the Federation definitions ``sdl`` does not define yet.

    The emitter prints its schema without the Federation directives, so the applied ``@key``
    / ``@shareable`` … it re-attaches from the source would be skipped as undefined. This adds
    every missing prelude definition (directives and their support types) first;
    :func:`to_subgraph_sdl` removes them all again afterwards.

    Args:
        sdl: The printed SDL.

    Returns:
        The SDL with the missing Federation definitions appended.
    """
    document = parse(sdl)
    defined = {
        definition.name.value
        for definition in document.definitions
        if isinstance(definition, (DirectiveDefinitionNode, TypeDefinitionNode))
    }
    missing = [node for name, node in federation_prelude_definitions().items() if name not in defined]
    if not missing:
        return sdl
    return print_ast(DocumentNode(definitions=(*document.definitions, *missing)))


def _is_machinery(name: str, prelude_names: Set[str]) -> bool:
    """Whether a definition named ``name`` belongs to the linked specs, not the subgraph."""
    return name in prelude_names or name.startswith(_MACHINERY_PREFIXES)


def _strip_join_applications(node: Any) -> None:
    """Remove supergraph ``@join__*`` applications from ``node`` and its fields, values and arguments."""
    directives = getattr(node, "directives", None)
    if directives:
        node.directives = tuple(d for d in directives if not d.name.value.startswith("join__"))
    for child_attr in ("fields", "values", "arguments"):
        for child in getattr(node, child_attr, None) or ():
            _strip_join_applications(child)


def _links_apollo_spec(directive: DirectiveNode) -> bool:
    """Whether ``directive`` is a schema ``@link`` to a federation / link / join spec."""
    if directive.name.value != "link":
        return False
    for argument in directive.arguments or ():
        if argument.name.value == "url" and isinstance(argument.value, StringValueNode):
            return argument.value.value.startswith(_APOLLO_SPEC_PREFIX)
    return False


def _applied_names(node: Any, into: Set[str]) -> None:
    """Collect every applied directive name under ``node`` into ``into``."""
    for directive in getattr(node, "directives", None) or ():
        into.add(directive.name.value)
    for child_attr in ("fields", "values", "arguments"):
        for child in getattr(node, child_attr, None) or ():
            _applied_names(child, into)


def _default_roots_only(definition: Any) -> bool:
    """Whether a schema block names only default roots (``query: Query`` …), or none."""
    return all(
        operation.type.name.value == operation.operation.value.capitalize()
        for operation in definition.operation_types or ()
    )


def _link_header(imports: Sequence[str]) -> SchemaExtensionNode:
    """``extend schema @link(url: FEDERATION_LINK_URL, import: [...])``."""
    arguments = f"url: {json.dumps(FEDERATION_LINK_URL)}"
    if imports:
        listed = ", ".join(json.dumps(f"@{name}") for name in imports)
        arguments += f", import: [{listed}]"
    (link,) = parse_directive_applications([f"@link({arguments})"])
    return SchemaExtensionNode(directives=(link,), operation_types=())


def to_subgraph_sdl(sdl: str, keys: Mapping[str, Sequence[str]]) -> SubgraphSdl:
    """Turn emitted SDL into Federation v2 subgraph SDL.

    Removes the Federation / ``link`` / ``join`` machinery definitions and ``@join__*``
    applications, replaces any schema ``@link`` to an Apollo spec, applies ``@key`` to each
    entity in ``keys`` that has none yet, and prepends an ``extend schema @link`` header that
    imports every Federation directive the document applies.

    Args:
        sdl: The emitted SDL (applied directives already re-attached, Federation definitions
            present or not).
        keys: Emitted object type name → emitted field names of its synthesized key. A name
            the document does not define (a type no root reaches is not printed) is ignored.

    Returns:
        The subgraph SDL, its imports, and which types were keyed.

    Raises:
        ValueError: When the subgraph SDL does not build (with the linked definitions).
    """
    from .graphql_parser import GraphQlParseError, build_graphql_schema

    document = parse(sdl)
    prelude_names = set(federation_prelude_definitions())
    kept: List[Any] = []
    keyed: List[str] = []
    entities: List[str] = []
    for definition in document.definitions:
        name = getattr(getattr(definition, "name", None), "value", None)
        if isinstance(definition, (DirectiveDefinitionNode, TypeDefinitionNode)) and name is not None:
            if _is_machinery(name, prelude_names):
                continue
        if isinstance(definition, (SchemaDefinitionNode, SchemaExtensionNode)):
            definition.directives = tuple(
                d for d in definition.directives or () if not _links_apollo_spec(d)
            )
            if not definition.directives and _default_roots_only(definition):
                continue  # what a printer omits anyway: a bare block of default-named roots
        _strip_join_applications(definition)
        if isinstance(definition, ObjectTypeDefinitionNode) and name is not None:
            existing = tuple(definition.directives or ())
            has_key = any(d.name.value == "key" for d in existing)
            if not has_key and name in keys:
                selection = " ".join(keys[name])
                definition.directives = existing + tuple(
                    parse_directive_applications([f"@key(fields: {json.dumps(selection)})"])
                )
                keyed.append(name)
            if has_key or name in keyed:
                entities.append(name)
        kept.append(definition)

    applied: Set[str] = set()
    for definition in kept:
        _applied_names(definition, applied)
    imports = sorted(applied & _federation_directive_names())
    subgraph = print_ast(DocumentNode(definitions=(_link_header(imports), *kept)))
    try:
        build_graphql_schema(subgraph)
    except GraphQlParseError as exc:
        raise ValueError(f"Emitted GraphQL subgraph failed validation: {exc}") from exc
    return SubgraphSdl(
        sdl=subgraph + ("" if subgraph.endswith("\n") else "\n"),
        imports=tuple(imports),
        keyed=tuple(sorted(keyed)),
        entities=tuple(sorted(entities)),
    )

