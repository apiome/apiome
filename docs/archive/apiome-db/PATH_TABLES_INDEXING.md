# Path Tables - Indexing Exclusion Guide

## Overview

Path-related tables in the Apiome database are **metadata-only** tables used exclusively for OpenAPI specification generation. These tables should be **excluded** from any database product indexing or schema generation processes.

## Excluded Tables

The following tables are used to store OpenAPI path definitions and should NOT be indexed when generating a database product:

### Core Path Tables

| Table | Purpose |
|-------|---------|
| `apiome.version_path` | Stores path patterns (e.g., `/api/users/{userId}`) for each version |
| `apiome.path_operation` | HTTP operations (GET, POST, PUT, PATCH, DELETE) for each path |
| `apiome.path_operation_description` | Operation metadata (summary, description, operationId, tags, deprecated) |

### Parameter Tables

| Table | Purpose |
|-------|---------|
| `apiome.shared_path_parameter` | Shared parameter definitions (path, query, header, cookie) |
| `apiome.path_operation_parameter_link` | Links parameters to operations (many-to-many) |

### Request Body Tables

| Table | Purpose |
|-------|---------|
| `apiome.shared_path_request_body` | Shared request body definitions |
| `apiome.path_operation_request_body_link` | Links request bodies to operations |
| `apiome.shared_path_request_body_content` | Content types for request bodies (application/json, multipart/form-data, etc.) with class reference or inline schema |

### Response Tables

| Table | Purpose |
|-------|---------|
| `apiome.shared_path_response` | Shared response definitions with status codes |
| `apiome.path_operation_response_link` | Links responses to operations (many-to-many) |
| `apiome.shared_path_response_content` | Content types for responses with class reference or inline schema |

## Rationale

1. **Metadata-Only**: These tables describe API contract structure, not data models. They define how endpoints should behave, not what data should be stored.

2. **OpenAPI Generation**: The sole purpose of these tables is to generate OpenAPI 3.1 specifications. They are consumed by:
   - `apiome-rest/src/app/paths_generator.py`
   - `apiome-ui/lib/utils/openapi-paths-generator.ts`

3. **Not Application Data**: Unlike `apiome.classes` and `apiome.class_properties` which define reusable data structures, path tables define API routing and documentation.

4. **Inline Schemas**: The `inline_schema` columns in content tables store path-specific schemas that are intentionally not reusable. They are either:
   - Copies of class schemas (for isolation)
   - Custom inline definitions for that specific endpoint

## Schema Storage Patterns

### Class Reference (`class_id`)
When `class_id` is set on a content type, the OpenAPI generator produces a `$ref`:
```yaml
schema:
  $ref: '#/components/schemas/User'
```
The referenced class IS indexed as a component schema.

### Inline Schema (`inline_schema`)
When `inline_schema` is set, the schema is embedded directly in the path:
```yaml
schema:
  type: object
  properties:
    id:
      type: string
    name:
      type: string
```
These inline schemas are NOT indexed separately.

## Database Product Generation

When generating a "database product" (schema export, code generation, etc.):

1. **Include** `apiome.classes`, `apiome.class_properties`, `apiome.properties`
2. **Exclude** all tables listed above
3. **Reference Resolution**: If path content types reference classes via `class_id`, the referenced classes should be included, but the path tables themselves should not

## Table Prefix Pattern

All excludable tables follow these patterns:
- `apiome.version_path*`
- `apiome.path_operation*`
- `apiome.shared_path_*`

Use this pattern for automated exclusion in tooling.
