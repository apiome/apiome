# Versioning Roadmap

This represents the different versions of the Apiome specification and their current status.

## Schema Versioning

### Version Control 📋 PARTIALLY COMPLETED
- ✅ Full version history
- ✅ Compare any two versions
- ✅ Visual diff with highlights
- ✅ Branch and merge workflows (named branch tips; merge preview/apply with **merge-base (LCA)** and three-way OpenAPI merge in REST — #738)
- ✅ Tag versions (v1.0, stable, beta) — #501
- ✅ Version notes and changelogs (#502)
- ✅ Fork versions for experiments (#503) — cross-project copy from a source revision with `forkedFromRevisionId` / optional `upstreamProjectId`; distinct from **named branches** within the same project (#500)
- ✅ Protected versions (branch/tag/revision policy; tenant-admin locks; audit trail) — #504
- ✅ Show branches when creating copies of schemas (#505)

### Migration Tools 📋 PLANNED
- ✅ Generate migration guides (#747) — **ADE → Versions → Compare → Migration guide** tab: ordered steps for breaking deltas, revision-pair metadata, links to **#746** / **#506**; copy, append to compare-to changelog, **Markdown** + **PDF** export; ties to **#502** changelog `breaking:` hints
- 📋 Data migration scripts
- ✅ Backward compatibility checker (#506) — REST `POST /v1/versions/{tenant}/{projectId}/compatibility`; merge dialog runs target-tip vs source-tip check; optional `compatGateOnMerge` in project metadata
- ✅ Deprecation warnings (#507) — `versions.metadata` (`deprecated`, `deprecationMessage`, `successorRevisionId`, `sunsetDate`); compat API `deprecationWarnings` + optional `policy.http409WhenDeprecatedRevision`; project `failCiOnDeprecatedRevision`; OpenAPI `info.x-apiome-revision-deprecation`; Studio & migration banners
- ✅ Sunset timeline (#508) — REST `GET /v1/versions/{tenant}/sunset-timeline` (optional `projectId`); ADE **Sunset timeline** page + nav; rows include **timelineStatus** (announced / imminent / past), **lifecyclePhase** (deprecated vs sunset reached), and **#507**-shaped **deprecationWarnings**; optional CSV export

### Version Management 📋 PLANNED

**Advanced Versioning** ✅ PARTIALLY IMPLEMENTED
- **Version Branches**: 📋 Create branches for experimental features
- ✅ **Version Merging** (#738): REST three-way merge + merge-base; Studio proxies to REST
- ✅ **Lifecycle version tags** (#739): governance labels (`stable` / `beta` / `deprecated` / `archived`) in `versions.metadata.lifecycle`, list filter, Studio badges; distinct from **git-like release tags** (#501)
- ✅ **Version Comparison**:
  - ✅ Side-by-side diff view
  - ✅ Highlight added/removed/changed classes (#740 class list; #741 property drill-down)
  - ✅ Property-level changes (#741)
  - 📋 Visual canvas comparison
- **Version History Graph**:
  - ✅ Visual DAG of version history (#743) — parent + merge edges, zoom/pan, compare/view from nodes
  - ✅ Show branches and merges (#744) — left-to-right **lanes**, **branch tips** vs **merge commits**, **branch filter** (ancestor union keeps merges readable)
  - ✅ Click to switch versions
- **Version Rollback**:
  - ✅ Rollback to any previous version (revert-style new revision) — **#745**
  - ✅ Create new version from old version
  - ✅ Undo version publish
- **Version Notes**: 
  - ✅ Release notes per version
  - ✅ What's new highlights
  - ✅ Breaking changes documentation
  - ✅ Migration guide (#747)
- **Version Deprecation**:
  - ✅ Mark versions as deprecated
  - ✅ Set sunset dates (#748) — `versions.metadata.sunsetAt` (UTC ISO), validation vs `deprecatedAt`, `successorRevisionId` required when sunset is set; ADE Edit Version + tenant-admin metadata on published
  - ✅ Redirect to newer versions (#749) — `GET /v1/versions/{tenant}/{project}/{revisionId}` and `.../by-version/{version}` with `successorResolution=none|resolve|redirect`; optional `auditSuccessorResolution`; protected branch/tag tips block following (#504); portal proxy forwards query + `X-Apiome-*` headers
  - ✅ Deprecation warnings in API
- **Version Copy**: ✅ IMPLEMENTED
  - ✅ Copy classes and properties from existing version
  - ✅ Create new version based on previous version

---

# Completed

- **#749** — **Successor resolution / redirect:** REST **GET** revision (by id or `by-version`) supports **`successorResolution`** (`none` default, `resolve` returns final revision + **`X-Apiome-*`** headers, `redirect` → **307**); optional **`auditSuccessorResolution`** → **`version.successor_resolution`** audit; **#504** protected branch tips / protected tags block chaining off that anchor; cycles **409** `SUCCESSOR_CYCLE`. Portal **`/api/versions/[id]`** forwards query params, maps REST **307** to app URL, passes through **`X-Apiome-*`**
- **#747** — **Migration guide from compare:** deterministic Markdown (**Migration guide** tab) with **ordered steps** per breaking change, **revision pair** ids + template version, **#746** / **#506** cross-links, optional **#502** changelog `breaking:` notes; **Copy**, **append to compare-to changelog**, **Download Markdown**, **Download PDF**; deprecation warnings (#507) point at the **#747** tracker URL
- **#746** — **Breaking changes doc from diff:** deterministic Markdown (**Breaking** / **Additions** / **Other**) from schema-aware `compareSchemas` output, stable `components.schemas…` identifiers, template version in header; **ADE → Versions → Compare → Breaking doc** tab with copy and **append to compare-to changelog** (opens Edit Version)
- **#745** — **Version rollback (revert-style):** **REST** `POST .../version-branches/rollback-preview` and `POST .../rollback` — new head revision with **content** from a **prior ancestor** revision, **`parent_version_id`** = prior tip, **`metadata.rollback`** lineage; **#506**-style OpenAPI compare (tip → target) + optional **`compatGateOnRollback`**; **version.rollback** audit; **ADE → Versions** row action with preview / confirm / diff summary
- **#744** — **ADE → Versions → Revision history graph (branches & merges)**: **Left-to-right** layered layout (**lanes**); **merge commits** (violet, dashed merge-parent edge) vs **branch tips** (emerald marker, **Tip:** labels from named branches, hover); **branch toggles** filter by **ancestor union** from each selected tip so **merge readability** is preserved; shared **#743** panel/DAG module.
- **#743** — **ADE → Versions → Revision history graph**: interactive **DAG** from `parent_version_id` / `merge_parent_version_id` (React Flow: zoom/pan, minimap); **compare** to primary parent or **view spec** (Ctrl/Cmd-click); **Load older** for large histories; merge nodes show **two parents** (dashed merge edge).
- **#741** — **Property-level diff** in **Schema Changes**: readable lines per property/schema (`property name: field old → new`), expanded OpenAPI compare (**default**, **nullable**, **readOnly** / **writeOnly**, **deprecated**, **example**, **title**, **multipleOf**, **uniqueItems**, **exclusiveMin/Max**, etc.), sorted drill lists, **performance** cap with **show all** for huge classes; **Merge branches** preview shows **conflict paths grouped by class** (aligned with `schemas.*` IDs).
- **#742** — **ADE → Versions → Compare → Canvas**: **visual** diagram compare for saved Studio layouts (default snapshot, else effective named layout) with **split** or **stacked overlay**, legend (**added / removed / moved / unchanged**), **lazy-loaded** when the tab opens (orthogonal to OpenAPI diff **#740** / **#741**).
- **#740** — Version compare **Schema Changes**: **class-level** structural diff (stable OpenAPI schema IDs), git-style **+/−/~** highlights, search and **virtualized** list for large schemas, **property drill-down** per class, **Copy class stat** export text.
- **#738** — Version merging (Git-style merge-base, three-way OpenAPI schema merge, merge revision with two parents, `baseRevisionId` lock; optional `compatGateOnMerge`).
