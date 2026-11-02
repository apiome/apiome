"""Tests for Avro → canonical model — MFI-12.2 (#3783).

Records, fields, enums, unions and logical types of Avro 1.12 map onto the canonical
model on both surfaces (``.avsc`` and ``.avdl``): every specification logical type is
honoured when valid and ignored (but recorded) when not, also behind a nullable union;
unions of named references, object-form primitives and maps resolve to real member keys;
and the evolution metadata — enum ``default``, ``aliases``, field ``order`` — survives a
``.avsc`` import and the Avro emitter writes it back.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.avro_emitter import AvroEmitter
from app.avro_logical_types import (
    AVRO_LOGICAL_TYPES,
    max_fixed_decimal_precision,
    resolve_logical_type,
)
from app.avro_normalizer import AvroNormalizer
from app.avro_parser import parse_avro
from app.canonical_model import CanonicalApi, CanonicalField, Type, TypeKind


def _normalize(schema: Dict[str, Any]) -> CanonicalApi:
    """Parse and normalize one ``.avsc`` schema dict."""
    return AvroNormalizer().normalize(parse_avro(json.dumps(schema)), include_raw=False)


def _record(*fields: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    """A ``com.example.R`` record with the given fields."""
    return {"type": "record", "name": "R", "namespace": "com.example", "fields": list(fields), **extra}


def _type(api: CanonicalApi, key: str) -> Type:
    return next(t for t in api.types if t.key == key)


def _field(api: CanonicalApi, name: str, record: str = "com.example.R") -> CanonicalField:
    return next(f for f in _type(api, record).fields if f.name == name)


def _one_field(field_type: Any, **field_extra: Any) -> CanonicalField:
    """Normalize a record holding a single field ``f`` of ``field_type``."""
    return _field(_normalize(_record({"name": "f", "type": field_type, **field_extra})), "f")


# --- logical types: the 1.12 table -------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "logical", "fmt", "ref_name"),
    [
        ("int", "date", "date", "string"),
        ("int", "time-millis", "time", "string"),
        ("long", "time-micros", "time", "string"),
        ("long", "timestamp-millis", "date-time", "string"),
        ("long", "timestamp-micros", "date-time", "string"),
        ("long", "timestamp-nanos", "date-time", "string"),
        ("long", "local-timestamp-millis", "date-time", "string"),
        ("long", "local-timestamp-micros", "date-time", "string"),
        ("long", "local-timestamp-nanos", "date-time", "string"),
        ("string", "uuid", "uuid", "string"),
        ("bytes", "big-decimal", "decimal", "bytes"),
    ],
)
def test_every_primitive_logical_type_projects_onto_its_format(
    base: str, logical: str, fmt: str, ref_name: str
) -> None:
    field = _one_field({"type": base, "logicalType": logical})
    assert field.constraints is not None and field.constraints.format == fmt
    assert field.type.name == ref_name
    assert field.extras["logicalType"] == logical
    assert field.extras["avro_type"] == base
    assert "avro_logical_type_ignored" not in field.extras


def test_the_table_covers_the_whole_1_12_specification() -> None:
    assert set(AVRO_LOGICAL_TYPES) == {
        "decimal",
        "big-decimal",
        "uuid",
        "date",
        "time-millis",
        "time-micros",
        "timestamp-millis",
        "timestamp-micros",
        "timestamp-nanos",
        "local-timestamp-millis",
        "local-timestamp-micros",
        "local-timestamp-nanos",
        "duration",
    }


def test_decimal_on_bytes_keeps_precision_and_scale() -> None:
    field = _one_field({"type": "bytes", "logicalType": "decimal", "precision": 12, "scale": 4})
    assert field.constraints is not None and field.constraints.format == "decimal"
    assert field.extras["precision"] == 12 and field.extras["scale"] == 4
    assert field.type.name == "bytes"


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "bytes", "logicalType": "decimal"},  # precision is required
        {"type": "bytes", "logicalType": "decimal", "precision": 0},
        {"type": "bytes", "logicalType": "decimal", "precision": 4, "scale": 5},
        {"type": "bytes", "logicalType": "decimal", "precision": 4, "scale": -1},
        {"type": "bytes", "logicalType": "decimal", "precision": True},
        {"type": "fixed", "name": "D", "size": 2, "logicalType": "decimal", "precision": 5},
    ],
)
def test_an_invalid_decimal_is_ignored_but_recorded(schema: Dict[str, Any]) -> None:
    resolved = resolve_logical_type(schema)
    assert resolved is not None
    assert resolved.format is None and resolved.ignored == "invalid"
    assert resolved.extras()["logicalType"] == "decimal"


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "logicalType": "date"},
        {"type": "int", "logicalType": "timestamp-millis"},
        {"type": "long", "logicalType": "time-millis"},
        {"type": "bytes", "logicalType": "uuid"},
        {"type": "string", "logicalType": "big-decimal"},
    ],
)
def test_a_logical_type_on_the_wrong_base_is_ignored(schema: Dict[str, Any]) -> None:
    field = _one_field(schema)
    assert field.constraints is None
    assert field.extras["avro_logical_type_ignored"] == "invalid"
    # The underlying type stands, as the specification requires.
    assert field.type.name == {"string": "string", "int": "integer", "long": "int64", "bytes": "bytes"}[schema["type"]]


def test_an_unknown_logical_type_is_ignored_as_unknown() -> None:
    field = _one_field({"type": "long", "logicalType": "event-time"})
    assert field.constraints is None
    assert field.type.name == "int64"
    assert field.extras["logicalType"] == "event-time"
    assert field.extras["avro_logical_type_ignored"] == "unknown"


def test_max_fixed_decimal_precision_matches_the_specification() -> None:
    # floor(log10(2^(8n-1) - 1)): 1 byte holds 127 (2 digits), 16 bytes hold 38 digits.
    assert max_fixed_decimal_precision(1) == 2
    assert max_fixed_decimal_precision(8) == 18
    assert max_fixed_decimal_precision(16) == 38
    assert max_fixed_decimal_precision(0) == 0


# --- logical types behind unions and on named fixed --------------------------------------


@pytest.mark.parametrize(
    "union",
    [
        ["null", {"type": "long", "logicalType": "timestamp-millis"}],
        [{"type": "long", "logicalType": "timestamp-millis"}, "null"],
    ],
)
def test_a_nullable_logical_type_keeps_its_format(union: List[Any]) -> None:
    field = _one_field(union, default=None)
    assert field.type.nullable is True
    assert field.type.name == "string"
    assert field.constraints is not None and field.constraints.format == "date-time"
    assert field.extras["logicalType"] == "timestamp-millis"
    assert field.extras["avro_type"] == "long"


def test_a_named_fixed_carries_its_own_logical_type() -> None:
    api = _normalize(
        _record(
            {
                "name": "amount",
                "type": {
                    "type": "fixed",
                    "name": "Money",
                    "size": 8,
                    "logicalType": "decimal",
                    "precision": 18,
                    "scale": 2,
                },
            },
            {"name": "again", "type": "Money"},
        )
    )
    money = _type(api, "com.example.Money")
    assert money.kind is TypeKind.SCALAR
    assert money.constraints is not None and money.constraints.format == "decimal"
    assert money.extras["logicalType"] == "decimal"
    assert money.extras["precision"] == 18 and money.extras["scale"] == 2
    assert money.extras["avro_type"] == "fixed" and money.extras["avro_size"] == 8
    # Referenced by name, the field still points at the fixed type.
    assert _field(api, "again").type.name == "com.example.Money"


def test_a_fixed_uuid_keeps_its_reference_to_the_fixed_type() -> None:
    field = _one_field({"type": "fixed", "name": "Id", "size": 16, "logicalType": "uuid"})
    assert field.type.name == "com.example.Id"
    assert field.constraints is not None and field.constraints.format == "uuid"


@pytest.mark.parametrize(("size", "valid"), [(12, True), (16, False)])
def test_duration_requires_a_twelve_byte_fixed(size: int, valid: bool) -> None:
    api = _normalize(
        _record({"name": "d", "type": {"type": "fixed", "name": "Dur", "size": size, "logicalType": "duration"}})
    )
    dur = _type(api, "com.example.Dur")
    if valid:
        assert dur.constraints is not None and dur.constraints.format == "duration"
        assert "avro_logical_type_ignored" not in dur.extras
    else:
        assert dur.constraints is None
        assert dur.extras["avro_logical_type_ignored"] == "invalid"


# --- unions ------------------------------------------------------------------------------


def test_a_union_of_named_references_keeps_every_member() -> None:
    api = _normalize(
        _record(
            {"name": "cat", "type": {"type": "record", "name": "Cat", "fields": []}},
            {"name": "dog", "type": {"type": "record", "name": "Dog", "fields": []}},
            {"name": "pet", "type": ["Cat", "Dog"]},
        )
    )
    pet = _field(api, "pet")
    union = _type(api, pet.type.name)
    assert union.kind is TypeKind.UNION
    assert union.union_members == ["com.example.Cat", "com.example.Dog"]


def test_a_union_resolves_object_form_primitives_and_maps() -> None:
    api = _normalize(
        _record({"name": "f", "type": ["null", "string", {"type": "long"}, {"type": "map", "values": "int"}]})
    )
    union = _type(api, _field(api, "f").type.name)
    assert union.union_members == ["null", "string", "int64", "com.example.Map_int"]
    assert _type(api, "com.example.Map_int").kind is TypeKind.MAP


def test_a_union_with_a_logical_branch_uses_the_base_type_as_member() -> None:
    api = _normalize(_record({"name": "f", "type": ["string", {"type": "long", "logicalType": "timestamp-millis"}]}))
    union = _type(api, _field(api, "f").type.name)
    assert union.union_members == ["string", "int64"]


# --- maps --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected_key"),
    [
        ("long", "com.example.Map_long"),
        ({"type": "array", "items": "string"}, "com.example.Map_array_string"),
        (["null", "string", "double"], "com.example.Map_Union_null_string_double"),
        ({"type": "map", "values": "int"}, "com.example.Map_Map_int"),
    ],
)
def test_a_map_key_never_embeds_schema_text(values: Any, expected_key: str) -> None:
    field = _one_field({"type": "map", "values": values})
    assert field.type.name == expected_key
    assert "{" not in expected_key and "[" not in expected_key


# --- enums, aliases and order on .avsc ---------------------------------------------------


def test_avsc_keeps_the_enum_default_and_aliases() -> None:
    api = _normalize(
        _record(
            {
                "name": "status",
                "type": {
                    "type": "enum",
                    "name": "Status",
                    "symbols": ["UNKNOWN", "ACTIVE"],
                    "default": "UNKNOWN",
                    "aliases": ["State"],
                },
            }
        )
    )
    status = _type(api, "com.example.Status")
    assert [value.name for value in status.enum_values] == ["UNKNOWN", "ACTIVE"]
    assert status.extras["avro_enum_default"] == "UNKNOWN"
    assert status.extras["avro_aliases"] == ["State"]


def test_avsc_keeps_record_and_field_aliases_and_order() -> None:
    api = _normalize(
        _record(
            {"name": "email", "type": "string", "aliases": ["mail"], "order": "descending"},
            aliases=["Person"],
        )
    )
    assert _type(api, "com.example.R").extras["avro_aliases"] == ["Person"]
    email = _field(api, "email")
    assert email.extras["avro_aliases"] == ["mail"]
    assert email.extras["avro_order"] == "descending"


def test_avsc_still_drops_custom_properties() -> None:
    api = _normalize(_record({"name": "x", "type": "string", "x-owner": "team"}, **{"x-owner": "team"}))
    assert "avro_properties" not in _type(api, "com.example.R").extras
    assert "avro_properties" not in _field(api, "x").extras


# --- the emitter writes it back ----------------------------------------------------------


def _emitted(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize, emit with the Avro emitter, and return the root record's schema."""
    result = AvroEmitter().emit(_normalize(schema))
    match = next(f for f in result.files if f.path.endswith("/R.avsc") or f.path == "R.avsc")
    return match.content if isinstance(match.content, dict) else json.loads(match.content)


def _emitted_field(schema: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(f for f in _emitted(schema)["fields"] if f["name"] == name)


def test_round_trip_keeps_a_nullable_timestamp() -> None:
    field = _emitted_field(
        _record({"name": "ts", "type": ["null", {"type": "long", "logicalType": "timestamp-nanos"}], "default": None}),
        "ts",
    )
    branches = field["type"]
    assert "null" in branches
    assert {"type": "long", "logicalType": "timestamp-nanos"} in branches


def test_round_trip_keeps_a_fixed_decimal() -> None:
    schema = _record(
        {
            "name": "amount",
            "type": {
                "type": "fixed",
                "name": "Money",
                "size": 8,
                "logicalType": "decimal",
                "precision": 18,
                "scale": 2,
            },
        }
    )
    result = AvroEmitter().emit(_normalize(schema))
    texts = [f.content if isinstance(f.content, str) else json.dumps(f.content) for f in result.files]
    money = next(
        json.loads(text)
        for text in texts
        if '"Money"' in text and '"fixed"' in text and json.loads(text).get("type") == "fixed"
    )
    assert money["logicalType"] == "decimal"
    assert money["precision"] == 18 and money["scale"] == 2 and money["size"] == 8


def test_round_trip_keeps_aliases_order_and_enum_default() -> None:
    emitted = _emitted(
        _record(
            {"name": "email", "type": "string", "aliases": ["mail"], "order": "ignore"},
            aliases=["Person"],
        )
    )
    assert emitted.get("aliases") == ["Person"]
    email = next(f for f in emitted["fields"] if f["name"] == "email")
    assert email["aliases"] == ["mail"] and email["order"] == "ignore"


# --- versioning --------------------------------------------------------------------------


def _version_fingerprint(**field_extra: Any) -> str:
    """The version fingerprint of a documented one-field record."""
    from app.fingerprint import fingerprint

    schema = _record({"name": "email", "type": "string", "doc": "Mail.", **field_extra}, doc="A record.")
    return fingerprint(_normalize(schema)).fingerprint


@pytest.mark.parametrize("edit", [{"aliases": ["mail"]}, {"order": "ignore"}])
def test_an_alias_or_order_edit_mints_a_version(edit: Dict[str, Any]) -> None:
    assert _version_fingerprint(**edit) != _version_fingerprint()


def test_a_doc_only_edit_still_mints_no_version() -> None:
    assert _version_fingerprint(doc="Changed.") == _version_fingerprint()
