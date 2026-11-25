"""Exporting and publishing a declared consumer surface as a Pact file — PFX-2.6 (#6930).

``apiome pact export-consumer-contract`` and ``apiome pact publish-consumer-contract`` call
``GET`` / ``POST …/projects/{p}/consumers/{c}/pact[/publish]``. The server generates the Pact v4
document from the consumer's picker-declared contract, using the specification's examples as
sample values, and reports every value it had to invent and everything it had to leave out.

This module holds the pure parts — building paths and bodies, and turning a response into
summary lines — so the commands stay thin and every rule here is unit-tested without HTTP.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote, urlencode


def consumer_pact_path(
    tenant_slug: str,
    project: str,
    consumer: str,
    *,
    publish: bool = False,
    revision: Optional[int] = None,
    provider: Optional[str] = None,
) -> str:
    """The export (or publish) path of one consumer, each segment escaped.

    Args:
        tenant_slug: The workspace.
        project: The project's slug or id.
        consumer: The consumer's slug or id.
        publish: Build the ``…/pact/publish`` path instead of ``…/pact``.
        revision: A contract revision, as a query parameter (export only).
        provider: The provider pacticipant name, as a query parameter (export only).

    Returns:
        ``/v1/tenants/{t}/projects/{p}/consumers/{c}/pact`` (``/publish``), with any query string.
    """
    path = (
        f"/v1/tenants/{quote(tenant_slug, safe='')}/projects/{quote(project, safe='')}"
        f"/consumers/{quote(consumer, safe='')}/pact"
    )
    if publish:
        return f"{path}/publish"
    query = {
        key: value
        for key, value in (("revision", revision), ("provider", provider))
        if value is not None
    }
    return f"{path}?{urlencode(query)}" if query else path


def build_publish_body(
    *,
    consumer_app_version: str,
    branch: Optional[str],
    tags: Optional[list[str]],
    build_url: Optional[str],
    revision: Optional[int],
    provider: Optional[str],
) -> dict[str, Any]:
    """The JSON body of ``POST …/consumers/{c}/pact/publish``.

    Args:
        consumer_app_version: The consumer build's version (a commit SHA is best).
        branch: The branch it was built from.
        tags: Tags for the consumer version.
        build_url: The CI build URL.
        revision: A contract revision; the current one when ``None``.
        provider: The provider pacticipant name; the server chooses when ``None``.

    Returns:
        The body, with only the fields that were given.
    """
    body: dict[str, Any] = {"consumer_version": consumer_app_version}
    if branch:
        body["branch"] = branch
    if tags:
        body["tags"] = list(tags)
    if build_url:
        body["build_url"] = build_url
    if revision is not None:
        body["revision"] = revision
    if provider:
        body["provider"] = provider
    return body


def has_findings(response: dict[str, Any]) -> bool:
    """Whether the generated pact invented any value or left anything out."""
    return bool(response.get("findings"))


def summary_lines(response: dict[str, Any]) -> list[str]:
    """The human-readable summary of an export or a publish.

    Args:
        response: The response body.

    Returns:
        Lines: what was generated from which revision, one line per finding, and — after a
        publish — the broker's notices.
    """
    version = response.get("version_label") or response.get("version_record_id") or "?"
    lines = [
        f"Pact v4 for {response.get('consumer_name')} → {response.get('provider_name')}: "
        f"{response.get('interaction_count', 0)} interaction(s) from contract revision "
        f"{response.get('revision')} (specification {version})",
        f"  findings: {response.get('placeholder_count', 0)} placeholder(s), "
        f"{response.get('omitted_count', 0)} omitted",
    ]
    for finding in response.get("findings") or []:
        where = " ".join(
            str(part) for part in (finding.get("method"), finding.get("path")) if part
        )
        status = f" {finding['status']}" if finding.get("status") else ""
        field = (
            f" {finding.get('location')} '{finding['field']}'"
            if finding.get("field")
            else ""
        )
        lines.append(
            f"    {finding.get('outcome')} [{finding.get('reason')}]"
            f"{(' ' + where) if where else ''}{status}{field}: {finding.get('message')}"
        )
    publish = response.get("publish")
    if isinstance(publish, dict):
        for notice in publish.get("notices") or []:
            lines.append(f"  {notice.get('type', 'info')}: {notice.get('text')}")
    return lines
