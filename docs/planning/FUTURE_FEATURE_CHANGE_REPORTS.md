# Publication change reports (OpenAPI diff → human-readable)

**Scope:** When a **specification is published**, Apiome generates a **change report** comparing the new published OpenAPI snapshot to a **baseline** (typically the immediately prior published revision, or a user-selected comparison target where the product allows it). The report is **human-readable**, structured with a **header**, **body** (schemas, properties, references/relationships, documentation), and **footnote**, and appears on the **Version** page for that publication.  
**Repository:** [KenSuenobu/objectified-commercial](https://github.com/KenSuenobu/objectified-commercial).  
**GitHub epic:** [#2698](https://github.com/KenSuenobu/objectified-commercial/issues/2698) (**CR-R1**). Full ticket index: `docs/CHANGE_REPORTS.md`.

---

## Roadmap ID

| ID | Meaning |
|----|---------|
| **CR-R1** | Umbrella epic — diff engine, persistence, templates, publication hook, Version page UX |
| **CR-01** | Semantic OpenAPI diff (schemas, properties, refs, docs) |
| **CR-02** | Persist report snapshots + overrides per publication |
| **CR-03** | Template model (header / body / footnote) + rendering |
| **CR-04** | Publication workflow integration |
| **CR-05** | Version page — view and edit report + template |
| **CR-06** | Tests (contract, E2E) and release gate |
| **CR-V2-01** | Enterprise: PDF, approvals, audit (post-MVP) |

---

## Problem

Consumers of published APIs need to understand **what changed** between releases without manually diffing raw OpenAPI YAML/JSON. Today, teams rely on external tools or ad-hoc release notes. Apiome already versions specifications; **publication** is the natural point to produce a **canonical, reviewable change narrative** tied to each published version.

---

## Solution (product shape)

1. **On publish**, resolve two OpenAPI documents (baseline vs candidate), run a **semantic diff**, and produce a **structured change model** (not only line diff).
2. **Render** that model through a **template** (header, body sections, footnote) into a stable artifact (e.g. HTML or Markdown stored server-side).
3. On the **Version** page, show the report for each **published** revision; allow users to **edit the rendered report** and/or **adjust the template** used for future publications (scope per product rules in CR-02/CR-05).
4. **V2** adds enterprise concerns: PDF export, approval gates, and immutable audit of edits.

---

## High-level architecture

```
  [Published rev N-1]     [Candidate at publish]
         |                          |
         +---------> [ Resolve OpenAPI ] <--------+
                         |
                         v
                 [ Semantic diff engine ]
                 (schemas, props, $ref,
                  relationships, descriptions )
                         |
                         v
                 [ Change model (JSON) ]
                         |
                         v
                 [ Template + render ]
                 header | body | footnote
                         |
                         v
                 [ Stored report artifact ]
                         |
                         v
                 [ Version page: view / edit ]
```

---

## Diff coverage (MVP)

| Area | Included |
|------|----------|
| **Component schemas** | Added / removed / renamed (where detectable); material type changes |
| **Properties** | Added / removed / type or format changes; required array changes |
| **References** | `$ref` targets changed; new or broken ref paths (reported as warnings where applicable) |
| **Relationships** | Composition / allOf / oneOf / discriminator-related changes surfaced in schema section |
| **Documentation** | `description`, `summary`, and top-level `info` field changes (title, version string, contact if present) |

Non-goals for MVP (may be V2): arbitrary markdown in external files, diff of non-OpenAPI sidecars, multi-spec aggregate reports.

---

## Template and editing model

```
  Default template (system / tenant)
           |
           v
  Project template override (optional)
           |
           v
  Publication render  ----->  User edits "report instance"
           |                    (per published version)
           v
  Stored artifact + edit metadata (MVP: author/time; V2: full audit)
```

---

## ASCII: Version page placement

```
+------------------------------------------------------------------+
|  Version: v3.2.0 (published)                         [Compare ...] |
+------------------------------------------------------------------+
|  Summary |  CHANGE REPORT  |  History |  ...                     |
+------------------------------------------------------------------+
|  [ Header: product name, from -> to, date ]                      |
|                                                                  |
|  Schemas                                                         |
|    - Pet: property `tag` added (string)                          |
|    - Error: removed                                              |
|  ...                                                             |
|  Documentation                                                   |
|    - info.description updated                                    |
|                                                                  |
|  [ Footnote: generator version / legal / links ]                 |
|                                                                  |
|  [ Edit report ]   [ Edit template ]                             |
+------------------------------------------------------------------+
```

---

## Dependencies

- **Git-like / publish:** A reliable notion of **published revision** and immutability (see existing versioning epics in `PLANNED_FEATURES.md`).
- **OpenAPI resolution:** Both sides of the diff must be **fully resolved** (dereferenced components) for stable comparison.

---

## Related documents

- `docs/CHANGE_REPORTS.md` — epics, tickets, testing, GitHub links.
- `docs/PLANNED_FEATURES.md` — MVP sequencing including this round of work.
