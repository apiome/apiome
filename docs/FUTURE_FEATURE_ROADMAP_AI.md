# Objectified: AI Assistant & Intelligence - Feature Roadmap

> A self-hosted AI layer built on Ollama (Qwen 2.5, Llama 3.2) that powers natural language schema generation, automated schema review, documentation generation, and AI-assisted personalization — with no data leaving the Objectified infrastructure.
>
> **Revenue Model**: AI features gated at Pro/Enterprise tiers; token budget and usage limits enforced per subscription tier; enterprise customers get dedicated Ollama cluster nodes
>
> **Tech Stack**: NextJS App Router, Ollama (self-hosted), Qwen 2.5 / Llama 3.2, PostgreSQL (conversation history, audit logs), OpenAPI 3.1, TypeScript AI SDK wrapper

---

## MVP Definition

- Natural language to schema: parse a user-story prompt and generate a complete class set with properties and relationships
- AI schema review triggered on-demand: produces severity-ranked recommendations with one-click fix options
- AI documentation generation: curl examples, TypeScript/Python code snippets, and getting-started guides
- Admin Ollama configuration: primary + failover server URLs, model selection, request limits per user/tenant
- All AI processing on self-hosted Ollama — no data sent to external services
- Audit logging of every AI interaction (user, model, prompt hash, response hash, timestamp)

---

## Epic 1 (#1498): AI Assistant Core

### Summary Table

| #   | Title                                    | Description                                                                        | Labels                               | MVP | Parallel |
|-----|------------------------------------------|------------------------------------------------------------------------------------|--------------------------------------|-----|----------|
| 1.1 (#1499) | Ollama Integration & Connection Layer    | HTTP client wrapper around Ollama API with failover, health checks, load balancing | `enhancement`, `mvp`, `ai`          | Yes | No       |
| 1.2 (#1500) | AI Chat UI Component                     | Floating chat panel in the schema studio for conversational AI interactions        | `enhancement`, `mvp`, `ai`          | Yes | No       |
| 1.3 (#1501) | Conversation History Storage             | Persist chat sessions per user per project in PostgreSQL with encryption at rest   | `enhancement`, `mvp`, `ai`          | Yes | No       |
| 1.4 (#1502) | Prompt Context Injection                 | Automatically inject the current schema context into prompts for relevant answers  | `enhancement`, `mvp`, `ai`          | Yes | Yes      |
| 1.5 (#1503) | AI Request Queue & Rate Limiting         | Queue AI requests per user/tenant; enforce token budget limits per subscription    | `enhancement`, `mvp`, `ai`, `rest`  | Yes | No       |
| 1.6 (#1504) | Streaming Response Rendering             | Stream token-by-token AI output to the chat UI for responsive feel                 | `enhancement`, `ai`                 | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1499) — Ollama Integration & Connection Layer

Build a typed TypeScript client that wraps the Ollama REST API. Support multiple server endpoints (primary + N failover), round-robin or least-connections load balancing, configurable health check interval, and connection pool size. On health check failure, automatically remove the endpoint from the rotation and re-add when it recovers.

```
OllamaClient
├── endpoints: OllamaEndpoint[]          ← primary + failovers
├── strategy: round-robin | least-conn
├── healthCheckInterval: number (ms)
├── generate(prompt, model, options)     ← streaming
└── embed(text, model)                   ← embeddings

OllamaEndpoint
├── url: string
├── healthy: boolean
├── activeConnections: number
└── lastHealthCheck: Date
```

**OpenAPI Endpoints:**
```
GET /api/v1/ai/health
  → 200: { endpoints: [{url, healthy, latency_ms}] }
```

**Acceptance Criteria:**
- Client retries failed requests on healthy endpoints transparently
- Health check endpoint returns aggregate cluster status
- All requests timeout after a configurable `request_timeout_ms` (default: 30s)
- Unit tests cover failover logic with mocked Ollama endpoints

**Tech Stack:** Node.js `fetch`, Ollama REST API, connection pooling via in-memory state

Part of Epic: AI Assistant Core

---

#### 1.5 (#1503) — AI Request Queue & Rate Limiting

Implement a server-side queue that enforces per-user and per-tenant AI request limits. Requests exceeding the limit are queued up to a configurable `queue_depth`; beyond that they are rejected with 429. Limits are tied to subscription tier (Free: 10 req/hour, Pro: 100 req/hour, Enterprise: configurable).

**OpenAPI Endpoints:**
```
GET /api/v1/ai/usage
  → 200: { requests_this_hour: N, limit: N, resets_at: ISO8601 }
```

**Acceptance Criteria:**
- Rate limit enforced per `user_id` and per `tenant_id` independently
- 429 response includes `Retry-After` header
- Usage counters stored in Redis with 1-hour TTL
- Admin can override limits per tenant via admin settings

Part of Epic: AI Assistant Core

---

## Epic 2 (#1505): AI-Powered Schema Tools

### Summary Table

| #   | Title                                       | Description                                                                      | Labels                               | MVP | Parallel |
|-----|---------------------------------------------|----------------------------------------------------------------------------------|--------------------------------------|-----|----------|
| 2.1 (#1506) | Natural Language to Schema — Prompt Input   | UI for entering user-story prompts; model selects domain template as baseline    | `enhancement`, `mvp`, `ai`          | Yes | No       |
| 2.2 (#1507) | Schema Generation from User Stories         | Parse user-story input and generate a complete class set with relationships       | `enhancement`, `mvp`, `ai`, `rest`  | Yes | No       |
| 2.3 (#1508) | Domain Template Selection                   | Allow AI to select from E-commerce, SaaS, Social, Healthcare, Education templates| `enhancement`, `ai`                 | No  | Yes      |
| 2.4 (#1509) | Generated Schema Canvas Preview             | Preview generated classes on read-only canvas before committing to project       | `enhancement`, `mvp`, `ai`          | Yes | No       |
| 2.5 (#1510) | AI Schema Review — On-Demand Trigger        | "Review my schema" command produces severity-ranked recommendations               | `enhancement`, `mvp`, `ai`          | Yes | No       |
| 2.6 (#1511) | Review: Naming Convention Analysis          | Detect inconsistent naming (camelCase vs snake_case, abbreviations)              | `enhancement`, `mvp`, `ai`          | Yes | Yes      |
| 2.7 (#1512) | Review: Documentation Gap Analysis          | Flag missing descriptions and examples; suggest AI-generated descriptions        | `enhancement`, `mvp`, `ai`          | Yes | Yes      |
| 2.8 (#1513) | Review: Relationship & Validation Analysis  | Detect orphaned schemas, missing references, and weak validation constraints     | `enhancement`, `ai`                 | No  | Yes      |
| 2.9 (#1514) | Review: Security & PII Analysis             | Flag fields likely containing PII that are missing `writeOnly` or `x-pii` marker| `enhancement`, `ai`, `security`     | No  | Yes      |
| 2.10 (#1515) | One-Click Fix from AI Recommendation       | Apply a single AI suggestion to the schema with one click (with undo)            | `enhancement`, `ai`                 | No  | Yes      |
| 2.11 (#1516) | Pre-Publish AI Review Gate                 | Optionally require AI review before a schema version can be published            | `enhancement`, `ai`                 | No  | No       |
| 2.12 (#1517) | Scheduled Periodic AI Reviews              | Cron-triggered reviews on a configured cadence (weekly, monthly)                 | `enhancement`, `ai`                 | No  | Yes      |

### Detailed Issue Descriptions

#### 2.2 (#1507) — Schema Generation from User Stories

Accept a natural-language user-story or scenario description and return a structured schema definition (classes, properties, relationships, CRUD endpoint stubs). The model receives a system prompt that includes the current project's existing classes as context to avoid duplicates and enforce consistency.

**OpenAPI Endpoints:**
```
POST /api/v1/ai/generate/schema
  Body: {
    prompt: string,        // user story or scenario description
    domain_hint?: string,  // e-commerce | saas | social | healthcare | education
    project_id: UUID,
    version_id: UUID
  }
  → 200: GeneratedSchemaProposal {
      classes: ClassDefinition[],
      relationships: Relationship[],
      suggested_endpoints: OperationStub[]
    }
  → 429: RateLimitError
```

**Acceptance Criteria:**
- Generated classes do not duplicate existing class names in the target version
- Each generated class includes at minimum: name, description, and 3+ properties with types
- The prompt includes existing schema context to prevent naming collisions
- Response time ≤ 15 seconds for prompts under 500 tokens

**Tech Stack:** Ollama `generate` endpoint, JSON Schema output parsing, schema context serialization

Part of Epic: AI-Powered Schema Tools

---

#### 2.5 (#1510) — AI Schema Review — On-Demand Trigger

Implement a "Review Schema" command in the AI chat and via a dedicated toolbar button in the studio. The review serializes the entire schema (classes + properties + relationships) and sends it to the AI with a structured review prompt. The response is parsed into a `ReviewResult[]` with severity, category, target node, and recommendation fields.

```
POST /api/v1/ai/review/schema
  Body: { project_id, version_id, review_categories?: [] }
  → 202: { review_id }

GET /api/v1/ai/review/{review_id}
  → 200: ReviewResult {
      status: pending | complete,
      items: [{
        severity: error | warning | info,
        category: naming | documentation | relationships | security | best_practices,
        target_node_id: UUID,
        message: string,
        suggestion: string,
        fixable: boolean
      }]
    }
```

**Acceptance Criteria:**
- Review runs asynchronously; poll endpoint returns status
- Results grouped by severity in the UI (errors first)
- Each result links to the specific class or property in the canvas
- Review history stored and viewable (last 10 reviews per project)

Part of Epic: AI-Powered Schema Tools

---

## Epic 3 (#1518): AI Documentation Generation

### Summary Table

| #   | Title                                      | Description                                                                      | Labels                          | MVP | Parallel |
|-----|--------------------------------------------|----------------------------------------------------------------------------------|---------------------------------|-----|----------|
| 3.1 (#1519) | Code Snippet Generation (Multi-Language)   | Generate curl, TS, Python, Java, Go snippets for each API operation              | `enhancement`, `mvp`, `ai`     | Yes | No       |
| 3.2 (#1520) | Realistic Payload Generation               | Generate semantically meaningful example request/response bodies                 | `enhancement`, `ai`             | No  | Yes      |
| 3.3 (#1521) | Getting Started Guide Generation           | Auto-draft a getting-started markdown guide for the API                          | `enhancement`, `ai`             | No  | Yes      |
| 3.4 (#1522) | Authentication Guide Generation            | Generate auth guide covering API keys, OAuth 2.0, and session flows              | `enhancement`, `ai`             | No  | Yes      |
| 3.5 (#1523) | Error Handling Guide Generation            | Document all error response schemas and when each is returned                    | `enhancement`, `ai`             | No  | Yes      |
| 3.6 (#1524) | Migration Guide Generation                 | Compare two versions and generate a human-readable migration guide for consumers | `enhancement`, `ai`             | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#1519) — Code Snippet Generation (Multi-Language)

For each OpenAPI operation defined in the project's Paths, generate ready-to-use code snippets in: curl, JavaScript (fetch + axios), TypeScript, Python (requests + httpx), Java (OkHttp), and Go (net/http). Snippets include authentication headers, realistic request bodies, and error handling patterns.

**OpenAPI Endpoints:**
```
POST /api/v1/ai/generate/snippets
  Body: { operation_id, languages: string[], api_key_hint?: string }
  → 200: SnippetSet { [language: string]: string }
```

**Acceptance Criteria:**
- Snippets are syntactically valid (linted via language-specific validators in CI)
- Snippets use the operation's request schema to populate a realistic body
- Output rendered in a tabbed code viewer in the documentation panel
- Snippets regenerated automatically when operation schema changes

Part of Epic: AI Documentation Generation

---

## Epic 4 (#1525): AI Administration & Privacy

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                               | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|--------------------------------------|-----|----------|
| 4.1 (#1526) | Ollama Cluster Admin Settings              | Admin UI for configuring primary + failover URLs, load balancing, health checks   | `enhancement`, `mvp`, `ai`          | Yes | No       |
| 4.2 (#1527) | Model Configuration per Use Case           | Select default model for chat, generation, and review; configure temperature      | `enhancement`, `mvp`, `ai`          | Yes | Yes      |
| 4.3 (#1528) | Per-Tenant AI Feature Toggles              | Enable/disable individual AI capabilities per tenant                              | `enhancement`, `mvp`, `ai`          | Yes | Yes      |
| 4.4 (#1529) | AI Usage Limits Configuration              | Set req/hour per user and req/day per tenant limits per subscription tier         | `enhancement`, `mvp`, `ai`          | Yes | Yes      |
| 4.5 (#1530) | AI Interaction Audit Log                   | Immutable log of every AI request: user, model, prompt hash, response hash, time  | `enhancement`, `mvp`, `ai`, `rest`  | Yes | No       |
| 4.6 (#1531) | PII Detection & Redaction in Prompts       | Scan prompts for PII patterns and redact before sending to Ollama                 | `enhancement`, `ai`, `security`     | No  | Yes      |
| 4.7 (#1532) | Conversation Encryption at Rest            | Encrypt stored conversation history using per-tenant AES-256 keys                | `enhancement`, `ai`, `security`     | No  | Yes      |
| 4.8 (#1533) | AI Personalization: Accepted vs Rejected   | Track accepted/rejected suggestions to improve future recommendations             | `enhancement`, `ai`                 | No  | No       |
| 4.9 (#1534) | Custom Prompt Templates                    | Save, categorize, and share prompt templates within a team                        | `enhancement`, `ai`                 | No  | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#1526) — Ollama Cluster Admin Settings

Provide a Super Admin settings page (`/admin/ai`) for configuring the Ollama cluster. Admins can add/remove server endpoints, set the load balancing strategy, configure the health check interval, and view current endpoint status (healthy/unhealthy, latency, active connections).

```
Admin → AI Settings
┌────────────────────────────────────────────────────────┐
│  Ollama Cluster Configuration                [Save]    │
├────────────────────────────────────────────────────────┤
│  Load Balancing:  [Round Robin ▼]                      │
│  Health Check:    [30] seconds                         │
│                                                        │
│  Endpoints:                                            │
│  ✓ http://ollama-1:11434  42ms  [Test] [Remove]        │
│  ✓ http://ollama-2:11434  38ms  [Test] [Remove]        │
│  ✗ http://ollama-3:11434  —    OFFLINE [Test] [Remove] │
│  [+ Add Endpoint]                                      │
└────────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- "Test" button pings the endpoint and shows response time
- Unhealthy endpoints highlighted in red and excluded from routing
- Configuration changes take effect within one health check interval
- Settings persisted in `ai_cluster_config` table; changes audit-logged

**Tech Stack:** Next.js server action, PostgreSQL `ai_cluster_config`, real-time status via polling

Part of Epic: AI Administration & Privacy

---

#### 4.5 (#1530) — AI Interaction Audit Log

Create an immutable `ai_audit_log` table that records every AI request. Store: `tenant_id`, `user_id`, `model`, `feature` (chat/generate/review/snippet), `prompt_hash` (SHA-256, not raw prompt), `response_hash`, `token_count`, `duration_ms`, and `occurred_at`. Expose a paginated, filterable viewer for Super Admins.

**OpenAPI Endpoints:**
```
GET /api/v1/admin/ai/audit-log
  ?tenant_id=&user_id=&feature=&from=&to=&limit=50&cursor=
  → 200: AuditLogPage
```

**Acceptance Criteria:**
- `ai_audit_log` rows are insert-only (no UPDATE or DELETE permissions)
- Prompt content is never stored — only SHA-256 hash
- Log is exportable as CSV for compliance review
- Retention policy defaults to 1 year; configurable by Super Admin

Part of Epic: AI Administration & Privacy
