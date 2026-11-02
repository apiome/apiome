"""WSDL and XSD imports across a multi-file set — MFI-13.1 (#3788).

Through the import adapters: a description or schema split across files in folders imports as
one, with each location resolved relative to the file that declares it; a WSDL 2.0 description
pulls in what it imports and includes; WS-I lint agrees with the parser on what resolves; and
XSD 1.1 is recognized.
"""

from __future__ import annotations

from typing import Dict

import pytest

from app.fileset import IntakeFileset
from app.wsdl_import_source import WsdlImportSource
from app.xsd_import_source import XsdImportSource

_WSDL = WsdlImportSource()
_XSD = XsdImportSource()

XS = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'


def _wsdl_set(members: Dict[str, str], root: str):
    fileset = IntakeFileset.from_members(members, root=root)
    document = _WSDL.parse_fileset(fileset)
    return document, _WSDL.normalize(document, include_raw=False)


def _xsd_set(members: Dict[str, str], root: str):
    fileset = IntakeFileset.from_members(members, root=root)
    document = _XSD.parse_fileset(fileset)
    return document, _XSD.normalize(document, include_raw=False)


def _type_names(api) -> set[str]:
    return {t.name for t in api.types}


# --- WSDL 1.1 in folders ---------------------------------------------------------------------

_SERVICE_11 = """<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:tns="urn:orders" targetNamespace="urn:orders" name="Orders">
  <wsdl:types>
    <xs:schema targetNamespace="urn:orders">
      <xs:import namespace="urn:orders:types" schemaLocation="../schemas/orders.xsd"/>
    </xs:schema>
  </wsdl:types>
  <wsdl:message name="GetOrder"><wsdl:part name="body" element="tns:getOrder"/></wsdl:message>
  <wsdl:portType name="OrdersPort">
    <wsdl:operation name="GetOrder"><wsdl:input message="tns:GetOrder"/></wsdl:operation>
  </wsdl:portType>
</wsdl:definitions>"""

_ORDERS_XSD = f"""<xs:schema {XS} targetNamespace="urn:orders:types">
  <xs:include schemaLocation="common/address.xsd"/>
  <xs:element name="getOrder" type="Order"/>
  <xs:complexType name="Order"><xs:sequence><xs:element name="id" type="xs:string"/></xs:sequence></xs:complexType>
</xs:schema>"""

_ADDRESS_XSD = f"""<xs:schema {XS} targetNamespace="urn:orders:types">
  <xs:complexType name="Address"><xs:sequence><xs:element name="city" type="xs:string"/></xs:sequence></xs:complexType>
</xs:schema>"""

#: A same-named file elsewhere in the set, which a basename guess would have picked.
_DECOY_ADDRESS_XSD = f"""<xs:schema {XS} targetNamespace="urn:decoy">
  <xs:complexType name="Decoy"/>
</xs:schema>"""


def test_a_wsdl_set_in_folders_resolves_relative_locations() -> None:
    members = {
        "wsdl/orders.wsdl": _SERVICE_11,
        "schemas/orders.xsd": _ORDERS_XSD,
        "schemas/common/address.xsd": _ADDRESS_XSD,
        "legacy/common/address.xsd": _DECOY_ADDRESS_XSD,
    }
    document, api = _wsdl_set(members, "wsdl/orders.wsdl")
    assert {"Order", "Address"} <= _type_names(api)
    assert "Decoy" not in _type_names(api)
    graph = api.extras["xml_import_graph"]
    assert [d["path"] for d in graph["documents"]] == [
        "wsdl/orders.wsdl",
        "schemas/orders.xsd",
        "schemas/common/address.xsd",
    ]
    assert graph["unresolved"] == []
    # WS-I resolves the same way, so it reports nothing unresolved.
    assert not [issue for issue in document.wsi_issues if issue["rule"] == "wsi.unresolved-import"]


def test_an_unresolved_import_is_recorded_and_linted() -> None:
    members = {"wsdl/orders.wsdl": _SERVICE_11}
    document, api = _wsdl_set(members, "wsdl/orders.wsdl")
    assert api.extras["xml_import_graph"]["unresolved"] == [
        {"declared_in": "wsdl/orders.wsdl", "location": "../schemas/orders.xsd", "reason": "missing"}
    ]
    assert [issue for issue in document.wsi_issues if issue["rule"] == "wsi.unresolved-import"]


def test_a_single_wsdl_file_records_no_graph() -> None:
    api = _WSDL.normalize(_WSDL.parse(_SERVICE_11), include_raw=False)
    assert "xml_import_graph" not in api.extras
    assert "xsd_version" not in api.extras


# --- WSDL 2.0 import / include ----------------------------------------------------------------

_W20 = 'xmlns="http://www.w3.org/ns/wsdl" xmlns:tns="urn:ship" targetNamespace="urn:ship"'

_SHIP_ROOT = f"""<description {_W20}>
  <include location="parts/interface.wsdl"/>
  <service name="Shipping" interface="tns:Tracking">
    <endpoint name="ShippingEndpoint" binding="tns:TrackingSoap" address="https://example.com/ship"/>
  </service>
</description>"""

_SHIP_INTERFACE = f"""<description {_W20} xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <types><xs:schema targetNamespace="urn:ship">
    <xs:element name="track"><xs:complexType><xs:sequence>
      <xs:element name="id" type="xs:string"/></xs:sequence></xs:complexType></xs:element>
  </xs:schema></types>
  <interface name="Tracking">
    <operation name="Track" pattern="http://www.w3.org/ns/wsdl/in-out">
      <input element="tns:track"/><output element="tns:track"/>
    </operation>
  </interface>
  <binding name="TrackingSoap" interface="tns:Tracking" type="http://www.w3.org/ns/wsdl/soap"/>
</description>"""


def test_a_wsdl_2_0_description_includes_its_interface_from_another_file() -> None:
    _, api = _wsdl_set({"ship.wsdl": _SHIP_ROOT, "parts/interface.wsdl": _SHIP_INTERFACE}, "ship.wsdl")
    operations = [operation.name for service in api.services for operation in service.operations]
    assert "Track" in operations
    assert "track" in _type_names(api)


def test_a_wsdl_2_0_service_naming_an_interface_nothing_declares_still_fails() -> None:
    with pytest.raises(Exception, match="does not declare|no `interface`"):
        _wsdl_set({"ship.wsdl": _SHIP_ROOT}, "ship.wsdl")


# --- XSD sets ---------------------------------------------------------------------------------

_INVOICE = f"""<xs:schema {XS} xmlns:c="urn:common" targetNamespace="urn:invoice">
  <xs:import namespace="urn:common" schemaLocation="common/party.xsd"/>
  <xs:include schemaLocation="lines.xsd"/>
  <xs:element name="invoice" type="Invoice"/>
  <xs:complexType name="Invoice"><xs:sequence>
    <xs:element name="seller" type="c:Party"/><xs:element name="line" type="Line"/>
  </xs:sequence></xs:complexType>
</xs:schema>"""

_LINES = f"""<xs:schema {XS} targetNamespace="urn:invoice">
  <xs:complexType name="Line"><xs:sequence><xs:element name="sku" type="xs:string"/></xs:sequence></xs:complexType>
  <xs:complexType name="Invoice"><xs:sequence>
    <xs:element name="shadowed" type="xs:string"/></xs:sequence></xs:complexType>
</xs:schema>"""

_PARTY = f"""<xs:schema {XS} targetNamespace="urn:common">
  <xs:complexType name="Party"><xs:sequence><xs:element name="name" type="xs:string"/></xs:sequence></xs:complexType>
  <xs:simpleType name="Country"><xs:restriction base="xs:string">
    <xs:enumeration value="JP"/></xs:restriction></xs:simpleType>
</xs:schema>"""


def test_an_xsd_set_reads_the_types_of_every_schema_it_imports() -> None:
    members = {"xsd/invoice.xsd": _INVOICE, "xsd/lines.xsd": _LINES, "xsd/common/party.xsd": _PARTY}
    document, api = _xsd_set(members, "xsd/invoice.xsd")
    assert {"Invoice", "Line", "Party", "Country"} <= _type_names(api)
    # The root's declaration wins over a same-named one in an included file.
    invoice = next(t for t in api.types if t.name == "Invoice")
    assert {f.name for f in invoice.fields} == {"seller", "line"}
    assert document.root_element == "invoice"
    assert len(api.extras["xml_import_graph"]["documents"]) == 3


def test_an_xsd_alone_ignores_its_imports_as_before() -> None:
    api = _XSD.normalize(_XSD.parse(_INVOICE), include_raw=False)
    assert _type_names(api) == {"Invoice"}
    assert "xml_import_graph" not in api.extras


def test_an_xsd_root_that_only_includes_others_imports_their_types() -> None:
    root = f'<xs:schema {XS} targetNamespace="urn:invoice"><xs:include schemaLocation="lines.xsd"/></xs:schema>'
    _, api = _xsd_set({"root.xsd": root, "lines.xsd": _LINES}, "root.xsd")
    assert {"Line", "Invoice"} <= _type_names(api)


# --- XSD 1.1 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [
        f'<xs:schema {XS} xmlns:vc="http://www.w3.org/2007/XMLSchema-versioning" vc:minVersion="1.1">'
        '<xs:complexType name="T"/></xs:schema>',
        f'<xs:schema {XS}><xs:complexType name="T"><xs:assert test="true()"/></xs:complexType></xs:schema>',
        f'<xs:schema {XS}><xs:element name="e" type="xs:string"><xs:alternative type="xs:int"/></xs:element>'
        '<xs:complexType name="T"/></xs:schema>',
        f"<xs:schema {XS}><xs:defaultOpenContent><xs:any/></xs:defaultOpenContent>"
        '<xs:complexType name="T"/></xs:schema>',
    ],
)
def test_an_xsd_1_1_schema_is_recognized(schema: str) -> None:
    api = _XSD.normalize(_XSD.parse(schema), include_raw=False)
    assert api.extras["xsd_version"] == "1.1"


def test_an_xsd_1_0_schema_records_no_version() -> None:
    api = _XSD.normalize(_XSD.parse(f'<xs:schema {XS}><xs:complexType name="T"/></xs:schema>'), include_raw=False)
    assert "xsd_version" not in api.extras


def test_an_xsd_1_1_schema_imported_by_a_wsdl_marks_the_wsdl() -> None:
    schema = (
        f'<xs:schema {XS} targetNamespace="urn:orders:types"><xs:complexType name="Order">'
        '<xs:assert test="true()"/></xs:complexType><xs:element name="getOrder" type="Order"/></xs:schema>'
    )
    _, api = _wsdl_set({"wsdl/orders.wsdl": _SERVICE_11, "schemas/orders.xsd": schema}, "wsdl/orders.wsdl")
    assert api.extras["xsd_version"] == "1.1"
