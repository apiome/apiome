# Fidelity / completeness gap analyzer (MFI-22.3)

`app.fidelity` reads the output of a canonical-model → OpenAPI conversion and produces
a **fidelity report**: what the converted spec will contain, what the conversion had
to *invent*, and what it *lost*. It is the preview a user must see before committing a
conversion (MFI-22.4), and the score/report a convert job persists (MFI-22.5).

It is the consumer of the two trails the conversion leaves behind:

- the **provenance** the emitter records per emitted value
  (`source` / `inferred` / `default`, see [`emitter_spi.md`](./emitter_spi.md)); and
- the **losses** each paradigm projection declares
  (`inferred` / `n/a`, see [`projection_strategies.md`](./projection_strategies.md)).

The analyzer is **pure and deterministic**: no DB or network, a fixed checklist order,
sorted+capped examples, so the same `(CanonicalApi, EmitResult)` always yields an equal
report.

## Usage

```python
from app.openapi_emitter import OpenApiEmitter
from app.fidelity import analyze_fidelity

result = OpenApiEmitter().emit(api)          # MFI-22.1 / 22.2
report = analyze_fidelity(api, result)       # MFI-22.3

report.score   # 0-100 weighted fidelity score
report.grade   # A-F, house bands (reuses MFI-4.2 GRADE_THRESHOLDS)
report.tier    # high / medium / low — drives the UI warning strength
report.items   # the completeness checklist, one row per OpenAPI construct
report.losses  # projection losses, carried through from the EmitResult
```

## The completeness checklist

One `ChecklistItem` per load-bearing OpenAPI construct, in a fixed order, each tagged
with a `Coverage`:

| Coverage | Meaning |
|----------|---------|
| `present` | carried faithfully from the source (every instance `source`) |
| `inferred` | emitted, but *derived* by the conversion (synthesized binding/id, defaulted status/media type) |
| `partial` | some instances faithful, others inferred/absent |
| `missing` | an OpenAPI construct the source *could* have carried, but this conversion has none of |
| `n/a` | no counterpart for this source — the canonical model does not retain it (contact/license/examples/security/externalDocs) or the paradigm has none of it (a schema-only source has no operations) |

Constructs scored: `info` (title/version/description/contact/license), `servers`,
`paths`+methods, operation id/summary, parameters, `requestBody`, `responses`,
`components.schemas`, security, `tags`, `examples`, `externalDocs`, `deprecated`.

Each row also carries a `count`, up to three example coordinates, a `weight` (how
load-bearing the construct is), and a human-readable `reason`.

## Score, grade & tier

The score starts at 100 and subtracts:

- a **checklist penalty** per row — `weight ×` a coverage factor: `present`/`n/a` cost
  nothing (faithful, or nothing was representable to lose), `inferred`/`partial` cost
  half the weight, `missing` costs the full weight; plus
- a **per-loss penalty** — each `n/a` projection loss (a source capability with *no*
  OpenAPI representation: a pub/sub action, a subscription, streaming) costs a fixed
  amount. `inferred` losses are *not* charged here, because they are already reflected
  in the `paths` row's `inferred` coverage (no double-counting).

The grade is derived from the score with the same house bands the OpenAPI/MCP lint
scores use (`app.schema_lint.GRADE_THRESHOLDS`: A≥90 … F<60). The tier is a coarse
three-band signal off the score (`high` ≥ 85, `medium` ≥ 60, else `low`) that the
conversion preview uses to scale its warning.

## Fidelity by paradigm (illustrative)

| Source | Typical tier | Why |
|--------|--------------|-----|
| OData / REST | **high** | routes, responses, media types, schemas all faithful; near-lossless |
| gRPC without HTTP annotations | **medium** | paths synthesized (`inferred`); media types + status codes defaulted (`inferred`) |
| AsyncAPI / event | **low** | routes non-normative; no responses; pub/sub action + channel bindings are `n/a` losses |
| Avro / data-schema | **high** | components-only conversion is clean; `paths` is `n/a`, not a loss |
