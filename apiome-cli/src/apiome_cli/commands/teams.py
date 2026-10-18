"""Teams and entity ownership from the command line — CDG-2.4 (#5963).

``apiome teams list|show|create|members|assign`` manage the tenant's teams — the durable "who" that
owns catalog entities and receives their findings — with the same calls the Teams pages make
(``teams`` RBAC resource). ``members --set`` **replaces** the whole membership; ``assign`` makes a
team the confirmed owner of a project, catalog item, MCP endpoint, consumer or connector.

A refusal prints REST's message on stderr and exits with the HTTP-derived code (4xx → 2, 5xx → 1),
so ``assign`` to an unknown team fails a pipeline. ``--format json`` (or the global ``--json``)
prints the API response.
"""

from __future__ import annotations

from typing import Any

import httpx
import typer

from apiome_cli.client import api_paths
from apiome_cli.client.connectors import refusal
from apiome_cli.client.errors import http_exit_code
from apiome_cli.client.teams import (
    CODE_OWNER_TEAM_NOT_FOUND,
    ENTITY_KINDS,
    detail_lines,
    member_rows,
    parse_members,
    team_rows,
    validate_kind,
)
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, emit_list_table, json_mode_from_context

app = typer.Typer(
    name="teams",
    help="Teams: who owns catalog entities and is notified about their findings.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_TEAM_COLUMNS = (
    ("Slug", "slug", None),
    ("Name", "name", None),
    ("Members", "members", None),
    ("Links", "links", None),
)

_MEMBER_COLUMNS = (
    ("User ID", "user_id", None),
    ("Role", "role", None),
    ("Email", "email", None),
    ("Name", "name", None),
)

_FORMATS = ("table", "json")


@app.callback(invoke_without_command=True)
def teams_group(ctx: typer.Context) -> None:
    """Teams command group."""
    group_callback_without_subcommand(ctx)


def _format(ctx: typer.Context, output_format: str) -> str:
    """Resolve ``--format`` (``table`` | ``json``); the global ``--json`` wins.

    Args:
        ctx: The Typer context (carries the global ``--json`` flag).
        output_format: The ``--format`` value.

    Returns:
        ``"table"`` or ``"json"``.

    Raises:
        typer.BadParameter: The format is neither (exit 2).
    """
    if json_mode_from_context(ctx):
        return "json"
    fmt = (output_format or "table").strip().lower()
    if fmt not in _FORMATS:
        raise typer.BadParameter("must be one of table, json", param_hint="--format")
    return fmt


def _format_option() -> Any:
    """The shared ``--format`` option."""
    return typer.Option(
        "table", "--format", help="Output: table (default) or json (the API response)."
    )


def _expect(response: httpx.Response, *, hint: str | None = None) -> httpx.Response:
    """Return a successful response, or print REST's reason and exit (4xx → 2, 5xx → 1).

    Args:
        response: The response to check.
        hint: An extra line printed on stderr after the refusal, when given.

    Returns:
        The response, when it succeeded.

    Raises:
        typer.Exit: The call failed; the code is derived from the HTTP status.
    """
    if response.is_success:
        return response
    message, _code = refusal(response)
    typer.echo(f"Error: {message}", err=True)
    if hint:
        typer.echo(hint, err=True)
    raise typer.Exit(http_exit_code(response.status_code))


def _emit_members(team: dict[str, Any]) -> None:
    """Print a team's members as a table.

    Args:
        team: A team record read with its members.
    """
    emit_list_table(
        member_rows(team),
        _MEMBER_COLUMNS,
        empty_message="No members. Add some with: apiome teams members <slug> --set USER_ID",
        min_width=120,
    )


@app.command("list")
def list_teams(
    ctx: typer.Context,
    output_format: str = _format_option(),
) -> None:
    """List the workspace's teams with their member counts and owner links (GET …/teams)."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(api_paths.teams(tenant))).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_list_table(
        team_rows(body.get("teams") or []),
        _TEAM_COLUMNS,
        empty_message="No teams. Create one with: apiome teams create <name>",
        min_width=100,
    )


@app.command("show")
def show_team(
    ctx: typer.Context,
    slug: str = typer.Argument(..., help="Team slug."),
    output_format: str = _format_option(),
) -> None:
    """Show one team: its owner links and members, leads first (GET …/teams/{slug})."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(api_paths.team(tenant, slug))).json()
    if fmt == "json":
        emit_json(body)
        return
    for line in detail_lines(body):
        typer.echo(line)
    _emit_members(body)


@app.command("create")
def create_team(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="The team's display name."),
    slug: str | None = typer.Option(
        None,
        "--slug",
        help="Permanent slug (default: derived from the name). Gateway tags owner:<slug> use it.",
    ),
    description: str | None = typer.Option(None, "--description", help="What the team does."),
    contact_email: str | None = typer.Option(
        None, "--contact-email", help="The team's contact address."
    ),
    chat_url: str | None = typer.Option(
        None, "--chat-url", help="Chat channel link (absolute http(s) URL)."
    ),
    oncall_url: str | None = typer.Option(
        None, "--oncall-url", help="On-call / paging link (absolute http(s) URL)."
    ),
    docs_url: str | None = typer.Option(
        None, "--docs-url", help="Team docs or runbook link (absolute http(s) URL)."
    ),
    output_format: str = _format_option(),
) -> None:
    """Create a team (POST …/teams). The slug cannot be changed afterwards.

    A taken slug or a malformed field is refused by REST and exits 2.
    """
    fmt = _format(ctx, output_format)
    body: dict[str, Any] = {"name": name}
    for key, value in (
        ("slug", slug),
        ("description", description),
        ("contact_email", contact_email),
        ("chat_url", chat_url),
        ("oncall_url", oncall_url),
        ("docs_url", docs_url),
    ):
        if value:
            body[key] = value
    client, tenant = tenant_scoped_client(ctx)
    created = _expect(client.post_raw(api_paths.teams(tenant), json=body)).json()
    if fmt == "json":
        emit_json(created)
    else:
        typer.echo(f"Created team {created.get('name')} ({created.get('slug')}).")


@app.command("members")
def team_members(
    ctx: typer.Context,
    slug: str = typer.Argument(..., help="Team slug."),
    set_members: list[str] | None = typer.Option(
        None,
        "--set",
        help=(
            "USER_ID[:lead|:member] (repeatable; default role member). Replaces the whole "
            "membership: anyone not listed is removed."
        ),
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Remove every member (cannot be combined with --set)."
    ),
    output_format: str = _format_option(),
) -> None:
    """List a team's members, or replace them (PUT …/teams/{slug}/members).

    With no option the members are listed. ``--set`` sends the **complete** new membership — it
    does not add to the current one — and ``--clear`` empties the team. Every user must belong to
    the workspace, otherwise REST refuses the whole change (exit 2) and nothing changes.
    """
    fmt = _format(ctx, output_format)
    specs = list(set_members or [])
    if clear and specs:
        raise typer.BadParameter("cannot be combined with --set", param_hint="--clear")
    try:
        members = parse_members(specs)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--set") from exc

    client, tenant = tenant_scoped_client(ctx)
    if not specs and not clear:
        body = _expect(client.get_raw(api_paths.team(tenant, slug))).json()
    else:
        body = _expect(
            client.put_raw(api_paths.team_members(tenant, slug), json={"members": members})
        ).json()
        if fmt != "json":
            typer.echo(
                f"Team {body.get('slug', slug)} now has "
                f"{int(body.get('member_count') or len(members))} member(s).",
                err=True,
            )
    if fmt == "json":
        emit_json(body)
        return
    _emit_members(body)


@app.command("assign")
def assign_owner(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help=f"Entity kind: {', '.join(ENTITY_KINDS)}."),
    entity_id: str = typer.Argument(..., help="The entity's id."),
    team: str = typer.Option(..., "--team", help="Slug of the team that will own it."),
    output_format: str = _format_option(),
) -> None:
    """Make a team the confirmed owner of an entity (PUT …/owners/{kind}/{id}).

    The previous confirmed owner, if any, is replaced; findings for the entity are routed to the
    new team. An unknown team or entity is refused with REST's message and exits 2; an unknown
    kind is a usage error (exit 2) caught before any call.
    """
    fmt = _format(ctx, output_format)
    try:
        normalised = validate_kind(kind)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="KIND") from exc
    client, tenant = tenant_scoped_client(ctx)
    response = client.put_raw(
        api_paths.entity_owner(tenant, normalised, entity_id), json={"team": team}
    )
    hint = None
    if not response.is_success and refusal(response)[1] == CODE_OWNER_TEAM_NOT_FOUND:
        hint = "List the workspace's teams with: apiome teams list"
    body = _expect(response, hint=hint).json()
    if fmt == "json":
        emit_json(body)
        return
    owner = (body.get("owner") or {}).get("team") or {}
    typer.echo(
        f"{normalised} {entity_id} is now owned by {owner.get('name') or team} "
        f"({owner.get('slug') or team})."
    )
