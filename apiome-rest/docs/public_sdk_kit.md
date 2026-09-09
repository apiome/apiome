# Public client kit (SDK-3.3, #4493)

The consumer-facing half of the SDK surface: a **Get SDK** download and per-operation snippet
tabs on the public browse portal, both opened by one per-project setting that is **off by
default**.

Modules:

- `app.sdk_kit` — pure builder (no FastAPI/db imports): what an archive contains and how it is
  named. Reuses `app.snippet_render` for the code and `app.zip_bundle` for the bytes.
- `app.sdk_kit_routes` — the two HTTP surfaces described below.

## What the download actually is

**Not a generated client library.** The original SDK-3.3 scope served "the latest generated
artifact" from the SDK-1.1 artifact store. SDK-1.1 (#4481), the generator SPI (#4482), both
language generators (#4485/#4486) and the dashboard/CLI surfaces (#4491/#4492) were all closed
**not-planned**, so there is no artifact to serve and no generator to make one.

What *did* ship is the SDK-2.3 snippet service, which renders runnable per-operation code
directly from the persisted canonical model. The kit packages that: a `README.md`, the published
contract, `manifest.json`, and one runnable snippet per operation per language.

```
widgets-1.0.0-sdk.zip
├── README.md                    install + auth legend + per-operation usage
├── manifest.json                contents + provenance (never lists itself)
├── spec.json                    the captured contract, verbatim
└── snippets/
    ├── ts/getWidget.ts
    ├── python/getWidget.py
    └── curl/getWidget.sh
```

It is built **per request**, not stored — so there is no artifact lifecycle to retain, expire or
invalidate, and nothing to garbage-collect.

## The gate

One setting controls the whole surface: **`publicSdkEnabled`** on the SDK-3.4
`sdk.generation-settings.v1` body (see `sdk_generation_settings.md`), read through
`app.sdk_generation_settings_store.load_public_sdk_enabled`.

- It merges tenant → project **key by key** like every other setting, so a workspace can open
  every project at once and a single project can override in either direction.
- It is the one setting that is an **access control** rather than branding, so it defaults to
  `false` rather than `null`: "not configured" and "not allowed" are the same answer, and it is
  the safe one. An unreadable settings row also reads as `false` — **the gate fails closed**.

**A project that has not opted in gets a 404**, identical to the one an unpublished, private or
unknown version gets. A distinct `403` would confirm that the project exists and merely declined,
which is exactly what the gate exists to hide. The browse panel needs no distinction either: it
renders nothing when the info call fails.

This gate also applies to the **anonymous** SDK-2.3 snippet route (`…/snippets/{operation_id}`),
which is part of the same consumer-facing surface — see `snippet_service.md`. The
**authenticated** snippet route is unaffected: it is tenant-scoped, not public exposure.

## Endpoints

Both are anonymous, slug-addressed, resolved through
`app.export_source.load_public_export_source`, and share the MFX-7.3 public-export per-IP rate
limit (429 when exceeded).

### Info

```
GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/sdk
```

Everything the browse Get SDK panel needs in one call: the slug coordinates, the languages with
their install lines, the **resolved package names** the tenant's SDK-3.4 patterns produce (with
the command that installs each), the operation counts, the licence header, the merged settings'
fingerprint, and the download's filename.

It **counts** rather than builds — `app.sdk_kit.summarize_kit` walks the model applying the same
eligibility rule the builder does (an operation needs an HTTP method and path), so the numbers
match the archive without rendering three snippets per operation for a call that would throw the
result away.

### Download

```
GET /v1/browse/tenants/{t}/projects/{p}/versions/{v}/sdk/download
```

`application/zip` with `Content-Disposition: attachment`, `Content-Length`, `Digest` /
`X-Content-SHA256` over the exact bytes, and `X-Apiome-Version-Record-Id` /
`X-Apiome-Kit-Schema` so a consumer can identify what they downloaded without unzipping it.
Serves a strong `ETag` with `If-None-Match` → 304 and `Cache-Control: public, max-age=300`, and
reuses the public-export size cap (413 above it).

## Determinism

Identical inputs produce **byte-identical** archives, which is what lets an unstored download
carry a content-addressed `ETag`:

- entries are written through `app.zip_bundle.write_zip_entry` with a pinned DOS epoch (a zip
  stores an mtime per entry, so an unpinned archive differs on every call);
- entries are emitted in sorted order, with `manifest.json` last;
- the snippets inherit `app.snippet_render`'s fixed defaults and seed-0 instance synthesis.

A tenant changing its branding therefore changes the bytes, the digest and the `ETag` together —
no cache-key work is needed.

## Provenance

`manifest.json` carries a `provenance` block mirroring the export bundle's shape:

| Field | Meaning |
| --- | --- |
| `version_record_id` | The resolved revision (`versions.id`) — the coordinate that cannot be re-pointed, unlike a version label |
| `version_label` | The revision's source-declared label |
| `source_format` | The captured contract's format key |
| `renderer` | The renderer and kit schema that produced the code |
| `apiome_version` | The API version that built it |
| `settings_fingerprint` | The merged SDK-3.4 settings, so a changed kit is attributable to changed branding rather than to a changed API |

Every entry is listed in `files[]` with its size and SHA-256. The manifest never lists itself — a
table of contents containing its own digest could not be verified.

## Limits and degradation

- **Operations with no HTTP binding** (gRPC methods, GraphQL fields, event operations) have no
  snippet defined. They are recorded in the manifest's `skipped` list with a reason and named in
  the README, never fatal: a kit covering an API's twelve REST operations is worth shipping even
  when its two subscriptions cannot be rendered.
- **`MAX_KIT_OPERATIONS` (250)** bounds the work, because the kit is built per request on an
  anonymous route. The cap counts only *renderable* operations, so a model's non-HTTP operations
  never push its REST ones out of the kit. Past it the manifest sets `truncated` and the README
  says so.
- **A revision with no captured source** still yields a kit — the snippets are the point; the
  contract is shipped when there is one.
- The contract's filename comes from the format key for text formats that are neither JSON nor
  YAML (`spec.graphql`, `spec.proto`, …); everything else is sniffed to `spec.json` or
  `spec.yaml`, because the JSON/YAML family shares one format key per *specification*, not per
  serialization.
