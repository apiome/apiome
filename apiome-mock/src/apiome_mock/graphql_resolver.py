"""Field-by-field value resolution for the GraphQL mock (#5729, XPC-1.1).

``graphql-core`` executes an operation by calling one resolver per selected field. Every field
the mock answers goes through :meth:`GraphQlValueResolver.resolve_field`, which takes the first
layer that has a value. The layers are the REST path's, in the same order:

1. **Scenario override.** Root fields only. The transport renders the scenario before execution
   and hands this resolver either a value or a GraphQL error for each root field it covers.
2. **Parent value.** A scenario body, an example or a fixture that already holds this field.
3. **Declared example** on the canonical field or root operation (``Query.user``), then on the
   field's named type (``User``).
4. **Fixture-pack value** keyed by the field's schema coordinate (``Query.user``,
   ``User.email``), from ``mock_settings.fixturePacks``.
5. **Synthesized value.** :func:`apiome_mock.schema_synthesizer.generate_example` under the
   request seed. The seed is mixed with the field's response path, so the same seed always gives
   the same response while two fields never share a value by accident.

An object the mock invents is an empty dict, so each of its fields resolves through these layers
in turn. That keeps synthesis lazy (only selected fields are generated) and lets a partial
example be completed by synthesized values.

A declared example is read from an entity's ``extras``: an ``example`` value, the first item of
an ``examples`` list, or an applied ``@example(value: …)`` directive. A string ``value`` that
holds JSON is decoded, so ``@example(value: "{\\"id\\": 1}")`` gives an object.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.canonical_model import CanonicalApi
from graphql import (
    DirectiveNode,
    GraphQLAbstractType,
    GraphQLEnumType,
    GraphQLError,
    GraphQLObjectType,
    GraphQLResolveInfo,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLSyntaxError,
    is_abstract_type,
    is_list_type,
    is_non_null_type,
    parse,
    value_from_ast_untyped,
)

from apiome_mock.schema_synthesizer import generate_example

__all__ = [
    "DeclaredExamples",
    "GraphQlValueResolver",
    "RootOverride",
    "collect_declared_examples",
]

_MISSING = object()
"""Sentinel for "this layer has no value" (``None`` is a real GraphQL value)."""

_BUILTIN_SCALAR_SCHEMAS: dict[str, dict[str, Any]] = {
    "Int": {"type": "integer", "minimum": 0, "maximum": 1000},
    "Float": {"type": "number", "minimum": 0, "maximum": 1000},
    "String": {"type": "string"},
    "Boolean": {"type": "boolean"},
    "ID": {"type": "string", "format": "uuid"},
}
"""JSON Schemas the synthesizer generates the five built-in scalars from."""

_CUSTOM_SCALAR_FORMATS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("datetime", {"type": "string", "format": "date-time"}),
    ("timestamp", {"type": "string", "format": "date-time"}),
    ("date", {"type": "string", "format": "date"}),
    ("time", {"type": "string", "format": "time"}),
    ("email", {"type": "string", "format": "email"}),
    ("uuid", {"type": "string", "format": "uuid"}),
    ("url", {"type": "string", "format": "uri"}),
    ("uri", {"type": "string", "format": "uri"}),
    ("long", {"type": "integer", "minimum": 0, "maximum": 1000}),
    ("bigint", {"type": "integer", "minimum": 0, "maximum": 1000}),
    ("decimal", {"type": "number", "minimum": 0, "maximum": 1000}),
    ("json", {"type": "object"}),
)
"""Custom scalar name fragments (lower-cased) and the JSON Schema each is synthesized from."""


@dataclass(frozen=True)
class DeclaredExamples:
    """Examples declared on a canonical GraphQL model, keyed for resolver lookup.

    Attributes:
        fields: Example values by schema coordinate (``Query.user``, ``User.email``).
        types: Example values by named type (``User``).
    """

    fields: Mapping[str, Any] = field(default_factory=dict)
    types: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RootOverride:
    """What a scenario decided for one root field, computed by the transport before execution.

    Exactly one of ``value`` and ``error`` is meaningful: an ``error`` is raised from the field's
    resolver (so it lands in ``errors[]`` with that field's path), otherwise ``value`` is returned.
    """

    value: Any = None
    error: GraphQLError | None = None


def _decode_example(value: Any) -> Any:
    """Decode a string example that holds JSON; return anything else unchanged."""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in {"{", "["}:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _example_from_directive(printed: str) -> Any:
    """Read the ``value`` argument of a printed ``@example(value: …)`` directive.

    Args:
        printed: One applied directive as the normalizer stores it (``@example(value: 3)``).

    Returns:
        The decoded argument value, or :data:`_MISSING` when ``printed`` is not an ``@example``
        directive with a ``value`` argument.
    """
    if not printed.startswith("@example"):
        return _MISSING
    try:
        document = parse(f"query _ {printed} {{ _ }}")
    except GraphQLSyntaxError:
        return _MISSING
    operation = document.definitions[0]
    directives: tuple[DirectiveNode, ...] = tuple(getattr(operation, "directives", ()) or ())
    for directive in directives:
        if directive.name.value != "example":
            continue
        for argument in directive.arguments or ():
            if argument.name.value == "value":
                return _decode_example(value_from_ast_untyped(argument.value))
    return _MISSING


def _example_from_extras(extras: Mapping[str, Any]) -> Any:
    """Return the example an entity's ``extras`` declares, or :data:`_MISSING`.

    Args:
        extras: A canonical entity's ``extras`` bag.

    Returns:
        ``extras["example"]``, else the first ``extras["examples"]`` item, else the value of an
        applied ``@example`` directive, else :data:`_MISSING`.
    """
    if "example" in extras:
        return _decode_example(extras["example"])
    examples = extras.get("examples")
    if isinstance(examples, list) and examples:
        return _decode_example(examples[0])
    directives = extras.get("directives")
    if isinstance(directives, list):
        for printed in directives:
            if isinstance(printed, str):
                found = _example_from_directive(printed)
                if found is not _MISSING:
                    return found
    return _MISSING


def collect_declared_examples(api: CanonicalApi) -> DeclaredExamples:
    """Index every example a canonical GraphQL model declares.

    Root operations contribute through their own ``extras`` and their response message's
    ``extras``. Record fields contribute by ``Type.field`` coordinate and named types by key.

    Args:
        api: The version's canonical model.

    Returns:
        The :class:`DeclaredExamples` index.
    """
    fields: dict[str, Any] = {}
    types: dict[str, Any] = {}
    for operation in api.operations():
        found = _example_from_extras(operation.extras)
        if found is _MISSING:
            for message in operation.messages:
                found = _example_from_extras(message.extras)
                if found is not _MISSING:
                    break
        if found is not _MISSING:
            fields[operation.key] = found
    for type_ in api.types:
        found = _example_from_extras(type_.extras)
        if found is not _MISSING:
            types[type_.key] = found
        for canonical_field in type_.fields:
            found = _example_from_extras(canonical_field.extras)
            if found is not _MISSING:
                fields[canonical_field.key] = found
    return DeclaredExamples(fields=fields, types=types)


def _derived_seed(seed: int, path_key: str) -> int:
    """Mix the request seed with a response path so every field gets its own stable value."""
    digest = hashlib.sha256(path_key.encode("utf-8")).hexdigest()
    return seed ^ int(digest[:16], 16)


def _scalar_schema(scalar: GraphQLScalarType) -> dict[str, Any]:
    """Return the JSON Schema a scalar's synthesized values are drawn from."""
    builtin = _BUILTIN_SCALAR_SCHEMAS.get(scalar.name)
    if builtin is not None:
        return builtin
    lowered = scalar.name.lower()
    for fragment, schema in _CUSTOM_SCALAR_FORMATS:
        if fragment in lowered:
            return schema
    return {"type": "string"}


class GraphQlValueResolver:
    """The ``field_resolver`` / ``type_resolver`` pair one GraphQL mock request executes with.

    Args:
        schema: The executable schema.
        examples: The version's declared examples.
        fixtures: Fixture-pack values by schema coordinate (and any other fixture names).
        seed: The request seed.
        list_length: Number of items in every synthesized list.
        root_overrides: Scenario decisions by root-field coordinate (``Query.user``).
    """

    def __init__(
        self,
        *,
        schema: GraphQLSchema,
        examples: DeclaredExamples,
        fixtures: Mapping[str, Any],
        seed: int,
        list_length: int,
        root_overrides: Mapping[str, RootOverride] | None = None,
    ) -> None:
        self._schema = schema
        self._examples = examples
        self._fixtures = fixtures
        self._seed = seed
        self._list_length = list_length
        self._root_overrides = dict(root_overrides or {})
        self._root_names = {
            root.name for root in (schema.query_type, schema.mutation_type, schema.subscription_type) if root
        }

    def resolve_field(self, source: Any, info: GraphQLResolveInfo, **_arguments: Any) -> Any:
        """Resolve one field through the layers in the module docstring.

        Args:
            source: The parent value (``None`` at the root, else a dict).
            info: ``graphql-core``'s resolve info for this field.
            **_arguments: The field's arguments (accepted, not used to shape the value).

        Returns:
            The field's value.

        Raises:
            GraphQLError: When a scenario turned this root field into an error.
        """
        coordinate = f"{info.parent_type.name}.{info.field_name}"
        if info.parent_type.name in self._root_names:
            override = self._root_overrides.get(coordinate)
            if override is not None:
                if override.error is not None:
                    raise override.error
                return copy.deepcopy(override.value)
        elif isinstance(source, Mapping) and info.field_name in source:
            return source[info.field_name]

        example = self._examples.fields.get(coordinate, _MISSING)
        if example is not _MISSING:
            return copy.deepcopy(example)
        if coordinate in self._fixtures:
            return copy.deepcopy(self._fixtures[coordinate])
        path_key = "/".join(str(part) for part in info.path.as_list())
        return self.synthesize(info.return_type, field_name=info.field_name, path_key=path_key)

    def resolve_type(self, value: Any, info: GraphQLResolveInfo, abstract_type: GraphQLAbstractType) -> str | None:
        """Pick the concrete type of an interface or union value.

        A value that names its ``__typename`` (an example or a scenario body can) gets that type
        when it is one of the possible types. Anything else gets the first possible type by name.

        Args:
            value: The resolved value.
            info: ``graphql-core``'s resolve info.
            abstract_type: The interface or union being resolved.

        Returns:
            The concrete object type's name, or ``None`` when the abstract type has no members.
        """
        possible = sorted(member.name for member in self._schema.get_possible_types(abstract_type))
        if isinstance(value, Mapping):
            named = value.get("__typename")
            if isinstance(named, str) and named in possible:
                return named
        return possible[0] if possible else None

    def synthesize(self, output_type: Any, *, field_name: str, path_key: str) -> Any:
        """Generate a seeded value for one output type.

        Args:
            output_type: The field's ``graphql-core`` output type (wrappers included).
            field_name: The field's name, which steers the synthesizer's name hints (``email``…).
            path_key: The field's response path, mixed into the seed.

        Returns:
            A list, scalar or enum value, or a dict for an object (whose fields then resolve one by
            one). Interfaces and unions get ``{"__typename": <member>}``.
        """
        if is_non_null_type(output_type):
            output_type = output_type.of_type
        if is_list_type(output_type):
            return [
                self.synthesize(output_type.of_type, field_name=field_name, path_key=f"{path_key}/{index}")
                for index in range(self._list_length)
            ]
        example = self._examples.types.get(output_type.name, _MISSING)
        if example is not _MISSING:
            return copy.deepcopy(example)
        seed = _derived_seed(self._seed, path_key)
        if isinstance(output_type, GraphQLScalarType):
            return generate_example(_scalar_schema(output_type), seed=seed, field=field_name)
        if isinstance(output_type, GraphQLEnumType):
            names = sorted(output_type.values)
            return names[seed % len(names)] if names else None
        if isinstance(output_type, GraphQLObjectType):
            return {}
        if is_abstract_type(output_type):
            members = sorted(member.name for member in self._schema.get_possible_types(output_type))
            return {"__typename": members[seed % len(members)]} if members else None
        return None
