---
title: "Catalog"
description: "REST endpoints tagged catalog: 10 operations."
sidebar_position: 9
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `catalog` · 10 operations

## `GET /v1/catalog/{tenant_slug}` {#list-catalog-items-v1-catalog-tenant-slug-get}

**List Catalog Items**

List all catalog items for a tenant.

Returns the same envelope as ``GET /v1/projects/{tenant_slug}`` (so the Catalog screen can be
cloned from the Projects dashboard) restricted to the non-publishable slice, with each item
also carrying the latest revision's format/protocol/source provenance.

Supports authentication via:
- JWT token in Authorization header (Bearer token)
- API key in X-API-Key header

Args:
    tenant_slug: The tenant slug.
    include_deleted: Include rows with deleted_at set (for trash / restore flows).
    auth_data: Authentication data (injected by dependency).

Returns:
    List of catalog items for the tenant (active first when include_deleted is set).

Operation id: `list_catalog_items_v1_catalog__tenant_slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `include_deleted` | query | boolean | no | When true, include soft-deleted catalog items (active items listed first). |
| `identityGroupId` | query | string or null | no | When set, return only catalog items in this cross-format identity group (MFI-6.4). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list catalog items. | `application/json` array of [`CatalogItemSchema`](#schema-catalogitemschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/catalog/{tenant_slug}/analysis-metrics` {#record-catalog-analysis-metric-v1-catalog-tenant-slug-analysis-metrics-post}

**Record a privacy-safe catalog analysis metric**

Increment an in-process counter and emit a structured ``catalog.analysis`` log line for UI/ops telemetry (CPDO-4.2). Payload is a strict whitelist of kinds, controlled surface names, and integer/duration fields — never node names, values, or source content.

Operation id: `record_catalog_analysis_metric_v1_catalog__tenant_slug__analysis_metrics_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for record a privacy-safe catalog analysis metric.

- `application/json` — [`CatalogAnalysisMetricRequest`](#schema-cataloganalysismetricrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for record a privacy-safe catalog analysis metric. | `application/json` [`CatalogAnalysisMetricResponse`](#schema-cataloganalysismetricresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}` {#get-catalog-item-v1-catalog-tenant-slug-item-id-get}

**Get Catalog Item**

Get a specific catalog item by ID, with the MFI-23.9 detail enrichments.

Returns the MFI-23.2 list envelope plus a normalized-content ``summary`` (services/operations/
types/channels counts), a ``source`` material descriptor (both derived from the latest revision's
``format_metadata``) and, from MFI-25.2, a ``parsed`` list of paradigm-tagged entity groups derived
from the item's canonical model (``[]`` when no model can be reconstructed from the captured
source). A publishable Project is intentionally *not* returned here: only the non-publishable
slice is a catalog item, so requesting a Project's id (or an unknown id) yields 404.

Supports authentication via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item ID.
    auth_data: Authentication data (injected by dependency).

Returns:
    The catalog item details, including its normalized summary and source descriptor.

Operation id: `get_catalog_item_v1_catalog__tenant_slug___item_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get catalog item. | `application/json` [`CatalogItemDetailSchema`](#schema-catalogitemdetailschema) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/analysis` {#get-catalog-item-analysis-v1-catalog-tenant-slug-item-id-analysis-get}

**Get Catalog Item Analysis**

Return the full native payload analysis of a catalog item's latest revision (CPDO-1.1).

The detail read (``GET …/{item_id}``) embeds only the analysis *summary* — status and counts,
no payload material — so it stays cheap regardless of how large the analysed source was. This
endpoint serves the record itself: the native tree in the analyzer's own vocabulary (X12
interchange → functional group → transaction set → segment → element; copybook level → PIC →
OCCURS → 88-condition), its source locations, analyzer warnings, and the redaction metadata
stating what was withheld.

**Authorization.** The summary is readable by anyone who can read the catalog item; the tree is
gated on ``imports:view``, the permission that governs imported source material, because a
native tree is a structural description of the payload itself. ``valueVisibility`` may further
restrict what is returned — it can never widen it, since values the store never held cannot be
re-materialised.

**Absence is declared.** A revision imported before this contract existed, or one whose source
was never captured, returns a record with ``status: "unavailable"``, an empty tree, and a reason
code saying which. It never returns a fabricated tree.

Like the other catalog reads this is restricted to the non-publishable slice — a Project's id, or
an unknown id, yields 404 — and authenticated via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item ID (a project id).
    value_visibility: Optional read-time value-visibility restriction.
    max_nodes: Optional read-time node budget for a lazy fetch of an oversized tree.
    max_depth: Optional read-time depth budget, applied with ``max_nodes``.
    auth_data: Authentication data (injected by dependency).

Returns:
    The :class:`~app.payload_analysis.PayloadAnalysisRecord` for the item's latest revision.

Operation id: `get_catalog_item_analysis_v1_catalog__tenant_slug___item_id__analysis_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `valueVisibility` | query | string or null | no | Optional read-time restriction on observed payload values: none \| structural \| full. It can only narrow what the stored record carries, never widen it. |
| `maxNodes` | query | integer or null | no | Optional read-time node budget for a lazy first fetch of an oversized tree. Keeps the same breadth-first prefix write-time bounding keeps; truncation is reported on the record's metrics, never silent (CPDO-4.2). |
| `maxDepth` | query | integer or null | no | Optional read-time depth budget, applied with maxNodes (CPDO-4.2). |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get catalog item analysis. | `application/json` [`PayloadAnalysisRecord`](#schema-payloadanalysisrecord) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/conversions` {#get-catalog-conversion-history-v1-catalog-tenant-slug-item-id-conversions-get}

**List a catalog item's conversion provenance history**

Return a catalog item's full conversion history, newest first (CPDO-3.3).

One entry per convert/re-convert from the append-only ``conversion_provenance`` ledger: the
target Project + revision it produced, the fidelity outcome, the converter tool versions, the
content-addressed evidence snapshot id (and whether that snapshot is actually stored and
replayable), and the digest of the exact source text converted. ``currentSourceHash`` digests
the item's *currently captured* source so a client can mark rows whose ``sourceHash`` differs
as historic — "the source has changed since this conversion was approved".

Exposes the same class of metadata the unguarded catalog list/detail already carry on their
``conversion`` back-link, so like them it requires authentication + tenant scoping only; the
per-conversion *evidence graph* read is the gated one. Restricted to the non-publishable slice
(a Project's id, or an unknown id, yields 404).

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item ID (a project id).
    auth_data: Authentication data (injected by dependency).

Returns:
    The :class:`~app.models.CatalogConversionHistoryResponse`, newest first.

Operation id: `get_catalog_conversion_history_v1_catalog__tenant_slug___item_id__conversions_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list a catalog item's conversion provenance history. | `application/json` [`CatalogConversionHistoryResponse`](#schema-catalogconversionhistoryresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/conversions/{provenance_id}/evidence` {#get-catalog-conversion-evidence-v1-catalog-tenant-slug-item-id-conversions-provenance-id-evidence-get}

**Page through the stored evidence snapshot of one historical conversion**

Return one page of the exact evidence graph a historical conversion was approved with.

Served from the content-addressed snapshot store (CPDO-3.3, V215) — **never rebuilt** — so the
graph is the one the user reviewed at commit time, regardless of how the source or the
converter changed since. A GET, unlike the projection's POST: the stored snapshot already fixed
its defaults, so there is no body to agree on. A snapshot that cannot be served degrades to an
explicit HTTP 200 state (``predates_snapshots`` / ``snapshot_missing`` / ``unreadable``), never
an error — pre-CPDO-3.3 conversions are a normal part of any history.

Carries the same class of source-native coordinates as the projection read, so it is gated on
the same ``imports:view`` permission, checked **after** the item lookup so a cross-tenant id
404s rather than confirming its existence with a 403. A provenance row that does not belong to
this item also 404s, so one item's evidence cannot be probed through another's URL.

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item ID (a project id).
    provenance_id: The ``conversion_provenance`` row whose snapshot to page.
    scope: Restrict the page to one edge scope; omit to page every scope.
    cursor: Opaque page cursor.
    limit: Maximum edges per page.
    auth_data: Authentication data (injected by dependency).

Returns:
    The :class:`~app.models.ConversionEvidenceResponse` — snapshot state, summary, and one page.

Raises:
    HTTPException: 400 for an unknown scope, 404 for an unknown item/provenance row, 422 for a
        malformed cursor.

Operation id: `get_catalog_conversion_evidence_v1_catalog__tenant_slug___item_id__conversions__provenance_id__evidence_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `provenance_id` | path | string | yes | Path parameter identifying the provenance id segment. |
| `scope` | query | string or null | no | Restrict the page to one edge scope: checklist / construct / loss / analysis. |
| `cursor` | query | string or null | no | Opaque cursor from a previous page; omit to start at the beginning. |
| `limit` | query | integer | no | Maximum edges per page; clamped server-side. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for page through the stored evidence snapshot of one historical conversion. | `application/json` [`ConversionEvidenceResponse`](#schema-conversionevidenceresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/catalog/{tenant_slug}/{item_id}/convert` {#convert-catalog-item-v1-catalog-tenant-slug-item-id-convert-post}

**Convert Catalog Item**

Convert a catalog item to OpenAPI — a dry-run preview or a committed Project (MFI-22.6).

The single convert verb behind the UI preview (MFI-22.4), CLI (``apiome convert``), and API:

* ``dryRun=true`` (the default) reconstructs the item's canonical model from its captured source,
  emits the OpenAPI 3.1 document (MFI-22.1) and analyzes its fidelity (MFI-22.3), and returns the
  **fidelity report + the would-be document with no side effects** — nothing is created.
* ``dryRun=false`` runs the convert-to-project/version commit job (MFI-22.5): it mints a new
  Project + ``v1`` (or appends a new version to the previously-converted Project on a re-convert),
  captures its lint score, persists provenance, and returns the created ids + the report.

The ``dryRun`` **query param is authoritative** for the side-effect decision (falling back to the
body's ``dryRun``), so a malformed/omitted body defaults to a safe dry-run and never silently
commits. ``target`` is ``openapi`` today; other targets yield 400 (the verb is target-generic for
future emitters). Optional ``defaults`` (info title/version, servers) fill cheap gaps only where
the source is empty.

A catalog item's id is a project id; this is restricted to the non-publishable slice, so a
Project's id — or an unknown id — yields 404. An item with no captured source material to
reconstruct from yields 422. Authenticated via JWT token or API key.

Args:
    tenant_slug: The tenant slug (used to reconstruct/commit the OpenAPI document).
    item_id: The catalog item ID (a project id).
    request: The conversion target + dryRun + optional defaults.
    dry_run: Authoritative dryRun query override (``None`` falls back to the body).
    auth_data: Authentication data (injected by dependency).

Returns:
    A :class:`ConvertDryRunResponse` for a dry-run, or a :class:`ConvertCommitResponse` for a commit.

Operation id: `convert_catalog_item_v1_catalog__tenant_slug___item_id__convert_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `dryRun` | query | boolean or null | no | Authoritative side-effect switch; overrides the body's dryRun when present. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for convert catalog item.

- `application/json` — [`ConvertCatalogItemRequest`](#schema-convertcatalogitemrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for convert catalog item. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/lint` {#lint-catalog-item-v1-catalog-tenant-slug-item-id-lint-get}

**Lint Catalog Item**

Score a catalog item's latest revision and return itemized lint findings (MFI-23.10).

The catalog analog of ``GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint``:
it lets the Catalog card/detail lint orbs open the *same* server-computed lint report the
Projects screens use, populated from the item's own revision rather than browser-local history.

A catalog item's id *is* a project id (the Catalog is the non-publishable slice of projects,
MFI-23.1), so the latest revision is resolved here and fed to the shared
:func:`app.lint_routes.build_lint_report`. Like the other catalog reads this is restricted to
the non-publishable slice — a Project's id, or an unknown id, yields 404 — and authenticated via
JWT token or API key.

Args:
    tenant_slug: The tenant slug (used to reconstruct the OpenAPI document).
    item_id: The catalog item ID (a project id).
    auth_data: Authentication data (injected by dependency).

Returns:
    The server-computed quality score, A-F grade and itemized findings for the latest revision.

Operation id: `lint_catalog_item_v1_catalog__tenant_slug___item_id__lint_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for lint catalog item. | `application/json` [`LintReportResponse`](#schema-lintreportresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/catalog/{tenant_slug}/{item_id}/projection` {#get-catalog-projection-v1-catalog-tenant-slug-item-id-projection-post}

**Page through a catalog item's conversion projection manifest**

Return one bounded page of the item's source → OpenAPI projection manifest (CPDO-1.3).

The graph API behind the fidelity report: where the report says *how much* a conversion would
lose, this says **which source construct became which OpenAPI pointer, and why anything did
not**. Rebuilds the deterministic manifest for the item's latest revision — the same manifest a
dry-run and a commit reference by hash, so a page fetched here describes the conversion the user
is about to run — and pages its edges.

Strictly read-only despite the POST verb, which carries the ``defaults`` body: gap-filling
defaults are folded into the snapshot hash, so a projection previewed with different defaults
from the ones the conversion will use would describe a different conversion. Nothing is created
and nothing is persisted.

**What it exposes, and why it is gated.** The page carries source-native *coordinates* — a
construct's native name/id, the line or offset a parser recorded, and payload-analysis node ids
— so a reader can open the source viewer where the evidence is. It carries no payload *values*
at all. That is the same class of data as the analysis read (CPDO-1.1), so it is gated on the
same ``imports:view`` permission, checked **after** the item lookup so a cross-tenant id 404s
rather than confirming its existence with a 403.

Like every other catalog read this is restricted to the non-publishable slice (a Project's id, or
an unknown id, yields 404) and authenticated via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item ID (a project id).
    request: Target + defaults + page window (``scope`` / ``cursor`` / ``limit``).
    auth_data: Authentication data (injected by dependency).

Returns:
    The :class:`~app.models.CatalogProjectionResponse` — the snapshot summary and one page.

Raises:
    HTTPException: 400 for an unsupported target or scope, 404 for an unknown item, 422 when the
        item has no reconstructable source or the cursor is malformed.

Operation id: `get_catalog_projection_v1_catalog__tenant_slug___item_id__projection_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (optional)

Request body for page through a catalog item's conversion projection manifest.

- `application/json` — [`CatalogProjectionRequest`](#schema-catalogprojectionrequest)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for page through a catalog item's conversion projection manifest. | `application/json` [`CatalogProjectionResponse`](#schema-catalogprojectionresponse) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/catalog/{tenant_slug}/{item_id}/source` {#get-catalog-item-source-v1-catalog-tenant-slug-item-id-source-get}

**Get Catalog Item Source**

Serve a catalog item's original source material (MFI-23.9): viewable / downloadable.

Resolves what the import captured onto the item's ``format_metadata``:

* **inline content** — streamed back as a downloadable attachment (typed by source format);
* **a source URL** (when no content was captured) — answered with a redirect to that URL;
* **neither** — ``404``, since the raw source has not (yet) been captured for this item.

**Authorization and audit (CPDO-4.2).** The raw source is the most sensitive read on the
catalog surface — it is the payload itself, not a description of it — so it is gated on the
same ``imports:view`` permission as the analysis tree and the projection graph, checked after
the item lookup so a cross-tenant id 404s rather than confirming its existence with a 403.
Every successful serve writes an ``access_audit`` row (``catalog.source.view``) recording who
read it and how it was answered; the row carries no source content.

Like the other catalog reads this is restricted to the non-publishable slice (a Project's id, or
an unknown id, yields 404) and authenticated via JWT token or API key.

Args:
    tenant_slug: The tenant slug.
    item_id: The catalog item ID.
    auth_data: Authentication data (injected by dependency).

Returns:
    A StreamingResponse of the captured source, or a RedirectResponse to the source URL.

Operation id: `get_catalog_item_source_v1_catalog__tenant_slug___item_id__source_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `item_id` | path | string | yes | Catalog item identifier. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for get catalog item source. | `application/json` any |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `CatalogAnalysisMetricRequest` {#schema-cataloganalysismetricrequest}

A privacy-safe UI latency report for a catalog analysis surface (CPDO-4.2).

A strict whitelist: one kind, a controlled surface name, and numbers. Unknown fields are
rejected (``extra="forbid"``) so a client cannot smuggle payload material into telemetry.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `kind` | `"ui_latency"` | yes | Privacy-safe metric kind (whitelist). |
| `surface` | string | yes | Which UI surface is reporting (controlled vocabulary, e.g. format_tab). |
| `latency_ms` | number or null | no | Wall-clock latency the surface measured. |
| `page_total` | integer or null | no | Optional integer row/edge total (no labels). |

### `CatalogAnalysisMetricResponse` {#schema-cataloganalysismetricresponse}

Acknowledgement that a privacy-safe metric was recorded.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `recorded` | boolean | no | Recorded. |
| `kind` | string | yes | Kind. |

### `CatalogConversionHistoryResponse` {#schema-catalogconversionhistoryresponse}

``GET /v1/catalog/{tenant_slug}/{item_id}/conversions`` — a catalog item's conversion
history, newest first (CPDO-3.3).

``currentSourceHash`` is the digest of the item's *currently captured* source, so a client can
mark rows whose ``sourceHash`` differs as historic ("the source has changed since"); ``null``
when no source is captured or the digest could not be computed.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `itemId` | string | yes | The catalog item id. |
| `currentSourceHash` | string or null | no | Digest of the item's currently captured source text, or null. |
| `conversions` | array of `ConversionProvenanceEntry` | no | Provenance rows, newest first. |

### `CatalogItemDetailSchema` {#schema-catalogitemdetailschema}

A catalog item with the MFI-23.9 detail enrichments layered onto the MFI-23.2 list shape.

Returned by ``GET /v1/catalog/{tenant_slug}/{item_id}``: the same envelope as
:class:`CatalogItemSchema` plus a normalized-content ``summary``, a ``source`` material
descriptor (both derived from the latest revision's ``format_metadata``, see ``catalog_detail.py``)
and, from MFI-25.2, a ``parsed`` list of paradigm-tagged entity groups derived from the canonical
model (see ``catalog_parsed_model.py``). ``parsed`` is ``[]`` when no model can be reconstructed
from the item's captured source. Sparse until the import path records that provenance.

From CPDO-1.1 it also carries ``analysis``: the summary of the revision-scoped native payload
analysis (:mod:`app.payload_analysis`). The summary carries status and counts only — never
payload material — so it is readable by anyone who can read the item; the native tree itself is a
separate, permission-gated request to ``…/{item_id}/analysis``. A revision that has never been
analysed reports a declared ``unavailable`` status with a reason code, never a fabricated tree.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `creator_id` | string or null | no | Creator ID. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `slug` | string | yes | URL-safe identifier. |
| `enabled` | boolean | no | Whether the resource is active. |
| `deleted_at` | string (date-time) or string or null | no | Deleted At timestamp (ISO 8601). |
| `metadata` | object or null | no | Additional JSON metadata bag. |
| `qualityScore` | integer or null | no | Quality Score. |
| `qualityGrade` | string or null | no | Quality Grade. |
| `versionsCount` | integer | no | Number of versions. |
| `publishable` | boolean | no | Publishable. |
| `sourceFormat` | string or null | no | Source Format. |
| `protocol` | string or null | no | Protocol. |
| `formatMetadata` | object or null | no | Format Metadata. |
| `toolVersions` | object or null | no | Tool Versions. |
| `creator_name` | string or null | no | Creator Name. |
| `creator_email` | string or null | no | Creator Email. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |
| `conversion` | `CatalogConversionRef` or null | no | Conversion. |
| `identityGroupId` | string or null | no | Identity Group ID. |
| `relatedArtifacts` | array of `RelatedArtifactRef` | no | Related Artifacts. |
| `summary` | `CatalogNormalizedSummary` | no | Short summary suitable for navigation and reference docs. |
| `source` | `CatalogSourceDescriptor` | no | Provenance source for the record (for example human or imported). |
| `parsed` | array of `CatalogParsedGroup` | no | Parsed. |
| `analysis` | `PayloadAnalysisSummary` | no | Summary of the revision-scoped native payload analysis: status, reason code, analyzer identity and node counts. Carries no payload material; fetch the native tree from GET /v1/catalog/{tenant_slug}/{item_id}/analysis, which requires imports:view. |

### `CatalogItemSchema` {#schema-catalogitemschema}

A catalog item (MFI-23.1): an OpenAPI-worthy non-OpenAPI import that is *not* a publishable
Project.

A catalog item is a projection over the same ``projects`` + ``versions`` tables a Project uses —
it is simply the ``publishable = false`` slice — so the Catalog screen can clone the Projects
dashboard. Alongside the project-compatible fields (id/name/slug/description/timestamps/creator/
qualityScore/qualityGrade) it carries the format/protocol/provenance the import recorded onto its
latest revision (MFI-7.1/7.2): ``sourceFormat``, ``protocol``, ``formatMetadata``, and
``toolVersions``. ``publishable`` is always ``False`` for a catalog item, by construction.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `tenant_id` | string | yes | Tenant that owns the resource. |
| `creator_id` | string or null | no | Creator ID. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `slug` | string | yes | URL-safe identifier. |
| `enabled` | boolean | no | Whether the resource is active. |
| `deleted_at` | string (date-time) or string or null | no | Deleted At timestamp (ISO 8601). |
| `metadata` | object or null | no | Additional JSON metadata bag. |
| `qualityScore` | integer or null | no | Quality Score. |
| `qualityGrade` | string or null | no | Quality Grade. |
| `versionsCount` | integer | no | Number of versions. |
| `publishable` | boolean | no | Publishable. |
| `sourceFormat` | string or null | no | Source Format. |
| `protocol` | string or null | no | Protocol. |
| `formatMetadata` | object or null | no | Format Metadata. |
| `toolVersions` | object or null | no | Tool Versions. |
| `creator_name` | string or null | no | Creator Name. |
| `creator_email` | string or null | no | Creator Email. |
| `created_at` | string (date-time) or string or null | no | Creation timestamp (ISO 8601). |
| `updated_at` | string (date-time) or string or null | no | Last update timestamp (ISO 8601). |
| `conversion` | `CatalogConversionRef` or null | no | Conversion. |
| `identityGroupId` | string or null | no | Identity Group ID. |
| `relatedArtifacts` | array of `RelatedArtifactRef` | no | Related Artifacts. |

### `CatalogProjectionRequest` {#schema-catalogprojectionrequest}

Request body for ``POST /v1/catalog/{tenant_slug}/{item_id}/projection`` (CPDO-1.3).

Read-only despite the verb: the endpoint rebuilds the deterministic manifest for the item's
latest revision and returns one page of it, creating nothing. ``defaults`` must match what the
conversion would be run with, because gap-filling defaults are folded into the snapshot hash —
previewing the projection with different defaults describes a different conversion.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target` | string | no | Conversion target (only 'openapi' today). |
| `defaults` | `ConversionDefaultsRequest` or null | no | The same gap-filling defaults the conversion would use; folded into the hash. |
| `scope` | string or null | no | Restrict the page to one edge scope: checklist / construct / loss / analysis. Omit to page every scope in canonical order. |
| `cursor` | string or null | no | Opaque cursor from a previous page; omit to start at the beginning. |
| `limit` | integer | no | Maximum edges per page; clamped server-side to the hard cap. |

### `CatalogProjectionResponse` {#schema-catalogprojectionresponse}

One bounded page of a catalog item's conversion projection manifest (CPDO-1.3).

Carries the snapshot ``summary`` (hash, tool versions, tallies) alongside the ``page`` of edges
and the nodes they reference, so a caller can render a page without a second request and can
tell — via the hash — whether two pages came from the same snapshot.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `itemId` | string | yes | The catalog item id. |
| `versionRecordId` | string or null | no | The source revision the manifest describes. |
| `target` | string | no | The conversion target. |
| `summary` | object | yes | The bounded projection-manifest summary. |
| `page` | object | yes | This page of edges + the nodes they reference. |

### `ConversionEvidenceResponse` {#schema-conversionevidenceresponse}

One page of a historical conversion's stored evidence graph (CPDO-3.3).

Serves the exact approved manifest from the content-addressed snapshot store — never a rebuild —
so the evidence shown is the evidence the conversion was committed with, regardless of how the
source or the converter changed since. ``summary``/``page`` are ``null`` exactly when
``snapshot.status`` is ``unavailable``; degrade is HTTP 200, never a 5xx.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `provenanceId` | string | yes | The conversion_provenance row served. |
| `itemId` | string or null | no | Catalog item id, on the catalog surface. |
| `projectId` | string or null | no | Target Project id, on the project surface. |
| `manifestHash` | string or null | no | Content-addressed snapshot id, or null. |
| `sourceHash` | string or null | no | Digest of the source text converted, or null. |
| `snapshot` | `ConversionSnapshotState` | yes | Snapshot availability + degrade reason. |
| `summary` | object or null | no | The bounded manifest summary of the stored snapshot; null when unavailable. |
| `page` | object or null | no | One page of the stored graph's edges + nodes; null when unavailable. |

### `ConvertCatalogItemRequest` {#schema-convertcatalogitemrequest}

Request body for ``POST /v1/catalog/{tenant_slug}/{item_id}/convert`` (MFI-22.6).

Carries the conversion target (``openapi`` is the only one today, but the verb is target-generic
for future emitters), the ``dryRun`` flag (the query param is authoritative for the side-effect
decision; this mirrors it so a body-only caller still works), and the optional user defaults.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `target` | string | no | Conversion target format (only 'openapi' today). |
| `dry_run` | boolean | no | When true, return the fidelity report with no side effects; when false, commit. |
| `defaults` | `ConversionDefaultsRequest` or null | no | Optional user-supplied fallbacks applied only where the source is empty. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `LintReportResponse` {#schema-lintreportresponse}

Server-computed quality score + itemized findings for one project version (#3609).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `projectId` | string | yes | Project ID. |
| `versionRecordId` | string | yes | Version Record ID. |
| `versionId` | string | yes | Human-readable version label (e.g. 1.0.0). |
| `score` | integer | yes | Deterministic 0-100 quality score. |
| `grade` | string | yes | A-F letter grade derived from the score. |
| `findings` | array of `LintFindingOut` | yes | Findings. |
| `ruleHits` | map of integer | no | Count of findings per rule id (deterministic). |
| `severityCounts` | map of integer | no | Count of findings per severity (error/warning/info). |
| `categories` | array of `LintCategoryScoreOut` | no | Per-category 0-100 rollup scores (MFI-25.6), sorted by name — drives the UI's category bars with real values. Empty when no categories apply. |
| `reportFingerprint` | string | yes | Stable hash over score, grade, and findings for a fixed input. |
| `baseRevisionId` | string or null | no | Base revision used for breaking-change comparison, when provided. |
| `compatibilityOverall` | string or null | no | Compatibility verdict vs base revision (safe/breaking/unknown), when compared. |
| `capturedScore` | integer or null | no | Score persisted on the version at import time (MFI-4.2), if any. |
| `capturedGrade` | string or null | no | A-F grade persisted on the version at import time, if any. |
| `capturedReportFingerprint` | string or null | no | Report fingerprint persisted on the version at import time, if any. |
| `scoreIsStale` | boolean | no | True when a captured fingerprint exists and differs from this live report's fingerprint, signalling the persisted score is out of date. Always False when a base revision is compared (the live report folds in extra findings) or when no score has been captured. |
| `guideId` | string or null | no | The style guide this report was scored under (GOV-1.4). Null when the in-code default guide applied (no guide assigned or resolvable). |
| `guideName` | string or null | no | Display name of the applied style guide (e.g. 'Apiome Recommended'). |
| `guideSource` | string or null | no | Origin of the applied guide: builtin \| custom \| fallback (in-code defaults). |
| `guideRevisionId` | string or null | no | Immutable revision of the applied style guide (GOV-1.6) — the exact ruleset this report was scored against, queryable at `GET /v1/style-guides/{tenantSlug}/{guideId}/revisions/{revisionId}`. Null when the in-code default guide applied or no revision could be resolved. |
| `algorithmId` | string or null | no | Multi-axis scoring algorithm id (CLX-1.2), e.g. clx-axis-v1. |
| `axes` | array of `LintAxisOut` or null | no | Per-axis scores and coverage (CLX-1.2). Null when not evaluated. |
| `compositeScore` | integer or null | no | Weighted composite when required coverage is met; null otherwise. |
| `compositeGrade` | string or null | no | A-F grade of the composite; null when compositeScore is null. |
| `requiredCoverageMet` | boolean or null | no | True when required axes (v1: quality) are assessed. |

### `PayloadAnalysisRecord` {#schema-payloadanalysisrecord}

A stored analysis: the document plus the identity of the row that holds it.

Returned by the full-analysis endpoint. The identity half is what makes the record citable — a
projection manifest (CPDO-1.3) references ``analysis_id`` and ``content_fingerprint``, not "the
analysis of this item", which would drift.

Attributes:
    analysis_id: Row id.
    tenant_id: Owning tenant.
    project_id: Catalog project the analysed revision belongs to.
    version_record_id: The analysed source revision.
    analysis_sequence: Monotonic sequence within the revision; highest is in force.
    content_fingerprint: SHA-256 over the canonicalized document.
    analyzed_at: When the record was written.
    analysis: The document itself.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `analysisId` | string or null | no | Analysis ID. |
| `tenantId` | string or null | no | Tenant ID. |
| `projectId` | string or null | no | Project ID. |
| `versionRecordId` | string or null | no | Version Record ID. |
| `analysisSequence` | integer | no | Analysis Sequence. |
| `contentFingerprint` | string or null | no | Content Fingerprint. |
| `analyzedAt` | string or null | no | Analyzed At. |
| `analysis` | `PayloadAnalysisDocument` | no | Analysis. |
