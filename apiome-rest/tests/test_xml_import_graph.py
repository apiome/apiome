"""Tests for the WSDL / XSD import graph — MFI-13.1 (#3788).

Every import and include of a description or schema is followed against the documents of a
multi-file set: each location relative to the file that declares it, then as written (a live
fetch), then by a file name only one member has. Cycles end, and a reference nothing answers is
reported rather than failing the import.
"""

from __future__ import annotations

from typing import Dict

import pytest

from app.secure_xml import parse_xml
from app.xml_import_graph import (
    KIND_SCHEMA,
    KIND_WSDL,
    REASON_MISSING,
    REASON_UNREADABLE,
    resolve_bundle_path,
    resolve_import_graph,
    resolve_member,
)

XS = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'
WSDL11 = 'xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"'
WSDL20 = 'xmlns="http://www.w3.org/ns/wsdl"'


def _schema(*refs: str, target: str = "urn:a") -> str:
    """A schema declaring ``refs`` (``xs:import`` / ``include`` / … elements) and one type."""
    return f'<xs:schema {XS} targetNamespace="{target}">{"".join(refs)}<xs:complexType name="T"/></xs:schema>'


def _graph(members: Dict[str, str], root: str):
    """Resolve the graph of ``members[root]``."""
    text = members[root]
    return resolve_import_graph(parse_xml(text), root_text=text, root_path=root, members=members)


def _paths(graph) -> list[str]:
    return [document.path for document in graph.documents]


# --- resolve_bundle_path / resolve_member -----------------------------------------------------


@pytest.mark.parametrize(
    "base, location, expected",
    [
        ("", "types.xsd", "types.xsd"),
        ("schemas", "types.xsd", "schemas/types.xsd"),
        ("schemas/orders", "../common/types.xsd", "schemas/common/types.xsd"),
        ("schemas", "./a/../b.xsd", "schemas/b.xsd"),
        ("", "../outside.xsd", None),
        ("", "/etc/passwd", None),
        ("", "https://host/types.xsd", None),
        ("", "C:/types.xsd", None),
        ("", "", None),
    ],
)
def test_resolve_bundle_path(base: str, location: str, expected: str | None) -> None:
    assert resolve_bundle_path(base, location) == expected


def test_resolve_member_prefers_the_path_relative_to_the_declaring_file() -> None:
    members = {"a/types.xsd": "A", "b/types.xsd": "B"}
    assert resolve_member("types.xsd", members, declared_in="b/root.xsd") == ("b/types.xsd", "B")
    assert resolve_member("../a/types.xsd", members, declared_in="b/root.xsd") == ("a/types.xsd", "A")


def test_resolve_member_falls_back_to_the_location_as_written() -> None:
    # A live fetch keys each document by the location its referrer wrote.
    members = {"?xsd=xsd0": "X", "https://host/svc?wsdl=wsdl0": "W"}
    assert resolve_member("?xsd=xsd0", members, declared_in="https://host/svc?wsdl") == ("?xsd=xsd0", "X")
    assert resolve_member("https://host/svc?wsdl=wsdl0", members) == ("https://host/svc?wsdl=wsdl0", "W")


def test_resolve_member_uses_a_file_name_only_when_one_member_has_it() -> None:
    assert resolve_member("schemas/types.xsd", {"flat/types.xsd": "T"}) == ("flat/types.xsd", "T")
    assert resolve_member("types.xsd", {"a/types.xsd": "A", "b/types.xsd": "B"}, declared_in="root.xsd") is None


def test_resolve_member_finds_nothing_for_an_empty_location() -> None:
    assert resolve_member("  ", {"a.xsd": "A"}) is None


# --- resolve_import_graph ---------------------------------------------------------------------


def test_a_single_document_is_its_own_graph() -> None:
    text = _schema('<xs:include schemaLocation="missing.xsd"/>')
    graph = resolve_import_graph(parse_xml(text), root_text=text, root_path="root.xsd", members=None)
    assert _paths(graph) == ["root.xsd"]
    assert graph.unresolved == ()
    assert graph.as_extras() is None


def test_nested_folders_resolve_relative_to_each_file() -> None:
    members = {
        "svc/root.xsd": _schema('<xs:import namespace="urn:o" schemaLocation="../schemas/orders/orders.xsd"/>'),
        "schemas/orders/orders.xsd": _schema('<xs:include schemaLocation="../common/types.xsd"/>', target="urn:o"),
        "schemas/common/types.xsd": _schema(target="urn:o"),
    }
    graph = _graph(members, "svc/root.xsd")
    assert _paths(graph) == ["svc/root.xsd", "schemas/orders/orders.xsd", "schemas/common/types.xsd"]
    assert {document.kind for document in graph.imported()} == {KIND_SCHEMA}
    assert graph.unresolved == ()


def test_the_same_location_in_two_folders_reaches_two_documents() -> None:
    members = {
        "root.xsd": _schema(
            '<xs:import namespace="urn:a" schemaLocation="a/main.xsd"/>',
            '<xs:import namespace="urn:b" schemaLocation="b/main.xsd"/>',
        ),
        "a/main.xsd": _schema('<xs:include schemaLocation="types.xsd"/>'),
        "b/main.xsd": _schema('<xs:include schemaLocation="types.xsd"/>', target="urn:b"),
        "a/types.xsd": _schema(),
        "b/types.xsd": _schema(target="urn:b"),
    }
    assert sorted(_paths(_graph(members, "root.xsd"))) == sorted(members)


@pytest.mark.parametrize("element", ["import", "include", "redefine", "override"])
def test_every_schema_reference_is_followed(element: str) -> None:
    members = {"root.xsd": _schema(f'<xs:{element} schemaLocation="other.xsd"/>'), "other.xsd": _schema()}
    assert _paths(_graph(members, "root.xsd")) == ["root.xsd", "other.xsd"]


def test_an_import_cycle_ends() -> None:
    members = {
        "a.xsd": _schema('<xs:include schemaLocation="b.xsd"/>'),
        "b.xsd": _schema('<xs:include schemaLocation="a.xsd"/>'),
    }
    assert _paths(_graph(members, "a.xsd")) == ["a.xsd", "b.xsd"]


def test_wsdl_1_1_import_and_its_schemas_are_followed() -> None:
    members = {
        "root.wsdl": (
            f'<wsdl:definitions {WSDL11}><wsdl:import namespace="urn:x" location="part.wsdl"/></wsdl:definitions>'
        ),
        "part.wsdl": (
            f'<wsdl:definitions {WSDL11} {XS}><wsdl:types><xs:schema>'
            '<xs:import namespace="urn:t" schemaLocation="t.xsd"/></xs:schema></wsdl:types></wsdl:definitions>'
        ),
        "t.xsd": _schema(target="urn:t"),
    }
    graph = _graph(members, "root.wsdl")
    assert [(d.path, d.kind) for d in graph.documents] == [
        ("root.wsdl", KIND_WSDL),
        ("part.wsdl", KIND_WSDL),
        ("t.xsd", KIND_SCHEMA),
    ]


@pytest.mark.parametrize("element", ["import", "include"])
def test_wsdl_2_0_import_and_include_are_followed(element: str) -> None:
    members = {
        "root.wsdl": f'<description {WSDL20}><{element} namespace="urn:x" location="part.wsdl"/></description>',
        "part.wsdl": f"<description {WSDL20}/>",
    }
    assert _paths(_graph(members, "root.wsdl")) == ["root.wsdl", "part.wsdl"]


def test_unresolved_and_unreadable_references_are_reported_once() -> None:
    members = {
        "root.xsd": _schema(
            '<xs:include schemaLocation="missing.xsd"/>',
            '<xs:include schemaLocation="missing.xsd"/>',
            '<xs:include schemaLocation="broken.xsd"/>',
            '<xs:include schemaLocation="../escape.xsd"/>',
        ),
        "broken.xsd": "<xs:schema",
    }
    graph = _graph(members, "root.xsd")
    assert _paths(graph) == ["root.xsd"]
    assert [(u.location, u.reason) for u in graph.unresolved] == [
        ("missing.xsd", REASON_MISSING),
        ("broken.xsd", REASON_UNREADABLE),
        ("../escape.xsd", REASON_MISSING),
    ]
    extras = graph.as_extras()
    assert extras is not None
    assert extras["unresolved"][0] == {"declared_in": "root.xsd", "location": "missing.xsd", "reason": "missing"}


def test_a_document_with_a_dtd_is_refused_as_unreadable() -> None:
    members = {
        "root.xsd": _schema('<xs:include schemaLocation="evil.xsd"/>'),
        "evil.xsd": '<!DOCTYPE x [<!ENTITY e "boom">]><xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>',
    }
    graph = _graph(members, "root.xsd")
    assert [u.reason for u in graph.unresolved] == [REASON_UNREADABLE]


def test_references_without_a_location_are_not_followed() -> None:
    members = {"root.xsd": _schema('<xs:import namespace="urn:only-a-namespace"/>')}
    graph = _graph(members, "root.xsd")
    assert _paths(graph) == ["root.xsd"] and graph.unresolved == ()
