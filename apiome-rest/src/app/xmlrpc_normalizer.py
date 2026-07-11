"""XML-RPC → canonical model normalizer.

Maps a parsed :class:`~app.xmlrpc_parser.XmlRpcDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
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
from .xmlrpc_parser import XmlRpcDocument, XmlRpcValue

__all__ = ["XmlRpcNormalizer"]

_FORMAT_KEY = "xmlrpc"
_REF_PREFIX = "#/components/schemas/"


def _pascal_case(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def _scalar_schema(value: XmlRpcValue) -> Dict[str, Any]:
    if value.kind == "int":
        return {"type": "integer"}
    if value.kind == "boolean":
        return {"type": "boolean"}
    if value.kind == "double":
        return {"type": "number"}
    if value.kind == "base64":
        return {"type": "string", "contentEncoding": "base64"}
    if value.kind == "dateTime.iso8601":
        return {"type": "string", "format": "date-time"}
    if value.kind == "nil":
        return {"type": "null"}
    return {"type": "string"}


class _StructCollector:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self.types: Dict[str, Type] = {}

    def absorb(self, value: XmlRpcValue, *, context: str) -> Tuple[Dict[str, Any], TypeRef]:
        if value.kind == "struct":
            type_name = f"{self._prefix}{context}"
            type_key = Keys.type(type_name, None)
            if type_key not in self.types:
                fields: List[CanonicalField] = []
                for index, member in enumerate(value.members):
                    schema, ref = self.absorb(member.value, context=f"{context}_{member.name}")
                    fields.append(
                        CanonicalField(
                            key=Keys.field(type_key, member.name),
                            name=member.name,
                            type=ref,
                            field_number=index + 1,
                        )
                    )
                self.types[type_key] = Type(
                    key=type_key,
                    name=type_name,
                    kind=TypeKind.RECORD,
                    fields=fields,
                    extras={
                        "xmlrpc_kind": "struct",
                        "xmlrpc_samples": {
                            member.name: _sample_literal(member.value)
                            for member in value.members
                        },
                    },
                )
            return (
                {"$ref": f"{_REF_PREFIX}{type_name}"},
                TypeRef(name=type_key, nullable=False),
            )

        if value.kind == "array":
            item_schema: Dict[str, Any] = {"type": "string"}
            item_ref = TypeRef(name="string", nullable=False)
            if value.items:
                item_schema, item_ref = self.absorb(value.items[0], context=f"{context}Item")
            return (
                {"type": "array", "items": item_schema},
                TypeRef(item=item_ref, nullable=False),
            )

        return _scalar_schema(value), _scalar_type_ref(value)


def _scalar_type_ref(value: XmlRpcValue) -> TypeRef:
    mapping = {
        "int": "integer",
        "boolean": "bool",
        "double": "double",
        "base64": "bytes",
        "dateTime.iso8601": "string",
        "nil": "null",
    }
    return TypeRef(name=mapping.get(value.kind, "string"), nullable=False)


def _sample_literal(value: XmlRpcValue) -> Any:
    if value.kind == "struct":
        return {
            member.name: _sample_literal(member.value)
            for member in value.members
        }
    if value.kind == "array":
        return [_sample_literal(item) for item in value.items]
    if value.kind == "boolean":
        return value.text in {"1", "true", "True"}
    if value.kind == "int":
        try:
            return int(value.text or "0")
        except ValueError:
            return 0
    if value.kind == "double":
        try:
            return float(value.text or "0")
        except ValueError:
            return 0.0
    if value.kind == "nil":
        return None
    return value.text or ""


def _method_messages(
    doc: XmlRpcDocument,
    *,
    op_key: str,
    collector: _StructCollector,
) -> List[Message]:
    messages: List[Message] = []
    if doc.kind == "methodCall":
        params: List[Dict[str, Any]] = []
        for index, value in enumerate(doc.params):
            schema, _ref = collector.absorb(value, context=f"Param{index + 1}")
            params.append(
                {
                    "index": index,
                    "name": f"param{index}",
                    "required": True,
                    "schema": schema,
                    "sample": _sample_literal(value),
                }
            )
        messages.append(
            Message(
                key=Keys.request_message(op_key),
                role=MessageRole.REQUEST,
                required=True,
                extras={"xmlrpc_params": params},
            )
        )
    elif doc.kind == "methodResponse" and doc.params:
        schema, payload = collector.absorb(doc.params[0], context="Response")
        messages.append(
            Message(
                key=f"{op_key}#response",
                role=MessageRole.RESPONSE,
                name="result",
                payload=payload,
                required=True,
                extras={
                    "xmlrpc_result_schema": schema,
                    "xmlrpc_sample": _sample_literal(doc.params[0]),
                },
            )
        )
    return messages


class XmlRpcNormalizer(Normalizer, register=True):
    """Normalize a parsed XML-RPC document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, XmlRpcDocument):
            raise ValueError(
                "XML-RPC source must be an XmlRpcDocument (see app.xmlrpc_parser.parse_xmlrpc)"
            )

        if source.kind == "fault":
            title = "XML-RPC Fault"
            method_name = "fault"
        elif source.method_name:
            title = source.method_name
            method_name = source.method_name
        else:
            title = "XML-RPC Response"
            method_name = "response"

        prefix = _pascal_case(method_name)
        collector = _StructCollector(prefix)
        service_key = Keys.type(title, None)
        op_key = Keys.operation_rpc(service_key, method_name)
        operation = Operation(
            key=op_key,
            name=method_name,
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            messages=_method_messages(source, op_key=op_key, collector=collector),
            extras={
                "xmlrpc_kind": source.kind,
                "xmlrpc_fault_code": source.fault_code,
                "xmlrpc_fault_string": source.fault_string,
            },
        )

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="xmlrpc",
            identity=ApiIdentity(name=title),
            title=title,
            services=[Service(key=service_key, name=title, operations=[operation])],
            types=list(collector.types.values()),
            raw={"xmlrpc": source.raw} if include_raw else None,
            extras={"xmlrpc_kind": source.kind},
        )
        return normalize_ordering(api)
