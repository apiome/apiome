# Apiome: Localization (i18n) - Feature Roadmap

> Internationalization and localization management for schemas, APIs, and generated documentation. Localization enables Apiome users to serve global audiences by managing multi-language schema metadata, translating API documentation, formatting responses for locale conventions, and validating internationalization compliance—all integrated into the existing schema-driven workflow.
>
> **Revenue Model**: Per-locale pricing, translation credits
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL with locale-partitioned storage, ICU MessageFormat, AI translation APIs
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Multi-language descriptions and examples on schema properties with locale selector
- Locale-specific validation rules (date formats, currency codes, phone patterns per locale)
- AI-powered translation pipeline for API documentation with human review queue
- Translation memory storing approved translations for consistency across schemas
- Locale-aware response formatting (dates, numbers, currencies) via API middleware
- Multi-language error messages with locale negotiation from Accept-Language header
- i18n compliance scanner detecting missing translations and encoding issues
- Coverage dashboard showing translation completeness per locale per schema

---

## Epic 1: Schema Localization Engine

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1103) | Multi-Language Schema Metadata | Store and serve schema descriptions in multiple languages | `enhancement`, `localization`, `mvp`, `rest` | Yes |
| 1.2 (#1104) | Locale-Specific Validation Rules | Define validation rules that vary by locale | `enhancement`, `localization`, `mvp`, `rest` | Yes |
| 1.3 (#1105) | Format Handling Engine | Handle locale-specific date, number, and currency formats | `enhancement`, `localization`, `mvp` | Yes |
| 1.4 (#1106) | RTL Language Support | Support right-to-left languages in schema UI and documentation | `enhancement`, `localization` | No |
| 1.5 (#1107) | Locale Management Dashboard | Central management of supported locales and locale configuration | `enhancement`, `localization`, `mvp` | Yes |

### Detailed Issue Descriptions

#### 1.1 (#1103) — Multi-Language Schema Metadata

Multi-Language Schema Metadata extends the Apiome schema model to support localized descriptions, titles, and examples on every schema property. Each property can have a `localizations` map keyed by BCP 47 locale code (e.g., `en-US`, `ja-JP`, `de-DE`) containing translated `title`, `description`, and `examples`. The default locale's content is stored in the standard JSON Schema fields; additional locales are stored in an extension namespace.

The localization editor at `/app/schemas/[id]/localize` renders a split-pane view with the schema tree on the left and a locale editor on the right. The locale editor uses Radix `Tabs` for each active locale with text inputs for title, description, and example fields. A locale selector in the header (Radix `Select`) switches the entire schema view to display content in the selected language—previewing how the schema documentation will appear for that locale.

```
┌──────────────────────────────────────────────────────────────────┐
│  Schema: UserProfile — Localization Editor                       │
│  Locale: [en-US ▾]  Coverage: en-US 100% | ja-JP 78% | de-DE 45%│
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Schema Properties          │  Locale: ja-JP                    │
│  ─────────────────          │  ──────────────                    │
│  ▼ firstName                │                                    │
│    ● en-US ✓                │  Title: [名前 (名)              ] │
│    ● ja-JP ✓                │                                    │
│    ○ de-DE ✗                │  Description:                      │
│                             │  [ユーザーの名前。表示名として   ] │
│  ▼ email                    │  [使用されます。                 ] │
│    ● en-US ✓                │                                    │
│    ● ja-JP ✓                │  Examples:                         │
│    ● de-DE ✓                │  [太郎                           ] │
│                             │                                    │
│  ▼ birthDate                │  Status: ● Translated              │
│    ● en-US ✓                │          [Save] [Auto-translate]   │
│    ○ ja-JP ✗                │                                    │
│    ○ de-DE ✗                │                                    │
│                             │                                    │
└──────────────────────────────────────────────────────────────────┘
```

Backend endpoints include `PUT /api/v1/schemas/{id}/properties/{propertyPath}/localizations` (upsert locale content), `GET /api/v1/schemas/{id}/localizations?locale={code}` (retrieve all properties for a locale), and `GET /api/v1/schemas/{id}/localizations/coverage` (translation coverage by locale). The `schema_localizations` table stores `schema_id`, `property_path` (JSON Pointer), `locale`, `title`, `description`, `examples` (JSONB array), and `status` (draft, reviewed, approved).

**Acceptance Criteria**:
- Every schema property supports localized title, description, and examples
- BCP 47 locale codes are used as keys (e.g., en-US, ja-JP, fr-FR, ar-SA)
- Split-pane editor displays schema tree alongside locale-specific content editor
- Coverage percentage is calculated per locale showing translated vs. total properties
- Locale selector switches the schema preview to display content in the selected language
- Default locale content is served when a requested locale is not available (fallback chain)

**Part of Epic: Schema Localization Engine**

---

#### 1.2 (#1104) — Locale-Specific Validation Rules

Locale-Specific Validation Rules enable defining validation constraints that vary by locale. Phone number patterns differ between countries (US: `+1-XXX-XXX-XXXX`, Japan: `+81-XX-XXXX-XXXX`), postal codes have different formats (US: 5 or 9 digits, UK: alphanumeric), date formats vary (US: MM/DD/YYYY, Europe: DD/MM/YYYY, Japan: YYYY/MM/DD), and currency codes are locale-bound (USD, JPY, EUR).

The validation rule editor at `/app/schemas/[id]/properties/[path]/validation` displays the base validation rule with a Radix `Accordion` for locale-specific overrides. Each override specifies a locale pattern (e.g., `en-US`, `en-*`, `*`) and the modified constraint (regex pattern, format, enum values). Overrides are evaluated in specificity order—exact locale match takes priority over wildcard.

Backend endpoints include `PUT /api/v1/schemas/{id}/properties/{path}/locale-validation` (set locale overrides), `GET /api/v1/schemas/{id}/properties/{path}/locale-validation` (list overrides), and `POST /api/v1/schemas/{id}/validate-localized` (validate a data payload with locale-aware rules). The `schema_locale_validation` table stores `schema_id`, `property_path`, `locale_pattern`, `validation_overrides` (JSONB containing the modified constraints), and `priority`.

**Acceptance Criteria**:
- Validation rules can be overridden per locale with specificity-based priority
- Locale patterns support exact match (en-US), language match (en-*), and wildcard (*)
- Common locale-specific validations include phone, postal code, date format, and currency
- Localized validation endpoint accepts a locale parameter and applies the appropriate rules
- Override editor shows the base rule alongside locale-specific modifications
- Missing locale overrides fall back to the base validation rule

**Part of Epic: Schema Localization Engine**

---

#### 1.3 (#1105) — Format Handling Engine

The Format Handling Engine provides locale-aware formatting and parsing for dates, numbers, currencies, and measurements. The engine wraps the ICU MessageFormat standard, enabling schemas to declare format-sensitive properties that are automatically formatted based on the consumer's locale. Formatting rules are applied at the API response layer via middleware.

The format configuration at `/app/schemas/[id]/formatting` allows defining format-sensitive properties with their format type (date, number, currency, measurement) and the canonical storage format (ISO 8601 for dates, raw number for amounts). The engine formats values on output and parses locale-formatted input back to the canonical format on input. Format profiles can be defined per locale, overriding the default ICU rules.

Backend endpoints include `PUT /api/v1/schemas/{id}/formatting` (configure format-sensitive properties), `POST /api/v1/localization/format` (format a value for a given locale), and `POST /api/v1/localization/parse` (parse a locale-formatted value to canonical form). The formatting middleware inspects the `Accept-Language` header and applies formatting to response properties marked as format-sensitive. Date formatting supports timezone conversion using the `X-Timezone` header.

**Acceptance Criteria**:
- Date formatting supports ISO 8601 input with locale-specific output (MM/DD/YYYY, DD.MM.YYYY, etc.)
- Number formatting handles decimal separators (. vs ,) and thousands grouping
- Currency formatting includes symbol placement, decimal precision, and currency code
- Formatting middleware applies transformations based on Accept-Language header
- Timezone conversion is supported via X-Timezone header for date/time properties
- Parse endpoint converts locale-formatted strings back to canonical storage format

**Part of Epic: Schema Localization Engine**

---

#### 1.4 (#1106) — RTL Language Support

RTL Language Support ensures that schema content, documentation, and UI elements render correctly for right-to-left languages including Arabic, Hebrew, Farsi, and Urdu. This affects text direction in schema descriptions, form layouts in the localization editor, and generated documentation. RTL support is applied at the CSS level with logical properties and at the content level with Unicode bidirectional markers.

The RTL implementation adds a `dir="rtl"` attribute and corresponding CSS logical properties when the active locale is an RTL language. Form layouts mirror their field order, text alignment switches from left to right, and icons with directional meaning (arrows, progress indicators) are flipped. Mixed-direction content (e.g., Arabic text with English code snippets) uses Unicode bidirectional isolation marks to prevent layout disruption.

The backend indicates RTL locales in the locale metadata returned by `GET /api/v1/localization/locales`. Each locale record includes an `isRTL` boolean. The NextJS application uses this flag to set the document direction. Generated documentation applies RTL styling when rendering content for RTL locales.

**Acceptance Criteria**:
- RTL locales (ar, he, fa, ur) trigger right-to-left document direction
- CSS logical properties ensure layout mirroring without separate RTL stylesheets
- Mixed-direction content uses Unicode bidi isolation for correct rendering
- Form inputs and labels are properly aligned for RTL locales
- Generated documentation respects RTL direction for RTL locale content
- RTL rendering is tested for Arabic and Hebrew locales with multi-paragraph content

**Part of Epic: Schema Localization Engine**

---

#### 1.5 (#1107) — Locale Management Dashboard

The Locale Management Dashboard provides centralized control over which locales are active in the organization, their configuration, and their translation status. Administrators can add new locales, set the default locale, configure fallback chains (e.g., fr-CA → fr-FR → en-US), and view aggregate translation coverage across all schemas.

The dashboard at `/app/settings/localization` renders a Radix `Table` of active locales with columns for locale code, display name, RTL flag, fallback locale, translation coverage percentage, and status (active, draft). Adding a locale via a Radix `Dialog` requires the BCP 47 code, display name, and fallback configuration. A coverage chart shows organization-wide translation progress per locale.

Backend endpoints include `GET /api/v1/localization/locales` (list), `POST /api/v1/localization/locales` (add), `PUT /api/v1/localization/locales/{code}` (update), and `DELETE /api/v1/localization/locales/{code}` (deactivate). The default locale is set via `PUT /api/v1/localization/settings` with the `default_locale` field. Fallback chains are configured per locale as an ordered array of fallback locale codes.

**Acceptance Criteria**:
- Locale management supports adding, updating, and deactivating locales
- Each locale has a BCP 47 code, display name, RTL flag, and fallback chain
- Default locale is configurable at the organization level
- Fallback chains define ordered locale preferences for missing translations
- Coverage chart shows organization-wide translation progress per locale
- Deactivating a locale hides it from translation editors but preserves existing translations

**Part of Epic: Schema Localization Engine**

---

## Epic 2: AI-Powered Documentation Translation

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1109) | Translation Pipeline | End-to-end pipeline for translating schema documentation | `enhancement`, `localization`, `mvp`, `rest` | Yes |
| 2.2 (#1110) | Translation Memory | Store and reuse approved translations for consistency | `enhancement`, `localization`, `mvp` | Yes |
| 2.3 (#1111) | Glossary Management | Maintain domain-specific term glossaries per locale | `enhancement`, `localization`, `mvp` | Yes |
| 2.4 (#1112) | Human Review Workflows | Review queue for approving AI-generated translations | `enhancement`, `localization`, `mvp` | No |
| 2.5 (#1113) | Batch Translation & Scheduling | Translate entire schemas or projects in batch with scheduling | `enhancement`, `localization` | No |

### Detailed Issue Descriptions

#### 2.1 (#1109) — Translation Pipeline

The Translation Pipeline orchestrates the end-to-end process of translating schema metadata from the source locale to target locales. The pipeline consists of: (1) extracting translatable strings from schema properties, (2) checking translation memory for existing approved translations, (3) applying glossary term substitutions, (4) sending remaining untranslated strings to the AI translation engine, (5) storing results as draft translations pending review.

The pipeline is triggered from the localization editor via a "Translate All" button or per-property "Auto-translate" action. Bulk translation of an entire schema submits a job that processes properties sequentially to maintain context coherence. The AI translation engine uses LLM capabilities with schema-aware prompting—including the property name, type, parent class name, and any related property descriptions for context.

Backend endpoints include `POST /api/v1/localization/translate` (translate specific properties), `POST /api/v1/localization/translate-schema` (bulk translate entire schema), and `GET /api/v1/localization/translate-schema/{jobId}/status` (job progress). The pipeline tracks credit usage per translation request and supports multiple AI backends (configurable). Translations are stored with `status: draft` until human review approves them.

**Acceptance Criteria**:
- Pipeline processes extraction, memory lookup, glossary application, AI translation, and storage
- Schema-aware prompting includes property name, type, and class context for better translations
- Translation memory matches are applied before AI translation to reduce costs
- Glossary terms are substituted in AI translations to ensure domain consistency
- Bulk schema translation runs as an async job with progress tracking
- All AI translations are stored with draft status pending human review

**Part of Epic: AI-Powered Documentation Translation**

---

#### 2.2 (#1110) — Translation Memory

Translation Memory (TM) stores previously approved translations as segment pairs (source text → target text per locale), enabling reuse across schemas. When a new translation request matches an existing TM entry (exact match or fuzzy match above a configurable threshold), the stored translation is used instead of invoking the AI engine. This reduces translation costs and improves consistency.

The TM management page at `/app/settings/localization/translation-memory` displays the TM database as a searchable Radix `Table` with columns for source text, target locale, translated text, match quality (exact, fuzzy with percentage), and approval status. Users can manually add TM entries, edit existing translations, and import/export the TM in TMX (Translation Memory eXchange) format for interoperability with professional translation tools.

Backend endpoints include `GET /api/v1/localization/tm` (search TM), `POST /api/v1/localization/tm` (add entry), `PUT /api/v1/localization/tm/{id}` (edit), `POST /api/v1/localization/tm/import` (import TMX), and `GET /api/v1/localization/tm/export` (export TMX). Fuzzy matching uses Levenshtein distance normalized by string length, with a configurable minimum threshold (default 75%). TM entries are scoped by organization and optionally by project.

**Acceptance Criteria**:
- Exact match TM lookups skip AI translation entirely
- Fuzzy matching identifies similar source texts above a configurable threshold (default 75%)
- TM is searchable by source text, target locale, and approval status
- TMX import/export supports interoperability with professional translation tools
- TM entries are scoped by organization with optional project-level scoping
- Approved translations from the review workflow are automatically added to TM

**Part of Epic: AI-Powered Documentation Translation**

---

#### 2.3 (#1111) — Glossary Management

Glossary Management maintains domain-specific term dictionaries per locale, ensuring that technical terms, product names, and domain vocabulary are translated consistently. Each glossary entry maps a source term to its approved translation in each target locale, with an optional note explaining the translation decision. Glossary terms are enforced during AI translation and flagged during human review.

The glossary editor at `/app/settings/localization/glossary` renders a Radix `Table` of terms with columns for source term, category (technical, product, domain), and translations per active locale. Adding a term via a Radix `Dialog` captures the source term, category, and per-locale translations. Terms can be imported from CSV for bulk setup.

Backend endpoints include `GET /api/v1/localization/glossary` (list with search), `POST /api/v1/localization/glossary` (add term), `PUT /api/v1/localization/glossary/{id}` (update), `DELETE /api/v1/localization/glossary/{id}` (remove), and `POST /api/v1/localization/glossary/import` (import CSV). The glossary is injected into the AI translation prompt as context, and the human review workflow highlights translations that deviate from glossary terms.

**Acceptance Criteria**:
- Glossary entries map source terms to per-locale translations with optional notes
- Terms are categorized (technical, product, domain) for organized management
- AI translation pipeline uses glossary terms as context to enforce consistency
- Human review highlights deviations from glossary terms for reviewer attention
- CSV import supports bulk glossary setup with source term and multi-locale columns
- Glossary is searchable by source term, category, and locale

**Part of Epic: AI-Powered Documentation Translation**

---

#### 2.4 (#1112) — Human Review Workflows

Human Review Workflows provide a queue-based system for reviewing and approving AI-generated translations before they go live. Each draft translation enters the review queue where designated reviewers can approve, reject (with feedback), or edit the translation. Approved translations are promoted to "approved" status and added to the translation memory.

The review queue at `/app/localization/review` renders a filterable Radix `Table` of pending translations with columns for source text, AI translation, target locale, schema, property, and age. Reviewers click a row to open a side panel showing the full context: the source text, AI translation, translation memory matches, glossary terms, and the schema property metadata. Bulk approval supports selecting and approving multiple translations at once.

```
  Translation Review Queue — ja-JP

  ┌──────────────────────────────────────────────────────────────┐
  │ Pending: 47  │  Approved today: 23  │  Rejected: 3          │
  ├──────────────────────────────────────────────────────────────┤
  │                                                              │
  │ Source (en-US)            │ Translation (ja-JP)  │ Actions  │
  │ ─────────────             │ ──────────────────    │ ───────  │
  │ The user's primary email  │ ユーザーのメイン     │ [✓] [✗]  │
  │ address used for login.  │ メールアドレス。     │ [Edit]   │
  │                           │ ログインに使用。     │          │
  │ ─────────────────────────┼──────────────────────┼──────────│
  │ Maximum number of items   │ ページあたりの       │ [✓] [✗]  │
  │ returned per page.       │ 最大アイテム数。     │ [Edit]   │
  │ ─────────────────────────┼──────────────────────┼──────────│
  │ Timestamp when the       │ リソースが作成       │ [✓] [✗]  │
  │ resource was created.    │ されたタイムスタンプ。│ [Edit]   │
  │                           │                      │          │
  │ [Select All]  [Bulk Approve]  Showing 3 of 47    │          │
  └──────────────────────────────────────────────────────────────┘
```

Backend endpoints include `GET /api/v1/localization/review` (list pending), `POST /api/v1/localization/review/{id}/approve` (approve), `POST /api/v1/localization/review/{id}/reject` (reject with feedback), `PUT /api/v1/localization/review/{id}` (edit translation), and `POST /api/v1/localization/review/bulk-approve` (approve multiple). Approved translations update the schema's localization metadata and are automatically added to the translation memory.

**Acceptance Criteria**:
- Review queue lists all pending translations with source, AI translation, and context
- Reviewers can approve, reject (with feedback), or edit each translation
- Approved translations are promoted to live status and added to translation memory
- Rejected translations include feedback visible to the translation pipeline for re-translation
- Bulk approval supports selecting and approving up to 100 translations at once
- Review queue is filterable by locale, schema, age, and priority

**Part of Epic: AI-Powered Documentation Translation**

---

#### 2.5 (#1113) — Batch Translation & Scheduling

Batch Translation & Scheduling enables translating entire schemas, projects, or the full organization's content in a single operation. Scheduled translations run at configured intervals (e.g., weekly) to catch new or modified content and translate it automatically. Batch jobs track progress per schema and per locale with estimated completion times.

The batch translation page at `/app/localization/batch` provides controls for selecting the translation scope (schema, project, or organization), target locales, and translation priority (normal, urgent). Scheduling uses a Radix `Select` for frequency (manual, daily, weekly, monthly) and a time picker for execution time. Active batch jobs display a progress view with per-schema/locale completion bars.

Backend endpoints include `POST /api/v1/localization/batch/translate` (submit batch job), `GET /api/v1/localization/batch/jobs` (list jobs), `GET /api/v1/localization/batch/jobs/{id}` (job detail with progress), and `PUT /api/v1/localization/batch/schedule` (configure scheduled translations). Batch jobs process schemas sequentially, prioritizing schemas with the most untranslated content. Credit consumption is estimated before job submission and tracked during execution.

**Acceptance Criteria**:
- Batch translation supports schema, project, and organization scope levels
- Scheduled translations run at configured intervals to translate new content
- Progress tracking shows completion percentage per schema and per locale
- Credit consumption is estimated before job submission for cost transparency
- Batch jobs can be paused and resumed without losing progress
- Urgent priority batch jobs are processed before normal priority jobs

**Part of Epic: AI-Powered Documentation Translation**

---

## Epic 3: Runtime Response Localization

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1115) | Locale Negotiation Middleware | Content negotiation for selecting response locale | `enhancement`, `localization`, `mvp`, `rest` | Yes |
| 3.2 (#1116) | Response Formatting Middleware | Apply locale-aware formatting to API responses | `enhancement`, `localization`, `mvp`, `rest` | No |
| 3.3 (#1117) | Multi-Language Error Messages | Serve error messages in the consumer's locale | `enhancement`, `localization`, `mvp`, `rest` | Yes |
| 3.4 (#1118) | Timezone Handling | Convert and display timestamps in the consumer's timezone | `enhancement`, `localization`, `rest` | Yes |
| 3.5 (#1119) | Cultural Adaptation Rules | Apply locale-specific business rules and display conventions | `enhancement`, `localization` | No |

### Detailed Issue Descriptions

#### 3.1 (#1115) — Locale Negotiation Middleware

The Locale Negotiation Middleware determines the consumer's preferred locale for each API request and propagates it through the request context. The middleware evaluates locale sources in priority order: (1) explicit `locale` query parameter, (2) `Accept-Language` HTTP header, (3) user profile locale preference (for authenticated requests), (4) organization default locale. The resolved locale is set on the request context and available to all downstream handlers.

The middleware parses the `Accept-Language` header per RFC 7231, handling quality values (`q=`) and wildcard preferences. When the preferred locale is not available, the fallback chain (configured in the locale management dashboard) determines the next best match. The resolved locale and the fallback chain used are included in the response headers: `Content-Language` (locale used) and `X-Available-Locales` (list of available locales for the requested resource).

The middleware is implemented as a NextJS middleware at `/middleware.ts` for UI routes and as API route middleware for REST endpoints. Configuration includes which routes are locale-aware (default: all), the fallback behavior (closest match vs. default locale), and whether to return 406 Not Acceptable when no matching locale is found. The middleware is registered via `PUT /api/v1/localization/settings` with the `negotiation_config` object.

**Acceptance Criteria**:
- Locale is resolved from query parameter, Accept-Language header, user profile, or default (in priority order)
- Accept-Language header parsing follows RFC 7231 with quality value support
- Fallback chain is applied when the preferred locale is not available
- Response includes Content-Language header indicating the locale used
- Locale negotiation adds less than 5ms to request processing time
- 406 Not Acceptable is returned when strict mode is enabled and no matching locale exists

**Part of Epic: Runtime Response Localization**

---

#### 3.2 (#1116) — Response Formatting Middleware

The Response Formatting Middleware transforms API response payloads to apply locale-specific formatting to dates, numbers, currencies, and other format-sensitive fields. The middleware intercepts outgoing responses, identifies format-sensitive properties (as configured in the schema formatting settings), and applies the appropriate ICU formatting for the negotiated locale.

The middleware operates as a response transformer that walks the response JSON, matching property paths against the format configuration. For date fields, it converts ISO 8601 strings to the locale's date format. For number fields, it applies the locale's decimal separator and grouping convention. For currency fields, it formats with the locale's currency symbol placement and decimal precision. The original (canonical) values are preserved in an `X-Original-Values` header or a `_meta` response key for consumers that need raw data.

The middleware is configurable per schema via the format configuration and per API route via `PUT /api/v1/localization/formatting-config`. Formatting can be disabled per request via the `X-Raw-Response: true` header for consumers that handle formatting client-side. The OpenAPI spec documents the formatted response shapes for each locale.

**Acceptance Criteria**:
- Date fields are formatted per locale conventions (MM/DD/YYYY, DD.MM.YYYY, etc.)
- Number fields use locale-appropriate decimal separators and thousands grouping
- Currency fields include locale-appropriate symbol placement and precision
- Original canonical values are preserved via response metadata for raw access
- X-Raw-Response header bypasses formatting for consumers that format client-side
- Formatting middleware adds less than 10ms to response processing time

**Part of Epic: Runtime Response Localization**

---

#### 3.3 (#1117) — Multi-Language Error Messages

Multi-Language Error Messages serve API error responses in the consumer's negotiated locale. Every error message (validation errors, authorization errors, not-found errors, server errors) is translatable through the localization system. Error messages are stored as ICU MessageFormat templates supporting variable interpolation (field names, values, constraints).

The error message registry at `/app/settings/localization/errors` renders a Radix `Table` of error codes with their message templates per locale. Each error code has a default (en-US) message and optional translations for active locales. Message templates use ICU MessageFormat syntax for variable interpolation: `"Field {field} must be at least {min} characters"` becomes `"フィールド {field} は少なくとも {min} 文字必要です"` in ja-JP.

Backend endpoints include `GET /api/v1/localization/error-messages` (list), `PUT /api/v1/localization/error-messages/{code}` (update translations), and `POST /api/v1/localization/error-messages/import` (bulk import). The error handler middleware resolves messages based on the negotiated locale and interpolates variables from the error context. Missing translations fall back to the default locale message.

**Acceptance Criteria**:
- Error messages are translatable per locale with ICU MessageFormat template support
- Variable interpolation inserts field names, values, and constraints into localized messages
- Error response includes the error code, localized message, and the locale used
- Missing translations fall back to the default locale message
- Error message registry supports bulk import from JSON or CSV
- All standard error codes (validation, auth, not-found, server) have translatable templates

**Part of Epic: Runtime Response Localization**

---

#### 3.4 (#1118) — Timezone Handling

Timezone Handling provides automatic timezone conversion for date/time fields in API responses and intelligent timezone parsing for incoming requests. All dates are stored internally in UTC. The consumer's timezone is determined from the `X-Timezone` header (IANA timezone identifier, e.g., `America/New_York`, `Asia/Tokyo`) or from the user profile's timezone setting.

Outgoing responses convert UTC timestamps to the consumer's timezone with the timezone offset appended (e.g., `2026-04-02T14:30:00-04:00`). Incoming requests parse timezone-aware timestamps and convert to UTC for storage. The middleware handles daylight saving time transitions correctly using the IANA timezone database. Date-only fields (without time components) are not converted, as they represent calendar dates rather than instants.

Backend endpoints include `PUT /api/v1/localization/timezone-config` (configure timezone behavior) and `GET /api/v1/localization/timezones` (list supported IANA timezone identifiers). The configuration controls whether timezone conversion is applied automatically or only when the `X-Timezone` header is present, and whether the UTC offset is included in formatted dates.

**Acceptance Criteria**:
- UTC timestamps are converted to the consumer's timezone in outgoing responses
- Timezone is determined from X-Timezone header or user profile preference
- Daylight saving time transitions are handled correctly per IANA timezone database
- Date-only fields are not converted (calendar dates are timezone-agnostic)
- Incoming timezone-aware timestamps are normalized to UTC for storage
- Timezone conversion adds less than 2ms to response processing time

**Part of Epic: Runtime Response Localization**

---

#### 3.5 (#1119) — Cultural Adaptation Rules

Cultural Adaptation Rules apply locale-specific conventions beyond formatting—name order (given name first vs. family name first), address format (street → city → state vs. postal code → prefecture → city → street), measurement units (metric vs. imperial), and calendar system preferences (Gregorian vs. Japanese era calendar). These rules are configurable per locale and applied to API responses containing structured data with cultural sensitivity.

The adaptation rule editor at `/app/settings/localization/cultural-rules` defines transformation rules per locale. Each rule targets a data pattern (person name, postal address, measurement) and specifies the transformation (field reordering, unit conversion, calendar conversion). Rules are evaluated during response formatting alongside the format handling engine.

Backend endpoints include `GET /api/v1/localization/cultural-rules` (list), `POST /api/v1/localization/cultural-rules` (create), and `PUT /api/v1/localization/cultural-rules/{id}` (update). Cultural rules are stored as transformation definitions with `locale_pattern`, `data_pattern`, `transformation` (JSONB specifying the field mapping and conversion functions). A test endpoint `POST /api/v1/localization/cultural-rules/preview` applies rules to sample data for verification.

**Acceptance Criteria**:
- Name ordering adapts to locale conventions (given-family vs. family-given)
- Address formatting reorders fields per locale postal conventions
- Measurement conversion supports metric/imperial switching per locale
- Rules are evaluated during response formatting based on negotiated locale
- Preview endpoint demonstrates rule application on sample data
- Rules are optional and only applied when explicitly configured for a locale

**Part of Epic: Runtime Response Localization**

---

## Epic 4: Internationalization Testing & Coverage

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#1121) | i18n Compliance Scanner | Scan schemas and APIs for internationalization issues | `enhancement`, `localization`, `mvp`, `rest` | Yes |
| 4.2 (#1122) | Character Encoding Validation | Verify correct handling of Unicode, multi-byte, and special characters | `enhancement`, `localization`, `rest` | Yes |
| 4.3 (#1123) | Translation Coverage Reports | Generate reports showing translation completeness by locale | `enhancement`, `localization`, `mvp` | Yes |
| 4.4 (#1124) | Missing Translation Detection | Real-time detection and alerting for missing translations | `enhancement`, `localization` | No |
| 4.5 (#1125) | i18n Test Suite Generator | Generate automated test cases for internationalization validation | `enhancement`, `localization` | No |

### Detailed Issue Descriptions

#### 4.1 (#1121) — i18n Compliance Scanner

The i18n Compliance Scanner analyzes schemas, API definitions, and stored data for internationalization issues. The scanner checks for: hardcoded English text in enum values, date/time fields without timezone information, string fields without max-length constraints (which can cause UI overflow with longer translations), numeric fields storing formatted strings instead of raw numbers, and properties using locale-specific patterns (e.g., US phone regex) without locale qualification.

The scanner page at `/app/localization/compliance` renders scan results as a prioritized list of issues grouped by severity (error, warning, info). Each issue includes the affected schema, property path, issue description, and a suggested fix. The scanner runs on-demand or can be scheduled to run nightly. Historical scan results are retained for trend analysis.

```
  i18n Compliance — Schema Scan Results

  ┌─────┬──────────────┬───────────────────────────────┬──────────┐
  │ Sev │ Schema       │ Issue                         │ Property │
  ├─────┼──────────────┼───────────────────────────────┼──────────┤
  │ ERR │ UserProfile  │ Hardcoded phone regex assumes │ phone    │
  │     │              │ US format (+1-XXX-XXX-XXXX)   │          │
  ├─────┼──────────────┼───────────────────────────────┼──────────┤
  │ ERR │ Order        │ Date field without timezone   │ orderDate│
  │     │              │ format specification          │          │
  ├─────┼──────────────┼───────────────────────────────┼──────────┤
  │ WRN │ Product      │ description field has no      │ desc     │
  │     │              │ maxLength (translation may    │          │
  │     │              │ overflow UI)                  │          │
  ├─────┼──────────────┼───────────────────────────────┼──────────┤
  │ WRN │ Invoice      │ amount stored as formatted    │ total    │
  │     │              │ string instead of number      │          │
  ├─────┼──────────────┼───────────────────────────────┼──────────┤
  │ INF │ Category     │ Enum values use English       │ type     │
  │     │              │ labels (consider using codes)  │          │
  └─────┴──────────────┴───────────────────────────────┴──────────┘

  Summary: 2 errors │ 2 warnings │ 1 info  │ 15 schemas scanned
```

Backend endpoints include `POST /api/v1/localization/compliance/scan` (trigger scan), `GET /api/v1/localization/compliance/results` (latest results), and `GET /api/v1/localization/compliance/history` (historical trend). The scanner rule engine is extensible—custom rules can be added via `POST /api/v1/localization/compliance/rules`. Each rule defines a check function, severity, and suggested fix template.

**Acceptance Criteria**:
- Scanner detects hardcoded locale-specific patterns, timezone-less dates, and missing length constraints
- Issues are classified by severity (error, warning, info) with suggested fixes
- On-demand and scheduled scanning modes are supported
- Historical scan results enable trend analysis over time
- Custom rules can extend the default rule set
- Scanner completes within 60 seconds for organizations with up to 500 schemas

**Part of Epic: Internationalization Testing & Coverage**

---

#### 4.2 (#1122) — Character Encoding Validation

Character Encoding Validation verifies that schemas, APIs, and data storage correctly handle Unicode characters, multi-byte sequences, emoji, combining characters, and special Unicode categories. The validator sends test payloads containing challenging character sequences through the API pipeline and verifies that responses preserve character fidelity.

The validation suite covers: CJK characters (Chinese, Japanese, Korean ideographs), Arabic/Hebrew script with bidirectional marks, Cyrillic characters, accented Latin characters (é, ü, ñ), emoji (including multi-codepoint sequences like family emoji), zero-width characters, and supplementary plane characters (U+10000+). For each test case, the validator compares input against output at the byte level to detect encoding issues, truncation, or replacement characters (U+FFFD).

Backend endpoints include `POST /api/v1/localization/encoding/validate` (run validation suite against a schema's API endpoints) and `GET /api/v1/localization/encoding/results/{id}` (retrieve validation results). The validation page at `/app/localization/encoding` shows test results as a pass/fail matrix with character categories as rows and API endpoints as columns.

**Acceptance Criteria**:
- Validation covers CJK, Arabic, Cyrillic, accented Latin, emoji, and supplementary plane characters
- Byte-level comparison detects encoding loss, truncation, and replacement characters
- Pass/fail matrix shows results by character category and API endpoint
- Validation runs against live API endpoints with test payloads
- Results identify the exact character sequences that failed and the failure mode
- Validation suite is extensible with custom character test cases

**Part of Epic: Internationalization Testing & Coverage**

---

#### 4.3 (#1123) — Translation Coverage Reports

Translation Coverage Reports generate comprehensive views of translation completeness across the organization. Reports show coverage percentages by locale, schema, project, and property category (titles, descriptions, examples, error messages). Gap analysis identifies the highest-impact untranslated content based on API request volume and consumer locale distribution.

The reports page at `/app/localization/coverage` renders a matrix of schemas (rows) vs. locales (columns) with percentage values color-coded from red (0%) to green (100%). Clicking a cell drills down to show the specific untranslated properties. A priority-weighted view reorders schemas by impact (request volume × gap size) to focus translation efforts where they matter most.

Backend endpoints include `GET /api/v1/localization/coverage` (organization-wide coverage matrix), `GET /api/v1/localization/coverage/{schemaId}` (per-schema detail), and `GET /api/v1/localization/coverage/priorities` (impact-weighted priority list). Reports are exportable as CSV and PDF via `GET /api/v1/localization/coverage/export?format={csv|pdf}`. Coverage data is recalculated hourly and cached for fast retrieval.

**Acceptance Criteria**:
- Coverage matrix shows translation percentages by schema and locale
- Color coding ranges from red (0%) through yellow (50%) to green (100%)
- Drill-down shows specific untranslated properties for a schema/locale combination
- Priority-weighted view orders schemas by impact for focused translation effort
- Reports are exportable as CSV and PDF
- Coverage data is refreshed hourly and reflects the latest translation approvals

**Part of Epic: Internationalization Testing & Coverage**

---

#### 4.4 (#1124) — Missing Translation Detection

Missing Translation Detection provides real-time monitoring for translation gaps in production. When an API response requires a localized string that has no approved translation for the requested locale, the system logs a missing translation event with the property path, requested locale, and fallback locale used. Accumulated missing translation events surface as alerts on the localization dashboard.

The detection system operates as an observer in the locale negotiation middleware. When a fallback is used (requested locale unavailable, falling back to parent or default), the event is logged to a `missing_translations` table with `schema_id`, `property_path`, `requested_locale`, `fallback_locale`, `request_count` (incremented), and `first_seen`/`last_seen` timestamps. Alerts fire when a missing translation accumulates above a configurable request threshold.

The missing translations page at `/app/localization/missing` renders a Radix `Table` sorted by request count (most-requested first). Each row shows the property, requested locale, fallback used, request count, and a "Translate Now" action that opens the localization editor pre-focused on that property and locale. Alert configuration is managed via `PUT /api/v1/localization/missing-alerts` with threshold and notification channel settings.

**Acceptance Criteria**:
- Missing translation events are logged when fallback locales are used in production
- Events are aggregated by property and locale with request counts and timestamps
- Alert fires when missing translations exceed configurable request count threshold
- Missing translations are sorted by request count to prioritize high-impact gaps
- "Translate Now" action opens the localization editor pre-focused on the missing translation
- Missing translation detection adds less than 1ms to request processing time

**Part of Epic: Internationalization Testing & Coverage**

---

#### 4.5 (#1125) — i18n Test Suite Generator

The i18n Test Suite Generator creates automated test cases that validate internationalization correctness for schemas and APIs. Generated tests cover: response locale matches the requested locale, formatted values match locale conventions, character encoding is preserved, RTL content is properly marked, error messages are translated, and timezone conversion is accurate.

The test generator at `/app/localization/testing` allows selecting schemas and locales to test, then generates a test suite in the chosen format (Jest/TypeScript, pytest/Python, or Postman collection). Each test case includes the expected behavior, test data, and assertions. The test suite can be downloaded and integrated into CI/CD pipelines for ongoing validation.

Backend endpoints include `POST /api/v1/localization/testing/generate` (generate test suite with format and scope parameters) and `GET /api/v1/localization/testing/download/{id}` (download generated suite). The generator uses the schema definitions, locale configurations, and formatting rules to produce comprehensive tests. Test cases are parameterized by locale to run the same assertions across all active locales.

**Acceptance Criteria**:
- Test suites are generated in Jest/TypeScript, pytest/Python, and Postman collection formats
- Tests cover locale negotiation, formatting, encoding, RTL, error messages, and timezones
- Test cases are parameterized by locale for cross-locale validation
- Generated tests include test data, expected results, and descriptive assertions
- Test suites are downloadable and runnable in CI/CD pipelines
- Test generation covers all format-sensitive properties configured for the selected schemas

**Part of Epic: Internationalization Testing & Coverage**

---

## Parallel Work Guide

**Epic 1 — Schema Localization Engine**:
Issues 1.1 (Multi-Language Metadata), 1.2 (Locale-Specific Validation), 1.3 (Format Handling), and 1.5 (Locale Management Dashboard) can be developed in parallel as they address independent aspects of the localization infrastructure. Issue 1.4 (RTL Support) depends on 1.1 for multi-language content rendering and 1.5 for locale RTL flag metadata.

**Epic 2 — AI-Powered Documentation Translation**:
Issues 2.1 (Translation Pipeline), 2.2 (Translation Memory), and 2.3 (Glossary Management) can be developed in parallel. Issue 2.4 (Human Review Workflows) depends on 2.1 for draft translations to review and 2.2 for TM integration on approval. Issue 2.5 (Batch Translation) depends on 2.1 for the translation pipeline and 2.4 for the review workflow.

**Epic 3 — Runtime Response Localization**:
Issues 3.1 (Locale Negotiation), 3.3 (Error Messages), and 3.4 (Timezone Handling) can be developed in parallel as they handle independent aspects of request/response processing. Issue 3.2 (Response Formatting) depends on 3.1 for the negotiated locale context. Issue 3.5 (Cultural Adaptation) depends on 3.1 and 3.2.

**Epic 4 — Internationalization Testing & Coverage**:
Issues 4.1 (Compliance Scanner), 4.2 (Encoding Validation), and 4.3 (Coverage Reports) can be developed in parallel. Issue 4.4 (Missing Translation Detection) depends on Epic 3's locale negotiation middleware for detection hooks. Issue 4.5 (Test Suite Generator) depends on 4.1 for compliance rules and Epic 1 for schema localization data.

**Cross-Epic Parallelism**: Epics 1 (Schema Localization) and 3 (Runtime Localization) can begin simultaneously as they operate at different layers (data vs. runtime). Epic 2 (Translation) depends on Epic 1 for schema metadata to translate. Epic 4 (Testing) can begin once Epics 1 and 3 have initial implementations to test against. Within each epic, the parallel work guides above identify the maximum concurrency.
