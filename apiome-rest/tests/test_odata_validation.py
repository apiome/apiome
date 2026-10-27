"""Tests for OData lint/validate — MFI-11.4 (#3779).

Covers the OASIS CSDL XML schema check (:mod:`app.odata_csdl_xsd`), reference and key
resolution for v4 (CSDL JSON) and v2/v3 (parsed model) (:mod:`app.odata_resolution`), the
import wiring (:mod:`app.odata_validation`), the normalizer extras and the ``odata`` lint rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.lint_engine import lint_canonical_model
from app.odata_csdl_json import csdl_xml_to_json
from app.odata_csdl_xsd import validate_csdl_xml
from app.odata_import_source import ODataImportSource
from app.odata_parser import parse_odata
from app.odata_resolution import (
    ISSUE_KEY,
    ISSUE_REFERENCE,
    MAX_REPORTED_ISSUES,
    resolve_csdl_json,
    resolve_legacy_document,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "odata_csdl"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_V4_CORPUS = sorted((_EXAMPLES / "odata").glob("*.edmx")) + sorted((_EXAMPLES / "odata").glob("*.json"))
_LEGACY_CORPUS = sorted((_EXAMPLES / "odata-v2").glob("*.xml"))

_EDMX = (
    '<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.01">'
    "{references}"
    '<edmx:DataServices><Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="Shop"{alias}>'
    "{body}"
    '<EntityContainer Name="Svc">{container}</EntityContainer>'
    "</Schema></edmx:DataServices></edmx:Edmx>"
)

_PRODUCT = (
    '<EntityType Name="Product"><Key><PropertyRef Name="ID"/></Key>'
    '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
    '<Property Name="Name" Type="Edm.String"/></EntityType>'
)

_PRODUCTS = '<EntitySet Name="Products" EntityType="Shop.Product"/>'


def _edmx(body: str = _PRODUCT, container: str = _PRODUCTS, *, alias: str = "", references: str = "") -> str:
    """A small v4 EDMX: one schema ``Shop`` (optionally aliased), container ``Svc``."""
    alias_attr = f' Alias="{alias}"' if alias else ""
    return _EDMX.format(body=body, container=container, alias=alias_attr, references=references)


def _issues(text: str) -> List[Dict[str, str]]:
    """Resolve a v4 EDMX through its CSDL JSON form."""
    csdl = csdl_xml_to_json(text)
    assert csdl is not None
    return [issue.as_dict() for issue in resolve_csdl_json(csdl)]


def _messages(issues: List[Dict[str, str]], kind: str) -> List[str]:
    return [issue["message"] for issue in issues if issue["kind"] == kind]


# ===========================================================================
# OASIS CSDL XML schema (XSD)
# ===========================================================================


@pytest.mark.parametrize("path", [p for p in _V4_CORPUS if p.suffix == ".edmx"], ids=lambda p: p.name)
def test_every_v4_corpus_document_is_xsd_valid(path: Path):
    result = validate_csdl_xml(path.read_text(encoding="utf-8"))
    assert result == ([], 0)


def test_the_oasis_xml_example_is_xsd_valid():
    result = validate_csdl_xml((_FIXTURES / "oasis-products-categories.xml").read_text(encoding="utf-8"))
    assert result == ([], 0)


def test_xsd_reports_what_the_json_form_cannot_see():
    body = (
        '<EntityType Name="Product"><Key><PropertyRef Name="ID"/></Key>'
        '<Property Name="ID" Type="Edm.Int32" Nulable="false"/>'
        '<Property Name="Name"/><Bogus/></EntityType>'
    )
    result = validate_csdl_xml(_edmx(body))
    assert result is not None
    violations, total = result
    assert total == 3
    by_path = {v.path: v.message for v in violations}
    assert "'Nulable' attribute not allowed" in by_path["/Shop/Product/ID"]
    assert "missing required attribute 'Type'" in by_path["/Shop/Product/Name"]
    assert "Bogus" in by_path["/Shop/Product"]


@pytest.mark.parametrize("path", _LEGACY_CORPUS, ids=lambda p: p.name)
def test_v2_and_v3_are_not_xsd_validated(path: Path):
    assert validate_csdl_xml(path.read_text(encoding="utf-8")) is None


def test_xsd_validation_ignores_schema_location_hints():
    # A hostile instance cannot make validation fetch a schema: hints are never followed.
    text = _edmx().replace(
        'Version="4.01">',
        'Version="4.01" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://docs.oasis-open.org/odata/ns/edmx http://127.0.0.1:9/evil.xsd">',
        1,
    )
    result = validate_csdl_xml(text)
    assert result is not None


def test_xsd_violations_are_capped():
    properties = "".join(f'<Property Name="P{i}"/>' for i in range(60))
    body = _PRODUCT.replace("</EntityType>", f"{properties}</EntityType>")
    result = validate_csdl_xml(_edmx(body))
    assert result is not None
    violations, total = result
    assert total == 60
    assert len(violations) == 50


# ===========================================================================
# v4 reference resolution
# ===========================================================================


@pytest.mark.parametrize("path", _V4_CORPUS, ids=lambda p: p.name)
def test_every_v4_corpus_document_resolves(path: Path):
    document = ODataImportSource().parse(path.read_text(encoding="utf-8"), source_label=path.name)
    assert document.resolution_issues == ()
    assert document.resolution_issue_count == 0


def test_the_oasis_json_example_resolves():
    csdl = json.loads((_FIXTURES / "oasis-products-categories.json").read_text(encoding="utf-8"))
    assert resolve_csdl_json(csdl) == []


def test_the_oasis_xml_example_has_its_published_alias_erratum():
    # The published XML example writes `self.Supplier` but, unlike the JSON one, declares no
    # `self` alias: the resolver finds the one dangling name.
    issues = _issues((_FIXTURES / "oasis-products-categories.xml").read_text(encoding="utf-8"))
    assert [issue["path"] for issue in issues] == ["/ODataDemo/DemoService/MainSupplier/$Type"]
    assert "`self.Supplier`" in issues[0]["message"]


def test_an_undeclared_property_type_is_reported():
    body = _PRODUCT.replace('Type="Edm.String"', 'Type="Shop.Money"')
    issues = _issues(_edmx(body))
    assert issues == [
        {
            "kind": ISSUE_REFERENCE,
            "path": "/Shop/Product/Name/$Type",
            "message": "property 'Product.Name' names `Shop.Money`, which is not declared.",
        }
    ]


def test_a_type_in_an_unknown_namespace_is_reported_as_such():
    body = _PRODUCT.replace('Type="Edm.String"', 'Type="Billing.Money"')
    (message,) = _messages(_issues(_edmx(body)), ISSUE_REFERENCE)
    assert "namespace `Billing` that the document neither declares nor references" in message


def test_a_type_in_a_referenced_namespace_is_not_reported():
    references = (
        '<edmx:Reference Uri="https://example.com/billing.xml">'
        '<edmx:Include Namespace="Billing" Alias="B"/></edmx:Reference>'
    )
    body = _PRODUCT.replace('Type="Edm.String"', 'Type="B.Money"')
    assert _issues(_edmx(body, references=references)) == []
    body = _PRODUCT.replace('Type="Edm.String"', 'Type="Billing.Money"')
    assert _issues(_edmx(body, references=references)) == []


def test_alias_qualified_names_resolve():
    body = _PRODUCT + '<ComplexType Name="Money"><Property Name="Amount" Type="Edm.Decimal"/></ComplexType>'
    body = body.replace('<Property Name="Name" Type="Edm.String"/>', '<Property Name="Price" Type="self.Money"/>')
    container = '<EntitySet Name="Products" EntityType="self.Product"/>'
    assert _issues(_edmx(body, container, alias="self")) == []


def test_wrong_kinds_and_unknown_primitives_are_reported():
    body = (
        _PRODUCT.replace('Type="Edm.String"', 'Type="Shop.Product"')
        + '<EntityType Name="Event"><Key><PropertyRef Name="ID"/></Key>'
        '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
        '<Property Name="At" Type="Edm.DateTime"/></EntityType>'
    )
    messages = _messages(_issues(_edmx(body)), ISSUE_REFERENCE)
    assert (
        "property 'Product.Name' names `Shop.Product`, an EntityType; "
        "expected ComplexType or EnumType or TypeDefinition." in messages
    )
    assert "property 'Event.At' names `Edm.DateTime`, which is not an OData v4 primitive type." in messages


def test_base_types_and_entity_sets_must_resolve():
    body = (
        _PRODUCT
        + '<EntityType Name="Book" BaseType="Shop.Item"/>'
        + '<ComplexType Name="Address" BaseType="Shop.Product"/>'
    )
    container = (
        _PRODUCTS + '<EntitySet Name="Things" EntityType="Shop.Thing"/><Singleton Name="Top" Type="Shop.Address"/>'
    )
    issues = _issues(_edmx(body, container))
    paths = {issue["path"] for issue in issues if issue["kind"] == ISSUE_REFERENCE}
    assert paths == {
        "/Shop/Book/$BaseType",
        "/Shop/Address/$BaseType",
        "/Shop/Svc/Things/$Type",
        "/Shop/Svc/Top/$Type",
    }


def test_navigation_targets_partners_and_constraints_must_resolve():
    body = (
        '<EntityType Name="Category"><Key><PropertyRef Name="ID"/></Key>'
        '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
        '<NavigationProperty Name="Products" Type="Collection(Shop.Product)" Partner="Kategory"/>'
        '<NavigationProperty Name="Owner" Type="Shop.Person"/></EntityType>'
        '<EntityType Name="Product"><Key><PropertyRef Name="ID"/></Key>'
        '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
        '<Property Name="CategoryID" Type="Edm.Int32"/>'
        '<NavigationProperty Name="Category" Type="Shop.Category" Partner="Products">'
        '<ReferentialConstraint Property="CatID" ReferencedProperty="ID"/>'
        '<ReferentialConstraint Property="CategoryID" ReferencedProperty="Code"/>'
        "</NavigationProperty></EntityType>"
    )
    messages = _messages(_issues(_edmx(body)), ISSUE_REFERENCE)
    assert len(messages) == 4
    assert any("partner `Kategory`" in m for m in messages)
    assert any("`Shop.Person`, which is not declared" in m for m in messages)
    assert any("property `CatID`, which `Product` does not declare" in m for m in messages)
    assert any("property `Code`, which `Shop.Category` does not declare" in m for m in messages)


def test_bindings_and_imports_must_resolve():
    body = (
        _PRODUCT.replace("</EntityType>", '<NavigationProperty Name="Related" Type="Shop.Product"/></EntityType>')
        + '<Function Name="Top"><ReturnType Type="Shop.Product"/></Function>'
        + '<Action Name="Reset"><Parameter Name="Hard" Type="Shop.Flag"/></Action>'
    )
    container = (
        '<EntitySet Name="Products" EntityType="Shop.Product">'
        '<NavigationPropertyBinding Path="Related" Target="Products"/>'
        '<NavigationPropertyBinding Path="Missing" Target="Products"/>'
        '<NavigationPropertyBinding Path="Related" Target="Elsewhere"/>'
        "</EntitySet>"
        '<FunctionImport Name="TopProduct" Function="Shop.Top" EntitySet="Products"/>'
        '<FunctionImport Name="Bottom" Function="Shop.Bottom"/>'
        '<ActionImport Name="ResetAll" Action="Shop.Reset" EntitySet="Gone"/>'
        '<ActionImport Name="Wrong" Action="Shop.Top"/>'
    )
    messages = _messages(_issues(_edmx(body, container)), ISSUE_REFERENCE)
    assert any("names path `Missing`" in m for m in messages)
    assert any("targets `Elsewhere`" in m for m in messages)
    assert any("function import 'Bottom' names `Shop.Bottom`, which is not declared." == m for m in messages)
    assert any("entity set `Gone`" in m for m in messages)
    assert any("action import 'Wrong' names `Shop.Top`, a Function; expected Action." == m for m in messages)
    assert any("parameter 'Hard' of 'Reset' names `Shop.Flag`" in m for m in messages)
    assert len(messages) == 6


def test_qualified_binding_targets_and_type_casts_resolve():
    body = (
        _PRODUCT.replace("</EntityType>", '<NavigationProperty Name="Related" Type="Shop.Product"/></EntityType>')
        + '<EntityType Name="Book" BaseType="Shop.Product">'
        + '<NavigationProperty Name="Author" Type="Shop.Product"/></EntityType>'
    )
    container = (
        '<EntitySet Name="Products" EntityType="Shop.Product">'
        '<NavigationPropertyBinding Path="Related" Target="Shop.Svc/Products"/>'
        '<NavigationPropertyBinding Path="Shop.Book/Author" Target="Products"/>'
        "</EntitySet>"
    )
    assert _issues(_edmx(body, container)) == []


def test_type_definitions_and_terms_must_resolve():
    body = (
        _PRODUCT
        + '<TypeDefinition Name="Weight" UnderlyingType="Edm.Weight"/>'
        + '<Term Name="Tag" Type="Shop.Label"/>'
    )
    paths = {issue["path"] for issue in _issues(_edmx(body))}
    assert paths == {"/Shop/Weight/$UnderlyingType", "/Shop/Tag/$Type"}


# ===========================================================================
# v4 key resolution
# ===========================================================================


def test_a_non_abstract_entity_type_needs_a_key():
    body = _PRODUCT + '<EntityType Name="Log"><Property Name="Text" Type="Edm.String"/></EntityType>'
    body += '<EntityType Name="Base" Abstract="true"><Property Name="Text" Type="Edm.String"/></EntityType>'
    issues = _issues(_edmx(body))
    assert issues == [
        {
            "kind": ISSUE_KEY,
            "path": "/Shop/Log",
            "message": "entity type 'Log' declares no key and inherits none; a non-abstract entity type must have one.",
        }
    ]


def test_a_derived_type_inherits_its_key_and_must_not_redeclare_it():
    body = (
        _PRODUCT
        + '<EntityType Name="Book" BaseType="Shop.Product"><Property Name="Isbn" Type="Edm.String"/></EntityType>'
        + '<EntityType Name="Ebook" BaseType="Shop.Book"><Key><PropertyRef Name="ID"/></Key></EntityType>'
    )
    issues = _issues(_edmx(body))
    assert [(i["kind"], i["path"]) for i in issues] == [(ISSUE_KEY, "/Shop/Ebook/$Key")]
    assert "must not redeclare it" in issues[0]["message"]


def test_an_entity_with_an_external_base_type_is_not_judged():
    references = '<edmx:Reference Uri="base.xml"><edmx:Include Namespace="Core"/></edmx:Reference>'
    body = (
        _PRODUCT + '<EntityType Name="Book" BaseType="Core.Item"><Property Name="Isbn" Type="Edm.String"/></EntityType>'
    )
    assert _issues(_edmx(body, references=references)) == []


@pytest.mark.parametrize(
    ("key_property", "fragment"),
    [
        ('<Property Name="ID" Type="Edm.Int32"/>', "is nullable"),
        ('<Property Name="ID" Type="Collection(Edm.Int32)" Nullable="false"/>', "is a collection"),
        ('<Property Name="ID" Type="Edm.Double" Nullable="false"/>', "`Edm.Double`, which cannot be part of a key"),
        ('<Property Name="ID" Type="Shop.Money" Nullable="false"/>', "has structured type `Shop.Money`"),
        ('<Property Name="Code" Type="Edm.Int32" Nullable="false"/>', "names `ID`, which is not a property"),
        ('<NavigationProperty Name="ID" Type="Shop.Product" Nullable="false"/>', "names navigation property `ID`"),
    ],
)
def test_key_property_defects(key_property: str, fragment: str):
    body = (
        '<ComplexType Name="Money"><Property Name="Amount" Type="Edm.Decimal"/></ComplexType>'
        f'<EntityType Name="Product"><Key><PropertyRef Name="ID"/></Key>{key_property}</EntityType>'
    )
    issues = _issues(_edmx(body))
    keys = [issue for issue in issues if issue["kind"] == ISSUE_KEY]
    assert len(keys) == 1, issues
    assert keys[0]["path"] == "/Shop/Product/$Key/0"
    assert fragment in keys[0]["message"]


def test_key_paths_through_complex_types_and_enum_keys_resolve():
    body = (
        '<EnumType Name="Region"><Member Name="EU"/></EnumType>'
        '<ComplexType Name="Ident"><Property Name="Code" Type="Edm.String" Nullable="false"/></ComplexType>'
        '<EntityType Name="Product"><Key>'
        '<PropertyRef Name="Ident/Code" Alias="Code"/><PropertyRef Name="Region"/></Key>'
        '<Property Name="Ident" Type="Shop.Ident" Nullable="false"/>'
        '<Property Name="Region" Type="Shop.Region" Nullable="false"/></EntityType>'
    )
    assert _issues(_edmx(body)) == []


# ===========================================================================
# v2 / v3 resolution
# ===========================================================================


_V2 = (
    '<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" '
    'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
    '<edmx:DataServices m:DataServiceVersion="2.0">'
    '<Schema Namespace="Sales" Alias="Self" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">'
    "{body}"
    '<EntityContainer Name="Svc" m:IsDefaultEntityContainer="true">{container}</EntityContainer>'
    "</Schema></edmx:DataServices></edmx:Edmx>"
)

_V2_TYPES = (
    '<EntityType Name="Customer"><Key><PropertyRef Name="ID"/></Key>'
    '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
    '<NavigationProperty Name="Orders" Relationship="Sales.CustomerOrders" FromRole="Customer" ToRole="Order"/>'
    "</EntityType>"
    '<EntityType Name="Order"><Key><PropertyRef Name="ID"/></Key>'
    '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
    '<Property Name="CustomerID" Type="Edm.Int32"/>'
    '<Property Name="Placed" Type="Edm.DateTime"/></EntityType>'
    '<Association Name="CustomerOrders">'
    '<End Role="Customer" Type="Self.Customer" Multiplicity="1"/>'
    '<End Role="Order" Type="Sales.Order" Multiplicity="*"/>'
    '<ReferentialConstraint><Principal Role="Customer"><PropertyRef Name="ID"/></Principal>'
    '<Dependent Role="Order"><PropertyRef Name="CustomerID"/></Dependent></ReferentialConstraint>'
    "</Association>"
)

_V2_CONTAINER = (
    '<EntitySet Name="Customers" EntityType="Self.Customer"/>'
    '<EntitySet Name="Orders" EntityType="Sales.Order"/>'
    '<AssociationSet Name="CustomerOrdersSet" Association="Self.CustomerOrders">'
    '<End Role="Customer" EntitySet="Customers"/><End Role="Order" EntitySet="Orders"/>'
    "</AssociationSet>"
    '<FunctionImport Name="Recent" ReturnType="Collection(Sales.Order)" EntitySet="Orders" m:HttpMethod="GET">'
    '<Parameter Name="Since" Type="Edm.DateTime" Mode="In"/></FunctionImport>'
)


def _legacy_issues(body: str = _V2_TYPES, container: str = _V2_CONTAINER) -> List[Dict[str, str]]:
    document = parse_odata(_V2.format(body=body, container=container))
    return [issue.as_dict() for issue in resolve_legacy_document(document)]


@pytest.mark.parametrize("path", _LEGACY_CORPUS, ids=lambda p: p.name)
def test_every_legacy_corpus_document_resolves(path: Path):
    document = ODataImportSource().parse(path.read_text(encoding="utf-8"), source_label=path.name)
    assert document.resolution_issues == ()


def test_a_clean_v2_document_with_an_alias_resolves():
    assert _legacy_issues() == []


def test_legacy_entity_sets_associations_and_imports_must_resolve():
    container = (
        _V2_CONTAINER.replace('EntityType="Sales.Order"', 'EntityType="Sales.Ordr"')
        .replace('<End Role="Order" EntitySet="Orders"/>', '<End Role="Item" EntitySet="Items"/>')
        .replace('EntitySet="Orders" m:HttpMethod', 'EntitySet="Gone" m:HttpMethod')
        .replace('Type="Edm.DateTime" Mode', 'Type="Edm.Instant" Mode')
    )
    messages = _messages(_legacy_issues(container=container), ISSUE_REFERENCE)
    assert "entity set 'Orders' names `Sales.Ordr`, which is not declared." in messages
    assert any("names role `Item`, which association" in m for m in messages)
    assert any("names entity set `Items`" in m for m in messages)
    assert any("function import 'Recent' names entity set `Gone`" in m for m in messages)
    assert (
        "parameter 'Since' of function import 'Recent' names `Edm.Instant`, which is not an OData v2 primitive type."
        in messages
    )


def test_legacy_associations_must_resolve():
    body = _V2_TYPES.replace('<PropertyRef Name="CustomerID"/>', '<PropertyRef Name="CustID"/>')
    body = body.replace('<End Role="Order" Type="Sales.Order"', '<End Role="Order" Type="Sales.Order"', 1)
    messages = _messages(_legacy_issues(body), ISSUE_REFERENCE)
    assert messages == [
        "referential constraint of association 'CustomerOrders' names property `CustID`, "
        "which `Order` does not declare."
    ]


def test_legacy_keys():
    body = (
        _V2_TYPES.replace(
            '<Property Name="ID" Type="Edm.Int32" Nullable="false"/><Property Name="CustomerID"',
            '<Property Name="ID" Type="Edm.Int32" Nullable="true"/><Property Name="CustomerID"',
        )
        + '<EntityType Name="Note"><Property Name="Text" Type="Edm.String"/></EntityType>'
    )
    keys = [issue for issue in _legacy_issues(body) if issue["kind"] == ISSUE_KEY]
    assert [(k["path"], "nullable" in k["message"] or "no key" in k["message"]) for k in keys] == [
        ("/Sales/Order/$Key/0", True),
        ("/Sales/Note", True),
    ]


def test_v3_derived_types_inherit_their_key():
    path = _EXAMPLES / "odata-v2" / "03-composition-v3-inheritance.xml"
    document = parse_odata(path.read_text(encoding="utf-8"))
    vehicle = next(e for s in document.schemas for e in s.entity_types if e.name == "Vehicle")
    truck = next(e for s in document.schemas for e in s.entity_types if e.name == "Truck")
    assert vehicle.abstract is True
    assert truck.base_type == "Fleet.Vehicle"
    assert resolve_legacy_document(document) == []


def test_v4_parsing_does_not_record_legacy_only_fields():
    document = parse_odata(_edmx())
    assert all(schema.alias is None for schema in document.schemas)
    assert all(e.base_type is None and not e.abstract for s in document.schemas for e in s.entity_types)


# ===========================================================================
# Import wiring, normalizer extras, lint rules
# ===========================================================================


def _lint(text: str) -> Dict[str, List[Dict[str, Any]]]:
    adapter = ODataImportSource()
    model = adapter.normalize(adapter.parse(text, source_label="t.edmx"))
    findings: Dict[str, List[Dict[str, Any]]] = {}
    for finding in lint_canonical_model(model).findings:
        payload = finding.as_dict()
        findings.setdefault(payload["rule"], []).append(payload)
    return findings


def test_a_clean_document_adds_no_validation_extras():
    adapter = ODataImportSource()
    model = adapter.normalize(adapter.parse(_edmx()))
    assert not {"odata_xsd_violations", "odata_resolution_issues"} & set(model.extras)
    findings = _lint(_edmx())
    assert not {"odata.csdl-xsd", "odata.unresolved-reference", "odata.entity-key"} & set(findings)


def test_a_broken_document_still_imports_and_lints_each_defect():
    body = (
        '<EntityType Name="Product"><Key><PropertyRef Name="ID"/></Key>'
        '<Property Name="ID" Type="Edm.Int32" Nulable="false"/>'
        '<Property Name="Price" Type="Shop.Money"/></EntityType>'
    )
    text = _edmx(body)
    adapter = ODataImportSource()
    model = adapter.normalize(adapter.parse(text))
    assert model.extras["odata_xsd_violation_count"] == 1
    assert model.extras["odata_resolution_issue_count"] == 2

    findings = _lint(text)
    (xsd,) = findings["odata.csdl-xsd"]
    assert xsd["severity"] == "warning"
    assert xsd["path"] == "xml:/Shop/Product/ID"
    (reference,) = findings["odata.unresolved-reference"]
    assert reference["severity"] == "error"
    assert reference["path"] == "csdl:/Shop/Product/Price/$Type"
    (key,) = findings["odata.entity-key"]
    assert key["severity"] == "error"
    assert key["path"] == "csdl:/Shop/Product/$Key/0"


def test_csdl_json_uploads_are_resolved_but_not_xsd_validated():
    csdl = {
        "$Version": "4.01",
        "$EntityContainer": "Shop.Svc",
        "Shop": {
            "Product": {"$Kind": "EntityType", "$Key": ["ID"], "ID": {"$Type": "Edm.Int32"}},
            "Svc": {"$Kind": "EntityContainer", "Products": {"$Collection": True, "$Type": "Shop.Thing"}},
        },
    }
    document = ODataImportSource().parse(json.dumps(csdl))
    assert document.xsd_violation_count == 0
    assert {issue["kind"] for issue in document.resolution_issues} == {ISSUE_REFERENCE}


def test_legacy_documents_are_resolved_on_import():
    text = _V2.format(
        body=_V2_TYPES, container=_V2_CONTAINER.replace('EntityType="Sales.Order"', 'EntityType="Sales.Ordr"')
    )
    findings = _lint(text)
    assert [f["path"] for f in findings["odata.unresolved-reference"]] == ["csdl:/Sales/Svc/Orders/$Type"]


def test_resolution_issues_are_capped_and_the_rest_counted():
    body = _PRODUCT + "".join(
        f'<ComplexType Name="C{i}"><Property Name="P" Type="Shop.Missing{i}"/></ComplexType>'
        for i in range(MAX_REPORTED_ISSUES + 5)
    )
    document = ODataImportSource().parse(_edmx(body))
    assert len(document.resolution_issues) == MAX_REPORTED_ISSUES
    assert document.resolution_issue_count == MAX_REPORTED_ISSUES + 5
    findings = _lint(_edmx(body))
    messages = [finding["message"] for finding in findings["odata.unresolved-reference"]]
    assert len(messages) == MAX_REPORTED_ISSUES + 1
    assert "5 more unresolved reference or entity-key issue(s) not listed." in messages


def test_a_legacy_reference_is_outside_the_document_until_merged():
    folder = _EXAMPLES / "odata-v2" / "07-referenced-set"
    service = (folder / "service.xml").read_text(encoding="utf-8")
    # Alone, the referenced namespace (reached through its alias) is not judged...
    assert resolve_legacy_document(parse_odata(service)) == []
    # ...and merged, the alias resolves to the merged schema.
    members = {"service.xml": service, "shared-types.xml": (folder / "shared-types.xml").read_text(encoding="utf-8")}
    merged = parse_odata(service, members=members)
    assert any(reference.resolved for reference in merged.references)
    assert resolve_legacy_document(merged) == []
    broken = parse_odata(service.replace("Shared.Address", "Shared.Adress"), members=members)
    (issue,) = resolve_legacy_document(broken)
    assert issue.message.endswith("names `Shared.Adress`, which is not declared.")
