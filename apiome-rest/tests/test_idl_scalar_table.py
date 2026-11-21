"""Every canonical scalar × the asn1, avro, corbaidl, flatbuffers, typespec, wsdl and xsd targets — COA-3.2 (#7053).

The canonical model keeps each source's scalar spelling (:data:`app.canonical_json_schema.CANONICAL_SCALAR_SCHEMAS`
lists them), and the OpenAPI normalizer puts a JSON Schema ``integer`` / ``number``'s width in the field's
``format``. These targets either wrote some spellings as something else (Avro ``fixed32`` → ``string``) or ignored
the ``format`` (Avro ``integer`` + ``int64`` → ``int``, FlatBuffers ``int`` + ``int64`` → ``int``).

These tests cover:

* :data:`_TABLE` — the type each target writes for every spelling (and each width ``format``), field by field,
  emitted through :func:`app.export_service.emit_canonical`; a new spelling must be added here;
* :mod:`app.scalar_aliases` — the per-target kind tables and :func:`~app.scalar_aliases.format_kind`;
* narrowing — a 64-bit ``format`` is never written narrower, and a type too small for its scalar (Avro
  ``uint64`` / ``bigint`` / ``decimal``, FlatBuffers ``bigint`` / ``decimal``) is a reported loss;
* the all-scalars record compiles in each target's own validator (asn1tools, fastavro, xmlschema …).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Dict, List, Optional, Tuple

import pytest

from app.avro_emitter import AvroEmitter
from app.canonical_json_schema import CANONICAL_SCALAR_SCHEMAS
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from app.export_service import emit_canonical
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind
from app.scalar_aliases import (
    ASN1_SCALAR_FOR_KIND,
    AVRO_SCALAR_FOR_KIND,
    CAPNP_SCALAR_FOR_KIND,
    FLATBUFFERS_SCALAR_FOR_KIND,
    INTEGER_RANGE_FOR_KIND,
    OMG_IDL_SCALAR_FOR_KIND,
    PROTO_SCALAR_FOR_KIND,
    SMITHY_SCALAR_FOR_KIND,
    THRIFT_SCALAR_FOR_KIND,
    TYPESPEC_SCALAR_FOR_KIND,
    XSD_SCALAR_FOR_KIND,
    format_kind,
    scalar_kind,
)

#: The targets, in the column order of :data:`_TABLE` (WSDL shares the XSD column).
_TARGETS = ("asn1", "avro", "corbaidl", "flatbuffers", "typespec", "xsd")

_I32 = "INTEGER (-2147483648..2147483647)"
_I64 = "INTEGER (-9223372036854775808..9223372036854775807)"
_U32 = "INTEGER (0..4294967295)"
_U64 = "INTEGER (0..18446744073709551615)"

#: Spelling (``name`` or ``name/format``) → the type each target writes for a field of it. ``None`` means the
#: field is not written (it holds no value) — and the loss is reported (see the tests below).
_TABLE: Dict[str, Tuple[Optional[str], ...]] = {
    # name             asn1                       avro       corbaidl                flatbuffers typespec       xsd
    "string": ("UTF8String", "string", "string", "string", "string", "string"),
    "str": ("UTF8String", "string", "string", "string", "string", "string"),
    "text": ("UTF8String", "string", "string", "string", "string", "string"),
    "char": ("UTF8String", "string", "string", "string", "string", "string"),
    "id": ("UTF8String", "string", "string", "string", "string", "ID"),
    "uuid": ("UTF8String", "string", "string", "string", "string", "string"),
    "guid": ("UTF8String", "string", "string", "string", "string", "string"),
    "uri": ("UTF8String", "string", "string", "string", "url", "anyURI"),
    "url": ("UTF8String", "string", "string", "string", "url", "anyURI"),
    "email": ("UTF8String", "string", "string", "string", "string", "string"),
    "hostname": ("UTF8String", "string", "string", "string", "string", "string"),
    "ipv4": ("UTF8String", "string", "string", "string", "string", "string"),
    "ipv6": ("UTF8String", "string", "string", "string", "string", "string"),
    "date": ("DATE", "string", "string", "string", "plainDate", "date"),
    "time": ("TIME-OF-DAY", "string", "string", "string", "plainTime", "time"),
    "datetime": ("GeneralizedTime", "string", "string", "string", "utcDateTime", "dateTime"),
    "date-time": ("GeneralizedTime", "string", "string", "string", "utcDateTime", "dateTime"),
    "timestamp": ("GeneralizedTime", "string", "string", "string", "utcDateTime", "dateTime"),
    "instant": ("GeneralizedTime", "string", "string", "string", "utcDateTime", "dateTime"),
    "duration": ("UTF8String", "string", "string", "string", "duration", "duration"),
    "bytes": ("OCTET STRING", "bytes", "sequence<octet>", "[ubyte]", "bytes", "base64Binary"),
    "binary": ("OCTET STRING", "bytes", "sequence<octet>", "[ubyte]", "bytes", "base64Binary"),
    "blob": ("OCTET STRING", "bytes", "sequence<octet>", "[ubyte]", "bytes", "base64Binary"),
    "integer": ("INTEGER", "int", "long", "long", "int32", "int"),
    "int": ("INTEGER", "int", "long", "int", "int32", "int"),
    "byte": ("INTEGER (-128..127)", "int", "short", "byte", "int8", "byte"),
    "sbyte": ("INTEGER (-128..127)", "int", "short", "byte", "int8", "byte"),
    "i8": ("INTEGER (-128..127)", "int", "short", "byte", "int8", "byte"),
    "int8": ("INTEGER (-128..127)", "int", "short", "byte", "int8", "byte"),
    "uint8": ("INTEGER (0..255)", "int", "octet", "ubyte", "uint8", "unsignedByte"),
    "short": ("INTEGER (-32768..32767)", "int", "short", "short", "int16", "short"),
    "i16": ("INTEGER (-32768..32767)", "int", "short", "short", "int16", "short"),
    "int16": ("INTEGER (-32768..32767)", "int", "short", "short", "int16", "short"),
    "uint16": ("INTEGER (0..65535)", "int", "unsigned short", "ushort", "uint16", "unsignedShort"),
    "i32": (_I32, "int", "long", "int", "int32", "int"),
    "int32": (_I32, "int", "long", "int", "int32", "int"),
    "uint32": (_U32, "long", "unsigned long", "uint", "uint32", "unsignedInt"),
    "fixed32": (_U32, "long", "unsigned long", "uint", "uint32", "unsignedInt"),
    "sfixed32": (_I32, "int", "long", "int", "int32", "int"),
    "sint32": (_I32, "int", "long", "int", "int32", "int"),
    "i64": (_I64, "long", "long long", "long", "int64", "long"),
    "int64": (_I64, "long", "long long", "long", "int64", "long"),
    "uint64": (_U64, "long", "unsigned long long", "ulong", "uint64", "unsignedLong"),
    "fixed64": (_U64, "long", "unsigned long long", "ulong", "uint64", "unsignedLong"),
    "sfixed64": (_I64, "long", "long long", "long", "int64", "long"),
    "sint64": (_I64, "long", "long long", "long", "int64", "long"),
    "long": (_I64, "long", "long long", "long", "int64", "long"),
    "bigint": ("INTEGER", "long", "string", "long", "integer", "integer"),
    "number": ("REAL", "double", "double", "double", "float64", "double"),
    "float": ("REAL", "float", "float", "float", "float32", "float"),
    "f32": ("REAL", "float", "float", "float", "float32", "float"),
    "double": ("REAL", "double", "double", "double", "float64", "double"),
    "f64": ("REAL", "double", "double", "double", "float64", "double"),
    "decimal": ("REAL", "double", "string", "double", "decimal", "decimal"),
    "boolean": ("BOOLEAN", "boolean", "boolean", "bool", "boolean", "boolean"),
    "bool": ("BOOLEAN", "boolean", "boolean", "bool", "boolean", "boolean"),
    "null": ("NULL", "null", "string", None, "null", "string"),
    "void": ("NULL", "null", None, None, "null", "string"),
    "none": ("NULL", "null", "string", None, "null", "string"),
    # a JSON Schema integer / number with a width format
    "integer/int32": (_I32, "int", "long", "int", "int32", "int"),
    "integer/int64": (_I64, "long", "long long", "long", "int64", "long"),
    "int/int64": (_I64, "long", "long long", "long", "int64", "long"),
    "number/float": ("REAL", "float", "float", "float", "float32", "float"),
    "number/double": ("REAL", "double", "double", "double", "float64", "double"),
}

#: How to read the field ``f``'s type out of each target's text.
_FIELD_TYPE = {
    "asn1": re.compile(r"^\s*f (.+?)(?: OPTIONAL)?,?$", re.M),
    "corbaidl": re.compile(r"^\s*(?:@optional )?(.+) f;$", re.M),
    "flatbuffers": re.compile(r"^\s*f: (.+?) \(id", re.M),
    "typespec": re.compile(r"^\s*f\?: (.+);$", re.M),
    "wsdl": re.compile(r'name="f"[^>]*type="xsd:([^"]+)"'),
    "xsd": re.compile(r'name="f"[^>]*type="xsd:([^"]+)"'),
}


def _spelling(entry: str) -> Tuple[str, Optional[str]]:
    """``"integer/int64"`` → ``("integer", "int64")``; ``"bool"`` → ``("bool", None)``."""
    name, _, fmt = entry.partition("/")
    return name, fmt or None


def _record(fields: List[CanonicalField]) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="json-schema",
        identity=ApiIdentity(name="W"),
        types=[Type(key="W", name="W", kind=TypeKind.RECORD, fields=fields)],
    )


def _field(name: str, type_name: str, fmt: Optional[str] = None) -> CanonicalField:
    return CanonicalField(
        key=f"W.{name}",
        name=name,
        type=TypeRef(name=type_name),
        constraints=Constraints(format=fmt) if fmt else None,
    )


def _written(target: str, entry: str) -> Tuple[Optional[str], List[str]]:
    """The type ``target`` writes for a field ``f`` of ``entry``, and the emit's loss subjects."""
    name, fmt = _spelling(entry)
    result = emit_canonical(_record([_field("f", name, fmt)]), target)
    subjects = [loss.subject for loss in result.losses or []]
    content = result.files[0].content
    if target == "avro":
        doc = content if isinstance(content, dict) else json.loads(str(content))
        written = doc["fields"][0]["type"]
        if isinstance(written, list):  # ["null", T]: the nullable union around the type
            written = next((branch for branch in written if branch != "null"), "null")
        return (written if isinstance(written, str) else json.dumps(written)), subjects
    text = "\n".join(str(f.content) for f in result.files)
    match = _FIELD_TYPE[target].search(text)
    return (match.group(1) if match else None), subjects


# ===========================================================================
# The table
# ===========================================================================


def test_the_table_lists_every_canonical_scalar() -> None:
    """A spelling added to the canonical vocabulary must be mapped here for every target."""
    names = {_spelling(entry)[0] for entry in _TABLE}
    assert names == set(CANONICAL_SCALAR_SCHEMAS)
    assert all(len(row) == len(_TARGETS) for row in _TABLE.values())


@pytest.mark.parametrize("target", [*_TARGETS, "wsdl"])
@pytest.mark.parametrize("entry", list(_TABLE))
def test_every_scalar_maps_to_the_targets_own_type(target: str, entry: str) -> None:
    column = _TARGETS.index("xsd" if target == "wsdl" else target)
    written, _ = _written(target, entry)
    assert written == _TABLE[entry][column]


#: Every type each target may write for a scalar: its kind table, plus the types its own spellings use.
_WRITABLE = {
    "asn1": set(ASN1_SCALAR_FOR_KIND.values()) | {"DATE", "TIME-OF-DAY", "GeneralizedTime", "NULL"},
    "avro": set(AVRO_SCALAR_FOR_KIND.values()) | {"null"},
    "corbaidl": set(OMG_IDL_SCALAR_FOR_KIND.values()),
    "flatbuffers": set(FLATBUFFERS_SCALAR_FOR_KIND.values()),
    "typespec": set(TYPESPEC_SCALAR_FOR_KIND.values())
    | {"url", "plainDate", "plainTime", "utcDateTime", "duration", "integer", "decimal", "null"},
    "xsd": set(XSD_SCALAR_FOR_KIND.values()) | {"ID", "anyURI", "date", "time", "dateTime", "duration", "integer",
                                                "decimal"},
}


@pytest.mark.parametrize("target", _TARGETS)
def test_no_spelling_is_written_as_a_type_the_target_lacks(target: str) -> None:
    """The bug class (#6278): a canonical name (``integer``, ``boolean``, ``fixed32``) reaching the output as is."""
    column = _TARGETS.index(target)
    written = {row[column].split(" (")[0] for row in _TABLE.values() if row[column] is not None}
    assert written <= _WRITABLE[target]


# ===========================================================================
# app.scalar_aliases
# ===========================================================================


@pytest.mark.parametrize(
    "table",
    [
        PROTO_SCALAR_FOR_KIND,
        THRIFT_SCALAR_FOR_KIND,
        CAPNP_SCALAR_FOR_KIND,
        OMG_IDL_SCALAR_FOR_KIND,
        SMITHY_SCALAR_FOR_KIND,
        AVRO_SCALAR_FOR_KIND,
        FLATBUFFERS_SCALAR_FOR_KIND,
        ASN1_SCALAR_FOR_KIND,
        TYPESPEC_SCALAR_FOR_KIND,
        XSD_SCALAR_FOR_KIND,
    ],
)
def test_every_target_table_covers_every_kind(table) -> None:
    from app.scalar_aliases import _FIXED_KINDS

    assert set(table) == set(_FIXED_KINDS.values())


def test_every_integer_kind_has_a_range() -> None:
    integers = {kind for kind in AVRO_SCALAR_FOR_KIND if kind.startswith(("int", "uint"))}
    assert set(INTEGER_RANGE_FOR_KIND) == integers
    assert INTEGER_RANGE_FOR_KIND["uint64"] == (0, 2**64 - 1)


@pytest.mark.parametrize(
    ("name", "fmt", "kind"),
    [
        ("integer", "int64", "int64"),
        ("Integer", "INT64", "int64"),  # case-insensitive
        ("int", "int64", "int64"),
        ("integer", "int32", "int32"),
        ("number", "float", "float"),
        ("number", "double", "double"),
        ("integer", None, None),  # a bare integer is the emitter's choice
        ("integer", "uuid", None),  # a format that is not a width
        ("int64", "int32", None),  # only JSON Schema's integer / number take their width from format
        ("string", "int64", None),
        (None, "int64", None),
    ],
)
def test_format_kind(name: Optional[str], fmt: Optional[str], kind: Optional[str]) -> None:
    assert format_kind(name, fmt) == kind


@pytest.mark.parametrize(("name", "kind"), [("fixed32", "uint32"), ("fixed64", "uint64"), ("blob", "bytes"),
                                            ("u8", "uint8"), ("u64", "uint64")])
def test_new_spellings_have_their_kind(name: str, kind: str) -> None:
    """Protobuf's ``fixed32`` / ``fixed64`` are unsigned; ``blob`` is binary; ``u8`` … ``u64`` are unsigned."""
    assert scalar_kind(name) == kind


# ===========================================================================
# Narrowing
# ===========================================================================


_WIDTH_64 = {
    "asn1": {_I64, _U64, "INTEGER"},
    "avro": {"long"},
    "corbaidl": {"long long", "unsigned long long"},
    "flatbuffers": {"long", "ulong"},
    "typespec": {"int64", "uint64", "integer"},
    "xsd": {"long", "unsignedLong", "integer"},
}


@pytest.mark.parametrize("target", _TARGETS)
def test_a_64_bit_integer_is_never_written_narrower(target: str) -> None:
    column = _TARGETS.index(target)
    for entry, row in _TABLE.items():
        name, fmt = _spelling(entry)
        if (format_kind(name, fmt) or scalar_kind(name)) in ("int64", "uint64"):
            assert row[column] in _WIDTH_64[target], (entry, row[column])


@pytest.mark.parametrize(
    ("target", "entry"),
    [
        ("avro", "uint64"),
        ("avro", "fixed64"),
        ("avro", "bigint"),
        ("avro", "decimal"),
        ("flatbuffers", "bigint"),
        ("flatbuffers", "decimal"),
    ],
)
def test_a_type_too_small_for_its_scalar_is_a_reported_loss(target: str, entry: str) -> None:
    _, subjects = _written(target, entry)
    assert "precision-narrowed" in subjects


@pytest.mark.parametrize(
    ("target", "entry"),
    [("avro", "int64"), ("avro", "integer/int64"), ("avro", "uint32"), ("flatbuffers", "uint64")],
)
def test_a_type_that_holds_its_scalar_reports_nothing(target: str, entry: str) -> None:
    _, subjects = _written(target, entry)
    assert "precision-narrowed" not in subjects


def test_an_avro_decimal_with_a_logical_type_is_not_narrowed() -> None:
    """A ``decimal`` format is Avro's ``bytes`` + ``decimal`` logical type, which keeps every digit."""
    written, subjects = _written("avro", "number/decimal")
    assert json.loads(written) == {"type": "bytes", "logicalType": "decimal"}
    assert "precision-narrowed" not in subjects


def test_the_avro_fidelity_report_names_the_narrowing() -> None:
    """The export preview predicts it too, on the field (and not on a 64-bit ``integer``)."""
    api = _record([_field("big", "uint64"), _field("ok", "integer", "int64")])
    report = compute_lossiness_for_emitter(api, AvroEmitter)
    narrowed = [item for item in report.items if item.target_mapping == "uint64 → long"]
    assert [item.construct_key for item in narrowed] == ["W.big"]
    assert narrowed[0].kind is LossinessKind.APPROX


def test_an_openapi_int64_keeps_its_width_in_every_target() -> None:
    """The issue's case: OpenAPI ``integer`` + ``format: int64`` (Avro wrote ``int``)."""
    for target in [*_TARGETS, "wsdl"]:
        written, _ = _written(target, "integer/int64")
        assert written in _WIDTH_64["xsd" if target == "wsdl" else target], target


# ===========================================================================
# CORBA: a void member
# ===========================================================================


def test_corba_leaves_out_a_member_that_holds_no_value() -> None:
    result = emit_canonical(_record([_field("f", "void"), _field("g", "string")]), "corbaidl")
    text = str(result.files[0].content)
    assert "void f;" not in text
    assert "string g;" in text
    assert [loss.pointer for loss in result.losses if loss.subject == "void-member-dropped"] == ["W.f"]


# ===========================================================================
# The all-scalars record compiles
# ===========================================================================


def _all_scalars() -> CanonicalApi:
    fields = []
    for index, entry in enumerate(_TABLE):
        name, fmt = _spelling(entry)
        fields.append(_field(f"f{index}", name, fmt))
    return _record(fields)


@pytest.mark.parametrize("target", [*_TARGETS, "wsdl"])
def test_the_all_scalars_record_is_valid_in_the_target(target: str) -> None:
    api = _all_scalars()
    verdict = asyncio.run(validate_emitted_artifact(target, emit_canonical(api, target), api=api))
    if not verdict.validated:
        pytest.skip(f"{target} validator not available here: {verdict.detail}")
    assert verdict.valid, verdict.errors
