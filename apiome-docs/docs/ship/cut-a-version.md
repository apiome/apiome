---
title: "Cut a version"
description: "Create a new revision of a project to edit and later publish."
sidebar_position: 2
tags: [versions]
---

Cutting a version creates a new **revision** of a project. Classes are copied from the base version,
and so are its paths unless you untick **Copy paths** (see [Edit paths and operations](../build/edit-paths.md)). A version is the
unit you later **publish** ([Publish a version](./publish-a-version.md)).

---

## In the UI

1. Open **Versions** at `/ade/dashboard/versions`.
2. **Click “New version”**, keep **Auto-generate version** or type a **Version ID**, write a
   **Message**, and **click “Create version”**. (A **Viewer** doesn't see **New version**.)
3. The new revision becomes the working revision you edit. The full walk-through is in [Version and
   publish](../getting-started/versions-and-publishing.mdx).

## With the REST API

```http
POST /v1/versions/{tenant_slug}/{project_id}
X-API-Key: <your-api-key>

{
  "version_id": "1.1.0",
  "shortMessage": "Add the orders endpoint",
  "changelog": "…",
  "baseRevisionId": "<the project's current head revision id>",
  "source_version_id": "<the version to copy classes from>"
}
```

`version_id` is a plain `MAJOR.MINOR.PATCH` (leave it out to bump the latest version). The push
is locked to the head you name in `baseRevisionId`: the branch tip, or the newest revision of a
project without branches, or empty for a project's first version. If someone advanced the head
meanwhile, the API answers **409** with `code: STALE_HEAD`. Returns the newly created version
record (unpublished).

## With the CLI

`apiome versions create` looks the head up for you, so a CI job can cut a version in one line:

```bash
apiome versions create payments-api --version 1.1.0 --notes 'Add the orders endpoint'
apiome versions show payments-api 1.1.0
```

Classes are copied from the latest published version unless you pass `--base <version>` (or
`--empty`); add `--copy-paths` to copy its paths too. See
[Manage versions from the CLI](./manage-versions-from-the-cli.md) for every option and exit code.

## Verify

- **UI:** the new revision appears in the Versions list as unpublished.
- **CLI:** `apiome versions show <project> <version>` prints it with the state `draft`.

## Related

- [Edit paths and operations](../build/edit-paths.md) — author paths on the revision you just cut
- [Publish a version](./publish-a-version.md) — the next step
