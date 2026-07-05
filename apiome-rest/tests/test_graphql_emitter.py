"""Tests for the GraphQL SDL emitter — MFX-13.1 (#3884), MFX-13.2 (#3885).

Exercises the acceptance criteria: emits **valid SDL** via ``graphql-core``
``print_schema``, **nullability/list wrappers** reproduce exactly, emission is
deterministic, a Graph-native source is a fixed point of ``normalize ∘ emit``, and
cross-paradigm request bodies produce synthesized **input** types (no output-as-input
violations).
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLInputObjectType, GraphQLNamedType, GraphQLNonNull, GraphQLString, validate_schema

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import Provenance, get_emitter
from app.graphql_emitter import GraphQlEmitter
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.openapi_normalizer import OpenApiNormalizer

# Reuse the representative blog schema from the normalizer tests.
_BLOG_SDL = '''
"""A small blog schema."""
directive @auth(role: String!) repeatable on FIELD_DEFINITION | OBJECT

scalar DateTime @specifiedBy(url: "https://example.com/datetime")

interface Node {
  id: ID!
}

"""A registered user."""
type User implements Node @auth(role: "admin") {
  id: ID!
  name: String!
  tags: [String!]!
  posts(first: Int = 10, after: String): [Post!] @auth(role: "self")
  status: Status @deprecated(reason: "use state instead")
  createdAt: DateTime
}

type Post implements Node {
  id: ID!
  title: String!
  author: User!
}

union SearchResult = User | Post

enum Status {
  ACTIVE
  INACTIVE @deprecated
}

input UserFilter {
  namePrefix: String = "a"
  minPosts: Int!
}

type Query {
  user(id: ID!): User
  search(q: String!): [SearchResult!]!
}

type Mutation {
  createUser(filter: UserFilter!): User!
}

type Subscription {
  userAdded: User!
}
'''


def _normalize(sdl: str = _BLOG_SDL, *, include_raw: bool = True) -> CanonicalApi:
    schema = build_graphql_schema(sdl)
    return GraphQlNormalizer().normalize(schema, include_raw=include_raw)


def _field(api: CanonicalApi, type_key: str, field_name: str):
    type_ = api.type_by_key(type_key)
    assert type_ is not None, f"type {type_key!r} missing"
    for field in type_.fields:
        if field.name == field_name:
            return field
    raise AssertionError(f"field {type_key}.{field_name} missing")


def _operation(api: CanonicalApi, op_key: str):
    for op in api.operations():
        if op.key == op_key:
            return op
    raise AssertionError(f"operation {op_key!r} missing")


def _emit(api: CanonicalApi) -> str:
    result = GraphQlEmitter().emit(api)
    assert len(result.files) == 1
    return result.files[0].content


def _emit_and_build(api: CanonicalApi):
    sdl = _emit(api)
    schema = build_graphql_schema(sdl)
    errors = validate_schema(schema)
    assert not errors, [e.message for e in errors]
    return sdl, schema


def _named_type(gql_type: Any) -> GraphQLNamedType:
    if isinstance(gql_type, GraphQLNonNull):
        return gql_type.of_type
    assert isinstance(gql_type, GraphQLNamedType)
    return gql_type


# ---------------------------------------------------------------------------
# Registration + basic emit
# ---------------------------------------------------------------------------


def test_registered_under_graphql_format() -> None:
    assert get_emitter("graphql") is GraphQlEmitter


def test_emits_valid_schema_for_blog_fixture() -> None:
    api = _normalize()
    sdl, _ = _emit_and_build(api)
    assert "type User" in sdl
    assert "type Query" in sdl
    assert "type Mutation" in sdl
    assert "type Subscription" in sdl


def test_emission_is_deterministic() -> None:
    api = _normalize()
    first = _emit(api)
    second = _emit(api)
    assert first == second


# ---------------------------------------------------------------------------
# Nullability / list wrapper fidelity
# ---------------------------------------------------------------------------


def test_nullability_and_list_wrappers_in_emitted_sdl() -> None:
    api = _normalize()
    sdl = _emit(api)

    user = _field(api, "User", "id")
    assert user.type.name == "ID" and user.type.nullable is False
    assert "id: ID!" in sdl

    tags = _field(api, "User", "tags")
    assert tags.type.is_list() and tags.type.item.name == "String"
    assert tags.type.item.nullable is False and tags.type.nullable is False
    assert "tags: [String!]!" in sdl

    search = _operation(api, "Query.search")
    payload = search.messages[0].payload
    assert payload.is_list() and payload.item.name == "SearchResult"
    assert payload.item.nullable is False and payload.nullable is False
    assert "search(q: String!): [SearchResult!]!" in sdl


# ---------------------------------------------------------------------------
# Graph-native fixed point
# ---------------------------------------------------------------------------

_SIMPLE_SDL = """
type Query {
  ping: String!
  echo(msg: String = "hi"): String
  user: User
}

type User {
  id: ID!
  name: String
}
"""


def test_graph_native_fixed_point() -> None:
    api = GraphQlNormalizer().normalize(
        build_graphql_schema(_SIMPLE_SDL), include_raw=False
    )
    sdl, schema = _emit_and_build(api)
    assert "ping: String!" in sdl
    again = GraphQlNormalizer().normalize(schema, include_raw=False)
    assert api.model_dump() == again.model_dump()


def test_blog_types_survive_emit_round_trip() -> None:
    """Structural round-trip for the rich blog schema (directives may differ)."""
    api = _normalize(include_raw=False)
    _, schema = _emit_and_build(api)
    again = GraphQlNormalizer().normalize(schema, include_raw=False)

    assert {t.key for t in again.types} == {t.key for t in api.types}
    assert {s.key for s in again.services} == {s.key for s in api.services}

    for type_key in ("User", "UserFilter", "SearchResult"):
        before = api.type_by_key(type_key)
        after = again.type_by_key(type_key)
        assert before.kind == after.kind
        assert before.extras.get("graphql_type") == after.extras.get("graphql_type")
        for field_name in (f.name for f in before.fields):
            bf = _field(api, type_key, field_name)
            af = _field(again, type_key, field_name)
            assert bf.type.model_dump() == af.type.model_dump()


# ---------------------------------------------------------------------------
# Cross-paradigm heuristic (REST → Query/Mutation)
# ---------------------------------------------------------------------------


def _petstore_openapi() -> dict:
    """Minimal petstore excerpt with GET + POST operations."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Pet Store", "version": "1.4.0"},
        "paths": {
            "/pets/{id}": {
                "get": {
                    "operationId": "getPet",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        }
                    },
                }
            },
            "/pets": {
                "post": {
                    "operationId": "createPet",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                }
            },
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            }
        },
    }


def _petstore_api() -> CanonicalApi:
    return OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)


def test_rest_source_maps_get_to_query_and_post_to_mutation() -> None:
    api = _petstore_api()
    sdl, schema = _emit_and_build(api)
    assert schema.query_type is not None
    assert schema.mutation_type is not None
    query_fields = set(schema.query_type.fields.keys())
    mutation_fields = set(schema.mutation_type.fields.keys())
    assert "getPet" in query_fields
    assert mutation_fields & {"createPet", "addPet"}
    assert "type Query" in sdl
    assert "type Mutation" in sdl


def test_rest_emit_marks_inferred_provenance() -> None:
    result = GraphQlEmitter().emit(_petstore_api())
    inferred = [r for r in result.provenance if r.provenance is Provenance.INFERRED]
    assert inferred


def test_openapi_to_graphql_and_back_preserves_types() -> None:
    """OpenAPI → GraphQL SDL → normalize keeps named component schemas."""
    api = _petstore_api()
    sdl = _emit(api)
    assert "Pet" in sdl
    again = GraphQlNormalizer().normalize(build_graphql_schema(sdl), include_raw=False)
    assert again.type_by_key("Pet") is not None
    assert again.type_by_key("Pet").kind is TypeKind.RECORD


# ---------------------------------------------------------------------------
# Input/output type splitting (MFX-13.2)
# ---------------------------------------------------------------------------


def test_rest_request_body_produces_synthesized_input_type() -> None:
    api = _petstore_api()
    sdl, schema = _emit_and_build(api)
    assert "input PetInput" in sdl
    assert "type Pet" in sdl
    mutation = schema.mutation_type.fields["createPet"]
    pet_arg = _named_type(mutation.args["pet"].type)
    assert isinstance(pet_arg, GraphQLInputObjectType)
    assert pet_arg.name == "PetInput"
    assert set(pet_arg.fields.keys()) == {"id", "name"}


def test_synthesized_inputs_are_reported_as_losses() -> None:
    result = GraphQlEmitter().emit(_petstore_api())
    synth = [loss for loss in result.losses if loss.subject == "synthesized-input"]
    assert synth
    assert any("PetInput" in loss.detail for loss in synth)


def test_synthesized_inputs_are_deduped_across_operations() -> None:
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Dup", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "post": {
                    "operationId": "createPet",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                },
                "put": {
                    "operationId": "replacePet",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        },
                    },
                    "responses": {"200": {"description": "ok"}},
                },
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            }
        },
    }
    api = OpenApiNormalizer().normalize(spec, include_raw=False)
    sdl, schema = _emit_and_build(api)
    assert sdl.count("input PetInput") == 1
    create_arg = _named_type(schema.mutation_type.fields["createPet"].args["pet"].type)
    replace_arg = _named_type(schema.mutation_type.fields["replacePet"].args["pet"].type)
    assert create_arg is replace_arg


def test_nested_output_records_produce_nested_input_types() -> None:
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Nested", "version": "1.0.0"},
        "paths": {
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Order"}
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                }
            }
        },
        "components": {
            "schemas": {
                "Customer": {
                    "type": "object",
                    "properties": {"email": {"type": "string"}},
                },
                "Order": {
                    "type": "object",
                    "properties": {
                        "customer": {"$ref": "#/components/schemas/Customer"},
                    },
                },
            }
        },
    }
    api = OpenApiNormalizer().normalize(spec, include_raw=False)
    sdl, schema = _emit_and_build(api)
    assert "input OrderInput" in sdl
    assert "input CustomerInput" in sdl
    order_input = _named_type(schema.mutation_type.fields["createOrder"].args["order"].type)
    customer_field = _named_type(order_input.fields["customer"].type)
    assert customer_field.name == "CustomerInput"


def test_graph_native_input_types_are_not_double_suffixed() -> None:
    api = _normalize()
    sdl, schema = _emit_and_build(api)
    assert "input UserFilterInput" not in sdl
    assert "input UserFilter" in sdl
    create_user = schema.mutation_type.fields["createUser"]
    filter_arg = _named_type(create_user.args["filter"].type)
    assert isinstance(filter_arg, GraphQLInputObjectType)
    assert filter_arg.name == "UserFilter"


def test_field_arguments_use_input_types_for_output_references() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="openapi-3.1",
        identity=ApiIdentity(name="Args"),
        types=[
            Type(
                key="Filter",
                name="Filter",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="Filter.name",
                        name="name",
                        type=TypeRef(name="String"),
                    )
                ],
            ),
            Type(
                key="Pet",
                name="Pet",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="Pet.findSimilar",
                        name="findSimilar",
                        type=TypeRef(name="String", nullable=False),
                        extras={
                            "arguments": [
                                {
                                    "name": "filter",
                                    "type": TypeRef(name="Filter", nullable=False),
                                }
                            ]
                        },
                    )
                ],
            ),
        ],
        services=[
            Service(
                key="Query",
                name="Query",
                operations=[
                    Operation(
                        key="Query.pets",
                        name="pets",
                        kind=OperationKind.QUERY,
                        messages=[
                            Message(
                                key="Query.pets#response",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="Pet", nullable=False),
                            )
                        ],
                    )
                ],
            )
        ],
    )
    sdl, schema = _emit_and_build(api)
    assert "input FilterInput" in sdl
    pet_type = schema.type_map["Pet"]
    field = pet_type.fields["findSimilar"]
    assert _named_type(field.args["filter"].type).name == "FilterInput"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_graph_native_provenance_tags_source_types() -> None:
    result = GraphQlEmitter().emit(_normalize())
    paths = {r.pointer for r in result.provenance}
    assert "/types/User" in paths
    assert "/Query" in paths


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_api_emits_minimal_query_schema() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="Empty"),
    )
    sdl, schema = _emit_and_build(api)
    assert schema.query_type is not None
    assert "type Query" in sdl


def test_event_operations_recorded_as_losses() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="Events"),
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="channel/publish",
                        name="publish",
                        kind=OperationKind.PUBLISH,
                    )
                ],
            )
        ],
    )
    result = GraphQlEmitter().emit(api)
    assert any(loss.subject == "event-operation" for loss in result.losses)


def test_manual_operation_without_response_gets_string_fallback() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        identity=ApiIdentity(name="Partial"),
        services=[
            Service(
                key="Query",
                name="Query",
                operations=[
                    Operation(
                        key="Query.noop",
                        name="noop",
                        kind=OperationKind.QUERY,
                        parameters=[
                            Parameter(
                                key="Query.noop#arg.id",
                                name="id",
                                location=ParameterLocation.QUERY,
                                type=TypeRef(name="ID", nullable=False),
                                required=True,
                            )
                        ],
                        messages=[],
                    )
                ],
            )
        ],
    )
    _, schema = _emit_and_build(api)
    field = schema.query_type.fields["noop"]
    assert field.type is GraphQLString


def test_map_types_fall_back_to_string_and_record_loss_message() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="proto",
        identity=ApiIdentity(name="Maps"),
        types=[
            Type(
                key="p.Holder.AttrsEntry",
                name="AttrsEntry",
                kind=TypeKind.MAP,
                key_type=TypeRef(name="String", nullable=False),
                value_type=TypeRef(name="Int", nullable=False),
            )
        ],
        services=[
            Service(
                key="Query",
                name="Query",
                operations=[
                    Operation(
                        key="Query.attrs",
                        name="attrs",
                        kind=OperationKind.QUERY,
                        messages=[
                            Message(
                                key="Query.attrs#response",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="p.Holder.AttrsEntry"),
                            )
                        ],
                    )
                ],
            )
        ],
    )

    result = GraphQlEmitter().emit(api)
    assert any(
        loss.subject == "map-type" and "emitted as String" in loss.detail
        for loss in result.losses
    )
    _, schema = _emit_and_build(api)
    assert schema.query_type.fields["attrs"].type is GraphQLString


def test_distinct_type_keys_with_same_name_get_distinct_graphql_types() -> None:
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="proto",
        identity=ApiIdentity(name="Nested"),
        types=[
            Type(
                key="ParentA.Entry",
                name="Entry",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="ParentA.Entry.a",
                        name="a",
                        type=TypeRef(name="String"),
                    )
                ],
            ),
            Type(
                key="ParentB.Entry",
                name="Entry",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="ParentB.Entry.b",
                        name="b",
                        type=TypeRef(name="Int"),
                    )
                ],
            ),
        ],
        services=[
            Service(
                key="Query",
                name="Query",
                operations=[
                    Operation(
                        key="Query.left",
                        name="left",
                        kind=OperationKind.QUERY,
                        messages=[
                            Message(
                                key="Query.left#response",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="ParentA.Entry"),
                            )
                        ],
                    ),
                    Operation(
                        key="Query.right",
                        name="right",
                        kind=OperationKind.QUERY,
                        messages=[
                            Message(
                                key="Query.right#response",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="ParentB.Entry"),
                            )
                        ],
                    ),
                ],
            )
        ],
    )

    sdl, schema = _emit_and_build(api)
    left_type = schema.query_type.fields["left"].type
    right_type = schema.query_type.fields["right"].type
    assert left_type.name != right_type.name
    assert left_type.fields.keys() == {"a"}
    assert right_type.fields.keys() == {"b"}
    assert "type ParentA_Entry" in sdl
    assert "type ParentB_Entry" in sdl
