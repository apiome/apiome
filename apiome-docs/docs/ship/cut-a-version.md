---
title: "Cut a version"
description: "Create a new revision of a project to edit and later publish."
sidebar_position: 2
tags: [versions]
---

Cutting a version creates a new **revision** of a project. Classes are carried over from the base,
while paths are authored on the new revision (see [Edit paths and operations](../build/edit-paths.md)). A version is the
unit you later **publish** ([Publish a version](./publish-a-version.md)).

---

## In the UI

1. Open **Versions** at `/ade/dashboard/versions`.
2. Choose **Cut a version**, set the version number and a revision note.
3. The new revision becomes the working revision you edit.

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
