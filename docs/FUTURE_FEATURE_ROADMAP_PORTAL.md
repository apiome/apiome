# Objectified: Developer Portal & SDK Platform - Feature Roadmap

> Full-featured developer portal and SDK platform enabling API discovery, interactive documentation, multi-language SDK generation with automated publishing, local mock servers for integration testing, and IDE extensions for VS Code and JetBrains—providing a complete self-service experience for API consumers.
>
> **Revenue Model**: Team tier for portal, Enterprise for custom branding and SDK distribution
>
> **Tech Stack**: NextJS App Router (ISR for portal pages), Radix UI, OpenAPI Generator, Docker (mock server), Language Server Protocol, REST/OpenAPI 3.1, PostgreSQL, Redis, Stripe.js (portal billing)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Searchable API discovery catalog with category filtering, health status indicators, and deprecation warnings
- Auto-generated API reference documentation from OpenAPI specs with interactive schema explorer
- Developer self-service registration with API key provisioning and sandbox access
- Multi-language SDK generation for TypeScript, Python, Java, and Go with typed models and auto-auth
- Mock server generation from OpenAPI specs with request validation and hot-reload
- Web-based API playground with request builder, auth management, and response inspection
- VS Code extension with OpenAPI syntax highlighting, schema validation, and IntelliSense

---

## Epic 1: Portal Platform

### Summary Table

| #   | Title                                      | Description                                                                  | Labels                                           | Parallel |
|-----|--------------------------------------------|------------------------------------------------------------------------------|--------------------------------------------------|----------|
| 1.1 (#1341) | API Discovery Catalog                      | Searchable, filterable catalog of all published APIs with health and metrics  | `enhancement`, `mvp`, `portal`, `rest`, `ai-generated`           | Yes      |
| 1.2 (#1354) | Auto-Generated API Documentation Hub       | Interactive reference docs generated from OpenAPI specs with code samples    | `enhancement`, `mvp`, `portal`, `rest`, `ai-generated`           | Yes      |
| 1.3 (#1361) | Developer Self-Service Registration        | Registration, SSO, org management, API key provisioning, sandbox access      | `enhancement`, `mvp`, `portal`, `rest`, `ai-generated`           | Yes      |
| 1.4 (#1369) | Developer Usage Analytics                  | Per-developer and per-org API usage dashboards with engagement metrics       | `enhancement`, `portal`, `rest`, `ai-generated`                  | No       |

### Detailed Issue Descriptions

---

#### 1.1 (#1341) — API Discovery Catalog

The API discovery catalog is the front door of the developer portal. It presents every published API as a browsable, searchable directory that helps developers find the right API for their use case without reading through sprawling documentation trees.

The catalog page lives at `app/(portal)/[tenantSlug]/catalog/page.tsx` and renders API entries as cards in a responsive grid. Each card shows the API name, version, a short description, health status badge (green/amber/red), popularity score (based on total consumers and request volume), and tags. The page supports full-text search via a Radix UI `TextField` with debounced queries against a PostgreSQL `tsvector` index, and filtering by category, tag, status, and deprecation state via Radix UI `Select` and `ToggleGroup` components.

A "Featured APIs" section at the top highlights tenant-curated APIs. A "Recently Updated" feed shows APIs with recent schema changes or new versions, sorted by update timestamp. A "Deprecation Warnings" banner surfaces APIs approaching end-of-life with migration links.

```
┌──────────────────────────────────────────────────────────────┐
│  [Search: ________________]  [Category ▾]  [Status ▾]       │
├──────────────────────────────────────────────────────────────┤
│  ★ Featured APIs                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ Orders API  │  │ Users API   │  │ Payments    │          │
│  │ v3.2  ● Up  │  │ v2.1  ● Up  │  │ v4.0  ● Up  │          │
│  │ 1.2k users  │  │ 890 users   │  │ 2.1k users  │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
│                                                              │
│  Recently Updated                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ Inventory   │  │ Shipping    │  │ Webhooks    │          │
│  │ v1.4  ● Up  │  │ v2.0  ⚠ Dep │  │ v1.0  ● Up  │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└──────────────────────────────────────────────────────────────┘
```

The backend REST API exposes `GET /api/v1/portal/catalog` with query parameters for `search`, `category`, `tags`, `status`, `deprecated`, `sort` (popularity, recent, name), and standard pagination. Health status is derived from the API gateway's upstream health checks when available, or manually set via `PUT /api/v1/portal/catalog/{apiId}/status`. ISR revalidates the catalog page every 60 seconds.

**Acceptance Criteria**

- Catalog page renders all published APIs as cards with name, version, health badge, and popularity score
- Full-text search returns results within 200ms using PostgreSQL `tsvector` indexing
- Category, tag, and status filters narrow results without page reload
- Featured APIs section displays tenant-curated entries at the top
- Recently Updated feed shows APIs with changes in the last 30 days sorted by recency
- Deprecation warnings banner appears for APIs with a scheduled end-of-life date
- ISR revalidates the catalog every 60 seconds without a full rebuild
- REST API returns paginated results conforming to OpenAPI 3.1 spec

**Part of Epic: Portal Platform**

---

#### 1.2 (#1354) — Auto-Generated API Documentation Hub

The documentation hub generates comprehensive, interactive API reference pages directly from OpenAPI 3.1 specifications and Objectified schema captures. Developers never write documentation manually — it flows from the schema definitions.

Each API version gets a dedicated documentation page at `app/(portal)/[tenantSlug]/docs/[apiSlug]/page.tsx`. The page renders: endpoint listing grouped by tag, HTTP method and path with color-coded method badges, request/response schema trees rendered as expandable/collapsible nodes (Radix UI `Accordion`), field-level descriptions, types, constraints (min/max/pattern/required), and example values. A right-side panel shows code samples for making requests in TypeScript, Python, Java, Go, cURL, Ruby, PHP, C#, Kotlin, and Swift — language selection persists in local storage.

The documentation includes a getting started guide auto-generated from the API's authentication scheme, base URL, and first endpoint. Authentication tutorials render step-by-step instructions for API key, OAuth2, and JWT flows based on the OpenAPI `securitySchemes`. Rate limit information is pulled from the gateway's usage plan metadata. A changelog is auto-generated from schema version diffs, showing added/removed/modified fields per version.

Migration guides are generated when breaking changes are detected between major versions. The guide lists every breaking change with the old and new shape, a code-level migration example, and a deprecation timeline. The documentation search (Radix UI `CommandDialog` pattern) indexes all endpoint paths, field names, descriptions, and enum values for instant in-page navigation.

**Acceptance Criteria**

- Documentation pages render all endpoints grouped by tag with method badges and path
- Schema trees are expandable/collapsible with field type, description, constraints, and examples
- Code samples are available in 10+ languages with persistent language selection
- Authentication tutorials render automatically from OpenAPI `securitySchemes`
- Changelog is auto-generated from schema version diffs with field-level change detail
- Migration guides appear for breaking changes between major versions
- In-page search indexes endpoint paths, field names, and descriptions

**Part of Epic: Portal Platform**

---

#### 1.3 (#1361) — Developer Self-Service Registration

Developers should be able to discover, register, and start consuming APIs within minutes. This issue builds the complete self-service onboarding flow from registration through first API call.

The registration page at `app/(portal)/[tenantSlug]/register/page.tsx` supports email+password signup and SSO via SAML 2.0 and OpenID Connect. On registration, a developer account is created and linked to an organization (new or existing via invitation). The org management page at `app/(portal)/[tenantSlug]/org/page.tsx` lets org admins invite team members (Radix UI `Dialog` with email input), manage roles (admin, developer, viewer via Radix UI `Select`), and view the member list (Radix UI `Table`).

After registration, the onboarding wizard (`app/(portal)/[tenantSlug]/onboarding/page.tsx`) walks the developer through: (1) creating their first API key, (2) selecting a sandbox environment, (3) making a test request from the embedded playground. API keys are self-provisioned from the keys page — full values shown once at creation, stored as bcrypt hashes, displayed masked thereafter. Sandbox environments are isolated gateway instances with relaxed rate limits and synthetic upstream data.

```
Registration Flow
─────────────────
  ┌──────────┐     ┌───────────┐     ┌────────────┐     ┌──────────┐
  │  Sign Up │────▶│  Verify   │────▶│  Onboard   │────▶│  First   │
  │  Email/  │     │  Email    │     │  Wizard    │     │  API     │
  │  SSO     │     │           │     │            │     │  Call    │
  └──────────┘     └───────────┘     └────────────┘     └──────────┘
                                          │
                                    ┌─────┴─────┐
                                    │ 1. API Key │
                                    │ 2. Sandbox │
                                    │ 3. Test    │
                                    └───────────┘
```

Production access follows an approval workflow. Developers request production access from the portal, specifying their use case and expected volume. Tenant admins review requests in the admin panel at `app/(dashboard)/portal/access-requests/page.tsx` and approve or reject with comments. Approved requests auto-provision production API keys and assign the developer to a usage plan.

**Acceptance Criteria**

- Developers can register with email+password or SSO (SAML 2.0 / OIDC)
- Organization management supports team invitations with admin/developer/viewer roles
- API keys are self-provisioned with full value shown once and stored as bcrypt hashes
- Onboarding wizard guides developers from key creation through first test API call
- Sandbox environments provide isolated access with relaxed rate limits
- Production access request workflow routes to tenant admins for approval
- All registration and key lifecycle events are logged in the audit trail

**Part of Epic: Portal Platform**

---

#### 1.4 (#1369) — Developer Usage Analytics

API providers need insight into how developers consume their APIs — which endpoints are popular, who's hitting errors, and which consumers are approaching their quotas. This issue builds the analytics dashboards for both API providers and individual developers.

The provider-facing dashboard at `app/(dashboard)/portal/analytics/page.tsx` presents aggregate metrics: total active developers, requests per day (time series chart), top endpoints by request volume (Radix UI `Table`), error rate by consumer (sortable table with sparkline charts), and latency percentiles (p50/p95/p99) per endpoint. Filters include date range (Radix UI date picker), API version, and consumer organization.

The developer-facing dashboard at `app/(portal)/[tenantSlug]/analytics/page.tsx` shows the individual developer's own usage: request volume over time, quota consumption progress bar, endpoint breakdown, error rate, and average latency. A Radix UI `Tabs` component switches between 24h, 7d, and 30d views.

Data is aggregated from gateway request logs into hourly rollup tables in PostgreSQL. The analytics REST API exposes `GET /api/v1/portal/analytics/provider` (admin-scoped) and `GET /api/v1/portal/analytics/developer/{developerId}` (self-scoped) with `from`, `to`, and `granularity` query parameters. Engagement metrics track developer activity: days since last request, API adoption breadth (unique endpoints used), and SDK download counts.

**Acceptance Criteria**

- Provider dashboard shows active developer count, request volume, top endpoints, and error rates
- Developer dashboard shows personal usage with quota consumption progress bar
- Time range selection (24h, 7d, 30d) updates all charts simultaneously
- Latency percentiles (p50, p95, p99) are computed from gateway request logs
- Engagement metrics track last active date, endpoint breadth, and SDK downloads
- Data freshness is within 5 minutes; dashboards display a "last updated" timestamp
- Analytics REST API conforms to OpenAPI 3.1 spec with pagination and filtering

**Part of Epic: Portal Platform**

---

## Epic 2: Portal Customization

### Summary Table

| #   | Title                            | Description                                                                    | Labels                                   | Parallel |
|-----|----------------------------------|--------------------------------------------------------------------------------|------------------------------------------|----------|
| 2.1 (#1385) | Branding & Theming Engine        | Custom logo, colors, CSS, themes, header/footer, and legal pages per tenant    | `enhancement`, `portal`, `rest`, `ai-generated`          | Yes      |
| 2.2 (#1394) | Content Management System        | Custom landing pages, blog, FAQ, video embeds, and Markdown/MDX authoring      | `enhancement`, `portal`, `rest`, `ai-generated`          | Yes      |
| 2.3 (#1405) | Custom Domain & SSO Integration  | Custom domain mapping with SSL provisioning and enterprise SSO configuration   | `enhancement`, `portal`, `rest`, `ai-generated`          | No       |

### Detailed Issue Descriptions

---

#### 2.1 (#1385) — Branding & Theming Engine

Enterprise API providers need their developer portal to look like their product, not like a third-party tool. This issue builds the theming engine that lets tenants fully customize the portal's visual identity.

The branding configuration page at `app/(dashboard)/portal/branding/page.tsx` provides controls for: logo upload (SVG/PNG, max 2MB), favicon upload, primary and secondary brand colors (Radix UI color picker via `Popover`), custom CSS injection (validated and sanitized), and light/dark theme selection with per-theme color overrides. Changes preview in a live side panel before publishing.

The header and footer are configurable via a WYSIWYG-lite editor. Tenants can add navigation links, social media icons, and a custom tagline to the header. The footer supports columns of links, a copyright notice, and legal page references. Legal pages (Terms of Service, Privacy Policy, Acceptable Use) are editable markdown documents stored per-tenant.

```
Theming Pipeline
────────────────
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │  Admin sets  │────▶│  CSS vars    │────▶│  Portal      │
  │  brand       │     │  generated   │     │  renders     │
  │  colors/logo │     │  & cached    │     │  with theme  │
  └──────────────┘     └──────────────┘     └──────────────┘
        │                                         │
        └── preview panel ────────────────────────┘
```

Theme configuration is stored in PostgreSQL and cached in Redis. The portal reads the theme at request time and injects CSS custom properties (`--portal-primary`, `--portal-secondary`, etc.) into the root layout. ISR ensures theme changes propagate within 60 seconds. The REST API exposes `GET /api/v1/portal/branding/{tenantId}` and `PUT /api/v1/portal/branding/{tenantId}` with multipart support for file uploads.

**Acceptance Criteria**

- Tenants can upload a custom logo and favicon that render in the portal header and browser tab
- Primary and secondary brand colors propagate through all portal UI components via CSS custom properties
- Custom CSS is validated, sanitized (no `@import`, no external URLs), and applied as an override layer
- Light and dark themes are independently configurable with per-theme color overrides
- Header and footer content is customizable with navigation links and legal page references
- Live preview panel shows branding changes before they are published
- Theme changes propagate to the public portal within 60 seconds via ISR revalidation

**Part of Epic: Portal Customization**

---

#### 2.2 (#1394) — Content Management System

Beyond auto-generated documentation, API providers need to publish custom content: landing pages, blog posts, tutorials, FAQs, and announcements. This issue builds a lightweight CMS integrated into the portal admin.

The CMS authoring interface at `app/(dashboard)/portal/content/page.tsx` presents a page list (Radix UI `Table`) with title, type (landing/blog/faq/tutorial), status (draft/published/archived), and last modified date. Creating or editing a page opens a Markdown/MDX editor with live preview, frontmatter fields (title, slug, description, tags, publish date), and media upload (images, videos). MDX support enables embedding React components like code playgrounds, interactive schema viewers, and API endpoint cards directly within content pages.

Published content renders at `app/(portal)/[tenantSlug]/content/[slug]/page.tsx` with ISR. Blog posts support an RSS feed at `/portal/[tenantSlug]/feed.xml`. The FAQ section renders as a Radix UI `Accordion` with search. Video tutorials support YouTube/Vimeo embed URLs with a custom player wrapper that tracks engagement (play, completion percentage).

The CMS REST API exposes `GET /api/v1/portal/content`, `POST /api/v1/portal/content`, `PATCH /api/v1/portal/content/{id}`, and `DELETE /api/v1/portal/content/{id}`. Content versioning tracks edit history with the ability to revert to previous versions.

**Acceptance Criteria**

- Content authors can create, edit, publish, and archive pages via a Markdown/MDX editor with live preview
- MDX components (code playground, schema viewer, endpoint card) render correctly in published pages
- Blog posts are listed chronologically with an auto-generated RSS feed
- FAQ section renders as a searchable Radix UI `Accordion`
- Video embeds track engagement metrics (play count, average watch percentage)
- Content versioning stores edit history and supports reverting to previous versions
- Published content pages are ISR-rendered with 60-second revalidation

**Part of Epic: Portal Customization**

---

#### 2.3 (#1405) — Custom Domain & SSO Integration

Enterprise tenants expect the portal to live on their own domain with their own authentication. This issue delivers custom domain mapping with automatic SSL certificate provisioning and enterprise SSO configuration.

Custom domain setup is managed at `app/(dashboard)/portal/domains/page.tsx`. Tenants enter their desired domain (e.g., `developers.acme.com`), and the system generates DNS verification records (CNAME or TXT). Once verified, the platform provisions an SSL certificate via Let's Encrypt and configures the reverse proxy to route the domain to the tenant's portal. Domain status is tracked through states: pending verification → DNS verified → SSL provisioning → active. The REST API exposes `POST /api/v1/portal/domains`, `GET /api/v1/portal/domains/{id}/verify`, and `DELETE /api/v1/portal/domains/{id}`.

SSO configuration is managed at `app/(dashboard)/portal/sso/page.tsx`. The admin uploads SAML 2.0 metadata XML or configures OIDC with issuer URL, client ID, and client secret. The system supports multiple identity providers per tenant for organizations with complex IdP landscapes. SSO login redirects the developer to the configured IdP, and on successful authentication, provisions a portal developer account linked to the SSO identity. Attribute mapping (Radix UI `Table` with editable rows) controls how IdP claims map to portal fields (name, email, organization, role).

JIT (Just-In-Time) provisioning creates developer accounts on first SSO login. Admins can restrict JIT provisioning to specific email domains or disable it entirely, requiring pre-created accounts.

**Acceptance Criteria**

- Tenants can register a custom domain with DNS verification and automatic SSL via Let's Encrypt
- Domain status transitions through pending → verified → provisioning → active with clear UI indicators
- SAML 2.0 SSO is configurable via metadata XML upload with attribute mapping
- OIDC SSO is configurable with issuer URL, client ID, and client secret
- JIT provisioning creates developer accounts on first SSO login with configurable domain restrictions
- Multiple identity providers are supported per tenant
- Custom domain traffic is routed to the tenant's portal with zero downtime on activation

**Part of Epic: Portal Customization**

---

## Epic 3: SDK Generation & Distribution

### Summary Table

| #   | Title                                 | Description                                                                  | Labels                                            | Parallel |
|-----|---------------------------------------|------------------------------------------------------------------------------|---------------------------------------------------|----------|
| 3.1 (#1424) | Multi-Language SDK Code Generator     | Generate typed SDKs from OpenAPI specs for 10 languages                      | `enhancement`, `mvp`, `portal`, `rest`, `ai-generated`            | Yes      |
| 3.2 (#1441) | SDK Quality Assurance Pipeline        | Auto-generated tests, breaking change detection, and semver enforcement      | `enhancement`, `portal`, `ai-generated`           | No       |
| 3.3 (#1450) | Package Registry Publishing           | Automated publishing to npm, PyPI, Maven, NuGet, and Go modules             | `enhancement`, `portal`, `rest`, `ai-generated`                   | No       |
| 3.4 (#1461) | SDK Versioning & Lifecycle Management | API-version-tied SDK versioning with LTS, pre-release, and deprecation      | `enhancement`, `portal`, `rest`, `ai-generated`                   | Yes      |
| 3.5 (#1469) | SDK Documentation Generation          | Auto-generated per-language SDK docs with usage examples and changelogs      | `enhancement`, `portal`, `ai-generated`                           | Yes      |

### Detailed Issue Descriptions

---

#### 3.1 (#1424) — Multi-Language SDK Code Generator

Hand-writing API clients is error-prone and tedious. This issue builds the SDK generation pipeline that takes an OpenAPI 3.1 specification and produces idiomatic, typed client libraries for TypeScript/JavaScript, Python, Java, Kotlin, Swift, Go, C#, Ruby, PHP, and Rust.

The generator wraps OpenAPI Generator with a custom template layer. Each language template produces idiomatic code: TypeScript emits ESM modules with full type exports, Python produces a pip-installable package with type hints and dataclasses, Java generates a Maven-structured project with builder-pattern models, Go produces a module with struct types and functional options for configuration. Every generated SDK includes: typed request/response models, an auto-configured HTTP client with base URL and auth header injection, retry logic with exponential backoff, request/response interceptor hooks, custom HTTP client support (for testing), async/await patterns where the language supports them, input validation against schema constraints, pagination helpers for list endpoints, and streaming support for file upload/download.

The generation pipeline is triggered via `POST /api/v1/portal/sdks/generate` with the OpenAPI spec ID, target languages (array), and configuration overrides (package name, namespace, auth strategy). Generation runs as an async job. The job status is polled via `GET /api/v1/portal/sdks/jobs/{jobId}`. On completion, the generated SDK packages are stored in object storage and linked to the API version.

```
Generation Pipeline
───────────────────
  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────┐
  │  OpenAPI    │────▶│  Template    │────▶│  Code Gen    │────▶│  Package  │
  │  3.1 Spec   │     │  Selection   │     │  (per lang)  │     │  Archive  │
  └─────────────┘     └──────────────┘     └──────────────┘     └───────────┘
                            │                     │
                      ┌─────┴─────┐         ┌─────┴─────┐
                      │ Language  │         │ Typed     │
                      │ Templates │         │ Models    │
                      │ (custom)  │         │ Auth      │
                      └───────────┘         │ Retry     │
                                            │ Paginate  │
                                            └───────────┘
```

The admin UI at `app/(dashboard)/portal/sdks/page.tsx` shows all generated SDKs in a Radix UI `Table` with language, API version, generation timestamp, and download link. A "Generate" button opens a Radix UI `Dialog` for selecting languages and configuring generation options.

**Acceptance Criteria**

- SDKs are generated for all 10 target languages from a single OpenAPI 3.1 specification
- Generated TypeScript SDK includes ESM modules, full type exports, and async/await patterns
- Generated Python SDK is pip-installable with type hints and dataclass models
- All SDKs include auto-configured auth, retry logic, interceptor hooks, and pagination helpers
- Generation runs as an async job with status polling; completion stores packages in object storage
- Configuration overrides (package name, namespace, auth strategy) are respected per generation
- Generated code compiles/type-checks without errors for all target languages
- Admin UI lists all generated SDKs with download links and generation metadata

**Part of Epic: SDK Generation & Distribution**

---

#### 3.2 (#1441) — SDK Quality Assurance Pipeline

Generated code must be trustworthy. This issue builds the automated QA pipeline that validates every generated SDK before it can be published, catching type errors, missing models, and breaking changes before consumers encounter them.

The QA pipeline runs immediately after code generation. For each language, it executes: (1) compilation/type-check (tsc for TypeScript, mypy for Python, javac for Java, go vet for Go, etc.), (2) auto-generated unit tests that exercise model serialization round-trips and endpoint method signatures, (3) auto-generated integration test scaffolding that makes real requests against the mock server (Epic 4) and asserts response shapes match the SDK types.

Breaking change detection compares the current SDK's public API surface (exported types, method signatures, constructor parameters) against the previous published version. Changes are classified as: `major` (removed/renamed exports, changed parameter types), `minor` (added exports, new optional parameters), or `patch` (internal changes, documentation). This classification feeds into the semver enforcement engine, which blocks publishing an SDK with breaking changes under a minor version bump.

The QA results are exposed via `GET /api/v1/portal/sdks/{sdkId}/qa-report` and rendered in the admin UI as a pass/fail summary with drill-down into individual test results. A Radix UI `Badge` on each SDK row indicates QA status: passed (green), failed (red), or pending (amber).

**Acceptance Criteria**

- Every generated SDK is type-checked/compiled in its target language before publishing is allowed
- Auto-generated unit tests verify model serialization round-trips for all schema types
- Integration test scaffolding generates runnable tests against the mock server
- Breaking change detection classifies changes as major/minor/patch by comparing public API surfaces
- Semver enforcement blocks publishing a breaking change under a minor or patch version bump
- QA reports are accessible via REST API and rendered in the admin UI with pass/fail badges
- The pipeline completes within 5 minutes for a typical SDK with 50+ models

**Part of Epic: SDK Generation & Distribution**

---

#### 3.3 (#1450) — Package Registry Publishing

Generated and QA-validated SDKs need to reach developers through their language's native package manager. This issue automates publishing to npm (TypeScript/JS), PyPI (Python), Maven Central (Java/Kotlin), NuGet (C#), Go modules (Go), RubyGems (Ruby), Packagist (PHP), crates.io (Rust), and Swift Package Manager (Swift). It also supports publishing to private registries for enterprise tenants.

Each registry requires specific credentials and metadata. The publishing configuration page at `app/(dashboard)/portal/sdks/registries/page.tsx` lets admins configure registry credentials (API tokens stored encrypted in PostgreSQL), package metadata (author, license, repository URL, homepage), and publishing rules (auto-publish on QA pass vs. manual approval). Credentials are entered via Radix UI `Dialog` with `TextField` inputs and stored with AES-256 encryption at rest.

The publishing pipeline runs as a background job triggered by QA pipeline completion (if auto-publish is enabled) or manual trigger via `POST /api/v1/portal/sdks/{sdkId}/publish`. The job builds the distribution package (tarball for npm, wheel for PyPI, JAR for Maven, etc.), signs it where required, and pushes it to the configured registry. The job logs every step and reports success or failure with the published version and registry URL.

Private registry support covers npm (Artifactory, GitHub Packages, Verdaccio), PyPI (Artifactory, devpi), and Maven (Nexus, Artifactory). The admin selects public or private registry per language in the configuration.

**Acceptance Criteria**

- SDKs are publishable to npm, PyPI, Maven Central, NuGet, Go modules, RubyGems, Packagist, crates.io, and SPM
- Registry credentials are stored with AES-256 encryption and never exposed in API responses
- Auto-publish triggers on QA pipeline pass when enabled; manual publish is always available
- Private registry support covers Artifactory, GitHub Packages, and Nexus configurations
- Publishing logs capture every step (build, sign, push) with success/failure and registry URL
- Failed publishes surface actionable error messages (auth failure, version conflict, validation error)
- Published package metadata (author, license, homepage) is configurable per tenant

**Part of Epic: SDK Generation & Distribution**

---

#### 3.4 (#1461) — SDK Versioning & Lifecycle Management

SDKs must stay in sync with the API they represent. This issue implements API-version-tied SDK versioning with automatic version bumping, pre-release channels, long-term support (LTS) tracks, and deprecation announcements.

Each SDK version is derived from the API version it was generated from, following semver. When a new API version is published, the system auto-generates SDKs and bumps the SDK version based on the breaking change classification from the QA pipeline (3.2). Pre-release versions (e.g., `2.0.0-beta.1`) are generated for draft API versions, giving consumers early access to upcoming changes without affecting stable installations.

LTS support allows tenants to designate specific SDK versions as long-term support. LTS versions receive security patches and critical bug fixes backported from newer versions. The LTS policy (duration, end-of-life date) is configured per API via `PUT /api/v1/portal/sdks/{apiId}/lts-policy`. When an LTS version approaches end-of-life, the system publishes deprecation notices to the SDK's changelog, the portal documentation, and email notifications to consumers who have downloaded the LTS version.

The lifecycle management dashboard at `app/(dashboard)/portal/sdks/lifecycle/page.tsx` shows all SDK versions in a timeline view (Radix UI `Table` with status `Badge` indicators: stable, pre-release, LTS, deprecated, EOL). Admins can promote pre-release to stable, designate LTS, or mark deprecated from this page.

**Acceptance Criteria**

- SDK versions are automatically derived from API versions following semver conventions
- Pre-release versions are generated for draft API versions with `-beta.N` or `-rc.N` suffixes
- LTS versions are configurable per API with duration and end-of-life date
- Deprecation announcements are published to changelog, documentation, and email 90 days before EOL
- Lifecycle dashboard displays all versions with status timeline and admin actions
- Auto-version bumping respects breaking change classification (major/minor/patch)
- Version history is immutable; yanked versions are marked but never deleted from the registry

**Part of Epic: SDK Generation & Distribution**

---

#### 3.5 (#1469) — SDK Documentation Generation

Every published SDK needs documentation that matches the language's conventions. This issue auto-generates per-language SDK documentation with usage examples, getting-started guides, and changelogs.

The documentation generator produces language-appropriate output: TSDoc for TypeScript, Sphinx/docstrings for Python, Javadoc for Java, GoDoc comments for Go, XML docs for C#, and YARD for Ruby. Generated docs are rendered as HTML and hosted on the portal at `app/(portal)/[tenantSlug]/sdks/[language]/docs/page.tsx`. Each page includes: installation instructions (copy-pasteable package manager command), authentication setup, quickstart example, full API reference with method signatures and parameter descriptions, and error handling patterns.

Changelogs are auto-generated from the version diff and breaking change detection output. Each changelog entry includes the version number, release date, a summary of changes (added endpoints, modified models, deprecated methods), and migration notes for breaking changes. The changelog is also published as a `CHANGELOG.md` file inside the SDK package.

The SDK docs page uses Radix UI `Tabs` for switching between languages, `NavigationMenu` for the sidebar table of contents, and `Accordion` for collapsible method details. Code examples are syntax-highlighted with a copy button.

**Acceptance Criteria**

- SDK documentation is auto-generated for each language using the language's native doc format
- Installation instructions include the correct package manager command for each language
- Quickstart examples show authentication setup and a complete request/response cycle
- Full API reference documents every method signature, parameter, and return type
- Changelogs are auto-generated with version, date, change summary, and migration notes
- Documentation pages are hosted on the portal with ISR and per-language navigation
- A copy button on all code examples copies the snippet to the clipboard

**Part of Epic: SDK Generation & Distribution**

---

## Epic 4: Local Development Environment

### Summary Table

| #   | Title                               | Description                                                                  | Labels                                           | Parallel |
|-----|-------------------------------------|------------------------------------------------------------------------------|--------------------------------------------------|----------|
| 4.1 (#1477) | Mock Server from OpenAPI Spec       | Generate a runnable mock server from any OpenAPI spec with hot-reload        | `enhancement`, `mvp`, `portal`, `rest`, `ai-generated`           | Yes      |
| 4.2 (#1482) | Stateful Mocking Engine             | In-memory CRUD store with relationship handling, seed data, and persistence  | `enhancement`, `portal`, `rest`, `ai-generated`                  | No       |
| 4.3 (#1487) | Interactive API Playground          | Web-based request builder with autocomplete, auth management, and history   | `enhancement`, `mvp`, `portal`, `rest`, `ai-generated`           | Yes      |
| 4.4 (#1489) | Playground Collaboration & Export   | Share collections, team workspaces, request comments, Postman/Insomnia export| `enhancement`, `portal`, `ai-generated`                          | No       |

### Detailed Issue Descriptions

---

#### 4.1 (#1477) — Mock Server from OpenAPI Spec

Developers need a local API to code against before the real backend is ready. This issue builds a mock server generator that reads an OpenAPI 3.1 specification and produces a runnable HTTP server returning schema-valid responses — available as a Docker container or a standalone Node.js process.

The generator analyzes response schemas and example values in the OpenAPI spec to produce realistic mock responses. When `example` values are present, those are used verbatim. When absent, the generator produces synthetic data matching the schema constraints: strings of the correct format (email, UUID, date-time), numbers within min/max bounds, arrays of the declared item type, and enums selected randomly from the allowed values. The mock server validates incoming requests against the spec's request schemas and returns 422 with detailed errors for invalid requests.

The mock server supports hot-reload: when the OpenAPI spec file changes on disk (watched via `fs.watch`), the server reloads the spec and regenerates response handlers without restarting. Latency simulation is configurable per endpoint via a `x-mock-latency` extension field (value in milliseconds) or globally via a `--latency` CLI flag. Error injection allows developers to test error paths by setting `x-mock-error-rate` (percentage of requests that return a configured error status).

```
Mock Server Architecture
────────────────────────
  ┌──────────────┐     ┌───────────────┐     ┌───────────────┐
  │  OpenAPI     │────▶│  Route        │────▶│  Express/     │
  │  3.1 Spec    │     │  Generator    │     │  Fastify      │
  └──────────────┘     └───────────────┘     │  Server       │
        │                     │              └───────┬───────┘
   fs.watch               ┌───┴────┐                │
   (hot-reload)           │ Schema │           ┌────┴────┐
                          │ → Data │           │ Req     │
                          │ Gen    │           │ Validate│
                          └────────┘           └─────────┘
```

The mock server is distributed as a Docker image (`objectified/mock-server`) and as an npm package (`@objectified/mock-server`). The CLI interface supports `mock-server start --spec ./openapi.yaml --port 4010`. The REST API at `POST /api/v1/portal/mock-servers` generates a downloadable Docker Compose file or npm project for a given spec.

**Acceptance Criteria**

- Mock server generates responses matching the OpenAPI schema with example values or synthetic data
- Incoming requests are validated against request schemas; invalid requests receive 422 responses
- Hot-reload picks up spec file changes within 2 seconds without server restart
- Latency simulation is configurable per endpoint via `x-mock-latency` or global `--latency` flag
- Error injection returns configured error statuses at the specified `x-mock-error-rate` percentage
- Docker image and npm package are both functional distribution channels
- CLI supports `start`, `--spec`, `--port`, `--latency`, and `--seed` flags

**Part of Epic: Local Development Environment**

---

#### 4.2 (#1482) — Stateful Mocking Engine

Stateless mocks return the same response every time. Real APIs have state — creating a resource returns it, listing resources includes previously created ones, deleting removes it. This issue builds a stateful mocking engine that simulates CRUD operations with an in-memory store.

The engine infers CRUD semantics from the OpenAPI spec: POST endpoints create resources (stored in the in-memory collection), GET with an ID parameter retrieves a single resource, GET without an ID lists all resources in the collection, PUT/PATCH updates a stored resource, and DELETE removes it. The engine uses `operationId` patterns and path structure to infer which endpoints operate on the same resource collection.

Relationship handling supports `$ref`-based associations. If a schema references another schema (e.g., an Order's `customerId` references a Customer), the engine validates referential integrity on create/update — returning 422 if the referenced resource doesn't exist. Cascading behavior (delete customer → delete their orders) is configurable per relationship.

Seed data is loadable from JSON files via `--seed ./seed-data.json` or via `POST /api/v1/mock-server/seed` at runtime. A reset endpoint (`POST /api/v1/mock-server/reset`) clears all state and reloads seed data. For teams that need persistence across server restarts, a SQLite mode (`--persist sqlite`) writes state to a local SQLite database file instead of in-memory storage.

**Acceptance Criteria**

- POST requests create resources stored in the in-memory collection and return the created entity
- GET requests retrieve previously created resources by ID or list all resources in a collection
- PUT/PATCH update stored resources; DELETE removes them with correct status codes
- Referential integrity is enforced for `$ref`-based relationships on create/update
- Seed data is loadable from JSON files via CLI flag or runtime REST endpoint
- Reset endpoint clears all state and reloads seed data
- SQLite persistent mode survives server restarts with `--persist sqlite` flag
- Collections are correctly inferred from OpenAPI path structure and `operationId` patterns

**Part of Epic: Local Development Environment**

---

#### 4.3 (#1487) — Interactive API Playground

The API playground is a web-based tool embedded in the developer portal where developers compose, send, and inspect API requests without leaving the browser. It replaces the need for external tools like Postman for quick API exploration.

The playground lives at `app/(portal)/[tenantSlug]/playground/page.tsx`. The interface is split into three panels: (1) a left sidebar showing saved collections and request history, (2) a center panel for composing requests, and (3) a right panel displaying the response. The request builder provides URL input with path parameter highlighting, HTTP method selector (Radix UI `Select`), a headers editor (Radix UI `Table` with inline editing), query parameter editor, and a body editor with JSON syntax highlighting and schema-aware autocomplete.

Authentication is managed through a credential vault (Radix UI `Dialog`) where developers store API keys, OAuth tokens, or JWT values. Credentials are stored in browser `localStorage` (encrypted with a user-derived key) and auto-injected into requests based on the endpoint's security scheme. Environment variables (`{{baseUrl}}`, `{{apiKey}}`) are supported in all fields and managed via a Radix UI `Popover` editor.

```
┌────────────┬──────────────────────────────┬──────────────────┐
│ Collections│  Request Builder             │  Response        │
│            │  ┌──────────────────────┐    │                  │
│ > Users    │  │ GET ▾ {{baseUrl}}/u… │    │  200 OK  342ms   │
│   GET /    │  └──────────────────────┘    │                  │
│   POST /   │  Headers  Params  Body  Auth │  {              │
│   GET /:id │  ┌──────────────────────┐    │    "users": [   │
│            │  │ Authorization:       │    │      { ... }    │
│ > Orders   │  │ Bearer {{apiKey}}    │    │    ]            │
│   ...      │  └──────────────────────┘    │  }              │
│            │                              │                  │
│ History    │  [Send Request]              │  Headers  Body   │
│  12:34 GET │                              │  Curl  Timing    │
│  12:31 POST│                              │                  │
└────────────┴──────────────────────────────┴──────────────────┘
```

The playground also supports test assertions — developers can write simple checks (status code equals, body contains, response time under N ms) that run after each request and display pass/fail badges. Performance timing breaks down DNS lookup, TCP connect, TLS handshake, TTFB, and content transfer phases.

**Acceptance Criteria**

- Request builder supports all HTTP methods with URL, headers, query params, and body editing
- Schema-aware autocomplete suggests field names and enum values in the JSON body editor
- Credential vault stores API keys and tokens in encrypted localStorage with auto-injection
- Environment variables are supported in URL, headers, and body with a management UI
- Response panel displays status code, timing, syntax-highlighted body, and response headers
- Test assertions evaluate status code, body content, and response time with pass/fail indicators
- Request history persists in localStorage across browser sessions
- Performance timing shows DNS, TCP, TLS, TTFB, and transfer breakdown

**Part of Epic: Local Development Environment**

---

#### 4.4 (#1489) — Playground Collaboration & Export

Individual exploration is useful, but teams need to share their API testing workflows. This issue adds collaboration features — shared collections, team workspaces, request comments — and export capabilities for Postman and Insomnia.

Shared collections move from localStorage to the server. When a developer clicks "Share" on a collection, it is saved to PostgreSQL and a shareable URL is generated. Team members with portal access can open shared collections, fork them (creating a personal copy), or contribute to the shared version if they have write access. Collection permissions follow the org's role model (admin: full access, developer: read + fork, viewer: read only).

Team workspaces at `app/(portal)/[tenantSlug]/playground/workspaces/page.tsx` provide a folder-level organization for collections. Each workspace has a name, description, and member list. Workspaces are listed in the playground sidebar. Request comments (Radix UI `Popover` attached to each saved request) enable developers to annotate requests with notes, known issues, or expected behaviors.

Export formats include Postman Collection v2.1 (JSON) and Insomnia v4 (JSON/YAML). Import from these formats is also supported, allowing developers to migrate existing workflows into the portal playground. The export button (Radix UI `DropdownMenu`) offers format selection and downloads the file immediately.

**Acceptance Criteria**

- Collections are shareable via URL with server-side storage in PostgreSQL
- Team members can fork shared collections to create personal copies
- Collection permissions follow org roles: admin (full), developer (read + fork), viewer (read only)
- Team workspaces organize collections into named, permissioned folders
- Request comments are attachable to saved requests with inline display
- Export produces valid Postman Collection v2.1 and Insomnia v4 format files
- Import parses Postman and Insomnia files and creates portal collections

**Part of Epic: Local Development Environment**

---

## Epic 5: IDE Extensions

### Summary Table

| #   | Title                                       | Description                                                                  | Labels                                           | Parallel |
|-----|---------------------------------------------|------------------------------------------------------------------------------|--------------------------------------------------|----------|
| 5.1 (#1494) | VS Code Extension — Schema Editing          | OpenAPI highlighting, JSON Schema IntelliSense, validation, quick fixes      | `enhancement`, `mvp`, `portal`, `ai-generated`                   | Yes      |
| 5.2 (#1495) | VS Code Extension — Cloud Integration       | Sync with portal, generate code, run mock server, test endpoints from IDE    | `enhancement`, `portal`, `rest`, `ai-generated`                  | No       |
| 5.3 (#1496) | JetBrains Plugin                            | Native JetBrains UI with schema editing, cloud sync, and project wizard      | `enhancement`, `portal`, `ai-generated`                          | Yes      |
| 5.4 (#1497) | Schema Diff & Live Preview                  | Visual schema diff tool and live documentation preview in both IDEs          | `enhancement`, `portal`, `ai-generated`                          | Yes      |

### Detailed Issue Descriptions

---

#### 5.1 (#1494) — VS Code Extension — Schema Editing

Editing OpenAPI and JSON Schema files in a plain text editor is error-prone. This extension brings full language intelligence to schema authoring: syntax highlighting, IntelliSense, real-time validation, quick fixes, go-to-definition, find-references, and rename support.

The extension implements a Language Server Protocol (LSP) server for OpenAPI 3.1 and JSON Schema 2020-12. The LSP server parses the active document on every keystroke (debounced at 300ms), validates it against the OpenAPI/JSON Schema meta-schema, and reports diagnostics (errors, warnings, hints) in the VS Code Problems panel. Validation covers structural errors (invalid property names, wrong types), semantic errors (missing required `$ref` targets, duplicate operation IDs), and best-practice warnings (missing descriptions, unused schemas).

IntelliSense provides context-aware completions: when typing inside a `paths` object, it suggests HTTP methods; inside a schema `properties` object, it suggests `type`, `format`, `description`, `example`, etc. Hovering a `$ref` pointer shows the referenced schema inline. Go-to-definition navigates to the referenced schema definition, even across files in multi-file specs. Find-references locates all `$ref` pointers to a given schema. Rename symbol updates a schema name and all `$ref` pointers referencing it across the workspace.

Quick fixes offer one-click resolutions: add missing `description` fields, generate `example` values from the schema type, convert inline schemas to `$ref` components, and fix common JSON Schema mistakes (e.g., `"type": "string"` with `minimum` → suggest changing to `"type": "number"` or removing `minimum`).

**Acceptance Criteria**

- Syntax highlighting distinguishes OpenAPI keywords, JSON keys, values, and `$ref` pointers
- Real-time validation reports errors in the Problems panel within 500ms of keystroke
- IntelliSense provides context-aware completions for OpenAPI and JSON Schema keywords
- Go-to-definition navigates to `$ref` targets within the same file and across workspace files
- Find-references locates all `$ref` pointers to a selected schema definition
- Rename symbol updates the schema name and all `$ref` references across the workspace
- Quick fixes offer at least 4 auto-fix actions (add description, generate example, extract component, fix type mismatch)

**Part of Epic: IDE Extensions**

---

#### 5.2 (#1495) — VS Code Extension — Cloud Integration

Schema editing alone doesn't close the loop. This issue connects the VS Code extension to the Objectified portal, enabling developers to sync schemas, generate SDK code, run mock servers, test endpoints, and browse documentation — all without leaving the editor.

Cloud sync authenticates with the portal via OAuth2 device flow (the extension opens a browser tab for login and receives a token). Once authenticated, the extension's sidebar (VS Code TreeView) lists all APIs the developer has access to. Pulling an API downloads the OpenAPI spec to the workspace. Pushing local changes uploads the spec to the portal as a draft version, triggering SDK regeneration and documentation preview.

The "Generate Code" command (available in the Command Palette and right-click context menu) sends the active spec to the portal's SDK generation endpoint and downloads the generated client code into the workspace. Language selection is configurable in extension settings. The "Run Mock Server" command starts a local mock server (from Epic 4) using the active spec, with output streamed to a VS Code terminal. The "Test Endpoint" CodeLens appears above each path in the OpenAPI spec, allowing developers to send a request with one click and see the response in an output panel.

The extension also provides a documentation preview webview panel that renders the spec as it would appear in the portal documentation hub, updating live as the developer edits the spec file.

**Acceptance Criteria**

- OAuth2 device flow authenticates the extension with the Objectified portal
- Sidebar TreeView lists accessible APIs with pull/push actions for syncing specs
- "Generate Code" command downloads generated SDK client into the workspace for the selected language
- "Run Mock Server" starts a local mock server in a VS Code terminal with hot-reload
- "Test Endpoint" CodeLens sends requests and displays responses in an output panel
- Documentation preview webview renders the spec as portal documentation with live updates
- Extension settings allow configuring portal URL, default language, and mock server port

**Part of Epic: IDE Extensions**

---

#### 5.3 (#1496) — JetBrains Plugin

JetBrains IDEs (IntelliJ IDEA, WebStorm, PyCharm, GoLand) are widely used in enterprise environments. This issue delivers the same capabilities as the VS Code extension (5.1 + 5.2) in a native JetBrains plugin built with the IntelliJ Platform SDK.

The plugin provides: OpenAPI/JSON Schema syntax highlighting via a custom `Language` and `Lexer`, inspections (the JetBrains equivalent of LSP diagnostics) that report validation errors in the editor gutter, completion contributors for context-aware IntelliSense, reference resolution for `$ref` pointers with Ctrl+Click navigation, and rename refactoring that updates `$ref` references across the project.

Cloud integration mirrors the VS Code extension: OAuth2 login, API listing in a tool window (JetBrains `ToolWindowFactory`), pull/push sync, code generation, mock server launch (in the Run/Debug configurations panel), and endpoint testing via intention actions on path definitions.

A project wizard ("New Project → Objectified API") scaffolds a new API project with a starter OpenAPI spec, a pre-configured mock server script, and a generated SDK in the developer's chosen language. The wizard uses JetBrains `ModuleBuilder` with step-by-step panels for API name, base URL, authentication scheme, and target languages.

**Acceptance Criteria**

- Plugin installs from the JetBrains Marketplace and activates for `.yaml`, `.json`, and `.openapi` files
- Syntax highlighting, inspections, completion, and `$ref` navigation match VS Code extension parity
- Cloud sync authenticates via OAuth2 and lists APIs in a dedicated tool window
- Code generation, mock server launch, and endpoint testing are available from the IDE
- Project wizard scaffolds a complete API project with spec, mock server, and generated SDK
- Rename refactoring updates `$ref` pointers across the project
- Plugin supports IntelliJ IDEA, WebStorm, PyCharm, and GoLand with compatible platform versions

**Part of Epic: IDE Extensions**

---

#### 5.4 (#1497) — Schema Diff & Live Preview

Schema evolution is inevitable, and developers need to see exactly what changed between versions and how those changes will appear in documentation. This issue adds a visual schema diff tool and a live documentation preview to both IDE extensions.

The schema diff tool compares two versions of an OpenAPI spec (local file vs. portal version, or two local files) and renders a side-by-side diff view with semantic awareness. Unlike a plain text diff, the schema diff understands OpenAPI structure: it groups changes by endpoint, highlights added/removed/modified parameters, request bodies, and response schemas, and classifies each change as breaking or non-breaking. Breaking changes are highlighted with a red background and a warning icon.

In VS Code, the diff opens in a custom webview panel using the editor's diff infrastructure augmented with semantic annotations. In JetBrains, it uses the platform's `DiffManager` with custom gutter annotations. Both implementations share a common diff engine (TypeScript library) that produces a structured diff output consumed by each IDE's rendering layer.

The live preview panel renders the OpenAPI spec as portal documentation (matching the portal's Documentation Hub styling) and updates in real-time as the developer types. This provides immediate visual feedback on how description changes, new endpoints, and schema modifications will appear to API consumers. The preview supports switching between desktop and mobile viewport widths.

**Acceptance Criteria**

- Schema diff compares two spec versions with semantic awareness of OpenAPI structure
- Changes are grouped by endpoint with added/removed/modified classification
- Breaking changes are visually distinguished with red highlights and warning icons
- Live preview renders the spec as portal documentation with real-time updates on edit
- Preview supports desktop and mobile viewport widths for responsive design verification
- Diff engine produces identical structured output for both VS Code and JetBrains consumers
- Diff view supports comparing local file vs. portal version and local file vs. local file

**Part of Epic: IDE Extensions**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 — Portal Platform**
- **1.1** (API Discovery Catalog), **1.2** (Documentation Hub), and **1.3** (Developer Registration) are independent features and can be developed in parallel. Each has its own pages, REST endpoints, and data models.
- **1.4** (Developer Analytics) depends on gateway request log data being available and should start after 1.3 establishes the developer account model.

**Epic 2 — Portal Customization**
- **2.1** (Branding & Theming) and **2.2** (Content Management) are fully independent and can be built in parallel.
- **2.3** (Custom Domain & SSO) depends on the portal being deployable (Epic 1 core) but has no dependency on 2.1 or 2.2.

**Epic 3 — SDK Generation & Distribution**
- **3.1** (Code Generator) is the foundation; all other Epic 3 issues depend on it.
- **3.4** (Versioning & Lifecycle) and **3.5** (SDK Documentation) can be built in parallel once 3.1 is complete.
- **3.2** (QA Pipeline) depends on 3.1. **3.3** (Registry Publishing) depends on 3.1 and 3.2 (QA must pass before publishing).

**Epic 4 — Local Development Environment**
- **4.1** (Mock Server) and **4.3** (API Playground) are independent and can be developed in parallel.
- **4.2** (Stateful Mocking) extends 4.1 and must follow it.
- **4.4** (Collaboration & Export) depends on 4.3 for the playground foundation.

**Epic 5 — IDE Extensions**
- **5.1** (VS Code Schema Editing) and **5.3** (JetBrains Plugin) can be developed in parallel by separate teams since they target different platforms.
- **5.2** (VS Code Cloud Integration) depends on 5.1 and on Epic 1 portal APIs being available.
- **5.4** (Schema Diff & Live Preview) can be built in parallel with 5.2 and 5.3 since it depends only on 5.1 for the VS Code side and the shared diff engine is platform-independent.

**Cross-Epic Parallelism**
- Epics 1 and 3 are independent and can be developed by separate teams. The portal platform (Epic 1) and SDK generation (Epic 3) share no code paths.
- Epic 2 (Portal Customization) depends on Epic 1 for the base portal but can be developed in parallel with Epics 3, 4, and 5.
- Epic 4 (Local Dev Environment) is fully independent of Epics 1–3. The mock server and playground are standalone tools.
- Epic 5 (IDE Extensions) depends on Epic 1 APIs for cloud integration (5.2) and Epic 4 for mock server integration (5.2), but the schema editing features (5.1, 5.3) have no dependencies on other epics.
- Maximum parallelism: 5 teams can work simultaneously — one on each epic — with integration points resolved when dependent issues reach their prerequisites.
