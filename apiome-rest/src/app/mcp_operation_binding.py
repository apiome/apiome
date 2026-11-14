"""Tool arguments → HTTP: where each argument of an MCP tool goes — AGX-2.1 (#4533), SDK-4.5 (#4499).

The AGX-1.1 compiler (:func:`app.mcp_tool_mapping.compile_mcp_tools`) flattens an operation's path,
query and header parameters and its request body into one ``inputSchema`` object. Two runtimes run
that flattening backwards and must agree with it, and with each other, about where every argument
goes: the managed invocation proxy (``apiome_mcp.agent_request_builder``) and the generated MCP
server artifact (:mod:`app.mcp_server_generator`). :func:`binding_for` is that one answer:

* a path, query or header parameter becomes a :class:`ParameterBinding`, carrying the OpenAPI
  ``style`` / ``explode`` / ``allowReserved`` of the source document (or the Swagger 2.0
  ``collectionFormat``), with the OpenAPI defaults when the source says nothing;
* credential parameters and cookies are never arguments (the compiler drops them; credentials are
  supplied by the runtime);
* the request body is either **flat** (its properties are top-level arguments) or **nested** under
  ``body``, decided by the compiler's own rule (:meth:`ToolSchemaBuilder.for_message` plus the
  collision check), so the compiler and the binding never disagree.

It is pure — no I/O, no clock. Serializing a binding into a request is each runtime's own job.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .canonical_model import CanonicalApi, Message, MessageRole, Operation, ParameterLocation
from .emitter import LossTracker
from .mcp_tool_mapping import success_response
from .tool_projection import BODY_ARGUMENT_NAME, ToolSchemaBuilder, is_credential_parameter

__all__ = [
    "BODY_ARGUMENT_NAME",
    "BodyMode",
    "Location",
    "OperationBinding",
    "OperationNotInvocableError",
    "ParameterBinding",
    "binding_for",
    "is_json_media_type",
]

Location = Literal["path", "query", "header"]
BodyMode = Literal["none", "flat", "nested"]

#: Swagger 2.0 ``collectionFormat`` → the OpenAPI 3 ``(style, explode)`` it means for a query value.
_COLLECTION_FORMATS: dict[str, tuple[str, bool]] = {
    "csv": ("form", False),
    "multi": ("form", True),
    "ssv": ("spaceDelimited", False),
    "pipes": ("pipeDelimited", False),
    "tsv": ("tabDelimited", False),
}

#: The OpenAPI default style per location (``explode`` defaults to true only for ``form``).
_DEFAULT_STYLE: dict[Location, str] = {"path": "simple", "query": "form", "header": "simple"}

_LOCATIONS: dict[ParameterLocation, Location] = {
    ParameterLocation.PATH: "path",
    ParameterLocation.QUERY: "query",
    ParameterLocation.HEADER: "header",
}


class OperationNotInvocableError(ValueError):
    """The tool's operation has no HTTP method and path, so no runtime can call it."""


@dataclass(frozen=True)
class ParameterBinding:
    """Where one argument goes and how it is serialized.

    Attributes:
        name: The parameter (and argument) name.
        location: ``path``, ``query`` or ``header``.
        style: The OpenAPI serialization style.
        explode: The OpenAPI ``explode`` flag.
        allow_reserved: OpenAPI ``allowReserved`` (query only).
        required: Whether the parameter must be present.
    """

    name: str
    location: Location
    style: str
    explode: bool
    allow_reserved: bool = False
    required: bool = False


@dataclass(frozen=True)
class OperationBinding:
    """Everything needed to turn one tool's arguments into a request.

    Attributes:
        operation_key: The canonical operation key (``GET /pets/{petId}``).
        method: The upper-case HTTP method.
        path_template: The operation path, with ``{name}`` placeholders.
        parameters: The non-body arguments, in declaration order.
        body_mode: ``none`` (no request body), ``flat`` (body properties are top-level arguments)
            or ``nested`` (the body is the ``body`` argument).
        body_required: Whether the spec marks the request body required.
        body_media_type: The media type the body is encoded as.
        accept: The ``Accept`` header (the success response's media type, when known).
    """

    operation_key: str
    method: str
    path_template: str
    parameters: tuple[ParameterBinding, ...] = ()
    body_mode: BodyMode = "none"
    body_required: bool = False
    body_media_type: str | None = None
    accept: str | None = None

    @property
    def path_arguments(self) -> tuple[str, ...]:
        """Names of the arguments that identify the resource (the path parameters)."""
        return tuple(p.name for p in self.parameters if p.location == "path")


def is_json_media_type(media_type: str) -> bool:
    """Whether a media type is JSON (``application/json``, ``…+json``, ``…/json; charset=…``)."""
    essence = media_type.split(";", 1)[0].strip().lower()
    return essence.endswith("/json") or essence.endswith("+json")


# --------------------------------------------------------------------------------------------------
# Binding an operation
# --------------------------------------------------------------------------------------------------


def _request_message(operation: Operation) -> Message | None:
    """The operation's request message, when it declares one."""
    for message in operation.messages:
        if message.role is MessageRole.REQUEST:
            return message
    return None


def _resolve_local_ref(document: Mapping[str, Any], node: Any) -> Any:
    """Follow one local ``#/…`` ``$ref`` (a few hops at most); anything else is returned as is."""
    for _ in range(8):
        if not isinstance(node, Mapping) or not isinstance(node.get("$ref"), str):
            return node
        ref = str(node["$ref"])
        if not ref.startswith("#/"):
            return node
        target: Any = document
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, Mapping) or part not in target:
                return node
            target = target[part]
        node = target
    return node


def _raw_parameters(api: CanonicalApi, operation: Operation) -> dict[tuple[str, str], Mapping[str, Any]]:
    """The source document's parameter objects for ``operation``, keyed by ``(in, name)``.

    Path-item parameters come first and operation parameters override them, as OpenAPI says.
    Empty when the model kept no raw document or the path is not in it.
    """
    raw = api.raw if isinstance(api.raw, Mapping) else None
    if raw is None or not operation.http_path or not operation.http_method:
        return {}
    paths = raw.get("paths")
    path_item = _resolve_local_ref(raw, paths.get(operation.http_path)) if isinstance(paths, Mapping) else None
    if not isinstance(path_item, Mapping):
        return {}
    found: dict[tuple[str, str], Mapping[str, Any]] = {}
    op_obj = path_item.get(operation.http_method.lower())
    for source in (path_item.get("parameters"), op_obj.get("parameters") if isinstance(op_obj, Mapping) else None):
        for entry in source if isinstance(source, list) else []:
            param = _resolve_local_ref(raw, entry)
            if isinstance(param, Mapping) and isinstance(param.get("name"), str) and isinstance(param.get("in"), str):
                found[(str(param["in"]).lower(), str(param["name"]))] = param
    return found


def _serialization(location: Location, raw: Mapping[str, Any] | None) -> tuple[str, bool, bool]:
    """``(style, explode, allow_reserved)`` from a raw parameter object, with OpenAPI defaults."""
    raw = raw or {}
    collection = raw.get("collectionFormat")
    if location == "query" and isinstance(collection, str) and collection in _COLLECTION_FORMATS:
        style, explode = _COLLECTION_FORMATS[collection]
        return style, explode, False
    declared_style = raw.get("style")
    style = declared_style if isinstance(declared_style, str) else _DEFAULT_STYLE[location]
    declared_explode = raw.get("explode")
    explode = declared_explode if isinstance(declared_explode, bool) else style == "form"
    return style, explode, bool(raw.get("allowReserved")) and location == "query"


def _body_media_type(message: Message) -> str:
    """The media type to encode the body as: the first JSON type declared, else the first, else JSON."""
    types = [t for t in message.content_types if isinstance(t, str) and t]
    for media_type in types:
        if is_json_media_type(media_type):
            return media_type
    return types[0] if types else "application/json"


def _body_mode(
    api: CanonicalApi, message: Message | None, argument_names: Iterable[str]
) -> tuple[BodyMode, bool, str | None]:
    """Decide where the body's arguments are, exactly as the AGX-1.1 compiler laid them out.

    The compiler merges an object body flat unless one of its properties collides with a parameter
    argument (then the whole body nests under ``body``); a body that is not an object always nests.
    """
    if message is None:
        return "none", False, None
    schema = ToolSchemaBuilder(api, losses=LossTracker()).for_message(message)
    if schema is None:
        return "none", False, None
    media_type = _body_media_type(message)
    properties = schema.get("properties")
    if schema.get("type") == "object" and isinstance(properties, dict) and not set(properties) & set(argument_names):
        return "flat", bool(message.required), media_type
    return "nested", bool(message.required), media_type


def _accept(operation: Operation) -> str | None:
    """The success response's media type, for ``Accept`` (``None`` when unknown)."""
    message = success_response(operation)
    types = [t for t in (message.content_types if message else []) if isinstance(t, str) and t]
    if not types:
        return None
    json_types = [t for t in types if is_json_media_type(t)]
    return json_types[0] if json_types else types[0]


def binding_for(api: CanonicalApi, operation: Operation) -> OperationBinding:
    """Bind one operation: where each of its tool's arguments goes, and how it is encoded.

    Args:
        api: The canonical model the operation belongs to (its ``raw`` document supplies the
            serialization styles).
        operation: The operation a tool invokes (``McpToolDefinition.operation``).

    Returns:
        The binding.

    Raises:
        OperationNotInvocableError: The operation has no HTTP method or path (an RPC, GraphQL or
            event operation), so there is no HTTP request to build.
    """
    if not operation.http_method or not operation.http_path:
        raise OperationNotInvocableError(f"operation {operation.key!r} has no HTTP method and path")
    raw = _raw_parameters(api, operation)
    bindings: list[ParameterBinding] = []
    for parameter in operation.parameters:
        location = _LOCATIONS.get(parameter.location)
        if location is None or is_credential_parameter(parameter):
            continue
        style, explode, allow_reserved = _serialization(location, raw.get((location, parameter.name)))
        bindings.append(
            ParameterBinding(
                name=parameter.name,
                location=location,
                style=style,
                explode=explode,
                allow_reserved=allow_reserved,
                required=parameter.required or location == "path",
            )
        )
    mode, body_required, media_type = _body_mode(api, _request_message(operation), (b.name for b in bindings))
    return OperationBinding(
        operation_key=operation.key,
        method=operation.http_method.upper(),
        path_template=operation.http_path,
        parameters=tuple(bindings),
        body_mode=mode,
        body_required=body_required,
        body_media_type=media_type,
        accept=_accept(operation),
    )
