"""``apiome data`` — records stored against a published class (CLI 10.x, epic #3183).

``data create`` (CLI 10.3, #3255): the rules live in :mod:`apiome_cli.data_record`; this module
reads the input, resolves ``--class <project>/<version>/<Class>`` with
``GET /v1/data/{tenant}/classes``, validates the payload against the class's frozen JSON Schema,
then ``POST /v1/data/{tenant}/records``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, NoReturn, Optional
from urllib.parse import urlencode

import typer

from apiome_cli import terminal
from apiome_cli.cli_input import exit_field_errors, read_object_file, read_object_text
from apiome_cli.client import api_paths
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.data_record import (
    ClassAddress,
    DataInputError,
    SchemaUnusable,
    build_payload,
    find_class,
    parse_class_address,
    render_created,
    render_valid,
    validate_record,
)
from apiome_cli.exit_codes import EXIT_RECORD_INVALID, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context

app = typer.Typer(
    name="data",
    help="Create records in a published class.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

#: The label the record is reported under when it arrives on stdin.
STDIN_LABEL = "stdin"

#: What the input object holds, for the "must hold one …" message.
RECORD_SHAPE = "record object (the class's fields)"


@app.callback(invoke_without_command=True)
def data_group(ctx: typer.Context) -> None:
    """Data command group."""
    group_callback_without_subcommand(ctx)


def _usage_error(message: str) -> NoReturn:
    """Print ``message`` on stderr and exit 2."""
    typer.echo(message, err=True)
    raise typer.Exit(EXIT_USAGE)


def _read_document(from_file: Optional[Path], stdin: bool, fields: list[str]) -> Optional[dict[str, Any]]:
    """The input object from ``--from-file`` or ``--stdin``; ``None`` when only ``--field`` was given.

    Exits 2 when no input was given, both sources were, or ``--stdin`` is a terminal (nothing piped).
    """
    if from_file is not None and stdin:
        _usage_error("Give the record with --from-file or --stdin, not both.")
    if from_file is not None:
        return read_object_file(from_file, shape=RECORD_SHAPE)
    if stdin:
        if terminal.stdin_is_tty():
            _usage_error("--stdin reads the record from a pipe, e.g. `cat charge.json | apiome data create … --stdin`.")
        return read_object_text(sys.stdin.read(), label=STDIN_LABEL, shape=RECORD_SHAPE)
    if not fields:
        _usage_error("Give the record with --from-file <path>, --stdin or --field key=value.")
    return None


def _resolve_class(client: Any, tenant_slug: str, address: ClassAddress) -> Mapping[str, Any]:
    """The class schema row ``address`` names, or exit 2 (unknown version / unpublished / no such class)."""
    query = urlencode({"project": address.project, "version": address.version})
    answer = client.get(f"{api_paths.data_classes(tenant_slug)}?{query}").json()
    classes = answer.get("classes") if isinstance(answer, dict) else None
    if not classes:
        where = f"{address.project}/{address.version}"
        if isinstance(answer, dict) and not answer.get("published"):
            _usage_error(f"Version {where} is not published, so it has no class schemas. Publish it first.")
        _usage_error(f"Version {where} has no classes.")
    try:
        return find_class(classes, address.class_name)
    except DataInputError as exc:
        _usage_error(str(exc))


def _result(address: ClassAddress, row: Mapping[str, Any], payload: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    """The ``--json`` object: where the record went, its class schema and its data."""
    return {
        **extra,
        "project": address.project,
        "version": address.version,
        "class": str(row.get("class_name") or address.class_name),
        "class_schema_id": str(row.get("class_schema_id")),
        "data": dict(payload),
    }


@app.command("create")
def create_record(
    ctx: typer.Context,
    class_ref: str = typer.Option(
        ..., "--class", metavar="PROJECT/VERSION/CLASS", help="The class, e.g. billing/1.0.0/Charge (published version)."
    ),
    from_file: Optional[Path] = typer.Option(None, "--from-file", help="JSON or YAML file holding the record."),
    stdin: bool = typer.Option(False, "--stdin", help="Read the record (JSON or YAML) from stdin."),
    field: Optional[list[str]] = typer.Option(
        None, "--field", help="Set one field: key=value, or key=:<json> to parse the value (repeatable)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate against the class schema only; send nothing."),
    json_output: bool = typer.Option(
        False, "--json", help="Print the created record as JSON (same as the global --json)."
    ),
) -> None:
    """Create one record in a published class (POST /v1/data/{tenant}/records).

    The record comes from --from-file, --stdin or --field; --field values are applied on top of the file or stdin object. It is checked against the class's JSON Schema before it is sent.

    A record that does not match the schema exits 7 with one line per field; nothing is created.

    --json prints the created record: record_id, class, class_schema_id and data.
    """
    fields = field or []
    try:
        address = parse_class_address(class_ref)
        payload = build_payload(_read_document(from_file, stdin, fields), fields)
    except DataInputError as exc:
        _usage_error(str(exc))

    client, tenant_slug = tenant_scoped_client(ctx)
    row = _resolve_class(client, tenant_slug, address)
    schema = row.get("schema")
    try:
        errors = validate_record(schema if isinstance(schema, Mapping) else {}, payload)
    except SchemaUnusable as exc:
        errors = []
        typer.echo(f"Warning: {address} was not validated locally: {exc}.", err=True)
    if errors:
        exit_field_errors(errors, code=EXIT_RECORD_INVALID)

    json_mode = json_output or json_mode_from_context(ctx)
    if dry_run:
        if json_mode:
            emit_json(_result(address, row, payload, valid=True, dry_run=True))
        else:
            typer.echo(render_valid(address))
        return

    body = {"class_schema_id": str(row.get("class_schema_id")), "data": payload}
    created = client.post(api_paths.data_records(tenant_slug), json=body).json()
    record_id = str(created.get("record_id")) if isinstance(created, dict) else ""
    if json_mode:
        emit_json(_result(address, row, payload, record_id=record_id))
        return
    typer.echo(render_created(record_id, address))
