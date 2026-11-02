"""Tests for the HL7 v2 lint pack and the migrate-to-FHIR note — MFI-20.2 (#3986)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.hl7v2_lint import (
    FHIR_RESOURCE_FOR_SEGMENT,
    STANDARD_ENCODING_CHARACTERS,
    Hl7V2RulePack,
    fhir_counterparts,
)
from app.hl7v2_normalizer import Hl7V2Normalizer
from app.hl7v2_parser import parse_hl7v2
from app.lint_engine import get_rule_pack, lint_canonical_model

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/hl7v2"
_ADT = (_EXAMPLES / "01-adt-a01.hl7").read_text(encoding="utf-8")


def _with_msh(msh: str) -> str:
    """The ADT example with its MSH line replaced."""
    lines = _ADT.splitlines()
    return "\n".join([msh, *lines[1:]]) + "\n"


def _findings(text: str) -> List[Tuple[str, str, str]]:
    """``(rule, severity, path)`` of every ``hl7v2.*`` finding for a message."""
    api = Hl7V2Normalizer().normalize(parse_hl7v2(text), include_raw=False)
    result = lint_canonical_model(api)
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("hl7v2."))


def _findings_for_extras(**extras) -> List[Tuple[str, str, str]]:
    """``hl7v2.*`` findings for a bare HL7 v2 model carrying only *extras* (rule-level tests)."""
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="hl7v2",
        identity=ApiIdentity(name="t"),
        title="t",
        types=[],
        extras=extras,
    )
    return sorted(
        (f.rule, f.severity, f.path)
        for f in lint_canonical_model(api).findings
        if f.rule.startswith("hl7v2.")
    )


def test_the_pack_is_registered_for_hl7v2():
    assert get_rule_pack("hl7v2") is not None
    assert capability_for_format("hl7v2").mode == MODE_NATIVE


def test_rule_ids_are_namespaced_and_unique():
    ids = [rule.rule_id for rule in Hl7V2RulePack().rules()]
    assert len(ids) == len(set(ids))
    assert all(rule_id.startswith("hl7v2.") for rule_id in ids)


@pytest.mark.parametrize(
    "name",
    [
        "01-adt-a01.hl7",
        "02-oru-r01.hl7",
        "03-minimal-ack.hl7",
        "04-orm-o01-order.hl7",
        "05-adt-a08-repetitions-escapes.hl7",
        "06-vxu-v04-immunization.hl7",
    ],
)
def test_every_example_is_clean(name: str):
    assert _findings((_EXAMPLES / name).read_text(encoding="utf-8")) == []


def test_message_type_declared():
    msh = "MSH|^~\\&|ADT1|GHH|GHH LAB|GHH|20260115083000|||MSG00001|P|2.5"
    assert ("hl7v2.message-type-declared", "error", "MSH.9") in _findings(_with_msh(msh))


def test_trigger_event_declared():
    msh = "MSH|^~\\&|ADT1|GHH|GHH LAB|GHH|20260115083000||ADT|MSG00001|P|2.5"
    assert _findings(_with_msh(msh)) == [("hl7v2.trigger-event-declared", "warning", "MSH.9")]


def test_version_declared():
    msh = "MSH|^~\\&|ADT1|GHH|GHH LAB|GHH|20260115083000||ADT^A01|MSG00001|P|"
    assert _findings(_with_msh(msh)) == [("hl7v2.version-declared", "warning", "MSH.12")]


def test_control_id_present():
    msh = "MSH|^~\\&|ADT1|GHH|GHH LAB|GHH|20260115083000||ADT^A01||P|2.5"
    assert _findings(_with_msh(msh)) == [("hl7v2.control-id-present", "warning", "MSH.10")]


def test_processing_id_declared():
    msh = "MSH|^~\\&|ADT1|GHH|GHH LAB|GHH|20260115083000||ADT^A01|MSG00001||2.5"
    assert _findings(_with_msh(msh)) == [("hl7v2.processing-id-declared", "info", "MSH.11")]


def test_standard_encoding_characters():
    findings = _findings_for_extras(
        hl7v2_message_type="ADT^A01",
        hl7v2_version="2.5",
        hl7v2_control_id="1",
        hl7v2_envelope={"field_separator": "#", "encoding_characters": "^~\\#", "processing_id": "P"},
    )
    assert findings == [
        ("hl7v2.standard-encoding-characters", "warning", "MSH.1"),
        ("hl7v2.standard-encoding-characters", "warning", "MSH.2"),
    ]
    assert STANDARD_ENCODING_CHARACTERS == "^~\\&"


def test_rules_tolerate_a_model_without_an_envelope():
    assert _findings_for_extras() == [
        ("hl7v2.control-id-present", "warning", "MSH.10"),
        ("hl7v2.message-type-declared", "error", "MSH.9"),
        ("hl7v2.processing-id-declared", "info", "MSH.11"),
        ("hl7v2.version-declared", "warning", "MSH.12"),
    ]


# --- migrate-to-FHIR note ----------------------------------------------------------------


def test_fhir_counterparts_keeps_only_known_segments_sorted():
    assert fhir_counterparts(["PV1", "PID", "EVN", "PID", "ZZZ"]) == {
        "PID": "Patient",
        "PV1": "Encounter",
    }
    assert fhir_counterparts([]) == {}
    assert FHIR_RESOURCE_FOR_SEGMENT["OBX"] == "Observation"


def test_normalizer_records_the_fhir_counterparts_of_the_segments_present():
    api = Hl7V2Normalizer().normalize(parse_hl7v2(_ADT), include_raw=False)
    counterparts = api.extras["hl7v2_fhir_counterparts"]
    assert counterparts["MSH"] == "MessageHeader"
    assert counterparts["PID"] == "Patient"
    assert counterparts["PV1"] == "Encounter"
    assert counterparts["NK1"] == "RelatedPerson"
    assert "EVN" not in counterparts
