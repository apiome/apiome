# Multi-Format Export — design mockup

Static, browser-openable mockup of the **Multi-Format API Export & Cross-Protocol Transcoding**
experience in apiome-ui (and apiome-browse). The mirror of the import flow.
Roadmap: [`ROADMAP_MULTI_FORMAT_EXPORT.md`](../../../ROADMAP_MULTI_FORMAT_EXPORT.md) (MFX).

For design iteration only — not production code; sample data is illustrative.

## View

```bash
xdg-open docs/planning/mockups/multi-format-export/index.html
```

Click **Export** (top bar) to open the **ExportDialog**. Pick different target cards to watch the
fidelity warning + preserved-% update. Use the left rail / buttons to switch screens.

## Screens & roadmap mapping

| Screen | Purpose | Roadmap |
|--------|---------|---------|
| **Version (entry point)** | Export is a **function of the version being viewed** (top-bar **Export** + "Export this version") — **not** a global left-nav item, since a tenant may have hundreds of projects/versions. Navigate *Projects → project → version*, then export that version. Pre-summarizes high- vs low-fidelity targets *for this source*. | MFX-EPIC-6.5, EPIC-2 |
| **ExportDialog** | Mirror of `ImportDialog`: numbered stepper + **target-card grid** (12 formats, each with a per-source fidelity badge) + options. | MFX-EPIC-1/6 |
| **Fidelity panel (headline)** | "Exporting to {format} may lose some fidelity" advisory + **preserved-% ring** + per-construct report (DROP / APPROX / SYNTH / OK) + counts. | **MFX-EPIC-2** |
| **Result** | Download (single file / zip bundle), fidelity report, emitted-artifact preview, round-trip diff. | MFX-EPIC-4/5/6.3/6.4 |
| **Public browse export** | Same fidelity advisory in apiome-browse (dark public chrome), no auth. | MFX-EPIC-7.2 |

## The fidelity model (the point of this feature)

Each lost construct is classified and color-coded:

- **DROP** (red) — unrepresentable in the target, removed (e.g. `oneOf` union → Protobuf).
- **APPROX** (amber) — represented imperfectly (e.g. `pattern`/`min`/`max` → comments).
- **SYNTH** (violet) — invented to satisfy the target (e.g. Protobuf field numbers).
- **OK** (green) — clean.

The **same advisory copy + report** renders in **apiome-ui, apiome-browse, the REST
preview, and the CLI** — per the directive that users be told *"the exported target format may lose
some fidelity from the originally imported data, due to the API not allowing for as much detail as
was provided."*

Per-target fidelity badges on the cards (`lossless` / `lossy` / `types-only`) are computed for the
**specific** source — e.g. a rich OpenAPI source exports **lossless** to OpenAPI/Smithy/TypeSpec,
**lossy** to gRPC/GraphQL/WSDL, and **types-only (severe)** to Avro (operations can't be expressed).

## Design principles

1. **Export is version-scoped, not global** — it's an action on the version you're viewing, not a left-nav menu item (hundreds of projects/versions make a global "Export" meaningless).
2. **Symmetry with import** — same `ImportDialog` stepper + card grid + `DashboardSideNav` tokens, inverted.
2. **Fidelity is unmissable** — warning before download, with a quantified preserved-% and a per-construct report; lossy exports require an explicit "Export anyway".
3. **Honest about severe cases** — Avro (types-only) and Arazzo (workflow-only) warn loudly rather than silently emitting a near-empty artifact.
4. **Validated output** — emitted artifact is re-parsed by the import parser (round-trip), shown as "valid · round-trip OK".

## Open questions for iteration

- Should lossy exports be **blocked** (hard confirm) or just **warned** above a severity threshold?
- Show the **round-trip diff** inline by default, or behind a button (as drawn)?
- Per-target options surface (proto3 vs editions, CSDL JSON vs XML, AsyncAPI 2 vs 3) — dialog vs advanced drawer?
- A **fidelity score** persisted in the catalog per export (like the lint grade)?
- Dark-theme variant?
