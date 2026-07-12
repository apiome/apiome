"""z/OS Connect → canonical model normalizer — MFI-22.9.

Maps a parsed :class:`~app.zosconnect_parser.ZosConnectDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .zosconnect_parser import (
    ZosConnectDocument,
    ZosConnectOperation,
    ZosConnectPathParameter,
    operation_template,
)

__all__ = ["ZosConnectNormalizer"]

_FORMAT_KEY = "zosconnect"

_TYPE_MAP: Dict[str, str] = {
    "string": "string",
    "integer": "i32",
    "int": "i32",
    "number": "double",
    "boolean": "bool",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref_from_expr(type_expr: str) -> TypeRef:
    return TypeRef(name=_TYPE_MAP.get(type_expr.lower(), "string"))


def _structure_type(
    structure_name: str,
    *,
    namespace: Optional[str],
    path_parameters: tuple[ZosConnectPathParameter, ...],
) -> Type:
    type_key = _type_key(structure_name, namespace)
    fields = tuple(
        CanonicalField(
            key=Keys.field(type_key, param.field),
            name=param.field,
            type=_type_ref_from_expr(param.type_expr),
            field_number=index,
            description=f"Path parameter `{param.name}`",
            extras={"zosconnect_path_parameter": param.name},
        )
        for index, param in enumerate(path_parameters, start=1)
    )
    return Type(
        key=type_key,
        name=structure_name,
        kind=TypeKind.RECORD,
        namespace=namespace,
        fields=fields,
        extras={"zosconnect_kind": "structure"},
    )


def _collect_structure_types(
    operations: tuple[ZosConnectOperation, ...],
    *,
    namespace: Optional[str],
) -> List[Type]:
    types: List[Type] = []
    seen: Set[str] = set()
    for operation in operations:
        for structure_name, params in (
            (operation.request_structure, operation.path_parameters),
            (operation.response_structure, ()),
        ):
            if not structure_name or structure_name in seen:
                continue
            seen.add(structure_name)
            types.append(
                _structure_type(
                    structure_name,
                    namespace=namespace,
                    path_parameters=params,
                )
            )
    return types


class ZosConnectNormalizer(Normalizer, register=True):
    """Normalize a parsed z/OS Connect document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, ZosConnectDocument):
            raise ValueError(
                "z/OS Connect source must be a ZosConnectDocument "
                "(see app.zosconnect_parser.parse_zosconnect)"
            )

        namespace = source.descriptor.name
        structure_types = _collect_structure_types(source.operations, namespace=namespace)
        operations: List[Operation] = []

        for endpoint in source.operations:
            op_key = Keys.operation_http(endpoint.method, endpoint.path)
            messages: List[Message] = []
            if endpoint.request_structure:
                messages.append(
                    Message(
                        key=Keys.request_message(op_key),
                        role=MessageRole.REQUEST,
                        payload=TypeRef(
                            name=_type_key(endpoint.request_structure, namespace),
                            nullable=False,
                        ),
                    )
                )
            if endpoint.response_structure:
                messages.append(
                    Message(
                        key=Keys.response_message(op_key, 200),
                        role=MessageRole.RESPONSE,
                        payload=TypeRef(
                            name=_type_key(endpoint.response_structure, namespace),
                            nullable=False,
                        ),
                        extras={"http_status": 200},
                    )
                )
            operations.append(
                Operation(
                    key=op_key,
                    name=endpoint.operation_id,
                    kind=OperationKind.REQUEST_RESPONSE,
                    streaming=StreamingMode.NONE,
                    http_method=endpoint.method,
                    http_path=endpoint.path,
                    parameters=[
                        Parameter(
                            key=Keys.parameter(op_key, "path", param.name),
                            name=param.name,
                            location=ParameterLocation.PATH,
                            required=True,
                            type=_type_ref_from_expr(param.type_expr),
                            extras={
                                "zosconnect_field": param.field,
                                "zosconnect_type": param.type_expr,
                            },
                        )
                        for param in endpoint.path_parameters
                    ],
                    messages=messages,
                    extras={
                        "zosconnect_request_structure": endpoint.request_structure,
                        "zosconnect_response_structure": endpoint.response_structure,
                        "zosconnect_program": endpoint.program,
                    },
                )
            )

        service_key = Keys.type(source.descriptor.name, namespace)
        services = [Service(key=service_key, name=source.descriptor.name, operations=operations)]
        servers: List[Server] = []
        if source.api.base_path:
            servers.append(Server(url=source.api.base_path, description="From z/OS Connect `api.basePath`"))

        title = source.api.title or source.descriptor.name
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="http",
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            version=source.descriptor.version,
            description=source.descriptor.description,
            servers=servers,
            services=services,
            types=structure_types,
            raw={"zosconnect": source.raw} if include_raw else None,
            extras={
                "zosconnect_kind": source.descriptor.kind,
                "zosconnect_descriptor": {
                    "name": source.descriptor.name,
                    "version": source.descriptor.version,
                    "description": source.descriptor.description,
                },
                "zosconnect_api": {
                    "title": source.api.title,
                    "specification": source.api.specification,
                    "basePath": source.api.base_path,
                },
                "zosconnect_language": {
                    "type": source.language.type_expr,
                    "codepage": source.language.codepage,
                },
                "zosconnect_operations": [
                    operation_template(operation) for operation in source.operations
                ],
            },
        )
        return normalize_ordering(api)
