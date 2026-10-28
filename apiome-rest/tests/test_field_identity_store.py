"""Tests for persisted export field identities — MFX-12.2 (#3880), MFX-25.2 (#4152)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Type,
    TypeKind,
    TypeRef,
)
from app.export_service import ExportPersistenceContext, emit_canonical
from app.fidelity_engine import compute_lossiness
from app.field_identity_store import (
    FieldNumberAllocator,
    field_number_in_reserved,
    load_persisted_field_numbers,
    persist_field_number_assignments,
)
from app.lossiness import LossinessKind
from app.proto_emitter import ProtoEmitOptions, ProtoEmitter
from app.thrift_emitter import ThriftEmitOptions, ThriftEmitter
from app.thrift_parser import parse_thrift


def _user_type(*, extra_field: bool = False) -> Type:
    fields = [
        CanonicalField(key="p.User.id", name="id", type=TypeRef(name="string")),
        CanonicalField(key="p.User.name", name="name", type=TypeRef(name="string")),
    ]
    if extra_field:
        fields.append(
            CanonicalField(key="p.User.phone", name="phone", type=TypeRef(name="string"))
        )
    return Type(key="p.User", name="User", kind=TypeKind.RECORD, fields=fields)


def _api(*, extra_field: bool = False) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="p", namespace="p"),
        types=[_user_type(extra_field=extra_field)],
    )


def test_field_number_in_reserved_half_open_message_range() -> None:
    assert field_number_in_reserved(9, [[9, 12]])
    assert field_number_in_reserved(11, [[9, 12]])
    assert not field_number_in_reserved(12, [[9, 12]])
    assert not field_number_in_reserved(8, [[9, 12]])


def test_allocator_honours_reserved_when_synthesizing() -> None:
    record = Type(
        key="p.M",
        name="M",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="p.M.a", name="a", type=TypeRef(name="string")),
            CanonicalField(key="p.M.b", name="b", type=TypeRef(name="string")),
        ],
        extras={"reserved_ranges": [[2, 4]]},
    )
    counter = FieldNumberAllocator(record)
    a, synth_a = counter.allocate(record.fields[0])
    b, synth_b = counter.allocate(record.fields[1])
    assert synth_a and synth_b
    assert a == 1
    assert b == 4  # skips reserved 2 and 3


def test_allocator_reuses_persisted_numbers() -> None:
    record = _user_type()
    counter = FieldNumberAllocator(
        record,
        persisted={"p.User.id": 7, "p.User.name": 8},
    )
    id_num, id_synth = counter.allocate(record.fields[0])
    name_num, name_synth = counter.allocate(record.fields[1])
    assert id_synth and name_synth
    assert id_num == 7
    assert name_num == 8
    assert counter.new_assignments == {}


def test_allocator_assigns_new_numbers_for_new_fields() -> None:
    record = _user_type(extra_field=True)
    counter = FieldNumberAllocator(
        record,
        persisted={"p.User.id": 1, "p.User.name": 2},
    )
    counter.allocate(record.fields[0])
    counter.allocate(record.fields[1])
    phone_num, phone_synth = counter.allocate(record.fields[2])
    assert phone_synth
    assert phone_num == 3
    assert counter.new_assignments == {"p.User.phone": 3}


def test_proto_emitter_reexport_is_stable_with_persisted_options() -> None:
    api = _api()
    first = ProtoEmitter().emit(api)
    assert first.field_identity_assignments == {"p.User.id": 1, "p.User.name": 2}

    persisted = {**first.field_identity_assignments}
    second = ProtoEmitter().emit(
        api,
        opts=ProtoEmitOptions(persisted_field_numbers=persisted),
    )
    assert str(first.files[0].content) == str(second.files[0].content)
    assert second.field_identity_assignments == {}


def test_proto_emitter_new_field_gets_next_number_with_persistence() -> None:
    api_v1 = _api()
    first = ProtoEmitter().emit(api_v1)
    persisted = {**first.field_identity_assignments}

    api_v2 = _api(extra_field=True)
    second = ProtoEmitter().emit(
        api_v2,
        opts=ProtoEmitOptions(persisted_field_numbers=persisted),
    )
    text = str(second.files[0].content)
    assert "string id = 1;" in text
    assert "string name = 2;" in text
    assert "string phone = 3;" in text
    assert second.field_identity_assignments == {"p.User.phone": 3}


def test_synthesized_fields_reported_as_synth_in_fidelity_engine() -> None:
    report = compute_lossiness(_api(), ProtoEmitter.capability_profile())
    synths = report.items_of_kind(LossinessKind.SYNTH)
    assert {item.construct_key for item in synths} == {"p.User.id", "p.User.name"}


@patch("app.field_identity_store.db")
def test_load_and_persist_field_numbers(mock_db: MagicMock) -> None:
    mock_db.list_export_field_identities.return_value = [
        {"field_key": "p.User.id", "field_number": 5},
    ]
    loaded = load_persisted_field_numbers("tenant-1", "project-1", "proto3")
    assert loaded == {"p.User.id": 5}

    persist_field_number_assignments(
        "tenant-1",
        "project-1",
        "proto3",
        {"p.User.name": 6},
    )
    mock_db.upsert_export_field_identity.assert_called_once_with(
        "tenant-1", "project-1", "proto3", "p.User.name", 6
    )


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_persists_proto_assignments(
    mock_persist: MagicMock,
    mock_load: MagicMock,
) -> None:
    mock_load.return_value = {"p.User.id": 1}
    api = _api(extra_field=True)
    result = emit_canonical(
        api,
        "proto3",
        persistence=ExportPersistenceContext(
            tenant_id="tenant-1",
            artifact_id="project-1",
        ),
    )
    text = str(result.files[0].content)
    assert "string id = 1;" in text
    assert "string name = 2;" in text
    assert "string phone = 3;" in text
    mock_load.assert_called_once_with("tenant-1", "project-1", "proto3")
    mock_persist.assert_called_once_with(
        "tenant-1",
        "project-1",
        "proto3",
        {"p.User.name": 2, "p.User.phone": 3},
    )


# ---------------------------------------------------------------------------
# Allocator: a stored number never duplicates another field's
# ---------------------------------------------------------------------------


def test_allocator_replaces_a_stored_number_the_source_now_uses() -> None:
    """The source gave ``name`` the number ``id`` was stored with: ``id`` gets a fresh one."""
    record = Type(
        key="p.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="p.User.id", name="id", type=TypeRef(name="string")),
            CanonicalField(key="p.User.name", name="name", type=TypeRef(name="string"), field_number=1),
        ],
    )
    counter = FieldNumberAllocator(record, persisted={"p.User.id": 1})
    id_num, id_synth = counter.allocate(record.fields[0])
    name_num, name_synth = counter.allocate(record.fields[1])
    assert (name_num, name_synth) == (1, False)
    assert id_synth and id_num == 2
    assert counter.new_assignments == {"p.User.id": 2}


def test_allocator_never_hands_one_stored_number_to_two_fields() -> None:
    record = _user_type()
    counter = FieldNumberAllocator(record, persisted={"p.User.id": 4, "p.User.name": 4})
    first, _ = counter.allocate(record.fields[0])
    second, _ = counter.allocate(record.fields[1])
    assert first == 4
    assert second != 4
    assert counter.new_assignments == {"p.User.name": second}


# ---------------------------------------------------------------------------
# Thrift (MFX-25.2)
# ---------------------------------------------------------------------------


def _thrift_ids(text: str, struct: str = "User") -> dict[str, int]:
    """``field name → id`` of one struct, as the Thrift parser reads it."""
    (parsed,) = [s for s in parse_thrift(text).structs if s.name == struct]
    return {field.name: field.id for field in parsed.fields}


def test_thrift_first_export_reports_its_assignments() -> None:
    result = ThriftEmitter().emit(_api())
    assert result.field_identity_assignments == {"p.User.id": 1, "p.User.name": 2}
    assert _thrift_ids(str(result.files[0].content)) == {"id": 1, "name": 2}


def test_thrift_reexport_is_identical_with_persisted_options() -> None:
    api = _api()
    first = ThriftEmitter().emit(api)
    second = ThriftEmitter().emit(
        api, opts=ThriftEmitOptions(persisted_field_numbers=dict(first.field_identity_assignments))
    )
    assert str(first.files[0].content) == str(second.files[0].content)
    assert second.field_identity_assignments == {}


def test_thrift_new_field_gets_a_fresh_id_and_old_ids_hold() -> None:
    """A field added before an existing one does not shift the ids already exported."""
    persisted = {"p.User.id": 1, "p.User.name": 2}
    record = Type(
        key="p.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="p.User.phone", name="phone", type=TypeRef(name="string")),
            *_user_type().fields,
        ],
    )
    api = _api().model_copy(update={"types": [record]})
    result = ThriftEmitter().emit(api, opts=ThriftEmitOptions(persisted_field_numbers=persisted))
    assert _thrift_ids(str(result.files[0].content)) == {"id": 1, "name": 2, "phone": 3}
    assert result.field_identity_assignments == {"p.User.phone": 3}


def test_thrift_reports_synthesized_ids() -> None:
    """Every id the emitter invents is an INFERRED loss and INFERRED provenance; source ids are not."""
    record = Type(
        key="p.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="p.User.id", name="id", type=TypeRef(name="string"), field_number=1),
            CanonicalField(key="p.User.name", name="name", type=TypeRef(name="string")),
        ],
    )
    result = ThriftEmitter().emit(_api().model_copy(update={"types": [record]}))
    synthesized = [loss for loss in result.losses if loss.subject == "synthesized-field-number"]
    assert [loss.pointer for loss in synthesized] == ["p.User.name"]
    provenance = {record.pointer: record.provenance.value for record in result.provenance}
    assert provenance["p.User.name"] == "inferred"
    assert provenance["p.User.id"] == "source"


def test_thrift_synthesized_ids_reported_as_synth_in_fidelity_engine() -> None:
    report = compute_lossiness(_api(), ThriftEmitter.capability_profile())
    synths = report.items_of_kind(LossinessKind.SYNTH)
    assert {item.construct_key for item in synths} == {"p.User.id", "p.User.name"}


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_persists_thrift_assignments_under_their_own_key(
    mock_persist: MagicMock,
    mock_load: MagicMock,
) -> None:
    """Thrift loads and stores under ``thrift``, never under Protobuf's ``proto3``."""
    mock_load.return_value = {"p.User.id": 5}
    result = emit_canonical(
        _api(extra_field=True),
        "thrift",
        persistence=ExportPersistenceContext(tenant_id="tenant-1", artifact_id="project-1"),
    )
    assert _thrift_ids(str(result.files[0].content)) == {"id": 5, "name": 1, "phone": 2}
    mock_load.assert_called_once_with("tenant-1", "project-1", "thrift")
    mock_persist.assert_called_once_with(
        "tenant-1", "project-1", "thrift", {"p.User.name": 1, "p.User.phone": 2}
    )


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_keeps_caller_options_when_merging_stored_ids(
    mock_persist: MagicMock,
    mock_load: MagicMock,
) -> None:
    mock_load.return_value = {}
    result = emit_canonical(
        _api(),
        "thrift",
        opts={"include_comments": False},
        persistence=ExportPersistenceContext(tenant_id="tenant-1", artifact_id="project-1"),
    )
    assert "Generated Apache Thrift IDL" not in str(result.files[0].content)


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_does_not_touch_the_store_for_other_targets(
    mock_persist: MagicMock,
    mock_load: MagicMock,
) -> None:
    emit_canonical(
        _api(),
        "openapi",
        persistence=ExportPersistenceContext(tenant_id="tenant-1", artifact_id="project-1"),
    )
    mock_load.assert_not_called()
    mock_persist.assert_not_called()


def test_emit_canonical_without_persistence_still_numbers_thrift_fields() -> None:
    result = emit_canonical(_api(), "thrift")
    assert _thrift_ids(str(result.files[0].content)) == {"id": 1, "name": 2}


def test_allocator_never_reuses_the_number_of_a_removed_field() -> None:
    """``name`` (2) was dropped from the schema; the new ``phone`` gets 3, not 2."""
    record = Type(
        key="p.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="p.User.id", name="id", type=TypeRef(name="string")),
            CanonicalField(key="p.User.phone", name="phone", type=TypeRef(name="string")),
        ],
    )
    counter = FieldNumberAllocator(
        record,
        # Rows of another message, and of a type nested under this one, do not retire numbers here.
        persisted={"p.User.id": 1, "p.User.name": 2, "p.Order.total": 3, "p.User.Address.street": 4},
    )
    assert counter.allocate(record.fields[0]) == (1, True)
    assert counter.allocate(record.fields[1]) == (3, True)
    assert counter.new_assignments == {"p.User.phone": 3}


def test_thrift_removed_field_id_is_not_reused_on_reexport() -> None:
    first = ThriftEmitter().emit(_api())  # id = 1, name = 2
    record = Type(
        key="p.User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="p.User.id", name="id", type=TypeRef(name="string")),
            CanonicalField(key="p.User.phone", name="phone", type=TypeRef(name="string")),
        ],
    )
    second = ThriftEmitter().emit(
        _api().model_copy(update={"types": [record]}),
        opts=ThriftEmitOptions(persisted_field_numbers=dict(first.field_identity_assignments)),
    )
    assert _thrift_ids(str(second.files[0].content)) == {"id": 1, "phone": 3}
