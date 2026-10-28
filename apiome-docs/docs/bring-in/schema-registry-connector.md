---
title: "Mirror a schema registry"
description: "Sync a Confluent-compatible schema registry's subjects into the catalog, within a crawl budget."
sidebar_position: 14.5
tags: [import, schema registry, confluent, karapace, apicurio, kafka, connector]
---

A **schema registry connector** keeps a copy of a Confluent-compatible schema registry in Apiome:
Confluent Platform or Cloud, Karapace, or Apicurio Registry's compatibility API
(`https://<apicurio>/apis/ccompat/v7`). Each upstream subject becomes a subject in Apiome's
[schema registry](../reference/rest/schema-registry.md) and a catalog item with one revision per
upstream version. The connector only reads. It never writes to the upstream registry.

A registry can hold thousands of subjects. Each sync works within a **crawl budget** and records
where it stopped. The next sync carries on from there, so a large registry is mirrored over several
syncs without overloading it, and an interrupted sync loses almost nothing.

## Add the connector

```bash
apiome connectors add --kind schema-registry --name "Prod registry" \
  --base-url https://psrc-123.eu-west-1.aws.confluent.cloud \
  --credentials-file creds.json          # {"username": "<API key>", "password": "<secret>"}
```

`{"token": "…"}` sends a bearer token instead. Leave out `--credentials-file` for a registry that
needs none. The connector syncs on the deployment's schedule; `apiome connectors sync <id>` runs one now.

## The crawl budget

A sync stops when it reaches any of these limits. Set them in the connector's scope; every key is
optional.

| Scope key | What it limits | Default | Highest |
| --- | --- | --- | --- |
| `requestsPerSecond` | Requests per second to the registry | 10 | 50 |
| `maxRequests` | Requests in one sync | 5,000 | 100,000 |
| `maxPages` | Pages of 100 subjects listed in one sync | 50 | 2,000 |
| `maxBytes` | Response bytes read in one sync | 500,000,000 | 2,000,000,000 |
| `fullPassHours` | Hours between full passes (see below) | 24 | 720 |

Give the scope when you add the connector (`--scope '{"maxRequests": 2000, "requestsPerSecond": 5}'`),
or change it later with `PATCH /v1/tenants/{tenant}/connectors/{id}` and a `scope` body (see the
[connectors reference](../reference/rest/connectors.md)).

Listing subjects may use at most half the request budget. The other half is kept for mirroring the
subjects it listed, so every sync makes progress.

When a sync reaches its budget it stops cleanly. The run **succeeds**: what it mirrored is kept, the
subjects it did not get to are counted as **deferred**, and the next sync resumes after the last
subject it finished.

## Full and incremental passes

**A full pass** reads the registry's subject list, then each subject's versions and compatibility
level, in name order. A pass over a large registry can take several syncs: each one picks up after
the last subject the previous sync finished. A subject the registry no longer lists becomes
**missing** in the connector's inventory. Its catalog item stays.

**An incremental pass** runs between full passes. Every new schema in a Confluent registry gets a
higher id than the last one. Apiome remembers the highest id it has seen, asks the registry which
subjects use the ids above it, and reads only those subjects. A quiet registry costs about twenty
requests per sync.

An incremental pass sees new schemas and new versions. It does not see deleted versions, deleted
subjects or a changed compatibility level: the next full pass picks those up, after `fullPassHours`
(a day by default).

A registry that does not answer the incremental question, such as Apicurio's compatibility API, gets
full passes only. Apiome tries once, then stops asking.

## If a sync is interrupted

Apiome saves its place after each subject it finishes. If a sync stops part-way, for example because
the server restarted, the next sync starts at the subject it was working on. Subjects it had already
finished are not read again.

## Read a sync's crawl report

Each sync's summary carries a `crawl` block (`apiome connectors runs <id> --format json`):

| Field | Meaning |
| --- | --- |
| `mode` | `full` or `incremental` |
| `requests`, `pages`, `bytes` | What the sync used |
| `budget` | The limits it ran with |
| `exhaustedBy` | `requests` or `bytes` when the sync stopped at its budget, else `null` |
| `pageBudgetReached` | Listing stopped at `maxPages` |
| `listed`, `settled` | Subjects listed, and how many of them the sync finished |
| `partial` | The pass did not finish in this sync |
| `resumesAfter` | The last subject finished in the full pass in progress |
| `watermark` | The highest schema id seen |
| `lastFullPassAt` | When the last full pass finished |
| `fallback` | `probe-unsupported` when an incremental pass became a full one |

## Other registry crawls

[Registry crawl](../reference/rest/connectors.md) connectors (xRegistry, A2A agent registries, FHIR
`/metadata`) accept `requestsPerSecond`, `maxRequests`, `maxPages` and `maxBytes` too. They read
the whole registry on each sync, without a checkpoint.

## Where next

- [Import Avro](./avro-import.md) — what a mirrored Avro schema becomes, and Confluent-style compatibility
- [Import a CNCF xRegistry](./xregistry-import.md) — the registry crawl for CloudEvents catalogs
- [`apiome connectors`](../reference/cli/connectors.md) — add, update, sync and read runs
