"""Matter cluster and device-type definition reader — FMT-9.5 (#5472).

Reads the Matter data-model XML (the ``configurator`` documents the ZAP tool and the Matter SDK
ship), which describes the interface of a Matter device:

.. code-block:: xml

    <configurator>
      <enum name="StartUpOnOffEnum" type="enum8"> <cluster code="0x0006"/> <item name="Off" value="0"/> … </enum>
      <bitmap name="OnOffFeature" type="bitmap32"> <cluster code="0x0006"/> <field name="Lighting" mask="1"/> …</bitmap>
      <struct name="RangeStruct"> <cluster code="0xFFF3"/> <item fieldId="0" name="Min" type="int32s"/> … </struct>
      <cluster>
        <name>On/Off</name> <code>0x0006</code> <define>ON_OFF_CLUSTER</define>
        <attribute side="server" code="0x0000" define="ON_OFF" type="boolean" writable="false">OnOff</attribute>
        <command source="client" code="0x00" name="Off"/>  <command source="server" …/>
        <event source="server" code="0x00" name="StartUp" priority="critical"> <field id="0" …/> </event>
      </cluster>
      <deviceType>
        <name>MA-dimmablelight</name> <typeName>Matter Dimmable Light</typeName> <deviceId>0x0101</deviceId>
        <clusters>
          <include cluster="On/Off" server="true"> <requireAttribute>ON_OFF</requireAttribute> </include>
        </clusters>
      </deviceType>
    </configurator>

A device type names the clusters it is composed of; the cluster definitions are usually separate
files, so a device type and its clusters are uploaded together as a **fileset** (every ``.xml``
member with a ``configurator`` root is read) and resolve against each other.

**Type references.** A member's ``type`` is a Matter base or semantic type (:data:`BASE_TYPES`), an
``array`` of its ``entryType``, or an enum, bitmap or struct the import declares. A name the import
does not declare is accepted only on a **standard cluster** (code ``0x0000``–``0x7FFF``): the
Matter specification defines that cluster's data types, and a definition file may lean on them
without restating them, so the reference is kept and declared unresolved. On a manufacturer-specific
or test cluster nothing outside the upload can define the type, so it is refused. A device type's
``include`` of a cluster outside the import is declared unresolved; a required attribute or command
missing from an included cluster that *is* in the import is refused.

Refusals carry the intake taxonomy code (:mod:`app.intake_error_taxonomy`):

* ``INPUT_ENCODING_INVALID`` / ``INPUT_TRUNCATED`` / ``INPUT_MALFORMED`` — see
  :func:`app.device_model_xml.read_device_model_xml`;
* ``FORMAT_MISMATCH`` — the root element is not ``configurator`` (an LwM2M object, for instance);
* ``INPUT_SEMANTIC_INVALID`` — no cluster and no device type, a cluster with no attributes,
  commands or events, a missing or invalid name or code, an ``array`` with no ``entryType``, or a
  duplicated cluster, member or data type;
* ``INPUT_REFERENCE_UNRESOLVED`` — see *Type references* above.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from .device_model_xml import (
    DeviceModelXmlError,
    child,
    child_text,
    children,
    local_name,
    read_device_model_xml,
    root_element_name,
)
from .fileset import IntakeFileset

__all__ = [
    "BASE_TYPES",
    "FORMAT_KEY",
    "ROOT_ELEMENT",
    "STANDARD_CLUSTER_MAX",
    "MatterAttribute",
    "MatterCluster",
    "MatterCommand",
    "MatterDataType",
    "MatterDeviceType",
    "MatterDocument",
    "MatterEvent",
    "MatterField",
    "MatterInclude",
    "MatterParseError",
    "MatterTypeUse",
    "is_matter_document",
    "parse_code",
    "parse_matter_fileset",
    "parse_matter_text",
    "raw_record",
]

#: The adapter / normalizer format key.
FORMAT_KEY = "matter"

#: The root element of every Matter data-model XML document.
ROOT_ELEMENT = "configurator"

#: The highest standard (specification-defined) cluster id; manufacturer-specific and test
#: clusters sit above it.
STANDARD_CLUSTER_MAX = 0x7FFF

#: Matter base and semantic data types → (canonical scalar, extra constraint facets). Keys are
#: lower-case; the XML spells them in either case.
BASE_TYPES: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "boolean": ("boolean", {}),
    "bool": ("boolean", {}),
    **{f"int{bits}u": (f"uint{max(8, 1 << (bits - 1).bit_length())}", {}) for bits in (8, 16, 24, 32, 40, 48, 56, 64)},
    **{f"int{bits}s": (f"int{max(8, 1 << (bits - 1).bit_length())}", {}) for bits in (8, 16, 24, 32, 40, 48, 56, 64)},
    "single": ("float", {}),
    "double": ("double", {}),
    "char_string": ("string", {}),
    "long_char_string": ("string", {}),
    "octet_string": ("bytes", {}),
    "long_octet_string": ("bytes", {}),
    "enum8": ("uint8", {}),
    "enum16": ("uint16", {}),
    "bitmap8": ("uint8", {}),
    "bitmap16": ("uint16", {}),
    "bitmap32": ("uint32", {}),
    "bitmap64": ("uint64", {}),
    "percent": ("uint8", {"maximum": 100}),
    "percent100ths": ("uint16", {"maximum": 10000}),
    "epoch_s": ("uint32", {"format": "matter-epoch-s"}),
    "epoch_us": ("uint64", {"format": "matter-epoch-us"}),
    "utc": ("uint32", {"format": "matter-epoch-s"}),
    "posix_ms": ("uint64", {"format": "unix-time-ms"}),
    "systime_ms": ("uint64", {}),
    "systime_us": ("uint64", {}),
    "elapsed_s": ("uint32", {}),
    "date": ("uint32", {}),
    "tod": ("uint32", {}),
    "temperature": ("int16", {}),
    "temperature_difference": ("int16", {}),
    "temperature_diff": ("int16", {}),
    "power_mw": ("int64", {}),
    "amperage_ma": ("int64", {}),
    "voltage_mv": ("int64", {}),
    "energy_mwh": ("int64", {}),
    "money": ("int64", {}),
    "fabric_idx": ("uint8", {}),
    "fabric_id": ("uint64", {}),
    "node_id": ("uint64", {}),
    "vendor_id": ("uint16", {}),
    "group_id": ("uint16", {}),
    "endpoint_no": ("uint16", {}),
    "cluster_id": ("uint32", {}),
    "attrib_id": ("uint32", {}),
    "field_id": ("uint32", {}),
    "event_id": ("uint32", {}),
    "command_id": ("uint32", {}),
    "devtype_id": ("uint32", {}),
    "action_id": ("uint8", {}),
    "trans_id": ("uint32", {}),
    "data_ver": ("uint32", {}),
    "event_no": ("uint64", {}),
    "entry_idx": ("uint16", {}),
    "priority": ("uint8", {}),
    "status": ("uint8", {}),
    "namespace": ("uint8", {}),
    "tag": ("uint8", {}),
    "ipadr": ("bytes", {}),
    "ipv4adr": ("bytes", {}),
    "ipv6adr": ("bytes", {}),
    "ipv6pre": ("bytes", {}),
    "hwadr": ("bytes", {}),
}

#: The ``type`` value that makes a member a list of its ``entryType``.
_ARRAY = "array"

#: Event priorities the data model defines.
_PRIORITIES = ("debug", "info", "critical")


class MatterParseError(ValueError):
    """The input is not a readable Matter data-model definition.

    Args:
        message: Human-readable description, naming the file and cluster where it can.
        code: The intake taxonomy code (see the module docstring).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


# ===========================================================================
# The parsed model
# ===========================================================================


@dataclass(frozen=True)
class MatterTypeUse:
    """The type written at one use site.

    Attributes:
        name: The element type (``int16u``, ``RangeStruct`` …) — ``entryType`` for an ``array``.
        is_list: Whether the member is a list (``type="array"`` or ``array="true"``).
    """

    name: str
    is_list: bool = False


@dataclass(frozen=True)
class MatterField:
    """A struct item, a command argument or an event field.

    Attributes:
        name: The member name.
        id: The field id (``fieldId`` / ``id``), else the position.
        type: The member's type.
        optional: Whether the member may be absent.
        nullable: Whether the member may be null.
        default: The ``default`` text, when written.
        minimum / maximum: Value bounds (``min`` / ``max``).
        length / min_length: Length bounds (``length`` / ``minLength``).
    """

    name: str
    id: int
    type: MatterTypeUse
    optional: bool = False
    nullable: bool = False
    default: Optional[str] = None
    minimum: Optional[str] = None
    maximum: Optional[str] = None
    length: Optional[int] = None
    min_length: Optional[int] = None


@dataclass(frozen=True)
class MatterAttribute:
    """One cluster ``attribute``.

    Attributes:
        name: The attribute name (the element text).
        code: The attribute id.
        define: The ``define`` macro name, when written.
        side: ``server`` or ``client``.
        type: The attribute's type.
        writable: Whether the attribute is writable.
        optional / nullable / reportable: The attribute qualities.
        default / minimum / maximum / length / min_length: As on :class:`MatterField`.
        access: ``(op, privilege)`` pairs from ``access`` children.
        description: A ``description`` child's text.
    """

    name: str
    code: int
    define: Optional[str]
    side: str
    type: MatterTypeUse
    writable: bool = False
    optional: bool = False
    nullable: bool = False
    reportable: bool = False
    default: Optional[str] = None
    minimum: Optional[str] = None
    maximum: Optional[str] = None
    length: Optional[int] = None
    min_length: Optional[int] = None
    access: Tuple[Tuple[str, str], ...] = ()
    description: Optional[str] = None


@dataclass(frozen=True)
class MatterCommand:
    """One cluster ``command``: ``source="client"`` is a request, ``source="server"`` a response."""

    name: str
    code: int
    source: str
    args: Tuple[MatterField, ...] = ()
    optional: bool = False
    response: Optional[str] = None
    access: Tuple[Tuple[str, str], ...] = ()
    description: Optional[str] = None


@dataclass(frozen=True)
class MatterEvent:
    """One cluster ``event``."""

    name: str
    code: int
    priority: str
    fields: Tuple[MatterField, ...] = ()
    optional: bool = False
    access: Tuple[Tuple[str, str], ...] = ()
    description: Optional[str] = None


@dataclass(frozen=True)
class MatterCluster:
    """One ``cluster`` definition.

    Attributes:
        name: The cluster name (``On/Off``).
        code: The cluster id.
        code_text: The id as written (``0x0006``).
        define: The ``define`` macro name.
        domain: The ``domain`` it belongs to.
        description: Its ``description``.
        attributes / commands / events: Its members, in file order.
        features: ``features/feature`` entries as written attributes plus a ``conformance`` key.
        path: The file it came from (in a fileset).
    """

    name: str
    code: int
    code_text: str
    define: Optional[str] = None
    domain: Optional[str] = None
    description: Optional[str] = None
    attributes: Tuple[MatterAttribute, ...] = ()
    commands: Tuple[MatterCommand, ...] = ()
    events: Tuple[MatterEvent, ...] = ()
    features: Tuple[Dict[str, Any], ...] = ()
    path: Optional[str] = None

    @property
    def is_standard(self) -> bool:
        """Whether the cluster id is in the specification-defined range."""
        return self.code <= STANDARD_CLUSTER_MAX


@dataclass(frozen=True)
class MatterDataType:
    """A declared ``enum``, ``bitmap`` or ``struct``.

    Attributes:
        name: The type name.
        kind: ``enum``, ``bitmap`` or ``struct``.
        base: The base type of an enum or bitmap (``enum8``, ``bitmap32``).
        clusters: The cluster ids it is bound to (``<cluster code=…/>`` children).
        members: ``(name, value)`` for an enum (value) or bitmap (mask).
        fields: The items of a struct.
        path: The file it came from (in a fileset).
    """

    name: str
    kind: str
    base: Optional[str] = None
    clusters: Tuple[int, ...] = ()
    members: Tuple[Tuple[str, int], ...] = ()
    fields: Tuple[MatterField, ...] = ()
    path: Optional[str] = None


@dataclass(frozen=True)
class MatterInclude:
    """One ``clusters/include`` of a device type."""

    cluster: str
    client: bool = False
    server: bool = False
    required_attributes: Tuple[str, ...] = ()
    required_commands: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MatterDeviceType:
    """One ``deviceType``."""

    name: str
    type_name: Optional[str] = None
    device_id: Optional[str] = None
    profile_id: Optional[str] = None
    domain: Optional[str] = None
    device_class: Optional[str] = None
    scope: Optional[str] = None
    includes: Tuple[MatterInclude, ...] = ()
    path: Optional[str] = None


@dataclass(frozen=True)
class MatterDocument:
    """Every cluster, data type and device type of one import."""

    clusters: Tuple[MatterCluster, ...] = ()
    data_types: Tuple[MatterDataType, ...] = ()
    device_types: Tuple[MatterDeviceType, ...] = ()
    label: Optional[str] = None
    is_fileset: bool = False
    sources: Dict[str, str] = field(default_factory=dict)

    def cluster_named(self, name: str) -> Optional[MatterCluster]:
        """The cluster with this name (or ``define``), when the import has it."""
        folded = name.strip().lower()
        for cluster in self.clusters:
            if cluster.name.lower() == folded or (cluster.define or "").lower() == folded:
                return cluster
        return None

    def resolve(self, name: str, cluster_code: Optional[int]) -> Optional[MatterDataType]:
        """The declared data type a use site in ``cluster_code`` means by ``name``.

        A type bound to the use site's cluster wins, then an unbound type, then the single type of
        that name bound elsewhere (a struct shared between clusters).
        """
        candidates = [item for item in self.data_types if item.name == name]
        if not candidates:
            return None
        for item in candidates:
            if cluster_code is not None and cluster_code in item.clusters:
                return item
        for item in candidates:
            if not item.clusters:
                return item
        return candidates[0] if len(candidates) == 1 else None


def is_matter_document(text: Optional[str]) -> bool:
    """Whether ``text`` opens with a ``configurator`` root element (read from the head only)."""
    return root_element_name(text) == ROOT_ELEMENT


def is_base_type(name: str) -> bool:
    """Whether ``name`` is a Matter base or semantic data type."""
    return name.lower() in BASE_TYPES


def parse_code(text: Optional[str]) -> Optional[int]:
    """A Matter id (``0x0006``, ``6``) as an int, or ``None`` when it does not read."""
    if text is None:
        return None
    try:
        value = int(text.strip(), 0)
    except ValueError:
        return None
    return value if value >= 0 else None


# ===========================================================================
# Readers
# ===========================================================================


def _where(path: Optional[str]) -> str:
    return f" ({path})" if path else ""


def _bool(value: Optional[str]) -> bool:
    return (value or "").strip().lower() == "true"


def _int_or_none(value: Optional[str]) -> Optional[int]:
    return parse_code(value) if value is not None and value.strip() else None


def _type_use(element: ET.Element, problems: List[str], label: str) -> Optional[MatterTypeUse]:
    """The type written on a member: ``type``, with ``entryType`` for an ``array``."""
    written = (element.get("type") or "").strip()
    if not written:
        problems.append(f"{label} has no type")
        return None
    if written.lower() == _ARRAY:
        entry = (element.get("entryType") or "").strip()
        if not entry:
            problems.append(f"{label} is an array with no entryType")
            return None
        return MatterTypeUse(name=entry, is_list=True)
    return MatterTypeUse(name=written, is_list=_bool(element.get("array")))


def _access(element: ET.Element) -> Tuple[Tuple[str, str], ...]:
    return tuple(
        ((item.get("op") or "").strip(), (item.get("privilege") or item.get("role") or "").strip())
        for item in children(element, "access")
        if item.get("op")
    )


def _description(element: ET.Element) -> Optional[str]:
    text = child_text(element, "description")
    return " ".join(text.split()) if text else None


def _read_field(element: ET.Element, position: int, problems: List[str], owner: str) -> Optional[MatterField]:
    """Read a struct ``item``, a command ``arg`` or an event ``field``."""
    name = (element.get("name") or "").strip()
    label = f"{owner} member {name or position}"
    if not name:
        problems.append(f"{label} has no name")
    type_use = _type_use(element, problems, label)
    if not name or type_use is None:
        return None
    raw_id = element.get("fieldId") if element.get("fieldId") is not None else element.get("id")
    field_id = _int_or_none(raw_id)
    return MatterField(
        name=name,
        id=position if field_id is None else field_id,
        type=type_use,
        optional=_bool(element.get("optional")),
        nullable=_bool(element.get("isNullable")),
        default=element.get("default"),
        minimum=element.get("min"),
        maximum=element.get("max"),
        length=_int_or_none(element.get("length")),
        min_length=_int_or_none(element.get("minLength")),
    )


def _read_fields(parent: ET.Element, tag: str, problems: List[str], owner: str) -> Tuple[MatterField, ...]:
    fields = [_read_field(item, index, problems, owner) for index, item in enumerate(children(parent, tag))]
    read = tuple(item for item in fields if item is not None)
    _check_duplicates([item.name for item in read], problems, f"{owner} member")
    return read


def _check_duplicates(names: List[str], problems: List[str], what: str) -> None:
    seen = set()
    for name in names:
        if name in seen:
            problems.append(f"{what} {name} is declared twice")
        seen.add(name)


def _read_attribute(element: ET.Element, problems: List[str], owner: str) -> Optional[MatterAttribute]:
    text = (element.text or "").strip()
    name = (element.get("name") or text or element.get("define") or "").strip()
    code = parse_code(element.get("code"))
    label = f"{owner} attribute {name or element.get('code') or '?'}"
    if not name:
        problems.append(f"{label} has no name")
    if code is None:
        problems.append(f"{label} has no valid code")
    type_use = _type_use(element, problems, label)
    if not name or code is None or type_use is None:
        return None
    return MatterAttribute(
        name=name,
        code=code,
        define=element.get("define"),
        side=(element.get("side") or "server").strip(),
        type=type_use,
        writable=_bool(element.get("writable")),
        optional=_bool(element.get("optional")),
        nullable=_bool(element.get("isNullable")),
        reportable=_bool(element.get("reportable")),
        default=element.get("default"),
        minimum=element.get("min"),
        maximum=element.get("max"),
        length=_int_or_none(element.get("length")),
        min_length=_int_or_none(element.get("minLength")),
        access=_access(element),
        description=_description(element),
    )


def _read_command(element: ET.Element, problems: List[str], owner: str) -> Optional[MatterCommand]:
    name = (element.get("name") or "").strip()
    code = parse_code(element.get("code"))
    label = f"{owner} command {name or element.get('code') or '?'}"
    if not name:
        problems.append(f"{label} has no name")
    if code is None:
        problems.append(f"{label} has no valid code")
    source = (element.get("source") or "client").strip().lower()
    if source not in ("client", "server"):
        problems.append(f"{label} has source {source!r}; expected client or server")
    args = _read_fields(element, "arg", problems, label)
    if not name or code is None or source not in ("client", "server"):
        return None
    return MatterCommand(
        name=name,
        code=code,
        source=source,
        args=args,
        optional=_bool(element.get("optional")),
        response=(element.get("response") or "").strip() or None,
        access=_access(element),
        description=_description(element),
    )


def _read_event(element: ET.Element, problems: List[str], owner: str) -> Optional[MatterEvent]:
    name = (element.get("name") or "").strip()
    code = parse_code(element.get("code"))
    label = f"{owner} event {name or element.get('code') or '?'}"
    if not name:
        problems.append(f"{label} has no name")
    if code is None:
        problems.append(f"{label} has no valid code")
    priority = (element.get("priority") or "info").strip().lower()
    if priority not in _PRIORITIES:
        problems.append(f"{label} has priority {priority!r}; expected debug, info or critical")
    fields = _read_fields(element, "field", problems, label)
    if not name or code is None or priority not in _PRIORITIES:
        return None
    return MatterEvent(
        name=name,
        code=code,
        priority=priority,
        fields=fields,
        optional=_bool(element.get("optional")),
        access=_access(element),
        description=_description(element),
    )


def _read_features(element: ET.Element) -> Tuple[Dict[str, Any], ...]:
    features: List[Dict[str, Any]] = []
    for feature in children(child(element, "features"), "feature"):
        record: Dict[str, Any] = {key: value for key, value in sorted(feature.attrib.items())}
        conformance = [local_name(item.tag) for item in feature if isinstance(item.tag, str)]
        if conformance:
            record["conformance"] = conformance
        features.append(record)
    return tuple(features)


def _read_cluster(element: ET.Element, path: Optional[str], problems: List[str]) -> Optional[MatterCluster]:
    name = child_text(element, "name")
    code_text = child_text(element, "code")
    code = parse_code(code_text)
    owner = f"Cluster {name or code_text or '?'}"
    if not name:
        problems.append(f"{owner} has no name")
    if code is None:
        problems.append(f"{owner} has no valid code")
    attributes = [_read_attribute(item, problems, owner) for item in children(element, "attribute")]
    commands = [_read_command(item, problems, owner) for item in children(element, "command")]
    events = [_read_event(item, problems, owner) for item in children(element, "event")]
    if not attributes and not commands and not events:
        problems.append(f"{owner} declares no attributes, commands or events, so it exposes nothing to import")
    read_attributes = tuple(item for item in attributes if item is not None)
    read_commands = tuple(item for item in commands if item is not None)
    read_events = tuple(item for item in events if item is not None)
    _check_duplicates([item.name for item in read_attributes], problems, f"{owner} attribute")
    _check_duplicates([item.name for item in read_commands], problems, f"{owner} command")
    _check_duplicates([item.name for item in read_events], problems, f"{owner} event")
    if not name or code is None or code_text is None:
        return None
    return MatterCluster(
        name=name,
        code=code,
        code_text=code_text,
        define=child_text(element, "define"),
        domain=child_text(element, "domain"),
        description=_description(element),
        attributes=read_attributes,
        commands=read_commands,
        events=read_events,
        features=_read_features(element),
        path=path,
    )


def _read_data_type(element: ET.Element, path: Optional[str], problems: List[str]) -> Optional[MatterDataType]:
    kind = local_name(element.tag)
    name = (element.get("name") or "").strip()
    owner = f"{kind} {name or '?'}"
    if not name:
        problems.append(f"An {kind} has no name")
        return None
    clusters = tuple(
        code for code in (parse_code(item.get("code")) for item in children(element, "cluster")) if code is not None
    )
    if kind == "struct":
        return MatterDataType(
            name=name, kind=kind, clusters=clusters, fields=_read_fields(element, "item", problems, owner), path=path
        )
    tag, attribute = ("item", "value") if kind == "enum" else ("field", "mask")
    members: List[Tuple[str, int]] = []
    for item in children(element, tag):
        member = (item.get("name") or "").strip()
        value = parse_code(item.get(attribute))
        if not member or value is None:
            problems.append(f"{owner} member {member or '?'} has no name or no valid {attribute}")
            continue
        members.append((member, value))
    _check_duplicates([member for member, _ in members], problems, f"{owner} member")
    return MatterDataType(
        name=name,
        kind=kind,
        base=(element.get("type") or "").strip() or None,
        clusters=clusters,
        members=tuple(members),
        path=path,
    )


def _read_device_type(element: ET.Element, path: Optional[str], problems: List[str]) -> Optional[MatterDeviceType]:
    name = child_text(element, "name") or child_text(element, "typeName")
    if not name:
        problems.append("A deviceType has no name")
        return None
    includes: List[MatterInclude] = []
    for include in children(child(element, "clusters"), "include"):
        cluster = (include.get("cluster") or "").strip()
        if not cluster:
            problems.append(f"Device type {name} includes a cluster with no name")
            continue
        includes.append(
            MatterInclude(
                cluster=cluster,
                client=_bool(include.get("client")),
                server=_bool(include.get("server")),
                required_attributes=tuple(
                    (item.text or "").strip()
                    for item in children(include, "requireAttribute")
                    if (item.text or "").strip()
                ),
                required_commands=tuple(
                    (item.text or "").strip()
                    for item in children(include, "requireCommand")
                    if (item.text or "").strip()
                ),
            )
        )
    if not includes:
        problems.append(f"Device type {name} includes no clusters, so it composes nothing")
    return MatterDeviceType(
        name=name,
        type_name=child_text(element, "typeName"),
        device_id=child_text(element, "deviceId"),
        profile_id=child_text(element, "profileId"),
        domain=child_text(element, "domain"),
        device_class=child_text(element, "class"),
        scope=child_text(element, "scope"),
        includes=tuple(includes),
        path=path,
    )


@dataclass
class _Draft:
    clusters: List[MatterCluster] = field(default_factory=list)
    data_types: List[MatterDataType] = field(default_factory=list)
    device_types: List[MatterDeviceType] = field(default_factory=list)


def _read_file(text: str, *, path: Optional[str], draft: _Draft) -> None:
    """Read one ``configurator`` document into ``draft``."""
    try:
        root = read_device_model_xml(text, source_label=path, kind="Matter definition")
    except DeviceModelXmlError as exc:
        raise MatterParseError(str(exc), code=exc.code) from exc
    root_name = local_name(root.tag)
    if root_name != ROOT_ELEMENT:
        hint = " — it looks like an LwM2M object definition; import it as LwM2M" if root_name == "LWM2M" else ""
        raise MatterParseError(
            f"The document{_where(path)} has a <{root_name}> root, not <{ROOT_ELEMENT}>{hint}",
            code="FORMAT_MISMATCH",
        )
    problems: List[str] = []
    clusters = [_read_cluster(item, path, problems) for item in children(root, "cluster")]
    data_types = [
        _read_data_type(item, path, problems)
        for item in root
        if isinstance(item.tag, str) and local_name(item.tag) in ("enum", "bitmap", "struct")
    ]
    device_types = [_read_device_type(item, path, problems) for item in children(root, "deviceType")]
    if problems:
        raise MatterParseError(
            f"Invalid Matter definition{_where(path)}: " + "; ".join(problems), code="INPUT_SEMANTIC_INVALID"
        )
    draft.clusters.extend(item for item in clusters if item is not None)
    draft.data_types.extend(item for item in data_types if item is not None)
    draft.device_types.extend(item for item in device_types if item is not None)


def _finish(draft: _Draft, *, label: Optional[str], is_fileset: bool, sources: Dict[str, str]) -> MatterDocument:
    """Check the import as a whole and build the document."""
    if not draft.clusters and not draft.device_types:
        raise MatterParseError(
            f"The Matter definition{_where(label)} declares no cluster and no device type, so there is "
            "nothing to import",
            code="INPUT_SEMANTIC_INVALID",
        )
    problems: List[str] = []
    codes: Dict[int, MatterCluster] = {}
    for cluster in draft.clusters:
        if cluster.code in codes:
            problems.append(
                f"Cluster {cluster.code_text} is defined twice ({codes[cluster.code].name} and {cluster.name})"
            )
        codes[cluster.code] = cluster
    seen: Dict[Tuple[str, Tuple[int, ...]], MatterDataType] = {}
    for item in draft.data_types:
        identity = (item.name, item.clusters)
        if identity in seen:
            problems.append(f"Data type {item.name} is declared twice for the same clusters")
        seen[identity] = item
    _check_duplicates([item.name for item in draft.device_types], problems, "Device type")
    if problems:
        raise MatterParseError("Invalid Matter definition: " + "; ".join(problems), code="INPUT_SEMANTIC_INVALID")
    document = MatterDocument(
        clusters=tuple(draft.clusters),
        data_types=tuple(draft.data_types),
        device_types=tuple(draft.device_types),
        label=label,
        is_fileset=is_fileset,
        sources=sources,
    )
    _check_references(document)
    return document


def _type_problem(
    document: MatterDocument, use: MatterTypeUse, cluster: Optional[MatterCluster], where: str
) -> Optional[str]:
    """Why ``use`` cannot be accounted for, or ``None`` when it can."""
    if is_base_type(use.name) or document.resolve(use.name, cluster.code if cluster else None) is not None:
        return None
    if cluster is not None and cluster.is_standard:
        return None
    scope = (
        f"cluster {cluster.name} ({cluster.code_text}) is not a standard cluster"
        if cluster
        else "it is not bound to a standard cluster"
    )
    return f"{where} has type {use.name}, which the import does not declare and {scope}"


def _check_references(document: MatterDocument) -> None:
    """Refuse type and member references the import cannot account for (see the module docstring)."""
    problems: List[str] = []
    for cluster in document.clusters:
        for attribute in cluster.attributes:
            problems.append(
                _type_problem(document, attribute.type, cluster, f"Attribute {cluster.name}.{attribute.name}") or ""
            )
        for command in cluster.commands:
            for arg in command.args:
                problems.append(
                    _type_problem(document, arg.type, cluster, f"Argument {cluster.name}.{command.name}.{arg.name}")
                    or ""
                )
            if command.response and not any(
                item.name == command.response and item.source == "server" for item in cluster.commands
            ):
                problems.append(
                    f"Command {cluster.name}.{command.name} names response {command.response}, which the "
                    "cluster does not declare as a server command"
                )
        for event in cluster.events:
            for item in event.fields:
                problems.append(
                    _type_problem(document, item.type, cluster, f"Event field {cluster.name}.{event.name}.{item.name}")
                    or ""
                )
    by_code = {cluster.code: cluster for cluster in document.clusters}
    for data_type in document.data_types:
        bound = next((by_code[code] for code in data_type.clusters if code in by_code), None)
        for item in data_type.fields:
            use_cluster = bound if bound is not None else None
            if use_cluster is None and any(code <= STANDARD_CLUSTER_MAX for code in data_type.clusters):
                continue
            problems.append(
                _type_problem(document, item.type, use_cluster, f"Struct field {data_type.name}.{item.name}") or ""
            )
    for device_type in document.device_types:
        for include in device_type.includes:
            cluster = document.cluster_named(include.cluster)
            if cluster is None:
                continue
            attributes = {
                name.lower() for item in cluster.attributes for name in (item.name, item.define or "") if name
            }
            commands = {item.name.lower() for item in cluster.commands}
            for name in include.required_attributes:
                if name.lower() not in attributes:
                    problems.append(
                        f"Device type {device_type.name} requires attribute {name} of {cluster.name}, "
                        "which the cluster does not declare"
                    )
            for name in include.required_commands:
                if name.lower() not in commands:
                    problems.append(
                        f"Device type {device_type.name} requires command {name} of {cluster.name}, "
                        "which the cluster does not declare"
                    )
    problems = [problem for problem in problems if problem]
    if problems:
        raise MatterParseError(
            "Unresolved Matter references: "
            + "; ".join(problems)
            + ". Upload the files that declare them beside this one.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


def parse_matter_text(text: str, *, label: Optional[str] = None) -> MatterDocument:
    """Parse one Matter data-model XML file.

    Args:
        text: The file text.
        label: The upload's label (file name).

    Returns:
        The parsed document.

    Raises:
        MatterParseError: See the module docstring.
    """
    draft = _Draft()
    _read_file(text, path=label, draft=draft)
    return _finish(draft, label=label, is_fileset=False, sources={label or "document.xml": text})


def parse_matter_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> MatterDocument:
    """Parse a set of Matter definition files (a device type beside its cluster definitions).

    Every ``.xml`` member whose root is ``configurator`` is read, the root member first; any other
    member is ignored.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        MatterParseError: See the module docstring.
    """
    ordered = [fileset.root] + sorted(path for path in fileset.members if path != fileset.root)
    draft = _Draft()
    sources: Dict[str, str] = {}
    for path in ordered:
        text = fileset.members[path]
        if path != fileset.root and (PurePosixPath(path).suffix.lower() != ".xml" or not is_matter_document(text)):
            continue
        _read_file(text, path=path, draft=draft)
        sources[path] = text
    return _finish(draft, label=label or fileset.root, is_fileset=True, sources=sources)


def raw_record(document: MatterDocument) -> Dict[str, Any]:
    """The lossless native record kept on ``CanonicalApi.raw``: every file's text."""
    return {"files": [{"path": path, "text": text} for path, text in sorted(document.sources.items())]}
