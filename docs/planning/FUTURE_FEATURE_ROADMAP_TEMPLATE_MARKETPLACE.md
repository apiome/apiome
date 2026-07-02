# Apiome: Template Marketplace - Feature Roadmap

> A community-driven marketplace where users browse, publish, fork, and import property templates and schema patterns across industry domains. Templates lower the time-to-first-schema for new projects and enable reuse of battle-tested data models across the Apiome ecosystem.
>
> **Revenue Model**: Free templates for community; premium curated template packs (Enterprise tier); revenue share with template publishers; template import wizard gated at Pro
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, S3-compatible asset storage, OpenAPI 3.1, TypeScript code generation for previews

---

## MVP Definition

- Template catalog browsable by category (industry, auth, common data models, API patterns)
- Template detail page with structural preview and metadata (author, version, license, rating)
- One-click import wizard: select destination project, choose classes, resolve naming conflicts, commit
- Template search and filter by industry, complexity, rating, and popularity
- Template submission flow for community contributors
- REST API for all template operations (OpenAPI 3.1 documented)

---

## Epic 1 (#2029): Template Catalog & Discovery

### Summary Table

| #   | Title                                   | Description                                                                       | Labels                                              | MVP | Parallel |
|-----|-----------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 1.1 (#2030) | Template Data Model & Storage           | Database schema for templates, versions, ratings, downloads, and categories       | `enhancement`, `mvp`, `template-marketplace`, `rest` | Yes | No       |
| 1.2 (#2031) | Industry Template Categories            | Pre-built templates for E-commerce, Healthcare, Finance, SaaS, Education, etc.   | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 1.3 (#2032) | Domain-Specific Template Categories     | Templates for IoT, Social media, Gaming, Travel, Media & entertainment           | `enhancement`, `template-marketplace`               | No  | Yes      |
| 1.4 (#2033) | Authentication & Authorization Templates | OAuth 2.0, JWT, Roles/Permissions, MFA, API key management templates            | `enhancement`, `template-marketplace`               | No  | Yes      |
| 1.5 (#2034) | Common Data Model Templates             | Address, Person, Organization, Payment methods, Communication, Audit log         | `enhancement`, `template-marketplace`               | No  | Yes      |
| 1.6 (#2035) | API Pattern Templates                   | CRUD, Pagination (cursor, offset), Search/filter, Bulk ops, Webhook payload      | `enhancement`, `template-marketplace`               | No  | Yes      |
| 1.7 (#2036) | Template Search & Filter Engine         | Full-text search + filter by industry, complexity, rating, downloads, updated    | `enhancement`, `mvp`, `template-marketplace`, `rest` | Yes | No       |
| 1.8 (#2037) | Template Detail Page                    | Visual structure preview, metadata, screenshots, live demo link, code preview    | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 1.9 (#2038) | Featured & Trending Templates           | Admin-curated featured templates; trending based on download velocity            | `enhancement`, `template-marketplace`               | No  | Yes      |
| 1.10 (#2039) | Related Template Suggestions            | Recommend related templates on the detail page based on category and tags        | `enhancement`, `template-marketplace`               | No  | Yes      |
| 1.11 (#2040) | Canvas Structure Preview                | Render template classes and relationships on a read-only canvas preview          | `enhancement`, `mvp`, `template-marketplace`        | Yes | Yes      |
| 1.12 (#2041) | Generated Code Preview                  | Show TypeScript, Python, and Go code generated from the template                 | `enhancement`, `template-marketplace`               | No  | Yes      |
| 1.13 (#2042) | Sample OpenAPI Spec Preview             | Render the template as a partial OpenAPI 3.1 YAML preview                        | `enhancement`, `template-marketplace`               | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#2030) — Template Data Model & Storage

Design the relational schema for the template marketplace. Each template has a parent `template` record (identity, authorship, stats) and one or more `template_version` records containing the actual class definitions as JSON. Ratings and download counts are denormalized onto the parent for query performance.

```
┌──────────────────────┐     ┌────────────────────────┐
│       template       │────▶│    template_version    │
├──────────────────────┤     ├────────────────────────┤
│ id          UUID PK  │     │ id          UUID PK    │
│ name        VARCHAR  │     │ template_id UUID FK    │
│ description TEXT     │     │ version     VARCHAR    │
│ author_id   UUID FK  │     │ changelog   TEXT       │
│ category    ENUM     │     │ content_json JSONB     │
│ tags        TEXT[]   │     │ openapi_ver VARCHAR    │
│ license     VARCHAR  │     │ created_at  TIMESTAMPTZ│
│ downloads   INTEGER  │     └────────────────────────┘
│ rating_avg  NUMERIC  │
│ rating_count INTEGER │     ┌────────────────────────┐
│ is_featured BOOLEAN  │     │   template_rating      │
│ created_at  TIMESTAMPTZ    ├────────────────────────┤
│ updated_at  TIMESTAMPTZ    │ template_id UUID FK    │
└──────────────────────┘     │ user_id     UUID FK    │
                             │ stars       SMALLINT   │
                             │ created_at  TIMESTAMPTZ│
                             └────────────────────────┘
```

**Acceptance Criteria:**
- Migration creates all tables with foreign keys, indexes, and constraints
- `template.category` uses a PostgreSQL enum covering all supported industry categories
- `content_json` validated against a JSON Schema for template class structure
- Composite index on `(category, rating_avg DESC)` for catalog browsing queries
- Seed script populates at least 20 sample templates across 5 categories

**Tech Stack:** PostgreSQL, JSONB, OpenAPI 3.1 component schemas for all entities

Part of Epic: Template Catalog & Discovery

---

#### 1.2 (#2031) — Industry Template Categories

Create the initial batch of curated industry templates. Each template must include complete class definitions with properties, pre-configured relationships, example values, descriptions, common validation rules, and best-practice documentation.

**Initial Templates:**
- **E-commerce**: Product, Cart, Order, Payment, Shipping, Discount
- **Healthcare**: Patient, Appointment, Medication, Prescription, InsuranceClaim
- **Finance**: Account, Transaction, Investment, Loan, Statement
- **SaaS**: Tenant, User, Subscription, UsageRecord, Invoice
- **Education**: Course, Student, Assignment, Grade, Enrollment
- **Real Estate**: Property, Listing, Agent, Offer, Transaction
- **Logistics**: Shipment, Route, Warehouse, DeliveryEvent, Carrier

**Acceptance Criteria:**
- Each template passes the schema linting quality score of ≥ 80/100
- All class properties have descriptions of ≥ 10 characters
- Each template includes at least one example value per class
- Templates are seeded into the `template` and `template_version` tables via migration

**Tech Stack:** PostgreSQL seed migration, JSON Schema definitions

Part of Epic: Template Catalog & Discovery

---

#### 1.7 (#2036) — Template Search & Filter Engine

Implement full-text search over template `name`, `description`, and `tags` using PostgreSQL `tsvector`. Combine with structured filters: `category`, `complexity` (simple/moderate/complex derived from class count), `min_rating`, `min_downloads`, `updated_after`. Sort options: relevance, rating, downloads, recently updated.

**OpenAPI Endpoints:**
```
GET /api/v1/marketplace/templates
  ?q=<text>
  &category=ecommerce|healthcare|finance|saas|...
  &complexity=simple|moderate|complex
  &min_rating=1-5
  &sort=relevance|rating|downloads|updated
  &cursor=<opaque>
  &limit=24
  → 200: TemplateList (cursor-paginated)
```

**Acceptance Criteria:**
- Full-text search returns relevant results within 200ms for the full template catalog
- `tsvector` index maintained automatically on insert/update via trigger
- Cursor-based pagination returns stable pages even as new templates are added
- Empty search returns templates sorted by `downloads DESC` (most popular first)

**Depends on:** 1.1 (template data model)

Part of Epic: Template Catalog & Discovery

---

## Epic 2 (#2043): Template Import & Customization

### Summary Table

| #   | Title                                  | Description                                                                       | Labels                                              | MVP | Parallel |
|-----|----------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 2.1 (#2044) | Import Wizard — Step 1: Project Select | Destination project/version picker as first step of the import wizard            | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 2.2 (#2045) | Import Wizard — Step 2: Class Selection | Checkbox-based class selector to import all or a subset of template classes      | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 2.3 (#2046) | Import Wizard — Step 3: Canvas Preview  | Read-only canvas preview showing selected classes and relationships before import | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 2.4 (#2047) | Import Wizard — Step 4: Conflict Resolution | Detect naming conflicts with existing schema and offer resolution options    | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 2.5 (#2048) | Import Wizard — Step 5: Namespace Customize | Rename classes and apply namespace prefixes before committing import        | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 2.6 (#2049) | One-Click Import Commit                | Final import step: atomically merge selected classes into the target schema       | `enhancement`, `mvp`, `template-marketplace`, `rest` | Yes | No      |
| 2.7 (#2050) | Bulk Import (Multiple Templates)       | Select and import from multiple templates in a single wizard session              | `enhancement`, `template-marketplace`               | No  | No       |
| 2.8 (#2051) | Template Dependency Auto-Import        | Detect when a template depends on another template and offer to import it too     | `enhancement`, `template-marketplace`               | No  | Yes      |
| 2.9 (#2052) | Pre-Import Customization               | Edit class names, add/remove properties, change types before committing import   | `enhancement`, `template-marketplace`               | No  | No       |
| 2.10 (#2053) | Save Customized Template               | Save a customized import as a new private template for reuse                     | `enhancement`, `template-marketplace`               | No  | Yes      |
| 2.11 (#2054) | Fork Template                          | Fork a public template into the user's account for independent modification      | `enhancement`, `template-marketplace`, `rest`       | No  | Yes      |
| 2.12 (#2055) | Smart Merge: Conflict Detection        | Detect property-level conflicts between template and existing schema             | `enhancement`, `mvp`, `template-marketplace`        | Yes | No       |
| 2.13 (#2056) | Smart Merge: Conflict Resolution UI    | Side-by-side conflict resolution: keep existing, use template, rename and keep both | `enhancement`, `mvp`, `template-marketplace`     | Yes | No       |
| 2.14 (#2057) | Intelligent Property Merging           | Auto-merge non-conflicting properties; prompt only for true conflicts            | `enhancement`, `template-marketplace`               | No  | Yes      |
| 2.15 (#2058) | Template Publisher Submission Flow     | Form and review queue for community members to submit new templates              | `enhancement`, `template-marketplace`, `rest`       | No  | No       |
| 2.16 (#2059) | Template Rating & Review System        | 1–5 star rating and text review after importing a template                       | `enhancement`, `template-marketplace`, `rest`       | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#2044) — Import Wizard — Step 1: Project Select

The import wizard is triggered by the "Use Template" button on any template detail page. Step 1 presents a project/version picker pre-filtered to projects the current user has write access to. If the user only has one writable project, auto-advance to Step 2.

```
Import: E-commerce Template  [Step 1 of 5]
┌─────────────────────────────────────────────────────┐
│  Select destination project                         │
│                                                     │
│  Project:  [My E-commerce API        ▼]             │
│  Version:  [v2 (draft)               ▼]             │
│                                                     │
│  ○ Create new version from current                  │
│  ● Import into existing draft                       │
│                                                     │
│                              [Cancel] [Next →]      │
└─────────────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Project list filtered to only projects where user has `write` permission
- Version list shows only `draft` versions (cannot import into published versions)
- "Create new version" option creates a draft branch before import
- Wizard state persisted in session so browser refresh does not lose progress

**Depends on:** 1.1 (template version must exist to import)

Part of Epic: Template Import & Customization

---

#### 2.6 (#2049) — One-Click Import Commit

After all wizard steps are complete, the final import step atomically merges the selected and configured classes into the target schema version. The operation is wrapped in a database transaction; if any step fails, the schema is left unchanged. On success, the user is redirected to the schema canvas with imported classes highlighted.

**OpenAPI Endpoints:**
```
POST /api/v1/marketplace/templates/{template_id}/import
  Body: {
    target_project_id,
    target_version_id,
    selected_class_ids: [],
    renames: { original_class_name: new_name },
    conflict_resolutions: { class_name: keep_existing|use_template|rename }
  }
  → 200: ImportResult { imported_class_ids[], skipped_class_ids[], warnings[] }
  → 409: ConflictError (unresolved conflicts remain)
```

**Acceptance Criteria:**
- Import runs in a single database transaction (all-or-nothing)
- Download counter on the template incremented atomically after successful import
- Imported classes are flagged with `imported_from_template_id` for provenance tracking
- User redirected to canvas with imported classes selected/highlighted
- Idempotent: re-importing the same template with the same configuration does not duplicate classes

**Depends on:** 2.1–2.5 (wizard steps must collect all import parameters)

Part of Epic: Template Import & Customization

---

#### 2.12 (#2055) — Smart Merge: Conflict Detection

Before presenting Step 4 of the wizard, run a conflict analysis that compares the template's class names and property names against the target schema version. Classify each overlap as: `class_name_conflict` (same class name exists), `property_type_conflict` (same property name, different type), or `compatible_merge` (same property name and type — safe to deduplicate).

```
Conflict Report:
  ✗ Class "User" already exists in target schema
     → Options: Rename imported class | Merge properties | Skip
  ✗ Property "email" on "Contact": template uses String, existing uses Email type
     → Options: Keep existing type | Use template type
  ✓ Property "id" on "Order": same type UUID — will merge automatically
```

**Acceptance Criteria:**
- Conflict detection runs in < 500ms for schemas with ≤ 200 classes
- `compatible_merge` conflicts resolved automatically without user intervention
- All `class_name_conflict` and `property_type_conflict` items require explicit resolution before import can proceed
- Conflict report shown on Step 4 of the wizard with clear explanations

**Depends on:** 2.2 (class selection must be known to scope conflict check)

Part of Epic: Template Import & Customization
