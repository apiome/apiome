"""End-to-end tests for the GraphQL normalizer (MFI-10.2, #3771).

Exercises the acceptance criteria — *nullability/list wrappers preserved* and
*fingerprint stable* — by feeding the **real** MFI-10.1 parser output (a built
``graphql-core`` ``GraphQLSchema``) into the normalizer. A representative blog
schema (object/interface/input/union/enum/scalar types, list/non-null wrappers,
field arguments, custom + applied directives, and all three root operation types)
maps into the canonical GRAPH model; the wrappers reproduce exactly, services/
operations key on Schema Coordinates, the output is deterministically ordered and
idempotent, its fingerprint is invariant to source declaration order yet flips on a
structural change (wrapper/argument/directive), the model survives the JSONB
round-trip, and the error path behaves.

``graphql-core`` is a first-class Python dependency, so every test runs the real
parser + normalizer — there is no gated "real tool" tier.
"""

from __future__ import annotations

import pytest

from app.canonical_model import (
    ApiParadigm,
    CanonicalApi,
    MessageRole,
    OperationKind,
    ParameterLocation,
    StreamingMode,
    TypeKind,
)
from app.fingerprint import canonical_fingerprint
from app.graphql_normalizer import GraphQlNormalizer
from app.graphql_parser import build_graphql_schema
from app.normalizer import get_normalizer

# ===========================================================================
# Representative schema (covers every type family + wrapper + directive)
# ===========================================================================

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
    """Build ``sdl`` with the real parser and normalize it (the full MFI-10.1→10.2 path)."""
    schema = build_graphql_schema(sdl)
    return GraphQlNormalizer().normalize(schema, include_raw=include_raw)


def _field(api: CanonicalApi, type_key: str, field_name: str):
    """Return the named field of a type, or fail the test if absent."""
    type_ = api.type_by_key(type_key)
    assert type_ is not None, f"type {type_key!r} missing"
    for field in type_.fields:
        if field.name == field_name:
            return field
    pytest.fail(f"field {type_key}.{field_name} missing")


def _operation(api: CanonicalApi, op_key: str):
    """Return the operation with ``op_key`` across all services, or fail."""
    for op in api.operations():
        if op.key == op_key:
            return op
    pytest.fail(f"operation {op_key!r} missing")


# ===========================================================================
# Artifact-level shape + registration
# ===========================================================================


def test_registered_under_graphql_format() -> None:
    assert get_normalizer("graphql") is GraphQlNormalizer


def test_artifact_paradigm_format_protocol() -> None:
    api = _normalize()
    assert api.paradigm is ApiParadigm.GRAPH
    assert api.format == "graphql"
    assert api.protocol == "graphql"
    assert api.identity.name == "GraphQL Schema"


def test_non_schema_source_raises() -> None:
    with pytest.raises(ValueError, match="GraphQLSchema"):
        GraphQlNormalizer().normalize({"not": "a schema"})


def test_raw_holds_sdl_when_included_and_omitted_otherwise() -> None:
    assert "type User" in _normalize().raw["sdl"]
    assert _normalize(include_raw=False).raw is None


# ===========================================================================
# Named types: kind mapping + the GraphQL family kept in extras
# ===========================================================================


def test_user_defined_types_present_builtins_and_roots_excluded() -> None:
    api = _normalize()
    keys = {t.key for t in api.types}
    # Every user type is present...
    assert keys == {"DateTime", "Node", "Post", "SearchResult", "Status", "User", "UserFilter"}
    # ...built-in scalars and the root operation types are not.
    assert "String" not in keys and "Int" not in keys and "ID" not in keys
    assert "Query" not in keys and "Mutation" not in keys and "Subscription" not in keys


def test_object_type_is_record_with_family_and_interfaces() -> None:
    user = _normalize().type_by_key("User")
    assert user.kind is TypeKind.RECORD
    assert user.extras["graphql_type"] == "object"
    assert user.extras["interfaces"] == ["Node"]
    assert user.description == "A registered user."


def test_interface_type_is_record_flagged_interface() -> None:
    node = _normalize().type_by_key("Node")
    assert node.kind is TypeKind.RECORD
    assert node.extras["graphql_type"] == "interface"
    assert "interfaces" not in node.extras  # implements nothing


def test_input_type_is_record_with_defaults() -> None:
    api = _normalize()
    filter_ = api.type_by_key("UserFilter")
    assert filter_.kind is TypeKind.RECORD
    assert filter_.extras["graphql_type"] == "input"
    name_prefix = _field(api, "UserFilter", "namePrefix")
    assert name_prefix.default == "a"
    assert name_prefix.type.nullable is True
    min_posts = _field(api, "UserFilter", "minPosts")
    assert min_posts.default is None
    assert min_posts.type.nullable is False


def test_union_type_lists_member_keys() -> None:
    union = _normalize().type_by_key("SearchResult")
    assert union.kind is TypeKind.UNION
    assert sorted(union.union_members) == ["Post", "User"]


def test_enum_type_values_and_deprecation() -> None:
    status = _normalize().type_by_key("Status")
    assert status.kind is TypeKind.ENUM
    by_name = {v.name: v for v in status.enum_values}
    assert set(by_name) == {"ACTIVE", "INACTIVE"}
    assert by_name["ACTIVE"].deprecated is False
    assert by_name["INACTIVE"].deprecated is True
    assert by_name["INACTIVE"].key == "Status.INACTIVE"


def test_custom_scalar_keeps_specified_by_url() -> None:
    dt = _normalize().type_by_key("DateTime")
    assert dt.kind is TypeKind.SCALAR
    assert dt.extras["graphql_type"] == "scalar"
    assert dt.extras["specified_by_url"] == "https://example.com/datetime"
    # @specifiedBy is captured structurally, not echoed as an applied directive.
    assert "directives" not in dt.extras


# ===========================================================================
# Nullability / list wrappers preserved (the acceptance criterion)
# ===========================================================================


def test_non_null_scalar_wrapper() -> None:
    # name: String!  ->  nullable=False leaf
    name = _field(_normalize(), "User", "name").type
    assert name.name == "String" and name.nullable is False and name.item is None


def test_nullable_named_wrapper() -> None:
    # createdAt: DateTime  ->  nullable leaf
    created = _field(_normalize(), "User", "createdAt").type
    assert created.name == "DateTime" and created.nullable is True


def test_non_null_list_of_non_null_wrapper() -> None:
    # tags: [String!]!  ->  list(nullable=False) of String(nullable=False)
    tags = _field(_normalize(), "User", "tags").type
    assert tags.name is None and tags.nullable is False
    assert tags.item is not None
    assert tags.item.name == "String" and tags.item.nullable is False


def test_nullable_list_of_non_null_wrapper() -> None:
    # posts: [Post!]  ->  list(nullable=True) of Post(nullable=False)
    posts = _field(_normalize(), "User", "posts").type
    assert posts.name is None and posts.nullable is True
    assert posts.item is not None
    assert posts.item.name == "Post" and posts.item.nullable is False


def test_non_null_list_of_non_null_named_in_operation_response() -> None:
    # Query.search: [SearchResult!]!
    payload = _operation(_normalize(), "Query.search").messages[0].payload
    assert payload.nullable is False and payload.item is not None
    assert payload.item.name == "SearchResult" and payload.item.nullable is False


# ===========================================================================
# Fields: arguments + deprecation kept on non-root fields
# ===========================================================================


def test_field_coordinate_key() -> None:
    assert _field(_normalize(), "User", "name").key == "User.name"


def test_non_root_field_arguments_kept_in_extras() -> None:
    posts = _field(_normalize(), "User", "posts")
    args = {a["name"]: a for a in posts.extras["arguments"]}
    assert set(args) == {"first", "after"}
    assert args["first"]["default"] == 10
    assert args["first"]["type"]["name"] == "Int"
    assert "default" not in args["after"]  # no default declared


def test_field_deprecation_reason_captured() -> None:
    status = _field(_normalize(), "User", "status")
    assert status.deprecated is True
    assert status.extras["deprecation_reason"] == "use state instead"


def test_applied_directive_kept_on_type_and_field() -> None:
    api = _normalize()
    assert api.type_by_key("User").extras["directives"] == ['@auth(role: "admin")']
    assert _field(api, "User", "posts").extras["directives"] == ['@auth(role: "self")']


# ===========================================================================
# Services / operations: root types -> services, fields -> operations
# ===========================================================================


def test_services_are_the_root_operation_types() -> None:
    api = _normalize()
    assert {s.key for s in api.services} == {"Query", "Mutation", "Subscription"}


def test_operation_kinds_and_streaming() -> None:
    api = _normalize()
    assert _operation(api, "Query.user").kind is OperationKind.QUERY
    assert _operation(api, "Query.user").streaming is StreamingMode.NONE
    assert _operation(api, "Mutation.createUser").kind is OperationKind.MUTATION
    sub = _operation(api, "Subscription.userAdded")
    assert sub.kind is OperationKind.SUBSCRIPTION
    assert sub.streaming is StreamingMode.SERVER


def test_operation_arguments_become_parameters() -> None:
    op = _operation(_normalize(), "Query.user")
    assert len(op.parameters) == 1
    param = op.parameters[0]
    assert param.key == "Query.user#arg.id"
    assert param.location is ParameterLocation.QUERY
    assert param.type.name == "ID" and param.type.nullable is False
    assert param.required is True  # non-null, no default


def test_argument_with_default_is_not_required() -> None:
    # Mutation.createUser(filter: UserFilter!)  -> required; contrast with a
    # defaulted optional via the non-root posts(first: Int = 10) arg above.
    op = _operation(_normalize(), "Mutation.createUser")
    assert op.parameters[0].required is True


def test_operation_response_message_carries_return_type() -> None:
    op = _operation(_normalize(), "Query.user")
    assert len(op.messages) == 1
    msg = op.messages[0]
    assert msg.key == "Query.user#response"
    assert msg.role is MessageRole.RESPONSE
    assert msg.payload.name == "User" and msg.payload.nullable is True


# ===========================================================================
# Directive definitions captured on the artifact
# ===========================================================================


def test_custom_directive_definition_captured_builtins_excluded() -> None:
    defs = _normalize().extras["directive_definitions"]
    assert len(defs) == 1
    auth = defs[0]
    assert auth["name"] == "auth"
    assert auth["repeatable"] is True
    assert auth["locations"] == ["FIELD_DEFINITION", "OBJECT"]
    assert auth["arguments"][0]["name"] == "role"
    arg_type = auth["arguments"][0]["type"]
    assert arg_type["name"] == "String" and arg_type["nullable"] is False


def test_no_directive_definitions_key_when_only_builtins() -> None:
    api = _normalize("type Query { ping: String }")
    assert "directive_definitions" not in api.extras


# ===========================================================================
# Determinism, idempotence, and JSONB round-trip
# ===========================================================================


def test_ordering_is_deterministic_and_idempotent() -> None:
    api = _normalize()
    assert [t.key for t in api.types] == sorted(t.key for t in api.types)
    again = _normalize()
    assert api.model_dump() == again.model_dump()


def test_survives_jsonb_round_trip() -> None:
    api = _normalize()
    restored = CanonicalApi.model_validate(api.model_dump())
    assert restored == api


# ===========================================================================
# Fingerprint: stable, order-invariant, flips on structural change
# ===========================================================================


def test_fingerprint_is_stable_across_runs() -> None:
    assert canonical_fingerprint(_normalize()) == canonical_fingerprint(_normalize())


def test_fingerprint_invariant_to_declaration_order_and_descriptions() -> None:
    reordered = '''
      type Query { user(id: ID!): User }
      """Different doc — must not change the fingerprint."""
      type User { name: String! id: ID! }
    '''
    baseline = '''
      type User { id: ID! name: String! }
      type Query { user(id: ID!): User }
    '''
    assert canonical_fingerprint(_normalize(reordered)) == canonical_fingerprint(
        _normalize(baseline)
    )


def test_fingerprint_flips_on_nullability_change() -> None:
    nullable = "type Query { me: User } type User { name: String }"
    non_null = "type Query { me: User } type User { name: String! }"
    assert canonical_fingerprint(_normalize(nullable)) != canonical_fingerprint(
        _normalize(non_null)
    )


def test_fingerprint_flips_on_list_wrapper_change() -> None:
    single = "type Query { me: User } type User { tags: String! }"
    listed = "type Query { me: User } type User { tags: [String!] }"
    assert canonical_fingerprint(_normalize(single)) != canonical_fingerprint(
        _normalize(listed)
    )


def test_fingerprint_flips_on_argument_change() -> None:
    without = "type Query { users: [String!]! }"
    with_arg = "type Query { users(first: Int): [String!]! }"
    assert canonical_fingerprint(_normalize(without)) != canonical_fingerprint(
        _normalize(with_arg)
    )


def test_fingerprint_flips_on_applied_directive_change() -> None:
    plain = 'directive @auth on FIELD_DEFINITION type Query { me: String }'
    authed = 'directive @auth on FIELD_DEFINITION type Query { me: String @auth }'
    assert canonical_fingerprint(_normalize(plain)) != canonical_fingerprint(
        _normalize(authed)
    )


def test_fingerprint_flips_on_directive_definition_change() -> None:
    one = "directive @a on OBJECT\ntype Query { me: String }"
    two = "directive @a on OBJECT\ndirective @b on OBJECT\ntype Query { me: String }"
    assert canonical_fingerprint(_normalize(one)) != canonical_fingerprint(
        _normalize(two)
    )
