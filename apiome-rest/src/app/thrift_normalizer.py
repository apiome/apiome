"""Apache Thrift IDL → canonical model normalizer — MFI-11.2.

Maps a parsed :class:`~app.thrift_parser.ThriftDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`. Structs, unions, exceptions and enums become
:class:`~app.canonical_model.Type` definitions; service methods become
:class:`~app.canonical_model.Service` / :class:`~app.canonical_model.Operation` pairs with
field numbers preserved on :class:`~app.canonical_model.CanonicalField.field_number`.

A multi-file set (MFI-19.3, :mod:`app.thrift_fileset`) contributes every included file's
definitions, keyed under that file's namespace (or its include prefix when it declares none);
a qualified reference such as ``shared.Money`` resolves to the included file's type. A service
that ``extends`` another records the base service's key in ``extras.thrift_extends``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .thrift_parser import ThriftDocument, ThriftField

__all__ = ["ThriftNormalizer"]

_FORMAT_KEY = "thrift"

_THRIFT_BASE_TO_CANONICAL: Dict[str, str] = {
    "bool": "bool",
    "byte": "int8",
    "i8": "int8",
    "i16": "i16",
    "i32": "i32",
    "i64": "i64",
    "double": "double",
    "string": "string",
    "binary": "bytes",
    "uuid": "uuid",
}


def _primary_namespace(document: ThriftDocument) -> Optional[str]:
    if not document.namespaces:
        return None
    # Prefer a stable language key when present.
    for lang in ("java", "py", "go", "cpp", "rb"):
        if lang in document.namespaces:
            return document.namespaces[lang]
    return next(iter(document.namespaces.values()))


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


#: How deep a chain of typedefs across included files is followed before giving up.
_MAX_TYPEDEF_DEPTH = 32


@dataclass
class _Scope:
    """One Thrift file's naming context (MFI-19.3).

    Attributes:
        document: The file.
        namespace: The namespace its definitions are keyed under: its own ``namespace``, or,
            for an included file that declares none, its include prefix.
        names: The enums and structs (incl. unions and exceptions) it defines.
        includes: Include prefix → the included file's scope.
    """

    document: ThriftDocument
    namespace: Optional[str]
    names: frozenset[str]
    includes: Dict[str, "_Scope"] = field(default_factory=dict)


def _build_scopes(root: ThriftDocument) -> List[_Scope]:
    """The scope of ``root`` and of every file it includes, transitively, root first.

    A file included from several places gets one scope.
    """
    scopes: Dict[int, _Scope] = {}
    order: List[_Scope] = []

    def build(document: ThriftDocument, fallback_namespace: Optional[str]) -> _Scope:
        existing = scopes.get(id(document))
        if existing is not None:
            return existing
        scope = _Scope(
            document=document,
            namespace=_primary_namespace(document) or fallback_namespace,
            names=frozenset(e.name for e in document.enums) | frozenset(s.name for s in document.structs),
        )
        scopes[id(document)] = scope
        order.append(scope)
        for prefix, included in document.included.items():
            scope.includes[prefix] = build(included, prefix)
        return scope

    build(root, None)
    return order


def _named_ref(
    name: str,
    *,
    scope: _Scope,
    map_types: Dict[str, Type],
    depth: int = 0,
) -> Optional[TypeRef]:
    """Resolve a named type (``Money``, ``shared.Money``) against ``scope``.

    A qualified name is looked up in the included file with that prefix; a typedef there is
    followed. Returns ``None`` when the name is not a definition this set knows.
    """
    if depth > _MAX_TYPEDEF_DEPTH:
        return None
    if name in scope.names:
        return TypeRef(name=_type_key(name, scope.namespace))
    typedef = scope.document.typedefs.get(name) if scope.document.included or depth else None
    if typedef:
        return _type_ref_from_expr(typedef, scope=scope, map_types=map_types, depth=depth + 1)
    prefix, _, rest = name.partition(".")
    target = scope.includes.get(prefix) if rest else None
    if target is None:
        return None
    return _named_ref(rest, scope=target, map_types=map_types, depth=depth + 1)


def _type_ref_from_expr(
    type_expr: str,
    *,
    scope: _Scope,
    map_types: Dict[str, Type],
    depth: int = 0,
) -> TypeRef:
    t = type_expr.strip()
    base = _THRIFT_BASE_TO_CANONICAL.get(t)
    if base:
        return TypeRef(name=base)

    def inner(expr: str) -> TypeRef:
        return _type_ref_from_expr(expr, scope=scope, map_types=map_types, depth=depth)

    list_match = re.fullmatch(r"list\s*<\s*([\w.<>,]+)\s*>", t)
    if list_match:
        return TypeRef(item=inner(list_match.group(1)))

    set_match = re.fullmatch(r"set\s*<\s*([\w.<>,]+)\s*>", t)
    if set_match:
        return TypeRef(item=inner(set_match.group(1)), extras={"thrift_container": "set"})

    map_match = re.fullmatch(r"map\s*<\s*([\w.<>,]+)\s*,\s*([\w.<>,]+)\s*>", t)
    if map_match:
        key_expr = map_match.group(1).strip()
        value_expr = map_match.group(2).strip()
        map_key = f"map<{key_expr},{value_expr}>"
        if map_key not in map_types:
            map_types[map_key] = Type(
                key=Keys.type(map_key.replace("<", "_").replace(">", "_").replace(",", "_"), scope.namespace),
                name=map_key,
                kind=TypeKind.MAP,
                key_type=inner(key_expr),
                value_type=inner(value_expr),
                extras={"thrift_map": True},
            )
        return TypeRef(name=map_types[map_key].key)

    named = _named_ref(t, scope=scope, map_types=map_types, depth=depth)
    if named is not None:
        return named
    return TypeRef(name=t)


def _canonical_field(
    thrift_field: ThriftField,
    *,
    type_key: str,
    scope: _Scope,
    map_types: Dict[str, Type],
) -> CanonicalField:
    ref = _type_ref_from_expr(thrift_field.type_expr, scope=scope, map_types=map_types)
    extras: Dict[str, Any] = {}
    if thrift_field.default is not None:
        extras["thrift_default"] = thrift_field.default
    extras["thrift_required"] = thrift_field.required
    return CanonicalField(
        key=Keys.field(type_key, thrift_field.name),
        name=thrift_field.name,
        type=TypeRef(
            name=ref.name,
            item=ref.item,
            nullable=not thrift_field.required,
            extras=ref.extras,
        ),
        field_number=thrift_field.id,
        extras=extras,
    )


def _scope_types(scope: _Scope, map_types: Dict[str, Type]) -> List[Type]:
    """The enums, structs, unions and exceptions one file defines."""
    namespace = scope.namespace
    types: List[Type] = []
    for enum in scope.document.enums:
        type_key = _type_key(enum.name, namespace)
        values = [
            EnumValue(
                key=Keys.enum_value(type_key, name),
                name=name,
                value=number if number is not None else index,
                # MFI-19.3: an implicit value moves when values are reordered (lint).
                extras={} if number is not None else {"thrift_implicit_value": True},
            )
            for index, (name, number) in enumerate(enum.values)
        ]
        types.append(
            Type(
                key=type_key,
                name=enum.name,
                kind=TypeKind.ENUM,
                namespace=namespace,
                enum_values=values,
                extras={"thrift_kind": "enum"},
            )
        )

    for struct in scope.document.structs:
        type_key = _type_key(struct.name, namespace)
        kind = TypeKind.UNION if struct.kind == "union" else TypeKind.RECORD
        fields = [
            _canonical_field(field_, type_key=type_key, scope=scope, map_types=map_types)
            for field_ in struct.fields
        ]
        types.append(
            Type(
                key=type_key,
                name=struct.name,
                kind=kind,
                namespace=namespace,
                fields=fields,
                extras={"thrift_kind": struct.kind},
            )
        )
    return types


def _service_key(name: str, scope: _Scope) -> str:
    """The key of a service named ``name`` (``Base`` / ``shared.Base``) as seen from ``scope``."""
    prefix, _, rest = name.partition(".")
    target = scope.includes.get(prefix) if rest else None
    if target is not None:
        return Keys.type(rest, target.namespace)
    return Keys.type(name, scope.namespace)


def _scope_services(scope: _Scope, map_types: Dict[str, Type]) -> List[Service]:
    """The services one file defines, each method an operation."""
    services: List[Service] = []
    for svc in scope.document.services:
        service_key = Keys.type(svc.name, scope.namespace)
        operations: List[Operation] = []
        for method in svc.methods:
            op_key = Keys.operation_rpc(service_key, method.name)
            messages: List[Message] = []
            if method.parameters:
                # Thrift positional args are modeled as a synthetic request struct ref
                # when there is exactly one parameter, otherwise inline parameters in extras.
                if len(method.parameters) == 1:
                    param = method.parameters[0]
                    messages.append(
                        Message(
                            key=Keys.request_message(op_key),
                            role=MessageRole.REQUEST,
                            payload=_type_ref_from_expr(param.type_expr, scope=scope, map_types=map_types),
                            required=param.required,
                        )
                    )
                else:
                    messages.append(
                        Message(
                            key=Keys.request_message(op_key),
                            role=MessageRole.REQUEST,
                            required=True,
                            extras={
                                "thrift_parameters": [
                                    {
                                        "id": p.id,
                                        "name": p.name,
                                        "type": p.type_expr,
                                        "required": p.required,
                                    }
                                    for p in method.parameters
                                ]
                            },
                        )
                    )
            if method.return_type != "void":
                messages.append(
                    Message(
                        key=f"{op_key}#response",
                        role=MessageRole.RESPONSE,
                        payload=_type_ref_from_expr(method.return_type, scope=scope, map_types=map_types),
                    )
                )
            for field_id, exc_type, alias in method.throws:
                payload = _named_ref(exc_type, scope=scope, map_types=map_types) or TypeRef(
                    name=_type_key(exc_type, scope.namespace)
                )
                messages.append(
                    Message(
                        key=f"{op_key}#error.{alias}",
                        role=MessageRole.ERROR,
                        name=alias,
                        payload=payload,
                        extras={"thrift_throw_id": field_id},
                    )
                )
            one_way = method.oneway or method.return_type == "void"
            kind = OperationKind.ONE_WAY if one_way else OperationKind.REQUEST_RESPONSE
            operations.append(
                Operation(
                    key=op_key,
                    name=method.name,
                    kind=kind,
                    streaming=StreamingMode.NONE,
                    messages=messages,
                    extras={"thrift_oneway": method.oneway},
                )
            )
        services.append(
            Service(
                key=service_key,
                name=svc.name,
                operations=operations,
                extras={"thrift_extends": _service_key(svc.extends, scope)} if svc.extends else {},
            )
        )
    return services


def _first_by_key(items: List[Any]) -> List[Any]:
    """``items`` with later duplicates of a ``key`` dropped (two files defining one name)."""
    seen: set[str] = set()
    kept = []
    for item in items:
        if item.key not in seen:
            seen.add(item.key)
            kept.append(item)
    return kept


class ThriftNormalizer(Normalizer, register=True):
    """Normalize a parsed Thrift document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, ThriftDocument):
            raise ValueError("Thrift source must be a ThriftDocument (see app.thrift_parser.parse_thrift)")

        scopes = _build_scopes(source)
        namespace = scopes[0].namespace
        map_types: Dict[str, Type] = {}

        types: List[Type] = []
        services: List[Service] = []
        for scope in scopes:
            types.extend(_scope_types(scope, map_types))
            services.extend(_scope_services(scope, map_types))
        types.extend(map_types.values())
        types = _first_by_key(types)
        services = _first_by_key(services)

        identity_name = namespace or (services[0].name if services else "Thrift API")
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=identity_name, namespace=namespace),
            services=services,
            types=types,
            raw={"thrift": source.raw} if include_raw else None,
            extras={
                "thrift_namespaces": dict(source.namespaces),
                "thrift_includes": list(source.includes),
                "thrift_typedefs": dict(source.typedefs),
                # MFI-19.3: the files of a multi-file set the API was built from.
                **(
                    {"thrift_source_files": sorted(scope.document.path for scope in scopes if scope.document.path)}
                    if source.path
                    else {}
                ),
            },
        )
        return normalize_ordering(api)
