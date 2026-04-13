# Planned features: Objectified first-release MVP

This document is a **sequencing and verification guide** for shipping a credible **first MVP** of Objectified. It is **not** a substitute for GitHub issue bodies; it ties together the existing roadmaps, **`KenSuenobu/objectified-commercial`** issue numbers, and what exists today in **`objectified-ui`** and **`objectified-rest`**.

**Scope order for MVP (product narrative):**

1. **Git-like** versioning (commit / push / pull / branch / merge / history / rollback / audit) — complete the remaining `mvp`-labeled work and prove it end-to-end.
2. **Paths** — OpenAPI 3.2 paths authoring aligned to **P-00 → P-17** (exclude **P-18** and **V2-01 → V2-05** from first MVP).
3. **AI** — Studio AI (Ollama-backed chat, context, guardrails, and prioritized NL/schema assist) per **`docs/PLANNED_FEATURE_ROADMAP_AI.md`**.

**Rules you asked for:**

- **Do not create new GitHub issues from this file.** Where work is missing but no issue exists, each section calls out **“Consider creating an issue for …”** instead.
- Issue numbers for Git-like and Paths refer to **`KenSuenobu/objectified-commercial`** (see `docs/PLANNED_FEATURE_ROADMAP_GITLIKE.md` and `docs/PLANNED_FEATURE_ROADMAP_PATHS.md`).
- AI ticket numbers in **`docs/PLANNED_FEATURE_ROADMAP_AI.md`** use **short numeric IDs (e.g. #257)** without a repo slug. **Before scheduling,** map each to a commercial-repo issue or add a single **AI epic** with children—this document does not invent those numbers.

---

## How to read issue status

- **`docs/PLANNED_FEATURE_ROADMAP_GITLIKE.md`** marks many P0/P1 items as **shipped** or **done**. Treat that as **authoritative until you re-verify** in GitHub (issue open/closed) and in the app.
- **`objectified-rest`** already contains substantial implementations tied to those tickets (e.g. optimistic locking / `STALE_HEAD` on push in `versions_routes.py`, merge routes in `version_merge_routes.py`, merge session persistence comments referencing **#2573**).
- **`objectified-ui`** has a large **Versions** surface under ADE (`src/app/ade/dashboard/versions/page.tsx` and related) and **Paths** under **`/ade/studio/paths`** with REST-backed clients (`lib/api/paths-client.ts`, API routes under `src/app/api/paths/`). The Paths **roadmap issues** may represent **parity work**, **UX alignment**, or **gap closure** versus what is already built—each Paths issue should be **closed only when its acceptance criteria match the current product**.

---

## Phase A — Git-like versioning and workflow (complete MVP slice)

**Epics (parent issues):** [#2558](https://github.com/KenSuenobu/objectified-commercial/issues/2558) (commit/push/sync), [#2559](https://github.com/KenSuenobu/objectified-commercial/issues/2559) (branch/merge), [#2560](https://github.com/KenSuenobu/objectified-commercial/issues/2560) (audit API), [#2561](https://github.com/KenSuenobu/objectified-commercial/issues/2561) (history/compare/rollback).

### A.1 Ordered issues (dependency-safe)

Implement and verify in this order so each step stays testable. **Issue → roadmap ID** for cross-reference.

| Order | Issue | ID | Notes (from roadmap) |
|------:|------|-----|------------------------|
| 1 | [#2563](https://github.com/KenSuenobu/objectified-commercial/issues/2563) | P0-01 | Commit metadata on revisions — roadmap: shipped |
| 2 | [#2564](https://github.com/KenSuenobu/objectified-commercial/issues/2564) | P0-02 | Commit dialog — roadmap: done |
| 3 | [#2565](https://github.com/KenSuenobu/objectified-commercial/issues/2565) | P0-03 | Pre-commit policy — roadmap: done |
| 4 | [#2566](https://github.com/KenSuenobu/objectified-commercial/issues/2566) | P0-04 | Push base revision / optimistic locking — roadmap: done |
| 5 | [#2567](https://github.com/KenSuenobu/objectified-commercial/issues/2567) | P0-05 | 409 / `STALE_HEAD` banner + CTAs — roadmap: done |
| 6 | [#2568](https://github.com/KenSuenobu/objectified-commercial/issues/2568) | P0-06 | Pull conditional fetch / ETag / 304 — roadmap: done |
| 7 | [#2569](https://github.com/KenSuenobu/objectified-commercial/issues/2569) | P0-07 | Sync indicators (dirty / unpushed / ahead) — roadmap: done |
| 8 | [#2570](https://github.com/KenSuenobu/objectified-commercial/issues/2570) | P0-08 | Branch from revision API — roadmap: shipped |
| 9 | [#2571](https://github.com/KenSuenobu/objectified-commercial/issues/2571) | P0-09 | Branch creation dialog from history — roadmap: shipped |
| 10 | [#2572](https://github.com/KenSuenobu/objectified-commercial/issues/2572) | P0-10 | Merge preview (dry-run) — roadmap: shipped |
| 11 | [#2573](https://github.com/KenSuenobu/objectified-commercial/issues/2573) | P1-01 | Persist merge session + conflicts — roadmap: shipped |
| 12 | [#2574](https://github.com/KenSuenobu/objectified-commercial/issues/2574) | P1-02 | Conflict list UI — roadmap: shipped |
| 13 | [#2575](https://github.com/KenSuenobu/objectified-commercial/issues/2575) | P1-03 | Bulk resolve — roadmap: shipped |
| 14 | [#2576](https://github.com/KenSuenobu/objectified-commercial/issues/2576) | P1-04 | Block merge apply until resolved — roadmap: shipped |
| 15 | [#2577](https://github.com/KenSuenobu/objectified-commercial/issues/2577) | P1-05 | Workflow audit **ledger** + write path — roadmap: shipped |
| 16 | [#2578](https://github.com/KenSuenobu/objectified-commercial/issues/2578) | P1-06 | Audit API (filters + pagination) — **shipped** (`GET .../workflow-audit`, `objectified-rest/docs/WORKFLOW_AUDIT_API.md`) |
| 17 | [#2579](https://github.com/KenSuenobu/objectified-commercial/issues/2579) | P1-07 | History search/filter in timeline — **shipped** (ADE **Timeline** bar: search, author, date range, reset; REST `q`, `creatorId`, `createdAfter`, `createdBefore` on list versions) |
| 18 | [#2580](https://github.com/KenSuenobu/objectified-commercial/issues/2580) | P1-08 | Compare revision with current — **shipped** (version row **Compare with current** → schema diff dialog; base = selected, compare-to = latest head by `created_at`; timeline filters unchanged on close) |
| 19 | [#2581](https://github.com/KenSuenobu/objectified-commercial/issues/2581) | P1-09 | Rollback confirmation + impact summary — **shipped** (Radix **AlertDialog** after preview; REST **`impactSummary`** on rollback-preview) |
| 20 | [#2582](https://github.com/KenSuenobu/objectified-commercial/issues/2582) | P1-10 | Rollback audit persistence — **shipped** (`workflow_audit.detail`: **`fromRevision`**, **`toRevision`**, optional **`reason`**; `POST .../rollback` **`reason`**; **`metadata.rollback.reason`**) |

**First-release MVP (git-like):** per `PLANNED_FEATURE_ROADMAP_GITLIKE.md`, the **labeled MVP** slice is **P0-01 → P0-10** and **P1-05 → P1-10** (P1-01 → P1-04 are merge-resolution depth; roadmap shows them shipped). **P2-01 → P2-10** below are **enterprise / platform** follow-ons—**exclude from minimal MVP** unless you explicitly expand v1 scope.

| Order | Issue | ID | Topic |
|------:|------|-----|--------|
| — | [#2583](https://github.com/KenSuenobu/objectified-commercial/issues/2583) | P2-01 | Branch protection — **shipped** (`require_merge_path` + `metadata.branchPushPolicy.patterns`; push **403** `MERGE_PATH_REQUIRED`; `PATCH .../version-branches/{id}`; tenant-admin bypass) |
| — | [#2584](https://github.com/KenSuenobu/objectified-commercial/issues/2584) | P2-02 | Draft lock API — **shipped** (`draft-lock/acquire|renew|release|force-release`; **409** `DRAFT_LOCK_CONFLICT`; migration **`20260412-150000.sql`**) |
| — | [#2585](https://github.com/KenSuenobu/objectified-commercial/issues/2585) | P2-03 | Lock state in Studio header — **shipped** (**GET** `.../draft-lock` polling; chip + tooltip in **Studio** header) |
| — | [#2586](https://github.com/KenSuenobu/objectified-commercial/issues/2586) | P2-04 | Published immutability — **shipped** (`versions.published_immutable`; push/merge/rollback **409** `PUBLISHED_IMMUTABLE`; tenant-admin **`overridePublishedImmutability`** + **`overrideReason`** → **`workflow_audit`** **`version.immutability_override`**) |
| — | [#2587](https://github.com/KenSuenobu/objectified-commercial/issues/2587) | P2-05 | Push webhook CRUD — **shipped** (REST **`/v1/push-webhook-subscriptions/...`**; **signingSecret** write-only; **signingSecretRef** in responses; **409** **`WEBHOOK_URL_DUPLICATE`**; migration **`20260412-170000.sql`**) |
| — | [#2588](https://github.com/KenSuenobu/objectified-commercial/issues/2588) | P2-06 | Webhook retry + DLQ — **shipped** (delivery events/attempts, bounded backoff, dead-letter API; migration **`20260412-180000.sql`**) |
| — | [#2589](https://github.com/KenSuenobu/objectified-commercial/issues/2589) | P2-07 | Compatibility engine — **shipped** (`CompatibilityCheckEngine`, **`ruleHits`** on **`POST .../compatibility`**; **`workflow_audit`** **`schema.compatibility`** after **push** / **merge** success) |
| — | [#2590](https://github.com/KenSuenobu/objectified-commercial/issues/2590) | P2-08 | Compatibility report UI — **shipped** (grouped merge/rollback panel + **`version.compat_gate_override`** audit; merge **API** **`compatGateOverrideReason`**) |
| — | [#2591](https://github.com/KenSuenobu/objectified-commercial/issues/2591) | P2-09 | Pull options for CI — **shipped** (**`includeSections`** / **`excludeSections`** on **GET** `.../versions/.../{revisionId}` and **`.../by-version/...`**; same **ETag** as full body, #2568) |
| — | [#2592](https://github.com/KenSuenobu/objectified-commercial/issues/2592) | P2-10 | Delta pull — **shipped** (**`sinceRevisionId`** on revision **GET** pulls; **`schemaPullDelta`** for **`components.schemas`**; validation **400**s; **`guarantee`** field) |

**Consider creating an issue for:** a single **“Git-like MVP verification / release gate”** checklist if you want a non-code tracking umbrella (optional; not required by this doc).

### A.2 Codebase alignment (for verification, not redesign)

- **`objectified-rest`:** `versions_routes.py` documents **#2566** behavior (`baseRevisionId`, `STALE_HEAD`). `version_merge_routes.py` implements merge preview, merge apply, merge sessions (**#2572–#2574** area). **`workflow_audit`** (**#2577**) is the git-like workflow ledger; **`version_protection_audit`** remains separate for protection overrides. **P1-06** query API: **`GET /v1/versions/{tenant}/workflow-audit`** (**#2578**, `objectified-rest/docs/WORKFLOW_AUDIT_API.md`). **P1-07** list filters (**#2579**): **`GET .../versions/{tenant}/{project}`** optional **`q`**, **`creatorId`**, **`createdAfter`**, **`createdBefore`**. **P2-02** draft edit locks (**#2584**): **`POST .../versions/{tenant}/{project}/{revisionId}/draft-lock/acquire|renew|release|force-release`**; table **`odb.version_draft_lock`**. **P2-03** draft lock visibility (**#2585**): **`GET .../draft-lock`** (active lock + owner + expiry for polling). **P2-09** pull payload sections (**#2591**): **`includeSections`** / **`excludeSections`** on revision **GET** pulls. **P2-10** delta pull (**#2592**): **`sinceRevisionId`** on revision **GET** pulls; **`schemaPullDelta`** for OpenAPI **`components.schemas`**.
- **`objectified-ui`:** Versions UX is centralized in a very large dashboard module; when testing, prefer **stable selectors** or **data-testid** additions **inside the issues that own the UI** (this doc does not prescribe code).

### A.3 Testing checkpoint 1 — After P0-10 (merge preview) and P1-04

**Goal:** Prove **branch → preview → resolve → apply** without relying on later audit/history tickets.

**Manual / exploratory:**

1. Two clients or two browsers on the **same project/version branch**: advance **head** with A; with B, attempt **commit** with stale **base** → expect **409**, banner, **Pull** / merge path per **#2567**.
2. Run **merge preview** from the UI/API; confirm **no mutation** and sensible **conflict** payload (**#2572**).
3. Walk **conflict list**, **bulk actions**, and **apply** gating (**#2573–#2576**).

**Automated (recommended as follow-up work in those issues):**

- **REST:** integration tests already present under `objectified-rest/tests/`—extend **only** where merge/preview/regression gaps appear during verification.
- **Browser:** `objectified-ui/e2e/` uses Playwright (`playwright.config.ts`). **Consider creating an issue for:** authenticated E2E covering **merge preview dialog** and **409** path (today `navigation.spec.ts` mostly checks unauthenticated redirects).

### A.4 Testing checkpoint 2 — After P1-06 (audit API)

**Goal:** Operators can **query** workflow events with filters/pagination.

**Manual:**

1. Perform commits, merges, failed pushes; confirm **audit** records (**#2577**) and **API** behavior (**#2578**).
2. Spot-check **pagination** and **filters** (actor, action, date).

**Automated:**

- Contract tests against **OpenAPI** (if published) or **pytest** on the audit routes.

**Consider creating an issue for:** Studio **Audit** panel wired to **#2578** if product expects in-app browsing and no issue explicitly covers UI.

### A.5 Testing checkpoint 3 — After P1-10 (history + rollback + rollback audit)

**Goal:** Full **read → compare → rollback → audit** story.

**Manual:**

1. **Search/filter** history (**#2579**).
2. **Compare** revision vs current (**#2580**).
3. **Rollback** with confirmation and impact (**#2581**); confirm **audit** for rollback (**#2582**, **#2578**).

**Browser E2E (recommended in issue scope):**

- Playwright: select revision → compare → open rollback → confirm → timeline updates.

---

## Phase B — Paths (OpenAPI 3.2 designer MVP)

**Epics:** [#2633](https://github.com/KenSuenobu/objectified-commercial/issues/2633)–[#2637](https://github.com/KenSuenobu/objectified-commercial/issues/2637) (see `docs/PLANNED_FEATURE_ROADMAP_PATHS.md`).

### B.1 Ordered MVP issues (P-00 → P-17)

| Order | Issue | ID |
|------:|------|-----|
| 1 | [#2639](https://github.com/KenSuenobu/objectified-commercial/issues/2639) | P-00 |
| 2 | [#2640](https://github.com/KenSuenobu/objectified-commercial/issues/2640) | P-01 |
| 3 | [#2641](https://github.com/KenSuenobu/objectified-commercial/issues/2641) | P-02 |
| 4 | [#2642](https://github.com/KenSuenobu/objectified-commercial/issues/2642) | P-03 |
| 5 | [#2643](https://github.com/KenSuenobu/objectified-commercial/issues/2643) | P-04 |
| 6 | [#2644](https://github.com/KenSuenobu/objectified-commercial/issues/2644) | P-05 |
| 7 | [#2645](https://github.com/KenSuenobu/objectified-commercial/issues/2645) | P-06 |
| 8 | [#2646](https://github.com/KenSuenobu/objectified-commercial/issues/2646) | P-07 |
| 9 | [#2653](https://github.com/KenSuenobu/objectified-commercial/issues/2653) | P-14 (OPTIONS first-class; sequenced after P-07 in dependency charts—keep graph order if conflicts) |
| 10 | [#2647](https://github.com/KenSuenobu/objectified-commercial/issues/2647) | P-08 |
| 11 | [#2648](https://github.com/KenSuenobu/objectified-commercial/issues/2648) | P-09 |
| 12 | [#2649](https://github.com/KenSuenobu/objectified-commercial/issues/2649) | P-10 |
| 13 | [#2650](https://github.com/KenSuenobu/objectified-commercial/issues/2650) | P-11 |
| 14 | [#2651](https://github.com/KenSuenobu/objectified-commercial/issues/2651) | P-12 |
| 15 | [#2652](https://github.com/KenSuenobu/objectified-commercial/issues/2652) | P-13 |
| 16 | [#2654](https://github.com/KenSuenobu/objectified-commercial/issues/2654) | P-15 |
| 17 | [#2655](https://github.com/KenSuenobu/objectified-commercial/issues/2655) | P-16 |
| 18 | [#2656](https://github.com/KenSuenobu/objectified-commercial/issues/2656) | P-17 |

**Excluded from first MVP (roadmap):** [#2657](https://github.com/KenSuenobu/objectified-commercial/issues/2657) (P-18), [#2658](https://github.com/KenSuenobu/objectified-commercial/issues/2658)–[#2662](https://github.com/KenSuenobu/objectified-commercial/issues/2662) (V2-01 → V2-05).

**Note on P-14 vs numbering:** The roadmap table lists **P-14** between P-07 and P-08 in the epic chart. The order above follows **canvas/ops before parameters**; if **P-14** is purely additive, you can ship it **after P-07** or **after P-13** per team preference—**keep issue acceptance criteria** as the tie-breaker.

### B.2 Codebase alignment (compliance / corrections to consider)

- **Current route:** Paths live at **`/ade/studio/paths`** (`objectified-ui/src/app/ade/studio/paths/page.tsx`) with **sidebar + canvas + panels** and REST integration—see also `objectified-ui/docs/PATHS_IMPLEMENTATION_SUMMARY.md` (may be **ahead** or **divergent** from P-00–P-17 acceptance text).
- **REST / DB:** `objectified-rest/src/app/paths_routes.py` and UI BFF routes back paths data; roadmap stresses mapping to **`odb.version_path`**, **`odb.path_operation`**, and related tables—**reconcile** any **stale internal docs** vs current **Postgres/REST** path.
- **PATH QUALITY / OpenAPI 3.2:** P-16/P-17 require a clear **validation/export** story; `lib/db/helper-paths-export.ts` and OpenAPI generators are relevant—gaps should be **closed inside P-15–P-17**, not via silent one-off scripts.

**Consider creating an issue for:** **navigation parity** if product expects **Paths** next to **Designer** on **dashboard** chrome (**#2639**) but routing remains **studio-only**.

### B.3 Testing checkpoint 1 — After P-03 (persist canvas JSON per version)

**Goal:** No “demo-only” state—refresh survives.

**Steps:**

1. Create paths graph; **reload**; confirm **structure** restores (**#2642**).
2. **REST:** GET paths for version matches UI.

**E2E:** Playwright: login (see `e2e/authenticated.spec.ts` patterns) → `/ade/studio/paths` → create minimal path → reload → assert.

### B.4 Testing checkpoint 2 — After P-07 + P-14 (graph + OPTIONS)

**Goal:** Canvas **operations** and **edges** behave; **OPTIONS** is first-class if in scope.

**Steps:**

1. Drag **methods**, connect **edges**, edit **operation** inspector fields.
2. Validate **OPTIONS** operation parity (**#2653**).

### B.5 Testing checkpoint 3 — After P-13 (reuse / `$ref`)

**Goal:** Realistic API design: **parameters**, **bodies**, **responses**, **composition**, **refs**.

**Steps:**

1. Path/query/header/cookie coverage (**#2647–#2649**).
2. Responses + **allOf/anyOf/oneOf** + **ref pickers** (**#2650–#2652**).

### B.6 Testing checkpoint 4 — After P-17 (code, export, PATH QUALITY)

**Goal:** Shippable artifact: **Monaco/code**, **OpenAPI export**, **quality** gate.

**Steps:**

1. **Code** view matches canvas (**#2654**).
2. **Export** validates as **OpenAPI 3.2** paths object / document rules you defined (**#2655**).
3. **PATH QUALITY** score and dialog (**#2656**).

**E2E:** Export → download/clipboard → optional **spectral** or **openapi-cli** validation in CI **if** you add a devDependency for that in the issue (this doc does not mandate tooling).

---

## Phase C — AI features (after Git-like + Paths MVP)

**Source:** `docs/PLANNED_FEATURE_ROADMAP_AI.md`. Issue numbers below are **as listed in that file** (e.g. **#257**); they are **not** verified here against `objectified-commercial`.

### C.1 Suggested implementation order (dependency-first)

| Stage | Topics | Issue IDs (from AI roadmap doc) |
|-------|--------|----------------------------------|
| C.1 | **Infra / safety:** Guardrails server, sensitive-data guardrails, licensing/monitoring hooks from doc’s “Preparation” | **#262**, **#263**, **#264**, **#527** (plus preparation bullets—**no issue numbers** in doc; **consider creating issues** for cluster ops if not tracked) |
| C.2 | **Ollama:** model selection, defaults per tenant/project | **#265**, **#266** |
| C.3 | **Streaming / UX:** SSE streaming, token display, cancel, progress | **#520**, **#521**, **#522**, **#523** |
| C.4 | **Caching (optional for MVP):** query cache, semantic cache, invalidation | **#524**, **#525**, **#526** |
| C.5 | **Chat shell:** placement, design guidelines | **#257**, **#258** |
| C.6 | **Conversation + context:** context awareness, multi-turn, history actions | **#259**, **#260**, **#261** |
| C.7 | **Quick actions + apply:** actions from chat, preview before apply | **#518**, **#519** |
| C.8 | **NL → schema:** description → schema, examples, preview surface | **#267**, **#268**, **#528–#532** |
| C.9 | **Property assist:** suggestions, dropdown, bulk, triggers, analysis | **#269–#276**, **#277**, **#278** |
| C.10 | **Higher insights (post-MVP polish):** improvement suggestions, docs generation, layout hints, etc. | **#253–#256**, **#495**, **#609–#623** (schedule after core chat works) |

### C.2 Codebase alignment

- **`objectified-ui`** already has **Ollama** integration pieces: `src/app/api/ollama/chat/route.ts` (SSE), `src/app/api/ollama/models/route.ts`, usage from `ClassEditDialog.tsx`, `LLMImportDialog.tsx`, `QueryUsingAIPanel.tsx`, and `lib/embedding.ts`. **MVP work** is likely **productization**: unified **Studio panel**, **tenant-safe** config, **guardrails**, **telemetry**, and **tests**—not greenfield networking.
- **`objectified-rest`:** Confirm whether **long-term** AI orchestration stays **Next.js BFF–only** or moves to **REST** for auth/rate limits/audit; **consider creating an issue for** “AI API ownership” if absent.

### C.3 Testing checkpoint — After C.5–C.7 (chat + streaming + core context)

**Manual:**

1. Model list loads (**`/api/ollama/models`**).
2. Chat streams tokens; **cancel** mid-stream; errors surface cleanly.
3. **Context**: project/version/schema awareness per **#259** (acceptance in issue).

**E2E:**

- **Consider creating an issue for:** Playwright **mocking Ollama** (or pointing at a **fixed test server**) so CI is deterministic—today chat E2E may be **flaky** without mocks.

### C.4 Testing checkpoint — After C.8 (NL → schema)

**Manual:**

1. Prompt → **preview** → accept/reject; schema matches **classes**/**versions** (**#528–#532**).
2. **Guardrails:** injection / PII cases per **#263**, **#527**.

---

## Cross-cutting: browser / integration tests to plan explicitly

| Area | Existing assets | Suggested additions (track inside the listed issues) |
|------|-----------------|-----------------------------------------------------|
| Auth / routing | `objectified-ui/e2e/navigation.spec.ts`, `login.spec.ts`, `authenticated.spec.ts` | Reuse fixtures for **logged-in** flows |
| Git-like | — | Authenticated **versions** flow: commit → push conflict → pull/merge |
| Paths | — | **/ade/studio/paths** create → persist → export |
| AI | — | **Mocked** Ollama or dedicated **test env**; assert **SSE** chunks |

**Consider creating an issue for:** **Test data seed** (project/version/branch) shared across E2E suites.

---

## Single-page ordered checklist (MVP issues only)

**Git-like (commercial):** 2563–2576, 2577–2582 (P0-01–P1-10).

**Paths (commercial):** 2639–2646, 2653, 2647–2652, 2654–2656.

**AI:** Use **Phase C** table; map **#257+** from `docs/PLANNED_FEATURE_ROADMAP_AI.md` to commercial issues before execution.

---

## Revision

Update this file when:

- GitHub **closes** or **rescopes** an issue.
- You add **commercial** AI epics that replace the legacy **#257**-style numbering.
- Paths routing or **ADE** layout changes (dashboard vs studio) stabilize.
