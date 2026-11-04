"""WSDL 2.0 output option — MFX-14.5 (#4182).

The WSDL emitter writes WSDL 1.1 by default; ``wsdl_version="2.0"`` writes a W3C WSDL 2.0
``description`` instead (:mod:`app.wsdl20_writer`). Covers, in order:

* the option: 1.1 stays the default and is unchanged; invalid values are refused;
* the 2.0 grammar: ``description`` / ``interface`` / ``binding`` / ``service`` / ``endpoint``, no
  ``message`` element, both layouts;
* message-exchange patterns, faults, SOAP 1.1 / 1.2 and HTTP bindings, ``wsoap:action``;
* the acceptance check — every export is valid against the W3C WSDL 2.0 schema and passes the
  emitted-bundle gate (:func:`app.wsdl_bundle_validation.validate_wsdl_bundle`);
* the differences from 1.1: each change a 1.1 source goes through is recorded as a loss and named in
  the fidelity report, a 2.0 source round-trips unchanged, and a one-way operation reads back one-way;
* the 2.0 structure check catching a dangling reference and a schema-invalid description.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List

import pytest
from pydantic import ValidationError
from test_wsdl_emitter import _EXAMPLES, _api, _corpus_api, _field, _pet, _service, _subjects

from app.canonical_model import (
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    TypeRef,
)
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import canonical_diff
from app.lossiness import LossinessKind
from app.roundtrip_matrix import reimport_emitted
from app.secure_xml import parse_xml
from app.wsdl20_validation import wsdl20_schema, wsdl20_structure_problems
from app.wsdl20_writer import SOAP11_HTTP_PROTOCOL, SOAP12_HTTP_PROTOCOL, soap_protocol
from app.wsdl_bundle_validation import inherited_wsi_rules, validate_wsdl_bundle
from app.wsdl_emitter import WsdlEmitOptions, WsdlEmitter
from app.wsdl_import_source import WsdlImportSource
from app.wsdl_versions import (
    MEP_IN_ONLY,
    MEP_IN_OUT,
    MEP_OUT_ONLY,
    MEP_ROBUST_IN_ONLY,
    WSDL_1_1_NAMESPACE,
    WSDL_2_0_NAMESPACE,
)

_W = f"{{{WSDL_2_0_NAMESPACE}}}"
_WSOAP = "{http://www.w3.org/ns/wsdl/soap}"
_WHTTP = "{http://www.w3.org/ns/wsdl/http}"


# ===========================================================================
# Helpers
# ===========================================================================


def _emit20(api: CanonicalApi, **opts):
    """Export ``api`` as WSDL 2.0 with the given extra options."""
    return WsdlEmitter().emit(api, opts=WsdlEmitOptions(wsdl_version="2.0", **opts))


def _root(result) -> ET.Element:
    """The parsed description of an export."""
    return ET.fromstring(result.files[0].content)


def _files(result) -> Dict[str, str]:
    """An export's members, path → text."""
    return {emitted.path: emitted.content for emitted in result.files}


def _schema_errors(result) -> List[str]:
    """Validation errors of the description against the W3C WSDL 2.0 schema."""
    return [str(error.reason) for error in wsdl20_schema().iter_errors(result.files[0].content)]


def _operations(result) -> Dict[str, ET.Element]:
    """Interface operations by name."""
    return {op.get("name"): op for op in _root(result).iter(f"{_W}operation") if op.get("name")}


def _wsdl_text(binding: str, extra_ns: str = "") -> str:
    """A minimal WSDL 1.1 description with one operation and the given binding block."""
    return f"""<?xml version="1.0"?>
<wsdl:definitions name="Echo" targetNamespace="urn:echo" xmlns:tns="urn:echo"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" {extra_ns}>
  <wsdl:types>
    <xsd:schema targetNamespace="urn:echo">
      <xsd:element name="Echo"><xsd:complexType><xsd:sequence>
        <xsd:element name="text" type="xsd:string"/></xsd:sequence></xsd:complexType></xsd:element>
      <xsd:element name="EchoResponse"><xsd:complexType><xsd:sequence>
        <xsd:element name="text" type="xsd:string"/></xsd:sequence></xsd:complexType></xsd:element>
    </xsd:schema>
  </wsdl:types>
  <wsdl:message name="EchoIn"><wsdl:part name="parameters" element="tns:Echo"/></wsdl:message>
  <wsdl:message name="EchoOut"><wsdl:part name="parameters" element="tns:EchoResponse"/></wsdl:message>
  <wsdl:portType name="EchoPort">
    <wsdl:operation name="Echo"><wsdl:input message="tns:EchoIn"/><wsdl:output message="tns:EchoOut"/>
    </wsdl:operation>
  </wsdl:portType>
  {binding}
  <wsdl:service name="EchoService">
    <wsdl:port name="EchoPort" binding="tns:EchoBinding"><address location="https://echo.example.com"/></wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""


def _imported(text: str) -> CanonicalApi:
    """Import one WSDL document."""
    source = WsdlImportSource()
    return source.normalize(source.parse(text, source_label="echo.wsdl"), include_raw=False)


def _one_way(*messages: Message) -> Service:
    """A service with one one-way operation carrying ``messages``."""
    return Service(
        key="Notify",
        name="Notify",
        operations=[
            Operation(
                key="notify",
                name="notify",
                kind=OperationKind.ONE_WAY,
                messages=[Message(key="notify#in", role=MessageRole.REQUEST, payload=TypeRef(name="Pet")), *messages],
            )
        ],
    )


_JSON_CORPUS = [
    _EXAMPLES / "openapi" / "07-nullable-types.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
]
_WSDL11_CORPUS = sorted((_EXAMPLES / "wsdl").glob("*.wsdl"))
_WSDL20_CORPUS = sorted((_EXAMPLES / "wsdl2").glob("*.wsdl"))


# ===========================================================================
# The option
# ===========================================================================


def test_wsdl_1_1_stays_the_default_and_is_unchanged() -> None:
    api = _api([_pet()], [_service()])
    default = WsdlEmitter().emit(api)
    explicit = WsdlEmitter().emit(api, opts=WsdlEmitOptions(wsdl_version="1.1"))
    assert WsdlEmitOptions().wsdl_version == "1.1"
    assert _files(default) == _files(explicit)
    assert _root(default).tag == f"{{{WSDL_1_1_NAMESPACE}}}definitions"


def test_an_unknown_version_is_refused() -> None:
    with pytest.raises(ValidationError):
        WsdlEmitOptions(wsdl_version="3.0")


def test_raw_options_select_2_0() -> None:
    options = WsdlEmitter.options_model.model_validate({"wsdl_version": "2.0", "layout": "single"})
    result = WsdlEmitter().emit(_api([_pet()], [_service()]), opts=options)
    assert _root(result).tag == f"{_W}description"


# ===========================================================================
# The 2.0 grammar
# ===========================================================================


def test_bundle_is_a_description_importing_its_schema() -> None:
    result = _emit20(_api([_pet()], [_service()]))
    assert [emitted.path for emitted in result.files] == ["Pets.wsdl", "Pets.xsd"]
    root = _root(result)
    assert root.tag == f"{_W}description"
    assert root.get("name") is None  # 2.0 has no description name
    assert root.get("targetNamespace") == "http://example.com/service"
    [types] = root.findall(f"{_W}types")
    [imported] = list(types)
    assert imported.tag == "{http://www.w3.org/2001/XMLSchema}import"
    assert imported.get("schemaLocation") == "Pets.xsd"
    assert not list(root.iter(f"{{{WSDL_1_1_NAMESPACE}}}message"))
    assert result.files[0].content.startswith("<!-- Generated WSDL 2.0 for Pets -->")


def test_single_layout_inlines_the_schema() -> None:
    result = _emit20(_api([_pet()], [_service()]), layout="single")
    assert len(result.files) == 1
    schemas = _root(result).find(f"{_W}types").findall("{http://www.w3.org/2001/XMLSchema}schema")
    assert len(schemas) == 1
    assert _schema_errors(result) == []


def test_operations_name_their_elements_and_pattern() -> None:
    result = _emit20(_api([_pet()], [_service()]))
    root = _root(result)
    [interface] = root.findall(f"{_W}interface")
    assert interface.get("name") == "default"
    get_pet = _operations(result)["getPetById"]
    assert get_pet.get("pattern") == MEP_IN_OUT
    assert get_pet.find(f"{_W}input").get("element") == "tns:getPetById"
    assert get_pet.find(f"{_W}output").get("element") == "tns:getPetByIdResponse"
    [outfault] = get_pet.findall(f"{_W}outfault")
    assert outfault.get("messageLabel") == "Out"
    faults = {fault.get("name"): fault.get("element") for fault in interface.findall(f"{_W}fault")}
    assert faults[outfault.get("ref").split(":")[1]] == "tns:getPetByIdStatus404Fault"


def test_default_binding_is_soap_1_1_and_service_names_its_interface() -> None:
    root = _root(_emit20(_api([_pet()], [_service()])))
    [binding] = root.findall(f"{_W}binding")
    assert binding.get("interface") == "tns:default"
    assert binding.get("type") == "http://www.w3.org/ns/wsdl/soap"
    assert binding.get(f"{_WSOAP}version") == "1.1"
    assert binding.get(f"{_WSOAP}protocol") == SOAP11_HTTP_PROTOCOL
    assert {op.get("ref") for op in binding.findall(f"{_W}operation")} == {"tns:getPetById", "tns:postPets"}
    [service] = root.findall(f"{_W}service")
    assert service.get("interface") == "tns:default"
    [endpoint] = service.findall(f"{_W}endpoint")
    assert endpoint.get("binding") == "tns:defaultBinding"
    assert endpoint.get("address") == "https://api.example.com/service"


# ===========================================================================
# Message-exchange patterns
# ===========================================================================


def test_one_way_is_in_only_and_reads_back_one_way() -> None:
    api = _api([_pet()], [_one_way()])
    result = _emit20(api)
    notify = _operations(result)["notify"]
    assert notify.get("pattern") == MEP_IN_ONLY
    assert notify.find(f"{_W}output") is None
    again = reimport_emitted(WsdlImportSource(), result, multi_file=True)
    assert again.services[0].operations[0].kind is OperationKind.ONE_WAY


def test_one_way_with_a_fault_is_robust_in_only() -> None:
    fault = Message(key="notify#err", role=MessageRole.ERROR, name="Busy", payload=TypeRef(name="Pet"))
    result = _emit20(_api([_pet()], [_one_way(fault)]))
    notify = _operations(result)["notify"]
    assert notify.get("pattern") == MEP_ROBUST_IN_ONLY
    [outfault] = notify.findall(f"{_W}outfault")
    assert outfault.get("messageLabel") == "In"
    assert _schema_errors(result) == []


def test_a_wsdl_notification_is_out_only() -> None:
    api = _corpus_api(_EXAMPLES / "wsdl2" / "04-stress-message-exchange-patterns.wsdl")
    operations = _operations(_emit20(api))
    assert operations["outOnly"].get("pattern") == MEP_OUT_ONLY
    assert operations["outOnly"].find(f"{_W}input") is None
    assert operations["robustInOnly"].get("pattern") == MEP_ROBUST_IN_ONLY


def test_a_fault_shared_by_operations_stays_one_interface_fault() -> None:
    api = _corpus_api(_EXAMPLES / "wsdl2" / "04-stress-message-exchange-patterns.wsdl")
    interface = _root(_emit20(api)).find(f"{_W}interface")
    assert [fault.get("name") for fault in interface.findall(f"{_W}fault")] == ["GeneralFault"]


# ===========================================================================
# Bindings carried from a WSDL source
# ===========================================================================


def test_soap_protocol_maps_the_1_1_http_transport_per_version() -> None:
    assert soap_protocol("1.1", "http://schemas.xmlsoap.org/soap/http") == SOAP11_HTTP_PROTOCOL
    assert soap_protocol("1.2", "http://schemas.xmlsoap.org/soap/http/") == SOAP12_HTTP_PROTOCOL
    assert soap_protocol("1.2", None) == SOAP12_HTTP_PROTOCOL
    assert soap_protocol("1.1", SOAP11_HTTP_PROTOCOL) == SOAP11_HTTP_PROTOCOL
    assert soap_protocol("1.1", "http://www.w3.org/2010/soapjms/") == "http://www.w3.org/2010/soapjms/"


def test_soap_1_2_binding_keeps_its_version_and_soap_action() -> None:
    api = _imported(_wsdl_text(
        """<wsdl:binding name="EchoBinding" type="tns:EchoPort">
        <soap12:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>
        <wsdl:operation name="Echo"><soap12:operation soapAction="urn:echo#Echo"/>
          <wsdl:input><soap12:body use="literal"/></wsdl:input><wsdl:output><soap12:body use="literal"/></wsdl:output>
        </wsdl:operation></wsdl:binding>""",
        'xmlns:soap12="http://schemas.xmlsoap.org/wsdl/soap12/"',
    ).replace("<address", '<soap12:address').replace('"https://echo.example.com"/>', '"https://echo.example.com"/>'))
    result = _emit20(api)
    [binding] = _root(result).findall(f"{_W}binding")
    assert binding.get(f"{_WSOAP}version") == "1.2"
    assert binding.get(f"{_WSOAP}protocol") == SOAP12_HTTP_PROTOCOL
    assert binding.find(f"{_W}operation").get(f"{_WSOAP}action") == "urn:echo#Echo"
    assert validate_wsdl_bundle(_files(result)) == []
    again = reimport_emitted(WsdlImportSource(), result, multi_file=True)
    assert again.servers[0].protocol == "soap12"
    assert again.services[0].operations[0].extras["wsdl_soap_action"] == "urn:echo#Echo"


def test_http_binding_is_a_2_0_http_binding() -> None:
    api = _imported(_wsdl_text(
        """<wsdl:binding name="EchoBinding" type="tns:EchoPort"><http:binding verb="POST"/>
        <wsdl:operation name="Echo"><http:operation location="/Echo"/></wsdl:operation></wsdl:binding>""",
        'xmlns:http="http://schemas.xmlsoap.org/wsdl/http/"',
    ).replace("<address", "<http:address"))
    result = _emit20(api)
    [binding] = _root(result).findall(f"{_W}binding")
    assert binding.get("type") == "http://www.w3.org/ns/wsdl/http"
    assert binding.get(f"{_WHTTP}methodDefault") == "POST"
    assert binding.find(f"{_W}operation").get(f"{_WHTTP}location") == "Echo"
    assert validate_wsdl_bundle(_files(result)) == []
    assert reimport_emitted(WsdlImportSource(), result, multi_file=True).servers[0].protocol == "http"


# ===========================================================================
# Acceptance: schema-valid WSDL 2.0, through the emitted-bundle gate
# ===========================================================================


@pytest.mark.parametrize("layout", ["bundle", "single"])
@pytest.mark.parametrize(
    "path", _JSON_CORPUS + _WSDL11_CORPUS + _WSDL20_CORPUS, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_corpus_export_is_valid_wsdl_2_0(path: Path, layout: str) -> None:
    api = _corpus_api(path)
    result = _emit20(api, layout=layout)
    assert _schema_errors(result) == []
    assert validate_wsdl_bundle(_files(result), inherited_rules=inherited_wsi_rules(api)) == []


@pytest.mark.parametrize("path", _WSDL20_CORPUS, ids=lambda p: p.name)
def test_wsdl_2_0_corpus_round_trips_unchanged(path: Path) -> None:
    api = _corpus_api(path)
    again = reimport_emitted(WsdlImportSource(), _emit20(api), multi_file=True)
    assert canonical_diff(api, again).entries == []


@pytest.mark.parametrize("path", _WSDL11_CORPUS, ids=lambda p: p.name)
def test_a_1_1_source_changes_only_where_a_loss_is_recorded(path: Path) -> None:
    """Each operation or type a 1.1 → 2.0 round trip changes has a recorded loss (besides one-way kinds)."""
    api = _corpus_api(path)
    result = _emit20(api)
    again = reimport_emitted(WsdlImportSource(), result, multi_file=True)
    pointers = {loss.pointer for loss in result.losses}
    message_owners = {
        message.key: operation.key
        for service in api.services
        for operation in service.operations
        for message in operation.messages
    }
    pointers |= {message_owners[p] for p in pointers if p in message_owners}
    operations = {op.key: op for service in api.services for op in service.operations}
    for entry in canonical_diff(api, again).entries:
        if entry.entity == "root":
            continue
        if entry.entity == "operation" and entry.key not in pointers:
            # A 1.1 input-only operation read back request/response; 2.0 says in-only.
            assert operations[entry.key].kind is OperationKind.REQUEST_RESPONSE
            assert next(op for s in again.services for op in s.operations if op.key == entry.key).kind is (
                OperationKind.ONE_WAY
            )
            continue
        assert entry.key in pointers, entry


# ===========================================================================
# Differences from 1.1, in the losses and the fidelity report
# ===========================================================================


def test_kitchen_sink_reports_every_1_1_only_construct() -> None:
    api = _corpus_api(_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl")
    result = _emit20(api)
    subjects = _subjects(result)
    assert "rpc-style-as-document" in subjects
    assert "message-parts-wrapped" in subjects
    assert "service-split" in subjects
    assert "description-name-dropped" in subjects
    report = compute_lossiness_for_emitter(api, WsdlEmitter, options={"wsdl_version": "2.0"})
    mappings = {item.target_mapping for item in report.items}
    assert {"rpc-style-as-document", "message-parts-wrapped", "service-split", "description-name-dropped"} <= mappings


def test_the_1_1_report_has_none_of_the_2_0_entries() -> None:
    api = _corpus_api(_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl")
    report = compute_lossiness_for_emitter(api, WsdlEmitter)
    assert not {item.target_mapping for item in report.items} & {
        "rpc-style-as-document", "message-parts-wrapped", "service-split", "description-name-dropped",
        "scalar-payload-as-element",
    }


def test_a_multi_part_message_is_one_wrapper_element() -> None:
    api = _corpus_api(_EXAMPLES / "wsdl" / "04-kitchen-sink.wsdl")
    result = _emit20(api, layout="single")
    status = _operations(result)["GetSensorStatus"]
    element = status.find(f"{_W}input").get("element").split(":")[1]
    schema = _root(result).find(f"{_W}types")[0]
    [wrapper] = [el for el in schema if el.get("name") == element]
    assert len(list(wrapper.iter("{http://www.w3.org/2001/XMLSchema}element"))) > 1


def test_a_one_way_operation_is_approximated_in_1_1_only() -> None:
    api = _api([_pet()], [_one_way()])

    def one_way_items(options):
        report = compute_lossiness_for_emitter(api, WsdlEmitter, options=options)
        return [item for item in report.items if "one-way" in (item.target_mapping or "")]

    assert one_way_items({})
    assert one_way_items({"wsdl_version": "2.0"}) == []


def test_invalid_report_options_fall_back_to_1_1() -> None:
    api = _api([_pet()], [_one_way()])
    report = compute_lossiness_for_emitter(api, WsdlEmitter, options={"wsdl_version": "9"})
    assert any("one-way" in (item.target_mapping or "") for item in report.items)


def test_a_2_0_source_reports_no_description_name_loss() -> None:
    api = _corpus_api(_EXAMPLES / "wsdl2" / "02-typical-orders.wsdl")
    result = _emit20(api)
    assert result.losses == []
    report = compute_lossiness_for_emitter(api, WsdlEmitter, options={"wsdl_version": "2.0"})
    assert all(item.kind is LossinessKind.OK for item in report.items)


def test_a_types_only_model_gets_one_empty_interface() -> None:
    api = _api([_pet()])
    result = _emit20(api)
    [interface] = _root(result).findall(f"{_W}interface")
    assert interface.get("name") == "Pets" and list(interface) == []
    assert "empty-interface-synthesized" in _subjects(result)
    assert validate_wsdl_bundle(_files(result)) == []
    report = compute_lossiness_for_emitter(api, WsdlEmitter, options={"wsdl_version": "2.0"})
    assert any(item.kind is LossinessKind.SYNTH for item in report.items)


def test_a_json_source_reports_the_name_and_keeps_its_mapping_losses() -> None:
    api = _api([_pet(_field("age", TypeRef(name="integer", nullable=True)))], [_service()])
    subjects = _subjects(_emit20(api))
    assert subjects["description-name-dropped"] == [""]
    assert "null-as-nillable" in subjects
    assert "http-binding-dropped" in subjects


# ===========================================================================
# The 2.0 structure check
# ===========================================================================


def test_structure_check_finds_a_dangling_element_reference() -> None:
    files = _files(_emit20(_api([_pet()], [_service()]), layout="single"))
    broken = files["Pets.wsdl"].replace('element="tns:getPetByIdResponse"', 'element="tns:missing"')
    problems = wsdl20_structure_problems("Pets.wsdl", parse_xml(broken), {"Pets.wsdl": broken})
    assert len(problems) == 1
    assert "'tns:missing'" in problems[0][0]
    [problem] = validate_wsdl_bundle({"Pets.wsdl": broken})
    assert problem.rule == "wsdl.structure"


def test_structure_check_finds_a_dangling_binding_and_fault() -> None:
    text = _files(_emit20(_api([_pet()], [_service()]), layout="single"))["Pets.wsdl"]
    broken = text.replace('binding="tns:defaultBinding"', 'binding="tns:Nope"').replace(
        'outfault ref="tns:', 'outfault ref="tns:x'
    )
    problems = wsdl20_structure_problems("Pets.wsdl", parse_xml(broken), {"Pets.wsdl": broken})
    messages = [message for message, _ in problems]
    assert any("binding 'tns:Nope'" in message for message in messages)
    assert any("outfault" in message for message in messages)


def test_structure_check_reports_a_schema_invalid_description() -> None:
    text = _files(_emit20(_api([_pet()], [_service()]), layout="single"))["Pets.wsdl"]
    broken = text.replace('<wsdl:interface name="default">', "<wsdl:interface>", 1)
    assert broken != text
    problems = wsdl20_structure_problems("Pets.wsdl", parse_xml(broken), {"Pets.wsdl": broken})
    assert problems and problems[0][0].startswith("Not valid against the WSDL 2.0 schema")


def test_structure_check_reports_a_schema_that_does_not_build() -> None:
    files = _files(_emit20(_api([_pet()], [_service()])))
    files["Pets.xsd"] = files["Pets.xsd"].replace('type="xsd:string"', 'type="tns:Undefined"', 1)
    problems = validate_wsdl_bundle(files)
    assert any(problem.rule == "wsdl.structure" and problem.file == "Pets.xsd" for problem in problems), problems
