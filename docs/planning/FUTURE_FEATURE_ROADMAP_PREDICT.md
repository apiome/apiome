# Apiome: Predict - Feature Roadmap

> Predictive analytics and recommendation engine for schema design, leveraging machine learning on anonymized usage patterns across the platform. Predict transforms raw telemetry into actionable intelligence — helping schema designers make better decisions, anticipate problems, and stay ahead of industry trends.
>
> **Revenue Model**: AI feature add-on (included in Pro tier), enterprise predictive analytics package with custom model training
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, Python ML services (scikit-learn, PyTorch), self-hosted Ollama cluster for LLM inference, REST API backed by PostgreSQL + time-series store (TimescaleDB), OpenAPI 3.1 spec

---

## MVP Definition

- Usage data collection pipeline with privacy-preserving anonymization
- Property suggestion engine that recommends properties based on class name and existing fields
- Relationship recommendation based on common schema patterns in the corpus
- Schema quality score with risk indicators (tech debt estimate, maintenance burden)
- Basic trend dashboard showing popular schema patterns across the platform
- Opt-in/opt-out controls for data contribution and recommendation features
- REST API for all prediction endpoints with confidence scores
- Admin configuration for model selection and feature toggles

---

## Epic 1: Data Pipeline & Feature Engineering

### Summary Table

| #   | Title                                | Description                                                                                 | Labels                                    | Parallel |
|-----|--------------------------------------|---------------------------------------------------------------------------------------------|-------------------------------------------|----------|
| 1.1 (#1224) | Usage Telemetry Collection           | Instrument schema operations to emit structured telemetry events for ML consumption          | `enhancement`, `mvp`, `predict`, `rest`   | Yes      |
| 1.2 (#1225) | Anonymization & Privacy Engine       | Strip PII, hash identifiers, and aggregate data before it enters the ML pipeline             | `enhancement`, `mvp`, `predict`           | Yes      |
| 1.3 (#1226) | Feature Extraction Pipeline          | Transform raw telemetry into ML-ready feature vectors for model training                     | `enhancement`, `mvp`, `predict`           | No       |
| 1.4 (#1227) | Model Training Infrastructure        | Infrastructure for training, versioning, and deploying ML models on usage data               | `enhancement`, `mvp`, `predict`           | No       |
| 1.5 (#1228) | Opt-In Controls & Data Governance    | User and tenant controls for opting in/out of data collection and recommendation features     | `enhancement`, `mvp`, `predict`           | Yes      |

### Detailed Issue Descriptions

---

#### 1.1 (#1224) — Usage Telemetry Collection

The telemetry collector instruments key schema operations across the Apiome platform to emit structured events that feed the ML pipeline. Every schema creation, property addition, relationship definition, validation rule change, and API endpoint configuration generates a telemetry event.

Events follow a standardized schema: `event_type`, `timestamp`, `tenant_id` (to be anonymized), `project_id` (to be anonymized), `schema_class_name`, `property_names`, `property_types`, `relationship_types`, `validation_rules_used`, and `session_context` (UI vs API, duration). Events are written to a dedicated telemetry topic (Kafka or PostgreSQL-backed queue) for downstream processing.

The collector is implemented as middleware and service-layer hooks in the existing Apiome backend. It adds minimal latency (< 5ms per event) by writing asynchronously. Events are batched and flushed every 5 seconds or when the batch reaches 100 events. A circuit breaker disables collection if the telemetry backend is unreachable, ensuring zero impact on core platform operations.

The telemetry schema is versioned. Schema changes to the telemetry format are backward-compatible and handled by the feature extraction pipeline (1.3).

```
┌──────────────────────────────────────────────────────────┐
│                 Telemetry Collection Flow                 │
│                                                          │
│   Schema         Middleware        Telemetry    Feature   │
│   Operation ───► Hook ──────────► Queue ──────► Pipeline │
│   (create,       (async,          (Kafka /      (batch    │
│    update,        batched,         PG queue)     ETL)     │
│    delete)        < 5ms)                                  │
│                                                          │
│   ┌─────────────────────────────────────────────────┐    │
│   │  Telemetry Event                                │    │
│   │  ┌──────────────┬─────────────────────────────┐ │    │
│   │  │ event_type   │ "property_added"            │ │    │
│   │  │ timestamp    │ "2026-04-02T10:30:00Z"      │ │    │
│   │  │ tenant_hash  │ "a3f8b2..."                 │ │    │
│   │  │ class_name   │ "Order"                     │ │    │
│   │  │ property     │ { name:"total", type:"num"} │ │    │
│   │  │ context      │ { source:"ui", dur_ms:450 } │ │    │
│   │  └──────────────┴─────────────────────────────┘ │    │
│   └─────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

**Acceptance Criteria**

- Telemetry hooks emit events for schema creation, property CRUD, relationship changes, and validation rule changes
- Event latency overhead is < 5ms per operation (measured via benchmarks)
- Events batch in memory and flush every 5 seconds or at 100 events, whichever comes first
- Circuit breaker disengages collection when the telemetry backend is unreachable
- Telemetry events conform to a versioned JSON Schema stored in the repository
- No PII is present in raw telemetry events (tenant/user IDs are hashed at emission time by the anonymizer in 1.2)

**Tech Stack Callouts**

- REST middleware hooks in existing NextJS API routes
- PostgreSQL-backed queue (or Kafka if available) as the telemetry transport
- OpenAPI 3.1: `TelemetryEvent` schema with `eventType`, `timestamp`, `tenantHash`, `className`, `propertyDescriptor`, `context`

Part of Epic: Data Pipeline & Feature Engineering

---

#### 1.2 (#1225) — Anonymization & Privacy Engine

Before telemetry data enters the ML pipeline, all potentially identifying information must be stripped or transformed. The anonymization engine sits between the telemetry collector and the feature extraction pipeline, ensuring that no individual tenant's proprietary schema designs can be reverse-engineered from the training data.

The engine applies three transformations. First, identifier hashing: tenant IDs, project IDs, and user IDs are replaced with one-way SHA-256 hashes salted with a rotating key. The salt rotates monthly, meaning historical data cannot be correlated with current identifiers after rotation. Second, name generalization: custom property names like `customerBillingAddress` are decomposed into semantic tokens (`customer`, `billing`, `address`) and mapped to a canonical vocabulary. This preserves semantic meaning for recommendations while preventing exact reconstruction of proprietary naming. Third, frequency thresholds: patterns observed in fewer than K tenants (configurable, default K=5) are excluded from training data to prevent memorization of rare, identifiable designs.

The engine runs as a batch job on the telemetry queue. Anonymized events are written to a separate `anonymized_telemetry` store that the ML pipeline reads from. The raw telemetry is retained for a configurable period (default 30 days) for debugging and then purged.

**Acceptance Criteria**

- Tenant, project, and user IDs are replaced with salted SHA-256 hashes before ML pipeline ingestion
- Salt rotation occurs monthly and historical raw-to-hash mappings are not retained
- Property names are decomposed into semantic tokens mapped to a canonical vocabulary
- Patterns from fewer than K tenants (default 5) are excluded from the training dataset
- Raw telemetry is purged after the configured retention period (default 30 days)
- An audit log records each anonymization batch run with input count, output count, and exclusion count

**Tech Stack Callouts**

- Python batch job or PostgreSQL stored procedure for transformation
- PostgreSQL: `anonymized_telemetry` table partitioned by month
- Configuration via `predict_config` table: `k_threshold`, `salt_rotation_days`, `raw_retention_days`

Part of Epic: Data Pipeline & Feature Engineering

---

#### 1.3 (#1226) — Feature Extraction Pipeline

The feature extraction pipeline transforms anonymized telemetry events into structured feature vectors suitable for model training. This is the bridge between raw operational data and machine learning.

Feature vectors are computed at multiple granularities. Per-class features include: property count, property type distribution (percentage of strings, numbers, booleans, arrays, objects), average constraint density (validations per property), relationship count (references to other classes), and naming pattern features (average token count per property name, use of common prefixes like `is_`, `has_`, `created_`). Per-project features include: class count, relationship density (edges/nodes ratio), schema depth (maximum nesting level), and design pattern indicators (CQRS, event sourcing, active record). Cross-corpus features include: property co-occurrence matrices (which properties tend to appear together), class name → property distributions, and industry vertical clusters.

The pipeline runs as a scheduled batch job (daily for full recomputation, hourly for incremental updates). Output feature vectors are stored in a `feature_store` table with the class name hash as the key and a JSONB column for the feature vector. Model training jobs (1.4) read from this store.

The pipeline also computes aggregate statistics for the trend analysis features (Epic 4): most common class names, fastest-growing property patterns, and emerging validation rule usage.

**Acceptance Criteria**

- Feature vectors are computed at per-class, per-project, and cross-corpus granularities
- The pipeline supports both full recomputation (daily) and incremental updates (hourly)
- Per-class features include property count, type distribution, constraint density, and relationship count
- Property co-occurrence matrix is computed across the anonymized corpus
- Feature vectors are stored in a `feature_store` table with JSONB payloads
- Pipeline execution time is under 30 minutes for a corpus of 1 million telemetry events

**Tech Stack Callouts**

- Python (pandas, numpy) for feature computation
- PostgreSQL: `feature_store` table with GIN index on feature vector JSONB
- Scheduled via cron job or task queue (Celery)

Part of Epic: Data Pipeline & Feature Engineering

---

#### 1.4 (#1227) — Model Training Infrastructure

The model training infrastructure supports the full ML lifecycle: training, evaluation, versioning, and deployment of models that power the recommendation and prediction features in Epics 2–4.

Training runs are triggered manually or on a schedule (weekly). Each run produces a versioned model artifact stored in the model registry (a PostgreSQL table with metadata and a reference to the serialized model file in object storage). Models are evaluated against a held-out test set with metrics: precision, recall, F1 score for recommendation tasks; RMSE and MAE for regression tasks (quality scoring, capacity prediction).

The deployment pipeline supports A/B model comparison: two model versions can serve simultaneously, with traffic split configurable per tenant or globally. The active model version is selected via an admin API. Model inference runs on the self-hosted Ollama cluster for LLM-based features and on a Python inference service for traditional ML models.

A model monitoring dashboard tracks inference latency, prediction distribution, and data drift indicators (feature distributions diverging from training data).

**Acceptance Criteria**

- Training pipeline reads from the feature store and produces versioned model artifacts
- Model registry stores metadata (version, training date, metrics, feature set version) and artifact references
- Evaluation metrics (precision, recall, F1, RMSE, MAE) are computed and stored per model version
- A/B deployment supports two concurrent model versions with configurable traffic split
- Admin API endpoints manage model versions: list, activate, deactivate, delete
- Model monitoring dashboard tracks inference latency p50/p95 and data drift indicators

**Tech Stack Callouts**

- Python: scikit-learn for traditional ML, PyTorch for neural models, Ollama for LLM inference
- REST: `GET /api/v1/predict/models`, `POST /api/v1/predict/models/{id}/activate`, `GET /api/v1/predict/models/{id}/metrics`
- OpenAPI 3.1: `PredictModel` schema with `id`, `version`, `status`, `metrics`, `createdAt`
- Object storage for serialized model artifacts

Part of Epic: Data Pipeline & Feature Engineering

---

#### 1.5 (#1228) — Opt-In Controls & Data Governance

Trust is foundational for a product that learns from user data. This feature provides transparent, granular controls for users and tenant admins to manage their participation in the Predict system.

At the tenant level, admins can: enable or disable telemetry collection entirely, choose which event types to share (schema operations, API usage, validation patterns), and set the anonymization strictness level (standard or enhanced, where enhanced adds additional noise to feature vectors). At the user level, individual users can: opt out of having their actions included in telemetry (their events are still processed for per-tenant features but excluded from cross-corpus training), and disable recommendation UI elements.

The settings page at `app/(dashboard)/settings/predict/page.tsx` provides these controls with clear explanations of what data is collected, how it's anonymized, and how it's used. A "Data Preview" section shows a sample of what the user's anonymized telemetry looks like, making the privacy guarantees tangible.

A legal notice (drafted by the platform team) explains the data processing agreement. Tenants on the enterprise tier can request a full data export or deletion of their contribution to the training corpus.

**Acceptance Criteria**

- Tenant admins can enable/disable telemetry collection with a single toggle
- Granular event-type selection allows sharing only specific categories of telemetry
- Individual users can opt out of cross-corpus training while retaining per-tenant features
- "Data Preview" section renders a sample anonymized event for transparency
- Enterprise tenants can request data export or deletion via an admin API
- Changes to opt-in settings take effect within 1 hour (next pipeline run)

**Tech Stack Callouts**

- Radix UI: `Switch` (toggles), `Checkbox` (event type selection), `RadioGroup` (strictness level), `Accordion` (settings sections)
- NextJS: `app/(dashboard)/settings/predict/page.tsx`
- REST: `GET /api/v1/predict/settings`, `PATCH /api/v1/predict/settings`, `POST /api/v1/predict/data-export-request`
- OpenAPI 3.1: `PredictSettings` schema with `telemetryEnabled`, `eventTypes[]`, `anonymizationLevel`, `userOptOut`

Part of Epic: Data Pipeline & Feature Engineering

---

## Epic 2: Design Recommendation Engine

### Summary Table

| #   | Title                                | Description                                                                                   | Labels                                         | Parallel |
|-----|--------------------------------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------|----------|
| 2.1 (#1230) | Property Suggestion Service          | Suggest properties for a schema class based on its name and existing properties                | `enhancement`, `mvp`, `predict`, `ai-generated`, `rest` | Yes      |
| 2.2 (#1231) | Relationship Recommendation          | Recommend relationships between classes based on common patterns in the corpus                | `enhancement`, `mvp`, `predict`, `ai-generated`, `rest` | Yes      |
| 2.3 (#1232) | Schema Auto-Complete                 | Inline auto-complete in the schema editor powered by ML predictions                           | `enhancement`, `predict`, `ai-generated`        | No       |
| 2.4 (#1233) | Industry-Specific Model Packs        | Pre-trained model packs tuned for specific industries (fintech, healthcare, e-commerce, etc.) | `enhancement`, `predict`, `ai-generated`        | Yes      |
| 2.5 (#1234) | Recommendation Feedback Loop         | Track accepted/rejected suggestions to improve model accuracy over time                       | `enhancement`, `predict`                        | No       |

### Detailed Issue Descriptions

---

#### 2.1 (#1230) — Property Suggestion Service

The property suggestion service is the most visible Predict feature. When a user creates a new schema class or is editing an existing one, the service suggests relevant properties based on the class name and any existing properties.

The suggestion algorithm works in three stages. First, class name analysis: the LLM (via Ollama) parses the class name into semantic tokens (e.g., "CustomerOrder" → "customer" + "order") and identifies the domain concept. Second, corpus lookup: the feature store's property co-occurrence matrix is queried for the most frequently paired properties with the identified concept. Third, ranking: suggestions are ranked by a weighted combination of corpus frequency, semantic relevance (from the LLM), and contextual fit (does the suggested property conflict with or complement existing properties).

Each suggestion includes the property name, recommended type, a confidence score (0.0–1.0), and a brief explanation of why it was suggested. Suggestions are delivered via a REST endpoint and rendered in the schema editor as ghost-text completions or in a dedicated suggestions panel.

The service respects opt-out settings: users who have disabled recommendations see no suggestions. Tenants who have disabled telemetry still receive suggestions from the global model but do not contribute to it.

```
┌──────────────────────────────────────────────────────────┐
│              Property Suggestion Pipeline                │
│                                                          │
│  Class Name          LLM               Co-occurrence     │
│  "CustomerOrder" ──► Tokenize ──────► Matrix Lookup      │
│                      "customer"        ┌───────────────┐ │
│                      "order"           │ orderId  0.95 │ │
│                                        │ total    0.92 │ │
│  Existing Props      Context           │ currency 0.88 │ │
│  ["status"] ────────►Filter ──────────►│ items[]  0.85 │ │
│                      (remove           │ shipAddr 0.78 │ │
│                       duplicates,      └───────┬───────┘ │
│                       conflicts)               │         │
│                                        ┌───────▼───────┐ │
│                                        │ Ranked        │ │
│                                        │ Suggestions   │ │
│                                        └───────────────┘ │
└──────────────────────────────────────────────────────────┘
```

**Acceptance Criteria**

- Given a class name and optional existing properties, the service returns 5–10 ranked property suggestions
- Each suggestion includes property name, type, confidence score (0.0–1.0), and explanation text
- Suggestions are returned within 500ms (p95 latency)
- Suggestions exclude properties that already exist in the class
- The service respects user and tenant opt-out settings
- Suggestions are reproducible for the same input (deterministic given the same model version)

**Tech Stack Callouts**

- REST: `POST /api/v1/predict/suggest-properties` with body `{ className, existingProperties[], modelVersion? }`
- OpenAPI 3.1: `PropertySuggestion` schema with `name`, `type`, `confidence`, `explanation`
- Ollama: LLM inference for semantic analysis
- Python inference service for co-occurrence matrix lookup

Part of Epic: Design Recommendation Engine

---

#### 2.2 (#1231) — Relationship Recommendation

Schema classes rarely exist in isolation. The relationship recommender analyzes the classes in a project and suggests relationships (references, arrays of references, embedded objects) based on patterns observed in the corpus.

The recommender takes as input the set of class names and their properties in the current project. It queries the feature store for common relationship patterns between similar class concepts. For example, if a project has `Order` and `Customer` classes, the recommender suggests a `customerId` reference from `Order` to `Customer` because this relationship appears in 94% of projects with both classes.

Suggestions include the source class, target class, relationship type (one-to-one, one-to-many, many-to-many), the suggested property name and location, a confidence score, and a brief rationale. The UI renders suggestions as a list in a Radix UI `Sheet` side panel accessible from the schema editor. Users can accept a suggestion (which adds the property and `$ref`) or dismiss it.

The recommender also flags missing relationships: if two classes share property names that suggest a connection (e.g., `userId` in both `Profile` and `Settings`), it recommends making the relationship explicit.

**Acceptance Criteria**

- Given a set of class names and properties, the service returns ranked relationship suggestions
- Suggestions include source/target class, relationship type, property name, confidence, and rationale
- Accepting a suggestion automatically adds the `$ref` property to the source class
- Missing relationship detection flags classes with shared property names that suggest a connection
- Suggestions are returned within 1 second for projects with up to 50 classes
- Dismissed suggestions do not reappear unless the class structure changes significantly

**Tech Stack Callouts**

- REST: `POST /api/v1/predict/suggest-relationships` with body `{ classes[]: { name, properties[] } }`
- OpenAPI 3.1: `RelationshipSuggestion` schema with `sourceClass`, `targetClass`, `relationType`, `propertyName`, `confidence`, `rationale`
- Radix UI: `Sheet`, `Table`, `Badge` (relationship type), `Button` (accept/dismiss)

Part of Epic: Design Recommendation Engine

---

#### 2.3 (#1232) — Schema Auto-Complete

Schema auto-complete brings the property suggestion engine (2.1) directly into the typing flow. As users type in the schema editor, the system predicts the next token or property definition and offers inline ghost-text completions.

The auto-complete service sits between the schema editor and the suggestion service. When the user types a property name or starts a new property block, the auto-complete engine sends the current context (class name, existing properties, cursor position) to the suggestion service and renders the top suggestion as grayed-out ghost text. Pressing Tab accepts the suggestion; pressing any other key continues typing normally.

For JSON Schema editing, auto-complete operates at the property level (suggesting entire `"propertyName": { "type": "..." }` blocks) rather than at the character level. This produces more useful completions than token-level prediction. The engine also auto-completes validation constraints: if a user types `"format":`, the system suggests the most common format value for that property type and name (e.g., `"email"` for a property named `email`).

Auto-complete is debounced (500ms after last keystroke) to avoid excessive API calls. A small loading indicator appears when a suggestion is being fetched.

**Acceptance Criteria**

- Ghost-text completions appear inline in the schema editor after 500ms of inactivity
- Tab accepts the suggestion; any other key dismisses it
- Completions operate at the property level (full property blocks, not individual characters)
- Validation constraint auto-complete suggests format, minimum, maximum, pattern values
- Auto-complete respects the user's opt-out setting
- Loading indicator is visible but unobtrusive during suggestion fetch

**Tech Stack Callouts**

- Monaco Editor / CodeMirror inline suggestion API
- Radix UI: none (editor-native UI)
- REST: `POST /api/v1/predict/auto-complete` with body `{ className, existingProperties[], cursorContext }`
- OpenAPI 3.1: `AutoCompleteResponse` with `suggestion`, `confidence`, `type` (property, constraint, value)

Part of Epic: Design Recommendation Engine

---

#### 2.4 (#1233) — Industry-Specific Model Packs

Generic recommendations are useful, but industry-specific models dramatically improve relevance. Model packs are pre-trained model variants tuned on curated datasets for specific verticals: fintech, healthcare, e-commerce, SaaS, IoT, and government.

Each model pack includes a fine-tuned property suggestion model, a relationship recommendation model, and a quality scoring model calibrated for the industry's standards. For example, the healthcare pack knows about FHIR resource types, HL7 terminology, and HIPAA-relevant validation patterns; the fintech pack understands PCI DSS requirements and financial instrument schemas.

Model packs are selected at the project level via a Radix UI `Select` dropdown in project settings. The selection configures which model version is used for all Predict features in that project. A "General" pack is the default for projects without a specific industry selection.

Model packs can be developed and distributed independently of the core Predict product. Enterprise customers can commission custom model packs trained on their internal schema corpus (handled via consulting engagement).

**Acceptance Criteria**

- At least 3 industry model packs are available at launch (e-commerce, SaaS, healthcare)
- Model packs are selectable at the project level via project settings
- Selecting a model pack changes the suggestions returned by all Predict features for that project
- Each pack includes property suggestion, relationship recommendation, and quality scoring models
- The "General" pack is the default for projects without industry selection
- Model packs are versioned and can be updated independently

**Tech Stack Callouts**

- Radix UI: `Select` (industry picker in project settings)
- REST: `GET /api/v1/predict/model-packs` (list available packs), `PATCH /api/v1/projects/{id}/settings` (set model pack)
- OpenAPI 3.1: `ModelPack` schema with `id`, `industry`, `version`, `models[]`, `description`

Part of Epic: Design Recommendation Engine

---

#### 2.5 (#1234) — Recommendation Feedback Loop

The feedback loop is how Predict gets smarter over time. Every time a user accepts or rejects a suggestion, that signal is recorded and fed back into the training pipeline to improve future recommendations.

Feedback events capture: the suggestion that was shown, whether it was accepted or rejected, how it was modified if accepted (did the user change the name, type, or constraints?), the time elapsed before the decision, and the surrounding context (class name, existing properties). This data feeds into the feature extraction pipeline (1.3) as a separate feature source with higher weight than passive telemetry.

A per-tenant learning loop allows the system to adjust recommendations based on that specific team's preferences. If a team consistently rejects certain suggestion patterns (e.g., always preferring `UUID` IDs over auto-increment), the model learns to adjust for that tenant. This per-tenant adaptation uses a lightweight cache layer rather than full model retraining.

An admin dashboard shows feedback metrics: acceptance rate, most-rejected suggestion types, and model accuracy trends over time.

**Acceptance Criteria**

- Every suggestion accept/reject event is recorded with context (suggestion, decision, modifications, timing)
- Feedback data is incorporated into the next training pipeline run
- Per-tenant adaptation adjusts recommendations within 24 hours of accumulated feedback
- Admin dashboard shows acceptance rate, rejection patterns, and model accuracy trends
- Users can view their own suggestion history and acceptance rate
- Feedback data follows the same anonymization pipeline as telemetry (1.2)

**Tech Stack Callouts**

- REST: `POST /api/v1/predict/feedback` with body `{ suggestionId, action, modifications?, elapsedMs }`
- OpenAPI 3.1: `PredictionFeedback` schema
- Radix UI: none (feedback is captured implicitly from accept/reject actions)
- PostgreSQL: `prediction_feedback` table feeding into the feature extraction pipeline

Part of Epic: Design Recommendation Engine

---

## Epic 3: Quality & Risk Prediction

### Summary Table

| #   | Title                                | Description                                                                                    | Labels                                         | Parallel |
|-----|--------------------------------------|------------------------------------------------------------------------------------------------|-------------------------------------------------|----------|
| 3.1 (#1236) | Schema Quality Scoring Engine        | Compute a multi-dimensional quality score for schema designs with actionable breakdowns         | `enhancement`, `mvp`, `predict`, `rest`         | Yes      |
| 3.2 (#1237) | Tech Debt Forecasting                | Predict future maintenance burden based on current schema complexity and growth patterns        | `enhancement`, `predict`, `ai-generated`, `rest`| Yes      |
| 3.3 (#1238) | Risk Scoring & Alerts                | Assign risk scores to schema changes and alert when high-risk modifications are proposed        | `enhancement`, `predict`, `rest`                | No       |
| 3.4 (#1239) | Quality Issue Prediction             | Predict likely quality issues before they manifest based on pattern analysis                    | `enhancement`, `predict`, `ai-generated`        | No       |
| 3.5 (#1240) | Quality Dashboard                    | Visual dashboard aggregating quality scores, risk levels, and predictions across projects       | `enhancement`, `predict`                        | Yes      |

### Detailed Issue Descriptions

---

#### 3.1 (#1236) — Schema Quality Scoring Engine

The quality scoring engine evaluates schema designs across multiple dimensions and produces a composite score (0–100) with a per-dimension breakdown. This gives schema designers objective, quantifiable feedback on their work.

The scoring dimensions are: completeness (are all properties documented with descriptions and examples?), consistency (do naming conventions follow a uniform pattern?), correctness (are types appropriate, constraints valid, and references resolvable?), complexity (cyclomatic-style measure of nesting depth, property count, and relationship fanout), and maintainability (estimated effort to evolve the schema based on coupling and cohesion metrics).

Each dimension produces a score from 0 to 100. The composite score is a weighted average with configurable weights (default: equal weighting). Scores are computed per-class and aggregated to per-project and per-tenant levels.

The scoring runs on demand (triggered by the user) or automatically on version publish. Results are displayed as a Radix UI circular gauge at the top of the schema detail page, with per-dimension bars below it. Historical scores are tracked so users can see how quality evolves over time.

**Acceptance Criteria**

- Quality score is computed across 5 dimensions: completeness, consistency, correctness, complexity, maintainability
- Composite score (0–100) is a weighted average with configurable weights
- Scores are available per-class and aggregated per-project
- Score computation completes within 2 seconds for projects with up to 100 classes
- Historical scores are stored and displayed as a trend line
- Each dimension provides a breakdown of specific findings (e.g., "3 properties missing descriptions")

**Tech Stack Callouts**

- REST: `POST /api/v1/predict/quality-score` with body `{ projectId, versionId? }`, `GET /api/v1/predict/quality-score/{projectId}/history`
- OpenAPI 3.1: `QualityScore` schema with `composite`, `dimensions[]` each having `name`, `score`, `findings[]`
- Radix UI: `Progress` (dimension bars), `Tooltip` (finding details)
- NextJS: quality score widget embedded in `app/(dashboard)/projects/[id]/page.tsx`

Part of Epic: Quality & Risk Prediction

---

#### 3.2 (#1237) — Tech Debt Forecasting

Tech debt in schema design accumulates silently: fields added without validation, relationships left implicit, documentation skipped "just for now." The tech debt forecaster quantifies this accumulation and projects future maintenance burden.

The forecaster uses a regression model trained on historical schema evolution data. Input features include: current quality score, rate of schema changes (velocity), proportion of changes that are additions vs. modifications vs. deletions, ratio of documented to undocumented properties, and validation rule coverage. The model predicts the maintenance hours per month required to keep the schema healthy at different time horizons (3 months, 6 months, 12 months).

The forecast is visualized as a line chart projecting maintenance burden over time, with the current trajectory (if nothing changes) and an improved trajectory (if recommended actions are taken). A table below the chart lists the top 5 debt-reducing actions ranked by impact.

This feature complements the quality scorer (3.1) by adding a temporal dimension: not just "how good is it now" but "where is it headed."

**Acceptance Criteria**

- Tech debt forecast predicts maintenance hours at 3, 6, and 12 month horizons
- Forecast uses at least 5 input features from the quality scorer and change velocity metrics
- Visualization shows current trajectory and improved trajectory as line charts
- Top 5 debt-reducing actions are listed with estimated impact (hours saved)
- Forecast updates automatically when quality scores change
- Confidence intervals are displayed for each projection point

**Tech Stack Callouts**

- REST: `GET /api/v1/predict/tech-debt-forecast/{projectId}`
- OpenAPI 3.1: `TechDebtForecast` with `projections[]` (each having `horizon`, `hoursPerMonth`, `confidenceInterval`), `recommendations[]`
- Python: regression model (scikit-learn GradientBoostingRegressor or similar)
- Radix UI: `Table` (recommendations), `Tooltip` (confidence intervals)

Part of Epic: Quality & Risk Prediction

---

#### 3.3 (#1238) — Risk Scoring & Alerts

Every schema change carries risk: a property type change might break consumers, a removed field might orphan data, a new required field might cause validation failures in existing records. The risk scorer evaluates proposed changes before they're committed and assigns a risk score.

The risk scoring algorithm analyzes the diff between the current schema and the proposed change. It evaluates: breaking change probability (based on the type of change and consumer count), data migration complexity (estimated number of records affected and transformation difficulty), downstream impact (number of dependent services or API consumers), and historical precedent (have similar changes in other projects caused issues?).

The risk score is displayed as a badge (Low/Medium/High/Critical) on the version draft page. High and Critical risk changes trigger an alert: a Radix UI `AlertDialog` warns the user and requires acknowledgment before proceeding. Alerts can also be configured to notify team leads via the platform's notification system.

The risk scorer integrates with the impact analysis engine from Architect (if available) to enrich downstream impact data.

**Acceptance Criteria**

- Risk score is computed for every version draft and displayed as a Low/Medium/High/Critical badge
- Scoring evaluates breaking change probability, migration complexity, downstream impact, and historical precedent
- High/Critical risk changes trigger an `AlertDialog` requiring acknowledgment
- Configurable alert notifications sent to team leads for High/Critical changes
- Risk score explanation is available showing which factors contributed most
- Risk scoring completes within 3 seconds for typical schema changes

**Tech Stack Callouts**

- Radix UI: `Badge` (risk level), `AlertDialog` (high-risk warning), `Tooltip` (score explanation)
- REST: `POST /api/v1/predict/risk-score` with body `{ projectId, versionId, diff }`
- OpenAPI 3.1: `RiskScore` schema with `level`, `score`, `factors[]` each having `name`, `weight`, `value`

Part of Epic: Quality & Risk Prediction

---

#### 3.4 (#1239) — Quality Issue Prediction

Rather than waiting for quality issues to manifest, the predictive quality engine identifies schemas that are likely to develop problems based on early warning signals. This is the proactive counterpart to the reactive quality scorer.

The prediction model is trained on historical data: schemas that eventually required significant rework (measured by subsequent large diffs, quality score drops, or bug reports) are labeled as "problematic," and the model learns which early features predict this outcome. Predictive signals include: rapid property growth without documentation, high coupling (many outbound `$ref`s relative to class complexity), inconsistent naming patterns within a project, and deviation from industry-standard schema structures.

Predictions are surfaced as a "Health Forecast" widget on the project dashboard. Each at-risk class shows the predicted issue type (documentation decay, complexity spiral, coupling creep, naming drift), the probability of the issue occurring within 90 days, and a preventive action.

The model's predictions are validated against actual outcomes, and false positive rates are tracked and reported to build trust in the system.

**Acceptance Criteria**

- Predictions identify at-risk schema classes with issue type, probability, and preventive action
- At least 4 issue types are predicted: documentation decay, complexity spiral, coupling creep, naming drift
- Predictions refresh daily or on significant schema changes
- "Health Forecast" widget on the project dashboard shows at-risk classes sorted by probability
- False positive rate is tracked and displayed on the admin monitoring dashboard
- Users can dismiss predictions with feedback (correct/incorrect) that feeds into model improvement

**Tech Stack Callouts**

- REST: `GET /api/v1/predict/quality-predictions/{projectId}`
- OpenAPI 3.1: `QualityPrediction` schema with `classId`, `issueType`, `probability`, `preventiveAction`, `predictedWithinDays`
- Radix UI: `Badge` (issue type), `Progress` (probability bar), `Tooltip` (preventive action detail)
- Python: classification model (Random Forest or XGBoost)

Part of Epic: Quality & Risk Prediction

---

#### 3.5 (#1240) — Quality Dashboard

The quality dashboard aggregates all quality and risk data into a single executive-facing view. It provides at-a-glance health for the entire schema portfolio and enables drill-down into specific projects and classes.

The dashboard page at `app/(dashboard)/predict/quality/page.tsx` has three sections. The top section shows portfolio-level KPIs: average quality score, total tech debt hours, number of high-risk items, and quality trend (improving/declining/stable). The middle section is a project-level table with sortable columns for project name, quality score, tech debt forecast, risk level, and last scored date. The bottom section shows a quality distribution chart (histogram of class quality scores across all projects).

Clicking a project row navigates to the project-specific quality detail page showing per-class scores, predictions, and recommendations. The dashboard supports date range filtering to compare quality across different periods.

**Acceptance Criteria**

- Portfolio KPIs display average quality score, total tech debt, high-risk count, and quality trend
- Project table is sortable by any column with pagination for large tenants
- Quality distribution chart shows a histogram of class quality scores
- Clicking a project row navigates to the project-specific quality detail
- Date range filter enables period comparison
- Dashboard loads within 3 seconds for tenants with up to 100 projects

**Tech Stack Callouts**

- Radix UI: `Table`, `Select` (date range), `Badge` (quality trend), `Tooltip`
- NextJS: `app/(dashboard)/predict/quality/page.tsx`
- REST: `GET /api/v1/predict/quality-dashboard?from={date}&to={date}`
- OpenAPI 3.1: `QualityDashboard` schema with `kpis`, `projects[]`, `distribution`

Part of Epic: Quality & Risk Prediction

---

## Epic 4: Trend Analysis & Optimization

### Summary Table

| #   | Title                                | Description                                                                                   | Labels                                         | Parallel |
|-----|--------------------------------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------|----------|
| 4.1 (#1242) | Industry Trend Dashboard             | Visualize schema design trends across the platform's anonymized corpus by industry vertical    | `enhancement`, `predict`                        | Yes      |
| 4.2 (#1243) | Pattern Detection Engine             | Identify emerging and declining design patterns across the corpus                              | `enhancement`, `predict`, `ai-generated`, `rest`| Yes      |
| 4.3 (#1244) | Optimization Suggestion Engine       | Recommend performance, cost, and simplification improvements for existing schemas              | `enhancement`, `predict`, `ai-generated`, `rest`| No       |
| 4.4 (#1245) | Trend Reports & Exports              | Scheduled and on-demand reports with trend data for stakeholders                               | `enhancement`, `predict`                        | Yes      |

### Detailed Issue Descriptions

---

#### 4.1 (#1242) — Industry Trend Dashboard

The trend dashboard visualizes how schema design practices are evolving across the platform's anonymized user base. Architects and technical leaders use this to benchmark their practices against industry peers and spot emerging patterns early.

The dashboard displays trends across several dimensions: most popular property types over time, emerging class naming patterns, validation rule adoption rates, relationship density trends, and schema complexity evolution. Each trend is visualized as a time-series line chart with configurable granularity (weekly, monthly, quarterly).

Users can filter by industry vertical (from the model packs in 2.4) to see trends specific to their sector. Cross-industry comparisons are available for trends that span verticals. An "Insights" panel highlights notable shifts with natural language summaries generated by the LLM (e.g., "UUID primary keys have overtaken auto-increment by 3:1 in e-commerce schemas over the past 6 months").

The dashboard data comes from the feature extraction pipeline's aggregate statistics (1.3). All data is pre-anonymized; no individual tenant data is ever displayed.

**Acceptance Criteria**

- Dashboard displays at least 5 trend dimensions as time-series line charts
- Granularity is configurable: weekly, monthly, quarterly
- Industry filter narrows trends to a specific vertical; cross-industry comparison is available
- "Insights" panel shows 3–5 LLM-generated natural language trend summaries
- All displayed data is derived from anonymized aggregate statistics
- Dashboard loads within 5 seconds for a 12-month view

**Tech Stack Callouts**

- Radix UI: `Select` (industry filter, granularity picker), `Tabs` (trend dimensions), `ScrollArea`
- NextJS: `app/(dashboard)/predict/trends/page.tsx`
- REST: `GET /api/v1/predict/trends?industry={id}&granularity={weekly|monthly|quarterly}&from={date}&to={date}`
- Ollama: LLM inference for natural language insight generation

Part of Epic: Trend Analysis & Optimization

---

#### 4.2 (#1243) — Pattern Detection Engine

While the trend dashboard shows aggregate statistics, the pattern detection engine identifies specific, named patterns that are emerging or declining. This is a higher-level analysis that connects data points into narratives.

The engine runs as a weekly batch job that analyzes the feature store for statistically significant shifts. Pattern detection uses a combination of clustering (grouping similar schema structures) and change-point detection (identifying when a cluster's popularity crosses a threshold). Detected patterns are classified as: emerging (growing > 20% quarter-over-quarter), stable (growth between -5% and +5%), and declining (shrinking > 10% quarter-over-quarter).

Each detected pattern includes: a name (auto-generated by the LLM based on the cluster characteristics, e.g., "Event-Sourced Audit Trail"), a description, example schema snippets from the anonymized corpus, adoption rate over time, and a list of projects in the tenant that do or don't follow this pattern.

Results feed into the optimization engine (4.3) which can suggest adopting emerging patterns or migrating away from declining ones.

**Acceptance Criteria**

- Pattern detection runs weekly and identifies emerging, stable, and declining patterns
- Each pattern has a name, description, example snippets, and adoption trend
- Patterns are classified by growth rate: emerging (>20% QoQ), stable (±5%), declining (>10% drop)
- Per-tenant relevance shows which of the tenant's projects follow or deviate from each pattern
- At least 10 patterns are detected across the corpus at launch
- Pattern names and descriptions are generated by the LLM and human-reviewed before display

**Tech Stack Callouts**

- REST: `GET /api/v1/predict/patterns` (list detected patterns), `GET /api/v1/predict/patterns/{id}`
- OpenAPI 3.1: `DetectedPattern` schema with `id`, `name`, `description`, `trend`, `adoptionRate`, `examples[]`
- Python: scikit-learn clustering (DBSCAN or HDBSCAN), change-point detection (ruptures library)
- Ollama: pattern naming and description generation

Part of Epic: Trend Analysis & Optimization

---

#### 4.3 (#1244) — Optimization Suggestion Engine

The optimization engine analyzes existing schemas and recommends specific improvements across three categories: performance (reduce query complexity, optimize indexing hints, flatten deep nesting), cost (identify redundant properties, consolidate duplicate schemas, reduce validation overhead), and simplification (merge similar classes, extract shared interfaces, standardize naming).

Each suggestion includes: the target class and properties, the category (performance/cost/simplification), a description of the proposed change, estimated impact (qualitative: low/medium/high), and a diff preview showing before and after. Suggestions are ranked by impact and grouped by category.

The engine combines rule-based heuristics (e.g., "arrays nested more than 3 levels deep should be extracted into a separate class") with ML-based recommendations (e.g., "schemas similar to yours that adopted pattern X saw 30% fewer breaking changes"). The rule-based engine runs instantly; ML recommendations may take a few seconds.

Users can accept a suggestion (which generates a version draft with the change applied), dismiss it (with optional feedback), or save it for later review. Accepted suggestions track their outcomes: did the quality score improve?

**Acceptance Criteria**

- Suggestions cover three categories: performance, cost, and simplification
- Each suggestion includes target, category, description, impact estimate, and before/after diff
- Rule-based suggestions are returned within 1 second; ML suggestions within 5 seconds
- Accepting a suggestion creates a version draft with the proposed change pre-applied
- Dismissed suggestions don't reappear for the same schema version
- Outcome tracking records quality score changes after accepted suggestions are published

**Tech Stack Callouts**

- REST: `GET /api/v1/predict/optimizations/{projectId}`, `POST /api/v1/predict/optimizations/{suggestionId}/accept`
- OpenAPI 3.1: `OptimizationSuggestion` schema with `id`, `category`, `targetClass`, `description`, `impact`, `diff`
- Radix UI: `Tabs` (category groups), `Badge` (impact level), `Sheet` (diff preview)
- NextJS: optimization panel embedded in project detail page

Part of Epic: Trend Analysis & Optimization

---

#### 4.4 (#1245) — Trend Reports & Exports

Stakeholders who don't log into the platform daily need periodic reports summarizing trends, quality changes, and optimization opportunities. This feature provides scheduled and on-demand report generation.

Reports are templated documents that combine data from the trend dashboard (4.1), pattern detection (4.2), quality dashboard (3.5), and optimization engine (4.3). Three report types are available: Executive Summary (1 page: portfolio KPIs, top trends, risk highlights), Technical Deep Dive (5–10 pages: per-project quality scores, trend analysis, optimization recommendations), and Industry Benchmark (3–5 pages: how the tenant compares to industry peers across key metrics).

Reports are generated as PDF and HTML. Users can configure scheduled delivery: weekly or monthly via email to a distribution list. On-demand generation is triggered from the reports page and produces the report within 30 seconds.

The reports page at `app/(dashboard)/predict/reports/page.tsx` shows generated reports in a Radix UI `Table` with columns for report type, date, and download links. A "Generate Report" button opens a Radix UI `Dialog` with type selection and date range inputs.

**Acceptance Criteria**

- Three report types are available: Executive Summary, Technical Deep Dive, Industry Benchmark
- Reports are generated as PDF and HTML formats
- On-demand generation completes within 30 seconds
- Scheduled delivery supports weekly and monthly cadence with email distribution
- Generated reports are listed in a history table with download links
- Reports pull live data from the quality dashboard, trend dashboard, and optimization engine

**Tech Stack Callouts**

- Radix UI: `Table` (report history), `Dialog` (generate), `Select` (report type, date range)
- NextJS: `app/(dashboard)/predict/reports/page.tsx`
- REST: `POST /api/v1/predict/reports` (generate), `GET /api/v1/predict/reports` (list), `GET /api/v1/predict/reports/{id}/download`
- PDF generation: Puppeteer or React-PDF

Part of Epic: Trend Analysis & Optimization

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 — Data Pipeline & Feature Engineering**
- **1.1** (Telemetry Collection) and **1.2** (Anonymization Engine) and **1.5** (Opt-In Controls) can all be built in parallel. The telemetry collector emits events, the anonymizer consumes them, and the opt-in controls gate both — but each has independent implementation scope.
- **1.3** (Feature Extraction) requires 1.1 and 1.2 since it processes anonymized telemetry.
- **1.4** (Model Training Infrastructure) requires 1.3 since it trains on extracted features.

**Epic 2 — Design Recommendation Engine**
- **2.1** (Property Suggestions) and **2.2** (Relationship Recommendations) and **2.4** (Industry Model Packs) can be built in parallel. Each is an independent prediction service with its own model and API.
- **2.3** (Auto-Complete) requires 2.1 since it wraps the property suggestion service in editor integration.
- **2.5** (Feedback Loop) requires 2.1 and 2.2 since it captures accept/reject events from both services.

**Epic 3 — Quality & Risk Prediction**
- **3.1** (Quality Scoring) and **3.2** (Tech Debt Forecasting) and **3.5** (Quality Dashboard) can be built in parallel. The scoring engine and forecaster are independent analytical services; the dashboard can be scaffolded with mock data.
- **3.3** (Risk Scoring) depends on 3.1 for quality score inputs and benefits from 3.2 for trend data.
- **3.4** (Quality Issue Prediction) depends on 3.1 for historical quality data and 1.4 for the trained classification model.

**Epic 4 — Trend Analysis & Optimization**
- **4.1** (Industry Trend Dashboard) and **4.2** (Pattern Detection) and **4.4** (Trend Reports) can be built in parallel. The dashboard and reports visualize data that the pattern detector also consumes, but each has independent UI and API scope.
- **4.3** (Optimization Engine) depends on 3.1 (quality scores) and 4.2 (detected patterns) for its combined rule-based and ML recommendations.

**Cross-Epic Parallelism**
- Epic 1 is the foundation: all other epics depend on the data pipeline being operational. However, Epics 2–4 can be developed using mock feature data while Epic 1 is completed.
- Epics 2 and 3 are fully independent of each other and can be developed by separate teams in parallel.
- Epic 4 depends on Epic 3 (quality dashboard data for reports) and Epic 1 (aggregate statistics for trends), but the dashboard UI (4.1) and report templates (4.4) can be built with mock data.
- The feedback loop (2.5) and opt-in controls (1.5) both touch user preferences and should share a coherent settings data model, but implementation can be parallel with a shared schema defined upfront.
