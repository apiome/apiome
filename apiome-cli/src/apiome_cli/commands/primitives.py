"""``apiome primitives`` — bulk import of a tenant's primitives (CLI 5.6, #3222).

The rules live in :mod:`apiome_cli.primitive_import`; this module reads the file, talks to the
REST API (``POST /v1/primitives/{tenant}/import/review`` then ``…/import``), prints, and maps the
outcome to an exit code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

import typer

from apiome_cli import terminal
from apiome_cli.client import api_paths
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.exit_codes import EXIT_PRIMITIVE_IMPORT_FAILED, EXIT_USAGE
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.import_.yaml_load import safe_load
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.primitive_import import (
    PROGRESS_THRESHOLD,
    STATUS_INVALID,
    STATUS_NEW,
    STATUS_OVERWRITE,
    STATUS_SYSTEM,
    WRITE_STATUSES,
    ImportFileError,
    ImportRow,
    RowOutcome,
    abort_outcomes,
    build_report,
    bundle_payload,
    commit_outcomes,
    convert_rows,
    has_failures,
    parse_rows,
    provenance_warning,
    render_plan,
    render_summary,
    review_outcomes,
)
from apiome_cli.progress import import_progress, row_progress

app = typer.Typer(
    name="primitives",
    help="Import a tenant's primitives in bulk.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

#: The source label used when the rows arrive on stdin.
STDIN_LABEL = "stdin"


@app.callback(invoke_without_command=True)
def primitives_group(ctx: typer.Context) -> None:
    """Primitives command group."""
    group_callback_without_subcommand(ctx)


def _read_source(file: Optional[str]) -> tuple[str, str]:
    """Read the document to import, or exit 2 saying why it cannot be read.

    Args:
        file: A path, ``-`` for stdin, or ``None`` (stdin when something is piped in).

    Returns:
        ``(text, label)``: the document and the name it is reported under.
    """
    if file is None or file == "-":
        if terminal.stdin_is_tty():
            typer.echo("Give a file to import, or pipe primitives in on stdin.", err=True)
            raise typer.Exit(EXIT_USAGE)
        return sys.stdin.read(), STDIN_LABEL
    try:
        return Path(file).read_text(encoding="utf-8"), Path(file).name
    except (OSError, UnicodeDecodeError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
        typer.echo(f"Cannot read {file}: {reason}.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


def _load_rows(text: str, label: str) -> list[Any]:
    """Parse the document and return its rows, or exit 2 when it is not an import file."""
    try:
        return parse_rows(safe_load(text))
    except ImportFileError as exc:
        typer.echo(f"{label} {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    except ValueError as exc:
        typer.echo(f"{label} is not valid JSON or YAML: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


def _write_report(path: Optional[Path], report: dict[str, Any]) -> None:
    """Write the per-row report to ``--report``, or exit 2 when the file cannot be written."""
    if path is None:
        return
    try:
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Cannot write the report to {path}: {exc.strerror or exc}.", err=True)
        raise typer.Exit(EXIT_USAGE) from exc


def _echo_failures(outcomes: Sequence[RowOutcome]) -> None:
    """Print one ``row N (name): message`` line per invalid row on stderr."""
    for outcome in outcomes:
        if outcome.status == STATUS_INVALID:
            typer.echo(f"{outcome.label}: {outcome.message}", err=True)


def _post(client: Any, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST ``payload`` and return the JSON object answered (the client exits on an HTTP error)."""
    body = client.post(path, json=payload).json()
    if not isinstance(body, dict):
        raise typer.BadParameter(f"Unexpected response from POST {path}.")
    return body


@app.command("import")
def import_primitives(
    ctx: typer.Context,
    file: Optional[str] = typer.Argument(
        None, metavar="[FILE]", help="JSON or YAML file of primitives; omit or pass - to read stdin."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be imported, and the conflicts, without writing."),
    update: bool = typer.Option(False, "--update", help="Overwrite an existing primitive with the same name."),
    skip_conflicts: bool = typer.Option(
        False, "--skip-conflicts", help="Leave an existing primitive with the same name alone (the default)."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Import without asking. Required when there is no terminal."),
    continue_on_error: bool = typer.Option(
        False, "--continue-on-error", help="Import the rows that are fine when others fail, and exit 0."
    ),
    report_path: Optional[Path] = typer.Option(
        None, "--report", metavar="PATH", help="Write a JSON report with one entry per row."
    ),
) -> None:
    """Import primitives from a file (POST /v1/primitives/{tenant}/import).

    The file holds one primitive or an array of them: name, base (a JSON Schema type) and any
    schema keyword such as pattern or examples — or name and schema, as `types list --json` prints.

    Every row is checked here first, then reviewed by the server; nothing is written before you
    confirm, or without --yes when there is no terminal.

    A row that fails stops the import with exit 7, unless --continue-on-error.
    """
    if update and skip_conflicts:
        typer.echo("--update and --skip-conflicts cannot be used together.", err=True)
        raise typer.Exit(EXIT_USAGE)

    text, label = _read_source(file)
    raw_rows = _load_rows(text, label)
    with row_progress(
        len(raw_rows), description="Checking primitives", enabled=len(raw_rows) > PROGRESS_THRESHOLD
    ) as advance:
        rows, local = convert_rows(raw_rows, on_row=advance)

    json_mode = json_mode_from_context(ctx)
    tenant: Optional[str] = None

    def finish(
        outcomes: Sequence[RowOutcome], *, committed: bool = False, import_id: Optional[str] = None
    ) -> None:
        """Write ``--report``, print the report under ``--json``, and exit 7 on a row failure."""
        report = build_report(outcomes, source=label, tenant=tenant, committed=committed, import_id=import_id)
        _write_report(report_path, report)
        if json_mode:
            emit_json(report)
        if has_failures(outcomes) and not continue_on_error:
            raise typer.Exit(EXIT_PRIMITIVE_IMPORT_FAILED)

    def refuse(outcomes: Sequence[RowOutcome], good: Sequence[ImportRow]) -> None:
        """Stop before writing because a row failed: list the rows, then :func:`finish`."""
        _echo_failures(outcomes)
        typer.echo("Nothing was imported. Fix the rows above, or pass --continue-on-error.", err=True)
        kept = [outcome for outcome in outcomes if outcome.status not in WRITE_STATUSES]
        settled = {outcome.index for outcome in kept}
        finish([*kept, *abort_outcomes([row for row in good if row.index not in settled])])
        raise typer.Exit(EXIT_PRIMITIVE_IMPORT_FAILED)

    if has_failures(local) and not continue_on_error:
        refuse(local, rows)
    if not rows:
        _echo_failures(local)
        typer.echo("No primitives to import.", err=True)
        finish(local)
        return

    client, tenant = tenant_scoped_client(ctx)
    review = _post(client, api_paths.primitives_import_review(tenant), bundle_payload(rows, source_label=label))
    for warning in review.get("warnings") or []:
        terminal.echo_notice(f"Warning: {warning}")
    planned = [*local, *review_outcomes(rows, review, update=update)]

    typer.echo(render_plan(planned, rows), err=json_mode)
    if has_failures(planned) and not continue_on_error:
        refuse(planned, rows)

    writes = [outcome for outcome in planned if outcome.status in WRITE_STATUSES]
    if dry_run or not writes:
        if not writes and not dry_run:
            terminal.echo_notice("Nothing to import.")
        finish(planned)
        return
    if not yes:
        if not terminal.interactive_enabled():
            terminal.echo_notice("Nothing was written. Pass --yes to import.")
            finish(planned)
            return
        # Written before asking, so the plan is on disk even when the answer is no.
        _write_report(report_path, build_report(planned, source=label, tenant=tenant, committed=False))
        created = sum(outcome.status == STATUS_NEW for outcome in writes)
        terminal.confirm_action(
            f"Import {created} new and overwrite {len(writes) - created} existing primitive(s) in {tenant}?"
        )

    rejected = {outcome.index for outcome in planned if outcome.status == STATUS_INVALID}
    sendable = [row for row in rows if row.index not in rejected]
    overwrite = [str(outcome.name) for outcome in writes if outcome.status == STATUS_OVERWRITE]
    with import_progress(initial_message=f"Importing {len(sendable)} primitives…"):
        result = _post(
            client,
            api_paths.primitives_import(tenant),
            bundle_payload(sendable, source_label=label, overwrite=overwrite),
        )
    warning = provenance_warning(result)
    if warning:
        terminal.echo_notice(f"Warning: the import was not recorded in the import history ({warning}).")
    done = [
        *(outcome for outcome in planned if outcome.status in (STATUS_INVALID, STATUS_SYSTEM)),
        *commit_outcomes(sendable, result),
    ]
    typer.echo(render_summary(done), err=json_mode)
    import_id = result.get("import_id")
    finish(done, committed=True, import_id=import_id if isinstance(import_id, str) else None)
