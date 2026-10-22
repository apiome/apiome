---
title: "Catalog migrations"
description: "REST endpoints tagged catalog-migrations: 6 operations."
sidebar_position: 14
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.284.0**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `catalog-migrations` · 6 operations

## `GET /v1/tenants/{tenant_slug}/catalog-components/{slug}` {#read-catalog-component-v1-tenants-tenant-slug-catalog-components-slug-get}

**Read a component**

An accepted Backstage or Compass component, system or domain (`imports:view`).

Its owner, facts and dependencies are read through the owners, entity-facts and graph routes
with kind `component`.

Operation id: `read_catalog_component_v1_tenants__tenant_slug__catalog_components__slug__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `slug` | path | string | yes | URL-safe resource slug. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read a component. | `application/json` [`ComponentOut`](#schema-componentout) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/catalog-migration-suggestions/{suggestion_id}/accept` {#accept-catalog-migration-suggestion-v1-tenants-tenant-slug-catalog-migration-suggestions-suggestion-id-accept-post}

**Accept a suggestion**

Accept a suggestion (`imports:create`; a team also needs `teams:create`).

* **Team** — creates the team with the imported name, description, email and links (or links the
  live team that already has the slug), then suggests it as the owner of everything the import
  said it owns. It is never confirmed as an owner here.
* **Component** matched to a Project or catalog item — applies the owner suggestion (and, for
  Compass, the declared dependencies) to that entity. `asComponent: true` registers it as a
  component of its own instead.
* **Component** — registers a `component` entity with its links and declared dependencies;
  references to it that were unresolved resolve now.

`name` and `slug` override what was imported. 409 `migration-slug-taken` when a component has
the slug already; 409 `migration-suggestion-decided` when it was decided before.

Operation id: `accept_catalog_migration_suggestion_v1_tenants__tenant_slug__catalog_migration_suggestions__suggestion_id__accept_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suggestion_id` | path | string | yes | Path parameter identifying the suggestion id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for accept a suggestion.

- `application/json` — [`AcceptInput`](#schema-acceptinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for accept a suggestion. | `application/json` [`MigrationSuggestion`](#schema-migrationsuggestion) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/catalog-migration-suggestions/{suggestion_id}/dismiss` {#dismiss-catalog-migration-suggestion-v1-tenants-tenant-slug-catalog-migration-suggestions-suggestion-id-dismiss-post}

**Dismiss a suggestion**

Dismiss a suggestion (`imports:create`); later scans and uploads keep it dismissed.

Operation id: `dismiss_catalog_migration_suggestion_v1_tenants__tenant_slug__catalog_migration_suggestions__suggestion_id__dismiss_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `suggestion_id` | path | string | yes | Path parameter identifying the suggestion id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for dismiss a suggestion. | `application/json` [`MigrationSuggestion`](#schema-migrationsuggestion) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/catalog-migrations` {#list-catalog-migrations-v1-tenants-tenant-slug-catalog-migrations-get}

**List import reports**

Every Backstage and Compass import report, most recently updated first (`imports:view`).

A repository branch with `catalog-info.yaml` files has one report, rewritten by each scan; each
Compass upload has its own. `pending` counts the suggestions still waiting for a decision.

Operation id: `list_catalog_migrations_v1_tenants__tenant_slug__catalog_migrations_get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for list import reports. | `application/json` [`MigrationRunList`](#schema-migrationrunlist) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `POST /v1/tenants/{tenant_slug}/catalog-migrations/compass` {#import-compass-export-v1-tenants-tenant-slug-catalog-migrations-compass-post}

**Import a Compass export**

Stage an Atlassian Compass export (`imports:create`).

`content` is the export's JSON: `{components, teams}`, a GraphQL `searchComponents` response, or
a list of components (at most 5 MB). Components become component suggestions (links,
`DEPENDS_ON` relationships as declared references), owners become team suggestions, and every
field that has no Apiome equivalent is listed in `unmapped`. Nothing is created until a
suggestion is accepted.

Operation id: `import_compass_export_v1_tenants__tenant_slug__catalog_migrations_compass_post`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Request body** (required)

Request body for import a compass export.

- `application/json` — [`CompassUploadInput`](#schema-compassuploadinput)

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 201 | Successful response for import a compass export. | `application/json` [`MigrationRun`](#schema-migrationrun) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## `GET /v1/tenants/{tenant_slug}/catalog-migrations/{run_id}` {#read-catalog-migration-v1-tenants-tenant-slug-catalog-migrations-run-id-get}

**Read an import report**

One report: counts, suggestions (teams, then components) and unmapped fields (`imports:view`).

Operation id: `read_catalog_migration_v1_tenants__tenant_slug__catalog_migrations__run_id__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `tenant_slug` | path | string | yes | URL-safe tenant slug that scopes the request. |
| `run_id` | path | string | yes | Path parameter identifying the run id segment. |
| `authorization` | header | string or null | no | JWT bearer token for authenticated access (``Authorization: Bearer <token>``). |
| `X-API-Key` | header | string or null | no | Tenant-scoped API key used as an alternative to JWT bearer authentication. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | Successful response for read an import report. | `application/json` [`MigrationRun`](#schema-migrationrun) |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `AcceptInput` {#schema-acceptinput}

Overrides for accepting a suggestion; everything defaults to what the import read.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string or null | no | Human-readable name. |
| `slug` | string or null | no | URL-safe identifier. |
| `asComponent` | boolean | no | For a component matched to an existing Project or catalog item: register it as a component of its own instead of applying it to the match. |

### `CompassUploadInput` {#schema-compassuploadinput}

An uploaded Compass export.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `filename` | string | no | Filename. |
| `content` | string | yes | The export's JSON text, as uploaded. |

### `ComponentOut` {#schema-componentout}

An accepted component (the ``component`` entity kind).

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `slug` | string | yes | URL-safe identifier. |
| `name` | string | yes | Human-readable name. |
| `description` | string or null | no | Free-text description. |
| `category` | enum `"component"`, `"system"`, `"domain"` | yes | Classification category for the primitive type. |
| `componentType` | string or null | no | Component Type. |
| `lifecycle` | string or null | no | Lifecycle. |
| `parentRef` | string or null | no | Parent Ref. |
| `links` | array of `ComponentLink` | no | Links. |
| `source` | enum `"backstage"`, `"compass"` | yes | Provenance source for the record (for example human or imported). |
| `externalRef` | string | yes | External Ref. |
| `owner` | `EntityOwnerRef` or null | no | The confirmed owner, else the oldest suggestion. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |

### `MigrationRun` {#schema-migrationrun}

One import report.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `source` | enum `"backstage"`, `"compass"` | yes | Provenance source for the record (for example human or imported). |
| `label` | string | yes | Label. |
| `repositoryId` | string or null | no | Repository ID. |
| `branch` | string or null | no | Branch. |
| `counts` | map of integer | no | Counts. |
| `unmapped` | array of `UnmappedFieldOut` | no | Unmapped. |
| `unmappedTotal` | integer | no | Unmapped Total. |
| `pending` | integer | no | Suggestions still waiting for a decision. |
| `suggestions` | array of [`MigrationSuggestion`](#schema-migrationsuggestion) or null | no | Present on a single report's read. |
| `createdAt` | string or null | no | Created At. |
| `updatedAt` | string or null | no | Updated At. |

### `MigrationRunList` {#schema-migrationrunlist}

Every import report of a tenant, newest first.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `runs` | array of [`MigrationRun`](#schema-migrationrun) | yes | Runs. |

### `MigrationSuggestion` {#schema-migrationsuggestion}

One staged component or team.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Stable resource identifier. |
| `kind` | enum `"component"`, `"team"` | yes | Kind. |
| `source` | enum `"backstage"`, `"compass"` | yes | Provenance source for the record (for example human or imported). |
| `externalRef` | string | yes | Its reference in its own catalog. |
| `name` | string | yes | Human-readable name. |
| `slug` | string | yes | URL-safe identifier. |
| `status` | enum `"suggested"`, `"accepted"`, `"dismissed"` | yes | Status. |
| `payload` | object | no | What accepting writes: description, category, type, links, ownerRef, references (components); description, contactEmail, chatUrl, oncallUrl, docsUrl (teams). |
| `match` | object or null | no | `{kind, id, name, slug}` of the Project or catalog item the component already is. |
| `entity` | object or null | no | `{kind, id, slug}` of what accepting made or applied to. |
| `decidedAt` | string or null | no | Decided At. |
