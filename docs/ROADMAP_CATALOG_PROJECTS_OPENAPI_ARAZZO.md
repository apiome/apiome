# Roadmap — Catalog, Projects, OpenAPI and Arazzo (RC9)

_Drafted 2026-11-19. Release: **RC9** (see [`RC9_PLAN.md`](RC9_PLAN.md)). Priority: **high** — these are the core of Apiome._
_The Contracts and PactFlow release is **RC10**: [`RC10_PLAN.md`](RC10_PLAN.md)._

**Umbrella:** [#7032](https://github.com/apiome/apiome/issues/7032). **Issue ID prefix:** `COA`. Epics `COA-EPIC-n`, issues `COA-n.m`. **GitHub title format:** `apiome: [COA-<epic>.<issue>] <title>`.

## 0. Source description (request, verbatim)

> Once RC9 is complete, create an RC10 that contains all of the remaining cleanup and improvement items for the Projects and Catalog, since OpenAPI/Arazzo is high priority, along with the Catalog import/export features. These are the core to Apiome, and important to keep current and competitive. It may make sense to make this an RC9, and rename the current RC9 that's being created (for pact and contracts) to RC10.

## 1. Current standards (checked 2026-11-19)

| Spec | Current | Apiome today |
| --- | --- | --- |
| OpenAPI | **3.2.0** (3.1.2 patch, 3.0.4) | Import/emit 2.0, 3.0, 3.1, 3.2; 3.1/3.2 meta-schema validation; 3.2 `query`, `additionalOperations`, tag hierarchy modelled |
| Arazzo | **1.1.0** (May 2026; AsyncAPI sources, `querystring`) | Read/normalise/lint/emit 1.0.x and 1.1.x in apiome-rest, the CLI, the legacy and UI generators and the docs (COA-1.1) |
| Overlay | **1.1.0** (`copy`, RFC 9535), 1.2 in progress | Applies 1.0–1.2 with provenance; stored overlays; lint rules; no UI manager |

Sources: OpenAPI Initiative newsletters (Feb and Jun 2026), the Arazzo specification page and Redocly's Arazzo 1.1 release post. Competitive notes (from the Oct 2026 market analysis): OpenAPI 3.2 is a lead for Apiome (Spectral added 3.2 on 1 Oct 2026); Specmatic charges for Arazzo testing; Redocly/vacuum/Spectral lint Arazzo and Overlay; lint `--fix` and governance scorecards are the catch-up items (adopted below).

## 2. MVP definition

A team can (1) import an Arazzo 1.0/1.1 workflow with the OpenAPI/AsyncAPI files it calls, see it as steps and a graph, and export it as the right version; (2) trust that no OpenAPI 3.0/3.1/3.2 construct is silently lost, with every version validated; (3) author and see the 3.2 additions in Projects; (4) manage Overlays in the UI; (5) export bundled, dereferenced or split specs; and (6) read docs that match the code. **V2:** workflow execution, change classification for Arazzo, the upgrade assistant, `$ref` hygiene, new validators.

## 3. Existing issues adopted (not duplicated)

| Issue | Title | Epic |
| --- | --- | --- |
| #5875 | GVM-EPIC-4 Arazzo and Overlay governance | Governance |
| #5879 | GVM-4.4 Arazzo 1.1 validation rules | Governance |
| #5880 | GVM-4.5 Arazzo and Overlay in the ladder, fixes and CLI | Governance |
| #5868 | GVM-EPIC-3 Deterministic auto-fix | Governance |
| #5869–#5872 | GVM-3.1 rule SPI, 3.2 fix plan + Overlay rendering, 3.3 `apiome lint --fix`, 3.4 CI fix suggestions | Governance |
| #6654 | MFX-38.1 follow-up: GitLab/Bitbucket/Azure DevOps export git delivery | Import/export |
| #6706 | Catalog import and export demo script | Cleanup |

Related, not adopted: #5849/#5851/#4544 (Arazzo for agents, in Agent Tool Quality; unblocked by COA-1.7), #5804 (Overlays as SDK input). Decision needed: the Version Archaeology epic #1023 and Diff 0.247–0.251 (evolution timeline, change attribution, cross-project comparison, merge assistant) are Projects improvements that were moved to the Diff project on 2026-11-19; RC9 can take them.

## 4. Epics

| Epic | Title | Issues |
| --- | --- | --- |
| COA-EPIC-1 | Arazzo: complete, current and visible | 7 |
| COA-EPIC-2 | OpenAPI 3.2 / 3.1 fidelity and authoring | 8 |
| COA-EPIC-3 | Import and export fidelity | 6 |
| COA-EPIC-4 | Catalog and Projects cleanup | 4 |

### COA-EPIC-1 · [#7033](https://github.com/apiome/apiome/issues/7033) — Arazzo: complete, current and visible

Arazzo 1.0/1.1 is read, normalised, linted and emitted in apiome-rest, but the CLI, the legacy generator, the UI generator and the docs still say 1.0, workflows have no viewer, and filesets are not supported.

| Issue | Title | Summary | Labels | Par | MVP | Cx | Modules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| COA-1.3 · [#7039](https://github.com/apiome/apiome/issues/7039) | Arazzo workflow viewer in Projects and Catalog | See an Arazzo workflow as steps, inputs, outputs and success/failure paths — not just as a file | `enhancement`, `ui`, `mvp` | N | Y | L | apiome-ui, apiome-rest |
| COA-1.4 · [#7040](https://github.com/apiome/apiome/issues/7040) | Arazzo round-trip and conformance corpus | Burn down the Arazzo cells in the round-trip xfail matrix and add an official-fixture corpus | `enhancement`, `rest`, `mvp` | Y | Y | M | apiome-rest |
| COA-1.5 · [#7041](https://github.com/apiome/apiome/issues/7041) | Arazzo workflow records: REST, CLI and docs | Read workflows and steps through the API and `apiome`, and make the docs match what is stored | `enhancement`, `rest`, `cli`, `mvp` | Y | Y | M | apiome-rest, apiome-cli, apiome-docs |
| COA-1.6 · [#7042](https://github.com/apiome/apiome/issues/7042) | Arazzo change reports and breaking-change depth | Classify changes to inputs, success criteria, parameters and sources — not only step removal and reorder | `enhancement`, `rest`, `diff`, `v2` | Y | N | M | apiome-rest |
| COA-1.7 · [#7043](https://github.com/apiome/apiome/issues/7043) | Run an Arazzo workflow against a target | Execute a workflow end to end against a verification target or the mock and report per-step results | `enhancement`, `rest`, `cli`, `v2` | N | N | L | apiome-rest, apiome-cli |

**✅ COA-1.1 · #7037 Arazzo 1.1 consistency sweep: CLI, generator, UI and docs — Complete**
- **Shipped:** CLI 0.148.0 vendors the Arazzo 1.1 schema (`import_/schemas/arazzo/1.1/2026-04-15.json`) and validates each document against the schema for the version it declares (`arazzo_version_line`; other versions fail at `/arazzo`). REST 1.767.0 / OpenAPI 1.598.0: `GET /v1/arazzo/...` (and the per-class route) take `arazzo_version` (default `1.0.1`; `400` otherwise); `arazzo_generator.resolve_generator_arazzo_version` applies the export target's rule (`1.1.0` for AsyncAPI sources, a 1.0 request for one is rejected). UI 0.671.0: `generateArazzoSpec` takes `arazzoVersion` / `sourceDescriptions` (`resolveArazzoVersion`); the import analyzer accepts 1.1.x; the Projects importer accepts `asyncapi` sources in a 1.1 document and leaves their steps to the server. Docs: `bring-in/import-a-spec.md`, `ship/export-a-spec.md`, regenerated REST/CLI reference, `ARAZZO_ENDPOINTS.md`, release note `arazzo-1-1-consistency`.
- **Problem:** apiome-rest reads 1.0.x and 1.1.x (`arazzo_spec.py`, vendored schemas for both), but `apiome-cli/.../import_/arazzo.py` validates 1.0 only, the legacy generator behind `/v1/arazzo/{tenant}/{project}/{version}` and the UI generator (`apiome-ui/src/app/utils/arazzo.ts`, `templates/arazzo/arazzo-spec.hbs`) emit 1.0.1, and `apiome-rest/docs/ARAZZO_ENDPOINTS.md` and several docs pages say "Arazzo 1.0".
- **Solution/Scope:**
- Vendor the 1.1 schema into the CLI and validate against the version the document declares.
- Give the legacy generator and the UI generator an `arazzoVersion` option (`1.1.0` default for AsyncAPI-bearing sources, otherwise preserve; `1.0.1` selectable).
- Update `ARAZZO_ENDPOINTS.md`, the import wizard copy, `catalog-import-formats.ts` descriptions and the docs pages; remove every "Arazzo 1.0" claim that is no longer true.
- Add a test per surface that a 1.1 document (with an AsyncAPI source) round-trips.
- **Acceptance Criteria:**
- A 1.1 document validates in the CLI, imports in the wizard, and exports from the generator with no downgrade.
- `grep -ri "arazzo 1.0"` over docs and UI copy returns only deliberate mentions.
- Tests cover 1.0.1 and 1.1.0 on each surface.
- **Parallelism/Dependencies:** None; first item of the release.
- **Technical Stack:** apiome-rest, apiome-cli, apiome-ui, apiome-docs
- **Documentation:** `bring-in/import-a-spec.md`, `ship/export-a-spec.md`, `reference/` pages for the Arazzo endpoint and CLI; screenshots: n/a (no UI change)

**✅ COA-1.2 · #7038 Arazzo multi-file filesets — Complete**
- **Shipped:** REST 1.768.0 / OpenAPI 1.599.0: archive, bulk and repository intake rank an Arazzo workflow whose `sourceDescriptions` name sibling members as the root (its sources are dependencies, not rival roots; `.arazzo.*` added to `_ROOT_CANDIDATE_SUFFIXES`; the bulk/git reference closure follows source URLs). New `app.arazzo_source_resolution` resolves each source fileset → catalog (`Database.find_arazzo_source_in_catalog`: same repo/branch path, or same URL) → remote (`remote_ref_resolver.fetch_remote_documents`, SSRF-guarded, under `resolve_remote_refs` + the kill switch). The job summary's `arazzo_sources` block, `ARAZZO_SOURCES_*` events and `format_metadata.arazzoSources` list every unresolved source with a stable reason code. CLI 0.149.0: `apiome import arazzo <archive|directory> [--root]` imports the set through the adapter and prints the source report. Tests build filesets through `unpack_archive` (`tests/test_arazzo_multi_file_filesets.py`, `test_arazzo_1_1.py`). Docs: `bring-in/import-a-spec.md` (Import an Arazzo workflow with its API files), CLI/REST reference, release note `arazzo-multi-file-filesets`.
- **Problem:** FORMAT_SUPPORT_MATRIX §3: 39 of 43 adapters take multi-file filesets; Arazzo, JSON Schema, JTD and samples do not, so an Arazzo workflow cannot be imported with the descriptions it calls unless they are already in the catalog.
- **Solution/Scope:**
- Accept an Arazzo root plus referenced local files in the fileset path, the archive intake (`archive_intake._ROOT_CANDIDATE_SUFFIXES`) and repository imports.
- Resolve relative `sourceDescriptions` inside the fileset first, then the catalog, then remote (SSRF-guarded).
- Report each unresolved source with a stable reason code; store nothing silently.
- **Acceptance Criteria:**
- A zip of `flow.arazzo.yaml` + two OpenAPI files imports as one workflow with both sources resolved.
- Unresolved sources are listed in the import report.
- Corpus/unit tests build the fileset through `unpack_archive`, not directly.
- **Parallelism/Dependencies:** After COA-1.1.
- **Technical Stack:** apiome-rest, apiome-cli
- **Documentation:** `bring-in/import-a-spec.md` (Arazzo sources section); screenshots: n/a (no UI change)

**COA-1.3 · #7039 Arazzo workflow viewer in Projects and Catalog**
- **Problem:** Workflows are persisted (`api_workflows`, `api_workflow_steps`, V225) but a user opening an Arazzo item or a project that references one sees an undifferentiated document; there is no way to read a workflow as a flow. (First confirm what the UI already shows.)
- **Solution/Scope:**
- A **Workflows** tab on Arazzo catalog items and on projects that have workflows: list, per-workflow step list with the operation each step calls (link into the project operation), inputs and outputs.
- A step graph (success/failure actions, `goto`/`end`) drawn with the existing graph components.
- Source-description status (resolved, missing) beside each workflow.
- Empty and error states; keyboard accessible; fixtures for the dump renderer.
- **Acceptance Criteria:**
- Opening a catalog Arazzo item shows its workflows and a step graph.
- Clicking a step opens the referenced operation.
- A11y pass; screenshots light and dark.
- **Parallelism/Dependencies:** After COA-1.1; uses the REST read endpoints from COA-1.7.
- **Technical Stack:** apiome-ui, apiome-rest
- **Documentation:** new `build/arazzo-workflows.mdx`; update `bring-in/catalog.mdx`; screenshots: arazzo-workflows, arazzo-workflow-graph

**COA-1.4 · #7040 Arazzo round-trip and conformance corpus**
- **Problem:** `apiome-rest/tests/roundtrip_xfails.py` lists many Arazzo cells (a2a→arazzo, acp→arazzo, arazzo→apigee …) as strict xfails ("diff not fully explained by the fidelity report").
- **Solution/Scope:**
- For each Arazzo xfail cell, either fix the loss, explain it in the fidelity report, or document it as deliberate.
- Add a corpus of documents from the OpenAPI Initiative examples and common third-party tools (Redocly, Spectral, Specmatic) as foreign-source goldens.
- Add the 1.1 `$components`, runtime-expression and `querystring` cases.
- **Acceptance Criteria:**
- Strict xfails shrink; none is added.
- Foreign-source goldens pass for 1.0.1 and 1.1.0.
- Every remaining xfail has a reason string naming a ticket.
- **Parallelism/Dependencies:** After COA-1.1.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-fidelity.md` (Arazzo rows); screenshots: n/a (no UI change)

**COA-1.5 · #7041 Arazzo workflow records: REST, CLI and docs**
- **Problem:** `import-a-spec.md` says "Workflows and their steps are not stored as their own records yet", yet `arazzo_workflow_persistence.py` writes them; there is no documented way to read them.
- **Solution/Scope:**
- REST: list/get workflows and steps for a version (and for a catalog revision), with `operationRef` resolution state.
- CLI: `apiome arazzo list|show|validate`.
- Correct the docs; document the record shape.
- **Acceptance Criteria:**
- Endpoints and CLI return the persisted workflows; OpenAPI version bumped.
- The stale docs statement is gone.
- **Parallelism/Dependencies:** Feeds COA-1.3.
- **Technical Stack:** apiome-rest, apiome-cli, apiome-docs
- **Documentation:** `bring-in/import-a-spec.md`, new `reference/rest/arazzo.md`, CLI reference; screenshots: n/a (no UI change)

**COA-1.6 · #7042 Arazzo change reports and breaking-change depth**
- **Problem:** `arazzo_breaking_change.py` (61 lines) recognises step removal as breaking and reorder as dangerous; nothing else is classified, so a changed input schema or removed `sourceDescription` is silent.
- **Solution/Scope:**
- Add rules to the CTG classifier registry for workflow input/output schema, parameter, success/failure criteria, `onSuccess`/`onFailure` and source description changes.
- Show them in change reports and the diff CLI/Action.
- **Acceptance Criteria:**
- Each rule has a golden fixture pair; unknown kinds default to breaking (fail-safe).
- **Parallelism/Dependencies:** After COA-1.4.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/api-changelog.mdx`; screenshots: n/a (no UI change)

**COA-1.7 · #7043 Run an Arazzo workflow against a target**
- **Problem:** Specmatic charges for Arazzo testing; Apiome has the suite compiler, runner and targets (ECA) but cannot execute a workflow's step chain, so the agent-facing roadmap (ATQ-5.4) has nothing to test against.
- **Solution/Scope:**
- Compile an Arazzo workflow into an ordered ECA run: step outputs feed later inputs through runtime expressions; success criteria are assertions.
- Same safety model as CTG-4.3 (read-only by default; mutation needs policy + opt-in + fixture).
- Report per step with the expected-vs-actual evidence; `apiome arazzo run`.
- **Acceptance Criteria:**
- A 3-step workflow runs against the mock with passing and failing criteria demonstrated.
- Mutating steps are refused without policy and opt-in.
- **Parallelism/Dependencies:** After COA-1.5; unblocks #5851.
- **Technical Stack:** apiome-rest, apiome-cli
- **Documentation:** `build/arazzo-workflows.mdx` (running a workflow); screenshots: n/a (no UI change)

### COA-EPIC-2 · [#7034](https://github.com/apiome/apiome/issues/7034) — OpenAPI 3.2 / 3.1 fidelity and authoring

OpenAPI 3.2 and 3.1.2 are the current specs. Import and emit exist; the work is to prove nothing is lost, validate every version, and surface 3.2 in Projects.

| Issue | Title | Summary | Labels | Par | MVP | Cx | Modules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| COA-2.1 · [#7044](https://github.com/apiome/apiome/issues/7044) | OpenAPI construct losslessness audit | Prove (or fix) that webhooks, callbacks, links, discriminator, extensions and 3.2 additions survive import → canonical → emit | `enhancement`, `rest`, `mvp` | N | Y | L | apiome-rest |
| COA-2.2 · [#7045](https://github.com/apiome/apiome/issues/7045) | Validate every OpenAPI version against its meta-schema | Add 3.0 and 2.0 meta-schema validation and 3.1.2 conformance; never report "valid" without having validated | `enhancement`, `rest`, `mvp` | Y | Y | S | apiome-rest |
| COA-2.3 · [#7046](https://github.com/apiome/apiome/issues/7046) | JSON Schema dialect handling per document | Honour `jsonSchemaDialect` / `$schema`, and the 3.0 vs 3.1+ schema differences, in import and emit | `enhancement`, `rest`, `mvp` | Y | Y | M | apiome-rest |
| COA-2.4 · [#7047](https://github.com/apiome/apiome/issues/7047) | Bundle and dereference options | Import and export a spec as bundled, dereferenced or split into files | `enhancement`, `rest`, `cli`, `ui`, `mvp` | Y | Y | M | apiome-rest, apiome-cli, apiome-ui |
| COA-2.5 · [#7048](https://github.com/apiome/apiome/issues/7048) | OpenAPI 3.2 in Projects: QUERY, additionalOperations, tags, streaming | Author and view the 3.2 additions in the Projects editor and viewers | `enhancement`, `ui`, `mvp` | N | Y | L | apiome-ui, apiome-rest |
| COA-2.6 · [#7049](https://github.com/apiome/apiome/issues/7049) | Spec upgrade assistant (2.0 → 3.0 → 3.1 → 3.2) | Upgrade a project or catalog item to a newer OpenAPI version with a reviewed change list | `enhancement`, `rest`, `ui`, `cli`, `v2` | Y | N | M | apiome-rest, apiome-ui, apiome-cli |
| COA-2.7 · [#7050](https://github.com/apiome/apiome/issues/7050) | Overlay manager in Versions | List, preview, apply and export Overlay 1.0–1.2 documents (incl. `copy` and reusable actions) from the UI | `enhancement`, `ui`, `rest`, `mvp` | Y | Y | M | apiome-ui, apiome-rest |
| COA-2.8 · [#7051](https://github.com/apiome/apiome/issues/7051) | `$ref` hygiene: refresh, cycles and external-ref policy in the UI | See which external `$ref`s a spec depends on, refresh them, and see cycles | `enhancement`, `ui`, `rest`, `v2` | Y | N | M | apiome-ui, apiome-rest |

**COA-2.1 · #7044 OpenAPI construct losslessness audit**
- **Problem:** The canonical model and normaliser are broad, but a grep did not confirm handling of `webhooks`, `callbacks`, `links`, `discriminator`, `x-` extensions, `$self`, `jsonSchemaDialect`, `$dynamicRef`, `itemSchema` and streaming media types; a silent drop is the worst failure for the core format.
- **Solution/Scope:**
- Build an OpenAPI construct matrix (3.0.x, 3.1.x, 3.2) and a corpus covering each construct, including the OpenAPI Initiative test documents.
- Run import → emit → re-import → diff on each; every loss is fixed or reported in the loss report (seven categories).
- Add the matrix to the docs as the format's fidelity statement.
- **Acceptance Criteria:**
- Zero silent loss across the corpus for 3.0, 3.1 and 3.2 (same bar as RC7).
- The matrix is published and generated from the tests.
- **Parallelism/Dependencies:** Gates COA-2.3 and COA-2.5.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-fidelity.md`, new `reference/openapi-construct-matrix.md`; screenshots: n/a (no UI change)

**COA-2.2 · #7045 Validate every OpenAPI version against its meta-schema**
- **Problem:** `openapi_validator.py` bundles the 3.1 and 3.2 meta-schemas only; 3.0 and Swagger 2.0 documents are not schema-validated, and the 3.1.2 patch release has no explicit coverage.
- **Solution/Scope:**
- Vendor the official 3.0 and 2.0 schemas; validate on import and before export for each emitted version.
- Show "not validated" where a validator is absent (RC7 rule).
- **Acceptance Criteria:**
- Invalid 3.0 and 2.0 fixtures fail with located errors; valid corpus passes.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-a-spec.md`; screenshots: n/a (no UI change)

**COA-2.3 · #7046 JSON Schema dialect handling per document**
- **Problem:** `canonical_json_schema.py` records a dialect that is always draft 2020-12; OpenAPI 3.0 uses a draft-04-like subset (`nullable`, boolean `exclusiveMinimum`) and 3.1/3.2 allow a declared dialect.
- **Solution/Scope:**
- Read and preserve the declared dialect; convert `nullable`/`exclusiveMinimum` forms on upgrade/downgrade with a loss entry where lossy.
- Test the `$dynamicRef`/`$anchor` cases.
- **Acceptance Criteria:**
- 3.0 → 3.1 → 3.2 → 3.0 round-trips on the corpus with every change recorded.
- **Parallelism/Dependencies:** After COA-2.1.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-fidelity.md`; screenshots: n/a (no UI change)

**COA-2.4 · #7047 Bundle and dereference options**
- **Problem:** Remote `$ref`s are merged on import and fileset bundling exists, but there is no user-facing choice on export (single bundled file, fully dereferenced, or split by path/schema), and no open issue covers it.
- **Solution/Scope:**
- Export options `bundle`, `dereference` (with a cycle policy) and `split`, in REST, CLI (`apiome export --refs`) and Export studio.
- Circular references are reported, never expanded forever.
- **Acceptance Criteria:**
- Each mode round-trips on the corpus; cycles produce a documented result.
- **Parallelism/Dependencies:** After COA-2.1.
- **Technical Stack:** apiome-rest, apiome-cli, apiome-ui
- **Documentation:** `ship/export-a-spec.md`, `ship/export-studio.mdx`; screenshots: export-refs-options

**COA-2.5 · #7048 OpenAPI 3.2 in Projects: QUERY, additionalOperations, tags, streaming**
- **Problem:** The model carries the `query` method, `additionalOperations` and the tag hierarchy, but the Projects UI offers no way to create or inspect them, and 3.2 media-type additions (`itemSchema`, sequential media types) and the `querystring` parameter have no surface.
- **Solution/Scope:**
- Operation editor: QUERY and custom methods; tag parent/summary/kind editor.
- Responses/request bodies: streaming media types with `itemSchema`.
- Parameters: `in: querystring`.
- Docs preview and diff show them; version-aware: hidden when the project targets 3.0/3.1.
- **Acceptance Criteria:**
- A 3.2 project round-trips through the UI with each construct; a 3.1 project does not show them.
- **Parallelism/Dependencies:** After COA-2.1.
- **Technical Stack:** apiome-ui, apiome-rest
- **Documentation:** `build/` operation and tag pages; screenshots: openapi32-operations, openapi32-tags

**COA-2.6 · #7049 Spec upgrade assistant (2.0 → 3.0 → 3.1 → 3.2)**
- **Problem:** Downgrade exists (`openapi_downgrade.py`); a user holding Swagger 2.0 or OpenAPI 3.0 specs has no guided upgrade to 3.1/3.2.
- **Solution/Scope:**
- Plan-then-apply: show every change (nullable → type arrays, `example` → `examples`, Swagger 2 body/formData → requestBody …), apply as a new version.
- `apiome upgrade --to 3.2`.
- **Acceptance Criteria:**
- The plan lists every change; applying creates a version; a downgrade of the result matches the original on the corpus.
- **Parallelism/Dependencies:** After COA-2.3.
- **Technical Stack:** apiome-rest, apiome-ui, apiome-cli
- **Documentation:** `build/` upgrade page; screenshots: n/a (no UI change)

**COA-2.7 · #7050 Overlay manager in Versions**
- **Problem:** Overlay 1.0–1.2 is applied in `openapi_overlay.py` with provenance, stored overlays and export-with-overlay exist, but a user cannot manage them in the app (UI surface unconfirmed).
- **Solution/Scope:**
- Versions → **Overlays**: stored overlays, an action list with per-target match counts, a before/after diff preview, apply as a version, export with overlay.
- Show per-value provenance.
- **Acceptance Criteria:**
- Create an overlay with an `update`, a `remove` and a `copy` action, preview the diff, apply it.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-ui, apiome-rest
- **Documentation:** `build/overlays.mdx` (new); screenshots: overlays-list, overlay-preview

**COA-2.8 · #7051 `$ref` hygiene: refresh, cycles and external-ref policy in the UI**
- **Problem:** External-ref scan and policy exist for repositories; users have no per-project view of what a spec pulls from outside and when it was last fetched.
- **Solution/Scope:**
- A **References** panel: external refs, last fetch, status, cycle list; refresh and pin actions.
- **Acceptance Criteria:**
- A changed remote ref is detected and reported as a diff.
- **Parallelism/Dependencies:** After COA-2.4.
- **Technical Stack:** apiome-ui, apiome-rest
- **Documentation:** `build/` references page; screenshots: project-references

### COA-EPIC-3 · [#7035](https://github.com/apiome/apiome/issues/7035) — Import and export fidelity

Close the silent-loss, scalar-leak and re-import gaps left from RC7 and triage the deferred export tickets, so every catalog import and export is honest and current.

| Issue | Title | Summary | Labels | Par | MVP | Cx | Modules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| COA-3.1 · [#7052](https://github.com/apiome/apiome/issues/7052) | Silent-loss ledger burn-down | Reduce the 628 remaining silent-loss pairs in the export conformance ledger | `enhancement`, `rest`, `mvp` | N | Y | L | apiome-rest |
| COA-3.2 · [#7053](https://github.com/apiome/apiome/issues/7053) | IDL scalar-name leaks and Avro int64 narrowing | Stop foreign scalar names leaking into asn1, corbaidl, flatbuffers, typespec, wsdl and xsd output; fix Avro int64 → int (#6278) | `bug`, `rest`, `mvp` | Y | Y | M | apiome-rest |
| COA-3.3 · [#7054](https://github.com/apiome/apiome/issues/7054) | Re-import failures: wadl, asn1, asyncapi, postman, oncrpc, protobuf, connectrpc, corbaidl | Make export → re-import succeed (or fail honestly) for the eight formats that currently do not | `bug`, `rest`, `mvp` | Y | Y | M | apiome-rest |
| COA-3.4 · [#7055](https://github.com/apiome/apiome/issues/7055) | Validators for the 14 "not applicable" export targets | Add a validator per target where one exists; show "not validated" where none does | `enhancement`, `rest`, `v2` | Y | N | M | apiome-rest |
| COA-3.5 · [#7056](https://github.com/apiome/apiome/issues/7056) | Sign-offs owed on closed export tickets #6223, #6227, #6229 | Verify the three closed tickets against their acceptance criteria and record the result | `documentation`, `mvp` | Y | Y | S | apiome-ui, apiome-docs |
| COA-3.6 · [#7057](https://github.com/apiome/apiome/issues/7057) | Triage the deferred export tickets and the "not planned" list | Check the state of every RC7/RC8 export ticket; close the not-planned ones with the stated reason; ticket what remains | `documentation`, `mvp` | Y | Y | S | docs |

**COA-3.1 · #7052 Silent-loss ledger burn-down**
- **Problem:** `tests/export_conformance_ledger.py` still lists 628 source→target pairs with unexplained loss (RC7_CATALOG_IMPORT_EXPORT §0.1).
- **Solution/Scope:**
- Rank pairs by usage; for each, fix, report as a loss category or mark not applicable.
- The ledger only shrinks (ratchet test).
- **Acceptance Criteria:**
- Pair count falls by an agreed target each batch; no new pair appears.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-fidelity.md`; screenshots: n/a (no UI change)

**COA-3.2 · #7053 IDL scalar-name leaks and Avro int64 narrowing**
- **Problem:** Emitters pass canonical scalar names through unmapped in several IDL targets, and Avro narrows int64.
- **Solution/Scope:**
- Map every canonical scalar per target with a table test; narrowing becomes a reported loss or a `long`.
- **Acceptance Criteria:**
- Table tests cover every scalar × target.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-fidelity.md`; screenshots: n/a (no UI change)

**COA-3.3 · #7054 Re-import failures: wadl, asn1, asyncapi, postman, oncrpc, protobuf, connectrpc, corbaidl**
- **Problem:** RC7 §0.1 lists re-import failures for these eight formats.
- **Solution/Scope:**
- Reproduce each, fix or document, and add each to the round-trip corpus.
- **Acceptance Criteria:**
- Each format round-trips or has a strict xfail naming a ticket.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-fidelity.md`; screenshots: n/a (no UI change)

**COA-3.4 · #7055 Validators for the 14 "not applicable" export targets**
- **Problem:** 14 targets report the validator as "not applicable", which reads as a pass.
- **Solution/Scope:**
- Integrate an available validator per target, or make the UI and report say "not validated".
- **Acceptance Criteria:**
- No target shows validated without a validator.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-rest
- **Documentation:** `ship/export-studio.mdx`; screenshots: n/a (no UI change)

**COA-3.5 · #7056 Sign-offs owed on closed export tickets #6223, #6227, #6229**
- **Problem:** Three tickets closed with a sign-off still owed (X2, X6, X8).
- **Solution/Scope:**
- Walk each ticket's criteria in the running app; file defects for any miss; comment the result.
- **Acceptance Criteria:**
- Each ticket has a recorded sign-off or a follow-up issue.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-ui, apiome-docs
- **Documentation:** none; screenshots: n/a (no UI change)

**COA-3.6 · #7057 Triage the deferred export tickets and the "not planned" list**
- **Problem:** RC7 appendices hold ~86 deferred export tickets and RC8_PLAN §4 lists formats "considered, not planned"; many are closed, the docs lag GitHub.
- **Solution/Scope:**
- Produce one table: ticket, state, decision (do / close / later). Close the §4 tickets with a comment. Open tickets for the ranked targets still wanted (TS types-only, Zod, Bruno/Insomnia v5, Google Cloud API Gateway, Protobuf Editions, Tyk OAS, OData V2).
- **Acceptance Criteria:**
- Every listed ticket has a decision; the plan docs are corrected.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** docs
- **Documentation:** none; screenshots: n/a (no UI change)

### COA-EPIC-4 · [#7036](https://github.com/apiome/apiome/issues/7036) — Catalog and Projects cleanup

Docs that contradict the code, Catalog/Projects path parity, a usability audit and the demo scripts.

| Issue | Title | Summary | Labels | Par | MVP | Cx | Modules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| COA-4.1 · [#7058](https://github.com/apiome/apiome/issues/7058) | Docs truth pass for Catalog, Projects, OpenAPI and Arazzo | Remove every statement that contradicts the code | `documentation`, `mvp` | Y | Y | S | apiome-docs |
| COA-4.2 · [#7059](https://github.com/apiome/apiome/issues/7059) | Catalog ↔ Projects path parity | Check that formats built "on the Projects path" also behave on the Catalog path, and the reverse | `enhancement`, `rest`, `ui`, `mvp` | Y | Y | M | apiome-rest, apiome-ui |
| COA-4.3 · [#7060](https://github.com/apiome/apiome/issues/7060) | Projects and Catalog usability audit | Walk the core journeys end to end and file every defect | `enhancement`, `ui`, `mvp` | Y | Y | M | apiome-ui |
| COA-4.4 · [#7061](https://github.com/apiome/apiome/issues/7061) | Demo scripts: Arazzo workflows and OpenAPI 3.2 | Two five-minute demo-video scripts as GitHub issues | `documentation`, `mvp` | Y | Y | S | docs |

**COA-4.1 · #7058 Docs truth pass for Catalog, Projects, OpenAPI and Arazzo**
- **Problem:** Known contradictions: "Arazzo 1.0" claims, "workflows are not stored as records", the format support matrix §7 ("no Arazzo 1.1", "no Overlay lint"), and format-coverage statements that name only the Projects path.
- **Solution/Scope:**
- Read the Bring in, Build and Ship pages for these formats against the code; correct them; regenerate the matrix from the registry rather than by hand.
- **Acceptance Criteria:**
- A reviewer finds no contradiction on a sample of 20 statements.
- **Parallelism/Dependencies:** Parallel with COA-1.1.
- **Technical Stack:** apiome-docs
- **Documentation:** `bring-in/*`, `build/*`, `ship/export-*`; screenshots: n/a (no UI change)

**COA-4.2 · #7059 Catalog ↔ Projects path parity**
- **Problem:** RC7 §3.2 builds OA3–OA6 and AZ2 on the Projects path; whether the Catalog path gives the same result is not asserted.
- **Solution/Scope:**
- A parity test importing each format both ways and comparing the canonical output; fix or document each difference.
- **Acceptance Criteria:**
- Parity table in the docs; no unexplained difference.
- **Parallelism/Dependencies:** After COA-2.1.
- **Technical Stack:** apiome-rest, apiome-ui
- **Documentation:** `bring-in/catalog.mdx`, `bring-in/import-a-spec.md`; screenshots: n/a (no UI change)

**COA-4.3 · #7060 Projects and Catalog usability audit**
- **Problem:** RC8 narrowed to Catalog and Projects; the journeys (import → project → version → publish → export) have not had one end-to-end review since the facelift.
- **Solution/Scope:**
- Run the catalog/project journey specs and a manual pass on 1440×900 and 1024 wide, light and dark; list defects by severity; fix the small ones in the audit PR and ticket the rest into this release.
- **Acceptance Criteria:**
- A written defect list; every S1/S2 ticketed.
- **Parallelism/Dependencies:** None.
- **Technical Stack:** apiome-ui
- **Documentation:** none; screenshots: n/a (no UI change)

**COA-4.4 · #7061 Demo scripts: Arazzo workflows and OpenAPI 3.2**
- **Problem:** Demo scripts live in issues (not files). #6706 already covers catalog import/export.
- **Solution/Scope:**
- Script 1: import an Arazzo workflow with its OpenAPI files, view the workflow graph, run it (if COA-1.7 lands). Script 2: author a 3.2 QUERY operation, upgrade a 3.0 spec, apply an overlay.
- **Acceptance Criteria:**
- Both scripts follow the house shape (goal, before you record, timed table, risky spots, done-when).
- **Parallelism/Dependencies:** After COA-1.3 and COA-2.5.
- **Technical Stack:** docs
- **Documentation:** none; screenshots: n/a (no UI change)

## 5. Work to be done, in order

1. **Quick wins and the truth pass (parallel):** COA-1.1 · COA-2.2 · COA-4.1 · COA-3.5 · COA-3.6.
2. **Foundations:** COA-2.1 (construct audit) · COA-1.5 (workflow records) · COA-1.2 (Arazzo filesets) · COA-4.3 (usability audit).
3. **Fidelity and options:** COA-1.4 · COA-2.3 · COA-2.4 · COA-2.7 · COA-4.2 · #5879 · #5880.
4. **Surfaces and burn-down:** COA-1.3 · COA-2.5 · COA-3.1 · COA-3.2 · COA-3.3 · governance epics #5875 and #5868 (+ #5869–#5872).
5. **Demos and delivery:** COA-4.4 · #6706 · #6654.
6. **V2:** COA-1.6 · COA-2.6 · COA-2.8 · COA-3.4 · COA-1.7.

Each issue follows AGENTS.md: OpenAPI version bump for REST changes, package bumps, docs in the same PR with regenerated screenshots, a release note, and `yarn docs:check`.
