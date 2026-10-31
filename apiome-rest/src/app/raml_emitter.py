"""RAML emitter: canonical model → RAML 1.0 — MFX-19.1, MFX-17.1 (#3901).

The inverse of :class:`app.raml_normalizer.RamlNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The document is built as plain data and written with PyYAML, so
every scalar is quoted where YAML needs it, and the ``#%RAML 1.0`` header is always the first line
(RAML refuses a document that starts with anything else).

**Document.** ``title`` (the API title, else its name), ``description``, ``version``, ``baseUri`` (the
first server) with its variables as ``baseUriParameters``, and ``mediaType`` (a RAML source's own, else
the media type the bodies use most, else ``application/json``).

**Types.** Records are ``object`` types whose ``properties`` keep the source's field order (so field
numbers survive); an optional field is written ``name?``. Enums are ``string`` types with ``enum``;
unions are ``A | B``; aliases and scalars name their base type; maps are objects with a ``//`` pattern
property. Scalars keep their meaning: ``i64`` is ``integer`` with ``format: int64``, a ``date-time``
string is ``datetime``. Constraints become RAML facets (``minLength``, ``pattern``, ``minimum``,
``multipleOf``, ``minItems``, ``uniqueItems``, ``enum`` …) on the types that allow them. A RAML source's
own type spellings (``date-only``, ``time-only`` …) are written back as they were read.

**Resources.** One resource per path, written flat (``/books/{bookId}``), sorted. Path parameters are
the resource's ``uriParameters``; each operation is a method with its ``displayName`` (when the source
names it), ``description``, ``queryParameters``, ``headers``, ``body`` per media type, and
``responses`` keyed by status code with their description, headers and body.

**Not carried, and reported** (by the writer as losses and by :class:`RamlFidelityRulePack` before an
emit): operations with no HTTP binding or with a method RAML 1.0 lacks, event operations and channels,
a second operation on the same method and path, cookie parameters, status ranges (``4XX``,
``default``), servers beyond the first, facets a type does not allow, string formats RAML has no type
for, exclusive bounds, deprecation flags, tags, and source-specific details. A RAML source's resource
types and traits arrive already applied to each method (MFI-15.2), so they are written merged into the
methods. Validation of the output is :func:`app.export_validation.validate_emitted_artifact`: AMF's
RAML 1.0 profile when the toolchain has it, else a re-parse through the RAML reader.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import yaml
from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity
from .scalar_aliases import scalar_kind

__all__ = ["REST_ONLY_WARNING", "RamlEmitOptions", "RamlEmitter", "RamlFidelityRulePack", "raml_scalar"]

_RAML_HEADER = "#%RAML 1.0"
_RAML_FORMAT = "raml"
_DEFAULT_MEDIA_TYPE = "application/json"
#: The advisory a source of another paradigm gets at the root of its fidelity report (MFX-17.2).
REST_ONLY_WARNING = "RAML captures REST only"

#: The HTTP methods RAML 1.0 declares, in the order a resource lists them.
_METHODS = ("get", "put", "post", "patch", "delete", "head", "options")
_STATUS = re.compile(r"^[1-5][0-9]{2}$")
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})

#: RAML 1.0 built-in type names. A declared type may not take one of these names.
_RAML_BUILTINS = frozenset(
    {
        "any", "array", "boolean", "date-only", "datetime", "datetime-only", "file", "integer",
        "nil", "number", "object", "string", "time-only", "union",
    }
)
#: A RAML type expression made only of built-ins (``date-only``, ``integer[]``): the shape of a
#: RAML source's ``raml_type`` hint that is written back verbatim.
_BUILTIN_EXPRESSION = re.compile(r"^(%s)(\[\])*$" % "|".join(re.escape(n) for n in sorted(_RAML_BUILTINS)))
#: The ``format`` facet values RAML 1.0 allows on ``integer`` and ``number``.
_NUMBER_FORMATS = frozenset({"int", "int8", "int16", "int32", "int64", "long", "float", "double"})

#: Scalar kind (:mod:`app.scalar_aliases`) → RAML type and ``format`` facet. RAML has no unsigned
#: integers; an unsigned kind is an ``integer`` with ``minimum: 0`` (see :class:`RamlScalar`).
_KIND_TO_RAML: Dict[str, Tuple[str, Optional[str]]] = {
    "bool": ("boolean", None),
    "int8": ("integer", "int8"),
    "int16": ("integer", "int16"),
    "int32": ("integer", "int32"),
    "int64": ("integer", "int64"),
    "uint8": ("integer", None),
    "uint16": ("integer", None),
    "uint32": ("integer", None),
    "uint64": ("integer", None),
    "float": ("number", "float"),
    "double": ("number", "double"),
    "string": ("string", None),
    "bytes": ("file", None),
}
#: Canonical spellings with a RAML type of their own (RAML's date types; JSON Schema leftovers).
_NAMED_TO_RAML: Dict[str, str] = {
    "date": "date-only",
    "date-only": "date-only",
    "time": "time-only",
    "time-only": "time-only",
    "datetime-only": "datetime-only",
    "date-time": "datetime",
    "datetime": "datetime",
    "timestamp": "datetime",
    "decimal": "number",
    "any": "any",
    "null": "nil",
    "nil": "nil",
    "object": "object",
    "array": "array",
    "file": "file",
    "uri": "string",
    "url": "string",
}
#: A string ``format`` that has a RAML type of its own.
_STRING_FORMAT_TO_RAML: Dict[str, str] = {
    "date": "date-only",
    "date-time": "datetime",
    "datetime": "datetime",
    "time": "time-only",
}

#: The facet families: which facets RAML 1.0 allows on which type.
_STRING_FAMILY = frozenset({"string"})
_NUMBER_FAMILY = frozenset({"integer", "number"})
#: Canonical constraint → (RAML facet, the families of type that allow it).
_FACETS: Tuple[Tuple[str, str, str], ...] = (
    ("min_length", "minLength", "string file"),
    ("max_length", "maxLength", "string file"),
    ("pattern", "pattern", "string"),
    ("minimum", "minimum", "number"),
    ("maximum", "maximum", "number"),
    ("multiple_of", "multipleOf", "number"),
    ("min_items", "minItems", "array"),
    ("max_items", "maxItems", "array"),
    ("unique_items", "uniqueItems", "array"),
    ("enum", "enum", "string number boolean"),
)


# ===========================================================================
# Scalars and type expressions
# ===========================================================================


@dataclass(frozen=True)
class RamlScalar:
    """The RAML spelling of one canonical scalar.

    Attributes:
        type: The RAML built-in (``integer``, ``datetime`` …).
        format: The ``format`` facet (``int64``), when the scalar has a width RAML names.
        unsigned: Whether the source scalar is unsigned (written with ``minimum: 0``).
        format_kept: Whether the source ``format`` (if any) is carried by ``type`` / ``format``.
    """

    type: str
    format: Optional[str] = None
    unsigned: bool = False
    format_kept: bool = True


def raml_scalar(name: Optional[str], fmt: Optional[str] = None) -> Optional[RamlScalar]:
    """Return the RAML spelling of a canonical scalar, or ``None`` when ``name`` is not a scalar.

    Args:
        name: The :class:`~app.canonical_model.TypeRef` name (``integer``, ``i64``, ``date-time`` …).
        fmt: The field's ``format`` constraint, when it has one (``int64``, ``date``, ``email`` …).

    Returns:
        The :class:`RamlScalar`, or ``None`` for a name that is not a scalar (a named type).
    """
    if not name:
        return None
    key = name.strip().lower()
    hint = (fmt or "").strip().lower() or None
    if key in ("integer", "int", "number"):
        family = "number" if key == "number" else "integer"
        if hint in _NUMBER_FORMATS:
            return RamlScalar(family, hint)
        return RamlScalar(family, None, format_kept=hint is None or (family == "number" and hint == "decimal"))
    if key in ("string", "str", "text"):
        if hint in _STRING_FORMAT_TO_RAML:
            return RamlScalar(_STRING_FORMAT_TO_RAML[hint])
        return RamlScalar("string", format_kept=hint is None)
    if key in _NAMED_TO_RAML:
        return RamlScalar(_NAMED_TO_RAML[key], format_kept=hint is None or hint == key)
    kind = scalar_kind(name, fmt)
    if kind is None:
        return None
    raml_type, raml_format = _KIND_TO_RAML[kind]
    return RamlScalar(raml_type, raml_format, unsigned=kind.startswith("uint"), format_kept=True)


def _facet_family(raml_type: str) -> str:
    """The facet family of a written type: ``string``, ``number``, ``boolean``, ``file`` or ``other``."""
    if raml_type in _STRING_FAMILY:
        return "string"
    if raml_type in _NUMBER_FAMILY:
        return "number"
    if raml_type in ("boolean", "file"):
        return raml_type
    return "other"


@dataclass
class Note:
    """One thing the RAML output does not carry as the source has it.

    Shared by the writer (a :class:`~app.emitter.Loss`) and :class:`RamlFidelityRulePack` (a
    verdict), so the export and its prediction say the same thing.

    Attributes:
        subject: Loss slug (``facet-dropped``).
        message: What happened, in a sentence fragment.
        dropped: ``True`` when something is not written at all (``n/a``), ``False`` when it is written
            differently (``inferred``).
        severity: How much it matters for the fidelity report.
    """

    subject: str
    message: str
    dropped: bool = True
    severity: LossinessSeverity = LossinessSeverity.INFO


@dataclass
class _Expression:
    """A written type: its expression, facets, and what it could not carry."""

    expr: str
    facets: Dict[str, Any] = field(default_factory=dict)
    notes: List[Note] = field(default_factory=list)


class RamlNames:
    """The RAML name of every named type of one model, and the RAML spelling of a type reference.

    RAML type names may not be built-in names and may not contain the characters of a type
    expression (``|``, ``[]``, ``()``, ``?``, ``,``) or a library dot, so other names are rewritten
    (``com.acme.Order`` → ``com_acme_Order``) and kept unique.

    Args:
        api: The model being exported.
    """

    def __init__(self, api: CanonicalApi) -> None:
        self._api = api
        #: Whether the model was read from RAML (its own spellings are written back).
        self.raml_source = api.format == _RAML_FORMAT
        taken = set(_RAML_BUILTINS)
        #: Type key → the name the type is declared under.
        self.names: Dict[str, str] = {}
        for type_ in api.types:
            name = _type_name(type_.name)
            candidate, suffix = name, 2
            while candidate in taken:
                candidate, suffix = f"{name}{suffix}", suffix + 1
            taken.add(candidate)
            self.names[type_.key] = candidate
        self._key_by_name: Dict[str, str] = {}
        for type_ in api.types:
            self._key_by_name.setdefault(type_.name, type_.key)

    def type_key(self, name: Optional[str]) -> Optional[str]:
        """The key of the named type ``name`` refers to (by key, else by source name), or ``None``."""
        if not name:
            return None
        if name in self.names:
            return name
        return self._key_by_name.get(name)

    def expression(
        self,
        ref: Optional[TypeRef],
        *,
        constraints: Optional[Constraints] = None,
        hint: Optional[str] = None,
        default: Any = None,
    ) -> _Expression:
        """Spell a type reference with its facets.

        Args:
            ref: The reference (``None`` is ``any``).
            constraints: The use site's constraints (become facets, or notes when not allowed).
            hint: A RAML source's own spelling (``raml_type``), written back when it is a built-in
                expression.
            default: The use site's default; a ``default`` facet is only meaningful with a type.

        Returns:
            The :class:`_Expression`.
        """
        fmt = constraints.format if constraints is not None else None
        notes: List[Note] = []
        out = _Expression(expr=self._expr(ref, fmt, notes), notes=notes)
        scalar = raml_scalar(_leaf(ref).name if ref is not None else None, fmt)
        if self.raml_source and hint and _BUILTIN_EXPRESSION.match(hint.strip()):
            # The source's own spelling; its width is whatever the source said (no format of ours).
            out.expr = hint.strip()
            scalar = raml_scalar(_strip_lists(out.expr), fmt)
        top = _strip_lists(out.expr)
        family = "array" if out.expr.endswith("[]") else _facet_family(top)
        if family != "array" and scalar is not None:
            if scalar.format and top in _NUMBER_FAMILY:
                out.facets["format"] = scalar.format
            if fmt and not scalar.format_kept:
                out.notes.append(
                    Note("format-dropped", f"RAML has no {fmt!r} format for {top}; it is written as {top}")
                )
        if constraints is not None:
            self._facets(constraints, family, out)
        if family != "array" and scalar is not None and scalar.unsigned and "minimum" not in out.facets:
            out.facets["minimum"] = 0
            out.notes.append(
                Note("unsigned-widened", "RAML has no unsigned integers; it is written as integer with minimum 0",
                     dropped=False)
            )
        return out

    def _expr(self, ref: Optional[TypeRef], fmt: Optional[str], notes: List[Note]) -> str:
        if ref is None:
            return "any"
        if ref.item is not None:
            inner = self._expr(ref.item, fmt, notes)
            return f"({inner})[]" if "|" in inner else f"{inner}[]"
        key = self.type_key(ref.name)
        if key is not None:
            return self.names[key]
        scalar = raml_scalar(ref.name, fmt)
        if scalar is not None:
            return scalar.type
        if ref.name:
            notes.append(Note("unknown-type", f"the type {ref.name!r} is not declared; it is written as any"))
        return "any"

    @staticmethod
    def _facets(constraints: Constraints, family: str, out: _Expression) -> None:
        """Add the facets ``family`` allows; note the ones it does not and the exclusive bounds."""
        for attribute, facet, families in _FACETS:
            value = getattr(constraints, attribute)
            if value is None or (attribute == "unique_items" and value is False):
                continue
            if family in families.split():
                out.facets[facet] = _plain(value)
            else:
                out.notes.append(
                    Note("facet-dropped", f"RAML allows no {facet} facet here; {facet}={value!r} is not written",
                         severity=LossinessSeverity.WARN)
                )
        for attribute, label in (("exclusive_minimum", "exclusiveMinimum"), ("exclusive_maximum", "exclusiveMaximum")):
            value = getattr(constraints, attribute)
            if value is not None:
                out.notes.append(
                    Note("facet-dropped", f"RAML has no exclusive bounds; {label}={value!r} is not written",
                         severity=LossinessSeverity.WARN)
                )


def _leaf(ref: TypeRef) -> TypeRef:
    while ref.item is not None:
        ref = ref.item
    return ref


def _strip_lists(expr: str) -> str:
    while expr.endswith("[]"):
        expr = expr[:-2]
    return expr.strip("()")


def _type_name(name: str) -> str:
    """A RAML-safe declared type name: letters, digits, ``_`` and ``-`` only."""
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", name or "").strip("_")
    return safe or "Type"


def _plain(value: Any) -> Any:
    """``value`` with integral floats as ints (``5.0`` → ``5``), so YAML writes what the source meant."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


# ===========================================================================
# What RAML cannot carry — shared by the writer and the rule pack
# ===========================================================================


@dataclass
class _Plan:
    """Which operations are written, on which resource, and why the others are not."""

    #: ``(path, method)`` → the operation written there, in model order.
    kept: Dict[Tuple[str, str], Operation] = field(default_factory=dict)
    #: Operation key → why it is not written.
    dropped: Dict[str, str] = field(default_factory=dict)


def _plan(api: CanonicalApi) -> _Plan:
    """Place every operation on a RAML resource and method, or say why it cannot be."""
    plan = _Plan()
    for operation in api.operations():
        if operation.kind in _EVENT_OPERATION_KINDS:
            plan.dropped[operation.key] = "RAML has no event operations"
            continue
        method = (operation.http_method or "").lower()
        if not method or not operation.http_path:
            plan.dropped[operation.key] = (
                "RAML describes HTTP resources only; the operation has no HTTP method and path"
            )
            continue
        if method not in _METHODS:
            plan.dropped[operation.key] = f"RAML 1.0 has no {method.upper()} method"
            continue
        slot = (_resource_path(operation.http_path), method)
        if slot in plan.kept:
            plan.dropped[operation.key] = (
                f"{plan.kept[slot].key!r} is already written as {method.upper()} {slot[0]}; RAML has one method "
                "per verb and resource"
            )
            continue
        plan.kept[slot] = operation
    return plan


def _resource_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def _status(message: Message) -> Optional[str]:
    """The message's HTTP status when it is a single code (``404``), else ``None`` (``4XX``)."""
    raw = str(message.status_code or message.extras.get("http_status") or "")
    return raw if _STATUS.match(raw) else None


def _messages_in_write_order(operation: Operation) -> List[Message]:
    """The operation's messages, those with a status first: a response with none only gets 200 if it is free."""
    return sorted(operation.messages, key=lambda m: not (m.status_code or m.extras.get("http_status")))


def _has_explicit_name(operation: Operation) -> bool:
    """Whether the source named the operation (an unnamed RAML method is ``"<VERB> <path>"``)."""
    synthesized = f"{(operation.http_method or '').upper()} {operation.http_path or ''}"
    return bool(operation.name) and operation.name not in (synthesized, operation.key)


def _same_parameter(a: Parameter, b: Parameter) -> bool:
    exclude = {"key", "extras"}
    return a.model_dump(exclude=exclude) == b.model_dump(exclude=exclude)


def _path_parameter_owners(plan: _Plan) -> Dict[Tuple[str, str], Parameter]:
    """``(path, name)`` → the path parameter the resource declares (the first operation's)."""
    owners: Dict[Tuple[str, str], Parameter] = {}
    for (path, _method), operation in plan.kept.items():
        for param in operation.parameters:
            if param.location is ParameterLocation.PATH:
                owners.setdefault((path, param.name), param)
    return owners


def _operation_notes(
    operation: Operation, names: RamlNames, owners: Dict[Tuple[str, str], Parameter], raml_source: bool
) -> List[Note]:
    """What a written operation loses (its parameters, messages and details)."""
    notes: List[Note] = []
    path = _resource_path(operation.http_path or "/")
    for param in operation.parameters:
        if param.location is ParameterLocation.COOKIE:
            notes.append(Note("parameter-dropped", f"RAML has no cookie parameters; {param.name!r} is not written",
                              severity=LossinessSeverity.WARN))
            continue
        if param.location is ParameterLocation.PATH:
            owner = owners.get((path, param.name))
            if owner is not None and owner is not param and not _same_parameter(owner, param):
                notes.append(Note("parameter-merged",
                                  f"the path parameter {param.name!r} is declared once for {path}; this operation's "
                                  "definition differs and is not written", severity=LossinessSeverity.WARN))
                continue
        if param.deprecated:
            notes.append(Note("deprecated-dropped", f"RAML has no deprecation flag; parameter {param.name!r} is not "
                              "marked deprecated"))
        if not raml_source and param.extras:
            notes.append(Note("parameter-details-dropped", f"source-specific details of parameter {param.name!r} "
                              f"({', '.join(sorted(param.extras))}) are not written"))
        notes.extend(
            names.expression(param.type, constraints=param.constraints, hint=param.extras.get("raml_type")).notes
        )
    seen: set = set()
    for message in _messages_in_write_order(operation):
        if message.role is MessageRole.EVENT:
            notes.append(Note("message-dropped", f"RAML has no event messages; {message.key!r} is not written"))
            continue
        if message.role is MessageRole.REQUEST:
            notes.extend(_body_notes(message, names))
            continue
        status = _status(message)
        raw = message.status_code or message.extras.get("http_status")
        if status is None and raw:
            notes.append(Note("status-range-dropped", f"RAML responses are single status codes; the {raw!r} "
                              "response is not written", severity=LossinessSeverity.WARN))
            continue
        status = status or "200"
        if status in seen:
            notes.append(Note("response-dropped", f"a {status} response is already written; {message.key!r} is not"))
            continue
        seen.add(status)
        if not (message.status_code or message.extras.get("http_status")):
            notes.append(Note("status-synthesized", f"the response {message.key!r} has no status; it is written as 200",
                              dropped=False))
        notes.extend(_body_notes(message, names))
        for header in message.headers:
            notes.extend(names.expression(header.type, constraints=header.constraints).notes)
    if operation.deprecated:
        notes.append(Note("deprecated-dropped", "RAML has no deprecation flag; the operation is not marked deprecated"))
    if operation.tags:
        notes.append(Note("tags-dropped", f"RAML methods have no tags; {', '.join(operation.tags)} not written"))
    if operation.streaming is not StreamingMode.NONE:
        notes.append(Note("streaming-dropped", f"RAML has no streaming; the {operation.streaming.value} stream is "
                          "written as one request and response", dropped=False, severity=LossinessSeverity.WARN))
    reuse = [key for key in ("raml_resource_type", "raml_traits") if operation.extras.get(key)]
    if raml_source and reuse:
        notes.append(Note("reuse-flattened", "the resource type and traits are written merged into the method",
                          dropped=False))
    elif not raml_source and operation.extras:
        notes.append(Note("operation-details-dropped",
                          f"source-specific details ({', '.join(sorted(operation.extras))}) are not written"))
    return notes


def _body_notes(message: Message, names: RamlNames) -> List[Note]:
    """What a written request or response body loses."""
    if message.payload is not None:
        return names.expression(message.payload).notes
    if message.payload_schema:
        return [Note("inline-schema", f"the inline schema of {message.key!r} is written as a JSON Schema type",
                     dropped=False)]
    return []


def _type_notes(type_: Type, names: RamlNames) -> List[Note]:
    """What a declared type loses (not its fields: see :func:`_field_notes`)."""
    notes: List[Note] = []
    written = names.names[type_.key]
    if written != type_.name:
        notes.append(Note("type-renamed", f"RAML type names allow no {type_.name!r}; it is written as {written!r}",
                          dropped=False))
    if type_.deprecated:
        notes.append(Note("deprecated-dropped", "RAML has no deprecation flag; the type is not marked deprecated"))
    if type_.namespace or type_.key not in (written, type_.name):
        notes.append(Note("namespace-dropped", f"RAML has no namespaces; {type_.key!r} is declared as {written!r}"))
    if type_.kind is TypeKind.RECORD and any(f.field_number is None for f in type_.fields):
        notes.append(Note("field-numbers-positional", "RAML has no field numbers; the properties keep their order "
                          "and read back numbered by position", dropped=False))
    if not names.raml_source and type_.extras:
        notes.append(Note("type-details-dropped",
                          f"source-specific details ({', '.join(sorted(type_.extras))}) are not written"))
    if type_.kind is TypeKind.ENUM:
        positional = all(value.value in (None, index, value.name) for index, value in enumerate(type_.enum_values))
        if not positional:
            notes.append(Note("enum-values-dropped", "RAML enums list names only; the values' numbers are not written"))
        if any(value.description or value.deprecated for value in type_.enum_values):
            notes.append(Note("enum-docs-dropped", "RAML enum values carry no description or deprecation"))
    elif type_.kind is TypeKind.UNION:
        missing = [member for member in type_.union_members if names.type_key(member) is None]
        if missing:
            notes.append(Note("unknown-type", f"union members {', '.join(missing)} are not declared; written as any"))
    elif type_.kind is TypeKind.ALIAS:
        notes.extend(names.expression(type_.aliased, constraints=type_.constraints).notes)
    elif type_.kind is TypeKind.MAP:
        notes.extend(_map_notes(type_, names))
    elif type_.kind is TypeKind.SCALAR:
        notes.extend(_scalar_type(type_, names).notes)
    return notes


def _map_notes(type_: Type, names: RamlNames) -> List[Note]:
    notes = list(names.expression(type_.value_type).notes)
    key = type_.key_type
    if key is not None and (key.item is not None or (raml_scalar(key.name) or RamlScalar("other")).type != "string"):
        notes.append(Note("map-key-dropped", "RAML map keys are strings; the key type is not written", dropped=False))
    return notes


def _scalar_type(type_: Type, names: RamlNames) -> _Expression:
    """The base expression of a named scalar: its own name when it is a known scalar, else ``string``."""
    if raml_scalar(type_.name, type_.constraints.format if type_.constraints else None) is not None:
        return names.expression(TypeRef(name=type_.name), constraints=type_.constraints)
    out = names.expression(TypeRef(name="string"), constraints=type_.constraints)
    out.notes.append(Note("custom-scalar", "RAML has no custom scalars; it is written as a string type",
                          dropped=False))
    return out


def _field_notes(field_: CanonicalField, names: RamlNames) -> List[Note]:
    """What a record field loses (its type, facets and flags)."""
    notes = list(
        names.expression(field_.type, constraints=field_.constraints, hint=field_.extras.get("raml_type")).notes
    )
    if field_.deprecated:
        notes.append(Note("deprecated-dropped", "RAML has no deprecation flag; the field is not marked deprecated"))
    return notes


def _positional_fields(type_: Type) -> set:
    """Keys of the fields whose number is their 1-based position in field-number order."""
    return {f.key for index, f in enumerate(_ordered_fields(type_), start=1) if f.field_number == index}


def _ordered_fields(type_: Type) -> List[CanonicalField]:
    """A record's fields in field-number order (unnumbered ones last, as declared)."""
    indexed = list(enumerate(type_.fields))
    indexed.sort(key=lambda pair: (pair[1].field_number is None, pair[1].field_number or 0, pair[0]))
    return [f for _index, f in indexed]


def _document_notes(api: CanonicalApi) -> List[Note]:
    """What the document envelope loses: services, identity, extra servers, agents, source details."""
    notes: List[Note] = []
    if not api.title:
        notes.append(Note("title-synthesized", f"RAML requires a title; {_title(api)!r} is used", dropped=False))
    if len(api.servers) > 1:
        notes.append(Note("servers-dropped", f"RAML has one baseUri; {api.servers[0].url!r} is used and "
                          f"{len(api.servers) - 1} other server(s) are not written"))
    if api.agents:
        notes.append(Note("agents-dropped", f"RAML has no agent descriptors; {len(api.agents)} are not written"))
    if api.format == _RAML_FORMAT:
        return notes
    if api.services:
        listed = ", ".join(repr(service.name) for service in api.services[:3])
        more = f" and {len(api.services) - 3} more" if len(api.services) > 3 else ""
        notes.append(Note("services-merged", f"the operations of service(s) {listed}{more} become resources of one "
                          "RAML API", dropped=False))
    if api.identity.namespace or api.identity.id or api.identity.name != _title(api):
        notes.append(
            Note("identity-dropped", "RAML names an API by its title only; the source identity is not written")
        )
    if api.servers and (api.servers[0].name or api.servers[0].description):
        notes.append(Note("server-details-dropped", "RAML's baseUri has no name or description"))
    if api.extras:
        notes.append(Note("document-details-dropped",
                          f"source-specific details ({', '.join(sorted(api.extras))}) are not written"))
    if not notes:
        notes.append(Note("document-rewritten", "the document is written as RAML 1.0 (title, version, "
                          "description and baseUri)", dropped=False))
    return notes


def _title(api: CanonicalApi) -> str:
    return api.title or api.identity.name or "API"


# ===========================================================================
# Fidelity rule pack
# ===========================================================================


def _verdict(notes: Sequence[Note], target_mapping: str) -> Optional[FidelityVerdict]:
    """One ``APPROX`` verdict naming every note (warn when any note warns), or ``None`` for no notes."""
    if not notes:
        return None
    severity = (
        LossinessSeverity.WARN if any(n.severity is LossinessSeverity.WARN for n in notes) else LossinessSeverity.INFO
    )
    return FidelityVerdict.approx(
        message="RAML: " + "; ".join(note.message for note in notes), severity=severity, target_mapping=target_mapping
    )


def _rest_only_verdict(api: CanonicalApi, plan: _Plan) -> Optional[FidelityVerdict]:
    """The root advisory of a source that is not a REST API: :data:`REST_ONLY_WARNING`, with counts.

    Args:
        api: The source model.
        plan: Where its operations are written (:func:`_plan`).

    Returns:
        ``None`` for a REST source. Otherwise a ``DROP`` naming the operations and channels that are
        not written (``critical`` when no operation is written at all), or an ``APPROX`` when every
        operation has an HTTP binding and only the paradigm changes.
    """
    if api.paradigm is ApiParadigm.REST:
        return None
    paradigm = api.paradigm.value.replace("_", " ")
    mapping = f"{api.paradigm.value} → REST"
    lost = []
    if plan.dropped:
        lost.append(f"{len(plan.dropped)} operation(s) RAML cannot place on an HTTP resource")
    if api.channels:
        lost.append(f"{len(api.channels)} channel(s)")
    if not lost:
        return FidelityVerdict.approx(
            message=f"RAML: {REST_ONLY_WARNING}; this {paradigm} API is written as HTTP resources and reads back as "
            "a REST API",
            target_mapping=mapping,
        )
    nothing_written = not plan.kept
    return FidelityVerdict.drop(
        message=f"RAML: {REST_ONLY_WARNING}; this {paradigm} API reads back as a REST API, and "
        f"{' and '.join(lost)} are not written"
        + ("; only its types are exported" if nothing_written else ""),
        severity=LossinessSeverity.CRITICAL if nothing_written else LossinessSeverity.WARN,
        target_mapping=mapping,
    )


class RamlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for RAML export — MFX-17.1 (#3901), non-REST losses and type coverage MFX-17.2 (#3902).

    On top of the capability rules, every verdict comes from the same helpers the writer reports
    its losses with: operations RAML cannot place (no HTTP binding, an unknown method, a second
    operation on one method and path), what a written operation, type or field loses, the document
    envelope (services, identity, extra servers), and field numbers that RAML's property order
    cannot keep.

    **Non-REST sources** (MFX-17.2): a GraphQL, RPC, event, data-schema or agent source gets the
    root advisory :data:`REST_ONLY_WARNING` — a ``DROP`` with the operations and channels that are not
    written (``critical`` when nothing but types is exported); its operations without an HTTP
    binding stay ``DROP`` each.

    **What a re-import gives back** (MFX-17.2), so the round trip (:mod:`app.raml_roundtrip`) can
    explain every structural change: RAML has no services, so each source service whose key is not
    the title is a ``DROP`` and the one service a RAML reader names after the title is a ``SYNTH``; a
    type declared under a name other than its key (a namespace or a rename) is a ``DROP`` under its
    key and a ``SYNTH`` under the declared name; a record with unnumbered fields reads back numbered
    by position, and a non-RAML type's source-specific details are not written (both ``APPROX``).
    RAML-source resource types and traits are written merged into each method (``APPROX``).
    """

    target_label = "RAML"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Prepare the model-wide facts the per-construct hooks need, then run the drive loop."""
        self._api = api
        self._names = RamlNames(api)
        self._plan = _plan(api)
        self._owners = _path_parameter_owners(self._plan)
        self._positional = {key for t in api.types if t.kind is TypeKind.RECORD for key in _positional_fields(t)}
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        notes = _document_notes(api)
        synthesized = [n for n in notes if n.subject == "title-synthesized"]
        verdicts = [
            FidelityVerdict.synth(message=f"RAML: {n.message}", severity=LossinessSeverity.INFO,
                                  target_mapping="title") for n in synthesized
        ]
        advisory = _rest_only_verdict(api, self._plan)
        rest = _verdict([n for n in notes if n not in synthesized], "document → RAML root")
        return [*([advisory] if advisory else []), *verdicts, *([rest] if rest else [])]

    def service_verdicts(self, service: Service) -> List[FidelityVerdict]:
        """A service whose key is not the title does not survive: RAML has one API, named by its title."""
        title = _title(self._api)
        if service.key == title:
            return []
        return [FidelityVerdict.drop(
            message=f"RAML: RAML has no services; the operations of {service.name!r} become resources of one API, "
            f"read back as the service {title!r}",
            severity=LossinessSeverity.INFO,
            target_mapping=f"service → API {title}",
        )]

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """The service a RAML reader names after the title, and each type declared under a new name."""
        title = _title(api)
        out: List[Tuple[str, FidelityVerdict]] = []
        if not any(service.key == title for service in api.services):
            out.append((title, FidelityVerdict.synth(
                message=f"RAML: a RAML document is one API; it reads back as the service {title!r}",
                severity=LossinessSeverity.INFO,
                target_mapping="title → service",
            )))
        source_keys = {type_.key for type_ in api.types}
        for type_ in api.types:
            written = self._names.names[type_.key]
            if written != type_.key and written not in source_keys:
                out.append((written, FidelityVerdict.synth(
                    message=f"RAML: {type_.key!r} is declared as the type {written!r} and reads back under that name",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"type {written}",
                )))
        return out

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        verdict = super().operation_verdict(operation)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        reason = self._plan.dropped.get(operation.key)
        if reason:
            return FidelityVerdict.drop(message=f"{reason}; the operation is dropped", target_mapping="dropped")
        notes = _operation_notes(operation, self._names, self._owners, self._api.format == _RAML_FORMAT)
        return _verdict(notes, "operation → resource method") or verdict

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        return _verdict(_type_notes(type_, self._names), f"{type_.kind.value} → RAML type") or verdict

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The type's verdict, and a ``DROP`` of its key when it is declared under another name.

        The key change replaces the type's namespace note; its other losses stay one ``APPROX``.
        """
        written = self._names.names[type_.key]
        if written == type_.key:
            return [self.type_verdict(type_)]
        verdicts = [FidelityVerdict.drop(
            message=f"RAML: RAML types are keyed by their name; {type_.key!r} is declared as {written!r} and "
            "its key is not kept",
            severity=LossinessSeverity.INFO,
            target_mapping=f"type {written}",
        )]
        capability = super().type_verdict(type_)
        if capability.kind is not LossinessKind.OK:
            return [*verdicts, capability]
        notes = [n for n in _type_notes(type_, self._names) if n.subject != "namespace-dropped"]
        rest = _verdict(notes, f"{type_.kind.value} → RAML type")
        return [*verdicts, *([rest] if rest else [])]

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        verdicts = super().field_verdicts(field)
        own = _verdict(_field_notes(field, self._names), "field → property")
        return [*verdicts, *([own] if own else [])]

    def _field_identity_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """Field numbers equal to the property's position survive (RAML keeps property order)."""
        if field.field_number is not None and field.key not in self._positional:
            return FidelityVerdict.drop(
                message=f"RAML has no field numbers; properties keep their order but number {field.field_number} "
                "is dropped",
                severity=LossinessSeverity.INFO,
            )
        return None


# ===========================================================================
# Emitter
# ===========================================================================


class RamlEmitOptions(EmitOptions):
    """Per-target options for :class:`RamlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Write a generated-file comment under the `#%RAML 1.0` header.",
    )
    media_type: str = Field(
        default=_DEFAULT_MEDIA_TYPE,
        description="The document `mediaType` when the source has no media type of its own and no body names one.",
    )


class RamlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a RAML 1.0 document."""

    key = "raml"
    format = "raml"
    label = "RAML"
    description = "Export as a RAML 1.0 REST API definition."
    icon = "book-marked"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = RamlEmitOptions

    OUTPUT_MEDIA_TYPE = "application/raml+yaml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return RamlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[RamlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, RamlEmitOptions)
            else RamlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _RamlWriter(api, options)
        content = writer.render()
        return EmitResult(
            files=[EmittedFile(path=writer.output_path, content=content, media_type=self.OUTPUT_MEDIA_TYPE)],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _RamlDumper(yaml.SafeDumper):
    """Block-style YAML with no anchors; multi-line strings as ``|`` blocks."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    style = "|" if "\n" in value.strip() else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_RamlDumper.add_representer(str, _represent_str)


class _RamlWriter:
    """Builds one RAML document (single use per export)."""

    def __init__(self, api: CanonicalApi, options: RamlEmitOptions) -> None:
        self._api = api
        self._options = options
        self._raml_source = api.format == _RAML_FORMAT
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.output_path = _output_path(api)
        self._names = RamlNames(api)
        self._plan = _plan(api)
        self._owners = _path_parameter_owners(self._plan)
        self._positional = {key for t in api.types if t.kind is TypeKind.RECORD for key in _positional_fields(t)}
        self._media_type = self._document_media_type()

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Render the document: the ``#%RAML 1.0`` header, then the YAML body."""
        api = self._api
        for note in _document_notes(api):
            self._loss(note, "")
        document: Dict[str, Any] = {"title": _title(api)}
        if api.description:
            document["description"] = api.description
        if api.version:
            document["version"] = api.version
        if api.servers:
            server = api.servers[0]
            document["baseUri"] = server.url
            params = self._base_uri_parameters(server.variables)
            if params:
                document["baseUriParameters"] = params
        document["mediaType"] = self._media_type
        types = {self._names.names[t.key]: self._type(t) for t in api.types}
        if types:
            document["types"] = types
        for channel in api.channels:
            self._loss(Note("channel-dropped", f"RAML has no event channels; {channel.key!r} is not written"),
                       channel.key)
        for key, reason in self._plan.dropped.items():
            self._loss(Note("operation-dropped", f"{reason}; the operation is not written"), key)
        for path, methods in self._resources().items():
            document[path] = methods

        header = [_RAML_HEADER]
        if self._options.include_comments:
            header.append(f"# Generated by Apiome from {_comment_safe(api.identity.name or _title(api))}")
        body = yaml.dump(document, Dumper=_RamlDumper, sort_keys=False, default_flow_style=False,
                         allow_unicode=True, width=1_000_000)
        return "\n".join(header) + "\n" + body

    def _document_media_type(self) -> str:
        """A RAML source's own ``mediaType``; else the one the bodies use most; else the option."""
        own = self._api.extras.get("raml_media_type") if self._raml_source else None
        if isinstance(own, str) and own:
            return own
        counts = Counter(
            message.content_types[0]
            for operation in self._plan.kept.values()
            for message in operation.messages
            if message.content_types
        )
        return counts.most_common(1)[0][0] if counts else self._options.media_type

    @staticmethod
    def _base_uri_parameters(variables: Iterable[Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for variable in variables:
            if variable.name == "version":  # RAML fills {version} from `version`
                continue
            spec: Dict[str, Any] = {"type": "string"}
            if variable.description:
                spec["description"] = variable.description
            if variable.enum:
                spec["enum"] = list(variable.enum)
            if variable.default is not None:
                spec["default"] = variable.default
            out[variable.name] = spec
        return out

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def _type(self, type_: Type) -> Dict[str, Any]:
        """One ``types`` entry."""
        for note in _type_notes(type_, self._names):
            self._loss(note, type_.key)
        spec: Dict[str, Any] = {}
        if type_.kind is TypeKind.RECORD:
            spec["type"] = "object"
            properties = {}
            for field_ in _ordered_fields(type_):
                name, value = self._property(field_)
                properties[name] = value
            if properties:
                spec["properties"] = properties
        elif type_.kind is TypeKind.ENUM:
            spec["type"] = "string"
            spec["enum"] = [value.name for value in type_.enum_values]
        elif type_.kind is TypeKind.UNION:
            members = [self._names.names.get(self._names.type_key(m) or "", "any") for m in type_.union_members]
            spec["type"] = " | ".join(members) if members else "any"
        elif type_.kind is TypeKind.ALIAS:
            expression = self._names.expression(type_.aliased, constraints=type_.constraints)
            spec["type"] = expression.expr
            spec.update(expression.facets)
        elif type_.kind is TypeKind.MAP:
            spec["type"] = "object"
            spec["properties"] = {"//": self._names.expression(type_.value_type).expr}
        else:  # SCALAR
            expression = _scalar_type(type_, self._names)
            spec["type"] = expression.expr
            spec.update(expression.facets)
        if type_.description:
            spec = {"description": type_.description, **spec}
        self.tracker.record(type_.key, Provenance.SOURCE)
        return spec

    def _property(self, field_: CanonicalField) -> Tuple[str, Any]:
        """One record property: ``name`` (``name?`` when optional) and its type or declaration."""
        for note in _field_notes(field_, self._names):
            self._loss(note, field_.key)
        if field_.field_number is not None and field_.key not in self._positional:
            self._loss(Note("field-number-dropped", f"RAML has no field numbers; {field_.field_number} is dropped"),
                       field_.key)
        expression = self._names.expression(
            field_.type, constraints=field_.constraints, hint=field_.extras.get("raml_type")
        )
        name = field_.name if field_.type.nullable is False else f"{field_.name}?"
        self.tracker.record(field_.key, Provenance.SOURCE)
        spec = self._declaration(expression, field_.description, field_.default)
        return name, spec

    @staticmethod
    def _declaration(expression: _Expression, description: Optional[str], default: Any) -> Any:
        """The short form (``string``) when there is nothing else to say, else a type declaration."""
        if not expression.facets and description is None and default is None:
            return expression.expr
        spec: Dict[str, Any] = {"type": expression.expr}
        if description:
            spec["description"] = description
        spec.update(expression.facets)
        if default is not None:
            spec["default"] = _plain(default)
        return spec

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    def _resources(self) -> Dict[str, Dict[str, Any]]:
        """Every resource path → its ``uriParameters`` and methods, sorted by path."""
        by_path: Dict[str, Dict[str, Operation]] = {}
        for (path, method), operation in self._plan.kept.items():
            by_path.setdefault(path, {})[method] = operation
        out: Dict[str, Dict[str, Any]] = {}
        for path in sorted(by_path):
            resource: Dict[str, Any] = {}
            uri_params = {
                name: self._parameter(param)
                for (owner_path, name), param in self._owners.items()
                if owner_path == path
            }
            if uri_params:
                resource["uriParameters"] = uri_params
            for method in _METHODS:
                operation = by_path[path].get(method)
                if operation is not None:
                    resource[method] = self._method(operation)
            out[path] = resource
        return out

    def _method(self, operation: Operation) -> Dict[str, Any]:
        """One method: name, description, query parameters, headers, body and responses."""
        for note in _operation_notes(operation, self._names, self._owners, self._raml_source):
            self._loss(note, operation.key)
        spec: Dict[str, Any] = {}
        if _has_explicit_name(operation):
            spec["displayName"] = operation.name
        if operation.description:
            spec["description"] = operation.description
        query = {p.name: self._parameter(p) for p in operation.parameters if p.location is ParameterLocation.QUERY}
        if query:
            spec["queryParameters"] = query
        headers = {p.name: self._parameter(p) for p in operation.parameters if p.location is ParameterLocation.HEADER}
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is not None:
            for header in request.headers:
                headers.setdefault(header.name, self._header(header))
        if headers:
            spec["headers"] = headers
        if request is not None:
            body = self._body(request)
            if body:
                spec["body"] = body
        responses = self._responses(operation)
        if responses:
            spec["responses"] = responses
        self.tracker.record(operation.key, Provenance.SOURCE)
        return spec

    def _parameter(self, param: Parameter) -> Any:
        """A ``uriParameters`` / ``queryParameters`` / ``headers`` entry (RAML parameters are required by default)."""
        expression = self._names.expression(
            param.type, constraints=param.constraints, hint=param.extras.get("raml_type")
        )
        spec = self._declaration(expression, param.description, param.default)
        if not param.required:
            spec = spec if isinstance(spec, dict) else {"type": spec}
            spec["required"] = False
        self.tracker.record(param.key, Provenance.SOURCE)
        return spec

    def _header(self, header: CanonicalField) -> Any:
        expression = self._names.expression(header.type, constraints=header.constraints)
        spec = self._declaration(expression, header.description, header.default)
        if header.type.nullable is not False:
            spec = spec if isinstance(spec, dict) else {"type": spec}
            spec["required"] = False
        return spec

    def _body(self, message: Message) -> Dict[str, Any]:
        """``media type → type declaration`` for a message body; empty when it has none."""
        if message.payload is not None:
            spec: Dict[str, Any] = {"type": self._names.expression(message.payload).expr}
        elif message.payload_schema:
            spec = {"type": json.dumps(message.payload_schema, indent=2, sort_keys=True)}
        else:
            return {}
        if message.description and message.role is MessageRole.REQUEST:
            spec["description"] = message.description
        return {media: dict(spec) for media in (message.content_types or [self._media_type])}

    def _responses(self, operation: Operation) -> Dict[int, Dict[str, Any]]:
        """``status → response`` for the operation's single-code responses, first one per status."""
        out: Dict[int, Dict[str, Any]] = {}
        for message in _messages_in_write_order(operation):
            if message.role not in (MessageRole.RESPONSE, MessageRole.ERROR):
                continue
            raw = message.status_code or message.extras.get("http_status")
            status = _status(message) or (None if raw else "200")
            if status is None or int(status) in out:
                continue
            response: Dict[str, Any] = {}
            if message.description:
                response["description"] = message.description
            if message.headers:
                response["headers"] = {h.name: self._header(h) for h in message.headers}
            body = self._body(message)
            if body:
                response["body"] = body
            out[int(status)] = response
        return out

    # ------------------------------------------------------------------

    def _loss(self, note: Note, pointer: str) -> None:
        self.losses.record(LossKind.NA if note.dropped else LossKind.INFERRED, note.subject,
                           f"RAML: {note.message}.", pointer=pointer)


def _comment_safe(text: str) -> str:
    return " ".join(str(text).split())


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.raml"
