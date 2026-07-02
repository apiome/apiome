"""Run ``apiome`` commands from an interactive prompt or stdin batch.

Used by ``run.sh`` when invoked with no arguments. Each non-empty line is parsed
with :func:`shlex.split` and executed via :func:`apiome_cli.main.run`.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Iterator

import typer

from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.help_util import show_cli_help
from apiome_cli.main import run

_PROMPT = "apiome> "
_STOP_WORDS = frozenset({"exit", "quit"})


def _iter_command_lines(*, interactive: bool) -> Iterator[str]:
    """Yield command lines from a TTY prompt or piped stdin."""
    if interactive:
        typer.echo(
            "Interactive apiome CLI (type 'help', 'exit', or 'quit').",
            err=True,
        )
        while True:
            try:
                line = input(_PROMPT)
            except EOFError:
                typer.echo(err=True)
                break
            yield line
        return

    for line in sys.stdin:
        yield line.rstrip("\n")


def _run_command_line(line: str) -> bool:
    """Execute one command line.

    :param line: Raw input line (may include shell-style quoting).
    :returns: ``False`` when the REPL should stop; ``True`` to continue.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True
    if stripped in _STOP_WORDS:
        return False

    if stripped == "help":
        show_cli_help(None)
        return True
    if stripped.startswith("help "):
        show_cli_help(shlex.split(stripped.removeprefix("help ").strip()))
        return True

    argv = ["apiome", *shlex.split(stripped)]
    sys.argv = argv
    try:
        run()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_ERROR
        if code:
            typer.echo(f"exit {code}", err=True)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        typer.echo(f"exit {EXIT_ERROR}", err=True)
    return True


def main() -> None:
    """Entry point for interactive or batch CLI execution."""
    interactive = sys.stdin.isatty()
    for line in _iter_command_lines(interactive=interactive):
        if not _run_command_line(line):
            break


if __name__ == "__main__":
    main()
