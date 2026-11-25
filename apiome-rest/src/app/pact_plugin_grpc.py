"""Read a Pact protobuf-plugin gRPC interaction onto the XPC-3.2 RPC case model — PFX-3.7 (#6937).

The Pact plugin framework lets a consumer test record exchanges Pact itself cannot describe.
The `protobuf plugin <https://github.com/pactflow/pact-protobuf-plugin>`_ records a gRPC call as
a Pact 4 ``Synchronous/Messages`` interaction with ``transport: grpc``::

    {"type": "Synchronous/Messages", "transport": "grpc",
     "description": "calculate the area of a rectangle",
     "pluginConfiguration": {"protobuf": {"descriptorKey": "a85d…", "service": "Calculator/calculateOne"}},
     "request":  {"contents": {"content": "<base64 protobuf>", "encoded": "base64",
                               "contentType": "application/protobuf;message=.area_calculator.ShapeMessage"}},
     "response": [{"contents": {"content": "<base64 protobuf>", …},
                   "matchingRules": {"body": {"$.value": {"matchers": [{"match": "number"}]}}}}]}

and files the ``.proto`` it was built from, compiled to a ``FileDescriptorSet``, once per pact
under ``metadata.plugins[name=protobuf].configuration[descriptorKey].protoDescriptors``.

This module turns one such interaction into what the XPC-3.2 RPC adapter
(:mod:`app.contract_suite_rpc`) already executes — a unary call of ``/{package.Service}/{Method}``
with a **protobuf-JSON** request message — plus the response the consumer expects, decoded the
same way. Everything is expressed in protobuf-JSON field names (``orderId`` for ``order_id``)
because that is what both transports return: a Connect server prints it, and the native gRPC
transport decodes binary replies with it. The pact's matching-rule paths name fields the way the
``.proto`` does, so they are rewritten to the JSON names through the descriptors.

Determinism
-----------
The descriptors live in the pact's ``metadata``, which the pact version's content address does
not cover. They are read only through the ``descriptorKey`` the interaction names — and that key
*is* covered (it is in the interaction) and is the plugin's digest of the descriptor bytes — so a
suite compiled from them is still a function of the pact version.

Nothing silently dropped
------------------------
Each reason an interaction cannot be expressed is a :class:`GrpcPluginProblem` naming a stable
code: no descriptors under the key, a service or method the descriptors do not declare, a
streaming method, request content that does not decode as the method's input type. What is
carried more weakly than the pact says is a *note* (a degraded finding): request metadata that
is not sent, response metadata or metadata rules that are not compared, more than one response.

Pure: protobuf descriptors are parsed in memory; nothing is fetched.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .pact_interaction_reader import as_dict

__all__ = [
    "CODE_GRPC_CONTENT_UNREADABLE",
    "CODE_GRPC_DESCRIPTORS_MISSING",
    "CODE_GRPC_METHOD_NOT_FOUND",
    "CODE_GRPC_STREAMING",
    "GRPC_STATUS_NAMES",
    "PROTOBUF_PLUGIN",
    "GrpcPluginCall",
    "GrpcPluginProblem",
    "DescriptorCatalog",
    "grpc_status_code",
    "is_grpc_plugin_interaction",
    "plugin_names",
    "read_grpc_interaction",
    "INT64_PATTERN",
    "int64_matcher",
    "rename_rule_path",
]

#: The plugin name the protobuf plugin registers under, in ``pluginConfiguration`` and metadata.
PROTOBUF_PLUGIN = "protobuf"

#: The pact's descriptors for the interaction's ``descriptorKey`` are absent or do not load.
CODE_GRPC_DESCRIPTORS_MISSING = "grpc-descriptors-missing"
#: The descriptors do not declare the service or method the interaction names.
CODE_GRPC_METHOD_NOT_FOUND = "grpc-method-not-found"
#: The method streams; a unary replay cannot express it.
CODE_GRPC_STREAMING = "grpc-streaming"
#: The request or response content does not decode as the method's message type.
CODE_GRPC_CONTENT_UNREADABLE = "grpc-content-unreadable"

#: gRPC status numbers → the lower-snake names the RPC runner compares (``ok``, ``not_found`` …).
GRPC_STATUS_NAMES: Dict[int, str] = {
    0: "ok",
    1: "cancelled",
    2: "unknown",
    3: "invalid_argument",
    4: "deadline_exceeded",
    5: "not_found",
    6: "already_exists",
    7: "permission_denied",
    8: "resource_exhausted",
    9: "failed_precondition",
    10: "aborted",
    11: "out_of_range",
    12: "unimplemented",
    13: "internal",
    14: "unavailable",
    15: "data_loss",
    16: "unauthenticated",
}

#: Metadata keys the plugin records that are part of the call itself, not sent or compared.
_CALL_METADATA = frozenset({"contenttype", "content-type", "grpc-status", "grpc-message"})

#: ``MethodOptions.idempotency_level`` values → the labels the mutating-method gate reads.
_IDEMPOTENCY_LABELS = {0: "unknown", 1: "no_side_effects", 2: "idempotent"}


def plugin_names(interaction: Mapping[str, Any]) -> List[str]:
    """The plugins an interaction's ``pluginConfiguration`` names, sorted.

    Args:
        interaction: One Pact 4 interaction.

    Returns:
        The plugin names (``["protobuf"]``), or an empty list.
    """
    configuration = interaction.get("pluginConfiguration")
    return sorted(str(name) for name in configuration) if isinstance(configuration, dict) else []


def is_grpc_plugin_interaction(interaction: Mapping[str, Any]) -> bool:
    """Whether an interaction is a gRPC call recorded by the protobuf plugin.

    Args:
        interaction: One Pact 4 interaction.

    Returns:
        True when it declares ``transport: grpc``, or is a ``Synchronous/Messages`` interaction
        configured by the protobuf plugin (older plugin versions write no transport).
    """
    transport = interaction.get("transport")
    if isinstance(transport, str) and transport.strip().lower() == "grpc":
        return True
    declared = interaction.get("type")
    synchronous = isinstance(declared, str) and declared.strip().lower() == "synchronous/messages"
    return synchronous and PROTOBUF_PLUGIN in plugin_names(interaction)


def grpc_status_code(value: Any) -> Optional[str]:
    """Normalise a recorded ``grpc-status`` to the runner's lower-snake code.

    Args:
        value: ``"NOT_FOUND"``, ``"not_found"``, ``5`` or ``"5"`` (a one-element list of any).

    Returns:
        ``not_found`` — or ``None`` for a value that names no gRPC status.
    """
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return GRPC_STATUS_NAMES.get(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return GRPC_STATUS_NAMES.get(int(text))
    name = text.lower()
    return name if name in GRPC_STATUS_NAMES.values() else None


@dataclass(frozen=True)
class GrpcPluginProblem:
    """Why an interaction cannot be replayed as a unary call.

    Attributes:
        code: One of the ``CODE_GRPC_*`` codes.
        reason: One sentence saying so.
    """

    code: str
    reason: str


@dataclass
class GrpcPluginCall:
    """A protobuf-plugin interaction, read onto the RPC case model.

    Attributes:
        service: Fully-qualified service (``area_calculator.Calculator``).
        method: Method name (``calculateOne``).
        procedure: ``/{service}/{method}``.
        input_type: Fully-qualified request message type.
        output_type: Fully-qualified response message type.
        idempotency_level: ``no_side_effects``, ``idempotent`` or ``unknown``.
        message: The request message, in protobuf-JSON.
        expect_code: The status the consumer expects (``ok``, or the recorded ``grpc-status``).
        expect_message: The recorded ``grpc-message`` of an error response, if any.
        has_body: Whether the consumer recorded a response message to compare.
        body: That message, in protobuf-JSON (``{}`` for an empty one).
        response_pointer: JSON Pointer of the response the case compares against.
        output_descriptor: The response message descriptor, to rename rule paths with
            (:func:`rename_rule_path`).
        notes: What is carried more weakly than the pact says, one sentence each.
    """

    service: str
    method: str
    procedure: str
    input_type: str
    output_type: str
    idempotency_level: str
    message: Dict[str, Any]
    expect_code: str
    expect_message: Optional[str]
    has_body: bool
    body: Optional[Dict[str, Any]]
    response_pointer: str
    output_descriptor: Any = None
    notes: List[Tuple[str, str]] = field(default_factory=list)


class DescriptorCatalog:
    """The protobuf descriptors a pact files, loaded on demand per ``descriptorKey``.

    Args:
        document: The parsed pact; ``metadata.plugins`` is read for the protobuf plugin's entry.
    """

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._encoded: Dict[str, Any] = {}
        plugins = as_dict(document.get("metadata")).get("plugins")
        for plugin in plugins if isinstance(plugins, list) else []:
            entry = as_dict(plugin)
            if entry.get("name") != PROTOBUF_PLUGIN:
                continue
            for key, value in as_dict(entry.get("configuration")).items():
                self._encoded.setdefault(str(key), as_dict(value).get("protoDescriptors"))
        self._pools: Dict[str, Tuple[Any, List[str], Optional[str]]] = {}

    def pool(self, key: str) -> Tuple[Any, List[str], Optional[str]]:
        """The descriptor pool for one key.

        Args:
            key: The interaction's ``descriptorKey``.

        Returns:
            ``(pool, service names, None)`` — every fully-qualified service the descriptors
            declare, sorted — or ``(None, [], why)`` when the pact files no loadable
            descriptors under the key.
        """
        if key not in self._pools:
            self._pools[key] = self._load(key)
        return self._pools[key]

    def _load(self, key: str) -> Tuple[Any, List[str], Optional[str]]:
        """Decode and load the ``FileDescriptorSet`` filed under ``key``."""
        from google.protobuf import descriptor_pb2, descriptor_pool

        encoded = self._encoded.get(key)
        if not isinstance(encoded, str) or not encoded.strip():
            return None, [], f"the pact's metadata files no protobuf descriptors under the key '{key}'"
        try:
            descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(base64.b64decode(encoded, validate=True))
        except Exception:  # noqa: BLE001 - bad base64 or bytes that are not a descriptor set
            return None, [], f"the protobuf descriptors under the key '{key}' are not a base64 FileDescriptorSet"
        files = {item.name: item for item in descriptor_set.file}
        pool = descriptor_pool.DescriptorPool()
        added: set = set()

        def _add(name: str) -> None:
            # Dependencies first: a pool refuses a file whose imports it has not seen.
            if name in added or name not in files:
                return
            added.add(name)
            for dependency in files[name].dependency:
                _add(dependency)
            pool.Add(files[name])

        try:
            for name in sorted(files):
                _add(name)
        except Exception as exc:  # noqa: BLE001 - a descriptor set that does not load
            return None, [], f"the protobuf descriptors under the key '{key}' do not load: {exc}"
        services = sorted(
            f"{item.package}.{service.name}" if item.package else service.name
            for item in descriptor_set.file
            for service in item.service
        )
        return pool, services, None


def _find_method(pool: Any, services: Sequence[str], service_ref: str) -> Tuple[Any, Optional[str]]:
    """Resolve the plugin's ``service`` (``Service/Method`` or ``pkg.Service/Method``).

    Args:
        pool: The descriptor pool.
        services: Every fully-qualified service the descriptors declare.
        service_ref: The ``service`` value of the interaction's plugin configuration.

    Returns:
        ``(method descriptor, None)`` or ``(None, why)``.
    """
    service_name, _, method_name = service_ref.strip().lstrip("/").partition("/")
    if not service_name or not method_name:
        return None, f"the plugin's service '{service_ref}' is not of the form Service/Method"
    candidates = (
        [service_name] if service_name in services else [name for name in services if name.endswith(f".{service_name}")]
    )
    if len(candidates) != 1:
        what = "declare no service" if not candidates else f"declare several ({', '.join(candidates)})"
        return None, f"the pact's descriptors {what} named '{service_name}'"
    service = pool.FindServiceByName(candidates[0])
    method = service.methods_by_name.get(method_name)
    if method is None:
        return None, f"the service '{service.full_name}' declares no method '{method_name}'"
    return method, None


def _idempotency(method: Any) -> str:
    """The method's ``idempotency_level`` label."""
    options = method.GetOptions()
    level = getattr(options, "idempotency_level", 0) if options is not None else 0
    return _IDEMPOTENCY_LABELS.get(int(level), "unknown")


def _content_bytes(contents: Mapping[str, Any]) -> Tuple[Optional[bytes], Optional[str]]:
    """The raw bytes of a plugin ``contents`` block.

    Args:
        contents: ``{"content": …, "encoded": "base64", "contentType": …}``.

    Returns:
        ``(bytes, None)`` — empty for an absent or empty content — or ``(None, why)``.
    """
    content = contents.get("content")
    if content is None or content == "":
        return b"", None
    if not isinstance(content, str):
        return None, "the content is not a string"
    encoded = contents.get("encoded")
    if isinstance(encoded, str) and encoded.strip().lower() == "base64":
        try:
            return base64.b64decode(content, validate=True), None
        except (binascii.Error, ValueError):
            return None, "the base64 content does not decode"
    return content.encode("utf-8"), None


def _declared_message(contents: Mapping[str, Any]) -> Optional[str]:
    """The message type a content type names (``application/protobuf;message=.pkg.Shape``)."""
    raw = contents.get("contentType")
    if not isinstance(raw, str):
        return None
    for part in raw.split(";")[1:]:
        name, _, value = part.strip().partition("=")
        if name.strip().lower() == "message" and value.strip():
            return value.strip().lstrip(".")
    return None


def _decode(descriptor: Any, contents: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Decode a plugin ``contents`` block as ``descriptor`` and print it as protobuf-JSON.

    Args:
        descriptor: The message descriptor the content must be.
        contents: The plugin's ``contents`` block.

    Returns:
        ``(message, None)`` or ``(None, why)``.
    """
    from google.protobuf import json_format, message_factory

    declared = _declared_message(contents)
    if declared and declared != descriptor.full_name and not descriptor.full_name.endswith(f".{declared}"):
        return None, f"its content type names the message '{declared}', but the method takes '{descriptor.full_name}'"
    data, problem = _content_bytes(contents)
    if problem or data is None:
        return None, problem or "the content is missing"
    message = message_factory.GetMessageClass(descriptor)()
    try:
        message.ParseFromString(data)
    except Exception as exc:  # noqa: BLE001 - undecodable bytes are a finding
        return None, f"the content does not decode as '{descriptor.full_name}': {exc}"
    return json_format.MessageToDict(message), None


def _extra_metadata(metadata: Mapping[str, Any]) -> List[str]:
    """Metadata keys beyond the ones that describe the call itself, sorted."""
    return sorted(str(key) for key in metadata if str(key).strip().lower() not in _CALL_METADATA)


def read_grpc_interaction(
    interaction: Mapping[str, Any], pointer: str, catalog: DescriptorCatalog
) -> Tuple[Optional[GrpcPluginCall], Optional[GrpcPluginProblem]]:
    """Read a protobuf-plugin interaction onto a unary call and its expected reply.

    Args:
        interaction: The interaction (:func:`is_grpc_plugin_interaction` holds).
        pointer: Its JSON Pointer in the pact.
        catalog: The pact's descriptors.

    Returns:
        ``(call, None)`` or ``(None, problem)``.
    """
    configuration = as_dict(as_dict(interaction.get("pluginConfiguration")).get(PROTOBUF_PLUGIN))
    key = configuration.get("descriptorKey")
    service_ref = configuration.get("service")
    if not isinstance(key, str) or not key.strip():
        return None, GrpcPluginProblem(CODE_GRPC_DESCRIPTORS_MISSING, "the plugin configuration names no descriptorKey")
    pool, services, why = catalog.pool(key.strip())
    if pool is None:
        return None, GrpcPluginProblem(CODE_GRPC_DESCRIPTORS_MISSING, why or "no descriptors")
    if not isinstance(service_ref, str) or not service_ref.strip():
        return None, GrpcPluginProblem(CODE_GRPC_METHOD_NOT_FOUND, "the plugin configuration names no service")
    method, why = _find_method(pool, services, service_ref)
    if method is None:
        return None, GrpcPluginProblem(CODE_GRPC_METHOD_NOT_FOUND, why or "no method")
    if method.client_streaming or method.server_streaming:
        return None, GrpcPluginProblem(
            CODE_GRPC_STREAMING,
            f"'{method.containing_service.full_name}/{method.name}' is a streaming method; a unary "
            "replay cannot express a stream",
        )

    notes: List[Tuple[str, str]] = []
    request = as_dict(interaction.get("request"))
    message, why = _decode(method.input_type, as_dict(request.get("contents")))
    if message is None:
        return None, GrpcPluginProblem(CODE_GRPC_CONTENT_UNREADABLE, f"the request cannot be sent: {why}")
    extra = _extra_metadata(as_dict(request.get("metadata")))
    if extra:
        notes.append(
            (
                f"{pointer}/request/metadata",
                f"the request metadata {', '.join(extra)} is not sent; only the target's own "
                "credentials travel as call metadata",
            )
        )

    responses = interaction.get("response")
    listed = responses if isinstance(responses, list) else [responses] if isinstance(responses, dict) else []
    if len(listed) > 1:
        notes.append(
            (
                f"{pointer}/response",
                f"the interaction records {len(listed)} responses; a unary call has one, so only the "
                "first is compared",
            )
        )
    response = as_dict(listed[0]) if listed else {}
    response_pointer = f"{pointer}/response/0" if isinstance(responses, list) else f"{pointer}/response"
    metadata = as_dict(response.get("metadata"))
    status_value = next((metadata[k] for k in metadata if str(k).lower() == "grpc-status"), None)
    expect_code = "ok"
    if status_value is not None:
        expect_code = grpc_status_code(status_value) or "ok"
        if grpc_status_code(status_value) is None:
            notes.append(
                (
                    f"{response_pointer}/metadata",
                    f"the recorded grpc-status {status_value!r} names no gRPC status; `ok` is expected",
                )
            )
    message_value = next((metadata[k] for k in metadata if str(k).lower() == "grpc-message"), None)
    extra = _extra_metadata(metadata)
    if extra:
        notes.append(
            (
                f"{response_pointer}/metadata",
                f"the response metadata {', '.join(extra)} is not compared; only the status and " "the message are",
            )
        )

    contents = as_dict(response.get("contents"))
    body: Optional[Dict[str, Any]] = None
    has_body = expect_code == "ok" and bool(contents)
    if has_body:
        body, why = _decode(method.output_type, contents)
        if body is None:
            return None, GrpcPluginProblem(
                CODE_GRPC_CONTENT_UNREADABLE, f"the expected response cannot be compared: {why}"
            )
    service = method.containing_service.full_name
    return (
        GrpcPluginCall(
            service=service,
            method=method.name,
            procedure=f"/{service}/{method.name}",
            input_type=method.input_type.full_name,
            output_type=method.output_type.full_name,
            idempotency_level=_idempotency(method),
            message=message,
            expect_code=expect_code,
            expect_message=str(message_value) if isinstance(message_value, (str, int)) else None,
            has_body=has_body,
            body=body,
            response_pointer=response_pointer,
            output_descriptor=method.output_type,
            notes=notes,
        ),
        None,
    )


#: ``FieldDescriptor`` types protobuf-JSON prints as decimal strings (``"1200"``).
_INT64_TYPES = frozenset({3, 4, 6, 16, 18})  # INT64, UINT64, FIXED64, SFIXED64, SINT64

#: Numeric matchers that cannot hold for a decimal string, and what an int64 field gets instead.
_NUMERIC_MATCHERS = frozenset({"integer", "number"})
#: A protobuf-JSON 64-bit integer: an optionally signed run of digits.
INT64_PATTERN = r"^-?\d+$"


def rename_rule_path(steps: Sequence[Any], descriptor: Any) -> Tuple[Optional[str], bool]:
    """Rewrite a parsed rule path from ``.proto`` field names to protobuf-JSON names.

    ``$.shape_area.square_metres`` becomes ``$.shapeArea.squareMetres``. A repeated field takes
    an index or ``[*]`` after it; a map field takes a key (or ``*``) and continues in the value
    type. A field already written with its JSON name is kept.

    Args:
        steps: The path as :func:`app.pact_matching_rules.parse_path` returns it (``str``
            properties, ``int`` indexes, ``None`` for "any").
        descriptor: The message descriptor the path starts in.

    Returns:
        ``(path, int64)`` — the rewritten JSONPath (``None`` when a step names no field of the
        message it is in; the rule is then carried under its own path), and whether it ends on a
        64-bit integer field, which protobuf-JSON prints as a decimal string.
    """
    out = "$"
    current = descriptor
    leaf: Any = None
    position = 0
    while position < len(steps):
        step = steps[position]
        if current is None:
            out += _render_step(step)
            position += 1
            leaf = None
            continue
        if not isinstance(step, str):
            return None, False
        found = current.fields_by_name.get(step) or next(
            (item for item in current.fields if item.json_name == step), None
        )
        if found is None:
            return None, False
        out += _render_step(found.json_name)
        position += 1
        current, leaf = found.message_type, found
        if _is_map(found):
            value_field = found.message_type.fields_by_name["value"]
            if position < len(steps):
                out += _render_step(steps[position])
                position += 1
                leaf = value_field
            current = value_field.message_type
        elif _is_repeated(found) and position < len(steps) and not isinstance(steps[position], str):
            out += _render_step(steps[position])
            position += 1
    return out, bool(leaf is not None and position == len(steps) and leaf.type in _INT64_TYPES)


def int64_matcher(match: str, matcher: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The matcher an ``integer`` / ``number`` rule on a 64-bit integer field is applied as.

    Protobuf-JSON prints ``int64`` and its kin as decimal strings, so a numeric matcher would
    fail every conforming reply; it is applied as a regex over the digits instead.

    Args:
        match: The rule's matcher, lowercase.
        matcher: The matcher object as the pact wrote it.

    Returns:
        The replacement matcher object, or ``None`` when ``match`` is not a numeric matcher.
    """
    if match not in _NUMERIC_MATCHERS:
        return None
    return {**dict(matcher), "match": "regex", "regex": INT64_PATTERN}


def _is_repeated(field_descriptor: Any) -> bool:
    """Whether a field is ``repeated`` (maps included)."""
    is_repeated = getattr(field_descriptor, "is_repeated", None)
    if isinstance(is_repeated, bool):
        return is_repeated
    return field_descriptor.label == field_descriptor.LABEL_REPEATED


def _is_map(field_descriptor: Any) -> bool:
    """Whether a field is a protobuf ``map``."""
    message = field_descriptor.message_type
    return bool(_is_repeated(field_descriptor) and message is not None and message.GetOptions().map_entry)


def _render_step(step: Any) -> str:
    """Render one path step back to JSONPath."""
    if step is None:
        return "[*]"
    if isinstance(step, int):
        return f"[{step}]"
    text = str(step)
    if text and all(ch.isalnum() or ch in "_-" for ch in text):
        return f".{text}"
    escaped = text.replace("\\", "\\\\").replace("'", "\\'")
    return f"['{escaped}']"
