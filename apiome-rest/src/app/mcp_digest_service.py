"""
Natural-language server digest via the Claude API (V2-MCP-32.5 / MCAT-18.5, #4649).

The catalog can *show* a server's surface (its tools, resources, prompts, metrics) but still leaves the
reader to synthesize "so what can this actually do for me?". This module produces the AI half of the
answer: a short, plain-language digest of a cataloged MCP server ("this server lets you …") written by
the Claude API from the server's declared surface. It is the model-calling counterpart to the pure,
offline example synthesis in :mod:`app.mcp_insight_aggregation` (``build_tool_examples``) — the digest
route pairs this prose with those schema-derived example calls.

Design notes:

* **Opt-in and gated.** Generation only runs when ``APIOME_MCP_AI_DIGEST_ENABLED`` is on *and* an API
  key is configured. :func:`generate_server_digest` returns ``None`` in every other case (flag off, no
  key, empty surface, network/parse error, or a model refusal), so the caller degrades to a labelled
  no-op and never a 500 — mirroring the flag-gated similar-servers reindex (MCAT-18.4).
* **No tool is ever executed.** The prompt describes the surface using the server's *declared* metadata
  (names, descriptions, and schema-derived example arguments); the model is explicitly told these are
  illustrative and that it must not attempt to invoke anything. Combined with the deterministic example
  synthesis, the "no tool is executed to produce examples" acceptance criterion holds by construction.
* **Stdlib only.** Like :mod:`app.embedding` (the Ollama client), the HTTP call uses ``urllib`` rather
  than adding an SDK dependency, and fails soft — any transport, HTTP, or parse error logs a warning and
  returns ``None``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import settings
from .mcp_insight_aggregation import ToolExample

logger = logging.getLogger(__name__)

#: Claude Messages API endpoint and the pinned wire version (see the claude-api reference).
_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

#: The digest is a short paragraph; cap output tokens so a runaway generation can't balloon cost/latency.
_DIGEST_MAX_TOKENS = 400

#: Only the first N tools are described in the prompt — enough to characterize the server without an
#: unbounded prompt for a very large surface. The full example list is still returned to the caller.
_DIGEST_PROMPT_TOOL_LIMIT = 40

_SYSTEM_PROMPT = (
    "You write a concise, plain-language digest of a Model Context Protocol (MCP) server for a catalog "
    "browser. Given the server's declared name, instructions, and tools, write 2-4 sentences describing "
    "what the server lets a user accomplish and the kinds of tasks its tools support. Start with a phrase "
    "like \"This server lets you\". Be concrete and neutral; do not invent capabilities that are not "
    "implied by the tools, do not mention that you are an AI, and do not include a preamble or a heading. "
    "The tool details and any example arguments are illustrative descriptions of the surface only — you "
    "must not attempt to call, execute, or simulate any tool."
)


def build_digest_prompt(server: Mapping[str, Any], tool_examples: List[ToolExample]) -> str:
    """Render the user-turn prompt describing a server's surface for the digest model (MCAT-18.5).

    Assembles a compact, deterministic description of the server — its display name / version, its
    ``instructions`` (the server's own natural-language guidance, when present), and up to
    :data:`_DIGEST_PROMPT_TOOL_LIMIT` of its tools with each tool's description and schema-derived
    example arguments. The text is data only: it never asks the model to invoke anything, and it is built
    the same way for the same surface, so the (cached-per-fingerprint) result is stable.

    Args:
        server: Identity fields of the current version snapshot (``server_name`` / ``server_title`` /
            ``server_version`` / ``instructions``).
        tool_examples: The tools' schema-derived example calls (:class:`ToolExample`), in surface order.

    Returns:
        The prompt string sent as the user message.
    """
    name = server.get("server_title") or server.get("server_name") or "This MCP server"
    lines: List[str] = [f"Server name: {name}"]

    version = server.get("server_version")
    if version:
        lines.append(f"Server version: {version}")

    instructions = server.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        lines.append(f"Server-provided instructions: {instructions.strip()}")

    if tool_examples:
        lines.append("")
        lines.append(f"Tools ({len(tool_examples)} total):")
        for example in tool_examples[:_DIGEST_PROMPT_TOOL_LIMIT]:
            label = example.title or example.name
            description = (example.description or "").strip()
            detail = f"- {label}"
            if description:
                detail += f": {description}"
            if example.arguments:
                detail += f" (example arguments: {json.dumps(example.arguments, sort_keys=True)})"
            lines.append(detail)
        if len(tool_examples) > _DIGEST_PROMPT_TOOL_LIMIT:
            lines.append(f"- … and {len(tool_examples) - _DIGEST_PROMPT_TOOL_LIMIT} more tools")
    else:
        lines.append("")
        lines.append("This server exposes no tools.")

    lines.append("")
    lines.append("Write the digest now.")
    return "\n".join(lines)


def generate_server_digest(
    server: Mapping[str, Any], tool_examples: List[ToolExample]
) -> Optional[str]:
    """Generate the natural-language digest for a server via the Claude API, or ``None`` (MCAT-18.5).

    The gated AI step behind the digest route. Returns ``None`` — a labelled no-op for the caller — when
    the feature flag is off, no API key is configured, or the call fails for any reason (transport error,
    non-200 response, unparseable body, or a model ``refusal`` stop reason). On success returns the
    trimmed digest text. The function never raises for an operational failure; only a programming error
    would propagate.

    Args:
        server: Identity fields of the current version snapshot (see :func:`build_digest_prompt`).
        tool_examples: The tools' schema-derived example calls, used to describe the surface.

    Returns:
        The digest text, or ``None`` when disabled/unconfigured/failed.
    """
    if not settings.mcp_ai_digest_enabled:
        return None
    api_key = settings.anthropic_api_key
    if not api_key:
        logger.warning("[mcp-digest] AI digest enabled but no API key configured; skipping generation")
        return None

    prompt = build_digest_prompt(server, tool_examples)
    payload = json.dumps(
        {
            "model": settings.mcp_ai_digest_model,
            "max_tokens": _DIGEST_MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            # A short summary needs no extended reasoning; disable it to keep the call cheap and fast.
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")

    request = Request(
        _ANTHROPIC_MESSAGES_URL,
        data=payload,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                logger.warning("[mcp-digest] Claude API returned %s %s", response.status, response.reason)
                return None
            data = json.loads(response.read().decode())
    except HTTPError as exc:
        logger.warning("[mcp-digest] Claude API HTTP error: %s %s", exc.code, exc.reason)
        return None
    except (URLError, OSError) as exc:
        logger.warning("[mcp-digest] Claude API request error: %s", exc)
        return None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("[mcp-digest] Claude API parse error: %s", exc)
        return None

    return _extract_digest_text(data)


def _extract_digest_text(data: Mapping[str, Any]) -> Optional[str]:
    """Pull the digest text out of a Claude Messages API response body, or ``None``.

    A safety ``refusal`` stop reason (a successful HTTP 200 with no usable content) yields ``None`` rather
    than surfacing a partial/empty answer. Otherwise the text blocks of ``content`` are concatenated and
    trimmed; a body with no text content also yields ``None``.
    """
    if data.get("stop_reason") == "refusal":
        logger.warning("[mcp-digest] Claude API declined to produce a digest (stop_reason=refusal)")
        return None

    content = data.get("content")
    if not isinstance(content, list):
        return None
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "text"
    ]
    text = "".join(parts).strip()
    return text or None
