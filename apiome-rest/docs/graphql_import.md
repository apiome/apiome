# GraphQL Import Source (MFI-10.6)

> **Status:** `ImportSource` adapter — `src/app/graphql_import_source.py`
> **Issue:** [#3775](https://github.com/objectified-project/objectified/issues/3775) ·
> **Epic:** MFI-EPIC-10 (#3725) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The [`ImportSource`](./import_source_spi.md) adapter (MFI-1.1) that makes the GraphQL pipeline of
MFI-10.1…10.5 reachable from the **UI source card** and the **CLI `import` command**. Like the
reference [OpenAPI adapter](./import_source_spi.md) and the
[AsyncAPI adapter](./asyncapi_import.md) it is a thin seam over machinery that already exists — it
adds *no* new parsing, mapping, or scoring logic:

```
 GraphQlImportSource
   ├─ detect()      SDL keyword / `.graphql` ext / `__schema` payload → graphql   (cheap sniff)
   ├─ parse()       build_graphql_schema (MFI-10.1) → built graphql-core GraphQLSchema
   ├─ introspect()  introspect_endpoint (MFI-10.3) → live schema (SSRF-guarded, SDL fallback)
   ├─ normalize()   registered GraphQlNormalizer (MFI-10.2) → CanonicalApi (paradigm GRAPH)
   ├─ lint()        lint_graphql_result (MFI-10.4) → score / grade / fingerprint
   └─ fingerprint()/diff()  canonical-model defaults (the MFI-10.5 breaking overlay layers on the diff)
```

Registering the adapter (`register=True`) is **all the UI and CLI need** for the SDL path. Both
surfaces are data-driven off the [import-source registry](./import_source_spi.md)
(`GET /v1/import/sources`):

* **UI** — the source-card grid merges every registry descriptor, so a `graphql` card with the
  `waypoints` icon, the *graph* paradigm, and file/url/paste/discovery inputs appears with no UI
  change.
* **CLI** — `apiome import --list` enumerates the registry and `apiome import graphql
  <input>` dispatches through the generic adapter-import path (MFI-1.4) with no new command code.

## Two paths, one canonical version

GraphQL is the first source whose `supports_live_discovery` is `True`, so it has **two** ways to
reach the same canonical model — and the acceptance criterion is that **both catalog a version**:

* **SDL** — `parse()` builds a `graphql-core` `GraphQLSchema` from SDL text via the MFI-10.1 parser.
  An invalid schema (unknown type, missing root) becomes a clean `ImportSourceError` so the job
  fails with a user-facing message rather than a stack trace. A *captured introspection response*
  (`{"data": {"__schema": …}}` or a bare `{"__schema": …}` payload) is recognized and rebuilt to
  canonical SDL first, so a discovery import whose document is the live `__schema` answer parses
  through the same path.
* **Live introspection** — `introspect()` runs the SSRF-guarded MFI-10.3 introspection service
  against a live endpoint: it POSTs the standard introspection query, rebuilds the schema from the
  `__schema` response, and **falls back** to caller-supplied uploaded SDL when the endpoint has
  introspection disabled. It returns the built schema, ready for `normalize()`. A live-introspected
  schema fingerprints **identically** to the same schema imported from SDL.

Because both paths return a built `GraphQLSchema`, `normalize()` / `fingerprint()` / `lint()` are
shared: the typed schema is mapped to a `CanonicalApi` of paradigm `GRAPH`, keyed by GraphQL Schema
Coordinate (MFI-10.2), and rolled up to a deterministic score / grade / `report_fingerprint`.

## Detection

`detect()` recognizes GraphQL three cheap ways, none of which raise: a top-level SDL definition
keyword (`type`/`interface`/`input`/`enum`/`union`/`scalar`/`schema`/`directive`) in the source
text, a `.graphql` / `.gql` / `.graphqls` filename, or a captured introspection response (a
`__schema` payload). Unlike OpenAPI/AsyncAPI, SDL is plain schema text — not a JSON/YAML mapping —
so detection reads `text`/`filename` rather than a parsed `document`.

## Normalize & lint

`normalize()` accepts the `GraphQLSchema` `parse()` / `introspect()` returns, or bare SDL text (which
it parses first), and delegates to the registered [`GraphQlNormalizer`](./normalizer_spi.md)
(MFI-10.2). `lint()` runs [`lint_graphql_result`](./graphql_lint.md) (MFI-10.4), which is pure over
the canonical model — the always-on common pack plus the registered native GraphQL rules always
produce a deterministic score; the authoritative `graphql-eslint` findings are folded in by the
MFI-4.3 external-linter adapter when present.

## Tests

`tests/test_graphql_import_source.py` — descriptor + registry registration, SDL / filename /
introspection-payload detection, SDL parse (+ invalid-schema error mapping and captured
introspection parse), normalize → graph model + determinism + error boundaries, lint roll-up, and
the live-introspection discovery seam over an `httpx.MockTransport` (success cataloging a version,
the disabled-endpoint SDL fallback, the no-fallback failure, and an SSRF-rejected endpoint). The
GraphQL toolchain is pure Python, so every path runs without gating.
