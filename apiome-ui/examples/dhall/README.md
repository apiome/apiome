# Dhall — `dhall`

Fixtures for the Dhall third of **FMT-8.5** ([#5466](https://github.com/apiome/apiome/issues/5466)).
The sibling directories are `cue/` and `pkl/`. Owned by the `dhall` adapter
(`apiome-rest/src/app/typed_config_import_source.py`, reader `dhall_parser.py`); valid entries are
pinned by golden snapshots under `apiome-rest/tests/golden/corpus/dhall/`.

**Detection markers.** `let … = … in …` bindings with type annotations (`: Text`, `: Natural`,
`: Optional …`, `List …`), union types (`< A | B : { … } >`), and the `::` completion operator, in a
`.dhall` file.

**How the adapter reads it.** The bundled `dhall` resolves, type-checks and normalizes the upload in
the sandboxed toolchain runner — network-free, time-bounded — and encodes the normal form as JSON;
the reader projects its types to JSON Schema (`dhall-to-json` renders values, not types, so its
conventions are followed instead) and the shared JSON Schema translator models them. Network-free
matters more here than for CUE or Pkl: **Dhall imports can be URLs, environment variables or absolute
paths**, and the reader refuses them before Dhall runs; the integrity-hash import in `04` (with a `?`
fallback, since it is imported on its own) makes the hash path explicit.

**Declared limits.** Dhall's types are values, so a schema can be *computed* by a function
(`\(a : Type) -> …`). Functions (type-level and dependent-ish construction included) and hash-pinned
imports have no JSON Schema analogue and are declared, not approximated; a fold or a function
*application* is computed by normalization, so its result is modelled.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-schema.dhall` | minimal | A `{ Type, default }` schema record. |
| `02-typical-order-schema.dhall` | typical | Record types, two union types, `Optional`, `List`, and a typed default value. |
| `03-imports-set/` | multi-file | `package.dhall` composing a sibling module — the conventional Dhall entry point. |
| `04-stress-type-system.dhall` | stress | Scalars, unions with and without payloads, `List { mapKey, mapValue }` maps, record type merge (`//\\`) and prefer (`/\`), a fold — then type-level functions, a generic `Page`, and a hash-pinned import as declared limits. |
| `05-real-world-service-config.dhall` | real-world | A platform schema with nested `{ Type, default }` records and two services built with `::`. |
| `06-typical-union-and-defaults.dhall` | typical | Union constructors with payloads plus record completion. |
| `07-composition-record-merge.dhall` | composition | Record types combined with `//\\`, schema records derived from other schema records. |
| `negative/` | — | A `let` chain with no `in`, a type mismatch that fails type checking, truncation, a **Nickel** file (the nearest neighbouring language), UTF-16, and an import of a file that is not in the set. |
