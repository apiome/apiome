"""Thunder Client collection import — FMT-10.2 (#5475).

Covers the reader (:mod:`app.thunder_client_parser`), the normalizer
(:mod:`app.thunder_client_normalizer`) and the adapter (:mod:`app.thunder_client_import_source`)
against the acceptance criteria:

* a Thunder Client collection and environment import as **one API** — folders (rebuilt from
  ``containerId`` links), requests with method / URL / headers / params / body, and environment
  variables;
* the **same** inferred-spec engine and scrub gate as Hoppscotch (FMT-10.1);
* saved credentials are scrubbed and **never persisted** — neither in the canonical model nor in
  the source content the intake stores;
* the corpus (collections, an environment set, malformed files) is exercised by the shared corpus
  suites; the taxonomy codes are pinned here too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import CanonicalApi, MessageRole, ParameterLocation
from app.canonical_security import declared_security_schemes, operation_security_schemes
from app.fileset import IntakeFileset
from app.import_preview_manifest import build_import_preview_manifest
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.import_source_pipeline import _ResolvedIntake, scrub_intake_source
from app.inference_provenance import INFERRED, provenance_of
from app.thunder_client_normalizer import AUTH_EXTRAS_KEY, THUNDER_CLIENT_EXTRAS_KEY
from app.thunder_client_parser import (
    ThunderParseError,
    is_thunder_collection,
    is_thunder_environment,
    parse_thunder_fileset,
    parse_thunder_text,
)

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "thunder-client"
_SET = "03-environment-set"
_SET_COLLECTION = f"{_SET}/thunder-collection_inventory.json"
_SET_ENVIRONMENT = f"{_SET}/thunder-environment_staging.json"
_ENVIRONMENT_ALONE = "negative/07-semantic-environment-alone.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter():
    return get_import_source("thunder-client")


def _example(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _import(text: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label="thunder-collection_test.json"))


def _import_set(members: Dict[str, str], root: str = "thunder-collection_test.json") -> CanonicalApi:
    adapter = _adapter()
    fileset = IntakeFileset.from_members(members, root=root)
    return adapter.normalize(adapter.parse_fileset(fileset, source_label=root))


def _operations(api: CanonicalApi) -> Dict[str, Any]:
    return {op.key: op for service in api.services for op in service.operations}


def _request_message(operation: Any) -> Any:
    [message] = [m for m in operation.messages if m.role is MessageRole.REQUEST]
    return message


def _request(name: str, method: str, url: str, **fields: Any) -> Dict[str, Any]:
    """A saved request in the Thunder Client export shape."""
    request = {
        "_id": f"req-{name}",
        "colId": "col-1",
        "containerId": "",
        "name": name,
        "url": url,
        "method": method,
        "sortNum": 10000,
        "headers": [],
        "params": [],
        "tests": [],
    }
    request.update(fields)
    return request


def _collection(requests: List[Dict[str, Any]], **fields: Any) -> Dict[str, Any]:
    collection = {
        "clientName": "Thunder Client",
        "collectionName": "Test collection",
        "collectionId": "col-1",
        "version": "1.2",
        "folders": [],
        "requests": requests,
    }
    collection.update(fields)
    return collection


def _environment(data: List[Dict[str, Any]], **fields: Any) -> Dict[str, Any]:
    environment = {"clientName": "Thunder Client", "name": "env", "data": data}
    environment.update(fields)
    return environment


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_claims_a_collection_with_confidence() -> None:
    result = _adapter().detect(DetectionInput(text=_example("02-typical-orders-collection.json")))
    assert result.format == "thunder-client"
    assert result.confidence >= 0.95


def test_detect_claims_an_export_without_a_client_name_by_its_request_links() -> None:
    collection = json.loads(_example("01-minimal-collection.json"))
    del collection["clientName"]
    result = _adapter().detect(DetectionInput(text=json.dumps(collection)))
    assert 0.85 <= result.confidence < 0.95


def test_detect_claims_an_environment_alone_only_weakly() -> None:
    result = _adapter().detect(DetectionInput(text=_example(_SET_ENVIRONMENT)))
    assert result.format == "thunder-client"
    assert result.confidence < 0.85


def test_detect_does_not_claim_a_hoppscotch_collection() -> None:
    result = _adapter().detect(DetectionInput(text=_example("negative/04-wrong-format-hoppscotch.json")))
    assert result.confidence == 0


def test_other_collection_adapters_do_not_claim_a_thunder_collection() -> None:
    text = _example("07-composition-folder-hierarchy.json")
    for key in ("hoppscotch", "postman", "http-file"):
        assert get_import_source(key).detect(DetectionInput(text=text)).confidence < 0.85


def test_shape_predicates() -> None:
    collection = json.loads(_example("01-minimal-collection.json"))
    environment = json.loads(_example(_SET_ENVIRONMENT))
    assert is_thunder_collection(collection)
    assert not is_thunder_collection(environment)
    assert is_thunder_environment(environment)
    assert not is_thunder_environment(collection)
    # A `data` list without the Thunder client name is not claimed.
    assert not is_thunder_environment({"name": "x", "data": [{"name": "a", "value": "b"}]})


# ---------------------------------------------------------------------------
# Acceptance: a collection and its environment import as one API
# ---------------------------------------------------------------------------


def test_collection_and_environment_import_as_one_api() -> None:
    api = _import_set(
        {
            "thunder-collection_inventory.json": _example(_SET_COLLECTION),
            "thunder-environment_staging.json": _example(_SET_ENVIRONMENT),
        },
        root="thunder-collection_inventory.json",
    )
    assert api.format == "thunder-client"
    assert api.title == "Inventory"
    assert len(api.services) == 1
    assert set(_operations(api)) == {"GET /stock/{sku}", "POST /reservations"}
    # The environment supplies the server variable's default.
    [server] = api.servers
    assert server.url == "{baseUrl}"
    assert server.variables[0].name == "baseUrl"
    assert server.variables[0].default == "https://staging.example.com/inventory"
    record = api.extras[THUNDER_CLIENT_EXTRAS_KEY]
    assert record["environments"] == ["Inventory · staging"]
    # A secret-named variable is listed by name, flagged secret, and declared as a limit.
    assert {"name": "apiKey", "source": "environment:Inventory · staging", "secret": True} in record["variables"]
    limits = {limit["construct"]: limit for limit in record["capability_limits"]}
    assert limits["thunder-client.secret_variable"]["locations"] == ["apiKey"]


def test_folders_rebuilt_from_container_ids_become_operation_groups() -> None:
    api = _import(_example("07-composition-folder-hierarchy.json"))
    operations = _operations(api)
    assert operations["GET /tenant-a/read"].tags == ["Tenant A / Read"]
    assert operations["POST /tenant-a/write"].tags == ["Tenant A / Write"]
    assert operations["GET /tenant-b/read"].tags == ["Tenant B"]
    assert operations["GET /root"].tags == []
    assert api.extras[THUNDER_CLIENT_EXTRAS_KEY]["folders"] == [
        "Tenant A",
        "Tenant A / Read",
        "Tenant A / Write",
        "Tenant B",
    ]


def test_nested_folder_in_the_stress_collection() -> None:
    operations = _operations(_import(_example("04-stress-bodies-auth-and-tests.json")))
    assert operations["GET /legacy"].tags == ["Bodies / Nested"]
    assert operations["POST /samples"].tags == ["Bodies"]


def test_unresolved_base_url_keeps_a_server_variable_without_default() -> None:
    [server] = _import(_example("02-typical-orders-collection.json")).servers
    assert server.url == "{baseUrl}"
    assert server.variables[0].default is None


def test_literal_host_becomes_a_server() -> None:
    api = _import(_example("01-minimal-collection.json"))
    assert [server.url for server in api.servers] == ["https://api.example.com"]
    assert set(_operations(api)) == {"GET /ping"}


def test_a_secret_named_base_url_variable_gets_no_default() -> None:
    collection = _collection([_request("Ping", "GET", "{{sessionHost}}/ping")])
    environment = _environment([{"name": "sessionHost", "value": "https://hidden.example.com"}])
    api = _import_set(
        {"thunder-collection_test.json": json.dumps(collection), "thunder-environment_e.json": json.dumps(environment)}
    )
    assert api.servers[0].variables[0].default is None
    assert "hidden.example.com" not in api.model_dump_json()


def test_the_default_environment_wins_over_another() -> None:
    collection = _collection([_request("Ping", "GET", "{{baseUrl}}/ping")])
    first = _environment([{"name": "baseUrl", "value": "https://a.example.com"}], name="a")
    second = _environment([{"name": "baseUrl", "value": "https://b.example.com"}], name="b", default=True)
    api = _import_set(
        {
            "thunder-collection_test.json": json.dumps(collection),
            "thunder-environment_a.json": json.dumps(first),
            "thunder-environment_b.json": json.dumps(second),
        }
    )
    assert api.servers[0].variables[0].default == "https://b.example.com"
    assert api.extras[THUNDER_CLIENT_EXTRAS_KEY]["environments"] == ["a", "b"]


def test_a_relative_url_takes_the_collection_base_url() -> None:
    collection = _collection(
        [_request("Ping", "GET", "/ping")], settings={"options": {"baseUrl": "https://base.example.com/v1"}}
    )
    api = _import(json.dumps(collection))
    assert set(_operations(api)) == {"GET /v1/ping"}
    assert [server.url for server in api.servers] == ["https://base.example.com"]


def test_several_collections_in_one_fileset_import_as_one_api() -> None:
    api = _import_set(
        {
            "thunder-collection_ping.json": _example("01-minimal-collection.json"),
            "thunder-collection_orders.json": _example("02-typical-orders-collection.json"),
        },
        root="thunder-collection_ping.json",
    )
    assert len(api.services) == 1
    assert {"GET /ping", "GET /v2/orders"} <= set(_operations(api))


# ---------------------------------------------------------------------------
# Requests: method, URL, headers, params, body
# ---------------------------------------------------------------------------


def test_path_params_become_path_parameters() -> None:
    operation = _operations(_import(_example("02-typical-orders-collection.json")))["GET /v2/orders/{orderId}"]
    [path_param] = [p for p in operation.parameters if p.location is ParameterLocation.PATH]
    assert path_param.name == "orderId"
    assert path_param.required


def test_query_params_and_inherited_headers() -> None:
    operation = _operations(_import(_example("02-typical-orders-collection.json")))["GET /v2/orders"]
    query = {p.name for p in operation.parameters if p.location is ParameterLocation.QUERY}
    assert query == {"status", "limit"}
    headers = {p.name for p in operation.parameters if p.location is ParameterLocation.HEADER}
    assert headers == {"accept", "x-tenant"}  # the collection header is inherited


def test_disabled_entries_are_left_out() -> None:
    operations = _operations(_import(_example("04-stress-bodies-auth-and-tests.json")))
    patch = operations["PATCH /samples/{sampleId}/status"]
    assert "x-debug" not in {p.name for p in patch.parameters}
    assert {p.name for p in patch.parameters if p.location is ParameterLocation.QUERY} == {"notify"}


def test_folder_headers_are_inherited_down_the_chain() -> None:
    operations = _operations(_import(_example("07-composition-folder-hierarchy.json")))
    names = {p.name for p in operations["GET /tenant-a/read"].parameters if p.location is ParameterLocation.HEADER}
    assert {"x-collection", "x-scope"} <= names


def test_a_query_written_into_the_url_is_kept_once() -> None:
    collection = _collection(
        [
            _request(
                "List",
                "GET",
                "https://api.example.com/items?page=1&sort=asc",
                params=[{"name": "page", "value": "1", "isPath": False}],
            )
        ]
    )
    operation = _operations(_import(json.dumps(collection)))["GET /items"]
    query = [p.name for p in operation.parameters if p.location is ParameterLocation.QUERY]
    assert sorted(query) == ["page", "sort"]


def test_json_body_produces_an_inferred_schema() -> None:
    api = _import(_example("02-typical-orders-collection.json"))
    operation = _operations(api)["POST /v2/orders"]
    request = _request_message(operation)
    assert request.content_types == ["application/json"]
    payload_type = api.type_by_key(request.payload.name)
    assert {field.name for field in payload_type.fields} == {"customerId", "lines"}
    # Stamped by the shared engine, never presented as declared.
    assert provenance_of(payload_type.extras) == INFERRED
    assert provenance_of(operation.extras) == INFERRED


def test_form_bodies_keep_their_content_type_and_infer_field_schemas() -> None:
    api = _import(_example("04-stress-bodies-auth-and-tests.json"))
    operations = _operations(api)
    samples = _request_message(operations["POST /samples"])
    assert samples.content_types == ["application/json", "application/x-www-form-urlencoded"]
    fields = {field.name for field in api.type_by_key(samples.payload.name).fields}
    assert {"label", "assay"} <= fields
    assert "replicates" not in fields  # disabled form field
    upload = _request_message(operations["POST /samples/upload"])
    assert upload.content_types == ["multipart/form-data"]
    # The file part is a string field beside the form field.
    assert {field.name for field in api.type_by_key(upload.payload.name).fields} == {"attachment", "label"}


def test_graphql_body_becomes_a_query_and_variables_object() -> None:
    api = _import(_example("04-stress-bodies-auth-and-tests.json"))
    request = _request_message(_operations(api)["POST /graphql"])
    assert request.content_types == ["application/json"]
    assert {field.name for field in api.type_by_key(request.payload.name).fields} == {"query", "variables"}


@pytest.mark.parametrize(
    "body",
    [
        {"type": "xml", "raw": "<order><id>1</id></order>"},
        {"type": "text", "raw": "plain words"},
        {"type": "binary", "binary": "/tmp/readings.bin"},
    ],
)
def test_bodies_without_a_json_shape_import_without_a_schema(body: Dict[str, Any]) -> None:
    """The shared engine infers schemas from JSON-shaped bodies only; other bodies infer none."""
    collection = _collection([_request("Send", "POST", "https://api.example.com/send", body=body)])
    operation = _operations(_import(json.dumps(collection)))["POST /send"]
    assert not any(m.role is MessageRole.REQUEST and m.payload for m in operation.messages)
    assert "/tmp/readings.bin" not in operation.model_dump_json()


def test_bare_variable_in_a_json_body_still_infers_a_schema() -> None:
    body = {"type": "json", "raw": '{ "sku": "WID-1", "quantity": {{qty}} }', "form": []}
    collection = _collection([_request("Reserve", "POST", "https://api.example.com/reserve", body=body)])
    api = _import(json.dumps(collection))
    request = _request_message(_operations(api)["POST /reserve"])
    assert {field.name for field in api.type_by_key(request.payload.name).fields} == {"sku", "quantity"}


def test_an_empty_body_is_no_body() -> None:
    body = {"type": "json", "raw": "", "form": []}
    collection = _collection([_request("Ping", "POST", "https://api.example.com/ping", body=body)])
    operation = _operations(_import(json.dumps(collection)))["POST /ping"]
    assert not any(m.role is MessageRole.REQUEST and m.payload for m in operation.messages)


# ---------------------------------------------------------------------------
# Auth, tests and pre-request steps
# ---------------------------------------------------------------------------


def test_auth_inheritance_and_overrides_resolve_per_request() -> None:
    api = _import(_example("07-composition-folder-hierarchy.json"))
    operations = _operations(api)
    assert operations["GET /root"].extras["security"] == ["bearer"]
    assert operations["GET /tenant-a/read"].extras["security"] == ["bearer"]
    assert operations["POST /tenant-a/write"].extras["security"] == ["basic"]
    assert operations["GET /tenant-b/read"].extras["security"] == ["bearer"]
    [basic] = operations["POST /tenant-a/write"].extras[AUTH_EXTRAS_KEY]
    assert basic == {"type": "basic", "scheme": "basic", "declared_at": "Tenant A/Write"}
    [bearer] = operations["GET /root"].extras[AUTH_EXTRAS_KEY]
    assert bearer["declared_at"] == "collection root"
    schemes, scope = operation_security_schemes(api, operations["POST /tenant-a/write"])
    assert (schemes, scope) == (["basic"], "operation")
    assert declared_security_schemes(api) == ["basic", "bearer"]


def test_a_request_auth_of_none_overrides_the_collection() -> None:
    operations = _operations(_import(_example("05-real-world-payments-collection.json")))
    assert "security" not in operations["POST /oauth/token"].extras
    assert operations["POST /authorizations"].extras["security"] == ["bearer"]


def test_oauth2_keeps_only_public_facts() -> None:
    operations = _operations(_import(_example("04-stress-bodies-auth-and-tests.json")))
    [oauth] = operations["GET /protected"].extras[AUTH_EXTRAS_KEY]
    assert oauth == {
        "type": "oauth2",
        "scheme": "oauth2",
        "declared_at": "request",
        "grant_type": "client_credentials",
        "token_url": "https://auth.example.com/oauth/token",
        "scopes": ["lab.read", "lab.write"],
    }
    assert "security" not in operations["POST /samples"].extras  # collection auth is `none`


@pytest.mark.parametrize(("auth_type", "scheme"), [("ntlm", "authorization"), ("aws", "authorization")])
def test_signing_auth_types_map_to_a_generic_requirement(auth_type: str, scheme: str) -> None:
    collection = _collection([_request("Signed", "GET", "https://api.example.com/x", auth={"type": auth_type})])
    assert _operations(_import(json.dumps(collection)))["GET /x"].extras["security"] == [scheme]


def test_tests_and_pre_request_steps_are_declared_limits() -> None:
    api = _import(_example("04-stress-bodies-auth-and-tests.json"))
    limits = {limit["construct"]: limit for limit in api.extras[THUNDER_CLIENT_EXTRAS_KEY]["capability_limits"]}
    assert limits["thunder-client.pre_request"]["locations"] == ["Path and query params with a pre-request"]
    assert "JSON body" in limits["thunder-client.test"]["locations"]
    manifest = build_import_preview_manifest(api, adapter_key="thunder-client")
    constructs = json.dumps([entry.model_dump(mode="json") for entry in manifest.document_coverage])
    for construct in ("thunder-client.test", "thunder-client.pre_request", "thunder-client.auth_credential"):
        assert construct in constructs


def test_import_is_deterministic() -> None:
    text = _example("04-stress-bodies-auth-and-tests.json")
    assert _import(text).model_dump_json() == _import(text).model_dump_json()


# ---------------------------------------------------------------------------
# Acceptance: credentials are scrubbed and never persisted
# ---------------------------------------------------------------------------

#: Literal credentials planted across every place a saved Thunder Client request can hold one.
_BEARER = "tc-bearer-9f8e7d6c5b4a39281706"
_PASSWORD = "Basic-Pa55word-Literal"
_CLIENT_SECRET = "oauth-client-secret-5566778899"
_AUTH_HEADER = "Bearer hdr-token-aabbccddeeff00112233"
_COOKIE = "session=cookie-jar-value-123456"
_API_KEY_HEADER = "hdr-api-key-literal-4455"
_QUERY_TOKEN = "qry-access-token-778899"
_BODY_PASSWORD = "body-password-literal-1"
_FORM_SECRET = "form-client-secret-literal"
_USERINFO_PASSWORD = "userinfo-pw-literal"
_ENV_SECRET = "env-secret-value-not-to-keep"
_ENV_TOKEN = "AIza" + "SyD-0a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P"
_STRIPE = "sk_live_" + "51HthunderLiteralKey000"

_PLANTED = [
    _BEARER,
    _PASSWORD,
    _CLIENT_SECRET,
    "hdr-token-aabbccddeeff00112233",
    "cookie-jar-value-123456",
    _API_KEY_HEADER,
    _QUERY_TOKEN,
    _BODY_PASSWORD,
    _FORM_SECRET,
    _USERINFO_PASSWORD,
    _ENV_SECRET,
    _ENV_TOKEN,
    _STRIPE,
]


def _credential_collection() -> Dict[str, Any]:
    return _collection(
        [
            _request(
                "Bearer",
                "GET",
                "{{baseUrl}}/me",
                auth={"type": "bearer", "bearer": _BEARER},
                headers=[
                    {"name": "Authorization", "value": _AUTH_HEADER},
                    {"name": "Cookie", "value": _COOKIE},
                    {"name": "X-Api-Key", "value": _API_KEY_HEADER},
                    {"name": "X-Trace", "value": _STRIPE},
                ],
                params=[{"name": "access_token", "value": _QUERY_TOKEN, "isPath": False}],
            ),
            _request(
                "Basic",
                "POST",
                f"https://svc:{_USERINFO_PASSWORD}@api.example.com/login?token={_QUERY_TOKEN}",
                auth={"type": "basic", "basic": {"username": "svc", "password": _PASSWORD}},
                body={"type": "json", "raw": json.dumps({"user": "svc", "password": _BODY_PASSWORD}), "form": []},
            ),
            _request(
                "Token",
                "POST",
                "{{baseUrl}}/oauth/token",
                auth={
                    "type": "oauth2",
                    "oauth2": {
                        "grantType": "client_credentials",
                        "accessTokenUrl": "https://auth.example.com/token",
                        "clientId": "client-1",
                        "clientSecret": _CLIENT_SECRET,
                    },
                },
                body={
                    "type": "formencoded",
                    "raw": "",
                    "form": [
                        {"name": "grant_type", "value": "client_credentials"},
                        {"name": "client_secret", "value": _FORM_SECRET},
                    ],
                },
            ),
        ],
        settings={"headers": [{"name": "X-Trace-Env", "value": _ENV_TOKEN}], "auth": {"type": "none"}},
    )


def _credential_environment() -> Dict[str, Any]:
    return _environment(
        [
            {"name": "baseUrl", "value": "https://api.example.com"},
            {"name": "apiKey", "value": _ENV_SECRET},
            {"name": "accessToken", "value": _BEARER},
        ],
        name="prod",
    )


def test_saved_credentials_never_reach_the_canonical_model() -> None:
    api = _import_set(
        {
            "thunder-collection_test.json": json.dumps(_credential_collection()),
            "thunder-environment_prod.json": json.dumps(_credential_environment()),
        }
    )
    persisted = api.model_dump_json()
    for secret in _PLANTED:
        assert secret not in persisted, f"{secret[:10]}… reached the canonical model"
    # The facts that are not credentials survive.
    operations = _operations(api)
    assert operations["POST /login"].extras["security"] == ["basic"]
    assert operations["GET /me"].extras["security"] == ["bearer"]
    [templated] = [server for server in api.servers if server.url == "{baseUrl}"]
    assert templated.variables[0].default == "https://api.example.com"


def test_saved_credentials_never_reach_the_coverage_manifest() -> None:
    api = _import(json.dumps(_credential_collection()))
    manifest = build_import_preview_manifest(api, adapter_key="thunder-client")
    rendered = repr(manifest.document_coverage) + repr(manifest.entity_rows) + repr(manifest.document_nodes)
    for secret in _PLANTED:
        assert secret not in rendered, f"{secret[:10]}… reached the coverage manifest"


@pytest.mark.parametrize("member", ["collection", "environment"])
def test_saved_credentials_never_reach_the_persisted_source(member: str) -> None:
    """The shared scrub gate redacts the stored source of a single upload."""
    document = _credential_collection() if member == "collection" else _credential_environment()
    text = json.dumps(document, indent=2)
    intake = _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)
    fields, report = scrub_intake_source(intake)
    stored = fields["sourceContent"]
    assert report["scrubbed"] is True
    for secret in (
        _BEARER,
        _PASSWORD,
        _CLIENT_SECRET,
        "hdr-token-aabbccddeeff00112233",
        "cookie-jar-value-123456",
        _API_KEY_HEADER,
        _FORM_SECRET,
        _STRIPE,
        _ENV_SECRET,
        _ENV_TOKEN,
        _USERINFO_PASSWORD,
    ):
        if secret in text:
            assert secret not in stored, f"{secret[:10]}… persisted in the source"
    for secret in _PLANTED:
        assert secret not in str(report)
    # Non-credential members of the same pairs survive.
    if member == "environment":
        assert "https://api.example.com" in stored


# ---------------------------------------------------------------------------
# Taxonomy codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-missing-comma.json", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-requests.json", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-request.json", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-hoppscotch.json", "FORMAT_MISMATCH"),
        ("negative/06-semantic-orphan-container-id.json", "INPUT_SEMANTIC_INVALID"),
        (_ENVIRONMENT_ALONE, "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_negative_corpus_codes(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as caught:
        _adapter().parse(_example(name), source_label=name)
    assert caught.value.code == code


def test_utf16_upload_is_an_encoding_fault() -> None:
    text = (_EXAMPLES / "negative/05-encoding-utf16.json").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_text(text)
    assert caught.value.code == "INPUT_ENCODING_INVALID"


def test_an_orphaned_request_is_refused() -> None:
    collection = _collection([_request("Lost", "GET", "https://api.example.com/x", containerId="missing")])
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_text(json.dumps(collection))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"
    assert "missing" in str(caught.value)


def test_a_folder_cycle_is_refused() -> None:
    folders = [
        {"_id": "a", "name": "A", "containerId": "b"},
        {"_id": "b", "name": "B", "containerId": "a"},
    ]
    collection = _collection([_request("Ping", "GET", "https://api.example.com/ping")], folders=folders)
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_text(json.dumps(collection))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"
    assert "cycle" in str(caught.value)


def test_url_written_only_as_an_undefined_variable_is_refused() -> None:
    collection = _collection([_request("Only var", "GET", "{{nowhere}}")])
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_text(json.dumps(collection))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"
    assert "{{nowhere}}" in str(caught.value)


def test_an_environment_uploaded_alone_is_refused() -> None:
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_text(_example(_ENVIRONMENT_ALONE))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_fileset({"thunder-environment_staging.json": _example(_SET_ENVIRONMENT)})
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


@pytest.mark.parametrize(
    "document",
    [
        {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}},
        {"info": {"_postman_id": "x", "name": "x"}, "item": []},
        {"log": {"version": "1.2", "entries": []}},
        {"name": "x"},
    ],
)
def test_other_json_is_a_format_mismatch(document: Dict[str, Any]) -> None:
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_text(json.dumps(document))
    assert caught.value.code == "FORMAT_MISMATCH"


@pytest.mark.parametrize(
    "mutation",
    [
        {"requests": [_request("No method", "", "https://api.example.com/x")]},
        {"requests": [_request("Ping", "GET", "https://api.example.com/x", headers="X-A: 1")]},
        {"folders": [{"name": "No id"}]},
    ],
)
def test_structural_faults_are_malformed(mutation: Dict[str, Any]) -> None:
    collection = _collection([_request("Ping", "GET", "https://api.example.com/ping")])
    collection.update(mutation)
    with pytest.raises(ThunderParseError) as caught:
        parse_thunder_text(json.dumps(collection))
    assert caught.value.code == "INPUT_MALFORMED"


def test_normalize_rejects_a_foreign_ast() -> None:
    with pytest.raises(ImportSourceError):
        _adapter().normalize({"not": "a document"})
