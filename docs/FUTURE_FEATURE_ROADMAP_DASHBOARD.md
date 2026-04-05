# Objectified: Dashboard - Feature Roadmap

> A comprehensive, role-adaptive dashboard system providing personal productivity views, team collaboration overviews, and enterprise-grade executive/compliance dashboards. Every user tier gets a customizable home experience that surfaces the data most relevant to their role.
>
> **Revenue Model**: Personal and team dashboards included in all tiers; enterprise dashboards (compliance, security, multi-tenant, custom builder) gated at Enterprise; custom dashboard builder is an Enterprise upsell
>
> **Tech Stack**: NextJS App Router, Radix UI, Recharts for in-app charts, React DnD for drag-and-drop layout, PostgreSQL (widget config, dashboard state), OpenAPI 3.1

---

## MVP Definition

- Personal dashboard with recently viewed projects, recently edited schemas, and activity heatmap
- Last login info widget with date, IP, and device
- Favorite projects pinned to dashboard for quick access
- Personal contribution stats (classes created, edits made, reviews completed)
- Notifications center with unread count, categories, and mark-read actions
- Schema health dashboard: overall health metrics, violation summary, documentation coverage
- Quick actions panel: create project, create class, import spec

---

## Epic 1 (#1624): Personal Dashboard

### Summary Table

| #   | Title                                    | Description                                                                        | Labels                                    | MVP | Parallel |
|-----|------------------------------------------|------------------------------------------------------------------------------------|-------------------------------------------|-----|----------|
| 1.1 (#1625) | Personal Dashboard Layout Engine         | Drag-and-drop widget grid with save/restore layout; default layout for new users   | `enhancement`, `mvp`, `dashboard`        | Yes | No       |
| 1.2 (#1626) | Last Login Info Widget                   | Display last successful login: timestamp, IP address, device, geolocation          | `enhancement`, `mvp`, `dashboard`        | Yes | Yes      |
| 1.3 (#1627) | Recently Viewed Projects Widget          | Show last 5 visited projects with thumbnail, last-visit time, quick-open link      | `enhancement`, `mvp`, `dashboard`        | Yes | Yes      |
| 1.4 (#1628) | Recently Edited Classes Widget           | List recently modified classes across projects with direct canvas link             | `enhancement`, `mvp`, `dashboard`        | Yes | Yes      |
| 1.5 (#1630) | Activity Heatmap Widget                  | GitHub-style contribution calendar showing daily schema edit activity              | `enhancement`, `mvp`, `dashboard`        | Yes | Yes      |
| 1.6 (#1631) | Favorite Projects Widget                 | Pin up to 10 projects for one-click access; reorder via drag                       | `enhancement`, `mvp`, `dashboard`        | Yes | Yes      |
| 1.7 (#1632) | Personal Contribution Stats Widget       | Classes created, edits made, reviews completed — current month vs prior month     | `enhancement`, `mvp`, `dashboard`        | Yes | Yes      |
| 1.8 (#1633) | Time Spent per Project Widget            | Approximate time-on-page per project from session tracking                         | `enhancement`, `dashboard`               | No  | Yes      |
| 1.9 (#1634) | Weekly/Monthly Productivity Trends       | Line chart: edit count and review throughput over rolling 4-week or 3-month view   | `enhancement`, `dashboard`               | No  | Yes      |
| 1.10 (#1635) | Notifications Center Widget             | Unified inbox: mentions, schema updates, review requests; mark read/unread         | `enhancement`, `mvp`, `dashboard`        | Yes | No       |
| 1.11 (#1636) | Notifications: Snooze & Action Buttons  | Snooze a notification for 1h/1d; inline action buttons (approve, view, dismiss)    | `enhancement`, `dashboard`               | No  | Yes      |
| 1.12 (#1637) | Task & Assignment Tracking Widget       | Assigned tasks with due dates, priority badges, and quick-complete checkbox        | `enhancement`, `dashboard`               | No  | Yes      |
| 1.13 (#1639) | Personal Goals & Streak Widget          | Set productivity goals; track daily-active streaks and show achievement badges     | `enhancement`, `dashboard`               | No  | Yes      |
| 1.14 (#1640) | Quick Actions Panel                     | Prominent shortcuts: create project, create class, import spec, recent actions     | `enhancement`, `mvp`, `dashboard`        | Yes | Yes      |
| 1.15 (#1641) | Multiple Dashboard Tabs                 | Save multiple named dashboard layouts (Work, Review, Personal) and switch tabs     | `enhancement`, `dashboard`               | No  | Yes      |
| 1.16 (#1642) | Full-Screen Dashboard Mode              | Expand dashboard to full viewport; useful for display on shared screens            | `enhancement`, `dashboard`               | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1625) — Personal Dashboard Layout Engine

Implement a responsive grid layout system where widgets snap to a 12-column grid. Users drag widgets to reposition and resize them. Layout state is persisted to `user_dashboard_config` (JSON blob) and restored on next login. A "Reset to Default" option restores the opinionated default layout shipped with the product.

```
┌──────────────────────────────────────────────────┐
│  Dashboard                        [+ Widget] [⋮] │
├──────────┬───────────────┬─────────────┬─────────┤
│ Last     │ Recent        │ Quick       │ Notifs  │
│ Login    │ Projects      │ Actions     │ (badge) │
├──────────┴───────────────┼─────────────┴─────────┤
│ Activity Heatmap (wide)  │ Contribution Stats     │
├──────────────────────────┼────────────────────────┤
│ Recently Edited Classes  │ Favorite Projects       │
└──────────────────────────┴────────────────────────┘
```

**Acceptance Criteria:**
- Widget positions persist across browser sessions (stored server-side, not localStorage)
- Drag-and-drop does not interfere with widget scroll areas
- Default layout renders correctly on 1280px+ viewports
- Mobile view collapses to single-column stack

**Tech Stack:** react-grid-layout, PostgreSQL `user_dashboard_config` JSONB column

Part of Epic: Personal Dashboard

---

#### 1.10 (#1635) — Notifications Center Widget

Aggregate all notification types (schema review requests, @mentions, approval decisions, system alerts) into a unified inbox widget. Group by category. Unread count badge visible on the widget header. Mark-all-read button. Click-through to the originating resource.

```
Notifications           [Mark all read] [⚙]
─────────────────────────────────────────
● Review Request   "User schema needs review"   2m ago
● Mention          "@you in Order.payment field" 1h ago
✓ Approved         "v2 schema was approved"      3h ago
─────────────────────────────────────────
  [Load more]
```

**Acceptance Criteria:**
- Notifications load from `/api/v1/notifications` with cursor pagination
- Unread count badge updates via polling (30s interval) or WebSocket push
- Mark-as-read updates persist immediately (optimistic UI)
- Clicking a notification navigates to the relevant resource

**Depends on:** Notifications data model (separate epic)

Part of Epic: Personal Dashboard

---

## Epic 2 (#1643): Schema Health Dashboard

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                               | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|--------------------------------------|-----|----------|
| 2.1 (#1644) | Schema Health Overview Panel               | Total classes, properties, relationships; validation score trend; documentation % | `enhancement`, `mvp`, `dashboard`   | Yes | No       |
| 2.2 (#1645) | Most Common Violations List                | Ranked list of lint rule violations by frequency across all schemas in a project  | `enhancement`, `mvp`, `dashboard`   | Yes | Yes      |
| 2.3 (#1646) | Classes with Most Violations               | Top 10 classes by violation count with direct canvas links                        | `enhancement`, `dashboard`          | No  | Yes      |
| 2.4 (#1648) | Circular Dependency Count                  | Count of detected circular dependency chains with click-to-inspect links          | `enhancement`, `dashboard`          | No  | Yes      |
| 2.5 (#1650) | Unused / Orphaned Classes List             | List of classes not referenced by any other class or path operation               | `enhancement`, `dashboard`          | No  | Yes      |
| 2.6 (#1652) | Score vs Team Average Comparison           | Compare project quality score against org-wide team average                       | `enhancement`, `dashboard`          | No  | Yes      |
| 2.7 (#1654) | Version-to-Version Score Improvement       | Delta chart showing quality score improvement (or regression) across versions     | `enhancement`, `dashboard`          | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#1644) — Schema Health Overview Panel

Build the top-level health panel displayed at `/projects/{id}/health`. Aggregate: total class count, total property count, total relationship count, current quality score (from linting engine), documentation coverage %, and a 90-day quality score trend sparkline.

```
Schema Health — My E-commerce API v3
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ Classes  │ Props    │ Relations│ Quality  │ Doc Cov  │
│   42     │  317     │   28     │  81/100  │  74%     │
└──────────┴──────────┴──────────┴──────────┴──────────┘
Quality Score (90d): [sparkline: 65 → 72 → 78 → 81]
Most Common Violations: [bar chart]
```

**Acceptance Criteria:**
- All counts computed server-side; panel loads in < 1 second
- Quality score sourced from `schema_quality_score` table (latest snapshot per version)
- Documentation coverage = (classes with description / total classes) × 100
- Trend sparkline shows last 90 days of daily snapshots (or version snapshots if fewer)

**Tech Stack:** PostgreSQL aggregation, Recharts sparkline component

Part of Epic: Schema Health Dashboard

---

## Epic 3 (#1656): Team Dashboard

### Summary Table

| #   | Title                                   | Description                                                                        | Labels                             | MVP | Parallel |
|-----|-----------------------------------------|------------------------------------------------------------------------------------|------------------------------------|-----|----------|
| 3.1 (#1658) | Team Overview Widget                    | Team activity feed: who edited what, when; shared project status summary           | `enhancement`, `dashboard`        | No  | No       |
| 3.2 (#1660) | Team Contribution Breakdown             | Per-member contribution chart for the current sprint/month                         | `enhancement`, `dashboard`        | No  | Yes      |
| 3.3 (#1662) | Most Active Collaborators               | Ranked list of contributors by edits, reviews, and approvals this period           | `enhancement`, `dashboard`        | No  | Yes      |
| 3.4 (#1664) | Review Pending Items Widget             | List of schema changes awaiting review; assignee, age, and urgency indicator       | `enhancement`, `dashboard`        | No  | Yes      |
| 3.5 (#1666) | Team Goals Progress Widget              | Shared team goals with progress bars (e.g., "Document 100% of properties")        | `enhancement`, `dashboard`        | No  | Yes      |
| 3.6 (#1668) | Shared Team Calendar                    | Upcoming review deadlines, publish dates, and team events on a calendar view      | `enhancement`, `dashboard`        | No  | No       |
| 3.7 (#1670) | Team Announcements Widget               | Admin-posted rich-text announcements pinned to the team dashboard                  | `enhancement`, `dashboard`        | No  | Yes      |
| 3.8 (#1672) | Team Leaderboard (Opt-In)              | Gamified contribution ranking; each user must opt-in before their name appears     | `enhancement`, `dashboard`        | No  | Yes      |

---

## Epic 4 (#1674): Enterprise Dashboard

### Summary Table

| #   | Title                                       | Description                                                                        | Labels                                      | MVP | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 4.1 (#1676) | Executive Summary Dashboard                 | Org-wide: health score, total schemas, DAU/MAU, license utilization, KPI cards    | `enhancement`, `dashboard`                 | No  | No       |
| 4.2 (#1678) | Multi-Tenant Overview                       | Tenant comparison: health rankings, resource allocation, growth trends, inactive   | `enhancement`, `dashboard`                 | No  | Yes      |
| 4.3 (#1680) | Compliance Dashboard                        | GDPR/HIPAA compliance scores, audit readiness, policy violations, sensitive fields | `enhancement`, `dashboard`, `security`     | No  | Yes      |
| 4.4 (#1682) | Security Dashboard                          | Failed logins, API key anomalies, privilege escalation, security score by project  | `enhancement`, `dashboard`, `security`     | No  | Yes      |
| 4.5 (#1684) | Usage Analytics Dashboard                   | API request volume, peak times heatmap, endpoint rankings, error rates, p99        | `enhancement`, `dashboard`                 | No  | Yes      |
| 4.6 (#1686) | Resource & Capacity Planning                | Storage utilization, DB growth projections, API capacity forecasts                 | `enhancement`, `dashboard`                 | No  | Yes      |
| 4.7 (#1688) | Admin Control Panel Widget                  | User provisioning queue, pending requests, feature flag status, A/B test perf     | `enhancement`, `dashboard`                 | No  | Yes      |
| 4.8 (#1690) | Custom Dashboard Builder                    | Drag-and-drop designer with custom metric definitions and SQL query widgets        | `enhancement`, `dashboard`                 | No  | No       |
| 4.9 (#1692) | Role-Based Dashboard Templates              | Pre-built layouts for developer, architect, manager, executive, security officer   | `enhancement`, `dashboard`                 | No  | Yes      |
| 4.10 (#1694) | Embeddable Dashboard (iframe)              | Generate signed iframe-embeddable dashboard URLs for external portals              | `enhancement`, `dashboard`, `rest`         | No  | Yes      |
| 4.11 (#1696) | Dashboard Version History                  | Track changes to custom dashboard layouts; restore previous versions               | `enhancement`, `dashboard`                 | No  | Yes      |

### Detailed Issue Descriptions

#### 4.3 (#1680) — Compliance Dashboard

Surface compliance-relevant data for GDPR, HIPAA, SOC 2, and custom regulation profiles. Each regulation is represented as a compliance score (0–100) based on: PII field classification coverage, audit log completeness, access review recency, and data residency configuration.

```
Compliance Dashboard — Acme Corp
┌──────────────────────────────────────────────────────┐
│  Regulation Scores                                   │
│  GDPR:  88/100  ✓  SOC 2:  72/100  ⚠  HIPAA: N/A   │
├──────────────────────────────────────────────────────┤
│  Policy Violations (3 open)                          │
│  ⚠ 2 schemas have unclassified PII fields           │
│  ⚠ Access review overdue for 4 users                │
│  ✓ Audit logs complete for past 365 days            │
├──────────────────────────────────────────────────────┤
│  Sensitive Field Inventory                [Export ▼] │
│  42 fields marked PII across 18 classes              │
└──────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Compliance scores computed from rule engine (same infrastructure as linting)
- Each violation links to the specific schema or user record requiring action
- Export button generates a PDF compliance summary report
- Dashboard access restricted to users with `compliance:read` permission

**Tech Stack:** PostgreSQL aggregation, PDF export via Puppeteer, role-based access check

Part of Epic: Enterprise Dashboard

---

#### 4.8 (#1690) — Custom Dashboard Builder

Allow Enterprise customers to design custom dashboards using a drag-and-drop widget designer. Widgets include: pre-built metric widgets, SQL query widgets (read-only replica), text/markdown widgets, and external data source embeds. Dashboards can be published to other users or embedded externally.

**Acceptance Criteria:**
- Widget palette includes all standard dashboard widgets plus blank SQL widget
- SQL widget executes against a read-only PostgreSQL replica with a query timeout of 5s
- Dashboard layout serialized as JSON and versioned in `enterprise_dashboard` table
- Sharing supports: private, team, org-wide, and public (with signed URL)
- White-label branding option: custom logo and color scheme per dashboard

Part of Epic: Enterprise Dashboard
