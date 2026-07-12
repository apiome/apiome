"""z/OS Connect descriptor parser — MFI-22.9.

Parses z/OS Connect API requester/provider JSON descriptors into a typed
:class:`ZosConnectDocument` AST. Syntax errors surface as :class:`ZosConnectParseError`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "ZosConnectParseError",
    "ZosConnectPathParameter",
    "ZosConnectOperation",
    "ZosConnectApiBlock",
    "ZosConnectLanguage",
    "ZosConnectDescriptor",
    "ZosConnectDocument",
    "is_zosconnect",
    "is_zosconnect_document",
    "parse_zosconnect",
    "operation_template",
]

_ALLOWED_METHODS = frozenset({"GET", "PUT", "POST", "DELETE", "PATCH", "HEAD", "OPTIONS"})


class ZosConnectParseError(ValueError):
    """Raised when z/OS Connect JSON cannot be parsed."""


@dataclass(frozen=True)
class ZosConnectPathParameter:
    name: str
    field: str
    type_expr: str


@dataclass(frozen=True)
class ZosConnectOperation:
    operation_id: str
    method: str
    path: str
    request_structure: Optional[str]
    response_structure: Optional[str]
    program: Optional[str]
    path_parameters: Tuple[ZosConnectPathParameter, ...]


@dataclass(frozen=True)
class ZosConnectApiBlock:
    title: Optional[str]
    specification: Optional[str]
    base_path: Optional[str]


@dataclass(frozen=True)
class ZosConnectLanguage:
    type_expr: Optional[str]
    codepage: Optional[str]


@dataclass(frozen=True)
class ZosConnectDescriptor:
    name: str
    version: Optional[str]
    description: Optional[str]
    kind: str


@dataclass(frozen=True)
class ZosConnectDocument:
    descriptor: ZosConnectDescriptor
    api: ZosConnectApiBlock
    language: ZosConnectLanguage
    operations: Tuple[ZosConnectOperation, ...]
    raw: str


def _document_dict(content: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ZosConnectParseError(f"Invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ZosConnectParseError("z/OS Connect document must be a JSON object")
    return parsed


def _descriptor_block(document: Mapping[str, Any]) -> Optional[tuple[str, Mapping[str, Any]]]:
    for key, kind in (("apiRequester", "requester"), ("apiProvider", "provider")):
        block = document.get(key)
        if isinstance(block, Mapping) and block.get("name"):
            return kind, block
    return None


def _looks_like_operation(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    method = str(value.get("method", "")).strip()
    path = str(value.get("path", "")).strip()
    return bool(method) and bool(path)


def _has_foreign_top_level_keys(document: Mapping[str, Any]) -> bool:
    foreign = (
        "openapi",
        "swagger",
        "asyncapi",
        "arazzo",
        "openrpc",
        "resourceType",
        "specversion",
        "mti",
        "dataElements",
        "data_elements",
    )
    return any(key in document for key in foreign)


def _is_zosconnect_mapping(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    if _has_foreign_top_level_keys(document):
        return False
    info = document.get("info")
    if isinstance(info, Mapping):
        schema = info.get("schema")
        if isinstance(schema, str) and "postman.com" in schema.lower():
            return False
    if _descriptor_block(document) is None:
        return False
    operations = document.get("operations")
    if not isinstance(operations, list) or not operations:
        return False
    return any(_looks_like_operation(operation) for operation in operations)


def is_zosconnect_document(document: Any) -> bool:
    """Return ``True`` when a parsed mapping looks like a z/OS Connect descriptor."""
    return _is_zosconnect_mapping(document)


def is_zosconnect(content: str) -> bool:
    """Return ``True`` when ``content`` looks like a z/OS Connect descriptor."""
    if not content or not isinstance(content, str):
        return False
    if not content.strip():
        return False
    try:
        document = _document_dict(content)
    except ZosConnectParseError:
        return False
    return _is_zosconnect_mapping(document)


def _parse_path_parameters(raw: Any) -> Tuple[ZosConnectPathParameter, ...]:
    if not isinstance(raw, list):
        return ()
    params: List[ZosConnectPathParameter] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", "")).strip()
        field = str(item.get("field", "")).strip()
        if not name or not field:
            continue
        params.append(
            ZosConnectPathParameter(
                name=name,
                field=field,
                type_expr=str(item.get("type", "string")),
            )
        )
    return tuple(params)


def _parse_operations(raw: Any) -> Tuple[ZosConnectOperation, ...]:
    if not isinstance(raw, list):
        raise ZosConnectParseError("z/OS Connect document must include an `operations` array")
    operations: List[ZosConnectOperation] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            continue
        if not _looks_like_operation(item):
            continue
        method = str(item.get("method", "GET")).upper()
        if method not in _ALLOWED_METHODS:
            raise ZosConnectParseError(f"Unsupported HTTP method {method!r}")
        operation_id = str(item.get("operationId") or item.get("operation_id") or f"operation{index}")
        operations.append(
            ZosConnectOperation(
                operation_id=operation_id,
                method=method,
                path=str(item.get("path", "")),
                request_structure=_optional_str(item.get("requestStructure")),
                response_structure=_optional_str(item.get("responseStructure")),
                program=_optional_str(item.get("program")),
                path_parameters=_parse_path_parameters(item.get("pathParameters")),
            )
        )
    if not operations:
        raise ZosConnectParseError("No z/OS Connect operations found")
    return tuple(operations)


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_zosconnect(content: str, *, source_label: Optional[str] = None) -> ZosConnectDocument:
    """Parse z/OS Connect JSON into a :class:`ZosConnectDocument`."""
    if not content or not content.strip():
        raise ZosConnectParseError("Invalid or empty z/OS Connect content")
    document = _document_dict(content)
    if not _is_zosconnect_mapping(document):
        label = f" ({source_label})" if source_label else ""
        raise ZosConnectParseError(f"Content does not appear to be a z/OS Connect descriptor{label}")

    descriptor_info = _descriptor_block(document)
    if descriptor_info is None:
        raise ZosConnectParseError("z/OS Connect document is missing `apiRequester` / `apiProvider`")
    kind, descriptor_block = descriptor_info

    api_block = document.get("api")
    if not isinstance(api_block, Mapping):
        raise ZosConnectParseError("z/OS Connect document is missing an `api` block")

    language_block = document.get("language")
    language = ZosConnectLanguage(
        type_expr=_optional_str(language_block.get("type")) if isinstance(language_block, Mapping) else None,
        codepage=_optional_str(language_block.get("codepage")) if isinstance(language_block, Mapping) else None,
    )

    descriptor = ZosConnectDescriptor(
        name=str(descriptor_block.get("name")),
        version=_optional_str(descriptor_block.get("version")),
        description=_optional_str(descriptor_block.get("description")),
        kind=kind,
    )
    api = ZosConnectApiBlock(
        title=_optional_str(api_block.get("title")),
        specification=_optional_str(api_block.get("specification")),
        base_path=_optional_str(api_block.get("basePath")),
    )
    operations = _parse_operations(document.get("operations"))
    return ZosConnectDocument(
        descriptor=descriptor,
        api=api,
        language=language,
        operations=operations,
        raw=content,
    )


def operation_template(operation: ZosConnectOperation) -> Dict[str, object]:
    """Serialize a :class:`ZosConnectOperation` for round-trip extras."""
    payload: Dict[str, object] = {
        "operationId": operation.operation_id,
        "method": operation.method,
        "path": operation.path,
        "requestStructure": operation.request_structure,
        "responseStructure": operation.response_structure,
        "pathParameters": [
            {"name": param.name, "field": param.field, "type": param.type_expr}
            for param in operation.path_parameters
        ],
    }
    if operation.program:
        payload["program"] = operation.program
    return payload
