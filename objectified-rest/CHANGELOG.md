# Changelog

All notable changes to the Objectified REST API will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.8.1] - 2026-06-26

### Added
- **MCP endpoint lifecycle — delete (#3667, V2-MCP-17.5 / MCAT-3.5)** — endpoints can now be retired
  via `DELETE /v1/mcp/{tenant_slug}/endpoints/{id}`. The endpoint row is *soft* deleted (stamped
  `deleted_at`, flipped to `enabled = false`, `current_version_id` cleared) so it disappears from
  browse/list/get and is skipped by the discovery sweep, while its slug stays reserved against the
  `(tenant_id, slug)` unique constraint. Its child data is *hard* deleted in the same tenant-scoped
  transaction: the credential vault row (the security-critical purge), every discovery job, and every
  version snapshot — whose capability items, change logs and scores cascade away via the
  `ON DELETE CASCADE` chain off `mcp_endpoint_versions`. The route returns a teardown summary
  (`credentials_purged`, `versions_deleted`, `jobs_deleted`) and `404` when the endpoint is not the
  caller's tenant's (or was already deleted). New `database.py` method `soft_delete_mcp_endpoint`, new
  `models.py` response model `McpEndpointDeleteResponse`; covered by route and DB-layer unit tests in
  `tests/test_mcp_catalog_routes.py`. (Enable/disable already shipped in #3663 via the `enabled` PATCH
  field, so this completes the enable/disable/delete lifecycle.)

## [1.6.6] - 2026-06-26

### Added
- **MCP catalog endpoint CRUD (#3663, V2-MCP-17.1 / MCAT-3.1)** — tenants can now register and manage
  external MCP servers in a catalog. New `app/mcp_catalog_routes.py` exposes the `mcp_endpoints_router`
  (registered in `main.py`) with tenant-scoped CRUD over `odb.mcp_endpoints`:
  `POST /v1/mcp/{tenant_slug}/endpoints` (register), `GET …/endpoints` (list),
  `GET …/endpoints/{id}` (fetch), and `PATCH …/endpoints/{id}` (partial update). Tenant scoping comes
  from the existing `validate_authentication` dependency (JWT Bearer or `X-API-Key`): every query is
  scoped to the caller's `tenant_id` — never the URL slug — so a cross-tenant id reads as `404`. The
  catalog `slug` is auto-derived from the endpoint name (or an explicit `slug` override) and made
  unique within the tenant by the DB layer (`base`, then `base-2`, `base-3`, …), with the
  `(tenant_id, slug)` unique constraint as a backstop that surfaces as `409`. New `database.py` methods
  `list_mcp_endpoints`, `get_mcp_endpoint`, `insert_mcp_endpoint`, `update_mcp_endpoint`, and the
  `_next_available_mcp_slug` resolver; new `models.py` request/response models
  (`McpEndpointCreate` / `McpEndpointUpdate` / `McpEndpointOut`, transport + visibility enums, positive
  cadence bound, camelCase aliases). Covered by route, model, and DB-layer unit tests in
  `tests/test_mcp_catalog_routes.py`; OpenAPI docs are generated for all four operations.

## [1.6.3] - 2026-06-26

### Added
- **MCP discovery list methods + pagination (#3659, V2-MCP-16.3)** — the capability-enumeration layer
  of the MCP discovery client (`app/mcp_client/discovery.py`), sitting on top of the `initialize`
  handshake. `discover_listings()` walks `tools/list`, `resources/list`, `resources/templates/list`
  (result key `resourceTemplates`), and `prompts/list`, returning a `DiscoveryListings` of raw items
  per category. Each endpoint is queried **only** when the server declared its owning capability in
  `initialize` (the single `resources` capability gates both resource endpoints); undeclared endpoints
  are skipped and reported in `DiscoveryListings.skipped`. The lower-level `paginate()` helper follows
  the opaque `cursor`/`nextCursor` loop to exhaustion, accumulating every page. Because the cursor is
  server-supplied, the loop is guarded against non-terminating servers two ways — a repeated cursor (a
  cycle) and exceeding `DEFAULT_PAGE_LIMIT` pages both raise `McpPaginationError`; a declared endpoint
  that returns a JSON-RPC error raises `McpDiscoveryError`. Covered by mocked-httpx unit tests plus an
  integration test that pages a real multi-page loopback stub and confirms undeclared capabilities are
  never requested.

## [1.6.2] - 2026-06-26

### Added
- **MCP initialize handshake + version negotiation (#3658, V2-MCP-16.2)** — the lifecycle layer on top
  of the Streamable HTTP transport (`app/mcp_client/handshake.py`). `initialize_session()` sends
  `initialize` with our `protocolVersion`, `capabilities`, and `clientInfo`; parses `serverInfo`,
  `capabilities`, and `instructions`; and negotiates the protocol version (echo, result-level fallback,
  `-32602` fallback-and-retry, disconnect on unsupported). The negotiated version is recorded on the
  transport (pinning `MCP-Protocol-Version` on later requests) and returned on `InitializeResult`,
  after which `notifications/initialized` completes the handshake. Covered by mocked-httpx unit tests
  plus an integration test negotiating against real loopback stub servers for both supported revisions.

## [1.6.1] - 2026-06-26

### Added
- **MCP transport client over Streamable HTTP (#3657, V2-MCP-16.1)** — the network foundation of the
  MCP discovery client (`app/mcp_client/transport_http.py`). `StreamableHttpTransport` speaks JSON-RPC
  2.0 to a single `…/mcp` endpoint per the MCP `2025-06-18` spec: every message is `POST`ed with
  `Accept: application/json, text/event-stream`, and both response shapes are handled transparently —
  a single `application/json` object or a `text/event-stream` SSE stream drained until the matching
  response id arrives (server-initiated messages on the stream are dispatched to an optional handler).
  Notifications are sent without an id and accept `202`. The server's `Mcp-Session-Id` is captured at
  `initialize` and echoed on every later request, `MCP-Protocol-Version` is pinned on all
  post-initialization requests, and the session is torn down with `DELETE` (a `405` refusal is
  tolerated). `400`/`405` surface as `McpHttpStatusError`; a `404` while a session is active surfaces
  as `McpSessionExpiredError` and clears the local session. Transport security: plaintext `http://` is
  allowed only to loopback hosts (local reference servers) unless `allow_insecure_http=True`, and an
  `Origin` header is always sent. Covered by mocked-httpx unit tests plus an integration test against a
  real loopback stub MCP server.

## [1.4.0] - 2026-06-24

### Added
- **Observability & error handling (#3617, RC1-3.2)** — production-grade diagnosability for the REST
  service. Structured JSON logging via `structlog` (`app/logging_config.py`, mirroring the MCP setup)
  emits one JSON object per line with `timestamp`, `level`, `logger`, `event` and a per-request
  `request_id` that is bound for the whole request lifetime — so every log line a handler emits is
  correlated to its request. A new `ObservabilityMiddleware` (`app/observability.py`, installed as the
  outermost layer) assigns/propagates the id via the `X-Request-ID` header (reusing an upstream value
  when present), records an in-process metrics registry (total requests, requests/sec, error rate,
  in-flight gauge, latency p50/p95/p99), and logs one access line per request.
- **Consistent error envelope** — exception handlers wrap every `4xx`/`5xx` (including
  `RequestValidationError` and the rate limiter's `429`) in a uniform shape that *preserves* FastAPI's
  `detail` for backward compatibility while adding an `error` object (`status`/`message`/`type`/
  `request_id`) and a top-level `request_id`. An unhandled-exception handler logs the full stack trace
  correlated to the request id (error tracking) and returns a safe generic 500 that never leaks
  internal details.
- **Health / readiness probes** — `GET /livez` (liveness, no DB), `GET /readyz` (readiness; `503` when
  the database is unreachable), and the backward-compatible `GET /health`. Wired into `docker-compose`
  (the `rest` healthcheck now uses `/readyz`; the `mcp` service gained a `/health` healthcheck).
- **Minimal ops dashboard** (platform-admin only) — `GET /v1/ops/metrics`, `/v1/ops/backups`,
  `/v1/ops/status`, and a dependency-free HTML `/v1/ops/dashboard`. Backup status is read from the
  RC1-1.3 backup manifests (`app/backup_status.py`): latest backup per scope, age, and a `stale` flag
  against the configured RPO window.
- New settings: `OBJECTIFIED_LOG_LEVEL`, `OBJECTIFIED_LOG_JSON`, `OBJECTIFIED_REQUEST_ID_HEADER`,
  `OBJECTIFIED_BACKUP_DIR`, `OBJECTIFIED_BACKUP_STALE_AFTER_HOURS`.

## [1.3.0] - 2026-06-23

### Added
- **Mock Server (#3615, RC1-2.2)** — provision a hosted mock from any published version and consume
  the designed API before a backend exists. New management plane `POST/GET /v1/mocks/{tenant_slug}`
  (provision, list), `GET/DELETE /v1/mocks/{tenant_slug}/{id}` (inspect, destroy), and
  `PUT .../active-scenario` (switch scenario), all tenant-scoped + authenticated. The OpenAPI
  document generated for the version (same output as `/v1/swagger/...`) is frozen into the instance,
  so the mock is stable for its lifetime. New public data plane `ANY /v1/mock/{id}/...` replays
  schema-valid responses synthesised deterministically from the response schemas
  (`app/mock_data_generator.py`, validated with `jsonschema`) and applies the selected scenario
  (`app/mock_engine.py`). Per-operation scenarios override status / latency / body and are selectable
  per instance or per request via the `X-Mock-Scenario` header; four built-ins ship (happy-path,
  server-error, not-found, slow). Free-tier guardrails: instances auto-expire (`410 Gone` past
  `expires_at`) and are rate limited per instance (`429` with `Retry-After`). Backed by migration
  V123 (`odb.mock_instances`). Configurable via `OBJECTIFIED_MOCK_SERVER_ENABLED` (default on),
  `OBJECTIFIED_MOCK_DEFAULT_TTL_HOURS` (default 24), `OBJECTIFIED_MOCK_MAX_TTL_HOURS` (default 168),
  and `OBJECTIFIED_MOCK_RATE_LIMIT_PER_MINUTE` (default 60).

## [1.2.0] - 2026-06-23

### Added
- **SSRF guard for user-supplied URL fetches (#3612)** — a new `app/ssrf_guard.py` vets every URL
  the import-from-URL and public repository-registration paths fetch: http/https only, no embedded
  credentials, and DNS resolution with rejection of any non-public address (loopback, RFC1918,
  link-local incl. the `169.254.169.254` metadata IP, multicast, reserved, unspecified — IPv4 and
  IPv6 including IPv4-mapped). Installed as an httpx request event hook so each redirect hop is
  re-validated, closing redirect-based bypasses. Applied to `import_ingestion._fetch_url_text`, the
  generic-URL branch of `repository_validation.validate_public_clone_url`, and the GitLab branch
  (whose API origin is derived from the tenant-supplied host). Set
  `OBJECTIFIED_SSRF_ALLOW_PRIVATE=true` to disable IP filtering for local development.
- **Per-tenant rate limiting (#3612)** — a new `app/rate_limit.py` middleware buckets requests by
  API key (hashed) → tenant slug (from the path) → client IP, enforcing a configurable fixed window.
  Authenticated traffic uses the higher limit, public traffic the lower; over-limit requests get
  `429` with `Retry-After`, and every response carries `X-RateLimit-{Limit,Remaining,Reset}`.
  Configurable via `OBJECTIFIED_RATE_LIMIT_ENABLED` (default on),
  `OBJECTIFIED_RATE_LIMIT_AUTHENTICATED_PER_MINUTE` (default 600),
  `OBJECTIFIED_RATE_LIMIT_PUBLIC_PER_MINUTE` (default 120), and
  `OBJECTIFIED_RATE_LIMIT_WINDOW_SECONDS` (default 60). `/health` and the docs are exempt. Limits
  are per replica (in-process counter); a shared store is the path to multi-replica enforcement.

### Fixed
- **GitLab clone-URL SSRF + crash (#3612)** — `parse_gitlab_project_path` built its API origin from
  `urlparse(...).host` (nonexistent attribute; raised `AttributeError`) and the GitLab branch
  fetched the tenant-controlled host with an unguarded client. Now reconstructs the origin from
  `hostname`/`port` and routes the fetch through the SSRF guard.

## [1.0.26] - 2026-06-23

### Added
- **Registry coverage/stats endpoint (#3454)** — `GET /v1/types/{tenant_slug}/stats` returns the
  tenant's registry coverage KPIs as a single server-side aggregate: core type count, tenant type
  count, imported count, properties bound, bound class count, unresolved `$ref` count, and
  namespace count. Backed by `Database.get_registry_coverage_stats(tenant_id)`, which aggregates
  over the extended `odb.primitives` table (type/namespace/import counts and unresolved `refs`
  edges) and the tenant's `odb.class_properties` bindings on the existing `objectified-db`
  connection — replacing the client-side stat computation in the Primitives overview dashboard
  (#3467). Gated by the `require_primitives_registry` entitlement and tenant-scoped to the
  authenticated caller. (The endpoint, model, and DB aggregate first shipped alongside #3467; this
  release documents and formally closes #3454.)

## [1.0.23] - 2026-06-23

### Added
- **Primitives type-registry entitlement & feature gating (#3478)** — the advanced Type Registry
  surface can now be gated behind a per-tenant `primitives-registry` entitlement. A reusable
  `require_primitives_registry` dependency (`app/feature_gating.py`) guards every `/v1/types/*`
  route (resolver, namespaces, settings, stats) plus the `/v1/primitives/*` import pipeline
  (`/import`, `/import/review`, `/import/stage`, `/imports`, `/imports/{id}`) and the `/unresolved`
  resolver. Baseline primitives CRUD (list/get/create/update/delete) and `/health` are never gated.
- **`Database.tenant_has_feature_flag(tenant_id, user_id, flag_name)`** — resolves a named feature
  flag for a tenant/user with precedence per-user override → per-tenant override → license default,
  honoring the flag's global master switch (`odb.feature_flags.enabled`).

### Changed
- **`OBJECTIFIED_PRIMITIVES_REGISTRY_GATING` operator switch (default off)** — when off, the gate is
  a pass-through and behavior is unchanged (every authenticated tenant reaches the advanced routes);
  when on, non-entitled tenants receive `403`. The `primitives-registry` flag is seeded by
  objectified-db migration `20260623-130000.sql` (bundled into the Paid and Sponsor plans, not Free)
  and is managed through the existing admin Feature-Flag panel.

## [1.0.20] - 2026-06-22

### Added
- **Import review: conflicts, dedupe, validation report (#3464)** — the Primitives import path no
  longer skips duplicates silently. New `app/primitives_review.py` provides the pure review logic:
  each imported definition is classified against the registry as **New** (nothing shares its `$id`),
  **Identical** (an existing type has the same `$id` and an identical schema), or **Conflict** (same
  `$id`, different schema), and a caller's per-type resolution choice (**keep** / **overwrite** /
  **rename**) is turned into a concrete commit decision by `decide()`.
- **`POST /v1/primitives/{tenant_slug}/import/review`** — a dry-run that writes nothing and returns
  the classification, a draft 2020-12 validation report, the `$ref` rewrites, the unresolved-ref
  mapping, and the resolution choices each conflict offers. This is the report the import wizard
  (#3469) renders before commit; the same classification drives the commit, so the committed result
  matches the review.

### Changed
- **`POST /v1/primitives/{tenant_slug}/import`** now honors review choices. New request fields:
  `dedupe` (default `true` — an Identical definition is skipped as a duplicate) and `resolutions`
  (a `name -> {action, new_name}` map). On commit, a conflict resolved `overwrite` updates the
  existing row in place, `rename` creates a copy under a new (slugified) name, and the default
  `keep` leaves the existing type but **surfaces** the conflict instead of dropping it. The import
  report gains `overwritten` / `renamed` / `identical` buckets (and their totals) plus a per-type
  `reviews` list, so the report can be shown to match the outcome; provenance counts reflect rows
  written (created + overwritten + renamed) vs. passed over (deduped + kept).
- Regenerated `openapi.{json,yaml}` for the new endpoint, request fields, and `ImportResolution`
  model; bumped to 1.0.20 (npm) / 1.0.90 (py).

## [1.0.19] - 2026-06-22

### Added
- **`$ref` rewrite + namespace/scope mapping (#3463)** — imported definitions now have their refs
  rewritten for their committed place in the registry instead of carrying document-local pointers.
  New `app/primitives_rewrite.py` provides `rewrite_import_schema()`, which (1) rewrites every
  intra-source pointer (`#/$defs/Money`, `#/definitions/Money`, `#/types/Money`) to a relative
  registry ref at the sibling's committed `$id` (`./money`, matching the `$id` leaf-slug; a deeper
  pointer like `#/$defs/Money/properties/c` is preserved as `./money#/properties/c`), and (2) maps a
  recognized string `format` (`email`, `uuid`, `uri`, `date`, `date-time`, `time`) to its seeded
  `std/v0/types` core type by injecting a relative `$ref` (mirroring the seed's
  `{"$ref": "../primitives/string", "format": "email"}` shape; an author's explicit `$ref` is never
  overridden). Because both rewrites produce ordinary registry-relative `$ref` values, the existing
  resolver (#3456) turns them into persisted `refs` edges with no separate internal-edge bookkeeping
  — so imported refs are stored relative and resolve via Epic 3, and core-format mapping resolves to
  the core type. `POST /v1/primitives/{tenant_slug}/import` applies this on commit for both the JSON
  Schema and type-def-bundle paths; a new `map_core_formats` request flag (default `true`) toggles
  the format mapping, and the import report gains a per-type `rewrites` map for the review table.

### Changed
- **Import commit no longer persists `internal` ref edges (#3463).** The `$defs`/`types` sibling
  pointers that #3461/#3462 captured as `{status: "internal"}` edges are now rewritten to relative
  registry refs and resolved like any other edge, so a committed primitive's `refs` carries only
  `resolved`/`unresolved` edges. (The staging path's per-candidate `internal_refs` metadata is
  unchanged.)

## [1.0.18] - 2026-06-22

### Added
- **Type-definition bundle importer (#3462)** — the `type-def-bundle` source kind now expands into
  many interlinked primitives instead of being enumerated shallowly. New `app/primitives_bundle.py`
  provides `parse_type_def_bundle()` (a parsed `.json`/`.yaml` bundle → discrete types) and
  `expand_zip_bundle()` (a `.zip` archive whose JSON/YAML members are each one type → a merged bundle
  document). A bundle reads its types from a `types` container (`$defs`/`definitions` accepted as
  equivalents); each type captures its **inter-type** `$ref` edges — refs at a sibling bundle type
  (`#/types/Money`, `#/$defs/Money`, `#/definitions/Money`) — as `internal` edges in the `refs` JSONB
  column for the rewrite stage (#3463), and is validated against draft 2020-12. The staging pipeline
  (`POST /import/stage`) now deep-parses bundle candidates (internal refs + per-type validation,
  matching the JSON Schema path), and `POST /v1/primitives/{tenant_slug}/import` with
  `source_kind='type-def-bundle'` commits a bundle of N types as N `odb.primitives` rows with their
  refs intact. A malformed bundle (no recognizable container, no usable types, bad/oversized/duplicate
  zip members) is rejected with a clear 400 / `BundleError` message. The per-definition commit loop is
  shared by the JSON Schema and bundle paths via `_commit_imported_definitions()`.

## [1.0.16] - 2026-06-22

### Added
- **Import pipeline core + ingestion (#3460)** — new `POST /v1/primitives/{tenant_slug}/import/stage`,
  the single orchestration path for all import sources. It ingests a document by one of four
  methods — `paste` / `file` (inline text), `url` (http/https fetch), or `git` (a file from a public
  github.com repo, reusing the repository-scan fetcher) — parses it as JSON **or** YAML, and detects
  the candidate types it carries, dispatched on source kind: `$defs`/`definitions` for `json-schema`
  (a bare document is one candidate), the `types`/`$defs` container for `type-def-bundle`, and
  `components.schemas` for `openapi`. The result is *staged*, not committed — each candidate carries
  its JSON Pointer and `$ref` count for the downstream parse (#3461/#3462), `$ref` rewrite (#3463),
  and conflict review (#3464) stages. Every staged import records an auditable `staged`
  `odb.primitive_imports` row (reusing #3448; no new table). The legacy paste-and-commit
  `POST /v1/primitives/{tenant_slug}/import` is unchanged. New `app/import_ingestion.py` (per-method
  fetch + JSON/YAML parse), `app/import_pipeline.py` (pure detection + staging), and
  `PrimitiveImportStageRequest` / `PrimitiveImportStageResult` / `StagedTypeCandidate` /
  `GitSourceLocator` models.

## [1.0.13] - 2026-06-22

### Added
- **Resolver API + dependency listing (#3459)** — new `POST /v1/types/{tenant_slug}/resolve`
  re-resolves every `$ref` dependency edge across the tenant's primitives against the *current*
  registry state and returns the per-primitive dependency listing the resolver UI (#3470) and
  Designer consume. Each stored edge's `resolved`/`unresolved` status is recomputed with the same
  existence test as save-time resolution (#3456) — so a target created since the edge was last
  computed now resolves and a deleted one now dangles — and the refreshed edges are persisted for
  the tenant's own primitives whose status changed ("re-resolve updates statuses"). Each resolved
  edge is enriched with its dependency target's id and name so the response is the dependency
  graph. The top-level counts mirror the coverage KPIs of `GET …/unresolved` (#3457/#3454), plus
  `reresolved_primitive_count` for how many primitives this pass updated. New `ResolveResponse` /
  `ResolvedPrimitiveRefs` / `ResolvedRefEdge` models and `app/type_resolver.py` (pure edge
  re-evaluation + dependency enrichment); system-core rows are listed but never written back.

## [1.0.12] - 2026-06-22

### Added
- **Unresolved-reference detection, flags & counts (#3457)** — a primitive's relative `$ref`
  edges are resolved and flagged `resolved`/`unresolved` on save/import (#3456); this adds the
  detection surface and the re-resolve-clears behavior on top of it. New
  `GET /v1/primitives/{tenant_slug}/unresolved` returns the tenant's total unresolved-edge count,
  the number of affected primitives, and a per-primitive breakdown (each with only its unresolved
  edges) — feeding the registry coverage/stats KPIs (#3454) and the resolver UI (#3470). New
  `UnresolvedRefsResponse`/`UnresolvedRefPrimitive` models and DB aggregates
  `count_unresolved_refs` / `get_primitives_with_unresolved_refs` (scoped to the caller's tenant,
  aggregating over the `odb.primitives.refs` JSONB column). Creating, importing, or repinning a
  primitive now runs a best-effort reconcile (`mark_refs_resolved_to_target`) that clears the
  unresolved flag on the tenant's other primitives whose dangling edge pointed at the new type's
  `$id`, so "fixing the target clears on re-resolve" without re-saving each dependent by hand.

## [1.0.11] - 2026-06-22

### Added
- **Type definition draft 2020-12 validation (#3452)** — the Primitives create, update, and
  import endpoints now strictly validate the supplied `schema` against the JSON Schema
  **draft 2020-12 meta-schema** server-side (new `app/schema_validation.py`, backed by the
  `jsonschema` library). An invalid schema is rejected at the REST boundary with HTTP 422 and a
  structured, field-level `errors` list (`path` / `message` / `keyword`) instead of being
  persisted. Valid types persist with a stable, derived JSON Schema `$id` (the
  `odb.primitives.schema_id` column) — an author-declared `$id` is honored, otherwise it is
  computed from the namespace base URI (or a stable tenant-default base) plus a url-safe slug of
  the name — and a stamped `draft` (default `2020-12`, read from `$schema`). The stored schema
  document is stamped with its `$id`/`$schema` so it is self-describing. `PrimitiveCreateRequest`/
  `PrimitiveUpdateRequest` gained optional `namespace`/`base_uri` placement fields (and `enabled`
  on update); `PrimitiveSchema` now exposes `schema_id`/`draft`/`namespace`/`base_uri`. The import
  path runs the same validator per `$defs` definition, recording invalid definitions in the import
  report (`error: "invalid_schema"` with `details`) without blocking the valid ones.

## [1.0.10] - 2026-06-22

### Added
- **Namespace CRUD API (#3451)** — added the type-registry namespace endpoints
  `GET/POST/PUT /v1/types/{tenant_slug}/namespaces` over the existing `objectified-db`
  connection. Namespaces (scope, base URI, version root, visibility, default) are persisted in
  the new `odb.type_namespaces` table, whose `namespace`/`base_uri` columns mirror those on
  `odb.primitives` (the type-count join key). `GET` lists system-core (`std/*`) namespaces plus
  the caller tenant's own, each with its tenant-scoped type count. `POST`/`PUT` require a tenant
  administrator and operate on tenant-owned namespaces only; the namespace path is immutable, and
  base URI / version root are derived from the path when omitted. System-core namespaces are
  platform-governed and read-only via the API (no platform-admin role is exposed), so creating or
  modifying one returns 403. Backed by `TypeNamespaceSchema`/`TypeNamespaceCreateRequest`/
  `TypeNamespaceUpdateRequest` models and `Database.list/get/create/update_type_namespace()` DAOs.

## [1.0.9] - 2026-06-22

### Added
- **Type-registry service skeleton + health (#3450)** — added an anonymous
  registry-layer health/ping endpoint `GET /v1/primitives/health` that reports the
  `objectified-db` connection status backing the registry's `odb.primitives` storage
  (overall `status`, `connection`, and whether the storage table is present). The existing
  tenant-scoped primitive CRUD/import endpoints are unchanged and remain authenticated, so
  current clients are unaffected. Backed by a new `Database.registry_ping()` probe and a
  `RegistryHealthResponse` model.

## [1.0.8] - 2026-06-22

### Added
- **Primitive import provenance & property binding (#3448)** — every
  `POST /v1/primitives/{tenant}/import` now records an auditable provenance row in the new
  `odb.primitive_imports` table (source kind, options, and a JSON outcome report with
  imported/skipped/errors) and marks imported primitives `source='imported'`. New read
  endpoints `GET /v1/primitives/{tenant}/imports` and `GET /v1/primitives/{tenant}/imports/{id}`
  expose the history and its report. Class properties gained a `primitive_id` foreign key to
  `odb.primitives` plus a stored `primitive_ref`, surfaced on the Designer read path so a bound
  property reloads its `$ref`; bindings are carried through class and version copies.

## [1.0.7] - 2026-06-22

### Removed
- **Separate type-registry database (#3447)** — removed the separate type-registry database
  and its dedicated REST connection, configuration, and health reporting. The type registry
  now lives in the main `objectified-db` database; `GET /health` reports only the core
  database status again. Reverses #3446.

## [1.2.0] - 2024-12-07

### Added
- **JSON Schema Endpoints**
  - New endpoint: `GET /v1/json/{tenant-slug}/{project-slug}/{version-slug}` - Get JSON Schema for all classes in a version
  - New endpoint: `GET /v1/json/{tenant-slug}/{project-slug}/{version-slug}/{class-name}` - Get JSON Schema for a single class
  - Content negotiation support for JSON and YAML formats (same as OpenAPI endpoints)
  - API key authentication for private versions (same as OpenAPI endpoints)
  - Full compliance with JSON Schema Draft 2020-12 specification
  - Schema definitions using $defs keyword
  - Automatic $id generation for schema identification
  - Support for nested and inline properties
  - Support for composition patterns (allOf, anyOf, oneOf)

- **New Python Module: `jsonschema_generator.py`**
  - Function: `generate_jsonschema_spec()` - Generate JSON Schema for all classes
  - Function: `generate_class_jsonschema_spec()` - Generate JSON Schema for single class
  - Reuses OpenAPI schema builder for consistency
  - Automatic format conversion to JSON Schema keywords

- **JSON Schema Documentation**
  - `docs/JSON_SCHEMA_ENDPOINTS.md` - Complete endpoint documentation
  - `docs/JSON_SCHEMA_QUICK_REFERENCE.md` - Developer quick reference guide

## [1.1.0] - 2024-12-07

### Added
- **Arazzo 1.0.1 Workflow Specification Endpoints**
  - New endpoint: `GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}` - Get workflows for all classes in a version
  - New endpoint: `GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}/{class-name}` - Get workflow for a single class
  - Content negotiation support for JSON and YAML formats (same as OpenAPI endpoints)
  - API key authentication for private versions (same as OpenAPI endpoints)
  - CRUD workflow generation (Create, Read, Update, Delete) for each class
  - Step dependency management and output capture
  - OpenAPI schema references in workflow payloads

- **New Python Module: `arazzo_generator.py`**
  - Function: `generate_arazzo_spec()` - Generate Arazzo spec for all classes
  - Function: `generate_class_arazzo_spec()` - Generate Arazzo spec for single class
  - Automatic CRUD workflow pattern generation
  - Step dependency chain creation
  - Success criteria definition

- **Comprehensive Documentation**
  - `README.md` - Complete project documentation with examples
  - `docs/ARAZZO_ENDPOINTS.md` - Detailed endpoint documentation
  - `docs/ARAZZO_QUICK_REFERENCE.md` - Developer quick reference guide
  - `docs/ARAZZO_IMPLEMENTATION.md` - Implementation summary and technical details

- **Test Suite**
  - `test_arazzo_endpoints.py` - Complete test coverage for Arazzo endpoints
  - Endpoint registration tests
  - Spec format validation tests
  - Workflow structure tests
  - Step dependency tests

### Changed
- Updated root endpoint (`/`) to list new Arazzo endpoints in the endpoint discovery response
- Updated `main.py` with new endpoint handlers and imports

### Technical Details
- Arazzo specification version: 1.0.1
- Maintains 100% parity with OpenAPI endpoints
- Same authentication and authorization patterns
- Same content negotiation behavior
- Same error handling and HTTP status codes

## [1.0.0] - 2024-11-XX

### Added
- Initial release
- OpenAPI 3.1.0 specification endpoints
- Swagger UI integration
- API key authentication
- Multi-tenant support
- Content negotiation (JSON/YAML)
- Database integration with PostgreSQL

[1.2.0]: https://github.com/your-org/objectified-rest/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/your-org/objectified-rest/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/your-org/objectified-rest/releases/tag/v1.0.0



