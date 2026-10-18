"""The catalog dependency graph from the command line — CDG-3.2 (#5967).

``apiome graph declare <kind> <entity> --depends-on <slug>`` sets what an entity declares it
depends on (its ``manual`` declarations, ``PUT …/dependencies``), and ``apiome graph dependencies``
lists every declaration it has — manual, from its spec's ``x-apiome-depends-on`` and from a
Backstage ``catalog-info.yaml`` — with the references that named nothing.

A refusal prints REST's message on stderr and exits with the HTTP-derived code (4xx → 2, 5xx → 1).
``--format json`` (or the global ``--json``) prints the API response.
"""

from __future__ import annotations

from typing import Any

import httpx
import typer

from apiome_cli.client import api_paths
from apiome_cli.client.connectors import refusal
from apiome_cli.client.errors import http_exit_code
from apiome_cli.client.graph import dependency_rows, parse_depends_on
from apiome_cli.client.teams import ENTITY_KINDS, validate_kind
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, emit_list_table, json_mode_from_context

app = typer.Typer(
    name="graph",
    help="The dependency graph: declare and list what an API depends on.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_COLUMNS = (
    ("Status", "status", None),
    ("Edge", "edge", None),
    ("Target", "target", None),
    ("Pointer", "pointer", None),
    ("Source", "source", None),
)

_FORMATS = ("table", "json")


@app.callback(invoke_without_command=True)
def graph_group(ctx: typer.Context) -> None:
    """Graph command group."""
    group_callback_without_subcommand(ctx)


def _format(ctx: typer.Context, output_format: str) -> str:
    """Resolve ``--format`` (``table`` | ``json``); the global ``--json`` wins.

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
    return typer.Option("table", "--format", help="Output: table (default) or json (the API response).")


def _kind(kind: str) -> str:
    """Normalise ``KIND`` or exit 2 before any call."""
    try:
        return validate_kind(kind)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="KIND") from exc


def _expect(response: httpx.Response) -> httpx.Response:
    """Return a successful response, or print REST's reason and exit (4xx → 2, 5xx → 1)."""
    if response.is_success:
        return response
    message, _code = refusal(response)
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(http_exit_code(response.status_code))


def _emit(body: dict[str, Any], fmt: str) -> None:
    """Print the dependencies as JSON or a table."""
    if fmt == "json":
        emit_json(body)
        return
    emit_list_table(dependency_rows(body), _COLUMNS, empty_message="No declared dependencies.")


@app.command("declare")
def declare(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help=f"Entity kind: {', '.join(ENTITY_KINDS)}."),
    entity: str = typer.Argument(..., help="The entity's id, or a project or catalog item's slug."),
    depends_on: list[str] | None = typer.Option(
        None,
        "--depends-on",
        help=(
            "`SLUG[#POINTER]` or `KIND:ID[#POINTER]` (repeatable). Replaces the entity's manual "
            "declarations: anything not listed is removed."
        ),
    ),
    note: str | None = typer.Option(None, "--note", help="A note attached to every --depends-on entry."),
    clear: bool = typer.Option(
        False, "--clear", help="Remove every manual declaration (cannot be combined with --depends-on)."
    ),
    output_format: str = _format_option(),
) -> None:
    """Declare what an entity depends on (PUT …/entities/{kind}/{entity}/dependencies).

    ``--depends-on`` sends the **complete** list of the entity's manual declarations — it does not
    add to them — and ``--clear`` removes them. Declarations from the entity's spec and from
    Backstage files are not touched. A target that does not exist is not an error: it is listed as
    ``unresolved: not-found``.
    """
    fmt = _format(ctx, output_format)
    normalised = _kind(kind)
    specs = list(depends_on or [])
    if clear and specs:
        raise typer.BadParameter("cannot be combined with --depends-on", param_hint="--clear")
    if not clear and not specs:
        raise typer.BadParameter("give at least one --depends-on, or --clear", param_hint="--depends-on")
    try:
        entries = [parse_depends_on(spec, note=note) for spec in specs]
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--depends-on") from exc
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(
        client.put_raw(api_paths.graph_dependencies(tenant, normalised, entity), json={"dependencies": entries})
    ).json()
    if fmt != "json":
        unresolved = len(body.get("unresolved") or [])
        typer.echo(
            f"{normalised} {entity} now declares {len(entries)} manual dependenc{'y' if len(entries) == 1 else 'ies'}"
            + (f"; {unresolved} unresolved." if unresolved else "."),
            err=True,
        )
    _emit(body, fmt)


@app.command("dependencies")
def dependencies(
    ctx: typer.Context,
    kind: str = typer.Argument(..., help=f"Entity kind: {', '.join(ENTITY_KINDS)}."),
    entity: str = typer.Argument(..., help="The entity's id, or a project or catalog item's slug."),
    output_format: str = _format_option(),
) -> None:
    """List what an entity declares it depends on, from every source (GET …/dependencies)."""
    fmt = _format(ctx, output_format)
    normalised = _kind(kind)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(api_paths.graph_dependencies(tenant, normalised, entity))).json()
    _emit(body, fmt)
