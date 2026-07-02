"""Helpers to load version paths, operations, and workflow steps from REST."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import typer

from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.version_scope import version_paths_base
from apiome_cli.exit_codes import EXIT_USAGE

_WORKFLOW_NOT_SUPPORTED = (
    "Workflow list/show is not available via the /v1 REST API yet."
)


def normalize_pathname(value: str) -> str:
    """Normalize a path template reference for comparison."""
    text = value.strip()
    if not text:
        return text
    if not text.startswith("/"):
        return f"/{text}"
    return text


def _encode_multi_params(
    *,
    method: list[str] | None,
    tag: list[str] | None,
) -> list[tuple[str, str]]:
    """Encode list-valued filters using explode form style for httpx/urlencode."""
    pairs: list[tuple[str, str]] = []
    if method:
        for value in method:
            pairs.append(("method", value.upper()))
    if tag:
        for value in tag:
            pairs.append(("tag", value))
    return pairs


def _workflow_not_supported() -> None:
    typer.echo(_WORKFLOW_NOT_SUPPORTED, err=True)
    raise typer.Exit(EXIT_USAGE)


def fetch_version_paths(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    *,
    methods: list[str] | None = None,
    tags: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List path templates for a version with optional operation-level filters."""
    params = _encode_multi_params(method=methods, tag=tags) or None
    return fetch_list(
        client,
        version_paths_base(tenant_slug, version_id),
        params=params,
    )


def fetch_path_operations(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    path_id: UUID,
    *,
    methods: list[str] | None = None,
    tags: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List operations for one path template."""
    params = _encode_multi_params(method=methods, tag=tags) or None
    base = version_paths_base(tenant_slug, version_id)
    return fetch_list(
        client,
        f"{base}/{path_id}/operations",
        params=params,
    )


def resolve_path_record(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    path_ref: str,
    *,
    methods: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve a path by UUID or pathname within a version."""
    ref = path_ref.strip()
    if not ref:
        typer.echo("Path reference cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)

    try:
        path_id = UUID(ref)
    except ValueError:
        path_id = None

    base = version_paths_base(tenant_slug, version_id)
    if path_id is not None:
        response = client.get_raw(f"{base}/{path_id}")
        if response.status_code == 404:
            typer.echo(f"Path not found: {path_ref!r}", err=True)
            raise typer.Exit(EXIT_USAGE)
        if not response.is_success:
            from apiome_cli.client.errors import exit_on_api_error

            exit_on_api_error(response)
        record = response.json()
        if not isinstance(record, dict):
            typer.echo(f"Unexpected response for path {path_ref!r}.", err=True)
            raise typer.Exit(EXIT_USAGE)
        return record

    pathname = normalize_pathname(ref)
    paths, _total = fetch_version_paths(
        client,
        tenant_slug,
        version_id,
        methods=methods,
        tags=tags,
    )
    matches = [
        row
        for row in paths
        if isinstance(row.get("pathname"), str) and row["pathname"] == pathname
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        typer.echo(f"Path not found: {path_ref!r}", err=True)
        raise typer.Exit(EXIT_USAGE)
    typer.echo(f"Path template {pathname!r} is ambiguous on the server.", err=True)
    raise typer.Exit(EXIT_USAGE)


def locate_operation(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    operation_ref: str,
    *,
    methods: list[str] | None = None,
    tags: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Find an operation by UUID or OpenAPI ``operationId`` across all version paths."""
    ref = operation_ref.strip()
    if not ref:
        typer.echo("Operation reference cannot be empty.", err=True)
        raise typer.Exit(EXIT_USAGE)

    operation_uuid: UUID | None = None
    try:
        operation_uuid = UUID(ref)
    except ValueError:
        operation_uuid = None

    paths, _total = fetch_version_paths(
        client,
        tenant_slug,
        version_id,
        methods=methods,
        tags=tags,
    )
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for path_row in paths:
        path_id = path_row.get("id")
        if not isinstance(path_id, str):
            continue
        operations, _op_total = fetch_path_operations(
            client,
            tenant_slug,
            version_id,
            UUID(path_id),
            methods=methods,
            tags=tags,
        )
        for operation_row in operations:
            if operation_uuid is not None and str(operation_row.get("id")) == str(operation_uuid):
                return (path_row, operation_row)
            description = operation_row.get("description")
            if isinstance(description, dict):
                op_id = description.get("operation_id")
                if isinstance(op_id, str) and op_id == ref:
                    matches.append((path_row, operation_row))

    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        typer.echo(f"Operation not found: {operation_ref!r}", err=True)
        raise typer.Exit(EXIT_USAGE)
    typer.echo(f"Operation reference {operation_ref!r} is ambiguous on the server.", err=True)
    raise typer.Exit(EXIT_USAGE)


def fetch_operation_parameters(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    path_id: UUID,
    operation_id: UUID,
) -> list[dict[str, Any]]:
    """Return shared path parameters for a path."""
    base = f"{version_paths_base(tenant_slug, version_id)}/{path_id}/parameters"
    parameters, _total = fetch_list(client, base)
    return [p for p in parameters if isinstance(p.get("id"), str)]


def fetch_operation_request_body(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    path_id: UUID,
    operation_id: UUID,
) -> dict[str, Any] | None:
    """Return the first request body for a path, if any."""
    base = f"{version_paths_base(tenant_slug, version_id)}/{path_id}/request-bodies"
    bodies, _total = fetch_list(client, base)
    for body in bodies:
        body_id = body.get("id")
        if not isinstance(body_id, str):
            continue
        contents, _content_total = fetch_list(
            client,
            f"{base}/{body_id}/contents",
        )
        return {"body": body, "contents": contents}
    return None


def fetch_operation_responses(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    path_id: UUID,
    operation_id: UUID,
) -> list[dict[str, Any]]:
    """Return shared path responses for a path with content rows."""
    base = f"{version_paths_base(tenant_slug, version_id)}/{path_id}/responses"
    responses, _total = fetch_list(client, base)
    result: list[dict[str, Any]] = []
    for response_row in responses:
        response_id = response_row.get("id")
        if not isinstance(response_id, str):
            continue
        contents, _content_total = fetch_list(
            client,
            f"{base}/{response_id}/contents",
        )
        result.append({"response": response_row, "contents": contents})
    return result


def fetch_version_workflows(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    *,
    fetch_all: bool = True,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """List workflows for a project version (not exposed on /v1 REST)."""
    del client, tenant_slug, version_id, fetch_all, limit
    _workflow_not_supported()
    return [], 0


def resolve_workflow_record(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    workflow_ref: str,
) -> dict[str, Any]:
    """Resolve a workflow by UUID or Arazzo ``workflow_id`` string."""
    del client, tenant_slug, version_id, workflow_ref
    _workflow_not_supported()
    return {}


def fetch_workflow_steps(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    workflow_id: UUID,
) -> list[dict[str, Any]]:
    """List ordered workflow steps for one version workflow."""
    del client, tenant_slug, version_id, workflow_id
    _workflow_not_supported()
    return []


def build_path_operation_rows(
    client: RestClient,
    tenant_slug: str,
    version_id: UUID,
    paths: list[dict[str, Any]],
    *,
    methods: list[str] | None = None,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Flatten path templates and operations into inventory rows for human list output."""
    rows: list[dict[str, Any]] = []
    for path_row in paths:
        path_id = path_row.get("id")
        pathname = path_row.get("pathname", "")
        if not isinstance(path_id, str):
            continue
        operations, _total = fetch_path_operations(
            client,
            tenant_slug,
            version_id,
            UUID(path_id),
            methods=methods,
            tags=tags,
        )
        if not operations:
            rows.append(
                {
                    "path_id": path_id,
                    "pathname": pathname,
                    "operation_id": "",
                    "method": "",
                    "operationId": "",
                    "tags": [],
                    "summary": "",
                },
            )
            continue
        for operation_row in operations:
            description = operation_row.get("description")
            op_name = ""
            op_tags: list[str] = []
            summary = ""
            if isinstance(description, dict):
                if isinstance(description.get("operation_id"), str):
                    op_name = description["operation_id"]
                raw_tags = description.get("tags")
                if isinstance(raw_tags, list):
                    op_tags = [str(tag) for tag in raw_tags]
                if isinstance(description.get("summary"), str):
                    summary = description["summary"]
            rows.append(
                {
                    "path_id": path_id,
                    "pathname": pathname,
                    "operation_id": operation_row.get("id", ""),
                    "method": operation_row.get("operation", ""),
                    "operationId": op_name,
                    "tags": op_tags,
                    "summary": summary,
                },
            )
    return rows


def filter_rows_by_query(rows: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    """Case-insensitive substring filter across pathname, method, operationId, summary, tags."""
    if not query or not query.strip():
        return rows
    needle = query.strip().casefold()

    def matches(row: dict[str, Any]) -> bool:
        fields = [
            str(row.get("pathname", "")),
            str(row.get("method", "")),
            str(row.get("operationId", "")),
            str(row.get("summary", "")),
            " ".join(row.get("tags", [])) if isinstance(row.get("tags"), list) else "",
        ]
        return any(needle in value.casefold() for value in fields if value)

    return [row for row in rows if matches(row)]
