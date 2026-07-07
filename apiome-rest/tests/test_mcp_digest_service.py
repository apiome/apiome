"""Unit tests for the Claude-API server-digest service (V2-MCP-32.5 / MCAT-18.5, #4649).

Exercises :mod:`app.mcp_digest_service` in isolation. The HTTP call to the Claude API is mocked, so these
assert the gating (flag off / no key → no call, ``None``), the prompt construction, and the response
parsing (text extraction, refusal handling, transport/parse errors → ``None``) without a network.
"""

import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

from app import mcp_digest_service
from app.mcp_digest_service import build_digest_prompt, generate_server_digest
from app.mcp_insight_aggregation import ToolExample

_SERVER = {
    "server_name": "acme",
    "server_title": "Acme Weather",
    "server_version": "1.2.0",
    "instructions": "Use forecast for multi-day outlooks.",
}
_EXAMPLES = [
    ToolExample("forecast", "Forecast", "multi-day forecast", {"city": "example"}),
    ToolExample("current", None, "current conditions", {}),
]


@pytest.fixture
def _enabled(monkeypatch):
    monkeypatch.setattr(mcp_digest_service.settings, "mcp_ai_digest_enabled", True)
    monkeypatch.setattr(mcp_digest_service.settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(mcp_digest_service.settings, "mcp_ai_digest_model", "claude-sonnet-5")


class _FakeResponse:
    """A minimal stand-in for the urlopen context-manager result."""

    def __init__(self, body, status=200, reason="OK"):
        self.status = status
        self.reason = reason
        self._body = body.encode() if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _message_body(text):
    return json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]})


# ---------------------------------------------------------------------------
# build_digest_prompt
# ---------------------------------------------------------------------------


def test_build_digest_prompt_includes_identity_instructions_and_tools():
    prompt = build_digest_prompt(_SERVER, _EXAMPLES)
    assert "Acme Weather" in prompt  # title preferred over name
    assert "1.2.0" in prompt
    assert "Use forecast for multi-day outlooks." in prompt
    assert "Tools (2 total):" in prompt
    assert "- Forecast: multi-day forecast" in prompt
    # the schema-derived example arguments are surfaced (deterministic JSON)
    assert '{"city": "example"}' in prompt
    # a tool with no arguments has no "example arguments" clause
    assert "- current: current conditions" in prompt


def test_build_digest_prompt_handles_empty_surface():
    prompt = build_digest_prompt({"server_name": "bare"}, [])
    assert "This server exposes no tools." in prompt
    assert prompt.strip().endswith("Write the digest now.")


# ---------------------------------------------------------------------------
# generate_server_digest — gating
# ---------------------------------------------------------------------------


def test_generate_returns_none_when_flag_disabled(monkeypatch):
    monkeypatch.setattr(mcp_digest_service.settings, "mcp_ai_digest_enabled", False)
    monkeypatch.setattr(mcp_digest_service.settings, "anthropic_api_key", "sk-test")
    with patch.object(mcp_digest_service, "urlopen") as mock_open:
        assert generate_server_digest(_SERVER, _EXAMPLES) is None
    mock_open.assert_not_called()


def test_generate_returns_none_when_no_api_key(monkeypatch):
    monkeypatch.setattr(mcp_digest_service.settings, "mcp_ai_digest_enabled", True)
    monkeypatch.setattr(mcp_digest_service.settings, "anthropic_api_key", None)
    with patch.object(mcp_digest_service, "urlopen") as mock_open:
        assert generate_server_digest(_SERVER, _EXAMPLES) is None
    mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# generate_server_digest — success & failure paths
# ---------------------------------------------------------------------------


def test_generate_returns_digest_text_and_sends_expected_request(_enabled):
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["body"] = json.loads(request.data.decode())
        return _FakeResponse(_message_body("This server lets you check the weather."))

    with patch.object(mcp_digest_service, "urlopen", _fake_urlopen):
        digest = generate_server_digest(_SERVER, _EXAMPLES)

    assert digest == "This server lets you check the weather."
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["model"] == "claude-sonnet-5"
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert captured["body"]["messages"][0]["role"] == "user"


def test_generate_returns_none_on_refusal(_enabled):
    body = json.dumps({"stop_reason": "refusal", "content": []})
    with patch.object(mcp_digest_service, "urlopen", return_value=_FakeResponse(body)):
        assert generate_server_digest(_SERVER, _EXAMPLES) is None


def test_generate_returns_none_on_non_200(_enabled):
    resp = _FakeResponse("nope", status=503, reason="Service Unavailable")
    with patch.object(mcp_digest_service, "urlopen", return_value=resp):
        assert generate_server_digest(_SERVER, _EXAMPLES) is None


def test_generate_returns_none_on_transport_error(_enabled):
    with patch.object(mcp_digest_service, "urlopen", side_effect=URLError("boom")):
        assert generate_server_digest(_SERVER, _EXAMPLES) is None


def test_generate_returns_none_on_unparseable_body(_enabled):
    with patch.object(mcp_digest_service, "urlopen", return_value=_FakeResponse("not json")):
        assert generate_server_digest(_SERVER, _EXAMPLES) is None


def test_generate_returns_none_when_no_text_content(_enabled):
    body = json.dumps({"stop_reason": "end_turn", "content": [{"type": "tool_use"}]})
    with patch.object(mcp_digest_service, "urlopen", return_value=_FakeResponse(body)):
        assert generate_server_digest(_SERVER, _EXAMPLES) is None
