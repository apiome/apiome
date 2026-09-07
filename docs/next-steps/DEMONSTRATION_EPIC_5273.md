# DEMONSTRATION — HIVE-EPIC-10: Quality, Accessibility & Cleanup

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [HIVE-EPIC-10 #5273](https://github.com/apiome/apiome/issues/5273) — **currently unmilestoned; pull into RC5** |
| Wave | Release gate — before [RC1-4.3](https://github.com/apiome/apiome/issues/3622) |
| Tickets | [10.2 #5338](https://github.com/apiome/apiome/issues/5338) · [10.3 #5339](https://github.com/apiome/apiome/issues/5339) · [10.4 #5340](https://github.com/apiome/apiome/issues/5340) · [10.5 #5341](https://github.com/apiome/apiome/issues/5341) · [10.6 #5342](https://github.com/apiome/apiome/issues/5342) |
| Builds on | every HIVE page epic (1–9) landed · HIVE-10.1 visual-parity harness ✅ |
| Runtime | ~11 min, plus 10 min prep |
| Audience | internal — the release gate review, and anyone who asks "is the redesign done?" |
| The one beat | **The redesign is not "the pages look new" — it's that every page holds up keyboard-only, in three themes, with the old code deleted.** |

> [HIVE-10.2](https://github.com/apiome/apiome/issues/5338) is the same work as
> [RC1-4.3](https://github.com/apiome/apiome/issues/3622)'s accessibility half. Do it once. This
> video is the evidence for both.

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The design system, as a route | Not a doc. The real components. | 2:00 |
| 2 | Run axe on a real page | Zero serious, zero critical — in three themes. | 2:30 |
| 3 | Put the mouse down | Every surface, keyboard only. | 3:00 |
| 4 | Turn motion off | Instant, with no layout jump. | 1:30 |
| 5 | The four states | Empty, loading, error, gated — on purpose. | 1:30 |
| 6 | Delete the old thing | The number that proves it landed. | 1:00 |

---

## PREP — before anyone is watching (~10 min)

**DO** — Start the stack. **Restart it after any CSS change** — a stale Turbopack `globals.css` is
the single most common way this demo shows the wrong thing.

```bash
yarn dev
```

**DO** — Have the theme switcher reachable, and know how to force high-contrast and
reduced-motion. You will switch themes four times; fumbling for the control each time is what
makes this video feel long.

**DO** — Pick **three routes** for Act 2 and Act 3 in advance: a dense table (Members or
Versions), a drawer-and-dialog surface (Preferences or Style Guides), and the command palette.
Those are where the redesign's new patterns concentrate, and where the risk actually is.

**DO** — Have the before/after bundle numbers from
[10.6](https://github.com/apiome/apiome/issues/5342) written down. Do not measure on camera.

**DO** — Full dry run with the browser's own screen reader turned on once, so you know what Act 3
sounds like before an audience hears it.

---

## ACT 1 — The design system, as a route (2:00)

**DO** — Go to <http://localhost:3000/design-system>.

**DO** — Scroll the primitives: buttons, fields, tables, badges, drawers, the palette. Each with
its variants and states.

**DO** — Switch theme, density and font scale **on the page itself**. Everything re-renders.

**SAY**

> This is not a document about the design system. These are the shipped components, rendered —
> so it cannot drift from what the product actually looks like, which is the failure mode of
> every design system page that is a separate HTML file.
>
> And there's a CI check: add a primitive without adding it here and the build fails. That's what
> keeps this page true in six months, when nobody remembers it exists.
>
> Theme, density and font scale switch live. Which is the honest way to review a design system —
> the components are only right if they're right in all of those at once.

---

## ACT 2 — Run axe on a real page (2:30)

**DO** — Open the dense table route. Run axe in the browser.

**DO** — *Pause on the result.* Zero serious. Zero critical.

**DO** — Switch to dark. Re-run. Switch to high-contrast. Re-run.

**DO** — Show the CI job that does this across every redesigned route.

**SAY**

> Zero serious and zero critical, and it holds in all three themes — which is a different claim
> from passing in light mode, because contrast failures are theme-specific and the dark palette
> is where they hide.
>
> WCAG 2.2 AA is the target, with AAA text contrast in high-contrast mode. And this isn't a
> one-time audit someone did with a browser extension; it's every redesigned route, in CI, in
> three themes.
>
> The token-level contrast check is worth a mention because it catches something axe can't: axe
> tests the pixels a page happens to render, but a token check tests every *combination* the
> tokens allow — including the pairs that only appear on a page you didn't open.

---

## ACT 3 — Put the mouse down (3:00)

*The act that finds real bugs. Rehearse it, then do it live anyway.*

**DO** — Physically move the mouse away from the desk. Say that you are doing so.

**DO** — Traverse the rail with the keyboard. Open the command palette with its chord. Navigate
results. Escape.

**DO** — Tab into the dense table. Sort a column. Open a row's actions.

**DO** — Open a drawer. Show focus moving into it, trapped inside, and returning to the trigger
on close. Do the same with a dialog.

**DO** — Tab through the permission matrix — the hardest surface — and show the tri-state control
being operable and announced.

**SAY**

> Rail, palette, table, drawer, dialog, matrix. No mouse.
>
> Focus goes into a drawer, stays in it, and comes back to the control that opened it. There is
> no point where focus vanishes to the top of the document, and no point where you cannot get out
> — a keyboard trap in a drawer isn't an inconvenience, it's the end of the session for someone
> who navigates this way.
>
> The permission matrix is the one I'd have bet against. A tri-state cell is hard to make
> operable and much harder to make *announce* correctly — it has to say what the mixed state
> means, not just that it's mixed.
>
> Save state, background jobs and bulk results announce through live regions too — so someone
> who can't see the toast still learns that the save happened.

---

## ACT 4 — Turn motion off (1:30)

**DO** — Open a drawer, a dialog and the palette at normal speed. Point out that nothing exceeds
260ms.

**DO** — Set the OS reduced-motion preference. Repeat all three. Instant, no layout jump.

**DO** — Show an animated progress indicator and the pulse dot both going static.

**SAY**

> Motion is doing a job here — the drawer slides from the right so you know where it came from,
> the palette rises so it reads as summoned rather than as a page change.
>
> With reduced motion it's instant, and — this is the part that's usually wrong — the layout
> doesn't jump. A lot of implementations set the duration to zero and leave a transform behind,
> so the element arrives in the wrong place. And the progress animation and the pulse dot stop
> too, because those are exactly the ones people forget.

---

## ACT 5 — The four states (1:30)

**DO** — Show one route in all four: empty, loading, error, and permission-gated.

**DO** — Read the empty state's copy aloud. Point at the honeycomb art.

**DO** — Trigger an error. Read it aloud: it says what happened *and* what to do.

**SAY**

> Every route, four states, reviewed against a checklist rather than by whoever happened to build
> the page.
>
> Titles are nouns, buttons are verbs, descriptions stay under fourteen words. No "No records
> found" — that sentence tells a new user nothing about what a record is or how to make one.
>
> And errors name a next action. "Something went wrong" is not an error message; it's an
> apology.

---

## ACT 6 — Delete the old thing (1:00)

**DO** — Show `globals.css`: the token layer and documented globals, and nothing else. No
`.theme-*` blocks, no legacy aliases.

**DO** — Show that nothing imports `dashboardScreenClasses`.

```bash
rg -c "dashboardScreenClasses" apiome-ui/src || echo "0 imports"
```

**DO** — Show the before/after bundle numbers from prep. Show the full suite green, with no
skipped tests added.

**SAY**

> This is the act that decides whether the redesign actually happened.
>
> A redesign that leaves the old system in place isn't finished — it's a second system, and
> every future change now has to be made twice by someone who has to work out which one is live.
>
> So the legacy theme blocks are gone, the old screen-class kit is gone and nothing imports it,
> the dead conversion scripts are gone, and the stale snapshots are gone. Suite green, no tests
> skipped to get there.
>
> The bundle number is the receipt.

---

## RESCUE — when it goes wrong on stage

**A route shows old styling**
Turbopack is serving a stale `globals.css`.
*On stage:* restart the dev server. This is common enough that you should expect it once.

**axe reports a serious violation**
*On stage:* do not hide it. Read it out, say whether it's known, and move on. A quality video
that suppresses a finding is worthless as evidence.

**Focus escapes a drawer**
A real bug, and exactly the sort this act exists to find.
*On stage:* note it and continue the traversal. File it as a gate item.

**Reduced motion leaves a layout jump**
*On stage:* show it, say it's a bug. It's a two-line fix and a good one to have found.

---

## IF ASKED

**"Is the admin console redesigned too?"**
No — [HIVE-EPIC-9 #5272](https://github.com/apiome/apiome/issues/5272) is separate and out of RC5
scope. The admin surfaces still carry the old chrome, deliberately.

**"Does this cover the browse app and the designer?"**
This epic covers `apiome-ui`. Browse and the designer have their own a11y coverage, and
[RC1-4.3](https://github.com/apiome/apiome/issues/3622) is where they get audited.

**"What's the performance story?"**
The other half of RC1-4.3 — latency budgets for the spine endpoints under load. Not this video.

---

## Reference

| Surface | Where |
|---|---|
| Design system route | <http://localhost:3000/design-system> |
| Hive gallery | <http://localhost:3000/design-system/hive> |
| Command palette | <http://localhost:3000/design-system/command-palette> |
| Members (dense table) | <http://localhost:3000/ade/dashboard/members> |
| Design language | `docs/mockups/DESIGN.md` §9 (a11y), §3.4 (motion), §10 (voice) |
| Plan | `private-suite/docs/roadmaps/ROADMAP_APIOME_UI_VISUAL_REDESIGN.md` |
