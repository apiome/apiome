---
title: "Types public"
description: "REST endpoints tagged types-public: 1 operation."
sidebar_position: 74
tags: [rest, reference]
generated: apiome-rest/scripts/generate_rest_reference_docs.py
---

<!-- GENERATED FILE — do not edit by hand.
     Regenerate with: cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py -->

Generated from `apiome-rest/openapi.yaml` (API version **1.204.1**) — do not edit by hand. How to authenticate is on the [REST API reference](./index.mdx#authentication).

Tag: `types-public` · 1 operation

## `GET /types/{schema_path}` {#get-public-type-types-schema-path-get}

**Get a public registry type by its $id path**

Serve the JSON Schema document a registry ``$id`` names.

``schema_path`` is everything after ``/types/`` — namespace plus type-name slug, e.g.
``std/v0/primitives/array``. It is re-joined onto :data:`REGISTRY_BASE_URL` to rebuild the exact
``$id`` the registry derived, then matched against the stored column, so this endpoint agrees
with ``$ref`` resolution by construction rather than by a second parsing rule.

Args:
    schema_path: The ``$id`` path below the registry mount.

Returns:
    The stored schema document with the JSON Schema media type.

Raises:
    HTTPException: 404 when no ``is_system``/``is_public`` type carries that ``$id``.

Operation id: `get_public_type_types__schema_path__get`

**Parameters**

| Name | In | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `schema_path` | path | string | yes | Path parameter identifying the schema path segment. |

**Responses**

| Status | Description | Body |
| --- | --- | --- |
| 200 | The type's JSON Schema document, as stored (its `$id` included). | `application/schema+json` any |
| 404 | No publicly servable type at this path. | — |
| 422 | Validation Error | `application/json` [`HTTPValidationError`](#schema-httpvalidationerror) |

## Schemas used {#schemas-used}

### `HTTPValidationError` {#schema-httpvalidationerror}

Validation error response emitted when request data fails schema checks.

| Property | Type | Required | Description |
| --- | --- | --- | --- |
| `detail` | array of `ValidationError` | no | Detail. |
