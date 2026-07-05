"""GraphQL SDL emitter: canonical model → SDL — MFX-13.1 (#3884), MFX-13.2 (#3885).

The inverse of :class:`app.graphql_normalizer.GraphQlNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. It walks a :class:`~app.canonical_model.CanonicalApi` and
builds a ``graphql-core`` :class:`~graphql.GraphQLSchema` programmatically, then serializes it
with :func:`~graphql.print_schema` so the output is guaranteed valid SDL:

* ``RECORD`` types become object/interface/input types (the GraphQL family is read from
  ``extras.graphql_type``);
* ``UNION`` / ``ENUM`` / ``SCALAR`` map to their GraphQL counterparts;
* :class:`~app.canonical_model.TypeRef` nullability and list wrappers invert
  :func:`app.graphql_normalizer._type_ref` level-by-level;
* root operations become ``Query`` / ``Mutation`` / ``Subscription`` fields — Graph-native
  sources reuse their :class:`~app.canonical_model.Service` root types; other paradigms
  aggregate operations with a read-vs-write heuristic (``QUERY`` / ``GET`` → ``Query``,
  ``MUTATION`` / other HTTP verbs → ``Mutation``);
* cross-paradigm request bodies and any argument that would reference an output object are
  mapped to deterministically named, deduplicated ``input`` types (MFX-13.2).

Constructs GraphQL cannot carry (``MAP`` types, event pub/sub, HTTP bindings) are recorded as
:class:`~app.emitter.Loss`\\es rather than silently dropped.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, Union

from graphql import (
    GraphQLArgument,
    GraphQLBoolean,
    GraphQLEnumType,
    GraphQLEnumValue,
    GraphQLField,
    GraphQLFloat,
    GraphQLID,
    GraphQLInputField,
    GraphQLInputObjectType,
    GraphQLInt,
    GraphQLInterfaceType,
    GraphQLList,
    GraphQLNamedType,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLString,
    GraphQLUnionType,
    Undefined,
    print_schema,
    validate_schema,
)
from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    Operation,
    OperationKind,
    Service,
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

__all__ = ["GraphQlEmitOptions", "GraphQlEmitter"]

# Built-in GraphQL scalars — referenced by name, never emitted as custom types.
_BUILTIN_SCALARS: Dict[str, GraphQLScalarType] = {
    "Int": GraphQLInt,
    "Float": GraphQLFloat,
    "String": GraphQLString,
    "Boolean": GraphQLBoolean,
    "ID": GraphQLID,
}

# Root operation slots the emitter may populate.
_ROOT_SLOTS = ("query", "mutation", "subscription")

# Service names that identify Graph-native root types when the paradigm is GRAPH.
_GRAPH_ROOT_NAMES = frozenset({"Query", "Mutation", "Subscription"})

# HTTP methods treated as read operations for the cross-paradigm heuristic.
_READ_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_FIELD_NAME_RE = re.compile(r"[^_A-Za-z0-9]")


class GraphQlEmitOptions(EmitOptions):
    """Per-target options for :class:`GraphQlEmitter` (MFX-1.4)."""

    schema_description: Optional[str] = Field(
        default=None,
        description="Optional schema-level description override.",
    )


class GraphQlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as GraphQL SDL with provenance."""

    key = "graphql"
    format = "graphql"
    label = "GraphQL SDL"
    description = "Export as a GraphQL schema definition language (SDL) document."
    icon = "share-2"
    paradigm = ApiParadigm.GRAPH
    multi_file = False
    options_model = GraphQlEmitOptions

    OUTPUT_MEDIA_TYPE = "application/graphql"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """GraphQL carries graph operations, unions, and exact nullability/list wrappers."""
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            constraints=False,
            field_identity=False,
        )

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[GraphQlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as GraphQL SDL with per-construct provenance."""
        options = (
            opts
            if isinstance(opts, GraphQlEmitOptions)
            else GraphQlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _GraphQlWriter(api, options)
        sdl = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path,
                    content=sdl,
                    media_type=self.OUTPUT_MEDIA_TYPE,
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _GraphQlWriter:
    """Build a ``graphql-core`` schema from a canonical model (internal to the emitter)."""

    def __init__(self, api: CanonicalApi, options: GraphQlEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key: Dict[str, Type] = {t.key: t for t in api.types}
        self._type_name_counts = Counter(type_.name for type_ in api.types)
        self._gql_types: Dict[str, GraphQLNamedType] = {}
        self._gql_names_by_key: Dict[str, str] = {}
        self._type_keys_by_gql_name: Dict[str, str] = {}
        self._synth_inputs_by_source_key: Dict[str, GraphQLInputObjectType] = {}

    @property
    def output_path(self) -> str:
        return "schema.graphql"

    def render(self) -> str:
        """Build and print the GraphQL schema as SDL."""
        for type_ in sorted(self._api.types, key=lambda t: t.key):
            self._ensure_named_type(type_)

        query, mutation, subscription = self._build_roots()
        if query is None:
            query = self._placeholder_query()
        elif not query.fields:
            query = self._placeholder_query()

        schema = GraphQLSchema(
            query=query,
            mutation=mutation,
            subscription=subscription,
            description=self._options.schema_description or self._api.description,
        )
        errors = validate_schema(schema)
        if errors:
            messages = "; ".join(error.message for error in errors)
            raise ValueError(f"Emitted GraphQL schema failed validation: {messages}")
        return print_schema(schema)

    # --- named types -------------------------------------------------------

    def _ensure_named_type(self, type_: Type) -> GraphQLNamedType:
        """Return the graphql-core type for ``type_``, building it on first use."""
        existing = self._gql_types.get(type_.key)
        if existing is not None:
            return existing

        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            gql = self._from_type_ref(type_.aliased)
            if isinstance(gql, GraphQLNamedType):
                self._gql_types[type_.key] = gql
                return gql

        if type_.kind is TypeKind.MAP:
            self.losses.record(
                LossKind.NA,
                "map-type",
                f"GraphQL has no native map type; {type_.key!r} was emitted as String.",
                pointer=type_.key,
            )
            gql = GraphQLString
            self._gql_types[type_.key] = gql
            return gql

        builder = {
            TypeKind.RECORD: self._build_record,
            TypeKind.UNION: self._build_union,
            TypeKind.ENUM: self._build_enum,
            TypeKind.SCALAR: self._build_scalar,
        }.get(type_.kind)
        if builder is None:
            self.losses.record(
                LossKind.NA,
                "unsupported-type-kind",
                f"Type kind {type_.kind.value!r} on {type_.key!r} has no GraphQL mapping.",
                pointer=type_.key,
            )
            gql = GraphQLString
            self._gql_types[type_.key] = gql
            return gql

        gql = builder(type_)
        self._gql_types[type_.key] = gql
        self.tracker.record(f"/types/{type_.key}", Provenance.SOURCE)
        return gql

    def _graphql_type_name(self, type_: Type) -> str:
        existing = self._gql_names_by_key.get(type_.key)
        if existing is not None:
            return existing

        if self._type_name_counts[type_.name] == 1:
            candidate = type_.name
        else:
            candidate = _graphql_name(type_.key, prefix="Type")

        name = candidate
        suffix = 2
        while name in _BUILTIN_SCALARS or (
            name in self._type_keys_by_gql_name and self._type_keys_by_gql_name[name] != type_.key
        ):
            name = f"{candidate}_{suffix}"
            suffix += 1

        self._gql_names_by_key[type_.key] = name
        self._type_keys_by_gql_name[name] = type_.key
        return name

    def _build_record(self, type_: Type) -> GraphQLNamedType:
        name = self._graphql_type_name(type_)
        family = (type_.extras or {}).get("graphql_type", "object")
        if family == "input":
            return GraphQLInputObjectType(
                name=name,
                description=type_.description,
                fields=lambda: self._input_fields(type_),
            )
        if family == "interface":
            return GraphQLInterfaceType(
                name=name,
                description=type_.description,
                interfaces=lambda: self._interfaces(type_),
                fields=lambda: self._output_fields(type_),
            )
        return GraphQLObjectType(
            name=name,
            description=type_.description,
            interfaces=lambda: self._interfaces(type_),
            fields=lambda: self._output_fields(type_),
        )

    def _build_union(self, type_: Type) -> GraphQLUnionType:
        members = [
            self._resolve_named(member_name)
            for member_name in (type_.union_members or [])
        ]
        return GraphQLUnionType(
            name=self._graphql_type_name(type_),
            description=type_.description,
            types=members,
        )

    def _build_enum(self, type_: Type) -> GraphQLEnumType:
        values = {
            value.name: GraphQLEnumValue(
                value.name,
                description=value.description,
                deprecation_reason=(value.extras or {}).get("deprecation_reason"),
            )
            for value in (type_.enum_values or [])
        }
        return GraphQLEnumType(
            name=self._graphql_type_name(type_),
            description=type_.description,
            values=values,
        )

    def _build_scalar(self, type_: Type) -> GraphQLScalarType:
        if type_.name in _BUILTIN_SCALARS:
            return _BUILTIN_SCALARS[type_.name]
        specified_by = (type_.extras or {}).get("specified_by_url")
        return GraphQLScalarType(
            name=self._graphql_type_name(type_),
            description=type_.description,
            specified_by_url=specified_by,
        )

    def _interfaces(self, type_: Type) -> List[GraphQLInterfaceType]:
        iface_names = (type_.extras or {}).get("interfaces") or []
        result: List[GraphQLInterfaceType] = []
        for name in iface_names:
            resolved = self._resolve_named(name)
            if isinstance(resolved, GraphQLInterfaceType):
                result.append(resolved)
            elif isinstance(resolved, GraphQLObjectType):
                self.losses.record(
                    LossKind.INFERRED,
                    "interface-reference",
                    f"Type {name!r} is an object, not an interface; skipped in "
                    f"{type_.name}.implements.",
                    pointer=type_.key,
                )
        return result

    def _output_fields(self, type_: Type) -> Dict[str, GraphQLField]:
        fields: Dict[str, GraphQLField] = {}
        for field in type_.fields:
            deprecation = (field.extras or {}).get("deprecation_reason")
            fields[field.name] = GraphQLField(
                self._from_type_ref(field.type),
                args=self._field_arguments(field),
                description=field.description,
                deprecation_reason=deprecation,
            )
            self.tracker.record(
                f"/types/{type_.key}/fields/{field.name}",
                Provenance.SOURCE if not field.extras.get("arguments") else Provenance.SOURCE,
            )
        return fields

    def _input_fields(self, type_: Type) -> Dict[str, GraphQLInputField]:
        fields: Dict[str, GraphQLInputField] = {}
        for field in type_.fields:
            default = field.default if field.default is not None else Undefined
            deprecation = (field.extras or {}).get("deprecation_reason")
            fields[field.name] = GraphQLInputField(
                self._input_type_for_ref(field.type),
                default_value=default,
                description=field.description,
                deprecation_reason=deprecation,
            )
        return fields

    def _field_arguments(self, field: CanonicalField) -> Dict[str, GraphQLArgument]:
        args: Dict[str, GraphQLArgument] = {}
        for descriptor in (field.extras or {}).get("arguments") or []:
            arg_type = TypeRef.model_validate(descriptor["type"])
            default = descriptor.get("default", Undefined)
            if default is None and "default" not in descriptor:
                default = Undefined
            args[descriptor["name"]] = GraphQLArgument(
                self._input_type_for_ref(arg_type),
                default_value=default,
                description=descriptor.get("description"),
            )
        return args

    def _placeholder_query(self) -> GraphQLObjectType:
        """Return a valid Query root when the model declares no query operations."""
        self.tracker.record("/Query/_", Provenance.DEFAULT)
        return GraphQLObjectType(
            "Query",
            lambda: {
                "_": GraphQLField(
                    GraphQLBoolean,
                    description=(
                        "Placeholder root field emitted when the model declares "
                        "no query operations."
                    ),
                )
            },
        )

    # --- type references ---------------------------------------------------

    def _resolve_named(self, name: str) -> GraphQLNamedType:
        if name in _BUILTIN_SCALARS:
            return _BUILTIN_SCALARS[name]
        type_ = self._types_by_key.get(name)
        if type_ is not None:
            return self._ensure_named_type(type_)
        self.losses.record(
            LossKind.INFERRED,
            "dangling-type-reference",
            f"Reference to unknown type {name!r}; emitted as String.",
            pointer=name,
        )
        return GraphQLString

    def _from_type_ref(self, ref: TypeRef) -> Any:
        """Invert :func:`app.graphql_normalizer._type_ref` into a graphql-core type."""
        if ref.is_list():
            inner = GraphQLList(self._from_type_ref(ref.item))  # type: ignore[arg-type]
            return inner if ref.nullable else GraphQLNonNull(inner)
        assert ref.name is not None
        if ref.name in _BUILTIN_SCALARS:
            leaf: Any = _BUILTIN_SCALARS[ref.name]
        else:
            leaf = self._resolve_named(ref.name)
        return leaf if ref.nullable else GraphQLNonNull(leaf)

    def _input_type_for_ref(self, ref: TypeRef) -> Any:
        """Resolve a type reference for an input position (args, request bodies).

        Output ``RECORD`` types are replaced with synthesized ``input`` types so the
        emitted schema never uses an object type where GraphQL requires an input type.
        """
        if ref.is_list():
            inner = GraphQLList(self._input_type_for_ref(ref.item))  # type: ignore[arg-type]
            return inner if ref.nullable else GraphQLNonNull(inner)
        assert ref.name is not None
        if ref.name in _BUILTIN_SCALARS:
            leaf: Any = _BUILTIN_SCALARS[ref.name]
        else:
            leaf = self._resolve_input_named(ref.name)
        return leaf if ref.nullable else GraphQLNonNull(leaf)

    def _resolve_input_named(self, name: str) -> Any:
        if name in _BUILTIN_SCALARS:
            return _BUILTIN_SCALARS[name]
        type_ = self._types_by_key.get(name)
        if type_ is None:
            self.losses.record(
                LossKind.INFERRED,
                "dangling-type-reference",
                f"Reference to unknown type {name!r}; emitted as String.",
                pointer=name,
            )
            return GraphQLString
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            return self._input_type_for_ref(type_.aliased)
        if type_.kind is TypeKind.RECORD and self._is_output_record(type_):
            return self._synthesize_input_type(type_)
        if type_.kind is TypeKind.UNION:
            self.losses.record(
                LossKind.INFERRED,
                "input-union-unsupported",
                f"GraphQL input positions cannot reference union {name!r}; "
                "emitted as String.",
                pointer=type_.key,
            )
            return GraphQLString
        return self._ensure_named_type(type_)

    @staticmethod
    def _is_output_record(type_: Type) -> bool:
        if type_.kind is not TypeKind.RECORD:
            return False
        return (type_.extras or {}).get("graphql_type", "object") != "input"

    def _synthesize_input_type(self, source: Type) -> GraphQLInputObjectType:
        """Derive a deduplicated input type from an output ``RECORD``."""
        cached = self._synth_inputs_by_source_key.get(source.key)
        if cached is not None:
            return cached

        output_name = self._graphql_type_name(source)
        input_name = self._synthesized_input_name(output_name, source.key)
        gql = GraphQLInputObjectType(
            name=input_name,
            description=source.description,
            fields=lambda src=source: self._synthesized_input_fields(src),
        )
        self._synth_inputs_by_source_key[source.key] = gql
        self._type_keys_by_gql_name[input_name] = f"{source.key}#input"
        self.losses.record(
            LossKind.INFERRED,
            "synthesized-input",
            f"Derived input type {input_name!r} from output type {output_name!r}.",
            pointer=source.key,
        )
        self.tracker.record(f"/types/{source.key}/input", Provenance.INFERRED)
        return gql

    def _synthesized_input_name(self, output_name: str, source_key: str) -> str:
        candidate = f"{output_name}Input"
        name = candidate
        suffix = 2
        while name in _BUILTIN_SCALARS or (
            name in self._type_keys_by_gql_name
            and self._type_keys_by_gql_name[name] != f"{source_key}#input"
        ):
            name = f"{candidate}_{suffix}"
            suffix += 1
        return name

    def _synthesized_input_fields(self, source: Type) -> Dict[str, GraphQLInputField]:
        fields: Dict[str, GraphQLInputField] = {}
        for field in source.fields:
            default = field.default if field.default is not None else Undefined
            deprecation = (field.extras or {}).get("deprecation_reason")
            fields[field.name] = GraphQLInputField(
                self._input_type_for_ref(field.type),
                default_value=default,
                description=field.description,
                deprecation_reason=deprecation,
            )
            self.tracker.record(
                f"/types/{source.key}/input/fields/{field.name}",
                Provenance.INFERRED,
            )
        return fields

    # --- root operations ---------------------------------------------------

    def _build_roots(
        self,
    ) -> Tuple[
        Optional[GraphQLObjectType],
        Optional[GraphQLObjectType],
        Optional[GraphQLObjectType],
    ]:
        if self._api.paradigm is ApiParadigm.GRAPH and self._has_graph_native_roots():
            return self._roots_from_services(self._api.services)
        return self._roots_from_heuristic(self._api.services)

    def _has_graph_native_roots(self) -> bool:
        if not self._api.services:
            return False
        graph_kinds = {
            OperationKind.QUERY,
            OperationKind.MUTATION,
            OperationKind.SUBSCRIPTION,
        }
        operations = list(self._api.operations())
        if not operations:
            return False
        return all(op.kind in graph_kinds for op in operations)

    def _roots_from_services(
        self, services: List[Service]
    ) -> Tuple[
        Optional[GraphQLObjectType],
        Optional[GraphQLObjectType],
        Optional[GraphQLObjectType],
    ]:
        roots: Dict[str, GraphQLObjectType] = {}
        for service in services:
            slot = self._slot_for_service(service)
            if slot is None:
                continue
            roots[slot] = GraphQLObjectType(
                service.name,
                lambda svc=service: self._root_fields(svc.operations),
                description=service.description,
            )
            self.tracker.record(f"/{service.name}", Provenance.SOURCE)
        return roots.get("query"), roots.get("mutation"), roots.get("subscription")

    def _roots_from_heuristic(
        self, services: List[Service]
    ) -> Tuple[
        Optional[GraphQLObjectType],
        Optional[GraphQLObjectType],
        Optional[GraphQLObjectType],
    ]:
        grouped: Dict[str, List[Operation]] = {
            slot: [] for slot in _ROOT_SLOTS
        }
        for service in services:
            for operation in service.operations:
                slot = self._slot_for_operation(operation)
                if slot is None:
                    continue
                grouped[slot].append(operation)

        roots: Dict[str, GraphQLObjectType] = {}
        default_names = {"query": "Query", "mutation": "Mutation", "subscription": "Subscription"}
        for slot, operations in grouped.items():
            if not operations:
                continue
            roots[slot] = GraphQLObjectType(
                default_names[slot],
                lambda ops=operations: self._root_fields(ops),
            )
            self.tracker.record(f"/{default_names[slot]}", Provenance.INFERRED)
        return roots.get("query"), roots.get("mutation"), roots.get("subscription")

    @staticmethod
    def _slot_for_service(service: Service) -> Optional[str]:
        name = service.name
        if name in _GRAPH_ROOT_NAMES:
            return name.lower()
        kinds = {op.kind for op in service.operations}
        if kinds == {OperationKind.QUERY}:
            return "query"
        if kinds == {OperationKind.MUTATION}:
            return "mutation"
        if kinds == {OperationKind.SUBSCRIPTION}:
            return "subscription"
        if OperationKind.QUERY in kinds:
            return "query"
        if OperationKind.MUTATION in kinds:
            return "mutation"
        if OperationKind.SUBSCRIPTION in kinds:
            return "subscription"
        return "query" if service.operations else None

    def _slot_for_operation(self, operation: Operation) -> Optional[str]:
        if operation.kind is OperationKind.QUERY:
            return "query"
        if operation.kind is OperationKind.MUTATION:
            return "mutation"
        if operation.kind is OperationKind.SUBSCRIPTION:
            return "subscription"
        if operation.kind in (OperationKind.PUBLISH, OperationKind.SUBSCRIBE):
            self.losses.record(
                LossKind.NA,
                "event-operation",
                f"Event operation {operation.key!r} has no GraphQL representation.",
                pointer=operation.key,
            )
            return None
        if operation.http_method and operation.http_method.upper() in _READ_HTTP_METHODS:
            return "query"
        if operation.http_method:
            return "mutation"
        if operation.kind is OperationKind.REQUEST_RESPONSE:
            return "mutation"
        self.losses.record(
            LossKind.NA,
            "unsupported-operation",
            f"Operation {operation.key!r} could not be mapped to Query/Mutation.",
            pointer=operation.key,
        )
        return None

    def _root_fields(self, operations: List[Operation]) -> Dict[str, GraphQLField]:
        fields: Dict[str, GraphQLField] = {}
        for operation in operations:
            name = _graphql_field_name(operation)
            return_type = self._operation_return_type(operation)
            deprecation = (operation.extras or {}).get("deprecation_reason")
            fields[name] = GraphQLField(
                return_type,
                args=self._operation_arguments(operation),
                description=operation.description,
                deprecation_reason=deprecation,
            )
            provenance = (
                Provenance.SOURCE
                if operation.kind
                in (OperationKind.QUERY, OperationKind.MUTATION, OperationKind.SUBSCRIPTION)
                else Provenance.INFERRED
            )
            self.tracker.record(f"/operations/{name}", provenance)
        return fields

    def _operation_return_type(self, operation: Operation) -> Any:
        for message in operation.messages:
            if message.role is MessageRole.RESPONSE and message.payload is not None:
                return self._from_type_ref(message.payload)
        self.losses.record(
            LossKind.INFERRED,
            "missing-response-type",
            f"Operation {operation.key!r} has no response payload; emitted as String.",
            pointer=operation.key,
        )
        return GraphQLString

    def _operation_arguments(self, operation: Operation) -> Dict[str, GraphQLArgument]:
        args: Dict[str, GraphQLArgument] = {}
        for parameter in operation.parameters:
            default = parameter.default if parameter.default is not None else Undefined
            args[parameter.name] = GraphQLArgument(
                self._input_type_for_ref(parameter.type),
                default_value=default,
                description=parameter.description,
            )
        for message in operation.messages:
            if message.role is not MessageRole.REQUEST or message.payload is None:
                continue
            arg_name = self._request_argument_name(message.payload)
            if arg_name in args:
                suffix = 2
                candidate = f"{arg_name}{suffix}"
                while candidate in args:
                    suffix += 1
                    candidate = f"{arg_name}{suffix}"
                arg_name = candidate
            args[arg_name] = GraphQLArgument(
                self._input_type_for_ref(message.payload),
                description=message.description,
            )
            self.tracker.record(
                f"/operations/{_graphql_field_name(operation)}/args/{arg_name}",
                Provenance.INFERRED,
            )
        return args

    @staticmethod
    def _request_argument_name(payload: TypeRef) -> str:
        """Derive a camelCase argument name from a request-body payload type."""
        if payload.name is None:
            return "input"
        return _camel_case(payload.name)


def _graphql_field_name(operation: Operation) -> str:
    """Derive a valid GraphQL field name from an operation."""
    candidate = operation.name
    if operation.extras.get("operationId"):
        candidate = str(operation.extras["operationId"])
    return _graphql_name(candidate, prefix="op")


def _graphql_name(candidate: str, *, prefix: str) -> str:
    sanitized = _FIELD_NAME_RE.sub("_", candidate.strip())
    if not sanitized:
        return prefix
    if not sanitized[0].isalpha() and sanitized[0] != "_":
        return f"{prefix}_{sanitized}"
    return sanitized


def _camel_case(name: str) -> str:
    """Lower-camel-case a GraphQL type name for use as an argument name."""
    if not name:
        return "input"
    parts = name.split("_")
    head = parts[0]
    if not head:
        return "input"
    tail = "".join(part[:1].upper() + part[1:] for part in parts[1:] if part)
    return head[:1].lower() + head[1:] + tail
