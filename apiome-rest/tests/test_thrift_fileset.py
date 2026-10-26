"""Tests for Apache Thrift multi-file sets and the parser fixes they needed — MFI-19.3 (#3981).

The corpus set ``apiome-ui/examples/thrift/07-orders-set`` (root ``api.thrift`` including
``shared.thrift`` and ``errors.thrift``, three services) is the main fixture; smaller sets are
built inline for the include-resolution edge cases.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from app.fileset import IntakeFileset, resolve_relative_reference
from app.import_source import ImportSourceError
from app.thrift_fileset import include_prefix, parse_thrift_set
from app.thrift_import_source import ThriftImportSource
from app.thrift_normalizer import ThriftNormalizer
from app.thrift_parser import parse_thrift

_SET_DIR = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "thrift" / "07-orders-set"


def _orders_set() -> Dict[str, str]:
    """The corpus set's members, file name → text."""
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(_SET_DIR.iterdir())}


def _normalize(members: Dict[str, str], root: str = "api.thrift"):
    """Parse and normalize a set."""
    return ThriftNormalizer().normalize(parse_thrift_set(members, root), include_raw=False)


# ===========================================================================
# Parser
# ===========================================================================


def test_service_extends_is_parsed():
    doc = parse_thrift("service A extends shared.Base {\n  string ping(),\n}\nservice B {\n  void x()\n}\n")
    assert [(s.name, s.extends) for s in doc.services] == [("A", "shared.Base"), ("B", None)]


def test_methods_with_several_parameters_and_no_separators_are_read():
    doc = parse_thrift(
        """service S {
  Order place(1: list<Line> lines, 2: string currency)
    throws (1: Invalid invalid, 2: Busy busy)
  oneway void fire(1: string a, 2: i32 b)
  map<string, list<i32>> stats(1: string key);
  string last(1: string only)
}
"""
    )
    methods = {m.name: m for m in doc.services[0].methods}
    assert list(methods) == ["place", "fire", "stats", "last"]
    assert [(p.id, p.name, p.type_expr) for p in methods["place"].parameters] == [
        (1, "lines", "list<Line>"),
        (2, "currency", "string"),
    ]
    assert methods["place"].throws == ((1, "Invalid", "invalid"), (2, "Busy", "busy"))
    assert methods["fire"].oneway is True
    assert methods["stats"].return_type == "map<string,list<i32>>"
    assert [p.name for p in methods["last"].parameters] == ["only"]


def test_last_field_without_a_separator_is_kept():
    doc = parse_thrift("struct S { 1: i32 a, 2: string b }")
    assert [f.name for f in doc.structs[0].fields] == ["a", "b"]


def test_comment_markers_inside_strings_are_kept():
    doc = parse_thrift(
        'include "http://host/x.thrift" // a comment\n'
        'struct S {\n  1: string color = "#fff", # hash comment\n  2: i32 n /* block */\n}\n'
    )
    assert doc.includes == ("http://host/x.thrift",)
    assert [(f.name, f.default) for f in doc.structs[0].fields] == [("color", '"#fff"'), ("n", None)]


def test_typedef_without_a_separator_resolves():
    doc = parse_thrift("typedef string Id\nstruct S {\n  1: Id id\n}\n")
    assert doc.typedefs == {"Id": "string"}
    assert doc.structs[0].fields[0].type_expr == "string"


def test_an_included_file_may_hold_only_typedefs():
    doc = parse_thrift("typedef i64 Amount\n", require_definitions=False)
    assert doc.typedefs == {"Amount": "i64"}
    with pytest.raises(ValueError):
        parse_thrift("typedef i64 Amount\n")


# ===========================================================================
# Include resolution
# ===========================================================================


@pytest.mark.parametrize(
    "target, prefix",
    [("shared.thrift", "shared"), ("common/errors.thrift", "errors"), ("noext", "noext")],
)
def test_include_prefix(target: str, prefix: str):
    assert include_prefix(target) == prefix


def test_resolve_relative_reference_stays_inside_the_set():
    assert resolve_relative_reference("a/b.thrift", "c.thrift") == "a/c.thrift"
    assert resolve_relative_reference("a/b.thrift", "../c.thrift") == "c.thrift"
    assert resolve_relative_reference("b.thrift", "../c.thrift") is None
    assert resolve_relative_reference("b.thrift", "/etc/passwd") is None
    assert resolve_relative_reference("b.thrift", "https://x/c.thrift") is None


def test_the_set_links_every_included_file():
    doc = parse_thrift_set(_orders_set(), "api.thrift")
    assert doc.path == "api.thrift"
    assert sorted(doc.included) == ["errors", "shared"]
    assert doc.included["shared"].path == "shared.thrift"
    assert [s.name for s in doc.included["shared"].services] == ["BaseService"]


def test_includes_resolve_beside_the_file_then_from_the_root():
    members = {
        "api.thrift": 'include "lib/a.thrift"\nstruct R { 1: a.A a }\n',
        "lib/a.thrift": 'include "b.thrift"\nstruct A { 1: b.B b }\n',
        # Not beside lib/a.thrift, so it is found from the root's folder (the `-I` path).
        "b.thrift": "struct B { 1: i32 x }\n",
    }
    doc = parse_thrift_set(members, "api.thrift")
    assert doc.included["a"].included["b"].path == "b.thrift"


def test_a_file_included_twice_is_parsed_once():
    members = {
        "api.thrift": 'include "a.thrift"\ninclude "b.thrift"\nstruct R { 1: a.A a, 2: b.B b }\n',
        "a.thrift": 'include "c.thrift"\nstruct A { 1: c.C c }\n',
        "b.thrift": 'include "c.thrift"\nstruct B { 1: c.C c }\n',
        "c.thrift": "struct C { 1: i32 x }\n",
    }
    doc = parse_thrift_set(members, "api.thrift")
    assert doc.included["a"].included["c"] is doc.included["b"].included["c"]
    api = _normalize(members)
    assert [t.key for t in api.types].count("c.C") == 1


@pytest.mark.parametrize("target", ["../outside.thrift", "/abs/x.thrift", "http://host/x.thrift"])
def test_an_include_outside_the_set_is_refused(target: str):
    members = {"api.thrift": f'include "{target}"\nstruct R {{ 1: i32 x }}\n'}
    with pytest.raises(ImportSourceError, match="outside the uploaded files") as exc:
        parse_thrift_set(members, "api.thrift")
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_a_missing_include_is_refused():
    with pytest.raises(ImportSourceError, match="Add shared.thrift") as exc:
        parse_thrift_set({"api.thrift": 'include "shared.thrift"\nstruct R { 1: i32 x }\n'}, "api.thrift")
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_an_include_cycle_is_refused():
    members = {
        "a.thrift": 'include "b.thrift"\nstruct A { 1: i32 x }\n',
        "b.thrift": 'include "a.thrift"\nstruct B { 1: i32 x }\n',
    }
    with pytest.raises(ImportSourceError, match="a.thrift → b.thrift → a.thrift") as exc:
        parse_thrift_set(members, "a.thrift")
    assert exc.value.code == "INPUT_SEMANTIC_INVALID"


def test_a_missing_root_and_an_invalid_member_are_refused():
    with pytest.raises(ImportSourceError) as exc:
        parse_thrift_set({"a.thrift": "struct A { 1: i32 x }"}, "api.thrift")
    assert exc.value.code == "INPUT_ARCHIVE_INVALID"
    with pytest.raises(ImportSourceError, match="^api.thrift: "):
        parse_thrift_set({"api.thrift": "just prose"}, "api.thrift")


# ===========================================================================
# Canonical model
# ===========================================================================


def test_every_file_contributes_types_under_its_namespace():
    api = _normalize(_orders_set())
    assert {t.key for t in api.types} >= {
        "com.example.orders.v1.Order",
        "com.example.shared.v1.Money",
        "com.example.shared.v1.Currency",
        "com.example.errors.v1.NotFound",
        "com.example.errors.v1.InvalidRequest",
    }
    assert api.identity.namespace == "com.example.orders.v1"
    assert api.extras["thrift_source_files"] == ["api.thrift", "errors.thrift", "shared.thrift"]


def test_qualified_references_and_included_typedefs_resolve():
    api = _normalize(_orders_set())
    order = next(t for t in api.types if t.name == "Order")
    fields = {f.name: f for f in order.fields}
    assert fields["id"].type.name == "string"  # root typedef without a separator
    assert fields["total"].type.name == "i64"  # shared.Amount, a typedef in shared.thrift
    line = next(t for t in api.types if t.name == "OrderLine")
    assert next(f for f in line.fields if f.name == "unitPrice").type.name == "com.example.shared.v1.Money"


def test_services_from_every_file_and_extends():
    api = _normalize(_orders_set())
    services = {s.key: s for s in api.services}
    assert sorted(services) == [
        "com.example.orders.v1.InventoryService",
        "com.example.orders.v1.OrderService",
        "com.example.shared.v1.BaseService",
    ]
    orders = services["com.example.orders.v1.OrderService"]
    assert orders.extras == {"thrift_extends": "com.example.shared.v1.BaseService"}
    get_order = next(o for o in orders.operations if o.name == "getOrder")
    error = next(m for m in get_order.messages if m.name == "notFound")
    assert error.payload.name == "com.example.errors.v1.NotFound"
    assert {o.name for o in orders.operations} == {"getOrder", "placeOrder", "cancelOrder"}


def test_an_included_file_without_a_namespace_is_keyed_by_its_prefix():
    members = {
        "api.thrift": 'namespace java app\ninclude "common.thrift"\nstruct R { 1: common.C c }\n',
        "common.thrift": "struct C { 1: i32 x }\n",
    }
    api = _normalize(members)
    r = next(t for t in api.types if t.name == "R")
    assert r.fields[0].type.name == "common.C"
    assert "common.C" in {t.key for t in api.types}


def test_a_single_document_is_unchanged_by_the_set_support():
    text = 'include "shared.thrift"\nnamespace java a\nstruct R { 1: shared.Money m }\n'
    api = ThriftNormalizer().normalize(parse_thrift(text), include_raw=False)
    assert api.types[0].fields[0].type.name == "shared.Money"
    assert "thrift_source_files" not in api.extras


def test_fingerprint_does_not_depend_on_member_order():
    source = ThriftImportSource()
    members = _orders_set()
    forward = IntakeFileset.from_members(members, root="api.thrift")
    backward = IntakeFileset.from_members(dict(reversed(list(members.items()))), root="api.thrift")
    first = source.fingerprint(source.normalize(source.parse_fileset(forward)))
    second = source.fingerprint(source.normalize(source.parse_fileset(backward)))
    assert first == second


def test_the_import_source_parses_a_fileset_through_the_set_parser():
    source = ThriftImportSource()
    doc = source.parse_fileset(IntakeFileset.from_members(_orders_set(), root="api.thrift"))
    assert sorted(doc.included) == ["errors", "shared"]
