"""Schema registry from the command line — CDG-4.5 (#5977).

``apiome registry subjects|versions|register|compat|config`` work with the tenant's schema subjects
(CDG-4.2) through the same routes the catalog item's **Subjects** tab and the **Registry settings**
page use:

* ``subjects`` lists live subjects; ``versions <subject>`` lists one subject's versions, or prints
  one with its schema text (``--version 3`` / ``--version latest``);
* ``register <subject> <file>`` registers a schema (idempotent on its fingerprint);
* ``compat <subject> <file>`` tests a schema on the Confluent-compatible API (CDG-4.3) and exits 1
  when it is not compatible — until XPC-4.x ships rules, any level but ``NONE`` is refused with
  error code ``42290``, which exits 2 like every other refusal;
* ``config`` reads or changes the tenant defaults, ``config <subject>`` one subject's settings.

A refusal prints the registry's message on stderr and exits with the HTTP-derived code (4xx → 2,
5xx → 1). ``--format json`` (or the global ``--json``) prints the API response.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import typer

from apiome_cli.client import api_paths
from apiome_cli.client.errors import http_exit_code
from apiome_cli.client.schema_registry import (
    CODE_COMPATIBILITY_RULES_UNAVAILABLE,
    COMPATIBILITY_LEVELS,
    ERROR_COMPATIBILITY_RULES_UNAVAILABLE,
    MODES,
    SCHEMA_TYPES,
    STRATEGIES,
    normalize_choice,
    refusal_message,
    schema_type_for,
    subject_rows,
    version_rows,
)
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import RecordField, emit_json, emit_list_table, emit_record_table, json_mode_from_context

app = typer.Typer(
    name="registry",
    help="Schema registry: subjects, versions, registration, compatibility and settings.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

_FORMATS = ("table", "json")

_SUBJECT_COLUMNS = (
    ("Subject", "name", None),
    ("Versions", "versions", None),
    ("Latest", "latest", None),
    ("Compatibility", "level", None),
    ("Mode", "mode", None),
    ("Strategy", "strategy", None),
)

_VERSION_COLUMNS = (
    ("Version", "version", None),
    ("Schema ID", "id", None),
    ("Type", "type", None),
    ("Revision", "revision", None),
    ("Created", "created", None),
)

_VERSION_FIELDS: tuple[RecordField, ...] = (
    ("Subject", "subject", None),
    ("Version", "version", None),
    ("Schema ID", "id", None),
    ("Type", "schemaType", None),
    ("Fingerprint", "fingerprint", None),
    ("Catalog item", "projectId", None),
    ("Revision", "versionRecordId", None),
    ("Created", "createdAt", None),
)

_SUBJECT_FIELDS: tuple[RecordField, ...] = (
    ("Subject", "name", None),
    ("Strategy", "strategy", lambda value: value or ""),
    ("Compatibility", "compatibilityLevel", lambda value: value or "(tenant default)"),
    ("Effective compatibility", "effectiveCompatibilityLevel", None),
    ("Mode", "mode", None),
    ("Versions", "versionCount", None),
    ("Catalog item", "projectId", lambda value: value or ""),
)

_CONFIG_FIELDS: tuple[RecordField, ...] = (
    ("Default compatibility", "compatibilityLevel", None),
    ("Mode", "mode", None),
)


@app.callback(invoke_without_command=True)
def registry_group(ctx: typer.Context) -> None:
    """Schema registry command group."""
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
    return typer.Option("table", "--format", help="Output: table (default) or json (the API response).")


def _expect(response: httpx.Response, *, hint: str | None = None) -> httpx.Response:
    """Return a successful response, or print the registry's reason and exit (4xx → 2, 5xx → 1).

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
    message, _code = refusal_message(response)
    typer.echo(f"Error: {message}", err=True)
    if hint:
        typer.echo(hint, err=True)
    raise typer.Exit(http_exit_code(response.status_code))


def _option(value: str | None, allowed: tuple[str, ...], hint: str, *, upper: bool = True) -> str | None:
    """Validate an optional enumerated option.

    Args:
        value: The option as typed.
        allowed: The accepted values.
        hint: The option name, for the error.
        upper: Upper-case the value (levels, modes, types); strategies are lower-case.

    Returns:
        The canonical value, or ``None`` when the option was not given.

    Raises:
        typer.BadParameter: The value is not one of ``allowed`` (exit 2).
    """
    canonical, valid = normalize_choice(value, allowed, upper=upper)
    if not valid:
        raise typer.BadParameter(f"must be one of {', '.join(allowed)}", param_hint=hint)
    return canonical


def _compatibility_hint(response: httpx.Response) -> str | None:
    """Return the next step for a refusal that needs compatibility rules Apiome lacks, else ``None``.

    Args:
        response: A registry response (Apiome routes say ``compatibility-rules-unavailable``,
            the Confluent routes ``42290``).

    Returns:
        A hint line, or ``None`` for a success or any other refusal.
    """
    if response.is_success:
        return None
    _message, code = refusal_message(response)
    if code in (CODE_COMPATIBILITY_RULES_UNAVAILABLE, ERROR_COMPATIBILITY_RULES_UNAVAILABLE):
        return "Hint: apiome registry config <subject> --level NONE registers without a check."
    return None


def _read_schema(path: Path, schema_type: str | None) -> tuple[str, str]:
    """Read a schema file and decide its type.

    Args:
        path: The schema file.
        schema_type: ``--type`` as typed, or ``None`` to go by the extension.

    Returns:
        ``(schema text, schema type)``.

    Raises:
        typer.BadParameter: The file cannot be read, or its type is unknown (exit 2).
    """
    resolved = schema_type_for(path, schema_type)
    if resolved is None:
        raise typer.BadParameter(
            "cannot tell the schema type from the file name; pass --type AVRO, JSON or PROTOBUF",
            param_hint="--type",
        )
    _option(resolved, SCHEMA_TYPES, "--type")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise typer.BadParameter(f"cannot read {path}: {exc.strerror or exc}", param_hint="FILE") from exc
    return text, resolved


def _type_option() -> Any:
    """The shared ``--type`` option."""
    return typer.Option(
        None,
        "--type",
        help="Schema type: AVRO, JSON or PROTOBUF (default: from the extension — .avsc, .json, .proto).",
    )


@app.command("subjects")
def list_subjects(ctx: typer.Context, output_format: str = _format_option()) -> None:
    """List the workspace's live schema subjects (GET …/schema-registry/subjects)."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    body = _expect(client.get_raw(f"{api_paths.schema_registry(tenant)}/subjects")).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_list_table(
        subject_rows(body),
        _SUBJECT_COLUMNS,
        empty_message="No subjects. Register one with: apiome registry register <subject> <file>",
        min_width=120,
    )


@app.command("versions")
def list_versions(
    ctx: typer.Context,
    subject: str = typer.Argument(..., help="Subject name, e.g. orders-value."),
    version: str | None = typer.Option(
        None, "--version", help="Print one version with its schema text: a number or latest."
    ),
    output_format: str = _format_option(),
) -> None:
    """List a subject's versions, oldest first, or print one with --version (GET …/versions)."""
    fmt = _format(ctx, output_format)
    client, tenant = tenant_scoped_client(ctx)
    path = f"{api_paths.schema_subject(tenant, subject)}/versions"
    if version is None:
        body = _expect(client.get_raw(path)).json()
        if fmt == "json":
            emit_json(body)
            return
        emit_list_table(version_rows(body), _VERSION_COLUMNS, empty_message="No versions.", min_width=120)
        return
    body = _expect(client.get_raw(f"{path}/{version.strip()}")).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_record_table(body, _VERSION_FIELDS)
    typer.echo(body.get("schema") or "")


@app.command("register")
def register(
    ctx: typer.Context,
    subject: str = typer.Argument(..., help="Subject name, e.g. orders-value."),
    file: Path = typer.Argument(..., help="Schema file (.avsc, .json or .proto)."),
    schema_type: str | None = _type_option(),
    strategy: str | None = typer.Option(
        None, "--strategy", help="Naming strategy for a new subject: topic, record or topic_record."
    ),
    output_format: str = _format_option(),
) -> None:
    """Register a schema under a subject (POST …/subjects/{subject}/versions).

    Registering a schema the subject already holds returns its version and id unchanged.
    """
    fmt = _format(ctx, output_format)
    text, resolved = _read_schema(file, schema_type)
    payload: dict[str, Any] = {"schema": text, "schemaType": resolved}
    chosen = _option(strategy, STRATEGIES, "--strategy", upper=False)
    if chosen:
        payload["strategy"] = chosen
    client, tenant = tenant_scoped_client(ctx)
    response = client.post_raw(f"{api_paths.schema_subject(tenant, subject)}/versions", json=payload)
    body = _expect(response, hint=_compatibility_hint(response)).json()
    if fmt == "json":
        emit_json(body)
        return
    state = "Registered" if body.get("created") else "Already registered"
    typer.echo(f"{state}: {subject} version {body.get('version')} (schema id {body.get('id')}).")


@app.command("compat")
def compat(
    ctx: typer.Context,
    subject: str = typer.Argument(..., help="Subject name, e.g. orders-value."),
    file: Path = typer.Argument(..., help="Candidate schema file (.avsc, .json or .proto)."),
    schema_type: str | None = _type_option(),
    version: str | None = typer.Option(
        None, "--version", help="Test against one version (a number or latest); default: the level's versions."
    ),
    output_format: str = _format_option(),
) -> None:
    """Test a schema against a subject without registering it (Confluent POST /compatibility/…).

    Exits 0 when compatible and 1 when not. Until compatibility rules ship, a subject whose level is
    not NONE is refused with error code 42290 (exit 2).
    """
    fmt = _format(ctx, output_format)
    text, resolved = _read_schema(file, schema_type)
    client, tenant = tenant_scoped_client(ctx)
    response = client.post_raw(
        api_paths.confluent_compatibility(tenant, subject, version.strip() if version else None),
        json={"schema": text, "schemaType": resolved},
    )
    body = _expect(response, hint=_compatibility_hint(response)).json()
    compatible = bool(body.get("is_compatible"))
    if fmt == "json":
        emit_json(body)
    else:
        typer.echo(f"{subject}: {'compatible' if compatible else 'NOT compatible'}")
        for message in body.get("messages") or []:
            typer.echo(f"  {message}")
    if not compatible:
        raise typer.Exit(EXIT_ERROR)


@app.command("config")
def config(
    ctx: typer.Context,
    subject: str | None = typer.Argument(
        None, help="Subject name; omit to read or change the workspace defaults."
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        help="Compatibility level: NONE, BACKWARD, BACKWARD_TRANSITIVE, FORWARD, FORWARD_TRANSITIVE, "
        "FULL or FULL_TRANSITIVE.",
    ),
    mode: str | None = typer.Option(None, "--mode", help="READWRITE or READONLY."),
    strategy: str | None = typer.Option(
        None, "--strategy", help="A subject's naming strategy: topic, record or topic_record."
    ),
    output_format: str = _format_option(),
) -> None:
    """Read or change registry settings (GET / PUT …/config, or …/subjects/{subject}).

    With no option it prints the current settings; with --level, --mode or --strategy it changes
    them. Changing a subject that does not exist yet creates it.
    """
    fmt = _format(ctx, output_format)
    changes: dict[str, str] = {}
    chosen_level = _option(level, COMPATIBILITY_LEVELS, "--level")
    chosen_mode = _option(mode, MODES, "--mode")
    chosen_strategy = _option(strategy, STRATEGIES, "--strategy", upper=False)
    if chosen_level:
        changes["compatibilityLevel"] = chosen_level
    if chosen_mode:
        changes["mode"] = chosen_mode
    if chosen_strategy:
        if subject is None:
            raise typer.BadParameter("a strategy belongs to a subject; name one", param_hint="--strategy")
        changes["strategy"] = chosen_strategy
    client, tenant = tenant_scoped_client(ctx)
    if subject is None:
        path = f"{api_paths.schema_registry(tenant)}/config"
        fields = _CONFIG_FIELDS
    else:
        path = api_paths.schema_subject(tenant, subject)
        fields = _SUBJECT_FIELDS
    response = client.put_raw(path, json=changes) if changes else client.get_raw(path)
    body = _expect(response).json()
    if fmt == "json":
        emit_json(body)
        return
    emit_record_table(body, fields)
