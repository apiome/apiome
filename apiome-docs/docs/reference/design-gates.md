---
title: "Design gates"
description: "The tests that keep honey, headers, banners and the first row in line."
sidebar_position: 13.5
tags: [content, reference]
---

The quiet pass (RC6) made `apiome-ui` calmer. Honey is back to being a brand colour, page headers
are short, a page has one banner, and the data starts near the top of the screen. The **design
gates** are the tests that keep it that way. Each one turns a rule in `docs/mockups/DESIGN.md`
into a check that fails a pull request. Epic 13 (#5596) built them, together with the design
docs they enforce.

Use this page to find out which gate failed your change, what rule it holds you to, and where
the full detail lives.

## The gates at a glance

| Gate | Rule (DESIGN.md) | Test | Fails when | Detail |
| --- | --- | --- | --- | --- |
| **Honey** | Honey is for brand moments only, never a feature-flag or filter colour (§2) | `tests/hive-design-tokens.test.ts` | A file or `globals.css` rule outside the allow-list uses a honey token or utility | [Below](#honey-only-in-brand-moments) |
| **Header action cap** | One primary, at most two secondaries and one ⋯ menu; no picker in the header (§1.2, §5.3) | `tests/page-header-gate.test.tsx` | A `PageHeader` has too many `Button`s, or a `select` in its actions | [Page headers and unavailable controls](./content-voice.md#page-headers-and-unavailable-controls) |
| **One banner** | At most one `Alert` between the header and the body; several statuses become a `StatusStrip` (§5.4) | `tests/page-header-gate.test.tsx` | Two or more banners stack under a header | [Several statuses on one page](./content-voice.md#several-statuses-on-one-page) |
| **No dead controls** | A control that cannot be used says why; "Coming soon" is never a button (§10) | `tests/page-header-gate.test.tsx`, `tests/copy-voice-gate.test.ts` | A button reads "Coming soon", or a new disabled button has no reason | [What enforces it](./content-voice.md#what-enforces-it) |
| **First-row budget** | The first row of data sits within a budget for the page kind at 1440 × 900 (§8) | `yarn test:e2e:visual` | The first data row starts below its budget | [The first-row budget](./visual-parity.md#the-first-row-budget) |

The honey gate and the page gates are Jest suites. They run in the unit-test step of the
**Apiome UI** workflow, and `yarn test` in `apiome-ui/` runs them locally. The first-row budget is
part of the visual-parity harness and runs in the **Apiome UI Visual Parity** workflow.

## Honey only in brand moments

Honey is Apiome's brand colour. DESIGN.md §2 spends it on brand ornament only:

- the mark and the auth and launcher brand canvas;
- the **new**, **starred**, **pinned** and **Preview** markers;
- the first-run checklist on Home, and empty-state art;
- the theme grid, the active rail marker and the **HEAD** node on the Versions timeline.

It is never a feature-flag or filter colour. A filter or a saved view is a neutral `.chip`, and a
feature-flagged item carries an outline `Badge`.

The gate reads every `.ts`, `.tsx` and `.css` file under `apiome-ui/src` and `apiome-ui/lib` and
finds each honey token (`--honey*`, `--color-honey*`, `--gradient-honey*`) and each Tailwind
utility built on one (`bg-honey`, `text-honey-fg`, `border-honey` …). Comments do not count.
Then it holds each use against an allow-list:

- **A component file** passes if the whole file is a brand surface.
- **A rule in `globals.css`** passes if that one rule is a brand role, or one of the rules that
  define the tokens and swap them per theme. `globals.css` holds every screen's styles, so the
  gate checks it rule by rule rather than as one file.
- **Pending** entries are honey uses that predate the gate. The list can only shrink: when an
  entry no longer uses honey, the test fails until you delete it.

When the gate fails, it names the file or rule and the token, for example
`.mcp-saved-chip: --honey-soft`. Use a neutral token instead. If the new use really is one of the
§2 brand roles, add it to the brand allow-list in `tests/hive-design-tokens.test.ts` with the role
as its reason.

## If a gate fails your change

1. Read the failure. Each gate names the page, file or rule and how far it is over.
2. Fix the page rather than the gate: move an extra header action into the ⋯ menu, fold a second
   banner into the `StatusStrip`, give a disabled button its reason, or move a toolbar or a stat
   strip out from above the data.
3. Use an allow-list entry only for a page that is not released yet, and give it a reason. Every
   allow-list in the gates is a ratchet: an entry that is no longer needed fails as stale.

## The design docs behind the gates

The gates check the rules in `docs/mockups/DESIGN.md`, and the visual-parity harness compares pages
against the mockups in `docs/mockups/`. The round-2 review (`docs/mockups/PROPOSALS.md`) measured
the problems, and the quiet pass fixed them. The rules from that review are now part of
DESIGN.md (§2, §5.2–§5.4, §8, §10, §12), and the page mockups draw the screens as shipped. The
four proposals stay under `docs/mockups/proposals/` as the record of the change.

## Related pages

- [Content and voice](./content-voice.md): the copy rules, the header and banner rules, and the
  copy gate.
- [Visual parity and first-row budgets](./visual-parity.md): the parity score, the budgets and
  allowances.
- [Hive design tokens](./design-tokens.mdx): the named tokens the gates expect you to use.
