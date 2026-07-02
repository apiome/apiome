"""Golden ChangeReportModel fixtures + rendered snapshot checks (#2704, CR-06)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from app.change_report_render import placeholder_render_from_change_model
from app.openapi_change_report import build_change_report

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "change_report_golden"


def _min_openapi(**kwargs) -> dict:
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "API", "version": "1.0.0", "description": "d0"},
        "paths": {},
        "components": {"schemas": {}},
    }
    doc.update(kwargs)
    return doc


def _pair_additive() -> tuple[dict, dict]:
    base = _min_openapi()
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["Pet"] = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }
    return base, cand


def _pair_breaking_property() -> tuple[dict, dict]:
    base = _min_openapi()
    base["components"]["schemas"]["N"] = {"type": "string"}
    cand = copy.deepcopy(base)
    cand["components"]["schemas"]["N"] = {"type": "integer"}
    return base, cand


def _pair_doc_only() -> tuple[dict, dict]:
    base = _min_openapi()
    cand = copy.deepcopy(base)
    cand["info"]["description"] = "d1"
    return base, cand


def _normalize_footnote_version(text: str) -> str:
    """Footnote embeds package semver; normalize so golden files survive patch bumps."""
    return re.sub(
        r"(Generator:\s*\*\*)apiome-rest/[^*]+(\*\*)",
        r"\1apiome-rest/<version>\2",
        text,
    )


def _load_expected(name: str) -> dict:
    with open(_FIXTURE_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def _load_render_snapshot(name: str) -> str:
    return (_FIXTURE_DIR / f"{name}_render.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fixture_name", "pair_fn"),
    [
        ("diff_additive_expected", _pair_additive),
        ("diff_breaking_property_expected", _pair_breaking_property),
        ("diff_doc_only_expected", _pair_doc_only),
    ],
)
def test_golden_change_report_model_matches_fixture(fixture_name: str, pair_fn):
    """Regression: diff engine output is stable for canonical OpenAPI pairs."""
    base, cand = pair_fn()
    expected = _load_expected(fixture_name)
    actual = build_change_report(base, cand)
    assert actual == expected


@pytest.mark.parametrize(
    "scenario",
    [
        "diff_additive_expected",
        "diff_breaking_property_expected",
        "diff_doc_only_expected",
    ],
)
def test_golden_render_snapshot_matches(scenario: str):
    """Template render (bundled Mustache) is stable for each golden ChangeReportModel."""
    cm = _load_expected(scenario)
    expected_raw = _load_render_snapshot(scenario)
    h, b, fn = placeholder_render_from_change_model(cm)
    actual = f"---HEADER---\n{h}\n---BODY---\n{b}\n---FOOTNOTE---\n{fn}\n"
    expected = _normalize_footnote_version(expected_raw)
    got = _normalize_footnote_version(actual)
    assert got == expected
