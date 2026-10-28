"""Tests for the completed WSDL → canonical model — MFI-13.2 (#3789).

Ports and bindings (servers with protocol and topology), faults (``error`` messages) and
multi-part messages (synthesized record types), in both grammars, and the WSDL emitter writing
them back so a re-import gives the same model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.canonical_model import MessageRole
from app.roundtrip_matrix import reimport_emitted
from app.wsdl_emitter import WsdlEmitter
from app.wsdl_import_source import WsdlImportSource
from app.wsdl_parser import parse_wsdl

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _model(text: str):
    adapter = WsdlImportSource()
    return adapter.normalize(adapter.parse(text), include_raw=False)


def _reimport(model) -> Any:
    """Export ``model`` (the default WSDL + XSD bundle) and re-import it as a fileset."""
    result = WsdlEmitter().emit(model)
    return reimport_emitted(WsdlImportSource(), result, multi_file=True)


def _operation(model, name: str):
    return next(op for service in model.services for op in service.operations if op.name == name)


# ===========================================================================
# Ports and bindings
# ===========================================================================


def test_bindings_record_port_type_protocol_and_transport():
    document = parse_wsdl((_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl").read_text(encoding="utf-8"))
    assert [(b.name, b.port_type, b.protocol, b.transport) for b in document.bindings] == [
        ("IngestionSoap11Binding", "IngestionPort", "soap11", "http://schemas.xmlsoap.org/soap/http"),
        ("IngestionSoap12Binding", "IngestionPort", "soap12", "http://schemas.xmlsoap.org/soap/http"),
        ("AlarmBinding", "AlarmPort", "soap11", "http://schemas.xmlsoap.org/soap/http"),
    ]


def test_wsdl_2_bindings_read_soap_version_and_http():
    document = parse_wsdl(
        (_EXAMPLES / "wsdl2" / "04-stress-message-exchange-patterns.wsdl").read_text(encoding="utf-8")
    )
    protocols = {b.name: b.protocol for b in document.bindings}
    assert protocols == {"MepHttpBinding": "http", "MepSoapBinding": "soap12"}
    soap11 = """<description xmlns="http://www.w3.org/ns/wsdl" xmlns:tns="urn:p" xmlns:wsoap="http://www.w3.org/ns/wsdl/soap"
      xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:p">
      <types><xs:schema targetNamespace="urn:p"><xs:element name="Ping" type="xs:string"/></xs:schema></types>
      <interface name="I"><operation name="Ping" pattern="http://www.w3.org/ns/wsdl/in-only">
        <input element="tns:Ping"/></operation></interface>
      <binding name="B" interface="tns:I" type="http://www.w3.org/ns/wsdl/soap" wsoap:version="1.1"
        wsoap:protocol="http://www.w3.org/2006/01/soap11/bindings/HTTP/"/>
      <service name="S" interface="tns:I"><endpoint name="E" binding="tns:B" address="https://p.example/ping"/></service>
    </description>"""
    (server,) = _model(soap11).servers
    assert (server.name, server.protocol) == ("E", "soap11")
    assert server.extras == {
        "wsdl_service": "S",
        "wsdl_binding": "B",
        "wsdl_port_type": "I",
        "wsdl_transport": "http://www.w3.org/2006/01/soap11/bindings/HTTP/",
    }


def test_each_port_is_a_named_server_with_its_protocol_and_topology():
    model = _model((_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl").read_text(encoding="utf-8"))
    summary = [(s.name, s.protocol, s.extras["wsdl_binding"], s.extras["wsdl_port_type"]) for s in model.servers]
    assert summary == [
        ("IngestionSoap11Port", "soap11", "IngestionSoap11Binding", "IngestionPort"),
        ("IngestionSoap12Port", "soap12", "IngestionSoap12Binding", "IngestionPort"),
        ("AlarmPort", "soap11", "AlarmBinding", "AlarmPort"),
    ]
    assert all(s.description == f"TelemetryHubService/{s.name}" for s in model.servers)


def test_a_port_naming_an_unknown_binding_has_no_protocol():
    text = (_EXAMPLES / "wsdl" / "01-calculator.wsdl").read_text(encoding="utf-8")
    text = text.replace('binding="tns:CalculatorBinding"', 'binding="tns:MissingBinding"')
    (server,) = _model(text).servers
    assert server.protocol is None
    assert server.extras == {"wsdl_service": server.extras["wsdl_service"], "wsdl_binding": "MissingBinding"}


# ===========================================================================
# Faults
# ===========================================================================


def test_wsdl_1_1_faults_are_error_messages():
    model = _model((_EXAMPLES / "wsdl" / "06-bank-transfer.wsdl").read_text(encoding="utf-8"))
    errors = [m for m in _operation(model, "TransferFunds").messages if m.role is MessageRole.ERROR]
    assert [(m.key.rsplit("#", 1)[-1], m.name) for m in errors] == [("fault.insufficientFunds", "insufficientFunds")]
    assert errors[0].payload is not None


def test_wsdl_2_outfaults_are_error_messages_with_the_interface_fault_element():
    model = _model((_EXAMPLES / "wsdl2" / "02-typical-orders.wsdl").read_text(encoding="utf-8"))
    (fault,) = [m for m in _operation(model, "getOrder").messages if m.role is MessageRole.ERROR]
    assert fault.name == "OrderFault"
    assert fault.payload is not None and fault.payload.name


def test_a_fault_message_without_parts_has_no_payload():
    text = (_EXAMPLES / "wsdl" / "06-bank-transfer.wsdl").read_text(encoding="utf-8")
    document = parse_wsdl(text)
    fault_message = next(m for m in document.messages if m.name == "InsufficientFundsMessage")
    part = fault_message.parts[0]
    stripped = text.replace(f'<wsdl:part name="{part.name}" element="tns:{part.element}"/>', "")
    if stripped == text:
        pytest.skip("fixture spells the fault part differently")
    (fault,) = [m for m in _operation(_model(stripped), "TransferFunds").messages if m.role is MessageRole.ERROR]
    assert fault.payload is None


# ===========================================================================
# Multi-part messages
# ===========================================================================


def test_a_multi_part_message_becomes_a_record_type_with_one_field_per_part():
    model = _model((_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl").read_text(encoding="utf-8"))
    request = next(m for m in _operation(model, "GetSensorStatus").messages if m.role is MessageRole.REQUEST)
    payload_type = next(t for t in model.types if t.key == request.payload.name)
    assert payload_type.extras == {"wsdl_kind": "message", "wsdl_message": "GetSensorStatusInput"}
    assert [(f.name, f.type.name, f.extras) for f in sorted(payload_type.fields, key=lambda f: f.field_number)] == [
        ("sensorId", "string", {"wsdl_part_type": "string"}),
        ("includeHistory", "bool", {"wsdl_part_type": "boolean"}),
    ]


def test_element_parts_take_the_element_type_and_a_clashing_name_gets_a_suffix():
    text = """<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
      xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:tns="urn:m" targetNamespace="urn:m">
      <wsdl:types><xs:schema targetNamespace="urn:m">
        <xs:complexType name="Pair"><xs:sequence><xs:element name="a" type="xs:string"/></xs:sequence></xs:complexType>
        <xs:element name="Left" type="tns:Pair"/>
      </xs:schema></wsdl:types>
      <wsdl:message name="Pair"><wsdl:part name="left" element="tns:Left"/>
        <wsdl:part name="count" type="xs:int"/></wsdl:message>
      <wsdl:portType name="P"><wsdl:operation name="Op">
        <wsdl:input message="tns:Pair"/></wsdl:operation></wsdl:portType>
    </wsdl:definitions>"""
    model = _model(text)
    message_type = next(t for t in model.types if t.extras.get("wsdl_kind") == "message")
    assert message_type.name == "PairMessage"
    left = next(f for f in message_type.fields if f.field_number == 1)
    assert (left.name, left.type.name, left.extras) == ("left", "urn:m.Pair", {"wsdl_part_element": "Left"})
    reimported = _reimport(model)
    again = next(t for t in reimported.types if t.extras.get("wsdl_kind") == "message")
    assert again.fields == message_type.fields


# ===========================================================================
# The emitter writes it all back
# ===========================================================================


@pytest.mark.parametrize(
    "path",
    [
        _EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl",
        _EXAMPLES / "wsdl" / "06-bank-transfer.wsdl",
        _EXAMPLES / "wsdl2" / "02-typical-orders.wsdl",
        _EXAMPLES / "wsdl2" / "04-stress-message-exchange-patterns.wsdl",
    ],
    ids=lambda p: p.name,
)
def test_a_re_import_of_the_export_keeps_servers_faults_and_message_types(path: Path):
    model = _model(path.read_text(encoding="utf-8"))
    again = _reimport(model)
    assert again.servers == model.servers
    for service in model.services:
        for operation in service.operations:
            before = sorted(
                (m.model_dump() for m in operation.messages if m.role is MessageRole.ERROR), key=lambda m: m["key"]
            )
            after = sorted(
                (m.model_dump() for m in _operation(again, operation.name).messages if m.role is MessageRole.ERROR),
                key=lambda m: m["key"],
            )
            assert after == before
    message_types = {t.key: t.fields for t in model.types if t.extras.get("wsdl_kind") == "message"}
    assert {t.key: t.fields for t in again.types if t.extras.get("wsdl_kind") == "message"} == message_types


def test_a_model_without_wsdl_topology_keeps_the_single_binding_export():
    model = _model((_EXAMPLES / "wsdl" / "01-calculator.wsdl").read_text(encoding="utf-8"))
    bare = model.model_copy(
        update={"servers": [s.model_copy(update={"extras": {}, "name": None, "protocol": None}) for s in model.servers]}
    )
    text = WsdlEmitter().emit(bare).files[0].content
    assert "Binding" in text and "Service" in text
    (server,) = _model(text).servers
    assert server.protocol == "soap11"
