"""AGX-2.1 request construction — tool arguments → one upstream HTTP request (#4533).

The AGX-1.1 compiler flattens an operation's path, query and header parameters and its request body
into one ``inputSchema`` object (``docs/TOOL_COMPILER.md``). This module runs that flattening
backwards: given the operation a tool invokes and the arguments an agent sent, it builds the HTTP
request the spec describes. It is pure — no I/O, no clock — so every serialization rule is tested
directly.

**Where each argument goes.** :func:`binding_for` reads the operation once (it lives in
:mod:`app.mcp_operation_binding`, shared with the SDK-4.5 generated MCP server, #4499):

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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from app.canonical_model import CanonicalApi
from app.mcp_operation_binding import (
    BODY_ARGUMENT_NAME,
    OperationBinding,
    OperationNotInvocableError,
    ParameterBinding,
    binding_for,
    is_json_media_type,
)
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

#: Header names an argument may never set: the HTTP client's framing headers (shared with the
#: AGX-2.2 vault's placement rule) plus the credential headers the vault owns.
_PROTECTED_HEADERS = frozenset(RESERVED_HEADER_NAMES | {"authorization", "proxy-authorization"})

#: Characters ``allowReserved`` leaves unencoded in a query value. ``&``, ``#`` and ``=`` stay
#: encoded even then: unencoded they would end the value, the query, or start a new pair.
_RESERVED_QUERY_SAFE = ":/?[]@!$'()*+,;"

#: ``{name}`` in a path template.
_TEMPLATE_VAR = re.compile(r"\{([^{}]+)\}")


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
# Serialization
# --------------------------------------------------------------------------------------------------


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
    if is_json_media_type(media_type):
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
