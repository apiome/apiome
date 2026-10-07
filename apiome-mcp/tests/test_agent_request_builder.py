"""AGX-2.1 request construction (#4533): arguments → the HTTP request the spec describes.

Pins the OpenAPI 3 serialization table (path / query / header styles), the Swagger 2.0
``collectionFormat`` mapping, the flat-versus-nested body rule shared with the AGX-1.1 compiler,
body encodings per media type, server URL resolution, and the request-level safety rails (no empty or
dot-segment path values, no header line breaks, protected headers never settable).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, Server, ServerVariable

from agent_runtime_fakes import PETSTORE, source_item
from apiome_mcp.agent_request_builder import (
    InvalidArgumentsError,
    OperationBinding,
    OperationNotInvocableError,
    ParameterBinding,
    binding_for,
    build_request,
    resolve_server_url,
)
from apiome_mcp.agent_toolset_source import ToolsetManifest, compile_served_toolset


def _manifest(exposed: tuple[str, ...]) -> ToolsetManifest:
    return ToolsetManifest(
        toolset_id="t",
        tenant_id="x",
        version_id="v",
        target="mock",
        tenant_slug="acme",
        project_slug="petstore",
        version_label="1.0.0",
        exposed=exposed,
    )


def _bindings(document: dict[str, Any], exposed: tuple[str, ...]) -> dict[str, OperationBinding]:
    served = compile_served_toolset(_manifest(exposed), source_item(document))
    return {name: tool.binding for name, tool in served.tools.items() if tool.binding is not None}


def _one(param: dict[str, Any], *, path: str = "/items", method: str = "get") -> OperationBinding:
    """Bind a one-parameter operation."""
    document = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {
            path: {method: {"operationId": "op", "parameters": [param], "responses": {"200": {"description": "ok"}}}}
        },
    }
    return _bindings(document, (f"{method.upper()} {path}",))["op"]


# ============================================================================
# Binding the Petstore
# ============================================================================


def test_petstore_bindings_carry_method_path_and_argument_locations() -> None:
    bindings = _bindings(PETSTORE, ("GET /pets", "POST /pets", "GET /pets/{petId}", "DELETE /pets/{petId}"))
    listing = bindings["listPets"]
    assert (listing.method, listing.path_template, listing.body_mode) == ("GET", "/pets", "none")
    assert {(p.name, p.location, p.style, p.explode) for p in listing.parameters} == {
        ("limit", "query", "form", True),
        ("tags", "query", "form", False),
    }
    assert listing.accept == "application/json"
    create = bindings["createPet"]
    assert (create.body_mode, create.body_required, create.body_media_type) == ("flat", True, "application/json")
    show = bindings["showPetById"]
    assert {(p.name, p.location) for p in show.parameters} == {("petId", "path"), ("X-Request-Id", "header")}
    assert show.path_arguments == ("petId",)


def test_a_body_property_colliding_with_a_parameter_nests_the_body() -> None:
    document = copy.deepcopy(PETSTORE)
    body = document["paths"]["/pets"]["post"]
    body["parameters"] = [{"name": "name", "in": "query", "schema": {"type": "string"}}]
    binding = _bindings(document, ("POST /pets",))["createPet"]
    assert binding.body_mode == "nested"
    request = build_request(binding, {"name": "q", "body": {"name": "Tom"}})
    assert request.query == "name=q"
    assert json.loads(request.content or b"") == {"name": "Tom"}


def test_a_non_object_body_nests_under_body() -> None:
    document = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/tags": {
                "put": {
                    "operationId": "setTags",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "array", "items": {"type": "string"}}}}
                    },
                    "responses": {"204": {"description": "ok"}},
                }
            }
        },
    }
    binding = _bindings(document, ("PUT /tags",))["setTags"]
    assert binding.body_mode == "nested"
    assert build_request(binding, {"body": ["a", "b"]}).content == b'["a","b"]'


def test_credential_parameters_are_not_bound() -> None:
    binding = _one({"name": "api_key", "in": "query", "schema": {"type": "string"}})
    assert binding.parameters == ()


def test_an_operation_without_http_binding_is_not_invocable() -> None:
    from app.canonical_model import Operation, OperationKind

    api = CanonicalApi(paradigm=ApiParadigm.RPC, format="grpc", identity=ApiIdentity(name="x"))
    with pytest.raises(OperationNotInvocableError):
        binding_for(api, Operation(key="svc.Do", name="Do", kind=OperationKind.REQUEST_RESPONSE))


# ============================================================================
# Path serialization
# ============================================================================


def _path(style: str, explode: bool, value: Any) -> str:
    binding = OperationBinding(
        operation_key="GET /x/{id}",
        method="GET",
        path_template="/x/{id}",
        parameters=(ParameterBinding(name="id", location="path", style=style, explode=explode, required=True),),
    )
    return build_request(binding, {"id": value}).path


@pytest.mark.parametrize(
    ("style", "explode", "value", "expected"),
    [
        ("simple", False, "blue", "/x/blue"),
        ("simple", False, ["blue", "black"], "/x/blue,black"),
        ("simple", False, {"R": 100, "G": 200}, "/x/R,100,G,200"),
        ("simple", True, {"R": 100, "G": 200}, "/x/R=100,G=200"),
        ("label", False, "blue", "/x/.blue"),
        ("label", False, ["blue", "black"], "/x/.blue,black"),
        ("label", True, ["blue", "black"], "/x/.blue.black"),
        ("label", True, {"R": 100, "G": 200}, "/x/.R=100.G=200"),
        ("matrix", False, "blue", "/x/;id=blue"),
        ("matrix", False, ["blue", "black"], "/x/;id=blue,black"),
        ("matrix", True, ["blue", "black"], "/x/;id=blue;id=black"),
        ("matrix", True, {"R": 100, "G": 200}, "/x/;R=100;G=200"),
        ("simple", False, True, "/x/true"),
        ("simple", False, 42, "/x/42"),
    ],
)
def test_path_styles_follow_the_openapi_table(style: str, explode: bool, value: Any, expected: str) -> None:
    assert _path(style, explode, value) == expected


def test_a_path_value_cannot_add_segments_or_a_query() -> None:
    assert _path("simple", False, "a/b?c=d#e") == "/x/a%2Fb%3Fc%3Dd%23e"


@pytest.mark.parametrize("value", ["", ".", ".."])
def test_an_empty_or_dot_path_value_is_refused(value: str) -> None:
    with pytest.raises(InvalidArgumentsError) as exc:
        _path("simple", False, value)
    assert exc.value.issues[0].argument == "id"


def test_a_missing_path_value_is_refused() -> None:
    binding = _bindings(PETSTORE, ("GET /pets/{petId}",))["showPetById"]
    with pytest.raises(InvalidArgumentsError) as exc:
        build_request(binding, {})
    assert [issue.argument for issue in exc.value.issues] == ["petId"]


# ============================================================================
# Query and header serialization
# ============================================================================


def _query(style: str, explode: bool, value: Any, *, allow_reserved: bool = False) -> str:
    binding = OperationBinding(
        operation_key="GET /x",
        method="GET",
        path_template="/x",
        parameters=(
            ParameterBinding(
                name="color", location="query", style=style, explode=explode, allow_reserved=allow_reserved
            ),
        ),
    )
    return build_request(binding, {"color": value}).query


@pytest.mark.parametrize(
    ("style", "explode", "value", "expected"),
    [
        ("form", True, "blue", "color=blue"),
        ("form", True, ["blue", "black"], "color=blue&color=black"),
        ("form", False, ["blue", "black"], "color=blue,black"),
        ("form", True, {"R": 100, "G": 200}, "R=100&G=200"),
        ("form", False, {"R": 100, "G": 200}, "color=R,100,G,200"),
        ("spaceDelimited", False, ["blue", "black"], "color=blue%20black"),
        ("pipeDelimited", False, ["blue", "black"], "color=blue|black"),
        ("deepObject", True, {"R": 100, "G": 200}, "color%5BR%5D=100&color%5BG%5D=200"),
        ("form", True, False, "color=false"),
        ("form", True, "a&b=c", "color=a%26b%3Dc"),
    ],
)
def test_query_styles_follow_the_openapi_table(style: str, explode: bool, value: Any, expected: str) -> None:
    assert _query(style, explode, value) == expected


def test_allow_reserved_keeps_reserved_characters_but_never_pair_separators() -> None:
    assert _query("form", True, "a/b:c&d", allow_reserved=True) == "color=a/b:c%26d"


def test_an_absent_optional_query_parameter_is_omitted() -> None:
    binding = _bindings(PETSTORE, ("GET /pets",))["listPets"]
    assert build_request(binding, {}).query == ""


@pytest.mark.parametrize(
    ("collection_format", "expected"),
    [("csv", "t=a,b"), ("multi", "t=a&t=b"), ("ssv", "t=a%20b"), ("pipes", "t=a|b"), ("tsv", "t=a%09b")],
)
def test_swagger_collection_formats_map_to_query_styles(collection_format: str, expected: str) -> None:
    document = {
        "swagger": "2.0",
        "info": {"title": "S", "version": "1"},
        "host": "api.example.com",
        "schemes": ["https"],
        "paths": {
            "/x": {
                "get": {
                    "operationId": "op",
                    "parameters": [
                        {
                            "name": "t",
                            "in": "query",
                            "type": "array",
                            "items": {"type": "string"},
                            "collectionFormat": collection_format,
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    item = source_item(document)
    item["source_format"] = "swagger-2.0"
    served = compile_served_toolset(_manifest(("GET /x",)), item)
    binding = served.tools["op"].binding
    assert binding is not None
    assert build_request(binding, {"t": ["a", "b"]}).query == expected


def test_header_values_are_simple_style() -> None:
    binding = _one({"name": "X-Tags", "in": "header", "schema": {"type": "array", "items": {"type": "string"}}})
    assert build_request(binding, {"X-Tags": ["a", "b"]}).headers["X-Tags"] == "a,b"


def test_a_header_value_with_a_line_break_is_refused() -> None:
    binding = _one({"name": "X-Note", "in": "header", "schema": {"type": "string"}})
    with pytest.raises(InvalidArgumentsError) as exc:
        build_request(binding, {"X-Note": "a\r\nX-Injected: 1"})
    assert exc.value.issues[0].argument == "X-Note"


@pytest.mark.parametrize("name", ["Host", "Content-Length", "Transfer-Encoding", "Cookie"])
def test_protected_headers_are_never_set_from_arguments(name: str) -> None:
    binding = OperationBinding(
        operation_key="GET /x",
        method="GET",
        path_template="/x",
        parameters=(ParameterBinding(name=name, location="header", style="simple", explode=False),),
    )
    assert name not in build_request(binding, {name: "evil"}).headers


# ============================================================================
# Bodies
# ============================================================================


def test_a_flat_body_collects_the_non_parameter_arguments() -> None:
    binding = _bindings(PETSTORE, ("POST /pets",))["createPet"]
    request = build_request(binding, {"name": "Tom", "tag": "cat"})
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content or b"") == {"name": "Tom", "tag": "cat"}


def _body_binding(media_type: str) -> OperationBinding:
    return OperationBinding(
        operation_key="POST /x",
        method="POST",
        path_template="/x",
        body_mode="flat",
        body_required=True,
        body_media_type=media_type,
    )


def test_a_form_body_is_url_encoded() -> None:
    request = build_request(_body_binding("application/x-www-form-urlencoded"), {"a": "1 2", "b": ["x", "y"]})
    assert request.content == b"a=1%202&b=x&b=y"


def test_a_multipart_body_has_one_part_per_field() -> None:
    request = build_request(_body_binding("multipart/form-data"), {"name": "Tom"})
    content_type = request.headers["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1]
    assert request.content == (
        f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\nTom\r\n--{boundary}--\r\n'.encode()
    )


def test_a_text_body_is_sent_as_is() -> None:
    binding = OperationBinding(
        operation_key="POST /x",
        method="POST",
        path_template="/x",
        body_mode="nested",
        body_media_type="text/plain",
    )
    assert build_request(binding, {"body": "hello"}).content == b"hello"


def test_an_optional_flat_body_with_no_fields_sends_nothing() -> None:
    binding = OperationBinding(
        operation_key="POST /x", method="POST", path_template="/x", body_mode="flat", body_media_type="application/json"
    )
    request = build_request(binding, {})
    assert request.content is None
    assert "Content-Type" not in request.headers


# ============================================================================
# Servers
# ============================================================================


def _api(*servers: Server) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST, format="openapi", identity=ApiIdentity(name="x"), servers=list(servers)
    )


def test_server_variables_take_their_defaults() -> None:
    server = Server(
        url="https://{region}.example.com/{base}/",
        variables=[ServerVariable(name="region", default="eu"), ServerVariable(name="base", enum=["v2", "v3"])],
    )
    assert resolve_server_url(_api(server)) == "https://eu.example.com/v2"


def test_the_first_absolute_server_wins_and_relative_ones_are_skipped() -> None:
    assert (
        resolve_server_url(_api(Server(url="/v1"), Server(url="https://api.example.com"))) == "https://api.example.com"
    )
    assert resolve_server_url(_api(Server(url="/v1"))) is None
    assert resolve_server_url(_api()) is None


def test_the_url_joins_base_path_and_query() -> None:
    binding = _bindings(PETSTORE, ("GET /pets",))["listPets"]
    assert (
        build_request(binding, {"limit": 2}).url("https://api.example.com/v1/")
        == "https://api.example.com/v1/pets?limit=2"
    )
