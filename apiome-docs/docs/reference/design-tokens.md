---
title: "Hive design tokens"
description: "The named tokens the Hive design system builds with, starting with stacking."
sidebar_position: 13
tags: [content, reference]
---

The Hive design system names its values instead of repeating them. Every token lives in one
file, `apiome-ui/src/app/globals.css`, and Studio uses the same stylesheet, so a token means the
same thing in the web app and in Studio. The design language behind the tokens is
`docs/mockups/DESIGN.md`. Use the [design-system gallery](#where-to-see-them) to see each one in
place.

## Design tokens

| Family | Tokens | Spent through |
| --- | --- | --- |
| Colour | `--color-*` (surfaces, ink, lines, accents, status) | `bg-surface`, `text-fg`, `border-border` … |
| Type | `--text-*`, `--font-sans`, `--font-mono` | `text-sm`, `font-mono` … |
| Radius and elevation | `--radius-*`, `--shadow-*` | `rounded-md`, `shadow-lg` … |
| Motion | `--dur-*`, `--ease-*` | `transition`, `duration-*` |
| Density and layout | `--control-h`, `--page-pad`, `--rail-w` … | `h-control`, `p-page` … |
| Stacking | `--z-*` | `z-chrome`, `z-modal` … (see below) |

### Stacking (z-index)

Which element paints over which is decided by one scale of ten named steps. Nothing in the
product writes a z-index number; it names a step. SUX-1.1 (apiome#6748) introduced the scale.

| Step | Value | Utility | Used for |
| --- | --- | --- | --- |
| `--z-base` | 0 | `z-base` | The page's own content |
| `--z-raised` | 10 | `z-raised` | One item lifted over its neighbours: a card's buttons over its link, a table's header row |
| `--z-sticky` | 100 | `z-sticky` | Sticky page headers, save bars, Studio's project and version toolbar |
| `--z-chrome` | 200 | `z-chrome` | Global headers and the navigation rail |
| `--z-floating` | 300 | `z-floating` | Canvas toolbars, docked panels, notices that float over the chrome |
| `--z-overlay` | 1000 | `z-overlay` | The dimmed backdrop behind a dialog or drawer |
| `--z-modal` | 1010 | `z-modal` | Dialogs, drawers and the command palette |
| `--z-popover` | 1020 | `z-popover` | Selects, menus and tooltips, including those opened inside a dialog |
| `--z-toast` | 1030 | `z-toast` | Toasts |
| `--z-alert` | 1040 | `z-alert` | Confirm and alert dialogs, backdrop and surface |

```text
alert 1040 ─ toast 1030 ─ popover 1020 ─ modal 1010 ─ overlay 1000
───────────────────────────────────────────────────────────────────
floating 300 ─ chrome 200 ─ sticky 100 ─ raised 10 ─ base 0
```

The two rows never mix. Every page step is below every overlay step, so opening a dialog or
drawer dims the whole screen, global header included. A popover is above a dialog, so a select
opened inside a dialog, or inside a dialog opened from a drawer, shows in full above both.

**In a component**, use the utility: `className="fixed inset-0 z-overlay"`. Passing a different
`z-*` class to a Hive primitive replaces its step, because `cn()` treats the step utilities and
Tailwind's own `z-*` as the same property.

**In a stylesheet**, use the token: `z-index: var(--z-sticky);`. For "one step behind",
write `calc(var(--z-base) - 1)`.

**From script**, for an inline `style` or a third-party component, use `zLayer('toast')` from
`apiome-ui/lib/zLayers.ts`. It returns `var(--z-toast)`. That file lists the steps in order,
and a unit test fails if it and `globals.css` disagree.

Inside an element that already stacks (anything with its own z-index), a step only orders that
element's children. A menu inside the header can never rise above a dialog, however high its
step.

## Where to see them

The design-system gallery is the `/design-system` route of `apiome-ui`. It needs no sign-in.
**Overlays & banners** has **Open layered drawer**, which opens a drawer, a dialog inside it and
a select inside that. It is the case the stacking scale exists for, and
`apiome-ui/e2e/hive-z-index-scale.spec.ts` checks it in a browser.
