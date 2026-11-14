"""``apiome data`` — records stored against a published class (CLI 10.x, epic #3183).

``data create`` (CLI 10.3, #3255): the rules live in :mod:`apiome_cli.data_record`; this module
reads the input, resolves ``--class <project>/<version>/<Class>`` with
``GET /v1/data/{tenant}/classes``, validates the payload against the class's frozen JSON Schema,
then ``POST /v1/data/{tenant}/records``.

``data list`` (CLI 10.1, #3253): pages through ``GET /v1/data/{tenant}/records`` with the server's
cursor; the table rendering lives in :mod:`apiome_cli.data_view`.

``data import`` (CLI 10.7, #3259): streams NDJSON / a JSON array / CSV through the readers in
:mod:`apiome_cli.data_import`, checks each row locally, and sends batches of rows on a small thread
pool (one POST per row — the server has no bulk create), writing ``--report`` as it goes.
"""

from __future__ import annotations

import json
import sys
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import IO, Any, Callable, Iterator, Mapping, NoReturn, Optional
from urllib.parse import urlencode

import typer

from apiome_cli import terminal
from apiome_cli.cli_input import exit_field_errors, read_object_file, read_object_text
from apiome_cli.client import api_paths
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT
from apiome_cli.client.version_scope import tenant_scoped_client
from apiome_cli.data_import import (
    FORMAT_CSV,
    FORMAT_JSON,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_INVALID,
    STATUS_VALID,
    STDIN_PATH,
    ImportCounts,
    ReportWriter,
    Row,
    RowResult,
    batches,
    detect_format,
    iter_csv,
    iter_json_array,
    iter_ndjson,
    parse_mapping,
    post_with_retry,
)
from apiome_cli.data_record import (
    ClassAddress,
    DataInputError,
    SchemaUnusable,
    build_payload,
    check_filter,
    find_class,
    is_class_schema_id,
    parse_class_address,
    record_validator,
    render_created,
    render_valid,
    validate_record,
)
from apiome_cli.exit_codes import EXIT_IMPORT_FAILED, EXIT_RECORD_INVALID, EXIT_USAGE
from apiome_cli.data_view import data_columns, parse_columns, render_footer, render_table
from apiome_cli.help_util import group_callback_without_subcommand
from apiome_cli.output import emit_json, json_mode_from_context
from apiome_cli.progress import progress_allowed, record_progress

app = typer.Typer(
    name="data",
    help="Create, list and import records in a published class.",
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)

#: The label the record is reported under when it arrives on stdin.
STDIN_LABEL = "stdin"

#: What the input object holds, for the "must hold one …" message.
RECORD_SHAPE = "record object (the class's fields)"

#: The page size ``data list --all`` asks for (the server's maximum).
MAX_LIST_PAGE = 500


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


def _fetch_page(
    client: Any,
    tenant_slug: str,
    class_schema_id: str,
    *,
    filters: list[str],
    sort: str,
    include_deleted: bool,
    limit: int,
    cursor: Optional[str],
) -> dict[str, Any]:
    """One page of ``GET /v1/data/{tenant}/records`` (the client exits on an HTTP error)."""
    query: list[tuple[str, str]] = [("class_schema_id", class_schema_id), ("limit", str(limit)), ("sort", sort)]
    query += [("filter", text) for text in filters]
    if include_deleted:
        query.append(("include_deleted", "true"))
    if cursor:
        query.append(("cursor", cursor))
    answer = client.get(f"{api_paths.data_records(tenant_slug)}?{urlencode(query)}").json()
    return answer if isinstance(answer, dict) else {}


def _pages(fetch: Any, cursor: Optional[str], follow: bool) -> Any:
    """Yield pages from ``cursor`` on: just one, or every page when ``follow`` (``--all``)."""
    while True:
        page = fetch(cursor)
        yield page
        cursor = page.get("next_cursor")
        if not follow or not cursor:
            return


@app.command("list")
def list_records(
    ctx: typer.Context,
    class_ref: str = typer.Option(
        ...,
        "--class",
        metavar="PROJECT/VERSION/CLASS",
        help="The class (e.g. billing/1.0.0/Charge), or its class schema id.",
    ),
    filter_: Optional[list[str]] = typer.Option(
        None, "--filter", help="Only records whose data field equals the value: key=value (repeatable)."
    ),
    sort: str = typer.Option(
        "created_at", "--sort", help="created_at, updated_at, deleted_at, record_id or a data field; -field descends."
    ),
    limit: int = typer.Option(
        DEFAULT_PAGE_LIMIT, "--limit", min=1, max=MAX_LIST_PAGE, help="Records per page."
    ),
    next_cursor: Optional[str] = typer.Option(
        None, "--next", metavar="CURSOR", help="Show the page after the one that printed this cursor."
    ),
    all_rows: bool = typer.Option(False, "--all", help="Show every remaining record (ignores --limit)."),
    columns: Optional[str] = typer.Option(
        None, "--columns", help="Data fields to show, comma-separated (table only; default: every field)."
    ),
    include_deleted: bool = typer.Option(
        False, "--include-deleted", help="Include soft-deleted records, with a DELETED_AT column."
    ),
    json_output: bool = typer.Option(False, "--json", help="Print the records as one JSON array."),
    ndjson: bool = typer.Option(False, "--ndjson", help="Print one JSON record per line (for ETL tools)."),
) -> None:
    """List a class's records, a page at a time (GET /v1/data/{tenant}/records).

    The table shows ID, CREATED and the data fields; the footer says how many records match and the --next cursor for the following page. --all follows every page.

    --json prints a JSON array and --ndjson one record per line; the next cursor, if any, goes to stderr. Both stream, so --all works on any number of records.
    """
    json_mode = json_output or json_mode_from_context(ctx)
    if json_mode and ndjson:
        _usage_error("Use --json or --ndjson, not both.")
    filters = filter_ or []
    try:
        for text in filters:
            check_filter(text)
        address = None if is_class_schema_id(class_ref) else parse_class_address(class_ref)
    except DataInputError as exc:
        _usage_error(str(exc))

    client, tenant_slug = tenant_scoped_client(ctx)
    class_schema_id = (
        str(_resolve_class(client, tenant_slug, address).get("class_schema_id")) if address else class_ref.strip()
    )

    def fetch(cursor: Optional[str]) -> dict[str, Any]:
        return _fetch_page(
            client,
            tenant_slug,
            class_schema_id,
            filters=filters,
            sort=sort,
            include_deleted=include_deleted,
            limit=MAX_LIST_PAGE if all_rows else limit,
            cursor=cursor,
        )

    pages = _pages(fetch, next_cursor, all_rows)
    if json_mode or ndjson:
        _stream_records(pages, ndjson=ndjson)
        return

    items: list[dict[str, Any]] = []
    page: dict[str, Any] = {}
    for page in pages:
        items += [item for item in page.get("items") or [] if isinstance(item, dict)]
    total = int(page.get("total") or 0)
    if not items:
        typer.echo(f"No records in {address or class_schema_id}.")
        return
    shown = data_columns(items, parse_columns(columns))
    typer.echo("\n".join(render_table(items, shown, include_deleted=include_deleted)))
    typer.echo("")
    typer.echo(render_footer(len(items), total, page.get("next_cursor")))


def _stream_records(pages: Any, *, ndjson: bool) -> None:
    """Write the records as they arrive: one JSON line each (``ndjson``), or one JSON array.

    The next cursor of the last page fetched (when more records remain) goes to stderr, so
    stdout stays valid JSON / NDJSON.
    """
    first = True
    cursor = None
    if not ndjson:
        typer.echo("[", nl=False)
    for page in pages:
        for item in page.get("items") or []:
            line = json.dumps(item, separators=(",", ":"), ensure_ascii=False)
            if ndjson:
                typer.echo(line)
            else:
                typer.echo(line if first else f",{line}", nl=False)
            first = False
        cursor = page.get("next_cursor")
    if not ndjson:
        typer.echo("]")
    if cursor:
        terminal.echo_notice(f"More records: --next {cursor}")


#: How many failed rows ``data import`` prints before pointing at ``--report``.
MAX_FAILURES_SHOWN = 20

#: The largest ``--batch`` and ``--concurrency`` accepted.
MAX_IMPORT_BATCH = 5000
MAX_IMPORT_CONCURRENCY = 16


def _open_source(source: str) -> IO[str]:
    """The input stream: stdin for ``-`` (exit 2 when nothing is piped), else the file (exit 2 if unreadable)."""
    if source == STDIN_PATH:
        if terminal.stdin_is_tty():
            _usage_error("FILE - reads the records from a pipe, e.g. `apiome data import - --class … --ndjson < charges.ndjson`.")
        return sys.stdin
    try:
        return open(source, encoding="utf-8", newline="")
    except OSError as exc:
        _usage_error(f"Cannot read {source}: {exc.strerror or exc}.")


def _row_reader(fmt: str, mapping: list[tuple[str, str]], properties: Mapping[str, Any]) -> Callable[[IO[str]], Iterator[Row]]:
    """The streaming reader for ``fmt``."""
    if fmt == FORMAT_CSV:
        return lambda stream: iter_csv(stream, mapping, properties)
    if fmt == FORMAT_JSON:
        return iter_json_array
    return iter_ndjson


def _count_rows(source: str, read: Callable[[IO[str]], Iterator[Row]]) -> Optional[int]:
    """How many rows the file holds (a first, constant-memory pass for the progress bar).

    ``None`` for stdin (it can only be read once) or when the file cannot be read through — the
    real pass then reports the problem.
    """
    if source == STDIN_PATH:
        return None
    try:
        with open(source, encoding="utf-8", newline="") as stream:
            return sum(1 for _ in read(stream))
    except (OSError, DataInputError, UnicodeDecodeError):
        return None


def _check_rows(
    batch: list[Row],
    validate: Optional[Callable[[Mapping[str, Any]], list[Any]]],
    *,
    dry_run: bool,
    stop_on_error: bool,
) -> tuple[list[tuple[Row, Optional[RowResult]]], bool]:
    """Check a batch locally: each row paired with its result, or ``None`` when it is to be sent.

    Returns:
        ``(rows, stopped)`` — with ``stop_on_error`` the batch is cut after its first bad row and
        ``stopped`` is True; the rows after it are not reported.
    """
    checked: list[tuple[Row, Optional[RowResult]]] = []
    for row in batch:
        problem = row.error
        if problem is None and validate is not None:
            errors = validate(row.data or {})
            problem = "; ".join(str(error) for error in errors) if errors else None
        if problem is not None:
            checked.append((row, RowResult(row.number, STATUS_INVALID, error=problem)))
            if stop_on_error:
                return checked, True
        elif dry_run:
            checked.append((row, RowResult(row.number, STATUS_VALID)))
        else:
            checked.append((row, None))
    return checked, False


def _send_rows(client: Any, path: str, class_schema_id: str, checked: list[tuple[Row, Optional[RowResult]]]) -> list[RowResult]:
    """POST each row that passed the local check (one worker runs one batch), in input order."""
    results: list[RowResult] = []
    for row, result in checked:
        if result is None:
            body = {"class_schema_id": class_schema_id, "data": row.data}
            record_id, error = post_with_retry(lambda: client.post_raw(path, json=body))
            status = STATUS_CREATED if record_id else STATUS_FAILED
            result = RowResult(row.number, status, record_id=record_id, error=error)
        results.append(result)
    return results


def _import_summary(
    address: ClassAddress,
    class_schema_id: str,
    counts: ImportCounts,
    *,
    source: str,
    fmt: str,
    dry_run: bool,
    stopped: bool,
    report_path: Optional[Path],
) -> dict[str, Any]:
    """The ``--json`` object and the keys after ``rows`` in the ``--report`` file."""
    return {
        "project": address.project,
        "version": address.version,
        "class": address.class_name,
        "class_schema_id": class_schema_id,
        "source": STDIN_LABEL if source == STDIN_PATH else source,
        "format": fmt,
        "dry_run": dry_run,
        "total": counts.total,
        "created_count": 0 if dry_run else counts.succeeded,
        "valid_count": counts.succeeded if dry_run else None,
        "failed_count": counts.failed,
        "stopped_at_first_failure": stopped,
        "report": str(report_path) if report_path else None,
    }


def _echo_import_outcome(address: ClassAddress, counts: ImportCounts, *, dry_run: bool, stopped: bool, has_report: bool) -> None:
    """The summary line on stdout; the failed rows (the first :data:`MAX_FAILURES_SHOWN`) on stderr."""
    for result in counts.failures:
        typer.echo(f"Row {result.row} ({result.status}): {result.error}", err=True)
    hidden = counts.failed - len(counts.failures)
    if hidden > 0:
        where = "see --report" if has_report else "add --report <path> to list every row"
        typer.echo(f"… and {hidden:,} more failed rows; {where}.", err=True)
    if stopped:
        typer.echo("Stopped at the first failure; add --continue-on-error to try every row.", err=True)
    mark = "✖" if counts.failed else "✔"
    if dry_run:
        typer.echo(f"{mark} {counts.succeeded:,} of {counts.total:,} rows are valid {address} records. Nothing was created (--dry-run).")
    elif counts.failed:
        typer.echo(f"{mark} Imported {counts.succeeded:,} of {counts.total:,} records into {address}; {counts.failed:,} failed.")
    else:
        typer.echo(f"{mark} Imported {counts.succeeded:,} records into {address}.")


@app.command("import")
def import_records(
    ctx: typer.Context,
    file: str = typer.Argument(..., metavar="FILE", help="NDJSON, JSON-array or CSV file; - reads stdin."),
    class_ref: str = typer.Option(
        ..., "--class", metavar="PROJECT/VERSION/CLASS", help="The class, e.g. billing/1.0.0/Charge (published version)."
    ),
    ndjson: bool = typer.Option(False, "--ndjson", help="The input is NDJSON: one JSON object per line."),
    csv_input: bool = typer.Option(False, "--csv", help="The input is CSV with a header row."),
    json_input: bool = typer.Option(False, "--json", help="The input is one JSON array of objects."),
    batch: int = typer.Option(100, "--batch", min=1, max=MAX_IMPORT_BATCH, help="Rows read and sent per batch."),
    concurrency: int = typer.Option(
        4, "--concurrency", min=1, max=MAX_IMPORT_CONCURRENCY, help="Batches sent at the same time."
    ),
    mapping: Optional[str] = typer.Option(
        None, "--mapping", help="CSV only: the columns to import, comma-separated; column=field renames one."
    ),
    continue_on_error: bool = typer.Option(
        False, "--continue-on-error", help="Try every row and exit 0 even when some fail (see failed_count)."
    ),
    report_path: Optional[Path] = typer.Option(
        None, "--report", metavar="PATH", help="Write a JSON report with one {row, status, record_id?, error?} per row."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate every row against the class schema; send nothing."),
) -> None:
    """Import many records into a published class from NDJSON, a JSON array or CSV.

    The file is streamed, so memory stays flat however large it is. The format comes from --ndjson, --csv or --json, else from the extension (.ndjson / .jsonl, .csv, .json); stdin (FILE -) needs the flag.

    Each row is checked against the class's JSON Schema before it is sent; CSV cells are typed from the schema (a number field gets a number). Rows go out in batches of --batch, --concurrency batches at a time, one POST /v1/data/{tenant}/records per row, retried on 429 and 5xx.

    A row that fails exits 7 and stops the import (rows already sent stay created). --continue-on-error tries every row and exits 0; --report lists every row's result and the failed_count.

    The progress bar is hidden under --quiet, the global --json, or when stderr is not a terminal. The global --json prints the summary as JSON.
    """
    try:
        fmt = detect_format(file, ndjson=ndjson, csv_=csv_input, json_=json_input)
        pairs = parse_mapping(mapping)
        address = parse_class_address(class_ref)
    except DataInputError as exc:
        _usage_error(str(exc))
    if pairs and fmt != FORMAT_CSV:
        _usage_error("--mapping only applies to CSV input (--csv or a .csv file).")
    json_mode = json_mode_from_context(ctx)
    stream = _open_source(file)

    client, tenant_slug = tenant_scoped_client(ctx)
    row = _resolve_class(client, tenant_slug, address)
    class_schema_id = str(row.get("class_schema_id"))
    schema = row.get("schema") if isinstance(row.get("schema"), Mapping) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    try:
        validate: Optional[Callable[[Mapping[str, Any]], list[Any]]] = record_validator(schema)
    except SchemaUnusable as exc:
        validate = None
        typer.echo(f"Warning: rows for {address} are not validated locally: {exc}.", err=True)

    read = _row_reader(fmt, pairs, properties)
    total = _count_rows(file, read) if progress_allowed(not json_mode) else None
    try:
        report = ReportWriter(report_path)
    except OSError as exc:
        _usage_error(f"Cannot write the report to {report_path}: {exc.strerror or exc}.")

    counts = ImportCounts()
    stopped = False
    records_path = api_paths.data_records(tenant_slug)

    def finish(results: list[RowResult], advance: Callable[[int], None]) -> None:
        nonlocal stopped
        for result in results:
            report.write(result)
            counts.add(result, keep_failures=MAX_FAILURES_SHOWN)
        advance(len(results))
        if counts.failed and not continue_on_error:
            stopped = True

    input_problem: Optional[str] = None
    try:
        with record_progress(total, description="Importing", enabled=not json_mode) as advance, ThreadPoolExecutor(
            max_workers=concurrency
        ) as pool:
            pending: deque[Future[list[RowResult]]] = deque()
            try:
                for rows in batches(read(stream), batch):
                    if stopped:
                        break
                    checked, cut = _check_rows(rows, validate, dry_run=dry_run, stop_on_error=not continue_on_error)
                    pending.append(pool.submit(_send_rows, client, records_path, class_schema_id, checked))
                    while len(pending) >= concurrency:
                        finish(pending.popleft().result(), advance)
                    if cut:
                        break
            except DataInputError as exc:
                input_problem = str(exc)
            except SchemaUnusable as exc:
                input_problem = f"Rows for {address} cannot be validated locally: {exc}."
            except UnicodeDecodeError:
                input_problem = f"{file} is not UTF-8 text."
            while pending:
                finish(pending.popleft().result(), advance)
    finally:
        summary = _import_summary(
            address,
            class_schema_id,
            counts,
            source=file,
            fmt=fmt,
            dry_run=dry_run,
            stopped=stopped,
            report_path=report_path,
        )
        report.close(summary)
        if stream is not sys.stdin:
            stream.close()

    if input_problem is not None and not counts.total:
        # Nothing was read (no header, a bad --mapping column, not an array): just say why.
        typer.echo(input_problem, err=True)
        raise typer.Exit(EXIT_USAGE)
    if json_mode:
        emit_json({**summary, "failures": [result.to_json() for result in counts.failures]})
    else:
        _echo_import_outcome(
            address, counts, dry_run=dry_run, stopped=summary["stopped_at_first_failure"], has_report=report_path is not None
        )
    if input_problem is not None:
        typer.echo(input_problem, err=True)
        raise typer.Exit(EXIT_USAGE)
    if counts.failed and not continue_on_error:
        raise typer.Exit(EXIT_IMPORT_FAILED)
