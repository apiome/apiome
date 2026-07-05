"""Emitter-registry export commands (MFX-9.4).

``apiome export`` is the client for the multi-format emitter registry — the inverse of ``import``.
``export targets`` enumerates the registered emitters and their per-source fidelity for a version
(``GET /v1/export/{tenant}/targets``); ``export openapi`` writes the OpenAPI document for a version
and surfaces the honest fidelity report for that export.

There is no REST endpoint that emits an artifact through the Emitter SPI, so the document bytes come
from the existing browse reconstruction (``GET /v1/schema/...`` — the same source ``spec export``
uses) while the fidelity report comes from the emitter registry's dry-run preview
(``POST /v1/export/{tenant}/preview``). A lossy export exits non-zero (so a CI export gate fails
loudly) unless ``--force`` is given; the document is written either way, mirroring ``convert``.
"""

from __future__ import annotations

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client.browse_scope import (
    resolve_browse_export_scope,
    resolve_tenant_slug,
)
from apiome_cli.client.export_document import fetch_export_document
from apiome_cli.client.export_registry import (
    fetch_export_preview,
    fetch_export_targets,
    preview_fidelity,
)
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.client.spec_download import SpecSerialization, fetch_browse_spec
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.export_output import (
    EXPORT_TARGET_COLUMNS,
    format_export_fidelity_summary,
    is_lossy,
    target_rows,
)
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, emit_list_table
from apiome_cli.spec_output import (
    SpecExportMetadata,
    build_spec_export_metadata,
    emit_download_metadata,
    write_document_bytes,
)

app = typer.Typer(
    name="export",
    help="Export a version to a target format via the emitter registry.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

# The registry key + format for the reference OpenAPI 3.1 emitter (apiome-rest OpenApiEmitter).
_OPENAPI_TARGET = "openapi"

# The registry key for the AsyncAPI 3.1 emitter (apiome-rest AsyncApiEmitter, MFX-11.5).
_ASYNCAPI_TARGET = "asyncapi"

_JSON_STDOUT_NOTE = (
    "With --output -, document bytes are written to stdout; the fidelity summary and --json "
    "metadata are written to stderr so stdout stays byte-safe for pipelines."
)


@app.callback(invoke_without_command=True)
def export_group(ctx: typer.Context) -> None:
    """Emitter-registry export commands."""
    group_callback_without_subcommand(ctx)


def _export_client(ctx: typer.Context) -> RestClient:
    """Authenticated REST client for the tenant-scoped export surface."""
    settings = settings_from_context(ctx)
    return RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )


def _parse_serialization(*, yaml_flag: bool, accept: str | None) -> SpecSerialization:
    """Resolve the wire serialization from ``--yaml`` / ``--accept`` (mirrors ``spec export``)."""
    if yaml_flag and accept is not None:
        typer.echo("Use only one of --yaml or --accept for serialization.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if yaml_flag:
        return "yaml"
    if accept is None:
        return "json"
    normalized = accept.strip().lower()
    if normalized in ("json", "application/json"):
        return "json"
    if normalized in ("yaml", "yml", "application/yaml", "text/yaml"):
        return "yaml"
    typer.echo("--accept must be json or yaml.", err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command("openapi", help=f"Export a version as OpenAPI + a fidelity report. {_JSON_STDOUT_NOTE}")
def export_openapi(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Destination file path, or - for stdout (document bytes only).",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant UUID or slug (overrides APIOME_TENANT_ID).",
    ),
    yaml_serialization: bool = typer.Option(
        False,
        "--yaml",
        help="Request YAML serialization (default JSON). Alias for --accept yaml.",
    ),
    accept: str | None = typer.Option(
        None,
        "--accept",
        help="Response serialization: json or yaml (default json).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Write and exit 0 even when the export loses fidelity (lossy/types-only).",
    ),
) -> None:
    """Export a version as OpenAPI and surface the emitter registry's fidelity report."""
    output = output.strip()
    if not output:
        typer.echo("--output cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)

    serialization = _parse_serialization(yaml_flag=yaml_serialization, accept=accept)
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = _export_client(ctx)
    tenant_slug = resolve_tenant_slug(settings, client, tenant_override=tenant)

    # The artifact (project) id the fidelity preview keys on; also drives browse-scope resolution.
    project_id = resolve_project_uuid(client, tenant_slug, project)
    scope = resolve_browse_export_scope(
        client,
        settings,
        project_ref=str(project_id),
        version_ref=version,
        tenant_override=tenant,
    )

    download = fetch_browse_spec(
        client,
        scope,
        spec_format="openapi",
        serialization=serialization,
    )
    write_document_bytes(download.body, output)

    preview = fetch_export_preview(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
        target=_OPENAPI_TARGET,
    )
    fidelity = preview_fidelity(preview)

    json_mode = json_mode_from_context(ctx)
    metadata = build_spec_export_metadata(
        download=download,
        scope_source_openapi_version=None,
        scope_fidelity_target=_OPENAPI_TARGET,
        fidelity=_fidelity_metadata(fidelity),
        output=output,
    )
    emit_download_metadata(metadata, json_mode=json_mode)

    # Human fidelity summary is a diagnostic → stderr (keeps stdout byte-safe under --output -).
    if not json_mode:
        for line in format_export_fidelity_summary(fidelity, target=_OPENAPI_TARGET):
            typer.echo(line, err=True)

    if is_lossy(fidelity) and not force:
        typer.echo(
            "Lossy export — the OpenAPI document does not carry every source construct. "
            "Re-run with --force to accept.",
            err=True,
        )
        raise typer.Exit(EXIT_ERROR)


@app.command(
    "asyncapi",
    help=f"Export a version as AsyncAPI 3 + a fidelity report. {_JSON_STDOUT_NOTE}",
)
def export_asyncapi(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Destination file path, or - for stdout (document bytes only).",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant UUID or slug (overrides APIOME_TENANT_ID).",
    ),
    yaml_serialization: bool = typer.Option(
        False,
        "--yaml",
        help="Request YAML serialization (default JSON). Alias for --accept yaml.",
    ),
    accept: str | None = typer.Option(
        None,
        "--accept",
        help="Response serialization: json or yaml (default json).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Write and exit 0 even when the export loses fidelity (lossy/types-only).",
    ),
) -> None:
    """Export a version as AsyncAPI 3 and surface the emitter registry's fidelity report.

    Unlike ``export openapi`` — whose bytes come from the OpenAPI browse reconstruction — AsyncAPI
    is produced through the Emitter SPI (``POST /export/{tenant}/document``); the honest fidelity
    report still comes from the dry-run preview (``POST /export/{tenant}/preview``). A REST/RPC
    source reframes onto channels and therefore exports *lossy* — a non-zero exit unless ``--force``
    — while a native event source round-trips lossless.
    """
    output = output.strip()
    if not output:
        typer.echo("--output cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)

    serialization = _parse_serialization(yaml_flag=yaml_serialization, accept=accept)
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = _export_client(ctx)
    tenant_slug = resolve_tenant_slug(settings, client, tenant_override=tenant)

    # The artifact (project) id both the emit and the fidelity preview key on.
    project_id = resolve_project_uuid(client, tenant_slug, project)

    document = fetch_export_document(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
        target=_ASYNCAPI_TARGET,
        serialization=serialization,
    )
    write_document_bytes(document.body, output)

    preview = fetch_export_preview(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
        target=_ASYNCAPI_TARGET,
    )
    fidelity = preview_fidelity(preview)

    json_mode = json_mode_from_context(ctx)
    metadata = SpecExportMetadata(
        output=output,
        bytes_written=len(document.body),
        content_type=document.content_type,
        format=_ASYNCAPI_TARGET,
        serialization=serialization,
        filename=document.filename,
        fidelity_target=_ASYNCAPI_TARGET,
        fidelity=_fidelity_metadata(fidelity),
    )
    emit_download_metadata(metadata, json_mode=json_mode)

    # Human fidelity summary is a diagnostic → stderr (keeps stdout byte-safe under --output -).
    if not json_mode:
        for line in format_export_fidelity_summary(fidelity, target=_ASYNCAPI_TARGET):
            typer.echo(line, err=True)

    if is_lossy(fidelity) and not force:
        typer.echo(
            "Lossy export — the AsyncAPI document does not carry every source construct "
            "(a REST/RPC source is reframed onto channels). Re-run with --force to accept.",
            err=True,
        )
        raise typer.Exit(EXIT_ERROR)


def _fidelity_metadata(fidelity: dict[str, object] | None) -> dict[str, object] | None:
    """Fold the fidelity envelope's coarse badge into the export metadata payload.

    Keeps the ``fidelity`` metadata field compact (``status`` + preserved-% + per-kind counts) so
    ``--json`` metadata carries the tier without embedding the whole per-construct report.
    """
    if not isinstance(fidelity, dict):
        return None
    summary = fidelity.get("summary")
    if not isinstance(summary, dict):
        return None
    payload: dict[str, object] = {"status": summary.get("tier")}
    for key in ("preserved_percent", "dropped", "approximated", "synthesized"):
        if key in summary:
            payload[key] = summary[key]
    return payload


@app.command("targets", help="List the emitter registry targets + fidelity for a version.")
def export_targets(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Version UUID, slug, or label (default: latest revision).",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant UUID or slug (overrides APIOME_TENANT_ID).",
    ),
) -> None:
    """List the registered emitters and their per-source fidelity for a version."""
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = _export_client(ctx)
    tenant_slug = resolve_tenant_slug(settings, client, tenant_override=tenant)

    project_id = resolve_project_uuid(client, tenant_slug, project)
    response = fetch_export_targets(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
    )

    if json_mode_from_context(ctx):
        emit_json(response)
        return

    targets = response.get("targets")
    rows = target_rows(targets) if isinstance(targets, list) else []
    emit_list_table(
        rows,
        list(EXPORT_TARGET_COLUMNS),
        empty_message="No export targets available for this version.",
        min_width=100,
    )
