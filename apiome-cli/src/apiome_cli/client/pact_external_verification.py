"""Publishing a verification report produced elsewhere — PFX-3.5 (#6935).

``apiome pact publish-verification-results <report>`` sends the report a team's own CI already has —
``pact_verifier_cli --json`` output, JUnit XML, or a Schemathesis, Newman or Dredd report (PFX-8.9) — to ``POST …/pact-broker/pacts/provider/{p}/
consumer/{c}/pact-version/{sha}/external-verification-results``. The server reads the report; the CLI
only names its media type, builds the query and prints what the server read and could not use.

This module holds the pure parts so the command stays a thin shell and every rule is unit-tested
without HTTP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

#: Report media types by file extension. Anything else is sent without a type and sniffed.
_REPORT_TYPES = {
    ".json": "application/json",
    ".xml": "application/xml",
    ".ndjson": "application/x-ndjson",
    ".jsonl": "application/x-ndjson",
}

#: The values of ``--format``.
REPORT_FORMATS = (
    "auto",
    "pact-verifier-json",
    "junit",
    "schemathesis",
    "newman",
    "dredd",
)


def report_content_type(path: Path, explicit: Optional[str]) -> str:
    """The media type to send a report as.

    Args:
        path: The report file.
        explicit: ``--content-type`` when given.

    Returns:
        ``explicit``, else the type its extension implies, else ``application/octet-stream`` (the
        server then sniffs the body).
    """
    return explicit or _REPORT_TYPES.get(
        path.suffix.lower(), "application/octet-stream"
    )


def external_results_path(
    tenant_slug: str,
    provider: str,
    consumer: str,
    sha: str,
    *,
    provider_app_version: str,
    build_url: Optional[str] = None,
    branch: Optional[str] = None,
    tags: Optional[list[str]] = None,
    report_format: str = "auto",
    verifier: Optional[str] = None,
    verifier_version: Optional[str] = None,
    report_id: Optional[str] = None,
) -> str:
    """The request path, with its query, for one ingestion.

    Args:
        tenant_slug: The workspace.
        provider: The provider pacticipant.
        consumer: The consumer pacticipant.
        sha: The pact version's SHA-256.
        provider_app_version: The provider version the report verified.
        build_url: The CI build.
        branch: A branch to record the provider version on.
        tags: Tags for the provider version.
        report_format: One of :data:`REPORT_FORMATS`.
        verifier: ``verifiedBy.implementation``.
        verifier_version: ``verifiedBy.version``.
        report_id: A linked Apiome provider-verification report.

    Returns:
        The path, starting with ``/v1/tenants/``.

    Raises:
        ValueError: for an unknown ``report_format``.
    """
    if report_format not in REPORT_FORMATS:
        raise ValueError(f"--format must be one of {', '.join(REPORT_FORMATS)}")
    pairs: list[tuple[str, str]] = [
        ("providerApplicationVersion", provider_app_version)
    ]
    for key, value in (
        ("buildUrl", build_url),
        ("branch", branch),
        ("format", report_format if report_format != "auto" else None),
        ("verifier", verifier),
        ("verifierVersion", verifier_version),
        ("providerVerificationReportId", report_id),
    ):
        if value:
            pairs.append((key, value))
    pairs.extend(("tag", tag) for tag in tags or [] if tag)
    base = (
        f"/v1/tenants/{quote(tenant_slug, safe='')}/pact-broker/pacts/provider/{quote(provider, safe='')}"
        f"/consumer/{quote(consumer, safe='')}/pact-version/{quote(sha, safe='')}/external-verification-results"
    )
    return f"{base}?{urlencode(pairs)}"


def summary_lines(response: dict[str, Any]) -> list[str]:
    """The human-readable summary of an ingestion.

    Args:
        response: The response body (the stored result and its ``ingestion`` object).

    Returns:
        Lines: the verdict with the report's format and interaction count, the result's URL, and
        every notice with its location, so nothing the server could not use goes unseen.
    """
    ingestion = response.get("ingestion") or {}
    verdict = "passed" if response.get("success") else "FAILED"
    lines = [
        f"Verification of {response.get('providerName') or '?'} {response.get('providerApplicationVersion') or '?'}"
        f" {verdict} ({ingestion.get('format') or '?'} report, {ingestion.get('interactions', 0)} interaction(s))",
    ]
    href = ((response.get("_links") or {}).get("self") or {}).get("href")
    if href:
        lines.append(f"  result: {href}")
    for notice in ingestion.get("notices") or []:
        lines.append(
            f"  note {notice.get('pointer') or '(report)'}: {notice.get('reason')}"
        )
    return lines
