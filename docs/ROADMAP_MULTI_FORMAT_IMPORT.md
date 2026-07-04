# Roadmap — Multi-Format API Import & Cataloging

> **Status:** ✅ **Issues filed on `objectified-project/objectified`** — umbrella **#3715**,
> epics **#3716–#3732** (MFI-EPIC-1…17), and 80 issues **#3733–#3812** (98 total). Epic/issue
> headings below carry their `#number`; epics track their children as GitHub sub-issues under
> umbrella #3715. (33 table-only abbreviated issues were filed with bodies synthesized from the
> epic adapter-template; their numbers are in the epic task-lists on GitHub.)
> **Issue ID prefix:** `MFI` (Multi-Format Import). Epics `MFI-EPIC-n`, issues `MFI-n.m`.
> **GitHub title format:** `apiome: [<epic>.<issue>] <title>`.
> **Recommended labels:** new `roadmap-multi-format` + reuse `multi-protocol`, `import`,
> `integrations`, `rest`, `ui`, `database`, `python`, `typescript`, `linting`,
> `version-control`, `browser`, `registry`, `validation` (+ optional per-format labels).
>
> **Update (2026-07-03 — gap analysis, §0.3):** adds **MFI-EPIC-29…32** (intake hardening ·
> OpenAPI-family completeness · live-source re-discovery · collections & captured traffic),
> **MFI-6.4** (cross-format API identity), and the **§9.7** candidate formats. **Filed
> 2026-07-03:** epics **#4384–#4387**, issues **#4388–#4409**, **MFI-6.4 #4410** (under epic
> #3721); the §9.7 candidates remain unfiled. **MFI-22.7** is promoted to MVP (matching the §5
> work order); UI dry-run **MFI-26.4** is promoted to MVP in `ROADMAP_MULTI_FORMAT_IMPORT_UI.md`.

---

## 0. Source description (request, verbatim)

> Multi-Format API Import & Cataloging — make Apiome an extremely powerful cataloging
> and versioning tool for many API description formats, not just OpenAPI/Swagger/Arazzo/
> JSON-Schema/Postman (and the new MCP import). Produce ONE consolidated roadmap file:
> `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`.
>
> Scope: add new IMPORT SOURCES (ingestion) for these 10 additional formats, each cataloged
> + versioned + diffable + lint/scored + browsable exactly like existing specs: **AsyncAPI,
> gRPC/Protocol Buffers, GraphQL, SOAP/WSDL, TypeSpec, OData, RAML, API Blueprint, Avro/
> Schema Registry, Smithy.** Structure as SHARED-FOUNDATION epics + one epic per format
> (parser, normalizer to a common model, format-specific lint/score rules, fixtures, a UI
> source card + CLI command, plus any live-discovery path). Heavily reuse the MCP catalog
> roadmap (V2-MCP-EPIC-15…27, umbrella #3637), `spec_import_engine`, `schema_lint`, the
> `versions`/`quality_*` columns, `apiome-browse`, `ImportDialog`, `DashboardSideNav`,
> the CLI, and Flyway migrations. Cross-link existing multi-protocol epics (#3489, #3496);
> do not duplicate. Document only — do not create issues.

### 0.1 Update request — Catalog → OpenAPI conversion & fidelity preview (verbatim)

> Update the `docs/ROADMAP_MULTI_FORMAT_IMPORT.md` to include the functionality to take an
> imported catalog and convert it to a project/version that is an OpenAPI Specification, if the
> imported object in the catalog isn't already one. When importing and converting, there needs to
> be a preview screen that shows what the data currently provides, and where it will be missing
> data that an OpenAPI specification might favor for completeness. Warn the user that the fidelity
> of the original API may not be complete enough to create a fully defined OpenAPI Specification.

This update adds **MFI-EPIC-22 — Catalog → OpenAPI Conversion & Fidelity Preview** (issues 22.1–22.8 — **filed #4002–#4009 under epic #4000**). It turns the canonical model (MFI-EPIC-2) into an
**OpenAPI 3.1 emitter** with a **completeness gap analyzer** and a **preview/confirm screen** that
shows, side by side, *what the source provides* vs *what an OpenAPI spec favors but the source
cannot supply* — fronted by an explicit **fidelity warning**. It also consolidates the previously
scattered "migrate-to-OpenAPI" off-ramps (RAML **15.5**, API Blueprint **16.4**, WADL §9.3) under
one engine. See **MFI-EPIC-22** below and the work-order/risk additions in §5/§6.

### 0.2 Update request — Catalog screen for non-publishable imported items (verbatim)

> Modify the same catalog roadmap so that when importing data into Apiome that is not OpenAPI,
> but is OpenAPI-worthy, the data is collected in a "Catalog" screen in the UI. Cataloged items are
> not candidates for publishing because they may be incomplete. Cataloged information in the screen
> should include the cataloged item that was imported, along with a pill that shows the format of
> the file that was imported, along with the source material, etc, like the current Projects screen
> shows. These projects may be visible using the Designer at some point, but they need to be
> cataloged in such a way that they can be viewed, linted, and so on, through the same type of
> screen that the projects screen provides.

This update adds **MFI-EPIC-23 — Catalog Screen & Non-Publishable Cataloged Items** (issues 23.1–23.12 — **filed #4010–#4021 under epic #4001**). It gives non-OpenAPI-but-OpenAPI-worthy imports a home: a
**Catalog screen** that mirrors the existing Projects dashboard (card/table, filter/sort/search,
lint-grade + quality orbs) but for **non-publishable** items, each carrying a **format pill** and
**source-material/provenance** metadata. Catalog items are viewable and lintable through the same
screens as Projects, may later open read-only in the Designer, and are promoted out of the catalog
into a publishable OpenAPI Project via the **MFI-EPIC-22** convert + fidelity-preview flow.
EPIC-23 is the **staging surface**; EPIC-22 is the **promotion path**. See **MFI-EPIC-23** below.

### 0.3 Update request — Gap-analysis additions (verbatim)

> Fold in the gap-analysis results: MVP additions (multi-file/zip intake under EPIC-1, Swagger 2.0/
> Arazzo adapter cleanup, OpenAPI 3.2 support, promote 26.4 dry-run and 22.7 passthrough to MVP),
> new v2 epics (live-source re-discovery & drift alerts; Collections & Captured Traffic:
> HAR/Insomnia/Bruno), remote $ref resolution, git-repo intake, cross-format API identity,
> registry-crawl throttling, secret scrubbing, and §9 format additions (Google Discovery, GraphQL
> Federation, .http/cURL, K8s CRDs, LLM tool schemas, OpenAPI Overlays, WIT, gateway configs).

This update (2026-07-03) came out of a walkthrough/gap analysis of the shipped MVP. It adds:

- **MFI-EPIC-29 — Ingestion Intake Hardening** · **#4384** (archives/multi-file, git-repo intake, remote
  `$ref` resolution, bulk import, secret scrubbing). The MVP slice (29.1/29.2) exists because a
  *shipped MVP format* — gRPC — is multi-file in every real-world repo, yet the intake accepts
  only a single file/URL/paste.
- **MFI-EPIC-30 — OpenAPI-Family Adapter Completeness** · **#4385** (Swagger 2.0 canonical normalizer, an
  Arazzo `ImportSource` adapter, OpenAPI 3.2 support). MVP-cleanup: these formats are advertised
  as importable/publishable today but bypass or break the canonical pipeline.
- **MFI-EPIC-31 — Live-Source Re-Discovery & Drift Alerts** · **#4386** (v2): the scheduled re-crawl +
  breaking-change notification layer that the MCP catalog (the template for this roadmap) already
  has and this roadmap omitted.
- **MFI-EPIC-32 — Collections & Captured Traffic** · **#4387** (v2): HAR, Insomnia, Bruno (+ Postman behind
  the SPI) — the *observed/collected* API-description family, previously covered only in the
  export roadmap.
- **MFI-6.4** (**#4410**) cross-format API identity, **MFI-22.7** promoted to MVP, UI **MFI-26.4** promoted to
  MVP (tracked in `ROADMAP_MULTI_FORMAT_IMPORT_UI.md`), and the **§9.7** format candidates.

---

## 1. Goal & strategy

Today apiome ingests **OpenAPI / Swagger / Arazzo / JSON-Schema / Postman** (and, per the
MCP roadmap, **MCP servers**). This roadmap makes the import + catalog + version + diff +
lint + browse pipeline **format-pluggable**, then adds **10 formats** spanning every major API
paradigm:

```
REST-ish:    OData · RAML · API Blueprint           (+ existing OpenAPI/Swagger)
RPC:         gRPC/Protobuf · Smithy
Graph:       GraphQL
Event-driven: AsyncAPI
Design-IDL:  TypeSpec  (compiles to OpenAPI/JSON-Schema/Protobuf)
Data schema: Avro / Confluent Schema Registry
```

**Core insight (from research):** every format wants the same shape of treatment —
*parse → resolve/dereference → normalize to a canonical model → fingerprint → diff any two
versions → lint/score → catalog/browse.* Only the **parser**, the **normalizer**, the
**lint rule-pack**, and the **breaking-change rules** are format-specific. So the bulk of the
work is **shared foundation built once**, then a thin, repeatable **per-format adapter**.

### What already exists that we REUSE (do not rebuild)

| Capability | Where | Reuse for |
|---|---|---|
| Async import job engine (submit→poll→commit) | `spec_import_engine.py`, `spec_import_routes.py` | Per-format ingestion jobs |
| Import wizard (3-col source-card grid) | apiome-ui `ImportDialog.tsx` | New source cards per format |
| Deterministic linter (findings + 0–100 + A–F + fingerprint) | `schema_lint.py`, `lint_routes.py` | Lint engine + per-format rule packs |
| Versioning + git-like tags + quality columns | `versions`, `version_tags`, `versions.quality_*` (V124) | Generalized versioning |
| **MCP catalog patterns** (import-source, fingerprint/diff, compare-any-two, lint, browse) | `ROADMAP_MCP_CATALOGING.md` · V2-MCP-EPIC-15…27 · umbrella **#3637** | Direct template for this whole roadmap |
| Public browse + read views | `browse_public_routes.py`, `apiome-browse` | Browse by protocol/format |
| Typer CLI + import commands + job polling | `apiome-cli` | Per-format CLI sources |
| Flyway migrations (`apiome`, UUID PKs, tenant scoping, soft delete) | `apiome-db/scripts` | Schema additions |

### Existing GitHub issues to RECONCILE / cross-link (avoid duplication)

| Format | Existing issues | This roadmap's relationship |
|---|---|---|
| AsyncAPI | **#1438** [Epic] AsyncAPI & Event-Driven Arch · **#2772** REPO-3.3 AsyncAPI importer · #1447 visual editor · #236/#222 (closed) | We provide the **catalog/version/diff/lint/browse** layer; the importer (#2772) is the parser feeding it. Link, don't duplicate. |
| GraphQL | **#1331** [Epic] GraphQL Schema Design · **#2775** REPO-3.6 GraphQL SDL importer · #1342/#1365/#1462 | Same — consume the SDL importer; add introspection discovery + diff/lint/catalog. |
| gRPC/Protobuf | **#1384** [Epic] gRPC & Protobuf Support · #1409 editor · #1427 testing/breaking-change · #1400 designer · #238 (closed) | #1427 overlaps breaking-change; coordinate. We add descriptor-set normalize + catalog. |
| Avro | **#239** Import from Avro · **#2776** REPO-3.7 Protobuf/Avro importer | Add Schema Registry discovery + compatibility-mode diff + catalog. |
| Schema registry / discovery | **#3489** [Epic] Schema Registry & Discovery · **#3496** [Epic] Community & Schema Browser · #624 | Strong overlap for browse/registry; **align EPIC-5/6/MFI-EPIC-12** with #3489/#3496. |
| RAML | #237 (closed import) | Legacy import + migrate-to-OpenAPI. |
| SOAP/WSDL, OData, TypeSpec, Smithy, API Blueprint | *(none found)* | **Net-new.** |

> **Recommendation:** open this as a **`roadmap-multi-format`** umbrella that links the existing
> format epics (#1438, #1331, #1384, #3489, #3496) as related, and positions these issues as the
> *cataloging engine* rather than re-spec'ing importers/editors already tracked.

### The gaps this roadmap closes

1. Import/catalog is **hard-wired to OpenAPI-family**; no plug-in seam for new formats.
2. No **paradigm-agnostic normalized model** so versioning/diff/lint/browse work uniformly across REST/RPC/event/graph/data-schema.
3. No **polyglot toolchain runner** — many best-of-breed parsers/linters are JS/JVM/native (buf, tsp, AMF, drafter, smithy, AsyncAPI CLI), not Python.
4. No **per-format breaking-change / compatibility** engine (incl. Avro Schema-Registry compat modes, Buf wire-compat, GraphQL/Smithy diff).
5. No **browse/search by protocol/format**.

---

## 2. MVP definition

**MVP (v1) — "the plug-in framework proven across 3 paradigms":**

1. **Import-source plug-in framework** (MFI-EPIC-1): formats register as sources; `ImportDialog` renders them dynamically; CLISource dispatch; format auto-detect.
2. **Normalized internal API model** (MFI-EPIC-2) covering REST/RPC/event/graph, with persistence.
3. **Generalized versioning + fingerprint + compare-any-two diff** (MFI-EPIC-3), reusing the MCP `EPIC-18` work.
4. **Generalized lint/score + rule-pack SPI** (MFI-EPIC-4), reusing `schema_lint`.
5. **Polyglot toolchain runner** (MFI-EPIC-5) — sandboxed subprocess to run JS/JVM/native parsers/linters.
6. **DB additions** (MFI-EPIC-7) and **browse-by-protocol** (MFI-EPIC-6).
7. **Three first formats proving the seam across paradigms:** **AsyncAPI** (event), **GraphQL** (graph + live introspection), **gRPC/Protobuf** (RPC + live reflection). *(MFI-EPIC-8/9/10)*
8. **Intake hardening — MVP slice** (MFI-29.1/29.2): archive (zip/tar) upload + multi-document
   adapter inputs, so a proto tree with imports, a split GraphQL SDL, or an AsyncAPI suite is
   actually importable through the UI/REST/CLI (today: single file/URL/paste only).
9. **OpenAPI-family completeness** (MFI-EPIC-30): Swagger 2.0 canonical normalizer (closes the
   "detect says importable, normalize raises" gap left open by MFI-1.1), an Arazzo `ImportSource`
   adapter, and **OpenAPI 3.2** detection/normalization/publishability.
10. **OpenAPI-native passthrough** (MFI-22.7, promoted): the §5 work order already says "ship
    22.7 first"; the MVP flag now matches. Its UI counterpart, the import dry-run preview
    (MFI-26.4), is promoted to MVP in `ROADMAP_MULTI_FORMAT_IMPORT_UI.md`.

**v2 / later:** OData, Avro/Schema-Registry (live registry crawl), **Collections & Captured
Traffic (MFI-EPIC-32: HAR/Insomnia/Bruno)**, SOAP/WSDL, TypeSpec, then the legacy/niche set RAML,
API Blueprint (legacy import + migrate-to-OpenAPI), and Smithy. Cross-cutting v2: **live-source
re-discovery & drift alerts (MFI-EPIC-31)** — sequenced with the first registry-crawl format
(EPIC-12) — plus git-repo intake (29.3), remote `$ref` resolution (29.4), bulk import (29.5),
secret scrubbing (29.6, mandatory before EPIC-32 ships), and cross-format API identity (6.4).

---

## 3. Epics overview

| Epic | Theme | Issues | MVP |
|---|---|---|---|
| MFI-EPIC-1 | Import-Source Plug-in Framework | 1.1–1.5 | ●●● |
| MFI-EPIC-2 | Normalized Internal API Model | 2.1–2.4 | ●●● |
| MFI-EPIC-3 | Versioning, Fingerprint & Compare/Diff (generalized) | 3.1–3.4 | ●●● |
| MFI-EPIC-4 | Lint/Score Engine + Rule-Pack SPI | 4.1–4.4 | ●●● |
| MFI-EPIC-5 | Polyglot Toolchain Runner | 5.1–5.3 | ●●● |
| MFI-EPIC-6 | Browse/Search & Categorization by protocol | 6.1–6.3 | ●● |
| MFI-EPIC-7 | DB model & persistence additions | 7.1–7.3 | ●●● |
| MFI-EPIC-8 | **AsyncAPI** (event-driven) | 8.1–8.5 | ●● MVP |
| MFI-EPIC-9 | **gRPC / Protocol Buffers** (RPC) | 9.1–9.6 | ●● MVP |
| MFI-EPIC-10 | **GraphQL** (graph) | 10.1–10.6 | ●● MVP |
| MFI-EPIC-11 | OData (queryable REST) | 11.1–11.6 | ○ v2 |
| MFI-EPIC-12 | Avro / Confluent Schema Registry | 12.1–12.6 | ○ v2 |
| MFI-EPIC-13 | SOAP / WSDL (+XSD) | 13.1–13.6 | ○ v2 |
| MFI-EPIC-14 | TypeSpec | 14.1–14.5 | ○ v2 |
| MFI-EPIC-15 | RAML (legacy) | 15.1–15.5 | ○ v2 |
| MFI-EPIC-16 | API Blueprint (legacy) | 16.1–16.4 | ○ v2 |
| MFI-EPIC-17 | Smithy | 17.1–17.5 | ○ v2 |
| **MFI-EPIC-22** | **Catalog → OpenAPI Conversion & Fidelity Preview** | 22.1–22.8 | ◐ conv-MVP |
| **MFI-EPIC-23** | **Catalog Screen & Non-Publishable Cataloged Items** | 23.1–23.12 | ◐ catalog-MVP |
| MFI-EPIC-28 | Catalog UX & Look-and-Feel Improvements | 28.1–28.8 | ○ polish |
| **MFI-EPIC-29** | **Ingestion Intake Hardening** (archives/git/remote $refs/bulk/scrub) | 29.1–29.6 | ◐ 29.3 MVP |
| **MFI-EPIC-30** | **OpenAPI-Family Adapter Completeness** (Swagger 2.0 · Arazzo · OAS 3.2) | 30.1–30.4 | ●●● MVP-cleanup |
| MFI-EPIC-31 | Live-Source Re-Discovery & Drift Alerts | 31.1–31.5 | ○ v2 |
| MFI-EPIC-32 | Collections & Captured Traffic (HAR · Insomnia · Bruno · Postman-SPI) | 32.1–32.7 | ○ v2 |

**Total: 24 epics in the main set (1–17, 22, 23, 28–32), ~125 issues** — plus the post-MVP
candidate epics 18–21 in §9. *(MFI-EPIC-22 depends on the foundation epics 2/3/4; MFI-EPIC-23 is
the UI/UX surface for non-OpenAPI imports and depends on the model/persistence (EPIC-2/7) and the
import framework (EPIC-1), and integrates EPIC-22 as its promotion path. EPIC-24…27 are the UI
mockup-parity epics tracked in `ROADMAP_MULTI_FORMAT_IMPORT_UI.md`. **EPIC-29…32 are the 2026-07
gap-analysis additions — filed as epics #4384–#4387 with issues #4388–#4409 (+ MFI-6.4 #4410).**)*

### Discovery tiers (drives ingestion design)

```mermaid
flowchart TB
  subgraph live[LIVE discovery — crawl a running endpoint]
    G[GraphQL introspection __schema]
    R[gRPC Server Reflection]
    O[OData $metadata + service doc]
    A[Avro Confluent Schema Registry REST]
  end
  subgraph file[FILE / build-time only]
    AA[AsyncAPI doc]
    W[WSDL ?wsdl / ?singleWsdl fetch]
    T[TypeSpec tsp compile -> OpenAPI/Protobuf]
    RA[RAML resolve includes via AMF]
    AB[API Blueprint drafter -> refract]
    SM[Smithy build -> JSON AST]
  end
  live --> NORM[Normalize -> canonical model -> fingerprint]
  file --> NORM
  NORM --> CAT[Version - Diff - Lint - Browse]
```

---

## 4. Architecture

```mermaid
flowchart LR
  subgraph ui[apiome-ui]
    ID[ImportDialog\ndynamic source cards]
  end
  CLI[apiome-cli\nimport sources]
  subgraph rest[apiome-rest]
    REG[Import-Source Registry\nSPI]
    JOB[spec_import job engine\nreused + generalized]
    RUN[Polyglot Toolchain Runner\nbuf/tsp/AMF/drafter/smithy/asyncapi/rover]
    NORM[Normalizer SPI\nformat -> common model]
    FP[Fingerprint + Diff\ncompare any two]
    LINT[Lint/Score + rule packs]
  end
  subgraph db[apiome-db apiome]
    SRC[(import source_format/protocol)]
    MODEL[(normalized api model tables)]
    VER[(versions + quality_*)]
  end
  BROWSE[apiome-browse\nfacet by protocol]

  ID & CLI --> REG --> JOB
  JOB --> RUN --> NORM --> MODEL
  NORM --> FP --> VER
  NORM --> LINT --> VER
  MODEL --> BROWSE
```

---

# Epics & issues

> Complexity ∈ {S, M, L, XL}. Each format epic follows the same adapter template:
> **parse → normalize → (discover) → lint pack → diff/breaking → UI+CLI source & fixtures.**

---

## MFI-EPIC-1 — Import-Source Plug-in Framework  ·  **#3716**

Generalize the existing import flow so a format is added by *registering a source*, not editing
the wizard/engine. This is the seam the whole roadmap hangs on.

```mermaid
flowchart LR
  R[ImportSource registry] --> D{detect/select}
  D --> P[parse via adapter]
  P --> N[normalize] --> J[commit version]
  R -. exposes .-> UI[source cards] & CLI[cli verbs]
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 1.1 ✅ | ImportSource SPI & registry | define adapter interface (detect/parse/normalize/lint/diff) + registry | multi-protocol,rest,python,mvp | N | Y | L | apiome-rest |
| 1.2 ✅ | Generalize spec-import job pipeline | make `spec_import_engine` format-agnostic via adapters | multi-protocol,rest,python,mvp | N | Y | L | apiome-rest |
| 1.3 | Dynamic source cards in ImportDialog | render registered sources (icon/label/input panel) | multi-protocol,ui,typescript,mvp | Y | Y | M | apiome-ui |
| 1.4 ✅ | CLI source dispatch | `apiome import <format>` resolves to adapters | multi-protocol,devex,python,mvp | Y | Y | M | apiome-cli |
| 1.5 ✅ | Format auto-detection | sniff format from content/extension/headers (extend `import auto`) | multi-protocol,rest,validation,mvp | Y | Y | M | apiome-rest |

### MFI-1.1 — ImportSource SPI & registry  ·  **#3733**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/import_source.py` (the `ImportSource` ABC + descriptor metadata + by-key registry + shared canonical fingerprint/diff and lint-report defaults), `apiome-rest/src/app/openapi_import_source.py` (the reference adapter — the existing OpenAPI/Swagger path refactored behind the SPI: `parse` reuses the pipeline's JSON/YAML loader, `normalize` delegates to the registered `OpenApiNormalizer`, `lint` delegates to `schema_lint.lint_openapi_spec`, fingerprint/diff use the canonical defaults), and `apiome-rest/src/app/sample_import_source.py` (the no-op acceptance adapter). The SPI carries `detect(payload) → DetectionResult` (confidence), `parse(raw) → native_ast`, `normalize(native_ast) → CanonicalApi`, and canonical-level `fingerprint`/`diff`/`lint`, plus descriptor metadata (key, label, icon, paradigm, input kinds file/url/paste/discovery, live-discovery capability, emitted formats). The registry (`register_import_source`/`get_import_source`/`available_import_sources`/`describe_import_sources`/`detect_import_source`, with a `register=True` subclass flag and lazy built-in loading) enumerates adapters for UI/CLI/REST — the source list. Detection recognizes both OpenAPI 3.x and Swagger 2.0; Swagger 2.0 *normalization* awaits its own normalizer (a later format epic) and raises a clear `ImportSourceError` until then. Wrapping is behavior-preserving (generalizing the job engine onto adapters is MFI-1.2). Documented in `apiome-rest/docs/import_source_spi.md`; tests in `tests/test_import_source.py` + `tests/test_openapi_import_source.py` (33 tests; full rest suite green, 1902 passed). apiome-rest 1.27.0 → 1.28.0.
- **Problem.** Each new format today would mean editing the import engine + wizard. There's no extension seam.
- **Solution / Scope.** Define an `ImportSource` adapter interface in `apiome-rest`: `detect(bytes/url) → confidence`, `parse(input) → native_ast`, `normalize(native_ast) → CanonicalApi` (EPIC-2), `fingerprint`, `diff(a,b)`, `lint(model)`; plus descriptor metadata (key, label, icon, paradigm, input kinds: file/url/paste/discovery, live-discovery capability). A registry enumerates adapters for UI/CLI/REST. Mirrors the MCP import-source decision (V2-MCP-EPIC-17/24.1).
- **Acceptance Criteria.** Existing OpenAPI/Swagger/Postman importers refactored behind the SPI with no behavior change; a no-op sample adapter registers and appears in the source list.
- **Dependencies / Parallelism.** Root of the roadmap. Blocks all format epics.
- **Technical Stack.** Python, FastAPI.

### MFI-1.2 — Generalize spec-import job pipeline  ·  **#3734**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/import_source_pipeline.py` (a new in-process driver, `run_adapter_import_job`, that runs any registered `ImportSource` through parse → normalize → version(fingerprint) → lint, publishing per-phase `SpecImportJobStatus` snapshots — events + percent + completed-job `summary` carrying the revision fingerprint, paradigm/format, entity counts, and lint score) and a refactor of `apiome-rest/src/app/spec_import_engine.py` (`_drive_job` now resolves `metadata.source_kind` against the registry via `_resolve_inprocess_adapter`: a non-worker adapter runs in-process through `_run_inprocess_adapter_job`; OpenAPI/Swagger — `_WORKER_BACKED_ADAPTER_KEYS = {"openapi"}` — and any unrecognized kind stay on the `apiome-ui` `tsx` worker, so the existing OpenAPI tests are unchanged). The contract (poll/commit/rollback), `dry_run`, and `incremental_mode` are preserved; the in-process path is preview-only (no catalog write — canonical→catalog persistence is a later format epic), so commit returns 409 for it. Adapter phase codes surface at INFO in the REST logs alongside the worker's. Tests in `tests/test_import_source_pipeline.py` (pipeline unit coverage: phases, snapshots, dry-run/incremental flags, deterministic fingerprint, parse/normalize failures, cancel) and `tests/test_spec_import_contract.py` (end-to-end `sample` adapter through the REST job API + job-list/cancel); full rest `tests/` suite green (1914 passed, 2 skipped). apiome-rest 1.28.0 → 1.29.0.
- **Problem.** `spec_import_engine.py` is OpenAPI-shaped; new formats need the same async job lifecycle.
- **Solution / Scope.** Refactor the submit→poll→commit/rollback engine to drive any `ImportSource` adapter (parse→normalize→version→lint), keeping the existing job status contract, dry-run, and incremental mode. Reuse the MCP discovery-job learnings.
- **Acceptance Criteria.** A format adapter runs end-to-end through the existing job API; OpenAPI import still passes its tests.
- **Dependencies / Parallelism.** After 1.1. Blocks format epics.
- **Technical Stack.** Python async.

### MFI-1.3 — Dynamic source cards in ImportDialog  ·  **#3735**  ·  ✅ **Done**
- **Status.** The `ImportDialog` source grid is now data-driven. A new authenticated REST route `GET /v1/import/sources` (`apiome-rest/src/app/import_sources_routes.py`) exposes the MFI-1.1 registry as `ImportSourceListResponse` (each adapter's `ImportSourceDescriptor`: key/label/description/Lucide `icon`/paradigm/`input_kinds`/live-discovery/`formats`). The UI proxies it via `apiome-ui/src/app/api/import/sources/route.ts`, and a pure catalog module (`apiome-ui/src/app/components/ade/dashboard/importSourceCatalog.ts`) **merges** the built-in cards (file/url/clipboard/git/swaggerhub/postman/mcp — unchanged) with the registry list: a descriptor becomes a new card unless its key is already a built-in or covered by one (`openapi` is handled by the generic file/url/paste intake; `sample` is the internal no-op adapter). Each registry card resolves its Lucide icon dynamically and routes to the generic intake panel implied by its `input_kinds` (file→file, url→url, paste→clipboard); a discovery-only adapter has no generic panel yet and renders disabled. The `useImportSources` hook fetches on dialog open and falls back to the built-ins if the registry is unreachable. So registering an adapter server-side makes a new card appear with no UI code change, and the existing cards are untouched. Tests: `apiome-rest/tests/test_import_sources_routes.py` (4) and `apiome-ui/tests/importSourceCatalog.test.ts` (15). apiome-rest 1.39.0 → 1.40.0; apiome-ui 0.24.0 → 0.25.0.
- **Problem.** The 3-col source grid is hard-coded; formats must self-register their card + input panel.
- **Solution / Scope.** Drive `ImportDialog` source cards from the registry (1.1) via a REST `GET /import/sources`; each card declares icon (Lucide), label, description, and which input panel (file/url/paste/discovery) it uses. Matches the MCP "MCP Server source card" pattern.
- **Acceptance Criteria.** Adding an adapter server-side makes a new card appear with no UI code change; existing cards unchanged.
- **Dependencies / Parallelism.** After 1.1. Parallel with 1.4.
- **Technical Stack.** Next.js, TanStack Query.

### MFI-1.4 — CLI source dispatch  ·  **#3736**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-cli`. The `import` Typer group is now a `DispatchImportGroup` (`src/apiome_cli/commands/import_.py`): a name that is not a dedicated verb (`openapi`/`swagger`/`arazzo`/`json-schema`/`json-schema-type`/`auto`) resolves to a generic adapter import, so a format registered server-side (the MFI-1.1 `ImportSource` registry) is invokable as `apiome import <format> <input>` with **no new command code**. `apiome import --list` enumerates the registry (`GET /v1/import/sources`, MFI-1.3's route) as a table or `--json`. The generic path (`src/apiome_cli/import_/sources.py` + `import_/source.load_document_bytes`) validates `<format>` against the live registry (typo → actionable "unknown format" with the available list), reads the document from an `INPUT` argument / `--file` / `--url` / stdin (exactly one), sends the bytes **verbatim** (so non-JSON/YAML formats survive), submits via the shared `POST /v1/tenants/{slug}/imports` job, and reuses `resolve_import_result` polling — surfacing the adapter's preview summary (source/paradigm/format, fingerprint, canonical entity counts, lint score). Shared flags `--file`/`--url`/`--dry-run`/`--import-timeout` (plus `--wait`/`--poll-interval` for poll parity); dedicated verbs keep their format-specific flags and take precedence. Tests: `tests/test_import_source_dispatch.py` (list + generic dispatch, unknown-format, input selection, precedence), `tests/test_import_sources_helpers.py`, and `load_document_bytes` cases in `tests/test_import_source.py`. README **Import sources (registry dispatch)** + AGENTS.md updated. apiome-cli 0.11.0 → 0.12.0 (pyproject).
- **Problem.** CLI import verbs are hard-coded per format.
- **Solution / Scope.** `apiome import <format> <input>` resolves the adapter from the registry; shared flags (`--url`, `--file`, `--dry-run`, `--import-timeout`); list available formats via `apiome import --list`.
- **Acceptance Criteria.** New adapter is invokable from CLI without new command code; polling/output consistent with current import.
- **Dependencies / Parallelism.** After 1.1. Parallel with 1.3.
- **Technical Stack.** Python, Typer.

### MFI-1.5 — Format auto-detection  ·  **#3737**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/format_detection.py`. `detect_format(DetectionInput) → FormatDetection` extends the MFI-1.1 detection seam: it ranks every registered `ImportSource.detect()` (importable matches, e.g. OpenAPI — via the new `detect_import_source_candidates` primitive in `import_source.py`) alongside cheap standalone marker sniffers for the formats whose full adapters land in later epics — `#%RAML`, `FORMAT: 1A` (API Blueprint), `$version`/`namespace` (Smithy vs TypeSpec, disambiguated by their distinctive markers), `<wsdl:definitions>`/`<edmx:Edmx>` (WSDL/OData), `asyncapi:` (AsyncAPI 2/3), `syntax = "proto3"` (protobuf), `{"type":"record"}` (Avro), and GraphQL root types / `schema {}`. Highest confidence wins; sniffer-only formats are reported `importable=False` so the importer can *name* the format without being able to import it yet; raw text is parsed once (best-effort JSON/YAML) so structured and text formats sniff uniformly; and when two formats tie within `DEFAULT_AMBIGUITY_MARGIN` the result is flagged `ambiguous` with the close candidate set so the caller prompts the user (e.g. a bare `namespace …` is Smithy-or-TypeSpec). The sniffers are intentionally **not** registered as no-op adapters, so the source list (UI cards / CLI `import --list`) is not polluted with not-yet-importable formats; when a format epic ships a real adapter its `detect()` supersedes the sniffer (dedup keeps the importable candidate). A new authenticated `POST /v1/import/detect` (`import_sources_routes.py`) exposes the verdict. Documented in `docs/import_source_spi.md`; tests in `tests/test_format_detection.py` (22) + `/detect` route cases in `tests/test_import_sources_routes.py`; full rest suite green (2149 passed, 2 pre-existing live-DB skips). apiome-rest 1.40.0 → 1.41.0.
- **Problem.** Users shouldn't have to know whether a file is RAML vs OpenAPI vs Smithy.
- **Solution / Scope.** Extend the existing `import auto` detector to sniff the new formats: `#%RAML`, `FORMAT: 1A` (API Blueprint), `$version`/namespace (Smithy/TypeSpec), `<wsdl:definitions>`/`<edmx:Edmx>` (WSDL/OData), `asyncapi:` key, `.proto` `syntax=`, Avro `{"type":"record"}`, GraphQL `type Query`. Each adapter contributes a `detect()` with a confidence score; highest wins.
- **Acceptance Criteria.** Fixtures of each format auto-route to the right adapter; ambiguous inputs prompt the user.
- **Dependencies / Parallelism.** After 1.1/1.2. Parallel with format epics.
- **Technical Stack.** Python.

---

## MFI-EPIC-2 — Normalized Internal API Model  ·  **#3717**

One paradigm-agnostic model that every format maps into, so versioning/diff/lint/browse are written **once**.

```mermaid
erDiagram
  api_artifact ||--o{ api_service : has
  api_service ||--o{ api_operation : exposes
  api_operation ||--o{ api_message : in_out
  api_artifact ||--o{ api_type : defines
  api_artifact ||--o{ api_channel : "event/async"
  api_type ||--o{ api_field : has
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 2.1 ✅ | Canonical model schema design | paradigm-agnostic entities (service/operation/message/type/field/channel) | multi-protocol,rest,python,mvp | N | Y | L | apiome-rest |
| 2.2 ✅ | Normalized-model persistence tables | store the canonical model per artifact version | multi-protocol,database,mvp | N | Y | M | apiome-db |
| 2.3 ✅ | Normalizer SPI (format → model) | per-format mapping contract + base utilities | multi-protocol,rest,python,mvp | N | Y | M | apiome-rest |
| 2.4 ✅ | Paradigm coverage & fidelity tests | ensure REST/RPC/event/graph/data map losslessly enough | multi-protocol,testing,mvp | Y | Y | M | apiome-rest |

### MFI-2.1 — Canonical model schema design  ·  **#3738**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/canonical_model.py`; documented in `apiome-rest/docs/canonical_model.md`; paradigm-coverage + persistence round-trip tests in `apiome-rest/tests/test_canonical_model.py` (REST/RPC/event/graph/data-schema).
- **Problem.** REST, RPC, event-driven, graph, and data-schema formats have different shapes; we need a common denominator that still supports per-format diff/lint fidelity.
- **Solution / Scope.** Design a `CanonicalApi`: artifact (format, protocol, identity, version, servers/endpoints), **services** (named groups), **operations** (op kind: request/response, query/mutation/subscription, unary/streaming, pub/sub; input/output message refs; verb/route where applicable), **messages** (payload schema ref, headers), **channels** (event address/binding), **types** (records/structs/enums/unions + fields with type, nullability, defaults, constraints), and a `raw`/`extras` bag for format-specific fidelity. Keys are stable (mirroring GraphQL Schema Coordinates / protobuf field numbers / XSD QNames so diffs are stable).
- **Acceptance Criteria.** Documented model maps cleanly from at least one REST, one RPC, one event, one graph, and one data-schema sample; round-trips to/from persistence.
- **Dependencies / Parallelism.** After 1.1. Blocks 2.2/2.3 and all normalizers.
- **Technical Stack.** Python, Pydantic.

### MFI-2.2 — Normalized-model persistence tables  ·  **#3739**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-db/scripts/V135__canonical_api_model_persistence_3739.sql`: seven `apiome` tables (`api_artifacts` → `api_services` → `api_operations` → `api_messages`; `api_artifacts` → `api_channels`; `api_artifacts` → `api_types` → `api_fields`) mirroring the MFI-2.1 `CanonicalApi`, each tied to a `versions` row and tenant-scoped, with stable per-parent keys, soft delete, JSONB for `raw`/constraints/irregular sub-structures, and GIN tsvector search indexes. Structural contract tests in `apiome-db/test/canonical-api-model-persistence.test.ts`; migration applied + a full store/reload round-trip verified against the live `apiome` database.
- **Problem.** The canonical model must be queryable (browse/search/diff), not a blob.
- **Solution / Scope.** Flyway migration adding `apiome.api_artifacts`, `api_services`, `api_operations`, `api_messages`, `api_channels`, `api_types`, `api_fields` (UUID PKs, tenant scoping, soft delete, JSONB for `raw`/constraints, GIN/tsvector for search), each tied to a `version_id`. Reuse `versions`/`version_tags`.
- **Acceptance Criteria.** Migration applies over the latest version; stores + reloads a canonical model; indexed for search.
- **Dependencies / Parallelism.** After 2.1. Blocks normalizers' persistence.
- **Technical Stack.** PostgreSQL, Flyway.

### MFI-2.3 — Normalizer SPI (format → model)  ·  **#3740**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/normalizer.py` (the SPI + base utilities) and `apiome-rest/src/app/openapi_normalizer.py` (the reference normalizer). The `Normalizer` abstract contract carries `format`/`paradigm` identity and a single `normalize()` method, with a by-format-key registry (`register_normalizer`/`get_normalizer`/`available_formats`, plus a `register=True` class flag). Base utilities: `Keys` (deterministic stable-key builders for the documented key grammar), `coerce_constraints` + `SchemaCoercer` (JSON-Schema fragment → canonical `TypeRef`/`Constraints`/named `Type`s, reusing the JSON-Schema vocabulary and accepting both OpenAPI 3.0 and 3.1 forms), and `normalize_ordering` (sorts identity-keyed collections for byte-stable output). The reference `OpenApiNormalizer` maps a parsed OpenAPI 3.0/3.1 document into a REST `CanonicalApi` and self-registers `openapi-3.0`/`openapi-3.1`. Documented in `apiome-rest/docs/normalizer_spi.md`; tests in `tests/test_normalizer.py` + `tests/test_openapi_normalizer.py` (41 tests; full rest suite green). apiome-rest 1.25.0 → 1.26.0.
- **Problem.** Each format needs a mapping into the canonical model with shared helpers.
- **Solution / Scope.** A `Normalizer` contract + base utilities (stable-key assignment, schema coercion into the canonical type model reusing the existing JSON-Schema/primitives work, ordering normalization). Format epics implement it.
- **Acceptance Criteria.** SPI documented; a reference normalizer (e.g. OpenAPI→Canonical) implemented and tested.
- **Dependencies / Parallelism.** After 2.1. Blocks format normalizer issues.
- **Technical Stack.** Python.

### MFI-2.4 — Paradigm coverage & fidelity tests  ·  **#3741**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/tests/test_paradigm_fidelity.py` — the cross-paradigm fidelity *contract* the format epics are written against. For each paradigm it sweeps the load-bearing axis exhaustively and asserts each value survives the full normalizer tail (`normalize_ordering`, asserted idempotent + fingerprint-stabilizing, then the JSONB round-trip): every gRPC `StreamingMode` (unary/client/server/bidi) + protobuf field-number identity across re-ordering; every GraphQL list/non-null wrapper permutation (`T`…`[[T!]!]!`, re-rendered back to source syntax); both AsyncAPI actions (publish/subscribe) with channel bindings/parameters; every falsy Avro default (`0`/`0.0`/`False`/`""`/`[]`/`{}`, type-checked so `0` ≠ `False`) plus enum-ordinal and union-resolution order preserved through ordering; and REST parameter locations + success/error status fidelity. A `test_load_bearing_fields_have_a_canonical_home` gap-audit fails — pointing straight back at MFI-2.1 — if the model ever drops a load-bearing field. The one true edge (an *explicit* Avro `default: null` vs no default) is shown covered losslessly by the documented per-entity `extras` escape hatch, so **no MFI-2.1 extension was required**. 27 fidelity tests; the normalizer+canonical suites (76 tests) stay green. Docs cross-linked from `apiome-rest/docs/normalizer_spi.md`. apiome-rest 1.26.0 → 1.27.0.
- **Problem.** A lossy model would make diffs/lint wrong for some paradigms.
- **Solution / Scope.** A cross-paradigm fixture suite asserting that key entities survive normalization (e.g. gRPC streaming flags, GraphQL nullability/list wrappers, AsyncAPI operation action, Avro defaults). Where a paradigm needs extra fields, extend 2.1.
- **Acceptance Criteria.** Each paradigm's load-bearing fields are represented and asserted; gaps tracked back into 2.1.
- **Dependencies / Parallelism.** After 2.3. Parallel with format epics (acts as their contract test).
- **Technical Stack.** Python, pytest.

---

## MFI-EPIC-3 — Versioning, Fingerprint & Compare/Diff (generalized)  ·  **#3718**

Lift the MCP catalog's versioning/diff (V2-MCP-EPIC-18) to operate on the **canonical model**, so
every format gets dated versions, a self-computed fingerprint, and compare-any-two diffs for free.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 3.1 ✅ | Canonical fingerprint SPI | stable SHA-256 over normalized model (+ per-format hash hooks) | multi-protocol,version-control,python,mvp | N | Y | M | apiome-rest |
| 3.2 | Compare-any-two diff over the model | added/removed/modified across services/ops/types/fields | multi-protocol,version-control,python,mvp | N | Y | M | apiome-rest |
| 3.3 ✅ | Breaking-change classifier SPI | per-format rules + wrap external tools (Buf/inspector/smithy/Avro) | multi-protocol,validation,version-control,mvp | N | Y | L | apiome-rest |
| 3.4 ✅ | Versioning + tagging reuse | dated versions on change; reuse versions/version_tags | multi-protocol,versions,mvp | Y | Y | S | apiome-rest |

### MFI-3.1 — Canonical fingerprint SPI  ·  **#3742**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/fingerprint.py`. `canonical_fingerprint(api)` is a SHA-256 over a canonicalized projection of the MFI-2.1 `CanonicalApi`: collections are order-normalized via `normalize_ordering` (order-meaningful `enum_values`/`union_members`/server variables left in place), descriptive/presentation keys (`description`, `title`, `raw`) are scrubbed structurally while opaque semantic bags (`extras`/`bindings`/`payload_schema` and literal `default`/`value`/`enum`) are carried verbatim, then `json.dumps(sort_keys=True, separators=(",",":"))` → `hashlib.sha256` — generalizing the MCP report-fingerprint recipe (V2-MCP-EPIC-18.1 / `schema_lint._report_fingerprint`). A per-format hash hook SPI (`FingerprintHasher` + `register_fingerprint_hasher`/`get_fingerprint_hasher`/`available_fingerprint_formats`, mirroring the normalizer registry) lets format epics attach special hashes (Avro PCF, protobuf descriptor-set, XSD QName); `fingerprint(api)` returns a `FingerprintResult` carrying the always-present semantic fingerprint plus the format hash when one is registered. Avro PCF vs semantic-hash distinction (PCF strips defaults/aliases/doc; the semantic hash keeps defaults/`deprecated`/constraints) documented in `apiome-rest/docs/fingerprint_spi.md`. 21 tests in `tests/test_fingerprint.py` (stability, doc-only + order invariance, single-field-change flips, hook dispatch); full rest suite green (1985 passed). apiome-rest 1.32.0 → 1.33.0.
- **Problem.** Change detection must work uniformly but respect per-format identity keys.
- **Solution / Scope.** Canonicalize the normalized model (sorted, stable keys, drop comments/descriptions/order) → SHA-256. Provide a per-format hook for special hashes (Avro **Parsing Canonical Form** CRC-64/SHA-256 [avro spec], protobuf descriptor-set, XSD QName canonicalization). Reuse MCP `EPIC-18.1`.
  - Source: Avro PCF — https://avro.apache.org/docs/1.12.0/specification/
- **Acceptance Criteria.** Identical artifacts → identical fingerprint across runs; a single field change flips it; Avro PCF vs semantic-hash distinction documented (PCF strips defaults/aliases/doc).
- **Dependencies / Parallelism.** After 2.1. Blocks 3.2.
- **Technical Stack.** Python, hashlib.

### MFI-3.2 — Compare-any-two diff over the model  ·  **#3743**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/diff.py`. `diff(base, target) -> ModelDiff` lists every service/operation/message/channel/type/field added/removed/modified, each carrying its before/after self-projection plus a per-attribute `FieldChange` breakdown for modifications, with overall and per-category `DiffCounts`. The diff is taken over `app.fingerprint.canonical_payload`, so it is in lock-step with MFI-3.1 change detection: documentation-only edits and source declaration-order differences are invisible, and identical models → empty diff (`ModelDiff.identical`). Entities are paired by their stable canonical `key` (rename = remove + add), so the comparison is exact for *any two* versions (adjacent or distant) and across formats; categories are flattened and globally keyed so parent/child changes are never double-counted (a type with one new field is not itself "modified"). A per-format label SPI (`DiffLabeler` + `register_diff_labeler`/`get_diff_labeler`/`available_diff_formats`, mirroring the normalizer and fingerprint-hasher registries) enriches `EntityChange.label` purely additively — the hook per-format diff enrichment (and the MFI-3.3 breaking-change classifier) builds on. Documented in `apiome-rest/docs/diff_spi.md`; 31 tests in `tests/test_diff.py` (identical→empty per paradigm, doc-only/ordering invariance, add/remove/modify per category, non-adjacent + cross-format pairs, counts, determinism, JSON round-trip, label hook); full rest suite green (2016 passed). apiome-rest 1.33.0 → 1.34.0.
- **Problem.** Users need to diff **any two versions** of any format (the MCP decision, generalized).
- **Solution / Scope.** A `diff(modelA, modelB)` over the canonical model returning added/removed/modified across services/operations/messages/channels/types/fields with before/after + counts; compare-any-two (not just adjacent), mirroring V2-MCP-EPIC-18.2/24.3. Format adapters may enrich change labels.
- **Acceptance Criteria.** Correct add/remove/modify on cross-format fixtures; non-adjacent pairs supported; identical models → empty diff.
- **Dependencies / Parallelism.** After 3.1. Blocks per-format diff enrichment.
- **Technical Stack.** Python.

### MFI-3.3 — Breaking-change classifier SPI  ·  **#3744**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/breaking_change.py`. `classify(model_diff, base, target) -> ClassificationResult` grades every change in an MFI-3.2 `ModelDiff` with a three-tier `Severity` (`safe` / `dangerous` / `breaking` — the common ground of GraphQL-Inspector, Buf, and Confluent), returning a per-change `ChangeClassification` (severity + stable `rule_id` + rationale, carrying the change's category/kind/key so a diff view joins severities back onto rendered changes), the worst `overall_severity`, a `breaking` convenience boolean, and a `counts_by_severity` tally. `classify` dispatches by `target.format`: a per-format `BreakingChangeClassifier` (SPI + `register_breaking_change_classifier`/`get_breaking_change_classifier`/`available_breaking_change_formats`, mirroring the normalizer/fingerprint/diff registries) when registered, else the format-agnostic `BuiltinBreakingChangeClassifier` baseline (removal = breaking, additive surface = safe, added-mandatory-field = dangerous, modifications graded as the worst over their moved canonical attributes; folded member lists like `parameters`/`headers`/`enum_values` flagged dangerous for a format pack to sharpen). Format packs either wrap the canonical tool via the EPIC-5 toolchain runner (Buf/GraphQL-Inspector/`@asyncapi/diff`/`smithy diff`/Confluent `/compatibility`) overriding `classify`, or subclass the builtin to override individual rules. `classify_models(base, target)` is a diff-then-classify convenience. Pure (no DB/network) on the builtin path; `ClassificationResult` round-trips to JSONB for MFI-3.4. Documented in `apiome-rest/docs/breaking_change_spi.md`; 28 tests in `tests/test_breaking_change.py` (known breaking + safe change per paradigm, every rule branch, registry register/lookup/duplicate-guard + dispatch, builtin-subclass override, worst-of aggregation + tally, determinism, JSON round-trip); full rest suite green (2045 passed, 2 pre-existing live-DB skips). apiome-rest 1.34.0 → 1.35.0.
- **Problem.** "What changed" must be graded **breaking vs safe**, and the rules differ sharply per format (Avro compat modes, Buf wire-compat, GraphQL breaking/dangerous, Smithy evaluators, OData §5.2, XSD).
- **Solution / Scope.** A classifier SPI that takes a diff + both models and returns severities. Format packs implement it, ideally **wrapping the canonical tool** via the toolchain runner (EPIC-5): Buf breaking (WIRE/WIRE_JSON), GraphQL-Inspector classes, `@asyncapi/diff`, `smithy diff` evaluators, Confluent `/compatibility`, OData policy. Where no tool exists (RAML, API Blueprint), a documented built-in ruleset.
  - Sources: Buf https://buf.build/docs/breaking/rules/ · GraphQL Inspector https://github.com/graphql-hive/graphql-inspector · Confluent compat https://docs.confluent.io/platform/current/schema-registry/develop/api.html · Smithy https://smithy.io/2.0/guides/evolving-models.html
- **Acceptance Criteria.** Each format pack classifies a known breaking and a known safe change; severities surfaced on the diff view.
- **Dependencies / Parallelism.** After 3.2, 5.1. Used by all format epics.
- **Technical Stack.** Python + external CLIs.

### MFI-3.4 — Versioning + tagging reuse  ·  **#3745**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/versioning.py`. `decide_version(model, *, previous, when, existing_tags) -> VersionDecision` generalizes the MCP version-on-change recipe (`mcp_discovery_engine._persist_outcome` / `Database.record_mcp_discovery_version`, V2-MCP-18.3/18.4) over the canonical model — **no new mechanism**. It fingerprints the freshly normalized model (MFI-3.1 `fingerprint`), compares the semantic fingerprint against the artifact's current version (`PreviousVersion.fingerprint`, the same `previous.surface_fingerprint == fingerprint` test the MCP path uses), and returns a `VersionDecision`: `VersionAction.CREATE` on the first import (no diff — nothing to compare) or when the fingerprint changed, `VersionAction.SKIP` on an unchanged re-import (mints nothing and leaves `current_version` put). A created version is stamped with a minute-precision UTC date/time tag (`format_version_tag`/`mint_version_tag`, e.g. `2026-06-26T14:03Z`, carrying the same `-N` same-minute collision suffix as `Database._next_mcp_version_tag`), and — when `previous.model` is supplied — the before→after `ModelDiff` (MFI-3.2 `diff`) the new version carries. The decision also reports the `current_version_tag` the artifact's `current_version` should point at afterward (advanced only on a change, mirroring `mcp_endpoints.current_version_id`). Pure (no DB/network/clock read): the import time and previously recorded version are inputs, so the persistence wiring (per-format catalog write, MFI-2.2 `api_artifacts` + the format epics) reuses one audited decision instead of re-deriving it per format. 27 tests in `tests/test_versioning.py` (no-change-skips and change-creates-dated-version+diff per paradigm, doc-only-edit skips, diff orientation/removal, fingerprint-only deciding without a previous model, same-minute tag collision suffixing, determinism, JSON round-trip, input-not-mutated); full rest suite green (2072 passed, 2 pre-existing live-DB skips). apiome-rest 1.35.0 → 1.36.0.
- **Problem.** Each imported artifact needs dated versions only when its fingerprint changes.
- **Solution / Scope.** Reuse `versions`/`version_tags` + the MCP version-on-change logic for canonical artifacts; date/time tags; `current_version`. No new mechanism.
- **Acceptance Criteria.** Re-import with no change creates no version; a change creates one dated version + diff.
- **Dependencies / Parallelism.** After 3.2. Parallel with EPIC-4.
- **Technical Stack.** PostgreSQL, FastAPI.

---

## MFI-EPIC-4 — Lint/Score Engine + Rule-Pack SPI  ·  **#3719**

Generalize `schema_lint.py` (findings + 0–100 + A–F + fingerprint) to a pluggable engine with
per-format **rule packs**, optionally wrapping external linters.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 4.1 ✅ | Lint engine + rule-pack SPI | run rule packs over the canonical model, deterministic findings | multi-protocol,linting,python,mvp | N | Y | M | apiome-rest |
| 4.2 ✅ | Score/grade/fingerprint reuse | 0–100 + A–F + stable fingerprint per version | multi-protocol,linting,mvp | N | Y | S | apiome-rest |
| 4.3 | External-linter adapter | wrap Spectral/Buf-lint/smithy-linters/graphql-eslint via runner | multi-protocol,linting,integrations | Y | N | M | apiome-rest |
| 4.4 ✅ | Lint REST/UI/CLI surfacing | expose findings/score per version everywhere | multi-protocol,rest,ui,linting,mvp | Y | Y | S | apiome-rest,apiome-ui,apiome-cli |

### MFI-4.1 — Lint engine + rule-pack SPI  ·  **#3746**  ·  ✅ **Done**
- **Problem.** The current linter targets OpenAPI/JSON-Schema; we need per-format rule packs over the canonical model.
- **Solution / Scope.** Generalize `schema_lint.py` into an engine that runs registered **rule packs** (a pack = ordered rules → `LintFinding` with stable IDs + severity + group), mirroring its deterministic structure. A "common" pack covers cross-format hygiene (missing descriptions, unstable identifiers); format packs add specifics.
- **Acceptance Criteria.** Pure (no DB/network); deterministic findings + stable IDs; OpenAPI pack reproduces current behavior.
- **Dependencies / Parallelism.** After 2.1. Blocks format lint packs.
- **Technical Stack.** Python.

### MFI-4.2 — Score/grade/fingerprint reuse  ·  **#3747**  ·  ✅ **Done**
- **Problem.** Findings must roll up to a stored score/grade per version, like specs and MCP.
- **Solution / Scope.** Weighted 0–100 (normative violations heavier), A–F bands (V124 thresholds), report fingerprint; persist to the artifact version (reuse `quality_*` columns / MCP `mcp_version_scores` pattern). Capture at import. `LintReport` now mirrors `LintResult` (score/grade/`report_fingerprint`/tallies); the SPI default `lint()` rolls up via `lint_canonical_model`; `capture_canonical_quality_score` persists onto `versions.quality_*` (one `api_artifacts` row per `versions` row ⇒ no new migration), wired best-effort into the import pipeline behind a version-target guard.
- **Acceptance Criteria.** Deterministic score per fixed model; auto-captured on new version.
- **Dependencies / Parallelism.** After 4.1. Parallel with 4.3.
- **Technical Stack.** Python, PostgreSQL.

### MFI-4.3 — External-linter adapter  ·  **#3748**
- **Problem.** Best-of-breed linters (Spectral, Buf lint, smithy-linters, graphql-eslint, AMF SHACL) are JS/JVM and authoritative for their formats.
- **Solution / Scope.** An adapter that runs an external linter via the toolchain runner (EPIC-5), maps its output into `LintFinding`s, and merges with native packs. Opt-in per format.
  - Sources: Spectral https://github.com/stoplightio/spectral · Buf lint https://buf.build/docs/lint/ · smithy-linters https://smithy.io/2.0/guides/model-linters.html
- **Acceptance Criteria.** At least one external linter (e.g. Spectral for AsyncAPI) runs and contributes findings; failures degrade gracefully to native packs.
- **Dependencies / Parallelism.** After 4.1, 5.1. Parallel with 4.2.
- **Technical Stack.** Python + Node/JVM CLIs.

### MFI-4.4 — Lint REST/UI/CLI surfacing  ·  **#3749**  ·  ✅ **Done**
- **Problem.** Findings/score must appear in REST, ADE, and CLI uniformly.
- **Solution / Scope.** Reuse `lint_routes.py` shape for canonical artifacts; ADE lint panel + CLI `apiome lint`. Mirrors MCP EPIC-24.4 / EPIC-25.3. The three surfaces (REST `GET .../lint`, the ADE `VersionLintBadge` panel, and CLI `apiome lint`) already render the live findings/score from `lint_routes.py`; MFI-4.4 makes them also surface the *captured* import-time score (#3609/MFI-4.2) persisted on `versions.quality_*`. `LintReportResponse` gains `capturedScore`/`capturedGrade`/`capturedReportFingerprint`/`scoreIsStale` (stale = captured fingerprint differs from the live one, never flagged when a base revision is compared), read tenant-scoped and best-effort via `Database.get_version_quality_score`. The ADE panel shows a stale-score note; the CLI prints a `Stored score:` line. No migration (score already lives on the version).
- **Acceptance Criteria.** Findings + score visible per version in all three surfaces; tenant-scoped.
- **Dependencies / Parallelism.** After 4.2. Parallel with 4.3.
- **Technical Stack.** FastAPI, Next.js, Typer.

---

## MFI-EPIC-5 — Polyglot Toolchain Runner  ·  **#3720**

Many authoritative parsers/linters/diff tools are **not Python** (buf, tsp, AMF/JVM, drafter,
smithy CLI, AsyncAPI CLI, rover/graphql-inspector). A sandboxed runner lets adapters shell out
safely. This is the single biggest non-obvious dependency for the format epics.

```mermaid
flowchart LR
  AD[format adapter] -->|invoke| RUN[Toolchain Runner]
  RUN -->|subprocess/sandbox| T1[buf] & T2[tsp] & T3[AMF] & T4[drafter] & T5[smithy] & T6[asyncapi-cli] & T7[graphql-inspector]
  T1 & T2 & T3 & T4 & T5 & T6 & T7 -->|normalized JSON| AD
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 5.1 ✅ | Toolchain runner service | sandboxed subprocess invocation + JSON capture + timeouts | multi-protocol,infrastructure,python,mvp | N | Y | L | apiome-rest |
| 5.2 | Tool runtime packaging | bundle Node/JVM/native CLIs (container image / pinned versions) | multi-protocol,infrastructure,mvp | N | Y | M | apiome-rest |
| 5.3 ✅ | Sandbox security & resource limits | no-network default, FS isolation, CPU/mem/time caps | multi-protocol,security,mvp | Y | Y | M | apiome-rest |

### MFI-5.1 — Toolchain runner service  ·  **#3750**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/toolchain_runner.py`: a `ToolSpec` (key, executable, base args, default timeout, env overrides/passthrough, `parses_json`) + by-key registry (`register_tool`/`get_tool`/`available_tools`/`describe_tools`, mirroring the ImportSource registry) and a `ToolchainRunner` that runs a tool in a constrained `asyncio` subprocess — explicit argv (never a shell), a sanitized environment that forwards only an allow-list of host vars (so `DATABASE_URL`/JWT/cloud secrets never reach a third-party CLI), an optional cwd, a per-call timeout that kills the process, JSON parsing of stdout, and a process-wide concurrency cap (`asyncio.Semaphore`, `APIOME_TOOLCHAIN_MAX_CONCURRENCY`, default 4). Failure modes are typed errors carrying the tool key: `ToolNotRegisteredError`, `ToolNotAvailableError` (missing binary — the MFI-5.2 "format unavailable" path), `ToolTimeoutError`, `ToolExecutionError` (non-zero exit + captured streams), `ToolOutputError` (non-JSON stdout). A built-in `sample-echo` tool (portable JSON echo via the current Python interpreter) is the acceptance vehicle so the runner is exercisable end-to-end without bundling a real CLI (that is MFI-5.2). OS-level sandboxing (no-network, FS isolation, CPU/mem caps) is deferred to MFI-5.3. Settings: `toolchain_max_concurrency`, `toolchain_default_timeout_seconds`. Documented in `apiome-rest/docs/toolchain_runner.md`; tests in `tests/test_toolchain_runner.py` (14 tests: registry, parsed-JSON happy path, not-registered/not-available/non-zero/non-JSON/timeout errors, env sanitization, concurrency cap). Full rest `tests/` suite green (1928 passed, 2 skipped). apiome-rest 1.29.0 → 1.30.0.
- **Problem.** Adapters need a uniform, safe way to run external tools and get structured output.
- **Solution / Scope.** A service that runs a registered tool (by key + args) in a constrained subprocess, captures stdout/stderr/exit, parses its JSON, with per-call timeout and structured errors. Used by parse (buf build, tsp compile, smithy ast, drafter, AMF), lint (4.3), and breaking (3.3).
- **Acceptance Criteria.** Runs a sample tool, returns parsed JSON; timeout/non-zero handled; concurrency-capped.
- **Dependencies / Parallelism.** Early foundation. Blocks 3.3/4.3 and most format epics.
- **Technical Stack.** Python (subprocess/asyncio).

### MFI-5.2 — Tool runtime packaging  ·  **#3751**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/toolchain_packaging.py` + `apiome-rest/Dockerfile`: `BUNDLED_TOOLS` is the single source of truth declaring the seven external CLIs the runtime ships — `buf` (1.50.0), `tsp` (0.65.0), `smithy` (1.53.0), `drafter` (4.0.0), `amf` (5.7.1), `asyncapi` (2.16.0), `rover` (0.27.0) — each as a `BundledTool` (key, executable, **pinned version**, `APIOME_<KEY>_BIN` override, version-probe args, runtime label). A new Dockerfile `tools` stage installs exactly those versions (build-arg pinned, kept in sync with the Python source of truth): native binaries (buf/rover) from GitHub releases, smithy's self-contained CLI zip, drafter built from its pinned tag, the AMF assembly jar + a `java -jar` wrapper, and tsp/asyncapi via npm into the tools prefix with node wrappers; all land on `PATH` at `/opt/apiome-tools/bin`. Tools are **optional/lazy**: `register_bundled_tools()` wires them into the MFI-5.1 runner registry, and a non-raising `probe_tool`/`probe_all` (PATH/override resolution only, no subprocess) reports `available: false` so a format degrades to "unavailable" instead of failing — surfaced operationally at `GET /v1/ops/toolchain` (platform-admin; `?verify=true` additionally runs each available tool's version probe). The MFI-5.1 `ToolNotAvailableError` remains the call-time signal. Footprint documented in `apiome-rest/docs/toolchain_packaging.md` (~465 MB added; drafter's build toolchain stays in the builder stage). Tests in `tests/test_toolchain_packaging.py` (declarations, registration idempotence, lazy availability incl. override-to-missing-file, optional verification, and the platform-admin ops route). apiome-rest 1.30.0 → 1.31.0.
- **Acceptance Criteria.** ✅ Image builds with pinned tools (versioned build args mirroring the Python source of truth); ✅ each tool invocable (bare-name on `PATH`, resolved by the runner; `?verify=true` confirms); ✅ missing-tool path yields a clear "format unavailable" status (`probe_tool` / `GET /v1/ops/toolchain`).
- **Dependencies / Parallelism.** After 5.1. Blocks format epics that need the tool.
- **Technical Stack.** Docker, Node, JVM, native.

### MFI-5.3 — Sandbox security & resource limits  ·  **#3752**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/toolchain_sandbox.py` + integration into the MFI-5.1 `ToolchainRunner`: every tool subprocess runs under a `SandboxPolicy` (the runner's `default_policy`, built from settings via `SandboxPolicy.from_settings()`, overridable per call). **No network by default** — the child is launched in a fresh Linux network namespace (`unshare(CLONE_NEWUSER|CLONE_NEWNET)`) so it cannot reach the cloud metadata IP / internal services / the internet; enforcement is `best_effort` (isolate when the kernel allows unprivileged userns, else log + continue) or `strict` (fail closed → `ToolSandboxError`). **Resource clamps** are applied in a `preexec_fn` (post-fork, pre-exec): `setrlimit` for CPU-seconds (`SIGXCPU`, soft<hard so it terminates before the SIGKILL backstop), address space, file size (`SIGXFSZ`), child processes (fork-bomb guard), open files, and a zeroed core-dump limit — and the resource signals are reset to `SIG_DFL` so an ambient `SIG_IGN` cannot turn a breach into a survivable error. **Input/output caps** are enforced in the runner: an oversized `stdin` is rejected before the tool is spawned, and a tool whose combined stdout+stderr exceeds the cap is killed mid-stream (a zip-bomb guard) while both pipes are still drained to EOF so the reap never wedges. New typed errors carry the tool key: `ToolInputTooLargeError`, `ToolOutputTooLargeError`, `ToolResourceLimitError` (CPU/file-size kill), `ToolSandboxError` (strict isolation unavailable). A tool needing the network for explicit live discovery opts out via `SandboxPolicy.for_live_discovery()`, and its fetches must then route through the SSRF guard (`app.ssrf_guard`, EPIC-16.6 / #3612) — the runner's no-network default is the belt, the SSRF guard the braces. The platform-admin `GET /v1/ops/toolchain` now also reports the active `sandbox` posture. Settings: `toolchain_no_network`, `toolchain_network_enforcement`, `toolchain_max_input_bytes`, `toolchain_max_output_bytes`, `toolchain_file_size_bytes`, `toolchain_open_files`, and optional `toolchain_cpu_seconds`/`toolchain_memory_bytes`/`toolchain_max_processes`. Documented in `apiome-rest/docs/toolchain_sandbox.md`; tests in `tests/test_toolchain_sandbox.py` (19 tests: policy construction, input/output caps, rlimit visibility + CPU/file-size enforcement, strict/best-effort network enforcement incl. real namespace isolation, ops surface). Full rest `tests/` suite green (1964 passed, 2 skipped). apiome-rest 1.31.0 → 1.32.0.
- **Problem.** Running third-party CLIs on user-supplied input is a security surface (SSRF, code exec, zip bombs).
- **Solution / Scope.** No-network by default, read-only temp FS, CPU/mem/time caps, input size limits; opt-in network only for explicit live-discovery (gRPC reflection, registry crawl) with SSRF guards (reuse MCP EPIC-16.6 posture).
- **Acceptance Criteria.** ✅ Network blocked by default (isolated network namespace; `strict` fails closed); ✅ oversized/hostile inputs rejected (`stdin` cap before spawn, output cap kills mid-stream); ✅ limits enforced (`setrlimit` CPU/file-size/processes/open-files + the wall-clock timeout).
- **Dependencies / Parallelism.** After 5.1. Parallel with 5.2.
- **Technical Stack.** Python, OS sandboxing.

---

## MFI-EPIC-6 — Browse/Search & Categorization by protocol  ·  **#3721**

Make the catalog navigable across paradigms. **Align with #3489 (Schema Registry & Discovery)
and #3496 (Community & Schema Browser).**

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 6.1 | Protocol/format facets | filter browse by protocol (REST/RPC/event/graph/data) + format | multi-protocol,browser,mvp | N | N | M | apiome-rest,apiome-ui |
| 6.2 | Cross-protocol search | search operations/types/messages across all formats | multi-protocol,browser,rest | N | N | M | apiome-rest,apiome-db |
| 6.3 | Catalog categorization | tag/categorize artifacts by paradigm + domain | multi-protocol,community | Y | N | S | apiome-rest |
| 6.4 | Cross-format API identity | link artifacts that describe the same logical API across formats | multi-protocol,registry,rest | Y | N | M | apiome-rest,apiome-ui,apiome-db |

### MFI-6.1 — Protocol/format facets  ·  **#3753**
- **Problem.** With 15+ formats, browse must filter by paradigm/format.
- **Solution / Scope.** Add protocol/format facets to browse (REST, RPC, event-driven, graph, data-schema; and specific format). Reuse `browse_public_routes`/`apiome-browse`. Coordinate with #3496.
- **Acceptance Criteria.** Browse filters by protocol + format; counts per facet.
- **Dependencies / Parallelism.** After 7.1, 2.2. Blocks 6.2.
- **Technical Stack.** FastAPI, Next.js.

### MFI-6.2 — Cross-protocol search  ·  **#3754**
- **Problem.** "Find every API with a `createOrder` operation" across formats.
- **Solution / Scope.** FTS over the normalized model (operations/types/messages) with protocol/format/grade filters; reuse the tsvector indexes from 2.2. Coordinate with #3489.
- **Acceptance Criteria.** Query returns matching operations/types across formats; facets compose.
- **Dependencies / Parallelism.** After 6.1, 2.2. 
- **Technical Stack.** PostgreSQL FTS, FastAPI.

### MFI-6.3 — Catalog categorization  ·  **#3755**
- **Problem.** Catalog needs domain/paradigm grouping.
- **Solution / Scope.** Categories + tags per artifact (paradigm auto-derived; domain manual), surfaced as browse facets. Reuse MCP EPIC-23.3.
- **Acceptance Criteria.** Artifacts categorizable; facets filter browse.
- **Dependencies / Parallelism.** After 7.1. Parallel with 6.1.
- **Technical Stack.** PostgreSQL, FastAPI.

### MFI-6.4 — Cross-format API identity  ·  **#4410**  ·  *(2026-07 gap analysis)*
- **Problem.** The same logical API imported as proto, SDL, and OpenAPI produces three unrelated
  catalog items. Nothing groups them, so the "multi-format catalog" reads as three catalogs; a
  converted OpenAPI project (EPIC-22) is the only linked pair today (via `conversion_provenance`).
- **Solution / Scope.** A lightweight **"related artifacts"** link: an `api_identity` grouping
  (manual link/unlink first — an action on the catalog item and project detail; heuristic
  *suggestions* later from matching titles, operation-name overlap in the canonical model, and
  shared `format_metadata` coordinates). Surfaced as a "Related artifacts" panel on catalog/project
  detail and as a browse facet ("show all representations"). Reuse the conversion-provenance
  back-link as an automatic seed.
- **Acceptance Criteria.** Two artifacts can be linked/unlinked; linked artifacts render each
  other's panel with format pills; a conversion (22.5) auto-links source↔converted project;
  suggestions never auto-link without confirmation.
- **Dependencies / Parallelism.** After 2.2, 23.9. Parallel with 6.1–6.3.
- **Technical Stack.** PostgreSQL, FastAPI, Next.js.

---

## MFI-EPIC-7 — DB model & persistence additions  ·  **#3722**

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 7.1 ✅ | Source-format & protocol columns | tag artifacts/versions with format + protocol + tool versions | multi-protocol,database,mvp | N | Y | S | apiome-db |
| 7.2 ✅ | Format-specific metadata store | JSONB per-format metadata (e.g. Avro subject, gRPC package, registry coords) | multi-protocol,database,mvp | Y | Y | S | apiome-db |
| 7.3 | Backfill existing specs | tag current OpenAPI/Arazzo artifacts with format/protocol | multi-protocol,database | Y | N | S | apiome-db |

### MFI-7.1 — Source-format & protocol columns  ·  **#3756**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-db/scripts/V136__source_format_protocol_columns_3756.sql`: adds `source_format VARCHAR(128)`, `protocol VARCHAR(64)`, and `source_tool_versions JSONB NOT NULL DEFAULT '{}'` to `apiome.versions` — the universally-present catalog/revision entity (an `api_artifacts` row only exists once the normalizer has run, whereas every import yields a `versions` row), mirroring V124's "captured at import" precedent. `source_format`/`protocol` reuse the `api_artifacts.format`/`protocol` vocabularies and are nullable until the MFI-7.3 backfill; `source_tool_versions` is provenance surfaced by the catalog endpoint as `tool_versions`. Two partial facet indexes (`idx_versions_source_format`, `idx_versions_protocol`, scoped `WHERE deleted_at IS NULL AND <col> IS NOT NULL`) back MFI-6.1 browse-by-protocol/format; the JSONB provenance column is intentionally not indexed. Adapter population at import is wired in the import path (apiome-rest/CLI); this migration provides the schema home + indexes. Purely additive (rollback recipe in the header). Structural contract tests in `apiome-db/test/source-format-protocol-columns.test.ts` (13 tests); full db suite green (251). apiome-db 0.17.0 → 0.18.0.
- **Problem.** The catalog can't currently say what *kind* of API an artifact is.
- **Solution / Scope.** Migration adding `source_format`, `protocol`, `source_tool_versions` to the artifact/version model (or project/version), indexed for facets.
- **Acceptance Criteria.** Columns added + indexed; populated by adapters at import.
- **Dependencies / Parallelism.** After 2.2. Blocks 6.x facets.
- **Technical Stack.** PostgreSQL, Flyway.

### MFI-7.2 — Format-specific metadata store  ·  **#3757**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-db/scripts/V137__format_metadata_store_3757.sql`: adds a single open-ended `format_metadata JSONB NOT NULL DEFAULT '{}'` bag to `apiome.versions` — the universally-present revision entity (an `api_artifacts` row only exists once the normalizer has run, whereas every import yields a `versions` row), mirroring V136/V124's "captured at import" precedent. Each format adapter writes the keys it carries beyond the canonical model (Avro subject/compatibility, gRPC package/edition, OData serviceRoot, WSDL targetNamespace, schema-registry coordinates) and discovery/diff/lint read them back, so a new format needs **no DDL change** ("no schema churn per format"). Intentionally **not** indexed: like V136's `source_tool_versions` it is per-revision provenance, not a facet, and a JSONB GIN index here would write-amplify the hot import path for no read benefit (cf. V125's GIN-index drops). Distinct from `api_artifacts.extras` (canonical-model-level format attributes). Purely additive (rollback recipe in the header). Structural contract tests in `apiome-db/test/format-metadata-store.test.ts` (10 tests); full db suite green. apiome-db 0.18.0 → 0.19.0.
- **Problem.** Each format carries identity beyond the common model (Avro subject/compat level, gRPC package/edition, OData root, WSDL targetNamespace, registry coordinates).
- **Solution / Scope.** A JSONB `format_metadata` column (or side table) for adapter-specific fields used by discovery/diff/lint.
- **Acceptance Criteria.** Adapters persist + read their metadata; no schema churn per format.
- **Dependencies / Parallelism.** After 7.1. Parallel with 7.3.
- **Technical Stack.** PostgreSQL.

### MFI-7.3 — Backfill existing specs  ·  **#3758**
- **Problem.** Existing OpenAPI/Arazzo artifacts predate the format/protocol columns.
- **Solution / Scope.** One-off backfill tagging existing artifacts as `openapi`/`arazzo` + `rest`/`workflow`.
- **Acceptance Criteria.** All existing artifacts carry a format/protocol; browse facets include them.
- **Dependencies / Parallelism.** After 7.1. Parallel with 7.2.
- **Technical Stack.** SQL.

---

## MFI-EPIC-8 — AsyncAPI (event-driven) · MVP  ·  **#3723**

AsyncAPI 3.1.0 (latest) / 3.0 / 2.6 still common. JSON/YAML; no live introspection. Servers/
channels/operations/messages. Diff via `@asyncapi/diff`; lint via Spectral.
Sources: https://www.asyncapi.com/docs/reference/specification/v3.1.0 · https://github.com/asyncapi/diff

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 8.1 ✅ | AsyncAPI parser + validate | `@asyncapi/parser` via runner; dereference; v2+v3 | multi-protocol,import,mvp | N | Y | M | apiome-rest |
| 8.2 ✅ | AsyncAPI → canonical model | servers/channels/operations/messages → model | multi-protocol,import,mvp | N | Y | M | apiome-rest |
| 8.3 ✅ | AsyncAPI lint pack | Spectral `spectral:asyncapi` + native hygiene | multi-protocol,linting | Y | Y | S | apiome-rest |
| 8.4 ✅ | AsyncAPI diff/breaking | wrap `@asyncapi/diff` (breaking/non-breaking) | multi-protocol,version-control | Y | Y | M | apiome-rest |
| 8.5 ✅ | AsyncAPI source card + CLI + fixtures | UI card, `apiome import asyncapi`, fixtures | multi-protocol,ui,devex,mvp | Y | Y | S | apiome-ui,apiome-cli |

### MFI-8.1 — AsyncAPI parser + validate  ·  **#3759**  ·  ✅ **Done**
- **Status.** Implemented as a polyglot seam over the official JS parser. A small repo-committed Node wrapper, `apiome-rest/toolchain/asyncapi-parse.mjs`, imports `@asyncapi/parser`: it reads a document (JSON/YAML) on `stdin`, **validates** it (2.6/3.0/3.1 and the wider 2.x/3.x families), **dereferences** in-document `$ref`s, strips the parser's `x-parser-*` bookkeeping keys, and writes a single canonical-JSON object on `stdout` (`{ok, asyncapiVersion, identity:{title,version,id}, document, diagnostics}`); a failed validation is reported in the body (exit 0), never as a crash. It is bundled as a new `asyncapi-parser` tool in `src/app/toolchain_packaging.py` (pinned `@asyncapi/parser` 3.6.0; installed + wrapped in the `Dockerfile` beside `@asyncapi/cli`) so `app.toolchain_runner` invokes it by bare name in the same sandbox as the other CLIs. The Python service `src/app/asyncapi_parser.py` (`parse_asyncapi(...) → AsyncApiParseResult`) shells out through the runner, adapts the wrapper contract into typed models (`AsyncApiIdentity` / `AsyncApiDiagnostic` / `AsyncApiParseResult`), captures `info.title`/`version` + document `id` identity, exposes `ok`/`errors`/`supported_version`/`raise_if_invalid()`, and maps tool failures (unavailable/timeout/non-JSON) to `AsyncApiParseError`. Tests: `tests/test_asyncapi_parser.py` — a seam suite (always-run, Node-free, replaying the wrapper contract incl. authentic dereferenced payloads) plus a gated end-to-end suite that runs the real wrapper through the real runner against `tests/fixtures/asyncapi/` (2.6/3.0/3.1 valid + invalid + non-AsyncAPI); `tests/test_toolchain_packaging.py` extended for the new key. Full rest suite green (2258 passed). apiome-rest 1.47.0 → 1.48.0.
- **Problem.** Need to parse + dereference AsyncAPI v2/v3 reliably (the Python ecosystem is thin).
- **Solution / Scope.** Use **`@asyncapi/parser`** (JS) via the toolchain runner to validate + dereference to a canonical JSON, supporting 2.6/3.0/3.1. Capture `info.title`/`version`/`id` identity.
  - Source: https://github.com/asyncapi/parser-js
- **Acceptance Criteria.** v2 and v3 fixtures parse + dereference; invalid docs report errors.
- **Dependencies / Parallelism.** After 1.x, 2.3, 5.1. Blocks 8.2.
- **Technical Stack.** Python + Node (`@asyncapi/parser`).

### MFI-8.2 — AsyncAPI → canonical model  ·  **#3760**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/asyncapi_normalizer.py` (`AsyncApiNormalizer`), a `Normalizer`-SPI implementation that maps the **dereferenced** AsyncAPI document from MFI-8.1 (`parse_asyncapi(...).document`) into a `CanonicalApi` of paradigm `EVENT`, handling both families by dispatching on the document's own `asyncapi` version. **servers→`Server`** (v2 `url`; v3 `host`+`pathname` recombined into the URL with the split kept in `extras`; transport `protocol` preserved and the first server's protocol becomes the artifact `protocol`); **channels→`Channel`** (wire `address` = stable key, address `parameters`, protocol `bindings`); **operations→`Operation`** (`action` drives the kind — `send`/`publish` → `PUBLISH`, `receive`/`subscribe` → `SUBSCRIBE`; the dereferenced `channel` is matched back to its declaring channel by address for `channel_ref`; the original action verb and any `reply` are kept in `extras`; operations grouped into `Service`s by first tag, `default` when untagged); **messages→`Message`** (role `EVENT`, inline `payload`→`payload_schema` since the parser has inlined every `$ref`, `headers` schema→header fields, `contentType`/`defaultContentType`→`content_types`, `correlationId`→`extras`). New `Keys` builders (`channel`/`operation_event`/`event_message`/`channel_parameter`) centralize the event key grammar. The model finishes through `normalize_ordering`, so the MFI-3.1 fingerprint is invariant to source declaration order yet flips on any structural change (payload field added/retyped, etc.). Registered under both `asyncapi-2` and `asyncapi-3`; `import_source.load_builtin_import_sources()` imports the module so it self-registers ahead of the MFI-8.5 adapter. Tests: `tests/test_asyncapi_normalizer.py` — multi-channel v2 + v3 mapping, action/channel/message fidelity, idempotence, fingerprint stability across source order, description-only edits ignored, lossless JSONB round-trip, registry resolution + error paths, plus a gated end-to-end suite feeding the real MFI-8.1 parser output into the normalizer. Docs (`normalizer_spi.md`, `canonical_model.md`) extended. apiome-rest 1.48.0 → 1.49.0.
- **Problem.** Map AsyncAPI's event model into the canonical model.
- **Solution / Scope.** Servers→endpoints, channels→`api_channel` (address/bindings/params), operations→`api_operation` (action send/receive, channel ref, reply), messages→`api_message` (payload schema, headers, correlationId). Hash the dereferenced structure (3.1).
- **Acceptance Criteria.** A multi-channel doc normalizes; round-trips; fingerprint stable.
- **Dependencies / Parallelism.** After 8.1, 2.1. Blocks 8.4.
- **Technical Stack.** Python.

### MFI-8.3 — AsyncAPI lint pack  ·  **#3761**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/asyncapi_lint.py` — the **first concrete format pack** on the MFI-4.1 lint engine. `AsyncApiRulePack` (registered under both `asyncapi-2` and `asyncapi-3`, since the two families normalize into the same shape) adds native, pure-over-the-canonical-model event-API rules: **message names** (`asyncapi.message-missing-name` info, `asyncapi.message-unstable-name` warning — the latter reusing the shared import-stability heuristic, now exposed as `lint_engine.is_unstable_name`), **missing payload schema** (`asyncapi.message-missing-payload` warning — neither a named `payload` nor an inline `payload_schema`), and **server protocol/security** (`asyncapi.server-missing-protocol` warning, `asyncapi.server-missing-security` info, the latter read from the `Server.extras["security"]` the MFI-8.2 normalizer preserves). For the **Spectral** half it *wraps* `extends: spectral:asyncapi` (v2+v3) without shipping a second linter: `@asyncapi/parser` (MFI-8.1) already runs that exact ruleset during parse, so `spectral_findings(...)` maps the parser's `AsyncApiDiagnostic`s into `LintFinding`s (rule `asyncapi.spectral.<code>`, category `spectral`, Spectral's `hint` folded to `info`, empty paths anchored to `(document)`). `lint_asyncapi_result(model, parse_result)` (sync, pure) merges Spectral + native + common through the shared `lint_canonical_model`/`assemble_lint_result`, so the score/grade/`report_fingerprint` use the exact same formula as every format; **Spectral is opt-in and degrades gracefully** — no parse result ⇒ native + common still score. A convenience async `lint_asyncapi(raw, runner=...)` ties parse→normalize→merge end-to-end (the MFI-8.5 import pipeline, which already holds the parse result, will call `lint_asyncapi_result` directly). The engine self-loads format packs via a new lazy `lint_engine.load_format_rule_packs()` (mirroring `load_builtin_import_sources`). Tests: `tests/test_asyncapi_lint.py` — every native rule fires + a clean model scores 100/A, registry resolution for both families, v2/v3 parity, Spectral mapping (namespacing/severity-fold/blank-code/empty-path), merge-into-score + graceful degradation + determinism, a Node-free end-to-end seam suite running `lint_asyncapi` for v2+v3 through a fake runner replaying the parser contract, and a gated suite over the real `2.6`/`3.0`/`3.1` fixtures. Docs: new `docs/asyncapi_lint.md`; `lint_engine_spi.md` extended. Full rest suite green (2293 passed). apiome-rest 1.49.0 → 1.50.0.
- **Problem.** Need quality signals for event APIs.
- **Solution / Scope.** Wrap **Spectral** `extends: spectral:asyncapi` (v2+v3) via 4.3, plus native rules (message names, missing payload schema, server protocol/security). 
- **Acceptance Criteria.** Lints v2+v3; findings merged into the score.
- **Dependencies / Parallelism.** After 4.1/4.3, 8.2. Parallel with 8.4.
- **Technical Stack.** Python + Spectral.

### MFI-8.4 — AsyncAPI diff/breaking  ·  **#3762**  ·  ✅ **Done**
- **Problem.** Classify breaking changes between versions.
- **Solution / Scope.** Wrap **`@asyncapi/diff`** (pass already-validated/dereferenced docs from 8.1) → breaking/non-breaking/unclassified, mapped into the classifier SPI (3.3).
- **Acceptance Criteria.** A breaking and a safe change classified correctly; surfaced on diff view.
- **Dependencies / Parallelism.** After 8.2, 3.3. Parallel with 8.3.
- **Technical Stack.** Python + `@asyncapi/diff`.
- **Status.** Implemented as `src/app/asyncapi_diff.py` — the **AsyncAPI provider** on the MFI-3.3 breaking-change classifier SPI (`app.breaking_change`). `AsyncApiBreakingChangeClassifier` subclasses the format-agnostic `BuiltinBreakingChangeClassifier` and registers under both `asyncapi-2` and `asyncapi-3`, so the **synchronous, pure** SPI dispatch (`breaking_change.classify`) already grades an AsyncAPI diff from structure alone (removed channel/operation/message breaking, added safe) even with no Node toolchain present — pulled in lazily via a new `breaking_change.load_format_breaking_change_classifiers()` mirroring the lint engine's loader. The **authoritative** grading is the async `classify_async` (+ convenience `classify_asyncapi(base, target)`): it runs **`@asyncapi/diff`** over the two already-validated/dereferenced documents MFI-8.1 preserved on `CanonicalApi.raw` (fed to a new bundled `asyncapi-diff` Node tool — `toolchain/asyncapi-diff.mjs` wrapping `@asyncapi/diff@0.5.0`, registered in `toolchain_packaging.py` like the MFI-8.1 parser — as `{"old":…,"new":…}` on stdin), then **overlays** the tool's `breaking`→`BREAKING` / `non-breaking`→`SAFE` verdict onto the structural grades wherever a change *joins* a canonical entity (a channel by its **address** — resolving the v3 map-name→address split; an operation by its v3 name or v2 `operationId`/`{action} {address}`). `unclassified` and non-joining changes (deep payload edits, metadata) keep the conservative structural grade, so a removal is never silently downgraded. The path **degrades gracefully** to the structural baseline when the documents or the `asyncapi-diff` tool are unavailable; the result is the standard `ClassificationResult`, 1:1 with the diff's changes (rule ids `asyncapi-diff.breaking`/`asyncapi-diff.non-breaking` for tool verdicts), so severities surface on the diff view. Tests: `tests/test_asyncapi_diff.py` — the tool seam over a fake runner (wrapper contract, malformed changes skipped, infra failures → `AsyncApiDiffError`, both docs on stdin), the join helper for v2 + v3, the overlay (a breaking + a safe change graded correctly, `unclassified`/non-joining keep structural), graceful degradation, SPI registration for both families + sync structural dispatch, determinism + JSON round-trip, and a gated end-to-end suite over the real bundled `@asyncapi/diff`; `test_toolchain_packaging.py` expects the new key. Docs: new `docs/asyncapi_diff.md`; `toolchain_packaging.md` extended; Dockerfile installs `@asyncapi/diff` + copies the wrapper. apiome-rest 1.50.0 → 1.51.0.

### MFI-8.5 — AsyncAPI source card + CLI + fixtures  ·  **#3763**  ·  ✅ **Done**
- **Problem.** Users need to import AsyncAPI from UI/CLI.
- **Solution / Scope.** Register the source (icon/label/input: file/url/paste), `apiome import asyncapi`, and a fixture suite (2.6/3.0/3.1). Coordinate with **#2772 / #1438**.
- **Acceptance Criteria.** Import from UI + CLI end-to-end → cataloged version with score + diff.
- **Dependencies / Parallelism.** After 8.2, 1.3/1.4. 
- **Technical Stack.** Next.js, Typer.
- **Status.** Implemented as `src/app/asyncapi_import_source.py` — the **`ImportSource` adapter** (MFI-1.1) that makes the AsyncAPI work of MFI-8.1…8.4 reachable from the UI source card and the CLI. Like the reference OpenAPI adapter it is a thin seam over machinery that already exists: **detect** sniffs the `asyncapi` version marker (→ `asyncapi-2` / `asyncapi-3`); **parse** runs the authoritative `@asyncapi/parser` (MFI-8.1) to validate + dereference, surfacing an invalid document as a clean `ImportSourceError`; **normalize** delegates to the registered `AsyncApiNormalizer` (MFI-8.2); **lint** folds the `spectral:asyncapi` diagnostics into the score via `lint_asyncapi_result` (MFI-8.3) when the parse result is on hand, else degrades to the engine default (common + native packs); **fingerprint/diff** use the canonical defaults (the MFI-8.4 breaking overlay layers on the diff view). The SPI's `parse()` is **synchronous** but the Node-backed parser is a coroutine called from the service's running loop, so `parse()` drives it to completion on a **dedicated worker-thread event loop** with a fresh sibling `ToolchainRunner` (its `asyncio.Semaphore` binds to that loop). Registering the adapter (`register=True`, wired into `load_builtin_import_sources`) is **all the UI and CLI need**: both are data-driven off `GET /v1/import/sources`, so an `asyncapi` card (`radio` icon, *event* paradigm, file/url/paste inputs) appears in the source-card grid and `apiome import asyncapi <input>` rides the MFI-1.4 generic dispatch — **no new UI or CLI command code**. The 2.6/3.0/3.1 fixture suite (`streetlights_2.6`, `user_events_3.0`, `account_3.1`) lives in `apiome-rest/tests/fixtures/asyncapi/` and a CLI mirror under `apiome-cli/tests/fixtures/`. Tests: `tests/test_asyncapi_import_source.py` (descriptor + registry registration, v2/v3 detect, inline-document normalize + determinism + error boundaries, lint with/without a stashed parse result, the parse bridge + error mapping via a monkeypatched parser, and a gated real-parser suite over the fixtures); `apiome-cli/tests/test_import_asyncapi.py` (drives `import asyncapi` over the 2.6/3.0/3.1 fixtures + `--url`/`--dry-run`/`--list` against a mocked REST); `apiome-ui/tests/importSourceCatalog.test.ts` (AsyncAPI descriptor → usable file-panel card + `radio` icon resolution). Docs: new `docs/asyncapi_import.md`. apiome-rest 1.51.0 → 1.52.0; apiome-cli 0.12.0 → 0.13.0; apiome-ui 0.33.0 → 0.34.0.

---

## MFI-EPIC-9 — gRPC / Protocol Buffers (RPC) · MVP  ·  **#3724**

`.proto` (proto2/proto3/Editions 2023/2024). **Live: Server Reflection.** Compile to a
`FileDescriptorSet` and hash that, not raw `.proto`. Buf for lint + breaking (WIRE/WIRE_JSON).
Sources: https://protobuf.dev/editions/overview/ · https://grpc.io/docs/guides/reflection/ · https://buf.build/docs/breaking/rules/

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 9.1 ✅ | .proto → FileDescriptorSet | `buf build`/protoc via runner; resolve imports | multi-protocol,import,mvp | N | Y | M | apiome-rest |
| 9.2 | Protobuf → canonical model | services/methods (streaming)/messages/fields(number) | multi-protocol,import,mvp | N | Y | M | apiome-rest |
| 9.3 ✅ | gRPC live discovery (reflection) | crawl a running server via Server Reflection | multi-protocol,integrations | N | Y | M | apiome-rest |
| 9.4 ✅ | Protobuf lint pack | wrap `buf lint` (MINIMAL/BASIC/STANDARD) | multi-protocol,linting | Y | Y | S | apiome-rest |
| 9.5 ✅ | Protobuf breaking | wrap `buf breaking` (WIRE/WIRE_JSON) | multi-protocol,version-control | Y | Y | M | apiome-rest |
| 9.6 ✅ | gRPC source card + CLI + fixtures | UI/CLI source (file + reflection URL) + fixtures | multi-protocol,ui,devex,mvp | Y | Y | S | apiome-ui,apiome-cli |

### MFI-9.1 — .proto → FileDescriptorSet  ·  **#3764**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/proto_descriptor.py`. Two layers: a compiler-free **read layer** (`read_file_descriptor_set(bytes)`) parses a binary `FileDescriptorSet` with `google.protobuf.descriptor_pb2` and extracts per-file syntax/edition (proto2/proto3/`editions` → `2023`/`2024`), package, imports + public deps, message/enum/service counts, and an import-vs-target flag, rolled into a serializable `DescriptorSetSummary`; and a **compile layer** (`compile_proto_descriptor_set(files)`) that materialises the supplied `.proto`s plus a minimal buf-v2 `buf.yaml` into a scratch module, shells out to the bundled `buf` (`buf build <scratch> --as-file-descriptor-set --output …binpb`, imports included so the set is self-contained) through the MFI-5.1 toolchain runner (no-network sandbox), and reads the binary descriptor back from disk — directed to a file because the runner returns stdout as UTF-8 text, which would corrupt the binary blob. The bytes are the canonical artifact the MFI-3.1 fingerprint hook hashes; the parsed `FileDescriptorSet` message is handed to MFI-9.2 as-is. A non-compiling proto raises `ProtoCompileError` carrying `buf`'s diagnostics (syntax error / unresolved import); a missing `buf` degrades to "format unavailable" (MFI-5.2). Path inputs are validated (no absolute/`..`/non-`.proto`) before anything spawns. Added the `protobuf>=5.28.0` dependency. Multi-file proto3 + Editions 2023 compile end-to-end (committed fixtures under `tests/fixtures/proto/`, gated real-`buf` e2e); Editions 2024 is recognised/labelled by the read layer. Docs in `apiome-rest/docs/proto_descriptor.md`; 29 tests in `tests/test_proto_descriptor.py` (+3 gated e2e); full rest suite green (2515 passed). apiome-rest 1.57.0 → 1.58.0.
- **Problem.** Hand-parsing `.proto` is fragile; the canonical artifact is the compiled descriptor set.
- **Solution / Scope.** Use **`buf build`** (or `protoc --descriptor_set_out`) via the runner to produce a `FileDescriptorSet`, resolving `import`s and Editions. Read with `google.protobuf.descriptor_pb2` in Python.
- **Acceptance Criteria.** Multi-file proto compiles to a descriptor set; Editions 2023/2024 + proto3 handled.
- **Dependencies / Parallelism.** After 5.1, 2.3. Blocks 9.2.
- **Technical Stack.** Python (`protobuf`), buf.

### MFI-9.2 — Protobuf → canonical model  ·  **#3765**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/proto_normalizer.py`. `ProtoNormalizer` (self-registered under the `protobuf` format key, paradigm `RPC`) consumes the MFI-9.1 `CompiledDescriptorSet` (or a bare `google.protobuf.FileDescriptorSet`/its bytes) and walks the typed descriptor messages — no re-parse. Services → `Service` (`pkg.Service`); methods → `Operation` (`pkg.Service.Method`, `kind=REQUEST_RESPONSE`) with `StreamingMode` derived from the client/server streaming flags (unary→`NONE`, client→`CLIENT`, server→`SERVER`, both→`BIDIRECTIONAL`) and the input/output types as request/response `Message`s (`#request`/`#response`); messages → `Type` (`RECORD`, nested types parent-prefixed `pkg.Outer.Inner`) with each `CanonicalField` keyed `pkg.Message.field` keeping its **field number**; enums → `Type` (`ENUM`) preserving value numbers + order. `oneof` membership is recorded in field/type `extras` (the synthetic proto3-`optional` wrapper excluded, flagged `proto3_optional` instead); `reserved` ranges/names are preserved in type `extras`; a `map<K,V>` synthetic `*Entry` becomes a `MAP` type the field references directly. Compiler-pulled imports (well-known types, transitive deps — flagged `is_import` by 9.1) are skipped, so an imported type is a `TypeRef` by key with no local `Type`. Pure + order-normalized, so the MFI-3.1 fingerprint is invariant to declaration order / doc-only edits yet flips on a streaming / field-number / oneof / reserved change. Docs in `apiome-rest/docs/proto_normalizer.md`; 43 tests in `tests/test_proto_normalizer.py` (+2 gated real-`buf` e2e over the committed fixtures); full rest suite green. apiome-rest 1.58.0 → 1.59.0.
- **Problem.** Map services/methods/messages into the canonical model with stable keys.
- **Solution / Scope.** Services→`api_service`, methods→`api_operation` (unary/client/server/bidi streaming flags, input/output type), messages→`api_type`/`api_field` keyed by **field number** (+ oneof, reserved). Exclude comments/order from the hash.
- **Acceptance Criteria.** Streaming flags + field numbers preserved; fingerprint stable; round-trips.
- **Dependencies / Parallelism.** After 9.1, 2.1. Blocks 9.5.
- **Technical Stack.** Python.

### MFI-9.3 — gRPC live discovery (reflection)  ·  **#3766**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/grpc_reflection.py`. `discover_endpoint(target, …)` crawls a **running** gRPC server's Server Reflection surface into the same `CompiledDescriptorSet` the MFI-9.1 file path produces, so it flows into the MFI-9.2 `ProtoNormalizer` unchanged. It validates the target host with the SSRF guard **before** opening a channel (new `ssrf_guard.validate_host()`, the bare-`host:port` companion to `validate_url`; `_host_of` strips scheme/`user:pass@`/port incl. bracketed IPv6), attaches auth as lower-cased gRPC **metadata** from the shared credential-vault model (`mcp_auth.build_auth_headers`: `none`/`bearer`/`header`/`oauth2`), then calls `ListServices` and `FileContainingSymbol` per service. The pure `build_descriptor_set` seam dedups the returned `FileDescriptorProto`s by name, orders them deterministically (stable MFI-3.1 fingerprint independent of reflection response order), flags files declaring a discovered service as targets (pulled-in deps as imports), and packs a `FileDescriptorSet` whose bytes feed `read_file_descriptor_set`; `result.compiled()` rebuilds the descriptor for normalization. The crawl tries the modern **`grpc.reflection.v1`** service and **falls back to `grpc.reflection.v1alpha`** on `UNIMPLEMENTED` — driving the bidi `ServerReflectionInfo` stream directly via `channel.stream_stream` with the version-specific method path (the v1/v1alpha wire protocol is identical; `grpcio-reflection` ships v1alpha stubs only). Validity is a return value: reflection disabled / server unreachable / no services → `GrpcReflectionResult(ok=False, reason=…)`; only an unsafe target (`SSRFError`) or malformed credential (`CredentialPayloadError`) raises `GrpcReflectionError` (4xx). A `transport_factory` DI seam lets the unit tests drive crawl/fallback/assembly with no network; a real in-process gRPC server (`grpcio-reflection`) exercises the genuine `stream_stream` wiring, the real `v1 → v1alpha` fallback, and the end-to-end flow into MFI-9.2. Two caps (file count + total bytes) bound a hostile server. Added the `grpcio` + `grpcio-reflection` dependencies. Docs in `apiome-rest/docs/grpc_reflection.md`; 35 tests in `tests/test_grpc_reflection.py`. The MFI-9.6 source card/CLI wires this into the import pipeline. apiome-rest 1.59.0 → 1.60.0.
- **Problem.** Many gRPC services expose their schema only at runtime.
- **Solution / Scope.** A discovery path that connects to a running server's **`grpc.reflection.v1`** service (`ListServices`, `FileContainingSymbol`), assembles `FileDescriptorProto`s into a descriptor set, then normalizes (9.2). Uses `grpcio-reflection`. Network opt-in via 5.3 with SSRF guard + auth (reuse MCP credential vault patterns).
- **Acceptance Criteria.** Reflection on a sample server yields the full surface; falls back to v1alpha; auth/SSRF handled.
- **Dependencies / Parallelism.** After 9.1, 5.3. Parallel with 9.4.
- **Technical Stack.** Python (`grpcio-reflection`).

### MFI-9.4 — Protobuf lint pack  ·  **#3767**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/proto_lint.py`. Two halves rolled into one score by the MFI-4.1 lint engine (so the 0–100 / A–F / fingerprint formula is identical to every other format). **Native pack** (`ProtobufRulePack`, self-registered under the `protobuf` format key the MFI-9.2 normalizer emits) — three pure, deterministic rules over the canonical model, the checks `buf`'s default categories do not cover but are decidable on one descriptor set: `protobuf.package-version-suffix` (the package's last component is a buf-style version, `foo.v1`/`foo.v1beta1`; mirrors `PACKAGE_VERSION_SUFFIX` so the always-on score is meaningful without `buf`), `protobuf.field-no-required` (a proto2/Editions `required` field — a one-way door — read off `extras['label']`), and `protobuf.reserved-on-deletion` (a gap in a message's field numbers / enum's value numbers that no `reserved` range covers — the single-artifact heuristic for "always reserve a deleted number", honouring message half-open vs enum inclusive reserved ranges, flagging only gaps strictly between the min/max used number). **`buf lint` wrap** — `run_buf_lint(files)` materialises the `.proto`s into a scratch buf module (reusing MFI-9.1's `materialize_proto_module`, plus a `buf.yaml` enabling the **STANDARD + COMMENTS** lint categories) and runs `buf lint --error-format=json` through the MFI-5.1 toolchain runner (no-network sandbox); lint violations (`buf` exit 100) are the normal outcome and are read off stdout, while an operational failure (absent/timeout/non-building proto) raises `ProtoLintError`. `buf_findings()` maps buf's newline-delimited JSON into `LintFinding`s namespaced `protobuf.buf.<type>` at `warning` severity (buf reports no per-finding severity), and `parse_buf_lint_output()` tolerates blank/non-JSON lines. The halves merge in `lint_protobuf_result(model, buf_report=None)` (pure; buf is opt-in and degrades gracefully to native + common) and the end-to-end `lint_protobuf(files)` (compile → normalize → buf lint → score). Docs in `apiome-rest/docs/proto_lint.md`; 28 tests in `tests/test_proto_lint.py` (native rules through the real MFI-9.2 normalizer over synthetic descriptor sets, buf mapping/parse, `run_buf_lint` via an injected fake runner, merge + degradation; +1 gated real-`buf` e2e over the committed fixtures); full rest suite green (2620 passed, 28 skipped). apiome-rest 1.60.0 → 1.61.0.
- **Solution / Scope.** Wrap **`buf lint`** (categories MINIMAL→STANDARD, COMMENTS) via 4.3 + native checks (versioned package `foo.v1`, no `required`, `reserved` on deletion).
- **Acceptance Criteria.** Lints a sample; findings scored.
- **Dependencies / Parallelism.** After 4.3, 9.2. Parallel with 9.5.
- **Technical Stack.** Python + buf.

### MFI-9.5 — Protobuf breaking  ·  **#3768**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/proto_breaking.py`, the Protobuf provider on the MFI-3.3 breaking-change classifier SPI (mirroring MFI-10.5's GraphQL-Inspector wrap and MFI-8.4's `@asyncapi/diff` wrap). `ProtobufBreakingChangeClassifier` (self-registered under the `protobuf` format key the MFI-9.2 normalizer emits) **subclasses** the format-agnostic `BuiltinBreakingChangeClassifier`, so the *synchronous, pure* SPI already grades a Protobuf diff from structure alone — and that baseline is already wire-aware (the built-in ruleset treats a reused `field_number` and a changed `type` as `breaking`, an added optional field as `safe`), so the acceptance cases hold with no `buf` binary. The authoritative **`buf breaking`** overlay is the async `classify_async` / convenience `classify_protobuf(base, target, against_files=…, target_files=…, strictness=…)`: `run_buf_breaking(target_files, against_files, strictness=…)` materialises the **new** and **baseline** `.proto`s into two scratch `buf` modules — the new one carrying a `buf.yaml` enabling the one breaking category for the strictness (`buf` reads breaking rules from the *input* module; `buf_breaking_module_yaml`), the baseline one carrying MFI-9.1's build-only `BUF_MODULE_YAML` — and runs `buf breaking <new> --against <baseline> --error-format=json` through the MFI-5.1 toolchain runner (no-network sandbox); breaks (`buf` exit 100) are the normal outcome and are read off stdout, while an operational failure (absent/timeout/non-building proto) raises `ProtoBreakingError`. `breaking_changes()` maps buf's newline-delimited JSON into `ProtoBreakingChange`s namespaced `protobuf.buf-breaking.<type>` at `breaking` severity (`buf breaking` emits only breaks; the *strictness* — the configurable `BufBreakingStrictness` `WIRE`/`WIRE_JSON`/`PACKAGE`/`FILE`, default `WIRE_JSON` for services — is what controls which changes count), and `parse_buf_breaking_output()` tolerates blank/non-JSON lines. Because `buf breaking`'s machine output is *file-scoped* (a proto file + line/column + rule `type`), not a schema-coordinate that joins one canonical entity, the overlay applies buf's verdict at that granularity: it forces the **overall** severity to `breaking` when buf finds a break, and **caps** structural over-approximations to `dangerous` when buf finds the diff wire/JSON-compatible (a wire-compatible field deletion is compatible-by-the-letter, review warranted); the per-change attribution stays the structural baseline's, and it degrades gracefully back to that baseline when the sources or the tool are unavailable. Registered in `breaking_change.load_format_breaking_change_classifiers`. Docs in `apiome-rest/docs/proto_breaking.md`; 26 tests in `tests/test_proto_breaking.py` (structural baseline through the real MFI-9.2 normalizer over synthetic descriptor sets, strictness config, buf mapping/parse, `run_buf_breaking` via an injected fake runner, overlay force/cap + degradation; +2 gated real-`buf` e2e over `string→int32` type-change vs additive `.proto` sources); full rest suite green (2646 passed, 30 skipped). apiome-rest 1.61.0 → 1.62.0.
- **Solution / Scope.** Wrap **`buf breaking`** with a configurable strictness (default WIRE_JSON for services) via 3.3; map to severities.
- **Acceptance Criteria.** Detects a field-number reuse / type change as breaking; safe additions pass.
- **Dependencies / Parallelism.** After 9.2, 3.3. Parallel with 9.4.
- **Technical Stack.** Python + buf.

### MFI-9.6 — gRPC source card + CLI + fixtures  ·  **#3769**  ·  ✅ **Done**
- **Status.** Implemented as `apiome-rest/src/app/grpc_import_source.py` — the **`ImportSource` adapter** (MFI-1.1) that makes the gRPC / Protobuf work of MFI-9.1…9.5 reachable from the UI source card and the CLI, mirroring the AsyncAPI (MFI-8.5) and GraphQL (MFI-10.6) adapters. `GrpcImportSource` (key `grpc`, paradigm `RPC`, formats `("protobuf",)`, `supports_live_discovery=True`, `share-2` icon) is a thin seam over machinery that already exists: **detect** sniffs `.proto` source text (`syntax`/`edition`/top-level `message`/`service`/`enum`/`package` markers, no `buf`); **parse** compiles an uploaded `.proto` via the MFI-9.1 `buf build` layer (`compile_proto_descriptor_set`) into a `CompiledDescriptorSet`, surfacing a non-compiling proto / absent `buf` as a clean `ImportSourceError` (diagnostics verbatim); **discover** is the live-reflection counterpart, wrapping the SSRF-guarded MFI-9.3 crawler (`discover_endpoint`) → `CompiledDescriptorSet` so a running server catalogs a version through the *same* canonical path as a file; **normalize** delegates to the registered MFI-9.2 `ProtoNormalizer` (`protobuf` key); **lint** delegates to MFI-9.4 `lint_protobuf_result` (native + common packs score deterministically without `buf`); **fingerprint/diff** use the canonical defaults (the MFI-9.5 `buf breaking` overlay layers on the diff). Since `compile_proto_descriptor_set` is a coroutine driving the `buf` subprocess but the SPI `parse()` is synchronous and called from the service's running loop, the compile runs on a dedicated worker-thread event loop with a fresh sibling `ToolchainRunner` (loop-bound semaphore) — the same bridge the AsyncAPI adapter uses. Registering the adapter (`register=True`, wired into `load_builtin_import_sources`) is **all the UI and CLI need**: both are data-driven off `GET /v1/import/sources`, so a `grpc` card (file/url/paste/**discovery** inputs) appears in the source-card grid and `apiome import grpc <input>` rides the MFI-1.4 generic dispatch — **no new UI or CLI command code**. Because the adapter now claims `protobuf`, the MFI-1.5 auto-detector reports a `.proto` as **importable** (`source_key: grpc`) rather than sniffer-only. A self-contained `echo.v1` gRPC fixture lives in `apiome-rest/tests/fixtures/proto/grpc/echo.proto` with a CLI mirror under `apiome-cli/tests/fixtures/`. Tests: `apiome-rest/tests/test_grpc_import_source.py` (descriptor + registry registration, detect, buf-free normalize/lint/fingerprint over a synthetic `FileDescriptorSet`, the parse bridge + compile/descriptor error mapping via a monkeypatched compiler, the discover seam success/disabled/error via a monkeypatched crawler, and a gated real-`buf` e2e over the fixture); `apiome-cli/tests/test_import_grpc.py` (drives `import grpc` over the `.proto` fixture + `--url`/`--dry-run`/`--list`/unknown-format against a mocked REST); `apiome-ui/tests/importSourceCatalog.test.ts` (gRPC descriptor → usable file-panel card + `share-2` icon resolution). Docs: new `apiome-rest/docs/grpc_import.md`. apiome-rest 1.62.0 → 1.63.0; apiome-cli 0.14.0 → 0.15.0; apiome-ui 0.35.0 → 0.36.0.
- **Solution / Scope.** UI/CLI source supporting `.proto` upload **and** a reflection URL; `apiome import grpc`; fixtures. Coordinate with **#1384 / #1427** (breaking-change overlap).
- **Acceptance Criteria.** Import from file and from a live reflection endpoint both catalog a version.
- **Dependencies / Parallelism.** After 9.2/9.3, 1.3/1.4.
- **Technical Stack.** Next.js, Typer.

---

## MFI-EPIC-10 — GraphQL (graph) · MVP  ·  **#3725**

SDL (Sept 2025 / Oct 2021). **Live: introspection.** Schema Coordinates as stable keys. Diff via
GraphQL-Inspector (breaking/dangerous/non-breaking); lint via graphql-eslint.
Sources: https://spec.graphql.org/September2025/ · https://graphql.org/learn/introspection/ · https://github.com/graphql-hive/graphql-inspector

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 10.1 | GraphQL SDL parse / build schema | `graphql-core` build_schema; multi-file merge | multi-protocol,import,python,mvp | N | Y | M | apiome-rest |
| 10.2 | GraphQL → canonical model | types/fields/args/directives keyed by Schema Coordinate | multi-protocol,import,mvp | N | Y | M | apiome-rest |

### MFI-10.1 — GraphQL SDL parse / build schema  ·  **#3770**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/graphql_parser.py` — a pure-Python service over **`graphql-core`** (added as a runtime dependency; the GraphQL ecosystem is first-class in Python, so unlike the AsyncAPI seam there is no Node toolchain). One call **parses** each SDL source (a syntax error becomes a per-source `GraphQlDiagnostic` with the offending file label + line/column, not a raise), **merges** multiple files with `graphql-tools` `mergeTypeDefs` semantics (same-named type/interface/input/enum/union definitions have their fields/values/members **unioned** into the first occurrence — a same-named field with a *different* type is reported as a conflict; `extend type` blocks pass through for the builder to apply), **builds** the merged AST into a `GraphQLSchema`, and **validates** it (`validate_sdl` for document-level problems — unknown types, conflicting/duplicate definitions — then `validate_schema` for schema-level ones — a missing `Query` root, a bad interface implementation). The **root operation types** (`query`/`mutation`/`subscription`, honouring `schema { query: … }` renames) are captured into `GraphQlRootOperations`, and the schema is re-printed to **canonical SDL** on `GraphQlParseResult.sdl` (the serializable artifact the MFI-10.2 mapping stores). An invalid schema is a *return value* (`ok=False` + error diagnostics), never an exception; callers wanting the live `GraphQLSchema` (MFI-10.2, no re-parse) use `build_schema_from_sources(...)` / `build_graphql_schema(...)`, which raise `GraphQlParseError`. Tests: `tests/test_graphql_parser.py` (29 cases, all real — no gating) — valid single + all type-kind capture, root/custom-root capture, canonical-SDL round-trip, the three invalid families (syntax w/ source+location, unknown type, missing root, bad interface, in-file dup field), multi-file merge (distinct + `extend`, field/enum/union union, identical-redeclare no-op, cross-file type conflict, per-file syntax attribution, same-name-different-kind), a realistic 3-file blog fixture under `tests/fixtures/graphql/`, source coercion (string/pair/model), the build-or-raise helpers, and the result-model surface (`errors`/`raise_if_invalid`/serializable round-trip). Full rest suite green (2345 passed, 15 skipped). apiome-rest 1.51.0 → 1.52.0.
- **Solution / Scope.** Parse SDL with **`graphql-core`** (`build_schema`/`validate`); merge multi-file via `graphql-tools` semantics. Capture root operation types.
  - Source: https://github.com/graphql-python/graphql-core
- **Acceptance Criteria.** Valid SDL builds; invalid reports errors; multi-file merges.
- **Dependencies / Parallelism.** After 2.3. Blocks 10.2.
- **Technical Stack.** Python (`graphql-core`).

### MFI-10.2 — GraphQL → canonical model  ·  **#3771**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/graphql_normalizer.py` — a pure `Normalizer` (MFI-2.3 SPI) that consumes the *built* `graphql-core` `GraphQLSchema` from MFI-10.1 (`build_schema_from_sources`, no SDL re-parse) and maps it to a `CanonicalApi` of paradigm `GRAPH`, everything keyed by **GraphQL Schema Coordinate**. Named types → `Type`: object/interface/input-object → `RECORD`, union → `UNION` (member keys), enum → `ENUM` (values w/ deprecation), custom scalar → `SCALAR`; the GraphQL family (`object`/`interface`/`input`/`scalar`), implemented interfaces, and a scalar's `@specifiedBy` URL ride in `extras` so the collapse is lossless. Built-in scalars (`Int`/`Float`/`String`/`Boolean`/`ID`) and introspection types (`__*`) are excluded, as is each root operation type — `Query`/`Mutation`/`Subscription` (honouring `schema { query: … }` renames) become `Service`s whose fields become `Operation`s of kind `QUERY`/`MUTATION`/`SUBSCRIPTION` (subscriptions server-streaming), with field arguments → `Parameter`s (`Query.user#arg.id`) and the field return type → the operation's lone response `Message` (`Query.user#response`). Fields key `Type.field`; a field's own arguments (GraphQL allows them anywhere) ride in the field `extras`. **Nullability/list wrappers are reproduced level-by-level on `TypeRef`** (`String!` → `nullable=False`; `[String!]!` → list(`nullable=False`) of `String`(`nullable=False`)) — the acceptance criterion. Directives: custom directive *definitions* (built-ins excluded) are captured on the artifact `extras`; *applied* directives ride in each entity's `extras` (`@deprecated`/`@specifiedBy` are consumed into the `deprecated` flag / `specified_by_url` instead of being echoed). Since the fingerprint payload keeps `extras` verbatim but strips `raw`/descriptions, every wrapper, argument and directive contributes to a **stable** semantic fingerprint while doc-only edits don't flip it. The normalizer self-registers under `graphql` (added to `load_builtin_import_sources` ahead of the MFI-10.5 import adapter); `Keys` gained `graphql_argument`/`graphql_response` coordinate builders. Tests: `tests/test_graphql_normalizer.py` (36 cases, all real — no gating) feed the real MFI-10.1 parser output through the normalizer: artifact shape/registration, every type-family kind + extras, all four wrapper shapes (incl. operation response), field args/deprecation/applied-directives, services/operations/parameters/response messages, directive-definition capture, determinism + idempotence + JSONB round-trip, and fingerprint stability (order/doc-invariant; flips on nullability/list/argument/applied-directive/directive-definition change). Full rest suite green (2399 passed, 20 skipped). apiome-rest 1.52.0 → 1.53.0.
- **Solution / Scope.** Types (object/interface/union/enum/input/scalar + LIST/NON_NULL wrappers), fields, args, input fields, enum values, directives → canonical model keyed by **Schema Coordinate** (`Type.field`). Preserve nullability/list wrappers in the hash.
- **Acceptance Criteria.** Nullability/list wrappers preserved; fingerprint stable.
- **Dependencies / Parallelism.** After 10.1, 2.1. Blocks 10.5.
- **Technical Stack.** Python.

### MFI-10.3 — GraphQL live introspection  ·  **#3772**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/graphql_introspection.py` — the live-endpoint counterpart to the file path: where MFI-10.1 turns *SDL text* into a built schema, this runs the standard introspection query against a **live endpoint** and rebuilds the schema from the `__schema` response, re-printing it to the **same canonical artifact** (`GraphQlParseResult`) the file path produces so it flows straight into the MFI-10.2 normalizer. One call (`introspect_endpoint`) **POSTs** `get_introspection_query()` over an **SSRF-guarded** httpx client (`ssrf_guard.build_guarded_client` — the URL is rejected up front *and* every redirect hop is re-validated, so a tenant URL can't be aimed at internal/metadata hosts), attaches auth from the **credential vault** model (`mcp_auth.build_auth_headers` — the same `none`/`bearer`/`header`/`oauth2` mapping MCP discovery uses; the payload arrives already decrypted, no keys read here), **rebuilds** via `build_client_schema` → `print_schema` → the MFI-10.1 parser, and **falls back** to caller-supplied uploaded SDL when introspection is **disabled** (the server answers with an *"introspection is not allowed"* error, a 4xx, or is briefly unreachable). Validity and the fallback decision are a **return value** (`GraphQlIntrospectionResult` carrying `ok`/`source` (`introspection`|`fallback-sdl`)/`introspection_ok`/`fallback_used`/`reason`/`parse_result`), never an exception — only a misconfigured request (unsafe URL or malformed credential) raises `GraphQlIntrospectionError` for a 4xx. Pure `graphql-core` seams (`build_introspection_query`/`schema_from_introspection`/`sdl_from_introspection`) are exported for reuse. The module is a service consumed by the MFI-10.6 import adapter (not yet wired into `load_builtin_import_sources`), mirroring how 10.1/10.2 landed ahead of the adapter. Tests: `tests/test_graphql_introspection.py` (25 cases, all real — the network is the only mock, fed the *real* introspection response of a built schema via `httpx.MockTransport`): sample-endpoint introspection with canonical-SDL equality + posted-query assertion, the disabled-introspection fallback (used / reason-only-without-fallback / fallback-also-invalid), the full unavailable matrix (4xx, network error, non-JSON, missing `__schema`, malformed payload, spec-legal partial-data-with-errors uses the schema), credential-vault auth (bearer/custom-header/none/extra-headers-don't-override/malformed-raises), and the SSRF guard (private host, non-http scheme, redirect-to-private hop). Full rest suite green (2424 passed, 20 skipped). apiome-rest 1.53.0 → 1.54.0.
- **Solution / Scope.** Run `getIntrospectionQuery()` against an endpoint, `build_client_schema` → SDL → normalize. Handle introspection-disabled (fall back to uploaded SDL); auth via credential vault.
- **Acceptance Criteria.** Introspects a sample endpoint; graceful fallback when disabled.
- **Dependencies / Parallelism.** After 10.1, 5.3. Parallel with 10.4.
- **Technical Stack.** Python (`graphql-core`, httpx).

### MFI-10.4 — GraphQL lint pack  ·  **#3773**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/graphql_lint.py` — a `GraphqlRulePack` (MFI-4.1 `RulePack` SPI) registered under the `graphql` format key (the one the MFI-10.2 normalizer emits), so a GraphQL artifact is linted by the always-on engine (`lint_canonical_model`) and scored through the same 0–100 / A–F / `report_fingerprint` formula as every other format (MFI-4.2). The native pack is **pure over the canonical model** (no I/O, no Node — mirroring the pure-Python GraphQL toolchain of MFI-10.1/10.2/10.3) and encodes the SDL-checkable semantics of the three `graphql-eslint` configs the scope names: **naming-convention** — `graphql.naming-type-pascal-case` (type-like names PascalCase), `graphql.naming-field-camel-case` (object/input **and** root-operation fields camelCase), `graphql.naming-argument-camel-case`, `graphql.naming-enum-value-upper-case`; **require-description** for the GraphQL-specific gaps the cross-format common pack does **not** already cover — `graphql.enum-value-missing-description`, `graphql.argument-missing-description` (type/field/operation/message descriptions are the common pack's job, not duplicated here); and **schema-recommended** — `graphql.require-deprecation-reason` (a `@deprecated` entity with a blank reason; `graphql-core` fills a bare `@deprecated` with the spec-default reason, so this native rule fires on an *explicit* `reason: ""` — the authoritative bare-`@deprecated` check is graphql-eslint's own rule). The authoritative `graphql-eslint` verdicts (`schema-recommended` + `require-description` + `naming-convention`) are a Node linter; rather than re-implement every rule, `eslint_findings(...)` **wraps** them — mapping graphql-eslint's standard ESLint JSON output into `LintFinding`s namespaced `graphql.eslint.*` (severity folded `2`→error / `1`→warning / else→info, path `{file}:{line}:{col}`), to be fed by the generic external-linter adapter (MFI-4.3, via the polyglot toolchain runner). `lint_graphql_result(model, eslint_report=None)` merges graphql-eslint + native + common (degrading gracefully — the native + common packs always produce a deterministic score with no report), and `lint_graphql(raw, ...)` runs it end-to-end from raw SDL (parse → normalize → lint). Tests: `tests/test_graphql_lint.py` (17 cases, all real, no gating — pure Python so the end-to-end native-rule tests run the real MFI-10.1 parser + MFI-10.2 normalizer): a clean schema is silent + each defect fires its rule, registry registration, the graphql-eslint mapping (namespacing/severity-fold/fatal-id/path/empty-degradation), and the merge pulling graphql-eslint findings into the score. apiome-rest 1.54.0 → 1.55.0.
- **Solution / Scope.** Wrap **graphql-eslint** (`schema-recommended`, `require-description`, `naming-convention`) via 4.3 + native checks.
- **Acceptance Criteria.** Lints SDL; findings scored.
- **Dependencies / Parallelism.** After 4.3, 10.2. Parallel with 10.5.
- **Technical Stack.** Python + Node.

### MFI-10.5 — GraphQL breaking  ·  **#3774**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/graphql_diff.py` — the **GraphQL provider** on the MFI-3.3 breaking-change classifier SPI (`app.breaking_change`), mirroring MFI-8.4's `@asyncapi/diff` integration. `GraphQlBreakingChangeClassifier` subclasses the format-agnostic `BuiltinBreakingChangeClassifier` and registers under the `graphql` format key (the one the MFI-10.2 normalizer emits), so the **synchronous, pure** SPI dispatch (`breaking_change.classify`) already grades a GraphQL diff from structure alone (removed type/field breaking, added safe, an enum's variant set or a parameter list moving dangerous) even with no Node toolchain present — pulled in lazily via `breaking_change.load_format_breaking_change_classifiers()`. The **authoritative** grading is the async `classify_async` (+ convenience `classify_graphql(base, target)`): it runs **GraphQL-Inspector's `diff`** over the two canonical SDL strings MFI-10.2 preserved on `CanonicalApi.raw` (fed to a new bundled `graphql-inspector-diff` Node tool — `toolchain/graphql-inspector-diff.mjs` wrapping `@graphql-inspector/core@6.2.0` + `graphql@16.9.0`, registered in `toolchain_packaging.py` like the MFI-8.4 tool — as `{"old":…,"new":…}` SDL strings on stdin, each built into a `graphql-js` schema before diffing), then **overlays** the tool's `BREAKING`/`DANGEROUS`/`NON_BREAKING` verdict onto the structural grades wherever a change's **schema-coordinate path** (GraphQL-Inspector's own `Type.field`/bare-`Type`/`Enum.VALUE` notation, the same grammar `app.normalizer.Keys` assigns) resolves against a key the diff actually reports — an exact `Type.field`/`Root.field` match joins a field/operation, falling back to the bare leading segment folds an enum-value/union-member change onto its *owning type* exactly as the structural baseline already grades it. A change that joins nothing (a custom directive, deep schema-root metadata) keeps the conservative structural grade. Unlike `@asyncapi/diff`, GraphQL-Inspector always assigns one of its three criticality levels (no "unclassified" tier), so the mapping onto `Severity` is total. The path **degrades gracefully** to the structural baseline when the SDL or the `graphql-inspector-diff` tool is unavailable; the result is the standard `ClassificationResult`, 1:1 with the diff's changes (rule ids `graphql-inspector-diff.<CHANGE_TYPE>` for tool verdicts), so severities surface on the diff view. Tests: `tests/test_graphql_diff.py` (the tool seam over a fake runner — wrapper contract, malformed changes skipped, infra failures → `GraphQlDiffError`, both SDL strings on stdin; the join helper — field/operation exact match, enum-value/union-member folding onto the owning type, argument changes folding onto the owning operation, non-joining changes; the overlay proving the acceptance criterion — a removed field graded BREAKING, an added enum value graded DANGEROUS, a plain addition graded SAFE; graceful degradation; SPI registration + sync structural dispatch; determinism + JSON round-trip; and a gated end-to-end suite over the real bundled GraphQL-Inspector), built on the real MFI-10.1/10.2 parser + normalizer; `test_toolchain_packaging.py` expects the new key. Docs: new `docs/graphql_diff.md`; `toolchain_packaging.md` extended; Dockerfile installs `@graphql-inspector/core` + `graphql` and copies the wrapper. Full rest suite green (2429 passed, 22 skipped — includes 2 new gated skips for the bundled tool not being installed in dev sandboxes). apiome-rest 1.55.0 → 1.56.0.
- **Solution / Scope.** Wrap **GraphQL-Inspector** `diff` → breaking/dangerous/non-breaking, mapped to severities (3.3).
- **Acceptance Criteria.** Removing a field = breaking; adding an enum value = dangerous; correctly surfaced.
- **Dependencies / Parallelism.** After 10.2, 3.3. Parallel with 10.4.
- **Technical Stack.** Python + Node.

### MFI-10.6 — GraphQL source card + CLI + fixtures  ·  **#3775**  ·  ✅ **Done**
- **Status.** Implemented as `src/app/graphql_import_source.py` — the `ImportSource` adapter (MFI-1.1) that makes the GraphQL work of MFI-10.1…10.5 reachable from the **UI source card** and the **CLI `import` command**, mirroring the AsyncAPI adapter (MFI-8.5) and adding the **live-introspection** dimension GraphQL is the first source to need. `GraphQlImportSource` (`register=True`, key `graphql`, paradigm `GRAPH`, `waypoints` icon, input kinds file/url/paste/**discovery**, `supports_live_discovery=True`) is a thin seam over machinery that already exists: **detect** sniffs SDL by a top-level definition keyword / `.graphql`·`.gql` extension / a captured `__schema` introspection payload (never raises); **parse** builds a `graphql-core` `GraphQLSchema` from SDL via the MFI-10.1 parser (an invalid schema → a clean `ImportSourceError`), transparently rebuilding a captured introspection response (`{"data": {"__schema": …}}` or a bare `__schema` object) to canonical SDL first so a discovery document flows through the same path; **normalize** delegates to the registered `GraphQlNormalizer` (MFI-10.2) under the `graphql` format key; **lint** runs `lint_graphql_result` (MFI-10.4), pure over the canonical model so the revision always rolls up to a deterministic score/grade/`report_fingerprint` (the authoritative `graphql-eslint` findings fold in via the MFI-4.3 adapter when present); **fingerprint**/**diff** use the canonical-model defaults (the MFI-10.5 breaking overlay layers onto the diff view). The new **`introspect()`** method is the discovery counterpart to `parse()`: it runs the SSRF-guarded MFI-10.3 introspection service against a live endpoint — POSTing the standard introspection query, rebuilding the schema, and **falling back** to uploaded SDL when introspection is disabled — and returns the built schema, so a live endpoint catalogs a version through the same canonical path SDL does (a live-introspected model fingerprints **identically** to the same schema imported from SDL — the acceptance criterion). Wired into `load_builtin_import_sources` (replacing the bare `graphql_normalizer` import), so `graphql` now surfaces from `GET /v1/import/sources` and `detect_format` reports it **importable** (`source_key="graphql"`). UI + CLI are data-driven off the registry: a `graphql` source card (waypoints icon, graph paradigm, file/url/paste/discovery) appears in the grid with no UI change, and `apiome import graphql <input>` rides the MFI-1.4 generic dispatch with no new CLI command code. Tests: REST `tests/test_graphql_import_source.py` (19 cases, all real — pure-Python GraphQL toolchain, the introspection endpoint's network the only mock via `httpx.MockTransport`): descriptor + registry registration, SDL/filename/introspection-payload detection, SDL parse (+ invalid-schema mapping + captured-introspection parse), normalize → graph model + determinism + error boundaries, lint roll-up, and the live-introspection seam (success cataloging a version, the disabled-endpoint SDL fallback, the no-fallback failure, an SSRF-rejected endpoint); `test_format_detection.py` / `test_import_sources_routes.py` updated (GraphQL now importable, protobuf the remaining sniffer-only example); CLI `tests/test_import_graphql.py` (generic-dispatch over SDL fixtures, `--url`, `--dry-run`, `--list`); UI `importSourceCatalog.test.ts` (GraphQL source-card coverage + waypoints icon). Fixtures: `blog-graphql.graphql` + `inventory-graphql.gql` under `apiome-cli/tests/fixtures/`. Docs: new `apiome-rest/docs/graphql_import.md`. Full rest suite green (2486 passed, 22 skipped); full cli suite green (1113 passed). apiome-rest 1.56.0 → 1.57.0; apiome-cli 0.13.0 → 0.14.0; apiome-ui 0.34.0 → 0.35.0.
- **Solution / Scope.** UI/CLI source for SDL file **and** introspection URL; `apiome import graphql`; fixtures. Coordinate with **#1331 / #2775**.
- **Acceptance Criteria.** Import from SDL and from live introspection both catalog a version.
- **Dependencies / Parallelism.** After 10.2/10.3, 1.3/1.4.
- **Technical Stack.** Next.js, Typer.

---

## MFI-EPIC-11 — OData (queryable REST) · v2  ·  **#3726**

CSDL XML/JSON, OData 4.01 (+ v2/v3 legacy). **Live: `$metadata` + service doc.** Normalize to
CSDL JSON; diff per §5.2.
Sources: https://docs.oasis-open.org/odata/odata-csdl-json/v4.01/odata-csdl-json-v4.01.html

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 11.1 | CSDL parse + validate | XML/JSON → canonical CSDL JSON; OASIS schema validate | multi-protocol,import,validation | N | N | M | apiome-rest |
| 11.2 | OData → canonical model | entity types/sets/functions/actions (param signatures) | multi-protocol,import | N | N | M | apiome-rest |
| 11.3 | OData live discovery | `$metadata` + service document fetch | multi-protocol,integrations | N | N | M | apiome-rest |
| 11.4 | OData lint/validate | OASIS JSON-Schema/XSD + ref/key resolution | multi-protocol,linting | Y | N | S | apiome-rest |
| 11.5 | OData breaking | §5.2 rules (incl. `$schemaversion`) | multi-protocol,version-control | Y | N | M | apiome-rest |
| 11.6 | OData source card + CLI + fixtures | UI/CLI (file + service URL) + v2/v4 fixtures | multi-protocol,ui,devex | Y | N | S | apiome-ui,apiome-cli |

*(Issues 11.1–11.6 follow the adapter template: parse → normalize → live-discover → lint → breaking → UI/CLI. Key notes: normalize CSDL XML→JSON before diffing; hash `(kind, FQ-name, identity)` tuples — operations keyed by ordered parameter signature; OASIS `csdl.schema.json` for validation; handle v2/v3 SAP services. Python via `xmlschema`/`jsonschema`; live via `$metadata`.)*

---

## MFI-EPIC-12 — Avro / Confluent Schema Registry · v2  ·  **#3727**

Avro 1.12; **Confluent Schema Registry REST** (subjects/versions/IDs + compatibility modes). This
epic is special: **compatibility is first-class** and registry crawl is live.
Sources: https://avro.apache.org/docs/1.12.0/specification/ · https://docs.confluent.io/platform/current/schema-registry/develop/api.html

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 12.1 | Avro schema parse + PCF fingerprint | `.avsc`/IDL parse; Parsing Canonical Form + semantic hash | multi-protocol,import,python | N | N | M | apiome-rest |
| 12.2 | Avro → canonical model | records/fields/enums/unions/logical types | multi-protocol,import | N | N | M | apiome-rest |
| 12.3 | Schema Registry discovery | crawl subjects/versions/IDs via REST | multi-protocol,registry,integrations | N | N | M | apiome-rest |
| 12.4 | Avro compatibility engine | BACKWARD/FORWARD/FULL(+TRANSITIVE) as breaking rules | multi-protocol,version-control,validation | N | N | L | apiome-rest |
| 12.5 | Avro lint pack | defaults/doc/aliases/optional-union hygiene | multi-protocol,linting | Y | N | S | apiome-rest |
| 12.6 | Avro source card + CLI + fixtures | UI/CLI (file + registry URL); subject naming strategies | multi-protocol,ui,devex,registry | Y | N | M | apiome-ui,apiome-cli |

### MFI-12.1 — Avro schema parse + PCF fingerprint  ·  **#3782**
- **Solution / Scope.** Parse `.avsc`/IDL with **`fastavro`**/`avro`; compute the **Parsing Canonical Form** fingerprint (CRC-64-AVRO/SHA-256) **and** a richer semantic hash that retains `default`/`aliases`/`order` (PCF strips these — they're evolution-load-bearing). Treat `doc`-only changes as non-breaking.
- **Acceptance Criteria.** PCF + semantic hashes computed; doc-only change flips semantic but not PCF.
- **Dependencies / Parallelism.** After 2.3, 3.1. Blocks 12.2.
- **Technical Stack.** Python (`fastavro`/`avro`).

### MFI-12.3 — Schema Registry discovery  ·  **#3784**
- **Solution / Scope.** Crawl a **Confluent Schema Registry**: `GET /subjects`, `/subjects/{s}/versions`, `/schemas/ids/{id}`, `GET /config[/{s}]` (compat level); dedup by schema ID; record subject naming strategy. Catalog each subject as an artifact with its version history. Auth via credential vault; SSRF guard.
- **Acceptance Criteria.** Crawls a registry; subjects→artifacts with versions + compat level captured.
- **Dependencies / Parallelism.** After 12.1, 5.3. Parallel with 12.2.
- **Technical Stack.** Python (`confluent-kafka[avro]`/`python-schema-registry-client`).

### MFI-12.4 — Avro compatibility engine  ·  **#3785**
- **Solution / Scope.** Implement the breaking classifier as the **Confluent compatibility modes** (BACKWARD/FORWARD/FULL + TRANSITIVE), pivoting on field `default`s; optionally dry-run against a live registry's `POST /compatibility/...`. This is the richest, most valuable diff in the roadmap.
  - Source: Confluent compat table (research brief).
- **Acceptance Criteria.** Classifies add/remove field per mode correctly; TRANSITIVE checks all prior versions; matches registry dry-run on fixtures.
- **Dependencies / Parallelism.** After 12.2, 3.3. Parallel with 12.5.
- **Technical Stack.** Python.

*(12.2, 12.5, 12.6 follow the adapter template. Coordinate with **#239 / #2776 / #3489**.)*

---

## MFI-EPIC-13 — SOAP / WSDL (+XSD) · v2  ·  **#3728**

WSDL 1.1 (+2.0), SOAP 1.1/1.2, XSD 1.0/1.1. **Live: `?wsdl` / `?singleWsdl`.** Resolve imports
before hashing; lint against WS-I Basic Profile.
Sources: https://www.w3.org/TR/wsdl · https://www.w3.org/TR/xmlschema11-1/

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 13.1 | WSDL+XSD parse & import resolution | `zeep`/`xmlschema`; stitch wsdl:import/xsd:import | multi-protocol,import,python | N | N | L | apiome-rest |
| 13.2 | WSDL → canonical model | services/ports/bindings/operations/messages/types | multi-protocol,import | N | N | M | apiome-rest |
| 13.3 | WSDL live fetch | `?wsdl`/`?singleWsdl` retrieval + inline | multi-protocol,integrations | N | N | M | apiome-rest |
| 13.4 | WS-I lint pack | document/literal, unique soapActions, resolvable imports | multi-protocol,linting,validation | Y | N | M | apiome-rest |
| 13.5 | WSDL/XSD breaking | op/MEP/soapAction changes; XSD facet/occurs changes | multi-protocol,version-control | Y | N | L | apiome-rest |
| 13.6 | WSDL source card + CLI + fixtures | UI/CLI (file + ?wsdl URL) + fixtures | multi-protocol,ui,devex | Y | N | M | apiome-ui,apiome-cli |

*(Adapter template. Notes: canonicalize XML + resolve all imports before hashing; "additive = safe" does NOT hold for XSD (strict receivers); no standard XSD-diff — build a ruleset (membrane/soa-model as reference); Python via `zeep`/`xmlschema` (XSD 1.0 **and 1.1**). Prefer `?singleWsdl` to inline the graph.)*

---

## MFI-EPIC-14 — TypeSpec · v2  ·  **#3729**

TypeSpec 1.0 GA; `.tsp` IDL that **compiles** to OpenAPI/JSON-Schema/Protobuf. No live introspection.
**Diff the emitted OpenAPI**, not raw `.tsp`. Versioning via `@typespec/versioning`.
Sources: https://typespec.io · https://typespec.io/docs/libraries/versioning/guide/

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 14.1 | TypeSpec compile via runner | `tsp compile` → OpenAPI/JSON-Schema/Protobuf | multi-protocol,import,typescript | N | N | M | apiome-rest |
| 14.2 | TypeSpec → canonical model | normalize via emitted OpenAPI (reuse OpenAPI normalizer) | multi-protocol,import | N | N | S | apiome-rest |
| 14.3 | TypeSpec lint pack | built-in `tsp` linter diagnostics | multi-protocol,linting | Y | N | S | apiome-rest |
| 14.4 | TypeSpec versioning/diff | `@typespec/versioning` per-version emit → openapi-diff | multi-protocol,version-control | Y | N | M | apiome-rest |
| 14.5 | TypeSpec source card + CLI + fixtures | UI/CLI (.tsp + tspconfig) + fixtures | multi-protocol,ui,devex | Y | N | S | apiome-ui,apiome-cli |

*(Adapter template. Key: treat emitted OpenAPI as the integration surface — reuse the existing OpenAPI normalizer/diff/lint; `@typespec/compiler` is JS-only → runner; for breaking changes compile both versions → OpenAPI and run openapi-diff. Coordinate with the existing OpenAPI pipeline.)*

---

## MFI-EPIC-15 — RAML (legacy) · v2  ·  **#3730**

RAML 1.0 (dormant since 2016; use **AMF** to parse/normalize). Static files; resolve `!include`/
`uses`. No official breaking framework → build a ruleset. Offer migrate-to-OpenAPI.
Sources: https://github.com/aml-org/amf · https://github.com/raml-org/raml-spec

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 15.1 | RAML parse/resolve via AMF | AMF (JS/JVM) via runner; resolve includes/uses | multi-protocol,import | N | N | M | apiome-rest |
| 15.2 | RAML → canonical model | resources/methods/types/traits (resolved model) | multi-protocol,import | N | N | M | apiome-rest |
| 15.3 | RAML lint pack | AMF SHACL validation + hygiene | multi-protocol,linting,validation | Y | N | S | apiome-rest |
| 15.4 | RAML breaking ruleset | custom (no official); resource/method/type changes | multi-protocol,version-control | Y | N | M | apiome-rest |
| 15.5 | RAML source card + CLI + migrate | UI/CLI + AMF-based RAML→OpenAPI export | multi-protocol,ui,devex,export | Y | N | M | apiome-ui,apiome-cli |

*(Adapter template. Standardize on **AMF** for parse/normalize/validate — avoid unmaintained `ramlfications`/`webapi-parser`. Hash the AMF-resolved model, not raw bytes. Coordinate with #237 (closed). **Migrate-to-OpenAPI is now provided by the shared MFI-EPIC-22 engine** (canonical→OpenAPI emitter + fidelity preview) — 15.5's RAML→OpenAPI export becomes a thin call into 22.x rather than a standalone migrator.)*

---

## MFI-EPIC-16 — API Blueprint (legacy) · v2  ·  **#3731**

Format 1A (archived Nov 2024). Markdown + MSON. Static single-file. Parse via **drafter** →
refract/API-Elements AST; offer **apib2swagger** migration.
Sources: https://github.com/apiaryio/api-blueprint

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 16.1 | API Blueprint parse via drafter | `drafter` → API Elements / Refract JSON | multi-protocol,import | N | N | M | apiome-rest |
| 16.2 | API Blueprint → canonical model | resource groups/resources/actions/transactions/MSON | multi-protocol,import | N | N | M | apiome-rest |
| 16.3 | API Blueprint lint pack | drafter warnings (zero = good) | multi-protocol,linting | Y | N | S | apiome-rest |
| 16.4 | API Blueprint source card + CLI + migrate | UI/CLI + apib2swagger → OpenAPI | multi-protocol,ui,devex,export | Y | N | M | apiome-ui,apiome-cli |

*(Adapter template, abbreviated — legacy/archived. Pin drafter version; hash the refract element tree excluding prose/examples; primary value is **import + migrate to OpenAPI** — the migrate path is the shared **MFI-EPIC-22** engine (16.4's `apib2swagger` becomes one per-format pack under 22.8, fronted by the same fidelity preview). Diff via canonical model (3.2); no native breaking framework.)*

---

## MFI-EPIC-17 — Smithy · v2  ·  **#3732**

Smithy 2.0; IDL `.smithy` ↔ JSON AST (isomorphic; **JSON AST is the canonical diff artifact**).
Built-in `smithy diff` (severities + ~30 evaluators) and `smithy-linters`. Build-time only.
Sources: https://smithy.io/2.0/spec/ · https://smithy.io/2.0/guides/evolving-models.html

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 17.1 | Smithy build → JSON AST | `smithy ast`/`build` via runner; assemble model | multi-protocol,import | N | N | M | apiome-rest |
| 17.2 | Smithy → canonical model | services/operations/resources/shapes/traits | multi-protocol,import | N | N | M | apiome-rest |
| 17.3 | Smithy lint pack | `smithy-linters` (CamelCase, MissingPaginatedTrait, …) | multi-protocol,linting | Y | N | S | apiome-rest |
| 17.4 | Smithy breaking | wrap `smithy diff` evaluators (NOTE/WARNING/DANGER/ERROR) | multi-protocol,version-control | Y | N | M | apiome-rest |
| 17.5 | Smithy source card + CLI + fixtures | UI/CLI (.smithy/JSON AST) + fixtures | multi-protocol,ui,devex | Y | N | S | apiome-ui,apiome-cli |

### MFI-17.1 — Smithy build → JSON AST  ·  **#3808**
- **Solution / Scope.** Use the **Smithy CLI** (`smithy ast`/`build`) via the runner to assemble multi-file models into the **JSON AST** (absolute shape IDs, no ref resolution needed) — read directly with Python `json`.
- **Acceptance Criteria.** Multi-file model assembles to JSON AST; identity (`$version`, namespaces) captured.
- **Dependencies / Parallelism.** After 5.1/5.2, 2.3. Blocks 17.2.
- **Technical Stack.** Python + Smithy CLI (JVM).

*(17.2–17.5 follow the adapter template: hash per-shape AST; lint via `smithy-linters`; breaking via the built-in `smithy diff` evaluators mapped to severities (3.3).)*

---

## MFI-EPIC-22 — Catalog → OpenAPI Conversion & Fidelity Preview · conv-MVP  ·  **#4000**

Turn **any cataloged artifact that is not already OpenAPI** into a first-class **OpenAPI 3.1
project/version** inside apiome. The conversion is driven off the **canonical model**
(MFI-EPIC-2): a format is parsed → normalized once, then *projected* onto OpenAPI. Because formats
span paradigms (RPC/event/graph/data-schema), **conversion is inherently lossy for most of them** —
so the headline feature is not the emitter but the **fidelity preview**: a confirm screen that
shows, side by side, *what the source actually provides* and *what an OpenAPI document favors for
completeness but the source cannot supply*, behind an explicit **"fidelity may be incomplete"**
warning. This epic also unifies the previously scattered migrate-to-OpenAPI off-ramps (RAML
**15.5**, API Blueprint **16.4**, WADL §9.3) into one engine + one UX.

> **Core principle (from research): convert *from the canonical model*, wrap the authoritative
> converter where one exists, and never hide the loss.** OData→OpenAPI is a near-lossless OASIS
> standard; Smithy and gRPC ship official (but explicitly *lossy*) converters; GraphQL and
> AsyncAPI have no clean request/response mapping at all. The gap analyzer encodes exactly this
> spectrum so the preview tells the truth per source.

```mermaid
flowchart LR
  SRC[(cataloged artifact\nnon-OpenAPI version)] --> DET{already OpenAPI?\nor TypeSpec→OAS?}
  DET -- yes --> PASS[passthrough:\noffer direct project/version]
  DET -- no --> CANON[canonical model\nMFI-EPIC-2]
  CANON --> PROJ[paradigm projection\n+ per-format pack]
  PROJ --> EMIT[OpenAPI 3.1 emitter]
  CANON & EMIT --> GAP[fidelity / completeness\ngap analyzer]
  GAP --> PREVIEW[preview screen\nprovides vs missing + WARNING]
  PREVIEW -- confirm --> JOB[convert job →\nnew project + v1 + provenance]
  JOB --> LINT[OpenAPI lint/score\nMFI-EPIC-4]
```

**Fidelity classification (the model behind the preview).** For every OpenAPI construct the emitter
considers, the analyzer tags coverage so the UI can render two honest columns + a score:

| Tag | Meaning | Example |
|---|---|---|
| `present` | directly derivable from the source | OData entity set → `paths` + CRUD ops; WSDL operation → path |
| `inferred` | synthesized via a documented heuristic/default | gRPC method w/o `google.api.http` → `POST /pkg.Svc/Method`; default `200` response |
| `partial` | some instances covered, others not | only some ops have response schemas |
| `missing` | OpenAPI favors it, source has **no** data | HTTP status codes, response media types, `servers`, `securitySchemes`, examples, error responses |
| `n/a` | the paradigm has no equivalent | AsyncAPI pub/sub `action`, GraphQL subscriptions, event channel bindings |

The **OpenAPI completeness checklist** the analyzer scores against: `info` (title/version/
description/contact/license) · `servers` · `paths`+methods · `operationId`/`summary`/`description` ·
parameters (`in`/`required`/`schema`) · `requestBody` media types+schema · `responses` per status
code + media types + schema · `components.schemas` · `securitySchemes`+`security` · `tags` ·
`examples` · `externalDocs` · `deprecated`.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 22.1 ✅ | Canonical → OpenAPI 3.1 emitter SPI | inverse-of-normalizer: project canonical model → valid OAS 3.1 doc | multi-protocol,export,rest,python | N | Y | L | apiome-rest |
| 22.2 ✅ | Paradigm projection strategies | per-paradigm mapping rules (RPC/event/graph/data-schema → REST) | multi-protocol,export,rest,python | N | Y | L | apiome-rest |
| 22.3 ✅ | Fidelity / completeness gap analyzer | classify each OAS construct present/inferred/partial/missing/n-a + score | multi-protocol,export,validation | N | Y | L | apiome-rest |
| 22.4 | Conversion preview screen + warning | side-by-side provides-vs-missing, fidelity grade, mandatory warning | multi-protocol,ui,typescript | Y | Y | L | apiome-ui |
| 22.5 ✅ | Convert-to-project/version job + provenance | emit doc, create project + v1, link source, lint/score, store report | multi-protocol,export,rest,versions | N | Y | M | apiome-rest,apiome-db |
| 22.6 ✅ | Conversion REST API + CLI | `POST …/convert` (dry-run=preview, commit=create) + `apiome convert` | multi-protocol,rest,devex | Y | Y | M | apiome-rest,apiome-cli |
| 22.7 | OpenAPI-native passthrough detection | skip conversion when source is OpenAPI/Swagger/TypeSpec-emitted | multi-protocol,rest,validation,mvp | Y | Y | S | apiome-rest |
| 22.8 | Per-format conversion packs + fixtures | wrap authoritative converters; consolidate RAML/APIB/WADL off-ramps | multi-protocol,export,integrations | Y | N | XL | apiome-rest |

### MFI-22.1 — Canonical → OpenAPI 3.1 emitter SPI  ·  **#4002**  ·  ✅ **Done**
- **Status.** Implemented as three pure, I/O-free modules in `apiome-rest`. `src/app/emitter.py` is the **Emitter SPI** — an `Emitter` ABC + format registry (`register_emitter`/`get_emitter`/`available_emit_formats`) mirroring the Normalizer SPI; the **provenance** primitives (`Provenance` = `source`/`inferred`/`default`, `ProvenanceRecord`, `ProvenanceTracker` keyed by RFC-6901 JSON Pointer) that feed the 22.3 analyzer; the `EmitResult` envelope; and `SchemaEmitter`, the exact inverse of the normalizer's `SchemaCoercer` (canonical `TypeRef`/`Constraints`/`Type` → JSON-Schema fragments). `src/app/openapi_emitter.py` is `OpenApiEmitter` (registered `openapi-3.1`): it walks a `CanonicalApi` → `info`/`servers`/`paths`+methods/`requestBody`/`responses`/`components.schemas`, deterministically (all collections ordered by key/name) and with every value provenance-tagged. Non-REST models are best-effort — an operation with no HTTP verb/route gets a synthesized `POST` binding (flagged `inferred`), a types-only model emits a components-only doc — covering REST + RPC + data-schema sources. On REST input the emitter is a **fixed point** of the reference normalizer (`normalize(emit(normalize(doc))) == normalize(doc)`). `src/app/openapi_validator.py` validates a whole document against the bundled official **OpenAPI 3.1 meta-schema** (`data/openapi_3_1_meta_schema.json`, vendored for fully-offline validation via the draft 2020-12 `jsonschema` engine). Tests in `tests/test_emitter.py`, `tests/test_openapi_emitter.py`, `tests/test_openapi_validator.py` (44 new); full rest `tests/` suite green (2715 passed, 31 skipped). apiome-rest 1.63.0 → 1.64.0.
- **Problem.** The pipeline normalizes *into* the canonical model but cannot emit *out* to OpenAPI. Conversion needs the inverse of the Normalizer SPI (2.3).
- **Solution / Scope.** An `OpenApiEmitter` that walks a `CanonicalApi` and produces a valid **OpenAPI 3.1** document: artifact→`info`/`servers`, services/operations→`paths`+methods+`operationId`, messages→`requestBody`/`responses` with media types, types/fields→`components.schemas` (reuse the existing JSON-Schema/primitives machinery — OAS 3.1 schemas *are* JSON Schema), channels/agent-skills→best-effort operations (delegated to 22.2). Output validates against the OpenAPI 3.1 meta-schema; deterministic ordering so re-conversion is stable. The emitter records, per construct, *where each value came from* (source / inferred / default) to feed the analyzer (22.3).
- **Acceptance Criteria.** Emits a schema-valid OAS 3.1 doc from a canonical model covering ≥1 REST, ≥1 RPC, ≥1 data-schema source; output passes the existing OpenAPI validator; emission is deterministic.
- **Dependencies / Parallelism.** After 2.1/2.3. Blocks 22.2/22.3/22.5.
- **Technical Stack.** Python, Pydantic, OpenAPI 3.1.

### MFI-22.2 — Paradigm projection strategies  ·  **#4003**  ·  ✅ **Done**
- **Status.** Implemented as a pluggable projection layer in `apiome-rest`. `src/app/projection.py` adds a `ProjectionStrategy` SPI (base class + paradigm registry `register_projection`/`get_projection`, mirroring the emitter/normalizer registries) with one strategy per `ApiParadigm`: `RpcProjection` (honors a `google.api.http`/Smithy `http` annotation from `extras`, else synthesizes `POST /{Service}/{Method}` per the gRPC-transcoding convention; flags streaming as an `x-apiome-streaming` extension + `n/a` loss), `GraphProjection` (SOFA-style query→`GET`/mutation→`POST` under `/graphql`, arguments→parameters; **subscriptions `n/a`** — not emitted, reported as a loss), `EventProjection` (explicitly low-fidelity — each pub/sub op → a non-normative path with `x-apiome-event-action` + a document-level `x-apiome-fidelity` caveat recommending schemas-only; pub/sub action, channel bindings, correlation ids `n/a`; payloads stay in `components.schemas`), and `RestProjection`/`DataSchemaProjection` (identity/components-only). Each strategy resolves an operation's `(method, path)` binding (or declares it un-representable) and records its losses on a `LossTracker`. New fidelity primitives on the Emitter SPI (`src/app/emitter.py`): `LossKind` (`inferred`/`n/a`), `Loss`, `LossTracker`, plus a `losses` field on `EmitResult` — the `n/a` channel captures constructs that produce no emitted value (so provenance can't describe them). `OpenApiEmitter` now delegates route/loss decisions to the paradigm's projection. Agent descriptors (A2A/MCP) normalize into the RPC paradigm and project via `RpcProjection`, so no separate strategy is needed. Tests: `tests/test_projection.py` (20 new) — each paradigm emits a schema-valid OAS 3.1 doc and reports its `inferred`/`n/a` set, subscriptions/streaming/pub-sub surfaced as losses not silent drops; `tests/test_openapi_emitter.py` updated for the spec-compliant RPC path. Full `apiome-rest` suite green (2735 passed, 31 skipped). Docs: `docs/projection_strategies.md`. apiome-rest 1.64.0 → 1.65.0.
- **Problem.** REST maps cleanly, but RPC/event/graph/data-schema do not have native paths/verbs/responses — each needs an explicit, documented projection (and each loses something).
- **Solution / Scope.** A pluggable projection per paradigm, each emitting where it can and **declaring its losses** to 22.3:
  - **RPC (gRPC/Smithy/Thrift/OpenRPC):** method→operation. Use `google.api.http`/Smithy `http` traits when present; else synthesize `POST /{Service}/{Method}` with the input message as `requestBody` and output as the `200` body (the gRPC-transcoding/JSON convention). Streaming flagged as `x-` extensions + a loss note.
  - **Graph (GraphQL):** SOFA-style projection — queries→`GET`, mutations→`POST` under a root path; **subscriptions are `n/a`**; arguments→parameters/body.
  - **Event (AsyncAPI/CloudEvents):** **explicitly low-fidelity** — emit message payloads as `components.schemas` and document each channel/operation as a non-normative path with a prominent caveat; pub/sub `action`, bindings, correlationId are `n/a`. Recommend "schemas-only" mode.
  - **Data-schema (Avro/Protobuf-schema/JSON-Schema/XSD):** **components-only** OpenAPI (types, no `paths`) unless a service definition is also present.
  - **Agent descriptors (A2A/MCP):** skills/tools→operations with input/output schemas (reuse MCP catalog mapping).
- **Acceptance Criteria.** Each projection produces a valid doc on a fixture and reports its `inferred`/`n/a` set; subscriptions/streaming/pubsub are surfaced as losses, not silently dropped.
- **Dependencies / Parallelism.** After 22.1. Parallel with 22.3. Feeds 22.8.
- **Technical Stack.** Python.

### MFI-22.3 — Fidelity / completeness gap analyzer  ·  **#4004**  ·  ✅ **Done**
- **Status.** Implemented as a pure, I/O-free module `apiome-rest/src/app/fidelity.py`. `analyze_fidelity(api, EmitResult) -> FidelityReport` reads the emitter's per-value **provenance** (`source`/`inferred`/`default`, MFI-22.1) and the paradigm projection's **losses** (`inferred`/`n/a`, MFI-22.2) — no re-derivation of the conversion. The `FidelityReport` carries: a **completeness checklist** (`ChecklistItem` per load-bearing OpenAPI construct — `info` title/version/description/contact/license, `servers`, `paths`+methods, operation id/summary, parameters, `requestBody`, `responses`, `components.schemas`, security, `tags`, `examples`, `externalDocs`, `deprecated`), each with a `Coverage` tag (`present`/`inferred`/`partial`/`missing`/`n/a`), a count, up to three example coordinates, a load-bearing `weight`, and a human-readable reason; the enumerated projection `losses`; a rolled-up **score** (0-100) + **A-F grade** (reusing `schema_lint.GRADE_THRESHOLDS`, the MFI-4.2 banding) weighted by how load-bearing each inferred/partial/missing construct is plus a per-`n/a`-loss penalty; and a coarse **fidelity tier** (`high` ≥ 85 / `medium` ≥ 60 / `low`) that drives the MFI-22.4 warning strength. Pure & deterministic (fixed checklist order, sorted+capped examples). Acceptance met: an OData-style REST model scores **high** (near-lossless, 100/A); an AsyncAPI event model scores **low** (F) with pub/sub + channel-binding `n/a` losses enumerated; a gRPC model without HTTP annotations flags **inferred paths** + inferred (defaulted) media types and status codes. Tests in `tests/test_fidelity.py` (21 new); full rest suite green (2757 passed, 31 skipped). Docs: `docs/fidelity_analyzer.md`. apiome-rest 1.65.0 → 1.66.0.
- **Solution / Scope.** Given the source canonical model + the emitter's provenance map, produce a structured **fidelity report**: for each completeness-checklist item, a coverage tag (`present`/`inferred`/`partial`/`missing`/`n/a`), the count + examples, and a human-readable reason ("source has no response status codes", "gRPC has no media types"). Roll up to a **fidelity score 0–100 + A–F grade** (reuse the 4.2 banding) weighted by how load-bearing each missing item is, and a top-line **fidelity tier** (`high`/`medium`/`low`) that drives how strong the UI warning is. Pure/deterministic (no DB/network).
- **Acceptance Criteria.** OData fixture scores high (near-lossless); AsyncAPI fixture scores low with pubsub/binding losses enumerated; gRPC-without-http-annotations flags inferred paths + missing media types/status codes; report is deterministic for a fixed model.
- **Dependencies / Parallelism.** After 22.1/22.2. Blocks 22.4/22.5.
- **Technical Stack.** Python.

### MFI-22.4 — Conversion preview screen + fidelity warning  ·  **#4005**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-ui`. A new `ConversionPreviewDialog` (`src/app/components/ade/dashboard/catalog/ConversionPreviewDialog.tsx`) is launched from the Catalog screen's "Convert to OpenAPI" action (replacing the placeholder alert in `catalog/page.tsx`). It lazy-fetches a **live dry-run** (only when opened, abortable, with a retry affordance — mirroring `CatalogLintReportDialog`) and renders the MFI-22.3 `FidelityReport` as **two columns**: *"What the source provides"* (the `present`/`inferred` checklist rows, with how each was derived) and *"What OpenAPI favors but is missing"* (the `missing`/`partial`/`n/a` rows plus the enumerated projection `losses`, grouped, with reasons). The header shows the fidelity **grade + score + tier**, and a **mandatory warning banner** carries the required sentence; its strength scales with tier (`tierWarning`) — a **low** tier warns critically and is **acknowledgement-gated** (Convert stays disabled until the user ticks the acknowledgement), while `medium`/`high` warn/reassure without gating. Inline **defaults** (title/version/servers) flow into the commit (`cleanDefaults`), and a collapsible **raw-OpenAPI preview** shows the would-be document. The report shape, presentation helpers, and the `fetchConversionDryRun`/`commitConversion` fetch wrappers live in a pure `src/app/utils/conversion-fidelity.ts` (types mirror the Python `FidelityReport` field-for-field). A Next.js proxy route `POST /api/catalog/{itemId}/convert` (`?dryRun=true` = report only, no side effects; else commit) forwards to the MFI-22.6 REST endpoint, mirroring the lint proxy. The dry-run has no side effects and nothing is created until confirmed, so **cancel makes no changes**. Uses native `fetch` + `AbortController` (the catalog screens' convention) rather than TanStack Query. Tests: `tests/conversion-fidelity.test.ts` (13 — partition/tier/coverage/defaults/fetch) and `tests/conversion-preview-dialog.test.tsx` (8 — lazy fetch, both columns, banner, low-tier ack gating, defaults→commit, cancel, error+retry, raw preview); full catalog suite green (177 passed). apiome-ui 0.36.0 → 0.37.0.
- **Problem.** Conversion must be a *reviewed* action, not a silent transform — the user has to understand the trade-off first.
- **Solution / Scope.** A preview/confirm UI (reuse the `ImportDialog`/dry-run pattern) rendering the 22.3 report as **two columns**: **"What the source provides"** (the `present`/`inferred` constructs that will be in the spec, with how each was derived) and **"What OpenAPI favors but is missing"** (the `missing`/`partial`/`n/a` items, grouped, with reasons). Header shows the **fidelity grade + tier** and a **mandatory, dismiss-to-proceed warning banner**: *"The fidelity of the original API may not be complete enough to create a fully defined OpenAPI Specification — review the gaps below before converting."* Strength/wording scales with tier (low-tier = stronger, requires explicit acknowledgement). Optional: let the user supply defaults inline (title/version/servers) to close cheap gaps before committing; a collapsible raw-OpenAPI preview. "Convert" stays disabled until the warning is acknowledged.
- **Acceptance Criteria.** Both columns render from a live dry-run; warning shown for every non-OpenAPI source and is acknowledgement-gated on low-tier; user-entered defaults flow into the commit; cancel makes no changes.
- **Entry point.** Launched from the **Catalog screen** (MFI-23.11) "Convert to OpenAPI" action on a cataloged item.
- **Dependencies / Parallelism.** After 22.3, 22.6 (dry-run API). Parallel with 22.5.
- **Technical Stack.** Next.js, TanStack Query.

### MFI-22.5 — Convert-to-project/version job + provenance  ·  **#4006**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest` + `apiome-db`. New module `src/app/conversion_job.py` orchestrates one conversion job against small **ports** so its decision logic is pure and DB-free-testable: it **emits** the OpenAPI 3.1 document from the source `CanonicalApi` (MFI-22.1/22.2 — optionally filling a missing info title/version/servers from user-supplied `defaults`, never overwriting a value the source declared), **analyzes** its fidelity (MFI-22.3), decides **first-convert vs re-convert** from the provenance ledger (a prior conversion of the source names the Project a re-convert appends a *new version* to, so a changed source never duplicates the Project — the version label is bumped `1.0.0` → `1.0.1`), **commits** by *reusing the spec-import submit→commit engine* (the emitted doc is base64'd and submitted as an `openapi` import, which decomposes it into a full publishable Project + version; on re-convert the prior Project is passed as `existing_project_id`), captures the **OpenAPI lint/score** (MFI-EPIC-4) on the converted revision, and **persists provenance** into the new **`apiome.conversion_provenance`** append-only ledger — source artifact id + source revision + source format/protocol + the fidelity report + the converter tool versions — so the converted spec links back to its origin and a later re-import diffs cleanly. Production wiring lives in swappable adapters (`SpecImportCommitter`, `DbLintScorer`, `DbConversionProvenanceStore`); new DAO methods `create_conversion_provenance` / `get_latest_conversion_for_source` / `get_conversions_for_project`. **`apiome-db` V139** adds the ledger table (two facet indexes for the re-convert and reverse lookups, a write-once BEFORE UPDATE OR DELETE trigger). Acceptance met: a first confirm creates a Project + `v1` with valid OAS, an attached fidelity report, and a back-link to the source version; a re-convert of a changed source produces a new version, not a duplicate Project; the lint/score is captured. The REST endpoint + CLI that drive this job are **MFI-22.6**. Tests: `apiome-rest/tests/test_conversion_job.py` (24 new; full rest suite green — 2781 passed, 31 skipped) and `apiome-db/test/conversion-provenance.test.ts` (16 structural; full db suite green — 290 passed). apiome-rest 1.66.0 → 1.67.0; apiome-db 0.20.0 → 0.21.0.
- **Problem.** A confirmed conversion must create a real, editable OpenAPI **project/version**, traceable back to its source.
- **Solution / Scope.** A job (reuse the spec-import submit→commit engine) that: emits the OAS doc (22.1/22.2), creates a **new project** (or new version of an existing converted project on re-convert) with the emitted spec as **v1**, runs the existing **OpenAPI lint/score** (MFI-EPIC-4) on the result, and persists **provenance** — source artifact id + source version + source format/protocol + the fidelity report + tool versions — so the converted spec links back to its origin and a later re-import diffs cleanly. The converted project is then a normal OpenAPI project: editable in the ADE to fill the gaps the preview flagged.
- **Acceptance Criteria.** Confirm creates a project + v1 with valid OAS, an attached fidelity report, and a back-link to the source version; re-convert of a changed source produces a new version, not a duplicate project; OpenAPI lint/score captured.
- **Dependencies / Parallelism.** After 22.1/22.2/22.3, 7.x. Parallel with 22.4.
- **Technical Stack.** Python async, PostgreSQL, FastAPI.

### MFI-22.6 — Conversion REST API + CLI  ·  **#4007**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest` + `apiome-cli`. **REST:** `POST /v1/catalog/{tenant_slug}/{item_id}/convert` (`catalog_routes.py`) is the single convert verb behind the UI preview (MFI-22.4), CLI, and API. The `dryRun` **query param is authoritative** (falling back to the body's `dryRun`, defaulting to a safe dry-run so a malformed body never silently commits): `dryRun=true` reconstructs the item's canonical model from its captured source, emits the OpenAPI 3.1 doc (MFI-22.1) and analyzes fidelity (MFI-22.3), returning `{report, openapi, sourceFormat, target}` with **no side effects**; `dryRun=false` runs the MFI-22.5 commit job (`run_conversion`), returning `{projectId, versionId, versionRecordId, createdProject, reconverted, provenanceId, report}`. A new caller-side loader `catalog_conversion.py` rebuilds the `ConversionSource` — it pulls the item's captured source (`resolve_source_payload`), resolves the source's `ImportSource` adapter robustly (canonical format → registry key → advertised `formats` → content sniff, so `protobuf`→`grpc`/`asyncapi-3`→`asyncapi` resolve), and `parse`→`normalize`s it back into a `CanonicalApi`; every failure (no captured source → 422, unknown format → 400, unparseable → 422) is a mapped `ConversionError`. The pure emit+analyze step was extracted into `conversion_job.preview_conversion` so the dry-run and commit paths share one code path (the dry-run doc equals the committed doc). `target` is `openapi` only (400 otherwise; the verb is target-generic). A Project's id / unknown id → 404. **CLI:** `apiome convert <artifact> --to openapi [--dry-run] [--out FILE] [--force] [--title] [--api-version] [--server …]` (`commands/convert.py`, a root command) posts to the endpoint, prints the server-computed fidelity summary + the mandatory warning (`client/conversion_output.py`), writes the would-be document with `--out` on a dry-run, and **exits non-zero on a low-fidelity tier unless `--force`** (mirroring `lint --min-grade`'s CI gate). `--title`/`--api-version`/`--server` become the request `defaults` applied only where the source left a gap. Acceptance met: dry-run returns the report with no side effects; commit creates the project/version; the CLI prints summary + warning and gates the exit code on low tier. Tests: `apiome-rest` `tests/test_catalog_conversion.py` (10) + `tests/test_catalog_convert_route.py` (8) + `preview_conversion` cases in `tests/test_conversion_job.py` (full rest suite green — 2803 passed, 31 skipped); `apiome-cli` `tests/test_conversion_output.py` (8) + `tests/test_convert_command.py` (9) (full cli suite green — 1135 passed). apiome-rest 1.67.0 → 1.68.0; apiome-cli 0.15.0 → 0.16.0.
- **Problem.** Convert + preview must be invokable from UI, CLI, and API uniformly.
- **Solution / Scope.** `POST /catalog/{artifactVersionId}/convert` with `dryRun=true` returning the **fidelity report only** (powers 22.4's preview) and `dryRun=false` running the commit job (22.5); plus `apiome convert <artifact> --to openapi [--dry-run] [--out file]`. Consistent job-polling/output with existing import. `--to openapi` is the only target now but the verb is target-generic for future emitters.
- **Acceptance Criteria.** Dry-run returns the report without side effects; commit creates the project/version; CLI prints the fidelity summary + warning and exits non-zero hint on low-tier unless `--force`.
- **Dependencies / Parallelism.** After 22.3/22.5. Parallel with 22.4.
- **Technical Stack.** FastAPI, Typer.

### MFI-22.7 — OpenAPI-native passthrough detection  ·  **#4008**  ·  **Promoted to MVP (2026-07)**
- **MVP note.** The §5 work order has always said "ship 22.7 passthrough first so OpenAPI/Swagger/
  TypeSpec sources are handled losslessly from day one" — the MVP flag now matches that sequencing
  (2026-07 gap analysis).
- **Problem.** The request is explicit: convert *only if the imported object isn't already OpenAPI*. Converting an OpenAPI source through the canonical model would needlessly lose fidelity.
- **Solution / Scope.** Detect when the source format is **OpenAPI/Swagger** (already first-class — offer direct project/version creation, no conversion) or **TypeSpec** (which *natively emits* OpenAPI via MFI-EPIC-14 — route to that emit, not the lossy projection). For these, the "convert" action becomes a near-lossless passthrough/adopt and the preview shows a `high`-fidelity report with no warning (or an informational note for Swagger 2.0→3.1 upgrade specifics).
- **Acceptance Criteria.** OpenAPI/Swagger sources skip lossy conversion and create a project directly; TypeSpec routes through its native OpenAPI emit; non-OpenAPI sources always go through 22.1–22.5.
- **Dependencies / Parallelism.** After 1.5 (detection), 22.5. Parallel with 22.8.
- **Technical Stack.** Python.

### MFI-22.8 — Per-format conversion packs + fixtures (consolidates migrate-to-OpenAPI)  ·  **#4009**
- **Problem.** Each source format needs a concrete mapping pack, and the existing one-off "migrate-to-OpenAPI" notes (RAML 15.5, API Blueprint 16.4, WADL §9.3) should not be re-implemented per epic.
- **Solution / Scope.** Per-format packs that refine the generic projection (22.2), **wrapping the authoritative converter via the toolchain runner (MFI-EPIC-5) where one exists**, with native fallback otherwise, each with a golden-fixture + expected-fidelity-tier assertion:
  - **OData** — wrap the OASIS **OData→OpenAPI v1.0** mapping (Microsoft `Microsoft.OpenApi.OData` / the OASIS JS lib). *Expected tier: high.*
  - **Smithy** — wrap the built-in **`smithy-openapi`** plugin (OAS 3.0.2/3.1.0). *Tier: medium-high; record documented losses (endpoint/hostLabel traits).*
  - **gRPC/Protobuf** — **gnostic** / **protoc-gen-openapiv2** / **protoc-gen-connect-openapi** via buf; honor `google.api.http`. *Tier: medium (low without http annotations).*
  - **GraphQL** — **SOFA**-style projection (or `graphql-to-openapi`). *Tier: medium; subscriptions n/a.*
  - **AsyncAPI / CloudEvents** — native schemas-only projection. *Tier: low — strong warning.*
  - **WSDL/SOAP, Avro/Protobuf-schema, RAML, API Blueprint, WADL** — native projection off the canonical model; RAML/APIB/WADL replace their per-epic migrate notes by pointing here.
  - Sources: OASIS OData→OpenAPI mapping & Microsoft.OpenApi.OData; Smithy `converting-to-openapi`; google/gnostic + grpc-gateway `protoc-gen-openapiv2` + protoc-gen-connect-openapi; SOFA (sofa-api).
- **Acceptance Criteria.** Each pack converts its golden fixture to a valid OAS doc and asserts its expected fidelity tier; RAML/APIB/WADL epics reference 22.x rather than defining separate migrators.
- **Dependencies / Parallelism.** After 22.2/22.3, 5.1/5.2. Parallel across formats; parallel with 22.7.
- **Technical Stack.** Python + external CLIs (.NET/JS/JVM via runner).

---

## MFI-EPIC-23 — Catalog Screen & Non-Publishable Cataloged Items · catalog-MVP  ·  **#4001**

When an import is **not OpenAPI but is OpenAPI-worthy** (it has operations/types that *could*
project to OpenAPI — gRPC, GraphQL, AsyncAPI, OData, WSDL, Smithy, RAML, API Blueprint, …), the
result should not silently become a publishable Project, because it may be incomplete. Instead it
lands in a dedicated **Catalog** screen — a near-clone of the existing **Projects dashboard**
(`apiome-ui/src/app/ade/dashboard/projects/page.tsx`) — where it can be **viewed, linted, and
inspected** exactly like a project, but is **never a publish candidate**. Each catalog item shows a
**format pill** (the imported file's format), a **paradigm/protocol** pill, **source-material**
provenance (original file/URL/discovery + tool versions), and the lint-grade/quality orbs the
project card already renders. The only way out of the catalog to a *publishable* artifact is the
**MFI-EPIC-22** convert-to-OpenAPI flow (with its fidelity preview).

> **Reuse, don't rebuild.** Mirror the Projects dashboard wholesale —
> `ProjectsDashboardProjectCard.tsx`, the card/table view toggle, filter/sort/search, the
> lint-report and `ProjectQualityHistoryDialog` dialogs, `DashboardSideNav.tsx`, and the
> `/projects/{tenantSlug}` REST shape. The catalog is a *parallel list surface*, not a new UI
> language. The one hard rule: **no publish path** for catalog items, anywhere.

```mermaid
flowchart TB
  IMP[Import non-OpenAPI source\nMFI-EPIC-1] --> WORTHY{OpenAPI-worthy?\nhas operations/types}
  WORTHY -- no\ndata-schema only --> CATdata[Catalog item\nschemas-only]
  WORTHY -- yes --> CAT[Catalog item\nnon-publishable]
  OAS[Import OpenAPI/Swagger] --> PRJ[(Projects\npublishable)]
  CAT --> SCREEN[Catalog screen\nview · lint · format pill · source]
  CATdata --> SCREEN
  SCREEN -- view read-only --> DES[Designer/Studio\n(later)]
  SCREEN -- Convert to OpenAPI\nMFI-EPIC-22 preview --> PRJ
  PRJ --> PUB[Publish ✔]
  CAT -. publish blocked .-x PUB
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 23.1 | Catalog item entity & non-publishable guarantee | listable catalog artifact distinct from publishable Project; `publishable=false` | multi-protocol,rest,database | N | Y | M | apiome-rest,apiome-db |
| 23.2 | Catalog list + detail REST API | `GET /catalog/{tenantSlug}` mirroring `/projects` shape (+ item detail) | multi-protocol,rest | N | Y | M | apiome-rest |
| 23.7 | Route OpenAPI-worthy non-OpenAPI imports → catalog | ingestion decides Project vs Catalog by format/paradigm | multi-protocol,import,rest | N | Y | M | apiome-rest |
| 23.8 ✅ | Non-publishable enforcement (UI + REST) | hide/disable publish on catalog items; reject publish server-side | multi-protocol,rest,ui,validation | Y | Y | M | apiome-rest,apiome-ui |
| 23.9 ✅ | Catalog item detail + source-material panel | provenance: original file/URL/discovery, tool versions, import job | multi-protocol,ui,rest | Y | Y | M | apiome-ui,apiome-rest |
| 23.10 ✅ | Lint/score + quality-history parity | reuse lint-report + quality dialogs for catalog items | multi-protocol,linting,ui | Y | Y | S | apiome-ui,apiome-rest |
| 23.11 ✅ | Convert-to-Project promotion (EPIC-22 entry) | "Convert to OpenAPI" action → fidelity preview → publishable Project | multi-protocol,export,ui | N | Y | M | apiome-ui,apiome-rest |
| 23.12 | Read-only Designer/Studio view | open a catalog item in the editor in view-only mode | multi-protocol,ui | Y | N | M | apiome-ui |

### MFI-23.1 — Catalog item entity & non-publishable guarantee  ·  **#4010**  ·  ✅ **Done**
- **Status.** Implemented across `apiome-db` and `apiome-rest` as a **projection over the existing `projects` + `versions` tables** — no new versioning mechanism. The Project-vs-Catalog boundary is a single `publishable BOOLEAN NOT NULL DEFAULT true` on `apiome.projects` (`apiome-db/scripts/V138__catalog_item_publishable_guarantee_4010.sql`): `true` for publishable OpenAPI/Swagger Projects (the `DEFAULT true` leaves every pre-existing project unaffected), `false` for catalog items. The "no publish" rule is enforced **in the database, not the UI**: a `BEFORE UPDATE` trigger (`projects_forbid_publishable_change`, mirroring V128's `mcp_forbid_row_mutation`) makes the flag write-once with NULL-safe `IS DISTINCT FROM`, so a catalog item (`publishable=false`) can never be promoted to a publishable Project by a stray UPDATE — the only path out is the MFI-EPIC-22 convert flow, which mints a *new* Project. A partial composite `idx_projects_tenant_publishable` (live rows) backs both list surfaces. On the REST side: `create_project(..., publishable=True)` round-trips the flag (catalog items pass `False`, used by MFI-23.7); `get_catalog_items_for_tenant` / `get_catalog_item_by_id` return only the `publishable=false` slice, projecting the latest revision's `source_format`/`protocol`/`format_metadata`/`tool_versions` (MFI-7.1/7.2) plus the captured lint `quality_score`/`quality_grade` (V124); `set_version_source_format` persists a revision's format/protocol/provenance at import; and `CatalogItemSchema` (always `publishable=false`) carries the project-compatible fields + format/source projection. `publishable` is surfaced on `ProjectSchema` and every project SELECT/RETURNING but is intentionally **not** in the `update_project` whitelist, so the flag is immutable through the app too. DB-free structural tests in `apiome-db/test/catalog-item-publishable-guarantee.test.ts` (13 tests); REST tests in `apiome-rest/tests/test_catalog_item.py` (15 tests). Full db suite green (274) + full rest suite green (2164 passed, 2 pre-existing live-DB skips). apiome-db 0.19.0 → 0.20.0; apiome-rest 1.41.0 → 1.42.0.
- **Problem.** The catalog needs a first-class, listable artifact that is explicitly *not* a publishable Project, so the UI and API can treat the two lists differently and the "no publish" rule is enforced at the data layer, not just hidden in the UI.
- **Solution / Scope.** Model a **catalog item** as a projection over the normalized artifact + version tables (MFI-EPIC-2/7) carrying `source_format`/`protocol` (7.1), `format_metadata` (7.2), source provenance, lint score/grade, and a **`publishable=false`** invariant (catalog items are never publishable; OpenAPI/Swagger imports remain Projects with `publishable=true`). Reuse `versions`/`version_tags`/soft-delete; no new versioning mechanism. Tenant-scoped like projects.
- **Acceptance Criteria.** A non-OpenAPI import is persisted + retrievable as a catalog item with format/protocol/source/lint; `publishable` is false and immutable for catalog items; existing OpenAPI projects are unaffected.
- **Dependencies / Parallelism.** After 2.2, 7.1/7.2. Blocks 23.2/23.7/23.8.
- **Technical Stack.** PostgreSQL, FastAPI.

### MFI-23.2 — Catalog list + detail REST API  ·  **#4011**  ·  ✅ **Done**
- **Status.** Implemented across `apiome-rest` and `apiome-ui` as a thin read API over the MFI-23.1 projection. New `apiome-rest/src/app/catalog_routes.py` (registered in `main.py`) exposes `GET /v1/catalog/{tenant_slug}` and `GET /v1/catalog/{tenant_slug}/{item_id}`, both tenant-scoped and authenticating via JWT or API key. The list calls `Database.get_catalog_items_for_tenant` and the detail calls `get_catalog_item_by_id` (MFI-23.1) — i.e. only the `publishable = false` slice — and serializes through `CatalogItemSchema`, so each response mirrors the Projects envelope (id/name/slug/description/timestamps/creator/`qualityScore`/`qualityGrade`) **plus** the latest revision's `sourceFormat`/`protocol`/`formatMetadata`/`toolVersions` and the `publishable = false` invariant. The list supports `include_deleted` for trash/restore parity with `/v1/projects`; the single-item read 404s on any id that is not a catalog item (e.g. a publishable Project), since the projection returns no row. A Next.js proxy mirroring the projects proxy was added: `apiome-ui/src/app/api/catalog/route.ts` (`GET` list, returns `{ success, catalog }`, forwards `include_deleted`) and `…/api/catalog/[itemId]/route.ts` (`GET` detail, returns `{ success, item }`) — read-only, since catalog items are created by the import routing (MFI-23.7), not through this API. Tests: `apiome-rest/tests/test_catalog_routes.py` (12 — auth, registration, JSON, projection/`include_deleted`, detail success + 404) and `apiome-ui/tests/api/catalog-proxy.test.ts` (10 — upstream URL shape, auth/tenant guards, envelope keys, read-only). Full rest suite green (2176 passed, 2 pre-existing live-DB skips); UI `tsc`/eslint/`next build` clean. apiome-rest 1.42.0 → 1.43.0; apiome-ui 0.25.0 → 0.26.0. *(Note: `source_material` from the original sketch is provided as the existing `formatMetadata` provenance bag off MFI-7.2 rather than a separate column; backend "filtering/sorting" stays at projects parity — the dashboard does filter/sort/search client-side, cloned in MFI-23.3.)*
- **Problem.** The Catalog screen needs data in the same shape the Projects screen already consumes, to maximize UI reuse.
- **Solution / Scope.** `GET /catalog/{tenantSlug}` (and item detail) returning the same envelope as `/projects/{tenantSlug}` (id/name/slug/description/timestamps/creator/qualityScore/qualityGrade) **plus** `source_format`, `protocol`, `source_material` (file name / source URL / discovery kind), `tool_versions`, and `publishable:false`. Support `include_deleted`, filtering, sorting parity. Proxied through a Next.js `/api/catalog` route mirroring `src/app/api/projects/route.ts`.
- **Acceptance Criteria.** Endpoint returns catalog items tenant-scoped with the project-compatible fields + the new format/source fields; matches the projects response contract so the UI list can be cloned.
- **Dependencies / Parallelism.** After 23.1. Blocks 23.3.
- **Technical Stack.** FastAPI, Next.js route proxy.

### MFI-23.3 — Catalog screen page (list/card/table)  ·  **#4012**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-ui` as a self-contained clone of the Projects dashboard, restricted to the non-publishable Catalog. New route `src/app/ade/dashboard/catalog/page.tsx` reaches the read-only `/api/catalog` proxy (MFI-23.2) for the list (forwarding `include_deleted`) and renders **both card and table views** with the four filter chips (all/active/attention/deleted), search (name/slug/description/format/protocol), and a six-option sort bar — **name/created/updated/quality/grade/format** — backed by a dedicated `src/app/utils/catalog-dashboard-sort.ts` (mirrors `projects-dashboard-sort.ts`, "unknowns last", plus the catalog-only `grade` and `format` columns reading score/grade/format straight off the row). Soft-delete / undelete / permanent-delete reuse the existing `deleteProject`/`restoreProject`/`permanentDeleteProject` server actions — a catalog item's id *is* a project id (the Catalog is a projection over `apiome.projects`) — so no new write API was needed; there is intentionally **no create/edit/publish** (items are minted by the import routing, MFI-23.7). The empty state explains the catalog holds OpenAPI-worthy non-OpenAPI imports and that items arrive via import, not by hand. The dedicated CatalogItemCard (MFI-23.4), format/protocol pills (MFI-23.5) and side-nav entry (MFI-23.6) remain their own tickets; this screen ships a styled inline card + format/quality badges so both views work today. Tests: `apiome-ui/tests/catalog-dashboard-sort.test.ts` (15 — every column, both directions, unknowns-last, no-mutation) and `apiome-ui/tests/catalog-page.test.ts` (13 — route/data wiring, read-only, reused delete helpers, views/filters/six sorts/search, empty state). Full UI suite green (267 suites, 3887 tests); `tsc`/eslint/`next build` clean. apiome-ui 0.26.0 → 0.27.0.
- **Problem.** Users need a Projects-equivalent screen to browse cataloged items.
- **Solution / Scope.** A new route `/ade/dashboard/catalog` cloned from `src/app/ade/dashboard/projects/page.tsx`: card/table view toggle, filter (all/attention/deleted), sort (name/created/updated/quality/grade/format), search, soft-delete/undelete. Wired to `/api/catalog` (23.2). Empty-state explains what the catalog is and how items get here (non-OpenAPI imports).
- **Acceptance Criteria.** Catalog list renders in both views with filter/sort/search and soft-delete, reaching feature parity with the projects list minus publish.
- **Dependencies / Parallelism.** After 23.2. Parallel with 23.4/23.5.
- **Technical Stack.** Next.js (app router), Tailwind + Radix, TanStack/fetch.

### MFI-23.4 — CatalogItemCard (mirror ProjectCard)  ·  **#4013**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-ui` as a dedicated `src/app/components/ade/dashboard/catalog/CatalogItemCard.tsx`, cloned from `ProjectsDashboardProjectCard.tsx` and wired into the Catalog screen's card grid (`src/app/ade/dashboard/catalog/page.tsx`) in place of the MFI-23.3 inline card. It reproduces every project-card affordance — gradient avatar, name, short id (`cat_…`)/slug, status badge (Active/Disabled/Deleted), the clickable **quality** and **lint-grade** orbs, the creator chip and the relative-time footer — with two catalog-specific differences: a `formatSlot` carries the format/source pills (MFI-23.5; today the existing `CatalogFormatBadge`) and there is intentionally **no Publish** anywhere. The orbs open the *same* `ProjectQualityHistoryDialog` the Projects screen uses (quality → quality-history section, lint → lint section), reached via `getProjectQualityHistory(item.id)` — a catalog item's id *is* a project id; when an item has no browser-local history (the common server-import case) the orbs fall back to the server-captured `qualityScore`/`qualityGrade` so they still render a grade. The per-item actions dropdown now offers **View** (→ versions) / **Lint** (→ lint report) / **Convert to OpenAPI** (informs the user the conversion is performed by the import routing, MFI-23.7/23.11) / **Delete**, plus the existing undelete + permanent-delete, and never Publish. Tests: new `apiome-ui/tests/catalog-item-card.test.tsx` (15 — affordances, status badges, orb scores from history *and* server fallback, dash orbs when unscored, View navigation incl. the deleted no-op, no-publish) and extended `catalog-page.test.ts` (+4 — card wiring, format/actions slots, orb→dialog wiring, View/Lint/Convert present & no publish). `tsc`/eslint/`next build` clean. apiome-ui 0.27.0 → 0.28.0.
- **Problem.** Catalog items need a card/row visually consistent with project cards.
- **Solution / Scope.** A `CatalogItemCard` cloned from `ProjectsDashboardProjectCard.tsx`: gradient avatar, name, short id/slug, status badge, **lint-grade orb** (→ lint report) and **quality orb** (→ quality history), creator + updated timestamp, and an actions dropdown that includes **View / Lint / Convert to OpenAPI / Delete** but **omits Publish**. Slots for the new format/source pills (23.5).
- **Acceptance Criteria.** Card renders all project-card affordances except publish; orbs open the same dialogs; actions menu has no publish path.
- **Dependencies / Parallelism.** After 23.2. Parallel with 23.3/23.5.
- **Technical Stack.** React 19, Tailwind, lucide-react.

### MFI-23.5 — Format + protocol + source pills  ·  **#4014**
- **Status.** Implemented in `apiome-ui`. New data-driven registry `src/app/utils/catalog-format-registry.ts` (modeled on `project-domain-categories.ts`, no React) maps each import **format** (OpenAPI/Swagger/gRPC/GraphQL/AsyncAPI/CloudEvents/OData/WSDL/Smithy/Thrift/RAML/API Blueprint/Avro/Protobuf/JSON Schema/XSD) and **protocol/paradigm** (the canonical `ApiParadigm` — REST/RPC/event/graph/data-schema — plus `agent`) to an icon + a centralized tone palette, with version- and punctuation-insensitive resolvers (`openapi-3.1`/`data_schema` resolve correctly) that return `undefined` for unknown tokens; plus `resolveCatalogSource(...)` which derives the **source material** (file name / URL / pasted / live-discovery) from the item's `formatMetadata`/`metadata` (camelCase or snake_case), inferring the input kind from the label when none is recorded and compacting URLs to host+path. Three reusable, presentational pills — `src/app/components/ui/catalog/{FormatPill,ProtocolPill,SourceBadge}.tsx` — render these (an unknown-but-present format/protocol degrades to a **neutral** pill showing the raw token; absent data renders nothing) and are wired into the Catalog screen's `CatalogFormatBadge` (`src/app/ade/dashboard/catalog/page.tsx`), used by both card (23.4) and table views and ready for the detail view (23.9). Tests: new `tests/catalog-format-registry.test.ts` (registry uniqueness, headline-format/protocol resolution, version/punctuation normalization, unknown→undefined, source derivation across file/url/discovery/either-bag) and `tests/catalog-pills.test.tsx` (known-label render, neutral degradation, null-render, URL compaction + full-URL tooltip) — 28 new assertions. Full UI suite green (270 suites, 3930 tests); `tsc`/eslint/`next build` clean. apiome-ui 0.28.0 → 0.29.0.
- **Problem.** The request calls out a **pill showing the imported file's format**, plus source material — the catalog's headline metadata.
- **Solution / Scope.** A reusable **FormatPill** + a format registry (icon + color per format: OpenAPI, gRPC, GraphQL, AsyncAPI, OData, WSDL, Smithy, RAML, API Blueprint, Avro, …) modeled on `src/app/utils/project-domain-categories.ts`; a **ProtocolPill** (REST/RPC/event/graph/data-schema/agent); and a **source-material badge** (file name / source URL / live-discovery) with an icon for the input kind. Used on the card (23.4) and detail (23.9).
- **Acceptance Criteria.** Each catalog item shows a correct format pill + protocol pill + source badge; unknown formats degrade to a neutral pill.
- **Dependencies / Parallelism.** After 23.2. Parallel with 23.3/23.4.
- **Technical Stack.** React, Tailwind, lucide-react.

### MFI-23.6 — "Catalog" side-nav entry  ·  **#4015**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-ui` as a single new entry in `src/app/components/ade/dashboard/DashboardSideNav.tsx`. A **Catalog** item now sits in the **Specifications** section directly above MCP Servers (and beside Projects), using the `Library` lucide icon — the same icon the Catalog screen header uses — links to `/ade/dashboard/catalog`, is tenant-gated exactly like Projects (`disabled: !hasTenant`, so with no tenant it renders the non-navigable, dimmed `cursor-not-allowed` row rather than a link), and carries the amber **Preview** pill like MCP Servers. The `isActive` helper gained a catalog branch so the entry highlights on `/ade/dashboard/catalog` and any child route (e.g. a future item detail). Tests: new `apiome-ui/tests/dashboard-sidenav-catalog.test.tsx` (4 — Specifications placement + Preview pill, link target with a tenant, disabled/non-link tenant-gating without a tenant, active-state on the route and its children). `tsc`/eslint/`next build` clean; catalog + side-nav suites green (10 suites, 143 tests). apiome-ui 0.29.0 → 0.30.0.
- **Problem.** The catalog needs a discoverable nav entry beside Projects.
- **Solution / Scope.** Add a **Catalog** entry to `DashboardSideNav.tsx` in the "Specifications" section (icon e.g. `Library`/`Boxes`, href `/ade/dashboard/catalog`, disabled with no tenant), optionally with a "Preview" pill like MCP Servers.
- **Acceptance Criteria.** Catalog appears in the side nav, navigates to the screen, and is tenant-gated like Projects.
- **Dependencies / Parallelism.** After 23.3. Parallel with the rest of the UI work.
- **Technical Stack.** Next.js, Tailwind.

### MFI-23.7 — Route OpenAPI-worthy non-OpenAPI imports → catalog  ·  **#4016**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest` as the single Project-vs-Catalog decision point on the generalized import job (MFI-1.2). New `apiome-rest/src/app/import_routing.py` exposes `decide_import_routing(adapter, model) → ImportRoutingDecision` — a **pure** function (no I/O, fully unit-testable) that branches on the canonical model's **emitted format** (`model.format`), not the source tool: OpenAPI/Swagger (`openapi-3.0`/`openapi-3.1`/`swagger-2.0`, the `PUBLISHABLE_FORMATS` set) → publishable **Project** (`publishable=True`, exactly as today) — and **TypeSpec-emitted OpenAPI** routes here too, since a TypeSpec adapter normalizes to an `openapi-3.x` format; every other OpenAPI-worthy import (gRPC/GraphQL/AsyncAPI/OData/… — carries operations and/or channels) → non-publishable **catalog item** (`publishable=False`, the MFI-23.1 slice); a pure data-schema source (Avro/Protobuf-schema/JSON-Schema/XSD — types but no callable surface) → catalog item additionally flagged **`schemas_only`** (set on the `DATA_SCHEMA` paradigm *or* the structural signal "types, no operations, no channels", so a mis-declared paradigm is still caught). The frozen `ImportRoutingDecision` carries `target`/`publishable`/`schemas_only`/`reason` plus paradigm/format/entity-counts, and `as_dict()` serializes it. The in-process pipeline (`import_source_pipeline.py`) computes the decision after normalize, emits a new `ROUTING_DECIDED` event carrying the decision context, and records `routing` on the completed-job `summary` — i.e. "the decision + reason is recorded for the UI to explain". Because the in-process path is still preview-only (no catalog write — MFI-1.2), the actual `db.create_project(..., publishable=...)` call is made by the canonical→catalog persistence hook a later format epic wires through, which consumes `routing.publishable`; the OpenAPI worker path is unchanged and keeps minting publishable Projects. Tests: `apiome-rest/tests/test_import_routing.py` (19 — every paradigm, the OpenAPI/TypeSpec carve-out, schemas-only flagging, empty-import + case-insensitivity + immutability edge cases, and pipeline summary/`ROUTING_DECIDED` recording) plus an updated event-sequence assertion in `test_import_source_pipeline.py`. Full rest suite green (2195 passed, 2 pre-existing live-DB skips). apiome-rest 1.43.0 → 1.44.0.
- **Problem.** The import pipeline must decide whether a finished import becomes a publishable Project or a non-publishable catalog item.
- **Solution / Scope.** In the generalized import job (MFI-1.2), branch on the adapter's format/paradigm: **OpenAPI/Swagger (and TypeSpec-emitted OpenAPI)** → Project (publishable, as today); **everything else that is OpenAPI-worthy** (has operations/types) → **catalog item** (23.1). Pure data-schema sources (Avro/Protobuf-schema/JSON-Schema/XSD) also catalog, flagged "schemas-only". The decision + reason is recorded on the item for the UI to explain.
- **Acceptance Criteria.** Importing gRPC/GraphQL/AsyncAPI/OData/etc. produces a catalog item, not a project; importing OpenAPI still produces a project; the routing reason is stored.
- **Dependencies / Parallelism.** After 1.2, 23.1. Blocks the catalog being populated.
- **Technical Stack.** Python async.

### MFI-23.8 — Non-publishable enforcement (UI + REST)  ·  **#4017**  ·  ✅ **Done**
- **Status.** Enforced the non-publishable rule in **both** layers, not just the UI. **REST:** `publish_version` (`apiome-rest/src/app/versions_routes.py`) now fetches the owning project up front and refuses with **409** when `publishable is False` — a catalog item (the MFI-23.1 `publishable=false` slice) — with a message pointing at the convert-to-OpenAPI flow; the guard is strict (`is False`), so a missing/None/True flag publishes exactly as before, and the existing description/compatibility prechecks and project publish are untouched. The project row is now fetched once and reused for the commit-policy lookup (no extra query). **UI:** the shared versions screen (`apiome-ui/src/app/ade/dashboard/versions/page.tsx`) gates every Publish affordance through a new pure predicate `isProjectPublishable` (`apiome-ui/src/app/utils/catalog-publishable.ts`): the `Project` shape carries `publishable`, the per-revision **Publish** menu item is withheld for catalog items, and both `handleRowAction('publish')` and the `handlePublishClick` funnel defensively refuse with a convert-to-OpenAPI toast — so a catalog item drilled into from the Catalog screen shows no publish path while ordinary projects publish normally. Tests: `apiome-rest/tests/test_publish_catalog_item_gate.py` (3 — refusal for a catalog item, publish proceeds for a publishable project, and back-compat publish when the flag is absent) and `apiome-ui/tests/catalog-publishable.test.ts` (6 — the predicate's true/false/absent/null/unresolved cases). Full rest publish/versions/projects suites green; UI build green. apiome-rest 1.44.0 → 1.45.0; apiome-ui 0.30.0 → 0.31.0.
- **Problem.** Catalog items "are not candidates for publishing because they may be incomplete" — this must be enforced, not merely visually omitted.
- **Solution / Scope.** **UI:** no publish action on catalog cards/detail/menus; **REST:** the publish endpoints reject a catalog item (or any `publishable=false` artifact) with a clear error pointing to the convert-to-OpenAPI flow. Existing project publish is unchanged.
- **Acceptance Criteria.** No publish affordance anywhere for catalog items; a direct publish API call against a catalog item is refused with a helpful message; projects publish normally.
- **Dependencies / Parallelism.** After 23.1. Parallel with 23.3/23.4.
- **Technical Stack.** FastAPI, Next.js.

### MFI-23.9 — Catalog item detail + source-material panel  ·  **#4018**  ·  ✅ **Done**
- **Status.** Implemented across `apiome-rest` and `apiome-ui` as the catalog item *detail* view over the MFI-23.2 read API. **REST:** the detail route `GET /v1/catalog/{tenant_slug}/{item_id}` now returns a `CatalogItemDetailSchema` — the MFI-23.2 envelope plus a normalized-content `summary` (services/operations/types/channels counts) and a `source` material descriptor (input kind / label / URL / `downloadable`), both derived from the latest revision's `format_metadata` by new **pure, unit-tested** helpers in `apiome-rest/src/app/catalog_detail.py` (tolerant of camel/snake + a nested `counts` bag — the `ImportRoutingDecision.as_dict()` shape — so they light up the moment a later format epic records that provenance; today's rows degrade to all-null counts + a non-downloadable source). A new `GET …/{item_id}/source` endpoint makes the original source viewable/downloadable: it **streams** captured inline content as a format-typed attachment, **307-redirects** to a recorded source URL, or **404s** when nothing was captured. Both reads stay on the non-publishable slice (a Project id → 404) and auth via JWT/API key. **UI:** new route `src/app/ade/dashboard/catalog/[id]/page.tsx` + `CatalogItemDetailClient.tsx` mirrors the dashboard detail pattern — back link, avatar/title header with the reused `FormatPill`/`ProtocolPill`/`SourceBadge` (MFI-23.5) and the **quality/lint orbs** opening the shared `ProjectQualityHistoryDialog` — then four panels: **source material** (view/download via a new `src/app/api/catalog/[itemId]/source/route.ts` proxy that passes content/`Content-Disposition` through and surfaces the upstream redirect *to the browser* rather than following it server-side, an SSRF guard), **normalized summary** (the counts, or a "not captured yet" note), and **provenance** (format/protocol, tool-version chips, import-job reference, timestamps + creator). The Catalog screen's card body / table name now open the detail view, and the per-item menu gains a **Details** action (alongside the existing View → versions, Lint, Convert, Delete; still **no Publish** — MFI-23.1). Shared card-presentation helpers were extracted to `src/app/utils/catalog-card-presentation.ts` so the card and detail header render an item identically. Tests: `apiome-rest/tests/test_catalog_detail.py` (helper derivations) + `test_catalog_routes.py` additions (detail summary/source + the three /source outcomes + auth); `apiome-ui/tests/catalog-item-detail.test.tsx` (8 — header/pills, summary, download affordance, provenance, orb→dialog, graceful degradation, error, no-publish), plus `catalog-proxy.test.ts` / `catalog-page.test.ts` / `catalog-item-card.test.tsx` additions. Full rest suite green (2218 passed, 2 pre-existing live-DB skips); full UI suite green (273 suites, 3957 tests); `tsc`/eslint/`next build` clean. apiome-rest 1.45.0 → 1.46.0; apiome-ui 0.31.0 → 0.32.0.
- **Problem.** Users need to inspect *what was imported* and *where it came from*.
- **Solution / Scope.** A catalog item detail view (route under `/ade/dashboard/catalog/...`) showing: the **original source material** (raw file/bytes or source URL or discovery target), **format/protocol** pills, **tool versions** + import-job reference (provenance), a normalized-content summary (services/operations/types counts), and links to lint + quality. Mirrors the versions/detail pattern.
- **Acceptance Criteria.** Detail view shows source material + provenance + format/protocol + a normalized summary; raw source is viewable/downloadable.
- **Dependencies / Parallelism.** After 23.2/23.5. Parallel with 23.10.
- **Technical Stack.** Next.js, FastAPI.

### MFI-23.10 — Lint/score + quality-history parity  ·  **#4019**
- **Problem.** Catalog items must be lintable "through the same type of screen that the projects screen provides."
- **Solution / Scope.** Reuse the lint-report view (`/api/projects/{projectId}/versions/{versionId}/lint` analog for catalog items) and `ProjectQualityHistoryDialog` so the grade/quality orbs on the catalog card and detail open the identical dialogs. Lint runs over the canonical model via the per-format rule packs (MFI-EPIC-4).
- **Acceptance Criteria.** Clicking a catalog item's lint/quality orbs opens the same dialogs as projects, populated from its lint/score history.
- **Dependencies / Parallelism.** After 4.4, 23.2. Parallel with 23.9.
- **Technical Stack.** Next.js, FastAPI.

### MFI-23.11 — Convert-to-Project promotion (EPIC-22 entry)  ·  **#4020**  ·  ✅ **Done**
- **Status.** Implemented across `apiome-rest` and `apiome-ui` as the **bridge** that closes the loop between the Catalog (EPIC-23) and the convert flow (EPIC-22): the fidelity preview + convert job + provenance ledger already shipped (MFI-22.4/22.5/22.6), so 23.11 adds the **converted-state back-link** the acceptance calls for. **REST:** the catalog list (`GET /v1/catalog/{tenant_slug}`) and detail (`…/{item_id}`) reads now LEFT-JOIN the newest `apiome.conversion_provenance` row for each item (MFI-22.5) plus its target Project (two new query fragments, `_CATALOG_CONVERSION_LATERAL` / `_CATALOG_CONVERSION_COLUMNS`, so the projection is a single joined read — no N+1, no second round-trip), and project it onto a new `conversion` field (`CatalogConversionRef`): the publishable **Project** the item was converted into (id + name/slug, or a `projectDeleted` flag when the target was since removed), the produced revision, whether the latest conversion was a **re-convert**, and the fidelity grade/tier. An item that was never converted serializes `conversion: null`; a pure `_build_conversion_ref` helper in `catalog_routes.py` reads the prefixed `conv_*` columns and the internal projection columns never leak onto the envelope. **UI:** a pure, unit-tested `src/app/utils/catalog-conversion.ts` (href/label/live-link/action-label helpers) backs a shared **`ConvertedBadge`** ("Converted → {project}" / "Re-converted → {project}", a live link to the produced project's versions screen, or struck-through plain text when that project was deleted) rendered on the Catalog **card** (a new `conversionSlot` on `CatalogItemCard`), the **table** row, and the **detail** view (`CatalogItemDetailClient` gains a converted-state panel *and* a Convert/Re-convert button that opens the existing `ConversionPreviewDialog`, reloading on success so the back-link appears). The per-item Convert action relabels to **"Re-convert to OpenAPI"** once converted — re-convert is always allowed (a changed source appends a new version rather than duplicating the Project, MFI-22.5) — and there is still **no Publish** (the catalog item itself stays non-publishable, MFI-23.1). Acceptance met: converting a catalog item launches the fidelity preview and, on confirm, yields a linked publishable project; the item then shows its converted state + link on both card and detail. Tests: `apiome-rest/tests/test_catalog_routes.py` (+5 — null-conversion, list/detail back-link serialization, deleted-target flag, no `conv_*` leak; full rest suite green — 2807 passed, 31 skipped); `apiome-ui` `tests/catalog-conversion.test.ts` (14 — href/label/live/action-label), `catalog-item-card.test.tsx` (+2 — slot render/omit), `catalog-item-detail.test.tsx` (+3 — convert action, converted back-link + re-convert relabel, deleted-target plain text), `catalog-page.test.ts` (+3 — badge slot + table wiring) (full UI suite green — 277 suites, 4009+ tests; `tsc`/eslint clean). OpenAPI spec regenerated (new `CatalogConversionRef` + `conversion` on the catalog schemas). apiome-rest 1.68.0 → 1.69.0; apiome-ui 0.37.0 → 0.38.0.
- **Problem.** The catalog needs an exit ramp to a publishable artifact — this is where EPIC-22 plugs in.
- **Solution / Scope.** A **"Convert to OpenAPI"** action on the catalog card/detail opens the **MFI-EPIC-22** fidelity preview (22.4) for that item; on confirm, the convert job (22.5) creates a publishable **Project**, and the catalog item is marked **"Converted → {project}"** with a back-link (re-convert allowed if the source changes). The catalog item itself stays non-publishable.
- **Acceptance Criteria.** Converting a catalog item launches the fidelity preview and, on confirm, yields a linked publishable project; the catalog item shows its converted state + link.
- **Dependencies / Parallelism.** After 22.4/22.5, 23.4/23.9. The bridge between EPIC-23 and EPIC-22.
- **Technical Stack.** Next.js, FastAPI.

### MFI-23.12 — Read-only Designer/Studio view of catalog items  ·  **#4021**
- **Problem.** "These projects may be visible using the Designer at some point" — view-only, since they're incomplete and non-publishable.
- **Solution / Scope.** Allow opening a catalog item in the Studio/editor (`/ade/studio/editor`) in a **read-only / preview** mode that renders the normalized model (and raw source) without enabling edit/save/publish. Lays groundwork for a future "edit to complete then convert" path.
- **Acceptance Criteria.** A catalog item opens in the Designer read-only; no edit/save/publish is possible; normalized content is rendered.
- **Dependencies / Parallelism.** After 23.9. Later (non-MVP) — parallel with everything once 23.9 lands.
- **Technical Stack.** Next.js.

---

## MFI-EPIC-28 — Catalog UX & Look-and-Feel Improvements · polish  ·  **#4116**

The Catalog list/detail surface (MFI-EPIC-23) and its mockup-parity layer (MFI-EPIC-24…27, see
`docs/ROADMAP_MULTI_FORMAT_IMPORT_UI.md`) are functionally complete, but a usability review against
the freshly modernized **MCP catalog screens** (V2-MCP / MCAT — Monaco-backed schema & diff viewers,
selectable side-by-side/unified diffs, expand-all controls, professional lint report layout) shows
the Catalog now trails the MCP surface in day-to-day ergonomics. This epic closes that gap: it is
**UI-only polish** over shipped behavior — no new backend endpoints except where noted (28.1 needs a
compare read it can reuse from the existing versions dashboard machinery).

> **Reuse, don't rebuild.** The MCP work already produced the shared primitives these tickets need:
> `McpJsonViewer` (read-only Monaco JSON), `McpJsonDiffViewer` (split/unified Monaco diff),
> `McpDisclosure` (lazy-mounting collapsible) in `apiome-ui/src/app/components/ui/mcp/`.
> Ticket 28.7 promotes them to a format-neutral home first; the rest consume them.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 28.1 · #4117 ✅ | Inline version diff on catalog detail | Diff two ticked revisions in-place (Monaco split/unified + expand-all) instead of deep-linking off-page | ui,version-control | Y | Y | M | apiome-ui |
| 28.2 · #4118 ✅ | Lint & Score parity with the MCP report | Provenance strip, MUST/SHOULD/advisory tier grouping, finding→entity deep links | ui,linting | Y | Y | M | apiome-ui |
| 28.3 · #4119 ✅ | Parsed-model explorer | Collapsible entities (lazy render), per-group filter, raw-JSON toggle, anchor deep-links | ui | Y | Y | M | apiome-ui |
| 28.4 · #4120 ✅ | Unified toolbar + persisted view preferences | One sticky toolbar (search/filter/group/sort), format facet, localStorage persistence | ui | Y | Y | S | apiome-ui |
| 28.5 · #4121 | Bulk actions | Multi-select cards/rows → bulk convert / soft-delete / restore | ui,rest | N | N | M | apiome-ui,apiome-rest |
| 28.6 · #4122 | Skeleton loading states | Skeleton cards/rows + per-tab detail skeletons instead of spinners | ui | Y | N | S | apiome-ui |
| 28.7 · #4123 ✅ | Promote shared code-viewer primitives | Move `McpJsonViewer`/`McpJsonDiffViewer`/`McpDisclosure` to a format-neutral `ui/code` module | ui | Y | Y | S | apiome-ui |
| 28.8 · #4124 | URL-synced detail tabs & a11y pass | `?tab=` deep links, keyboard nav on grids/menus, dialog focus management | ui,accessibility | Y | N | M | apiome-ui |

### MFI-28.1 — Inline version diff on the catalog detail · #4117 · ✅ **Done**
- **Status.** Implemented in `apiome-ui`. `CatalogVersionsPanel` (`src/app/components/ade/dashboard/catalog/CatalogVersionsPanel.tsx`) now renders the ticked pair's diff **in-place** — ticking two revisions no longer routes away. The compare read reuses the versions-dashboard machinery via `src/app/utils/catalog-revision-diff.ts` (`loadCatalogRevisionSpec` → the `buildOpenApiSpecJsonForVersion` server action) — no new endpoints. The diff renders in the shared `McpJsonDiffViewer`, which gained an optional `hideUnchangedRegions` prop (default `true`, MCP unchanged) so the panel's **expand-all/collapse-all** control folds or reveals unchanged regions; the side-by-side/unified toggle persists to localStorage (`catalog-versions-diff-mode`); `minLines` sets the minimum viewport height. The off-page "Open version history" link is retained as the escape hatch. Ordering is shared with the deep-link via the new `orderRevisionPairOldToNew` helper in `catalog-versions-timeline.ts` (older → base, newer → head). Tests: `tests/catalog-versions-panel.test.tsx` and `tests/catalog-versions-timeline.test.ts` (full apiome-ui suite green). apiome-ui 0.44.4 → 0.45.0.
- **Problem.** The detail's Versions tab (MFI-25.7) lets the reader tick two revisions, but **Diff** navigates away to the versions dashboard — losing catalog context, tab state, and scroll position. The MCP endpoint detail renders its diff inline with a selectable side-by-side/unified layout and an expand/collapse-all control; the Catalog should match.
- **Solution / Scope.** Render the selected pair's diff inline in the Versions pane using the shared Monaco diff viewer (split/unified toggle persisted in localStorage, minimum viewport height, expand-all over per-change disclosures). Keep the off-page "Open version history" link as the escape hatch for the full dashboard.
- **Acceptance Criteria.** Ticking two revisions renders the diff in-place without a route change; layout is selectable (side-by-side/unified) and remembered; an expand-all/collapse-all control governs per-change detail; the off-page link still works.
- **Dependencies / Parallelism.** After 28.7 (or consume from `ui/mcp` and migrate later). Parallel with everything else.
- **Technical Stack.** Next.js, monaco-editor.

### MFI-28.2 — Lint & Score parity with the MCP report layout · #4118 · ✅ **Done**
- **Status.** Implemented in `apiome-ui`. `CatalogLintPanel` (`src/app/components/ade/dashboard/catalog/CatalogLintPanel.tsx`) now leads its loaded report with a **provenance strip** (version · scored-at · stored-vs-computed source · fingerprint) and renders findings in **MUST / SHOULD / advisory tier sections** with per-tier counts, mirroring the MCP tab's visual language. Each finding's `path` becomes a **deep link** when it resolves to a parsed entity: clicking it switches to the Overview tab, scrolls to the entity, and highlights it with a transient ring. The pure helpers live in `src/app/utils/catalog-lint-panel.ts` (`catalogLintGroupByTier`/`catalogLintTierCounts`, `catalogLintProvenance`, `catalogEntityAnchorId`, `resolveCatalogFindingEntity` — mirroring `mcpLintUi`); `CatalogParsedModel` renders each entity with the shared anchor id + highlight, and `CatalogItemDetailClient` owns the pending/highlighted-anchor state and the tab-switch/scroll effect. Source classification is derived from the catalog report's captured-score fields (no REST change): never-captured → *Computed live*, fresh captured → *Stored report*, stale captured → *Recomputed (stored is stale)*; the scored-at value is the item's `updated_at`. Tests: `tests/catalog-lint-panel.test.tsx`, `tests/catalog-lint-panel-util.test.ts`, `tests/catalog-parsed-model.test.ts`, and a deep-link integration case in `tests/catalog-item-detail.test.tsx` (full apiome-ui suite green, 4214 tests). apiome-ui 0.45.0 → 0.46.0.
- **Problem.** The inline lint pane (MFI-25.5/25.6) shows gauge + category bars + a flat findings list, but lacks the report provenance (scored-at, stored-vs-computed, fingerprint) and the MUST/SHOULD/advisory **tier grouping** the MCP Lint & Score tab leads with; findings also don't link back to the entity they flag.
- **Solution / Scope.** Add a provenance strip to the report header; group findings into MUST/SHOULD/advisory sections (severity → tier, one visual language with the MCP tab); make each finding's `path` a deep link that switches to the Overview tab and scrolls/highlights the matching parsed entity (mirror `mcpCapabilityAnchorId`).
- **Acceptance Criteria.** The pane shows scored-at/source metadata; findings render in tier sections with per-tier counts; clicking an entity-scoped finding lands on the highlighted entity in Overview.
- **Dependencies / Parallelism.** Independent; pairs well with 28.3 (which mints the anchors).
- **Technical Stack.** Next.js.

### MFI-28.3 — Parsed-model explorer · #4119 · ✅ **Done**
- **Status.** Implemented in `apiome-ui`. `CatalogParsedModel` (`src/app/components/ade/dashboard/catalog/CatalogParsedModel.tsx`) now renders each group as an **explorer card** instead of a wall of expanded entities: every entity is a **lazy-mounting disclosure** whose field rows mount only on first expand (small entities in small groups default open; large groups — > `PARSED_LARGE_GROUP_ENTITY_COUNT` entities — stay fully collapsed so a 200-entity model renders fast), each group carries a live **name/tag filter** (`filterParsedEntities`, with a match count and a clear button) and a **raw-model toggle** that swaps the entity list for the group's normalized JSON (`parsedGroupToJson`) in the shared read-only Monaco viewer (`McpJsonViewer`, consumed from `ui/mcp` until MFI-28.7 promotes it to `ui/code`). Every entity keeps its stable anchor id (`catalogEntityAnchorId`, MFI-28.2), and a deep-linked entity is **force-expanded and pinned past an active filter** so lint findings always land on a visible, highlightable target. The default-open heuristic, filter, and JSON serialization are pure exported helpers (`parsedEntityDefaultOpen`/`parsedEntityMatchesFilter`/`filterParsedEntities`/`parsedGroupToJson`). Tests: `tests/catalog-parsed-model.test.ts` (helpers) + new `tests/catalog-parsed-explorer.test.tsx` (12 render/interaction cases — collapsed-large-model, lazy field mount, live filter + no-matches, clear, deep-link pin/expand, raw-model toggle) + the existing `tests/catalog-item-detail.test.tsx` deep-link case (full apiome-ui suite green — 298 suites, 4234 tests; `tsc`/eslint clean; `next build` green). apiome-ui 0.46.0 → 0.47.0.
- **Problem.** The Overview's parsed entity groups (MFI-25.3) render every entity and field expanded — a large GraphQL schema or Protobuf package becomes an unscannable wall, with no way to filter or to view the underlying normalized JSON.
- **Solution / Scope.** Make each entity a lazy-mounting disclosure (fields render on expand; small entities may default open), add a per-group filter box (name/tag), stable anchor ids per entity (consumed by 28.2's deep links), and a "raw model" toggle that renders the group's normalized JSON in the shared read-only Monaco viewer.
- **Acceptance Criteria.** A 200-entity model renders fast and collapsed; filtering narrows entities live; every entity is addressable by anchor; the raw-JSON toggle shows the normalized model per group.
- **Dependencies / Parallelism.** After 28.7 for the viewer/disclosure primitives. Parallel with 28.1/28.2.
- **Technical Stack.** Next.js, monaco-editor.

### MFI-28.4 — Unified catalog toolbar + persisted view preferences · #4120 · ✅ **Done**
- **Problem.** The list screen splits its controls across the page header (search, card/table toggle, show-deleted) and a second chip row (view filters, group, sort) — two visual rows with different idioms; none of the choices survive a reload; and there is no way to filter by **format**, the Catalog's defining facet.
- **Solution / Scope.** Consolidate into one sticky toolbar under the header (search · filter chips · format facet dropdown · group · sort · view toggle); persist view mode, group mode, sort column/direction, and show-deleted in localStorage; keep every existing testid/behavior.
- **Status.** Implemented in `apiome-ui`. The list header now carries only the **Import** action; every list control lives in one **sticky toolbar** (`data-testid="catalog-toolbar"`) rendered in both the empty and populated states (so **Show deleted** stays reachable when the active list is empty but soft-deleted items exist): row one is search · the new **format facet** · card/table toggle · show-deleted; row two is the view filter chips · group (cards only) · sort. The view/group/sort/show-deleted choices are hydrated once from localStorage and written back whenever any changes, via a validated, versioned, self-healing preferences layer (`src/app/utils/catalog-view-preferences.ts`: `loadCatalogViewPreferences`/`persistCatalogViewPreferences` + pure `coerce`/`parse`/`serialize` helpers — a corrupt or stale blob degrades per-field to the defaults; all localStorage access is SSR-safe and non-throwing). The **format facet** (`CatalogFormatFacet.tsx`) is a controlled multi-select that lists only the formats actually present (each item's `sourceFormat` resolved through the format registry, de-duplicated and label-sorted), with an active-count badge and Clear; an empty selection means "all formats". Selecting one or more formats keeps only items whose resolved format id is in the set; stale selections self-prune when the underlying formats leave the list. Every existing testid/behavior is preserved. Tests: new `tests/catalog-view-preferences.test.ts` (16 cases — defaults, coercion/validation, round-trip, load/persist, corrupt-blob self-heal, quota/SecurityError non-throw) + new `tests/catalog-format-facet.test.tsx` (8 render/interaction cases — disabled-empty, open, toggle on/off, count badge, clear, Escape) + extended `tests/catalog-page.test.ts` (unified-toolbar, hydration, persistence, format-filter contract). Full apiome-ui suite green — 300 suites, 4260 tests; `tsc`/eslint clean; `next build` green. apiome-ui 0.47.0 → 0.48.0.
- **Dependencies / Parallelism.** Independent; UI-only.
- **Technical Stack.** Next.js.

### MFI-28.5 — Bulk actions on the catalog list · #4121
- **Problem.** Every action (convert, delete, restore) is one-item-at-a-time through a per-row menu; importing a directory of protos or a suite of AsyncAPI docs then converting them is dozens of clicks.
- **Solution / Scope.** Add multi-select (checkboxes on cards/table rows + a select-all per view) with a floating action bar: bulk soft-delete, bulk restore, and bulk convert (queues the EPIC-22 convert per item, each still individually confirmable or with an explicit "apply fidelity warning to all" gate). Server-side: reuse existing per-item endpoints; a batch endpoint is optional follow-up.
- **Acceptance Criteria.** Selecting N items exposes bulk delete/restore/convert; bulk convert runs the fidelity-gated flow per item; partial failures are reported per item.
- **Dependencies / Parallelism.** After 28.4 (toolbar hosts the selection state). The only ticket with possible REST work.
- **Technical Stack.** Next.js, FastAPI (optional batch endpoint).

### MFI-28.6 — Skeleton loading states · #4122
- **Problem.** The list and every detail pane show a bare spinner/text line while loading, so the layout jumps when content lands; the dashboard already has a `Skeleton` primitive that most newer screens use.
- **Solution / Scope.** Skeleton cards (grid) and skeleton rows (table) matching the real layout; per-pane skeletons for detail tabs (stats tiles, gauge, timeline rows); keep the existing loading testids.
- **Acceptance Criteria.** Initial loads render layout-stable skeletons; no content jump on data arrival.
- **Dependencies / Parallelism.** Independent; trivially parallel.
- **Technical Stack.** Next.js.

### MFI-28.7 — Promote shared code-viewer primitives out of `ui/mcp` · #4123 · ✅ **Done**
- **Problem.** The Monaco-backed read-only JSON viewer, split/unified diff viewer, and lazy disclosure shipped under `src/app/components/ui/mcp/` for the MCP screens, but they are format-neutral and the Catalog (28.1/28.3), primitives, and future format screens all want them. Importing catalog UI from an `mcp` module is misleading.
- **Solution / Scope.** Move `McpJsonViewer` → `ui/code/JsonViewer`, `McpJsonDiffViewer` → `ui/code/JsonDiffViewer`, `McpDisclosure` → `ui/code/Disclosure` (neutral names, language prop instead of JSON-only where cheap); re-export from `ui/mcp` for back-compat; update the design-system gallery.
- **Status.** Implemented in `apiome-ui`. A new **`src/app/components/ui/code`** module owns the three primitives — `JsonViewer`, `JsonDiffViewer` (both now format-neutral via a `language` prop defaulting to `json`, passed through to Monaco), and `Disclosure` — plus a barrel `index.ts`. The old `ui/mcp/{McpJsonViewer,McpJsonDiffViewer,McpDisclosure}.tsx` files became **thin back-compat re-export shims** that alias the neutral components (and the `McpDiffMode`/`Mcp*Props` type names) to their old identifiers, so the MCP screens (`McpEndpointDetailClient`, `McpVersionHistory`) and the `ui/mcp` barrel keep working unchanged. The **catalog** consumers were promoted off the misleading `mcp` path to `@/app/components/ui/code`: `CatalogParsedModel` (`JsonViewer`) and `CatalogVersionsPanel` (`JsonDiffViewer`/`DiffMode`). The design-system gallery (`/design-system/mcp`) documents all three under their neutral names, imported from `ui/code`, adding live `JsonDiffViewer` and `Disclosure` showcases beside the renamed `JsonViewer`. Tests: new `tests/ui-code-primitives.test.tsx` (8 cases — render + `language`-prop forwarding for both viewers, lazy-mount `Disclosure`, and back-compat identity of the `Mcp*` aliases via both the per-file shims and the barrel), plus the existing `catalog-versions-panel` diff-viewer mock repointed to `ui/code/JsonDiffViewer`. Full apiome-ui suite green — 301 suites, 4268 tests; `tsc`/eslint clean; `next build` green. apiome-ui 0.48.0 → 0.49.0.
- **Dependencies / Parallelism.** Do **first** in this epic — 28.1/28.3 consume it.
- **Technical Stack.** Next.js, monaco-editor.

### MFI-28.8 — URL-synced detail tabs & accessibility pass · #4124
- **Problem.** The detail's five tabs (MFI-25.1) are client state only — you cannot link a teammate to "the Lint tab of this item"; and the list's custom dropdown menus/card grids lack full keyboard support.
- **Solution / Scope.** Reflect the active tab in the URL (`?tab=lint`, shallow routing, default Overview) and honor it on load; add arrow-key navigation + Escape/focus-return to the actions dropdown; ensure card grids and the toolbar are fully keyboard-traversable; audit dialog focus traps.
- **Acceptance Criteria.** Deep links open the right tab; every list/detail control is operable by keyboard; axe/dev-mode a11y checks pass on both screens.
- **Dependencies / Parallelism.** Independent.
- **Technical Stack.** Next.js.

---

## MFI-EPIC-29 — Ingestion Intake Hardening  ·  **#4384**

The import intake accepts a **single** file, URL, or paste — but the formats this roadmap imports
are **multi-file in practice**: a proto tree with `import`s across directories, a GraphQL SDL
split per domain, an AsyncAPI suite sharing message files, WSDL+XSD graphs, RAML `!include`
trees, Smithy model directories, TypeSpec projects. The backend can already *compile* trees
(`buf build`, graphql-tools merge, and every v2 format's resolver), but nothing can *receive*
one. This epic gives the SPI real-world intake channels: archives (MVP), git repositories,
SSRF-guarded remote `$ref` resolution, bulk import, and secret scrubbing.

```mermaid
flowchart LR
  Z[zip / tar upload] --> X[unpack in 5.3 sandbox\nsize/entry caps]
  G[git repo + ref + path/glob] --> X
  X --> FS[fileset input\nroot doc + siblings]
  FS --> AD[adapter parse\nbuf / graphql-tools / AMF / smithy]
  RR[remote $ref resolver\nSSRF-guarded + cached] -.-> AD
  AD --> N[normalize → canonical]
  SCRUB[secret scrubbing] --> FS
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 29.1 | Archive (zip/tar) upload intake | accept `.zip`/`.tgz` across UI/REST/CLI; unpack sandboxed; route to adapter | multi-protocol,import,rest,ui,mvp | N | Y | M | apiome-rest,apiome-ui,apiome-cli | ✅ **Done** |
| 29.2 | Adapter multi-document (fileset) inputs | new SPI input kind `fileset`: proto tree, split SDL, AsyncAPI suite, WSDL+XSD | multi-protocol,rest,python,mvp | N | Y | M | apiome-rest | ✅ **Done** |
| 29.3 | Git-repo intake for adapter formats | extend the git source card to registry adapters (repo + ref + path/glob) | import,integrations,version-control | Y | N | M | apiome-rest,apiome-ui |
| 29.4 | SSRF-guarded remote $ref resolver | shared resolver for external `$ref`s (AsyncAPI/JSON-Schema) with cache + budgets | rest,validation,security | Y | N | M | apiome-rest |
| 29.5 | Bulk import of independent specs | one archive/repo containing N unrelated specs → N catalog items + per-item results | import,rest,ui | Y | N | M | apiome-rest,apiome-ui,apiome-cli |
| 29.6 | Secret scrubbing on intake | detect/redact credentials in uploaded payloads before persistence | security,validation,import | Y | N | M | apiome-rest |

### MFI-29.1 — Archive (zip/tar) upload intake  ·  **#4388**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/archive_intake.py` (+ `intake_paths.py`, `fileset.py`): `.zip`/`.tar.gz`/`.tgz` uploads are unpacked under configurable sandbox caps (entry count, total/per-file uncompressed size, depth) with MFI-9.1 path rules (no `..`, absolute paths, or symlink/hard-link tar entries). Root document auto-detection runs `detect_format` over archive members (service/import-aware tie-break for proto trees); explicit `archive_root` / CLI `--root` resolves ambiguity. Unpacked trees are handed to adapters via `ImportSource.parse_fileset` — gRPC wired today. REST `POST /v1/import/detect` accepts `document_base64` for archive sniffing; the catalog import dialog and `apiome import <format> --file` accept archives. Zip-bombs and path-traversal archives fail pre-parse with clear errors; single-file intake unchanged.
- **Problem.** Real-world protobuf (an MVP format!) is never one file; today a `.proto` with
  imports cannot be imported through the UI at all. Every v2 format has the same shape.
- **Solution / Scope.** Accept `.zip`/`.tar.gz` in the file intake (UI drop zone, REST import
  submit, CLI `--file`). Unpack inside the MFI-5.3 sandbox discipline: entry-count cap, total- and
  per-file-size caps, no path traversal (`..`/absolute/symlink entries rejected — extend the 9.1
  path-validation rules), depth cap. Detect the root document (`detect_format` over candidate
  entries; explicit `--root` / UI picker when ambiguous) and hand the unpacked tree to the adapter
  as a fileset (29.2).
- **Acceptance Criteria.** A zipped proto tree with cross-directory imports imports end-to-end via
  UI, REST, and CLI; a zip-bomb/path-traversal archive is rejected pre-parse with a clear error;
  single-file behavior unchanged.
- **Dependencies / Parallelism.** After 1.2, 5.3. Blocks 29.2 UI surfacing; parallel with 29.3.
- **Technical Stack.** Python (zipfile/tarfile hardened), FastAPI, Next.js, Typer.

### MFI-29.2 — Adapter multi-document (fileset) inputs  ·  **#4389**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/import_source.py` (`InputKind.FILESET`), `fileset.py` (`IntakeFileset` / `Fileset`), `asyncapi_fileset.py` (cross-file `$ref` bundling among members), and `parse_fileset` on the gRPC, GraphQL, and AsyncAPI adapters. Archive/git intake hands unpacked trees to `ImportSource.parse_fileset`; member names are recorded on the revision's `format_metadata` as `filesetMembers` / `filesetRoot` (alongside `intakeKind`). Fingerprints are computed on the normalized model as always (§6.2).
- **Problem.** The `ImportSource` SPI models file/url/paste/discovery — there is no input kind for
  "a root document plus its siblings," so adapters that *can* compile trees never receive them.
- **Solution / Scope.** Add a `fileset` input kind to the SPI descriptor + a `Fileset` payload
  (root + named members). Wire the three MVP adapters: **gRPC** (feed the tree to
  `buf build` with include paths), **GraphQL** (multi-file SDL merge — parser already supports
  it), **AsyncAPI** (resolve cross-file `$ref`s among members, no network). Fingerprint the
  *resolved* model as always (§6.2 normalize-before-hash); record member names in
  `format_metadata`.
- **Acceptance Criteria.** Each MVP adapter imports a multi-file fixture; the resolved fingerprint
  is identical whether the same content arrives pre-flattened or as a fileset; a missing member
  produces a diagnostic naming the unresolved import/ref.
- **Dependencies / Parallelism.** After 29.1 (or CLI-only before it). v2 format epics 11–17 adopt
  `fileset` as they land.
- **Technical Stack.** Python.

### MFI-29.3 — Git-repo intake for adapter formats  ·  **#4390**
- **Problem.** Specs live in git; the existing git source card serves only the legacy
  OpenAPI-family path. CI-adjacent teams want "import `protos/**` from this repo at this ref."
- **Solution / Scope.** Extend the git source to registry adapters: repo URL + ref + path or glob
  → shallow fetch (existing git plumbing) → build a fileset (29.2) → adapter import. Record
  repo/ref/commit in `format_metadata` for provenance; pairs with EPIC-31 for re-import-on-change
  later. Credentials via the existing credential vault.
- **Acceptance Criteria.** A repo path of protos imports via the git card and CLI; provenance
  shows repo+commit; private-repo auth reuses stored credentials.
- **Dependencies / Parallelism.** After 29.2. Parallel with 29.4/29.5.
- **Technical Stack.** Python, git, FastAPI, Next.js.

### MFI-29.4 — SSRF-guarded remote $ref resolver  ·  **#4391**
- **Problem.** AsyncAPI dereferences **in-document** `$ref`s only; shared message libraries and
  JSON-Schema bundles reference external URLs. Unresolved refs degrade the canonical model, and
  naive fetching is an SSRF hole.
- **Solution / Scope.** One shared resolver service used by adapters (AsyncAPI first, JSON-Schema
  next): fetch via `ssrf_guard.build_guarded_client`, per-import budgets (max refs, max depth, max
  bytes, timeout), content-addressed cache so a re-import doesn't re-fetch, and an explicit
  opt-in flag (default **off**; off = current behavior + a lint finding listing unresolved
  externals). Resolved refs are inlined before fingerprinting.
- **Acceptance Criteria.** An AsyncAPI doc with external message refs imports fully resolved when
  enabled; budgets terminate a hostile ref-chain; disabled mode lists unresolved refs as findings;
  every fetch passes the SSRF guard (redirects re-validated).
- **Dependencies / Parallelism.** After 1.2. Parallel with 29.3.
- **Technical Stack.** Python, httpx.

### MFI-29.5 — Bulk import of independent specs  ·  **#4392**
- **Problem.** Distinct from 29.1's one-spec-many-files: a team's "specs/" folder holds N
  unrelated documents. Importing them one by one doesn't scale to onboarding.
- **Solution / Scope.** When an archive/repo contains multiple *independent* root documents,
  offer bulk mode: auto-detect per file, group filesets, submit N import jobs, and render a
  per-item result list (imported → Catalog/Projects per the §0.2 routing policy; failed → reason).
  CLI: `apiome import auto --bulk <archive|dir>`. Complements MFI-28.5 (bulk actions on existing
  items).
- **Acceptance Criteria.** A mixed archive (proto tree + 2 AsyncAPI docs + 1 OpenAPI) yields 4
  correctly-routed items + a summary; partial failure doesn't abort the batch.
- **Dependencies / Parallelism.** After 29.1/29.2, 1.5. Parallel with 29.3/29.4.
- **Technical Stack.** Python async, FastAPI, Next.js, Typer.

### MFI-29.6 — Secret scrubbing on intake  ·  **#4393**
- **Problem.** Uploaded payloads can embed live credentials (server URLs with basic-auth,
  API keys in examples/extensions). This becomes **mandatory** the moment EPIC-32 lands —
  Postman/Insomnia/HAR files routinely carry bearer tokens and cookies.
- **Solution / Scope.** A scrubbing pass on intake, before persistence of source material
  (23.9 stores it): pattern + entropy detection (authorization headers, `api_key`/token fields,
  basic-auth URLs, cookie jars), redact-in-place with `«redacted»` markers, and record a
  scrub report (what/where, not the values) on the import job summary. Configurable per tenant
  (warn-only vs enforce); **enforce is the default for EPIC-32 formats** (32.5 gates on this).
- **Acceptance Criteria.** A fixture with embedded tokens persists only redacted content; the job
  summary lists redactions; scrubbing never alters fingerprint-relevant structure (values only);
  warn-only mode surfaces findings without modifying content.
- **Dependencies / Parallelism.** After 1.2. Blocks 32.x ship; parallel with everything else here.
- **Technical Stack.** Python.

---

## MFI-EPIC-30 — OpenAPI-Family Adapter Completeness (Swagger 2.0 · Arazzo · OpenAPI 3.2)  ·  **#4385**

MVP-cleanup epic. Three formats are advertised as first-class today but bypass or break the
canonical pipeline: **Swagger 2.0** is detected as importable and is in `PUBLISHABLE_FORMATS`,
but `normalize()` raises `ImportSourceError` (MFI-1.1 explicitly deferred its normalizer — no
epic owned it until now); **Arazzo** routes to Projects via the legacy worker with no
`ImportSource` adapter, so it gets no canonical model, cross-format diff, or conversion support;
**OpenAPI 3.2** (QUERY method, streaming media types, tag hierarchy) is unacknowledged across
detection, publishability, and the EPIC-22 emitter.

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 30.4 | OpenAPI-family conformance fixtures | 2.0/3.0/3.1/3.2 + Arazzo round-trip matrix (import→canonical→emit) | rest,validation | Y | Y | S | apiome-rest |

### MFI-30.1 — Swagger 2.0 canonical normalizer  ·  **#4394**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/swagger2_normalizer.py` (`Swagger2Normalizer`, registered under `swagger-2.0`) and wired into `openapi_import_source.py` so the OpenAPI/Swagger adapter's `normalize()` path no longer raises for Swagger 2.0. Maps `host`/`basePath`/`schemes`→servers, `definitions`→types (via `SchemaCoercer` with `#/definitions/` refs), Swagger parameter forms (`body`/`formData`)→request messages, and `produces`/`consumes`→media types on messages — matching OpenAPI 3.x fingerprint semantics for the same contract. Tests in `tests/test_swagger2_normalizer.py`; `test_openapi_import_source.py` updated. apiome-rest 1.75.2 → 1.75.3.
- **Problem.** MFI-1.1's detection recognizes Swagger 2.0 and the routing policy publishes it, but
  the SPI path raises — so Swagger 2.0 rides the legacy worker only and never enters the canonical
  model (no cross-format diff, no conversion fidelity, no format packs).
- **Solution / Scope.** A `Swagger2Normalizer` registered beside `OpenApiNormalizer`: map
  `basePath`/`host`/`schemes`→servers, `definitions`→types, parameter forms (`body`/`formData`)
  →messages, `produces`/`consumes`→media types. Keep the worker path for project decomposition;
  the adapter path feeds canonical persistence so both stay consistent (same fingerprint
  semantics as 3.x).
- **Acceptance Criteria.** A Swagger 2.0 fixture normalizes without error; diffing it against its
  own 3.0 conversion shows only expected structural changes; `detect` and `normalize` verdicts
  agree for every fixture.
- **Dependencies / Parallelism.** After 2.3. Parallel with 30.2/30.3.
- **Technical Stack.** Python.

### MFI-30.2 — Arazzo ImportSource adapter  ·  **#4395**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest/src/app/arazzo_import_source.py` (`ArazzoImportSource`, registered under `arazzo`), `arazzo_normalizer.py` (workflows→services/steps→operations, `sourceDescriptions` in root `extras`), `arazzo_lint.py` (dangling `operationId`, unused inputs, missing success criteria), and `arazzo_breaking_change.py` (step reorder graded via MFI-3.3). Tests in `tests/test_arazzo_import_source.py`. Auto-detection now reports Arazzo as `importable: true`. apiome-rest 1.75.3 → 1.75.4.
- **Problem.** Arazzo (workflows) is sniffed by `format_detection` and routed to Projects, but has
  no adapter — it is invisible to the canonical model, lint packs, and compare-any-two diff.
- **Solution / Scope.** An `ArazzoImportSource`: parse (JSON/YAML), normalize workflows/steps →
  canonical services/operations (steps reference source-description operations; keep
  `sourceDescriptions` links in `extras`/`format_metadata`), lint pack (unresolvable operation
  refs, unused inputs, missing success criteria), diff (step add/remove/reorder classified via
  3.3). Routing stays Projects-bound (publishable) per the §0.2 policy.
- **Acceptance Criteria.** An Arazzo fixture imports through the SPI with canonical entities;
  lint flags a dangling `operationId` ref; two workflow versions diff step-level.
- **Dependencies / Parallelism.** After 1.1/2.3. Parallel with 30.1.
- **Technical Stack.** Python.

### MFI-30.3 — OpenAPI 3.2 support  ·  **#4396**  ·  ✅ **Done**
- **Status.** Implemented in `apiome-rest`: `openapi-3.2` detection/format key, `OpenApiNormalizer` handles QUERY/additionalOperations/tag hierarchy, `PUBLISHABLE_FORMATS` routing, bundled 3.2 meta-schema (`data/openapi_3_2_meta_schema.json`), emitter stashes non-3.1 methods on `x-apiome-*` extensions, and fidelity preview notes 3.2→3.1 conversion. UI catalog format registry adds `openapi32` alias. Tests in `tests/test_openapi_32.py`. apiome-rest 1.75.4 → 1.75.5; apiome-ui 0.49.1 → 0.49.2.
- **Problem.** OAS 3.2.0 shipped (Q4 2025): `QUERY` method, `additionalOperations`, streaming
  media-type guidance, hierarchical tags, `$self`. Detection pins 3.0/3.1, `PUBLISHABLE_FORMATS`
  omits 3.2, and the EPIC-22 emitter/validator only know 3.1 — a current-version OpenAPI doc
  imports as "unknown" or mis-normalizes.
- **Solution / Scope.** Add `openapi-3.2` to detection + the OpenAPI adapter's `formats`;
  normalizer handles the new operation kinds (QUERY → canonical operation with method preserved;
  tag hierarchy → categorization metadata); add 3.2 to `PUBLISHABLE_FORMATS` and the routing
  policy; vendor the 3.2 meta-schema beside the 3.1 one for validation. Emitter target stays 3.1
  for now (3.2 emit is a later `--to` target for the target-generic convert verb, 22.6).
- **Acceptance Criteria.** A 3.2 doc with a QUERY operation imports, normalizes, lints, and
  publishes; 3.1 behavior unchanged; the fidelity preview correctly reports a 3.2→3.1 conversion
  note if converted.
- **Dependencies / Parallelism.** After 1.5. Parallel with 30.1/30.2.
- **Technical Stack.** Python, JSON Schema.

### MFI-30.4 — OpenAPI-family conformance fixtures  ·  **#4397**
- **Problem.** The family now spans Swagger 2.0 → OAS 3.2 + Arazzo across two pipelines (worker +
  SPI); regressions between them are currently invisible.
- **Solution / Scope.** A fixture matrix (2.0, 3.0, 3.1, 3.2, Arazzo) asserting: detect verdict =
  normalize capability; canonical entity counts; fingerprint stability; round-trip
  `normalize(emit(normalize(doc))) == normalize(doc)` where the emitter supports the version;
  routing policy (all → Projects).
- **Acceptance Criteria.** Matrix runs in CI; any detect/normalize disagreement fails loudly.
- **Dependencies / Parallelism.** After 30.1–30.3.
- **Technical Stack.** Python, pytest.

---

## MFI-EPIC-31 — Live-Source Re-Discovery & Drift Alerts · v2  ·  **#4386**

The largest structural omission the gap analysis found. GraphQL introspection, gRPC reflection,
OData `$metadata`, Schema-Registry crawl, and (future) FHIR `/metadata` are **one-shot** imports:
nothing re-polls, so the catalog silently goes stale and the breaking-change engine (3.3) — the
most valuable machinery in this roadmap — never fires on drift. The MCP catalog (this roadmap's
stated template) already has a periodic re-discovery sweep (`repository_refresh_sweep.py`), and
`ROADMAP_REPOSITORY_AUTOREFRESH.md` covers git repos; this epic is the same capability for
live-discovery import sources. Sequence with EPIC-12 — a registry crawl without re-crawl is half
a feature.

```mermaid
flowchart LR
  SCHED[per-artifact cadence\nopt-in schedule] --> SWEEP[re-discovery sweep]
  SWEEP --> DISC[adapter discover\nreflection / introspection / crawl]
  DISC --> FP{fingerprint\nchanged?}
  FP -- no --> SKIP[touch last-checked]
  FP -- yes --> VER[new version 3.4] --> CLS[breaking classifier 3.3]
  CLS --> NOTIF[UI drift badge\n+ webhook / email]
  VER --> RET[retention policy]
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 31.1 | Refresh scheduler & per-artifact cadence | opt-in re-discovery schedule for live-capable artifacts | rest,registry,database | N | N | L | apiome-rest,apiome-db |
| 31.2 | Re-discovery pipeline reuse | re-run discover→normalize→fingerprint; version-on-change via 3.4 | rest,python | N | N | M | apiome-rest |
| 31.3 | Drift & breaking-change notifications | UI badge + webhook/email when a sweep lands a breaking version | rest,ui,integrations | Y | N | M | apiome-rest,apiome-ui |
| 31.4 | Registry-crawl throttling & incremental resume | rate limits, page budgets, checkpoint/resume for registry-as-source crawls | rest,registry,security | Y | N | M | apiome-rest |
| 31.5 | Version retention & pruning policy | cap sweep-generated history; keep tagged/breaking/converted versions | database,rest | Y | N | S | apiome-rest,apiome-db |

### MFI-31.1 — Refresh scheduler & per-artifact cadence  ·  **#4398**
- **Problem.** No mechanism exists to re-check a live source; staleness is invisible.
- **Solution / Scope.** Per-artifact opt-in refresh: cadence (hourly/daily/weekly/manual-only,
  default off), stored on the artifact; a background sweep (generalize the MCP
  `repository_refresh_sweep` pattern) walks due artifacts whose adapter declares
  `supports_live_discovery`, honoring a global concurrency cap and per-host politeness delay.
  Failures back off exponentially and surface as a "last check failed" state, never as a new
  version. Credentials via the vault; every call SSRF-guarded (unchanged adapter paths).
- **Acceptance Criteria.** An artifact with daily cadence re-discovers on schedule; failure shows
  status without corrupting history; disabling stops the sweep; tenant-level kill switch.
- **Dependencies / Parallelism.** After 3.4 + ≥1 live-capable adapter (exists: gRPC/GraphQL).
  Blocks 31.2/31.3.
- **Technical Stack.** Python async, PostgreSQL, FastAPI.

### MFI-31.2 — Re-discovery pipeline reuse  ·  **#4399**
- **Problem.** A sweep hit must behave exactly like a manual re-import — same normalize,
  fingerprint, version-on-change, lint capture — with zero new pipeline code.
- **Solution / Scope.** Drive the existing adapter import pipeline (1.2) in "refresh" mode:
  discover→parse→normalize→fingerprint; `decide_version()` (3.4) CREATEs on change else SKIPs;
  lint/score captured per 4.2; diff + breaking classification (3.2/3.3) stored with the new
  version. Provenance records `trigger=sweep` vs `trigger=manual`.
- **Acceptance Criteria.** An unchanged endpoint produces no version; a changed one produces a
  version whose diff/classification matches a manual re-import byte-for-byte.
- **Dependencies / Parallelism.** After 31.1. Parallel with 31.4.
- **Technical Stack.** Python.

### MFI-31.3 — Drift & breaking-change notifications  ·  **#4400**
- **Problem.** A breaking change landing silently in version history defeats the purpose of
  watching.
- **Solution / Scope.** On a sweep-created version: catalog/project card **drift badge** (colored
  by 3.3 severity: safe/dangerous/breaking), a dismissible detail banner linking the diff, and
  outbound **webhook** (JSON payload: artifact, versions, severity, top findings) + optional
  email per tenant notification settings. Batch digest option for chatty sources.
- **Acceptance Criteria.** A breaking sweep version raises badge + webhook within one sweep cycle;
  webhook retries with backoff; safe changes badge quietly without notifying (configurable).
- **Dependencies / Parallelism.** After 31.2. Parallel with 31.5.
- **Technical Stack.** FastAPI, Next.js, httpx.

### MFI-31.4 — Registry-crawl throttling & incremental resume  ·  **#4401**
- **Problem.** §9's "registry-as-source" mode (Confluent SR, xRegistry, FHIR `/metadata`) implies
  crawling catalogs with thousands of subjects; an unthrottled or restart-from-zero crawl is
  hostile to the registry and fragile for us.
- **Solution / Scope.** Crawl budget primitives for discovery adapters: requests/sec + max-pages +
  max-bytes per crawl, checkpoint cursor persisted per source so an interrupted crawl resumes,
  and incremental mode (only subjects changed since the stored registry offset/etag where the
  registry exposes one). Applies first to EPIC-12's Confluent crawler.
- **Acceptance Criteria.** A crawl against a 10k-subject fixture respects rate/page budgets,
  resumes from checkpoint after a kill, and an incremental pass touches only changed subjects.
- **Dependencies / Parallelism.** With/after 12.3. Parallel with 31.2.
- **Technical Stack.** Python async.

### MFI-31.5 — Version retention & pruning policy  ·  **#4402**
- **Problem.** A daily sweep on a churning endpoint mints unbounded version rows.
- **Solution / Scope.** Per-artifact retention: keep-last-N sweep versions plus **always keep**
  tagged versions, breaking-change versions, and conversion-source versions
  (`conversion_provenance` referenced). Pruning is soft-delete, consistent with house style.
- **Acceptance Criteria.** History respects the policy; protected versions survive; diff endpoints
  handle pruned gaps gracefully.
- **Dependencies / Parallelism.** After 31.2.
- **Technical Stack.** PostgreSQL, Python.

---

## MFI-EPIC-32 — Collections & Captured Traffic (HAR · Insomnia · Bruno · Postman-SPI) · v2  ·  **#4387**

The roadmap covers everything *designed* (IDLs, schemas) but nothing *observed or collected* —
and those are precisely the artifacts most teams actually have. This epic imports the
collection/traffic family: **HAR** captures (browser devtools, proxies), **Insomnia** and
**Bruno** collections (import direction; the export roadmap's MFX-EPIC-31 already covers the
reverse), and refactors the legacy **Postman** importer behind the SPI. All of it feeds one
**inferred-spec engine**: requests/entries merge into inferred operations whose provenance is
`inferred` — which is exactly what the EPIC-22 fidelity machinery was built to represent, and why
these land in the **Catalog** (non-publishable) with conversion as the promotion path.
**Hard gate: 29.6 secret scrubbing ships first — these files carry live tokens.**

```mermaid
flowchart LR
  HAR[.har traffic capture] --> SCRUB[29.6 secret scrub\nENFORCED]
  INS[Insomnia export v4/v5] --> SCRUB
  BRU[Bruno .bru folder] --> SCRUB
  PM[Postman collection] --> SCRUB
  SCRUB --> INF[inferred-spec engine\nmerge → operations + schemas]
  INF --> CAN[canonical model\nprovenance = inferred]
  CAN --> CAT[Catalog item\nformat pill + fidelity]
  CAT --> CONV[EPIC-22 convert\n→ OpenAPI project]
```

| ID | Title | Summary | Labels | Parallel | MVP | Complexity | Affected Modules |
|----|-------|---------|--------|----------|-----|-----------|------------------|
| 32.1 | Inferred-spec engine (observations → canonical) | merge requests/entries into inferred operations + JSON-Schema shapes | rest,python,import | N | N | L | apiome-rest |
| 32.2 | HAR adapter | `.har` (browser/proxy) → inferred canonical REST model | import,rest,python | Y | N | M | apiome-rest |
| 32.3 | Insomnia collection adapter | Insomnia v4/v5 export (JSON/YAML) incl. environments | import,rest,python | Y | N | M | apiome-rest |
| 32.4 | Bruno collection adapter | `.bru` folder / `bruno.json` (git-native; pairs with 29.3) | import,rest,python | Y | N | M | apiome-rest |
| 32.5 | Secret scrubbing & environment mapping (gate) | 29.6 enforced ON; env vars → server variables, auth → securityScheme stubs | security,import | N | N | M | apiome-rest |
| 32.6 | Source cards + CLI + fixtures | cards + `apiome import har\|insomnia\|bruno` + fixtures | ui,devex,python | Y | N | S | apiome-rest,apiome-ui,apiome-cli |
| 32.7 | Postman importer behind the SPI | refactor the legacy Postman path into an ImportSource sharing 32.1 | import,rest,python | Y | N | M | apiome-rest |

### MFI-32.1 — Inferred-spec engine (observations → canonical)  ·  **#4403**
- **Problem.** Collections and captures are *lists of concrete requests*, not specs: the same
  endpoint appears many times with different ids/params/bodies. Naive 1:1 mapping produces
  garbage paths (`/users/123`, `/users/456` as separate operations).
- **Solution / Scope.** A shared inference layer (the proven traffic→spec approach: Optic/Akita/
  Postman-style): cluster requests by host+method+tokenized path (numeric/UUID/hash segments →
  `{param}`), union observed query/header params (required = seen in all samples), derive
  JSON-Schema from observed bodies/responses (type widening across samples), keep per-operation
  sample counts as confidence. Everything lands in the canonical model with **provenance =
  `inferred`** (the EPIC-22 primitive), so fidelity reports and the Catalog's non-publishable
  stance tell the truth automatically.
- **Acceptance Criteria.** A 500-entry HAR of a CRUD API infers the parameterized paths (not one
  op per URL); response schemas widen correctly across samples; every inferred construct carries
  `inferred` provenance and a sample count; deterministic for a fixed input.
- **Dependencies / Parallelism.** After 2.3, 22.1 (provenance primitives). Blocks 32.2–32.4/32.7.
- **Technical Stack.** Python.

### MFI-32.2 — HAR adapter  ·  **#4404**
- **Problem.** "Record in devtools/proxy, import the traffic" is the fastest onboarding path a
  cataloging product can offer, and it is entirely missing.
- **Solution / Scope.** `HarImportSource`: parse HAR 1.2 (`log.entries`), filter non-API noise
  (static assets, analytics — content-type + heuristic filters, user-tunable), feed entries to
  32.1, one artifact per host (or user-selected hosts on multi-host captures). Scrubbing (32.5)
  strips cookies/auth headers before anything persists. Detection: `{"log":{"version":"1.2"`.
- **Acceptance Criteria.** A devtools HAR of a REST app imports as a Catalog item with inferred
  operations + schemas; assets are excluded; no header/cookie secret survives to storage; format
  pill shows `HAR (inferred)`.
- **Dependencies / Parallelism.** After 32.1/32.5. Parallel with 32.3/32.4.
- **Technical Stack.** Python.

### MFI-32.3 — Insomnia collection adapter  ·  **#4405**
- **Problem.** Insomnia workspaces describe real APIs (requests, folders, environments) but only
  the *export* direction exists (MFX-EPIC-31); users switching to or cataloging alongside
  Insomnia cannot bring them in.
- **Solution / Scope.** `InsomniaImportSource`: parse v4 JSON / v5 YAML exports, folders→tags,
  requests→32.1 (single-sample operations; bodies as declared), environment variables→server
  variables/parameter defaults via 32.5's mapping (never resolve secret values). Detection:
  `_type: export` / `insomnia.rest` markers.
- **Acceptance Criteria.** A v5 export imports with folder structure as tags and env-var-templated
  URLs mapped to server variables; secrets redacted; round-trip with MFX-EPIC-31 export is
  structurally stable.
- **Dependencies / Parallelism.** After 32.1/32.5. Parallel with 32.2/32.4.
- **Technical Stack.** Python, YAML.

### MFI-32.4 — Bruno collection adapter  ·  **#4406**
- **Problem.** Bruno's git-native `.bru` folders are rapidly displacing Postman in dev teams;
  export exists (MFX-EPIC-31.3), import does not.
- **Solution / Scope.** `BrunoImportSource`: parse `bruno.json` + `.bru` files (their `meta`/
  `get`/`post`/`body`/`vars` block grammar), folder tree→tags, environments→32.5 mapping. Natural
  fileset/git citizen: arrives via 29.1 archive or 29.3 git intake.
- **Acceptance Criteria.** A Bruno repo imports via archive and via git intake with identical
  fingerprints; `.bru` grammar edge cases (multipart, scripts blocks ignored-with-note) handled.
- **Dependencies / Parallelism.** After 32.1/32.5, 29.2. Parallel with 32.2/32.3.
- **Technical Stack.** Python.

### MFI-32.5 — Secret scrubbing & environment mapping (gate)  ·  **#4407**
- **Problem.** Collections/captures are the highest-risk payloads this roadmap will ever ingest:
  cookies, bearer tokens, API keys in env files. A single leak into stored source material
  (23.9) is an incident.
- **Solution / Scope.** Turn 29.6 **on and unskippable** for every EPIC-32 format; add the
  family-specific mappings: environment *names* become OpenAPI server variables / parameter
  placeholders while their *values* are redacted; declared auth (Postman/Insomnia auth blocks,
  observed `Authorization` headers) becomes `securityScheme` **stubs** (type only, no material).
  Scrub report attached to the import job and the catalog item's provenance panel.
- **Acceptance Criteria.** Fixtures seeded with tokens/cookies/env secrets persist zero secret
  bytes (verified by scanning stored source); auth appears as scheme stubs; scrub report lists
  every redaction site.
- **Dependencies / Parallelism.** After 29.6. Blocks 32.2–32.4/32.6 ship.
- **Technical Stack.** Python.

### MFI-32.6 — Source cards + CLI + fixtures  ·  **#4408**
- **Problem.** Standard adapter surfacing, per the template every format epic ends with.
- **Solution / Scope.** Source cards (HAR: activity icon; Insomnia/Bruno: their marks are
  trademarked — use neutral Lucide icons), file/archive input kinds; `apiome import har|insomnia|
  bruno`; `detect()` entries; fixtures per format incl. a secrets-seeded scrub fixture. Catalog
  format pills read `HAR (inferred)` / `Insomnia` / `Bruno`.
- **Acceptance Criteria.** Cards appear via the registry with no UI code change (1.3); CLI
  dispatch works via 1.4 with no new command code; fixtures green in CI.
- **Dependencies / Parallelism.** After 32.2–32.4. Parallel across formats.
- **Technical Stack.** Python, Next.js, Typer.

### MFI-32.7 — Postman importer behind the SPI  ·  **#4409**
- **Problem.** Postman import predates the SPI (legacy path), so Postman collections get no
  canonical model, no cross-format diff, no conversion fidelity — while newer, less-used formats
  do.
- **Solution / Scope.** `PostmanImportSource` (Collection v2.1): reuse 32.1 for request→operation
  inference and 32.5 for env/auth handling; keep the legacy path until parity, then route the
  source card through the adapter (same behavior-preserving pattern as MFI-1.1's OpenAPI
  refactor).
- **Acceptance Criteria.** A Postman collection imports through the SPI with canonical entities
  and identical user-visible results to the legacy path; legacy path retired behind a flag.
- **Dependencies / Parallelism.** After 32.1/32.5. Parallel with 32.2–32.4.
- **Technical Stack.** Python.

---

## 5. Work order (dependency-driven)

```mermaid
flowchart LR
  E1[1 Source Framework] --> E2[2 Canonical Model]
  E1 --> E5[5 Toolchain Runner]
  E2 --> E7[7 DB]
  E2 --> E3[3 Versioning/Diff]
  E2 --> E4[4 Lint Engine]
  E5 --> E3 & E4
  E3 & E4 & E5 & E7 --> F[Format epics 8-17]
  F --> E6[6 Browse/Search]
  E2 & E3 & E4 --> E22[22 Catalog→OpenAPI Conversion]
  F --> E22
  E1 & E2 & E7 --> E23[23 Catalog Screen]
  E22 --> E23
```

**Build order:**

1. **Foundation first:** MFI-1.1 → 1.2 (SPI + generalized engine) ‖ MFI-5.1 (runner) ‖ MFI-2.1 → 2.2/2.3 (model + persistence) ‖ MFI-7.1.
2. **Cross-cutting:** MFI-3.1 → 3.2 → 3.3 (fingerprint/diff/breaking SPI) ‖ MFI-4.1 → 4.2/4.3 (lint engine) ‖ MFI-5.2/5.3 (tool packaging + sandbox) ‖ MFI-1.3/1.4/1.5 (UI/CLI/auto-detect).
3. **MVP formats (prove the seam):** MFI-EPIC-8 AsyncAPI, MFI-EPIC-10 GraphQL, MFI-EPIC-9 gRPC — each: parse → normalize → discover (9/10) → lint → breaking → UI/CLI.
4. **MVP-hardening (2026-07 additions, before v2 formats):** **MFI-EPIC-30** (Swagger 2.0 /
   Arazzo / OAS 3.2 completeness) ‖ **MFI-29.1 → 29.2** (archive + fileset intake — unblocks
   real-world proto/SDL/AsyncAPI inputs for the already-shipped MVP formats) ‖ **22.7**
   (passthrough, now MVP) ‖ UI **26.4** dry-run (in `ROADMAP_MULTI_FORMAT_IMPORT_UI.md`).
5. **MVP ships.** Then v2 formats by value: **OData → Avro/Schema-Registry →
   Collections & Captured Traffic (MFI-EPIC-32, gated on 29.6 scrubbing) → SOAP/WSDL →
   TypeSpec**, then legacy **RAML → API Blueprint**, then **Smithy**.
6. **Browse/Search (MFI-EPIC-6)** lands once ≥3 formats populate the model (align with
   #3489/#3496); **6.4 cross-format identity** rides with it (conversion-provenance auto-links
   arrive free from 22.5).
7. **Live-source re-discovery (MFI-EPIC-31)** is sequenced with **EPIC-12**: 31.1 scheduler →
   31.2 pipeline reuse → 31.3 notifications, with 31.4 crawl-throttling built alongside 12.3's
   Confluent crawler and 31.5 retention after the first sweeps run. (gRPC/GraphQL artifacts can
   opt in as soon as 31.1/31.2 exist — the adapters already support live discovery.)
8. **Intake scale-out:** 29.3 git intake + 29.4 remote `$refs` + 29.5 bulk import land with the
   first v2 format wave; **29.6 secret scrubbing must land before MFI-EPIC-32 starts** (32.5
   enforces it).
9. **Catalog → OpenAPI conversion (MFI-EPIC-22)** can start as soon as the canonical model +
   versioning + lint (EPIC-2/3/4) exist — its conv-MVP (22.1 emitter → 22.2 projections → 22.3 gap
   analyzer → 22.5 convert job → 22.6 API → 22.4 preview) is independent of which format epics have
   shipped. Per-format packs (22.8) light up incrementally as each format's normalizer lands;
   ship 22.7 passthrough first so OpenAPI/Swagger/TypeSpec sources are handled losslessly from day one.
10. **Catalog screen (MFI-EPIC-23)** needs only the model/persistence (EPIC-2/7) + import framework
   (EPIC-1) to start. Build the catalog-MVP as: 23.1 entity + 23.2 API → 23.7 import routing →
   23.3/23.4/23.5/23.6 screen+card+pills+nav → 23.8 non-publishable enforcement → 23.9/23.10
   detail+lint parity. **23.11 promotion** lands once EPIC-22's preview (22.4) exists — it is the
   bridge between the two epics. **23.12 read-only Designer** is later/non-MVP. The catalog fills up
   incrementally as each format epic (8–17) ships its normalizer.

---

## 6. Cross-cutting risks & decisions

1. **Polyglot toolchain is the critical path.** Authoritative tooling for AsyncAPI/gRPC/RAML/
   Smithy/TypeSpec/API-Blueprint is JS/JVM/native. MFI-EPIC-5 (runner + packaging + sandbox) gates
   most format epics — build it early and treat tool packaging as a real ops cost.
2. **Normalize-before-hash is universal.** Never hash raw bytes — hash the resolved/dereferenced
   canonical model with stable keys (Schema Coordinates, protobuf field numbers, XSD QNames, Avro PCF).
3. **Two ingestion pipelines.** Live discovery (gRPC reflection, GraphQL introspection, OData
   `$metadata`, Schema-Registry crawl) vs file/build-time (AsyncAPI, WSDL fetch, TypeSpec/RAML/
   Smithy/API-Blueprint compile/resolve). The SPI must express both.
4. **Compatibility maturity varies.** Buy/wrap where tools exist (Buf, GraphQL-Inspector,
   `@asyncapi/diff`, `smithy diff`, Confluent compat, OData §5.2); build rulesets only for RAML &
   API Blueprint.
5. **Lifecycle reality:** Avro/Confluent, Smithy, gRPC, GraphQL, AsyncAPI, OData, TypeSpec are
   active; **RAML is dormant (use AMF), API Blueprint is archived (import + migrate to OpenAPI).**
   Set expectations accordingly.
6. **Don't duplicate existing issues.** Position as the *cataloging/versioning engine* feeding/
   consuming the existing importer/editor epics (#1438, #1331, #1384, #3489, #3496, REPO-3.x); link them.
7. **Security:** running third-party CLIs on user input + live network discovery = SSRF/code-exec
   surface; MFI-5.3 (no-network default, FS/CPU/mem/time caps) and credential vault reuse are mandatory.
8. **Conversion is lossy — never hide it (MFI-EPIC-22).** OpenAPI cannot faithfully represent every
   paradigm: event pub/sub, GraphQL subscriptions, and gRPC streaming have no clean OAS equivalent,
   and most sources lack the HTTP status codes / media types / servers / security that a *complete*
   OpenAPI doc wants. The fidelity-gap analyzer (22.3) + the mandatory preview warning (22.4) exist
   precisely so users convert with eyes open. Fidelity tier is per-source: OData is near-lossless
   (OASIS standard), Smithy/gRPC are medium (official but lossy converters), AsyncAPI is low. Always
   wrap the authoritative converter where one exists rather than re-deriving the mapping (22.8), and
   keep provenance so a converted spec can be edited up to full fidelity in the ADE.
9. **Catalog vs Project is a hard boundary (MFI-EPIC-23).** Non-OpenAPI imports are *cataloged*, not
   *published* — they may be incomplete, so `publishable=false` is enforced at the data + REST layer,
   not just hidden in the UI (23.1/23.8). The Catalog screen mirrors the Projects dashboard for
   parity (view/lint/format-pill/source) but never offers publish; the *only* path to a publishable
   artifact is MFI-EPIC-22 conversion (23.11). This keeps "incomplete imports" from leaking into the
   public/published surface while still making them first-class, inspectable catalog citizens.
10. **A live-discovered catalog decays without re-discovery (MFI-EPIC-31).** One-shot imports of
    living endpoints (introspection/reflection/registry crawls) go stale silently, and the
    breaking-change engine never fires on drift. Re-discovery must reuse the exact import pipeline
    (a sweep version = a manual re-import version), be opt-in with backoff and per-host politeness,
    and never turn a fetch failure into a phantom version. Retention (31.5) caps sweep churn.
11. **Collections & captures carry live secrets and only *inferred* truth (MFI-EPIC-32).**
    Postman/Insomnia/HAR payloads routinely embed bearer tokens, cookies, and env secrets —
    scrubbing (29.6/32.5) is a ship-gate, not a lint. And an inferred spec is a *sample* of an API,
    not its contract: keep `inferred` provenance on every construct, keep these items
    non-publishable (EPIC-23), and let EPIC-22's fidelity preview tell the truth at promotion time.

---

## 7. Sources

- AsyncAPI 3.1 spec · `@asyncapi/parser` · `@asyncapi/diff` — https://www.asyncapi.com/docs/reference/specification/v3.1.0 · https://github.com/asyncapi/parser-js · https://github.com/asyncapi/diff
- Protobuf Editions · gRPC Server Reflection · Buf lint/breaking — https://protobuf.dev/editions/overview/ · https://grpc.io/docs/guides/reflection/ · https://buf.build/docs/breaking/rules/
- GraphQL spec (Sept 2025) · introspection · GraphQL-Inspector — https://spec.graphql.org/September2025/ · https://graphql.org/learn/introspection/ · https://github.com/graphql-hive/graphql-inspector
- WSDL/SOAP/XSD — https://www.w3.org/TR/wsdl · https://www.w3.org/TR/soap/ · https://www.w3.org/TR/xmlschema11-1/
- TypeSpec · versioning — https://typespec.io · https://typespec.io/docs/libraries/versioning/guide/
- OData CSDL 4.01 — https://docs.oasis-open.org/odata/odata-csdl-json/v4.01/odata-csdl-json-v4.01.html
- RAML 1.0 · AMF — https://github.com/raml-org/raml-spec · https://github.com/aml-org/amf
- API Blueprint · drafter — https://github.com/apiaryio/api-blueprint
- Avro 1.12 · Confluent Schema Registry API — https://avro.apache.org/docs/1.12.0/specification/ · https://docs.confluent.io/platform/current/schema-registry/develop/api.html
- Smithy 2.0 · evolving models · linters — https://smithy.io/2.0/spec/ · https://smithy.io/2.0/guides/evolving-models.html · https://smithy.io/2.0/guides/model-linters.html
- Spectral — https://github.com/stoplightio/spectral
- **Catalog → OpenAPI conversion (MFI-EPIC-22):**
  - OData → OpenAPI (OASIS mapping v1.0 + Microsoft.OpenApi.OData) — https://docs.oasis-open.org/odata/odata-openapi/v1.0/cn01/odata-openapi-v1.0-cn01.html · https://github.com/microsoft/OpenAPI.NET.OData · https://oasis-tcs.github.io/odata-openapi/lib/
  - Smithy → OpenAPI (built-in, documented as lossy) — https://smithy.io/2.0/guides/model-translations/converting-to-openapi.html
  - gRPC/Protobuf → OpenAPI — https://github.com/google/gnostic · https://grpc-ecosystem.github.io/grpc-gateway/docs/mapping/customizing_openapi_output/ · https://github.com/sudorandom/protoc-gen-connect-openapi
  - GraphQL → REST/OpenAPI (SOFA) — https://github.com/Urigo/sofa · https://github.com/schwer/graphql-to-openapi
  - OpenAPI 3.1 = JSON Schema (schema reuse for `components`) — https://spec.openapis.org/oas/v3.1.0
- **Gap-analysis additions (EPIC-29…32, §9.7):**
  - HAR 1.2 — http://www.softwareishard.com/blog/har-12-spec/ · traffic→spec prior art: https://github.com/opticdev/optic
  - Insomnia export format — https://docs.insomnia.rest/insomnia/import-export-data · Bruno `.bru` — https://docs.usebruno.com/bru-lang/overview
  - Postman Collection v2.1 — https://schema.postman.com/collection/json/v2.1.0/draft-07/docs/index.html
  - Google API Discovery — https://developers.google.com/discovery/v1/reference
  - OpenAPI 3.2.0 — https://spec.openapis.org/oas/v3.2.0 · Overlay Specification 1.0 — https://spec.openapis.org/overlay/v1.0.0
  - GraphQL Federation / supergraph (rover already bundled per MFI-5.2) — https://www.apollographql.com/docs/rover/
  - Kubernetes CRDs (structural schemas) — https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/ · Gateway API — https://gateway-api.sigs.k8s.io/
  - WIT (WebAssembly Component Model) — https://component-model.bytecodealliance.org/design/wit.html
- Reused in-repo: `ROADMAP_MCP_CATALOGING.md` (V2-MCP-EPIC-15…27, #3637), `spec_import_engine.py`, `schema_lint.py`, `versions`/`version_tags`/`quality_*`, `browse_public_routes.py`, `ImportDialog.tsx`, `DashboardSideNav.tsx`, apiome-cli, apiome-db Flyway, `repository_refresh_sweep.py` (EPIC-31 template), `ROADMAP_REPOSITORY_AUTOREFRESH.md`, `ROADMAP_MULTI_FORMAT_EXPORT.md` (MFX-EPIC-25/29/31/33/34 — export counterparts of §9/EPIC-32 formats).

---

## 8. Related existing issues to reconcile (link, don't duplicate)

- #1438 [Epic] AsyncAPI & Event-Driven Architecture · #2772 REPO-3.3 AsyncAPI importer · #1447
- #1331 [Epic] GraphQL Schema Design & Tooling · #2775 REPO-3.6 GraphQL SDL importer · #1342/#1365/#1462
- #1384 [Epic] gRPC & Protocol Buffer Support · #1409 · #1427 (breaking-change overlap) · #1400
- #239 Import from Avro · #2776 REPO-3.7 Protobuf/Avro importer
- #3489 [Epic] Schema Registry & Discovery · #3496 [Epic] Community & Schema Browser · #624
- #237 Import from RAML (closed)
- MCP catalog umbrella **#3637** (V2-MCP-EPIC-15…27) — the pattern this roadmap generalizes.

---

## 9. Further import candidates (2026 research)

> **Status:** ✅ **Issues filed** on `objectified-project/objectified` — **4 epics #3970–#3973**
> (MFI-EPIC-18…21) + **23 candidate issues #3974–#3996**, all under umbrella **#3715**, labelled
> `roadmap-candidate` (post-MVP). These are formats discovered while scanning what companies are
> actually adopting in 2026, plus long-lived legacy/mainframe formats with large installed bases.
> They are documented here so the **plug-in seam (MFI-EPIC-1/2)** is designed wide enough to absorb
> them; the Tier-1 set (**A2A Agent Cards #3974**, **OpenRPC #3979**, **CloudEvents/xRegistry
> #3980**, **FHIR #3985**) is flagged to promote first. See **§9.6** for the full issue map, and
> **§9.7** for the 2026-07 gap-analysis candidates (documented only, **not yet filed**).
>
> Every candidate below is scored against the SAME pipeline the rest of this roadmap uses
> (*parse → normalize → fingerprint → diff → lint/score → catalog/browse*) and reuses MFI-EPIC-1…7.

### 9.0 Headline: the "alternative to MCP" — catalog **agent** descriptors, not just API specs

The agent-interoperability stack converged hard in Q1 2026. MCP (already imported here) won
*agent → tool*; the **complementary** layer that won *agent → agent* is **A2A (Agent2Agent)** —
created by Google, donated to the **Linux Foundation** (now under the Agentic AI Foundation
alongside MCP), 150+ supporting orgs, production enterprise adoption by 2026. **This is the
"alternative to MCP" worth cataloging first**, for one decisive reason:

- An A2A agent advertises itself with an **Agent Card** — a JSON capability descriptor served at
  `/.well-known/agent-card.json` (a.k.a. `agent.json`) carrying `name`, `description`, `url`,
  `provider`, `version`, `capabilities`, `securitySchemes`, and a list of **skills** (id / name /
  description / tags / input-output modes). It is structurally a near-twin of an MCP server
  descriptor — **directly** ingestible by the MCP catalog machinery (V2-MCP-EPIC-15…27) we
  already built.
- **A2A deliberately has no standard registry/discovery API yet** (the spec calls it "an area of
  potential future exploration"). That is an open lane: **apiome can be the Agent-Card
  catalog** — fetch via well-known URI, fingerprint, version, diff skills across releases,
  lint for capability/auth hygiene, and browse/search by skill & tag. Same play that made the
  MCP catalog valuable, on the fastest-growing descriptor format of 2026.

The broader **agentic-web** family clusters around this and is worth cataloging as a group
(most are tiny JSON/markdown manifests — cheap adapters, high discovery value):

| Candidate | What it is | Discovery | Why catalog it | Fit |
|---|---|---|---|---|
| **A2A Agent Card** | Agent capability/skills descriptor (JSON) | `/.well-known/agent-card.json` (live) | The MCP-complement everyone is shipping; no canonical registry exists → be it | ●●● **top pick** |
| **ACP (Agent Communication Protocol)** | IBM/AGNTCY REST-native agent protocol; MIME multipart, sync+async | HTTP endpoint manifest | REST-native A2A alternative under LF; same Agent-Card-style metadata | ●● |
| **ANP (Agent Network Protocol)** | Decentralized agent discovery across open networks | DID/JSON identity docs | Captures the decentralized end of the spectrum | ● |
| **agents.json / agent.json / agents.txt** | Site-level "what agent protocols & capabilities this site speaks" manifest (the robots.txt of the agentic web) | site root / `.well-known` | One file enumerates A2A/MCP/AP2/x402 endpoints → a natural crawl seed feeding all the above | ●● |
| **llms.txt** | Markdown content/capability manifest for LLMs | site root | Trivial parse; pairs with agents.json for site-level cataloging | ● |
| **AP2 / x402** | Agent **payment** mandates & HTTP-402 monetized endpoints | headers / manifest | Mostly out of scope (payments), but flag as endpoint metadata if seen | ○ note-only |

**Recommendation:** add an **"Agent descriptors" paradigm** to the canonical model (EPIC-2) —
agents have *skills/capabilities/auth* rather than *operations/types* — and a single
**Agent-Card adapter (A2A first, ACP second)** that reuses the MCP catalog wholesale. This is the
highest strategic-value addition in this appendix.

### 9.1 Modern API/RPC description formats companies are adopting

| Candidate | What it is | What it brings | Reuse / discovery | Fit |
|---|---|---|---|---|
| **OpenRPC** | OpenAPI-equivalent for **JSON-RPC 2.0** (methods, params, result, components) — pure JSON | De-facto standard across **blockchain/web3** (Ethereum Foundation, MetaMask, Chainlink, Filecoin, Starknet, Celestia). JSON → trivial parse, clean diff/lint, `service_discovery` via `rpc.discover` live method | Maps to RPC paradigm (like gRPC). Reuse Smithy/gRPC normalizer; live `rpc.discover` mirrors gRPC reflection | ●●● strong |
| **CloudEvents + xRegistry** | CNCF **graduated** event envelope + **xRegistry** universal catalog (schema + message-definitions + endpoint registries; spans JSON-Schema/Avro/Protobuf over MQTT/AMQP/Kafka/NATS/HTTP) | xRegistry is *itself a catalog standard with a symmetric REST API + document model* — apiome can both **import from** and **expose as** xRegistry. Complements AsyncAPI for the event paradigm | Feeds AsyncAPI epic (EPIC-8) + Avro/Schema-Registry epic (EPIC-12); live crawl like Confluent SR | ●●● strong |
| **Apache Thrift** | Cross-language IDL + RPC (`.thrift`); heavy use at Meta and large back-ends | Net-new **RPC** coverage beside gRPC; struct/service/exception model normalizes cleanly; field-id-based diff like protobuf | Reuse gRPC/Protobuf normalizer & breaking-change rules (field numbers) | ●● |
| **Connect / Connect-RPC (Buf)** | gRPC + REST/JSON from one protobuf definition | Mostly **already covered** by gRPC/Protobuf (EPIC-9) — add as a Buf-toolchain *flavor*, not a new epic | Extension of EPIC-9 + MFI-EPIC-5 (buf runner already planned) | ○ fold-in |
| **FlatBuffers** (`.fbs`) / **Cap'n Proto** (`.capnp`) | Zero-copy binary IDLs (games, low-latency, embedded) | Net-new **data-schema/RPC**; table/struct/union schema + Cap'n Proto interfaces; evolution rules (reserved fields/ids) diffable | Reuse protobuf-style normalizer + breaking-change engine | ● |
| **JSON:API / HAL / JSON-LD+Hydra** | REST hypermedia conventions/media-types | Convention-level (less a hard schema) — value is **tagging/normalizing** existing REST artifacts that declare these media types; lint for spec conformance | Light adapter over existing OpenAPI model; browse facet | ○ low |
| **JSON Type Definition (JTD, RFC 8927)** | Compact alternative to JSON Schema | Pairs with existing JSON-Schema import + Type Registry governance work | Reuse JSON-Schema normalizer | ○ low |

### 9.2 Vertical-standard formats (healthcare & finance) — large, mandated, sticky

These carry the biggest *non-tech* installed bases and are increasingly **mandated**, which makes
cataloging/versioning/diff genuinely valuable (compliance, migration tracking).

| Candidate | Domain | What it brings | Catalogable artifact | Fit |
|---|---|---|---|---|
| **FHIR (HL7 R4/R5/R6)** | Healthcare | RESTful healthcare API standard, very active 2026 (Caliper accelerator, US Cures-Act mandates). Resources are JSON/XML with **StructureDefinition** profiles + **CapabilityStatement** describing a server's API | StructureDefinitions (types), CapabilityStatement (operations) → maps cleanly to canonical model; live `/metadata` discovery | ●●● strong vertical |
| **HL7 v2** | Healthcare | Still the **most-used** clinical messaging standard (pipe-delimited segments) | Message/segment schemas → legacy import + migrate-to-FHIR path (like RAML→OpenAPI) | ●● |
| **ISO 20022** | Finance/payments | SWIFT cross-border **cutover** in progress; richer XSD-based message schemas; AML/compliance value | XSD message definitions → reuse WSDL/XSD epic (EPIC-13) normalizer | ●● |
| **FIX / FIX Orchestra** | Capital markets | Trading-message standard; **FIX Orchestra** is the machine-readable (XML) spec of a venue's FIX dialect | Orchestra file → normalize messages/fields; diff venue dialects across versions | ●● |
| **EDI: X12 / EDIFACT (+ Peppol/UBL)** | B2B supply chain | $41B+ market, still core; modernization = EDI↔JSON/API hybrids; **Peppol e-invoicing mandated** (BE 2026, FR/PL 2026, DE/ES 2027, EU ViDA 2030) | Transaction sets / message types as schemas; huge catalog/versioning value for trading-partner maps | ●● |
| **ISO 8583** | Card payments | ATM/POS card-transaction messaging; positional/bitmap | Message/bitmap schema → legacy data-schema import | ○ niche |

### 9.3 Legacy / mainframe / middleware formats (large installed base, modernization-driven)

Mainframe modernization is a live 2026 theme (z/OS Connect, AI-assisted COBOL analysis). The
catalog value is **mapping legacy contracts to a normalized model and diffing them as they migrate**.

| Candidate | What it is | What it brings | Path | Fit |
|---|---|---|---|---|
| **COBOL copybooks** | Mainframe record/data-layout definitions (`PIC`, `OCCURS`, `REDEFINES`; EBCDIC) | Copybook→JSON-Schema is a central modernization need (Precisely, OpenLegacy, Google MAT all do it). Big installed base; pairs with z/OS Connect REST exposure | Parse copybook → canonical **types**; diff layouts across versions; lint for ambiguous redefines | ●● legacy-strong |
| **z/OS Connect / CICS-IMS API requester** | Mainframe-as-REST layer | Often emits OpenAPI (partly covered) — value is cataloging the **copybook↔API binding** | Feed OpenAPI epic + copybook adapter | ○ fold-in |
| **WADL** | XML REST description, predates OpenAPI | Legacy REST contracts still in gov/enterprise | Legacy import + **migrate-to-OpenAPI via MFI-EPIC-22** (same engine/preview as RAML/API-Blueprint) | ● |
| **CORBA IDL (OMG IDL)** | Distributed-object RPC IDL | Long-lived in telecom/defense/finance back-ends | RPC normalize (interfaces/operations/structs); reuse gRPC model | ○ niche |
| **ASN.1** | Schema language for telecom/crypto/X.509/SNMP/5G/LTE | Extremely long-lived, enormous reach (every X.509 cert, 5G signalling, SNMP MIBs) | Modules→types; net-new but high-reach data-schema adapter | ● |
| **XML-RPC / ONC-RPC (XDR, RFC 4506)** | Early RPC IDLs | Legacy RPC contracts; cheap adapters | RPC normalize; migrate notes | ○ niche |

### 9.4 Prioritization (suggested promotion order)

```
Tier 1 (promote next — highest strategic value):
  A2A Agent Card  ·  OpenRPC  ·  CloudEvents/xRegistry  ·  FHIR
Tier 2 (strong, vertical/B2B pull or clean reuse):
  ACP/agents.json (agentic group)  ·  Apache Thrift  ·  ISO 20022  ·  FIX Orchestra  ·  EDI X12/EDIFACT  ·  COBOL copybooks  ·  HL7 v2
Tier 3 (niche / fold-in / opportunistic):
  Connect-RPC (→EPIC-9)  ·  FlatBuffers/Cap'n Proto  ·  WADL  ·  ASN.1  ·  JSON:API/HAL  ·  JTD  ·  CORBA IDL  ·  ISO 8583  ·  XML-RPC/ONC-RPC
```

> **2026-07 gap analysis:** see **§9.7** for a further set of candidates (collections/traffic,
> Google Discovery, Federation, CRDs, LLM tool schemas, Overlays, WIT, gateway configs) — the
> highest-value of which (HAR/Insomnia/Bruno) were promoted straight into **MFI-EPIC-32** rather
> than parked here.

**Two model changes these candidates imply for MFI-EPIC-1/2 (worth designing in now):**
1. An **"agent descriptor" paradigm** (skills/capabilities/auth) in the canonical model so A2A/ACP
   Agent Cards catalog as first-class citizens beside operation-based APIs.
2. A **"registry-as-source" ingestion mode** — xRegistry, Confluent Schema Registry, FHIR
   `/metadata`, and a future A2A registry are all *catalogs we crawl*, not single files; the
   plug-in SPI's live-discovery path (MFI-1.x) should model "crawl a registry" alongside "fetch one doc".

### 9.5 Sources (section 9)

- A2A protocol & Agent Card / discovery — https://a2a-protocol.org/latest/specification/ · https://a2a-protocol.org/latest/topics/agent-discovery/ · https://agent2agent.info/docs/concepts/agentcard/
- Agent-interoperability landscape (MCP/A2A/ACP/ANP, LF governance) — https://arxiv.org/html/2505.02279v1 · https://getstream.io/blog/ai-agent-protocols/ · https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/
- Agentic-web manifests (agents.json/agent.json/agents.txt/llms.txt/x402/AP2/WebMCP) — https://www.agentwebprotocol.org/ · https://github.com/agents-txt/agents-txt
- OpenRPC — https://spec.open-rpc.org/ · https://www.open-rpc.org/
- CloudEvents (CNCF) + xRegistry — https://github.com/cloudevents/spec · https://xregistry.io/ · https://github.com/xregistry/spec
- Apache Thrift / FlatBuffers / Cap'n Proto / Connect-RPC — https://thrift.apache.org/ · https://en.wikipedia.org/wiki/FlatBuffers · https://capnproto.org/ · https://connectrpc.com/
- FHIR / HL7 — https://www.hl7.org/fhir/ · https://blog.hl7.org/topic/fhir · https://en.wikipedia.org/wiki/Fast_Healthcare_Interoperability_Resources
- ISO 20022 / SWIFT · FIX Orchestra · EDI X12/EDIFACT/Peppol — https://www.iso20022.org/ · https://www.fixtrading.org/standards/fix-orchestra/ · https://intuitionlabs.ai/articles/x12-edi-standard-guide
- Mainframe modernization (COBOL copybooks, z/OS Connect) — https://www.openlegacy.com/solutions/platform/cics-mainframe-integration · https://openmainframeproject.org/blog/mentorship-series-automating-mainframe-modernization-using-ai-agents-to-reduce-costs-by-a-vijay-aditya/
- ASN.1 — https://www.itu.int/en/ITU-T/asn1/Pages/introduction.aspx

### 9.6 Filed issues (map)

Umbrella **#3715**. Epics & issues created from this section (all `roadmap-candidate`, post-MVP):

| Epic | Issue | Candidate | Tier |
|---|---|---|---|
| **MFI-EPIC-18** #3970 — Agent Descriptor Cataloging | #3974 | MFI-18.1 A2A Agent Card adapter (top pick) | 1 |
| | #3975 | MFI-18.2 ACP (Agent Communication Protocol) | 2 |
| | #3976 | MFI-18.3 Agentic-web site manifests (agents.json/agent.json/agents.txt/llms.txt) | 2 |
| | #3977 | MFI-18.4 Canonical model: agent-descriptor paradigm | 1 |
| | #3978 | MFI-18.5 Registry-as-source ingestion mode | 1 |
| **MFI-EPIC-19** #3971 — Modern RPC / Event | #3979 | MFI-19.1 OpenRPC (JSON-RPC 2.0) | 1 |
| | #3980 | MFI-19.2 CloudEvents + xRegistry | 1 |
| | #3981 | MFI-19.3 Apache Thrift | 2 |
| | #3982 | MFI-19.4 FlatBuffers / Cap'n Proto | 3 |
| | #3983 | MFI-19.5 Connect-RPC (fold into EPIC-9) | 3 |
| | #3984 | MFI-19.6 REST hypermedia conventions (JSON:API/HAL/Hydra/JTD) | 3 |
| **MFI-EPIC-20** #3972 — Vertical (Health & Finance) | #3985 | MFI-20.1 FHIR (R4/R5/R6) | 1 |
| | #3986 | MFI-20.2 HL7 v2 | 2 |
| | #3987 | MFI-20.3 ISO 20022 | 2 |
| | #3988 | MFI-20.4 FIX / FIX Orchestra | 2 |
| | #3989 | MFI-20.5 EDI X12 / EDIFACT (+ Peppol/UBL) | 2 |
| | #3990 | MFI-20.6 ISO 8583 | 3 |
| **MFI-EPIC-21** #3973 — Legacy / Mainframe | #3991 | MFI-21.1 COBOL copybooks | 2 |
| | #3992 | MFI-21.2 z/OS Connect / CICS-IMS binding (fold-in) | 3 |
| | #3993 | MFI-21.3 WADL (→ migrate-to-OpenAPI) | 3 |
| | #3994 | MFI-21.4 CORBA IDL (OMG IDL) | 3 |
| | #3995 | MFI-21.5 ASN.1 | 3 |
| | #3996 | MFI-21.6 XML-RPC / ONC-RPC (XDR) | 3 |

### 9.7 Gap-analysis additions (2026-07 — **not yet filed**)

The §1–§17 set covers formats that are *designed* (IDLs, schemas, contracts); §9.0–9.6 adds
agents, modern RPC/event, verticals, and legacy. The systematic blind spot the 2026-07 gap
analysis found is the **observed / collected** family — traffic captures and API-client
workspaces — which is what mid-market teams actually possess. The three highest-value entries
(**HAR, Insomnia, Bruno**) were promoted directly into **MFI-EPIC-32** (with Postman-behind-SPI);
the rest are cataloged here. None of these are filed as issues yet.

| Candidate | What it is | Path into apiome | Fit |
|---|---|---|---|
| **HAR / Insomnia / Bruno / Postman-SPI** | Traffic captures + API-client collections | **Promoted → MFI-EPIC-32** (inferred-spec engine, scrub gate, Catalog + EPIC-22 promotion) | ●●● shipped upstairs |
| **Google API Discovery** | Google's JSON API description (near-OpenAPI shape); export side already planned (MFX-EPIC-29.2) | Cheap normalizer (REST paradigm); huge public corpus for seeding catalogs; live discovery via the public directory endpoint | ●● Tier 2 |
| **GraphQL Federation supergraph/subgraph** | Apollo Federation composition (supergraph SDL, subgraph set) — `rover` is **already bundled** (MFI-5.2) | Extend **EPIC-10**: composition-aware import, subgraph-level ownership + diff (which subgraph broke the supergraph) | ●● Tier 2 (fold into EPIC-10) |
| **`.http` / `.rest` files + cURL snippets** | VS Code REST Client / JetBrains HTTP Client request files; ubiquitous in repos | Same inferred-spec engine as EPIC-32 (32.1); natural 29.3 git-intake citizen | ●● Tier 2 (fold into EPIC-32) |
| **Kubernetes CRDs** | CustomResourceDefinitions embed OpenAPI v3 structural schemas | Schemas → the JSON-Schema/types path (data-schema paradigm); opens the platform-engineering audience; live discovery via cluster API is a later opt-in | ●● Tier 2 |
| **LLM tool/function schema bundles** | Bare OpenAI/Anthropic function-calling tool arrays (JSON-Schema based) — the most common agent artifact in the wild, *not* covered by MCP/A2A/agents.json | Candidate **MFI-18.6** in the agent-descriptor epic; reuse JSON-Schema normalizer + agent paradigm | ●● Tier 2 (→ EPIC-18) |
| **OpenAPI Overlay Specification 1.0** | Standardized patch/overlay documents applied to a base OpenAPI doc | Pre-processor in the OpenAPI adapter: overlay + base → resolved spec, provenance notes which values came from the overlay | ● Tier 3 |
| **WIT (WebAssembly Component Model)** | Interface types for Wasm components (`.wit`) | Watch-list: RPC-ish normalize (worlds/interfaces/functions); revisit when the ecosystem settles | ○ Tier 3 |
| **Gateway configs (Kong declarative, K8s Gateway API HTTPRoute)** | Infra route configs that imply an API surface | Inferred, partial-fidelity import (routes/hosts/methods, no schemas) — pairs with the EPIC-32 provenance machinery | ○ Tier 3 |

**Also folded from this analysis (features, not formats — filed 2026-07-03):** MFI-EPIC-29 #4384 (intake hardening),
MFI-EPIC-30 #4385 (Swagger 2.0 / Arazzo / **OpenAPI 3.2** — note OAS 3.2 is a *current-spec* obligation,
not a candidate), MFI-EPIC-31 #4386 (re-discovery & drift alerts), MFI-EPIC-32 #4387, MFI-6.4 #4410 (cross-format identity), and
the MFI-22.7 / UI-26.4 MVP promotions. See §0.3.
