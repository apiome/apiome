# Objectified: Schema Showcase - Feature Roadmap

> A curated public gallery on browse.objectified.dev that recognizes and promotes organizations producing exemplary API schemas. The Showcase drives community engagement, provides marketing value to featured companies, and establishes Objectified as the authority on API schema quality.
>
> **Revenue Model**: Free participation; featured companies receive marketing value (traffic, recognition); Showcase drives Pro/Enterprise upsells via quality improvement motivation; premium placement and marketing asset generation may become paid add-ons
>
> **Tech Stack**: NextJS App Router (browse site), PostgreSQL, S3-compatible asset storage (OG images, certificates), Puppeteer (PDF/image generation), OpenAPI 3.1, email delivery via Resend/SES

---

## MVP Definition

- Showcase gallery page on browse.objectified.dev with "Schema of the Month" hero and category grid
- Eligibility engine: automatically scan for schemas with quality score ≥ 90 maintained for 30+ days with no critical violations
- Schema submission flow for tenants to nominate their own schemas
- Admin approval workflow: review, approve/reject, schedule future showcases
- Showcase detail page: company branding, quality score breakdown, canvas preview, "Use This Template" button
- Email notification to schema owners on eligibility and on feature/removal
- Opt-out mechanism for privacy-conscious organizations

---

## Epic 1 (#1570): Eligibility & Selection Engine

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                            | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|---------------------------------------------------|-----|----------|
| 1.1 (#1575) | Showcase Data Model                        | DB schema for showcase entries, nominations, schedules, and audit events          | `enhancement`, `mvp`, `schema-showcase`, `rest`  | Yes | No       |
| 1.2 (#1581) | Automated Eligibility Scanner              | Weekly cron job: scan all public schemas for quality score ≥ 90 sustained 30+ days| `enhancement`, `mvp`, `schema-showcase`          | Yes | No       |
| 1.3 (#1587) | Eligibility Notification to Schema Owners  | Email owner when their schema becomes eligible; include dashboard link to submit  | `enhancement`, `mvp`, `schema-showcase`          | Yes | Yes      |
| 1.4 (#1593) | Opt-Out Control                            | Tenant-level toggle: exclude from showcase consideration; persists across updates | `enhancement`, `mvp`, `schema-showcase`          | Yes | Yes      |
| 1.5 (#1598) | Quality Score Monitoring for Featured      | Alert if a currently featured schema drops below 85; trigger grace period         | `enhancement`, `mvp`, `schema-showcase`          | Yes | No       |
| 1.6 (#1605) | Auto-Removal on Score Drop                 | Remove schema from active showcase after grace period if score not recovered      | `enhancement`, `mvp`, `schema-showcase`          | Yes | No       |
| 1.7 (#1612) | Re-Showcase Opportunity                    | After score recovery, re-enter submission queue for next monthly selection        | `enhancement`, `schema-showcase`                 | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1575) — Showcase Data Model

Design the complete database schema for the Showcase feature. The `showcase_entry` table holds featured schemas with their active period, category, and associated metadata. The `showcase_nomination` table tracks the pipeline from submission/auto-detection through editorial review.

```
┌──────────────────────────────────────────────┐
│          showcase_nomination                 │
├──────────────────────────────────────────────┤
│ id             UUID PK                       │
│ schema_id      UUID FK                       │
│ tenant_id      UUID FK                       │
│ nominated_by   UUID FK (users) nullable      │
│ source         ENUM auto|self|community|staff│
│ status         ENUM pending|approved|rejected│
│ review_notes   TEXT                          │
│ reviewed_by    UUID FK (users) nullable      │
│ created_at     TIMESTAMPTZ                   │
│ reviewed_at    TIMESTAMPTZ                   │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│           showcase_entry                     │
├──────────────────────────────────────────────┤
│ id             UUID PK                       │
│ nomination_id  UUID FK                       │
│ schema_id      UUID FK                       │
│ tenant_id      UUID FK                       │
│ category       ENUM (see category list)      │
│ featured_month DATE  (YYYY-MM-01)            │
│ is_schema_of_month BOOLEAN                   │
│ quality_score  SMALLINT (at time of feature) │
│ page_views     INTEGER DEFAULT 0             │
│ template_uses  INTEGER DEFAULT 0             │
│ active         BOOLEAN DEFAULT true          │
│ removed_at     TIMESTAMPTZ                   │
│ removal_reason TEXT                          │
└──────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Migration creates all tables with proper foreign keys and indexes
- Only one `is_schema_of_month = true` entry per `featured_month` (enforced via partial unique index)
- `showcase_nomination.source = 'auto'` records created by scanner without user involvement
- All nomination status changes logged in `audit_log`

Part of Epic: Eligibility & Selection Engine

---

#### 1.2 (#1581) — Automated Eligibility Scanner

Implement a weekly cron job that queries the `schema_quality_score` history table for schemas that have maintained a score ≥ 90 for ≥ 30 consecutive days, have no active `critical` lint violations, are publicly accessible, and have not opted out of the showcase.

```sql
-- Eligibility query (simplified)
SELECT s.id, s.tenant_id, MIN(sqs.score) as min_score
FROM schemas s
JOIN schema_quality_score sqs ON sqs.schema_id = s.id
WHERE s.visibility = 'public'
  AND s.updated_at > NOW() - INTERVAL '90 days'
  AND s.tenant_id NOT IN (SELECT tenant_id FROM showcase_opt_out)
  AND sqs.calculated_at > NOW() - INTERVAL '30 days'
GROUP BY s.id, s.tenant_id
HAVING MIN(sqs.score) >= 90
  AND COUNT(*) >= 30  -- at least 30 daily snapshots
```

**Acceptance Criteria:**
- Scanner runs every Sunday at 00:00 UTC
- New eligible schemas not already in `showcase_nomination` table create a new `source='auto'` nomination
- Scanner completes in < 60 seconds for up to 100,000 schemas (validated in staging)
- Results logged to application log with count of new eligible schemas found

Part of Epic: Eligibility & Selection Engine

---

## Epic 2 (#1840): Showcase Gallery & Display

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                    | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------|-----|----------|
| 2.1 (#1841) | Showcase Gallery Page                      | Hero + category grid on browse.objectified.dev/showcase with filter and search    | `enhancement`, `mvp`, `schema-showcase`  | Yes | No       |
| 2.2 (#1842) | Schema of the Month Hero Section           | Full-width hero card for the monthly feature with company branding                | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 2.3 (#1843) | Schema Cards Grid                          | Card grid with logo, title, quality badge, category tags, view/clone counts       | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 2.4 (#1844) | Showcase Categories Display                | Category sections: Industry Leaders, Best Practices, Innovation, Community Choice  | `enhancement`, `mvp`, `schema-showcase`  | Yes | No       |
| 2.5 (#1845) | Industry Filter for Showcase              | Filter gallery by industry tag; integrated with tenancy industry taxonomy          | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 2.6 (#1846) | Search Showcase Archives                   | Search past showcase entries by company name, schema name, category, date         | `enhancement`, `schema-showcase`         | No  | Yes      |
| 2.7 (#1847) | Schema Detail Page                         | Full schema visualization, company spotlight, quality breakdown, metrics, CTA     | `enhancement`, `mvp`, `schema-showcase`  | Yes | No       |
| 2.8 (#1848) | Canvas Preview on Detail Page              | Read-only interactive canvas showing the featured schema's classes and relations  | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 2.9 (#1849) | "Use This Template" Button                 | One-click link to the template import wizard pre-loaded with this schema          | `enhancement`, `schema-showcase`         | No  | Yes      |
| 2.10 (#1850) | Showcase Archive (Hall of Fame)           | Browse past months; filter by date/industry/category; Hall of Fame for 3+ features| `enhancement`, `schema-showcase`        | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#1841) — Showcase Gallery Page

Build the public Showcase gallery at `browse.objectified.dev/showcase`. The page structure:
1. Hero section with the current "Schema of the Month"
2. Category sections (one row per category) with schema cards
3. Sidebar filter: industry, category, date range
4. Full-text search over schema name and company name

```
┌──────────────────────────────────────────────────────┐
│  🏆 Schema Showcase                 [Industry ▼]     │
├──────────────────────────────────────────────────────┤
│  SCHEMA OF THE MONTH — April 2026                    │
│  ┌──────────────────────────────────────────────┐    │
│  │ [Acme Corp Logo]  Healthcare API v3           │    │
│  │ Score: 96/100  ██████████ Healthcare         │    │
│  │ "Best-in-class patient data model..."  [View]│    │
│  └──────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────┤
│  Industry Leaders                          [See all] │
│  [Card] [Card] [Card] [Card]                         │
├──────────────────────────────────────────────────────┤
│  Best Practices                            [See all] │
│  [Card] [Card] [Card] [Card]                         │
└──────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Page pre-rendered at build time (ISR with 1-hour revalidation) for fast load
- Gallery renders in < 1 second on first load (Lighthouse performance ≥ 90)
- Industry filter updates URL query string for shareable filtered views
- Schema cards show: company logo, schema name, quality score badge, category tags, view count

Part of Epic: Showcase Gallery & Display

---

#### 2.7 (#1847) — Schema Detail Page

The detail page at `/showcase/{entry_id}` shows the full featured schema in depth:

```
Acme Corp — Healthcare API v3
┌──────────────────────────────────────────────────────┐
│  Company Spotlight                                   │
│  [Logo] Acme Corp | Healthcare | Featured April 2026 │
│  "Leading provider of patient data APIs..."          │
├──────────────────────────────────────────────────────┤
│  Quality Score: 96/100                               │
│  Design: 29/30  Docs: 20/20  API: 25/25  Sec: 14/15 │
│  Performance: 8/10                                   │
├──────────────────────────────────────────────────────┤
│  Why This Schema Stands Out                          │
│  [Editorial text from admin review]                  │
├──────────────────────────────────────────────────────┤
│  Key Metrics: 48 classes | 312 properties | 31 rels  │
├──────────────────────────────────────────────────────┤
│  [Interactive Canvas Preview]                        │
├──────────────────────────────────────────────────────┤
│  [Use This Template] [View Documentation]            │
└──────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Editorial "Why This Schema Stands Out" section authored by admin during approval
- Canvas preview loads the schema in read-only mode (no edit controls)
- Page view counted atomically in `showcase_entry.page_views`
- Open Graph meta tags generated for social sharing (company logo, schema name, score)

Part of Epic: Showcase Gallery & Display

---

## Epic 3 (#1851): Nomination & Selection Workflow

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                    | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------|-----|----------|
| 3.1 (#1852) | Self-Nomination Submission Flow            | Tenant submits their own schema via "Apply for Showcase" form in their dashboard  | `enhancement`, `mvp`, `schema-showcase`  | Yes | No       |
| 3.2 (#1853) | Community Nomination                       | Users can nominate any public schema via the gallery with a nomination reason     | `enhancement`, `schema-showcase`         | No  | Yes      |
| 3.3 (#1854) | Admin Review Interface                     | Admin queue: review nominations, see quality breakdown, approve/reject, schedule  | `enhancement`, `mvp`, `schema-showcase`  | Yes | No       |
| 3.4 (#1855) | Schedule Future Showcases                  | Calendar-based scheduling: assign approved nominations to future monthly slots    | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 3.5 (#1856) | Category & "Schema of Month" Assignment    | Assign category and flag one as "Schema of the Month" during admin review         | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 3.6 (#1857) | Nomination Approval/Rejection Email        | Email to schema owner on nomination outcome with personalized message             | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 3.7 (#1858) | Company Dashboard: Showcase Status         | Tenant dashboard widget showing showcase status, opt-in/out, analytics link       | `enhancement`, `schema-showcase`         | No  | Yes      |

---

## Epic 4 (#1859): Company Benefits & Recognition

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                    | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------|-----|----------|
| 4.1 (#1860) | "Featured Schema" Badge on Company Profile | Display showcase badge on the tenant's public profile page                        | `enhancement`, `mvp`, `schema-showcase`  | Yes | Yes      |
| 4.2 (#1861) | Showcase Certificate (PDF)                 | Auto-generate a branded PDF certificate downloadable from the tenant dashboard    | `enhancement`, `schema-showcase`         | No  | Yes      |
| 4.3 (#1862) | Marketing Badge Assets                     | Downloadable "Featured Schema" badge in SVG/PNG for company websites              | `enhancement`, `schema-showcase`         | No  | Yes      |
| 4.4 (#1863) | Showcase Analytics for Companies           | Per-tenant analytics: page views, template uses, traffic referrals from showcase  | `enhancement`, `schema-showcase`, `rest` | No  | Yes      |
| 4.5 (#1864) | Social Media Auto-Generated Cards          | OG images for LinkedIn, Twitter, Facebook sized and branded per featured schema   | `enhancement`, `schema-showcase`         | No  | Yes      |

---

## Epic 5 (#1865): Gamification & Engagement

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                    | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------|-----|----------|
| 5.1 (#1866) | Achievement Badges System                  | Award badges: Featured Schema, Schema of Month, Category Leader, Hall of Fame     | `enhancement`, `schema-showcase`         | No  | No       |
| 5.2 (#1867) | Quality Leaderboards                       | Top schemas by quality score; most featured companies; rising stars               | `enhancement`, `schema-showcase`         | No  | Yes      |
| 5.3 (#1868) | Hall of Fame                               | Dedicated section for companies featured 3+ times with permanent recognition      | `enhancement`, `schema-showcase`         | No  | Yes      |
| 5.4 (#1869) | Community Choice Voting                    | Monthly voting for community-favorite schemas among the month's featured entries  | `enhancement`, `schema-showcase`         | No  | No       |
| 5.5 (#1870) | Monthly Showcase Newsletter               | Email digest to subscribers announcing the month's featured schemas               | `enhancement`, `schema-showcase`         | No  | Yes      |
| 5.6 (#1871) | Showcase Blog Integration                  | Auto-draft a blog post template for the Schema of the Month feature               | `enhancement`, `schema-showcase`         | No  | Yes      |

### Detailed Issue Descriptions

#### 5.1 (#1866) — Achievement Badges System

Define a badge taxonomy and the conditions that trigger each badge award. Badges are stored in `tenant_badge` and displayed on tenant profiles.

| Badge | Trigger Condition |
|-------|-------------------|
| Featured Schema | First showcase appearance |
| Schema of the Month | Selected as the monthly hero feature |
| Category Leader | Featured in the same category 2+ times |
| Hall of Fame | Featured 3+ times total |
| Quality Pioneer | First tenant in their industry to be featured |

**Acceptance Criteria:**
- Badges awarded automatically by post-approval trigger (not manually by admin)
- Badge display order: most prestigious first (Hall of Fame → Schema of Month → Category Leader → Featured → Quality Pioneer)
- Badge award triggers a congratulatory email to the tenant admin
- Badges visible on public tenant profile and in the tenant's own dashboard

Part of Epic: Gamification & Engagement
