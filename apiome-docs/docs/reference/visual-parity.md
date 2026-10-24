---
title: "Visual parity and first-row budgets"
description: "How redesigned pages are scored against the mockups, and the first-row budget."
sidebar_position: 11
tags: [content]
---

The visual-parity harness checks every redesigned `apiome-ui` page against its mockup in
`docs/mockups/`. It has two checks. The **parity score** measures whether the page uses the same
design tokens in the same places. The **first-row budget** measures how far down the page the
first row of data starts. HIVE-10.1 ([#5337](https://github.com/apiome/apiome/issues/5337))
built the harness, and HIVE-13.3 ([#5616](https://github.com/apiome/apiome/issues/5616)) added
the budget. Both run in the **Apiome UI Visual Parity** CI workflow, in the light and dark themes.

```bash
cd apiome-ui
yarn test:e2e:visual                 # every route, both themes
yarn test:e2e:visual -g catalog      # one route
```

The harness starts its own app on port 3300. It needs no REST API and no database.

## The first-row budget

[`PROPOSALS.md`](https://github.com/apiome/apiome/blob/main/docs/mockups/PROPOSALS.md) found that
stat strips, banners and extra toolbars were pushing data below the fold. At 1440 × 900 the first
row of data started 600–870 px down the page. The quiet pass (Epic 11) removed that clutter, and the
budget stops it from coming back. The harness mounts each page at 1440 × 900 (comfortable density,
`md` font scale) and reads where the page's first row of data starts:

| Page kind | Budget | Example |
| --- | ---: | --- |
| List page | **360 px** | Published (216 px), Catalog after HIVE-11.6 (344 px) |
| Detail page | **560 px** | Repository detail (443 px) |
| Versions | **700 px** | Versions keeps its status strip and artifacts card |

Analytics pages are **exempt**, because their figures and charts are the data. Forms and wizards
are exempt as well, because their controls come first by design. Every other page has a budget,
and a unit test fails if a route has neither a budget nor an exemption.

### Allowances

Some pages are over budget today because their quiet pass has not landed yet. Each one has an
**allowance**: a ceiling set just above today's measurement, plus the reason the page is over.
An allowance works like a ratchet:

- the first row can move up, but not below the ceiling;
- when the page comes back within budget, the check **fails** until you delete the allowance.
  That way an old allowance cannot hide a new regression.

### Reading the result

The report in `visual-parity-report/<theme>/index.html`, and the CI job summary, show a
**First row** column beside each route's parity score:

| Cell | Meaning |
| --- | --- |
| `344 / 360 px` | the row starts at 344 px; the budget is 360 px |
| `382 / 360 px (allowed 390)` | over budget, but inside its allowance |
| `no match / 360 px` | the selector matched nothing (this fails) |
| `—` | the route is exempt |

When a page goes over its budget, the test failure tells you how far:
`catalog first row: 609 px, 249 px over the 360 px budget — something new stands above the data`.

### Setting a budget for a page

When a redesigned page joins the harness, add a `firstRow` to its entry in
`apiome-ui/e2e/visual/routes.ts`:

1. Pick the page kind: `firstRowBudget('list')`, `firstRowBudget('detail')` or
   `firstRowBudget('versions')`. Budgets always come from this list; you cannot pick a custom number.
2. The default selector is the first `DataTable` body row (`.page-body tbody tr[data-row-id]`).
   If the page's data is something else, such as a card list or a chart, pass that selector as
   the second argument.
3. If the page is an analytics page or a form, add it to `FIRST_ROW_EXEMPT` instead.
4. Run `yarn test:e2e:visual -g <route id>`. If the page is over budget and the fix belongs to a
   later ticket, add an allowance as the third argument, with `ceilingPx` set to the next
   multiple of ten above the measurement and a `reason`.

### At size

The parity fixtures hold a handful of rows. A real workspace can have a thousand catalog items, and
a project can have hundreds of versions. RC6 checks both lists at that size:

- **Offset.** `e2e/visual/at-size.spec.ts` mounts the Catalog table with 1,000 items and the
  versions table with 300 revisions. Each must meet its route's budget above, allowance included.
  The Catalog cards with 1,000 items must put their first card within 4 px of where three items
  put it. The fixtures in `e2e/fixtures/hive-at-size/` are written by
  `AT_SIZE_FIXTURE_DUMP=1 npx jest tests/rc6-list-budgets -t fixture`.
- **Time.** `tests/rc6-list-budgets-catalog.test.tsx` and `tests/rc6-list-budgets-versions.test.tsx`
  render the real screens at that size in jsdom. Each screen must mount only one page (50 rows)
  and stay inside these ceilings on the CI runner, while other suites run in parallel:

  | Step | Ceiling (jsdom, CI) | Measured (jsdom, idle) |
  | --- | ---: | ---: |
  | First row of data | 3,000 ms | 150–330 ms (2.4–2.6 s before paging) |
  | A filter | 1,000 ms | 100–160 ms |
  | A re-sort | 1,000 ms | about 120 ms |

  jsdom does the same React work as a browser, without painting, and does it more slowly. So the
  browser time is lower than the jsdom time, inside the 200 ms target for a filter or a sort.

`apiome-ui/e2e/visual/README.md` has the full detail, including how the parity score is weighted.
