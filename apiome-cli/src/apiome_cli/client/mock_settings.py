"""Hosted-mock settings client helpers and output for ``apiome mock`` (SIM-2.4).

The CLI mirrors the SIM-2.1 REST control plane: the mock flag lives on the
version record (``VersionSchema.mockEnabled`` / ``mockBaseUrl``), the toggle is
``PUT /v1/versions/{tenant}/{project}/{version_record_id}/mock``, and the
best-effort usage summary comes from ``GET /v1/mocks/{tenant}/usage`` (SIM-1.5).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.output import RecordField, emit_json, emit_record_table


def _format_optional(value: Any) -> str:
    """Render an optional scalar cell, showing booleans as ``True``/``False``."""
    return "" if value is None else str(value)


# Field rows for the version-record table printed by status/enable/disable.
MOCK_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Project ID", "project_id", None),
    ("Version", "version_id", None),
    ("Published", "published", _format_optional),
    ("Mock Enabled", "mockEnabled", _format_optional),
    ("Mock Base URL", "mockBaseUrl", _format_optional),
)


def fetch_version_record(
    client: RestClient,
    tenant_slug: str,
    project_id: UUID,
    version_id: UUID,
) -> dict[str, Any]:
    """Fetch one version record (``GET /v1/versions/{tenant}/{project}/{id}``).

    Parameters
    ----------
    client:
        Authenticated REST client.
    tenant_slug:
        Tenant scope for the route.
    project_id:
        Parent project UUID.
    version_id:
        Version record UUID.

    Returns
    -------
    dict[str, Any]
        The ``VersionSchema`` payload (``mockEnabled``, ``mockBaseUrl``, …);
        exits the CLI on HTTP or transport errors.
    """
    payload = client.get(api_paths.version_record(tenant_slug, project_id, version_id)).json()
    return payload if isinstance(payload, dict) else {}


def set_version_mock(
    client: RestClient,
    tenant_slug: str,
    project_id: UUID,
    version_id: UUID,
    *,
    enabled: bool,
) -> dict[str, Any]:
    """Enable or disable the hosted mock (``PUT …/mock``, SIM-2.1).

    Parameters
    ----------
    client:
        Authenticated REST client.
    tenant_slug:
        Tenant scope for the route.
    project_id:
        Parent project UUID.
    version_id:
        Version record UUID.
    enabled:
        ``True`` to enable the mock, ``False`` to disable it.

    Returns
    -------
    dict[str, Any]
        The updated ``VersionSchema`` payload. REST eligibility errors (draft
        version, insufficient role) exit the CLI with a readable message and a
        non-zero exit code via the shared error mapping.
    """
    response = client.put(
        api_paths.version_mock(tenant_slug, project_id, version_id),
        json={"enabled": enabled},
    )
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_project_slug(
    client: RestClient,
    tenant_slug: str,
    project_id: UUID,
) -> str:
    """Best-effort lookup of a project's slug for usage filtering.

    Returns an empty string instead of failing so a usage-summary lookup never
    breaks ``mock status`` — usage is optional decoration on the status output.
    """
    response = client.get_raw(api_paths.project(tenant_slug, project_id))
    if not response.is_success:
        return ""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    slug = payload.get("slug")
    return slug if isinstance(slug, str) else ""


def fetch_mock_usage(
    client: RestClient,
    tenant_slug: str,
    *,
    project_slug: str,
    version_label: str,
    days: int,
) -> dict[str, Any] | None:
    """Best-effort mock usage summary (``GET /v1/mocks/{tenant}/usage``, SIM-1.5).

    Parameters
    ----------
    client:
        Authenticated REST client.
    tenant_slug:
        Tenant scope for the route.
    project_slug:
        Filters the daily rollups to one project.
    version_label:
        Filters the daily rollups to one version label (e.g. ``1.0.0``).
    days:
        Rollup window in days.

    Returns
    -------
    dict[str, Any] | None
        The ``MockUsageResponse`` payload, or ``None`` when usage is
        unavailable (mock server disabled, older REST service, or a
        malformed body). Never exits the CLI: the issue scope treats usage
        as "when available" data.
    """
    query = urlencode(
        {"days": days, "project_slug": project_slug, "version_label": version_label}
    )
    response = client.get_raw(f"{api_paths.mock_usage(tenant_slug)}?{query}")
    if not response.is_success:
        return None
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def version_usage_request_count(usage: dict[str, Any]) -> int:
    """Sum the filtered daily rollup request counts for one version."""
    rollups = usage.get("dailyRollups")
    if not isinstance(rollups, list):
        return 0
    total = 0
    for rollup in rollups:
        if isinstance(rollup, dict) and isinstance(rollup.get("requestCount"), int):
            total += rollup["requestCount"]
    return total


def emit_mock_status(
    record: dict[str, Any],
    usage: dict[str, Any] | None,
    *,
    days: int,
    json_mode: bool,
) -> None:
    """Print the mock status for one version (human table or stable JSON).

    Parameters
    ----------
    record:
        The raw ``VersionSchema`` payload for the version.
    usage:
        The raw ``MockUsageResponse`` payload, or ``None`` when unavailable.
    days:
        Usage window used for the rollup heading.
    json_mode:
        When ``True`` emit ``{"version": <VersionSchema>, "usage":
        <MockUsageResponse|null>}`` on stdout — a stable envelope of raw API
        payloads for scripting.
    """
    if json_mode:
        emit_json({"version": record, "usage": usage})
        return

    emit_record_table(record, MOCK_RECORD_FIELDS)
    if usage is None:
        return

    typer.echo(f"Usage (last {days} days):")
    typer.echo(f"  Requests (this version): {version_usage_request_count(usage)}")
    monthly = usage.get("monthlyRequestCount")
    quota = usage.get("monthlyQuota")
    if isinstance(monthly, int) and isinstance(quota, int):
        typer.echo(f"  Tenant monthly usage: {monthly} / {quota}")
    rps = usage.get("mockRps")
    if isinstance(rps, (int, float)):
        typer.echo(f"  Rate limit: {rps} rps")


def emit_mock_toggle_result(record: dict[str, Any], *, json_mode: bool) -> None:
    """Print the updated version record after an enable/disable toggle."""
    if json_mode:
        emit_json(record)
        return
    emit_record_table(record, MOCK_RECORD_FIELDS)
