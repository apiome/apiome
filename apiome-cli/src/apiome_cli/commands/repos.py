"""Tenant repository list and file inspection commands (Tier 2 API key auth)."""

from __future__ import annotations

from uuid import UUID

import typer

from apiome_cli.cli_context import (
    insecure_from_context,
    json_mode_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.repos_files import (
    build_file_list_query_params,
    emit_repository_files_table,
)
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    ListColumn,
    RecordField,
    emit_json,
    emit_list_table,
    emit_record_response,
)

app = typer.Typer(
    name="repos",
    help="List tenant Git repositories and inspect repository files.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_NOT_SUPPORTED = "This repository command is not supported via the /v1 REST API yet."

_REPOSITORY_PROVIDERS = frozenset({"github", "gitlab", "bitbucket", "public_url"})
_REPOSITORY_STATUSES = frozenset({"pending", "scanning", "ready", "error", "archived"})


@app.callback(invoke_without_command=True)
def repos_group(ctx: typer.Context) -> None:
    """Repositories command group."""
    group_callback_without_subcommand(ctx)


def _scoped_client(ctx: typer.Context) -> tuple[RestClient, str]:
    settings = settings_from_context(ctx)
    require_api_key(settings)
    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = require_tenant_slug(settings, client)
    return client, tenant_slug


def _json_output(ctx: typer.Context, output_format: str | None) -> bool:
    if output_format == "json":
        return True
    if output_format is not None and output_format != "table":
        msg = "--format must be 'table' or 'json'."
        raise typer.BadParameter(msg)
    return json_mode_from_context(ctx)


def _normalize_provider_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _REPOSITORY_PROVIDERS:
        return normalized
    allowed = ", ".join(sorted(_REPOSITORY_PROVIDERS))
    msg = f"--provider must be one of: {allowed}."
    raise typer.BadParameter(msg)


def _normalize_status_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _REPOSITORY_STATUSES:
        return normalized
    allowed = ", ".join(sorted(_REPOSITORY_STATUSES))
    msg = f"--status must be one of: {allowed}."
    raise typer.BadParameter(msg)


def _format_optional_int(value: object) -> str:
    return "" if value is None else str(value)


def _not_supported() -> None:
    typer.echo(_NOT_SUPPORTED, err=True)
    raise typer.Exit(EXIT_USAGE)


_REPO_LIST_COLUMNS: tuple[ListColumn, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Provider", "provider", None),
    ("Status", "status", None),
    ("Branch", "default_branch", None),
    ("Visibility", "visibility", None),
    ("Files", "total_files", _format_optional_int),
    ("Last scanned", "last_scanned_at", None),
)

_REPO_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Name", "name", None),
    ("Provider", "provider", None),
    ("Status", "status", None),
    ("Branch", "default_branch", None),
    ("Visibility", "visibility", None),
)


@app.command("list")
def list_repositories(
    ctx: typer.Context,
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Filter by Git provider: github, gitlab, bitbucket, or public_url.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter by lifecycle status: pending, scanning, ready, error, or archived.",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Case-insensitive substring match on repository display name.",
    ),
    output_format: str | None = typer.Option(
        None,
        "--format",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """List tenant repositories (GET /v1/tenants/{tenant_slug}/repositories)."""
    json_mode = _json_output(ctx, output_format)
    client, tenant_slug = _scoped_client(ctx)

    query_params: list[tuple[str, str]] = []
    provider_filter = _normalize_provider_filter(provider)
    if provider_filter is not None:
        query_params.append(("provider", provider_filter))
    status_filter = _normalize_status_filter(status)
    if status_filter is not None:
        query_params.append(("status", status_filter))
    if name is not None and name.strip():
        query_params.append(("name", name.strip()))

    items, total = fetch_list(
        client,
        api_paths.tenant_repositories(tenant_slug),
        params=query_params or None,
    )
    if json_mode:
        emit_json({"total": total, "items": items})
    else:
        emit_list_table(items, _REPO_LIST_COLUMNS, total=total)


@app.command("show")
def show_repository(
    ctx: typer.Context,
    repository_id: UUID = typer.Argument(..., help="Repository UUID."),
    output_format: str | None = typer.Option(
        None,
        "--format",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """Fetch one repository (GET /v1/tenants/{tenant_slug}/repositories/{id})."""
    json_mode = _json_output(ctx, output_format)
    client, tenant_slug = _scoped_client(ctx)
    response = client.get(api_paths.tenant_repository(tenant_slug, repository_id))
    payload = response.json()
    if json_mode:
        emit_json(payload)
        return
    emit_record_response(payload, _REPO_RECORD_FIELDS, json_mode=False)


@app.command("files")
def list_repository_files(
    ctx: typer.Context,
    repository_id: str = typer.Argument(
        ...,
        help="Repository UUID whose files to list.",
    ),
    glob: str | None = typer.Option(
        None,
        "--glob",
        help="Comma-separated glob patterns on repository-relative paths.",
    ),
    regex: str | None = typer.Option(
        None,
        "--regex",
        help="POSIX regular expression on repository-relative paths.",
    ),
    preset: str | None = typer.Option(
        None,
        "--preset",
        help="Files-tab preset filter.",
    ),
    detected_kind: str | None = typer.Option(
        None,
        "--detected-kind",
        help="Exact match on detected_kind.",
    ),
    importable: bool | None = typer.Option(
        None,
        "--importable/--not-importable",
        help="Filter by importable verdict.",
    ),
    output_format: str | None = typer.Option(
        None,
        "--format",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """List repository files (GET /v1/tenants/{tenant_slug}/repositories/{id}/files)."""
    json_mode = _json_output(ctx, output_format)
    client, tenant_slug = _scoped_client(ctx)
    query_params = build_file_list_query_params(
        glob=glob,
        regex=regex,
        preset=preset,
        detected_kind=detected_kind,
        importable=importable,
    )
    items, total = fetch_list(
        client,
        api_paths.tenant_repository_files(tenant_slug, repository_id),
        params=query_params or None,
    )
    if json_mode:
        emit_json({"total": total, "items": items})
    else:
        emit_repository_files_table(items, total=total, show_closure=False)


@app.command("content")
def get_repository_file_content(
    ctx: typer.Context,
    repository_id: str = typer.Argument(..., help="Repository UUID."),
    file_id: str = typer.Argument(..., help="Repository file UUID."),
    output: str = typer.Option(
        "-",
        "--output",
        "-o",
        help="Destination file path, or - for stdout.",
    ),
) -> None:
    """Fetch repository file bytes (GET …/files/{file_id}/content)."""
    client, tenant_slug = _scoped_client(ctx)
    path = api_paths.tenant_repository_file_content(tenant_slug, repository_id, file_id)
    response = client.get_raw(path)
    if not response.is_success:
        from apiome_cli.client.errors import exit_on_api_error

        exit_on_api_error(response)
    if output.strip() == "-":
        typer.echo(response.text, nl=False)
        return
    with open(output, "wb") as handle:
        handle.write(response.content)


@app.command("add")
def add_repository(ctx: typer.Context) -> None:
    """Register a tenant repository (not exposed on /v1 REST)."""
    del ctx
    _not_supported()


@app.command("scan")
def scan_repository(ctx: typer.Context) -> None:
    """Enqueue a repository branch scan (not exposed on /v1 REST)."""
    del ctx
    _not_supported()


@app.command("inspect")
def inspect_repository_file(ctx: typer.Context) -> None:
    """Run content sniff on a repository file (not exposed on /v1 REST)."""
    del ctx
    _not_supported()


@app.command("import")
def import_repository_file(ctx: typer.Context) -> None:
    """Import repository file(s) (not exposed on /v1 REST)."""
    del ctx
    _not_supported()


@app.command("imports")
def list_repository_imports(ctx: typer.Context) -> None:
    """List repository import history (not exposed on /v1 REST)."""
    del ctx
    _not_supported()


@app.command("verify")
def verify_repository_files(ctx: typer.Context) -> None:
    """Verify repository file trust (not exposed on /v1 REST)."""
    del ctx
    _not_supported()
