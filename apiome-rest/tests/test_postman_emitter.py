"""Postman Collection v2.1 emitter — MFX-31.1 (#4289).

Covers, in order:

* schema validity: every export validates against the vendored Postman v2.1.0 JSON Schema, and the
  validator rejects what the schema or the reader rejects;
* folders: ``auto`` (tag, else service when there are several), ``tag``, ``service``, ``flat``,
  nested tags, and a Postman source's own tree;
* variables: servers as ``{{baseUrl}}`` / ``{{baseUrl2}}``, server template variables, ``inline``,
  credential variables declared empty;
* requests: ``:param`` path variables, query and headers, example bodies synthesized from the schema
  (``minimal`` / ``full``), never the schema itself;
* saved example responses, status ranges;
* auth: collection-level when shared, per request otherwise, credentials as references only;
* options, refusal, fidelity, emitted-output validation;
* the acceptance check: every Postman corpus collection round-trips unchanged and reports nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    ServerVariable,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitOptions, EmitOptionsError, EmitResult
from app.export_service import ExportError, emit_canonical
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind
from app.postman_emitter import PostmanEmitOptions, PostmanEmitter, validate_postman_collection
from app.postman_import_source import PostmanImportSource
from app.postman_parser import parse_postman
from app.roundtrip_matrix import reimport_emitted

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


# ===========================================================================
# Helpers
# ===========================================================================


def _pet() -> Type:
    return Type(key="Pet", name="Pet", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Pet.id", name="id", type=TypeRef(name="i64", nullable=False), field_number=1),
        CanonicalField(key="Pet.name", name="name", type=TypeRef(name="string", nullable=False), field_number=2),
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"), field_number=3),
    ])


def _op(method: str, path: str, *, name: str | None = None, **kw) -> Operation:
    return Operation(key=f"{method} {path}", name=name or f"{method} {path}", kind=OperationKind.REQUEST_RESPONSE,
                     http_method=method, http_path=path, **kw)


def _pets_ops(**extras) -> List[Operation]:
    list_pets = _op(
        "GET", "/pets", name="List pets", tags=["Pets"],
        parameters=[Parameter(key="GET /pets#query.limit", name="limit", location=ParameterLocation.QUERY,
                              type=TypeRef(name="i32"), default=20)],
        messages=[Message(key="GET /pets#response.200", role=MessageRole.RESPONSE, status_code="200",
                          payload=TypeRef(item=TypeRef(name="Pet")), content_types=["application/json"])],
        extras=dict(extras),
    )
    get_pet = _op(
        "GET", "/pets/{petId}", name="Get a pet", tags=["Pets"],
        parameters=[Parameter(key="GET /pets/{petId}#path.petId", name="petId", location=ParameterLocation.PATH,
                              type=TypeRef(name="string"), required=True, default="p-1")],
        messages=[Message(key="GET /pets/{petId}#response.200", role=MessageRole.RESPONSE, status_code="200",
                          payload=TypeRef(name="Pet"), content_types=["application/json"]),
                  Message(key="GET /pets/{petId}#response.4XX", role=MessageRole.RESPONSE, status_code="4XX")],
        extras=dict(extras),
    )
    add_pet = _op(
        "POST", "/pets", name="Add a pet",
        messages=[Message(key="POST /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"),
                          content_types=["application/json"]),
                  Message(key="POST /pets#response.201", role=MessageRole.RESPONSE, status_code="201",
                          payload=TypeRef(name="Pet"), content_types=["application/json"])],
        extras=dict(extras),
    )
    return [list_pets, get_pet, add_pet]


def _api(*, operations: List[Operation] | None = None, services: List[Service] | None = None, **kw) -> CanonicalApi:
    defaults: Dict[str, Any] = dict(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Pets"),
        title="Pets",
        version="1.2.0",
        description="The pet store.",
        servers=[Server(url="https://pets.example.com/v1")],
        services=services or [Service(key="default", name="default", operations=operations or _pets_ops())],
        types=[_pet()],
    )
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _emit(api: CanonicalApi, **opts) -> EmitResult:
    return PostmanEmitter().emit(api, opts=PostmanEmitOptions(**opts) if opts else None)


def _doc(result: EmitResult) -> Dict[str, Any]:
    return json.loads(result.files[0].content)


def _requests(document: Dict[str, Any], folder: tuple = ()) -> Dict[str, tuple]:
    """Request name → the folder path it sits in."""
    out: Dict[str, tuple] = {}
    for item in document["item"]:
        if "item" in item:
            out.update(_requests(item, folder + (item["name"],)))
        else:
            out[item["name"]] = folder
    return out


def _item(document: Dict[str, Any], name: str) -> Dict[str, Any]:
    for item in document["item"]:
        if "item" in item:
            try:
                return _item(item, name)
            except KeyError:
                continue
        elif item["name"] == name:
            return item
    raise KeyError(name)


def _variables(document: Dict[str, Any]) -> Dict[str, Any]:
    return {entry["key"]: entry["value"] for entry in document.get("variable", [])}


def _subjects(result: EmitResult) -> set:
    return {loss.subject for loss in result.losses}


def _corpus_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".yaml": "openapi", ".graphql": "graphql", ".raml": "raml", ".json": "postman", ".http": "http-file"}
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt[path.suffix],
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


# ===========================================================================
# Schema validity
# ===========================================================================


def test_the_export_validates_against_the_v2_1_schema() -> None:
    result = _emit(_api())
    validate_postman_collection(result.files[0].content)
    document = _doc(result)
    assert document["info"]["schema"] == "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    assert document["info"]["description"] == "The pet store." and document["info"]["version"] == "1.2.0"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "not JSON"),
        (json.dumps({"item": []}), "v2.1.0 schema"),  # info is required
        (json.dumps({"info": {"name": "x", "schema": "s"}, "item": [{"request": {"method": 7}}]}), "v2.1.0 schema"),
    ],
)
def test_the_validator_rejects_what_the_schema_rejects(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_postman_collection(text)


# ===========================================================================
# Folders
# ===========================================================================


def test_auto_files_by_first_tag_and_keeps_untagged_requests_at_the_root_of_a_one_service_api() -> None:
    folders = _requests(_doc(_emit(_api())))
    assert folders == {"List pets": ("Pets",), "Get a pet": ("Pets",), "Add a pet": ()}


def test_auto_falls_back_to_the_service_when_there_are_several() -> None:
    ops = _pets_ops()
    services = [Service(key="pets", name="Pets service", operations=ops[:2]),
                Service(key="admin", name="Admin", operations=[_op("GET", "/health", name="Health")])]
    folders = _requests(_doc(_emit(_api(services=services))))
    assert folders["Health"] == ("Admin",) and folders["List pets"] == ("Pets",)


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("tag", {"List pets": ("Pets",), "Get a pet": ("Pets",), "Add a pet": ()}),
        ("service", {"List pets": ("default",), "Get a pet": ("default",), "Add a pet": ("default",)}),
        ("flat", {"List pets": (), "Get a pet": (), "Add a pet": ()}),
    ],
)
def test_folder_strategies(strategy: str, expected: Dict[str, tuple]) -> None:
    assert _requests(_doc(_emit(_api(), folder_strategy=strategy))) == expected


def test_folder_paths_nest() -> None:
    ops = [_op("GET", "/usage", name="Usage", tags=["Admin / Reports"]), _op("GET", "/audit", name="Audit",
                                                                              tags=["Admin"])]
    document = _doc(_emit(_api(operations=ops)))
    assert _requests(document) == {"Usage": ("Admin", "Reports"), "Audit": ("Admin",)}
    assert [item["name"] for item in document["item"]] == ["Admin"]


# ===========================================================================
# Variables
# ===========================================================================


def test_servers_and_their_template_variables_become_collection_variables() -> None:
    servers = [
        Server(url="https://{region}.pets.example.com", variables=[ServerVariable(name="region", default="eu")]),
        Server(url="https://staging.pets.example.com", description="Staging"),
    ]
    document = _doc(_emit(_api(servers=servers)))
    assert _variables(document) == {
        "baseUrl": "https://{{region}}.pets.example.com",
        "region": "eu",
        "baseUrl2": "https://staging.pets.example.com",
    }
    url = _item(document, "List pets")["request"]["url"]
    assert (url["raw"], url["host"]) == ("{{baseUrl}}/pets", ["{{baseUrl}}"])  # the disabled query is not sent


def test_inline_writes_the_literal_server_and_declares_no_base_variable() -> None:
    result = _emit(_api(), variable_style="inline")
    document = _doc(result)
    url = _item(document, "Get a pet")["request"]["url"]
    assert url["raw"] == "https://pets.example.com/v1/pets/:petId"
    assert (url["protocol"], url["host"]) == ("https", ["pets", "example", "com"])
    assert url["path"] == ["v1", "pets", ":petId"]
    assert "baseUrl" not in _variables(document)
    validate_postman_collection(result.files[0].content)


def test_inline_reports_servers_beyond_the_first() -> None:
    api = _api(servers=[Server(url="https://a.example.com"), Server(url="https://b.example.com")])
    assert "additional-servers" in _subjects(_emit(api, variable_style="inline"))
    assert "additional-servers" not in _subjects(_emit(api))


# ===========================================================================
# Requests
# ===========================================================================


def test_path_query_and_header_values() -> None:
    document = _doc(_emit(_api()))
    url = _item(document, "Get a pet")["request"]["url"]
    assert url["path"] == ["pets", ":petId"] and url["variable"] == [{"key": "petId", "value": "p-1"}]
    query = _item(document, "List pets")["request"]["url"]["query"]
    assert query == [{"key": "limit", "value": "20", "disabled": True}]  # optional: saved, not sent


def test_the_request_body_is_an_example_synthesized_from_the_schema_not_the_schema() -> None:
    body = _item(_doc(_emit(_api())), "Add a pet")["request"]["body"]
    assert body["mode"] == "raw" and body["options"] == {"raw": {"language": "json"}}
    example = json.loads(body["raw"])
    assert set(example) == {"id", "name"}  # minimal: required properties only
    assert isinstance(example["id"], int) and isinstance(example["name"], str)
    assert "type" not in example and "properties" not in example


def test_full_example_depth_fills_every_property() -> None:
    body = _item(_doc(_emit(_api(), example_depth="full")), "Add a pet")["request"]["body"]
    assert set(json.loads(body["raw"])) == {"id", "name", "tag"}


def test_a_form_body_is_written_as_fields() -> None:
    op = _op("POST", "/login", name="Log in", messages=[
        Message(key="POST /login#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"),
                content_types=["application/x-www-form-urlencoded"])])
    body = _item(_doc(_emit(_api(operations=[op]))), "Log in")["request"]["body"]
    assert body["mode"] == "urlencoded" and {f["key"] for f in body["urlencoded"]} == {"id", "name"}


# ===========================================================================
# Saved example responses
# ===========================================================================


def test_responses_become_saved_examples_synthesized_from_their_schemas() -> None:
    document = _doc(_emit(_api()))
    responses = _item(document, "List pets")["response"]
    assert [(r["code"], r["status"]) for r in responses] == [(200, "OK")]
    assert isinstance(json.loads(responses[0]["body"]), list)
    assert responses[0]["header"] == [{"key": "Content-Type", "value": "application/json"}]
    assert responses[0]["originalRequest"]["url"]["raw"].startswith("{{baseUrl}}/pets")


def test_a_status_range_is_not_saved_and_is_reported() -> None:
    result = _emit(_api())
    assert [r["code"] for r in _item(_doc(result), "Get a pet")["response"]] == [200]
    assert {"status-range-response", "example-response-synthesized"} <= _subjects(result)
    assert "responses-not-carried" not in _subjects(result)


# ===========================================================================
# Auth
# ===========================================================================


def test_shared_auth_is_written_once_on_the_collection_with_credential_references() -> None:
    result = _emit(_api(operations=_pets_ops(security=["bearer"])))
    document = _doc(result)
    assert document["auth"] == {"type": "bearer", "bearer": [{"key": "token", "value": "{{accessToken}}",
                                                              "type": "string"}]}
    assert "auth" not in _item(document, "List pets")["request"]
    assert _variables(document)["accessToken"] == ""


def test_differing_auth_is_written_per_request() -> None:
    ops = _pets_ops()
    ops[0] = ops[0].model_copy(update={"extras": {"security": ["apiKey"]}})
    ops[2] = ops[2].model_copy(update={"extras": {"security": ["basic"]}})
    document = _doc(_emit(_api(operations=ops)))
    assert "auth" not in document
    apikey = _item(document, "List pets")["request"]["auth"]
    assert apikey["type"] == "apikey"
    assert {e["key"]: e["value"] for e in apikey["apikey"]} == {"key": "X-API-Key", "value": "{{apiKey}}",
                                                                "in": "header"}
    basic = _item(document, "Add a pet")["request"]["auth"]
    assert {e["key"]: e["value"] for e in basic["basic"]} == {"username": "{{username}}", "password": "{{password}}"}
    assert "auth" not in _item(document, "Get a pet")["request"]


def test_no_secret_value_is_ever_written() -> None:
    op = _op("GET", "/me", name="Me", parameters=[
        Parameter(key="GET /me#header.X-Api-Token", name="X-Api-Token", location=ParameterLocation.HEADER,
                  type=TypeRef(name="string"), required=True, default="sk_live_123456789")])
    result = _emit(_api(operations=[op]))
    assert "sk_live_123456789" not in result.files[0].content
    header = _item(_doc(result), "Me")["request"]["header"][0]
    assert header["value"].startswith("{{") and _variables(_doc(result))[header["value"][2:-2]] == ""


# ===========================================================================
# Options, refusal, fidelity, validation
# ===========================================================================


class _BadOptions(EmitOptions):
    folder_strategy: str = "by-color"


def test_invalid_options_are_refused() -> None:
    with pytest.raises(EmitOptionsError):
        PostmanEmitter().emit(_api(), opts=_BadOptions())


def test_a_source_with_no_http_operation_is_refused() -> None:
    api = _api(operations=[Operation(key="rpc", name="rpc", kind=OperationKind.REQUEST_RESPONSE)])
    with pytest.raises(ExportError) as excinfo:
        emit_canonical(api, "postman")
    assert excinfo.value.status_code == 422


def test_fidelity_for_another_format() -> None:
    kinds = {item.construct_key: item.kind for item in compute_lossiness_for_emitter(_api(), PostmanEmitter()).items}
    assert kinds[""] is LossinessKind.APPROX
    assert kinds["GET /pets"] is LossinessKind.APPROX
    assert kinds["Pet"] is LossinessKind.DROP


async def test_emitted_output_validation() -> None:
    api = _api()
    result = _emit(api)
    verdict = await validate_emitted_artifact("postman", result, api=api)
    assert verdict.validated and verdict.valid, verdict.errors
    broken = result.model_copy(update={"files": [result.files[0].model_copy(update={"content": "{}"})]})
    assert (await validate_emitted_artifact("postman", broken, api=api)).failed


def test_the_reader_reads_a_string_response_body() -> None:
    text = json.dumps({
        "info": {"name": "R", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": [{"name": "Get", "request": {"method": "GET", "url": "https://x.example.com/a"},
                  "response": [{"name": "OK", "code": 200, "body": "{\"a\": 1}"}]}],
    })
    response = parse_postman(text).operations[0].responses[0]
    assert response.body is not None and response.body.raw == "{\"a\": 1}"


# ===========================================================================
# Acceptance: Postman round trips; other formats export to valid collections
# ===========================================================================

_POSTMAN_CORPUS = sorted((_EXAMPLES / "postman").glob("*.json"))


@pytest.mark.parametrize("path", _POSTMAN_CORPUS, ids=lambda p: p.name)
def test_postman_corpus_round_trips_and_reports_nothing(path: Path) -> None:
    api = _corpus_api(path)
    result = _emit(api)
    validate_postman_collection(result.files[0].content)
    assert result.losses == []
    assert canonical_diff(api, reimport_emitted(PostmanImportSource(), result, multi_file=False)).entries == []
    report = compute_lossiness_for_emitter(api, PostmanEmitter())
    assert all(item.kind is LossinessKind.OK for item in report.items)


def test_a_postman_source_keeps_its_folder_tree() -> None:
    api = _corpus_api(_EXAMPLES / "postman" / "04-folders-and-variables.postman_collection.json")
    folders = _requests(_doc(_emit(api)))
    assert folders["Usage report"] == ("Admin", "Reports") and folders["List users"] == ("Users",)


_CORPUS = [
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "raml" / "01-simple-api.raml",
]


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
@pytest.mark.parametrize("style", ["variables", "inline"])
@pytest.mark.parametrize("depth", ["minimal", "full"])
def test_corpus_exports_validate(path: Path, style: str, depth: str) -> None:
    api = _corpus_api(path)
    try:
        result = _emit(api, variable_style=style, example_depth=depth)
    except ValueError:
        pytest.skip("the source has no HTTP operation")
    validate_postman_collection(result.files[0].content)
