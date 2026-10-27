"""Tests for the OData breaking-change classifier — MFI-11.5 (#3780).

Each case imports two small OData documents, diffs the canonical models and checks the grade the
``odata`` classifier gives — against OData 4.01 Part 1 §5.2 *Model Versioning*.
"""

from __future__ import annotations

from typing import Dict, Tuple

import pytest

from app.breaking_change import Severity, classify, get_breaking_change_classifier
from app.diff import diff
from app.odata_breaking import ODataBreakingChangeClassifier, schema_versions
from app.odata_import_source import ODataImportSource

_V4 = (
    '<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.01"><edmx:DataServices>'
    '<Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="Shop">{schema_annotations}'
    '<EntityType Name="Product"><Key>{key}</Key>'
    '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>'
    '<Property Name="Code" Type="Edm.String" Nullable="false"/>'
    "{properties}{navigations}</EntityType>"
    '<EntityType Name="Category"><Key><PropertyRef Name="ID"/></Key>'
    '<Property Name="ID" Type="Edm.Int32" Nullable="false"/></EntityType>'
    '<EntityContainer Name="Svc"><EntitySet Name="Products" EntityType="Shop.Product"/>{sets}</EntityContainer>'
    "</Schema></edmx:DataServices></edmx:Edmx>"
)

_DEFAULTS = {
    "schema_annotations": "",
    "key": '<PropertyRef Name="ID"/>',
    "properties": "",
    "navigations": "",
    "sets": '<EntitySet Name="Categories" EntityType="Shop.Category"/>',
}


def _model(*, include_raw: bool = True, **parts: str):
    adapter = ODataImportSource()
    return adapter.normalize(adapter.parse(_V4.format(**{**_DEFAULTS, **parts})), include_raw=include_raw)


def _grades(base, head) -> Dict[str, Tuple[str, str, str]]:
    """``change key → (severity, rule_id, rationale)``."""
    model_diff = diff(base, head)
    result = classify(model_diff, base, head)
    assert result.classifier == "odata-model-versioning"
    return {c.key: (c.severity.value, c.rule_id, c.rationale) for c in result.classifications}


def test_the_classifier_is_registered_for_odata():
    assert get_breaking_change_classifier("odata") is ODataBreakingChangeClassifier


# ===========================================================================
# Properties
# ===========================================================================


def test_adding_a_nullable_property_is_safe():
    grades = _grades(_model(), _model(properties='<Property Name="Note" Type="Edm.String"/>'))
    assert grades["Shop.Product.Note"][:2] == ("safe", "odata.property-added-nullable")


def test_adding_a_required_property_is_breaking():
    grades = _grades(_model(), _model(properties='<Property Name="Stock" Type="Edm.Int32" Nullable="false"/>'))
    assert grades["Shop.Product.Stock"][:2] == ("breaking", "odata.property-added-required")


def test_adding_a_required_property_with_a_default_is_safe():
    head = _model(properties='<Property Name="Stock" Type="Edm.Int32" Nullable="false" DefaultValue="0"/>')
    grades = _grades(_model(), head)
    assert grades["Shop.Product.Stock"][:2] == ("safe", "odata.property-added-with-default")


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (
            '<Property Name="Price" Type="Edm.Decimal"/>',
            '<Property Name="Price" Type="Edm.String"/>',
            ("breaking", "odata.property-type-changed"),
        ),
        (
            '<Property Name="Price" Type="Edm.Decimal"/>',
            '<Property Name="Price" Type="Edm.Decimal" Nullable="false"/>',
            ("breaking", "odata.property-made-non-nullable"),
        ),
        (
            '<Property Name="Price" Type="Edm.Decimal" Nullable="false"/>',
            '<Property Name="Price" Type="Edm.Decimal"/>',
            ("dangerous", "odata.property-made-nullable"),
        ),
    ],
)
def test_property_modifications(before: str, after: str, expected: Tuple[str, str]):
    grades = _grades(_model(properties=before), _model(properties=after))
    assert grades["Shop.Product.Price"][:2] == expected


def test_removing_a_property_is_breaking():
    grades = _grades(_model(properties='<Property Name="Note" Type="Edm.String"/>'), _model())
    assert grades["Shop.Product.Note"][0] == "breaking"


# ===========================================================================
# Keys and navigation properties
# ===========================================================================


def test_changing_the_key_is_breaking():
    grades = _grades(_model(), _model(key='<PropertyRef Name="Code"/>'))
    assert grades["Shop.Product"][:2] == ("breaking", "odata.key-changed")


@pytest.mark.parametrize(
    ("navigation", "expected"),
    [
        ('<NavigationProperty Name="Related" Type="Collection(Shop.Product)"/>', ("safe", "odata.navigation-added")),
        ('<NavigationProperty Name="Category" Type="Shop.Category"/>', ("safe", "odata.navigation-added")),
        (
            '<NavigationProperty Name="Category" Type="Shop.Category" Nullable="false"/>',
            ("breaking", "odata.navigation-added-required"),
        ),
    ],
)
def test_adding_navigation_properties(navigation: str, expected: Tuple[str, str]):
    grades = _grades(_model(), _model(navigations=navigation))
    assert grades["Shop.Product"][:2] == expected


def test_a_single_navigation_without_csdl_json_has_unknown_nullability():
    head = _model(navigations='<NavigationProperty Name="Category" Type="Shop.Category"/>', include_raw=False)
    grades = _grades(_model(include_raw=False), head)
    assert grades["Shop.Product"][:2] == ("dangerous", "odata.navigation-added-unknown")


def test_removing_retyping_and_repartnering_navigations():
    nav = '<NavigationProperty Name="Category" Type="Shop.Category" Partner="Products"/>'
    grades = _grades(_model(navigations=nav), _model())
    assert grades["Shop.Product"][:2] == ("breaking", "odata.navigation-removed")
    retyped = nav.replace('Type="Shop.Category"', 'Type="Shop.Product"')
    assert _grades(_model(navigations=nav), _model(navigations=retyped))["Shop.Product"][:2] == (
        "breaking",
        "odata.navigation-type-changed",
    )
    repartnered = nav.replace('Partner="Products"', 'Partner="Items"')
    assert _grades(_model(navigations=nav), _model(navigations=repartnered))["Shop.Product"][:2] == (
        "dangerous",
        "odata.navigation-partner-changed",
    )


def test_one_type_change_combines_its_grades():
    head = _model(
        key='<PropertyRef Name="Code"/>',
        navigations='<NavigationProperty Name="Related" Type="Collection(Shop.Product)"/>',
    )
    severity, rule, rationale = _grades(_model(), head)["Shop.Product"]
    assert (severity, rule) == ("breaking", "odata.key-changed")
    assert "collection-valued navigation property 'Related'" in rationale


# ===========================================================================
# Entity sets and types (baseline grading kept)
# ===========================================================================


def test_entity_sets_and_types_keep_the_baseline_grades():
    grades = _grades(_model(), _model(sets=""))
    removed = {key: grade for key, grade in grades.items() if grade[1] == "removed-entity"}
    assert removed and all(grade[0] == "breaking" for grade in removed.values())
    added = _grades(_model(sets=""), _model())
    assert all(grade[0] == "safe" for grade in added.values())


# ===========================================================================
# v2 / v3: navigation nullability from the association multiplicity, annotations
# ===========================================================================

_V2 = (
    '<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" '
    'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" '
    'xmlns:sap="http://www.sap.com/Protocols/SAPData">'
    '<edmx:DataServices m:DataServiceVersion="2.0">'
    '<Schema Namespace="Sales" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">'
    '<EntityType Name="Order"{order_annotations}><Key><PropertyRef Name="ID"/></Key>'
    '<Property Name="ID" Type="Edm.Int32" Nullable="false"/>{order_nav}</EntityType>'
    '<EntityType Name="Customer"><Key><PropertyRef Name="ID"/></Key>'
    '<Property Name="ID" Type="Edm.Int32" Nullable="false"/></EntityType>'
    '<Association Name="OrderCustomer"><End Role="Order" Type="Sales.Order" Multiplicity="*"/>'
    '<End Role="Customer" Type="Sales.Customer" Multiplicity="{multiplicity}"/></Association>'
    '<EntityContainer Name="Svc" m:IsDefaultEntityContainer="true">'
    '<EntitySet Name="Orders" EntityType="Sales.Order"/><EntitySet Name="Customers" EntityType="Sales.Customer"/>'
    "</EntityContainer></Schema></edmx:DataServices></edmx:Edmx>"
)
_V2_NAV = '<NavigationProperty Name="Customer" Relationship="Sales.OrderCustomer" FromRole="Order" ToRole="Customer"/>'


def _v2(order_nav: str = "", multiplicity: str = "1", order_annotations: str = ""):
    adapter = ODataImportSource()
    text = _V2.format(order_nav=order_nav, multiplicity=multiplicity, order_annotations=order_annotations)
    return adapter.normalize(adapter.parse(text))


@pytest.mark.parametrize(
    ("multiplicity", "expected"),
    [("0..1", ("safe", "odata.navigation-added")), ("1", ("breaking", "odata.navigation-added-required"))],
)
def test_v2_navigation_nullability_comes_from_the_multiplicity(multiplicity: str, expected: Tuple[str, str]):
    grades = _grades(_v2(multiplicity=multiplicity), _v2(order_nav=_V2_NAV, multiplicity=multiplicity))
    assert grades["Sales.Order"][:2] == expected


def test_annotations_added_are_safe_and_changed_are_dangerous():
    added = _grades(_v2(), _v2(order_annotations=' sap:label="Order"'))
    assert added["Sales.Order"][:2] == ("safe", "odata.annotation-added")
    changed = _grades(_v2(order_annotations=' sap:label="Order"'), _v2(order_annotations=' sap:label="Sales order"'))
    assert changed["Sales.Order"][:2] == ("dangerous", "odata.annotation-changed")


# ===========================================================================
# $schemaversion
# ===========================================================================

_VERSION = '<Annotation Term="Core.SchemaVersion" String="{version}"/>'


def test_schema_versions_are_read_from_the_csdl_json():
    assert schema_versions(_model(schema_annotations=_VERSION.format(version="2"))) == {"Shop": "2"}
    assert schema_versions(_model()) == {}
    assert schema_versions(_model(schema_annotations=_VERSION.format(version="2"), include_raw=False)) == {}


def test_a_breaking_diff_without_a_schema_version_bump_says_so():
    grades = _grades(_model(), _model(key='<PropertyRef Name="Code"/>'))
    assert "Core.SchemaVersion did not change" in grades["Shop.Product"][2]
    assert "$schemaversion" in grades["Shop.Product"][2]


def test_a_breaking_diff_with_a_schema_version_bump_says_so():
    base = _model(schema_annotations=_VERSION.format(version="1"))
    head = _model(schema_annotations=_VERSION.format(version="2"), key='<PropertyRef Name="Code"/>')
    rationale = _grades(base, head)["Shop.Product"][2]
    assert "Core.SchemaVersion moved (Shop: '1' → '2')" in rationale


def test_safe_grades_carry_no_schema_version_note():
    grades = _grades(_model(), _model(properties='<Property Name="Note" Type="Edm.String"/>'))
    assert "SchemaVersion" not in grades["Shop.Product.Note"][2]


def test_the_overall_result_is_breaking_when_any_change_is():
    base, head = _model(), _model(properties='<Property Name="Stock" Type="Edm.Int32" Nullable="false"/>')
    result = classify(diff(base, head), base, head)
    assert result.overall_severity is Severity.BREAKING
    assert result.breaking
