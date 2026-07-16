"""CTG-1.4 classifier regression corpus (#4470 / #4467).

Loads every fixture under ``tests/fixtures/diff/<case>/`` and asserts the
classifier output matches the committed ``expected.json`` golden. Any change to
classification behavior requires an explicit golden-file update in the same PR.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.change_taxonomy import classify_openapi_changes, classify_raw_changes
from app.change_taxonomy_enum import RawChange

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures" / "diff"


def _case_dirs() -> List[Path]:
    if not FIXTURES_ROOT.is_dir():
        return []
    return sorted(p for p in FIXTURES_ROOT.iterdir() if p.is_dir() and (p / "expected.json").is_file())


def _load_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _normalize_change(change: Dict[str, Any]) -> Dict[str, Any]:
    """Keep golden comparison fields stable."""
    return {
        "rule_id": change["rule_id"],
        "severity": change["severity"],
        "pointer": change["pointer"],
        "unclassified": change["unclassified"],
        "change_kind": change["change_kind"],
        "before": change.get("before"),
        "after": change.get("after"),
    }


@pytest.mark.parametrize("case_dir", _case_dirs(), ids=lambda p: p.name)
def test_corpus_case(case_dir: Path) -> None:
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    mode = expected.get("meta", {}).get("mode", "openapi")

    if mode == "raw":
        raw_path = case_dir / "raw.json"
        assert raw_path.is_file(), f"{case_dir.name}: raw mode requires raw.json"
        raw_rows = json.loads(raw_path.read_text(encoding="utf-8"))
        raw_changes = [
            RawChange(
                kind=row["kind"],
                pointer=row["pointer"],
                before=row.get("before"),
                after=row.get("after"),
            )
            for row in raw_rows
        ]
        result = classify_raw_changes(raw_changes)
    else:
        base = _load_yaml(case_dir / "base.yaml")
        head = _load_yaml(case_dir / "head.yaml")
        result = classify_openapi_changes(base, head)

    actual_changes = [_normalize_change(c.model_dump()) for c in result.changes]
    expected_changes = [_normalize_change(c) for c in expected["changes"]]

    assert actual_changes == expected_changes, (
        f"{case_dir.name}: classified changes drifted from golden expected.json"
    )
    assert result.max_severity == expected["max_severity"]
    assert result.counts == expected["counts"]


def test_corpus_covers_every_default_rule() -> None:
    """Every default taxonomy rule (except the fail-safe id) appears in some golden."""
    from app.change_taxonomy_rules import RULE_REGISTRY, UNCLASSIFIED_RULE_ID

    seen: set[str] = set()
    for case_dir in _case_dirs():
        expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
        for change in expected["changes"]:
            seen.add(change["rule_id"])

    missing = sorted(set(RULE_REGISTRY.keys()) - seen)
    assert not missing, f"corpus missing fixtures for rules: {missing}"
    assert UNCLASSIFIED_RULE_ID in seen or any(
        c.get("unclassified")
        for d in _case_dirs()
        for c in json.loads((d / "expected.json").read_text())["changes"]
    )
