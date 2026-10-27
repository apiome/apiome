"""Tests for WSDL / XSD breaking changes — MFI-13.5 (#3792).

Covers what the WSDL importer now records (soapAction / style per operation; element occurs,
nillable, default and simple-type facets), that the WSDL emitter writes it back so a re-import
matches, and the ``wsdl`` breaking-change classifier's grades.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pytest

from app.breaking_change import classify, get_breaking_change_classifier
from app.diff import diff
from app.wsdl_breaking import WsdlBreakingChangeClassifier
from app.wsdl_emitter import WsdlEmitter
from app.wsdl_import_source import WsdlImportSource
from app.wsdl_parser import parse_wsdl

_WSDL = """<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:tns="urn:o" targetNamespace="urn:o">
  <wsdl:types><xs:schema targetNamespace="urn:o">
    <xs:simpleType name="Status"><xs:restriction base="xs:string">{enum}</xs:restriction></xs:simpleType>
    <xs:complexType name="Order"><xs:sequence>
      <xs:element name="id" type="xs:string"/>
      <xs:element name="status" type="tns:Status"/>
      <xs:element name="note" minOccurs="0"><xs:simpleType>
        <xs:restriction base="xs:string">{note_facets}</xs:restriction></xs:simpleType></xs:element>
      <xs:element name="lines" {lines}/>{extra}
    </xs:sequence></xs:complexType>
    <xs:element name="GetOrder" type="tns:Order"/>
  </xs:schema></wsdl:types>
  <wsdl:message name="In"><wsdl:part name="p" element="tns:GetOrder"/></wsdl:message>
  <wsdl:portType name="Orders"><wsdl:operation name="GetOrder">
    <wsdl:input message="tns:In"/>{output}</wsdl:operation></wsdl:portType>
  <wsdl:binding name="B" type="tns:Orders"><soap:binding style="{style}" transport="http://schemas.xmlsoap.org/soap/http"/>
    <wsdl:operation name="GetOrder"><soap:operation soapAction="{action}"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input></wsdl:operation>
  </wsdl:binding>
</wsdl:definitions>"""

_DEFAULTS = {
    "enum": '<xs:enumeration value="OPEN"/><xs:enumeration value="CLOSED"/>',
    "note_facets": '<xs:maxLength value="50"/>',
    "lines": 'type="xs:string" maxOccurs="unbounded"',
    "extra": "",
    "output": '<wsdl:output message="tns:In"/>',
    "style": "document",
    "action": "urn:GetOrder",
}


def _text(**parts: str) -> str:
    return _WSDL.format(**{**_DEFAULTS, **parts})


def _model(**parts: str):
    adapter = WsdlImportSource()
    return adapter.normalize(adapter.parse(_text(**parts)))


def _grades(base_parts: Dict[str, str], head_parts: Dict[str, str]) -> Dict[str, Tuple[str, str, str]]:
    base, head = _model(**base_parts), _model(**head_parts)
    result = classify(diff(base, head), base, head)
    assert result.classifier == "wsdl-xsd"
    return {c.key: (c.severity.value, c.rule_id, c.rationale) for c in result.classifications}


def _emitted_text(result: Any) -> str:
    """The WSDL text of an emit result (one file)."""
    files = getattr(result, "files", None)
    if files:
        first = files[0]
        return first.content if hasattr(first, "content") else str(first)
    return getattr(result, "content", result)


def _field(model, name: str) -> Any:
    order = next(t for t in model.types if t.name == "Order")
    return next(f for f in order.fields if f.name == name)


def test_the_classifier_is_registered_for_wsdl():
    assert get_breaking_change_classifier("wsdl") is WsdlBreakingChangeClassifier


# ===========================================================================
# What the importer records
# ===========================================================================


def test_fields_record_occurs_and_simple_type_facets():
    model = _model()
    assert _field(model, "status").extras == {
        "xsd_type": "Status",
        "xsd_simple_type": "Status",
        "xsd_base": "string",
        "xsd_facets": {"enumeration": ["OPEN", "CLOSED"]},
    }
    assert _field(model, "note").extras == {
        "xsd_type": "string",
        "xsd_min_occurs": "0",
        "xsd_base": "string",
        "xsd_facets": {"maxLength": "50"},
    }
    assert _field(model, "lines").extras == {"xsd_type": "string", "xsd_max_occurs": "unbounded"}
    assert _field(model, "id").extras == {"xsd_type": "string"}


def test_operations_record_their_soap_action_and_rpc_style():
    operation = _model().services[0].operations[0]
    assert operation.extras == {"wsdl_soap_action": "urn:GetOrder"}
    rpc = _model(style="rpc", action="").services[0].operations[0]
    assert rpc.extras == {"wsdl_soap_style": "rpc"}


def test_an_operation_style_overrides_the_binding_default():
    text = _text().replace(
        '<soap:operation soapAction="urn:GetOrder"/>', '<soap:operation soapAction="a" style="rpc"/>'
    )
    (operation,) = parse_wsdl(text).port_types[0].operations
    assert (operation.soap_action, operation.soap_style) == ("a", "rpc")


def test_the_first_binding_that_states_a_value_wins():
    second = (
        '<wsdl:binding name="B12" type="tns:Orders"><soap12:binding xmlns:soap12="http://schemas.xmlsoap.org/wsdl/soap12/"'
        ' style="document" transport="http://schemas.xmlsoap.org/soap/http"/>'
        '<wsdl:operation name="GetOrder"><soap12:operation xmlns:soap12="http://schemas.xmlsoap.org/wsdl/soap12/"'
        ' soapAction="urn:Other"/></wsdl:operation></wsdl:binding>'
    )
    text = _text(action="").replace("</wsdl:definitions>", second + "</wsdl:definitions>")
    (operation,) = parse_wsdl(text).port_types[0].operations
    assert operation.soap_action == "urn:Other"


def test_wsdl_2_records_wsoap_action():
    text = """<description xmlns="http://www.w3.org/ns/wsdl" xmlns:tns="urn:o" xmlns:wsoap="http://www.w3.org/ns/wsdl/soap"
      xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:o">
      <types><xs:schema targetNamespace="urn:o"><xs:element name="Ping"><xs:complexType><xs:sequence>
        <xs:element name="at" type="xs:dateTime"/></xs:sequence></xs:complexType></xs:element></xs:schema></types>
      <interface name="Pinger"><operation name="Ping" pattern="http://www.w3.org/ns/wsdl/in-only">
        <input element="tns:Ping"/></operation></interface>
      <binding name="PingSoap" interface="tns:Pinger" type="http://www.w3.org/ns/wsdl/soap">
        <operation ref="tns:Ping" wsoap:action="urn:Ping"/></binding>
    </description>"""
    (operation,) = parse_wsdl(text).port_types[0].operations
    assert operation.soap_action == "urn:Ping"


def test_a_list_simple_type_records_nothing():
    text = _text().replace(
        '<xs:simpleType name="Status"><xs:restriction base="xs:string">'
        '<xs:enumeration value="OPEN"/><xs:enumeration value="CLOSED"/></xs:restriction></xs:simpleType>',
        '<xs:simpleType name="Status"><xs:list itemType="xs:string"/></xs:simpleType>',
    )
    adapter = WsdlImportSource()
    field = _field(adapter.normalize(adapter.parse(text)), "status")
    assert field.extras == {"xsd_type": "Status"}


def test_the_emitter_writes_the_details_back():
    model = _model(style="rpc")
    emitted = _emitted_text(WsdlEmitter().emit(model))
    again = WsdlImportSource().normalize(WsdlImportSource().parse(emitted))
    for name in ("status", "note", "lines", "id"):
        assert _field(again, name).extras == _field(model, name).extras
    assert again.services[0].operations[0].extras == model.services[0].operations[0].extras


# ===========================================================================
# Grades
# ===========================================================================


@pytest.mark.parametrize(
    ("head", "key", "expected"),
    [
        ({"action": "urn:FetchOrder"}, "urn:o.Orders.GetOrder", ("breaking", "wsdl.soap-action-changed")),
        ({"style": "rpc"}, "urn:o.Orders.GetOrder", ("breaking", "wsdl.soap-style-changed")),
        ({"lines": 'type="xs:string" maxOccurs="3"'}, "urn:o.Order.lines", ("breaking", "wsdl.max-occurs-lowered")),
        (
            {"lines": 'type="xs:string" maxOccurs="unbounded" minOccurs="2"'},
            "urn:o.Order.lines",
            ("breaking", "wsdl.min-occurs-raised"),
        ),
        (
            {"lines": 'type="xs:string" maxOccurs="unbounded" minOccurs="0"'},
            "urn:o.Order.lines",
            ("dangerous", "wsdl.min-occurs-lowered"),
        ),
        (
            {"lines": 'type="xs:string" maxOccurs="unbounded" nillable="true"'},
            "urn:o.Order.lines",
            ("dangerous", "wsdl.made-nillable"),
        ),
        (
            {"lines": 'type="xs:string" maxOccurs="unbounded" default="x"'},
            "urn:o.Order.lines",
            ("dangerous", "wsdl.default-changed"),
        ),
        (
            {"lines": 'type="xs:int" maxOccurs="unbounded"'},
            "urn:o.Order.lines",
            ("breaking", "wsdl.element-type-changed"),
        ),
        ({"note_facets": '<xs:maxLength value="20"/>'}, "urn:o.Order.note", ("breaking", "wsdl.facet-narrowed")),
        ({"note_facets": '<xs:maxLength value="80"/>'}, "urn:o.Order.note", ("dangerous", "wsdl.facet-widened")),
        ({"note_facets": ""}, "urn:o.Order.note", ("dangerous", "wsdl.facet-widened")),
        (
            {"note_facets": '<xs:maxLength value="50"/><xs:pattern value="[a-z]*"/>'},
            "urn:o.Order.note",
            ("breaking", "wsdl.facet-narrowed"),
        ),
        (
            {"enum": '<xs:enumeration value="OPEN"/>'},
            "urn:o.Order.status",
            ("breaking", "wsdl.facet-narrowed"),
        ),
        (
            {"enum": '<xs:enumeration value="OPEN"/><xs:enumeration value="CLOSED"/><xs:enumeration value="HELD"/>'},
            "urn:o.Order.status",
            ("dangerous", "wsdl.facet-widened"),
        ),
        (
            {"extra": '<xs:element name="tag" type="xs:string" minOccurs="0"/>'},
            "urn:o.Order.tag",
            ("dangerous", "wsdl.element-added-optional"),
        ),
        (
            {"extra": '<xs:element name="code" type="xs:int"/>'},
            "urn:o.Order.code",
            ("breaking", "wsdl.element-added-required"),
        ),
        (
            {"lines": 'type="xs:string" maxOccurs="unbounded" minOccurs="1"'},
            "urn:o.Order.lines",
            ("safe", "wsdl.element-unchanged-on-the-wire"),
        ),
    ],
)
def test_grades(head: Dict[str, str], key: str, expected: Tuple[str, str]):
    grades = _grades({}, head)
    assert grades[key][:2] == expected


def test_nillable_true_to_false_is_breaking():
    grades = _grades(
        {"lines": 'type="xs:string" maxOccurs="unbounded" nillable="true"'},
        {"lines": 'type="xs:string" maxOccurs="unbounded" nillable="false"'},
    )
    assert grades["urn:o.Order.lines"][:2] == ("breaking", "wsdl.made-non-nillable")


def test_numeric_bounds_compare_by_value():
    base = {"note_facets": '<xs:minLength value="2"/><xs:maxInclusive value="10.5"/>'}
    narrowed = _grades(base, {"note_facets": '<xs:minLength value="3"/><xs:maxInclusive value="10.5"/>'})
    assert narrowed["urn:o.Order.note"][:2] == ("breaking", "wsdl.facet-narrowed")
    widened = _grades(base, {"note_facets": '<xs:minLength value="1"/><xs:maxInclusive value="20"/>'})
    assert widened["urn:o.Order.note"][:2] == ("dangerous", "wsdl.facet-widened")


def test_one_element_combines_its_grades():
    severity, rule, rationale = _grades({}, {"lines": 'type="xs:string" maxOccurs="2" minOccurs="0"'})[
        "urn:o.Order.lines"
    ]
    assert (severity, rule) == ("breaking", "wsdl.max-occurs-lowered")
    assert "may now be omitted" in rationale and "(was unbounded)" in rationale


def test_unchanged_documents_have_no_changes():
    assert _grades({}, {}) == {}


def test_a_new_operation_stays_safe():
    base = _model()
    text = _text().replace(
        "</wsdl:portType>",
        '<wsdl:operation name="Ping"><wsdl:input message="tns:In"/></wsdl:operation></wsdl:portType>',
    )
    head = WsdlImportSource().normalize(WsdlImportSource().parse(text))
    grades = {c.key: c for c in classify(diff(base, head), base, head).classifications}
    assert grades["urn:o.Orders.Ping"].severity.value == "safe"
