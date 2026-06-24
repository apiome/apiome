# Objectified — First Release Candidate (RC1) Roadmap

> **Goal:** Ship the first complete, public-quality version of Objectified — the **MVP spine** that lets a
> team design schemas and APIs, validate them, version them, store them as the source of truth, and publish
> them — hardened to a standard we are comfortable putting in front of strangers.
>
> **Status (2026-06-23): very close.** The MVP spine is already *built*. RC1 is overwhelmingly about
> **hardening, closing a small number of trust gaps, and release engineering** — not net-new feature
> construction. This document is the ordered path from "it works on our machines" to "RC1 is public."
>
> **How to read this:** Steps are listed in **execution order**, grouped into phases. Within each phase,
> items are in **priority order** (most release-blocking first). Each step states *why it blocks RC*, its
> *dependencies*, and its *exit criteria*. Items marked **‖ parallel** can run alongside the step above them.

---

## 1. The MVP Spine

The minimal end-to-end value loop Objectified must deliver on its own:

```
   Import / Author  →  Design  →  Validate  →  Version  →  Store (source of truth)  →  Publish
   (CLI · UI · MCP)    (Atlas    (linting/    (git-like   (objectified-db)            (browse ·
                        types →   quality      branches,                               static docs ·
                        Designer  scoring)     diff,                                   OpenAPI/SDK
                        → Paths)               publish)                                export · mocks)
```

This loop is the product. Everything else in `docs/planning/mockups` (Marketplace, the ETL/ingestion
suite, Monetization, Academy, Gateway, Enterprise Hub, …) is **post-RC1** and explicitly out of scope below.

---

## 2. What's Done Now ✅

Verified against the codebase (not the mockups). The spine is substantially implemented across all packages.

| Spine capability | Status | Where it lives |
|---|---|---|
| **Type registry (Atlas) / Primitives** | ✅ Built | `objectified-rest` `/v1/primitives` (12 ep), `/v1/types` namespaces (7 ep); JSON Schema 2020-12 validation; `$ref` resolution |
| **Designer — Classes & Properties** | ✅ Built | REST `/v1/classes` (11 ep), `/v1/properties` (5 ep); UI visual canvas `objectified-ui /ade/studio/editor` (React Flow, drag-drop, groups, export wizard) |
| **Paths — OpenAPI 3.x operations** | ✅ Built | REST `/v1/paths` (33 ep: operations, params, bodies, responses, canvas persistence); UI `/ade/studio/paths` |
| **Versioning — git-like** | ✅ Built | REST branches/merge/push/pull/tags/commit metadata (`version_merge_routes`, `versions_routes`); UI `/ade/dashboard/versions` with diff viewer & lineage |
| **Compatibility / breaking-change** | ✅ Built | `compatibility_engine.py`, `/v1/versions/.../compatibility`; change reports |
| **Import** | ✅ Built | Async jobs `/v1/tenants/{t}/imports` (OpenAPI/JSON Schema/Arazzo); UI import (file/URL/clipboard/Git/SwaggerHub/Postman/AI); CLI `import auto/openapi/arazzo/json-schema` |
| **Storage (objectified-db)** | ✅ Built (snapshot model) | 117 Flyway migrations; `/v1/data` records + snapshots; admin CLI (tenants/users/apikeys/migrate) |
| **Publish — interactive browse** | ✅ Built | `objectified-browse` public app: discovery, search, spec viewer, version compare; REST `/v1/browse/*` |
| **Publish — spec generation/export** | ✅ Built | REST `/v1/schema`, `/v1/swagger`, `/v1/json`, `/v1/arazzo` (JSON/YAML); UI export wizard (OpenAPI, Mermaid, PlantUML, PNG/SVG/PDF) |
| **Auth (baseline)** | ✅ Built | JWT (NextAuth) + API key (`X-API-Key`); tenant membership checks; `/login`, OAuth |
| **Tenancy / Projects** | ✅ Built | REST `/v1/projects`, `/v1/tenants`; UI management pages |
| **API Keys** | ✅ Built | UI `/ade/dashboard/api-keys`; CLI `api-keys`, `tokens`; admin CLI |
| **MCP server** | ✅ Built | `objectified-mcp` — 16 tools (spec list/describe/search/semantic/operations/components), stdio + HTTP, scoped keys |
| **CLI** | ✅ Built | `objectified-cli` — 15+ command groups (auth, repos, import, spec export, paths, types, tokens, api-keys, integrations) |
| **Marketing site** | ✅ Built | `objectified-web` (features, pricing, screenshots, MCP docs) |
| **Local run / compose** | ✅ Built | `docker-compose.yml` (Postgres + migrate + mcp), `run.sh`, `setup.sh`, Turborepo |

**Takeaway:** there is no missing spine *feature*. RC1 risk is concentrated in the gaps and hardening below.

---

## 3. Known Gaps & Soft Spots (the real RC1 work)

These came out of the codebase assessment and the mockup gap analysis. Each is addressed by a step in §4.

1. **Quality score is a stub.** The A–F "quality score" shown in the UI is computed/stored client-side
   (localStorage), not by a real linting/scoring service. Linting is a headline spine capability and the
   word "quality" is in the release name — this must be a real backend feature.
2. **RBAC is binary.** Only tenant *member vs. admin* exists (`is_user_tenant_admin`), with scattered
   `_assert_tenant_admin` checks and no platform-admin separation. Insufficient for multi-tenant public use.
   → New mockup: `docs/planning/mockups/access/`.
3. **No backup / disaster recovery.** "Source of truth" with no backup, restore, or PITR story is a
   credibility blocker. → New mockup: `docs/planning/mockups/backup/`.
4. **No mock server.** Highest-leverage, lowest-effort dev-value gap; closes design→consume loop. Generated
   directly from existing spec output. → New mockup: `docs/planning/mockups/mock-server/`.
5. **Onboarding is empty.** `README.md` "Getting Started" is blank; there's no first-run sample/templates.
   A public visitor hits a wall. (No code gap — a content/seed gap.)
6. **Release engineering unproven at RC bar.** Test coverage across the full spine, security review, rate
   limiting, observability, and a production (non-compose) deploy story are not yet established as a gate.

---

## 4. The Ordered Plan

Five phases. Ship gates at the end of Phase 4 (`RC1`) and Phase 5 (`GA-ready`). Rough sizing: **S** ≤ 3 days,
**M** ≈ 1 week, **L** ≈ 2–3 weeks, per item with one focused owner.

---

### Phase 0 — Prove the Spine & Stop the Bleeding  *(week 1)*  · **Epic #3603**
*Lock down what's already built before adding anything. Nothing here is optional.*

**0.1 — End-to-end spine smoke test** (#3608) · **M** · *blocks everything* · ✅ **Done**
Author one golden path exercised in CI and by hand: `import an OpenAPI doc → edit a class & a path in the
UI → lint → cut a version → publish → view in browse → export OpenAPI + download via CLI → query via MCP`.
This is both a regression net and the definition of "the product works."
*Exit:* a scripted run (and a manual checklist) that goes green start-to-finish on a clean `docker compose up`.
*Delivered:* `scripts/golden_path/` (harness + `run.sh` + fixture), [`docs/GOLDEN_PATH.md`](GOLDEN_PATH.md)
manual checklist, `rest` + `seed` services added to `docker-compose.yml`, and the
`.github/workflows/golden-path.yml` CI check.

**0.2 — Real quality-scoring / linting service** (#3609) · **L** · *blocks RC; gap #1*
Promote the A–F score from localStorage to a backend endpoint: a rule set over the OpenAPI/JSON-Schema
output (naming, descriptions, missing examples, unbounded arrays, breaking-change flags via the existing
`compatibility_engine`), returning a score + itemized findings. Wire the UI badges and a per-version report
to it. ‖ parallel with 0.3.
*Exit:* `GET .../lint` (or equivalent) returns deterministic findings + score; UI reflects server truth; CLI `lint` command added.
*Delivered:* REST `app/schema_lint.py` engine + `GET /v1/versions/{tenant}/{project}/{version}/lint`
(`app/lint_routes.py`, deterministic score/grade + itemized findings, optional `baseRevisionId` folds
`compatibility_engine` breaking-change flags); `objectified-cli lint` command (`--base-version`,
`--min-grade` CI gate); UI server-backed per-version quality badge + lint report dialog
(`VersionLintBadge`, `/api/projects/[projectId]/versions/[versionId]/lint` proxy).

**0.3 — Auth & secret hardening pass** (#3610) · **M** · *blocks RC* · ‖ parallel · ✅ **Done**
Token lifetimes/refresh, API-key scope audit, CORS, secret handling in compose/env (`docker-compose.env.example`
reviewed), brute-force/lockout on login. No new authz model yet — that's 1.1.
*Exit:* documented auth model; no plaintext secrets in repo/images; pen-test-style checklist passed.
*Delivered:* [`docs/security/AUTH_MODEL.md`](security/AUTH_MODEL.md) (tokens/keys/scopes/expiry, CORS, secrets)
and [`docs/security/RC1_HARDENING_CHECKLIST.md`](security/RC1_HARDENING_CHECKLIST.md); in-memory login
brute-force limiter (`objectified-ui/lib/auth/login-rate-limit.ts`) wired into credential + super-admin login;
configuration-driven REST CORS allow-list and a fail-closed production JWT secret (`objectified-rest/src/app/config.py`,
`main.py`); secret audit (only placeholder `.env` templates tracked, real `.env` git-ignored).

---

### Phase 1 — Access & Trust  *(weeks 2–4)*  · **Epic #3604**
*The things that make multi-tenant exposure safe. Highest-priority gap fills.*

**1.1 — Granular RBAC + platform-admin plane** (#3611) · **L** · *blocks RC; gap #2* · ✅ **Done**
Implement the `access/` mockup: roles (`Owner/Admin/Editor/Viewer` + custom), a `role_permissions` model,
and a **central permission guard** replacing ad-hoc `_assert_tenant_admin` checks on every route. Separate
platform-admin from tenant-admin. Member lifecycle (invite/suspend/offboard) UI.
*Depends on:* 0.3. *Exit:* every mutating route is permission-checked; matrix editable in UI; audit log of grants.

**1.2 — Security review of the branch/surface** (#3612) · **M** · *blocks RC* · ‖ parallel with 1.1 tail · ✅ **Done**
Run `/security-review`; address authz bypass, injection, SSRF (import-from-URL, repo refresh), file-upload,
and multi-tenant data-isolation findings. Add per-tenant rate limiting on public + auth endpoints.
*Exit:* no High/Critical findings open; rate limits enforced; isolation tests pass.
*Shipped:* SSRF guard (`app/ssrf_guard.py`) on import-from-URL + public-repo registration (generic + GitLab
branches), per-tenant rate-limit middleware (`app/rate_limit.py`), and a fixed GitLab-branch host-controlled
SSRF surfaced by the review. Tenant-isolation auth tests pass.

**1.3 — Backup & DR baseline** (#3613) · **M** · *blocks RC; gap #3* · ✅ **Done**
Implement the `backup/` mockup at MVP depth: scheduled logical backups (tenant + project scope), encrypted
off-site copy, a **documented and tested** restore runbook, and at least a manual PITR using the existing
snapshot+event model. Full DR-drill automation can trail into Phase 5.
*Exit:* a backup can be taken and **restored to a sandbox** successfully in a drill; RPO/RTO documented.
*Shipped:* `objectified-db backup` command group (`create`/`list`/`restore`/`prune`/`drill`) — AES-256-GCM
encrypted, off-site-mirrored logical (tenant/project) + full `pg_dump` backups with manifests + SHA-256
integrity; event-log PITR (`--as-of`) restored into an isolated sandbox schema; retention policy + cron
wrapper (`scripts/backup/scheduled-backup.sh`); RPO/RTO targets, restore runbook, and a verified DR drill in
[`docs/runbooks/BACKUP_AND_DR.md`](runbooks/BACKUP_AND_DR.md). 107 unit tests; end-to-end drill verified.

---

### Phase 2 — Developer Value & First-Run  *(weeks 4–6, overlaps Phase 1)*  · **Epic #3605**
*Make the first five minutes great and close the consume loop.*

**2.1 — Onboarding & sample content** (#3614) · **M** · *blocks RC; gap #5* · ✅ **Done**
Fill `README.md` Getting Started (compose quick-start + first-project walkthrough). Add a seeded **sample
project** and 2–3 **starter templates/blueprints** so a new tenant isn't empty. Guided first-run in the UI.
*Exit:* a brand-new user reaches a published, browsable spec in < 10 minutes without docs spelunking.
*Shipped:* shared idempotent `odb.provision_sample_project()` (objectified-db V122) auto-seeds a curated,
published+public "Pet Store" sample on **every** tenant-creation path — OAuth self-signup, admin tenant
create, the `objectified-db tenants provision-sample` / `tenants create --sample-creator` CLI, and the dev
seed; the sample renders end-to-end in Browse (verified live via `GET /v1/schema/.../petstore-sample/1.0.0`).
Starter templates reuse the existing 50 system `class_templates` (surfaced via the Designer template
browser). A dismissible **Get started** checklist on the dashboard derives completion from real stats
(localStorage-persisted). README "Your first project in ~10 minutes" walkthrough added. Tests: objectified-db
vitest (migration shape), objectified-rest pytest (sample render contract), objectified-ui jest (checklist
logic + component).

**2.2 — Mock Server** (#3615) · **L** · *high value; gap #4* · ‖ parallel with 2.1 · ✅ **Done**
Implement the `mock-server/` mockup: one-click hosted mock from a published version, schema-valid responses
(examples + faker), per-operation scenarios, optional stateful mode. Generated from existing
`/v1/swagger/...` output. Free-tier mocks auto-expire.
*Exit:* provision a mock, hit it, get schema-valid responses; expiry + rate limit enforced.
*Shipped:* objectified-rest mock plane — management `/v1/mocks/{tenant}` (provision/list/get/active-scenario/destroy)
+ public data plane `/v1/mock/{id}/...`. Frozen OpenAPI spec per instance; deterministic schema-valid response
synthesis (`mock_data_generator`) validated with jsonschema; selectable per-operation scenarios (status/latency/body,
4 built-ins + `X-Mock-Scenario` header); free-tier auto-expiry (410) + per-instance rate limit (429). Migration V123
`odb.mock_instances`. Tests: pytest (generator, engine, routes, migration).
*Note:* if velocity is tight, 2.2 may slip to Phase 5 — it is the most deferrable RC item. 2.1 may not slip.

---

### Phase 3 — Release Engineering & Operability  *(weeks 5–7, overlaps Phase 2)*  · **Epic #3606**
*What turns "works" into "operable in production."*

**3.1 — Test coverage across the spine** (#3616) · **L** · *blocks RC* · ✅ **Done**
Integration tests on the REST routers touched by the golden path; component tests on the UI editors;
contract tests between UI ↔ REST. CI gates merges on them.
*Exit:* spine endpoints + editors covered; CI red on regression of the golden path.
*Delivered:* the objectified-rest pytest suite was repaired (collection errors fixed, suite made
deterministic and DB-free) and is now gated in CI with coverage (`objectified-rest-test.yml`);
objectified-ui CI now reports coverage; a shared UI↔REST golden-path contract
(`scripts/golden_path/contract.json`) is verified from both sides; and the class-designer editor
toolbar gained component tests. See `docs/TESTING.md`.

**3.2 — Observability & error handling** (#3617) · **M** · *blocks RC* · ‖ parallel
Structured logs (MCP already uses structlog — extend to REST), health/readiness endpoints, error tracking,
and a minimal ops dashboard (request rate, error rate, latency, backup status). Graceful API error envelopes.
*Exit:* a failing request is diagnosable from logs/metrics alone; health checks wired into compose/deploy.

**3.3 — Production deployment story** (#3618) · **M** · *blocks RC* · ‖ parallel
Promote `docker-compose` to a documented production deploy (TLS, managed Postgres or pinned volume, secrets,
backups from 1.3 wired in, migration step gated). Reproducible from a clean host.
*Exit:* documented deploy runbook produces a working stack on a fresh environment; rollback documented.

**3.4 — Documentation set** (#3619) · **M** · ‖ parallel
User guide for the spine, API reference (the REST app already serves Swagger UI — publish it), MCP setup,
CLI reference. Keep it lean; depth can grow post-RC.
*Exit:* each spine capability has a "how do I…" page; MCP/CLI quick-starts exist.

---

### Phase 4 — RC1 Stabilization & Gate  *(week 8)*  · **Epic #3607**
*Dogfood, burn down, sign off.*

**4.1 — Private beta / dogfood** (#3620) · **M** — invite a small cohort; triage on real usage.
**4.2 — Bug burn-down** (#3621) · **M** — fix Critical/High; defer the rest with explicit notes.
**4.3 — Performance & accessibility pass** (#3622) · **S–M** — load-check the spine endpoints; a11y audit of editors/browse.
**4.4 — RC1 release gate** — all boxes in §5 checked → **tag `v1.0.0-rc.1`, announce publicly.**

---

### Phase 5 — Post-RC Hardening → GA  *(after RC1)*
Roll feedback in; promote deferred items: full automated DR drills, Mock Server (if slipped), BYOK/encryption
& data residency, project-scoped roles, deeper analytics/monitoring, and the **next** product tier from
`FUTURE_OFFERINGS.md` launch sequence (Playground, Academy, Gateway…). RC→GA when the gate holds under real load.

---

## 5. RC1 Release Gate Checklist

Public RC1 ships only when **all** of these are true:

- [ ] Golden-path E2E (0.1) green in CI **and** on a clean `docker compose up`.
- [ ] Quality/linting score is server-computed and consistent across UI/CLI (0.2).
- [ ] Every mutating REST route enforces the RBAC permission guard (1.1).
- [ ] `/security-review` shows **no open High/Critical**; rate limiting live (1.2).
- [ ] A backup has been **restored successfully in a drill**; RPO/RTO documented (1.3).
- [ ] New user reaches a published, browsable spec in < 10 min via onboarding + sample (2.1).
- [ ] Spine has integration/component test coverage gating merges (3.1).
- [ ] Logs/metrics/health checks make a failure diagnosable; backup status visible (3.2).
- [ ] Production deploy reproducible from a clean host with a rollback path (3.3).
- [ ] Spine user guide + API/MCP/CLI references published (3.4).
- [ ] Beta bug burn-down complete; no Critical/High open (4.2).

---

## 6. Critical Path & Velocity Notes

- **Hard sequence:** `0.x → 1.1 → (1.2, 1.3) → 4.x gate`. RBAC (1.1) is the longest pole and gates the
  security review (1.2); start it the moment Phase 0 lands.
- **Run in parallel** to protect velocity: 0.2‖0.3, 2.1‖2.2, and all of Phase 3 alongside Phase 2.
- **Only safely deferrable RC items:** **2.2 Mock Server** (high value but not a trust blocker) and
  **full DR-drill automation** (the manual restore in 1.3 is the gate; automation is Phase 5).
- **Do not defer:** 1.1 RBAC, 1.2 security, 1.3 backup baseline, 2.1 onboarding, 0.2 quality scoring — these
  are what separate "demo" from "public RC."
- **Indicative timeline:** ~8 weeks to `v1.0.0-rc.1` with 2–3 focused contributors, given how much of the
  spine is already built.

---

## 7. Explicitly Out of Scope for RC1

Deferred to post-RC (tracked elsewhere / in `FUTURE_OFFERINGS.md`): Marketplace, Monetization/billing,
Gateway, the ingestion/ETL suite (Bulk, Stream, CDC, Forge, Temporal, Reverse-ETL, DeltaSync, File-Gateway,
Data-Federate), Academy, Enterprise Hub, Multi-Protocol, Pact broker, Connect, Wormhole, Comply/CAB,
Localization, Mobile SDK, Copilot, Predict, BYOK/data-residency, and project-scoped RBAC. These are real and
valuable — they are simply not required for a *complete, trustworthy first public version of the spine*.

---

## 8. Supporting Mockups Created With This Roadmap

The three RC-relevant gaps now have draft mockups (static HTML, matching the existing convention):

- `docs/planning/mockups/access/` — Roles & permission matrix, Members & SSO/SCIM, Access audit *(supports 1.1)*
- `docs/planning/mockups/mock-server/` — Mock servers, Scenario editor, Connect & try *(supports 2.2)*
- `docs/planning/mockups/backup/` — Backup catalog, Restore & PITR, DR drills *(supports 1.3)*

All three are registered in `docs/planning/mockups/index.html`.

---

## 9. GitHub Issue Tracker

Created in `objectified-project/objectified` (pack label `roadmap-first-rc`, all tagged `mvp`):

| Issue | Title | Phase |
|---|---|---|
| #3603 | Epic: RC1 Phase 0 — Prove the Spine & Stop the Bleeding | 0 |
| #3604 | Epic: RC1 Phase 1 — Access & Trust | 1 |
| #3605 | Epic: RC1 Phase 2 — Developer Value & First-Run | 2 |
| #3606 | Epic: RC1 Phase 3 — Release Engineering & Operability | 3 |
| #3617 | RC1-3.2 — Observability & error handling | 3 |
| #3618 | RC1-3.3 — Production deployment story | 3 |
| #3619 | RC1-3.4 — Documentation set (spine + API/MCP/CLI) | 3 |
| #3607 | Epic: RC1 Phase 4 — Stabilization & Release Gate | 4 |
| #3620 | RC1-4.1 — Private beta / dogfood | 4 |
| #3621 | RC1-4.2 — Bug burn-down | 4 |
| #3622 | RC1-4.3 — Performance & accessibility pass | 4 |

---

*Last updated: 2026-06-23 · Owner: TBD · Target tag: `v1.0.0-rc.1`*
