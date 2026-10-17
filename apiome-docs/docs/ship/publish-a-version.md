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
- there are no un-acknowledged breaking changes.

You choose a **visibility** when publishing: `public` (anyone can browse it) or `private` (only
in-scope API keys can reach it).

---

## In the UI

1. Open **Versions** at `/ade/dashboard/versions` and select the version.
2. Choose **Publish**, pick **public** or **private**, and add a revision note.
3. If a gate fails, the UI reports which one — fix it (usually a missing description or an
   unacknowledged breaking change) and publish again.
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
