# Open Source Redesign: Canvas & Dashboard Roadmap

> Roadmap for redesigning the Objectified application into a community-maintained Open Source version. Scope: **canvas and dashboard only**. The UI uses **REST only** (no `lib/db/helper`); version edits are **local-first** (browser → commit → push); **pull/merge** with conflict resolution; versions stored **historically** for rollback, remove, and branch.
>
> **Last Updated**: February 28, 2026  
> **Version**: 1.0 – Canvas & Dashboard Open Source Redesign

---

## Design Principles

- **REST-only UI**: All data operations via REST (objectified-rest or equivalent); no direct DB or helper usage from UI.
- **OpenAPI 3.2.0 & JSON Schema 2020-12**: Full spec coverage for schema and property/class authoring.
- **Local-first version workflow**: Edits in memory/local storage → commit → push; pull/merge with visual conflict resolution.
- **Version history**: DB stores version history; support rollback, remove, and branch.

**Data model (in scope):** User, Tenant, User–Tenant, Tenant administrators, Project, Version (with history), Class, Property, Class–Property join; forms for properties and classes per OpenAPI 3.2.0 / JSON Schema 2020-12.

---

## 1. REST API Foundation

> **Section Status**: Implement in objectified-rest (or equivalent OSS service). No UI in these tickets.

### 1.1 Users, Tenants, and Auth

**Core data model & authentication**
- Implement REST routes for **users**: list (admin), get by id, create (signup), update, deactivate (no hard delete if audit needed).
- Implement **tenants**: list (for current user), get, create, update, delete; enforce slug uniqueness per tenant.
- Implement **user–tenant**: list members for a tenant, add member (by user id or email), remove member, optional role field.
- Implement **tenant administrators**: list, add, remove; only admins can manage tenant and members.
- **Auth**: Login (issue JWT); API key create/revoke per tenant; middleware that attaches `user_id` and `tenant_id` (when applicable) to requests. Support JWT in `Authorization: Bearer` and API key in `X-API-Key`.
- [DONE] **DB**: Tables/schema for users, tenants, user_tenants, tenant_administrators; migrations as needed.
- **Reference**: Extend `objectified-rest/src/app/auth.py` and add routes under `/v1/users`, `/v1/tenants`, `/v1/tenants/{id}/members`, `/v1/tenants/{id}/administrators`. Document in OpenAPI.

| Ticket | Feature Description |
|--------|---------------------|
| #13    | Create the scaffolding for the REST services, only the class representations in the #/definitions/schemas |
| #15    | Create user services |
| #16    | Create tenant services |
| #17    | Create user-tenant services |
| #18    | Create tenant administration services |
| #19    | Create authentication services |
| #20    | Create routes and document in OpenAPI Specification file |

---

### 1.2 Projects & Versions with History

**Projects and versioned schema with historical storage**
- **Projects**: Create, list by tenant, get, update, delete; tenant-scoped; creator tracking; slug/name uniqueness per tenant.
- **Versions**: Create (optional `source_version_id` for branch), list by project, get by id, update metadata (description, changelog), delete. Project-scoped.
- **Version history**: Store each committed version state (e.g. `version_snapshots` or `version_commits` table) with reference to classes/properties at that point. Support “list revisions for version” and “get version at revision”.
- **Publish**: Publish/unpublish/freeze-schema endpoints; only published versions visible for pull by others (define policy).
- [DONE] **DB**: projects table; versions table; version_history or version_snapshots table for rollback and branch.
- **Reference**: `objectified-rest/src/app/projects_routes.py`, `versions_routes.py`; add history tables and `/v1/versions/{id}/history`, get-by-revision.

**Enterprise and advanced (Projects)**
- **Project lifecycle**: Soft delete or archive projects (retain data for audit); restore archived project; project status (active, archived, locked).
- **Project metadata and governance**: Owner, team, or cost-center metadata; project tags/labels for filtering and catalog; optional project templates or blueprints for quick setup.
- **Quotas and limits**: Configurable per-tenant or per-project quotas (e.g. max versions per project, max classes per version) with clear errors and optional dashboard visibility.

**Enterprise and advanced (Versions)**
- **Version locking**: Lock version to prevent further edits (freeze); optional unlock by authorized role; lock state in version metadata.
- **Version tags and promotion**: Tags or labels on versions (e.g. `staging`, `production`, semantic version); list/filter by tag; optional promotion workflow (promote version to tag).
- **Version comparison**: REST endpoint to diff two versions (or two revisions) and return structural delta (classes/properties added, removed, changed) for review and compliance.

**Enterprise and advanced (Version history)**
- **Revision metadata**: Store author (user_id), optional commit message, and optional external id (e.g. CI run id, ticket id) per revision for audit and traceability.
- **History retention and export**: Optional retention policy (e.g. keep last N revisions or by age); export version history (or range) for compliance or backup; immutable append-only revisions where required.

**Enterprise and advanced (Publish)**
- **Publish channels or targets**: Publish to named targets (e.g. `dev`, `staging`, `production`); list what is published where; unpublish per target.
- **Publish artifacts and integrity**: Optional checksum or signed manifest for published schema; webhook or event on publish for downstream systems (API gateways, codegen, Backstage).

| Ticket | Feature Description |
|--------|---------------------|
| #22    | Create projects services |
| #23    | Create versions services |
| #24    | Create version history services |
| #25    | Create publish services |
| #26    | Modify REST services endpoints to match names |
|        | Add project soft delete/archive and restore with status (active, archived, locked) |
|        | Add project metadata (owner, team, tags/labels) and optional project templates or blueprints |
|        | Add per-tenant or per-project quotas (max versions, max classes) with enforcement and visibility |
|        | Add version locking (freeze edits) with optional unlock by role |
|        | Add version tags/labels and promotion workflow (e.g. staging, production) |
|        | Add version comparison/diff endpoint (structural delta between two versions or revisions) |
|        | Add revision metadata (author, commit message, optional CI/ticket id) and immutable append-only option |
|        | Add history retention policy and export for compliance or backup |
|        | Add publish channels/targets (e.g. dev, staging, production) and list-by-target |
|        | Add publish artifact integrity (checksum/signed manifest) and webhook or event on publish |

---

### 1.3 Classes, Properties, Class-Property (Ticket 3)

**Schema entities and bulk read for canvas**
- **Classes**: Create, list by version, get, update (metadata + `canvas_metadata`: position, dimensions, style, group), delete. Version-scoped.
- **Bulk**: Endpoint to get all classes for a version with properties (and tags if kept) in one response for canvas load.
- **Properties**: Create, list by project, get, update, delete; `data` JSON holds schema (OpenAPI/JSON Schema). Project-scoped (reusable library).
- **Class-property**: Add property to class, reorder, update overrides (e.g. required, description), remove; support `parent_id` for nested properties. Endpoints: add to class, update join row, remove from class, list by class.
- [DONE] **DB**: classes, properties, class_properties tables; indexes for version_id, project_id, class_id.
- **Reference**: `objectified-rest/src/app/classes_routes.py`, `properties_routes.py`, `get_classes_with_properties_and_tags_for_version` in database layer.

| Ticket | Feature Description |
|--------|---------------------|
| #27    | Create class services |
| #28    | Create bulk services |
| #29    | Create property services |
| #30    | Create class property services |
| #31    | Modify REST services endpoints to match names |

---

### 1.4 OpenAPI 3.2.0 & JSON Schema 2020-12 (Ticket 4)

**Validation, export, and import**
- **Validation**: On create/update of class or property, validate `schema`/`data` against OpenAPI 3.2.0 schema object and JSON Schema 2020-12; return 400 with error details if invalid.
- **Export**: Endpoints to export a version as OpenAPI 3.2.0 document and as JSON Schema 2020-12 document (single or multi-schema). Reuse/extend `openapi_generator` and `jsonschema_generator` to 3.2.0 and 2020-12.
- **Import**: Import OpenAPI 3.2.0 or JSON Schema 2020-12; create/update classes and properties; conflict handling can be deferred to merge (Ticket 5).
- **Docs**: Document which keywords and features are supported (full coverage statement and any exclusions).
- **Reference**: `objectified-ui/src/app/utils/openapi.ts`, `jsonschema.ts`; objectified-rest generators; `lib/db/import-helper.ts`, importers.

| Ticket | Feature Description |
|--------|---------------------|
| #32    | Create validation endpoint |
| #33    | Create export endpoints |
| #34    | Create import endpoints |
| #35    | Modify REST services endpoints to match names |

---

### 1.5 Version Commit, Push, Pull, Merge (Ticket 5)

**Git-like version workflow APIs**
- **Commit**: Endpoint that accepts full version payload (classes, properties, class_properties, canvas_metadata) and writes to DB and version history; returns new revision id.
- **Push**: Client sends committed state; server overwrites (or merges) working version and appends to history; returns success and revision id.
- **Pull**: Get version state (latest or by revision); optionally return “since revision” diff.
- **Merge**: Input base revision, “ours” state, “theirs” state (or server current). Output: merged state plus list of conflicts (e.g. class/property modified in both). Conflict entries: path, description, suggested resolution. Optional endpoint to submit resolution choices and return merged state.
- **DB**: Ensure version_history stores full or delta snapshots so pull and merge are implementable.
- **Reference**: New routes e.g. `POST /v1/versions/{id}/commit`, `POST /v1/versions/{id}/push`, `GET /v1/versions/{id}/pull`, `POST /v1/versions/{id}/merge`. Use `objectified-ui/src/app/utils/schema-merge.ts` and ClassImportDialog merge logic for conflict semantics.

| Ticket | Feature Description |
|--------|---------------------|
| #40    | Review DB for version history functionality |
| #36    | Create version commit endpoints |
| #37    | Create version push endpoints |
| #38    | Create version pull endpoints |
| #39    | Create version merge endpoints |
| #41    | Modify REST services endpoints to match names |

---

## 2 UI: REST-Only (No Helpers)

> **Section Status**: All canvas and dashboard code must call REST only; no `lib/db/helper` or server-side DB access from UI.

### 2.1 Remove Helpers and Introduce REST Client (Ticket 6)

**Replace all helper usage with REST client**
- **Audit**: List every use of `lib/db/helper` and `lib/db/helper-*` in canvas and dashboard (grep `@lib/db/helper` and helper imports).
- **REST client**: Implement or extend client that wraps fetch for tenants, projects, versions (CRUD + publish/unpublish), classes, properties, class-properties (CRUD + bulk), and commit/push/pull/merge. Auth: send JWT or API key per objectified-rest contract.
- **Replace**: For each call site in dashboard (stats, recent activity, projects, versions), studio/editor, sidebar, and forms, use REST client or Next.js API route that only proxies to objectified-rest with session. No direct DB or helper usage.
- **Next.js API routes**: Either remove and call objectified-rest directly from client, or keep thin proxy routes that add session and forward to objectified-rest.
- **Cleanup**: Remove or archive helper modules used only by canvas/dashboard; fix tests and build.
- **Reference**: `objectified-ui/lib/api/rest-client.ts`, `paths-client.ts`; dashboard pages; `editor/page.tsx`; StudioSideNav; ClassEditDialog, PropertyDialog, ClassPropertyEditDialog.

| Ticket | Feature Description |
|--------|---------------------|
| #42    | Add UI-Only REST services for Auditing |
| #43    | Add REST service usage to UI |
| #44    | Replace all calls in Dashboard with REST services calls |
| #45    | Replace Next.JS API routes with REST service calls |
| #46    | Clean up Canvas/Dashboard call conversions |

---

## 3 UI: Dashboard

> **Section Status**: Dashboard layout and all list/manage pages use REST only.

### 3.1 Dashboard Shell & Navigation (Ticket 7)

**Layout, nav, theme, routes**
- **Layout**: Main content area and responsive shell; sidebar with links to Dashboard home, Projects, Versions, Tenants, Users (if admin), Profile. Active state and responsive behavior.
- **Theme**: Use existing theme provider and system preference for light/dark; ensure all dashboard pages respect it. Theme selector in header if desired.
- **Routes**: `/dashboard`, `/dashboard/projects`, `/dashboard/versions`, `/dashboard/tenants`, `/dashboard/users`, `/dashboard/profile`. Placeholder pages OK until Tickets 8/9.
- **Reference**: `objectified-ui/src/app/ade/dashboard/layout.tsx`, `DashboardSideNav.tsx`; ThemeSelector, ThemeRegistry.

| Ticket | Feature Description |
|--------|---------------------|
| #47    | Create main layout and content area for UI Dashboard |
| #48    | Establish theme provider and system preferences |
| #49    | Establish correct routes for dashboard |

---

### 3.2 Users, Tenants, Tenant-Admins (Ticket 8)

**User and tenant management via REST**
- **Users**: List (admin only), create (signup), edit, deactivate; all via REST users API.
- **Tenants**: List (current user’s tenants), create, edit, delete; slug; REST tenants API. Reference: `objectified-ui/src/app/ade/dashboard/tenants/page.tsx`.
- **User–tenant**: Per tenant, list members, add member (by user id or email), remove member, optional role; REST members API.
- **Tenant administrators**: List, add, remove; only tenant admins see this; REST tenant-admins API.
- **Permissions**: Show/hide sections by role (admin vs tenant-admin vs member); handle 403 from API.
- **Reference**: New or refactored pages under dashboard: users, tenants, tenant members, tenant administrators; shared tables, forms, confirm dialogs; Radix UI and Tailwind.

| Ticket | Feature Description |
|--------|---------------------|
| #50    | Create Users page in Dashboard |
| #51    | Create Tenants page in Dashboard |
| #52    | Create User-Tenant page in Dashboard |
| #53    | Create Tenant Administrators page in Dashboard |
| #54    | Handle Permissions to show/hide sections by role |

---

### 3.3 Projects & Versions List (Ticket 9)

**Projects and versions CRUD and publish**
- **Projects**: List by tenant via REST; create project dialog (name, slug, description, metadata); edit dialog; delete / permanent delete; dropdown actions. Reference: `objectified-ui/src/app/ade/dashboard/projects/page.tsx`.
- **Import**: Optional import project from OpenAPI/URL; call REST import if available. Reference: OpenAPIImportDialog, ImportDialog.
- **Versions**: List by project via REST; create version dialog (version_id, description, changelog, copy from for branch); edit; delete. Reference: `objectified-ui/src/app/ade/dashboard/versions/page.tsx`.
- **Publish**: Publish dialog (visibility); unpublish; freeze-schema; all via REST.
- **Published**: List published versions; link to open in Studio. Reference: `published/page.tsx`.
- **Optional**: Version diff view; relationship graph dialog (RelationshipGraphDialog, compareSchemas). Primitives list/create/edit/import if in OSS scope (PrimitivesManagementClient, PrimitiveEditorDialog).

| Ticket | Feature Description |
|--------|---------------------|
| #55    | Create Projects page in Dashboard |
| #56    | Create import for versions in dashboard |
| #57    | Create Versions page in Dashboard |
| #58    | Create Publish page in Dashboard |
| #59    | Create Published page in Dashboard |
| #60    | Create additional support pages in Dashboard |

---

## 4 UI: Local-First Version & Workflow

> **Section Status**: Version edits live in browser until commit; push/pull/merge with conflict resolution.

### 4.1 Local Version State & Undo/Redo (Ticket 10)

**In-browser version state and undo stack**
- **State shape**: Single source of truth: versionId, classes[], properties[], class_properties[] (order and overrides), canvas_metadata per class, groups. Reference: StudioContext, editor types.
- **Load**: On “Open in Studio”, call REST get (or pull) for version; hydrate local state and canvas/sidebar. Reference: editor/page.tsx initial load.
- **Mutations**: Add/update/delete class, add/update/remove class-property, reorder; all update local state only (no REST per edit). Canvas metadata (position, dimensions, style, group) updated on drag/resize/group; persist in local state (saveDefaultCanvasLayout/getDefaultCanvasLayout pattern).
- **Undo stack**: Push previous state on each mutation; max depth (e.g. 50). Undo/redo: pop and apply; clear stack on commit or discard.
- **Optional**: localStorage backup keyed by versionId; clear on successful push.

| Ticket | Feature Description |
|--------|---------------------|
| #61    | Create local in-browser version and undo stack in UI |
| #62    | Create Load functionality in browser application |
| #63    | Create canvas mutations functionality |
| #64    | Add undo stack to the UI |
| #65    | Add localStorage backup |

---

### 4.2 Commit, Push, Pull, Merge Workflow (Ticket 11)

**Toolbar actions and conflict resolution**
- **Toolbar/menu**: Commit (snapshot local state, optional message; reset undo or keep one pre-commit); Push; Pull; Merge (enabled when pull indicates diverged or conflicts). Reference: EditorToolbar, StudioHeader.
- **Commit**: Persist “last committed” locally; after Push, clear dirty and optionally undo stack.
- **Push**: Call REST push with committed (or current) state; on 409 (newer on server), suggest Pull then Merge.
- **Pull**: Call REST pull; if local dirty, block or offer stash/discard; replace or merge local state with server response.
- **Merge UI**: List conflicts (class/property, path, description); “Use mine” / “Use theirs” / “Edit manually” per conflict; apply resolution and update local state; allow Push. Reference: ClassImportDialog conflict resolution patterns.
- **Indicators**: Dirty, unpushed commits, “server has new changes”.

| Ticket | Feature Description |
|--------|---------------------|
| #66    | Add Toolbar for Version-based actions |
| #67    | Add Toolbar for commit |
| #68    | Add Toolbar for Push functionality |
| #69    | Add Toolbar for Pull functionality |
| #70    | Add Merge UI for merging versions |

---

### 4.3 Version History – Rollback, Remove, Branch (Ticket 12)

**History panel and version actions**
- **History panel**: List revisions (id, timestamp, optional message) via REST; show in dashboard or Studio.
- **Load revision**: Replace local state with chosen revision (read-only or editable in Studio).
- **Rollback (server)**: Set version state to chosen revision; append to history; call REST.
- **Branch**: Dialog for new version name/id; REST create version from source revision; open new version in Studio. Reference: versions page “copy from”.
- **Remove**: Confirm; REST delete version (or revision); redirect to versions list.

| Ticket | Feature Description |
|--------|---------------------|
| #71    | Add version history to UI |
| #72    | Add load revision to UI version history |
| #73    | Add rollback to UI version history |
| #74    | Add branching to UI version history |
| #75    | Add history removal to UI version history |

---

## 5 UI: Schema Canvas (Class Diagram)

> **Section Status**: React Flow canvas; all data from local version state; no per-move REST.

### 5.1 Canvas Container & Selectors (Ticket 13a)

**Project/version selector and canvas shell**
- **Project/version selector**: In toolbar; load projects and versions via REST; on switch, reload local state and canvas. Reference: EditorToolbar project/version Select.
- **React Flow**: Background, Controls, MiniMap; viewport persistence. Reference: editor/page.tsx ReactFlow, Background, Controls.
- **Read-only**: When version is published, set read-only (no add/delete/edit). Reference: isReadOnly from version.published.

| Ticket | Feature Description |
|--------|---------------------|
| #76    | Add project/version selector in UI Canvas |
| #77    | Configure react-flow canvas properly |
| #78    | Add read-only behavior to the UI canvas |

---

### 5.2 Class Nodes & Edges (Ticket 13b)

**Nodes and edges from local state**
- **Class nodes**: Render from local state; position, dimensions, style from canvas_metadata. Reference: ClassNode.tsx, NodeData.
- **Class node**: Expand/collapse properties; theme (backgroundColor, border, icon); double-click opens class form. Reference: ClassNode.
- **Edges**: Refs between classes; style by type (direct/optional/weak/bidirectional). Reference: SmartEdge.tsx, EdgeWithWideHit.tsx, edge-styling.
- **Interactions**: Node drag/resize; single and multi selection; pan/zoom. Reference: useNodesState, onNodesChange.

| Ticket | Feature Description |
|--------|---------------------|
| #79    | Class node design for the react-flow canvas |
| #80    | Class-node properties and themes |
| #81    | Class node edge design and behavior in the canvas |
| #82    | Add interactivity to nodes in the react-flow canvas |

---

### 5.3 Groups (Ticket 13c)

**Group nodes and class membership**
- **Create group**: From toolbar or at drop position; add/remove class nodes; rename, color, style. Reference: GroupNode.tsx, handleCreateGroup, handleCreateGroupAtPosition.
- **Delete**: Delete group; “delete all classes in group” with confirm. Reference: handleDeleteAllClassesInGroup.

| Ticket | Feature Description |
|--------|---------------------|
| #83    | Add ability to create groups in the react-flow canvas |
| #84    | Deletion of groups in the UI |

---

### 5.4 Canvas Search & Focus (Ticket 13d)

**Search and focus mode**
- **Canvas search**: Query input; regex toggle; filters: type (class/allOf/oneOf/anyOf), group, has properties, property name. Reference: canvasSearchQuery, searchFilterType, searchFilterGroup.
- **Search history**: Add on close; list, remove, clear (localStorage). Reference: useSearchHistory.ts, CanvasSettingsDialog.
- **Focus mode**: Selection plus N-degree neighbors; “Focus on group”; exit on Esc. Reference: focusModeEnabled, focusModeDegree, focusOnGroup.

| Ticket | Feature Description |
|--------|---------------------|
| #85    | Add search functionality to the canvas |
| #86    | Add search history to the canvas search functionality |
| #87    | Implement Focus Mode into the Canvas |

---

### 5.5 Layout & Dependency (Ticket 13e)

**Layout and dependency overlay**
- **Layout**: Save default layout (per version/user); load default on version load. Auto-layout (e.g. dagre); layout preview then apply. Reference: saveDefaultCanvasLayout, getDefaultCanvasLayout, canvas-auto-layout.ts, layoutPreviewNodes.
- **Layout quality**: Optional hints (edge crossings, spacing). Reference: layout-quality.ts, canvasSuggestions.
- **Dependency overlay**: Upstream/downstream/path from selected node; circular ref warning. Reference: schema-metrics, getCircularDependencyEdgeIds, dependencyView.
- **Schema metrics panel**: Optional (depth, circular, affected count). Reference: SchemaMetricsPanel.

| Ticket | Feature Description |
|--------|---------------------|
| #88    | Implement Layout functions to the Canvas |
| #89    | Add layout hinting to the canvas |
| #90    | Add dependency overlay to the Canvas |
| #91    | Add schema metrics panel to the canvas |

---

### 5.6 Export & Canvas Settings (Ticket 13f)

**Export and settings dialog**
- **Export**: PNG, SVG, JPEG, PDF, Mermaid, PlantUML, DOT, GraphML, JSON. Reference: useExportFunctions, EditorToolbar.
- **Export Wizard**: Format options, include groups, background; capture and download. Reference: ExportWizard.
- **Canvas settings**: Grid (size, style, snap, visible); background (solid/grid/image/gradient/texture); edge styling (style type, color, arrow per ref type); routing (straight/bezier/orthogonal/smart); animation; search history management. Reference: CanvasSettingsDialog.tsx, StudioContext edgeStyling.

| Ticket | Feature Description |
|--------|---------------------|
| #92    | Add export dialog with export functions for the Canvas |
| #93    | Create an export wizard in the export form |
| #94    | Add canvas settings form |

---

### 5.7 Class Actions & Sidebar (Ticket 13g)

**Add/delete/copy/reference and sidebar**
- **Add class**: Toolbar or context menu; create in local state; place on canvas.
- **Delete class**: Single or multi-select; confirm; remove from local state and canvas. Reference: handleDelete, deleteClassWithSession pattern.
- **Copy / Paste / Duplicate**: Classes (and optional refs) in local state.
- **Create reference**: From property to class (edge); update local state (class-property $ref). Reference: handleCreateReference.
- **Sidebar**: Classes tab (list, search, add, edit, delete, select → zoom); Properties tab (list project properties; add, edit, delete; select → highlight on canvas); Groups tab (list groups; select → focus on group; delete group / delete all classes). Load from local state. Reference: StudioSideNav.tsx.
- **Tag manager**: Assign/remove tags to class; list tags for project; load/save via REST or local state. Reference: TagManager, ClassEditDialog tags.

| Ticket | Feature Description |
|--------|---------------------|
| #95    | Add the ability to create a new class from the sidebar |
| #96    | Add ability to delete classes from the canvas |
| #97    | Add copy/paste/duplicate for classes in the canvas |
| #98    | Add the ability to create a reference in a class node |
| #99    | Add sidebar updates for the Classes in the Canvas |
| #100   | Create a tag manager that can be used in the canvas |

---

## 6 UI: Class & Property Forms

> **Section Status**: Forms drive local state (or REST on submit); 100% OpenAPI 3.2.0 / JSON Schema 2020-12 coverage for in-scope subset.

### 6.1 Class Form (Ticket 14a)

**Class edit dialog and schema**
- **Class edit dialog**: Name, description; open from canvas double-click or sidebar. Reference: ClassEditDialog.tsx.
- **Schema extensions**: OpenAPI 3.2.0 / JSON Schema 2020-12 (e.g. discriminator, externalDocs).
- **Tags**: Assign, remove; tag list for project. Reference: assignTagToClass, removeTagFromClass, getTagsForClass.

| Ticket | Feature Description |
|--------|---------------------|
| #101   | Add Class Edit dialog, reuses the Add Edit dialog |
| #102   | Class edit dialog needs to handle schema extensions |
| #103   | Class node tag behavior |

---

### 6.2 Property Form – Core & Types (Ticket 14b)

**Property dialog and type-specific fields**
- **Property dialog**: Create/edit; name, type (string/number/integer/boolean/object/array/null), description, required. Reference: PropertyDialog.tsx, PropertyFormFields.tsx.
- **$ref selector**: Link to class or library property; store in property data. Reference: PropertyFormFields, PrimitiveSelector.
- **String**: format, pattern, minLength, maxLength, enum, default, example. Reference: stringConstraints.
- **Number/integer**: format (int32/int64, float/double); minimum, maximum, exclusiveMin/Max, multipleOf; enum, default. Reference: numberConstraints.
- **Array**: items schema, minItems, maxItems, uniqueItems; prefixItems (tuple); contains, minContains, maxContains. Reference: arrayConstraints, tupleMode.
- **Object**: properties, required, additionalProperties, patternProperties, unevaluatedProperties. Reference: objectConstraints.

| Ticket | Feature Description |
|--------|---------------------|
| #104   | Add create property form that can be reused for editing |
| #105   | Add $ref selector to the property dialog |
| #106   | Add string constraints to the property form |
| #107   | Add number/integer constraints to the property form |
| #108   | Add array constraints to the property form |
| #109   | Add object constraints to the property form

---

### 6.3 Property Form – Metadata & Class-Property (Ticket 14c)

**Metadata, conditionals, extensions, class-property overrides**
- **Metadata**: readOnly, writeOnly, deprecated, nullable, title; default; examples (array). Reference: propertyFlags, values section.
- **Conditional schema**: if/then/else, dependentSchemas (JSON Schema 2020-12). Reference: ConditionalSchemaBuilder.
- **Extensions**: x-*; XML (attribute, wrapped). Reference: ExtensionsEditor, xmlAttribute, xmlWrapped.
- **Class-property edit**: Override required, description; order; nested parent_id. Reference: ClassPropertyEditDialog.
- **Validation**: Client-side validation (same rules as REST); call REST validate on submit; show errors.

| Ticket | Feature Description |
|--------|---------------------|
| #110   | Add Metadata to property form |
| #111   | Add Conditional schema settings to the property form |
| #112   | Add extensions to the property form |
| #113   | Add additional class-property editing features |
| #114   | Add validation to client-side for properties |

---

## 7 Schema Designer: Enterprise, Code Generation & Mode Switching

> **Section Status**: Schema-designer features for OSS release: enterprise capabilities, code generation support, and OpenAPI vs SQL schema mode. Ticket numbers to be assigned in GitHub.

### 7.1 Schema Mode: OpenAPI vs SQL

**Mode switching and ID-based references**
- Allow the schema designer to operate in **OpenAPI mode** (current: JSON Schema / OpenAPI 3.2.0) or **SQL mode**.
- In **SQL mode**, references between schema objects (classes) are expressed by **ID** (e.g. foreign-key style: `user_id`, `tenant_id`, `parent_id`) rather than (or in addition to) nested `$ref`; support defining and editing these ID-based references in the class/property forms and on the canvas.
- Persist the selected mode per version or project; validate and export appropriately (OpenAPI doc in OpenAPI mode; DDL or relational model in SQL mode).
- **Reference**: ClassEditDialog, PropertyFormFields, canvas edges; add mode selector in toolbar or project/version settings; extend schema storage for ID-reference metadata.

| Ticket | Feature Description |
|--------|---------------------|
| #115   | Add schema mode selector (OpenAPI vs SQL) in the schema designer |
| #116   | Implement ID-based references between classes in SQL mode (e.g. foreign-key style properties) |
| #117   | Persist and validate schema according to selected mode; export OpenAPI or SQL/DDL accordingly |
| #118   | Extend class and property forms to define and edit ID-based references when in SQL mode |

---

### 7.2 Code Generation from Schema

**Templates, preview, and versioning for codegen**
- **Code generation templates**: Configurable templates for generating code from the current schema (e.g. TypeScript/JavaScript types, Prisma schema, SQL DDL, GraphQL schema, Go structs, Pydantic models). Store templates in project or workspace; allow custom templates (e.g. Mustache/Handlebars or a small DSL).
- **Code generation preview**: In the schema designer, a panel or dialog to preview generated code for the selected template and target (e.g. “TypeScript types for this version”). Refresh on schema change; copy or download output.
- **Schema version tag for codegen**: Tag or label schema versions for code generation (e.g. `v1`, `api-v2`); generate against a chosen version or the current working version.
- **Validation rules export**: Export validation rules (required, format, pattern, min/max, enum, etc.) in a form suitable for code generation or documentation (e.g. JSON or structured format for client validators).
- **Reference**: New UI under Studio or Dashboard (e.g. “Generate code” action); template registry; reuse existing export/generator patterns where applicable.

| Ticket | Feature Description |
|--------|---------------------|
| #119   | Add configurable code generation templates (TypeScript, Prisma, SQL DDL, GraphQL, etc.) |
| #120   | Add code generation preview panel in schema designer with copy/download |
| #121   | Add schema version tagging for code generation and generate against chosen version |
| #122   | Export validation rules in a structured format for code generation and documentation |

---

### 7.3 Enterprise Schema Designer Features

**Annotations, multi-schema, and audit**
- **Schema annotations for codegen**: Support `x-*` or custom annotations on classes and properties that drive code generation (e.g. table name, column name, ORM hints, serialization name). Edit in class/property forms; include in exports and codegen templates.
- **Multi-schema workspace**: Support viewing or comparing multiple schemas (or versions) in one workspace (e.g. side-by-side or diff) for comparison and code generation across versions.
- **Audit log for schema changes**: Optional audit trail of schema changes (who changed what, when) for compliance; store in version history or separate audit table; expose in dashboard or version history UI.
- **Documentation generation**: Generate API documentation (e.g. OpenAPI document, Markdown, or static site) from the schema designer with optional branding and tenant-specific styling.
- **Reference**: ClassEditDialog, PropertyDialog, version history; new “Annotations” or “Codegen” section in forms; audit tables and REST endpoints; docs generator.

| Ticket | Feature Description |
|--------|---------------------|
| #123   | Add schema annotations (x-* / custom) for code generation in class and property forms |
| #124   | Add multi-schema workspace view for comparison and code generation across versions |
| #125   | Add optional audit log for schema changes (who, what, when) with dashboard visibility |
| #126   | Add documentation generation from schema (OpenAPI, Markdown, or static site) with optional branding |

---

## 8 Enterprise & Developer Experience

> **Section Status**: Enterprise readiness and development-friendly capabilities. Ticket numbers to be assigned in GitHub.

### 8.1 Security, Auth & Permissions

**Enterprise auth and fine-grained access**
- **SSO / OIDC / SAML**: Optional integration with identity providers (e.g. Okta, Auth0, Azure AD) for login and user provisioning; support OIDC discovery and SAML metadata for enterprise deployments.
- **RBAC**: Fine-grained roles and permissions beyond tenant-admin (e.g. schema-editor, viewer, publisher, auditor); permission checks on REST endpoints and UI; optional resource-level permissions (per project or version).
- **API key scopes**: Scope API keys by tenant, project, or role (e.g. read-only vs full) for CI/CD and external integrations.
- **Reference**: auth routes, middleware; new tables or config for roles/permissions; document in OpenAPI.

| Ticket | Feature Description |
|--------|---------------------|
| #127   | Add optional SSO integration (OIDC / SAML) for enterprise identity providers |
| #128   | Implement RBAC with configurable roles and permissions (schema-editor, viewer, publisher, auditor) |
| #129   | Add API key scopes (tenant, project, role) for CI/CD and integrations |

---

### 8.2 Observability, Reliability & Operations

**Health, metrics, and operational controls**
- **Health and readiness**: REST endpoints for liveness and readiness (e.g. `/health`, `/ready`) for Kubernetes and load balancers; optional DB and dependency checks.
- **Structured logging and tracing**: Structured logs (e.g. JSON) with request id, tenant, user; optional OpenTelemetry or trace-id for debugging and observability.
- **Rate limiting and quotas**: Configurable rate limits per tenant or API key; optional quotas for projects/versions for fair use and cost control.
- **Backup and restore**: Documented backup/restore procedures for version history and audit data; optional export/import for disaster recovery.
- **Reference**: new health routes; logging middleware; rate-limit middleware; ops runbook or docs.

| Ticket | Feature Description |
|--------|---------------------|
| #130   | Add health and readiness endpoints for orchestration and load balancers |
| #131   | Add structured logging and optional OpenTelemetry tracing |
| #132   | Add configurable rate limiting and optional quotas per tenant or API key |
| #133   | Document backup/restore and optional export/import for disaster recovery |

---

### 8.3 Developer-Friendly Integrations

**CLI, webhooks, catalog API, and promotion**
- **Developer CLI / SDK**: CLI or SDK (e.g. Node or Python) for scripting: pull/push schema, export OpenAPI, trigger code generation; usable in CI/CD pipelines and local dev.
- **Webhooks**: Configurable webhooks on schema events (e.g. version committed, published, branch created); payload with version/project metadata; retry and secret for signing.
- **Schema catalog API**: Public or authenticated catalog API to list projects, versions, and published schemas (by tenant or org) for discovery, Backstage catalog sync, or API gateways.
- **Schema promotion and environments**: Optional promotion workflow (e.g. dev → staging → prod) with environment or deployment targets; track which version is “live” per environment.
- **Reference**: new CLI package or script; webhook table and delivery job; catalog endpoints; environment/promotion metadata.

| Ticket | Feature Description |
|--------|---------------------|
| #134   | Add developer CLI or SDK for pull/push, export, and codegen in CI/CD |
| #135   | Add configurable webhooks for schema events (commit, publish, branch) with retry and signing |
| #136   | Add schema catalog API for discovery and integration with API gateways or IDPs |
| #137   | Add optional schema promotion workflow (dev/staging/prod) with deployment targets |

---

### 8.4 Developer Onboarding & Tooling

**Quickstart, samples, and IDE support**
- **Quickstart and samples**: One-command or script to run Objectified locally (e.g. Docker Compose); sample project(s) with example schemas and versions for onboarding.
- **API playground**: Interactive API docs (e.g. Swagger UI or Stoplight) from the published OpenAPI spec; try-it-out for key endpoints with auth.
- **IDE or editor integration**: Optional VS Code (or other) extension for schema validation, snippet generation, or “open in Objectified” from local OpenAPI/JSON Schema files.
- **Reference**: docker-compose, sample data seeds; OpenAPI UI; extension repo or spec.

| Ticket | Feature Description |
|--------|---------------------|
| #138   | Add quickstart (e.g. Docker Compose) and sample projects for onboarding |
| #139   | Add API playground (Swagger UI or similar) from OpenAPI spec with try-it-out |
| #140   | Add optional IDE/editor integration (e.g. VS Code extension) for schema validation and links to Objectified |

---

## 9 Backstage IDP Plugin

> **Section Status**: Plugin for use within Backstage (Internal Developer Portal). Enables schema discovery, documentation, and workflow from the IDP. Ticket numbers to be assigned in GitHub.

### 9.1 Backstage Plugin – Core

**Plugin package and integration**
- **Backstage plugin package**: Create a Backstage plugin (e.g. `@internal/objectified-plugin` or OSS name) that can be added to a Backstage app; plugin exposes one or more pages and optional entity cards.
- **Configuration and auth**: Plugin config for Objectified REST base URL and auth (API key or Backstage proxy with user identity); support Backstage’s proxy for secure backend calls.
- **Entity integration**: Define Backstage catalog entity kind(s) for “Schema” or “API” (e.g. `objectified-schema.v1`) with spec pointing to project/version; optional entity provider to sync from Objectified catalog API into Backstage Software Catalog.
- **Reference**: Backstage plugin API; `createPlugin`, `createRouteRef`; Backstage auth and proxy; catalog `Entity` and provider interfaces.

| Ticket | Feature Description |
|--------|---------------------|
| #141   | Create Backstage plugin package with page(s) and configuration for Objectified REST URL and auth |
| #142   | Add Backstage proxy support for secure calls to Objectified API |
| #143   | Define Backstage catalog entity kind for Schema/API and optional entity provider to sync from Objectified |

---

### 9.2 Backstage Plugin – Features

**Schema discovery, docs, and actions**
- **Schema overview page**: Plugin page that lists projects and versions (by tenant or org); link to open schema in Objectified or show read-only summary (classes, last updated).
- **TechDocs integration**: Option to publish generated schema documentation (OpenAPI, Markdown) to Backstage TechDocs so schema docs appear alongside other docs in the IDP.
- **Entity card and actions**: Catalog entity card for Schema/API entities showing version, last published, link to Objectified; optional “Open in Objectified” and “Export OpenAPI” actions.
- **Reference**: Backstage frontend components; TechDocs API; catalog entity page extensions.

| Ticket | Feature Description |
|--------|---------------------|
| #144   | Add plugin page for schema overview (projects, versions) with links to Objectified |
| #145   | Add optional TechDocs integration to publish schema documentation into Backstage |
| #146   | Add catalog entity card and actions (Open in Objectified, Export OpenAPI) for Schema/API entities |

---

## Dependency Order

- **REST**: 1 → 2 → 3 → 4 → 5 (5 depends on 2 for version history).
- **UI**: 6 after 5; 7 after 6; 8, 9 after 7; 10 after 6 and 9; 11 after 5 and 10; 12 after 5 and 6; 13a–13g after 10 and 3; 14a–14c after 10 and 4; 15 optional after 10 and paths REST; 16 any time.

---

## Current Code References

| Area | Reference |
|------|-----------|
| Dashboard | `objectified-ui/src/app/ade/dashboard/**`, `DashboardSideNav.tsx` |
| Studio/editor | `objectified-ui/src/app/ade/studio/editor/page.tsx`, `EditorToolbar.tsx`, `StudioContext.tsx` |
| Canvas nodes/edges | `ClassNode.tsx`, `GroupNode.tsx`, `SmartEdge.tsx`, `EdgeWithWideHit.tsx` |
| Sidebar | `StudioSideNav.tsx` |
| Forms | `ClassEditDialog.tsx`, `PropertyDialog.tsx`, `PropertyFormFields.tsx`, `ClassPropertyEditDialog.tsx` |
| Utils | `openapi.ts`, `jsonschema.ts`, `schema-merge.ts`, `canvas-auto-layout.ts`, `edge-styling.ts` |
| REST client | `lib/api/rest-client.ts`, `paths-client.ts` |
| objectified-rest | `src/app/*_routes.py`, `database.py`, `auth.py` |

---

**Document Version**: 1.1
**Last Updated**: March 02, 2026  
**Next Review**: Before OSS release  
**Purpose**: Single-step tasks with enough detail to drive an LLM/Agent to implement each feature.
