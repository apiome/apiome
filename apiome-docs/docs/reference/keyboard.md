---
title: "Keyboard"
description: "The keyboard path for every primary task, and the shortcut reference."
sidebar_position: 7
tags: [accessibility]
---

Every primary task in Apiome can be done without a mouse. This page lists the keyboard path
for each one, then the full shortcut reference. On Windows and Linux, read `⌘` as `Ctrl`.

The same reference is in the app: press **`?`** anywhere outside a text field, or open
**Preferences → Shortcuts**.

> These paths are checked in CI by the accessibility gate (`apiome-ui/e2e/a11y/`): every page
> can be walked with Tab without getting stuck, and every drawer, dialog and the command
> palette keeps focus inside while open and hands it back to the control that opened it when
> closed. See [Accessibility](./accessibility.md).

## Moving around any page

| To… | Press |
|---|---|
| Skip the sidebar and land on the page | `Tab` once from the top of the page, then `↵` on **Skip to content** |
| Move to the next / previous control | `Tab` / `Shift`+`Tab` |
| Press a button or follow a link | `↵` (buttons also take `Space`) |
| Switch a switch, tick a checkbox | `Space` |
| Move inside a set of options (view switch, tabs, radio group) | `←` `→` (or `↑` `↓`), `Home`, `End` |
| Close whatever is in front (pane, dialog, menu, palette) | `Esc` — focus goes back to what opened it |

## Primary tasks

### Sign in (and two-factor)
1. On `/login`, `Tab` to **Continue with GitHub** / **Continue with GitLab** and press `↵`, or
   `Tab` to **or use your email**, press `↵`, then fill **Email** and **Password** and press `↵`.
2. On the two-factor screen, type the six-digit code (focus starts in the field) and press `↵`.
   When both an authenticator app and an emailed code are offered, `Tab` to the method switch
   and use `←` `→` to change method.

### Find anything — the command palette
1. Press **`⌘ K`** (works even while typing in a field), or **`/`** outside a field.
2. Type to filter; the number of matches is announced.
3. `↑` `↓` to choose, `↵` to go. Type `>` first, or press `Tab`, to see actions only.
4. `Esc` closes it and returns focus where you were.

### Go to a section
Press **`G`** then a letter, outside a text field: **`G then H`** Home, **`G then P`** Projects,
**`G then C`** Catalog, **`G then L`** Lint posture, **`G then M`** Members. Or `Tab` into the
sidebar and press `↵` on a destination. **`⌘ \`** collapses or expands the sidebar.

### Switch workspace
`Tab` to the workspace row at the top of the sidebar, press `↵`, choose with `↑` `↓` and `↵`.
`Esc` closes the menu without switching.

### Browse, filter and act on a table (projects, catalog, repositories, versions…)
1. `Tab` to the search box and type, or press **`/`**.
2. `Tab` to the filter chips; `↵` or `Space` toggles one (its pressed state is announced).
3. `Tab` into the table: **`↑ ↓`** move between rows, **`↵`** opens the focused row,
   **`X`** selects it, **`.`** reaches the row's actions.
4. With rows selected, `Tab` to the bulk bar and press `↵` on an action; the result is announced.

### Create something
On a list page press **`N`** (outside a field) for a new item, or **`I`** to import; or open the
palette and choose the action. Focus moves into the dialog that opens; `Tab` through the
form and press `↵` on the primary button. `Esc` cancels and returns focus to where you were.

### Import a specification
Press **`I`** on a list page (or **`⌘ K`** → *Import a spec*). In the wizard, `Tab` between the
source options and use `↵` to choose; progress (“Import running: step 3 of 8”) is announced as
it changes, and the result is announced when the job finishes.

### Cut, publish or export a version
On a version, `Tab` to its actions and press `↵`. Dialogs keep focus inside until you confirm
(`↵` on the primary button) or cancel (`Esc`). A destructive confirmation focuses **Cancel**
first, so a reflexive `↵` never deletes anything.

### Edit roles in the permission matrix
On a role, `Tab` moves cell to cell; `Space` or `↵` toggles a permission (its pressed state is
announced). The save bar's state is announced as it changes.

### Manage members and API keys
`Tab` to a row's actions and press `↵` to open its drawer; the drawer keeps focus inside.
A new API key's secret is shown once with a **Copy** button you can reach with `Tab`.

### Set preferences
Press **`⌘ ,`** (or **`⌘ K`** → *Preferences*). Use `←` `→` between the tabs, `Tab` through the
controls (theme, density, font size, reduced motion), `Space` on switches. Changes apply
immediately; `Esc` closes the pane.

## Shortcut reference

Generated from the shortcut registry (`apiome-ui/lib/shortcuts.ts`); a test fails if a shortcut
is added there without a row here.

| Shortcut | Does | Where |
|---|---|---|
| `⌘ K` | Open the command palette | Anywhere, even while typing |
| `/` | Search or filter | Outside a text field |
| `⌘ ,` | Open preferences | Anywhere, even while typing |
| `⌘ \` | Collapse or expand the sidebar | Anywhere, even while typing |
| `?` | Show the keyboard shortcuts | Outside a text field |
| `Esc` | Close the pane, dialog or menu in front | Any overlay |
| `G then H` | Home | Outside a text field |
| `G then P` | Projects | Outside a text field |
| `G then C` | Catalog | Outside a text field |
| `G then L` | Lint posture | Outside a text field |
| `G then M` | Members | Outside a text field |
| `N` | New item | A list page |
| `I` | Import | A list page |
| `↑ ↓` | Move between rows | A focused table |
| `↵` | Open the focused row | A focused table |
| `X` | Select the focused row | A focused table |
| `.` | Reach the row’s actions | A focused table |
