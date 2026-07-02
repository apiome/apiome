"""Unit tests for the Normalizer SPI + base utilities (MFI-2.3, #3740).

Covers the format registry, the stable-key grammar, JSON-Schema constraint and
type coercion (the bit format epics reuse), and deterministic ordering
normalization — all independently of the reference OpenAPI normalizer (which has
its own end-to-end suite in ``test_openapi_normalizer.py``).
"""

import pytest

# Importing the reference normalizer registers the OpenAPI format keys.
import app.openapi_normalizer  # noqa: F401
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Channel,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    TypeKind,
    TypeRef,
)
from app.normalizer import (
    Keys,
    Normalizer,
    SchemaCoercer,
    available_formats,
    coerce_constraints,
    get_normalizer,
    normalize_ordering,
    register_normalizer,
)

# ===========================================================================
# Registry / SPI contract
# ===========================================================================


def test_openapi_normalizer_registers_both_versions() -> None:
    assert "openapi-3.0" in available_formats()
    assert "openapi-3.1" in available_formats()
    assert get_normalizer("openapi-3.1").format == "openapi-3.1"
    assert get_normalizer("openapi-3.0").format == "openapi-3.0"


def test_get_normalizer_unknown_returns_none() -> None:
    assert get_normalizer("does-not-exist") is None


def test_register_requires_nonempty_format() -> None:
    class _NoFormat(Normalizer):
        paradigm = ApiParadigm.REST

        def normalize(self, source, *, include_raw=True):  # pragma: no cover - contract stub
            raise NotImplementedError

    with pytest.raises(ValueError, match="non-empty `format`"):
        register_normalizer(_NoFormat)


def test_register_same_class_twice_is_noop_but_conflict_raises() -> None:
    class _FirstOwner(Normalizer):
        format = "unit-test-format"
        paradigm = ApiParadigm.RPC

        def normalize(self, source, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    register_normalizer(_FirstOwner)
    register_normalizer(_FirstOwner)  # idempotent
    assert get_normalizer("unit-test-format") is _FirstOwner

    class _SecondOwner(Normalizer):
        format = "unit-test-format"
        paradigm = ApiParadigm.RPC

        def normalize(self, source, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(ValueError, match="already registered"):
        register_normalizer(_SecondOwner)


def test_init_subclass_register_flag_auto_registers() -> None:
    class _AutoReg(Normalizer, register=True):
        format = "unit-test-auto"
        paradigm = ApiParadigm.EVENT

        def normalize(self, source, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    assert get_normalizer("unit-test-auto") is _AutoReg


def test_normalizer_is_abstract() -> None:
    with pytest.raises(TypeError):
        Normalizer()  # type: ignore[abstract]


# ===========================================================================
# Stable keys
# ===========================================================================


def test_key_grammar_matches_documented_coordinates() -> None:
    op = Keys.operation_http("get", "/pets/{id}")
    assert op == "GET /pets/{id}"  # verb upper-cased
    assert Keys.parameter(op, "path", "id") == "GET /pets/{id}#path.id"
    assert Keys.request_message(op) == "GET /pets/{id}#request"
    assert Keys.response_message(op, "200") == "GET /pets/{id}#response.200"
    assert Keys.type("Pet") == "Pet"
    assert Keys.type("Pet", "acme") == "acme.Pet"
    assert Keys.field("Pet", "name") == "Pet.name"
    assert Keys.enum_value("Status", "ACTIVE") == "Status.ACTIVE"
    assert Keys.operation_rpc("acme.PetService", "GetPet") == "acme.PetService.GetPet"
    assert Keys.operation_graphql("Query", "user") == "Query.user"


# ===========================================================================
# Constraint coercion (JSON-Schema vocabulary)
# ===========================================================================


def test_coerce_constraints_maps_json_schema_keywords() -> None:
    c = coerce_constraints(
        {
            "minLength": 1,
            "maxLength": 10,
            "pattern": "^a",
            "minimum": 0,
            "maximum": 100,
            "multipleOf": 2,
            "minItems": 1,
            "maxItems": 3,
            "uniqueItems": True,
            "enum": ["a", "b"],
            "format": "uuid",
        }
    )
    assert c is not None
    assert (c.min_length, c.max_length, c.pattern) == (1, 10, "^a")
    assert (c.minimum, c.maximum, c.multiple_of) == (0, 100, 2)
    assert (c.min_items, c.max_items, c.unique_items) == (1, 3, True)
    assert c.enum == ["a", "b"] and c.format == "uuid"


def test_coerce_constraints_none_when_empty() -> None:
    assert coerce_constraints({"type": "string", "description": "x"}) is None


def test_coerce_constraints_exclusive_numeric_form_31() -> None:
    c = coerce_constraints({"exclusiveMinimum": 0, "exclusiveMaximum": 10})
    assert c is not None
    assert c.exclusive_minimum == 0 and c.exclusive_maximum == 10
    assert c.minimum is None and c.maximum is None


def test_coerce_constraints_exclusive_boolean_form_30() -> None:
    # OpenAPI 3.0: exclusiveMinimum: true pairs with minimum and drops it.
    c = coerce_constraints({"minimum": 0, "exclusiveMinimum": True})
    assert c is not None
    assert c.exclusive_minimum == 0 and c.minimum is None


def test_coerce_constraints_exclusive_boolean_false_keeps_inclusive() -> None:
    c = coerce_constraints({"minimum": 0, "exclusiveMinimum": False})
    assert c is not None
    assert c.minimum == 0 and c.exclusive_minimum is None


# ===========================================================================
# Type-ref coercion (use sites)
# ===========================================================================


def test_type_ref_named_reference() -> None:
    ref = SchemaCoercer().type_ref({"$ref": "#/components/schemas/Pet"}, required=True)
    assert ref.name == "Pet" and ref.nullable is False and not ref.is_list()


def test_type_ref_scalar_required_vs_optional_nullability() -> None:
    required = SchemaCoercer().type_ref({"type": "string"}, required=True)
    optional = SchemaCoercer().type_ref({"type": "string"}, required=False)
    assert required.nullable is False
    assert optional.nullable is True


def test_type_ref_array_wraps_item() -> None:
    ref = SchemaCoercer().type_ref(
        {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}, required=True
    )
    assert ref.is_list() and ref.item is not None
    assert ref.item.name == "Pet"


def test_type_ref_openapi_30_nullable_flag() -> None:
    ref = SchemaCoercer().type_ref({"type": "string", "nullable": True}, required=True)
    assert ref.nullable is True


def test_type_ref_openapi_31_null_in_type_array() -> None:
    ref = SchemaCoercer().type_ref({"type": ["string", "null"]}, required=True)
    assert ref.name == "string" and ref.nullable is True


def test_type_ref_typeless_leaves_name_unset() -> None:
    ref = SchemaCoercer().type_ref({"oneOf": [{"type": "string"}]}, required=True)
    assert ref.name is None and not ref.is_list()


def test_ref_name_recovers_segment_for_foreign_ref() -> None:
    coercer = SchemaCoercer()
    assert coercer.ref_name("#/components/schemas/Pet") == "Pet"
    assert coercer.ref_name("other.yaml#/components/schemas/Tag") == "Tag"


# ===========================================================================
# Named-type coercion
# ===========================================================================


def test_named_type_record_with_required_fields() -> None:
    t = SchemaCoercer().named_type(
        "Pet",
        {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "nickname": {"type": "string"},
            },
        },
    )
    assert t.kind is TypeKind.RECORD
    by_name = {f.name: f for f in t.fields}
    assert by_name["id"].type.nullable is False
    assert by_name["id"].constraints is not None and by_name["id"].constraints.format == "uuid"
    assert by_name["nickname"].type.nullable is True


def test_named_type_enum() -> None:
    t = SchemaCoercer().named_type("Status", {"type": "string", "enum": ["a", "b"]})
    assert t.kind is TypeKind.ENUM
    assert [e.name for e in t.enum_values] == ["a", "b"]
    assert [e.key for e in t.enum_values] == ["Status.a", "Status.b"]


def test_named_type_union_from_oneof() -> None:
    t = SchemaCoercer().named_type(
        "PetOrTag",
        {"oneOf": [{"$ref": "#/components/schemas/Pet"}, {"$ref": "#/components/schemas/Tag"}]},
    )
    assert t.kind is TypeKind.UNION
    assert t.union_members == ["Pet", "Tag"]


def test_named_type_map_from_additional_properties() -> None:
    t = SchemaCoercer().named_type(
        "Labels", {"type": "object", "additionalProperties": {"type": "string"}}
    )
    assert t.kind is TypeKind.MAP
    assert t.key_type is not None and t.key_type.name == "string"
    assert t.value_type is not None and t.value_type.name == "string"


def test_named_type_alias_for_array() -> None:
    t = SchemaCoercer().named_type(
        "Tags", {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}}
    )
    assert t.kind is TypeKind.ALIAS
    assert t.aliased is not None and t.aliased.is_list()


def test_named_type_scalar_carries_constraints() -> None:
    t = SchemaCoercer().named_type("Uuid", {"type": "string", "format": "uuid", "pattern": "^x"})
    assert t.kind is TypeKind.SCALAR
    assert t.constraints is not None and t.constraints.format == "uuid"


def test_named_types_from_components_covers_all_entries() -> None:
    coercer = SchemaCoercer(
        components={
            "Pet": {"type": "object", "properties": {"id": {"type": "string"}}},
            "Status": {"type": "string", "enum": ["a"]},
        }
    )
    types = {t.key: t for t in coercer.named_types_from_components()}
    assert set(types) == {"Pet", "Status"}
    assert types["Pet"].kind is TypeKind.RECORD
    assert types["Status"].kind is TypeKind.ENUM


# ===========================================================================
# Ordering normalization
# ===========================================================================


def _unordered_api() -> CanonicalApi:
    """A model whose collections are deliberately out of key order."""
    svc = Service(
        key="pets",
        name="pets",
        operations=[
            Operation(
                key="POST /pets",
                name="b",
                kind=OperationKind.REQUEST_RESPONSE,
                parameters=[
                    Parameter(
                        key="POST /pets#query.b",
                        name="b",
                        location=ParameterLocation.QUERY,
                        type=TypeRef(name="string"),
                    ),
                    Parameter(
                        key="POST /pets#query.a",
                        name="a",
                        location=ParameterLocation.QUERY,
                        type=TypeRef(name="string"),
                    ),
                ],
                messages=[
                    Message(key="POST /pets#response.500", role=MessageRole.ERROR),
                    Message(key="POST /pets#response.200", role=MessageRole.RESPONSE),
                ],
            ),
            Operation(key="GET /pets", name="a", kind=OperationKind.REQUEST_RESPONSE),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="x"),
        services=[svc],
        channels=[Channel(key="z", address="z"), Channel(key="a", address="a")],
    )


def test_normalize_ordering_sorts_identity_keyed_collections() -> None:
    ordered = normalize_ordering(_unordered_api())
    ops = ordered.services[0].operations
    assert [o.key for o in ops] == ["GET /pets", "POST /pets"]
    post = ops[1]
    assert [p.key for p in post.parameters] == ["POST /pets#query.a", "POST /pets#query.b"]
    assert [m.key for m in post.messages] == ["POST /pets#response.200", "POST /pets#response.500"]
    assert [c.key for c in ordered.channels] == ["a", "z"]


def test_normalize_ordering_is_non_mutating_and_idempotent() -> None:
    api = _unordered_api()
    before = api.model_dump()
    ordered = normalize_ordering(api)
    assert api.model_dump() == before  # input untouched
    assert normalize_ordering(ordered).model_dump() == ordered.model_dump()  # stable
