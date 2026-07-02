# Paradigm projection strategies (MFI-22.2)

> **Status:** SPI + per-paradigm strategies — `src/app/projection.py`
> **Issue:** [#4003](https://github.com/objectified-project/objectified/issues/4003) ·
> **Epic:** MFI-EPIC-22 (#4000) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

OpenAPI is a **REST** vocabulary — it describes *paths*, *HTTP verbs*, and
*status-coded responses*. A [`CanonicalApi`](./canonical_model.md) from a REST source
maps onto it one-to-one, but a model from any *other* paradigm has no native
path/verb/response. Each therefore needs an **explicit, documented projection** that
emits what it can and **declares what it loses**.

A `ProjectionStrategy` is the pluggable unit that does this. The
[`OpenApiEmitter`](./emitter_spi.md) selects one from the model's `ApiParadigm` via
`get_projection(...)` and consults it — once per operation — to resolve the
`(method, path)` binding (or to learn the operation has no OpenAPI representation) and
to gather `x-` extensions and document-level notes. Every strategy records its
**losses** on a `LossTracker` so the fidelity analyzer (MFI-22.3) can show what each
projection dropped or inferred rather than discarding it silently.

```
CanonicalApi(paradigm) ─get_projection→ ProjectionStrategy
                                            │  route(op, service, losses) → RouteBinding | None
                                            └  document_extensions(api, losses) → {x-…}
```

## The contract

```python
class ProjectionStrategy:
    paradigm: ClassVar[ApiParadigm]           # registry key

    def route(self, operation, service, losses) -> RouteBinding | None: ...
    def document_extensions(self, api, losses) -> dict: ...
```

* `route` returns a `RouteBinding(method, path, from_source, extensions)` — or `None`
  when the operation has **no** OpenAPI representation (it is dropped from `paths`; the
  strategy records an `n/a` loss first so the drop is surfaced). `from_source`
  distinguishes a binding taken from the model (a REST verb/route, an RPC `http` trait)
  from a synthesized one (which the emitter tags `inferred`).
* `document_extensions` returns document-root `x-` keys (e.g. an event projection's
  low-fidelity caveat) and may record document-level losses.

The default `route` **is** the REST/best-effort projection — honor an operation's own
HTTP binding, else synthesize a `POST` to a path derived from its key — so `REST` and
`DATA_SCHEMA` need no override.

### Registration & lookup

```python
class MyProjection(ProjectionStrategy, register=True):  # auto-registers on definition
    paradigm = ApiParadigm.RPC
    def route(self, operation, service, losses): ...

get_projection(ApiParadigm.RPC)   # -> RpcProjection()
```

## The strategies

| Paradigm | Strategy | Projection | `n/a` losses |
|----------|----------|------------|--------------|
| `rest` | `RestProjection` | identity — the operation's own `http_method`/`http_path`; missing → best-effort `POST /{key}` | — |
| `rpc` | `RpcProjection` | `google.api.http` / Smithy `http` from `extras` if present; else `POST /{Service}/{Method}` (gRPC-transcoding). Input → `requestBody`, output → `200`. | streaming (also `x-apiome-streaming`) |
| `graph` | `GraphProjection` | SOFA-style: query → `GET`, mutation → `POST` under `/graphql`; arguments → parameters | **subscriptions** (not emitted) |
| `event` | `EventProjection` | explicitly low-fidelity: each pub/sub op → a *non-normative* path (`x-apiome-event-action`) + a document-level `x-apiome-fidelity` caveat; payloads stay in `components.schemas` | pub/sub action, channel bindings, correlation ids |
| `data_schema` | `DataSchemaProjection` | components-only (types, no `paths`) — unless a service is present, then best-effort bindings | — |

**Agent descriptors (A2A/MCP)** normalize into the **RPC** paradigm (a skill/tool is a
request/response method with an input and output schema), so they are projected by
`RpcProjection` and need no separate strategy.

## `x-` extensions

Each nuance OpenAPI cannot model is surfaced as a vendor `x-apiome-*` extension
(the OpenAPI 3.1 meta-schema permits `^x-` keys), so it is visible in the document
*and* recorded as a loss:

| Extension | Where | Carries |
|-----------|-------|---------|
| `x-apiome-streaming` | operation | an RPC streaming cardinality (`client`/`server`/`bidirectional`) |
| `x-apiome-event-action` | operation | an event operation's pub/sub action (`publish`/`subscribe`) |
| `x-apiome-fidelity` | document root | `{paradigm, fidelity, recommended-mode, caveat}` for a low-fidelity projection |

## Purity & determinism

Every strategy is **pure**: given the same model it returns equal bindings and records
equal losses, performs no I/O, and is deterministic. `LossTracker.records()` returns
the losses sorted (by kind, subject, pointer, detail), so `EmitResult.losses` is
byte-stable across re-emissions.
