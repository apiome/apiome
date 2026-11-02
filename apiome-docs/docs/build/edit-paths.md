---
title: "Edit paths and operations"
description: "Author URL templates and their operations on a version."
sidebar_position: 3
tags: [studio, paths]
---

A **path** is an OpenAPI URL template (e.g. `/pets/{petId}`); each path carries **operations** (GET,
POST, …) with parameters, request bodies, and responses. Paths are authored **on a specific version
(revision)** — unlike classes, they belong to the revision you are editing.

---

## In the UI

1. Open the **Designer** and go to **Paths** at `/ade/studio/paths`.
2. Add or select a path template, then edit its summary, tags, and description.
3. Add operations and wire their parameters, request bodies, and responses to your classes.

## With the REST API

All path routes are scoped by tenant **and** version id.

| Action | Method & route |
|---|---|
| List paths | `GET /v1/paths/{tenant_slug}/{version_id}` |
| Get one path | `GET /v1/paths/{tenant_slug}/{version_id}/{path_id}` |
| Create a path | `POST /v1/paths/{tenant_slug}/{version_id}` |
| Update a path | `PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}` |
| Delete a path | `DELETE /v1/paths/{tenant_slug}/{version_id}/{path_id}` |

Operations, parameters, request bodies, and responses hang off a path under
`/v1/paths/{tenant_slug}/{version_id}/{path_id}/…` (e.g. `…/operations`).

```http
PUT /v1/paths/{tenant_slug}/{version_id}/{path_id}
X-API-Key: <your-api-key>

{ "summary": "Find pet by ID", "tags": ["pets"] }
```

## With the CLI

The CLI inspects paths, operations, and Arazzo workflows for a version (read-only):

```bash
apiome paths      list <project> <version>
apiome paths      show <project> <version> <path>
apiome operations show <op-ref>   --project <id-or-slug> --version <id-or-label>
apiome workflows  list --project <id-or-slug> --version <id-or-label>
```

The project is a slug or UUID and the version a label (`2.1.0`), slug or UUID. The older
`--project <p> --version <v>` form still works for `paths list` and `paths show`.

### List a version's paths

```bash
apiome paths list payments-api 2.1.0
```

```text
┃ Path          ┃ Methods     ┃ Operations                ┃ Tags     ┃
│ /charges      │ GET, POST   │ listCharges, createCharge │ public   │
│ /charges/{id} │ GET, DELETE │ getCharge, deleteCharge   │ public   │
│ /webhooks     │ POST        │ receiveWebhook            │ internal │
```

There is one row per path. Filter with:
- `--method GET` and `--tag public` (both repeatable), which the server applies;
- `--search <text>` (or `--q`), which matches the path, method, operation id, summary or tags.

`--json` prints the API's array of path records, keeping only the ones `--search` matches when you
pass it.

### Show one path

```bash
apiome paths show payments-api 2.1.0 /charges/{id}
```

```text
/charges/{id} — One charge
├── GET getCharge — Fetch a charge  [public]
│   ├── params
│   │   ├── id (path, required) string
│   │   └── expand (query) string[]
│   └── responses
│       ├── 200 application/json → Charge
│       └── 404
└── DELETE deleteCharge  [public]  (deprecated)
    ├── params
    │   └── id (path, required) string
    └── responses
        └── 204
```

The path can be:
- the template (`/charges/{id}`, with or without the leading `/`);
- its URL-encoded form (`/charges/%7Bid%7D`);
- its JSON Pointer token (`~1charges~1{id}`, RFC 6901, as it appears after `#/paths/` in a `$ref`);
- the path's UUID.

Operations are listed in OpenAPI order (GET, PUT, POST, DELETE…). Each shows its parameters, request
body and responses, with the class or inline type each one carries. `--method` and `--tag` narrow
the operations shown. `--json` prints the API's full path object
(`GET /v1/paths/{tenant}/{version}/{path_id}/full`).

## Verify

- **CLI:** `apiome paths list <project> <version>` lists the path, and `apiome paths show <project>
  <version> <path>` shows its operations.
- **Export:** the path appears in the reconstructed OpenAPI document — see
  [Export a spec](../ship/export-a-spec.md).

## Related

- [Cut a version](../ship/cut-a-version.md) — paths are authored on the revision you cut
- [Lint and check quality](./lint-and-quality.md) — undocumented operations show up as findings
