"""MCP ``export.targets`` and ``version.export`` tools — MFX-40.1 (#4339).

Two **generic** export tools: any emitter registered in apiome-rest is exportable over MCP with no
per-format tool code (the per-format tools of #2866/#2867 are not needed).

* ``export.targets`` — for an artifact version, every registered export target with its per-source
  fidelity tier, options schema and defaults (the answer of ``GET /v1/export/{tenant}/targets``).
* ``version.export`` — runs an export job for a target key and options, and returns the emitted files
  (inline when small, otherwise a REST download reference) together with the structured fidelity report:
  the tier, the per-construct ``LossinessReport`` and the advisory, plus the transcoding guard. A job still
  running after ``APIOME_MCP_EXPORT_WAIT_SECONDS`` answers ``state: running`` with its ``jobId``; calling
  ``version.export`` again with that ``job_id`` collects it.

  A conversion that loses fidelity needs ``allow_lossy=true`` (MFX-40.2, #4340; the CLI ``--force``):
  without it the tool answers ``state: blocked`` with the report and the advisory and emits nothing.
  ``advisory`` is the canonical MFX-2.4 advisory string — the words the UI, browse and the CLI show.

Both require an MCP API key. They export within the key's own tenant, and only an artifact the key's
scope allows. The emitter registry and the export job engine live in apiome-rest; these tools call its
internal ``/v1/internal/mcp/export`` routes with the shared internal service token
(``APIOME_MCP_REST_INTERNAL_URL``, ``APIOME_MCP_REST_INTERNAL_SERVICE_TOKEN``).
"""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.settings import Settings, get_settings

__all__ = ["build_export_targets_response", "build_version_export_response"]

#: Seconds added to the export wait for the HTTP round trip itself.
_HTTP_MARGIN_SECONDS = 30.0


def _require_in_scope(auth_ctx: McpAuthContext, artifact: str) -> None:
    """Refuse an artifact outside the key's scope (the export runs in the key's tenant)."""
    if not artifact or not artifact.strip():
        raise ToolError("artifact is required (the artifact / project id to export).")
    if not auth_ctx.scope.allows(str(auth_ctx.tenant_id), artifact.strip()):
        raise ToolError("This MCP API key's scope does not include that artifact.")


def _error_message(response: httpx.Response) -> str:
    """The REST refusal's message, in one line."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return response.text[:500] or f"HTTP {response.status_code}"
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    if isinstance(detail, list):  # FastAPI validation errors
        return "; ".join(str(item.get("msg", item)) for item in detail if isinstance(item, dict)) or str(detail)
    return str(detail or f"HTTP {response.status_code}")


async def _post(
    path: str,
    body: dict[str, Any],
    *,
    settings: Settings,
    wait_seconds: float,
    transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    """POST one internal export route and return its JSON, or raise a ``ToolError`` naming the problem."""
    base = (settings.rest_internal_url or "").strip().rstrip("/")
    token = settings.rest_internal_service_token.get_secret_value() if settings.rest_internal_service_token else ""
    if not base or not token:
        raise ToolError(
            "Export over MCP is not configured on this server: set APIOME_MCP_REST_INTERNAL_URL and "
            "APIOME_MCP_REST_INTERNAL_SERVICE_TOKEN (apiome-rest's INTERNAL_SERVICE_TOKEN)."
        )
    timeout = httpx.Timeout(wait_seconds + _HTTP_MARGIN_SECONDS, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(f"{base}{path}", json=body, headers={"X-Internal-Service-Token": token})
    except httpx.HTTPError as exc:
        raise ToolError(f"apiome-rest could not be reached for the export: {exc.__class__.__name__}.") from exc
    if response.status_code >= 400:
        raise ToolError(f"Export refused ({response.status_code}): {_error_message(response)}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ToolError("apiome-rest answered the export with an unexpected payload.")
    return payload


async def build_export_targets_response(
    *,
    auth_ctx: McpAuthContext,
    artifact: str,
    version: str | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Every registered export target for an artifact version, with its fidelity tier.

    Args:
        auth_ctx: The authenticated MCP key.
        artifact: The artifact (project / catalog item) id.
        version: A revision id or version label; the latest revision when omitted.
        settings: Overrides the process settings (tests).
        transport: An ``httpx`` transport (tests).

    Returns:
        ``{artifact, version, version_record_id, version_label, targets: [{descriptor, fidelity,
        options_schema, default_options, …}]}``.

    Raises:
        ToolError: For an artifact outside the key's scope, export not configured, or a REST refusal.
    """
    _require_in_scope(auth_ctx, artifact)
    resolved = settings or get_settings()
    return await _post(
        "/v1/internal/mcp/export/targets",
        {"tenantId": str(auth_ctx.tenant_id), "artifact": artifact.strip(), "version": version},
        settings=resolved,
        wait_seconds=0,
        transport=transport,
    )


async def build_version_export_response(
    *,
    auth_ctx: McpAuthContext,
    artifact: str | None = None,
    target: str | None = None,
    version: str | None = None,
    options: dict[str, Any] | None = None,
    confirm: bool = False,
    allow_lossy: bool = False,
    job_id: str | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Export an artifact version to a target (or collect a running export), with its fidelity report.

    Args:
        auth_ctx: The authenticated MCP key.
        artifact: The artifact id (required to start an export).
        target: Any registered target key from ``export.targets`` (required to start an export).
        version: A revision id or label; the latest revision when omitted.
        options: The target's emit options (validated against its schema).
        confirm: Proceed with a severe conversion the transcoding guard would otherwise refuse.
        allow_lossy: Emit even when the conversion loses fidelity; otherwise a lossy conversion answers
            ``state: blocked`` with the report and the advisory, and nothing is emitted.
        job_id: Collect an export a previous call left ``running``, instead of starting one.
        settings: Overrides the process settings (tests).
        transport: An ``httpx`` transport (tests).

    Returns:
        ``{jobId, state (blocked / queued / running / completed / failed / canceled), advisory,
        fidelity: {summary, report, advisory, …}, guard, files: [{path, mediaType,
        sizeBytes, content?}], contentInline, downloadPath, error}``.

    Raises:
        ToolError: For a missing argument, an artifact outside the key's scope, export not configured,
            or a REST refusal (unknown target, invalid options, …).
    """
    resolved = settings or get_settings()
    if job_id:
        body: dict[str, Any] = {"tenantId": str(auth_ctx.tenant_id), "jobId": job_id}
    else:
        _require_in_scope(auth_ctx, artifact or "")
        if not target or not target.strip():
            raise ToolError("target is required: any target key export.targets lists (e.g. openapi-3.1).")
        body = {
            "tenantId": str(auth_ctx.tenant_id),
            "artifact": (artifact or "").strip(),
            "version": version,
            "target": target.strip(),
            "options": options,
            "confirm": bool(confirm),
            "allowLossy": bool(allow_lossy),
        }
    body["waitSeconds"] = resolved.export_wait_seconds
    result = await _post(
        "/v1/internal/mcp/export/run",
        body,
        settings=resolved,
        wait_seconds=float(resolved.export_wait_seconds),
        transport=transport,
    )
    # A collected job names its artifact only now: a project-limited key may not read another project's.
    exported = result.get("artifact")
    if job_id and exported and not auth_ctx.scope.allows(str(auth_ctx.tenant_id), str(exported)):
        raise ToolError("This MCP API key's scope does not include that export's artifact.")
    return result
