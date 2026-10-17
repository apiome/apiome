"""Classes: ``apiome classes list`` (CLI 7.1, #3229) and ``classes create`` (CLI 7.3, #3231)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import typer

from apiome_cli.class_create import (
    ClassDraft,
    PropertyRef,
    VersionLocked,
    check_draft,
    check_version,
    class_body,
    class_property_body,
    merge_draft,
    missing_properties,
    normalize_tags,
    render_created,
    tags_to_create,
)
from apiome_cli.class_view import filter_classes, render_hydrated, render_lean, summary_line
from apiome_cli.cli_input import exit_field_errors, prompt_primitive, read_object_file
from apiome_cli.client import api_paths
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.list_response import fetch_list
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.primitive_cache import load_primitives
from apiome_cli.client.project_version_resolve import list_versions, resolve_project_uuid
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE, EXIT_VERSION_LOCKED
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.property_create import FieldError, PropertyDraft, PropertyInvalid
from apiome_cli.property_create import request_body as property_request_body
from apiome_cli.property_show import PropertyNotFound, find_property
from apiome_cli.terminal import confirm_action, echo_notice, interactive_enabled
from apiome_cli.version_fork import ForkError, find_source_version

app = typer.Typer(
    name="classes",
    help="List a version's classes and create new ones.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def classes_group(ctx: typer.Context) -> None:
    """Classes command group."""
    group_callback_without_subcommand(ctx)


def _version(client: Any, tenant_slug: str, project_id: Any, ref: str) -> dict[str, Any]:
    """The version ``ref`` names (label with or without ``v``, UUID, or version tag); exit 2 if none."""
    tags = client.get(api_paths.version_tags(tenant_slug, project_id)).json()
    try:
        return find_source_version(
            list_versions(client, tenant_slug, project_id), tags if isinstance(tags, list) else [], ref
        ).version
    except ForkError as exc:
        typer.echo(f"No version or version tag {ref!r} in this project.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


@app.command("list")
def list_classes(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    version_ref: str = typer.Argument(..., metavar="VERSION", help="Version label (2.1.0 or v2.1.0), UUID or tag."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Only classes with this tag (any case)."),
    search: Optional[str] = typer.Option(None, "--search", help="Case-insensitive text in the name or description."),
    with_properties: bool = typer.Option(
        False, "--with-properties", help="Show every class's properties (one call for the whole version)."
    ),
    limit: int = typer.Option(DEFAULT_PAGE_LIMIT, "--limit", min=1, help="Show at most this many classes."),
    all_rows: bool = typer.Option(False, "--all", help="Show every match (ignores --limit)."),
) -> None:
    """List a version's classes with their property count, tags and description.

    --with-properties adds each class's properties (name, type, required), nested ones indented.

    --json prints the classes exactly as the API returns them (after the filters and --limit).
    """
    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    version = _version(client, tenant_slug, project_id, version_ref)
    if with_properties:
        payload = client.get(api_paths.classes_with_properties_tags(tenant_slug, version["id"])).json()
    else:
        payload = client.get(f"{api_paths.classes(tenant_slug)}?version_id={version['id']}").json()
    classes = payload if isinstance(payload, list) else []
    matched = filter_classes(classes, tag=tag, search=search)
    shown = matched if all_rows else matched[:limit]
    if json_mode_from_context(ctx):
        emit_json(shown)
        return
    where = f"{project_ref} {version.get('version_id') or version_ref}"
    lines = render_hydrated(shown) if with_properties else render_lean(shown)
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(summary_line(shown=len(shown), matched=len(matched), total=len(classes), where=where))
    typer.echo("\n".join(lines))


def _is_frozen(client: Any, tenant_slug: str, project_id: Any, version_id: str) -> bool:
    """Whether the version's OpenAPI is frozen (``GET …/freeze-schema``); unknown counts as not frozen."""
    try:
        response = client.get_raw(api_paths.version_freeze(tenant_slug, project_id, version_id))
        return bool(response.is_success and response.json().get("frozen"))
    except Exception:  # noqa: BLE001 - an older server without the endpoint: the publish check still applies
        return False


def _prompt_class_name(existing: Sequence[str]) -> str:
    """Ask for the class name until it is given and new in the version."""
    while True:
        name = typer.prompt("? Class name", err=True).strip()
        errors = check_draft(ClassDraft(name=name, description=None), existing_classes=existing, library=[])
        if not errors:
            return name
        typer.echo(f"  {errors[0].message}", err=True)


def _prompt_properties(library: Sequence[Mapping[str, Any]], *, create_missing: bool) -> list[PropertyRef]:
    """Pick properties one at a time (part of a name lists matches), each with a required toggle.

    A name the project lacks is offered for creation when ``create_missing``; an empty answer ends.
    """
    picked: list[PropertyRef] = []
    names = [str(p.get("name")) for p in library]
    while True:
        text = typer.prompt("? Property (type to search, empty to finish)", default="", show_default=False, err=True).strip()
        if not text:
            return picked
        try:
            name = str(find_property(library, text, project="").get("name"))
        except PropertyNotFound:
            matches = [n for n in names if text.lower() in n.lower()]
            if len(matches) == 1:
                name = matches[0]
            elif matches:
                typer.echo(f"  Matches: {', '.join(sorted(matches)[:10])}", err=True)
                continue
            elif create_missing:
                name = text
            else:
                typer.echo(f"  No property matches {text!r} (pass --create-missing to create it).", err=True)
                continue
        if any(ref.name == name for ref in picked):
            typer.echo(f"  {name} is already picked.", err=True)
            continue
        required = typer.confirm(f"  Required in this class? ({name})", default=False, err=True)
        picked.append(PropertyRef(name, required))


def _prompt_draft(
    draft: ClassDraft, existing: Sequence[str], library: Sequence[Mapping[str, Any]], *, create_missing: bool
) -> ClassDraft:
    """Ask for what the flags left out: name, description, tags, then properties."""
    name = draft.name or _prompt_class_name(existing)
    description = draft.description
    if description is None:
        description = typer.prompt("? Description", default="", show_default=False, err=True).strip() or None
    tags = draft.tags or normalize_tags(typer.prompt("? Tags (comma-separated)", default="", show_default=False, err=True))
    properties = draft.properties
    if not properties and typer.confirm("? Add properties now?", default=True, err=True):
        properties = _prompt_properties(library, create_missing=create_missing)
    return ClassDraft(name=name, description=description, tags=tags, properties=properties)


def _create_missing_properties(
    client: Any, tenant_slug: str, project_id: Any, names: Sequence[str]
) -> list[dict[str, Any]]:
    """Create each missing library property from a primitive chosen at a prompt (``--create-missing``)."""
    if not names:
        return []
    primitives = load_primitives(client, tenant_slug)
    created = []
    for name in names:
        typer.echo(f"Property '{name}' does not exist yet; choose its primitive.", err=True)
        primitive = prompt_primitive(primitives)
        body = property_request_body(PropertyDraft(name, str(primitive.get("name")), None, []), primitive)
        response = client.post_raw(api_paths.properties(tenant_slug, project_id), json=body)
        exit_on_api_error(response)
        created.append(response.json())
    return created


def _attach(client: Any, tenant_slug: str, project_id: Any, class_id: str, draft: ClassDraft, library: Mapping[str, Any]) -> list[str]:
    """Attach the properties and tags to the new class; the project tags created on the way.

    Raises:
        RuntimeError: Naming the step that failed (the caller rolls the class back).
    """
    for ref in draft.properties:
        response = client.post_raw(
            api_paths.class_properties(tenant_slug, class_id), json=class_property_body(library[ref.name], ref.required)
        )
        if not response.is_success:
            raise RuntimeError(f"adding property {ref.name!r} failed (HTTP {response.status_code})")
    if not draft.tags:
        return []
    project_tags = client.get(api_paths.project_tags(tenant_slug, project_id)).json()
    project_tags = project_tags if isinstance(project_tags, list) else []
    created = []
    for tag in tags_to_create(draft, project_tags):
        response = client.post_raw(api_paths.project_tags(tenant_slug, project_id), json={"name": tag})
        if not response.is_success:
            raise RuntimeError(f"creating tag {tag!r} failed (HTTP {response.status_code})")
        project_tags.append(response.json())
        created.append(tag)
    by_name = {str(t.get("name") or "").lower(): t for t in project_tags}
    for tag in draft.tags:
        response = client.post_raw(api_paths.class_tags(tenant_slug, class_id), json={"tag_id": str(by_name[tag]["id"])})
        if not response.is_success:
            raise RuntimeError(f"tagging the class {tag!r} failed (HTTP {response.status_code})")
    return created


@app.command("create")
def create_class(
    ctx: typer.Context,
    project_ref: str = typer.Argument(..., metavar="PROJECT", help="Project slug or UUID."),
    version_ref: str = typer.Argument(..., metavar="VERSION", help="Draft version: label (±v), UUID or tag."),
    name: Optional[str] = typer.Option(None, "--name", help="Class name (unique in the version)."),
    description: Optional[str] = typer.Option(None, "--description", help="What the class represents."),
    tag: Optional[list[str]] = typer.Option(None, "--tag", help="A project tag (repeatable); created if missing."),
    prop: Optional[list[str]] = typer.Option(
        None, "--property", help="A project property, `name` or `name:required` (repeatable)."
    ),
    from_file: Optional[Path] = typer.Option(
        None, "--from-file", help="JSON or YAML class spec: name, description, tags, properties."
    ),
    create_missing: bool = typer.Option(
        False, "--create-missing", help="Create missing properties, asking for each one's primitive (terminal only)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the final question the prompts ask."),
) -> None:
    """Create a class in a draft version, with its properties and tags (POST /v1/classes/{tenant}).

    On a terminal, missing fields are asked for. Properties must exist, unless --create-missing.

    A published or frozen version exits 6; field problems exit 7.

    If attaching a property or tag fails, the class is deleted again (exit 1).
    """
    if create_missing and not interactive_enabled():
        typer.echo("--create-missing asks for each property's primitive, so it needs a terminal.", err=True)
        raise typer.Exit(EXIT_USAGE)
    try:
        draft = merge_draft(
            name=name,
            description=description,
            tags=tag or [],
            properties=prop or [],
            document=read_object_file(from_file, shape="class spec (name, description, tags, properties)")
            if from_file
            else None,
        )
    except PropertyInvalid as exc:
        exit_field_errors(exc.errors)

    client, tenant_slug = tenant_scoped_client(ctx)
    project_id = resolve_project_uuid(client, tenant_slug, project_ref)
    version = _version(client, tenant_slug, project_id, version_ref)
    try:
        check_version(version, frozen=_is_frozen(client, tenant_slug, project_id, str(version["id"])))
    except VersionLocked as exc:
        typer.echo(f"{exc} Nothing was created.", err=True)
        raise typer.Exit(EXIT_VERSION_LOCKED) from exc
    classes_now = client.get(f"{api_paths.classes(tenant_slug)}?version_id={version['id']}").json()
    existing = [str(c.get("name")) for c in classes_now] if isinstance(classes_now, list) else []
    library_items, _total = fetch_list(client, api_paths.properties(tenant_slug, project_id))
    prompted = interactive_enabled() and draft.name is None
    if prompted:
        draft = _prompt_draft(draft, existing, library_items, create_missing=create_missing)

    library_names = [str(p.get("name")) for p in library_items]
    errors = check_draft(draft, existing_classes=existing, library=library_names, allow_missing=create_missing)
    if errors:
        exit_field_errors(errors)
    if prompted:
        count = len(draft.properties)
        confirm_action(
            f"Create class '{draft.name}' with {count} propert{'y' if count == 1 else 'ies'} in {version.get('version_id')}?",
            skip=yes,
            default=True,
        )
    new_properties = _create_missing_properties(client, tenant_slug, project_id, missing_properties(draft, library_names))
    library = {str(p.get("name")): p for p in [*library_items, *new_properties]}

    response = client.post_raw(api_paths.classes(tenant_slug), json=class_body(draft, str(version["id"])))
    if response.status_code == 409:
        exit_field_errors([FieldError("name", f"the version already has a class '{draft.name}'")])
    exit_on_api_error(response)
    created = response.json()
    try:
        created_tags = _attach(client, tenant_slug, project_id, str(created["id"]), draft, library)
    except RuntimeError as exc:
        client.delete_raw(api_paths.class_record(tenant_slug, str(created["id"])))
        typer.echo(
            f"Creating class '{draft.name}' failed: {exc}. The class was deleted again, so the name is free to retry "
            "(project tags and properties created on the way are kept).",
            err=True,
        )
        raise typer.Exit(EXIT_ERROR) from exc
    if new_properties:
        echo_notice(f"Created properties: {', '.join(str(p.get('name')) for p in new_properties)}")
    if json_mode_from_context(ctx):
        emit_json(
            {
                "class": created,
                "properties": [{"name": r.name, "required": r.required} for r in draft.properties],
                "tags": draft.tags,
                "createdTags": created_tags,
                "createdProperties": [str(p.get("name")) for p in new_properties],
            }
        )
        return
    typer.echo(render_created(str(created.get("name", draft.name)), len(draft.properties), created_tags))
