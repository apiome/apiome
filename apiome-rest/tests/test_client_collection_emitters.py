"""Tests for the Hoppscotch and Thunder Client emit modes — FMT-10.4 (#5479).

Exercises the ticket's acceptance criteria:

* **Both formats emit and re-import to an equivalent canonical model** — every valid Hoppscotch and
  Thunder Client corpus fixture is imported, emitted to *both* clients and re-imported, and its call
  surface (operation keys, parameters with location and requiredness, folder tags, security scheme,
  body media types, title and servers with their defaults) is asserted identical. The one inherent
  difference — Thunder Client has no API-key auth type — is asserted to be reported as a loss.
* **No credential value is ever emitted** — a model laden with credential-shaped defaults, samples,
  body examples and a server userinfo is emitted and none of them is found in either file; every
  credential is a variable reference the environment declares empty (and, in Hoppscotch, secret).
* **Round-trip matrix rows exist for both** — the native and cross-client cells run through the
  same :func:`app.roundtrip_matrix.run_roundtrip` the matrix uses and pass.
* **Export Studio cards** — both targets are enumerated by the registry the Studio reads, with a
  capability profile, a fidelity rule pack and a post-emit validation gate.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest
from corpus_adapter_support import valid_entries
from corpus_roundtrip import _import_entry

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Channel,
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
from app.client_collection_emit import (
    BASE_URL_VARIABLE,
    ClientCollectionFidelityRulePack,
    plan_collection,
)
from app.emitter import (
    EmitOptionsError,
    coerce_emit_options,
    describe_emit_targets,
    get_emitter,
    load_builtin_emitters,
)
from app.export_validation import validate_emitted_artifact
from app.hoppscotch_emitter import HOPPSCOTCH_AUTH_BLOCKS, HoppscotchEmitter, validate_hoppscotch_export
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind
from app.roundtrip_matrix import production_emit_targets, reimport_emitted, run_roundtrip
from app.thunder_client_emitter import ThunderClientEmitter, validate_thunder_client_export

TARGETS: Tuple[str, ...] = ("hoppscotch", "thunder-client")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_import_sources()
    load_builtin_emitters()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def client_entries() -> List[Any]:
    """Every valid Hoppscotch and Thunder Client corpus entry."""
    return [entry for entry in valid_entries() if entry.format in TARGETS]


def emit(api: CanonicalApi, target: str) -> Any:
    """Emit ``api`` through the registered ``target`` emitter."""
    return get_emitter(target)().emit(api)


def reimport(result: Any, target: str) -> CanonicalApi:
    """Re-import an emitted collection + environment through ``target``'s import adapter."""
    return reimport_emitted(get_import_source(target), result, multi_file=True, source_label="emitted")


def files(result: Any) -> Dict[str, Any]:
    """The emitted files, parsed, keyed by path."""
    return {emitted.path: json.loads(emitted.content) for emitted in result.files}


def all_text(result: Any) -> str:
    """Every emitted byte, joined."""
    return "\n".join(emitted.content for emitted in result.files)


def surface(api: CanonicalApi) -> Dict[str, Any]:
    """The call surface a client collection carries."""
    operations = {}
    for service in api.services:
        for operation in service.operations:
            operations[operation.key] = {
                "parameters": sorted((p.location.value, p.name, p.required) for p in operation.parameters),
                "tags": operation.tags,
                "security": operation.extras.get("security"),
                "content_types": [m.content_types for m in operation.messages if m.role is MessageRole.REQUEST],
            }
    return {
        "title": api.title,
        "servers": [(server.url, [(v.name, v.default) for v in server.variables]) for server in api.servers],
        "operations": operations,
    }


def param(op_key: str, name: str, location: ParameterLocation, *, required: bool = True, **extra: Any) -> Parameter:
    """One string parameter."""
    return Parameter(
        key=f"{op_key}#{location.value}.{name}",
        name=name,
        location=location,
        type=TypeRef(name="string"),
        required=required,
        **extra,
    )


def operation(
    key: str,
    *,
    parameters: Optional[List[Parameter]] = None,
    messages: Optional[List[Message]] = None,
    tags: Optional[List[str]] = None,
    extras: Optional[Dict[str, Any]] = None,
    kind: OperationKind = OperationKind.REQUEST_RESPONSE,
) -> Operation:
    """One HTTP operation keyed ``METHOD /path``."""
    method, path = key.split(" ", 1)
    return Operation(
        key=key,
        name=key,
        kind=kind,
        http_method=method,
        http_path=path,
        parameters=parameters or [],
        messages=messages or [],
        tags=tags or [],
        extras=extras or {},
    )


def model(
    operations: List[Operation],
    *,
    servers: Optional[List[Server]] = None,
    types: Optional[List[Type]] = None,
    channels: Optional[List[Channel]] = None,
    extras: Optional[Dict[str, Any]] = None,
    title: str = "Widgets API",
) -> CanonicalApi:
    """A small cross-format (OpenAPI-shaped) model."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi",
        protocol="http",
        identity=ApiIdentity(name=title),
        title=title,
        description="Widgets, end to end.",
        servers=servers if servers is not None else [Server(url="https://api.example.com/v1")],
        services=[Service(key="widgets", name="widgets", operations=operations)],
        types=types or [],
        channels=channels or [],
        extras=extras or {},
    )


def json_body(schema: Dict[str, Any], content_types: Optional[List[str]] = None) -> Message:
    """A request message with an inline JSON Schema payload."""
    return Message(
        key="request",
        role=MessageRole.REQUEST,
        payload_schema=schema,
        content_types=content_types or ["application/json"],
    )


# ---------------------------------------------------------------------------
# Registration and the Export Studio card
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_emitter_is_registered_under_the_import_adapter_key(target: str) -> None:
    emitter = get_emitter(target)
    assert emitter is not None and emitter.key == target and emitter.format == target
    assert get_import_source(target) is not None, "the round-trip matrix joins emit and import by key"


@pytest.mark.parametrize("target", TARGETS)
def test_target_is_enumerated_for_the_export_studio(target: str) -> None:
    targets = {item.descriptor.key: item for item in describe_emit_targets()}
    card = targets[target]
    assert card.descriptor.paradigm == ApiParadigm.REST.value
    assert card.descriptor.multi_file is True
    assert card.descriptor.needs_toolchain is False
    profile = card.capability_profile
    assert (profile.operations, profile.events, profile.unions) == (True, False, False)
    assert (profile.nullability, profile.constraints, profile.field_identity) == (False, False, False)
    assert set(card.options_schema["properties"]) == {"indent"}


@pytest.mark.parametrize("target", TARGETS)
def test_target_is_a_production_round_trip_column(target: str) -> None:
    assert target in {item.descriptor.key for item in production_emit_targets()}


@pytest.mark.parametrize("target", TARGETS)
def test_invalid_options_are_an_emit_options_error(target: str) -> None:
    with pytest.raises(EmitOptionsError):
        coerce_emit_options(get_emitter(target), {"indent": "x"})


@pytest.mark.parametrize("target", TARGETS)
def test_compact_indent_writes_single_line_json(target: str) -> None:
    emitter = get_emitter(target)
    result = emitter().emit(model([operation("GET /widgets")]), opts=coerce_emit_options(emitter, {"indent": 0}))
    for emitted in result.files:
        assert emitted.content.count("\n") == 1


# ---------------------------------------------------------------------------
# Equivalent canonical model (round trip)
# ---------------------------------------------------------------------------


def test_the_corpus_has_fixtures_for_both_clients() -> None:
    formats = {entry.format for entry in client_entries()}
    assert formats == set(TARGETS)


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("entry", client_entries(), ids=lambda entry: entry.path)
def test_every_client_fixture_re_imports_to_the_same_call_surface(entry: Any, target: str) -> None:
    source = _import_entry(entry)
    result = emit(source, target)
    back = reimport(result, target)
    expected = surface(source)
    actual = surface(back)
    if target == "thunder-client":
        # Thunder Client has no API-key auth type: the key is saved as the parameter a Thunder user
        # writes, which re-imports as a parameter. That is the one inherent difference, and it must
        # be reported rather than hidden.
        for key, details in expected["operations"].items():
            if details["security"] != ["apiKey"]:
                continue
            assert any(loss.subject == "auth-as-parameter" and loss.pointer == key for loss in result.losses)
            got = actual["operations"][key]
            added = [item for item in got["parameters"] if item not in details["parameters"]]
            assert got["security"] is None and len(added) == 1 and "api" in added[0][1].lower()
            got["parameters"], got["security"] = details["parameters"], details["security"]
    assert actual == expected


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("source_format", TARGETS)
def test_native_and_cross_client_matrix_cells_pass(source_format: str, target: str) -> None:
    from corpus_roundtrip import representatives_by_format

    entry = representatives_by_format()[source_format]
    columns = {item.descriptor.key: item for item in production_emit_targets()}
    cell = run_roundtrip(_import_entry(entry), columns[target], source_format=source_format, corpus_path=entry.path)
    assert cell.status.value == "pass", cell.reason


def test_a_cross_format_source_keeps_its_operations_and_base_url() -> None:
    api = model(
        [
            operation(
                "GET /widgets/{id}",
                parameters=[
                    param("GET /widgets/{id}", "id", ParameterLocation.PATH, default="w-1"),
                    param("GET /widgets/{id}", "expand", ParameterLocation.QUERY, required=False),
                    param("GET /widgets/{id}", "X-Request-Id", ParameterLocation.HEADER),
                ],
                tags=["Catalogue / Widgets"],
            ),
            operation("POST /widgets", messages=[json_body({"type": "object", "properties": {}})]),
        ]
    )
    for target in TARGETS:
        back = reimport(emit(api, target), target)
        operations = {op.key: op for service in back.services for op in service.operations}
        assert set(operations) == {"GET /widgets/{id}", "POST /widgets"}
        assert operations["GET /widgets/{id}"].tags == ["Catalogue / Widgets"]
        names = {(p.location, p.name) for p in operations["GET /widgets/{id}"].parameters}
        assert (ParameterLocation.PATH, "id") in names
        assert (ParameterLocation.QUERY, "expand") not in names, "optional parameters are saved disabled"
        assert back.servers[0].url == "{baseUrl}"
        assert back.servers[0].variables[0].default == "https://api.example.com/v1"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_hoppscotch_writes_folders_variables_and_disabled_optional_params() -> None:
    api = model(
        [
            operation(
                "GET /widgets/{id}",
                parameters=[
                    param("GET /widgets/{id}", "id", ParameterLocation.PATH, default="w-1"),
                    param("GET /widgets/{id}", "expand", ParameterLocation.QUERY, required=False, default="parts"),
                ],
                tags=["Catalogue / Widgets"],
            )
        ]
    )
    documents = files(emit(api, "hoppscotch"))
    collection = documents["Widgets_API.hoppscotch_collection.json"]
    environment = documents["Widgets_API.hoppscotch_environment.json"]
    assert collection["v"] == 6 and collection["name"] == "Widgets API"
    folder = collection["folders"][0]["folders"][0]
    assert (collection["folders"][0]["name"], folder["name"]) == ("Catalogue", "Widgets")
    request = folder["requests"][0]
    assert request["endpoint"] == "<<baseUrl>>/widgets/<<id>>"
    assert request["requestVariables"] == [{"key": "id", "value": "w-1", "active": True}]
    assert request["params"] == [{"key": "expand", "value": "parts", "active": False, "description": ""}]
    assert environment["variables"][0] == {
        "key": BASE_URL_VARIABLE,
        "initialValue": "https://api.example.com/v1",
        "currentValue": "https://api.example.com/v1",
        "secret": False,
    }


def test_thunder_client_writes_a_flat_folder_tree_and_colon_path_params() -> None:
    api = model(
        [
            operation(
                "GET /widgets/{id}/parts/{part}.json",
                parameters=[
                    param("GET /widgets/{id}/parts/{part}.json", "id", ParameterLocation.PATH),
                    param("GET /widgets/{id}/parts/{part}.json", "part", ParameterLocation.PATH),
                    param("GET /widgets/{id}/parts/{part}.json", "page", ParameterLocation.QUERY, default="2"),
                ],
                tags=["Catalogue / Widgets"],
            )
        ]
    )
    documents = files(emit(api, "thunder-client"))
    collection = documents["thunder-collection_Widgets_API.json"]
    environment = documents["thunder-environment_Widgets_API.json"]
    assert collection["clientName"] == "Thunder Client" and collection["collectionName"] == "Widgets API"
    parent, child = collection["folders"]
    assert (parent["name"], parent["containerId"]) == ("Catalogue", "")
    assert (child["name"], child["containerId"]) == ("Widgets", parent["_id"])
    request = collection["requests"][0]
    assert request["containerId"] == child["_id"] and request["colId"] == collection["collectionId"]
    # A whole segment is Thunder's `:name`; a parameter inside a segment is a `{{name}}` reference.
    assert request["url"] == "{{baseUrl}}/widgets/:id/parts/{{part}}.json?page=2"
    assert {"name": "id", "value": "", "isPath": True} in request["params"]
    assert environment["data"][0] == {"name": "baseUrl", "value": "https://api.example.com/v1"}


@pytest.mark.parametrize("target", TARGETS)
def test_output_is_deterministic(target: str) -> None:
    api = model([operation("GET /widgets", tags=["A"]), operation("DELETE /widgets/{id}", tags=["A / B"])])
    assert all_text(emit(api, target)) == all_text(emit(api, target))


@pytest.mark.parametrize("target", TARGETS)
def test_a_model_with_no_http_operation_refuses_to_emit(target: str) -> None:
    rpc = Operation(key="GetWidget", name="GetWidget", kind=OperationKind.REQUEST_RESPONSE)
    with pytest.raises(ValueError, match="at least one HTTP operation"):
        emit(model([rpc]), target)


@pytest.mark.parametrize("target", TARGETS)
def test_an_operation_with_two_body_media_types_is_saved_once_per_type(target: str) -> None:
    schema = {"type": "object", "required": ["label"], "properties": {"label": {"type": "string", "example": "a"}}}
    api = model(
        [
            operation(
                "POST /samples", messages=[json_body(schema, ["application/json", "application/x-www-form-urlencoded"])]
            )
        ]
    )
    result = emit(api, target)
    back = reimport(result, target)
    message = next(m for m in back.services[0].operations[0].messages if m.role is MessageRole.REQUEST)
    assert message.content_types == ["application/json", "application/x-www-form-urlencoded"]


# ---------------------------------------------------------------------------
# Auth placeholders — no credential value is ever emitted
# ---------------------------------------------------------------------------

#: Credential-shaped values planted in the leaky model; none may reach an emitted byte.
PLANTED = (
    "sk_live_51HxQ2eC0ffeeBeefCafe",
    "hunter2-correct-horse",
    "tok_9f8e7d6c5b4a39281706",
    "s3cr3t-userinfo-pw",
    "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
)


@pytest.fixture()
def leaky_api() -> CanonicalApi:
    """A model whose defaults, samples, body example and server all carry credentials."""
    key = "POST /login"
    return model(
        [
            operation(
                key,
                parameters=[
                    param(key, "X-API-Key", ParameterLocation.HEADER, default=PLANTED[0]),
                    param(key, "access_token", ParameterLocation.QUERY, extras={"samples": [PLANTED[2]]}),
                    param(key, "Authorization", ParameterLocation.HEADER, default=f"Bearer {PLANTED[4]}"),
                ],
                messages=[
                    json_body(
                        {
                            "type": "object",
                            "required": ["user", "password", "nested"],
                            "properties": {
                                "user": {"type": "string", "example": "ada"},
                                "password": {"type": "string", "example": PLANTED[1]},
                                "nested": {
                                    "type": "object",
                                    "required": ["client_secret"],
                                    "properties": {"client_secret": {"type": "string", "example": PLANTED[4]}},
                                },
                            },
                        }
                    )
                ],
                extras={"security": ["bearer"]},
            )
        ],
        servers=[Server(url=f"https://admin:{PLANTED[3]}@api.example.com")],
    )


@pytest.mark.parametrize("target", TARGETS)
def test_no_planted_credential_reaches_either_file(leaky_api: CanonicalApi, target: str) -> None:
    text = all_text(emit(leaky_api, target))
    for planted in PLANTED:
        assert planted not in text
    assert "admin" not in text, "userinfo is a credential and is stripped from the base URL"


@pytest.mark.parametrize("target", TARGETS)
def test_every_credential_is_a_declared_empty_variable(leaky_api: CanonicalApi, target: str) -> None:
    result = emit(leaky_api, target)
    documents = files(result)
    environment = next(document for path, document in documents.items() if "environment" in path)
    if target == "hoppscotch":
        variables = {item["key"]: item for item in environment["variables"]}
        secrets = {name for name, item in variables.items() if item["secret"]}
        assert all(variables[name]["initialValue"] == variables[name]["currentValue"] == "" for name in secrets)
        reference = "<<{}>>"
    else:
        variables = {item["name"]: item for item in environment["data"]}
        secrets = {name for name, item in variables.items() if name != BASE_URL_VARIABLE}
        assert all(variables[name]["value"] == "" for name in secrets)
        reference = "{{{{{}}}}}"
    assert {"accessToken", "xApiKey", "access_token", "password", "client_secret"} <= secrets
    text = all_text(result)
    for name in secrets:
        assert reference.format(name) in text, f"{name} is declared but never referenced"


def test_the_auth_header_is_not_repeated_beside_the_auth_block(leaky_api: CanonicalApi) -> None:
    collection = next(d for p, d in files(emit(leaky_api, "hoppscotch")).items() if "collection" in p)
    request = collection["requests"][0]
    assert all(header["key"].lower() != "authorization" for header in request["headers"])
    assert collection["auth"] == {"authType": "bearer", "authActive": True, "token": "<<accessToken>>"}
    assert request["auth"] == {"authType": "inherit", "authActive": True}


AUTH_CASES = [
    ("bearer", {}, "bearer"),
    ("basic", {}, "basic"),
    ("digest", {}, "digest"),
    ("oauth2", {}, "oauth2"),
    ("openIdConnect", {}, "bearer"),
    ("authorization", {}, None),
    ("cookie", {}, None),
]


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("scheme,record,expected", AUTH_CASES)
def test_each_scheme_re_imports_to_the_scheme_it_was_written_as(
    target: str, scheme: str, record: Dict[str, Any], expected: Optional[str]
) -> None:
    api = model([operation("GET /secure", extras={"security": [scheme]}), operation("GET /open")])
    back = reimport(emit(api, target), target)
    operations = {op.key: op for service in back.services for op in service.operations}
    assert operations["GET /open"].extras.get("security") is None
    if expected is None:
        # No auth type of its own: written as the credential header, which the engine reads as an
        # observed scheme of the API rather than a requirement of the call.
        assert scheme in (back.extras.get("inferred_auth_schemes") or [])
    else:
        assert operations["GET /secure"].extras.get("security") == [expected]


def test_an_api_key_keeps_its_parameter_name_and_location() -> None:
    record = {"scheme": "apiKey", "in": "query", "name": "api_key", "type": "api-key", "declared_at": "request"}
    api = model([operation("GET /keyed", extras={"security": ["apiKey"], "hoppscotch_auth": [record]})])
    collection = next(d for p, d in files(emit(api, "hoppscotch")).items() if "collection" in p)
    assert collection["auth"]["key"] == "api_key" and collection["auth"]["addTo"] == "QUERY_PARAMS"
    thunder = next(d for p, d in files(emit(api, "thunder-client")).items() if "collection" in p)
    assert {"name": "api_key", "value": "{{apiKey}}", "isPath": False} in thunder["requests"][0]["params"]


def test_an_observed_scheme_only_rewrites_the_header_the_call_declares() -> None:
    key = "GET /me"
    api = model(
        [operation(key, parameters=[param(key, "Authorization", ParameterLocation.HEADER)]), operation("GET /ping")],
        extras={"inferred_auth_schemes": ["bearer"]},
    )
    for target, expected in (("hoppscotch", "Bearer <<accessToken>>"), ("thunder-client", "Bearer {{accessToken}}")):
        collection = next(d for p, d in files(emit(api, target)).items() if "collection" in p)
        requests = {request["name"]: request for request in collection["requests"]}
        values = [header.get("value") for header in requests[key]["headers"]]
        assert values == [expected]
        assert requests["GET /ping"]["headers"] == [], "an observation never adds auth to a call"


@pytest.mark.parametrize("target", TARGETS)
def test_an_unrepresentable_scheme_is_a_loss_not_a_guess(target: str) -> None:
    result = emit(model([operation("GET /mtls", extras={"security": ["mutualTLS"]})]), target)
    assert any(loss.subject == "unrepresentable-auth-scheme" for loss in result.losses)
    assert "mutualTLS" not in all_text(result)


def test_the_planner_hoists_shared_auth_and_keeps_mixed_auth_per_request() -> None:
    shared = model(
        [operation("GET /a", extras={"security": ["bearer"]}), operation("GET /b", extras={"security": ["bearer"]})]
    )
    plan = plan_collection(shared, target_label="Hoppscotch", auth_blocks=HOPPSCOTCH_AUTH_BLOCKS)
    assert plan.shared_auth is not None and plan.shared_auth.scheme == "bearer"
    mixed = model([operation("GET /a", extras={"security": ["bearer"]}), operation("GET /b")])
    assert plan_collection(mixed, target_label="Hoppscotch", auth_blocks=HOPPSCOTCH_AUTH_BLOCKS).shared_auth is None


# ---------------------------------------------------------------------------
# Losses and fidelity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_what_a_collection_cannot_carry_is_recorded(target: str) -> None:
    api = model(
        [
            operation(
                "GET /a",
                tags=["One", "Two"],
                parameters=[param("GET /a", "q", ParameterLocation.QUERY, required=False)],
            ),
            operation(
                "GET /b", messages=[Message(key="ok", role=MessageRole.RESPONSE, content_types=["application/json"])]
            ),
            operation("GET /c", parameters=[param("GET /c", "sid", ParameterLocation.COOKIE)]),
            operation("POST /d", messages=[json_body({"type": "string"}, ["application/xml"])]),
            operation("POST /events", kind=OperationKind.PUBLISH),
        ],
        servers=[Server(url="https://one.example.com"), Server(url="https://two.example.com")],
        types=[Type(key="Widget", name="Widget", kind=TypeKind.RECORD)],
        channels=[Channel(key="widget-events", name="widget-events", address="widget-events")],
    )
    subjects = {loss.subject for loss in emit(api, target).losses}
    assert {
        "additional-tags",
        "optional-parameters-disabled",
        "responses-not-carried",
        "cookie-parameters",
        "example-body-omitted",
        "event-operation",
        "additional-servers",
        "types-not-declared",
        "channels-dropped",
        "api-description",
    } <= subjects


def test_a_model_with_no_server_records_the_stand_in_base_url() -> None:
    result = emit(model([operation("GET /a")], servers=[]), "hoppscotch")
    assert any(loss.subject == "synthesized-base-url" for loss in result.losses)


def test_a_bare_template_server_keeps_its_variable_and_default() -> None:
    server = Server(url="{host}", variables=[ServerVariable(name="host", default="https://h.example.com")])
    collection, environment = files(emit(model([operation("GET /a")], servers=[server]), "hoppscotch")).values()
    assert collection["requests"][0]["endpoint"] == "<<host>>/a"
    assert environment["variables"][0]["key"] == "host"


@pytest.mark.parametrize("pack", [HoppscotchEmitter.fidelity_rule_pack(), ThunderClientEmitter.fidelity_rule_pack()])
def test_the_fidelity_pack_states_what_a_collection_loses(pack: type) -> None:
    assert issubclass(pack, ClientCollectionFidelityRulePack)
    instance = pack(HoppscotchEmitter.capability_profile())
    http = operation("GET /a")
    assert instance.operation_verdict(http).kind is LossinessKind.APPROX
    assert instance.operation_verdict(operation("POST /e", kind=OperationKind.PUBLISH)).kind is LossinessKind.DROP
    rpc = Operation(key="Rpc", name="Rpc", kind=OperationKind.REQUEST_RESPONSE)
    assert instance.operation_verdict(rpc).kind is LossinessKind.DROP
    assert instance.type_verdict(Type(key="T", name="T", kind=TypeKind.RECORD)).kind is LossinessKind.DROP
    assert instance.channel_verdict(Channel(key="c", name="c", address="c")).kind is LossinessKind.DROP
    assert [v.kind for v in instance.root_verdicts(model([http]))] == [LossinessKind.APPROX]
    native = model([http]).model_copy(update={"format": instance.format_key})
    assert instance.root_verdicts(native) == [], "a model from the same client keeps its root"


# ---------------------------------------------------------------------------
# Post-emit validation gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", TARGETS)
def test_the_export_gate_re_parses_the_emitted_pair(target: str) -> None:
    api = model([operation("GET /widgets")])
    verdict = asyncio.run(validate_emitted_artifact(target, emit(api, target), api=api))
    assert verdict.applicable and verdict.validated and verdict.valid and not verdict.failed


@pytest.mark.parametrize(
    "validator,target", [(validate_hoppscotch_export, "hoppscotch"), (validate_thunder_client_export, "thunder-client")]
)
def test_the_gate_rejects_a_broken_collection(validator: Any, target: str) -> None:
    result = emit(model([operation("GET /widgets")]), target)
    members = {emitted.path: emitted.content for emitted in result.files}
    collection = next(path for path in members if "collection" in path)
    members[collection] = members[collection][: len(members[collection]) // 2]
    with pytest.raises(ValueError):
        validator(members)
