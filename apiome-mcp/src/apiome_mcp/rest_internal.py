"""Calls from the MCP server to apiome-rest's internal ``/v1/internal/mcp/*`` routes.

Shared by the export tools (MFX-40.1, #4339) and the pact tools (PFX-4.5, #6942). Those routes trust the
tenant the MCP server sends, so every call carries the shared internal service token
(``APIOME_MCP_REST_INTERNAL_URL`` + ``APIOME_MCP_REST_INTERNAL_SERVICE_TOKEN``). Every failure — not
configured, unreachable, a refusal, an unexpected payload — becomes a :class:`ToolError` that names it.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from apiome_mcp.settings import Settings

__all__ = ["post_internal", "rest_error_message"]


def rest_error_message(response: httpx.Response, *, with_code: bool = False) -> str:
    """The REST refusal's message, in one line (``detail.message``, a validation list, or the text).

    Args:
        response: The refused response.
        with_code: Prefix ``detail.code`` in brackets when present, so an agent can branch on it.

    Returns:
        The message.
    """
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.text[:500] or f"HTTP {response.status_code}"
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("detail") or detail)
        code = detail.get("code")
        return f"[{code}] {message}" if code and with_code else message
    if isinstance(detail, list):  # FastAPI validation errors
        return "; ".join(str(item.get("msg", item)) for item in detail if isinstance(item, dict)) or str(detail)
    return str(detail or f"HTTP {response.status_code}")


async def post_internal(
    path: str,
    body: dict[str, Any],
    *,
    settings: Settings,
    what: str,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
    with_code: bool = False,
) -> dict[str, Any]:
    """POST one internal route and return its JSON object.

    Args:
        path: The route, e.g. ``/v1/internal/mcp/pacts/matrix``.
        body: The JSON body.
        settings: The process settings (REST URL and service token).
        what: What the call is, for messages (``export``, ``pact request``).
        timeout_seconds: The read timeout.
        transport: An ``httpx`` transport (tests).
        with_code: Put the refusal's ``detail.code`` in its message (see :func:`rest_error_message`).

    Returns:
        The answer.

    Raises:
        ToolError: Not configured, unreachable, refused (``<What> refused (<status>): <message>``) or an
            answer that is not a JSON object.
    """
    base = (settings.rest_internal_url or "").strip().rstrip("/")
    token = settings.rest_internal_service_token.get_secret_value() if settings.rest_internal_service_token else ""
    label = what[:1].upper() + what[1:]
    if not base or not token:
        raise ToolError(
            f"{label} over MCP is not configured on this server: set APIOME_MCP_REST_INTERNAL_URL and "
            "APIOME_MCP_REST_INTERNAL_SERVICE_TOKEN (apiome-rest's INTERNAL_SERVICE_TOKEN)."
        )
    timeout = httpx.Timeout(timeout_seconds, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(f"{base}{path}", json=body, headers={"X-Internal-Service-Token": token})
    except httpx.HTTPError as exc:
        raise ToolError(f"apiome-rest could not be reached for the {what}: {exc.__class__.__name__}.") from exc
    if response.status_code >= 400:
        message = rest_error_message(response, with_code=with_code)
        raise ToolError(f"{label} refused ({response.status_code}): {message}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ToolError(f"apiome-rest answered the {what} with a body that is not JSON.") from exc
    if not isinstance(payload, dict):
        raise ToolError(f"apiome-rest answered the {what} with an unexpected payload.")
    return payload
