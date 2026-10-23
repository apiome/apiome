"""ROS 2 interface import — FMT-9.3 (#5470).

Covers the line grammar (primitives, bounded strings, fixed / bounded / unbounded arrays,
constants, defaults, comments), the three interface kinds and their canonical projection
(records, request/response operations, goal operation + feedback channel), package filesets with
cross-package resolution, the declared-unresolved versus refused reference rule, every refusal's
taxonomy code, detection, the coverage-ledger rows and the registry wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, MessageRole, OperationKind, TypeKind
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.format_version_coverage import version_coverage_for
from app.import_preview_manifest import _ros2_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.inference_provenance import INFERENCE_BASED_ADAPTERS
from app.ros2_import_source import Ros2ImportSource
from app.ros2_normalizer import LIMIT_DETAILS, PRIMITIVE_TO_CANONICAL
from app.ros2_parser import (
    STANDARD_INTERFACE_PACKAGES,
    Ros2ParseError,
    has_interface_lines,
    interface_name_from_path,
    parse_ros2_fileset,
    parse_ros2_text,
    parse_type,
)

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "ros2"

PACKAGE_XML = """<?xml version="1.0"?>
<package format="3">
  <name>{name}</name>
  <version>0.3.1</version>
  <description>Test interfaces.</description>
  <maintainer email="a@example.com">A</maintainer>
  <license>Apache-2.0</license>
  <buildtool_depend>rosidl_default_generators</buildtool_depend>
  {depends}
  <member_of_group>rosidl_interface_packages</member_of_group>
</package>
"""


def _adapter() -> Ros2ImportSource:
    return Ros2ImportSource()


def _import(text: str, label: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=label))


def _import_fileset(members: Dict[str, str], root: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root=root)))


def _code(text: str, label: str) -> str:
    with pytest.raises(ImportSourceError) as info:
        _adapter().parse(text, source_label=label)
    return str(info.value.code)


def _field(api: CanonicalApi, type_key: str, name: str):
    type_ = api.type_by_key(type_key)
    assert type_ is not None, f"{type_key} not in {[t.key for t in api.types]}"
    return next(f for f in type_.fields if f.name == name)


def _limits(api: CanonicalApi) -> Dict[str, int]:
    return {limit["construct"]: limit["count"] for limit in api.extras["ros2"]["capability_limits"]}


# ===========================================================================
# Type grammar
# ===========================================================================


class TestTypeGrammar:
    def test_primitive(self) -> None:
        type_ = parse_type("float64")
        assert type_.is_primitive and not type_.is_array and type_.reference is None

    def test_bounded_string(self) -> None:
        type_ = parse_type("string<=32")
        assert type_.base == "string" and type_.string_bound == 32

    @pytest.mark.parametrize(
        ("text", "array", "size"),
        [("int32[]", "unbounded", None), ("int32[3]", "fixed", 3), ("int32[<=10]", "bounded", 10)],
    )
    def test_arrays(self, text: str, array: str, size) -> None:
        type_ = parse_type(text)
        assert (type_.array, type_.array_size) == (array, size)

    def test_bounded_array_of_bounded_strings(self) -> None:
        type_ = parse_type("string<=8[<=4]")
        assert (type_.string_bound, type_.array, type_.array_size) == (8, "bounded", 4)

    @pytest.mark.parametrize("text", ["geometry_msgs/Pose", "geometry_msgs/msg/Pose"])
    def test_qualified_reference(self, text: str) -> None:
        type_ = parse_type(text)
        assert (type_.package, type_.base, type_.reference) == ("geometry_msgs", "Pose", "geometry_msgs/Pose")

    def test_bare_reference(self) -> None:
        type_ = parse_type("LoadCell[]")
        assert type_.package is None and type_.reference == "LoadCell" and not type_.is_primitive

    @pytest.mark.parametrize(
        "text",
        ["message", "int32<=4", "Pose<=3", "Bad_Pkg/Pose", "pkg/pose", "int32[0]", "string<=0", "int32[<=]"],
    )
    def test_rejects(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_type(text)


class TestInterfaceNames:
    @pytest.mark.parametrize(
        ("path", "name"),
        [
            ("msg/LoadCell.msg", "LoadCell"),
            ("05-real-world-navigate-to-pose.action", "RealWorldNavigateToPose"),
            ("battery_state.msg", "BatteryState"),
            (None, None),
        ],
    )
    def test_from_path(self, path, name) -> None:
        assert interface_name_from_path(path) == name


# ===========================================================================
# Messages
# ===========================================================================


class TestMessage:
    def test_minimal(self) -> None:
        api = _import("string id\nint64 seen_at\n", "Ping.msg")
        assert api.paradigm is ApiParadigm.RPC and api.format == "ros2" and api.protocol == "ros2"
        record = api.type_by_key("Ping")
        assert record is not None and record.kind is TypeKind.RECORD
        assert [(f.name, f.type.name, f.type.nullable) for f in record.fields] == [
            ("id", "string", False),
            ("seen_at", "int64", False),
        ]
        assert api.services == [] and api.channels == []

    def test_every_primitive_maps_to_a_canonical_scalar(self) -> None:
        text = "\n".join(f"{primitive} f_{index}" for index, primitive in enumerate(sorted(PRIMITIVE_TO_CANONICAL)))
        api = _import(text, "All.msg")
        record = api.type_by_key("All")
        assert record is not None
        written = {f.extras["ros2_type"]: f.type.name for f in record.fields}
        assert written == PRIMITIVE_TO_CANONICAL
        assert _limits(api) == {"ros2.wide_string": 1}

    def test_bounds_map_to_constraints(self) -> None:
        api = _import(
            "string<=32 label\nfloat64[3] xyz\nfloat64[<=10] samples\nstring<=8[<=4] tags\nint8[] raw\n",
            "Bounds.msg",
        )
        label = _field(api, "Bounds", "label")
        assert label.constraints is not None and label.constraints.max_length == 32
        xyz = _field(api, "Bounds", "xyz")
        assert xyz.type.is_list() and xyz.type.item.name == "double"
        assert (xyz.constraints.min_items, xyz.constraints.max_items) == (3, 3)
        samples = _field(api, "Bounds", "samples")
        assert (samples.constraints.min_items, samples.constraints.max_items) == (None, 10)
        tags = _field(api, "Bounds", "tags")
        assert tags.constraints.max_items == 4 and tags.constraints.extras == {"item_max_length": 8}
        assert tags.constraints.max_length is None
        assert _field(api, "Bounds", "raw").constraints is None

    def test_defaults_are_parsed_values(self) -> None:
        api = _import(
            'int32 count 42\nfloat32 speed 0.55\nbool on false\nstring name "hi # there"\n'
            "bool[3] mask [true, false, 1]\nstring[] words ['a,b', \"c\"]\nint8 hex 0x10\n",
            "Defaults.msg",
        )
        values = {f.name: f.default for f in api.type_by_key("Defaults").fields}
        assert values == {
            "count": 42,
            "speed": 0.55,
            "on": False,
            "name": "hi # there",
            "mask": [True, False, True],
            "words": ["a,b", "c"],
            "hex": 16,
        }
        assert _field(api, "Defaults", "count").extras["ros2_default"] == "42"

    def test_constants_become_an_enum(self) -> None:
        api = _import(
            'uint8 STATE_EMPTY=0\nuint8 STATE_FULL = 2  # full\nstring GREETING="hello"\nuint8 state\n',
            "Bin.msg",
        )
        record = api.type_by_key("Bin")
        assert record.extras["ros2_constants"] == "Bin_Constants"
        enum = api.type_by_key("Bin_Constants")
        assert enum.kind is TypeKind.ENUM
        assert [(v.name, v.value) for v in enum.enum_values] == [
            ("STATE_EMPTY", 0),
            ("STATE_FULL", 2),
            ("GREETING", "hello"),
        ]
        assert enum.enum_values[1].description == "full"
        assert enum.extras["provenance"] == "synthesized"

    def test_comments_document_the_interface_and_fields(self) -> None:
        api = _import(
            "# Battery state.\n\n# Volts.\nfloat32 voltage\nfloat32 current  # Amperes\n"
            "# ------------- section\nbool present\n",
            "Battery.msg",
        )
        record = api.type_by_key("Battery")
        assert record.description == "Battery state."
        described = {f.name: f.description for f in record.fields}
        assert described == {"voltage": "Volts.", "current": "Amperes", "present": None}

    def test_paste_without_a_name(self) -> None:
        document = parse_ros2_text("int32 a\n")
        assert document.interfaces[0].kind == "msg" and document.interfaces[0].name == "Message"

    def test_paste_kind_follows_section_count(self) -> None:
        assert parse_ros2_text("int32 a\n---\nint32 b\n").interfaces[0].kind == "srv"
        assert parse_ros2_text("int32 a\n---\nint32 b\n---\nint32 c\n").interfaces[0].kind == "action"


# ===========================================================================
# Services and actions
# ===========================================================================


class TestService:
    def test_request_response_operation(self) -> None:
        api = _import("string map_name\nbool overwrite false\n---\nuint8 OK=0\nuint8 result\n", "SaveMap.srv")
        request = api.type_by_key("SaveMap_Request")
        response = api.type_by_key("SaveMap_Response")
        assert request is not None and response is not None
        assert response.extras["ros2_constants"] == "SaveMap_Response_Constants"
        (service,) = api.services
        (operation,) = service.operations
        assert operation.kind is OperationKind.REQUEST_RESPONSE and operation.key == "SaveMap.SaveMap"
        assert [(m.role, m.payload.name) for m in operation.messages] == [
            (MessageRole.REQUEST, "SaveMap_Request"),
            (MessageRole.RESPONSE, "SaveMap_Response"),
        ]

    def test_empty_request_is_allowed(self) -> None:
        api = _import("---\nbool success\nstring message\n", "Trigger.srv")
        assert api.type_by_key("Trigger_Request").fields == []


class TestAction:
    def test_goal_operation_and_feedback_channel(self) -> None:
        api = _import(
            "float32 target\n---\nbool done\n---\nfloat32 progress\n",
            "Lift.action",
        )
        assert {t.key for t in api.types} == {"Lift_Goal", "Lift_Result", "Lift_Feedback"}
        (channel,) = api.channels
        assert channel.address == "Lift/_action/feedback" and channel.protocol == "ros2"
        assert channel.extras["provenance"] == "synthesized"
        operations = {op.key: op for op in api.operations()}
        goal = operations["Lift.Lift"]
        assert goal.kind is OperationKind.REQUEST_RESPONSE
        assert [m.payload.name for m in goal.messages] == ["Lift_Goal", "Lift_Result"]
        assert goal.extras["ros2_feedback_channel"] == channel.key
        feedback = operations["Lift.Lift.feedback"]
        assert feedback.kind is OperationKind.SUBSCRIBE and feedback.channel_ref == channel.key
        (message,) = feedback.messages
        assert message.role is MessageRole.EVENT and message.payload.name == "Lift_Feedback"


# ===========================================================================
# References
# ===========================================================================


class TestReferences:
    def test_standard_package_is_a_declared_external_reference(self) -> None:
        api = _import("std_msgs/Header header\ngeometry_msgs/msg/Pose[] poses\n", "Track.msg")
        header = _field(api, "Track", "header")
        assert header.type.name == "any" and header.type.extras == {"ros2_unresolved": "std_msgs/msg/Header"}
        poses = _field(api, "Track", "poses")
        assert poses.type.item.extras == {"ros2_unresolved": "geometry_msgs/msg/Pose"}
        assert _limits(api) == {"ros2.external_reference": 2}

    def test_bare_name_in_a_single_file_is_a_declared_sibling_reference(self) -> None:
        api = _import("LoadCell cell\n", "Pallet.msg")
        assert _field(api, "Pallet", "cell").type.extras == {"ros2_unresolved": "LoadCell"}
        assert _limits(api) == {"ros2.sibling_reference": 1}

    def test_unknown_package_is_refused(self) -> None:
        with pytest.raises(ImportSourceError) as info:
            _adapter().parse("warehouse_msgs/DockSpec spec\n", source_label="Dock.msg")
        assert info.value.code == "INPUT_REFERENCE_UNRESOLVED"
        assert "warehouse_msgs/DockSpec" in str(info.value)

    def test_package_set_resolves_bare_and_qualified_names(self) -> None:
        api = _import_fileset(
            {
                "pallets/package.xml": PACKAGE_XML.format(name="pallets", depends="<depend>std_msgs</depend>"),
                "pallets/msg/LoadCell.msg": "float32 mass_kg\n",
                "pallets/msg/Pallet.msg": "std_msgs/Header header\nLoadCell[] cells\npallets/LoadCell spare\n",
                "pallets/srv/Weigh.srv": "string id\n---\nPallet pallet\n",
            },
            root="pallets/package.xml",
        )
        assert api.identity.name == "pallets" and api.identity.namespace == "pallets" and api.version == "0.3.1"
        assert _field(api, "pallets.Pallet", "cells").type.item.name == "pallets.LoadCell"
        assert _field(api, "pallets.Pallet", "spare").type.name == "pallets.LoadCell"
        assert _field(api, "pallets.Weigh_Response", "pallet").type.name == "pallets.Pallet"
        assert api.type_by_key("pallets.Pallet").extras["ros2_interface"]["full_name"] == "pallets/msg/Pallet"
        (service,) = api.services
        assert service.key == "pallets" and [op.key for op in service.operations] == ["pallets.Weigh"]
        assert _limits(api) == {"ros2.external_reference": 1}

    def test_declared_dependency_allows_a_nonstandard_package(self) -> None:
        members = {
            "package.xml": PACKAGE_XML.format(name="dock", depends="<depend>warehouse_msgs</depend>"),
            "msg/Dock.msg": "warehouse_msgs/DockSpec spec\n",
        }
        api = _import_fileset(members, root="package.xml")
        assert _field(api, "dock.Dock", "spec").type.extras == {"ros2_unresolved": "warehouse_msgs/msg/DockSpec"}

    def test_cross_package_fileset_resolves_both_packages(self) -> None:
        api = _import_fileset(
            {
                "base_msgs/package.xml": PACKAGE_XML.format(name="base_msgs", depends=""),
                "base_msgs/msg/Point.msg": "float64 x\nfloat64 y\n",
                "robot_msgs/package.xml": PACKAGE_XML.format(name="robot_msgs", depends=""),
                "robot_msgs/msg/Path.msg": "base_msgs/Point[] points\n",
            },
            root="robot_msgs/package.xml",
        )
        assert _field(api, "robot_msgs.Path", "points").type.item.name == "base_msgs.Point"
        assert "ros2.external_reference" not in _limits(api)

    def test_missing_type_of_a_package_in_the_import_is_refused(self) -> None:
        fileset = IntakeFileset.from_members(
            {
                "base_msgs/package.xml": PACKAGE_XML.format(name="base_msgs", depends=""),
                "base_msgs/msg/Point.msg": "float64 x\n",
                "robot_msgs/package.xml": PACKAGE_XML.format(name="robot_msgs", depends=""),
                "robot_msgs/msg/Path.msg": "base_msgs/Pose[] points\n",
            },
            root="robot_msgs/package.xml",
        )
        with pytest.raises(Ros2ParseError) as info:
            parse_ros2_fileset(fileset)
        assert info.value.code == "INPUT_REFERENCE_UNRESOLVED"

    def test_missing_sibling_in_a_fileset_is_refused(self) -> None:
        fileset = IntakeFileset.from_members(
            {"package.xml": PACKAGE_XML.format(name="p", depends=""), "msg/A.msg": "Missing m\n"},
            root="package.xml",
        )
        with pytest.raises(Ros2ParseError) as info:
            parse_ros2_fileset(fileset)
        assert info.value.code == "INPUT_REFERENCE_UNRESOLVED" and "Missing.msg" in str(info.value)

    def test_fileset_without_manifest(self) -> None:
        api = _import_fileset({"A.msg": "B b\n", "B.msg": "int32 x\n"}, root="A.msg")
        assert _field(api, "A", "b").type.name == "B"

    def test_standard_packages_include_the_core_set(self) -> None:
        assert {"std_msgs", "geometry_msgs", "builtin_interfaces", "sensor_msgs"} <= STANDARD_INTERFACE_PACKAGES


# ===========================================================================
# Refusals
# ===========================================================================


class TestRefusals:
    @pytest.mark.parametrize(
        ("text", "label", "code"),
        [
            ("float32\n", "A.msg", "FORMAT_MISMATCH"),
            ("int32 ok\nfloat32\n", "A.msg", "INPUT_MALFORMED"),
            ("int32 count 42 extra\nint32 ok\n", "A.msg", "INPUT_MALFORMED"),
            ("uint8 x 300\nint32 ok\n", "A.msg", "INPUT_MALFORMED"),
            ("geometry_msgs/Pose pose 1\nint32 ok\n", "A.msg", "INPUT_MALFORMED"),
            ("int32 CamelName\nint32 ok\n", "A.msg", "INPUT_MALFORMED"),
            ("int32 lower=1\nint32 ok\n", "A.msg", "INPUT_MALFORMED"),
            ("int32[] ARR=1\nint32 ok\n", "A.msg", "INPUT_MALFORMED"),
            ("int32[3] a [1, 2]\nint32 ok\n", "A.msg", "INPUT_MALFORMED"),
            ('string<=2 a "long"\nint32 ok\n', "A.msg", "INPUT_MALFORMED"),
            ("int32 a\n---\nint32 b\n", "A.msg", "INPUT_MALFORMED"),
            ("int32 a\n---\nint32 b\n---\nint32 c\n---\nint32 d\n", None, "INPUT_MALFORMED"),
            ("int32 a\n", "A.srv", "INPUT_TRUNCATED"),
            ("int32 a\n---\nint32 b\n", "A.action", "INPUT_TRUNCATED"),
            ("# only a comment\n", "A.msg", "INPUT_SEMANTIC_INVALID"),
            ("int32 a\nint32 a\n", "A.msg", "INPUT_SEMANTIC_INVALID"),
            ("﻿int32 a\n", "A.msg", "INPUT_ENCODING_INVALID"),
            ("i\x00n\x00t\x00", "A.msg", "INPUT_ENCODING_INVALID"),
            ("   \n", "A.msg", "INPUT_EMPTY"),
            ('syntax = "proto3";\nmessage A {\n  int32 a = 1;\n}\n', "a.proto", "FORMAT_MISMATCH"),
        ],
    )
    def test_codes(self, text: str, label, code: str) -> None:
        assert _code(text, label) == code

    def test_lone_package_manifest_is_semantically_invalid(self) -> None:
        assert _code(PACKAGE_XML.format(name="p", depends=""), "package.xml") == "INPUT_SEMANTIC_INVALID"

    def test_fileset_with_no_interfaces(self) -> None:
        fileset = IntakeFileset.from_members(
            {"package.xml": PACKAGE_XML.format(name="p", depends="")}, root="package.xml"
        )
        with pytest.raises(Ros2ParseError) as info:
            parse_ros2_fileset(fileset)
        assert info.value.code == "INPUT_SEMANTIC_INVALID"

    def test_fileset_with_a_duplicate_interface(self) -> None:
        fileset = IntakeFileset.from_members({"a/A.msg": "int32 x\n", "b/A.msg": "int32 y\n"}, root="a/A.msg")
        with pytest.raises(Ros2ParseError) as info:
            parse_ros2_fileset(fileset)
        assert info.value.code == "INPUT_SEMANTIC_INVALID"

    def test_malformed_manifest(self) -> None:
        fileset = IntakeFileset.from_members({"package.xml": "<package><name>", "A.msg": "int32 x\n"}, root="A.msg")
        with pytest.raises(Ros2ParseError) as info:
            parse_ros2_fileset(fileset)
        assert info.value.code == "INPUT_MALFORMED"

    def test_normalize_rejects_other_inputs(self) -> None:
        with pytest.raises(ImportSourceError):
            _adapter().normalize({"not": "a document"})


# ===========================================================================
# Detection and wiring
# ===========================================================================


class TestDetection:
    def test_named_interface(self) -> None:
        result = _adapter().detect(DetectionInput(text="int32 a\n", filename="A.msg"))
        assert result.confidence >= 0.9 and result.format == "ros2"

    def test_unnamed_interface_text(self) -> None:
        result = _adapter().detect(DetectionInput(text="uint8 OK=0\n---\nstring msg\n"))
        assert 0.85 <= result.confidence < 0.9

    def test_partially_readable_named_file_is_claimed_weakly(self) -> None:
        result = _adapter().detect(DetectionInput(text="int32 a\nfloat32\n", filename="A.msg"))
        assert result.confidence == pytest.approx(0.6)

    def test_package_manifest(self) -> None:
        text = PACKAGE_XML.format(name="p", depends="")
        assert _adapter().detect(DetectionInput(text=text, filename="package.xml")).confidence >= 0.85

    @pytest.mark.parametrize(
        "text",
        ['syntax = "proto3";\nmessage A { int32 a = 1; }\n', "openapi: 3.1.0\ninfo:\n  title: x\n", "", "<package/>"],
    )
    def test_other_text_is_not_claimed(self, text: str) -> None:
        assert not _adapter().detect(DetectionInput(text=text)).matched

    def test_line_counter(self) -> None:
        assert has_interface_lines("# c\nint32 a\n---\nnope\n") == (1, 1)


class TestWiring:
    def test_registered(self) -> None:
        adapter = get_import_source("ros2")
        assert isinstance(adapter, Ros2ImportSource)
        assert ".msg" in adapter.file_extensions and ".action" in adapter.file_extensions

    def test_capability_seed_lists_every_limit(self) -> None:
        capability = capability_for("ros2")
        assert capability is not None
        assert sorted(capability.canonical_projection.dropped_constructs) == sorted(LIMIT_DETAILS)

    def test_version_coverage(self) -> None:
        assert version_coverage_for("ros2") is not None

    def test_inference_provenance_entry(self) -> None:
        assert "ros2" in INFERENCE_BASED_ADAPTERS

    def test_ledger_rows_are_partial(self) -> None:
        api = _import("std_msgs/Header header\nwstring w\n", "L.msg")
        rows = _ros2_capability_rows(api)
        assert {row.source_construct for row in rows} == {"ros2.external_reference", "ros2.wide_string"}
        assert all(row.coverage.value == "partially-mapped" and row.document_scoped for row in rows)


# ===========================================================================
# Corpus
# ===========================================================================


class TestCorpus:
    def test_package_set(self) -> None:
        members = {path.name: path.read_text(encoding="utf-8") for path in (EXAMPLES / "03-package-set").iterdir()}
        api = _import_fileset(members, root="package.xml")
        assert api.identity.name == "example_interfaces_extra"
        status = _field(api, "example_interfaces_extra.PalletStatus", "load_cells")
        assert status.type.item.name == "example_interfaces_extra.LoadCell"

    def test_navigate_to_pose(self) -> None:
        path = EXAMPLES / "05-real-world-navigate-to-pose.action"
        api = _import(path.read_text(encoding="utf-8"), path.name)
        assert _field(api, "RealWorldNavigateToPose_Goal", "max_speed").default == pytest.approx(0.55)
        assert api.type_by_key("RealWorldNavigateToPose_Result_Constants") is not None
        assert len(api.channels) == 1

    def test_unresolvable_reference_negative(self) -> None:
        path = EXAMPLES / "negative" / "06-unresolvable-type-reference.msg"
        assert _code(path.read_text(encoding="utf-8"), path.name) == "INPUT_REFERENCE_UNRESOLVED"
