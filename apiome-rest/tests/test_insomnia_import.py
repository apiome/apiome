"""Insomnia export import — MFI-32.3 (#4405).

Covers the reader (:mod:`app.insomnia_parser`), the normalizer (:mod:`app.insomnia_normalizer`) and
the adapter (:mod:`app.insomnia_import_source`) against the acceptance criteria:

* a **v5** (YAML) export imports with its **folder structure as tags** and env-var-templated URLs
  mapped to **server variables**; **v4** (JSON) exports import the same way;
* **secrets are redacted** — never in the canonical model, the coverage manifest or the stored
  source (the scrub gate's YAML and ``secret``-type rules);
* **structural stability**: the same collection exported as v4 and as v5 imports to the same
  operations, tags, servers and parameters, and an import is deterministic. (The round trip with
  an Insomnia *export* belongs to MFX-31.3, #4291, which has no emitter yet.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.canonical_model import CanonicalApi, MessageRole, ParameterLocation
from app.canonical_security import declared_security_schemes
from app.fileset import IntakeFileset
from app.import_preview_manifest import build_import_preview_manifest
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.import_source_pipeline import _ResolvedIntake, scrub_intake_source
from app.inference_provenance import INFERRED, provenance_of
from app.insomnia_normalizer import AUTH_EXTRAS_KEY, INSOMNIA_EXTRAS_KEY
from app.insomnia_parser import InsomniaParseError, detect_insomnia, parse_insomnia_fileset, parse_insomnia_text

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "insomnia"
_V5 = "02-typical-v5-users-collection.yaml"
_V4 = "06-composition-v4-users-export.json"
_STRESS = "04-stress-v4-all-shapes.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adapter():
    return get_import_source("insomnia")


def _example(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _import(text: str, label: str = "export.yaml") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=label))


def _operations(api: CanonicalApi) -> Dict[str, Any]:
    return {op.key: op for service in api.services for op in service.operations}


def _surface(api: CanonicalApi) -> Dict[str, Any]:
    """The structure an export carries, independent of the export format."""
    operations = {}
    for key, op in _operations(api).items():
        operations[key] = {
            "tags": op.tags,
            "security": op.extras.get("security"),
            "parameters": sorted((p.location.value, p.name, p.required, p.default) for p in op.parameters),
            "request": [
                (m.content_types, m.payload.name if m.payload else None)
                for m in op.messages
                if m.role is MessageRole.REQUEST
            ],
        }
    return {
        "title": api.title,
        "servers": [(s.url, [(v.name, v.default) for v in s.variables]) for s in api.servers],
        "operations": operations,
        "types": sorted(t.name for t in api.types),
    }


def _v5(collection: List[Dict[str, Any]], **extra: Any) -> str:
    doc: Dict[str, Any] = {"type": "collection.insomnia.rest/5.0", "name": "Test", "collection": collection}
    doc.update(extra)
    return yaml.safe_dump(doc, sort_keys=False)


def _request(url: str, method: str = "GET", **fields: Any) -> Dict[str, Any]:
    return {"url": url, "name": fields.pop("name", f"{method} {url}"), "method": method, **fields}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [_V5, _V4, _STRESS, "07-real-world-v5-design-document.yaml"])
def test_detect_claims_exports_with_confidence(name: str) -> None:
    result = _adapter().detect(DetectionInput(text=_example(name)))
    assert result.matched and result.format == "insomnia" and result.confidence >= 0.95


def test_detect_claims_an_environment_alone_only_weakly() -> None:
    result = _adapter().detect(DetectionInput(text=_example("negative/08-semantic-environment-alone.yaml")))
    assert result.matched and result.confidence <= 0.5


def test_an_export_without_insomnia_source_is_claimed_a_little_less() -> None:
    found = detect_insomnia(json.dumps({"_type": "export", "__export_format": 4, "resources": []}))
    assert found is not None and 0.8 <= found[1] < 0.95


@pytest.mark.parametrize(
    "text",
    [
        "not an export",
        "type: something-else\n",
        json.dumps({"info": {"_postman_id": "x"}, "item": []}),
        json.dumps({"log": {"entries": []}}),
        "openapi: 3.0.0\ninfo: {}\n",
    ],
)
def test_detect_ignores_other_documents(text: str) -> None:
    assert not _adapter().detect(DetectionInput(text=text)).matched


def test_registry_detection_picks_insomnia_for_every_export() -> None:
    for path in sorted(_EXAMPLES.glob("0*.*")):
        adapter, _ = detect_import_source(DetectionInput(text=path.read_text(encoding="utf-8"), filename=path.name))
        assert adapter is not None and adapter.key == "insomnia", path.name


@pytest.mark.parametrize("key", ["thunder-client", "hoppscotch", "postman", "har"])
def test_other_collection_adapters_do_not_claim_an_insomnia_export(key: str) -> None:
    other = get_import_source(key)
    for name in (_V5, _V4):
        assert not other.detect(DetectionInput(text=_example(name))).matched, (key, name)


def test_descriptor() -> None:
    descriptor = _adapter().descriptor()
    assert descriptor.label == "Insomnia collection"
    assert {".json", ".yaml", ".yml"} <= set(descriptor.file_extensions)


# ---------------------------------------------------------------------------
# Acceptance: v5 folders → tags, env-var URLs → server variables
# ---------------------------------------------------------------------------


def test_v5_export_imports_folders_as_tags_and_base_url_as_a_server_variable() -> None:
    api = _import(_example(_V5))
    operations = _operations(api)
    assert set(operations) == {
        "GET /health",
        "GET /v1/users",
        "GET /v1/users/{userId}",
        "POST /v1/users",
        "DELETE /v1/users/{userId}",
    }
    assert operations["GET /health"].tags == []
    assert operations["GET /v1/users"].tags == ["Users"]
    assert operations["DELETE /v1/users/{userId}"].tags == ["Users / Admin"]
    [server] = api.servers
    assert server.url == "{baseUrl}"
    assert [(v.name, v.default) for v in server.variables] == [("baseUrl", "https://api.example.com")]
    assert api.extras[INSOMNIA_EXTRAS_KEY]["folders"] == ["Users", "Users / Admin"]
    assert api.extras[INSOMNIA_EXTRAS_KEY]["environments"] == ["Base Environment", "Staging", "Production"]


def test_the_base_environment_wins_and_sub_environments_fill_gaps() -> None:
    """``baseUrl`` is the base's; ``userId`` only Staging defines, so its value is a default."""
    api = _import(_example(_V5))
    assert api.servers[0].variables[0].default == "https://api.example.com"
    record = {(v["name"], v["source"]) for v in api.extras[INSOMNIA_EXTRAS_KEY]["variables"]}
    assert ("userId", "environment:Staging") in record


def test_v4_and_v5_exports_of_one_collection_import_identically() -> None:
    """Structural stability across Insomnia's two export formats."""
    v5 = _surface(_import(_example(_V5)))
    v4 = _surface(_import(_example(_V4), label="export.json"))
    assert v4 == v5


def test_import_is_deterministic() -> None:
    for name in (_V5, _V4, _STRESS):
        assert _import(_example(name)).model_dump_json() == _import(_example(name)).model_dump_json()


def test_every_construct_is_stamped_inferred() -> None:
    api = _import(_example(_V5))
    assert provenance_of(api.extras) == INFERRED
    for operation in _operations(api).values():
        assert provenance_of(operation.extras) == INFERRED
        assert operation.extras["sample_count"] >= 1


# ---------------------------------------------------------------------------
# Requests: paths, parameters, defaults, headers
# ---------------------------------------------------------------------------


def test_colon_and_variable_path_segments_become_path_parameters() -> None:
    operations = _operations(_import(_example(_V5)))
    for key in ("GET /v1/users/{userId}", "DELETE /v1/users/{userId}"):
        names = {p.name for p in operations[key].parameters if p.location is ParameterLocation.PATH}
        assert names == {"userId"}


def test_disabled_parameters_are_left_out_and_query_params_kept() -> None:
    listing = _operations(_import(_example(_V5)))["GET /v1/users"]
    assert {p.name for p in listing.parameters if p.location is ParameterLocation.QUERY} == {"page", "limit"}


def test_whole_variable_parameters_take_their_environment_value_as_default() -> None:
    operation = _operations(_import(_example(_V5)))["GET /v1/users"]
    params = {(p.location, p.name): p for p in operation.parameters}
    assert params[(ParameterLocation.QUERY, "limit")].default == "20"
    assert params[(ParameterLocation.HEADER, "x-tenant")].default == "acme"  # inherited from the folder
    assert params[(ParameterLocation.QUERY, "page")].default is None  # a literal, not a variable


def test_a_secret_variable_never_becomes_a_default() -> None:
    text = _v5(
        [
            _request(
                "{{ _.baseUrl }}/x",
                parameters=[
                    {"name": "key", "value": "{{ _.apiKey }}"},
                    {"name": "tenant", "value": "{{ _.tenantSecret }}"},
                ],
            )
        ],
        environments={
            "name": "Base",
            "data": {"baseUrl": "https://a.example.com", "apiKey": "k-1234", "tenantSecret": "t-1234"},
        },
    )
    operation = _operations(_import(text))["GET /x"]
    assert all(p.default is None for p in operation.parameters)


def test_folder_auth_and_headers_are_inherited() -> None:
    operations = _operations(_import(_example(_V5)))
    assert operations["GET /v1/users"].extras["security"] == ["bearer"]
    assert operations["DELETE /v1/users/{userId}"].extras[AUTH_EXTRAS_KEY][0]["declared_at"] == "Users"
    assert "security" not in operations["GET /health"].extras  # `type: none` at the request
    assert "bearer" in declared_security_schemes(_import(_example(_V5)))


def test_auth_types_resolve_to_schemes_with_public_facts_only() -> None:
    operations = _operations(_import(_example(_STRESS), label="stress.json"))
    assert operations["GET /me"].extras["security"] == ["basic"]  # inherited from the Auth folder
    oauth = operations["GET /oauth/me"].extras[AUTH_EXTRAS_KEY][0]
    assert oauth == {
        "type": "oauth2",
        "scheme": "oauth2",
        "declared_at": "request",
        "grant_type": "authorization_code",
        "token_url": "https://auth.example.com/oauth/token",
        "scopes": ["read:items", "write:items"],
    }
    keyed = operations["GET /keyed"].extras[AUTH_EXTRAS_KEY][0]
    assert (keyed["scheme"], keyed["key_name"], keyed["key_location"]) == ("apiKey", "X-API-Key", "header")
    assert operations["GET /keyed-query"].extras[AUTH_EXTRAS_KEY][0]["key_location"] == "queryParams"
    assert operations["GET /digest"].extras["security"] == ["digest"]
    assert operations["GET /signed"].extras["security"] == ["authorization"]
    assert "security" not in operations["GET /public"].extras
    assert "security" not in operations["GET /off"].extras  # a disabled auth block is no auth


def test_an_api_key_sent_as_a_cookie_is_cookie_auth() -> None:
    text = _v5(
        [
            _request(
                "https://a.example.com/x",
                authentication={"type": "apikey", "key": "sid", "value": "v-1234", "addTo": "cookie"},
            )
        ]
    )
    assert _operations(_import(text))["GET /x"].extras["security"] == ["cookie"]


# ---------------------------------------------------------------------------
# Bodies (as declared)
# ---------------------------------------------------------------------------


def _request_message(operation: Any) -> Any:
    [message] = [m for m in operation.messages if m.role is MessageRole.REQUEST]
    return message


def test_bodies_keep_their_media_type_and_infer_schemas_where_they_can() -> None:
    api = _import(_example(_STRESS), label="stress.json")
    operations = _operations(api)
    types = {t.name: t for t in api.types}
    items = _request_message(operations["POST /items"])  # JSON with a bare {{ _.qty }}
    assert items.content_types == ["application/json"]
    assert {f.name for f in types[items.payload.name].fields} == {"name", "qty", "tags"}
    login = _request_message(operations["POST /login"])
    assert login.content_types == ["application/x-www-form-urlencoded"]
    assert {f.name for f in types[login.payload.name].fields} == {"username", "password"}  # disabled left out
    upload = _request_message(operations["POST /files"])
    assert upload.content_types == ["multipart/form-data"]
    graphql = _request_message(operations["POST /graphql"])
    assert {f.name for f in types[graphql.payload.name].fields} == {"query", "variables"}
    # XML and binary bodies infer nothing; the operation is kept.
    assert not [m for m in operations["POST /legacy"].messages if m.role is MessageRole.REQUEST]
    assert "PUT /blobs/{blobId}" in operations


# ---------------------------------------------------------------------------
# Variables, scopes, servers
# ---------------------------------------------------------------------------


def test_nested_environment_data_and_folder_environments() -> None:
    api = _import(_example(_STRESS), label="stress.json")
    servers = {s.url: s for s in api.servers}
    assert servers["{api_host}"].variables[0].default == "https://geo.example.com"
    assert servers["http://localhost:3000"].variables == []  # a scheme-less URL is http
    operation = _operations(api)["GET /v3/regions/{region}/zones"]
    assert operation.tags == ["Deep / Deeper / Deepest"]
    header = {p.name: p for p in operation.parameters if p.location is ParameterLocation.HEADER}["x-region"]
    assert header.default == "eu"  # from the Deep folder's own environment


def test_a_variable_resolving_to_another_variable_is_followed() -> None:
    text = _v5(
        [_request("{{ _.baseUrl }}/x")],
        environments={"name": "Base", "data": {"host": "api.example.com", "baseUrl": "https://{{ _.host }}/v2"}},
    )
    assert _import(text).servers[0].variables[0].default == "https://api.example.com/v2"


def test_an_undefined_leading_variable_keeps_a_server_without_a_default() -> None:
    api = _import(_v5([_request("{{ _.host }}/x")]))
    assert [(s.url, s.variables[0].default) for s in api.servers] == [("{host}", None)]


def test_a_url_only_an_undefined_variable_is_refused() -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        _import(_v5([_request("{{ _.nowhere }}")]))
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"


def test_a_fileset_with_a_global_environment_imports_as_one_api() -> None:
    folder = _EXAMPLES / "03-environment-set"
    members = {path.name: path.read_text(encoding="utf-8") for path in folder.glob("*.yaml")}
    members["README.md"] = "# notes"
    adapter = _adapter()
    api = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root="orders.insomnia.yaml")))
    assert set(_operations(api)) == {"GET /v2/orders", "GET /v2/orders/{orderId}"}
    assert api.servers[0].variables[0].default == "https://orders.staging.example.com"
    record = api.extras[INSOMNIA_EXTRAS_KEY]
    assert record["export_formats"] == ["v5", "v5"]
    assert {"name": "ordersApiKey", "source": "environment:Staging", "secret": True} in record["variables"]


def test_a_fileset_without_an_export_is_a_format_mismatch() -> None:
    with pytest.raises(InsomniaParseError) as excinfo:
        parse_insomnia_fileset({"notes.md": "# x"}, root="notes.md")
    assert excinfo.value.code == "FORMAT_MISMATCH"


# ---------------------------------------------------------------------------
# Declared limits
# ---------------------------------------------------------------------------


def test_what_is_not_modelled_is_declared() -> None:
    api = _import(_example(_STRESS), label="stress.json")
    limits = {limit["construct"]: limit for limit in api.extras[INSOMNIA_EXTRAS_KEY]["capability_limits"]}
    assert limits["insomnia.grpc_request"]["locations"] == ["Say hello (gRPC)"]
    assert limits["insomnia.websocket_request"]["locations"] == ["Live feed"]
    assert limits["insomnia.unit_test"]["count"] == 2
    assert limits["insomnia.cookie_jar"]["count"] == 1
    assert limits["insomnia.template_tag"]["locations"] == ["Chained token"]
    assert limits["insomnia.script"]["locations"] == ["Nested env value"]
    assert set(limits["insomnia.secret_variable"]["locations"]) == {"clientSecret", "stripeKey"}
    design = _import(_example("07-real-world-v5-design-document.yaml"))
    constructs = {limit["construct"] for limit in design.extras[INSOMNIA_EXTRAS_KEY]["capability_limits"]}
    assert "insomnia.api_spec" in constructs


def test_declared_limits_reach_the_coverage_ledger() -> None:
    api = _import(_example(_STRESS), label="stress.json")
    manifest = build_import_preview_manifest(api, adapter_key="insomnia")
    rows = {row.source_construct: row for row in manifest.document_coverage}
    assert rows["insomnia.auth_credential"].coverage.value == "partially-mapped"
    assert rows["insomnia.grpc_request"].coverage.value == "not-parsed-by-adapter"
    assert rows["insomnia.grpc_request"].detail.startswith("gRPC requests are not HTTP calls")


def test_a_secret_typed_variable_is_listed_secret_and_never_read() -> None:
    api = _import(_example(_STRESS), label="stress.json")
    variables = {v["name"]: v for v in api.extras[INSOMNIA_EXTRAS_KEY]["variables"]}
    assert variables["stripeKey"]["secret"] is True
    assert variables["region"]["secret"] is False


# ---------------------------------------------------------------------------
# Acceptance: secrets redacted
# ---------------------------------------------------------------------------

_PLANTED = [
    "demo-access-token-not-real",
    "demo-password-not-real",
    "demo-basic-not-real",
    "demo-client-secret-not-real",
    "demo-oauth-token-not-real",
    "demo-apikey-not-real",
    "demo-apikey-q-not-real",
    "demo-digest-not-real",
    "demo-iam-not-real",
    "demo-off-not-real",
    "demo-env-secret-not-real",
    "demo-vault-not-real",
    "demo-cookie-not-real",
    "demo-orders-key-not-real",
]


@pytest.mark.parametrize("name", [_V5, _STRESS, "03-environment-set/staging.environment.yaml"])
def test_no_secret_reaches_the_canonical_model(name: str) -> None:
    if name.startswith("03-"):
        folder = _EXAMPLES / "03-environment-set"
        members = {p.name: p.read_text(encoding="utf-8") for p in folder.glob("*.yaml")}
        adapter = _adapter()
        api = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root="orders.insomnia.yaml")))
    else:
        api = _import(_example(name), label=name)
    stored = api.model_dump_json()
    for secret in _PLANTED:
        assert secret not in stored, f"{secret} reached the canonical model"


def test_no_secret_reaches_the_coverage_manifest() -> None:
    api = _import(_example(_STRESS), label="stress.json")
    manifest = build_import_preview_manifest(api, adapter_key="insomnia")
    rendered = repr(manifest.document_coverage) + repr(manifest.entity_rows) + repr(manifest.document_nodes)
    for secret in _PLANTED:
        assert secret not in rendered


def _stored(text: str) -> str:
    intake = _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)
    fields, report = scrub_intake_source(intake)
    assert report["scrubbed"] is True
    for secret in _PLANTED:
        assert secret not in str(report)
    return fields["sourceContent"]


@pytest.mark.parametrize("shape", ["v4-json", "v4-json-compact", "as-yaml", "v5-yaml"])
def test_no_secret_reaches_the_stored_source(shape: str) -> None:
    """The shared scrub gate redacts the stored export, JSON and YAML alike, and keeps it loadable."""
    stress = json.loads(_example(_STRESS))
    if shape == "v4-json":
        text = json.dumps(stress, indent=2)
    elif shape == "v4-json-compact":
        text = json.dumps(stress)
    elif shape == "as-yaml":
        text = yaml.safe_dump(stress, sort_keys=False)
    else:
        text = _example(_V5).replace("accessToken: ''", "accessToken: demo-access-token-not-real")
    stored = _stored(text)
    for secret in _PLANTED:
        assert secret not in stored, f"{secret} persisted in the {shape} source"
    loaded = json.loads(stored) if shape.startswith("v4") else yaml.safe_load(stored)
    assert loaded  # still a readable export
    assert "https://stress.example.com" in stored or "https://api.example.com" in stored


# ---------------------------------------------------------------------------
# Taxonomy codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-bad-indentation.yaml", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-requests.yaml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-v4-mid-resource.json", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-postman.json", "FORMAT_MISMATCH"),
        ("negative/06-version-out-of-range-format-3.json", "FORMAT_VERSION_UNSUPPORTED"),
        ("negative/07-semantic-orphan-parent.json", "INPUT_SEMANTIC_INVALID"),
        ("negative/08-semantic-environment-alone.yaml", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_negative_corpus_codes(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        _import(_example(name), label=name)
    assert excinfo.value.code == code


def test_utf16_upload_is_an_encoding_fault() -> None:
    text = (_EXAMPLES / "negative/05-encoding-utf16.json").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(InsomniaParseError) as excinfo:
        parse_insomnia_text(text)
    assert excinfo.value.code == "INPUT_ENCODING_INVALID"


@pytest.mark.parametrize(
    ("text", "code", "phrase"),
    [
        ("type: collection.insomnia.rest/4.0\ncollection: []\n", "FORMAT_VERSION_UNSUPPORTED", "v4 document"),
        ("type: mock.insomnia.rest/5.0\nname: M\n", "INPUT_SEMANTIC_INVALID", "mock server"),
        (
            "type: spec.insomnia.rest/5.0\nname: S\nspec:\n  contents: 'openapi: 3.0.0'\ncollection: []\n",
            "INPUT_SEMANTIC_INVALID",
            "imports as OpenAPI",
        ),
        (
            _v5([{"url": "wss://a.example.com/feed", "name": "Feed"}]),
            "INPUT_SEMANTIC_INVALID",
            "websocket requests",
        ),
        ('type: collection.insomnia.rest/5.0\ncollection: [{"url": "x"', "INPUT_TRUNCATED", "truncated"),
        ("type: collection.insomnia.rest/5.0\ncollection: {a: 1}\n", "INPUT_MALFORMED", "must be a list"),
        (_v5([_request("https://a.example.com/x", method="")]), "INPUT_MALFORMED", "no method"),
        (_v5([{"name": "No URL", "method": "GET"}]), "INPUT_SEMANTIC_INVALID", "no URL"),
    ],
)
def test_refusals(text: str, code: str, phrase: str) -> None:
    with pytest.raises(InsomniaParseError) as excinfo:
        parse_insomnia_text(text)
    assert excinfo.value.code == code
    assert phrase in str(excinfo.value)


def test_an_unreachable_v4_folder_cycle_never_loops() -> None:
    export = {
        "_type": "export",
        "__export_format": 4,
        "resources": [
            {"_id": "wrk_1", "_type": "workspace", "name": "W"},
            {"_id": "fld_a", "parentId": "fld_b", "_type": "request_group", "name": "A"},
            {"_id": "fld_b", "parentId": "fld_a", "_type": "request_group", "name": "B"},
            {
                "_id": "req_1",
                "parentId": "wrk_1",
                "_type": "request",
                "name": "R",
                "method": "GET",
                "url": "https://a.example.com/",
            },
        ],
    }
    # The cycle is unreachable from the workspace, so it imports what is reachable and never loops.
    document = parse_insomnia_text(json.dumps(export))
    assert [request.name for request in document.requests] == ["R"]


@pytest.mark.parametrize(
    "resources",
    [{"x": 1}, [1], [{"_id": "a"}]],
)
def test_v4_structural_faults_are_malformed(resources: Any) -> None:
    with pytest.raises(InsomniaParseError) as excinfo:
        parse_insomnia_text(json.dumps({"_type": "export", "__export_format": 4, "resources": resources}))
    assert excinfo.value.code == "INPUT_MALFORMED"


def test_normalize_rejects_a_foreign_ast() -> None:
    with pytest.raises(ImportSourceError):
        _adapter().normalize({"_type": "export"})
