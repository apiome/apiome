"""Hoppscotch collection import — FMT-10.1 (#5473).

Covers the reader (:mod:`app.hoppscotch_parser`), the normalizer (:mod:`app.hoppscotch_normalizer`)
and the adapter (:mod:`app.hoppscotch_import_source`) against the acceptance criteria:

* a collection with nested folders and an environment file imports as **one API**;
* request bodies produce inferred schemas through the **shared** inferred-spec engine;
* saved credentials are scrubbed and **never persisted** — neither in the canonical model nor in
  the source content the intake stores;
* the corpus (nested collection, environment set, malformed collections) is exercised by the
  shared corpus suites; the taxonomy codes are pinned here too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.canonical_model import CanonicalApi, MessageRole, ParameterLocation
from app.canonical_security import declared_security_schemes, operation_security_schemes
from app.fileset import IntakeFileset
from app.hoppscotch_normalizer import HOPPSCOTCH_EXTRAS_KEY
from app.hoppscotch_parser import (
    HoppscotchParseError,
    is_hoppscotch_collection,
    is_hoppscotch_environment,
    parse_hoppscotch_fileset,
    parse_hoppscotch_text,
)
from app.import_preview_manifest import build_import_preview_manifest
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.import_source_pipeline import _ResolvedIntake, scrub_intake_source
from app.inference_provenance import INFERRED, provenance_of

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "hoppscotch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter():
    return get_import_source("hoppscotch")


def _example(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _import(text: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label="collection.json"))


def _import_set(members: Dict[str, str], root: str = "collection.json") -> CanonicalApi:
    adapter = _adapter()
    fileset = IntakeFileset.from_members(members, root=root)
    return adapter.normalize(adapter.parse_fileset(fileset, source_label=root))


def _operations(api: CanonicalApi) -> Dict[str, Any]:
    return {op.key: op for service in api.services for op in service.operations}


def _request(name: str, method: str, endpoint: str, **fields: Any) -> Dict[str, Any]:
    """A saved request in the Hoppscotch v11 request shape."""
    request = {
        "v": "11",
        "name": name,
        "method": method,
        "endpoint": endpoint,
        "params": [],
        "headers": [],
        "auth": {"authType": "inherit", "authActive": True},
        "body": {"contentType": None, "body": None},
        "preRequestScript": "",
        "testScript": "",
        "requestVariables": [],
    }
    request.update(fields)
    return request


def _collection(requests: List[Dict[str, Any]], **fields: Any) -> Dict[str, Any]:
    collection = {
        "v": 6,
        "name": "Test collection",
        "folders": [],
        "requests": requests,
        "auth": {"authType": "none", "authActive": False},
        "headers": [],
    }
    collection.update(fields)
    return collection


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_claims_a_collection_with_confidence() -> None:
    result = _adapter().detect(DetectionInput(text=_example("02-typical-orders-collection.json")))
    assert result.format == "hoppscotch"
    assert result.confidence >= 0.95


def test_detect_claims_an_environment_alone_only_weakly() -> None:
    result = _adapter().detect(DetectionInput(text=_example("03-environment-set/environment.json")))
    assert result.format == "hoppscotch"
    assert result.confidence < 0.85


def test_detect_does_not_claim_a_postman_collection() -> None:
    result = _adapter().detect(DetectionInput(text=_example("negative/04-wrong-format-postman.json")))
    assert result.confidence == 0


def test_other_collection_adapters_do_not_claim_a_hoppscotch_collection() -> None:
    text = _example("06-typical-nested-folders.json")
    for key in ("postman", "http-file"):
        assert get_import_source(key).detect(DetectionInput(text=text)).confidence < 0.85


def test_shape_predicates() -> None:
    collection = json.loads(_example("01-minimal-collection.json"))
    environment = json.loads(_example("03-environment-set/environment.json"))
    assert is_hoppscotch_collection(collection)
    assert is_hoppscotch_collection([collection, collection])
    assert not is_hoppscotch_collection(environment)
    assert is_hoppscotch_environment(environment)
    assert is_hoppscotch_environment([environment])
    # A Postman environment uses `values`, not `variables`.
    assert not is_hoppscotch_environment({"name": "x", "values": [{"key": "a", "value": "b"}]})


# ---------------------------------------------------------------------------
# Acceptance: nested folders + environment → one API
# ---------------------------------------------------------------------------


def test_nested_folders_and_environment_import_as_one_api() -> None:
    collection = json.loads(_example("06-typical-nested-folders.json"))
    environment = {
        "v": 2,
        "name": "Storefront · prod",
        "variables": [
            {"key": "baseUrl", "initialValue": "https://shop.example.com/api", "secret": False},
            {"key": "sessionKey", "initialValue": "", "secret": True},
        ],
    }
    api = _import_set({"collection.json": json.dumps(collection), "env/prod.json": json.dumps(environment)})
    assert api.format == "hoppscotch"
    assert len(api.services) == 1
    operations = _operations(api)
    assert set(operations) == {
        "GET /categories",
        "GET /products",
        "GET /products/{sku}",
        "POST /carts",
        "POST /carts/{cartId}/items",
    }
    # Folders are operation groups, nested folders spelled as a path.
    assert operations["GET /products/{sku}"].tags == ["Catalogue / Products"]
    assert operations["GET /categories"].tags == ["Catalogue / Categories"]
    assert operations["POST /carts"].tags == ["Cart"]
    assert api.extras[HOPPSCOTCH_EXTRAS_KEY]["folders"] == [
        "Cart",
        "Catalogue",
        "Catalogue / Categories",
        "Catalogue / Products",
    ]
    # Environment variables become server variables.
    [server] = api.servers
    assert server.url == "{baseUrl}"
    assert server.variables[0].name == "baseUrl"
    assert server.variables[0].default == "https://shop.example.com/api"
    assert api.extras[HOPPSCOTCH_EXTRAS_KEY]["environments"] == ["Storefront · prod"]


def test_corpus_environment_set_resolves_the_base_url_and_withholds_the_secret() -> None:
    api = _import_set(
        {
            "collection.json": _example("03-environment-set/collection.json"),
            "environment.json": _example("03-environment-set/environment.json"),
        }
    )
    [server] = api.servers
    assert server.variables[0].default == "https://staging.example.com/inventory"
    record = api.extras[HOPPSCOTCH_EXTRAS_KEY]
    assert {"name": "apiKey", "source": "environment:Inventory · staging", "secret": True} in record["variables"]
    limits = {limit["construct"]: limit for limit in record["capability_limits"]}
    assert limits["hoppscotch.secret_variable"]["locations"] == ["apiKey"]


def test_a_secret_base_url_variable_gets_no_default() -> None:
    collection = _collection([_request("Ping", "GET", "<<baseUrl>>/ping")])
    environment = {"name": "prod", "variables": [{"key": "baseUrl", "value": "https://x.example.com", "secret": True}]}
    api = _import_set({"collection.json": json.dumps(collection), "environment.json": json.dumps(environment)})
    assert api.servers[0].variables[0].default is None
    assert "x.example.com" not in api.model_dump_json()


def test_unresolved_base_url_keeps_a_server_variable_without_default() -> None:
    api = _import(_example("02-typical-orders-collection.json"))
    [server] = api.servers
    assert server.url == "{baseUrl}"
    assert server.variables[0].default is None


def test_literal_host_becomes_a_server() -> None:
    api = _import(_example("01-minimal-collection.json"))
    assert [server.url for server in api.servers] == ["https://api.example.com"]
    assert set(_operations(api)) == {"GET /ping"}


def test_variable_precedence_request_over_environment_over_collection() -> None:
    collection = _collection(
        [
            _request(
                "Ping",
                "GET",
                "<<host>>/ping",
                requestVariables=[{"key": "host", "value": "https://req.example.com", "active": True}],
            )
        ],
        variables=[{"key": "host", "initialValue": "https://col.example.com", "secret": False}],
    )
    environment = {"name": "e", "variables": [{"key": "host", "value": "https://env.example.com", "secret": False}]}
    with_request = _import_set({"collection.json": json.dumps(collection), "environment.json": json.dumps(environment)})
    assert with_request.servers[0].variables[0].default == "https://req.example.com"

    collection["requests"][0]["requestVariables"] = []
    with_env = _import_set({"collection.json": json.dumps(collection), "environment.json": json.dumps(environment)})
    assert with_env.servers[0].variables[0].default == "https://env.example.com"
    assert _import(json.dumps(collection)).servers[0].variables[0].default == "https://col.example.com"


def test_an_export_of_several_collections_imports_as_one_api() -> None:
    first = json.loads(_example("01-minimal-collection.json"))
    second = json.loads(_example("06-typical-nested-folders.json"))
    api = _import(json.dumps([first, second]))
    assert api.title == "Ping · Storefront"
    assert len(api.services) == 1
    assert {"GET /ping", "GET /products"} <= set(_operations(api))


# ---------------------------------------------------------------------------
# Acceptance: request bodies → inferred schemas via the shared engine
# ---------------------------------------------------------------------------


def test_json_body_produces_an_inferred_schema() -> None:
    api = _import(_example("02-typical-orders-collection.json"))
    operation = _operations(api)["POST /v2/orders"]
    [request] = [message for message in operation.messages if message.role is MessageRole.REQUEST]
    assert request.content_types == ["application/json"]
    payload_type = api.type_by_key(request.payload.name)
    assert payload_type is not None
    assert {field.name for field in payload_type.fields} == {"customerId", "lines"}
    # Stamped by the shared engine, never presented as declared.
    assert provenance_of(payload_type.extras) == INFERRED
    assert provenance_of(operation.extras) == INFERRED


def test_form_bodies_keep_their_content_type_and_infer_field_schemas() -> None:
    api = _import(_example("04-stress-auth-and-bodies.json"))
    operations = _operations(api)
    [samples] = [m for m in operations["POST /samples"].messages if m.role is MessageRole.REQUEST]
    # Raw JSON and URL-encoded requests share one route; both media types are kept and the
    # field sets are widened together.
    assert samples.content_types == ["application/json", "application/x-www-form-urlencoded"]
    fields = {field.name for field in api.type_by_key(samples.payload.name).fields}
    assert {"label", "assay", "replicates"} <= fields
    [upload] = [m for m in operations["POST /samples/upload"].messages if m.role is MessageRole.REQUEST]
    assert upload.content_types == ["multipart/form-data"]
    # The inactive `notes` part is left out; the file part is a string field.
    assert {field.name for field in api.type_by_key(upload.payload.name).fields} == {"attachment", "label"}


def test_bare_variable_in_a_json_body_still_infers_a_schema() -> None:
    body = '{ "sku": "WID-1", "quantity": <<qty>> }'
    collection = _collection(
        [
            _request(
                "Reserve",
                "POST",
                "https://api.example.com/reserve",
                body={"contentType": "application/json", "body": body},
            )
        ]
    )
    api = _import(json.dumps(collection))
    [request] = [m for m in _operations(api)["POST /reserve"].messages if m.role is MessageRole.REQUEST]
    assert {field.name for field in api.type_by_key(request.payload.name).fields} == {"sku", "quantity"}


def test_saved_responses_produce_response_schemas() -> None:
    collection = _collection(
        [
            _request(
                "Get order",
                "GET",
                "https://api.example.com/orders/<<id>>",
                responses={
                    "ok": {
                        "name": "ok",
                        "code": 200,
                        "status": "OK",
                        "headers": [],
                        "body": '{"id": "o-1", "total": 12.5}',
                    }
                },
            )
        ]
    )
    api = _import(json.dumps(collection))
    operation = _operations(api)["GET /orders/{id}"]
    [response] = [m for m in operation.messages if m.role is MessageRole.RESPONSE]
    assert response.status_code == "200"
    assert {field.name for field in api.type_by_key(response.payload.name).fields} == {"id", "total"}


# ---------------------------------------------------------------------------
# Requests: path variables, params, headers, auth
# ---------------------------------------------------------------------------


def test_path_variables_become_path_parameters() -> None:
    operation = _operations(_import(_example("02-typical-orders-collection.json")))["GET /v2/orders/{orderId}"]
    [path_param] = [p for p in operation.parameters if p.location is ParameterLocation.PATH]
    assert path_param.name == "orderId"
    assert path_param.required


def test_only_active_params_and_headers_are_read() -> None:
    operations = _operations(_import(_example("02-typical-orders-collection.json")))
    query = {p.name for p in operations["GET /v2/orders"].parameters if p.location is ParameterLocation.QUERY}
    assert query == {"status", "limit"}  # `cursor` is inactive
    headers = {p.name for p in operations["GET /v2/orders"].parameters if p.location is ParameterLocation.HEADER}
    assert headers == {"accept", "x-tenant"}  # collection header inherited
    stress = _operations(_import(_example("04-stress-auth-and-bodies.json")))
    patch = stress["PATCH /samples/{sampleId}/status"]
    assert "x-debug" not in {p.name for p in patch.parameters}  # disabled header


def test_folder_headers_are_inherited_down_the_tree() -> None:
    operations = _operations(_import(_example("07-composition-inherited-auth.json")))
    names = {p.name for p in operations["GET /tenant-a/read"].parameters if p.location is ParameterLocation.HEADER}
    assert {"x-collection", "x-tenant", "x-scope"} <= names


def test_auth_inheritance_and_overrides_resolve_per_request() -> None:
    api = _import(_example("07-composition-inherited-auth.json"))
    operations = _operations(api)
    assert operations["GET /root"].extras["security"] == ["apiKey"]
    assert operations["GET /tenant-a/read"].extras["security"] == ["bearer"]
    assert operations["POST /tenant-a/write"].extras["security"] == ["basic"]
    assert operations["GET /tenant-b/read"].extras["security"] == ["apiKey"]
    [record] = operations["GET /root"].extras["hoppscotch_auth"]
    assert record == {
        "type": "api-key",
        "scheme": "apiKey",
        "declared_at": "collection root",
        "in": "header",
        "name": "X-Api-Key",
    }
    [bearer] = operations["GET /tenant-a/read"].extras["hoppscotch_auth"]
    assert bearer["declared_at"] == "Tenant A"
    schemes, scope = operation_security_schemes(api, operations["GET /root"])
    assert (schemes, scope) == (["apiKey"], "operation")
    assert declared_security_schemes(api) == ["apiKey", "basic", "bearer"]


def test_every_auth_type_maps_to_a_canonical_scheme() -> None:
    operations = _operations(_import(_example("04-stress-auth-and-bodies.json")))
    assert operations["GET /legacy"].extras["security"] == ["basic"]
    assert operations["GET /deep"].extras["security"] == ["bearer"]
    [api_key] = operations["GET /keyed"].extras["hoppscotch_auth"]
    assert api_key["in"] == "query" and api_key["name"] == "api_key"
    [oauth] = operations["GET /protected"].extras["hoppscotch_auth"]
    assert oauth["scheme"] == "oauth2"
    assert oauth["grant_type"] == "client_credentials"
    assert oauth["token_url"] == "https://auth.example.com/oauth/token"
    assert oauth["scopes"] == ["lab.read", "lab.write"]
    # A request with no auth of its own under a collection with none records nothing.
    assert "security" not in operations["POST /samples"].extras


def test_scripts_are_declared_limits_in_the_coverage_ledger() -> None:
    api = _import(_example("05-real-world-payments-collection.json"))
    limits = {limit["construct"]: limit for limit in api.extras[HOPPSCOTCH_EXTRAS_KEY]["capability_limits"]}
    assert limits["hoppscotch.script"]["locations"] == ["Authorize a payment", "Get access token"]
    manifest = build_import_preview_manifest(api, adapter_key="hoppscotch")
    constructs = json.dumps([entry.model_dump(mode="json") for entry in manifest.document_coverage])
    assert "hoppscotch.script" in constructs
    assert "hoppscotch.auth_credential" in constructs


def test_import_is_deterministic() -> None:
    text = _example("04-stress-auth-and-bodies.json")
    assert _import(text).model_dump_json() == _import(text).model_dump_json()


# ---------------------------------------------------------------------------
# Acceptance: saved credentials are scrubbed and never persisted
# ---------------------------------------------------------------------------

#: Literal credentials planted across every place a saved Hoppscotch request can hold one.
_BEARER = "hpsc-bearer-9f8e7d6c5b4a39281706"
_PASSWORD = "Basic-Pa55word-Literal"
_API_KEY_VALUE = "k3y-v4lu3-0011223344"
_CLIENT_SECRET = "oauth-client-secret-5566778899"
_AUTH_HEADER = "Bearer hdr-token-aabbccddeeff00112233"
_COOKIE = "session=cookie-jar-value-123456"
_QUERY_TOKEN = "qry-access-token-778899"
_BODY_PASSWORD = "body-password-literal-1"
_FORM_SECRET = "form-client-secret-literal"
_USERINFO_PASSWORD = "userinfo-pw-literal"
_ENV_SECRET = "env-secret-value-not-to-keep"
_ENV_TOKEN = "AIza" + "SyD-0a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P"
_STRIPE = "sk_live_" + "51HhoppscotchLiteralKey00"

_PLANTED = [
    _BEARER,
    _PASSWORD,
    _API_KEY_VALUE,
    _CLIENT_SECRET,
    "hdr-token-aabbccddeeff00112233",
    "cookie-jar-value-123456",
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
                "<<baseUrl>>/me",
                auth={"authType": "bearer", "authActive": True, "token": _BEARER},
                headers=[
                    {"key": "Authorization", "value": _AUTH_HEADER, "active": True},
                    {"key": "Cookie", "value": _COOKIE, "active": True},
                    {"key": "X-Trace", "value": _STRIPE, "active": True},
                ],
                params=[{"key": "access_token", "value": _QUERY_TOKEN, "active": True}],
            ),
            _request(
                "Basic",
                "POST",
                f"https://svc:{_USERINFO_PASSWORD}@api.example.com/login?token={_QUERY_TOKEN}",
                auth={"authType": "basic", "authActive": True, "username": "svc", "password": _PASSWORD},
                body={
                    "contentType": "application/json",
                    "body": json.dumps({"user": "svc", "password": _BODY_PASSWORD}),
                },
            ),
            _request(
                "Key",
                "GET",
                "<<baseUrl>>/keyed",
                auth={
                    "authType": "api-key",
                    "authActive": True,
                    "addTo": "HEADERS",
                    "key": "X-Api-Key",
                    "value": _API_KEY_VALUE,
                },
            ),
            _request(
                "Token",
                "POST",
                "<<baseUrl>>/oauth/token",
                auth={
                    "authType": "oauth-2",
                    "authActive": True,
                    "grantTypeInfo": {
                        "grantType": "CLIENT_CREDENTIALS",
                        "authEndpoint": "https://auth.example.com/token",
                        "clientID": "client-1",
                        "clientSecret": _CLIENT_SECRET,
                        "token": _BEARER,
                    },
                },
                body={
                    "contentType": "application/x-www-form-urlencoded",
                    "body": f"grant_type=client_credentials&client_secret={_FORM_SECRET}",
                },
            ),
        ],
        variables=[{"key": "trace", "initialValue": _ENV_TOKEN, "secret": False}],
    )


def _credential_environment() -> Dict[str, Any]:
    return {
        "name": "prod",
        "variables": [
            {"key": "baseUrl", "value": "https://api.example.com", "secret": False},
            {"key": "apiKey", "value": _ENV_SECRET, "secret": True},
        ],
    }


def test_saved_credentials_never_reach_the_canonical_model() -> None:
    api = _import_set(
        {
            "collection.json": json.dumps(_credential_collection()),
            "environment.json": json.dumps(_credential_environment()),
        }
    )
    persisted = api.model_dump_json()
    for secret in _PLANTED:
        assert secret not in persisted, f"{secret[:10]}… reached the canonical model"
    # The facts that are not credentials survive.
    operations = _operations(api)
    assert operations["GET /keyed"].extras["hoppscotch_auth"][0]["name"] == "X-Api-Key"
    assert operations["POST /login"].extras["security"] == ["basic"]
    assert "api.example.com" in persisted


def test_saved_credentials_never_reach_the_coverage_manifest() -> None:
    api = _import(json.dumps(_credential_collection()))
    manifest = build_import_preview_manifest(api, adapter_key="hoppscotch")
    rendered = repr(manifest.document_coverage) + repr(manifest.entity_rows) + repr(manifest.document_nodes)
    for secret in _PLANTED:
        assert secret not in rendered, f"{secret[:10]}… reached the coverage manifest"


@pytest.mark.parametrize("member", ["collection.json", "environment.json"])
def test_saved_credentials_never_reach_the_persisted_source(member: str) -> None:
    """The shared scrub gate redacts the stored source of a single upload."""
    text = json.dumps(_credential_collection() if member == "collection.json" else _credential_environment(), indent=2)
    intake = _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)
    fields, report = scrub_intake_source(intake)
    stored = fields["sourceContent"]
    assert report["scrubbed"] is True
    # Credential-named fields and provider-shaped tokens are redacted by the gate.
    for secret in (
        _BEARER,
        _PASSWORD,
        _API_KEY_VALUE,
        _CLIENT_SECRET,
        _STRIPE,
        _ENV_SECRET,
        _ENV_TOKEN,
        _USERINFO_PASSWORD,
    ):
        if secret in text:
            assert secret not in stored, f"{secret[:10]}… persisted in the source"
    for secret in _PLANTED:
        assert secret not in str(report)


# ---------------------------------------------------------------------------
# Taxonomy codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-missing-brace.json", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-requests.json", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-request.json", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-postman.json", "FORMAT_MISMATCH"),
        ("negative/06-semantic-request-without-endpoint.json", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_negative_corpus_codes(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as caught:
        _adapter().parse(_example(name), source_label=name)
    assert caught.value.code == code


def test_utf16_upload_is_an_encoding_fault() -> None:
    text = (_EXAMPLES / "negative/05-encoding-utf16.json").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(HoppscotchParseError) as caught:
        parse_hoppscotch_text(text)
    assert caught.value.code == "INPUT_ENCODING_INVALID"


def test_endpoint_written_only_as_an_undefined_variable_is_refused() -> None:
    collection = _collection([_request("Only var", "GET", "<<nowhere>>")])
    with pytest.raises(HoppscotchParseError) as caught:
        parse_hoppscotch_text(json.dumps(collection))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"
    assert "<<nowhere>>" in str(caught.value)


def test_an_environment_uploaded_alone_is_refused() -> None:
    with pytest.raises(HoppscotchParseError) as caught:
        parse_hoppscotch_text(_example("03-environment-set/environment.json"))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"
    with pytest.raises(HoppscotchParseError) as caught:
        parse_hoppscotch_fileset({"environment.json": _example("03-environment-set/environment.json")})
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


@pytest.mark.parametrize(
    "document",
    [
        {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}},
        {"log": {"version": "1.2", "entries": []}},
        {"name": "x"},
    ],
)
def test_other_json_is_a_format_mismatch(document: Dict[str, Any]) -> None:
    with pytest.raises(HoppscotchParseError) as caught:
        parse_hoppscotch_text(json.dumps(document))
    assert caught.value.code == "FORMAT_MISMATCH"


def test_a_request_without_a_method_is_malformed() -> None:
    collection = _collection([_request("No method", "", "https://api.example.com/x")])
    with pytest.raises(HoppscotchParseError) as caught:
        parse_hoppscotch_text(json.dumps(collection))
    assert caught.value.code == "INPUT_MALFORMED"


def test_a_folder_of_the_wrong_shape_is_malformed() -> None:
    collection = _collection([_request("Ping", "GET", "https://api.example.com/ping")], folders=[{"name": "Bad"}])
    with pytest.raises(HoppscotchParseError) as caught:
        parse_hoppscotch_text(json.dumps(collection))
    assert caught.value.code == "INPUT_MALFORMED"


def test_normalize_rejects_a_foreign_ast() -> None:
    with pytest.raises(ImportSourceError):
        _adapter().normalize({"not": "a document"})
