"""Smithy IDL → canonical model normalizer.

Maps a parsed :class:`~app.smithy_parser.SmithyDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

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
from .smithy_parser import SmithyDocument, SmithyField

__all__ = ["SmithyNormalizer"]

_FORMAT_KEY = "smithy"

_SMITHY_PRIMITIVES: Dict[str, str] = {
    "String": "string",
    "Integer": "integer",
    "Float": "float",
    "Double": "double",
    "Boolean": "boolean",
    "Blob": "bytes",
    "Timestamp": "datetime",
    "Document": "object",
    "BigInteger": "integer",
    "BigDecimal": "number",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref(
    type_name: str,
    *,
    namespace: Optional[str],
    structure_names: Set[str],
    enum_names: Set[str],
    list_names: Set[str],
    map_names: Set[str],
    list_types: Dict[str, Type],
    map_types: Dict[str, Type],
) -> TypeRef:
    primitive = _SMITHY_PRIMITIVES.get(type_name)
    if primitive:
        return TypeRef(name=primitive, nullable=False)

    if type_name in list_names:
        list_type = list_types.get(type_name)
        if list_type and list_type.aliased:
            return TypeRef(name=list_type.key, nullable=False)
        return TypeRef(name=_type_key(type_name, namespace), nullable=False)

    if type_name in map_names:
        map_type = map_types.get(type_name)
        if map_type:
            return TypeRef(name=map_type.key, nullable=False)
        return TypeRef(name=_type_key(type_name, namespace), nullable=False)

    if type_name in enum_names or type_name in structure_names:
        return TypeRef(name=_type_key(type_name, namespace), nullable=False)

    return TypeRef(name=type_name, nullable=False)


def _canonical_field(
    field: SmithyField,
    *,
    type_key: str,
    namespace: Optional[str],
    structure_names: Set[str],
    enum_names: Set[str],
    list_names: Set[str],
    map_names: Set[str],
    list_types: Dict[str, Type],
    map_types: Dict[str, Type],
) -> CanonicalField:
    ref = _type_ref(
        field.type_name,
        namespace=namespace,
        structure_names=structure_names,
        enum_names=enum_names,
        list_names=list_names,
        map_names=map_names,
        list_types=list_types,
        map_types=map_types,
    )
    extras: Dict[str, Any] = {}
    if field.traits:
        extras["smithy_traits"] = list(field.traits)
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=TypeRef(
            name=ref.name,
            item=ref.item,
            nullable=not field.required,
            extras=ref.extras,
        ),
        extras=extras,
    )


class SmithyNormalizer(Normalizer, register=True):
    """Normalize a parsed Smithy document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, SmithyDocument):
            raise ValueError(
                "Smithy source must be a SmithyDocument (see app.smithy_parser.parse_smithy)"
            )

        namespace = source.namespace
        structure_names = {shape.name for shape in source.structures}
        enum_names = {enum.name for enum in source.enums}
        list_names = {lst.name for lst in source.lists}
        map_names = {mp.name for mp in source.maps}
        list_types: Dict[str, Type] = {}
        map_types: Dict[str, Type] = {}
        types: List[Type] = []

        for enum in source.enums:
            type_key = _type_key(enum.name, namespace)
            values = [
                EnumValue(
                    key=Keys.enum_value(type_key, value),
                    name=value,
                    value=index,
                )
                for index, value in enumerate(enum.values)
            ]
            types.append(
                Type(
                    key=type_key,
                    name=enum.name,
                    kind=TypeKind.ENUM,
                    namespace=namespace,
                    description=enum.documentation,
                    enum_values=values,
                    extras={"smithy_kind": "enum"},
                )
            )

        for lst in source.lists:
            type_key = _type_key(lst.name, namespace)
            member_ref = _type_ref(
                lst.member,
                namespace=namespace,
                structure_names=structure_names,
                enum_names=enum_names,
                list_names=list_names,
                map_names=map_names,
                list_types=list_types,
                map_types=map_types,
            )
            list_type = Type(
                key=type_key,
                name=lst.name,
                kind=TypeKind.ALIAS,
                namespace=namespace,
                description=lst.documentation,
                aliased=TypeRef(item=member_ref, nullable=False),
                extras={"smithy_kind": "list"},
            )
            list_types[lst.name] = list_type
            types.append(list_type)

        for mp in source.maps:
            type_key = _type_key(mp.name, namespace)
            map_type = Type(
                key=type_key,
                name=mp.name,
                kind=TypeKind.MAP,
                namespace=namespace,
                description=mp.documentation,
                key_type=_type_ref(
                    mp.key,
                    namespace=namespace,
                    structure_names=structure_names,
                    enum_names=enum_names,
                    list_names=list_names,
                    map_names=map_names,
                    list_types=list_types,
                    map_types=map_types,
                ),
                value_type=_type_ref(
                    mp.value,
                    namespace=namespace,
                    structure_names=structure_names,
                    enum_names=enum_names,
                    list_names=list_names,
                    map_names=map_names,
                    list_types=list_types,
                    map_types=map_types,
                ),
                extras={"smithy_kind": "map"},
            )
            map_types[mp.name] = map_type
            types.append(map_type)

        for shape in source.structures:
            type_key = _type_key(shape.name, namespace)
            kind = TypeKind.UNION if shape.kind == "union" else TypeKind.RECORD
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    namespace=namespace,
                    structure_names=structure_names,
                    enum_names=enum_names,
                    list_names=list_names,
                    map_names=map_names,
                    list_types=list_types,
                    map_types=map_types,
                )
                for field in shape.fields
            ]
            types.append(
                Type(
                    key=type_key,
                    name=shape.name,
                    kind=kind,
                    namespace=namespace,
                    description=shape.documentation,
                    fields=fields,
                    extras={"smithy_kind": shape.kind},
                )
            )

        operations_by_name = {op.name: op for op in source.operations}
        services: List[Service] = []
        for svc in source.services:
            service_key = _type_key(svc.name, namespace)
            service_operations: List[Operation] = []
            for op_name in svc.operations:
                op = operations_by_name.get(op_name)
                if op is None:
                    continue
                op_key = Keys.operation_rpc(service_key, op.name)
                messages: List[Message] = []
                if op.input_type:
                    messages.append(
                        Message(
                            key=Keys.request_message(op_key),
                            role=MessageRole.REQUEST,
                            payload=_type_ref(
                                op.input_type,
                                namespace=namespace,
                                structure_names=structure_names,
                                enum_names=enum_names,
                                list_names=list_names,
                                map_names=map_names,
                                list_types=list_types,
                                map_types=map_types,
                            ),
                            required=True,
                        )
                    )
                if op.output_type:
                    messages.append(
                        Message(
                            key=f"{op_key}#response",
                            role=MessageRole.RESPONSE,
                            payload=_type_ref(
                                op.output_type,
                                namespace=namespace,
                                structure_names=structure_names,
                                enum_names=enum_names,
                                list_names=list_names,
                                map_names=map_names,
                                list_types=list_types,
                                map_types=map_types,
                            ),
                        )
                    )
                service_operations.append(
                    Operation(
                        key=op_key,
                        name=op.name,
                        kind=OperationKind.REQUEST_RESPONSE,
                        streaming=StreamingMode.NONE,
                        description=op.documentation,
                        messages=messages,
                    )
                )
            services.append(
                Service(
                    key=service_key,
                    name=svc.name,
                    description=svc.documentation,
                    operations=service_operations,
                    extras={
                        "smithy_version": svc.version,
                        "smithy_operations": list(svc.operations),
                    },
                )
            )

        title = (
            source.services[0].name
            if source.services
            else (namespace or "Smithy API")
        )
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="smithy",
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            services=services,
            types=types,
            raw={"smithy": source.raw} if include_raw else None,
            extras={
                "smithy_version": source.version,
                "smithy_namespace": namespace,
            },
        )
        return normalize_ordering(api)
