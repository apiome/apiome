"""Tests for persisted export field identities — MFX-12.2 (#3880)."""

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
from app.field_identity_store import (
    FieldNumberAllocator,
    field_number_in_reserved,
    load_persisted_field_numbers,
    persist_field_number_assignments,
)
from app.fidelity_engine import compute_lossiness
from app.lossiness import LossinessKind
from app.proto_emitter import ProtoEmitOptions, ProtoEmitter


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
