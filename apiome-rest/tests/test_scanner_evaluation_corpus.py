"""CLX-4.3 (#4861) — differential / determinism / ops inventory for scanner evaluation corpus."""

from __future__ import annotations

from pathlib import Path

from app.scanner_evaluation_corpus import (
    CORPUS_SOFT_BUDGET_SECONDS,
    corpus_root,
    finding_fingerprint,
    load_fixture,
    load_manifest,
    run_corpus,
    run_fixture,
)

ROOT = corpus_root()


def test_manifest_lists_fixtures_and_ops_inventory() -> None:
    manifest = load_manifest()
    assert manifest["corpus_version"] == "1"
    assert manifest["fixtures"]
    assert manifest["ops_failure_inventory"]
    for entry in manifest["ops_failure_inventory"]:
        path = (ROOT / entry["path"]).resolve()
        assert path.is_file(), f"ops inventory path missing: {path}"


def test_multi_format_pointers_exist() -> None:
    data = load_fixture("catalog/multi-format-index")
    assert data["kind"] == "catalog_pointer_index"
    for pointer in data["pointers"]:
        path = (ROOT / "catalog" / pointer["path"]).resolve()
        assert path.is_file(), f"multi-format pointer missing: {path}"


def test_differential_expected_blocking_rules() -> None:
    """Scanner updates must keep blocking goldens green (release gate)."""
    manifest = load_manifest()
    for entry in manifest["fixtures"]:
        fixture_id = entry["id"]
        data = load_fixture(fixture_id)
        blocking, findings = run_fixture(data)
        expected = set(entry.get("expected_blocking_rule_ids") or [])
        assert blocking == expected, (
            f"{fixture_id}: blocking rules {sorted(blocking)} != expected {sorted(expected)}"
        )
        for expected_any in entry.get("expected_rule_ids") or []:
            fired = {f.get("rule") for f in findings}
            assert expected_any in fired, (
                f"{fixture_id}: expected rule {expected_any!r} not in {sorted(fired)}"
            )


def test_corpus_determinism() -> None:
    manifest = load_manifest()
    for entry in manifest["fixtures"]:
        data = load_fixture(entry["id"])
        _b1, f1 = run_fixture(data)
        _b2, f2 = run_fixture(data)
        assert finding_fingerprint(f1) == finding_fingerprint(f2), entry["id"]


def test_full_corpus_within_soft_budget() -> None:
    _results, elapsed = run_corpus()
    assert elapsed < CORPUS_SOFT_BUDGET_SECONDS, (
        f"corpus pass took {elapsed:.2f}s (budget {CORPUS_SOFT_BUDGET_SECONDS}s)"
    )


def test_safe_surface_has_no_blocking_findings() -> None:
    blocking, _ = run_fixture(load_fixture("mcp/safe/clean-surface"))
    assert blocking == set()
