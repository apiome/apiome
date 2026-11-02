"""Tests for the ISO 8583 message definition: MTI decoding, bitmaps, lint and breaking changes —
MFI-20.6 (#3990)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.iso8583_breaking import Iso8583BreakingChangeClassifier
from app.iso8583_import_source import Iso8583ImportSource
from app.iso8583_lint import Iso8583RulePack
from app.iso8583_message_type import bitmaps_for, decode_mti, is_response_function
from app.lint_engine import get_rule_pack, lint_canonical_model

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "iso8583"
_VALID = [
    "01-authorization-0100.json",
    "02-authorization-response-0110.json",
    "03-network-echo-0800.json",
    "04-financial-request-0200.json",
    "05-reversal-advice-0420.json",
    "06-atm-withdrawal-0200.json",
]


def _api(text: str):
    adapter = Iso8583ImportSource()
    return adapter.normalize(adapter.parse(text, source_label="msg.json"), include_raw=False)


def _document(mti: str = "0100", elements: Dict[str, dict] | None = None, name: str = "Test") -> str:
    base = {
        "7": {"name": "Transmission Date & Time", "type": "n", "length": "10", "value": "0115083000"},
        "11": {"name": "System Trace Audit Number", "type": "n", "length": "6", "value": "000001"},
    }
    return json.dumps({"mti": mti, "name": name, "dataElements": elements if elements is not None else base})


# --- MTI and bitmap -----------------------------------------------------------------------


def test_decode_mti_names_every_position():
    decoded = decode_mti("0100")
    assert decoded["version_label"] == "ISO 8583:1987"
    assert decoded["class_label"] == "Authorization"
    assert decoded["function_label"] == "Request"
    assert decoded["origin_label"] == "Acquirer"
    assert decoded["summary"] == "Authorization request (acquirer)"
    assert decode_mti("1210")["summary"] == "Financial request response (acquirer)"
    assert decode_mti("0800")["class_label"] == "Network management"


def test_decode_mti_tolerates_reserved_and_malformed_values():
    reserved = decode_mti("0900")
    assert reserved["class"] == "9" and reserved["class_label"] is None and reserved["summary"] is None
    assert decode_mti("ABCD") == decode_mti("01") == {
        "version": None, "class": None, "function": None, "origin": None,
        "version_label": None, "class_label": None, "function_label": None, "origin_label": None,
        "summary": None,
    }
    assert is_response_function("1") and is_response_function("3") and not is_response_function("0")


def test_bitmaps_follow_the_elements_present():
    primary_only = bitmaps_for(["2", "3", "4", "7", "11"])
    assert primary_only["has_secondary"] is False and primary_only["secondary"] is None
    # DE 2, 3, 4 → bits 2–4 of the first byte (0111 0000), DE 7 → bit 7, DE 11 → bit 11.
    assert primary_only["primary"] == "7220000000000000"
    assert primary_only["elements"] == [2, 3, 4, 7, 11]
    with_secondary = bitmaps_for([2, 90, 128])
    assert with_secondary["has_secondary"] is True
    assert with_secondary["primary"].startswith("C")  # bit 1 (secondary follows) and bit 2
    assert with_secondary["secondary"] == "0000004000000001"
    assert bitmaps_for(["x", "0", "129"]) == {
        "primary": "0" * 16,
        "secondary": None,
        "has_secondary": False,
        "elements": [],
    }


def test_normalizer_records_the_definition():
    api = _api((_EXAMPLES / "05-reversal-advice-0420.json").read_text(encoding="utf-8"))
    assert api.extras["iso8583_mti_decoded"]["summary"] == "Reversal and chargeback advice (acquirer)"
    bitmap = api.extras["iso8583_bitmap"]
    assert bitmap["has_secondary"] is True and 128 in bitmap["elements"]
    message = next(t for t in api.types if t.extras.get("iso8583_kind") == "message")
    assert message.extras["iso8583_bitmap"] == bitmap
    numbers = {f.name: f.field_number for f in message.fields}
    assert numbers["DE2"] == 2 and numbers["DE128"] == 128


# --- lint ---------------------------------------------------------------------------------


def _findings(text: str) -> List[Tuple[str, str, str]]:
    result = lint_canonical_model(_api(text))
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("iso8583."))


def test_the_lint_pack_is_registered():
    assert get_rule_pack("iso8583") is not None
    assert capability_for_format("iso8583").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in Iso8583RulePack().rules()]
    assert len(ids) == len(set(ids)) and all(i.startswith("iso8583.") for i in ids)


@pytest.mark.parametrize("name", [n for n in _VALID if n != "03-network-echo-0800.json"])
def test_every_full_example_is_clean(name: str):
    assert _findings((_EXAMPLES / name).read_text(encoding="utf-8")) == []


def test_the_minimal_echo_example_lints_as_minimal():
    """The smallest document (an MTI and DE 70) is flagged for the trace fields it leaves out."""
    assert _findings((_EXAMPLES / "03-network-echo-0800.json").read_text(encoding="utf-8")) == [
        ("iso8583.stan-present", "warning", "dataElements.11"),
        ("iso8583.transmission-datetime-present", "info", "dataElements.7"),
    ]


def test_mti_known():
    assert ("iso8583.mti-known", "warning", "mti") in _findings(_document(mti="0900"))
    assert ("iso8583.mti-known", "warning", "mti") in _findings(_document(mti="0180"))
    assert not [f for f in _findings(_document(mti="0100")) if f[0] == "iso8583.mti-known"]


def test_de_number_valid():
    elements = {
        "1": {"name": "Bitmap", "type": "b", "length": "16", "value": "00"},
        "7": {"name": "T", "type": "n", "length": "10", "value": "0"},
        "11": {"name": "S", "type": "n", "length": "6", "value": "1"},
        "129": {"name": "X", "type": "n", "length": "1", "value": "1"},
    }
    findings = _findings(_document(elements=elements))
    assert ("iso8583.de-number-valid", "error", "dataElements.1") in findings
    assert ("iso8583.de-number-valid", "error", "dataElements.129") in findings


def test_de_type_and_length():
    elements = {
        "7": {"name": "T", "type": "n", "length": "10", "value": "0"},
        "11": {"name": "S", "type": "n", "length": "6", "value": "1"},
        "41": {"name": "Terminal", "type": "text", "value": "T1"},
    }
    findings = _findings(_document(elements=elements))
    assert ("iso8583.de-type-known", "warning", "dataElements.41") in findings
    assert ("iso8583.de-length-declared", "warning", "dataElements.41") in findings


def test_stan_and_transmission_datetime():
    only_pan = {"2": {"name": "PAN", "type": "n", "length": "..19", "value": "4111"}}
    findings = _findings(_document(elements=only_pan))
    assert ("iso8583.stan-present", "warning", "dataElements.11") in findings
    assert ("iso8583.transmission-datetime-present", "info", "dataElements.7") in findings


def test_response_code_on_response():
    response = _findings(_document(mti="0110"))
    assert ("iso8583.response-code-on-response", "warning", "dataElements.39") in response
    assert not [f for f in _findings(_document(mti="0100")) if f[0] == "iso8583.response-code-on-response"]


# --- breaking changes ---------------------------------------------------------------------


def _grades(base: str, target: str) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    result = classify_models(_api(base), _api(target))
    assert result.classifier == Iso8583BreakingChangeClassifier.classifier_id
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


_DE = {
    "7": {"name": "Transmission Date & Time", "type": "n", "length": "10", "value": "0115083000"},
    "11": {"name": "System Trace Audit Number", "type": "n", "length": "6", "value": "000001"},
    "41": {"name": "Card Acceptor Terminal ID", "type": "ans", "length": "8", "value": "TERM0001"},
}


def _with(**changes: dict) -> str:
    elements = {k: dict(v) for k, v in _DE.items()}
    for number, change in changes.items():
        if change is None:
            elements.pop(number)
        else:
            elements.setdefault(number, {}).update(change)
    return _document(elements=elements)


def test_the_classifier_is_registered():
    assert "iso8583" in available_breaking_change_formats()


def test_data_element_additions_and_removals():
    with_49 = _with(**{"49": {"name": "Currency Code", "type": "n", "length": "3", "value": "840"}})
    assert _grades(_with(), with_49)[("added", "0100.Message0100.DE49")] == (Severity.DANGEROUS, "iso8583.de-added")
    assert _grades(with_49, _with())[("removed", "0100.Message0100.DE49")] == (Severity.BREAKING, "iso8583.de-removed")


def test_length_and_type_changes_are_breaking():
    assert _grades(_with(), _with(**{"41": {"length": "16"}}))[("modified", "0100.Message0100.DE41")] == (
        Severity.BREAKING,
        "iso8583.de-length-changed",
    )
    assert _grades(_with(), _with(**{"41": {"type": "an"}}))[("modified", "0100.Message0100.DE41")] == (
        Severity.BREAKING,
        "iso8583.de-type-changed",
    )


def test_name_and_sample_value_changes_are_safe():
    renamed = _grades(_with(), _with(**{"41": {"name": "Terminal Identifier"}}))
    assert renamed[("modified", "0100.Message0100.DE41")] == (Severity.SAFE, "iso8583.de-renamed")
    assert _grades(_with(), _with(**{"41": {"value": "TERM0002"}}))[("modified", "0100.Message0100.DE41")] == (
        Severity.SAFE,
        "iso8583.sample-value-changed",
    )


def test_a_changed_mti_is_breaking():
    grades = _grades(_document(mti="0100", elements=_DE), _document(mti="0120", elements=_DE))
    # The MTI is every key's namespace, so the message record is removed and re-added; both halves
    # carry the one rule, and the data elements that moved with it keep their own grades.
    assert grades[("removed", "0100.Message0100")] == (Severity.BREAKING, "iso8583.mti-changed")
    assert grades[("added", "0120.Message0120")] == (Severity.BREAKING, "iso8583.mti-changed")
