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
- when the workspace **requires an owner to publish**, the project has a confirmed
  [owner team](../reference/rest/owners.md) — otherwise publish is refused with reason
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
   unacknowledged breaking change) and publish again. When the owner gate would refuse the publish,
   an **Owner team** card under **Publish gates** says **Blocked** — give the project a confirmed
   owner over the [REST API](../reference/rest/owners.md), or force-publish with a reason.
4. Published versions are listed on [Published](./published.mdx) (`/ade/dashboard/published`).

## With the REST API

```http
POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/publish
X-API-Key: <your-api-key>

{ "visibility": "public", "notes": "First public cut." }
```

Returns the version with `published = true`. To reverse it, see [Unpublish a version](#unpublish-a-version).

## Unpublish a version

Unpublishing returns a published version to **draft** — for a bad release, a publish to the wrong
workspace, or a security regression. Only the version's creator or a tenant administrator can do it,
and a version that already has data records cannot be unpublished. Unpublishing:

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

`GET /v1/schema/{tenant}/{project}/{version}` normally builds the OpenAPI document from the
version's **current** classes, properties and paths, so editing a published version changes what
consumers download. **Freezing** stores the document byte-for-byte; while a version is frozen,
`/v1/schema` serves exactly those bytes — the right thing to point an SDK generator at. Only a
**published** version can be frozen, by its creator or a tenant administrator.

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
3. **Verify** a download: the response carries the SHA-256 in the `X-Apiome-Snapshot-Sha256` header.

With `--json` the command prints `{ "frozen": true, "sha256": "…", "size_bytes": …, "snapshot_url": "…" }`
plus the counts.

**Unfreeze** with `apiome versions freeze <project> <version> --unfreeze`. Every fetch of the
frozen `/v1/schema` URL is counted; once anyone has downloaded the snapshot, unfreezing is refused
(exit `6`) because a consumer may depend on its bytes. A tenant administrator can still unfreeze
with `--force-unfreeze`. After an unfreeze, `/v1/schema` is generated from the version's current
classes again.

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
