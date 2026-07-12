"""Tests for TypeSpec catalog import/export adapters — MFI-22.3."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.typespec_emitter import validate_typespec_document
from app.typespec_import_source import TypeSpecImportSource
from app.typespec_normalizer import TypeSpecNormalizer
from app.typespec_parser import is_typespec, parse_typespec

_PETS_API = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/typespec/01-pets-api.tsp"
).read_text(encoding="utf-8")
_ORDERS_API = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/typespec/02-orders-api.tsp"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> TypeSpecImportSource:
    return TypeSpecImportSource()


def test_is_typespec_recognizes_pets_fixture():
    assert is_typespec(_PETS_API) is True
    assert is_typespec('syntax = "proto3";\npackage demo;\n') is False


def test_parse_pets_fixture_collects_models_and_operations():
    doc = parse_typespec(_PETS_API)
    assert doc.namespace == "PetStore"
    assert doc.service_title == "Pets API"
    assert {model.name for model in doc.models} == {"Pet", "NewPet"}
    assert doc.enums[0].name == "PetStatus"
    pets = doc.interfaces[0]
    assert pets.name == "Pets"
    assert pets.route_prefix == "/pets"
    assert {operation.name for operation in pets.operations} == {"list", "read", "create"}


def test_parse_orders_fixture_covers_put_and_delete():
    doc = parse_typespec(_ORDERS_API)
    assert doc.namespace == "OrderStore"
    operations = doc.interfaces[0].operations
    assert {operation.verb for operation in operations} == {"get", "put", "delete"}
    update = next(operation for operation in operations if operation.name == "update")
    assert any(param.location == "body" for param in update.parameters)


def test_normalizer_maps_rest_interface_and_operations():
    doc = parse_typespec(_PETS_API)
    api = TypeSpecNormalizer().normalize(doc)
    assert api.format == "typespec"
    assert api.paradigm is ApiParadigm.REST
    pet = next(type_ for type_ in api.types if type_.name == "Pet")
    assert pet.kind is TypeKind.RECORD
    service = api.services[0]
    assert service.name == "Pets"
    assert any(op.http_method == "GET" and op.http_path == "/pets" for op in service.operations)
    assert any(op.http_method == "GET" and op.http_path == "/pets/{id}" for op in service.operations)


def test_adapter_detect_parse_normalize(adapter: TypeSpecImportSource):
    detected = adapter.detect(DetectionInput(text=_PETS_API, filename="01-pets-api.tsp"))
    assert detected.matched
    assert detected.format == "typespec"
    doc = adapter.parse(_PETS_API)
    api = adapter.normalize(doc)
    assert api.extras.get("typespec_models")


def test_adapter_invalid_source_raises(adapter: TypeSpecImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('syntax = "proto3";\npackage demo;\n')


def test_emitter_round_trips_pets_api():
    doc = parse_typespec(_PETS_API)
    api = TypeSpecNormalizer().normalize(doc)
    emitter = get_emitter("typespec")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert 'import "@typespec/http"' in text
    assert "namespace PetStore" in text
    assert "interface Pets" in text
    validate_typespec_document(text)


def test_emitter_round_trips_orders_api():
    doc = parse_typespec(_ORDERS_API)
    api = TypeSpecNormalizer().normalize(doc)
    emitter = get_emitter("typespec")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "@delete remove" in text
    validate_typespec_document(text)


def test_catalog_conversion_resolves_typespec_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("typespec", _PETS_API).key == "typespec"
