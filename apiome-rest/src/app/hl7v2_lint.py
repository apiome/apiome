"""HL7 v2 lint pack — MFI-20.2 (#3986).

Native, deterministic quality rules for HL7 v2.x messages, layered on the canonical lint engine
(MFI-4.1 :mod:`app.lint_engine`) the way the Thrift pack (:mod:`app.thrift_lint`) is. The
:class:`Hl7V2RulePack` is registered under the ``hl7v2`` format key, so it runs with the always-on
common pack on every HL7 v2 artifact. The rules read only the canonical model — the ``MSH``
envelope :class:`~app.hl7v2_normalizer.Hl7V2Normalizer` records under ``extras`` — never the raw
message:

* **hl7v2.message-type-declared** (error) — ``MSH-9`` is empty: without a message type nothing
  says which structure the segments follow, and no receiver can route the message.
* **hl7v2.trigger-event-declared** (warning) — ``MSH-9`` names a message code but no trigger
  event (``ADT`` instead of ``ADT^A01``): the event decides the segment structure.
* **hl7v2.version-declared** (warning) — ``MSH-12`` is empty: the receiver cannot pick the
  segment and field definitions (2.3.1, 2.5.1, …) to validate against.
* **hl7v2.control-id-present** (warning) — ``MSH-10`` is empty: an acknowledgement (``MSA-2``)
  cannot refer back to the message, so duplicates and losses go unnoticed.
* **hl7v2.processing-id-declared** (info) — ``MSH-11`` is empty: production, training and
  debugging traffic (``P`` / ``T`` / ``D``) cannot be told apart.
* **hl7v2.standard-encoding-characters** (warning) — ``MSH-1`` / ``MSH-2`` are not the
  conventional ``|`` and ``^~\\&``: legal, but many interface engines assume the defaults.

The pack also publishes :data:`FHIR_RESOURCE_FOR_SEGMENT`, the segment → FHIR resource
counterparts the normalizer records on each item (``extras["hl7v2_fhir_counterparts"]``) as its
migrate-to-FHIR note: converting the item is the migration, as it is for RAML → OpenAPI, and the
table says where each segment lands.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack

__all__ = [
    "FHIR_RESOURCE_FOR_SEGMENT",
    "Hl7V2RulePack",
    "STANDARD_ENCODING_CHARACTERS",
    "STANDARD_FIELD_SEPARATOR",
    "fhir_counterparts",
]

#: The conventional ``MSH-1`` field separator.
STANDARD_FIELD_SEPARATOR = "|"

#: The conventional ``MSH-2`` encoding characters: component ``^``, repetition ``~``, escape
#: ``\``, subcomponent ``&``.
STANDARD_ENCODING_CHARACTERS = "^~\\&"

#: The FHIR resource each common HL7 v2 segment maps to when a message is migrated to FHIR —
#: the HL7 "v2-to-FHIR" implementation guide's segment maps, reduced to one resource per segment.
#: Segments with no counterpart (``EVN``, ``MSA``, ``ERR`` …) are not listed.
FHIR_RESOURCE_FOR_SEGMENT: Mapping[str, str] = {
    "MSH": "MessageHeader",
    "PID": "Patient",
    "PD1": "Patient",
    "NK1": "RelatedPerson",
    "PV1": "Encounter",
    "PV2": "Encounter",
    "AL1": "AllergyIntolerance",
    "DG1": "Condition",
    "PR1": "Procedure",
    "IN1": "Coverage",
    "GT1": "RelatedPerson",
    "ORC": "ServiceRequest",
    "OBR": "ServiceRequest",
    "OBX": "Observation",
    "NTE": "Annotation",
    "SPM": "Specimen",
    "RXA": "Immunization",
    "RXR": "Immunization",
    "RXE": "MedicationRequest",
    "RXO": "MedicationRequest",
    "RXD": "MedicationDispense",
    "SCH": "Appointment",
    "AIS": "Appointment",
    "AIL": "Location",
    "AIP": "Practitioner",
    "MRG": "Patient",
    "TXA": "DocumentReference",
    "FT1": "ChargeItem",
}


def fhir_counterparts(segment_ids: Iterable[str]) -> Dict[str, str]:
    """The FHIR resource counterpart of every segment in *segment_ids* that has one.

    Args:
        segment_ids: Segment ids as they appear in the message (``PID``, ``OBX`` …); order and
            repeats do not matter.

    Returns:
        ``{segment_id: fhir_resource}`` sorted by segment id, holding only the segments
        :data:`FHIR_RESOURCE_FOR_SEGMENT` knows.
    """
    present = {segment_id for segment_id in segment_ids if segment_id in FHIR_RESOURCE_FOR_SEGMENT}
    return {segment_id: FHIR_RESOURCE_FOR_SEGMENT[segment_id] for segment_id in sorted(present)}


def _envelope(api: CanonicalApi) -> Mapping[str, Any]:
    """The ``MSH`` envelope the normalizer recorded, or an empty mapping."""
    envelope = api.extras.get("hl7v2_envelope")
    return envelope if isinstance(envelope, Mapping) else {}


def _text(value: Optional[object]) -> str:
    """A string extra, stripped; anything else is the empty string."""
    return value.strip() if isinstance(value, str) else ""


def _check_message_type_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """``MSH-9`` must name the message type."""
    if not _text(api.extras.get("hl7v2_message_type")):
        yield (
            "MSH.9",
            "MSH-9 (message type) is empty; without it no receiver can tell which message "
            "structure the segments follow. Set it, e.g. 'ADT^A01'.",
        )


def _check_trigger_event_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """``MSH-9`` should carry a trigger event next to the message code."""
    message_type = _text(api.extras.get("hl7v2_message_type"))
    if not message_type:
        return
    parts = [part for part in message_type.split("^") if part]
    if len(parts) < 2:
        yield (
            "MSH.9",
            f"MSH-9 is '{message_type}' with no trigger event; the event (the 'A01' in "
            "'ADT^A01') decides the segment structure the message follows.",
        )


def _check_version_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """``MSH-12`` must name the HL7 version."""
    if not _text(api.extras.get("hl7v2_version")):
        yield (
            "MSH.12",
            "MSH-12 (version id) is empty; the receiver cannot pick the segment and field "
            "definitions to validate against. Set it, e.g. '2.5.1'.",
        )


def _check_control_id_present(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """``MSH-10`` must carry a message control id."""
    if not _text(api.extras.get("hl7v2_control_id")):
        yield (
            "MSH.10",
            "MSH-10 (message control id) is empty; an acknowledgement cannot refer back to this "
            "message (MSA-2), so duplicates and losses go unnoticed.",
        )


def _check_processing_id_declared(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """``MSH-11`` should say whether the message is production, training or debugging."""
    if not _text(_envelope(api).get("processing_id")):
        yield (
            "MSH.11",
            "MSH-11 (processing id) is empty; production, training and debugging traffic "
            "cannot be told apart. Set it to 'P', 'T' or 'D'.",
        )


def _check_standard_encoding_characters(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    """``MSH-1`` and ``MSH-2`` should be the conventional separators."""
    envelope = _envelope(api)
    separator = _text(envelope.get("field_separator"))
    encoding = _text(envelope.get("encoding_characters"))
    if separator and separator != STANDARD_FIELD_SEPARATOR:
        yield (
            "MSH.1",
            f"MSH-1 (field separator) is '{separator}' rather than the conventional "
            f"'{STANDARD_FIELD_SEPARATOR}'; many interface engines assume the default.",
        )
    if encoding and encoding != STANDARD_ENCODING_CHARACTERS:
        yield (
            "MSH.2",
            f"MSH-2 (encoding characters) is '{encoding}' rather than the conventional "
            f"'{STANDARD_ENCODING_CHARACTERS}'; many interface engines assume the default.",
        )


class Hl7V2RulePack(RulePack, register=True):
    """Native rules for HL7 v2 artifacts (see the module docstring)."""

    format = "hl7v2"
    pack_id = "hl7v2"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="hl7v2.message-type-declared",
            category="structure",
            severity="error",
            description="MSH-9 must name the message type.",
            check=_check_message_type_declared,
        ),
        LintRule(
            rule_id="hl7v2.trigger-event-declared",
            category="structure",
            severity="warning",
            description="MSH-9 should carry a trigger event next to the message code.",
            check=_check_trigger_event_declared,
        ),
        LintRule(
            rule_id="hl7v2.version-declared",
            category="structure",
            severity="warning",
            description="MSH-12 must name the HL7 version.",
            check=_check_version_declared,
        ),
        LintRule(
            rule_id="hl7v2.control-id-present",
            category="structure",
            severity="warning",
            description="MSH-10 must carry a message control id.",
            check=_check_control_id_present,
        ),
        LintRule(
            rule_id="hl7v2.processing-id-declared",
            category="structure",
            severity="info",
            description="MSH-11 should say whether the message is production, training or debugging.",
            check=_check_processing_id_declared,
        ),
        LintRule(
            rule_id="hl7v2.standard-encoding-characters",
            category="structure",
            severity="warning",
            description="MSH-1 and MSH-2 should be the conventional '|' and '^~\\&'.",
            check=_check_standard_encoding_characters,
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the HL7 v2 native rules in deterministic execution order."""
        return list(self._RULES)
