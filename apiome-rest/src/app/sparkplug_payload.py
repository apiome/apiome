"""Sparkplug B payload wire reader — FMT-9.2 (#5469).

Decodes the protobuf payload a Sparkplug B edge node publishes (Eclipse Tahu
``sparkplug_b.proto``, ``org.eclipse.tahu.protobuf.Payload``) without a protobuf runtime: the
schema is small and fixed, and reading it by hand lets the reader tell a **cut-off** payload from
a **broken** one, which a generated decoder cannot.

.. code-block:: text

    Payload          1 timestamp · 2 metrics[] · 3 seq · 4 uuid · 5 body
      Metric         1 name · 2 alias · 3 timestamp · 4 datatype · 5 is_historical ·
                     6 is_transient · 7 is_null · 8 metadata · 9 properties · 10–19 value
        MetaData     1 is_multi_part · 2 content_type · 3 size · 4 seq · 5 file_name ·
                     6 file_type · 7 md5 · 8 description
        PropertySet  1 keys[] · 2 values[] (PropertyValue: 1 type · 2 is_null · 3–10 value)
        DataSet      1 num_of_columns · 2 columns[] · 3 types[] · 4 rows[]
        Template     1 version · 2 metrics[] · 3 parameters[] · 4 template_ref · 5 is_definition

**Truncated vs malformed** (the IXH-7.5 rule the protobuf descriptor reader set): the top-level
elements are walked first, and one that runs past the end of the buffer — a tag, a varint or a
length-delimited body cut short — means the payload was **truncated**. Once every top-level element
fits, anything wrong *inside* a complete element (a wire type the schema does not allow, a nested
length that overruns its parent) is **malformed**.

Unknown fields are skipped — the schema reserves extension ranges — and counted, so the
normalizer can say that something was not read.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "DATATYPE_NAMES",
    "DataSetColumn",
    "SparkplugDataSet",
    "SparkplugMetaData",
    "SparkplugMetric",
    "SparkplugParameter",
    "SparkplugPayload",
    "SparkplugPropertyValue",
    "SparkplugTemplate",
    "SparkplugWireError",
    "datatype_name",
    "decode_payload",
    "sniff_payload",
]

#: Sparkplug ``DataType`` enum value → its name (Sparkplug B 3.0, §6.4.16).
DATATYPE_NAMES: Dict[int, str] = {
    0: "Unknown",
    1: "Int8",
    2: "Int16",
    3: "Int32",
    4: "Int64",
    5: "UInt8",
    6: "UInt16",
    7: "UInt32",
    8: "UInt64",
    9: "Float",
    10: "Double",
    11: "Boolean",
    12: "String",
    13: "DateTime",
    14: "Text",
    15: "UUID",
    16: "DataSet",
    17: "Bytes",
    18: "File",
    19: "Template",
    20: "PropertySet",
    21: "PropertySetList",
    22: "Int8Array",
    23: "Int16Array",
    24: "Int32Array",
    25: "Int64Array",
    26: "UInt8Array",
    27: "UInt16Array",
    28: "UInt32Array",
    29: "UInt64Array",
    30: "FloatArray",
    31: "DoubleArray",
    32: "BooleanArray",
    33: "StringArray",
    34: "DateTimeArray",
}

_VARINT = 0
_FIXED64 = 1
_LEN = 2
_FIXED32 = 5

#: Payload top-level fields the schema defines (6+ is the extension range).
_PAYLOAD_FIELDS = frozenset({1, 2, 3, 4, 5})


class SparkplugWireError(ValueError):
    """A payload could not be decoded.

    Attributes:
        code: Intake-taxonomy code — ``INPUT_TRUNCATED`` for a payload cut short,
            ``INPUT_MALFORMED`` for a broken one, ``INPUT_EMPTY`` for no bytes at all.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


def datatype_name(value: Optional[int]) -> Optional[str]:
    """The Sparkplug name of a ``DataType`` enum value.

    Args:
        value: The wire value, or ``None`` when the metric declared none.

    Returns:
        The name (``"Double"``), ``None`` for no value, or ``"DataType(<n>)"`` for a value outside
        the enum so the caller can report it rather than guess.
    """
    if value is None:
        return None
    return DATATYPE_NAMES.get(value, f"DataType({value})")


@dataclass(frozen=True)
class SparkplugMetaData:
    """A metric's ``MetaData`` message (only the fields that were present are set)."""

    is_multi_part: Optional[bool] = None
    content_type: Optional[str] = None
    size: Optional[int] = None
    seq: Optional[int] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    md5: Optional[str] = None
    description: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        """The present fields under their Sparkplug JSON names."""
        pairs = (
            ("isMultiPart", self.is_multi_part),
            ("contentType", self.content_type),
            ("size", self.size),
            ("seq", self.seq),
            ("fileName", self.file_name),
            ("fileType", self.file_type),
            ("md5", self.md5),
            ("description", self.description),
        )
        return {key: value for key, value in pairs if value is not None}


@dataclass(frozen=True)
class SparkplugPropertyValue:
    """One ``PropertyValue``: its declared type and its value (nested sets as dicts / lists)."""

    type: Optional[int]
    value: object = None
    is_null: bool = False


@dataclass(frozen=True)
class DataSetColumn:
    """One ``DataSet`` column: its name and its declared datatype."""

    name: str
    datatype: Optional[int]


@dataclass(frozen=True)
class SparkplugDataSet:
    """A ``DataSet`` value: its columns and how many rows it carried."""

    columns: Tuple[DataSetColumn, ...]
    row_count: int


@dataclass(frozen=True)
class SparkplugParameter:
    """One template ``Parameter``: its name and declared datatype."""

    name: str
    datatype: Optional[int]


@dataclass(frozen=True)
class SparkplugTemplate:
    """A ``Template`` value — a definition (``is_definition``) or an instance of one."""

    version: Optional[str]
    metrics: Tuple["SparkplugMetric", ...]
    parameters: Tuple[SparkplugParameter, ...]
    template_ref: Optional[str]
    is_definition: bool


@dataclass(frozen=True)
class SparkplugMetric:
    """One decoded ``Metric``.

    Attributes:
        name: The metric name; ``None`` for an alias-only metric (a DATA message after a BIRTH).
        alias: The numeric alias, when one was sent.
        timestamp: The metric's own timestamp (ms since the epoch).
        datatype: The ``DataType`` enum value; ``None`` when the metric sent none.
        is_historical / is_transient / is_null: The metric's flags.
        metadata: The ``MetaData`` message, when present.
        properties: The ``PropertySet`` as ``key → PropertyValue`` in wire order.
        value_field: Which value field carried the value (``"double_value"`` …), or ``None``.
        value: The decoded scalar value (a ``bytes`` value is kept as its length only).
        dataset: The ``DataSet`` value's shape, when the value is one.
        template: The ``Template`` value, when the value is one.
        unknown_fields: How many fields outside the schema were skipped inside the metric.
    """

    name: Optional[str] = None
    alias: Optional[int] = None
    timestamp: Optional[int] = None
    datatype: Optional[int] = None
    is_historical: bool = False
    is_transient: bool = False
    is_null: bool = False
    metadata: Optional[SparkplugMetaData] = None
    properties: Tuple[Tuple[str, SparkplugPropertyValue], ...] = ()
    value_field: Optional[str] = None
    value: object = None
    dataset: Optional[SparkplugDataSet] = None
    template: Optional[SparkplugTemplate] = None
    unknown_fields: int = 0


@dataclass(frozen=True)
class SparkplugPayload:
    """One decoded ``Payload``."""

    timestamp: Optional[int] = None
    metrics: Tuple[SparkplugMetric, ...] = ()
    seq: Optional[int] = None
    uuid: Optional[str] = None
    body_length: Optional[int] = None
    unknown_fields: int = 0
    size: int = 0


# ---------------------------------------------------------------------------
# Wire primitives
# ---------------------------------------------------------------------------


class _OverrunError(Exception):
    """An element ran past the end of the buffer it was read from."""


def _varint(data: bytes, offset: int) -> Tuple[int, int]:
    """Read one base-128 varint, returning ``(value, next offset)``."""
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise _OverrunError()
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
        if shift >= 70:
            raise SparkplugWireError("A varint is longer than ten bytes")


@dataclass(frozen=True)
class _Element:
    """One wire element: field number, wire type and its value (an int or the raw bytes)."""

    number: int
    wire_type: int
    value: object


def _elements(data: bytes) -> List[_Element]:
    """Split ``data`` into wire elements.

    Raises:
        _OverrunError: An element runs past the end of ``data``.
        SparkplugWireError: A wire type the protobuf encoding does not define, or field 0.
    """
    elements: List[_Element] = []
    offset = 0
    while offset < len(data):
        key, offset = _varint(data, offset)
        number, wire_type = key >> 3, key & 0x7
        if number == 0:
            raise SparkplugWireError("A field number of 0 is not a valid protobuf field")
        if wire_type == _VARINT:
            value, offset = _varint(data, offset)
            elements.append(_Element(number, wire_type, value))
        elif wire_type == _FIXED64:
            if offset + 8 > len(data):
                raise _OverrunError()
            elements.append(_Element(number, wire_type, data[offset : offset + 8]))
            offset += 8
        elif wire_type == _FIXED32:
            if offset + 4 > len(data):
                raise _OverrunError()
            elements.append(_Element(number, wire_type, data[offset : offset + 4]))
            offset += 4
        elif wire_type == _LEN:
            length, offset = _varint(data, offset)
            if offset + length > len(data):
                raise _OverrunError()
            elements.append(_Element(number, wire_type, data[offset : offset + length]))
            offset += length
        else:
            raise SparkplugWireError(f"Field {number} uses wire type {wire_type}, which protobuf does not define")
    return elements


def _nested(data: bytes, where: str) -> List[_Element]:
    """Split a nested message; inside a complete parent, an overrun is malformed, not truncated."""
    try:
        return _elements(data)
    except _OverrunError:
        raise SparkplugWireError(f"{where}: a field runs past the end of its enclosing message") from None
    except SparkplugWireError as exc:
        raise SparkplugWireError(f"{where}: {exc}") from None


def _expect(element: _Element, wire_type: int, where: str, name: str) -> None:
    """Reject a known field sent with the wrong wire type."""
    if element.wire_type != wire_type:
        raise SparkplugWireError(
            f"{where}: field {element.number} ({name}) has wire type {element.wire_type}, "
            f"the schema declares {wire_type}"
        )


def _text(element: _Element, where: str, name: str) -> str:
    """Decode a ``string`` field as UTF-8."""
    _expect(element, _LEN, where, name)
    assert isinstance(element.value, bytes)
    try:
        return element.value.decode("utf-8")
    except UnicodeDecodeError:
        raise SparkplugWireError(f"{where}: {name} is not valid UTF-8") from None


def _int(element: _Element, where: str, name: str) -> int:
    _expect(element, _VARINT, where, name)
    assert isinstance(element.value, int)
    return element.value


def _float(element: _Element, where: str, name: str) -> float:
    _expect(element, _FIXED32, where, name)
    assert isinstance(element.value, bytes)
    return float(struct.unpack("<f", element.value)[0])


def _double(element: _Element, where: str, name: str) -> float:
    _expect(element, _FIXED64, where, name)
    assert isinstance(element.value, bytes)
    return float(struct.unpack("<d", element.value)[0])


def _bytes(element: _Element, where: str, name: str) -> bytes:
    _expect(element, _LEN, where, name)
    assert isinstance(element.value, bytes)
    return element.value


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _metadata(data: bytes, where: str) -> SparkplugMetaData:
    """Decode a ``MetaData`` message (extensions 9+ are skipped)."""
    values: Dict[str, object] = {}
    for element in _nested(data, where):
        number = element.number
        if number == 1:
            values["is_multi_part"] = bool(_int(element, where, "is_multi_part"))
        elif number in (2, 5, 6, 7, 8):
            name = {2: "content_type", 5: "file_name", 6: "file_type", 7: "md5", 8: "description"}[number]
            values[name] = _text(element, where, name)
        elif number in (3, 4):
            name = "size" if number == 3 else "seq"
            values[name] = _int(element, where, name)
    return SparkplugMetaData(**values)  # type: ignore[arg-type]


def _property_value(data: bytes, where: str) -> SparkplugPropertyValue:
    """Decode a ``PropertyValue`` (nested property sets become dicts / lists of dicts)."""
    type_: Optional[int] = None
    is_null = False
    value: object = None
    for element in _nested(data, where):
        number = element.number
        if number == 1:
            type_ = _int(element, where, "type")
        elif number == 2:
            is_null = bool(_int(element, where, "is_null"))
        elif number in (3, 4):
            value = _int(element, where, "int_value" if number == 3 else "long_value")
        elif number == 5:
            value = _float(element, where, "float_value")
        elif number == 6:
            value = _double(element, where, "double_value")
        elif number == 7:
            value = bool(_int(element, where, "boolean_value"))
        elif number == 8:
            value = _text(element, where, "string_value")
        elif number == 9:
            value = _property_dict(_property_set(_bytes(element, where, "propertyset_value"), where))
        elif number == 10:
            value = [
                _property_dict(_property_set(_bytes(item, where, "propertyset"), where))
                for item in _nested(_bytes(element, where, "propertysets_value"), where)
                if item.number == 1
            ]
    return SparkplugPropertyValue(type=type_, value=value, is_null=is_null)


def _property_dict(pairs: Tuple[Tuple[str, SparkplugPropertyValue], ...]) -> Dict[str, object]:
    """A property set's plain ``key → value`` view."""
    return {key: (None if item.is_null else item.value) for key, item in pairs}


def _property_set(data: bytes, where: str) -> Tuple[Tuple[str, SparkplugPropertyValue], ...]:
    """Decode a ``PropertySet``, pairing its parallel ``keys`` and ``values`` lists."""
    keys: List[str] = []
    values: List[SparkplugPropertyValue] = []
    for element in _nested(data, where):
        if element.number == 1:
            keys.append(_text(element, where, "keys"))
        elif element.number == 2:
            values.append(_property_value(_bytes(element, where, "values"), f"{where}, property {len(values) + 1}"))
    if len(keys) != len(values):
        raise SparkplugWireError(f"{where}: the property set has {len(keys)} key(s) but {len(values)} value(s)")
    return tuple(zip(keys, values))


def _dataset(data: bytes, where: str) -> SparkplugDataSet:
    """Decode a ``DataSet``'s shape: column names and types, and how many rows it carried."""
    columns: List[str] = []
    types: List[int] = []
    rows = 0
    declared: Optional[int] = None
    for element in _nested(data, where):
        if element.number == 1:
            declared = _int(element, where, "num_of_columns")
        elif element.number == 2:
            columns.append(_text(element, where, "columns"))
        elif element.number == 3:
            if element.wire_type == _LEN:
                # ``repeated uint32`` may arrive packed.
                packed = _bytes(element, where, "types")
                offset = 0
                while offset < len(packed):
                    try:
                        value, offset = _varint(packed, offset)
                    except _OverrunError:
                        raise SparkplugWireError(f"{where}: a packed column type is cut short") from None
                    types.append(value)
            else:
                types.append(_int(element, where, "types"))
        elif element.number == 4:
            _expect(element, _LEN, where, "rows")
            rows += 1
    if types and len(types) != len(columns):
        raise SparkplugWireError(f"{where}: the data set names {len(columns)} column(s) but types {len(types)}")
    if declared is not None and declared != len(columns):
        raise SparkplugWireError(f"{where}: num_of_columns is {declared} but {len(columns)} column(s) are named")
    return SparkplugDataSet(
        columns=tuple(
            DataSetColumn(name=name, datatype=types[index] if index < len(types) else None)
            for index, name in enumerate(columns)
        ),
        row_count=rows,
    )


def _template(data: bytes, where: str) -> SparkplugTemplate:
    """Decode a ``Template`` (its metrics recursively)."""
    version: Optional[str] = None
    metrics: List[SparkplugMetric] = []
    parameters: List[SparkplugParameter] = []
    template_ref: Optional[str] = None
    is_definition = False
    for element in _nested(data, where):
        number = element.number
        if number == 1:
            version = _text(element, where, "version")
        elif number == 2:
            metrics.append(_metric(_bytes(element, where, "metrics"), f"{where}, member {len(metrics) + 1}"))
        elif number == 3:
            parameters.append(_parameter(_bytes(element, where, "parameters"), where))
        elif number == 4:
            template_ref = _text(element, where, "template_ref")
        elif number == 5:
            is_definition = bool(_int(element, where, "is_definition"))
    return SparkplugTemplate(
        version=version,
        metrics=tuple(metrics),
        parameters=tuple(parameters),
        template_ref=template_ref,
        is_definition=is_definition,
    )


def _parameter(data: bytes, where: str) -> SparkplugParameter:
    """Decode a template ``Parameter``'s name and type (its value is a default, not read)."""
    name = ""
    type_: Optional[int] = None
    for element in _nested(data, where):
        if element.number == 1:
            name = _text(element, where, "name")
        elif element.number == 2:
            type_ = _int(element, where, "type")
    return SparkplugParameter(name=name, datatype=type_)


#: Metric value field number → (name, decoder).
_VALUE_FIELDS = {
    10: "int_value",
    11: "long_value",
    12: "float_value",
    13: "double_value",
    14: "boolean_value",
    15: "string_value",
    16: "bytes_value",
    17: "dataset_value",
    18: "template_value",
    19: "extension_value",
}


def _metric(data: bytes, where: str) -> SparkplugMetric:
    """Decode one ``Metric``."""
    values: Dict[str, object] = {}
    unknown = 0
    for element in _nested(data, where):
        number = element.number
        if number == 1:
            values["name"] = _text(element, where, "name")
        elif number in (2, 3, 4):
            name = {2: "alias", 3: "timestamp", 4: "datatype"}[number]
            values[name] = _int(element, where, name)
        elif number in (5, 6, 7):
            name = {5: "is_historical", 6: "is_transient", 7: "is_null"}[number]
            values[name] = bool(_int(element, where, name))
        elif number == 8:
            values["metadata"] = _metadata(_bytes(element, where, "metadata"), f"{where}, metadata")
        elif number == 9:
            values["properties"] = _property_set(_bytes(element, where, "properties"), f"{where}, properties")
        elif number in _VALUE_FIELDS:
            field_name = _VALUE_FIELDS[number]
            values["value_field"] = field_name
            if number in (10, 11):
                values["value"] = _int(element, where, field_name)
            elif number == 12:
                values["value"] = _float(element, where, field_name)
            elif number == 13:
                values["value"] = _double(element, where, field_name)
            elif number == 14:
                values["value"] = bool(_int(element, where, field_name))
            elif number == 15:
                values["value"] = _text(element, where, field_name)
            elif number == 16:
                values["value"] = len(_bytes(element, where, field_name))
            elif number == 17:
                values["dataset"] = _dataset(_bytes(element, where, field_name), f"{where}, data set")
            elif number == 18:
                values["template"] = _template(_bytes(element, where, field_name), f"{where}, template")
            else:
                _expect(element, _LEN, where, field_name)
        else:
            unknown += 1
    return SparkplugMetric(unknown_fields=unknown, **values)  # type: ignore[arg-type]


def decode_payload(data: bytes) -> SparkplugPayload:
    """Decode one Sparkplug B payload.

    Args:
        data: The raw payload bytes (an MQTT message body).

    Returns:
        The decoded payload.

    Raises:
        SparkplugWireError: ``INPUT_EMPTY`` for no bytes; ``INPUT_TRUNCATED`` when a top-level
            element runs past the end of the buffer; ``INPUT_MALFORMED`` for anything wrong inside
            a complete element, or a known field with the wrong wire type.
    """
    if not data:
        raise SparkplugWireError("The Sparkplug payload is empty", code="INPUT_EMPTY")
    try:
        elements = _elements(data)
    except _OverrunError:
        raise SparkplugWireError(
            f"The Sparkplug payload is truncated: an element runs past the end of the {len(data)}-byte buffer",
            code="INPUT_TRUNCATED",
        ) from None
    where = "Payload"
    timestamp: Optional[int] = None
    seq: Optional[int] = None
    uuid: Optional[str] = None
    body_length: Optional[int] = None
    metrics: List[SparkplugMetric] = []
    unknown = 0
    for element in elements:
        number = element.number
        if number == 1:
            timestamp = _int(element, where, "timestamp")
        elif number == 2:
            metrics.append(_metric(_bytes(element, where, "metrics"), f"Metric {len(metrics) + 1}"))
        elif number == 3:
            seq = _int(element, where, "seq")
        elif number == 4:
            uuid = _text(element, where, "uuid")
        elif number == 5:
            body_length = len(_bytes(element, where, "body"))
        else:
            unknown += 1
    return SparkplugPayload(
        timestamp=timestamp,
        metrics=tuple(metrics),
        seq=seq,
        uuid=uuid,
        body_length=body_length,
        unknown_fields=unknown,
        size=len(data),
    )


def sniff_payload(data: Optional[bytes]) -> bool:
    """Whether ``data`` is, with high likelihood, a Sparkplug B payload.

    A payload must decode completely, use only the schema's top-level fields (1–5), carry at least
    one metric, and every metric must be addressable (a name or an alias) with a datatype inside
    the enum when it sends one. Random binary — and a protobuf ``FileDescriptorSet``, whose field 1
    is a message rather than a timestamp — fails at least one of those.

    Args:
        data: The undecoded upload, or ``None``.

    Returns:
        ``True`` for a payload this reader would accept.
    """
    if not data:
        return False
    try:
        elements = _elements(data)
        if any(element.number not in _PAYLOAD_FIELDS for element in elements):
            return False
        payload = decode_payload(data)
    except (SparkplugWireError, _OverrunError):
        return False
    if not payload.metrics:
        return False
    for metric in payload.metrics:
        if metric.name is None and metric.alias is None:
            return False
        if metric.datatype is not None and metric.datatype not in DATATYPE_NAMES:
            return False
    return True
