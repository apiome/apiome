"""AGX-2.1 request construction — tool arguments → one upstream HTTP request (#4533).

The AGX-1.1 compiler flattens an operation's path, query and header parameters and its request body
into one ``inputSchema`` object (``docs/TOOL_COMPILER.md``). This module runs that flattening
backwards: given the operation a tool invokes and the arguments an agent sent, it builds the HTTP
request the spec describes. It is pure — no I/O, no clock — so every serialization rule is tested
directly.

**Where each argument goes.** :func:`binding_for` reads the operation once:

* a path, query or header parameter becomes a :class:`ParameterBinding`, carrying the OpenAPI
  ``style`` / ``explode`` / ``allowReserved`` of the source document (or the Swagger 2.0
  ``collectionFormat``), with the OpenAPI defaults when the source says nothing;
* credential parameters and cookies are never arguments (the compiler drops them; the AGX-2.2 vault
  supplies credentials server-side);
* the request body is either **flat** (its properties are top-level arguments) or **nested** under
  ``body``, decided by the compiler's own rule (:meth:`ToolSchemaBuilder.for_message` plus the
  collision check), so the two never disagree.

**Serialization** follows the OpenAPI 3 "Style Values" table: ``simple``, ``label`` and ``matrix``
for path parameters; ``form``, ``spaceDelimited``, ``pipeDelimited`` and ``deepObject`` for query
parameters; ``simple`` for headers. Booleans are ``true``/``false``; a nested object or array inside
a value is sent as compact JSON. Every value is percent-encoded, so an argument can never add a path
segment, a query parameter or a header line.

**Safety rails here** are the ones request construction alone can enforce: an empty path parameter,
a path parameter that serializes to a ``.``/``..`` segment, and a header value with a line break are
refused as invalid arguments; a header argument that names a header the HTTP client or the vault
owns (``Host``, ``Content-Length``, ``Authorization``…) is dropped. The SSRF / method / size rails
are AGX-2.3 (#4535).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

from app.canonical_model import CanonicalApi, Message, MessageRole, Operation, ParameterLocation
from app.emitter import LossTracker
from app.mcp_tool_mapping import success_response
from app.tool_projection import BODY_ARGUMENT_NAME, ToolSchemaBuilder, is_credential_parameter
from app.upstream_credential_binding import RESERVED_HEADER_NAMES

__all__ = [
    "BODY_ARGUMENT_NAME",
    "ArgumentIssue",
    "InvalidArgumentsError",
    "OperationBinding",
    "OperationNotInvocableError",
    "ParameterBinding",
    "UpstreamRequest",
    "binding_for",
    "build_request",
    "resolve_server_url",
]

Location = Literal["path", "query", "header"]
BodyMode = Literal["none", "flat", "nested"]

#: Header names an argument may never set: the HTTP client's framing headers (shared with the
#: AGX-2.2 vault's placement rule) plus the credential headers the vault owns.
_PROTECTED_HEADERS = frozenset(RESERVED_HEADER_NAMES | {"authorization", "proxy-authorization"})

#: Characters ``allowReserved`` leaves unencoded in a query value. ``&``, ``#`` and ``=`` stay
#: encoded even then: unencoded they would end the value, the query, or start a new pair.
_RESERVED_QUERY_SAFE = ":/?[]@!$'()*+,;"

#: ``{name}`` in a path template.
_TEMPLATE_VAR = re.compile(r"\{([^{}]+)\}")

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


@dataclass(frozen=True)
class ArgumentIssue:
    """One problem with the arguments an agent sent.

    Attributes:
        argument: Where: the argument name, a dotted/indexed path into it (``tags[0]``), or
            ``(arguments)`` for the argument object itself.
        problem: What is wrong, in a sentence the agent can act on. Never echoes a whole value.
    """

    argument: str
    problem: str

    def to_dict(self) -> dict[str, str]:
        """The issue as JSON (``{"argument", "problem"}``)."""
        return {"argument": self.argument, "problem": self.problem}


class InvalidArgumentsError(ValueError):
    """The arguments cannot be turned into a request; nothing is sent upstream.

    Attributes:
        issues: Every problem found.
    """

    def __init__(self, issues: Sequence[ArgumentIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{issue.argument}: {issue.problem}" for issue in self.issues))


class OperationNotInvocableError(ValueError):
    """The tool's operation has no HTTP method and path, so the proxy cannot call it."""


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


@dataclass(frozen=True)
class UpstreamRequest:
    """A request ready to send, relative to a base URL.

    Attributes:
        method: The HTTP method.
        path: The expanded, percent-encoded path (starts with ``/``).
        query: The encoded query string, without ``?`` (may be empty).
        headers: Headers to send. Content-Type is set when there is a body.
        content: The encoded body, or ``None``.
    """

    method: str
    path: str
    query: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    content: bytes | None = None

    def url(self, base_url: str) -> str:
        """The absolute URL of this request under ``base_url`` (no trailing slash expected)."""
        url = base_url.rstrip("/") + self.path
        return f"{url}?{self.query}" if self.query else url


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
        if _is_json(media_type):
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
    json_types = [t for t in types if _is_json(t)]
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


# --------------------------------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------------------------------


def _is_json(media_type: str) -> bool:
    """Whether a media type is JSON (``application/json``, ``…+json``, ``…/json; charset=…``)."""
    essence = media_type.split(";", 1)[0].strip().lower()
    return essence.endswith("/json") or essence.endswith("+json")


def _text(value: Any) -> str:
    """One scalar as text: ``true``/``false`` for booleans, compact JSON for nested values."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _enc(text: str, safe: str = "") -> str:
    """Percent-encode ``text`` (UTF-8), leaving only unreserved characters and ``safe``."""
    return quote(text, safe=safe)


def _pairs(value: Mapping[str, Any]) -> list[tuple[str, str]]:
    """An object value as ``(key, text)`` pairs, in its own order."""
    return [(str(k), _text(v)) for k, v in value.items()]


def _serialize_path(binding: ParameterBinding, value: Any) -> str:
    """Serialize one path parameter (``simple`` / ``label`` / ``matrix``), percent-encoded."""
    name, explode, style = binding.name, binding.explode, binding.style
    if isinstance(value, list):
        items = [_enc(_text(v)) for v in value]
        if style == "label":
            return "." + ("." if explode else ",").join(items)
        if style == "matrix":
            if explode:
                return "".join(f";{_enc(name)}={item}" for item in items)
            return f";{_enc(name)}=" + ",".join(items)
        return ",".join(items)
    if isinstance(value, Mapping):
        pairs = [(_enc(k), _enc(v)) for k, v in _pairs(value)]
        if style == "matrix":
            if explode:
                return "".join(f";{k}={v}" for k, v in pairs)
            return f";{_enc(name)}=" + ",".join(f"{k},{v}" for k, v in pairs)
        joined = ("." if style == "label" and explode else ",").join(
            f"{k}={v}" if explode else f"{k},{v}" for k, v in pairs
        )
        return f".{joined}" if style == "label" else joined
    text = _enc(_text(value))
    if style == "label":
        return f".{text}"
    if style == "matrix":
        return f";{_enc(name)}={text}"
    return text


def _serialize_query(binding: ParameterBinding, value: Any) -> list[str]:
    """Serialize one query parameter into encoded ``name=value`` pairs."""
    safe = _RESERVED_QUERY_SAFE if binding.allow_reserved else ""
    name = _enc(binding.name)

    def enc(text: str) -> str:
        return _enc(text, safe)

    if isinstance(value, list):
        items = [enc(_text(v)) for v in value]
        if binding.style == "form" and binding.explode:
            return [f"{name}={item}" for item in items]
        separator = {"spaceDelimited": "%20", "pipeDelimited": "|", "tabDelimited": "%09"}.get(binding.style, ",")
        return [f"{name}=" + separator.join(items)]
    if isinstance(value, Mapping):
        pairs = _pairs(value)
        if binding.style == "deepObject":
            return [f"{name}%5B{_enc(k)}%5D={enc(v)}" for k, v in pairs]
        if binding.style == "form" and binding.explode:
            return [f"{_enc(k)}={enc(v)}" for k, v in pairs]
        return [f"{name}=" + ",".join(f"{enc(k)},{enc(v)}" for k, v in pairs)]
    return [f"{name}={enc(_text(value))}"]


def _serialize_header(binding: ParameterBinding, value: Any) -> str:
    """Serialize one header parameter (``simple``)."""
    if isinstance(value, list):
        return ",".join(_text(v) for v in value)
    if isinstance(value, Mapping):
        return ",".join(f"{k}={v}" if binding.explode else f"{k},{v}" for k, v in _pairs(value))
    return _text(value)


def _has_dot_segment(serialized: str) -> bool:
    """Whether a serialized path value is (or contains) a ``.``/``..`` segment a server would collapse."""
    return serialized in (".", "..") or any(part in (".", "..") for part in re.split(r"[;,=]", serialized))


def _multipart(fields: Mapping[str, Any]) -> tuple[bytes, str]:
    """Encode ``fields`` as ``multipart/form-data`` text parts; returns ``(body, content type)``."""
    boundary = f"apiome-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        for item in value if isinstance(value, list) else [value]:
            safe_name = str(name).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")
            chunks.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{safe_name}"\r\n\r\n'.encode()
                + _text(item).encode("utf-8")
                + b"\r\n"
            )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _encode_body(media_type: str, value: Any) -> tuple[bytes, str]:
    """Encode a request body for ``media_type``; returns ``(bytes, Content-Type)``.

    Raises:
        InvalidArgumentsError: A form media type was given a body that is not an object.
    """
    essence = media_type.split(";", 1)[0].strip().lower()
    if _is_json(media_type):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), media_type
    if essence in ("application/x-www-form-urlencoded", "multipart/form-data"):
        if not isinstance(value, Mapping):
            raise InvalidArgumentsError(
                [ArgumentIssue(BODY_ARGUMENT_NAME, f"must be an object of form fields for {essence}")]
            )
        if essence == "multipart/form-data":
            return _multipart(value)
        pairs = []
        for key, item in value.items():
            for element in item if isinstance(item, list) else [item]:
                pairs.append(f"{_enc(str(key))}={_enc(_text(element))}")
        return "&".join(pairs).encode("ascii"), media_type
    if isinstance(value, str):
        return value.encode("utf-8"), media_type
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), media_type


def build_request(binding: OperationBinding, arguments: Mapping[str, Any]) -> UpstreamRequest:
    """Build the HTTP request for one call.

    Args:
        binding: The tool's :func:`binding_for` result.
        arguments: The (already schema-validated) arguments the agent sent.

    Returns:
        The request, relative to a base URL.

    Raises:
        InvalidArgumentsError: A path parameter is missing, empty, or serializes to a dot segment;
            a header value contains a line break; or a form body is not an object.
    """
    issues: list[ArgumentIssue] = []
    by_name = {p.name: p for p in binding.parameters}
    consumed: set[str] = set()

    def expand(match: re.Match[str]) -> str:
        name = match.group(1)
        consumed.add(name)
        value = arguments.get(name)
        if value is None:
            issues.append(ArgumentIssue(name, "is a required path parameter"))
            return match.group(0)
        param = by_name.get(name) or ParameterBinding(name=name, location="path", style="simple", explode=False)
        serialized = _serialize_path(param, value)
        if serialized == "" or (isinstance(value, str) and value == ""):
            issues.append(ArgumentIssue(name, "must not be empty: it is a path segment"))
        elif _has_dot_segment(serialized):
            issues.append(ArgumentIssue(name, "must not be '.' or '..': it is a path segment"))
        return serialized

    path = _TEMPLATE_VAR.sub(expand, binding.path_template)
    if not path.startswith("/"):
        path = "/" + path

    query: list[str] = []
    headers: dict[str, str] = {}
    for param in binding.parameters:
        if param.location == "path":
            continue
        consumed.add(param.name)
        value = arguments.get(param.name)
        if value is None:
            continue
        if param.location == "query":
            query.extend(_serialize_query(param, value))
            continue
        if param.name.lower() in _PROTECTED_HEADERS:
            continue
        text = _serialize_header(param, value)
        if "\r" in text or "\n" in text or "\x00" in text:
            issues.append(ArgumentIssue(param.name, "must not contain line breaks: it is an HTTP header value"))
            continue
        headers[param.name] = text

    content: bytes | None = None
    if binding.body_mode != "none" and binding.body_media_type:
        body: Any = None
        if binding.body_mode == "nested":
            body = arguments.get(BODY_ARGUMENT_NAME)
        else:
            fields = {k: v for k, v in arguments.items() if k not in consumed}
            body = fields if fields or binding.body_required else None
        if body is not None:
            try:
                content, content_type = _encode_body(binding.body_media_type, body)
                headers["Content-Type"] = content_type
            except InvalidArgumentsError as exc:
                issues.extend(exc.issues)

    if issues:
        raise InvalidArgumentsError(issues)
    if binding.accept:
        headers.setdefault("Accept", binding.accept)
    return UpstreamRequest(method=binding.method, path=path, query="&".join(query), headers=headers, content=content)


# --------------------------------------------------------------------------------------------------
# Servers
# --------------------------------------------------------------------------------------------------


def resolve_server_url(api: CanonicalApi) -> str | None:
    """The production base URL from the spec's ``servers``: the first absolute ``http(s)`` entry.

    Server variables are replaced by their defaults (or their first ``enum`` value).

    Args:
        api: The canonical model.

    Returns:
        The base URL without a trailing slash, or ``None`` when no server is absolute (a relative
        ``/v1`` only makes sense next to the document, which the proxy does not have).
    """
    for server in api.servers:
        url = server.url or ""
        for variable in server.variables:
            fallback = variable.default if variable.default is not None else (variable.enum or [""])[0]
            url = url.replace("{" + variable.name + "}", fallback or "")
        lowered = url.lower()
        if (lowered.startswith("https://") or lowered.startswith("http://")) and "{" not in url:
            return url.rstrip("/")
    return None
