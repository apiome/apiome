# Apiome 07-2026 RC2

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features

- Governance: guide editor custom rules tab — author Spectral-compatible YAML rules in Monaco with JSON-schema completion (rule ids, `given`, `then`, and the six core functions), inline 422 validation markers on save, and a "Test against…" pane that dry-runs draft rules against any project/version without persisting (GOV-2.3, #4435)
- Mock server: latency & chaos injection — configurable delay ± jitter (capped at 30s) and error rate (0-100% of calls answered with a spec-defined 5xx, else problem+json 500) per route and per version default, edited in the Control Panel scenario dialog; a scenario can carry its own chaos block (chaos only in the "degraded" scenario), injected delays are concurrency-capped per tenant and count against rate/usage accounting (SIM-4.3, #4455)
- Mock server: scenario overrides — author named per-version scenarios ("quota-exceeded", "payment-declined") in the Control Panel, mapping operations to canned responses (status + headers + body) or per-call sequences; consumers switch with the `X-Mock-Scenario` header, sequences advance per `X-Mock-Session` (scenario+IP fallback) and reset per session; canned responses are validated against the spec's response schemas with an explicit off-spec flag, and definitions persist in `mock_settings` across republish and mock toggles (SIM-4.2, #4454)
- Browser Try It: scheme-aware auth helpers for bearer, apiKey, and basic credentials from the operation's `securitySchemes`; values stay in sessionStorage only, with a red proxy-transit warning on custom hosts (SIM-3.6, #4452)
- Mock server: stateful CRUD memory via `X-Mock-Session` — POST then GET/DELETE stay coherent per session with 1h sliding TTL, isolation, and size caps; in-memory default plus Postgres-backed store for multi-replica (SIM-4.1, #4453)
- Mock server: multi-protocol transports for AsyncAPI and gRPC — WebSocket/SSE event mocks emit schema-valid messages from the MFI canonical model; gRPC reflection mock answers unary and bounded streaming RPCs with synthesized protobuf payloads, with rate limiting and audit on both transports (SIM-4.4, #4456)
- Browser Try It: copy the composed request as curl, JavaScript fetch, or Python httpx snippets that update live with the form; credentials are replaced with placeholders like `$API_KEY`, never emitted as raw secrets (SIM-3.5, #4451)
- Browser Try It: example selector and "Generate sample" prefill request bodies from named OpenAPI examples or schema-driven synthesis via `POST /api/try-it/sample`, with source indication and content-type aware formatting (SIM-3.4, #4450)
- Mock server: private draft-version mocks — enable `mockEnabled` on unpublished drafts (`mockPrivate` + same base URL); `apiome-mock` serves the in-design spec only when the caller presents a valid tenant `X-Api-Key`, while anonymous traffic still gets 404/401 without revealing the draft (SIM-2.5, #4446)
- Browser: "Mock available" badge on public version pages when a version's mock is enabled, with the mock base URL, a copyable curl one-liner, and a Mock entry in the spec overview's server list; the URL is exposed in spec-viewer props for the upcoming try-it server picker (SIM-2.3, #4444)
- Mock server: `apiome-mock` wired into docker-compose (dev + production overlay with Caddy TLS), healthchecks, and the golden-path smoke step — publish → enable mock → GET /pets → assert 200/shape (SIM-1.6, #4421)
- Mock server: per-version enable/disable toggle (`PUT /v1/versions/{tenant}/{project}/{version}/mock`) with `mockEnabled` + computed `mockBaseUrl` on version GET; apiome-mock returns 404 problem+json when mock is disabled (SIM-2.1, #4422)
- Mock server: per-tenant rate limiting and monthly quotas keyed by license tier (free tier 5 rps / 10k req/mo), sampled mock hits in the tenant access audit trail, daily `mock_usage` rollups, and `GET /v1/mocks/{tenant}/usage` for Control Panel stats (SIM-1.5, #4420)
- Mock server: request validation and 4xx simulation validate path/query/header params and request bodies against the operation spec, return spec-declared 400/415 bodies when defined (otherwise problem+json), and support forced error paths via `Prefer: code=<status>` or `?__status=<status>` (SIM-1.4, #4419)
- Mock server: new `apiome-mock` FastAPI runtime with `/{tenant}/{project}/{version}/{path}` routing, published-spec resolution via Postgres, LRU caching with publish NOTIFY invalidation, and RFC 7807 problem+json infrastructure errors (SIM-1.1, #4416)
- Mock server: example-first response resolver returns author-written OpenAPI examples before schema synthesis, with `Prefer: example=<name>` selection and `Accept` media-type negotiation (SIM-1.2, #4417)
- Mock server: schema-driven data synthesis generates JSON-Schema-valid mock bodies with name heuristics, pattern support, deterministic `?__seed=` output, and depth/size caps as the resolver fallback tier (SIM-1.3, #4418)
- MCP Catalog: cataloger notes & annotations — per-endpoint human commentary authored by tenant users, stored separately from server-reported data, with full CRUD on the endpoint page and optional inclusion in report exports (`mcp_endpoint_notes`, MCAT-22.3)
- MCP Catalog: staleness & freshness reporting — flags endpoints overdue for re-discovery, in backoff/quarantine, or on a failing streak, with a last-known-good timestamp and freshness badge on catalog cards (`GET /v1/mcp/{tenant}/data-quality/freshness`, MCAT-22.2)
- MCP Catalog: duplicate / near-duplicate detection — advisory review list flags endpoints sharing a normalized URL, host (when not proven distinct by fingerprint), or identical capability surface; cross-tenant hints for matching published servers (`GET /v1/mcp/{tenant}/data-quality/duplicates`, MCAT-22.1)
- MCP Catalog: capability directory — browse every tool/resource/prompt across your catalog with filters for name, type, host, and visibility, paginated with links back to each owning server (`GET /v1/mcp/{tenant}/capabilities`, MCAT-21.4)
- MCP Catalog: saved searches & catalog views — persist named filter sets per user/tenant, re-run them from the catalog toolbar, and optionally pin as quick-access catalog views (`mcp_saved_searches`, MCAT-21.3)
- MCP Catalog: cross-server capability search — `GET /v1/mcp/{tenant}/capabilities/search` merges keyword (V127 FTS) and semantic (V149 pgvector) matches across the tenant catalog, grouped by owning server and ranked relevance→grade (MCAT-21.2)
- Export: Protobuf multi-file packaging — the proto3 emitter emits one `.proto` per package with cross-package `import` lines; the full bundle is validated via `buf build` (MFX-12.4)
- Export: `apiome export <format> <artifact>` — generic CLI export via the async job pipeline (submit, poll, download); writes a single file or unpacks a zip bundle to `--out`; supports `--option`, `--force`, `--confirm`, and `--json` (MFX-8.1)
- Export: CLI fidelity report — every `export` verb prints the server advisory (MFX-2.4) and a concise per-construct loss table on stderr; lossy/types-only exports exit non-zero unless `--force` or the user confirms at an interactive prompt (MFX-8.2)
- Export: emitted-artifact validation gate — completed export jobs now surface a structured validation report (`valid` / `invalid` / `skipped` / `not_applicable`) alongside the fidelity envelope; invalid output blocks delivery with actionable parser findings (MFX-5.3)
- Export: Emitter registry REST target list — `GET /v1/export/{tenant}/targets` enumerates every registered emitter with descriptor, capability profile, `options_schema` and `default_options`, and a per-source fidelity tier badge (`lossless`/`lossy`/`types-only`) computed without emitting (MFX-1.2)
- Browser: public export downloads are rate-limited and size-capped on the server; the dialog shows clear messages when throttled or the artifact is too large (MFX-7.3)
- Browser: public export dialog shows the full fidelity advisory + per-construct report, matching the ADE export flow (MFX-7.2)
- Export: `apiome export avro` writes Avro `.avsc` with the honest fidelity report; UI export-target metadata maps avro/avsc to Monaco `json` + `.avsc` download names (MFX-19.5)
- Export: Avro Schema Registry subjects — per-type Confluent subjects on each `.avsc` (`RecordNameStrategy` default; `TopicNameStrategy` / `TopicRecordNameStrategy` via emit options); nullable optional fields without source defaults get synthesized evolution defaults (MFX-19.3)
- Export: Avro fidelity pack — operations/channels critical DROP with "only data schemas are exported"; constraints DROP; unions OK when shape allows else APPROX; optional fields APPROX as `["null", T]` unions; evolution defaults SYNTH (MFX-19.2)
- Export: Avro emitter — canonical model → validated `.avsc` per named type (records, enums, unions, maps, fixed/logical scalars); nullability as `["null", T]` unions; date/timestamp/uuid/decimal logical types; names sanitized to Avro rules (MFX-19.1)
- Export: `apiome export graphql` writes GraphQL SDL with the honest fidelity report; UI export-target metadata maps graphql/gql/sdl to Monaco `graphql` + `.graphql` download names (MFX-13.5)
- Export: GraphQL validate + round-trip — emitted SDL is checked with `build_schema`/`validate_schema`, re-imported through the MFI GraphQL parser, and diffed against the source; predicted fidelity losses corroborated and divergences flagged (MFX-13.4)
- Export: GraphQL fidelity pack — REST HTTP method/path/status/headers are reported as APPROX when reframing to Query/Mutation fields (HTTP semantics have no GraphQL representation); validation constraints approximate as custom scalars; oneOf/unions report OK when member shapes allow (MFX-13.3)
- Export: GraphQL input/output type splitting — cross-paradigm request bodies and object-typed arguments synthesize deduplicated `{Name}Input` types so emitted SDL never uses output objects as inputs; synthesized inputs reported in the fidelity envelope (MFX-13.2)
- Export: GraphQL SDL emitter — canonical model → valid SDL via `graphql-core` `print_schema`; preserves nullability/list wrappers; Graph-native sources round-trip; REST sources map GET→Query and write verbs→Mutation (MFX-13.1)
- Export: `apiome export grpc` writes a proto3 `.proto` document with the honest fidelity report; UI export-target metadata maps protobuf/gRPC/proto3 to Monaco `protobuf` + `.proto` download names (MFX-12.5)
- Export: Protobuf fidelity pack — unions, nullability, constraints, inheritance, and arbitrary JSON losses are predicted as APPROX/SYNTH (not silent DROPs) when exporting OpenAPI/GraphQL sources to proto3; pub/sub operations reframed as unary rpc (MFX-12.3)
- Export: Stable protobuf field-number assignment — synthesized field numbers persist per artifact and are reused on re-export; new fields get the next free number honouring `reserved` ranges; reported as SYNTH in the fidelity report (MFX-12.2)
- Export: Per-target emit options — each registered emitter declares a Pydantic options model with JSON Schema + validated defaults on the registry target list; OpenAPI 3.1 and sample targets ship reference option sets (MFX-1.4)
- Export: Refactored existing OpenAPI export behind the Emitter SPI — catalog conversion and future export surfaces resolve emitters through the registry instead of direct emitter imports (MFX-1.3)
- Export: Emitter SPI + capability/fidelity profile — export targets register with descriptor metadata (key/label/icon/paradigm/single-vs-multi-file/toolchain), static capability profiles for fidelity prediction, and multi-file `EmitResult` envelopes; OpenAPI 3.1 and a no-op sample target ship as reference emitters (MFX-1.1)
- Import: OpenAPI-family conformance matrix (Swagger 2.0, OAS 3.0/3.1/3.2, Arazzo) runs in CI — detect/normalize agreement, entity counts, fingerprint stability, and Project routing are regression-gated (MFI-30.4)
- Import: OpenAPI 3.2 documents (QUERY method, additionalOperations, hierarchical tags) now import, normalize, lint, and publish through the multi-format SPI; fidelity preview notes 3.2→3.1 conversion
- Catalog: Shows the number of versions in each card

## Bug Fixes

- Import: Arazzo workflow documents now import through the multi-format SPI with canonical model, lint, and step-level diff support
- Browser: Updated to show MCP Catalog
- Browser: Updated to show activity spinner when searching
- Catalog: Implementation of the catalog to import API sources other than OpenAPI and Arazzo
- Catalog: Implements gRPC/Protobuf/GraphQL/AsyncAPI import cataloging
- CLI: Corrected Swagger 2.0 support in auto import mode
- CLI: Adds --force option to import so that warnings do not prevent publication
- CLI: Import shows correct elapsed time for an import job
- CLI: Adds "--import-timeout (seconds)" option to import to override 120 second timeout
- CLI: Adds MCP registration functionality to the system
- DB: Optimizations made to increase speed for import processing
- DB: Implements catalog storage and indexing
- DB: Job status table was created for import/export jobs
- Import: Corrected import for Swagger responses in paths to capture the schema properly for array items
- Import: Import speed greatly improved
- Import: Special cases with unicode characters are now properly handled
- Import: Better duplication checks - now compares project and version IDs before rejecting
- Import: Fixes publish flag when importing via CLI
- Import: Publish uses short note via description, title, or slug and version if not provided
- Import: Updates import service to include benchmarking output
- Import: Fixes linting problem in rare cases during import
- Import: Corrects base ref and $ref external dereferencing
- Import: Updating class creation step to increase speed using transactions and commits in groups
- Import: Catalog import dialog accepts `.zip`/`.tar.gz` archives for multi-file gRPC/GraphQL/AsyncAPI sources (MFI-29.1)
- Import: gRPC, GraphQL, and AsyncAPI adapters accept multi-document fileset input — split SDL, proto trees, and AsyncAPI suites resolve cross-file refs with identical fingerprints to pre-flattened imports (MFI-29.2)
- Import: Fixed to use job table for status in cases where server could be round-robin deployed
- Import/Export: Adds Thrift support
- Import/Export: Adds ConnectRPC support
- Import/Export: Adds FlatBuffers support
- Import/Export: Adds Cap'n Proto support
- Import/Export: Adds WSDL/SOAP support
- Import/Export: Adds RAML support
- Import/Export: Adds WADL support
- Import/Export: Adds OpenRPC support
- Import/Export: Adds Avro support
- Import/Export: Adds XML-RPC support
- Import/Export: Adds XSD support
- Import/Export: Adds Postman collection support
- Import/Export: Adds CloudEvents support
- Import/Export: Adds Smithy support
- Import/Export: Adds API Blueprint support
- Import/Export: Adds ASN.1 support
- REST: Swagger 2.0 documents normalize into the canonical model through the import SPI (MFI-30.1), closing the detect-without-normalize gap for cross-format diff and catalog persistence
- Projects: Now displays quality and linting information in each project
- UI: Fixes Published Versions viewing of OpenAPI and Arazzo URLs
- UI: Fixes Published Versions list so versions starting with a "v" don't duplicate and show "vv"
- UI: Adds the ability to import MCP servers as an input for API cataloging
- UI: Adds MCP linting and scoring based on interally set criteria
- UI: Repositories are no longer in preview
- UI: MCP entries provide a small summary once imported
- UI: Updated MCP registries to be published either public or private
- UI: Applied Fable 5 to improve overall UI additions
- UI: Improved Profile layout
- UI: Fixed sidebar so that "Sunset Timeline" doesn't also highlight Projects at the same time
- UI: Fixed sidebar to be static with scrollable content to the right-hand side
- Naming: Renamed the project to Apiome

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: June 23, 2026*

