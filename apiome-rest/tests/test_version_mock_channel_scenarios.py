"""Scenario overrides keyed by an AsyncAPI channel (``PUBLISH /<channel>``) — XPC-2.2 (#5736).

A canned body for a channel becomes the payload the hosted mock publishes to the version's bound
broker. Author-time validation accepts the key only for a channel the version declares.
"""

from __future__ import annotations

from app.mock_scenario_settings import (
    channel_scenario_key,
    is_channel_publish_key,
    normalize_operation_key,
    uses_channel_keys,
    validate_mock_scenarios,
)
from app.models import MockScenarioSpec

_SPEC = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}}
_CHANNELS = frozenset({channel_scenario_key("user/signedup")})


def _scenarios(key: str, body=None) -> dict:
    return {
        "vip": MockScenarioSpec.model_validate(
            {"operations": {key: {"responses": [{"status": 200, "body": body or {"userId": "vip"}}]}}}
        )
    }


def test_channel_keys_have_one_canonical_form() -> None:
    assert channel_scenario_key("/user/signedup/") == "PUBLISH /user/signedup"
    assert normalize_operation_key("publish /user/signedup") == "PUBLISH /user/signedup"
    assert is_channel_publish_key("PUBLISH /user/signedup")
    assert not is_channel_publish_key("POST /user/signedup")


def test_a_key_naming_a_declared_channel_validates() -> None:
    errors = validate_mock_scenarios(_scenarios("PUBLISH /user/signedup"), _SPEC, channel_operations=_CHANNELS)
    assert errors == []


def test_a_key_naming_no_channel_is_rejected() -> None:
    errors = validate_mock_scenarios(_scenarios("PUBLISH /orders/placed"), _SPEC, channel_operations=_CHANNELS)
    assert errors == [
        "Scenario 'vip', operation 'PUBLISH /orders/placed': no event channel orders/placed exists in this version."
    ]


def test_a_channel_key_on_a_non_event_version_is_rejected() -> None:
    errors = validate_mock_scenarios(_scenarios("PUBLISH /user/signedup"), _SPEC)
    assert len(errors) == 1 and "no event channel" in errors[0]


def test_uses_channel_keys_only_when_a_scenario_names_one() -> None:
    assert uses_channel_keys(_scenarios("PUBLISH /user/signedup"))
    assert not uses_channel_keys(_scenarios("GET /pets"))
    assert not uses_channel_keys(_scenarios("Query.user"))
