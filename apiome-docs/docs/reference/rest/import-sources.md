---
title: "Import sources"
description: "REST endpoints tagged import-sources: 4 operations."
sidebar_position: 27
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `import-sources` · 4 operations

## `POST /v1/import/detect` {#detect-import-format-v1-import-detect-post}

**Auto-detect a document's import format**

Sniff a document's format (MFI-1.5) by polling every registered adapter and the built-in format sniffers; the highest-confidence match wins. Recognized-but-not-yet-importable formats (RAML, AsyncAPI, GraphQL, …) are reported with ``importable: false`` so the importer can name the format. When two formats tie within the ambiguity margin, ``ambiguous`` is true and ``ambiguous_candidates`` lists the choices to prompt for.

Operation id: `detect_import_format_v1_import_detect_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for auto-detect a document's import format.

- `application/json` — [`DetectFormatRequest`](#schema-detectformatrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for auto-detect a document's import format. | `application/json` [`DetectFormatResponse`](#schema-detectformatresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/import/format-capabilities` {#get-format-capability-registry-v1-import-format-capabilities-get}

**Get the source-format capability & parsing-limit registry**

Return the versioned source-format capability registry (CPDO-2.4): one entry per registered import source — the native hierarchy its analyzer models, the quality of the source locations it can point at, the value visibility it can ever carry, the grammar it knowingly does not read, how much survives the projection onto the canonical model, and whether the format converts — each stamped with the analyzer key, analyzer version and underlying tool versions that back the claim. The snapshot also carries the reviewed explanation for every way a detail can be absent, and the map from a stored payload-analysis reason code onto those categories. Exactly one category means the source material is missing; a parser limit, a capability boundary, an analyzer failure and a redaction each mean something else. This is static reference data — the same for every tenant and every item — so the UI can fetch it once and cache it by ``version``.

Operation id: `get_format_capability_registry_v1_import_format_capabilities_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get the source-format capability & parsing-limit registry. | `application/json` [`FormatCapabilitySnapshot`](#schema-formatcapabilitysnapshot) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/import/format-capabilities/{format_key}` {#get-format-capability-v1-import-format-capabilities-format-key-get}

**Get one source format's capability entry**

Return the capability & parsing-limit entry for a single source format (CPDO-2.4). **Always resolves**: a reviewed format returns its reviewed entry, any other registered adapter returns one derived from the adapter itself, and a key no adapter is registered under returns an ``unknown_format`` entry that claims nothing about the format. That last case is deliberate — a catalog item can name an adapter that was later retired, and a 404 there would leave the UI with exactly the "no details" dead end this registry exists to remove. A key that could never have been registered (wrong character class, or over 64 characters) is a 422 rather than an echo.

Operation id: `get_format_capability_v1_import_format_capabilities__format_key__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `format_key` | path | string | yes | Path parameter identifying the format key segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get one source format's capability entry. | `application/json` [`FormatCapability`](#schema-formatcapability) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/import/sources` {#list-import-sources-v1-import-sources-get}

**List import sources**

Enumerate every registered import-source adapter (MFI-1.1 registry). Drives the ImportDialog source cards (MFI-1.3) and the CLI format list (MFI-1.4): each descriptor carries the Lucide icon, label, description, and the input kinds (file/url/paste/discovery) its card/verb should use.

Operation id: `list_import_sources_v1_import_sources_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list import sources. | `application/json` [`ImportSourceListResponse`](#schema-importsourcelistresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `DetectFormatRequest` {#schema-detectformatrequest}

A document (plus optional hints) to auto-detect the format of.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `text` | string or null | no | Raw document text to sniff (the primary signal). |
| `filename` | string or null | no | Optional filename hint (extension-based signals). |
| `content_type` | string or null | no | Optional MIME type hint. |
| `url` | string or null | no | Optional source URL hint. |
| `document_base64` | string or null | no | Standard base64 of an uploaded archive (.zip / .tar.gz) for multi-file intake (MFI-29.1). When present and the payload is an archive, the root document is auto-detected (or chosen via ``archive_root``). |
| `archive_root` | string or null | no | Explicit module-relative root path inside an uploaded archive. |

### `DetectFormatResponse` {#schema-detectformatresponse}

The auto-detection verdict for a document.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `matched` | boolean | yes | Whether any detector recognized the document. |
| `detected` | `FormatCandidateModel` or null | no | The best candidate, or null when nothing matched. |
| `ambiguous` | boolean | yes | True when leading formats tie within the ambiguity margin (prompt the user). |
| `candidates` | array of `FormatCandidateModel` | no | All distinct-format candidates, ranked. |
| `ambiguous_candidates` | array of `FormatCandidateModel` | no | The close cluster to choose between when ambiguous; empty otherwise. |
| `archive_root` | string or null | no | When the request carried an archive, the chosen root member path. |
| `archive_members` | array of string | no | Sorted member paths when an archive was unpacked for detection. |

### `FormatCapability` {#schema-formatcapability}

The versioned capability & parsing-limit entry for one source format (CPDO-2.4).

Everything a reader needs to know what apiome will *ever* be able to say about a document
of this format, before opening one: the native hierarchy it preserves, the source pointers
it can offer, the values it can carry, the grammar it does not read, what survives
normalization, and whether it converts — each backed by the analyzer and tool versions in
:attr:`analyzer`.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `format` | string | yes | Stable import-source registry key (e.g. ``edix12``). |
| `label` | string | yes | Human label for the format. |
| `paradigm` | string or null | no | The canonical paradigm the adapter produces, or null for an unknown format. |
| `provenance` | `CapabilityProvenance` | yes | Whether this entry is reviewed, derived from the adapter, or a declaration that the format is unknown. |
| `availability` | `FormatAvailability` | yes | Whether this format can be imported and analysed in the current runtime. |
| `unavailable_reason` | string or null | no | Why the format is unavailable here, or null when it is available. |
| `native_hierarchy` | `NativeHierarchy` | yes | Native Hierarchy. |
| `native_hierarchy_note` | string | yes | One line on what the tree's node vocabulary actually is. |
| `analyzer` | `AnalyzerEvidence` | yes | The analyzer and tool versions backing every claim in this entry. |
| `source_location` | `SourceLocationSupport` | yes | The best source pointer nodes from this format can carry. |
| `value_visibility` | `ValueVisibilitySupport` | yes | The value material this format's analysis can ever carry. |
| `supported_constructs` | array of string | no | Construct keys the analyzer models, sorted. Their absence from a tree means they were not in the source. |
| `unsupported_constructs` | array of string | no | Construct keys the analyzer knowingly does not model, sorted — the format's unsupported grammar. Their absence from a tree means nothing about the source. |
| `limits` | map of integer | no | The numeric parsing limits in force (node/depth budgets, value preview length), so a bounded record is distinguishable from a small one. |
| `canonical_projection` | `CanonicalProjectionSupport` | yes | Canonical Projection. |
| `conversion` | `ConversionSupportEntry` | yes | Whether this format participates in the conversion graph, and by which route. |
| `version_coverage` | `VersionCoverage` | yes | Which versions of this format are read and written, which one an export produces by default, and where a version is reached through a projection or a downgrade (FMT-3.8). A claim about *versions*: how completely the format's constructs are modelled is what ``unsupported_constructs`` and ``canonical_projection`` above answer. |
| `notes` | array of string | no | Reviewed prose about this format's boundaries, in reading order. |
| `registry_version` | string | yes | The registry contract version this entry belongs to. |
| `review_date` | string | yes | When this entry's claims were last reviewed. |

### `FormatCapabilitySnapshot` {#schema-formatcapabilitysnapshot}

The full, deterministic registry view exposed to the REST contract + UI (CPDO-2.4).

Derived from the (deterministic) import-source registry and the static seeds, so identical
inputs yield an identical snapshot — safe to cache by :attr:`version` and to mirror in a
TypeScript contract.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `version` | string | yes | The registry contract version (:data:`REGISTRY_VERSION`). |
| `review_date` | string | yes | When the registry's seeds/explanations were reviewed. |
| `analysis_schema_version` | string | yes | The payload-analysis contract version this registry's reason mapping pairs with, so a reader can tell the two apart when either moves. |
| `absence_categories` | array of string | yes | The canonical set of absence-category strings, sorted. Contract tests reject any category outside this set. |
| `absences` | array of `AbsenceExplanation` | yes | The reviewed explanation for each absence category, in vocabulary order. |
| `reason_absence_categories` | map of string | yes | Analysis reason code → absence category, for every reason code CPDO-1.1 can store. |
| `formats` | array of [`FormatCapability`](#schema-formatcapability) | yes | One capability entry per registered import source, in key order. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `ImportSourceListResponse` {#schema-importsourcelistresponse}

The list of registered import sources, for source-card / CLI enumeration.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `sources` | array of `ImportSourceDescriptor` | no | Every registered adapter's descriptor, sorted by key. |
