"""``apiome arazzo`` — read and check stored Arazzo workflow records (COA-1.5, #7041).

* ``apiome arazzo list`` — the workflows a revision stores, with how many steps resolved;
* ``apiome arazzo show WORKFLOW_ID`` — one workflow, its sources and its ordered steps;
* ``apiome arazzo validate [FILE]`` — check a local Arazzo document's structure, or check that
  every stored step's ``operationRef`` / ``operationId`` resolved and every source was found.

A revision is named with ``--project`` and ``--version`` (a Project's revision) or ``--catalog``
(a catalog item's latest revision; ``--revision`` names another one). The reads are the REST
routes under ``/v1/workflows/{tenant}/…``; the tables and checks are in
:mod:`apiome_cli.arazzo_records`.
"""

from __future__ import annotations

from typing import Any, Optional

import typer

from apiome_cli.arazzo_records import (
    describe_problem,
    document_summary,
    emit_workflow_detail,
    emit_workflows_table,
    find_workflow,
    record_problems,
)
from apiome_cli.client import api_paths
from apiome_cli.client.version_scope import resolve_version_scope, tenant_scoped_client
from apiome_cli.exit_codes import EXIT_ARAZZO_INVALID, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.import_.arazzo import ArazzoStructureError, load_and_validate_arazzo_file
from apiome_cli.output import emit_json, json_mode_from_context

app = typer.Typer(
    name="arazzo",
    help="List, show and validate the Arazzo workflows a revision stores.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def arazzo_group(ctx: typer.Context) -> None:
    """Arazzo workflow records command group."""
    group_callback_without_subcommand(ctx)


def _project_option() -> Any:
    return typer.Option(None, "--project", help="Project UUID or slug (with --version).")


def _version_option() -> Any:
    return typer.Option(None, "--version", help="Version UUID, slug or label (with --project).")


def _catalog_option() -> Any:
    return typer.Option(
        None, "--catalog", help="Catalog item UUID; reads its latest revision unless --revision."
    )


def _revision_option() -> Any:
    return typer.Option(None, "--revision", help="Catalog revision UUID (with --catalog).")


def _usage(message: str) -> None:
    """Print ``message`` to stderr and exit with :data:`EXIT_USAGE`."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(EXIT_USAGE)


def _check_scope(
    project: Optional[str], version: Optional[str], catalog: Optional[str], revision: Optional[str]
) -> None:
    """Require exactly one revision scope: ``--project`` + ``--version``, or ``--catalog``.

    Raises:
        typer.Exit: :data:`EXIT_USAGE` when no scope, both scopes or half a scope is given.
    """
    if catalog and (project or version):
        _usage("use --project/--version or --catalog, not both.")
    if revision and not catalog:
        _usage("--revision needs --catalog.")
    if not catalog and not (project and version):
        _usage("name a revision with --project and --version, or with --catalog.")


def _fetch_workflows(
    ctx: typer.Context,
    *,
    project: Optional[str],
    version: Optional[str],
    catalog: Optional[str],
    revision: Optional[str],
) -> dict[str, Any]:
    """Read a revision's stored workflows.

    Args:
        ctx: Typer context (settings, timeout, TLS).
        project: ``--project`` value, used with ``version``.
        version: ``--version`` value.
        catalog: ``--catalog`` item id, used instead of ``project`` / ``version``.
        revision: ``--revision`` id of the catalog item, or ``None`` for its latest.

    Returns:
        The REST ``ArazzoWorkflowsResponse`` body.

    Raises:
        typer.Exit: :data:`EXIT_USAGE` for a bad scope or a 4xx; exit 1 for a 5xx or no network.
    """
    _check_scope(project, version, catalog, revision)
    if catalog:
        client, tenant_slug = tenant_scoped_client(ctx)
        path = api_paths.arazzo_catalog_workflows(tenant_slug, catalog, revision)
    else:
        client, tenant_slug, _project_id, version_id = resolve_version_scope(
            ctx, project=str(project), version=str(version)
        )
        path = api_paths.arazzo_version_workflows(tenant_slug, version_id)
    return client.get(path).json()


@app.command("list")
def list_workflows(
    ctx: typer.Context,
    project: Optional[str] = _project_option(),
    version: Optional[str] = _version_option(),
    catalog: Optional[str] = _catalog_option(),
    revision: Optional[str] = _revision_option(),
) -> None:
    """List the Arazzo workflows a revision stores.

    Reads GET /v1/workflows/{tenant}/versions/{version_id}, or the catalog route with --catalog.
    The table counts each workflow's steps and how many resolved to an operation; --json prints
    the REST response (every workflow with its steps).

    Exit codes: 0 listed (an empty table when the revision holds no Arazzo document); 2 bad
    flags, or the project, version or catalog item is unknown; 1 server or network error.
    """
    payload = _fetch_workflows(
        ctx, project=project, version=version, catalog=catalog, revision=revision
    )
    if json_mode_from_context(ctx):
        emit_json(payload)
        return
    emit_workflows_table(payload)


@app.command("show")
def show_workflow(
    ctx: typer.Context,
    workflow_id: str = typer.Argument(..., help="The workflow's Arazzo workflowId."),
    project: Optional[str] = _project_option(),
    version: Optional[str] = _version_option(),
    catalog: Optional[str] = _catalog_option(),
    revision: Optional[str] = _revision_option(),
) -> None:
    """Show one stored Arazzo workflow and its ordered steps.

    Reads GET /v1/workflows/{tenant}/versions/{version_id}/workflows/{workflow_id}; with --catalog
    the workflow is picked from the catalog route's list. Each step shows its target, its
    resolution state (resolved, unresolved, not_applicable or parse_error) and the operation it
    resolved to; --json prints the workflow with its revision and declared sources.

    Exit codes: 0 shown; 2 bad flags, or the revision or workflow is unknown; 1 server or
    network error.
    """
    _check_scope(project, version, catalog, revision)
    if catalog:
        payload = _fetch_workflows(
            ctx, project=None, version=None, catalog=catalog, revision=revision
        )
        workflow = find_workflow(payload, workflow_id)
        if workflow is None:
            _usage(f"Workflow not found: {workflow_id}")
        detail = {
            "version_id": payload.get("version_id"),
            "project_id": payload.get("project_id"),
            "sources": payload.get("sources") or [],
            "workflow": workflow,
        }
    else:
        client, tenant_slug, _project_id, version_id = resolve_version_scope(
            ctx, project=str(project), version=str(version)
        )
        detail = client.get(
            api_paths.arazzo_version_workflow(tenant_slug, version_id, workflow_id)
        ).json()
    if json_mode_from_context(ctx):
        emit_json(detail)
        return
    emit_workflow_detail(detail["workflow"])


def _validate_file(ctx: typer.Context, source: str) -> None:
    """Validate a local (or URL, or stdin) Arazzo document against its version's schema.

    Raises:
        typer.Exit: :data:`EXIT_ARAZZO_INVALID` when the document fails validation;
            :data:`EXIT_USAGE` when it cannot be read or parsed.
    """
    json_mode = json_mode_from_context(ctx)
    try:
        doc = load_and_validate_arazzo_file(source)
    except ArazzoStructureError as exc:
        if json_mode:
            emit_json({"valid": False, "source": source, "error": exc.message, "pointer": exc.pointer})
        typer.echo(f"Invalid Arazzo document: {exc.message}", err=True)
        raise typer.Exit(EXIT_ARAZZO_INVALID) from exc
    except (ValueError, OSError) as exc:
        _usage(str(exc))
    summary = document_summary(doc)
    if json_mode:
        emit_json({"valid": True, "source": source, **summary})
        return
    typer.echo(
        f"Valid Arazzo {summary['arazzo']} document: {summary['workflows']} workflow(s), "
        f"{summary['steps']} step(s), {summary['sources']} source description(s)."
    )


def _validate_records(ctx: typer.Context, payload: dict[str, Any]) -> None:
    """Check that a revision's stored steps resolved and its sources were found.

    Raises:
        typer.Exit: :data:`EXIT_ARAZZO_INVALID` when any step is unresolved or a source missing.
    """
    problems = record_problems(payload)
    workflows = payload.get("workflows") or []
    if json_mode_from_context(ctx):
        emit_json(
            {
                "valid": not problems,
                "version_id": payload.get("version_id"),
                "workflows": len(workflows),
                "problems": problems,
            }
        )
    else:
        for problem in problems:
            typer.echo(describe_problem(problem), err=True)
        if not workflows:
            typer.echo("The revision stores no Arazzo workflows.")
        elif not problems:
            typer.echo(
                f"{len(workflows)} workflow(s): every step resolved and every source was found."
            )
        else:
            typer.echo(f"{len(problems)} problem(s) in {len(workflows)} workflow(s).", err=True)
    if problems:
        raise typer.Exit(EXIT_ARAZZO_INVALID)


@app.command("validate")
def validate(
    ctx: typer.Context,
    source: Optional[str] = typer.Argument(
        None,
        metavar="[FILE]",
        help="Arazzo document to check (.yaml, .yml, .json, a URL, or - for stdin).",
    ),
    project: Optional[str] = _project_option(),
    version: Optional[str] = _version_option(),
    catalog: Optional[str] = _catalog_option(),
    revision: Optional[str] = _revision_option(),
) -> None:
    """Validate an Arazzo document, or the workflows a revision stores.

    With FILE, checks the document against the Arazzo JSON Schema for the version it declares
    (1.0.x or 1.1.x) — no server call. With --project/--version or --catalog instead, reads the
    stored workflows and fails when a step's operationRef / operationId is unresolved or could
    not be parsed, or when a source description is missing; each problem is printed on stderr.

    Exit codes: 0 valid; 7 invalid document, or unresolved steps or missing sources; 2 bad
    flags, an unreadable file, or an unknown revision; 1 server or network error.
    """
    if source is not None:
        if project or version or catalog or revision:
            _usage("give a FILE or a revision (--project/--version or --catalog), not both.")
        _validate_file(ctx, source)
        return
    payload = _fetch_workflows(
        ctx, project=project, version=version, catalog=catalog, revision=revision
    )
    _validate_records(ctx, payload)
