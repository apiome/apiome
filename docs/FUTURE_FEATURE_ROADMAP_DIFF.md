# Objectified: Diff (Schema Comparison) - Feature Roadmap

> Advanced schema comparison and migration planning for complex schema evolution scenarios. Diff provides visual side-by-side comparison, automated breaking change detection, consumer impact analysis, migration script generation, and cross-project schema archaeology—enabling teams to evolve schemas confidently and understand the full history of why changes were made.
>
> **Revenue Model**: Included in Studio, advanced features (cross-project comparison, migration scripting) in enterprise tier
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, JSON Schema diff engine, PostgreSQL for version history, Canvas API for visual rendering
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Side-by-side diff view comparing two schema versions with property-level highlighting
- Breaking change auto-detection with severity classification (breaking, non-breaking, info)
- Consumer impact report showing which API consumers are affected by schema changes
- Backward compatibility score (0–100) computed from change analysis
- Migration guide generation with step-by-step instructions for consumers
- Schema version timeline showing the evolution history of a schema
- Cross-project schema comparison for identifying duplication

---

## Epic 1: Visual Diff Engine

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1006) | Schema Diff Algorithm | Core diffing engine for JSON Schema comparison | `enhancement`, `diff`, `mvp`, `rest` | Yes |
| 1.2 (#1007) | Side-by-Side Diff Renderer | Visual side-by-side view with property-level highlighting | `enhancement`, `diff`, `mvp` | No |
| 1.3 (#1008) | Relationship Change Visualization | Visualize changes to schema relationships and references | `enhancement`, `diff` | No |
| 1.4 (#1009) | Diff Permalink & Sharing | Shareable URLs for specific diff comparisons | `enhancement`, `diff` | Yes |
| 1.5 (#1010) | Inline Annotation & Comments | Comment on specific diff lines for review discussions | `enhancement`, `diff` | No |

### Detailed Issue Descriptions

#### 1.1 (#1006) — Schema Diff Algorithm

The Schema Diff Algorithm is the core computation engine that compares two JSON Schema documents and produces a structured diff result. The algorithm operates at the property level, identifying additions, removals, modifications, and moves across the schema tree. For each change, the algorithm classifies the semantic impact: adding a required property is breaking, adding an optional property is non-breaking, changing a type is breaking, widening an enum is non-breaking while narrowing is breaking.

The diff engine handles JSON Schema composition operators (`allOf`, `anyOf`, `oneOf`, `$ref`), resolving references before comparison. For nested objects, the diff recurses into child properties, producing a tree-structured result where each node contains the change type, path (JSON Pointer), old value, new value, and impact classification. Array item schema changes are tracked separately from array constraint changes (minItems, maxItems, uniqueItems).

The REST API exposes `POST /api/v1/diff/compare` accepting `source_schema_id` and `target_schema_id` (schema capture IDs or version IDs) and returning the structured diff result. A batch endpoint `POST /api/v1/diff/compare-batch` accepts multiple comparison pairs for bulk analysis. The diff result conforms to a `SchemaDiff` schema in the OpenAPI spec with `changes[]` containing `path`, `type` (added/removed/modified/moved), `old_value`, `new_value`, `impact` (breaking/non-breaking/info), and `description`.

```
  Schema v1.2                          Schema v1.3
  ┌────────────────────┐               ┌────────────────────┐
  │ User               │               │ User               │
  │  ├─ id: uuid       │    unchanged  │  ├─ id: uuid       │
  │  ├─ name: string   │──────────────►│  ├─ name: string   │
  │  ├─ email: string  │    unchanged  │  ├─ email: string  │
  │  ├─ age: integer   │──── removed ──│                    │
  │  │                 │               │  ├─ birthDate: date │◄── added
  │  ├─ role: enum     │── modified ──►│  ├─ role: enum     │
  │  │  [admin, user]  │               │  │  [admin,user,mod]│
  │  └─ active: bool   │    unchanged  │  └─ active: bool   │
  └────────────────────┘               └────────────────────┘

  Diff Result:
  ┌──────────────────────────────────────────────────────────┐
  │ - REMOVED  /properties/age        (breaking)             │
  │ + ADDED    /properties/birthDate  (non-breaking, optional)│
  │ ~ MODIFIED /properties/role/enum  (non-breaking, widened) │
  └──────────────────────────────────────────────────────────┘
```

**Acceptance Criteria**:
- Diff identifies additions, removals, modifications, and moves at the property level
- Impact classification distinguishes breaking, non-breaking, and informational changes
- `$ref` resolution, `allOf`/`anyOf`/`oneOf` composition is handled before comparison
- Diff result includes JSON Pointer paths for each change with old and new values
- Batch comparison endpoint supports up to 50 comparison pairs in a single request
- Diff computation completes within 2 seconds for schemas with up to 500 properties

**Part of Epic: Visual Diff Engine**

---

#### 1.2 (#1007) — Side-by-Side Diff Renderer

The Side-by-Side Diff Renderer presents the diff result as a visual comparison at `/app/diff/[comparisonId]`. The left panel shows the source schema and the right panel shows the target schema, with synchronized scrolling. Changed properties are highlighted: green for additions, red for removals, yellow for modifications. Unchanged properties are dimmed to focus attention on changes.

The renderer uses Radix `Tabs` to switch between three views: "Properties" (property-level diff), "Raw JSON" (raw JSON Schema diff with syntax highlighting), and "Summary" (aggregated change counts and impact assessment). The property view renders each schema class as a collapsible tree (Radix `Accordion`) with change indicators on each node. A floating change navigator allows jumping between changes with keyboard shortcuts (J/K for next/previous).

The version selector at the top uses two Radix `Select` dropdowns for choosing the source and target versions. A "Swap" button reverses the comparison direction. The URL structure `/app/diff?source={id}&target={id}` supports deep linking to specific comparisons. The diff page is also accessible from the schema version history via "Compare with..." context menu actions.

**Acceptance Criteria**:
- Side-by-side panels display source and target schemas with synchronized scrolling
- Additions (green), removals (red), and modifications (yellow) are color-highlighted
- Three view modes: property tree, raw JSON, and summary with change counts
- Change navigator enables jumping between changes with J/K keyboard shortcuts
- Version selectors allow comparing any two versions of the same schema
- Deep linking via URL parameters supports sharing specific comparisons

**Part of Epic: Visual Diff Engine**

---

#### 1.3 (#1008) — Relationship Change Visualization

Relationship Change Visualization extends the diff engine to show how schema relationships (`$ref` references, `link_def` entries) have changed between versions. Relationship changes are visualized as a before/after graph where nodes are schema classes and edges are relationships. Added relationships are shown as green dashed edges, removed relationships as red strikethrough edges, and unchanged relationships as solid gray edges.

The relationship diff view is accessible from the diff page as an additional Radix `Tabs` panel labeled "Relationships." The graph is rendered using an interactive canvas with zoom and pan. Selecting a changed relationship edge displays the change details in a side panel: the old and new cardinality, cascade behavior, and any property-level changes in the referenced schema.

The backend extends the diff result with a `relationship_changes` array in the `POST /api/v1/diff/compare` response. Each relationship change includes `source_class`, `target_class`, `change_type` (added/removed/modified), `old_relationship` (cardinality, cascade), and `new_relationship`. The relationship diff algorithm compares `$ref` targets and `link_def` entries between the two schema versions.

**Acceptance Criteria**:
- Relationship changes are visualized as a before/after graph with color-coded edges
- Added relationships display as green dashed edges; removed as red strikethrough
- Selecting a changed edge shows cardinality and cascade behavior changes
- Graph supports zoom, pan, and node selection interactions
- Relationship diff covers `$ref` references and `link_def` entries
- Circular relationships are rendered without layout issues

**Part of Epic: Visual Diff Engine**

---

#### 1.4 (#1009) — Diff Permalink & Sharing

Diff Permalink & Sharing generates permanent, shareable URLs for specific schema comparisons. Each comparison is assigned a unique ID and persisted, enabling team members to reference a specific diff in code reviews, Slack messages, and documentation without the comparison being recalculated or changing if schemas are further modified.

Permalinks are generated via a "Share" button on the diff page that copies the URL to the clipboard with a Radix `Toast` confirmation. The permalink URL follows the pattern `/app/diff/saved/[permalinkId]`. Permalink metadata includes the creator, creation date, source and target schema versions (frozen references), and an optional title and description added via a Radix `Dialog` when saving.

Backend endpoints include `POST /api/v1/diff/permalinks` (create permalink from a comparison), `GET /api/v1/diff/permalinks/{id}` (retrieve), and `GET /api/v1/diff/permalinks` (list user's saved comparisons). The `diff_permalinks` table stores `source_schema_id`, `target_schema_id`, `diff_result` (cached JSONB), `created_by`, `title`, and `description`. Permalinks are retained indefinitely and reference immutable schema captures.

**Acceptance Criteria**:
- Share button generates a permalink URL and copies it to the clipboard
- Permalinks reference frozen schema versions and do not change over time
- Permalink metadata includes title, description, and creator
- List endpoint returns the user's saved comparisons with search and pagination
- Permalinks render the same diff view as live comparisons
- Permalink URLs are accessible by any authenticated user in the organization

**Part of Epic: Visual Diff Engine**

---

#### 1.5 (#1010) — Inline Annotation & Comments

Inline Annotation & Comments enable team members to discuss specific changes directly on the diff view. Each diff line (property change) can have a comment thread attached, similar to code review tools. Comments support markdown formatting and @mentions for notifying specific team members.

Clicking the gutter area next to a change opens a comment form rendered as a Radix `Popover`. Existing comments display as badges on the diff line showing the comment count. Clicking the badge opens the full thread. Comment notifications are delivered via the existing notification system (in-app + email).

Backend endpoints include `POST /api/v1/diff/permalinks/{id}/comments` (add comment), `GET /api/v1/diff/permalinks/{id}/comments` (list all comments), and `DELETE /api/v1/diff/permalinks/{id}/comments/{commentId}` (delete own comment). Comments are linked to specific diff paths (JSON Pointer) so they remain anchored to the correct change even if the diff is viewed at different zoom levels or view modes.

**Acceptance Criteria**:
- Comments can be attached to specific diff lines identified by JSON Pointer path
- Comment threads support multiple replies with markdown formatting
- @mentions trigger notifications to the mentioned users
- Comment count badges appear on diff lines with existing comments
- Comments are anchored to diff paths and persist across view mode changes
- Only the comment author or an admin can delete a comment

**Part of Epic: Visual Diff Engine**

---

## Epic 2: Breaking Change Detection & Impact Analysis

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1012) | Breaking Change Classifier | Classify schema changes by breaking impact severity | `enhancement`, `diff`, `mvp`, `rest` | Yes |
| 2.2 (#1013) | Consumer Impact Report | Identify API consumers affected by breaking changes | `enhancement`, `diff`, `mvp` | No |
| 2.3 (#1014) | Backward Compatibility Scoring | Compute a compatibility score for schema transitions | `enhancement`, `diff`, `mvp` | Yes |
| 2.4 (#1015) | Mitigation Suggestions | Auto-generate strategies to reduce breaking change impact | `enhancement`, `diff`, `ai-generated` | No |
| 2.5 (#1016) | Pre-Publish Change Gate | Block schema publication if breaking changes exceed threshold | `enhancement`, `diff`, `rest` | No |

### Detailed Issue Descriptions

#### 2.1 (#1012) — Breaking Change Classifier

The Breaking Change Classifier extends the diff algorithm with a comprehensive ruleset for classifying schema changes by their impact on API consumers. The classifier evaluates each change against a rule table that maps change patterns to severity levels. Rules cover type changes (breaking), required field additions (breaking), optional field additions (non-breaking), enum narrowing (breaking), enum widening (non-breaking), constraint tightening (breaking), constraint relaxing (non-breaking), and description-only changes (info).

The classifier supports custom rules defined per organization to handle domain-specific breaking change semantics. For example, an organization might classify renaming a field as breaking even though it technically appears as a remove+add. Custom rules are managed via `POST /api/v1/diff/breaking-rules` and stored in a `breaking_change_rules` table with `pattern` (JSON expression), `severity`, and `description` fields.

The classification result enriches the diff output with a `breaking_changes` summary containing counts by severity, a list of all breaking changes with their paths and descriptions, and an overall assessment (safe to publish, review recommended, publication blocked). The API endpoint `POST /api/v1/diff/classify` accepts a diff result and returns the classified output.

**Acceptance Criteria**:
- Default ruleset covers type changes, required fields, enum changes, and constraint modifications
- Each breaking change includes path, description, severity, and affected property details
- Custom rules can override or extend the default ruleset per organization
- Classification summary includes counts by severity and an overall assessment
- Classifier handles nested schema changes and composition operator changes
- Classification adds less than 100ms to the diff computation time

**Part of Epic: Breaking Change Detection & Impact Analysis**

---

#### 2.2 (#1013) — Consumer Impact Report

The Consumer Impact Report identifies which API consumers will be affected by schema changes and quantifies the impact. The report cross-references breaking changes with consumer usage data—API request logs, SDK version distributions, and active contract references—to determine which consumers call affected endpoints and which response fields they access.

The impact report page at `/app/diff/[comparisonId]/impact` renders a Radix `Table` listing affected consumers with columns for consumer name, affected endpoints, estimated request volume impacted, SDK version, and remediation status (not started, in progress, complete). Clicking a consumer row expands to show the specific breaking changes that affect them and whether their SDK version handles the change.

The backend provides `POST /api/v1/diff/impact` accepting a diff result and returning the consumer impact analysis. The `consumer_usage` data is sourced from API analytics (if available) or from contract registrations. If no usage data is available, the report falls back to listing all known consumers without impact quantification.

**Acceptance Criteria**:
- Report identifies consumers affected by each breaking change
- Consumer rows show name, affected endpoints, impacted request volume, and SDK version
- Impact quantification shows estimated percentage of consumer requests affected
- Fallback mode lists all known consumers when usage data is unavailable
- Report is exportable as CSV for distribution to consumer teams
- Impact report generates within 10 seconds for schemas with up to 100 consumers

**Part of Epic: Breaking Change Detection & Impact Analysis**

---

#### 2.3 (#1014) — Backward Compatibility Scoring

Backward Compatibility Scoring computes a numeric score (0–100) representing how compatible a schema change is with existing consumers. A score of 100 means no breaking changes; 0 means a complete rewrite. The score is computed from weighted factors: number of breaking changes, severity of each change, percentage of properties affected, and consumer impact breadth.

The score is displayed prominently on the diff page as a large gauge component with color coding (green: 80–100, yellow: 50–79, red: 0–49). Historical scores are tracked per schema version pair, enabling trend analysis of how compatibility evolves over time. A chart on the schema detail page shows the compatibility score for each version transition.

The REST API includes the compatibility score in the `POST /api/v1/diff/compare` response and provides `GET /api/v1/schemas/{id}/compatibility-history` for the historical trend. Score weights are configurable per organization via `PUT /api/v1/diff/score-weights`. The OpenAPI spec defines the `CompatibilityScore` schema with `overall`, `breaking_count`, `non_breaking_count`, `affected_percentage`, and `consumer_impact` sub-scores.

**Acceptance Criteria**:
- Score ranges from 0 (incompatible) to 100 (fully compatible) with clear color coding
- Weighted factors include breaking change count, severity, property coverage, and consumer impact
- Score weights are configurable per organization
- Historical scores are tracked per schema version transition
- Compatibility trend chart is available on the schema detail page
- Score calculation is deterministic for the same diff result and weight configuration

**Part of Epic: Breaking Change Detection & Impact Analysis**

---

#### 2.4 (#1015) — Mitigation Suggestions

Mitigation Suggestions automatically generate strategies to reduce the impact of breaking changes. For each breaking change, the system suggests one or more mitigation approaches: deprecation with sunset period (mark old field as deprecated, keep it for N versions), versioned endpoint (create v2 endpoint while maintaining v1), default value injection (add a default value to the new required field), field aliasing (serve the old field name alongside the new one), or consumer-specific feature flags.

Suggestions are displayed on the diff page as expandable cards attached to each breaking change. Each suggestion includes the approach name, a description of the implementation steps, estimated consumer impact reduction, and a "complexity" indicator (low/medium/high). AI-powered suggestions (labeled `ai-generated`) provide more nuanced recommendations considering the specific schema context and consumer patterns.

The backend provides suggestions via the `POST /api/v1/diff/mitigations` endpoint accepting a diff result with breaking changes and returning mitigation options. AI-generated suggestions use LLM analysis of the schema context and are cached by diff hash. The `mitigation_templates` table stores reusable mitigation patterns that can be customized per organization.

**Acceptance Criteria**:
- At least 5 mitigation strategies are available: deprecation, versioning, defaults, aliasing, feature flags
- Each suggestion includes implementation steps, estimated impact reduction, and complexity
- AI-generated suggestions consider schema context and consumer patterns
- Suggestions are attached to specific breaking changes on the diff page
- Mitigation templates are customizable per organization
- Suggestions are cached by diff hash to avoid redundant computation

**Part of Epic: Breaking Change Detection & Impact Analysis**

---

#### 2.5 (#1016) — Pre-Publish Change Gate

The Pre-Publish Change Gate integrates breaking change detection into the schema publication workflow, optionally blocking publication when breaking changes exceed configurable thresholds. The gate evaluates the diff between the current published version and the proposed new version, and either allows publication, requires explicit acknowledgment of breaking changes, or blocks publication entirely.

Gate configuration at `/app/settings/diff/publish-gate` uses Radix `RadioGroup` for gate mode (disabled, warn, block) and number inputs for thresholds. In "warn" mode, users see a Radix `AlertDialog` listing all breaking changes and must check a confirmation box before proceeding. In "block" mode, publication is prevented until the compatibility score exceeds the configured minimum (e.g., 80).

The backend gate check is performed during schema publication via a middleware that calls `POST /api/v1/diff/gate-check` with the proposed and current schema versions. The gate returns `{ allowed: boolean, warnings: [], blocks: [], compatibility_score: number }`. Gate configuration is stored in organizational settings via `PUT /api/v1/settings/diff/publish-gate`.

**Acceptance Criteria**:
- Gate modes include disabled (no check), warn (show + confirm), and block (prevent publication)
- Block mode prevents publication when compatibility score is below the configured threshold
- Warn mode displays all breaking changes and requires explicit confirmation
- Gate check is performed automatically during the schema publication workflow
- Gate configuration is managed at the organization level
- Gate check adds less than 3 seconds to the publication workflow

**Part of Epic: Breaking Change Detection & Impact Analysis**

---

## Epic 3: Migration Planning & Script Generation

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1018) | Migration Guide Generator | Generate step-by-step migration guides from diff results | `enhancement`, `diff`, `mvp` | Yes |
| 3.2 (#1019) | Migration Script Generator | Generate executable data migration scripts | `enhancement`, `diff`, `rest` | Yes |
| 3.3 (#1020) | Rollback Plan Generator | Generate rollback plans for failed migrations | `enhancement`, `diff` | No |
| 3.4 (#1021) | Effort Estimation Engine | Estimate migration effort in person-hours from diff complexity | `enhancement`, `diff`, `ai-generated` | Yes |
| 3.5 (#1022) | Migration Execution Tracker | Track migration progress across consumer teams | `enhancement`, `diff` | No |

### Detailed Issue Descriptions

#### 3.1 (#1018) — Migration Guide Generator

The Migration Guide Generator transforms a diff result into a human-readable, step-by-step migration guide for API consumers. Each breaking change is expanded into specific action items: what code to change, what new fields to handle, what removed fields to stop sending, and what enum values to add support for. The guide is organized by priority—breaking changes first, then non-breaking changes, then informational notes.

The guide page at `/app/diff/[comparisonId]/migration-guide` renders the guide as a structured document with Radix `Accordion` sections for each change category. Each action item has a checkbox for consumers to track their progress. The guide includes code snippets showing before/after examples in common languages (TypeScript, Python, Go). A "Download as Markdown" option exports the guide for inclusion in release notes.

The backend generates the guide via `POST /api/v1/diff/migration-guide` accepting a diff result and returning the structured guide. Guides are cached per comparison ID. The guide generator uses templates for common change patterns (field rename, type change, enum addition) and falls back to generic descriptions for unusual changes. OpenAPI spec references are included for each affected endpoint.

**Acceptance Criteria**:
- Guide includes step-by-step action items organized by priority (breaking → non-breaking → info)
- Before/after code snippets are generated for TypeScript, Python, and Go
- Each action item includes the affected endpoint, field path, and required change
- Guide is downloadable as Markdown for inclusion in release notes and changelogs
- Progress checkboxes allow consumers to track migration completion
- Guide includes OpenAPI spec references for each affected endpoint

**Part of Epic: Migration Planning & Script Generation**

---

#### 3.2 (#1019) — Migration Script Generator

The Migration Script Generator produces executable scripts that transform data from the old schema format to the new one. For database-stored instances (via the Objectified data storage layer), the generator creates SQL migration scripts that update existing records. For API consumers, it generates transformation functions in TypeScript and Python that can be integrated into client code.

The script generator page at `/app/diff/[comparisonId]/scripts` offers script type selection (SQL migration, TypeScript transform, Python transform) via Radix `RadioGroup`. Generated scripts include inline comments explaining each transformation, error handling for edge cases (null values, missing fields), and validation checks ensuring the transformed data matches the target schema. A dry-run option generates the script with a transaction rollback at the end for safe testing.

Backend endpoints include `POST /api/v1/diff/migration-scripts` (generate script with type parameter) and `GET /api/v1/diff/migration-scripts/{id}` (retrieve generated script). The script generator handles field renames (copy value from old to new name), type coercions (integer to string), default value injection (populate new required fields), and calculated fields (derive new values from existing data). Generated scripts are reviewed by the AI for correctness before delivery.

**Acceptance Criteria**:
- SQL migration scripts update database-stored instances for PostgreSQL
- TypeScript and Python transformation functions handle client-side data migration
- Scripts include error handling for null values, missing fields, and type mismatches
- Dry-run mode wraps scripts in a transaction rollback for safe testing
- Scripts handle field renames, type coercions, default values, and calculated fields
- Generated scripts include inline comments explaining each transformation step

**Part of Epic: Migration Planning & Script Generation**

---

#### 3.3 (#1020) — Rollback Plan Generator

The Rollback Plan Generator creates a plan for reversing a migration if problems are discovered after deployment. The rollback plan includes reverse migration scripts (undoing the forward migration), data validation checks to verify rollback completeness, and a decision framework for when to trigger the rollback (error rate thresholds, data integrity checks).

The rollback plan is generated alongside the forward migration and accessible at `/app/diff/[comparisonId]/rollback`. The plan includes a checklist of pre-rollback conditions to verify, the reverse scripts, and post-rollback validation steps. The plan distinguishes between reversible changes (field additions, which can simply be ignored) and irreversible changes (data loss from field removals) that require backup restoration.

The backend generates rollback plans via `POST /api/v1/diff/rollback-plan` accepting the comparison ID and returning the structured plan. The plan includes `reversible_changes` (can be undone), `irreversible_changes` (require backup), `reverse_scripts` (SQL/code), and `validation_checks` (queries to verify rollback completeness). The plan references the forward migration script for consistency.

**Acceptance Criteria**:
- Rollback plan classifies changes as reversible or irreversible
- Reverse migration scripts undo forward migration transformations
- Pre-rollback checklist verifies conditions before initiating rollback
- Post-rollback validation checks confirm data integrity after rollback
- Irreversible changes include backup restoration instructions
- Rollback plan references the forward migration script by ID for traceability

**Part of Epic: Migration Planning & Script Generation**

---

#### 3.4 (#1021) — Effort Estimation Engine

The Effort Estimation Engine calculates the expected person-hours required to complete a migration based on the diff complexity, number of affected consumers, and historical migration data. The estimation considers: number of breaking changes, schema complexity (nested objects, relationships), consumer count, and codebase size (estimated from SDK usage).

The estimation is displayed on the diff page as a summary card showing estimated total hours, breakdown by task category (code changes, testing, deployment, documentation), and a confidence range (optimistic, expected, pessimistic). Historical data from completed migrations improves estimation accuracy over time through a feedback loop where actual hours are recorded post-migration.

The backend provides estimates via `POST /api/v1/diff/estimate-effort` accepting the comparison ID and returning the estimation breakdown. AI-assisted estimation considers the specific schema domain and change patterns for more accurate predictions. The `migration_estimates` table stores estimates alongside actual hours (when reported) for calibration.

**Acceptance Criteria**:
- Estimation covers code changes, testing, deployment, and documentation hours
- Confidence range shows optimistic, expected, and pessimistic scenarios
- Historical migration data calibrates future estimates via a feedback loop
- AI-assisted estimation considers schema domain and change patterns
- Estimation is available within 5 seconds of requesting
- Actual hours can be reported post-migration to improve future estimates

**Part of Epic: Migration Planning & Script Generation**

---

#### 3.5 (#1022) — Migration Execution Tracker

The Migration Execution Tracker provides a project management view for coordinating migrations across multiple consumer teams. When a schema version with breaking changes is published, the tracker creates a migration project with tasks assigned to each affected consumer team. Teams update their migration status, and the tracker provides an overall progress dashboard.

The tracker page at `/app/diff/migrations/[projectId]` renders a Kanban-style board using Radix-based columns for each migration status: Not Started, In Progress, Testing, Deployed, Verified. Each card represents a consumer team with their assigned breaking changes, estimated effort, and current status. The project overview shows overall completion percentage and an estimated completion date.

Backend endpoints include `POST /api/v1/diff/migration-projects` (create from a comparison), `GET /api/v1/diff/migration-projects/{id}` (project detail with team statuses), `PATCH /api/v1/diff/migration-projects/{id}/teams/{teamId}` (update team status), and `GET /api/v1/diff/migration-projects/{id}/progress` (aggregate progress). Notifications are sent when teams update their status and when the overall migration reaches key milestones (50%, 100%).

**Acceptance Criteria**:
- Migration project is created from a diff comparison with affected consumer teams
- Kanban board tracks team progress through Not Started → In Progress → Testing → Deployed → Verified
- Each team card shows assigned breaking changes, estimated effort, and current status
- Overall progress percentage and estimated completion date are displayed
- Notifications fire at team status changes and project milestones (50%, 100%)
- Migration projects are archived after all teams reach Verified status

**Part of Epic: Migration Planning & Script Generation**

---

## Epic 4: Version Archaeology & Cross-Project Comparison

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#1024) | Schema Evolution Timeline | Interactive timeline showing the complete history of a schema | `enhancement`, `diff`, `mvp` | Yes |
| 4.2 (#1025) | Change Attribution & Context | Track who made changes and why with business context | `enhancement`, `diff` | Yes |
| 4.3 (#1026) | Cross-Project Schema Comparison | Compare schemas across different projects to find duplication | `enhancement`, `diff`, `rest` | Yes |
| 4.4 (#1027) | Schema Merge Assistant | Assist merging similar schemas from different projects | `enhancement`, `diff`, `ai-generated` | No |
| 4.5 (#1028) | Evolution Pattern Analysis | Identify recurring schema evolution patterns across the organization | `enhancement`, `diff` | No |

### Detailed Issue Descriptions

#### 4.1 (#1024) — Schema Evolution Timeline

The Schema Evolution Timeline provides an interactive visualization of a schema's complete version history. The timeline renders as a horizontal scrollable view where each version is a node connected by edges. Nodes are sized by the number of changes and colored by the compatibility score—green for backward-compatible transitions, red for breaking changes. Hovering over a node shows a summary tooltip; clicking opens the diff between that version and the previous one.

The timeline page at `/app/schemas/[id]/timeline` uses a Canvas-based renderer for smooth interaction. Zoom controls allow viewing the full history or focusing on a date range. A filter panel allows highlighting specific change types (property additions, type changes, relationship changes). Branch and merge points are visualized when schema versions were forked and reconciled.

```
  Schema: UserProfile — Evolution Timeline

  v1.0        v1.1        v1.2        v2.0        v2.1
   ●───────────●───────────●───────────●───────────●
   │           │           │           │           │
   │ +3 props  │ +1 prop   │ ~2 mods   │ BREAKING  │ +1 prop
   │ Score:100 │ Score:100  │ Score:95  │ Score:62  │ Score:100
   │           │           │           │           │
   Jan 2025   Mar 2025    Jun 2025    Sep 2025    Dec 2025

   Legend: ● Compatible  ● Breaking  Size = change count

   [Zoom: ─────●──── ]  [Filter: All changes ▾]
```

The backend provides `GET /api/v1/schemas/{id}/timeline` returning an array of version nodes with metadata: version number, date, author, change summary, compatibility score, and diff summary. The timeline data is precomputed and cached when new versions are published.

**Acceptance Criteria**:
- Timeline renders all schema versions as connected nodes on a horizontal axis
- Node size reflects the number of changes; color reflects compatibility score
- Hovering shows a summary tooltip; clicking opens the version diff
- Zoom and date range controls allow focusing on specific time periods
- Branch and merge points are visualized for forked schema versions
- Timeline loads within 3 seconds for schemas with up to 200 versions

**Part of Epic: Version Archaeology & Cross-Project Comparison**

---

#### 4.2 (#1025) — Change Attribution & Context

Change Attribution & Context enriches schema version history with information about who made changes, why they were made, and what business context drove the evolution. Each schema version can have linked context: commit messages, Jira/GitHub issue references, approval records, and free-form notes explaining the rationale behind changes.

The attribution view at `/app/schemas/[id]/versions/[version]/context` displays a structured page with sections for: author and approver (pulled from version metadata), linked issues (Jira, GitHub, Linear), change rationale (free-form markdown), business impact notes, and consumer communication status. Authors can add context retrospectively, and the system prompts for context during the schema publication workflow.

Backend endpoints include `PUT /api/v1/schemas/{id}/versions/{version}/context` (add/update context), `GET /api/v1/schemas/{id}/versions/{version}/context` (retrieve), and `GET /api/v1/schemas/{id}/attribution-report` (aggregate attribution across all versions). The `schema_version_context` table stores `version_id`, `author_id`, `approver_id`, `linked_issues` (JSONB array), `rationale` (text), and `business_impact` (text).

**Acceptance Criteria**:
- Each schema version records author, approver, and publication timestamp
- Linked issues support Jira, GitHub, and Linear URL formats with auto-detection
- Change rationale supports markdown formatting for detailed explanations
- Publication workflow prompts for context before finalizing a version
- Attribution report aggregates contribution statistics across all versions
- Context can be added or updated retrospectively by the version author or admins

**Part of Epic: Version Archaeology & Cross-Project Comparison**

---

#### 4.3 (#1026) — Cross-Project Schema Comparison

Cross-Project Schema Comparison enables comparing schemas from different Objectified projects to identify duplication, inconsistencies, and standardization opportunities. The comparison works across organizational boundaries (for enterprise hub users) and within a single project (comparing different schema classes that might overlap).

The cross-project comparison page at `/app/diff/cross-project` provides two schema pickers side by side, each allowing selection of a project and schema class. The diff engine produces the same structured result as within-project comparisons but annotates each difference with a "standardization opportunity" flag when the schemas could be unified. A similarity score (0–100%) quantifies how closely the schemas match.

Backend endpoints include `POST /api/v1/diff/cross-project` accepting `source_project_id`, `source_schema_id`, `target_project_id`, and `target_schema_id`. A discovery endpoint `GET /api/v1/diff/similar-schemas?schema_id={id}` uses structural hashing to find schemas across projects that share significant structural overlap (configurable threshold, default 70%).

**Acceptance Criteria**:
- Schema pickers allow selecting schemas from any accessible project
- Diff result annotates differences with standardization opportunity flags
- Similarity score quantifies structural overlap between compared schemas
- Discovery endpoint finds similar schemas across projects using structural hashing
- Similarity threshold is configurable (default 70%)
- Cross-project comparison respects project-level access controls

**Part of Epic: Version Archaeology & Cross-Project Comparison**

---

#### 4.4 (#1027) — Schema Merge Assistant

The Schema Merge Assistant helps teams consolidate similar schemas from different projects into a unified definition. Starting from a cross-project comparison, the merge assistant proposes a merged schema that retains all properties from both sources, resolves conflicts (different types for the same property name), and maintains backward compatibility with both original schemas where possible.

The merge workflow at `/app/diff/merge` is a multi-step wizard: (1) select the two schemas to merge, (2) review the auto-generated merged schema with conflict highlights, (3) resolve conflicts manually (choose source A, source B, or create a new definition), (4) validate the merged schema against both original schemas for compatibility, (5) publish the merged schema to a target project. AI suggestions help resolve conflicts by analyzing property semantics and usage patterns.

Backend endpoints include `POST /api/v1/diff/merge/propose` (generate merged schema proposal), `POST /api/v1/diff/merge/resolve` (submit conflict resolutions), `POST /api/v1/diff/merge/validate` (check compatibility with originals), and `POST /api/v1/diff/merge/publish` (create the merged schema in target project). The merge proposal includes `merged_schema`, `conflicts` (array of unresolved differences), and `compatibility_check` (whether the merge is backward compatible with each source).

**Acceptance Criteria**:
- Merge proposal auto-generates a unified schema from two source schemas
- Conflicts are identified when properties share names but differ in type or constraints
- Conflict resolution offers source A, source B, or custom definition options
- AI suggestions provide reasoning for conflict resolution recommendations
- Validation checks backward compatibility of the merged schema against both sources
- Merged schema is publishable to any accessible project

**Part of Epic: Version Archaeology & Cross-Project Comparison**

---

#### 4.5 (#1028) — Evolution Pattern Analysis

Evolution Pattern Analysis examines schema change history across the organization to identify recurring evolution patterns. Patterns include: "rapid iteration" (many versions in a short period), "stability plateau" (long periods without changes), "complexity growth" (steadily increasing property counts), "refactoring waves" (breaking changes followed by stability), and "API surface expansion" (new endpoints without removing old ones).

The analysis page at `/app/diff/patterns` renders detected patterns as categorized cards with example schemas exhibiting each pattern. Each pattern card includes a description, the affected schemas, a risk assessment, and a recommended action. The analysis runs weekly as a background job and stores results in a `schema_evolution_patterns` table.

The backend provides `GET /api/v1/diff/patterns` (list detected patterns) and `GET /api/v1/diff/patterns/{patternId}` (detail with affected schemas and recommendations). AI-enhanced analysis identifies novel patterns beyond the pre-defined categories and correlates schema evolution with business metrics (when available).

**Acceptance Criteria**:
- At least 5 pre-defined evolution patterns are detected: rapid iteration, stability plateau, complexity growth, refactoring waves, API expansion
- Each detected pattern includes affected schemas, risk assessment, and recommended action
- Analysis runs weekly and results are cached for fast retrieval
- AI-enhanced analysis identifies novel patterns beyond pre-defined categories
- Pattern detail shows example schemas with timeline visualization
- Organization-wide pattern summary highlights the most common evolution trends

**Part of Epic: Version Archaeology & Cross-Project Comparison**

---

## Parallel Work Guide

**Epic 1 — Visual Diff Engine**:
Issues 1.1 (Diff Algorithm) and 1.4 (Permalink & Sharing) can be developed in parallel. Issue 1.2 (Side-by-Side Renderer) depends on 1.1 for the structured diff result. Issue 1.3 (Relationship Visualization) depends on 1.1 for the relationship diff data. Issue 1.5 (Inline Annotations) depends on 1.2 for the diff view and 1.4 for permalink storage.

**Epic 2 — Breaking Change Detection & Impact Analysis**:
Issues 2.1 (Breaking Change Classifier) and 2.3 (Compatibility Scoring) can be developed in parallel as they consume the diff result independently. Issue 2.2 (Consumer Impact) depends on 2.1 for classified breaking changes. Issue 2.4 (Mitigation Suggestions) depends on 2.1 and 2.2. Issue 2.5 (Pre-Publish Gate) depends on 2.1 and 2.3.

**Epic 3 — Migration Planning & Script Generation**:
Issues 3.1 (Migration Guide), 3.2 (Migration Scripts), and 3.4 (Effort Estimation) can be developed in parallel as they address independent output formats. Issue 3.3 (Rollback Plan) depends on 3.2 for the forward migration script to generate the reverse. Issue 3.5 (Execution Tracker) depends on 3.1 for migration tasks to track.

**Epic 4 — Version Archaeology & Cross-Project Comparison**:
Issues 4.1 (Evolution Timeline), 4.2 (Change Attribution), and 4.3 (Cross-Project Comparison) can be developed in parallel as they operate on independent data sources. Issue 4.4 (Schema Merge) depends on 4.3 for the cross-project diff result. Issue 4.5 (Evolution Pattern Analysis) depends on 4.1 for timeline data across all schemas.

**Cross-Epic Parallelism**: Epic 1 (Visual Diff) must be completed first as all other epics depend on the core diff engine (1.1). Once the diff algorithm is stable, Epics 2, 3, and 4 can proceed in parallel since they consume diff results independently. Epic 2 (Breaking Changes) and Epic 3 (Migration) are closely related—2.1 (classifier) should be available before 3.1 (migration guide) for optimal results—but they can be developed concurrently with stub data.
