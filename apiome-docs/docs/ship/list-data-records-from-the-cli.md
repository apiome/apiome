---
title: "List data records from the CLI"
description: "Page, filter and sort a published class's records with apiome data list."
sidebar_position: 2.3
tags: [data, cli, ci]
---

`apiome data list` shows the records stored in a class of a published version. You can page
through them, filter and sort them, and pipe them into other tools as JSON or NDJSON. Use it to
inspect what is stored, to debug a client that writes records, or to export records for an ETL
job.

To add records, see [Create data records from the CLI](./create-data-records-from-the-cli.md).

## Before you start

- **Install** the CLI and **sign in**: see [Install the CLI](../reference/install-the-cli.md) and the
  [CLI quick-start](../reference/cli-quickstart.md). In CI, set `APIOME_API_KEY`,
  `APIOME_BASE_URL` and `APIOME_TENANT_ID` instead of signing in.
- Your role needs **Versions: view**.
- Name the class as `<project>/<version>/<Class>`, e.g. `billing/1.0.0/Charge`. The rules are the
  same as for `data create`: see
  [Name the class](./create-data-records-from-the-cli.md#name-the-class). You can also give the class
  schema id that `apiome data create --json` prints as `class_schema_id`.

## List records

```text
$ apiome data list --class billing/1.0.0/Charge --limit 3
ID                                    CREATED           AMOUNT  CURRENCY  STATUS
8a2f0000-0000-4000-8000-000000000001  2026-05-04 12:41  19.99   USD       succeeded
8a2f0000-0000-4000-8000-000000000002  2026-05-04 12:42  100.0   EUR       succeeded
8a2f0000-0000-4000-8000-000000000003  2026-05-04 12:43  5       USD       failed

3 of 1,234 (use --next eyJvIjozfQ or --all).
```

The table has these columns:

- **ID** is the record id.
- **CREATED** is when the record was created.
- Then comes one column per data field, in the order the records first use them.

`--columns amount,status` shows only those fields. Long values are cut with `…`; use `--json`
to see them in full.

The footer shows how many records are on screen and how many match in total.

## Page through records

The CLI shows 50 records per page by default; `--limit` changes that (up to 500).

- **Next page:** copy the cursor from the footer and pass it to `--next`. Repeat until the footer
  has no cursor left:

  ```bash
  apiome data list --class billing/1.0.0/Charge --limit 3 --next eyJvIjozfQ
  ```

- **Every record:** `--all` follows every page for you.

A cursor only works with the query that printed it. If you change `--class`, `--filter`, `--sort`
or `--include-deleted`, start again without `--next`. Records added while you page can shift
later pages.

## Filter and sort

- `--filter key=value` keeps the records whose data field equals the value. The value is compared
  as text, so `--filter status=succeeded`, `--filter amount=19.99` and `--filter active=true` all
  work. Repeat `--filter` to require several fields (all must match).
- `--sort` takes `created_at` (the default), `updated_at`, `deleted_at`, `record_id`, or any data
  field. Put `-` in front to sort in descending order: `--sort -created_at`, `--sort -amount`.
  Numbers sort as numbers. Records without the field come last.

```bash
apiome data list --class billing/1.0.0/Charge --filter status=succeeded --sort -created_at --limit 20
```

## Show deleted records

Deleted records are hidden by default. Add `--include-deleted` to show them too. They keep the
data they had when they were deleted, and a **DELETED_AT** column shows when that happened:

```text
$ apiome data list --class billing/1.0.0/Charge --include-deleted --columns amount,status
ID                                    CREATED           AMOUNT  STATUS     DELETED_AT
8a2f0000-0000-4000-8000-000000000001  2026-05-04 12:41  19.99   succeeded
8a2f0000-0000-4000-8000-000000000004  2026-05-04 12:44  7       succeeded  2026-05-05 09:00
```

## JSON and NDJSON

- `--json` (before or after the command) prints the records as one JSON array.
- `--ndjson` prints one record per line with no surrounding array. This is the format most ETL
  tools read.

Each record is `{"record_id", "created_at", "updated_at", "deleted_at", "data"}`.

Both formats stream page by page, so `--all --ndjson > charges.ndjson` works however many records
there are. If more records remain after the page you asked for, `More records: --next <cursor>`
goes to stderr, so the output stays valid JSON.

```bash
apiome data list --class billing/1.0.0/Charge --all --ndjson | jq -r '.data.amount'
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The records were listed, including when none match |
| `1` | Apiome could not be reached, or the server failed |
| `2` | Bad options, an unknown project, version or class, an unpublished version, a cursor from another query, or a rejected request (including authentication) |

Every option is listed in the [`apiome data` reference](../reference/cli/data.md#data-list). The
endpoint behind it is `GET /v1/data/{tenant_slug}/records` in the
[REST reference](../reference/rest/data.md).
