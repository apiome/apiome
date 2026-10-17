"""Input helpers shared by the commands that create things (``properties``, ``classes``).

* :func:`read_object_file` — ``--from-file``: one JSON or YAML object, or exit 2;
* :func:`exit_field_errors` — print ``field: message`` lines and exit 7;
* :func:`prompt_primitive` — ask for a primitive, listing matches for part of a name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import typer

from apiome_cli.exit_codes import EXIT_PROPERTY_INVALID, EXIT_USAGE
from apiome_cli.import_.yaml_load import safe_load
from apiome_cli.property_create import FieldError, PropertyInvalid, find_primitive, search_primitives


def read_object_file(path: Path, *, shape: str) -> dict[str, Any]:
    """Read ``--from-file`` (one JSON or YAML object), or exit 2 saying why it cannot be used.

    Args:
        path: The file.
        shape: What the object holds, for the message (e.g. ``"property object (name, …)"``).
    """
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
        typer.echo(f"{path} must hold one {shape}.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return document


def exit_field_errors(errors: Sequence[FieldError], *, code: int = EXIT_PROPERTY_INVALID) -> None:
    """Print one ``field: message`` line per problem, then "Nothing was created.", and exit ``code``."""
    for error in errors:
        typer.echo(str(error), err=True)
    typer.echo("Nothing was created.", err=True)
    raise typer.Exit(code)


def prompt_primitive(primitives: Sequence[Mapping[str, Any]], *, label: str = "? Primitive (type to search)") -> Mapping[str, Any]:
    """Ask for the primitive; part of a name lists the matches to choose from, until one fits."""
    while True:
        text = typer.prompt(label, err=True).strip()
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
