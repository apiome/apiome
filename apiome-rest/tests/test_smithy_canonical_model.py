"""Smithy → canonical model — MFI-17.2 (#3809).

Services, operations, resources, shapes and traits reach the canonical model from the JSON AST
(the Smithy CLI's assembled model, or one uploaded as is): ``@http`` bindings and HTTP parameters,
declared and service-wide errors with their ``@httpError`` status, resources with their lifecycle,
member documentation / defaults / constraints (inherited from the simple shapes they target),
``@enumValue`` and ``intEnum`` values, and a hash per shape. The fixture
``tests/fixtures/smithy_canonical_weather.json`` is a Smithy 2.0 JSON AST using each of them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import CanonicalApi, Operation, Type
from app.fingerprint import fingerprint
from app.smithy_ast_mapper import shape_sha256
from app.smithy_import_source import SmithyImportSource

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "smithy_canonical_weather.json"
_SOURCE = SmithyImportSource()


def _ast() -> Dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _api(ast: Dict[str, Any] | None = None) -> CanonicalApi:
    text = json.dumps(ast if ast is not None else _ast())
    return _SOURCE.normalize(_SOURCE.parse(text, source_label="weather.json"), include_raw=False)


def _op(api: CanonicalApi, name: str) -> Operation:
    return next(o for s in api.services for o in s.operations if o.name == name)


def _type(api: CanonicalApi, name: str) -> Type:
    return next(t for t in api.types if t.name == name)


def _field(api: CanonicalApi, type_name: str, field_name: str) -> Any:
    return next(f for f in _type(api, type_name).fields if f.name == field_name)


# --- operations: @http and its parameters ------------------------------------------------------


def test_http_binds_the_method_path_and_projection_binding() -> None:
    get_city = _op(_api(), "GetCity")
    assert (get_city.http_method, get_city.http_path) == ("GET", "/cities/{cityId}")
    assert get_city.extras["http"] == {"method": "get", "path": "/cities/{cityId}"}
    assert get_city.extras["smithy_http_code"] == 200


def test_http_label_query_and_header_members_are_parameters() -> None:
    api = _api()
    get_city = {p.name: p for p in _op(api, "GetCity").parameters}
    assert get_city["cityId"].location.value == "path" and get_city["cityId"].required
    assert get_city["cityId"].constraints is not None and get_city["cityId"].constraints.pattern
    listing = {p.name: p for p in _op(api, "ListCities").parameters}
    assert {name: p.location.value for name, p in listing.items()} == {"nextToken": "query", "pageSize": "query"}
    assert not listing["nextToken"].required


def test_a_header_parameter_is_named_by_its_trait() -> None:
    ast = _ast()
    ast["shapes"]["example.weather#ListCitiesInput"]["members"]["requestId"] = {
        "target": "smithy.api#String",
        "traits": {"smithy.api#httpHeader": "X-Request-Id", "smithy.api#documentation": "Trace id."},
    }
    header = next(p for p in _op(_api(ast), "ListCities").parameters if p.location.value == "header")
    assert (header.name, header.description) == ("X-Request-Id", "Trace id.")
    assert header.extras["smithy_member"] == "requestId"


def test_operation_traits_are_recorded() -> None:
    api = _api()
    assert _op(api, "GetCity").extras["smithy_readonly"] is True
    assert _op(api, "CreateCity").extras["smithy_idempotent"] is True
    assert _op(api, "ListCities").extras["smithy_paginated"]["items"] == "items"
    current = _op(api, "GetCurrentTime")
    assert current.deprecated is True and current.extras["smithy_deprecated"] == {"message": "Use the clock."}


def test_an_operation_without_http_has_no_binding() -> None:
    ast = _ast()
    del ast["shapes"]["example.weather#GetForecast"]["traits"]["smithy.api#http"]
    forecast = _op(_api(ast), "GetForecast")
    assert forecast.http_method is None and forecast.http_path is None and "http" not in forecast.extras


# --- errors ------------------------------------------------------------------------------------


def test_declared_and_service_errors_are_error_messages_with_their_status() -> None:
    errors = {m.name: m for m in _op(_api(), "GetCity").messages if m.role.value == "error"}
    assert set(errors) == {"NoSuchResource", "ServiceUnavailable"}
    assert errors["NoSuchResource"].status_code == "404"
    assert errors["ServiceUnavailable"].status_code == "503"
    # A service-wide error reaches every operation, once.
    for name in ("ListCities", "GetCurrentTime"):
        names = [m.name for m in _op(_api(), name).messages if m.role.value == "error"]
        assert names == ["ServiceUnavailable"]


def test_an_error_structure_records_its_kind_and_status() -> None:
    api = _api()
    assert _type(api, "NoSuchResource").extras["smithy_error"] == "client"
    assert _type(api, "NoSuchResource").extras["smithy_http_error"] == 404
    unavailable = _type(api, "ServiceUnavailable").extras
    assert unavailable["smithy_error"] == "server" and unavailable["smithy_retryable"] is True


def test_an_error_message_is_described_by_its_documented_shape() -> None:
    ast = _ast()
    ast["shapes"]["example.weather#NoSuchResource"]["traits"]["smithy.api#documentation"] = "No such city."
    error = next(m for m in _op(_api(ast), "GetCity").messages if m.name == "NoSuchResource")
    assert error.description == "No such city."


# --- services and resources --------------------------------------------------------------------


def test_the_service_records_its_errors_resources_and_protocols() -> None:
    service = _api().services[0]
    assert service.extras["smithy_errors"] == ["ServiceUnavailable"]
    assert service.extras["smithy_resources"] == ["City"]
    assert service.extras["smithy_service_traits"] == ["aws.protocols#restJson1"]


def test_a_resource_records_identifiers_properties_lifecycle_and_children() -> None:
    city = _type(_api(), "City")
    resource = city.extras["smithy_resource"]
    assert resource["identifiers"] == {"cityId": "String"}
    assert resource["properties"] == {"name": "String"}
    assert resource["lifecycle"] == {"create": "CreateCity", "read": "GetCity", "list": "ListCities"}
    assert resource["resources"] == ["Forecast"]
    assert {f.name for f in city.fields} == {"cityId", "name"}


def test_resource_bound_operations_are_tagged_with_their_resource() -> None:
    api = _api()
    assert _op(api, "GetCity").tags == ["City"]
    assert _op(api, "GetForecast").tags == ["Forecast"]
    assert _op(api, "GetCurrentTime").tags == []


# --- members: traits ---------------------------------------------------------------------------


def test_member_documentation_default_and_constraints() -> None:
    api = _api()
    name = _field(api, "GetCityOutput", "name")
    assert name.description == "City name."
    assert (name.constraints.min_length, name.constraints.max_length) == (1, 64)
    population = _field(api, "GetCityOutput", "population")
    assert population.default == 0 and population.constraints.minimum == 0


def test_a_member_inherits_its_simple_targets_constraints() -> None:
    city_id = _field(_api(), "CitySummary", "cityId")
    assert city_id.constraints is not None and city_id.constraints.pattern == "^[A-Za-z0-9 ]+$"


def test_a_members_own_trait_wins_over_the_inherited_one() -> None:
    ast = _ast()
    ast["shapes"]["example.weather#CitySummary"]["members"]["cityId"]["traits"]["smithy.api#pattern"] = "^[a-z]+$"
    assert _field(_api(ast), "CitySummary", "cityId").constraints.pattern == "^[a-z]+$"


def test_a_lists_length_bounds_its_items() -> None:
    ast = _ast()
    ast["shapes"]["example.weather#ListCitiesOutput"]["members"]["items"]["traits"]["smithy.api#length"] = {"max": 50}
    constraints = _field(_api(ast), "ListCitiesOutput", "items").constraints
    assert constraints.max_items == 50 and constraints.max_length is None


def test_unmodeled_trait_values_are_kept() -> None:
    updated = _field(_api(), "GetCityOutput", "updatedAt")
    assert updated.extras["smithy_trait_values"] == {"timestampFormat": "date-time"}


def test_a_deprecated_member_is_deprecated() -> None:
    ast = _ast()
    ast["shapes"]["example.weather#GetCityOutput"]["members"]["tags"]["traits"] = {"smithy.api#deprecated": {}}
    assert _field(_api(ast), "GetCityOutput", "tags").deprecated is True


# --- enums -------------------------------------------------------------------------------------


def test_enum_values_are_the_wire_values() -> None:
    api = _api()
    assert [(v.name, v.value) for v in _type(api, "CityKind").enum_values] == [("CAPITAL", "capital"), ("TOWN", "town")]
    priority = _type(api, "Priority")
    assert [(v.name, v.value) for v in priority.enum_values] == [("LOW", 1), ("HIGH", 10)]
    assert priority.extras["smithy_kind"] == "intEnum"


def test_an_enum_without_enum_values_keeps_positions() -> None:
    ast = _ast()
    for member in ast["shapes"]["example.weather#CityKind"]["members"].values():
        member.pop("traits")
    assert [v.value for v in _type(_api(ast), "CityKind").enum_values] == [0, 1]


# --- per-shape hashes --------------------------------------------------------------------------


def test_every_shape_is_hashed_by_its_absolute_id() -> None:
    api, ast = _api(), _ast()
    hashes = api.extras["smithy_shape_hashes"]
    assert set(hashes) == set(ast["shapes"])
    assert hashes["example.weather#City"] == shape_sha256(ast["shapes"]["example.weather#City"])


def test_a_shape_hash_ignores_key_order_and_moves_on_an_edit() -> None:
    shape = _ast()["shapes"]["example.weather#GetCity"]
    reordered = dict(reversed(list(copy.deepcopy(shape).items())))
    assert shape_sha256(reordered) == shape_sha256(shape)
    edited = copy.deepcopy(shape)
    edited["traits"]["smithy.api#http"]["method"] = "POST"
    assert shape_sha256(edited) != shape_sha256(shape)


def test_the_shape_hashes_stay_out_of_the_version_fingerprint() -> None:
    api = _api()
    stripped = api.model_copy(update={"extras": {k: v for k, v in api.extras.items() if k != "smithy_shape_hashes"}})
    assert fingerprint(api).fingerprint == fingerprint(stripped).fingerprint


# --- the IDL reader stays as it was ------------------------------------------------------------


def test_the_idl_reader_records_none_of_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import smithy_import_source

    monkeypatch.setattr(smithy_import_source, "smithy_cli_available", lambda: False)
    idl = (
        '$version: "2"\nnamespace example.weather\n\n@readonly\n@http(method: "GET", uri: "/time")\n'
        "operation GetTime {\n    output: GetTimeOutput\n}\n\nstructure GetTimeOutput {\n    @required\n"
        "    time: Timestamp\n}\n\nservice Weather {\n    version: \"1\"\n    operations: [GetTime]\n}\n"
    )
    api = _SOURCE.normalize(_SOURCE.parse(idl, source_label="weather.smithy"), include_raw=False)
    operation = _op(api, "GetTime")
    assert operation.http_method is None and "http" not in operation.extras
    assert "smithy_shape_hashes" not in api.extras


# --- conversion to OpenAPI uses the bindings ---------------------------------------------------


def test_a_json_ast_model_converts_to_openapi_with_its_own_routes() -> None:
    from app.conversion_job import ConversionSource, preview_conversion

    text = _FIXTURE.read_text(encoding="utf-8")
    api = _SOURCE.normalize(_SOURCE.parse(text, source_label="weather.json"))
    preview = preview_conversion(ConversionSource(api=api, source_project_id="p1", source_format="smithy"))
    routes = {
        (method, path)
        for path, item in preview.document.get("paths", {}).items()
        for method in item
        if method in {"get", "put", "post", "delete", "patch"}
    }
    # Before MFI-17.2 a JSON AST had no bindings and every operation became POST /{Service}/{Operation}.
    assert routes == {
        ("get", "/cities"),
        ("get", "/cities/{cityId}"),
        ("get", "/cities/{cityId}/forecast"),
        ("get", "/time"),
        ("put", "/cities/{cityId}"),
    }
