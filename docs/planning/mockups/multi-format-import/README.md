# Multi-Format Import Catalog — design mockup

Static, browser-openable mockup of the **Catalog** screen in objectified-ui — the home for
imports that are **OpenAPI-worthy but not OpenAPI** (gRPC, GraphQL, AsyncAPI, OData, SOAP/WSDL,
Avro, RAML, Smithy, TypeSpec, API Blueprint…). It is the UI surface for the multi-format import
pipeline. Roadmap: [`ROADMAP_MULTI_FORMAT_IMPORT.md`](../../../ROADMAP_MULTI_FORMAT_IMPORT.md)
(**MFI-EPIC-23** catalog screen + **MFI-EPIC-22** convert / fidelity preview).

For design iteration only — not production code; sample data is illustrative.

## View

```bash
xdg-open docs/planning/mockups/multi-format-import/index.html   # Linux
# or drag the file into a browser
```

Click a **catalog card** to open its detail view. On the detail view use the tab strip
(Overview / Source & Code / Provenance / Lint & Score / Versions). The **Source & Code** tab loads
a **real Monaco editor** (read-only) over a CDN — needs network access. Top-bar **Import** opens the
import wizard; **Convert to OpenAPI** opens the fidelity-preview dialog.

## Screens & roadmap mapping

| Screen | Purpose | Roadmap |
|--------|---------|---------|
| **Sidebar** | Adopts `DashboardSideNav`; **Catalog** sits in the *Specifications* section (lucide `Library`, amber **Preview** pill) between Repositories and MCP Servers. | MFI-23.6 |
| **Catalog** (grid + table) | Cloned wholesale from the Projects dashboard: stat KPIs, filter chips (All / Active / Needs attention / Deleted), **Cards ↔ Table** toggle, group-by-protocol, sort (+ grade/format). Each entry shows **name**, short id `cat_…`, status pill, **FormatPill / ProtocolPill / SourceBadge**, and clickable **Quality + Lint (A–F) + Debt** orbs; converted items carry a **Converted → project** back-link. **No Publish anywhere.** | MFI-23.2/23.3/23.4/23.5/23.11 |
| **Import wizard** | New source in the existing Import flow — stepper + side-by-side source/destination panels for the current base sources: File Upload, URL Import, and Clipboard paste. The compact guide explains Catalog-only, Projects, JSON Schema choice, and future source-method branches before detection. Shows **auto-detect** + the **routing decision** (Catalog vs Projects). | MFI-1.3/1.5/23.7; UI addendum folded into MFI-26.1/26.3 |
| **Detail · Overview** | Human-readable parsed model: normalized **counts** (services/operations/types/channels) + **entity blocks** rendered per paradigm (GraphQL types/ops, gRPC services/messages, AsyncAPI channels/messages, OData entity sets, WSDL operations/XSD, Avro records, Smithy shapes, TypeSpec models, API-Blueprint resources, RAML resources). | MFI-23.9 |
| **· Source & Code** | Read-only **Monaco** viewer over the raw imported artifact, language-highlighted per format; download original. | MFI-23.9 (view/download) → MFI-23.12 (read-only Designer, later) |
| **· Provenance** | Format/protocol, source material, fingerprint, import-job ref, **tool-version chips**, and the recorded routing decision. `publishable: false`. | MFI-7.2/23.7 |
| **· Lint & Score** | Grade gauge (A–F + 0–100) + category bars + findings tagged **MUST / SHOULD**. | MFI-EPIC-4 |
| **· Versions** | Date/version-tagged timeline on the shared `versions` table; diff any two. | MFI-EPIC-3 |
| **Convert to OpenAPI** | The **fidelity-preview dialog** (`ConversionPreviewDialog`): two columns — *what the source provides* (present/inferred) vs *what OpenAPI favors but is missing* (missing/partial/n/a) — a warning banner whose strength scales with the fidelity tier, and a **low-tier acknowledgement gate**. The only exit ramp from the catalog to a publishable Project. | **MFI-22.3/22.4/22.5** |

## Format coverage in the sample data

One representative item per new format, across every paradigm:

| Paradigm | Items |
|----------|-------|
| Graph | GraphQL (Orders Graph API) |
| RPC | gRPC/Protobuf (Fleet Telemetry) · Smithy (Coffee Service) · SOAP/WSDL (Legacy Billing) |
| Event | AsyncAPI (Payments Events — *converted*) |
| REST | OData (Northwind) · TypeSpec (Widget API — *converted*) · API Blueprint (Polls) · RAML (Weather — *deleted*) |
| Data schema | Avro (User Profile — `schemas_only`) |

Each carries a distinct **format pill** (tone + icon mirror the real
`catalog-format-registry.ts`), a lint grade, a parsed human-readable model, a raw source snippet
for Monaco, and a per-source fidelity report driving the convert dialog.

## Design principles encoded here

1. **Catalog mirrors Projects, minus Publish.** Same card/table language, orbs and dialogs — the
   catalog is a parallel list surface, not a new UI. `publishable: false` is the whole difference.
2. **Format is a first-class signal.** Every entry leads with a **FormatPill + ProtocolPill +
   SourceBadge**; the grade and quality orbs sit beside it. Sort adds *grade* and *format*.
3. **Detail is parse-everything.** The point of cataloging a non-OpenAPI artifact is to make it
   legible — so the detail view renders the normalized model in human-readable blocks, not just a blob.
4. **Raw source is always viewable.** A read-only Monaco viewer over the original bytes; download too.
5. **Conversion is honest.** The only way out is Convert-to-OpenAPI, always fronted by the fidelity
   preview and (for low-fidelity sources) an explicit acknowledgement — never a silent lossy emit.
6. **Consistent with objectified-ui** — sidebar chrome, tokens (indigo `#6366f1`, slate, Aptos,
   6/8/12/16px radii), pill tones, quality orbs, and the import stepper mirror the real components.

## Open questions for iteration

- **Debt orb** is a placeholder (`—`) everywhere, matching the real card — surface it or drop it?
- Group-by default: **protocol** (as drawn) vs **format** vs flat?
- Should `schemas_only` items (Avro) get a distinct visual treatment beyond the data-schema pill?
- Should the import destination guide remain expanded by default, or collapse after the first successful import?
- Convert dialog: inline **raw-OpenAPI preview** of the would-be document (collapsible) — show by
  default or behind a button?
- Detail tab order — is Overview → Source → Provenance → Lint → Versions right?
- Dark-theme variant (objectified-ui ships multiple themes)?
