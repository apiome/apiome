"""MQTT Sparkplug B import — FMT-9.2 (#5469).

Covers the payload wire reader (truncated vs malformed, unknown fields, DataSet / Template values),
the topic grammar, message-type inference, the topic-namespace description and its identity
checks, the normalizer (datatype mapping, aliases, provenance, declared limits), the adapter's
detection and binary claim, the native analysis, the binary fileset seam through archive intake,
and the coverage-ledger rows.
"""

from __future__ import annotations

import base64
import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Dict, Optional

import pytest

from app.archive_intake import unpack_archive
from app.canonical_model import ApiParadigm, OperationKind
from app.fileset import IntakeFileset
from app.import_preview_manifest import _sparkplug_capability_rows
from app.import_source import DetectionInput, ImportSourceError, get_import_source, load_builtin_import_sources
from app.import_source_pipeline import run_adapter_import_job
from app.inference_provenance import INFERRED, SYNTHESIZED, provenance_of
from app.sparkplug_analysis import analyze_sparkplug
from app.sparkplug_import_source import SparkplugImportSource
from app.sparkplug_normalizer import DATATYPE_TO_CANONICAL, SPARKPLUG_EXTRAS_KEY
from app.sparkplug_parser import (
    SparkplugParseError,
    infer_message_type,
    parse_sparkplug_bytes,
    parse_sparkplug_fileset,
    parse_sparkplug_text,
    parse_topic,
)
from app.sparkplug_payload import (
    DATATYPE_NAMES,
    SparkplugWireError,
    decode_payload,
    sniff_payload,
)

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "sparkplug"

ADAPTER = SparkplugImportSource()

# ---------------------------------------------------------------------------
# A tiny protobuf encoder, so each test states the payload it decodes.
# ---------------------------------------------------------------------------

DATATYPE = {name: number for number, name in DATATYPE_NAMES.items()}


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(number: int, wire: int) -> bytes:
    return _varint((number << 3) | wire)


def vint(number: int, value: int) -> bytes:
    return _key(number, 0) + _varint(value)


def vlen(number: int, data: bytes) -> bytes:
    return _key(number, 2) + _varint(len(data)) + data


def vstr(number: int, text: str) -> bytes:
    return vlen(number, text.encode("utf-8"))


def vdouble(number: int, value: float) -> bytes:
    return _key(number, 1) + struct.pack("<d", value)


def vfloat(number: int, value: float) -> bytes:
    return _key(number, 5) + struct.pack("<f", value)


def metric(
    name: Optional[str] = None,
    *,
    alias: Optional[int] = None,
    datatype: Optional[str] = None,
    value: bytes = b"",
    extra: bytes = b"",
) -> bytes:
    """One ``Metric`` message."""
    body = b""
    if name is not None:
        body += vstr(1, name)
    if alias is not None:
        body += vint(2, alias)
    if datatype is not None:
        body += vint(4, DATATYPE[datatype])
    return body + extra + value


def payload(*metrics: bytes, timestamp: int = 1_786_000_000_000, seq: Optional[int] = 0, extra: bytes = b"") -> bytes:
    """One ``Payload`` message."""
    data = vint(1, timestamp)
    for item in metrics:
        data += vlen(2, item)
    if seq is not None:
        data += vint(3, seq)
    return data + extra


def property_set(**values: object) -> bytes:
    """A ``PropertySet`` of string / double / boolean values."""
    keys = b"".join(vstr(1, key) for key in values)
    encoded = b""
    for value in values.values():
        if isinstance(value, bool):
            encoded += vlen(2, vint(1, DATATYPE["Boolean"]) + vint(7, int(value)))
        elif isinstance(value, float):
            encoded += vlen(2, vint(1, DATATYPE["Double"]) + vdouble(6, value))
        else:
            encoded += vlen(2, vint(1, DATATYPE["String"]) + vstr(8, str(value)))
    return keys + encoded


def _normalize(document):
    return ADAPTER.normalize(document)


def _type(api, key):
    return next(t for t in api.types if t.key == key)


def _field(type_, name):
    return next(f for f in type_.fields if f.name == name)


def _limits(api) -> Dict[str, dict]:
    return {limit["construct"]: limit for limit in api.extras[SPARKPLUG_EXTRAS_KEY]["capability_limits"]}


# ---------------------------------------------------------------------------
# Wire reader
# ---------------------------------------------------------------------------


def test_decodes_the_corpus_dbirth_with_properties_and_metadata():
    decoded = decode_payload((EXAMPLES / "03-composition-dbirth.bin").read_bytes())

    assert decoded.seq == 1
    temperature = decoded.metrics[0]
    assert (temperature.name, temperature.alias, DATATYPE_NAMES[temperature.datatype]) == (
        "Inputs/Temperature",
        1,
        "Double",
    )
    assert dict((key, item.value) for key, item in temperature.properties) == {
        "engUnit": "degC",
        "engLow": -40.0,
        "engHigh": 150.0,
        "quality": 192,
    }
    assert temperature.metadata is not None
    assert temperature.metadata.description == "Process temperature at the inlet."
    assert temperature.value == 21.5


def test_an_element_running_past_the_buffer_is_truncated():
    data = payload(metric("A", alias=1, datatype="Double", value=vdouble(13, 1.0)))
    with pytest.raises(SparkplugWireError) as raised:
        decode_payload(data[:-3])
    assert raised.value.code == "INPUT_TRUNCATED"


def test_a_fault_inside_a_complete_metric_is_malformed():
    broken = vstr(1, "name") + b"\x0f"  # field 1, wire type 7
    with pytest.raises(SparkplugWireError) as raised:
        decode_payload(payload(broken))
    assert raised.value.code == "INPUT_MALFORMED"


def test_a_nested_length_overrunning_its_parent_is_malformed_not_truncated():
    inner = vint(4, DATATYPE["Double"]) + _key(8, 2) + _varint(40) + b"\x01\x02"
    with pytest.raises(SparkplugWireError) as raised:
        decode_payload(payload(inner))
    assert raised.value.code == "INPUT_MALFORMED"


def test_a_known_field_with_the_wrong_wire_type_is_malformed():
    with pytest.raises(SparkplugWireError) as raised:
        decode_payload(payload(vstr(2, "not-an-alias")))
    assert "wire type" in str(raised.value)


def test_no_bytes_is_empty():
    with pytest.raises(SparkplugWireError) as raised:
        decode_payload(b"")
    assert raised.value.code == "INPUT_EMPTY"


def test_unknown_fields_are_skipped_and_counted():
    decoded = decode_payload(
        payload(metric("A", datatype="Int32", value=vint(10, 1), extra=vint(25, 9)), extra=vstr(9, "ext"))
    )
    assert decoded.unknown_fields == 1
    assert decoded.metrics[0].unknown_fields == 1


def test_decodes_data_set_columns_including_packed_types():
    dataset = vint(1, 2) + vstr(2, "x") + vstr(2, "label") + vlen(3, _varint(DATATYPE["Int32"]) + _varint(12))
    dataset += vlen(4, b"") + vlen(4, b"")
    decoded = decode_payload(payload(metric("Table", datatype="DataSet", value=vlen(17, dataset))))

    shape = decoded.metrics[0].dataset
    assert shape is not None
    assert [(c.name, DATATYPE_NAMES[c.datatype]) for c in shape.columns] == [("x", "Int32"), ("label", "String")]
    assert shape.row_count == 2


def test_a_data_set_whose_columns_and_types_disagree_is_malformed():
    dataset = vint(1, 2) + vstr(2, "x") + vint(3, DATATYPE["Int32"])
    with pytest.raises(SparkplugWireError):
        decode_payload(payload(metric("Table", datatype="DataSet", value=vlen(17, dataset))))


def test_sniff_accepts_payloads_and_refuses_lookalikes():
    assert sniff_payload((EXAMPLES / "02-typical-nbirth.bin").read_bytes())
    # A FileDescriptorSet's field 1 is a message, not a timestamp varint.
    assert not sniff_payload(vlen(1, vstr(1, "a.proto")))
    assert not sniff_payload(b'{"namespace": "spBv1.0"}')
    assert not sniff_payload(b"\x00\x01\x02\x03")
    assert not sniff_payload(payload())  # no metrics
    assert not sniff_payload(payload(metric("A", value=vint(10, 1)), extra=vint(7, 1)))  # extension field
    assert not sniff_payload(None)


# ---------------------------------------------------------------------------
# Topic grammar and message types
# ---------------------------------------------------------------------------


def test_parses_node_device_and_state_topics():
    node = parse_topic("spBv1.0/Plant/NBIRTH/Edge")
    assert (node.group_id, node.message_type, node.edge_node_id, node.device_id) == ("Plant", "NBIRTH", "Edge", None)
    assert node.address() == "spBv1.0/Plant/NBIRTH/Edge"

    device = parse_topic("spBv1.0/Plant/DDATA/Edge/Pump")
    assert device.device_level and device.device_id == "Pump"

    assert parse_topic("spBv1.0/STATE/Scada").host_id == "Scada"
    legacy = parse_topic("STATE/Scada")
    assert (legacy.message_type, legacy.host_id) == ("STATE", "Scada")


@pytest.mark.parametrize(
    "topic",
    [
        "spBv1.0/Plant/NDATA",  # no edge node
        "spBv1.0/Plant/DDATA/Edge",  # device message without a device
        "spBv1.0/Plant/NDATA/Edge/Pump",  # node message naming a device
        "spBv1.0/Plant/NOPE/Edge",  # unknown message type
        "spBv1.0/Plant/NDATA/+",  # wildcard
        "spBv1.0/a/NDATA/b/c/d",  # too many segments
    ],
)
def test_rejects_misshapen_topics(topic):
    with pytest.raises(SparkplugParseError) as raised:
        parse_topic(topic)
    assert raised.value.code == "INPUT_SEMANTIC_INVALID"


def test_message_type_is_inferred_from_the_file_name_then_the_metrics():
    birth = decode_payload(
        payload(metric("bdSeq", datatype="UInt64", value=vint(11, 0)), metric("A", value=vint(10, 1)))
    )
    death = decode_payload(payload(metric("bdSeq", datatype="UInt64", value=vint(11, 0))))
    data = decode_payload(payload(metric(alias=3, value=vint(10, 1))))

    assert infer_message_type(data, "line1-ddata.bin")[0] == "DDATA"
    assert infer_message_type(data, "dir/NCMD_2026.bin")[0] == "NCMD"
    # A token glued to letters is not a message type ("ddatabase").
    assert infer_message_type(data, "ddatabase.bin")[0] is None
    assert infer_message_type(birth, None)[0] == "NBIRTH"
    assert infer_message_type(death, "payload.bin")[0] == "NDEATH"
    message_type, evidence = infer_message_type(data, None)
    assert message_type is None and "could not be inferred" in evidence


# ---------------------------------------------------------------------------
# Parser entry points
# ---------------------------------------------------------------------------


def test_a_payload_without_metrics_is_semantically_invalid():
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_bytes(payload(seq=4))
    assert raised.value.code == "INPUT_SEMANTIC_INVALID"


def test_a_metric_without_name_or_alias_is_semantically_invalid():
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_bytes(payload(metric(datatype="Int32", value=vint(10, 1))))
    assert raised.value.code == "INPUT_SEMANTIC_INVALID"


def _namespace(**overrides) -> dict:
    document = {
        "namespace": "spBv1.0",
        "groupId": "Plant",
        "edgeNodeId": "Edge",
        "topics": [{"messageType": "NBIRTH", "topic": "spBv1.0/Plant/NBIRTH/Edge"}],
    }
    document.update(overrides)
    return document


def test_namespace_contradictions_are_all_reported():
    document = _namespace(
        topics=[
            {"messageType": "NDATA", "topic": "spBv1.0/Other/NDATA/Edge9"},
            {"messageType": "DDATA", "topic": "spBv1.0/Plant/NDATA/Edge"},
            {"topic": "spBv1.0/STATE/Wrong"},
        ],
        hostApplicationId="Scada",
    )
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_text(json.dumps(document))
    message = str(raised.value)
    assert raised.value.code == "INPUT_SEMANTIC_INVALID"
    assert "in group 'Other'" in message
    assert "edge node 'Edge9'" in message
    assert "listed as 'DDATA'" in message
    assert "host application 'Wrong'" in message


@pytest.mark.parametrize(
    "document, fragment",
    [
        (_namespace(topics=[]), "lists no topics"),
        (_namespace(groupId="a/b"), "groupId"),
        (_namespace(topics=[{"topic": "spBv1.0/Plant/NBIRTH/Edge"}] * 2), "listed twice"),
        (_namespace(nodeMetrics=[{"name": "A", "alias": 1}, {"name": "B", "alias": 1}]), "alias 1"),
        (_namespace(devices=[{"deviceId": "P"}, {"deviceId": "P"}]), "listed twice"),
        ({"namespace": "spAv1.0", "groupId": "g", "topics": []}, "spAv1.0"),
    ],
)
def test_namespace_description_shape_errors(document, fragment):
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_text(json.dumps(document))
    assert raised.value.code == "INPUT_SEMANTIC_INVALID"
    assert fragment in str(raised.value)


def test_json_that_is_not_sparkplug_leaves_the_code_to_the_pipeline():
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_text('{"openapi": "3.1.0"}')
    assert raised.value.code is None
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_text('syntax = "proto2";')
    assert raised.value.code is None


def test_broken_namespace_json_is_truncated_or_malformed():
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_text('{"namespace": "spBv1.0", "topics": [')
    assert raised.value.code == "INPUT_TRUNCATED"


def test_non_utf8_text_is_an_encoding_fault():
    with pytest.raises(SparkplugParseError) as raised:
        parse_sparkplug_text("\ufffd\ufffd{\x00")
    assert raised.value.code == "INPUT_ENCODING_INVALID"


# ---------------------------------------------------------------------------
# Normalizer — payloads
# ---------------------------------------------------------------------------


def test_every_scalar_datatype_maps_to_a_canonical_scalar():
    metrics = [metric(f"m/{name}", alias=index, datatype=name) for index, name in enumerate(DATATYPE_TO_CANONICAL)]
    api = _normalize(parse_sparkplug_bytes(payload(*metrics), label="x-ddata.bin"))
    record = _type(api, "DDATA")
    for name, scalar in DATATYPE_TO_CANONICAL.items():
        field = _field(record, f"m/{name}")
        assert field.type.name == scalar, name
        assert field.extras["sparkplug_datatype"] == name


def test_arrays_become_lists_of_their_element_scalar():
    api = _normalize(parse_sparkplug_bytes(payload(metric("Temps", datatype="DoubleArray")), label="a-ddata.bin"))
    field = _field(_type(api, "DDATA"), "Temps")
    assert field.type.is_list() and field.type.item.name == "double"


def test_a_payload_only_import_is_inferred_throughout():
    api = _normalize(
        parse_sparkplug_bytes((EXAMPLES / "02-typical-nbirth.bin").read_bytes(), label="02-typical-nbirth.bin")
    )

    assert api.paradigm is ApiParadigm.EVENT
    assert api.protocol == "mqtt"
    (channel,) = api.channels
    assert channel.address == "spBv1.0/{group_id}/NBIRTH/{edge_node_id}"
    assert [p.name for p in channel.parameters] == ["edge_node_id", "group_id"]
    assert channel.extras["sparkplug_topic"]["message_type"] == "NBIRTH"
    assert provenance_of(channel.extras) == INFERRED
    for parameter in channel.parameters:
        assert provenance_of(parameter.extras) == INFERRED
    (operation,) = api.services[0].operations
    assert operation.kind is OperationKind.PUBLISH
    assert operation.channel_ref == channel.key
    assert provenance_of(operation.extras) == INFERRED
    assert operation.messages[0].payload.name == "NBIRTH"
    record = _type(api, "NBIRTH")
    assert provenance_of(record.extras) == INFERRED
    assert all(provenance_of(field.extras) == INFERRED for field in record.fields)
    assert _field(record, "bdSeq").type.name == "uint64"


def test_an_alias_only_metric_keeps_a_placeholder_and_a_declared_limit():
    api = _normalize(
        parse_sparkplug_bytes((EXAMPLES / "06-typical-ddata.bin").read_bytes(), label="06-typical-ddata.bin")
    )
    names = sorted(field.name for field in _type(api, "DDATA").fields)
    assert names == ["alias:1", "alias:2", "alias:3"]
    limit = _limits(api)["sparkplug.alias_unresolved"]
    assert limit["count"] == 3
    assert "DDATA.alias:1" in limit["locations"]


def test_a_fileset_names_data_metrics_through_its_birth():
    session = EXAMPLES / "07-session-set"
    members = {path.name: path.read_bytes() for path in session.iterdir()}
    document = parse_sparkplug_fileset(
        IntakeFileset.from_members(
            {name: data.decode("utf-8", errors="replace") for name, data in members.items()},
            root="dbirth.bin",
            binary_members=members,
        )
    )
    api = _normalize(document)

    data = _type(api, "DDATA")
    assert sorted(field.name for field in data.fields) == ["Inputs/DoorOpen", "Inputs/Temperature"]
    temperature = _field(data, "Inputs/Temperature")
    assert temperature.extras["sparkplug_alias"] == 1
    assert "named through the BIRTH dbirth.bin" in temperature.extras["provenance_evidence"]
    assert "sparkplug.alias_unresolved" not in _limits(api)
    assert sorted(channel.name for channel in api.channels) == ["DBIRTH", "DDATA", "DDEATH"]


def test_a_birth_datatype_types_an_alias_only_metric_that_sent_none():
    birth = payload(metric("Speed", alias=4, datatype="Float", value=vfloat(12, 1.0)))
    data = payload(metric(alias=4, value=vfloat(12, 2.0)))
    document = parse_sparkplug_fileset(
        IntakeFileset.from_members(
            {"nbirth.bin": "", "ndata.bin": ""},
            root="nbirth.bin",
            binary_members={"nbirth.bin": birth, "ndata.bin": data},
        )
    )
    field = _field(_type(_normalize(document), "NDATA"), "Speed")
    assert field.type.name == "float"
    assert field.extras["sparkplug_datatype"] == "Float"


def test_a_metric_without_a_datatype_is_typed_from_its_value_and_says_so():
    api = _normalize(parse_sparkplug_bytes(payload(metric("Count", value=vint(11, 5))), label="n-ndata.bin"))
    field = _field(_type(api, "NDATA"), "Count")
    assert field.type.name == "integer"
    assert field.extras["sparkplug_value_field"] == "long_value"
    assert "sparkplug.datatype_inferred" in _limits(api)


def test_an_unknown_datatype_is_any_with_a_declared_limit():
    api = _normalize(parse_sparkplug_bytes(payload(metric("Odd", extra=vint(4, 99))), label="n-ndata.bin"))
    field = _field(_type(api, "NDATA"), "Odd")
    assert field.type.name == "any"
    assert field.extras["sparkplug_datatype"] == "DataType(99)"
    assert "sparkplug.datatype_unknown" in _limits(api)


def test_an_undetermined_message_type_keeps_it_as_an_address_parameter():
    api = _normalize(parse_sparkplug_bytes(payload(metric(alias=1, datatype="Int8", value=vint(10, 1)))))
    (channel,) = api.channels
    assert channel.address == "spBv1.0/{group_id}/{message_type}/{edge_node_id}"
    assert "message_type" in [parameter.name for parameter in channel.parameters]
    assert _type(api, "SparkplugPayload")
    assert "sparkplug.message_type_unknown" in _limits(api)


def test_a_data_set_metric_becomes_a_list_of_a_synthesized_row_record():
    dataset = vint(1, 2) + vstr(2, "x") + vstr(2, "label") + vint(3, DATATYPE["Int32"]) + vint(3, DATATYPE["String"])
    api = _normalize(
        parse_sparkplug_bytes(
            payload(metric("Table", datatype="DataSet", value=vlen(17, dataset))), label="t-ddata.bin"
        )
    )
    field = _field(_type(api, "DDATA"), "Table")
    assert field.type.is_list()
    row = _type(api, field.type.item.name)
    assert row.key == "DDATA.Table row"
    assert provenance_of(row.extras) == SYNTHESIZED
    assert {f.name: f.type.name for f in row.fields} == {"x": "int32", "label": "string"}


def test_template_definitions_become_records_and_instances_refer_to_them():
    definition = vlen(
        18,
        vstr(1, "1.0") + vlen(2, metric("RPM", datatype="Int32")) + vlen(3, vstr(1, "rated") + vint(2, 3)) + vint(5, 1),
    )
    instance = vlen(18, vstr(4, "Motor") + vlen(2, metric("RPM", datatype="Int32", value=vint(10, 10))))
    orphan = vlen(18, vstr(4, "Pump"))
    data = payload(
        metric("_types_/Motor", datatype="Template", value=definition),
        metric("Motor1", datatype="Template", value=instance),
        metric("Pump1", datatype="Template", value=orphan),
        metric("bdSeq", datatype="UInt64", value=vint(11, 0)),
    )
    api = _normalize(parse_sparkplug_bytes(data, label="edge-nbirth.bin"))

    motor = _type(api, "Motor")
    assert [f.name for f in motor.fields] == ["RPM"]
    assert motor.extras["sparkplug_template"]["parameters"] == [{"name": "rated", "datatype": "Int32"}]
    record = _type(api, "NBIRTH")
    assert "_types_/Motor" not in [f.name for f in record.fields]
    assert _field(record, "Motor1").type.name == "Motor"
    assert _field(record, "Pump1").type.name == "any"
    assert _field(record, "Pump1").extras["sparkplug_template_ref"] == "Pump"
    assert "sparkplug.template_unresolved" in _limits(api)


def test_skipped_extension_fields_and_body_are_declared():
    data = payload(metric("A", datatype="Int8", value=vint(10, 1)), extra=vlen(5, b"opaque") + vint(9, 1))
    api = _normalize(parse_sparkplug_bytes(data, label="a-ndata.bin"))
    limits = _limits(api)
    assert limits["sparkplug.unknown_fields"]["count"] == 1
    assert "sparkplug.payload_body" in limits


# ---------------------------------------------------------------------------
# Normalizer — namespace description
# ---------------------------------------------------------------------------


def test_the_namespace_description_is_declared_with_bindings_and_a_broker():
    api = _normalize(parse_sparkplug_text((EXAMPLES / "05-real-world-namespace-description.json").read_text()))

    assert api.identity.name == "PlantAmsterdam/Line1"
    assert all(provenance_of(channel.extras) != INFERRED for channel in api.channels)
    by_address = {op.channel_ref: op for op in api.services[0].operations}

    dbirth = by_address["spBv1.0/PlantAmsterdam/DBIRTH/Line1/Filler01"]
    assert dbirth.kind is OperationKind.PUBLISH
    assert dbirth.messages[0].payload.name == "PlantAmsterdam.Line1.Filler01"
    assert by_address["spBv1.0/PlantAmsterdam/DCMD/Line1/Filler01"].kind is OperationKind.SUBSCRIBE
    state = by_address["spBv1.0/STATE/SCADA-Primary"]
    assert state.kind is OperationKind.SUBSCRIBE
    assert state.extras["bindings"] == {"mqtt": {"qos": 0, "retain": True}}
    assert by_address["spBv1.0/PlantAmsterdam/NDEATH/Line1"].messages[0].payload is None

    channel = next(c for c in api.channels if c.address.endswith("DDATA/Line1/Capper01"))
    assert channel.extras["sparkplug_topic"] == {
        "namespace": "spBv1.0",
        "group_id": "PlantAmsterdam",
        "message_type": "DDATA",
        "edge_node_id": "Line1",
        "device_id": "Capper01",
    }
    assert channel.parameters == []

    temperature = _field(_type(api, "PlantAmsterdam.Line1.Filler01"), "Inputs/Temperature")
    assert temperature.type.name == "double"
    assert temperature.extras["sparkplug_alias"] == 1
    assert temperature.extras["sparkplug_properties"] == {"engUnit": "degC", "engLow": -40, "engHigh": 150}
    (server,) = api.servers
    assert (server.url, server.protocol) == ("ssl://mqtt.internal.example.com:8883", "mqtt")


def test_a_device_topic_without_a_catalogue_is_a_declared_limit():
    document = _namespace(topics=[{"topic": "spBv1.0/Plant/DDATA/Edge/Ghost"}])
    api = _normalize(parse_sparkplug_text(json.dumps(document)))
    assert api.services[0].operations[0].messages[0].payload is None
    assert _limits(api)["sparkplug.device_without_catalogue"]["locations"] == ["spBv1.0/Plant/DDATA/Edge/Ghost"]


def test_namespace_datatypes_are_case_insensitive():
    document = _namespace(nodeMetrics=[{"name": "A", "datatype": "double"}])
    api = _normalize(parse_sparkplug_text(json.dumps(document)))
    assert _field(_type(api, "Plant.Edge"), "A").type.name == "double"


def test_capability_rows_grade_partial_and_unparsed_limits():
    data = payload(metric(alias=2, datatype="Int8", value=vint(10, 1)), extra=vlen(5, b"x"))
    rows = {
        row.source_construct: row
        for row in _sparkplug_capability_rows(_normalize(parse_sparkplug_bytes(data, label="d-ddata.bin")))
    }
    assert rows["sparkplug.alias_unresolved"].coverage.value == "partially-mapped"
    assert rows["sparkplug.payload_body"].coverage.value == "not-parsed-by-adapter"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def test_the_adapter_is_registered_under_its_key():
    assert isinstance(get_import_source("sparkplug"), SparkplugImportSource)


def test_detect_claims_payloads_namespaces_and_markers():
    nbirth = (EXAMPLES / "02-typical-nbirth.bin").read_bytes()
    assert ADAPTER.detect(DetectionInput(data=nbirth)).confidence == pytest.approx(0.9)
    text = (EXAMPLES / "01-minimal-topic-namespace.json").read_text()
    assert ADAPTER.detect(DetectionInput(text=text)).confidence == pytest.approx(0.95)
    assert ADAPTER.detect(DetectionInput(document=json.loads(text))).confidence == pytest.approx(0.95)
    assert ADAPTER.detect(DetectionInput(text='topics: ["spBv1.0/a/NDATA/b"]')).confidence == pytest.approx(0.6)
    assert ADAPTER.detect(DetectionInput(data=b"\xff\xfe", filename="x.bin")).confidence == pytest.approx(0.5)
    # An AsyncAPI document quoting a Sparkplug topic (and some other "namespace") is weak evidence.
    asyncapi = '{"asyncapi": "3.0.0", "namespace": "x", "channels": {"a": {"address": "spBv1.0/g/NDATA/e"}}}'
    assert ADAPTER.detect(DetectionInput(text=asyncapi)).confidence == pytest.approx(0.6)
    assert not ADAPTER.detect(DetectionInput(text='{"openapi": "3.1.0"}')).matched
    assert not ADAPTER.detect(DetectionInput(text='syntax = "proto2";\nmessage Payload {}')).matched


def test_accepts_bytes_claims_by_suffix_or_decode_but_never_json():
    broken = b"\x08\x01\x12\x50"
    assert ADAPTER.accepts_bytes(broken, filename="cut.bin")
    assert ADAPTER.accepts_bytes((EXAMPLES / "02-typical-nbirth.bin").read_bytes(), filename=None)
    assert not ADAPTER.accepts_bytes(broken, filename=None)
    assert not ADAPTER.accepts_bytes(b'{"namespace": "spBv1.0"}', filename="ns.json")


def test_parse_bytes_carries_the_readers_code():
    with pytest.raises(ImportSourceError) as raised:
        ADAPTER.parse_bytes(b"\x08\x01\x12\x50", source_label="cut.bin")
    assert raised.value.code == "INPUT_TRUNCATED"


def test_normalize_and_analyze_reject_foreign_documents():
    with pytest.raises(ImportSourceError):
        ADAPTER.normalize({"not": "a document"})
    with pytest.raises(ImportSourceError):
        ADAPTER.analyze({"not": "a document"})


def test_analysis_hashes_the_payload_bytes_and_reports_metric_values():
    data = (EXAMPLES / "03-composition-dbirth.bin").read_bytes()
    document = parse_sparkplug_bytes(data, label="03-composition-dbirth.bin")
    analysis = ADAPTER.analyze(document, source=data.decode("utf-8", errors="replace"))
    same = analyze_sparkplug(document)
    assert analysis.source_hash == same.source_hash
    (root,) = analysis.tree
    assert root.kind == "payload" and root.attributes["messageType"] == "DBIRTH"
    temperature = root.children[0]
    assert temperature.name == "Inputs/Temperature"
    assert temperature.value_present is True
    assert [child.name for child in temperature.children][:2] == ["engUnit", "engLow"]


def test_analysis_describes_a_namespace_description():
    document = parse_sparkplug_text((EXAMPLES / "05-real-world-namespace-description.json").read_text())
    (root,) = analyze_sparkplug(document).tree
    assert root.kind == "namespace"
    topics = root.children[0]
    assert topics.attributes["count"] == 11
    assert [child.kind for child in root.children[1:]] == ["node", "device", "device"]


# ---------------------------------------------------------------------------
# Binary fileset seam and the pipeline
# ---------------------------------------------------------------------------


def _session_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted((EXAMPLES / "07-session-set").iterdir()):
            archive.writestr(zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0)), path.read_bytes())
        archive.writestr(zipfile.ZipInfo("README.md", date_time=(1980, 1, 1, 0, 0, 0)), "notes")
    return buffer.getvalue()


def test_archive_intake_keeps_the_exact_bytes_of_binary_members():
    unpacked = unpack_archive(_session_zip(), root_path="dbirth.bin")
    assert unpacked.root_path == "dbirth.bin"
    assert unpacked.detection.detected is not None and unpacked.detection.detected.format == "sparkplug"
    assert unpacked.binary_members["dbirth.bin"] == (EXAMPLES / "07-session-set" / "dbirth.bin").read_bytes()
    # A UTF-8 member is not repeated: its text re-encodes exactly.
    assert "README.md" not in unpacked.binary_members


def test_fileset_member_bytes_and_stray_binary_members():
    fileset = IntakeFileset.from_members({"a.bin": "x", "b.txt": "é"}, root="a.bin", binary_members={"a.bin": b"\xff"})
    assert fileset.member_bytes("a.bin") == b"\xff"
    assert fileset.member_bytes("b.txt") == "é".encode("utf-8")
    with pytest.raises(ValueError):
        IntakeFileset.from_members({"a.bin": "x"}, root="a.bin", binary_members={"other.bin": b"\x00"})


def _job_payload(data: bytes, filename: str) -> dict:
    return {
        "rest_job_id": f"sparkplug-{filename}",
        "metadata": {
            "source_kind": "sparkplug",
            "project": {"name": "Sparkplug", "slug": "sparkplug"},
            "version": {"version_id": "0.0.1"},
            "options": {"dry_run": True},
        },
        "document_base64": base64.standard_b64encode(data).decode("ascii"),
        "filename": filename,
    }


async def test_the_pipeline_imports_a_binary_payload():
    data = (EXAMPLES / "06-typical-ddata.bin").read_bytes()
    final = await run_adapter_import_job(ADAPTER, _job_payload(data, "06-typical-ddata.bin"))
    assert final.state == "completed", final.error
    assert final.summary["format"] == "sparkplug"
    assert final.summary["paradigm"] == "event"


async def test_the_pipeline_imports_a_session_archive():
    final = await run_adapter_import_job(ADAPTER, _job_payload(_session_zip(), "session.zip"))
    assert final.state == "completed", final.error


@pytest.mark.parametrize(
    "name, code",
    [
        ("negative/01-syntactic-malformed-wire-format.bin", "INPUT_MALFORMED"),
        ("negative/03-truncated-mid-metric.bin", "INPUT_TRUNCATED"),
        ("negative/05-encoding-utf16.json", "INPUT_ENCODING_INVALID"),
    ],
)
async def test_the_pipeline_reports_broken_inputs_with_their_code(name: str, code: str):
    path = EXAMPLES / name
    final = await run_adapter_import_job(ADAPTER, _job_payload(path.read_bytes(), path.name))
    assert final.state == "failed"
    assert final.error is not None and final.error.code == code
