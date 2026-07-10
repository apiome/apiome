"""Unit tests for mock_settings helpers (#4446, SIM-2.5)."""

from __future__ import annotations

from app.mock_settings_util import is_private_mock_mode, mock_settings_for_toggle, parse_mock_settings


def test_parse_mock_settings_accepts_dict_and_json_string() -> None:
    assert parse_mock_settings({"mode": "private"}) == {"mode": "private"}
    assert parse_mock_settings('{"mode":"private"}') == {"mode": "private"}
    assert parse_mock_settings(None) == {}


def test_is_private_mock_mode_only_for_unpublished_drafts() -> None:
    assert is_private_mock_mode({"mode": "private"}, published=False) is True
    assert is_private_mock_mode({"mode": "private"}, published=True) is False
    assert is_private_mock_mode({}, published=False) is False


def test_mock_settings_for_toggle() -> None:
    assert mock_settings_for_toggle(enabled=False, published=False) == "{}"
    assert mock_settings_for_toggle(enabled=True, published=True) == "{}"
    assert mock_settings_for_toggle(enabled=True, published=False) == '{"mode":"private"}'
