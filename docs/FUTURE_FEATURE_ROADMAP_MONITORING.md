# Objectified: Monitoring & Observability - Feature Roadmap

> Full-stack observability layer providing centralized logging, audit trails, API key analytics, alerting, incident management, and SLO tracking for the Objectified platform. Enables operations teams to detect, diagnose, and resolve issues proactively.
>
> **Revenue Model**: Basic application metrics in all tiers; centralized log search, audit export, alerting integrations, and SLO management gated at Pro/Enterprise; SLA reporting and SIEM export are Enterprise-only
>
> **Tech Stack**: NextJS App Router, PostgreSQL, ELK Stack / Grafana Loki for log aggregation, Prometheus for metrics, PagerDuty / OpsGenie integrations, OpenAPI 3.1

---

## MVP Definition

- API response time tracking, error rate monitoring, request volume charts in admin portal
- Comprehensive audit trail: login/logout, schema changes, permission changes, API key usage, settings changes
- Audit log viewer with filters and search
- Audit log export for compliance (CSV, JSON)
- Basic health check endpoints (service, database, external dependencies)
- Custom alert rules with email and Slack notification channels

---

## Epic 1 (#1539): Application Monitoring

### Summary Table

| #   | Title                                      | Description                                                                        | Labels                                       | MVP | Parallel |
|-----|--------------------------------------------|------------------------------------------------------------------------------------|----------------------------------------------|-----|----------|
| 1.1 (#1542) | API Response Time Tracking                 | Record p50/p95/p99 latency per endpoint; chart in Super Admin portal               | `enhancement`, `mvp`, `monitoring`, `rest`  | Yes | No       |
| 1.2 (#1546) | Error Rate Monitoring                      | Aggregate 4xx/5xx error counts per endpoint per time window; alert on spike        | `enhancement`, `mvp`, `monitoring`          | Yes | Yes      |
| 1.3 (#1551) | Request Volume Charts                      | Time-series chart of total requests, grouped by endpoint and tenant                | `enhancement`, `mvp`, `monitoring`          | Yes | Yes      |
| 1.4 (#1556) | Database Query Performance                 | Track slow queries (> 100ms); surface in admin as top-N slowest queries list       | `enhancement`, `monitoring`                 | No  | Yes      |
| 1.5 (#1562) | Memory & CPU Usage Metrics                 | Expose process memory and CPU from Node.js process; chart over time                | `enhancement`, `monitoring`                 | No  | Yes      |
| 1.6 (#1569) | Canvas Rendering Performance               | Track time-to-interactive for canvas renders; alert on p99 > 3s                    | `enhancement`, `monitoring`                 | No  | Yes      |
| 1.7 (#1574) | Active Users / Sessions Widget             | Real-time count of active sessions; DAU/MAU trend over 30 days                    | `enhancement`, `mvp`, `monitoring`          | Yes | Yes      |
| 1.8 (#1580) | Downdetector Integration                   | Push status updates to Downdetector API on detected outages                        | `enhancement`, `monitoring`                 | No  | Yes      |
| 1.9 (#1586) | Public Status Page                         | Customer-facing status page at status.objectified.dev showing service health       | `enhancement`, `monitoring`                 | No  | No       |

### Detailed Issue Descriptions

#### 1.1 (#1542) — API Response Time Tracking

Instrument every Next.js API route with request timing middleware. On each response, record: endpoint path pattern (not raw URL to avoid PII), HTTP method, status code, duration_ms, tenant_id, and timestamp. Store in a time-series table partitioned by day. Surface as p50/p95/p99 percentile charts in the Super Admin portal.

```
┌─────────────────────────────────────────────────────┐
│  api_request_metric                                 │
├─────────────────────────────────────────────────────┤
│ id           UUID PK                                │
│ endpoint     VARCHAR   (pattern e.g. /api/v1/schemas/{id}) │
│ method       VARCHAR                                │
│ status       SMALLINT                               │
│ duration_ms  INTEGER                                │
│ tenant_id    UUID FK                                │
│ occurred_at  TIMESTAMPTZ                            │
└─────────────────────────────────────────────────────┘

Partitioned by: occurred_at (daily)
Indexes: (endpoint, occurred_at), (tenant_id, occurred_at)
```

**OpenAPI Endpoints:**
```
GET /api/v1/admin/metrics/response-times
  ?from=&to=&endpoint=&percentile=p50|p95|p99
  → 200: MetricTimeSeries
```

**Acceptance Criteria:**
- Middleware adds < 1ms overhead per request (measured via benchmarks)
- Pre-computed hourly rollup table for fast dashboard queries
- Data retained for 90 days by default; configurable per deployment
- Super Admin portal charts render with correct p50/p95/p99 values (validated against raw data)

**Tech Stack:** Next.js middleware, PostgreSQL PARTITION BY RANGE, percentile_cont SQL aggregate

Part of Epic: Application Monitoring

---

## Epic 2 (#1592): Audit Logging

### Summary Table

| #   | Title                                      | Description                                                                        | Labels                                            | MVP | Parallel |
|-----|--------------------------------------------|------------------------------------------------------------------------------------|---------------------------------------------------|-----|----------|
| 2.1 (#1601) | Audit Event Data Model                     | Immutable `audit_log` table with event type enum, actor, resource, metadata        | `enhancement`, `mvp`, `monitoring`, `rest`       | Yes | No       |
| 2.2 (#1607) | Login / Logout Events                      | Record every login attempt (success and failure), logout, and session expiry       | `enhancement`, `mvp`, `monitoring`               | Yes | No       |
| 2.3 (#1613) | Schema Change Events                       | Record class/property create, update, delete, and version publish events           | `enhancement`, `mvp`, `monitoring`               | Yes | No       |
| 2.4 (#1798) | Permission Change Events                   | Record role assignments, permission grants/revocations, team membership changes    | `enhancement`, `mvp`, `monitoring`               | Yes | Yes      |
| 2.5 (#1799) | API Key Usage Events                       | Record first-use, rotation, revocation, and suspicious-use events per key         | `enhancement`, `mvp`, `monitoring`               | Yes | Yes      |
| 2.6 (#1800) | Export & Download Events                   | Record every OpenAPI export, code generation, and documentation download           | `enhancement`, `monitoring`                      | No  | Yes      |
| 2.7 (#1801) | Settings Change Events                     | Record changes to tenant, project, and user settings with before/after values     | `enhancement`, `mvp`, `monitoring`               | Yes | Yes      |
| 2.8 (#1802) | Audit Log Viewer UI                        | Filterable, searchable audit log table in admin portal with click-to-expand detail | `enhancement`, `mvp`, `monitoring`               | Yes | No       |
| 2.9 (#1803) | Audit Log Export (Compliance)              | Export filtered audit log as CSV or JSON for compliance review                    | `enhancement`, `mvp`, `monitoring`, `rest`       | Yes | Yes      |
| 2.10 (#1804) | Real-Time Audit Alerts                    | Alert on specific high-severity audit events (mass delete, admin privilege grant)  | `enhancement`, `monitoring`                      | No  | Yes      |
| 2.11 (#1805) | Immutable Log Guarantee                   | Enforce insert-only constraint on `audit_log`; no UPDATE or DELETE permissions    | `enhancement`, `mvp`, `monitoring`, `security`   | Yes | No       |
| 2.12 (#1806) | Audit Log Retention Policies              | Configurable retention per tenant (default: 1 year); archive to cold storage      | `enhancement`, `monitoring`                      | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#1601) — Audit Event Data Model

Design an immutable audit log table that captures every security-relevant action in the system. The table must be append-only enforced at the database role level.

```
┌─────────────────────────────────────────────────────┐
│  audit_log                                          │
├─────────────────────────────────────────────────────┤
│ id            UUID PK                               │
│ tenant_id     UUID FK                               │
│ actor_id      UUID FK (users)                       │
│ actor_type    ENUM (user | system | api_key)        │
│ event_type    ENUM (see catalog below)              │
│ resource_type VARCHAR  (schema | user | api_key...) │
│ resource_id   UUID                                  │
│ metadata_json JSONB    (before/after values, IP...) │
│ ip_address    INET                                  │
│ user_agent    VARCHAR                               │
│ occurred_at   TIMESTAMPTZ                           │
└─────────────────────────────────────────────────────┘

Event Type Catalog:
  auth.login.success, auth.login.failure, auth.logout,
  schema.class.create, schema.class.update, schema.class.delete,
  schema.version.publish,
  permission.role.assign, permission.role.revoke,
  api_key.create, api_key.rotate, api_key.revoke, api_key.suspicious_use,
  settings.update, export.openapi, export.code
```

**Acceptance Criteria:**
- Database role `app_user` has INSERT only on `audit_log` (no UPDATE, DELETE, TRUNCATE)
- Table partitioned by `occurred_at` month for query performance
- All existing application code paths that perform auditable actions emit events
- Automated test verifies insert-only constraint is enforced

Part of Epic: Audit Logging

---

#### 2.8 (#1802) — Audit Log Viewer UI

Build a paginated audit log table in the admin portal. Filters: date range, event type (multi-select), actor (user search), resource type, tenant (Super Admin only). Clicking a row expands to show full `metadata_json` detail in a readable formatted view.

```
Audit Log                              [Export CSV] [Export JSON]
──────────────────────────────────────────────────────────────
Filter: [All Events ▼] [All Users ▼] [Date Range ▼] [Apply]
──────────────────────────────────────────────────────────────
Time              │ Actor      │ Event               │ Resource
2026-04-03 14:22  │ alice@...  │ schema.class.update │ User (class)
2026-04-03 14:20  │ bob@...    │ auth.login.success  │ —
2026-04-03 13:45  │ system     │ api_key.rotate      │ Prod Key #42
──────────────────────────────────────────────────────────────
  [< Prev]                                          [Next >]
```

**Acceptance Criteria:**
- Table loads in < 500ms using indexed queries with cursor pagination
- Expanding a row shows formatted JSON of before/after metadata
- Export triggers 2.9 export pipeline with current filter state applied
- Viewer access restricted to users with `audit:read` permission

Part of Epic: Audit Logging

---

## Epic 3 (#1807): Log Management

### Summary Table

| #   | Title                                   | Description                                                                        | Labels                                 | MVP | Parallel |
|-----|-----------------------------------------|------------------------------------------------------------------------------------|----------------------------------------|-----|----------|
| 3.1 (#1808) | Centralized Log Aggregation             | Ship all application logs to ELK Stack or Grafana Loki; structured JSON format     | `enhancement`, `monitoring`           | No  | No       |
| 3.2 (#1809) | Structured Logging (Context-Rich)       | Add request ID, tenant ID, user ID, and trace ID to every log line                | `enhancement`, `mvp`, `monitoring`    | Yes | Yes      |
| 3.3 (#1810) | Log Search & Filter UI                  | Full-text log search with field filters (level, tenant, endpoint, trace_id)        | `enhancement`, `monitoring`           | No  | No       |
| 3.4 (#1811) | Log Levels & Runtime Configuration      | Support debug/info/warn/error; allow runtime log level change without restart      | `enhancement`, `monitoring`           | No  | Yes      |
| 3.5 (#1812) | Real-Time Log Streaming                 | WebSocket-based live log tail in admin portal                                      | `enhancement`, `monitoring`           | No  | No       |
| 3.6 (#1813) | Error Pattern Detection                 | Detect repeated error patterns and surface as grouped alerts                       | `enhancement`, `monitoring`           | No  | Yes      |
| 3.7 (#1814) | Sensitive Data Redaction in Logs        | Automatically redact PII patterns (email, phone, credit card) from log output     | `enhancement`, `monitoring`, `security` | No | Yes    |
| 3.8 (#1815) | Log Correlation with Traces             | Attach trace_id to logs; link log lines to distributed trace spans                | `enhancement`, `monitoring`           | No  | No       |
| 3.9 (#1816) | Log Export to SIEM                      | Webhook or S3 push of structured logs to customer SIEM (Splunk, Datadog, etc.)   | `enhancement`, `monitoring`           | No  | Yes      |

---

## Epic 4 (#1817): Alerting & Incident Management

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                 | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|----------------------------------------|-----|----------|
| 4.1 (#1818) | Custom Alert Rule Engine                   | Define alert rules: threshold, anomaly, composite (AND/OR), heartbeat, SLO-based | `enhancement`, `mvp`, `monitoring`    | Yes | No       |
| 4.2 (#1819) | Email Alert Channel                        | Send alert notifications via email with configurable recipients per rule          | `enhancement`, `mvp`, `monitoring`    | Yes | Yes      |
| 4.3 (#1820) | Slack Integration                          | Post alert notifications to Slack channels via incoming webhook                   | `enhancement`, `mvp`, `monitoring`    | Yes | Yes      |
| 4.4 (#1821) | PagerDuty Integration                      | Create PagerDuty incidents from critical alerts; auto-resolve on alert clear      | `enhancement`, `monitoring`           | No  | Yes      |
| 4.5 (#1822) | OpsGenie Integration                       | Create OpsGenie alerts with on-call routing and escalation policies               | `enhancement`, `monitoring`           | No  | Yes      |
| 4.6 (#1823) | Custom Webhook Alert Channel               | POST alert payload to any configured HTTPS webhook endpoint                       | `enhancement`, `monitoring`           | No  | Yes      |
| 4.7 (#1824) | SMS Alerts via Twilio                      | Send SMS alert to configured phone numbers for critical severity alerts           | `enhancement`, `monitoring`           | No  | Yes      |
| 4.8 (#1825) | Alert Escalation Policies                  | Auto-escalate unacknowledged alerts after configurable duration                  | `enhancement`, `monitoring`           | No  | Yes      |
| 4.9 (#1826) | Alert Templates                            | Pre-built alert rule templates for common scenarios (error spike, slow DB)        | `enhancement`, `monitoring`           | No  | Yes      |
| 4.10 (#1827) | Anomaly Detection                         | Statistical baseline modeling; alert when metrics deviate by > 2 sigma            | `enhancement`, `monitoring`           | No  | No       |
| 4.11 (#1828) | Incident Creation from Alerts             | Promote an alert to an incident with timeline, ownership, and status              | `enhancement`, `monitoring`           | No  | No       |
| 4.12 (#1829) | Incident Timeline Tracking                | Log events (alert fired, acknowledged, resolved) on a per-incident timeline      | `enhancement`, `monitoring`           | No  | Yes      |
| 4.13 (#1830) | Post-Mortem Templates                     | Structured post-mortem form attached to each resolved incident                    | `enhancement`, `monitoring`           | No  | Yes      |
| 4.14 (#1831) | MTTR / MTTA Metrics                       | Track Mean Time to Acknowledge and Mean Time to Resolve per team and service     | `enhancement`, `monitoring`           | No  | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#1818) — Custom Alert Rule Engine

Build a rule evaluation engine that runs on a configurable schedule (minimum 1-minute resolution) against metric snapshots. Each rule has: a metric selector, a condition (threshold/anomaly/composite), a severity (info/warning/critical), a cooldown period (minimum time between successive alerts for the same rule), and notification channels.

```
AlertRule {
  id, name, description
  metric: string          // e.g. "api.error_rate"
  condition: {
    type: threshold | anomaly | composite
    operator: gt | lt | gte | lte | eq
    value: number
    window_minutes: number
  }
  severity: info | warning | critical
  cooldown_minutes: number
  channels: AlertChannel[]
}
```

**Acceptance Criteria:**
- Rule evaluation runs every minute via cron job
- Alert fires when condition is met for the full `window_minutes` (not on a single data point)
- Alert clears and sends "resolved" notification when condition no longer met after cooldown
- Rule evaluation errors do not block other rules (isolated execution per rule)

Part of Epic: Alerting & Incident Management

---

## Epic 5 (#1832): SLA & SLO Management

### Summary Table

| #   | Title                                   | Description                                                                        | Labels                                 | MVP | Parallel |
|-----|-----------------------------------------|------------------------------------------------------------------------------------|----------------------------------------|-----|----------|
| 5.1 (#1833) | SLO Definition Model                    | Define availability, latency, and error rate SLOs per service/endpoint             | `enhancement`, `monitoring`, `rest`   | No  | No       |
| 5.2 (#1834) | Error Budget Tracking Dashboard         | Visualize remaining error budget; burn rate by hour/day/week                       | `enhancement`, `monitoring`           | No  | Yes      |
| 5.3 (#1835) | Burn Rate Alerting                      | Alert when error budget burns faster than sustainable rate (2x / 5x burn rate)    | `enhancement`, `monitoring`           | No  | Yes      |
| 5.4 (#1836) | Budget Exhaustion Prediction            | Predict when error budget will be exhausted at current burn rate                  | `enhancement`, `monitoring`           | No  | Yes      |
| 5.5 (#1837) | SLA Report Generation                   | Monthly customer-facing SLA performance report (PDF)                              | `enhancement`, `monitoring`           | No  | Yes      |
| 5.6 (#1838) | SLA Breach Tracking                     | Record each SLA breach with duration, impact, and root cause link                 | `enhancement`, `monitoring`           | No  | Yes      |
| 5.7 (#1839) | Historical SLA Performance Chart        | Rolling 12-month SLA achievement percentage per service                           | `enhancement`, `monitoring`           | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 (#1833) — SLO Definition Model

Allow Super Admins to define Service Level Objectives for each monitored service. SLOs are expressed as: service name, metric type (availability | latency | error_rate), target value, measurement window (rolling 30 days), and the metric source.

```
┌──────────────────────────────────────────────┐
│  slo_definition                              │
├──────────────────────────────────────────────┤
│ id             UUID PK                       │
│ name           VARCHAR   "API Availability"  │
│ service        VARCHAR   "api"               │
│ metric_type    ENUM      availability|latency|error_rate │
│ target         NUMERIC   99.9                │
│ target_unit    ENUM      percent|ms|percent  │
│ window_days    INTEGER   30                  │
│ created_at     TIMESTAMPTZ                   │
└──────────────────────────────────────────────┘
```

**OpenAPI Endpoints:**
```
GET  /api/v1/admin/slos              → 200: SLOList
POST /api/v1/admin/slos              → 201: SLO
GET  /api/v1/admin/slos/{id}/status  → 200: SLOStatus {
  current_value, target, error_budget_remaining_percent,
  burn_rate_1h, burn_rate_24h, predicted_exhaustion_at
}
```

**Acceptance Criteria:**
- SLO status computed on-demand from `api_request_metric` data
- `error_budget_remaining_percent` = (budget_total - budget_consumed) / budget_total × 100
- Status endpoint responds in < 500ms using pre-computed hourly rollups
- Burn rate calculated as: actual error rate / (1 - target rate)

Part of Epic: SLA & SLO Management
