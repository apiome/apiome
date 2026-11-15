"""The GraphQL protocol adapter of the contract-suite compiler — XPC-1.2 (#5730).

A GraphQL version normalizes to services named after its root types (``Query``, ``Mutation``,
``Subscription``) whose operations are the root fields (``Query.user``), with the field's
arguments as parameters and its return type as the lone response message (see
:mod:`app.graphql_normalizer`). This adapter compiles each root ``query`` and ``mutation`` field
into cases that a runner executes as ``POST {target.url}`` with a GraphQL-over-HTTP JSON body.

What a GraphQL case is
----------------------
One named operation selecting one root field, e.g.::

    query Query_user($id: ID!) { user(id: $id) { email id name } }

with its ``variables`` and ``operationName``. The selection set is expanded from the canonical
return type down to ``max_selection_depth`` levels of object fields; a field that takes a
required argument is left out (the suite would have to invent its value), and so is anything
past the depth bound — both reported. A union, or an object with nothing selectable, selects
``__typename``.

Cases are built in the same preference order the HTTP adapter uses:

1. **Declared example arguments** — an argument's ``@example(value: …)`` directive (or an
   ``example``/``examples`` entry in its ``extras``), the only kind of value an author wrote.
2. **Schema-valid generated arguments** — the required arguments only, then every argument,
   each value seeded through :mod:`app.schema_instance_synthesis` from a JSON Schema built for
   the argument's GraphQL input type (``Int`` bounded to 32 bits, input objects as ``$defs``).
3. **Negative cases** — a required argument omitted from the document, an argument given a
   value of the wrong type, and an unknown field added to the selection. A conforming server
   answers each with a non-empty ``errors`` array.

The response contract
---------------------
A success case expects ``errors`` absent and ``data`` to satisfy a schema built from the
**selection**, not the whole type: exactly the selected fields, each required, each nullable
only where the GraphQL type is. The schema is registered under ``graphql:<operation key>`` and
validates the ``data`` object, so every violation is located by a JSON Pointer into ``data``
(``/user/email``). GraphQL carries its verdict in the envelope rather than in the status, so
both expectations accept ``2XX`` and a negative case also accepts ``4XX`` (GraphQL-over-HTTP
lets a server answer a request error either way); ``status_declared`` is ``false`` on both.

Subscriptions are listed under the manifest's ``unsupported`` with a reason: a
request/response case cannot express a stream.

This module is pure and deterministic, like :mod:`app.contract_suite`, whose models, finding
vocabulary, operation selection and seeding it shares.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from graphql import GraphQLSyntaxError, parse, value_from_ast_untyped

from .canonical_model import (
    CanonicalApi,
    CanonicalField,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .contract_protocols import PROTOCOL_GRAPHQL
from .contract_suite import (
    CASE_SOURCE_DECLARED_EXAMPLE,
    CASE_SOURCE_GENERATED_FULL,
    CASE_SOURCE_GENERATED_MINIMAL,
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
    CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
    CODE_FIELD_ARGUMENTS_REQUIRED,
    CODE_GENERATION_LIMITED,
    CODE_NO_CASES_COMPILED,
    CODE_NO_NEGATIVE_CASES,
    CODE_SELECTION_DEPTH_LIMITED,
    CODE_UNMAPPED_SCALAR,
    CODE_UNRESOLVED_PAYLOAD_TYPE,
    CODE_UNSUPPORTED_OPERATION_KIND,
    CODE_UNSUPPORTED_PARAMETER_SHAPE,
    CODE_UNSUPPORTED_STREAMING,
    DEFAULT_MEDIA_TYPE,
    FINDING_DEGRADED,
    FINDING_INFO,
    FINDING_UNSUPPORTED,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    WRONG_TYPE_PARAMETER_VALUE,
    ContractCase,
    ContractCaseExpectation,
    ContractCaseRequest,
    ContractGraphqlRequest,
    SuiteOperation,
    _case_id,
    _Compilation,
    _seed_for,
    _select_operations,
)
from .schema_instance_synthesis import INSTANCE_FULL, INSTANCE_MINIMAL, synthesize_instances
from .schema_validation import DRAFT_2020_12_META_URI

__all__ = [
    "GRAPHQL_REQUEST_PATH",
    "GRAPHQL_SCHEMA_PREFIX",
    "UNKNOWN_FIELD_NAME",
    "compile_graphql_cases",
    "graphql_type_text",
]

#: Path every GraphQL case records: the runner posts to the target URL itself, never a sub-path.
GRAPHQL_REQUEST_PATH = "/"

#: Prefix of the manifest ``schemas`` key a GraphQL success case's ``data`` is validated against.
GRAPHQL_SCHEMA_PREFIX = "graphql:"

#: Name of the field the unknown-field negative case selects. Suffixed with a number in the
#: unlikely event the returned type declares a field of that name.
UNKNOWN_FIELD_NAME = "apiomeUnknownField"

#: GraphQL's built-in scalars, and the JSON Schema each serializes to. ``ID`` is serialized as a
#: string; ``Int`` is a signed 32-bit integer, so its bounds are part of the contract.
_INT_BOUNDS = {"minimum": -(2**31), "maximum": 2**31 - 1}
_BUILTIN_SCALARS: Dict[str, Dict[str, Any]] = {
    "String": {"type": "string"},
    "ID": {"type": "string"},
    "Int": {"type": "integer", **_INT_BOUNDS},
    "Float": {"type": "number"},
    "Boolean": {"type": "boolean"},
}

#: Root field kinds this adapter compiles, and the GraphQL operation type each one is sent as.
_OPERATION_TYPES = {OperationKind.QUERY: "query", OperationKind.MUTATION: "mutation"}

#: Backstop on how many fields one selection set may carry. A wide schema expanded three levels
#: deep multiplies quickly; past this the selection stops growing and says so.
_SELECTION_FIELD_LIMIT = 250

#: Sentinel for "no declared example" (``None`` is a legitimate example value).
_MISSING = object()


# ===========================================================================
# Entry point
# ===========================================================================


def compile_graphql_cases(compilation: _Compilation) -> None:
    """The GraphQL adapter: compile every root ``query``/``mutation`` field into cases.

    Args:
        compilation: The run state, filled in place.
    """
    selected, dropped = _select_operations(compilation)
    compilation.dropped += dropped
    types = _types_by_key(compilation.api)
    for service, operation in selected:
        _compile_root_field(compilation, types, service, operation)


# ===========================================================================
# Per-root-field compilation
# ===========================================================================


@dataclass
class _Argument:
    """One root-field argument, resolved once and reused by every case.

    Attributes:
        parameter: The canonical parameter.
        type_text: The GraphQL type the argument's variable is declared with (``[ID!]!``).
        declared: The value an author declared for it, or :data:`_MISSING`.
        minimal: A generated required-only value, or :data:`_MISSING` when none was generated.
        full: A generated every-field value, or :data:`_MISSING`.
        wrong: A value of the wrong type for the argument, or :data:`_MISSING` when none is
            known to be wrong (a custom scalar accepts whatever its server decides).
    """

    parameter: Parameter
    type_text: str
    declared: Any = _MISSING
    minimal: Any = _MISSING
    full: Any = _MISSING
    wrong: Any = _MISSING

    @property
    def name(self) -> str:
        """The argument's name, which is also its variable's name."""
        return self.parameter.name

    @property
    def required(self) -> bool:
        """Whether the argument is non-null with no default."""
        return self.parameter.required


@dataclass
class _Selection:
    """A selection set and the JSON Schema of the value it produces.

    Attributes:
        fields: The selected fields at this level, already rendered (``owner { name }``).
            Empty for a leaf (scalar or enum), which takes no selection set.
        schema: The schema the selected value must satisfy.
        field_names: Names the selected type declares, for choosing an unknown field name.
    """

    fields: List[str]
    schema: Dict[str, Any]
    field_names: Tuple[str, ...] = ()

    def text(self) -> str:
        """Render the selection set, or ``""`` for a leaf."""
        return "{ " + " ".join(self.fields) + " }" if self.fields else ""


@dataclass
class _Expansion:
    """Bookkeeping for one root field's selection expansion.

    Attributes:
        depth_limited: Whether an object field was left out for depth (reported once).
        size_limited: Whether the field backstop was hit (reported once).
        required_arguments: Keys of nested fields left out for their required arguments.
        unmapped: Custom scalars met while building schemas.
        selected: How many fields the selection carries so far.
    """

    depth_limited: bool = False
    size_limited: bool = False
    required_arguments: List[str] = field(default_factory=list)
    unmapped: List[str] = field(default_factory=list)
    selected: int = 0


def _compile_root_field(
    compilation: _Compilation,
    types: Mapping[str, Type],
    service: Service,
    operation: Operation,
) -> None:
    """Compile one root field's cases, or report why none could be compiled.

    Args:
        compilation: The run state, mutated in place.
        types: The model's types by key.
        service: The root type the field belongs to.
        operation: The root field.
    """
    key = operation.key
    if operation.kind is OperationKind.SUBSCRIPTION or operation.streaming is not StreamingMode.NONE:
        reason = (
            f"{key!r} is a subscription: it pushes a stream of results, which a "
            "request/response case cannot express."
        )
        compilation.report(CODE_UNSUPPORTED_STREAMING, FINDING_UNSUPPORTED, reason, operation_key=key)
        compilation.mark_unsupported(key, CODE_UNSUPPORTED_STREAMING, reason)
        return
    operation_type = _OPERATION_TYPES.get(operation.kind)
    if operation_type is None:
        reason = (
            f"{key!r} is a {operation.kind.value} operation; only query and mutation root "
            "fields compile into GraphQL cases."
        )
        compilation.report(
            CODE_UNSUPPORTED_OPERATION_KIND, FINDING_UNSUPPORTED, reason, operation_key=key
        )
        compilation.mark_unsupported(key, CODE_UNSUPPORTED_OPERATION_KIND, reason)
        return

    returns = _return_type(operation)
    if returns is None:
        reason = f"{key!r} declares no return type, so there is nothing to select or check."
        compilation.report(
            CODE_UNRESOLVED_PAYLOAD_TYPE, FINDING_UNSUPPORTED, reason, operation_key=key
        )
        compilation.mark_unsupported(key, CODE_UNRESOLVED_PAYLOAD_TYPE, reason)
        return

    expansion = _Expansion()
    selection = _select(types, returns, 1, compilation.options.max_selection_depth, expansion)
    arguments = _arguments(compilation, types, operation, expansion)
    _report_expansion(compilation, key, expansion)
    if arguments is None:
        compilation.skipped.append(key)
        return

    builder = _CaseBuilder(
        operation=operation,
        root=service.key or service.name,
        operation_type=operation_type,
        selection=selection,
    )
    success = _success_expectation(compilation, operation, selection)
    client_error = _error_expectation(operation_type)

    before = len(compilation.cases)
    _emit_positive_cases(compilation, builder, arguments, success)
    _emit_negative_cases(compilation, builder, arguments, client_error)
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
            service_key=service.key or None,
            http_method="POST",
            http_path=GRAPHQL_REQUEST_PATH,
            deprecated=operation.deprecated,
            tags=list(operation.tags),
            case_count=emitted,
            request_media_type=DEFAULT_MEDIA_TYPE,
        )
    )


def _return_type(operation: Operation) -> Optional[TypeRef]:
    """Return a root field's return type: the payload of its lone response message."""
    for message in operation.messages:
        if message.role is MessageRole.RESPONSE and message.payload is not None:
            return message.payload
    return None


def _report_expansion(compilation: _Compilation, key: str, expansion: _Expansion) -> None:
    """Surface what the selection and argument schemas could not express, once per root field."""
    if expansion.depth_limited:
        compilation.report(
            CODE_SELECTION_DEPTH_LIMITED,
            FINDING_INFO,
            f"The selection for {key!r} stops at `max_selection_depth` "
            f"({compilation.options.max_selection_depth}); deeper object fields are not "
            "selected or checked.",
            operation_key=key,
        )
    if expansion.size_limited:
        compilation.report(
            CODE_SELECTION_DEPTH_LIMITED,
            FINDING_DEGRADED,
            f"The selection for {key!r} reached {_SELECTION_FIELD_LIMIT} fields; the rest of "
            "the return type is not selected or checked. Lower `max_selection_depth` to keep "
            "the selection whole.",
            operation_key=key,
        )
    for field_key in sorted(set(expansion.required_arguments)):
        compilation.report(
            CODE_FIELD_ARGUMENTS_REQUIRED,
            FINDING_INFO,
            f"Field {field_key!r} takes a required argument, so the selection for {key!r} "
            "leaves it out rather than inventing a value.",
            operation_key=key,
        )
    if expansion.unmapped:
        compilation.report(
            CODE_UNMAPPED_SCALAR,
            FINDING_DEGRADED,
            f"{key!r} uses custom scalar(s) {', '.join(sorted(set(expansion.unmapped)))} with no "
            "JSON Schema analogue; values at those positions are generated unconstrained and "
            "validated against nothing.",
            operation_key=key,
        )


# ===========================================================================
# Selection sets and the response schema
# ===========================================================================


def _select(
    types: Mapping[str, Type],
    ref: TypeRef,
    level: int,
    max_depth: int,
    expansion: _Expansion,
) -> Optional[_Selection]:
    """Expand a selection set for an output type, with the schema its value must satisfy.

    Args:
        types: The model's types by key.
        ref: The output type at this position, wrappers included.
        level: Depth of the selection set this type would open (1 for the root field's own).
        max_depth: The deepest selection set allowed.
        expansion: Bookkeeping for what was left out.

    Returns:
        The selection, or ``None`` when the type is an object that sits below ``max_depth`` and
        so cannot be selected at all.
    """
    if ref.item is not None:
        inner = _select(types, ref.item, level, max_depth, expansion)
        if inner is None:
            return None
        schema = {"type": _nullable("array", ref.nullable), "items": inner.schema}
        return _Selection(fields=inner.fields, schema=schema, field_names=inner.field_names)

    name = ref.name or ""
    if name in _BUILTIN_SCALARS:
        return _Selection(fields=[], schema=_nullable_schema(dict(_BUILTIN_SCALARS[name]), ref))
    type_ = types.get(name)
    if type_ is None or type_.kind is TypeKind.SCALAR:
        expansion.unmapped.append(name or "<unnamed>")
        return _Selection(fields=[], schema={})
    if type_.kind is TypeKind.ENUM:
        return _Selection(fields=[], schema=_enum_schema(type_, ref.nullable))
    if type_.kind is TypeKind.UNION:
        members = sorted(type_.union_members)
        schema = _object_schema({"__typename": {"enum": members}}, ref.nullable)
        return _Selection(fields=["__typename"], schema=schema)
    if type_.kind is not TypeKind.RECORD:
        expansion.unmapped.append(name)
        return _Selection(fields=[], schema={})

    if level > max_depth:
        expansion.depth_limited = True
        return None

    rendered: List[str] = []
    properties: Dict[str, Any] = {}
    for member in sorted(type_.fields, key=lambda item: item.name):
        if expansion.selected >= _SELECTION_FIELD_LIMIT:
            expansion.size_limited = True
            break
        if _requires_arguments(member):
            expansion.required_arguments.append(member.key)
            continue
        child = _select(types, member.type, level + 1, max_depth, expansion)
        if child is None:
            continue
        expansion.selected += 1
        rendered.append(f"{member.name} {child.text()}".rstrip())
        properties[member.name] = child.schema

    if not rendered:
        # Every selection set needs at least one field; ``__typename`` is always valid.
        rendered = ["__typename"]
        properties = {"__typename": {"type": "string"}}
    names = tuple(sorted(member.name for member in type_.fields))
    return _Selection(
        fields=rendered, schema=_object_schema(properties, ref.nullable), field_names=names
    )


def _requires_arguments(member: CanonicalField) -> bool:
    """Return whether a nested field declares an argument that is non-null with no default."""
    for argument in member.extras.get("arguments") or ():
        if not isinstance(argument, Mapping):
            continue
        type_ = argument.get("type")
        if isinstance(type_, Mapping) and type_.get("nullable") is False and "default" not in argument:
            return True
    return False


def _nullable(json_type: str, nullable: bool) -> Any:
    """Return a JSON Schema ``type`` that admits ``null`` exactly when GraphQL does."""
    return [json_type, "null"] if nullable else json_type


def _nullable_schema(schema: Dict[str, Any], ref: TypeRef) -> Dict[str, Any]:
    """Widen a scalar schema's ``type`` to admit ``null`` when the GraphQL type is nullable."""
    if ref.nullable and isinstance(schema.get("type"), str):
        schema["type"] = [schema["type"], "null"]
    return schema


def _enum_schema(type_: Type, nullable: bool) -> Dict[str, Any]:
    """The schema of an enum value: one of its member names, or ``null`` when nullable."""
    values: List[Any] = sorted(value.name for value in type_.enum_values)
    if nullable:
        values.append(None)
    return {"enum": values}


def _object_schema(properties: Dict[str, Any], nullable: bool) -> Dict[str, Any]:
    """The schema of a selected object: exactly the selected fields, every one present."""
    return {
        "type": _nullable("object", nullable),
        "properties": properties,
        "required": sorted(properties),
        "additionalProperties": False,
    }


def _data_schema(field_name: str, selection: _Selection) -> Dict[str, Any]:
    """The schema the response's ``data`` object must satisfy for one root field."""
    return {
        "$schema": DRAFT_2020_12_META_URI,
        "type": "object",
        "properties": {field_name: selection.schema},
        "required": [field_name],
        "additionalProperties": False,
    }


# ===========================================================================
# Arguments
# ===========================================================================


def _arguments(
    compilation: _Compilation,
    types: Mapping[str, Type],
    operation: Operation,
    expansion: _Expansion,
) -> Optional[List[_Argument]]:
    """Resolve every argument of a root field to its declared, generated and wrong values.

    Args:
        compilation: The run state.
        types: The model's types by key.
        operation: The root field.
        expansion: Bookkeeping that collects custom scalars met in argument types.

    Returns:
        The arguments sorted by name, or ``None`` when a required argument can be given no
        value at all — reported, because a "positive" case missing it would fail for a reason
        the suite invented.
    """
    resolved: List[_Argument] = []
    for parameter in sorted(operation.parameters, key=lambda item: item.name):
        argument = _Argument(parameter=parameter, type_text=graphql_type_text(parameter.type))
        argument.declared = _declared_value(parameter.extras)
        schema = _input_document(types, parameter.type, expansion)
        minimal, full = _generate(compilation, operation, parameter, schema)
        # A value the generator could not produce falls back to the author's own example, so
        # every case that needs the argument can still send a valid value for it.
        argument.minimal = minimal if minimal is not _MISSING else argument.declared
        argument.full = full if full is not _MISSING else argument.minimal
        argument.wrong = _wrong_value(types, parameter.type)
        if parameter.required and argument.minimal is _MISSING and argument.declared is _MISSING:
            compilation.report(
                CODE_UNSUPPORTED_PARAMETER_SHAPE,
                FINDING_UNSUPPORTED,
                f"No value could be generated for the required argument {parameter.name!r} of "
                f"{operation.key!r}, so no case for it could be built.",
                operation_key=operation.key,
            )
            return None
        resolved.append(argument)
    return resolved


def graphql_type_text(ref: TypeRef) -> str:
    """Render a canonical type reference as GraphQL type syntax.

    Args:
        ref: The reference, wrappers included.

    Returns:
        The GraphQL spelling, e.g. ``[ID!]!`` for a non-null list of non-null IDs.
    """
    inner = f"[{graphql_type_text(ref.item)}]" if ref.item is not None else (ref.name or "")
    return inner if ref.nullable else inner + "!"


def _input_document(
    types: Mapping[str, Type], ref: TypeRef, expansion: _Expansion
) -> Dict[str, Any]:
    """Build the JSON Schema a variable value of a GraphQL input type must satisfy.

    Input objects are carried as ``$defs`` so a recursive input type (a filter that nests
    itself) stays finite. Values are generated non-null even for nullable positions: ``null``
    is valid there, but it exercises nothing.

    Args:
        types: The model's types by key.
        ref: The argument's type.
        expansion: Collects custom scalars met along the way.

    Returns:
        A self-contained draft 2020-12 schema document.
    """
    defs: Dict[str, Dict[str, Any]] = {}
    root = _input_schema(types, ref, defs, expansion)
    document = {"$schema": DRAFT_2020_12_META_URI, **root}
    if defs:
        document["$defs"] = {name: defs[name] for name in sorted(defs)}
    return document


def _input_schema(
    types: Mapping[str, Type],
    ref: TypeRef,
    defs: Dict[str, Dict[str, Any]],
    expansion: _Expansion,
) -> Dict[str, Any]:
    """Project one input type position into JSON Schema (see :func:`_input_document`)."""
    if ref.item is not None:
        return {"type": "array", "items": _input_schema(types, ref.item, defs, expansion)}
    name = ref.name or ""
    if name in _BUILTIN_SCALARS:
        return dict(_BUILTIN_SCALARS[name])
    type_ = types.get(name)
    if type_ is not None and type_.kind is TypeKind.ENUM:
        return {"type": "string", "enum": sorted(value.name for value in type_.enum_values)}
    if type_ is not None and type_.kind is TypeKind.RECORD:
        if name not in defs:
            defs[name] = {}  # placeholder first, so a self-reference terminates
            properties = {
                member.name: _input_schema(types, member.type, defs, expansion)
                for member in sorted(type_.fields, key=lambda item: item.name)
            }
            required = sorted(
                member.name
                for member in type_.fields
                if not member.type.nullable and member.default is None
            )
            defs[name] = {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            }
        return {"$ref": f"#/$defs/{name}"}
    expansion.unmapped.append(name or "<unnamed>")
    return {}


def _generate(
    compilation: _Compilation,
    operation: Operation,
    parameter: Parameter,
    schema: Dict[str, Any],
) -> Tuple[Any, Any]:
    """Generate the required-only and every-field values for one argument.

    Args:
        compilation: The run state (seed, findings).
        operation: The root field, for findings.
        parameter: The argument; its key seeds the generator.
        schema: The argument's input schema.

    Returns:
        ``(minimal, full)``, either being :data:`_MISSING` when it could not be generated.
    """
    result = synthesize_instances(
        schema,
        seed=_seed_for(compilation.options.seed, parameter.key),
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
            f"Generating argument {parameter.name!r} of {operation.key!r} was limited: "
            f"{diagnostic.message}",
            operation_key=operation.key,
            pointer=diagnostic.pointer,
        )
    found = {instance.kind: instance.instance for instance in result.instances}
    return found.get(INSTANCE_MINIMAL, _MISSING), found.get(INSTANCE_FULL, _MISSING)


def _wrong_value(types: Mapping[str, Type], ref: TypeRef) -> Any:
    """Pick a value GraphQL's input coercion must reject for this type.

    ``true`` is rejected by every built-in scalar but ``Boolean``, by every enum and by every
    input object; a ``Boolean`` gets a string instead. A list coerces a single value into a
    one-item list, so the item type decides. A custom scalar has no known wrong value.

    Args:
        types: The model's types by key.
        ref: The argument's type.

    Returns:
        The wrong value, or :data:`_MISSING` when none is certain to be wrong.
    """
    leaf = ref
    while leaf.item is not None:
        leaf = leaf.item
    name = leaf.name or ""
    if name == "Boolean":
        return WRONG_TYPE_PARAMETER_VALUE
    if name in _BUILTIN_SCALARS:
        return True
    type_ = types.get(name)
    if type_ is not None and type_.kind in (TypeKind.ENUM, TypeKind.RECORD):
        return True
    return _MISSING


def _declared_value(extras: Mapping[str, Any]) -> Any:
    """Return the example an argument declares, or :data:`_MISSING`.

    Read in the order the GraphQL mock (XPC-1.1) reads examples: ``extras["example"]``, then the
    first ``extras["examples"]`` item, then the ``value`` of an applied ``@example`` directive.
    A string that holds JSON is decoded, so ``@example(value: "{\\"id\\": 1}")`` is an object.

    Args:
        extras: The argument's ``extras``.

    Returns:
        The declared value, or :data:`_MISSING`.
    """
    if "example" in extras:
        return _decode(extras["example"])
    examples = extras.get("examples")
    if isinstance(examples, list) and examples:
        return _decode(examples[0])
    for printed in extras.get("directives") or ():
        if isinstance(printed, str):
            found = _example_directive_value(printed)
            if found is not _MISSING:
                return found
    return _MISSING


def _example_directive_value(printed: str) -> Any:
    """Read the ``value`` argument of a printed ``@example(value: …)`` directive.

    Args:
        printed: One applied directive as the normalizer stores it (``@example(value: 3)``).

    Returns:
        The decoded value, or :data:`_MISSING` when ``printed`` is not such a directive.
    """
    if not printed.startswith("@example"):
        return _MISSING
    try:
        document = parse(f"query _ {printed} {{ _ }}")
    except GraphQLSyntaxError:
        return _MISSING
    for directive in getattr(document.definitions[0], "directives", None) or ():
        if directive.name.value != "example":
            continue
        for argument in directive.arguments or ():
            if argument.name.value == "value":
                return _decode(value_from_ast_untyped(argument.value))
    return _MISSING


def _decode(value: Any) -> Any:
    """Decode a string example that holds a JSON object or array; return anything else as is."""
    if isinstance(value, str) and value.strip()[:1] in {"{", "["}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


# ===========================================================================
# Expectations
# ===========================================================================


def _success_expectation(
    compilation: _Compilation, operation: Operation, selection: Optional[_Selection]
) -> ContractCaseExpectation:
    """Build what a positive case asserts: no ``errors``, and ``data`` matching the selection.

    Args:
        compilation: The run state; the ``data`` schema is registered on it.
        operation: The root field.
        selection: The root field's selection (always present for a root field, which sits at
            depth zero).

    Returns:
        The expectation.
    """
    schema_id: Optional[str] = None
    if selection is not None and compilation.options.include_response_schemas:
        schema_id = GRAPHQL_SCHEMA_PREFIX + operation.key
        compilation.schemas.setdefault(schema_id, _data_schema(operation.name, selection))
    return ContractCaseExpectation(
        outcome=OUTCOME_SUCCESS,
        status_codes=["2XX"],
        status_declared=False,
        response_schema_id=schema_id,
        reason=(
            f"A valid operation is answered with no `errors` and `data.{operation.name}` "
            "matching its return type; GraphQL declares no status codes, so any 2XX is accepted."
        ),
    )


def _error_expectation(operation_type: str) -> ContractCaseExpectation:
    """Build what a negative case asserts: a non-empty ``errors`` array."""
    return ContractCaseExpectation(
        outcome=OUTCOME_CLIENT_ERROR,
        status_codes=["2XX", "4XX"],
        status_declared=False,
        response_schema_id=None,
        reason=(
            f"The {operation_type} violates the schema, so a conforming server answers with a "
            "non-empty `errors` array (with 2XX or 4XX, as GraphQL over HTTP allows)."
        ),
    )


# ===========================================================================
# Case emission
# ===========================================================================


@dataclass(frozen=True)
class _CaseBuilder:
    """Renders one root field's GraphQL documents and assembles its cases.

    Attributes:
        operation: The root field.
        root: The root type's name (``Query``), which prefixes the operation name.
        operation_type: ``query`` or ``mutation``.
        selection: The root field's selection; ``None`` never happens for a root field.
    """

    operation: Operation
    root: str
    operation_type: str
    selection: Optional[_Selection]

    @property
    def operation_name(self) -> str:
        """The GraphQL operation name every case of this field uses (``Query_user``)."""
        return f"{self.root}_{self.operation.name}"

    def document(
        self, arguments: Sequence[_Argument], *, extra_field: Optional[str] = None
    ) -> str:
        """Render the GraphQL document selecting the root field with these arguments.

        Args:
            arguments: The arguments the document passes, each through a variable of its own
                name. An argument left out is absent from the document entirely.
            extra_field: A field to add to the root selection (the unknown-field negative).

        Returns:
            The single-line document.
        """
        variables = ", ".join(f"${item.name}: {item.type_text}" for item in arguments)
        header = f"{self.operation_type} {self.operation_name}"
        if variables:
            header += f"({variables})"
        call = self.operation.name
        if arguments:
            call += "(" + ", ".join(f"{item.name}: ${item.name}" for item in arguments) + ")"
        fields = list(self.selection.fields) if self.selection is not None else []
        if extra_field is not None:
            fields.insert(0, extra_field)
        if fields:
            call += " { " + " ".join(fields) + " }"
        return f"{header} {{ {call} }}"

    def case(
        self,
        *,
        source: str,
        source_detail: Optional[str],
        title: str,
        description: str,
        synthetic: bool,
        query: str,
        variables: Dict[str, Any],
        expectation: ContractCaseExpectation,
    ) -> ContractCase:
        """Assemble one GraphQL case, deriving its stable id from what makes it distinct.

        Args:
            source: The case source.
            source_detail: What distinguishes the case within its source.
            title: Short human-readable name.
            description: What the case exercises.
            synthetic: ``False`` only when every variable is an author's declared example.
            query: The GraphQL document.
            variables: The variable values.
            expectation: What must come back.

        Returns:
            The assembled :class:`ContractCase`.
        """
        envelope = {"operationName": self.operation_name, "query": query, "variables": variables}
        return ContractCase(
            case_id=_case_id(self.operation.key, source, source_detail, None, title),
            operation_key=self.operation.key,
            operation_name=self.operation.name,
            source=source,
            source_detail=source_detail,
            source_pointer=None,
            title=title,
            description=description,
            synthetic=synthetic,
            protocol=PROTOCOL_GRAPHQL,
            request=ContractCaseRequest(
                method="POST",
                path_template=GRAPHQL_REQUEST_PATH,
                path=GRAPHQL_REQUEST_PATH,
                parameters=[],
                has_body=True,
                body=envelope,
                media_type=DEFAULT_MEDIA_TYPE,
            ),
            graphql=ContractGraphqlRequest(
                query=query,
                variables=variables,
                operationName=self.operation_name,
                operation_type=self.operation_type,
                field=self.operation.name,
            ),
            expect=expectation,
            tags=list(self.operation.tags),
        )


def _union(*groups: Sequence[_Argument]) -> List[_Argument]:
    """Merge argument lists into one, without duplicates, sorted by name."""
    merged = {item.name: item for group in groups for item in group}
    return [merged[name] for name in sorted(merged)]


def _values(arguments: Sequence[_Argument], attribute: str) -> Dict[str, Any]:
    """Map each argument to one of its resolved values, skipping those without one."""
    values: Dict[str, Any] = {}
    for argument in arguments:
        value = getattr(argument, attribute)
        if value is not _MISSING:
            values[argument.name] = value
    return values


def _emit_positive_cases(
    compilation: _Compilation,
    builder: _CaseBuilder,
    arguments: Sequence[_Argument],
    expectation: ContractCaseExpectation,
) -> None:
    """Emit the cases a conforming server must answer: declared, then generated arguments.

    Args:
        compilation: The run state.
        builder: Renders the field's documents.
        arguments: The resolved arguments.
        expectation: The success expectation.
    """
    options = compilation.options
    required = [item for item in arguments if item.required]

    declared = [item for item in arguments if item.declared is not _MISSING]
    if options.include_declared_examples and declared:
        # Declared values first; a required argument the author gave no example for still
        # needs a value, which is generated — and then the case says it is synthetic.
        sent = _union(declared, required)
        variables = {
            item.name: item.declared if item.declared is not _MISSING else item.minimal
            for item in sent
        }
        compilation.cases.append(
            builder.case(
                source=CASE_SOURCE_DECLARED_EXAMPLE,
                source_detail=",".join(item.name for item in declared),
                title="declared example arguments",
                description=(
                    "Calls the field with the argument values the schema declares through "
                    "`@example`. An example the author wrote is the strongest evidence of intent."
                ),
                synthetic=len(declared) != len(sent),
                query=builder.document(sent),
                variables=variables,
                expectation=expectation,
            )
        )

    if not options.include_generated:
        return
    budget = options.max_generated_cases_per_operation
    minimal = _values(required, "minimal")
    compilation.cases.append(
        builder.case(
            source=CASE_SOURCE_GENERATED_MINIMAL,
            source_detail=None,
            title="required arguments only" if required else "no arguments",
            description=(
                "Calls the field with schema-valid generated values for its required arguments "
                "only." if required else "Calls the field with no arguments."
            ),
            synthetic=True,
            query=builder.document(required),
            variables=minimal,
            expectation=expectation,
        )
    )
    full = _values(arguments, "full")
    if budget >= 2 and arguments and full != minimal:
        compilation.cases.append(
            builder.case(
                source=CASE_SOURCE_GENERATED_FULL,
                source_detail=None,
                title="every argument",
                description=(
                    "Calls the field with a schema-valid generated value for every argument, "
                    "optional input fields included."
                ),
                synthetic=True,
                query=builder.document(list(arguments)),
                variables=full,
                expectation=expectation,
            )
        )


def _emit_negative_cases(
    compilation: _Compilation,
    builder: _CaseBuilder,
    arguments: Sequence[_Argument],
    expectation: ContractCaseExpectation,
) -> None:
    """Emit the requests a conforming server must answer with ``errors``.

    In order, within ``max_negative_cases_per_operation``: each required argument omitted, one
    argument given a wrong-typed value, and an unknown field selected. Every one isolates a
    single fault: the rest of the request is the valid required-only call.

    Args:
        compilation: The run state.
        builder: Renders the field's documents.
        arguments: The resolved arguments.
        expectation: The client-error expectation.
    """
    if not compilation.options.include_negative:
        return
    budget = compilation.options.max_negative_cases_per_operation
    key = builder.operation.key
    required = [item for item in arguments if item.required]
    emitted = 0

    for argument in required:
        if emitted >= budget:
            break
        rest = [item for item in required if item is not argument]
        compilation.cases.append(
            builder.case(
                source=CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
                source_detail=argument.name,
                title=f"required argument '{argument.name}' omitted",
                description=(
                    f"Leaves the required argument {argument.name!r} out of the document. A "
                    "conforming server rejects the operation in validation."
                ),
                synthetic=True,
                query=builder.document(rest),
                variables=_values(rest, "minimal"),
                expectation=expectation,
            )
        )
        emitted += 1

    typed = next(
        (
            item
            for item in sorted(arguments, key=lambda item: (not item.required, item.name))
            if item.wrong is not _MISSING
        ),
        None,
    )
    if typed is not None and emitted < budget:
        sent = _union(required, [typed])
        variables = _values(sent, "minimal")
        variables[typed.name] = typed.wrong
        compilation.cases.append(
            builder.case(
                source=CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
                source_detail=typed.name,
                title=f"argument '{typed.name}' with a wrong-typed value",
                description=(
                    f"Sends {typed.wrong!r} for {typed.name!r}, declared as {typed.type_text}. "
                    "A conforming server rejects the variable when it coerces it."
                ),
                synthetic=True,
                query=builder.document(sent),
                variables=variables,
                expectation=expectation,
            )
        )
        emitted += 1

    selection = builder.selection
    if selection is not None and selection.fields and emitted < budget:
        unknown = _unknown_field_name(selection.field_names)
        compilation.cases.append(
            builder.case(
                source=CASE_SOURCE_NEGATIVE_UNKNOWN_FIELD,
                source_detail=unknown,
                title=f"unknown field '{unknown}' selected",
                description=(
                    f"Selects {unknown!r}, which the returned type does not declare. A "
                    "conforming server rejects the operation in validation."
                ),
                synthetic=True,
                query=builder.document(required, extra_field=unknown),
                variables=_values(required, "minimal"),
                expectation=expectation,
            )
        )
        emitted += 1

    if emitted == 0:
        compilation.report(
            CODE_NO_NEGATIVE_CASES,
            FINDING_DEGRADED,
            f"No negative case could be compiled for {key!r}: it takes no argument a value "
            "could break and returns a leaf type with no selection to corrupt.",
            operation_key=key,
        )


def _unknown_field_name(declared: Sequence[str]) -> str:
    """Return :data:`UNKNOWN_FIELD_NAME`, suffixed until the type does not declare it."""
    taken = set(declared)
    candidate = UNKNOWN_FIELD_NAME
    suffix = 1
    while candidate in taken:
        suffix += 1
        candidate = f"{UNKNOWN_FIELD_NAME}{suffix}"
    return candidate


def _types_by_key(api: CanonicalApi) -> Dict[str, Type]:
    """Index a model's types by key — GraphQL type names, which is how a ``TypeRef`` names them."""
    return {type_.key: type_ for type_ in api.types if type_.key}
