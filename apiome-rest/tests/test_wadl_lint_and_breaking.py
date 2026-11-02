"""Tests for WADL as a legacy REST description: reuse, normalization, lint, breaking changes and the
migrate-to-OpenAPI path — MFI-21.3 (#3993)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.canonical_model import MessageRole, ParameterLocation, TypeKind
from app.catalog_conversion import build_conversion_source
from app.conversion_job import preview_conversion
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.import_source import canonical_diff
from app.lint_engine import get_rule_pack, lint_canonical_model
from app.openapi_validator import validate_openapi_document
from app.roundtrip_matrix import reimport_emitted
from app.wadl_breaking import RULE_IDS, WadlBreakingChangeClassifier, relative_order_changed
from app.wadl_emitter import WadlEmitter
from app.wadl_import_source import WadlImportSource
from app.wadl_lint import STANDARD_HTTP_METHODS, WadlRulePack
from app.wadl_normalizer import CANONICAL_PRIMITIVES, explicit_method_id
from app.wadl_parser import parse_wadl

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _ROOT / "apiome-ui" / "examples" / "wadl"
_VERSIONS = Path(__file__).parent / "fixtures" / "wadl_versions"
_NS = "http://example.com/t"


def _wadl(resources: str, grammar: str = "", extra: str = "", base: str = 'base="https://api.example.com/"') -> str:
    """A minimal WADL document around ``resources`` (and an optional grammar schema body)."""
    grammars = f'<grammars><xsd:schema targetNamespace="{_NS}">{grammar}</xsd:schema></grammars>' if grammar else ""
    return (
        '<?xml version="1.0"?>'
        '<application xmlns="http://wadl.dev.java.net/2009/02" '
        f'xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:tns="{_NS}">'
        f"<doc>T</doc>{grammars}{extra}<resources {base}>{resources}</resources></application>"
    )


_ITEM = (
    '<xsd:element name="item" type="tns:Item"/>'
    '<xsd:complexType name="Item"><xsd:sequence>'
    '<xsd:element name="id" type="xsd:string"/>'
    "</xsd:sequence></xsd:complexType>"
)

_GET_ITEM = (
    '<resource path="items/{id}"><param name="id" style="template" type="xsd:string"/>'
    '<method name="GET" id="getItem"><response status="200">'
    '<representation mediaType="application/xml" element="tns:item"/></response></method></resource>'
)


def _api(text: str):
    adapter = WadlImportSource()
    return adapter.normalize(adapter.parse(text, source_label="t.wadl"), include_raw=False)


def _version(name: str):
    return _api((_VERSIONS / name).read_text(encoding="utf-8"))


def _operations(api) -> Dict[str, object]:
    return {op.key: op for service in api.services for op in service.operations}


def _fields(api, type_name: str) -> Dict[str, object]:
    type_ = next(t for t in api.types if t.name == type_name)
    return {f.name: f for f in type_.fields}


def _findings(text: str) -> List[Tuple[str, str, str]]:
    result = lint_canonical_model(_api(text))
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("wadl."))


def _rules(text: str) -> set:
    return {rule for rule, _, _ in _findings(text)}


def _grades(base, target) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two models."""
    result = classify_models(base, target)
    assert result.classifier == "wadl-resources"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


def _grammar_api(sequence: str, *, extra_grammar: str = ""):
    """A model whose ``Item`` type has the given sequence body."""
    grammar = (
        '<xsd:element name="item" type="tns:Item"/>'
        f'{extra_grammar}<xsd:complexType name="Item"><xsd:sequence>{sequence}</xsd:sequence></xsd:complexType>'
    )
    return _api(_wadl(_GET_ITEM, grammar))


# --- parsing WADL's reuse ------------------------------------------------------------------


def test_method_param_and_resource_type_references_resolve_in_place() -> None:
    doc = parse_wadl((_VERSIONS / "library.v1.wadl").read_text(encoding="utf-8"))
    by_route = {(op.method, op.path): op for op in doc.operations}
    # `<method href="#listLoans"/>` reads as the method written at the top level.
    listed = by_route[("GET", "/loans")]
    assert listed.operation_id == "listLoans"
    assert listed.description == "List loans, optionally by status."
    # `<param href="#statusFilter"/>` brings its name, style and options.
    (status,) = listed.parameters
    assert (status.name, status.location, status.required) == ("status", "query", False)
    assert status.options == ("ACTIVE", "RETURNED", "OVERDUE")
    # `type="#item"` applies the resource_type's param and method to `{loanId}`.
    item = by_route[("GET", "/loans/{loanId}")]
    assert item.operation_id == "getLoan"
    assert [p.name for p in item.parameters] == ["loanId"]
    assert doc.unresolved_refs == ()


def test_unresolved_references_are_recorded_not_guessed() -> None:
    text = _wadl(
        '<resource path="a" type="#nope"><method href="#missing"/>'
        '<method name="GET" id="a"><request><param href="other.wadl#p"/></request>'
        '<response status="200"><representation href="#r"/></response></method></resource>'
    )
    doc = parse_wadl(text)
    assert doc.unresolved_refs == (
        "resource_type #nope",
        "method #missing",
        "param other.wadl#p",
        "representation #r",
    )
    assert [(op.method, op.path) for op in doc.operations] == [("GET", "/a")]


def test_an_href_cycle_stops_and_is_recorded() -> None:
    text = _wadl(
        '<resource path="a"><method href="#m1"/><method name="GET" id="a"><response/></method></resource>',
        extra='<method id="m1" href="#m2"/><method id="m2" href="#m1"/>',
    )
    doc = parse_wadl(text)
    assert [op.operation_id for op in doc.operations] == ["a"]
    assert doc.unresolved_refs == ("method #m1",)


def test_a_status_list_reads_as_one_response_per_code() -> None:
    doc = parse_wadl(
        _wadl('<resource path="a"><method name="POST" id="a"><response status="400 409"/></method></resource>')
    )
    assert doc.operations[0].response_types == (("400", None), ("409", None))


def test_params_keep_style_repeating_default_and_options() -> None:
    text = _wadl(
        '<resource path="a;v"><param name="v" style="matrix" type="xsd:string" required="false"/>'
        '<method name="GET" id="a"><request>'
        '<param name="tag" style="query" type="xsd:string" repeating="true" required="false"/>'
        '<param name="size" style="query" type="xsd:int" default="10" required="false">'
        '<option value="10"/><option value="50"/></param>'
        "</request><response/></method></resource>"
    )
    params = {p.name: p for p in parse_wadl(text).operations[0].parameters}
    assert (params["v"].style, params["v"].location) == ("matrix", "path")
    assert params["tag"].repeating is True
    assert (params["size"].default, params["size"].options) == ("10", ("10", "50"))


def test_sequence_occurrence_and_simple_types_are_read() -> None:
    grammar = (
        '<xsd:simpleType name="Color"><xsd:restriction base="xsd:string">'
        '<xsd:enumeration value="RED"/><xsd:enumeration value="BLUE"/></xsd:restriction></xsd:simpleType>'
        '<xsd:simpleType name="Code"><xsd:restriction base="xsd:token"><xsd:maxLength value="4"/>'
        "</xsd:restriction></xsd:simpleType>"
        '<xsd:complexType name="Item"><xsd:sequence>'
        '<xsd:element name="a" type="xsd:string" minOccurs="0"/>'
        '<xsd:element name="b" type="xsd:string" maxOccurs="unbounded"/>'
        '<xsd:element name="c" type="xsd:string" nillable="true"/>'
        "</xsd:sequence></xsd:complexType>"
    )
    doc = parse_wadl(_wadl(_GET_ITEM, grammar))
    fields = {f.name: f for f in doc.complex_types[0].fields}
    assert (fields["a"].min_occurs, fields["a"].max_occurs) == (0, 1)
    assert (fields["b"].min_occurs, fields["b"].max_occurs) == (1, None)
    assert fields["c"].nillable is True
    simple = {s.name: s for s in doc.simple_types}
    assert simple["Color"].enumerations == ("RED", "BLUE")
    assert (simple["Code"].base, simple["Code"].enumerations) == ("token", ())


# --- normalization ---------------------------------------------------------------------------


def test_occurrence_maps_to_nullability_and_list_bounds() -> None:
    api = _grammar_api(
        '<xsd:element name="req" type="xsd:string"/>'
        '<xsd:element name="opt" type="xsd:string" minOccurs="0"/>'
        '<xsd:element name="nil" type="xsd:string" nillable="true"/>'
        '<xsd:element name="many" type="xsd:string" minOccurs="1" maxOccurs="5"/>'
        '<xsd:element name="any" type="xsd:string" minOccurs="0" maxOccurs="unbounded"/>'
    )
    fields = _fields(api, "Item")
    assert fields["req"].type.nullable is False
    assert fields["opt"].type.nullable is True
    assert fields["nil"].type.nullable is True
    many = fields["many"]
    assert many.type.item is not None and many.type.item.nullable is False and many.type.nullable is False
    assert (many.constraints.min_items, many.constraints.max_items) == (1, 5)
    unbounded = fields["any"]
    assert unbounded.type.item is not None and unbounded.type.nullable is True
    assert unbounded.constraints is None


def test_enumerated_simple_types_are_enums_and_others_resolve_to_their_base() -> None:
    api = _grammar_api(
        '<xsd:element name="color" type="tns:Color"/><xsd:element name="code" type="tns:Code"/>',
        extra_grammar=(
            '<xsd:simpleType name="Color"><xsd:restriction base="xsd:string">'
            '<xsd:enumeration value="RED"/><xsd:enumeration value="BLUE"/></xsd:restriction></xsd:simpleType>'
            '<xsd:simpleType name="Code"><xsd:restriction base="xsd:token"/></xsd:simpleType>'
        ),
    )
    color = next(t for t in api.types if t.name == "Color")
    assert color.kind is TypeKind.ENUM
    assert [v.name for v in color.enum_values] == ["RED", "BLUE"]
    fields = _fields(api, "Item")
    assert fields["color"].type.name == color.key
    assert fields["code"].type.name == "string"
    assert fields["code"].extras["wadl_type"] == "Code"


def test_params_normalize_options_repeating_default_and_style() -> None:
    api = _api(
        _wadl(
            '<resource path="a;v"><param name="v" style="matrix" type="xsd:string" required="false"/>'
            '<method name="GET" id="a"><request>'
            '<param name="tag" style="query" type="xsd:string" repeating="true" required="false"/>'
            '<param name="size" style="query" type="xsd:int" default="10" required="false">'
            '<option value="10"/><option value="50"/></param>'
            '<param name="p" style="plain" type="xsd:string" required="false"/>'
            '</request><response status="204"/></method></resource>'
        )
    )
    params = {p.name: p for p in _operations(api)["GET /a;v"].parameters}
    assert params["v"].location is ParameterLocation.PATH and params["v"].extras["wadl_style"] == "matrix"
    assert params["tag"].type.item is not None and params["tag"].type.item.name == "string"
    assert params["size"].default == "10" and params["size"].constraints.enum == ["10", "50"]
    assert params["p"].extras["wadl_style"] == "plain"
    # A param whose style has its own canonical location records no style.
    assert "wadl_style" not in params["tag"].extras


def test_messages_carry_media_types_and_status_codes() -> None:
    api = _version("library.v2-compatible.wadl")
    operations = _operations(api)
    listed = next(m for m in operations["GET /loans"].messages if m.role is MessageRole.RESPONSE)
    assert listed.content_types == ["application/xml", "application/json"]
    assert listed.status_code == "200"
    created = operations["POST /loans"]
    assert {m.status_code for m in created.messages if m.role is MessageRole.RESPONSE} == {"201", "400", "409"}


def test_a_representation_without_a_type_still_records_its_media_type() -> None:
    api = _api(
        _wadl(
            '<resource path="f"><method name="POST" id="f"><request>'
            '<representation mediaType="application/x-www-form-urlencoded"/></request>'
            '<response status="202"/></method></resource>'
        )
    )
    request = next(m for m in _operations(api)["POST /f"].messages if m.role is MessageRole.REQUEST)
    assert request.payload is None and request.content_types == ["application/x-www-form-urlencoded"]


def test_more_xsd_builtins_are_primitives() -> None:
    api = _grammar_api(
        '<xsd:element name="u" type="xsd:anyURI"/><xsd:element name="n" type="xsd:nonNegativeInteger"/>'
        '<xsd:element name="b" type="xsd:base64Binary"/>'
    )
    fields = _fields(api, "Item")
    assert (fields["u"].type.name, fields["n"].type.name, fields["b"].type.name) == ("string", "uint64", "string")
    assert {"string", "uint64", "i64", "bool"} <= CANONICAL_PRIMITIVES


def test_unresolved_references_reach_the_model() -> None:
    api = _api(
        _wadl('<resource path="a"><method href="#missing"/><method name="GET" id="a"><response/></method></resource>')
    )
    assert api.extras["wadl_unresolved_refs"] == ["method #missing"]


def test_explicit_method_id_tells_a_declared_id_from_a_synthesized_name() -> None:
    operations = _operations(_api((_EXAMPLES / "04-kitchen-sink.wadl").read_text(encoding="utf-8")))
    assert explicit_method_id(operations["GET /query"]) == "search"
    assert explicit_method_id(operations["GET /corpus/{collection};view"]) is None


# --- lint ------------------------------------------------------------------------------------


def test_the_pack_is_registered_and_native() -> None:
    assert get_rule_pack("wadl") is WadlRulePack
    assert capability_for_format("wadl").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in WadlRulePack().rules()]
    assert len(ids) == len(set(ids)) == 13
    assert all(rule_id.startswith("wadl.") for rule_id in ids)


@pytest.mark.parametrize("path", sorted(_EXAMPLES.glob("*.wadl")), ids=lambda p: p.name)
def test_the_corpus_raises_no_wadl_errors_or_warnings(path: Path) -> None:
    findings = _findings(path.read_text(encoding="utf-8"))
    assert [f for f in findings if f[1] != "info"] == []


def test_the_version_fixtures_lint_clean() -> None:
    for name in ("library.v1.wadl", "library.v2-compatible.wadl", "library.v3-breaking.wadl"):
        assert _findings((_VERSIONS / name).read_text(encoding="utf-8")) == [], name


def test_unresolved_references_are_errors() -> None:
    findings = _findings(
        _wadl('<resource path="a" type="#rt"><method name="GET" id="a"><response/></method></resource>')
    )
    assert ("wadl.reference-resolved", "error", "references.#rt") in findings


def test_template_params_must_be_declared_and_used() -> None:
    text = _wadl(
        '<resource path="a/{x}"><param name="y" style="template" type="xsd:string"/>'
        '<method name="GET" id="a"><response/></method></resource>'
    )
    findings = _findings(text)
    assert ("wadl.template-param-declared", "error", "GET /a/{x}") in findings
    assert ("wadl.template-param-used", "warning", "GET /a/{x}#path.y") in findings


def test_a_matrix_param_is_not_a_template_variable() -> None:
    text = _wadl(
        '<resource path="a;v"><param name="v" style="matrix" type="xsd:string"/>'
        '<method name="GET" id="a"><response/></method></resource>'
    )
    assert "wadl.template-param-used" not in _rules(text)


def test_method_ids_should_be_present_and_unique() -> None:
    text = _wadl(
        '<resource path="a"><method name="GET" id="dup"><response/></method>'
        '<method name="POST" id="dup"><response/></method><method name="PUT"><response/></method></resource>'
    )
    findings = _findings(text)
    assert ("wadl.method-id-unique", "error", "POST /a") in findings
    assert ("wadl.method-id-present", "info", "PUT /a") in findings


def test_non_standard_verbs_bodies_on_safe_methods_and_missing_responses() -> None:
    text = _wadl(
        '<resource path="a"><method name="PURGE" id="purge"><response status="204"/></method>'
        '<method name="GET" id="get"><request><representation mediaType="application/xml"/></request>'
        '<response status="200"/></method><method name="DELETE" id="del"/></resource>'
    )
    findings = _findings(text)
    assert ("wadl.method-name-standard", "warning", "PURGE /a") in findings
    assert ("wadl.body-on-safe-method", "warning", "GET /a") in findings
    assert ("wadl.response-declared", "warning", "DELETE /a") in findings
    assert "PURGE" not in STANDARD_HTTP_METHODS


def test_a_status_must_be_three_digits() -> None:
    findings = _findings(
        _wadl('<resource path="a"><method name="GET" id="a"><response status="2xx"/></method></resource>')
    )
    assert ("wadl.response-status-valid", "warning", "GET /a#response.2xx") in findings


def test_undeclared_types_are_flagged_where_they_are_used() -> None:
    text = _wadl(
        '<resource path="a"><param name="q" style="query" type="tns:Missing"/>'
        '<method name="GET" id="a"><response status="200">'
        '<representation mediaType="application/xml" element="tns:ghost"/></response></method></resource>',
        grammar=(
            '<xsd:complexType name="Item"><xsd:sequence>'
            '<xsd:element name="x" type="tns:Other"/></xsd:sequence></xsd:complexType>'
        ),
    )
    paths = {path for rule, _, path in _findings(text) if rule == "wadl.type-resolved"}
    assert paths == {f"{_NS}.Item.x", "GET /a#query.q", "GET /a#response.200"}


def test_representations_should_be_typed_and_state_their_media_type() -> None:
    text = _wadl(
        '<resource path="a"><method name="POST" id="a">'
        '<request><representation mediaType="application/xml"/></request>'
        '<response status="200"><representation element="tns:item"/></response></method></resource>',
        grammar=_ITEM,
    )
    findings = _findings(text)
    assert ("wadl.representation-typed", "info", "POST /a#request") in findings
    assert ("wadl.representation-media-type", "info", "POST /a#response.200") in findings


def test_a_form_body_is_not_expected_to_be_typed() -> None:
    text = _wadl(
        '<resource path="a"><method name="POST" id="a"><request>'
        '<representation mediaType="application/x-www-form-urlencoded"/></request>'
        '<response status="202"/></method></resource>'
    )
    assert "wadl.representation-typed" not in _rules(text)


def test_a_missing_base_uri_is_noted() -> None:
    findings = _findings(_wadl('<resource path="a"><method name="GET" id="a"><response/></method></resource>', base=""))
    assert ("wadl.base-uri-present", "info", "resources.base") in findings


# --- breaking changes --------------------------------------------------------------------------


def test_the_classifier_is_registered() -> None:
    assert "wadl" in available_breaking_change_formats()
    assert WadlBreakingChangeClassifier.classifier_id == "wadl-resources"
    assert len(RULE_IDS) == len(set(RULE_IDS)) == 23


def test_the_compatible_version_grades_safe() -> None:
    v1, v2 = _version("library.v1.wadl"), _version("library.v2-compatible.wadl")
    grades = _grades(v1, v2)
    assert grades == {
        ("modified", "GET /loans"): (Severity.SAFE, "wadl.parameter-added-optional"),
        ("modified", "GET /loans#response.200"): (Severity.SAFE, "wadl.media-type-added"),
        ("added", "http://example.com/library.Loan.branch"): (Severity.SAFE, "wadl.element-added-optional"),
    }
    # The new status option is graded with the param that carries it.
    rationale = next(c.rationale for c in classify_models(v1, v2).classifications if c.key == "GET /loans")
    assert "'LOST'" in rationale


def test_the_breaking_version_grades_each_change() -> None:
    grades = _grades(_version("library.v1.wadl"), _version("library.v3-breaking.wadl"))
    loan = "http://example.com/library.Loan"
    assert grades == {
        ("modified", "GET /loans"): (Severity.BREAKING, "wadl.parameter-added-required"),
        ("modified", "POST /loans#request"): (Severity.BREAKING, "wadl.media-type-removed"),
        ("modified", "http://example.com/library.LoanStatus"): (Severity.BREAKING, "wadl.enum-value-removed"),
        ("modified", f"{loan}.isbn"): (Severity.BREAKING, "wadl.element-reordered"),
        ("modified", f"{loan}.member"): (Severity.BREAKING, "wadl.element-reordered"),
        ("modified", f"{loan}.note"): (Severity.BREAKING, "wadl.element-made-required"),
        ("modified", f"{loan}.renewal"): (Severity.BREAKING, "wadl.occurs-narrowed"),
    }


def test_an_insertion_shifts_later_elements_without_reordering_them() -> None:
    base = _grammar_api('<xsd:element name="a" type="xsd:string"/><xsd:element name="c" type="xsd:string"/>')
    target = _grammar_api(
        '<xsd:element name="a" type="xsd:string"/><xsd:element name="b" type="xsd:string" minOccurs="0"/>'
        '<xsd:element name="c" type="xsd:string"/>'
    )
    grades = _grades(base, target)
    assert grades[("added", f"{_NS}.Item.b")] == (Severity.SAFE, "wadl.element-added-optional")
    assert grades[("modified", f"{_NS}.Item.c")] == (Severity.SAFE, "wadl.element-shifted")
    assert relative_order_changed(base, target, f"{_NS}.Item.c") is False


def test_a_required_element_added_breaks_documents_written_without_it() -> None:
    base = _grammar_api('<xsd:element name="a" type="xsd:string"/>')
    target = _grammar_api('<xsd:element name="a" type="xsd:string"/><xsd:element name="b" type="xsd:string"/>')
    assert _grades(base, target)[("added", f"{_NS}.Item.b")] == (Severity.BREAKING, "wadl.element-added-required")


@pytest.mark.parametrize(
    "before,after,expected",
    [
        ('type="xsd:string"', 'type="xsd:string" minOccurs="0"', (Severity.DANGEROUS, "wadl.element-made-optional")),
        ('type="xsd:string"', 'type="xsd:int"', (Severity.BREAKING, "wadl.element-type-changed")),
        (
            'type="xsd:string" maxOccurs="2"',
            'type="xsd:string" maxOccurs="4"',
            (Severity.DANGEROUS, "wadl.occurs-widened"),
        ),
        (
            'type="xsd:string" maxOccurs="4"',
            'type="xsd:string" maxOccurs="2"',
            (Severity.BREAKING, "wadl.occurs-narrowed"),
        ),
        (
            'type="xsd:string"',
            'type="xsd:string" maxOccurs="unbounded"',
            (Severity.BREAKING, "wadl.element-type-changed"),
        ),
    ],
)
def test_element_changes(before: str, after: str, expected) -> None:
    base = _grammar_api(f'<xsd:element name="a" {before}/>')
    target = _grammar_api(f'<xsd:element name="a" {after}/>')
    assert _grades(base, target)[("modified", f"{_NS}.Item.a")] == expected


def _with_param(param: str):
    return _api(
        _wadl(f'<resource path="a"><method name="GET" id="a"><request>{param}</request><response/></method></resource>')
    )


@pytest.mark.parametrize(
    "before,after,expected",
    [
        (
            '<param name="s" style="query" type="xsd:string" required="false">'
            '<option value="A"/><option value="B"/></param>',
            '<param name="s" style="query" type="xsd:string" required="false"><option value="A"/></param>',
            (Severity.BREAKING, "wadl.parameter-option-removed"),
        ),
        (
            '<param name="s" style="query" type="xsd:string" required="false"><option value="A"/></param>',
            '<param name="s" style="query" type="xsd:string" required="false"/>',
            (Severity.SAFE, "wadl.parameter-option-added"),
        ),
        (
            '<param name="s" style="query" type="xsd:string" required="false"/>',
            '<param name="s" style="query" type="xsd:string" required="false"><option value="A"/></param>',
            (Severity.BREAKING, "wadl.parameter-option-removed"),
        ),
        (
            '<param name="s" style="query" type="xsd:string" required="false"/>',
            '<param name="s" style="query" type="xsd:int" required="false"/>',
            (Severity.BREAKING, "wadl.parameter-type-changed"),
        ),
        (
            '<param name="s" style="query" type="xsd:string" required="false"/>',
            '<param name="s" style="query" type="xsd:string" required="true"/>',
            (Severity.BREAKING, "wadl.parameter-made-required"),
        ),
        (
            '<param name="s" style="query" type="xsd:string" required="false"/>',
            "",
            (Severity.DANGEROUS, "wadl.parameter-removed"),
        ),
    ],
)
def test_param_changes(before: str, after: str, expected) -> None:
    assert _grades(_with_param(before), _with_param(after))[("modified", "GET /a")] == expected


def test_a_representation_naming_another_element_is_breaking() -> None:
    grammar = (
        _ITEM
        + '<xsd:element name="other" type="tns:Other"/><xsd:complexType name="Other"><xsd:sequence/></xsd:complexType>'
    )

    def api(element: str):
        return _api(
            _wadl(
                f'<resource path="a"><method name="GET" id="a"><response status="200">'
                f'<representation mediaType="application/xml" element="tns:{element}"/></response></method></resource>',
                grammar,
            )
        )

    grades = _grades(api("item"), api("other"))
    assert grades[("modified", "GET /a#response.200")] == (Severity.BREAKING, "wadl.representation-type-changed")


def test_enum_value_added_is_dangerous_and_a_removed_method_keeps_the_baseline() -> None:
    def api(values: str, extra_method: str = ""):
        grammar = (
            _ITEM
            + f'<xsd:simpleType name="S"><xsd:restriction base="xsd:string">{values}</xsd:restriction></xsd:simpleType>'
        )
        return _api(_wadl(_GET_ITEM + extra_method, grammar))

    a = '<xsd:enumeration value="A"/>'
    b = '<xsd:enumeration value="B"/>'
    grades = _grades(api(a, '<resource path="x"><method name="GET" id="x"><response/></method></resource>'), api(a + b))
    assert grades[("modified", f"{_NS}.S")] == (Severity.DANGEROUS, "wadl.enum-value-added")
    assert grades[("removed", "GET /x")] == (Severity.BREAKING, "removed-entity")


# --- migrate to OpenAPI ----------------------------------------------------------------------


def _convert(path: Path):
    item = {
        "id": f"wadl-{path.stem}",
        "source_format": "wadl",
        "protocol": None,
        "tool_versions": {},
        "format_metadata": {"sourceContent": path.read_text(encoding="utf-8"), "sourceLabel": path.name},
    }
    return preview_conversion(build_conversion_source(item))


def test_the_library_migrates_to_valid_openapi_with_its_method_ids() -> None:
    preview = _convert(_VERSIONS / "library.v1.wadl")
    assert preview.pack is not None and preview.pack.key == "wadl"
    document = preview.document
    assert validate_openapi_document(document) == []
    assert document["paths"]["/loans"]["get"]["operationId"] == "listLoans"
    assert document["paths"]["/loans"]["post"]["operationId"] == "createLoan"
    assert document["paths"]["/loans/{loanId}"]["get"]["operationId"] == "getLoan"
    (status,) = document["paths"]["/loans"]["get"]["parameters"]
    assert status["schema"]["enum"] == ["ACTIVE", "RETURNED", "OVERDUE"]
    assert set(document["paths"]["/loans"]["post"]["responses"]) == {"201", "400", "409"}
    assert any("operationId" in note for note in preview.pack.refinements)


def test_a_shared_method_id_is_left_to_the_projection(tmp_path: Path) -> None:
    fixture = tmp_path / "dup.wadl"
    fixture.write_text(
        _wadl(
            '<resource path="a"><method name="GET" id="dup"><response status="200"/></method>'
            '<method name="POST" id="dup"><response status="201"/></method>'
            '<method name="PUT" id="put"><response status="200"/></method></resource>'
        ),
        encoding="utf-8",
    )
    document = _convert(fixture).document
    assert validate_openapi_document(document) == []
    ids = [op["operationId"] for op in document["paths"]["/a"].values()]
    assert len(ids) == len(set(ids))
    assert document["paths"]["/a"]["put"]["operationId"] == "put"


# --- WADL → WADL stays lossless ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["library.v1.wadl", "library.v2-compatible.wadl", "library.v3-breaking.wadl"])
def test_the_version_fixtures_round_trip_through_the_emitter(name: str) -> None:
    api = _version(name)
    emitted = WadlEmitter().emit(api)
    again = reimport_emitted(WadlImportSource(), emitted, multi_file=True)
    assert canonical_diff(api, again).entries == []
    # The options a param allows are written back as `option` children.
    assert 'value="RETURNED"' in emitted.files[0].content
