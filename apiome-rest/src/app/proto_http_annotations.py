"""``google.api.http`` annotations for the protobuf emitter — MFX-12.6 (#4343).

A REST source's operations carry an HTTP verb and a route (``GET /pets/{id}``). Protobuf has no
native place for them, but the gRPC-Gateway / Connect / Envoy transcoding convention does: the
``google.api.http`` method option. This module turns an operation's REST binding into that rule,
so :class:`app.proto_emitter.ProtoEmitter` (with ``http_annotations`` on) can write::

    rpc GetPet (.acme.GetPetRequest) returns (.acme.Pet) {
      option (google.api.http) = {
        get: "/pets/{id}"
      };
    }

and :class:`app.proto_emitter.ProtoFidelityRulePack` can predict the same outcome. Both read the
binding through :func:`http_annotation_for` and the parameters the rule cannot bind through
:func:`unbound_parameters`, so the emitted losses and the predicted verdicts agree.

The binding comes from, in order:

* the operation's own ``http_method`` + ``http_path`` (a REST/OpenAPI source); or
* an ``extras["http"]`` binding an RPC normalizer recorded (a ``.proto`` that already carried
  ``google.api.http``, or a Smithy ``@http`` trait), read the way
  :func:`app.projection._http_binding_from_extras` reads it.

The module is pure: no I/O, and the same operation always yields the same rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional

from .canonical_model import Operation, ParameterLocation, Type
from .projection import _http_binding_from_extras

__all__ = [
    "GOOGLE_API_ANNOTATIONS_IMPORT",
    "HttpAnnotation",
    "http_annotation_for",
    "render_http_option",
    "request_field_names",
    "request_payload_name",
    "unbound_parameters",
]

#: The import an annotated ``.proto`` needs; :mod:`app.proto_descriptor` vendors it for ``buf``.
GOOGLE_API_ANNOTATIONS_IMPORT = "google/api/annotations.proto"

#: The verbs ``google.api.HttpRule`` names as fields; any other verb is written as ``custom``.
_RULE_VERBS = frozenset({"get", "put", "post", "delete", "patch"})

#: Verbs whose rule may carry a request ``body`` (gRPC-Gateway rejects a body on GET/DELETE).
_BODY_VERBS = frozenset({"post", "put", "patch"})

#: A ``{variable}`` (or ``{variable=pattern}``) segment of a route template.
_PATH_VARIABLE_RE = re.compile(r"\{([^}=]+)(=[^}]*)?\}")

#: Characters a ``google.api.http`` field path may not contain (``a.b_c`` is legal).
_NON_FIELD_PATH_RE = re.compile(r"[^A-Za-z0-9_.]")


@dataclass(frozen=True)
class HttpAnnotation:
    """One ``google.api.http`` rule derived from an operation's REST binding.

    Attributes:
        verb: The lower-cased HTTP verb (``get``, ``post``, … or a custom one such as ``head``).
        path: The route template with each variable coerced to a legal field path.
        body: The rule's ``body`` (``"*"`` for the whole request message), or ``None``.
    """

    verb: str
    path: str
    body: Optional[str]

    @property
    def label(self) -> str:
        """The binding as a reader writes it, e.g. ``GET /pets/{id}``."""
        return f"{self.verb.upper()} {self.path}"

    def variables(self) -> List[str]:
        """The route's variable names, in order (``/pets/{id}/toys/{toy_id}`` → ``id``, ``toy_id``)."""
        return [match.group(1) for match in _PATH_VARIABLE_RE.finditer(self.path)]


def request_payload_name(operation: Operation) -> Optional[str]:
    """The type key of the operation's request payload, or ``None`` when it has none.

    Mirrors how :class:`app.proto_emitter.ProtoEmitter` picks an ``rpc``'s request message: the
    first ``request`` or ``event`` message that names a payload.

    Args:
        operation: The canonical operation.

    Returns:
        The payload's type key, or ``None`` (the emitter then uses ``google.protobuf.Empty``).
    """
    for message in operation.messages:
        if message.payload is not None and message.payload.name and message.role.value in (
            "request",
            "event",
        ):
            return message.payload.name
    return None


def _field_path(name: str) -> str:
    """Coerce a route variable to a legal ``google.api.http`` field path (``pet-id`` → ``pet_id``)."""
    coerced = _NON_FIELD_PATH_RE.sub("_", name.strip()) or "_"
    return f"_{coerced}" if coerced[0].isdigit() else coerced


def _normalize_path(path: str) -> str:
    """Return ``path`` absolute, with each ``{variable}`` coerced to a legal field path."""
    absolute = path if path.startswith("/") else f"/{path}"
    return _PATH_VARIABLE_RE.sub(
        lambda match: "{" + _field_path(match.group(1)) + (match.group(2) or "") + "}", absolute
    )


def http_annotation_for(operation: Operation) -> Optional[HttpAnnotation]:
    """Derive the ``google.api.http`` rule for ``operation``, or ``None`` when it has no binding.

    A REST operation's own verb and route win; otherwise an ``extras["http"]`` binding is used,
    keeping the ``body`` it recorded. A REST operation with a request payload gets ``body: "*"``
    on a POST/PUT/PATCH (the whole request message is the HTTP body); a GET/DELETE never carries
    a body, as gRPC-Gateway requires.

    Args:
        operation: The canonical operation.

    Returns:
        The rule, or ``None`` when the operation has no HTTP verb and route to carry.
    """
    if operation.http_method and operation.http_path:
        verb = operation.http_method.strip().lower()
        body = "*" if verb in _BODY_VERBS and request_payload_name(operation) else None
        return HttpAnnotation(
            verb=verb, path=_normalize_path(operation.http_path), body=body
        )
    binding = _http_binding_from_extras(operation)
    if binding is None:
        return None
    verb, path = binding
    http = operation.extras.get("http")
    recorded = http.get("body") if isinstance(http, dict) else None
    body = recorded if isinstance(recorded, str) and recorded and verb in _BODY_VERBS else None
    return HttpAnnotation(verb=verb, path=_normalize_path(path), body=body)


def unbound_parameters(
    operation: Operation,
    annotation: HttpAnnotation,
    request_fields: Optional[Iterable[str]],
) -> List[str]:
    """The REST inputs the annotated rule cannot bind to a request-message field.

    gRPC-Gateway binds a route variable or a query parameter to the request message field of the
    same name, and has no binding for a header or cookie. So an input is *unbound* when:

    * it is a ``header`` or ``cookie`` parameter (never carried by the rule); or
    * it is a route variable or ``query`` parameter the request message does not declare (when
      ``body`` is ``"*"`` the query cannot carry anything, so only route variables count there).

    Args:
        operation: The canonical operation.
        annotation: The rule :func:`http_annotation_for` derived for it.
        request_fields: The request message's field names, or ``None`` when the request is
            ``google.protobuf.Empty`` (no fields at all).

    Returns:
        Human-readable labels of the unbound inputs (``path id``, ``header X-Trace``), sorted.
    """
    fields = {name for name in (request_fields or ())}
    unbound: set[str] = set()
    for variable in annotation.variables():
        if variable.split(".", 1)[0] not in fields:
            unbound.add(f"path {variable}")
    for parameter in operation.parameters:
        location = parameter.location
        if location in (ParameterLocation.HEADER, ParameterLocation.COOKIE):
            unbound.add(f"{location.value} {parameter.name}")
        elif location is ParameterLocation.QUERY and annotation.body != "*":
            if _field_path(parameter.name) not in fields:
                unbound.add(f"query {parameter.name}")
    return sorted(unbound)


def _quote(text: str) -> str:
    """Render ``text`` as a protobuf text-format string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_http_option(annotation: HttpAnnotation, pad: str, indent: str) -> List[str]:
    """Render the ``option (google.api.http) = { … };`` lines for one rule.

    Args:
        annotation: The rule to render.
        pad: The indentation of the ``option`` line (inside the ``rpc`` block).
        indent: One indentation step, for the rule's fields.

    Returns:
        The option's lines. A standard verb is a field (``get: "/pets/{id}"``); any other verb is
        a ``custom`` pattern (``custom: { kind: "HEAD" path: "/pets" }``).
    """
    inner = pad + indent
    lines = [f"{pad}option (google.api.http) = {{"]
    if annotation.verb in _RULE_VERBS:
        lines.append(f"{inner}{annotation.verb}: {_quote(annotation.path)}")
    else:
        lines.append(
            f"{inner}custom: {{ kind: {_quote(annotation.verb.upper())} "
            f"path: {_quote(annotation.path)} }}"
        )
    if annotation.body:
        lines.append(f"{inner}body: {_quote(annotation.body)}")
    lines.append(f"{pad}}};")
    return lines


def request_field_names(
    operation: Operation, types_by_key: Mapping[str, Type]
) -> Optional[List[str]]:
    """The emitted field names of ``operation``'s request message, or ``None`` when it has none.

    Args:
        operation: The canonical operation.
        types_by_key: The model's types, keyed by canonical key.

    Returns:
        Each request field's name as the emitter writes it, ``[]`` for a request type the model
        does not define (an imported message), or ``None`` when the request is
        ``google.protobuf.Empty``.
    """
    payload = request_payload_name(operation)
    if payload is None:
        return None
    request_type = types_by_key.get(payload)
    if request_type is None:
        return []
    return [_field_path(field.name) for field in request_type.fields]
