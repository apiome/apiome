# Planned Feature Roadmap: Repository Connector

_GitHub issues filed against `KenSuenobu/objectified-commercial`._
_New epics: #2924 · #2925 · #2926 · #2927 · #2928
(`REPO-EPIC-A` … `REPO-EPIC-E`)._
_Use the `repository` label on `KenSuenobu/objectified-commercial` to
filter all Repository Connector work; use `roadmap-repository` to
filter only the tickets defined in this document._

> **Periodic repository scanning, opt-in spec selection, and checksum-bound
> auto-import for the Repository Connector.**
>
> The first generation of the Repository Connector (REPO-1.x through
> REPO-7.x, see _Completed_ below) gave us a tree walker, manifest support,
> SHA-driven scheduler, OpenAPI/Swagger/JSON Schema importers, scan diffs,
> and per-repository UI. What it does **not** yet do is treat the corpus of
> tracked repositories as a first-class _catalog of importable
> specifications_:
>
> - There is no surface that lists, across all tracked repos, _what is
>   importable_ vs. _what failed_ vs. _what is being ignored_.
> - There is no opt-in selection model — every discovered file with a
>   manifest entry is tracked and dispatched, even when the user only
>   wanted to look first.
> - There is no per-spec auto-import switch; a repository is "all in or
>   all out" for tracked branches.
> - Project ↔ version provenance is implied through commit SHA but not
>   anchored to the **content checksum of the imported file**, so a
>   repository whose commit changed but whose spec did not is currently
>   re-imported (wasted work, duplicate version rows, noisy change
>   reports).
> - There is no dashboard signal for repositories whose health regressed
>   between scans (parse errors, manifest errors, revoked tokens,
>   stale checksums, repeated polling failures).
>
> This roadmap fills those five gaps in five epics:
>
> 1. **Epic A — File checksum & version provenance**
> 2. **Epic B — Spec selection & per-spec auto-import**
> 3. **Epic C — Scanned Repository Report**
> 4. **Epic D — Repositories Needing Attention (dashboard)**
> 5. **Epic E — Auto-import pipeline & report artifacts**

---

## Completed (Repository Connector v1)

- REPO-10.2 (#2946): Per-repository **Scanned repository report** drill-in at `/ade/dashboard/repositories/{id}/reports/{scan_report_id}` (and `…/latest` → stable redirect) with server materialized `totalsJson` / `payloadJson` / `errorsJson`, REST list/detail/diff, and “compare with previous” totals roll-up.
- REPO-7.4 (#2802): Added linked-account token health monitoring by introducing per-credential probe persistence, classifying daily probe outcomes (`healthy` / `scope_missing` / `revoked` / `network_error`), auto-pausing repositories bound to revoked credentials, and surfacing usage + verification + reconnect states in Linked Accounts UI.
- REPO-7.1 (#2799): Added repository workflow-audit coverage in the shared `workflow_audit` ledger, documenting and emitting repository action codes (`registered/scanned/sync/pause/poll/token/archive/remove`) with structured per-event detail payloads and actor identities.
- REPO-6.3 (#2796): Added scan timeline upgrades in the repository detail view with trigger/status/branch filter chips, per-row trigger/SHA/duration/file-count summaries, and expandable failed-scan error consoles that render `repository_scan.event_log` plus `error_detail`.
- REPO-6.2 (#2795): Added the repository detail experience at `/ade/dashboard/repositories/{id}` with deep-link tabs (`branches/files/scans/sync/manifest/settings`), virtualized file rendering + drawer details, scan timeline links for REPO-6.3 and `repository_scan` drill-in, and Monaco-based manifest editing with REPO-2.4 schema validation.
- REPO-6.1 (#2794): Added an ADE repositories index experience with provider/status/search filters, sortable repository health and last-scan columns, skeleton-loading rows, and quick row actions for scan-now, pause/resume, and detail navigation from Account -> Repositories.
- REPO-5.6 (#2791): Added manifest-driven promotion gates by defaulting repository sync promotions to `manual`, preserving `repository.sync_committed` audit + change-report persistence for `promote: auto`, and forcing manual review whenever `onBreakingChange: block` is configured.
- REPO-5.5 (#2790): Added repository-sync conflict detection against the current draft by reusing import-pipeline conflict taxonomy, exposing conflict + resolution event history through sync-history endpoints for REPO-6.2 UI consumption, and persisting resolution choices on each `import_job.event_log`.
- REPO-5.4 (#2789): Added repository-sync dry-run change report previews by generating a persisted `ChangeReportModel` per dispatched import job (`source_kind='repository_sync'`), keeping manual promotions in review while auto promotions proceed, and preventing dry-run scans from mutating resolved version-head state.
- REPO-5.3 (#2788): Added commit-SHA draft version auto-binding for repository import jobs by creating `<datestamp>-<short-sha>` versions per resolved project with `(project, sha)` idempotency, recording `metadata.repositorySource` on created versions, and feature-gating manifest-driven project auto-creation to tenant administrators.
- REPO-5.2 (#2787): Added manifest-first project/version mapping resolution (`specs[].project`, `specs[].versionStrategy`) with persisted `repository_file.project_slug` / `repository_file.version_strategy` decisions, documented auto fallback rules (`project` derived from path segment, `version_strategy='commit-sha'`), and unmapped-file UI affordance metadata via `tracked=false` + `settings_json.mappingRequired=true`.
- REPO-5.1 (#2786): Added discovered-file to import-job binding in the repository scan completion path so `new`/`modified` files dispatch dry-run git import jobs, `removed` files dispatch manual-approval removal jobs, `unchanged` files skip job creation, parse failures write back `repository_file.status='parse_error'`, and each job records `repository.sync_committed` or `repository.sync_pending_review` audit events.
- REPO-4.5 (#2783): Added scheduler failure backoff and auto-pause behavior by persisting per-branch consecutive failure/error metadata, exponentially backing off poll cadence without mutating configured poll intervals, resetting failure state on successful checks, and auto-pausing repositories with `repository.auto_paused` workflow audits after eight consecutive failures.
- REPO-4.4 (#2782): Added multi-branch scheduler tracking for wildcard patterns by treating branch globs as discovery templates, expanding provider-matched concrete branches at poll time into `repository_branch` rows, and preserving branch scan history by re-tracking existing rows instead of deleting history.
- REPO-4.2 (#2780): Added commit-SHA change detection in scheduled polling by resolving provider branch HEADs, using conditional `If-None-Match` requests for GitHub checks, recording `skipped_unchanged` scans when HEAD is unchanged, and only dispatching downstream scan jobs when SHA changes.
- REPO-4.1 (#2779): Added a scheduler tick dispatcher that atomically reserves due tracked branches, skips paused repositories, clamps poll cadence to enterprise/non-enterprise minimums, dispatches poll jobs to `repo.poll.<priority>`, and records `repository.polled` workflow audit rows per dispatch.
- REPO-3.8 (#2777): Added an in-scan virtual filesystem `$ref` resolver for repository imports that resolves relative file-path and JSON-pointer chains in dependency order, memoizes repeated nodes per scan, and emits deterministic cycle errors for cross-file loops.
- REPO-3.5 (#2774): Added a standalone repository JSON Schema importer for Draft 7, 2019-09, and 2020-12 documents, preserving source `$id`/draft metadata on class schemas, keeping composition keywords intact, and delegating sibling `$ref` resolution through the REPO-3.8 resolver contract.
- REPO-3.2 (#2771): Added `swagger_2_0` support to the repository OpenAPI importer pipeline so Swagger 2.0 repository specs run through the same conversion/parser path as OpenAPI 3.x, with semantic parity tests covering definitions, paths, parameters, and security scheme mapping.
- REPO-3.1 (#2770): Added a repository OpenAPI importer hook that reuses the existing one-shot `parseOpenAPISpec` conversion pipeline, accepts normalized `{source, format, content, refs}` input for repository ingestion, and delegates cross-file `$ref` handling to the REPO-3.8 resolver contract with fixture-set parity coverage.
- REPO-2.7 (#2768): Added scan diff classification against the previous completed scan keyed by `(repository_id, path)`, including persisted `new/unchanged/modified/removed` per-file statuses with carried-forward `removed` rows and `{added, modified, removed, unchanged}` diff summary counts.
- REPO-2.6 (#2767): Added `repository_scan` and `repository_file` history support with cursor-paginated scan/file REST endpoints, `force` rescan behavior, and `skipped_unchanged` audit/event tracking.
- REPO-2.4 (#2765): Added `.objectified/repo.yaml` manifest support with published JSON Schema validation, non-fatal `manifest_error` repository file recording, per-spec format/polling overrides, and untracked discovery output for files not explicitly listed.
- REPO-2.3 (#2764): Added provider-agnostic spec format detection with filename heuristics plus 64 KB content sniffing, confidence/discriminator output, and stream-mode sniffing for files larger than 5 MB.
- REPO-2.2 (#2763): Added scanner include/exclude rule support with published default ignore patterns, manifest-level ignore merge behavior, ignore skip telemetry (`files_skipped_by_ignore`), and explicit `specs` precedence over ignores.
- REPO-2.1 (#2762): Added a streaming repository tree walker that iterates files at a commit SHA, enforces typed scan limits (`SCAN_LIMIT_EXCEEDED`), applies subpath glob filtering at the walker boundary, and emits `repository.scan.walked` workflow audit events.
- REPO-1.8 (#2760): Implemented a Bitbucket Cloud repository provider adapter for REST API 2.0 with shared contract coverage, UUID-based webhook verification, and linked-account availability for Bitbucket linking.
- REPO-1.7 (#2759): Implemented the GitLab repository provider adapter with full contract coverage, keyset pagination for repository listing, and GitLab webhook registration/signature verification.
- REPO-1.4 (#2756): Added repository registration UI flow and REST registration endpoint for GitHub repositories.
- REPO-1.5 (#2757): Added per-repository branch management with per-branch subpath and polling settings, including default branch preselection and wildcard branch patterns.
- REPO-1.6 (#2758): Added repository settings edit/archive/unarchive/delete flows with typed delete confirmation, archival audit events, and deletion cascades for repository relations.

---

## How to read this document

- Each epic has a **summary table** (columns: roadmap ID, title,
  description, labels, MVP, Parallel, Issue) followed by **detailed
  issue descriptions** for the highest-leverage tickets. Every detailed
  issue follows the same shape: **Problem statement → Solution / Scope
  → Acceptance criteria → Parallelism / Dependencies → Epic membership**.
  Most tickets also carry an **ASCII diagram** of the data flow or UI.
- Tickets are listed **in implementation order** within each epic, and
  the **single-page ordered checklist** at the bottom orders them across
  all epics for execution sequencing.
- The **Issue** column points to the live GitHub issue on
  `KenSuenobu/objectified-commercial`. Each child issue is also linked
  as a native sub-issue under its epic umbrella issue.
- **MVP = Yes** items are required for the first release of this
  extension ("Repo-Scan v1"). **MVP = No, V2 = Yes** items are explicit
  enterprise / follow-on tickets; they ship after v1.
- **Parallel = Yes** tickets can be implemented concurrently with other
  tickets in the same epic without merge conflicts on the schema, REST
  surface, or UI tree. **Parallel = No** tickets are dependency anchors
  and must be completed before later tickets in the epic begin.

---

## MVP Definition (Repo-Scan v1)

The first release of this extension must:

- Compute and persist a content checksum (`SHA-256`) on every discovered
  spec file, in addition to the existing git `blob_sha` — REPO-8.1
- Bind every auto-created draft version to its **(repository, branch,
  path, content_checksum, commit_sha)** provenance tuple — REPO-8.2
- Skip re-import when the content checksum matches the most recent
  imported version for `(project, source_path)` — REPO-8.3
- Default every newly discovered spec file to **import disabled** and
  **auto-import disabled**, requiring explicit opt-in — REPO-9.1, REPO-9.2
- Surface a per-repository spec list in ADE with **Import** and
  **Auto-Import** switches plus a one-shot **Import Now** action and a
  spec detail drawer — REPO-9.3, REPO-9.4, REPO-9.5, REPO-9.6
- Publish a tenant-wide **Scanned Repository Report** page listing every
  scanned repository, its discovered specs, and per-spec status, with
  per-repository report drill-in (REPO-10.1, REPO-10.2 — **done**)
- Publish two ADE dashboard widgets — **Repositories Needing Attention**
  and **Recent Imports Needing Attention** — backed by a unified
  attention rollup — REPO-11.1, REPO-11.2, REPO-11.3
- Run an auto-import worker that dispatches dry-run import jobs only
  when `auto_import = true` AND the content checksum changed since the
  last imported version — REPO-12.1, REPO-12.3
- Persist a **scanned repository report artifact** per scheduler tick
  for audit and reproducibility — REPO-12.4

Everything else in this document is **post-MVP** or **Enterprise V2**.

---

## Labels

**Reuse existing labels wherever possible**:

| Label              | Source                                  | Use here                                                       |
|--------------------|-----------------------------------------|----------------------------------------------------------------|
| `enhancement`      | repo-wide                               | All feature tickets                                            |
| `mvp`              | git-like / paths / repo / mcp roadmaps  | Tickets in the MVP slice                                       |
| `rest`             | repo-wide                               | Adds REST endpoints in `objectified-rest`                      |
| `database`         | repo-wide                               | Adds migrations under `objectified-db/scripts/`                |
| `ui`               | repo-wide                               | Adds UI in `objectified-ui`                                    |
| `security`         | repo-wide                               | Token / scope / RBAC handling                                  |
| `repository`       | repository roadmap (existing)           | Anything in the Repository Connector                           |
| `import`           | `FUTURE_FEATURE_ROADMAP_IMPORT`         | Anything that interacts with the import-job pipeline           |
| `dashboard`        | `FUTURE_FEATURE_ROADMAP_DASHBOARD`      | ADE dashboard widgets / panels                                 |
| `governance`       | governance roadmap                      | Audit / policy hooks                                           |
| `v2-enterprise`    | repo-wide                               | Gated to V2 Enterprise tier                                    |

**Already exists, reuse**:

| Label                | Description                                                                |
|----------------------|----------------------------------------------------------------------------|
| `roadmap-repository` | `PLANNED_FEATURE_ROADMAP_REPOSITORY.md` ticket pack — filter for this doc  |
| `scan`               | Scanner / tree walker / file discovery                                     |
| `repo-sync`          | Repository sync pipeline (discovered file → import job)                    |
| `epic`               | Umbrella issue grouping related sub-issues                                 |

**New labels created for this roadmap** (already added on `KenSuenobu/objectified-commercial`):

| Label                   | Description                                                                |
|-------------------------|----------------------------------------------------------------------------|
| `repository-report`     | Scanned-repository-report pages, exports, saved filters                    |
| `repository-selection`  | Per-spec import / auto-import toggles, bulk select, spec detail drawer     |
| `repository-provenance` | Content checksum, project↔version source tuple, idempotency keys           |
| `attention`             | "Needs attention" rollups, dashboard widgets, badges, banners              |

Apply at minimum: `enhancement`, `repository`, `roadmap-repository`,
plus the topic label (`scan`, `repository-report`,
`repository-selection`, `repository-provenance`, `attention`) and the
surface label (`database`, `rest`, `ui`, `security`, `dashboard`,
`import`, `governance`). Add `mvp` if it is in the MVP slice. Add
`v2-enterprise` if it is gated. Epic umbrella issues additionally
carry the `epic` label.

---

## Architecture at a glance

```
                           SCHEDULED POLL TICK (existing REPO-4.x)
                                           │
                                           ▼
                       ┌──────────────────────────────────────┐
                       │  Tree walker (REPO-2.1)              │
                       │  + manifest (REPO-2.4)               │
                       │  + format sniffer (REPO-2.3)         │
                       └─────────────────┬────────────────────┘
                                         │ for each discovered file
                                         ▼
                       ┌──────────────────────────────────────┐
                       │  NEW: SHA-256 content checksum       │      ── Epic A
                       │  → repository_file.content_checksum  │
                       │  → repository_scan_report row        │
                       └─────────────────┬────────────────────┘
                                         │
                                         ▼
                       ┌──────────────────────────────────────┐
                       │  Selection gate                      │      ── Epic B
                       │   import_enabled?  auto_import?      │
                       │   (default: both false)              │
                       └─────────┬─────────────────┬──────────┘
                                 │ no              │ yes
                                 ▼                 ▼
                  ┌──────────────────────┐   ┌──────────────────────┐
                  │ Discovered, not      │   │ Idempotency check    │  ── Epic A
                  │ imported (visible    │   │ (project,            │
                  │ in scan report)      │   │  source_path,        │
                  └──────────────────────┘   │  content_checksum)   │
                                             └──────────┬───────────┘
                                                        │ checksum changed
                                                        ▼
                                             ┌──────────────────────┐
                                             │ Auto-import worker   │  ── Epic E
                                             │ → dry-run import_job │
                                             │ → version creation   │
                                             │   with provenance    │
                                             └──────────┬───────────┘
                                                        │
                          ┌─────────────────────────────┴─────────────────────┐
                          ▼                                                   ▼
                ┌───────────────────────┐                       ┌──────────────────────┐
                │ Scanned Repository    │                       │ Repositories Needing │
                │ Report (tenant-wide,  │  ──── Epic C ────►    │ Attention dashboard  │  ── Epic D
                │ + per-repo drill-in)  │                       │ + Recent Imports     │
                └───────────────────────┘                       │   Needing Attention  │
                                                                └──────────────────────┘
```

**Key insight: checksum vs. commit-SHA**

```
  commit-SHA changes        │ checksum changes        │ what we do today (REPO-5.3) │ what we do after Epic A
  ──────────────────────────┼─────────────────────────┼────────────────────────────┼──────────────────────────
  yes (any file)            │ no (this spec untouched) │ dispatch import job        │ skip — no spec change
  yes                       │ yes                     │ dispatch import job        │ dispatch import job
  no                        │ —                       │ skipped_unchanged          │ skipped_unchanged
```

Today, _every_ commit on a tracked branch causes _every_ tracked spec
in that branch to round-trip through the importer, even when 99 % of
the time only one spec actually changed. After Epic A this becomes a
content-keyed pipeline; after Epic E it becomes user-controlled.

---

## Data model deltas (cross-epic reference)

```
  odb.repository_file
  ───────────────────
  + content_checksum           CHAR(64)         -- SHA-256 hex, populated by walker
  + content_algo               VARCHAR(16)      -- 'sha256' (forward-compat)
  + import_enabled             BOOLEAN NOT NULL DEFAULT FALSE   -- Epic B
  + auto_import_enabled        BOOLEAN NOT NULL DEFAULT FALSE   -- Epic B
  + selection_actor_id         UUID                           -- who toggled last
  + selection_changed_at       TIMESTAMPTZ
  + last_imported_checksum     CHAR(64)         -- for idempotency
  + last_imported_version_id   UUID REFERENCES odb.version(id)

  odb.version                                                   -- existing
  ──────────────
  + repository_source JSONB    -- Epic A (canonical provenance tuple)
                               -- { repositoryId, branch, path,
                               --   commitSha, contentChecksum,
                               --   contentAlgo, importedAt }

  odb.repository_scan_report   -- new, Epic E
  ──────────────────────────
  id                  UUID PK
  scan_id             UUID FK → odb.repository_scan(id)
  repository_id       UUID FK → odb.repository(id)
  generated_at        TIMESTAMPTZ
  totals_json         JSONB    -- { discovered, importable, parse_error,
                               --   manifest_error, ignored, unchanged,
                               --   imported, skipped_unchecksummed }
  attention_score     SMALLINT -- 0–100, used by Epic D
  payload_json        JSONB    -- per-file rows (path, format, status,
                               -- importable, content_checksum, …)

  odb.repository_attention      -- new, Epic D (denormalized rollup)
  ────────────────────────
  repository_id       UUID PK FK → odb.repository(id)
  computed_at         TIMESTAMPTZ
  reasons             TEXT[]   -- {parse_error, manifest_error,
                               --   token_revoked, scheduler_paused,
                               --   stale_checksum, repeated_failures,
                               --   import_failed}
  open_count          INTEGER  -- distinct files contributing
  last_change_at      TIMESTAMPTZ
```

---

## Epic A: File checksum & version provenance — REPO-EPIC-A (#2924)

### Summary

| Roadmap ID | Title                                                  | Description                                                                                                  | Labels                                                                                       | MVP | Parallel | Issue |
|------------|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|-----|----------|-------|
| REPO-8.1   | `repository_file.content_checksum` column + walker hash ✅ | Add `content_checksum` (SHA-256) + `content_algo` columns; populate in tree walker; index for lookups       | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-provenance`, `database` | Yes | No       | Done |
| REPO-8.2   | Version provenance tuple (`repository_source`) ✅       | Persist `(repositoryId, branch, path, commitSha, contentChecksum, contentAlgo, importedAt)` on every version created from a repo import | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-provenance`, `database`, `import` | Yes | Yes      | Done |
| REPO-8.3   | Checksum-keyed idempotent re-import ✅                  | Skip dispatch when `(project, source_path, content_checksum)` already mapped to a non-deleted version       | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-provenance`, `import`   | Yes | No       | Done |
| REPO-8.4   | Backfill checksum + provenance for historical scans ✅   | One-shot job to compute checksums for current `tracked` files and stamp `repository_source` on existing versions | `enhancement`, `repository`, `roadmap-repository`, `repository-provenance`, `database`        | No  | Yes      | Done |

### Detailed issues

#### REPO-8.1 — `repository_file.content_checksum` column + walker hash

**Problem statement**: Today `repository_file.blob_sha` stores the git
blob OID, which is content-addressable _per provider_ (GitHub blob
SHAs, GitLab blob SHAs, Bitbucket blob hashes are different
representations). When we promote a discovered file to a version we
have no provider-agnostic content fingerprint to pin the version to;
this in turn prevents us from short-circuiting re-imports when only
the commit SHA changed (a README edit on the same branch will
re-import every tracked spec). It also blocks any future cross-repo
deduplication (e.g. the same vendored OpenAPI spec mirrored into two
repos).

**Solution / Scope**:

- Add to `odb.repository_file`:
  - `content_checksum CHAR(64)` — SHA-256 hex, lower-case, no prefix.
  - `content_algo VARCHAR(16) NOT NULL DEFAULT 'sha256'` — forward-
    compat for stronger algorithms.
- Compute the hash inside the existing tree walker (REPO-2.1) on the
  same byte stream we already read for format sniffing (REPO-2.3) — no
  extra provider round-trips. Stream the hash so we never materialize
  files larger than `SCAN_LIMIT_BYTES_PER_FILE` in memory.
- Add a partial index for the idempotency lookup in REPO-8.3:
  ```sql
  CREATE INDEX idx_repository_file_content_checksum
    ON odb.repository_file (content_checksum)
    WHERE content_checksum IS NOT NULL;
  ```
- Audit: every walker pass writes `repository.scan.hashed` with
  `{path, content_algo, content_checksum_short}` (first 12 chars) into
  `repository_scan.event_log`. Never log the full hash to user-visible
  output (PII-equivalent for proprietary specs).

**ASCII flow**:

```
   walker        ┌────────────────────────────────────────┐
   reads file →  │ TeeReader                              │
                 │   ├── format sniffer  (REPO-2.3, ≤64KB)│
                 │   └── Sha256 streaming hasher          │
                 └────────────────────────────────────────┘
                                 │
                                 ▼
                 ┌────────────────────────────────────────┐
                 │ persist (path, blob_sha,               │
                 │          content_algo='sha256',        │
                 │          content_checksum=<hex>)       │
                 └────────────────────────────────────────┘
```

**Acceptance criteria**:

- A migration under `objectified-db/scripts/<YYYYMMDD-HHMMSS>-` adds
  the two columns and the partial index; the migration is idempotent.
- Walker tests in `objectified-rest/tests/repository/test_walker.py`
  assert deterministic SHA-256 for a fixture corpus, identical
  byte-for-byte across providers.
- A 25 MB fixture spec hashes without exceeding the existing walker
  RSS budget (peak heap delta ≤ 4 MB; verified via `tracemalloc`).
- A second scan over an unchanged file produces the same checksum and
  is recorded as `unchanged` in the diff (REPO-2.7) — no duplicate
  hash work is performed (we read `blob_sha` first; if it matches the
  prior scan we copy the prior `content_checksum`).
- `repository.scan.hashed` audit rows appear in
  `repository_scan.event_log`.

**Parallelism / Dependencies**:

- **Blocks**: REPO-8.2, REPO-8.3, REPO-9.x, REPO-10.x, REPO-12.x.
- **Depends on**: REPO-2.1 (tree walker) — already shipped.
- **Parallel = No**.

**Epic membership**: REPO-EPIC-A (#2924).

---

#### REPO-8.2 — Version provenance tuple (`repository_source`)

**Problem statement**: REPO-5.3 already stamps
`metadata.repositorySource` on commit-SHA-bound draft versions, but the
shape is loose JSON, not validated, and not indexed; we cannot answer
"which version did the spec at `<repo>@<branch>:<path>` map to last
time?" without a full table scan, and we cannot detect that a spec we
imported into project A is byte-identical to a spec in project B.

**Solution / Scope**:

- Promote `metadata.repositorySource` to a first-class
  `repository_source JSONB` column on `odb.version` with a CHECK that
  validates against a small JSON schema:
  ```json
  {
    "type": "object",
    "required": ["repositoryId", "branch", "path",
                 "commitSha", "contentChecksum", "contentAlgo",
                 "importedAt"],
    "properties": {
      "repositoryId":    { "type": "string", "format": "uuid" },
      "branch":          { "type": "string", "maxLength": 256 },
      "path":            { "type": "string", "maxLength": 1024 },
      "commitSha":       { "type": "string", "pattern": "^[0-9a-f]{40,64}$" },
      "contentChecksum": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
      "contentAlgo":     { "type": "string", "enum": ["sha256"] },
      "importedAt":      { "type": "string", "format": "date-time" }
    }
  }
  ```
- Add two indexes:
  ```sql
  CREATE INDEX idx_version_repo_source_lookup
    ON odb.version ((repository_source->>'repositoryId'),
                    (repository_source->>'path'));
  CREATE INDEX idx_version_content_checksum
    ON odb.version ((repository_source->>'contentChecksum'));
  ```
- Update the importer's draft-version creator to populate the column
  on every new version sourced from a repository, alongside the
  existing `metadata.repositorySource` payload (kept for one release
  for back-compat, then removed in REPO-8.4 cleanup).
- Add a REST helper `GET /v1/versions/by-repo-source?repository_id&path`
  used by Epic E to make the idempotency check fast.

**Acceptance criteria**:

- New repo-sourced versions populate `repository_source` and the
  CHECK constraint rejects malformed payloads in tests.
- The new indexes are confirmed via `EXPLAIN` to be used by the
  Epic A / Epic E lookups (no sequential scan).
- Existing versions whose `metadata.repositorySource` is well-formed
  get migrated by REPO-8.4 (separate ticket).

**Parallelism / Dependencies**: parallel with REPO-8.3 once REPO-8.1
ships. **Parallel = Yes**.

**Epic membership**: REPO-EPIC-A (#2924).

---

#### REPO-8.3 — Checksum-keyed idempotent re-import

**Problem statement**: Even with REPO-5.3, a commit that touches
`README.md` on a watched branch dispatches dry-run import jobs for
every tracked spec on that branch. Over time this is the dominant
source of duplicate `import_job` rows and noisy `change_report`
entries.

**Solution / Scope**:

- In the scan-completion dispatcher (REPO-5.1), before enqueuing an
  import job for a `modified` file, look up the most recent
  non-deleted version for `(project_id, repository_source.path,
  repository_source.repositoryId)` and compare its
  `repository_source.contentChecksum` to the freshly walked
  `repository_file.content_checksum`. If they match, **skip
  dispatch** and write a `repository_file.status='unchanged_checksum'`
  + `repository.scan.skipped_checksum` audit event.
- Honor a `--force` override (already plumbed through REPO-2.6) to
  always dispatch.
- Counter `repository_scan.skipped_unchanged_by_checksum` is added to
  the diff summary for visibility in the scan report.

**Acceptance criteria**:

- Modify `README.md` on a tracked branch in a fixture; the next scan
  reports `0` import jobs dispatched and `N` files marked
  `unchanged_checksum`.
- Modify a tracked spec; that one file dispatches, others do not.
- `--force` rescan ignores checksum match and dispatches regardless.
- Audit and counter assertions pass.

**Parallelism / Dependencies**:

- **Depends on**: REPO-8.1, REPO-8.2.
- **Blocks**: REPO-12.1.
- **Parallel = No**.

**Epic membership**: REPO-EPIC-A (#2924).

---

## Epic B: Spec selection & per-spec auto-import — REPO-EPIC-B (#2925)

### Summary

| Roadmap ID | Title                                            | Description                                                                                                  | Labels                                                                                  | MVP | Parallel | Issue |
|------------|--------------------------------------------------|--------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|-----|----------|-------|
| REPO-9.1   | `import_enabled` flag on `repository_file`     | New boolean defaulting `false`; new audit code `repository.spec.selection_changed`                          | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-selection`, `database` | Yes | No  | Done (#2931) |
| REPO-9.2   | `auto_import_enabled` flag on `repository_file` | New boolean defaulting `false`; toggling triggers REPO-12.1 worker eligibility                              | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-selection`, `database` | Yes | Yes | Done (#2932) |
| REPO-9.3   | REST: list / toggle / bulk-update spec selection | `GET /v1/repositories/{id}/specs`, `PATCH /v1/repositories/{id}/specs/{file_id}`, bulk variant              | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-selection`, `rest` | Yes | No  | Done (#2934) |
| REPO-9.4   | ADE Repository Detail "Specs" tab               | Replace existing Files tab spec list with switches (Import / Auto-Import) + status pill + last-imported-version link | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-selection`, `ui`   | Yes | Yes | Done (#2938) |
| REPO-9.5   | "Import Now" one-shot action                    | Trigger a manual import for any discovered spec regardless of `auto_import_enabled`                         | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-selection`, `import`, `ui` | Yes | Yes | Done (#2939) |
| REPO-9.6   | Spec detail drawer                              | Read-only Monaco preview, lint summary, last 5 import attempts, current selection state                     | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-selection`, `ui`   | Yes | Yes | Done (#2940) |
| REPO-9.7   | Bulk select + apply across discovered files     | Multi-select with sticky toolbar; "Enable import for selected", "Disable", "Set auto-import"                 | `enhancement`, `repository`, `roadmap-repository`, `repository-selection`, `ui`          | No  | Yes | Done (#2948) |

### Detailed issues

#### REPO-9.1 — `import_enabled` flag on `repository_file`

**Problem statement**: Today, the existence of a `specs[]` entry in
`.objectified/repo.yaml` (REPO-2.4) implies the file is tracked and
will be dispatched. There is no surface for the user to look at a
discovered spec and say "I see it, do not import it yet." Manifest-less
repositories have an even weaker contract: every file that the format
sniffer recognized at high confidence is dispatched.

**Solution / Scope**:

- Add `import_enabled BOOLEAN NOT NULL DEFAULT FALSE` to
  `odb.repository_file`.
- A spec listed in the manifest is recorded as discovered with
  `import_enabled = TRUE` **only when manifest opt-in is explicit**
  (`specs[].importEnabled: true`); otherwise `FALSE`. This is
  back-compat-safe: the manifest schema (REPO-2.4) defaults
  `importEnabled` to `true` for files **already** listed prior to
  this rollout, and to `false` for newly added files. We surface a
  one-time migration banner on the manifest editor.
- Repositories without a manifest get every discovered file at
  `import_enabled = FALSE`. The Specs tab (REPO-9.4) is then the
  single source of truth.
- Add audit code `repository.spec.selection_changed` carrying
  `{path, before, after, actor_id, source: 'ui'|'manifest'|'api'}`.
- Update REPO-5.1 dispatcher: import jobs are only dispatched when
  `import_enabled = TRUE`.

**ASCII state diagram**:

```
                ┌─────────────┐    user opts in (UI / API / manifest)
                │ DISCOVERED  │ ─────────────────────────────► ENABLED
                │ (default)   │ ◄─────────────────────────── DISABLED
                └──────┬──────┘   user opts out
                       │
            scanner re-runs;  same path, new content_checksum
                       │
                       ▼
                  selection state is preserved across scans
                  (we only delete the row when the file is
                   removed from the repo for ≥ 14 days)
```

**Acceptance criteria**:

- New spec rows default to `import_enabled = FALSE`.
- Toggling via REST writes audit row and updates the column.
- Dispatcher tests confirm no import job is created for
  `import_enabled = FALSE` rows.
- Migration is idempotent and safe to re-run.

**Parallelism / Dependencies**: blocks REPO-9.3 / REPO-9.4 / REPO-12.1.
**Parallel = No**.

**Epic membership**: REPO-EPIC-B (#2925).

---

#### REPO-9.2 — `auto_import_enabled` flag on `repository_file`

**Problem statement**: Even when a user opts a spec _in_, they may
want to review every change manually rather than letting the platform
create draft versions on every checksum change. Conversely, "trusted"
specs (well-managed, change-controlled upstream) deserve a one-click
"keep this in sync forever" toggle.

**Solution / Scope**:

- Add `auto_import_enabled BOOLEAN NOT NULL DEFAULT FALSE`.
- Worker logic (REPO-12.1) requires **both**
  `import_enabled = TRUE` and `auto_import_enabled = TRUE` to
  auto-dispatch on checksum change. If only `import_enabled` is true,
  the user must trigger REPO-9.5 manually.
- Toggling auto-import emits the same `repository.spec.selection_changed`
  audit event with a `field: 'auto_import_enabled'` discriminator.

**Truth table**:

```
  import_enabled   auto_import_enabled    behaviour on checksum change
  ────────────────────────────────────────────────────────────────────
  FALSE            (any)                  do nothing
  TRUE             FALSE                  surface in "Recent Imports
                                          Needing Attention" as a
                                          ready-to-promote candidate;
                                          no automatic import
  TRUE             TRUE                   auto-import worker dispatches
                                          dry-run import_job
```

**Acceptance criteria**:

- Default is `FALSE` for every new row.
- Worker eligibility query joins both flags.
- Toggling each flag is independently audited.

**Parallelism / Dependencies**: parallel with REPO-9.1 once schema lands.
**Parallel = Yes**.

**Epic membership**: REPO-EPIC-B (#2925).

---

#### REPO-9.4 — ADE Repository Detail "Specs" tab

**Problem statement**: The current Files tab (REPO-6.2) is a flat
virtualized listing optimized for browsing every file the walker
saw, including ignored ones. There is no affordance for opt-in /
opt-out per spec, no last-imported-version link, no per-spec status
pill, and the import / auto-import switches do not exist.

**Solution / Scope**:

- Add a new tab between Files and Scans called **Specs**. It lists
  only rows where the format sniffer's `confidence ≥ 0.5` (i.e. the
  walker thinks this file is _potentially_ importable). Files
  recognized but ignored are still visible under the Files tab.
- Each row renders:
  - Path (truncated, click expands the spec detail drawer — REPO-9.6).
  - Detected format chip (`openapi_3.1`, `swagger_2.0`,
    `json_schema_2020_12`, `asyncapi_2.6`, …).
  - Confidence + discriminator hover.
  - Last imported version link (if any) — links into version detail.
  - Last imported timestamp.
  - Last status pill — `imported`, `parse_error`, `manifest_error`,
    `not_imported`, `unchanged_checksum`.
  - Two switches: **Import** (binds REPO-9.1) and **Auto-Import**
    (binds REPO-9.2; disabled when **Import** is off).
  - Overflow menu: **Import Now** (REPO-9.5), **View change report**,
    **View raw file**, **Open spec detail**.

**ASCII wireframe**:

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ ADE › Repositories › orders-service › Specs                                        │
├────────────────────────────────────────────────────────────────────────────────────┤
│  Filter: ◯ All  ◯ Importable  ◯ Imported  ◯ Failing  ◯ Awaiting selection          │
│  Branch: [main ▾]   Search: [____________]            [Bulk-edit ▾]   ⟳ Rescan now │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Path                          Format        Status            Last version  Import │
│                                                                            Auto    │
│ ────────────────────────────  ───────────   ───────────────   ───────────  ─────── │
│ openapi/orders-v3.yaml        openapi 3.1   ● Imported        v3.4.0       [✓] [✓] │
│ openapi/orders-v2.yaml        openapi 3.1   ● Imported        v2.9.1       [✓] [ ] │
│ openapi/legacy.yaml           swagger 2.0   ◌ Not imported    —            [ ] [ ] │
│ asyncapi/orders.yaml          asyncapi 2.6  ⚠ Parse error      —            [ ] [ ] │
│ schemas/order.json            json-schema   ● Imported        sub-of v3.4  [✓] [✓] │
│ schemas/_partials/headers.yml json-schema   ◌ Not imported    —            [ ] [ ] │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**:

- Switches are optimistic with rollback on REST 4xx.
- Disabling **Import** disables and clears **Auto-Import** in the
  same PATCH (atomic).
- Filter chips deep-link via query string (`?status=parse_error`).
- Playwright spec covers: toggle on, toggle off, bulk edit, "Import
  Now", filter chip change, drawer open.

**Parallelism / Dependencies**: depends on REPO-9.3 (REST). Parallel
with REPO-9.5 / REPO-9.6 / REPO-9.7. **Parallel = Yes**.

**Epic membership**: REPO-EPIC-B (#2925).

---

#### REPO-9.6 — Spec detail drawer

**Problem statement**: Before opting a spec in, the user has no
in-product way to look at it: the only way to read the file today is
to leave the platform, open the repository in the provider UI, find
the file, and read it there. This breaks the selection flow's
decision loop.

**Solution / Scope**:

- Drawer opens from the Specs tab row click and from the dashboard
  attention widgets (Epic D).
- Sections (top-down):
  - **Header**: path, branch, format chip, last status pill, copy-link
    button, "Open in provider" external link.
  - **Preview**: read-only Monaco editor showing the latest scanned
    content, syntax-highlighted by detected format, with a
    "Show raw" toggle. Content is fetched lazily through
    `GET /v1/repositories/{id}/specs/{file_id}/content` capped at
    2 MB; larger files prompt the user to download.
  - **Lint summary**: counts by severity (error, warning, info) using
    the existing import-job lint output if any.
  - **Recent imports**: last five `import_job` rows for this file —
    status, started/finished, conflict count, link to change report.
  - **Selection state**: switches mirroring the row, disabled state
    showing the actor + timestamp of the last toggle.

**ASCII wireframe**:

```
┌─────────────────────────────  Spec › openapi/orders-v3.yaml  ──────────────────────┐
│  branch: main · format: openapi 3.1 · status: ● Imported    [Open in GitHub ↗]    │
├────────────────────────────────────────────────────────────────────────────────────┤
│  Preview                                                          [⤓ Download]    │
│  ┌────────────────────────────────────────────────────────────────────────────┐    │
│  │ openapi: 3.1.0                                                             │    │
│  │ info:                                                                      │    │
│  │   title: Orders                                                            │    │
│  │   version: 3.4.0                                                           │    │
│  │ ...                                                                        │    │
│  └────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                    │
│  Lint summary                                                                      │
│   ✖ 0 errors    ⚠ 3 warnings    ℹ 12 info        (from last successful import)     │
│                                                                                    │
│  Recent imports                                                                    │
│   #4321  2026-04-25 09:12  ● succeeded   v3.4.0  [Change report ↗]                 │
│   #4180  2026-04-22 18:47  ⚠ warnings    v3.3.0  [Change report ↗]                 │
│   #4099  2026-04-21 09:10  ✖ failed       —      [Error console ↗]                  │
│                                                                                    │
│  Selection state                                                                   │
│    Import:        [✓]   last toggled 2026-04-22 by alice@…                         │
│    Auto-import:   [✓]   last toggled 2026-04-22 by alice@…                         │
│                                                                                    │
│                                                  [ Import now ]   [ Close ]       │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**:

- Lazy-loaded content; no payload fetched if drawer is closed.
- Files > 2 MB show a download prompt instead of inline preview.
- Drawer is keyboard-navigable; Esc closes; deep-link survives reload.

**Parallelism / Dependencies**: depends on REPO-9.3. **Parallel = Yes**.

**Epic membership**: REPO-EPIC-B (#2925).

---

## Epic C: Scanned Repository Report — REPO-EPIC-C (#2926)

### Summary

| Roadmap ID | Title                                            | Description                                                                                                  | Labels                                                                              | MVP | Parallel | Issue |
|------------|--------------------------------------------------|--------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|-----|----------|-------|
| REPO-10.1  | "Scanned Repository Report" page (tenant-wide)  | New page at `/ade/dashboard/repositories/reports` listing every repository, last scan, importable counts    | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-report`, `ui`  | Yes | No       | #2945 |
| REPO-10.3  | Cross-repo aggregate stats card (shipped)        | Top-of-page stat cards: total repos, importable specs, parse errors, manifest errors, awaiting-selection; `GET /v1/dashboard/{tenant}/repository_corpus_stats` + `odb.repository_corpus_stats_rollup`    | `enhancement`, `repository`, `roadmap-repository`, `repository-report`, `ui`         | No  | Yes      | #2949 |
| REPO-10.4  | Report export (CSV + JSON)                      | Stream-export the current filtered report; capped at 100k rows; reuses the existing audit-export pipeline   | `enhancement`, `repository`, `roadmap-repository`, `repository-report`, `rest`       | No  | Yes      | #2950 |
| REPO-10.5  | Saved filters per user                          | Persist named filters ("All failing on prod", "Awaiting selection in core repos") in `user_settings`        | `enhancement`, `repository`, `roadmap-repository`, `repository-report`, `ui`         | No  | Yes      | #2951 |

### Detailed issues

#### REPO-10.1 — "Scanned Repository Report" page

**Problem statement**: The repositories index (REPO-6.1) shows
repositories at the row level — name, provider, status, last scan.
It does not aggregate _what was found_ across repos (importable
counts, error counts), so a user looking for "where do we have
specs awaiting selection" has to walk into every repo individually.

**Solution / Scope**:

- New tenant-scoped page at
  `/ade/dashboard/repositories/reports`. The route is gated by the
  existing `repository.read` scope (all org members get it).
- Top-of-page filter bar:
  - Provider chips (GitHub / GitLab / Bitbucket / All)
  - Status chips:
    - **Importable** — at least one spec with confidence ≥ 0.5
    - **Imported** — last scan produced ≥ 1 successful import
    - **Failing** — last scan has parse_error or manifest_error
    - **Awaiting selection** — ≥ 1 spec with `import_enabled = FALSE`
      and confidence ≥ 0.5
    - **Stale** — last scan > 7 days
  - Search by repo name / slug.
- Table columns: Repository, Provider, Branches tracked, Last scan,
  Specs (importable / imported / failing / awaiting), Attention,
  Actions.
- Default sort: Attention DESC, then last-scan DESC.

**ASCII wireframe**:

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│ ADE › Repositories › Scan Reports                                                  │
├────────────────────────────────────────────────────────────────────────────────────┤
│  [GitHub] [GitLab] [Bitbucket]   Status: ◯ All ◯ Importable ◯ Failing ◯ Awaiting   │
│  Search: [orders___________]                                  [⤓ Export ▾]         │
├────────────────────────────────────────────────────────────────────────────────────┤
│ Repository           Provider  Branches  Last scan      Specs (I / A / F / S)  ⚠   │
│ ──────────────────   ────────  ────────  ───────────    ────────────────────  ──── │
│ orders-service       GitHub    2         2m ago         12 / 10 / 0 / 2       —   │
│ payments-service     GitHub    1         5h ago         8 / 6 / 1 / 1       ⚠ 1 │
│ legacy-monolith      GitLab    3         3d ago         42 / 0 / 6 / 36      ⚠ 6 │
│ vendor/openapi-mirror Bitbucket 1        12d ago        3 / 3 / 0 / 0      ⏱ stale│
│                                                                                    │
│  Legend: I=Importable · A=Imported (last scan) · F=Failing · S=Awaiting selection  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**:

- Page loads in ≤ 800 ms p95 on a 200-repo tenant (server-side
  pagination, `repository_scan_report.totals_json` powers the row
  counts so we never aggregate per-file at request time).
- Filter chips persist in URL query string.
- Each row drills into REPO-10.2.
- A11y: filter bar focusable in tab order, table headers properly
  marked sortable, screen-reader announcements on filter change.

**Parallelism / Dependencies**: depends on REPO-12.4 (report
artifacts). **Parallel = No**.

**Epic membership**: REPO-EPIC-C (#2926).

---

#### REPO-10.2 — Per-repository report drill-in

**Problem statement**: The Specs tab (REPO-9.4) shows the _live_
state of a repository. The scanned-repository report needs a
historical, snapshot-level companion view that says "this is exactly
what scan #N saw, and exactly what we did with it" — useful for
audits, change reviews, and reproducing a previous decision.

**Solution / Scope**:

- Route: `/ade/dashboard/repositories/{id}/reports/{scan_id}` (with
  `scan_id` defaulting to "latest" → most recent
  `repository_scan_report` row).
- Three sections:
  - **Summary** — totals from `totals_json`, scan metadata
    (commit SHA, started/finished, trigger), attention score.
  - **Files table** — rendered from `payload_json[]` with read-only
    selection state (no switches; this is a snapshot view).
  - **Errors** — collapsible list of parse / manifest errors with
    full message and `error_detail` rendering, reusing the REPO-6.3
    error console component.

**Acceptance criteria**:

- Snapshots are fully reproducible without hitting any provider API
  (everything needed to render is in `repository_scan_report`).
- The "latest" deep-link redirects to the actual `scan_id` once
  loaded so refreshes are stable.
- A "Compare with previous scan" affordance shows a diff of totals
  between this report and the prior one (added/removed specs,
  status changes).

**Parallelism / Dependencies**: depends on REPO-12.4. **Parallel = Yes**
with REPO-10.3, REPO-10.4, REPO-10.5.

**Epic membership**: REPO-EPIC-C (#2926).

---

## Epic D: Repositories Needing Attention — REPO-EPIC-D (#2927)

### Summary

| Roadmap ID | Title                                            | Description                                                                                                  | Labels                                                                          | MVP | Parallel | Issue |
|------------|--------------------------------------------------|--------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|-----|----------|-------|
| REPO-11.1  | `repository_attention` rollup table + computer | Materialized rollup table; recomputed at scan completion and at scheduler tick                              | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `attention`, `database`, `rest` | Yes | No  | #2941 |
| REPO-11.2  | Dashboard widget: "Repositories Needing Attention" | Top-N panel on `/ade/dashboard` rendering `repository_attention` ordered by score                          | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `attention`, `dashboard`, `ui` | Yes | Yes | #2942 |
| REPO-11.3  | Dashboard widget: "Recent Imports Needing Attention" | Last N failed/warning import jobs sourced from repositories                                              | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `attention`, `dashboard`, `ui`, `import` | Yes | Yes | #2943 |
| REPO-11.4  | Per-repo "Issues" tab                           | Repository detail tab listing actionable problems with "Fix" links (reconnect, edit manifest, retry import) | `enhancement`, `repository`, `roadmap-repository`, `attention`, `ui`             | No  | Yes | #2952 |

### Detailed issues

#### REPO-11.1 — `repository_attention` rollup + computer

**Problem statement**: The signals that compose "this repository
needs attention" are scattered across `repository`, `repository_scan`,
`repository_branch`, `repository_file`, `import_job`, and the linked-
account credential store. Computing them at request time on the
dashboard hot path is too expensive, and dashboards must be
sub-second.

**Solution / Scope**:

- New table `odb.repository_attention` (one row per repository).
- Reasons enum (`TEXT[]`):
  - `parse_error` — at least one file in last scan with
    `status='parse_error'`
  - `manifest_error` — last scan recorded a manifest validation error
  - `token_revoked` — linked-account probe (REPO-7.4) reported
    `revoked` for the bound credential
  - `scheduler_paused` — `repository.status = 'paused'` and the pause
    is non-user-initiated (auto-pause from REPO-4.5)
  - `repeated_failures` — consecutive scheduler failure count ≥ 3
  - `stale_checksum` — `import_enabled = TRUE` AND
    `last_imported_checksum != content_checksum` for ≥ 24 h (the
    user opted in but we've not auto-imported because
    `auto_import_enabled = FALSE`; this is the "ready to promote"
    bucket)
  - `import_failed` — last `import_job` for any tracked file is in
    `failed` state
- Compute is **event-driven**: scan completion, scheduler-failure
  bump, token-probe outcome change, import-job terminal state, and
  selection toggles. A safety-net scheduled job runs hourly to
  reconcile drift.
- `attention_score = clamp(0, 100, sum(weight[reason]))` where
  weights live in a config map (e.g. `token_revoked = 40`,
  `manifest_error = 30`, `parse_error = 20`, `stale_checksum = 10`,
  `repeated_failures = 25`, `scheduler_paused = 25`,
  `import_failed = 30`, capped at 100).

**ASCII flow**:

```
   ┌───────────────────────┐    ┌────────────────────────┐
   │ scan complete         │    │ scheduler failure ++   │
   │ → recompute(repo)     │    │ → recompute(repo)      │
   └──────────┬────────────┘    └─────────┬──────────────┘
              │                            │
              ▼                            ▼
       ┌────────────────────────────────────────┐
       │ recompute(repo):                        │
       │   reasons = []                          │
       │   if last_scan.parse_error_count > 0:   │
       │     reasons += [parse_error]            │
       │   if linked_account.probe == revoked:   │
       │     reasons += [token_revoked]          │
       │   …                                     │
       │   UPSERT repository_attention(          │
       │     repo, reasons, score, computed_at)  │
       └─────────────────────┬───────────────────┘
                             │
                             ▼
       ┌────────────────────────────────────────┐
       │ pub/sub channel: dashboard.attention    │
       │   so widgets refresh w/o polling       │
       └────────────────────────────────────────┘
```

**Acceptance criteria**:

- Recompute runs in O(1) per repository (no full-tenant scans).
- Round-trip latency from event → updated row ≤ 2 s p95.
- Hourly reconciliation catches missed events without producing
  spurious changes (idempotent).

**Parallelism / Dependencies**: blocks REPO-11.2, REPO-11.3.
**Parallel = No**.

**Epic membership**: REPO-EPIC-D (#2927).

---

#### REPO-11.2 — Dashboard widget: "Repositories Needing Attention"

**Problem statement**: The ADE dashboard has no surface for repository
health; problems are only visible if a user opens the repositories
index and visually scans status pills.

**Solution / Scope**:

- New widget rendered on `/ade/dashboard` in the right column,
  positioned above "Recent Activity".
- Lists the top 5 repositories ordered by `attention_score DESC,
  last_change_at DESC`.
- Each row: repo name, top reason chip, count of contributing files,
  ago-timestamp, link to the per-repo Issues tab (REPO-11.4) or
  Specs tab (when reasons include `stale_checksum`).
- Empty state: "All scanned repositories are healthy."
- Header link: "View scan report" → `/ade/dashboard/repositories/reports`.

**ASCII wireframe**:

```
┌─────────────────  Repositories Needing Attention  ─────────────────┐
│                                            [View scan report ↗]    │
│  payments-service           ⚠ token_revoked    1 file   2m ago  ▸  │
│  legacy-monolith            ✖ parse_error      6 files  17m ago ▸  │
│  inventory-svc              ⚠ manifest_error   1 file   1h ago  ▸  │
│  vendor/openapi-mirror      ⏱ stale            3 files  3d ago  ▸  │
│  reporting-svc              ⏳ stale_checksum  4 files  4h ago  ▸  │
│                                                                    │
│  All other 47 repositories: healthy                                │
└────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**:

- Widget renders from a single `GET /v1/dashboard/repository_attention?limit=5`
  call backed by the rollup table — no fan-out queries.
- Updates within 5 s of a recompute event (server-sent events
  pub/sub already wired by REPO-7.4 reconnect channel).
- Widget honors RBAC: rows only include repositories the caller
  can `repository.read`.

**Parallelism / Dependencies**: depends on REPO-11.1. **Parallel = Yes**
with REPO-11.3, REPO-11.4.

**Epic membership**: REPO-EPIC-D (#2927).

---

#### REPO-11.3 — Dashboard widget: "Recent Imports Needing Attention"

**Problem statement**: A repository can be _healthy at the rollup
level_ (no parse errors, valid token, recently scanned) and still
have produced an import job that needs review (warnings, conflicts,
ready-to-promote drafts). The Imports module already lists every
job; the dashboard should surface only the high-leverage ones.

**Solution / Scope**:

- Widget on `/ade/dashboard` directly under REPO-11.2.
- Lists the most recent 5 `import_job` rows where:
  - `source_kind IN ('git', 'repository_sync', 'repository_auto_import')`
  - terminal state is `failed` OR final change report has
    breaking changes OR `lint.warnings_count > 0` OR job is in
    `awaiting_review` state
  - within the last 7 days
- Each row: project name, version label, status badge, key reason
  ("breaking changes", "1 conflict", "5 warnings"), timestamp, link
  to the change report.

**ASCII wireframe**:

```
┌─────────────────  Recent Imports Needing Attention  ───────────────┐
│                                                  [All imports ↗]   │
│  orders-service · v3.4.0      ⚠ 2 breaking      14m ago  ▸         │
│  payments-svc · v0.0.0-draft  ✖ failed          1h ago   ▸         │
│  inventory-svc · v2.7.0       ⚠ 5 warnings      3h ago   ▸         │
│  reporting-svc · v1.2-draft   ⏳ awaiting review 1d ago   ▸         │
│  legacy-svc · v0.0.0-draft    ⚠ 1 conflict       2d ago  ▸         │
└────────────────────────────────────────────────────────────────────┘
```

**Acceptance criteria**:

- Backed by a single REST call against the existing `import_job`
  table with the documented filter; no new persistence.
- "Mark as reviewed" affordance hides the row for the current user
  (per-user dismissal stored in `user_settings`).

**Parallelism / Dependencies**: depends on REPO-11.1 only for the
shared widget shell. **Parallel = Yes**.

**Epic membership**: REPO-EPIC-D (#2927).

---

## Epic E: Auto-import pipeline & report artifacts — REPO-EPIC-E (#2928)

### Summary

| Roadmap ID | Title                                            | Description                                                                                                  | Labels                                                                          | MVP | Parallel | Issue |
|------------|--------------------------------------------------|--------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|-----|----------|-------|
| REPO-12.1  | Auto-import worker + dispatch                    | Consume scan-completion events; for `(import_enabled, auto_import_enabled, checksum_changed)` triplets, dispatch dry-run import jobs | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `scan`, `import` | Yes | No  | #2935 |
| REPO-12.2  | Project auto-creation policy & conflict handling | Reuse REPO-5.3 policy; expose conflict resolution surface ("project slug taken", "version-strategy mismatch") | `enhancement`, `repository`, `roadmap-repository`, `scan`, `import`   | No  | Yes | #2953 |
| REPO-12.3  | Version creation with provenance                 | Bind `repository_source` (Epic A) on every auto-imported version; emit `repository.auto_imported` audit     | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `repository-provenance`, `import` | Yes | No  | #2936 |
| REPO-12.4  | `repository_scan_report` artifact persisted per tick | Per scheduler tick (or scan), emit a single report row with totals + per-file payload; retained 90 days   | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `scan`, `database` | Yes | Yes | #2937 |
| REPO-12.5  | Notifications on auto-import failure / warnings  | Re-use the existing notification system to ping the spec's selection actor on terminal-state changes        | `enhancement`, `repository`, `roadmap-repository`, `attention`, `import`         | No  | Yes | #2954 |
| REPO-12.6  | Audit + change-report linking for auto-imports   | Every auto-import emits a `repository.auto_imported` row pointing at the change report                      | `enhancement`, `mvp`, `repository`, `roadmap-repository`, `governance`, `import` | Yes | Yes | #2944 |

### Detailed issues

#### REPO-12.1 — Auto-import worker + dispatch

**Problem statement**: REPO-5.1 already dispatches import jobs based on
the file diff classifier (`new` / `modified` / `removed`). What's
missing is the **selection gate** (Epic B) and the **checksum gate**
(Epic A) on the same path: today, every modified file with a
manifest entry round-trips through the importer regardless of user
opt-in.

**Solution / Scope**:

- The dispatcher becomes a chain of three filters:
  1. **Selection filter** — `import_enabled = TRUE`. Files that fail
     this filter are recorded as `discovered` only.
  2. **Mode filter** — `auto_import_enabled = TRUE`. Files that pass
     selection but fail this filter become **ready-to-promote**
     candidates surfaced in REPO-11.3.
  3. **Checksum filter** (REPO-8.3) — `content_checksum !=
     last_imported_checksum`. Equal checksums are recorded as
     `unchanged_checksum`.
- Files passing all three filters dispatch a dry-run import job
  with `source_kind = 'repository_auto_import'` (new value), so
  Epic D widgets and existing import dashboards can filter
  cleanly.
- Worker concurrency: per-repository serialization (one in-flight
  auto-import per repo at a time) to keep change-report ordering
  deterministic.

**ASCII flow**:

```
  scan complete (REPO-2.x) ───► scan_files[]
                                    │
                                    ▼
                       ┌───────────────────────────┐
                       │ for each modified file:   │
                       │   if !import_enabled:     │  → status='discovered'
                       │     skip dispatch         │
                       │   elif !auto_import:      │  → mark 'ready_to_promote'
                       │     surface in widget     │
                       │   elif checksum_unchanged:│  → status='unchanged_checksum'
                       │     skip dispatch         │
                       │   else:                   │
                       │     dispatch import_job   │
                       │       source_kind=        │
                       │       'repository_auto_   │
                       │        import'            │
                       └───────────────────────────┘
```

**Acceptance criteria**:

- Dispatcher tests cover all four branches with deterministic
  fixtures.
- Per-repo serialization is enforced via a row-level advisory lock
  on `repository.id`.
- Audit row `repository.auto_imported` written on dispatch with
  `{file_id, content_checksum_short, project_slug, version_strategy}`.

**Parallelism / Dependencies**: depends on REPO-8.3, REPO-9.1,
REPO-9.2. **Parallel = No**.

**Epic membership**: REPO-EPIC-E (#2928).

---

#### REPO-12.4 — `repository_scan_report` artifact persisted per tick

**Problem statement**: Epics C and D both need a stable, indexable
read surface that does not require joining scan, file, and import
state per request. We also want a tamper-evident, point-in-time
record we can retain for audits and reproduce reports against
months later.

**Solution / Scope**:

- New table `odb.repository_scan_report` (already sketched in the
  cross-epic data-model section above). One row per
  `(repository_id, scan_id)`.
- Populated transactionally at the end of every scheduler tick —
  same DB transaction that flips `repository_scan.status` to its
  terminal state — so failures are atomic with the scan.
- Retention: rolling 90 days by default, configurable per tenant
  (Enterprise), enforced by a daily cleanup job that preserves the
  **most recent report per repository** even outside the window.
- `payload_json` is a **bounded** array (≤ 5 000 file rows). For
  larger repositories, the payload contains a summary plus a
  `payload_overflow_url` pointing at an object-store blob (signed
  URL); the export pipeline (REPO-10.4) follows the URL.

**Acceptance criteria**:

- Report write and scan-finalize are in the same transaction
  (verified in tests).
- A 200-file repo's report fits comfortably under 1 MB JSON.
- A 30 000-file repo writes the overflow blob and the table row
  references it.
- Cleanup job is idempotent and writes `repository.scan_report.purged`
  audit rows.

**Parallelism / Dependencies**: blocks REPO-10.1 / REPO-10.2.
**Parallel = Yes** with REPO-12.5 / REPO-12.6.

**Epic membership**: REPO-EPIC-E (#2928).

---

## Single-page ordered checklist (execution sequence)

This list is **the** burn-down for Repo-Scan v1, ordered to minimize
blocking.

| Order | ID         | Issue | Title                                               | MVP | Epic |
|-------|------------|-------|-----------------------------------------------------|-----|------|
| 3     | REPO-9.1   | #2931 | import_enabled flag                                 | Yes | B    |
| 7     | REPO-12.1  | #2935 | auto-import worker + dispatch                       | Yes | E    |
| 8     | REPO-12.3  | #2936 | version creation with provenance                    | Yes | E    |
| 9     | REPO-12.4  | #2937 | repository_scan_report artifact                     | Yes | E    |
| 13    | REPO-11.1  | #2941 | repository_attention rollup table + computer        | Yes | D    |
| 14    | REPO-11.2  | #2942 | dashboard widget: Repositories Needing Attention    | Yes | D    |
| 15    | REPO-11.3  | #2943 | dashboard widget: Recent Imports Needing Attention  | Yes | D    |
| 16    | REPO-12.6  | #2944 | audit + change-report linking for auto-imports      | Yes | E    |
| 17    | REPO-10.1  | #2945 | Scanned Repository Report page                      | Yes | C    |
| —     | _Repo-Scan v1 ships here. Items below are post-MVP._               |     |      |
| 20    | REPO-9.7   | #2948 | bulk select + apply across discovered files        | No  | B    |
| 21    | REPO-10.3  | #2949 | cross-repo aggregate stats card                    | Yes | C    |
| 22    | REPO-10.4  | #2950 | report export (CSV + JSON)                         | No  | C    |
| 23    | REPO-10.5  | #2951 | saved filters per user                             | No  | C    |
| 24    | REPO-11.4  | #2952 | per-repo "Issues" tab                              | No  | D    |
| 25    | REPO-12.2  | #2953 | project auto-creation policy & conflict handling   | No  | E    |
| 26    | REPO-12.5  | #2954 | notifications on auto-import failure / warnings    | No  | E    |

---

## Cross-cutting integration & test plan

| Area                | Existing assets                                          | Add inside the listed issues                                              |
|---------------------|----------------------------------------------------------|---------------------------------------------------------------------------|
| Tree walker         | REPO-2.1, REPO-2.3, REPO-2.4                             | `content_checksum` streaming (REPO-8.1)                                   |
| Import pipeline     | REPO-3.x importers, REPO-5.1 dispatcher                  | Selection + checksum gates (REPO-8.3, REPO-12.1)                          |
| Manifest schema     | REPO-2.4                                                 | `specs[].importEnabled` opt-in (REPO-9.1)                                 |
| Scheduler           | REPO-4.1 / 4.2 / 4.4 / 4.5                               | Emits scan-complete events consumed by REPO-12.1 / 12.4                   |
| Linked-account probes | REPO-7.4                                               | Feeds `token_revoked` into `repository_attention` (REPO-11.1)             |
| Repository detail UI | REPO-6.2, REPO-6.3                                      | New Specs tab (REPO-9.4); spec drawer (REPO-9.6); Issues tab (REPO-11.4) |
| Repositories index  | REPO-6.1                                                 | "Scan reports" header link → REPO-10.1                                    |
| Workflow audit      | REPO-7.1                                                 | New codes: `repository.scan.hashed`, `repository.scan.skipped_checksum`, `repository.spec.selection_changed`, `repository.auto_imported`, `repository.scan_report.purged` |
| Change reports      | REPO-5.4 / 5.5 / 5.6                                     | Linked from REPO-11.3 widget rows (REPO-12.6)                             |
| Dashboard           | `/ade/dashboard` shell (existing)                        | Two new widgets (REPO-11.2, REPO-11.3)                                    |
| Notifications       | existing notification module                             | New channels for auto-import outcomes (REPO-12.5)                         |
| MCP read surface    | `PLANNED_FEATURE_ROADMAP_MCP.md` (Epic 7)                | Future: expose `repository.list_attention`, `repository.list_specs`       |

**E2E coverage to add inside the issues (not stand-alone tickets)**:

- `e2e/repo-scan-checksum-skip.spec.ts` (REPO-8.1, REPO-8.3)
- `e2e/repo-scan-selection-toggle.spec.ts` (REPO-9.1, REPO-9.2, REPO-9.4)
- `e2e/repo-scan-import-now.spec.ts` (REPO-9.5)
- `e2e/repo-scan-spec-drawer.spec.ts` (REPO-9.6)
- `e2e/repo-scan-report-page.spec.ts` (REPO-10.1, REPO-10.2)
- `e2e/repo-scan-attention-widgets.spec.ts` (REPO-11.2, REPO-11.3)
- `e2e/repo-scan-auto-import-pipeline.spec.ts` (REPO-12.1, REPO-12.3, REPO-12.4)

---

## Open questions (track separately, not blocking MVP)

1. Should `repository_attention.reasons` carry per-reason
   `last_seen_at` for "snooze for 24 h" UX? (V2 candidate;
   would slot into REPO-11.4.)
2. Cross-tenant fingerprinting via `content_checksum` is technically
   possible but raises confidentiality concerns; explicitly out of
   scope for v1, revisit under governance roadmap.
3. Do we want `auto_import_enabled = TRUE` to imply automatic
   **promotion** (not just dry-run)? Current design dispatches a
   dry-run job; promotion still respects REPO-5.6 manifest gates.
   Worth a dedicated discussion in V2.
