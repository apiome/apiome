# Opt-in SDK compatibility beacon (RDG-1.7 / SGD-3.1, #4736)

Generated SDKs can, **only when their user turns it on**, report per-operation outcome counts so the API owner
sees which published releases real SDK users find incompatible.

## Contract — `apiome.sdk.beacon/v1` (`app/sdk_beacon.py`)

```json
{"schema": "apiome.sdk.beacon/v1", "source_id": "<sdk_beacon usage source>",
 "events": [{"sdk_name": "pets-go", "sdk_version": "1.4.0", "api_version": "1.2.0",
             "spec_revision_id": "<versions.id>", "operation_id": "getPet",
             "outcome": "incompatible", "count": 3}]}
```

- Outcomes: `ok`, `client_error` (4xx), `server_error` (5xx), `network` (no response), `incompatible` (a 2xx the SDK
  could not decode against the contract).
- Strict: unknown keys refused; every string pattern-checked (mirrors the V380 CHECKs); 1–500 events, counts 1–10,000.
- No body, header, status, latency, URL, host, credential, caller identifier or timestamp — the server counts on its
  receive day.

## Endpoints (`app/sdk_beacon_routes.py`, tag `usage`)

| Route | Notes |
|---|---|
| `POST /v1/tenants/{t}/usage/sdk-beacon` | `usage:ingest` key (allowlisted in `auth._API_KEY_SCOPE_ALLOWLIST`); session → 403. Source via `X-Apiome-Usage-Source` or `source_id`; must be enabled (`403`) and of kind `sdk_beacon` (`409`). Events on a revision that is not published in the source's project → `rejected[{index, reason: revision-unknown}]`. `202 {accepted, calls, rejected}`. |
| `GET /v1/tenants/{t}/usage/sdk-beacons?project=&days=` | `consumer_contracts:view`. Grouped by `spec_revision_id, api_version, sdk_name, sdk_version, operation_id, outcome` — the SDK kit manifest's keys (`provenance.version_record_id`, `operations[].operation_id`). |

Why not `/usage/ingest`: usage events need a real status and latency (`usage_hourly`); a beacon has neither, and a
`network` outcome has no status at all. The beacon reuses the usage source (its `enabled` flag is the off switch),
the `usage:ingest` key scope, and the rollup retention.

## Storage and retention

apiome-db **V380** `usage_sdk_beacon_daily` (daily counters, PK over every dimension) and
`purge_usage_sdk_beacons(now, batch)`, called by `app.usage_sweep` on `usage_retention().rollup_cutoff`.

## Generated Go client (`app/go_client_telemetry.py`)

`telemetry.go` in the SDK kit's Go module: `WithTelemetry(TelemetryConfig{Endpoint, APIKey, SourceID, SDKVersion,
HTTPClient, FlushEvery})` — **off unless passed**, and off when the config is incomplete or the module was generated
outside a kit (`ManifestRevisionID == ""`). `Client.do(req, out, operationID)` classifies each call (the operation id is the manifest's, or its key / a sanitised form when it would not pass the endpoint pattern — `beacon_operation_id`); counts flush in
the background every `FlushEvery` (100) calls and on `FlushTelemetry(ctx)`, through the beacon's own HTTP client with
only `Content-Type` and `X-API-Key` headers. Failures are dropped. Tests: `tests/test_go_client_telemetry.py`
(template assertions everywhere; `go test` over real HTTP when a Go toolchain is on `PATH`).
