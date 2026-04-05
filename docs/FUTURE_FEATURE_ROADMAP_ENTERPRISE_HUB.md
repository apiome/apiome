# Objectified: Enterprise Hub - Feature Roadmap

> Centralized management console for large enterprises with multiple teams, projects, and Objectified instances. Enterprise Hub consolidates multi-tenant operations, cost governance, federated identity, and service cataloging into a single pane of glass—enabling platform teams to manage Objectified at organizational scale.
>
> **Revenue Model**: Enterprise licensing, per-tenant pricing, professional services
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL with row-level security, Redis for cross-tenant caching
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Single dashboard aggregating health, usage, and status for all managed tenants
- Tenant provisioning workflow with template-based configuration
- Cross-tenant schema sharing policy editor (allow/deny rules)
- Usage tracking per tenant with basic chargeback CSV export
- Organization-wide governance policy engine with violation alerts
- Federated SSO login via SAML 2.0 / OIDC with role mapping
- Service catalog listing internal APIs and schemas with ownership metadata
- Budget threshold alerts delivered via email and in-app notifications

---

## Epic 1: Multi-Tenant Dashboard & Provisioning

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1030) | Tenant Overview Dashboard | Aggregate health and status view across all tenants | `enhancement`, `enterprise-hub`, `mvp` | Yes |
| 1.2 (#1031) | Tenant Provisioning Wizard | Step-by-step tenant creation with template selection | `enhancement`, `enterprise-hub`, `mvp` | Yes |
| 1.3 (#1032) | Tenant Health Monitoring | Real-time health checks with alerting for degraded tenants | `enhancement`, `enterprise-hub`, `rest` | No |
| 1.4 (#1033) | Cross-Tenant Schema Sharing Policies | Policy editor controlling schema visibility across tenants | `enhancement`, `enterprise-hub`, `mvp` | Yes |
| 1.5 (#1034) | Tenant Configuration Management | Centralized configuration for feature flags, limits, and settings per tenant | `enhancement`, `enterprise-hub` | No |
| 1.6 (#1035) | Tenant Lifecycle Operations | Suspend, archive, and decommission tenant workflows | `enhancement`, `enterprise-hub`, `rest` | Yes |

### Detailed Issue Descriptions

#### 1.1 (#1030) — Tenant Overview Dashboard

The Tenant Overview Dashboard is the primary landing page for Enterprise Hub administrators. It presents a grid of tenant cards showing key health indicators—API request volume, error rate, active users, schema count, and storage consumption—with color-coded status badges (healthy, degraded, critical). Administrators can filter by region, business unit, or custom tags, and sort by any metric column.

The dashboard uses a Radix UI `Tabs` component to switch between card view and table view. The table view renders via a Radix `Table` with sortable column headers and inline sparkline charts for 7-day trends. A global search bar at the top uses debounced input to filter tenants by name or ID. The page lives at `/app/enterprise/dashboard` in the NextJS app router.

Data is sourced from a new REST endpoint `GET /api/v1/enterprise/tenants/overview` that aggregates metrics from the per-tenant metrics tables. The endpoint accepts query parameters for `region`, `business_unit`, `sort_by`, and `order`. Response payloads conform to the existing Objectified envelope format with pagination cursors.

```
┌──────────────────────────────────────────────────────────────────┐
│  Enterprise Hub — Tenant Overview                    [Search...] │
├──────────────────────────────────────────────────────────────────┤
│  [Card View]  [Table View]                                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Acme Corp    │  │ Globex Inc   │  │ Initech LLC  │           │
│  │ ● Healthy    │  │ ▲ Degraded   │  │ ● Healthy    │           │
│  │              │  │              │  │              │           │
│  │ Users: 342   │  │ Users: 87    │  │ Users: 1,204 │           │
│  │ Schemas: 56  │  │ Schemas: 23  │  │ Schemas: 189 │           │
│  │ Req/s: 1.2k  │  │ Req/s: 340   │  │ Req/s: 4.8k  │           │
│  │ Err%: 0.02%  │  │ Err%: 3.1%   │  │ Err%: 0.01%  │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                  │
│  Showing 3 of 47 tenants  [< Prev]  [Next >]                    │
└──────────────────────────────────────────────────────────────────┘
```

**Acceptance Criteria**:
- Dashboard loads all tenant summaries within 2 seconds for up to 500 tenants
- Card view shows status badge, active users, schema count, request rate, and error percentage
- Table view supports sorting by any numeric column and text search filtering
- Region and business unit filters reduce the tenant set via query parameters
- Clicking a tenant card navigates to the tenant detail page at `/app/enterprise/tenants/[id]`
- Empty state renders when no tenants exist with a CTA to the provisioning wizard

**Part of Epic: Multi-Tenant Dashboard & Provisioning**

---

#### 1.2 (#1031) — Tenant Provisioning Wizard

The Tenant Provisioning Wizard guides administrators through creating a new Objectified tenant with a multi-step form. Steps include: (1) basic metadata—name, slug, region, business unit; (2) template selection—choose from pre-defined configuration templates that set default quotas, feature flags, and schema sharing policies; (3) identity configuration—SSO provider, default admin user; (4) review and confirm.

The wizard is implemented as a Radix `Dialog` containing a stepper component. Each step validates before allowing progression. The template selection step renders a Radix `RadioGroup` of template cards with descriptions. The review step shows a read-only summary using Radix `Separator` and label/value pairs.

On submission, the wizard calls `POST /api/v1/enterprise/tenants` with the full provisioning payload. The backend spawns an async provisioning job—creating the tenant database schema, seeding default data, configuring SSO, and registering the tenant in the hub registry. A `GET /api/v1/enterprise/tenants/{id}/provisioning-status` endpoint supports polling until provisioning completes. The NextJS page route is `/app/enterprise/tenants/new`.

**Acceptance Criteria**:
- Wizard enforces unique tenant slug with real-time validation against existing slugs
- Template selection pre-fills quotas and feature flags that can be overridden
- Provisioning status page shows progress bar with step-by-step completion indicators
- Failed provisioning displays the failed step with retry option
- Newly provisioned tenant appears in the overview dashboard within 30 seconds of completion
- Audit log entry is created recording the provisioning actor and configuration

**Part of Epic: Multi-Tenant Dashboard & Provisioning**

---

#### 1.3 (#1032) — Tenant Health Monitoring

Tenant Health Monitoring provides a real-time view of each tenant's operational status. It collects metrics including API latency percentiles (p50, p95, p99), error rates by HTTP status code, database connection pool utilization, storage growth rate, and background job queue depth. Metrics are polled every 60 seconds and stored in a time-series table partitioned by tenant and day.

The health monitoring page at `/app/enterprise/tenants/[id]/health` displays metric charts using a time-range selector (1h, 6h, 24h, 7d, 30d). Critical thresholds trigger status transitions—when a tenant's p99 latency exceeds 2 seconds or error rate exceeds 5%, the status flips to "degraded" and an alert fires. Alerts are delivered via the notification system (in-app + email webhook).

The backend exposes `GET /api/v1/enterprise/tenants/{id}/health` returning the current health summary, and `GET /api/v1/enterprise/tenants/{id}/metrics?metric={name}&from={iso}&to={iso}` for time-series data. Alert thresholds are configurable per tenant via `PUT /api/v1/enterprise/tenants/{id}/alert-config`. The OpenAPI spec defines threshold objects with `metric`, `operator`, `value`, and `severity` fields.

**Acceptance Criteria**:
- Health page renders latency, error rate, storage, and job queue charts with selectable time ranges
- Status transitions from healthy to degraded trigger in-app notification within 2 minutes
- Alert thresholds are configurable per tenant and per metric
- Historical health data is retained for at least 90 days
- Health summary endpoint returns aggregated status usable by the overview dashboard cards

**Part of Epic: Multi-Tenant Dashboard & Provisioning**

---

#### 1.4 (#1033) — Cross-Tenant Schema Sharing Policies

Cross-Tenant Schema Sharing Policies allow enterprise administrators to control which schemas can be shared between tenants. Policies are defined as rules specifying a source tenant, target tenant (or wildcard for "all"), schema pattern (glob matching on schema name), and permission level (read-only, fork, full-copy). Policies are evaluated in order with a default-deny fallback.

The policy editor lives at `/app/enterprise/governance/schema-sharing` and renders a Radix `Table` of existing rules with inline editing. New rules are added via a Radix `Dialog` form with `Select` dropdowns for source/target tenants and a text input for the schema pattern. The permission level uses a Radix `RadioGroup`. Rules can be reordered via drag-and-drop to control evaluation priority.

Backend endpoints include `GET /api/v1/enterprise/schema-sharing-policies` (list all), `POST /api/v1/enterprise/schema-sharing-policies` (create), `PUT /api/v1/enterprise/schema-sharing-policies/{id}` (update), and `DELETE /api/v1/enterprise/schema-sharing-policies/{id}`. A `POST /api/v1/enterprise/schema-sharing-policies/evaluate` endpoint accepts a source tenant, target tenant, and schema name and returns the effective permission—useful for dry-run validation.

**Acceptance Criteria**:
- Policy rules support source tenant, target tenant (or wildcard), schema glob pattern, and permission level
- Rules are evaluated top-to-bottom with first-match semantics and default-deny
- Drag-and-drop reordering persists rule priority via a `PUT` batch endpoint
- Dry-run evaluation endpoint returns the matched rule and effective permission
- Deleting a rule shows a confirmation dialog warning about potential access revocation
- Policy changes are recorded in the audit log with before/after snapshots

**Part of Epic: Multi-Tenant Dashboard & Provisioning**

---

#### 1.5 (#1034) — Tenant Configuration Management

Tenant Configuration Management provides a centralized interface for managing feature flags, resource quotas, and operational settings across all tenants. Configuration values are organized into categories (quotas, features, integrations) and can be set at the organization default level or overridden per tenant. Per-tenant overrides are visually distinguished from inherited defaults.

The configuration page at `/app/enterprise/tenants/[id]/config` uses Radix `Tabs` to separate categories. Each configuration item renders as a labeled row with the current value, the source (default or override), and an edit control appropriate to the value type (toggle for booleans, number input for quotas, text input for strings). Bulk operations allow applying a configuration preset to multiple tenants simultaneously.

The REST API exposes `GET /api/v1/enterprise/config/defaults` for organization defaults and `GET /api/v1/enterprise/tenants/{id}/config` for the effective (merged) configuration. Updates use `PATCH /api/v1/enterprise/tenants/{id}/config` with a partial object of overrides. A `DELETE /api/v1/enterprise/tenants/{id}/config/{key}` endpoint removes an override, reverting to the organization default.

**Acceptance Criteria**:
- Configuration items display their source (organization default vs. tenant override)
- Overriding a default value highlights the row and shows a "reset to default" action
- Bulk configuration application supports selecting multiple tenants and applying a preset
- Configuration changes take effect within 60 seconds without tenant restart
- Invalid configuration values are rejected with descriptive validation errors
- Configuration change history is viewable per tenant with actor attribution

**Part of Epic: Multi-Tenant Dashboard & Provisioning**

---

#### 1.6 (#1035) — Tenant Lifecycle Operations

Tenant Lifecycle Operations cover the post-provisioning states a tenant can transition through: active, suspended, archived, and decommissioned. Suspending a tenant disables all API access while preserving data. Archiving moves tenant data to cold storage. Decommissioning permanently deletes tenant data after a configurable grace period.

Each transition requires confirmation through a Radix `AlertDialog` with a typed confirmation (e.g., type the tenant slug to confirm decommission). The tenant detail page at `/app/enterprise/tenants/[id]` displays the current lifecycle state with available transitions as Radix `DropdownMenu` actions. Scheduled transitions (e.g., auto-archive after 90 days of inactivity) are configured via the tenant settings.

Backend endpoints include `POST /api/v1/enterprise/tenants/{id}/suspend`, `POST /api/v1/enterprise/tenants/{id}/activate`, `POST /api/v1/enterprise/tenants/{id}/archive`, and `POST /api/v1/enterprise/tenants/{id}/decommission`. The decommission endpoint initiates an async job with a grace period; `POST /api/v1/enterprise/tenants/{id}/cancel-decommission` can abort before data deletion occurs.

**Acceptance Criteria**:
- Suspended tenants return 403 for all API requests with a descriptive error message
- Archived tenants can be restored within the retention period via a restore endpoint
- Decommission requires typed slug confirmation and respects a configurable grace period (default 30 days)
- Lifecycle transitions are recorded in the audit log with actor and reason fields
- Scheduled lifecycle transitions can be configured and are displayed on the tenant detail page

**Part of Epic: Multi-Tenant Dashboard & Provisioning**

---

## Epic 2: Cost Management & Chargeback

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1037) | Usage Tracking Engine | Collect and store per-tenant usage metrics for billing | `enhancement`, `enterprise-hub`, `mvp`, `rest` | Yes |
| 2.2 (#1038) | Chargeback & Showback Reports | Generate cost allocation reports by team and project | `enhancement`, `enterprise-hub`, `mvp` | No |
| 2.3 (#1039) | Budget Alerts & Limits | Configurable budget thresholds with automated notifications | `enhancement`, `enterprise-hub`, `mvp` | Yes |
| 2.4 (#1040) | Cost Optimization Recommendations | AI-assisted suggestions for reducing resource waste | `enhancement`, `enterprise-hub`, `ai-generated` | No |
| 2.5 (#1041) | Usage Analytics Dashboard | Visual exploration of consumption trends and forecasts | `enhancement`, `enterprise-hub` | No |

### Detailed Issue Descriptions

#### 2.1 (#1037) — Usage Tracking Engine

The Usage Tracking Engine captures granular consumption data for every tenant, including API request counts (read vs. write), storage bytes consumed, schema operations performed, AI credit usage, and compute time for background jobs. Metrics are collected via lightweight middleware that increments counters in Redis, which are flushed to PostgreSQL usage tables every 5 minutes.

Usage records are stored in a partitioned table (`enterprise_usage`) keyed by tenant ID, metric name, and time bucket (hourly granularity). Each record contains the raw count, a unit (requests, bytes, credits), and optional dimensional tags (endpoint, user, project). A daily rollup job aggregates hourly records into daily summaries for efficient long-range querying.

The REST API exposes `GET /api/v1/enterprise/tenants/{id}/usage?metric={name}&from={iso}&to={iso}&granularity={hourly|daily|monthly}` for retrieving usage data. A batch endpoint `GET /api/v1/enterprise/usage/summary?from={iso}&to={iso}` returns aggregated usage across all tenants for the chargeback report. The OpenAPI spec defines the `UsageRecord` schema with `tenant_id`, `metric`, `value`, `unit`, `tags`, and `bucket_start` fields.

**Acceptance Criteria**:
- Usage metrics are captured for API requests, storage, schema operations, and AI credits
- Metrics are flushed from Redis to PostgreSQL within 5 minutes with no data loss
- Hourly granularity is available for the past 90 days; daily granularity for 2 years
- Usage API supports filtering by metric name, date range, and granularity level
- Batch summary endpoint aggregates across tenants within 5 seconds for up to 500 tenants
- Usage records include dimensional tags for drill-down analysis

**Part of Epic: Cost Management & Chargeback**

---

#### 2.2 (#1038) — Chargeback & Showback Reports

Chargeback & Showback Reports transform raw usage data into financial reports that attribute costs to teams, projects, or cost centers. Administrators define cost models that map usage metrics to monetary values—for example, $0.001 per API request, $0.10 per GB-month of storage. Reports can operate in chargeback mode (actual billing) or showback mode (informational only).

The report builder at `/app/enterprise/cost/reports` uses Radix `Tabs` to separate monthly chargeback reports from ad-hoc showback views. Reports render as Radix `Table` components with hierarchical rows (organization → business unit → team → tenant) and columns for each cost category. Export options include CSV, PDF, and JSON via `GET /api/v1/enterprise/cost/reports/{id}/export?format={csv|pdf|json}`.

```
┌───────────────────────────────────────────────────────────────────┐
│  Cost Report — March 2026                     [Export ▾] [Print] │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Cost Model: Standard v2.1          Mode: [Chargeback] [Showback]│
│                                                                   │
│  ┌─────────────────┬──────────┬─────────┬────────┬──────────┐    │
│  │ Entity          │ API Reqs │ Storage │ AI     │ Total    │    │
│  ├─────────────────┼──────────┼─────────┼────────┼──────────┤    │
│  │ ▼ Engineering   │ $1,240   │ $340    │ $89    │ $1,669   │    │
│  │   Team Alpha    │   $780   │  $200   │  $45   │  $1,025  │    │
│  │   Team Beta     │   $460   │  $140   │  $44   │    $644  │    │
│  │ ▼ Product       │   $890   │ $120    │ $210   │ $1,220   │    │
│  │   Design        │   $340   │   $60   │ $150   │    $550  │    │
│  │   Analytics     │   $550   │   $60   │  $60   │    $670  │    │
│  ├─────────────────┼──────────┼─────────┼────────┼──────────┤    │
│  │ Total           │ $2,130   │ $460    │ $299   │ $2,889   │    │
│  └─────────────────┴──────────┴─────────┴────────┴──────────┘    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

Cost models are managed via `POST /api/v1/enterprise/cost/models` (create), `GET /api/v1/enterprise/cost/models` (list), and `PUT /api/v1/enterprise/cost/models/{id}` (update). Reports are generated on-demand or scheduled monthly via `POST /api/v1/enterprise/cost/reports` with parameters for date range, cost model ID, and mode.

**Acceptance Criteria**:
- Cost models define per-metric unit prices and can be versioned
- Reports support hierarchical drill-down from organization to individual tenant
- Export to CSV, PDF, and JSON produces correctly formatted documents
- Showback mode generates identical reports without triggering billing actions
- Monthly scheduled reports are automatically generated and distributed to configured recipients
- Cost model changes are applied prospectively and do not retroactively alter past reports

**Part of Epic: Cost Management & Chargeback**

---

#### 2.3 (#1039) — Budget Alerts & Limits

Budget Alerts & Limits allow administrators to set spending thresholds at the organization, business unit, or tenant level. When usage-derived costs approach a threshold (e.g., 80%, 90%, 100%), the system fires notifications. At 100%, optional hard limits can block further API requests until the next billing period or until an administrator raises the limit.

Budget configuration lives at `/app/enterprise/cost/budgets` and uses a Radix `Dialog` for creating budgets with fields for scope (org/unit/tenant), monthly amount, alert thresholds (multiple percentage triggers), and enforcement mode (alert-only vs. hard-limit). Active budgets are displayed as Radix `Table` rows with a progress bar showing current spend against the budget.

The backend provides `POST /api/v1/enterprise/cost/budgets`, `GET /api/v1/enterprise/cost/budgets`, `PUT /api/v1/enterprise/cost/budgets/{id}`, and `DELETE /api/v1/enterprise/cost/budgets/{id}`. Budget evaluation runs every hour, comparing accumulated usage costs against thresholds and dispatching alerts via the notification service. Hard limits are enforced at the API gateway layer using a budget-check middleware.

**Acceptance Criteria**:
- Budgets can be scoped to organization, business unit, or individual tenant
- Multiple alert thresholds (e.g., 50%, 80%, 100%) can be configured per budget
- Alert notifications are delivered within 1 hour of threshold breach
- Hard-limit mode returns HTTP 429 with a descriptive error when budget is exhausted
- Budget progress is visible on the cost dashboard with a visual progress bar
- Budget overrides allow an administrator to temporarily raise limits without deleting the budget

**Part of Epic: Cost Management & Chargeback**

---

#### 2.4 (#1040) — Cost Optimization Recommendations

Cost Optimization Recommendations analyze tenant usage patterns and surface actionable suggestions for reducing costs. The recommendation engine identifies idle tenants (low activity over 30 days), over-provisioned quotas (allocated but unused capacity), redundant schemas (duplicated across tenants that could be shared), and expensive API patterns (high-volume endpoints that could benefit from caching).

Recommendations are displayed at `/app/enterprise/cost/optimize` as a prioritized list of cards, each showing the recommendation category, affected tenant(s), estimated monthly savings, and a one-click action to apply the fix (where applicable). The recommendation engine runs nightly as a background job and stores results in a `cost_recommendations` table.

The REST API exposes `GET /api/v1/enterprise/cost/recommendations` with filtering by category, tenant, and minimum savings. Each recommendation includes an `action_url` that deep-links to the relevant configuration page. Dismissing a recommendation via `POST /api/v1/enterprise/cost/recommendations/{id}/dismiss` prevents it from reappearing for 90 days.

**Acceptance Criteria**:
- Engine identifies at least four recommendation categories: idle tenants, over-provisioned quotas, redundant schemas, and expensive API patterns
- Each recommendation shows estimated monthly savings in the tenant's configured currency
- One-click actions navigate to the appropriate configuration page with pre-filled values
- Dismissed recommendations do not reappear for 90 days
- Recommendations refresh nightly and reflect the previous 30 days of usage data

**Part of Epic: Cost Management & Chargeback**

---

#### 2.5 (#1041) — Usage Analytics Dashboard

The Usage Analytics Dashboard provides visual exploration of consumption trends across the enterprise. It renders time-series charts for each metric category (API requests, storage, AI credits) with tenant-level breakdown. Forecasting overlays project future costs based on linear regression of the past 90 days, helping administrators anticipate budget overruns.

The page at `/app/enterprise/cost/analytics` uses Radix `Tabs` to separate metric categories and Radix `Select` to choose the time range (7d, 30d, 90d, 1y). Charts support toggling individual tenants on/off for comparison. A summary panel at the top shows month-over-month change percentages and highlights the fastest-growing cost drivers.

Data is sourced from the usage tracking engine via `GET /api/v1/enterprise/usage/analytics?metrics={list}&from={iso}&to={iso}&group_by={tenant|unit|org}`. The forecast endpoint `GET /api/v1/enterprise/usage/forecast?metric={name}&horizon={days}` returns projected values with confidence intervals.

**Acceptance Criteria**:
- Time-series charts render for API requests, storage, AI credits, and compute metrics
- Tenant-level breakdown allows toggling individual tenants for comparison
- Forecast overlay displays projected costs with confidence bands for 30/60/90-day horizons
- Month-over-month change percentages are calculated and displayed in the summary panel
- Charts are interactive with hover tooltips showing exact values and dates
- Data loads within 3 seconds for organizations with up to 500 tenants

**Part of Epic: Cost Management & Chargeback**

---

## Epic 3: Organization-Wide Governance

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1043) | Governance Policy Engine | Define and enforce organization-wide schema and API policies | `enhancement`, `enterprise-hub`, `mvp`, `rest` | Yes |
| 3.2 (#1044) | Compliance Dashboard | Aggregate compliance status across all tenants | `enhancement`, `enterprise-hub`, `mvp` | No |
| 3.3 (#1045) | Standardization Scoring | Score tenants on adherence to organizational standards | `enhancement`, `enterprise-hub` | No |
| 3.4 (#1046) | Best Practice Tracking | Track adoption of recommended patterns and conventions | `enhancement`, `enterprise-hub` | Yes |
| 3.5 (#1047) | Policy Violation Workflow | Review, acknowledge, and remediate policy violations | `enhancement`, `enterprise-hub`, `rest` | No |

### Detailed Issue Descriptions

#### 3.1 (#1043) — Governance Policy Engine

The Governance Policy Engine enables enterprise administrators to define organization-wide rules that all tenants must follow. Policies are expressed as declarative rules targeting specific schema attributes—for example, "all schemas must include a `createdAt` timestamp field," "property names must use camelCase," or "no schema may exceed 50 properties." Policies are evaluated automatically when schemas are created or updated within any tenant.

Policies are authored at `/app/enterprise/governance/policies` using a rule builder interface. Each rule consists of a target (schema, property, endpoint), a condition (exists, matches regex, less than, contains), and a severity (error, warning, info). Rules are grouped into policy sets that can be assigned to specific tenants or applied globally. The rule builder uses Radix `Select` for target/condition selection and Radix `Switch` for enabling/disabling individual rules.

The backend provides `POST /api/v1/enterprise/governance/policies` (create policy set), `GET /api/v1/enterprise/governance/policies` (list), `PUT /api/v1/enterprise/governance/policies/{id}` (update), and `POST /api/v1/enterprise/governance/policies/evaluate` (evaluate a schema against all active policies). The evaluation endpoint returns a list of violations with severity, rule ID, and a human-readable message. Policy evaluation is also triggered automatically via a webhook on schema save events.

**Acceptance Criteria**:
- Policy rules support targeting schemas, properties, and API endpoints
- Conditions include exists, not-exists, regex match, numeric comparison, and contains
- Severity levels (error, warning, info) control whether violations block schema saves
- Policy sets can be assigned globally or to specific tenants
- Automatic evaluation triggers on schema create/update events across all tenants
- Policy evaluation results are cached and invalidated when policies or schemas change

**Part of Epic: Organization-Wide Governance**

---

#### 3.2 (#1044) — Compliance Dashboard

The Compliance Dashboard provides a high-level view of policy compliance across the entire organization. It aggregates violation counts by tenant, policy category, and severity, rendering a heat map where rows are tenants and columns are policy categories. Color intensity indicates violation density. Clicking a cell drills down to the specific violations for that tenant and policy.

The dashboard at `/app/enterprise/governance/compliance` includes a summary bar showing organization-wide compliance percentage, total violations by severity, and trend arrows indicating improvement or regression over the past 30 days. A Radix `DropdownMenu` allows filtering by severity level, and a date range picker enables historical comparison.

The backend exposes `GET /api/v1/enterprise/governance/compliance/summary` returning aggregate counts and percentages, and `GET /api/v1/enterprise/governance/compliance/details?tenant_id={id}&policy_id={id}` for drill-down. Compliance snapshots are stored daily to support trend analysis over time.

**Acceptance Criteria**:
- Heat map renders tenants vs. policy categories with color-coded violation density
- Summary bar shows organization-wide compliance percentage and violation counts by severity
- Trend indicators show 30-day improvement or regression per tenant
- Clicking a heat map cell navigates to filtered violation details
- Daily compliance snapshots enable historical trend charts for up to 1 year
- Dashboard loads within 3 seconds for organizations with up to 200 tenants and 50 policies

**Part of Epic: Organization-Wide Governance**

---

#### 3.3 (#1045) — Standardization Scoring

Standardization Scoring assigns each tenant a numeric score (0–100) reflecting how closely its schemas and API definitions adhere to organizational standards. Scores are computed from weighted policy compliance, naming convention adherence, documentation completeness, and schema reuse percentage. Weights are configurable by the enterprise administrator.

The scoring page at `/app/enterprise/governance/scores` renders a leaderboard using Radix `Table` with tenant name, overall score, sub-scores by category, and a trend sparkline. Clicking a tenant row expands to show the score breakdown with specific improvement suggestions. Scores are recalculated nightly and stored historically for trend analysis.

The REST API provides `GET /api/v1/enterprise/governance/scores` (all tenants) and `GET /api/v1/enterprise/governance/scores/{tenant_id}` (single tenant with breakdown). Score weights are configured via `PUT /api/v1/enterprise/governance/score-weights`. The OpenAPI spec defines the `StandardizationScore` schema with `overall`, `compliance`, `naming`, `documentation`, and `reuse` sub-scores.

**Acceptance Criteria**:
- Scores range from 0–100 and are computed from weighted sub-scores
- Sub-score categories include compliance, naming conventions, documentation, and schema reuse
- Score weights are configurable by enterprise administrators
- Leaderboard supports sorting by overall score or any sub-score
- Historical scores are retained for at least 1 year to support trend analysis
- Score calculation completes within 10 minutes for organizations with up to 500 tenants

**Part of Epic: Organization-Wide Governance**

---

#### 3.4 (#1046) — Best Practice Tracking

Best Practice Tracking monitors adoption of recommended patterns across the organization. Best practices are defined as named patterns—such as "use ISO 8601 date formats," "include pagination on list endpoints," or "define error response schemas." Each practice has a detection rule that scans schemas and API definitions to determine adoption status per tenant.

The tracking page at `/app/enterprise/governance/best-practices` renders a matrix where rows are best practices and columns are tenants, with checkmarks or X marks indicating adoption. A summary row shows the adoption percentage for each practice across the organization. Best practices can be marked as mandatory (mapping to governance policies) or recommended (informational tracking only).

The backend provides `GET /api/v1/enterprise/governance/best-practices` (list all with adoption stats) and `POST /api/v1/enterprise/governance/best-practices` (create). Adoption scanning runs nightly alongside standardization scoring. Detection rules are stored as JSON expressions evaluated against schema and API definition metadata.

**Acceptance Criteria**:
- Best practices are defined with a name, description, category, and detection rule
- Detection rules are evaluated against all schemas and API definitions nightly
- Adoption matrix shows per-tenant adoption status for each best practice
- Summary row displays organization-wide adoption percentage per practice
- Best practices can be promoted to mandatory (creating a corresponding governance policy)
- New best practice definitions trigger a full scan within 24 hours

**Part of Epic: Organization-Wide Governance**

---

#### 3.5 (#1047) — Policy Violation Workflow

The Policy Violation Workflow manages the lifecycle of detected governance violations from detection through remediation. Each violation can be in one of four states: open, acknowledged, in-progress, or resolved. Tenant administrators can acknowledge violations (accepting responsibility), request exemptions (with justification), or mark them as resolved (triggering re-evaluation).

The violation management page at `/app/enterprise/governance/violations` renders a filterable Radix `Table` with columns for tenant, policy, severity, status, assignee, and age. Bulk actions allow acknowledging or assigning multiple violations at once via Radix `DropdownMenu`. An exemption request triggers a Radix `Dialog` form for justification text and expiration date, which routes to the enterprise administrator for approval.

Backend endpoints include `GET /api/v1/enterprise/governance/violations` (list with filters), `PATCH /api/v1/enterprise/governance/violations/{id}` (update status), `POST /api/v1/enterprise/governance/violations/{id}/exempt` (request exemption), and `POST /api/v1/enterprise/governance/violations/{id}/verify` (re-evaluate and auto-resolve if fixed). Exemption approvals are managed via `POST /api/v1/enterprise/governance/exemptions/{id}/approve` and `POST /api/v1/enterprise/governance/exemptions/{id}/deny`.

**Acceptance Criteria**:
- Violations transition through open → acknowledged → in-progress → resolved states
- Exemption requests include justification text and expiration date
- Enterprise administrators receive notifications for pending exemption requests
- Re-evaluation endpoint automatically resolves violations that have been fixed
- Bulk actions support acknowledging and assigning up to 100 violations at once
- Violation age is tracked and violations older than 30 days are flagged as overdue

**Part of Epic: Organization-Wide Governance**

---

## Epic 4: Service Catalog & Internal Marketplace

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#1049) | Service Catalog Registry | Central registry of internal APIs and schemas with ownership | `enhancement`, `enterprise-hub`, `mvp`, `rest` | Yes |
| 4.2 (#1050) | Schema Reuse Tracking | Track and promote schema reuse across teams | `enhancement`, `enterprise-hub` | Yes |
| 4.3 (#1051) | Dependency Visualization | Interactive graph of cross-team API and schema dependencies | `enhancement`, `enterprise-hub` | No |
| 4.4 (#1052) | Team Capability Mapping | Map teams to their published APIs and domain capabilities | `enhancement`, `enterprise-hub` | Yes |
| 4.5 (#1053) | Internal API Marketplace | Searchable marketplace for discovering and requesting access to internal APIs | `enhancement`, `enterprise-hub` | No |

### Detailed Issue Descriptions

#### 4.1 (#1049) — Service Catalog Registry

The Service Catalog Registry is a central inventory of all internal APIs, schemas, and data products published across the organization. Each catalog entry includes metadata: name, description, owning team, version, status (active, deprecated, sunset), documentation URL, and tags. Catalog entries are either auto-discovered from tenant data or manually registered by teams.

The catalog browsing page at `/app/enterprise/catalog` renders a searchable grid of service cards using Radix `Card`-style layouts. Each card shows the service name, owning team badge, status indicator, version, and a brief description. Full-text search and tag-based filtering are supported. Clicking a card opens a detail page at `/app/enterprise/catalog/[id]` showing full metadata, endpoint listings, schema definitions, and consumer count.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Service Catalog                  [Search APIs and schemas...]      │
│  Tags: [All ▾]  Status: [Active ▾]  Team: [All ▾]                  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────────┐  ┌──────────────────────┐                 │
│  │ Payment API    v3.2  │  │ User Schema    v2.0  │                 │
│  │ Team: Billing        │  │ Team: Identity        │                 │
│  │ ● Active             │  │ ● Active             │                 │
│  │ 12 endpoints         │  │ 8 classes            │                 │
│  │ 34 consumers         │  │ 67 consumers         │                 │
│  │ [View] [Request]     │  │ [View] [Request]     │                 │
│  └──────────────────────┘  └──────────────────────┘                 │
│                                                                      │
│  ┌──────────────────────┐  ┌──────────────────────┐                 │
│  │ Inventory API  v1.5  │  │ Notification  v4.1   │                 │
│  │ Team: Supply Chain   │  │ Team: Platform        │                 │
│  │ ▲ Deprecated         │  │ ● Active             │                 │
│  │ 6 endpoints          │  │ 3 endpoints          │                 │
│  │ 8 consumers          │  │ 102 consumers        │                 │
│  │ [View] [Migrate]     │  │ [View] [Request]     │                 │
│  └──────────────────────┘  └──────────────────────┘                 │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

Backend endpoints include `GET /api/v1/enterprise/catalog` (list with search/filter), `POST /api/v1/enterprise/catalog` (register), `PUT /api/v1/enterprise/catalog/{id}` (update), and `GET /api/v1/enterprise/catalog/{id}` (detail). Auto-discovery runs nightly, scanning tenant API definitions and creating draft catalog entries for review.

**Acceptance Criteria**:
- Catalog entries include name, description, owning team, version, status, docs URL, and tags
- Full-text search returns results within 500ms across up to 10,000 catalog entries
- Auto-discovery creates draft entries from tenant API definitions nightly
- Status lifecycle supports active → deprecated → sunset transitions with consumer notification
- Catalog detail page shows endpoint listings, schema definitions, and consumer count
- Access request button triggers the marketplace access request workflow (issue 4.5)

**Part of Epic: Service Catalog & Internal Marketplace**

---

#### 4.2 (#1050) — Schema Reuse Tracking

Schema Reuse Tracking identifies schemas that are duplicated across tenants and promotes consolidation. The system computes structural similarity between schemas using JSON Schema diff—flagging schemas that share more than 80% of their properties as potential duplicates. Reuse metrics track how many tenants reference shared schemas vs. maintain private copies.

The reuse dashboard at `/app/enterprise/catalog/reuse` displays a similarity matrix for the most common schema patterns and a list of reuse opportunities ranked by estimated savings (reduced maintenance burden). Each opportunity card shows the candidate schemas, their owning teams, similarity percentage, and a suggested merge action.

The backend provides `GET /api/v1/enterprise/catalog/reuse/opportunities` (list potential consolidations) and `GET /api/v1/enterprise/catalog/reuse/metrics` (organization-wide reuse statistics). Similarity analysis runs weekly as a background job, comparing schema structures across tenants while respecting schema sharing policies.

**Acceptance Criteria**:
- Similarity analysis identifies schemas sharing more than 80% of properties (configurable threshold)
- Reuse opportunities display candidate schemas, owning teams, and similarity percentage
- Organization-wide reuse metrics show the ratio of shared to private schemas
- Similarity threshold is configurable by enterprise administrators
- Analysis respects schema sharing policies and does not compare schemas across restricted boundaries
- Reuse opportunities link to the schema sharing policy editor for creating sharing rules

**Part of Epic: Service Catalog & Internal Marketplace**

---

#### 4.3 (#1051) — Dependency Visualization

Dependency Visualization renders an interactive graph showing how APIs, schemas, and teams depend on each other across the organization. Nodes represent services (APIs and schemas) colored by owning team. Edges represent dependencies—API-to-schema references, schema-to-schema imports, and consumer-to-provider relationships. The graph supports zoom, pan, and node selection with detail panels.

The visualization page at `/app/enterprise/catalog/dependencies` renders a force-directed graph. Selecting a node highlights its direct dependencies (incoming and outgoing) and dims unrelated nodes. A side panel displays the selected node's metadata, list of dependents, and list of dependencies. Filters allow showing only specific teams, dependency types, or status levels.

The backend provides `GET /api/v1/enterprise/catalog/dependency-graph` returning a nodes-and-edges data structure suitable for client-side rendering. The response includes node metadata (type, team, status) and edge metadata (dependency type, strength). A `GET /api/v1/enterprise/catalog/dependency-graph/impact?node={id}` endpoint returns the transitive impact set for change analysis.

**Acceptance Criteria**:
- Graph renders nodes for APIs, schemas, and teams with color-coding by owning team
- Edges represent dependency relationships with type labels (imports, consumes, references)
- Node selection highlights direct dependencies and shows a detail panel
- Impact analysis endpoint returns the full transitive dependency set for a given node
- Graph renders within 3 seconds for organizations with up to 1,000 services
- Filter controls allow isolating specific teams, dependency types, or service statuses

**Part of Epic: Service Catalog & Internal Marketplace**

---

#### 4.4 (#1052) — Team Capability Mapping

Team Capability Mapping associates teams with their published API capabilities and domain expertise. Each team profile includes published APIs, owned schemas, domain tags (e.g., payments, identity, logistics), and contact information. The mapping enables cross-team discovery—teams can find who owns what capability and reach out for collaboration.

The team directory at `/app/enterprise/catalog/teams` renders a list of team cards using Radix `Card`-style layouts. Each card shows the team name, member count, published API count, domain tags, and a contact link. Clicking a team card opens a profile page at `/app/enterprise/catalog/teams/[id]` showing all published services, team members (pulled from federated identity), and a contribution timeline.

The backend provides `GET /api/v1/enterprise/catalog/teams` (list), `GET /api/v1/enterprise/catalog/teams/{id}` (detail with services), and `PUT /api/v1/enterprise/catalog/teams/{id}` (update profile). Team data is synchronized from the federated identity provider, with capability tags managed manually by team leads.

**Acceptance Criteria**:
- Team profiles include name, description, domain tags, published APIs, and member list
- Team directory supports filtering by domain tag and searching by team name
- Team detail page shows all owned services with status and consumer counts
- Member lists synchronize from the federated identity provider nightly
- Domain tags are managed by team leads and indexed for search
- Team profiles link to their published services in the service catalog

**Part of Epic: Service Catalog & Internal Marketplace**

---

#### 4.5 (#1053) — Internal API Marketplace

The Internal API Marketplace enables teams to discover, request access to, and consume internal APIs through a self-service workflow. The marketplace surfaces catalog entries with access request buttons. Requesting access triggers an approval workflow where the owning team reviews and grants appropriate access levels (read-only, full, admin).

The marketplace page at `/app/enterprise/marketplace` extends the catalog browsing experience with access-focused features: an "Available to You" section showing APIs the team can access, a "Pending Requests" section tracking outstanding access requests, and a "Discover" section showing all available APIs. Access requests are submitted via a Radix `Dialog` form specifying the intended use case and desired access level.

Backend endpoints include `POST /api/v1/enterprise/marketplace/access-requests` (submit), `GET /api/v1/enterprise/marketplace/access-requests` (list for requester or approver), `POST /api/v1/enterprise/marketplace/access-requests/{id}/approve` (approve), and `POST /api/v1/enterprise/marketplace/access-requests/{id}/deny` (deny with reason). Approved requests automatically configure the appropriate cross-tenant schema sharing policies and generate API credentials if needed.

**Acceptance Criteria**:
- Access request form captures intended use case, desired access level, and requesting team
- Owning team receives notification of pending access requests
- Approval automatically configures schema sharing policies and generates credentials
- Denied requests include a reason visible to the requester
- Marketplace shows three sections: available, pending, and discover
- Access can be revoked by the owning team, triggering credential rotation and policy removal

**Part of Epic: Service Catalog & Internal Marketplace**

---

## Parallel Work Guide

**Epic 1 — Multi-Tenant Dashboard & Provisioning**:
Issues 1.1 (Dashboard), 1.2 (Provisioning Wizard), 1.4 (Schema Sharing Policies), and 1.6 (Lifecycle Operations) can be developed in parallel as they operate on independent UI pages and API endpoints. Issue 1.3 (Health Monitoring) depends on 1.1 for the dashboard integration and health status badges. Issue 1.5 (Configuration Management) depends on 1.3 for alert threshold configuration.

**Epic 2 — Cost Management & Chargeback**:
Issue 2.1 (Usage Tracking Engine) must be completed first as all other issues depend on usage data. Issues 2.3 (Budget Alerts) can begin in parallel with 2.1 for the UI/API shell, but needs 2.1 data for functional testing. Issue 2.2 (Chargeback Reports) depends on 2.1. Issue 2.4 (Optimization Recommendations) depends on 2.1 and 2.2. Issue 2.5 (Analytics Dashboard) depends on 2.1.

**Epic 3 — Organization-Wide Governance**:
Issues 3.1 (Policy Engine) and 3.4 (Best Practice Tracking) can be developed in parallel as they use independent data models. Issue 3.2 (Compliance Dashboard) depends on 3.1 for violation data. Issue 3.3 (Standardization Scoring) depends on 3.1 and 3.4. Issue 3.5 (Policy Violation Workflow) depends on 3.1 and 3.2.

**Epic 4 — Service Catalog & Internal Marketplace**:
Issues 4.1 (Catalog Registry), 4.2 (Schema Reuse Tracking), and 4.4 (Team Capability Mapping) can be developed in parallel. Issue 4.3 (Dependency Visualization) depends on 4.1 for catalog data. Issue 4.5 (Internal API Marketplace) depends on 4.1 for catalog entries and 4.4 for team ownership data.

**Cross-Epic Parallelism**: All four epics can begin simultaneously since they operate on independent database tables and UI sections. Epic 3 (Governance) benefits from Epic 1 (Multi-Tenant) being in place for cross-tenant policy enforcement, but the governance engine can be developed against mock tenant data initially.
