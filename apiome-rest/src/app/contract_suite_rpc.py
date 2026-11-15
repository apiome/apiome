"""The gRPC/Connect protocol adapter of the contract-suite compiler — XPC-3.2 (#5742).

A Protobuf version normalizes to services keyed ``package.Service`` whose operations are the
methods (``acme.orders.v1.Orders.GetOrder``), each with one request and one response message
referencing the mapped message types (see :mod:`app.proto_normalizer`). This adapter compiles
every **unary** method into cases a runner executes as one call of
``/{package.Service}/{Method}`` — over the Connect protocol (a JSON ``POST`` through the HTTP
runner) or over a native gRPC channel, whichever the verification target declares. The cases are
the same either way; only the transport differs.

What an RPC case is
-------------------
One request message in its **protobuf-JSON** form — field JSON names (``orderId`` for
``order_id``), enums by name, bytes as base64 — and the status code a conforming server answers
with. Cases are built in the order every adapter uses:

1. **Declared example message** — an ``example`` (or the first of ``examples``) in the request
   message's or the input type's ``extras``. Protobuf has no example syntax of its own, so this
   is present only when an importer recorded one; an example that does not satisfy the request
   schema is reported and left out.
2. **Schema-valid generated messages** — the required fields only, then every field, seeded
   through :mod:`app.schema_instance_synthesis` from a JSON Schema built for the input type
   (``int32`` bounded to 32 bits, nested messages as ``$defs``, one member per ``oneof``).
3. **Negative cases** — each required field omitted, one field given a value of the wrong JSON
   type, and an unknown field added. A field is *required* when proto2 declares it ``required``
   or an Editions file resolves it ``LEGACY_REQUIRED`` (XPC-3.3 adds Protovalidate rules later).
   The last two only the JSON encoding can express — binary protobuf has no way to carry a
   wrong-typed or an unknown *named* field — so they are marked ``json_only`` and a native gRPC
   run records them as skipped.

The response contract
---------------------
A success case expects status ``ok`` and a response message that satisfies a schema built from
the output type, registered under ``rpc:<operation key>``: every declared field allowed under its
JSON name (or its original proto name, which protobuf-JSON printers may also emit), nothing else,
and proto2-required fields present. Protobuf-JSON omits fields holding their default value, so a
proto3 field is never required. The schema is lenient exactly where protobuf-JSON is — a 64-bit
integer may be a number or a decimal string, an enum a name or a number, a float ``"NaN"`` — so a
conforming printer never fails it, and every violation is located by a JSON Pointer into the
message (``/order/total``).

A negative case expects ``invalid_argument`` (HTTP 400 over Connect). Methods are mutating unless
the method declares ``idempotency_level = NO_SIDE_EFFECTS``, so the target's mutating-method gate
holds back everything else. Streaming methods are listed under the manifest's ``unsupported``
with the reason ``unsupported: streaming``.

This module is pure and deterministic, like :mod:`app.contract_suite`, whose models, finding
vocabulary, operation selection and seeding it shares.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .canonical_model import (
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .contract_protocols import PROTOCOL_GRPC
from .contract_suite import (
    CASE_SOURCE_DECLARED_EXAMPLE,
    CASE_SOURCE_GENERATED_FULL,
    CASE_SOURCE_GENERATED_MINIMAL,
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
    CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    CODE_EXAMPLE_SCHEMA_MISMATCH,
    CODE_GENERATION_LIMITED,
    CODE_NO_CASES_COMPILED,
    CODE_NO_NEGATIVE_CASES,
    CODE_UNRESOLVED_PAYLOAD_TYPE,
    CODE_UNSUPPORTED_STREAMING,
    DEFAULT_MEDIA_TYPE,
    FINDING_DEGRADED,
    FINDING_UNSUPPORTED,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    WRONG_TYPE_PARAMETER_VALUE,
    ContractCase,
    ContractCaseExpectation,
    ContractCaseRequest,
    ContractRpcRequest,
    SuiteOperation,
    _case_id,
    _Compilation,
    _seed_for,
    _select_operations,
)
from .proto_editions import FIELD_PRESENCE_EXTRA_KEY, FIELD_PRESENCE_LEGACY_REQUIRED
from .schema_instance_synthesis import INSTANCE_FULL, INSTANCE_MINIMAL, synthesize_instances
from .schema_instance_validation import validate_json_instance
from .schema_validation import DRAFT_2020_12_META_URI

__all__ = [
    "IDEMPOTENCY_NO_SIDE_EFFECTS",
    "IDEMPOTENCY_UNKNOWN",
    "RPC_CODE_INVALID_ARGUMENT",
    "RPC_CODE_OK",
    "RPC_FORMATS",
    "RPC_SCHEMA_PREFIX",
    "UNKNOWN_FIELD_NAME",
    "compile_rpc_cases",
    "json_name",
    "procedure_path",
]

#: Canonical formats this adapter compiles. Other RPC formats (Smithy, Thrift, JSON-RPC) have no
#: Connect or gRPC wire form and keep falling through to the HTTP adapter's per-operation report.
RPC_FORMATS = frozenset({"protobuf"})

#: Prefix of the manifest ``schemas`` key a success case's response message is validated against.
RPC_SCHEMA_PREFIX = "rpc:"

#: Name of the field the unknown-field negative case adds. Suffixed with a number in the unlikely
#: event the input type declares a field of that JSON name.
UNKNOWN_FIELD_NAME = "apiomeUnknownField"

#: Status codes, in the lower-snake spelling Connect uses on the wire (gRPC's ``StatusCode`` names,
#: lower-cased).
RPC_CODE_OK = "ok"
RPC_CODE_INVALID_ARGUMENT = "invalid_argument"

#: The method option that makes a method safe to call against a target that forbids writes.
IDEMPOTENCY_NO_SIDE_EFFECTS = "no_side_effects"
#: What a method with no ``idempotency_level`` option records — the protobuf default.
IDEMPOTENCY_UNKNOWN = "unknown"

#: Schema modes. A *request* schema is what generated values are drawn from, so it is narrow
#: enough that every generated value is one any protobuf-JSON parser accepts. A *response* schema
#: is what a server's answer is judged against, so it is as wide as protobuf-JSON itself.
_MODE_REQUEST = "request"
_MODE_RESPONSE = "response"

_INT32 = {"type": "integer", "minimum": -(2**31), "maximum": 2**31 - 1}
_UINT32 = {"type": "integer", "minimum": 0, "maximum": 2**32 - 1}
_INT64_RESPONSE = {"type": ["integer", "string"], "pattern": "^-?[0-9]+$"}
_UINT64_RESPONSE = {"type": ["integer", "string"], "minimum": 0, "pattern": "^[0-9]+$"}
_FLOAT_RESPONSE = {"anyOf": [{"type": "number"}, {"enum": ["NaN", "Infinity", "-Infinity"]}]}
_BYTES_REQUEST = {"type": "string", "enum": ["YXBpb21l"]}  # base64 of "apiome"
_BYTES_RESPONSE = {"type": "string", "pattern": "^[A-Za-z0-9+/_-]*={0,2}$"}

#: Protobuf scalars → (request schema, response schema). A 64-bit integer is *generated* as a
#: 32-bit JSON number — valid for every parser — and *accepted* as a number or a decimal string,
#: the two forms protobuf-JSON allows.
_SCALARS: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {
    "double": ({"type": "number"}, _FLOAT_RESPONSE),
    "float": ({"type": "number"}, _FLOAT_RESPONSE),
    "int32": (_INT32, _INT32),
    "sint32": (_INT32, _INT32),
    "sfixed32": (_INT32, _INT32),
    "uint32": (_UINT32, _UINT32),
    "fixed32": (_UINT32, _UINT32),
    "int64": (_INT32, _INT64_RESPONSE),
    "sint64": (_INT32, _INT64_RESPONSE),
    "sfixed64": (_INT32, _INT64_RESPONSE),
    "uint64": (_UINT32, _UINT64_RESPONSE),
    "fixed64": (_UINT32, _UINT64_RESPONSE),
    "bool": ({"type": "boolean"}, {"type": "boolean"}),
    "string": ({"type": "string"}, {"type": "string"}),
    "bytes": (_BYTES_REQUEST, _BYTES_RESPONSE),
}

#: Well-known types, which live in an imported file and so never appear in ``api.types``, mapped
#: to their special protobuf-JSON forms as (request schema, response schema).
_WELL_KNOWN: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {
    "google.protobuf.Timestamp": (
        {"type": "string", "enum": ["2026-01-01T00:00:00Z"]},
        {"type": "string", "format": "date-time"},
    ),
    "google.protobuf.Duration": (
        {"type": "string", "enum": ["1s"]},
        {"type": "string", "pattern": "^-?[0-9]+(\\.[0-9]{1,9})?s$"},
    ),
    "google.protobuf.Empty": (
        {"type": "object", "additionalProperties": False},
        {"type": "object", "additionalProperties": False},
    ),
    "google.protobuf.Struct": ({"type": "object", "maxProperties": 0}, {"type": "object"}),
    "google.protobuf.Value": ({"type": "string"}, {}),
    "google.protobuf.ListValue": ({"type": "array", "maxItems": 0}, {"type": "array"}),
    "google.protobuf.NullValue": ({"type": "null"}, {"type": "null"}),
    "google.protobuf.FieldMask": ({"type": "string", "enum": [""]}, {"type": "string"}),
    "google.protobuf.Any": (
        {
            "type": "object",
            "properties": {"@type": {"enum": ["type.googleapis.com/google.protobuf.Empty"]}},
            "required": ["@type"],
            "additionalProperties": False,
        },
        {"type": "object", "properties": {"@type": {"type": "string"}}, "required": ["@type"]},
    ),
    "google.protobuf.StringValue": ({"type": "string"}, {"type": "string"}),
    "google.protobuf.BytesValue": (_BYTES_REQUEST, _BYTES_RESPONSE),
    "google.protobuf.BoolValue": ({"type": "boolean"}, {"type": "boolean"}),
    "google.protobuf.Int32Value": (_INT32, _INT32),
    "google.protobuf.UInt32Value": (_UINT32, _UINT32),
    "google.protobuf.Int64Value": (_INT32, _INT64_RESPONSE),
    "google.protobuf.UInt64Value": (_UINT32, _UINT64_RESPONSE),
    "google.protobuf.FloatValue": ({"type": "number"}, _FLOAT_RESPONSE),
    "google.protobuf.DoubleValue": ({"type": "number"}, _FLOAT_RESPONSE),
}

#: Positions whose JSON form accepts any value, so no value is certain to be wrong for them.
_ACCEPTS_ANYTHING = frozenset({"google.protobuf.Value"})

#: Positions whose JSON form is a boolean: they take a string as their wrong value.
_BOOLEAN_POSITIONS = frozenset({"bool", "google.protobuf.BoolValue"})

#: Sentinel for "no value" (``None`` is a legitimate JSON value).
_MISSING = object()


# ===========================================================================
# Entry point
# ===========================================================================


def compile_rpc_cases(compilation: _Compilation) -> None:
    """The gRPC/Connect adapter: compile every unary method of a Protobuf version into cases.

    Args:
        compilation: The run state, filled in place.
    """
    selected, dropped = _select_operations(compilation)
    compilation.dropped += dropped
    types = _types_by_key(compilation.api)
    for service, operation in selected:
        _compile_method(compilation, types, service, operation)


def json_name(name: str) -> str:
    """Return a protobuf field's default JSON name, as ``protoc`` derives it.

    Underscores are dropped and the letter after each one is upper-cased: ``order_id`` →
    ``orderId``, ``line_items_2`` → ``lineItems2``. The canonical model keeps the source field
    name only, so the JSON name is re-derived the way every protobuf-JSON printer does by default.

    Args:
        name: The field's source name.

    Returns:
        The lowerCamel JSON name.
    """
    parts: List[str] = []
    upper_next = False
    for char in name:
        if char == "_":
            upper_next = True
            continue
        parts.append(char.upper() if upper_next else char)
        upper_next = False
    return "".join(parts)


def procedure_path(service_key: str, method: str) -> str:
    """Return the gRPC/Connect procedure path of a method: ``/{package.Service}/{Method}``.

    Args:
        service_key: The fully-qualified service name.
        method: The method name.

    Returns:
        The procedure path, which is also what a Connect target's ``base_url`` is joined with.
    """
    return f"/{service_key}/{method}"


# ===========================================================================
# Per-method compilation
# ===========================================================================


@dataclass
class _Method:
    """Everything one method's cases are built from, resolved once.

    Attributes:
        operation: The canonical method.
        service_key: Its fully-qualified service name.
        input_type: The request message type key.
        output_type: The response message type key.
        fields: The request message's declared fields, sorted by JSON name.
        request_schema: The request message's generation schema.
        minimal: A generated required-fields-only message, or :data:`_MISSING`.
        full: A generated every-field message, or :data:`_MISSING`.
        declared: The declared example message, or :data:`_MISSING`.
    """

    operation: Operation
    service_key: str
    input_type: str
    output_type: str
    fields: List[CanonicalField] = field(default_factory=list)
    request_schema: Dict[str, Any] = field(default_factory=dict)
    minimal: Any = _MISSING
    full: Any = _MISSING
    declared: Any = _MISSING

    @property
    def key(self) -> str:
        """The method's canonical operation key."""
        return self.operation.key

    @property
    def procedure(self) -> str:
        """The procedure path every case of this method calls."""
        return procedure_path(self.service_key, self.operation.name)

    @property
    def idempotency_level(self) -> str:
        """The method's ``idempotency_level`` label, ``unknown`` when it declares none."""
        level = self.operation.extras.get("idempotency_level")
        return str(level) if level else IDEMPOTENCY_UNKNOWN


def _compile_method(
    compilation: _Compilation,
    types: Mapping[str, Type],
    service: Service,
    operation: Operation,
) -> None:
    """Compile one method's cases, or report why none could be compiled.

    Args:
        compilation: The run state, mutated in place.
        types: The model's types by key.
        service: The service the method belongs to.
        operation: The method.
    """
    key = operation.key
    if operation.streaming is not StreamingMode.NONE:
        reason = (
            f"unsupported: streaming — {key!r} is a {operation.streaming.value}-streaming "
            "method, which a unary request/response case cannot express."
        )
        compilation.report(CODE_UNSUPPORTED_STREAMING, FINDING_UNSUPPORTED, reason, operation_key=key)
        compilation.mark_unsupported(key, CODE_UNSUPPORTED_STREAMING, reason)
        return

    input_ref = _payload(operation, MessageRole.REQUEST)
    output_ref = _payload(operation, MessageRole.RESPONSE)
    if input_ref is None or output_ref is None or not input_ref.name or not output_ref.name:
        compilation.report(
            CODE_UNRESOLVED_PAYLOAD_TYPE,
            FINDING_UNSUPPORTED,
            f"{key!r} declares no request or no response message type, so there is nothing to "
            "send or check.",
            operation_key=key,
        )
        compilation.skipped.append(key)
        return

    method = _Method(
        operation=operation,
        service_key=service.key or service.name,
        input_type=input_ref.name,
        output_type=output_ref.name,
    )
    request_builder = _SchemaBuilder(types, _MODE_REQUEST)
    method.request_schema = request_builder.document(input_ref)
    input_type = types.get(method.input_type)
    if input_type is not None and input_type.kind is TypeKind.RECORD:
        method.fields = sorted(input_type.fields, key=lambda item: json_name(item.name))
    method.minimal, method.full = _generate(compilation, method)
    if method.minimal is _MISSING:
        # An empty message is always a valid protobuf message; it is what a client sends when
        # it sets nothing, so it stands in when generation produced nothing usable.
        method.minimal = {}
    if method.full is _MISSING:
        method.full = method.minimal
    method.declared = _declared_example(compilation, method, operation, input_type)

    response_builder = _SchemaBuilder(types, _MODE_RESPONSE)
    response_schema = response_builder.document(output_ref)
    _report_unresolved(compilation, key, request_builder.unresolved + response_builder.unresolved)

    success = _success_expectation(compilation, method, response_schema)
    client_error = _error_expectation(method)

    before = len(compilation.cases)
    _emit_positive_cases(compilation, method, success)
    _emit_negative_cases(compilation, types, method, client_error)
    emitted = len(compilation.cases) - before

    if emitted == 0:
        compilation.report(
            CODE_NO_CASES_COMPILED,
            FINDING_UNSUPPORTED,
            f"No case could be compiled for {key!r} under these options, so the suite does "
            "not cover it.",
            operation_key=key,
        )
        compilation.skipped.append(key)
        return

    compilation.operations.append(
        SuiteOperation(
            key=key,
            name=operation.name,
            service_key=method.service_key,
            http_method="POST",
            http_path=method.procedure,
            deprecated=operation.deprecated,
            tags=list(operation.tags),
            case_count=emitted,
            request_media_type=DEFAULT_MEDIA_TYPE,
        )
    )


def _payload(operation: Operation, role: MessageRole) -> Optional[TypeRef]:
    """Return the payload type of a method's request or response message."""
    for message in operation.messages:
        if message.role is role and message.payload is not None:
            return message.payload
    return None


def _report_unresolved(compilation: _Compilation, key: str, unresolved: Sequence[str]) -> None:
    """Report message types the schemas could not see into, once per method."""
    names = sorted(set(unresolved))
    if not names:
        return
    compilation.report(
        CODE_UNRESOLVED_PAYLOAD_TYPE,
        FINDING_DEGRADED,
        f"{key!r} uses type(s) {', '.join(names)} that this version does not define (an import "
        "other than a well-known type); values at those positions are generated empty and "
        "validated against nothing.",
        operation_key=key,
    )


def _types_by_key(api: CanonicalApi) -> Dict[str, Type]:
    """Index a model's types by key — package-qualified names, which is how a ``TypeRef`` names them."""
    return {type_.key: type_ for type_ in api.types if type_.key}


# ===========================================================================
# Schemas — the protobuf-JSON view of a message type
# ===========================================================================


class _SchemaBuilder:
    """Projects message types into JSON Schema over their protobuf-JSON encoding.

    Message types are carried as ``$defs`` keyed by type key, so a recursive message (a tree
    node that holds its children) stays finite.

    Attributes:
        types: The model's types by key.
        mode: :data:`_MODE_REQUEST` or :data:`_MODE_RESPONSE`.
        defs: The ``$defs`` built so far.
        unresolved: Type names met that neither the model nor the well-known table defines.
    """

    def __init__(self, types: Mapping[str, Type], mode: str) -> None:
        self.types = types
        self.mode = mode
        self.defs: Dict[str, Dict[str, Any]] = {}
        self.unresolved: List[str] = []

    def document(self, ref: TypeRef) -> Dict[str, Any]:
        """Build the self-contained draft 2020-12 schema of one message type.

        Args:
            ref: The message type.

        Returns:
            The schema document, with every referenced message under ``$defs``.
        """
        root = self.position(ref)
        document: Dict[str, Any] = {"$schema": DRAFT_2020_12_META_URI, **root}
        if self.defs:
            document["$defs"] = {name: self.defs[name] for name in sorted(self.defs)}
        return document

    def position(self, ref: TypeRef) -> Dict[str, Any]:
        """Project one field position — a repeated wrapper or a named type — into JSON Schema."""
        if ref.item is not None:
            return {"type": "array", "items": self.position(ref.item)}
        return self.named(ref.name or "")

    def named(self, name: str) -> Dict[str, Any]:
        """Project one named type: a scalar, a well-known type, an enum, a map or a message."""
        index = 0 if self.mode == _MODE_REQUEST else 1
        if name in _SCALARS:
            return copy.deepcopy(_SCALARS[name][index])
        if name in _WELL_KNOWN:
            return copy.deepcopy(_WELL_KNOWN[name][index])
        type_ = self.types.get(name)
        if type_ is None:
            self.unresolved.append(name or "<unnamed>")
            return {} if self.mode == _MODE_RESPONSE else {"type": "object", "maxProperties": 0}
        if type_.kind is TypeKind.ENUM:
            names = [value.name for value in type_.enum_values]
            if self.mode == _MODE_REQUEST:
                return {"type": "string", "enum": names}
            return {"anyOf": [{"enum": names}, {"type": "integer"}]}
        if type_.kind is TypeKind.MAP:
            value = type_.value_type or TypeRef(name="string")
            schema: Dict[str, Any] = {
                "type": "object",
                "additionalProperties": self.position(value),
            }
            if self.mode == _MODE_REQUEST:
                schema["maxProperties"] = 1
            return schema
        if type_.kind is TypeKind.RECORD:
            if name not in self.defs:
                self.defs[name] = {}  # placeholder first, so a self-reference terminates
                self.defs[name] = self.record(type_)
            return {"$ref": f"#/$defs/{name}"}
        self.unresolved.append(name)
        return {}

    def record(self, type_: Type) -> Dict[str, Any]:
        """Project a message's fields: JSON names, required fields, nothing undeclared.

        A request schema keeps only the first member (by field number) of each ``oneof``, since
        a message may set at most one of them and the generator would otherwise set them all. A
        response schema allows every member, under its JSON name and its original name.
        """
        properties: Dict[str, Any] = {}
        required: List[str] = []
        oneofs_seen: set = set()
        ordered = sorted(type_.fields, key=lambda item: (item.field_number or 0, item.name))
        for member in ordered:
            oneof = member.extras.get("oneof")
            if self.mode == _MODE_REQUEST and oneof:
                if oneof in oneofs_seen:
                    continue
                oneofs_seen.add(oneof)
            name = json_name(member.name)
            schema = self.position(member.type)
            properties[name] = schema
            if self.mode == _MODE_RESPONSE and member.name != name:
                properties[member.name] = copy.deepcopy(schema)
            if is_required_field(member):
                required.append(name)
        return {
            "type": "object",
            "properties": {name: properties[name] for name in sorted(properties)},
            "required": sorted(required),
            "additionalProperties": False,
        }


def is_required_field(member: CanonicalField) -> bool:
    """Return whether a message field must be present in every valid message.

    Args:
        member: The field.

    Returns:
        ``True`` for a proto2 ``required`` field and an Editions ``LEGACY_REQUIRED`` one. A proto3
        field never is: protobuf-JSON omits a field holding its default value.
    """
    extras = member.extras
    return (
        extras.get("label") == "required"
        or extras.get(FIELD_PRESENCE_EXTRA_KEY) == FIELD_PRESENCE_LEGACY_REQUIRED
    )


# ===========================================================================
# Messages — generated, declared and wrong values
# ===========================================================================


def _generate(compilation: _Compilation, method: _Method) -> Tuple[Any, Any]:
    """Generate the required-fields-only and every-field request messages.

    Args:
        compilation: The run state (seed, findings).
        method: The method; its key seeds the generator.

    Returns:
        ``(minimal, full)``, either being :data:`_MISSING` when it could not be generated.
    """
    result = synthesize_instances(
        method.request_schema,
        seed=_seed_for(compilation.options.seed, f"{method.key}#request"),
        include_minimal=True,
        include_full=True,
        include_branches=False,
        include_mutants=False,
        verify=True,
    )
    for diagnostic in result.diagnostics:
        compilation.report(
            CODE_GENERATION_LIMITED,
            FINDING_DEGRADED,
            f"Generating the request message of {method.key!r} was limited: {diagnostic.message}",
            operation_key=method.key,
            pointer=diagnostic.pointer,
        )
    found = {instance.kind: instance.instance for instance in result.instances}
    minimal = found.get(INSTANCE_MINIMAL, _MISSING)
    full = found.get(INSTANCE_FULL, _MISSING)
    return (
        minimal if isinstance(minimal, dict) else _MISSING,
        full if isinstance(full, dict) else _MISSING,
    )


def _declared_example(
    compilation: _Compilation,
    method: _Method,
    operation: Operation,
    input_type: Optional[Type],
) -> Any:
    """Return the example request message an importer recorded, or :data:`_MISSING`.

    Read from the request :class:`~app.canonical_model.Message`'s ``extras`` first, then from the
    input type's: ``example``, then the first of ``examples``. A string holding a JSON object is
    decoded. An example that does not satisfy the request schema is reported and dropped, because
    a positive case built from it would fail for a reason the author did not intend.

    Args:
        compilation: The run state, for findings.
        method: The method being compiled.
        operation: The canonical method, for its request message.
        input_type: The request message type, when the model defines it.

    Returns:
        The example message, or :data:`_MISSING`.
    """
    request: Optional[Message] = next(
        (item for item in operation.messages if item.role is MessageRole.REQUEST), None
    )
    sources = [request.extras if request is not None else {}]
    if input_type is not None:
        sources.append(input_type.extras)
    for extras in sources:
        value = _example_value(extras)
        if value is _MISSING:
            continue
        if not isinstance(value, dict):
            break
        if not validate_json_instance(method.request_schema, value).valid:
            compilation.report(
                CODE_EXAMPLE_SCHEMA_MISMATCH,
                FINDING_DEGRADED,
                f"The declared example request message of {method.key!r} does not satisfy "
                f"{method.input_type!r}, so it was not compiled into a case.",
                operation_key=method.key,
            )
            return _MISSING
        return value
    return _MISSING


def _example_value(extras: Mapping[str, Any]) -> Any:
    """Read ``example`` or the first ``examples`` entry from an ``extras`` bag."""
    if "example" in extras:
        return _decode(extras["example"])
    examples = extras.get("examples")
    if isinstance(examples, list) and examples:
        return _decode(examples[0])
    return _MISSING


def _decode(value: Any) -> Any:
    """Decode a string that holds a JSON object; return anything else as is."""
    if isinstance(value, str) and value.strip()[:1] == "{":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _wrong_value(types: Mapping[str, Type], ref: TypeRef) -> Any:
    """Pick a JSON value a strict protobuf-JSON parser must reject for a field position.

    ``true`` is rejected everywhere except a boolean position, which gets a string instead; a
    repeated field rejects a non-array. ``google.protobuf.Value`` and types the model does not
    define accept anything as far as the suite can tell, so they have no wrong value.

    Args:
        types: The model's types by key.
        ref: The field's type.

    Returns:
        The wrong value, or :data:`_MISSING` when none is certain to be wrong.
    """
    if ref.item is not None:
        return True
    name = ref.name or ""
    if name in _BOOLEAN_POSITIONS:
        return WRONG_TYPE_PARAMETER_VALUE
    if name in _ACCEPTS_ANYTHING:
        return _MISSING
    if name in _SCALARS or name in _WELL_KNOWN or name in types:
        return True
    return _MISSING


def _unknown_field_name(fields: Sequence[CanonicalField]) -> str:
    """Return :data:`UNKNOWN_FIELD_NAME`, suffixed until the message does not declare it."""
    taken = {json_name(item.name) for item in fields} | {item.name for item in fields}
    candidate = UNKNOWN_FIELD_NAME
    suffix = 1
    while candidate in taken:
        suffix += 1
        candidate = f"{UNKNOWN_FIELD_NAME}{suffix}"
    return candidate


# ===========================================================================
# Expectations
# ===========================================================================


def _success_expectation(
    compilation: _Compilation, method: _Method, response_schema: Dict[str, Any]
) -> ContractCaseExpectation:
    """Build what a positive case asserts: status ``ok`` and a response matching the output type.

    Args:
        compilation: The run state; the response schema is registered on it.
        method: The method.
        response_schema: The output message's response schema.

    Returns:
        The expectation.
    """
    schema_id: Optional[str] = None
    if compilation.options.include_response_schemas:
        schema_id = RPC_SCHEMA_PREFIX + method.key
        compilation.schemas.setdefault(schema_id, response_schema)
    return ContractCaseExpectation(
        outcome=OUTCOME_SUCCESS,
        status_codes=["200"],
        status_declared=False,
        response_schema_id=schema_id,
        reason=(
            f"A valid request is answered with status `ok` (HTTP 200 over Connect) and a "
            f"message that decodes as {method.output_type!r}."
        ),
    )


def _error_expectation(method: _Method) -> ContractCaseExpectation:
    """Build what a negative case asserts: status ``invalid_argument``."""
    return ContractCaseExpectation(
        outcome=OUTCOME_CLIENT_ERROR,
        status_codes=["400"],
        status_declared=False,
        response_schema_id=None,
        reason=(
            f"The request is not a valid {method.input_type!r}, so a conforming server answers "
            "with status `invalid_argument` (HTTP 400 over Connect)."
        ),
    )


# ===========================================================================
# Case emission
# ===========================================================================


def _case(
    method: _Method,
    *,
    source: str,
    source_detail: Optional[str],
    title: str,
    description: str,
    synthetic: bool,
    message: Dict[str, Any],
    expectation: ContractCaseExpectation,
    json_only: bool = False,
) -> ContractCase:
    """Assemble one RPC case, deriving its stable id from what makes it distinct.

    Args:
        method: The method.
        source: The case source.
        source_detail: What distinguishes the case within its source.
        title: Short human-readable name.
        description: What the case exercises.
        synthetic: ``False`` only when the message is the author's declared example.
        message: The request message, protobuf-JSON.
        expectation: What must come back.
        json_only: Whether only the JSON encoding can express the case.

    Returns:
        The assembled :class:`ContractCase`.
    """
    expect_code = (
        RPC_CODE_OK if expectation.outcome == OUTCOME_SUCCESS else RPC_CODE_INVALID_ARGUMENT
    )
    operation = method.operation
    return ContractCase(
        case_id=_case_id(operation.key, source, source_detail, None, title),
        operation_key=operation.key,
        operation_name=operation.name,
        source=source,
        source_detail=source_detail,
        source_pointer=None,
        title=title,
        description=description,
        synthetic=synthetic,
        protocol=PROTOCOL_GRPC,
        request=ContractCaseRequest(
            method="POST",
            path_template=method.procedure,
            path=method.procedure,
            parameters=[],
            has_body=True,
            body=message,
            media_type=DEFAULT_MEDIA_TYPE,
        ),
        rpc=ContractRpcRequest(
            service=method.service_key,
            method=operation.name,
            procedure=method.procedure,
            input_type=method.input_type,
            output_type=method.output_type,
            message=message,
            idempotency_level=method.idempotency_level,
            expect_code=expect_code,
            json_only=json_only,
        ),
        expect=expectation,
        tags=list(operation.tags),
    )


def _emit_positive_cases(
    compilation: _Compilation, method: _Method, expectation: ContractCaseExpectation
) -> None:
    """Emit the calls a conforming server must answer ``ok``: declared, then generated messages.

    Args:
        compilation: The run state.
        method: The method.
        expectation: The success expectation.
    """
    options = compilation.options
    if options.include_declared_examples and method.declared is not _MISSING:
        compilation.cases.append(
            _case(
                method,
                source=CASE_SOURCE_DECLARED_EXAMPLE,
                source_detail="example",
                title="declared example message",
                description=(
                    "Calls the method with the example request message the contract declares. "
                    "An example the author wrote is the strongest evidence of intent."
                ),
                synthetic=False,
                message=copy.deepcopy(method.declared),
                expectation=expectation,
            )
        )

    if not options.include_generated:
        return
    has_required = any(is_required_field(item) for item in method.fields)
    compilation.cases.append(
        _case(
            method,
            source=CASE_SOURCE_GENERATED_MINIMAL,
            source_detail=None,
            title="required fields only" if has_required else "empty message",
            description=(
                "Calls the method with a schema-valid generated message that sets its required "
                "fields only." if has_required else "Calls the method with an empty message."
            ),
            synthetic=True,
            message=copy.deepcopy(method.minimal),
            expectation=expectation,
        )
    )
    if options.max_generated_cases_per_operation >= 2 and method.full != method.minimal:
        compilation.cases.append(
            _case(
                method,
                source=CASE_SOURCE_GENERATED_FULL,
                source_detail=None,
                title="every field",
                description=(
                    "Calls the method with a schema-valid generated message that sets every "
                    "field (one member of each `oneof`)."
                ),
                synthetic=True,
                message=copy.deepcopy(method.full),
                expectation=expectation,
            )
        )


def _emit_negative_cases(
    compilation: _Compilation,
    types: Mapping[str, Type],
    method: _Method,
    expectation: ContractCaseExpectation,
) -> None:
    """Emit the calls a conforming server must answer ``invalid_argument``.

    In order, within ``max_negative_cases_per_operation``: each required field omitted, one field
    given a wrong-typed value, and an unknown field added. Every one isolates a single fault: the
    rest of the message is the valid required-fields-only one.

    Args:
        compilation: The run state.
        types: The model's types by key.
        method: The method.
        expectation: The client-error expectation.
    """
    if not compilation.options.include_negative:
        return
    budget = compilation.options.max_negative_cases_per_operation
    emitted = 0

    for member in method.fields:
        if emitted >= budget:
            break
        if not is_required_field(member):
            continue
        name = json_name(member.name)
        message = copy.deepcopy(method.minimal)
        message.pop(name, None)
        message.pop(member.name, None)
        compilation.cases.append(
            _case(
                method,
                source=CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
                source_detail=name,
                title=f"required field '{name}' omitted",
                description=(
                    f"Leaves the required field {member.name!r} out of the message. A conforming "
                    "server refuses a message that is not fully initialized."
                ),
                synthetic=True,
                message=message,
                expectation=expectation,
            )
        )
        emitted += 1

    typed = next(
        (
            item
            for item in sorted(
                method.fields, key=lambda item: (not is_required_field(item), json_name(item.name))
            )
            if _wrong_value(types, item.type) is not _MISSING
        ),
        None,
    )
    if typed is not None and emitted < budget:
        name = json_name(typed.name)
        wrong = _wrong_value(types, typed.type)
        message = copy.deepcopy(method.minimal)
        message[name] = wrong
        compilation.cases.append(
            _case(
                method,
                source=CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
                source_detail=name,
                title=f"field '{name}' with a wrong-typed value",
                description=(
                    f"Sends {wrong!r} for {typed.name!r}, which protobuf-JSON cannot parse into "
                    "the field's type. A conforming server rejects the message."
                ),
                synthetic=True,
                message=message,
                expectation=expectation,
                json_only=True,
            )
        )
        emitted += 1

    if emitted < budget:
        unknown = _unknown_field_name(method.fields)
        message = copy.deepcopy(method.minimal)
        message[unknown] = "x"
        compilation.cases.append(
            _case(
                method,
                source=CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
                source_detail=unknown,
                title=f"unknown field '{unknown}' set",
                description=(
                    f"Adds {unknown!r}, which {method.input_type!r} does not declare. A server "
                    "parsing protobuf-JSON strictly rejects the message."
                ),
                synthetic=True,
                message=message,
                expectation=expectation,
                json_only=True,
            )
        )
        emitted += 1

    if emitted == 0:
        compilation.report(
            CODE_NO_NEGATIVE_CASES,
            FINDING_DEGRADED,
            f"No negative case could be compiled for {method.key!r} within "
            "`max_negative_cases_per_operation`.",
            operation_key=method.key,
        )
