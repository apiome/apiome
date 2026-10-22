# CUE — `cue`

Fixtures for the CUE third of **FMT-8.5** ([#5466](https://github.com/apiome/apiome/issues/5466)).
CUE, Pkl and Dhall are typed configuration languages whose schemas are genuine, checkable type
definitions; the sibling directories are `pkl/` and `dhall/`. Owned by the `cue` adapter
(`apiome-rest/src/app/typed_config_import_source.py`, reader `cue_parser.py`); valid entries are pinned
by golden snapshots under `apiome-rest/tests/golden/corpus/cue/`.

**Detection markers.** `package <name>` plus `#Definition: { … }` declarations, constraint operators
(`&`, `|`, `=~`, `>=`), and optional-field `?:` syntax, in a `.cue` file.

**How the adapter reads it.** The bundled `cue` runs **in the sandboxed toolchain runner** —
network-free, time-bounded: `cue export` evaluates the package, then `cue export --out jsonschema`
projects every definition, and the shared JSON Schema translator models it. That is why `negative/06`
matters: an *incomplete* configuration is valid CUE and still produces no export.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-schema.cue` | minimal | One definition, two fields. |
| `02-typical-order-schema.cue` | typical | Disjunction enums, regex and range constraints, list types with a non-empty bound, optional fields, a default branch. |
| `03-imports-set/` | multi-file | A module laid out flat: root schema, an imported package (`example.com/shipping/shared`), and a `cue.mod` file the reader lays out as `cue.mod/module.cue`. |
| `04-stress-lattice.cue` | stress | Every scalar and collection form, open vs closed structs, embedding, **unification narrowing**, recursion — then comprehensions, conditional fields, hidden fields, `let` and interpolation as declared limits. |
| `05-real-world-service-config.cue` | real-world | A platform configuration schema with defaults, a cross-field production constraint, a pattern-keyed service map, and a conforming instance. |
| `06-typical-schema-and-data.cue` | typical | Schema **and** data in one file — the idiom where evaluation both validates and completes. |
| `07-composition-embedding.cue` | composition | Definitions built by embedding and narrowed by unification, plus a pattern-keyed map. |
| `negative/` | — | Unclosed struct, a unification that bottoms out, a file cut off mid-constraint, an **HCL** file, UTF-16, and an incomplete value that `cue export` refuses. |

**Declared limits.** CUE's lattice unification exceeds JSON Schema: comprehensions, conditional
fields, `let` bindings, hidden fields, computed interpolations, defaults, label references and most
standard-library validators have no analogue, and FMT-8.5 requires them declared rather than
approximated (`cue.*` keys in the coverage ledger).
