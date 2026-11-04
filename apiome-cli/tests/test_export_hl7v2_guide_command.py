"""``apiome export hl7guide`` — MFX-26.3 (#4159).

The HL7 v2 segment guide is a registry target (``hl7v2-guide``), so the verb runs through the generic export seam
(``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that the spellings
resolve to it, that ``hl7v2`` still names the HL7 v2 message target, and that the recorded registry fixture
carries the message picker (``message_type``, ``version``), the other defaults and the types-only badge.

The fixture is recorded from the REST emitter registry (``apiome-rest/tests/test_hl7v2_guide_target_card.py``
keeps ``export-targets-hl7v2-guide.json`` equal to the live descriptor, options schema and badge).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiome_cli.client.export_registry import resolve_export_target

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-hl7v2-guide.json").read_text())


@pytest.mark.parametrize("spelling", ["hl7guide", "HL7GUIDE", "hl7v2-guide", "hl7v2guide"])
def test_every_spelling_resolves_to_the_hl7v2_guide(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "hl7v2-guide"


def test_hl7v2_still_names_the_message_target() -> None:
    message = {"descriptor": {"key": "hl7v2", "format": "hl7v2", "label": "HL7 v2"}}
    both = [message, *_TARGETS["targets"]]
    assert resolve_export_target("hl7v2", both) == "hl7v2"
    assert resolve_export_target("hl7guide", both) == "hl7v2-guide"


def test_the_fixture_carries_the_message_picker_and_the_types_only_badge() -> None:
    target = _TARGETS["targets"][0]
    properties = target["options_schema"]["properties"]
    assert {"message_type", "version", "default_field_length", "max_code_length", "first_table_number"} <= set(
        properties)
    assert target["default_options"]["message_type"] is None
    assert target["default_options"]["default_field_length"] == 199
    assert target["descriptor"]["multi_file"] is True
    assert target["fidelity"]["tier"] == "types-only"
