"""LwM2M / IPSO object-definition reader — FMT-9.5 (#5472).

Reads OMA LwM2M object definitions — the XML the OMA registry publishes for every object,
including the IPSO smart objects (``3303`` Temperature, ``3306`` Actuation …)::

    <LWM2M>
      <Object ObjectType="MODefinition">
        <Name>Temperature</Name>  <ObjectID>3303</ObjectID>  <ObjectURN>urn:oma:lwm2m:ext:3303</ObjectURN>
        <LWM2MVersion>1.1</LWM2MVersion>  <ObjectVersion>1.1</ObjectVersion>
        <MultipleInstances>Multiple</MultipleInstances>  <Mandatory>Optional</Mandatory>
        <Resources>
          <Item ID="5700">
            <Name>Sensor Value</Name>  <Operations>R</Operations>
            <MultipleInstances>Single</MultipleInstances>  <Mandatory>Mandatory</Mandatory>
            <Type>Float</Type>  <RangeEnumeration/>  <Units>Cel</Units>
            <Description>…</Description>
          </Item>
        </Resources>
      </Object>
    </LWM2M>

A file may define several objects; the registry convention is one file per object, uploaded
together as a **fileset** (every ``.xml`` member with an ``LWM2M`` root is read).

A resource's ``RangeEnumeration`` is read as a numeric range (``0..100``) or a list of permitted
values (``0, 1, 2, 3``); any other text is kept verbatim and declared by the normalizer.

Refusals carry the intake taxonomy code (:mod:`app.intake_error_taxonomy`):

* ``INPUT_ENCODING_INVALID`` / ``INPUT_TRUNCATED`` / ``INPUT_MALFORMED`` — see
  :func:`app.device_model_xml.read_device_model_xml`;
* ``FORMAT_MISMATCH`` — the root element is not ``LWM2M`` (a Matter ``configurator`` cluster
  definition, for instance);
* ``INPUT_SEMANTIC_INVALID`` — no objects, an object without a valid ``ObjectID`` or ``Name``, an
  object with no resources, a resource with an unknown ``Type``, an invalid ``Operations``,
  ``MultipleInstances`` or ``Mandatory`` value, or a duplicated object or resource id.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from .device_model_xml import (
    DeviceModelXmlError,
    child,
    child_text,
    children,
    read_device_model_xml,
    root_element_name,
)
from .fileset import IntakeFileset

__all__ = [
    "FORMAT_KEY",
    "OPERATIONS",
    "RESOURCE_TYPES",
    "ROOT_ELEMENT",
    "Lwm2mDocument",
    "Lwm2mObject",
    "Lwm2mParseError",
    "Lwm2mRange",
    "Lwm2mResource",
    "is_lwm2m_document",
    "parse_lwm2m_fileset",
    "parse_lwm2m_text",
    "raw_record",
]

#: The adapter / normalizer format key.
FORMAT_KEY = "lwm2m"

#: The root element every object-definition file carries.
ROOT_ELEMENT = "LWM2M"

#: The resource data types of LwM2M 1.0–1.2 (``Unsigned Integer`` and ``Corelnk`` arrived in 1.1).
RESOURCE_TYPES: Tuple[str, ...] = (
    "String",
    "Integer",
    "Unsigned Integer",
    "Float",
    "Boolean",
    "Opaque",
    "Time",
    "Objlnk",
    "Corelnk",
)

#: The valid ``Operations`` values: read, write, read-write and execute.
OPERATIONS: Tuple[str, ...] = ("R", "W", "RW", "E")

_TYPE_BY_FOLDED = {name.replace(" ", "").lower(): name for name in RESOURCE_TYPES}
_NUMERIC_TYPES = frozenset({"Integer", "Unsigned Integer", "Float", "Time"})
_ID_LIMIT = 65535
_RANGE_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)\s*$")
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


class Lwm2mParseError(ValueError):
    """The input is not a readable LwM2M object definition.

    Args:
        message: Human-readable description, naming the file and object where it can.
        code: The intake taxonomy code (see the module docstring).
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Lwm2mRange:
    """A parsed ``RangeEnumeration``.

    Attributes:
        text: The text as written.
        minimum: Lower bound of an ``a..b`` range.
        maximum: Upper bound of an ``a..b`` range.
        values: The permitted values of an enumeration (``0, 1, 2``).
    """

    text: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    values: Tuple[Any, ...] = ()

    @property
    def is_parsed(self) -> bool:
        """Whether the text read as a range or an enumeration."""
        return self.minimum is not None or bool(self.values)


@dataclass(frozen=True)
class Lwm2mResource:
    """One ``Resources/Item``.

    Attributes:
        id: The resource id.
        name: The resource name as written.
        operations: ``R``, ``W``, ``RW`` or ``E``.
        multiple: Whether the resource is multi-instance.
        mandatory: Whether the resource is mandatory.
        type: The resource type (one of :data:`RESOURCE_TYPES`), ``None`` for an executable.
        range: The parsed ``RangeEnumeration``, when one is written.
        units: The ``Units`` text, when written.
        description: The ``Description`` text.
    """

    id: int
    name: str
    operations: str
    multiple: bool
    mandatory: bool
    type: Optional[str]
    range: Optional[Lwm2mRange] = None
    units: Optional[str] = None
    description: Optional[str] = None

    @property
    def is_executable(self) -> bool:
        """Whether the resource is an executable (``E``) — an operation, not data."""
        return self.operations == "E"


@dataclass(frozen=True)
class Lwm2mObject:
    """One ``Object`` definition.

    Attributes:
        object_id: The object id (``3303``).
        name: The object name as written.
        resources: The resources, in file order.
        urn: The ``ObjectURN``.
        lwm2m_version: The ``LWM2MVersion`` the object targets.
        object_version: The object's own ``ObjectVersion``.
        multiple: Whether a client may hold several instances.
        mandatory: Whether a client must implement the object.
        description: ``Description1``.
        description2: ``Description2``, when written.
        path: The file the object came from (in a fileset).
    """

    object_id: int
    name: str
    resources: Tuple[Lwm2mResource, ...]
    urn: Optional[str] = None
    lwm2m_version: Optional[str] = None
    object_version: Optional[str] = None
    multiple: bool = False
    mandatory: bool = False
    description: Optional[str] = None
    description2: Optional[str] = None
    path: Optional[str] = None


@dataclass(frozen=True)
class Lwm2mDocument:
    """Every object of one import.

    Attributes:
        objects: The objects, in file then document order.
        label: The upload's label.
        is_fileset: Whether the objects came from a fileset.
        sources: Every file's text, keyed by path (a single file under its label).
    """

    objects: Tuple[Lwm2mObject, ...]
    label: Optional[str] = None
    is_fileset: bool = False
    sources: Dict[str, str] = field(default_factory=dict)


def is_lwm2m_document(text: Optional[str]) -> bool:
    """Whether ``text`` opens with an ``LWM2M`` root element (read from the head only)."""
    return root_element_name(text) == ROOT_ELEMENT


def _where(path: Optional[str], name: Optional[str] = None) -> str:
    parts = [part for part in (path, name) if part]
    return f" ({', '.join(parts)})" if parts else ""


def _number(text: str) -> Any:
    """A numeric literal as an ``int`` when integral, else a ``float``."""
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def parse_range(text: Optional[str], resource_type: Optional[str]) -> Optional[Lwm2mRange]:
    """Read a ``RangeEnumeration``.

    ``a..b`` is a range; a comma-separated list is an enumeration (numbers for a numeric resource,
    strings otherwise). Anything else is kept as text with no bounds.

    Args:
        text: The written text (``None`` or blank for none).
        resource_type: The resource type, which decides how enumeration members are read.

    Returns:
        The parsed range, or ``None`` when nothing is written.
    """
    if text is None or not text.strip():
        return None
    written = text.strip()
    match = _RANGE_RE.match(written)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        if low <= high:
            return Lwm2mRange(text=written, minimum=low, maximum=high)
        return Lwm2mRange(text=written)
    if "," in written:
        members = [member.strip() for member in written.split(",")]
        if all(members):
            if resource_type in _NUMERIC_TYPES:
                if all(_NUMBER_RE.match(member) for member in members):
                    return Lwm2mRange(text=written, values=tuple(_number(member) for member in members))
                return Lwm2mRange(text=written)
            return Lwm2mRange(text=written, values=tuple(members))
    return Lwm2mRange(text=written)


def _read_id(text: Optional[str]) -> Optional[int]:
    if text is None or not text.strip().isdigit():
        return None
    value = int(text.strip())
    return value if value <= _ID_LIMIT else None


def _flag(value: Optional[str], *, true: str, false: str, default: bool) -> Optional[bool]:
    """Read a two-valued element (``Multiple``/``Single``, ``Mandatory``/``Optional``)."""
    if value is None:
        return default
    folded = value.strip().lower()
    if folded == true.lower():
        return True
    if folded == false.lower():
        return False
    return None


def _read_resource(item: ET.Element, problems: List[str], owner: str) -> Optional[Lwm2mResource]:
    """Read one ``Item``, appending what is wrong with it to ``problems``."""
    resource_id = _read_id(item.get("ID"))
    name = child_text(item, "Name")
    label = f"{owner} resource {item.get('ID') or '?'}{f' ({name})' if name else ''}"
    if resource_id is None:
        problems.append(f"{label} has no valid ID (0–{_ID_LIMIT})")
    if not name:
        problems.append(f"{label} has no Name")
    operations = (child_text(item, "Operations") or "").upper()
    if operations not in OPERATIONS:
        problems.append(f"{label} has Operations {operations or '(empty)'!r}; expected R, W, RW or E")
    multiple = _flag(child_text(item, "MultipleInstances"), true="Multiple", false="Single", default=False)
    if multiple is None:
        problems.append(
            f"{label} has MultipleInstances {child_text(item, 'MultipleInstances')!r}; expected Single or Multiple"
        )
    mandatory = _flag(child_text(item, "Mandatory"), true="Mandatory", false="Optional", default=False)
    if mandatory is None:
        problems.append(f"{label} has Mandatory {child_text(item, 'Mandatory')!r}; expected Mandatory or Optional")
    written_type = child_text(item, "Type")
    resource_type = _TYPE_BY_FOLDED.get(written_type.replace(" ", "").lower()) if written_type else None
    if operations != "E":
        if written_type is None:
            problems.append(f"{label} has no Type")
        elif resource_type is None:
            problems.append(f"{label} has Type {written_type!r}, which is not an LwM2M resource type")
    if resource_id is None or not name or operations not in OPERATIONS or multiple is None or mandatory is None:
        return None
    if operations != "E" and resource_type is None:
        return None
    return Lwm2mResource(
        id=resource_id,
        name=name,
        operations=operations,
        multiple=multiple,
        mandatory=mandatory,
        type=resource_type,
        range=parse_range(child_text(item, "RangeEnumeration"), resource_type),
        units=child_text(item, "Units"),
        description=child_text(item, "Description"),
    )


def _read_object(element: ET.Element, path: Optional[str]) -> Lwm2mObject:
    """Read one ``Object``.

    Raises:
        Lwm2mParseError: ``INPUT_SEMANTIC_INVALID`` listing every problem the object has.
    """
    name = child_text(element, "Name")
    object_id = _read_id(child_text(element, "ObjectID"))
    owner = f"Object {child_text(element, 'ObjectID') or '?'}{f' ({name})' if name else ''}"
    problems: List[str] = []
    if object_id is None:
        problems.append(f"{owner} has no valid ObjectID (0–{_ID_LIMIT})")
    if not name:
        problems.append(f"{owner} has no Name")
    multiple = _flag(child_text(element, "MultipleInstances"), true="Multiple", false="Single", default=False)
    if multiple is None:
        problems.append(
            f"{owner} has MultipleInstances {child_text(element, 'MultipleInstances')!r}; expected Single or Multiple"
        )
    mandatory = _flag(child_text(element, "Mandatory"), true="Mandatory", false="Optional", default=False)
    if mandatory is None:
        problems.append(f"{owner} has Mandatory {child_text(element, 'Mandatory')!r}; expected Mandatory or Optional")
    items = children(child(element, "Resources"), "Item")
    if not items:
        problems.append(f"{owner} has no resources, so it exposes nothing to import")
    resources = [resource for resource in (_read_resource(item, problems, owner) for item in items) if resource]
    seen: Dict[int, str] = {}
    for resource in resources:
        if resource.id in seen:
            problems.append(f"{owner} defines resource {resource.id} twice ({seen[resource.id]} and {resource.name})")
        seen[resource.id] = resource.name
    if problems:
        raise Lwm2mParseError(
            f"Invalid LwM2M object definition{_where(path)}: " + "; ".join(problems),
            code="INPUT_SEMANTIC_INVALID",
        )
    assert object_id is not None and name is not None and multiple is not None and mandatory is not None
    return Lwm2mObject(
        object_id=object_id,
        name=name,
        resources=tuple(resources),
        urn=child_text(element, "ObjectURN"),
        lwm2m_version=child_text(element, "LWM2MVersion"),
        object_version=child_text(element, "ObjectVersion"),
        multiple=multiple,
        mandatory=mandatory,
        description=child_text(element, "Description1"),
        description2=child_text(element, "Description2"),
        path=path,
    )


def _read_file(text: str, *, path: Optional[str]) -> List[Lwm2mObject]:
    """Read every object of one ``LWM2M`` document."""
    try:
        root = read_device_model_xml(text, source_label=path, kind="LwM2M object definition")
    except DeviceModelXmlError as exc:
        raise Lwm2mParseError(str(exc), code=exc.code) from exc
    root_name = root.tag.rsplit("}", 1)[-1]
    if root_name != ROOT_ELEMENT:
        hint = (
            " — it looks like a Matter cluster definition; import it as Matter" if root_name == "configurator" else ""
        )
        raise Lwm2mParseError(
            f"The document{_where(path)} has a <{root_name}> root, not <{ROOT_ELEMENT}>{hint}",
            code="FORMAT_MISMATCH",
        )
    elements = children(root, "Object")
    if not elements:
        raise Lwm2mParseError(
            f"The LwM2M document{_where(path)} defines no Object, so there is nothing to import",
            code="INPUT_SEMANTIC_INVALID",
        )
    return [_read_object(element, path) for element in elements]


def _check_unique(objects: List[Lwm2mObject]) -> None:
    seen: Dict[int, Lwm2mObject] = {}
    for obj in objects:
        if obj.object_id in seen:
            first = seen[obj.object_id]
            raise Lwm2mParseError(
                f"Object {obj.object_id} is defined twice ({first.name}{_where(first.path)} and "
                f"{obj.name}{_where(obj.path)})",
                code="INPUT_SEMANTIC_INVALID",
            )
        seen[obj.object_id] = obj


def parse_lwm2m_text(text: str, *, label: Optional[str] = None) -> Lwm2mDocument:
    """Parse one LwM2M object-definition file.

    Args:
        text: The file text.
        label: The upload's label (file name).

    Returns:
        The parsed document.

    Raises:
        Lwm2mParseError: See the module docstring.
    """
    objects = _read_file(text, path=label)
    _check_unique(objects)
    return Lwm2mDocument(objects=tuple(objects), label=label, sources={label or "document.xml": text})


def parse_lwm2m_fileset(fileset: IntakeFileset, *, label: Optional[str] = None) -> Lwm2mDocument:
    """Parse a set of object-definition files (the registry's one-file-per-object convention).

    Every ``.xml`` member whose root is ``LWM2M`` is read, the root member first; any other
    member (a README, a different XML vocabulary) is ignored.

    Args:
        fileset: The uploaded set.
        label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        Lwm2mParseError: See the module docstring; ``FORMAT_MISMATCH`` when the root member is
            not an LwM2M document.
    """
    ordered = [fileset.root] + sorted(path for path in fileset.members if path != fileset.root)
    objects: List[Lwm2mObject] = []
    sources: Dict[str, str] = {}
    for path in ordered:
        text = fileset.members[path]
        if path != fileset.root and (PurePosixPath(path).suffix.lower() != ".xml" or not is_lwm2m_document(text)):
            continue
        objects.extend(_read_file(text, path=path))
        sources[path] = text
    _check_unique(objects)
    return Lwm2mDocument(objects=tuple(objects), label=label or fileset.root, is_fileset=True, sources=sources)


def raw_record(document: Lwm2mDocument) -> Dict[str, Any]:
    """The lossless native record kept on ``CanonicalApi.raw``: every file's text."""
    return {"files": [{"path": path, "text": text} for path, text in sorted(document.sources.items())]}
