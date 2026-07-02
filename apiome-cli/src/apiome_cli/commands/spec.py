"""Reconstructed spec export."""

from __future__ import annotations

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client.browse_scope import resolve_browse_export_scope
from apiome_cli.client.http import RestClient
from apiome_cli.client.spec_download import (
    SpecFormat,
    SpecSerialization,
    fetch_browse_spec,
)
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.spec_output import (
    build_spec_export_metadata,
    emit_download_metadata,
    write_document_bytes,
)

app = typer.Typer(
    name="spec",
    help="Export reconstructed OpenAPI/Arazzo specs.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_JSON_STDOUT_NOTE = (
    "With --output -, document bytes are written to stdout; --json metadata is written to stderr "
    "so stdout stays byte-safe for pipelines."
)


@app.callback(invoke_without_command=True)
def spec_group(ctx: typer.Context) -> None:
    """Spec export commands."""
    group_callback_without_subcommand(ctx)


def _export_client(ctx: typer.Context) -> RestClient:
    """REST client for browse spec export (optional API key for protected versions)."""
    settings = settings_from_context(ctx)
    return RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )


def _parse_spec_format(value: str) -> SpecFormat:
    normalized = value.strip().lower()
    if normalized in ("openapi", "arazzo"):
        return normalized  # type: ignore[return-value]
    typer.echo("format must be openapi or arazzo.", err=True)
    raise typer.Exit(EXIT_USAGE)


def _parse_serialization(*, yaml_flag: bool, accept: str | None) -> SpecSerialization:
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


@app.command("export", help=f"Export reconstructed OpenAPI or Arazzo. {_JSON_STDOUT_NOTE}")
def export_spec(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="Project UUID or slug."),
    version: str = typer.Option(..., "--version", help="Version UUID, slug, or label."),
    spec_format: str = typer.Option(
        "openapi",
        "--format",
        help="Export format: openapi or arazzo.",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Destination file path, or - for stdout (document bytes only).",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant UUID or slug (overrides APIOME_TENANT_ID). Required for browse export.",
    ),
    yaml_serialization: bool = typer.Option(
        False,
        "--yaml",
        help="Request YAML serialization (default JSON). Alias for --accept yaml.",
    ),
    accept: str | None = typer.Option(
        None,
        "--accept",
        help="Response serialization: json or yaml (REST accept query; default json).",
    ),
) -> None:
    """Export a reconstructed OpenAPI or Arazzo document."""
    output = output.strip()
    if not output:
        typer.echo("--output cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)

    normalized_format = _parse_spec_format(spec_format)
    serialization = _parse_serialization(yaml_flag=yaml_serialization, accept=accept)
    client = _export_client(ctx)
    settings = settings_from_context(ctx)
    scope = resolve_browse_export_scope(
        client,
        settings,
        project_ref=project,
        version_ref=version,
        tenant_override=tenant,
    )
    download = fetch_browse_spec(
        client,
        scope,
        spec_format=normalized_format,
        serialization=serialization,
    )
    write_document_bytes(download.body, output)

    metadata = build_spec_export_metadata(
        download=download,
        scope_source_openapi_version=None,
        scope_fidelity_target=None,
        fidelity=None,
        output=output,
    )
    emit_download_metadata(metadata, json_mode=json_mode_from_context(ctx))


@app.command("download-original", help=f"Download original import bytes. {_JSON_STDOUT_NOTE}")
def download_original(
    ctx: typer.Context,
    import_id: str = typer.Option(
        ...,
        "--import-id",
        help="Project version UUID that owned the original import artifact.",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Destination file path, or - for stdout (artifact bytes only).",
    ),
) -> None:
    """Download the byte-identical original import artifact (not exposed on /v1 REST)."""
    del ctx, import_id, output
    typer.echo(
        "Downloading original import artifacts is not supported via the /v1 REST API yet.",
        err=True,
    )
    raise typer.Exit(EXIT_USAGE)
