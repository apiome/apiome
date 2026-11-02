"""OData functions and actions → canonical operations — MFI-11.2 (#3777).

The OData adapter mapped entity types and entity sets onto the canonical model but left the rest
of a service's callable surface out: v4 ``<Function>`` / ``<Action>`` overloads and their
container imports were never read, and v2/v3 ``<FunctionImport>`` signatures were kept only in
``extras``. This suite pins what the issue asks for:

#. functions and actions are read from CSDL XML **and** CSDL JSON, into the same canonical
   operations;
#. each overload is keyed by ``(kind, fully-qualified name, ordered parameter types)``, so
   overloads stay distinct and a key changes only with the signature;
#. parameters, the binding parameter, the return type and the HTTP route are carried;
#. v2/v3 function imports become operations too, with their ``m:HttpMethod``;
#. a document without operations normalizes exactly as before, and an OData → OData export
   writes the operations back unchanged.
"""

from __future__ import annotations

import json
from typing import Dict, List

import pytest

from app.canonical_model import CanonicalApi, MessageRole, Operation, ParameterLocation
from app.import_source import canonical_diff
from app.odata_csdl_json import csdl_xml_to_json, parse_csdl_json
from app.odata_emitter import ODataEmitOptions, ODataEmitter
from app.odata_import_source import ODataImportSource
from app.odata_normalizer import ODataNormalizer
from app.odata_operations import operation_key
from app.odata_parser import ODataOperation, ODataOperationParameter, parse_odata

_V4_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0">\n'
    "  <edmx:DataServices>\n"
    '    <Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="Shop">\n'
    '      <EntityType Name="Product"><Key><PropertyRef Name="ID"/></Key>\n'
    '        <Property Name="ID" Type="Edm.Int32" Nullable="false"/>\n'
    '        <Property Name="Price" Type="Edm.Decimal"/>\n'
    "      </EntityType>\n"
)
_V4_TAIL = "    </Schema>\n  </edmx:DataServices>\n</edmx:Edmx>\n"

#: A bound composable function, an overloaded unbound function (two signatures), a bound action
#: on one product and an unbound action with no result, plus their container imports.
_V4_OPERATIONS = (
    _V4_HEAD
    + '      <Function Name="Cheapest" IsBound="true" IsComposable="true">\n'
    '        <Parameter Name="products" Type="Collection(Shop.Product)"/>\n'
    '        <Parameter Name="max" Type="Edm.Int32" Nullable="false"/>\n'
    '        <ReturnType Type="Shop.Product"/>\n'
    "      </Function>\n"
    '      <Function Name="Search">\n'
    '        <Parameter Name="term" Type="Edm.String" Nullable="false"/>\n'
    '        <ReturnType Type="Collection(Shop.Product)"/>\n'
    "      </Function>\n"
    '      <Function Name="Search">\n'
    '        <Parameter Name="term" Type="Edm.String" Nullable="false"/>\n'
    '        <Parameter Name="limit" Type="Edm.Int32"/>\n'
    '        <ReturnType Type="Collection(Shop.Product)"/>\n'
    "      </Function>\n"
    '      <Action Name="Discount" IsBound="true">\n'
    '        <Parameter Name="product" Type="Shop.Product"/>\n'
    '        <Parameter Name="percent" Type="Edm.Int32" Nullable="false"/>\n'
    '        <ReturnType Type="Edm.Decimal"/>\n'
    "      </Action>\n"
    '      <Action Name="Reindex"/>\n'
    '      <EntityContainer Name="ShopService">\n'
    '        <EntitySet Name="Products" EntityType="Shop.Product"/>\n'
    '        <FunctionImport Name="Search" Function="Shop.Search" EntitySet="Products"/>\n'
    '        <ActionImport Name="Reindex" Action="Shop.Reindex"/>\n'
    "      </EntityContainer>\n"
    + _V4_TAIL
)

_V4_NO_OPERATIONS = (
    _V4_HEAD
    + '      <EntityContainer Name="ShopService">\n'
    '        <EntitySet Name="Products" EntityType="Shop.Product"/>\n'
    "      </EntityContainer>\n"
    + _V4_TAIL
)

_V2_SERVICE = """<?xml version="1.0" encoding="UTF-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" Version="1.0">
  <edmx:DataServices xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
                     m:DataServiceVersion="2.0">
    <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm" Namespace="Legacy">
      <EntityType Name="Order"><Key><PropertyRef Name="ID"/></Key>
        <Property Name="ID" Type="Edm.Int32" Nullable="false"/>
      </EntityType>
      <EntityContainer Name="LegacyService" m:IsDefaultEntityContainer="true">
        <EntitySet Name="Orders" EntityType="Legacy.Order"/>
        <FunctionImport Name="Release" ReturnType="Legacy.Order" EntitySet="Orders" m:HttpMethod="POST">
          <Parameter Name="OrderID" Type="Edm.Int32" Mode="In" Nullable="false"/>
        </FunctionImport>
        <FunctionImport Name="Pending" ReturnType="Collection(Legacy.Order)" EntitySet="Orders"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


def _normalize(document) -> CanonicalApi:
    return ODataNormalizer().normalize(document, include_raw=False)


def _operations(api: CanonicalApi) -> Dict[str, Operation]:
    """Every function / action / function-import operation, by key."""
    return {
        operation.key: operation
        for service in api.services
        for operation in service.operations
        if operation.extras.get("odata_kind")
    }


@pytest.fixture()
def v4_api() -> CanonicalApi:
    return _normalize(parse_odata(_V4_OPERATIONS))


# ===========================================================================
# Parsing
# ===========================================================================


def test_parses_every_v4_overload_and_import():
    schema = parse_odata(_V4_OPERATIONS).schemas[0]
    assert [(op.kind, op.name, len(op.parameters)) for op in schema.operations] == [
        ("Function", "Cheapest", 2),
        ("Function", "Search", 1),
        ("Function", "Search", 2),
        ("Action", "Discount", 2),
        ("Action", "Reindex", 0),
    ]
    cheapest = schema.operations[0]
    assert (cheapest.is_bound, cheapest.is_composable, cheapest.return_type) == (True, True, "Shop.Product")
    assert [(i.kind, i.name, i.operation, i.entity_set) for i in schema.entity_container.operation_imports] == [
        ("Function", "Search", "Shop.Search", "Products"),
        ("Action", "Reindex", "Shop.Reindex", None),
    ]


def test_xml_nullable_defaults_follow_csdl():
    """Unstated is nullable — except a collection, whose facet is about its items."""
    cheapest, search, *_ = parse_odata(_V4_OPERATIONS).schemas[0].operations
    assert [p.nullable for p in cheapest.parameters] == [False, False]  # collection, explicit false
    assert cheapest.return_nullable is True  # unstated single value
    assert search.return_nullable is False  # unstated collection


def test_an_action_is_never_composable():
    xml = _V4_HEAD + '      <Action Name="A" IsComposable="true"/>\n' + _V4_NO_OPERATIONS[len(_V4_HEAD):]
    (action,) = parse_odata(xml).schemas[0].operations
    assert action.is_composable is False


def test_a_parameter_without_a_type_is_skipped():
    xml = (
        _V4_HEAD
        + '      <Function Name="F"><Parameter Name="a"/><Parameter Name="b" Type="Edm.Int32"/>'
        '<ReturnType Type="Edm.Int32"/></Function>\n'
        + _V4_NO_OPERATIONS[len(_V4_HEAD):]
    )
    (function,) = parse_odata(xml).schemas[0].operations
    assert [p.name for p in function.parameters] == ["b"]


def test_a_v2_document_records_no_v4_operations():
    document = parse_odata(_V2_SERVICE)
    assert document.schemas[0].operations == ()
    assert document.schemas[0].entity_container.operation_imports == ()


# ===========================================================================
# Keys
# ===========================================================================


def test_operation_key_is_kind_name_and_ordered_signature():
    assert operation_key("Function", "Shop.Search", ["Edm.String", "Edm.Int32"]) == (
        "Function Shop.Search(Edm.String,Edm.Int32)"
    )
    assert operation_key("Action", "Shop.Reindex", []) == "Action Shop.Reindex()"


def test_overloads_get_distinct_keys(v4_api):
    keys = set(_operations(v4_api))
    assert {"Function Shop.Search(Edm.String)", "Function Shop.Search(Edm.String,Edm.Int32)"} <= keys
    assert len(keys) == 5


def test_parameter_order_is_part_of_the_key():
    swapped = _V4_OPERATIONS.replace(
        '<Parameter Name="term" Type="Edm.String" Nullable="false"/>\n'
        '        <Parameter Name="limit" Type="Edm.Int32"/>',
        '<Parameter Name="limit" Type="Edm.Int32"/>\n'
        '        <Parameter Name="term" Type="Edm.String" Nullable="false"/>',
    )
    keys = set(_operations(_normalize(parse_odata(swapped))))
    assert "Function Shop.Search(Edm.Int32,Edm.String)" in keys
    assert "Function Shop.Search(Edm.String,Edm.Int32)" not in keys


def test_keys_are_stable_across_imports():
    first = set(_operations(_normalize(parse_odata(_V4_OPERATIONS))))
    second = set(_operations(_normalize(parse_odata(_V4_OPERATIONS))))
    assert first == second


# ===========================================================================
# Normalization
# ===========================================================================


def test_bound_function_is_addressed_through_its_entity_set(v4_api):
    op = _operations(v4_api)["Function Shop.Cheapest(Collection(Shop.Product),Edm.Int32)"]
    assert (op.http_method, op.http_path) == ("GET", "/Products/Shop.Cheapest")
    # The binding parameter is the path, not a request parameter.
    assert [(p.name, p.location, p.required) for p in op.parameters] == [
        ("max", ParameterLocation.QUERY, True)
    ]
    assert op.extras["odata_bound"] is True
    assert op.extras["odata_composable"] is True
    assert op.extras["odata_binding_set"] == "Products"
    (response,) = op.messages
    assert (response.role, response.status_code, response.payload.name) == (
        MessageRole.RESPONSE,
        "200",
        "Shop.Product",
    )


def test_bound_action_on_one_entity_takes_its_parameters_in_the_body(v4_api):
    op = _operations(v4_api)["Action Shop.Discount(Shop.Product,Edm.Int32)"]
    assert (op.http_method, op.http_path) == ("POST", "/Products({key})/Shop.Discount")
    assert op.parameters == []
    request = next(m for m in op.messages if m.role is MessageRole.REQUEST)
    assert request.extras["odata_parameters"] == [
        {"name": "percent", "type": "Edm.Int32", "nullable": False}
    ]


def test_unbound_operations_use_their_import(v4_api):
    ops = _operations(v4_api)
    search = ops["Function Shop.Search(Edm.String,Edm.Int32)"]
    assert (search.http_path, search.extras["odata_import"]) == ("/Search", "Search")
    assert search.extras["odata_import_entity_set"] == "Products"
    # Canonical parameters are sorted by key (normalize_ordering); the declared order is kept in
    # the signature extras, which is what the key is built from.
    assert {(p.name, p.required) for p in search.parameters} == {("term", True), ("limit", False)}
    assert [p["name"] for p in search.extras["odata_parameter_signature"]] == ["term", "limit"]
    reindex = ops["Action Shop.Reindex()"]
    assert (reindex.http_method, reindex.http_path) == ("POST", "/Reindex")
    assert [(m.role, m.status_code) for m in reindex.messages] == [(MessageRole.RESPONSE, "204")]


def test_an_unimported_unbound_operation_has_no_path():
    xml = _V4_OPERATIONS.replace('        <ActionImport Name="Reindex" Action="Shop.Reindex"/>\n', "")
    op = _operations(_normalize(parse_odata(xml)))["Action Shop.Reindex()"]
    assert op.http_path is None
    assert "odata_import" not in op.extras


def test_a_bound_operation_with_no_entity_set_of_its_type_has_no_path():
    xml = _V4_OPERATIONS.replace(
        '<Parameter Name="product" Type="Shop.Product"/>', '<Parameter Name="product" Type="Shop.Other"/>'
    )
    op = _operations(_normalize(parse_odata(xml)))["Action Shop.Discount(Shop.Other,Edm.Int32)"]
    assert op.http_path is None
    assert "odata_binding_set" not in op.extras


def test_signature_is_recorded_in_full(v4_api):
    op = _operations(v4_api)["Action Shop.Discount(Shop.Product,Edm.Int32)"]
    assert op.extras["odata_parameter_signature"] == [
        {"name": "product", "type": "Shop.Product", "nullable": True},
        {"name": "percent", "type": "Edm.Int32", "nullable": False},
    ]


def test_operations_live_on_a_service_named_after_the_container(v4_api):
    service = next(s for s in v4_api.services if s.key == "Shop.ShopService")
    assert service.name == "ShopService"
    assert len(service.operations) == 5


def test_a_container_named_like_an_entity_set_merges_into_its_service():
    xml = _V4_OPERATIONS.replace('<EntityContainer Name="ShopService">', '<EntityContainer Name="Products">')
    api = _normalize(parse_odata(xml))
    (service,) = [s for s in api.services if s.key == "Shop.Products"]
    kinds = {op.extras.get("odata_kind") or op.extras.get("odata_operation") for op in service.operations}
    assert {"list", "get", "create", "function", "action"} <= kinds


def test_a_document_without_operations_is_unchanged():
    api = _normalize(parse_odata(_V4_NO_OPERATIONS))
    assert [s.key for s in api.services] == ["Shop.Products"]
    assert not _operations(api)


def test_normalizer_tolerates_a_hand_built_operation_without_nullability():
    """Parameters built outside a reader carry ``nullable=None``; they are optional, not required."""
    document = parse_odata(_V4_NO_OPERATIONS)
    schema = document.schemas[0]
    extra = ODataOperation(
        kind="Function",
        name="Ping",
        namespace="Shop",
        parameters=(ODataOperationParameter(name="echo", type_expr="Edm.String"),),
        return_type="Edm.String",
    )
    from dataclasses import replace

    document = replace(document, schemas=(replace(schema, operations=(extra,)),))
    (op,) = _operations(_normalize(document)).values()
    assert [(p.name, p.required) for p in op.parameters] == [("echo", False)]


# ===========================================================================
# CSDL JSON
# ===========================================================================


def test_csdl_json_gives_the_same_operations_as_xml(v4_api):
    from_json = _normalize(parse_csdl_json(json.dumps(csdl_xml_to_json(_V4_OPERATIONS))))
    assert _operations(from_json) == _operations(v4_api)


def test_csdl_json_reads_overload_lists_and_imports():
    document = {
        "$Version": "4.01",
        "$EntityContainer": "Shop.Svc",
        "Shop": {
            "Product": {"$Kind": "EntityType", "$Key": ["ID"], "ID": {"$Type": "Edm.Int32"}},
            "Find": [
                {"$Kind": "Function", "$Parameter": [{"$Name": "q"}], "$ReturnType": {"$Type": "Shop.Product"}},
                {"$Kind": "Function", "$Parameter": [{"$Name": "id", "$Type": "Edm.Int32"}],
                 "$ReturnType": {"$Type": "Shop.Product", "$Nullable": True}},
            ],
            "Svc": {
                "$Kind": "EntityContainer",
                "Products": {"$Collection": True, "$Type": "Shop.Product"},
                "Find": {"$Function": "Shop.Find"},
            },
        },
    }
    schema = parse_csdl_json(json.dumps(document)).schemas[0]
    assert [(op.name, op.parameters[0].type_expr, op.return_nullable) for op in schema.operations] == [
        ("Find", "Edm.String", False),
        ("Find", "Edm.Int32", True),
    ]
    assert [(i.name, i.operation) for i in schema.entity_container.operation_imports] == [("Find", "Shop.Find")]


def test_csdl_json_skips_malformed_overloads():
    document = {
        "$Version": "4.01",
        "Shop": {
            "Product": {"$Kind": "EntityType", "$Key": ["ID"], "ID": {"$Type": "Edm.Int32"}},
            "Bad": ["not an overload", {"$Kind": "Term"}, {"$Kind": "Action"}],
            "Svc": {"$Kind": "EntityContainer", "Products": {"$Collection": True, "$Type": "Shop.Product"}},
        },
    }
    schema = parse_csdl_json(json.dumps(document)).schemas[0]
    assert [(op.kind, op.name) for op in schema.operations] == [("Action", "Bad")]


# ===========================================================================
# v2 / v3 function imports
# ===========================================================================


def test_v2_function_imports_become_operations():
    ops = _operations(_normalize(parse_odata(_V2_SERVICE)))
    release = ops["FunctionImport LegacyService.Release(Edm.Int32)"]
    assert (release.http_method, release.http_path) == ("POST", "/Release")
    assert [(p.name, p.location, p.required) for p in release.parameters] == [
        ("OrderID", ParameterLocation.QUERY, True)
    ]
    assert release.extras["odata_import_entity_set"] == "Orders"
    pending = ops["FunctionImport LegacyService.Pending()"]
    assert pending.http_method == "GET"  # no m:HttpMethod and not side-effecting


def test_v3_side_effecting_import_defaults_to_post():
    xml = _V2_SERVICE.replace(
        '<FunctionImport Name="Pending" ReturnType="Collection(Legacy.Order)" EntitySet="Orders"/>',
        '<FunctionImport Name="Pending" ReturnType="Collection(Legacy.Order)" EntitySet="Orders" '
        'IsSideEffecting="true"/>',
    )
    pending = _operations(_normalize(parse_odata(xml)))["FunctionImport LegacyService.Pending()"]
    assert pending.http_method == "POST"


def test_v2_function_import_extras_are_kept():
    api = _normalize(parse_odata(_V2_SERVICE))
    container = api.extras["odata_schemas"][0]["entity_container"]
    assert [f["name"] for f in container["function_imports"]] == ["Release", "Pending"]


# ===========================================================================
# Export: an OData source's operations are written back unchanged
# ===========================================================================


@pytest.mark.parametrize("output", ["json", "xml"])
def test_odata_export_writes_operations_back_unchanged(output: str):
    source = ODataImportSource()
    api = source.normalize(source.parse(_V4_OPERATIONS))
    result = ODataEmitter().emit(api, opts=ODataEmitOptions(output=output))
    reimported = source.normalize(source.parse(result.files[0].content))
    changed: List[str] = [
        entry.key for entry in canonical_diff(api, reimported).entries if entry.entity == "operation"
    ]
    assert changed == []
    assert set(_operations(reimported)) == set(_operations(api))


def test_odata_export_keeps_overloads_together():
    source = ODataImportSource()
    api = source.normalize(source.parse(_V4_OPERATIONS))
    document = json.loads(ODataEmitter().emit(api, opts=ODataEmitOptions(output="json")).files[0].content)
    namespace = next(k for k in document if not k.startswith("$"))
    assert len(document[namespace]["Search"]) == 2
    assert document[namespace]["Cheapest"][0]["$IsBound"] is True


def test_an_imported_function_is_not_folded_into_its_entity_set():
    """`GET /Search` returning Products looks like the set's query; it stays a function."""
    source = ODataImportSource()
    api = source.normalize(source.parse(_V4_OPERATIONS))
    result = ODataEmitter().emit(api, opts=ODataEmitOptions(output="json"))
    reimported = source.normalize(source.parse(result.files[0].content))
    assert "Function Shop.Search(Edm.String)" in _operations(reimported)
    assert not any(
        loss.subject == "crud-as-entity-set" and "Search" in (loss.pointer or "") for loss in result.losses
    )
