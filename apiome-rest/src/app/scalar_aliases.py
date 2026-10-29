"""Resolve the canonical model's scalar spellings to a target's own scalar types — #6278.

The canonical model has no single scalar vocabulary: each normalizer keeps its source format's
spelling (:data:`app.canonical_json_schema.CANONICAL_SCALAR_SCHEMAS` lists the ones in use). The
OpenAPI normalizer keeps JSON Schema's ``integer``, ``number`` and ``boolean``, with the width in the
field's ``format`` constraint (``int64``, ``float``). An emitter that only knows its own keywords
writes those names as type references, and the file does not compile — Protobuf printed
``.integer id = 1;``.

This module reduces a spelling (plus its ``format``) to a small set of :data:`ScalarKind` values,
and each emitter maps a kind to its own keyword (:data:`PROTO_SCALAR_FOR_KIND`,
:data:`THRIFT_SCALAR_FOR_KIND`, :data:`CAPNP_SCALAR_FOR_KIND`, :data:`OMG_IDL_SCALAR_FOR_KIND`).
Stored canonical models are untouched; only the emitted text changes.

Only spellings with one clear meaning are listed. A name that is not listed — a named type, or a
scalar such as ``decimal`` or ``date`` whose mapping is a choice — resolves to ``None``, and the
emitter keeps its previous behaviour for it.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional

__all__ = [
    "CAPNP_SCALAR_FOR_KIND",
    "OMG_IDL_SCALAR_FOR_KIND",
    "PROTO_SCALAR_FOR_KIND",
    "THRIFT_SCALAR_FOR_KIND",
    "ScalarKind",
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
    "fixed32": "int32",
    "sfixed32": "int32",
    "i64": "int64",
    "int64": "int64",
    "sint64": "int64",
    "fixed64": "int64",
    "sfixed64": "int64",
    "long": "int64",
    # unsigned integers
    "uint8": "uint8",
    "uint16": "uint16",
    "uint32": "uint32",
    "uint64": "uint64",
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
