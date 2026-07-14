# Format lint capability matrix (CLX-2.4)

> **Status:** published coverage matrix — `src/app/format_lint_capabilities.py`
> **Issue:** [#4854](https://github.com/apiome/apiome/issues/4854) ·
> **Epic:** CLX-EPIC-2 (#4845)

Catalog quality should not vary arbitrarily by input format. This module publishes a
deterministic matrix of every sniffed / importable format and classifies each as:

| Mode | Meaning |
|------|---------|
| `native` | A format-specific rule pack (or OpenAPI `schema_lint`) is registered |
| `adapted` | Only external adapters cover the format (no native pack) |
| `unsupported` | No format pack and no adapter — common pack only when importable |

Live state is derived from `available_lint_formats()` and `available_adapters()`, so the
matrix cannot drift from registrations.

## Planned packs (linked, not duplicated)

These formats stay `unsupported` (or common-pack-only when importable) until their MFI
lint-pack issues land:

| Format | Issue |
|--------|-------|
| Smithy | [#3810](https://github.com/apiome/apiome/issues/3810) |
| RAML | [#3801](https://github.com/apiome/apiome/issues/3801) |
| TypeSpec | [#3796](https://github.com/apiome/apiome/issues/3796) |
| Avro | [#3786](https://github.com/apiome/apiome/issues/3786) |
| OData | [#3779](https://github.com/apiome/apiome/issues/3779) |
| API Blueprint | [#3806](https://github.com/apiome/apiome/issues/3806) |
| WS-I / WSDL | [#3791](https://github.com/apiome/apiome/issues/3791) |

CLX-2.4 does **not** re-implement those packs or their parsers/normalizers.

## Discovery API

```
GET /v1/lint/format-capabilities
```

Returns every matrix row (`format`, `mode`, `importable`, `nativePack`,
`adaptedScanners`, `commonPackOnly`, `relatedIssues`, `notes`).

## Related evidence

- Buf lint (`buf.lint`) and GraphQL ESLint (`graphql.eslint`) run through the
  [external-linter adapter SPI](./external_linter_adapter.md) and write CLX-1.1 evidence.
- Revision coverage on `GET …/lint/evidence` uses
  `expected_scanners_for_catalog_format(source_format)` so absent adapters read as
  `not_run` / `unavailable`, never as clean.
