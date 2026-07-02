"""Inspect and update persisted CLI defaults in the user config file."""

from __future__ import annotations

from typing import Annotated

import typer
from pydantic import ValidationError

from apiome_cli.config import (
    ConfigFileError,
    FIELD_TO_CLI_KEY,
    mask_api_key,
    read_user_config_file,
    resolve_config_cli_key,
    validate_config_set,
    write_user_config_file,
)
from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand

app = typer.Typer(
    name="config",
    help="Show or change saved defaults in the user config file.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def config_group(ctx: typer.Context) -> None:
    """Config command group."""
    group_callback_without_subcommand(ctx)


def _format_show_value(field_name: str, value: object) -> str:
    """Format one config file value for human-readable ``config show`` output."""
    text = str(value).strip()
    if field_name in ("api_key", "session_token"):
        return mask_api_key(text)
    return text


def _echo_usage(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(EXIT_USAGE)


@app.command("show")
def show_config() -> None:
    """Print values stored in the user config file (api-key is masked)."""
    try:
        stored = read_user_config_file()
    except ConfigFileError as exc:
        _echo_usage(str(exc))

    for field_name in ("base_url", "tenant_id", "api_key", "session_token"):
        if field_name not in stored:
            continue
        cli_key = FIELD_TO_CLI_KEY[field_name]
        typer.echo(f"{cli_key} = {_format_show_value(field_name, stored[field_name])}")


@app.command("set")
def set_config(
    key: Annotated[
        str,
        typer.Argument(help="Setting name: base-url, tenant, api-key, or session-token."),
    ],
    value: Annotated[
        str,
        typer.Argument(help="Value to persist in the user config file."),
    ],
) -> None:
    """Persist a default to the user config file."""
    try:
        field_name = resolve_config_cli_key(key)
    except ValueError as exc:
        _echo_usage(str(exc))

    try:
        normalized = validate_config_set(field_name, value)
    except (ValidationError, ValueError) as exc:
        _echo_usage(str(exc))

    try:
        stored = read_user_config_file()
    except ConfigFileError as exc:
        _echo_usage(str(exc))

    stored[field_name] = normalized
    try:
        write_user_config_file(stored)
    except (ConfigFileError, OSError) as exc:
        _echo_usage(str(exc))


@app.command("unset")
def unset_config(
    key: Annotated[
        str,
        typer.Argument(help="Setting name: base-url, tenant, api-key, or session-token."),
    ],
) -> None:
    """Remove a default from the user config file."""
    try:
        field_name = resolve_config_cli_key(key)
    except ValueError as exc:
        _echo_usage(str(exc))

    try:
        stored = read_user_config_file()
    except ConfigFileError as exc:
        _echo_usage(str(exc))

    stored.pop(field_name, None)
    try:
        write_user_config_file(stored)
    except (ConfigFileError, OSError) as exc:
        _echo_usage(str(exc))
