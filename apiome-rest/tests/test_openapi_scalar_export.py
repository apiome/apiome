"""Protobuf and Thrift export from OpenAPI projects — #6278.

The OpenAPI normalizer keeps JSON Schema's scalar names (``integer``, ``number``, ``boolean``) and
puts the width in the field's ``format`` constraint. The proto3 and Thrift emitters used to write
those names as type references (``.integer id = 1;``), and Thrift numbered every field ``1:``.

These tests cover:

* :mod:`app.scalar_aliases` — spelling + ``format`` → kind → each target's keyword;
* both emitters — JSON Schema names become real scalars, a type the model defines by such a name
  is still referenced, and source scalar names keep their exact spelling;
* Thrift field ids — unique within a struct, the source's ids kept, missing ones filled in order;
* the acceptance check — an OpenAPI corpus spec exports to Protobuf that ``buf`` compiles (when
  ``buf`` is available) and to Thrift that the repository's own parser reads, with no unknown type
  and no repeated field id.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Set

import pytest

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
from app.catalog_conversion import build_conversion_source
from app.proto_descriptor import BUF_TOOL_KEY
from app.proto_emitter import ProtoEmitter, compile_emitted_descriptor_set
from app.scalar_aliases import (
    CAPNP_SCALAR_FOR_KIND,
    PROTO_SCALAR_FOR_KIND,
    THRIFT_SCALAR_FOR_KIND,
    scalar_kind,
    target_scalar,
)
from app.thrift_emitter import ThriftEmitter
from app.thrift_parser import parse_thrift
from app.toolchain_packaging import probe_tool

_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))

#: The OpenAPI corpus the Catalog and Projects import (the same files the UI's examples use).
_CORPUS = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "openapi"

#: Thrift's base types, plus the containers' keywords.
_THRIFT_BASE = {"bool", "byte", "i8", "i16", "i32", "i64", "double", "string", "binary", "uuid"}

#: A small OpenAPI document with every scalar the issue names, and their formats.
_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "W", "version": "1.0.0"},
    "paths": {},
    "components": {
        "schemas": {
            "W": {
                "type": "object",
                "properties": {
                    "b": {"type": "boolean"},
                    "i": {"type": "integer"},
                    "l": {"type": "integer", "format": "int64"},
                    "n": {"type": "number"},
                    "f": {"type": "number", "format": "float"},
                    "s": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "integer"}},
                },
            }
        }
    },
}


def _openapi_api(spec: dict) -> CanonicalApi:
    """Build the canonical model an OpenAPI project exports from (the #6277 path)."""
    source = build_conversion_source(
        {
            "id": "item-1",
            "name": spec["info"]["title"],
            "source_format": "openapi",
            "format_metadata": {"sourceContent": json.dumps(spec)},
        }
    )
    return source.api


def _text(result) -> str:
    """The first emitted file's text."""
    return str(result.files[0].content)


def _record(fields: List[CanonicalField], extra_types: List[Type] = ()) -> CanonicalApi:
    """A one-record model (plus any extra types) for emitter unit tests."""
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="json-schema",
        identity=ApiIdentity(name="W"),
        types=[Type(key="W", name="W", kind=TypeKind.RECORD, fields=fields), *extra_types],
    )


def _field(name: str, type_name: str, *, fmt: str | None = None, number: int | None = None) -> CanonicalField:
    return CanonicalField(
        key=f"W.{name}",
        name=name,
        type=TypeRef(name=type_name),
        constraints=Constraints(format=fmt) if fmt else None,
        field_number=number,
    )


# ===========================================================================
# app.scalar_aliases
# ===========================================================================


@pytest.mark.parametrize(
    ("name", "fmt", "kind"),
    [
        ("integer", None, "int32"),
        ("integer", "int32", "int32"),
        ("integer", "int64", "int64"),
        ("integer", "uuid", "int32"),  # an unrelated format keeps the default width
        ("int", "int64", "int64"),
        ("number", None, "double"),
        ("number", "float", "float"),
        ("number", "double", "double"),
        ("boolean", None, "bool"),
        ("Boolean", None, "bool"),  # spellings are case-insensitive
        ("long", None, "int64"),
        ("i16", None, "int16"),
        ("uint64", None, "uint64"),
        ("binary", None, "bytes"),
        ("string", "int64", "string"),  # format only matters for integer / number
    ],
)
def test_scalar_kind(name: str, fmt: str | None, kind: str) -> None:
    assert scalar_kind(name, fmt) == kind


@pytest.mark.parametrize("name", [None, "", "Pet", "decimal", "date", "acme.v1.Pet"])
def test_unknown_spellings_have_no_kind(name: str | None) -> None:
    """Named types, and scalars whose mapping is a choice, are left to the emitter."""
    assert scalar_kind(name) is None
    assert target_scalar(name, PROTO_SCALAR_FOR_KIND) is None


def test_every_kind_has_a_keyword_in_both_targets() -> None:
    from app.scalar_aliases import _FIXED_KINDS

    kinds = set(_FIXED_KINDS.values()) | {"int32", "int64", "float", "double"}
    assert kinds == set(PROTO_SCALAR_FOR_KIND) == set(THRIFT_SCALAR_FOR_KIND)
    assert kinds == set(CAPNP_SCALAR_FOR_KIND)


def test_target_scalar_widens_where_a_target_has_no_exact_type() -> None:
    assert target_scalar("i16", PROTO_SCALAR_FOR_KIND) == "int32"  # protobuf has no 16-bit int
    assert target_scalar("uint32", THRIFT_SCALAR_FOR_KIND) == "i64"  # thrift has no unsigned
    assert target_scalar("number", THRIFT_SCALAR_FOR_KIND, "float") == "double"  # nor float


# ===========================================================================
# Protobuf
# ===========================================================================


def test_openapi_scalars_export_as_protobuf_scalars() -> None:
    text = _text(ProtoEmitter().emit(_openapi_api(_SPEC)))
    for line in (
        "bool b = ",
        "int32 i = ",
        "int64 l = ",
        "double n = ",
        "float f = ",
        "string s = ",
        "repeated int32 tags = ",
    ):
        assert line in text, line
    assert not re.search(r"\.(integer|number|boolean)\b", text)


def test_protobuf_prefers_a_type_the_model_defines_over_the_alias() -> None:
    """A schema really named ``number`` is a message, not ``double``."""
    number_type = Type(
        key="number",
        name="number",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="number.v", name="v", type=TypeRef(name="string"), field_number=1)],
    )
    text = _text(ProtoEmitter().emit(_record([_field("n", "number", number=1)], [number_type])))
    assert ".number n = 1;" in text


def test_protobuf_keeps_native_scalar_spellings() -> None:
    """A Protobuf source's ``sint64`` stays ``sint64`` — no widening through the alias table."""
    text = _text(ProtoEmitter().emit(_record([_field("x", "sint64", number=1)])))
    assert "sint64 x = 1;" in text


def test_protobuf_records_no_unresolved_import_for_aliased_scalars() -> None:
    result = ProtoEmitter().emit(_openapi_api(_SPEC))
    assert not [loss for loss in result.losses if "unresolved-import" in str(loss)]


# ===========================================================================
# Thrift
# ===========================================================================


def _struct_ids(text: str, name: str) -> List[int]:
    """The field ids of struct ``name`` as the repository's own parser reads them."""
    document = parse_thrift(text)
    (struct,) = [s for s in document.structs if s.name == name]
    return [field.id for field in struct.fields]


def test_openapi_scalars_export_as_thrift_base_types() -> None:
    text = _text(ThriftEmitter().emit(_openapi_api(_SPEC)))
    for line in (
        "optional bool b,",
        "optional i32 i,",
        "optional i64 l,",
        "optional double n,",
        "optional double f,",
        "optional string s,",
        "optional list<i32> tags,",
    ):
        assert line in text, line
    assert not re.search(r"\b(integer|number|boolean)\b", text)


def test_thrift_field_ids_are_unique_and_follow_declaration_order() -> None:
    ids = _struct_ids(_text(ThriftEmitter().emit(_openapi_api(_SPEC))), "W")
    assert ids == list(range(1, len(ids) + 1))


def test_thrift_keeps_the_source_ids_and_fills_the_gaps() -> None:
    """Explicit ids stay; a field without one gets the next free id, never a used one."""
    api = _record(
        [
            _field("a", "string"),
            _field("b", "string", number=1),
            _field("c", "string", number=3),
            _field("d", "string"),
        ]
    )
    text = _text(ThriftEmitter().emit(api))
    assert _struct_ids(text, "W") == [1, 2, 3, 4]
    assert "1: optional string b," in text
    assert "2: optional string a," in text
    assert "3: optional string c," in text
    assert "4: optional string d," in text


def test_thrift_source_with_ids_emits_as_before() -> None:
    """A Thrift-sourced model (every field numbered) keeps its ids and order."""
    api = _record([_field("z", "i64", number=7), _field("y", "string", number=2)])
    text = _text(ThriftEmitter().emit(api))
    assert text.index("2: optional string y") < text.index("7: optional i64 z")


def test_thrift_prefers_a_type_the_model_defines_over_the_alias() -> None:
    number_type = Type(key="number", name="number", kind=TypeKind.ENUM)
    text = _text(ThriftEmitter().emit(_record([_field("n", "number", number=1)], [number_type])))
    assert "1: optional number n" in text


# ===========================================================================
# The acceptance check: a corpus OpenAPI spec compiles
# ===========================================================================


def _corpus_api(name: str) -> CanonicalApi:
    path = _CORPUS / name
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    source = build_conversion_source(
        {
            "id": "item-1",
            "name": path.stem,
            "source_format": "openapi",
            "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")},
        }
    )
    return source.api


#: Corpus specs with integer, number and boolean fields (01: numeric constraints; 07: nullable
#: types; 08: several scalar kinds with examples).
_CORPUS_SPECS = ["01-numeric-constraints.yaml", "07-nullable-types.yaml", "08-multiple-examples.yaml"]


@pytest.mark.parametrize("name", _CORPUS_SPECS)
def test_corpus_spec_exports_to_thrift_the_parser_reads(name: str) -> None:
    """Every field type is a base type, a container or a declared type; ids are unique."""
    text = _text(ThriftEmitter().emit(_corpus_api(name)))
    document = parse_thrift(text)
    declared: Set[str] = {s.name for s in document.structs} | {e.name for e in document.enums}
    declared |= set(document.typedefs)
    for struct in document.structs:
        ids = [field.id for field in struct.fields]
        assert len(ids) == len(set(ids)), f"{struct.name} repeats a field id: {ids}"
        for field in struct.fields:
            for token in re.findall(r"[A-Za-z_][\w.]*", field.type_expr):
                if token in {"list", "set", "map"}:
                    continue
                assert token in _THRIFT_BASE or token in declared, f"{struct.name}.{field.name}: {token}"


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="buf is not resolvable here (bundled in the image)")
@pytest.mark.parametrize("name", _CORPUS_SPECS)
async def test_corpus_spec_exports_to_protobuf_that_compiles(name: str) -> None:
    compiled = await compile_emitted_descriptor_set(_corpus_api(name))
    assert compiled.files
