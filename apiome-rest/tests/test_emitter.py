"""Unit tests for the emitter SPI — MFI-22.1 (#4002).

Covers the format registry, the provenance primitives, the result envelope, and
the :class:`~app.emitter.SchemaEmitter` (the inverse of the normalizer's
:class:`~app.normalizer.SchemaCoercer`) in isolation. The end-to-end OpenAPI
emission is exercised in ``test_openapi_emitter.py``.
"""

import pytest

from app.canonical_model import (
    ApiParadigm,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import (
    EmitResult,
    Emitter,
    Provenance,
    ProvenanceRecord,
    ProvenanceTracker,
    SchemaEmitter,
    _emit_constraints,
    available_emit_formats,
    get_emitter,
    register_emitter,
)

# --- registry ---------------------------------------------------------------


def test_openapi_emitter_is_registered() -> None:
    # Importing the emitter module self-registers it under its format key.
    import app.openapi_emitter  # noqa: F401
    from app.openapi_emitter import OpenApiEmitter

    assert get_emitter("openapi-3.1") is OpenApiEmitter
    assert "openapi-3.1" in available_emit_formats()


def test_register_rejects_empty_format() -> None:
    class NoFormatEmitter(Emitter):
        paradigm = ApiParadigm.REST

        def emit(self, api):  # pragma: no cover - never called
            return EmitResult(document={})

    with pytest.raises(ValueError, match="non-empty"):
        register_emitter(NoFormatEmitter)


def test_register_is_idempotent_but_rejects_conflicts() -> None:
    class DummyEmitter(Emitter):
        format = "dummy-emit-test"
        paradigm = ApiParadigm.REST

        def emit(self, api):  # pragma: no cover - never called
            return EmitResult(document={})

    assert register_emitter(DummyEmitter) is DummyEmitter
    assert get_emitter("dummy-emit-test") is DummyEmitter
    # Re-registering the same class is a no-op.
    assert register_emitter(DummyEmitter) is DummyEmitter

    class OtherEmitter(Emitter):
        format = "dummy-emit-test"
        paradigm = ApiParadigm.REST

        def emit(self, api):  # pragma: no cover - never called
            return EmitResult(document={})

    with pytest.raises(ValueError, match="already registered"):
        register_emitter(OtherEmitter)


def test_get_emitter_unknown_is_none() -> None:
    assert get_emitter("no-such-format") is None


# --- provenance -------------------------------------------------------------


def test_provenance_values() -> None:
    assert Provenance.SOURCE.value == "source"
    assert Provenance.INFERRED.value == "inferred"
    assert Provenance.DEFAULT.value == "default"


def test_pointer_escaping_follows_rfc6901() -> None:
    assert ProvenanceTracker.escape("a/b") == "a~1b"
    assert ProvenanceTracker.escape("a~b") == "a~0b"
    # `~` must be escaped before `/` so `~1` is not re-escaped.
    assert ProvenanceTracker.escape("~/") == "~0~1"
    assert ProvenanceTracker.child("/paths", "/pets/{id}", "get") == "/paths/~1pets~1{id}/get"


def test_tracker_records_sorted_by_pointer() -> None:
    tracker = ProvenanceTracker()
    tracker.record("/b", Provenance.SOURCE)
    tracker.record("/a", Provenance.INFERRED, "why")
    tracker.record("/c", Provenance.DEFAULT)
    records = tracker.records()
    assert [r.pointer for r in records] == ["/a", "/b", "/c"]
    assert records[0].provenance is Provenance.INFERRED
    assert records[0].detail == "why"


def test_emit_result_is_serializable() -> None:
    result = EmitResult(
        document={"openapi": "3.1.0"},
        provenance=[ProvenanceRecord(pointer="/openapi", provenance=Provenance.DEFAULT)],
    )
    reloaded = EmitResult.model_validate(result.model_dump())
    assert reloaded == result


# --- constraints ------------------------------------------------------------


def test_emit_constraints_none_and_empty() -> None:
    assert _emit_constraints(None) == {}
    assert _emit_constraints(Constraints()) == {}


def test_emit_constraints_maps_every_facet() -> None:
    constraints = Constraints(
        minimum=0,
        maximum=10,
        exclusive_minimum=1,
        exclusive_maximum=9,
        multiple_of=2,
        min_length=1,
        max_length=5,
        pattern="^x$",
        min_items=1,
        max_items=3,
        unique_items=True,
        enum=["a", "b"],
        format="uuid",
    )
    emitted = _emit_constraints(constraints)
    assert emitted == {
        "minimum": 0,
        "maximum": 10,
        "exclusiveMinimum": 1,
        "exclusiveMaximum": 9,
        "multipleOf": 2,
        "minLength": 1,
        "maxLength": 5,
        "pattern": "^x$",
        "minItems": 1,
        "maxItems": 3,
        "uniqueItems": True,
        "enum": ["a", "b"],
        "format": "uuid",
    }


# --- SchemaEmitter.type_ref -------------------------------------------------


def test_type_ref_primitive_and_typeless() -> None:
    emitter = SchemaEmitter()
    assert emitter.type_ref(TypeRef(name="string")) == {"type": "string"}
    # A typeless reference is any-schema.
    assert emitter.type_ref(TypeRef()) == {}


def test_type_ref_named_reference() -> None:
    emitter = SchemaEmitter()
    assert emitter.type_ref(TypeRef(name="Pet")) == {"$ref": "#/components/schemas/Pet"}
    # Optionality (nullable) is not rendered as a `"null"` type on a reference.
    assert emitter.type_ref(TypeRef(name="Pet", nullable=True)) == {
        "$ref": "#/components/schemas/Pet"
    }


def test_type_ref_nested_list() -> None:
    emitter = SchemaEmitter()
    ref = TypeRef(item=TypeRef(item=TypeRef(name="string")))
    assert emitter.type_ref(ref) == {
        "type": "array",
        "items": {"type": "array", "items": {"type": "string"}},
    }


def test_type_ref_custom_prefix() -> None:
    emitter = SchemaEmitter(ref_prefix="#/$defs/")
    assert emitter.type_ref(TypeRef(name="Pet")) == {"$ref": "#/$defs/Pet"}


# --- SchemaEmitter.named_schema ---------------------------------------------


def _record_type() -> Type:
    return Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        description="A pet",
        fields=[
            CanonicalField(
                key="Pet.id", name="id", type=TypeRef(name="string", nullable=False)
            ),
            CanonicalField(
                key="Pet.nick",
                name="nick",
                type=TypeRef(name="string", nullable=True),
                description="nickname",
                default="rex",
            ),
            CanonicalField(
                key="Pet.owner", name="owner", type=TypeRef(name="Owner", nullable=True)
            ),
        ],
    )


def test_named_schema_record_required_from_non_nullable() -> None:
    schema = SchemaEmitter().named_schema(_record_type())
    assert schema["type"] == "object"
    assert schema["required"] == ["id"]  # only the non-nullable field
    assert schema["description"] == "A pet"
    # Optional scalar keeps its facets; optional reference stays a bare $ref.
    assert schema["properties"]["nick"] == {
        "type": "string",
        "default": "rex",
        "description": "nickname",
    }
    assert schema["properties"]["owner"] == {"$ref": "#/components/schemas/Owner"}


def test_named_schema_record_without_required_omits_key() -> None:
    type_ = Type(
        key="T",
        name="T",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="T.a", name="a", type=TypeRef(name="string", nullable=True))
        ],
    )
    schema = SchemaEmitter().named_schema(type_)
    assert "required" not in schema


def test_named_schema_enum_infers_scalar_type() -> None:
    string_enum = Type(
        key="Status",
        name="Status",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Status.A", name="A", value="A"),
            EnumValue(key="Status.B", name="B", value="B"),
        ],
    )
    assert SchemaEmitter().named_schema(string_enum) == {
        "type": "string",
        "enum": ["A", "B"],
    }
    int_enum = Type(
        key="Code",
        name="Code",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Code.1", name="ONE", value=1),
            EnumValue(key="Code.2", name="TWO", value=2),
        ],
    )
    assert SchemaEmitter().named_schema(int_enum) == {"type": "integer", "enum": [1, 2]}


def test_named_schema_enum_falls_back_to_name_and_untyped_when_mixed() -> None:
    mixed = Type(
        key="M",
        name="M",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="M.A", name="A", value="A"),
            EnumValue(key="M.1", name="ONE", value=1),
        ],
    )
    schema = SchemaEmitter().named_schema(mixed)
    assert schema == {"enum": ["A", 1]}  # mixed types → untyped enum
    # A value-less enum member falls back to its name.
    named_only = Type(
        key="N",
        name="N",
        kind=TypeKind.ENUM,
        enum_values=[EnumValue(key="N.X", name="X")],
    )
    assert SchemaEmitter().named_schema(named_only) == {"type": "string", "enum": ["X"]}


def test_named_schema_union() -> None:
    union = Type(
        key="Result",
        name="Result",
        kind=TypeKind.UNION,
        union_members=["Ok", "Err"],
    )
    assert SchemaEmitter().named_schema(union) == {
        "oneOf": [
            {"$ref": "#/components/schemas/Ok"},
            {"$ref": "#/components/schemas/Err"},
        ]
    }


def test_named_schema_map() -> None:
    map_type = Type(
        key="Meta",
        name="Meta",
        kind=TypeKind.MAP,
        key_type=TypeRef(name="string", nullable=False),
        value_type=TypeRef(name="string", nullable=False),
    )
    assert SchemaEmitter().named_schema(map_type) == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }


def test_named_schema_alias_and_scalar() -> None:
    alias = Type(
        key="Tags",
        name="Tags",
        kind=TypeKind.ALIAS,
        aliased=TypeRef(item=TypeRef(name="string", nullable=False)),
    )
    assert SchemaEmitter().named_schema(alias) == {
        "type": "array",
        "items": {"type": "string"},
    }
    scalar = Type(
        key="Email",
        name="Email",
        kind=TypeKind.SCALAR,
        deprecated=True,
        constraints=Constraints(format="email", pattern="@"),
    )
    assert SchemaEmitter().named_schema(scalar) == {
        "format": "email",
        "pattern": "@",
        "deprecated": True,
    }
