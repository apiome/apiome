"""API Blueprint emitter: canonical model → API Blueprint 1A (Markdown + MSON) — MFX-18.1 (#3905).

The inverse of :class:`app.apiblueprint_normalizer.ApiblueprintNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI. API Blueprint is a legacy, human-readable format, so the export
is positioned as **documentation**: what a reader of the API needs (resources, actions, parameters,
bodies, data structures, descriptions) is written; validation rules MSON cannot express are not.

**Document.** ``FORMAT: 1A`` and ``HOST`` (the first server) metadata first — drafter only reads
metadata at the very top — then ``# <title>``, an optional generated-by comment, and the description.

**Resources.** One ``## <name> [<path>]`` resource per path, sorted. Path parameters (those in the
path template) are the resource's ``+ Parameters``; each operation is a ``### <name> [<METHOD>]``
action with its description, its own ``+ Parameters`` (query parameters, whose names go in the
action's URI template ``{?limit,offset}``, and path parameters the template does not name), a
``+ Request (<media type>)`` with ``+ Attributes (<type>)``, and one ``+ Response <status>`` per
status code with its ``+ Attributes``. Inline JSON Schema bodies are written as ``+ Schema``
sections. A parameter's or property's default is a nested ``+ Default:``.

**Data Structures.** Records are ``## <Name> (object)`` with one MSON property per field, in
field-number order (``+ name: sample (type, required) - description``); enums are ``(enum)`` with
their members. MSON has three primitives — ``string``, ``number``, ``boolean`` — so wider scalar
vocabularies are written as the nearest one and reported. Aliases, named scalars, maps and unions
become named types based on what they wrap. An API Blueprint source's own spellings (its MSON type
expressions, samples and inheritance bases) are written back as they were read.

**Not carried, and reported** (by the writer as losses and by
:class:`ApiblueprintFidelityRulePack` before an emit — both from the same helpers): validation
constraints (MSON has no facets: ``DROP``), operations with no HTTP binding, event operations and
channels, a second operation on one method and path, header and cookie parameters, status ranges,
response headers and descriptions, servers beyond the first, server variables, the API version,
deprecation, tags, streaming, field numbers that are not positional, and source-specific details.
Validation of the output is :func:`app.export_validation.validate_emitted_artifact`: drafter's
errors when the toolchain has it, else a re-parse through the API Blueprint reader.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

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
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
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

__all__ = ["ApiblueprintEmitOptions", "ApiblueprintEmitter", "ApiblueprintFidelityRulePack", "mson_scalar"]

_APIB_FORMAT = "apiblueprint"
_DEFAULT_MEDIA_TYPE = "application/json"
_METHOD = re.compile(r"^[A-Z]+$")
_STATUS = re.compile(r"^[1-5][0-9]{2}$")
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
#: A name the reader takes as written: an MSON property, parameter or type name without escaping.
_PLAIN_NAME = re.compile(r"^\w+$")
#: A sample or default written without backticks (the reader stops a bare value at whitespace).
_BARE_VALUE = re.compile(r"^[^\s`(][^\s`]*$")
#: Path template variables: ``{id}`` (not the query expansion ``{?limit}``).
_PATH_VARIABLE = re.compile(r"\{([^}?&]+)\}")

#: MSON's base types. A named type may not take one of these names.
_MSON_BASE_TYPES = frozenset({"array", "boolean", "enum", "number", "object", "string"})

#: Scalar kind (:mod:`app.scalar_aliases`) → MSON primitive. MSON has one number type.
_KIND_TO_MSON: Dict[str, str] = {
    "bool": "boolean",
    "int8": "number",
    "int16": "number",
    "int32": "number",
    "int64": "number",
    "uint8": "number",
    "uint16": "number",
    "uint32": "number",
    "uint64": "number",
    "float": "number",
    "double": "number",
    "string": "string",
    "bytes": "string",
}
#: Canonical spellings the API Blueprint reader produces, which round-trip exactly.
_EXACT = {"string": "string", "double": "number", "number": "number", "bool": "boolean", "boolean": "boolean",
          "object": "object", "array": "array"}
#: Other spellings with a natural MSON primitive (dates and identifiers are strings).
_NAMED_TO_MSON: Dict[str, str] = {
    "date": "string", "date-only": "string", "time": "string", "time-only": "string", "datetime": "string",
    "datetime-only": "string", "date-time": "string", "timestamp": "string", "duration": "string",
    "uuid": "string", "uri": "string", "url": "string", "email": "string", "decimal": "number",
    "integer": "number", "int": "number", "any": "string", "null": "string", "nil": "string",
    "map": "object", "file": "string",
}


# ===========================================================================
# Scalars and type expressions
# ===========================================================================


def mson_scalar(name: Optional[str]) -> Optional[Tuple[str, bool]]:
    """Return the MSON primitive of a canonical scalar, or ``None`` when ``name`` is not a scalar.

    Args:
        name: The :class:`~app.canonical_model.TypeRef` name (``string``, ``i64``, ``date-time`` …).

    Returns:
        ``(primitive, exact)``: the MSON primitive (``string`` / ``number`` / ``boolean`` /
        ``object`` / ``array``) and whether reading it back gives the same canonical name. ``None``
        for a name that is not a scalar (a named type).
    """
    if not name:
        return None
    key = name.strip().lower()
    if key in _EXACT:
        return _EXACT[key], name in ("string", "double", "bool", "object", "array")
    if key in _NAMED_TO_MSON:
        return _NAMED_TO_MSON[key], False
    kind = scalar_kind(name)
    if kind is None:
        return None
    return _KIND_TO_MSON[kind], False


@dataclass
class Note:
    """One thing the API Blueprint output does not carry as the source has it.

    Shared by the writer (a :class:`~app.emitter.Loss`) and :class:`ApiblueprintFidelityRulePack` (a
    verdict), so the export and its prediction say the same thing.

    Attributes:
        subject: Loss slug (``constraints-dropped``).
        message: What happened, in a sentence fragment.
        dropped: ``True`` when something is not written at all (``n/a``), ``False`` when it is written
            differently (``inferred``).
        severity: How much it matters for the fidelity report.
    """

    subject: str
    message: str
    dropped: bool = True
    severity: LossinessSeverity = LossinessSeverity.INFO


class ApibNames:
    """The MSON name of every named type of one model, and the MSON spelling of a type reference.

    MSON type names here are word characters only (what the reader takes as a type name) and may
    not be a base type, so other names are rewritten (``com.acme.Order`` → ``com_acme_Order``) and
    kept unique.

    Args:
        api: The model being exported.
    """

    def __init__(self, api: CanonicalApi) -> None:
        taken = set(_MSON_BASE_TYPES)
        #: Type key → the name the type is declared under.
        self.names: Dict[str, str] = {}
        for type_ in api.types:
            name = re.sub(r"\W+", "_", type_.name or "").strip("_") or "Type"
            candidate, suffix = name, 2
            while candidate.lower() in taken:
                candidate, suffix = f"{name}{suffix}", suffix + 1
            taken.add(candidate.lower())
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

    def expression(self, ref: Optional[TypeRef], hint: Optional[str] = None) -> Tuple[str, List[Note]]:
        """Spell a type reference in MSON.

        Args:
            ref: The reference (``None`` is an untyped value).
            hint: An API Blueprint source's own spelling (``apib_type``), written back as it was.

        Returns:
            The expression (``string``, ``Book``, ``array[Book]``) and what it could not carry.
        """
        if hint:
            return hint, []
        notes: List[Note] = []
        return self._expr(ref, notes), notes

    def _expr(self, ref: Optional[TypeRef], notes: List[Note]) -> str:
        if ref is None or (ref.name is None and ref.item is None):
            notes.append(Note("untyped-value", "MSON values have a type; an untyped value is written as string",
                              dropped=False))
            return "string"
        if ref.item is not None:
            return f"array[{self._expr(ref.item, notes)}]"
        key = self.type_key(ref.name)
        if key is not None:
            return self.names[key]
        scalar = mson_scalar(ref.name)
        if scalar is not None:
            primitive, exact = scalar
            if not exact and ref.name.lower() != primitive:
                notes.append(Note("scalar-widened", f"MSON has no {ref.name!r} type; it is written as {primitive}",
                                  dropped=False))
            return primitive
        notes.append(Note("unknown-type", f"the type {ref.name!r} is not declared; it is written as string",
                          dropped=False))
        return "string"


def _constraint_notes(constraints: Optional[Constraints], owner: str) -> List[Note]:
    """MSON has no validation facets: every set constraint is a note (``DROP``)."""
    if constraints is None:
        return []
    facets = sorted(constraints.model_dump(exclude={"extras"}, exclude_none=True, exclude_defaults=True))
    if not facets:
        return []
    return [Note("constraints-dropped", f"MSON has no validation facets; the {owner}'s {', '.join(facets)} "
                 "not written", severity=LossinessSeverity.WARN)]


def _value_text(value: Any) -> Optional[str]:
    """A sample or default as MSON writes it (``true``, ``5``, text), or ``None`` for a structured value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float, str)):
        return str(value)
    return None


def _quoted(text: str) -> str:
    """``text`` bare when the reader takes it as written, else in backticks."""
    return text if _BARE_VALUE.match(text) else f"`{text}`"


def _member_name(name: str) -> str:
    """A property name, escaped in backticks when it is not plain word characters."""
    return name if _PLAIN_NAME.match(name) else f"`{name}`"


def _one_line(text: Optional[str]) -> Optional[str]:
    """A description on one line (MSON descriptions after ``-`` end at the line)."""
    if not text:
        return None
    return " ".join(text.split()) or None


def _description_block(text: Optional[str]) -> List[str]:
    """The lines of a description block: stripped, non-empty, as the reader reads them back."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _reflow_notes(text: Optional[str], owner: str, *, block: bool = True) -> List[Note]:
    """A note when the description does not read back as written (blank lines, markup, line breaks)."""
    if not text:
        return []
    if block:
        lines = _description_block(text)
        kept = "\n".join(line for line in lines if not line.startswith(("+", "#")))
        if kept == text:
            return []
    elif _one_line(text) == text:
        return []
    return [Note("description-reflowed", f"the {owner} description is written as API Blueprint text; its "
                 "line breaks are not kept", dropped=False)]


# ===========================================================================
# What API Blueprint cannot carry — shared by the writer and the rule pack
# ===========================================================================


@dataclass
class _Plan:
    """Which operations are written, on which resource, and why the others are not."""

    #: ``(path, METHOD)`` → the operation written there, in model order.
    kept: Dict[Tuple[str, str], Operation] = field(default_factory=dict)
    #: Operation key → why it is not written.
    dropped: Dict[str, str] = field(default_factory=dict)


def _plan(api: CanonicalApi) -> _Plan:
    """Place every operation on an API Blueprint resource and action, or say why it cannot be."""
    plan = _Plan()
    for operation in api.operations():
        if operation.kind in _EVENT_OPERATION_KINDS:
            plan.dropped[operation.key] = "API Blueprint has no event operations"
            continue
        method = (operation.http_method or "").upper()
        if not _METHOD.match(method) or not operation.http_path:
            plan.dropped[operation.key] = (
                "API Blueprint describes HTTP resources only; the operation has no HTTP method and path"
            )
            continue
        slot = (_resource_path(operation.http_path), method)
        if slot in plan.kept:
            plan.dropped[operation.key] = (
                f"{plan.kept[slot].key!r} is already written as {method} {slot[0]}; API Blueprint has one action "
                "per method and resource"
            )
            continue
        plan.kept[slot] = operation
    return plan


def _resource_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def _template_names(path: str) -> List[str]:
    return _PATH_VARIABLE.findall(path)


def _status(message: Message) -> Optional[str]:
    """The message's HTTP status when it is a single code (``404``), else ``None`` (``4XX``)."""
    raw = str(message.status_code or message.extras.get("http_status") or "")
    return raw if _STATUS.match(raw) else None


def _raw_status(message: Message) -> Optional[str]:
    raw = message.status_code or message.extras.get("http_status")
    return str(raw) if raw else None


def _messages_in_write_order(operation: Operation) -> List[Message]:
    """The operation's messages, those with a status first: a response with none only gets 200 if it is free."""
    return sorted(operation.messages, key=lambda m: _raw_status(m) is None)


def _same_parameter(a: Parameter, b: Parameter) -> bool:
    exclude = {"key", "extras"}
    return a.model_dump(exclude=exclude) == b.model_dump(exclude=exclude)


def _resource_parameters(plan: _Plan) -> Dict[Tuple[str, str], Parameter]:
    """``(path, name)`` → the path parameter a resource declares (the first operation's).

    Only parameters the path template names (``{id}``) belong to the resource; any other is written
    on its action.
    """
    owners: Dict[Tuple[str, str], Parameter] = {}
    for (path, _method), operation in plan.kept.items():
        named = set(_template_names(path))
        for param in operation.parameters:
            if param.location is ParameterLocation.PATH and param.name in named:
                owners.setdefault((path, param.name), param)
    return owners


def _action_parameters(operation: Operation, path: str) -> List[Parameter]:
    """The parameters written on the action: query parameters and path parameters the template lacks."""
    named = set(_template_names(path))
    return [
        param
        for param in operation.parameters
        if param.location is ParameterLocation.QUERY
        or (param.location is ParameterLocation.PATH and param.name not in named)
    ]


def _parameter_notes(param: Parameter, names: ApibNames, apib_source: bool) -> List[Note]:
    """What a written parameter loses."""
    _expr, notes = names.expression(param.type, param.extras.get("apib_type") if apib_source else None)
    notes = list(notes)
    notes.extend(_constraint_notes(param.constraints, f"parameter {param.name!r}"))
    notes.extend(_reflow_notes(param.description, f"parameter {param.name!r}", block=False))
    if param.default is not None and _value_text(param.default) is None:
        notes.append(Note("default-dropped", f"MSON defaults are single values; {param.name!r}'s is not written"))
    if param.deprecated:
        notes.append(Note("deprecated-dropped", f"API Blueprint has no deprecation flag; parameter {param.name!r} "
                          "is not marked deprecated"))
    return notes


def _operation_notes(
    operation: Operation, names: ApibNames, owners: Dict[Tuple[str, str], Parameter], apib_source: bool
) -> List[Note]:
    """What a written operation loses (its parameters, messages and details)."""
    notes: List[Note] = []
    path = _resource_path(operation.http_path or "/")
    for param in operation.parameters:
        if param.location in (ParameterLocation.HEADER, ParameterLocation.COOKIE):
            notes.append(Note("parameter-dropped", f"API Blueprint has no typed {param.location.value} parameters; "
                              f"{param.name!r} is not written", severity=LossinessSeverity.WARN))
            continue
        if param.location is ParameterLocation.PATH:
            owner = owners.get((path, param.name))
            if owner is not None and owner is not param and not _same_parameter(owner, param):
                notes.append(Note("parameter-merged",
                                  f"the path parameter {param.name!r} is declared once for {path}; this operation's "
                                  "definition differs and is not written", severity=LossinessSeverity.WARN))
                continue
        notes.extend(_parameter_notes(param, names, apib_source))
    request_written = False
    seen: set = set()
    for message in _messages_in_write_order(operation):
        if message.role is MessageRole.EVENT:
            notes.append(Note("message-dropped", f"API Blueprint has no event messages; {message.key!r} is not "
                              "written"))
            continue
        if message.role is MessageRole.REQUEST:
            if request_written:
                notes.append(Note("message-dropped", f"one request is written per action; {message.key!r} is not"))
                continue
            request_written = True
            notes.extend(_body_notes(message, names, apib_source))
            if message.payload is not None and not message.content_types:
                notes.append(Note("media-type-synthesized", f"an API Blueprint request names its media type; "
                                  f"{_DEFAULT_MEDIA_TYPE} is written", dropped=False))
            continue
        status = _status(message)
        raw = _raw_status(message)
        if status is None and raw:
            notes.append(Note("status-range-dropped", f"API Blueprint responses are single status codes; the "
                              f"{raw!r} response is not written", severity=LossinessSeverity.WARN))
            continue
        status = status or "200"
        if status in seen:
            notes.append(Note("response-dropped", f"a {status} response is already written; {message.key!r} is not"))
            continue
        seen.add(status)
        if raw is None:
            notes.append(Note("status-synthesized", f"the response {message.key!r} has no status; it is written as "
                              "200", dropped=False))
        notes.extend(_body_notes(message, names, apib_source))
        if message.headers:
            notes.append(Note("headers-dropped", f"API Blueprint response headers carry values, not types; the "
                              f"headers of {message.key!r} are not written"))
        if message.description:
            notes.append(Note("response-description-dropped", f"the description of {message.key!r} is not written"))
    notes.extend(_reflow_notes(operation.description, "operation"))
    if "[" in (operation.name or "") or "]" in (operation.name or ""):
        notes.append(Note("operation-renamed", "API Blueprint action names cannot contain brackets; they are "
                          "removed", dropped=False))
    if operation.deprecated:
        notes.append(Note("deprecated-dropped", "API Blueprint has no deprecation flag; the operation is not "
                          "marked deprecated"))
    if operation.tags:
        notes.append(Note("tags-dropped", f"API Blueprint actions have no tags; {', '.join(operation.tags)} not "
                          "written"))
    if operation.streaming is not StreamingMode.NONE:
        notes.append(Note("streaming-dropped", f"API Blueprint has no streaming; the {operation.streaming.value} "
                          "stream is written as one request and response", dropped=False,
                          severity=LossinessSeverity.WARN))
    if not apib_source and operation.extras:
        notes.append(Note("operation-details-dropped",
                          f"source-specific details ({', '.join(sorted(operation.extras))}) are not written"))
    return notes


def _body_notes(message: Message, names: ApibNames, apib_source: bool) -> List[Note]:
    """What a written request or response body loses."""
    if message.payload is not None:
        notes = list(names.expression(message.payload)[1])
        if len(message.content_types) > 1:
            notes.append(Note("media-types-dropped", f"one media type is written per body; "
                              f"{', '.join(message.content_types[1:])} not written"))
        return notes
    if message.payload_schema:
        return [Note("inline-schema", f"the inline schema of {message.key!r} is written as a Schema section, not "
                     "as MSON attributes", dropped=False)]
    return []


def _type_notes(type_: Type, names: ApibNames, apib_source: bool) -> List[Note]:
    """What a declared type loses (not its fields: see :func:`_field_notes`)."""
    notes: List[Note] = []
    written = names.names[type_.key]
    if written != type_.name:
        notes.append(Note("type-renamed", f"MSON type names are word characters; {type_.name!r} is written as "
                          f"{written!r}", dropped=False))
    if type_.namespace or type_.key not in (written, type_.name):
        notes.append(Note("namespace-dropped", f"API Blueprint has no namespaces; {type_.key!r} is declared as "
                          f"{written!r}"))
    if type_.deprecated:
        notes.append(Note("deprecated-dropped", "API Blueprint has no deprecation flag; the type is not marked "
                          "deprecated"))
    notes.extend(_reflow_notes(type_.description, "type"))
    if type_.kind is TypeKind.ENUM:
        positional = all(value.value in (None, index, value.name) for index, value in enumerate(type_.enum_values))
        if not positional:
            notes.append(Note("enum-values-dropped", "MSON enums list members only; the values' numbers are not "
                              "written"))
        if any(value.description or value.deprecated for value in type_.enum_values):
            notes.append(Note("enum-docs-dropped", "MSON enum members carry no description or deprecation"))
    elif type_.kind is TypeKind.UNION:
        notes.append(Note("union-as-enum", "MSON has no union types; the members are written as the types of an "
                          "enum", dropped=False, severity=LossinessSeverity.WARN))
    elif type_.kind is TypeKind.ALIAS:
        notes.append(Note("alias-as-named-type", "the alias is written as a named type based on what it wraps",
                          dropped=False))
        notes.extend(names.expression(type_.aliased)[1])
    elif type_.kind is TypeKind.MAP:
        notes.append(Note("map-as-object", "MSON has no map types; the map is written as an object and its key and "
                          "value types are not written", severity=LossinessSeverity.WARN))
    elif type_.kind is TypeKind.SCALAR:
        base = (mson_scalar(type_.name) or ("string", False))[0]
        notes.append(Note("scalar-as-named-type", f"the scalar is written as a named {base} type", dropped=False))
    if type_.kind is not TypeKind.RECORD:
        notes.extend(_constraint_notes(type_.constraints, "type"))
    if type_.kind is TypeKind.RECORD and apib_source is False and type_.extras:
        notes.append(Note("type-details-dropped",
                          f"source-specific details ({', '.join(sorted(type_.extras))}) are not written"))
    return notes


def _field_notes(field_: CanonicalField, names: ApibNames, apib_source: bool) -> List[Note]:
    """What a record field loses (its type, description, default and flags; constraints are the rule pack's)."""
    notes = list(names.expression(field_.type, field_.extras.get("apib_type") if apib_source else None)[1])
    notes.extend(_reflow_notes(field_.description, "field", block=False))
    if field_.default is not None and _value_text(field_.default) is None:
        notes.append(Note("default-dropped", "MSON defaults are single values; the field's default is not written"))
    if field_.deprecated:
        notes.append(Note("deprecated-dropped", "API Blueprint has no deprecation flag; the field is not marked "
                          "deprecated"))
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
    """What the document envelope loses: services, identity, version, extra servers, source details."""
    notes: List[Note] = []
    if not api.title:
        notes.append(Note("title-synthesized", f"API Blueprint names the API by a title; {_title(api)!r} is used",
                          dropped=False))
    if len(api.servers) > 1:
        notes.append(Note("servers-dropped", f"API Blueprint has one HOST; {api.servers[0].url!r} is used and "
                          f"{len(api.servers) - 1} other server(s) are not written"))
    if api.servers and api.servers[0].variables:
        notes.append(Note("server-variables-dropped", "API Blueprint's HOST has no variables; they are not written"))
    if api.agents:
        notes.append(Note("agents-dropped", f"API Blueprint has no agent descriptors; {len(api.agents)} are not "
                          "written"))
    notes.extend(_reflow_notes(api.description, "API"))
    if api.format == _APIB_FORMAT:
        return notes
    if api.version:
        notes.append(Note("version-dropped", f"API Blueprint has no API version; {api.version!r} is not written"))
    if api.services:
        listed = ", ".join(repr(service.name) for service in api.services[:3])
        more = f" and {len(api.services) - 3} more" if len(api.services) > 3 else ""
        notes.append(Note("services-merged", f"the operations of service(s) {listed}{more} become resources of one "
                          "blueprint", dropped=False))
    if api.identity.namespace or api.identity.id or api.identity.name != _title(api):
        notes.append(Note("identity-dropped", "API Blueprint names an API by its title only; the source identity "
                          "is not written"))
    if api.servers and (api.servers[0].name or api.servers[0].description):
        notes.append(Note("server-details-dropped", "API Blueprint's HOST has no name or description"))
    if api.extras:
        notes.append(Note("document-details-dropped",
                          f"source-specific details ({', '.join(sorted(api.extras))}) are not written"))
    if not notes:
        notes.append(Note("document-rewritten", "the document is written as API Blueprint 1A (title, description "
                          "and HOST)", dropped=False))
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
        message="API Blueprint: " + "; ".join(note.message for note in notes),
        severity=severity,
        target_mapping=target_mapping,
    )


class ApiblueprintFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for API Blueprint export.

    On top of the capability rules, every verdict comes from the same helpers the writer reports
    its losses with: operations API Blueprint cannot place (no HTTP binding, a second operation on
    one method and path), what a written operation, type or field loses, the document envelope
    (services, identity, version, extra servers), and field numbers MSON's property order cannot
    keep. Validation constraints are a ``DROP``: MSON has no facets to write them in.
    """

    target_label = "API Blueprint"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Prepare the model-wide facts the per-construct hooks need, then run the drive loop."""
        self._api = api
        self._apib_source = api.format == _APIB_FORMAT
        self._names = ApibNames(api)
        self._plan = _plan(api)
        self._owners = _resource_parameters(self._plan)
        self._positional = {key for t in api.types if t.kind is TypeKind.RECORD for key in _positional_fields(t)}
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        notes = _document_notes(api)
        synthesized = [n for n in notes if n.subject == "title-synthesized"]
        verdicts = [
            FidelityVerdict.synth(message=f"API Blueprint: {n.message}", severity=LossinessSeverity.INFO,
                                  target_mapping="title") for n in synthesized
        ]
        rest = _verdict([n for n in notes if n not in synthesized], "document → API Blueprint")
        return [*verdicts, *([rest] if rest else [])]

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        verdict = super().operation_verdict(operation)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        reason = self._plan.dropped.get(operation.key)
        if reason:
            return FidelityVerdict.drop(message=f"{reason}; the operation is dropped", target_mapping="dropped")
        notes = _operation_notes(operation, self._names, self._owners, self._apib_source)
        return _verdict(notes, "operation → resource action") or verdict

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        notes = _type_notes(type_, self._names, self._apib_source)
        return _verdict(notes, f"{type_.kind.value} → MSON type") or verdict

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        verdicts = super().field_verdicts(field)
        own = _verdict(_field_notes(field, self._names, self._apib_source), "field → MSON property")
        return [*verdicts, *([own] if own else [])]

    def _constraints_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """MSON has no validation facets: a field's constraints are dropped."""
        notes = _constraint_notes(field.constraints, "field")
        if not notes:
            return None
        return FidelityVerdict.drop(message=f"API Blueprint: {notes[0].message}", severity=LossinessSeverity.WARN,
                                    target_mapping="constraints → dropped")

    def _field_identity_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """Field numbers equal to the property's position survive (MSON keeps property order)."""
        if field.field_number is not None and field.key not in self._positional:
            return FidelityVerdict.drop(
                message=f"API Blueprint has no field numbers; properties keep their order but number "
                f"{field.field_number} is dropped",
                severity=LossinessSeverity.INFO,
            )
        return None


# ===========================================================================
# Emitter
# ===========================================================================


class ApiblueprintEmitOptions(EmitOptions):
    """Per-target options for :class:`ApiblueprintEmitter`."""

    format_version: str = Field(default="1A", description="API Blueprint `FORMAT` value.")
    include_comments: bool = Field(
        default=True,
        description="Write a generated-file HTML comment under the API title.",
    )
    media_type: str = Field(
        default=_DEFAULT_MEDIA_TYPE,
        description="The media type of a request body whose source names none.",
    )


class ApiblueprintEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an API Blueprint 1A document."""

    key = "apiblueprint"
    format = "apiblueprint"
    label = "API Blueprint"
    description = "Export as an API Blueprint 1A document (Markdown + MSON), for human-readable docs."
    icon = "file-text"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = ApiblueprintEmitOptions
    requires_source = ("http-operation-or-type",)

    OUTPUT_MEDIA_TYPE = "text/markdown"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=True,
            constraints=False,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return ApiblueprintFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ApiblueprintEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, ApiblueprintEmitOptions)
            else ApiblueprintEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _ApiblueprintWriter(api, options)
        content = writer.render()
        return EmitResult(
            files=[EmittedFile(path=writer.output_path, content=content, media_type=self.OUTPUT_MEDIA_TYPE)],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _ApiblueprintWriter:
    """Builds one API Blueprint document (single use per export)."""

    def __init__(self, api: CanonicalApi, options: ApiblueprintEmitOptions) -> None:
        self._api = api
        self._options = options
        self._apib_source = api.format == _APIB_FORMAT
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.output_path = _output_path(api)
        self._names = ApibNames(api)
        self._plan = _plan(api)
        self._owners = _resource_parameters(self._plan)
        self._positional = {key for t in api.types if t.kind is TypeKind.RECORD for key in _positional_fields(t)}

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Render the document: metadata, title, description, resources, then data structures."""
        api = self._api
        if not self._plan.kept and not api.types:
            raise EmitPreconditionError(
                "API Blueprint export needs at least one HTTP operation or one type; this source has neither."
            )
        for note in _document_notes(api):
            self._loss(note, "")
        lines: List[str] = [f"FORMAT: {self._format_version()}"]
        host = self._host()
        if host:
            lines.append(f"HOST: {host}")
        lines += ["", f"# {_title(api)}", ""]
        if self._options.include_comments:
            lines += [f"<!-- Generated by Apiome from {_comment_safe(api.identity.name or _title(api))} -->", ""]
        description = [line for line in _description_block(api.description) if not line.startswith(("+", "#"))]
        if description:
            lines += [*description, ""]

        for channel in api.channels:
            self._loss(Note("channel-dropped", f"API Blueprint has no event channels; {channel.key!r} is not written"),
                       channel.key)
        for key, reason in self._plan.dropped.items():
            self._loss(Note("operation-dropped", f"{reason}; the operation is not written"), key)
        lines += self._resources()

        if api.types:
            lines += ["# Data Structures", ""]
            for type_ in api.types:
                lines += [*self._type(type_), ""]
        return "\n".join(lines).rstrip() + "\n"

    def _format_version(self) -> str:
        own = self._api.extras.get("apib_format_version") if self._apib_source else None
        return str(own) if isinstance(own, str) and own else self._options.format_version

    def _host(self) -> Optional[str]:
        own = self._api.extras.get("apib_host") if self._apib_source else None
        if isinstance(own, str) and own:
            return own
        return self._api.servers[0].url if self._api.servers else None

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    def _resources(self) -> List[str]:
        """Every resource: ``## <name> [<path>]``, its path ``+ Parameters``, then its actions."""
        by_path: Dict[str, List[Operation]] = {}
        for (path, _method), operation in self._plan.kept.items():
            by_path.setdefault(path, []).append(operation)
        lines: List[str] = []
        for path in sorted(by_path):
            lines += [f"## {_resource_name(path)} [{path}]", ""]
            params = [param for (owner_path, _name), param in self._owners.items() if owner_path == path]
            if params:
                lines += ["+ Parameters", *_flatten([self._parameter(p, "    ") for p in params]), ""]
            for operation in by_path[path]:
                lines += self._action(operation, path)
        return lines

    def _action(self, operation: Operation, path: str) -> List[str]:
        """One action: heading, description, parameters, request and responses."""
        for note in _operation_notes(operation, self._names, self._owners, self._apib_source):
            self._loss(note, operation.key)
        method = (operation.http_method or "").upper()
        query = [p.name for p in operation.parameters if p.location is ParameterLocation.QUERY]
        uri = f" {path}{{?{','.join(query)}}}" if query else ""
        lines = [f"### {_action_name(operation)} [{method}{uri}]", ""]
        description = [line for line in _description_block(operation.description) if not line.startswith(("+", "#"))]
        if description:
            lines += [*description, ""]
        params = _action_parameters(operation, path)
        if params:
            lines += ["+ Parameters", *_flatten([self._parameter(p, "    ") for p in params]), ""]
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is not None:
            lines += self._request(request)
        lines += self._responses(operation)
        self.tracker.record(operation.key, Provenance.SOURCE)
        return lines

    def _parameter(self, param: Parameter, indent: str) -> Any:
        """A ``+ name (type, required) - description`` line, with a nested ``+ Default:`` when it has one."""
        hint = param.extras.get("apib_type") if self._apib_source else None
        expr, _notes = self._names.expression(param.type, hint)
        modifier = "required" if param.required else "optional"
        description = _one_line(param.description)
        line = f"{indent}+ {param.name} ({expr}, {modifier})" + (f" - {description}" if description else "")
        self.tracker.record(param.key, Provenance.SOURCE)
        default = _value_text(param.default) if param.default is not None else None
        return [line, f"{indent}    + Default: {_quoted(default)}"] if default is not None else line

    def _request(self, message: Message) -> List[str]:
        if message.payload is None and not message.payload_schema:
            return []
        media = message.content_types[0] if message.content_types else self._options.media_type
        return [f"+ Request ({media})", *self._body(message), ""]

    def _responses(self, operation: Operation) -> List[str]:
        """``+ Response <status>`` for the operation's single-code responses, first one per status."""
        lines: List[str] = []
        seen: set = set()
        for message in _messages_in_write_order(operation):
            if message.role not in (MessageRole.RESPONSE, MessageRole.ERROR):
                continue
            raw = _raw_status(message)
            status = _status(message) or (None if raw else "200")
            if status is None or status in seen:
                continue
            seen.add(status)
            media = f" ({message.content_types[0]})" if message.content_types else ""
            lines += [f"+ Response {status}{media}", *self._body(message), ""]
        return lines

    def _body(self, message: Message) -> List[str]:
        """``+ Attributes (<type>)`` for a typed body, or a ``+ Schema`` section for an inline schema."""
        if message.payload is not None:
            return [f"    + Attributes ({self._names.expression(message.payload)[0]})"]
        if message.payload_schema:
            schema = json.dumps(message.payload_schema, indent=2, sort_keys=True)
            return ["    + Schema", "", *(f"            {line}" for line in schema.splitlines())]
        return []

    # ------------------------------------------------------------------
    # Data structures
    # ------------------------------------------------------------------

    def _type(self, type_: Type) -> List[str]:
        """One named type: ``## <Name> (<base>)``, its description, then its members."""
        for note in _type_notes(type_, self._names, self._apib_source):
            self._loss(note, type_.key)
        for note in _constraint_notes(type_.constraints, "type") if type_.kind is TypeKind.RECORD else []:
            self._loss(note, type_.key)
        base, members = self._type_body(type_)
        lines = [f"## {self._names.names[type_.key]} ({base})"]
        description = [line for line in _description_block(type_.description) if not line.startswith(("+", "#"))]
        if description:
            lines += ["", *description, ""]
        lines += members
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _type_body(self, type_: Type) -> Tuple[str, List[str]]:
        """The type's base (``object``, ``enum``, a primitive or a named type) and its member lines."""
        if type_.kind is TypeKind.RECORD:
            own = type_.extras.get("apib_kind") if self._apib_source else None
            base = own if isinstance(own, str) and own and own != "enum" else "object"
            return base, _flatten([self._property(f) for f in _ordered_fields(type_)])
        if type_.kind is TypeKind.ENUM:
            return "enum", [f"+ {_enum_member(value.name)}" for value in type_.enum_values]
        if type_.kind is TypeKind.UNION:
            members = [self._names.expression(TypeRef(name=member))[0] for member in type_.union_members]
            return "enum", [f"+ ({member})" for member in members]
        if type_.kind is TypeKind.ALIAS:
            expr = self._names.expression(type_.aliased)[0]
            if expr.startswith("array["):
                return "array", [f"+ ({expr[len('array['):-1]})"]
            return expr, []
        if type_.kind is TypeKind.MAP:
            return "object", []
        scalar = mson_scalar(type_.name)  # SCALAR
        return (scalar[0] if scalar else "string"), []

    def _property(self, field_: CanonicalField) -> Any:
        """One MSON property line (``+ name: sample (type, required) - description``), and its default."""
        for note in _field_notes(field_, self._names, self._apib_source):
            self._loss(note, field_.key)
        for note in _constraint_notes(field_.constraints, "field"):
            self._loss(note, field_.key)
        if field_.field_number is not None and field_.key not in self._positional:
            self._loss(Note("field-number-dropped", f"API Blueprint has no field numbers; {field_.field_number} is "
                            "dropped"), field_.key)
        hint = field_.extras.get("apib_type") if self._apib_source else None
        expr, _notes = self._names.expression(field_.type, hint)
        modifiers = f"{expr}, required" if field_.type.nullable is False else expr
        sample = field_.extras.get("apib_sample") if self._apib_source else None
        sample_text = f": {self._sample(str(sample), expr)}" if sample is not None else ""
        description = _one_line(field_.description)
        line = f"+ {_member_name(field_.name)}{sample_text} ({modifiers})" + (
            f" - {description}" if description else ""
        )
        self.tracker.record(field_.key, Provenance.SOURCE)
        default = _value_text(field_.default) if field_.default is not None else None
        return [line, f"    + Default: {_quoted(default)}"] if default is not None else line

    @staticmethod
    def _sample(sample: str, expr: str) -> str:
        """A sample bare for numbers and booleans that need no quoting, else in backticks."""
        if expr in ("number", "boolean") and _BARE_VALUE.match(sample):
            return sample
        return f"`{sample}`"

    # ------------------------------------------------------------------

    def _loss(self, note: Note, pointer: str) -> None:
        self.losses.record(LossKind.NA if note.dropped else LossKind.INFERRED, note.subject,
                           f"API Blueprint: {note.message}.", pointer=pointer)


def _flatten(items: List[Any]) -> List[str]:
    """Lines, with a member's nested lines (a list) spliced in place."""
    out: List[str] = []
    for item in items:
        out.extend(item if isinstance(item, list) else [item])
    return out


def _resource_name(path: str) -> str:
    """A resource name from its path: the last literal segment, title-cased (``/books/{id}`` → ``Books``)."""
    segments = [segment for segment in path.strip("/").split("/") if segment and not segment.startswith("{")]
    if not segments:
        return "Root"
    return segments[-1].replace("-", " ").replace("_", " ").title()


def _action_name(operation: Operation) -> str:
    """The action heading's name: the operation name without brackets (they end the heading)."""
    name = " ".join((operation.name or "").replace("[", " ").replace("]", " ").split())
    return name or f"{(operation.http_method or '').upper()} {operation.http_path or ''}".strip()


def _enum_member(name: str) -> str:
    return name if re.match(r"^[^\s`()]+$", name) else f"`{name}`"


def _comment_safe(text: str) -> str:
    return " ".join(str(text).replace("--", "-").split())


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or api.title or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.apib"
