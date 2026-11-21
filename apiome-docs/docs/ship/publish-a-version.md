---
title: "Publish a version"
description: "Freeze a version and make it available to browse, export and MCP."
sidebar_position: 3
tags: [versions, publish]
---

Publishing freezes a version and makes it available to **browse**, **export**, and **MCP** consumers.
Publishing enforces server-side **publish gates** — it will refuse a version that does not meet them.

**Publish gates:**

- the reconstructed document is valid OpenAPI,
- every class is documented (has a description),
- there are no un-acknowledged breaking changes,
- when the style guide has a [maturity ladder](../govern/maturity-ladders.mdx#gate-publishing-on-a-level)
  and a **required publish level**, the version has reached that level — otherwise publish is
  refused with the level reached, the level required and what blocks the next level
  (see [The maturity level gate](#the-maturity-level-gate)),
- when the workspace **requires an owner to publish**, the project has a confirmed
  [owner team](../workspace/teams.mdx#ownership) — otherwise publish is refused with reason
  `no-owner` (the `422` carries `reason: "no-owner"` and an `ownerGate` object).

You choose a **visibility** when publishing: `public` (anyone can browse it) or `private` (only
in-scope API keys can reach it).

---

## In the UI

1. Open **Versions** at `/ade/dashboard/versions` and select the version.
2. Choose **Publish**, pick **public** or **private**, and add a revision note. **Publish** is shown
   only to a role that can publish (an **Editor** can't), and only to the version's creator or a
   workspace administrator; it never appears on a catalog item.
3. If a gate fails, the UI reports which one — fix it (usually a missing description or an
   unacknowledged breaking change) and publish again. The **Owner team** card under **Publish
   gates** always says where the owner gate stands: **Off** (publishing does not require an owner),
   **Met** (it names the owner team) or **Blocked** — [assign or confirm an owner](../workspace/teams.mdx#confirm-or-assign-an-owner)
   on the project, or force-publish with a reason.
4. Published versions are listed on [Published](./published.mdx) (`/ade/dashboard/published`).

## With the REST API

```http
POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/publish
X-API-Key: <your-api-key>

{ "visibility": "public", "notes": "First public cut." }
```

Returns the version with `published = true`. To reverse it, see [Unpublish a version](#unpublish-a-version).

Straight after the publish, Apiome writes a change report comparing this version with the previous
published one. `changeReportBaselineMode` (`auto`, `initial` or `manual`) chooses what it is compared
with — see [Publication change reports](./publication-change-reports.md).

## The maturity level gate

A style guide with a maturity ladder can set `requiredPublishLevel`, the level a version must reach
before it publishes (for example `silver`). The gate runs after the style-guide error check and
before the approval check. A guide without a ladder, or without a required level, never arms it.

A version below the required level is refused with `422`. `detail.maturityGate` says what to fix:

```json
{
  "detail": {
    "message": "This version is at Bronze; Silver is required (1 blocker to the next level). Clear the blockers, lower the guide's required publish level, or force-publish with a reason.",
    "maturityGate": {
      "status": "blocked",
      "blocked": true,
      "ladderName": "Payments maturity",
      "level": "bronze", "levelLabel": "Bronze",
      "requiredLevel": "silver", "requiredLevelLabel": "Silver",
      "blockers": [
        {"levelKey": "silver", "kind": "axis", "axis": "quality", "minGrade": "B",
         "reason": "below_threshold", "grade": "C", "score": 74, "count": 1, "sample": []}
      ],
      "reason": "maturity-below-required-level",
      "policyVersionId": "…", "evaluationId": "…"
    }
  }
}
```

`blockers` are the blockers of the version's **next** level, the same list
[`GET …/lint/level`](../govern/maturity-ladders.mdx#read-a-level) returns.

To publish anyway, **force-publish**: send `"skipPublishChecks": true` with a `forcePublishReason`.
Every publish the gate judges is written to the version's audit trail as `version.maturity_gate`,
with `action` set to:

| `action` | When |
| --- | --- |
| `satisfied` | The version reached the required level. |
| `forced` | A force-publish went past the gate. The row carries the reason and the level. |
| `unavailable` | The level could not be read. The publish went ahead. |

The gate never blocks on its own fault. When the level cannot be read, the publish goes ahead and
the audit row says `unavailable`.

## Unpublish a version

Unpublishing returns a published version to **draft** — for a bad release, a publish to the wrong
workspace, or a security regression. Only the version's creator or a tenant administrator can do it. Unpublishing:

- **hides** the version from `/v1/schema`, `/v1/swagger`, `/v1/arazzo` and `/v1/json`;
- **moves its version tags** (such as `latest`) back to the project's next-most-recent published
  version. Immutable tags, protected tags (unless you are a tenant administrator) and tags with no
  other published version to go to stay where they are;
- **notifies webhook subscribers** with a `version.unpublished` event;
- **records the reason**, when, and who — `apiome versions get` shows them.

### With the CLI

```bash
apiome versions unpublish payments-api v2.1.0 --reason 'Security regression in /charges'
# Unpublishing will:
#   • Hide 2.1.0 from /v1/schema, /v1/swagger, /v1/arazzo, /v1/json
#   • Move the 'latest' tag back to 2.0.0 (next-most-recent published)
#   • Notify webhook subscribers (3 active)
#   • Record the reason: Security regression in /charges
# Type the version to confirm (2.1.0): 2.1.0
# ✔ Unpublished 2.1.0.
```

1. **Run** `apiome versions unpublish <project> <version> --reason '…'`. The version can be a label
   (`2.1.0` or `v2.1.0`) or a revision id. `--reason` is required.
2. **Read** the preview — it comes from the server, so it is exactly what will happen.
3. **Type the version** as shown to confirm. In a script, pass `--yes` instead.

| Option | What it does |
| --- | --- |
| `--reason <text>` | Recorded for audit and sent to webhook subscribers. Required unless `--silent`. |
| `--keep-tags` | Leave the version tags on the unpublished version. |
| `--silent` | Do not notify webhook subscribers. Tenant administrators only. |
| `--force` | Unpublish the project's **only** published version. Without it the command refuses and exits `6`. |
| `--yes` | Skip the typed confirmation. |

With `--json` it prints the unpublished version, with `tagsMoved`, `tagsKept` and `unpublishReason`.
The older form `apiome versions unpublish <version> --project <project>` still works.

### With the REST API

```http
POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/unpublish
X-API-Key: <your-api-key>

{ "reason": "Security regression", "keepTags": false, "silent": false, "dryRun": false }
```

Every field is optional; an empty body unpublishes, moves the tags and notifies subscribers.
`dryRun: true` returns the plan (`tagsMoved`, `tagsKept`, `webhookSubscribers`,
`publishedVersionsRemaining`) without changing anything. `silent: true` from someone who is not a
tenant administrator is refused with `403` `silent_requires_admin`.

## Freeze a version's schema

`GET /v1/schema/{tenant}/{project}/{version}` normally serves the OpenAPI document of the
version's **current** classes, properties and paths, so editing a published version changes what
consumers download. **Freezing** stores the document byte-for-byte; while a version is frozen,
`/v1/schema` serves exactly those bytes — the right thing to point an SDK generator at. Only a
**published** version can be frozen, by its creator or a tenant administrator.

Apiome generates the document when you publish and keeps it in the
[document store](../admin/document-store.mdx#rendered-documents). It generates a new one only after
the version changes. Every `/v1/schema` response has an `ETag` header, the SHA-256 of the document
in double quotes. Send it back in `If-None-Match` to get `304 Not Modified` when nothing changed.

### With the CLI

```bash
apiome versions freeze payments-api v2.1.0
# Schema snapshot for 2.1.0:
#   Classes:    24
#   Properties: 142
#   Paths:      18
#   SHA-256:    7f2c…a041
#   Size:       128.3 KiB
#
# After freeze, edits to 2.1.0's classes, properties and paths will NOT alter the
# published schema at /v1/schema/acme/payments-api/2.1.0.
# Continue? [y/N]: y
# ✔ Frozen. Snapshot stored at /v1/schema/acme/payments-api/2.1.0 (SHA-256 7f2c…a041)
```

1. **Run** `apiome versions freeze <project> <version>`. The summary comes from the server, so the
   SHA-256 is the one consumers will see.
2. **Answer `y`** to freeze, or pass `--yes` in a script.
3. **Verify** a download: the response carries the SHA-256 in the `X-Apiome-Snapshot-Sha256` header
   and, in double quotes, in the `ETag` header.

With `--json` the command prints `{ "frozen": true, "sha256": "…", "size_bytes": …, "snapshot_url": "…" }`
plus the counts.

**Unfreeze** with `apiome versions freeze <project> <version> --unfreeze`. Every fetch of the
frozen `/v1/schema` URL is counted; once anyone has downloaded the snapshot, unfreezing is refused
(exit `6`) because a consumer may depend on its bytes. A tenant administrator can still unfreeze
with `--force-unfreeze`. After an unfreeze, `/v1/schema` serves the document of the version's
current classes again. A request that sends a matching `If-None-Match` gets `304` and is not
counted as a download.

Only the version document at `/v1/schema/{tenant}/{project}/{version}` is frozen. Per-class
documents, Swagger UI, `/v1/json` and `/v1/arazzo` are still generated live.

### With the REST API

| Request | What it does |
| --- | --- |
| `POST …/{version_record_id}/freeze-schema` | Freezes; body `{ "dryRun": true }` returns the snapshot without storing it. `409 version_not_published` for a draft, `409 already_frozen` when already frozen. |
| `GET …/{version_record_id}/freeze-schema` | `frozen`, `sha256`, `sizeBytes`, `snapshotUrl`, counts and `downloadCount`. |
| `DELETE …/{version_record_id}/freeze-schema` | Unfreezes. `409 snapshot_downloaded` once downloaded, unless `?force=true` (tenant administrators only; otherwise `403 force_unfreeze_requires_admin`). |

## Tip: lint before you publish

Run [Lint and check quality](../build/lint-and-quality.md) first — clearing its findings clears most publish-gate
failures before you hit them.

## Verify

- **Browse:** `GET /v1/browse/tenants/{tenant}/projects/{project}/versions` lists the published
  version — see [Browse published specs](./browse-published-specs.md).
- **Export:** the version's OpenAPI is now reconstructable — see [Export a spec](./export-a-spec.md).
- **MCP:** a published *public* spec shows up via `spec.list` — see [MCP quick-start](../reference/mcp-quickstart.md).

## Related

- [Cut a version](./cut-a-version.md) — the version you publish
- [Browse published specs](./browse-published-specs.md) — where it lands
- [Publication change reports](./publication-change-reports.md) — the report each publish writes
