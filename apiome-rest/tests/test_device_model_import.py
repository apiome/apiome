"""LwM2M / IPSO and Matter device-model import — FMT-9.5 (#5472).

Covers the shared XML intake (:mod:`app.device_model_xml`), the LwM2M reader and normalizer, the
Matter reader and normalizer, both adapters' detection, and the coverage-ledger rows of their
declared limits. The staged corpus (``apiome-ui/examples/lwm2m`` and ``matter``) is exercised by the
shared corpus suites; these tests pin each mapping rule on small inline documents.
"""

from __future__ import annotations

from typing import Dict, Optional

import pytest

from app.canonical_model import MessageRole, OperationKind, TypeKind
from app.device_model_xml import identifier, root_element_name
from app.fileset import IntakeFileset
from app.import_preview_manifest import _device_model_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.lwm2m_normalizer import OBJLNK_TYPE
from app.lwm2m_parser import parse_range

load_builtin_import_sources()

LWM2M = get_import_source("lwm2m")
MATTER = get_import_source("matter")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _item(
    item_id: int,
    name: str,
    *,
    operations: str = "R",
    type_: Optional[str] = "String",
    multiple: str = "Single",
    mandatory: str = "Optional",
    range_: str = "",
    units: str = "",
) -> str:
    type_xml = f"<Type>{type_}</Type>" if type_ is not None else "<Type/>"
    range_xml = f"<RangeEnumeration>{range_}</RangeEnumeration>" if range_ else "<RangeEnumeration/>"
    units_xml = f"<Units>{units}</Units>" if units else "<Units/>"
    return (
        f'<Item ID="{item_id}"><Name>{name}</Name><Operations>{operations}</Operations>'
        f"<MultipleInstances>{multiple}</MultipleInstances><Mandatory>{mandatory}</Mandatory>"
        f"{type_xml}{range_xml}{units_xml}<Description>{name} resource.</Description></Item>"
    )


def _object(object_id: int, name: str, *items: str) -> str:
    return (
        f'<Object ObjectType="MODefinition"><Name>{name}</Name><Description1>{name} object.</Description1>'
        f"<ObjectID>{object_id}</ObjectID><ObjectURN>urn:oma:lwm2m:x:{object_id}</ObjectURN>"
        f"<LWM2MVersion>1.1</LWM2MVersion><ObjectVersion>1.0</ObjectVersion>"
        f"<MultipleInstances>Multiple</MultipleInstances><Mandatory>Optional</Mandatory>"
        f"<Resources>{''.join(items)}</Resources></Object>"
    )


def _lwm2m(*objects: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<LWM2M>{"".join(objects)}</LWM2M>\n'


def _matter(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<configurator>{body}</configurator>\n'


def _cluster(body: str, *, name: str = "Widget", code: str = "0xFFF1") -> str:
    return f"<cluster><name>{name}</name><code>{code}</code><define>WIDGET_CLUSTER</define>{body}</cluster>"


def _import_lwm2m(text: str):
    return LWM2M.normalize(LWM2M.parse(text, source_label="object.xml"), include_raw=False)


def _import_matter(text: str):
    return MATTER.normalize(MATTER.parse(text, source_label="cluster.xml"), include_raw=False)


def _types(api) -> Dict[str, object]:
    return {item.key: item for item in api.types}


def _fields(type_) -> Dict[str, object]:
    return {item.name: item for item in type_.fields}


def _operations(api) -> Dict[str, object]:
    return {operation.key: operation for service in api.services for operation in service.operations}


def _limits(api, key: str) -> Dict[str, int]:
    return {limit["construct"]: limit["count"] for limit in api.extras[key]["capability_limits"]}


def _code(callable_, *args, **kwargs) -> Optional[str]:
    with pytest.raises(ImportSourceError) as caught:
        callable_(*args, **kwargs)
    return caught.value.code


# ---------------------------------------------------------------------------
# Shared XML intake
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Sensor Value", "SensorValue"),
        ("On/Off", "OnOff"),
        ("PkgName", "PkgName"),
        ("Reset Min and Max Measured Values", "ResetMinAndMaxMeasuredValues"),
        ("3D Position", "_3DPosition"),
        ("---", "Fallback"),
    ],
)
def test_identifier_joins_words(name, expected):
    assert identifier(name, fallback="Fallback") == expected


def test_root_element_name_ignores_declaration_and_comments():
    text = '<?xml version="1.0"?>\n<!-- <cluster> in a comment -->\n<LWM2M xmlns:x="u"><Obj'
    assert root_element_name(text) == "LWM2M"
    assert root_element_name("not xml") is None
    assert root_element_name("") is None


# ---------------------------------------------------------------------------
# LwM2M detection
# ---------------------------------------------------------------------------


def test_lwm2m_detects_object_definition_confidently():
    text = _lwm2m(_object(32700, "Beacon", _item(0, "Identifier")))
    result = LWM2M.detect(DetectionInput(text=text, filename="32700.xml"))
    assert result.matched and result.format == "lwm2m" and result.confidence >= 0.95


def test_lwm2m_detects_truncated_head_and_refuses_other_roots():
    assert LWM2M.detect(DetectionInput(text="<LWM2M>\n  <Obj", filename=None)).matched
    assert not LWM2M.detect(DetectionInput(text=_matter(_cluster("")), filename=None)).matched
    assert not LWM2M.detect(DetectionInput(text="openapi: 3.1.0", filename=None)).matched


# ---------------------------------------------------------------------------
# LwM2M mapping
# ---------------------------------------------------------------------------


def test_lwm2m_object_becomes_record_and_resources_fields():
    api = _import_lwm2m(
        _lwm2m(
            _object(
                3303,
                "Temperature",
                _item(5700, "Sensor Value", type_="Float", mandatory="Mandatory", units="Cel"),
                _item(5750, "Application Type", operations="RW"),
                _item(5800, "Secret", operations="W"),
                _item(5605, "Reset Min and Max", operations="E", type_=None),
            )
        )
    )
    assert api.format == "lwm2m" and api.paradigm.value == "data_schema" and api.protocol == "lwm2m"
    assert api.identity.name == "Temperature" and api.identity.namespace == "urn:oma:lwm2m:x:3303"
    assert api.version == "1.0"
    record = _types(api)["Temperature"]
    assert record.kind is TypeKind.RECORD
    assert record.extras["lwm2m_object"]["id"] == 3303
    fields = _fields(record)
    assert set(fields) == {"SensorValue", "ApplicationType", "Secret"}
    value = fields["SensorValue"]
    assert value.field_number == 5700
    assert value.type.name == "double" and value.type.nullable is False
    assert value.constraints.extras["unit"] == "Cel"
    assert value.extras["lwm2m_resource"]["access"] == "read"
    assert fields["ApplicationType"].type.nullable is True
    assert fields["ApplicationType"].extras["lwm2m_resource"]["access"] == "read-write"
    assert fields["Secret"].extras["lwm2m_resource"]["access"] == "write"


def test_lwm2m_executable_resource_becomes_one_way_operation():
    api = _import_lwm2m(
        _lwm2m(_object(3, "Device", _item(0, "Manufacturer"), _item(4, "Reboot", operations="E", type_=None)))
    )
    operations = _operations(api)
    assert list(operations) == ["DeviceService.Reboot"]
    reboot = operations["DeviceService.Reboot"]
    assert reboot.kind is OperationKind.ONE_WAY
    assert reboot.extras["lwm2m_resource"]["id"] == 4
    assert reboot.extras["lwm2m_object"] == 3
    assert "Reboot" not in _fields(_types(api)["Device"])


def test_lwm2m_object_without_executables_has_no_service():
    api = _import_lwm2m(_lwm2m(_object(32700, "Beacon", _item(0, "Identifier"))))
    assert api.services == []


@pytest.mark.parametrize(
    "type_, range_, expected",
    [
        ("Integer", "0..100", {"minimum": 0.0, "maximum": 100.0}),
        ("Float", "-40..150.5", {"minimum": -40.0, "maximum": 150.5}),
        ("String", "0..64", {"min_length": 0, "max_length": 64}),
        ("Opaque", "1..1024", {"min_length": 1, "max_length": 1024}),
        ("Integer", "0, 1, 2", {"enum": [0, 1, 2]}),
        ("String", "U, UQ, S", {"enum": ["U", "UQ", "S"]}),
    ],
)
def test_lwm2m_range_enumeration_maps_to_constraints(type_, range_, expected):
    api = _import_lwm2m(_lwm2m(_object(32701, "Ranged", _item(0, "Value", type_=type_, range_=range_))))
    constraints = _fields(_types(api)["Ranged"])["Value"].constraints
    assert {name: getattr(constraints, name) for name in expected} == expected
    assert _limits(api, "lwm2m") == {}


def test_lwm2m_multiple_instances_is_a_list_with_item_facets():
    api = _import_lwm2m(
        _lwm2m(
            _object(
                3,
                "Device",
                _item(6, "Power Sources", type_="Integer", multiple="Multiple", mandatory="Mandatory", range_="0..7"),
            )
        )
    )
    field = _fields(_types(api)["Device"])["PowerSources"]
    assert field.type.is_list() and field.type.item.name == "int64" and field.type.nullable is False
    assert field.constraints.minimum is None
    assert field.constraints.extras == {"item_minimum": 0.0, "item_maximum": 7.0}


def test_lwm2m_time_corelnk_and_objlnk_types():
    api = _import_lwm2m(
        _lwm2m(
            _object(
                32702,
                "Links",
                _item(0, "When", type_="Time"),
                _item(1, "Core", type_="Corelnk"),
                _item(2, "Target", type_="Objlnk"),
                _item(3, "Count", type_="Unsigned Integer"),
            )
        )
    )
    fields = _fields(_types(api)["Links"])
    assert fields["When"].type.name == "int64" and fields["When"].constraints.format == "unix-time"
    assert fields["Core"].type.name == "string" and fields["Core"].constraints.format == "core-link"
    assert fields["Target"].type.name == OBJLNK_TYPE
    assert fields["Count"].type.name == "uint64"
    objlnk = _types(api)[OBJLNK_TYPE]
    assert [field.name for field in objlnk.fields] == ["ObjectID", "ObjectInstanceID"]
    assert objlnk.extras["provenance"] == "synthesized"
    assert _limits(api, "lwm2m") == {"lwm2m.object_link_target": 1}


def test_lwm2m_unparsed_range_is_kept_and_declared():
    api = _import_lwm2m(_lwm2m(_object(32703, "Odd", _item(0, "Value", type_="Integer", range_="see spec"))))
    field = _fields(_types(api)["Odd"])["Value"]
    assert field.constraints is None
    assert field.extras["lwm2m_resource"]["range"] == "see spec"
    assert _limits(api, "lwm2m") == {"lwm2m.unparsed_range": 1}


def test_lwm2m_colliding_identifiers_are_suffixed_by_id():
    api = _import_lwm2m(
        _lwm2m(
            _object(32704, "Twin", _item(0, "On Off"), _item(1, "On/Off")),
            _object(32705, "Twin", _item(0, "Value")),
        )
    )
    types = _types(api)
    assert {"Twin", "Twin_32705"} <= set(types)
    assert set(_fields(types["Twin"])) == {"OnOff", "OnOff_1"}
    assert api.identity.name == "Twin, Twin"


def test_parse_range_rejects_reversed_bounds():
    assert not parse_range("10..1", "Integer").is_parsed
    assert parse_range("", "Integer") is None


# ---------------------------------------------------------------------------
# LwM2M refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, code",
    [
        ("", "INPUT_EMPTY"),
        ("not xml at all", "FORMAT_MISMATCH"),
        ("\ufeff<LWM2M/>", "INPUT_ENCODING_INVALID"),
        ("<\x00L\x00W\x00M\x002\x00M\x00>", "INPUT_ENCODING_INVALID"),
        ("<LWM2M><Object><Name>X</Name><ObjectID>1", "INPUT_TRUNCATED"),
        ("<LWM2M><Object></Resources></Object></LWM2M>", "INPUT_MALFORMED"),
        (_matter(_cluster("")), "FORMAT_MISMATCH"),
        ("<LWM2M/>", "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(1, "Empty")), "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(1, "BadType", _item(0, "V", type_="Decimal128"))), "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(1, "BadOps", _item(0, "V", operations="RX"))), "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(1, "NoType", _item(0, "V", type_=None))), "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(1, "BadFlag", _item(0, "V", multiple="Many"))), "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(1, "Dup", _item(0, "A"), _item(0, "B"))), "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(1, "A", _item(0, "V")), _object(1, "B", _item(0, "V"))), "INPUT_SEMANTIC_INVALID"),
        (_lwm2m(_object(70000, "Huge", _item(0, "V"))), "INPUT_SEMANTIC_INVALID"),
        ("<LWM2M><!DOCTYPE x [<!ENTITY e 'v'>]></LWM2M>", "INPUT_MALFORMED"),
    ],
)
def test_lwm2m_refusals_carry_taxonomy_codes(text, code):
    assert _code(LWM2M.parse, text, source_label="bad.xml") == code


def test_lwm2m_refusal_names_every_problem():
    text = _lwm2m(_object(1, "Untyped", _item(0, "A", type_="Decimal128"), _item(1, "B", operations="RX")))
    with pytest.raises(ImportSourceError) as caught:
        LWM2M.parse(text, source_label="bad.xml")
    assert "Decimal128" in str(caught.value) and "'RX'" in str(caught.value)


def test_lwm2m_dtd_is_refused_as_unsafe():
    text = '<?xml version="1.0"?>\n<!DOCTYPE LWM2M [<!ENTITY x "y">]>\n<LWM2M>&x;</LWM2M>'
    assert _code(LWM2M.parse, text, source_label="evil.xml") == "INPUT_UNSAFE_CONSTRUCT"


# ---------------------------------------------------------------------------
# LwM2M fileset
# ---------------------------------------------------------------------------


def test_lwm2m_fileset_reads_every_object_file_root_first():
    fileset = IntakeFileset.from_members(
        {
            "b/32711.xml": _lwm2m(_object(32711, "Probe", _item(0, "Value", type_="Float"))),
            "32710.xml": _lwm2m(_object(32710, "Unit", _item(0, "Probe", type_="Objlnk"))),
            "README.md": "# not a definition",
            "other.xml": "<catalog/>",
        },
        root="32710.xml",
    )
    document = LWM2M.parse_fileset(fileset, source_label="set")
    assert [obj.object_id for obj in document.objects] == [32710, 32711]
    assert set(document.sources) == {"32710.xml", "b/32711.xml"}
    api = LWM2M.normalize(document)
    assert api.identity.name == "Unit"
    assert api.extras["lwm2m"]["input"] == "fileset"
    assert {obj["file"] for obj in api.extras["lwm2m"]["objects"]} == {"32710.xml", "b/32711.xml"}
    assert [item["path"] for item in api.raw["files"]] == ["32710.xml", "b/32711.xml"]


def test_lwm2m_fileset_refuses_duplicate_object_ids_across_files():
    one = _lwm2m(_object(32710, "Unit", _item(0, "V")))
    fileset = IntakeFileset.from_members({"a.xml": one, "b.xml": one}, root="a.xml")
    assert _code(LWM2M.parse_fileset, fileset) == "INPUT_SEMANTIC_INVALID"


# ---------------------------------------------------------------------------
# Matter detection
# ---------------------------------------------------------------------------


def test_matter_detects_cluster_and_device_type():
    for body in (
        _cluster('<attribute code="0" type="boolean">On</attribute>'),
        "<deviceType><name>D</name></deviceType>",
    ):
        result = MATTER.detect(DetectionInput(text=_matter(body), filename="x.xml"))
        assert result.matched and result.format == "matter" and result.confidence >= 0.95


def test_matter_detection_is_weak_for_bare_configurator_and_absent_otherwise():
    assert 0 < MATTER.detect(DetectionInput(text=_matter('<domain name="G"/>'), filename=None)).confidence < 0.9
    assert not MATTER.detect(DetectionInput(text=_lwm2m(_object(1, "X", _item(0, "V"))), filename=None)).matched


# ---------------------------------------------------------------------------
# Matter mapping
# ---------------------------------------------------------------------------


_STATUS_ENUM = (
    '<enum name="ModeEnum" type="enum8"><cluster code="0xFFF1"/><item name="Off" value="0x00"/><item name="Auto" '
    'value="0x01"/></enum>'
)
_FEATURE_BITMAP = (
    '<bitmap name="WidgetFeature" type="bitmap32"><cluster code="0xFFF1"/><field name="A" mask="0x1"/><field '
    'name="B" mask="0x2"/></bitmap>'
)
_RANGE_STRUCT = (
    '<struct name="RangeStruct"><cluster code="0xFFF1"/><item fieldId="0" name="Min" type="int32s"/><item '
    'fieldId="1" name="Max" type="int32s" optional="true"/></struct>'
)


def test_matter_cluster_attributes_become_fields_with_access():
    api = _import_matter(
        _matter(
            _STATUS_ENUM
            + _cluster(
                "<description>A widget.</description>"
                '<attribute side="server" code="0x0000" define="LEVEL" type="int8u" writable="false" '
                'reportable="true" default="0x10">Level</attribute>'
                '<attribute side="server" code="0x0001" define="SETPOINT" type="temperature" writable="true" '
                'optional="true" min="-500" max="0x0BB8">Setpoint'
                '<access op="read" privilege="view"/><access op="write" privilege="manage"/></attribute>'
                '<attribute side="server" code="0x0002" define="LABEL" type="char_string" length="32" '
                'writable="true" isNullable="true" default="">Label</attribute>'
                '<attribute side="server" code="0x0003" define="MODE" type="ModeEnum" writable="true" '
                'default="Auto">Mode</attribute>'
                '<attribute side="server" code="0x0004" define="ON" type="boolean" default="true">On</attribute>'
                '<attribute side="server" code="0x0005" define="PCT" type="percent100ths">Pct</attribute>'
            )
        )
    )
    assert api.format == "matter" and api.paradigm.value == "rpc" and api.protocol == "matter"
    assert api.identity.name == "Widget"
    record = _types(api)["Widget"]
    assert record.description == "A widget."
    assert record.extras["matter_cluster"]["code"] == "0xFFF1"
    fields = _fields(record)
    level = fields["Level"]
    assert level.field_number == 0 and level.type.name == "uint8" and level.type.nullable is False
    assert level.default == 16 and level.extras["matter_default"] == "0x10"
    assert level.extras["matter_attribute"]["access"] == "read"
    assert level.extras["matter_attribute"]["reportable"] is True
    setpoint = fields["Setpoint"]
    assert setpoint.type.name == "int16" and setpoint.type.nullable is True
    assert setpoint.constraints.minimum == -500 and setpoint.constraints.maximum == 3000
    assert setpoint.extras["matter_type"] == "temperature"
    assert setpoint.extras["matter_attribute"]["access"] == "read-write"
    assert setpoint.extras["matter_attribute"]["privileges"] == {"read": "view", "write": "manage"}
    label = fields["Label"]
    assert label.type.nullable is True and label.constraints.max_length == 32 and label.default == ""
    assert fields["Mode"].type.name == "ModeEnum" and fields["Mode"].default == "Auto"
    assert fields["On"].default is True
    assert fields["Pct"].constraints.maximum == 10000


def test_matter_list_attribute_uses_entry_type_and_list_bounds():
    api = _import_matter(
        _matter(
            _RANGE_STRUCT
            + _cluster(
                '<attribute code="0x0000" type="array" entryType="RangeStruct" length="8" '
                'minLength="1">Ranges</attribute>'
            )
        )
    )
    ranges = _fields(_types(api)["Widget"])["Ranges"]
    assert ranges.type.is_list() and ranges.type.item.name == "RangeStruct"
    assert ranges.constraints.max_items == 8 and ranges.constraints.min_items == 1
    assert ranges.extras["matter_type"] == "array<RangeStruct>"
    struct = _types(api)["RangeStruct"]
    assert struct.kind is TypeKind.RECORD
    assert {f.name: (f.field_number, f.type.nullable) for f in struct.fields} == {"Min": (0, False), "Max": (1, True)}


def test_matter_commands_become_operations_with_request_and_response_records():
    api = _import_matter(
        _matter(
            _cluster(
                '<attribute code="0" type="boolean">On</attribute>'
                '<command source="client" code="0x00" name="Start" response="StartResponse">'
                '<description>Begin.</description><arg name="Seconds" type="int32u" min="1"/>'
                '<arg name="Tags" type="char_string" array="true" optional="true"/>'
                '<access op="invoke" privilege="operate"/></command>'
                '<command source="server" code="0x01" name="StartResponse"><arg name="Accepted" '
                'type="boolean"/></command>'
                '<command source="client" code="0x02" name="Stop"/>'
            )
        )
    )
    operations = _operations(api)
    assert set(operations) == {"WidgetService.Start", "WidgetService.Stop"}
    start = operations["WidgetService.Start"]
    assert start.kind is OperationKind.REQUEST_RESPONSE and start.description == "Begin."
    roles = {message.role: message.payload.name for message in start.messages}
    assert roles == {MessageRole.REQUEST: "Widget.StartRequest", MessageRole.RESPONSE: "Widget.StartResponse"}
    assert start.extras["matter_command"]["privileges"] == {"invoke": "operate"}
    request = _fields(_types(api)["Widget.StartRequest"])
    assert request["Seconds"].type.name == "uint32" and request["Seconds"].constraints.minimum == 1
    assert request["Tags"].type.is_list() and request["Tags"].type.nullable is True
    assert _types(api)["Widget.StartResponse"].extras["matter_command"]["source"] == "server"
    stop = operations["WidgetService.Stop"]
    assert stop.messages == [] and stop.extras["matter_command"]["response"] == "default"


def test_matter_events_become_subscribe_operations():
    api = _import_matter(
        _matter(
            _cluster(
                '<event source="server" code="0x00" name="Fault" priority="critical" optional="true">'
                '<description>Broke.</description><field id="0" name="Detail" type="char_string" isNullable="true" '
                'length="64"/></event>'
                '<event source="server" code="0x01" name="ShutDown" priority="info"/>'
            )
        )
    )
    operations = _operations(api)
    fault = operations["WidgetService.Fault"]
    assert fault.kind is OperationKind.SUBSCRIBE
    assert fault.messages[0].role is MessageRole.EVENT
    assert fault.messages[0].payload.name == "Widget.FaultEvent"
    assert fault.extras["matter_event"] == {"code": "0x00", "priority": "critical", "optional": True}
    detail = _fields(_types(api)["Widget.FaultEvent"])["Detail"]
    assert detail.constraints.max_length == 64 and detail.type.nullable is True
    assert _types(api)["Widget.ShutDownEvent"].fields == []


def test_matter_event_named_like_a_command_is_suffixed():
    api = _import_matter(
        _matter(
            _cluster('<command source="client" code="0" name="Ping"/><event code="0" name="Ping" priority="info"/>')
        )
    )
    assert set(_operations(api)) == {"WidgetService.Ping", "WidgetService.PingEvent"}


def test_matter_enum_and_bitmap_become_enums():
    api = _import_matter(
        _matter(_STATUS_ENUM + _FEATURE_BITMAP + _cluster('<attribute code="0" type="ModeEnum">Mode</attribute>'))
    )
    types = _types(api)
    assert sorted((v.name, v.value) for v in types["ModeEnum"].enum_values) == [("Auto", 1), ("Off", 0)]
    assert types["ModeEnum"].extras["matter_enum"] == {"base": "enum8", "clusters": ["0xFFF1"]}
    bitmap = types["WidgetFeature"]
    assert bitmap.kind is TypeKind.ENUM and {v.value for v in bitmap.enum_values} == {1, 2}
    assert _limits(api, "matter") == {"matter.bitmap_flags": 1}


def test_matter_features_are_kept_and_declared():
    api = _import_matter(
        _matter(
            _cluster(
                '<features><feature bit="0" code="DIRC" name="Direct"><optionalConform/></feature></features>'
                '<attribute code="0" type="boolean">On</attribute>'
            )
        )
    )
    features = _types(api)["Widget"].extras["matter_cluster"]["features"]
    assert features == [{"bit": "0", "code": "DIRC", "name": "Direct", "conformance": ["optionalConform"]}]
    assert _limits(api, "matter") == {"matter.feature_conformance": 1}


def test_matter_same_named_types_for_different_clusters_are_namespaced():
    enum_a = '<enum name="Feature" type="bitmap8"><cluster code="0xFFF1"/><item name="A" value="1"/></enum>'
    enum_b = '<enum name="Feature" type="bitmap8"><cluster code="0xFFF2"/><item name="B" value="1"/></enum>'
    api = _import_matter(
        _matter(
            enum_a
            + enum_b
            + _cluster('<attribute code="0" type="Feature">F</attribute>')
            + _cluster('<attribute code="0" type="Feature">F</attribute>', name="Gadget", code="0xFFF2")
        )
    )
    types = _types(api)
    assert {"Widget.Feature", "Gadget.Feature"} <= set(types)
    assert _fields(types["Widget"])["F"].type.name == "Widget.Feature"
    assert _fields(types["Gadget"])["F"].type.name == "Gadget.Feature"


def test_matter_undeclared_type_on_standard_cluster_is_declared():
    api = _import_matter(
        _matter(
            _cluster(
                '<command source="client" code="0x40" name="OffWithEffect"><arg name="Effect" '
                'type="EffectIdentifierEnum"/></command>',
                name="On/Off",
                code="0x0006",
            )
        )
    )
    effect = _fields(_types(api)["OnOff.OffWithEffectRequest"])["Effect"]
    assert effect.type.name == "any" and effect.type.extras == {"matter_unresolved": "EffectIdentifierEnum"}
    assert _limits(api, "matter") == {"matter.standard_type_reference": 1}


def test_matter_ledger_rows_are_partially_mapped():
    api = _import_matter(
        _matter(_cluster('<attribute code="0" type="MissingEnum">M</attribute>', name="On/Off", code="0x0006"))
    )
    rows = _device_model_capability_rows(api)
    assert [row.source_construct for row in rows] == ["matter.standard_type_reference"]
    assert rows[0].coverage.value == "partially-mapped"
    assert _device_model_capability_rows(_import_lwm2m(_lwm2m(_object(1, "X", _item(0, "L", type_="Objlnk")))))


# ---------------------------------------------------------------------------
# Matter device types
# ---------------------------------------------------------------------------


_DEVICE = _matter(
    '<deviceType><name>MA-light</name><typeName>Matter Light</typeName><deviceId editable="false">0x0100</deviceId>'
    "<class>Simple</class><scope>Endpoint</scope><clusters>"
    '<include cluster="On/Off" client="false" server="true"><requireAttribute>ON_OFF</requireAttribute>'
    "<requireCommand>Toggle</requireCommand></include>"
    '<include cluster="Identify" server="true"/></clusters></deviceType>'
)
_ONOFF = _matter(
    _cluster(
        '<attribute code="0x0000" define="ON_OFF" type="boolean">OnOff</attribute>'
        '<command source="client" code="0x02" name="Toggle"/>',
        name="On/Off",
        code="0x0006",
    )
)


def test_matter_device_type_fileset_composes_clusters():
    fileset = IntakeFileset.from_members({"device.xml": _DEVICE, "clusters/onoff.xml": _ONOFF}, root="device.xml")
    api = MATTER.normalize(MATTER.parse_fileset(fileset, source_label="set"))
    assert api.identity.name == "Matter Light"
    device = _types(api)["MatterLight"]
    assert device.extras["matter_device_type"]["device_id"] == "0x0100"
    fields = _fields(device)
    assert fields["OnOff"].type.name == "OnOff" and fields["OnOff"].type.nullable is False
    assert fields["OnOff"].field_number == 6
    assert fields["OnOff"].extras["matter_include"]["required_attributes"] == ["ON_OFF"]
    assert fields["Identify"].type.name == "any"
    assert fields["Identify"].type.extras == {"matter_unresolved": "Identify"}
    assert _limits(api, "matter") == {"matter.external_cluster": 1}
    assert api.extras["matter"]["input"] == "fileset"


def test_matter_device_type_alone_declares_every_cluster():
    api = _import_matter(_DEVICE)
    assert _limits(api, "matter") == {"matter.external_cluster": 2}
    assert api.services == []


def test_matter_device_type_requiring_missing_member_is_refused():
    missing = _DEVICE.replace("<requireCommand>Toggle</requireCommand>", "<requireCommand>Blink</requireCommand>")
    fileset = IntakeFileset.from_members({"device.xml": missing, "onoff.xml": _ONOFF}, root="device.xml")
    assert _code(MATTER.parse_fileset, fileset) == "INPUT_REFERENCE_UNRESOLVED"


# ---------------------------------------------------------------------------
# Matter refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, code",
    [
        ("", "INPUT_EMPTY"),
        ("\ufeff<configurator/>", "INPUT_ENCODING_INVALID"),
        ('<configurator><cluster><name>T</name><attribute type="temper', "INPUT_TRUNCATED"),
        ("<configurator><cluster></configurator>", "INPUT_MALFORMED"),
        (_lwm2m(_object(1, "X", _item(0, "V"))), "FORMAT_MISMATCH"),
        (_matter('<domain name="General"/>'), "INPUT_SEMANTIC_INVALID"),
        (_matter(_cluster("<description>Nothing.</description>")), "INPUT_SEMANTIC_INVALID"),
        (_matter(_cluster('<attribute code="0">NoType</attribute>')), "INPUT_SEMANTIC_INVALID"),
        (_matter(_cluster('<attribute code="0" type="array">List</attribute>')), "INPUT_SEMANTIC_INVALID"),
        (_matter(_cluster('<attribute code="x" type="boolean">A</attribute>')), "INPUT_SEMANTIC_INVALID"),
        (_matter(_cluster('<event code="0" name="E" priority="urgent"/>')), "INPUT_SEMANTIC_INVALID"),
        (
            _matter(
                _cluster(
                    '<attribute code="0" type="boolean">A</attribute><attribute code="1" type="boolean">A</attribute>'
                )
            ),
            "INPUT_SEMANTIC_INVALID",
        ),
        (
            _matter(
                _cluster('<attribute code="0" type="boolean">A</attribute>')
                + _cluster('<attribute code="0" type="boolean">B</attribute>', name="Other")
            ),
            "INPUT_SEMANTIC_INVALID",
        ),
        (_matter("<deviceType><name>D</name><clusters/></deviceType>"), "INPUT_SEMANTIC_INVALID"),
        (_matter(_cluster('<attribute code="0" type="MissingEnum">M</attribute>')), "INPUT_REFERENCE_UNRESOLVED"),
        (
            _matter(_cluster('<command source="client" code="0" name="Go" response="GoResponse"/>')),
            "INPUT_REFERENCE_UNRESOLVED",
        ),
        (
            _matter(
                '<struct name="S"><item fieldId="0" name="X" type="Nowhere"/></struct>'
                + _cluster('<attribute code="0" type="S">A</attribute>')
            ),
            "INPUT_REFERENCE_UNRESOLVED",
        ),
    ],
)
def test_matter_refusals_carry_taxonomy_codes(text, code):
    assert _code(MATTER.parse, text, source_label="bad.xml") == code


def test_matter_normalizers_reject_foreign_documents():
    with pytest.raises(ImportSourceError):
        MATTER.normalize(object())
    with pytest.raises(ImportSourceError):
        LWM2M.normalize(object())
