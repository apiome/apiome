# Objectified 04-2026

We continue to improve the platform based on your feedback with improvements and new features!

---

## UI:
- **Version merge (#738):** Branch merge **preview** and **apply** run through **objectified-rest** — **merge-base (LCA)** plus **three-way** `components.schemas` merge, structured conflict paths, **two parents** on the merge revision, **`baseRevisionId`** optimistic lock on the target tip; Studio API routes proxy to REST
- **Canvas ↔ Code (#2595):** Switching to **Code** now **synchronously hides group floating toolbars** (including hover/settings/export), **clears flow selection**, and **blocks sidebar group delete row actions** while the Code tab is active so nothing in that stack can take a stray click during the transition
- **Studio Code / GraphQL (#147):** GraphQL SDL in the Code tab is generated from a **Handlebars template** (`templates/graphql/graphql-schema.hbs`) instead of inlined string building, aligned with OpenAPI and Arazzo; template loader init is synchronous so tooling can import it safely
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

## Versioning
- **Lifecycle tags (#739):** Revisions support governance labels **Stable / Beta / Deprecated / Archived** (`metadata.lifecycle`); **Versions** list has a **lifecycle filter** and badges; **deprecated** aligns with **#507**. **Archived** revisions are read-only except tenant admins (lifecycle / revision lock). Distinct from **git-like release tags** (#501)
- **Sunset timeline (#508):** **REST** `GET /v1/versions/{tenant}/sunset-timeline` aggregates **deprecated** and **sunset** revisions across projects (optional **`projectId`** filter); **ADE → Sunset timeline** lists **timeline** status (announced / imminent within 30 days / past), **lifecycle** (deprecated vs sunset reached), **#507** warning text, and **CSV export**
- **Deprecation warnings (#507):** **Revision-level** deprecation in **`versions.metadata`** (`deprecated`, `deprecationMessage`, `successorRevisionId`, `sunsetDate`); **compatibility** responses include **`deprecationWarnings`** (with migration guide **#747**), optional **`409`** via **`policy.http409WhenDeprecatedRevision`**, and project **`failCiOnDeprecatedRevision`** for CI-style **blocked** flags; exported OpenAPI includes **`info.x-objectified-revision-deprecation`**; **Studio** and **Migration** headers show amber **banners** when the selected revision(s) are deprecated
- **Backward compatibility (#506):** **REST** `POST /v1/versions/{tenant}/{project}/compatibility` compares two **revision IDs** (generated OpenAPI) and returns **safe / breaking / unknown** findings, deterministic **reportFingerprint**, link to **#746** when breaking, optional **409** via `policy.http409WhenBreaking`; **ADE → Versions → Merge branches** runs the check after merge preview (target tip vs source tip). Optional project metadata **`compatGateOnMerge`** sets **tenantCompatGateActive** and blocks apply when the pair is not fully safe
- **Create version from copy (#505):** **ADE → Versions → Create new version** shows **branch context** when copying from a revision—**branch tip picker** when multiple named branches exist, **breadcrumb + compact ASCII lineage** from parent links, **merge** called out in text (not color-only), and **screen-reader summary**; branch list refresh and loading/error states when metadata fails to load
- **Protected versions (#504):** **Tenant-admin policy** on **tags**, **named branches**, and **revisions** — `protected` / `revision_locked` columns, **403/409**-style errors from API routes, **version_protection_audit** for denials and policy changes; **ADE → Versions** shows **Protect / Unprotect**, **Lock revision**, and shields on locked rows
- **Fork versions (#503):** **Fork to another project** from the version row menu — copies the source revision’s schema into a **different** project with stored lineage (`forkedFromRevisionId`, optional upstream project for merge-back); **REST** `POST /v1/versions/{tenant}/{projectId}/fork`; **not** the same as a **named branch** in the same project (#500)
- **Revision notes & changelogs (#502):** **REST** returns `shortMessage` / `changelog` (aliases for `description` / `change_log`) with **tenant-default size limits**; **publish** applies last-minute notes in one transaction; **ADE → Versions** uses **Revision note** / **Changelog** labels, validation before create/edit/publish, **compare** shows both sides’ notes and **breaking:** bullets for downstream docs
- **Version tags (#501):** **Git-like tags** on schema revisions — create/list/delete from **ADE → Versions** (optional message, channel, **immutable** lock); **REST** `GET/POST /v1/version-tags/{tenant}/{project}` and `PATCH/DELETE .../{tag_id}`; compare dialog can **set base/compare from a tag**; history table filters by tag
- **Versions (#500):** **Named branches** (tip = version snapshot), **merge preview** and **apply merge** with optimistic `baseRevisionId` / target tip; merge revisions record **two parent** version ids; conflict banner when overlapping schema paths differ (merge-base LCA planned in #2593)

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
- **Free OAuth sign-up (#66):** On the login page, choose **Create one**, then **Continue with GitHub** or **Continue with GitLab** to complete OAuth, enter your name and first organization (slug), and receive a **free plan** (1 organization, 1 project, up to 3 versions) with automatic sign-in
- Removed verbose NextAuth debug logging from server and client auth flows (credentials, OAuth linking, JWT/session callbacks)
- Profile shows your last successful login date and time (stored when you sign in with email/password or OAuth)

View our YouTube channel [here](https://www.youtube.com/@objectifieddev) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Objectified better.

---

**Thank you for using Objectified!**

*Last updated: April 8, 2026*

