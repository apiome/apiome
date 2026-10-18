"""The catalog dependency graph from the command line — CDG-3.2 (#5967), CDG-3.3 (#5968).

``apiome graph impact --project <slug> --operation "GET /pets/{id}"`` asks what a change affects:
the consumers and dependents it reaches, directly and transitively, and the evidence it
invalidates (``POST …/blast-radius``).

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
from apiome_cli.client.graph import (
    dependency_rows,
    evidence_rows,
    impact_rows,
    operation_pointer,
    parse_depends_on,
    schema_pointer,
)
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


_IMPACT_COLUMNS = (
    ("Depth", "depth", None),
    ("Kind", "kind", None),
    ("Entity", "name", None),
    ("Edge", "edge", None),
    ("Provenance", "provenance", None),
    ("Owner", "owner", None),
)

_EVIDENCE_COLUMNS = (("Evidence", "evidence", None), ("Count", "count", None))


@app.command("impact")
def impact(
    ctx: typer.Context,
    project: str = typer.Option(..., "--project", help="The project or catalog item (slug or id) that changes."),
    operation: list[str] | None = typer.Option(
        None, "--operation", help='An operation that changes, as METHOD /path, e.g. "GET /pets/{id}" (repeatable).'
    ),
    schema: list[str] | None = typer.Option(
        None, "--schema", help="A component schema that changes, by name, e.g. Pet (repeatable)."
    ),
    pointer: list[str] | None = typer.Option(None, "--pointer", help="A raw JSON pointer that changes (repeatable)."),
    kind: str = typer.Option("project", "--kind", help="The changing entity's kind (default project)."),
    version: str | None = typer.Option(None, "--version", help="Version for the evidence; default latest published."),
    depth: int = typer.Option(3, "--depth", min=1, max=5, help="Levels of dependents to walk (1-5)."),
    provenance: list[str] | None = typer.Option(
        None, "--provenance", help="declared, derived or runtime (repeatable; default all)."
    ),
    output_format: str = _format_option(),
) -> None:
    """Ask what a change affects (POST …/blast-radius).

    Lists the entities that depend on the change — direct consumers, then transitive dependents —
    with their owner team, and how many pieces of evidence it invalidates (verification runs,
    contracts, deploy-gate evaluations, SDK targets, agent tools, mock packs, consumers on
    deprecated versions). With no ``--operation``, ``--schema`` or ``--pointer`` the whole project
    changes. ``--format json`` prints the full answer, including every edge path.
    """
    fmt = _format(ctx, output_format)
    normalised = _kind(kind)
    try:
        pointers = [operation_pointer(op) for op in operation or []]
        pointers += [schema_pointer(name) for name in schema or []]
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--operation / --schema") from exc
    pointers += [p.strip() for p in pointer or [] if p.strip()]
    body: dict[str, Any] = {"entity": {"kind": normalised, "id": project}, "pointers": pointers, "depth": depth}
    if provenance:
        body["provenance"] = list(provenance)
    if version:
        body["version"] = version
    client, tenant = tenant_scoped_client(ctx)
    answer = _expect(client.post_raw(api_paths.graph_blast_radius(tenant), json=body)).json()
    if fmt == "json":
        emit_json(answer)
        return
    rows = impact_rows(answer)
    if rows:
        emit_list_table(rows, _IMPACT_COLUMNS, empty_message="Nothing depends on this change.")
    else:
        typer.echo("Nothing depends on this change.")
    emit_list_table(evidence_rows(answer), _EVIDENCE_COLUMNS, empty_message="No evidence.")
    if answer.get("truncated"):
        typer.echo("The answer was truncated: raise --depth (at most 5) or narrow the change.", err=True)
    for warning in answer.get("warnings") or []:
        typer.echo(f"Warning: {warning}", err=True)
