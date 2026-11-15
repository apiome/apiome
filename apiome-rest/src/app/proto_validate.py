"""Protovalidate (``buf.validate``) rules ↔ canonical constraints — XPC-3.3 (#5743).

`Protovalidate <https://protovalidate.com/reference/rules/>`_ is where modern protobuf APIs
declare required fields, ranges and patterns: options on fields, messages and oneofs under the
``buf.validate`` extensions (number 1159 on each). This module is the one place that reads those
options and writes them back, so the normalizer and the emitter cannot drift apart — the
**symmetry rule**: every canonical constraint :func:`read_field_rules` produces,
:func:`render_field_options` writes.

**Reading.** A compiled descriptor set carries the options as *unknown fields* of
``google.protobuf.FieldOptions`` (the Python runtime does not know the extension), so each
options message is re-parsed against a private descriptor pool holding the vendored
``buf/validate/validate.proto`` (compiled once to ``validate.binpb`` beside it). The standard
rules then land in two places:

* a rule with a JSON-Schema analogue fills the named :class:`~app.canonical_model.Constraints`
  facet the OpenAPI normalizer already fills (the table below), so the JSON Schema projection,
  the contract suite and every emitter see it with no code of their own;
* every other standard rule (``string.prefix``, ``enum.defined_only``, ``timestamp.gt_now``,
  ``repeated.items``, …) is kept verbatim, in its protobuf-JSON form, under
  ``Constraints.extras['protovalidate']`` — the bag the canonical model reserves for
  "constraints with no JSON-Schema analogue".

=====================================  ==============================================
Protovalidate rule                     Canonical constraint
=====================================  ==============================================
``required``                           ``TypeRef.nullable = False`` (+ the
                                       ``protovalidate_required`` field extra)
``string.min_len`` / ``max_len``       ``min_length`` / ``max_length``
``string.len``                         ``min_length`` = ``max_length``
``string.pattern``                     ``pattern``
``string.const`` / ``string.in``       ``enum``
``string.email`` / ``hostname`` /      ``format`` (``email``, ``hostname``, ``ipv4``,
``ipv4`` / ``ipv6`` / ``uri`` /        ``ipv6``, ``uri``, ``uri-reference``, ``uuid``)
``uri_ref`` / ``uuid``
numeric ``gte`` / ``gt``               ``minimum`` / ``exclusive_minimum``
numeric ``lte`` / ``lt``               ``maximum`` / ``exclusive_maximum``
numeric ``const`` / ``in``             ``enum``
``bool.const``                         ``enum``
``repeated.min_items`` / ``max_items``  ``min_items`` / ``max_items``
``repeated.unique``                    ``unique_items``
``(buf.validate.oneof).required``      the type's ``oneofs_required`` extra
anything else                          ``extras['protovalidate']`` (verbatim)
=====================================  ==============================================

A field marked ``ignore = IGNORE_ALWAYS`` has its rules switched off, so its whole option stays
verbatim and nothing is mapped. (``IGNORE_IF_ZERO_VALUE`` is mapped: protobuf-JSON omits a field
holding its zero value, which is exactly the case the rules then skip.)

A numeric bound stays verbatim rather than being mapped when a canonical ``float`` cannot hold
it exactly (a 64-bit integer beyond 2**53, ``NaN``, an infinity) or when the range is
*reversed* (``gt`` above ``lt`` — Protovalidate's spelling of "outside this range", which
JSON Schema's ``minimum``/``maximum`` would turn into an unsatisfiable one).

**CEL is never evaluated.** A ``cel`` rule, a ``cel_expression`` and ``message.cel`` are kept
verbatim (so a ``.proto`` export writes them back) and :func:`unsupported_constraints` lists
each one as an ``unsupported_constraint`` entry with the expression text — the record the
normalizer publishes for the import coverage ledger. A rule this reader does not know (a
*predefined* rule, which is a user-declared extension backed by CEL, or a field from another
``validate.proto`` version) cannot be carried at all and is listed the same way.

**Writing.** :func:`render_field_options` rebuilds a ``buf.validate.FieldRules`` message from a
canonical field — the verbatim rules first, then the named facets under the rule family of the
field's emitted type — and prints it as ``(buf.validate.field).…`` option assignments. A facet
with no standard rule for that type (``multiple_of``, a ``date-time`` format) is returned as
*unwritten* so the emitter can say so.
"""

from __future__ import annotations

import functools
import io
import math
import os
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
    duration_pb2,
    field_mask_pb2,
    json_format,
    message_factory,
    text_format,
    timestamp_pb2,
    unknown_fields,
)
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message import DecodeError, Message

from .canonical_model import CanonicalField, Constraints, Type

__all__ = [
    "FIELD_OPTION",
    "MESSAGE_OPTION",
    "ONEOF_OPTION",
    "ONEOFS_REQUIRED_EXTRA_KEY",
    "PROTOVALIDATE_EXTRA_KEY",
    "PROTOVALIDATE_IMPORT",
    "PROTOVALIDATE_REQUIRED_EXTRA_KEY",
    "PROTOVALIDATE_UNRECOGNIZED_EXTRA_KEY",
    "RULE_FAMILIES",
    "UNSUPPORTED_CONSTRAINT_KIND",
    "FieldRuleReading",
    "MessageRuleReading",
    "RenderedFieldRules",
    "UnsupportedRule",
    "has_protovalidate_rules",
    "is_protovalidate_required",
    "read_field_rules",
    "read_message_rules",
    "read_oneof_required",
    "render_field_options",
    "render_message_options",
    "rules_family_for_scalar",
    "unprojected_rules",
    "unsupported_constraints",
    "verbatim_rule_names",
    "verbatim_rules",
]

#: The import a ``.proto`` needs before it may set a ``buf.validate`` option.
PROTOVALIDATE_IMPORT = "buf/validate/validate.proto"

#: Key of the verbatim-rules bag: on ``Constraints.extras`` (field rules with no named facet),
#: on a RECORD ``Type.extras`` (message rules) and on ``CanonicalApi.extras`` (the import record
#: holding the ``unsupported_constraint`` entries).
PROTOVALIDATE_EXTRA_KEY = "protovalidate"

#: ``CanonicalField.extras`` flag for a field declared ``(buf.validate.field).required``. The
#: canonical spelling of "required" is ``TypeRef.nullable = False``; this flag is what tells the
#: emitter the non-nullability came from a Protovalidate rule it must write back, rather than
#: from a proto2 ``required`` label or another format's ``required`` list.
PROTOVALIDATE_REQUIRED_EXTRA_KEY = "protovalidate_required"

#: ``CanonicalField.extras`` / ``Type.extras`` key listing the paths of the rules the reader did
#: not recognize (a predefined rule, a rule of another ``validate.proto`` version). They are
#: reported as ``unsupported_constraint`` and are not written back.
PROTOVALIDATE_UNRECOGNIZED_EXTRA_KEY = "protovalidate_unrecognized"

#: RECORD ``Type.extras`` key listing the ``oneof`` names declared
#: ``(buf.validate.oneof).required`` — exactly one member must be set.
ONEOFS_REQUIRED_EXTRA_KEY = "oneofs_required"

#: The ledger kind of a rule that is preserved or dropped but never enforced (CEL, predefined).
UNSUPPORTED_CONSTRAINT_KIND = "unsupported_constraint"

#: The option names, as written in ``.proto`` source.
FIELD_OPTION = "(buf.validate.field)"
MESSAGE_OPTION = "(buf.validate.message)"
ONEOF_OPTION = "(buf.validate.oneof)"

#: The compiled twin of the vendored ``validate.proto`` (``buf build --exclude-imports
#: --exclude-source-info``). ``tests/test_proto_validate.py`` rebuilds it with the bundled
#: ``buf`` and fails when the two drift.
_DESCRIPTOR_PATH = os.path.join(
    os.path.dirname(__file__), "data", "proto_vendor", "buf", "validate", "validate.binpb"
)

#: Numeric rule families — one per protobuf numeric scalar, each with the same rule names.
_INTEGER_FAMILIES = frozenset(
    {
        "int32",
        "int64",
        "uint32",
        "uint64",
        "sint32",
        "sint64",
        "fixed32",
        "fixed64",
        "sfixed32",
        "sfixed64",
    }
)
_FLOAT_FAMILIES = frozenset({"float", "double"})
_NUMERIC_FAMILIES = _INTEGER_FAMILIES | _FLOAT_FAMILIES

#: Every rule family of ``FieldRules`` (its ``type`` oneof). The numeric families, ``string``,
#: ``bool`` and ``repeated`` have rules mapped onto named canonical facets; the rest (``enum``,
#: ``bytes``, ``map``, ``any``, ``duration``, ``field_mask``, ``timestamp``) are carried verbatim
#: only. The fixture suite asserts every family here against a fixture and against the vendored
#: ``validate.proto``, so none can claim support without one.
RULE_FAMILIES: Tuple[str, ...] = (
    "float",
    "double",
    "int32",
    "int64",
    "uint32",
    "uint64",
    "sint32",
    "sint64",
    "fixed32",
    "fixed64",
    "sfixed32",
    "sfixed64",
    "bool",
    "string",
    "bytes",
    "enum",
    "repeated",
    "map",
    "any",
    "duration",
    "field_mask",
    "timestamp",
)

#: ``string`` well-known rules ↔ the JSON-Schema ``format`` that means the same thing. The
#: other well-known rules (``ip``, ``address``, ``tuuid``, ``host_and_port``, …) have no
#: standard ``format`` and stay verbatim.
_STRING_FORMAT_RULES: Tuple[Tuple[str, str], ...] = (
    ("email", "email"),
    ("hostname", "hostname"),
    ("ipv4", "ipv4"),
    ("ipv6", "ipv6"),
    ("uri", "uri"),
    ("uri_ref", "uri-reference"),
    ("uuid", "uuid"),
)

#: Lower/upper bound rules ↔ canonical facets: ``(rule, facet)``.
_LOWER_BOUNDS: Tuple[Tuple[str, str], ...] = (("gte", "minimum"), ("gt", "exclusive_minimum"))
_UPPER_BOUNDS: Tuple[Tuple[str, str], ...] = (("lte", "maximum"), ("lt", "exclusive_maximum"))

#: ``buf.validate.Ignore.IGNORE_ALWAYS``: the field's rules are declared but not applied.
_IGNORE_ALWAYS = 3

#: The largest integer magnitude a canonical ``float`` bound holds exactly.
_MAX_EXACT_INT = 2**53


# ===========================================================================
# Runtime — the vendored validate.proto, loaded once into a private pool
# ===========================================================================


@dataclass(frozen=True)
class _Runtime:
    """The dynamic message classes and extension descriptors of ``buf.validate``.

    Attributes:
        field_options: ``google.protobuf.FieldOptions``, in the pool that knows the extension.
        message_options: ``google.protobuf.MessageOptions``, likewise.
        oneof_options: ``google.protobuf.OneofOptions``, likewise.
        field_extension: The ``buf.validate.field`` extension descriptor.
        message_extension: The ``buf.validate.message`` extension descriptor.
        oneof_extension: The ``buf.validate.oneof`` extension descriptor.
        field_rules: The ``buf.validate.FieldRules`` message class.
        message_rules: The ``buf.validate.MessageRules`` message class.
    """

    field_options: Any
    message_options: Any
    oneof_options: Any
    field_extension: Any
    message_extension: Any
    oneof_extension: Any
    field_rules: Any
    message_rules: Any


@functools.lru_cache(maxsize=1)
def _runtime() -> _Runtime:
    """Load the vendored ``buf.validate`` descriptors into a private pool (once per process).

    A private pool keeps the extension out of the default one, so this module can never
    collide with another library that registers ``buf/validate/validate.proto`` itself.

    Returns:
        The message classes and extension descriptors used to read and write rules.
    """
    pool = descriptor_pool.DescriptorPool()
    for module in (descriptor_pb2, duration_pb2, field_mask_pb2, timestamp_pb2):
        pool.AddSerializedFile(module.DESCRIPTOR.serialized_pb)
    with open(_DESCRIPTOR_PATH, "rb") as handle:
        descriptor_set = descriptor_pb2.FileDescriptorSet.FromString(handle.read())
    for file_proto in descriptor_set.file:
        pool.AddSerializedFile(file_proto.SerializeToString())

    def message_class(full_name: str) -> Any:
        return message_factory.GetMessageClass(pool.FindMessageTypeByName(full_name))

    return _Runtime(
        field_options=message_class("google.protobuf.FieldOptions"),
        message_options=message_class("google.protobuf.MessageOptions"),
        oneof_options=message_class("google.protobuf.OneofOptions"),
        field_extension=pool.FindExtensionByName("buf.validate.field"),
        message_extension=pool.FindExtensionByName("buf.validate.message"),
        oneof_extension=pool.FindExtensionByName("buf.validate.oneof"),
        field_rules=message_class("buf.validate.FieldRules"),
        message_rules=message_class("buf.validate.MessageRules"),
    )


def _extension_of(options: Message, options_class: Any, extension: Any) -> Optional[Message]:
    """Return the ``buf.validate`` rules message set on ``options``, or ``None``.

    Args:
        options: A descriptor's options message, as the default runtime parsed it (the
            extension sits in its unknown fields).
        options_class: The same options type in the pool that knows the extension.
        extension: The extension descriptor to read.

    Returns:
        The rules message, or ``None`` when the options carry no such extension or its payload
        does not decode.
    """
    if options.ByteSize() == 0:
        return None
    try:
        typed = options_class.FromString(options.SerializeToString())
    except DecodeError:
        return None
    if not typed.HasExtension(extension):
        return None
    return typed.Extensions[extension]


def _is_repeated(descriptor: FieldDescriptor) -> bool:
    """Whether a rule field is ``repeated`` (across protobuf runtime versions)."""
    repeated = getattr(descriptor, "is_repeated", None)
    if repeated is not None:
        return bool(repeated)
    return descriptor.label == FieldDescriptor.LABEL_REPEATED


def _is_message(descriptor: FieldDescriptor) -> bool:
    """Whether a rule field holds a message (rather than a scalar or an enum)."""
    return descriptor.type == FieldDescriptor.TYPE_MESSAGE


# ===========================================================================
# Reading — options → canonical constraints
# ===========================================================================


@dataclass(frozen=True)
class UnsupportedRule:
    """One rule that is recorded but never enforced.

    Attributes:
        path: Where in the option it sits (``cel``, ``repeated.items.cel``, ``string.#1001``).
        expression: The CEL expression text, or a description of an unrecognized rule.
        rule_id: The CEL rule's ``id``, when it declares one.
        message: The CEL rule's violation ``message``, when it declares one.
        preserved: ``True`` when the rule is kept verbatim and written back on a ``.proto``
            export (CEL); ``False`` when this reader cannot carry it at all (an unrecognized
            rule).
    """

    path: str
    expression: str
    rule_id: Optional[str] = None
    message: Optional[str] = None
    preserved: bool = True


@dataclass
class FieldRuleReading:
    """What one field's ``(buf.validate.field)`` option says, in canonical terms.

    Attributes:
        constraints: The named facets plus the verbatim remainder under
            ``extras['protovalidate']``; ``None`` when the option maps to neither.
        required: ``True`` when the field is declared ``required``.
        unrecognized: Paths of the rules this reader does not know (``string.#1001``); they
            cannot be carried, only reported.
    """

    constraints: Optional[Constraints] = None
    required: bool = False
    unrecognized: List[str] = dataclass_field(default_factory=list)


@dataclass
class MessageRuleReading:
    """What one message's ``(buf.validate.message)`` option says.

    Attributes:
        rules: The rules verbatim in protobuf-JSON form (``cel``, ``cel_expression``,
            ``oneof``), for the type's ``extras['protovalidate']``; empty when none.
        unrecognized: Paths of the rules this reader does not know.
    """

    rules: Dict[str, Any] = dataclass_field(default_factory=dict)
    unrecognized: List[str] = dataclass_field(default_factory=list)


def read_field_rules(options: descriptor_pb2.FieldOptions) -> Optional[FieldRuleReading]:
    """Read a field's Protovalidate rules into canonical constraints.

    Args:
        options: The field descriptor's options.

    Returns:
        The reading, or ``None`` when the field sets no ``(buf.validate.field)`` option.
    """
    runtime = _runtime()
    rules = _extension_of(options, runtime.field_options, runtime.field_extension)
    if rules is None:
        return None

    reading = FieldRuleReading(unrecognized=list(_unrecognized_paths(rules)))
    # `ignore = IGNORE_ALWAYS` switches the field's rules off, so none of them may become a
    # constraint something would enforce: the whole option stays verbatim.
    ignored = rules.ignore == _IGNORE_ALWAYS
    if rules.HasField("required") and not ignored:
        reading.required = bool(rules.required)
        rules.ClearField("required")

    facets: Dict[str, Any] = {}
    family = None if ignored else rules.WhichOneof("type")
    if family is not None:
        family_rules = getattr(rules, family)
        if family in _NUMERIC_FAMILIES:
            _claim_numeric(family_rules, facets)
        elif family == "string":
            _claim_string(family_rules, facets)
        elif family == "bool":
            _claim_const(family_rules, facets)
        elif family == "repeated":
            _claim_repeated(family_rules, facets)
        if not family_rules.ListFields():
            rules.ClearField(family)

    verbatim = json_format.MessageToDict(rules, preserving_proto_field_name=True)
    if facets or verbatim:
        extras = {PROTOVALIDATE_EXTRA_KEY: verbatim} if verbatim else {}
        reading.constraints = Constraints(**facets, extras=extras)
    return reading


def read_message_rules(options: descriptor_pb2.MessageOptions) -> Optional[MessageRuleReading]:
    """Read a message's Protovalidate rules (``cel``, ``cel_expression``, ``oneof``).

    Args:
        options: The message descriptor's options.

    Returns:
        The reading, or ``None`` when the message sets no ``(buf.validate.message)`` option.
    """
    runtime = _runtime()
    rules = _extension_of(options, runtime.message_options, runtime.message_extension)
    if rules is None:
        return None
    return MessageRuleReading(
        rules=json_format.MessageToDict(rules, preserving_proto_field_name=True),
        unrecognized=list(_unrecognized_paths(rules)),
    )


def read_oneof_required(options: descriptor_pb2.OneofOptions) -> bool:
    """Whether a ``oneof`` is declared ``(buf.validate.oneof).required``.

    Args:
        options: The oneof descriptor's options.

    Returns:
        ``True`` when exactly one member of the oneof must be set.
    """
    runtime = _runtime()
    rules = _extension_of(options, runtime.oneof_options, runtime.oneof_extension)
    return bool(rules is not None and rules.required)


def _unrecognized_paths(rules: Message, path: str = "") -> Iterator[str]:
    """Yield the path of every rule this reader does not know, depth-first.

    An unknown field of a rules message is a *predefined* rule (a user-declared extension
    backed by CEL) or a rule from another ``validate.proto`` version. Either way it has no
    name here, so it cannot be kept verbatim — only reported.

    Args:
        rules: A ``buf.validate`` rules message (any level: field, family, nested ``items``).
        path: The dotted path of ``rules`` within the option, empty at the top.

    Yields:
        ``<path>.#<field number>`` per unknown field, e.g. ``string.#1001``.
    """
    prefix = f"{path}." if path else ""
    for descriptor, value in rules.ListFields():
        if _is_message(descriptor) and descriptor.message_type.full_name.startswith(
            "buf.validate."
        ):
            for item in value if _is_repeated(descriptor) else (value,):
                yield from _unrecognized_paths(item, f"{prefix}{descriptor.name}")
    for unknown in unknown_fields.UnknownFieldSet(rules):
        yield f"{prefix}#{unknown.field_number}"


def _cel_rules(rules: Any, path: str = "") -> Iterator[UnsupportedRule]:
    """Yield every CEL rule in a verbatim (protobuf-JSON) rules bag, depth-first.

    Args:
        rules: The bag, or any value nested in it.
        path: The dotted path walked so far.

    Yields:
        One :class:`UnsupportedRule` per ``cel`` rule and per ``cel_expression`` entry,
        wherever it sits (``cel``, ``repeated.items.cel``, ``map.values.cel_expression``).
    """
    if not isinstance(rules, dict):
        return
    prefix = f"{path}." if path else ""
    for name in sorted(rules):
        value = rules[name]
        here = f"{prefix}{name}"
        if name == "cel" and isinstance(value, list):
            for rule in value:
                if isinstance(rule, dict):
                    yield UnsupportedRule(
                        path=here,
                        expression=str(rule.get("expression") or ""),
                        rule_id=rule.get("id") or None,
                        message=rule.get("message") or None,
                    )
        elif name == "cel_expression" and isinstance(value, list):
            for expression in value:
                yield UnsupportedRule(path=here, expression=str(expression))
        else:
            yield from _cel_rules(value, here)


def unsupported_constraints(types: Sequence[Type]) -> List[Dict[str, Any]]:
    """List every Protovalidate rule of a normalized model that is recorded but not enforced.

    This is the import-side loss record: the normalizer publishes it under
    ``CanonicalApi.extras['protovalidate']['capability_limits']`` and the import preview
    manifest renders each entry as a coverage-ledger row.

    Args:
        types: The model's types, in their final (normalized) order.

    Returns:
        One entry per CEL rule and per unrecognized rule, each with ``kind``
        ``unsupported_constraint``, the ``location`` (field or type key), the rule ``path``
        within the option, the ``expression`` text and whether it is ``preserved`` for a
        ``.proto`` export. Message rules precede the fields' within a type.
    """
    entries: List[Dict[str, Any]] = []

    def add(location: str, rule: UnsupportedRule) -> None:
        entry: Dict[str, Any] = {
            "construct": "Protovalidate CEL rule"
            if rule.preserved
            else "Protovalidate unrecognized rule",
            "kind": UNSUPPORTED_CONSTRAINT_KIND,
            "location": location,
            "path": rule.path,
            "expression": rule.expression,
            "preserved": rule.preserved,
        }
        if rule.rule_id:
            entry["id"] = rule.rule_id
        if rule.message:
            entry["message"] = rule.message
        entries.append(entry)

    def add_unrecognized(location: str, extras: Mapping[str, Any]) -> None:
        for path in extras.get(PROTOVALIDATE_UNRECOGNIZED_EXTRA_KEY) or []:
            add(
                location,
                UnsupportedRule(
                    path=str(path),
                    expression="unrecognized rule — a predefined rule or one from another "
                    "validate.proto version",
                    preserved=False,
                ),
            )

    for type_ in types:
        for rule in _cel_rules(type_.extras.get(PROTOVALIDATE_EXTRA_KEY)):
            add(type_.key, rule)
        add_unrecognized(type_.key, type_.extras)
        for member in type_.fields:
            for rule in _cel_rules(verbatim_rules(member.constraints)):
                add(member.key, rule)
            add_unrecognized(member.key, member.extras)
    return entries


def _exact(value: Any) -> bool:
    """Whether a canonical ``float`` bound (or a JSON number) holds ``value`` exactly."""
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return abs(value) <= _MAX_EXACT_INT
    if isinstance(value, float):
        return math.isfinite(value)
    return True


def _claim_const(rules: Message, facets: Dict[str, Any]) -> None:
    """Move ``const`` (else ``in``) onto the ``enum`` facet when every value is exact.

    Args:
        rules: The rule family message; a claimed rule is cleared from it.
        facets: The canonical facets being collected.
    """
    names = {descriptor.name for descriptor, _ in rules.ListFields()}
    if "const" in names:
        if _exact(rules.const):
            facets["enum"] = [rules.const]
            rules.ClearField("const")
        return
    if "in" in names:
        values = list(getattr(rules, "in"))
        if values and all(_exact(value) for value in values):
            facets["enum"] = values
            rules.ClearField("in")


def _claim_numeric(rules: Message, facets: Dict[str, Any]) -> None:
    """Move a numeric family's bounds and ``const``/``in`` onto canonical facets.

    A reversed range (lower bound above the upper) and a bound a ``float`` cannot hold exactly
    are left in place, so they stay verbatim.
    """
    names = {descriptor.name for descriptor, _ in rules.ListFields()}
    lower = next((pair for pair in _LOWER_BOUNDS if pair[0] in names), None)
    upper = next((pair for pair in _UPPER_BOUNDS if pair[0] in names), None)
    bounds = [pair for pair in (lower, upper) if pair is not None]
    values = [getattr(rules, rule) for rule, _facet in bounds]
    reversed_range = len(values) == 2 and values[0] > values[1]
    if not reversed_range and all(_exact(value) for value in values):
        for (rule, facet), value in zip(bounds, values):
            facets[facet] = float(value)
            rules.ClearField(rule)
    _claim_const(rules, facets)


def _claim_string(rules: Message, facets: Dict[str, Any]) -> None:
    """Move a string's length, pattern, ``const``/``in`` and well-known-format rules."""
    names = {descriptor.name for descriptor, _ in rules.ListFields()}
    if "len" in names and not names & {"min_len", "max_len"}:
        facets["min_length"] = facets["max_length"] = rules.len
        rules.ClearField("len")
    for rule, facet in (("min_len", "min_length"), ("max_len", "max_length")):
        if rule in names:
            facets[facet] = getattr(rules, rule)
            rules.ClearField(rule)
    if "pattern" in names:
        facets["pattern"] = rules.pattern
        rules.ClearField("pattern")
    for rule, fmt in _STRING_FORMAT_RULES:
        if rule in names and getattr(rules, rule):
            facets["format"] = fmt
            rules.ClearField(rule)
    _claim_const(rules, facets)


def _claim_repeated(rules: Message, facets: Dict[str, Any]) -> None:
    """Move a repeated field's size bounds and ``unique`` onto canonical facets."""
    names = {descriptor.name for descriptor, _ in rules.ListFields()}
    for rule, facet in (("min_items", "min_items"), ("max_items", "max_items")):
        if rule in names:
            facets[facet] = getattr(rules, rule)
            rules.ClearField(rule)
    if "unique" in names and rules.unique:
        facets["unique_items"] = True
        rules.ClearField("unique")


# ===========================================================================
# Model predicates
# ===========================================================================


def is_protovalidate_required(field: CanonicalField) -> bool:
    """Whether a canonical field was declared ``(buf.validate.field).required``."""
    return bool(field.extras.get(PROTOVALIDATE_REQUIRED_EXTRA_KEY))


def verbatim_rules(constraints: Optional[Constraints]) -> Optional[Dict[str, Any]]:
    """Return the rules a field keeps verbatim (no named facet), or ``None``.

    Args:
        constraints: A field's canonical constraints.

    Returns:
        The protobuf-JSON rules under ``extras['protovalidate']``, when present and non-empty.
    """
    if constraints is None:
        return None
    rules = constraints.extras.get(PROTOVALIDATE_EXTRA_KEY)
    return rules if isinstance(rules, dict) and rules else None


def has_protovalidate_rules(type_: Type) -> bool:
    """Whether a RECORD type carries any Protovalidate rule a ``.proto`` export must write."""
    if type_.extras.get(PROTOVALIDATE_EXTRA_KEY) or type_.extras.get(ONEOFS_REQUIRED_EXTRA_KEY):
        return True
    return any(
        is_protovalidate_required(field) or verbatim_rules(field.constraints) is not None
        for field in type_.fields
    )


def verbatim_rule_names(rules: Optional[Mapping[str, Any]]) -> List[str]:
    """Name the rules in a verbatim bag, for a loss message (``string.prefix``, ``cel``).

    Args:
        rules: A protobuf-JSON rules bag (field or message level), or ``None``.

    Returns:
        ``family.rule`` for each rule of a family and the bare name of a top-level rule
        (``cel``, ``cel_expression``, ``ignore``, ``oneof``), sorted.
    """
    names: List[str] = []
    for name, value in (rules or {}).items():
        if isinstance(value, dict):
            names.extend(f"{name}.{rule}" for rule in value)
        else:
            names.append(str(name))
    return sorted(names)


def unprojected_rules(types: Sequence[Type]) -> List[Tuple[str, List[str]]]:
    """List the Protovalidate rules only a ``.proto`` export can carry.

    A target that projects the named canonical facets (JSON Schema's ``minLength``,
    ``pattern``, …) still loses the verbatim rules, the message rules and required oneofs;
    this is what such an emitter reports instead of dropping them silently.

    Args:
        types: The model's types.

    Returns:
        ``(entity key, rule names)`` per type and field holding such rules, in model order.
    """
    found: List[Tuple[str, List[str]]] = []
    for type_ in types:
        names = verbatim_rule_names(type_.extras.get(PROTOVALIDATE_EXTRA_KEY))
        names.extend(f"oneof {name} required" for name in type_.extras.get(ONEOFS_REQUIRED_EXTRA_KEY) or [])
        if names:
            found.append((type_.key, names))
        for member in type_.fields:
            names = verbatim_rule_names(verbatim_rules(member.constraints))
            if names:
                found.append((member.key, names))
    return found


def rules_family_for_scalar(scalar: Optional[str], *, repeated: bool = False) -> Optional[str]:
    """Name the rule family whose rules apply to a field of an emitted protobuf type.

    Args:
        scalar: The protobuf scalar keyword the field is emitted as (``string``, ``int64``, …),
            or ``None`` / a type name for a message, enum or map field.
        repeated: Whether the field is ``repeated`` — its own rules are then the
            ``repeated`` family's, whatever the element type.

    Returns:
        The family name, or ``None`` when no named facet has a rule for this field.
    """
    if repeated:
        return "repeated"
    if scalar in _NUMERIC_FAMILIES or scalar in ("string", "bool"):
        return scalar
    return None


# ===========================================================================
# Writing — canonical constraints → option assignments
# ===========================================================================


@dataclass
class RenderedFieldRules:
    """A field's Protovalidate rules, ready to print.

    Attributes:
        options: ``(buf.validate.field).… = …`` assignments, in rules-message order.
        unwritten: The named facets (and ``protovalidate`` for an unreadable verbatim bag) that
            no standard rule of this field's family can express, sorted.
    """

    options: List[str] = dataclass_field(default_factory=list)
    unwritten: List[str] = dataclass_field(default_factory=list)


def render_field_options(
    field: CanonicalField, family: Optional[str]
) -> RenderedFieldRules:
    """Render a canonical field's constraints as ``(buf.validate.field)`` option assignments.

    The verbatim rules are restored first; the named facets are then set under ``family`` —
    unless the verbatim rules already chose a *different* family, in which case the facets are
    reported unwritten rather than silently replacing it (a ``FieldRules`` holds one family).

    Args:
        field: The canonical field.
        family: The rule family of the field's emitted type (see
            :func:`rules_family_for_scalar`), or ``None`` when it has none.

    Returns:
        The assignments and the facets left unwritten.
    """
    rendered = RenderedFieldRules()
    rules = _runtime().field_rules()
    constraints = field.constraints
    verbatim = verbatim_rules(constraints)
    if verbatim is not None:
        try:
            json_format.ParseDict(verbatim, rules)
        except json_format.ParseError:
            rules.Clear()
            rendered.unwritten.append(PROTOVALIDATE_EXTRA_KEY)
    if is_protovalidate_required(field):
        rules.required = True

    facets = (
        constraints.model_dump(exclude={"extras"}, exclude_none=True)
        if constraints is not None
        else {}
    )
    written: set[str] = set()
    if family is not None and rules.WhichOneof("type") in (None, family):
        family_rules = getattr(rules, family)
        if family in _NUMERIC_FAMILIES:
            written = _write_numeric(family_rules, facets, integral=family in _INTEGER_FAMILIES)
        elif family == "string":
            written = _write_string(family_rules, facets)
        elif family == "bool":
            written = _write_enum(family_rules, facets, (bool,))
        elif family == "repeated":
            written = _write_repeated(family_rules, facets)
    rendered.unwritten = sorted({*rendered.unwritten, *(set(facets) - written)})
    rendered.options = _assignments(FIELD_OPTION, rules)
    return rendered


def render_message_options(type_: Type) -> List[str]:
    """Render a RECORD type's verbatim message rules as ``(buf.validate.message)`` assignments.

    Args:
        type_: The canonical type.

    Returns:
        The assignments (without the ``option`` keyword), empty when the type has no message
        rules or its bag does not parse.
    """
    verbatim = type_.extras.get(PROTOVALIDATE_EXTRA_KEY)
    if not isinstance(verbatim, dict) or not verbatim:
        return []
    rules = _runtime().message_rules()
    try:
        json_format.ParseDict(verbatim, rules)
    except json_format.ParseError:
        return []
    return _assignments(MESSAGE_OPTION, rules)


def _number(value: Any, *, integral: bool) -> Optional[Any]:
    """Coerce a canonical bound or enum member to a rule value, or ``None`` when it does not fit."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not integral:
        return float(value)
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value)
    return value


def _set(rules: Message, rule: str, value: Any) -> bool:
    """Set one rule, reporting ``False`` when the value is out of the rule type's range."""
    try:
        target = getattr(rules, rule)
        if hasattr(target, "extend"):
            target.extend(value)
        else:
            setattr(rules, rule, value)
    except (TypeError, ValueError, OverflowError):
        rules.ClearField(rule)
        return False
    return True


def _write_enum(rules: Message, facets: Mapping[str, Any], kinds: Tuple[type, ...]) -> set[str]:
    """Write the ``enum`` facet as ``const`` (one value) or ``in`` (several)."""
    values = facets.get("enum")
    if not values or not all(isinstance(value, kinds) for value in values):
        return set()
    has_in = "in" in rules.DESCRIPTOR.fields_by_name
    if len(values) == 1:
        return {"enum"} if _set(rules, "const", values[0]) else set()
    if has_in and _set(rules, "in", values):
        return {"enum"}
    return set()


def _write_numeric(rules: Message, facets: Mapping[str, Any], *, integral: bool) -> set[str]:
    """Write a numeric family's bounds and ``const``/``in`` from the canonical facets.

    When both the inclusive and the exclusive bound of a side are set, the stricter one is
    written — a rules message holds one bound per side — and both count as written.
    """
    written: set[str] = set()
    for (inclusive_rule, inclusive), (exclusive_rule, exclusive), stricter in (
        (*_LOWER_BOUNDS, max),
        (*_UPPER_BOUNDS, min),
    ):
        loose = _number(facets.get(inclusive), integral=integral)
        strict = _number(facets.get(exclusive), integral=integral)
        if loose is not None and strict is not None:
            use_strict = stricter(loose, strict) == strict
            rule, value = (exclusive_rule, strict) if use_strict else (inclusive_rule, loose)
            if _set(rules, rule, value):
                written |= {inclusive, exclusive}
        elif loose is not None:
            if _set(rules, inclusive_rule, loose):
                written.add(inclusive)
        elif strict is not None:
            if _set(rules, exclusive_rule, strict):
                written.add(exclusive)

    values = facets.get("enum")
    if values:
        numbers = [_number(value, integral=integral) for value in values]
        if all(number is not None for number in numbers):
            written |= _write_enum(rules, {"enum": numbers}, (int, float))
    return written


def _write_string(rules: Message, facets: Mapping[str, Any]) -> set[str]:
    """Write a string's length, pattern, ``const``/``in`` and well-known-format rules."""
    written: set[str] = set()
    low, high = facets.get("min_length"), facets.get("max_length")
    if low is not None and low == high:
        if _set(rules, "len", low):
            written |= {"min_length", "max_length"}
    else:
        for rule, facet in (("min_len", "min_length"), ("max_len", "max_length")):
            if facets.get(facet) is not None and _set(rules, rule, facets[facet]):
                written.add(facet)
    if facets.get("pattern") is not None and _set(rules, "pattern", facets["pattern"]):
        written.add("pattern")
    for rule, fmt in _STRING_FORMAT_RULES:
        # The well-known rules share a oneof, so a verbatim one (``ip``, ``tuuid``) wins.
        if facets.get("format") == fmt and rules.WhichOneof("well_known") is None:
            if _set(rules, rule, True):
                written.add("format")
    return written | _write_enum(rules, facets, (str,))


def _write_repeated(rules: Message, facets: Mapping[str, Any]) -> set[str]:
    """Write a repeated field's size bounds and ``unique``."""
    written: set[str] = set()
    for facet in ("min_items", "max_items"):
        if facets.get(facet) is not None and _set(rules, facet, facets[facet]):
            written.add(facet)
    if facets.get("unique_items") is not None:
        # ``unique: false`` is the default, so a false facet is "written" by omission.
        if not facets["unique_items"] or _set(rules, "unique", True):
            written.add("unique_items")
    return written


def _literal(descriptor: FieldDescriptor, value: Any) -> str:
    """Print one rule value as a ``.proto`` option literal (text format)."""
    if _is_message(descriptor):
        return "{ " + text_format.MessageToString(value, as_one_line=True).strip() + " }"
    out = io.StringIO()
    text_format.PrintFieldValue(descriptor, value, out)
    return out.getvalue()


def _assignments(option: str, rules: Message) -> List[str]:
    """Flatten a rules message into ``option.path = literal`` assignments.

    A rule family (``string``, ``repeated``, …) is descended into, so its rules read
    ``(buf.validate.field).string.min_len = 3``; any deeper message (a ``Timestamp`` bound, the
    ``items`` of a repeated field, a CEL rule) is printed as one aggregate ``{ … }`` literal. A
    repeated rule is assigned once per element, which is how ``.proto`` sets a repeated option.

    Args:
        option: The parenthesised option name.
        rules: The rules message.

    Returns:
        The assignments, in field-number order.
    """
    lines: List[str] = []
    for descriptor, value in rules.ListFields():
        path = f"{option}.{descriptor.name}"
        if descriptor.containing_oneof is not None and _is_message(descriptor):
            if not value.ListFields():
                continue
            for inner, inner_value in value.ListFields():
                lines.extend(_leaf_assignments(f"{path}.{inner.name}", inner, inner_value))
        else:
            lines.extend(_leaf_assignments(path, descriptor, value))
    return lines


def _leaf_assignments(path: str, descriptor: FieldDescriptor, value: Any) -> Sequence[str]:
    """Assign one rule: once, or once per element of a repeated rule."""
    values = value if _is_repeated(descriptor) else (value,)
    return [f"{path} = {_literal(descriptor, item)}" for item in values]
