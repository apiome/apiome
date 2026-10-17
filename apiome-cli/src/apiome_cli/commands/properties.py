"""Properties list, show, get, create and update commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

import typer

from apiome_cli.client import api_paths
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.primitive_cache import load_primitives
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import (
    EXIT_PROPERTY_BREAKING,
    EXIT_PROPERTY_INVALID,
    EXIT_UPDATE_CONFLICT,
    EXIT_USAGE,
)
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import (
    RecordField,
    emit_json,
    emit_record_response,
    json_mode_from_context,
)
from apiome_cli.import_.yaml_load import safe_load
from apiome_cli.property_create import (
    FieldError,
    PropertyDraft,
    PropertyInvalid,
    check_examples,
    check_name,
    find_primitive,
    merge_draft,
    property_schema,
    request_body,
    search_primitives,
    split_examples,
)
from apiome_cli.property_show import PropertyNotFound, find_property, render_show
from apiome_cli.property_update import (
    BreakingChange,
    PropertyUpdateError,
    changes_from_file,
    changes_from_flags,
    check_changes,
    check_primitive_change,
    expected_updated_at,
    field_changes,
    render_diff,
    summary,
)
from apiome_cli.property_update import request_body as update_request_body
from apiome_cli.property_view import UsageUnavailable, filter_properties, render_table
from apiome_cli.terminal import confirm_action, echo_notice, interactive_enabled

app = typer.Typer(
    name="properties",
    help="List, show, fetch, create and update project properties.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def properties_group(ctx: typer.Context) -> None:
    """Properties command group."""
    group_callback_without_subcommand(ctx)


def _sorted_json_value(value: object) -> object:
    """Recursively sort dictionary keys for stable JSON output."""
    if isinstance(value, dict):
        return {key: _sorted_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_json_value(item) for item in value]
    return value


def _format_value_as_json(value: object) -> str:
    """Format a table value as compact JSON."""
    if value is None:
        return ""
    return json.dumps(_sorted_json_value(value), separators=(",", ":"))


_PROPERTY_RECORD_FIELDS: tuple[RecordField, ...] = (
    ("ID", "id", None),
    ("Tenant", "tenant_id", None),
    ("Name", "name", None),
    ("Description", "description", None),
    ("Body", "body", _format_value_as_json),
    ("Enabled", "enabled", lambda value: "" if value is None else str(value)),
    ("Created On", "created_on", None),
    ("Updated On", "updated_on", None),
)


@app.command("list")
def list_properties(
    ctx: typer.Context,
    project_ref: Optional[str] = typer.Argument(
        None, metavar="PROJECT", help="Project slug or UUID (or pass --project-id)."
    ),
    project_id: Optional[UUID] = typer.Option(None, "--project-id", help="Project UUID (the older form)."),
    type_filter: Optional[str] = typer.Option(
        None,
        "--type",
        "--primitive",
        help="Only properties of this schema type, e.g. string, uuid, date-time, array<string>.",
    ),
    search: Optional[str] = typer.Option(None, "--search", help="Case-insensitive text in the name or description."),
    unused: bool = typer.Option(False, "--unused", help="Only properties no class uses."),
    limit: int = typer.Option(DEFAULT_PAGE_LIMIT, "--limit", min=1, help="Show at most this many."),
    all_rows: bool = typer.Option(False, "--all", help="Show every match (ignores --limit)."),
) -> None:
    """List a project's properties with their type and the classes that use them (GET /v1/properties/{tenant}/{project}).

    Properties have no tags and are not bound to primitives, so the TYPE column is read from each
    property's JSON Schema (its format, else its type).
    """
    if project_ref is None and project_id is None:
        typer.echo("Name the project: apiome properties list <project>.", err=True)
        raise typer.Exit(EXIT_USAGE)
    client, tenant_slug = tenant_scoped_client(ctx)
    pid = project_id if project_id is not None else resolve_project_uuid(client, tenant_slug, str(project_ref))
    items, _total = fetch_list(client, api_paths.properties(tenant_slug, pid))
    try:
        matched = filter_properties(items, type_filter=type_filter, search=search, unused=unused)
    except UsageUnavailable as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    shown = matched if all_rows else matched[:limit]
    if json_mode_from_context(ctx):
        emit_json({"total": len(matched), "items": shown})
        return
    typer.echo(
        render_table(shown, matched=len(matched), project=str(project_ref or project_id), total=len(items))
    )


@app.command("show")
def show_property(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    property_ref: str = typer.Argument(..., metavar="PROPERTY", help="Property name or UUID."),
) -> None:
    """Show one property: its type, constraints, examples, description and the classes that use it.

    The name is matched exactly, then ignoring case; a miss suggests the closest names (exit 2).
    ``--json`` prints the full property with ``usage[]`` of ``{class_name, attribute_name, required}``.
    """
    _client, _tenant, _pid, _items, prop = _resolve_property(ctx, project_ref, property_ref)
    if json_mode_from_context(ctx):
        emit_json(prop)
        return
    typer.echo(render_show(prop))


@app.command("get")
def get_property(
    ctx: typer.Context,
    property_id: UUID = typer.Argument(..., help="Property UUID."),
    project_id: UUID = typer.Option(..., "--project-id", help="Project UUID."),
) -> None:
    """Fetch one property by id (GET /v1/properties/{tenant_slug}/{project_id}/{id})."""
    client, tenant_slug = tenant_scoped_client(ctx)
    response = client.get(api_paths.property_record(tenant_slug, project_id, property_id))
    emit_record_response(
        response.json(),
        _PROPERTY_RECORD_FIELDS,
        json_mode=json_mode_from_context(ctx),
    )


def _read_property_file(path: Path) -> dict[str, Any]:
    """Read ``--from-file`` (one JSON or YAML object), or exit 2 saying why it cannot be used."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Cannot read {path}: {exc.strerror or exc}.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    try:
        document = safe_load(text)
    except ValueError as exc:
        typer.echo(f"{path} is not valid JSON or YAML: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    if not isinstance(document, dict):
        typer.echo(f"{path} must hold one property object (name, primitive, description, examples).", err=True)
        raise typer.Exit(EXIT_USAGE)
    return document


def _exit_invalid(errors: Sequence[FieldError]) -> None:
    """Print one ``field: message`` line per problem and exit 7 (nothing was created)."""
    for error in errors:
        typer.echo(str(error), err=True)
    typer.echo("Nothing was created.", err=True)
    raise typer.Exit(EXIT_PROPERTY_INVALID)


def _prompt_name(existing: Sequence[str]) -> str:
    """Ask for the name until it is given and new in the project."""
    while True:
        name = typer.prompt("? Name", err=True).strip()
        errors = check_name(name, existing)
        if not errors:
            return name
        typer.echo(f"  {errors[0].message}", err=True)


def _prompt_primitive(primitives: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Ask for the primitive; part of a name lists the matches to choose from, until one fits."""
    while True:
        text = typer.prompt("? Primitive (type to search)", err=True).strip()
        try:
            return find_primitive(primitives, text)
        except PropertyInvalid:
            pass
        matches = search_primitives(primitives, text)
        if len(matches) == 1:
            return find_primitive(primitives, matches[0])
        typer.echo(
            f"  Matches: {', '.join(matches)}" if matches else f"  No primitive matches {text!r}.",
            err=True,
        )


def _prompt_draft(
    draft: PropertyDraft, existing: Sequence[str], primitives: Sequence[Mapping[str, Any]]
) -> tuple[PropertyDraft, Optional[Mapping[str, Any]]]:
    """Ask for what the flags left out: name and primitive, then description and examples.

    Returns:
        The completed draft, and the primitive when it was chosen here (else ``None``).
    """
    name = draft.name or _prompt_name(existing)
    chosen = None if draft.primitive else _prompt_primitive(primitives)
    description = draft.description
    if description is None:
        description = typer.prompt("? Description", default="", show_default=False, err=True).strip() or None
    examples = draft.examples
    if not examples:
        examples = split_examples(typer.prompt("? Examples (comma-separated)", default="", show_default=False, err=True))
    primitive = str(chosen.get("name")) if chosen else draft.primitive
    return PropertyDraft(name=name, primitive=primitive, description=description, examples=examples), chosen


@app.command("create")
def create_property(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    name: Optional[str] = typer.Option(None, "--name", help="Property name (unique in the project)."),
    primitive: Optional[str] = typer.Option(
        None, "--primitive", help="Primitive whose schema the property copies: name, UUID or $id."
    ),
    description: Optional[str] = typer.Option(None, "--description", help="What the property holds."),
    example: Optional[list[str]] = typer.Option(
        None, "--example", help="An example value (repeatable); read as JSON when it parses, else as text."
    ),
    from_file: Optional[Path] = typer.Option(
        None, "--from-file", help="JSON or YAML object with name, primitive, description and examples."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the final question the prompts ask."),
) -> None:
    """Create a property from a primitive (POST /v1/properties/{tenant}/{project}).

    The primitive's JSON Schema is copied in; each example is checked against it locally.

    On a terminal, missing fields are asked for. Properties have no tags.

    Exit 7, one line per field, when the property is invalid.
    """
    try:
        draft = merge_draft(
            name=name,
            primitive=primitive,
            description=description,
            examples=example or [],
            document=_read_property_file(from_file) if from_file else None,
        )
    except PropertyInvalid as exc:
        _exit_invalid(exc.errors)
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    items, _total = fetch_list(client, api_paths.properties(tenant_slug, project_id))
    existing = [str(p.get("name")) for p in items]
    primitives = load_primitives(client, tenant_slug)
    prompted = interactive_enabled() and (draft.name is None or draft.primitive is None)
    chosen: Optional[Mapping[str, Any]] = None
    if prompted:
        draft, chosen = _prompt_draft(draft, existing, primitives)

    errors = check_name(draft.name, existing)
    try:
        chosen = chosen or find_primitive(primitives, draft.primitive)
    except PropertyInvalid as exc:
        errors += exc.errors
    if chosen is not None:
        example_errors, warnings = check_examples(property_schema(chosen, []), draft.examples)
        errors += example_errors
        for warning in warnings:
            echo_notice(warning)
    if errors:
        _exit_invalid(errors)

    if prompted:
        confirm_action(f"Create property '{draft.name}' from primitive '{chosen.get('name')}'?", skip=yes, default=True)
    response = client.post_raw(api_paths.properties(tenant_slug, project_id), json=request_body(draft, chosen))
    if response.status_code == 409:
        _exit_invalid([FieldError("name", f"the project already has a property '{draft.name}'")])
    exit_on_api_error(response)
    created = response.json()
    if json_mode_from_context(ctx):
        emit_json(created)
        return
    typer.echo(f"✔ Created property '{created.get('name', draft.name)}'.")


def _resolve_property(ctx: typer.Context, project_ref: str, property_ref: str) -> tuple[Any, str, UUID, list, dict]:
    """The client, tenant, project id, the project's property list, and the property as read.

    Exits 2 (with did-you-mean) when the property is not found.
    """
    client, tenant_slug = tenant_scoped_client(ctx)
    pid = resolve_project_uuid(client, tenant_slug, project_ref)
    items, _total = fetch_list(client, api_paths.properties(tenant_slug, pid))
    try:
        match = find_property(items, property_ref, project=project_ref)
    except PropertyNotFound as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    prop = client.get(api_paths.property_record(tenant_slug, pid, str(match["id"]))).json()
    return client, tenant_slug, pid, items, prop


def _exit_on_property_conflict(response: Any, *, name: str, from_file: Optional[Path]) -> None:
    """Exit 6 on ``update_conflict`` (re-fetch hint), or 7 when a rename hit a taken name."""
    if response.status_code != 409:
        return
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if isinstance(detail, dict) and detail.get("code") == "update_conflict":
        source = f"{from_file} was read" if from_file else "it was read"
        typer.echo(
            f"Conflict: property {name!r} changed since {source} (server updated_at "
            f"{detail.get('current_updated_at') or 'unknown'}). Nothing was written.\n"
            "Re-fetch it with `apiome properties show <project> <property> --json > property.json`, "
            "re-apply your edit, and run the update again.",
            err=True,
        )
        raise typer.Exit(EXIT_UPDATE_CONFLICT)
    _exit_invalid([FieldError("name", "the project already has a property with that name")])


@app.command("update")
def update_property(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    property_ref: str = typer.Argument(..., metavar="PROPERTY", help="Property name or UUID."),
    name: Optional[str] = typer.Option(None, "--name", help="Rename the property."),
    primitive: Optional[str] = typer.Option(
        None, "--primitive", help="Re-copy the schema from this primitive (name, UUID or $id); keeps examples."
    ),
    description: Optional[str] = typer.Option(None, "--description", help="New description; an empty string clears it."),
    add_example: Optional[list[str]] = typer.Option(None, "--add-example", help="Add an example (repeatable)."),
    remove_example: Optional[list[str]] = typer.Option(None, "--remove-example", help="Remove an example (repeatable)."),
    required_everywhere: Optional[bool] = typer.Option(
        None,
        "--required-everywhere/--optional-everywhere",
        help="Mark it required (or optional) on every class attribute using it, in unpublished versions.",
    ),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from-file",
        help="Apply an edited `properties show --json` dump (JSON or YAML); exit 6 if it changed since.",
    ),
    allow_breaking: bool = typer.Option(
        False, "--allow-breaking", help="Change the primitive even though classes require the property."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the changes as a diff without sending them."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the question --primitive and --required-everywhere ask."),
) -> None:
    """Change a property's name, description, primitive or examples (PUT /v1/properties/{tenant}/{project}/{id}).

    Only changed fields are sent. A concurrent edit since the read (or the file) exits 6.

    --primitive is refused (exit 6) while a class requires the property, unless --allow-breaking.

    Field problems exit 7. Properties have no tags.
    """
    field_flags = (name, primitive, description, add_example, remove_example, required_everywhere)
    flags_given = any(value not in (None, []) for value in field_flags)
    if from_file is not None and flags_given:
        typer.echo("--from-file cannot be combined with field flags.", err=True)
        raise typer.Exit(EXIT_USAGE)
    if from_file is None and not flags_given:
        typer.echo(
            "Nothing to update: pass --name, --primitive, --description, --add-example, --remove-example, "
            "--required-everywhere / --optional-everywhere or --from-file.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)
    document = _read_property_file(from_file) if from_file else None

    client, tenant_slug, pid, items, prop = _resolve_property(ctx, project_ref, property_ref)
    others = [str(p.get("name")) for p in items if str(p.get("id")) != str(prop.get("id"))]
    chosen: Optional[Mapping[str, Any]] = None
    try:
        if primitive is not None:
            chosen = find_primitive(load_primitives(client, tenant_slug), primitive)
        if document is not None:
            changes = changes_from_file(prop, document)
            precondition = expected_updated_at(document)
        else:
            changes = changes_from_flags(
                prop,
                name=name,
                description=description,
                primitive=chosen,
                add_examples=add_example or [],
                remove_examples=remove_example or [],
            )
            precondition = prop.get("updated_at")
    except PropertyUpdateError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except PropertyInvalid as exc:
        _exit_invalid(exc.errors)
    primitive_changed = chosen is not None and "data" in changes
    if primitive_changed:
        try:
            check_primitive_change(prop.get("usage"), allow_breaking=allow_breaking)
        except BreakingChange as exc:
            typer.echo(str(exc), err=True)
            for use in exc.uses:
                typer.echo(f"  {use}  (required)", err=True)
            typer.echo("Nothing was changed. Pass --allow-breaking to change it anyway.", err=True)
            raise typer.Exit(EXIT_PROPERTY_BREAKING) from exc

    errors = check_changes(prop, changes, others)
    if errors:
        _exit_invalid(errors)

    json_mode = json_mode_from_context(ctx)
    body = update_request_body(changes, precondition, required_everywhere)
    if dry_run:
        if json_mode:
            emit_json(
                {
                    "dryRun": True,
                    "propertyId": str(prop.get("id")),
                    "changes": [
                        {"field": row.field, "before": row.before, "after": row.after}
                        for row in field_changes(prop, changes)
                    ],
                    "request": body,
                }
            )
        else:
            typer.echo(render_diff(prop, changes, required_everywhere))
        return
    if not changes and required_everywhere is None:
        echo_notice(f"Property {prop.get('name')!r} already matches; nothing to update.")
        if json_mode:
            emit_json(prop)
        return

    if primitive_changed or required_everywhere is not None:
        typer.echo(render_diff(prop, changes, required_everywhere), err=True)
        if primitive_changed:
            typer.echo(
                "Classes keep their own copy of the schema: changing the primitive here does not change them.",
                err=True,
            )
        confirm_action("Apply these changes?", skip=yes)

    response = client.put_raw(api_paths.property_record(tenant_slug, pid, str(prop.get("id"))), json=body)
    _exit_on_property_conflict(response, name=str(prop.get("name")), from_file=from_file)
    exit_on_api_error(response)
    updated = response.json()
    if json_mode:
        emit_json(updated)
        return
    typer.echo(summary(prop, changes, updated.get("required_everywhere_result")))
