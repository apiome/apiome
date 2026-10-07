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
4. Published versions are listed under `/ade/dashboard/published`.

## With the REST API

```http
POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/publish
X-API-Key: <your-api-key>

{ "visibility": "public", "notes": "First public cut." }
```

Returns the version with `published = true`. To reverse it:

```http
POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/unpublish
```

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
