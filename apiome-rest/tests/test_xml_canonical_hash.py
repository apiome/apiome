"""Tests for the canonical-XML hash of WSDL / XSD imports — MFI-13.1 (#3788).

The hash is taken over Canonical XML 2.0 of every document a description reaches, after resolving
its imports: formatting (whitespace, comments, attribute order, prefix choice) does not move it, a
real edit to the root *or to an imported file* does. It is the WSDL / XSD ``format_hash`` and stays
out of the semantic version fingerprint.
"""

from __future__ import annotations

from app.fileset import IntakeFileset
from app.fingerprint import fingerprint, get_fingerprint_hasher
from app.wsdl_import_source import WsdlImportSource
from app.xml_canonical_hash import C14N_ALGORITHM, WsdlCanonicalXmlHasher, XsdCanonicalXmlHasher
from app.xsd_import_source import XsdImportSource

_XSD = XsdImportSource()
_WSDL = WsdlImportSource()

SCHEMA = """<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:tns="urn:o" targetNamespace="urn:o">
  <!-- orders -->
  <xs:element name="order" type="tns:Order"/>
  <xs:complexType name="Order">
    <xs:sequence><xs:element name="id" type="xs:string"/></xs:sequence>
  </xs:complexType>
</xs:schema>"""

#: The same schema: other prefixes, attribute order, no whitespace, no comment.
REFORMATTED = (
    '<xsd:schema targetNamespace="urn:o" xmlns:p="urn:o" xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
    '<xsd:element type="p:Order" name="order"/><xsd:complexType name="Order"><xsd:sequence>'
    '<xsd:element type="xsd:string" name="id"/></xsd:sequence></xsd:complexType></xsd:schema>'
)

ROOT_WITH_INCLUDE = (
    '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:tns="urn:o" targetNamespace="urn:o">'
    '<xs:include schemaLocation="types/order.xsd"/><xs:element name="order" type="tns:Order"/></xs:schema>'
)
INCLUDED = (
    '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:o">'
    '<xs:complexType name="Order"><xs:sequence><xs:element name="id" type="xs:string"/>'
    "</xs:sequence></xs:complexType></xs:schema>"
)


def _xsd_model(text: str):
    return _XSD.normalize(_XSD.parse(text), include_raw=False)


def _xsd_set_model(included: str = INCLUDED):
    members = {"order.xsd": ROOT_WITH_INCLUDE, "types/order.xsd": included}
    fileset = IntakeFileset.from_members(members, root="order.xsd")
    return _XSD.normalize(_XSD.parse_fileset(fileset), include_raw=False)


def test_formatting_does_not_move_the_hash() -> None:
    assert _xsd_model(SCHEMA).extras["xml_c14n_sha256"] == _xsd_model(REFORMATTED).extras["xml_c14n_sha256"]
    assert _xsd_model(SCHEMA).extras["xml_c14n_algorithm"] == C14N_ALGORITHM


def test_a_real_edit_moves_the_hash() -> None:
    edited = SCHEMA.replace('name="id" type="xs:string"', 'name="id" type="xs:int"')
    assert _xsd_model(SCHEMA).extras["xml_c14n_sha256"] != _xsd_model(edited).extras["xml_c14n_sha256"]


def test_an_edit_to_an_imported_file_moves_the_hash() -> None:
    edited = INCLUDED.replace('type="xs:string"', 'type="xs:int"')
    assert _xsd_set_model().extras["xml_c14n_sha256"] != _xsd_set_model(edited).extras["xml_c14n_sha256"]


def test_reformatting_an_imported_file_keeps_the_hash() -> None:
    reformatted = INCLUDED.replace("><", ">\n  <")
    assert _xsd_set_model().extras["xml_c14n_sha256"] == _xsd_set_model(reformatted).extras["xml_c14n_sha256"]


def test_a_documentation_edit_moves_the_format_hash_but_not_the_version() -> None:
    documented = SCHEMA.replace(
        '<xs:complexType name="Order">',
        '<xs:complexType name="Order"><xs:annotation><xs:documentation>An order.</xs:documentation></xs:annotation>',
    )
    plain, edited = fingerprint(_xsd_model(SCHEMA)), fingerprint(_xsd_model(documented))
    assert plain.format_hash != edited.format_hash
    assert plain.fingerprint == edited.fingerprint


def test_the_hash_and_the_graph_stay_out_of_the_version_fingerprint() -> None:
    model = _xsd_set_model()
    stripped = model.model_copy(
        update={"extras": {k: v for k, v in model.extras.items() if not k.startswith("xml_")}}
    )
    assert fingerprint(model).fingerprint == fingerprint(stripped).fingerprint


def test_the_hashers_expose_it_as_the_format_hash() -> None:
    assert get_fingerprint_hasher("wsdl") is WsdlCanonicalXmlHasher
    assert get_fingerprint_hasher("xsd") is XsdCanonicalXmlHasher
    model = _xsd_model(SCHEMA)
    result = fingerprint(model)
    assert result.format_hash == model.extras["xml_c14n_sha256"]
    assert result.format_algorithm == C14N_ALGORITHM


def test_a_root_alone_or_in_a_set_hashes_the_same() -> None:
    alone = _xsd_model(SCHEMA).extras["xml_c14n_sha256"]
    in_a_set = _XSD.normalize(
        _XSD.parse_fileset(IntakeFileset.from_members({"schemas/order.xsd": SCHEMA}, root="schemas/order.xsd")),
        include_raw=False,
    ).extras["xml_c14n_sha256"]
    assert alone == in_a_set


def test_a_wsdl_import_records_the_hash() -> None:
    wsdl = (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" xmlns:tns="urn:o" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:o" name="S">'
        '<wsdl:types><xs:schema targetNamespace="urn:o"><xs:complexType name="Ping"/></xs:schema></wsdl:types>'
        '<wsdl:portType name="P"/></wsdl:definitions>'
    )
    model = _WSDL.normalize(_WSDL.parse(wsdl), include_raw=False)
    assert len(model.extras["xml_c14n_sha256"]) == 64
    assert fingerprint(model).format_hash == model.extras["xml_c14n_sha256"]
