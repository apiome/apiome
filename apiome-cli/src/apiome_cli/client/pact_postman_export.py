"""Exporting a pact as a Postman collection — PFX-4.7 (#6944).

``apiome pact export-postman`` calls ``POST /v1/tenants/{t}/pact-postman-collections``. The server
writes a Postman Collection v2.1 from a stored pact (provider + consumer, and a consumer version,
tag, branch or pact version SHA) or from a local Pact file sent inline, and lists in ``notices``
everything the collection does not carry, each with a reason.

This module holds the pure parts — the path, the request body, the summary lines and the refusal
message — so the command stays thin and every rule here is unit-tested without HTTP.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

#: The notice outcome of an interaction that is not in the collection.
OUTCOME_LEFT_OUT = "left-out"


def postman_export_path(tenant_slug: str) -> str:
    """``/v1/tenants/{t}/pact-postman-collections``, the tenant escaped."""
    return f"/v1/tenants/{quote(tenant_slug, safe='')}/pact-postman-collections"


def build_export_body(
    *,
    provider: Optional[str],
    consumer: Optional[str],
    consumer_version: Optional[str],
    tag: Optional[str],
    branch: Optional[str],
    pact_version: Optional[str],
    pact: Optional[dict[str, Any]],
    provider_base_url: Optional[str],
    tests: bool,
) -> dict[str, Any]:
    """The JSON body of the export, with only the fields that were given.

    Args:
        provider: The provider pacticipant (required for a stored pact).
        consumer: The consumer pacticipant (required for a stored pact).
        consumer_version: A consumer version number.
        tag: A consumer version tag (the latest pact with it).
        branch: A consumer branch (the latest pact on it).
        pact_version: A pact version SHA.
        pact: A local Pact document, sent inline.
        provider_base_url: The ``{{baseUrl}}`` value.
        tests: Whether requests carry test scripts.

    Returns:
        The body; the server checks the combination and refuses with the reason.
    """
    body: dict[str, Any] = {"tests": tests}
    for key, value in (
        ("provider", provider),
        ("consumer", consumer),
        ("consumerVersion", consumer_version),
        ("tag", tag),
        ("branch", branch),
        ("pactVersionSha", pact_version),
        ("baseUrl", provider_base_url),
    ):
        if value is not None:
            body[key] = value
    if pact is not None:
        body["pact"] = pact
    return body


def has_left_out(response: dict[str, Any]) -> bool:
    """Whether any pact entry was left out of the collection."""
    return any(notice.get("outcome") == OUTCOME_LEFT_OUT for notice in response.get("notices") or [])


def notice_lines(notices: list[dict[str, Any]]) -> list[str]:
    """One indented line per notice: outcome, code, pointer, description, reason and paths."""
    lines = []
    for notice in notices:
        where = f" {notice['pointer']}" if notice.get("pointer") else ""
        named = f" '{notice['description']}'" if notice.get("description") else ""
        paths = f" ({', '.join(notice['paths'])})" if notice.get("paths") else ""
        lines.append(
            f"    {notice.get('outcome')} [{notice.get('code')}]{where}{named}: {notice.get('message')}{paths}"
        )
    return lines


def summary_lines(response: dict[str, Any]) -> list[str]:
    """The human-readable summary of an export.

    Args:
        response: The response body.

    Returns:
        Lines: which pact, how many requests out of how many entries, then one line per notice.
    """
    pact = response.get("pact") or {}
    counts = response.get("counts") or {}
    version = f" version {pact['consumerVersion']}" if pact.get("consumerVersion") else ""
    lines = [
        f"Postman collection for {pact.get('consumer')}{version} → {pact.get('provider')}: "
        f"{counts.get('exported', 0)} request(s) from {counts.get('interactions', 0)} interaction(s), "
        f"{counts.get('leftOut', 0)} left out",
    ]
    notices = response.get("notices") or []
    if notices:
        lines.append(f"  notices: {len(notices)}")
        lines.extend(notice_lines(notices))
    return lines


def refusal_message(status_code: int, payload: Any) -> Optional[str]:
    """The message of a coded refusal (``{"detail": {"code", "message"[, "notices"]}}``).

    Args:
        status_code: The HTTP status.
        payload: The parsed response body.

    Returns:
        ``HTTP <status> <code>: <message>`` plus the notice lines; ``None`` when the body is not a
        coded refusal (the generic error handling prints it then).
    """
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict) or not detail.get("code") or not detail.get("message"):
        return None
    lines = [f"HTTP {status_code} {detail['code']}: {detail['message']}"]
    notices = detail.get("notices")
    if isinstance(notices, list):
        lines.extend(notice_lines([notice for notice in notices if isinstance(notice, dict)]))
    return "\n".join(lines)
