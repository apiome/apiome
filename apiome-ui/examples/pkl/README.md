# Pkl — `pkl`

Fixtures for the Pkl third of **FMT-8.5** ([#5466](https://github.com/apiome/apiome/issues/5466)). The
sibling directories are `cue/` and `dhall/`. Owned by the `pkl` adapter
(`apiome-rest/src/app/typed_config_import_source.py`, reader `pkl_parser.py`); valid entries are pinned
by golden snapshots under `apiome-rest/tests/golden/corpus/pkl/`.

**Detection markers.** `module <name>` plus `class X { … }` / `typealias …` declarations, member
constraints in parentheses (`Int(isPositive)`, `String(matches(Regex(…)))`), and `Listing<…>` /
`Mapping<…,…>` types, in a `.pkl` file.

**How the adapter reads it.** `pkl eval` in the sandboxed toolchain runner — network-free,
time-bounded, modules only from the upload, no resource reads — runs a reflection program over the
upload; the reader projects classes and aliases to JSON Schema (constraints read from each annotation)
and the shared JSON Schema translator models them. `negative/02` is the
fixture where evaluation itself fails a constraint, and `04-stress-type-system.pkl` includes a
`read("env:…")` that the sandbox must refuse.

| File | Rung | What it exercises |
| --- | --- | --- |
| `01-minimal-schema.pkl` | minimal | Two module-level typed properties. |
| `02-typical-order-schema.pkl` | typical | `typealias` union and regex alias, constrained `Int`/`String`, nullable with a constraint (`Float(…)?`), a non-empty `Listing`. |
| `03-modules-set/` | multi-file | Root module importing a shared module's classes. |
| `04-stress-type-system.pkl` | stress | Every scalar (including `Duration`/`DataSize`), collection types, `open`/`abstract` classes and inheritance, unions — then amending, `this`-constrained late binding, generators, conditionals, `read("env:…")`, `output` renderers and a function, as declared limits. |
| `05-real-world-service-config.pkl` | real-world | A platform template: an `open class` every service amends, defaults on nearly every member, a `ProductionService` subclass tightening `replicas`, and two concrete services. |
| `06-typical-template-and-instance.pkl` | typical | Class template plus an amended instance in one module. |
| `07-composition-mixins.pkl` | composition | An open-class chain amended by two subclasses and a module value that amends the tree. |
| `negative/` | — | Unclosed class, a default that violates its own constraint, truncation, a **CUE** file (the sibling language), UTF-16, and an import of a module that is not in the set. |
