---
title: "What an import records"
description: "The format, protocol, toolchain and source details stored with every imported version."
sidebar_position: 1.13
tags: [catalog, import]
---

Every import stores more than the API itself. With each new version, Apiome records **what kind
of source it was** and **how it was read**, so the version can be filtered by format, traced back to
its source, converted, re-imported or refreshed later — whatever format it came in.

## What is recorded

| Record | What it holds | Example |
| --- | --- | --- |
| **Format** | The exact source format the importer recognized | `openapi-3.1`, `swagger-2.0`, `protobuf`, `graphql`, `asyncapi-3`, `avro` |
| **Protocol** | The kind of API: `rest`, `rpc`, `event`, `graph`, `data_schema` or `agent` | `rpc` for a `.proto` file |
| **Tool versions** | The toolchain that parsed the source into Apiome's model | One entry per tool, with its version |
| **Format metadata** | What the import knew about the source beyond the model | See below |

Format and protocol are what the [Catalog's filters](./find-apis-across-formats.md), search
across formats and the browse app's **Paradigm** and **Format** chips read.

### Format metadata

Format metadata is one open record per version. Each importer adds what its format needs, so a new
format never needs a database change. It can hold:

- **Where the source came from** — its name or URL, how it arrived (file, URL, pasted, git,
  connector, live discovery) and, for a repository or connector, the commit or remote revision.
- **Why it landed where it did** — the routing reason the **Provenance** tab shows.
- **The source's fingerprint** and, where the source was kept, the **source document itself**, which
  [conversion](./convert-to-openapi.md) and export read back. A source that held credentials is
  withheld instead, and the record says so.
- **What the secret scrub removed** — the kinds and places of redacted values, never the values
  ([Secrets in collections and captures](./collection-secret-scrubbing.md)).
- **The import settings** of an uploaded file, so a **Re-upload…** replays them.
- **Format-specific details**, such as an EDI dialect profile, FIX message types, a z/OS Connect
  binding or the REST hypermedia conventions a source declares.

## Where you see it

On a catalog item's **Provenance** tab, the four import steps show the records:

| Step | Shows | When nothing was recorded |
| --- | --- | --- |
| **Source intake** | Where the imported document came from | *Not recorded* |
| **Format detection** | The format and protocol, as pills | *No detected format or protocol was recorded.* |
| **Normalization** | A chip per tool and its version | *Tool versions were not recorded for this import.* |
| **Catalog record** | The import job that created the item, and who ran it when | *Not recorded* |

Beside them, **Toolchain & routing** shows the **Fingerprint**, **Publishable**, **Secret scrub**
and **Routing**. See [Catalog](./catalog.mdx) for the whole item page.

<Screenshot id="catalog-item-provenance" alt="The Provenance tab: the four import steps on the left, and Fingerprint, Publishable false and the routing reason on the right" />

Over the REST API, a catalog item carries its latest revision's `sourceFormat`, `protocol`,
`formatMetadata` and `toolVersions`; see the [Catalog REST reference](/reference/rest/catalog).

## Versions from before these records

Versions that existed before Apiome recorded format and protocol were tagged once, so every
filter finds them too:

| Older version | Format | Protocol |
| --- | --- | --- |
| Its source was kept when it was imported | The imported format (`openapi-3.1`, `swagger-2.0`, `asyncapi-3`, …) | That format's protocol |
| An Arazzo file imported from a repository | `arazzo` | `rest` |
| Any other version (built in the designer, the `petstore-sample` project, older OpenAPI imports) | `openapi` | `rest` |

Only empty values were filled; nothing an import had recorded was changed. Tool versions and format
metadata were not backfilled, so an older item's **Normalization** step reads *Tool versions were not
recorded for this import.*

## Related

- [Find APIs across formats](./find-apis-across-formats.md) — filter and search by format and protocol
- [Catalog](./catalog.mdx) — the item page and its **Provenance** tab
- [Supported formats](./supported-formats.md) — every format and its protocol
- [Read a catalog item's format details](./catalog-format-details.md) — the native structure of a payload
