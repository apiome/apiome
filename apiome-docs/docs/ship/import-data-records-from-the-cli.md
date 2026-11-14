---
title: "Import data records from the CLI"
description: "Bulk-load NDJSON, JSON or CSV records into a class with apiome data import."
sidebar_position: 2.4
tags: [data, cli, ci]
---

`apiome data import` loads many records into a class of a published version in one go. It reads
NDJSON, a JSON array or CSV, checks each row against the class's JSON Schema, and sends the rows
in parallel batches with a progress bar. Use it to seed a class, migrate records from another
system, or load an export made with `apiome data list --ndjson`.

To add one record, see [Create data records from the CLI](./create-data-records-from-the-cli.md).
To check what was loaded, see [List data records from the CLI](./list-data-records-from-the-cli.md).

## Before you start

- **Install** the CLI and **sign in**: see [Install the CLI](../reference/install-the-cli.md) and the
  [CLI quick-start](../reference/cli-quickstart.md). In CI, set `APIOME_API_KEY`,
  `APIOME_BASE_URL` and `APIOME_TENANT_ID` instead of signing in.
- Your role needs **Versions: create**.
- Name the class as `<project>/<version>/<Class>`, e.g. `billing/1.0.0/Charge`. The version must be
  published. See [Name the class](./create-data-records-from-the-cli.md#name-the-class).

## Import a file

```text
$ apiome data import ./charges.ndjson --class billing/1.0.0/Charge --batch 500
Importing ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━  60%  7407/12345  812 rec/s
✔ Imported 12,345 records into billing/1.0.0/Charge.
```

The CLI reads the file as a stream, so memory use stays the same however large the file is.

The format comes from the file's extension:

| Extension | Format |
| --- | --- |
| `.ndjson`, `.jsonl` | NDJSON: one JSON object per line. Blank lines are skipped. |
| `.json` | One JSON array of objects. |
| `.csv` | CSV with a header row. See [Import CSV](#import-csv). |

For any other extension, add `--ndjson`, `--json` or `--csv`. Here `--json` names the **input**
format. To get the summary as JSON, put `--json` **before** the command: `apiome --json data import …`.

To read from a pipe, pass `-` as the file and name the format:

```bash
apiome data import - --class billing/1.0.0/Charge --ndjson < charges.ndjson
```

## Import CSV

The first row of the file names the columns. By default every column becomes a field of the same
name. `--mapping` picks the columns to import and can rename them: list the columns, separated by
commas, and write `column=field` to rename one:

```bash
apiome data import ./customers.csv --class crm/2.0.0/Customer \
  --mapping 'first_name,last_name,email_addr=email'
```

This imports `first_name` and `last_name` as they are, imports `email_addr` as `email`, and skips
every other column. If a mapped column is not in the header, the CLI lists the file's columns and
exits 2.

CSV cells are text. The CLI converts each cell to the type that the class schema gives the field:

| Field type | Cell | Becomes |
| --- | --- | --- |
| `number` | `19.99`, `5` | `19.99`, `5` |
| `integer` | `3` | `3` |
| `boolean` | `true`, `FALSE` | `true`, `false` |
| `null` allowed | `null` | `null` |
| `object`, `array` | `{"k":1}`, `[1,2]` | the parsed JSON |
| `string`, or no type | anything | the text as it is |

An empty cell leaves the field out of the record. An optional field then stays unset, and a
required one is reported as missing. If a cell cannot be converted, it stays text, and the
schema check then reports the field.

## How rows are checked and sent

1. **Checked locally.** Each row is validated against the class's JSON Schema before anything is
   sent, so a bad row costs no round trip. A row that is not JSON or not an object fails here too.
2. **Batched.** Rows are grouped into batches of `--batch` rows (default `100`). Up to
   `--concurrency` batches (default `4`, at most `16`) are sent at the same time.
3. **Sent.** Each row is sent as its own `POST /v1/data/{tenant_slug}/records` request. A `429` or
   `5xx` answer is retried up to three more times. The wait doubles each time, or follows
   `Retry-After` (at most 30 seconds).

The progress bar is drawn on stderr. It is hidden under `--quiet`, under the global `--json`, and
when stderr is not a terminal (in CI logs, for example). Before importing a file, the CLI reads it
once to count its rows so the bar can show a percentage. From a pipe it shows only the count so far.

## When a row fails

By default the import **stops at the first failure** and exits `7`. Rows sent before the failure
stay created. Each failed row is printed on stderr:

```text
Row 2 (invalid): amount: 'x' is not of type 'number'
Stopped at the first failure; add --continue-on-error to try every row.
✖ Imported 1 of 2 records into billing/1.0.0/Charge; 1 failed.
```

`--continue-on-error` tries every row and exits `0` even when some fail. The summary and the
report's `failed_count` say how many failed. The first 20 failures are printed. Write a report to
see all of them.

`--dry-run` checks every row against the schema and sends nothing. Combine it with
`--continue-on-error` to list every bad row in a file before you import it:

```bash
apiome data import ./charges.ndjson --class billing/1.0.0/Charge --dry-run --continue-on-error
```

## The report

`--report <path>` writes a JSON file with one entry per row, written as the import goes:

```json
{"rows":[
{"row": 1, "status": "created", "record_id": "8a2f0000-0000-4000-8000-000000000001"},
{"row": 2, "status": "invalid", "error": "amount: 'x' is not of type 'number'"}
],"project": "billing", "version": "1.0.0", "class": "Charge", "class_schema_id": "…",
"source": "./charges.ndjson", "format": "ndjson", "dry_run": false, "total": 2,
"created_count": 1, "valid_count": null, "failed_count": 1,
"stopped_at_first_failure": true, "report": "report.json"}
```

- `row` is the row's position in the input, starting at 1. Blank NDJSON lines and the CSV header
  are not counted.
- `status` is `created`, `valid` (under `--dry-run`), `invalid` (it failed the local check) or
  `failed` (the server refused it).
- `record_id` is set for created rows. `error` says why a row failed.

The global `--json` prints the same summary (without `rows`) on stdout, plus `failures` with the
first 20 failed rows.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Every row was imported, or `--continue-on-error` was given |
| `1` | Apiome could not be reached, or the server failed |
| `2` | Bad options, an unreadable file, an unknown format, a `--mapping` column the CSV lacks, an unknown project, version or class, an unpublished version, or a JSON array that is malformed part-way (the rows before the problem are imported) |
| `7` | A row failed and `--continue-on-error` was not given |

Every option is listed in the [`apiome data` reference](../reference/cli/data.md#data-import). The
endpoint behind it is `POST /v1/data/{tenant_slug}/records` in the
[REST reference](../reference/rest/data.md).
