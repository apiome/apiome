# Objectified: Multi-Tenancy & Organizations - Feature Roadmap

> Full-featured multi-tenancy system providing hierarchical organization structure, industry classification, cross-team schema sharing, compliance recommendations per industry vertical, and enterprise-grade tenant administration — all built on top of the existing tenant CRUD, slug management, and Super Admin portal foundation.
>
> **Revenue Model**: Core multi-tenancy in all tiers; industry tagging, benchmarking, custom industry categories, and cross-tenant schema sharing gated at Pro/Enterprise; compliance framework recommendations and industry-specific validation rules are Enterprise-only
>
> **Tech Stack**: NextJS App Router, PostgreSQL, Redis, Radix UI, SCIM 2.0, OpenAPI 3.1

---

## MVP Definition

- Industry classification: standard category taxonomy (15 industries) with multi-industry support and primary designation
- Industry tags surfaced on tenant profile (public) and tenant admin dashboard (private)
- Tenant resource quotas: configurable per-tenant limits on projects, versions, classes, API calls
- Industry-filtered template marketplace ("Recommended for your industry")
- Schema Showcase filtered by industry
- REST API: industry tags CRUD with webhook events on industry change
- Super Admin: view all tenants by industry, manage industry taxonomy

---

## Epic 1: Tenant Industry Tagging — [#2483](https://github.com/KenSuenobu/objectified-commercial/issues/2483)

### Summary Table

| #   | Issue | Title                                     | Description                                                                       | Labels                                        | MVP | Parallel |
|-----|-------|-------------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 1.1 | [#2488](https://github.com/KenSuenobu/objectified-commercial/issues/2488) | Industry Taxonomy Data Model             | `industry` lookup table with standard categories; `tenant_industry` junction table| `enhancement`, `mvp`, `tenancy`, `rest`      | Yes | No       |
| 1.2 | [#2489](https://github.com/KenSuenobu/objectified-commercial/issues/2489) | Standard Industry Categories             | Seed 15 standard industry categories (Financial, Healthcare, E-commerce, etc.)    | `enhancement`, `mvp`, `tenancy`              | Yes | No       |
| 1.3 | [#2490](https://github.com/KenSuenobu/objectified-commercial/issues/2490) | Tenant Industry Assignment UI            | Multi-select industry picker in tenant settings; primary industry designation     | `enhancement`, `mvp`, `tenancy`              | Yes | No       |
| 1.4 | [#2491](https://github.com/KenSuenobu/objectified-commercial/issues/2491) | Multi-Industry Support                   | Allow multiple tags per tenant; primary vs secondary designation; weight scoring  | `enhancement`, `mvp`, `tenancy`              | Yes | Yes      |
| 1.5 | [#2492](https://github.com/KenSuenobu/objectified-commercial/issues/2492) | Industry History Tracking                | Record industry changes over time in `tenant_industry_history`                   | `enhancement`, `tenancy`                     | No  | Yes      |
| 1.6 | [#2493](https://github.com/KenSuenobu/objectified-commercial/issues/2493) | Custom Industry Categories               | Enterprise tenants define custom industry sub-categories with parent-child hierarchy| `enhancement`, `tenancy`                    | No  | No       |
| 1.7 | [#2494](https://github.com/KenSuenobu/objectified-commercial/issues/2494) | Industry Tags in REST API                | Expose industry tags on `GET /api/v1/tenants/{id}` and update via `PUT`           | `enhancement`, `mvp`, `tenancy`, `rest`      | Yes | Yes      |
| 1.8 | [#2495](https://github.com/KenSuenobu/objectified-commercial/issues/2495) | Webhook Events for Industry Changes      | Emit `tenant.industry.updated` webhook when industry tags change                  | `enhancement`, `tenancy`, `rest`             | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 — Industry Taxonomy Data Model — [#2488](https://github.com/KenSuenobu/objectified-commercial/issues/2488)

Create the database schema for the industry taxonomy. The `industry` table holds the canonical list of industry categories (system-provided, admin-managed). The `tenant_industry` junction table links tenants to one or more industries with a `is_primary` flag and `weight` for relevance scoring.

```
┌─────────────────────────────────────────┐
│              industry                   │
├─────────────────────────────────────────┤
│ id          UUID PK                     │
│ slug        VARCHAR UNIQUE              │
│ name        VARCHAR                     │
│ description TEXT                        │
│ parent_id   UUID FK SELF (nullable)     │
│ is_active   BOOLEAN DEFAULT true        │
│ sort_order  INTEGER                     │
│ created_at  TIMESTAMPTZ                 │
└──────────────────────┬──────────────────┘
                       │ M:N
┌──────────────────────▼──────────────────┐
│           tenant_industry               │
├─────────────────────────────────────────┤
│ tenant_id   UUID FK                     │
│ industry_id UUID FK                     │
│ is_primary  BOOLEAN DEFAULT false       │
│ weight      SMALLINT DEFAULT 100        │
│ assigned_at TIMESTAMPTZ                 │
│ assigned_by UUID FK (users)             │
│ PRIMARY KEY (tenant_id, industry_id)    │
└─────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Migration seeds all 15 standard industry categories
- Each tenant limited to one `is_primary = true` industry (enforced via partial unique index)
- Composite index on `(industry_id, is_primary)` for industry-based tenant listing queries
- `#499` addressed by this issue

**Tech Stack:** PostgreSQL, partial unique index, OpenAPI component schemas

Part of Epic: [#2483](https://github.com/KenSuenobu/objectified-commercial/issues/2483) — Tenant Industry Tagging

---

#### 1.2 — Standard Industry Categories — [#2489](https://github.com/KenSuenobu/objectified-commercial/issues/2489)

Seed the canonical 15-category industry taxonomy:

| Slug | Name |
|------|------|
| `financial-services` | Financial Services |
| `healthcare` | Healthcare |
| `e-commerce` | E-commerce |
| `saas-b2b` | SaaS / B2B |
| `government` | Government & Public Sector |
| `education` | Education |
| `manufacturing` | Manufacturing |
| `technology` | Technology |
| `real-estate` | Real Estate |
| `logistics` | Logistics & Transportation |
| `media-entertainment` | Media & Entertainment |
| `energy-utilities` | Energy & Utilities |
| `professional-services` | Professional Services |
| `non-profit` | Non-Profit & NGO |
| `other` | Other / Multi-Industry |

**Acceptance Criteria:**
- Categories seeded in a repeatable migration (idempotent on re-run)
- System-managed categories cannot be deleted via the tenant UI (Super Admin only)
- Each category has a slug, name, and placeholder description

Part of Epic: [#2483](https://github.com/KenSuenobu/objectified-commercial/issues/2483) — Tenant Industry Tagging

---

## Epic 2: Industry-Specific Features — [#2484](https://github.com/KenSuenobu/objectified-commercial/issues/2484)

### Summary Table

| #   | Issue | Title                                      | Description                                                                       | Labels                                   | MVP | Parallel |
|-----|-------|--------------------------------------------|-----------------------------------------------------------------------------------|------------------------------------------|-----|----------|
| 2.1 | [#2496](https://github.com/KenSuenobu/objectified-commercial/issues/2496) | Compliance Recommendations by Industry    | Auto-suggest compliance frameworks (HIPAA, PCI DSS, FedRAMP) based on industry   | `enhancement`, `tenancy`, `security`    | No  | No       |
| 2.2 | [#2497](https://github.com/KenSuenobu/objectified-commercial/issues/2497) | Industry Compliance Checklist              | Per-regulation checklist surfaced in the compliance dashboard                     | `enhancement`, `tenancy`                | No  | Yes      |
| 2.3 | [#2498](https://github.com/KenSuenobu/objectified-commercial/issues/2498) | Industry-Filtered Template Marketplace    | "Recommended for your industry" section in template browser; filter by industry  | `enhancement`, `mvp`, `tenancy`         | Yes | Yes      |
| 2.4 | [#2499](https://github.com/KenSuenobu/objectified-commercial/issues/2499) | Schema Showcase Industry Filter            | Filter Schema Showcase gallery by industry; "Schemas from [Industry]" collections | `enhancement`, `mvp`, `tenancy`         | Yes | Yes      |
| 2.5 | [#2500](https://github.com/KenSuenobu/objectified-commercial/issues/2500) | Industry Leaderboards                      | Rank tenants by quality score within their primary industry                      | `enhancement`, `tenancy`                | No  | Yes      |
| 2.6 | [#2501](https://github.com/KenSuenobu/objectified-commercial/issues/2501) | Industry-Specific Validation Rules        | Optional validation rule sets tailored per industry (PHI fields, PCI, etc.)      | `enhancement`, `tenancy`, `security`    | No  | No       |
| 2.7 | [#2502](https://github.com/KenSuenobu/objectified-commercial/issues/2502) | Industry Benchmarking                      | Compare tenant quality score against industry median; industry average metrics   | `enhancement`, `tenancy`                | No  | Yes      |
| 2.8 | [#2503](https://github.com/KenSuenobu/objectified-commercial/issues/2503) | Industry-Based API Quotas                 | Configure different rate limits and resource quotas per industry tier             | `enhancement`, `tenancy`                | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 — Compliance Recommendations by Industry — [#2496](https://github.com/KenSuenobu/objectified-commercial/issues/2496)

Based on a tenant's assigned industries, surface relevant compliance frameworks and their checklist items in the compliance dashboard. Maintain a `compliance_framework_industry` mapping table that links regulatory frameworks to industries.

| Industry | Recommended Frameworks |
|----------|----------------------|
| Healthcare | HIPAA, FHIR R4, HL7 |
| Financial Services | PCI DSS, SOX, Open Banking |
| Government | FedRAMP, NIST 800-53 |
| E-commerce | PCI DSS, GDPR |
| SaaS/B2B | SOC 2, ISO 27001, GDPR |

**Acceptance Criteria:**
- Compliance recommendations appear in the Compliance Dashboard for tenants with assigned industries
- Each recommendation links to the external regulation documentation
- Tenants can dismiss recommendations that don't apply (with reason recorded)
- Recommendations re-surface when industry tags change

Part of Epic: [#2484](https://github.com/KenSuenobu/objectified-commercial/issues/2484) — Industry-Specific Features

---

## Epic 3: Tenant Profile & Discovery — [#2485](https://github.com/KenSuenobu/objectified-commercial/issues/2485)

### Summary Table

| #   | Issue | Title                                      | Description                                                                       | Labels                                   | MVP | Parallel |
|-----|-------|--------------------------------------------|-----------------------------------------------------------------------------------|------------------------------------------|-----|----------|
| 3.1 | [#2504](https://github.com/KenSuenobu/objectified-commercial/issues/2504) | Industry Tags on Tenant Public Profile     | Display industry badges and "Serving [Industry]" on the public tenant profile     | `enhancement`, `mvp`, `tenancy`         | Yes | Yes      |
| 3.2 | [#2505](https://github.com/KenSuenobu/objectified-commercial/issues/2505) | Industry Dashboard Insights (Private)      | Private dashboard section: industry tips, regulatory updates, peer comparisons    | `enhancement`, `tenancy`                | No  | Yes      |
| 3.3 | [#2506](https://github.com/KenSuenobu/objectified-commercial/issues/2506) | Global Search by Industry                  | `?industry=healthcare` filter on tenant and schema search endpoints               | `enhancement`, `mvp`, `tenancy`, `rest` | Yes | Yes      |
| 3.4 | [#2507](https://github.com/KenSuenobu/objectified-commercial/issues/2507) | Browse Page Industry Facets               | Industry sidebar facets on the public browse page; industry tag cloud             | `enhancement`, `tenancy`                | No  | Yes      |
| 3.5 | [#2508](https://github.com/KenSuenobu/objectified-commercial/issues/2508) | Popular Industries Widget                  | "Popular industries this month" widget on browse homepage                         | `enhancement`, `tenancy`                | No  | Yes      |

---

## Epic 4: Organization Management — [#2486](https://github.com/KenSuenobu/objectified-commercial/issues/2486)

### Summary Table

| #   | Issue | Title                                      | Description                                                                       | Labels                                      | MVP | Parallel |
|-----|-------|--------------------------------------------|-----------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 4.1 | [#2509](https://github.com/KenSuenobu/objectified-commercial/issues/2509) | Hierarchical Organization Structure        | Company → Teams → Projects hierarchy with inheritance of org-level settings       | `enhancement`, `tenancy`, `rest`           | No  | No       |
| 4.2 | [#2510](https://github.com/KenSuenobu/objectified-commercial/issues/2510) | Organization-Wide Settings & Policies      | Org-level defaults for linting rules, import settings, API quotas, security policies| `enhancement`, `tenancy`                 | No  | Yes      |
| 4.3 | [#2511](https://github.com/KenSuenobu/objectified-commercial/issues/2511) | Cross-Team Schema Sharing                  | Publish schemas from one team as accessible to other teams within the org        | `enhancement`, `tenancy`, `rest`           | No  | No       |
| 4.4 | [#2512](https://github.com/KenSuenobu/objectified-commercial/issues/2512) | Organization Admin Dashboard               | Aggregated view: schema count, quality scores, team activity, compliance status   | `enhancement`, `tenancy`                  | No  | Yes      |
| 4.5 | [#2513](https://github.com/KenSuenobu/objectified-commercial/issues/2513) | Tenant Resource Quotas                     | Per-tenant configurable limits: projects, versions, classes, API calls/day        | `enhancement`, `mvp`, `tenancy`, `rest`    | Yes | No       |
| 4.6 | [#2514](https://github.com/KenSuenobu/objectified-commercial/issues/2514) | Tenant Billing & Usage Tracking            | Track resource consumption per tenant for billing and overage alerting            | `enhancement`, `tenancy`                  | No  | Yes      |
| 4.7 | [#2515](https://github.com/KenSuenobu/objectified-commercial/issues/2515) | Custom Branding per Organization           | Upload org logo, set brand colors; applied to public profile and shared reports   | `enhancement`, `tenancy`                  | No  | Yes      |
| 4.8 | [#2516](https://github.com/KenSuenobu/objectified-commercial/issues/2516) | Cross-Tenant Schema Sharing (Controlled)   | Explicitly share specific schemas between tenants with access control             | `enhancement`, `tenancy`                  | No  | No       |
| 4.9 | [#2517](https://github.com/KenSuenobu/objectified-commercial/issues/2517) | Organization-Level Audit Logs              | Aggregate audit events across all tenants in an organization                     | `enhancement`, `tenancy`                  | No  | Yes      |

### Detailed Issue Descriptions

#### 4.5 — Tenant Resource Quotas — [#2513](https://github.com/KenSuenobu/objectified-commercial/issues/2513)

Implement configurable resource quotas per tenant, enforced at the API layer. Quotas: `max_projects`, `max_versions_per_project`, `max_classes_per_version`, `max_api_calls_per_day`, `max_import_size_mb`. Default quotas are set per subscription tier; Super Admins can override per tenant.

```
┌────────────────────────────────────────────┐
│           tenant_quota                     │
├────────────────────────────────────────────┤
│ tenant_id                UUID FK PK        │
│ max_projects             INTEGER           │
│ max_versions_per_project INTEGER           │
│ max_classes_per_version  INTEGER           │
│ max_api_calls_per_day    INTEGER           │
│ max_import_size_mb       INTEGER           │
│ override_by              UUID FK (users)   │
│ updated_at               TIMESTAMPTZ       │
└────────────────────────────────────────────┘
```

**OpenAPI Endpoints:**
```
GET /api/v1/admin/tenants/{id}/quota   → 200: TenantQuota
PUT /api/v1/admin/tenants/{id}/quota   → 200: TenantQuota
GET /api/v1/tenant/quota/usage         → 200: QuotaUsage {
  projects: { used, limit },
  api_calls_today: { used, limit },
  ...
}
```

**Acceptance Criteria:**
- Quota checks run before every resource creation; return 429 with `{"error": "quota_exceeded", "resource": "projects"}` on violation
- Usage counters for `max_api_calls_per_day` stored in Redis (24h TTL)
- Tenant dashboard shows current usage vs quota with progress bars
- Super Admin can set `null` for any quota (meaning unlimited)

Part of Epic: [#2486](https://github.com/KenSuenobu/objectified-commercial/issues/2486) — Organization Management

---

## Epic 5: Super Admin & Reporting — [#2487](https://github.com/KenSuenobu/objectified-commercial/issues/2487)

### Summary Table

| #   | Issue | Title                                      | Description                                                                       | Labels                                   | MVP | Parallel |
|-----|-------|--------------------------------------------|-----------------------------------------------------------------------------------|------------------------------------------|-----|----------|
| 5.1 | [#2518](https://github.com/KenSuenobu/objectified-commercial/issues/2518) | Industry Distribution Dashboard            | Super Admin: tenant count, growth, and engagement by industry                    | `enhancement`, `mvp`, `tenancy`         | Yes | No       |
| 5.2 | [#2519](https://github.com/KenSuenobu/objectified-commercial/issues/2519) | Industry Taxonomy Management               | Add, edit, archive, merge, and alias industry categories; hierarchy editor        | `enhancement`, `tenancy`                | No  | Yes      |
| 5.3 | [#2520](https://github.com/KenSuenobu/objectified-commercial/issues/2520) | Industry Reports Export                    | Export: schemas per industry, quality score by industry, active users by industry | `enhancement`, `tenancy`, `rest`        | No  | Yes      |
| 5.4 | [#2521](https://github.com/KenSuenobu/objectified-commercial/issues/2521) | Business Intelligence: Industry Segmentation | Churn analysis, cross-sell opportunities, feature adoption — all by industry  | `enhancement`, `tenancy`                | No  | No       |
| 5.5 | [#2522](https://github.com/KenSuenobu/objectified-commercial/issues/2522) | Industry-Based GraphQL Filtering           | Add `industry` filter arguments to the GraphQL schema browser queries            | `enhancement`, `tenancy`                | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 — Industry Distribution Dashboard — [#2518](https://github.com/KenSuenobu/objectified-commercial/issues/2518)

Build a Super Admin dashboard section that aggregates tenant data by industry. Surface: tenant count per industry (pie chart), month-over-month growth by industry (line chart), schema quality average per industry, and engagement metrics (DAU by industry).

```
Super Admin → Industries
┌──────────────────────────────────────────────────────┐
│  Industry Distribution                [Export CSV]   │
├──────────────┬──────────────┬───────────┬────────────┤
│ Industry     │ Tenants      │ MoM Growth│ Avg Quality│
├──────────────┼──────────────┼───────────┼────────────┤
│ SaaS/B2B     │    342       │  +12%     │  78/100   │
│ Healthcare   │    187       │  +8%      │  82/100   │
│ E-commerce   │    156       │  +5%      │  74/100   │
└──────────────┴──────────────┴───────────┴────────────┘
```

**Acceptance Criteria:**
- Dashboard renders using pre-computed daily aggregates (< 1s load time)
- Industry distribution pie chart links to filtered tenant list
- CSV export includes all columns and all industries
- Data refreshed nightly via scheduled aggregation job

Part of Epic: [#2487](https://github.com/KenSuenobu/objectified-commercial/issues/2487) — Super Admin & Reporting
