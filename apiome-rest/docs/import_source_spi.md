# ImportSource SPI & registry (MFI-1.1)

> **Status:** SPI + registry + reference/sample adapters — `src/app/import_source.py`,
> `src/app/openapi_import_source.py`, `src/app/sample_import_source.py`
> **Issue:** [#3733](https://github.com/objectified-project/objectified/issues/3733) ·
> **Epic:** MFI-EPIC-1 (#3716) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The **ImportSource SPI** is the extension seam the multi-format import roadmap
hangs on. Before it, a new format meant editing the import engine *and* the import
wizard — there was no place to plug one in. Now a format is added by **registering
a source**: one adapter class that the UI (source cards, MFI-1.3), the CLI (source
dispatch, MFI-1.4), and REST all drive through one uniform contract and enumerate
from one registry.

```
 detect          parse              normalize            fingerprint / diff / lint
 input ─▶ confidence   raw ─▶ native_ast   native_ast ─▶ CanonicalApi ─▶ (shared, canonical-level)
        (per adapter)        (per adapter)       (delegates to a Normalizer, MFI-2.3)
```

An adapter is **deterministic and side-effect free**: fetching happens in the
ingestion layer *before* `parse()`, so the same document always produces an equal
model and therefore an identical fingerprint.

## The contract

`ImportSource` (an `ABC`) carries descriptor metadata as class attributes and
three abstract, format-specific methods plus three shared, canonical-level methods
with working defaults:

| Member | Kind | Purpose |
|--------|------|---------|
| `key` / `label` / `description` / `icon` | metadata | registry key + how a source card / CLI listing renders |
| `paradigm` | metadata | the `ApiParadigm` the adapter produces |
| `input_kinds` | metadata | which of file / url / paste / discovery it accepts (`InputKind`) |
| `supports_live_discovery` | metadata | whether it can introspect a live endpoint |
| `formats` | metadata | normalizer format keys it can emit (e.g. `openapi-3.1`) |
| `detect(payload) → DetectionResult` | abstract | cheap content sniff with a `0.0`–`1.0` confidence; never raises |
| `parse(raw) → native_ast` | abstract | raw source text → the format's parse tree |
| `normalize(native_ast) → CanonicalApi` | abstract | map onto the [canonical model](./canonical_model.md); usually delegates to a [Normalizer](./normalizer_spi.md) via `_normalize_via_registry` |
| `fingerprint(model) → str` | default | stable `sha256:` over the normalized model (excludes the `raw` fidelity bag) |
| `diff(a, b) → CanonicalDiff` | default | by-stable-key structural diff (re-ordering is **not** a diff) |
| `lint(model) → LintReport` | default | empty report; override for a format-native rule pack |

Because `fingerprint`/`diff`/`lint` work on the *canonical* model, they are
written **once** here and work for every paradigm. An adapter overrides one only
when it has a format-native rule (the OpenAPI adapter delegates `lint` to the
existing `schema_lint.lint_openapi_spec`).

## Registry

```python
from app.import_source import (
    describe_import_sources,          # → [ImportSourceDescriptor]  (the "source list")
    available_import_sources,         # → ["openapi", "sample", ...]
    get_import_source,                # key → adapter instance | None
    detect_import_source,             # DetectionInput → (adapter, DetectionResult) | None
    detect_import_source_candidates,  # DetectionInput → [(adapter, DetectionResult)] ranked
)
```

Built-in adapters self-register via the `register=True` subclass flag and are
imported on demand by `load_builtin_import_sources()` (called by the registry
lookups), so a consumer never has to import each adapter module to enumerate the
source list.

## Format auto-detection (MFI-1.5)

`app.format_detection.detect_format(DetectionInput) → FormatDetection` answers
"what format is this document?" without the user knowing. It ranks two kinds of
detector together — highest confidence wins:

- **Registered adapters** via `detect_import_source_candidates` — *importable*
  matches (an adapter can parse/normalize them today, e.g. OpenAPI).
- **Standalone marker sniffers** in `format_detection` for the formats whose full
  adapters arrive in later epics (RAML, API Blueprint, Smithy, TypeSpec, WSDL,
  OData, AsyncAPI, protobuf, Avro, GraphQL). These report `importable=False`.

The sniffers are deliberately **not** registered as no-op `ImportSource` adapters,
which would pollute the source list (UI cards / CLI `import --list`) with formats
that cannot be imported yet. When a format epic ships a real adapter, its
`detect()` supersedes the sniffer (dedup keeps the importable candidate).

`FormatDetection` carries the best `detected` candidate, all ranked `candidates`,
and an `ambiguous` flag (plus the close `ambiguous_candidates` cluster) when the
two leading formats tie within `DEFAULT_AMBIGUITY_MARGIN` — so the importer can
prompt the user instead of guessing. `POST /v1/import/detect` exposes it over REST.

## Implementing an adapter

```python
class FooImportSource(ImportSource, register=True):
    key = "foo"
    label = "Foo"
    description = "Import a Foo description."
    icon = "file-code"
    paradigm = ApiParadigm.RPC
    input_kinds = (InputKind.FILE, InputKind.PASTE)
    formats = ("foo-1",)

    def detect(self, payload): ...        # → DetectionResult(confidence=…, format="foo-1")
    def parse(self, raw, *, source_label=None): ...   # → native AST
    def normalize(self, native_ast, *, include_raw=True):
        return self._normalize_via_registry("foo-1", native_ast, include_raw=include_raw)
    # fingerprint / diff / lint inherited unless the format needs its own.
```

## Built-in adapters

- **`openapi`** (`OpenApiImportSource`) — the reference adapter; the existing
  OpenAPI/Swagger import path refactored behind the SPI. `parse` reuses the
  pipeline's JSON/YAML loader; `normalize` delegates to the registered OpenAPI
  normalizer; `lint` delegates to the OpenAPI linter. Detection recognizes both
  OpenAPI 3.x and Swagger 2.0; Swagger 2.0 *normalization* awaits its own
  normalizer (a later format epic) and raises a clear `ImportSourceError` until
  then. Wrapping is behavior-preserving — the same parser/normalizer/linter run
  (generalizing the job engine onto adapters is MFI-1.2).
- **`sample`** (`SampleImportSource`) — a no-op reference adapter that registers
  and appears in the source list with no engine/wizard changes (the acceptance
  adapter, and the smallest worked example of the contract).
