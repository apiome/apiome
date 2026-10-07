"""
Ollama chat client — the REST side of the copilot infrastructure (AGX-1.3, #4531).

apiome-ui's copilot features (LLM import, schema suggestions) talk to Ollama's ``/api/chat``.
This module is the matching server-side call for apiome-rest features that need a generated
text, starting with the agent toolset description-enrichment pass
(:mod:`app.agent_toolset_enrichment`).

Like :mod:`app.embedding` (the Ollama embedding client) it uses stdlib ``urllib`` rather than an
SDK, reads the server from ``settings.ollama_base_url``, and fails soft: a transport error, a
non-200 status, or an unexpected body logs a warning and returns ``None``. Callers treat ``None``
as "the copilot is unavailable" and degrade, never as a 500.
"""

from __future__ import annotations

import json
import logging
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import settings

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_CHAT_TIMEOUT_SECONDS", "chat_completion"]

#: A local model can take a while to answer a cold prompt; past this the call is abandoned.
DEFAULT_CHAT_TIMEOUT_SECONDS = 60.0


def chat_completion(
    model: str,
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    timeout: float = DEFAULT_CHAT_TIMEOUT_SECONDS,
) -> Optional[str]:
    """Ask an Ollama chat model for one non-streamed reply.

    The request is deterministic as far as Ollama allows (``temperature: 0``), so the same prompt
    tends to give the same reply.

    Args:
        model: The Ollama model name (for example ``llama3.1:8b``). Blank means no call is made.
        system: The system prompt.
        user: The user turn.
        json_mode: Ask Ollama to constrain the reply to JSON (``format: "json"``).
        timeout: Seconds to wait for the whole reply.

    Returns:
        The assistant's reply text, or ``None`` when the model is blank, Ollama cannot be reached,
        answers with an error, or returns a body without assistant content.
    """
    if not model or not model.strip():
        return None
    body = {
        "model": model.strip(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0},
    }
    if json_mode:
        body["format"] = "json"
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                logger.warning("[ollama-chat] chat failed: %s %s", response.status, response.reason)
                return None
            data = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, OSError) as exc:
        logger.warning("[ollama-chat] request error: %s", exc)
        return None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("[ollama-chat] parse error: %s", exc)
        return None

    message = data.get("message") if isinstance(data, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        logger.warning("[ollama-chat] reply had no assistant content")
        return None
    return content
