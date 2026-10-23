"""SoapUI / ReadyAPI project import — FMT-10.3 (#5477).

Covers the reader (:mod:`app.soapui_parser`), the normalizer (:mod:`app.soapui_normalizer`), the
adapter (:mod:`app.soapui_import_source`) and the declared-test-intent record
(:mod:`app.declared_test_intent`) against the acceptance criteria:

* a **SOAP project** and a **REST project** both import;
* **WSDL-backed interfaces reuse the WSDL adapter** and match its goldens — every WSDL corpus golden
  is reproduced exactly when that WSDL sits behind a SoapUI interface;
* **test suites are recorded as declared test intent**, linked to the operations they call, and
  visible on the catalog item (the parsed view's *Declared tests* group);
* **credentials in saved requests are scrubbed** — never in the canonical model, the coverage
  manifest or the persisted source;
* the corpus (a SOAP project, a REST project, a project with a missing WSDL) is exercised here and
  by the shared corpus suites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.canonical_model import CanonicalApi, MessageRole, OperationKind, ParameterLocation
from app.catalog_parsed_model import derive_parsed_model
from app.declared_test_intent import DECLARED_TESTS_EXTRAS_KEY, build_declared_tests, declared_tests_of
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
from app.inference_provenance import DECLARED, INFERRED, provenance_of
from app.intake_secret_scrub import scrub_document_text
from app.soapui_normalizer import AUTH_EXTRAS_KEY, SOAPUI_EXTRAS_KEY
from app.soapui_parser import SoapUiParseError, is_soapui_project, parse_soapui_fileset, parse_soapui_text
from app.wsdl_normalizer import WsdlNormalizer
from app.wsdl_parser import parse_wsdl

load_builtin_import_sources()

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _ROOT / "apiome-ui" / "examples" / "soapui"
_WSDL_EXAMPLES = _ROOT / "apiome-ui" / "examples" / "wsdl"
_WSDL_GOLDENS = Path(__file__).resolve().parent / "golden" / "corpus" / "wsdl"
_SET = "03-wsdl-set"

_NS = "http://eviware.com/soapui/config"

# Credential literals are assembled from fragments so no realistic secret is committed verbatim.
_PASSWORD = "Pa55" + "-word-" + "rest-call"
_WSS_PASSWORD = "wss" + "-envelope-" + "s3cret"
_API_KEY = "key" + "-live-" + "0f9e8d7c6b5a"
_HEADER_TOKEN = "hdr" + "Tok" + "AAbbCCddEEff0011"
_PROPERTY_SECRET = "prop" + "-secret-" + "value-42"
_USERINFO = "user" + "info" + "Pw99"
_PLANTED = (_PASSWORD, _WSS_PASSWORD, _API_KEY, _HEADER_TOKEN, _PROPERTY_SECRET, _USERINFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detected(text: str) -> Optional[str]:
    """The registry key of the adapter registry-wide detection picks for ``text``."""
    best = detect_import_source(DetectionInput(text=text))
    return best[0].key if best else None


def _adapter():
    return get_import_source("soapui")


def _example(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _import(text: str, label: str = "project.xml") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=label))


def _import_set(members: Dict[str, str], root: str = "project.xml") -> CanonicalApi:
    adapter = _adapter()
    fileset = IntakeFileset.from_members(members, root=root)
    return adapter.normalize(adapter.parse_fileset(fileset, source_label=root))


def _example_set() -> Dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted((_EXAMPLES / _SET).iterdir())}


def _operations(api: CanonicalApi) -> Dict[str, Any]:
    return {op.key: op for service in api.services for op in service.operations}


def _project(body: str, *, name: str = "Test project", properties: str = "") -> str:
    """A SoapUI project document around ``body`` (interfaces, suites, mocks)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<con:soapui-project xmlns:con="{_NS}" name="{name}" soapui-version="5.7.0">\n'
        "  <con:settings/>\n"
        f"{body}\n"
        f"  <con:properties>{properties}</con:properties>\n"
        "</con:soapui-project>\n"
    )


def _rest_interface(
    resources: str, *, name: str = "Orders", base_path: str = "/v1", endpoint: str = "https://api.example.com"
) -> str:
    return (
        f'<con:interface xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="con:RestService" '
        f'name="{name}" type="rest" basePath="{base_path}">\n'
        f"  <con:endpoints><con:endpoint>{endpoint}</con:endpoint></con:endpoints>\n"
        f"{resources}\n"
        "</con:interface>"
    )


def _wsdl_interface(*, name: str, definition: str, cache: str = "", operations: str = "") -> str:
    return (
        f'<con:interface xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="con:WsdlInterface" '
        f'name="{name}" type="wsdl" soapVersion="1_1" definition="{definition}">\n'
        f'  <con:definitionCache type="TEXT" rootPart="{definition}">{cache}</con:definitionCache>\n'
        f"{operations}\n"
        "</con:interface>"
    )


def _cached_part(url: str, text: str) -> str:
    return f"<con:part><con:url>{url}</con:url><con:content><![CDATA[{text}]]></con:content></con:part>"


def _property(name: str, value: str) -> str:
    return f"<con:property><con:name>{name}</con:name><con:value>{value}</con:value></con:property>"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_claims_a_project_with_confidence() -> None:
    result = _adapter().detect(DetectionInput(text=_example("01-minimal-project.xml")))
    assert result.format == "soapui"
    assert result.confidence >= 0.9


def test_detect_claims_a_truncated_project_so_parse_can_refuse_it() -> None:
    assert _adapter().detect(DetectionInput(text=_example("negative/03-truncated-mid-operation.xml"))).confidence >= 0.9


@pytest.mark.parametrize("name", ["01-minimal-project.xml", "05-real-world-soap-project.xml"])
def test_registry_detection_routes_projects_to_soapui(name: str) -> None:
    assert _detected(_example(name)) == "soapui"


def test_a_bare_wsdl_is_not_claimed_and_still_detects_as_wsdl() -> None:
    text = (_EXAMPLES / _SET / "catalogue.wsdl").read_text(encoding="utf-8")
    assert not is_soapui_project(text)
    assert not _adapter().detect(DetectionInput(text=text)).matched
    assert _detected(text) == "wsdl"


def test_a_root_without_the_soapui_namespace_is_not_claimed() -> None:
    assert not is_soapui_project('<soapui-project name="x"><interface/></soapui-project>')


# ---------------------------------------------------------------------------
# REST projects
# ---------------------------------------------------------------------------


def test_a_rest_project_imports() -> None:
    api = _import(_example("02-typical-rest-project.xml"))
    assert api.format == "soapui"
    assert api.identity.name == "Orders API"
    assert sorted(_operations(api)) == [
        "DELETE /v2/orders/{orderId}",
        "GET /v2/orders",
        "GET /v2/orders/{orderId}",
        "POST /v2/orders",
    ]
    assert [server.url for server in api.servers] == ["https://api.example.com", "https://staging.example.com"]


def test_rest_operations_are_inferred_by_the_shared_engine() -> None:
    api = _import(_example("02-typical-rest-project.xml"))
    for operation in _operations(api).values():
        assert provenance_of(operation.extras) == INFERRED
        assert operation.tags == ["Orders"]


def test_query_and_template_parameters() -> None:
    operations = _operations(_import(_example("02-typical-rest-project.xml")))
    listing = {(p.name, p.location) for p in operations["GET /v2/orders"].parameters}
    assert listing == {("status", ParameterLocation.QUERY), ("limit", ParameterLocation.QUERY)}
    detail = {(p.name, p.location) for p in operations["GET /v2/orders/{orderId}"].parameters}
    assert detail == {("orderId", ParameterLocation.PATH)}


def test_saved_body_infers_a_request_schema_and_representation_status() -> None:
    operation = _operations(_import(_example("02-typical-rest-project.xml")))["POST /v2/orders"]
    [request] = [m for m in operation.messages if m.role is MessageRole.REQUEST]
    assert request.payload is not None
    assert request.content_types == ["application/json"]
    assert [m.status_code for m in operation.messages if m.role is MessageRole.RESPONSE] == ["201"]


def test_nested_resources_inherit_path_and_parameters() -> None:
    resources = """
      <con:resource name="orders" path="/orders">
        <con:parameters><con:parameter><con:name>tenant</con:name><con:value>acme</con:value><con:style>HEADER</con:style></con:parameter></con:parameters>
        <con:resource name="order" path="{orderId}">
          <con:method name="getOrder" method="GET"/>
        </con:resource>
      </con:resource>"""
    operation = _operations(_import(_project(_rest_interface(resources))))["GET /v1/orders/{orderId}"]
    assert {(p.name, p.location) for p in operation.parameters} == {
        ("orderId", ParameterLocation.PATH),
        ("tenant", ParameterLocation.HEADER),
    }


def test_a_method_without_saved_requests_still_becomes_an_operation() -> None:
    resources = '<con:resource name="health" path="/health"><con:method name="health" method="GET"/></con:resource>'
    assert list(_operations(_import(_project(_rest_interface(resources))))) == ["GET /v1/health"]


def test_property_endpoint_becomes_a_server_variable_with_the_property_default() -> None:
    api = _import(_example("07-composition-shared-endpoints.xml"))
    [templated] = [server for server in api.servers if server.url == "{apiBaseUrl}"]
    assert templated.variables[0].default == "https://acc.example.com"
    assert {"https://acc.example.com", "https://api.example.com"} <= {server.url for server in api.servers}
    tags = {op.key: op.tags for op in _operations(api).values()}
    assert tags == {"GET /v2/orders": ["Orders"], "GET /v2/products": ["Catalogue"]}


def test_a_secret_named_property_never_becomes_a_server_default() -> None:
    resources = (
        '<con:resource name="x" path="/x"><con:method name="x" method="GET"><con:request name="r">'
        "<con:endpoint>${#Project#apiToken}</con:endpoint></con:request></con:method></con:resource>"
    )
    text = _project(
        _rest_interface(resources, endpoint="${#Project#apiToken}"), properties=_property("apiToken", _PROPERTY_SECRET)
    )
    api = _import(text)
    [templated] = [server for server in api.servers if server.url == "{apiToken}"]
    assert templated.variables[0].default is None
    assert _PROPERTY_SECRET not in api.model_dump_json()
    assert {"name": "apiToken", "secret": True} in api.extras[SOAPUI_EXTRAS_KEY]["properties"]


def test_mock_responses_become_response_schemas_of_the_operation_they_answer() -> None:
    api = _import(_example("06-typical-mock-service.xml"))
    operation = _operations(api)["GET /v2/orders"]
    responses = {m.status_code: m for m in operation.messages if m.role is MessageRole.RESPONSE}
    assert sorted(responses) == ["200", "401"]
    assert all(message.payload is not None for message in responses.values())
    [mock] = api.extras[SOAPUI_EXTRAS_KEY]["mock_services"]
    assert mock == {"name": "Orders REST MockService", "kind": "rest", "actions": 1, "responses": 2}


def test_a_method_without_a_verb_is_malformed() -> None:
    resources = '<con:resource name="x" path="/x"><con:method name="broken"/></con:resource>'
    with pytest.raises(SoapUiParseError) as caught:
        parse_soapui_text(_project(_rest_interface(resources)))
    assert caught.value.code == "INPUT_MALFORMED"


# ---------------------------------------------------------------------------
# SOAP projects — WSDL delegation
# ---------------------------------------------------------------------------


def test_a_soap_project_imports_with_its_wsdl_beside_it() -> None:
    api = _import_set(_example_set())
    operation = _operations(api)["http://example.com/catalogue.CatalogueServicePortType.GetProduct"]
    assert operation.kind is OperationKind.REQUEST_RESPONSE
    assert {type_.name for type_ in api.types} == {"GetProductRequest", "GetProductResponse"}
    interface = api.extras[SOAPUI_EXTRAS_KEY]["interfaces"][0]
    assert interface["wsdl_source"] == "fileset"
    assert interface["operations"][0]["saved_requests"] == [{"name": "Request 1"}]


def test_wsdl_interfaces_match_the_wsdl_adapter_exactly() -> None:
    members = _example_set()
    soapui = _import_set(members)
    wsdl = WsdlNormalizer().normalize(parse_wsdl(members["catalogue.wsdl"]), include_raw=False)
    assert [service.model_dump() for service in soapui.services] == [service.model_dump() for service in wsdl.services]
    assert [type_.model_dump() for type_ in soapui.types] == [type_.model_dump() for type_ in wsdl.types]
    assert {server.url for server in wsdl.servers} <= {server.url for server in soapui.servers}


@pytest.mark.parametrize("golden", sorted(path.name for path in _WSDL_GOLDENS.glob("*.json")))
def test_a_cached_wsdl_reproduces_the_wsdl_corpus_golden(golden: str) -> None:
    """A WSDL kept in the project's definitionCache normalizes to the WSDL adapter's own golden."""
    expected = json.loads((_WSDL_GOLDENS / golden).read_text(encoding="utf-8"))["canonical"]
    source = golden.removesuffix(".json")
    wsdl_text = (_WSDL_EXAMPLES / source).read_text(encoding="utf-8")
    url = f"https://legacy.example.com/{source}"
    api = _import(_project(_wsdl_interface(name="Binding", definition=url, cache=_cached_part(url, wsdl_text))))
    actual = api.model_dump(mode="json", exclude={"raw"})
    assert actual["services"] == expected["services"]
    assert actual["types"] == expected["types"]
    assert api.extras[SOAPUI_EXTRAS_KEY]["interfaces"][0]["wsdl_source"] == "cache"


def test_two_interfaces_over_one_wsdl_delegate_once() -> None:
    wsdl_text = (_EXAMPLES / _SET / "catalogue.wsdl").read_text(encoding="utf-8")
    body = _wsdl_interface(name="Soap11", definition="catalogue.wsdl") + _wsdl_interface(
        name="Soap12", definition="catalogue.wsdl"
    )
    api = _import_set({"project.xml": _project(body), "catalogue.wsdl": wsdl_text})
    assert [service.name for service in api.services] == ["CatalogueServicePortType"]
    assert [i["name"] for i in api.extras[SOAPUI_EXTRAS_KEY]["interfaces"]] == ["Soap11", "Soap12"]


def test_a_definition_path_resolves_by_file_name() -> None:
    wsdl_text = (_EXAMPLES / _SET / "catalogue.wsdl").read_text(encoding="utf-8")
    body = _wsdl_interface(name="Catalogue", definition="file:/C:/projects/soap/catalogue.wsdl")
    api = _import_set({"project.xml": _project(body), "wsdl/catalogue.wsdl": wsdl_text})
    assert len(api.types) == 2


def test_a_remote_wsdl_is_not_fetched_and_operations_are_declared() -> None:
    api = _import(_example("05-real-world-soap-project.xml"))
    assert api.protocol == "soap"
    operations = _operations(api)
    prefix = "http://example.com/billing.BillingServiceSoapBinding."
    assert sorted(operations) == [prefix + "GetInvoice", prefix + "ListInvoices", prefix + "NotifyPayment"]
    assert operations[prefix + "NotifyPayment"].kind is OperationKind.ONE_WAY
    assert operations[prefix + "GetInvoice"].extras["soap_action"] == "http://example.com/billing/GetInvoice"
    assert all(provenance_of(op.extras) == DECLARED and not op.messages for op in operations.values())
    interface = api.extras[SOAPUI_EXTRAS_KEY]["interfaces"][0]
    assert interface["wsdl_source"] == "not-fetched"
    limits = {limit["construct"] for limit in api.extras[SOAPUI_EXTRAS_KEY]["capability_limits"]}
    assert "soapui.wsdl_not_fetched" in limits
    assert sorted(api.extras[SOAPUI_EXTRAS_KEY]["environments"]) == ["Acceptance", "Production"]


def test_a_missing_local_wsdl_is_an_unresolved_reference() -> None:
    with pytest.raises(ImportSourceError) as caught:
        _adapter().parse(_example("negative/06-unresolvable-wsdl-definition.xml"))
    assert caught.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "does-not-exist.wsdl" in str(caught.value)


def test_the_wsdl_set_root_alone_names_its_missing_wsdl() -> None:
    with pytest.raises(SoapUiParseError) as caught:
        parse_soapui_text(_example(f"{_SET}/project.xml"))
    assert caught.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "upload the WSDL beside the project" in str(caught.value)


def test_an_unreadable_cached_wsdl_carries_the_wsdl_readers_code() -> None:
    body = _wsdl_interface(name="Bad", definition="a.wsdl", cache=_cached_part("a.wsdl", "<wsdl:definitions"))
    with pytest.raises(SoapUiParseError) as caught:
        parse_soapui_text(_project(body))
    assert caught.value.code == "INPUT_MALFORMED"
    assert "interface 'Bad'" in str(caught.value)


def test_a_mixed_project_keeps_both_halves() -> None:
    wsdl_text = (_EXAMPLES / _SET / "catalogue.wsdl").read_text(encoding="utf-8")
    resources = '<con:resource name="ping" path="/ping"><con:method name="ping" method="GET"/></con:resource>'
    body = _rest_interface(resources) + _wsdl_interface(
        name="Catalogue", definition="c.wsdl", cache=_cached_part("c.wsdl", wsdl_text)
    )
    operations = _operations(_import(_project(body)))
    assert "GET /v1/ping" in operations
    assert "http://example.com/catalogue.CatalogueServicePortType.GetProduct" in operations


def test_a_fileset_without_a_project_is_a_format_mismatch() -> None:
    with pytest.raises(SoapUiParseError) as caught:
        parse_soapui_fileset({"a.wsdl": "<x/>", "b.xsd": "<y/>"}, root="missing")
    assert caught.value.code == "FORMAT_MISMATCH"


# ---------------------------------------------------------------------------
# Declared test intent
# ---------------------------------------------------------------------------


def test_test_suites_are_recorded_as_declared_test_intent() -> None:
    api = _import(_example("04-stress-test-suites.xml"))
    record = api.extras[DECLARED_TESTS_EXTRAS_KEY]
    assert record["source_format"] == "soapui"
    assert record["counts"] == {"suites": 1, "cases": 2, "steps": 7, "assertions": 4}
    [suite] = declared_tests_of(api.extras)
    assert suite["name"] == "Order lifecycle"
    assert suite["run_type"] == "SEQUENTIAL"
    case = suite["cases"][0]
    assert case["properties"] == ["customerId", "orderId"]
    step = case["steps"][0]
    assert step["operation"] == "POST /v2/orders"
    assert [a["type"] for a in step["assertions"]] == ["Valid HTTP Status Codes", "JsonPath Match", "Response SLA"]
    assert step["assertions"][1]["expects"] == {"expected": "new", "path": "$.status"}
    assert [s["type"] for s in case["steps"]] == ["restrequest", "transfer", "delay", "groovy"]


def test_a_step_whose_target_is_not_in_the_model_links_to_nothing() -> None:
    [suite] = declared_tests_of(_import(_example("04-stress-test-suites.xml")).extras)
    lookup = suite["cases"][1]["steps"][1]
    assert lookup["target"] == "Orders listOrders"
    assert lookup["operation"] is None


def test_soap_and_cross_interface_steps_link_to_their_operations() -> None:
    [suite] = declared_tests_of(_import(_example("05-real-world-soap-project.xml")).extras)
    assert (
        suite["cases"][0]["steps"][0]["operation"] == "http://example.com/billing.BillingServiceSoapBinding.GetInvoice"
    )
    [suite] = declared_tests_of(_import(_example("07-composition-shared-endpoints.xml")).extras)
    linked = [step.get("operation") for step in suite["cases"][0]["steps"]]
    assert linked == ["GET /v2/orders", None, "GET /v2/products"]


def test_groovy_scripts_are_never_read() -> None:
    api = _import(_example("04-stress-test-suites.xml"))
    assert "context.expand" not in api.model_dump_json()
    limits = {limit["construct"]: limit for limit in api.extras[SOAPUI_EXTRAS_KEY]["capability_limits"]}
    assert limits["soapui.groovy_script"]["locations"] == [
        "Order lifecycle / Place and cancel / Assert identifier shape"
    ]


def test_declared_tests_are_visible_on_the_catalog_item() -> None:
    groups = derive_parsed_model(_import(_example("04-stress-test-suites.xml")))
    [tests] = [group for group in groups if group["title"] == "Declared tests"]
    first = tests["entities"][0]
    assert first["tag"] == "TEST"
    assert first["meta"] == "Order lifecycle · 4 steps · 3 assertions"
    assert first["fields"][0]["description"].startswith("Calls POST /v2/orders; asserts Valid HTTP Status Codes")


def test_a_project_without_tests_adds_no_declared_tests() -> None:
    api = _import(_example("01-minimal-project.xml"))
    assert DECLARED_TESTS_EXTRAS_KEY not in api.extras
    assert all(group["title"] != "Declared tests" for group in derive_parsed_model(api))


def test_build_declared_tests_counts_and_empty_input() -> None:
    assert build_declared_tests("x", []) is None
    record = build_declared_tests("x", [{"name": "S", "cases": [{"name": "C", "steps": [{"assertions": [{}, {}]}]}]}])
    assert record is not None and record["counts"] == {"suites": 1, "cases": 1, "steps": 1, "assertions": 2}
    assert declared_tests_of({DECLARED_TESTS_EXTRAS_KEY: "junk"}) == []


def test_declared_limits_reach_the_coverage_ledger() -> None:
    api = _import(_example("04-stress-test-suites.xml"))
    manifest = build_import_preview_manifest(api, adapter_key="soapui")
    rendered = repr(manifest.document_coverage)
    assert "soapui.test_case" in rendered
    assert "soapui.groovy_script" in rendered


def test_import_is_deterministic() -> None:
    text = _example("07-composition-shared-endpoints.xml")
    assert _import(text).model_dump_json() == _import(text).model_dump_json()


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def _credential_project() -> str:
    """A project whose saved requests carry every kind of credential SoapUI can keep."""
    envelope = (
        '&lt;soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"&gt;&lt;soapenv:Header&gt;'
        f"&lt;wsse:Security&gt;&lt;wsse:UsernameToken&gt;&lt;wsse:Username&gt;svc&lt;/wsse:Username&gt;"
        f'&lt;wsse:Password Type="#PasswordText"&gt;{_WSS_PASSWORD}&lt;/wsse:Password&gt;'
        "&lt;/wsse:UsernameToken&gt;&lt;/wsse:Security&gt;&lt;/soapenv:Header&gt;&lt;soapenv:Body/&gt;&lt;/soapenv:Envelope&gt;"
    )
    headers = (
        '&lt;xml-fragment xmlns:con="http://eviware.com/soapui/config"&gt;'
        f'&lt;con:entry key="Authorization" value="Bearer {_HEADER_TOKEN}"/&gt;'
        '&lt;con:entry key="X-Trace" value="trace-1"/&gt;&lt;/xml-fragment&gt;'
    )
    resources = f"""
      <con:resource name="orders" path="/orders">
        <con:parameters>
          <con:parameter><con:name>api_key</con:name><con:value>{_API_KEY}</con:value><con:style>QUERY</con:style></con:parameter>
        </con:parameters>
        <con:method name="listOrders" method="GET">
          <con:request name="Signed in" mediaType="application/json">
            <con:settings>
              <con:setting id="com.eviware.soapui.impl.wsdl.WsdlRequest@request-headers">{headers}</con:setting>
            </con:settings>
            <con:endpoint>https://ops:{_USERINFO}@api.example.com</con:endpoint>
            <con:request/>
            <con:credentials>
              <con:username>ops-user</con:username>
              <con:password>{_PASSWORD}</con:password>
              <con:authType>Basic</con:authType>
            </con:credentials>
            <con:parameters><con:entry key="api_key" value="{_API_KEY}"/></con:parameters>
          </con:request>
        </con:method>
      </con:resource>"""
    wsdl_text = (_EXAMPLES / _SET / "catalogue.wsdl").read_text(encoding="utf-8")
    operations = f"""
      <con:operation name="GetProduct" action="http://example.com/catalogue/GetProduct" type="Request-Response">
        <con:call name="Secured">
          <con:endpoint>https://api.example.com/catalogue</con:endpoint>
          <con:request>{envelope}</con:request>
          <con:credentials>
            <con:username>svc</con:username>
            <con:password>{_PASSWORD}</con:password>
            <con:authType>NTLM</con:authType>
            <con:wssType>PasswordText</con:wssType>
          </con:credentials>
        </con:call>
      </con:operation>"""
    body = _rest_interface(resources) + _wsdl_interface(
        name="Catalogue", definition="c.wsdl", cache=_cached_part("c.wsdl", wsdl_text), operations=operations
    )
    return _project(body, properties=_property("clientSecret", _PROPERTY_SECRET))


def test_saved_credentials_never_reach_the_canonical_model() -> None:
    api = _import(_credential_project())
    persisted = api.model_dump_json()
    for secret in _PLANTED:
        assert secret not in persisted, f"{secret[:6]}… reached the canonical model"
    operation = _operations(api)["GET /v1/orders"]
    assert operation.extras["security"] == ["basic"]
    assert operation.extras[AUTH_EXTRAS_KEY] == [{"type": "Basic", "scheme": "basic"}]
    [interface] = [i for i in api.extras[SOAPUI_EXTRAS_KEY]["interfaces"] if i["kind"] == "wsdl"]
    assert interface["operations"][0]["saved_requests"] == [
        {"name": "Secured", "auth": {"type": "NTLM", "scheme": "authorization", "ws_security": "PasswordText"}}
    ]
    assert "https://api.example.com" in {server.url for server in api.servers}


def test_saved_credentials_never_reach_the_coverage_manifest() -> None:
    manifest = build_import_preview_manifest(_import(_credential_project()), adapter_key="soapui")
    rendered = repr(manifest.document_coverage) + repr(manifest.entity_rows) + repr(manifest.document_nodes)
    for secret in _PLANTED:
        assert secret not in rendered, f"{secret[:6]}… reached the coverage manifest"


def test_saved_credentials_never_reach_the_persisted_source() -> None:
    text = _credential_project()
    intake = _ResolvedIntake(raw_bytes=text.encode("utf-8"), text=text, fileset=None, archive_root=None)
    fields, report = scrub_intake_source(intake)
    stored = fields["sourceContent"]
    assert report["scrubbed"] is True
    for secret in _PLANTED:
        assert secret not in stored, f"{secret[:6]}… persisted in the source"
        assert secret not in str(report)
    # The scrubbed source still parses and imports to the same operations.
    assert sorted(_operations(_import(stored))) == sorted(_operations(_import(text)))


@pytest.mark.parametrize(
    "fragment",
    [
        f"<con:password>{_PASSWORD}</con:password>",
        f'&lt;wsse:Password Type="x"&gt;{_WSS_PASSWORD}&lt;/wsse:Password&gt;',
        f'<con:entry key="X-Api-Key" value="{_API_KEY}"/>',
        f"<con:clientSecret>{_PROPERTY_SECRET}</con:clientSecret>",
        f"<con:property><con:name>clientSecret</con:name><con:value>{_PROPERTY_SECRET}</con:value></con:property>",
    ],
)
def test_the_scrub_gate_redacts_soapui_credential_shapes(fragment: str) -> None:
    scrubbed = scrub_document_text(fragment).text
    assert all(secret not in scrubbed for secret in _PLANTED)


@pytest.mark.parametrize(
    "fragment",
    [
        "<con:password/>",
        "<token>new</token>",
        '<xs:element name="password" type="xs:string"/>',
        '<con:entry key="status" value="shipped"/>',
        "<con:property><con:name>baseUrl</con:name><con:value>https://api.example.com</con:value></con:property>",
    ],
)
def test_the_scrub_gate_leaves_non_credentials_alone(fragment: str) -> None:
    assert scrub_document_text(fragment).text == fragment


# ---------------------------------------------------------------------------
# Taxonomy codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("negative/01-syntactic-unclosed-interface.xml", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-interfaces.xml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-operation.xml", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-wsdl.wsdl", "FORMAT_MISMATCH"),
        ("negative/06-unresolvable-wsdl-definition.xml", "INPUT_REFERENCE_UNRESOLVED"),
    ],
)
def test_negative_corpus_codes(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as caught:
        _adapter().parse(_example(name), source_label=name)
    assert caught.value.code == code


def test_utf16_upload_is_an_encoding_fault() -> None:
    text = (_EXAMPLES / "negative/05-encoding-utf16.xml").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(SoapUiParseError) as caught:
        parse_soapui_text(text)
    assert caught.value.code == "INPUT_ENCODING_INVALID"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("not xml at all", "FORMAT_MISMATCH"),
        ('<application xmlns="http://wadl.dev.java.net/2009/02"/>', "FORMAT_MISMATCH"),
        (_project(""), "INPUT_SEMANTIC_INVALID"),
        (_project(_rest_interface("")), "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_other_refusals(text: str, code: str) -> None:
    with pytest.raises(SoapUiParseError) as caught:
        parse_soapui_text(text)
    assert caught.value.code == code


def test_an_unsupported_interface_kind_is_a_declared_limit() -> None:
    resources = '<con:resource name="ping" path="/ping"><con:method name="ping" method="GET"/></con:resource>'
    body = _rest_interface(resources) + (
        '<con:interface xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:type="con:GraphQLService" name="Graph"/>'
    )
    limits = _import(_project(body)).extras[SOAPUI_EXTRAS_KEY]["capability_limits"]
    assert [(limit["construct"], limit["locations"]) for limit in limits] == [
        ("soapui.unsupported_interface", ["Graph (GraphQLService)"])
    ]


def test_normalize_rejects_a_foreign_ast() -> None:
    with pytest.raises(ImportSourceError):
        _adapter().normalize({"not": "a document"})


def _soapui_version(api: CanonicalApi) -> Optional[str]:
    return api.extras[SOAPUI_EXTRAS_KEY].get("soapui_version")


def test_the_saving_soapui_version_is_recorded() -> None:
    resources = '<con:resource name="ping" path="/ping"><con:method name="ping" method="GET"/></con:resource>'
    assert _soapui_version(_import(_project(_rest_interface(resources)))) == "5.7.0"
    assert _soapui_version(_import(_example("01-minimal-project.xml"))) is None


def test_interfaces_are_listed_in_the_projection_record() -> None:
    interfaces: List[Dict[str, Any]] = _import(_example("07-composition-shared-endpoints.xml")).extras[
        SOAPUI_EXTRAS_KEY
    ]["interfaces"]
    assert interfaces == [{"name": "Orders", "kind": "rest"}, {"name": "Catalogue", "kind": "rest"}]
