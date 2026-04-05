# Objectified: Analytics - Feature Roadmap

> Enterprise analytics layer that surfaces schema quality trends, API usage patterns, team productivity metrics, and executive KPIs across the Objectified platform. Integrates with external BI tools and provides a custom report builder for data-driven decision making.
>
> **Revenue Model**: Analytics features gated behind Pro/Enterprise subscription tiers; custom BI connectors and scheduled report delivery are Enterprise-only upsells
>
> **Tech Stack**: NextJS App Router, PostgreSQL (aggregation queries), Recharts/D3.js for in-app visualization, REST export API (OpenAPI 3.1), optional Snowflake/BigQuery connectors

---

## MVP Definition

- Schema analytics: most viewed, most updated, complexity trends over time
- Team analytics: active contributors, contribution heatmaps, review turnaround times
- API analytics: endpoint popularity, error rates by endpoint, response time percentiles
- Executive report: API portfolio overview and quality score trends
- Export to CSV and JSON from all analytics views
- REST API exposing analytics data (OpenAPI 3.1 documented)

---

## Epic 1 (#1759): Usage Analytics

### Summary Table

| #   | Title                                | Description                                                                      | Labels                                         | MVP | Parallel |
|-----|--------------------------------------|----------------------------------------------------------------------------------|------------------------------------------------|-----|----------|
| 1.1 (#1760) | Schema Analytics Data Model          | Database schema for tracking schema views, updates, property usage, and history  | `enhancement`, `mvp`, `analytics`, `rest`      | Yes | No       |
| 1.2 (#1761) | Most Viewed & Updated Schemas        | Aggregate and surface which schemas receive the most views and modifications      | `enhancement`, `mvp`, `analytics`              | Yes | No       |
| 1.3 (#1762) | Schema Complexity Trend Tracking     | Track complexity score over time per schema version for trend visualization       | `enhancement`, `mvp`, `analytics`              | Yes | Yes      |
| 1.4 (#1763) | Property Usage Statistics            | Count how frequently each property type and name pattern is used across schemas  | `enhancement`, `analytics`                     | No  | Yes      |
| 1.5 (#1764) | Deprecated Property Tracking         | Flag and track usage of properties marked deprecated across the project portfolio | `enhancement`, `analytics`                     | No  | Yes      |
| 1.6 (#1765) | Schema Growth Over Time              | Visualize schema size (class count, property count) growth as a time series      | `enhancement`, `analytics`                     | No  | Yes      |
| 1.7 (#1766) | Team Analytics: Active Contributors  | Aggregate commit-like activity per user: edits, reviews, approvals               | `enhancement`, `mvp`, `analytics`              | Yes | No       |
| 1.8 (#1767) | Contribution Heatmaps                | Calendar heatmap of schema modification activity per contributor                 | `enhancement`, `analytics`                     | No  | Yes      |
| 1.9 (#1768) | Review Turnaround Time Metrics       | Measure time from schema change submission to approval across teams              | `enhancement`, `mvp`, `analytics`              | Yes | Yes      |
| 1.10 (#1769) | Approval Bottleneck Detection        | Identify reviewers and schemas with longest pending review queues                | `enhancement`, `analytics`                     | No  | Yes      |
| 1.11 (#1770) | Team Productivity Metrics            | Composite score: velocity, review speed, quality score delta per team           | `enhancement`, `analytics`                     | No  | Yes      |
| 1.12 (#1771) | API Endpoint Popularity              | Track call counts per OpenAPI endpoint defined in project paths                 | `enhancement`, `mvp`, `analytics`, `rest`      | Yes | No       |
| 1.13 (#1772) | Error Rate by Endpoint               | Aggregate error response rates per endpoint over configurable time windows      | `enhancement`, `mvp`, `analytics`              | Yes | Yes      |
| 1.14 (#1773) | Response Time Percentiles            | Store p50/p95/p99 latency per endpoint; surface in dashboard charts             | `enhancement`, `analytics`                     | No  | Yes      |
| 1.15 (#1774) | Consumer Adoption Tracking           | Track which API consumers (API keys / tenants) use which endpoints              | `enhancement`, `analytics`, `rest`             | No  | Yes      |
| 1.16 (#1775) | Version Adoption Rates               | Show what percentage of consumers are on each API version                       | `enhancement`, `analytics`                     | No  | Yes      |
| 1.17 (#1776) | Deprecation Impact Analysis          | Estimate traffic impact when an endpoint or schema property is deprecated        | `enhancement`, `analytics`                     | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1760) — Schema Analytics Data Model

All analytics features depend on a well-structured events table that records schema interactions. Design an `analytics_event` table with `tenant_id`, `event_type` (enum: `schema_view`, `schema_edit`, `property_add`, `property_deprecate`, `review_submitted`, `review_approved`, `api_call`), `actor_id`, `resource_id`, `resource_type`, `metadata_json`, and `occurred_at`. Partition by `occurred_at` month for query performance.

```
┌─────────────────────────────────┐
│         analytics_event         │
├─────────────────────────────────┤
│ id           UUID PK            │
│ tenant_id    UUID FK            │
│ event_type   ENUM               │
│ actor_id     UUID FK (users)    │
│ resource_id  UUID               │
│ resource_type VARCHAR           │
│ metadata_json JSONB             │
│ occurred_at  TIMESTAMPTZ        │
└─────────────────────────────────┘

Indexes:
  (tenant_id, occurred_at)   — time-range queries
  (tenant_id, resource_id)   — per-schema queries
  (tenant_id, actor_id)      — per-user queries
```

**Acceptance Criteria:**
- Migration creates `analytics_event` with correct column types and partition strategy
- BRIN index on `occurred_at` applied to each partition
- Seed script generates realistic sample events for development
- OpenAPI component schema defined for `AnalyticsEvent`

**Tech Stack:** PostgreSQL table partitioning, JSONB for flexible event metadata, OpenAPI 3.1

Part of Epic: Usage Analytics

---

#### 1.7 (#1766) — Team Analytics: Active Contributors

Aggregate `analytics_event` records with `event_type IN ('schema_edit', 'review_submitted', 'review_approved')` by `actor_id` within a tenant. Expose a ranked list of contributors with their total contribution count, last active timestamp, and a 30-day activity sparkline.

**OpenAPI Endpoints:**
```
GET /api/v1/analytics/contributors
  ?tenant_id=...&from=...&to=...&limit=50
  → 200: ContributorList
```

**Acceptance Criteria:**
- Returns contributors sorted by activity count descending
- Supports `from`/`to` date range filtering
- Activity sparkline is a 30-day bucket array (suitable for mini chart rendering)
- Paginated with cursor-based pagination

**Depends on:** 1.1 (data model must exist)

Part of Epic: Usage Analytics

---

#### 1.12 (#1771) — API Endpoint Popularity

Instrument the platform's own API call layer to emit `api_call` analytics events when Objectified's REST endpoints are invoked. Aggregate by `resource_id` (endpoint path pattern) to produce a ranked popularity list. Surface as a sortable table in the analytics dashboard.

**OpenAPI Endpoints:**
```
GET /api/v1/analytics/api-endpoints
  ?tenant_id=...&from=...&to=...&sort=calls|errors|latency_p95
  → 200: EndpointMetricsList
```

**Acceptance Criteria:**
- Every REST endpoint in the platform emits an `api_call` event on request completion
- Events include HTTP method, path pattern (not raw path, to avoid PII in resource IDs), status code, and duration_ms
- Dashboard table supports sorting by calls, error rate, and p95 latency
- Data retention policy defaults to 90 days (configurable per tenant)

**Depends on:** 1.1 (data model must exist)

Part of Epic: Usage Analytics

---

## Epic 2 (#1777): Executive Reporting & Custom Reports

### Summary Table

| #   | Title                                 | Description                                                                       | Labels                               | MVP | Parallel |
|-----|---------------------------------------|-----------------------------------------------------------------------------------|--------------------------------------|-----|----------|
| 2.1 (#1778) | Executive Dashboard UI                | C-level overview widget: portfolio health, team velocity, compliance status       | `enhancement`, `mvp`, `analytics`   | Yes | No       |
| 2.2 (#1779) | API Portfolio Overview Report         | Rolled-up view of all API projects: schema count, quality score, endpoint count   | `enhancement`, `mvp`, `analytics`   | Yes | Yes      |
| 2.3 (#1780) | Quality Score Trend Report            | Line chart of quality score over time, per project and org-wide average           | `enhancement`, `mvp`, `analytics`   | Yes | Yes      |
| 2.4 (#1781) | Breaking Change Frequency Report      | Count and list breaking changes per project per release cycle                    | `enhancement`, `analytics`          | No  | Yes      |
| 2.5 (#1782) | Cost Attribution per Team/Project     | Map compute/storage resource usage to teams for chargeback reporting             | `enhancement`, `analytics`          | No  | Yes      |
| 2.6 (#1783) | Risk & Compliance Status Summary      | Surface security rule violations, deprecated endpoint usage, and policy breaches  | `enhancement`, `analytics`          | No  | Yes      |
| 2.7 (#1784) | Custom Report Builder                 | Drag-and-drop widget builder for assembling custom dashboards from metric blocks  | `enhancement`, `analytics`          | No  | No       |
| 2.8 (#1785) | Customizable KPI Widgets              | Per-user configurable KPI cards pinned to their personal dashboard               | `enhancement`, `analytics`          | No  | Yes      |
| 2.9 (#1786) | Multi-Format Export                   | Export any report as PDF, Excel (XLSX), CSV, or JSON via download or API         | `enhancement`, `mvp`, `analytics`, `rest` | Yes | No  |
| 2.10 (#1787) | Scheduled Report Delivery            | Define report schedules; deliver PDF/Excel to email or webhook on cron           | `enhancement`, `analytics`          | No  | No       |
| 2.11 (#1788) | Report Sharing with External Stakeholders | Generate shareable read-only report links with optional password protection  | `enhancement`, `analytics`          | No  | Yes      |
| 2.12 (#1789) | SQL Query Interface for Power Users   | Sandboxed SQL read replica interface for advanced analytics queries              | `enhancement`, `analytics`          | No  | No       |
| 2.13 (#1790) | Report Templates Library              | Pre-built report templates for common use cases (QA, release, compliance)        | `enhancement`, `analytics`          | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#1778) — Executive Dashboard UI

Design a dedicated Executive Dashboard page that aggregates top-level KPIs into a scannable overview. The dashboard must load in < 2 seconds via pre-computed aggregation tables. Include: overall schema quality score (org-wide), total API endpoints, active contributors this month, open review queue size, and compliance violation count.

```
┌──────────────────────────────────────────────────────┐
│  Executive Dashboard                           [PDF ▼]│
├──────────┬──────────┬──────────┬──────────┬──────────┤
│ Quality  │ Endpoints│ Contributors│ Reviews │ Violations│
│  87/100  │   1,234  │    42    │   17 open│    3      │
├──────────┴──────────┴──────────┴──────────┴──────────┤
│  Quality Score Trend (90d)     Team Velocity (30d)   │
│  [Line Chart]                  [Bar Chart]            │
├───────────────────────────────────────────────────────┤
│  API Portfolio Overview (Top 10 by traffic)           │
│  [Table: Project | Endpoints | Quality | Calls/day]   │
└───────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Dashboard renders in < 2 seconds using pre-computed daily aggregates
- All KPI cards link to their corresponding detail report
- Dashboard is accessible at `/analytics/executive` (Enterprise-tier only)
- PDF export button triggers 2.9 multi-format export for the current view

**Depends on:** 1.1 (event model), 1.3 (quality trends)

Part of Epic: Executive Reporting & Custom Reports

---

#### 2.9 (#1786) — Multi-Format Export

Implement an export pipeline that accepts a report definition (widget configuration + date range) and generates the requested format. PDF uses a headless Chrome renderer (Puppeteer) for pixel-accurate charts; Excel uses a server-side XLSX library; CSV and JSON are streamed directly from database queries.

**OpenAPI Endpoints:**
```
POST /api/v1/analytics/export
  Body: { report_type, format: pdf|xlsx|csv|json, from, to, filters }
  → 202: { job_id }

GET /api/v1/analytics/export/{job_id}
  → 200: { status, download_url } | 202: { status: processing }
```

**Acceptance Criteria:**
- PDF export renders charts using the same data as the live dashboard
- XLSX export includes formatted column headers and auto-width columns
- Export jobs complete in < 30 seconds for 90-day date ranges
- Download URLs expire after 1 hour

Part of Epic: Executive Reporting & Custom Reports

---

## Epic 3 (#1791): Business Intelligence Integrations

### Summary Table

| #   | Title                                | Description                                                                      | Labels                                | MVP | Parallel |
|-----|--------------------------------------|----------------------------------------------------------------------------------|---------------------------------------|-----|----------|
| 3.1 (#1792) | Snowflake Data Export Connector      | Periodic export of analytics events to a customer-owned Snowflake account        | `enhancement`, `analytics`           | No  | Yes      |
| 3.2 (#1793) | Tableau Connector                    | Web Data Connector (WDC) exposing Objectified analytics API for Tableau Desktop  | `enhancement`, `analytics`           | No  | Yes      |
| 3.3 (#1794) | Power BI Connector                   | Custom Power BI connector using the analytics REST API as a data source           | `enhancement`, `analytics`           | No  | Yes      |
| 3.4 (#1795) | Looker Integration                   | LookML model definition for Objectified analytics data exposed via API           | `enhancement`, `analytics`           | No  | Yes      |
| 3.5 (#1796) | Custom Data Warehouse Export         | Generic webhook/S3 push export for customers using non-standard BI tools         | `enhancement`, `analytics`           | No  | Yes      |
| 3.6 (#1797) | Embed Reports in External Dashboards | `<iframe>`-embeddable signed report URLs for embedding charts in external tools  | `enhancement`, `analytics`           | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#1792) — Snowflake Data Export Connector

Provide an Enterprise-tier feature that streams `analytics_event` data into a customer-provided Snowflake account using Snowflake's data loading API. Customers configure their Snowflake account credentials and target database in the tenant settings. Objectified schedules hourly incremental exports using the `occurred_at` watermark.

**OpenAPI Endpoints:**
```
PUT /api/v1/integrations/snowflake
  Body: { account, warehouse, database, schema, username, private_key_pem }
  → 200: SnowflakeIntegrationConfig

POST /api/v1/integrations/snowflake/test
  → 200: { connection_ok: true }

GET /api/v1/integrations/snowflake/exports
  → 200: ExportJobList
```

**Acceptance Criteria:**
- Credentials stored encrypted at rest using application-level encryption
- Test connection endpoint validates Snowflake connectivity before saving
- Incremental export uses `occurred_at > last_watermark` to avoid duplicates
- Export failure triggers a retry with exponential backoff (max 3 attempts)
- Tenant can disable the integration and delete all exported data from their Snowflake account via a documented runbook

**Tech Stack:** Snowflake Node.js driver, AES-256 credential encryption, cron-based scheduler

Part of Epic: Business Intelligence Integrations
