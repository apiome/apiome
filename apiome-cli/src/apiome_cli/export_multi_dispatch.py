"""``apiome export <format>`` over several targets or several items — E1-3 (#6219).

Two shapes of the generic export command run one export job that writes one archive:

* ``--targets openapi,graphql`` with an ``ARTIFACT`` — a **multi-target** job (MFX-39.1): the
  version to ``<format>`` plus every listed target, one folder per target. All-or-nothing: the
  first target that fails fails the job.
* ``--items ID[@VERSION],…`` with no ``ARTIFACT`` — a **batch** job (E1-3): each item (at its
  version, or its latest) to ``<format>`` and any ``--targets``, one folder per item × target.
  Failures are per item.

Both print a per-item outcome table (``--json``: the job's ``result``). Exit codes: ``0`` when
every item completed, :data:`~apiome_cli.exit_codes.EXIT_EXPORT_PARTIAL` (7) when the archive was
written but some items failed, and non-zero (the job's failure code) when every item failed.
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
from apiome_cli.client.export_jobs import (
    download_export_job_artifact,
    filename_from_disposition,
    wait_for_export_job,
)
from apiome_cli.client.export_registry import (
    fetch_export_targets,
    resolve_export_target,
    unknown_export_target_message,
)
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_EXPORT_PARTIAL, EXIT_USAGE
from apiome_cli.export_dispatch import refuse_unavailable_target, write_export_artifact
from apiome_cli.export_output import enforce_export_fidelity_gate
from apiome_cli.export_overlays import format_overlay_summary, load_overlay_files
from apiome_cli.output import emit_json, emit_list_table

__all__ = [
    "MAX_EXPORT_PAIRS",
    "outcome_rows",
    "parse_item_refs",
    "parse_target_list",
    "run_multi_export",
]

#: The REST cap on item × target pairs in one batch export job.
MAX_EXPORT_PAIRS = 100


def parse_target_list(raw: str | None) -> list[str]:
    """Split ``--targets a,b`` into distinct non-blank names, in order."""
    names: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    return names


def parse_item_refs(raw: str | None) -> list[tuple[str, str | None]]:
    """Split ``--items id1,id2@1.0.0`` into ``(item, version)`` pairs (``None`` = latest).

    Raises:
        typer.Exit: :data:`EXIT_USAGE` on an empty entry, an empty ``@version`` or a repeat.
    """
    refs: list[tuple[str, str | None]] = []
    for part in (raw or "").split(","):
        entry = part.strip()
        item, at, version = entry.partition("@")
        item, version = item.strip(), version.strip()
        if not item or (at and not version):
            typer.echo(f"Invalid --items entry {part!r}; expected ITEM or ITEM@VERSION.", err=True)
            raise typer.Exit(EXIT_USAGE)
        ref = (item, version or None)
        if ref in refs:
            typer.echo(f"--items names {entry!r} twice.", err=True)
            raise typer.Exit(EXIT_USAGE)
        refs.append(ref)
    return refs


def outcome_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The per-item outcome rows of a completed multi-target or batch job's ``result``.

    A batch reports ``batch.items`` (item, version, target, state, tier, error); a multi-target job
    reports ``targets`` (every one completed — the job is all-or-nothing).
    """
    batch = result.get("batch")
    if isinstance(batch, Mapping) and isinstance(batch.get("items"), list):
        rows = []
        for item in batch["items"]:
            if not isinstance(item, Mapping):
                continue
            error = item.get("error") if isinstance(item.get("error"), Mapping) else {}
            rows.append(
                {
                    "item": item.get("artifact") or result.get("artifact") or "",
                    "version": item.get("version_label") or item.get("version") or "",
                    "target": item.get("target") or "",
                    "state": item.get("state") or "",
                    "tier": item.get("tier") or "",
                    "detail": error.get("message") or item.get("directory") or "",
                }
            )
        return rows
    rows = []
    for target in result.get("targets") or []:
        if not isinstance(target, Mapping):
            continue
        fidelity = target.get("fidelity") if isinstance(target.get("fidelity"), Mapping) else {}
        summary = fidelity.get("summary") if isinstance(fidelity.get("summary"), Mapping) else {}
        rows.append(
            {
                "item": result.get("artifact") or "",
                "version": result.get("version_label") or "",
                "target": target.get("target") or "",
                "state": "completed",
                "tier": summary.get("tier") or "",
                "detail": target.get("directory") or "",
            }
        )
    return rows


_OUTCOME_COLUMNS = (
    ("Item", "item", None),
    ("Version", "version", None),
    ("Target", "target", None),
    ("State", "state", None),
    ("Fidelity", "tier", None),
    ("Folder / error", "detail", None),
)


def _resolve_targets(
    client: RestClient,
    tenant_slug: str,
    *,
    artifact: str,
    version: str | None,
    names: Sequence[str],
) -> list[str]:
    """Resolve each requested format name to a registry key against ``artifact``'s targets."""
    response = fetch_export_targets(client, tenant_slug, artifact=artifact, version=version)
    registry = response.get("targets")
    if not isinstance(registry, list):
        typer.echo("Export targets response was missing a targets list.", err=True)
        raise typer.Exit(EXIT_ERROR)
    keys: list[str] = []
    for name in names:
        try:
            key = resolve_export_target(name, registry)
        except ValueError:
            typer.echo(unknown_export_target_message(name, registry), err=True)
            raise typer.Exit(EXIT_USAGE) from None
        refuse_unavailable_target(key, registry)
        if key not in keys:
            keys.append(key)
    return keys


def run_multi_export(
    ctx: typer.Context,
    *,
    target_format: str,
    artifact: str | None,
    version: str | None,
    items_raw: str | None,
    targets_raw: str | None,
    out: str | None,
    options: Mapping[str, Any],
    force: bool,
    confirm: bool,
    poll_interval: float,
    export_timeout_override: float | None,
    overlay_paths: Sequence[str] = (),
) -> None:
    """Run a multi-target (``ARTIFACT`` + ``--targets``) or batch (``--items``) export job.

    Args:
        ctx: The Typer context (settings, JSON mode, timeouts).
        target_format: The ``<format>`` the command was invoked as — always the first target.
        artifact: The artifact for a multi-target job (``None`` with ``--items``).
        version: The artifact's version (multi-target only).
        items_raw: The raw ``--items`` value.
        targets_raw: The raw ``--targets`` value (extra targets after ``<format>``).
        out: ``--out``: a directory to unpack into, or a ``.zip`` path.
        options: ``--option`` values; they apply to ``<format>`` only (each other target uses
            its defaults).
        force: Exit 0 even when the fidelity rollup is lossy.
        confirm: Proceed with severe conversions.
        poll_interval: Seconds between status polls.
        export_timeout_override: ``--export-timeout``.
        overlay_paths: ``--overlay`` files (GVM-4.2), applied to the artifact's OpenAPI document
            for every target. Refused with ``--items``: an overlay is written against one source.

    Raises:
        typer.Exit: :data:`EXIT_USAGE` for an inconsistent request, :data:`EXIT_EXPORT_PARTIAL`
            when some batch items failed, or the job's failure code when it failed.
    """
    if out is None or not out.strip() or out.strip() == "-":
        typer.echo("--out is required: a directory to unpack the archive into, or a .zip path.", err=True)
        raise typer.Exit(EXIT_USAGE)
    out = out.strip()
    refs = parse_item_refs(items_raw) if items_raw is not None else None
    if refs is not None and version is not None:
        typer.echo("--version does not apply with --items; pin one with ITEM@VERSION.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if refs is not None and overlay_paths:
        typer.echo("--overlay applies to one ARTIFACT; it cannot be combined with --items.", err=True)
        raise typer.Exit(EXIT_USAGE)
    overlays = load_overlay_files(overlay_paths)
    names = [target_format, *[n for n in parse_target_list(targets_raw) if n != target_format]]
    if refs is not None and len(refs) * len(names) > MAX_EXPORT_PAIRS:
        typer.echo(
            f"One export runs at most {MAX_EXPORT_PAIRS} item × target pairs; "
            f"this names {len(refs) * len(names)}.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(settings, timeout=timeout_from_context(ctx), verify=not insecure_from_context(ctx))
    tenant_slug = resolve_tenant_slug(settings, client, tenant_override=None)

    body: dict[str, Any] = {"confirm": confirm}
    if refs is not None:
        resolved = [(str(resolve_project_uuid(client, tenant_slug, item)), ver) for item, ver in refs]
        body["items"] = [{"artifact": a, **({"version": v} if v else {})} for a, v in resolved]
        first_artifact, first_version = resolved[0]
    else:
        first_artifact, first_version = str(resolve_project_uuid(client, tenant_slug, artifact or "")), version
        body["artifact"] = first_artifact
        if version is not None:
            body["version"] = version
    keys = _resolve_targets(client, tenant_slug, artifact=first_artifact, version=first_version, names=names)
    body["targets"] = [
        {"target": key, **({"options": dict(options)} if options and index == 0 else {})}
        for index, key in enumerate(keys)
    ]
    if overlays:
        body["overlays"] = overlays

    accepted = client.post(api_paths.export_jobs(tenant_slug), json=body).json()
    job_id = accepted.get("job_id") if isinstance(accepted, dict) else None
    if not isinstance(job_id, str) or not job_id:
        typer.echo("Export job acceptance response missing job_id.", err=True)
        raise typer.Exit(EXIT_ERROR)
    timeout = export_timeout_override if export_timeout_override is not None else import_timeout_from_context(ctx)
    status = wait_for_export_job(
        client,
        tenant_slug,
        job_id,
        poll_interval=poll_interval,
        timeout=timeout,
        no_progress=no_progress_from_context(ctx),
    )
    result = status.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("download_path"), str):
        typer.echo("Completed export job missing its result or download_path.", err=True)
        raise typer.Exit(EXIT_ERROR)

    payload, content_type, disposition = download_export_job_artifact(
        client, download_path=result["download_path"], tenant_slug=tenant_slug, job_id=job_id
    )
    _written, effective_out = write_export_artifact(
        payload,
        out=out,
        content_type=content_type,
        files=None,
        disposition_filename=filename_from_disposition(disposition),
    )

    if json_mode_from_context(ctx):
        emit_json({"job_id": job_id, "output": effective_out, "result": result})
    else:
        emit_list_table(outcome_rows(result), _OUTCOME_COLUMNS, min_width=160)
        for line in format_overlay_summary(result.get("overlay")):
            typer.echo(line, err=True)
        typer.echo(f"Wrote {effective_out}", err=True)

    batch = result.get("batch")
    if isinstance(batch, Mapping) and int(batch.get("failed_count") or 0) > 0:
        typer.echo(
            f"{batch.get('failed_count')} of {batch.get('item_count')} items failed; "
            "the archive holds the rest.",
            err=True,
        )
        raise typer.Exit(EXIT_EXPORT_PARTIAL)
    rollup = result.get("fidelity_rollup")
    if isinstance(rollup, Mapping):
        enforce_export_fidelity_gate({"summary": {"tier": rollup.get("tier")}}, force=force)
