# Objectified: Validation (Violation Detection & Compliance) - Feature Roadmap

> Real-time schema violation detection, auto-remediation, and compliance engine that continuously validates Objectified schemas against configurable rule sets, industry standards, and organizational policies—surfacing issues inline on the canvas and generating auditable compliance reports.
>
> **Revenue Model**: Compliance tier pricing, enterprise compliance packages
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, REST/OpenAPI 3.1, PostgreSQL, Redis (rule caching & evaluation queuing)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- Real-time inline violation indicators on canvas nodes with severity levels (critical, warning, info)
- Violation panel with grouped, filterable violations and jump-to-node navigation
- One-click auto-fix for naming conventions, missing descriptions, required fields, and data type normalization
- Fix preview with diff view and single-action undo
- Pre-configured compliance rule sets for GDPR, HIPAA, and PCI DSS
- Compliance dashboard with pass/fail scoring per rule set
- Automated compliance report generation in PDF and HTML formats
- Violation export as CSV/JSON for external tooling integration

---

## Epic 1: Violation Detection & Reporting

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1322) | Real-Time Violation Scanner | Continuous validation engine that evaluates rule sets against canvas state and emits violations | `ai-generated`, `enhancement`, `mvp`, `validation`, `rest` | Yes |
| 1.2 (#1328) | Violation Panel & Navigation | Dedicated violations drawer with grouping, severity badges, and jump-to-node actions | `ai-generated`, `enhancement`, `mvp`, `validation` | Yes |
| 1.3 (#1334) | Inline Canvas Violation Indicators | Visual error/warning/info badges on canvas nodes with hover detail popovers | `ai-generated`, `enhancement`, `mvp`, `validation` | Yes |
| 1.4 (#1340) | Violation Suppression & Justification | Suppress individual violations with mandatory reason, expiration, and approval workflow | `ai-generated`, `enhancement`, `validation`, `rest` | No |
| 1.5 (#1346) | Violation Export & Notifications | Export violations as CSV/JSON and push alerts via email/webhook on severity thresholds | `ai-generated`, `enhancement`, `validation`, `rest` | Yes |

### Detailed Issue Descriptions

---

#### 1.1 (#1322) — Real-Time Violation Scanner

The violation scanner is the core engine of the Validation product. It continuously evaluates all classes, properties, and relationships on the Objectified canvas against a set of active rule definitions, producing a stream of violation records that feed the panel (1.2), inline indicators (1.3), and compliance scoring (3.2). The engine must run efficiently enough to re-evaluate after every canvas edit without introducing perceptible latency.

Rules are stored in PostgreSQL in a `validation_rules` table with columns for `id`, `rule_set_id`, `name`, `description`, `severity` (critical, warning, info), `target_type` (class, property, relationship), `condition` (JSONB expression), and `enabled`. The scanner loads active rules into Redis on startup and watches for changes. When a canvas edit occurs, the scanner identifies which rules are affected by the changed nodes and evaluates only those rules—a targeted re-evaluation rather than a full scan. A full scan runs on canvas load and periodically (configurable, default every 5 minutes) to catch drift.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Canvas Edit │────▶│  Change      │────▶│  Rule Evaluator  │
│  Event       │     │  Detector    │     │  (targeted)      │
└──────────────┘     └──────────────┘     └──────────────────┘
                                                   │
                           ┌───────────────────────┤
                           │                       │
                           ▼                       ▼
                    ┌──────────────┐     ┌──────────────────┐
                    │  Violation   │     │  Redis Rule      │
                    │  Store (PG)  │     │  Cache           │
                    └──────────────┘     └──────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  Panel   │ │  Canvas  │ │  Compl.  │
        │  (1.2)   │ │  Badges  │ │  Score   │
        │          │ │  (1.3)   │ │  (3.2)   │
        └──────────┘ └──────────┘ └──────────┘
```

Each violation record includes `rule_id`, `node_id`, `node_type`, `severity`, `message`, `current_value`, `expected_value`, and `detected_at`. Violations are stored in a `violations` table partitioned by `schema_id` and indexed on `severity` for fast filtering. The scanner exposes its results via `GET /api/v1/validation/schemas/{schemaId}/violations` with filters for severity, rule set, node, and date range. A summary endpoint `GET /api/v1/validation/schemas/{schemaId}/violations/summary` returns counts grouped by severity for badge rendering.

The REST API also exposes `POST /api/v1/validation/schemas/{schemaId}/scan` to trigger an on-demand full scan, useful after bulk imports or rule changes. The OpenAPI 3.1 spec defines a `Violation` schema with all fields, plus `ViolationSummary` for the aggregated counts.

**Acceptance Criteria**

- Canvas edits trigger targeted rule re-evaluation within 200ms for schemas with up to 500 nodes
- Full scan completes within 5 seconds for schemas with up to 500 nodes and 200 active rules
- Violation records include rule ID, node ID, severity, current value, expected value, and timestamp
- `GET /api/v1/validation/schemas/{schemaId}/violations` supports filtering by severity, rule set, and node type
- On-demand scan endpoint triggers a full re-evaluation and returns the updated violation count
- Rule cache in Redis invalidates automatically when rules are created, updated, or deleted

**Part of Epic: Violation Detection & Reporting**

---

#### 1.2 (#1328) — Violation Panel & Navigation

The Violation Panel is the primary interface for reviewing and acting on detected violations. It renders as a bottom drawer on the canvas page, toggled via a persistent violation count badge in the canvas toolbar. The panel groups violations by category (naming, documentation, structure, data types, compliance) and severity, allowing users to triage issues systematically.

Each violation row displays the rule name, a human-readable description of what is wrong, the affected class or property name, severity badge (red for critical, amber for warning, blue for info), and action buttons: "Fix it" (triggers auto-fix from Epic 2), "Suppress" (opens suppression dialog from 1.4), and "Go to node" (pans the canvas to center on the affected node and highlights it). The panel uses Radix `Accordion` for category grouping, `Badge` for severity indicators, `Table` for the violation list within each group, and `ScrollArea` for the scrollable content area.

The panel header includes aggregate counts per severity, a search field for filtering by rule name or node name, and Radix `Select` dropdowns for filtering by severity, category, and rule set. A "Fix All" button in the header triggers batch auto-fix for all low-risk violations (info and warning severity only, with user confirmation). The panel state (open/closed, filters, scroll position) persists in browser session storage.

The panel page lives at the canvas route with the violations drawer as an overlay component. REST data is fetched from `GET /api/v1/validation/schemas/{schemaId}/violations` with pagination (cursor-based) and the active filters passed as query parameters. The panel polls for updates every 10 seconds or refreshes when a canvas edit event fires.

**Acceptance Criteria**

- Panel displays violations grouped by category with expandable Radix `Accordion` sections
- Each violation shows rule name, description, affected node, severity badge, and action buttons
- "Go to node" pans and highlights the affected node on the canvas
- Search and filter controls narrow violations by name, severity, category, and rule set
- Violation counts in the panel header update in real time as violations are fixed or suppressed
- Panel state (filters, scroll position, open/closed) persists across page navigations within the session

**Part of Epic: Violation Detection & Reporting**

---

#### 1.3 (#1334) — Inline Canvas Violation Indicators

Inline violation indicators surface problems directly on the canvas without requiring the user to open the violation panel. Each canvas node (class, property, relationship) that has one or more violations displays a small badge in its top-right corner showing the count and worst severity: a red circle for any critical violations, amber for warnings-only, and blue for info-only. This provides instant spatial awareness of where problems exist in the schema.

Hovering over a violation badge opens a Radix `Popover` listing the violations for that specific node. The popover shows a compact version of each violation: severity icon, rule name, and a one-line description. Clicking a violation in the popover scrolls the violation panel to that entry and expands its detail view. The popover also includes a "Fix all on this node" shortcut that triggers auto-fix for all fixable violations on that node.

Canvas-level filtering adds a severity overlay mode. When activated via the canvas toolbar (Radix `ToggleGroup` with Critical/Warning/Info toggles), nodes without violations at the selected severity are dimmed to 30% opacity, making problem areas visually prominent. This is especially useful for large schemas where scrolling through the panel would be impractical.

The badge rendering subscribes to the violation summary endpoint (`GET /api/v1/validation/schemas/{schemaId}/violations/summary?groupBy=node`) and maintains a client-side map of node ID to violation counts. The map updates on canvas edit events and scanner refresh cycles. Badge positioning uses the canvas node's bounding box and renders as an absolutely-positioned overlay.

**Acceptance Criteria**

- Every node with violations displays a badge showing the count and worst severity color
- Badge color reflects the highest severity violation on that node (critical > warning > info)
- Hover popover lists all violations for the node with severity, rule name, and description
- Clicking a violation in the popover navigates to the corresponding entry in the violation panel
- Severity overlay mode dims non-violating nodes to highlight problem areas
- Badges update within 500ms of a canvas edit that resolves or introduces a violation

**Part of Epic: Violation Detection & Reporting**

---

#### 1.4 (#1340) — Violation Suppression & Justification

Not every violation requires immediate resolution. Some are intentional design decisions, accepted technical debt, or false positives from overly broad rules. Violation suppression lets users acknowledge a violation and remove it from active counts without fixing the underlying issue, provided they supply a mandatory justification.

Suppressions come in two types: **permanent** (remains suppressed until manually un-suppressed or the rule changes) and **temporary** (auto-expires on a specified date, after which the violation resurfaces). Each suppression records the suppressing user, justification text, type, expiration date (if temporary), and whether it requires approval from a designated reviewer. When approval is required, the suppression enters a "pending" state and the violation remains visible until the reviewer approves or rejects it via `POST /api/v1/validation/suppressions/{id}/approve` or `/reject`.

The suppression dialog opens from the violation panel (1.2) or the inline popover (1.3) and uses a Radix `Dialog` with fields for justification text (Radix `TextArea`), type selection (Radix `RadioGroup`: permanent vs. temporary), expiration date picker (for temporary), and an optional reviewer selector (Radix `Select` populated from organization members). The REST API exposes `POST /api/v1/validation/violations/{violationId}/suppress`, `GET /api/v1/validation/schemas/{schemaId}/suppressions` (list all suppressions with filters), and `DELETE /api/v1/validation/suppressions/{id}` (un-suppress).

A suppression audit trail records all suppression lifecycle events (created, approved, rejected, expired, un-suppressed) in a `suppression_events` table. The validation dashboard includes a "Suppressed Violations" tab showing all active suppressions with their justifications, expiration dates, and approval status. A weekly digest email summarizes expiring suppressions and prompts reviewers to re-evaluate.

**Acceptance Criteria**

- Suppressions require a mandatory justification text with a minimum length of 20 characters
- Temporary suppressions auto-expire on the specified date and the violation resurfaces
- Approval-required suppressions remain visible until a designated reviewer approves them
- Suppression audit trail records all lifecycle events with actor, timestamp, and action
- `GET /api/v1/validation/schemas/{schemaId}/suppressions` lists active suppressions with filter support
- Un-suppressing a violation immediately returns it to the active violation count

**Part of Epic: Violation Detection & Reporting**

---

#### 1.5 (#1346) — Violation Export & Notifications

Teams integrating Objectified into their development workflow need violations accessible outside the canvas UI. This issue delivers export and notification capabilities: on-demand export of violations in CSV and JSON formats, and configurable alert notifications when violations exceed severity thresholds.

The export function is accessible from the violation panel header via an "Export" button that opens a Radix `Dialog` with format selection (Radix `RadioGroup`: CSV or JSON), scope selection (all violations, current filter, or a specific rule set), and an option to include suppressed violations. The REST endpoint `GET /api/v1/validation/schemas/{schemaId}/violations/export?format={csv|json}` generates the file with a `Content-Disposition` header for browser download. CSV exports include columns for rule name, severity, node type, node name, current value, expected value, and detected timestamp. JSON exports use the same structure as the list API response.

Notification rules are configured at `/validation/settings/notifications` (NextJS page) using Radix `Table` for the rule list and `Dialog` for creation. Each notification rule specifies a trigger condition (e.g., "critical violations > 0" or "total violations > 50"), a delivery channel (email or webhook URL), and a cooldown period to prevent alert storms. When a scan completes and the trigger condition is met, the system dispatches the notification with a summary of new violations since the last alert.

The REST API exposes `POST /api/v1/validation/notification-rules`, `GET /api/v1/validation/notification-rules`, `PUT /api/v1/validation/notification-rules/{id}`, and `DELETE /api/v1/validation/notification-rules/{id}`. Webhook notifications include an HMAC signature header for verification. Email notifications use the organization's configured SMTP or SendGrid integration.

**Acceptance Criteria**

- CSV export includes all violation fields and respects active panel filters
- JSON export conforms to the `Violation` schema defined in the OpenAPI spec
- Notification rules support threshold-based triggers on severity counts
- Webhook notifications include an HMAC-SHA256 signature for payload verification
- Email notifications include a violation summary with counts per severity and a link to the canvas
- Cooldown period prevents duplicate alerts for the same threshold crossing within the configured window

**Part of Epic: Violation Detection & Reporting**

---

## Epic 2: Auto-Remediation Engine

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1373) | Auto-Fix Engine Core | One-click remediation for common violations: naming, descriptions, types, required fields | `ai-generated`, `enhancement`, `mvp`, `validation`, `rest` | Yes |
| 2.2 (#1397) | Fix Preview & Undo System | Diff-based preview of proposed fixes with full undo/redo support | `ai-generated`, `enhancement`, `mvp`, `validation` | Yes |
| 2.3 (#1406) | Batch Auto-Fix Pipeline | Apply fixes across multiple violations in a single atomic operation | `ai-generated`, `enhancement`, `validation`, `rest` | No |
| 2.4 (#1414) | AI-Powered Fix Suggestions | LLM-generated descriptions, naming corrections, and structural recommendations | `ai-generated`, `enhancement`, `validation`, `rest` | Yes |
| 2.5 (#1420) | Custom Remediation Rules | User-defined fix templates that map violation types to automated corrections | `ai-generated`, `enhancement`, `validation`, `rest` | No |

### Detailed Issue Descriptions

---

#### 2.1 (#1373) — Auto-Fix Engine Core

The auto-fix engine transforms common violation types into one-click corrections. Rather than requiring users to manually navigate to a node, understand the violated rule, and apply the fix themselves, the engine computes the correction and applies it directly to the schema. The initial set of built-in fixers covers: **naming convention** (rename classes/properties to PascalCase/camelCase per the active rule set), **missing descriptions** (placeholder descriptions pending AI enhancement from 2.4), **data type normalization** (coerce `string` fields with format hints into proper types like `date-time`, `email`, `uri`), and **required field enforcement** (add missing required markers based on rule definitions).

Each fixer is registered as a plugin conforming to a `Fixer` interface: `canFix(violation: Violation): boolean` and `computeFix(violation: Violation, node: SchemaNode): FixProposal`. A `FixProposal` contains the target node ID, a list of property changes (old value → new value), and a confidence score (0–1). Fixers with confidence below 0.8 are flagged as "suggestion" rather than "auto-fix" and require explicit user confirmation.

The fix application endpoint `POST /api/v1/validation/violations/{violationId}/fix` computes the proposal and applies it atomically to the schema. The response includes the applied changes and the updated violation state (typically resolved). A batch variant is handled by issue 2.3. The NextJS integration adds a "Fix" button to each violation row in the panel (1.2) and inline popover (1.3) that calls this endpoint and refreshes the canvas.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Violation   │────▶│  Fixer       │────▶│  Fix Proposal    │
│  Record      │     │  Registry    │     │  (diff + score)  │
└──────────────┘     └──────────────┘     └──────────────────┘
                                                   │
                                          ┌────────┴────────┐
                                          │                 │
                                     score ≥ 0.8       score < 0.8
                                          │                 │
                                          ▼                 ▼
                                   ┌────────────┐   ┌──────────────┐
                                   │  Auto-Fix  │   │  Suggestion  │
                                   │  (1-click) │   │  (confirm)   │
                                   └────────────┘   └──────────────┘
```

**Acceptance Criteria**

- Naming convention fixer renames classes to PascalCase and properties to camelCase
- Missing description fixer adds a placeholder description derived from the field name
- Data type normalization fixer converts string fields with known format patterns to typed fields
- Fix proposals with confidence < 0.8 require explicit user confirmation before application
- `POST /api/v1/validation/violations/{violationId}/fix` applies the fix atomically and returns the diff
- Applied fixes trigger a targeted re-scan that removes the resolved violation from active counts

**Part of Epic: Auto-Remediation Engine**

---

#### 2.2 (#1397) — Fix Preview & Undo System

Automated fixes must be transparent and reversible. This issue builds the preview and undo infrastructure that lets users inspect proposed changes before committing them and revert any fix that produces undesirable results.

The preview flow intercepts the fix application before it writes to the schema. When a user clicks "Fix" with preview mode enabled (the default), a Radix `Dialog` opens showing a side-by-side diff of the affected node's current state versus the proposed state. The diff highlights changed properties in green (additions), red (removals), and amber (modifications). The dialog includes "Apply" and "Cancel" buttons, plus a "Apply & Don't Preview Again" option for users who trust the fixer category. Preview preferences are stored per-user in browser local storage.

The undo system maintains a fix history stack per schema session. Each applied fix pushes an entry containing the inverse operation (the old values) onto the stack. The undo button in the violation panel header pops the last fix and restores the previous values via `POST /api/v1/validation/schemas/{schemaId}/fixes/{fixId}/undo`. Redo is supported by maintaining a separate redo stack that captures undone fixes. The stacks are bounded to 50 entries and are cleared when the user navigates away from the schema.

The fix history is also viewable as a log at `/validation/schemas/[schemaId]/fix-history` (NextJS page) with a Radix `Table` showing timestamp, rule name, affected node, change summary, and an "Undo" button for each entry. This page queries `GET /api/v1/validation/schemas/{schemaId}/fixes` which returns the fix history with pagination.

**Acceptance Criteria**

- Preview dialog shows a side-by-side diff with additions, removals, and modifications highlighted
- Users can skip preview for trusted fixer categories via a per-user preference
- Undo reverts the most recent fix and restores the node to its pre-fix state
- Redo re-applies the last undone fix
- Fix history page lists all applied fixes with timestamp, rule, node, and change summary
- Undo is available for fixes applied within the current session (bounded to 50 entries)

**Part of Epic: Auto-Remediation Engine**

---

#### 2.3 (#1406) — Batch Auto-Fix Pipeline

Schemas with dozens or hundreds of violations need a way to apply fixes in bulk rather than one at a time. The batch auto-fix pipeline selects all fixable violations matching user-specified criteria and applies their fixes in a single atomic transaction, rolling back entirely if any individual fix fails.

The batch flow is initiated from the violation panel's "Fix All" button or from `POST /api/v1/validation/schemas/{schemaId}/fixes/batch` with a request body specifying filter criteria: `severity` (which levels to include), `categories` (which rule categories), `minConfidence` (minimum fixer confidence score, default 0.8), and `dryRun` (boolean). In dry-run mode, the endpoint returns the list of proposed fixes without applying them, allowing review before commitment.

The pipeline processes fixes in dependency order. If fixing violation A (renaming a class) would affect the input to violation B (a relationship referencing that class), the pipeline resolves the dependency graph and applies fixes in topological order. Circular dependencies (rare but possible with cross-referencing rules) are detected and excluded from the batch with an explanatory error message.

A progress indicator on the UI shows fixes applied out of total. For large batches (>50 fixes), the operation runs asynchronously and the user is notified via a toast when complete. The REST endpoint returns a `202 Accepted` with a job ID for async operations and a `200 OK` with results for synchronous ones. Job status is queryable via `GET /api/v1/validation/schemas/{schemaId}/fixes/batch/{jobId}`.

**Acceptance Criteria**

- Batch fix applies all matching violations in a single atomic transaction
- Dry-run mode returns proposed fixes without applying them
- Dependency ordering ensures fixes are applied in topological order
- Circular dependencies are detected and excluded with an error message per affected violation
- Async jobs return 202 with a job ID; status is queryable until completion
- Rollback reverts all changes if any individual fix in the batch fails

**Part of Epic: Auto-Remediation Engine**

---

#### 2.4 (#1414) — AI-Powered Fix Suggestions

Some violations cannot be resolved with deterministic rules. Missing descriptions, ambiguous naming, and suboptimal data modeling choices benefit from LLM-generated suggestions. This issue integrates an AI suggestion engine that produces high-quality fix proposals for violations where the built-in fixers (2.1) cannot reach sufficient confidence.

When the auto-fix engine's confidence score falls below 0.8 for a violation, or when the violation type is inherently subjective (e.g., "description is too vague"), the system routes the violation to the AI suggestion service. The service sends the schema context (class name, property names, existing descriptions, related classes) to a configured LLM endpoint and receives a suggested fix. Suggestions include AI-generated property descriptions, alternative naming proposals with explanations, and structural recommendations (e.g., "consider extracting these 5 address fields into a reusable Address class").

AI suggestions are displayed in the violation panel with a distinct "AI Suggestion" badge and always require explicit user confirmation—no AI fix is auto-applied. The suggestion includes the proposed change, a brief rationale, and a confidence indicator. Users can accept, modify (edit the suggestion before applying), or dismiss with feedback. Dismissal feedback is logged for future model improvement.

The REST API exposes `POST /api/v1/validation/violations/{violationId}/ai-suggest` to trigger suggestion generation and `POST /api/v1/validation/violations/{violationId}/ai-suggest/accept` to apply the accepted suggestion. The NextJS settings page at `/validation/settings/ai` allows configuring the LLM provider, API key, and which violation categories are eligible for AI suggestions (using Radix `Switch` toggles per category).

**Acceptance Criteria**

- AI generates descriptions for classes and properties using schema context as input
- AI naming suggestions include the proposed name and a human-readable rationale
- All AI suggestions require explicit user confirmation before application
- Users can edit AI suggestions before accepting them
- Dismissal with feedback is logged for model improvement tracking
- AI suggestion is available only for configured violation categories (opt-in per category)

**Part of Epic: Auto-Remediation Engine**

---

#### 2.5 (#1420) — Custom Remediation Rules

Organizations often have domain-specific fix patterns that the built-in fixers don't cover. Custom remediation rules let users define their own fix templates: mapping a violation type to a scripted correction using a declarative JSON DSL, without writing application code.

Each custom remediation rule specifies a `matchCondition` (which violations it applies to, expressed as a filter on rule ID, severity, or node properties), a `fixTemplate` (a set of property assignments using JSONPath expressions, supporting string interpolation for deriving values from existing fields), and a `confidence` score. Rules are evaluated after built-in fixers, giving custom rules the ability to override or extend default behavior.

The rule editor lives at `/validation/settings/remediation-rules` (NextJS page) with a Radix `Table` listing existing rules, a Radix `Dialog` for creating and editing rules, and a built-in test panel where users can paste a sample violation payload and see the computed fix proposal. The REST API exposes `POST /api/v1/validation/remediation-rules`, `GET /api/v1/validation/remediation-rules`, `PUT /api/v1/validation/remediation-rules/{id}`, and `DELETE /api/v1/validation/remediation-rules/{id}`.

Custom rules are scoped per organization and versioned. When a rule is updated, previously applied fixes are not retroactively changed, but new violations matching the updated rule receive the new fix template. Rules support an `enabled` toggle for safe rollout—administrators can create and test rules in disabled mode before activating them.

**Acceptance Criteria**

- Custom rules match violations by rule ID, severity, node type, or property filters
- Fix templates support JSONPath-based property assignments with string interpolation
- Test panel evaluates a rule against a sample violation and displays the proposed fix
- Custom rules are scoped per organization and not visible to other organizations
- Rule versioning tracks changes; updates apply only to new violations going forward
- Rules can be toggled between enabled and disabled states without deletion

**Part of Epic: Auto-Remediation Engine**

---

## Epic 3: Compliance Engine

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1446) | Compliance Rule Set Library | Pre-configured rule sets for GDPR, HIPAA, PCI DSS, SOC 2, and ISO 27001 | `ai-generated`, `enhancement`, `mvp`, `validation`, `rest` | Yes |
| 3.2 (#1454) | Compliance Dashboard & Scoring | Real-time compliance scoring with pass/fail status per rule set and drill-down detail | `ai-generated`, `enhancement`, `mvp`, `validation` | No |
| 3.3 (#1459) | Automated Compliance Reports | Generate PDF/HTML compliance reports with executive summary and detailed findings | `ai-generated`, `enhancement`, `mvp`, `validation`, `rest` | Yes |
| 3.4 (#1465) | Attestation & Sign-Off Workflow | Formal sign-off process for compliance status with audit trail | `ai-generated`, `enhancement`, `validation`, `rest` | No |
| 3.5 (#1470) | Report Scheduling & Distribution | Schedule recurring reports with email delivery to stakeholders | `ai-generated`, `enhancement`, `validation`, `rest` | No |

### Detailed Issue Descriptions

---

#### 3.1 (#1446) — Compliance Rule Set Library

The Compliance Rule Set Library ships pre-configured validation rule sets aligned to major industry standards and regulations. Each rule set contains dozens of individual rules that check schema properties relevant to that standard. For example, the GDPR rule set verifies that personal data fields have retention period annotations, purpose declarations, and lawful basis markers. The HIPAA rule set checks for encryption-at-rest flags on PHI fields and access control annotations.

The library ships with five built-in rule sets: **GDPR** (data minimization, purpose limitation, retention, consent basis), **HIPAA** (PHI identification, encryption requirements, access controls, audit logging), **PCI DSS** (cardholder data field identification, encryption, tokenization markers), **SOC 2** (availability, confidentiality, processing integrity annotations), and **ISO 27001** (asset classification, risk assessment markers, control mappings). Each rule set is immutable—users cannot modify built-in rules—but they can clone a rule set to create a custom variant.

```
┌───────────────────────────────────────────────────────────┐
│                 Compliance Rule Sets                       │
├───────────────┬────────┬─────────┬────────┬───────────────┤
│     GDPR      │ HIPAA  │ PCI DSS │ SOC 2  │  ISO 27001    │
├───────────────┼────────┼─────────┼────────┼───────────────┤
│ 24 rules      │ 18 rules│ 15 rules│ 20 rules│ 22 rules     │
│               │        │         │        │               │
│ • Retention   │ • PHI  │ • CHD   │ • Avail│ • Asset class │
│ • Purpose     │ • Encr.│ • Token │ • Conf.│ • Risk assess │
│ • Consent     │ • ACL  │ • Encr. │ • Integ│ • Controls    │
│ • Minimiz.    │ • Audit│ • Mask  │ • Priv.│ • Audit       │
└───────────────┴────────┴─────────┴────────┴───────────────┘
```

The rule set management page lives at `/validation/compliance/rule-sets` (NextJS page) with a Radix `Table` listing available sets with name, standard, rule count, and status (active/inactive). Clicking a set opens a detail view showing all rules within it. The REST API exposes `GET /api/v1/validation/rule-sets` (list), `GET /api/v1/validation/rule-sets/{id}` (detail with rules), `POST /api/v1/validation/rule-sets/{id}/clone` (create editable copy), and `PUT /api/v1/validation/rule-sets/{id}/activate` / `deactivate`. Custom rule sets support full CRUD via `POST /api/v1/validation/rule-sets` with custom rules.

**Acceptance Criteria**

- Five built-in rule sets ship with the product: GDPR, HIPAA, PCI DSS, SOC 2, ISO 27001
- Built-in rule sets are immutable; modifications require cloning into a custom set
- Each rule within a set has a name, description, severity, and link to the relevant standard section
- Rule sets can be activated or deactivated per schema independently
- Custom rule sets support full CRUD with organization-level scoping
- Cloning a built-in rule set copies all rules into a new editable set with a user-defined name

**Part of Epic: Compliance Engine**

---

#### 3.2 (#1454) — Compliance Dashboard & Scoring

The Compliance Dashboard provides a real-time overview of how each schema scores against active compliance rule sets. The dashboard aggregates violation data from the scanner (1.1) and presents it as a compliance score: the percentage of rules passing (no active violations) within each rule set. This gives compliance officers and architects an at-a-glance view of organizational compliance posture.

The dashboard page at `/validation/compliance` renders a card grid where each card represents an active rule set. Each card displays the rule set name, the compliance score as a percentage with a color-coded ring (green ≥ 90%, amber 60–89%, red < 60%), the count of passing vs. failing rules, and the timestamp of the last evaluation. Clicking a card navigates to a drill-down page at `/validation/compliance/[ruleSetId]` showing every rule with pass/fail status, the affected nodes for failing rules, and links to the violations in the panel.

The drill-down page uses Radix `Table` for the rule list with columns for rule name, status (pass/fail `Badge`), affected node count, severity, and a link to the relevant section of the compliance standard. A historical score chart shows the compliance score trend over the past 90 days, making it easy to spot regressions. The REST API provides `GET /api/v1/validation/compliance/scores` (all sets) and `GET /api/v1/validation/compliance/scores/{ruleSetId}` (per-set detail with rule-level breakdown).

The scoring engine recomputes scores whenever the violation scanner completes a run. Scores are cached in Redis with a TTL matching the scan interval. Delta notifications fire when a score changes by more than 5 percentage points, alerting stakeholders to significant compliance shifts.

**Acceptance Criteria**

- Each active rule set displays a compliance score as a percentage with color-coded indicator
- Drill-down view lists every rule with pass/fail status and links to affected violations
- Historical score chart shows the compliance trend over the past 90 days
- Scores recompute automatically after each violation scan
- Delta notifications fire when a score changes by more than 5 percentage points
- `GET /api/v1/validation/compliance/scores` returns all active rule sets with their current scores

**Part of Epic: Compliance Engine**

---

#### 3.3 (#1459) — Automated Compliance Reports

Compliance officers need formal, exportable reports—not just dashboards. This issue builds the report generation engine that compiles violation data, compliance scores, remediation status, and suppression justifications into structured PDF and HTML documents suitable for auditors and executive stakeholders.

Each report includes four sections: **Executive Summary** (overall compliance posture, scores per rule set, key findings count, trend vs. previous report), **Detailed Findings** (every failing rule with affected nodes, current values, expected values, and remediation guidance), **Remediation Status** (fixes applied since the last report, outstanding violations by age, suppressed violations with justifications), and **Recommendations** (prioritized list of actions to improve compliance scores, auto-generated from violation severity and count).

Report generation is triggered via `POST /api/v1/validation/compliance/reports` with parameters for `schemaId`, `ruleSetIds` (which sets to include), `format` (pdf or html), and `comparisonPeriod` (for historical comparison). The endpoint returns a `202 Accepted` with a job ID since report generation may take several seconds for large schemas. The completed report is downloadable via `GET /api/v1/validation/compliance/reports/{reportId}/download`. The report list endpoint `GET /api/v1/validation/compliance/reports` returns all generated reports with metadata.

The report generation page at `/validation/compliance/reports` uses Radix `Select` for rule set and format selection, a date range picker for the comparison period, and a Radix `Table` listing previously generated reports with download links. A progress indicator shows generation status for in-flight reports.

**Acceptance Criteria**

- Reports include executive summary, detailed findings, remediation status, and recommendations
- PDF reports render with professional formatting including charts for compliance scores
- HTML reports are self-contained single-file documents viewable in any browser
- Historical comparison shows score changes vs. the selected comparison period
- Report generation completes within 30 seconds for schemas with up to 500 nodes and 5 rule sets
- Generated reports are persisted and listable for future reference and audit purposes

**Part of Epic: Compliance Engine**

---

#### 3.4 (#1465) — Attestation & Sign-Off Workflow

Compliance reports are useful only when someone accountable formally acknowledges their contents. The attestation workflow adds a formal sign-off process where designated compliance officers or architects review a compliance report and attest that they have reviewed the findings, accept the current compliance posture, and commit to remediating outstanding issues within a specified timeframe.

The attestation page at `/validation/compliance/reports/[reportId]/attest` displays the report summary in read-only format with an attestation form at the bottom. The form includes the attester's name and role (pre-filled from their profile), a Radix `Checkbox` for legal acknowledgment ("I have reviewed this report and accept responsibility for the compliance posture described herein"), a remediation deadline date picker, and a "Sign & Attest" button. Upon attestation, the report's status transitions from "generated" to "attested" and the attestation record is immutable.

Backend endpoints include `POST /api/v1/validation/compliance/reports/{reportId}/attest` (record attestation), `GET /api/v1/validation/compliance/reports/{reportId}/attestations` (list attestations for a report), and `GET /api/v1/validation/compliance/attestations?status={pending|completed|overdue}` (list all attestations across reports). The `compliance_attestations` table records `report_id`, `attester_user_id`, `attested_at`, `ip_address`, `remediation_deadline`, `acknowledgment_text`, and `status`.

Attestation reminders are sent when a report is generated but not attested within a configurable period (default 7 days). Overdue attestations (past the remediation deadline with outstanding violations) are escalated to organization administrators. The attestation audit trail is included in compliance reports for downstream auditors.

**Acceptance Criteria**

- Attestation captures attester identity, timestamp, IP address, and acknowledgment text
- Attestation records are immutable and cannot be modified or deleted after creation
- Reminder notifications fire when reports are un-attested past the configured period
- Overdue remediations (past deadline with outstanding violations) trigger escalation alerts
- `GET /api/v1/validation/compliance/attestations` supports filtering by status and date range
- Attestation history is included in subsequent compliance reports for auditor reference

**Part of Epic: Compliance Engine**

---

#### 3.5 (#1470) — Report Scheduling & Distribution

Manual report generation is fine for ad-hoc reviews, but ongoing compliance requires automated, recurring reports delivered to the right stakeholders without manual intervention. This issue adds scheduling and email distribution for compliance reports.

Report schedules are configured at `/validation/compliance/reports/schedules` (NextJS page) using a Radix `Dialog` for schedule creation. Each schedule specifies: frequency (Radix `Select`: daily, weekly, monthly), target schema, rule sets to include, report format (PDF or HTML), and a distribution list of email addresses. The schedule engine runs as a background job, generating reports on the configured cadence and emailing them to all recipients with the report attached and a brief summary in the email body.

The REST API exposes `POST /api/v1/validation/compliance/reports/schedules` (create), `GET /api/v1/validation/compliance/reports/schedules` (list), `PUT /api/v1/validation/compliance/reports/schedules/{id}` (update), and `DELETE /api/v1/validation/compliance/reports/schedules/{id}` (remove). Each schedule has an `enabled` toggle and a `lastRunAt` timestamp. Failed deliveries (SMTP errors, invalid addresses) are logged and retried once; persistent failures disable the affected recipient and notify the schedule owner.

The scheduling page also shows a delivery history table with Radix `Table` listing each scheduled run's timestamp, recipient count, delivery status (success, partial, failed), and a link to the generated report. This provides operational visibility into the distribution pipeline.

**Acceptance Criteria**

- Schedules support daily, weekly, and monthly frequencies with configurable rule sets and format
- Email delivery attaches the report file and includes a compliance score summary in the body
- Failed deliveries are retried once; persistent failures disable the recipient with owner notification
- Schedule CRUD is available via REST API with `enabled` toggle for pause/resume
- Delivery history shows each run with timestamp, status, and link to the generated report
- Scheduled reports are indistinguishable from manually generated reports in the report archive

**Part of Epic: Compliance Engine**

---

## Parallel Work Guide

The following issues can be worked simultaneously within and across epics:

**Epic 1 (Violation Detection & Reporting):**
- 1.1 (Violation Scanner), 1.2 (Violation Panel), 1.3 (Inline Indicators), and 1.5 (Export & Notifications) can all be developed in parallel. The scanner provides data, but the panel and indicators can be built against a mock data layer and integrated once the scanner API is stable. Export and notifications are standalone output modules.
- 1.4 (Suppression & Justification) depends on 1.1 and 1.2 being at least partially complete since suppressions modify violation state and render in the panel.

**Epic 2 (Auto-Remediation Engine):**
- 2.1 (Auto-Fix Engine Core), 2.2 (Fix Preview & Undo), and 2.4 (AI-Powered Suggestions) can be developed in parallel. The fix engine and preview system share an interface but have independent internals. AI suggestions are a separate service integration.
- 2.3 (Batch Auto-Fix) depends on 2.1 for the individual fixer implementations and the `FixProposal` data model.
- 2.5 (Custom Remediation Rules) depends on 2.1 for the fixer registry and plugin interface.

**Epic 3 (Compliance Engine):**
- 3.1 (Rule Set Library) and 3.3 (Automated Reports) can be developed in parallel. The rule set library provides the data model, while report generation can be built against seed data.
- 3.2 (Compliance Dashboard) depends on 3.1 for rule set definitions and 1.1 for violation data to compute scores.
- 3.4 (Attestation Workflow) depends on 3.3 for generated reports to attest.
- 3.5 (Report Scheduling) depends on 3.3 for the report generation engine.

**Cross-Epic Parallelism:**
- Epic 1 and Epic 2 are mostly independent—Epic 2's fixers consume violation records from Epic 1, but the fixer interface can be developed against a `Violation` type contract before the scanner is complete.
- Epic 3 depends on Epic 1's scanner (1.1) for violation data that feeds compliance scoring, but the rule set library (3.1) and report templates (3.3) can be built concurrently with Epic 1.
- All three epics can have UI work proceeding in parallel since they operate on separate NextJS routes (`/validation/schemas/...`, `/validation/settings/...`, `/validation/compliance/...`).
- A recommended team split: one engineer on the scanner + panel (1.1, 1.2, 1.3), one on the fix engine (2.1, 2.2), and one on compliance infrastructure (3.1, 3.3). Convergence happens when integrating fixes into the panel, scores into the dashboard, and reports into the scheduling pipeline.
