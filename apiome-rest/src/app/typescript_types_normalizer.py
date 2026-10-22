"""TypeScript type declarations → canonical model normalizer — FMT-8.1 (#5462).

Maps a :class:`~app.typescript_types_parser.TsDocument` — the neutral JSON AST the bundled
TypeScript extractor produced — onto a :class:`~app.canonical_model.CanonicalApi` with the
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA` paradigm.

**What becomes what.**

* An ``interface`` becomes a ``RECORD``; ``extends`` is flattened (the parents' members first,
  the child's own members overriding them by name) and the parents are named in
  ``typescript_extends``. An interface that is nothing but an index signature is a ``MAP``.
* A ``type`` alias becomes whatever its right-hand side is: an object literal is a ``RECORD``,
  a union of object shapes or named types is a ``UNION`` (inline variants become records named
  after their discriminant), a union of literals is an ``ENUM``, an intersection of object
  shapes is one merged ``RECORD``, ``Record``/``Map`` is a ``MAP``, and anything else is an
  ``ALIAS`` of the type it names.
* An ``enum`` (``const`` or not) becomes an ``ENUM`` with each member's constant value.
* A member's optional marker and a ``| null`` / ``| undefined`` in its type both map to a
  nullable reference — FMT-8.1's "optional properties map to nullability" — and the optional
  and readonly modifiers are kept in ``typescript_optional`` / ``typescript_readonly``.
* ``Pick``, ``Omit``, ``Partial``, ``Required``, ``Readonly``, indexed access types and ``keyof``
  arrive already evaluated by the compiler, so they model as the shape they produce.

**Generics are resolved where they are instantiated.** ``type OrderPage = Page<Order>`` is a
``RECORD`` named ``OrderPage`` with ``Page``'s members and ``T`` replaced by ``Order``; an
inline ``Paginated<Customer>`` becomes a record named ``Paginated_Customer``. A generic that is
never instantiated is not a type at all — it is a declared limit.

**What is declared, never guessed.** Conditional, mapped and template-literal types, function
types, symbol keys, unbound type parameters and merged interfaces are each recorded in
``extras['typescript']['capability_limits']`` with the reviewed wording from
:data:`app.typescript_types_parser.LIMIT_DETAILS`, and the declaration or member that needed one
is left out of the model. Nothing here ever widens an unsupported construct to ``any``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, coerce_constraints, normalize_ordering
from .typescript_types_parser import LimitRecorder, TsDocument, TsLimit

__all__ = ["TYPESCRIPT_EXTRAS_KEY", "TYPESCRIPT_TYPES_FORMAT", "TypeScriptTypesNormalizer"]

#: The format key the normalizer registers under.
TYPESCRIPT_TYPES_FORMAT = "typescript-types"

#: The key the projection record sits under in ``CanonicalApi.extras``.
TYPESCRIPT_EXTRAS_KEY = "typescript"

#: TypeScript primitive -> canonical scalar (and the constraints it implies).
_PRIMITIVE_SCALARS: Dict[str, Tuple[str, Optional[Constraints]]] = {
    "string": ("string", None),
    "number": ("number", None),
    "boolean": ("boolean", None),
    "bigint": ("bigint", None),
    "null": ("null", None),
    "undefined": ("null", None),
    "void": ("null", None),
    "any": ("any", None),
    "unknown": ("unknown", None),
    "integer": ("integer", None),
    "object": ("object", None),
    "date": ("string", Constraints(format="date-time")),
    "bytes": ("bytes", None),
}

#: Primitives with no data meaning — a ``never`` member, a ``symbol`` value — and the limit
#: that declares them.
_UNMODELLED_PRIMITIVES: Dict[str, str] = {
    "never": "typescript.type_query",
    "symbol": "typescript.symbol_key",
}

#: The AST's out-of-subset construct names -> the declared limit key.
_UNSUPPORTED_LIMITS: Dict[str, str] = {
    "conditional_type": "typescript.conditional_type",
    "mapped_type": "typescript.mapped_type",
    "template_literal_type": "typescript.template_literal_type",
    "function_type": "typescript.function_type",
    "symbol_key": "typescript.symbol_key",
    "type_query": "typescript.type_query",
    "lib_type": "typescript.lib_type",
}

#: Library collections that are lists.
_LIST_LIBS = frozenset({"Array", "ReadonlyArray"})
#: Library collections that are sets (lists of unique items).
_SET_LIBS = frozenset({"Set", "ReadonlySet"})
#: Library collections that are maps.
_MAP_LIBS = frozenset({"Map", "ReadonlyMap", "Record"})


def _sanitize(name: str) -> str:
    """Return ``name`` folded to the characters a canonical key may carry."""
    folded = "".join(
        character if (character.isalnum() or character in "_$") else "_" for character in name
    ).strip("_")
    return folded or "value"


def _limit_key(construct: Optional[str]) -> str:
    """The declared limit an AST ``unsupported`` construct belongs to.

    A construct that is already a full limit key (``zod.function``) is passed through: a sibling
    reader that reuses this model (FMT-8.2's Zod reader) names its own constructs.
    """
    if construct and "." in construct:
        return construct
    return _UNSUPPORTED_LIMITS.get(construct or "", "typescript.type_query")


def _substitute(node: Any, env: Dict[str, Any]) -> Any:
    """Replace every bound ``typeParameter`` beneath ``node`` with its argument.

    Arguments are substituted *before* a generic body is read, so the body is closed over its
    instantiation and nothing downstream has to carry a scope. A parameter with no binding is
    left in place and is declared an unresolved generic where it is met.
    """
    if isinstance(node, dict):
        if node.get("kind") == "typeParameter" and node.get("name") in env:
            return env[node["name"]]
        return {key: _substitute(value, env) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(value, env) for value in node]
    return node


def _signature(node: Any) -> str:
    """A stable text form of an AST node, for caching instantiations."""
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def _label(node: Any) -> str:
    """A short, readable name fragment for a type argument (``Customer``, ``StringList``)."""
    kind = node.get("kind") if isinstance(node, dict) else None
    if kind == "ref":
        args = "_".join(_label(argument) for argument in node.get("typeArguments") or [])
        return _sanitize(node.get("name", "Ref")) + (f"_{args}" if args else "")
    if kind == "primitive":
        return str(node.get("name", "value")).capitalize()
    if kind == "literal":
        return _sanitize(str(node.get("value")))
    if kind == "array":
        return f"{_label(node.get('element'))}List"
    if kind == "lib":
        args = "_".join(_label(argument) for argument in node.get("typeArguments") or [])
        return _sanitize(node.get("name", "Lib")) + (f"_{args}" if args else "")
    if kind == "evaluated":
        return _label(node.get("type"))
    if kind == "union":
        return "Or".join(_label(member) for member in node.get("members") or [])[:60] or "Union"
    return "Object"


def _literal_scalar(value: Any) -> str:
    """The canonical scalar a literal value belongs to."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _is_nullish(node: Any) -> bool:
    """Whether a union member is ``null`` / ``undefined`` (it makes the use site nullable)."""
    return (
        isinstance(node, dict)
        and node.get("kind") == "primitive"
        and node.get("name") in {"null", "undefined", "void"}
    )


class _Shape:
    """A converted use-site type: the reference, its constraints and extras to attach."""

    __slots__ = ("ref", "constraints", "extras")

    def __init__(
        self,
        ref: TypeRef,
        constraints: Optional[Constraints] = None,
        extras: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ref = ref
        self.constraints = constraints
        self.extras = extras or {}


class _Model:
    """One document's walk from the extractor's AST to canonical types.

    Owns the four things every step needs: the declarations by id, the types built so far (by
    key, so an intersection can read a built record's fields), the instantiation cache, and the
    limit recorder.
    """

    def __init__(self, document: TsDocument, limits: LimitRecorder) -> None:
        self.document = document
        self.declarations = document.by_id()
        self.limits = limits
        self.types: Dict[str, Type] = {}
        self._claimed: Set[str] = set()
        #: (declaration id, argument signature) -> built type key, or ``None`` when the
        #: declaration could not be modelled.
        self._built: Dict[Tuple[str, str], Optional[str]] = {}
        #: Generic declarations that were instantiated at least once.
        self._instantiated: Set[str] = set()
        self._declared_merges: Set[str] = set()
        #: AST nodes whose attached ``limits`` were already recorded (a node is met once as a
        #: named type and again if it is converted, and must count once). Keyed by ``id`` and
        #: holding the node itself, so a collected node's id cannot be reused by a new one.
        self._noted: Dict[int, Any] = {}

    def _note_limits(self, node: Any, location: str) -> None:
        """Record the declared limits a sibling reader attached to an AST node.

        The TypeScript extractor never attaches any; FMT-8.2's Zod reader marks a ``refine``,
        ``transform`` or ``brand`` on the node whose shape it still models.
        """
        if not isinstance(node, dict) or not node.get("limits") or self._noted.get(id(node)) is node:
            return
        self._noted[id(node)] = node
        for construct in node["limits"]:
            self.limits.record(_limit_key(construct), location=location)

    # --- naming ---------------------------------------------------------------------------

    def reserve(self, name: str) -> None:
        """Claim a declared type's own name before any synthetic name can take it."""
        self._claimed.add(name)

    def claim(self, parts: Sequence[str]) -> str:
        """Reserve a unique name for a synthetic type built from a path of name parts."""
        base = "_".join(_sanitize(part) for part in parts if part) or "Value"
        name = base
        suffix = 2
        while name in self._claimed:
            name = f"{base}_{suffix}"
            suffix += 1
        self._claimed.add(name)
        return name

    def add(self, type_: Type) -> str:
        """Record a completed type and return its key."""
        self.types[type_.key] = type_
        return type_.key

    # --- declarations ---------------------------------------------------------------------

    def ensure(
        self,
        declaration_id: str,
        args: Sequence[Any],
        *,
        location: str,
        referenced: bool = True,
    ) -> Optional[str]:
        """Build (once) the type a reference names, and return its key.

        A non-generic declaration is built under its own name. A generic one is built per
        distinct argument list, under ``<Name>_<ArgLabels>``. A generic referenced with too few
        arguments and no defaults, a merged interface, or a declaration that was itself a limit
        yields ``None`` — the caller records why.

        Args:
            declaration_id: The ``<module>#<name>`` id the reference resolved to.
            args: The reference's (already closed) type arguments.
            location: Where the reference sits, for limit locations.
            referenced: ``False`` when the declaration is being modelled for its own sake (an
                export) rather than because a member points at it — then a declaration that
                cannot be modelled has already recorded its own limit, and there is no member
                to declare an ``unmodelled_reference`` for.

        Returns:
            The built type's key, or ``None`` when it cannot be modelled.
        """
        declaration = self.declarations.get(declaration_id)
        if declaration is None:
            self.limits.record("typescript.unmodelled_reference", location=location)
            return None
        env = self._bindings(declaration, args)
        if env is None:
            self.limits.record("typescript.unresolved_generic", location=location)
            return None

        cache_key = (declaration_id, _signature(sorted(env.items())))
        if cache_key in self._built:
            built = self._built[cache_key]
            if built is None and referenced:
                self.limits.record("typescript.unmodelled_reference", location=location)
            return built

        if env:
            self._instantiated.add(declaration_id)
            name = self.claim(
                [
                    declaration["name"],
                    *(_label(env[p["name"]]) for p in declaration["typeParameters"]),
                ]
            )
        else:
            name = declaration["name"]
        key = Keys.type(name)
        # Cached before the body is read, so a self-referencing declaration (a tree node whose
        # children are nodes) resolves to its own key instead of recursing forever.
        self._built[cache_key] = key
        built = self.build(declaration, name=name, key=key, env=env)
        if built is None:
            self._built[cache_key] = None
            if referenced:
                self.limits.record("typescript.unmodelled_reference", location=location)
            return None
        return built

    def _bindings(
        self, declaration: Dict[str, Any], args: Sequence[Any]
    ) -> Optional[Dict[str, Any]]:
        """Bind a declaration's type parameters to arguments (or their defaults).

        Returns:
            Parameter name -> argument, ``{}`` for a non-generic declaration, or ``None`` when a
            parameter has neither an argument nor a default.
        """
        env: Dict[str, Any] = {}
        for index, parameter in enumerate(declaration.get("typeParameters") or []):
            if index < len(args):
                env[parameter["name"]] = args[index]
            elif parameter.get("default") is not None:
                env[parameter["name"]] = _substitute(parameter["default"], env)
            else:
                return None
        return env

    def declare_exported(self, declaration: Dict[str, Any]) -> None:
        """Model one exported declaration under its own name (generics wait for a use)."""
        if declaration.get("typeParameters"):
            return
        self.ensure(declaration["id"], (), location=declaration["name"], referenced=False)

    def report_uninstantiated(self, exported: Sequence[Dict[str, Any]]) -> None:
        """Declare every exported generic that no reference ever instantiated.

        A generic whose parameters all have defaults is modelled with them. Otherwise the
        generic is a limit — and when its body is itself outside the subset (``type Unwrap<T> =
        T extends Promise<infer U> ? U : T``) the body's construct is what is declared, since
        that, not the missing argument, is why it cannot be modelled.
        """
        for declaration in exported:
            if not declaration.get("typeParameters") or declaration["id"] in self._instantiated:
                continue
            if all(p.get("default") is not None for p in declaration["typeParameters"]):
                self.ensure(declaration["id"], (), location=declaration["name"], referenced=False)
                continue
            body = declaration.get("type") if declaration.get("kind") == "alias" else None
            if isinstance(body, dict) and body.get("kind") == "unsupported":
                self.limits.record(_limit_key(body.get("construct")), location=declaration["name"])
            else:
                self.limits.record("typescript.unresolved_generic", location=declaration["name"])

    def build(
        self, declaration: Dict[str, Any], *, name: str, key: str, env: Dict[str, Any]
    ) -> Optional[str]:
        """Build one declaration (closed over ``env``) as the named type ``key``."""
        if int(declaration.get("mergedDeclarations") or 1) > 1:
            if declaration["id"] not in self._declared_merges:
                self._declared_merges.add(declaration["id"])
                self.limits.record("typescript.declaration_merging", location=declaration["name"])
            return None
        common = {
            "description": declaration.get("doc"),
            "deprecated": bool(declaration.get("deprecated")),
        }
        kind = declaration.get("kind")
        if kind == "enum":
            return self.add(self._enum(declaration, name=name, key=key, common=common))
        if kind == "interface":
            body = _substitute(
                {
                    "kind": "object",
                    "properties": declaration.get("properties") or [],
                    "indexSignatures": declaration.get("indexSignatures") or [],
                    "unsupported": declaration.get("unsupported") or [],
                },
                env,
            )
            parents = [_substitute(parent, env) for parent in declaration.get("extends") or []]
            return self.named(body, name=name, key=key, common=common, parents=parents)
        body = _substitute(declaration.get("type"), env)
        return self.named(body, name=name, key=key, common=common)

    def _enum(
        self, declaration: Dict[str, Any], *, name: str, key: str, common: Dict[str, Any]
    ) -> Type:
        """An ``enum`` declaration as a canonical ``ENUM``."""
        values = [
            EnumValue(
                key=Keys.enum_value(key, member["name"]),
                name=member["name"],
                value=member.get("value"),
                description=member.get("doc"),
                deprecated=bool(member.get("deprecated")),
            )
            for member in declaration.get("members") or []
        ]
        extras = {"typescript_kind": "const_enum" if declaration.get("const") else "enum"}
        return Type(
            key=key, name=name, kind=TypeKind.ENUM, enum_values=values, extras=extras, **common
        )

    # --- named types (the right-hand side of a declaration) -------------------------------

    def named(
        self,
        node: Any,
        *,
        name: str,
        key: str,
        common: Dict[str, Any],
        parents: Sequence[Any] = (),
        extras: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Build ``node`` as the named type ``key``, choosing the canonical kind it deserves.

        Returns:
            ``key``, or ``None`` when the node is outside the subset (the limit is recorded).
        """
        extras = dict(extras or {})
        kind = node.get("kind") if isinstance(node, dict) else None
        self._note_limits(node, name)

        if kind == "evaluated":
            extras["typescript_evaluated"] = {"via": node.get("via"), "text": node.get("text")}
            return self.named(node.get("type"), name=name, key=key, common=common, extras=extras)

        if kind == "object" or parents:
            obj = (
                node
                if kind == "object"
                else {"kind": "object", "properties": [], "indexSignatures": []}
            )
            return self._record_or_map(
                obj, name=name, key=key, common=common, parents=parents, extras=extras
            )

        if kind == "union":
            return self._union_type(node, name=name, key=key, common=common, extras=extras)

        if kind == "intersection":
            merged = self._merge_intersection(node, location=name)
            if merged is not None:
                extras["typescript_kind"] = "intersection"
                return self._record_or_map(merged, name=name, key=key, common=common, extras=extras)

        if kind == "lib" and node.get("name") in _MAP_LIBS:
            map_type = self._map_type(node, name=name, key=key, location=name)
            if map_type is None:
                return None
            return self.add(
                map_type.model_copy(update={**common, "extras": {**map_type.extras, **extras}})
            )

        if kind == "ref":
            target = self.declarations.get(node.get("target", ""))
            if (
                target is not None
                and target.get("typeParameters")
                and int(target.get("mergedDeclarations") or 1) == 1
            ):
                # `type OrderPage = Page<Order>`: the instantiation *is* the alias, so it is
                # built under the alias's own name rather than as a second, synthetic type.
                env = self._bindings(target, node.get("typeArguments") or [])
                if env is None:
                    self.limits.record("typescript.unresolved_generic", location=name)
                    return None
                self._instantiated.add(target["id"])
                extras["typescript_instantiates"] = target["name"]
                built = self.build(target, name=name, key=key, env=env)
                if built is not None:
                    self._tag(key, extras, common)
                return built

        shape = self.convert(node, path=(name,), location=name)
        if shape is None:
            return None
        return self.add(
            Type(
                key=key,
                name=name,
                kind=TypeKind.ALIAS,
                aliased=shape.ref,
                constraints=shape.constraints,
                extras={**shape.extras, **extras},
                **common,
            )
        )

    def _tag(self, key: str, extras: Dict[str, Any], common: Dict[str, Any]) -> None:
        """Merge extras and the alias's own documentation into a type built under its name."""
        built = self.types[key]
        update: Dict[str, Any] = {"extras": {**built.extras, **extras}}
        if common.get("description"):
            update["description"] = common["description"]
        if common.get("deprecated"):
            update["deprecated"] = True
        self.types[key] = built.model_copy(update=update)

    def _record_or_map(
        self,
        node: Dict[str, Any],
        *,
        name: str,
        key: str,
        common: Dict[str, Any],
        parents: Sequence[Any] = (),
        extras: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """An object shape (plus inherited members) as a ``RECORD``, or a ``MAP`` when it is
        nothing but an index signature."""
        extras = {**(node.get("extras") or {}), **(extras or {})}
        properties, signatures, unsupported, parent_names = self._flatten(
            node, parents, location=name
        )
        if parent_names:
            extras["typescript_extends"] = parent_names

        for member in unsupported:
            self.limits.record(
                _limit_key(member.get("construct")), location=f"{name}.{member.get('name')}"
            )

        if not properties and len(signatures) == 1:
            map_type = self._map_from_signature(signatures[0], name=name, key=key, location=name)
            if map_type is None:
                return None
            return self.add(
                map_type.model_copy(update={**common, "extras": {**map_type.extras, **extras}})
            )

        # Registered before its fields are converted, so a member that refers back to this
        # record (directly or through an inline shape) finds it.
        self.add(Type(key=key, name=name, kind=TypeKind.RECORD, extras=extras, **common))
        fields = self._fields(properties, owner_key=key, owner_name=name)
        if signatures:
            self.limits.record("typescript.index_signature", location=name)
            extras["typescript_index"] = [self._signature_extra(s, name=name) for s in signatures]
        self.types[key] = self.types[key].model_copy(update={"fields": fields, "extras": extras})
        return key

    def _flatten(
        self, node: Dict[str, Any], parents: Sequence[Any], *, location: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """Collect an object's members with its parents' first, the child's own overriding.

        Returns:
            ``(properties, index signatures, unsupported members, parent names)``.
        """
        by_name: Dict[str, Dict[str, Any]] = {}
        signatures: List[Dict[str, Any]] = []
        unsupported: List[Dict[str, Any]] = []
        names: List[str] = []
        for parent in parents:
            members = self._members_of(parent, location=location, seen=set())
            if members is None:
                continue
            names.append(_label(parent) if parent.get("typeArguments") else str(parent.get("name")))
            for prop in members["properties"]:
                by_name[prop["name"]] = prop
            signatures.extend(members["indexSignatures"])
        for prop in node.get("properties") or []:
            by_name[prop["name"]] = prop
        signatures.extend(node.get("indexSignatures") or [])
        unsupported.extend(node.get("unsupported") or [])
        return list(by_name.values()), signatures, unsupported, names

    def _members_of(
        self, node: Any, *, location: str, seen: Set[str]
    ) -> Optional[Dict[str, List[Any]]]:
        """The (closed) members an ``extends`` target or intersection operand contributes.

        Returns:
            ``{"properties": [...], "indexSignatures": [...]}``, or ``None`` when the operand
            is not an object shape (the caller records why).
        """
        kind = node.get("kind") if isinstance(node, dict) else None
        if kind == "object":
            return {
                "properties": list(node.get("properties") or []),
                "indexSignatures": list(node.get("indexSignatures") or []),
            }
        if kind == "evaluated":
            return self._members_of(node.get("type"), location=location, seen=seen)
        if kind == "intersection":
            merged = self._merge_intersection(node, location=location)
            return (
                None if merged is None else self._members_of(merged, location=location, seen=seen)
            )
        if kind == "unsupported":
            self.limits.record(_limit_key(node.get("construct")), location=location)
            return None
        if kind != "ref":
            return None
        target = self.declarations.get(node.get("target", ""))
        if target is None or target["id"] in seen:
            return None
        if int(target.get("mergedDeclarations") or 1) > 1:
            self.build(target, name=target["name"], key=Keys.type(target["name"]), env={})
            self.limits.record("typescript.unmodelled_reference", location=location)
            return None
        env = self._bindings(target, node.get("typeArguments") or [])
        if env is None:
            self.limits.record("typescript.unresolved_generic", location=location)
            return None
        if env:
            self._instantiated.add(target["id"])
        if target.get("kind") == "interface":
            own = _substitute(
                {
                    "properties": target.get("properties") or [],
                    "indexSignatures": target.get("indexSignatures") or [],
                },
                env,
            )
            inherited: Dict[str, Any] = {}
            signatures: List[Any] = []
            for parent in _substitute(target.get("extends") or [], env):
                members = self._members_of(parent, location=location, seen=seen | {target["id"]})
                if members is not None:
                    for prop in members["properties"]:
                        inherited[prop["name"]] = prop
                    signatures.extend(members["indexSignatures"])
            for prop in own["properties"]:
                inherited[prop["name"]] = prop
            return {
                "properties": list(inherited.values()),
                "indexSignatures": signatures + own["indexSignatures"],
            }
        if target.get("kind") == "alias":
            return self._members_of(
                _substitute(target.get("type"), env), location=location, seen=seen | {target["id"]}
            )
        return None

    def _merge_intersection(
        self, node: Dict[str, Any], *, location: str
    ) -> Optional[Dict[str, Any]]:
        """Merge an intersection of object shapes into one object, or declare it a limit."""
        properties: Dict[str, Any] = {}
        signatures: List[Any] = []
        for member in node.get("members") or []:
            members = self._members_of(member, location=location, seen=set())
            if members is None:
                self.limits.record("typescript.intersection", location=location)
                return None
            for prop in members["properties"]:
                properties[prop["name"]] = prop
            signatures.extend(members["indexSignatures"])
        return {
            "kind": "object",
            "properties": list(properties.values()),
            "indexSignatures": signatures,
        }

    def _fields(
        self, properties: Sequence[Dict[str, Any]], *, owner_key: str, owner_name: str
    ) -> List[CanonicalField]:
        """Convert an object's properties; a property outside the subset is left out."""
        fields: List[CanonicalField] = []
        for prop in properties:
            location = f"{owner_name}.{prop['name']}"
            shape = self.convert(
                prop.get("type"), path=(owner_name, prop["name"]), location=location
            )
            if shape is None:
                continue
            extras = dict(shape.extras)
            if prop.get("optional"):
                extras["typescript_optional"] = True
            if prop.get("readonly"):
                extras["typescript_readonly"] = True
            nullable = bool(prop.get("optional")) or shape.ref.nullable
            fields.append(
                CanonicalField(
                    key=Keys.field(owner_key, prop["name"]),
                    name=prop["name"],
                    type=shape.ref.model_copy(update={"nullable": nullable}),
                    constraints=shape.constraints,
                    default=prop.get("default"),
                    description=prop.get("doc"),
                    deprecated=bool(prop.get("deprecated")),
                    extras=extras,
                )
            )
        return fields

    def _union_type(
        self,
        node: Dict[str, Any],
        *,
        name: str,
        key: str,
        common: Dict[str, Any],
        extras: Dict[str, Any],
    ) -> Optional[str]:
        """A named union: an ``ENUM`` of literals, or a ``UNION`` over its variants."""
        members = list(node.get("members") or [])
        if members and all(m.get("kind") == "literal" or _is_nullish(m) for m in members):
            literals = [m for m in members if m.get("kind") == "literal"]
            if literals:
                if len(literals) < len(members):
                    extras["typescript_nullable"] = True
                return self.add(
                    self._literal_enum(literals, name=name, key=key, common=common, extras=extras)
                )
        variant_keys = self._variants(members, path=(name,), location=name)
        if variant_keys is None:
            return None
        if len(variant_keys) == 1 and variant_keys[0] != "null":
            # `string | undefined` and the like: one real member, so the alias names it.
            return self.add(
                Type(
                    key=key,
                    name=name,
                    kind=TypeKind.ALIAS,
                    aliased=TypeRef(name=variant_keys[0], nullable=True),
                    extras=extras,
                    **common,
                )
            )
        return self.add(
            Type(
                key=key,
                name=name,
                kind=TypeKind.UNION,
                union_members=variant_keys,
                extras=extras,
                **common,
            )
        )

    def _literal_enum(
        self,
        literals: Sequence[Dict[str, Any]],
        *,
        name: str,
        key: str,
        common: Optional[Dict[str, Any]] = None,
        extras: Optional[Dict[str, Any]] = None,
    ) -> Type:
        """A union of literals as a canonical ``ENUM`` whose values are the literals."""
        values: List[EnumValue] = []
        seen: Set[str] = set()
        for literal in literals:
            label = _sanitize(str(literal.get("value")))
            unique = label
            suffix = 2
            while unique in seen:
                unique = f"{label}_{suffix}"
                suffix += 1
            seen.add(unique)
            value = literal.get("value")
            values.append(EnumValue(key=Keys.enum_value(key, unique), name=str(value), value=value))
        return Type(
            key=key,
            name=name,
            kind=TypeKind.ENUM,
            enum_values=values,
            extras={"typescript_kind": "literal_union", **(extras or {})},
            **(common or {}),
        )

    def _variants(
        self, members: Sequence[Any], *, path: Tuple[str, ...], location: str
    ) -> Optional[List[str]]:
        """Resolve a union's members to canonical member keys.

        Named types contribute their key, primitives their scalar name, and inline object
        shapes become records named after their discriminant (``Union_circle``) or position.
        Literals are grouped into one enum member. A member outside the subset makes the whole
        union unmodellable — dropping a variant would silently narrow it.
        """
        discriminant = self._discriminant(members)
        keys: List[str] = []
        literals: List[Dict[str, Any]] = []
        for index, member in enumerate(members):
            kind = member.get("kind") if isinstance(member, dict) else None
            if kind == "literal":
                literals.append(member)
                continue
            if _is_nullish(member):
                key = "null"
            elif kind == "object" or (
                kind == "evaluated" and member.get("type", {}).get("kind") == "object"
            ):
                obj = member if kind == "object" else member["type"]
                label = self._variant_label(obj, discriminant, index)
                variant_name = self.claim([*path, label])
                key = self._record_or_map(
                    obj, name=variant_name, key=Keys.type(variant_name), common={}
                )
            else:
                shape = self.convert(member, path=(*path, str(index + 1)), location=location)
                if shape is None:
                    return None
                if shape.ref.name and not shape.ref.is_list() and not shape.constraints:
                    key = shape.ref.name
                else:
                    alias_name = self.claim([*path, _label(member)])
                    key = self.add(
                        Type(
                            key=Keys.type(alias_name),
                            name=alias_name,
                            kind=TypeKind.ALIAS,
                            aliased=shape.ref.model_copy(update={"nullable": False}),
                            constraints=shape.constraints,
                            extras=shape.extras,
                        )
                    )
            if key is None:
                return None
            if key not in keys:
                keys.append(key)
        if literals:
            enum_name = self.claim([*path, "literal"])
            keys.append(
                self.add(self._literal_enum(literals, name=enum_name, key=Keys.type(enum_name)))
            )
        return keys

    @staticmethod
    def _discriminant(members: Sequence[Any]) -> Optional[str]:
        """The property every inline object variant carries as a distinct string literal."""
        objects = [m for m in members if isinstance(m, dict) and m.get("kind") == "object"]
        if len(objects) < 2:
            return None
        candidates: Optional[Set[str]] = None
        for obj in objects:
            names = {
                p["name"]
                for p in obj.get("properties") or []
                if (p.get("type") or {}).get("kind") == "literal"
                and isinstance(p["type"].get("value"), str)
            }
            candidates = names if candidates is None else candidates & names
        for name in sorted(candidates or ()):
            values = [
                next(p["type"]["value"] for p in obj["properties"] if p["name"] == name)
                for obj in objects
            ]
            if len(set(values)) == len(values):
                return name
        return None

    @staticmethod
    def _variant_label(obj: Dict[str, Any], discriminant: Optional[str], index: int) -> str:
        """Name an inline union variant by its discriminant value, else by its position."""
        if discriminant:
            for prop in obj.get("properties") or []:
                if prop["name"] == discriminant:
                    return _sanitize(str(prop["type"]["value"]))
        return f"variant{index + 1}"

    # --- maps -----------------------------------------------------------------------------

    def _map_type(
        self, node: Dict[str, Any], *, name: str, key: str, location: str
    ) -> Optional[Type]:
        """``Record<K, V>`` / ``Map<K, V>`` as a canonical ``MAP``."""
        args = list(node.get("typeArguments") or [])
        if len(args) != 2:
            self.limits.record("typescript.lib_type", location=location)
            return None
        key_shape = self.convert(args[0], path=(name, "key"), location=location)
        value_shape = self.convert(args[1], path=(name, "value"), location=location)
        if key_shape is None or value_shape is None:
            return None
        return Type(
            key=key,
            name=name,
            kind=TypeKind.MAP,
            key_type=key_shape.ref.model_copy(update={"nullable": False}),
            value_type=value_shape.ref,
            extras={"typescript_kind": str(node.get("name"))},
        )

    def _map_from_signature(
        self, signature: Dict[str, Any], *, name: str, key: str, location: str
    ) -> Optional[Type]:
        """An object made only of ``[key: K]: V`` as a canonical ``MAP``."""
        return self._map_type(
            {
                "name": "index_signature",
                "typeArguments": [signature.get("keyType"), signature.get("valueType")],
            },
            name=name,
            key=key,
            location=location,
        )

    def _signature_extra(self, signature: Dict[str, Any], *, name: str) -> Dict[str, Any]:
        """Render an index signature that sits beside named properties, for ``extras``."""
        value = self.convert(signature.get("valueType"), path=(name, "additional"), location=name)
        key = self.convert(signature.get("keyType"), path=(name, "key"), location=name)
        return {
            "key_name": signature.get("keyName"),
            "key_type": key.ref.model_dump() if key else None,
            "value_type": value.ref.model_dump() if value else None,
            "readonly": bool(signature.get("readonly")),
        }

    # --- use sites --------------------------------------------------------------------------

    def convert(self, node: Any, *, path: Tuple[str, ...], location: str) -> Optional[_Shape]:
        """Convert one use-site type node, then apply what a sibling reader attached to it.

        A node may carry declared ``limits`` (recorded here, at ``location``) and JSON-Schema
        ``constraints`` (merged over the ones the node's kind implies). The TypeScript
        extractor attaches neither; FMT-8.2's Zod reader attaches both.

        Args:
            node: The (closed) AST node.
            path: Name parts for any synthetic type this use site needs.
            location: Where the use site sits, for limit locations.

        Returns:
            The converted shape, or ``None`` when the node is outside the subset.
        """
        self._note_limits(node, location)
        shape = self._convert_node(node, path=path, location=location)
        extra = node.get("constraints") if isinstance(node, dict) else None
        if shape is not None and extra:
            attached = coerce_constraints(extra)
            if attached is not None:
                merged = shape.constraints.model_dump(exclude_none=True) if shape.constraints else {}
                merged.update(attached.model_dump(exclude_none=True))
                shape.constraints = Constraints(**merged)
        return shape

    def _convert_node(
        self, node: Any, *, path: Tuple[str, ...], location: str
    ) -> Optional[_Shape]:
        """Convert one use-site type node into a canonical reference.

        Named shapes an inline node needs (an object literal, a union of objects, a map) are
        created as synthetic types named from ``path``.

        Args:
            node: The (closed) AST node.
            path: Name parts for any synthetic type this use site needs.
            location: Where the use site sits, for limit locations.

        Returns:
            The converted shape, or ``None`` when the node is outside the subset (the limit is
            recorded and the caller leaves the member out).
        """
        kind = node.get("kind") if isinstance(node, dict) else None

        if kind == "primitive":
            name = node.get("name")
            if name in _UNMODELLED_PRIMITIVES:
                self.limits.record(_UNMODELLED_PRIMITIVES[name], location=location)
                return None
            scalar, constraints = _PRIMITIVE_SCALARS.get(name, ("any", None))
            nullable = name in {"null", "undefined", "void"}
            extras = {"typescript_implicit_any": True} if node.get("implicit") else {}
            return _Shape(TypeRef(name=scalar, nullable=nullable), constraints, extras)

        if kind == "literal":
            value = node.get("value")
            return _Shape(
                TypeRef(name=_literal_scalar(value), nullable=False), Constraints(enum=[value])
            )

        if kind == "ref":
            built = self.ensure(
                node.get("target", ""), node.get("typeArguments") or [], location=location
            )
            if built is None:
                return None
            return _Shape(TypeRef(name=built, nullable=False))

        if kind == "typeParameter":
            self.limits.record("typescript.unresolved_generic", location=location)
            return None

        if kind == "unresolved":
            self.limits.record("typescript.type_query", location=location)
            return None

        if kind == "unsupported":
            self.limits.record(_limit_key(node.get("construct")), location=location)
            return None

        if kind == "evaluated":
            shape = self.convert(node.get("type"), path=path, location=location)
            if shape is not None:
                shape.extras["typescript_evaluated"] = {
                    "via": node.get("via"),
                    "text": node.get("text"),
                }
            return shape

        if kind == "array" or (kind == "lib" and node.get("name") in _LIST_LIBS | _SET_LIBS):
            element = (
                node.get("element") if kind == "array" else (node.get("typeArguments") or [None])[0]
            )
            item = self.convert(element, path=(*path, "item"), location=location)
            if item is None:
                return None
            constraints = (
                Constraints(unique_items=True)
                if kind == "lib" and node.get("name") in _SET_LIBS
                else None
            )
            extras = {"typescript_item": item.extras} if item.extras else {}
            if item.constraints is not None:
                extras["typescript_item_constraints"] = item.constraints.model_dump(
                    exclude_none=True
                )
            return _Shape(TypeRef(item=item.ref, nullable=False), constraints, extras)

        if kind == "lib" and node.get("name") in _MAP_LIBS:
            name = self.claim(path)
            map_type = self._map_type(node, name=name, key=Keys.type(name), location=location)
            if map_type is None:
                return None
            return _Shape(TypeRef(name=self.add(map_type), nullable=False))

        if kind == "tuple":
            return self._tuple(node, path=path, location=location)

        if kind == "union":
            return self._union_use(node, path=path, location=location)

        if kind == "intersection":
            merged = self._merge_intersection(node, location=location)
            if merged is None:
                first = (node.get("members") or [None])[0]
                shape = self.convert(first, path=path, location=location)
                if shape is not None:
                    shape.extras["typescript_intersection"] = [
                        _label(m) for m in node.get("members") or []
                    ]
                return shape
            name = self.claim(path)
            key = self._record_or_map(
                merged,
                name=name,
                key=Keys.type(name),
                common={},
                extras={"typescript_kind": "intersection"},
            )
            return None if key is None else _Shape(TypeRef(name=key, nullable=False))

        if kind == "object":
            name = self.claim(path)
            key = self._record_or_map(node, name=name, key=Keys.type(name), common={})
            return None if key is None else _Shape(TypeRef(name=key, nullable=False))

        self.limits.record("typescript.type_query", location=location)
        return None

    def _union_use(
        self, node: Dict[str, Any], *, path: Tuple[str, ...], location: str
    ) -> Optional[_Shape]:
        """A union at a use site: nullable members fold into the reference, literals into an
        ``enum`` constraint, and anything else becomes a synthetic ``UNION`` type."""
        members = list(node.get("members") or [])
        nullable = any(_is_nullish(m) for m in members)
        rest = [m for m in members if not _is_nullish(m)]
        if not rest:
            return _Shape(TypeRef(name="null", nullable=True))
        if len(rest) == 1:
            shape = self.convert(rest[0], path=path, location=location)
            if shape is not None and nullable:
                shape.ref = shape.ref.model_copy(update={"nullable": True})
            return shape
        if all(m.get("kind") == "literal" for m in rest):
            scalars = {_literal_scalar(m.get("value")) for m in rest}
            if len(scalars) == 1:
                return _Shape(
                    TypeRef(name=scalars.pop(), nullable=nullable),
                    Constraints(enum=[m.get("value") for m in rest]),
                )
        name = self.claim(path)
        keys = self._variants(rest, path=(name,), location=location)
        if keys is None:
            return None
        key = self.add(
            Type(key=Keys.type(name), name=name, kind=TypeKind.UNION, union_members=keys)
        )
        return _Shape(TypeRef(name=key, nullable=nullable))

    def _tuple(
        self, node: Dict[str, Any], *, path: Tuple[str, ...], location: str
    ) -> Optional[_Shape]:
        """A tuple as a bounded list over the union of its element types (positions recorded)."""
        elements = list(node.get("elements") or [])
        rendered: List[Dict[str, Any]] = []
        item_members: List[Any] = []
        for element in elements:
            element_type = element.get("type")
            if (
                element.get("rest")
                and isinstance(element_type, dict)
                and element_type.get("kind") == "array"
            ):
                element_type = element_type.get("element")
            item_members.append(element_type)
            rendered.append(
                {
                    "name": element.get("name"),
                    "type": _label(element_type),
                    "optional": bool(element.get("optional")),
                    "rest": bool(element.get("rest")),
                }
            )
        distinct: List[Any] = []
        for member in item_members:
            if _signature(member) not in {_signature(seen) for seen in distinct}:
                distinct.append(member)
        item_node = distinct[0] if len(distinct) == 1 else {"kind": "union", "members": distinct}
        item = self.convert(item_node, path=(*path, "item"), location=location)
        if item is None:
            return None
        self.limits.record("typescript.tuple_positions", location=location)
        required = sum(1 for e in elements if not e.get("optional") and not e.get("rest"))
        has_rest = any(e.get("rest") for e in elements)
        constraints = Constraints(min_items=required, max_items=None if has_rest else len(elements))
        return _Shape(
            TypeRef(item=item.ref, nullable=False), constraints, {"typescript_tuple": rendered}
        )


def _identity_name(document: TsDocument) -> str:
    """The model's name: the root module's first exported interface, else its first export.

    The filename is not consulted, so a module pasted and the same module uploaded catalog as
    one API rather than two.
    """
    exported = document.exported()
    own = [d for d in exported if d.get("module") == document.root] or exported
    for declaration in own:
        if declaration.get("kind") == "interface":
            return str(declaration["name"])
    return str(own[0]["name"]) if own else "TypeScriptTypes"


def _limits_payload(limits: Sequence[TsLimit]) -> List[Dict[str, Any]]:
    """Render declared limits as the extras bag's ``capability_limits``."""
    return [
        {
            "construct": limit.construct,
            "detail": limit.detail,
            "count": limit.count,
            "locations": list(limit.locations),
        }
        for limit in limits
    ]


class TypeScriptTypesNormalizer(Normalizer, register=True):
    """Normalize a parsed TypeScript module (or module set) into a :class:`CanonicalApi`."""

    format = TYPESCRIPT_TYPES_FORMAT
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.typescript_types_parser.TsDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep the module sources on ``raw``.

        Returns:
            The canonical model: one ``data_schema`` API holding every exported type and every
            declaration they reach.

        Raises:
            ValueError: When ``source`` is not a :class:`TsDocument`.
        """
        if not isinstance(source, TsDocument):
            raise ValueError(
                "TypeScript source must be a TsDocument "
                "(see app.typescript_types_parser.parse_typescript_types)"
            )

        limits = LimitRecorder()
        model = _Model(source, limits)
        exported = source.exported()
        for declaration in exported:
            model.reserve(declaration["name"])
        for declaration in exported:
            model.declare_exported(declaration)
        model.report_uninstantiated(exported)

        name = _identity_name(source)
        typescript: Dict[str, Any] = {
            "root_module": source.root,
            "modules": list(source.files),
            "exports": [d["name"] for d in exported],
            "capability_limits": _limits_payload(limits.limits()),
        }
        root_type = Keys.type(name)
        if root_type in model.types:
            typescript["root_type"] = root_type

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=name),
            title=name,
            types=list(model.types.values()),
            raw={"typescript": dict(source.sources)} if include_raw else None,
            extras={TYPESCRIPT_EXTRAS_KEY: typescript},
        )
        return normalize_ordering(api)
