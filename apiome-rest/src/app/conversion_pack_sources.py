"""Source-text readers for the per-format conversion packs (MFI-22.8, #4009).

Two packs refine the canonical model with an HTTP binding the normalizer does not record, and
both read it from the *source text* the conversion re-parsed rather than from the normalized
model:

* **gRPC / Protobuf** — ``option (google.api.http) = { get: "/v1/…" body: "*" };`` on an
  ``rpc``, the gRPC-transcoding annotation ``protoc-gen-openapiv2`` and gnostic honor.
* **Smithy** — the ``@http(method: "GET", uri: "/…", code: 200)`` trait on an ``operation``,
  plus whether the model uses ``@endpoint`` / ``@hostLabel`` (which ``smithy-openapi``
  documents as not converting).

Reading the text keeps the normalizers' ``extras`` contract (and with it the round-trip matrix
and the corpus goldens) untouched: the binding is only needed on the way *to* OpenAPI. The
readers are deliberately small lexers — comments are stripped and braces are matched — not
grammars; anything they cannot read is simply not a binding, and the conversion falls back to
the synthesized ``POST /{Service}/{Method}`` it has always produced.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "HttpBinding",
    "proto_http_bindings",
    "smithy_http_bindings",
    "smithy_unconverted_traits",
]

#: Verbs a ``google.api.http`` rule may name directly (the ``pattern`` oneof).
_PROTO_VERBS = ("get", "put", "post", "delete", "patch")

_STRING = r'"(?:[^"\\]|\\.)*"'
_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_PROTO_SERVICE_RE = re.compile(r"\bservice\s+(\w+)\s*\{")
_PROTO_RPC_RE = re.compile(
    r"\brpc\s+(\w+)\s*\([^)]*\)\s*returns\s*\([^)]*\)\s*(\{|;)", re.MULTILINE
)
_PROTO_HTTP_OPTION_RE = re.compile(r"\boption\s*\(\s*google\.api\.http\s*\)\s*=\s*\{")
# `name: "value"`, `name: { … }`, or the text format's colon-less `name { … }`.
_FIELD_RE = re.compile(r"(\w+)\s*(?::\s*(" + _STRING + r")|:?\s*(\{))")

_SMITHY_OPERATION_RE = re.compile(r"\boperation\s+(\w+)\s*\{")
_SMITHY_HTTP_TRAIT_RE = re.compile(r"@http\s*\(")
_SMITHY_TRAIT_ARG_RE = re.compile(r"(\w+)\s*:\s*(" + _STRING + r"|\d+)")


@dataclass(frozen=True)
class HttpBinding:
    """One HTTP binding read from the source.

    Attributes:
        method: The HTTP method, lower-case (``get``, ``post``, or a custom verb).
        path: The URI template, e.g. ``/v1/orders/{id}``.
        body: The ``google.api.http`` ``body`` field (``*``, a field name), when declared.
        extra_bindings: How many ``additional_bindings`` the rule carried — only the primary
            binding becomes an OpenAPI operation, so the pack reports the rest as a loss.
    """

    method: str
    path: str
    body: Optional[str] = None
    extra_bindings: int = 0

    def as_extras(self) -> Dict[str, str]:
        """The ``extras["http"]`` shape :func:`app.projection._http_binding_from_extras` reads."""
        binding = {"method": self.method, "path": self.path}
        if self.body:
            binding["body"] = self.body
        return binding


def _strip_comments(text: str) -> str:
    """Blank out ``/* … */`` and ``// …`` comments (string contents are left alone)."""
    return _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", text))


def _block_end(text: str, open_brace: int) -> int:
    """Return the index of the ``}`` matching the ``{`` at ``open_brace``, or ``-1``.

    Braces inside double-quoted strings are skipped, so a path template such as
    ``"/v1/{name}"`` never unbalances the count.
    """
    depth = 0
    index = open_brace
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _unquote(literal: str) -> str:
    """Strip the quotes off a ``"…"`` literal and undo its escapes (JSON rules; else verbatim)."""
    try:
        value = json.loads(literal)
    except ValueError:
        return literal[1:-1]
    return value if isinstance(value, str) else literal[1:-1]


def _top_level_fields(body: str) -> List[Tuple[str, str]]:
    """Read ``name: "value"`` / ``name: { … }`` pairs at the top level of a message literal.

    Returns ``(name, value)`` with a string value unquoted and a nested message returned as its
    inner text, in source order. Nested messages are not descended into here.
    """
    fields: List[Tuple[str, str]] = []
    index = 0
    while True:
        match = _FIELD_RE.search(body, index)
        if not match:
            return fields
        name, value = match.group(1), match.group(2) or match.group(3)
        if value == "{":
            end = _block_end(body, match.end() - 1)
            if end < 0:
                return fields
            fields.append((name, body[match.end() : end]))
            index = end + 1
        else:
            fields.append((name, _unquote(value)))
            index = match.end()


def _http_rule(body: str) -> Optional[HttpBinding]:
    """Turn the inside of a ``google.api.http`` option into its primary binding."""
    method: Optional[str] = None
    path: Optional[str] = None
    request_body: Optional[str] = None
    extra = 0
    for name, value in _top_level_fields(body):
        if name in _PROTO_VERBS and method is None:
            method, path = name, value
        elif name == "custom" and method is None:
            custom = dict(_top_level_fields(value))
            if custom.get("kind") and custom.get("path"):
                method, path = custom["kind"].lower(), custom["path"]
        elif name == "body":
            request_body = value
        elif name == "additional_bindings":
            extra += 1
    if method is None or not path:
        return None
    return HttpBinding(method=method, path=path, body=request_body, extra_bindings=extra)


def proto_http_bindings(source_text: Optional[str]) -> Dict[Tuple[str, str], HttpBinding]:
    """Read every ``google.api.http`` binding in a ``.proto`` source.

    Args:
        source_text: The ``.proto`` text the conversion re-parsed; ``None`` (a binary
            descriptor set has no text) yields no bindings.

    Returns:
        ``{(service_name, rpc_name): binding}`` for each annotated ``rpc``. Unannotated
        methods and options the reader cannot parse are absent.
    """
    if not source_text:
        return {}
    text = _strip_comments(source_text)
    bindings: Dict[Tuple[str, str], HttpBinding] = {}
    for service in _PROTO_SERVICE_RE.finditer(text):
        service_end = _block_end(text, service.end() - 1)
        if service_end < 0:
            continue
        service_body = text[service.end() : service_end]
        for rpc in _PROTO_RPC_RE.finditer(service_body):
            if rpc.group(2) != "{":
                continue
            rpc_end = _block_end(service_body, rpc.end() - 1)
            if rpc_end < 0:
                continue
            rpc_body = service_body[rpc.end() : rpc_end]
            option = _PROTO_HTTP_OPTION_RE.search(rpc_body)
            if not option:
                continue
            option_end = _block_end(rpc_body, option.end() - 1)
            if option_end < 0:
                continue
            binding = _http_rule(rpc_body[option.end() : option_end])
            if binding is not None:
                bindings[(service.group(1), rpc.group(1))] = binding
    return bindings


def _last_unquoted_brace(text: str) -> int:
    """Index of the last ``}`` in ``text`` that is not inside a double-quoted string, or -1."""
    last = -1
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "}":
            last = index
        index += 1
    return last


def _trait_arguments(text: str, open_paren: int) -> Tuple[Dict[str, str], int]:
    """Read the ``key: value`` arguments of a trait call starting at ``(``.

    Returns the arguments (strings unquoted, numbers as text) and the index after ``)``.
    """
    depth = 0
    index = open_paren
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        index += 1
    inner = text[open_paren + 1 : index]
    arguments = {
        key: (_unquote(value) if value.startswith('"') else value)
        for key, value in _SMITHY_TRAIT_ARG_RE.findall(inner)
    }
    return arguments, index + 1


def smithy_http_bindings(source_text: Optional[str]) -> Dict[str, HttpBinding]:
    """Read the ``@http`` trait of every Smithy ``operation`` that declares one.

    The trait must sit in the operation's leading trait block — between the previous shape
    (or the start of the file) and the ``operation`` keyword — which is where Smithy IDL puts
    it.

    Args:
        source_text: The Smithy IDL text the conversion re-parsed.

    Returns:
        ``{operation_name: binding}`` for each operation with a readable ``@http`` trait.
    """
    if not source_text:
        return {}
    text = _strip_comments(source_text)
    bindings: Dict[str, HttpBinding] = {}
    previous_end = 0
    for operation in _SMITHY_OPERATION_RE.finditer(text):
        prelude = text[previous_end : operation.start()]
        # Only the traits applied to *this* shape: everything after the last closing brace
        # (a brace inside a string — a `uri: "/orders/{id}"` — is not one).
        prelude = prelude[_last_unquoted_brace(prelude) + 1 :]
        trait = None
        for candidate in _SMITHY_HTTP_TRAIT_RE.finditer(prelude):
            trait = candidate
        if trait is not None:
            arguments, _ = _trait_arguments(prelude, trait.end() - 1)
            method, uri = arguments.get("method"), arguments.get("uri")
            if method and uri:
                bindings[operation.group(1)] = HttpBinding(method=method.lower(), path=uri)
        end = _block_end(text, operation.end() - 1)
        previous_end = end + 1 if end >= 0 else operation.end()
    return bindings


def smithy_unconverted_traits(source_text: Optional[str]) -> List[str]:
    """Which of the traits ``smithy-openapi`` documents as unconverted the model uses.

    ``@endpoint`` (a host prefix per operation) and ``@hostLabel`` (a member bound into that
    host) have no OpenAPI representation; the Smithy pack reports each one it finds as a loss.

    Args:
        source_text: The Smithy IDL text.

    Returns:
        The trait names present, from ``("endpoint", "hostLabel")``, in that order.
    """
    if not source_text:
        return []
    text = _strip_comments(source_text)
    return [name for name in ("endpoint", "hostLabel") if re.search(rf"@{name}\b", text)]
