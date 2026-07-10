"""Unit tests for mock chaos knob validation and canonicalization (#4455, SIM-4.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.mock_scenario_settings import (
    MAX_CHAOS_OPERATIONS,
    chaos_from_storage,
    chaos_to_storage,
    scenarios_to_storage,
    validate_mock_chaos,
    validate_mock_scenarios,
)
from app.models import MockChaosKnobsSpec, MockChaosSpec, MockScenarioSpec

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"type": "array", "items": {"type": "object"}}}},
                    },
                }
            }
        }
    },
}


def _chaos(raw: dict) -> MockChaosSpec:
    return MockChaosSpec.model_validate(raw)


# ---------------------------------------------------------------------------
# Model-level range validation
# ---------------------------------------------------------------------------


def test_knobs_accept_valid_ranges() -> None:
    knobs = MockChaosKnobsSpec.model_validate({"delayMs": 800, "jitterMs": 200, "errorRate": 25.5})
    assert knobs.delay_ms == 800
    assert knobs.jitter_ms == 200
    assert knobs.error_rate == 25.5


@pytest.mark.parametrize(
    "raw",
    [
        {"delayMs": -1},
        {"delayMs": 30_001},
        {"jitterMs": -1},
        {"jitterMs": 30_001},
        {"errorRate": -0.1},
        {"errorRate": 100.1},
        {"unknown": 1},
    ],
)
def test_knobs_reject_out_of_range_values(raw: dict) -> None:
    with pytest.raises(ValidationError):
        MockChaosKnobsSpec.model_validate(raw)


def test_knobs_reject_delay_plus_jitter_over_cap() -> None:
    with pytest.raises(ValidationError, match="30000"):
        MockChaosKnobsSpec.model_validate({"delayMs": 20_000, "jitterMs": 15_000})


# ---------------------------------------------------------------------------
# validate_mock_chaos
# ---------------------------------------------------------------------------


def test_validate_chaos_none_is_valid() -> None:
    assert validate_mock_chaos(None, SPEC) == []


def test_validate_chaos_known_operation_passes() -> None:
    chaos = _chaos({"default": {"delayMs": 800}, "operations": {"GET /pets": {"errorRate": 50}}})
    assert validate_mock_chaos(chaos, SPEC) == []


def test_validate_chaos_unknown_operation_rejected() -> None:
    chaos = _chaos({"operations": {"DELETE /pets": {"delayMs": 5}}})
    errors = validate_mock_chaos(chaos, SPEC)
    assert len(errors) == 1
    assert "DELETE /pets" in errors[0]


def test_validate_chaos_malformed_key_rejected() -> None:
    chaos = _chaos({"operations": {"not-a-key": {"delayMs": 5}}})
    errors = validate_mock_chaos(chaos, SPEC)
    assert any("GET /pets/{petId}" in error for error in errors)


def test_validate_chaos_too_many_operations_rejected() -> None:
    operations = {f"GET /pets/{index}": {"delayMs": 1} for index in range(MAX_CHAOS_OPERATIONS + 1)}
    chaos = _chaos({"operations": operations})
    errors = validate_mock_chaos(chaos, SPEC)
    assert any(str(MAX_CHAOS_OPERATIONS) in error for error in errors)


def test_validate_scenarios_checks_scenario_chaos() -> None:
    scenarios = {
        "degraded": MockScenarioSpec.model_validate(
            {"operations": {}, "chaos": {"operations": {"DELETE /pets": {"delayMs": 5}}}}
        )
    }
    errors = validate_mock_scenarios(scenarios, SPEC)
    assert any("Scenario 'degraded' chaos" in error and "DELETE /pets" in error for error in errors)


# ---------------------------------------------------------------------------
# Storage canonicalization
# ---------------------------------------------------------------------------


def test_chaos_to_storage_normalizes_keys_and_omits_unset() -> None:
    chaos = _chaos({"default": {"delayMs": 800}, "operations": {"get /pets": {"errorRate": 50}}})
    assert chaos_to_storage(chaos) == {
        "default": {"delayMs": 800},
        "operations": {"GET /pets": {"errorRate": 50.0}},
    }


def test_chaos_to_storage_empty_block() -> None:
    assert chaos_to_storage(_chaos({})) == {}


def test_scenarios_to_storage_includes_scenario_chaos() -> None:
    scenarios = {
        "degraded": MockScenarioSpec.model_validate(
            {"operations": {}, "chaos": {"default": {"errorRate": 100}}}
        ),
        "plain": MockScenarioSpec.model_validate({"operations": {}}),
    }
    storage = scenarios_to_storage(scenarios)
    assert storage["degraded"]["chaos"] == {"default": {"errorRate": 100.0}}
    assert "chaos" not in storage["plain"]


def test_chaos_from_storage_variants() -> None:
    assert chaos_from_storage(None) == (None, True)
    assert chaos_from_storage({}) == (None, True)
    assert chaos_from_storage({"chaos": {"default": {"delayMs": 5}}}) == (
        {"default": {"delayMs": 5}},
        True,
    )
    assert chaos_from_storage('{"chaos": {"default": {"delayMs": 5}}}') == (
        {"default": {"delayMs": 5}},
        True,
    )
    assert chaos_from_storage("not json") == (None, False)
    assert chaos_from_storage({"chaos": "nope"}) == (None, False)
