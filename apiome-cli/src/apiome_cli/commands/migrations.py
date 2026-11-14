"""Migration plans: ``apiome migrations list`` (CLI 11.1, #3260) and ``counts`` (CLI 11.2, #3261)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.project_version_resolve import list_projects, list_versions, resolve_project_uuid
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.migration_view import (
    count_project_plans,
    filter_plans,
    render_plan_counts,
    render_plan_list,
    sort_counts,
    sort_plans,
    summarize_plan,
    version_labels,
)
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.version_fork import ForkError, find_source_version

app = typer.Typer(
    name="migrations",
    help="List a project's migration plans (rules that move data from one version to another) and count them per project.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def migrations_group(ctx: typer.Context) -> None:
    """Migration plans command group."""
    group_callback_without_subcommand(ctx)


def _resolve_version_id(
    versions: list[dict[str, Any]], version_tags: list[dict[str, Any]], ref: str, flag: str
) -> str:
    """The revision id ``ref`` names (UUID, label with or without ``v``, or version tag); exit 2 if none.

    Args:
        versions: The project's versions.
        version_tags: The project's version tags.
        ref: What the user passed to ``flag``.
        flag: ``--from`` or ``--to``, for the error message.
    """
    try:
        return str(find_source_version(versions, version_tags, ref).version["id"])
    except ForkError as exc:
        typer.echo(f"{flag}: no version or version tag {ref!r} in this project.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


def _version_tags(client: RestClient, tenant_slug: str, project_id: UUID) -> list[dict[str, Any]]:
    """The project's version tags, so ``--from stable`` works; ``[]`` if the body is not a list."""
    payload = client.get(api_paths.version_tags(tenant_slug, project_id)).json()
    return [tag for tag in payload if isinstance(tag, dict)] if isinstance(payload, list) else []


def _project_plans(client: RestClient, tenant_slug: str, project_id: UUID | str) -> list[dict[str, Any]]:
    """Every raw plan of one project (one GET); ``[]`` if the body holds no ``plans`` list."""
    payload = client.get(api_paths.project_migration_plans(tenant_slug, project_id)).json()
    raw = payload.get("plans") if isinstance(payload, dict) else None
    return [plan for plan in raw or [] if isinstance(plan, dict)]


@app.command("list")
def list_plans(
    ctx: typer.Context,
    project_ref: str = typer.Option(..., "--project", metavar="PROJECT", help="Project slug or UUID."),
    from_ref: Optional[str] = typer.Option(
        None, "--from", metavar="VERSION", help="Only plans from this version: label (2.0.0 or v2.0.0), UUID or tag."
    ),
    to_ref: Optional[str] = typer.Option(
        None, "--to", metavar="VERSION", help="Only plans to this version: label (2.1.0 or v2.1.0), UUID or tag."
    ),
    limit: int = typer.Option(DEFAULT_PAGE_LIMIT, "--limit", min=1, help="Show at most this many plans."),
    all_plans: bool = typer.Option(False, "--all", help="Show every plan (ignores --limit)."),
    json_output: bool = typer.Option(False, "--json", help="Print the plans as one JSON array (same as the global --json)."),
) -> None:
    """List a project's migration plans, newest first (GET /v1/migration-plans/{tenant}/projects/{project}).

    The table shows PLAN ID, FROM and TO version, how many CLASSES and RULES the plan maps, and when
    it was UPDATED. --from / --to keep only the plans between those versions. --json prints the
    matching plans as one JSON array (rule bodies left out — the rule count is kept).
    """
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    versions = list_versions(client, tenant_slug, project_id)
    from_id = to_id = None
    if from_ref is not None or to_ref is not None:
        version_tags = _version_tags(client, tenant_slug, project_id)
        if from_ref is not None:
            from_id = _resolve_version_id(versions, version_tags, from_ref, "--from")
        if to_ref is not None:
            to_id = _resolve_version_id(versions, version_tags, to_ref, "--to")

    labels = version_labels(versions)
    plans = sort_plans(
        filter_plans(
            [summarize_plan(plan, labels) for plan in _project_plans(client, tenant_slug, project_id)],
            from_version_id=from_id,
            to_version_id=to_id,
        )
    )
    shown = plans if all_plans else plans[:limit]
    if json_output or json_mode_from_context(ctx):
        emit_json(list(shown))
        return
    typer.echo(render_plan_list(shown, total=len(plans)))


@app.command("counts")
def count_plans(
    ctx: typer.Context,
    project_ref: Optional[str] = typer.Option(
        None, "--project", metavar="PROJECT", help="Only this project (slug or UUID): one plan-list request."
    ),
    json_output: bool = typer.Option(False, "--json", help="Print the counts as one JSON object (same as the global --json)."),
) -> None:
    """Count migration plans per project: PLANS, distinct CLASSES mapped, and RULES.

    Without --project every project of the tenant is listed (most plans first), one
    GET /v1/migration-plans/{tenant}/projects/{project} per project. --project rolls up a single
    project in one plan-list request. The server records no plan status, so no published / draft /
    deprecated split is shown. --json prints ``{"projects": [...], "total": {plans, rules}}``.
    """
    client, tenant_slug = tenant_scoped_client(ctx)
    if project_ref is not None:
        project_id = resolve_project_uuid(client, tenant_slug, project_ref)
        projects: list[dict[str, Any]] = [{"id": str(project_id), "slug": project_ref.strip()}]
    else:
        projects = [p for p in list_projects(client, tenant_slug) if isinstance(p, dict) and p.get("id")]
    rows = sort_counts(
        [count_project_plans(project, _project_plans(client, tenant_slug, str(project["id"]))) for project in projects]
    )
    if json_output or json_mode_from_context(ctx):
        total = {key: sum(int(row[key]) for row in rows) for key in ("plans", "rules")}
        emit_json({"projects": list(rows), "total": total})
        return
    typer.echo(render_plan_counts(rows))
