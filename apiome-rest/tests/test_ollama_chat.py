"""Ollama chat client — AGX-1.3 (#4531).

``urlopen`` is replaced, so these tests pin the request :func:`app.ollama_chat.chat_completion`
sends (``/api/chat``, non-streamed, temperature 0, optional JSON mode) and that every failure
degrades to ``None`` instead of raising.
"""

from __future__ import annotations

import io
import json
from typing import Any, Dict, List
from urllib.error import URLError

import pytest

import app.ollama_chat as ollama_chat
from app.ollama_chat import chat_completion


class _Response(io.BytesIO):
    """A minimal ``urlopen`` response: a body, a status and a reason."""

    def __init__(self, body: Any, status: int = 200) -> None:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        super().__init__(raw)
        self.status = status
        self.reason = "OK" if status == 200 else "Error"


@pytest.fixture
def sent(monkeypatch) -> List[Dict[str, Any]]:
    """Capture each request and answer every one with the same JSON reply."""
    calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(ollama_chat.settings, "ollama_base_url", "http://ollama.test:11434/")

    def fake_urlopen(request, timeout):
        calls.append(
            {"url": request.full_url, "body": json.loads(request.data), "timeout": timeout}
        )
        return _Response({"message": {"role": "assistant", "content": '{"tool": "x"}'}})

    monkeypatch.setattr(ollama_chat, "urlopen", fake_urlopen)
    return calls


def test_a_reply_is_returned_and_the_request_is_deterministic(sent):
    assert chat_completion(" llama3.1:8b ", "sys", "user", json_mode=True) == '{"tool": "x"}'
    [call] = sent
    assert call["url"] == "http://ollama.test:11434/api/chat"
    assert call["body"] == {
        "model": "llama3.1:8b",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ],
        "stream": False,
        "options": {"temperature": 0},
        "format": "json",
    }
    assert call["timeout"] == ollama_chat.DEFAULT_CHAT_TIMEOUT_SECONDS


def test_json_mode_is_off_by_default(sent):
    chat_completion("m", "s", "u")
    assert "format" not in sent[0]["body"]


def test_a_blank_model_makes_no_call(sent):
    assert chat_completion("  ", "s", "u") is None
    assert sent == []


@pytest.mark.parametrize(
    "outcome",
    [
        URLError("connection refused"),
        _Response({"error": "model not found"}, status=404),
        _Response(b"not json"),
        _Response({"message": {"content": "   "}}),
        _Response({"done": True}),
        _Response([1, 2]),
    ],
)
def test_every_failure_is_none(monkeypatch, outcome):
    def fake_urlopen(_request, timeout):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(ollama_chat, "urlopen", fake_urlopen)
    assert chat_completion("m", "s", "u") is None
