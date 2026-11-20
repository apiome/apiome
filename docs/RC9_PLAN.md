# RC9 — Plan: Catalog, Projects, OpenAPI and Arazzo (after RC8)

_Drafted 2026-11-19 against `main`. RC9 is the release after RC8. **Theme: the core of Apiome** — Projects and
Catalog, with OpenAPI 3.2 / 3.1 and Arazzo 1.1 as the top priority, and catalog import/export fidelity._
_The Contracts and PactFlow release that was first called RC9 is now **RC10** ([`RC10_PLAN.md`](RC10_PLAN.md))._

**Tracking:** the [**Apiome: RC9**](https://github.com/orgs/apiome/projects/133) GitHub Project (items in order of
execution, by *Rank*) and the **RC9** milestone on `apiome/apiome`. The roadmap is
[`ROADMAP_CATALOG_PROJECTS_OPENAPI_ARAZZO.md`](ROADMAP_CATALOG_PROJECTS_OPENAPI_ARAZZO.md) (prefix `COA`).

---

## 0. What is in RC9

| Section | What | Where |
| --- | --- | --- |
| §1 | New tickets: Arazzo, OpenAPI fidelity and authoring, import/export fidelity, cleanup | Roadmap epics COA-EPIC-1…4 (25 issues) |
| §1 | Document store: originals and rendered documents in object storage (S3) | Roadmap COA-EPIC-5 ([#7076](https://github.com/apiome/apiome/issues/7076), #7077–#7090, #7092) |
| §2 | Existing issues adopted into the release | Roadmap §3 |
| §3 | Why now: current standards and competitive position | Roadmap §1 |
| §4 | Open decisions | below |

## 1. Scope in one paragraph each

- **Arazzo (COA-EPIC-1).** apiome-rest already reads and writes Arazzo 1.0.x and 1.1.x. The CLI, the legacy
  generator, the UI generator and the docs still say 1.0, workflows are stored but cannot be seen or read through
  an API, and an Arazzo file cannot import with the files it calls. RC9 makes Arazzo current, visible and testable.
- **OpenAPI (COA-EPIC-2).** 3.2.0 and 3.1.2 are current. Import and emit exist; RC9 proves nothing is lost across
  3.0/3.1/3.2, validates every version, handles JSON Schema dialects, adds bundle/dereference/split, puts the 3.2
  additions in the Projects editor and gives Overlays a UI.
- **Import and export (COA-EPIC-3).** The silent-loss ledger (628 pairs), scalar-name leaks in IDL targets,
  re-import failures, the 14 "not validated" targets, three owed sign-offs and the triage of ~86 deferred export tickets.
- **Cleanup (COA-EPIC-4).** Docs that contradict the code, Catalog ↔ Projects path parity, a usability audit and
  demo scripts.
- **Document store (COA-EPIC-5).** Today both sides of an OpenAPI diff are regenerated from classes and properties on
  every request, in REST and in a second TypeScript generator behind the UI's Versions, Catalog, merge-request and
  review views, and originals sit in Postgres TEXT/JSONB. RC9 stores originals and rendered documents in an
  S3-compatible store (filesystem/DB fallback), with normalized data kept in Postgres, so diffs, `/v1/schema`,
  exports, every UI document view and "download original" read stored bytes. A tenant can bring its own bucket.
- **Governance (adopted).** Arazzo/Overlay governance (#5875, #5879, #5880) and lint `--fix` (#5868–#5872), the
  catch-up items against Redocly, vacuum and Spectral.

## 2. Execution order

1 quick wins (COA-1.1, 2.2, 4.1, 3.5, 3.6) → 2 foundations (2.1, 1.5, 1.2, 4.3) → 3 fidelity and options (1.4, 2.3,
2.4, 2.7, 4.2, #5879, #5880) → 4 surfaces and burn-down (1.3, 2.5, 3.1–3.3, governance epics) → 5 demos and delivery
(4.4, #6706, #6654) → V2 (1.6, 2.6, 2.8, 3.4, 1.7). COA-EPIC-5 runs alongside phases 2–4 (5.1/5.2 → 5.3 → 5.4/5.5/5.7 → 5.6/5.13/5.14/5.8/5.10 → 5.15). The project's *Rank* field carries this order.

## 3. Carry-over from RC8

RC8 keeps Catalog/Projects work, Export & Interoperability (#3494), #6263 (first-row budgets, ✅ done 2026-11-19) and the withdrawal of
five features (#6894). Anything RC8 does not close moves here.

## 4. Decisions needed

1. **Version Archaeology (#1023) and Diff 0.247–0.251** (schema evolution timeline, change attribution,
   cross-project comparison, merge assistant) are Projects improvements, moved to the Diff project today. Take them
   into RC9?
2. **Arazzo execution (COA-1.7)** is V2 here; promote it if the competitive pressure from Specmatic matters more
   than the viewer (COA-1.3).
3. **Order against RC10.** RC9 is named first, but the Pact work in RC10 was due to start today; the two share no
   code, so they can run in parallel if you choose.

## 5. Issue numbers

Umbrella [#7032](https://github.com/apiome/apiome/issues/7032); epics [#7033](https://github.com/apiome/apiome/issues/7033), [#7034](https://github.com/apiome/apiome/issues/7034), [#7035](https://github.com/apiome/apiome/issues/7035), [#7036](https://github.com/apiome/apiome/issues/7036), [#7076](https://github.com/apiome/apiome/issues/7076) (COA-EPIC-5, document store). Issues are listed in the roadmap.
