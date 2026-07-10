"""Helpers for per-version mock_settings JSON (#4446, SIM-2.5)."""

from __future__ import annotations

import json
from typing import Any


def parse_mock_settings(raw: Any) -> dict[str, Any]:
    """Normalize ``versions.mock_settings`` JSONB to a dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def is_private_mock_mode(mock_settings: Any, *, published: bool) -> bool:
    """True when the version is configured as a key-gated draft mock."""
    if published:
        return False
    settings = parse_mock_settings(mock_settings)
    return settings.get("mode") == "private"


def mock_settings_for_toggle(*, enabled: bool, published: bool) -> str:
    """Return JSON text to persist alongside ``mock_enabled``."""
    if not enabled:
        return "{}"
    if published:
        return "{}"
    return '{"mode":"private"}'
