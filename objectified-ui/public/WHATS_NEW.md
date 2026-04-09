# Objectified 04-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## UI:
- **Schema quality details (#2548):** **Studio header** Schema quality is **clickable** — opens a dialog with **letter grade (A–F)**, weighted **factor table**, and the same **score band guide** as import quality. **Schema Metrics** shows the same **overall schema quality** block (numeric score + letter + guide) above the per-metric controls
- **Studio schema quality (#245):** **Overall score (0–100)** in the Studio header — weighted blend of documentation, naming, structural load (inverted complexity), and canvas layout quality; updates live on the Canvas
- **Import quality score (#247):** **Weighted breakdown by category** — Design Quality (30 pts), Documentation (20), API Best Practices (25), Security (15), Performance (10); overall total out of 100 points with per-category progress and issues
- **Score bands (#248):** Shared **green / yellow / orange / red** tiers for 0–100 scores (90+ excellent down to 0–49 poor) on import **Quality Score** (overall + per-metric bars and guide), **Schema Metrics** docs/naming bars, and **Version scoring** radial gauges (documentation & naming; complexity still uses its own low/medium/high scale)
- **Version scoring:** New **Version scoring** panel (gauge icon) — pick a project version to see **per-schema** documentation, naming, and complexity scores with **animated radial gauges** (eased arc and value; respects reduced motion)
- **Version scoring (#244):** For the **version open in Studio**, those per-schema scores use the **live canvas graph** and update as you edit; choosing another version still loads scores from the server
- **Schema timeline:** **Compare schema scores** between any two versions (complexity, documentation, naming compliance, and size metrics with deltas)
- **Schema metrics & timeline:** Export **score reports as PDF** from the Schema Metrics panel (full breakdown) or the Schema timeline panel (per-version metrics history)
- **Property editor:** Optional **Owner** field (team or person responsible) stored as OpenAPI extension **`x-owner`** on the property schema; available in class property edit and project property library dialogs
- **Import from URL:** Source tabs switch between File, URL, Clipboard, Git, and SwaggerHub; URL step matches the import spec (auth, URL options including cache, **Test URL** and **Next** in the dialog footer)
- **Git import:** Load a GitHub repository by URL or `owner/repo`, pick a **branch** or **tag**, optionally type a **spec path** and open it, or browse the tree — directory listing uses the selected ref (same behavior when choosing a repo from the list)
- **Git import (#79):** **Save for later** — bookmark the linked account, repository, branch or tag, and optional spec path in this browser; reopen from **Saved for re-import** when you are ready to import again (e.g. after opening a PR branch)
- **OpenAPI import:** Import step shows the **Import Execution** layout — progress with schema index and ETA, per-schema live checklist (success / warning / in progress / pending), expandable import log, and technical summary in a collapsible section
- **What's New** dialog is centered on the viewport again (overlay renders outside the header so it is not offset downward)
- **Import classes:** duplicate-schema rows in the conflict report include **Schema diff** — side-by-side property diff (new / modified / removed), summary counts, and resolution choices (merge, replace, keep current, rename) before you apply
- **OpenAPI import:** one shared rule for “direct” schema properties — specs that mix top-level `properties` with inline `allOf` fragments now pick up both (aligned with the unified class importer)


## Projects:
- **Domain categories (#243):** Optional **domain category** per project (IoT, social, gaming, travel & hospitality, media & entertainment) — stored in project metadata, editable on create/edit, shown as a chip on the projects list
- **Industry domain patterns (#242):** Seven additional categories — e-commerce, healthcare, finance, SaaS, education, real estate, and logistics — each with representative entity names in the label (e.g. Product, Cart, Order, Payment, Shipping)
- **Quality score history (#246):** After a successful **Import specification** run, the OpenAPI **overall quality score** is saved in this browser per project; the projects table shows a **sparkline** and latest score, with a **trend chart** and history table in a detail dialog
- Added ability to start a new project from a template

## Groups:
- Studio **Groups** tab: each group row can expand or collapse; collapsed rows show the group name and node count, expanded rows list the classes in that group (click a class to focus it on the canvas when click-to-focus is enabled)
- Canvas group frames: set a custom container color with the palette popover (hex picker and `#RRGGBB` field); colors saved from the database display correctly
- Layout panel: group classes that share the same project tag name into separate canvas frames (multi-tagged classes are placed in one group via a clear A–Z rule)
- Canvas groups can be assigned project tags from the group style settings (saved with the group for future search and filtering)
- Fixed group tag picker and chips so tag names and colors show correctly (project tags use `name`/`color` from the database)

## Account:
- Removed verbose NextAuth debug logging from server and client auth flows (credentials, OAuth linking, JWT/session callbacks)
- Profile shows your last successful login date and time (stored when you sign in with email/password or OAuth)

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: April 7, 2026*

