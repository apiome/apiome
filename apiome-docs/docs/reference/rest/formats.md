---
title: "Formats"
description: "REST endpoints tagged formats: 1 operation."
sidebar_position: 24
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `formats` · 1 operation

## `GET /v1/formats/matrix` {#get-format-matrix-v1-formats-matrix-get}

**Get the format support matrix**

Return one row per format Apiome reads or writes (FMT-1.5) — the single machine-readable answer to "what do you support?". Each row carries the registry key, label and paradigm; the import half (accepted input kinds, live-discovery capability, remote ``$ref`` support, and whether an import mints a publishable Project or a catalog item); the export half (the emitter's target key, output format, multi-file flag and capability profile); the declared version coverage (every format key the adapter emits, so a specific version can be requested); the advisory file extensions; the external toolchain the format hard-requires and whether **this** deployment has it; and the source-format capability registry's boundary summary. Optional ``paradigm`` and ``direction`` filters narrow the result and are echoed back in ``filters``, with ``counts`` computed over the rows actually returned, so a filtered table is never mistaken for the whole surface. This is the same payload the generated supported-formats documentation page is rendered from and the ``apiome formats`` command prints, so the three cannot disagree. It is static reference data — identical for every tenant — and safe to cache by ``version``.

Operation id: `get_format_matrix_v1_formats_matrix_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `paradigm` | query | [`ApiParadigm`](#schema-apiparadigm) or null | no | Return only formats in this paradigm (``rest``, ``rpc``, ``event``, ``graph``, ``data_schema``, ``agent``). Omit for every paradigm. |
| `direction` | query | [`DirectionFilter`](#schema-directionfilter) or null | no | Return only formats with this capability: ``import`` for everything Apiome can read, ``export`` for everything it can write, ``both`` for the formats that round-trip. Omit for every direction. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the format support matrix. | `application/json` [`FormatMatrixResponse`](#schema-formatmatrixresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `ApiParadigm` {#schema-apiparadigm}

The high-level interaction style a format belongs to.

A format declares exactly one paradigm; it selects which canonical fields
are load-bearing (for example ``channels`` matter for ``EVENT`` but not for
``REST``) and drives browse/search facets.

Type: enum `"rest"`, `"rpc"`, `"event"`, `"graph"`, `"data_schema"`, `"agent"`

### `DirectionFilter` {#schema-directionfilter}

The ``direction`` query filter: *which capability must a row have?*

Deliberately a different vocabulary from :class:`FormatDirection`, which states what a format
**is**. ``import`` here selects every row Apiome can read — including the ones it can also
write — so the filter reads as a capability question rather than an exact-match on the row's
own direction.

Type: enum `"import"`, `"export"`, `"both"`

### `FormatMatrixResponse` {#schema-formatmatrixresponse}

The format matrix: one row per format Apiome reads or writes.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | string | yes | Contract version of this payload (:data:`FORMAT_MATRIX_VERSION`). Bumped only when a field is removed or changes meaning — never for a new format — so a response is safe to cache by it. |
| `capability_registry_version` | string | yes | The source-format capability registry version the ``capability`` summaries were read from. |
| `filters` | `FormatMatrixFilters` | yes | The filters applied to this response. |
| `counts` | `FormatMatrixCounts` | yes | Headline counts over the rows in this response. |
| `formats` | array of `FormatMatrixRow` | no | One row per format, ordered by label then key — the same order the generated supported-formats page and the CLI table use. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
