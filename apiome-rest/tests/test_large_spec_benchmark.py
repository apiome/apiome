"""Large-spec performance benchmark and gate — COA-5.11 (#7087).

Drives every fixture in :func:`large_spec_benchmark.fixture_specs` (GitHub-, Stripe- and
Azure-shaped revisions and a 50 MB synthetic one) through cold and warm schema, classified diff,
compatibility and export stages, and holds the numbers to the committed baseline
(``tests/scale/large_spec_budgets.json``) and to the absolute latency targets: a warm diff of two
large revisions under 2 s and a warm schema read under 200 ms.

**Opt-in.** It takes minutes and gigabytes, so it runs on a schedule
(``.github/workflows/apiome-rest-large-spec.yml``), not per PR::

    RUN_LARGE_SPEC_SUITE=1 pytest tests/test_large_spec_benchmark.py
    pytest tests/test_large_spec_benchmark.py --large-spec

**Refreshing the baseline** (also how the "before" baseline is recorded on ``main``)::

    RUN_LARGE_SPEC_SUITE=1 pytest tests/test_large_spec_benchmark.py --update-large-spec-budgets

The machinery — the fixture builder, the stage list, the target and baseline rules — is covered per
PR by :mod:`tests.test_large_spec_harness`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from large_spec_benchmark import (
    LARGE_BUDGETS_PATH,
    MAX_STAGE_PEAK_BYTES,
    MAX_STAGE_SECONDS,
    LargeSpecMeasurement,
    benchmark_large_spec,
    build_large_report,
    fixture_specs,
    large_report_path,
    target_misses,
    warm_generation,
)
from scale_benchmark import (
    budgets_from_measurements,
    ceiling_breaches,
    compare,
    describe_breach,
    describe_regression,
    load_budgets,
    save_budgets,
    write_report,
)


@pytest.fixture(scope="session")
def large_run(request) -> Dict[str, Any]:
    """Run every fixture once and return everything the tests assert on.

    ``--update-large-spec-budgets`` rewrites the baseline here, before any assertion, so a refresh
    always succeeds and lands as a reviewable diff. A refresh keeps the policy (margins, floors,
    targets) of the file it replaces; only the numbers move.
    """
    measurements: List[LargeSpecMeasurement] = [benchmark_large_spec(fixture) for fixture in fixture_specs()]

    updating = bool(request.config.getoption("--update-large-spec-budgets", default=False))
    if updating:
        previous = load_budgets(LARGE_BUDGETS_PATH)
        document = budgets_from_measurements(measurements, previous)
        if "targets" in previous:
            document["targets"] = previous["targets"]
        save_budgets(document, LARGE_BUDGETS_PATH)

    document = load_budgets(LARGE_BUDGETS_PATH)
    regressions, problems = compare(measurements, document)
    breaches = ceiling_breaches(measurements, max_seconds=MAX_STAGE_SECONDS, max_peak_bytes=MAX_STAGE_PEAK_BYTES)
    report = build_large_report(measurements, document, regressions, problems, breaches)
    return {
        "measurements": measurements,
        "budgets": document,
        "regressions": regressions,
        "problems": problems,
        "breaches": breaches,
        "report": report,
        "report_path": write_report(report, large_report_path()),
        "updating": updating,
    }


def test_every_stage_is_measured_for_every_fixture(large_run):
    """Each fixture produces a number for every stage, in report order."""
    specs = {spec.name: spec for spec in fixture_specs()}
    for measurement in large_run["measurements"]:
        assert tuple(measurement.stages) == specs[measurement.name].stages, measurement.name
        for name, stage in measurement.stages.items():
            assert stage.wall_ms > 0, f"{measurement.name} · {name}: no wall-clock"
            assert stage.peak_bytes > 0, f"{measurement.name} · {name}: no memory figure"


def test_the_stress_fixture_is_about_fifty_megabytes(large_run):
    """The synthetic fixture really is 50 MB, so its numbers mean what the issue asked for."""
    stress = next(m for m in large_run["measurements"] if m.name == "synthetic-50mb")
    assert 48 * 1024 * 1024 <= stress.source_bytes <= 56 * 1024 * 1024, stress.source_bytes


def test_a_warm_read_does_no_generation(large_run):
    """With the rendered document stored, schema, diff, compatibility and export never generate."""
    generated = warm_generation(large_run["measurements"])
    assert not generated, "warm stages ran the generator:\n  " + "\n  ".join(generated)


def test_the_latency_targets_hold(large_run):
    """A warm diff of two large revisions is under 2 s and a warm schema read under 200 ms."""
    misses = target_misses(large_run["measurements"], large_run["budgets"])
    assert not misses, "latency targets missed:\n  " + "\n  ".join(miss.describe() for miss in misses)


def test_no_stage_exceeds_its_committed_budget(large_run):
    """No stage is slower or hungrier than the baseline allows (skipped while refreshing it)."""
    if large_run["updating"]:
        pytest.skip("baseline refreshed from this run")
    regressions = large_run["regressions"]
    assert not regressions, "regressions against the baseline:\n  " + "\n  ".join(
        describe_regression(regression) for regression in regressions
    )


def test_budget_file_covers_exactly_the_measured_fixtures(large_run):
    """The baseline has an entry for every fixture and stage, and no stale ones."""
    assert not large_run["problems"], "\n".join(large_run["problems"])


def test_no_stage_exceeds_the_absolute_ceilings(large_run):
    """The baseline-independent backstop: nothing hangs or allocates without bound."""
    breaches = large_run["breaches"]
    assert not breaches, "\n  ".join(describe_breach(breach) for breach in breaches)


def test_the_report_is_written_and_states_the_verdict(large_run):
    """The report artifact parses, lists every fixture, and its verdict matches its findings."""
    payload = json.loads(large_run["report_path"].read_text(encoding="utf-8"))
    assert len(payload["fixtures"]) == len(large_run["measurements"])
    assert payload["policy"]["targets"]["warm_diff_ms"] > 0
    findings = (
        payload["regressions"] or payload["problems"] or payload["breaches"]
        or payload["target_misses"] or payload["warm_generation"]
    )
    assert payload["passed"] is (not findings)


def test_the_budget_file_is_the_one_committed_place(large_run):
    """The run compared against the committed file."""
    assert json.loads(LARGE_BUDGETS_PATH.read_text(encoding="utf-8")) == large_run["budgets"]
