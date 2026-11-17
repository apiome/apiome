"""Golden maturity levels over the CLX-4.3 scanner-evaluation corpus — GVM-1.2 (#5855).

Every corpus fixture is run through its scanner (:func:`app.scanner_evaluation_corpus.run_fixture`)
and its findings judged by :func:`app.maturity_ladder.evaluate_ladder` under the default
Bronze / Silver / Gold template ladder (:func:`app.style_guide_ladder.default_ladder_template`),
in three scenarios:

* ``bare`` — no axis evaluation and no evidence: the findings alone;
* ``no_security`` — quality assessed at A and an approved review, but the security axis never
  assessed: no fixture may reach Gold, and Gold's blocker must say ``not_assessed``;
* ``assessed`` — every axis assessed at A (score 100) and an approved review.

The golden file pins each fixture's level per scenario. A scanner or template change that moves
a level shows up as a diff. Regenerate after an intended change with::

    APIOME_REGEN_MATURITY_GOLDEN=1 uv run pytest tests/test_maturity_ladder_corpus_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.axis_score import AXIS_KEYS
from app.maturity_ladder import evaluate_ladder
from app.scanner_evaluation_corpus import load_fixture, load_manifest, run_fixture
from app.style_guide_ladder import default_ladder_template

GOLDEN = Path(__file__).parent / "golden" / "maturity" / "default_ladder_levels.json"

ALL_AXES_A = [{"axis": key, "assessed": True, "grade": "A", "score": 100} for key in AXIS_KEYS]
QUALITY_ONLY = [{"axis": "quality", "assessed": True, "grade": "A", "score": 100}]

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "bare": {"axes": None, "evidence": {}},
    "no_security": {"axes": QUALITY_ONLY, "evidence": {"review_approved": True}},
    "assessed": {"axes": ALL_AXES_A, "evidence": {"review_approved": True}},
}


def _fixture_ids() -> List[str]:
    return [str(entry["id"]) for entry in load_manifest().get("fixtures") or []]


def _levels() -> Dict[str, Dict[str, Optional[str]]]:
    """Run every fixture and judge it in every scenario."""
    ladder = default_ladder_template()
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for fixture_id in _fixture_ids():
        _blocking, findings = run_fixture(load_fixture(fixture_id))
        out[fixture_id] = {
            name: evaluate_ladder(
                findings, scenario["axes"], {}, ladder, evidence=scenario["evidence"]
            )["level"]
            for name, scenario in SCENARIOS.items()
        }
    return out


@pytest.fixture(scope="module")
def levels() -> Dict[str, Dict[str, Optional[str]]]:
    return _levels()


def test_levels_match_the_golden(levels) -> None:
    if os.environ.get("APIOME_REGEN_MATURITY_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(levels, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert levels == expected


def test_the_golden_covers_every_corpus_fixture(levels) -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(expected) == sorted(_fixture_ids())


def test_without_axis_evidence_no_fixture_passes_bronze_by_quality(levels) -> None:
    # Silver requires the quality axis; with no axis evaluation it is never assessed.
    assert {row["bare"] for row in levels.values()} <= {None, "bronze"}


def test_an_unassessed_security_axis_never_reaches_gold() -> None:
    ladder = default_ladder_template()
    scenario = SCENARIOS["no_security"]
    for fixture_id in _fixture_ids():
        _blocking, findings = run_fixture(load_fixture(fixture_id))
        result = evaluate_ladder(
            findings, scenario["axes"], {}, ladder, evidence=scenario["evidence"]
        )
        assert result["level"] != "gold", fixture_id
        assert "security" in result["unassessedAxes"], fixture_id
        if result["nextLevel"] == "gold":
            security = [b for b in result["blockers"] if b.get("axis") == "security"]
            assert security and security[0]["reason"] == "not_assessed", fixture_id


def test_the_corpus_spans_more_than_one_level(levels) -> None:
    # A golden where every fixture lands on the same level would pin nothing useful.
    assert len({row["assessed"] for row in levels.values()}) > 1
