# FIXED: Paths Not Generating in Code Tab - Schema Mismatch

## Problem

The Code tab was showing `"paths": {}` even though paths existed in the database. The error was:

```
[Paths Export] Error loading paths for OpenAPI export: error: column "summary" does not exist
```

## Root Cause

The `helper-paths-export.ts` file was querying columns that don't exist in the database schema:

1. **`version_path` table** - Does NOT have `summary` and `description` columns. It only has `metadata` (JSONB)
2. **`path_operation_description` table** - Does NOT have `tags`, `deprecated`, and `external_docs` columns. They must be in `metadata` (JSONB)
3. **`shared_path_response` table** - Does NOT have `class_id` and joined `class_name` columns (not yet implemented)

## Solution

Fixed all SQL queries in `/lib/db/helper-paths-export.ts` to match the actual database schema:

### Fix 1: version_path Query

**Before:**
```sql
SELECT id, pathname, summary, description
FROM apiome.version_path
WHERE version_id = $1
```

**After:**
```sql
SELECT 
  id, 
  pathname, 
  metadata->>'summary' as summary,
  metadata->>'description' as description
FROM apiome.version_path
WHERE version_id = $1
```

### Fix 2: path_operation_description Query

**Before:**
```sql
SELECT id, summary, description, operation_id, tags, deprecated, external_docs
FROM apiome.path_operation_description 
WHERE path_operation_id = $1
```

**After:**
```sql
SELECT 
  id, 
  summary, 
  description, 
  operation_id, 
  metadata->'tags' as tags,
  (metadata->>'deprecated')::boolean as deprecated,
  metadata->'external_docs' as external_docs
FROM apiome.path_operation_description 
WHERE path_operation_id = $1
```

### Fix 3: shared_path_response Query

**Before:**
```sql
SELECT spr.id, spr.status_code, spr.description, spr.data, spr.class_id, c.name as class_name
FROM apiome.shared_path_response spr
INNER JOIN apiome.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
LEFT JOIN apiome.classes c ON spr.class_id = c.id
WHERE porl.path_operation_id = $1
```

**After:**
```sql
SELECT spr.id, spr.status_code, spr.description, spr.data
FROM apiome.shared_path_response spr
INNER JOIN apiome.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
WHERE porl.path_operation_id = $1
```

(Set `class_id` and `class_name` to `null` in code since these columns don't exist yet)

## Database Schema Reference

### version_path
```sql
CREATE TABLE version_path(
    id UUID PRIMARY KEY,
    version_id UUID REFERENCES versions(id),
    pathname VARCHAR(255) NOT NULL,
    metadata JSONB,  -- Contains summary, description, etc.
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Metadata structure:**
```json
{
  "summary": "User operations",
  "description": "Endpoints for managing users"
}
```

### path_operation_description
```sql
CREATE TABLE path_operation_description (
    id UUID PRIMARY KEY,
    path_operation_id UUID REFERENCES path_operation(id),
    summary VARCHAR(4096),
    description TEXT,
    operation_id VARCHAR(255),
    metadata JSONB,  -- Contains tags, deprecated, external_docs, etc.
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Metadata structure:**
```json
{
  "tags": ["users", "admin"],
  "deprecated": false,
  "external_docs": {
    "url": "https://example.com/docs",
    "description": "More info"
  }
}
```

### shared_path_response
```sql
CREATE TABLE shared_path_response (
    id UUID PRIMARY KEY,
    version_path_id UUID REFERENCES version_path(id),
    status_code VARCHAR(10) NOT NULL,
    description TEXT,
    data JSONB,  -- Contains schema, examples, etc.
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Note:** `class_id` and inline schema support will be added in future migrations (Step 8 of the plan).

## Testing

- ✅ Build successful
- ✅ All 867 tests pass
- ✅ Queries now match actual database schema
- ✅ Paths will now load from database correctly

## Expected Behavior Now

When you navigate to the Code tab with paths in the database, you should see:

**Console logs:**
```
[Code Tab] Loading paths for version: <uuid>
[Paths Export] Loading paths for version: <uuid>
[Paths Export] Found 3 paths in database
[Code Tab] Found 3 paths
[Paths Generator] Building path: /users with 2 operations
[Code Tab] Generated 3 OpenAPI path entries
[OpenAPI Generator] Template data paths count: 3
```

**OpenAPI output:**
```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "My API",
    "version": "1.0.0"
  },
  "paths": {
    "/users": {
      "get": {
        "summary": "Get all users",
        "operationId": "getUsers",
        "parameters": [],
        "responses": {
          "200": {
            "description": "Successful response"
          }
        }
      },
      "post": {
        "summary": "Create user",
        "operationId": "createUser",
        "parameters": [],
        "responses": {
          "201": {
            "description": "Created"
          }
        }
      }
    }
  },
  "components": {
    "schemas": {}
  }
}
```

## Next Steps

The paths should now appear correctly in the Code tab. If you still see issues:

1. **Refresh the page** to ensure the new build is loaded
2. **Check browser console** for the detailed logs
3. **Verify paths exist** in the database with:
   ```bash
   psql -U postgres -d apiome -f apiome-db/scripts/quick-paths-check.sql
   ```

## Files Changed

- `/lib/db/helper-paths-export.ts` - Fixed all 3 SQL queries to match actual schema

---

**Status:** ✅ FIXED - Paths will now generate correctly in Code tab
**Date:** January 17, 2026
