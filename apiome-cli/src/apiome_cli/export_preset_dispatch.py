"""``apiome export --preset NAME ARTIFACT --out PATH`` — MFX-39.3 (#4335).

Runs one export job from a saved preset: the job is submitted with ``"preset"``, and the REST layer fills
in the preset's targets, their options and its delivery profile (``POST /v1/export/{tenant}/jobs``). The
source is the command's own — an ``ARTIFACT`` (with ``--version``) or ``--items`` for a batch.

A one-target preset writes its file (or bundle) as ``apiome export <format>`` does; a multi-target preset
or a batch writes one archive with a folder per target and prints the per-item outcome table. Deliveries
— the preset's profile and any ``--deliver`` — print after the download. Exit codes follow the multi
export: ``7`` when a batch wrote the archive but some items failed, ``1`` when a delivery failed, and the
fidelity gate (``--force``) as every export.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import typer

from apiome_cli.cli_context import (
    import_timeout_from_context,
    insecure_from_context,
    json_mode_from_context,
    no_progress_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.browse_scope import resolve_tenant_slug
from apiome_cli.client.export_delivery_profiles import report_job_deliveries, resolve_profile_ids
from apiome_cli.client.export_jobs import (
    download_export_job_artifact,
    filename_from_disposition,
    wait_for_export_job,
)
from apiome_cli.client.export_presets import get_preset
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_EXPORT_PARTIAL, EXIT_USAGE
from apiome_cli.export_dispatch import write_export_artifact
from apiome_cli.export_multi_dispatch import _OUTCOME_COLUMNS, outcome_rows, parse_item_refs
from apiome_cli.export_output import enforce_export_fidelity_gate
from apiome_cli.export_overlays import load_overlay_files
from apiome_cli.output import emit_json, emit_list_table

__all__ = ["run_preset_export"]


def _fidelity_tier(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """The fidelity the gate judges: a single target's report, else the multi-target rollup's tier."""
    fidelity = result.get("fidelity")
    if isinstance(fidelity, Mapping):
        return dict(fidelity)
    rollup = result.get("fidelity_rollup")
    if isinstance(rollup, Mapping):
        return {"summary": {"tier": rollup.get("tier")}}
    return None


def run_preset_export(
    ctx: typer.Context,
    *,
    preset: str,
    artifact: str | None,
    version: str | None,
    items_raw: str | None,
    out: str | None,
    force: bool,
    confirm: bool,
    poll_interval: float,
    export_timeout_override: float | None,
    overlay_paths: Sequence[str] = (),
    deliver_refs: Sequence[str] = (),
) -> None:
    """Run one export job from a saved preset and write what it produced.

    Args:
        ctx: The Typer context (settings, JSON mode, timeouts).
        preset: The preset's name or id.
        artifact: The source artifact (``None`` with ``--items``).
        version: The artifact's version (not with ``--items``).
        items_raw: ``--items`` (``ID[@VERSION],…``) for a batch.
        out: A file or directory for one target, a directory or ``.zip`` for several.
        force: Exit 0 even when the export is lossy.
        confirm: Proceed with severe conversions.
        poll_interval: Seconds between status polls.
        export_timeout_override: ``--export-timeout``.
        overlay_paths: ``--overlay`` files (one ARTIFACT only).
        deliver_refs: More delivery profiles (names or ids), after the preset's own.

    Raises:
        typer.Exit: :data:`EXIT_USAGE` for an inconsistent request, :data:`EXIT_EXPORT_PARTIAL` when some
            batch items failed, :data:`EXIT_ERROR` when a delivery failed, or the job's failure code.
    """
    if (artifact is None) == (items_raw is None):
        typer.echo("Name an ARTIFACT or --items (not both) to run the preset on.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if out is None or not out.strip():
        typer.echo("--out is required (file, directory, '-' for stdout, or .zip).", err=True)
        raise typer.Exit(EXIT_USAGE)
    refs = parse_item_refs(items_raw) if items_raw is not None else None
    if refs is not None and (version is not None or overlay_paths):
        typer.echo("--version and --overlay apply to one ARTIFACT; with --items pin versions as ITEM@VERSION.",
                   err=True)
        raise typer.Exit(EXIT_USAGE)

    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, timeout=timeout_from_context(ctx), verify=not insecure_from_context(ctx))
    tenant_slug = resolve_tenant_slug(settings, client, tenant_override=None)

    stored = get_preset(client, tenant_slug, preset)  # exits 404 for an unknown preset
    multi = len(stored.get("targets") or []) > 1 or refs is not None
    if multi and out.strip() == "-":
        typer.echo("A multi-target preset or a batch writes an archive: --out must be a directory or .zip.",
                   err=True)
        raise typer.Exit(EXIT_USAGE)

    body: dict[str, Any] = {"preset": str(stored.get("id") or preset), "confirm": confirm}
    if refs is not None:
        body["items"] = [{"artifact": str(resolve_project_uuid(client, tenant_slug, item)),
                          **({"version": ver} if ver else {})} for item, ver in refs]
    else:
        body["artifact"] = str(resolve_project_uuid(client, tenant_slug, artifact or ""))
        if version is not None:
            body["version"] = version
    overlays = load_overlay_files(overlay_paths)
    if overlays:
        body["overlays"] = overlays
    extra_profiles = resolve_profile_ids(client, tenant_slug, deliver_refs)
    if extra_profiles:
        body["delivery_profiles"] = extra_profiles
    expected = len({*extra_profiles, *([stored["deliveryProfileId"]] if stored.get("deliveryProfileId") else [])})

    accepted = client.post(api_paths.export_jobs(tenant_slug), json=body).json()
    job_id = accepted.get("job_id") if isinstance(accepted, dict) else None
    if not isinstance(job_id, str) or not job_id:
        typer.echo("Export job acceptance response missing job_id.", err=True)
        raise typer.Exit(EXIT_ERROR)
    timeout = export_timeout_override if export_timeout_override is not None else import_timeout_from_context(ctx)
    status = wait_for_export_job(client, tenant_slug, job_id, poll_interval=poll_interval, timeout=timeout,
                                 no_progress=no_progress_from_context(ctx))
    result = status.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("download_path"), str):
        typer.echo("Completed export job missing its result or download_path.", err=True)
        raise typer.Exit(EXIT_ERROR)

    payload, content_type, disposition = download_export_job_artifact(
        client, download_path=result["download_path"], tenant_slug=tenant_slug, job_id=job_id)
    files = result.get("files")
    _written, effective_out = write_export_artifact(
        payload, out=out.strip(), content_type=content_type,
        files=None if multi or not isinstance(files, list) else files,
        disposition_filename=filename_from_disposition(disposition),
    )

    if json_mode_from_context(ctx):
        emit_json({"job_id": job_id, "preset": stored.get("name"), "output": effective_out, "result": result})
    else:
        if multi:
            emit_list_table(outcome_rows(result), _OUTCOME_COLUMNS, min_width=160)
        typer.echo(f"Exported with preset {stored.get('name')!r}; wrote {effective_out}", err=True)
    report_job_deliveries(client, tenant_slug, job_id, expected=expected, poll_interval=poll_interval,
                          timeout=timeout)

    batch = result.get("batch")
    if isinstance(batch, Mapping) and int(batch.get("failed_count") or 0) > 0:
        typer.echo(f"{batch.get('failed_count')} of {batch.get('item_count')} items failed; the archive holds the rest.",
                   err=True)
        raise typer.Exit(EXIT_EXPORT_PARTIAL)
    enforce_export_fidelity_gate(_fidelity_tier(result), force=force)
