"""``apiome data import <file> --class <class>`` (CLI 10.7, #3259).

The rules in :mod:`apiome_cli.data_import` — format detection, the streaming NDJSON / JSON-array /
CSV readers, ``--mapping`` and CSV typing, batching, retries, the report writer — and the command
against a mocked ``GET /v1/data/{tenant}/classes`` + ``POST /v1/data/{tenant}/records``: local
validation, ``--dry-run``, stop-at-first-failure vs ``--continue-on-error`` (exit 7 / 0),
``--report``, the global ``--json`` summary, stdin and usage errors.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli import data_import
from apiome_cli.data_import import (
    ImportCounts,
    ReportWriter,
    Row,
    RowResult,
    batches,
    coerce_cell,
    detect_format,
    iter_csv,
    iter_json_array,
    iter_ndjson,
    map_csv_row,
    parse_mapping,
    post_with_retry,
)
from apiome_cli.data_record import DataInputError
from apiome_cli.exit_codes import EXIT_IMPORT_FAILED, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.progress import progress_allowed, record_progress

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_CS = "33333333-3333-4333-8333-333333333333"
_CLASSES = "http://localhost:8000/v1/data/acme/classes?project=billing&version=1.0.0"
_RECORDS = "http://localhost:8000/v1/data/acme/records"
_SCHEMA = {
    "type": "object",
    "properties": {
        "amount": {"type": "number"},
        "currency": {"type": "string"},
        "count": {"type": "integer"},
        "active": {"type": "boolean"},
    },
    "required": ["amount", "currency"],
}
_LOOKUP = {
    "success": True,
    "project": "billing",
    "version": "1.0.0",
    "published": True,
    "classes": [{"class_schema_id": _CS, "class_id": "c-1", "class_name": "Charge", "schema": _SCHEMA}],
}


# ---- format ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, fmt",
    [("a.ndjson", "ndjson"), ("a.JSONL", "ndjson"), ("a.csv", "csv"), ("dir/a.json", "json")],
)
def test_detect_format_from_extension(path, fmt) -> None:
    assert detect_format(path, ndjson=False, csv_=False, json_=False) == fmt


def test_detect_format_flag_wins_and_rules() -> None:
    assert detect_format("a.txt", ndjson=False, csv_=True, json_=False) == "csv"
    assert detect_format("-", ndjson=True, csv_=False, json_=False) == "ndjson"
    with pytest.raises(DataInputError, match="one of"):
        detect_format("a.csv", ndjson=True, csv_=True, json_=False)
    with pytest.raises(DataInputError, match="stdin"):
        detect_format("-", ndjson=False, csv_=False, json_=False)
    with pytest.raises(DataInputError, match="extension"):
        detect_format("a.txt", ndjson=False, csv_=False, json_=False)


# ---- readers -----------------------------------------------------------------------------------


def test_iter_ndjson_skips_blank_lines_and_flags_bad_ones() -> None:
    rows = list(iter_ndjson(io.StringIO('{"a":1}\n\n  \nnot json\n[1]\n{"b":2}\n')))
    assert [(r.number, r.data, r.error is None) for r in rows] == [
        (1, {"a": 1}, True),
        (2, None, False),
        (3, None, False),
        (4, {"b": 2}, True),
    ]
    assert rows[1].error.startswith("is not valid JSON")
    assert rows[2].error == "is not a JSON object"


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 64 * 1024])
def test_iter_json_array_streams_across_chunks(chunk) -> None:
    text = ' [ {"a": 1, "s": "x,]"} , {"b": [1, 2]},\n{"c": 12345}, 42 ] '
    rows = list(iter_json_array(io.StringIO(text), chunk_size=chunk))
    assert [r.data for r in rows] == [{"a": 1, "s": "x,]"}, {"b": [1, 2]}, {"c": 12345}, None]
    assert rows[3].error == "is not a JSON object"


def test_iter_json_array_empty_and_errors() -> None:
    assert list(iter_json_array(io.StringIO("[]"))) == []
    with pytest.raises(DataInputError, match="not a JSON array"):
        list(iter_json_array(io.StringIO('{"a":1}')))
    with pytest.raises(DataInputError, match="not a JSON array"):
        list(iter_json_array(io.StringIO("")))
    with pytest.raises(DataInputError, match="without a closing"):
        list(iter_json_array(io.StringIO('[{"a":1},'), chunk_size=2))
    with pytest.raises(DataInputError, match="expected ','"):
        list(iter_json_array(io.StringIO('[{"a":1} {"b":2}]')))
    with pytest.raises(DataInputError, match="Element 2"):
        list(iter_json_array(io.StringIO('[{"a":1}, {"b":')))


def test_iter_json_array_reads_lazily() -> None:
    """The first element arrives before the rest of the array is read."""
    stream = io.StringIO('[{"a":1},' + '{"b":2},' * 10_000 + '{"c":3}]')
    rows = iter_json_array(stream, chunk_size=16)
    assert next(rows).data == {"a": 1}
    assert stream.tell() < 100


def test_parse_mapping() -> None:
    assert parse_mapping(None) == []
    assert parse_mapping("first_name, last_name ,email_addr=email") == [
        ("first_name", "first_name"),
        ("last_name", "last_name"),
        ("email_addr", "email"),
    ]
    for bad in ("a,,b", "=x", "a="):
        with pytest.raises(DataInputError, match="column or column=field"):
            parse_mapping(bad)
    with pytest.raises(DataInputError, match="several columns to email"):
        parse_mapping("email,addr=email")


@pytest.mark.parametrize(
    "text, prop, value",
    [
        ("19.99", {"type": "number"}, 19.99),
        ("3", {"type": "number"}, 3),
        ("3.0", {"type": "number"}, 3.0),
        ("1e3", {"type": "number"}, 1000.0),
        ("nan", {"type": "number"}, "nan"),
        ("7", {"type": "integer"}, 7),
        ("7.5", {"type": "integer"}, "7.5"),
        ("TRUE", {"type": "boolean"}, True),
        ("false", {"type": "boolean"}, False),
        ("yes", {"type": "boolean"}, "yes"),
        ("null", {"type": ["integer", "null"]}, None),
        ("42", {"type": ["string", "null"]}, "42"),
        ('{"k":1}', {"type": "object"}, {"k": 1}),
        ("[1,2]", {"type": "array"}, [1, 2]),
        ("x", {"type": "array"}, "x"),
        ("12", None, "12"),
        ("12", {"description": "untyped"}, "12"),
    ],
)
def test_coerce_cell(text, prop, value) -> None:
    assert coerce_cell(text, prop) == value


def test_map_csv_row_maps_types_and_drops_empty_cells() -> None:
    props = _SCHEMA["properties"]
    cells = {"amount": "19.99", "currency": "USD", "count": "", "extra": "x"}
    assert map_csv_row(cells, [], props) == {"amount": 19.99, "currency": "USD", "extra": "x"}
    assert map_csv_row(cells, [("amount", "amount"), ("currency", "cur")], props) == {"amount": 19.99, "cur": "USD"}


def test_iter_csv() -> None:
    text = "first_name,email_addr,age\nAda,ada@example.com,36\nBob,b@example.com,40,extra\n"
    rows = list(iter_csv(io.StringIO(text), parse_mapping("first_name,email_addr=email"), {}))
    assert rows[0] == Row(1, {"first_name": "Ada", "email": "ada@example.com"})
    assert rows[1].data is None and "more cells" in rows[1].error


def test_iter_csv_errors() -> None:
    with pytest.raises(DataInputError, match="no header"):
        list(iter_csv(io.StringIO(""), [], {}))
    with pytest.raises(DataInputError, match="does not have: phone. Its columns: a, b"):
        list(iter_csv(io.StringIO("a,b\n1,2\n"), [("phone", "phone")], {}))


def test_batches() -> None:
    rows = [Row(n, {}) for n in range(1, 6)]
    assert [[r.number for r in b] for b in batches(rows, 2)] == [[1, 2], [3, 4], [5]]
    assert list(batches([], 3)) == []


# ---- retries -----------------------------------------------------------------------------------


def _response(status: int, body=None, headers=None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers, request=httpx.Request("POST", _RECORDS))


def test_post_with_retry_retries_429_and_5xx() -> None:
    answers = iter([
        _response(429, {"detail": "slow down"}, {"Retry-After": "2"}),
        _response(503, {"detail": "busy"}),
        _response(200, {"success": True, "record_id": "rc_1"}),
    ])
    waits: list[float] = []
    assert post_with_retry(lambda: next(answers), sleep=waits.append) == ("rc_1", None)
    assert waits == [2.0, 1.0]


def test_post_with_retry_gives_up() -> None:
    calls: list[int] = []

    def send():
        calls.append(1)
        return _response(500, {"detail": "boom"})

    record_id, error = post_with_retry(send, max_attempts=3, sleep=lambda _s: None)
    assert record_id is None and "boom" in error and len(calls) == 3


def test_post_with_retry_does_not_retry_4xx() -> None:
    calls: list[int] = []

    def send():
        calls.append(1)
        return _response(404, {"detail": "Class schema not found."})

    record_id, error = post_with_retry(send, sleep=lambda _s: pytest.fail("no retry"))
    assert record_id is None and "Class schema not found" in error and len(calls) == 1


def test_post_with_retry_without_record_id() -> None:
    assert post_with_retry(lambda: _response(200, {"success": True})) == (None, "the server did not return a record_id")


# ---- report ------------------------------------------------------------------------------------


def test_report_writer(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    writer = ReportWriter(path)
    writer.write(RowResult(1, "created", record_id="rc_1"))
    writer.write(RowResult(2, "invalid", error="amount: is required"))
    writer.close({"total": 2, "failed_count": 1})
    assert json.loads(path.read_text()) == {
        "rows": [
            {"row": 1, "status": "created", "record_id": "rc_1"},
            {"row": 2, "status": "invalid", "error": "amount: is required"},
        ],
        "total": 2,
        "failed_count": 1,
    }


def test_report_writer_empty_and_disabled(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    writer = ReportWriter(path)
    writer.close({})
    assert json.loads(path.read_text()) == {"rows": []}
    ReportWriter(None).close({"total": 0})  # no file, no error


def test_import_counts_keeps_the_first_failures() -> None:
    counts = ImportCounts()
    for n in range(5):
        counts.add(RowResult(n, "failed", error="x"), keep_failures=2)
    counts.add(RowResult(9, "created"), keep_failures=2)
    assert (counts.total, counts.succeeded, counts.failed, len(counts.failures)) == (6, 1, 5, 2)


# ---- command -----------------------------------------------------------------------------------


class _Server:
    """A stand-in for ``POST /v1/data/{tenant}/records``: stores each body, answers with an id."""

    def __init__(self, *, fail_amounts=(), flaky: int = 0) -> None:
        self.created: list[dict] = []
        self.fail_amounts = set(fail_amounts)
        self.flaky = flaky

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["class_schema_id"] == _CS
        if self.flaky:
            self.flaky -= 1
            return httpx.Response(503, json={"detail": "busy"})
        if body["data"].get("amount") in self.fail_amounts:
            return httpx.Response(400, json={"detail": "refused by the server"})
        self.created.append(body["data"])
        return httpx.Response(200, json={"success": True, "record_id": f"rc_{len(self.created)}"})


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_import.time, "sleep", lambda _s: None)


def _serve(httpx_mock, server: _Server | None = None) -> _Server:
    server = server or _Server()
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    httpx_mock.add_callback(server, url=_RECORDS, method="POST", is_reusable=True, is_optional=True)
    return server


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _import(*args: str, root: tuple[str, ...] = (), stdin: str | None = None):
    return runner.invoke(
        app, [*root, "data", "import", *args, "--class", "billing/1.0.0/Charge"], env=_ENV, input=stdin
    )


_NDJSON = "".join(json.dumps({"amount": n, "currency": "USD"}) + "\n" for n in range(1, 8))


def test_import_ndjson(httpx_mock, tmp_path) -> None:
    server = _serve(httpx_mock)
    path = _write(tmp_path, "charges.ndjson", _NDJSON)
    result = _import(str(path), "--batch", "3", "--concurrency", "2")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "✔ Imported 7 records into billing/1.0.0/Charge." in result.stdout
    assert sorted(d["amount"] for d in server.created) == list(range(1, 8))


def test_import_json_array_and_report(httpx_mock, tmp_path) -> None:
    _serve(httpx_mock)
    path = _write(tmp_path, "charges.json", json.dumps([{"amount": 1, "currency": "USD"}, {"amount": 2, "currency": "EUR"}]))
    report = tmp_path / "out" / "report.json"
    report.parent.mkdir()
    result = _import(str(path), "--report", str(report))
    assert result.exit_code == EXIT_SUCCESS, result.output
    written = json.loads(report.read_text())
    assert written["rows"] == [
        {"row": 1, "status": "created", "record_id": written["rows"][0]["record_id"]},
        {"row": 2, "status": "created", "record_id": written["rows"][1]["record_id"]},
    ]
    assert (written["total"], written["created_count"], written["failed_count"]) == (2, 2, 0)
    assert written["format"] == "json" and written["class_schema_id"] == _CS


def test_import_csv_with_mapping_types_cells(httpx_mock, tmp_path) -> None:
    server = _serve(httpx_mock)
    path = _write(tmp_path, "charges.csv", "amt,cur,n,active,note\n19.99,USD,3,true,x\n5,EUR,,false,y\n")
    result = _import(str(path), "--mapping", "amt=amount,cur=currency,n=count,active")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert server.created == [
        {"amount": 19.99, "currency": "USD", "count": 3, "active": True},
        {"amount": 5, "currency": "EUR", "active": False},
    ]


def test_import_stdin(httpx_mock) -> None:
    server = _serve(httpx_mock)
    result = _import("-", "--ndjson", stdin=_NDJSON)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(server.created) == 7


def test_import_stops_at_the_first_invalid_row(httpx_mock, tmp_path) -> None:
    server = _serve(httpx_mock)
    text = '{"amount":1,"currency":"USD"}\n{"amount":"x","currency":"USD"}\n{"amount":3,"currency":"USD"}\n'
    report = tmp_path / "report.json"
    result = _import(str(_write(tmp_path, "c.ndjson", text)), "--report", str(report))
    assert result.exit_code == EXIT_IMPORT_FAILED
    assert "Row 2 (invalid): amount: 'x' is not of type 'number'" in result.stderr
    assert "Stopped at the first failure" in result.stderr
    assert "✖ Imported 1 of 2 records into billing/1.0.0/Charge; 1 failed." in result.stdout
    assert [d["amount"] for d in server.created] == [1]
    written = json.loads(report.read_text())
    assert [r["status"] for r in written["rows"]] == ["created", "invalid"]
    assert written["stopped_at_first_failure"] is True and written["failed_count"] == 1


def test_import_continue_on_error_exits_0(httpx_mock, tmp_path) -> None:
    server = _serve(httpx_mock, _Server(fail_amounts={4}))
    text = _NDJSON + "not json\n" + '{"currency":"USD"}\n'
    report = tmp_path / "report.json"
    result = _import(str(_write(tmp_path, "c.ndjson", text)), "--continue-on-error", "--batch", "2", "--report", str(report))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(server.created) == 6
    written = json.loads(report.read_text())
    assert [r["row"] for r in written["rows"]] == list(range(1, 10))
    failed = {r["row"]: r for r in written["rows"] if r["status"] != "created"}
    assert failed[4]["status"] == "failed" and "refused by the server" in failed[4]["error"]
    assert failed[8]["error"].startswith("is not valid JSON")
    assert failed[9]["error"] == "amount: is required"
    assert written["failed_count"] == 3 and written["stopped_at_first_failure"] is False


def test_import_retries_server_errors(httpx_mock, tmp_path) -> None:
    server = _serve(httpx_mock, _Server(flaky=2))
    result = _import(str(_write(tmp_path, "c.ndjson", '{"amount":1,"currency":"USD"}\n')))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(server.created) == 1


def test_import_dry_run_sends_nothing(httpx_mock, tmp_path) -> None:
    server = _serve(httpx_mock)
    text = _NDJSON + '{"amount":"x","currency":"USD"}\n'
    result = _import(str(_write(tmp_path, "c.ndjson", text)), "--dry-run", "--continue-on-error")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert server.created == []
    assert "✖ 7 of 8 rows are valid billing/1.0.0/Charge records. Nothing was created (--dry-run)." in result.stdout
    assert not [r for r in httpx_mock.get_requests() if r.method == "POST"]


def test_import_global_json_summary(httpx_mock, tmp_path) -> None:
    _serve(httpx_mock)
    result = _import(str(_write(tmp_path, "c.ndjson", _NDJSON)), root=("--json",))
    assert result.exit_code == EXIT_SUCCESS, result.output
    summary = json.loads(result.stdout)
    assert summary["total"] == 7 and summary["created_count"] == 7 and summary["failed_count"] == 0
    assert summary["failures"] == [] and summary["dry_run"] is False and summary["class"] == "Charge"


def test_import_lists_at_most_20_failures(httpx_mock, tmp_path) -> None:
    _serve(httpx_mock)
    text = '{"currency":"USD"}\n' * 25
    result = _import(str(_write(tmp_path, "c.ndjson", text)), "--continue-on-error", "--dry-run")
    assert result.stderr.count("(invalid)") == 20
    assert "… and 5 more failed rows; add --report <path> to list every row." in result.stderr


def test_import_malformed_json_array_exits_2_after_the_good_rows(httpx_mock, tmp_path) -> None:
    server = _serve(httpx_mock)
    path = _write(tmp_path, "c.json", '[{"amount":1,"currency":"USD"} {"amount":2}]')
    result = _import(str(path))
    assert result.exit_code == EXIT_USAGE
    assert "malformed after element 1" in result.stderr
    assert len(server.created) == 1


@pytest.mark.parametrize(
    "args, message",
    [
        (("c.txt",), "Cannot tell the format"),
        (("c.ndjson", "--csv", "--json"), "Give one of"),
        (("c.ndjson", "--mapping", "a=b"), "--mapping only applies to CSV"),
        (("missing.ndjson",), "Cannot read missing.ndjson"),
    ],
)
def test_import_usage_errors(args, message) -> None:
    result = _import(*args)
    assert result.exit_code == EXIT_USAGE
    assert message in result.stderr


def test_import_bad_mapping_column(httpx_mock, tmp_path) -> None:
    _serve(httpx_mock)
    result = _import(str(_write(tmp_path, "c.csv", "a,b\n1,2\n")), "--mapping", "phone")
    assert result.exit_code == EXIT_USAGE
    assert "does not have: phone" in result.stderr
    assert "Imported" not in result.stdout


def test_import_bad_class_address() -> None:
    result = runner.invoke(app, ["data", "import", "c.ndjson", "--class", "Charge"], env=_ENV)
    assert result.exit_code == EXIT_USAGE
    assert "must be <project>/<version>/<Class>" in result.stderr


def test_batches_yields_the_rows_read_before_an_error() -> None:
    def rows():
        yield Row(1, {})
        raise DataInputError("broken")

    seen = []
    with pytest.raises(DataInputError, match="broken"):
        for batch in batches(rows(), 10):
            seen.append([r.number for r in batch])
    assert seen == [[1]]


# ---- progress ----------------------------------------------------------------------------------


def test_record_progress_is_a_no_op_off_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apiome_cli.progress.sys.stderr.isatty", lambda: False)
    with record_progress(10, description="Importing") as advance:
        advance(5)  # nothing drawn, nothing raised


@pytest.mark.parametrize("total", [3, None])
def test_record_progress_draws_on_a_terminal(monkeypatch: pytest.MonkeyPatch, total) -> None:
    monkeypatch.setattr("apiome_cli.progress.sys.stderr.isatty", lambda: True)
    with record_progress(total, description="Importing") as advance:
        advance(2)
        advance(1)


def test_record_progress_disabled_under_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apiome_cli.progress.sys.stderr.isatty", lambda: True)
    assert progress_allowed(True)
    assert not progress_allowed(False)  # data import passes enabled=not json_mode
