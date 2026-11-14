---
title: "Create data records from the CLI"
description: "Add a record to a published class with apiome data create."
sidebar_position: 2.2
tags: [data, cli, ci]
---

When you publish a version, Apiome freezes a JSON Schema for each of its classes. Records are
stored against that frozen schema: a `Charge` record created against `billing 1.0.0` keeps
matching `billing 1.0.0`'s `Charge`, even after later versions change the class.

`apiome data create` adds one record from a terminal or a script. It finds the class, checks the
record against the class's JSON Schema **before** sending it, and creates it with
`POST /v1/data/{tenant_slug}/records`. Use it to seed test data, or to add a record without
writing client code.

## Before you start

- **Install** the CLI and **sign in**: see [Install the CLI](../reference/install-the-cli.md) and the
  [CLI quick-start](../reference/cli-quickstart.md). In CI, set `APIOME_API_KEY`,
  `APIOME_BASE_URL` and `APIOME_TENANT_ID` instead of signing in.
- The version must be **published** — see [Publish a version](./publish-a-version.md). A draft
  has no frozen class schemas yet, so the command stops and asks you to publish it first.
- Your role needs **Versions: view** to look the class up and **Versions: create** to add the
  record.

## Name the class

`--class` takes `<project>/<version>/<Class>`:

| Part | What it is | Example |
| --- | --- | --- |
| project | The project's **slug** | `billing` |
| version | The version **label**, with or without a `v` | `1.0.0` or `v1.0.0` |
| Class | The class name; a different case still matches if only one class matches | `Charge` |

If no class has that name, the command lists the version's classes so you can pick the right one.

## Create a record

1. Write the record as a JSON or YAML object whose fields are the class's properties:

   ```json title="charge.json"
   { "amount": 19.99, "currency": "USD", "customer_id": "cu_1042" }
   ```

2. Create it:

   ```text
   $ apiome data create --class billing/1.0.0/Charge --from-file charge.json
   ✔ Created 9b3e1c4a-…-f50d in billing/1.0.0/Charge.
   ```

The same record can come from **stdin** or from **`--field`** options. All three send the same
request:

```bash
echo '{"amount":19.99,"currency":"USD","customer_id":"cu_1042"}' \
  | apiome data create --class billing/1.0.0/Charge --stdin

apiome data create --class billing/1.0.0/Charge \
  --field amount=:19.99 --field currency=USD --field customer_id=cu_1042
```

### `--field key=value`

- A value is a **string**: `--field currency=USD`.
- Start the value with `:` to parse it as **JSON**. Use this for numbers, booleans, lists, objects
  and `null`: `--field amount=:19.99`, `--field active=:true`, `--field tags=:'["vip"]'`.
- `--field` can be combined with `--from-file` or `--stdin`. Each field then replaces the key of
  the same name in the file, so one file can be reused with a different value:
  `--from-file charge.json --field currency=EUR`.
- If you give the same key twice, the last value wins.

## Check a record without creating it

`--dry-run` looks up the class and validates the record, then stops. Nothing is sent:

```text
$ apiome data create --class billing/1.0.0/Charge --from-file charge.json --dry-run
✔ Valid billing/1.0.0/Charge record. Nothing was created (--dry-run).
```

## When the record does not match

Every problem is printed on its own line as `field: message`, and the command exits **7**. Nothing
is created:

```text
$ apiome data create --class billing/1.0.0/Charge --field amount=19.99
amount: '19.99' is not of type 'number'
currency: is required
Nothing was created.
```

A nested field is written as a path (`address/city`). A problem with the record as a whole, such
as a field the class does not allow, is reported as `(record)`.

If the class schema has a reference the CLI cannot resolve offline (for example a `$ref` to a
type in a registry), the record cannot be checked locally. The CLI prints a warning and creates
the record anyway, because the server stores records as given.

## Machine-readable output

Add `--json` (before the command, or after it) to print the created record:

```json
{"record_id":"9b3e1c4a-…-f50d","project":"billing","version":"1.0.0","class":"Charge","class_schema_id":"…","data":{"amount":19.99,"currency":"USD","customer_id":"cu_1042"}}
```

With `--dry-run`, the object has `"valid": true, "dry_run": true` and no `record_id`.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The record was created (or, with `--dry-run`, is valid) |
| `1` | Apiome could not be reached, or the server failed |
| `2` | Bad options or input, an unknown project, version or class, an unpublished version, or a rejected request (including authentication) |
| `7` | The record does not match the class schema; nothing was created |

To see the records you created, use [List data records from the CLI](./list-data-records-from-the-cli.md).
To load many records at once from NDJSON, JSON or CSV, use [Import data records from the CLI](./import-data-records-from-the-cli.md).
Every option is listed in the [`apiome data` reference](../reference/cli/data.md). The lookup
behind `--class` is `GET /v1/data/{tenant_slug}/classes` in the
[REST reference](../reference/rest/data.md).
