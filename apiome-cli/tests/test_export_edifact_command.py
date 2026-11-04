"""``apiome export edifact`` — MFX-24.2 (#4146).

The UN/EDIFACT message guide is a registry target (``edifact-guide``), so the verb runs through the generic
export seam (``export <format> <artifact>``, MFX-8.1) with no command code of its own. These tests pin that the
spellings resolve to it, and that the recorded registry fixture carries the message picker (``message_type``,
``release``), the other defaults and the types-only badge.

The fixture is recorded from the REST emitter registry (``apiome-rest/tests/test_edifact_guide_target_card.py``
keeps ``export-targets-edifact-guide.json`` equal to the live descriptor, options schema and badge).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiome_cli.client.export_registry import resolve_export_target

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TARGETS = json.loads((_FIXTURES / "export-targets-edifact-guide.json").read_text())


@pytest.mark.parametrize("spelling", ["edifact", "EDIFACT", "edifact-guide", "edifactguide"])
def test_every_spelling_resolves_to_the_edifact_guide(spelling: str) -> None:
    assert resolve_export_target(spelling, _TARGETS["targets"]) == "edifact-guide"


def test_x12_still_names_the_x12_guide() -> None:
    x12 = json.loads((_FIXTURES / "export-targets-x12-guide.json").read_text())
    both = [*x12["targets"], *_TARGETS["targets"]]
    assert resolve_export_target("x12", both) == "x12-guide"
    assert resolve_export_target("edifact", both) == "edifact-guide"


def test_the_fixture_carries_the_message_picker_and_the_types_only_badge() -> None:
    target = _TARGETS["targets"][0]
    properties = target["options_schema"]["properties"]
    assert {"message_type", "release", "default_element_length", "max_code_length", "default_max_use"} <= set(
        properties)
    assert target["default_options"]["message_type"] is None
    assert target["default_options"]["default_element_length"] == 35
    assert target["descriptor"]["multi_file"] is True
    assert target["fidelity"]["tier"] == "types-only"
