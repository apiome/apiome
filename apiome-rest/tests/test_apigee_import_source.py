"""The Apigee proxy bundle import source (FMT-7.3, #5457).

Drives the adapter over the committed corpus (``apiome-ui/examples/apigee``) and small inline
documents. Covers the acceptance criteria: a proxy bundle zip imports, flows become operations and
targets become servers; security and quota policies map to canonical constructs; unreducible flow
conditions are preserved and visible; and the corpus covers a single-target proxy, a multi-target
proxy and a bundle with a missing target endpoint.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

from app.apigee_bundle import classify_xml_root, interpret_policy, path_template, read_bundle, reduce_condition
from app.apigee_import_source import ApigeeImportSource
from app.fileset import IntakeFileset
from app.format_detection import detect_format
from app.import_preview_manifest import (
    CoverageClass,
    build_import_preview_manifest,
    paginate_import_preview_manifest,
)
from app.import_routing import decide_import_routing
from app.import_source import DetectionInput, ImportSourceError
from app.import_source_pipeline import _resolve_intake

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "apigee"


@pytest.fixture
def adapter() -> ApigeeImportSource:
    return ApigeeImportSource()


def _bundle(adapter: ApigeeImportSource, name: str):
    return adapter.normalize(adapter.parse_bytes((EXAMPLES / name).read_bytes(), source_label=name))


def _ops(model) -> Dict[str, Any]:
    return {op.key: op for op in model.operations()}


def _ledger(model) -> Dict[str, Any]:
    page = paginate_import_preview_manifest(build_import_preview_manifest(model, adapter_key="apigee", options={}))
    return {row.source_construct: row for row in page.coverage}


def _zip(members: Dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


MANIFEST = '<APIProxy revision="3" name="pets"><DisplayName>Pets</DisplayName><BasePaths>/pets</BasePaths></APIProxy>'


def _proxy(
    flows: str = "", rules: str = '<RouteRule name="default"><TargetEndpoint>default</TargetEndpoint></RouteRule>'
) -> str:
    return (
        '<ProxyEndpoint name="default"><PreFlow><Request/><Response/></PreFlow>'
        f"<Flows>{flows}</Flows><HTTPProxyConnection><BasePath>/pets</BasePath></HTTPProxyConnection>{rules}"
        "</ProxyEndpoint>"
    )


TARGET = '<TargetEndpoint name="default"><HTTPTargetConnection><URL>https://pets.internal</URL></HTTPTargetConnection></TargetEndpoint>'


# --- acceptance: a bundle imports, flows become operations, targets servers ---------------


def test_a_single_target_bundle_imports(adapter):
    model = _bundle(adapter, "02-typical-proxy-bundle.zip")
    assert model.format == "apigee" and model.title == "Orders v2" and model.version == "7"
    assert set(_ops(model)) == {"GET /v2/orders/orders", "POST /v2/orders/orders", "GET /v2/orders/orders/{segment1}"}
    get_one = _ops(model)["GET /v2/orders/orders/{segment1}"]
    assert [p.name for p in get_one.parameters] == ["segment1"] and get_one.name == "GetOrder"
    assert [(s.url, s.name) for s in model.servers] == [("https://orders.internal.example.com/v2", "default")]


def test_a_multi_target_bundle_has_one_server_per_target_and_ordered_rules(adapter):
    model = _bundle(adapter, "03-composition-multi-target-bundle.zip")
    assert {s.name for s in model.servers} == {"admin", "catalogue", "search"}
    rules = model.extras["apigee"]["routeRules"]
    assert [r["name"] for r in rules] == ["to-search", "to-admin", "no-route", "default"]
    assert rules[2]["target"] is None
    admin = _ops(model)["ANY /v1/store/admin/{path}"]
    assert admin.parameters[0].name == "path" and "segments" in (admin.parameters[0].description or "")


def test_a_load_balanced_target_is_a_server_template(adapter):
    model = _bundle(adapter, "04-stress-policy-coverage-bundle.zip")
    (server,) = model.servers
    assert server.url == "https://{server}/internal/v3"
    assert server.variables[0].enum == ["lab-primary", "lab-secondary"]


# --- acceptance: security and quota policies map to canonical constructs -----------------


def test_security_rate_limits_and_cors_map_to_canonical_records(adapter):
    op = _ops(_bundle(adapter, "02-typical-proxy-bundle.zip"))["POST /v2/orders/orders"]
    (security,) = op.extras["security"]
    assert security["scheme"] == "apiKey" and security["in"] == "header" and security["parameterName"] == "x-api-key"
    kinds = {r["kind"]: r for r in op.extras["rate_limits"]}
    assert kinds["spike-arrest"]["rate"] == "30ps"
    assert kinds["quota"]["calls"] == 10000 and kinds["quota"]["timeUnit"] == "day"
    assert op.extras["cors"]["allowOrigins"] == ["https://app.example.com"]
    # The quota step belongs to CreateOrder only; the list flow has the spike arrest alone.
    listed = _ops(_bundle(adapter, "02-typical-proxy-bundle.zip"))["GET /v2/orders/orders"]
    assert [r["kind"] for r in listed.extras["rate_limits"]] == ["spike-arrest"]


def test_oauth_scopes_and_conditional_steps(adapter):
    model = _bundle(adapter, "04-stress-policy-coverage-bundle.zip")
    op = _ops(model)["POST /v3/lab/legacy/{path}"]
    oauth = next(r for r in op.extras["security"] if r["scheme"] == "oauth2")
    assert oauth["policy"] == "Verify-OAuth-Token"
    spike = next(r for r in op.extras["rate_limits"] if r["kind"] == "spike-arrest")
    assert spike["condition"] == 'request.verb != "OPTIONS"'


# --- acceptance: unreducible conditions are preserved and visible ------------------------


def test_unreducible_conditions_are_declared_and_on_the_ledger(adapter):
    model = _bundle(adapter, "03-composition-multi-target-bundle.zip")
    declared = {c["kind"]: c for c in model.extras["apigee"]["declaredConditions"]}
    assert declared["route-condition"]["unreduced"] == ["request.header.x-admin-token != null"]
    assert declared["route-without-target"]["routeRule"] == "no-route"
    rows = _ledger(model)
    row = rows["apigee#declared-condition.route-without-target.no-route"]
    assert row.coverage is CoverageClass.PARTIALLY_MAPPED and "never dropped" in row.detail
    assert rows["apigee#policy.VerifyAPIKey"].coverage is CoverageClass.MAPPED
    assert rows["apigee#policy.RaiseFault.Check-Admin-Role"].coverage is CoverageClass.PARTIALLY_MAPPED


def test_an_unconditional_flow_is_a_declared_condition(adapter):
    model = _bundle(adapter, "04-stress-policy-coverage-bundle.zip")
    (unconditional,) = [c for c in model.extras["apigee"]["declaredConditions"] if c["kind"] == "unconditional-flow"]
    assert unconditional["flow"] == "Unconditional"
    assert "Javascript-Merge" in {u["name"] for u in model.extras["apigee"]["unmapped"]}


def test_a_partially_reducible_flow_keeps_the_rest_on_the_operation(adapter):
    flows = (
        '<Flow name="Beta"><Condition>(proxy.pathsuffix MatchesPath "/beta") and (request.verb = "GET") '
        'and (request.header.x-beta = "1")</Condition><Request/><Response/></Flow>'
    )
    model = adapter.normalize(
        adapter.parse_bytes(
            _zip(
                {
                    "apiproxy/pets.xml": MANIFEST,
                    "apiproxy/proxies/default.xml": _proxy(flows),
                    "apiproxy/targets/default.xml": TARGET,
                }
            )
        )
    )
    op = _ops(model)["GET /pets/beta"]
    assert op.extras["declared_conditions"][0]["unreduced"] == ['request.header.x-beta = "1"']


def test_an_or_condition_is_not_reduced(adapter):
    flows = (
        '<Flow name="Either"><Condition>(proxy.pathsuffix MatchesPath "/a") or (proxy.pathsuffix MatchesPath "/b")'
        "</Condition><Request/><Response/></Flow>"
    )
    model = adapter.normalize(
        adapter.parse_bytes(
            _zip(
                {
                    "apiproxy/pets.xml": MANIFEST,
                    "apiproxy/proxies/default.xml": _proxy(flows),
                    "apiproxy/targets/default.xml": TARGET,
                }
            )
        )
    )
    assert model.operations() == []
    assert model.extras["apigee"]["declaredConditions"][0]["kind"] == "flow-condition"


# --- loose files and filesets ------------------------------------------------------------


def test_loose_files_import_without_target_checks(adapter):
    proxy = adapter.normalize(adapter.parse((EXAMPLES / "01-minimal-proxy-endpoint.xml").read_text()))
    assert set(_ops(proxy)) == {"GET /v1/ping/ping"} and proxy.servers == []
    target = adapter.normalize(adapter.parse((EXAMPLES / "06-typical-target-endpoint.xml").read_text()))
    assert target.operations() == [] and target.servers[0].name == "production"
    assert target.extras["apigee"]["unresolvedSteps"] == {"Add-Backend-Auth": ["target:production"]}


def test_a_shared_flow_fileset_expands_the_callout(adapter):
    members = {p.name: p.read_text() for p in (EXAMPLES / "07-shared-flow-set").iterdir()}
    model = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root="proxy-endpoint.xml")))
    report = model.extras["apigee"]
    assert report["flowCallouts"] == [
        {"policy": "Call-Security-SharedFlow", "sharedFlowBundle": "security-v1", "resolved": True}
    ]
    # The shared flow's own steps are named; their policies live in the shared-flow bundle, not here.
    assert {"Verify-OAuth-Token", "Quota-Per-App", "Call-Logging-SharedFlow"} <= set(report["unresolvedSteps"])


def test_an_uploaded_bundle_resolves_its_root_through_archive_intake(adapter):
    raw = (EXAMPLES / "02-typical-proxy-bundle.zip").read_bytes()
    import base64

    intake = _resolve_intake({"document_base64": base64.standard_b64encode(raw).decode(), "filename": "b.zip"}, {})
    assert intake.archive_root == "apiproxy/orders-v2.xml"
    model = adapter.normalize(adapter.parse_fileset(intake.fileset))
    assert len(model.operations()) == 3 and model.extras["apigee"]["shape"] == "bundle"


# --- rejections --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    [
        ("02-semantic-no-proxy-endpoint.zip", "INPUT_SEMANTIC_INVALID"),
        ("03-truncated-bundle.zip", "INPUT_ARCHIVE_INVALID"),
        ("06-unresolvable-target-endpoint.zip", "INPUT_REFERENCE_UNRESOLVED"),
    ],
)
def test_negative_bundles(adapter, name, code):
    with pytest.raises(ImportSourceError) as info:
        adapter.parse_bytes((EXAMPLES / "negative" / name).read_bytes(), source_label=name)
    assert info.value.code == code


@pytest.mark.parametrize(
    "name,code",
    [
        ("01-syntactic-unclosed-flow.xml", "INPUT_MALFORMED"),
        ("04-wrong-format-gateway-api.yaml", "FORMAT_MISMATCH"),
        ("05-encoding-utf16.xml", "INPUT_ENCODING_INVALID"),
    ],
)
def test_negative_files(adapter, name, code):
    text = (EXAMPLES / "negative" / name).read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(ImportSourceError) as info:
        adapter.parse(text, source_label=name)
    assert info.value.code == code


def test_a_policy_xml_alone_is_not_apigee(adapter):
    with pytest.raises(ImportSourceError) as info:
        adapter.parse('<VerifyAPIKey name="k"><APIKey ref="request.header.k"/></VerifyAPIKey>')
    assert info.value.code == "FORMAT_MISMATCH"


# --- detection and routing ---------------------------------------------------------------


def test_detection(adapter):
    assert (
        adapter.detect(DetectionInput(data=(EXAMPLES / "02-typical-proxy-bundle.zip").read_bytes())).confidence == 0.97
    )
    assert adapter.detect(DetectionInput(data=_zip({"other/a.json": "{}"}))).matched is False
    text = (EXAMPLES / "01-minimal-proxy-endpoint.xml").read_text()
    detection = detect_format(DetectionInput(text=text))
    assert detection.detected.source_key == "apigee" and not detection.ambiguous
    assert adapter.detect(DetectionInput(text="<definitions/>")).matched is False


def test_routes_to_the_catalog_and_lints(adapter):
    model = _bundle(adapter, "05-real-world-payments-bundle.zip")
    assert decide_import_routing(adapter, model).publishable is False
    assert adapter.lint(model) is not None


# --- pure helpers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression,path,verb,unreduced",
    [
        ('(proxy.pathsuffix MatchesPath "/a/*") and (request.verb = "get")', "/a/*", "GET", []),
        ('proxy.pathsuffix MatchesPath "/a"', "/a", None, []),
        ('request.verb == "DELETE"', None, "DELETE", []),
        ('proxy.pathsuffix ~/ "/a.*"', None, None, ['proxy.pathsuffix ~/ "/a.*"']),
        ('not (request.verb = "GET")', None, None, ['not (request.verb = "GET")']),
        (None, None, None, []),
    ],
)
def test_reduce_condition(expression, path, verb, unreduced):
    reduced = reduce_condition(expression)
    assert (reduced.path, reduced.verb, reduced.unreduced) == (path, verb, unreduced)


def test_path_template():
    assert path_template("/v1/x", "/a/*/b/*") == (
        "/v1/x/a/{segment1}/b/{segment2}",
        [("segment1", False), ("segment2", False)],
    )
    assert path_template("/v1", "/files/**") == ("/v1/files/{path}", [("path", True)])
    assert path_template("/", None) == ("/", [])


def test_classify_and_interpret():
    assert classify_xml_root('<?xml version="1.0"?>\n<!-- c -->\n<APIProxy name="x"/>') == "manifest"
    assert classify_xml_root("<Other/>") is None
    bundle = read_bundle({"apiproxy/policies/q.xml": '<Quota name="Q"><Allow count="5"/></Quota>', "r/x.js": "1"})
    assert bundle.resources == ["r/x.js"]
    target, record = interpret_policy("Q", bundle.policies["Q"])
    assert target == "rate_limits" and record["calls"] == 5
    target, record = interpret_policy(
        "X",
        read_bundle({"p.xml": '<OAuthV2 name="X"><Operation>GenerateAccessToken</Operation></OAuthV2>'}).policies["X"],
    )
    assert (target, record) == ("unmapped", None)
