"""The Azure API Management import source (FMT-7.2, #5456).

Drives the adapter over the committed corpus (``apiome-ui/examples/azure-apim``) and small inline
documents. Covers the acceptance criteria: an APIM export with a policy document imports and its
policies map to canonical constructs; unmapped policies are preserved in extras and reported on
the coverage ledger; definition-derived facts are told apart from policy-derived ones; and the
corpus covers an OpenAPI-backed API with policies and a SOAP pass-through API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from app.azure_apim_arm import has_apim_markers, openapi_for_estate, read_arm_template
from app.azure_apim_import_source import AzureApimImportSource, policy_member_scope
from app.azure_apim_policies import (
    PolicyError,
    ScopedPolicy,
    compose,
    interpret,
    is_policy_text,
    named_value_references,
    read_policy_xml,
    verbatim_xml,
)
from app.canonical_security import operation_security_schemes
from app.fileset import IntakeFileset
from app.format_detection import detect_format
from app.import_preview_manifest import (
    CoverageClass,
    build_import_preview_manifest,
    paginate_import_preview_manifest,
)
from app.import_routing import decide_import_routing
from app.import_source import DetectionInput, ImportSourceError
from app.openapi_import_source import OpenApiImportSource

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "azure-apim"
POLICY_SET = EXAMPLES / "03-api-with-policy-set"


@pytest.fixture
def adapter() -> AzureApimImportSource:
    return AzureApimImportSource()


def _model(adapter: AzureApimImportSource, name: str):
    text = (EXAMPLES / name).read_text(encoding="utf-8")
    return adapter.normalize(adapter.parse(text, source_label=name))


def _fileset_model(adapter: AzureApimImportSource, members: Dict[str, str], root: str):
    return adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root=root)))


def _policy_set(adapter: AzureApimImportSource):
    members = {p.name: p.read_text(encoding="utf-8") for p in POLICY_SET.iterdir()}
    return _fileset_model(adapter, members, "orders.openapi.yaml")


def _ops(model) -> Dict[str, Any]:
    return {op.key: op for op in model.operations()}


def _ledger(model) -> Dict[str, Any]:
    page = paginate_import_preview_manifest(build_import_preview_manifest(model, adapter_key="azure-apim", options={}))
    return {row.source_construct: row for row in page.coverage}


def _policy(inbound: str = "", outbound: str = "") -> str:
    return (
        f"<policies><inbound>{inbound}</inbound><backend><base /></backend>"
        f"<outbound>{outbound}</outbound><on-error><base /></on-error></policies>"
    )


# --- acceptance: an export with its policy document imports ----------------------------


def test_a_definition_with_its_policy_document_imports(adapter):
    model = _policy_set(adapter)
    assert model.format == "azure-apim"
    assert set(_ops(model)) == {"GET /orders", "GET /orders/{orderId}", "POST /orders"}
    assert model.extras["azure_apim"]["shape"] == "definition+policy"
    # The API-scope backend URL becomes a server named backend, after the gateway server.
    assert [(s.url, s.name) for s in model.servers] == [
        ("https://example-apim.azure-api.net/orders", None),
        ("https://orders.internal.example.com/v2", "backend"),
    ]


def test_policies_map_to_canonical_constructs(adapter):
    op = _ops(_policy_set(adapter))["GET /orders"]
    by_name = {record["name"]: record for record in op.extras["security"]}
    jwt = by_name["validate-jwt"]
    assert jwt["scheme"] == "openIdConnect"
    assert jwt["openIdConnectUrl"] == "https://login.example.com/.well-known/openid-configuration"
    assert jwt["scopes"] == ["orders.read", "orders.write"]
    assert [c["name"] for c in jwt["requiredClaims"]] == ["aud", "scp"]

    limits = {r["policy"]: r for r in op.extras["rate_limits"]}
    assert limits["rate-limit-by-key"]["calls"] == 1000 and limits["rate-limit-by-key"]["renewalPeriodSeconds"] == 60
    assert limits["quota-by-key"]["kind"] == "quota" and limits["quota-by-key"]["bandwidthKilobytes"] == 4096

    assert op.extras["backend"]["uri"] == "https://orders.internal.example.com/v2"
    assert op.extras["rewrite"] == {
        "provenance": "declared",
        "derivedFrom": "policy",
        "policyScope": "api",
        "uriTemplate": "/v2{path}",
        "copyUnmatchedParams": True,
    }
    cors = op.extras["cors"]
    assert cors["allowOrigins"] == ["https://app.example.com"] and cors["allowCredentials"] is True
    assert cors["maxAge"] == 600


def test_definition_and_policy_facts_are_told_apart(adapter):
    op = _ops(_policy_set(adapter))["GET /orders"]
    origins = {(r["name"], r["derivedFrom"]) for r in op.extras["security"]}
    assert origins == {("apiKeyHeader", "definition"), ("validate-jwt", "policy")}
    for key in ("rate_limits",):
        assert all(r["derivedFrom"] == "policy" and r["policyScope"] == "api" for r in op.extras[key])
    assert all(r["provenance"] == "declared" for r in op.extras["security"])
    # canonical_security reads both: the subscription key and the bearer token.
    schemes, scope = operation_security_schemes(_policy_set(adapter), op)
    assert scope == "operation" and schemes == ["apiKey", "openIdConnect"]


def test_definition_backend_is_overridden_by_a_policy_backend(adapter):
    model = _model(adapter, "02-typical-arm-api.json")
    op = _ops(model)["GET /orders"]
    assert op.extras["backend"]["derivedFrom"] == "policy"
    template = {
        "resources": [
            {
                "type": "Microsoft.ApiManagement/service/apis",
                "name": "svc/a",
                "properties": {"path": "a", "serviceUrl": "https://backend.example.com"},
            },
            {
                "type": "Microsoft.ApiManagement/service/apis/operations",
                "name": "svc/a/list",
                "properties": {"method": "GET", "urlTemplate": "/items"},
            },
        ]
    }
    plain = adapter.normalize(adapter._structured_native(template, None))
    backend = _ops(plain)["GET /items"].extras["backend"]
    assert backend == {
        "kind": "http",
        "uri": "https://backend.example.com",
        "provenance": "declared",
        "derivedFrom": "definition",
    }


# --- acceptance: unmapped policies are preserved and visible --------------------------


def test_an_unmapped_policy_is_preserved_verbatim_and_reported(adapter):
    model = _model(adapter, "04-stress-policy-vocabulary.xml")
    unmapped = {u["name"]: u for u in model.extras["azure_apim"]["unmapped"]}
    unknown = unmapped["example-unknown-policy"]
    assert unknown["status"] == "unknown" and unknown["section"] == "inbound"
    assert 'owner="platform-team"' in unknown["xml"] and "Vendor-specific policy" in unknown["xml"]
    assert unmapped["cache-lookup"]["status"] == "preserved"
    assert unmapped["send-request"]["status"] == "preserved"

    rows = _ledger(model)
    row = rows["apim#unknown-policy.example-unknown-policy"]
    assert row.coverage is CoverageClass.PARTIALLY_MAPPED and "never dropped" in row.detail
    assert rows["apim#policy.json-to-xml"].coverage is CoverageClass.PARTIALLY_MAPPED
    assert rows["apim#policy.validate-jwt"].coverage is CoverageClass.MAPPED
    assert rows["apim#backend.lab-backend"].coverage is CoverageClass.PARTIALLY_MAPPED


def test_mapped_policies_inside_choose_and_retry_are_conditional(adapter):
    text = _policy(
        inbound='<choose><when condition="@(true)"><rate-limit calls="5" renewal-period="1" /></when></choose>'
    )
    model = adapter.normalize(adapter.parse(text))
    (limit,) = model.extras["rate_limits"]
    assert limit["conditional"] is True and limit["calls"] == 5
    assert model.extras["azure_apim"]["unmapped"][0]["name"] == "choose"


def test_an_operation_policy_attaches_to_its_operation(adapter):
    model = _model(adapter, "02-typical-arm-api.json")
    ops = _ops(model)
    get_order = ops["GET /orders/{orderId}"]
    assert get_order.extras["rewrite"]["uriTemplate"] == "/v2/orders/{orderId}"
    assert get_order.extras["rewrite"]["policyScope"] == "operation"
    assert [u["name"] for u in get_order.extras["azure_apim"]["unmapped"]] == ["cache-lookup", "cache-store"]
    # The API-scope rate limit is inherited through <base /> on both operations.
    assert get_order.extras["rate_limits"][0]["policyScope"] == "api"
    assert "rewrite" not in ops["GET /orders"].extras


# --- acceptance: corpus shapes ---------------------------------------------------------


def test_a_soap_pass_through_api_imports_one_operation_per_action(adapter):
    model = _model(adapter, "05-real-world-soap-passthrough-arm.json")
    assert set(_ops(model)) == {
        "POST /?soapAction=http://example.com/billing/GetInvoice",
        "POST /?soapAction=http://example.com/billing/ListInvoices",
    }
    op = next(iter(model.operations()))
    assert op.extras["backend"]["authentication"] == {"type": "certificate", "thumbprint": "0" * 40}
    assert op.extras["access"][0]["addressRanges"] == [{"from": "10.20.0.0", "to": "10.20.255.255"}]
    report = model.extras["azure_apim"]
    assert report["products"][0]["name"] == "internal-only"
    assert report["products"][0]["apis"] == ["legacy-billing-soap"]
    assert report["backends"][0]["id"] == "legacy-billing-backend"
    assert report["apis"][0]["apiType"] == "soap"


def test_a_version_set_records_both_versions(adapter):
    model = _model(adapter, "06-typical-arm-api-versionset.json")
    report = model.extras["azure_apim"]
    assert [(a["name"], a["isCurrent"]) for a in report["apis"]] == [("catalogue-v1", False), ("catalogue-v2", True)]
    assert report["versionSets"][0]["versioningScheme"] == "Segment"
    assert set(_ops(model)) == {"GET /products", "GET /products/{sku}"}


def test_base_composes_scopes_in_evaluation_order(adapter):
    model = _model(adapter, "07-composition-policy-inheritance.xml")
    report = model.extras["azure_apim"]
    assert report["shape"] == "policy-composition"
    scopes = [r["policyScope"] for r in model.extras["rate_limits"]]
    assert scopes == ["global", "product"]
    operation = report["unattachedOperations"]["orders-api/get-order"]
    assert operation["rewrite"]["uriTemplate"] == "/v2/orders/{orderId}"
    # <base /> follows the local cache-lookup: the operation's cache-lookup runs first.
    root = read_policy_xml((EXAMPLES / "07-composition-policy-inheritance.xml").read_text())
    from app.azure_apim_policies import read_composition

    docs = {p.scope: p for p in read_composition(root)}
    api_pipeline, _ = compose(docs["api"], None)
    op_pipeline, _ = compose(docs["operation"], api_pipeline)
    names = [item.element.tag for item in op_pipeline["inbound"]]
    assert names[:3] == ["cache-lookup", "base", "validate-jwt"]


def test_a_lone_policy_document_has_no_operations(adapter):
    model = _model(adapter, "01-minimal-policy.xml")
    assert model.operations() == []
    assert [s.url for s in model.servers] == ["https://orders.internal.example.com"]
    assert model.extras["azure_apim"]["apiPolicy"]["inheritsFromParentScope"] == [
        "inbound",
        "backend",
        "outbound",
        "on-error",
    ]
    assert _ledger(model)["apim#base"].coverage is CoverageClass.PARTIALLY_MAPPED


# --- detection -------------------------------------------------------------------------


def test_an_apim_definition_beats_openapi_without_ambiguity(adapter):
    text = (POLICY_SET / "orders.openapi.yaml").read_text()
    detection = detect_format(DetectionInput(text=text))
    assert detection.detected.source_key == "azure-apim" and not detection.ambiguous
    openapi = OpenApiImportSource().detect(DetectionInput(text=text))
    assert openapi.confidence == 0.7 and openapi.format == "openapi-3.0"


def test_a_plain_openapi_document_stays_with_openapi(adapter):
    document = {"openapi": "3.0.1", "info": {"title": "t", "version": "1"}, "servers": [{"url": "https://x.example"}]}
    assert has_apim_markers(document) is False
    assert adapter.detect(DetectionInput(document=document)).matched is False
    with pytest.raises(ImportSourceError) as info:
        adapter._structured_native(document, None)
    assert info.value.code == "FORMAT_MISMATCH"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<policies><inbound /></policies>", True),
        ('<?xml version="1.0"?>\n<!-- c -->\n<policies>', True),
        ("<policies-composition>", True),
        ("<policiesX>", False),
        ("<definitions/>", False),
        ("", False),
    ],
)
def test_policy_sniff(text, expected):
    assert is_policy_text(text) is expected


def test_an_arm_template_is_claimed(adapter):
    text = (EXAMPLES / "02-typical-arm-api.json").read_text()
    result = adapter.detect(DetectionInput(text=text))
    assert result.matched and result.confidence == 0.95


# --- rejections ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    [
        ("01-syntactic-unclosed-policy.xml", "INPUT_MALFORMED"),
        ("02-semantic-policy-without-sections.xml", "INPUT_SEMANTIC_INVALID"),
        ("03-truncated-mid-policy.xml", "INPUT_TRUNCATED"),
        ("04-wrong-format-kong.yaml", "FORMAT_MISMATCH"),
        ("06-unresolvable-backend-reference.xml", "INPUT_REFERENCE_UNRESOLVED"),
    ],
)
def test_negative_fixtures_fail_with_their_code(adapter, name, code):
    with pytest.raises(ImportSourceError) as info:
        adapter.parse((EXAMPLES / "negative" / name).read_text(), source_label=name)
    assert info.value.code == code


def test_utf16_is_an_encoding_error(adapter):
    text = (EXAMPLES / "negative" / "05-encoding-utf16.xml").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(ImportSourceError) as info:
        adapter.parse(text)
    assert info.value.code == "INPUT_ENCODING_INVALID"


def test_a_declared_named_value_resolves(adapter):
    policy = _policy(inbound='<set-header name="X" exists-action="override"><value>{{shared}}</value></set-header>')
    template = {
        "resources": [{"type": "Microsoft.ApiManagement/service/namedValues", "name": "svc/shared", "properties": {}}]
    }
    import json

    members = {"policy.xml": policy, "service.json": json.dumps(template)}
    native = adapter.parse_fileset(IntakeFileset.from_members(members, root="policy.xml"))
    assert adapter.normalize(native).extras["azure_apim"]["namedValues"] == ["shared"]


def test_a_backend_id_missing_from_declared_backends_is_rejected(adapter):
    xml = _policy(inbound='<set-backend-service backend-id="ghost" />').replace('"', '\\"')
    text = (
        '{"resources": ['
        '{"type": "Microsoft.ApiManagement/service/backends", "name": "svc/real", "properties": {"url": "https://r"}},'
        '{"type": "Microsoft.ApiManagement/service/policies", "name": "svc/policy",'
        f' "properties": {{"format": "xml", "value": "{xml}"}}}}]}}'
    )
    with pytest.raises(ImportSourceError) as info:
        adapter.parse(text)
    assert info.value.code == "INPUT_REFERENCE_UNRESOLVED" and "ghost" in str(info.value)


def test_a_declared_backend_id_resolves_to_its_url(adapter):
    xml = _policy(inbound='<set-backend-service backend-id="real" />').replace('"', '\\"')
    text = (
        '{"resources": ['
        '{"type": "Microsoft.ApiManagement/service/backends", "name": "svc/real", "properties": {"url": "https://r"}},'
        '{"type": "Microsoft.ApiManagement/service/apis", "name": "svc/a", "properties": {"path": "a"}},'
        '{"type": "Microsoft.ApiManagement/service/apis/operations", "name": "svc/a/op",'
        ' "properties": {"method": "GET", "urlTemplate": "/x"}},'
        '{"type": "Microsoft.ApiManagement/service/apis/policies", "name": "svc/a/policy",'
        f' "properties": {{"format": "xml", "value": "{xml}"}}}}]}}'
    )
    model = adapter.normalize(adapter.parse(text))
    backend = _ops(model)["GET /x"].extras["backend"]
    assert backend["uri"] == "https://r" and backend["resolved"] is True and backend["backendId"] == "real"


# --- fileset member scoping -----------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("policy.xml", ("api", None)),
        ("api.policy.xml", ("api", None)),
        ("operations/get-order.xml", ("operation", "get-order")),
        ("get-order.policy.xml", ("operation", "get-order")),
        ("products/starter.xml", ("product", "starter")),
        ("global.xml", ("global", None)),
    ],
)
def test_policy_member_scope(path, expected):
    assert policy_member_scope(path) == expected


def test_operation_policy_members_attach_by_operation_id(adapter):
    members = {p.name: p.read_text(encoding="utf-8") for p in POLICY_SET.iterdir()}
    members["operations/create-order.xml"] = _policy(
        inbound='<base /><rate-limit calls="10" renewal-period="60" /><cache-lookup vary-by-developer="false" '
        'vary-by-developer-groups="false" />',
        outbound="<base />",
    )
    model = _fileset_model(adapter, members, "orders.openapi.yaml")
    create = _ops(model)["POST /orders"]
    scopes = [r["policyScope"] for r in create.extras["rate_limits"]]
    assert scopes == ["api", "api", "operation"]
    assert create.extras["azure_apim"]["policyScopes"] == ["api", "operation"]
    assert [u["name"] for u in create.extras["azure_apim"]["unmapped"]] == ["cache-lookup"]
    assert len(_ops(model)["GET /orders"].extras["rate_limits"]) == 2


# --- routing and lint ------------------------------------------------------------------


def test_an_import_routes_to_the_catalog_and_lints(adapter):
    for model in (
        _policy_set(adapter),
        _model(adapter, "02-typical-arm-api.json"),
        _model(adapter, "01-minimal-policy.xml"),
    ):
        assert decide_import_routing(adapter, model).publishable is False
        assert adapter.lint(model) is not None


def test_normalize_without_raw_drops_the_native_ast(adapter):
    text = (EXAMPLES / "01-minimal-policy.xml").read_text()
    assert adapter.normalize(adapter.parse(text), include_raw=False).raw is None


# --- pure helpers ----------------------------------------------------------------------


def test_credentials_never_reach_records_or_verbatim_xml():
    root = read_policy_xml(
        _policy(
            inbound='<authentication-basic username="svc" password="hunter2" />'
            '<send-request mode="new"><authentication-certificate thumbprint="ab" password="pw" /></send-request>'
        )
    )
    pipeline, _ = compose(ScopedPolicy("api", root), None)
    facts = interpret(pipeline)
    assert facts.backend["authentication"] == {"type": "basic", "username": "svc", "hasSecret": True}
    xml = facts.unmapped[0]["xml"]
    assert "pw" not in xml and "[redacted]" in xml
    assert "hunter2" not in verbatim_xml(root)


def test_named_value_references():
    assert named_value_references("<a>{{ one }}</a><b x='{{two}}'/>{{one}}") == ["one", "two"]


def test_a_non_policy_xml_root_is_a_format_mismatch():
    with pytest.raises(PolicyError) as info:
        read_policy_xml("<definitions />")
    assert info.value.code == "FORMAT_MISMATCH"


def test_arm_names_resolve_parameters_and_nested_resources():
    template = {
        "parameters": {"svc": {"type": "string", "defaultValue": "prod-apim"}},
        "resources": [
            {
                "type": "Microsoft.ApiManagement/service",
                "name": "[parameters('svc')]",
                "resources": [
                    {
                        "type": "apis",
                        "name": "[concat(parameters('svc'), '/pets')]",
                        "properties": {"path": "pets", "subscriptionRequired": True},
                    },
                ],
            },
            {
                "type": "Microsoft.ApiManagement/service/apis/operations",
                "name": "[concat(parameters('svc'), '/pets/list')]",
                "properties": {
                    "method": "GET",
                    "urlTemplate": "/pets",
                    "request": {"queryParameters": [{"name": "limit", "type": "integer", "defaultValue": "10"}]},
                    "responses": [{"statusCode": 200, "representations": [{"contentType": "application/json"}]}],
                },
            },
        ],
    }
    estate = read_arm_template(template)
    assert estate.service == "prod-apim" and [a.name for a in estate.apis] == ["pets"]
    document, owners, collisions = openapi_for_estate(estate)
    assert document["servers"] == [{"url": "https://prod-apim.azure-api.net/pets"}]
    op = document["paths"]["/pets"]["get"]
    assert op["parameters"][0]["schema"] == {"type": "integer", "default": 10}
    assert op["security"] == [{"apiKeyHeader": []}, {"apiKeyQuery": []}]
    assert op["responses"]["200"]["content"] == {"application/json": {}}
    assert owners == {("GET", "/pets"): ("pets", "list")} and collisions == []


def test_several_apis_are_prefixed_with_their_paths():
    template = {
        "resources": [
            {"type": "Microsoft.ApiManagement/service/apis", "name": "s/a", "properties": {"path": "a"}},
            {"type": "Microsoft.ApiManagement/service/apis", "name": "s/b", "properties": {"path": "b"}},
            {
                "type": "Microsoft.ApiManagement/service/apis/operations",
                "name": "s/a/x",
                "properties": {"method": "GET", "urlTemplate": "/"},
            },
            {
                "type": "Microsoft.ApiManagement/service/apis/operations",
                "name": "s/b/y",
                "properties": {"method": "GET", "urlTemplate": "/items"},
            },
        ]
    }
    document, owners, _ = openapi_for_estate(read_arm_template(template))
    assert document["servers"] == [{"url": "https://s.azure-api.net"}]
    assert set(document["paths"]) == {"/a", "/b/items"}
    assert owners[("GET", "/b/items")] == ("b", "y")


def test_an_operation_rewrite_after_the_api_rewrite_reports_the_operation_scope(adapter):
    members = {p.name: p.read_text(encoding="utf-8") for p in POLICY_SET.iterdir()}
    members["operations/get-order.xml"] = _policy(inbound='<base /><rewrite-uri template="/v3/orders/{orderId}" />')
    rewrite = _ops(_fileset_model(adapter, members, "orders.openapi.yaml"))["GET /orders/{orderId}"].extras["rewrite"]
    assert rewrite["uriTemplate"] == "/v3/orders/{orderId}" and rewrite["policyScope"] == "operation"
    assert rewrite["copyUnmatchedParams"] is True  # the API scope's field is kept


def test_the_definition_is_the_root_even_when_another_member_is_named_root(adapter):
    members = {p.name: p.read_text(encoding="utf-8") for p in POLICY_SET.iterdir()}
    members["service.json"] = (
        '{"resources": [{"type": "Microsoft.ApiManagement/service/backends", "name": "s/b", "properties": {}}]}'
    )
    for root in ("service.json", "policy.xml"):
        model = _fileset_model(adapter, members, root)
        assert model.extras["azure_apim"]["shape"] == "definition+policy" and len(model.operations()) == 3
