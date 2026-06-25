"""Import subcommands (OpenAPI, Arazzo, and JSON Schema uploads)."""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID

import typer

from objectified_cli.cli_context import (
    import_timeout_from_context,
    insecure_from_context,
    no_progress_from_context,
    settings_from_context,
)
from objectified_cli.client import api_paths
from objectified_cli.client.http import RestClient
from objectified_cli.client.tenant_scope import require_tenant_slug
from objectified_cli.import_.spec_import import (
    build_spec_import_json_body,
    build_spec_import_metadata,
    document_bytes_from_spec,
    infer_source_kind,
    post_spec_import_json,
    post_spec_import_multipart,
    source_basename as spec_source_basename,
)
from objectified_cli.config import require_api_key
from objectified_cli.extract.openapi_info import extract_info_metadata
from objectified_cli.extract.slug import slugify_project_name, slugify_version
from objectified_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from objectified_cli.import_.detect import (
    DocumentKind,
    describe_document_format,
    detect_document_kind,
    looks_like_json_schema_type,
    resolve_auto_import_command,
    unrecognized_auto_import_message,
    wrong_importer_message,
)
from objectified_cli.import_.source import (
    format_document_import_progress,
    load_import_document,
    source_basename,
)
from objectified_cli.import_.json_schema import (
    JsonSchemaTarget,
)
from objectified_cli.import_.openapi import (
    OpenApiStructureError,
    load_openapi_file,
    validate_openapi_structure,
)
from objectified_cli.import_.schema_type_coercion import SchemaTypeCoercionWarning
from objectified_cli.import_.jobs import DEFAULT_POLL_INTERVAL
from objectified_cli.import_.publish import (
    PUBLISH_FLAG_HELP,
    TYPE_PUBLISH_FLAG_HELP,
    VISIBILITY_FLAG_HELP,
    resolve_publish_visibility,
    resolve_type_publish_system,
)
from objectified_cli.import_.source import is_local_file_source
from objectified_cli.import_.upload import (
    apply_info_overrides,
    import_result_has_errors,
    resolve_import_result,
)
from objectified_cli.help_util import group_callback_without_subcommand
from objectified_cli.output import (
    emit_import_job_accepted,
    emit_import_result,
    json_mode_from_context,
    merge_import_warnings,
)

_REST_IMPORT_NOT_SUPPORTED = (
    "This import command is not supported via the /v1 REST API yet."
)

PROJECT_NAME_FIELD_HELP = (
    "Dot path or JSON Pointer for the field used as the project name "
    "(for example ``info.summary`` or ``#/info/summary``). Stored as "
    "``info.x-objectified-project-name-field`` when omitted from the document."
)

app = typer.Typer(
    name="import",
    help=(
        "Import OpenAPI, Swagger, Arazzo, JSON Schema, and JSON Schema type "
        "documents into Objectified."
    ),
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


def _coerce_publish_visibility(
    *,
    publish: str | None,
    visibility: str | None,
) -> str | None:
    """Resolve ``--publish`` / ``--visibility`` to a REST API visibility value."""
    try:
        return resolve_publish_visibility(publish=publish, visibility=visibility)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc


def _coerce_type_publish_system(
    *,
    publish: str | None,
    visibility: str | None,
) -> bool | None:
    """Resolve ``--publish`` / ``--visibility`` to a REST ``system`` flag."""
    try:
        return resolve_type_publish_system(publish=publish, visibility=visibility)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc


def _import_result_id(
    payload: dict[str, Any],
    *,
    top_key: str,
    nested_key: str,
) -> str | None:
    """Extract a UUID string from an import result payload (top-level or nested)."""
    value = payload.get(top_key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    nested = payload.get(nested_key)
    if isinstance(nested, dict):
        nested_id = nested.get("id")
        if isinstance(nested_id, str) and nested_id.strip():
            return nested_id.strip()
    return None


def _publish_imported_version(
    client: RestClient,
    tenant_slug: str,
    *,
    payload: dict[str, Any],
    visibility: str,
    no_progress: bool,
) -> None:
    """Publish the version created by a completed import via the publish endpoint.

    The ``/v1`` spec-import surface carries no visibility field, so ``--publish``
    is realized as a follow-up ``POST .../{version_record_id}/publish`` once the
    import has produced a concrete project and version record.
    """
    project_id = _import_result_id(payload, top_key="project_id", nested_key="project")
    version_id = _import_result_id(payload, top_key="version_id", nested_key="version")
    if project_id is None or version_id is None:
        typer.echo(
            "Imported successfully but could not publish: the import result is "
            "missing the project or version id.",
            err=True,
        )
        raise typer.Exit(EXIT_ERROR)
    client.post(
        api_paths.version_publish(tenant_slug, project_id, version_id),
        json={"visibility": visibility},
    )
    if not no_progress:
        label = "public" if visibility == "public" else "private"
        typer.echo(f"Published imported version as {label}.", err=True)


def _format_openapi_import_target(
    spec: dict[str, Any],
    *,
    project_name: str | None,
    project_name_field: str | None,
    version: str | None,
    project_slug: str | None,
    version_slug: str | None,
) -> str:
    """Return a human-readable import target label from OpenAPI ``info`` metadata."""
    target = extract_info_metadata(
        spec,
        project_name=project_name,
        project_name_field=project_name_field,
        version=version,
    )
    resolved_project_slug = (
        slugify_project_name(project_slug) if project_slug is not None else target.project_slug
    )
    resolved_version_slug = (
        slugify_version(version_slug) if version_slug is not None else target.version_slug
    )
    return (
        f"{target.name} @ {target.version} "
        f"({resolved_project_slug}/{resolved_version_slug})"
    )


def _document_has_multi_type_defs(document: dict[str, Any]) -> bool:
    """Return True when the document is a ``$defs`` type library without a concrete top-level type."""
    return looks_like_json_schema_type(document)


def _apply_type_description_override(
    document: dict[str, Any],
    *,
    description: str | None,
) -> dict[str, Any]:
    """Return *document* with an optional top-level ``description`` override."""
    if description is None:
        return document
    updated = copy.deepcopy(document)
    updated["description"] = description
    return updated


@app.callback(invoke_without_command=True)
def import_group(ctx: typer.Context) -> None:
    """Import command group."""
    group_callback_without_subcommand(ctx)


def _run_openapi_import(
    ctx: typer.Context,
    *,
    path: str,
    dry_run: bool,
    project_name: str | None,
    project_name_field: str | None,
    version: str | None,
    project_id: UUID | None,
    project_slug: str | None,
    version_slug: str | None,
    publish: str | None,
    visibility: str | None,
    wait: bool,
    poll_interval: float,
    progress_label: str,
    attempted: str = "openapi",
) -> None:
    settings = settings_from_context(ctx)
    require_api_key(settings)

    # Resolve before uploading so invalid --publish/--visibility input fails fast.
    publish_visibility = _coerce_publish_visibility(publish=publish, visibility=visibility)

    import_timeout = import_timeout_from_context(ctx)
    no_progress = no_progress_from_context(ctx)

    try:
        spec = load_openapi_file(
            path,
            timeout=import_timeout,
            verify=not insecure_from_context(ctx),
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except OSError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    detected = detect_document_kind(spec)
    if detected in (DocumentKind.json_schema, DocumentKind.arazzo):
        typer.echo(
            wrong_importer_message(detected, attempted=attempted),
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    try:
        preparation_warnings: list[SchemaTypeCoercionWarning] = []
        validate_openapi_structure(
            spec,
            preparation_warnings=preparation_warnings,
        )
    except OpenApiStructureError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    try:
        spec = apply_info_overrides(
            spec,
            project_name=project_name,
            version=version,
            project_slug=project_slug,
            version_slug=version_slug,
            project_name_field=project_name_field,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    client = RestClient(
        settings,
        timeout=import_timeout,
        verify=not insecure_from_context(ctx),
    )

    tenant_slug = require_tenant_slug(settings, client)
    use_multipart = is_local_file_source(path)
    upload_name = spec_source_basename(path) or "import.json"
    source_kind = infer_source_kind(spec, filename=upload_name)
    metadata = build_spec_import_metadata(
        spec,
        source_kind=source_kind,
        project_name=project_name,
        project_slug=project_slug,
        version=version,
        existing_project_id=str(project_id) if project_id is not None else None,
        dry_run=dry_run,
    )

    if not no_progress:
        target_label = _format_openapi_import_target(
            spec,
            project_name=project_name,
            project_name_field=project_name_field,
            version=version,
            project_slug=project_slug,
            version_slug=version_slug,
        )
        typer.echo(
            format_document_import_progress(
                document_label=progress_label,
                source=path,
                dry_run=dry_run,
                target_label=target_label,
            ),
            err=True,
        )

    if use_multipart:
        file_bytes = document_bytes_from_spec(spec, filename=upload_name)
        response = post_spec_import_multipart(
            client,
            tenant_slug,
            metadata=metadata,
            file_bytes=file_bytes,
            filename=upload_name,
        )
    else:
        file_bytes = document_bytes_from_spec(spec, filename=upload_name)
        body = build_spec_import_json_body(
            file_bytes,
            metadata,
            filename=upload_name,
            content_type="application/json",
        )
        response = post_spec_import_json(client, tenant_slug, body)
    json_mode = json_mode_from_context(ctx)
    resolution = resolve_import_result(
        response,
        client,
        tenant_slug,
        wait=wait,
        poll_interval=poll_interval,
        timeout=import_timeout,
        no_progress=no_progress,
    )

    if resolution.kind == "completed":
        result_payload = merge_import_warnings(
            resolution.payload,
            preparation_warnings,
        )
        emit_import_result(
            result_payload,
            json_mode=json_mode,
            dry_run=dry_run,
        )
        if import_result_has_errors(resolution.payload):
            raise typer.Exit(EXIT_ERROR)
        if publish_visibility is not None:
            if dry_run:
                typer.echo(
                    "Skipping --publish: dry run did not persist a version.",
                    err=True,
                )
            else:
                _publish_imported_version(
                    client,
                    tenant_slug,
                    payload=resolution.payload,
                    visibility=publish_visibility,
                    no_progress=no_progress,
                )
        return

    if publish_visibility is not None:
        typer.echo(
            "Skipping --publish: import has not completed "
            "(remove --no-wait to publish).",
            err=True,
        )
    emit_import_job_accepted(resolution.payload, json_mode=json_mode)


@app.command("openapi")
def import_openapi(
    ctx: typer.Context,
    path: str = typer.Argument(
        ...,
        help=(
            "OpenAPI document path (``.json``, ``.yaml``, ``.yml``), "
            "``http``/``https`` URL, or ``-`` for stdin."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and plan the import without persisting changes.",
    ),
    project_name: str | None = typer.Option(
        None,
        "--project-name",
        help="Override project name derived from the configured project-name field.",
    ),
    project_name_field: str | None = typer.Option(
        None,
        "--project-name-field",
        help=PROJECT_NAME_FIELD_HELP,
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Override version string derived from ``info.version``.",
    ),
    project_id: UUID | None = typer.Option(
        None,
        "--project-id",
        help="Update an existing project instead of creating from ``info``.",
    ),
    project_slug: str | None = typer.Option(
        None,
        "--project-slug",
        help="Override project slug derived from ``info.title`` (DB slug rules).",
    ),
    version_slug: str | None = typer.Option(
        None,
        "--version-slug",
        help="Override version slug derived from ``info.version`` (DB slug rules).",
    ),
    publish: str | None = typer.Option(
        None,
        "--publish",
        help=PUBLISH_FLAG_HELP,
    ),
    visibility: str | None = typer.Option(
        None,
        "--visibility",
        help=VISIBILITY_FLAG_HELP,
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll async imports until complete (default: wait).",
    ),
    poll_interval: float = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        min=0.1,
        help="Seconds between ``GET /imports/{job_id}`` polls when waiting.",
    ),
) -> None:
    """Import an OpenAPI document from a file, URL, or stdin."""
    _run_openapi_import(
        ctx,
        path=path,
        dry_run=dry_run,
        project_name=project_name,
        project_name_field=project_name_field,
        version=version,
        project_id=project_id,
        project_slug=project_slug,
        version_slug=version_slug,
        publish=publish,
        visibility=visibility,
        wait=wait,
        poll_interval=poll_interval,
        progress_label="OpenAPI",
        attempted="openapi",
    )


@app.command("swagger")
def import_swagger(
    ctx: typer.Context,
    path: str = typer.Argument(
        ...,
        help=(
            "Swagger 2.0 document path (``.json``, ``.yaml``, ``.yml``), "
            "``http``/``https`` URL, or ``-`` for stdin."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and plan the import without persisting changes.",
    ),
    project_name: str | None = typer.Option(
        None,
        "--project-name",
        help="Override project name derived from the configured project-name field.",
    ),
    project_name_field: str | None = typer.Option(
        None,
        "--project-name-field",
        help=PROJECT_NAME_FIELD_HELP,
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Override version string derived from ``info.version``.",
    ),
    project_id: UUID | None = typer.Option(
        None,
        "--project-id",
        help="Update an existing project instead of creating from ``info``.",
    ),
    project_slug: str | None = typer.Option(
        None,
        "--project-slug",
        help="Override project slug derived from ``info.title`` (DB slug rules).",
    ),
    version_slug: str | None = typer.Option(
        None,
        "--version-slug",
        help="Override version slug derived from ``info.version`` (DB slug rules).",
    ),
    publish: str | None = typer.Option(
        None,
        "--publish",
        help=PUBLISH_FLAG_HELP,
    ),
    visibility: str | None = typer.Option(
        None,
        "--visibility",
        help=VISIBILITY_FLAG_HELP,
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll async imports until complete (default: wait).",
    ),
    poll_interval: float = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        min=0.1,
        help="Seconds between ``GET /imports/{job_id}`` polls when waiting.",
    ),
) -> None:
    """Import a Swagger 2.0 document from a file, URL, or stdin."""
    _run_openapi_import(
        ctx,
        path=path,
        dry_run=dry_run,
        project_name=project_name,
        project_name_field=project_name_field,
        version=version,
        project_id=project_id,
        project_slug=project_slug,
        version_slug=version_slug,
        publish=publish,
        visibility=visibility,
        wait=wait,
        poll_interval=poll_interval,
        progress_label="Swagger",
        attempted="swagger",
    )


@app.command("arazzo")
def import_arazzo(
    ctx: typer.Context,
    path: str = typer.Argument(
        ...,
        help=(
            "Arazzo document path (``.json``, ``.yaml``, ``.yml``), "
            "``http``/``https`` URL, or ``-`` for stdin."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and plan the import without persisting changes.",
    ),
    project_name: str | None = typer.Option(
        None,
        "--project-name",
        help="Override project name derived from the configured project-name field.",
    ),
    project_name_field: str | None = typer.Option(
        None,
        "--project-name-field",
        help=PROJECT_NAME_FIELD_HELP,
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Override version string derived from ``info.version``.",
    ),
    project_id: UUID | None = typer.Option(
        None,
        "--project-id",
        help="Update an existing project instead of creating from ``info``.",
    ),
    project_slug: str | None = typer.Option(
        None,
        "--project-slug",
        help="Override project slug derived from ``info.title`` (DB slug rules).",
    ),
    version_id: UUID | None = typer.Option(
        None,
        "--version-id",
        help="Attach workflows to this existing project version.",
    ),
    version_slug: str | None = typer.Option(
        None,
        "--version-slug",
        help="Override version slug derived from ``info.version`` (DB slug rules).",
    ),
    publish: str | None = typer.Option(
        None,
        "--publish",
        help=PUBLISH_FLAG_HELP,
    ),
    visibility: str | None = typer.Option(
        None,
        "--visibility",
        help=VISIBILITY_FLAG_HELP,
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll async imports until complete (default: wait).",
    ),
    poll_interval: float = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        min=0.1,
        help="Seconds between ``GET /imports/{job_id}`` polls when waiting.",
    ),
) -> None:
    """Import an Arazzo 1.0 workflow document from a file, URL, or stdin."""
    _run_arazzo_import(
        ctx,
        path=path,
        dry_run=dry_run,
        project_name=project_name,
        project_name_field=project_name_field,
        version=version,
        project_id=project_id,
        project_slug=project_slug,
        version_id=version_id,
        version_slug=version_slug,
        publish=publish,
        visibility=visibility,
        wait=wait,
        poll_interval=poll_interval,
    )


def _run_arazzo_import(
    ctx: typer.Context,
    *,
    path: str,
    dry_run: bool,
    project_name: str | None,
    project_name_field: str | None,
    version: str | None,
    project_id: UUID | None,
    project_slug: str | None,
    version_id: UUID | None,
    version_slug: str | None,
    publish: str | None,
    visibility: str | None,
    wait: bool,
    poll_interval: float,
) -> None:
    del (
        ctx,
        path,
        dry_run,
        project_name,
        project_name_field,
        version,
        project_id,
        project_slug,
        version_id,
        version_slug,
        publish,
        visibility,
        wait,
        poll_interval,
    )
    typer.echo(_REST_IMPORT_NOT_SUPPORTED, err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command("json-schema")
def import_json_schema(
    ctx: typer.Context,
    path: str = typer.Argument(
        ...,
        help=(
            "JSON Schema path (``.json``, ``.yaml``, ``.yml``), "
            "``http``/``https`` URL, or ``-`` for stdin."
        ),
    ),
    as_target: JsonSchemaTarget | None = typer.Option(
        None,
        "--as",
        help=(
            "Import as ``property``, ``properties`` (all ``$defs`` entries), "
            "or ``schema`` (default: auto-detect)."
        ),
        case_sensitive=False,
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Property or schema name when not inferred from the file.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Description stored on the property or schema.",
    ),
    project_id: UUID | None = typer.Option(
        None,
        "--project-id",
        help="Link the import to this project (``project_properties`` when requested).",
    ),
    version_id: UUID | None = typer.Option(
        None,
        "--version-id",
        help="Link a schema import to this project version.",
    ),
    link_project_property: bool = typer.Option(
        False,
        "--link-project-property",
        help="Create a ``project_properties`` row when ``--project-id`` is set.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and plan the import without persisting changes.",
    ),
) -> None:
    """Import a JSON Schema 2020-12 document from a file, URL, or stdin."""
    _run_json_schema_import(
        ctx,
        path=path,
        dry_run=dry_run,
        as_target=as_target,
        name=name,
        description=description,
        project_id=project_id,
        version_id=version_id,
        link_project_property=link_project_property,
    )


def _run_json_schema_import(
    ctx: typer.Context,
    *,
    path: str,
    dry_run: bool,
    as_target: JsonSchemaTarget | None,
    name: str | None,
    description: str | None,
    project_id: UUID | None,
    version_id: UUID | None,
    link_project_property: bool,
) -> None:
    del (
        ctx,
        path,
        dry_run,
        as_target,
        name,
        description,
        project_id,
        version_id,
        link_project_property,
    )
    typer.echo(_REST_IMPORT_NOT_SUPPORTED, err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command("json-schema-type")
def import_json_schema_type(
    ctx: typer.Context,
    path: str = typer.Argument(
        ...,
        help=(
            "JSON Schema type library path (``.json``, ``.yaml``, ``.yml``), "
            "``http``/``https`` URL, or ``-`` for stdin."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and plan the import without persisting changes.",
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Override inferred type name (single-type imports only).",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Override description stored on the type (single-type imports only).",
    ),
    publish: str | None = typer.Option(
        None,
        "--publish",
        help=TYPE_PUBLISH_FLAG_HELP,
    ),
    visibility: str | None = typer.Option(
        None,
        "--visibility",
        help=VISIBILITY_FLAG_HELP,
    ),
) -> None:
    """Import system-wide JSON Schema type definitions from a file, URL, or stdin."""
    _run_json_schema_type_import(
        ctx,
        path=path,
        dry_run=dry_run,
        name=name,
        description=description,
        publish=publish,
        visibility=visibility,
    )


def _run_json_schema_type_import(
    ctx: typer.Context,
    *,
    path: str,
    dry_run: bool,
    name: str | None,
    description: str | None,
    publish: str | None = None,
    visibility: str | None = None,
) -> None:
    del ctx, path, dry_run, name, description, publish, visibility
    typer.echo(_REST_IMPORT_NOT_SUPPORTED, err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command("auto")
def import_auto(
    ctx: typer.Context,
    path: str = typer.Argument(
        ...,
        help=(
            "Document path (``.json``, ``.yaml``, ``.yml``), "
            "``http``/``https`` URL, or ``-`` for stdin."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and plan the import without persisting changes.",
    ),
    project_name: str | None = typer.Option(
        None,
        "--project-name",
        help="Override project name derived from the configured project-name field (OpenAPI/Arazzo).",
    ),
    project_name_field: str | None = typer.Option(
        None,
        "--project-name-field",
        help=f"{PROJECT_NAME_FIELD_HELP} (OpenAPI/Arazzo).",
    ),
    version: str | None = typer.Option(
        None,
        "--version",
        help="Override version string derived from ``info.version`` (OpenAPI/Arazzo).",
    ),
    project_id: UUID | None = typer.Option(
        None,
        "--project-id",
        help="Target or link project for the import.",
    ),
    project_slug: str | None = typer.Option(
        None,
        "--project-slug",
        help="Override project slug derived from ``info.title`` (OpenAPI/Arazzo).",
    ),
    version_slug: str | None = typer.Option(
        None,
        "--version-slug",
        help="Override version slug derived from ``info.version`` (OpenAPI/Arazzo).",
    ),
    version_id: UUID | None = typer.Option(
        None,
        "--version-id",
        help="Attach Arazzo workflows or JSON Schema to this project version.",
    ),
    publish: str | None = typer.Option(
        None,
        "--publish",
        help=f"{PUBLISH_FLAG_HELP} (OpenAPI/Arazzo).",
    ),
    visibility: str | None = typer.Option(
        None,
        "--visibility",
        help=f"{VISIBILITY_FLAG_HELP} (OpenAPI/Arazzo).",
    ),
    as_target: JsonSchemaTarget | None = typer.Option(
        None,
        "--as",
        help=(
            "JSON Schema import target: ``property``, ``properties``, or ``schema`` "
            "(default: auto-detect)."
        ),
        case_sensitive=False,
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        help="Property, schema, or type name override.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Description stored on the imported JSON Schema artifact.",
    ),
    link_project_property: bool = typer.Option(
        False,
        "--link-project-property",
        help="Create a ``project_properties`` row when ``--project-id`` is set.",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Poll async OpenAPI/Arazzo imports until complete (default: wait).",
    ),
    poll_interval: float = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        min=0.1,
        help="Seconds between ``GET /imports/{job_id}`` polls when waiting.",
    ),
) -> None:
    """Detect document format from headers and run the matching import."""
    import_timeout = import_timeout_from_context(ctx)
    no_progress = no_progress_from_context(ctx)

    try:
        document = load_import_document(
            path,
            timeout=import_timeout,
            verify=not insecure_from_context(ctx),
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except OSError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc

    filename = source_basename(path)
    command = resolve_auto_import_command(document, filename=filename)
    if command is None:
        typer.echo(unrecognized_auto_import_message(document), err=True)
        raise typer.Exit(EXIT_USAGE)

    if not no_progress:
        typer.echo(
            f"Detected {describe_document_format(document, filename=filename)}; "
            f"running import {command}.",
            err=True,
        )

    if command in {"openapi", "swagger"}:
        _run_openapi_import(
            ctx,
            path=path,
            dry_run=dry_run,
            project_name=project_name,
            project_name_field=project_name_field,
            version=version,
            project_id=project_id,
            project_slug=project_slug,
            version_slug=version_slug,
            publish=publish,
            visibility=visibility,
            wait=wait,
            poll_interval=poll_interval,
            progress_label="Swagger" if command == "swagger" else "OpenAPI",
            attempted=command,
        )
        return

    if command == "arazzo":
        _run_arazzo_import(
            ctx,
            path=path,
            dry_run=dry_run,
            project_name=project_name,
            project_name_field=project_name_field,
            version=version,
            project_id=project_id,
            project_slug=project_slug,
            version_id=version_id,
            version_slug=version_slug,
            publish=publish,
            visibility=visibility,
            wait=wait,
            poll_interval=poll_interval,
        )
        return

    if command == "json-schema":
        _run_json_schema_import(
            ctx,
            path=path,
            dry_run=dry_run,
            as_target=as_target,
            name=name,
            description=description,
            project_id=project_id,
            version_id=version_id,
            link_project_property=link_project_property,
        )
        return

    _run_json_schema_type_import(
        ctx,
        path=path,
        dry_run=dry_run,
        name=name,
        description=description,
        publish=publish,
        visibility=visibility,
    )
