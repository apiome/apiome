# Apiome: Test Lab - Feature Roadmap

> Automated API and schema testing platform with synthetic data generation, contract testing, performance benchmarking, and chaos engineering. Test Lab ensures schemas and APIs behave correctly, perform well under load, and degrade gracefully under failure conditions—all driven by Apiome schema definitions.
>
> **Revenue Model**: Per-test-run pricing (free tier: 100 runs/month), monthly active schema limits, enterprise unlimited
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, Redis (job queues), K6/Artillery for load testing, Docker for test isolation, OpenAPI 3.1

---

## MVP Definition

- Consumer-driven contract test definition and provider verification
- Breaking change detection between schema versions with impact analysis
- AI-powered synthetic data generation from schema definitions
- PII-safe data masking with configurable strategies
- Load testing with schema-aware payload generation
- Test suite management with run history and trend visualization
- CI/CD integration via REST API for automated test execution
- Test results dashboard with pass/fail summaries and drill-down

---

## Epic 1: Contract Testing Engine

### Summary Table

| #   | Title                                  | Description                                                                   | Labels                                     | Parallel |
|-----|----------------------------------------|-------------------------------------------------------------------------------|--------------------------------------------|----------|
| 1.1 (#1295) | Contract Definition Data Model         | Schema for consumer contracts, provider specs, and compatibility records       | `enhancement`, `mvp`, `test-lab`, `rest`   | Yes      |
| 1.2 (#1296) | Consumer Contract Authoring            | UI and API for consumers to define expected request/response contracts         | `enhancement`, `mvp`, `test-lab`           | No       |
| 1.3 (#1297) | Provider Verification Engine           | Verify provider APIs satisfy all registered consumer contracts                | `enhancement`, `mvp`, `test-lab`, `rest`   | No       |
| 1.4 (#1298) | Breaking Change Detection              | Compare schema versions to detect backward-incompatible changes               | `enhancement`, `mvp`, `test-lab`, `rest`   | Yes      |
| 1.5 (#1299) | Contract Compatibility Matrix          | Dashboard showing provider-consumer compatibility across all contracts        | `enhancement`, `test-lab`                  | No       |

### Detailed Issue Descriptions

#### 1.1 (#1295) — Contract Definition Data Model

The contract testing data model captures the relationships between API consumers and providers through explicit contracts. A `contract` record defines expectations from a consumer's perspective: which provider API it depends on, expected request format (HTTP method, path pattern, headers, body schema), expected response format (status codes, body schema, headers), and metadata (consumer name, version, owner, creation date).

Contracts reference Apiome schema definitions for request and response bodies, creating a strong link between schema governance and API testing. The `contract_verification` table records each verification run: which contract was tested, against which provider version, the result (pass/fail), failure details, and execution timestamp. A `compatibility_record` table tracks the compatibility matrix between consumer contract versions and provider schema versions.

The data model supports contract grouping via `contract_suite` for organizing related contracts (e.g., all contracts from "Order Service" consumer). Suites enable batch verification and aggregated reporting.

**Acceptance Criteria:**
- Database migration creates contract, contract_suite, contract_verification, and compatibility_record tables
- Contract stores consumer expectations: HTTP method, path, request_schema_ref, response_schema_ref, expected_status_codes
- Contracts reference Apiome schema IDs for body definitions (foreign key to schema system)
- Contract suite groups related contracts with metadata: suite_name, consumer_name, description
- All tables tenant-scoped with proper indexes on (tenant_id, provider_schema_id) and (tenant_id, consumer_name)
- OpenAPI 3.1 component schemas defined for all contract-related entities

**Tech Stack:** PostgreSQL migrations, foreign keys to Apiome schema tables, OpenAPI 3.1 component definitions

Part of Epic: Contract Testing Engine

---

#### 1.2 (#1296) — Consumer Contract Authoring

The contract authoring interface enables API consumers to define their expectations in a structured, verifiable format. The authoring flow walks through four steps: (1) Select the provider schema/API being consumed, (2) Define request expectations (method, path template, headers, body shape using Apiome schema subset), (3) Define response expectations (status codes, body shape, required fields), and (4) Provide sample interactions (example request/response pairs for documentation).

The interface presents the provider's full schema in a reference panel so consumers can select the subset of fields they actually depend on—this is the key insight of consumer-driven contracts. Rather than testing the entire schema, contracts test only what the consumer uses, making them resilient to additive changes. The UI lets consumers click fields in the provider schema to include them in their contract, building the expected schema interactively.

Contracts can also be authored via the REST API (`POST /api/v1/test-lab/contracts`) with the full contract specification as JSON, enabling programmatic contract generation from consumer codebases. A Pact-compatible import endpoint accepts Pact V3/V4 JSON files for teams migrating from existing Pact-based setups.

**Acceptance Criteria:**
- Step-by-step authoring wizard with provider schema reference panel
- Field selection UI: click fields in provider schema to include in consumer contract (subset selection)
- Request expectation definition: HTTP method, path (with parameter placeholders), header requirements, body schema
- Response expectation definition: expected status codes, body schema (subset of provider), required headers
- REST API: `POST /api/v1/test-lab/contracts` for programmatic contract creation with JSON spec
- Pact import: `POST /api/v1/test-lab/contracts/import/pact` accepts Pact V3/V4 JSON and creates contracts

**Tech Stack:** NextJS page (`app/(platform)/test-lab/contracts/new/page.tsx`), Radix UI Dialog for wizard steps, Radix UI Checkbox for field selection, REST API with OpenAPI 3.1

Part of Epic: Contract Testing Engine

---

#### 1.3 (#1297) — Provider Verification Engine

Provider verification is the automated process of testing whether a provider's API implementation satisfies all registered consumer contracts. When triggered (manually, on schedule, or via CI/CD), the engine collects all contracts for the specified provider, generates test requests based on contract expectations, executes them against the provider's API (or mock), and validates responses against the contract's expected format.

The verification process for each contract: (1) Build the HTTP request from the contract's request definition (method, path, headers, body with synthetic data matching the request schema), (2) Send the request to the provider's API endpoint (configurable base URL per environment), (3) Validate the response status code against expected values, (4) Validate the response body against the contract's expected schema using JSON Schema validation, (5) Record the result as a `contract_verification` entry.

For teams not ready to test against live APIs, the engine supports mock-based verification: it validates that the provider's Apiome schema is a superset of each consumer contract's expected schema without making HTTP calls. This structural verification catches breaking changes at the schema level before deployment.

**Acceptance Criteria:**
- Verification endpoint: `POST /api/v1/test-lab/contracts/verify` accepts provider_schema_id and target_base_url
- Generates HTTP requests from contract request definitions with synthetic body data
- Validates response status codes and body against contract expected schema
- Mock-based verification: structural compatibility check without HTTP calls (schema superset validation)
- Verification results stored per contract with: pass/fail, failure_details (field path, expected vs actual), duration
- Batch verification: verify all contracts for a provider in a single run with aggregate pass/fail summary

**Tech Stack:** NextJS API routes, HTTP client for live verification, JSON Schema validation for structural checks, background worker for batch verification, OpenAPI 3.1

Part of Epic: Contract Testing Engine

---

#### 1.4 (#1298) — Breaking Change Detection

Breaking change detection compares two versions of an Apiome schema and identifies backward-incompatible changes that would break existing consumers. The analysis categorizes changes into three severity levels: breaking (field removed, type changed, required field added), warning (field deprecated, enum value removed, constraint tightened), and info (field added, description changed, example updated).

The detection engine performs structural diff analysis: it walks both schema trees in parallel, comparing each field's type, constraints, required status, and nested structure. For each difference found, it applies compatibility rules to classify the change. When consumer contracts exist, the engine cross-references breaking changes against actual consumer dependencies—a field removal is only breaking if at least one consumer contract references that field.

The output is a `compatibility_report` containing: the two versions compared, a list of all changes with severity and description, affected consumer contracts (if any), and a recommended migration path for each breaking change. The report is available via API and rendered as a visual diff in the UI with color-coded severity indicators.

```
┌────────────────────────────────────────────────────────┐
│           Breaking Change Report                        │
│           Schema: Order  v2.1.0 → v3.0.0               │
├────────────────────────────────────────────────────────┤
│                                                        │
│  🔴 BREAKING (2)                                       │
│  ├─ /properties/payment_method  REMOVED                │
│  │  Consumers affected: checkout-service, billing-svc  │
│  └─ /properties/total/type  number → string            │
│     Consumers affected: analytics-service              │
│                                                        │
│  🟡 WARNING (1)                                        │
│  └─ /properties/status/enum  removed: "pending"        │
│     Consumers affected: order-tracker                  │
│                                                        │
│  🟢 INFO (3)                                           │
│  ├─ /properties/metadata  ADDED (optional object)      │
│  ├─ /properties/notes/description  Updated             │
│  └─ /properties/shipping/examples  Added 2 examples    │
│                                                        │
│  Summary: 2 breaking · 1 warning · 3 info              │
│  Recommendation: Major version bump required           │
└────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Comparison endpoint: `POST /api/v1/test-lab/breaking-changes` accepts source_version_id and target_version_id
- Change classification: breaking (red), warning (yellow), info (green) with clear category descriptions
- Cross-reference with consumer contracts: report which consumers are affected by each breaking change
- Recommended version bump: patch (info only), minor (warnings, no breaking), major (any breaking)
- Compatibility report API response includes full change list, affected consumers, and migration suggestions
- Visual diff UI with color-coded severity, expandable change details, and affected consumer list

**Tech Stack:** JSON Schema structural diff engine, PostgreSQL for report storage, NextJS page for visual diff, Radix UI Accordion for expandable change details

Part of Epic: Contract Testing Engine

---

#### 1.5 (#1299) — Contract Compatibility Matrix

The compatibility matrix provides an at-a-glance view of which consumer contract versions are compatible with which provider schema versions. This dashboard is essential for release planning: before deploying a new provider version, teams can see which consumers will break and need updates first.

The matrix view renders as a table: rows are consumer contracts (grouped by consumer service), columns are provider schema versions (most recent first), and cells show compatibility status (green checkmark, red X, yellow warning, gray untested). Clicking a cell drills down to the specific verification result showing which contract assertions passed and which failed.

The matrix automatically updates as new verifications are run. A "Release Readiness" view summarizes compatibility for a specific provider version: number of consumers compatible, number breaking, and a go/no-go recommendation. Notifications can be configured to alert consumer team owners when a new provider version breaks their contracts.

**Acceptance Criteria:**
- Matrix view with consumer contracts as rows and provider schema versions as columns
- Cell status indicators: compatible (green), breaking (red), warning (yellow), untested (gray)
- Click-to-drill-down from matrix cell to specific verification result details
- "Release Readiness" summary for a selected provider version: compatible count, breaking count, recommendation
- Notification to consumer owners when new provider version breaks their contracts
- Matrix data API: `GET /api/v1/test-lab/compatibility-matrix?providerId={id}` with version range filter

**Tech Stack:** NextJS page (`app/(platform)/test-lab/compatibility/page.tsx`), Radix UI Table for matrix, Radix UI Tooltip for cell details, notification service integration

Part of Epic: Contract Testing Engine

---

## Epic 2: Synthetic Data Generator

### Summary Table

| #   | Title                                | Description                                                                     | Labels                                      | Parallel |
|-----|--------------------------------------|---------------------------------------------------------------------------------|---------------------------------------------|----------|
| 2.1 (#1301) | Schema-Driven Data Generation Engine | Generate realistic data from Apiome schema definitions using AI and rules  | `enhancement`, `mvp`, `test-lab`, `rest`, `ai-generated` | Yes      |
| 2.2 (#1302) | PII Masking & Safe Data Strategies   | Configurable data anonymization for sensitive field types                        | `enhancement`, `mvp`, `test-lab`, `rest`    | Yes      |
| 2.3 (#1303) | Edge Case & Boundary Value Generator | Generate adversarial test data targeting schema constraints and boundaries       | `enhancement`, `test-lab`, `rest`           | Yes      |
| 2.4 (#1304) | Locale-Aware Data Generation         | Generate culturally appropriate data for international testing                  | `enhancement`, `test-lab`, `rest`           | Yes      |
| 2.5 (#1305) | Data Generation Profiles & Presets   | Save and reuse generation configurations for consistent test data               | `enhancement`, `test-lab`, `rest`           | No       |

### Detailed Issue Descriptions

#### 2.1 (#1301) — Schema-Driven Data Generation Engine

The synthetic data generator produces realistic test data by analyzing Apiome schema definitions and generating values that conform to all type constraints, validation rules, and semantic expectations. The engine combines rule-based generation (using schema constraints: type, format, minimum, maximum, pattern, enum) with AI-powered semantic generation (using field names and descriptions to infer realistic content).

For a field named `email` of type `string` with format `email`, the engine generates realistic email addresses. For a field named `company_name` of type `string`, the AI component generates plausible company names rather than random strings. The generator understands nested structures, generating coherent objects where related fields make sense together (e.g., a `city` field value that matches the `state` field value in an address object).

Generation supports configurable volume: generate 1 record for manual inspection, 100 for functional testing, or 100,000+ for load testing. Batch generation runs asynchronously for large volumes, with progress tracking. The output format matches the Apiome instance data structure, enabling generated data to be directly imported as test instances.

**Acceptance Criteria:**
- Generation endpoint: `POST /api/v1/test-lab/generate` accepts schema_id, count, and generation_options
- Rule-based generation respects all JSON Schema constraints: type, format, min/max, pattern, enum, required
- AI-powered semantic generation uses field names and descriptions for realistic values (via Ollama)
- Coherent object generation: related fields within an object produce logically consistent values
- Batch generation for count > 1000 runs asynchronously with progress polling endpoint
- Output conforms to Apiome instance data format for direct import into test environments

**Tech Stack:** NextJS API routes, Ollama for AI-powered generation, Faker.js for common data types, background worker for batch generation, OpenAPI 3.1

Part of Epic: Synthetic Data Generator

---

#### 2.2 (#1302) — PII Masking & Safe Data Strategies

When generating test data or working with production data copies, sensitive fields must be anonymized to prevent PII exposure in non-production environments. The PII masking module provides configurable strategies for different field types: redaction (replace with `***`), hashing (deterministic one-way hash preserving referential integrity), format-preserving encryption (maintain format while changing value), synthetic replacement (generate fake but realistic alternative), and partial masking (show first/last N characters, mask middle).

Field sensitivity is detected automatically by analyzing field names, types, and descriptions against a configurable sensitivity dictionary (e.g., fields named `ssn`, `social_security`, `tax_id` are flagged as high-sensitivity). Users can override auto-detection to add or remove sensitivity flags. Masking strategies are configured per sensitivity level: high (hash or redact), medium (format-preserving encrypt), low (synthetic replace).

Deterministic masking ensures the same input always produces the same masked output within a masking session, preserving foreign key relationships across tables. If `customer_id: 12345` maps to `customer_id: ABCDE`, all references to 12345 across all generated data are consistently mapped to ABCDE.

**Acceptance Criteria:**
- Masking strategies: redaction, deterministic hashing, format-preserving encryption, synthetic replacement, partial masking
- Auto-detection of PII fields using configurable sensitivity dictionary (name patterns, JSON Schema formats)
- Override UI for adding/removing sensitivity flags on specific fields
- Strategy configuration per sensitivity level (high/medium/low) at tenant scope
- Deterministic masking: same input produces same output within a session for referential integrity
- Masking API: `POST /api/v1/test-lab/mask` accepts data array and masking configuration, returns masked data

**Tech Stack:** NextJS API routes, format-preserving encryption library, deterministic hashing (HMAC-SHA256 with session key), Radix UI Select for strategy configuration

Part of Epic: Synthetic Data Generator

---

#### 2.3 (#1303) — Edge Case & Boundary Value Generator

Testing schema validation requires data that intentionally pushes boundaries and violates constraints. The edge case generator analyzes schema constraints and produces adversarial test data designed to exercise boundary conditions: minimum and maximum values (exactly at boundary, one below, one above), string length limits, empty strings, null values for optional fields, maximum array lengths, deeply nested objects, special characters (unicode, control characters, emoji, SQL injection patterns, XSS payloads).

The generator produces two categories of data: valid edge cases (conform to schema but test boundaries) and invalid edge cases (deliberately violate constraints to test rejection). For a `string` field with `minLength: 3` and `maxLength: 50`, the generator produces: empty string (invalid), 2-char string (invalid), 3-char string (valid boundary), 50-char string (valid boundary), 51-char string (invalid), and string with special characters (valid but tricky).

Output is organized as a test data matrix showing each field, the edge case category, the generated value, and whether it should pass or fail validation. This matrix can be exported as a test fixture for use in unit tests.

**Acceptance Criteria:**
- Boundary value analysis: generate min, min-1, min+1, max, max-1, max+1 for numeric and string length constraints
- Null/empty/undefined generation for optional fields to test null handling
- Special character sets: unicode, control chars, emoji, SQL injection patterns, XSS payloads, newlines
- Two output categories: `valid_edge_cases` (should pass schema validation) and `invalid_edge_cases` (should fail)
- Test data matrix output: field_path, edge_case_type, value, expected_validation_result (pass/fail)
- Generation API: `POST /api/v1/test-lab/generate/edge-cases` accepts schema_id and returns categorized test data

**Tech Stack:** NextJS API routes, JSON Schema constraint analysis, predefined adversarial data libraries, Radix UI Table for matrix view

Part of Epic: Synthetic Data Generator

---

#### 2.4 (#1304) — Locale-Aware Data Generation

International applications require test data that reflects locale-specific formats and cultural conventions. The locale-aware generator extends the base generator with locale-specific providers for: addresses (country-specific format, real city/state/postal code combinations), phone numbers (country code, national format), names (culturally appropriate first/last names), dates (locale date format: MM/DD/YYYY vs DD/MM/YYYY vs YYYY-MM-DD), currencies (symbol placement, decimal separator, thousands grouping), and government IDs (SSN format for US, NI number for UK, Aadhaar for India).

Users select one or more target locales when generating data. Multi-locale generation produces a mixed dataset where each record randomly selects from the configured locales, simulating a multinational user base. Locale-specific validation rules are applied: a US phone number is validated against the US format, not a generic pattern.

The system ships with built-in providers for 20+ locales and supports custom locale definitions for additional regions. Custom locales specify field formats, example value pools, and validation patterns. The locale library is extensible via the REST API.

**Acceptance Criteria:**
- Locale selection parameter on generation endpoint: `locale` accepts ISO 639-1 codes (en-US, ja-JP, de-DE, etc.)
- Built-in providers for 20+ locales covering: names, addresses, phone numbers, dates, currencies, government IDs
- Multi-locale mode: specify multiple locales with distribution percentages for mixed datasets
- Locale-specific validation: generated values conform to locale formatting rules
- Custom locale API: `POST /api/v1/test-lab/locales` for adding custom locale definitions
- Generated data includes `_locale` metadata field for filtering and locale verification

**Tech Stack:** Faker.js locale support, custom locale providers, NextJS API routes, Radix UI Select for locale picker with multi-select support

Part of Epic: Synthetic Data Generator

---

#### 2.5 (#1305) — Data Generation Profiles & Presets

Data generation profiles save a complete generation configuration (schema, count, locale, masking settings, edge case inclusion, custom overrides) as a reusable preset. This enables consistent test data generation across team members and CI/CD pipelines. A profile named "Order Service Load Test" might specify: Order schema v2.3, 10,000 records, en-US locale, PII masking enabled, include 5% edge cases.

The profile library supports three scopes: personal (visible to the creating user), team (shared within a team), and tenant (available to all users in the tenant). Profiles can be parameterized with variables (e.g., record count as a variable that CI pipelines can override). A profile can reference other profiles for linked schemas—generating orders and their associated customers in a single run with referential integrity.

The API supports triggering generation from a profile: `POST /api/v1/test-lab/generate/profile/{profileId}` with optional parameter overrides. This enables CI/CD pipelines to generate test data as a step in their workflow without embedding complex generation configuration in pipeline definitions.

**Acceptance Criteria:**
- Profile CRUD API: `POST /api/v1/test-lab/profiles` with full generation configuration
- Profile scopes: personal, team, tenant with appropriate access control
- Parameterized profiles: define variables (e.g., `{{count}}`) with defaults, overridable at generation time
- Linked profile generation: reference other profiles for related schemas with referential integrity
- Profile execution endpoint: `POST /api/v1/test-lab/generate/profile/{profileId}` with parameter overrides
- Profile library UI with search, filter by scope, and "Generate Now" action button

**Tech Stack:** NextJS page (`app/(platform)/test-lab/profiles/page.tsx`), Radix UI Dialog for profile creation, PostgreSQL for profile storage, REST API with OpenAPI 3.1

Part of Epic: Synthetic Data Generator

---

## Epic 3: Performance & Chaos Testing

### Summary Table

| #   | Title                              | Description                                                                    | Labels                                   | Parallel |
|-----|------------------------------------|--------------------------------------------------------------------------------|------------------------------------------|----------|
| 3.1 (#1307) | Load Test Configuration & Runner   | Configure and execute load tests with schema-aware payload generation          | `enhancement`, `test-lab`, `rest`        | Yes      |
| 3.2 (#1308) | Stress Testing & Breakpoint Analysis | Progressive load increase to find system breaking points and degradation curves | `enhancement`, `test-lab`, `rest`       | No       |
| 3.3 (#1309) | Latency Tracking & Benchmarking    | Track response time percentiles (p50, p95, p99) with historical comparison     | `enhancement`, `test-lab`, `rest`        | Yes      |
| 3.4 (#1310) | Chaos Engineering & Fault Injection | Schema mutation testing and fault injection for resilience validation          | `enhancement`, `test-lab`, `rest`        | Yes      |
| 3.5 (#1311) | Performance Report Generation      | Automated performance report with trends, regressions, and recommendations    | `enhancement`, `test-lab`                | No       |

### Detailed Issue Descriptions

#### 3.1 (#1307) — Load Test Configuration & Runner

The load test runner executes configurable load tests against API endpoints using schema-aware payloads generated from Apiome schema definitions. A load test configuration specifies: target endpoint(s), HTTP method(s), authentication, payload schema (from Apiome), virtual user count, ramp-up pattern (linear, step, spike), test duration, and success criteria (max error rate, max p95 latency).

The runner generates unique request payloads for each virtual user request using the synthetic data generator (Epic 2), ensuring realistic and varied test traffic rather than replaying the same payload. Payloads conform to the Apiome schema, testing both the API's functionality and its schema validation under load.

Test execution runs in isolated Docker containers to prevent interference between concurrent tests. The runner streams real-time metrics (requests/second, error rate, latency percentiles) to the UI via server-sent events. Results are stored for historical comparison. Tests can be triggered via the UI or the REST API for CI/CD integration.

**Acceptance Criteria:**
- Load test configuration: target URL, method, auth, schema_id, virtual_users, ramp_pattern, duration, success_criteria
- Schema-aware payload generation: each request uses a unique payload conforming to the Apiome schema
- Ramp patterns: linear (gradual increase), step (increase by N every M seconds), spike (sudden burst)
- Real-time metrics streaming during test execution: RPS, error rate, latency (p50, p95, p99)
- Execution API: `POST /api/v1/test-lab/load-tests/{id}/run` triggers test, returns run_id for monitoring
- Results stored per run with full metrics timeseries for historical comparison

**Tech Stack:** K6 or Artillery for load generation, Docker for test isolation, server-sent events for real-time metrics, NextJS API routes, PostgreSQL for results storage

Part of Epic: Performance & Chaos Testing

---

#### 3.2 (#1308) — Stress Testing & Breakpoint Analysis

Stress testing extends load testing by progressively increasing load until the system degrades or fails, identifying the breaking point and degradation characteristics. The stress test runner starts at a baseline load (e.g., 10 RPS) and increases by a configurable step (e.g., +10 RPS every 60 seconds) while continuously monitoring response times, error rates, and system health.

The breakpoint analyzer watches for degradation signals: when p95 latency exceeds a threshold, when error rate exceeds a threshold, or when the system stops responding. It marks the load level at which degradation begins ("soft limit") and the level at which the system fails ("hard limit"). The degradation curve is plotted as a chart showing load level on the X-axis and latency/error rate on the Y-axis.

Results include recommendations: "Your API handles 500 RPS with <200ms p95 latency. At 600 RPS, latency spikes to 1.2s. At 750 RPS, error rate exceeds 5%. Recommend capacity planning for 500 RPS with 20% headroom." Historical stress test results enable tracking capacity changes across deployments.

**Acceptance Criteria:**
- Stress test configuration: start_rps, step_rps, step_interval_seconds, max_rps, degradation_thresholds
- Automatic breakpoint detection: identify soft limit (degradation onset) and hard limit (system failure)
- Degradation curve chart: load (X-axis) vs latency and error rate (dual Y-axis) with marked breakpoints
- Test stops automatically when hard limit is reached or max_rps is achieved
- Results include capacity recommendation text based on observed breakpoints
- Historical comparison: overlay current run's degradation curve against previous runs

**Tech Stack:** K6/Artillery with progressive load scripting, chart library for degradation curve, NextJS page, PostgreSQL for results

Part of Epic: Performance & Chaos Testing

---

#### 3.3 (#1309) — Latency Tracking & Benchmarking

Latency tracking captures and analyzes response time distributions across API endpoints, providing percentile breakdowns (p50, p95, p99, max) for each endpoint and version. Historical tracking enables detecting performance regressions: if p95 latency for a specific endpoint increases by more than 20% between schema versions, a regression alert is triggered.

The benchmarking system establishes baselines by running standardized load tests (e.g., 100 concurrent users, 60 seconds) and recording the latency profile. Subsequent runs are compared against the baseline to detect regressions. Baselines can be updated when performance improvements are intentional. The benchmark comparison view shows side-by-side latency distributions with statistical significance testing (is the difference real or noise).

Latency data is collected from both Test Lab's own load tests and from optional production telemetry ingestion (if the user configures their API to send latency data to Test Lab). This dual-source approach ensures testing environments and production environments can be compared.

**Acceptance Criteria:**
- Latency percentile tracking: p50, p95, p99, max for each endpoint in every test run
- Baseline establishment: mark a specific run as the baseline for future comparisons
- Regression detection: alert when p95 increases by configurable threshold (default 20%) versus baseline
- Benchmark comparison view: side-by-side latency distributions between two runs with diff percentage
- Latency trend chart: historical p50/p95/p99 over time for a specific endpoint
- API for latency data: `GET /api/v1/test-lab/benchmarks/{endpointId}/latency?from=&to=` returns timeseries

**Tech Stack:** NextJS page (`app/(platform)/test-lab/benchmarks/page.tsx`), chart library for latency distributions, PostgreSQL for timeseries data, statistical analysis for regression detection

Part of Epic: Performance & Chaos Testing

---

#### 3.4 (#1310) — Chaos Engineering & Fault Injection

Chaos engineering tests system resilience by intentionally introducing failures and observing how the system responds. The chaos testing module provides two capabilities: schema mutation testing (randomly modifying valid payloads to test schema validation robustness) and fault injection (simulating network failures, timeouts, and malformed responses to test client resilience).

Schema mutation testing takes valid payloads and applies controlled mutations: changing field types (string→number), removing required fields, adding unexpected fields, corrupting nested structures, and injecting invalid values for constrained fields. The test verifies that the API correctly rejects these mutations with appropriate error responses (400 Bad Request with descriptive error messages) rather than silently accepting bad data.

Fault injection simulates infrastructure failures: latency injection (add artificial delay to responses), error injection (return 500/503 for a percentage of requests), connection drops (terminate TCP connection mid-response), and payload corruption (garble response body). These tests validate that API consumers handle failures gracefully with proper timeout, retry, and fallback behavior.

**Acceptance Criteria:**
- Schema mutation test: mutate valid payloads with configurable mutation types and verify API rejection
- Mutation types: type_change, field_removal, field_addition, value_corruption, structure_corruption
- Fault injection modes: latency (configurable delay), error (configurable rate and status code), connection_drop, payload_corruption
- Test configuration: mutation_rate (% of requests mutated), fault_injection_rate, target endpoint
- Results report: mutation detection rate (% correctly rejected), fault tolerance score, failure mode analysis
- Chaos test API: `POST /api/v1/test-lab/chaos-tests/{id}/run` with configuration overrides

**Tech Stack:** Custom mutation engine for schema-aware payload corruption, proxy-based fault injection, Docker for test isolation, NextJS API routes

Part of Epic: Performance & Chaos Testing

---

#### 3.5 (#1311) — Performance Report Generation

Performance reports consolidate test results into comprehensive documents suitable for stakeholders, release reviews, and compliance audits. Reports are generated automatically after each test run or on demand for a specified date range. A report includes: executive summary (overall health, key metrics), test coverage (which endpoints were tested, which were not), latency analysis (percentile charts, comparison to baseline), error analysis (error categorization, top failure modes), capacity analysis (current limits, growth headroom), and recommendations.

Reports support multiple output formats: interactive HTML (for sharing via URL), PDF (for formal documentation), and JSON (for programmatic consumption). The HTML format includes interactive charts, drill-down capabilities, and links to individual test runs. Templates are configurable: teams can choose which sections to include and customize the branding (logo, colors).

Scheduled reporting enables automatic generation and distribution: configure a weekly performance report sent to a distribution list every Monday, or a monthly report including trend analysis across the month. Report history is retained for auditing with diff capabilities between consecutive reports.

**Acceptance Criteria:**
- Report generation endpoint: `POST /api/v1/test-lab/reports` with date range, endpoint scope, and format (html/pdf/json)
- Report sections: executive summary, test coverage, latency analysis, error analysis, capacity analysis, recommendations
- Interactive HTML reports with charts and drill-down links to individual test runs
- PDF export with configurable branding (logo, colors) via tenant settings
- Scheduled report generation with email distribution (daily/weekly/monthly)
- Report comparison: diff view between two reports highlighting metric changes and new issues

**Tech Stack:** Report generation engine, chart library for visualizations, Puppeteer for PDF rendering, email service for distribution, NextJS API routes

Part of Epic: Performance & Chaos Testing

---

## Epic 4: Test Management & CI/CD Integration

### Summary Table

| #   | Title                              | Description                                                                    | Labels                                   | Parallel |
|-----|------------------------------------|--------------------------------------------------------------------------------|------------------------------------------|----------|
| 4.1 (#1313) | Test Suite Management              | Organize tests into suites with tagging, filtering, and bulk operations        | `enhancement`, `mvp`, `test-lab`, `rest` | Yes      |
| 4.2 (#1314) | Test Run History & Trends          | Historical test run data with trend visualization and regression detection     | `enhancement`, `mvp`, `test-lab`         | No       |
| 4.3 (#1315) | CI/CD Pipeline Integration         | REST API and CLI for triggering tests from GitHub Actions, GitLab CI, Jenkins  | `enhancement`, `mvp`, `test-lab`, `rest` | Yes      |
| 4.4 (#1316) | Coverage Analysis & Gap Detection  | Identify untested schemas, endpoints, and edge cases                           | `enhancement`, `test-lab`                | No       |
| 4.5 (#1317) | Test Results Dashboard             | Unified dashboard showing test health across all test types                    | `enhancement`, `mvp`, `test-lab`         | No       |

### Detailed Issue Descriptions

#### 4.1 (#1313) — Test Suite Management

Test suites group related tests (contracts, data generation profiles, load test configurations, chaos tests) into logical collections that can be executed as a unit. A suite named "Order Service Release" might include: 5 contract tests, 2 load test configs, 1 chaos test, and 1 data generation profile for setting up test data. Suites support sequential execution order with configurable stop-on-failure behavior.

The suite management interface provides a tree view of all suites with nested tests. Users can create suites, add tests via drag-and-drop or search, configure execution order, and set suite-level settings (environment variables, target base URL, timeout). Tags enable cross-cutting categorization: a test can belong to multiple suites and have tags like "smoke", "regression", "nightly".

Suite execution triggers all contained tests in sequence (or parallel where configured) and produces an aggregate result. The suite result is pass (all tests pass), partial (some tests pass), or fail (critical tests fail). Partial results respect test criticality flags: a non-critical test failure doesn't fail the suite.

**Acceptance Criteria:**
- Suite CRUD API: `POST /api/v1/test-lab/suites` with test references, execution order, and stop-on-failure flag
- Suite execution: `POST /api/v1/test-lab/suites/{id}/run` triggers all tests with aggregate result
- Test criticality flag: critical (suite fails if this test fails) vs non-critical (suite reports partial)
- Tag system for tests with search and filter by tag across all test types
- Drag-and-drop test ordering within suite in the management UI
- Suite templates: save suite configurations as templates for quick setup of standard test patterns

**Tech Stack:** NextJS page (`app/(platform)/test-lab/suites/page.tsx`), Radix UI Dialog for suite creation, drag-and-drop library, PostgreSQL for suite configuration, REST API

Part of Epic: Test Management & CI/CD Integration

---

#### 4.2 (#1314) — Test Run History & Trends

The run history captures every test execution with full results, enabling trend analysis and regression detection over time. Each run record stores: test/suite reference, trigger source (manual, scheduled, CI/CD), start time, duration, result (pass/partial/fail), metric summary (tests run, passed, failed, skipped), and detailed per-test results.

The trend visualization shows test pass rate over time as a line chart, with a secondary chart showing test count trends (are we adding tests?). Regression detection triggers when the pass rate drops below a configurable threshold or when a specific test that has been passing starts failing. Flaky test detection identifies tests that alternate between pass and fail, using a "flakiness score" based on result consistency over the last 20 runs.

Run history supports comparison: select two runs and see a diff showing which tests changed status (newly passing, newly failing, newly added). This is particularly useful for release validation: compare the release candidate run against the last known-good run.

**Acceptance Criteria:**
- Run history API: `GET /api/v1/test-lab/runs` with filters for test/suite, trigger source, result, date range
- Pass rate trend chart: line chart of pass percentage over configurable time window (7d, 30d, 90d)
- Regression detection: alert when pass rate drops by configurable threshold (default 10%) between runs
- Flaky test detection: flag tests with >20% result inconsistency over last 20 runs
- Run comparison: select two runs to see diff of test status changes (newly passing/failing/added/removed)
- Run detail view with expandable per-test results and failure details

**Tech Stack:** NextJS page (`app/(platform)/test-lab/history/page.tsx`), chart library for trend visualization, Radix UI Table for run list, PostgreSQL for run storage

Part of Epic: Test Management & CI/CD Integration

---

#### 4.3 (#1315) — CI/CD Pipeline Integration

Test Lab integrates into CI/CD pipelines via a REST API and optional CLI tool, enabling automated test execution on every commit, pull request, or deployment. The integration provides three interaction patterns: (1) API trigger with polling (start a test run via API, poll for completion, check results), (2) API trigger with webhook callback (start a run, receive results at a callback URL), and (3) CLI tool that wraps the API with exit codes suitable for pipeline steps.

The CLI tool (`apiome-test`) supports commands: `run-suite --suite-id <id> --wait` (run a suite and wait for results, exit 0 on pass, exit 1 on fail), `run-contract --provider-schema <id>` (verify contracts), `run-load-test --config <id>` (execute load test), and `check-breaking-changes --from <version> --to <version>` (detect breaking changes). The tool outputs results in human-readable format by default, with `--format json` for programmatic parsing.

Pipeline examples are provided for GitHub Actions, GitLab CI, and Jenkins. Each example demonstrates: installing the CLI, configuring authentication (API key), running tests as a pipeline step, and interpreting results. A GitHub Actions marketplace action wraps the CLI for zero-configuration setup.

**Acceptance Criteria:**
- Test execution API: `POST /api/v1/test-lab/execute` with test/suite reference, returns run_id
- Polling endpoint: `GET /api/v1/test-lab/runs/{runId}` returns status (pending/running/completed) and results
- Webhook callback: optional `callback_url` parameter on execute, receives POST with results on completion
- CLI tool: `apiome-test` with commands: run-suite, run-contract, run-load-test, check-breaking-changes
- CLI exit codes: 0 (pass), 1 (fail), 2 (error/timeout) with human-readable and JSON output formats
- Pipeline examples documented for GitHub Actions, GitLab CI, and Jenkins in Test Lab documentation

**Tech Stack:** Node.js CLI tool (published to npm), NextJS API routes, webhook delivery service, OpenAPI 3.1 spec for all execution endpoints

Part of Epic: Test Management & CI/CD Integration

---

#### 4.4 (#1316) — Coverage Analysis & Gap Detection

Coverage analysis identifies which parts of the Apiome schema ecosystem have test coverage and which do not. Coverage is measured across multiple dimensions: schema field coverage (which fields in a schema are exercised by tests), endpoint coverage (which API endpoints have contract tests), edge case coverage (which constraint boundaries are tested), and version coverage (which schema versions have been tested).

The gap detector scans all schemas and compares against existing tests to produce a coverage report. Gaps are prioritized by risk: a critical field (e.g., `amount` on a payment schema) without tests is higher priority than an optional `notes` field. Risk scoring considers field sensitivity (PII, financial), usage frequency (from API analytics if available), and change frequency (fields that change often need more testing).

The coverage dashboard shows a treemap visualization where each rectangle represents a schema, sized by field count and colored by coverage percentage (green >80%, yellow 50-80%, red <50%). Clicking a schema shows field-level coverage with specific gap recommendations: "Field `billing.amount` has no contract test coverage. Recommended: add assertion in checkout-service contract."

**Acceptance Criteria:**
- Coverage analysis endpoint: `POST /api/v1/test-lab/coverage/analyze` scans schemas against existing tests
- Coverage dimensions: field coverage, endpoint coverage, edge case coverage, version coverage
- Risk-prioritized gaps: rank uncovered areas by field sensitivity, usage frequency, and change frequency
- Treemap visualization of schema coverage with color coding (green >80%, yellow 50-80%, red <50%)
- Field-level gap report with specific recommendations for adding test coverage
- Coverage trend tracking: historical coverage percentage with regression alerts on decrease

**Tech Stack:** NextJS page (`app/(platform)/test-lab/coverage/page.tsx`), treemap chart component, Radix UI Tooltip for coverage details, PostgreSQL for coverage data

Part of Epic: Test Management & CI/CD Integration

---

#### 4.5 (#1317) — Test Results Dashboard

The test results dashboard is the unified entry point for all testing activity in Test Lab. It provides a single-pane-of-glass view across all test types: contract tests, synthetic data validation, load tests, chaos tests, and coverage analysis. The dashboard surfaces the most important information: overall test health score, recent failures requiring attention, upcoming scheduled tests, and trending metrics.

The dashboard layout uses a card-based design with five primary sections: "Health Score" (aggregate pass rate across all test types, displayed as a large percentage with trend arrow), "Attention Required" (list of recently failed or regressed tests with quick links to details), "Recent Runs" (chronological list of recent test executions with status badges), "Scheduled" (upcoming automated test runs with next execution time), and "Quick Actions" (buttons for common operations: run all smoke tests, check breaking changes, generate test data).

Each card supports drill-down: clicking the health score card navigates to a breakdown by test type, clicking a failed test navigates to the failure details, clicking a scheduled test navigates to its configuration. The dashboard auto-refreshes every 60 seconds to reflect ongoing test executions.

**Acceptance Criteria:**
- Dashboard page with 5 sections: health score, attention required, recent runs, scheduled, quick actions
- Health score: weighted aggregate pass rate across all test types with 7-day trend arrow (up/down/stable)
- Attention required: max 10 items, ordered by severity (failed > regressed > flaky), with direct links to details
- Recent runs: last 20 runs across all types with type icon, name, status badge, and duration
- Auto-refresh every 60 seconds with visual indicator; manual refresh button
- Dashboard data API: `GET /api/v1/test-lab/dashboard` returns all dashboard data in a single response

**Tech Stack:** NextJS page (`app/(platform)/test-lab/dashboard/page.tsx`), Radix UI Table for recent runs, chart components for health score visualization, server-sent events for live updates

Part of Epic: Test Management & CI/CD Integration

---

## Parallel Work Guide

The following issues can be worked on simultaneously within and across epics:

**Epic 1 — Contract Testing Engine:**
- Issues 1.1 and 1.4 can be developed in parallel (data model and breaking change detection are independent)
- Issue 1.2 depends on 1.1 (contract authoring needs the data model)
- Issue 1.3 depends on 1.2 (provider verification needs authored contracts)
- Issue 1.5 depends on 1.3 (compatibility matrix needs verification results)

**Epic 2 — Synthetic Data Generator:**
- Issues 2.1, 2.2, 2.3, and 2.4 can all be developed in parallel (generation engine, PII masking, edge cases, and locale are independent modules)
- Issue 2.5 depends on 2.1 (profiles reference the generation engine configuration)

**Epic 3 — Performance & Chaos Testing:**
- Issues 3.1, 3.3, and 3.4 can be developed in parallel (load testing, latency tracking, and chaos testing are independent)
- Issue 3.2 depends on 3.1 (stress testing extends the load test runner)
- Issue 3.5 depends on 3.1, 3.2, 3.3 (reports consolidate results from all performance test types)

**Epic 4 — Test Management & CI/CD:**
- Issues 4.1 and 4.3 can be developed in parallel (suite management and CI/CD integration are independent)
- Issue 4.2 depends on 4.1 (run history needs suite/test execution records)
- Issue 4.4 depends on 4.1 and 4.2 (coverage analysis needs test and run data)
- Issue 4.5 depends on 4.2 and 4.4 (dashboard aggregates run history and coverage)

**Cross-Epic Parallelism:**
- Epics 1 and 2 can begin simultaneously (contracts and data generation are independent)
- Epic 3 benefits from Epic 2 (load tests use generated payloads) but can start independently with manual payloads
- Epic 4 (issues 4.1 and 4.3) can start in parallel with any other epic
- Issue 3.1 uses Epic 2's generator for payload generation; if developed in parallel, use placeholder data initially
