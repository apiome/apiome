---
title: "OpenAPI Overlays"
description: "Apply Overlay 1.0, 1.1 and 1.2 documents to a base OpenAPI description."
sidebar_position: 49
tags: [import, openapi, overlay, lint]
---

An **OpenAPI Overlay** is a small document that changes a base OpenAPI description without editing
it: add a production server, hide an internal path, rewrite descriptions for a public audience. Each
overlay lists **actions**, and each action picks parts of the base with a JSONPath `target` and
updates, copies or removes them. Apiome applies the overlays to the base before it reads the API,
and records which overlay changed each value.

## Supported revisions

The `overlay` field at the top of the document says which revision it is written for. Apiome reads
the first two numbers (`1.1.0` and `1.1.3` are both **1.1**):

| Revision | What it can do |
| --- | --- |
| **1.0** | `target`, `update` and `remove`. An `update` on a list adds one entry. |
| **1.1** | Adds `copy` (take one part of the document and merge it somewhere else) and changing a single value. Lists are joined when merged. |
| **1.2** | Adds reusable actions (`components.actions`, used with `$ref`) and `$self`, the overlay's own address. |

An overlay that declares any other revision, such as `overlay: 1.3.0`, is refused with the message
*Apiome reads Overlay 1.0, 1.1 and 1.2*. It is not applied with rules it was not written for.

## Import a base with its overlays

An overlay only makes sense next to its base, so import them **together**:

1. Put the base OpenAPI document and its overlays in one `.zip` archive. Try
   `apiome-ui/examples/openapi/36-overlay-1-1-set/` (a base and an Overlay 1.1 document).
2. Import the archive, with the base document as the archive's root.

The fileset rule:

- The archive must hold **exactly one** base document (a file with an `openapi` or `swagger`
  field). Any number of overlays can sit beside it, and other files are left alone.
- Overlays are applied in file-name order, each to the result of the one before, so the last
  overlay wins any conflict.
- An overlay uploaded **without** its base is refused with `INPUT_OVERLAY_BASE_MISSING`. You can
  still [lint it on its own](#lint-an-overlay-on-its-own).

Pre-flight (`POST /v1/tenants/{tenant}/import/preflight`, and the **Quality** step of the import
wizard; see [Import a specification](./import-a-spec.md#check-quality-before-importing)) applies
the overlays and reports their findings next to the API's own. The import preview lists each value
an overlay set, replaced, appended or removed.

## Overlay rules

Overlay problems are lint findings in the **overlay** rule pack, so a style guide can raise any of
them to an error:

| Rule | Default | Flags |
| --- | --- | --- |
| [`overlay.unmatched-target`](../build/lint-rules.md#overlay-unmatched-target) | warning | An action whose `target` matches nothing in the base, so it changed nothing |
| [`overlay.action-invalid`](../build/lint-rules.md#overlay-action-invalid) | warning | An action that cannot be applied as written for its revision |
| [`overlay.target-expression-invalid`](../build/lint-rules.md#overlay-target-expression-invalid) | warning | A `target` or `copy` that is not a valid JSONPath expression |
| [`overlay.extends-unresolved`](../build/lint-rules.md#overlay-extends-unresolved) | warning | An `extends` that names a different document from the base it was applied to |
| [`overlay.version-unsupported`](../build/lint-rules.md#overlay-version-unsupported) | error | An overlay revision Apiome does not read |

These replace the earlier `intake.overlay-unmatched-target` and `intake.overlay-action-invalid`
rules. A style guide that set those ids should set the `overlay.*` ones instead.

## Lint an overlay on its own

You can check an overlay without its base:

```http
POST /v1/lint/overlay
Content-Type: application/json

{ "document": "overlay: 1.1.0\ninfo: …\nactions: …", "filename": "public.yaml" }
```

The answer lists the findings and a status for every overlay rule: `passed`, `failed` or
`skipped`. The two rules that need the base, `overlay.unmatched-target` and
`overlay.extends-unresolved`, are always `skipped` with reason `no-base`. They are never reported
as passed. See the [Lint reference](../reference/rest/lint.md).

## Where next

- [Import a specification](./import-a-spec.md): the import wizard and pre-flight
- [Supported formats](./supported-formats.md#version-coverage): the Overlay row in the version table
- [Built-in lint rules](../build/lint-rules.md): every rule, including the overlay pack
