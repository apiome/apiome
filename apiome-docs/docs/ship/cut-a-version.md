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

{ "version": "1.1.0", "description": "Add the orders endpoint", "notes": "…" }
```

Returns the newly created version record (unpublished).

## With the CLI

The CLI inspects versions (authoring/cutting happens in the UI/REST):

```bash
apiome versions list --project-id <id>
apiome versions get <version_id> --project-id <id>
```

## Verify

- **UI:** the new revision appears in the Versions list as unpublished.
- **CLI:** `apiome versions list --project-id <id>` shows it.

## Related

- [Edit paths and operations](../build/edit-paths.md) — author paths on the revision you just cut
- [Publish a version](./publish-a-version.md) — the next step
