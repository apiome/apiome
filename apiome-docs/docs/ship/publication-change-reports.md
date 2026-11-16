---
title: "Publication change reports"
description: "A readable report of what changed, written every time you publish."
sidebar_position: 3.05
tags: [versions, publish, change-report]
---

Every time you **publish** a version, Apiome compares its OpenAPI with an earlier published version
— the **baseline** — and writes a **change report**: a short, readable account of what changed, with
a **header**, a **body** and a **footnote**. The report is kept with that publication, so the release
notes your API consumers read come from the spec itself rather than from a document that drifts.

## When to use it

- You want release notes for a published version without writing them by hand.
- You want to check, before publishing, what consumers will see as changed.
- You want every team in the workspace to word its reports the same way (a shared **template**).
- You need a reviewed, approved copy to send outside your organisation (review and PDF export).

To see the raw differences between two versions instead, use
[Compare published versions](./compare-published-versions.md). To fail a build or a publish on a
breaking change, see [Contract testing and CI gates](./contract-testing-and-ci-gates.mdx).

## What the report covers

Both versions are read as **resolved** OpenAPI 3.x (components merged, `$ref` normalised). The
comparison reports:

| Section | What it lists |
| --- | --- |
| **Schemas** | Schemas added, removed and modified |
| **Properties** | Properties added or removed, and changes to a type, `required` or a constraint such as `enum`, `format` or `minimum` |
| **References** | `$ref` targets that changed |
| **Relationships** | Composition that changed: `allOf`, `oneOf`, `anyOf` and `discriminator` |
| **Documentation** | Changed `title`, `description` and `summary` text |
| **Warnings** / **Not diffed** | What could not be compared (an external `$ref`, for example), and why |

The built-in template opens with a table of counts and then lists each section. The structured
result is stored with the report as `changeModelJson`, so the text can be rendered again later with
another template.

## How the baseline is chosen

The publish request (and its preview) takes `changeReportBaselineMode`:

| Mode | Compares with |
| --- | --- |
| `auto` (default) | The latest published version before this one on the same line |
| `initial` | Nothing — the report reads **Initial publication** and lists everything as new |
| `manual` | The published version you name in `changeReportBaselineRevisionId` |

When `auto` finds no earlier published version, the report is an initial publication too. A
`manual` baseline must be a **published** version of the **same project**, and not the version being
published; otherwise the publish is refused with **400**.

Writing the report never blocks a publish. If it fails, the version is still published, and the
failure is recorded in the workflow audit as `schema.change_report.generated` with outcome
`failure`.

## Preview, read and edit a report

| Step | REST call |
| --- | --- |
| Preview the report a publish would write, without saving it | `POST /v1/versions/{tenant}/{project}/{version}/change-report/publish-preview` |
| Publish (the report is written straight after) | `POST /v1/versions/{tenant}/{project}/{version}/publish` |
| Read the stored report | `GET …/change-report` |
| Edit the header, body or footnote | `PATCH …/change-report` |
| Render it again from the stored comparison | `POST …/change-report/regenerate` |

- **Edits are layered over the generated text.** A `PATCH` sends the full new text of each part you
  change (`editedHeaderSnapshot`, `editedRenderedBody`, `editedFootnoteSnapshot`); `null` removes one
  edit and `clearEdits: true` removes them all. `GET` returns the generated text, your edits, and the
  `effective…` text readers see.
- **Regenerating** renders the stored comparison again, optionally with another `templateVersionId`.
  It discards your edits unless you send `discardUserEdits: false`.
- Editing and regenerating need a signed-in user (not an API key) who created the version or is a
  tenant administrator.

The full request and response shapes are in the
[Version change report](../reference/rest/version-change-report.md) REST reference. To compare two
OpenAPI documents of your own without publishing, call `POST /v1/openapi/change-report` — see
[OpenAPI change report](../reference/rest/openapi-change-report.md).

## Templates

The header, body and footnote are [Mustache](https://mustache.github.io/) templates. The template
used is, first to last:

1. the `templateVersionId` sent with a regenerate,
2. the **project's** default template,
3. the **tenant's** default template,
4. the built-in system template **1.0.0**.

A template is created once per tenant with a `semver` and three parts
(`POST /v1/tenants/{tenant}/change-report-template-versions`) and cannot be changed afterwards — to
change the wording, create a new version. A second template with the same `semver` is refused with
**409**, and a template that does not render is refused with **400**. Tenant administrators set the
tenant default; the project's creator or a tenant administrator sets the project default.

Templates can use `productName`, `fromVersionLabel`, `toVersionLabel` and `publishTimestamp`; the
counts `schemaCounts.added` / `.removed` / `.modified`, `propertyCount`, `referenceCount`,
`relationshipCount`, `documentationCount`, `warningCount` and `skippedCount`; the lists `schemas`,
`properties`, `references`, `relationships`, `documentation`, `warnings` and `skipped`; and the
switches `schemaSection`, `propertiesSection` and so on, which are true when that list has entries.
See the [Change report templates](../reference/rest/change-report-templates.md) REST reference.

## Review, approve and export

A report starts as a **Draft**. It can be submitted for review, approved or rejected by a tenant
administrator, and, once **Approved**, downloaded as a PDF. Editing or regenerating it returns it to
**Draft**. Every edit, regeneration, review step and export is kept in an append-only audit log. The
steps are in [Review, approve and export a change report](../build/versions.mdx#review-approve-and-export-a-change-report)
and the log in the [Change report audit](../reference/rest/change-report-audit.md) REST reference.
These belong to the **Enterprise change reports** entitlement — see
[Feature flags](../admin/feature-flags.mdx).

## In the app

The [**Change report** tab](../build/versions.mdx#change-report-) on **Versions** shows the report
for a **Published revision**, with editing, regenerating, templates and review. It is behind
`FEATURE_GITLIKE`, which is off in shipped builds, so until it is switched on use the REST calls
above.

## Related

- [Publish a version](./publish-a-version.md) — the publish that writes the report
- [Compare published versions](./compare-published-versions.md) — the raw differences
- [Versions](../build/versions.mdx#change-report-) — the **Change report** tab
