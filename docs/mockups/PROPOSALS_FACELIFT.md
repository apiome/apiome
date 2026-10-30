# Apiome “Hive” — round-3 proposals: the facelift

> **Status:** proposal. Reviewed 2026-10-30 against `apiome-ui` 0.550.27 (the HIVE-11/12/13
> “quiet pass” shipped; HIVE-EPIC-9 admin console open). Every proposal below is one of twelve
> **ideas**, each a token swap or a markup variant that the mockups gate on
> `<html data-fx="…">` (`assets/facelift.css`, `assets/facelift.js`). One mockup per screen
> renders both the shipped look (`?fx=none`) and the proposal (`?fx=all`, or a list such as
> `?fx=rail,hex,type`). **Open `proposals/facelift-compare.html`** to see any screen before /
> after under a slider and switch each idea on and off live. Nothing here changes routes, data
> or permissions; it is chrome, surfaces, type, colour and the shape of a few empty panes.

## 0. TL;DR

The Hive language is deliberately calm, and the quiet pass then removed stat strips and
banners for density. Both were right, and together they produced a UI where **every page is
the same shape** — breadcrumb → 24 px title → one line → white bordered card → chip row →
table — and nobody *wants* to open it:

| # | Finding | Where it shows |
| --- | --- | --- |
| 1 | **Brand lives only on the launcher and login.** The bee, the honeycomb and the honey/azure glows vanish inside the app; “apiome” is a 14 px word in the rail corner. | every `/ade/dashboard/**` page |
| 2 | **Everything is a 1 px-bordered white rectangle.** Cards, tables, stat tiles, filter bars, side panels. Nothing sits above or below anything else. | every page |
| 3 | **One typeface, two weights, one title size.** 24 px/600 Inter for titles, the same face at 32 px for numbers. | every page |
| 4 | **Colour only in badges.** Format colours exist (GraphQL rose, Protobuf azure, AsyncAPI violet…) but only as 22 px pills. | Catalog, Projects, Versions |
| 5 | **Big voids.** The Changes tab is one sentence in a viewport of white; export targets are large blank boxes with a lone icon; the catalog item has a 150 px empty band. | Versions → Changes, Export studio, Catalog item |
| 6 | **The admin console is a different product** — indigo sidebar, pink icon chips, placeholder “+12 %” stats. | `/admin/**` (HIVE-EPIC-9 #5272 open) |
| 7 | **Nine themes, seven of them neutrals-only**, dilute the brand. | Preferences |
| 8 | **The UI snaps.** 17 keyframes exist; no page enters, no card lifts, nothing follows the pointer. | every page |

## 1. How this was reviewed

* The shipped pages were read from the docs screenshots (`apiome-docs/static/img/screens/*.{light,dark}.png`,
  1440 × 900, real component output) and the shell from `apiome-ui/src/app/components/shell/*`,
  `globals.css` tokens and `DESIGN.md`; the quiet-pass tickets (#5594–#5617) were checked for state.
* Each idea was then built as an overlay on the **existing mockups** — the round-2 proposals are the
  authority for Versions and Catalog, `home/overview.html`, `sources/catalog-item.html`,
  `ship/export-studio.html` and `admin/overview.html` for the rest — so the “before” side of every
  comparison is the shipped design, not a redraw.

## 2. The twelve ideas

| Idea (`data-fx` token) | What changes | Where to look |
| --- | --- | --- |
| **rail** — navy rail | The rail is the mark’s navy (`--brand-navy`) with white type, a honey active marker and the bee in a honey hex; content stays on warm paper. Admin gets a rose cast. Dark themes keep a navy tint. | every screen |
| **hex** — honeycomb in the data | Item avatars (`data-hex`) are hexes filled with the format colour; card and section icons are hex tiles; a faint hex cell sits behind a card’s corner. People stay round. | Home, Catalog, Catalog item, Versions |
| **type** — display voice | Manrope 700/800, tight tracking, for page titles (28 px), greetings, section titles, dialog titles and numbers (tabular). Inter stays for everything else. | every screen |
| **layers** — surfaces, not borders | Three levels: canvas → raised card (soft shadow, no ring) → inset well (`data-well`, `.card--flat`). Toolbars fold into a tinted band inside the card; stats become separate tiles; the header loses its hairline. | every screen |
| **color** — format & status colour | A 3 px format rule on rows and cards; azure selection (rule + 6 % fill); tinted attention panels; a hero band on Home; an identity wash on detail headers in the item’s format colour; azure tab underline. | Home, Catalog, Versions, Catalog item |
| **viz** — numbers as measurements | Sparklines under the stats that have a history, a ring for “5 of 14”, deltas with their period. | Home |
| **timeline** — the Timeline is a timeline | A spine with a node per revision (draft hollow, published green, deprecated orange + sunset, archived grey, beta azure), the HEAD node in honey, sunset flags, the changelog as the body; a Timeline / Table segment keeps the table. | Versions |
| **voids** — fill the voids | Empty panes name the object, say why, offer a next step and the art in the format colour; export targets are compact 4-up tiles with a three-segment fidelity meter and the reason; the catalog item’s dead band goes. | Versions → Changes, Export studio, Catalog item |
| **forms** — designed forms | Sections, labels with hints, side-by-side fields, editor panes with line numbers for JSON, disclosure for advanced rules, actions in the footer. | Mock scenarios |
| **motion** — motion that explains | Content rises in with a stagger (420 ms), cards lift 2 px, the rail pill follows the pointer, numbers count up once, skeletons shimmer. Honours Reduce motion and `prefers-reduced-motion`. | every screen |
| **admin** — admin on the shell | The console on the Hive shell with the rose rail (HIVE-9.2): real numbers or none, approvals and signups where the banner was. | Admin |
| **themes** — signature Dark | Dark becomes navy-black surfaces with a honey primary and azure links; the theme grid shows four and folds the other five under “More themes”. | Preferences; any screen in Dark |

### Tokens and rules the ideas add (`assets/facelift.css`)

* `--font-display` (Manrope) · `--shadow-card`, `--shadow-card-hover` · `--fmtc-*` solid format colours and
  `[data-format] { --fmtc }` · the signature Dark block under `html[data-theme="dark"][data-fx~="themes"]`.
* Structural variants in page markup: `[data-fx-before="id"]` / `[data-fx-after="id"]` (one shown),
  `[data-fx-only="id"]` / `[data-fx-not="id"]` (small extras).
* Honey stays brand-only (DESIGN.md §2): the active rail marker, the HEAD node, the primary button in
  Dark. Never a warning.

## 3. Screens

| Mockup | Route | Ideas it demonstrates |
| --- | --- | --- |
| `proposals/facelift-compare.html` | — (viewer) | all, live |
| `proposals/facelift-home.html` | `/ade/dashboard` | rail · hex · type · layers · color · viz · motion · themes |
| `proposals/facelift-versions.html` | `/ade/dashboard/versions` | rail · hex · type · layers · color · timeline · motion |
| `proposals/facelift-versions-changes.html` | `…/versions?tab=changes` | voids (+ rail · type · layers) |
| `proposals/facelift-catalog.html` | `/ade/dashboard/catalog` | hex · color · layers (+ rail · type · motion) |
| `proposals/facelift-catalog-item.html` | `/ade/dashboard/catalog/{id}` | hex · color · layers · voids |
| `proposals/facelift-export-studio.html` | `/ade/dashboard/export/studio` | voids · hex · layers |
| `proposals/facelift-mock-scenarios.html` | Versions → Mock → Scenarios | forms · layers · type |
| `proposals/facelift-admin.html` | `/admin/dashboard` | admin · rail · hex · layers |
| `proposals/facelift-themes.html` | ⌘, → Appearance | themes · layers |

Every mockup carries **Notes** (mock bar, bottom right): the ideas it shows, **Keeps (1:1)**,
**States** and, for list pages, the first-row **Budget** against HIVE-13.3.

## 4. Suggested order

1. **rail + hex + type** — token and avatar work; the whole app looks different in a week.
2. **layers + color** — the surface system and the format colour.
3. **timeline + viz** — Versions and Home.
4. **voids + forms** — the empty panes, the export tiles, the dialogs.
5. **motion** — one pass, all tokenised, behind the Reduce motion switch.
6. **admin + themes** — HIVE-EPIC-9 is already ticketed; the theme trim is small.

## 5. Constraints kept

* The quiet-pass first-row budgets (HIVE-13.3, `e2e/visual/routes.ts`) hold: no idea adds standing chrome
  to a list page. The hero band is Home and the launcher only (+14 px on Home).
* Honey never means warning. Every colour is a token; Dark and High contrast still pass (High contrast
  ignores the shadow and signature tokens).
* Nothing is removed: the table stays behind the Timeline segment, the five extra themes stay one click
  away, every field of the scenarios dialog is still there.

## 6. DESIGN.md amendments these imply

§2 (honey as the Dark primary; hexagons for item avatars) · §3.1 (display face, layered shadows,
solid format colours) · §4 (the signature Dark; four themes shown) · §5.2 (navy rail) ·
§7 (forms: label, editor pane, footer actions) · §8 (empty-state rule; the timeline list pattern).

## 7. Tickets

Not ticketed yet. The natural split is one epic per numbered step in §4 (six epics), each citing
its mockups and the sections above; the viewer link with `#screen=…&fx=…` goes in each ticket.
