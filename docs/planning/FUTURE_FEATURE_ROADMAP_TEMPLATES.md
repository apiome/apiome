# Apiome: Schema & Property Templates - Feature Roadmap

> A layered template system operating at three levels: Group Templates (pre-defined class clusters), Schema Templates (drag-and-drop schema snippets for the canvas), and Property Templates (shared, reusable property definitions). Together they accelerate schema creation and enforce consistency across projects and teams.
>
> **Revenue Model**: Default system templates available to all tiers; custom template creation, cross-tenant sharing, and team-shared libraries gated at Pro; template monetization and premium template packs are Enterprise/Marketplace features
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, S3-compatible asset storage, TypeScript code generation, OpenAPI 3.1

---

## MVP Definition

- Pre-defined group templates for common class clusters: REST Resource, Auth, E-commerce, Audit
- Save custom class groups as reusable templates within a project
- Drag-and-drop schema templates onto the canvas for core domains (Addresses, Users, Payments, Orders, etc.)
- Custom template creation from selected canvas classes
- Property library: shared property definitions with inheritance and versioning
- Template categories and tags for discoverability
- Template ratings and reviews

---

## Epic 1: Group Templates

**Epic Issue:** #2456

### Summary Table

| #   | Title                                     | Issue  | Description                                                                        | Labels                                     | MVP | Parallel |
|-----|-------------------------------------------|--------|------------------------------------------------------------------------------------|--------------------------------------------|-----|----------|
| 1.1 | Pre-Defined Group Template Library        | #2457  | Built-in group templates: REST Resource, Auth, E-commerce, Audit, and more        | `enhancement`, `mvp`, `templates`         | Yes | No       |
| 1.2 | Save Custom Group Templates               | #2458  | Select classes on canvas, save selection as a named reusable group template        | `enhancement`, `mvp`, `templates`, `rest` | Yes | No       |
| 1.3 | Share Group Templates Across Projects     | #2459  | Promote a custom group template to tenant-wide or project-shared scope            | `enhancement`, `templates`                | No  | Yes      |
| 1.4 | Group Template Preview                    | #2460  | Preview all classes and relationships in a group template before applying          | `enhancement`, `templates`                | No  | Yes      |
| 1.5 | Apply Group Template to Canvas            | #2461  | Insert all classes from a group template onto the canvas with layout auto-arrange  | `enhancement`, `mvp`, `templates`         | Yes | No       |

### Detailed Issue Descriptions

#### 1.1 — Pre-Defined Group Template Library (Issue #2457)

Ship a curated set of built-in group templates that cover the most common schema patterns. Each group includes fully defined class definitions, property sets, and inter-class relationships ready to drop onto the canvas.

**Built-In Groups:**

| Group Name         | Classes Included                                                |
|--------------------|----------------------------------------------------------------|
| REST Resource      | Resource, ResourceList, CreateRequest, UpdateRequest, ErrorResponse |
| Authentication     | User, Token, Session, Role, Permission                          |
| E-commerce         | Product, Cart, CartItem, Order, OrderItem, Payment              |
| Audit              | AuditEvent, AuditLog, AuditActor                               |
| Common Contact     | Person, Address, PhoneNumber, Email                             |
| Pagination         | PageRequest, PageResponse, CursorRequest, CursorResponse        |
| File & Media       | File, MediaAsset, UploadRequest, StorageLocation                |

**Acceptance Criteria:**
- All built-in groups seeded in migration; not editable by tenants (system-managed)
- Each group displays a description, class count, and relationship count in the picker UI
- Applying a group does not overwrite existing classes with the same name (conflict detection)
- `#159` addressed by this issue

**Tech Stack:** PostgreSQL seed migration, canvas insertion API

Part of Epic: Group Templates (#2456)

---

#### 1.2 — Save Custom Group Templates (Issue #2458)

Allow users to select a set of classes on the canvas and save them as a named group template. The template captures the class definitions (structure only, not data), their relationships, and the relative canvas layout positions for restore-on-apply.

**OpenAPI Endpoints:**
```
POST /api/v1/group-templates
  Body: {
    name: string,
    description?: string,
    class_ids: UUID[],   -- selected classes to include
    scope: project | tenant
  }
  → 201: GroupTemplate { id, name, class_count }

GET  /api/v1/group-templates              → 200: GroupTemplateList
GET  /api/v1/group-templates/{id}         → 200: GroupTemplate
DELETE /api/v1/group-templates/{id}       → 204
```

**Acceptance Criteria:**
- Template captures class definitions as a snapshot (not a live reference)
- Relative canvas positions preserved in `layout_json` for restore-on-apply
- Template visible to the creating user immediately; shared templates visible to all project members
- `#160` addressed by this issue

Part of Epic: Group Templates (#2456)

---

## Epic 2: Schema Templates

**Epic Issue:** #2462

### Summary Table

| #   | Title                                     | Issue  | Description                                                                        | Labels                                      | MVP | Parallel |
|-----|-------------------------------------------|--------|------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 2.1 | Schema Template Data Model               | #2463  | DB schema for schema templates with categories, tags, versioning, and metadata      | `enhancement`, `mvp`, `templates`, `rest`  | Yes | No       |
| 2.2 | Core Domain Templates (Phase 1)          | #2464  | Addresses, Common, Content, Integrations, Notifications, Orders, Payments, Products | `enhancement`, `mvp`, `templates`          | Yes | No       |
| 2.3 | Core Domain Templates (Phase 2)          | #2465  | Security/Auth, Users, Analytics, Communication, Compliance, Marketplace, Scheduling, Support | `enhancement`, `templates`        | No  | No       |
| 2.4 | Template Category Browser                | #2466  | Browse templates by category in a sidebar or modal; search by keyword              | `enhancement`, `mvp`, `templates`          | Yes | No       |
| 2.5 | Template Tags System                     | #2467  | Tag templates for discoverability; filter by tag in the browser                    | `enhancement`, `templates`                 | No  | Yes      |
| 2.6 | Drag-and-Drop from Template Browser      | #2468  | Drag a template from the browser sidebar and drop it onto the canvas               | `enhancement`, `mvp`, `templates`          | Yes | No       |
| 2.7 | Custom Template Creation from Canvas     | #2469  | Select classes → "Save as Template" → name, description, category, tags           | `enhancement`, `mvp`, `templates`, `rest`  | Yes | No       |
| 2.8 | Template Variables with Auto-Fill        | #2470  | Mark placeholder properties in a template; prompt user to fill values on apply     | `enhancement`, `templates`                 | No  | Yes      |
| 2.9 | Team-Shared Template Library             | #2471  | Publish custom templates to a tenant-wide shared library visible to all users      | `enhancement`, `templates`                 | No  | Yes      |
| 2.10 | Template Ratings & Reviews              | #2472  | 1–5 star rating plus free-text review after using a template                       | `enhancement`, `templates`, `rest`         | No  | Yes      |
| 2.11 | Community Marketplace Integration        | #2473  | Push/pull templates to/from the Template Marketplace (cross-reference)             | `enhancement`, `templates`                 | No  | No       |

### Detailed Issue Descriptions

#### 2.1 — Schema Template Data Model (Issue #2463)

Design the database model for schema templates. Each template is a versioned artifact with content stored as JSON (class definitions, property sets, relationships). Templates have a category, tags, scope, and rating aggregate.

```
┌──────────────────────────────────────────┐
│           schema_template                │
├──────────────────────────────────────────┤
│ id           UUID PK                     │
│ tenant_id    UUID FK  (null = system)    │
│ name         VARCHAR                     │
│ description  TEXT                        │
│ category     VARCHAR                     │
│ tags         TEXT[]                      │
│ scope        ENUM (system|tenant|project)│
│ rating_avg   NUMERIC (0-5)               │
│ rating_count INTEGER                     │
│ created_by   UUID FK (users)             │
│ created_at   TIMESTAMPTZ                 │
│ updated_at   TIMESTAMPTZ                 │
└────────────────────┬─────────────────────┘
                     │ 1:N
┌────────────────────▼─────────────────────┐
│        schema_template_version           │
├──────────────────────────────────────────┤
│ id           UUID PK                     │
│ template_id  UUID FK                     │
│ version      VARCHAR   (semver)          │
│ content_json JSONB     (class definitions)│
│ changelog    TEXT                        │
│ created_at   TIMESTAMPTZ                 │
└──────────────────────────────────────────┘
```

**Acceptance Criteria:**
- `tenant_id = null` for system-provided templates (visible to all tenants)
- JSONB content validated against a JSON Schema for template structure
- Full-text search index on `(name, description, tags)` for the template browser
- Seed migration populates all Phase 1 system templates
- `#602`, `#603`, `#604` addressed by this issue

Part of Epic: Schema Templates (#2462)

---

#### 2.2 — Core Domain Templates (Phase 1) (Issue #2464)

Implement the first batch of system-provided schema templates covering the most frequently needed domains. Each template must be production-quality: all properties typed, described, and with example values. Quality score ≥ 80/100 required before shipping.

**Phase 1 Templates:**

| Category      | Template Name         | Key Classes                                              | Ticket |
|---------------|-----------------------|----------------------------------------------------------|--------|
| Addresses     | Global Address        | Address, PostalCode, Country, AddressType                | #773   |
| Common        | Common Primitives     | Identifier, Timestamp, AuditFields, SortOrder            | #774   |
| Content       | Rich Content          | Article, ContentBlock, MediaEmbed, ContentTag            | #775   |
| Integrations  | Webhook Model         | WebhookEvent, WebhookDelivery, WebhookEndpoint           | #776   |
| Notifications | Notification System   | Notification, NotificationPreference, NotificationChannel| #777   |
| Orders        | Order Lifecycle       | Order, OrderItem, OrderStatus, Fulfillment               | #778   |
| Payments      | Payment Processing    | Payment, PaymentMethod, Transaction, Refund              | #779   |
| Products      | Product Catalog       | Product, ProductVariant, Category, Inventory             | #780   |

**Acceptance Criteria:**
- Each template passes schema linting quality check (≥ 80/100)
- All class properties have descriptions of ≥ 10 characters and at least one example
- Templates visible in the canvas sidebar under their respective categories
- Can be applied to a canvas without conflict if no naming collisions exist

Part of Epic: Schema Templates (#2462)

---

#### 2.3 — Core Domain Templates (Phase 2) (Issue #2465)

Implement the second batch of system templates for security, user management, analytics, communication, compliance, marketplace, scheduling, and support domains.

**Phase 2 Templates:**

| Category      | Template Name            | Key Classes                                             | Ticket |
|---------------|--------------------------|---------------------------------------------------------|--------|
| Security      | Auth & Permissions       | User, Role, Permission, ApiKey, Session                 | #781   |
| Users & Auth  | User Management          | UserProfile, UserPreference, UserGroup, Invitation      | #782   |
| Analytics     | Event Tracking           | AnalyticsEvent, Funnel, Metric, Dimension               | #783   |
| Communication | Messaging System         | Message, Conversation, Participant, MessageStatus       | #784   |
| Compliance    | Audit & Compliance       | AuditEvent, ConsentRecord, DataRetentionPolicy          | #785   |
| Marketplace   | Multi-Vendor Marketplace | Vendor, Listing, Review, Commission                     | #786   |
| Scheduling    | Calendar & Booking       | Event, TimeSlot, Booking, Recurrence                    | #787   |
| Support       | Help Desk                | Ticket, TicketComment, SupportAgent, KnowledgeArticle   | #788   |

Part of Epic: Schema Templates (#2462)

---

## Epic 3: Property Templates (Property Library)

**Epic Issue:** #2474

### Summary Table

| #   | Title                                     | Issue  | Description                                                                        | Labels                                     | MVP | Parallel |
|-----|-------------------------------------------|--------|------------------------------------------------------------------------------------|--------------------------------------------|-----|----------|
| 3.1 | Property Library Data Model              | #2475  | Shared property definitions per tenant with type, constraints, description, examples| `enhancement`, `mvp`, `templates`, `rest` | Yes | No       |
| 3.2 | Reusable Property Components             | #2476  | Reference a library property from any class; changes to library propagate optionally| `enhancement`, `templates`               | No  | No       |
| 3.3 | Property Inheritance                     | #2477  | Extend a library property in a class to add local constraints without forking      | `enhancement`, `templates`               | No  | No       |
| 3.4 | Property Versioning                      | #2478  | Version library properties; track which class uses which version                   | `enhancement`, `templates`               | No  | Yes      |
| 3.5 | Property Search & Filter                 | #2479  | Search library properties by name, type, tag; filter by usage count                | `enhancement`, `mvp`, `templates`         | Yes | Yes      |
| 3.6 | Property Usage Tracking                  | #2480  | Count and list which classes reference each library property                       | `enhancement`, `templates`               | No  | Yes      |
| 3.7 | Deprecate Library Properties             | #2481  | Mark a property deprecated with migration guidance; warn in consuming classes      | `enhancement`, `templates`               | No  | Yes      |
| 3.8 | Property Marketplace (Community-Shared)  | #2482  | Share property definitions publicly via Template Marketplace                       | `enhancement`, `templates`               | No  | No       |

### Detailed Issue Descriptions

#### 3.1 — Property Library Data Model (Issue #2475)

Create a `property_library` table holding reusable property definitions at the tenant scope. Each entry defines a canonical property (type, format, constraints, description, examples) that can be referenced by name from any class in the tenant.

```
┌──────────────────────────────────────────────┐
│           property_library                   │
├──────────────────────────────────────────────┤
│ id           UUID PK                         │
│ tenant_id    UUID FK (null = system)         │
│ name         VARCHAR  (unique per tenant)    │
│ type         VARCHAR  (string|integer|...)   │
│ format       VARCHAR  (email|uri|uuid|...)   │
│ description  TEXT                            │
│ constraints  JSONB    (min, max, pattern...) │
│ examples     JSONB[]                         │
│ tags         TEXT[]                          │
│ deprecated   BOOLEAN  DEFAULT false          │
│ created_at   TIMESTAMPTZ                     │
│ updated_at   TIMESTAMPTZ                     │
└──────────────────────────────────────────────┘
```

**OpenAPI Endpoints:**
```
GET  /api/v1/property-library             → 200: PropertyLibraryList
POST /api/v1/property-library             → 201: LibraryProperty
GET  /api/v1/property-library/{id}        → 200: LibraryProperty
PUT  /api/v1/property-library/{id}        → 200: LibraryProperty
DELETE /api/v1/property-library/{id}      → 204
GET  /api/v1/property-library/{id}/usages → 200: ClassUsageList
```

**Acceptance Criteria:**
- `name` unique per `tenant_id` scope (system properties: `tenant_id = null`)
- Full-text search index on `(name, description, tags)`
- Deleting a library property blocked if any class currently references it
- System-provided properties (e.g., `id`, `created_at`, `updated_at`) seeded in migration

Part of Epic: Property Templates (Property Library) (#2474)

---

#### 3.5 — Property Search & Filter (Issue #2479)

Provide a searchable property library panel within the schema editor. Users can type a property name or keyword and see matching library properties with their type, description, and usage count. Double-click or drag to add the property to the current class.

```
Property Library                      [+ New Property]
Search: [email_address        ]
────────────────────────────────────────
email_address   string/email  Used: 12 classes
  "Standard RFC 5322 compliant email..."
  [Add to class]

email_verified  boolean       Used: 7 classes
  "Whether the email address has been..."
  [Add to class]
────────────────────────────────────────
Filter: [All Types ▼] [All Tags ▼]
```

**Acceptance Criteria:**
- Search responds in < 200ms using PostgreSQL full-text index
- Usage count displayed alongside each property
- Deprecated properties shown with strikethrough and deprecation notice
- Adding a library property to a class creates a reference (not a copy), enabling propagation

Part of Epic: Property Templates (Property Library) (#2474)
