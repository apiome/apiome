"""OPC UA NodeSet2 import — FMT-9.1 (#5468).

The acceptance criteria, in the order the issue lists them:

* a NodeSet2 file imports; types become canonical types and methods become operations;
* structured ``UADataType`` definitions map to records with fields;
* the reference graph is preserved in the payload analysis and bounded by the analyzer's node
  budget — a nodeset over the budget reports ``partial`` / ``bounds_exceeded`` (the fixture is
  generated here, as the corpus README says, rather than committed);
* namespace URIs and the model version are recorded in provenance;
* the corpus covers a companion-specification nodeset, a small custom nodeset and the
  over-budget case (``tests/test_corpus_golden.py`` / ``test_analysis_golden.py`` pin every
  corpus entry; this file pins behaviour).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from app.canonical_model import TypeKind
from app.import_preview_manifest import _opcua_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.inference_provenance import SYNTHESIZED, provenance_of
from app.opcua_nodeset_analysis import ROLE_DECLARATION, ROLE_INSTANCE, ROLE_SIGNATURE, ROLE_TYPE
from app.opcua_nodeset_normalizer import BUILTIN_DATA_TYPES, LIMIT_DETAILS, PARTIAL_LIMITS
from app.opcua_nodeset_parser import (
    NodeSetParseError,
    canonical_node_id,
    is_nodeset,
    namespace_index,
    parse_nodeset,
    parse_nodeset_fileset,
    split_browse_name,
)
from app.payload_analysis import MAX_TREE_NODES, REASON_BOUNDS_EXCEEDED, STATUS_AVAILABLE, STATUS_PARTIAL

load_builtin_import_sources()

CORPUS = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "opcua-nodeset"
ADAPTER = get_import_source("opcua-nodeset")

NODESET_OPEN = (
    '<UANodeSet xmlns="http://opcfoundation.org/UA/2011/03/UANodeSet.xsd" '
    'xmlns:uax="http://opcfoundation.org/UA/2008/02/Types.xsd">'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(name: str) -> str:
    return (CORPUS / name).read_text(encoding="utf-8")


def _import(name: str):
    """Parse and normalize one corpus file through the adapter."""
    document = ADAPTER.parse(_read(name), source_label=name)
    return document, ADAPTER.normalize(document)


def _types(api) -> Dict[str, Any]:
    return {type_.key: type_ for type_ in api.types}


def _fields(type_) -> Dict[str, Any]:
    return {field.name: field for field in type_.fields}


def _limits(api) -> Dict[str, int]:
    return {limit["construct"]: limit["count"] for limit in api.extras["opcua"]["capability_limits"]}


def _walk(nodes: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    for node in nodes:
        yield node
        yield from _walk(node.get("children") or [])


def _analysis_nodes(document) -> List[Dict[str, Any]]:
    analysis = ADAPTER.analyze(document, source=document.raw)
    return list(_walk(json.loads(analysis.model_dump_json(by_alias=True))["tree"]))


def _nodeset(body: str, *, uris: str = "<Uri>urn:test:model</Uri>", models: str = "") -> str:
    """A minimal NodeSet2 document around ``body``."""
    return f'<?xml version="1.0"?>\n{NODESET_OPEN}<NamespaceUris>{uris}</NamespaceUris>{models}{body}</UANodeSet>'


def _over_budget_nodeset(instances: int) -> str:
    """A plant model with one object type and ``instances`` variables of six references each."""
    variables = "".join(
        f'<UAVariable NodeId="ns=1;i={10000 + n}" BrowseName="1:Tag{n}" DataType="Double">'
        "<References>"
        '<Reference ReferenceType="HasTypeDefinition">i=63</Reference>'
        '<Reference ReferenceType="Organizes" IsForward="false">i=85</Reference>'
        '<Reference ReferenceType="HasProperty">i=2368</Reference>'
        '<Reference ReferenceType="GeneratesEvent">i=2041</Reference>'
        '<Reference ReferenceType="HasModellingRule">i=78</Reference>'
        '<Reference ReferenceType="HasNotifier">i=85</Reference>'
        "</References></UAVariable>"
        for n in range(instances)
    )
    object_type = (
        '<UAObjectType NodeId="ns=1;i=1" BrowseName="1:TankType"><References>'
        '<Reference ReferenceType="HasSubtype" IsForward="false">i=58</Reference>'
        "</References></UAObjectType>"
    )
    models = '<Models><Model ModelUri="urn:test:plant" Version="4.2.0" /></Models>'
    return _nodeset(object_type + variables, uris="<Uri>urn:test:plant</Uri>", models=models)


# ---------------------------------------------------------------------------
# NodeIds, browse names, detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written, expected",
    [
        ("ns=0;i=45", "i=45"),
        ("i=45", "i=45"),
        ("ns=1;i=1001", "ns=1;i=1001"),
        ("ns=01;s=Pump.Speed", "ns=1;s=Pump.Speed"),
        ("ns=2;g=09087e75-8e5e-499b-954f-f2a9603db28a", "ns=2;g=09087e75-8e5e-499b-954f-f2a9603db28a"),
        ("  ns=3;b=AQID  ", "ns=3;b=AQID"),
        ("", None),
        (None, None),
    ],
)
def test_node_ids_have_one_canonical_spelling(written, expected) -> None:
    assert canonical_node_id(written) == expected


def test_namespace_index_and_browse_name_prefixes() -> None:
    assert namespace_index("i=45") == 0
    assert namespace_index("ns=2;i=5") == 2
    assert split_browse_name("1:PumpType") == (1, "PumpType")
    assert split_browse_name("InputArguments") == (0, "InputArguments")


def test_detection_is_confident_on_the_schema_namespace_and_tolerant_without_it() -> None:
    with_namespace = ADAPTER.detect(DetectionInput(text=_read("01-minimal-nodeset.xml")))
    without = ADAPTER.detect(DetectionInput(text="<UANodeSet><NamespaceUris/></UANodeSet>"))
    assert with_namespace.format == "opcua-nodeset" and with_namespace.confidence >= 0.95
    assert without.format == "opcua-nodeset" and 0.8 <= without.confidence < with_namespace.confidence


def test_detection_ignores_a_comment_that_mentions_the_root() -> None:
    assert not is_nodeset("<!-- <UANodeSet> --><xs:schema xmlns:xs='x'/>")
    assert is_nodeset("<?xml version='1.0'?><!-- header --><UANodeSet/>")
    assert ADAPTER.detect(DetectionInput(text=_read("negative/04-wrong-format-xsd.xsd"))).confidence == 0


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, code",
    [
        ("negative/01-syntactic-unclosed-node.xml", "INPUT_MALFORMED"),
        ("negative/02-semantic-no-nodes.xml", "INPUT_SEMANTIC_INVALID"),
        ("negative/03-truncated-mid-definition.xml", "INPUT_TRUNCATED"),
        ("negative/04-wrong-format-xsd.xsd", "FORMAT_MISMATCH"),
        ("negative/06-unresolvable-node-reference.xml", "INPUT_REFERENCE_UNRESOLVED"),
    ],
)
def test_corpus_negatives_are_refused_with_their_code(name: str, code: str) -> None:
    with pytest.raises(ImportSourceError) as caught:
        ADAPTER.parse(_read(name), source_label=name)
    assert caught.value.code == code


def test_a_utf16_file_is_left_to_the_pipelines_encoding_rule() -> None:
    raw = (CORPUS / "negative/05-encoding-utf16.xml").read_bytes().decode("utf-8", errors="replace")
    with pytest.raises(ImportSourceError) as caught:
        ADAPTER.parse(raw)
    assert caught.value.code is None


def test_an_empty_document_and_a_non_xml_text_are_refused() -> None:
    with pytest.raises(NodeSetParseError) as empty:
        parse_nodeset("   ")
    with pytest.raises(NodeSetParseError) as text:
        parse_nodeset("ns=1;i=1001 is a NodeId, not a nodeset")
    assert (empty.value.code, text.value.code) == ("INPUT_EMPTY", "FORMAT_MISMATCH")


def test_a_duplicate_node_id_is_refused() -> None:
    body = '<UAObjectType NodeId="ns=1;i=1" BrowseName="1:A" /><UAObjectType NodeId="ns=1;i=1" BrowseName="1:B" />'
    with pytest.raises(NodeSetParseError) as caught:
        parse_nodeset(_nodeset(body))
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


def test_a_namespace_index_with_no_uri_is_refused() -> None:
    body = (
        '<UAObjectType NodeId="ns=1;i=1" BrowseName="1:A"><References>'
        '<Reference ReferenceType="HasComponent">ns=7;i=99</Reference>'
        "</References></UAObjectType>"
    )
    with pytest.raises(NodeSetParseError) as caught:
        parse_nodeset(_nodeset(body))
    assert caught.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_a_reference_into_a_required_model_is_declared_not_refused() -> None:
    body = (
        '<UAObjectType NodeId="ns=1;i=1" BrowseName="1:FillerType"><References>'
        '<Reference ReferenceType="HasSubtype" IsForward="false">ns=2;i=15063</Reference>'
        '<Reference ReferenceType="HasComponent">ns=1;i=2</Reference>'
        "</References></UAObjectType>"
        '<UAVariable NodeId="ns=1;i=2" BrowseName="1:Calibration" ParentNodeId="ns=1;i=1" DataType="ns=2;i=3017">'
        '<References><Reference ReferenceType="HasModellingRule">i=78</Reference></References></UAVariable>'
    )
    models = (
        '<Models><Model ModelUri="urn:test:model" Version="1.0.0">'
        '<RequiredModel ModelUri="http://opcfoundation.org/UA/DI/" Version="1.04.0" /></Model></Models>'
    )
    api = ADAPTER.normalize(
        parse_nodeset(
            _nodeset(body, uris="<Uri>urn:test:model</Uri><Uri>http://opcfoundation.org/UA/DI/</Uri>", models=models)
        )
    )
    field = _fields(_types(api)["FillerType"])["Calibration"]
    assert field.type.name == "any"
    assert field.type.extras == {
        "opcua_unresolved": "ns=2;i=3017",
        "opcua_namespace": "http://opcfoundation.org/UA/DI/",
    }
    assert _limits(api)["opcua.unresolved_reference"] == 2  # the supertype and the field


# ---------------------------------------------------------------------------
# Types and methods
# ---------------------------------------------------------------------------


def test_object_types_are_records_of_their_instance_declarations() -> None:
    _, api = _import("02-typical-machine-type.xml")
    machine = _types(api)["MachineType"]
    assert machine.kind is TypeKind.RECORD
    fields = _fields(machine)
    assert set(fields) == {"SerialNumber", "State", "Temperature"}
    assert fields["State"].type.name == "MachineState"
    assert fields["Temperature"].constraints.format == "double"
    assert fields["SerialNumber"].extras["opcua_property"] is True
    assert all(field.extras["opcua_modelling_rule"] == "Mandatory" for field in fields.values())
    assert machine.extras["native_id"] and machine.extras["opcua_supertype"] == "BaseObjectType"


def test_methods_become_rpc_operations_with_synthesized_argument_records() -> None:
    _, api = _import("02-typical-machine-type.xml")
    (service,) = api.services
    (operation,) = service.operations
    assert (service.key, operation.key, operation.kind.value) == (
        "MachineType",
        "MachineType.Start",
        "request_response",
    )
    (request,) = operation.messages
    record = _types(api)[request.payload.name]
    assert record.key == "MachineType_Start_Request"
    assert list(_fields(record)) == ["ProgrammeName"]
    assert provenance_of(record.extras) == SYNTHESIZED
    assert "input arguments of method MachineType.Start" in record.extras["provenance_evidence"]


def test_structured_enumerated_option_set_and_union_data_types() -> None:
    _, api = _import("04-stress-datatypes-and-methods.xml")
    types = _types(api)
    batch = _fields(types["BatchRecord"])
    assert types["BatchRecord"].kind is TypeKind.RECORD
    assert batch["StartedAt"].constraints.format == "date-time"
    assert batch["Readings"].type.item is not None
    assert batch["Operator"].type.nullable is True  # IsOptional
    assert batch["BatchId"].type.nullable is False
    assert [value.value for value in types["FaultCode"].enum_values] == [0, 10, 20, 99]
    assert types["AlarmFlags"].kind is TypeKind.ENUM and types["AlarmFlags"].extras["opcua_option_set"] is True
    measurement = types["Measurement"]
    assert measurement.extras["opcua_union"] is True
    assert all(field.type.nullable for field in measurement.fields)
    limits = _limits(api)
    assert {"opcua.option_set", "opcua.union", "opcua.multi_dimensional_array"} <= set(limits)


def test_value_ranks_and_array_dimensions() -> None:
    body = (
        '<UADataType NodeId="ns=1;i=1" BrowseName="1:Grid"><References>'
        '<Reference ReferenceType="HasSubtype" IsForward="false">i=22</Reference></References>'
        '<Definition Name="1:Grid">'
        '<Field Name="Cells" DataType="Double" ValueRank="2" ArrayDimensions="3,4" />'
        '<Field Name="Header" DataType="String" ValueRank="1" ArrayDimensions="16" />'
        '<Field Name="Samples" DataType="Float" ValueRank="0" />'
        '<Field Name="Anything" DataType="BaseDataType" ValueRank="-2" />'
        '<Field Name="Range" DataType="i=884" />'
        "</Definition></UADataType>"
    )
    api = ADAPTER.normalize(parse_nodeset(_nodeset(body)))
    fields = _fields(_types(api)["Grid"])
    assert fields["Cells"].type.item.item.name == "number"
    assert fields["Cells"].extras["opcua_array_dimensions"] == [3, 4]
    assert fields["Header"].constraints.max_items == 16
    assert fields["Samples"].type.item.name == "number" and fields["Samples"].constraints.max_items is None
    assert fields["Anything"].type.name == "any" and fields["Anything"].extras["opcua_value_rank"] == -2
    assert fields["Range"].type.name == "object" and fields["Range"].type.extras["opcua_base_type"] == "Range"


def test_every_builtin_data_type_has_a_scalar() -> None:
    assert BUILTIN_DATA_TYPES["i=6"] == ("integer", "int32")
    assert BUILTIN_DATA_TYPES["i=13"] == ("string", "date-time")
    assert all(
        name in ("boolean", "integer", "number", "string", "bytes", "object", "any")
        for name, _ in BUILTIN_DATA_TYPES.values()
    )


def test_inheritance_placeholders_and_variable_types() -> None:
    _, api = _import("03-composition-subtypes.xml")
    types = _types(api)
    pump = _fields(types["PumpType"])
    assert pump["AssetTag"].extras["opcua_inherited_from"] == "EquipmentType"
    assert types["MeasurementType"].kind is TypeKind.ALIAS and types["MeasurementType"].aliased.name == "number"
    assert _fields(types["ValveType"])["Position"].type.nullable is True  # Optional

    body = (
        '<UAObjectType NodeId="ns=1;i=1" BrowseName="1:PressType"><References>'
        '<Reference ReferenceType="HasComponent">ns=1;i=2</Reference>'
        '<Reference ReferenceType="HasComponent">ns=1;i=3</Reference></References></UAObjectType>'
        '<UAObjectType NodeId="ns=1;i=9" BrowseName="1:ToolType" />'
        '<UAObject NodeId="ns=1;i=2" BrowseName="1:&lt;Tool&gt;"><References>'
        '<Reference ReferenceType="HasTypeDefinition">ns=1;i=9</Reference>'
        '<Reference ReferenceType="HasModellingRule">i=11508</Reference></References></UAObject>'
        '<UAObject NodeId="ns=1;i=3" BrowseName="1:&lt;Zone&gt;"><References>'
        '<Reference ReferenceType="HasTypeDefinition">ns=1;i=9</Reference>'
        '<Reference ReferenceType="HasModellingRule">i=11510</Reference></References></UAObject>'
    )
    press = _fields(_types(ADAPTER.normalize(parse_nodeset(_nodeset(body))))["PressType"])
    assert press["<Tool>"].type.item.name == "ToolType" and press["<Tool>"].type.nullable is True
    assert press["<Zone>"].constraints.min_items == 1 and press["<Zone>"].type.nullable is False


def test_a_child_without_a_modelling_rule_is_still_part_of_its_type() -> None:
    _, api = _import("01-minimal-nodeset.xml")
    assert "Identifier" in _fields(_types(api)["BeaconType"])
    assert "opcua.instances_not_promoted" not in _limits(api)


def test_well_known_names_resolve_without_an_alias() -> None:
    body = (
        '<UADataType NodeId="ns=1;i=1" BrowseName="1:Reading"><References>'
        '<Reference ReferenceType="HasSubtype" IsForward="false">Structure</Reference></References>'
        '<Definition Name="1:Reading"><Field Name="Value" DataType="Double" /></Definition></UADataType>'
    )
    reading = _types(ADAPTER.normalize(parse_nodeset(_nodeset(body))))["Reading"]
    assert reading.extras["opcua_supertype"] == "Structure"
    assert reading.fields[0].type.name == "number"


def test_a_shared_browse_name_gets_a_distinct_key() -> None:
    body = (
        '<UADataType NodeId="ns=1;i=1" BrowseName="1:Mode"><References>'
        '<Reference ReferenceType="HasSubtype" IsForward="false">i=29</Reference></References>'
        '<Definition Name="1:Mode"><Field Name="Manual" Value="1" /></Definition></UADataType>'
        '<UAObjectType NodeId="ns=1;i=2" BrowseName="1:Mode" />'
    )
    assert set(_types(ADAPTER.normalize(parse_nodeset(_nodeset(body))))) == {"Mode", "Mode_ObjectType"}


# ---------------------------------------------------------------------------
# Instances and provenance
# ---------------------------------------------------------------------------


def test_address_space_instances_are_never_promoted() -> None:
    document, api = _import("06-typical-instance-address-space.xml")
    assert api.types == [] and api.services == []
    assert _limits(api)["opcua.instances_not_promoted"] == 7
    roles = {
        node["attributes"]["browseName"]: node["attributes"]["role"]
        for node in _analysis_nodes(document)
        if node["kind"] == "node"
    }
    assert set(roles.values()) == {ROLE_INSTANCE}
    assert len(roles) == 7


def test_namespaces_and_model_versions_are_recorded_as_provenance() -> None:
    _, api = _import("02-typical-machine-type.xml")
    record = api.extras["opcua"]
    assert record["namespace_uris"] == ["http://example.com/UA/Machine/"]
    (model,) = record["models"]
    assert model["model_uri"] == api.identity.namespace == "http://example.com/UA/Machine/"
    assert model["version"] == api.version == "1.2.0"
    assert any(required["model_uri"] == "http://opcfoundation.org/UA/" for required in model["required_models"])
    assert all(
        type_.namespace == "http://example.com/UA/Machine/" for type_ in api.types if "native_id" in type_.extras
    )


def test_references_are_kept_on_each_type() -> None:
    _, api = _import("02-typical-machine-type.xml")
    references = _types(api)["MachineType"].extras["opcua_references"]
    assert {
        "referenceType": "HasSubtype",
        "target": "i=58",
        "targetName": "BaseObjectType",
        "isForward": False,
    } in references
    assert any(reference["referenceType"] == "HasComponent" for reference in references)


def test_reference_types_are_recorded() -> None:
    _, api = _import("03-composition-subtypes.xml")
    (feeds,) = api.extras["opcua"]["reference_types"]
    assert (feeds["name"], feeds["inverse_name"], feeds["supertype"]) == (
        "FeedsInto",
        "FedFrom",
        "HierarchicalReferences",
    )


# ---------------------------------------------------------------------------
# Filesets
# ---------------------------------------------------------------------------


def test_a_fileset_resolves_a_required_model_shipped_beside_it() -> None:
    members = {
        name: (CORPUS / "07-companion-set" / name).read_text(encoding="utf-8")
        for name in ("model.xml", "companion.xml")
    }
    document = parse_nodeset_fileset(members, "model.xml")
    api = ADAPTER.normalize(document)
    types = _types(api)
    filler = _fields(types["VendorFillerType"])
    assert filler["CurrentRecipeState"].type.name == "RecipeState"
    assert filler["SerialNumber"].extras["opcua_inherited_from"] == "MachineBaseType"
    assert types["RecipeState"].namespace == "http://example.com/UA/Companion/"
    assert types["RecipeState"].extras["source_file"] == "companion.xml"
    assert [model["model_uri"] for model in api.extras["opcua"]["models"]] == [
        "http://example.com/UA/Vendor/",
        "http://example.com/UA/Companion/",
    ]


def test_the_root_alone_still_imports_with_the_companion_declared_unresolved() -> None:
    api = ADAPTER.normalize(parse_nodeset((CORPUS / "07-companion-set" / "model.xml").read_text(encoding="utf-8")))
    assert _limits(api)["opcua.unresolved_reference"] >= 1
    assert _fields(_types(api)["VendorFillerType"])["CurrentRecipeState"].type.name == "any"


def test_a_node_declared_in_two_members_is_refused() -> None:
    node = '<UAObjectType NodeId="ns=1;i=1" BrowseName="1:A" />'
    members = {"a.xml": _nodeset(node), "b.xml": _nodeset(node)}
    with pytest.raises(NodeSetParseError) as caught:
        parse_nodeset_fileset(members, "a.xml")
    assert caught.value.code == "INPUT_SEMANTIC_INVALID"


def test_a_fileset_without_its_root_is_refused() -> None:
    with pytest.raises(NodeSetParseError):
        parse_nodeset_fileset({"a.xml": _nodeset("")}, "missing.xml")


# ---------------------------------------------------------------------------
# Payload analysis and the node budget
# ---------------------------------------------------------------------------


def test_the_analysis_keeps_the_reference_graph_and_every_role() -> None:
    document, _ = _import("02-typical-machine-type.xml")
    analysis = ADAPTER.analyze(document, source=document.raw)
    assert analysis.status == STATUS_AVAILABLE
    nodes = _analysis_nodes(document)
    roles = {node["attributes"]["role"] for node in nodes if node["kind"] == "node"}
    assert {ROLE_TYPE, ROLE_DECLARATION, ROLE_SIGNATURE} <= roles
    references = [node for node in nodes if node["kind"] == "reference"]
    assert references and all(
        {"referenceType", "target", "isForward"} <= set(node["attributes"]) for node in references
    )
    assert any(node["kind"] == "field" for node in nodes)  # the enumeration's definition


def test_a_nodeset_over_the_node_budget_is_partial_and_keeps_every_node() -> None:
    instances = 900
    text = _over_budget_nodeset(instances)
    document = ADAPTER.parse(text, source_label="plant.xml")
    analysis = ADAPTER.analyze(document, source=text)
    assert (analysis.status, analysis.status_reason) == (STATUS_PARTIAL, REASON_BOUNDS_EXCEEDED)
    assert analysis.metrics.truncated is True
    assert analysis.metrics.node_count <= MAX_TREE_NODES
    assert analysis.metrics.dropped_node_count > 0
    nodes = _analysis_nodes(document)
    kept = [node for node in nodes if node["kind"] == "node"]
    assert len(kept) == instances + 1, "the budget drops references, never nodes"
    # The canonical model is unaffected by the budget, and records the instances it left out.
    api = ADAPTER.normalize(document)
    assert [type_.key for type_ in api.types] == ["TankType"]
    assert _limits(api)["opcua.instances_not_promoted"] == instances
    assert api.version == "4.2.0"


def test_analysis_is_deterministic() -> None:
    document, _ = _import("04-stress-datatypes-and-methods.xml")
    first = ADAPTER.analyze(document, source=document.raw).model_dump_json()
    second = ADAPTER.analyze(document, source=document.raw).model_dump_json()
    assert first == second


# ---------------------------------------------------------------------------
# Ledger, lint and registration
# ---------------------------------------------------------------------------


def test_declared_limits_render_as_graded_ledger_rows() -> None:
    _, api = _import("06-typical-instance-address-space.xml")
    (row,) = _opcua_capability_rows(api)
    assert row.source_construct == "opcua.instances_not_promoted"
    assert row.coverage.value == "not-parsed-by-adapter"
    assert PARTIAL_LIMITS == frozenset(LIMIT_DETAILS) - {"opcua.instances_not_promoted"}


def test_the_import_lints_and_the_adapter_is_registered() -> None:
    _, api = _import("05-real-world-companion-nodeset.xml")
    report = ADAPTER.lint(api)
    assert report.score is not None
    assert ADAPTER.paradigm.value == "rpc"
    assert "fileset" in [kind.value for kind in ADAPTER.input_kinds]
    assert ADAPTER.analyzer_key == "opcua-nodeset"
