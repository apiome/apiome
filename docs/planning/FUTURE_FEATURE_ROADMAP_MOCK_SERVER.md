# Apiome: Mock Server - Feature Roadmap

> Intelligent mock server that generates realistic API responses from Apiome schemas without requiring backend implementation. Mock Server accelerates frontend, mobile, and integration development by providing schema-driven, stateful, scenario-aware API endpoints that behave like real backends—eliminating the "waiting for the API" bottleneck.
>
> **Revenue Model**: Hosted mock server hours, enterprise dedicated instances
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, Node.js mock runtime, Docker/Kubernetes for deployment, Redis for stateful mocking, Faker.js for data generation
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Schema parser that reads Apiome schema captures and generates mock endpoints
- Automatic response generation matching JSON Schema constraints (types, enums, ranges, formats)
- Stateful CRUD mocking (POST creates resources, GET retrieves them, DELETE removes them)
- Faker.js integration for generating realistic names, emails, addresses, and dates
- Scenario manager for defining success/error response profiles
- Hosted mock server provisioning with unique URL per project
- Postman/Insomnia collection export from mock endpoint definitions
- Mock server dashboard showing active instances, request logs, and usage metrics

---

## Epic 1: Core Mock Engine

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1151) | Schema Parser & Endpoint Generator | Parse Apiome schemas and generate mock API routes | `enhancement`, `mock-server`, `mvp`, `rest` | Yes |
| 1.2 (#1152) | Response Body Generator | Generate JSON responses matching schema constraints | `enhancement`, `mock-server`, `mvp` | Yes |
| 1.3 (#1153) | Stateful Mock Store | In-memory store enabling CRUD state across requests | `enhancement`, `mock-server`, `mvp` | No |
| 1.4 (#1154) | Relationship-Aware Responses | Generate linked resources respecting schema relationships | `enhancement`, `mock-server` | No |
| 1.5 (#1155) | Request Validation Layer | Validate incoming requests against schema definitions | `enhancement`, `mock-server`, `rest` | Yes |
| 1.6 (#1156) | Mock Server Configuration API | REST API for creating, configuring, and managing mock instances | `enhancement`, `mock-server`, `mvp`, `rest` | Yes |

### Detailed Issue Descriptions

#### 1.1 (#1151) — Schema Parser & Endpoint Generator

The Schema Parser reads Apiome schema captures (frozen schema versions with full JSON Schema definitions) and generates a routing table of mock API endpoints. For each schema class, the parser creates standard RESTful routes: `GET /resource` (list), `GET /resource/:id` (detail), `POST /resource` (create), `PUT /resource/:id` (update), `PATCH /resource/:id` (partial update), and `DELETE /resource/:id` (delete). If the schema includes OpenAPI path definitions, those are used instead of auto-generated routes.

The parser extracts property types, required fields, enum values, string formats, numeric ranges, array bounds, and nested object structures from JSON Schema definitions. This metadata is compiled into a "mock blueprint" that the response generator uses to produce valid payloads. The parser handles `$ref` resolution, `allOf`/`anyOf`/`oneOf` composition, and recursive schemas with depth limits.

The parsing pipeline is exposed via `POST /api/v1/mock/parse` which accepts a schema capture ID and returns the generated routing table. The routing table is persisted in a `mock_blueprints` table with columns for `schema_capture_id`, `routes` (JSONB array of route definitions), and `property_metadata` (JSONB map of generation hints). Re-parsing updates the blueprint when the schema is revised.

```
  Schema Capture ──► Parser ──► Mock Blueprint ──► Mock Router

  ┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
  │ JSON Schema  │     │ Route Generator  │     │ Mock Server  │
  │              │     │                  │     │              │
  │ classes:     │────►│ For each class:  │────►│ GET /users   │
  │  - User      │     │  - CRUD routes   │     │ GET /users/1 │
  │  - Product   │     │  - List/detail   │     │ POST /users  │
  │  - Order     │     │  - Nested routes │     │ PUT /users/1 │
  │              │     │                  │     │ DELETE /users │
  │ paths:       │     │ For each path:   │     │ GET /products│
  │  - /search   │────►│  - Method map    │────►│ POST /search │
  │              │     │  - Param extract │     │ ...          │
  └──────────────┘     └──────────────────┘     └──────────────┘
```

**Acceptance Criteria**:
- Parser generates standard CRUD routes for each schema class with pluralized resource names
- OpenAPI path definitions override auto-generated routes when present
- `$ref` resolution, `allOf`/`anyOf`/`oneOf` composition, and recursive schemas are supported
- Generated blueprint captures property types, required fields, enums, formats, and constraints
- Re-parsing a revised schema updates the blueprint without losing custom configuration
- Parser completes within 5 seconds for schemas with up to 100 classes

**Part of Epic: Core Mock Engine**

---

#### 1.2 (#1152) — Response Body Generator

The Response Body Generator produces JSON response payloads that satisfy the schema constraints defined in the mock blueprint. For each property, the generator selects an appropriate value based on type and constraints: strings respect `minLength`/`maxLength`/`pattern`/`format`, numbers respect `minimum`/`maximum`/`multipleOf`, arrays respect `minItems`/`maxItems`/`uniqueItems`, and enums select randomly from the allowed values.

The generator supports multiple strategies: "random" (fully random values within constraints), "realistic" (using Faker.js for semantic types like names and emails), and "deterministic" (seeded random for reproducible responses). The strategy is configurable per mock instance. For object properties without explicit constraints, the generator uses heuristics based on property name—a field named `email` generates an email format, `phone` generates a phone number, `created_at` generates an ISO timestamp.

List endpoints generate arrays of objects with configurable default page sizes (10, 25, 50) and support query parameters for pagination (`?page=1&limit=25`), sorting (`?sort=name&order=asc`), and filtering (`?status=active`). The response envelope matches the Apiome standard: `{ data: [...], pagination: { page, limit, total, pages } }`.

**Acceptance Criteria**:
- Generated values satisfy all JSON Schema constraints (type, range, pattern, format, enum)
- Heuristic property name matching generates semantically appropriate values for common field names
- List endpoints support pagination, sorting, and filtering query parameters
- Response envelope matches the Apiome standard format
- Three generation strategies are available: random, realistic (Faker), and deterministic (seeded)
- Nullable properties randomly include or exclude values based on a configurable probability

**Part of Epic: Core Mock Engine**

---

#### 1.3 (#1153) — Stateful Mock Store

The Stateful Mock Store gives mock servers CRUD persistence, so POSTed resources can be subsequently retrieved via GET, updated via PUT/PATCH, and removed via DELETE. State is maintained in a Redis-backed in-memory store keyed by mock instance ID and resource type. Each resource has an auto-generated UUID and a version counter.

When a POST request creates a resource, the request body is validated against the schema, assigned an ID, and stored. Subsequent GET requests for that ID return the stored resource. PUT/PATCH requests update the stored resource with the new values. DELETE requests remove the resource from the store. List endpoints return all stored resources of that type, with pagination applied to the in-memory collection.

State can be reset via `POST /api/v1/mock/{instanceId}/reset` which clears all stored resources, or `POST /api/v1/mock/{instanceId}/seed` which populates the store with a configurable number of generated resources per type. State persistence is configurable—ephemeral (memory only, lost on restart) or durable (Redis with TTL). The state store exposes `GET /api/v1/mock/{instanceId}/state` for debugging, returning a summary of stored resource counts by type.

**Acceptance Criteria**:
- POST requests store resources in the mock state with auto-generated UUIDs
- GET requests return previously stored resources by ID
- PUT/PATCH requests update stored resources and increment version
- DELETE requests remove resources from the store
- State reset endpoint clears all stored resources for a mock instance
- Seed endpoint populates the store with a configurable count of generated resources per type

**Part of Epic: Core Mock Engine**

---

#### 1.4 (#1154) — Relationship-Aware Responses

Relationship-Aware Responses extend the mock engine to generate linked resources that respect schema relationships. When a schema defines a `$ref` relationship between classes (e.g., an Order references a User), the mock engine generates consistent references—the `userId` in an Order matches an actual User in the stateful store. Nested includes (`?include=user`) embed the related resource in the response.

The relationship resolver reads `link_def` entries from the schema capture and builds a dependency graph. During seed generation, resources are created in topological order—parent resources before children. During individual POST operations, `$ref` fields are validated to ensure the referenced resource exists in the store (or a new one is auto-created if configured).

Include/expand support follows a query parameter convention: `GET /orders?include=user,items` embeds the related User object and Order Items array in each Order response. The depth of nested includes is capped at 3 levels to prevent circular reference loops. The response shape for included resources matches what the real API would return.

**Acceptance Criteria**:
- `$ref` relationships generate consistent foreign key references to existing resources
- Seed generation creates resources in topological order respecting dependencies
- Include parameter embeds related resources up to 3 levels deep
- Circular relationship detection prevents infinite loops during inclusion
- Missing referenced resources are either auto-created or return a 422 validation error (configurable)
- Relationship metadata is derived from schema `link_def` entries

**Part of Epic: Core Mock Engine**

---

#### 1.5 (#1155) — Request Validation Layer

The Request Validation Layer validates incoming requests to the mock server against schema definitions, returning proper error responses for invalid payloads. POST and PUT requests have their bodies validated against the schema class's JSON Schema definition. Required headers, query parameters, and path parameters defined in OpenAPI paths are also validated.

Validation errors return HTTP 400/422 with structured error responses following the Apiome error format: `{ error: { code, message, details: [{ field, constraint, message }] } }`. The error details array includes field-level information pointing to the exact property that failed validation, the constraint that was violated, and a human-readable message.

Validation strictness is configurable per mock instance: "strict" (reject all invalid requests), "warn" (accept but log validation failures), and "permissive" (accept everything, no validation). The strictness setting is managed via the mock configuration API. Validation results are included in the request log for debugging.

**Acceptance Criteria**:
- Request bodies are validated against JSON Schema definitions for POST, PUT, and PATCH
- Required headers and query parameters from OpenAPI definitions are validated
- Error responses follow the Apiome error format with field-level details
- Three strictness modes are available: strict, warn, and permissive
- Validation results are logged in the request log regardless of strictness mode
- Content-Type validation ensures the request body matches expected media types

**Part of Epic: Core Mock Engine**

---

#### 1.6 (#1156) — Mock Server Configuration API

The Mock Server Configuration API provides REST endpoints for creating, configuring, and managing mock server instances. Each instance is tied to a schema capture, has a unique base URL, and exposes configuration for response strategy, validation strictness, latency simulation, and state management. The configuration API is the control plane; the generated mock endpoints are the data plane.

The configuration dashboard at `/app/mock-server` lists all mock instances with status, base URL, schema capture reference, request count, and last activity. Creating a new instance via a Radix `Dialog` requires selecting a schema capture and optional configuration overrides. Each instance detail page at `/app/mock-server/[id]` shows the generated routes, configuration settings, request log, and state summary.

Backend endpoints include `POST /api/v1/mock/instances` (create), `GET /api/v1/mock/instances` (list), `GET /api/v1/mock/instances/{id}` (detail), `PUT /api/v1/mock/instances/{id}/config` (update configuration), `DELETE /api/v1/mock/instances/{id}` (destroy), and `GET /api/v1/mock/instances/{id}/logs` (request log). The `mock_instances` table stores `schema_capture_id`, `base_url`, `config` (JSONB), `status`, `created_by`, and `last_activity_at`.

**Acceptance Criteria**:
- Instance creation generates a unique base URL and parses the schema into a mock blueprint
- Configuration settings include response strategy, validation strictness, and latency simulation
- Instance dashboard shows status, base URL, request count, and last activity
- Request log captures method, path, status code, response time, and validation result
- Instance deletion stops the mock server and cleans up all associated state
- Configuration changes take effect immediately without instance restart

**Part of Epic: Core Mock Engine**

---

## Epic 2: Data Generation & Scenarios

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1158) | Faker.js Integration | Semantic data generation using Faker.js with locale support | `enhancement`, `mock-server`, `mvp` | Yes |
| 2.2 (#1159) | AI-Powered Data Generation | LLM-based contextual data generation for complex schemas | `enhancement`, `mock-server`, `ai-generated` | Yes |
| 2.3 (#1160) | Scenario Definition Manager | Define and switch between success, error, and edge case scenarios | `enhancement`, `mock-server`, `mvp` | Yes |
| 2.4 (#1161) | Delay & Chaos Injection | Simulate latency, timeouts, and intermittent failures | `enhancement`, `mock-server` | Yes |
| 2.5 (#1162) | Custom Data Generators | User-defined generator functions for domain-specific data | `enhancement`, `mock-server` | No |

### Detailed Issue Descriptions

#### 2.1 (#1158) — Faker.js Integration

Faker.js Integration provides semantically meaningful test data by mapping schema property names and formats to Faker.js generator functions. The mapping engine uses a configurable rules table: property names like `firstName`, `email`, `phone`, `address`, `company`, and `avatar` are automatically matched to their corresponding Faker modules. JSON Schema `format` values (`date-time`, `email`, `uri`, `uuid`, `ipv4`) are also mapped to appropriate generators.

The locale system allows generating data in over 60 locales supported by Faker.js—names, addresses, and phone numbers match the selected locale's conventions. The locale is configurable per mock instance and can be overridden per request via an `Accept-Language` header. Multiple locales can be mixed within a single response for testing internationalization scenarios.

Custom mappings extend the default rules: users can map any property name pattern (regex) to any Faker function path (e.g., `.*_price` → `faker.commerce.price`). Mappings are managed via `PUT /api/v1/mock/instances/{id}/faker-mappings` and stored in the instance configuration. A preview endpoint `POST /api/v1/mock/instances/{id}/preview-data` generates a single sample object using current Faker settings for quick verification.

**Acceptance Criteria**:
- Default mappings cover 20+ common property names (name, email, phone, address, etc.)
- JSON Schema format values map to appropriate Faker generators
- Locale selection affects generated names, addresses, phone numbers, and dates
- Custom mappings support regex-based property name matching to Faker function paths
- Preview endpoint generates a sample object for verification without modifying state
- Generated data satisfies all schema constraints (type, range, pattern) in addition to being realistic

**Part of Epic: Data Generation & Scenarios**

---

#### 2.2 (#1159) — AI-Powered Data Generation

AI-Powered Data Generation uses LLM capabilities to generate contextually meaningful data for complex schemas where Faker.js heuristics fall short. Given a schema class name, property descriptions, and an optional domain context prompt, the AI generates data that makes business sense—product descriptions that read naturally, reviews that vary in sentiment, and configuration objects with realistic settings.

The AI generator is invoked when a schema property has a `description` field or when the property name doesn't match any Faker rule. A configurable prompt template includes the schema class name, property name, type, constraints, and any description. The LLM returns a value that satisfies the schema constraints and fits the semantic context. Generated values are cached to reduce LLM calls—cache keys include the schema class, property, and a hash of the constraints.

AI generation is opt-in per mock instance via configuration. The rate is controlled by a credit system—each AI-generated value consumes a credit, and usage is tracked against the account's credit balance. The setting is managed at `/app/mock-server/[id]/config` under the "AI Generation" section with a Radix `Switch` to enable/disable and a Radix `Slider` to set the AI generation probability (0–100% of eligible properties).

**Acceptance Criteria**:
- AI generates contextually appropriate values for properties with descriptions
- Generated values satisfy all JSON Schema constraints (type, range, format, enum)
- Results are cached by schema class + property + constraint hash to reduce LLM calls
- AI generation is opt-in per instance with a probability slider
- Credit usage is tracked and displayed on the mock instance dashboard
- Fallback to Faker.js occurs when AI generation fails or credits are exhausted

**Part of Epic: Data Generation & Scenarios**

---

#### 2.3 (#1160) — Scenario Definition Manager

The Scenario Definition Manager enables users to define named scenarios that alter mock server behavior—switching between success responses, specific error codes, validation failures, empty results, and edge cases. Scenarios are defined as named configurations specifying response status codes, body overrides, and header modifications for specific endpoints or globally.

The scenario editor at `/app/mock-server/[id]/scenarios` renders a list of defined scenarios using Radix `Accordion` panels. Each scenario contains rules: a route matcher (method + path pattern), a response override (status code, body template, headers), and an optional condition (request header, query parameter match). The active scenario is selected via a Radix `Select` dropdown that immediately switches the mock server's behavior.

```
┌──────────────────────────────────────────────────────────────────┐
│  Scenarios — Payment API Mock                                    │
│  Active: [Happy Path ▾]                                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ▼ Happy Path (default)                                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ All endpoints return 200 with generated data              │   │
│  │ POST endpoints return 201 with created resource           │   │
│  │ DELETE endpoints return 204 no content                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ► Payment Declined                                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ POST /payments → 402 { error: "card_declined" }           │   │
│  │ All other endpoints → normal behavior                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ► Rate Limited                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ All endpoints → 429 after 10 requests per minute          │   │
│  │ Retry-After header: 60                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ► Server Error                                                 │
│  ► Empty Results                                                │
│                                                   [+ New Scenario]│
└──────────────────────────────────────────────────────────────────┘
```

Backend endpoints include `POST /api/v1/mock/instances/{id}/scenarios` (create), `GET /api/v1/mock/instances/{id}/scenarios` (list), `PUT /api/v1/mock/instances/{id}/scenarios/{scenarioId}` (update), and `PUT /api/v1/mock/instances/{id}/active-scenario` (switch active scenario). Scenarios can also be switched via a request header `X-Mock-Scenario: scenario-name` for per-request scenario control during testing.

**Acceptance Criteria**:
- Scenarios define response overrides (status code, body, headers) per route pattern
- Active scenario can be switched via the UI or the `X-Mock-Scenario` request header
- Default "Happy Path" scenario returns standard success responses for all endpoints
- Scenarios support conditional matching on request headers and query parameters
- Switching scenarios takes effect immediately without mock server restart
- At least 4 built-in scenario templates: happy path, error responses, rate limited, empty results

**Part of Epic: Data Generation & Scenarios**

---

#### 2.4 (#1161) — Delay & Chaos Injection

Delay & Chaos Injection simulates real-world network conditions by introducing configurable latency, timeouts, connection errors, and intermittent failures. This enables frontend developers to test loading states, error handling, retry logic, and timeout behavior against the mock server.

Delay settings include fixed delay (e.g., 500ms added to every response), random delay (e.g., 100–2000ms uniformly distributed), and percentile-based delay (e.g., p50=100ms, p95=500ms, p99=2000ms simulating realistic latency distribution). Chaos settings include failure probability (percentage of requests that return 500), timeout probability (percentage that hang until client timeout), and connection reset probability (TCP connection dropped).

Configuration is managed at `/app/mock-server/[id]/config` under the "Latency & Chaos" section with Radix `Slider` components for each setting. Settings are persisted via `PUT /api/v1/mock/instances/{id}/config` in the instance configuration JSONB. Per-route overrides allow different delay profiles for different endpoints—e.g., search endpoints might be slower than detail endpoints.

**Acceptance Criteria**:
- Fixed, random, and percentile-based delay modes are configurable per instance
- Chaos injection supports failure (500), timeout (hang), and connection reset probabilities
- Per-route delay overrides allow different latency profiles for specific endpoints
- Delay and chaos settings can be adjusted without restarting the mock instance
- Request log records the actual delay applied and whether chaos was injected
- A "no delay" quick toggle disables all latency simulation for fast iteration

**Part of Epic: Data Generation & Scenarios**

---

#### 2.5 (#1162) — Custom Data Generators

Custom Data Generators allow users to define JavaScript functions that produce domain-specific mock data beyond what Faker.js and AI generation offer. Custom generators are registered for specific property name patterns and receive the property schema as input, returning a generated value. This enables generating realistic SKU codes, custom ID formats, industry-specific codes, and calculated fields.

The generator editor at `/app/mock-server/[id]/generators` provides a code editor for writing generator functions in a sandboxed JavaScript environment. Each generator has a name, a property pattern (regex), and a function body. The sandbox provides access to `faker`, `Math`, `Date`, and a `context` object containing the current resource being generated (for computed fields that depend on other property values).

Backend endpoints include `POST /api/v1/mock/instances/{id}/generators` (create), `GET /api/v1/mock/instances/{id}/generators` (list), `PUT /api/v1/mock/instances/{id}/generators/{genId}` (update), and `POST /api/v1/mock/instances/{id}/generators/{genId}/test` (execute the generator once and return the result). Generators are stored in a `mock_generators` table with `instance_id`, `name`, `pattern`, `function_body`, and `priority`.

**Acceptance Criteria**:
- Generator functions are written in JavaScript with access to faker, Math, Date, and context
- Generators are matched to properties by regex pattern with configurable priority
- Sandbox environment prevents access to the file system, network, and process globals
- Test endpoint executes a generator once and returns the result for quick validation
- Generator execution timeout prevents infinite loops (configurable, default 100ms)
- Custom generators take priority over Faker.js mappings when both match a property

**Part of Epic: Data Generation & Scenarios**

---

## Epic 3: Deployment & Infrastructure

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1164) | Hosted Mock Server Provisioning | One-click provisioning of cloud-hosted mock instances | `enhancement`, `mock-server`, `mvp`, `rest` | Yes |
| 3.2 (#1165) | Docker Image & Local Development | Docker images for running mock servers locally | `enhancement`, `mock-server` | Yes |
| 3.3 (#1166) | Kubernetes Operator | K8s operator for deploying mock servers in CI/CD pipelines | `enhancement`, `mock-server` | Yes |
| 3.4 (#1167) | Edge Deployment | Deploy mock servers to edge locations for low-latency access | `enhancement`, `mock-server` | No |
| 3.5 (#1168) | Mock Server Monitoring & Observability | Request logging, metrics, and health monitoring for instances | `enhancement`, `mock-server`, `rest` | Yes |

### Detailed Issue Descriptions

#### 3.1 (#1164) — Hosted Mock Server Provisioning

Hosted Mock Server Provisioning enables users to create cloud-hosted mock server instances with a single click. Each hosted instance gets a unique subdomain (e.g., `acme-payment-api.mock.apiome.app`), runs in an isolated container, and is accessible over HTTPS. Provisioning takes less than 30 seconds from request to first available endpoint.

The provisioning flow at `/app/mock-server/new` guides users through selecting a schema capture, configuring the instance name and settings, and clicking "Launch." The backend creates a container, deploys the mock engine with the schema's blueprint, configures TLS via wildcard certificate, and registers the DNS entry. Instance lifecycle management supports stop, start, and destroy operations.

Backend endpoints include `POST /api/v1/mock/instances` (provision), `POST /api/v1/mock/instances/{id}/stop` (stop container), `POST /api/v1/mock/instances/{id}/start` (restart container), and `DELETE /api/v1/mock/instances/{id}` (destroy and cleanup). Usage is metered by uptime hours, with free tier including 100 hours per month. The provisioning status is trackable via `GET /api/v1/mock/instances/{id}/status`.

**Acceptance Criteria**:
- Hosted instances are provisioned with unique HTTPS subdomains within 30 seconds
- Instance lifecycle supports stop, start, and destroy operations
- Free tier includes 100 hosted mock server hours per month
- TLS is configured automatically via wildcard certificate
- Instance status endpoint reports provisioning progress and runtime health
- Stopped instances do not consume metered hours

**Part of Epic: Deployment & Infrastructure**

---

#### 3.2 (#1165) — Docker Image & Local Development

The Docker Image packages the mock engine into a container that developers can run locally. The image is published to Docker Hub and the Apiome container registry. Running locally requires only `docker run -p 3100:3100 -v ./schema.json:/schema.json apiome/mock-server` to start a mock server from a schema file.

The Docker image supports configuration via environment variables: `MOCK_SCHEMA_URL` (fetch schema from Apiome API), `MOCK_STRATEGY` (random/realistic/deterministic), `MOCK_SEED` (for deterministic mode), `MOCK_LATENCY` (fixed delay in ms), and `MOCK_STRICT` (validation strictness). A `docker-compose.yml` template is provided for running the mock server alongside frontend development containers.

Documentation at `/docs/mock-server/docker` covers installation, configuration, and integration with common development workflows. The Docker image is tagged with the mock engine version and published on every release. Multi-architecture builds support both `amd64` and `arm64` (Apple Silicon).

**Acceptance Criteria**:
- Docker image starts a functional mock server from a local schema file or remote URL
- Configuration via environment variables supports strategy, seed, latency, and strictness
- Image supports `amd64` and `arm64` architectures
- Docker Compose template runs mock server alongside a sample frontend container
- Image size is under 200MB to minimize download times
- Health check endpoint is configured for Docker's `HEALTHCHECK` instruction

**Part of Epic: Deployment & Infrastructure**

---

#### 3.3 (#1166) — Kubernetes Operator

The Kubernetes Operator automates deployment and management of mock servers within Kubernetes clusters, primarily for CI/CD pipeline integration. The operator introduces a `MockServer` Custom Resource Definition (CRD) that declares the desired mock server configuration—schema source, scenario, resource limits. The operator reconciles the CRD by deploying a mock server pod, service, and optional ingress.

CI/CD pipelines apply a `MockServer` YAML manifest at the start of integration tests, wait for the ready condition, run tests against the mock server's service URL, and delete the manifest to clean up. The operator handles lifecycle management, health checking, and resource cleanup. A Helm chart packages the operator for easy installation.

The CRD spec includes `schemaRef` (Apiome schema capture reference or inline schema), `scenario` (active scenario name), `replicas` (for load testing), `resources` (CPU/memory limits), and `ttl` (auto-delete after duration). The operator is published as a Helm chart to the Apiome chart repository and documented at `/docs/mock-server/kubernetes`.

**Acceptance Criteria**:
- `MockServer` CRD declares schema source, scenario, replicas, resources, and TTL
- Operator creates pod, service, and optional ingress from the CRD spec
- Ready condition is set when the mock server passes its health check
- TTL-based auto-deletion cleans up mock servers after the configured duration
- Helm chart installs the operator and CRD definitions in a single command
- Operator handles schema updates by rolling the mock server pod

**Part of Epic: Deployment & Infrastructure**

---

#### 3.4 (#1167) — Edge Deployment

Edge Deployment distributes mock servers to edge locations worldwide for ultra-low-latency access during mobile and frontend development. Edge instances run on a lightweight runtime (e.g., Cloudflare Workers or Deno Deploy) with the mock blueprint compiled to a self-contained bundle. Edge deployment is triggered from the hosted provisioning flow by selecting "Edge" as the deployment target.

Edge instances support a subset of features: stateless mocking only (no CRUD state), Faker.js data generation (no AI generation), and basic scenario switching. These constraints allow the mock engine to fit within edge runtime size and memory limits. Edge URLs follow the pattern `acme-payment-api.edge.mock.apiome.app` with automatic geo-routing.

The backend compiles the mock blueprint into an edge-compatible bundle via `POST /api/v1/mock/instances/{id}/deploy-edge`. Deployment status is trackable, and edge metrics (request count, latency by region) are reported back to the dashboard. Edge instances are billed at a separate rate reflecting the edge infrastructure costs.

**Acceptance Criteria**:
- Edge deployment creates globally distributed mock servers with sub-50ms latency
- Edge instances support stateless mocking, Faker.js generation, and scenario switching
- Edge URLs use geo-routing to direct requests to the nearest edge location
- Deployment completes within 60 seconds to all edge locations
- Edge request metrics are reported back to the mock server dashboard by region
- Feature limitations (no state, no AI) are clearly communicated in the deployment flow

**Part of Epic: Deployment & Infrastructure**

---

#### 3.5 (#1168) — Mock Server Monitoring & Observability

Mock Server Monitoring & Observability provides request logging, performance metrics, and health dashboards for all mock server instances. The request log captures every incoming request with method, path, status code, response time, matched scenario rule, validation result, and response size. Metrics are aggregated for dashboard display.

The monitoring page at `/app/mock-server/[id]/monitor` renders three Radix `Tabs`: "Request Log" (paginated table of recent requests), "Metrics" (time-series charts for request rate, error rate, and response time), and "Health" (instance resource utilization). The request log supports filtering by status code, path pattern, and time range.

Backend endpoints include `GET /api/v1/mock/instances/{id}/logs` (request log with pagination and filters), `GET /api/v1/mock/instances/{id}/metrics` (aggregated metrics), and `GET /api/v1/mock/instances/{id}/health` (instance health). Request logs are retained for 7 days for hosted instances (configurable for enterprise). Metrics are aggregated at 1-minute granularity.

**Acceptance Criteria**:
- Request log captures method, path, status, response time, scenario, and validation result
- Metrics charts display request rate, error rate, and response time percentiles
- Health tab shows instance CPU, memory, and connection utilization
- Request log is filterable by status code range, path pattern, and time range
- Logs are retained for 7 days (configurable for enterprise instances)
- Real-time log streaming is available via WebSocket for live debugging

**Part of Epic: Deployment & Infrastructure**

---

## Epic 4: Developer Tooling & Integration

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#1170) | Postman/Insomnia Collection Export | Generate API client collections from mock endpoints | `enhancement`, `mock-server`, `mvp` | Yes |
| 4.2 (#1171) | Collection Import & Sync | Import existing Postman/Insomnia collections to create mock servers | `enhancement`, `mock-server` | Yes |
| 4.3 (#1172) | SDK & Client Library Integration | Generate typed API clients from mock server schemas | `enhancement`, `mock-server` | No |
| 4.4 (#1173) | Test Fixture Generation | Generate test data fixtures from mock schemas for unit tests | `enhancement`, `mock-server` | Yes |
| 4.5 (#1174) | VS Code Extension | Mock server management directly from the IDE | `enhancement`, `mock-server` | Yes |

### Detailed Issue Descriptions

#### 4.1 (#1170) — Postman/Insomnia Collection Export

Postman/Insomnia Collection Export generates downloadable API client collections from a mock server's endpoint definitions. The export includes all generated routes with example requests, request bodies populated with sample data, response examples, and environment variables for the mock server URL. Collections are formatted for Postman Collection v2.1 and Insomnia v4 formats.

The export is available from the mock instance detail page at `/app/mock-server/[id]` via an "Export Collection" Radix `DropdownMenu` with options for Postman and Insomnia formats. The exported collection organizes endpoints by resource type with folders for each schema class. Each request includes pre-populated body examples generated from the mock's response generator, and test scripts that validate response structure against the schema.

Backend endpoints include `GET /api/v1/mock/instances/{id}/export/postman` (Postman v2.1 JSON), `GET /api/v1/mock/instances/{id}/export/insomnia` (Insomnia v4 JSON), and `GET /api/v1/mock/instances/{id}/export/openapi` (OpenAPI 3.1 spec). The export includes an environment definition with `{{baseUrl}}` variable set to the mock server's URL, making it easy to switch between mock and real API by changing the environment.

**Acceptance Criteria**:
- Postman Collection v2.1 export includes all routes organized by resource type
- Insomnia v4 export includes equivalent routes with workspace structure
- Request bodies are populated with sample data matching schema constraints
- Environment variables include `baseUrl` pointing to the mock server URL
- OpenAPI 3.1 export generates a valid spec document from the mock blueprint
- Export files are downloadable as JSON with appropriate Content-Disposition headers

**Part of Epic: Developer Tooling & Integration**

---

#### 4.2 (#1171) — Collection Import & Sync

Collection Import & Sync allows users to import existing Postman or Insomnia collections to create mock servers, bridging the gap for teams that already have API collections but no schema definitions. The import parser extracts endpoint definitions, request/response examples, and infers a JSON Schema from the collection's example payloads.

The import flow at `/app/mock-server/import` accepts a file upload (Postman JSON, Insomnia JSON) or a Postman collection URL. The parser analyzes the collection, infers schemas from example responses using JSON-to-JSON-Schema conversion, and presents the inferred schema for user review and correction before creating the mock server. Users can map imported endpoints to existing Apiome schemas or create new schema captures from the inferred definitions.

Backend endpoints include `POST /api/v1/mock/import/analyze` (upload collection and return inferred schema), `POST /api/v1/mock/import/create` (create mock server from analyzed collection), and `POST /api/v1/mock/import/sync` (update an existing mock server from a re-imported collection). Sync tracks changes between the imported collection and the existing mock, presenting a diff for review before applying updates.

**Acceptance Criteria**:
- Import supports Postman Collection v2.1 and Insomnia v4 formats
- JSON Schema inference derives types, required fields, and enums from example payloads
- Inferred schema is presented for review and correction before mock creation
- Import can create new schema captures or map to existing Apiome schemas
- Sync detects changes between imported collection and existing mock configuration
- Import handles collections with up to 500 endpoints and 1000 example payloads

**Part of Epic: Developer Tooling & Integration**

---

#### 4.3 (#1172) — SDK & Client Library Integration

SDK & Client Library Integration generates typed API clients from mock server schemas, enabling frontend and mobile developers to use strongly-typed client libraries during development that work seamlessly against both mock and real APIs. Generated clients include TypeScript/JavaScript (fetch-based), Python (httpx), and Swift types.

The generation page at `/app/mock-server/[id]/sdk` offers language selection via Radix `RadioGroup` and a "Generate" button that produces a downloadable client library package. The generated client includes typed request/response models, method stubs for each endpoint, error handling, and a configurable base URL that defaults to the mock server. Switching to the production API requires only changing the base URL.

Backend endpoints include `POST /api/v1/mock/instances/{id}/sdk/generate` (trigger generation with language parameter), `GET /api/v1/mock/instances/{id}/sdk/status` (generation progress), and `GET /api/v1/mock/instances/{id}/sdk/download` (download generated package). Generation is performed asynchronously for large schemas. The generated TypeScript client uses `zod` for runtime validation matching the schema constraints.

**Acceptance Criteria**:
- TypeScript/JavaScript client generation produces typed fetch-based API methods
- Python client generation produces httpx-based methods with type hints
- Generated clients include typed request/response models matching schema definitions
- Base URL is configurable, defaulting to the mock server URL
- TypeScript client includes zod schemas for runtime response validation
- Generation completes within 30 seconds for schemas with up to 100 classes

**Part of Epic: Developer Tooling & Integration**

---

#### 4.4 (#1173) — Test Fixture Generation

Test Fixture Generation produces static test data files from mock schemas for use in unit tests, snapshot tests, and storybook stories. Unlike the runtime mock server, fixtures are pre-generated JSON files committed to the project repository, providing fast, deterministic test data without network dependencies.

The fixture generator at `/app/mock-server/[id]/fixtures` allows configuring the number of fixtures per schema class, the generation strategy (deterministic with seed), and the output format (individual JSON files, single combined file, or TypeScript constants). Generated fixtures include valid data (matching all constraints) and optionally invalid data (deliberately violating constraints for error testing).

Backend endpoints include `POST /api/v1/mock/instances/{id}/fixtures/generate` (generate fixture set) and `GET /api/v1/mock/instances/{id}/fixtures/download` (download as ZIP). The fixture package includes a `README.md` describing the schema source, generation date, and seed value for reproducibility. Fixtures can be regenerated with the same seed to produce identical output after schema changes, with a diff showing which fixtures changed.

**Acceptance Criteria**:
- Fixtures are generated as deterministic JSON files using a configurable seed
- Output formats include individual JSON files, combined file, and TypeScript constants
- Invalid fixture generation deliberately violates constraints for error test cases
- Fixture ZIP includes a README with schema source, date, and seed for reproducibility
- Same seed produces identical fixtures for the same schema version
- Regeneration after schema changes produces a diff showing which fixtures were affected

**Part of Epic: Developer Tooling & Integration**

---

#### 4.5 (#1174) — VS Code Extension

The VS Code Extension brings mock server management directly into the IDE, reducing context-switching between the browser and editor. The extension provides a sidebar panel listing active mock server instances with start/stop controls, a command palette for common actions (create instance, switch scenario, reset state), and inline CodeLens annotations showing which schema properties have mock generators.

The extension authenticates with the Apiome API using the user's API key stored in VS Code settings. It communicates with the mock server configuration API for all operations. The sidebar renders instance status with the mock server URL that can be copied with one click. Scenario switching is available via a status bar item that shows the current active scenario with a dropdown to switch.

The extension is published to the VS Code Marketplace and supports both VS Code and Cursor. Source code lives in `/packages/vscode-mock-server`. Key features include: (1) activity bar icon with instance list sidebar, (2) command palette commands prefixed with "Apiome Mock:", (3) status bar showing active instance and scenario, (4) CodeLens on schema files showing mock generator annotations.

**Acceptance Criteria**:
- Sidebar panel lists all mock server instances with status and base URL
- Start, stop, reset, and destroy operations are available from the sidebar
- Scenario switching is available from the status bar dropdown
- Command palette provides "Apiome Mock:" prefixed commands for common actions
- API key authentication is configured via VS Code settings
- Extension works in both VS Code and Cursor editors

**Part of Epic: Developer Tooling & Integration**

---

## Parallel Work Guide

**Epic 1 — Core Mock Engine**:
Issues 1.1 (Schema Parser), 1.2 (Response Generator), 1.5 (Request Validation), and 1.6 (Configuration API) can be developed in parallel. Issue 1.3 (Stateful Store) depends on 1.2 for response generation during seed operations. Issue 1.4 (Relationship-Aware Responses) depends on 1.3 for the stateful store and 1.1 for relationship metadata extraction.

**Epic 2 — Data Generation & Scenarios**:
Issues 2.1 (Faker.js), 2.2 (AI Generation), 2.3 (Scenario Manager), and 2.4 (Delay Injection) can all be developed in parallel as they address independent aspects of the mock engine. Issue 2.5 (Custom Generators) depends on 2.1 for the generator registry and priority system.

**Epic 3 — Deployment & Infrastructure**:
Issues 3.1 (Hosted Provisioning), 3.2 (Docker Image), 3.3 (K8s Operator), and 3.5 (Monitoring) can be developed in parallel as they target independent deployment targets. Issue 3.4 (Edge Deployment) depends on 3.1 for the provisioning flow and requires the mock engine to be compilable to an edge-compatible bundle.

**Epic 4 — Developer Tooling & Integration**:
Issues 4.1 (Postman Export), 4.2 (Collection Import), 4.4 (Test Fixtures), and 4.5 (VS Code Extension) can be developed in parallel. Issue 4.3 (SDK Generation) depends on 4.1 for the OpenAPI export that serves as input to SDK generators.

**Cross-Epic Parallelism**: Epic 1 (Core Engine) must be substantially complete before Epics 2, 3, and 4 can be fully functional, as they all depend on the core mock engine. However, UI scaffolding and API shell work for all epics can proceed in parallel. Epic 2 (Data Generation) and Epic 4 (Tooling) are independent of each other and can progress simultaneously once Epic 1 is stable.
