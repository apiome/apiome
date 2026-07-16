# Publish-event webhooks (`version.published`)

CTG-3.3 (#4477). When a version is published, Apiome fans a `version.published`
event out to the tenant's push-webhook subscriptions (#2587/#2588), embedding
the classified changelog persisted at publish time by CTG-3.1 (#4475). Delivery,
signing, retry, and dead-letter semantics are the standard push-webhook ones —
this document covers only the publish event's payload and its severity filter.

## Delivery pipeline

```
publish ──► version_changelogs row (CTG-3.1) ──► version.published payload
        ──► one delivery per active subscription whose min_severity is met
        ──► HMAC-signed POST, 4 attempts with backoff, then dead-letter
```

The fan-out runs as a background task *after* the changelog classification task,
so the payload reflects the persisted `version_changelogs` row. Fan-out is
best-effort: a notification problem never fails the publish itself.

Headers are the standard push-webhook ones:

| Header | Value |
|---|---|
| `X-Apiome-Event` | `version.published` |
| `X-Apiome-Signature` | `sha256=<hex HMAC of the raw body, keyed by the subscription's signing secret>` |

## Payload schema

```json
{
  "event": "version.published",
  "projectId": "8b0c…",
  "versionId": "44f2…",
  "versionLabel": "2.0.0",
  "publishedBy": "user-a",
  "maxSeverity": "breaking",
  "changelog": {
    "schemaVersion": "ctg.changelog.v1",
    "status": "ready",
    "fromVersion": "1.4.0",
    "toVersion": "2.0.0",
    "counts": { "breaking": 2, "non-breaking": 5, "docs-only": 1, "unclassified": 0, "total": 8 },
    "maxSeverity": "breaking",
    "topChanges": [
      {
        "severity": "breaking",
        "ruleId": "ctg.path.removed",
        "path": "/paths/~1pets",
        "pointer": "/paths/~1pets",
        "summary": "Path removed"
      }
    ],
    "totalChanges": 8,
    "topChangesTruncated": false
  }
}
```

| Field | Presence | Meaning |
|---|---|---|
| `event` | always | `version.published`. |
| `projectId` / `versionId` | always | The catalog project and the published revision record id. |
| `versionLabel` | when known | Human version label (e.g. `2.0.0`). |
| `publishedBy` | when known | Id of the publishing user. |
| `maxSeverity` | always | Mirror of `changelog.maxSeverity` for cheap routing; `null` when there is nothing classified. |
| `changelog.status` | always | `ready` (classified), `initial` (first publish on the line, no baseline), `failed` (classification errored), or `unavailable` (no stored row). |
| `changelog.counts` | always | Per-severity tallies from `ctg.changelog.v1` (empty object when unavailable). |
| `changelog.topChanges` | always | Up to 10 entries, most severe first (the stored changelog's deterministic order); each carries `severity`, `ruleId`, `path` (the entry's path group), `pointer`, and `summary`. |
| `changelog.totalChanges` / `topChangesTruncated` | always | Full entry count, and whether `topChanges` is a truncated slice. Fetch the complete changelog via `GET /v1/versions/{tenant}/{project}/{revision}/changelog` when truncated. |
| `changelog.schemaVersion` / `fromVersion` / `toVersion` / `initialPublication` | when stored | Copied from the persisted `ctg.changelog.v1` JSON when present. |

## `minSeverity` subscription filter

Subscriptions (`/v1/push-webhook-subscriptions/{tenant}`) accept an optional
`minSeverity` field on create and update: `"docs-only"`, `"non-breaking"`,
`"breaking"`, or `null` (default — no filter). On PATCH the field is tri-state:
omit it to leave the filter unchanged, pass an explicit `null` to clear it.

A `version.published` event is delivered to a filtered subscription only when
the publish's classified max severity **meets the threshold**
(`docs-only` < `non-breaking` < `breaking`):

| Changelog state | Unfiltered | `docs-only` | `non-breaking` | `breaking` |
|---|---|---|---|---|
| `ready`, max severity `breaking` | ✓ | ✓ | ✓ | ✓ |
| `ready`, max severity `non-breaking` | ✓ | ✓ | ✓ | — |
| `ready`, max severity `docs-only` | ✓ | ✓ | — | — |
| `ready` with no changes, or `initial` | ✓ | — | — | — |
| `failed` or no stored row | ✓ | ✓ | ✓ | ✓ |

The last row is the fail-safe: when classification failed or never ran, the
publish cannot be proven below the threshold, so it is delivered (mirroring the
change taxonomy's unclassified→breaking fail-safe). An initial publication or an
empty changelog has no changes to meet any threshold, so filtered subscriptions
stay quiet.

`minSeverity` applies **only** to `version.published` events. The other webhook
event families (`repository.refresh.*`, `lint.*`, `mcp.*`) are delivered to
every active subscription regardless of the filter.

## Backwards compatibility

Pre-#4477 subscriptions have `min_severity = NULL` and continue to receive
every publish event; no payload field was removed from any existing event type.
Migration: `apiome-db/scripts/V179__push_webhook_min_severity_4477.sql`.

## Implementation map

| Concern | Where |
|---|---|
| Payload builder + fan-out | `src/app/publish_notifications.py` |
| Severity ranking | `changelog_generator.severity_rank` |
| Subscription filter column | `push_webhook_subscriptions.min_severity` (V179) |
| Publish wiring | `versions_routes.py` publish route (background task after the CTG-3.1 changelog task) |
| Delivery/retry/DLQ | `src/app/push_webhook_delivery.py` (unchanged) |
