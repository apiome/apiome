# Apiome: Gateway (API Gateway) - Feature Roadmap

> A fully managed API gateway that uses Apiome schemas for automatic request/response validation, traffic management, protocol transformation, and developer self-service—turning schema definitions into enforceable runtime contracts.
>
> **Revenue Model**: Request volume pricing, enterprise dedicated gateways
>
> **Tech Stack**: NextJS (app router), Radix UI, PostgreSQL, Redis (caching/rate limiting), OpenAPI 3.1, Envoy/NGINX (proxy layer)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Schema-driven request and response validation against published Apiome schemas with detailed error reporting
- Type coercion and normalization engine that auto-converts compatible types before validation
- Load balancing with weighted round-robin and passive health checks across upstream targets
- Circuit breaker with configurable failure thresholds and half-open recovery
- Basic request/response caching with TTL and cache-key derivation from schema + path
- Developer portal with auto-generated endpoint documentation from Apiome schemas
- API key self-service: create, rotate, revoke keys tied to usage plans
- Usage dashboard showing request counts, latency percentiles, and error rates per consumer

---

## Epic 1: Schema-Driven Request Pipeline

### Summary Table

| #   | Title                                | Description                                                                 | Labels                                  | Parallel |
|-----|--------------------------------------|-----------------------------------------------------------------------------|-----------------------------------------|----------|
| 1.1 (#1055) | Validation Engine Core               | Build the JSON Schema validation engine that enforces published schemas     | `enhancement`, `mvp`, `gateway`, `rest` | Yes      |
| 1.2 (#1056) | Type Coercion & Normalization        | Auto-convert query params, headers, and body fields to expected types       | `enhancement`, `mvp`, `gateway`         | Yes      |
| 1.3 (#1057) | Custom Validation Rules              | Support tenant-defined validation rules beyond JSON Schema                  | `enhancement`, `gateway`, `rest`        | No       |
| 1.4 (#1058) | Response Validation & Contracts      | Validate upstream responses before returning to consumers                   | `enhancement`, `gateway`, `rest`        | No       |
| 1.5 (#1059) | Error Formatting & Problem Details   | RFC 9457 problem-details error responses with field-level paths             | `enhancement`, `mvp`, `gateway`, `rest` | Yes      |

### Detailed Issue Descriptions

---

#### 1.1 (#1055) — Validation Engine Core

The gateway's primary value proposition is that every request hitting an upstream service has already been validated against the published Apiome schema. This issue delivers the core validation engine that loads frozen schema captures and compiles them into fast, reusable validators.

The engine must resolve `$ref` pointers within captured schemas, support JSON Schema draft 2020-12, and cache compiled validators keyed by `(schema_capture_id, class_name)`. On a cache miss the engine fetches the schema from the Apiome REST API (`GET /api/v1/schema-captures/{id}/classes/{className}`) and compiles it. Validation runs synchronously in the request hot-path, so compilation must happen at deploy/warm-up time, not per-request.

A configuration layer lets gateway admins bind a route (method + path pattern) to a specific schema class and version. This binding is stored in PostgreSQL and cached in Redis. When a request arrives, the gateway resolves the binding, selects the compiled validator, and runs it against the parsed body. On failure, the engine collects all errors (not just the first) and hands them to the error formatter (1.5).

```
┌──────────┐     ┌────────────┐     ┌──────────────┐     ┌──────────┐
│  Client   │────▶│  Gateway   │────▶│  Validation  │────▶│ Upstream │
│  Request  │     │  Router    │     │  Engine      │     │ Service  │
└──────────┘     └────────────┘     └──────────────┘     └──────────┘
                       │                    │
                       │  route → schema    │  compiled
                       │  binding lookup    │  validator
                       ▼                    ▼
                 ┌────────────┐     ┌──────────────┐
                 │   Redis    │     │  Schema      │
                 │   Cache    │     │  Capture API │
                 └────────────┘     └──────────────┘
```

**Acceptance Criteria**

- Requests with invalid bodies receive a 422 response with all validation errors listed
- Valid requests pass through to the upstream with zero modification
- Validators are compiled once and cached; a warm validator adds < 5ms p99 latency
- `$ref` resolution works for intra-schema references within the captured version
- Route-to-schema bindings are configurable via REST API (`POST /api/v1/gateway/routes`)
- OpenAPI 3.1 spec for the gateway admin API is published and kept in sync

**Part of Epic: Schema-Driven Request Pipeline**

---

#### 1.2 (#1056) — Type Coercion & Normalization

HTTP transports everything as strings. Query parameters, path parameters, and many header values arrive as text even when the schema declares them as `integer`, `boolean`, or `number`. This issue builds a coercion layer that runs before validation, converting compatible string representations to their declared schema types.

Coercion follows a strict allow-list: `"true"/"false"` → boolean, numeric strings → number/integer, ISO-8601 strings → date-time. Ambiguous or lossy conversions (e.g., `"3.7"` → integer) are rejected rather than silently truncated. The coercion engine reads the target type from the compiled schema and applies transformations in a single pass over the parsed input.

Normalization extends beyond type coercion to include trimming whitespace from string fields, normalizing Unicode to NFC, and lower-casing enum values when the schema specifies case-insensitive matching. These behaviors are opt-in per route via the gateway configuration. All coercions are logged at debug level for troubleshooting.

The coercion pipeline integrates as a middleware step between request parsing and the validation engine (1.1). It modifies the in-memory representation only; the raw request body is preserved for audit purposes.

**Acceptance Criteria**

- Query param `?count=5` is coerced to integer `5` when schema declares `type: integer`
- String `"true"` in a JSON body coerces to boolean `true` for `type: boolean` fields
- Lossy conversions (e.g., float string to integer) return a 422 with a clear error message
- Coercion behaviors are toggleable per route via `PUT /api/v1/gateway/routes/{id}/coercion`
- Unicode normalization to NFC is applied when enabled
- Coerced values are what the upstream service receives; raw values are preserved in audit logs

**Part of Epic: Schema-Driven Request Pipeline**

---

#### 1.3 (#1057) — Custom Validation Rules

JSON Schema covers structural and type validation, but tenants often need domain-specific rules: cross-field constraints ("if `country` is US, `state` must be a valid US state code"), conditional required fields, or business-logic guards ("discount cannot exceed 50%"). This issue adds a custom rule engine on top of the schema validator.

Rules are defined as JSON expressions using a restricted DSL (no arbitrary code execution). Each rule specifies a condition (JSONPath expression), an operator (eq, gt, lt, in, matches, exists), and an expected value or cross-reference. Rules are stored per route binding and evaluated after schema validation passes. They produce the same structured error format as schema validation failures.

The rule engine is exposed via a NextJS admin page at `/gateway/routes/[routeId]/rules` using Radix UI `Table`, `Dialog` for rule creation, and `Select` for operator dropdowns. The REST API exposes `POST /api/v1/gateway/routes/{routeId}/rules` and `GET /api/v1/gateway/routes/{routeId}/rules` endpoints conforming to OpenAPI 3.1.

Rules support ordering (priority) so that expensive cross-field checks can be placed last. A dry-run mode evaluates rules against a sample payload without blocking traffic, allowing tenants to validate new rules before enforcement.

**Acceptance Criteria**

- Tenants can create, update, delete, and reorder custom rules via REST API and UI
- Cross-field rules (e.g., "if A then B required") evaluate correctly
- Rule violations produce RFC 9457 error responses with the rule ID and human-readable message
- Dry-run mode evaluates rules against a provided payload and returns pass/fail without affecting live traffic
- Rules are scoped per route binding and tenant; no cross-tenant leakage
- The admin UI (`/gateway/routes/[routeId]/rules`) uses Radix `Dialog`, `Table`, and `Select` components

**Part of Epic: Schema-Driven Request Pipeline**

---

#### 1.4 (#1058) — Response Validation & Contracts

Validation should not be one-directional. When a gateway promises consumers a certain response shape, it must enforce that contract on upstream services too. This issue adds an optional response validation step that checks upstream responses against the schema's response definitions before forwarding to the consumer.

When response validation is enabled for a route, the gateway deserializes the upstream response body and validates it against the schema class declared for that route's response. If validation fails, the gateway can be configured to: (a) return a 502 Bad Gateway with a generic error, (b) log the violation and pass through anyway (shadow mode), or (c) attempt to strip unexpected fields and pass a sanitized response.

Shadow mode is critical for rollout. Teams enable response validation in shadow mode first, review violation logs in the gateway dashboard, then switch to enforcement once upstreams are compliant. Violation events are emitted to the gateway's event stream for integration with alerting systems.

The response validation configuration is per-route, set via `PUT /api/v1/gateway/routes/{id}/response-validation` with fields for `mode` (enforce | shadow | strip) and `schemaClassId`.

**Acceptance Criteria**

- Upstream responses violating the declared schema are caught and logged
- Shadow mode logs violations without blocking the response to the consumer
- Enforce mode returns 502 with a problem-details body when upstream response is invalid
- Strip mode removes unexpected fields and passes through the sanitized response
- Response validation can be enabled/disabled per route independently of request validation
- Violation events include the route ID, upstream URL, timestamp, and a summary of failed checks

**Part of Epic: Schema-Driven Request Pipeline**

---

#### 1.5 (#1059) — Error Formatting & Problem Details

Every validation failure, coercion error, or custom rule violation must produce a consistent, machine-readable error response. This issue implements RFC 9457 (Problem Details for HTTP APIs) as the gateway's universal error format, ensuring consumers can programmatically parse errors regardless of which validation layer generated them.

The error response includes a `type` URI identifying the error category, a `title`, a `status` code, a `detail` message, and an `errors` array with per-field entries. Each field error includes a JSON Pointer (`/body/address/zipCode`), the violated constraint (`pattern`), and the expected vs. actual value (with PII redaction for sensitive fields).

Error responses are localized based on the `Accept-Language` header when translations are available. The default language is English. The gateway ships with error message templates that can be overridden per tenant via `PUT /api/v1/gateway/tenants/{tenantId}/error-templates`.

A NextJS page at `/gateway/errors` provides a searchable log of recent validation errors with filters by route, error type, and time range. This page uses Radix `Table` for the error list, `Popover` for field-level detail inspection, and `Tabs` for switching between request errors and response violations.

**Acceptance Criteria**

- All gateway-generated errors conform to RFC 9457 with `type`, `title`, `status`, `detail`, and `errors[]`
- Each field-level error includes a JSON Pointer path to the offending field
- Sensitive fields (marked in the schema as `x-sensitive`) have their values redacted in error details
- Error templates are customizable per tenant via REST API
- The `/gateway/errors` page displays filterable, paginated error logs using Radix `Table` and `Tabs`
- Error responses include a `correlation_id` header for tracing

**Part of Epic: Schema-Driven Request Pipeline**

---

## Epic 2: Traffic Management & Resilience

### Summary Table

| #   | Title                              | Description                                                                  | Labels                                  | Parallel |
|-----|------------------------------------|------------------------------------------------------------------------------|-----------------------------------------|----------|
| 2.1 (#1061) | Load Balancer & Health Checks      | Weighted round-robin with passive and active health checking                 | `enhancement`, `mvp`, `gateway`         | Yes      |
| 2.2 (#1062) | Circuit Breaker                    | Per-upstream circuit breaker with configurable thresholds and recovery       | `enhancement`, `mvp`, `gateway`         | Yes      |
| 2.3 (#1063) | Retry Policies                     | Configurable retry with exponential backoff, jitter, and idempotency keys   | `enhancement`, `gateway`                | Yes      |
| 2.4 (#1064) | Request/Response Caching           | Schema-aware caching layer with TTL, invalidation, and cache-key derivation | `enhancement`, `mvp`, `gateway`         | No       |
| 2.5 (#1065) | Rate Limiting & Quotas             | Per-consumer rate limits tied to usage plans and API key tiers              | `enhancement`, `mvp`, `gateway`, `rest` | Yes      |

### Detailed Issue Descriptions

---

#### 2.1 (#1061) — Load Balancer & Health Checks

Production gateways must distribute traffic across multiple upstream instances and stop sending requests to unhealthy backends. This issue implements a load balancer with weighted round-robin distribution and both passive and active health checking.

Each route binding in the gateway can declare multiple upstream targets with weights. The load balancer maintains a ring of targets and selects the next one based on weight distribution. When a target returns 5xx errors or connection failures above a configurable threshold within a sliding window, the passive health checker marks it as unhealthy and removes it from the ring. An active health checker periodically sends synthetic requests to a configurable health endpoint and re-adds targets once they respond successfully.

Configuration is managed via `POST /api/v1/gateway/upstreams` with fields for URL, weight, health check path, interval, and thresholds. The gateway admin UI at `/gateway/upstreams` shows a real-time status panel with green/yellow/red indicators per upstream using Radix `Badge` and `Table` components.

The load balancer emits metrics (requests per upstream, latency per upstream, health state transitions) to the gateway's metrics pipeline for dashboard consumption.

**Acceptance Criteria**

- Traffic distributes across upstreams proportionally to configured weights
- Passive health checking removes an upstream after N consecutive 5xx responses (configurable)
- Active health checking re-adds an upstream when the health endpoint returns 200
- At least one upstream must remain in the ring; if all are unhealthy, the gateway returns 503
- Upstream configuration is manageable via REST API and the `/gateway/upstreams` admin page
- Health state transitions are logged and exposed as metrics events

**Part of Epic: Traffic Management & Resilience**

---

#### 2.2 (#1062) — Circuit Breaker

When an upstream service is degraded, continuing to send it requests wastes resources and increases latency for consumers. This issue implements a per-upstream circuit breaker following the standard closed → open → half-open state machine pattern.

In the **closed** state, requests flow normally. When the error rate within a sliding window exceeds the configured threshold (e.g., 50% of the last 100 requests), the breaker trips to **open**. In open state, all requests to that upstream are immediately rejected with a 503 and a `Retry-After` header. After a configurable cooldown period, the breaker enters **half-open** and allows a limited number of probe requests. If probes succeed, the breaker resets to closed; if they fail, it returns to open.

```
              success
        ┌───────────────┐
        ▼               │
  ┌──────────┐    ┌───────────┐    ┌───────────┐
  │  CLOSED  │───▶│   OPEN    │───▶│ HALF-OPEN │
  │          │    │           │    │           │
  │ requests │    │ fail-fast │    │  N probes │
  │ flow     │    │ 503 + RA  │    │  allowed  │
  └──────────┘    └───────────┘    └───────────┘
       ▲          error threshold       │
       │          exceeded              │
       └────────────────────────────────┘
                   probes fail → re-open
```

Configuration is per-upstream via `PUT /api/v1/gateway/upstreams/{id}/circuit-breaker` with fields: `errorThresholdPercent`, `windowSize`, `cooldownSeconds`, `halfOpenProbes`. The gateway dashboard shows circuit state per upstream with color-coded indicators.

**Acceptance Criteria**

- Circuit breaker transitions through closed → open → half-open → closed states correctly
- Open-state requests return 503 with a `Retry-After` header reflecting the remaining cooldown
- Half-open state allows exactly the configured number of probe requests
- Configuration is per-upstream and adjustable without gateway restart
- State transitions are logged with timestamps for post-incident analysis
- The gateway dashboard displays current circuit state per upstream

**Part of Epic: Traffic Management & Resilience**

---

#### 2.3 (#1063) — Retry Policies

Transient failures (network blips, upstream restarts, brief overloads) should not cause consumer-facing errors when a simple retry would succeed. This issue adds configurable retry policies with exponential backoff, jitter, and idempotency awareness.

Retry policies are configured per-route. Each policy specifies: max retries (default 2), base delay (default 500ms), backoff multiplier (default 2), max delay cap (default 5s), and retryable status codes (default 502, 503, 504). Jitter is added to prevent thundering-herd retries across many gateway instances.

Critically, the gateway only retries requests that are safe to retry. GET, HEAD, OPTIONS, and requests with an `Idempotency-Key` header are always retryable. POST/PUT/PATCH without an idempotency key are not retried unless the failure occurred before the request was sent to the upstream (connection refused). This prevents duplicate side effects.

The retry layer sits between the load balancer and the circuit breaker. If a request fails and the target's circuit breaker is still closed, the retry selects the next healthy upstream from the load balancer ring. This provides both retry and failover in a single mechanism.

**Acceptance Criteria**

- GET requests are retried up to the configured maximum on retryable status codes
- POST/PUT/PATCH requests are only retried when an `Idempotency-Key` header is present or the failure was pre-send
- Exponential backoff with jitter is applied between retries
- Retries select alternate upstreams from the load balancer ring when available
- Total retry latency is bounded by the max delay cap
- Retry attempts are logged with attempt number and reason for each retry

**Part of Epic: Traffic Management & Resilience**

---

#### 2.4 (#1064) — Request/Response Caching

Many API responses are cacheable—reference data, configuration, or any resource with a stable representation. This issue adds a Redis-backed caching layer that uses schema-aware cache keys to maximize hit rates while preventing stale data across schema versions.

Cache keys are derived from: route ID + schema version + normalized request path + sorted query parameters + relevant headers (e.g., `Accept`, `Accept-Language`). This ensures that a schema version change automatically invalidates cached responses, preventing consumers from receiving data validated against an old schema.

Cache behavior is configured per-route with: TTL (seconds), max body size (skip caching for large responses), cacheable status codes (default 200, 203, 300, 301), and vary headers. The gateway respects upstream `Cache-Control` headers when present, using the minimum of the upstream `max-age` and the configured TTL. A `X-Gateway-Cache` response header indicates HIT, MISS, or BYPASS.

Manual cache invalidation is available via `DELETE /api/v1/gateway/cache?routeId={id}&schemaVersion={v}` for operational use when an upstream deploys new data. The gateway admin page at `/gateway/cache` displays cache hit/miss ratios and top cached routes using Radix `Table` and `Badge` components.

**Acceptance Criteria**

- Cacheable responses are stored in Redis and served on subsequent identical requests
- Cache keys incorporate schema version so version changes automatically invalidate entries
- `X-Gateway-Cache: HIT|MISS|BYPASS` header is included on every response
- Upstream `Cache-Control` headers are respected when present
- Manual cache invalidation works via REST API for specific routes and/or schema versions
- Cache metrics (hit rate, miss rate, eviction count) are exposed on the admin dashboard

**Part of Epic: Traffic Management & Resilience**

---

#### 2.5 (#1065) — Rate Limiting & Quotas

API consumers need predictable access governed by their subscription tier, and the gateway must protect upstream services from abuse. This issue implements per-consumer rate limiting using a sliding window algorithm backed by Redis, tied to API key tiers and usage plans.

Rate limits are defined at two levels: per-second (burst) and per-month (quota). Each API key is assigned to a usage plan that specifies both limits. The sliding window algorithm uses Redis sorted sets to track request timestamps, providing accurate rate calculations without the boundary issues of fixed windows.

When a consumer exceeds their rate limit, the gateway returns 429 Too Many Requests with headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (Unix timestamp). When approaching the monthly quota (>80%), responses include a `X-Quota-Warning` header. Quota exhaustion returns 429 with a different `type` URI distinguishing it from burst rate limiting.

The rate limiting configuration UI lives at `/gateway/plans` (NextJS page) using Radix `Table` for plan listing, `Dialog` for plan creation/editing, and `Slider` for setting thresholds. The REST API exposes `POST /api/v1/gateway/plans` and `PUT /api/v1/gateway/api-keys/{keyId}/plan`.

**Acceptance Criteria**

- Per-second burst limits reject excess requests with 429 and appropriate rate limit headers
- Monthly quotas track cumulative usage and enforce hard limits at the plan ceiling
- API keys are assignable to usage plans via REST API
- 80% quota threshold triggers `X-Quota-Warning` headers on responses
- Rate limit state survives gateway restarts (Redis-backed)
- The `/gateway/plans` admin page allows CRUD operations on usage plans with Radix `Dialog` and `Table`

**Part of Epic: Traffic Management & Resilience**

---

## Epic 3: Transformation & Version Translation

### Summary Table

| #   | Title                                | Description                                                                   | Labels                            | Parallel |
|-----|--------------------------------------|-------------------------------------------------------------------------------|-----------------------------------|----------|
| 3.1 (#1067) | Schema Version Bridge                | Automatically translate requests/responses between schema versions            | `enhancement`, `gateway`, `rest`  | Yes      |
| 3.2 (#1068) | Format Conversion Engine             | Convert between JSON, XML, and Protobuf based on Accept/Content-Type headers | `enhancement`, `gateway`          | Yes      |
| 3.3 (#1069) | Field Mapping & Filtering            | Rename, restructure, and filter fields between consumer and upstream shapes   | `enhancement`, `gateway`, `rest`  | No       |
| 3.4 (#1070) | Response Aggregation                 | Compose a single consumer response from multiple upstream service calls       | `enhancement`, `gateway`, `rest`  | No       |
| 3.5 (#1071) | Transformation Pipeline Config UI    | Admin interface for building and testing transformation chains                | `enhancement`, `gateway`          | No       |

### Detailed Issue Descriptions

---

#### 3.1 (#1067) — Schema Version Bridge

One of the gateway's most powerful capabilities is transparent schema version translation. When a consumer sends a request targeting schema v1 but the upstream service expects v2, the gateway automatically transforms the request forward and the response backward, using the diff between schema versions as the transformation recipe.

The version bridge computes a structural diff between two schema captures, identifying added fields (supply defaults), removed fields (strip), renamed fields (map), and type changes (coerce). This diff is computed once when a new schema version is published and cached. At request time, the bridge applies forward transforms to the request body and reverse transforms to the response body.

Ambiguous transformations (a field split into two, or a type change from string to object) cannot be auto-resolved. These are flagged during diff computation and require manual mapping rules (issue 3.3). The bridge only handles unambiguous structural changes automatically.

The bridge is activated per-route by specifying `consumerSchemaVersion` and `upstreamSchemaVersion` in the route binding. The REST API endpoint is `PUT /api/v1/gateway/routes/{id}/version-bridge`. A preview endpoint (`POST /api/v1/gateway/routes/{id}/version-bridge/preview`) accepts a sample payload and returns the transformed output for verification.

```
Consumer (v1)           Gateway                    Upstream (v2)
    │                      │                           │
    │  POST /orders (v1)   │                           │
    │─────────────────────▶│                           │
    │                      │  forward transform        │
    │                      │  v1 → v2                  │
    │                      │──────────────────────────▶│
    │                      │                           │
    │                      │  response (v2)            │
    │                      │◀──────────────────────────│
    │                      │  reverse transform        │
    │                      │  v2 → v1                  │
    │  response (v1)       │                           │
    │◀─────────────────────│                           │
```

**Acceptance Criteria**

- Unambiguous field additions are handled by supplying schema-defined defaults in the forward transform
- Removed fields are stripped from the transformed payload without error
- Renamed fields are mapped correctly in both forward and reverse directions
- Ambiguous transformations are flagged during diff computation and require manual mapping rules
- The preview endpoint returns the transformed payload without sending to upstream
- Version bridge is toggleable per route; disabled routes pass payloads through unmodified

**Part of Epic: Transformation & Version Translation**

---

#### 3.2 (#1068) — Format Conversion Engine

Not all API consumers speak JSON. Legacy systems may require XML, and high-performance internal services may use Protobuf. This issue builds a format conversion engine that translates between JSON, XML, and Protobuf based on `Content-Type` and `Accept` headers.

The engine uses the Apiome schema as the canonical format definition. JSON is the native format. For XML conversion, the engine maps JSON object properties to XML elements, arrays to repeated elements, and uses schema annotations (`x-xml-name`, `x-xml-attribute`, `x-xml-wrapped`) to control XML-specific formatting. For Protobuf, the engine generates `.proto` definitions from the schema at publish time and uses compiled serializers for fast conversion.

Format conversion sits in the transformation pipeline after type coercion and before validation. Incoming non-JSON requests are converted to JSON for validation, then the response is converted back to the requested format on the way out. This means the validation engine always operates on JSON regardless of the wire format.

Configuration is per-route via `PUT /api/v1/gateway/routes/{id}/formats` specifying which formats are enabled. Protobuf support requires a one-time `.proto` generation step triggered via `POST /api/v1/gateway/schemas/{id}/proto`.

**Acceptance Criteria**

- XML requests with `Content-Type: application/xml` are converted to JSON for validation and upstream forwarding
- Responses are converted to XML when the consumer sends `Accept: application/xml`
- Protobuf serialization/deserialization works for schemas with generated `.proto` definitions
- Schema annotations (`x-xml-name`, `x-xml-attribute`) control XML element naming and structure
- Format support is toggleable per route; unsupported format requests receive 415 Unsupported Media Type
- Conversion round-trips (JSON → XML → JSON) produce identical data for all supported schema types

**Part of Epic: Transformation & Version Translation**

---

#### 3.3 (#1069) — Field Mapping & Filtering

When consumers and upstream services use different field names, structures, or subsets of a schema, the gateway needs explicit field mapping rules. This issue builds the mapping engine that renames, restructures, and filters fields during request/response transformation.

Mappings are defined as declarative rules: source JSON Pointer → target JSON Pointer, with optional transformation functions (uppercase, lowercase, format date, split string, join array). Rules are ordered and executed sequentially, allowing complex restructuring like flattening a nested object into top-level fields or grouping top-level fields into a nested object.

Field filtering lets consumers receive only the fields they need. A route binding can specify an `includeFields` or `excludeFields` list. The gateway strips unneeded fields from the response before sending it to the consumer, reducing bandwidth and preventing exposure of internal fields.

The mapping configuration UI is a NextJS page at `/gateway/routes/[routeId]/mappings` with a visual field-to-field mapping interface. Source and target schemas are displayed side-by-side, and administrators drag connections between fields. The page uses Radix `ScrollArea` for schema display, `Select` for transformation functions, and `Table` for the rule summary.

**Acceptance Criteria**

- Field rename mappings correctly transform both request and response payloads
- Nested-to-flat and flat-to-nested restructuring works for arbitrary depth
- `includeFields` filtering returns only the specified fields in responses
- `excludeFields` filtering strips specified fields from responses
- Mapping rules are persisted per-route and manageable via REST API (`POST /api/v1/gateway/routes/{id}/mappings`)
- The mapping UI renders source/target schemas side-by-side with visual connection lines

**Part of Epic: Transformation & Version Translation**

---

#### 3.4 (#1070) — Response Aggregation

Modern frontends often need data from multiple backend services in a single API call. This issue adds a response aggregation capability where a single gateway route fans out to multiple upstream services, merges their responses according to a declared schema, and returns a unified response.

An aggregation route defines multiple upstream calls with their individual request transformations and a merge strategy. Merge strategies include: `merge` (combine top-level fields from all responses), `nest` (place each response under a named key), and `array` (collect responses into an array). Upstream calls execute in parallel by default; sequential execution is supported for cases where one call's response feeds into another's request.

Error handling in aggregation is configurable: `fail-fast` (return error if any upstream fails), `partial` (return available data with an `errors` array for failed upstreams), or `fallback` (use cached or default values for failed upstreams). The response includes a `X-Aggregation-Status` header indicating full/partial success.

The aggregation configuration is managed via `POST /api/v1/gateway/routes/{id}/aggregation` with the upstream definitions, merge strategy, and error handling mode. A dry-run endpoint tests the aggregation against live upstreams and returns the merged response without caching or logging it as production traffic.

**Acceptance Criteria**

- Parallel upstream calls complete and merge into a single response within a configurable timeout
- `merge`, `nest`, and `array` strategies produce correct output structures
- `partial` error mode returns available data with an `errors` array for failed upstreams
- Sequential execution mode passes prior response data to subsequent upstream request templates
- Aggregation routes are configurable via REST API with full OpenAPI 3.1 spec
- The `X-Aggregation-Status` header correctly reflects full or partial success

**Part of Epic: Transformation & Version Translation**

---

#### 3.5 (#1071) — Transformation Pipeline Config UI

Transformations (version bridge, format conversion, field mapping, aggregation) form a pipeline. This issue builds the admin UI where gateway administrators compose, order, and test transformation chains visually.

The pipeline config page lives at `/gateway/routes/[routeId]/pipeline` in the NextJS app. It displays the current transformation steps as an ordered vertical list, where each step shows its type (coercion → validation → version bridge → field mapping → format conversion) and its configuration summary. Administrators can reorder steps via drag-and-drop, add new steps from a Radix `DropdownMenu`, and edit each step's configuration in a Radix `Dialog`.

A built-in test panel on the right side of the page lets administrators paste a sample request, select a consumer schema version and format, and click "Run Pipeline" to see the transformed output at each step. This eliminates guesswork when building complex transformation chains.

The page also displays warnings for misconfigured pipelines: coercion after validation (should be before), format conversion without the format enabled on the route, or version bridge without both versions specified.

**Acceptance Criteria**

- The pipeline page renders the ordered list of transformation steps for a route
- Drag-and-drop reordering persists the new step order via REST API
- Adding a new step opens a Radix `Dialog` with step-type-specific configuration fields
- The test panel executes the pipeline against a sample payload and displays intermediate results per step
- Misconfiguration warnings appear inline when step ordering or configuration is invalid
- Pipeline configuration changes are audited with the admin user ID and timestamp

**Part of Epic: Transformation & Version Translation**

---

## Epic 4: Developer Portal & Monetization

### Summary Table

| #   | Title                            | Description                                                                  | Labels                                  | Parallel |
|-----|----------------------------------|------------------------------------------------------------------------------|-----------------------------------------|----------|
| 4.1 (#1073) | Auto-Generated Developer Portal  | Public-facing portal auto-generated from Apiome schemas                 | `enhancement`, `mvp`, `gateway`         | Yes      |
| 4.2 (#1074) | Try-It-Out Console               | Interactive API explorer embedded in the portal for live request testing     | `enhancement`, `mvp`, `gateway`         | Yes      |
| 4.3 (#1075) | API Key Self-Service             | Consumer-facing key management: create, rotate, revoke, view usage          | `enhancement`, `mvp`, `gateway`, `rest` | Yes      |
| 4.4 (#1076) | Usage Dashboards                 | Per-consumer dashboards showing request volume, latency, errors, and quotas | `enhancement`, `mvp`, `gateway`         | No       |
| 4.5 (#1077) | Usage-Based Billing Integration  | Metered billing engine with tiered plans, invoice generation, and Stripe integration | `enhancement`, `gateway`, `rest` | No       |
| 4.6 (#1078) | Quota Management & Alerts        | Configurable quotas with email/webhook alerts at threshold crossings        | `enhancement`, `gateway`                | No       |

### Detailed Issue Descriptions

---

#### 4.1 (#1073) — Auto-Generated Developer Portal

The developer portal is the public face of every API published through the gateway. This issue builds the portal generation engine that reads published Apiome schemas and produces a polished, navigable documentation site—automatically, with zero manual authoring required.

The portal is a NextJS application served at `/portal/[tenantSlug]`. It renders each schema class as a documentation page with: endpoint URL, HTTP method, request/response schemas rendered as interactive expandable trees, field descriptions, types, constraints, and examples. The navigation sidebar groups endpoints by tag (from the OpenAPI spec) and supports search.

The portal pulls content from the gateway's route bindings and the underlying Apiome schema captures. When a new schema version is published or a route binding changes, the portal re-generates within seconds. There is no separate build step—content is rendered on-demand with ISR (Incremental Static Regeneration) for performance.

Branding is customizable per tenant: logo, accent color, favicon, and introductory markdown content. Configuration is managed via `PUT /api/v1/gateway/portal/{tenantId}/branding`. The portal uses Radix `NavigationMenu` for the sidebar, `Accordion` for expandable schema trees, and `Tabs` for switching between request/response/example views.

**Acceptance Criteria**

- The portal renders all routes bound to the tenant's gateway with endpoint URL, method, and schema documentation
- Schema fields display type, description, constraints (min/max/pattern), and example values
- Navigation sidebar groups endpoints by tag with full-text search
- ISR ensures portal updates within 60 seconds of schema or route changes
- Tenant branding (logo, color, favicon, intro text) is customizable via REST API
- The portal is publicly accessible without authentication; authenticated sections (API keys, usage) require login

**Part of Epic: Developer Portal & Monetization**

---

#### 4.2 (#1074) — Try-It-Out Console

Documentation is useful, but developers learn fastest by sending real requests. This issue builds an interactive API console embedded in the developer portal where consumers can compose requests, send them through the gateway, and inspect responses—all within the browser.

The console pre-populates request fields from the schema's example values. Consumers can edit the body in a JSON editor (with schema-aware autocomplete and inline validation), set headers, and choose authentication (paste an API key or use an OAuth flow). The send button dispatches the request through the gateway and displays the response with syntax highlighting, timing, and response headers.

The console supports all HTTP methods and displays the equivalent `curl` command for each request, allowing developers to copy-paste into their terminal. Request history is stored in browser local storage so developers can revisit previous attempts.

The console component is built with Radix `Tabs` (for request/response/curl views), `TextArea` for the body editor, and `Select` for method and content-type selection. It lives at `/portal/[tenantSlug]/[endpointId]/try` within the NextJS app.

**Acceptance Criteria**

- The console pre-populates request body, headers, and URL from schema examples
- Requests are sent through the gateway and subject to all validation and transformation rules
- Responses display with syntax-highlighted body, status code, timing, and response headers
- A copy-to-clipboard `curl` equivalent is generated for every request
- Request history persists in local storage across browser sessions
- The console validates the request body against the schema before sending, showing inline errors

**Part of Epic: Developer Portal & Monetization**

---

#### 4.3 (#1075) — API Key Self-Service

API consumers need to manage their own credentials without filing support tickets. This issue builds the self-service API key management interface within the developer portal, allowing registered consumers to create, rotate, and revoke API keys tied to their usage plan.

Each consumer signs up via the portal (email + password or SSO) and receives a consumer account. From the key management page (`/portal/[tenantSlug]/keys`), they can create new API keys with optional labels and expiration dates. Keys are displayed once at creation (full value) and subsequently shown as masked (`obj_****abcd`). Consumers can rotate a key (which creates a new key and schedules the old one for revocation after a grace period) or revoke immediately.

The backend REST API exposes `POST /api/v1/gateway/consumers/{consumerId}/keys`, `DELETE /api/v1/gateway/consumers/{consumerId}/keys/{keyId}`, and `POST /api/v1/gateway/consumers/{consumerId}/keys/{keyId}/rotate`. Keys are stored as bcrypt hashes; the raw value is never persisted. The grace period for rotation defaults to 24 hours and is configurable per tenant.

The key management page uses Radix `Table` for the key list, `Dialog` for key creation, `AlertDialog` for revocation confirmation, and `Badge` for key status (active, rotating, revoked, expired).

**Acceptance Criteria**

- Consumers can create API keys with optional labels and expiration dates via the portal
- Key values are displayed exactly once at creation and stored as bcrypt hashes
- Key rotation creates a new key and revokes the old key after a configurable grace period
- Revocation is immediate and confirmed via Radix `AlertDialog`
- The key management page displays masked key values with status badges
- All key lifecycle events (create, rotate, revoke) are logged in the gateway audit trail

**Part of Epic: Developer Portal & Monetization**

---

#### 4.4 (#1076) — Usage Dashboards

Consumers need visibility into their API usage to stay within quotas and optimize their integration. This issue builds per-consumer dashboards showing request volume, latency percentiles, error rates, and quota consumption over configurable time ranges.

The dashboard page lives at `/portal/[tenantSlug]/usage` and displays four primary widgets: (1) request volume time series (hourly/daily/monthly), (2) latency percentiles (p50, p95, p99) as a line chart, (3) error rate by status code as a stacked bar chart, and (4) quota consumption as a progress bar with the plan ceiling.

Data is aggregated from the gateway's request logs into a time-series store (PostgreSQL with TimescaleDB extension or a dedicated time-series table with hourly rollups). The dashboard queries the aggregation API (`GET /api/v1/gateway/consumers/{consumerId}/usage?from=&to=&granularity=`) which returns pre-computed metrics.

The page uses Radix `Tabs` for time range selection (24h, 7d, 30d, custom), `Select` for granularity, and `Table` for a detailed breakdown by endpoint. Charts are rendered with a lightweight charting library. The dashboard is also available to gateway admins at `/gateway/consumers/[consumerId]/usage` with additional columns for billing reconciliation.

**Acceptance Criteria**

- Request volume chart displays accurate counts at hourly, daily, and monthly granularity
- Latency percentiles (p50, p95, p99) are computed from gateway request logs
- Error rate breakdown shows counts by HTTP status code category (4xx, 5xx)
- Quota progress bar reflects current period consumption vs. plan ceiling
- Time range selection (24h, 7d, 30d, custom) updates all widgets simultaneously
- Data freshness is within 5 minutes of real-time; the dashboard displays a "last updated" timestamp

**Part of Epic: Developer Portal & Monetization**

---

#### 4.5 (#1077) — Usage-Based Billing Integration

Monetizing the API gateway requires accurate metering and billing. This issue builds the billing engine that tracks per-consumer usage, applies tiered pricing, generates invoices, and integrates with Stripe for payment processing.

Billing plans define pricing tiers: a free tier (e.g., 1,000 requests/month), a standard tier (e.g., $0.001/request up to 1M), and an enterprise tier (custom pricing). Each tier can include overage rates for usage beyond the allocation. Plans are managed via `POST /api/v1/gateway/billing/plans` with the pricing structure as a JSON document.

At the end of each billing period (monthly), the billing engine queries the usage aggregation API, applies the consumer's plan pricing, and generates an invoice. Invoices are stored in PostgreSQL and exposed via `GET /api/v1/gateway/consumers/{consumerId}/invoices`. Integration with Stripe handles payment method management, charge creation, and webhook handling for payment events (succeeded, failed, disputed).

The billing admin page at `/gateway/billing` provides Radix `Table` for invoice listing, `Dialog` for plan editing, and `Tabs` for switching between plans, invoices, and revenue reports. Consumers view their invoices at `/portal/[tenantSlug]/billing`.

**Acceptance Criteria**

- Billing plans support tiered pricing with free tier, per-request pricing, and overage rates
- Monthly invoices are generated automatically from metered usage data
- Stripe integration handles payment method attachment, charge creation, and webhook processing
- Consumers can view and download invoices from the portal billing page
- Gateway admins can view revenue reports aggregated by plan, consumer, and time period
- Invoice generation is idempotent; re-running for the same period produces the same invoice

**Part of Epic: Developer Portal & Monetization**

---

#### 4.6 (#1078) — Quota Management & Alerts

Quotas without alerts lead to surprise 429 errors. This issue builds the alerting system that notifies consumers and admins when quota thresholds are crossed, and provides quota management tools for gateway admins to adjust limits on the fly.

Alert thresholds are configurable per plan: warning at 80%, critical at 95%, and exhausted at 100%. Notifications are delivered via email (SendGrid/SES) and webhook (consumer-provided URL). Each alert includes the current usage count, the plan ceiling, the projected exhaustion date (based on current usage rate), and a link to upgrade or contact sales.

Gateway admins can temporarily adjust a consumer's quota via `PUT /api/v1/gateway/consumers/{consumerId}/quota-override` with an expiration date, allowing for promotional periods or burst capacity during a launch. Overrides are audited and auto-expire.

The admin UI at `/gateway/quotas` shows a sortable Radix `Table` of all consumers with their current usage percentage, plan, and alert status. Clicking a consumer opens a Radix `Dialog` for applying quota overrides.

**Acceptance Criteria**

- Email alerts fire at 80%, 95%, and 100% quota consumption thresholds
- Webhook alerts deliver a JSON payload to the consumer's configured URL at each threshold
- Alerts include usage count, ceiling, projected exhaustion date, and upgrade link
- Admins can apply temporary quota overrides with expiration dates via REST API
- Quota overrides are logged in the audit trail with admin user and reason
- The `/gateway/quotas` admin page displays all consumers with usage percentages sortable by column

**Part of Epic: Developer Portal & Monetization**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Schema-Driven Request Pipeline):**
- 1.1 (Validation Engine), 1.2 (Type Coercion), and 1.5 (Error Formatting) can all be developed in parallel. The validation engine and coercion layer share an interface but have independent internals. Error formatting is a standalone output module.
- 1.3 (Custom Rules) depends on 1.1 being complete since rules run after schema validation.
- 1.4 (Response Validation) depends on 1.1 for the core validation engine.

**Epic 2 (Traffic Management & Resilience):**
- 2.1 (Load Balancer), 2.2 (Circuit Breaker), 2.3 (Retry Policies), and 2.5 (Rate Limiting) can all start in parallel since they operate on independent middleware layers.
- 2.4 (Caching) should follow 2.1 because cache key derivation depends on the route binding model established by the load balancer.

**Epic 3 (Transformation & Version Translation):**
- 3.1 (Version Bridge) and 3.2 (Format Conversion) are independent engines and can be built in parallel.
- 3.3 (Field Mapping) depends on 3.1 for the manual mapping rules that supplement the auto-bridge.
- 3.4 (Response Aggregation) depends on the route binding model but is otherwise independent.
- 3.5 (Pipeline Config UI) depends on all other transformation issues being at least partially implemented.

**Epic 4 (Developer Portal & Monetization):**
- 4.1 (Portal), 4.2 (Try-It-Out), and 4.3 (API Key Self-Service) can be developed in parallel.
- 4.4 (Usage Dashboards) depends on the metering data pipeline but can be stubbed independently.
- 4.5 (Billing) depends on 4.4 for usage data and 2.5 for rate limiting plan definitions.
- 4.6 (Quota Alerts) depends on 4.5 for plan definitions and 2.5 for quota tracking.

**Cross-Epic Parallelism:**
- Epic 1 and Epic 2 are fully independent and can be developed by separate teams.
- Epic 3 depends on Epic 1 (validation engine) for the transformation pipeline.
- Epic 4 depends on Epic 2 (rate limiting, issue 2.5) for usage plan enforcement.
