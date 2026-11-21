"""Resolve the canonical model's scalar spellings to a target's own scalar types — #6278.

The canonical model has no single scalar vocabulary: each normalizer keeps its source format's
spelling (:data:`app.canonical_json_schema.CANONICAL_SCALAR_SCHEMAS` lists the ones in use). The
OpenAPI normalizer keeps JSON Schema's ``integer``, ``number`` and ``boolean``, with the width in the
field's ``format`` constraint (``int64``, ``float``). An emitter that only knows its own keywords
writes those names as type references, and the file does not compile — Protobuf printed
``.integer id = 1;``.

This module reduces a spelling (plus its ``format``) to a small set of :data:`ScalarKind` values,
and each emitter maps a kind to its own keyword (:data:`PROTO_SCALAR_FOR_KIND`,
:data:`THRIFT_SCALAR_FOR_KIND`, :data:`CAPNP_SCALAR_FOR_KIND`, :data:`OMG_IDL_SCALAR_FOR_KIND`,
:data:`SMITHY_SCALAR_FOR_KIND`, :data:`AVRO_SCALAR_FOR_KIND`, :data:`FLATBUFFERS_SCALAR_FOR_KIND`,
:data:`ASN1_SCALAR_FOR_KIND`, :data:`TYPESPEC_SCALAR_FOR_KIND`, :data:`XSD_SCALAR_FOR_KIND`).
Stored canonical models are untouched; only the emitted text changes.

An emitter whose own table predates this module keeps it for bare spellings, and asks
:func:`format_kind` first so a ``format`` that names a width is never ignored — COA-3.2 (#7053):
Avro wrote ``integer`` + ``int64`` as ``int``.

Only spellings with one clear meaning are listed. A name that is not listed — a named type, or a
scalar such as ``decimal`` or ``date`` whose mapping is a choice — resolves to ``None``, and the
emitter keeps its previous behaviour for it.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "ASN1_SCALAR_FOR_KIND",
    "AVRO_SCALAR_FOR_KIND",
    "CAPNP_SCALAR_FOR_KIND",
    "FLATBUFFERS_SCALAR_FOR_KIND",
    "INTEGER_RANGE_FOR_KIND",
    "OMG_IDL_SCALAR_FOR_KIND",
    "SMITHY_SCALAR_FOR_KIND",
    "PROTO_SCALAR_FOR_KIND",
    "THRIFT_SCALAR_FOR_KIND",
    "TYPESPEC_SCALAR_FOR_KIND",
    "XDR_SCALAR_FOR_KIND",
    "XSD_SCALAR_FOR_KIND",
    "ScalarKind",
    "format_kind",
    "scalar_kind",
    "target_scalar",
]

#: The kinds a scalar spelling reduces to (plain strings, so tables read naturally).
ScalarKind = str

#: Spelling (lower-cased) → kind, for spellings whose width does not depend on ``format``.
_FIXED_KINDS: Dict[str, ScalarKind] = {
    # booleans
    "boolean": "bool",
    "bool": "bool",
    # signed integers
    "byte": "int8",
    "sbyte": "int8",
    "i8": "int8",
    "int8": "int8",
    "short": "int16",
    "i16": "int16",
    "int16": "int16",
    "i32": "int32",
    "int32": "int32",
    "sint32": "int32",
    "sfixed32": "int32",
    "i64": "int64",
    "int64": "int64",
    "sint64": "int64",
    "sfixed64": "int64",
    "long": "int64",
    # unsigned integers (Protobuf's ``fixed32`` / ``fixed64`` are unsigned)
    "u8": "uint8",
    "uint8": "uint8",
    "u16": "uint16",
    "uint16": "uint16",
    "u32": "uint32",
    "uint32": "uint32",
    "fixed32": "uint32",
    "u64": "uint64",
    "uint64": "uint64",
    "fixed64": "uint64",
    # reals
    "float": "float",
    "f32": "float",
    "double": "double",
    "f64": "double",
    # text and binary
    "string": "string",
    "str": "string",
    "text": "string",
    "bytes": "bytes",
    "binary": "bytes",
    "blob": "bytes",
}

#: JSON Schema ``integer`` / ``number`` ``format`` values that pick a width (OpenAPI's registry).
_INTEGER_FORMATS: Dict[str, ScalarKind] = {"int32": "int32", "int64": "int64"}
_NUMBER_FORMATS: Dict[str, ScalarKind] = {"float": "float", "double": "double"}

#: Protobuf keyword per kind. Protobuf has no 8- or 16-bit integers, so they widen to 32 bits.
PROTO_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "bool",
    "int8": "int32",
    "int16": "int32",
    "int32": "int32",
    "int64": "int64",
    "uint8": "uint32",
    "uint16": "uint32",
    "uint32": "uint32",
    "uint64": "uint64",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "bytes",
}

#: ONC RPC / XDR type per kind (RFC 4506). XDR has no 8-bit integer; ``int8`` / ``uint8`` widen to
#: ``int`` / ``unsigned int``. COA-3.3 (#7054): the emitter wrote ``integer age;``.
XDR_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "bool",
    "int8": "int",
    "int16": "short",
    "int32": "int",
    "int64": "hyper",
    "uint8": "unsigned int",
    "uint16": "unsigned short",
    "uint32": "unsigned int",
    "uint64": "unsigned hyper",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "opaque",
}

#: Thrift base type per kind. Thrift has no unsigned integers or ``float``: an unsigned value widens
#: to the next signed size (``uint64`` stays ``i64``), and ``float`` widens to ``double``.
THRIFT_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "bool",
    "int8": "byte",
    "int16": "i16",
    "int32": "i32",
    "int64": "i64",
    "uint8": "i16",
    "uint16": "i32",
    "uint32": "i64",
    "uint64": "i64",
    "float": "double",
    "double": "double",
    "string": "string",
    "bytes": "binary",
}

#: Cap'n Proto built-in type per kind (MFX-30.2). Cap'n Proto has every width, signed and unsigned,
#: so nothing widens.
CAPNP_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "Bool",
    "int8": "Int8",
    "int16": "Int16",
    "int32": "Int32",
    "int64": "Int64",
    "uint8": "UInt8",
    "uint16": "UInt16",
    "uint32": "UInt32",
    "uint64": "UInt64",
    "float": "Float32",
    "double": "Float64",
    "string": "Text",
    "bytes": "Data",
}

#: OMG IDL type per kind (MFX-28.1). The classic CORBA spellings, which every IDL compiler reads
#: (IDL 4's ``int8`` / ``int64`` … are not in omniidl): a signed 8-bit integer widens to ``short``,
#: and ``bytes`` is a sequence of octets.
OMG_IDL_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "boolean",
    "int8": "short",
    "int16": "short",
    "int32": "long",
    "int64": "long long",
    "uint8": "octet",
    "uint16": "unsigned short",
    "uint32": "unsigned long",
    "uint64": "unsigned long long",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "sequence<octet>",
}

#: Smithy prelude shape per kind (MFX-20.1). Smithy has no unsigned integers: an unsigned value widens
#: to the next signed size, and ``uint64`` to ``BigInteger``.
SMITHY_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "Boolean",
    "int8": "Byte",
    "int16": "Short",
    "int32": "Integer",
    "int64": "Long",
    "uint8": "Short",
    "uint16": "Integer",
    "uint32": "Long",
    "uint64": "BigInteger",
    "float": "Float",
    "double": "Double",
    "string": "String",
    "bytes": "Blob",
}

#: Avro primitive per kind. Avro has only 32- and 64-bit signed integers: a smaller integer widens to
#: ``int``, ``uint32`` to ``long``, and ``uint64`` *narrows* to ``long`` (values above 2^63 − 1 do
#: not fit) — the emitter reports it.
AVRO_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "boolean",
    "int8": "int",
    "int16": "int",
    "int32": "int",
    "int64": "long",
    "uint8": "int",
    "uint16": "int",
    "uint32": "long",
    "uint64": "long",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "bytes",
}

#: FlatBuffers scalar per kind. FlatBuffers has every width, signed and unsigned, so nothing widens;
#: ``bytes`` is a vector of ``ubyte``.
FLATBUFFERS_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "bool",
    "int8": "byte",
    "int16": "short",
    "int32": "int",
    "int64": "long",
    "uint8": "ubyte",
    "uint16": "ushort",
    "uint32": "uint",
    "uint64": "ulong",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "[ubyte]",
}

#: ASN.1 built-in type per kind. ASN.1 has one unbounded ``INTEGER`` and one ``REAL``: an integer's
#: width is written as a value range from :data:`INTEGER_RANGE_FOR_KIND`, and ``float`` / ``double``
#: are both ``REAL`` (which holds either).
ASN1_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "BOOLEAN",
    "int8": "INTEGER",
    "int16": "INTEGER",
    "int32": "INTEGER",
    "int64": "INTEGER",
    "uint8": "INTEGER",
    "uint16": "INTEGER",
    "uint32": "INTEGER",
    "uint64": "INTEGER",
    "float": "REAL",
    "double": "REAL",
    "string": "UTF8String",
    "bytes": "OCTET STRING",
}

#: TypeSpec scalar per kind. TypeSpec has every width, signed and unsigned.
TYPESPEC_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "boolean",
    "int8": "int8",
    "int16": "int16",
    "int32": "int32",
    "int64": "int64",
    "uint8": "uint8",
    "uint16": "uint16",
    "uint32": "uint32",
    "uint64": "uint64",
    "float": "float32",
    "double": "float64",
    "string": "string",
    "bytes": "bytes",
}

#: XSD built-in (local name) per kind, used by the XSD and WSDL emitters. XSD has every width,
#: signed and unsigned, so nothing narrows or widens.
XSD_SCALAR_FOR_KIND: Mapping[ScalarKind, str] = {
    "bool": "boolean",
    "int8": "byte",
    "int16": "short",
    "int32": "int",
    "int64": "long",
    "uint8": "unsignedByte",
    "uint16": "unsignedShort",
    "uint32": "unsignedInt",
    "uint64": "unsignedLong",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "base64Binary",
}

#: The inclusive value range of each integer kind (an ASN.1 width, a narrowing check).
INTEGER_RANGE_FOR_KIND: Mapping[ScalarKind, Tuple[int, int]] = {
    "int8": (-(2**7), 2**7 - 1),
    "int16": (-(2**15), 2**15 - 1),
    "int32": (-(2**31), 2**31 - 1),
    "int64": (-(2**63), 2**63 - 1),
    "uint8": (0, 2**8 - 1),
    "uint16": (0, 2**16 - 1),
    "uint32": (0, 2**32 - 1),
    "uint64": (0, 2**64 - 1),
}


def format_kind(name: Optional[str], fmt: Optional[str]) -> Optional[ScalarKind]:
    """The kind a ``format`` picks for a JSON Schema ``integer`` / ``number`` (or ``int``).

    An emitter with its own spelling table asks this first: a bare ``integer`` keeps the emitter's
    choice, but ``integer`` + ``int64`` is always a 64-bit integer.

    Args:
        name: The canonical spelling.
        fmt: The field's ``format`` constraint, if any.

    Returns:
        ``int32`` / ``int64`` / ``float`` / ``double`` when ``name`` is ``integer``, ``int`` or
        ``number`` and ``fmt`` names a width; otherwise ``None``.
    """
    if not name or not fmt:
        return None
    key = name.strip().lower()
    hint = fmt.strip().lower()
    if key in ("integer", "int"):
        return _INTEGER_FORMATS.get(hint)
    if key == "number":
        return _NUMBER_FORMATS.get(hint)
    return None


def scalar_kind(name: Optional[str], fmt: Optional[str] = None) -> Optional[ScalarKind]:
    """Reduce a canonical scalar spelling to its kind.

    Args:
        name: The :class:`~app.canonical_model.TypeRef` name, e.g. ``integer`` or ``i64``.
        fmt: The field's ``format`` constraint, when it has one (``int64``, ``float``, …).
            It only matters for JSON Schema's ``integer`` and ``number``.

    Returns:
        The kind, or ``None`` when the spelling is not a scalar this module knows.
        ``integer`` is ``int32`` unless ``fmt`` is ``int64``; ``number`` is ``double`` unless
        ``fmt`` is ``float``; ``int`` follows ``integer``.
    """
    if not name:
        return None
    key = name.strip().lower()
    hint = (fmt or "").strip().lower()
    if key in ("integer", "int"):
        return _INTEGER_FORMATS.get(hint, "int32")
    if key == "number":
        return _NUMBER_FORMATS.get(hint, "double")
    return _FIXED_KINDS.get(key)


def target_scalar(
    name: Optional[str], vocabulary: Mapping[ScalarKind, str], fmt: Optional[str] = None
) -> Optional[str]:
    """Map a canonical scalar spelling to a target's keyword.

    Args:
        name: The canonical spelling.
        vocabulary: The target's kind → keyword table, e.g. :data:`PROTO_SCALAR_FOR_KIND`.
        fmt: The field's ``format`` constraint, if any.

    Returns:
        The target keyword, or ``None`` when the spelling is not a known scalar.
    """
    kind = scalar_kind(name, fmt)
    return vocabulary.get(kind) if kind is not None else None
