"""Tests for the Apache Avro emitter — MFX-19.1 (#3909), subjects MFX-19.3 (#3911).

Exercises the acceptance criteria: canonical types emit **valid** ``.avsc`` schemas
(records, enums, unions, arrays, maps, fixed, logical types), nullability maps to
``["null", T]`` unions, names are sanitized to Avro rules, every schema passes
``fastavro.parse_schema``, per-type Schema Registry subjects are assigned, and
optional fields without source defaults receive evolution-compatible synthesized
defaults. Operations are omitted (types-only target).
"""

from __future__ import annotations

import json

import pytest

from app.avro_emitter import (
    AvroEmitOptions,
    AvroEmitter,
    AvroSubjectNamingStrategy,
    resolve_avro_subject,
    validate_avro_schema,
)
from app.emitter import LossKind, Provenance, get_emitter, load_builtin_emitters
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)


def _emit(api: CanonicalApi, *, opts: AvroEmitOptions | None = None):
    return AvroEmitter().emit(api, opts=opts)


def _schema_by_name(result, name: str) -> dict:
    match = next(f for f in result.files if f.path.endswith(f"/{name}.avsc") or f.path == f"{name}.avsc")
    content = match.content
    return content if isinstance(content, dict) else json.loads(content)


def _data_schema_api() -> CanonicalApi:
    """A rich data-schema model covering records, enums, unions, maps, and logical types."""
    suit = Type(
        key="com.example.Suit",
        name="Suit",
        kind=TypeKind.ENUM,
        namespace="com.example",
        enum_values=[
            EnumValue(key="com.example.Suit.SPADES", name="SPADES", value=0),
            EnumValue(key="com.example.Suit.HEARTS", name="HEARTS", value=1),
        ],
    )
    labels = Type(
        key="com.example.Labels",
        name="Labels",
        kind=TypeKind.MAP,
        namespace="com.example",
        value_type=TypeRef(name="string", nullable=False),
    )
    opt_string = Type(
        key="com.example.OptString",
        name="OptString",
        kind=TypeKind.UNION,
        namespace="com.example",
        union_members=["null", "string"],
    )
    md5 = Type(
        key="com.example.Md5",
        name="md5",
        kind=TypeKind.SCALAR,
        namespace="com.example",
        extras={"avro_type": "fixed", "avro_size": 16},
    )
    money = Type(
        key="com.example.Money",
        name="Money",
        kind=TypeKind.SCALAR,
        namespace="com.example",
        constraints=Constraints(format="decimal"),
        extras={"precision": 10, "scale": 2},
    )
    user = Type(
        key="com.example.User",
        name="User",
        kind=TypeKind.RECORD,
        namespace="com.example",
        description="A catalog user.",
        fields=[
            CanonicalField(
                key="com.example.User.id",
                name="id",
                type=TypeRef(name="string", nullable=False),
            ),
            CanonicalField(
                key="com.example.User.email",
                name="email",
                type=TypeRef(name="string", nullable=True),
                default=None,
                extras={"has_default": True},
            ),
            CanonicalField(
                key="com.example.User.age",
                name="age",
                type=TypeRef(name="integer", nullable=True),
                default=0,
            ),
            CanonicalField(
                key="com.example.User.born",
                name="born",
                type=TypeRef(name="string", nullable=False),
                constraints=Constraints(format="date"),
            ),
            CanonicalField(
                key="com.example.User.updated",
                name="updated",
                type=TypeRef(name="string", nullable=False),
                constraints=Constraints(format="date-time"),
            ),
            CanonicalField(
                key="com.example.User.token",
                name="token",
                type=TypeRef(name="string", nullable=False),
                constraints=Constraints(format="uuid"),
            ),
            CanonicalField(
                key="com.example.User.suit",
                name="suit",
                type=TypeRef(name="com.example.Suit", nullable=False),
            ),
            CanonicalField(
                key="com.example.User.tags",
                name="tags",
                type=TypeRef(item=TypeRef(name="string", nullable=False), nullable=False),
            ),
            CanonicalField(
                key="com.example.User.labels",
                name="labels",
                type=TypeRef(name="com.example.Labels", nullable=False),
            ),
            CanonicalField(
                key="com.example.User.nick",
                name="nick",
                type=TypeRef(name="com.example.OptString", nullable=False),
            ),
            CanonicalField(
                key="com.example.User.digest",
                name="digest",
                type=TypeRef(name="com.example.Md5", nullable=False),
            ),
            CanonicalField(
                key="com.example.User.balance",
                name="balance",
                type=TypeRef(name="com.example.Money", nullable=True),
            ),
            CanonicalField(
                key="com.example.User.bad-name",
                name="bad-name",
                type=TypeRef(name="string", nullable=False),
            ),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="Users", namespace="com.example"),
        types=[suit, labels, opt_string, md5, money, user],
    )


# ---------------------------------------------------------------------------
# Registry + descriptor
# ---------------------------------------------------------------------------


def test_avro_emitter_is_registered() -> None:
    load_builtin_emitters()
    from app.avro_emitter import AvroEmitter as Registered

    assert get_emitter("avro") is Registered


def test_avro_descriptor_and_capability_profile() -> None:
    descriptor = AvroEmitter.descriptor()
    assert descriptor.key == "avro"
    assert descriptor.format == "avro"
    assert descriptor.multi_file is True
    profile = AvroEmitter.capability_profile()
    assert profile.operations is False
    assert profile.events is False
    assert profile.unions is True
    assert profile.nullability is True
    assert profile.constraints is False


# ---------------------------------------------------------------------------
# Acceptance: valid .avsc for the type set
# ---------------------------------------------------------------------------


def test_emits_valid_avsc_for_each_type() -> None:
    result = _emit(_data_schema_api())
    assert len(result.files) == 6
    # render() already validates every schema with a shared named-schema registry.
    assert all(emitted.content for emitted in result.files)


def test_record_fields_logical_types_and_nullability() -> None:
    schema = _schema_by_name(_emit(_data_schema_api()), "User")
    fields = {f["name"]: f for f in schema["fields"]}

    assert schema == {
        "type": "record",
        "name": "User",
        "namespace": "com.example",
        "doc": "A catalog user.",
        "fields": schema["fields"],
    }
    assert fields["id"]["type"] == "string"
    assert fields["email"]["type"] == ["null", "string"]
    assert fields["email"]["default"] is None
    assert fields["age"]["type"] == ["null", "int"]
    assert fields["age"]["default"] == 0
    assert fields["born"]["type"] == {"type": "int", "logicalType": "date"}
    assert fields["updated"]["type"] == {"type": "long", "logicalType": "timestamp-millis"}
    assert fields["token"]["type"] == {"type": "string", "logicalType": "uuid"}
    assert fields["suit"]["type"] == "Suit"
    assert fields["tags"]["type"] == {"type": "array", "items": "string"}
    assert fields["labels"]["type"] == {"type": "map", "values": "string"}
    assert fields["nick"]["type"] == ["null", "string"]
    assert fields["digest"]["type"] == "md5"
    assert fields["balance"]["type"] == [
        "null",
        {"type": "bytes", "logicalType": "decimal", "precision": 10, "scale": 2},
    ]
    assert fields["balance"]["default"] is None
    assert fields["bad_name"]["type"] == "string"


def test_enum_symbols_are_sanitized_and_ordered() -> None:
    schema = _schema_by_name(_emit(_data_schema_api()), "Suit")
    assert schema["symbols"] == ["SPADES", "HEARTS"]


def test_union_type_emits_as_array_schema() -> None:
    result = _emit(_data_schema_api())
    union_file = next(f for f in result.files if f.path.endswith("OptString.avsc"))
    assert union_file.content == ["null", "string"]


def test_namespace_override_applies_to_paths_and_named_refs() -> None:
    suit = Type(
        key="com.example.Suit",
        name="Suit",
        kind=TypeKind.ENUM,
        enum_values=[EnumValue(key="com.example.Suit.SPADES", name="SPADES", value=0)],
    )
    user = Type(
        key="com.example.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="com.example.User.suit",
                name="suit",
                type=TypeRef(name="com.example.Suit", nullable=False),
            )
        ],
    )
    result = _emit(
        CanonicalApi(
            paradigm=ApiParadigm.DATA_SCHEMA,
            format="avro",
            identity=ApiIdentity(name="Users", namespace="com.example"),
            types=[suit, user],
        ),
        opts=AvroEmitOptions(namespace="io.override"),
    )

    assert [emitted.path for emitted in result.files] == [
        "io/override/Suit.avsc",
        "io/override/User.avsc",
    ]
    assert _schema_by_name(result, "Suit")["namespace"] == "io.override"
    assert _schema_by_name(result, "User")["namespace"] == "io.override"
    assert _schema_by_name(result, "User")["fields"][0]["type"] == "Suit"


def test_fixed_scalar_emits_named_fixed_type() -> None:
    schema = _schema_by_name(_emit(_data_schema_api()), "md5")
    assert schema == {
        "type": "fixed",
        "name": "md5",
        "namespace": "com.example",
        "size": 16,
    }


def test_operations_are_omitted() -> None:
    api = _data_schema_api()
    api.services = [
        Service(
            key="default",
            name="default",
            operations=[
                Operation(
                    key="getUser",
                    name="getUser",
                    kind=OperationKind.REQUEST_RESPONSE,
                )
            ],
        )
    ]
    result = _emit(api)
    assert len(result.files) == 6
    assert all(loss.subject == "evolution-default" for loss in result.losses)


def test_emission_is_deterministic() -> None:
    api = _data_schema_api()
    first = _emit(api)
    second = _emit(api)
    assert first.model_dump() == second.model_dump()


def test_provenance_records_each_schema() -> None:
    result = _emit(_data_schema_api())
    pointers = {record.pointer for record in result.provenance}
    assert "/schemas/com.example.User" in pointers
    assert any(record.provenance is Provenance.SOURCE for record in result.provenance)
    assert any(record.provenance is Provenance.DEFAULT for record in result.provenance)


def test_falsy_defaults_are_preserved() -> None:
    rec = Type(
        key="com.example.Rec",
        name="Rec",
        kind=TypeKind.RECORD,
        namespace="com.example",
        fields=[
            CanonicalField(
                key="com.example.Rec.flag",
                name="flag",
                type=TypeRef(name="boolean", nullable=True),
                default=False,
            ),
            CanonicalField(
                key="com.example.Rec.count",
                name="count",
                type=TypeRef(name="integer", nullable=True),
                default=0,
            ),
        ],
    )
    schema = _schema_by_name(
        _emit(
            CanonicalApi(
                paradigm=ApiParadigm.DATA_SCHEMA,
                format="avro",
                identity=ApiIdentity(name="x"),
                types=[rec],
            )
        ),
        "Rec",
    )
    fields = {f["name"]: f for f in schema["fields"]}
    assert fields["flag"]["default"] is False
    assert fields["count"]["default"] == 0


def test_validate_avro_schema_rejects_invalid_schema() -> None:
    with pytest.raises(ValueError, match="Invalid Avro schema"):
        validate_avro_schema({"type": "not-a-real-avro-type"})


# ---------------------------------------------------------------------------
# MFX-19.3 — Schema Registry subjects, naming strategy, evolution defaults
# ---------------------------------------------------------------------------


def test_each_emitted_file_has_record_name_subject() -> None:
    """Default ``record_name`` strategy assigns one ``{qualifiedName}-value`` subject per type."""
    result = _emit(_data_schema_api())
    subjects = {emitted.subject for emitted in result.files}
    assert subjects == {
        "com.example.Suit-value",
        "com.example.Labels-value",
        "com.example.OptString-value",
        "com.example.md5-value",
        "com.example.Money-value",
        "com.example.User-value",
    }


def test_topic_record_name_subject_strategy() -> None:
    result = _emit(
        _data_schema_api(),
        opts=AvroEmitOptions(
            subject_naming=AvroSubjectNamingStrategy.TOPIC_RECORD_NAME,
            topic="users",
        ),
    )
    assert {emitted.subject for emitted in result.files} == {
        "users-com.example.Suit-value",
        "users-com.example.Labels-value",
        "users-com.example.OptString-value",
        "users-com.example.md5-value",
        "users-com.example.Money-value",
        "users-com.example.User-value",
    }


def test_topic_name_subject_strategy_uses_single_topic_subject() -> None:
    result = _emit(
        _data_schema_api(),
        opts=AvroEmitOptions(
            subject_naming=AvroSubjectNamingStrategy.TOPIC_NAME,
            topic="users",
        ),
    )
    assert {emitted.subject for emitted in result.files} == {"users-value"}


def test_subject_role_key_suffix() -> None:
    result = _emit(
        _data_schema_api(),
        opts=AvroEmitOptions(subject_role="key"),
    )
    assert all(emitted.subject.endswith("-key") for emitted in result.files)
    assert "com.example.Suit-key" in {emitted.subject for emitted in result.files}


def test_topic_strategies_require_topic() -> None:
    with pytest.raises(ValueError, match="topic is required"):
        AvroEmitOptions(subject_naming=AvroSubjectNamingStrategy.TOPIC_NAME)


def test_resolve_avro_subject_is_deterministic() -> None:
    api = _data_schema_api()
    user = next(t for t in api.types if t.name == "User")
    opts = AvroEmitOptions()
    assert resolve_avro_subject(user, opts, "com.example") == "com.example.User-value"
    assert (
        resolve_avro_subject(
            user,
            AvroEmitOptions(
                subject_naming=AvroSubjectNamingStrategy.TOPIC_RECORD_NAME,
                topic="events",
            ),
            "com.example",
        )
        == "events-com.example.User-value"
    )


def test_synthesized_evolution_defaults_on_nullable_fields_without_source_default() -> None:
    """Nullable fields without an explicit source default get ``default: null`` for evolution."""
    rec = Type(
        key="com.example.Rec",
        name="Rec",
        kind=TypeKind.RECORD,
        namespace="com.example",
        fields=[
            CanonicalField(
                key="com.example.Rec.note",
                name="note",
                type=TypeRef(name="string", nullable=True),
            ),
            CanonicalField(
                key="com.example.Rec.balance",
                name="balance",
                type=TypeRef(name="com.example.Money", nullable=True),
            ),
        ],
    )
    money = Type(
        key="com.example.Money",
        name="Money",
        kind=TypeKind.SCALAR,
        namespace="com.example",
        constraints=Constraints(format="decimal"),
        extras={"precision": 10, "scale": 2},
    )
    result = _emit(
        CanonicalApi(
            paradigm=ApiParadigm.DATA_SCHEMA,
            format="avro",
            identity=ApiIdentity(name="x", namespace="com.example"),
            types=[money, rec],
        )
    )
    schema = _schema_by_name(result, "Rec")
    fields = {f["name"]: f for f in schema["fields"]}
    assert fields["note"]["default"] is None
    assert fields["balance"]["default"] is None

    synth = [loss for loss in result.losses if loss.subject == "evolution-default"]
    assert len(synth) == 2
    assert all(loss.kind is LossKind.INFERRED for loss in synth)
    assert any(record.provenance is Provenance.DEFAULT for record in result.provenance)
