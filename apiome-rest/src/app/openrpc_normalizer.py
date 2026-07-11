"""OpenRPC → canonical model normalizer — MFI-18.2.

Maps a parsed :class:`~app.openrpc_parser.OpenRpcDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`.
"""

from __future__ import annotations

from typing import Any, List

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    StreamingMode,
)
from .normalizer import Keys, Normalizer, SchemaCoercer, normalize_ordering
from .openrpc_parser import OpenRpcDocument, OpenRpcMethod

__all__ = ["OpenRpcNormalizer"]

_FORMAT_KEY = "openrpc"
_REF_PREFIX = "#/components/schemas/"


def _method_messages(
    method: OpenRpcMethod,
    *,
    op_key: str,
    coercer: SchemaCoercer,
) -> List[Message]:
    messages: List[Message] = []
    if method.params:
        payload = (
            coercer.type_ref(method.params[0].schema, required=method.params[0].required)
            if len(method.params) == 1
            else None
        )
        messages.append(
            Message(
                key=Keys.request_message(op_key),
                role=MessageRole.REQUEST,
                payload=payload,
                required=True,
                extras={
                    "openrpc_params": [
                        {
                            "name": param.name,
                            "required": param.required,
                            "schema": param.schema,
                            "description": param.description,
                        }
                        for param in method.params
                    ]
                },
            )
        )
    if method.result_schema is not None:
        messages.append(
            Message(
                key=f"{op_key}#response",
                role=MessageRole.RESPONSE,
                name=method.result_name,
                payload=coercer.type_ref(method.result_schema, required=True),
            )
        )
    return messages


class OpenRpcNormalizer(Normalizer, register=True):
    """Normalize a parsed OpenRPC document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, OpenRpcDocument):
            raise ValueError(
                "OpenRPC source must be an OpenRpcDocument (see app.openrpc_parser.parse_openrpc)"
            )

        coercer = SchemaCoercer(components=source.schemas, ref_prefix=_REF_PREFIX)
        service_key = Keys.type(source.title, None)
        operations: List[Operation] = []
        for method in source.methods:
            op_key = Keys.operation_rpc(service_key, method.name)
            operations.append(
                Operation(
                    key=op_key,
                    name=method.name,
                    kind=OperationKind.REQUEST_RESPONSE,
                    streaming=StreamingMode.NONE,
                    description=method.description or method.summary,
                    messages=_method_messages(method, op_key=op_key, coercer=coercer),
                    extras={
                        "openrpc_summary": method.summary,
                        "openrpc_result_name": method.result_name,
                    },
                )
            )

        services = [Service(key=service_key, name=source.title, operations=operations)]
        servers = [
            Server(url=server.url, description=server.description or server.name)
            for server in source.servers
        ]

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="jsonrpc",
            identity=ApiIdentity(name=source.title),
            title=source.title,
            description=source.description,
            version=source.version,
            servers=servers,
            services=services,
            types=coercer.named_types_from_components(),
            raw={"openrpc": source.raw} if include_raw else None,
            extras={
                "openrpc_version": source.openrpc_version,
            },
        )
        return normalize_ordering(api)
