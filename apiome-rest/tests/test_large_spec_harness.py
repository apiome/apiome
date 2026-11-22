"""Contract tests for the large-spec benchmark harness — COA-5.11 (#7087).

The measurements are opt-in and nightly (:mod:`tests.test_large_spec_benchmark`), but the
machinery around them runs on every PR: a tiny fixture goes through every stage, and the target,
warm-generation and baseline rules are checked on synthetic numbers.
"""

from __future__ import annotations

import json
from typing import Dict

import pytest
from large_spec_benchmark import (
    DEFAULT_TARGETS,
    LARGE_BUDGETS_PATH,
    STAGES,
    TARGET_STAGES,
    LargeSpecFixture,
    LargeSpecMeasurement,
    benchmark_large_spec,
    build_large_report,
    fixture_specs,
    measure_unbiased,
    target_misses,
    warm_generation,
)
from scale_benchmark import StageMeasurement, compare, load_budgets

TINY = LargeSpecFixture("tiny", "test fixture", classes=30, properties=6, description_bytes=40)


@pytest.fixture(scope="module")
def tiny_run() -> LargeSpecMeasurement:
    """One real pass of the tiny fixture through every stage."""
    return benchmark_large_spec(TINY)


def _measurement(wall: Dict[str, float], *, enforce: bool = True, renders: int = 0) -> LargeSpecMeasurement:
    stages = {name: StageMeasurement(name, wall.get(name, 1.0), 1024) for name in STAGES}
    return LargeSpecMeasurement(
        name="m", paradigm="rest", adapter_key="openapi", export_target="openapi-3.1", source_bytes=1,
        stages=stages, process_peak_rss_bytes=1, detail={"warm_renders": {"diff-large-warm": renders}},
        enforce_targets=enforce,
    )


def test_every_stage_runs_for_a_real_fixture(tiny_run):
    assert tuple(tiny_run.stages) == STAGES
    assert all(stage.wall_ms > 0 and stage.peak_bytes > 0 for stage in tiny_run.stages.values())


def test_warm_stages_never_generate_and_the_diffs_see_the_edits(tiny_run):
    assert not warm_generation([tiny_run])
    small, large = tiny_run.detail["diff_small_changes"], tiny_run.detail["diff_large_changes"]
    assert 0 < small < large
    assert tiny_run.detail["emitted_files"] >= 1


def test_the_stage_vocabulary_has_a_cold_and_a_warm_of_every_operation():
    for operation in ("schema", "diff-small", "diff-large", "compat-small", "compat-large", "export"):
        assert f"{operation}-cold" in STAGES and f"{operation}-warm" in STAGES
    assert set(TARGET_STAGES) <= set(STAGES)


def test_fixtures_are_named_uniquely_and_the_stress_one_is_exempt_from_targets():
    specs = fixture_specs()
    assert len({spec.name for spec in specs}) == len(specs)
    stress = next(spec for spec in specs if spec.name == "synthetic-50mb")
    assert not stress.enforce_targets
    assert not stress.export and "export-cold" not in stress.stages  # the intake limit refuses 50 MB
    assert all(spec.export for spec in specs if spec is not stress)
    assert all(spec.enforce_targets for spec in specs if spec is not stress)


def test_targets_flag_only_enforced_fixtures_over_the_limit():
    slow = {"diff-large-warm": 2500.0, "schema-warm": 50.0}
    misses = target_misses([_measurement(slow)], {})
    assert [(m.stage, m.target) for m in misses] == [("diff-large-warm", "warm_diff_ms")]
    assert "2500 ms" in misses[0].describe()
    assert not target_misses([_measurement(slow, enforce=False)], {})
    assert not target_misses([_measurement({"schema-warm": 199.0, "diff-small-warm": 1999.0})], {})


def test_budget_file_targets_override_the_defaults():
    assert not target_misses([_measurement({"diff-large-warm": 2500.0})], {"targets": {"warm_diff_ms": 3000}})
    assert target_misses([_measurement({"diff-large-warm": 900.0})], {"targets": {"warm_diff_ms": 800}})


def test_generation_on_a_warm_cache_is_reported():
    assert warm_generation([_measurement({}, renders=2)]) == ["m · diff-large-warm: 2 generator run(s) on a warm cache"]


def test_the_report_fails_on_a_missed_target_and_lists_it():
    report = build_large_report([_measurement({"schema-warm": 900.0})], {}, [], [], [])
    assert report["passed"] is False and report["target_misses"][0]["stage"] == "schema-warm"
    assert report["policy"]["targets"] == DEFAULT_TARGETS and report["totals"]["stages"] == len(STAGES)
    assert build_large_report([_measurement({})], {}, [], [], [])["passed"] is True


def test_measure_unbiased_prepares_before_each_pass_and_returns_the_timed_value():
    log = []
    value, stage = measure_unbiased("s", lambda: log.append("prepare"), lambda: log.append("call") or 7)
    assert value == 7
    assert log == ["prepare", "call", "prepare", "call"]
    assert stage.wall_ms >= 0 and stage.peak_bytes >= 0


def test_the_committed_baseline_covers_exactly_the_fixtures_and_stages():
    document = load_budgets(LARGE_BUDGETS_PATH)
    assert set(document["fixtures"]) == {spec.name for spec in fixture_specs()}
    for spec in fixture_specs():
        assert set(document["fixtures"][spec.name]["stages"]) == set(spec.stages), spec.name
    assert document["regression_margin"] >= 1.0 and document["memory_margin"] >= 1.0
    assert document["targets"] == DEFAULT_TARGETS


def test_a_regression_against_the_baseline_is_found(tiny_run):
    stages = {name: {"wall_ms": 1.0, "peak_bytes": 1} for name in STAGES}
    document = {
        "regression_margin": 1.5, "memory_margin": 1.5, "wall_floor_ms": 0, "peak_floor_bytes": 0,
        "fixtures": {"tiny": {"stages": stages}},
    }
    regressions, problems = compare([tiny_run], document)
    assert regressions and not problems
    assert json.dumps(regressions[0].as_dict())
