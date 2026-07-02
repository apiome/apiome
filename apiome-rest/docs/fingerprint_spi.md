# Canonical Fingerprint SPI (MFI-3.1)

> **Status:** SPI + format-agnostic implementation — `src/app/fingerprint.py`
> **Issue:** [#3742](https://github.com/objectified-project/objectified/issues/3742) ·
> **Epic:** MFI-EPIC-3 (#3718) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Change detection has to work the **same way for every format** — REST, RPC,
event, graph, data-schema — while still honoring each format's own notion of
identity. The fingerprint module gives you both:

- a **format-agnostic semantic fingerprint** of the [canonical model](./canonical_model.md)
  (`CanonicalApi`, MFI-2.1), and
- a **per-format hook** so a format can additionally expose its own canonical
  hash (Avro Parsing Canonical Form, a protobuf descriptor-set hash, XSD QName
  canonicalization, …).

```
 CanonicalApi ──normalize_ordering──▶ scrub descriptions/raw ──▶ JSON(sort_keys) ──sha256──▶ semantic fingerprint
              └─(format hook, if registered)──────────────────────────────────────────────▶ format_hash
```

Everything here is **pure** (no DB, no network): it takes an in-memory model and
returns hex digests, so it is cheap to call from the import pipeline, a version
roll (MFI-3.4), or a diff (MFI-3.2).

## The semantic fingerprint

`canonical_fingerprint(api: CanonicalApi) -> str` is a SHA-256 over a
*canonicalized* projection of the model. Canonicalization makes the digest
invariant to everything that is **not** the artifact's contract:

1. **Order normalization.** Identity-keyed collections (services, operations,
   parameters, messages, headers, channels, types, fields) are sorted by `key`
   via [`normalize_ordering`](./normalizer_spi.md). Order-meaningful collections —
   `enum_values` (ordinals), `union_members` (Avro resolution order),
   `Server.variables` — are **left in place** and remain load-bearing.
2. **Descriptive scrub.** Keys that are documentation/presentation, not contract,
   are dropped before hashing: every `description`, the artifact `title`, and the
   native `raw` AST (which is comment- and order-laden and exists only for
   round-tripping and per-format lint).
3. **Stable serialization.** The projection is dumped with `json.dumps(...,
   sort_keys=True, separators=(",", ":"))` so the byte stream is identical across
   runs and machines.

What is **kept** (and therefore flips the fingerprint when it changes): names,
keys, type references and nullability/list nesting, `field_number`, `default`,
constraints, enum values/ordinals, union members, http verb/route, channel
address/bindings, `deprecated` flags, and the `extras` fidelity bags. `extras`,
`bindings`, `payload_schema`, and literal `default`/`value`/`enum` values are
treated as **opaque** — carried into the hash verbatim, never recursed into — so
semantic data that merely *contains* a `description`-named member is preserved
rather than mistaken for a canonical doc field and stripped.

```python
from app.fingerprint import canonical_fingerprint, canonical_payload

fp = canonical_fingerprint(model)        # 64-char lowercase hex sha256
payload = canonical_payload(model)       # the exact dict that was hashed (for inspection / diff reuse)
```

**Guarantees** (asserted in `tests/test_fingerprint.py`):

- identical artifacts → identical fingerprint across independent runs;
- a doc-only edit (descriptions/title/`raw`) → **same** fingerprint;
- a source-order difference → **same** fingerprint;
- any single structural change (add/remove/retype a field, change a default or
  constraint, change a verb, add an enum value, deprecate, change `extras`) →
  **different** fingerprint.

The algorithm is labeled `sha256-canonical-v1` (`FINGERPRINT_ALGORITHM`), recorded
next to every digest so stored fingerprints can be re-validated and migrated if
the canonicalization rules ever change.

## The per-format hash hook

Some formats define a canonical hash of their own that captures format-specific
identity better than the structural projection can. The SPI mirrors the
[normalizer registry](./normalizer_spi.md):

```python
class FingerprintHasher(ABC):
    format: ClassVar[str]      # e.g. "avro" — matched against CanonicalApi.format
    algorithm: ClassVar[str]   # e.g. "avro-parsing-canonical-form-sha256"

    @abstractmethod
    def hash(self, api: CanonicalApi) -> str: ...
```

A format epic registers a hasher — `class AvroPcfHasher(FingerprintHasher,
register=True): ...`, or `register_fingerprint_hasher(cls)` — and it is looked up
by `get_fingerprint_hasher(format_key)`. A hasher must be **deterministic and
side-effect free** and derive its hash only from the model (typically from
`api.raw` or a re-rendered canonical form).

`fingerprint(api: CanonicalApi) -> FingerprintResult` is the dispatcher. It
**always** computes the semantic fingerprint, and **additionally** attaches the
format hash when a hasher is registered for `api.format`:

```python
from app.fingerprint import fingerprint

result = fingerprint(model)
result.fingerprint        # semantic sha256 (always present) — change detection keys on this
result.algorithm          # "sha256-canonical-v1"
result.format             # the artifact's format key
result.format_hash        # format-specific hash, or None when no hasher is registered
result.format_algorithm   # e.g. "avro-parsing-canonical-form-sha256", or None
```

`FingerprintResult` is a Pydantic model, so MFI-3.4 persists it as JSONB next to
the version row.

## Avro PCF vs. the semantic hash — why both

Avro's **Parsing Canonical Form** (PCF) is a normalization of a schema that, by
design, **strips `doc`, aliases, and defaults**, then hashes the result
(CRC-64-AVRO or SHA-256) — see the
[Avro 1.12 specification](https://avro.apache.org/docs/1.12.0/specification/).
PCF answers *"are these two schemas wire/parse-compatible for read/write
resolution?"* Two schemas that differ only in their defaults, aliases, or
documentation share **one** PCF — which is exactly right for Avro resolution.

The semantic fingerprint answers a **different** question: *"did anything about
this artifact change since last import?"* For that, a changed default **is** a
change (it alters behavior and warrants a new dated version), and so the semantic
fingerprint deliberately **keeps** defaults (and `deprecated`, constraints, etc.)
that PCF discards.

So the two are complementary and are surfaced side by side:

| | strips defaults | strips aliases | strips doc/descriptions | answers |
|---|---|---|---|---|
| **Semantic fingerprint** (`fingerprint`) | no | no | yes | did the contract change? (versioning/diff) |
| **Avro PCF** (`format_hash`, when registered) | yes | yes | yes | are these schemas parse-compatible? |

A future Avro format epic registers an `FingerprintHasher` that emits the PCF
hash as `format_hash`; the semantic fingerprint continues to drive
version-on-change. The same pattern applies to a protobuf `FileDescriptorSet`
hash and XSD QName canonicalization.

## Reuse note

This generalizes the MCP catalog's report fingerprint (V2-MCP-EPIC-18.1 /
`schema_lint._report_fingerprint`, `mcp_score._report_fingerprint`) from
"hash of a lint report" to "hash of the canonical model", using the same
`hashlib.sha256` + `json.dumps(sort_keys=True, separators=(",", ":"))`
deterministic-serialization recipe so the two remain comparable in spirit.
```
