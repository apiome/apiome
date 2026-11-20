"""Structure-aware walk over an OpenAPI 3.x document — COA-2.1 (#7044).

An OpenAPI document is a tree of typed objects (Path Item, Operation, Parameter, Media Type,
Schema, …) whose *kind* decides what a key means: ``callbacks`` on an Operation is a construct,
while ``callbacks`` as a property name inside a schema's ``properties`` map is user data. This
module walks a parsed document and yields every object together with its kind and its RFC 6901
JSON Pointer, so callers can reason about constructs without re-deriving the grammar:

* :mod:`app.openapi_source_preservation` uses it to gate version-specific constructs and to
  upgrade OpenAPI 3.0 schemas when a preserved source object is written at 3.1 / 3.2;
* :mod:`app.openapi_construct_audit` uses it to find every occurrence of every construct in
  the construct matrix.

Only mapping nodes are yielded; data values (``example``, ``default``, ``enum``, ``const``,
extension values) are never descended into. The walk is depth-first, parents before children,
and reads a node's children *after* the caller has seen it — so a caller may rewrite a node in
place (for example the 3.0 → 3.1 schema upgrade) and the walk continues into the rewritten
children. Everything here is pure; nothing is mutated by the walker itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

__all__ = [
    "HTTP_METHODS",
    "Node",
    "escape_pointer_token",
    "is_missing",
    "join_pointer",
    "node_pointers",
    "resolve_pointer",
    "walk_document",
    "walk_operation",
]

#: The fixed HTTP-method keys of a Path Item Object (``query`` is new in OpenAPI 3.2).
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace", "query")

# Components Object section → the kind of object each entry is.
_COMPONENT_SECTIONS: Dict[str, str] = {
    "schemas": "schema",
    "responses": "response",
    "parameters": "parameter",
    "examples": "example",
    "requestBodies": "request_body",
    "headers": "header",
    "securitySchemes": "security_scheme",
    "links": "link",
    "callbacks": "callback",
    "pathItems": "path_item",
    "mediaTypes": "media_type",
}

# Schema keywords whose value is a map of name → subschema.
_SCHEMA_MAP_KEYWORDS = (
    "properties",
    "patternProperties",
    "$defs",
    "definitions",
    "dependentSchemas",
)

# Schema keywords whose value is a single subschema.
_SCHEMA_SINGLE_KEYWORDS = (
    "items",
    "additionalProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
    "not",
    "if",
    "then",
    "else",
    "contains",
    "propertyNames",
    "contentSchema",
    "additionalItems",
)

# Schema keywords whose value is a list of subschemas.
_SCHEMA_LIST_KEYWORDS = ("allOf", "anyOf", "oneOf", "prefixItems")


@dataclass(frozen=True)
class Node:
    """One object of an OpenAPI document, as the walk sees it.

    Attributes:
        pointer: RFC 6901 JSON Pointer to the object (``""`` for the root).
        kind: The OpenAPI object kind: ``root``, ``info``, ``license``, ``contact``,
            ``server``, ``server_variable``, ``tag``, ``external_docs``, ``components``,
            ``path_item``, ``operation``, ``parameter``, ``request_body``, ``response``,
            ``media_type``, ``header``, ``encoding``, ``link``, ``callback``, ``example``,
            ``security_scheme``, ``oauth_flow`` or ``schema``.
        value: The object itself (the live mapping inside the document, not a copy).
        name: The key the object sits under in its parent map (a media-type name, a status
            code, a component name), or ``None`` for list members and fixed fields.
    """

    pointer: str
    kind: str
    value: Dict[str, Any]
    name: Optional[str] = None


def escape_pointer_token(token: str) -> str:
    """Escape one reference token per RFC 6901 (``~`` → ``~0``, ``/`` → ``~1``)."""
    return token.replace("~", "~0").replace("/", "~1")


def join_pointer(base: str, *tokens: Any) -> str:
    """Append escaped reference tokens to a JSON Pointer.

    Args:
        base: An existing pointer (``""`` for the document root).
        *tokens: Keys or list indices to append; each is stringified and escaped.

    Returns:
        The extended pointer, e.g. ``join_pointer("", "paths", "/pets")`` → ``/paths/~1pets``.
    """
    return base + "".join("/" + escape_pointer_token(str(token)) for token in tokens)


_MISSING = object()


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Return the value at ``pointer`` in ``document``, or a private sentinel when absent.

    Test the result with :func:`is_missing` — ``None`` is a legitimate JSON value.

    Args:
        document: A parsed JSON/YAML value.
        pointer: An RFC 6901 pointer (``""`` is the whole document).

    Returns:
        The value, or the module's ``_MISSING`` sentinel when any segment does not resolve.
    """
    if pointer == "":
        return document
    node = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return _MISSING
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return _MISSING
            node = node[int(token)]
        else:
            return _MISSING
    return node


def is_missing(value: Any) -> bool:
    """Whether ``value`` is the sentinel :func:`resolve_pointer` returns for an absent pointer."""
    return value is _MISSING



def walk_document(document: Dict[str, Any]) -> Iterator[Node]:
    """Yield every object of an OpenAPI 3.x document with its kind and pointer.

    Args:
        document: A parsed OpenAPI 3.0 / 3.1 / 3.2 document.

    Yields:
        :class:`Node` values, root first, parents before children.
    """
    if not isinstance(document, dict):
        return
    yield Node("", "root", document)

    info = document.get("info")
    if isinstance(info, dict):
        yield Node("/info", "info", info)
        for key in ("license", "contact"):
            if isinstance(info.get(key), dict):
                yield Node(f"/info/{key}", key, info[key])

    yield from _walk_servers(document.get("servers"), "/servers")
    yield from _walk_list(document.get("tags"), "/tags", _walk_tag)
    yield from _walk_external_docs(document, "")

    yield from _walk_path_map(document.get("paths"), "/paths")
    yield from _walk_path_map(document.get("webhooks"), "/webhooks")

    components = document.get("components")
    if isinstance(components, dict):
        yield Node("/components", "components", components)
        for section, kind in _COMPONENT_SECTIONS.items():
            entries = components.get(section)
            if not isinstance(entries, dict):
                continue
            for name, entry in entries.items():
                pointer = join_pointer("/components", section, name)
                yield from _walk_kind(kind, entry, pointer, name)


def walk_operation(operation: Dict[str, Any], pointer: str) -> Iterator[Node]:
    """Yield an Operation Object and everything inside it (parameters, bodies, callbacks…).

    Args:
        operation: An Operation Object.
        pointer: The operation's pointer in its document.
    """
    yield from _walk_operation(operation, pointer, None)


# --- per-kind walkers ------------------------------------------------------------------


def _walk_kind(kind: str, value: Any, pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Dispatch to the walker for ``kind`` (only mapping values are walked)."""
    if not isinstance(value, dict):
        return
    walker = _WALKERS.get(kind)
    if walker is None:
        yield Node(pointer, kind, value, name)
        return
    yield from walker(value, pointer, name)


def _walk_list(values: Any, pointer: str, walker: Any) -> Iterator[Node]:
    """Walk each mapping member of a list with ``walker``."""
    if not isinstance(values, list):
        return
    for index, value in enumerate(values):
        if isinstance(value, dict):
            yield from walker(value, join_pointer(pointer, index), None)


def _walk_map(values: Any, pointer: str, kind: str) -> Iterator[Node]:
    """Walk each mapping value of a name → object map as ``kind``."""
    if not isinstance(values, dict):
        return
    for name, value in values.items():
        yield from _walk_kind(kind, value, join_pointer(pointer, name), str(name))


def _walk_external_docs(parent: Dict[str, Any], pointer: str) -> Iterator[Node]:
    """Yield a parent's ``externalDocs`` object, when present."""
    if isinstance(parent.get("externalDocs"), dict):
        yield Node(join_pointer(pointer, "externalDocs"), "external_docs", parent["externalDocs"])


def _walk_servers(servers: Any, pointer: str) -> Iterator[Node]:
    """Yield each Server Object and its variables."""
    if not isinstance(servers, list):
        return
    for index, server in enumerate(servers):
        if not isinstance(server, dict):
            continue
        server_ptr = join_pointer(pointer, index)
        yield Node(server_ptr, "server", server)
        yield from _walk_map(server.get("variables"), join_pointer(server_ptr, "variables"), "server_variable")


def _walk_tag(tag: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Tag Object and its ``externalDocs``."""
    yield Node(pointer, "tag", tag, name)
    yield from _walk_external_docs(tag, pointer)


def _walk_path_map(paths: Any, pointer: str) -> Iterator[Node]:
    """Yield every Path Item of a ``paths`` / ``webhooks`` map."""
    yield from _walk_map(paths, pointer, "path_item")


def _walk_path_item(item: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Path Item, its shared parameters and servers, and each of its operations."""
    yield Node(pointer, "path_item", item, name)
    yield from _walk_servers(item.get("servers"), join_pointer(pointer, "servers"))
    yield from _walk_list(item.get("parameters"), join_pointer(pointer, "parameters"), _walk_parameter)
    for method in HTTP_METHODS:
        if isinstance(item.get(method), dict):
            yield from _walk_operation(item[method], join_pointer(pointer, method), method)
    additional = item.get("additionalOperations")
    if isinstance(additional, dict):
        for method, operation in additional.items():
            if isinstance(operation, dict):
                yield from _walk_operation(
                    operation, join_pointer(pointer, "additionalOperations", method), str(method)
                )


def _walk_operation(operation: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield an Operation and its parameters, body, responses, callbacks and servers."""
    yield Node(pointer, "operation", operation, name)
    yield from _walk_external_docs(operation, pointer)
    yield from _walk_servers(operation.get("servers"), join_pointer(pointer, "servers"))
    yield from _walk_list(
        operation.get("parameters"), join_pointer(pointer, "parameters"), _walk_parameter
    )
    yield from _walk_kind(
        "request_body", operation.get("requestBody"), join_pointer(pointer, "requestBody"), None
    )
    yield from _walk_map(operation.get("responses"), join_pointer(pointer, "responses"), "response")
    yield from _walk_map(operation.get("callbacks"), join_pointer(pointer, "callbacks"), "callback")


def _walk_callback(callback: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Callback Object (expression → Path Item map) and its path items."""
    yield Node(pointer, "callback", callback, name)
    for expression, item in callback.items():
        if isinstance(item, dict) and not str(expression).startswith("x-") and expression != "$ref":
            yield from _walk_path_item(item, join_pointer(pointer, expression), str(expression))


def _walk_parameter(parameter: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Parameter and its schema, content and examples."""
    yield Node(pointer, "parameter", parameter, name)
    yield from _walk_schema_at(parameter, "schema", pointer)
    yield from _walk_map(parameter.get("content"), join_pointer(pointer, "content"), "media_type")
    yield from _walk_map(parameter.get("examples"), join_pointer(pointer, "examples"), "example")


def _walk_header(header: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Header and its schema, content and examples."""
    yield Node(pointer, "header", header, name)
    yield from _walk_schema_at(header, "schema", pointer)
    yield from _walk_map(header.get("content"), join_pointer(pointer, "content"), "media_type")
    yield from _walk_map(header.get("examples"), join_pointer(pointer, "examples"), "example")


def _walk_request_body(body: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Request Body and its media types."""
    yield Node(pointer, "request_body", body, name)
    yield from _walk_map(body.get("content"), join_pointer(pointer, "content"), "media_type")


def _walk_response(response: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Response and its headers, media types and links."""
    yield Node(pointer, "response", response, name)
    yield from _walk_map(response.get("headers"), join_pointer(pointer, "headers"), "header")
    yield from _walk_map(response.get("content"), join_pointer(pointer, "content"), "media_type")
    yield from _walk_map(response.get("links"), join_pointer(pointer, "links"), "link")


def _walk_media_type(media: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Media Type and its schema / itemSchema, examples and encodings."""
    yield Node(pointer, "media_type", media, name)
    yield from _walk_schema_at(media, "schema", pointer)
    yield from _walk_schema_at(media, "itemSchema", pointer)
    yield from _walk_map(media.get("examples"), join_pointer(pointer, "examples"), "example")
    yield from _walk_encodings(media, pointer)


def _walk_encoding(encoding: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield an Encoding Object, its headers, and its nested (3.2) encodings."""
    yield Node(pointer, "encoding", encoding, name)
    yield from _walk_map(encoding.get("headers"), join_pointer(pointer, "headers"), "header")
    yield from _walk_encodings(encoding, pointer)


def _walk_encodings(parent: Dict[str, Any], pointer: str) -> Iterator[Node]:
    """Yield ``encoding`` (map), ``prefixEncoding`` (list) and ``itemEncoding`` (single)."""
    yield from _walk_map(parent.get("encoding"), join_pointer(pointer, "encoding"), "encoding")
    yield from _walk_list(
        parent.get("prefixEncoding"), join_pointer(pointer, "prefixEncoding"), _walk_encoding
    )
    yield from _walk_kind(
        "encoding", parent.get("itemEncoding"), join_pointer(pointer, "itemEncoding"), None
    )


def _walk_security_scheme(
    scheme: Dict[str, Any], pointer: str, name: Optional[str]
) -> Iterator[Node]:
    """Yield a Security Scheme and each of its OAuth flows."""
    yield Node(pointer, "security_scheme", scheme, name)
    yield from _walk_map(scheme.get("flows"), join_pointer(pointer, "flows"), "oauth_flow")


def _walk_schema_at(parent: Dict[str, Any], key: str, pointer: str) -> Iterator[Node]:
    """Walk ``parent[key]`` as a schema when it is a mapping."""
    if isinstance(parent.get(key), dict):
        yield from _walk_schema(parent[key], join_pointer(pointer, key), None)


def _walk_schema(schema: Dict[str, Any], pointer: str, name: Optional[str]) -> Iterator[Node]:
    """Yield a Schema Object and every subschema it nests (JSON Schema applicators).

    Boolean schemas (``true`` / ``false``) are values, not objects, and are not yielded.
    """
    yield Node(pointer, "schema", schema, name)
    for keyword in _SCHEMA_MAP_KEYWORDS:
        members = schema.get(keyword)
        if isinstance(members, dict):
            for member, subschema in members.items():
                if isinstance(subschema, dict):
                    yield from _walk_schema(
                        subschema, join_pointer(pointer, keyword, member), str(member)
                    )
    for keyword in _SCHEMA_SINGLE_KEYWORDS:
        subschema = schema.get(keyword)
        if isinstance(subschema, dict):
            yield from _walk_schema(subschema, join_pointer(pointer, keyword), None)
        elif keyword == "items" and isinstance(subschema, list):
            yield from _walk_schema_list(subschema, join_pointer(pointer, keyword))
    for keyword in _SCHEMA_LIST_KEYWORDS:
        yield from _walk_schema_list(schema.get(keyword), join_pointer(pointer, keyword))


def _walk_schema_list(values: Any, pointer: str) -> Iterator[Node]:
    """Walk each mapping member of a list of subschemas."""
    if not isinstance(values, list):
        return
    for index, subschema in enumerate(values):
        if isinstance(subschema, dict):
            yield from _walk_schema(subschema, join_pointer(pointer, index), None)


_WALKERS = {
    "path_item": _walk_path_item,
    "operation": _walk_operation,
    "callback": _walk_callback,
    "parameter": _walk_parameter,
    "header": _walk_header,
    "request_body": _walk_request_body,
    "response": _walk_response,
    "media_type": _walk_media_type,
    "encoding": _walk_encoding,
    "security_scheme": _walk_security_scheme,
    "schema": _walk_schema,
}


def node_pointers(document: Dict[str, Any]) -> List[str]:
    """Return the pointer of every object :func:`walk_document` yields (handy in tests)."""
    return [node.pointer for node in walk_document(document)]

