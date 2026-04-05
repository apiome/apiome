# Objectified: Testing & Quality Assurance - Feature Roadmap

> A comprehensive in-product testing platform that transforms Objectified from a schema design tool into a complete API quality assurance environment. Covers interactive API testing, mock server infrastructure, request collections, CRUD test flows, contract testing (Pact), load testing (k6), chaos engineering, and an automated CI/CD pipeline.
>
> **Revenue Model**: Swagger UI integration and basic interactive testing in all tiers; mock server, request collections, CRUD test runner, and Postman collection generation gated at Pro; contract testing (Pact broker), load testing, chaos engineering, and quality gates for publishing are Enterprise-only
>
> **Tech Stack**: NextJS App Router, Swagger UI (already integrated), Playwright/Cypress for E2E, k6 for load testing, Pact for contract testing, json-schema-faker (already integrated), Docker (mock server), PostgreSQL (test results), OpenAPI 3.1

---

## MVP Definition

- "Test API" button on each operation in the studio: pre-filled request body from examples, parameter auto-complete, authentication token management
- Mock server: one-click startup, serve mock responses from schema examples, request logging, hot-reload on spec changes
- CRUD test sequence runner: Create → Read → Update → Delete with automatic ID propagation
- Save requests as named collections; organize by feature/endpoint; share with team
- Swagger UI customization: custom branding, filter by tag, sort operations, Try-It-Out enhancements
- Schema validation: real-time OpenAPI 3.1 validation with naming convention enforcement
- Mock data generation: Faker.js-powered realistic data respecting constraints

---

## Epic 1 (#1555): Interactive API Testing

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                          | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-------------------------------------------------|-----|----------|
| 1.1 (#1561) | "Test API" Studio Button per Operation      | Per-operation test trigger in the studio: pre-fill body, auto-complete params      | `enhancement`, `mvp`, `testing`                | Yes | No       |
| 1.2 (#1567) | Authentication Token Management             | Store and switch API keys/Bearer tokens for testing; environment-aware            | `enhancement`, `mvp`, `testing`                | Yes | Yes      |
| 1.3 (#1572) | Save Requests as Test Collections           | Save requests to named collections; organize by endpoint; version control         | `enhancement`, `mvp`, `testing`, `rest`        | Yes | No       |
| 1.4 (#1578) | Collection Runner                           | Execute entire collection sequentially; variable substitution; assertions         | `enhancement`, `testing`                       | No  | No       |
| 1.5 (#1584) | Variable Substitution Between Requests      | Chain requests: use response field from request N as input to request N+1         | `enhancement`, `testing`                       | No  | Yes      |
| 1.6 (#1590) | Assertions & Test Validation                | Assert on status code, response body fields, response time; pass/fail output      | `enhancement`, `testing`                       | No  | No       |
| 1.7 (#1596) | Request History with Replay                 | Last 50 requests per user stored; replay any with one click                       | `enhancement`, `mvp`, `testing`                | Yes | Yes      |
| 1.8 (#1602) | Import/Export Postman Collections           | Import from Postman Collection v2.1 JSON; export as Postman collection             | `enhancement`, `testing`, `rest`               | No  | Yes      |
| 1.9 (#1608) | Generate Insomnia Workspaces               | Export current collections as Insomnia workspace JSON                              | `enhancement`, `testing`                       | No  | Yes      |
| 1.10 (#1614) | Pre-Request Scripts (JavaScript)           | Execute JS before a request: set headers, compute values, modify body              | `enhancement`, `testing`                       | No  | Yes      |
| 1.11 (#1872) | Post-Response Assertions (JavaScript)      | Execute JS after response: validate fields, extract values, run custom checks      | `enhancement`, `testing`                       | No  | Yes      |
| 1.12 (#1873) | Environment Variables for Endpoints        | Define environments (staging, production); switch base URL and credentials        | `enhancement`, `testing`                       | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1561) — "Test API" Studio Button per Operation

Add a "Test" button to every operation in the schema studio's path editor view. Clicking opens a test panel pre-populated with the operation's request schema (body, parameters, headers) using schema examples as defaults. The panel includes a "Send" button and a response viewer with syntax highlighting.

```
POST /users                              [Test ▶]
─────────────────────────────────────────────────
Request:
  Headers:  Authorization: Bearer [your-token]
  Body: {
    "displayName": "Alice Smith",
    "email": "alice@example.com"
  }

[Send Request]

Response (201 Created — 142ms):
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "displayName": "Alice Smith",
    "email": "alice@example.com",
    "createdAt": "2026-04-03T12:00:00Z"
  }
```

**Acceptance Criteria:**
- Test panel opens without leaving the studio context
- Request body auto-populated from schema `example` or `x-examples`; falls back to Faker.js if no examples
- Response rendered with JSON syntax highlighting; status code color-coded (green/red/yellow)
- Request saved to history on send (1.7)

Part of Epic: Interactive API Testing

---

#### 1.3 (#1572) — Save Requests as Test Collections

Allow users to save any tested request to a named collection. Collections are organized in a tree structure (collection → folder → request). Stored server-side per project.

**OpenAPI Endpoints:**
```
GET  /api/v1/test-collections?project_id=   → 200: CollectionList
POST /api/v1/test-collections               → 201: Collection
POST /api/v1/test-collections/{id}/requests → 201: TestRequest
GET  /api/v1/test-collections/{id}/requests → 200: TestRequestList
```

**Acceptance Criteria:**
- Collections visible to all project members (shared by default)
- Collections can be duplicated and modified independently
- Requests store: method, URL, headers (secrets masked), body, expected status
- Version history for collections (last 10 versions, diff view)

Part of Epic: Interactive API Testing

---

## Epic 2 (#1874): Swagger UI Enhancements

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|
| 2.1 (#1875) | Custom Branding & Colors                    | Apply tenant brand colors and logo to the embedded Swagger UI                     | `enhancement`, `testing`               | No  | Yes      |
| 2.2 (#1876) | Filter Operations by Tag                    | Sidebar filter to show/hide operations by tag group                                | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 2.3 (#1877) | Sort Operations                             | Sort operations alphabetically, by method, or by path                             | `enhancement`, `testing`               | No  | Yes      |
| 2.4 (#1878) | Show/Hide Model Schemas                     | Toggle visibility of the schemas section at the bottom of Swagger UI              | `enhancement`, `testing`               | No  | Yes      |
| 2.5 (#1879) | Try-It-Out: Example Selector Dropdown       | Choose from multiple defined examples for the request body                        | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 2.6 (#1880) | Try-It-Out: Generate Random Data Button     | One-click Faker.js-powered random data fill for the request body                  | `enhancement`, `testing`               | No  | Yes      |
| 2.7 (#1881) | Try-It-Out: Copy as cURL Command           | Generate and copy a valid cURL command for the current request                    | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 2.8 (#1882) | Try-It-Out: Copy as Code Snippet           | Copy as TypeScript/Python/Go code snippet for the current request                 | `enhancement`, `testing`               | No  | Yes      |
| 2.9 (#1883) | Try-It-Out: Download Response as File       | Download the response body as a JSON or CSV file                                  | `enhancement`, `testing`               | No  | Yes      |
| 2.10 (#1884) | Rich API Documentation: Markdown Support   | Render Markdown in operation `description` fields with code blocks                | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 2.11 (#1885) | Version-Specific Documentation              | Switch documentation view between published API versions                           | `enhancement`, `testing`               | No  | Yes      |

---

## Epic 3 (#1886): CRUD Test Runner

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|
| 3.1 (#1887) | Visual CRUD Test Panel                      | Dedicated CRUD testing interface: Create → Read → Update → Delete flow            | `enhancement`, `mvp`, `testing`        | Yes | No       |
| 3.2 (#1888) | Automatic ID Propagation                    | Extract ID from Create response; inject into subsequent Read/Update/Delete paths  | `enhancement`, `mvp`, `testing`        | Yes | No       |
| 3.3 (#1889) | Happy Path Test Execution                   | Run full CRUD sequence; visual step-by-step status (pass/fail per step)           | `enhancement`, `mvp`, `testing`        | Yes | No       |
| 3.4 (#1890) | Error Path Test Scenarios                   | Test invalid data (400), not-found (404), duplicate (409), unauthorized (401/403) | `enhancement`, `testing`               | No  | Yes      |
| 3.5 (#1891) | Edge Case Test Scenarios                    | Empty list, pagination with no results, large datasets, special characters        | `enhancement`, `testing`               | No  | Yes      |
| 3.6 (#1892) | Test Data Persistence Within Session        | Keep created test resources available for update/delete steps within the session  | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 3.7 (#1893) | Test Results History                        | Store CRUD test run results; show pass/fail history over time per schema          | `enhancement`, `testing`               | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#1887) — Visual CRUD Test Panel

Build a dedicated CRUD test panel that guides the user through a full resource lifecycle test. The panel knows which path operations correspond to each CRUD verb (derived from the schema's auto-generated CRUD paths or manually mapped).

```
CRUD Test Runner — User Resource
─────────────────────────────────────────────────────
Step 1: CREATE (POST /users)          ✓ 201 Created
  → id: "550e8400-..."  [propagated]

Step 2: READ (GET /users/{id})        ✓ 200 OK
  → User retrieved successfully

Step 3: UPDATE (PUT /users/{id})      ✓ 200 OK
  → displayName changed to "Alice Updated"

Step 4: DELETE (DELETE /users/{id})   ✓ 204 No Content

Step 5: VERIFY DELETED (GET /users/{id}) ✓ 404 Not Found

─────────────────────────────────────────────────────
Result: 5/5 PASSED    Duration: 412ms   [Run Again]
```

**Acceptance Criteria:**
- Panel auto-discovers CRUD operations from the project's Paths for the selected schema
- ID propagation uses `jsonpath` expression to extract the ID from the Create response
- Each step shows: status code, duration, response body snippet
- "Run Again" clears previous results and starts a fresh CRUD cycle

Part of Epic: CRUD Test Runner

---

## Epic 4 (#1894): Mock Server

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|
| 4.1 (#1895) | One-Click Mock Server Startup               | Start an in-process mock server serving responses from schema examples             | `enhancement`, `mvp`, `testing`        | Yes | No       |
| 4.2 (#1896) | Mock Response from Schema Examples          | Use `example`/`examples` from schema for response bodies; fallback to Faker.js    | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 4.3 (#1897) | Hot-Reload on Spec Changes                  | Mock server automatically reflects schema changes without restart                  | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 4.4 (#1898) | Request Logging & Inspection                | Real-time log of requests hitting the mock server with request/response details   | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 4.5 (#1899) | In-Memory CRUD Data Store                   | Stateful mock: POST creates, GET reads, PUT updates, DELETE removes in memory      | `enhancement`, `testing`               | No  | No       |
| 4.6 (#1900) | Persistent Mock Mode (SQLite)               | Persist mock data to SQLite so state survives server restarts                      | `enhancement`, `testing`               | No  | Yes      |
| 4.7 (#1901) | Configurable Response Delays                | Simulate network latency: fixed delay or random within min/max range              | `enhancement`, `testing`               | No  | Yes      |
| 4.8 (#1902) | Error Injection                             | Configure specific paths to return error responses for negative testing            | `enhancement`, `testing`               | No  | Yes      |
| 4.9 (#1903) | Docker Container Generation                 | Generate Dockerfile + docker-compose for the mock server for local dev            | `enhancement`, `testing`               | No  | Yes      |
| 4.10 (#1904) | Mock Data Export as JSON                   | Export current in-memory mock data state as JSON for use in other tools           | `enhancement`, `testing`               | No  | Yes      |
| 4.11 (#1905) | Start/Stop Controls in Studio              | Start and stop the mock server from the studio toolbar; status indicator          | `enhancement`, `mvp`, `testing`        | Yes | Yes      |
| 4.12 (#1906) | Modify Mock Data On-The-Fly               | Edit response values for specific paths while the server is running               | `enhancement`, `testing`               | No  | Yes      |

---

## Epic 5 (#1907): Mock Data Generation

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|
| 5.1 (#1908) | Schema-Constrained Random Data              | Faker.js + json-schema-faker generating data respecting min/max, pattern, enum    | `enhancement`, `mvp`, `testing`        | Yes | No       |
| 5.2 (#1909) | Realistic Field-Type Generators             | Names, addresses, emails, UUIDs, phone numbers, dates from domain-appropriate generators | `enhancement`, `mvp`, `testing`  | Yes | Yes      |
| 5.3 (#1910) | Bulk Mock Dataset Generation                | Generate N records (1–1000) per class in one click                                 | `enhancement`, `testing`               | No  | Yes      |
| 5.4 (#1911) | Export Mock Data as JSON / CSV / SQL INSERT | Download generated data in multiple formats for seeding, testing, or demos        | `enhancement`, `testing`, `rest`       | No  | Yes      |
| 5.5 (#1912) | Seed Database with Mock Data                | Execute generated INSERT statements against a configured dev database connection   | `enhancement`, `testing`               | No  | No       |
| 5.6 (#1913) | Multiple Example Variations                 | Generate N distinct example variations for use as alternative request bodies      | `enhancement`, `testing`               | No  | Yes      |

---

## Epic 6 (#1914): Contract Testing & CI/CD Pipeline

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|
| 6.1 (#1915) | Pact Broker Hosting                         | Host a Pact broker for consumer-driven contract storage and verification           | `enhancement`, `testing`               | No  | No       |
| 6.2 (#1916) | Consumer Contract Registration              | Register consumer contracts via Pact CLI integration                               | `enhancement`, `testing`               | No  | Yes      |
| 6.3 (#1917) | Provider Verification Workflow             | Trigger provider verification against registered contracts from the studio        | `enhancement`, `testing`               | No  | Yes      |
| 6.4 (#1918) | Can-I-Deploy Integration                    | Surface can-I-deploy status before version publish                                 | `enhancement`, `testing`               | No  | Yes      |
| 6.5 (#1919) | Webhook on Contract Change                  | Fire webhooks when consumer contracts change (for CI integration)                  | `enhancement`, `testing`, `rest`       | No  | Yes      |
| 6.6 (#1920) | Generate Postman Collections from Schemas   | Auto-generate Postman Collection v2.1 JSON covering all API operations             | `enhancement`, `testing`               | No  | Yes      |
| 6.7 (#1921) | GitHub Actions CI Workflow                  | Pre-built workflow: run schema validation and contract tests on PR                 | `enhancement`, `testing`               | No  | Yes      |
| 6.8 (#1922) | Quality Gate for Publishing                 | Block version publish if quality score < threshold or contract tests failing       | `enhancement`, `testing`               | No  | No       |

---

## Epic 7 (#1923): Load Testing & Chaos Engineering

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|
| 7.1 (#1924) | k6 Script Generation from Paths             | Generate k6 load test scripts covering all operations with configurable VUs/duration | `enhancement`, `testing`             | No  | No       |
| 7.2 (#1925) | Load Test Execution from Studio             | Run k6 tests from the studio UI; real-time metrics streaming via WebSocket        | `enhancement`, `testing`               | No  | No       |
| 7.3 (#1926) | Load Test Result Analysis                   | Chart: RPS, p50/p95/p99 latency, error rate over test duration; exportable        | `enhancement`, `testing`               | No  | Yes      |
| 7.4 (#1927) | Trend Comparison Across Runs                | Compare current load test results against historical baselines                    | `enhancement`, `testing`               | No  | Yes      |
| 7.5 (#1928) | Chaos Engineering: Fault Injection          | Inject network faults (packet loss, timeout) against mock server endpoints        | `enhancement`, `testing`               | No  | No       |
| 7.6 (#1929) | Chaos Engineering: Latency Injection        | Add configurable artificial latency to specific endpoints                          | `enhancement`, `testing`               | No  | Yes      |
| 7.7 (#1930) | Chaos Engineering: Error Response Simulation | Force specific error codes (500, 503) for resilience testing                     | `enhancement`, `testing`               | No  | Yes      |
| 7.8 (#1931) | Recovery Time Measurement                   | Measure time-to-recovery after chaos event; report MTTR                           | `enhancement`, `testing`               | No  | Yes      |

### Detailed Issue Descriptions

#### 7.1 (#1924) — k6 Script Generation from Paths

Generate a ready-to-run k6 TypeScript script from the project's defined path operations. The script includes: configurable VUs and duration, authentication setup, realistic request bodies from schema examples, response status assertions, and latency threshold checks.

```typescript
// Generated k6 script — User API v2
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 10,
  duration: '30s',
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.01'],
  },
};

const BASE_URL = 'https://api.example.com/v2';
const HEADERS = { 'Content-Type': 'application/json',
                   'Authorization': `Bearer ${__ENV.API_KEY}` };

export default function () {
  // Create user
  const createRes = http.post(`${BASE_URL}/users`,
    JSON.stringify({ displayName: 'Test User', email: `user${Date.now()}@test.com` }),
    { headers: HEADERS }
  );
  check(createRes, { 'create: status 201': r => r.status === 201 });

  const userId = JSON.parse(createRes.body).id;

  // Get user
  const getRes = http.get(`${BASE_URL}/users/${userId}`, { headers: HEADERS });
  check(getRes, { 'get: status 200': r => r.status === 200 });

  sleep(1);
}
```

**Acceptance Criteria:**
- Generated script uses TypeScript and runs with `k6 run --env API_KEY=...` without modification
- One test function per CRUD operation group in the script
- Threshold defaults: p95 < 500ms, error rate < 1% (configurable)
- Script downloadable as `.ts` file; includes `package.json` with `@types/k6` dependency

Part of Epic: Load Testing & Chaos Engineering

---

## Epic 8 (#1932): Automated Testing Infrastructure

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                  | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|-----------------------------------------|-----|----------|
| 8.1 (#1933) | Unit Test Infrastructure (Jest)             | Jest test runner for UI components; coverage reports on every PR                  | `enhancement`, `testing`               | No  | No       |
| 8.2 (#1934) | Integration Test Suite                      | API endpoint tests, database integration tests, authentication flow tests         | `enhancement`, `testing`               | No  | No       |
| 8.3 (#1935) | Playwright E2E Tests                        | Critical user journey tests: create project, import spec, design schema, export   | `enhancement`, `testing`               | No  | No       |
| 8.4 (#1936) | Visual Regression Tests                     | Screenshot comparison for canvas rendering; fail on unexpected visual changes     | `enhancement`, `testing`               | No  | Yes      |
| 8.5 (#1937) | GitHub Actions Full Pipeline               | Build → Lint → Type-check → Unit → Integration → E2E → Deploy to staging          | `enhancement`, `testing`               | No  | No       |
| 8.6 (#1938) | SonarQube Code Quality Integration         | Code quality gate in CI: block merge on quality drop below configured threshold   | `enhancement`, `testing`               | No  | Yes      |
| 8.7 (#1939) | Dependabot / Snyk Security Scanning        | Automated dependency vulnerability scanning with PR-based remediation             | `enhancement`, `testing`, `security`   | No  | Yes      |
| 8.8 (#1940) | Blue-Green Deployment & Smoke Tests        | Deploy to staging with smoke tests; promote to production only on pass            | `enhancement`, `testing`               | No  | No       |
