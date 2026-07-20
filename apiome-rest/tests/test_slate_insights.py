"""Observability honesty, residency gaps, correlation, usage and budgets — UXE-3.4 (private-suite#2476).

Pure tests over :mod:`app.slate_insights`: no TestClient, no database, no clock. Every instant and
every date is a parameter, and :class:`TestPurity` asserts that it actually is one.

The suite is weighted toward the one claim §29.6 makes that its three predecessors do not. Those
surfaces guard against *doing* too much — purging too much cache, turning protection off, granting
reach. This one guards against *believing* too much, and the two failures it exists to prevent are
a modelled metric read as measured and a modelled cost read as a bill. So:

* **The honesty fields are structurally unfakeable.** ``TelemetryVerdict.observed``,
  ``MetricPoint.observed``, ``UsageRollup.metered``, ``UsageRollup.billable`` and
  ``BudgetAlert.delivery_state`` are asserted at every construction path this module has, and the
  module source is asserted to contain no assignment able to flip one. ``roll_up_usage`` is pinned
  as unbillable even when every contributing row is metered, because the rollup is arithmetic this
  process did and billing owns what may be charged.
* **A refusal has no acknowledgement path, and a warning is never a boundary crossing.** The
  asymmetry between :data:`app.slate_insights._HARD_REFUSALS` and
  :data:`app.slate_insights._WARNING_SENTENCES` is asserted in both directions, and every sentence
  is asserted to say what to do next rather than only what failed.
* **The closed vocabularies agree with V190.** The module docstring promises the duplication is
  covered by golden tests; :class:`TestMigrationGoldens` reads the migration and is that promise.
* **A residency promise is only as good as its stated gap, and a lane is only as strong as its
  weakest stage.** Five pinned stages plus one unrestricted stage is asserted to read as
  ``unrestricted``, because reading it as "mostly pinned" is the misreading
  :func:`app.slate_insights.residency_coverage` exists to prevent.
* **Nothing is clamped into looking complete.** :func:`app.slate_insights.plan_live_tail` refuses a
  rate above a ceiling rather than lowering it, because a clamped tail is a stream an operator
  believes is complete, and a route sampled away looks exactly like a route that was quiet.
"""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import get_args

import pytest

from app.slate_insights import (
    _BUDGET_NEAR_EXHAUSTED_RATIO,
    _HARD_REFUSALS,
    _LOG_RETENTION_FLOOR_DAYS,
    _MIN_FORECAST_HISTORY_DAYS,
    _MOSTLY_SUPPRESSED_RATIO,
    _PRIVACY_THRESHOLD_FLOOR,
    _REFUSAL_SENTENCES,
    _SPARSE_SAMPLE_RATE,
    _WARNING_SENTENCES,
    ANNOTATION_KINDS,
    BUDGET_PERIODS,
    DELIVERY_STATES,
    EVIDENCE_KEYS,
    LOG_LEVELS,
    LOG_SOURCES,
    METRIC_FAMILIES,
    METRIC_FAMILY_CATALOG,
    OTLP_PROTOCOLS,
    RESIDENCY_CLASS_CATALOG,
    RESIDENCY_CLASSES,
    RESIDENCY_STAGE_CATALOG,
    RESIDENCY_STAGES,
    SERVICE_CATALOG,
    SERVICES,
    SIGNAL_CLASSES,
    SPAN_ATTRIBUTE_KEYS,
    SYNTHETIC_OUTCOMES,
    BudgetAlert,
    BudgetEvaluation,
    CorrelationKey,
    InsightRefusal,
    InsightRefusalReason,
    InsightWarning,
    MetricPoint,
    SlateInsightRefusedError,
    TelemetryVerdict,
    UsageRollup,
    correlate_signals,
    evaluate_budget,
    forecast_service,
    normalize_budget,
    normalize_export,
    normalize_policy,
    normalize_residency_lane,
    normalize_tail_request,
    plan_live_tail,
    redact_evidence,
    residency_coverage,
    roll_up_usage,
    signals_digest,
    validate_budget,
    validate_export,
    validate_policy,
    validate_residency_lane,
    validate_synthetic_check,
)

NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)


# ─── Builders ─────────────────────────────────────────────────────────────────
#
# Each baseline is deliberately the boring, passing case, so any refusal or warning a test observes
# was caused by the override it made rather than by the fixture. The four policy-ish builders
# return *normalized* bodies because that is what the validators take.


def policy(**overrides):
    """A lane policy at the shipped defaults: retention above the floor, threshold above it too."""
    base = {
        "telemetry_enabled": True,
        "metric_retention_days": 90,
        "log_retention_days": 14,
        "trace_retention_days": 7,
        "default_sample_rate": 0.05,
        "max_tail_sample_rate": 0.01,
        "max_tail_events_per_sec": 100,
        "privacy_threshold": 10,
        "retention_waiver_reason": None,
        "edge_attached": False,
    }
    base.update(overrides)
    return normalize_policy(base)


def lane(**overrides):
    """One residency lane: confined to a named region, with the catalog's stated gap."""
    base = {
        "stage": "ingress",
        "residency_class": "in-region-only",
        "regions": ["eu-central"],
        "uncovered_sentence": "",
        "residency_waiver_reason": None,
        "enforced": False,
    }
    base.update(overrides)
    return normalize_residency_lane(base)


def all_six_lanes(**per_stage):
    """One lane per stage, so :func:`residency_coverage` has a complete set to summarize."""
    return [lane(stage=stage, **per_stage.get(stage, {})) for stage in RESIDENCY_STAGES]


def export(**overrides):
    """An HTTPS destination taking every signal class, authorized by a secret reference."""
    base = {
        "label": "Central collector",
        "endpoint": "https://otlp.example.com:4318",
        "protocol": "http/protobuf",
        "signals": ["metrics", "logs", "traces"],
        "header_secret_ref": "otlp-bearer",
        "enabled": True,
    }
    base.update(overrides)
    return normalize_export(base)


def budget(**overrides):
    """A positive monthly budget in USD with two thresholds."""
    base = {
        "label": "Monthly delivery",
        "service": "delivery",
        "period": "monthly",
        "amount": 1000.0,
        "currency": "USD",
        "alert_thresholds": [0.8, 1.0],
        "notify_channel_ref": "ops-channel",
        "enabled": True,
    }
    base.update(overrides)
    return normalize_budget(base)


def tail(**overrides):
    """A narrow tail request with a stated reason, inside both lane ceilings."""
    base = {
        "sample_rate": 0.001,
        "max_events_per_sec": 10,
        "redaction_allowlist": [],
        "filter_expression": None,
        "reason": "Investigating the 502s reported at 11:40.",
    }
    base.update(overrides)
    return normalize_tail_request(base)


def metric_row(**overrides):
    """One reportable metric row: keyed, windowed, above the privacy threshold, with a value."""
    base = {
        "id": "row-1",
        "environment_id": "env-1",
        "release_id": "rel-1",
        "region": "eu-central",
        "metric_family": "request",
        "metric_key": "latency-p95",
        "window_start": NOW,
        "window_end": LATER,
        "value": 120.0,
        "unit": "ms",
        "sample_count": 500,
        "suppressed": False,
    }
    base.update(overrides)
    return base


def usage_row(**overrides):
    """One modelled daily usage record for the delivery service."""
    base = {
        "quantity": 1000.0,
        "unit": "requests",
        "amount": 10.0,
        "currency": "USD",
        "included_quantity": 800.0,
        "overage_quantity": 200.0,
        "cache_savings_amount": None,
        "forecast_amount": None,
        "basis": "modelled",
    }
    base.update(overrides)
    return base


def metered_row(**overrides):
    """The same record, but with something behind it."""
    return usage_row(basis="metered", **overrides)


# Every hard refusal this module can raise, paired with a body that provokes it. The one omission
# is ``policy-version-conflict``, a store-level concurrency check with no pure trigger;
# :meth:`TestRefusalVocabulary.test_every_declared_reason_has_a_sentence` still covers it.


def _trigger_currency_mismatch():
    validate_budget(budget(currency="USD"), usage_currency="EUR")


def _trigger_residency_gap_unstated():
    validate_residency_lane(dict(lane(), uncovered_sentence="   "))


def _trigger_residency_violation():
    validate_residency_lane(lane(residency_class="unrestricted"))


def _trigger_residency_stage_missing():
    residency_coverage(all_six_lanes()[:-1])


def _trigger_retention_below_floor():
    validate_policy(policy(log_retention_days=1))


def _trigger_privacy_threshold_below_floor():
    validate_policy(policy(privacy_threshold=1))


def _trigger_tail_exceeds_ceiling():
    plan_live_tail(tail(sample_rate=0.9), policy())


def _trigger_tail_without_reason():
    plan_live_tail(tail(reason="   "), policy())


def _trigger_tail_redaction_removed():
    plan_live_tail(tail(redaction_allowlist=["cookie"]), policy())


def _trigger_export_header_inline():
    validate_export(export(), raw={"headers": {"authorization": "Bearer hunter2"}})


def _trigger_export_endpoint_insecure():
    validate_export(export(endpoint="http://otlp.example.com:4318"))


def _trigger_export_without_signals():
    validate_export(dict(export(), signals=[]))


def _trigger_budget_without_threshold():
    validate_budget(dict(budget(), alert_thresholds=[]))


def _trigger_budget_not_positive():
    validate_budget(budget(amount=0))


#: (reason, trigger) for every hard refusal reachable from a body.
REFUSAL_TRIGGERS = [
    ("currency-mismatch", _trigger_currency_mismatch),
    ("residency-gap-unstated", _trigger_residency_gap_unstated),
    ("residency-violation", _trigger_residency_violation),
    ("residency-stage-missing", _trigger_residency_stage_missing),
    ("retention-below-floor", _trigger_retention_below_floor),
    ("privacy-threshold-below-floor", _trigger_privacy_threshold_below_floor),
    ("tail-exceeds-ceiling", _trigger_tail_exceeds_ceiling),
    ("tail-without-reason", _trigger_tail_without_reason),
    ("tail-redaction-removed", _trigger_tail_redaction_removed),
    ("export-header-inline", _trigger_export_header_inline),
    ("export-endpoint-insecure", _trigger_export_endpoint_insecure),
    ("export-without-signals", _trigger_export_without_signals),
    ("budget-without-threshold", _trigger_budget_without_threshold),
    ("budget-not-positive", _trigger_budget_not_positive),
]

#: Refusals the schema owns rather than this module: the four honesty CHECKs in V190 have no Python
#: trigger because there is no code path here able to produce the state they forbid, which is the
#: point. They are covered by the vocabulary goldens and by :class:`TestHonestyIsUnfakeable`.
SCHEMA_OWNED_REFUSALS = {
    "observed-without-collector",
    "billable-without-meter",
    "savings-without-meter",
    "forecast-presented-as-actual",
    "policy-version-conflict",
}


# ─── The migration, read for the golden tests ─────────────────────────────────

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "apiome-db"
    / "scripts"
    / "V190__slate_insights_control_2476.sql"
)


def _migration_text() -> str:
    """The V190 source with its ``--`` commentary stripped.

    The prose in that migration quotes several of its own CHECKs in abbreviated form (``evidence -
    ARRAY[...]``), so a golden that searched the raw file would match the description of a
    constraint rather than the constraint.
    """
    assert MIGRATION_PATH.is_file(), f"V190 is missing at {MIGRATION_PATH}"
    return "\n".join(
        line
        for line in MIGRATION_PATH.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )


def sql_enum(column: str) -> tuple:
    """The members of the first ``<column> IN (...)`` CHECK in V190, in the order written."""
    match = re.search(rf"\b{re.escape(column)}\s+IN\s*\(([^)]*)\)", _migration_text(), re.S)
    assert match, f"V190 declares no CHECK ({column} IN (...))"
    return tuple(re.findall(r"'([^']*)'", match.group(1)))


def sql_array(prefix: str) -> tuple:
    """The members of the first ``<prefix> ARRAY[...]`` literal in V190, in the order written."""
    match = re.search(rf"{re.escape(prefix)}\s*ARRAY\[([^\]]*)\]", _migration_text(), re.S)
    assert match, f"V190 declares no {prefix} ARRAY[...]"
    return tuple(re.findall(r"'([^']*)'", match.group(1)))


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestHonestyIsUnfakeable:
    """The whole ticket: a modelled number read as measured, and a modelled cost read as a bill."""

    def test_a_correlated_point_is_never_marked_observed_because_nothing_is_in_the_request_path(
        self,
    ) -> None:
        verdict = correlate_signals("env-1", [metric_row()], privacy_threshold=10)
        assert verdict.points[0].observed is False
        assert verdict.points[0].basis == "modelled"

    def test_the_telemetry_verdict_is_neither_observed_nor_enforced_however_many_rows_arrive(
        self,
    ) -> None:
        verdict = correlate_signals(
            "env-1", [metric_row(id=f"row-{n}") for n in range(20)], privacy_threshold=1
        )
        assert verdict.observed is False
        assert verdict.enforced is False
        assert verdict.basis == "policy-modelled"

    def test_an_empty_row_set_still_produces_an_honest_verdict_rather_than_an_absent_one(
        self,
    ) -> None:
        verdict = correlate_signals("env-1", [])
        assert (verdict.observed, verdict.enforced, verdict.basis) == (
            False,
            False,
            "policy-modelled",
        )

    def test_a_row_claiming_it_was_observed_does_not_make_the_point_observed(self) -> None:
        """The honesty field is set by this module, never carried in from a mapping."""
        verdict = correlate_signals(
            "env-1", [metric_row(observed=True, basis="edge-observed")], privacy_threshold=1
        )
        assert verdict.points[0].observed is False
        assert verdict.points[0].basis == "modelled"

    def test_a_verdict_claiming_enforcement_cannot_be_produced_from_a_row_that_claims_it(
        self,
    ) -> None:
        verdict = correlate_signals("env-1", [metric_row(enforced=True, edge_attached=True)])
        assert verdict.enforced is False

    def test_modelled_usage_cannot_be_marked_billable_because_a_model_presented_as_a_charge_is_an_invented_invoice(  # noqa: E501
        self,
    ) -> None:
        assert roll_up_usage([usage_row()], service="delivery").billable is False

    def test_fully_metered_usage_is_still_not_billable_because_billing_owns_what_may_be_charged(
        self,
    ) -> None:
        rollup = roll_up_usage([metered_row(), metered_row()], service="delivery")
        assert rollup.metered is True
        assert rollup.basis == "metered"
        assert rollup.billable is False

    def test_an_empty_rollup_is_unmetered_rather_than_vacuously_metered(self) -> None:
        """``all()`` over nothing is True, and a rollup of no days measuring nothing must not be."""
        rollup = roll_up_usage([], service="delivery")
        assert rollup.metered is False
        assert rollup.billable is False
        assert rollup.basis == "modelled"

    def test_a_row_asserting_it_is_billable_does_not_make_the_rollup_billable(self) -> None:
        rollup = roll_up_usage([metered_row(billable=True)], service="delivery")
        assert rollup.billable is False

    def test_every_alert_this_module_produces_says_it_was_never_dispatched(self) -> None:
        evaluation = evaluate_budget(
            budget(),
            budget_id="bud-1",
            consumed_amount=1500.0,
            consumed_currency="USD",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        assert evaluation.alerts
        for alert in evaluation.alerts:
            assert alert.delivery_state == "not-dispatched"
            assert alert.basis == "modelled"

    def test_a_budget_evaluation_states_its_basis_as_modelled(self) -> None:
        evaluation = evaluate_budget(
            budget(),
            budget_id="bud-1",
            consumed_amount=10.0,
            consumed_currency="USD",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )
        assert evaluation.basis == "modelled"

    def test_a_planned_tail_is_requested_rather_than_attached_because_nothing_attaches(
        self,
    ) -> None:
        session = plan_live_tail(tail(), policy())
        assert session["stream_state"] == "requested"
        assert session["edge_attached"] is False
        assert session["events_delivered"] == 0

    def test_a_lane_policy_claiming_an_edge_does_not_let_a_tail_claim_delivery(self) -> None:
        session = plan_live_tail(tail(), policy(edge_attached=True))
        assert session["stream_state"] == "requested"
        assert session["edge_attached"] is False
        assert session["events_delivered"] == 0

    @pytest.mark.parametrize(
        "cls,field_name,expected",
        [
            (MetricPoint, "observed", False),
            (MetricPoint, "basis", "modelled"),
            (TelemetryVerdict, "observed", False),
            (TelemetryVerdict, "enforced", False),
            (TelemetryVerdict, "basis", "policy-modelled"),
            (UsageRollup, "metered", False),
            (UsageRollup, "billable", False),
            (UsageRollup, "basis", "modelled"),
            (BudgetAlert, "delivery_state", "not-dispatched"),
            (BudgetAlert, "basis", "modelled"),
            (BudgetEvaluation, "basis", "modelled"),
        ],
    )
    def test_the_honest_value_is_the_default_so_a_dropped_field_is_not_a_silent_claim(
        self, cls, field_name, expected
    ) -> None:
        defaults = {f.name: f.default for f in fields(cls)}
        assert defaults[field_name] == expected

    @pytest.mark.parametrize(
        "cls", [MetricPoint, TelemetryVerdict, UsageRollup, BudgetAlert, BudgetEvaluation, CorrelationKey]
    )
    def test_every_verdict_is_frozen_so_a_caller_cannot_edit_the_honesty_out_of_it(
        self, cls
    ) -> None:
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen is True

    def test_a_verdict_rejects_an_attempt_to_reassign_its_honesty_field(self) -> None:
        verdict = correlate_signals("env-1", [metric_row()])
        with pytest.raises(Exception):
            verdict.observed = True  # type: ignore[misc]

    def test_the_module_source_contains_no_assignment_able_to_flip_an_honesty_field(self) -> None:
        """The strongest claim here is a structural absence, so it is asserted structurally."""
        import app.slate_insights as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        for forbidden in (
            "observed=True",
            "enforced=True",
            "metered=True",
            "billable=True",
            'basis="edge-observed"',
            'delivery_state="delivered"',
            'stream_state="attached"',
            '"edge_attached": True',
        ):
            assert forbidden not in code, f"the module can set {forbidden}"


class TestRefusalVocabulary:
    """The codes are ours to test against; the sentences are the operator's only explanation."""

    def test_every_declared_reason_has_a_sentence(self) -> None:
        assert set(get_args(InsightRefusalReason)) == set(_REFUSAL_SENTENCES)

    def test_the_nineteen_refusals_are_exactly_the_declared_ones(self) -> None:
        assert len(_REFUSAL_SENTENCES) == 19
        assert set(_HARD_REFUSALS) == set(_REFUSAL_SENTENCES)

    def test_every_refusal_is_hard(self) -> None:
        """A future reason has to decide which side it is on rather than defaulting to one."""
        for reason in _REFUSAL_SENTENCES:
            assert reason in _HARD_REFUSALS

    def test_no_refusal_is_also_a_warning(self) -> None:
        assert not set(_REFUSAL_SENTENCES) & set(_WARNING_SENTENCES)

    @pytest.mark.parametrize("reason", sorted(_REFUSAL_SENTENCES))
    def test_sentences_say_what_to_do_rather_than_only_what_failed(self, reason) -> None:
        sentence = _REFUSAL_SENTENCES[reason]
        assert len(sentence) > 80, f"{reason} is too short to explain itself"
        assert len(sentence.split(".")) >= 3, f"{reason} is a single clause"

    @pytest.mark.parametrize("reason", sorted(_REFUSAL_SENTENCES))
    def test_a_refusal_sentence_is_prose_rather_than_a_restated_code(self, reason) -> None:
        assert reason not in _REFUSAL_SENTENCES[reason]
        assert _REFUSAL_SENTENCES[reason].strip() == _REFUSAL_SENTENCES[reason]

    def test_no_two_refusals_share_a_sentence(self) -> None:
        sentences = list(_REFUSAL_SENTENCES.values())
        assert len(set(sentences)) == len(sentences), "two refusals share boilerplate"

    def test_an_unknown_reason_still_produces_a_sentence(self) -> None:
        assert InsightRefusal.of("not-a-real-code").sentence.strip()

    def test_a_refusal_carries_the_code_it_was_built_from(self) -> None:
        assert InsightRefusal.of("currency-mismatch").reason == "currency-mismatch"

    def test_the_error_carries_both_the_code_and_the_sentence(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            _trigger_budget_not_positive()
        assert excinfo.value.code == "budget-not-positive"
        assert excinfo.value.refusal.sentence == _REFUSAL_SENTENCES["budget-not-positive"]
        assert str(excinfo.value) == _REFUSAL_SENTENCES["budget-not-positive"]

    def test_the_two_money_refusals_name_the_invented_invoice_rather_than_an_estimate(self) -> None:
        """The distinction is the whole reason ``billable`` exists as a column."""
        assert "invoice" in _REFUSAL_SENTENCES["billable-without-meter"]
        assert "discount" in _REFUSAL_SENTENCES["savings-without-meter"]

    def test_the_residency_gap_refusal_names_the_regulator_reading_the_unwritten_gap(self) -> None:
        assert "regulator" in _REFUSAL_SENTENCES["residency-gap-unstated"]


class TestWarningVocabulary:
    """The acknowledgeable half: a cost, a fidelity loss or a misreading, never a false claim."""

    def test_every_warning_has_a_sentence(self) -> None:
        for code, sentence in _WARNING_SENTENCES.items():
            assert sentence.strip(), code

    def test_the_eight_acknowledgeable_warnings_are_the_contract_ones(self) -> None:
        assert set(_WARNING_SENTENCES) == {
            "retention-shortened",
            "sampling-sparse",
            "residency-partially-unrestricted",
            "export-partial-signals",
            "budget-near-exhausted",
            "threshold-suppresses-most",
            "forecast-wide",
            "synthetic-single-region",
        }

    @pytest.mark.parametrize("code", sorted(_WARNING_SENTENCES))
    def test_warning_sentences_explain_the_consequence_rather_than_naming_the_setting(
        self, code
    ) -> None:
        sentence = _WARNING_SENTENCES[code]
        assert len(sentence) > 80, f"{code} is too short to explain itself"
        assert len(sentence.split(".")) >= 3, f"{code} is a single clause"

    def test_no_two_warnings_share_a_sentence(self) -> None:
        sentences = list(_WARNING_SENTENCES.values())
        assert len(set(sentences)) == len(sentences), "two warnings share boilerplate"

    @pytest.mark.parametrize("code", sorted(_WARNING_SENTENCES))
    def test_every_warning_code_is_acknowledgeable_rather_than_blocking(self, code) -> None:
        assert code not in _HARD_REFUSALS

    def test_an_unknown_warning_code_still_produces_a_sentence(self) -> None:
        assert InsightWarning.of("not-a-real-code").message.strip()

    def test_a_warning_carries_the_field_it_attaches_to(self) -> None:
        assert InsightWarning.of("sampling-sparse", "default_sample_rate").field == (
            "default_sample_rate"
        )

    def test_a_warning_without_a_field_is_allowed_because_some_are_about_the_whole_lane(
        self,
    ) -> None:
        assert InsightWarning.of("forecast-wide").field is None


class TestHardRefusalsFire:
    """Each refusal is reachable from a body, and raising is what stops a fall-through persist."""

    @pytest.mark.parametrize("reason,trigger", REFUSAL_TRIGGERS)
    def test_the_refusal_fires(self, reason, trigger) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            trigger()
        assert excinfo.value.code == reason

    @pytest.mark.parametrize("reason,trigger", REFUSAL_TRIGGERS)
    def test_the_refusal_raises_rather_than_returning_so_a_caller_cannot_ignore_it(
        self, reason, trigger
    ) -> None:
        try:
            result = trigger()
        except SlateInsightRefusedError:
            return
        pytest.fail(f"{reason} returned {result!r} instead of raising")

    def test_the_trigger_table_covers_every_refusal_except_the_schema_owned_ones(self) -> None:
        covered = {reason for reason, _ in REFUSAL_TRIGGERS}
        assert set(_REFUSAL_SENTENCES) - covered == SCHEMA_OWNED_REFUSALS


class TestEnumerations:
    """The vocabularies V190 CHECKs, pinned so a widened enum is a visible diff."""

    def test_metric_families_carry_cost_alongside_the_four_delivery_families(self) -> None:
        """Cost sharing the correlation columns is what lets a spend chart meet a latency chart."""
        assert METRIC_FAMILIES == ("request", "cache", "origin", "function", "security", "cost")

    def test_log_levels_are_ordered_by_urgency_so_a_threshold_filter_is_a_comparison(self) -> None:
        assert LOG_LEVELS == ("debug", "info", "warn", "error")

    def test_log_sources_share_the_metric_family_vocabulary_so_a_drill_down_lands_correctly(
        self,
    ) -> None:
        assert LOG_SOURCES == ("request", "cache", "origin", "function", "security", "build")
        assert set(LOG_SOURCES) - set(METRIC_FAMILIES) == {"build"}

    def test_the_six_residency_stages_are_ordered_along_the_request_path(self) -> None:
        assert RESIDENCY_STAGES == (
            "ingress",
            "tls-termination",
            "decrypted-processing",
            "cache-storage",
            "function-execution",
            "log-data-storage",
        )

    def test_residency_classes_are_ordered_most_restrictive_first(self) -> None:
        assert RESIDENCY_CLASSES == ("in-region-only", "region-pinned", "unrestricted")

    def test_residency_classes_are_spelled_as_the_edge_surface_spells_them(self) -> None:
        """An operator comparing this lane against a function policy must not have to translate."""
        from app.slate_functions import RESIDENCY_CLASSES as EDGE_CLASSES

        assert RESIDENCY_CLASSES == EDGE_CLASSES

    def test_the_five_billable_services_match_the_ones_the_roadmap_names(self) -> None:
        assert SERVICES == ("delivery", "build", "function", "log", "ai")

    def test_signal_classes_are_the_three_opentelemetry_ones(self) -> None:
        assert SIGNAL_CLASSES == ("metrics", "logs", "traces")

    def test_otlp_protocols_are_the_two_wire_formats(self) -> None:
        assert OTLP_PROTOCOLS == ("grpc", "http/protobuf")

    def test_budget_periods_are_the_three_billing_windows(self) -> None:
        assert BUDGET_PERIODS == ("daily", "weekly", "monthly")

    def test_delivery_states_are_ordered_from_least_to_most_claimed(self) -> None:
        assert DELIVERY_STATES == ("never-attempted", "pending", "failed", "delivered")
        assert DELIVERY_STATES[-1] == "delivered"

    def test_not_run_is_a_distinct_outcome_from_failed_because_they_page_different_people(
        self,
    ) -> None:
        assert SYNTHETIC_OUTCOMES == ("healthy", "degraded", "failed", "not-run")

    def test_annotation_kinds_cover_the_regression_and_its_recovery(self) -> None:
        assert ANNOTATION_KINDS == ("post-promotion-regression", "post-promotion-recovery")

    def test_no_evidence_key_can_hold_a_credential(self) -> None:
        joined = " ".join(EVIDENCE_KEYS).lower()
        for forbidden in ("cookie", "authorization", "token", "secret", "header"):
            assert forbidden not in joined

    def test_no_span_attribute_can_hold_a_credential(self) -> None:
        joined = " ".join(SPAN_ATTRIBUTE_KEYS).lower()
        for forbidden in ("cookie", "authorization", "token", "secret"):
            assert forbidden not in joined

    def test_the_span_allowlist_is_a_subset_of_the_evidence_allowlist_plus_route(self) -> None:
        """Two allowlists that drifted apart would make a trace richer than the log beside it."""
        assert set(SPAN_ATTRIBUTE_KEYS) - set(EVIDENCE_KEYS) == {"route"}

    @pytest.mark.parametrize(
        "vocabulary",
        [
            METRIC_FAMILIES,
            LOG_LEVELS,
            LOG_SOURCES,
            RESIDENCY_STAGES,
            RESIDENCY_CLASSES,
            SERVICES,
            SIGNAL_CLASSES,
            OTLP_PROTOCOLS,
            BUDGET_PERIODS,
            DELIVERY_STATES,
            SYNTHETIC_OUTCOMES,
            ANNOTATION_KINDS,
            EVIDENCE_KEYS,
            SPAN_ATTRIBUTE_KEYS,
        ],
    )
    def test_every_vocabulary_is_an_immutable_tuple_without_duplicates(self, vocabulary) -> None:
        assert isinstance(vocabulary, tuple)
        assert len(set(vocabulary)) == len(vocabulary)
        assert all(member and member.strip() == member for member in vocabulary)


class TestMigrationGoldens:
    """The module docstring promises the duplication cannot rot silently. This is that promise."""

    def test_the_migration_is_where_the_module_says_it_is(self) -> None:
        assert MIGRATION_PATH.is_file()
        assert "slate_insight_policies" in _migration_text()

    def test_metric_families_match_the_check(self) -> None:
        assert METRIC_FAMILIES == sql_enum("metric_family")

    def test_log_levels_match_the_check(self) -> None:
        assert LOG_LEVELS == sql_enum("level")

    def test_log_sources_match_the_check(self) -> None:
        assert LOG_SOURCES == sql_enum("source")

    def test_residency_stages_match_the_check_in_path_order(self) -> None:
        assert RESIDENCY_STAGES == sql_enum("stage")

    def test_residency_classes_match_the_check(self) -> None:
        assert RESIDENCY_CLASSES == sql_enum("residency_class")

    def test_services_match_the_check(self) -> None:
        assert SERVICES == sql_enum("service")

    def test_otlp_protocols_match_the_check(self) -> None:
        assert OTLP_PROTOCOLS == sql_enum("protocol")

    def test_budget_periods_match_the_check(self) -> None:
        assert BUDGET_PERIODS == sql_enum("period")

    def test_export_delivery_states_match_the_check(self) -> None:
        assert DELIVERY_STATES == sql_enum("last_delivery_state")

    def test_synthetic_outcomes_match_the_check(self) -> None:
        assert SYNTHETIC_OUTCOMES == sql_enum("outcome")

    def test_annotation_kinds_match_the_check(self) -> None:
        assert ANNOTATION_KINDS == sql_enum("annotation_kind")

    def test_the_evidence_allowlist_matches_the_jsonb_subtraction_check(self) -> None:
        assert EVIDENCE_KEYS == sql_array("evidence -")

    def test_the_span_attribute_allowlist_matches_its_subtraction_check(self) -> None:
        assert SPAN_ATTRIBUTE_KEYS == sql_array("attributes -")

    def test_signal_classes_match_the_containment_check(self) -> None:
        assert SIGNAL_CLASSES == sql_array("signals <@")

    def test_the_planned_tail_state_is_a_value_the_stream_state_check_permits(self) -> None:
        assert plan_live_tail(tail(), policy())["stream_state"] in sql_enum("stream_state")

    def test_the_alert_delivery_state_is_a_value_its_own_check_permits(self) -> None:
        """The budget-alert enum is deliberately not the export enum, and the difference matters."""
        alert_states = sql_enum("delivery_state")
        assert "not-dispatched" in alert_states
        assert alert_states != DELIVERY_STATES
        assert BudgetAlert.__dataclass_fields__["delivery_state"].default in alert_states

    def test_the_metric_basis_this_module_emits_is_a_value_the_check_permits(self) -> None:
        assert MetricPoint.__dataclass_fields__["basis"].default in sql_enum("basis")

    def test_the_retention_floor_matches_the_migrations_waiver_check(self) -> None:
        """V190 writes ``log_retention_days >= 7 OR retention_waiver_reason IS NOT NULL``."""
        assert _LOG_RETENTION_FLOOR_DAYS == 7
        assert "log_retention_days >= 7 OR retention_waiver_reason IS NOT NULL" in (
            _migration_text()
        )

    def test_the_column_defaults_this_module_normalizes_to_match_the_migration(self) -> None:
        text = _migration_text()
        defaults = normalize_policy({})
        assert "metric_retention_days    INTEGER NOT NULL DEFAULT 90" in text
        assert "log_retention_days       INTEGER NOT NULL DEFAULT 14" in text
        assert "privacy_threshold        INTEGER NOT NULL DEFAULT 10" in text
        assert defaults["metric_retention_days"] == 90
        assert defaults["log_retention_days"] == 14
        assert defaults["privacy_threshold"] == 10


class TestResidencyStageCatalog:
    """§29.6 asks the UX to state what a residency option does not cover, so it is required."""

    def test_the_catalog_covers_exactly_the_six_stages_in_path_order(self) -> None:
        assert tuple(entry.stage for entry in RESIDENCY_STAGE_CATALOG) == RESIDENCY_STAGES

    @pytest.mark.parametrize("entry", RESIDENCY_STAGE_CATALOG, ids=lambda e: e.stage)
    def test_every_stage_states_a_non_empty_gap_because_a_blank_gap_reads_as_no_gap(
        self, entry
    ) -> None:
        assert entry.default_uncovered.strip()
        assert len(entry.default_uncovered.strip()) > 60, f"{entry.stage} names no real gap"

    @pytest.mark.parametrize("entry", RESIDENCY_STAGE_CATALOG, ids=lambda e: e.stage)
    def test_every_stage_says_what_pinning_it_actually_guarantees(self, entry) -> None:
        assert entry.label.strip()
        assert len(entry.covers.strip()) > 30, f"{entry.stage} does not say what it covers"

    @pytest.mark.parametrize("entry", RESIDENCY_STAGE_CATALOG, ids=lambda e: e.stage)
    def test_a_stages_gap_is_not_a_restatement_of_what_it_covers(self, entry) -> None:
        assert entry.default_uncovered != entry.covers
        assert entry.default_uncovered != entry.label

    def test_no_two_stages_share_a_gap_sentence(self) -> None:
        gaps = [entry.default_uncovered for entry in RESIDENCY_STAGE_CATALOG]
        assert len(set(gaps)) == len(gaps), "two stages share a boilerplate gap"

    def test_the_log_storage_stage_names_the_exported_copy_as_its_gap(self) -> None:
        """An OTLP destination holds a copy outside the promise, which is the gap nobody writes."""
        entry = next(e for e in RESIDENCY_STAGE_CATALOG if e.stage == "log-data-storage")
        assert "export" in entry.default_uncovered.lower()

    def test_the_function_stage_names_egress_as_its_gap(self) -> None:
        entry = next(e for e in RESIDENCY_STAGE_CATALOG if e.stage == "function-execution")
        assert "egress" in entry.default_uncovered.lower()

    def test_the_residency_class_catalog_covers_exactly_the_three_classes(self) -> None:
        assert tuple(key for key, _ in RESIDENCY_CLASS_CATALOG) == RESIDENCY_CLASSES

    @pytest.mark.parametrize("key,sentence", RESIDENCY_CLASS_CATALOG, ids=lambda x: str(x)[:20])
    def test_every_residency_class_explains_itself_in_prose(self, key, sentence) -> None:
        assert len(sentence.strip()) > 80, f"{key} does not explain what it promises"

    def test_the_unrestricted_class_says_plainly_that_no_promise_is_made(self) -> None:
        sentence = dict(RESIDENCY_CLASS_CATALOG)["unrestricted"]
        assert "no residency promise" in sentence.lower()


class TestMetricFamilyCatalog:
    """A number that cannot say what it fails to capture is a number read as more than it is."""

    def test_the_catalog_covers_exactly_the_metric_families_in_order(self) -> None:
        assert tuple(entry.family for entry in METRIC_FAMILY_CATALOG) == METRIC_FAMILIES

    @pytest.mark.parametrize("entry", METRIC_FAMILY_CATALOG, ids=lambda e: e.family)
    def test_every_family_states_what_it_does_not_answer(self, entry) -> None:
        assert entry.does_not_answer.strip()
        assert len(entry.does_not_answer.strip()) > 60, f"{entry.family} claims to answer all"

    @pytest.mark.parametrize("entry", METRIC_FAMILY_CATALOG, ids=lambda e: e.family)
    def test_every_family_states_what_it_does_answer(self, entry) -> None:
        assert entry.label.strip()
        assert len(entry.answers.strip()) > 30

    @pytest.mark.parametrize("entry", METRIC_FAMILY_CATALOG, ids=lambda e: e.family)
    def test_a_familys_limit_is_not_a_restatement_of_its_answer(self, entry) -> None:
        assert entry.does_not_answer != entry.answers

    def test_no_two_families_share_prose(self) -> None:
        limits = [entry.does_not_answer for entry in METRIC_FAMILY_CATALOG]
        answers = [entry.answers for entry in METRIC_FAMILY_CATALOG]
        assert len(set(limits)) == len(limits)
        assert len(set(answers)) == len(answers)

    def test_the_cost_family_says_a_modelled_cost_is_not_the_invoice(self) -> None:
        entry = next(e for e in METRIC_FAMILY_CATALOG if e.family == "cost")
        assert "invoice" in entry.does_not_answer.lower()
        assert "metered" in entry.does_not_answer.lower()

    def test_the_cache_family_says_a_good_hit_ratio_does_not_mean_correct_hits(self) -> None:
        entry = next(e for e in METRIC_FAMILY_CATALOG if e.family == "cache")
        assert "hit ratio" in entry.does_not_answer.lower()

    def test_the_security_family_says_a_mitigation_count_omits_what_was_missed(self) -> None:
        entry = next(e for e in METRIC_FAMILY_CATALOG if e.family == "security")
        assert "missed" in entry.does_not_answer.lower()


class TestServiceCatalog:
    """A spike an operator cannot attribute is a spike nobody acts on."""

    def test_the_catalog_covers_exactly_the_services_in_order(self) -> None:
        assert tuple(entry.service for entry in SERVICE_CATALOG) == SERVICES

    @pytest.mark.parametrize("entry", SERVICE_CATALOG, ids=lambda e: e.service)
    def test_every_service_names_a_unit_and_what_drives_it(self, entry) -> None:
        assert entry.label.strip()
        assert entry.unit.strip()
        assert len(entry.driver.strip()) > 30, f"{entry.service} does not say what moves it"

    def test_no_two_services_share_a_driver_sentence(self) -> None:
        drivers = [entry.driver for entry in SERVICE_CATALOG]
        assert len(set(drivers)) == len(drivers)

    def test_no_service_is_counted_in_the_placeholder_unit(self) -> None:
        """``count`` is the column default and the sign that nobody chose a unit."""
        assert all(entry.unit != "count" for entry in SERVICE_CATALOG)


class TestValidatePolicy:
    """Retention and the privacy threshold are the two floors an incident later depends on."""

    def test_a_policy_at_the_shipped_defaults_passes_silently(self) -> None:
        assert validate_policy(policy()) == ()

    def test_retention_below_the_floor_with_no_reason_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_policy(policy(log_retention_days=3))
        assert excinfo.value.code == "retention-below-floor"

    def test_retention_below_the_floor_with_a_stated_reason_is_allowed(self) -> None:
        assert (
            validate_policy(
                policy(
                    log_retention_days=3,
                    retention_waiver_reason="Contractual erasure window; reviewed 2026-07-01.",
                )
            )
            == ()
        )

    @pytest.mark.parametrize("reason", ["", "   ", None])
    def test_a_blank_waiver_is_not_a_reason(self, reason) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_policy(policy(log_retention_days=3, retention_waiver_reason=reason))
        assert excinfo.value.code == "retention-below-floor"

    def test_retention_exactly_at_the_floor_needs_no_waiver(self) -> None:
        assert validate_policy(policy(log_retention_days=_LOG_RETENTION_FLOOR_DAYS)) == ()

    def test_the_retention_floor_is_the_weekend_an_incident_is_reviewed_across(self) -> None:
        assert _LOG_RETENTION_FLOOR_DAYS == 7

    def test_a_privacy_threshold_below_the_identifiability_floor_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_policy(policy(privacy_threshold=2))
        assert excinfo.value.code == "privacy-threshold-below-floor"

    def test_a_privacy_threshold_exactly_at_the_floor_is_allowed(self) -> None:
        assert validate_policy(policy(privacy_threshold=_PRIVACY_THRESHOLD_FLOOR)) == ()

    def test_the_column_default_sits_above_the_floor_so_the_default_is_not_the_minimum(
        self,
    ) -> None:
        assert normalize_policy({})["privacy_threshold"] > _PRIVACY_THRESHOLD_FLOOR

    def test_a_waiver_does_not_buy_a_lower_privacy_threshold(self) -> None:
        """Retention is a cost decision; identifiability is not, so there is no waiver for it."""
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_policy(
                policy(privacy_threshold=1, retention_waiver_reason="We really want it.")
            )
        assert excinfo.value.code == "privacy-threshold-below-floor"

    @pytest.mark.parametrize(
        "field_name", ["metric_retention_days", "log_retention_days", "trace_retention_days"]
    )
    def test_shortening_any_retention_window_warns(self, field_name) -> None:
        current = policy()
        proposed = policy(**{field_name: current[field_name] - 1})
        codes = [w.code for w in validate_policy(proposed, current=current)]
        assert "retention-shortened" in codes

    def test_lengthening_retention_does_not_warn(self) -> None:
        current = policy()
        assert validate_policy(policy(log_retention_days=30), current=current) == ()

    def test_leaving_retention_alone_does_not_warn(self) -> None:
        assert validate_policy(policy(), current=policy()) == ()

    def test_with_no_previous_policy_nothing_can_have_been_shortened(self) -> None:
        assert validate_policy(policy(log_retention_days=8), current=None) == ()

    def test_the_shortening_warning_names_the_field_it_is_about(self) -> None:
        current = policy()
        warnings = validate_policy(policy(trace_retention_days=1), current=current)
        assert [(w.code, w.field) for w in warnings] == [
            ("retention-shortened", "trace_retention_days")
        ]

    def test_a_sparse_sample_rate_warns(self) -> None:
        codes = [w.code for w in validate_policy(policy(default_sample_rate=0.0001))]
        assert "sampling-sparse" in codes

    def test_a_sample_rate_at_the_sparse_threshold_does_not_warn(self) -> None:
        assert validate_policy(policy(default_sample_rate=_SPARSE_SAMPLE_RATE)) == ()

    def test_sampling_nothing_at_all_is_not_reported_as_sparse_sampling(self) -> None:
        """Zero is a decision to collect no traces, not a rate that will silently omit a route."""
        assert validate_policy(policy(default_sample_rate=0.0)) == ()

    def test_an_ordinary_head_sample_rate_does_not_warn(self) -> None:
        assert validate_policy(policy(default_sample_rate=0.05)) == ()

    def test_a_threshold_suppressing_most_cells_warns_when_the_caller_measured_it(self) -> None:
        codes = [w.code for w in validate_policy(policy(), suppressed_ratio=0.9)]
        assert "threshold-suppresses-most" in codes

    def test_a_threshold_suppressing_few_cells_does_not_warn(self) -> None:
        assert validate_policy(policy(), suppressed_ratio=0.1) == ()

    def test_an_unmeasured_suppression_ratio_produces_no_warning_rather_than_a_guess(self) -> None:
        assert validate_policy(policy(), suppressed_ratio=None) == ()

    def test_warnings_accumulate_without_raising(self) -> None:
        current = policy()
        warnings = validate_policy(
            policy(log_retention_days=8, default_sample_rate=0.0001),
            current=current,
            suppressed_ratio=0.99,
        )
        assert {w.code for w in warnings} == {
            "retention-shortened",
            "sampling-sparse",
            "threshold-suppresses-most",
        }

    def test_a_refusal_pre_empts_the_warnings_because_the_write_is_not_happening(self) -> None:
        with pytest.raises(SlateInsightRefusedError):
            validate_policy(policy(log_retention_days=1, default_sample_rate=0.0001))


class TestValidateResidencyLane:
    """A claim with no stated gap is the same promise with the gap unwritten."""

    def test_a_confined_lane_with_a_region_and_a_gap_passes_silently(self) -> None:
        assert validate_residency_lane(lane()) == ()

    @pytest.mark.parametrize("sentence", ["", "   ", "\n"])
    def test_a_lane_stating_no_gap_is_refused(self, sentence) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_residency_lane(dict(lane(), uncovered_sentence=sentence))
        assert excinfo.value.code == "residency-gap-unstated"

    def test_an_unwritten_gap_falls_back_to_the_catalog_rather_than_to_silence(self) -> None:
        """This is why the refusal is only reachable by bypassing normalization."""
        normalized = lane(stage="cache-storage", uncovered_sentence="")
        expected = next(
            e.default_uncovered for e in RESIDENCY_STAGE_CATALOG if e.stage == "cache-storage"
        )
        assert normalized["uncovered_sentence"] == expected
        assert validate_residency_lane(normalized) == ()

    def test_an_operators_own_gap_sentence_survives_normalization(self) -> None:
        stated = "Does not cover the backup snapshots taken nightly to a second region."
        assert lane(uncovered_sentence=stated)["uncovered_sentence"] == stated

    def test_a_stage_outside_the_catalog_gets_no_default_and_is_therefore_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_residency_lane(lane(stage="invented-stage"))
        assert excinfo.value.code == "residency-gap-unstated"

    def test_an_unrestricted_lane_with_no_stated_reason_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_residency_lane(lane(residency_class="unrestricted"))
        assert excinfo.value.code == "residency-violation"

    @pytest.mark.parametrize("reason", ["", "   ", None])
    def test_a_blank_unrestricted_reason_is_not_a_reason(self, reason) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_residency_lane(
                lane(residency_class="unrestricted", residency_waiver_reason=reason)
            )
        assert excinfo.value.code == "residency-violation"

    def test_an_unrestricted_lane_with_a_stated_reason_is_allowed(self) -> None:
        assert (
            validate_residency_lane(
                lane(
                    residency_class="unrestricted",
                    regions=[],
                    residency_waiver_reason="APAC latency; reviewed 2026-07-01.",
                )
            )
            == ()
        )

    @pytest.mark.parametrize("residency_class", ["in-region-only", "region-pinned"])
    def test_a_confined_lane_naming_no_region_is_refused(self, residency_class) -> None:
        """The strictest-sounding setting that means nothing at all."""
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_residency_lane(lane(residency_class=residency_class, regions=[]))
        assert excinfo.value.code == "residency-violation"

    def test_an_unrestricted_lane_needs_no_region_because_it_promises_none(self) -> None:
        assert (
            validate_residency_lane(
                lane(
                    residency_class="unrestricted",
                    regions=[],
                    residency_waiver_reason="Capacity.",
                )
            )
            == ()
        )

    def test_the_gap_is_checked_before_the_class_so_the_first_thing_reported_is_the_missing_prose(
        self,
    ) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_residency_lane(
                dict(lane(residency_class="unrestricted"), uncovered_sentence="")
            )
        assert excinfo.value.code == "residency-gap-unstated"

    def test_blank_region_names_do_not_count_as_naming_a_region(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_residency_lane(lane(regions=["", "  ".strip()]))
        assert excinfo.value.code == "residency-violation"


class TestResidencyCoverage:
    """A lane makes only the weakest promise any of its stages makes."""

    def test_a_complete_set_of_pinned_stages_reads_as_the_strictest_class(self) -> None:
        effective, warnings = residency_coverage(all_six_lanes())
        assert effective == "in-region-only"
        assert warnings == ()

    def test_five_pinned_stages_plus_one_unrestricted_stage_reads_as_unrestricted(self) -> None:
        """The misreading this function exists to prevent: that is not a mostly-pinned lane."""
        lanes = all_six_lanes(
            **{
                "log-data-storage": {
                    "residency_class": "unrestricted",
                    "regions": [],
                    "residency_waiver_reason": "Collector is global.",
                }
            }
        )
        effective, warnings = residency_coverage(lanes)
        assert effective == "unrestricted"
        assert [w.code for w in warnings] == ["residency-partially-unrestricted"]

    def test_one_region_pinned_stage_among_five_strict_ones_weakens_the_whole_lane(self) -> None:
        lanes = all_six_lanes(**{"cache-storage": {"residency_class": "region-pinned"}})
        effective, warnings = residency_coverage(lanes)
        assert effective == "region-pinned"
        assert warnings == ()

    def test_a_uniformly_unrestricted_lane_does_not_warn_about_being_partial(self) -> None:
        lanes = [
            lane(
                stage=stage,
                residency_class="unrestricted",
                regions=[],
                residency_waiver_reason="Capacity.",
            )
            for stage in RESIDENCY_STAGES
        ]
        effective, warnings = residency_coverage(lanes)
        assert effective == "unrestricted"
        assert warnings == ()

    @pytest.mark.parametrize("missing", RESIDENCY_STAGES)
    def test_omitting_any_one_stage_is_refused(self, missing) -> None:
        lanes = [entry for entry in all_six_lanes() if entry["stage"] != missing]
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            residency_coverage(lanes)
        assert excinfo.value.code == "residency-stage-missing"

    def test_no_lanes_at_all_is_refused_rather_than_read_as_the_strictest_promise(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            residency_coverage([])
        assert excinfo.value.code == "residency-stage-missing"

    def test_an_extra_stage_outside_the_six_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            residency_coverage([*all_six_lanes(), lane(stage="invented-stage")])
        assert excinfo.value.code == "residency-stage-missing"

    def test_the_effective_class_does_not_depend_on_the_order_the_lanes_arrive_in(self) -> None:
        lanes = all_six_lanes(**{"ingress": {"residency_class": "unrestricted", "regions": []}})
        assert residency_coverage(lanes)[0] == residency_coverage(list(reversed(lanes)))[0]

    def test_the_partial_warning_names_the_field_the_surface_should_place_it_on(self) -> None:
        lanes = all_six_lanes(**{"ingress": {"residency_class": "region-pinned"}})
        lanes[-1] = lane(
            stage="log-data-storage",
            residency_class="unrestricted",
            regions=[],
            residency_waiver_reason="Global collector.",
        )
        _, warnings = residency_coverage(lanes)
        assert warnings[0].field == "residency_class"


class TestValidateExport:
    """An export is a copy leaving the lane, so the two ways it leaks are refusals."""

    def test_a_complete_https_destination_passes_silently(self) -> None:
        assert validate_export(export()) == ()

    def test_an_inline_header_map_is_refused_rather_than_silently_dropped(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_export(export(), raw={"headers": {"authorization": "Bearer hunter2"}})
        assert excinfo.value.code == "export-header-inline"

    def test_an_inline_single_header_value_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_export(export(), raw={"header_value": "Bearer hunter2"})
        assert excinfo.value.code == "export-header-inline"

    def test_a_raw_body_naming_only_a_secret_reference_is_allowed(self) -> None:
        assert validate_export(export(), raw={"header_secret_ref": "otlp-bearer"}) == ()

    def test_without_the_raw_body_the_header_check_cannot_run_and_does_not_pretend_to(self) -> None:
        assert validate_export(export(), raw=None) == ()

    def test_a_normalized_export_has_no_key_capable_of_holding_a_header_value(self) -> None:
        """The strongest claim this module makes about export credentials is a structural absence."""
        normalized = normalize_export(
            {
                "label": "x",
                "endpoint": "https://otlp.example.com",
                "headers": {"authorization": "Bearer hunter2"},
                "header_value": "Bearer hunter2",
                "authorization": "Bearer hunter2",
            }
        )
        assert "hunter2" not in repr(normalized)
        assert set(normalized) == {
            "label",
            "endpoint",
            "protocol",
            "signals",
            "header_secret_ref",
            "enabled",
        }

    @pytest.mark.parametrize(
        "endpoint",
        ["http://otlp.example.com", "HTTP://otlp.example.com", "  http://otlp.example.com  "],
    )
    def test_a_plaintext_endpoint_is_refused_however_it_is_written(self, endpoint) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_export(export(endpoint=endpoint))
        assert excinfo.value.code == "export-endpoint-insecure"

    def test_an_https_endpoint_is_allowed(self) -> None:
        assert validate_export(export(endpoint="https://otlp.example.com:4317")) == ()

    def test_an_endpoint_merely_containing_the_plaintext_scheme_is_not_refused(self) -> None:
        assert validate_export(export(endpoint="https://http.example.com/v1")) == ()

    def test_a_destination_receiving_no_signals_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_export(dict(export(), signals=[]))
        assert excinfo.value.code == "export-without-signals"

    def test_normalization_never_produces_the_silent_destination_the_refusal_guards_against(
        self,
    ) -> None:
        assert normalize_export({})["signals"] == ["metrics", "traces"]

    @pytest.mark.parametrize(
        "signals", [["metrics"], ["logs"], ["traces"], ["metrics", "traces"], ["logs", "traces"]]
    )
    def test_a_partial_signal_set_warns_rather_than_refusing(self, signals) -> None:
        warnings = validate_export(export(signals=signals))
        assert [w.code for w in warnings] == ["export-partial-signals"]

    def test_the_full_signal_set_does_not_warn(self) -> None:
        assert validate_export(export(signals=list(SIGNAL_CLASSES))) == ()

    def test_an_unknown_signal_class_is_dropped_rather_than_stored(self) -> None:
        assert normalize_export({"signals": ["metrics", "profiles"]})["signals"] == ["metrics"]

    def test_the_partial_warning_names_the_signals_field(self) -> None:
        assert validate_export(export(signals=["logs"]))[0].field == "signals"

    def test_the_header_refusal_pre_empts_the_endpoint_one_because_the_token_is_already_pasted(
        self,
    ) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_export(
                export(endpoint="http://otlp.example.com"), raw={"headers": {"a": "b"}}
            )
        assert excinfo.value.code == "export-header-inline"


class TestPlanLiveTail:
    """A tail is reader traffic on a screen, so it refuses rather than quietly narrowing."""

    def test_a_narrow_tail_with_a_stated_reason_is_planned(self) -> None:
        session = plan_live_tail(tail(), policy())
        assert session["reason"] == "Investigating the 502s reported at 11:40."
        assert session["sample_rate"] == 0.001
        assert session["max_events_per_sec"] == 10

    @pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
    def test_a_tail_with_no_stated_reason_is_refused(self, reason) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            plan_live_tail(tail(reason=reason), policy())
        assert excinfo.value.code == "tail-without-reason"

    def test_a_sample_rate_above_the_lane_ceiling_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            plan_live_tail(tail(sample_rate=0.5), policy(max_tail_sample_rate=0.01))
        assert excinfo.value.code == "tail-exceeds-ceiling"

    def test_an_event_rate_above_the_lane_ceiling_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            plan_live_tail(tail(max_events_per_sec=5000), policy(max_tail_events_per_sec=100))
        assert excinfo.value.code == "tail-exceeds-ceiling"

    def test_a_rate_exactly_at_either_ceiling_is_allowed(self) -> None:
        session = plan_live_tail(
            tail(sample_rate=0.01, max_events_per_sec=100),
            policy(max_tail_sample_rate=0.01, max_tail_events_per_sec=100),
        )
        assert session["sample_rate"] == 0.01
        assert session["max_events_per_sec"] == 100

    def test_an_excessive_rate_is_refused_rather_than_clamped_to_the_ceiling(self) -> None:
        """A clamped tail is a stream an operator reads as complete, and it is not one."""
        lane_policy = policy(max_tail_sample_rate=0.01)
        with pytest.raises(SlateInsightRefusedError):
            plan_live_tail(tail(sample_rate=0.5), lane_policy)
        # And nothing about the lane changed as a side effect of the attempt.
        assert lane_policy["max_tail_sample_rate"] == 0.01

    def test_a_tail_that_would_have_been_clamped_returns_no_session_at_all(self) -> None:
        try:
            session = plan_live_tail(tail(max_events_per_sec=10_000), policy())
        except SlateInsightRefusedError:
            return
        pytest.fail(f"a session was planned at {session['max_events_per_sec']}/s")

    @pytest.mark.parametrize("field", ["cookie", "authorization", "setCookie", "requestBody"])
    def test_an_allowlist_widened_past_the_redaction_set_is_refused(self, field) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            plan_live_tail(tail(redaction_allowlist=[*EVIDENCE_KEYS, field]), policy())
        assert excinfo.value.code == "tail-redaction-removed"

    def test_a_narrowed_allowlist_is_allowed_because_it_shows_less_rather_than_more(self) -> None:
        session = plan_live_tail(
            tail(redaction_allowlist=["method", "path", "statusCode"]), policy()
        )
        assert session["redaction_allowlist"] == ["method", "path", "statusCode"]

    def test_an_unstated_allowlist_defaults_to_the_full_redaction_set_rather_than_to_nothing(
        self,
    ) -> None:
        """An empty list reads as "redact nothing" to one reader and "allow nothing" to another."""
        allowlist = normalize_tail_request({})["redaction_allowlist"]
        assert set(allowlist) == set(EVIDENCE_KEYS)
        assert allowlist == sorted(EVIDENCE_KEYS), "the default must normalize to a stable order"

    def test_the_reason_check_runs_before_the_ceiling_one(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            plan_live_tail(tail(reason="", sample_rate=0.9), policy())
        assert excinfo.value.code == "tail-without-reason"

    def test_the_ceiling_check_runs_before_the_redaction_one(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            plan_live_tail(tail(sample_rate=0.9, redaction_allowlist=["cookie"]), policy())
        assert excinfo.value.code == "tail-exceeds-ceiling"

    def test_the_planned_session_carries_the_filter_the_auditor_will_ask_about(self) -> None:
        session = plan_live_tail(tail(filter_expression="status >= 500"), policy())
        assert session["filter_expression"] == "status >= 500"

    def test_the_session_records_exactly_the_fields_the_store_persists(self) -> None:
        assert set(plan_live_tail(tail(), policy())) == {
            "sample_rate",
            "max_events_per_sec",
            "redaction_allowlist",
            "filter_expression",
            "reason",
            "stream_state",
            "events_delivered",
            "edge_attached",
        }


class TestValidateBudget:
    """Money reconciles or it is not money."""

    def test_a_positive_budget_with_thresholds_passes_silently(self) -> None:
        assert validate_budget(budget()) == ()

    @pytest.mark.parametrize("amount", [0, 0.0, -1, -0.01])
    def test_a_non_positive_budget_is_refused(self, amount) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_budget(budget(amount=amount))
        assert excinfo.value.code == "budget-not-positive"

    def test_a_budget_with_no_thresholds_is_refused(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_budget(dict(budget(), alert_thresholds=[]))
        assert excinfo.value.code == "budget-without-threshold"

    def test_normalization_never_produces_the_silent_budget_the_refusal_guards_against(
        self,
    ) -> None:
        assert normalize_budget({})["alert_thresholds"] == [0.8, 1.0]

    def test_a_budget_in_another_currency_from_its_usage_is_refused_rather_than_converted(
        self,
    ) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_budget(budget(currency="USD"), usage_currency="EUR")
        assert excinfo.value.code == "currency-mismatch"

    def test_a_matching_currency_is_compared_case_insensitively(self) -> None:
        assert validate_budget(budget(currency="usd"), usage_currency="USD") == ()
        assert validate_budget(budget(currency="USD"), usage_currency="usd") == ()

    def test_an_unknown_usage_currency_does_not_refuse_because_nothing_disagrees_yet(self) -> None:
        assert validate_budget(budget(), usage_currency=None) == ()

    def test_a_budget_already_near_exhausted_warns_when_it_is_created(self) -> None:
        warnings = validate_budget(budget(amount=1000.0), consumed_amount=900.0)
        assert [w.code for w in warnings] == ["budget-near-exhausted"]

    def test_a_budget_with_headroom_does_not_warn(self) -> None:
        assert validate_budget(budget(amount=1000.0), consumed_amount=100.0) == ()

    def test_the_near_exhausted_ratio_is_stated_rather_than_measured(self) -> None:
        assert _BUDGET_NEAR_EXHAUSTED_RATIO == 0.8

    def test_consumption_exactly_at_the_ratio_warns(self) -> None:
        warnings = validate_budget(
            budget(amount=1000.0), consumed_amount=1000.0 * _BUDGET_NEAR_EXHAUSTED_RATIO
        )
        assert [w.code for w in warnings] == ["budget-near-exhausted"]

    def test_an_unknown_consumption_produces_no_warning_rather_than_a_guess(self) -> None:
        assert validate_budget(budget(), consumed_amount=None) == ()

    def test_the_amount_refusal_pre_empts_the_currency_one(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            validate_budget(budget(amount=0), usage_currency="EUR")
        assert excinfo.value.code == "budget-not-positive"

    def test_a_currency_is_stored_upper_case_so_two_spellings_cannot_disagree(self) -> None:
        assert normalize_budget({"currency": "eur"})["currency"] == "EUR"

    def test_a_service_outside_the_catalog_reads_as_an_all_services_budget(self) -> None:
        """NULL means every service, which is different from a budget covering none."""
        assert normalize_budget({"service": "invented"})["service"] is None
        assert normalize_budget({})["service"] is None

    def test_thresholds_are_deduplicated_and_sorted_so_one_crossing_fires_once(self) -> None:
        assert normalize_budget({"alert_thresholds": [1.0, 0.8, 0.8, 0.5]})[
            "alert_thresholds"
        ] == [0.5, 0.8, 1.0]

    def test_a_boolean_is_not_a_threshold(self) -> None:
        assert normalize_budget({"alert_thresholds": [True, 0.9]})["alert_thresholds"] == [0.9]


class TestEvaluateBudget:
    """A budget alert that re-fires on every scheduler pass is one somebody turns off."""

    def evaluate(self, **overrides):
        """Evaluate the baseline budget against overridable spend."""
        kwargs = {
            "budget_id": "bud-1",
            "consumed_amount": 0.0,
            "consumed_currency": "USD",
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
        }
        body = overrides.pop("budget", budget())
        kwargs.update(overrides)
        return evaluate_budget(body, **kwargs)

    def test_spend_below_every_threshold_fires_nothing(self) -> None:
        evaluation = self.evaluate(consumed_amount=100.0)
        assert evaluation.alerts == ()
        assert evaluation.consumed_ratio == pytest.approx(0.1)

    def test_spend_crossing_the_first_threshold_fires_only_it(self) -> None:
        evaluation = self.evaluate(consumed_amount=850.0)
        assert [alert.threshold for alert in evaluation.alerts] == [0.8]

    def test_spend_over_budget_fires_every_threshold_it_crossed_in_ascending_order(self) -> None:
        evaluation = self.evaluate(
            budget=budget(alert_thresholds=[1.0, 0.5, 0.8]), consumed_amount=1200.0
        )
        assert [alert.threshold for alert in evaluation.alerts] == [0.5, 0.8, 1.0]

    def test_spend_exactly_at_a_threshold_fires_it(self) -> None:
        evaluation = self.evaluate(consumed_amount=800.0)
        assert [alert.threshold for alert in evaluation.alerts] == [0.8]

    def test_a_threshold_already_fired_is_not_re_emitted_when_the_scheduler_retries(self) -> None:
        """Without this, every retry re-alerts and the surface teaches operators to ignore it."""
        first = self.evaluate(consumed_amount=1200.0)
        assert [alert.threshold for alert in first.alerts] == [0.8, 1.0]
        retry = self.evaluate(
            consumed_amount=1200.0, already_fired=[a.threshold for a in first.alerts]
        )
        assert retry.alerts == ()

    def test_a_retry_still_emits_a_threshold_crossed_since_the_last_pass(self) -> None:
        evaluation = self.evaluate(
            budget=budget(alert_thresholds=[0.5, 0.8, 1.0]),
            consumed_amount=1200.0,
            already_fired=[0.5, 0.8],
        )
        assert [alert.threshold for alert in evaluation.alerts] == [1.0]

    def test_an_already_fired_threshold_is_matched_at_the_stored_precision(self) -> None:
        """V190 stores thresholds as NUMERIC(4,3), so 0.8 read back must still suppress 0.800."""
        evaluation = self.evaluate(consumed_amount=850.0, already_fired=[0.8000004])
        assert evaluation.alerts == ()

    def test_the_budget_amount_is_captured_at_fire_time_so_a_later_edit_cannot_rewrite_history(
        self,
    ) -> None:
        body = budget(amount=1000.0)
        evaluation = self.evaluate(budget=body, consumed_amount=1200.0)
        body["amount"] = 5000.0
        assert all(alert.budget_amount == 1000.0 for alert in evaluation.alerts)

    def test_an_alert_shows_the_arithmetic_it_was_computed_from(self) -> None:
        evaluation = self.evaluate(consumed_amount=1200.0)
        alert = evaluation.alerts[0]
        assert alert.budget_id == "bud-1"
        assert alert.observed_amount == 1200.0
        assert alert.budget_amount == 1000.0
        assert alert.currency == "USD"
        assert (alert.period_start, alert.period_end) == (PERIOD_START, PERIOD_END)

    def test_spend_in_another_currency_is_refused_rather_than_converted(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            self.evaluate(consumed_amount=1200.0, consumed_currency="EUR")
        assert excinfo.value.code == "currency-mismatch"

    def test_a_currency_is_compared_case_insensitively(self) -> None:
        assert self.evaluate(consumed_amount=10.0, consumed_currency="usd").alerts == ()

    def test_the_consumed_ratio_is_spend_over_budget(self) -> None:
        assert self.evaluate(consumed_amount=250.0).consumed_ratio == pytest.approx(0.25)

    def test_a_budget_of_nothing_reports_no_ratio_rather_than_dividing_by_zero(self) -> None:
        evaluation = self.evaluate(budget=budget(amount=0.0), consumed_amount=100.0)
        assert evaluation.consumed_ratio == 0.0
        assert evaluation.alerts == ()

    def test_being_near_exhausted_without_crossing_a_threshold_warns_instead(self) -> None:
        evaluation = self.evaluate(
            budget=budget(alert_thresholds=[0.95]), consumed_amount=850.0
        )
        assert evaluation.alerts == ()
        assert [w.code for w in evaluation.warnings] == ["budget-near-exhausted"]

    def test_an_alert_replaces_the_warning_because_the_alert_says_it_louder(self) -> None:
        evaluation = self.evaluate(consumed_amount=850.0)
        assert evaluation.alerts
        assert evaluation.warnings == ()

    def test_the_evaluation_names_the_budget_it_evaluated(self) -> None:
        assert self.evaluate(budget_id="bud-9", consumed_amount=1.0).budget_id == "bud-9"

    def test_evaluating_twice_produces_the_same_alerts(self) -> None:
        first = self.evaluate(consumed_amount=1200.0)
        second = self.evaluate(consumed_amount=1200.0)
        assert first == second


class TestCorrelateSignals:
    """Correlation is a precondition: an unkeyed point is one a drill-down cannot land on."""

    def test_a_fully_keyed_row_is_emitted_with_its_correlation(self) -> None:
        verdict = correlate_signals("env-1", [metric_row()])
        assert len(verdict.points) == 1
        point = verdict.points[0]
        assert point.key == CorrelationKey(
            environment_id="env-1", release_id="rel-1", region="eu-central"
        )
        assert point.value == 120.0
        assert point.unit == "ms"
        assert verdict.dropped == ()

    def test_a_row_with_no_environment_is_dropped_and_reported(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(environment_id="")])
        assert verdict.points == ()
        assert len(verdict.dropped) == 1
        assert verdict.dropped[0][0] == "row-1"
        assert "no environment" in verdict.dropped[0][1]

    def test_a_row_belonging_to_another_environment_is_dropped_and_reported(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(environment_id="env-2")])
        assert verdict.points == ()
        assert verdict.dropped[0][1] == "belongs to another environment"

    def test_a_row_in_an_unknown_metric_family_is_dropped_and_reported(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(metric_family="vibes")])
        assert verdict.points == ()
        assert "unknown metric family" in verdict.dropped[0][1]

    def test_a_row_with_no_family_at_all_is_dropped(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(metric_family=None)])
        assert verdict.points == ()
        assert verdict.dropped

    @pytest.mark.parametrize(
        "overrides",
        [
            {"window_start": None},
            {"window_end": None},
            {"window_start": "2026-07-20T12:00:00Z"},
            {"window_end": 1_753_012_800},
        ],
    )
    def test_a_row_with_no_usable_window_is_dropped_and_reported(self, overrides) -> None:
        verdict = correlate_signals("env-1", [metric_row(**overrides)])
        assert verdict.points == ()
        assert "no aggregation window" in verdict.dropped[0][1]

    def test_a_row_whose_window_ends_before_it_starts_is_dropped_and_reported(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(window_start=LATER, window_end=NOW)])
        assert verdict.points == ()
        assert verdict.dropped[0][1] == "aggregation window ends before it starts"

    def test_a_zero_length_window_is_dropped_because_the_migration_forbids_it(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(window_end=NOW)])
        assert verdict.points == ()
        assert verdict.dropped

    def test_a_reported_row_carrying_no_value_is_dropped_and_reported(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(value=None)], privacy_threshold=1)
        assert verdict.points == ()
        assert verdict.dropped[0][1] == "reported point carries no value"

    def test_a_row_whose_value_is_not_a_number_is_dropped(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(value="fast")], privacy_threshold=1)
        assert verdict.points == ()
        assert verdict.dropped

    def test_a_dropped_row_names_itself_so_the_operator_can_find_it(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(id="row-42", environment_id="")])
        assert verdict.dropped[0][0] == "row-42"

    def test_an_unidentified_row_is_still_reported_rather_than_swallowed(self) -> None:
        row = metric_row(environment_id="")
        row.pop("id")
        verdict = correlate_signals("env-1", [row])
        assert verdict.dropped[0][0] == "<unidentified>"

    def test_a_drop_is_reported_rather_than_leaving_an_unexplained_hole_in_the_chart(self) -> None:
        rows = [metric_row(id="ok"), metric_row(id="bad", metric_family="vibes")]
        verdict = correlate_signals("env-1", rows)
        assert len(verdict.points) == 1
        assert len(verdict.dropped) == 1

    def test_a_point_below_the_privacy_threshold_is_suppressed_rather_than_dropped(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(sample_count=3)], privacy_threshold=10)
        assert len(verdict.points) == 1
        assert verdict.points[0].suppressed is True
        assert verdict.points[0].value is None
        assert verdict.suppressed_count == 1

    def test_a_suppressed_point_keeps_its_population_so_the_reason_is_visible(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(sample_count=3)], privacy_threshold=10)
        assert verdict.points[0].sample_count == 3

    def test_a_point_exactly_at_the_threshold_is_reported(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(sample_count=10)], privacy_threshold=10)
        assert verdict.points[0].suppressed is False
        assert verdict.points[0].value == 120.0
        assert verdict.suppressed_count == 0

    def test_a_row_already_marked_suppressed_stays_suppressed_above_the_threshold(self) -> None:
        verdict = correlate_signals(
            "env-1", [metric_row(suppressed=True, sample_count=500)], privacy_threshold=10
        )
        assert verdict.points[0].suppressed is True
        assert verdict.points[0].value is None

    def test_a_suppressed_point_with_no_value_is_emitted_rather_than_dropped(self) -> None:
        verdict = correlate_signals(
            "env-1", [metric_row(sample_count=1, value=None)], privacy_threshold=10
        )
        assert len(verdict.points) == 1
        assert verdict.dropped == ()

    def test_mostly_suppressed_data_warns_that_the_empty_chart_is_working_correctly(self) -> None:
        rows = [metric_row(id="a", sample_count=1), metric_row(id="b", sample_count=1)]
        verdict = correlate_signals("env-1", rows, privacy_threshold=10)
        assert [w.code for w in verdict.warnings] == ["threshold-suppresses-most"]

    def test_lightly_suppressed_data_does_not_warn(self) -> None:
        rows = [metric_row(id=str(n)) for n in range(10)] + [metric_row(id="q", sample_count=1)]
        verdict = correlate_signals("env-1", rows, privacy_threshold=10)
        assert verdict.warnings == ()

    def test_the_mostly_suppressed_ratio_is_stated_rather_than_measured(self) -> None:
        assert _MOSTLY_SUPPRESSED_RATIO == 0.5

    def test_no_points_at_all_produces_no_suppression_warning(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(environment_id="")])
        assert verdict.warnings == ()

    def test_points_are_sorted_deterministically_by_family_key_and_window(self) -> None:
        rows = [
            metric_row(id="c", metric_family="security", metric_key="mitigations"),
            metric_row(id="a", metric_family="cache", metric_key="hit-ratio"),
            metric_row(id="b", metric_family="cache", metric_key="bypass"),
        ]
        verdict = correlate_signals("env-1", rows)
        assert [(p.family, p.metric_key) for p in verdict.points] == [
            ("cache", "bypass"),
            ("cache", "hit-ratio"),
            ("security", "mitigations"),
        ]

    def test_the_same_series_is_ordered_by_window_start(self) -> None:
        rows = [
            metric_row(id="late", window_start=LATER, window_end=LATER + timedelta(hours=1)),
            metric_row(id="early"),
        ]
        verdict = correlate_signals("env-1", rows)
        assert [p.window_start for p in verdict.points] == [NOW, LATER]

    def test_the_sort_does_not_depend_on_the_order_the_rows_arrived_in(self) -> None:
        rows = [
            metric_row(id="c", metric_family="cost", metric_key="spend"),
            metric_row(id="a", metric_family="request", metric_key="errors"),
            metric_row(id="b", metric_family="origin", metric_key="latency"),
        ]
        forward = correlate_signals("env-1", rows).points
        backward = correlate_signals("env-1", list(reversed(rows))).points
        assert [(p.family, p.metric_key) for p in forward] == [
            (p.family, p.metric_key) for p in backward
        ]

    def test_a_point_spanning_releases_is_keyed_with_no_release_rather_than_being_dropped(
        self,
    ) -> None:
        verdict = correlate_signals("env-1", [metric_row(release_id="")])
        assert verdict.points[0].key.release_id is None
        assert verdict.dropped == ()

    def test_an_unstated_region_reads_as_auto_rather_than_as_a_missing_key(self) -> None:
        verdict = correlate_signals("env-1", [metric_row(region="")])
        assert verdict.points[0].key.region == "auto"

    def test_a_point_with_no_stated_unit_takes_the_column_default(self) -> None:
        row = metric_row()
        row.pop("unit")
        verdict = correlate_signals("env-1", [row])
        assert verdict.points[0].unit == "count"

    def test_the_verdict_names_the_lane_it_was_asked_about_rather_than_the_rows_lane(self) -> None:
        assert correlate_signals("env-1", []).environment_id == "env-1"

    def test_correlating_twice_produces_the_same_verdict(self) -> None:
        rows = [metric_row(id="a"), metric_row(id="b", metric_family="cost")]
        assert correlate_signals("env-1", rows) == correlate_signals("env-1", rows)

    def test_the_points_and_drops_are_tuples_so_a_caller_cannot_append_to_them(self) -> None:
        verdict = correlate_signals("env-1", [metric_row()])
        assert isinstance(verdict.points, tuple)
        assert isinstance(verdict.dropped, tuple)
        assert isinstance(verdict.warnings, tuple)


class TestRollUpUsage:
    """A total assembled from a mix of measured and modelled parts is a model wearing a costume."""

    def test_a_single_modelled_day_rolls_up_to_itself(self) -> None:
        rollup = roll_up_usage([usage_row()], service="delivery")
        assert rollup.quantity == 1000.0
        assert rollup.amount == 10.0
        assert rollup.days == 1

    def test_days_are_summed_across_the_period(self) -> None:
        rollup = roll_up_usage([usage_row(), usage_row(), usage_row()], service="delivery")
        assert rollup.amount == 30.0
        assert rollup.quantity == 3000.0
        assert rollup.days == 3

    def test_the_included_and_overage_quantities_are_summed_separately(self) -> None:
        rollup = roll_up_usage([usage_row(), usage_row()], service="delivery")
        assert rollup.included_quantity == 1600.0
        assert rollup.overage_quantity == 400.0

    def test_rows_disagreeing_about_currency_are_refused_rather_than_converted(self) -> None:
        with pytest.raises(SlateInsightRefusedError) as excinfo:
            roll_up_usage([usage_row(currency="USD"), usage_row(currency="EUR")], service="delivery")
        assert excinfo.value.code == "currency-mismatch"

    def test_rows_agreeing_on_a_non_default_currency_keep_it(self) -> None:
        rollup = roll_up_usage(
            [usage_row(currency="EUR"), usage_row(currency="eur")], service="delivery"
        )
        assert rollup.currency == "EUR"

    def test_a_forecast_is_never_summed_into_the_amount(self) -> None:
        """A projection added to things that happened produces a figure that is neither."""
        rollup = roll_up_usage(
            [usage_row(amount=10.0, forecast_amount=90.0)], service="delivery"
        )
        assert rollup.amount == 10.0
        assert rollup.forecast_amount == 90.0

    def test_forecasts_are_summed_only_with_each_other(self) -> None:
        rollup = roll_up_usage(
            [usage_row(forecast_amount=5.0), usage_row(forecast_amount=7.0)], service="delivery"
        )
        assert rollup.amount == 20.0
        assert rollup.forecast_amount == 12.0

    def test_rows_with_no_forecast_leave_the_field_unset_rather_than_zero(self) -> None:
        """Zero would be a projection of nothing; None is the absence of one."""
        assert roll_up_usage([usage_row()], service="delivery").forecast_amount is None

    def test_savings_survive_when_every_row_is_metered(self) -> None:
        rollup = roll_up_usage(
            [metered_row(cache_savings_amount=3.0), metered_row(cache_savings_amount=4.0)],
            service="delivery",
        )
        assert rollup.cache_savings_amount == 7.0

    def test_savings_are_dropped_when_only_some_rows_are_metered(self) -> None:
        """The mixed case is the one that would present a model as a measurement."""
        rollup = roll_up_usage(
            [metered_row(cache_savings_amount=3.0), usage_row(cache_savings_amount=4.0)],
            service="delivery",
        )
        assert rollup.cache_savings_amount is None
        assert rollup.metered is False

    def test_savings_are_dropped_when_no_row_is_metered(self) -> None:
        rollup = roll_up_usage([usage_row(cache_savings_amount=3.0)], service="delivery")
        assert rollup.cache_savings_amount is None

    def test_an_all_metered_rollup_with_no_savings_reported_leaves_the_field_unset(self) -> None:
        assert roll_up_usage([metered_row()], service="delivery").cache_savings_amount is None

    def test_a_metered_savings_figure_of_zero_is_a_measurement_and_is_kept(self) -> None:
        rollup = roll_up_usage([metered_row(cache_savings_amount=0.0)], service="delivery")
        assert rollup.cache_savings_amount == 0.0

    @pytest.mark.parametrize("service", SERVICES)
    def test_a_rollup_takes_its_services_catalog_unit_when_the_rows_state_none(
        self, service
    ) -> None:
        row = usage_row()
        row.pop("unit")
        rollup = roll_up_usage([row], service=service)
        expected = next(e.unit for e in SERVICE_CATALOG if e.service == service)
        assert rollup.unit == expected

    def test_a_unit_the_rows_state_is_kept_over_the_catalogs(self) -> None:
        rollup = roll_up_usage([usage_row(unit="bytes")], service="delivery")
        assert rollup.unit == "bytes"

    def test_an_empty_period_rolls_up_to_zero_rather_than_failing(self) -> None:
        rollup = roll_up_usage([], service="build")
        assert (rollup.quantity, rollup.amount, rollup.days) == (0.0, 0.0, 0)
        assert rollup.currency == "USD"

    def test_the_rollup_names_the_service_it_was_asked_about(self) -> None:
        assert roll_up_usage([], service="ai").service == "ai"

    def test_a_row_with_a_non_numeric_amount_contributes_nothing_rather_than_failing(self) -> None:
        rollup = roll_up_usage([usage_row(amount="ten")], service="delivery")
        assert rollup.amount == 0.0

    def test_rolling_up_twice_produces_the_same_rollup(self) -> None:
        rows = [usage_row(), metered_row()]
        assert roll_up_usage(rows, service="delivery") == roll_up_usage(rows, service="delivery")


class TestForecastService:
    """A trend fitted to five days is a confident-looking curve whose slope is mostly noise."""

    def test_the_projection_is_the_mean_per_day_times_the_days_remaining(self) -> None:
        rows = [usage_row(amount=amount) for amount in (10.0, 20.0, 30.0)]
        projection, _ = forecast_service(rows, days_remaining=10)
        assert projection == pytest.approx(200.0)

    def test_one_day_of_history_projects_that_day_forward(self) -> None:
        projection, _ = forecast_service([usage_row(amount=7.0)], days_remaining=5)
        assert projection == pytest.approx(35.0)

    def test_no_history_returns_no_projection_rather_than_zero(self) -> None:
        assert forecast_service([], days_remaining=10) == (None, ())

    def test_no_days_remaining_returns_no_projection(self) -> None:
        assert forecast_service([usage_row()], days_remaining=0) == (None, ())

    def test_a_negative_days_remaining_returns_no_projection(self) -> None:
        assert forecast_service([usage_row()], days_remaining=-3) == (None, ())

    def test_a_short_history_warns_that_the_projection_will_move(self) -> None:
        rows = [usage_row() for _ in range(3)]
        _, warnings = forecast_service(rows, days_remaining=10)
        assert [w.code for w in warnings] == ["forecast-wide"]

    def test_a_full_week_of_history_does_not_warn(self) -> None:
        rows = [usage_row() for _ in range(_MIN_FORECAST_HISTORY_DAYS)]
        assert forecast_service(rows, days_remaining=10)[1] == ()

    def test_the_history_floor_is_one_of_every_weekday(self) -> None:
        assert _MIN_FORECAST_HISTORY_DAYS == 7

    def test_the_wide_warning_names_the_forecast_field(self) -> None:
        _, warnings = forecast_service([usage_row()], days_remaining=10)
        assert warnings[0].field == "forecast_amount"

    def test_a_short_history_still_returns_the_projection_alongside_the_warning(self) -> None:
        projection, warnings = forecast_service([usage_row(amount=4.0)], days_remaining=3)
        assert projection == pytest.approx(12.0)
        assert warnings

    def test_a_history_of_zero_spend_projects_zero_rather_than_nothing(self) -> None:
        """Zero spend is a measurement; it must not read as the absence of a forecast."""
        rows = [usage_row(amount=0.0) for _ in range(_MIN_FORECAST_HISTORY_DAYS)]
        projection, _ = forecast_service(rows, days_remaining=10)
        assert projection == 0.0

    def test_forecasting_twice_produces_the_same_projection(self) -> None:
        rows = [usage_row(amount=3.0), usage_row(amount=9.0)]
        assert forecast_service(rows, days_remaining=4) == forecast_service(rows, days_remaining=4)


class TestRedactEvidence:
    """An allowlist, because it is always the header nobody anticipated that reaches a screenshot."""

    def test_allowlisted_keys_survive(self) -> None:
        evidence = {"method": "GET", "path": "/docs", "statusCode": 502}
        assert redact_evidence(evidence) == evidence

    @pytest.mark.parametrize(
        "key", ["cookie", "Cookie", "authorization", "Authorization", "setCookie"]
    )
    def test_a_credential_bearing_key_is_dropped(self, key) -> None:
        assert redact_evidence({"method": "GET", key: "hunter2"}) == {"method": "GET"}

    def test_a_dropped_value_does_not_survive_in_the_result(self) -> None:
        redacted = redact_evidence({"cookie": "session=hunter2", "authorization": "Bearer x"})
        assert redacted == {}
        assert "hunter2" not in repr(redacted)

    @pytest.mark.parametrize("key", EVIDENCE_KEYS)
    def test_every_allowlisted_key_is_actually_permitted(self, key) -> None:
        assert redact_evidence({key: "value"}) == {key: "value"}

    @pytest.mark.parametrize(
        "key", ["requestBody", "responseBody", "headers", "email", "ipAddress", "apiKey"]
    )
    def test_a_key_outside_the_allowlist_is_dropped_whatever_it_is(self, key) -> None:
        assert redact_evidence({key: "x"}) == {}

    def test_a_narrower_allowlist_narrows_the_result(self) -> None:
        assert redact_evidence({"method": "GET", "path": "/x"}, allowlist=["method"]) == (
            {"method": "GET"}
        )

    def test_an_empty_allowlist_permits_nothing(self) -> None:
        assert redact_evidence({"method": "GET"}, allowlist=[]) == {}

    def test_redaction_does_not_mutate_the_evidence_it_was_given(self) -> None:
        evidence = {"method": "GET", "cookie": "session=1"}
        redact_evidence(evidence)
        assert set(evidence) == {"method", "cookie"}

    def test_redacting_an_already_redacted_mapping_changes_nothing(self) -> None:
        once = redact_evidence({"method": "GET", "cookie": "x"})
        assert redact_evidence(once) == once


class TestValidateSyntheticCheck:
    """A single-region probe reports one region's health, not the lane's."""

    def test_a_single_region_check_warns(self) -> None:
        warnings = validate_synthetic_check({"enabled": True, "regions": ["eu-central"]})
        assert [w.code for w in warnings] == ["synthetic-single-region"]

    def test_a_multi_region_check_does_not_warn(self) -> None:
        assert validate_synthetic_check({"enabled": True, "regions": ["eu-central", "us-east"]}) == ()

    def test_a_disabled_single_region_check_does_not_warn(self) -> None:
        """Nothing probes, so there is no health to misread yet."""
        assert validate_synthetic_check({"enabled": False, "regions": ["eu-central"]}) == ()

    def test_a_check_naming_no_region_does_not_warn_about_naming_one(self) -> None:
        assert validate_synthetic_check({"enabled": True, "regions": []}) == ()

    def test_the_warning_names_the_regions_field(self) -> None:
        warnings = validate_synthetic_check({"enabled": True, "regions": ["eu-central"]})
        assert warnings[0].field == "regions"


class TestNormalization:
    """Normalizing once is what makes two spellings of one configuration hash the same."""

    def test_an_unconfigured_policy_reads_as_the_shipped_column_defaults(self) -> None:
        resolved = normalize_policy({})
        assert resolved["telemetry_enabled"] is False
        assert resolved["edge_attached"] is False
        assert resolved["default_sample_rate"] == 0.05
        assert resolved["max_tail_sample_rate"] == 0.01
        assert resolved["max_tail_events_per_sec"] == 100

    def test_a_policy_that_never_configured_a_waiver_reads_as_having_none(self) -> None:
        assert normalize_policy({"retention_waiver_reason": "  "})["retention_waiver_reason"] is None

    @pytest.mark.parametrize(
        "normalizer,field",
        [
            (normalize_policy, "retention_waiver_reason"),
            (normalize_residency_lane, "residency_waiver_reason"),
            (normalize_export, "header_secret_ref"),
            (normalize_budget, "notify_channel_ref"),
            (normalize_tail_request, "filter_expression"),
        ],
    )
    @pytest.mark.parametrize("blank", ["", "   ", "\n\t", 17, None])
    def test_a_blank_optional_field_collapses_to_none_rather_than_surviving_as_truthy(
        self, normalizer, field, blank
    ) -> None:
        """Every one of these is a field a refusal tests for presence, and "   " is not presence."""
        assert normalizer({field: blank})[field] is None

    @pytest.mark.parametrize(
        "normalizer,field",
        [
            (normalize_policy, "retention_waiver_reason"),
            (normalize_residency_lane, "residency_waiver_reason"),
            (normalize_budget, "notify_channel_ref"),
        ],
    )
    def test_a_stated_optional_field_is_stripped_but_kept(self, normalizer, field) -> None:
        assert normalizer({field: "  a real answer  "})[field] == "a real answer"

    def test_a_non_numeric_retention_falls_back_rather_than_reading_as_zero(self) -> None:
        """Zero would be a retention of nothing, which is the opposite of an unset field."""
        assert normalize_policy({"log_retention_days": "forever"})["log_retention_days"] == 14

    def test_a_boolean_is_not_a_number(self) -> None:
        assert normalize_policy({"privacy_threshold": True})["privacy_threshold"] == 10

    def test_lane_regions_are_deduplicated_and_sorted(self) -> None:
        normalized = normalize_residency_lane(
            {"stage": "ingress", "regions": ["us-east", "eu-central", "us-east", ""]}
        )
        assert normalized["regions"] == ["eu-central", "us-east"]

    def test_a_lane_defaults_to_the_strictest_class_because_a_promise_opted_into_is_none(
        self,
    ) -> None:
        assert normalize_residency_lane({"stage": "ingress"})["residency_class"] == "in-region-only"
        assert RESIDENCY_CLASSES[0] == "in-region-only"

    def test_a_lane_is_not_enforced_by_default_because_nothing_enforces(self) -> None:
        assert normalize_residency_lane({"stage": "ingress"})["enforced"] is False

    def test_an_export_defaults_to_the_protocol_the_column_defaults_to(self) -> None:
        assert normalize_export({})["protocol"] == "http/protobuf"

    def test_an_export_is_disabled_by_default(self) -> None:
        assert normalize_export({})["enabled"] is False

    def test_export_signals_are_deduplicated_and_sorted(self) -> None:
        assert normalize_export({"signals": ["traces", "metrics", "traces"]})["signals"] == [
            "metrics",
            "traces",
        ]

    def test_a_budget_defaults_to_the_monthly_period_in_dollars(self) -> None:
        resolved = normalize_budget({})
        assert resolved["period"] == "monthly"
        assert resolved["currency"] == "USD"

    def test_a_budget_is_enabled_by_default_because_a_budget_nobody_armed_is_a_number(self) -> None:
        assert normalize_budget({})["enabled"] is True

    def test_a_tail_request_strips_the_reason_so_whitespace_is_not_a_justification(self) -> None:
        assert normalize_tail_request({"reason": "  why  "})["reason"] == "why"

    def test_a_tail_request_defaults_to_the_narrowest_rates(self) -> None:
        resolved = normalize_tail_request({})
        assert resolved["sample_rate"] == 0.001
        assert resolved["max_events_per_sec"] == 10

    def test_a_default_redaction_allowlist_survives_being_normalized_twice(self) -> None:
        """The stored session and the same session read back must digest identically."""
        once = normalize_tail_request({"reason": "why"})
        assert normalize_tail_request(once)["redaction_allowlist"] == once["redaction_allowlist"]

    @pytest.mark.parametrize(
        "normalizer,body",
        [
            (normalize_policy, {"log_retention_days": 30}),
            (normalize_policy, {"retention_waiver_reason": "  spaced  "}),
            (normalize_tail_request, {"reason": "  why  "}),
            (normalize_residency_lane, {"stage": "ingress", "regions": ["eu-central"]}),
            (normalize_export, {"label": "x", "endpoint": "https://otlp.example.com"}),
            (normalize_budget, {"label": "b", "amount": 10, "currency": "usd"}),
            (normalize_tail_request, {"reason": "why", "sample_rate": 0.002}),
        ],
    )
    def test_normalizing_is_idempotent(self, normalizer, body) -> None:
        once = normalizer(body)
        assert normalizer(once) == once

    @pytest.mark.parametrize(
        "normalizer,keys",
        [
            (normalize_policy, 10),
            (normalize_residency_lane, 6),
            (normalize_export, 6),
            (normalize_budget, 8),
            (normalize_tail_request, 5),
        ],
    )
    def test_normalization_never_carries_an_unknown_key_through(self, normalizer, keys) -> None:
        normalized = normalizer({"totally_unknown": "x", "observed": True, "billable": True})
        assert "totally_unknown" not in normalized
        assert "observed" not in normalized
        assert "billable" not in normalized
        assert len(normalized) == keys


class TestSignalsDigest:
    """A receipt, so "did anything change while I was reading this" is a string comparison."""

    def configuration(self):
        """One lane's full observability configuration."""
        return (policy(), all_six_lanes(), [export()], [budget()])

    def test_the_digest_matches_the_shape_the_column_constraints_expect(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", signals_digest(*self.configuration()))

    def test_the_digest_is_repeatable(self) -> None:
        config = self.configuration()
        assert signals_digest(*config) == signals_digest(*config)

    def test_the_digest_does_not_depend_on_the_order_the_lanes_arrived_in(self) -> None:
        policy_body, lanes, exports, budgets = self.configuration()
        assert signals_digest(policy_body, lanes, exports, budgets) == signals_digest(
            policy_body, list(reversed(lanes)), exports, budgets
        )

    def test_the_digest_does_not_depend_on_the_order_the_exports_arrived_in(self) -> None:
        policy_body, lanes, _, budgets = self.configuration()
        exports = [export(label="A"), export(label="B")]
        assert signals_digest(policy_body, lanes, exports, budgets) == signals_digest(
            policy_body, lanes, list(reversed(exports)), budgets
        )

    def test_the_digest_does_not_depend_on_the_order_the_budgets_arrived_in(self) -> None:
        policy_body, lanes, exports, _ = self.configuration()
        budgets = [budget(label="A"), budget(label="B")]
        assert signals_digest(policy_body, lanes, exports, budgets) == signals_digest(
            policy_body, lanes, exports, list(reversed(budgets))
        )

    def test_the_digest_does_not_depend_on_the_order_of_the_policys_own_keys(self) -> None:
        policy_body, lanes, exports, budgets = self.configuration()
        reordered = {key: policy_body[key] for key in reversed(list(policy_body))}
        assert signals_digest(policy_body, lanes, exports, budgets) == signals_digest(
            reordered, lanes, exports, budgets
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("log_retention_days", 30),
            ("privacy_threshold", 25),
            ("default_sample_rate", 0.5),
            ("max_tail_events_per_sec", 5),
            ("telemetry_enabled", False),
        ],
    )
    def test_the_digest_changes_when_a_policy_field_changes(self, field, value) -> None:
        policy_body, lanes, exports, budgets = self.configuration()
        assert signals_digest(policy_body, lanes, exports, budgets) != signals_digest(
            policy(**{field: value}), lanes, exports, budgets
        )

    def test_the_digest_changes_when_a_lanes_class_changes(self) -> None:
        policy_body, lanes, exports, budgets = self.configuration()
        loosened = all_six_lanes(
            **{
                "log-data-storage": {
                    "residency_class": "unrestricted",
                    "regions": [],
                    "residency_waiver_reason": "Global collector.",
                }
            }
        )
        assert signals_digest(policy_body, lanes, exports, budgets) != signals_digest(
            policy_body, loosened, exports, budgets
        )

    def test_the_digest_changes_when_an_export_endpoint_changes(self) -> None:
        policy_body, lanes, _, budgets = self.configuration()
        assert signals_digest(policy_body, lanes, [export()], budgets) != signals_digest(
            policy_body, lanes, [export(endpoint="https://other.example.com")], budgets
        )

    def test_the_digest_changes_when_a_budget_amount_changes(self) -> None:
        policy_body, lanes, exports, _ = self.configuration()
        assert signals_digest(policy_body, lanes, exports, [budget()]) != signals_digest(
            policy_body, lanes, exports, [budget(amount=2000.0)]
        )

    def test_an_empty_configuration_still_digests(self) -> None:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", signals_digest(normalize_policy({}), [], [], []))

    def test_two_different_configurations_do_not_collide(self) -> None:
        assert signals_digest(policy(), [], [], []) != signals_digest(
            policy(log_retention_days=99), [], [], []
        )


class TestPurity:
    """No database, no clock. Every instant and every date is a parameter."""

    def test_the_module_imports_no_database_session_and_reads_no_wall_clock(self) -> None:
        import app.slate_insights as module

        text = Path(module.__file__).read_text(encoding="utf-8")
        assert "sqlalchemy" not in text.lower()
        assert "from app.database" not in text
        assert "datetime.now(" not in text
        assert "datetime.utcnow(" not in text
        assert "date.today(" not in text

    def test_a_budget_evaluation_judges_the_period_it_was_handed(self) -> None:
        far_past = evaluate_budget(
            budget(),
            budget_id="bud-1",
            consumed_amount=1200.0,
            consumed_currency="USD",
            period_start=date(1999, 1, 1),
            period_end=date(1999, 1, 31),
        )
        assert far_past.alerts[0].period_start == date(1999, 1, 1)

    def test_correlation_places_points_in_the_window_it_was_given_rather_than_today(self) -> None:
        ancient = datetime(1999, 1, 1, tzinfo=timezone.utc)
        verdict = correlate_signals(
            "env-1",
            [metric_row(window_start=ancient, window_end=ancient + timedelta(hours=1))],
        )
        assert verdict.points[0].window_start == ancient

    def test_a_naive_window_is_accepted_without_raising(self) -> None:
        verdict = correlate_signals(
            "env-1",
            [metric_row(window_start=datetime(2026, 7, 20), window_end=datetime(2026, 7, 21))],
        )
        assert len(verdict.points) == 1

    def test_no_validator_mutates_the_body_it_was_given(self) -> None:
        body = policy()
        before = dict(body)
        validate_policy(body, current=policy(), suppressed_ratio=0.9)
        assert body == before

    def test_correlation_does_not_mutate_the_rows_it_was_given(self) -> None:
        rows = [metric_row(sample_count=1)]
        before = [dict(row) for row in rows]
        correlate_signals("env-1", rows, privacy_threshold=10)
        assert rows == before

    def test_rolling_up_does_not_mutate_the_rows_it_was_given(self) -> None:
        rows = [usage_row(), metered_row()]
        before = [dict(row) for row in rows]
        roll_up_usage(rows, service="delivery")
        assert rows == before


class TestPublicSurface:
    """``__all__`` is the contract the REST layer imports against."""

    def test_everything_exported_actually_exists(self) -> None:
        import app.slate_insights as module

        for name in module.__all__:
            assert hasattr(module, name), f"__all__ names {name}, which does not exist"

    def test_nothing_private_is_exported(self) -> None:
        import app.slate_insights as module

        assert not [name for name in module.__all__ if name.startswith("_")]

    def test_the_exported_names_are_grouped_and_sorted_so_a_new_one_is_a_one_line_diff(
        self,
    ) -> None:
        """Constants, then types, then functions — each group sorted, as its predecessors are."""
        import app.slate_insights as module

        groups: dict = {"constant": [], "type": [], "function": []}
        for name in module.__all__:
            kind = "constant" if name.isupper() else "type" if name[0].isupper() else "function"
            groups[kind].append(name)
        for kind, names in groups.items():
            assert names == sorted(names), f"the {kind} group is out of order"
        assert list(module.__all__) == [*groups["constant"], *groups["type"], *groups["function"]]

    def test_no_name_is_exported_twice(self) -> None:
        import app.slate_insights as module

        assert len(set(module.__all__)) == len(module.__all__)

    @pytest.mark.parametrize(
        "function",
        [
            correlate_signals,
            evaluate_budget,
            forecast_service,
            normalize_budget,
            normalize_export,
            normalize_policy,
            normalize_residency_lane,
            normalize_tail_request,
            plan_live_tail,
            redact_evidence,
            residency_coverage,
            roll_up_usage,
            signals_digest,
            validate_budget,
            validate_export,
            validate_policy,
            validate_residency_lane,
            validate_synthetic_check,
        ],
    )
    def test_every_public_function_documents_itself(self, function) -> None:
        assert function.__doc__ and len(function.__doc__.strip()) > 40, function.__name__
