"""ROS 2 interfaces → canonical model normalizer — FMT-9.3 (#5470).

Maps a parsed :class:`~app.ros2_parser.Ros2Document` onto the **rpc** paradigm:

.. code-block:: text

    LoadCell.msg              → RECORD   <pkg>.LoadCell
    LiftPallet.srv            → RECORD   <pkg>.LiftPallet_Request, <pkg>.LiftPallet_Response
                                operation <service>.LiftPallet (request_response)
    NavigateToPose.action     → RECORD   <pkg>.NavigateToPose_Goal / _Result / _Feedback
                                operation <service>.NavigateToPose (goal → result)
                                operation <service>.NavigateToPose.feedback (subscribe)
                                channel   NavigateToPose/_action/feedback
    uint8 STATE_EMPTY=0 …     → ENUM     <record>_Constants, one member per constant

The ``_Request`` / ``_Response`` / ``_Goal`` / ``_Result`` / ``_Feedback`` names are the ones the
ROS 2 code generators give those structures. Type keys are package-qualified (``pkg.Name``) when a
``package.xml`` names the package. Every service and action of the import is grouped under one
service named after the package (or the single interface).

Fields map ROS 2 primitives to canonical scalars (:data:`PRIMITIVE_TO_CANONICAL`); every field is
present on the wire, so no reference is nullable. Arrays are lists — a fixed array pins
``min_items`` and ``max_items``, a bounded one ``max_items`` — and a bounded string sets
``max_length`` (for an array of bounded strings, ``item_max_length`` in the constraints' extras).
Defaults are kept as parsed values. A message reference resolved in the import names its type; one
outside the import keeps the ``any`` type and names the referenced message in
``extras['ros2_unresolved']``, and the coverage ledger counts it.

The written type of every field and constant is kept in ``extras['ros2_type']``; the declared limits
are in ``extras['ros2']['capability_limits']``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .inference_provenance import SYNTHESIZED, provenance_extras
from .normalizer import Keys, Normalizer, normalize_ordering
from .ros2_parser import (
    FORMAT_KEY,
    Ros2Constant,
    Ros2Document,
    Ros2Field,
    Ros2Interface,
    Ros2Section,
    Ros2Type,
    raw_record,
)
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "LIMIT_DETAILS",
    "PARTIAL_LIMITS",
    "PRIMITIVE_TO_CANONICAL",
    "ROS2_EXTRAS_KEY",
    "Ros2Normalizer",
    "section_type_name",
]

#: Root extras key of the projection record.
ROS2_EXTRAS_KEY = "ros2"

#: The transport the canonical model names for ROS 2 interfaces.
ROS2_PROTOCOL = "ros2"

#: ROS 2 primitive → canonical scalar name.
PRIMITIVE_TO_CANONICAL: Dict[str, str] = {
    "bool": "boolean",
    "byte": "uint8",
    "char": "uint8",
    "int8": "int8",
    "uint8": "uint8",
    "int16": "int16",
    "uint16": "uint16",
    "int32": "int32",
    "uint32": "uint32",
    "int64": "int64",
    "uint64": "uint64",
    "float32": "float",
    "float64": "double",
    "string": "string",
    "wstring": "string",
}

#: The declared-limit vocabulary (stable keys → reviewed sentence).
LIMIT_DETAILS: Dict[str, str] = {
    "ros2.external_reference": (
        "A field references a message of another package that is not in the import (a standard "
        "ROS 2 interface package, or a dependency package.xml declares). The field keeps the any "
        "type and names the message in extras['ros2_unresolved']; import that package beside this "
        "one to resolve it."
    ),
    "ros2.sibling_reference": (
        "A field names a message of its own package by bare name, but the file was imported on its "
        "own, without the package's other interfaces. The field keeps the any type and names the "
        "message in extras['ros2_unresolved']; import the whole package to resolve it."
    ),
    "ros2.wide_string": (
        "A wstring (UTF-16 on the wire) is projected to the canonical string; its wire encoding "
        "is kept in extras['ros2_type']."
    ),
}

#: Limits whose construct is still modelled, with only a detail lost — every ROS 2 limit is.
PARTIAL_LIMITS = frozenset(LIMIT_DETAILS)

#: Section role → suffix of the structure the ROS 2 generators name for it.
_SECTION_SUFFIXES: Dict[str, str] = {
    "message": "",
    "request": "_Request",
    "response": "_Response",
    "goal": "_Goal",
    "result": "_Result",
    "feedback": "_Feedback",
}

_CONSTANTS_EVIDENCE = "ROS 2 declares constants inline on the interface; the enum that groups them is named by Apiome."
_FEEDBACK_EVIDENCE = (
    "An action's feedback is published on <action name>/_action/feedback; the action's runtime "
    "name is not part of the interface, so the interface name stands in for it."
)


def section_type_name(interface: Ros2Interface, section: Ros2Section) -> str:
    """The record name of one section (``LiftPallet`` + request → ``LiftPallet_Request``)."""
    return f"{interface.name}{_SECTION_SUFFIXES[section.role]}"


class _Builder:
    """Accumulates types and limits while one document is normalized."""

    def __init__(self, document: Ros2Document) -> None:
        self.document = document
        self.types: Dict[str, Type] = {}
        self.limits = LimitRecorder(details=LIMIT_DETAILS)

    # --- references ----------------------------------------------------------

    def _element_ref(self, type_: Ros2Type, owner: Ros2Interface, location: str) -> TypeRef:
        """The reference of one element (no array wrapper)."""
        if type_.is_primitive:
            if type_.base == "wstring":
                self.limits.record("ros2.wide_string", location=location)
            return TypeRef(name=PRIMITIVE_TO_CANONICAL[type_.base], nullable=False)
        reference = self.document.resolve(type_, owner)
        assert reference is not None
        if reference.status == "resolved":
            return TypeRef(name=Keys.type(reference.name, reference.package), nullable=False)
        limit = "ros2.external_reference" if reference.status == "external" else "ros2.sibling_reference"
        self.limits.record(limit, location=location)
        target = f"{reference.package}/msg/{reference.name}" if reference.package else reference.name
        return TypeRef(name="any", nullable=False, extras={"ros2_unresolved": target})

    def type_ref(self, type_: Ros2Type, owner: Ros2Interface, location: str) -> TypeRef:
        """The canonical reference of a field type, wrapped in a list for an array."""
        element = self._element_ref(type_, owner, location)
        if type_.is_array:
            return TypeRef(item=element, nullable=False)
        return element

    @staticmethod
    def constraints(type_: Ros2Type) -> Optional[Constraints]:
        """The canonical constraints a bounded string or a sized array carries."""
        values: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        if type_.array == "fixed":
            values["min_items"] = type_.array_size
            values["max_items"] = type_.array_size
        elif type_.array == "bounded":
            values["max_items"] = type_.array_size
        if type_.string_bound is not None:
            if type_.is_array:
                extras["item_max_length"] = type_.string_bound
            else:
                values["max_length"] = type_.string_bound
        if not values and not extras:
            return None
        return Constraints(**values, extras=extras)

    # --- types ---------------------------------------------------------------

    def field(self, member: Ros2Field, owner: Ros2Interface, type_key: str) -> CanonicalField:
        """One field of a section record."""
        key = Keys.field(type_key, member.name)
        extras: Dict[str, Any] = {"ros2_type": member.type.text}
        if member.default_text is not None:
            extras["ros2_default"] = member.default_text
        return CanonicalField(
            key=key,
            name=member.name,
            type=self.type_ref(member.type, owner, key),
            default=member.default,
            constraints=self.constraints(member.type),
            description=member.description,
            extras=extras,
        )

    def constants_enum(
        self, constants: Tuple[Ros2Constant, ...], record_key: str, record_name: str, namespace: Optional[str]
    ) -> str:
        """Define the enum that groups a section's constants and return its key."""
        name = f"{record_name}_Constants"
        key = Keys.type(name, namespace)
        values = [
            EnumValue(
                key=Keys.enum_value(key, constant.name),
                name=constant.name,
                value=constant.value,
                description=constant.description,
                extras={"ros2_type": constant.type.text, "ros2_value": constant.value_text},
            )
            for constant in constants
        ]
        self.types[key] = Type(
            key=key,
            name=name,
            kind=TypeKind.ENUM,
            namespace=namespace,
            description=f"Constants declared on {record_name}.",
            enum_values=values,
            extras={"ros2_constants_of": record_key, **provenance_extras(SYNTHESIZED, _CONSTANTS_EVIDENCE)},
        )
        return key

    def section_record(self, interface: Ros2Interface, section: Ros2Section) -> str:
        """Define the record of one section (and its constants enum) and return the record key."""
        name = section_type_name(interface, section)
        key = Keys.type(name, interface.package)
        extras: Dict[str, Any] = {
            "ros2_interface": {
                "kind": interface.kind,
                "full_name": interface.full_name,
                "section": section.role,
                **({"file": interface.path} if interface.path else {}),
            }
        }
        if section.constants:
            extras["ros2_constants"] = self.constants_enum(section.constants, key, name, interface.package)
        description = interface.description if section.role in ("message", "request", "goal") else None
        self.types[key] = Type(
            key=key,
            name=name,
            kind=TypeKind.RECORD,
            namespace=interface.package,
            description=description,
            fields=[self.field(member, interface, key) for member in section.fields],
            extras=extras,
        )
        return key


def _service_operations(builder: _Builder, interface: Ros2Interface, service_key: str) -> List[Operation]:
    """The request/response operation of a service."""
    request = builder.section_record(interface, interface.sections[0])
    response = builder.section_record(interface, interface.sections[1])
    key = Keys.operation_rpc(service_key, interface.name)
    return [
        Operation(
            key=key,
            name=interface.name,
            kind=OperationKind.REQUEST_RESPONSE,
            description=interface.description,
            messages=[
                Message(
                    key=Keys.request_message(key),
                    role=MessageRole.REQUEST,
                    required=True,
                    payload=TypeRef(name=request, nullable=False),
                ),
                Message(
                    key=f"{key}#response", role=MessageRole.RESPONSE, payload=TypeRef(name=response, nullable=False)
                ),
            ],
            extras={"ros2_interface": {"kind": "srv", "full_name": interface.full_name}},
        )
    ]


def _action_operations(
    builder: _Builder, interface: Ros2Interface, service_key: str
) -> Tuple[List[Operation], Channel]:
    """The goal operation and the feedback subscription (with its channel) of an action."""
    goal = builder.section_record(interface, interface.sections[0])
    result = builder.section_record(interface, interface.sections[1])
    feedback = builder.section_record(interface, interface.sections[2])
    address = f"{interface.name}/_action/feedback"
    channel = Channel(
        key=Keys.channel(address),
        address=address,
        name=f"{interface.name} feedback",
        description=f"Feedback the {interface.name} action server publishes while a goal runs.",
        protocol=ROS2_PROTOCOL,
        extras={
            "ros2_action": interface.full_name,
            **provenance_extras(SYNTHESIZED, _FEEDBACK_EVIDENCE),
        },
    )
    goal_key = Keys.operation_rpc(service_key, interface.name)
    feedback_key = f"{goal_key}.feedback"
    operations = [
        Operation(
            key=goal_key,
            name=interface.name,
            kind=OperationKind.REQUEST_RESPONSE,
            description=interface.description,
            messages=[
                Message(
                    key=Keys.request_message(goal_key),
                    role=MessageRole.REQUEST,
                    required=True,
                    payload=TypeRef(name=goal, nullable=False),
                ),
                Message(
                    key=f"{goal_key}#response", role=MessageRole.RESPONSE, payload=TypeRef(name=result, nullable=False)
                ),
            ],
            extras={
                "ros2_interface": {"kind": "action", "full_name": interface.full_name},
                "ros2_feedback_channel": channel.key,
            },
        ),
        Operation(
            key=feedback_key,
            name=f"{interface.name} feedback",
            kind=OperationKind.SUBSCRIBE,
            description=f"Receive the {interface.name} action's feedback while a goal runs.",
            channel_ref=channel.key,
            messages=[
                Message(
                    key=Keys.event_message(feedback_key, f"{interface.name}_Feedback"),
                    role=MessageRole.EVENT,
                    name=f"{interface.name}_Feedback",
                    payload=TypeRef(name=feedback, nullable=False),
                )
            ],
            extras={"ros2_interface": {"kind": "action", "full_name": interface.full_name, "section": "feedback"}},
        ),
    ]
    return operations, channel


def _identity(document: Ros2Document) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """The API's name, namespace, version and description."""
    if document.packages:
        primary = document.packages[0]
        name = primary.name if len(document.packages) == 1 else ", ".join(p.name for p in document.packages)
        return name, primary.name, primary.version, primary.description
    if len(document.interfaces) == 1:
        interface = document.interfaces[0]
        return interface.name, None, None, interface.description
    return "ROS 2 interfaces", None, None, None


class Ros2Normalizer(Normalizer, register=True):
    """Normalize parsed ROS 2 interfaces into an rpc-paradigm :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.ros2_parser.Ros2Document` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            The canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed ROS 2 document.
        """
        if not isinstance(source, Ros2Document):
            raise ValueError("ROS 2 source must be a Ros2Document (see app.ros2_parser)")
        builder = _Builder(source)
        name, namespace, version, description = _identity(source)
        service_key = namespace or name
        operations: List[Operation] = []
        channels: List[Channel] = []
        for interface in source.interfaces:
            if interface.kind == "msg":
                builder.section_record(interface, interface.sections[0])
            elif interface.kind == "srv":
                operations.extend(_service_operations(builder, interface, service_key))
            else:
                action_ops, channel = _action_operations(builder, interface, service_key)
                operations.extend(action_ops)
                channels.append(channel)
        services = (
            [
                Service(
                    key=service_key,
                    name=service_key,
                    description="The services and actions of the import.",
                    operations=operations,
                )
            ]
            if operations
            else []
        )
        record: Dict[str, Any] = {
            "input": "fileset" if source.is_fileset else "file",
            "interfaces": [
                {"full_name": i.full_name, "kind": i.kind, **({"file": i.path} if i.path else {})}
                for i in source.interfaces
            ],
            "packages": [
                {
                    "name": p.name,
                    **({"version": p.version} if p.version else {}),
                    **({"license": p.license} if p.license else {}),
                    "dependencies": list(p.dependencies),
                }
                for p in source.packages
            ],
            "capability_limits": _limits_payload(builder.limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol=ROS2_PROTOCOL,
            identity=ApiIdentity(name=name, namespace=namespace),
            version=version,
            title=name,
            description=description,
            services=services,
            channels=channels,
            types=list(builder.types.values()),
            raw=raw_record(source) if include_raw else None,
            extras={ROS2_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
