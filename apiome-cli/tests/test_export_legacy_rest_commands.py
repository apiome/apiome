"""``apiome export wadl`` and ``apiome export discovery`` — MFX-29.4 (#4176).

Both targets are registry targets (``wadl``, ``discovery``), so the verbs run through the generic export seam
(``export <format> <artifact>``, MFX-8.1) with no command code of their own. These tests pin that the spellings
resolve to them, and that the recorded registry fixtures carry each target's options, defaults and card.

The fixtures are recorded from the REST emitter registry (``apiome-rest/tests/test_legacy_rest_target_cards.py``
keeps ``export-targets-wadl.json`` and ``export-targets-discovery.json`` equal to the live descriptors).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apiome_cli.client.export_registry import resolve_export_target

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_WADL = json.loads((_FIXTURES / "export-targets-wadl.json").read_text())
_DISCOVERY = json.loads((_FIXTURES / "export-targets-discovery.json").read_text())
_BOTH = [*_WADL["targets"], *_DISCOVERY["targets"]]


@pytest.mark.parametrize(("spelling", "key"), [("wadl", "wadl"), ("WADL", "wadl"), ("discovery", "discovery"),
                                               ("Discovery", "discovery")])
def test_every_spelling_resolves_to_its_target(spelling: str, key: str) -> None:
    assert resolve_export_target(spelling, _BOTH) == key


def test_the_wadl_fixture_carries_the_layout_option() -> None:
    target = _WADL["targets"][0]
    assert target["descriptor"]["label"] == "WADL" and target["descriptor"]["multi_file"] is True
    assert set(target["options_schema"]["properties"]["layout"]["enum"]) == {"bundle", "single"}
    assert target["default_options"]["layout"] == "bundle"
    assert target["fidelity"]["tier"] == "lossy"


def test_the_discovery_fixture_carries_the_name_and_version_options() -> None:
    target = _DISCOVERY["targets"][0]
    assert target["descriptor"]["label"] == "Google API Discovery" and target["descriptor"]["multi_file"] is False
    assert {"name", "version", "indent"} <= set(target["options_schema"]["properties"])
    assert target["default_options"]["name"] is None and target["default_options"]["indent"] == 2
    assert target["fidelity"]["tier"] == "lossy"
