# Objectified-Commercial Git-Like Ticket Pack

## Source issue set from `NobuData/objectified`

The following issues were used as direct source material for git-like behavior, including both closed and still-open work.

### Open issues (git-like)

- `#175` Add commit metadata and optional checksum/fingerprint for integrity
- `#176` Add pre-commit validation and configurable commit policy
- `#177` Add push conflict policy, permissions, and optional branch protection
- `#178` Add webhook or event on successful push for downstream systems
- `#179` Add conditional pull and optional delta pull
- `#180` Add pull options for headless/CI
- `#181` Add merge preview, resolution submission API, and optional post-merge validation
- `#182` Add optimistic locking and workflow audit log
- `#183` Add audit log for compliance and debugging

### Closed issues (git-like)

- `#66` Add toolbar for version-based actions (commit/push/pull/merge)
- `#67` Add toolbar for commit
- `#68` Add toolbar for push
- `#69` Add toolbar for pull
- `#70` Add merge UI for merging versions
- `#71` Add version history to UI
- `#73` Add rollback to UI version history
- `#74` Add branching to UI version history
- `#75` Add history removal to UI version history
- `#134` Add developer CLI or SDK for pull/push/export/codegen in CI/CD
- `#213` Add push retry and 409 handling guidance
- `#214` Add conditional pull and stash/discard dialog
- `#215` Add merge preview and side-by-side conflict diff
- `#216` Add unpushed/server-ahead indicators and status
- `#217` Add history filter/search/metadata and compare with current
- `#218` Add load-as-read-only/editable and revision warning handling
- `#219` Add rollback confirmation and policy handling
- `#220` Add branch dialog UX from revision
- `#221` Add remove confirmation, soft delete, and cascade warning
- `#222` Add export history and retention policy display

## Design alignment for objectified-commercial

These ticket drafts are designed to match the current product direction:

- UI uses `Next.js + TypeScript + Tailwind + Radix UI` with modern, compact workflows.
- Existing git-like patterns already exist in Objectified and are extended here for enterprise-grade controls.
- Behavior is centered on version-first workflows, not file-based Git primitives.
- Multi-tenant compliance, auditability, and safe collaboration are first-class requirements.

## Prioritized single-scope tickets for objectified-commercial

Each ticket below is intentionally small enough to complete in isolation. They are ordered by delivery priority and dependency.

---

## GitHub tracking (`KenSuenobu/objectified-commercial`)

**Labels used:** `roadmap-gitlike`, `git-behavior`, `version-control` (applies to all issues in this pack), plus area labels (`rest`, `database`, `ui`, `typescript`, `python`, …). Tickets marked **MVP** also have the `mvp` label.

### Epics

| Epic | Issue | Scope |
|------|------:|--------|
| Commit, Push & Studio Sync | [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558) | P0-01 — P0-07 |
| Branching, Merge & Conflict Resolution | [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559) | P0-08 — P0-10, P1-01 — P1-04 |
| Workflow Audit & Compliance API | [#2560](https://github.com/KenSuenobu/objectified-commercial/issues/2560) | P1-05, P1-06 |
| History, Compare & Rollback | [#2561](https://github.com/KenSuenobu/objectified-commercial/issues/2561) | P1-07 — P1-10 |
| Enterprise Governance, Webhooks & Platform APIs | [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562) | P2-01 — P2-10 |

### Related existing issues (not duplicates — different scope)

| Topic | Issue | Relation |
|-------|------|----------|
| Import wizard conflicts | [#2296](https://github.com/KenSuenobu/objectified-commercial/issues/2296), [#2337](https://github.com/KenSuenobu/objectified-commercial/issues/2337) | **Import** job conflicts vs **native version merge** in this roadmap |
| External Git branch-per-version | [#1336](https://github.com/KenSuenobu/objectified-commercial/issues/1336), [#1473](https://github.com/KenSuenobu/objectified-commercial/issues/1473) | Remote Git integration vs **in-product** revision branches (P0-08/09) |
| Version comparison epic | [#2124](https://github.com/KenSuenobu/objectified-commercial/issues/2124) | Share UI components with **P1-08** where sensible |

### MVP release candidates

Ship first for a credible git-like Studio: **P0-01 — P0-10** (core metadata through merge preview), plus **P1-05 — P1-10** (audit + history + rollback). **P1-01 — P1-04** (persisted merge sessions, full conflict UX) can trail merge-preview MVP or ship as phase 2.

**Labeled `mvp` on GitHub:** P0-01 — P0-10, P1-05 — P1-10. **P1-01 — P1-04** intentionally omit `mvp` (phase-2 merge-session / conflict UX after merge-preview ships).

### Safe parallel execution (by workstream)

Workstreams below can proceed in parallel once shared contracts (revision id, head, error envelope) are agreed. Items in the same row may still share merge conflicts in code — use branches per workstream.

| Parallel track | Tickets | Notes |
|----------------|---------|--------|
| **A — Commit & metadata** | P0-01, P0-02 ✓, P0-03 ✓ | P0-02 (ADE **Commit** dialog) shipped after P0-01 API |
| **B — Push & conflict UX** | P0-04, P0-05 | P0-05 can mock 409 until P0-04 stable |
| **C — Pull efficiency** | P0-06 | Coordinate ETag with P0-04 head semantics |
| **D — Studio status** | P0-07 | Depends on signals from B/C; can mock |
| **E — Branching** | P0-08 ✓, P0-09 ✓ | P0-09 after P0-08 |
| **F — Merge preview** | P0-10 ✓ | Gates P1-01 — P1-04 |
| **G — Merge resolution UI** | P1-01 ✓, P1-02 ✓, P1-03 ✓, P1-04 ✓ | Sequential within: 01→02→03→04 |
| **H — Audit** | P1-05, P1-06 | 05 before 06 |
| **I — History & rollback** | P1-07, P1-08, P1-09, P1-10 | P1-07/08 parallel; 09/10 pair with rollback API |
| **J — Enterprise** | P2-01 — P2-10 | Parallel across subdomains after core push/pull stable |

**High parallelism:** P0-01+P0-03 (track A), P0-06 (track C), P1-05 (track H), and P2-02 (locks) can start early with minimal blocking.



## P0-01: Add Commit Metadata Fields to Revision Records

**GitHub:** [#2563](https://github.com/KenSuenobu/objectified-commercial/issues/2563) · **Epic:** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558) · **Status:** shipped (DB columns + REST create/fork + list/get history)

### Problem statement
Commits are not consistently traceable to who made the change or why. Teams need author/message/reference metadata to audit change intent and link commits to delivery workflows.

### Scope
Add metadata persistence for commit author, message, and external reference id. Return these fields in revision history APIs.

### Acceptance criteria
- Commit API accepts and stores `author`, `message`, and `externalRef`.
- Revision history returns these fields for each commit.
- Existing commits without metadata still render without errors.

---

## P0-02: Commit Dialog with Radix Form Validation

**Status:** **Done** — ADE **Versions** toolbar **Commit** opens a Radix dialog (required message, optional external ref, validation, toasts); create revision uses REST `POST /api/versions` with `shortMessage` / `externalRef`.

**GitHub:** [#2564](https://github.com/KenSuenobu/objectified-commercial/issues/2564) · **Epic:** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558)

### Problem statement
Users can commit without a structured UI flow, leading to inconsistent commit quality and missing metadata.

### Scope
Add a Radix dialog for commit action with message, optional external reference, and inline validation.

### Acceptance criteria
- Commit action opens a Radix dialog with fields and clear labels.
- Submit is disabled until required fields pass validation.
- Success and error states are shown with project-standard toasts.

---

## P0-03: Add Pre-Commit Policy Enforcement (Message Required + Max Payload)

**Status:** **Done** — REST evaluates policy before persisting revisions; `projects.metadata.commitPolicy` overrides defaults; errors use `POLICY_VIOLATION` / `PAYLOAD_TOO_LARGE`.

**GitHub:** [#2565](https://github.com/KenSuenobu/objectified-commercial/issues/2565) · **Epic:** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558)

### Problem statement
Without policy enforcement, commits can violate tenant standards (empty messages, oversized payloads).

### Scope
Implement policy checks before commit and return policy violations in a consistent error format.

### Acceptance criteria
- Policy rejects empty message when enabled.
- Policy rejects payload above configured size threshold.
- API returns deterministic error codes and human-readable messages.

---

## P0-04: Add Push Base Revision Check (Optimistic Locking)

**Status:** **Done** — `POST /v1/versions/{tenant}/{project}` requires **`baseRevisionId`**; stale base → **`409`** with `code: STALE_HEAD`, `currentHeadRevisionId`, `currentHead` (subset); advances **named branch tip** in the same transaction when applicable; ADE Commit sends **`baseRevisionId`** / **`branchName`**.

**GitHub:** [#2566](https://github.com/KenSuenobu/objectified-commercial/issues/2566) · **Epic:** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558)

### Problem statement
Concurrent edits can overwrite each other because push does not always require a base revision match.

### Scope
Require `baseRevisionId` on push and return `409` conflict when stale.

### Acceptance criteria
- Push without `baseRevisionId` is rejected.
- Push with stale base revision returns `409` and latest server revision metadata.
- Valid push with current base revision succeeds.

### Push conflict response (REST, for P0-05 UI)

On **`409`** with **`code: STALE_HEAD`**:

| Field | Meaning |
|-------|---------|
| `message` | Human-readable reason |
| `currentHeadRevisionId` | Server revision id (UUID) clients should treat as head |
| `currentHead` | Optional object: `revisionId`, `versionId`, `shortMessage`, `createdAt` |

**Idempotency:** Retrying the **same** successful push body may create a **second** revision if the first commit persisted; clients should refresh head from the error payload or re-pull before retry.

---

## P0-05: Push Conflict Banner + CTA Guidance in Studio

**Status:** **Done** — On **`409`** / **`STALE_HEAD`** from commit (push), **ADE** shows a **persistent server-ahead banner** with **Pull** and **Open merge**; **`/api/versions`** POST forwards **`code`**, **`currentHeadRevisionId`**, **`currentHead`**; banner clears after **pull** reconciliation or **successful merge**.

**GitHub:** [#2567](https://github.com/KenSuenobu/objectified-commercial/issues/2567) · **Epic:** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558)

### Problem statement
Users receiving push conflicts do not get a clear next action path.

### Scope
Add server-ahead conflict banner with direct CTAs (`Pull`, `Open Merge`) in editor toolbar/state region.

### Acceptance criteria
- On `409`, UI shows persistent server-ahead banner.
- Banner includes direct actions for pull/merge.
- Banner clears automatically after successful reconciliation.

---

## P0-06: Add Pull Conditional Fetch (ETag / 304)

**Status:** **Done** — `GET /v1/versions/.../{revisionId}` and `GET .../by-version/{versionId}` send **`ETag`** (revision id); **`If-None-Match`** → **`304`** empty body when unchanged; Next.js **`/api/versions/[versionId]`** forwards **`If-None-Match`** / **`ETag`**.

**GitHub:** [#2568](https://github.com/KenSuenobu/objectified-commercial/issues/2568) · **Epic:** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558)

### Problem statement
Clients repeatedly fetch unchanged state, increasing latency and bandwidth.

### Scope
Support `If-None-Match` on pull and return `304` when version head is unchanged.

### Acceptance criteria
- Pull returns ETag header.
- Pull with matching ETag returns `304` with empty body.
- Pull with stale ETag returns fresh state payload.

---

## P0-07: Show Sync State Indicators (Dirty, Unpushed, Server Ahead)

**Status:** **Done** — **Studio header** compact **Dirty / ↑N / Ahead** chips (Tailwind + Radix tooltips): local dirty from canvas **auto-save pending**; **↑N** counts **your** revisions on the **parent** chain from latest to the selected revision; **Ahead** when latest ≠ selection or **`STALE_HEAD`** push conflict is active.

**GitHub:** [#2569](https://github.com/KenSuenobu/objectified-commercial/issues/2569) · **Epic:** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558)

### Problem statement
Editors lack clear status visibility, causing accidental pushes/pulls at the wrong time.

### Scope
Add compact sync indicators in toolbar/header using modern status chips.

### Acceptance criteria
- Dirty state indicator updates on local edits.
- Unpushed commit count is shown when greater than zero.
- Server-ahead state appears when remote head differs from local base.

---

## P0-08: Add Branch from Revision API Endpoint ✓

**GitHub:** [#2570](https://github.com/KenSuenobu/objectified-commercial/issues/2570) (done) · **Epic:** [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559)

### Problem statement
Branching from a selected historical revision is required for safe experimentation but is not a first-class endpoint.

### Scope
Create endpoint to generate new version branch from provided revision id with lineage metadata.

### Shipped
- **REST** `POST .../version-branches/from-revision` with `sourceRevisionId`, `branchName`; column `version_branches.branched_from_revision_id`; **409** `BRANCH_NAME_CONFLICT` on name reuse; **idempotent** replay when the same name + source tip already match (response `idempotentReplay`).

### Acceptance criteria
- Endpoint accepts source revision and target branch name.
- New version branch is created with source lineage.
- Duplicate branch names in same project are rejected with clear error.

---

## P0-09: Branch Creation Dialog from History Row ✓

**GitHub:** [#2571](https://github.com/KenSuenobu/objectified-commercial/issues/2571) · **Epic:** [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559)

### Problem statement
Users cannot branch directly from the revision they are inspecting.

### Scope
Add branch action in history UI row with Radix dialog for branch name and open behavior.

### Shipped
- **ADE → Versions** revision **history graph** node menu **Branch → Branch from here** opens the same Radix **Create named branch** dialog as the versions table row action.
- Dialog **prefills** a suggested name (`feature/<slug>` from the revision note, else `branch/v<semver>`).
- Create calls **Next.js** `POST .../version-branches/from-revision` (proxies **REST** P0-08) for lineage on `version_branches`.
- On success: **commit base** switches to the **new branch tip** (`copySourceBranchKey` + `sourceVersionId`) and the view **scrolls** to the named-branches panel (or the history graph when it is the first branch).

### Acceptance criteria
- History row exposes `Branch from here` action.
- Dialog prefills suggested branch name and allows edits.
- On success, user is navigated to the new branch version.

---

## P0-10: Merge Preview Endpoint (No State Mutation)

**GitHub:** [#2572](https://github.com/KenSuenobu/objectified-commercial/issues/2572) · **Epic:** [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559) · **Status:** shipped (REST dry-run: `summaryCounts`, `conflictCounts`, `conflicts[]` with kinds, optional `mergedOpenApi` capped, `includeMergedOpenApi`)

### Problem statement
Teams need to understand conflicts before applying a merge.

### Scope
Add dry-run merge API returning merged preview and conflict list without persisting changes.

### Acceptance criteria
- Merge preview returns conflict list and summary counts.
- No server state is changed by preview requests.
- Preview response includes enough metadata to drive conflict UI.

---

## P1-01: Persist Merge Session + Conflict Records

**GitHub:** [#2573](https://github.com/KenSuenobu/objectified-commercial/issues/2573) · **Epic:** [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559) · **Status:** shipped (DB `merge_sessions` + `merge_session_conflicts` + `merge_session_status_events`; REST `persistMergeSession` on merge-preview; GET/PATCH merge-session APIs)

### Problem statement
Conflict resolution work cannot be resumed reliably without persisted merge session state.

### Scope
Store merge session header and per-conflict records for resolution lifecycle.

### Acceptance criteria
- Merge preview can optionally create a persisted merge session (`persistMergeSession` on dry-run).
- Conflicts are queryable by `mergeSessionId` (`GET .../merge-sessions/{id}/conflicts`).
- Session status transitions are tracked (`preview`, `resolving`, `applied`, `aborted`) with audited events (`PATCH .../merge-sessions/{id}`).

---

## P1-02: Conflict List UI with Per-Conflict Resolution Controls ✓

**GitHub:** [#2574](https://github.com/KenSuenobu/objectified-commercial/issues/2574) · **Epic:** [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559) · **Status:** shipped (ADE **Versions** merge dialog: table with path, conflict **type** from preview `kinds`, resolution badge, **Mine** / **Theirs** / **Manual** with local session state; Manual opens detail placeholder for future merge-session submit)

### Problem statement
Users cannot resolve conflicts efficiently from a structured UI workflow.

### Scope
Render conflicts with actions per item (`Use mine`, `Use theirs`, `Manual`).

### Acceptance criteria
- Conflict list shows path, type, and current resolution state.
- User can apply resolution choice per conflict.
- Unresolved conflicts are clearly highlighted.

---

## P1-03: Bulk Resolve Actions for Conflict Groups ✓

**GitHub:** [#2575](https://github.com/KenSuenobu/objectified-commercial/issues/2575) · **Epic:** [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559) · **Status:** shipped (ADE merge conflict panel: path + conflict-type filters; **Bulk (shown)** and **Bulk (all)** mine/theirs; per-row overrides unchanged)

### Problem statement
Resolving many similar conflicts one-by-one is slow and error-prone.

### Scope
Add group-level and global bulk actions for repetitive conflict types.

### Acceptance criteria
- User can apply bulk `mine/theirs` for a filtered conflict group.
- Bulk operation updates all affected rows immediately in UI.
- User can still override any single conflict after bulk apply.

---

## P1-04: Block Merge Apply Until All Conflicts Resolved

**GitHub:** [#2576](https://github.com/KenSuenobu/objectified-commercial/issues/2576) · **Epic:** [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559) · **Status:** shipped (REST structured 409 + Studio gating)

### Problem statement
Partial conflict resolution can produce invalid merges.

### Scope
Enforce server and UI checks that prevent merge apply with unresolved conflicts.

### Acceptance criteria
- Merge apply request with unresolved conflicts is rejected.
- UI disables apply button until all conflicts are resolved.
- Error copy clearly states unresolved conflict count.

---

## P1-05: Add Workflow Audit Ledger Table + Write Path

**GitHub:** [#2577](https://github.com/KenSuenobu/objectified-commercial/issues/2577) · **Epic:** [#2560](https://github.com/KenSuenobu/objectified-commercial/issues/2560)

### Problem statement
Commit/push/pull/merge actions are not consistently auditable from a single source.

### Scope
Create workflow audit table and write an event on every workflow action outcome.

### Acceptance criteria
- Each action writes one audit event with `action`, `outcome`, `actor`, `version`, timestamp.
- Failures write events with structured error details.
- Query by version and date range is indexed and performant.

**Status:** Shipped — `odb.workflow_audit` migration (`objectified-db/scripts/20260412-120000.sql`); `Database.insert_workflow_audit` / `list_workflow_audit_for_version`; writes from push (`version.push`), pull (`version.pull` on revision GET), merge (`version.merge`), rollback (`version.rollback`).

---

## P1-06: Audit API Endpoint with Filter + Pagination

**GitHub:** [#2578](https://github.com/KenSuenobu/objectified-commercial/issues/2578) · **Epic:** [#2560](https://github.com/KenSuenobu/objectified-commercial/issues/2560)

### Problem statement
Audit data exists but cannot be consumed efficiently in UI or external tooling.

### Scope
Expose paginated REST endpoint for audit ledger with common filters.

### Acceptance criteria
- Supports filters by action, actor, outcome, version, date range.
- Supports cursor/offset pagination and total/next metadata.
- Response shape is stable and documented.

**Status:** Shipped — `GET /v1/versions/{tenant}/workflow-audit` (filters, offset + cursor pages, `schemaVersion` envelope); see `objectified-rest/docs/WORKFLOW_AUDIT_API.md`.

---

## P1-07: History Search and Filter in Timeline Panel

**GitHub:** [#2579](https://github.com/KenSuenobu/objectified-commercial/issues/2579) · **Epic:** [#2561](https://github.com/KenSuenobu/objectified-commercial/issues/2561)

### Problem statement
Large commit histories are difficult to navigate without filtering.

### Scope
Add search/filter controls for message, author, and date range.

### Acceptance criteria
- History can be filtered by message text and author.
- Date range filter returns only matching revisions.
- Empty state is user-friendly and reset is one click.

**Status:** Shipped — ADE **Versions** **Timeline** bar (search, author, From/To dates, **Reset**); table + revision graph respect the same filtered set; empty state + reset when nothing matches. REST: **`GET /v1/versions/{tenant}/{projectId}`** supports **`q`**, **`creatorId`**, **`createdAfter`**, **`createdBefore`** (database-side filter for scale / API clients).

---

## P1-08: Compare Selected Revision with Current

**GitHub:** [#2580](https://github.com/KenSuenobu/objectified-commercial/issues/2580) · **Epic:** [#2561](https://github.com/KenSuenobu/objectified-commercial/issues/2561)

### Problem statement
Users need quick impact review before rollback or branch actions.

### Scope
Add `Compare with current` action for any revision in history.

### Acceptance criteria
- Compare action loads diff view for selected revision vs current.
- Diff view supports both light and dark themes.
- User can return to timeline without losing filter state.

**Status:** Shipped — ADE **Versions** table row menu **Compare with current** opens the existing **Compare Version Schemas** dialog; diff is **selected revision (base) → latest head** (max `created_at` among revisions returned for the project / lifecycle filter). Overlay and side-by-side diff use existing **light/dark** Tailwind styling; closing the dialog does not reset **Timeline** search/author/date filters.

---

## P1-09: Rollback Confirmation Dialog with Impact Summary

**GitHub:** [#2581](https://github.com/KenSuenobu/objectified-commercial/issues/2581) · **Epic:** [#2561](https://github.com/KenSuenobu/objectified-commercial/issues/2561)

### Problem statement
Rollback is high risk and currently lacks a clear impact confirmation step.

### Scope
Add Radix confirmation dialog showing target revision and changed entity count.

### Acceptance criteria
- Dialog displays revision id, timestamp, and impact summary.
- User must explicitly confirm rollback action.
- Successful rollback creates a new revision and refreshes timeline.

**Status:** Shipped — **ADE → Versions** rollback flow keeps the branch **Preview impact** step; **Apply rollback** opens a Radix **`AlertDialog`** with **target revision id**, **UTC commit time**, and **`impactSummary`** from **`POST .../version-branches/rollback-preview`** (`changedEntityCount` plus added / removed / modified OpenAPI schema paths vs the branch tip). **Roll back** runs apply; success closes both dialogs and **`loadVersions`** / **`loadBranches`** refresh the timeline.

---

## P1-10: Rollback Event Audit Persistence

**GitHub:** [#2582](https://github.com/KenSuenobu/objectified-commercial/issues/2582) · **Epic:** [#2561](https://github.com/KenSuenobu/objectified-commercial/issues/2561)

### Problem statement
Rollback events need explicit traceability beyond generic commit history.

### Scope
Persist rollback events with source/target revision and optional reason.

### Acceptance criteria
- Rollback stores `fromRevision`, `toRevision`, actor, and timestamp.
- Reason field is persisted when provided.
- Rollback events are visible via audit API.

**Status:** Shipped — **`workflow_audit.detail`** on **`version.rollback`** includes **`fromRevision`**, **`toRevision`**, optional **`reason`**; **`POST .../version-branches/rollback`** body **`reason`**; row **`actor_id`** and **`created_at`**; **`GET .../workflow-audit`** unchanged (**#2578**). **`metadata.rollback`** may include **`reason`**.

---

## P2-01: Add Branch Protection Rules (No Direct Push / Require Merge)

**GitHub:** [#2583](https://github.com/KenSuenobu/objectified-commercial/issues/2583) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Critical branches need governance to prevent direct unsafe changes.

### Scope
Implement branch protection policy checks on push path.

### Acceptance criteria
- Protected branch can block direct push when policy requires merge path.
- Unauthorized push attempts return policy error with reason.
- Policy can be configured per project/branch pattern.

**Status:** Shipped — **`version_branches.require_merge_path`** and project **`metadata.branchPushPolicy.patterns`** (glob via `fnmatch`); **`POST .../versions/{tenant}/{project}`** returns **403** with **`code: MERGE_PATH_REQUIRED`**; tenant admins may direct-push; **`PATCH /v1/versions/{tenant}/{project}/version-branches/{branchId}`** and Studio API **`PATCH .../version-branches/[branchId]`** set policy (**#2583**).

---

## P2-02: Add Draft Lock Acquisition/Release API

**GitHub:** [#2584](https://github.com/KenSuenobu/objectified-commercial/issues/2584) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Concurrent editing on the same draft can cause conflicting local assumptions.

### Scope
Add lock endpoints for acquire, renew, release, and force release (authorized roles).

### Acceptance criteria
- Lock acquisition succeeds when draft unlocked.
- Second editor receives lock conflict with owner and expiry metadata.
- Lock release and renew update lock state correctly.

**Status:** Shipped — table **`odb.version_draft_lock`** (migration **`20260412-150000.sql`**); **`POST .../{versionId}/draft-lock/acquire|renew|release|force-release`** (JWT required for holder identity; **409** `DRAFT_LOCK_CONFLICT` with **`ownerUserId`** / **`expiresAt`**; tenant-admin **force-release**) (**#2584**).

---

## P2-03: Show Lock State and Owner in Studio Header

**GitHub:** [#2585](https://github.com/KenSuenobu/objectified-commercial/issues/2585) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Editors need immediate awareness of lock ownership to avoid wasted edits.

### Scope
Display lock chip with owner and expiration tooltip in header.

### Acceptance criteria
- Header shows lock status when active.
- Tooltip includes owner identity and expiry.
- UI updates live after acquire/release actions.

**Status:** Shipped — **`GET .../{revisionId}/draft-lock`** (REST); **Studio** header chip + tooltip with owner, countdown, and absolute UTC; **10s** poll + **1s** countdown refresh (**#2585**).

---

## P2-04: Add Published Version Immutability Flag Enforcement

**GitHub:** [#2586](https://github.com/KenSuenobu/objectified-commercial/issues/2586) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Published artifacts should not be editable by default in enterprise environments.

### Scope
Enforce immutability checks for commit/push/rollback on published versions.

### Acceptance criteria
- Published immutable versions reject write actions by default.
- Authorized override path is explicit and auditable.
- Read operations remain unaffected.

**Status:** Shipped — column **`versions.published_immutable`** (migration **`20260412-160000.sql`**; default **true** on publish via **`publishedImmutable`** on **`POST .../publish`**); **409** **`PUBLISHED_IMMUTABLE`** on push (immutable published tip), merge preview/apply, rollback preview/apply unless tenant admin sends **`overridePublishedImmutability`** + optional **`overrideReason`** → **`workflow_audit`** **`version.immutability_override`** (**#2586**).

---

## P2-05: Push Webhook Subscription CRUD

**GitHub:** [#2587](https://github.com/KenSuenobu/objectified-commercial/issues/2587) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Downstream systems (CI, catalogs, gateways) need push event integration setup.

### Scope
Create subscription CRUD for push webhook endpoints with active/inactive control.

### Acceptance criteria
- Users can create, list, update, and disable subscriptions.
- URL validation and duplicate safeguards are enforced.
- Secrets are stored via reference (not plaintext response).

**Status:** Shipped — table **`odb.push_webhook_subscriptions`** (migration **`20260412-170000.sql`**); **GET/POST** **`/v1/push-webhook-subscriptions/{tenant_slug}`**, **GET/PATCH** **`/v1/push-webhook-subscriptions/{tenant_slug}/{subscription_id}`**; **signingSecret** on create/update only; responses include **signingSecretRef**; normalized HTTPS URLs; **409** **`WEBHOOK_URL_DUPLICATE`** on conflict (**#2587**).

---

## P2-06: Webhook Delivery Retry + Dead Letter Status

**GitHub:** [#2588](https://github.com/KenSuenobu/objectified-commercial/issues/2588) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Push webhooks can fail transiently and need reliable retry behavior.

### Scope
Implement retry scheduling, attempt tracking, and dead-letter terminal state.

### Acceptance criteria
- Failed delivery retries with bounded backoff policy.
- Delivery attempt history is persisted per event.
- Terminal failures are marked dead-letter and queryable.

**Status:** Shipped — tables **`odb.push_webhook_delivery_events`**, **`odb.push_webhook_delivery_attempts`**; column **`signing_secret_encrypted`** (Fernet at rest when **`OBJECTIFIED_WEBHOOK_SIGNING_SECRET_ENCRYPTION_KEY`** is set); bounded backoff **10s / 60s / 300s** after failures (up to **4** attempts); background sweep in **objectified-rest**; **GET** **`/v1/push-webhook-subscriptions/{tenant_slug}/deliveries/dead-letter`**, **GET** **`.../deliveries/{event_id}`** (attempt history); migration **`20260412-180000.sql`** (**#2588**).

---

## P2-07: Compatibility Check Engine for Commit and Merge

**GitHub:** [#2589](https://github.com/KenSuenobu/objectified-commercial/issues/2589) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Breaking schema changes can be committed/merged without guardrails.

### Scope
Add compatibility check pass that classifies candidate changes as breaking or non-breaking.

### Acceptance criteria
- Engine returns deterministic classification and rule hits.
- Commit/merge pipelines can call compatibility checks synchronously.
- Results are persisted for later audit/display.

**Status:** Shipped — **`CompatibilityCheckEngine`** (`objectified-rest/src/app/compatibility_engine.py`) wraps **`analyze_schema_compatibility`** with **`ruleHits`** (per-rule counts) and stable fingerprints; **`POST .../compatibility`** includes **`ruleHits`**; successful **push** (with parent) and **merge** append **`workflow_audit`** rows with **`action`** **`schema.compatibility`** and **`detail.pipeline`** **`version.push`** / **`version.merge`** (**#2589**).

---

## P2-08: Compatibility Report UI Panel + Override Reason

**GitHub:** [#2590](https://github.com/KenSuenobu/objectified-commercial/issues/2590) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Users need understandable compatibility output and controlled override workflow.

### Scope
Show compatibility report in commit/merge flow and require justification when override is allowed.

### Acceptance criteria
- Report groups findings by severity and entity path.
- Override (when enabled) requires non-empty justification.
- Override action is logged in audit trail.

**Status:** Shipped — **ADE → Versions** uses **`CompatibilityReportPanel`** (severity → path); merge **override** requires **tenant admin** + **`compatGateOverrideReason`** when **`skipCompatGate`** and **`compatGateOnMerge`**; **`workflow_audit`** **`version.compat_gate_override`** (**#2590**); **Commit** dialog copy for post-commit **`schema.compatibility`** audit.

---

## P2-09: Pull Options for Headless/CI Clients

**GitHub:** [#2591](https://github.com/KenSuenobu/objectified-commercial/issues/2591) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Automation clients need payload selection controls to reduce unnecessary transfer.

### Scope
Support include/exclude options on pull for non-UI consumers.

### Acceptance criteria
- Pull request can specify include/exclude sections.
- Returned payload respects option set and remains schema-valid.
- Defaults remain backward compatible for existing clients.

**Status:** Shipped — **GET** `.../v1/versions/{tenant}/{project}/{revisionId}` and **GET** `.../by-version/{versionLine}` support **`includeSections`** and **`excludeSections`** (comma-separated: `core`, `commit`, `publish`, `lineage`, `governance`, `creator`, `project`, `timestamps`). Mutually exclusive; core identifiers always returned; **307** successor redirect preserves query (**#2591**). Strong **ETag** unchanged vs full body (**#2568**).

---

## P2-10: Delta Pull Endpoint (Changes Since Revision)

**GitHub:** [#2592](https://github.com/KenSuenobu/objectified-commercial/issues/2592) · **Epic:** [#2562](https://github.com/KenSuenobu/objectified-commercial/issues/2562)

### Problem statement
Full pulls are expensive for large versions when clients only need recent changes.

### Scope
Implement delta pull using `sinceRevisionId` input.

### Acceptance criteria
- Delta response returns only changed entities since specified revision.
- Invalid or unknown revision id returns clear validation error.
- Applying delta yields same effective state as full pull at target head.

**Status:** Shipped — **GET** `.../v1/versions/{tenant}/{project}/{revisionId}` and **GET** `.../by-version/{versionLine}` accept **`sinceRevisionId`**. JSON includes **`schemaPullDelta`** (`removedSchemaNames`, **`schemas`** map of full head fragments for touched entities, **`guarantee`** text). **400** codes: **`UNKNOWN_REVISION_ID`**, **`REVISION_PROJECT_MISMATCH`**, **`SINCE_NOT_ANCESTOR_OF_HEAD`**. Same strong **ETag** as full pull (**#2568**); **307** successor redirect preserves query (**#2591**).

---

## Notes for implementation (issues created on GitHub)

- **Pack labels:** `roadmap-gitlike`, `git-behavior` (plus `epic` on epic issues). Area labels include `rest`, `database`, `ui`, `typescript`, `python`, `mvp` where applicable.
- One GitHub issue per roadmap row (see **GitHub tracking** above); do not merge adjacent tickets into one issue.
- Require tests per issue:
  - DB migration coverage in `objectified-db`
  - API tests in `objectified-rest`
  - UI tests in `objectified-ui` for all user-facing workflows.