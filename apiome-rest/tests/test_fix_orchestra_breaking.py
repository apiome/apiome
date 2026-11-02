"""Tests for the FIX Orchestra breaking-change classifier — MFI-20.4 (#3988)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.fix_orchestra_import_source import FixOrchestraImportSource

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "fix-orchestra"
_NS = "http://fixprotocol.io/2020/orchestra/repository"


def _fixture(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


def _api(text: str):
    adapter = FixOrchestraImportSource()
    return adapter.normalize(adapter.parse(text, source_label="repo.xml"), include_raw=False)


def _grades(base: str, target: str) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two repositories."""
    result = classify_models(_api(base), _api(target))
    assert result.classifier == "fix-orchestra-dialect"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


def _repository(fields: str, structure: str, *, code_sets: str = "") -> str:
    return (
        f'<fixr:repository xmlns:fixr="{_NS}" name="T" version="FIX.4.4">'
        f"<fixr:codeSets>{code_sets}</fixr:codeSets><fixr:fields>{fields}</fixr:fields>"
        '<fixr:messages><fixr:message name="NewOrderSingle" id="14" msgType="D">'
        f"<fixr:structure>{structure}</fixr:structure></fixr:message></fixr:messages></fixr:repository>"
    )


_F = '<fixr:field id="11" name="ClOrdID" type="String"/><fixr:field id="55" name="Symbol" type="String"/>'


def test_the_classifier_is_registered_for_fix_orchestra():
    assert "fix-orchestra" in available_breaking_change_formats()


# --- the dialect fixture: EP001 → the venue's EP002 ---------------------------------------


def test_the_venue_dialect_fixture_is_graded_rule_by_rule():
    grades = _grades(
        _fixture("02-typical-order-repository.xml"),
        _fixture("08-typical-order-repository-venue-dialect.xml"),
    )
    by_rule: Dict[str, set] = {}
    for key, (_, rule) in grades.items():
        by_rule.setdefault(rule, set()).add(key)
    assert ("added", "NewOrderSingle.ExDestination") in by_rule["fix-orchestra.optional-field-added"]
    assert ("modified", "NewOrderSingle.TimeInForce") in by_rule["fix-orchestra.made-required"]
    assert ("modified", "NewOrderSingle.Price") in by_rule["fix-orchestra.presence-relaxed"]
    assert ("modified", "Instrument.SecurityIDSource") in by_rule["fix-orchestra.made-forbidden"]
    assert ("modified", "SideCodeSet") in by_rule["fix-orchestra.code-removed"]
    assert ("modified", "OrdTypeCodeSet") in by_rule["fix-orchestra.code-removed"]
    assert ("added", "OrderCancelReject") in by_rule["added-entity"]
    assert grades[("modified", "NewOrderSingle.TimeInForce")][0] is Severity.BREAKING
    assert grades[("modified", "SideCodeSet")][0] is Severity.BREAKING
    assert grades[("added", "NewOrderSingle.ExDestination")][0] is Severity.SAFE


# --- fields -------------------------------------------------------------------------------


def test_a_rename_that_keeps_the_tag_and_type_is_dangerous():
    before = _repository(_F, '<fixr:fieldRef id="11" presence="required"/>')
    after = _repository(
        '<fixr:field id="11" name="ClientOrderID" type="String"/>',
        '<fixr:fieldRef id="11" presence="required"/>',
    )
    grades = _grades(before, after)
    assert grades[("removed", "NewOrderSingle.ClOrdID")] == (Severity.DANGEROUS, "fix-orchestra.field-renamed")
    assert grades[("added", "NewOrderSingle.ClientOrderID")] == (Severity.DANGEROUS, "fix-orchestra.field-renamed")


def test_a_tag_reused_for_another_type_is_breaking():
    before = _repository(_F, '<fixr:fieldRef id="55" presence="optional"/>')
    after = _repository(
        '<fixr:field id="55" name="OrderQty" type="Qty"/><fixr:field id="11" name="ClOrdID" type="String"/>',
        '<fixr:fieldRef id="55" presence="optional"/>',
    )
    grades = _grades(before, after)
    assert grades[("removed", "NewOrderSingle.Symbol")] == (Severity.BREAKING, "fix-orchestra.tag-reused")
    assert grades[("added", "NewOrderSingle.OrderQty")] == (Severity.BREAKING, "fix-orchestra.tag-reused")


def test_a_field_moved_to_another_tag_is_breaking():
    before = _repository(_F, '<fixr:fieldRef id="55" presence="optional"/>')
    after = _repository(
        '<fixr:field id="11" name="ClOrdID" type="String"/><fixr:field id="65" name="Symbol" type="String"/>',
        '<fixr:fieldRef id="65" presence="optional"/>',
    )
    assert _grades(before, after)[("modified", "NewOrderSingle.Symbol")] == (
        Severity.BREAKING,
        "fix-orchestra.tag-changed",
    )


def test_added_and_removed_fields_depend_on_presence():
    only_clordid = _repository(_F, '<fixr:fieldRef id="11" presence="required"/>')
    both_required = _repository(
        _F, '<fixr:fieldRef id="11" presence="required"/><fixr:fieldRef id="55" presence="required"/>'
    )
    both_optional = _repository(
        _F, '<fixr:fieldRef id="11" presence="required"/><fixr:fieldRef id="55" presence="optional"/>'
    )
    assert _grades(only_clordid, both_required)[("added", "NewOrderSingle.Symbol")] == (
        Severity.BREAKING,
        "fix-orchestra.required-field-added",
    )
    assert _grades(only_clordid, both_optional)[("added", "NewOrderSingle.Symbol")] == (
        Severity.SAFE,
        "fix-orchestra.optional-field-added",
    )
    assert _grades(both_required, only_clordid)[("removed", "NewOrderSingle.Symbol")] == (
        Severity.BREAKING,
        "fix-orchestra.required-field-removed",
    )
    assert _grades(both_optional, only_clordid)[("removed", "NewOrderSingle.Symbol")] == (
        Severity.DANGEROUS,
        "fix-orchestra.optional-field-removed",
    )


def _presence_grade(before: str, after: str) -> Tuple[Severity, str]:
    base = _repository(_F, f'<fixr:fieldRef id="11" presence="required"/><fixr:fieldRef id="55" presence="{before}"/>')
    target = _repository(_F, f'<fixr:fieldRef id="11" presence="required"/><fixr:fieldRef id="55" presence="{after}"/>')
    return _grades(base, target)[("modified", "NewOrderSingle.Symbol")]


def test_presence_transitions():
    assert _presence_grade("optional", "required") == (Severity.BREAKING, "fix-orchestra.made-required")
    assert _presence_grade("optional", "forbidden") == (Severity.BREAKING, "fix-orchestra.made-forbidden")
    assert _presence_grade("required", "optional") == (Severity.DANGEROUS, "fix-orchestra.made-optional")
    assert _presence_grade("optional", "ignored") == (Severity.DANGEROUS, "fix-orchestra.made-ignored")
    assert _presence_grade("forbidden", "optional") == (Severity.SAFE, "fix-orchestra.presence-relaxed")
    assert _presence_grade("forbidden", "required") == (Severity.BREAKING, "fix-orchestra.made-required")


def test_a_constant_value_change_is_breaking():
    base = _repository(_F, '<fixr:fieldRef id="55" presence="constant" value="AAPL"/>')
    target = _repository(_F, '<fixr:fieldRef id="55" presence="constant" value="MSFT"/>')
    assert _grades(base, target)[("modified", "NewOrderSingle.Symbol")] == (
        Severity.BREAKING,
        "fix-orchestra.constant-changed",
    )


def test_a_changed_conditional_rule_is_dangerous():
    def with_rule(when: str) -> str:
        return _repository(
            _F,
            '<fixr:fieldRef id="55" presence="conditional"><fixr:rule name="r" presence="required">'
            f"<fixr:when>{when}</fixr:when></fixr:rule></fixr:fieldRef>",
        )

    assert _grades(with_rule("OrdType == 1"), with_rule("OrdType == 2"))[("modified", "NewOrderSingle.Symbol")] == (
        Severity.DANGEROUS,
        "fix-orchestra.rules-changed",
    )


# --- code sets and messages ---------------------------------------------------------------


def _with_codes(codes: str) -> str:
    return _repository(
        '<fixr:field id="54" name="Side" type="SideCodeSet"/>',
        '<fixr:fieldRef id="54" presence="required"/>',
        code_sets=f'<fixr:codeSet name="SideCodeSet" id="54" type="char">{codes}</fixr:codeSet>',
    )


_BUY_SELL = '<fixr:code name="Buy" id="1" value="1"/><fixr:code name="Sell" id="2" value="2"/>'


def test_code_set_changes():
    added = _BUY_SELL + '<fixr:code name="Cross" id="8" value="8"/>'
    assert _grades(_with_codes(_BUY_SELL), _with_codes(added))[("modified", "SideCodeSet")] == (
        Severity.SAFE,
        "fix-orchestra.code-added",
    )
    assert _grades(_with_codes(added), _with_codes(_BUY_SELL))[("modified", "SideCodeSet")] == (
        Severity.BREAKING,
        "fix-orchestra.code-removed",
    )
    renumbered = '<fixr:code name="Buy" id="1" value="B"/><fixr:code name="Sell" id="2" value="2"/>'
    assert _grades(_with_codes(_BUY_SELL), _with_codes(renumbered))[("modified", "SideCodeSet")] == (
        Severity.BREAKING,
        "fix-orchestra.code-value-changed",
    )


def test_a_changed_msgtype_is_breaking():
    base = _repository(_F, '<fixr:fieldRef id="11" presence="required"/>')
    target = base.replace('msgType="D"', 'msgType="AB"')
    assert _grades(base, target)[("modified", "NewOrderSingle")] == (
        Severity.BREAKING,
        "fix-orchestra.msgtype-changed",
    )
