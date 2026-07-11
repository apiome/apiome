"""OpenRPC parser — MFI-18.1.

Parses OpenRPC JSON-RPC service descriptions into a typed :class:`OpenRpcDocument`
AST. Syntax errors surface as :class:`OpenRpcParseError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from .import_ingestion import IngestionError, parse_document

__all__ = [
    "OpenRpcParseError",
    "OpenRpcParam",
    "OpenRpcMethod",
    "OpenRpcServer",
    "OpenRpcDocument",
    "is_openrpc",
    "is_openrpc_document",
    "parse_openrpc",
]

_API_MARKERS = ("openapi", "swagger", "asyncapi", "arazzo")


class OpenRpcParseError(ValueError):
    """Raised when OpenRPC text cannot be parsed."""


@dataclass(frozen=True)
class OpenRpcParam:
    name: str
    required: bool
    schema: Dict[str, Any]
    description: Optional[str] = None


@dataclass(frozen=True)
class OpenRpcMethod:
    name: str
    summary: Optional[str]
    description: Optional[str]
    params: Tuple[OpenRpcParam, ...]
    result_name: Optional[str]
    result_schema: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class OpenRpcServer:
    name: Optional[str]
    url: str
    description: Optional[str] = None


@dataclass(frozen=True)
class OpenRpcDocument:
    openrpc_version: str
    title: str
    version: Optional[str]
    description: Optional[str]
    servers: Tuple[OpenRpcServer, ...]
    methods: Tuple[OpenRpcMethod, ...]
    schemas: Dict[str, Any]
    raw: str


def _is_openrpc_mapping(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    if any(marker in document for marker in _API_MARKERS):
        return False
    version = document.get("openrpc")
    return isinstance(version, str) and bool(version.strip())


def is_openrpc_document(document: Any) -> bool:
    """Return ``True`` when a parsed mapping looks like an OpenRPC document."""
    return _is_openrpc_mapping(document)


def is_openrpc(content: str) -> bool:
    """Return ``True`` when ``content`` looks like an OpenRPC document."""
    if not content or not isinstance(content, str):
        return False
    if not content.strip():
        return False
    try:
        document = parse_document(content)
    except IngestionError:
        return False
    return _is_openrpc_mapping(document)


def _parse_params(raw_params: Any) -> Tuple[OpenRpcParam, ...]:
    if not isinstance(raw_params, list):
        return ()
    params: list[OpenRpcParam] = []
    for entry in raw_params:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        schema = entry.get("schema")
        if not isinstance(schema, dict):
            schema = {}
        required = entry.get("required") is True
        description = entry.get("description")
        params.append(
            OpenRpcParam(
                name=name.strip(),
                required=required,
                schema=schema,
                description=description if isinstance(description, str) else None,
            )
        )
    return tuple(params)


def _parse_methods(raw_methods: Any) -> Tuple[OpenRpcMethod, ...]:
    if not isinstance(raw_methods, list):
        return ()
    methods: list[OpenRpcMethod] = []
    for entry in raw_methods:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        result = entry.get("result")
        result_name: Optional[str] = None
        result_schema: Optional[Dict[str, Any]] = None
        if isinstance(result, dict):
            if isinstance(result.get("name"), str):
                result_name = result["name"]
            schema = result.get("schema")
            if isinstance(schema, dict):
                result_schema = schema
        methods.append(
            OpenRpcMethod(
                name=name.strip(),
                summary=entry.get("summary") if isinstance(entry.get("summary"), str) else None,
                description=entry.get("description") if isinstance(entry.get("description"), str) else None,
                params=_parse_params(entry.get("params")),
                result_name=result_name,
                result_schema=result_schema,
            )
        )
    return tuple(methods)


def _parse_servers(raw_servers: Any) -> Tuple[OpenRpcServer, ...]:
    if not isinstance(raw_servers, list):
        return ()
    servers: list[OpenRpcServer] = []
    for entry in raw_servers:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        servers.append(
            OpenRpcServer(
                name=entry.get("name") if isinstance(entry.get("name"), str) else None,
                url=url.strip(),
                description=entry.get("description") if isinstance(entry.get("description"), str) else None,
            )
        )
    return tuple(servers)


def parse_openrpc(content: str, *, source_label: Optional[str] = None) -> OpenRpcDocument:
    """Parse OpenRPC JSON into an :class:`OpenRpcDocument`."""
    if not content or not content.strip():
        raise OpenRpcParseError("Invalid or empty OpenRPC document")
    try:
        document = parse_document(content, source_label=source_label)
    except IngestionError as exc:
        raise OpenRpcParseError(str(exc)) from exc

    if not _is_openrpc_mapping(document):
        raise OpenRpcParseError("Content does not appear to be an OpenRPC document")

    info = document.get("info") or {}
    if not isinstance(info, dict):
        info = {}
    title = info.get("title")
    if not isinstance(title, str) or not title.strip():
        raise OpenRpcParseError("OpenRPC document is missing `info.title`")

    components = document.get("components") or {}
    schemas = components.get("schemas") if isinstance(components, dict) else {}
    if not isinstance(schemas, dict):
        schemas = {}
    methods = _parse_methods(document.get("methods"))
    if not methods and not schemas:
        label = f" ({source_label})" if source_label else ""
        raise OpenRpcParseError(f"No OpenRPC methods or component schemas found{label}")

    return OpenRpcDocument(
        openrpc_version=str(document.get("openrpc")).strip(),
        title=title.strip(),
        version=info.get("version") if isinstance(info.get("version"), str) else None,
        description=info.get("description") if isinstance(info.get("description"), str) else None,
        servers=_parse_servers(document.get("servers")),
        methods=methods,
        schemas=schemas,
        raw=content,
    )
