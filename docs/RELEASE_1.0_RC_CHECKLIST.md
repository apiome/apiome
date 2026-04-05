# Release 1.0 First Release Candidate (RC) Checklist

**Goal:** Ship a stable 1.0 RC with **bug fixes and polish only**. No new features until the first RC is done.

**Scope:** Objectified Studio (objectified-ui), core flows: schema design (canvas), Paths/API designer, import, export, auth, and admin. Supporting services (objectified-rest, objectified-db, objectified-web, objectified-browse) should be build-clean and test-clean where applicable.

---

## 2. Lint and TypeScript (Small Fixes)

2.1 - **paths-client.ts:** Many `@typescript-eslint/no-explicit-any` violations. For RC, either:
  - Add proper types for path/operation/parameter/response payloads, or
  - Add a single file-level `/* eslint-disable @typescript-eslint/no-explicit-any */` with a short comment and a follow-up ticket to type properly post-RC.
2.2 - **E2E specs:** Clean up unused variables and explicit `any` in:
  - `e2e/authenticated.spec.ts` (e.g. `loginAndVerify`, `error`, and `any` type)
  - `e2e/components.spec.ts` (`navigationPromise`, `initialBg`, `hoverBg`)
  - `e2e/login.spec.ts` (`logo`)
2.3 - **npm warning:** “Unknown env config devdir” and “baseline-browser-mapping is over two months old” are optional cleanups (env config in npm, update baseline-browser-mapping).

---

## 3. User-Facing Bug Fixes (No New Features)

3.1 - **Contact form:** `objectified-web/src/app/contact.disabled/page.tsx` has `// TODO: Implement actual form submission`. Either keep the page disabled for RC or implement minimal submission (e.g. post to API or mailto) and remove the TODO.
3.2 - **Credentials/licensing:** `objectified-ui/lib/auth/credentials.ts` has `TODO: Check licenses here.` For RC, document current behavior (e.g. “no license check”) and leave implementation for post-1.0 unless it’s a known bug.
3.3 - **Import flow:** Consider trimming or guarding `console.log` in `ImportDialog` (e.g. only in dev or behind a debug flag) so production console stays clean. Optional for RC.

---

## 4. Roadmap-Derived Polish (Existing Features Only)

These are “already implemented” or “partial” areas where small fixes improve RC quality without adding scope:

4.1 - **Paths Designer (FEATURE_ROADMAP_PATHS.md, PLANNED_IMPROVEMENTS_ROADMAP_PATHS.md):**
  - Validation: Ensure unique operationIds, valid path params, and required request body/content types are enforced and that validation errors are visible (e.g. in UI or export).
  - No new UX features (e.g. no focus mode, overlay editor, or new toolbar); only fix incorrect or missing validation behavior.
4.2 - **Canvas / Studio:** Rely on existing fix docs (e.g. drag-drop reliability, group position, memory leak, theme) and confirm no regressions; no new canvas features for RC.
4.3 - **Git integration (FEATURE_ROADMAP.md):** Marked implemented; verify “push to Git on publish” and repo browser still work and errors are shown to the user.
4.4 - **OpenAPI 3.1 / JSON Schema:** Roadmap says ~95%+ implemented; for RC, fix any known bugs in existing property/schema editors (e.g. tuple mode, constraints) without adding new spec features.

---

## 5. Testing and Build

5.1 - **Unit/integration:** All 1980 Jest tests pass. Before tagging RC, run full suite (including DB-backed tests if applicable) and fix any flakiness or environment-dependent failures.
5.2 - **E2E:** Run Playwright (e.g. `npm run test:e2e`) and fix any failing critical paths (login, dashboard, open studio, create class, import, paths designer open). No new E2E coverage required for RC.
5.3 - **Build:** `npm run build` in objectified-ui (and any other apps you ship) must succeed. Resolve any build errors or warnings that block a production build.

---

## 6. Documentation and Version

6.1 - **Version:** When ready for the first RC, set version to `1.0.0-rc.1` (e.g. in `objectified-ui/package.json`) and document in CHANGELOG or WHATS_NEW what’s included and what’s known to be out of scope.
6.2 - **README / docs:** Ensure “first run” and “minimum requirements” (Node, DB, env vars) are accurate so install and run are repeatable.

---

## 7. Explicitly Out of Scope for 1.0 RC

Do **not** add or scope the following for the first RC; defer to post-1.0 or later RCs:

7.1 - New roadmap features (violation detection, layout snapshots, focus mode, overlay editor, canvas toolbar, SDK generation, developer portal, etc.).
7.2 - New integrations (ReDoc, Slate, IDE plugins, webhooks, gateway connectors).
7.3 - New compliance or quality scoring features beyond existing validation.
7.4 - Any “planned” or “TODO” items that are clearly new functionality rather than fixes to existing behavior.

---

## 8. Quick Reference: Where Things Live

| Area              | Primary location / docs |
|-------------------|-------------------------|
| Studio UI         | objectified-ui/         |
| Paths designer    | objectified-ui/…/paths/ |
| Import            | ImportDialog, import-helper, import-actions |
| Roadmaps          | CURRENT_ROADMAP.md, FEATURE_ROADMAP*.md, PLANNED_*.md |
| Bug fix history   | objectified-ui/docs/*FIX*.md, *BUG*.md |

---

**Summary:** Focus on lint/type cleanups, small user-facing bug fixes (especially error messaging and TODOs that block or confuse users), validation correctness for existing features, and a green build + tests. No new features until 1.0 RC is shipped.
