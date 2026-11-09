"""
Optional Claude-assisted category suggestion (V2-MCP-23.4 / MCAT-9.4, #3694).

The keyword heuristic in :mod:`app.mcp_category_suggestion` handles servers whose tool names say what
they do. For the rest, this module asks the Claude API to pick the best-fitting category for a server
from the tenant's own lookup. It is the model-calling counterpart to that heuristic and, like it, is
**suggest-only**: the answer is returned to a person who confirms it; nothing here writes.

Design notes:

* **Opt-in and gated.** Runs only when ``APIOME_MCP_AI_CATEGORIZATION_ENABLED`` is on *and* an API key
  is configured. :func:`suggest_category_with_claude` returns ``None`` in every other case (flag off, no
  key, empty vocabulary, network/parse error, a model refusal, or an answer outside the vocabulary), so
  the caller falls back to the heuristic and never a 500 — the same posture as the server digest
  (:mod:`app.mcp_digest_service`).
* **Constrained to the vocabulary.** The request uses structured output with the category slugs as a
  JSON-schema ``enum``, and the reply is checked against the vocabulary again before it is returned, so
  the model can never invent a category.
* **No tool is ever executed.** The prompt carries the server's *declared* names and descriptions only.
* **Stdlib only.** Like the digest, the HTTP call uses ``urllib`` rather than adding an SDK dependency,
  and fails soft — any transport, HTTP or parse error logs a warning and returns ``None``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import settings

logger = logging.getLogger(__name__)

#: Claude Messages API endpoint and the pinned wire version (same as the digest).
_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"

#: Server-side refusal fallback (beta). Sent only for models that accept the ``"default"`` form.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})

#: The answer is one slug plus a sentence; this leaves room for the model's thinking.
_MAX_TOKENS = 2048

#: Only the first N tools are described — enough to characterize a server without an unbounded prompt.
_PROMPT_TOOL_LIMIT = 60

#: Longest tool description quoted in the prompt.
_PROMPT_DESCRIPTION_LIMIT = 300

_SYSTEM_PROMPT = (
    "You file Model Context Protocol (MCP) servers into a catalog. Given a server's declared name, "
    "instructions and tools, choose the one category from the provided list that best describes what "
    "the server is for, and give a one-sentence reason that cites the tools. Choose \"other\" only when "
    "no listed category fits. The tool details describe the surface only - you must not attempt to "
    "call, execute or simulate any tool."
)


@dataclass(frozen=True)
class ClaudeCategorySuggestion:
    """The category Claude picked for a server.

    Attributes:
        slug: A slug from the vocabulary the request offered.
        rationale: Claude's one-sentence reason (may be empty).
        model: The model that answered.
    """

    slug: str
    rationale: str
    model: str


def ai_categorization_available() -> bool:
    """True when the Claude-assisted step can run (flag on and an API key configured)."""
    return bool(settings.mcp_ai_categorization_enabled and settings.anthropic_api_key)


def build_category_prompt(
    server: Mapping[str, Any],
    tools: Sequence[Mapping[str, Any]],
    categories: Sequence[Mapping[str, Any]],
) -> str:
    """Render the user-turn prompt: the category list, then the server's identity and tools.

    Deterministic for the same input. Tools beyond :data:`_PROMPT_TOOL_LIMIT` are summarized as a
    count; long descriptions are cut to :data:`_PROMPT_DESCRIPTION_LIMIT` characters.

    Args:
        server: ``name`` / ``server_name`` / ``server_title`` / ``instructions`` (any may be absent).
        tools: Tool rows with ``name`` and optionally ``title`` / ``description``.
        categories: Lookup rows with ``slug`` / ``label`` and optionally ``description``.

    Returns:
        The prompt text.
    """
    lines: List[str] = ["Categories (slug: label):"]
    for category in categories:
        line = f"- {category['slug']}: {category.get('label') or category['slug']}"
        description = str(category.get("description") or "").strip()
        if description:
            line += f" - {description}"
        lines.append(line)

    lines.append("")
    name = server.get("server_title") or server.get("server_name") or server.get("name") or "Unnamed"
    lines.append(f"Server name: {name}")
    if server.get("name") and server.get("name") != name:
        lines.append(f"Catalog entry name: {server['name']}")
    instructions = server.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        lines.append(f"Server-provided instructions: {instructions.strip()}")

    lines.append("")
    if tools:
        lines.append(f"Tools ({len(tools)} total):")
        for tool in list(tools)[:_PROMPT_TOOL_LIMIT]:
            label = tool.get("title") or tool.get("name") or "unnamed"
            detail = f"- {tool.get('name') or label}"
            if tool.get("title") and tool.get("title") != tool.get("name"):
                detail += f" ({label})"
            description = str(tool.get("description") or "").strip()
            if description:
                detail += f": {description[:_PROMPT_DESCRIPTION_LIMIT]}"
            lines.append(detail)
        if len(tools) > _PROMPT_TOOL_LIMIT:
            lines.append(f"- ... and {len(tools) - _PROMPT_TOOL_LIMIT} more tools")
    else:
        lines.append("This server exposes no tools.")

    lines.append("")
    lines.append("Choose the category now.")
    return "\n".join(lines)


def build_request_body(
    server: Mapping[str, Any],
    tools: Sequence[Mapping[str, Any]],
    categories: Sequence[Mapping[str, Any]],
    model: str,
) -> Dict[str, Any]:
    """Build the Messages API request body, with the slugs as a structured-output ``enum``.

    Args:
        server: See :func:`build_category_prompt`.
        tools: See :func:`build_category_prompt`.
        categories: See :func:`build_category_prompt`; their slugs become the allowed answers.
        model: The Claude model id.

    Returns:
        The JSON-serializable body.
    """
    slugs = [str(c["slug"]) for c in categories]
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        "system": _SYSTEM_PROMPT,
        "output_config": {
            # Picking one label from a short list does not need deep reasoning.
            "effort": "low",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": slugs},
                        "reason": {"type": "string"},
                    },
                    "required": ["category", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "messages": [
            {"role": "user", "content": build_category_prompt(server, tools, categories)}
        ],
    }
    if model in _FALLBACK_MODELS:
        body["fallbacks"] = "default"
    return body


def suggest_category_with_claude(
    server: Mapping[str, Any],
    tools: Sequence[Mapping[str, Any]],
    categories: Sequence[Mapping[str, Any]],
) -> Optional[ClaudeCategorySuggestion]:
    """Ask Claude for the best-fitting category, or ``None`` (suggest-only; never writes).

    Returns ``None`` — the caller falls back to the heuristic — when the feature is unavailable (see
    :func:`ai_categorization_available`), the vocabulary is empty, or the call fails for any reason
    (transport error, non-200, unparseable body, ``refusal`` stop reason, or a slug outside the
    vocabulary). Never raises for an operational failure.

    Args:
        server: See :func:`build_category_prompt`.
        tools: See :func:`build_category_prompt`.
        categories: The tenant's lookup rows; the answer is always one of their slugs.

    Returns:
        The suggestion, or ``None``.
    """
    if not ai_categorization_available() or not categories:
        return None

    model = settings.mcp_ai_categorization_model
    headers = {
        "content-type": "application/json",
        "x-api-key": str(settings.anthropic_api_key),
        "anthropic-version": _ANTHROPIC_VERSION,
    }
    if model in _FALLBACK_MODELS:
        headers["anthropic-beta"] = _FALLBACK_BETA
    request = Request(
        _ANTHROPIC_MESSAGES_URL,
        data=json.dumps(build_request_body(server, tools, categories, model)).encode("utf-8"),
        method="POST",
        headers=headers,
    )

    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                logger.warning("[mcp-category] Claude API returned %s %s", response.status, response.reason)
                return None
            data = json.loads(response.read().decode())
    except HTTPError as exc:
        logger.warning("[mcp-category] Claude API HTTP error: %s %s", exc.code, exc.reason)
        return None
    except (URLError, OSError) as exc:
        logger.warning("[mcp-category] Claude API request error: %s", exc)
        return None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("[mcp-category] Claude API parse error: %s", exc)
        return None

    return parse_category_response(data, {str(c["slug"]) for c in categories}, model)


def parse_category_response(
    data: Mapping[str, Any], allowed_slugs: set, model: str
) -> Optional[ClaudeCategorySuggestion]:
    """Read the structured answer out of a Messages API response body, or ``None``.

    ``None`` for a ``refusal`` stop reason, a body with no text, text that is not the expected JSON
    object, or a category outside ``allowed_slugs``. The answering model is taken from the body when
    present (a fallback model may have answered), else ``model``.
    """
    if data.get("stop_reason") == "refusal":
        logger.warning("[mcp-category] Claude API declined to categorize (stop_reason=refusal)")
        return None
    content = data.get("content")
    if not isinstance(content, list):
        return None
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "text"
    ).strip()
    if not text:
        return None
    try:
        answer = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("[mcp-category] Claude API answer was not JSON")
        return None
    if not isinstance(answer, Mapping):
        return None
    slug = str(answer.get("category") or "").strip().lower()
    if slug not in allowed_slugs:
        logger.warning("[mcp-category] Claude API answered outside the vocabulary: %r", slug)
        return None
    return ClaudeCategorySuggestion(
        slug=slug,
        rationale=str(answer.get("reason") or "").strip(),
        model=str(data.get("model") or model),
    )


__all__ = [
    "ClaudeCategorySuggestion",
    "ai_categorization_available",
    "build_category_prompt",
    "build_request_body",
    "parse_category_response",
    "suggest_category_with_claude",
]
