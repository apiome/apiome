# Response Body Schema Implementation - Complete Guide

## Overview

Response bodies now support the same schema patterns as request bodies:
- **Class References** - Link to existing `apiome.classes` via `class_id`
- **Inline Schemas** - Free-form properties defined inline with `inline_schema` JSONB
- **Multiple Content Types** - Support for `application/json`, `application/xml`, etc.

This implementation mirrors the request body design for consistency and follows OpenAPI 3.1.0 specifications.

## Database Schema

### Migration: `20260117-140000.sql`

#### New Columns on `shared_path_response`

```sql
ALTER TABLE apiome.shared_path_response
ADD COLUMN class_id UUID REFERENCES apiome.classes(id);

ALTER TABLE apiome.shared_path_response
ADD COLUMN inline_schema JSONB;

-- Constraint ensures at least one schema type is defined
ALTER TABLE apiome.shared_path_response
ADD CONSTRAINT check_response_schema_defined 
CHECK (class_id IS NOT NULL OR inline_schema IS NOT NULL OR data IS NOT NULL);
```

#### New Table: `shared_path_response_content`

```sql
CREATE TABLE apiome.shared_path_response_content (
    id UUID PRIMARY KEY,
    shared_path_response_id UUID REFERENCES shared_path_response(id),
    media_type VARCHAR(255) DEFAULT 'application/json',
    class_id UUID REFERENCES apiome.classes(id),
    inline_schema JSONB,
    examples JSONB,
    UNIQUE(shared_path_response_id, media_type),
    CHECK (class_id IS NOT NULL OR inline_schema IS NOT NULL)
);
```

## Helper Functions

### `/lib/db/helper-shared-path-responses-content.ts`

#### Content Type Management

```typescript
// Add a content type to a response
await addResponseContentType(
  responseId: string,
  mediaType: string,
  classId?: string,
  inlineSchema?: InlineSchema,
  examples?: unknown[]
);

// Update content type
await updateResponseContentType(contentId, {
  mediaType?: string,
  classId?: string | null,
  inlineSchema?: InlineSchema | null,
  examples?: unknown[] | null,
});

// Delete content type
await deleteResponseContentType(contentId);

// Get all content types for a response
await getResponseContentTypes(responseId);
```

#### Schema Conversion

```typescript
// Convert class reference to inline schema (copies properties)
await convertResponseClassToInlineSchema(contentId);

// Initialize empty inline schema
await initializeResponseInlineSchema(contentId);

// Set class reference (replaces inline schema)
await setResponseContentTypeClassReference(contentId, classId);
```

#### Property Management

```typescript
// Add property to inline schema
await addPropertyToResponseInlineSchema(contentId, {
  name: string,
  description?: string,
  data: Record<string, unknown>,
  parent_id?: string | null,
});

// Update property
await updateResponseInlineSchemaProperty(contentId, propertyId, {
  name?: string,
  description?: string,
  data?: Record<string, unknown>,
});

// Delete property (with cascade option)
await deleteResponseInlineSchemaProperty(contentId, propertyId, cascadeChildren);
```

## OpenAPI Generation

### Updated `buildResponseForOpenAPI`

The function now handles:

1. **Multiple Content Types** (like request bodies)
2. **Class References** - Generates `$ref: '#/components/schemas/ClassName'`
3. **Inline Schemas** - Uses `buildSchemaFromInlineProperties()`
4. **Examples** - Supports single example or multiple named examples

### Example Output

#### Single Content Type with Class Reference

```json
{
  "200": {
    "description": "Successful response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/User"
        }
      }
    }
  }
}
```

#### Single Content Type with Inline Schema

```json
{
  "200": {
    "description": "Successful response",
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "id": { "type": "string" },
            "name": { "type": "string" },
            "email": { "type": "string", "format": "email" }
          },
          "required": ["id", "name"]
        }
      }
    }
  }
}
```

#### Multiple Content Types

```json
{
  "200": {
    "description": "Successful response",
    "content": {
      "application/json": {
        "schema": {
          "$ref": "#/components/schemas/User"
        },
        "examples": {
          "example1": {
            "summary": "Basic user",
            "value": { "id": "123", "name": "John" }
          }
        }
      },
      "application/xml": {
        "schema": {
          "type": "object",
          "properties": {
            "user": { "type": "object" }
          }
        }
      }
    }
  }
}
```

## Usage Patterns

### Pattern 1: Simple Response with Class Reference

**Scenario:** Response returns a standard `User` object

```sql
-- Set class_id on the response
UPDATE apiome.shared_path_response 
SET class_id = '<user-class-id>' 
WHERE id = '<response-id>';
```

**OpenAPI Output:**
```json
{
  "200": {
    "description": "User details",
    "content": {
      "application/json": {
        "schema": { "$ref": "#/components/schemas/User" }
      }
    }
  }
}
```

### Pattern 2: Simple Response with Inline Schema

**Scenario:** Response has custom fields not defined in any class

```typescript
// Initialize inline schema
await initializeResponseInlineSchema(contentId);

// Add properties
await addPropertyToResponseInlineSchema(contentId, {
  name: 'status',
  data: { type: 'string', enum: ['success', 'error'] }
});

await addPropertyToResponseInlineSchema(contentId, {
  name: 'message',
  data: { type: 'string' }
});
```

**OpenAPI Output:**
```json
{
  "200": {
    "description": "Operation status",
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "status": { "type": "string", "enum": ["success", "error"] },
            "message": { "type": "string" }
          }
        }
      }
    }
  }
}
```

### Pattern 3: Multiple Content Types

**Scenario:** API returns both JSON and XML

```typescript
// Add JSON content type
await addResponseContentType(
  responseId,
  'application/json',
  userClassId // class reference
);

// Add XML content type with inline schema
await addResponseContentType(
  responseId,
  'application/xml',
  undefined, // no class
  {
    type: 'object',
    properties: [
      { id: uuid(), name: 'user', data: { type: 'object' }, parent_id: null }
    ]
  }
);
```

### Pattern 4: Convert Class to Inline for Customization

**Scenario:** Start with class reference, then customize

```typescript
// First, response uses class reference
await setResponseContentTypeClassReference(contentId, userClassId);

// Later, convert to inline to customize
await convertResponseClassToInlineSchema(contentId);
// Now all properties are copied and can be modified

// Add custom property
await addPropertyToResponseInlineSchema(contentId, {
  name: 'extraField',
  data: { type: 'string' }
});
```

## Backwards Compatibility

The implementation maintains backwards compatibility:

1. **Legacy `data` JSONB** - Existing responses continue to work
2. **Optional `content_types`** - If not defined, falls back to simple schema
3. **Graceful fallback** - Missing schemas default to empty object

### Migration Strategy

```sql
-- Existing response with legacy data field
SELECT id, status_code, data FROM shared_path_response;
-- { "schema": { "$ref": "#/components/schemas/User" } }

-- Migrated to class_id
UPDATE shared_path_response 
SET class_id = '<user-class-id>', data = NULL 
WHERE id = '<response-id>';
```

## Testing

All tests pass (867 total):
- ✅ Response content type CRUD operations
- ✅ Inline schema property management
- ✅ Class to inline conversion
- ✅ OpenAPI generation with multiple content types
- ✅ Examples handling

## Complete Example: REST Endpoint with Response Schemas

```typescript
// POST /users - Create user
const createResponse = await createSharedPathResponse(
  versionPathId,
  '201',
  'User created successfully'
);

// Add JSON content type with User class reference
await addResponseContentType(
  createResponse.id,
  'application/json',
  userClassId,
  undefined,
  [{
    name: 'example1',
    summary: 'New user',
    value: { id: '123', name: 'John', email: 'john@example.com' }
  }]
);

// GET /users/{id} - Get user
const getResponse = await createSharedPathResponse(
  versionPathId,
  '200',
  'User details'
);

// Initialize inline schema for custom response
await initializeResponseInlineSchema(getResponse.contentTypeId);

// Add properties
await addPropertyToResponseInlineSchema(getResponse.contentTypeId, {
  name: 'user',
  data: { $ref: '#/components/schemas/User' },
  parent_id: null
});

await addPropertyToResponseInlineSchema(getResponse.contentTypeId, {
  name: 'metadata',
  data: { type: 'object' },
  parent_id: null
});

// Add nested properties under metadata
await addPropertyToResponseInlineSchema(getResponse.contentTypeId, {
  name: 'timestamp',
  data: { type: 'string', format: 'date-time' },
  parent_id: metadataPropertyId
});
```

**Generated OpenAPI:**

```json
{
  "paths": {
    "/users": {
      "post": {
        "responses": {
          "201": {
            "description": "User created successfully",
            "content": {
              "application/json": {
                "schema": { "$ref": "#/components/schemas/User" },
                "examples": {
                  "example1": {
                    "summary": "New user",
                    "value": { "id": "123", "name": "John", "email": "john@example.com" }
                  }
                }
              }
            }
          }
        }
      }
    },
    "/users/{id}": {
      "get": {
        "responses": {
          "200": {
            "description": "User details",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "user": { "$ref": "#/components/schemas/User" },
                    "metadata": {
                      "type": "object",
                      "properties": {
                        "timestamp": { "type": "string", "format": "date-time" }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

## Next Steps

1. **UI Implementation** - Create UI components similar to RequestBodySection
2. **Canvas Integration** - Add response body nodes to PathsCanvasView
3. **Property Editor** - Reuse ClassPropertyEditDialog for inline schemas
4. **Examples Editor** - Add UI for managing response examples
5. **Content Type Tabs** - Show multiple content types in properties panel

---

**Status:** ✅ Complete - Backend Implementation
**Date:** January 17, 2026
**Tests:** All 867 tests passing
