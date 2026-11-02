"""API Blueprint → canonical model — MFI-16.2 (#3805).

Resource groups, resources, actions, transactions and MSON reach the canonical model through the
built-in reader: groups as operation tags, named requests with their body, request and response
headers, inline bodies as types, MSON type names with spaces, inheritance and mixins (flattened),
nested objects, inline enums and ``nullable``. The Avro-style contract pair is held too: the API
Blueprint emitter writes inheritance and mixins back so a re-import records the same model.
"""

from __future__ import annotations

from textwrap import dedent
from typing import Any, Dict

import pytest

from app.apiblueprint_import_source import ApiblueprintImportSource
from app.apiblueprint_parser import parse_apiblueprint
from app.canonical_model import CanonicalApi, Operation, Type

_SOURCE = ApiblueprintImportSource()

SHELTER = dedent(
    """\
    FORMAT: 1A
    HOST: https://api.example.com

    # Shelter API

    A shelter service.

    # Group Pets

    ## Pets Collection [/pets{?status}]

    + Parameters
        + status (enum[string], optional) - Filter by status.
            + Members
                + available
                + adopted
        + limit (number, optional) - Page size.
            + Default: 20

    ### List pets [GET]

    + Response 200 (application/json)
        + Headers

                X-Total-Count: 2
                Link: <https://api.example.com/pets?page=2>; rel="next"

        + Attributes (array[Pet])

    ### Create pet [POST]

    + Request Minimal (application/json)
        + Headers

                Idempotency-Key: 123

        + Attributes (Pet)

    + Response 201 (application/json)
        + Attributes (Pet)

    + Request Invalid (application/json)
        + Attributes (Problem)

    + Response 422 (application/json)
        + Attributes (Error)

    # Group Owners

    ## Owner [/owners/{id}]

    + Parameters
        + id (number, required)

    ### Get owner [GET]

    + Response 200 (application/json)
        + Attributes
            + id: 1 (number, required)
            + name: Jane (string)
            + address (object)
                + city: Tokyo (string, required)
                + geo (object)
                    + lat: 35.6 (number)

    # Data Structures

    ## Pet (object)
    + id: 1 (number, required)
    + name: Rex (string, required)
    + status (enum[string])
        + Members
            + available
            + adopted
    + owner (Owner Summary, nullable)

    ## Owner Summary (object)
    + id (number)

    ## Cat (Pet)
    + indoor: true (boolean)

    ## Error (object)
    + Include Problem
    + code: 422 (number)

    ## Problem (object)
    + message (string, required)

    ## Status (enum)
    + available
    + adopted
    """
)


def _api(text: str = SHELTER) -> CanonicalApi:
    return _SOURCE.normalize(_SOURCE.parse(text), include_raw=False)


def _type(api: CanonicalApi, name: str) -> Type:
    return next(t for t in api.types if t.name == name)


def _operation(api: CanonicalApi, name: str) -> Operation:
    return next(o for s in api.services for o in s.operations if o.name == name)


def _fields(type_: Type) -> Dict[str, Any]:
    return {f.name: f for f in type_.fields}


# --- resource groups ---------------------------------------------------------------------------


def test_each_action_is_tagged_with_its_group() -> None:
    api = _api()
    assert _operation(api, "List pets").tags == ["Pets"]
    assert _operation(api, "Create pet").tags == ["Pets"]
    assert _operation(api, "Get owner").tags == ["Owners"]
    assert _operation(api, "Get owner").extras["apib_group"] == "Owners"


def test_a_group_heading_is_not_the_title() -> None:
    text = "FORMAT: 1A\n\n# Group Pets\n\n## Pets [/pets]\n\n### List [GET]\n\n+ Response 200\n"
    document = parse_apiblueprint(text, source_label="pets.apib")
    assert document.title == "pets.apib"
    assert document.operations[0].group == "Pets"


def test_an_action_outside_any_group_has_no_tag() -> None:
    text = "FORMAT: 1A\n\n# API\n\n## Pets [/pets]\n\n### List [GET]\n\n+ Response 200\n"
    operation = _operation(_api(text), "List")
    assert operation.tags == [] and "apib_group" not in operation.extras


# --- transactions ------------------------------------------------------------------------------


def test_a_named_request_keeps_its_body_and_headers() -> None:
    operation = _operation(_api(), "Create pet")
    request = next(m for m in operation.messages if m.role.value == "request")
    assert request.payload is not None and request.payload.name == "Pet"
    assert request.content_types == ["application/json"]
    assert [h.name for h in request.headers] == ["Idempotency-Key"]


def test_a_further_request_is_not_the_operations_body() -> None:
    document = parse_apiblueprint(SHELTER)
    create = next(o for o in document.operations if o.name == "Create pet")
    assert create.request_type == "Pet"
    assert [status for status, *_ in create.responses] == ["201", "422"]


def test_a_bare_request_line_is_read() -> None:
    text = (
        "FORMAT: 1A\n\n# API\n\n## Pets [/pets]\n\n### Create [POST]\n\n+ Request\n"
        "    + Attributes (Pet)\n\n+ Response 204\n\n# Data Structures\n\n## Pet (object)\n+ id (number)\n"
    )
    document = parse_apiblueprint(text)
    assert document.operations[0].request_type == "Pet"
    assert document.operations[0].request_media_type is None


def test_response_headers_are_message_headers() -> None:
    response = next(m for m in _operation(_api(), "List pets").messages if m.status_code == "200")
    headers = {h.name: h for h in response.headers}
    assert set(headers) == {"X-Total-Count", "Link"}
    assert headers["X-Total-Count"].extras["apib_sample"] == "2"
    assert headers["Link"].extras["apib_sample"] == '<https://api.example.com/pets?page=2>; rel="next"'
    assert response.payload is not None and response.payload.item is not None
    assert response.payload.item.name == "Pet"


def test_an_inline_body_is_a_type_with_its_nested_objects() -> None:
    api = _api()
    response = next(m for m in _operation(api, "Get owner").messages if m.status_code == "200")
    assert response.payload is not None and response.payload.name == "Get owner 200 Response"
    body = _type(api, "Get owner 200 Response")
    assert body.extras["apib_inline"] is True
    assert set(_fields(body)) == {"id", "name", "address"}
    address = _type(api, "Get owner 200 Response.address")
    assert _fields(body)["address"].type.name == address.key
    assert set(_fields(address)) == {"city", "geo"}
    assert set(_fields(_type(api, "Get owner 200 Response.address.geo"))) == {"lat"}


def test_an_inline_body_with_no_members_stays_untyped() -> None:
    text = (
        "FORMAT: 1A\n\n# API\n\n## Ping [/ping]\n\n### Ping [GET]\n\n"
        "+ Response 200 (application/json)\n    + Attributes\n"
    )
    response = next(m for m in _operation(_api(text), "Ping").messages)
    assert response.payload is not None and response.payload.name == "object"


# --- parameters --------------------------------------------------------------------------------


def test_an_enum_parameter_keeps_its_members_and_the_parameters_after_it() -> None:
    operation = _operation(_api(), "List pets")
    params = {p.name: p for p in operation.parameters}
    assert params["status"].constraints is not None and params["status"].constraints.enum == ["available", "adopted"]
    assert params["status"].type.name == "string"
    # Before MFI-16.2, `+ Members` ended the parameters block and `limit` was lost.
    assert params["limit"].default == 20


# --- MSON --------------------------------------------------------------------------------------


def test_a_type_name_with_spaces_is_its_own_type() -> None:
    api = _api()
    assert set(_fields(_type(api, "Owner Summary"))) == {"id"}
    # Its member no longer leaks into the type above it.
    assert set(_fields(_type(api, "Pet"))) == {"id", "name", "status", "owner"}


def test_inheritance_flattens_the_base_members_first() -> None:
    cat = _type(_api(), "Cat")
    assert set(_fields(cat)) == {"id", "name", "status", "owner", "indoor"}
    assert cat.extras["apib_base"] == "Pet"
    assert cat.extras["apib_kind"] == "object"


def test_a_mixin_contributes_its_members() -> None:
    error = _type(_api(), "Error")
    assert set(_fields(error)) == {"message", "code"}
    assert error.extras["apib_includes"] == ["Problem"]
    assert _fields(error)["message"].type.nullable is False


def test_a_later_member_overrides_an_inherited_one() -> None:
    text = (
        "FORMAT: 1A\n\n# API\n\n# Data Structures\n\n## Base (object)\n+ id (number)\n\n"
        "## Child (Base)\n+ id (string, required)\n"
    )
    child = _type(_api(text), "Child")
    assert _fields(child)["id"].type.name == "string"
    assert _fields(child)["id"].type.nullable is False


def test_an_inheritance_cycle_or_unknown_base_contributes_nothing() -> None:
    text = (
        "FORMAT: 1A\n\n# API\n\n# Data Structures\n\n## A (B)\n+ a (string)\n\n"
        "## B (object)\n+ Include A\n+ b (string)\n\n"
        "## C (Missing)\n+ c (string)\n"
    )
    api = _api(text)
    assert set(_fields(_type(api, "A"))) == {"a", "b"}
    assert set(_fields(_type(api, "B"))) == {"a", "b"}
    assert set(_fields(_type(api, "C"))) == {"c"}


def test_an_inline_enum_member_is_a_constrained_string() -> None:
    status = _fields(_type(_api(), "Pet"))["status"]
    assert status.type.name == "string"
    assert status.constraints is not None and status.constraints.enum == ["available", "adopted"]


def test_nullable_makes_even_a_required_reference_nullable() -> None:
    text = "FORMAT: 1A\n\n# API\n\n# Data Structures\n\n## T (object)\n+ owner (string, required, nullable)\n"
    owner = _fields(_type(_api(text), "T"))["owner"]
    assert owner.type.nullable is True
    assert owner.extras["apib_nullable"] is True
    assert _fields(_type(_api(), "Pet"))["owner"].type.nullable is True


def test_an_enum_type_lists_its_members() -> None:
    status = _type(_api(), "Status")
    assert [v.name for v in status.enum_values] == ["available", "adopted"]


@pytest.mark.parametrize(
    "heading, kind, base",
    [
        ("## Pet (object)", "object", None),
        ("## Pet", "object", None),
        ("## Pet (Animal)", "object", "Animal"),
        ("## Pet (Animal, fixed)", "object", "Animal"),
        ("## Tags (array[string])", "array", None),
        ("## Color (enum[string])", "enum", None),
    ],
)
def test_a_data_structure_heading_names_its_kind_and_base(heading: str, kind: str, base: str | None) -> None:
    document = parse_apiblueprint(f"FORMAT: 1A\n\n# API\n\n# Data Structures\n\n{heading}\n+ x (string)\n")
    parsed = document.types[0]
    assert (parsed.kind, parsed.base) == (kind, base)


def test_samples_and_sections_are_not_members() -> None:
    text = (
        "FORMAT: 1A\n\n# API\n\n# Data Structures\n\n## T (object)\n+ Properties\n    + a (string)\n"
        "+ b (array[string])\n    + Sample\n        + x (string)\n"
    )
    assert set(_fields(_type(_api(text), "T"))) == {"a", "b"}


# --- the emitter writes it back ----------------------------------------------------------------


def test_inheritance_and_mixins_round_trip_through_the_emitter() -> None:
    from app.emitter import get_emitter, load_builtin_emitters

    load_builtin_emitters()
    text = (
        "FORMAT: 1A\n\n# API\n\n## Things [/things]\n\n### List [GET]\n\n+ Response 200 (application/json)\n"
        "    + Attributes (Error)\n\n# Data Structures\n\n## Problem (object)\n+ message (string, required)\n\n"
        "## Base (object)\n+ id (number)\n\n## Error (Base)\n+ Include Problem\n+ code (number)\n"
    )
    api = _api(text)
    emitted = get_emitter("apiblueprint")().emit(api)
    blueprint = next(str(f.content) for f in emitted.files if str(f.path).endswith(".apib"))
    assert "## Error (Base)" in blueprint
    assert "+ Include Problem" in blueprint

    again = _type(_api(blueprint), "Error")
    original = _type(api, "Error")
    assert again.extras["apib_base"] == original.extras["apib_base"] == "Base"
    assert again.extras["apib_includes"] == ["Problem"]
    assert set(_fields(again)) == set(_fields(original)) == {"id", "message", "code"}
