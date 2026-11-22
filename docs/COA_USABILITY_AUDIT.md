# Projects and Catalog usability audit (COA-4.3)

_Walked 2026-11-21 against `main` @ `1cbec0ebc` for COA-4.3 ([#7060](https://github.com/apiome/apiome/issues/7060))._

RC8 narrowed to Catalog and Projects. This is the first end-to-end review of the core journey since the
facelift: **import → project → version → publish → export**. Every defect found is listed below with a
severity and what happened to it: fixed in the audit pull request, or ticketed into RC9.

## 1. Result

| | Count |
| --- | --- |
| Defects found | 18 |
| S1 — the journey cannot be completed | 1 (already ticketed: [#7113](https://github.com/apiome/apiome/issues/7113)) |
| S2 — a core step misleads or dead-ends | 5 (4 fixed here, one of them with a follow-up ticket; 1 ticketed) |
| S3 — a visible defect with a workaround | 8 (2 fixed here, 6 ticketed) |
| S4 — polish | 4 (1 fixed here, 3 ticketed) |
| Fixed in the audit pull request | 7 |
| New tickets (RC9 milestone, **Apiome: RC9** project) | [#7126](https://github.com/apiome/apiome/issues/7126), [#7127](https://github.com/apiome/apiome/issues/7127), [#7128](https://github.com/apiome/apiome/issues/7128), [#7129](https://github.com/apiome/apiome/issues/7129) |

Every S1 and S2 is either fixed or ticketed. #7113 was not in a release; it is now on the RC9 milestone and
project.

Severity scale:

- **S1** — the journey cannot be completed.
- **S2** — a core step misleads the user, loses their work or leaves them with no way forward.
- **S3** — visibly wrong or confusing, with an obvious workaround.
- **S4** — polish: wording, noise, an accessibility warning with no user impact found.

## 2. How the audit was run

**Journey specs.** `e2e/journey/catalog-project-journey.spec.ts` and `catalog-exporter-journey.spec.ts` run in
CI (`.github/workflows/e2e-catalog-journey.yml`). On `main` (run 44875041299, the #7059 merge) both jobs fail
at the first step after import: the catalog item page answers *Internal server error*. That is
[#7113](https://github.com/apiome/apiome/issues/7113). The specs were not run locally: E2E suites stay in CI
by house rule.

**Manual pass.** A local stack: a scratch Postgres migrated with `apiome-db` and the dev seed, `apiome-rest`
under uvicorn, and `apiome-ui` under `next dev`, signed in as the seeded `ada@example.com`. A scripted
browser walked the spec's steps with the spec's own fixture, the RAML corpus entry `raml/01-simple-api.raml`:
paste into **Import to catalog**, quality step, import, find it in the Catalog, open it, **Convert to OpenAPI
Project**, find the project, **Edit project**, **New version**, **Publish**, open the published spec, **Export**
to Protocol Buffers, **Unpublish**. A second walk pasted an OpenAPI 3.0 document
(`openapi/30-openapi-3.0-petstore.yaml`) into **Import to catalog**.

At every stop it captured the screen at **1440 × 900** and **1024 × 768**, in the **light** and **dark**
themes (the accessibility gate's appearance pins), and recorded:

- console errors and failed requests,
- horizontal overflow of the page,
- axe violations (serious and critical) inside `main`.

All 22 stops completed. No page overflowed horizontally at either width, and axe found nothing serious or
critical except S4-4. After the fixes, the whole RAML journey was walked again and passed, and the screens whose CSS changed
were captured again.

## 3. Defects

### S1

| # | Where | Defect | Status |
| --- | --- | --- | --- |
| S1-1 | Catalog journey in CI | Both journey jobs fail: the catalog item page returns 500 after the first AMF run (REST database connections drop). Locally the same journey passes. | Ticketed — [#7113](https://github.com/apiome/apiome/issues/7113) (now RC9) |

### S2

| # | Where | Defect | Status |
| --- | --- | --- | --- |
| S2-1 | Versions → **New version** | Every dialog opened on a red banner, *Couldn't load this project's branches — Not found*. Branch routes are switched off with git-like features (`src/middleware.ts` answers 404), but the page asked for them anyway. The page also read version tags on every load, another 404. | **Fixed** — both reads ask `isApiRouteDisabled` first |
| S2-2 | Versions → **New version** | **Copy from version** defaults to **Create blank version**. Accepting the defaults cut and published v1.1.0 with no paths and no schemas, and it scored **A · 100**. Nothing warned. | Ticketed — [#7126](https://github.com/apiome/apiome/issues/7126) |
| S2-3 | **Import to catalog**, OpenAPI source | Detection shows *Routing decision → Projects*, then **Continue** stays disabled with no reason and no way on. | **Fixed** (the card says to use **Import** on the Projects page and links there); ✅ the hand-off that carries the source along shipped in [#7127](https://github.com/apiome/apiome/issues/7127) — **Continue in Projects** opens the Projects importer on **Analyze** with a pasted, uploaded or URL source loaded |
| S2-4 | `catalog-project-journey.spec.ts` | `gotoVersions` waited for `versions-table`, but the Versions page opens on the **Timeline** view (facelift default). The spec would fail at *cuts a new version* as soon as S1-1 is fixed. | **Fixed** — the step switches to **Table** first |
| S2-5 | Catalog item page | Every load logged a React hydration error: the loading skeleton put a `div` inside the header's `<p>` description and `<h1>` title. | **Fixed** — `Skeleton as="span"` |

### S3

| # | Where | Defect | Status |
| --- | --- | --- | --- |
| S3-1 | **Import to catalog** → Quality | The selected finding's docs pointer was the repository path as plain text (`apiome-docs/docs/build/lint-rules.md#…`). | **Fixed** — a **Rule docs** link to the docs site |
| S3-2 | Projects → **Edit project** | **Created** and **Updated** were drawn at the headline-figure size; each date wrapped to three lines and the strip took a third of the dialog. | **Fixed** — body-size values |
| S3-3 | Catalog at 1024 × 768 | The header, the info banner and twelve kind tiles push the first item under the fold. | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the kind tiles become one sideways-scrolling row with an edge fade below 1,200 px |
| S3-4 | Versions tabs at 1024 | The tab strip is cut mid-word (*Test be…*) with no overflow cue. | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the tab strip fades the edge that hides tabs (`useOverflowEdges` + `.overflow-fade`) |
| S3-5 | **Import to catalog** → done | *Stored in the catalog…* has **Close** and **Done**, which do the same, and no link to the new item. | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the done step links **Open the catalog item** and keeps only **Done** |
| S3-6 | Catalog item → Overview | A fresh item says *The normalized-content summary has not been captured for this item yet.* while **Operations** lists 3 below it. | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the line is dropped when the parsed model lists entities |
| S3-7 | **Import to catalog** → Quality | The findings list opens scrolled, with finding #1 above the fold although it is selected. | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the raw viewer centres the line inside itself instead of `scrollIntoView`, which scrolled the wizard body |
| S3-8 | Converted project | Description *Converted from raml catalog item e1501f13-…* and a slug ending in the full catalog UUID, on the card, the Versions page, **Edit project** and every download name. | Ticketed — [#7129](https://github.com/apiome/apiome/issues/7129) |

### S4

| # | Where | Defect | Status |
| --- | --- | --- | --- |
| S4-1 | **Convert to OpenAPI Project** | The description named the format by its id: *Review what the raml source…*. | **Fixed** — the registry label (*RAML*) |
| S4-2 | **Import to catalog** → Quality | A finding's location is the internal model path (`services.<title> <timestamp>.operations.…`). | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the row shows the resolved source line; the model path is its tooltip |
| S4-3 | **Convert** → Summary | *Source OpenAPI version — source is not OpenAPI 3.2* is listed as missing for a non-OpenAPI source. | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the `n/a` **Source OpenAPI version** row is left out of the Summary columns |
| S4-4 | Versions row menu | With the menu open, axe reports `aria-hidden-focus` on the header, status strip and overview (the modal menu hides focusable siblings). | ✅ **Fixed** in [#7128](https://github.com/apiome/apiome/issues/7128) — the row menu is non-modal, so nothing is `aria-hidden` while it is open |

### Checked, not defects

| Where | Looked wrong | Why it stays |
| --- | --- | --- |
| **Convert** banner | A *High fidelity* banner carries the sentence *The fidelity … may not be complete enough…*. | The sentence is mandatory on every tier (MFI-22.4). |
| Export dialog title | A visible gap before the closing quote in *Export “… (OpenAPI)” v1.1.0*. | The display font's quote glyph; the markup has no space. |
| RAML import, locally | Quality, import and conversion of the journey's RAML fixture all worked and the REST stack stayed up. | Recorded for [#7113](https://github.com/apiome/apiome/issues/7113): the CI failure does not reproduce on a local stack. |

## 4. What the audit PR changed

| Defect | Change |
| --- | --- |
| S2-1 | `lib/gitlike-route-guard.ts` gains `isApiRouteDisabled(path, method)`, the middleware's rule; `src/middleware.ts` uses it, and the Versions page asks it before reading branches and tags. |
| S2-3 | `CatalogImportDialog`: the Projects routing card says the dialog does not import the source and links to **Open Projects**. |
| S2-4 | `e2e/journey/catalog-project-journey.spec.ts`: `gotoVersions` clicks **Table** before waiting for the table. |
| S2-5 | `Skeleton` takes `as="span"`; `CatalogDetailSkeleton` uses it in the header title and description. |
| S3-1 | `docsHrefFromPointer` in `src/app/utils/docsLinks.ts`; the quality step renders **Rule docs**. |
| S3-2 | `.prj-edit-stats .hive-stat__value` sets body-size values in **Edit project**. |
| S4-1 | `ConversionPreviewDialog` names the source by `resolveCatalogFormat(…).label`. |

Each change has unit tests (`tests/versions-hive-redesign.test.tsx`, `tests/unit/gitlike-route-guard.test.ts`,
`tests/CatalogImportDialogDetect.test.tsx`, `tests/catalog-skeletons.test.tsx`, `tests/hive-feedback-set.test.tsx`,
`tests/docs-links.test.ts`, `tests/CatalogImportQualityStep.test.tsx`, `tests/conversion-preview-dialog.test.tsx`).
