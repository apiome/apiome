# Apiome: Copilot (AI Assistant) - Feature Roadmap

> An AI-powered assistant that goes beyond schema generation to become a full development partner, integrated across the entire software development lifecycle—from natural language design through code review and documentation.
>
> **Revenue Model**: AI credit system, enterprise unlimited AI access
>
> **Tech Stack**: NextJS (app router), Radix UI, Ollama (self-hosted LLMs: Qwen 2.5, Llama 3.2), PostgreSQL, OpenAPI 3.1, WebSocket (streaming responses)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Conversational schema design from natural language descriptions with iterative refinement
- Domain-specific understanding for common verticals (e-commerce, SaaS, healthcare, fintech)
- Full CRUD application scaffolding from a published schema (TypeScript/Python)
- Admin panel generation with list/detail/edit views from schema definitions
- Schema quality analysis with actionable optimization recommendations
- Auto-generated API documentation and integration guides from schemas
- AI credit tracking and usage limits per tenant
- Chat history persistence with context window management

---

## Epic 1: Natural Language Schema Designer

### Summary Table

| #   | Title                                  | Description                                                                     | Labels                                   | Parallel |
|-----|----------------------------------------|---------------------------------------------------------------------------------|------------------------------------------|----------|
| 1.1 (#982) | Conversational Design Interface        | Chat-based UI for describing schemas in plain English with streaming responses   | `enhancement`, `mvp`, `copilot`, `ai-generated` | Yes      |
| 1.2 (#983) | Domain-Specific Language Understanding | Pre-trained domain recognizers for e-commerce, SaaS, healthcare, fintech        | `enhancement`, `mvp`, `copilot`, `ai-generated` | Yes      |
| 1.3 (#984) | Schema Generation Pipeline             | LLM output → JSON Schema → Apiome schema import pipeline                   | `enhancement`, `mvp`, `copilot`, `rest`  | No       |
| 1.4 (#985) | Iterative Refinement & Constraints     | Multi-turn conversation for adding validations, relationships, and constraints   | `enhancement`, `mvp`, `copilot`, `ai-generated` | No       |
| 1.5 (#986) | Schema Preview & Accept Workflow       | Visual diff and one-click import of AI-generated schemas into a project          | `enhancement`, `mvp`, `copilot`          | Yes      |

### Detailed Issue Descriptions

---

#### 1.1 (#982) — Conversational Design Interface

The entry point for Copilot is a conversational interface where developers describe what they want to build in plain English. This issue delivers the chat UI, the WebSocket streaming connection to the Ollama backend, and the prompt engineering layer that translates conversational input into schema generation instructions.

The chat interface is a NextJS page at `/copilot/designer` with a persistent sidebar showing conversation history and a main panel for the active conversation. Messages stream in real-time over a WebSocket connection to the backend, which proxies to the Ollama cluster. The UI renders AI responses progressively as tokens arrive, using a markdown renderer for explanatory text and a syntax-highlighted code block for generated schema fragments.

The prompt engineering layer wraps user input in a system prompt that instructs the LLM to output valid JSON Schema with Apiome-compatible extensions (`x-apiome-class`, `x-apiome-relationships`). The system prompt includes few-shot examples of high-quality schema output and instructions to ask clarifying questions when the input is ambiguous rather than guessing.

```
┌─────────────────────────────────────────────────┐
│  /copilot/designer                              │
│                                                 │
│  ┌──────────┐  ┌──────────────────────────────┐ │
│  │ History  │  │  Chat Panel                  │ │
│  │          │  │                              │ │
│  │ conv-1   │  │  User: I need a billing      │ │
│  │ conv-2   │  │  system with subscriptions   │ │
│  │ conv-3   │  │  and usage metering.         │ │
│  │          │  │                              │ │
│  │          │  │  AI: I'll design that. Here  │ │
│  │          │  │  are the classes I recommend: │ │
│  │          │  │                              │ │
│  │          │  │  ┌──────────────────────────┐│ │
│  │          │  │  │ {schema preview panel}   ││ │
│  │          │  │  └──────────────────────────┘│ │
│  │          │  │                              │ │
│  │          │  │  [Accept] [Refine] [Discard] │ │
│  │          │  │                              │ │
│  │          │  │  ┌──────────────────────┐    │ │
│  │          │  │  │  Type a message...   │    │ │
│  │          │  │  └──────────────────────┘    │ │
│  └──────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

**Acceptance Criteria**

- Chat messages stream token-by-token via WebSocket with < 200ms time-to-first-token
- Conversation history is persisted in PostgreSQL and loadable from the sidebar
- Schema fragments in AI responses render in syntax-highlighted code blocks
- The system prompt produces valid JSON Schema output for well-formed natural language input
- Ambiguous input triggers clarifying questions rather than hallucinated schemas
- The chat input supports multi-line text and Shift+Enter for newlines

**Part of Epic: Natural Language Schema Designer**

---

#### 1.2 (#983) — Domain-Specific Language Understanding

A generic LLM lacks context about industry data models. This issue adds domain-specific prompt augmentation that activates when Copilot detects the user is describing a known domain (e-commerce, SaaS, healthcare, fintech), injecting domain-specific terminology, common entity patterns, and relationship templates into the generation context.

Domain detection runs as a lightweight classifier on the user's first message. When a domain is identified with high confidence, the system prompt is augmented with a domain-specific knowledge pack: canonical entity names (e.g., "Product", "SKU", "Cart", "Order" for e-commerce), standard relationships (Order has many LineItems, LineItem references Product), and industry-specific constraints (healthcare: HIPAA-related field annotations, fintech: PCI-DSS sensitive field markers).

Knowledge packs are stored as JSON documents in PostgreSQL and loaded via `GET /api/v1/copilot/domains`. Admins can create custom domain packs via `POST /api/v1/copilot/domains` for tenant-specific terminology. The API also exposes `GET /api/v1/copilot/domains/{domainId}/entities` for listing canonical entities in a domain.

The domain recognizer and knowledge packs are versioned independently of the LLM, allowing updates to domain knowledge without retraining. When a domain is detected, the chat UI displays a Radix `Badge` indicating the active domain, with a `DropdownMenu` to manually switch or disable domain augmentation.

**Acceptance Criteria**

- At least 5 domains are supported out of the box: e-commerce, SaaS, healthcare, fintech, education
- Domain detection activates automatically on the first message with > 80% confidence
- Domain augmentation produces domain-appropriate entity names and relationship patterns
- Custom domain packs are creatable via REST API for tenant-specific terminology
- A Radix `Badge` + `DropdownMenu` in the chat UI shows the active domain and allows manual override
- Domain augmentation is optional and can be disabled without affecting core schema generation

**Part of Epic: Natural Language Schema Designer**

---

#### 1.3 (#984) — Schema Generation Pipeline

The LLM produces text that looks like JSON Schema, but it may contain hallucinated fields, invalid references, or non-standard extensions. This issue builds the pipeline that validates, normalizes, and converts raw LLM output into proper Apiome schemas ready for import.

The pipeline runs in three stages: (1) **Parse** — extract JSON from the LLM's markdown-formatted response, handling partial outputs and common formatting errors. (2) **Validate** — run the extracted JSON through a JSON Schema meta-validator to ensure it is itself valid JSON Schema, checking for required fields like `type`, `properties`, and valid `$ref` pointers. (3) **Normalize** — map the schema to Apiome's internal format, creating class definitions, adding missing descriptions with LLM-generated defaults, and resolving relationships into Apiome's link model.

When validation fails, the pipeline feeds the errors back to the LLM as a follow-up prompt ("The schema you generated has these issues: ... Please fix them.") and retries up to 3 times before surfacing the errors to the user. This self-healing loop means most generation errors are invisible to the user.

The pipeline is exposed as a REST endpoint `POST /api/v1/copilot/generate` that accepts a conversation context and returns the normalized Apiome schema. It also powers the inline generation within the chat interface (1.1).

**Acceptance Criteria**

- Raw LLM output is parsed even when wrapped in markdown code fences or contains trailing text
- Generated schemas pass JSON Schema draft 2020-12 meta-validation
- Invalid schemas trigger an automatic self-healing retry loop (up to 3 retries)
- Normalized output maps to Apiome's class definition format with proper `$ref` resolution
- The pipeline endpoint returns structured errors when all retries are exhausted
- Generated schemas include `description` fields for all properties (LLM-generated if not explicitly stated)

**Part of Epic: Natural Language Schema Designer**

---

#### 1.4 (#985) — Iterative Refinement & Constraints

First-pass schema generation rarely captures all requirements. This issue extends the conversational interface to support multi-turn refinement where users add validations, constraints, relationships, and modifications to a previously generated schema through natural language.

The refinement engine maintains a working schema in memory across conversation turns. When the user says "add email validation to the User class" or "make the status field an enum with values active, suspended, closed", the engine generates a targeted patch to the working schema rather than regenerating the entire thing. Patches are displayed as diffs in the chat, showing exactly what changed.

Cross-reference refinements are supported: "the Order class should reference the Customer class" generates a `$ref` relationship and updates both classes. The engine tracks all relationships in a dependency graph so that changes to a referenced class can trigger suggestions for dependent classes ("You changed the Customer ID to UUID—should I update the Order's customer reference too?").

Constraint expressions are translated to JSON Schema keywords: "name must be at least 2 characters" → `minLength: 2`, "price must be positive" → `exclusiveMinimum: 0`, "email must be valid" → `format: email`. The engine understands approximately 30 common constraint patterns and falls back to asking for clarification on ambiguous ones.

**Acceptance Criteria**

- Multi-turn refinements produce targeted patches displayed as diffs, not full regeneration
- Adding a validation constraint translates to the correct JSON Schema keyword
- Relationship references between classes are created with proper `$ref` pointers
- Changes to a referenced class trigger suggestions for updating dependent classes
- The working schema is persisted across conversation turns and survives page refresh
- At least 30 common constraint patterns are recognized (minLength, maximum, format, enum, etc.)

**Part of Epic: Natural Language Schema Designer**

---

#### 1.5 (#986) — Schema Preview & Accept Workflow

Before a generated schema enters the Apiome project, users need to see exactly what will be created and have the chance to make final adjustments. This issue builds the preview and accept workflow that bridges AI generation and project import.

The preview panel renders the generated schema as a visual card layout matching Apiome's schema canvas style. Each class is displayed as a card with its properties, types, constraints, and relationships. A diff view highlights what is new vs. what already exists in the project (for refinements to existing schemas). The preview uses Radix `Tabs` to switch between "Visual" (card layout), "JSON Schema" (raw JSON), and "Diff" (before/after) views.

The "Accept" action calls `POST /api/v1/copilot/import` which creates the schema classes, properties, and relationships in the active Apiome project as a draft version. The "Refine" action returns to the chat with the current schema as context. The "Discard" action clears the working schema and conversation (with a Radix `AlertDialog` confirmation).

Import conflict resolution handles cases where the generated schema overlaps with existing classes in the project. The preview highlights conflicts (same class name, incompatible property types) and offers merge strategies: overwrite, rename, or skip.

**Acceptance Criteria**

- Preview renders all generated classes as visual cards with properties, types, and relationships
- Diff view shows additions/modifications/deletions relative to the current project state
- "Accept" imports the schema into the active project as a draft version via REST API
- Import conflict detection identifies overlapping class names and incompatible types
- Merge strategies (overwrite, rename, skip) are selectable per-conflict via Radix `RadioGroup`
- "Discard" requires confirmation via Radix `AlertDialog` before clearing the working schema

**Part of Epic: Natural Language Schema Designer**

---

## Epic 2: Application Scaffolding Engine

### Summary Table

| #   | Title                                  | Description                                                                     | Labels                                   | Parallel |
|-----|----------------------------------------|---------------------------------------------------------------------------------|------------------------------------------|----------|
| 2.1 (#988) | CRUD Application Generator             | Generate full CRUD apps (NextJS/Express) from published schema definitions      | `enhancement`, `mvp`, `copilot`, `rest`  | Yes      |
| 2.2 (#989) | Microservice Template Engine           | Scaffold microservices with API routes, database models, and Docker configs     | `enhancement`, `copilot`, `rest`         | Yes      |
| 2.3 (#990) | Admin Panel Generator                  | Generate admin panels with list/detail/edit/delete views from schemas           | `enhancement`, `mvp`, `copilot`          | Yes      |
| 2.4 (#991) | Mobile App Skeleton Generator          | Scaffold React Native and Flutter app structures from schemas                   | `enhancement`, `copilot`                 | Yes      |
| 2.5 (#992) | Code Template Registry                 | Manage and version code generation templates for different frameworks           | `enhancement`, `copilot`, `rest`         | No       |

### Detailed Issue Descriptions

---

#### 2.1 (#988) — CRUD Application Generator

Schemas define the data model; the next step is a working application. This issue builds the CRUD generator that takes a published Apiome schema and produces a complete, runnable application with create, read, update, delete, and list operations for every schema class.

The generator supports two target frameworks: NextJS (app router with server actions) and Express + TypeScript. For NextJS, it produces: page routes for list and detail views, server actions for mutations, Prisma schema for database access, and Zod validation schemas derived from the JSON Schema. For Express, it produces: route handlers, controller classes, Prisma models, and request validation middleware.

Code generation uses a template engine (Handlebars) with templates stored in a registry (issue 2.5). The generator resolves schema relationships to produce joined queries and nested forms. For a one-to-many relationship (Order → LineItems), the generated detail page includes an inline table of related records with add/edit/delete capabilities.

The generation endpoint is `POST /api/v1/copilot/scaffold/crud` accepting `schemaId`, `framework` (nextjs | express), and `options` (authentication: boolean, pagination: boolean, search: boolean). The generated code is returned as a downloadable ZIP or pushed to a connected Git repository.

**Acceptance Criteria**

- NextJS output includes app router pages, server actions, Prisma schema, and Zod validators
- Express output includes route handlers, controllers, Prisma models, and validation middleware
- One-to-many relationships produce nested list views on the parent's detail page
- Many-to-many relationships produce association management UI/endpoints
- Generated applications are immediately runnable with `npm install && npm run dev`
- Output is available as a downloadable ZIP via REST API

**Part of Epic: Application Scaffolding Engine**

---

#### 2.2 (#989) — Microservice Template Engine

Modern architectures decompose into services. This issue builds a microservice scaffolder that generates a standalone, production-ready service from a schema definition, complete with API routes, database models, Docker configuration, health checks, and OpenAPI documentation.

Each generated microservice includes: a Dockerfile with multi-stage build, docker-compose for local development with a database, environment configuration (.env template with validation), health check endpoint (`/health`), readiness endpoint (`/ready`), graceful shutdown handling, structured JSON logging, and an auto-generated OpenAPI 3.1 spec that matches the Apiome schema.

The scaffolder supports three architectures: (1) **monolith-ready** — a single service with all schema classes, (2) **domain-split** — one service per bounded context (grouping related classes), (3) **class-per-service** — one microservice per schema class (for maximum decomposition). The architecture choice is specified via `POST /api/v1/copilot/scaffold/microservice` with a `strategy` parameter.

Inter-service communication stubs are generated for the domain-split and class-per-service strategies. When schema classes reference each other across service boundaries, the scaffolder generates HTTP client stubs with retry logic and circuit breaker patterns for cross-service calls.

**Acceptance Criteria**

- Generated services include Dockerfile, docker-compose, .env template, and health/readiness endpoints
- OpenAPI 3.1 spec is auto-generated and served at `/docs` by the service
- Domain-split strategy correctly groups related classes into bounded contexts
- Cross-service references produce HTTP client stubs with retry and circuit breaker logic
- Services start successfully with `docker-compose up` from the generated output
- Structured JSON logging is configured with request ID correlation

**Part of Epic: Application Scaffolding Engine**

---

#### 2.3 (#990) — Admin Panel Generator

Every application needs an admin interface for data management. This issue generates full-featured admin panels from Apiome schemas with list views (searchable, sortable, paginated tables), detail views, create/edit forms with schema-driven validation, and delete confirmation dialogs.

The admin panel is generated as a NextJS application using Radix UI components throughout. List views use Radix `Table` with sortable column headers and a search input. Detail views render each field with the appropriate Radix input component based on the schema type: `TextField` for strings, `Select` for enums, `Checkbox` for booleans, `TextArea` for long text, and a date picker for date-time fields. Required fields are marked and validated before submission.

Relationships are rendered as navigation links and inline editors. A one-to-many relationship displays a collapsible Radix `Accordion` section on the parent detail page listing child records. Many-to-many relationships render as a multi-select Radix `Combobox` with search.

The admin panel includes authentication (NextAuth.js with configurable providers) and role-based access. The generator produces an admin role that can CRUD all records and a viewer role with read-only access. Configuration is via `POST /api/v1/copilot/scaffold/admin` with `schemaId`, `authProvider` (credentials | google | github), and `theme` (light | dark).

**Acceptance Criteria**

- List views render sortable, paginated tables with search using Radix `Table`
- Create/edit forms use schema-appropriate Radix input components with validation
- Boolean fields render as `Checkbox`, enums as `Select`, dates as date pickers
- One-to-many relationships display inline child record lists with add/edit/delete
- NextAuth.js authentication is configured with the selected provider
- Generated admin panels start and function correctly with `npm install && npm run dev`

**Part of Epic: Application Scaffolding Engine**

---

#### 2.4 (#991) — Mobile App Skeleton Generator

Mobile teams need a head start too. This issue generates mobile app skeletons from Apiome schemas for React Native and Flutter, including type-safe models, API client code, navigation structure, and basic list/detail screens.

For React Native, the generator produces: TypeScript models matching the schema, an API client with fetch-based HTTP calls, React Navigation setup with stack and tab navigators, list screens with FlatList and pull-to-refresh, and detail screens with form inputs. For Flutter, it produces: Dart model classes with JSON serialization, a Dio-based API client, GoRouter navigation, ListView screens, and form screens with TextFormField widgets.

The generated models include serialization/deserialization code that matches the schema's type definitions. Enum properties produce TypeScript/Dart enums. Optional fields are correctly typed as nullable. Nested objects produce nested model classes with proper import paths.

Generation is triggered via `POST /api/v1/copilot/scaffold/mobile` with `schemaId`, `platform` (react-native | flutter), and `apiBaseUrl`. The output is a downloadable ZIP or Git push.

**Acceptance Criteria**

- React Native output includes TypeScript models, API client, navigation, and list/detail screens
- Flutter output includes Dart models, Dio client, GoRouter navigation, and list/detail screens
- Generated models correctly handle nullable fields, enums, and nested objects
- API client code targets the configured `apiBaseUrl` with proper error handling
- Generated apps compile and run on their respective platforms without modification
- Models serialize/deserialize to JSON matching the Apiome schema's type definitions

**Part of Epic: Application Scaffolding Engine**

---

#### 2.5 (#992) — Code Template Registry

The scaffolding engine's flexibility depends on its template library. This issue builds the registry that stores, versions, and manages Handlebars templates for all code generation targets, allowing tenants to customize templates and community contributors to share new ones.

Templates are organized by target: `nextjs-crud`, `express-crud`, `nextjs-admin`, `react-native`, `flutter`, `microservice-express`, etc. Each template is a bundle containing Handlebars `.hbs` files, a `manifest.json` describing the template's inputs and outputs, and optional static files (configuration, assets) that are copied verbatim into the generated output.

The registry API exposes `GET /api/v1/copilot/templates` for listing, `POST /api/v1/copilot/templates` for publishing, and `GET /api/v1/copilot/templates/{id}/versions` for version history. Templates are versioned with semver. When a user scaffolds an application, they can pin a template version or use `latest`.

Tenant-specific template overrides allow enterprises to inject their coding standards, internal libraries, and configuration patterns into generated output. Overrides are stored per-tenant and merged with the base template at generation time. The template management UI is a NextJS page at `/copilot/templates` using Radix `Table` for the template list, `Dialog` for template upload, and `Tabs` for switching between built-in and custom templates.

**Acceptance Criteria**

- Templates are stored as versioned bundles with Handlebars files and a manifest
- The registry supports listing, publishing, and version history via REST API
- Template version pinning works: `latest` resolves to the newest version, explicit versions are honored
- Tenant-specific overrides merge with base templates at generation time
- The `/copilot/templates` page displays templates with version info using Radix `Table` and `Tabs`
- Template bundles include a `manifest.json` that declares required input variables

**Part of Epic: Application Scaffolding Engine**

---

## Epic 3: Intelligent Analysis & Refactoring

### Summary Table

| #   | Title                                    | Description                                                                     | Labels                                   | Parallel |
|-----|------------------------------------------|---------------------------------------------------------------------------------|------------------------------------------|----------|
| 3.1 (#994) | Usage-Based Optimization Recommendations | Analyze API usage patterns and suggest schema optimizations                     | `enhancement`, `copilot`, `ai-generated` | Yes      |
| 3.2 (#995) | Automated Schema Normalization           | Detect and suggest normalization of redundant or denormalized schema structures | `enhancement`, `copilot`, `ai-generated` | Yes      |
| 3.3 (#996) | Performance Impact Analysis              | Predict performance implications of schema changes before they ship            | `enhancement`, `copilot`                 | Yes      |
| 3.4 (#997) | Breaking Change Mitigation Engine        | Detect breaking changes and generate migration strategies automatically        | `enhancement`, `copilot`, `rest`         | No       |
| 3.5 (#998) | Schema Quality Scoring                   | Compute and display a quality score for schemas based on best practices        | `enhancement`, `mvp`, `copilot`          | Yes      |

### Detailed Issue Descriptions

---

#### 3.1 (#994) — Usage-Based Optimization Recommendations

Schemas are designed once but used continuously. Over time, actual usage patterns diverge from the original design assumptions. This issue builds an analysis engine that examines real API usage data (which fields are queried, which are rarely populated, which endpoints see the most traffic) and generates optimization recommendations.

The engine connects to the gateway's usage metrics (if Gateway is deployed) or accepts uploaded usage logs. It computes: (1) field population rates — fields that are null/empty in > 90% of instances may be candidates for deprecation, (2) query patterns — fields used in filters/sorts that lack database indexes, (3) payload size — schemas with many rarely-used fields may benefit from a lean/full response split, (4) relationship traversal — relationships that are always resolved together may benefit from denormalization.

Recommendations are presented on a NextJS page at `/copilot/analysis/[schemaId]` with a prioritized list. Each recommendation includes the observation (data), the suggestion (action), the estimated impact (high/medium/low), and a one-click "Apply" button that generates the schema change as a draft. The page uses Radix `Accordion` for expandable recommendation details and `Badge` for impact levels.

The analysis runs on-demand via `POST /api/v1/copilot/analyze/{schemaId}` or can be scheduled to run weekly. Results are stored in PostgreSQL for trend tracking.

**Acceptance Criteria**

- Field population analysis identifies fields with > 90% null/empty rate
- Query pattern analysis detects frequently filtered fields without indexes
- Payload size analysis suggests field grouping for lean vs. full response patterns
- Recommendations include observation, suggestion, impact level, and one-click apply
- Analysis can run on-demand or on a weekly schedule via REST API
- The analysis page uses Radix `Accordion` and `Badge` for structured presentation

**Part of Epic: Intelligent Analysis & Refactoring**

---

#### 3.2 (#995) — Automated Schema Normalization

Schema designs often accumulate redundancy: the same address structure duplicated across Customer, Supplier, and Warehouse classes; phone number fields with inconsistent validation rules; or denormalized fields that could be derived from relationships. This issue builds a normalization analyzer that detects structural redundancy and suggests refactoring.

The analyzer examines all classes within a schema version and identifies: (1) duplicate property groups — sets of fields that appear identically across multiple classes (candidates for shared component extraction), (2) inconsistent constraints — the same semantic field (e.g., email) with different validation rules across classes, (3) denormalized data — fields that duplicate data available through a relationship traversal, (4) naming inconsistencies — the same concept with different property names across classes.

For each finding, the analyzer generates a concrete refactoring suggestion: extract a shared `Address` component, standardize email validation to a single pattern, or replace a denormalized field with a relationship reference. Suggestions include a before/after diff and an assessment of the breaking change impact.

The normalizer is accessible from the schema detail page via a "Analyze" button that triggers `POST /api/v1/copilot/normalize/{schemaId}`. Results render in a Radix `Dialog` with `Tabs` for each finding category.

**Acceptance Criteria**

- Duplicate property groups across classes are detected with > 85% structural similarity threshold
- Inconsistent constraints on semantically identical fields are flagged with suggested standard
- Denormalized fields that duplicate relationship data are identified
- Naming inconsistencies are detected using string similarity and semantic analysis
- Each finding includes a before/after diff and breaking change impact assessment
- Findings are categorized and navigable via Radix `Tabs` in the result dialog

**Part of Epic: Intelligent Analysis & Refactoring**

---

#### 3.3 (#996) — Performance Impact Analysis

Schema changes have downstream performance consequences: adding a required field to a high-traffic endpoint increases payload size; removing an index-backed field may slow queries; changing a type from integer to string affects storage and comparison performance. This issue builds a predictive analyzer that estimates performance impacts before schema changes are published.

The analyzer runs automatically when a schema version is prepared for publishing. It compares the draft changes against the current published version and computes: estimated payload size delta (bytes per response × daily request volume = daily bandwidth impact), query performance implications (added/removed fields that affect index usage), serialization cost changes, and storage growth projections.

Results are displayed as a "Performance Impact Report" on the version publish confirmation page. High-impact changes (> 10% payload increase, index removal) are flagged as warnings that require explicit acknowledgment before publishing. The report uses traffic lights (green/yellow/red) via Radix `Badge` for quick visual assessment.

The analysis endpoint is `POST /api/v1/copilot/performance-impact` accepting `schemaId`, `fromVersion`, and `toVersion`. It returns a structured report with per-field impact assessments.

**Acceptance Criteria**

- Payload size delta is computed per-field and aggregated across the schema change
- Index usage impact is flagged when removing or modifying fields used in database indexes
- Storage growth projections estimate the additional disk space for the schema change
- High-impact changes (> 10% payload increase) produce yellow/red warnings
- The performance report renders on the version publish confirmation page
- Analysis runs in < 5 seconds for schemas with up to 50 classes

**Part of Epic: Intelligent Analysis & Refactoring**

---

#### 3.4 (#997) — Breaking Change Mitigation Engine

Breaking changes are inevitable in evolving APIs. This issue builds an engine that detects breaking changes between schema versions and automatically generates migration strategies to minimize consumer impact—including adapter code, deprecation timelines, and consumer notification plans.

The detection engine classifies changes as: **breaking** (field removed, type changed incompatibly, required field added), **non-breaking** (field added as optional, description changed, example updated), or **potentially breaking** (enum value removed, constraint tightened). The classification follows the OpenAPI breaking change rules.

For each breaking change, the engine generates a mitigation strategy: (1) **adapter code** — a transformation function that converts v1 requests to v2 format, installable as a gateway transformation rule (Epic 3 of the Gateway roadmap), (2) **deprecation timeline** — a suggested schedule for deprecating the old version with consumer notification at 30/14/7/1 days before sunset, (3) **consumer impact report** — which API keys have accessed the affected endpoints in the last 30 days.

The mitigation engine integrates with the version publishing workflow. When a draft version contains breaking changes, the publish button is replaced with a "Publish with Migration Plan" flow that steps through each breaking change and its mitigation before finalizing.

**Acceptance Criteria**

- Breaking, non-breaking, and potentially-breaking changes are classified correctly per OpenAPI rules
- Adapter code is generated for each breaking change as a gateway-compatible transformation rule
- Deprecation timelines include configurable notification intervals (30/14/7/1 days)
- Consumer impact reports list API keys that accessed affected endpoints in the last 30 days
- The publish workflow requires mitigation acknowledgment for each breaking change
- Generated migration strategies are exportable as a markdown document

**Part of Epic: Intelligent Analysis & Refactoring**

---

#### 3.5 (#998) — Schema Quality Scoring

A schema quality score gives teams a single metric to track design health over time. This issue computes a quality score (0–100) based on weighted criteria and displays it prominently on the schema overview page, with drill-down into specific improvement areas.

The scoring rubric evaluates: **completeness** (25%) — all properties have descriptions, examples, and appropriate constraints; **consistency** (25%) — naming conventions are uniform, similar fields use similar types; **best practices** (25%) — no overly broad types (avoid `any`), proper use of `$ref` for shared structures, enum usage for fixed value sets; **security** (25%) — sensitive fields marked with `x-sensitive`, no PII in examples, authentication schemas present where needed.

```
┌────────────────────────────────────┐
│  Schema Quality Score              │
│                                    │
│        ┌──────────┐                │
│        │    87    │                │
│        │  /100    │                │
│        └──────────┘                │
│                                    │
│  Completeness     ████████░░  80%  │
│  Consistency      █████████░  90%  │
│  Best Practices   █████████░  92%  │
│  Security         ████████░░  85%  │
│                                    │
│  Top improvements:                 │
│  • Add descriptions to 12 fields   │
│  • Standardize date formats (3)    │
│  • Mark 2 PII fields as sensitive  │
└────────────────────────────────────┘
```

The score is computed via `GET /api/v1/copilot/quality/{schemaId}` and displayed as a Radix `Progress` bar on the schema overview page. Historical scores are tracked to show trend lines. The drill-down page lists individual findings with "Fix" buttons that generate the correction as a schema patch.

**Acceptance Criteria**

- Quality score computes a 0–100 value from four weighted categories
- Completeness checks verify descriptions, examples, and constraints on all properties
- Consistency checks detect naming convention violations and type inconsistencies
- Best practices checks flag `any` types, missing `$ref` usage, and missing enum definitions
- Historical scores are stored for trend visualization
- Individual findings include one-click "Fix" buttons that generate schema patches

**Part of Epic: Intelligent Analysis & Refactoring**

---

## Epic 4: Code Review & Documentation Automation

### Summary Table

| #   | Title                                | Description                                                                     | Labels                                   | Parallel |
|-----|--------------------------------------|---------------------------------------------------------------------------------|------------------------------------------|----------|
| 4.1 (#1000) | PR Schema Compatibility Review       | Automated PR review that checks code changes for schema compatibility           | `enhancement`, `copilot`, `ai-generated` | Yes      |
| 4.2 (#1001) | Schema Drift Detection               | Detect when code and schema definitions diverge over time                       | `enhancement`, `copilot`, `rest`         | Yes      |
| 4.3 (#1002) | API Documentation Generator          | Auto-generate user guides and integration tutorials from schemas                | `enhancement`, `mvp`, `copilot`          | Yes      |
| 4.4 (#1003) | Changelog & Migration Guide Generator| Generate human-readable changelogs and migration guides for version transitions | `enhancement`, `copilot`                 | No       |
| 4.5 (#1004) | AI Credit & Usage Management         | Track AI credit consumption, enforce limits, and manage enterprise AI budgets   | `enhancement`, `mvp`, `copilot`, `rest`  | Yes      |

### Detailed Issue Descriptions

---

#### 4.1 (#1000) — PR Schema Compatibility Review

Schema changes often happen in code (model definitions, API handlers, validation logic) without updating the Apiome schema, or vice versa. This issue builds a GitHub integration that reviews pull requests for schema compatibility issues.

The integration registers as a GitHub App that receives webhook events on PR creation and update. When a PR is opened, the reviewer fetches the changed files and analyzes: (1) model definition changes (Prisma, TypeORM, Mongoose) — do they match the current Apiome schema? (2) API handler changes — do request/response shapes align with the schema? (3) Validation changes — are constraints consistent with the schema's JSON Schema rules? (4) Test changes — do mock data shapes match the schema?

The review posts comments directly on the PR as a GitHub check, with inline annotations on specific lines where incompatibilities are detected. Each annotation includes the expected schema shape, the actual code shape, and a suggested fix. The overall check passes/fails based on whether any blocking incompatibilities were found.

Configuration is per-repository via a `.apiome.yml` file that specifies the Apiome project ID, schema version to check against, and file patterns to scan. The GitHub App is registered via `POST /api/v1/copilot/integrations/github` with repository and installation details.

**Acceptance Criteria**

- PR review triggers automatically on PR creation and push events via GitHub webhook
- Model definition changes (Prisma/TypeORM) are compared against the Apiome schema
- Incompatibilities produce inline PR comments with expected vs. actual shapes
- A GitHub check status (pass/fail) is reported on the PR
- Configuration is managed via `.apiome.yml` in the repository root
- The integration is installable as a GitHub App via the Copilot settings page

**Part of Epic: Code Review & Documentation Automation**

---

#### 4.2 (#1001) — Schema Drift Detection

Over time, the deployed application's data shapes may drift from the schema definitions—new fields added in code but not in the schema, or schema changes that were never reflected in the codebase. This issue builds a continuous drift detector that compares live application behavior against the published schema.

The drift detector runs in two modes: (1) **static analysis** — scan the codebase for model definitions and compare their structure against the Apiome schema, and (2) **runtime analysis** — sample live API traffic (via the gateway) and compare actual request/response payloads against the schema. Runtime analysis is opt-in and only runs in staging/development environments by default.

Detected drift is categorized as: **schema-only** (field exists in schema but not in code/traffic), **code-only** (field exists in code/traffic but not in schema), or **type mismatch** (field exists in both but with incompatible types). Each drift finding includes the source evidence (file path and line, or sample request ID) and a recommended action (update schema, update code, or investigate).

Drift reports are accessible at `/copilot/drift/[projectId]` and via `GET /api/v1/copilot/drift/{projectId}`. Scheduled weekly scans are configurable via `POST /api/v1/copilot/drift/{projectId}/schedule`.

**Acceptance Criteria**

- Static analysis detects fields present in code but absent from the schema (and vice versa)
- Runtime analysis samples gateway traffic and detects payload shapes that diverge from the schema
- Type mismatches between code and schema are flagged with both sources referenced
- Drift findings include recommended actions (update schema, update code, investigate)
- Weekly scheduled scans are configurable via REST API
- Drift reports are persisted and viewable at `/copilot/drift/[projectId]`

**Part of Epic: Code Review & Documentation Automation**

---

#### 4.3 (#1002) — API Documentation Generator

Good documentation is essential but tedious to maintain manually. This issue builds a documentation generator that produces comprehensive API guides from Apiome schemas, including getting-started tutorials, authentication guides, endpoint references, and code examples in multiple languages.

The generator uses the Ollama LLM to produce human-quality prose from schema definitions. For each schema class, it generates: a conceptual overview explaining the entity's purpose, field-by-field documentation with examples, relationship explanations with navigation examples, and code snippets in JavaScript, Python, Go, and Java showing how to create, read, update, and delete instances.

Generated documentation is output in two formats: Markdown (for Git repository hosting) and HTML (for the developer portal). The generator supports customization via a documentation template that controls tone (formal/casual), detail level (concise/comprehensive), and which code languages to include.

The generation endpoint is `POST /api/v1/copilot/docs/generate` with `schemaId`, `format` (markdown | html), and `template` parameters. Generated docs are downloadable or automatically committed to a configured Git repository. The docs management page at `/copilot/docs` uses Radix `Table` for listing generated docs, `Tabs` for format switching, and `Dialog` for template configuration.

**Acceptance Criteria**

- Generated docs include conceptual overview, field-by-field reference, and relationship explanations
- Code snippets are produced in JavaScript, Python, Go, and Java for CRUD operations
- Markdown and HTML output formats are supported
- Documentation templates allow customization of tone, detail level, and code languages
- Generated docs are downloadable as a ZIP or committable to a Git repository
- Regeneration detects schema changes and updates only the affected sections

**Part of Epic: Code Review & Documentation Automation**

---

#### 4.4 (#1003) — Changelog & Migration Guide Generator

When schema versions change, consumers need to know what changed and how to adapt. This issue generates human-readable changelogs and step-by-step migration guides for version transitions.

The changelog generator computes a structural diff between two schema versions and produces a categorized changelog: **Added** (new classes, new fields, new endpoints), **Changed** (type changes, constraint modifications, renamed fields), **Deprecated** (fields or classes marked for removal), and **Removed** (fields or classes deleted). Each entry includes the affected class, field, and a human-readable description of the change.

The migration guide goes deeper: for each breaking change, it provides step-by-step instructions for updating client code, including before/after code examples. For non-breaking changes, it explains what new capabilities are available. The guide is written by the LLM using the structural diff as context, producing natural prose rather than mechanical listings.

Generation is triggered automatically when a version is published or on-demand via `POST /api/v1/copilot/changelog` with `schemaId`, `fromVersion`, `toVersion`. Output is available as Markdown. The changelog is displayed on the schema version page and linked from the developer portal.

**Acceptance Criteria**

- Changelogs categorize changes as Added, Changed, Deprecated, or Removed
- Each changelog entry references the affected class and field with a human-readable description
- Migration guides include before/after code examples for breaking changes
- Guides are produced in natural prose, not mechanical diff listings
- Changelog generation triggers automatically on version publish
- Generated changelogs are displayed on the schema version page and linked from the developer portal

**Part of Epic: Code Review & Documentation Automation**

---

#### 4.5 (#1004) — AI Credit & Usage Management

Copilot features consume LLM inference resources. This issue builds the credit tracking and management system that meters AI usage, enforces tenant-level limits, and provides visibility into consumption patterns for billing and capacity planning.

Each AI operation is assigned a credit cost based on complexity: simple chat messages cost 1 credit, schema generation costs 5 credits, full application scaffolding costs 20 credits, analysis operations cost 10 credits, and documentation generation costs 15 credits. Credits are deducted from the tenant's balance when the operation begins and partially refunded if the operation fails.

Tenants are assigned AI plans: **free** (100 credits/month), **pro** (5,000 credits/month), **enterprise** (unlimited or custom allocation). The credit system is managed via `GET /api/v1/copilot/credits/{tenantId}` for balance inquiries and `POST /api/v1/copilot/credits/{tenantId}/allocate` for admin adjustments. When a tenant's balance reaches 20%, a warning is displayed in the Copilot UI. At 0%, AI operations return a 402 Payment Required with a link to upgrade.

The credit dashboard at `/copilot/credits` shows balance, consumption history by operation type, daily usage trends, and projected exhaustion date. It uses Radix `Progress` for balance visualization, `Table` for transaction history, and `Badge` for plan tier display.

**Acceptance Criteria**

- Each AI operation deducts the correct credit amount from the tenant balance
- Failed operations refund credits (partial for streaming operations that produced some output)
- Low-balance warning appears at 20% remaining credits
- Zero-balance blocks AI operations with 402 status and upgrade link
- Credit dashboard displays balance, history, daily trends, and projected exhaustion
- Admin API allows manual credit allocation and plan tier changes

**Part of Epic: Code Review & Documentation Automation**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Natural Language Schema Designer):**
- 1.1 (Chat Interface), 1.2 (Domain Understanding), and 1.5 (Preview Workflow) can be developed in parallel. The chat UI, domain recognition, and preview rendering are independent components.
- 1.3 (Generation Pipeline) depends on 1.1 for the chat integration but can be developed as a standalone library first.
- 1.4 (Iterative Refinement) depends on both 1.1 and 1.3 being functional.

**Epic 2 (Application Scaffolding Engine):**
- 2.1 (CRUD Generator), 2.2 (Microservice Templates), 2.3 (Admin Panel), and 2.4 (Mobile Skeleton) can all be developed in parallel since they are independent generators targeting different output frameworks.
- 2.5 (Template Registry) should be built early to provide the storage layer, but each generator can use local templates during development and migrate to the registry later.

**Epic 3 (Intelligent Analysis & Refactoring):**
- 3.1 (Usage Optimization), 3.2 (Normalization), 3.3 (Performance Impact), and 3.5 (Quality Scoring) are all independent analysis engines and can be developed in parallel.
- 3.4 (Breaking Change Mitigation) depends on 3.3 for performance impact data and should follow it.

**Epic 4 (Code Review & Documentation Automation):**
- 4.1 (PR Review), 4.2 (Drift Detection), 4.3 (Docs Generator), and 4.5 (Credit Management) can be developed in parallel.
- 4.4 (Changelog Generator) depends on the structural diff logic also used by 3.4 and should reuse that module.
- 4.5 (Credit Management) should be among the first completed since all other Copilot features depend on it for metering.

**Cross-Epic Parallelism:**
- Epic 1 and Epic 2 are independent and can be built by separate teams; Epic 2 only requires published schemas, not the designer.
- Epic 3 is independent of Epics 1 and 2 and can be developed in parallel.
- Epic 4 is largely independent but 4.1 and 4.2 benefit from the schema diff logic developed in Epic 3 (issue 3.4).
