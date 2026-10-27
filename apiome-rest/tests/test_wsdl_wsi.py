"""Tests for the WS-I lint pack — MFI-13.4 (#3791).

Covers :mod:`app.wsdl_wsi` (WS-I Basic Profile binding and import checks), the import-source
wiring that runs it with the fileset members, the normalizer extras and the ``wsi.*`` rules of
:mod:`app.wsdl_lint`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pytest

from app.fileset import IntakeFileset
from app.lint_engine import lint_canonical_model
from app.wsdl_import_source import WsdlImportSource
from app.wsdl_wsi import MAX_REPORTED_ISSUES, check_wsi

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_CLEAN = [
    p
    for p in sorted((_EXAMPLES / "wsdl").glob("*.wsdl")) + sorted((_EXAMPLES / "wsdl2").glob("*.wsdl"))
    if p.name != "04-kitchen-sink.wsdl"
]

_SOAP11 = "http://schemas.xmlsoap.org/wsdl/soap/"
_SOAP12 = "http://schemas.xmlsoap.org/wsdl/soap12/"


def _wsdl(
    binding_ops: str,
    *,
    messages: Optional[str] = None,
    port_ops: Optional[str] = None,
    types_extra: str = "",
    imports: str = "",
    style: str = "document",
    soap_ns: str = _SOAP11,
) -> str:
    """A WSDL 1.1 description with one portType / binding / service; parts default to element."""
    messages = messages or (
        '<wsdl:message name="In"><wsdl:part name="parameters" element="tns:GetOrder"/></wsdl:message>'
        '<wsdl:message name="Out"><wsdl:part name="parameters" element="tns:GetOrderResponse"/></wsdl:message>'
    )
    port_ops = port_ops or (
        '<wsdl:operation name="GetOrder"><wsdl:input message="tns:In"/>'
        '<wsdl:output message="tns:Out"/></wsdl:operation>'
    )
    return f"""<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" xmlns:soap="{soap_ns}"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:tns="urn:orders" targetNamespace="urn:orders">
  {imports}
  <wsdl:types><xsd:schema targetNamespace="urn:orders">{types_extra}
    <xsd:element name="GetOrder" type="xsd:string"/><xsd:element name="GetOrderResponse" type="xsd:string"/>
  </xsd:schema></wsdl:types>
  {messages}
  <wsdl:portType name="Port">{port_ops}</wsdl:portType>
  <wsdl:binding name="Soap" type="tns:Port">
    <soap:binding style="{style}" transport="http://schemas.xmlsoap.org/soap/http"/>
    {binding_ops}
  </wsdl:binding>
  <wsdl:service name="Svc"><wsdl:port name="P" binding="tns:Soap"><soap:address location="https://x.example/soap"/></wsdl:port></wsdl:service>
</wsdl:definitions>"""


def _op(
    name: str = "GetOrder", *, action: str = "urn:GetOrder", style: str = "", use: str = "literal", body: str = ""
) -> str:
    """One binding operation with literal (or ``use``) input and output bodies."""
    style_attr = f' style="{style}"' if style else ""
    return (
        f'<wsdl:operation name="{name}"><soap:operation soapAction="{action}"{style_attr}/>'
        f'<wsdl:input><soap:body use="{use}"{body}/></wsdl:input>'
        f'<wsdl:output><soap:body use="literal"{body}/></wsdl:output></wsdl:operation>'
    )


def _issues(text: str, members: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    issues, _ = check_wsi(text, version="1.1", members=members)
    return [issue.as_dict() for issue in issues]


def _rules(text: str, members: Optional[Dict[str, str]] = None) -> List[str]:
    return [issue["rule"] for issue in _issues(text, members)]


@pytest.mark.parametrize("path", _CLEAN, ids=lambda p: p.name)
def test_the_corpus_descriptions_are_wsi_clean(path: Path):
    document = WsdlImportSource().parse(path.read_text(encoding="utf-8"), source_label=path.name)
    assert document.wsi_issues == ()


def test_the_kitchen_sink_fixture_reports_its_deliberate_defects():
    path = _EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl"
    document = WsdlImportSource().parse(path.read_text(encoding="utf-8"))
    rules = {issue["rule"] for issue in document.wsi_issues}
    assert rules == {"wsi.binding-style", "wsi.document-literal"}


def test_a_clean_description_has_no_issues():
    assert _issues(_wsdl(_op())) == []


# ===========================================================================
# document/literal
# ===========================================================================


@pytest.mark.parametrize("soap_ns", [_SOAP11, _SOAP12])
def test_encoded_use_is_reported(soap_ns: str):
    issues = _issues(_wsdl(_op(use="encoded"), soap_ns=soap_ns))
    assert [(i["rule"], i["path"]) for i in issues] == [("wsi.literal-use", "/binding/Soap/operation/GetOrder/input")]
    assert "R2706" in issues[0]["message"]


def test_encoded_headers_and_faults_are_reported():
    op = (
        '<wsdl:operation name="GetOrder"><soap:operation soapAction="urn:GetOrder"/>'
        '<wsdl:input><soap:body use="literal"/>'
        '<soap:header message="tns:In" part="parameters" use="encoded">'
        '<soap:headerfault message="tns:In" part="parameters" use="encoded"/></soap:header></wsdl:input>'
        '<wsdl:output><soap:body use="literal"/></wsdl:output>'
        '<wsdl:fault name="Oops"><soap:fault name="Oops" use="encoded"/></wsdl:fault></wsdl:operation>'
    )
    issues = _issues(_wsdl(op))
    assert [i["rule"] for i in issues] == ["wsi.literal-use"] * 3
    assert issues[-1]["path"] == "/binding/Soap/operation/GetOrder/fault/Oops"


def test_a_missing_use_is_literal():
    assert _rules(_wsdl(_op().replace(' use="literal"', ""))) == []


def test_mixed_styles_in_one_binding():
    ops = _op() + _op("FindOrder", action="urn:FindOrder", style="rpc", body=' namespace="urn:orders"')
    port_ops = (
        '<wsdl:operation name="GetOrder"><wsdl:input message="tns:In"/>'
        '<wsdl:output message="tns:Out"/></wsdl:operation>'
        '<wsdl:operation name="FindOrder"><wsdl:input message="tns:RIn"/></wsdl:operation>'
    )
    messages = (
        '<wsdl:message name="In"><wsdl:part name="parameters" element="tns:GetOrder"/></wsdl:message>'
        '<wsdl:message name="Out"><wsdl:part name="parameters" element="tns:GetOrderResponse"/></wsdl:message>'
        '<wsdl:message name="RIn"><wsdl:part name="id" type="xsd:string"/></wsdl:message>'
    )
    issues = _issues(_wsdl(ops, messages=messages, port_ops=port_ops))
    assert [(i["rule"], i["path"]) for i in issues] == [("wsi.binding-style", "/binding/Soap")]
    assert "document: GetOrder; rpc: FindOrder" in issues[0]["message"]


def test_document_literal_parts_and_namespace():
    messages = (
        '<wsdl:message name="In"><wsdl:part name="a" element="tns:GetOrder"/>'
        '<wsdl:part name="b" type="xsd:int"/></wsdl:message>'
        '<wsdl:message name="Out"><wsdl:part name="parameters" element="tns:GetOrderResponse"/></wsdl:message>'
    )
    issues = _issues(_wsdl(_op(), messages=messages))
    messages_out = [i["message"] for i in issues]
    assert {i["rule"] for i in issues} == {"wsi.document-literal"}
    assert any("references 2 parts" in m for m in messages_out)
    assert any("part `b` defined by `type`" in m for m in messages_out)
    # `parts=` narrowing the body to the element part makes it conformant.
    narrowed = _op().replace(
        '<wsdl:input><soap:body use="literal"/>', '<wsdl:input><soap:body use="literal" parts="a"/>'
    )
    assert _issues(_wsdl(narrowed, messages=messages)) == []
    namespaced = _issues(_wsdl(_op(body=' namespace="urn:orders"')))
    assert [i["rule"] for i in namespaced] == ["wsi.document-literal", "wsi.document-literal"]
    assert "R2716" in namespaced[0]["message"]


def test_rpc_literal_parts_and_namespace():
    messages = (
        '<wsdl:message name="In"><wsdl:part name="id" element="tns:GetOrder"/></wsdl:message>'
        '<wsdl:message name="Out"><wsdl:part name="status" type="xsd:string"/></wsdl:message>'
    )
    issues = _issues(_wsdl(_op(), messages=messages, style="rpc"))
    assert [i["rule"] for i in issues] == ["wsi.rpc-literal"] * 3
    joined = " ".join(i["message"] for i in issues)
    assert "part `id` defined by `element`" in joined and "R2717" in joined
    fixed = messages.replace('element="tns:GetOrder"', 'type="xsd:string"')
    assert _issues(_wsdl(_op(body=' namespace="urn:orders"'), messages=fixed, style="rpc")) == []


# ===========================================================================
# Unique soapActions and operation signatures
# ===========================================================================


_TWO_OPS = (
    '<wsdl:operation name="GetOrder"><wsdl:input message="tns:In"/><wsdl:output message="tns:Out"/></wsdl:operation>'
    '<wsdl:operation name="FindOrder"><wsdl:input message="tns:In"/><wsdl:output message="tns:Out"/></wsdl:operation>'
)


def test_shared_soap_action_and_identical_signature():
    issues = _issues(_wsdl(_op() + _op("FindOrder"), port_ops=_TWO_OPS))
    assert [i["rule"] for i in issues] == ["wsi.unique-soap-action", "wsi.unique-operation-signature"]
    assert "`GetOrder`, `FindOrder`" in issues[0]["message"]


def test_same_body_element_with_distinct_soap_actions_is_distinguishable():
    assert _issues(_wsdl(_op() + _op("FindOrder", action="urn:FindOrder"), port_ops=_TWO_OPS)) == []


def test_empty_soap_actions_are_not_duplicates_but_signatures_still_clash():
    issues = _issues(_wsdl(_op(action="") + _op("FindOrder", action=""), port_ops=_TWO_OPS))
    assert [i["rule"] for i in issues] == ["wsi.unique-operation-signature"]
    assert "no soapAction" in issues[0]["message"]


# ===========================================================================
# Resolvable imports
# ===========================================================================


def test_schema_imports_resolve_against_members():
    text = _wsdl(_op(), types_extra='<xsd:import namespace="urn:common" schemaLocation="schemas/common.xsd"/>')
    issues = _issues(text)
    assert [(i["rule"], i["path"]) for i in issues] == [
        ("wsi.unresolved-import", "/schema/urn:orders/import/schemas/common.xsd")
    ]
    common = '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:common"/>'
    assert _issues(text, {"common.xsd": common}) == []
    unreadable = _issues(text, {"common.xsd": "<xsd:schema"})
    assert "cannot be read" in unreadable[0]["message"]


def test_includes_are_followed_transitively():
    text = _wsdl(_op(), types_extra='<xsd:include schemaLocation="a.xsd"/>')
    a = (
        '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:orders">'
        '<xsd:include schemaLocation="b.xsd"/></xsd:schema>'
    )
    issues = _issues(text, {"a.xsd": a})
    assert [(i["rule"], i["path"]) for i in issues] == [("wsi.unresolved-import", "/schema/urn:orders/import/b.xsd")]


def test_location_less_schema_imports_need_a_declaring_schema():
    text = _wsdl(
        _op(),
        types_extra=(
            '<xsd:import namespace="urn:orders"/>'
            '<xsd:import namespace="http://schemas.xmlsoap.org/soap/encoding/"/>'
            '<xsd:import namespace="urn:missing"/>'
        ),
    )
    issues = _issues(text)
    assert [(i["rule"], i["path"]) for i in issues] == [
        ("wsi.unresolved-import", "/schema/urn:orders/import/urn:missing")
    ]


def test_wsdl_imports():
    no_location = _issues(_wsdl(_op(), imports='<wsdl:import namespace="urn:shared"/>'))
    assert [i["rule"] for i in no_location] == ["wsi.wsdl-import-target"]
    text = _wsdl(_op(), imports='<wsdl:import namespace="urn:shared" location="shared.wsdl"/>')
    assert _rules(text) == ["wsi.unresolved-import"]
    schema = '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:shared"/>'
    wrong = _issues(text, {"shared.wsdl": schema})
    assert [i["rule"] for i in wrong] == ["wsi.wsdl-import-target"]
    assert "names a `schema`" in wrong[0]["message"]
    shared = (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'targetNamespace="urn:shared"><wsdl:types><xsd:schema targetNamespace="urn:shared">'
        '<xsd:import namespace="urn:deep" schemaLocation="deep.xsd"/></xsd:schema></wsdl:types></wsdl:definitions>'
    )
    # The imported description's own schemas are checked too.
    assert _rules(text, {"shared.wsdl": shared}) == ["wsi.unresolved-import"]


def test_bindings_in_imported_descriptions_are_checked():
    binding_only = _wsdl(_op(use="encoded"))
    root = (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" targetNamespace="urn:root">'
        '<wsdl:import namespace="urn:orders" location="orders.wsdl"/></wsdl:definitions>'
    )
    assert _rules(root, {"orders.wsdl": binding_only}) == ["wsi.literal-use"]


def test_wsdl_2_checks_imports_only():
    folder = _EXAMPLES / "wsdl2" / "06-imported-set"
    service = (folder / "service.wsdl").read_text(encoding="utf-8")
    issues, _ = check_wsi(service, version="2.0")
    assert [i.rule for i in issues] == ["wsi.unresolved-import"]
    members = {p.name: p.read_text(encoding="utf-8") for p in folder.iterdir() if p.is_file()}
    assert check_wsi(service, version="2.0", members=members) == ([], 0)


def test_unparseable_text_yields_nothing():
    assert check_wsi("<not-xml", version="1.1") == ([], 0)


def test_issues_are_capped():
    ops = "".join(_op(f"Op{i}", action=f"urn:Op{i}", use="encoded") for i in range(MAX_REPORTED_ISSUES + 4))
    port_ops = "".join(
        f'<wsdl:operation name="Op{i}"><wsdl:input message="tns:In"/><wsdl:output message="tns:Out"/></wsdl:operation>'
        for i in range(MAX_REPORTED_ISSUES + 4)
    )
    issues, total = check_wsi(_wsdl(ops, port_ops=port_ops), version="1.1")
    assert len(issues) == MAX_REPORTED_ISSUES
    # Every operation sends `GetOrder` with a distinct soapAction: only the encoded inputs count.
    assert total == MAX_REPORTED_ISSUES + 4


# ===========================================================================
# Import wiring, extras and lint rules
# ===========================================================================


def _findings(text: str) -> Dict[str, List[Dict[str, str]]]:
    adapter = WsdlImportSource()
    model = adapter.normalize(adapter.parse(text, source_label="t.wsdl"))
    out: Dict[str, List[Dict[str, str]]] = {}
    for finding in lint_canonical_model(model).findings:
        payload = finding.as_dict()
        out.setdefault(payload["rule"], []).append(payload)
    return out


def test_a_clean_description_adds_no_extras_or_findings():
    adapter = WsdlImportSource()
    model = adapter.normalize(adapter.parse(_wsdl(_op())))
    assert "wsdl_wsi_issues" not in model.extras
    assert not [rule for rule in _findings(_wsdl(_op())) if rule.startswith("wsi.")]


def test_the_rules_report_with_their_severities_and_paths():
    findings = _findings(_wsdl(_op(use="encoded") + _op("FindOrder"), port_ops=_TWO_OPS))
    assert findings["wsi.literal-use"][0]["severity"] == "error"
    assert findings["wsi.literal-use"][0]["path"] == "wsdl:/binding/Soap/operation/GetOrder/input"
    assert findings["wsi.unique-soap-action"][0]["severity"] == "warning"
    assert findings["wsi.unique-operation-signature"][0]["severity"] == "error"


def test_a_fileset_import_resolves_its_members():
    text = _wsdl(_op(), types_extra='<xsd:import namespace="urn:common" schemaLocation="common.xsd"/>')
    common = '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:common"/>'
    adapter = WsdlImportSource()
    alone = adapter.parse(text)
    assert alone.wsi_issue_count == 1
    fileset = IntakeFileset(root="svc.wsdl", members={"svc.wsdl": text, "common.xsd": common})
    assert adapter.parse_fileset(fileset).wsi_issues == ()


def test_the_overflow_is_reported_once():
    ops = "".join(_op(f"Op{i}", action=f"urn:Op{i}", use="encoded") for i in range(MAX_REPORTED_ISSUES + 4))
    port_ops = "".join(
        f'<wsdl:operation name="Op{i}"><wsdl:input message="tns:In"/><wsdl:output message="tns:Out"/></wsdl:operation>'
        for i in range(MAX_REPORTED_ISSUES + 4)
    )
    messages = [f["message"] for f in _findings(_wsdl(ops, port_ops=port_ops))["wsi.literal-use"]]
    assert "4 more WS-I Basic Profile issue(s) not listed." in messages
