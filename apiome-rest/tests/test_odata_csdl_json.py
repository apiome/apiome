"""Tests for OData CSDL JSON and OASIS schema validation — MFI-11.1 (#3776).

The conversion is checked against the OASIS specifications' own example (``tests/fixtures/
odata_csdl/oasis-products-categories.{xml,json}``, section 16.1 of CSDL XML and CSDL JSON
4.01): converting the published XML must give the published JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from app.import_source import DetectionInput, ImportSourceError
from app.lint_engine import lint_canonical_model
from app.odata_csdl_json import csdl_xml_to_json, is_csdl_json, parse_csdl_json, with_csdl_validation
from app.odata_csdl_schema import MAX_REPORTED_VIOLATIONS, validate_csdl_json
from app.odata_import_source import ODataImportSource
from app.odata_parser import ODataParseError, parse_odata

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "odata_csdl"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_V4_CORPUS = sorted((_EXAMPLES / "odata").glob("*.edmx"))
_LEGACY_CORPUS = sorted((_EXAMPLES / "odata-v2").glob("*.xml"))

_EDMX = (
    '<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.01">'
    '<edmx:DataServices><Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="Shop">'
    "{body}"
    '<EntityContainer Name="Svc">{container}</EntityContainer>'
    "</Schema></edmx:DataServices></edmx:Edmx>"
)


def _convert(body: str = "", container: str = "") -> Dict[str, Any]:
    """Convert a small v4 EDMX (one schema ``Shop``, container ``Svc``) to CSDL JSON."""
    converted = csdl_xml_to_json(_EDMX.format(body=body, container=container))
    assert converted is not None
    return converted


def _oasis_json() -> Dict[str, Any]:
    """The OASIS JSON example, with the differences the two published examples have from each
    other removed (alias ``self``, ``.json`` vocabulary URLs, the schema-level default-namespace
    annotation, ``Product/ID`` without its type)."""
    text = (_FIXTURES / "oasis-products-categories.json").read_text(encoding="utf-8")
    document = json.loads(text.replace("self.", "ODataDemo.").replace(".V1.json", ".V1.xml"))
    document["ODataDemo"].pop("$Alias")
    document["ODataDemo"].pop("@Core.DefaultNamespace")
    document["ODataDemo"]["Product"]["ID"]["$Type"] = "Edm.Int32"
    return document


# ===========================================================================
# XML → canonical CSDL JSON
# ===========================================================================


def test_the_oasis_xml_example_converts_to_the_oasis_json_example():
    converted = csdl_xml_to_json((_FIXTURES / "oasis-products-categories.xml").read_text(encoding="utf-8"))
    # The XML example names `self.Supplier` on MainSupplier as written; the rest is identical.
    converted["ODataDemo"]["DemoService"]["MainSupplier"]["$Type"] = "ODataDemo.Supplier"
    assert converted == _oasis_json()


def test_both_oasis_examples_validate():
    for name in ("oasis-products-categories.json",):
        violations, total = validate_csdl_json(json.loads((_FIXTURES / name).read_text(encoding="utf-8")))
        assert (violations, total) == ((), 0)
    converted = csdl_xml_to_json((_FIXTURES / "oasis-products-categories.xml").read_text(encoding="utf-8"))
    assert validate_csdl_json(converted) == ((), 0)


@pytest.mark.parametrize("path", _V4_CORPUS, ids=[p.name for p in _V4_CORPUS])
def test_every_v4_corpus_document_converts_to_valid_csdl_json(path: Path):
    converted = csdl_xml_to_json(path.read_text(encoding="utf-8"))
    assert converted is not None
    assert validate_csdl_json(converted) == ((), 0)


@pytest.mark.parametrize("path", _LEGACY_CORPUS, ids=[p.name for p in _LEGACY_CORPUS])
def test_v2_and_v3_have_no_csdl_json_form(path: Path):
    assert csdl_xml_to_json(path.read_text(encoding="utf-8")) is None


def test_properties_are_written_the_json_way():
    converted = _convert(
        '<EntityType Name="Item"><Key><PropertyRef Name="ID"/></Key>'
        '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
        '<Property Name="Name" Type="Edm.String" MaxLength="max" Unicode="false"/>'
        '<Property Name="Price" Type="Edm.Decimal" Precision="10" Scale="variable"/>'
        '<Property Name="Ratio" Type="Edm.Decimal" Scale="floating" DefaultValue="1.5"/>'
        '<Property Name="Tags" Type="Collection(Edm.String)"/>'
        '<Property Name="Active" Type="Edm.Boolean" DefaultValue="true"/>'
        '<Property Name="Count" Type="Edm.Int32" DefaultValue="3"/>'
        "</EntityType>",
        '<EntitySet Name="Items" EntityType="Shop.Item"/>',
    )
    item = converted["Shop"]["Item"]
    assert item["$Key"] == ["ID"]
    assert item["ID"] == {"$Type": "Edm.Int32"}  # Nullable="false" is JSON's default
    assert item["Name"] == {"$Nullable": True, "$Unicode": False}  # Edm.String and `max` omitted
    assert item["Price"] == {"$Type": "Edm.Decimal", "$Nullable": True, "$Precision": 10}
    assert item["Ratio"] == {"$Type": "Edm.Decimal", "$Nullable": True, "$Scale": "floating", "$DefaultValue": "1.5"}
    assert item["Tags"] == {"$Collection": True}  # item nullability only when explicit
    assert item["Active"]["$DefaultValue"] is True
    assert item["Count"]["$DefaultValue"] == 3


def test_navigation_keys_and_enums():
    converted = _convert(
        '<EntityType Name="Order" OpenType="true"><Key><PropertyRef Name="Info/ID" Alias="InfoID"/></Key>'
        '<Property Name="Info" Type="Shop.Info" Nullable="false"/>'
        '<NavigationProperty Name="Lines" Type="Collection(Shop.Line)" Partner="Order"'
        ' ContainsTarget="true"/>'
        '<NavigationProperty Name="Customer" Type="Shop.Customer" Nullable="false">'
        '<ReferentialConstraint Property="CustomerID" ReferencedProperty="ID"/><OnDelete Action="Cascade"/>'
        "</NavigationProperty></EntityType>"
        '<EnumType Name="Color" IsFlags="true" UnderlyingType="Edm.Byte">'
        '<Member Name="Red"/><Member Name="Blue" Value="4">'
        '<Annotation Term="Core.Description" String="Sky"/></Member></EnumType>',
    )
    order = converted["Shop"]["Order"]
    assert order["$OpenType"] is True
    assert order["$Key"] == [{"InfoID": "Info/ID"}]
    assert order["Lines"] == {
        "$Kind": "NavigationProperty",
        "$Collection": True,
        "$Type": "Shop.Line",
        "$Partner": "Order",
        "$ContainsTarget": True,
    }
    assert order["Customer"] == {
        "$Kind": "NavigationProperty",
        "$Type": "Shop.Customer",
        "$ReferentialConstraint": {"CustomerID": "ID"},
        "$OnDelete": "Cascade",
    }
    color = converted["Shop"]["Color"]
    assert color == {
        "$Kind": "EnumType",
        "$UnderlyingType": "Edm.Byte",
        "$IsFlags": True,
        "Red": 0,
        "Blue": 4,
        "Blue@Core.Description": "Sky",
    }


def test_operations_terms_and_the_container():
    converted = _convert(
        '<TypeDefinition Name="Money" UnderlyingType="Edm.Decimal" Precision="12"/>'
        '<Term Name="Audited" Type="Edm.Boolean" AppliesTo="EntityType Property"/>'
        '<Action Name="Restock" IsBound="true"><Parameter Name="it" Type="Shop.Item" Nullable="false"/>'
        '<Parameter Name="count" Type="Edm.Int32"/></Action>'
        '<Function Name="Top" IsComposable="true"><ReturnType Type="Collection(Shop.Item)"/></Function>',
        '<EntitySet Name="Items" EntityType="Shop.Item" IncludeInServiceDocument="false">'
        '<NavigationPropertyBinding Path="Category" Target="Categories"/></EntitySet>'
        '<Singleton Name="Boss" Type="Shop.Person"/>'
        '<ActionImport Name="Reset" Action="Shop.Reset"/>'
        '<FunctionImport Name="TopItems" Function="Shop.Top" EntitySet="Items" IncludeInServiceDocument="true"/>',
    )
    shop = converted["Shop"]
    assert converted["$EntityContainer"] == "Shop.Svc"
    assert shop["Money"] == {"$Kind": "TypeDefinition", "$Precision": 12, "$UnderlyingType": "Edm.Decimal"}
    assert shop["Audited"] == {
        "$Kind": "Term",
        "$Type": "Edm.Boolean",
        "$Nullable": True,
        "$AppliesTo": ["EntityType", "Property"],
    }
    assert shop["Restock"] == [
        {
            "$Kind": "Action",
            "$IsBound": True,
            "$Parameter": [
                {"$Name": "it", "$Type": "Shop.Item"},
                {"$Name": "count", "$Type": "Edm.Int32", "$Nullable": True},
            ],
        }
    ]
    assert shop["Top"] == [
        {"$Kind": "Function", "$IsComposable": True, "$ReturnType": {"$Collection": True, "$Type": "Shop.Item"}}
    ]
    svc = shop["Svc"]
    assert svc["Items"] == {
        "$Collection": True,
        "$Type": "Shop.Item",
        "$IncludeInServiceDocument": False,
        "$NavigationPropertyBinding": {"Category": "Categories"},
    }
    assert svc["Boss"] == {"$Type": "Shop.Person"}
    assert svc["Reset"] == {"$Action": "Shop.Reset"}
    assert svc["TopItems"] == {"$Function": "Shop.Top", "$EntitySet": "Items", "$IncludeInServiceDocument": True}
    assert validate_csdl_json(converted)[1] == 0


def test_annotation_expressions():
    converted = _convert(
        '<Annotations Target="Shop.Item">'
        '<Annotation Term="Core.Computed"/>'
        '<Annotation Term="Core.Description" Qualifier="Short" String="An item"/>'
        '<Annotation Term="Core.Rank" Int="3"/>'
        '<Annotation Term="UI.Color" EnumMember="UI.Color/Red UI.Color/Blue"/>'
        '<Annotation Term="Measures.ISOCurrency" Path="Currency"/>'
        '<Annotation Term="UI.Fields"><Collection>'
        "<PropertyPath>Name</PropertyPath><PropertyPath>Price</PropertyPath>"
        "</Collection></Annotation>"
        '<Annotation Term="UI.Header"><Record Type="UI.HeaderType">'
        '<PropertyValue Property="Title" String="T"/></Record></Annotation>'
        '<Annotation Term="UI.Label"><Apply Function="odata.concat">'
        "<String>A</String><Path>Name</Path></Apply></Annotation>"
        '<Annotation Term="UI.Hidden"><Not><Bool>true</Bool></Not></Annotation>'
        '<Annotation Term="UI.Nothing"><Null/></Annotation>'
        "</Annotations>"
    )
    block = converted["Shop"]["$Annotations"]["Shop.Item"]
    assert block == {
        "@Core.Computed": True,
        "@Core.Description#Short": "An item",
        "@Core.Rank": 3,
        "@UI.Color": "Red,Blue",
        "@Measures.ISOCurrency": {"$Path": "Currency"},
        "@UI.Fields": ["Name", "Price"],
        "@UI.Header": {"@type": "UI.HeaderType", "Title": "T"},
        "@UI.Label": {"$Apply": ["A", {"$Path": "Name"}], "$Function": "odata.concat"},
        "@UI.Hidden": {"$Not": True},
        "@UI.Nothing": None,
    }


# ===========================================================================
# Validation
# ===========================================================================


@pytest.mark.parametrize(
    "document, path, fragment",
    [
        ({"$Version": "3.0"}, "/$Version", "'3.0' is not one of"),
        (
            {"$Version": "4.01", "A": {"T": {"$Kind": "EntityType", "$Key": "ID"}}},
            "/A/T/$Key",
            "is not of type 'array'",
        ),
        ({"$Version": "4.01", "A": {"T": {"$Kind": "Bogus"}}}, "/A/T/$Kind", "is not a CSDL member kind"),
        (
            {"$Version": "4.01", "A": {"T": {"$Kind": "ComplexType", "N": {"$Nullable": "yes"}}}},
            "/A/T/N/$Nullable",
            "is not of type 'boolean'",
        ),
        (
            {"$Version": "4.01", "A": {"C": {"$Kind": "EntityContainer", "S": {"$Collection": True}}}},
            "/A/C/S",
            "'$Type' is a required property",
        ),
        ({"$Version": "4.01", "A": {"F": [{"$Kind": "Function"}]}}, "/A/F/0", "'$ReturnType' is a required property"),
    ],
)
def test_violations_name_the_specific_problem(document: Dict[str, Any], path: str, fragment: str):
    violations, total = validate_csdl_json(document)
    assert total == 1
    assert violations[0].path == path
    assert fragment in violations[0].message


def test_violations_are_capped():
    document = {"$Version": "4.01", "A": {f"T{i}": {"$Kind": "Bogus"} for i in range(MAX_REPORTED_VIOLATIONS + 5)}}
    violations, total = validate_csdl_json(document)
    assert len(violations) == MAX_REPORTED_VIOLATIONS
    assert total == MAX_REPORTED_VIOLATIONS + 5


# ===========================================================================
# CSDL JSON input
# ===========================================================================


def test_is_csdl_json():
    assert is_csdl_json((_FIXTURES / "oasis-products-categories.json").read_text(encoding="utf-8"))
    assert not is_csdl_json('{"openapi": "3.1.0"}')
    assert not is_csdl_json('{"$Version": "3.0", "A": {}}')
    assert not is_csdl_json('{"$Version": "4.01"}')
    assert not is_csdl_json("{broken")


def test_csdl_json_reads_into_the_same_shape_as_xml():
    document = parse_csdl_json((_FIXTURES / "oasis-products-categories.json").read_text(encoding="utf-8"))
    (schema,) = document.schemas
    assert schema.namespace == "ODataDemo"
    product = next(t for t in schema.entity_types if t.name == "Product")
    assert product.key_properties == ("ID",)
    assert [n.name for n in product.navigation_properties] == ["Category", "Supplier"]
    assert schema.entity_container is not None
    assert [s.name for s in schema.entity_container.entity_sets] == ["Products", "Categories", "Suppliers", "Countries"]
    assert document.version == "4.01" or document.version.startswith("4")


@pytest.mark.parametrize("path", _V4_CORPUS, ids=[p.name for p in _V4_CORPUS])
def test_xml_and_its_csdl_json_give_the_same_canonical_model(path: Path):
    source = ODataImportSource()
    xml = path.read_text(encoding="utf-8")
    from_xml = source.normalize(source.parse(xml), include_raw=False)
    from_json = source.normalize(source.parse(json.dumps(csdl_xml_to_json(xml))), include_raw=False)
    assert from_xml.services == from_json.services
    assert from_xml.types == from_json.types
    assert from_xml.identity == from_json.identity


def test_csdl_json_without_a_container_is_refused():
    with pytest.raises(ODataParseError) as exc:
        parse_csdl_json('{"$Version": "4.01", "A": {"T": {"$Kind": "ComplexType"}}}')
    assert exc.value.code == "INPUT_SEMANTIC_INVALID"


def test_detects_csdl_json():
    text = (_FIXTURES / "oasis-products-categories.json").read_text(encoding="utf-8")
    result = ODataImportSource().detect(DetectionInput(text=text, filename="metadata.json"))
    assert (result.format, result.confidence) == ("odata", 0.97)


# ===========================================================================
# Import: violations are recorded, not refused
# ===========================================================================


_INVALID_JSON = json.dumps(
    {
        "$Version": "4.01",
        "$EntityContainer": "Shop.Svc",
        "Shop": {
            "Item": {"$Kind": "EntityType", "$Key": ["ID"], "ID": {"$Nullable": "yes"}},
            "Svc": {"$Kind": "EntityContainer", "Items": {"$Collection": True, "$Type": "Shop.Item"}},
        },
    }
)


def test_an_invalid_document_still_imports_with_its_violations():
    source = ODataImportSource()
    api = source.normalize(source.parse(_INVALID_JSON))
    assert api.extras["odata_csdl_valid"] is False
    assert api.extras["odata_csdl_violations"] == [
        {"path": "/Shop/Item/ID/$Nullable", "message": "'yes' is not of type 'boolean'"}
    ]
    assert api.extras["odata_csdl_violation_count"] == 1
    assert api.raw["csdl_json"] == json.loads(_INVALID_JSON)


def test_the_lint_rule_reports_each_violation():
    source = ODataImportSource()
    findings = [
        f
        for f in lint_canonical_model(source.normalize(source.parse(_INVALID_JSON))).findings
        if f.rule == "odata.csdl-schema"
    ]
    assert [(f.severity, f.path) for f in findings] == [("warning", "csdl:/Shop/Item/ID/$Nullable")]


def test_a_valid_v4_document_records_its_canonical_form():
    source = ODataImportSource()
    xml = (_V4_CORPUS[0]).read_text(encoding="utf-8")
    api = source.normalize(source.parse(xml))
    assert api.extras["odata_csdl_valid"] is True
    assert "odata_csdl_violations" not in api.extras
    assert api.raw["csdl_json"] == csdl_xml_to_json(xml)
    assert not [f for f in lint_canonical_model(api).findings if f.rule == "odata.csdl-schema"]


def test_a_legacy_document_is_not_validated():
    source = ODataImportSource()
    api = source.normalize(source.parse(_LEGACY_CORPUS[0].read_text(encoding="utf-8")))
    assert "odata_csdl_valid" not in api.extras
    assert "csdl_json" not in (api.raw or {})


def test_with_csdl_validation_leaves_v2_documents_alone():
    document = parse_odata(_LEGACY_CORPUS[0].read_text(encoding="utf-8"))
    assert with_csdl_validation(document) is document


def test_malformed_csdl_json_is_refused():
    with pytest.raises(ImportSourceError):
        ODataImportSource().parse('{"$Version": "4.01", "A": {}')
