# Planned Feature Roadmap — Git-Like Improvements

## Purpose

This document plans the next wave of git-like improvements for the ADE
Designer canvas. It builds on the shipped
`docs/FUTURE_FEATURE_ROADMAP_GITLIKE.md` pack (P0-01 … P2-10) and targets
the gaps that still make the in-product workflow feel different from the
`git` command line:

1. **No first-class branch picker on the canvas** — branch switching
   currently requires leaving Designer and opening the Versions dashboard.
2. **No concept of a "default / main" branch** — every branch is peer, so
   there is no way to say "how many commits behind main am I?".
3. **No divergence (ahead / behind) indicator** — the existing
   `N your revisions toward head` chip walks the linear parent chain, not
   a branch-vs-branch diff.
4. **Commit action is buried** — `Commit new revision…` is an item inside
   the `DesignerCanvasGitMenu` dropdown; iteration → commit loops feel
   heavier than `git commit -m`.
5. **No "sync from main"** — bringing upstream changes into a working
   branch requires manual navigation to the Versions dashboard and the
   `Merge branches` dialog.

The tickets below make the canvas feel like working against a git remote:
pick a branch, see ahead / behind, commit with a message, sync from main,
all without leaving Designer.

---

## Scope anchor — what already ships

| Concern | Status | Source |
|---|---|---|
| Commit dialog (message, changelog, external ref, bump) | **Shipped** | `CommitRevisionDialog`, P0-02 |
| Branch creation from revision | **Shipped** | P0-08 / P0-09 |
| Stale-head conflict banner + pull CTA | **Shipped** | P0-05 |
| Merge preview + conflict resolution UI | **Shipped** | P0-10 / P1-01 … P1-04 |
| Branch push protection (`require_merge_path`) | **Shipped** | P2-01 |
| Draft lock + header chip | **Shipped** | P2-02 / P2-03 |
| Canvas revision + sync dropdown | **Shipped** | `DesignerCanvasGitMenu` |

The tickets below do **not** duplicate any of the above; they re-use the
existing REST envelopes (e.g. `STALE_HEAD`, merge-preview, push-webhook)
wherever possible.

---

## Labels

Reuse labels from `docs/FUTURE_FEATURE_ROADMAP_GITLIKE.md`:
`roadmap-gitlike`, `git-behavior`, `version-control`, `ui`, `rest`,
`database`, `typescript`, `mvp`.

One new label is proposed — `branch-workflow` — to distinguish this pack
from the original git-like roadmap in issue searches. Each ticket caps at
**five labels** (the GitHub issue list style); the label set per ticket is
listed in its header.

New labels introduced by this pack:

- `branch-workflow` — touches default-branch, branch picker, divergence,
  or sync-from-main flows.

---

## Delivery order (priority)

Tickets are listed in the order they should be implemented. Each depends
on the ones above it to be meaningful in isolation.

| # | Ticket | MVP / Enterprise | Depends on |
|---|---|---|---|
| ~~GLI-01~~ | ~~Designate a default (main) branch per project~~ ([#2720](https://github.com/KenSuenobu/objectified-commercial/issues/2720)) | **MVP** (completed) | — |
| ~~GLI-02~~ | ~~Branch divergence API (`ahead` / `behind` / `mergeBase`)~~ ([#2721](https://github.com/KenSuenobu/objectified-commercial/issues/2721)) | **MVP** (completed) | GLI-01 |
| ~~GLI-03~~ | ~~Canvas branch picker (`checkout`) with current-branch chip~~ ([#2722](https://github.com/KenSuenobu/objectified-commercial/issues/2722)) | **MVP** (completed) | GLI-01 |
| ~~GLI-04~~ | ~~Ahead / behind-main chip in canvas header~~ ([#2723](https://github.com/KenSuenobu/objectified-commercial/issues/2723)) | **MVP** (completed) | GLI-02, GLI-03 |
| ~~GLI-05~~ | ~~Prominent "Commit…" action on the canvas toolbar~~ ([#2724](https://github.com/KenSuenobu/objectified-commercial/issues/2724)) | **MVP** (completed) | GLI-03 |
| ~~GLI-06~~ | ~~"Sync from main" one-click action~~ ([#2725](https://github.com/KenSuenobu/objectified-commercial/issues/2725)) | **MVP** (completed) | GLI-02, GLI-03 |
| ~~GLI-07~~ | ~~Branch status popover (`git status` style summary)~~ ([#2726](https://github.com/KenSuenobu/objectified-commercial/issues/2726)) | **MVP** (completed) | GLI-02, GLI-03, GLI-05 |
| ~~GLI-08~~ | ~~Auto-protect the default branch (require merge path)~~ ([#2727](https://github.com/KenSuenobu/objectified-commercial/issues/2727)) | **Enterprise** (completed) | GLI-01 |
| ~~GLI-09~~ | ~~Recent-activity ticker for current branch~~ ([#2728](https://github.com/KenSuenobu/objectified-commercial/issues/2728)) | **Enterprise** (completed) | GLI-03 |
| GLI-10 | Keyboard palette for git actions (CLI muscle memory) | **Enterprise** | GLI-03, GLI-05, GLI-06 |

MVP (first major release) = GLI-01 → GLI-07. Enterprise (later releases)
= GLI-08 → GLI-10.

### GitHub issue mapping (created 2026-04-18)

| Order | Ticket | Parent Epic | GitHub issue |
|---|---|---|---|
| E1 | MVP Branch Workflow Epic | — | [#2718](https://github.com/KenSuenobu/objectified-commercial/issues/2718) |
| E2 | Enterprise Branch Workflow Epic | — | [#2719](https://github.com/KenSuenobu/objectified-commercial/issues/2719) |
| 1 | GLI-01 | #2718 | [#2720](https://github.com/KenSuenobu/objectified-commercial/issues/2720) ✅ |
| 2 | GLI-02 | #2718 | [#2721](https://github.com/KenSuenobu/objectified-commercial/issues/2721) ✅ |
| 3 | GLI-03 | #2718 | [#2722](https://github.com/KenSuenobu/objectified-commercial/issues/2722) ✅ |
| 4 | GLI-04 | #2718 | [#2723](https://github.com/KenSuenobu/objectified-commercial/issues/2723) ✅ |
| 5 | GLI-05 | #2718 | [#2724](https://github.com/KenSuenobu/objectified-commercial/issues/2724) ✅ |
| 6 | GLI-06 | #2718 | [#2725](https://github.com/KenSuenobu/objectified-commercial/issues/2725) ✅ |
| 7 | GLI-07 | #2718 | [#2726](https://github.com/KenSuenobu/objectified-commercial/issues/2726) ✅ |
| 8 | GLI-08 | #2719 | [#2727](https://github.com/KenSuenobu/objectified-commercial/issues/2727) ✅ |
| 9 | GLI-09 | #2719 | [#2728](https://github.com/KenSuenobu/objectified-commercial/issues/2728) ✅ |
| 10 | GLI-10 | #2719 | [#2729](https://github.com/KenSuenobu/objectified-commercial/issues/2729) ✅ |

### Parallel execution map

Items in the same row can proceed in parallel once their upstream ticket
is merged. Tickets in different rows depend on earlier rows as listed in
the table above.

| Wave | Parallel tracks |
|------|-----------------|
| W0 | GLI-01 |
| W1 | GLI-02, GLI-03 (share a shared `BranchRow` type contract) |
| W2 | GLI-04, GLI-05, GLI-06 (touch different canvas areas) |
| W3 | GLI-07 (needs W2 data), GLI-08 (REST only — back-end track) |
| W4 | GLI-09, GLI-10 (UI polish, independent of each other) |

---

## How to test this roadmap end-to-end

Once all MVP tickets ship, the following walk-through should pass on a
fresh project:

1. Create a new project; confirm a `main` branch is auto-created with
   `is_default = true` (**GLI-01**).
2. Open the Designer canvas; a branch chip in the canvas chrome reads
   `main` (**GLI-03**).
3. Create a branch `feature/x` from the current tip; the chip switches to
   `feature/x` automatically (**GLI-03**).
4. Commit twice on `feature/x` using the toolbar `Commit…` button
   (**GLI-05**); the ahead chip reads `↑ 2 main` (**GLI-04**).
5. Switch back to `main` from the chip dropdown; commit once on `main`;
   switch to `feature/x`; chip now reads `↑ 2 ↓ 1 main` (**GLI-04**).
6. Click `Sync from main` (**GLI-06**); merge preview opens; resolve any
   conflicts; after apply the chip reads `↑ 3 ↓ 0 main`.
7. Click the branch chip → status popover shows branch, ahead / behind,
   unpushed, lock, recent commits (**GLI-07**).

Per-ticket test steps are included in each section below.

---

## GLI-01: Designate a default (main) branch per project

**Summary:** Add a first-class "default branch" concept to projects so
the product can reason about `main` the way git does.

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`database`, `rest`

**MVP:** Yes.

**Parallelism:** Track A — back-end only; nothing else depends on it for
wave W0 but every later ticket reads `is_default` or an equivalent.

### Problem statement

`version_branches` rows are peer today. Nothing on the `projects` row or
on `version_branches` marks one branch as "the trunk". As a result:

- New tenants see a blank branch list until they create one manually.
- The UI cannot show `↑N ↓M main` because it does not know which branch
  `main` is.
- Branch protection (P2-01, shipped) has to be configured per-branch even
  on day one.

### Scope

- Add `is_default BOOLEAN NOT NULL DEFAULT FALSE` to
  `apiome.version_branches`.
- Add a partial unique index guaranteeing at most one `is_default = TRUE`
  per `project_id`.
- Migration: for every existing project, promote the branch whose
  `tip_version_id` equals the project's current head (latest
  `created_at`) to `is_default = TRUE`. If a project has no
  `version_branches` row, create one named `main` pointing at the head.
- REST: `PATCH /v1/versions/{tenant}/{projectId}/version-branches/{branchId}`
  accepts `isDefault: true`; setting it flips the previous default to
  `false` atomically.
- REST: on first commit of a brand-new project, auto-create a `main`
  branch with `is_default = true` if none exists.
- UI: the Versions dashboard named-branches panel shows a "default"
  badge on the default branch; tenant admin can promote another branch.

### Technical specifications

```
apiome.version_branches
┌───────────────────────────────┐
│ id               UUID PK      │
│ project_id       UUID FK      │
│ name             VARCHAR(255) │
│ tip_version_id   UUID FK      │
│ is_default       BOOLEAN   ←──┤  new column
│ branched_from…   UUID FK      │
│ require_merge_…  BOOLEAN      │ (from P2-01)
│ created_at       TIMESTAMPTZ  │
│ updated_at       TIMESTAMPTZ  │
└───────────────────────────────┘

  Invariant (partial unique index):
    CREATE UNIQUE INDEX uq_version_branches_default_per_project
      ON apiome.version_branches(project_id)
      WHERE is_default = TRUE;
```

Migration file naming: follow the existing
`apiome-db/scripts/YYYYMMDD-HHMMSS.sql` convention.

Error envelope for promote:

```
409 BRANCH_DEFAULT_CONFLICT when two rows attempt is_default=true
400 BRANCH_NOT_IN_PROJECT   when branch does not belong to project
```

### Acceptance criteria

- `version_branches.is_default` exists and is `TRUE` on exactly one row
  per project.
- The migration is idempotent (safe to re-run) and backfills every
  legacy project.
- `PATCH …/version-branches/{id}` with `isDefault=true` flips the
  previous default to `false` atomically.
- A new project's first commit creates `main` with `is_default=true`.
- `GET …/version-branches` returns `isDefault` on every row.

### Test plan

1. Run the migration against a database snapshot; confirm every existing
   project has exactly one `is_default=true` row.
2. Create a new project via the UI; issue one commit; query
   `version_branches` — a `main` row exists with `is_default=true`.
3. Create a second branch `hotfix`; `PATCH` it to `isDefault=true`;
   confirm the previous `main` row is now `false` and `hotfix` is
   `true`.
4. Attempt (via raw SQL) to insert a second `is_default=true` row; the
   partial unique index must reject it.
5. `GET …/version-branches` returns `isDefault` on every row.

---

## GLI-02: Branch divergence API (`ahead` / `behind` / `mergeBase`)

**Summary:** Add a REST endpoint that returns how many revisions a branch
is ahead and behind another branch (defaulting to the project's default
branch).

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`rest`, `mvp`

**MVP:** Yes.

**Parallelism:** Track B — back-end only. Can be built in parallel with
GLI-03 once the branch-row contract is agreed.

### Problem statement

The canvas cannot render `↑N ↓M main` because no server endpoint computes
it. The current "↑N your revisions toward head" chip walks
`parent_version_id` from head toward selection; that is not the same as
branch-to-branch divergence (it ignores side branches, tagged revisions,
and merge parents).

### Scope

- Add `GET /v1/versions/{tenant}/{projectId}/version-branches/{branchId}/divergence`
  (optional query `against=<branchId>` — defaults to the project's
  default branch).
- Response shape:

```json
{
  "branch":        { "id": "…", "name": "feature/x", "tipRevisionId": "…" },
  "against":       { "id": "…", "name": "main",      "tipRevisionId": "…" },
  "mergeBase":     { "revisionId": "…", "createdAt": "…" },
  "ahead":         3,
  "behind":        1,
  "aheadSample":   [ { "revisionId": "…", "shortMessage": "…" }, … ],
  "behindSample":  [ { "revisionId": "…", "shortMessage": "…" }, … ]
}
```

- Sample arrays are capped at `ADE_DIVERGENCE_SAMPLE_MAX = 5` newest-first
  revisions on each side.
- Use an in-database recursive CTE against
  `versions(parent_version_id, merge_parent_version_id)` to find the
  merge base (lowest common ancestor) and the two side counts.
- Cache-friendly: strong `ETag = sha1(branch.tip || against.tip)`; return
  `304` on `If-None-Match`.

### Technical specifications

```
  GET .../version-branches/{branchId}/divergence?against={otherBranchId}

  ┌───────────────────────────────────────────┐
  │        recursive CTE                      │
  │                                           │
  │   ancestors(branch.tip) = { set A }       │
  │   ancestors(against.tip) = { set B }      │
  │                                           │
  │   merge_base = newest by created_at       │
  │                 in (A ∩ B)                │
  │                                           │
  │   ahead  = |{ A \ (ancestors(merge_base) ∪ {merge_base}) }|
  │   behind = |{ B \ (ancestors(merge_base) ∪ {merge_base}) }|
  └───────────────────────────────────────────┘

  400 SELF_DIVERGENCE            when branchId == againstId
  400 BRANCHES_PROJECT_MISMATCH  when the two branches are in
                                  different projects
  404 BRANCH_NOT_FOUND
```

### Acceptance criteria

- Endpoint returns `ahead` / `behind` / `mergeBase` for any pair of
  branches in the same project.
- Without `against`, the project's default branch (GLI-01) is used.
- Self-divergence (`branchId == againstId`) returns `400`.
- Response is deterministic and returns `304` when tips are unchanged.
- CTE is bounded (tested against a project with ≥ 10k revisions in under
  500 ms on a standard tenant DB).

### Test plan

1. Create two branches sharing a merge base; issue `N` commits on each.
   Call the endpoint — assert `ahead=N` and `behind=N`.
2. Call without `against`; confirm the default branch from GLI-01 is
   used automatically.
3. Call with identical branch ids; expect `400 SELF_DIVERGENCE`.
4. Call twice with identical `ETag`; the second call returns `304`
   with empty body.
5. Seed a synthetic project with 10 000 revisions; confirm the endpoint
   returns in < 500 ms (add to REST perf tests).

---

## GLI-03: Canvas branch picker (`checkout`) with current-branch chip

**Summary:** Replace the "Current revision" panel at the top of
`DesignerCanvasGitMenu` with a branch-first picker that lets users
checkout another branch without leaving the canvas.

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`ui`, `mvp`

**MVP:** Yes.

**Parallelism:** Track C — UI only. Depends on GLI-01 (`isDefault` on
branches) but can stub against a hard-coded default while GLI-01 ships.

### Problem statement

The canvas shows the current *revision* label but not the current
*branch*. Switching branches requires navigating to
`/ade/dashboard/versions` and clicking a branch row. This breaks the
iteration loop and does not match the `git checkout <branch>` mental
model.

### Scope

- Extend `StudioContext` with `selectedBranchId`,
  `setSelectedBranchId`, and a `branches` cache per project.
- New `BranchPickerChip` component replaces the "Current revision"
  header inside the canvas git menu **and** gains a stand-alone
  lightweight chip in the floating canvas toolbar (next to the git
  menu).
- Clicking the chip opens a Radix popover listing branches:
  - Default branch first (badge from GLI-01).
  - Active branch highlighted.
  - Dirty-canvas warning if selecting a different branch would drop
    unsaved layout (existing `syncLocalDirty`).
- Selecting a branch: `setSelectedVersionId(branch.tip_version_id)`,
  `setSelectedBranchId(branch.id)`, call `triggerCanvasRefresh`.
- Honour `isReadOnly` (`versions.published`) on checkout.

### Technical specifications

```
  Canvas floating toolbar (today):
  ┌──────────┬──────────┬──────────┐
  │ Layout   │ Export   │ GitMenu  │
  └──────────┴──────────┴──────────┘

  After GLI-03:
  ┌──────────┬──────────┬────────────────────┬──────────┐
  │ Layout   │ Export   │ ⌥ branch: main   ▾│ GitMenu  │
  └──────────┴──────────┴────────────────────┴──────────┘
                             │
                             ▼ (Radix popover)
                   ┌──────────────────────────────┐
                   │  ✓ main          (default)   │
                   │    feature/checkout-x        │
                   │    hotfix/2025-q4            │
                   │  ─────────────────────────   │
                   │  + Create new branch…        │
                   └──────────────────────────────┘
```

- Popover fetches `/api/projects/{id}/version-branches` on open; cached
  for the lifetime of the popover.
- Keyboard: `↑ / ↓` to move, `Enter` to checkout, `Esc` to close.
- Dirty-state guard reuses the existing `syncLocalDirty` flag and the
  same Radix `AlertDialog` pattern as the rollback flow (GLI-07 may
  extend this).

### Acceptance criteria

- The canvas chrome renders a branch chip with the current branch name.
- Clicking it lists every branch; checkout switches the canvas.
- `Published` branches open as read-only and the canvas respects it.
- If `syncLocalDirty = true`, a warning dialog explains the unsaved
  changes before switching.
- The chip updates after commit (new tip) and after merge.
- Works in both light and dark themes.

### Test plan

1. Open a project with two branches; confirm the chip shows the branch
   whose tip matches the current selection.
2. Click the chip; select the other branch; canvas refreshes and the
   chip updates.
3. Edit a class (dirty the canvas) without saving; click the chip;
   confirm the dirty-state warning appears.
4. Checkout a branch whose tip is `published=true`; confirm the
   canvas toolbar shows the read-only indicator.
5. Commit on the active branch; confirm the chip keeps the same
   branch name but the chip tooltip shows the new tip revision id.

---

## GLI-04: Ahead / behind-main chip in canvas header

**Summary:** Show the active branch's ahead / behind counts versus the
default branch as a compact chip in the canvas chrome.

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`ui`, `mvp`

**MVP:** Yes.

**Parallelism:** Depends on GLI-02 (divergence API) + GLI-03 (selected
branch context).

### Problem statement

Users on a feature branch cannot see from the canvas how far they have
drifted from `main`. They rely on going to the Versions dashboard to
compare. A native chip closes the gap.

### Scope

- New `BranchDivergenceChip` component next to `BranchPickerChip`.
- Fetches `GET …/version-branches/{branchId}/divergence` (GLI-02) on
  selected-branch change, and on every commit / merge / rollback
  success (uses the existing `triggerSidebarRefresh` signal as the
  refresh trigger).
- Rendering logic:
  - `ahead = 0 && behind = 0` → chip reads `in sync with main` (muted).
  - `ahead > 0 && behind = 0` → green chip `↑3 ahead of main`.
  - `ahead = 0 && behind > 0` → amber chip `↓2 behind main`.
  - `ahead > 0 && behind > 0` → indigo chip `↑3 ↓2 diverged from main`.
  - On the default branch itself → chip reads `main` with no counts.
- Tooltip lists up to 5 newest-first commits on each side
  (from `aheadSample` / `behindSample`).
- Click opens the existing `Compare Version Schemas` dialog with
  `base = mergeBase`, `head = branch.tip`.

### Technical specifications

```
  ┌─────────────────────────────────────────────────────┐
  │ ⌥ branch: feature/x   ▾   [↑ 3  ↓ 2  vs main]  (*) │
  └─────────────────────────────────────────────────────┘
                              │
                              └── tooltip:
                                   Ahead (3 of your commits)
                                     • "add spec field" (r-a4…)
                                     • "rename order.id" (r-b2…)
                                     • "refactor schema" (r-c3…)
                                   Behind (2 upstream commits)
                                     • "main: fix nullable" (r-e7…)
                                     • "main: ci bump"     (r-e6…)
```

### Acceptance criteria

- Chip renders only when the active branch ≠ default branch.
- Counts update within 1 s of commit / merge / rollback.
- Tooltip lists up to 5 commits per side, newest-first.
- Clicking the chip opens the Compare dialog pre-populated with the
  merge base and branch tip.
- `Esc` closes the tooltip; chip is keyboard focusable.

### Test plan

1. On a brand-new branch, confirm the chip reads `in sync with main`.
2. Commit twice on the branch; chip reads `↑ 2 ahead of main` within
   1 s.
3. Switch to `main`, commit once, switch back to the feature branch;
   chip reads `↑ 2 ↓ 1 diverged from main`.
4. Click the chip; the Compare dialog opens with the merge base as
   base.
5. Checkout `main`; the chip disappears (the default branch has no
   "vs main" comparison).

---

## GLI-05: Prominent "Commit…" action on the canvas toolbar

**Summary:** Surface a dedicated `Commit…` button on the canvas toolbar
(outside the git dropdown) that opens the existing
`CommitRevisionDialog` pre-scoped to the active branch.

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`ui`, `mvp`

**MVP:** Yes.

**Parallelism:** Depends on GLI-03 (active branch known to the canvas).
Independent of GLI-04 and GLI-06 UI.

### Problem statement

Committing is the canvas's most frequent git-like action but it is two
clicks deep inside the `DesignerCanvasGitMenu`. `git commit -m` is one
command — the canvas should be one button.

### Scope

- Add `CommitButton` to the floating canvas toolbar, positioned
  immediately after the branch chip.
- Click opens `CommitRevisionDialog` with `selectedBranchId` from
  `StudioContext` pre-selected (hides the branch dropdown inside the
  dialog when the active branch is already known).
- Keyboard shortcut `Cmd/Ctrl + Enter` opens the same dialog (active
  only when the canvas has focus).
- Button shows a subtle dirty-dot when `syncLocalDirty = true`.
- Disabled when `isReadOnly = true` with tooltip "This revision is
  read-only. Pull the latest to commit new work."

### Technical specifications

```
  After GLI-03 + GLI-05:
  ┌─────┬─────┬──────────────┬───────────────┬──────────┬─────┐
  │ Lay │ Exp │ branch: main │ [↑3 ↓2 main]  │ ● Commit │ Git │
  └─────┴─────┴──────────────┴───────────────┴──────────┴─────┘

  ● = dirty indicator (only when unsaved canvas layout exists)
```

- Reuse the existing `CommitRevisionDialog`; extend its props with
  `lockedBranchId?: string` so the inline branch dropdown is hidden
  when the branch is already known.
- Wire `onCreated` to trigger the divergence refresh from GLI-04.

### Acceptance criteria

- `Commit…` appears on the canvas toolbar whenever a branch is active.
- Clicking opens the dialog with the current branch fixed.
- `Cmd/Ctrl + Enter` opens the same dialog without moving the cursor.
- Button is disabled when `isReadOnly = true`.
- The dirty-dot appears when `syncLocalDirty = true` and clears on
  successful commit.

### Test plan

1. Edit a class on the canvas without saving; confirm the commit
   button shows the dirty dot.
2. Click the button; confirm the dialog opens with the active branch
   already selected and the inline branch dropdown hidden.
3. Submit the commit with a message; confirm the dot disappears and
   the branch chip updates to the new tip.
4. Press `Cmd/Ctrl + Enter` with focus on the canvas; the same dialog
   opens.
5. Checkout a `published` branch; confirm the button is disabled with
   the read-only tooltip.

---

## GLI-06: "Sync from main" one-click action

**Summary:** Add a "Sync from main" action in the canvas git menu that
runs the existing merge-preview flow from the default branch into the
active branch and opens the existing merge-resolution UI.

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`ui`, `mvp`

**MVP:** Yes.

**Parallelism:** Depends on GLI-02 (divergence) + GLI-03 (active
branch). Can be built in parallel with GLI-04 and GLI-05.

### Problem statement

To pick up upstream changes, users must leave the canvas, find the
`Merge branches` dialog in the Versions dashboard, pick source + target
branches by hand, and run preview. This round-trip is the single biggest
friction point for keeping feature branches current.

### Scope

- Add `Sync from main` menu item in `DesignerCanvasGitMenu` under the
  existing `History and sync` section.
- Enabled only when `behind > 0` (reads the GLI-04 cached divergence
  result).
- On click, call merge-preview with
  `source = defaultBranch, target = activeBranch` and open the existing
  `MergeBranchesDialog` with both branches pre-selected.
- On successful merge apply, update the divergence chip and
  reload the canvas.

### Technical specifications

```
  DesignerCanvasGitMenu → "History and sync"
  ┌──────────────────────────────────────────────┐
  │ Show history graph…                          │
  │ Switch to latest revision (pull)             │
  │ Refresh revision list                        │
  │ ▶ Sync from main  (↓2)           ← new item  │
  │ Open Versions dashboard                      │
  └──────────────────────────────────────────────┘

  Disabled state (when behind = 0):
   "Sync from main (up-to-date)"
```

- Re-use `MergeBranchesDialog`; extend with an optional
  `preselectSource` / `preselectTarget` prop pair.
- Default branch is read from GLI-01; falls back to the branch with the
  oldest `created_at` until GLI-01 ships (feature-flagged).

### Acceptance criteria

- Menu item reads `Sync from main (↓N)` when `behind = N > 0`.
- Menu item is disabled with a tooltip when `behind = 0`.
- Click opens the merge dialog with source = default, target = active.
- On successful apply, the divergence chip drops to `↓0`.

### Test plan

1. Commit on `main`, then checkout `feature/x`; menu reads
   `Sync from main (↓1)`.
2. Click; confirm the merge dialog opens pre-scoped to
   `main → feature/x`.
3. Resolve any conflicts and apply; confirm the chip updates to
   `↓ 0`.
4. With `behind = 0`, confirm the menu item is disabled and shows the
   `up-to-date` tooltip.

---

## GLI-07: Branch status popover (`git status` style summary)

**Summary:** A Radix popover launched from the branch chip that shows a
CLI-style status summary for the active branch.

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`ui`, `mvp`

**MVP:** Yes (trailing — ship with or just after GLI-06).

**Parallelism:** Depends on GLI-02, GLI-03, GLI-05. Purely UI composition
of already-fetched data.

### Problem statement

Once the chip, divergence, commit, and sync features ship, users want a
single spot that summarizes "what does this branch look like right now?"
— the equivalent of running `git status`.

### Scope

- Hover-delay popover on the branch chip (or click on touch).
- Sections:
  1. **Branch** — name, default badge, tip revision id (short), last
     commit author and relative time.
  2. **Divergence** — ahead / behind counts with the sample list from
     GLI-02.
  3. **Working copy** — `Dirty layout? yes/no` (from `syncLocalDirty`)
     and `Uncommitted schema edits?` (hook into existing dirty flags).
  4. **Locks** — re-use the `DraftLockHeaderChip` payload (P2-03) to
     show any active lock.
  5. **Recent commits** — last five entries on this branch.
- Footer link `Open Versions dashboard` for deep-dive actions.

### Technical specifications

```
  ┌ branch: feature/x ──────────────────────────────── ●    ▲
  │                                                         │
  │  Branch                                                 │
  │    feature/x  (not default)                             │
  │    tip  r-91a2…   by Alex · 3 min ago                   │
  │                                                         │
  │  Divergence vs main                                     │
  │    ↑ 3 ahead     ↓ 2 behind                             │
  │    merge base  r-07f1…                                  │
  │                                                         │
  │  Working copy                                           │
  │    dirty layout  ●                                      │
  │    lock          held by Sam · expires in 4m            │
  │                                                         │
  │  Recent                                                 │
  │    r-91a2  add spec field          3m ago               │
  │    r-82b1  refactor schema         28m ago              │
  │    r-80e4  rename order.id         1h ago               │
  │    …                                                    │
  │                                                         │
  │  [ Open Versions dashboard ▸ ]                          │
  └──────────────────────────────────────────────────────── ▼
```

- No new server endpoints; composes data already available from GLI-02,
  GLI-03, and P2-03.
- Popover width is 360 px; scrolls on small screens.

### Acceptance criteria

- Popover opens on hover (delay ≥ 250 ms) and on click.
- All five sections render with the correct values.
- Closing the popover returns focus to the chip.
- No extra REST calls are made that are not already triggered by
  GLI-02 / GLI-03 / P2-03.

### Test plan

1. Hover the branch chip; confirm the popover opens after the delay.
2. Induce each state (dirty layout, active lock, ahead / behind) and
   verify the sections update live.
3. Tab-focus the chip and press `Enter`; the popover opens and
   keyboard focus moves inside.
4. Click `Open Versions dashboard`; the app navigates to
   `/ade/dashboard/versions?projectId=…`.
5. Measure the REST call count with the browser devtools; confirm no
   new endpoints are hit on popover open.

---

## GLI-08: Auto-protect the default branch (require merge path)

**Summary:** When a branch is promoted to `is_default = true` (GLI-01),
automatically set `require_merge_path = true` on that branch and prevent
direct push from non-admins.

**Labels (5):** `roadmap-gitlike`, `branch-workflow`, `git-behavior`,
`rest`, `enterprise`

**MVP:** No — Enterprise release.

**Parallelism:** Depends on GLI-01. Back-end only; can run after GLI-07
ships or in parallel with GLI-09 / GLI-10.

### Problem statement

Today's branch protection (P2-01) must be configured per branch. In an
enterprise tenancy, the default branch should be protected from day one.

### Scope

- On `PATCH …/version-branches/{id}` with `isDefault=true`, set
  `require_merge_path = true` in the same transaction unless the caller
  explicitly sends `requireMergePath=false`.
- On the auto-created `main` branch from GLI-01, set
  `require_merge_path = true` at creation.
- New `workflow_audit` event `version.default_branch_promoted` with
  prior default branch id, new default branch id, and
  `mergePathAutoEnabled` flag.

### Technical specifications

```
  PATCH .../version-branches/{id}
    body: { "isDefault": true }

  Server pseudocode:
    tx:
      row.is_default = true
      prev_default.is_default = false  (partial unique index from GLI-01)
      if row.require_merge_path is not explicit in body:
        row.require_merge_path = true
      audit(version.default_branch_promoted, { prev, next, auto: true })
```

- No UI changes required; the Versions dashboard already renders the
  `Require merge path` toggle from P2-01.

### Acceptance criteria

- Promoting a branch to default turns on `require_merge_path` unless
  explicitly disabled in the same request.
- Auto-created `main` branches have `require_merge_path=true`.
- `workflow_audit` records the promotion with the auto flag.
- Direct push from a non-admin to the default branch returns
  `403 MERGE_PATH_REQUIRED` (unchanged contract from P2-01).

### Test plan

1. Promote a branch to default; confirm `require_merge_path=true` is
   set in the same row.
2. Promote with explicit `requireMergePath=false`; confirm the flag
   respects the override.
3. Create a new project; confirm `main` is auto-protected.
4. As a non-admin, attempt a direct push to `main`; confirm
   `403 MERGE_PATH_REQUIRED`.
5. Query `workflow_audit`; confirm a `version.default_branch_promoted`
   row exists.

---

## GLI-09: Recent-activity ticker for current branch

**Status:** Completed (2026-04-20, #2728).

**Summary:** A small ticker in the canvas chrome showing the last three
commits on the active branch, with deep-links to compare each commit
against the current tip.

**Labels (4):** `roadmap-gitlike`, `branch-workflow`, `ui`, `enterprise`

**MVP:** No — Enterprise release.

**Parallelism:** Depends on GLI-03. Independent of GLI-08 and GLI-10.

### Problem statement

When working in a shared branch, teammates commit continuously. There is
no passive way to learn that the branch has moved unless the editor
opens the Versions dashboard.

### Scope

- New `BranchRecentTicker` component rendered under the canvas chrome
  when the branch chip is in focus (or when hovered).
- Shows three most recent commits on the active branch.
- Each entry deep-links to the compare dialog against the current tip.
- Polls `/api/versions?projectId=…&branchId=…&limit=3` every 30 s
  while the canvas is in the foreground (uses the existing
  `visibilitychange` hook).

### Technical specifications

```
  ┌──── recent on feature/x ───────────────────────────┐
  │  r-91a2  add spec field       by Alex · 3m ago    │
  │  r-82b1  refactor schema      by Sam  · 28m ago   │
  │  r-80e4  rename order.id      by Sam  · 1h ago    │
  └────────────────────────────────────────────────────┘
```

- Polling respects `document.visibilityState`; suspends when the tab is
  hidden.
- Uses the existing `/api/versions` list; no new REST surface required.

### Acceptance criteria

- Ticker renders the last three commits on the active branch.
- Commits from other branches are excluded.
- Polling stops when the tab is hidden.
- Clicking a row opens the compare dialog for that revision versus the
  branch tip.

### Test plan

1. Commit twice on the active branch; the ticker updates within 30 s.
2. Commit on a different branch; the ticker does not update.
3. Switch tabs for 5 minutes; confirm (via devtools network panel)
   that polling is suspended.
4. Click a ticker row; confirm the compare dialog opens for that
   revision vs the branch tip.

---

## GLI-10: Keyboard palette for git actions (CLI muscle memory)

**Status:** Shipped — `GitCommandPalette` in studio layout, handlers via `StudioContext`, shortcuts in `studio-keybindings.ts`.

**Summary:** A `Cmd/Ctrl + G` palette that lists every git-like action
(`commit`, `branch`, `checkout`, `pull`, `sync`, `merge`, `rollback`)
with keyboard-first completion.

**Labels (4):** `roadmap-gitlike`, `branch-workflow`, `ui`, `enterprise`

**MVP:** No — Enterprise release.

**Parallelism:** Depends on GLI-03 / GLI-05 / GLI-06 to route actions.
Independent of GLI-08 and GLI-09.

### Problem statement

Power users coming from the git CLI want keyboard-first access to the
same actions without hunting through menus.

### Scope

- New `GitCommandPalette` component (Radix `Command` / `Dialog`).
- Opened with `Cmd/Ctrl + G` anywhere inside `/ade/studio` surfaces.
- Lists every available git action with fuzzy completion:
  - `commit` → opens `CommitRevisionDialog`.
  - `branch <name>` → creates a branch from the current tip.
  - `checkout <branch>` → switches branch.
  - `pull` → switch to latest revision.
  - `sync` → triggers GLI-06 `Sync from main`.
  - `merge <source>` → opens `MergeBranchesDialog` with source preset.
  - `rollback <rev>` → opens `RollbackBranchDialog`.
- Pressing `?` inside the palette shows a keybinding cheatsheet.

### Technical specifications

```
  Cmd + G
    ┌─ ▸ git ──────────────────────────────┐
    │   commit   ⏎                         │
    │   branch   feature/                  │
    │   checkout <tab to cycle branches>   │
    │   pull                               │
    │   sync                               │
    │   merge    <tab to cycle sources>    │
    │   rollback <tab to cycle revisions>  │
    │   ?  bindings cheatsheet             │
    └──────────────────────────────────────┘
```

- Purely client-side orchestration; every action routes to an existing
  dialog or API.
- Shortcut registration is tracked in
  `apiome-ui/src/app/utils/studio-keybindings.ts` (new file).

### Acceptance criteria

- `Cmd/Ctrl + G` opens the palette on any `/ade/studio` surface.
- Each action dispatches to its existing dialog or orchestration.
- `Esc` closes the palette without side effects.
- `?` inside the palette shows a cheatsheet.
- Keybindings are discoverable from a single file.

### Test plan

1. Press `Cmd/Ctrl + G` on `/ade/studio/editor`; confirm the palette
   opens.
2. Type `commit`; press `Enter`; confirm the commit dialog opens.
3. Type `checkout `; cycle branches with `Tab`; press `Enter`;
   confirm the branch switches.
4. Press `?` inside the palette; the cheatsheet renders.
5. Press `Esc`; the palette closes and the canvas retains focus.

---

## Notes for the issue author

- One GitHub issue per ticket (GLI-01 … GLI-10). Do not fold adjacent
  tickets into a single issue.
- Add the `roadmap-gitlike` label to every issue for search parity with
  the prior pack.
- Tests required on every issue:
  - **DB migration** coverage in `apiome-db` (GLI-01 only).
  - **REST** tests in `apiome-rest` (GLI-01, GLI-02, GLI-08).
  - **UI** tests in `apiome-ui` for every user-facing workflow.
- After each ticket merges, update the **Delivery order** table above
  by striking through the completed row and linking the GitHub issue
  number next to the ticket id.
