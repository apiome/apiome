"""Golden-style checks: ChangeReportModel JSON → Mustache render (#2701)."""

import json
from pathlib import Path

import pytest

from app.change_report_render import placeholder_render_from_change_model, validate_change_report_templates

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "change_report_golden" / "sample_change_model.json"


@pytest.fixture
def sample_cm() -> dict:
    with open(_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_golden_render_contains_expected_sections(sample_cm: dict):
    h, b, f = placeholder_render_from_change_model(sample_cm)
    assert "Pet" in b
    assert "OldThing" in b
    assert "Box" in b
    assert "retargeted" in b
    assert "Generator" in f
    assert "apiome-rest/" in f
    assert "#" in h
    assert "Summary" in b


def test_invalid_mustache_rejected():
    with pytest.raises(ValueError, match="headerTemplate"):
        validate_change_report_templates("{{#broken", "x", "y")
