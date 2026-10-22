---
title: "Import CUE, Pkl and Dhall schemas"
description: "Catalog typed configuration schemas, evaluated by each language's own tool."
sidebar_position: 8.9
tags: [import, cue, pkl, dhall, configuration, schema]
---

CUE, Pkl and Dhall are typed configuration languages: platform teams use them to write the
contract a configuration must meet — which fields exist, their types, and the constraints on them.
Apiome imports those contracts as **schema types** in the catalog, with the constraints attached.

## Each language reads itself

Apiome does not re-implement these languages. Each upload is evaluated by the language's own tool,
bundled with Apiome:

| Language | Tool | What it does during an import |
| --- | --- | --- |
| CUE | `cue` | `cue export` evaluates the package, then CUE's own JSON Schema generator describes every `#Definition`. |
| Pkl | `pkl` | `pkl eval` reflects every class and type alias, and evaluates the module's values. |
| Dhall | `dhall` | Resolves imports, type-checks and normalizes the expression, then encodes it for Apiome to read. |

The evaluation runs in a sandbox: **no network**, a private scratch directory, and a time limit.
It can read the files you uploaded and nothing else — a Pkl `read("env:…")`, a Dhall import from a
URL or an environment variable, or a module outside the upload is refused.

If the tool rejects your upload — a type error, a value that breaks its own constraint, a CUE
conflict — the import fails with the tool's own explanation.

## What you can import

| You have | Import it as |
| --- | --- |
| One `.cue`, `.pkl` or `.dhall` file | One file, or paste the source |
| A CUE module (a `cue.mod` and several packages) | One archive. The root is a file of the package whose definitions you want. Uploading the files flat, with a `cue.mod` file beside them, also works. |
| Pkl modules that import one another | One archive; the root is the module whose classes you want |
| A Dhall package (`package.dhall` and the files it imports) | One archive; the root is `package.dhall` |

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises each language from its source and picks **CUE** (`cue`), **Pkl** (`pkl`) or **Dhall**
(`dhall`).

The types land in the [Catalog](./catalog.mdx) as a schemas-only item, named after the root's main
record.

## What each part becomes

| CUE | Pkl | Dhall | Becomes |
| --- | --- | --- | --- |
| `#Order: { … }` | `class Order { … }` | `Order = { id : Text, … }` | A record |
| Embedding (`#Record`), unification (`#Base & {…}`) | `class Child extends Base` | A record type merge (`A //\\ B`) | A record that includes its base's fields |
| `"a" \| "b"` | `"a" \| "b"` | `< A \| B >` | An enum |
| Any other disjunction | Any other union | A union with payloads | A union |
| `field?: T` | `T?` | `Optional T` | A nullable field |
| `[string]: T` | `Mapping<String, T>` | `List { mapKey : Text, mapValue : T }` | A map |
| `[...T]` | `Listing<T>`, `List<T>`, `Set<T>` | `List T` | A list (a set adds unique items) |
| — | `typealias Sku = String(…)` | — | A named alias with its constraints |
| — | A template module's own properties (`id: String` with no value) | `{ Type = …, default = … }` | A record (for Dhall, `default` gives the field defaults) |

Constraints are kept on the field:

| CUE | Pkl | Becomes |
| --- | --- | --- |
| `>=0`, `<=9999`, `int` | `isBetween(…)`, `isPositive`, `this >= n`, `Int8` … `UInt` | Numeric bounds |
| `=~"…"` | `matches(Regex("…"))`, `startsWith`, `endsWith` | A pattern |
| `strings.MinRunes`, `strings.MaxRunes` | `length.isBetween(…)`, `length <= n`, `!isEmpty` | String length |
| `[_, ...]`, `list.MaxItems` | `!isEmpty`, `length <= n`, `isDistinct` on a listing | Item count, unique items |

A Dhall `Natural` is an integer with a minimum of 0. Pkl and Dhall defaults become field defaults.

Concrete values a file also defines — a CUE `platform: #Platform & {…}`, a Pkl `services` mapping, a
Dhall list of services — are checked by the tool and listed on the import as **instances**; they
are data, not types.

## What is declared, not imported

These languages can say things a JSON Schema cannot. Apiome lists them in the import's coverage
ledger rather than approximating them:

- **CUE** — comprehensions and interpolated strings (the computed field is left out); conditional
  fields (`if …`; the rest of the definition is kept); `let` bindings and hidden fields; defaults
  (`*value`); standard-library validators other than the length and item-count ones; `bytes`; a
  pattern that refers to its own label (`[Name=string]: {name: Name}`).
- **Pkl** — any constraint other than the ones in the table above; constraints written in terms of
  another property (`Int(this > minimum)`); defaults computed from other properties or generated
  with `for` / `when`; resource reads the sandbox refused; `output` blocks and methods;
  `Duration` and `DataSize` (imported as text); maps whose keys are not strings.
- **Dhall** — functions, including type-level ones such as `\(a : Type) -> { items : List a }` (a
  type built by applying one, like `Page Text`, is imported as the type it produced); integrity
  hashes on imports.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_MALFORMED` | The file has a syntax error, such as a missing closing brace. |
| `INPUT_TRUNCATED` | The file stops in the middle of a declaration. |
| `INPUT_SEMANTIC_INVALID` | The tool rejected it: a CUE conflict or an incomplete value, a Pkl value that breaks its own constraint, a Dhall type error — or the file declares no types. |
| `INPUT_REFERENCE_UNRESOLVED` | An import is not in the upload, or reaches outside it (a URL, an environment variable, an absolute path). Add the imported files to the upload. |
| `INPUT_TIME_LIMIT` | Evaluation did not finish within the time limit. |
| `FORMAT_MISMATCH` | The file is another language — for example HCL, CUE uploaded as Pkl, or Nickel. |
| `INPUT_ENCODING_INVALID` | The file is not UTF-8 (for example, it was saved as UTF-16). |

## What is inferred

On the catalog item, a type Apiome names (an anonymous record or list item) is **synthesized**. Those entities carry a badge with the evidence, and the
**Provenance** filter on the **Overview** tab narrows to them — see
[Declared, inferred and synthesized](./inference-provenance.mdx).

## Related

- [Supported formats](./supported-formats.md#format-cue): what these importers read, with
  [Pkl](./supported-formats.md#format-pkl) and [Dhall](./supported-formats.md#format-dhall).
- [Import Pydantic models](./pydantic-model-import.md) and [Import Zod schemas](./zod-schema-import.md):
  other code-first schema sources, modelled the same way.
- [Read a catalog item's format details](./catalog-format-details.md): where the coverage ledger
  lists what was declared.
