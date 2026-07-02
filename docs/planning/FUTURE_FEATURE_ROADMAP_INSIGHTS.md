# Apiome: Insights - Feature Roadmap

> Business intelligence and analytics platform specifically designed for API and schema ecosystems, providing actionable insights for technical and business stakeholders. Insights transforms raw telemetry from Apiome's platform operations into dashboards, scores, predictions, and reports that drive both engineering decisions and executive strategy.
>
> **Revenue Model**: Tiered analytics packages (Starter/Professional/Enterprise), enterprise custom dashboards, data export fees
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, ClickHouse (analytics datastore), Apache Kafka (event streaming), OpenAPI 3.1, Recharts for visualizations

---

## MVP Definition

- Telemetry ingestion pipeline for API and schema events
- Schema health scoring with quality breakdown by category
- API usage analytics with endpoint popularity and error rates
- Developer experience metrics (time-to-first-API-call, documentation engagement)
- Pre-built dashboard with configurable date ranges and filters
- Data export to CSV/JSON for external analysis
- REST API for all analytics data (OpenAPI 3.1 documented)
- Alerting on metric threshold breaches via email and in-app notification

---

## Epic 1: Data Collection & Pipeline

### Summary Table

| #   | Title                                 | Description                                                                   | Labels                                    | Parallel |
|-----|---------------------------------------|-------------------------------------------------------------------------------|-------------------------------------------|----------|
| 1.1 (#1080) | Telemetry Event Schema & Taxonomy     | Define canonical event types, properties, and naming conventions               | `enhancement`, `mvp`, `insights`, `rest`  | Yes      |
| 1.2 (#1081) | Event Ingestion API & SDK             | REST endpoint and client-side SDK for capturing telemetry events              | `enhancement`, `mvp`, `insights`, `rest`  | No       |
| 1.3 (#1082) | Event Streaming Pipeline              | Kafka-based pipeline for processing, enriching, and routing telemetry events  | `enhancement`, `mvp`, `insights`          | No       |
| 1.4 (#1083) | Analytics Data Warehouse              | ClickHouse schema and materialized views for fast analytical queries          | `enhancement`, `mvp`, `insights`          | Yes      |
| 1.5 (#1084) | Data Retention & Archival             | Configurable retention policies with tiered storage and archival to cold storage | `enhancement`, `insights`, `rest`       | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1080) — Telemetry Event Schema & Taxonomy

A well-defined event taxonomy is the foundation for all analytics. Every event flowing through Insights must conform to a canonical schema that ensures consistency, enables cross-event correlation, and supports future extensibility. The taxonomy organizes events into categories: API events (request, response, error), schema events (created, updated, published, deprecated), user events (login, page_view, feature_use), system events (deploy, health_check, config_change), and business events (subscription_change, usage_threshold).

Each event has a standard envelope: `event_id` (UUID), `event_type` (category.action format: `api.request`, `schema.published`), `timestamp` (ISO 8601 with timezone), `tenant_id`, `actor_id` (user or service), `session_id` (for user events), `correlation_id` (linking related events), and `properties` (event-specific data as JSON). The `properties` schema varies by event type but always includes a `source` field indicating which component emitted the event.

The taxonomy document serves as the contract between event producers and the analytics pipeline. It must be versioned and evolve without breaking existing consumers. New event types can be added freely; changing existing event type schemas requires a migration plan.

```
Event Taxonomy (v1.0)

  api.*                 schema.*              user.*
  ├── api.request       ├── schema.created    ├── user.login
  ├── api.response      ├── schema.updated    ├── user.page_view
  ├── api.error         ├── schema.published  ├── user.feature_use
  └── api.rate_limited  ├── schema.deprecated └── user.search
                        └── schema.deleted
  system.*              business.*
  ├── system.deploy     ├── business.subscription_change
  ├── system.health     ├── business.usage_threshold
  └── system.config     └── business.invoice_generated
```

**Acceptance Criteria:**
- Canonical event envelope schema defined with: event_id, event_type, timestamp, tenant_id, actor_id, session_id, correlation_id, properties
- Event type taxonomy with 5 categories and 15+ event types documented with property schemas
- Event type naming convention: `{category}.{action}` using lowercase snake_case
- Versioning strategy: event schema version field, backward-compatible additions, migration plan for breaking changes
- OpenAPI 3.1 component schemas for envelope and all event type properties
- Validation library that verifies events against the taxonomy before ingestion

**Tech Stack:** OpenAPI 3.1 for event schema definitions, JSON Schema validation, documentation in markdown

Part of Epic: Data Collection & Pipeline

---

#### 1.2 (#1081) — Event Ingestion API & SDK

The ingestion API receives telemetry events from all Apiome platform components and external sources. The primary endpoint `POST /api/v1/insights/events` accepts single events or batches (up to 1000 events per request). Events are validated against the taxonomy schema, enriched with server-side metadata (received_at, ingestion_id), and forwarded to the streaming pipeline.

A client-side JavaScript SDK simplifies event capture from the NextJS frontend. The SDK provides methods like `insights.track('schema.published', { schema_id, version })` with automatic envelope population (tenant_id, actor_id, session_id from the current auth context). The SDK includes batching (aggregate events for 5 seconds before sending), retry logic (exponential backoff on failure), and offline queueing (store events in localStorage when offline, flush on reconnect).

For server-side event capture, platform components emit events directly to the Kafka topic (bypassing the HTTP API for lower latency and higher throughput). The ingestion API serves external integrations and the frontend SDK. Rate limiting applies per tenant: configurable events-per-second limit with 429 responses when exceeded.

**Acceptance Criteria:**
- Ingestion endpoint: `POST /api/v1/insights/events` accepts single event or batch (max 1000)
- Event validation against taxonomy schema; rejected events return 422 with field-level errors
- Client-side SDK: `insights.track(eventType, properties)` with auto-populated envelope fields
- SDK batching: aggregate events for 5 seconds before sending, configurable batch size (default 50)
- SDK offline queueing: localStorage persistence, automatic flush on reconnect (max 1000 queued events)
- Rate limiting: configurable per-tenant events/second limit (default 10,000) with 429 response

**Tech Stack:** NextJS API route for ingestion, TypeScript SDK package, Kafka producer for pipeline forwarding, Redis for rate limiting, OpenAPI 3.1

Part of Epic: Data Collection & Pipeline

---

#### 1.3 (#1082) — Event Streaming Pipeline

The streaming pipeline processes raw telemetry events in real-time, applying enrichment, filtering, and routing before writing to the analytics data warehouse. The pipeline is built on Apache Kafka with stream processing: raw events land in the `insights.raw` topic, processors enrich events (resolve actor names, add geographic data from IP, compute derived fields), and enriched events are written to category-specific topics (e.g., `insights.api`, `insights.schema`).

Enrichment includes: resolving `actor_id` to user profile data (name, role, team), adding geographic information from request IP addresses (country, region, city), computing derived fields (e.g., `response_time_bucket` from raw milliseconds: fast <100ms, medium 100-500ms, slow >500ms), and deduplicating events using `event_id` with a 5-minute window. Filtering drops events that match exclusion rules (e.g., health check requests, internal bot traffic).

Consumer groups write enriched events to ClickHouse for analytical queries and to PostgreSQL for metadata and configuration. Real-time aggregation consumers compute running totals (requests per minute, error rate per endpoint) and update dashboards via WebSocket push. Pipeline lag monitoring ensures processing stays within acceptable latency (target: <10 seconds from event emission to dashboard availability).

**Acceptance Criteria:**
- Kafka topics: `insights.raw` (input), `insights.api`, `insights.schema`, `insights.user`, `insights.system` (output)
- Enrichment: actor name resolution, IP geolocation, derived field computation, event deduplication
- Filtering: configurable exclusion rules for health checks, bot traffic, and internal service events
- Real-time aggregation: running totals for key metrics updated every 10 seconds
- Pipeline lag monitoring: alert when processing lag exceeds 30 seconds
- Dead letter topic for events that fail enrichment with error metadata for debugging

**Tech Stack:** Apache Kafka, stream processing (Kafka Streams or custom Node.js consumers), IP geolocation database, ClickHouse writer, WebSocket for real-time push

Part of Epic: Data Collection & Pipeline

---

#### 1.4 (#1083) — Analytics Data Warehouse

ClickHouse serves as the analytical data store, optimized for fast aggregation queries across billions of events. The schema design uses ClickHouse's columnar storage and materialized views to pre-compute common aggregations. The primary table `events` stores all enriched events with columns for each envelope field and a `properties` Map column for event-specific data. Materialized views pre-aggregate: hourly counts by event type, daily API metrics by endpoint, and weekly schema health scores.

Table design follows ClickHouse best practices: partitioned by month on `timestamp`, ordered by `(tenant_id, event_type, timestamp)` for fast tenant-scoped queries, and with a TTL for automatic data expiration aligned with retention policies. Sampling enables approximate queries on large datasets for dashboard responsiveness.

The query layer provides a parameterized query API that translates dashboard requests into ClickHouse SQL. Common queries are templated and cached: "API requests per hour for tenant X, last 7 days" executes in <100ms regardless of data volume. Custom queries are supported via a restricted SQL interface for advanced users (read-only, with row-level security enforcing tenant isolation).

**Acceptance Criteria:**
- ClickHouse `events` table with proper partitioning (monthly), ordering (tenant_id, event_type, timestamp), and TTL
- Materialized views for: hourly event counts by type, daily API metrics by endpoint, weekly schema health scores
- Query API: parameterized templates for common dashboard queries executing in <100ms
- Restricted SQL interface for custom queries with tenant isolation enforced via row-level filtering
- Data ingestion from Kafka consumer with batch inserts (insert every 5 seconds or 10,000 events, whichever comes first)
- Schema migration tooling for ClickHouse schema evolution (add columns, create new materialized views)

**Tech Stack:** ClickHouse for analytical storage, Kafka consumer for data ingestion, parameterized query templates, NextJS API routes for query access

Part of Epic: Data Collection & Pipeline

---

#### 1.5 (#1084) — Data Retention & Archival

Analytics data volume grows continuously, and retention policies ensure storage costs remain manageable while preserving data for the required duration. The retention system implements three tiers: hot (ClickHouse, last 90 days, fast queries), warm (compressed ClickHouse partitions, 90 days to 1 year, slower queries), and cold (S3-compatible object storage, 1+ years, export-only access).

Retention policies are configurable per tenant and per event category. Enterprise tenants might retain API events for 2 years for compliance, while free-tier tenants retain only 30 days. The migration process runs as a nightly job: identify partitions exceeding the hot tier threshold, compress and migrate to warm storage, identify warm partitions exceeding the warm threshold, export to S3 as Parquet files and drop from ClickHouse.

Data access across tiers is transparent to the user for hot and warm data (ClickHouse handles it). Cold data requires an explicit export request: `POST /api/v1/insights/exports` generates a downloadable archive from S3 for the specified date range. Retention dashboard shows current storage usage per tier, projected costs, and retention policy configuration.

**Acceptance Criteria:**
- Retention policy configuration: per tenant, per event category, with hot/warm/cold tier thresholds
- Nightly migration job: move aging hot data to warm, warm data to cold (S3 Parquet export)
- Transparent query access for hot and warm tiers (ClickHouse internal)
- Cold data export: `POST /api/v1/insights/exports` generates downloadable Parquet/CSV archive from S3
- Retention dashboard: storage usage per tier, projected monthly cost, policy configuration UI
- GDPR compliance: data deletion endpoint removes events for a specific actor_id across all tiers

**Tech Stack:** ClickHouse TTL and partition management, S3-compatible storage for cold tier, Apache Parquet for archival format, background job for migration

Part of Epic: Data Collection & Pipeline

---

## Epic 2: Schema Health & Quality Dashboards

### Summary Table

| #   | Title                                 | Description                                                                    | Labels                                   | Parallel |
|-----|---------------------------------------|--------------------------------------------------------------------------------|------------------------------------------|----------|
| 2.1 (#1086) | Schema Health Score Algorithm          | Weighted scoring algorithm evaluating schema quality across multiple dimensions | `enhancement`, `mvp`, `insights`, `rest` | Yes      |
| 2.2 (#1087) | Quality Trend Visualization           | Time-series charts showing health score evolution with event correlation        | `enhancement`, `mvp`, `insights`         | No       |
| 2.3 (#1088) | Technical Debt Quantification         | Measure and track schema technical debt with remediation prioritization        | `enhancement`, `insights`, `rest`        | Yes      |
| 2.4 (#1089) | Deprecation Impact Forecasting        | Predict impact of deprecating schemas/fields on consumers and downstream systems| `enhancement`, `insights`               | Yes      |
| 2.5 (#1090) | Schema Complexity Metrics             | Measure schema complexity with actionable simplification recommendations       | `enhancement`, `insights`, `rest`        | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#1086) — Schema Health Score Algorithm

The health score is a single number (0-100) that represents the overall quality of a schema, computed from weighted sub-scores across five dimensions: completeness (are all fields documented with descriptions and examples? are validation rules defined?), consistency (do naming conventions follow standards? are types used consistently?), freshness (has the schema been updated recently? are there stale deprecated fields?), test coverage (does the schema have contract tests? what percentage of fields are tested?), and adoption (are consumers using this schema? what's the error rate?).

Each dimension is scored 0-100 independently, then combined using configurable weights (default: completeness 25%, consistency 25%, freshness 15%, test coverage 20%, adoption 15%). The algorithm produces both the aggregate score and per-dimension breakdowns, enabling targeted improvement. Specific findings (e.g., "3 fields missing descriptions", "naming inconsistency: mixes camelCase and snake_case") are attached to each dimension for actionable feedback.

Health scores are computed on demand via API and cached with a 1-hour TTL. A nightly batch job recomputes scores for all schemas and stores historical snapshots in the analytics warehouse. Score change alerts notify schema owners when their schema's health score drops below a threshold or decreases by more than 10 points.

**Acceptance Criteria:**
- Health score API: `GET /api/v1/insights/schemas/{schemaId}/health` returns aggregate score (0-100) and per-dimension breakdown
- Five scoring dimensions: completeness, consistency, freshness, test_coverage, adoption with configurable weights
- Per-dimension findings: specific actionable items (e.g., "field X missing description", "naming inconsistency on field Y")
- Score caching with 1-hour TTL and nightly batch recomputation for all schemas
- Historical score snapshots stored in analytics warehouse for trend analysis
- Alert on score decrease: configurable threshold (default: drops below 60 or decreases by 10+ points)

**Tech Stack:** NextJS API routes, schema analysis algorithms, ClickHouse for historical scores, notification service for alerts

Part of Epic: Schema Health & Quality Dashboards

---

#### 2.2 (#1087) — Quality Trend Visualization

Quality trend visualization shows how schema health scores evolve over time, correlating score changes with specific events (schema updates, version publications, team changes). The primary chart is a time-series line graph showing the aggregate health score over a configurable date range (7 days, 30 days, 90 days, 1 year), with colored bands indicating score thresholds (green >80, yellow 60-80, red <60).

Event markers on the chart annotate significant occurrences: schema version publications (blue diamond), breaking changes detected (red triangle), consumer count changes (orange circle), and manual score overrides (purple square). Hovering over a marker reveals the event details, and clicking navigates to the relevant schema version or event.

A multi-schema comparison mode overlays health scores for up to 5 schemas on the same chart, enabling comparative analysis across a team's schema portfolio. A "Org Health" view aggregates scores across all schemas in the tenant, showing the distribution (histogram of schemas by score range) and the weighted average.

**Acceptance Criteria:**
- Time-series health score chart with configurable date range (7d, 30d, 90d, 1y) and score threshold bands
- Event markers for schema publications, breaking changes, consumer changes, and overrides
- Hover tooltip on markers showing event details; click-through to event context
- Multi-schema comparison: overlay up to 5 schemas on one chart with legend
- Organization health view: score distribution histogram and weighted average across all tenant schemas
- Chart data API: `GET /api/v1/insights/schemas/{id}/health/history?from=&to=` returns timeseries data

**Tech Stack:** NextJS page (`app/(platform)/insights/health/page.tsx`), Recharts for time-series and histogram, Radix UI Select for date range, Radix UI Tabs for single/compare/org views

Part of Epic: Schema Health & Quality Dashboards

---

#### 2.3 (#1088) — Technical Debt Quantification

Technical debt in schemas manifests as: deprecated fields still in use, overly complex nested structures, inconsistent naming, missing validation, duplicated field definitions across schemas, and orphaned schemas with no consumers. The debt quantification module assigns a "debt score" to each finding, measured in estimated remediation hours, and aggregates across schemas to produce an organization-level debt inventory.

Each debt item has: category (deprecated, complexity, consistency, duplication, orphaned), severity (high, medium, low), estimated remediation effort (hours), affected schemas and fields, and a recommended fix. The debt inventory is prioritized by impact: high-severity items affecting many consumers rank above low-severity items on rarely-used schemas.

The debt dashboard shows total estimated debt (in hours), debt breakdown by category (pie chart), debt trend over time (are we accumulating or paying down debt?), and a prioritized remediation backlog. A "Debt Sprint" feature generates a set of recommended fixes for a time-boxed improvement effort (e.g., "8-hour debt sprint: fix these 12 items to reduce debt by 30%").

**Acceptance Criteria:**
- Debt scanner identifies items across categories: deprecated, complexity, consistency, duplication, orphaned
- Each debt item includes: category, severity, estimated_hours, affected_schemas, recommended_fix
- Organization debt inventory API: `GET /api/v1/insights/debt` returns prioritized debt items with aggregate hours
- Debt trend chart: total estimated hours over time showing accumulation vs remediation
- Debt breakdown pie chart by category with drill-down to individual items
- "Debt Sprint" generator: `POST /api/v1/insights/debt/sprint` with time_budget_hours returns recommended fix set

**Tech Stack:** Schema analysis algorithms, NextJS page (`app/(platform)/insights/debt/page.tsx`), Recharts for pie chart and trend, Radix UI Table for debt backlog

Part of Epic: Schema Health & Quality Dashboards

---

#### 2.4 (#1089) — Deprecation Impact Forecasting

When deprecating a schema field or version, understanding the downstream impact is critical for planning migrations. The deprecation forecaster analyzes current consumer usage to predict: how many API consumers reference the deprecated element, which specific consumers are affected, what percentage of traffic uses the deprecated element, and the estimated timeline for consumer migration based on historical adoption curves.

The forecaster builds a dependency graph: deprecated field → consumer contracts → consumer services → consuming applications → end users. Each node in the graph has an estimated migration effort based on the type of change required (simple field rename, type change, removal requiring alternative). The output is an impact report with: total affected consumers, migration effort estimate (hours), recommended deprecation timeline, and a suggested migration guide.

A "What-If" mode allows users to explore deprecation impact before committing: "If I deprecate field X, which consumers would break?" This is surfaced in the schema editor as a button next to each field, providing instant feedback during design decisions. The forecaster also monitors deprecated fields post-marking, tracking the actual migration progress against the forecast.

**Acceptance Criteria:**
- Impact analysis endpoint: `POST /api/v1/insights/deprecation/impact` accepts schema_id, field_path, returns impact report
- Consumer dependency graph showing affected contracts, services, and estimated migration effort
- Traffic analysis: percentage of recent API requests that reference the deprecated element
- Timeline forecast: estimated migration completion date based on historical consumer adoption curves
- "What-If" mode: preview deprecation impact without marking the field as deprecated
- Post-deprecation tracking: monitor actual vs forecasted migration progress for marked deprecations

**Tech Stack:** Dependency graph analysis, API traffic analysis from ClickHouse, NextJS page, Recharts for timeline forecasting charts

Part of Epic: Schema Health & Quality Dashboards

---

#### 2.5 (#1090) — Schema Complexity Metrics

Schema complexity correlates with maintenance burden, onboarding difficulty, and error rates. The complexity module computes metrics for each schema: nesting depth (maximum and average), field count (total, required, optional), type diversity (number of distinct types used), reference count (number of $ref pointers), circular reference depth, and a composite complexity score.

Complexity thresholds are configurable per tenant, and schemas exceeding thresholds are flagged with recommendations: "Schema Order has 47 fields with 6 levels of nesting. Consider splitting into Order, OrderItem, and ShippingDetails." Recommendations are generated by analyzing the schema structure and suggesting decomposition points based on logical grouping of fields.

A complexity comparison view shows how a schema's complexity has changed across versions, helping teams understand whether refactoring efforts are reducing complexity. The complexity radar chart visualizes all metrics for a schema on a single diagram, making it easy to spot which dimension is contributing most to overall complexity.

**Acceptance Criteria:**
- Complexity metrics API: `GET /api/v1/insights/schemas/{id}/complexity` returns all metrics and composite score
- Metrics computed: nesting_depth (max/avg), field_count (total/required/optional), type_diversity, ref_count, circular_ref_depth
- Configurable thresholds with automatic flagging when exceeded (e.g., field_count > 30, nesting_depth > 4)
- Decomposition recommendations when complexity exceeds thresholds, suggesting logical split points
- Complexity comparison across schema versions with improvement/regression indicators
- Radar chart visualization of all complexity metrics on a single diagram

**Tech Stack:** JSON Schema analysis library, NextJS page, Recharts radar chart, Radix UI Tooltip for metric explanations

Part of Epic: Schema Health & Quality Dashboards

---

## Epic 3: API Economy & Business Analytics

### Summary Table

| #   | Title                                 | Description                                                                   | Labels                                   | Parallel |
|-----|---------------------------------------|-------------------------------------------------------------------------------|------------------------------------------|----------|
| 3.1 (#1092) | API Monetization Tracking             | Track revenue attribution per API endpoint, consumer, and schema              | `enhancement`, `insights`, `rest`        | Yes      |
| 3.2 (#1093) | Consumer Adoption Funnels             | Visualize the journey from API discovery to active consumption                | `enhancement`, `insights`                | Yes      |
| 3.3 (#1094) | Churn Prediction for API Consumers    | ML-based prediction of consumer churn risk with retention recommendations     | `enhancement`, `insights`, `ai-generated`| No       |
| 3.4 (#1095) | Developer Experience Metrics          | Track TTFAC, documentation engagement, SDK adoption, and developer satisfaction| `enhancement`, `insights`, `rest`       | Yes      |
| 3.5 (#1096) | Revenue Attribution & ROI Analysis    | Connect schema investments to business outcomes with ROI calculations          | `enhancement`, `insights`               | No       |

### Detailed Issue Descriptions

#### 3.1 (#1092) — API Monetization Tracking

For organizations that monetize their APIs (usage-based billing, tiered subscriptions, marketplace listings), monetization tracking connects API usage events to revenue data. The module ingests billing events (from Stripe, internal billing systems, or manual entry) and correlates them with API usage telemetry to produce per-endpoint, per-consumer, and per-schema revenue attribution.

The monetization dashboard shows: total API revenue over time, revenue breakdown by endpoint (which endpoints generate the most revenue), revenue per consumer (top consumers by spend), and revenue per schema (which schemas are most valuable). Trend analysis identifies growing and declining revenue streams, and margin analysis factors in infrastructure cost data (if provided) to show per-endpoint profitability.

A "Revenue at Risk" indicator surfaces API consumers whose usage is declining (potential churn) with their associated revenue impact. This connects to the churn prediction module (issue 3.3) for a complete picture. Pricing optimization suggestions analyze usage patterns and recommend pricing tier adjustments to maximize revenue without increasing churn.

**Acceptance Criteria:**
- Billing event ingestion API: `POST /api/v1/insights/billing/events` accepts revenue records with consumer_id, endpoint, amount
- Revenue dashboard: total revenue over time, breakdown by endpoint, by consumer, and by schema
- Trend analysis: identify growing/declining revenue streams with percentage change indicators
- "Revenue at Risk" indicator: consumers with declining usage and associated annual revenue impact
- Margin analysis: per-endpoint profitability when infrastructure costs are provided
- Revenue data API: `GET /api/v1/insights/revenue?groupBy=endpoint|consumer|schema&from=&to=` with aggregations

**Tech Stack:** NextJS page (`app/(platform)/insights/revenue/page.tsx`), Recharts for revenue charts, ClickHouse for revenue aggregation, Stripe webhook integration

Part of Epic: API Economy & Business Analytics

---

#### 3.2 (#1093) — Consumer Adoption Funnels

The adoption funnel visualizes the journey API consumers take from discovery to active usage, identifying where potential consumers drop off. The funnel stages are: Discovery (viewed API documentation), Registration (created API key/account), First Call (made first API request), Active Use (made 10+ requests), Power User (using 3+ endpoints regularly), and Retained (active for 30+ consecutive days).

Each funnel stage shows: the number of consumers who reached that stage, the conversion rate from the previous stage, and the median time between stages. Drop-off analysis identifies which stage loses the most consumers and correlates drop-offs with potential causes: incomplete documentation, complex authentication, confusing error messages, or slow response times.

Cohort analysis groups consumers by their signup month and tracks their progression through funnel stages over time. This reveals whether recent onboarding improvements are working (newer cohorts should progress faster) and identifies seasonal patterns. Funnel data can be segmented by consumer attributes: company size, industry, plan tier, and geographic region.

**Acceptance Criteria:**
- Funnel visualization: 6 stages with consumer counts, conversion rates, and median time between stages
- Drop-off analysis: identify highest-drop-off stage with correlated potential causes
- Cohort analysis: group consumers by signup month, track funnel progression over time
- Segmentation: filter funnel by consumer attributes (company size, industry, plan, region)
- Funnel data API: `GET /api/v1/insights/funnels/adoption?segment=&cohort=` with stage breakdown
- Funnel trend: compare current period conversion rates to previous period with delta indicators

**Tech Stack:** NextJS page (`app/(platform)/insights/funnels/page.tsx`), funnel chart component, Recharts for cohort analysis, Radix UI Select for segmentation controls

Part of Epic: API Economy & Business Analytics

---

#### 3.3 (#1094) — Churn Prediction for API Consumers

The churn prediction module uses machine learning to identify API consumers at risk of abandoning the platform. The model analyzes behavioral signals: declining request volume, increasing error rates, decreasing endpoint diversity (using fewer features), longer intervals between requests, support ticket volume, and documentation disengagement. Each consumer receives a churn risk score (0-100) updated weekly.

The model is trained on historical churn data: consumers who stopped making API calls for 30+ consecutive days are labeled as churned. Feature engineering extracts rolling 7-day and 30-day metrics for each behavioral signal. The initial model uses gradient boosted trees (XGBoost) with the ability to retrain monthly on new data. Model performance is tracked via precision, recall, and AUC metrics.

The churn dashboard shows: consumers ranked by churn risk, risk score trend per consumer, contributing factors (why is this consumer flagged), and recommended retention actions. Actions are templated: "Send personalized onboarding follow-up," "Offer migration assistance for deprecated endpoint," "Schedule check-in call." Integration with the notification system enables automated outreach workflows triggered by risk score thresholds.

**Acceptance Criteria:**
- Churn risk score (0-100) per consumer, updated weekly via batch ML inference job
- Behavioral signals tracked: request volume trend, error rate trend, endpoint diversity, request interval, support tickets
- Consumer churn dashboard: ranked list with risk score, trend sparkline, top contributing factors
- Retention action recommendations: templated suggestions based on churn risk factors
- Risk threshold alerts: notify account team when consumer's churn score exceeds configurable threshold (default 70)
- Model performance tracking: precision, recall, AUC updated on each retrain cycle

**Tech Stack:** Python ML pipeline (XGBoost), feature engineering from ClickHouse, NextJS page for dashboard, background job for weekly scoring, Radix UI Table for consumer list

Part of Epic: API Economy & Business Analytics

---

#### 3.4 (#1095) — Developer Experience Metrics

Developer experience (DX) metrics quantify how easy it is for developers to work with Apiome-managed APIs and schemas. The core metrics are: Time-to-First-API-Call (TTFAC—median time from API key creation to first successful request), documentation engagement (page views, time on page, search queries, and "was this helpful" ratings), SDK adoption (which SDKs are used, version distribution, upgrade rates), and developer satisfaction (periodic in-app survey with NPS-style scoring).

TTFAC is the most important DX metric: a long TTFAC indicates onboarding friction. The system measures TTFAC automatically by correlating API key creation events with first successful request events for the same consumer. A TTFAC distribution chart shows the spread, and a trend line tracks whether onboarding is getting faster over time.

Documentation engagement analytics track which pages are most visited, which pages have the highest exit rates (indicating confusion or lack of value), and which search queries return no results (indicating documentation gaps). These insights feed directly into documentation improvement priorities.

**Acceptance Criteria:**
- TTFAC computation: median time from API key creation to first 200-response request, tracked per consumer
- TTFAC distribution chart with percentile markers (p50, p75, p95) and trend line over time
- Documentation engagement: page views, avg time on page, exit rate per page, search queries with zero results
- SDK adoption tracking: SDK name, version, install count, active usage count, upgrade rate
- Developer satisfaction survey: in-app NPS prompt (monthly), score aggregation, and trend
- DX metrics API: `GET /api/v1/insights/dx-metrics` returns all metrics with configurable date range

**Tech Stack:** Event correlation in ClickHouse for TTFAC, documentation analytics SDK, NextJS page (`app/(platform)/insights/dx/page.tsx`), Recharts for visualizations

Part of Epic: API Economy & Business Analytics

---

#### 3.5 (#1096) — Revenue Attribution & ROI Analysis

Revenue attribution connects schema and API investments (development hours, infrastructure costs) to business outcomes (API revenue, consumer growth, efficiency gains). The ROI module provides a framework for quantifying the return on schema governance investments, enabling executive buy-in for continued platform investment.

The ROI calculator takes inputs: investment costs (developer hours × hourly rate, infrastructure costs, licensing fees) and business outcomes (API revenue generated, time saved by automated governance, reduced error rates, faster onboarding). It computes ROI as (total value generated - total investment) / total investment × 100%. Values are tracked over time to show ROI trend.

Cost-per-API-call analysis breaks down the fully loaded cost of serving each API request: compute, storage, bandwidth, and personnel allocated to the API program. This enables pricing decisions: ensuring API pricing covers costs and generates target margins. The analysis highlights the most expensive endpoints and recommends optimization opportunities.

**Acceptance Criteria:**
- ROI calculator UI: input investment costs and business outcomes, compute and display ROI percentage
- Investment tracking: log development hours, infrastructure costs, and licensing fees with date attribution
- Value tracking: API revenue, estimated time savings, error reduction value, onboarding acceleration value
- ROI trend chart: monthly ROI percentage over time showing investment payback trajectory
- Cost-per-API-call analysis: breakdown by compute, storage, bandwidth, and personnel per endpoint
- Executive summary export: one-page PDF with key ROI metrics, trends, and recommendations

**Tech Stack:** NextJS page (`app/(platform)/insights/roi/page.tsx`), Recharts for ROI trend, PDF generation for executive summary, Radix UI form components for cost/value inputs

Part of Epic: API Economy & Business Analytics

---

## Epic 4: Executive Dashboards & Reporting

### Summary Table

| #   | Title                                 | Description                                                                   | Labels                                   | Parallel |
|-----|---------------------------------------|-------------------------------------------------------------------------------|------------------------------------------|----------|
| 4.1 (#1098) | Executive Dashboard Builder           | Drag-and-drop dashboard builder with pre-built widget library                 | `enhancement`, `insights`                | Yes      |
| 4.2 (#1099) | Portfolio Overview & KPI Tracking     | C-level view of API portfolio health, value, and strategic metrics            | `enhancement`, `insights`                | No       |
| 4.3 (#1100) | Scheduled Report Generation           | Automated report generation and distribution on configurable schedules        | `enhancement`, `insights`, `rest`        | Yes      |
| 4.4 (#1101) | Multi-Format Export Engine            | Export dashboards and reports as PDF, Excel, CSV, and embeddable iframes      | `enhancement`, `insights`, `rest`        | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#1098) — Executive Dashboard Builder

The dashboard builder enables non-technical users to create custom dashboards by dragging and dropping widgets from a widget library onto a responsive grid canvas. Widgets are pre-built visualizations connected to Insights data: line charts, bar charts, pie charts, metric cards (single big number with trend), tables, funnels, and text/markdown blocks for annotations.

Each widget has a configuration panel for: data source (which metric or query), filters (date range, tenant, schema, endpoint), visualization settings (colors, labels, axis formatting), and refresh interval. The canvas supports responsive grid layout with configurable column counts (1, 2, 3, or 4 columns), widget sizing (small, medium, large, full-width), and drag-to-reorder. Dashboard state is auto-saved and versioned.

Dashboards have three visibility levels: personal (only creator), team (shared with team members), and organization (visible to all tenant users). A template system provides pre-built dashboards for common use cases: "API Program Overview," "Schema Quality Report," "Developer Experience Summary," and "Executive Business Review."

**Acceptance Criteria:**
- Drag-and-drop dashboard canvas with responsive grid layout (1-4 columns, configurable widget sizes)
- Widget library: line chart, bar chart, pie chart, metric card, table, funnel, text block
- Widget configuration panel: data source, filters, visualization settings, refresh interval
- Dashboard visibility: personal, team, organization with appropriate access control
- Auto-save with version history; undo/redo for layout changes
- Pre-built dashboard templates: API Overview, Schema Quality, DX Summary, Executive Review

**Tech Stack:** NextJS page (`app/(platform)/insights/dashboards/[id]/edit/page.tsx`), React-Grid-Layout for drag-and-drop canvas, Recharts for widgets, Radix UI Dialog for widget config, Radix UI DropdownMenu for visibility settings

Part of Epic: Executive Dashboards & Reporting

---

#### 4.2 (#1099) — Portfolio Overview & KPI Tracking

The portfolio overview provides C-level executives with a single page summarizing the health and value of the organization's entire API and schema portfolio. The page is designed for glance-ability: large metric cards at the top show the 4-5 most important KPIs (total active schemas, aggregate health score, total API revenue, active consumers, TTFAC), each with a trend indicator (up/down arrow with percentage change from previous period).

Below the KPIs, a portfolio map visualizes all schemas as bubbles sized by consumer count and colored by health score. Clicking a bubble drills down to that schema's detail page. A "Risk & Opportunity" section highlights: schemas with declining health (risk), schemas with growing adoption (opportunity), recently published schemas (awareness), and schemas approaching deprecation deadlines (action required).

KPI tracking allows executives to define target values for key metrics and track progress. For example, "Achieve average health score >80 by Q3" becomes a tracked goal with current progress, trend, and projected completion date. KPI definitions are configurable by executives, and historical tracking enables quarterly business reviews.

**Acceptance Criteria:**
- KPI cards: total active schemas, aggregate health score, API revenue, active consumers, TTFAC with trend indicators
- Portfolio map: bubble chart with schemas sized by consumer count, colored by health score (green/yellow/red)
- "Risk & Opportunity" section: 4 categories (declining health, growing adoption, recently published, nearing deprecation)
- KPI goal tracking: define target value and deadline, track current progress with projected completion
- Historical KPI data: queryable for quarterly business reviews with period-over-period comparison
- Page optimized for presentation: clean layout suitable for screen sharing in executive meetings

**Tech Stack:** NextJS page (`app/(platform)/insights/portfolio/page.tsx`), Recharts bubble chart, Radix UI Tooltip for metric details, presentation-optimized CSS

Part of Epic: Executive Dashboards & Reporting

---

#### 4.3 (#1100) — Scheduled Report Generation

Scheduled reports automate the generation and distribution of analytics reports on configurable cadences. Report definitions specify: content (which dashboard or pre-defined report template), format (PDF or HTML email), schedule (daily, weekly on specific day, monthly on specific date, quarterly), recipients (email addresses and/or Slack channels), and filters (date range relative to send date: "last 7 days," "last month").

The generation engine renders the report at the scheduled time by querying fresh data, rendering visualizations, and composing the final document. For PDF reports, the engine renders an HTML template with embedded charts and converts to PDF. For email reports, inline HTML with embedded chart images is generated. Reports include a "View Live Dashboard" link for recipients who want to explore the data interactively.

Report schedules support timezone-aware delivery (send at 8 AM in the recipient's timezone), skip-if-no-data (don't send empty reports), and conditional sending (only send if a metric exceeds a threshold, e.g., "send weekly error rate report only if error rate >5%").

**Acceptance Criteria:**
- Report schedule CRUD: `POST /api/v1/insights/reports/schedules` with content, format, schedule, recipients, filters
- Schedule options: daily, weekly (specific day), monthly (specific date), quarterly with timezone-aware delivery
- PDF generation with embedded charts and data tables matching the dashboard layout
- HTML email generation with inline chart images and "View Live Dashboard" link
- Conditional sending: configurable metric threshold that gates report delivery
- Delivery log: track sent reports with delivery status, recipient list, and report archive link

**Tech Stack:** NextJS API routes, Puppeteer for PDF rendering, email service (SMTP or transactional email API), cron scheduler, chart-to-image rendering

Part of Epic: Executive Dashboards & Reporting

---

#### 4.4 (#1101) — Multi-Format Export Engine

Analytics data and dashboards need to be consumable outside the Insights platform. The export engine supports multiple output formats: PDF (formatted reports with charts), Excel (tabular data with multiple sheets per data source, formulas for totals), CSV (raw data for import into other tools), JSON (API response format for programmatic access), and embeddable iframe (authenticated widget for embedding in external portals).

Each dashboard and report page includes an "Export" button in the toolbar that opens a Radix UI DropdownMenu with format options. The export process runs asynchronously for large datasets: the user initiates the export, receives a notification when it's ready, and downloads from a temporary URL (valid for 24 hours). Small exports (under 10,000 rows) are generated synchronously and downloaded immediately.

The iframe embedding feature generates authenticated embed URLs for individual dashboard widgets. The URL includes a time-limited token that grants read-only access to the specific widget's data, enabling safe embedding in external portals, Confluence pages, or customer-facing dashboards. Embed settings control: refresh interval, color theme (light/dark), and interactive features (hover tooltips, drill-down).

**Acceptance Criteria:**
- Export formats: PDF, Excel (.xlsx with multiple sheets), CSV, JSON available from dashboard toolbar
- Async export for large datasets (>10,000 rows): initiate, notify on completion, download from temporary URL (24hr TTL)
- Sync export for small datasets (<10,000 rows): immediate download
- Excel export includes: data sheets per widget, summary sheet with KPIs, formulas for totals and averages
- Iframe embed URL generation: time-limited token, configurable theme, refresh interval, and interactivity
- Export history: `GET /api/v1/insights/exports` returns list of recent exports with download links and expiry

**Tech Stack:** ExcelJS for .xlsx generation, Puppeteer for PDF, NextJS API routes for export endpoints, JWT for embed authentication tokens, Radix UI DropdownMenu for format selection

Part of Epic: Executive Dashboards & Reporting

---

## Parallel Work Guide

The following issues can be worked on simultaneously within and across epics:

**Epic 1 — Data Collection & Pipeline:**
- Issues 1.1, 1.4, and 1.5 can be developed in parallel (event schema, ClickHouse warehouse, and retention are independent)
- Issue 1.2 depends on 1.1 (ingestion validates against the taxonomy)
- Issue 1.3 depends on 1.1 and 1.2 (streaming pipeline processes ingested events)

**Epic 2 — Schema Health & Quality:**
- Issues 2.1, 2.3, 2.4, and 2.5 can all be developed in parallel (health scoring, debt, deprecation, and complexity are independent analysis modules)
- Issue 2.2 depends on 2.1 (trend visualization needs health scores over time)

**Epic 3 — API Economy & Business Analytics:**
- Issues 3.1, 3.2, and 3.4 can be developed in parallel (monetization, funnels, and DX metrics are independent)
- Issue 3.3 depends on 3.1 and 3.2 (churn prediction uses monetization and adoption data as features)
- Issue 3.5 depends on 3.1 (ROI needs revenue attribution data)

**Epic 4 — Executive Dashboards & Reporting:**
- Issues 4.1, 4.3, and 4.4 can be developed in parallel (dashboard builder, scheduling, and export are independent)
- Issue 4.2 depends on 4.1 (portfolio overview uses the dashboard builder's widget system)

**Cross-Epic Parallelism:**
- Epic 1 must start first (pipeline provides data for all other epics)
- Once Epic 1 issue 1.4 (data warehouse) is complete, Epics 2, 3, and 4 can all begin in parallel
- Epic 2 and Epic 3 are fully independent of each other
- Epic 4 (issues 4.1, 4.3, 4.4) can start as soon as any data is available in the warehouse
- Issue 4.2 benefits from Epic 2 (health scores) and Epic 3 (business metrics) but can start with placeholder data
