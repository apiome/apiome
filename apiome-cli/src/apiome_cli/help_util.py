"""Shared help output for the root CLI and interactive runner."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click
import typer
from typer.main import get_command

from apiome_cli.exit_codes import EXIT_SUCCESS

if TYPE_CHECKING:
    from apiome_cli.main import app as AppType

CONCISE_HELP_EPILOG = """
Examples:
  apiome
  apiome --version
  apiome help
  apiome help projects list
  apiome doctor
  apiome health
  apiome --base-url http://localhost:8000 projects list

Run `apiome --help` for global options and Typer command details.
""".strip()


def _first_help_line(help_text: str | None) -> str:
    """Return the first line of a Click/Typer help string."""
    if not help_text:
        return ""
    return help_text.strip().splitlines()[0].strip()


def build_command_directory(app: AppType | None = None) -> str:
    """Build a nested catalog of all registered CLI commands and summaries."""
    if app is None:
        from apiome_cli.main import app as root_app

        app = root_app

    root = get_command(app)
    if not isinstance(root, click.Group):
        return "Commands:\n  (none)"

    lines: list[str] = ["Commands:"]

    def append_entry(name: str, cmd: click.Command, depth: int) -> None:
        indent = "  " * depth
        lines.append(f"{indent}{name:<16}  {_first_help_line(cmd.help)}")

    for name in sorted(root.commands):
        cmd = root.commands[name]
        if isinstance(cmd, click.Group) and cmd.commands:
            append_entry(name, cmd, depth=1)
            for sub_name in sorted(cmd.commands):
                append_entry(sub_name, cmd.commands[sub_name], depth=2)
        else:
            append_entry(name, cmd, depth=1)

    return "\n".join(lines)


def echo_concise_help() -> None:
    """Print usage, command directory, and examples for a bare ``apiome`` run."""
    typer.echo(
        "apiome — Command-line client for the Apiome REST API.\n\n"
        "Usage:\n"
        "  apiome [OPTIONS] COMMAND [ARGS]...\n\n"
        f"{build_command_directory()}\n\n"
        f"{CONCISE_HELP_EPILOG}"
    )


def group_callback_without_subcommand(ctx: typer.Context) -> None:
    """Print a command group's help and exit 0 when invoked without a subcommand."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(EXIT_SUCCESS)


def show_cli_help(command: list[str] | None) -> int:
    """Print concise or subcommand help.

    :param command: When ``None``, print concise usage. Otherwise show Typer help
        for the given subcommand path (e.g. ``["projects", "list"]``).
    :returns: Process exit code (``0`` on success).
    """
    if not command:
        echo_concise_help()
        return EXIT_SUCCESS

    from apiome_cli.main import app

    sys.argv = ["apiome", *command, "--help"]
    result = app(standalone_mode=False)
    return int(result) if isinstance(result, int) else EXIT_SUCCESS
