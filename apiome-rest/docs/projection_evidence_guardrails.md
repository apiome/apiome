# Projection evidence guardrails (EFP-3.2, #4817)

Operational budgets, privacy policy, telemetry, and release gates for the
export projection evidence surface (`POST /v1/export/{tenant}/projection-evidence`
and the Export Studio graph/table).

## Budgets

| Budget | Constant | Value |
|--------|----------|-------|
| Soft evidence-build wall clock (CI) | `EVIDENCE_BUILD_SOFT_BUDGET_SECONDS` | 2.0 s |
| Default evidence page size | `DEFAULT_EVIDENCE_PAGE_SIZE` | 50 |
| Max evidence page size | `MAX_EVIDENCE_PAGE_SIZE` | 500 |
| Manifest cache TTL | `MANIFEST_CACHE_TTL_SECONDS` | 60 s |
| Manifest cache capacity | `MANIFEST_CACHE_MAX_ENTRIES` | 64 |
| UI aggregation threshold | `GRAPH_AGGREGATION_THRESHOLD` / `UI_AGGREGATION_THRESHOLD_ROWS` | 48 |
| UI page size per request | `EVIDENCE_PAGE_LIMIT` | 200 |
| UI pages per auto-load window | `EVIDENCE_PAGES_PER_WINDOW` | 5 |
| Soft UI `buildProjectionView` budget (CI) | Jest soft assert | 100 ms |

**Initial UI render** is bounded by: snapshot summary chips (full status counts) +
the first fetch window (`EVIDENCE_PAGE_LIMIT × EVIDENCE_PAGES_PER_WINDOW` rows) +
deterministic aggregation once row count exceeds 48. Users continue with
**Load more evidence**; dropped / unavailable / critical rows are never aggregated away.

Constants live in:

* `apiome-rest/src/app/export_projection.py`
* `apiome-rest/src/app/projection_manifest_cache.py`
* `apiome-ui/.../useProjectionEvidence.ts`
* `apiome-ui/.../projectionGraph.ts`

## Cache keys

Manifests (not pages) are cached in-process under:

`(tenant_id, artifact_id, version_record_id, target, options_digest, emitter_version, registry_version, apiome_version)`

Keys are tenant-scoped; TTL eviction plus LRU capacity bounds memory.

## Redaction policy (always on)

Every evidence response redacts source-native fields:

* `native_id`, `source_location`, `native_name` → `[redacted]` when present
* Edge `detail` / `explanation` / `target_mapping` substrings that echo those
  captured native values are replaced with `[redacted]`

Construct keys, statuses, reason categories, and target locations remain.
`redact_source` on the request is **ignored** for compatibility; `redacted` is
always `true`.

## Privacy-safe telemetry

Structured events (`event=export.projection`) and in-process counters via
`app.projection_telemetry`. Allowed kinds:

* `preview_failure` (+ `reason_category`)
* `stale_acknowledgement`
* `evidence_page` (+ `page_total`, `latency_ms`, count maps, `large_manifest`)
* `aggregation_used` (UI → `POST …/projection-metrics`)
* `documentation_link_available` / `documentation_link_missing`

Never: construct labels, native ids, source text, artifact names.

## Release gates (CI)

Run as part of the existing package CI workflows (no separate k6 pipeline):

1. **apiome-rest** — `pytest` including
   `tests/test_export_projection_evidence_routes.py` and
   `tests/test_projection_telemetry.py` (always-on redaction, soft build budget,
   cache tenant isolation, stale-ack / evidence telemetry privacy).
2. **apiome-ui** — `yarn test` including projection guardrail Jest coverage
   (aggregation soft budget, reduced-motion / high-contrast, metric whitelist).

Load testing for this surface is the soft wall-clock pytest budget above, not an
external load-tool harness.
