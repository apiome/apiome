# Primitives Management Feature

## Overview

The Primitives feature allows you to define and manage reusable primitive type definitions that can be used across your JSON schemas. Primitives are tenant-scoped and can be imported from existing JSON Schema documents.

## Features

- **Create and manage primitives**: Define custom primitive types with JSON Schema
- **Import from JSON Schema**: Import primitive definitions from existing JSON Schema documents ($defs or definitions)
- **Tenant-scoped**: All primitives are scoped to a specific tenant
- **Authentication**: API key-based authentication for all operations
- **Categories**: Organize primitives by category (string, number, integer, boolean, array, object)
- **Tags**: Tag primitives for better discoverability
- **Usage tracking**: Track how many times a primitive has been used
- **System primitives**: Pre-defined system primitives available to all tenants

## Database Schema

### Table: `odb.primitives`

```sql
CREATE TABLE primitives (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100) NOT NULL,
    schema JSONB NOT NULL,
    tags TEXT[],
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    created_by UUID REFERENCES users(id),
    is_system BOOLEAN DEFAULT false,
    is_public BOOLEAN DEFAULT false,
    usage_count INTEGER DEFAULT 0,
    enabled BOOLEAN DEFAULT true,
    deleted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT primitives_name_category_unique UNIQUE (tenant_id, category, name)
);
```

## REST API Endpoints

All endpoints support dual authentication:
- **JWT Token**: Pass via `Authorization: Bearer <token>` header (from NextAuth session)
- **API Key**: Pass via `X-API-Key: <key>` header

JWT authentication will validate that the user belongs to the requested tenant.
API key authentication will validate that the key belongs to the requested tenant.

### Authentication Examples

**Using JWT Token (from NextAuth session):**
```bash
curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  http://localhost:8000/v1/primitives/my-tenant
```

**Using API Key:**
```bash
curl -H "X-API-Key: your-api-key" \
  http://localhost:8000/v1/primitives/my-tenant
```

### List Primitives

```
GET /v1/primitives/{tenant-slug}?category={category}
```

Lists all primitives for a tenant, optionally filtered by category.

**Response:**
```json
[
  {
    "id": "uuid",
    "tenant_id": "uuid",
    "name": "Email Address",
    "description": "A valid email address",
    "category": "string",
    "schema": {
      "type": "string",
      "format": "email",
      "pattern": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
    },
    "tags": ["email", "contact"],
    "is_system": true,
    "is_public": true,
    "usage_count": 42,
    "enabled": true,
    "created_at": "2026-01-22T10:00:00Z",
    "updated_at": "2026-01-22T10:00:00Z"
  }
]
```

### Get Primitive

```
GET /v1/primitives/{tenant-slug}/{primitive-id}
```

Gets a specific primitive by ID.

### Create Primitive

```
POST /v1/primitives/{tenant-slug}
```

**Request Body:**
```json
{
  "name": "Percentage",
  "description": "A number representing a percentage (0-100)",
  "category": "number",
  "schema": {
    "type": "number",
    "minimum": 0,
    "maximum": 100
  },
  "tags": ["percentage", "ratio"]
}
```

### Update Primitive

```
PUT /v1/primitives/{tenant-slug}/{primitive-id}
```

**Request Body:**
```json
{
  "name": "Updated Name",
  "description": "Updated description",
  "enabled": true
}
```

### Delete Primitive

```
DELETE /v1/primitives/{tenant-slug}/{primitive-id}
```

Soft deletes a primitive. System primitives cannot be deleted.

### Import from JSON Schema

```
POST /v1/primitives/{tenant-slug}/import
```

Imports primitive definitions from a JSON Schema document.

**Request Body:**
```json
{
  "schema": {
    "$defs": {
      "EmailAddress": {
        "type": "string",
        "format": "email",
        "description": "A valid email address"
      },
      "Percentage": {
        "type": "number",
        "minimum": 0,
        "maximum": 100,
        "description": "A percentage value"
      }
    }
  },
  "import_all": false,
  "selected_definitions": ["EmailAddress", "Percentage"]
}
```

**Response:**
```json
{
  "message": "Import completed",
  "imported": ["EmailAddress", "Percentage"],
  "skipped": [],
  "errors": [],
  "total_imported": 2,
  "total_skipped": 0,
  "total_errors": 0
}
```

## UI Helper Functions

### TypeScript Interface

```typescript
export interface Primitive {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  category: string;
  schema: any;
  tags: string[];
  created_by: string | null;
  is_system: boolean;
  is_public: boolean;
  usage_count: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
```

### Helper Functions

```typescript
// Get all primitives for a tenant
await getPrimitives(tenantId: string, category?: string | null)

// Get primitive categories
await getPrimitiveCategories(tenantId: string)

// Get a specific primitive
await getPrimitiveById(primitiveId: string, tenantId: string)

// Create a primitive
await createPrimitive(
  tenantId: string,
  createdBy: string,
  name: string,
  description: string | null,
  category: string,
  schema: any,
  tags: string[]
)

// Update a primitive
await updatePrimitive(
  primitiveId: string,
  tenantId: string,
  updates: {
    name?: string;
    description?: string;
    category?: string;
    schema?: any;
    tags?: string[];
    enabled?: boolean;
  }
)

// Delete a primitive
await deletePrimitive(primitiveId: string, tenantId: string)

// Increment usage count
await incrementPrimitiveUsage(primitiveId: string)

// Import from JSON Schema
await importPrimitivesFromSchema(
  tenantId: string,
  createdBy: string,
  jsonSchema: any,
  selectedDefinitions?: string[]
)
```

## Usage Examples

### Example 1: Create a Custom Primitive

```typescript
const result = await createPrimitive(
  'tenant-123',
  'user-456',
  'Credit Card Number',
  'A valid credit card number (Luhn validated)',
  'string',
  {
    type: 'string',
    pattern: '^[0-9]{13,19}$',
    minLength: 13,
    maxLength: 19
  },
  ['payment', 'credit-card', 'finance']
);
```

### Example 2: Import from JSON Schema

```typescript
const jsonSchema = {
  $defs: {
    UUID: {
      type: 'string',
      format: 'uuid',
      pattern: '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
      description: 'A universally unique identifier'
    },
    ISODate: {
      type: 'string',
      format: 'date',
      pattern: '^\\d{4}-\\d{2}-\\d{2}$',
      description: 'An ISO 8601 date'
    }
  }
};

const result = await importPrimitivesFromSchema(
  'tenant-123',
  'user-456',
  jsonSchema,
  ['UUID', 'ISODate']
);

console.log(`Imported ${result.total_imported} primitives`);
```

### Example 3: REST API Call with curl

```bash
# List all primitives (using API key)
curl -H "X-API-Key: your-api-key" \
  http://localhost:8000/v1/primitives/my-tenant

# List all primitives (using JWT token)
curl -H "Authorization: Bearer your-jwt-token" \
  http://localhost:8000/v1/primitives/my-tenant

# Create a primitive (using API key)
curl -X POST \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Positive Integer",
    "description": "An integer greater than zero",
    "category": "integer",
    "schema": {
      "type": "integer",
      "minimum": 1
    },
    "tags": ["integer", "positive"]
  }' \
  http://localhost:8000/v1/primitives/my-tenant

# Create a primitive (using JWT token)
curl -X POST \
  -H "Authorization: Bearer your-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Positive Integer",
    "description": "An integer greater than zero",
    "category": "integer",
    "schema": {
      "type": "integer",
      "minimum": 1
    },
    "tags": ["integer", "positive"]
  }' \
  http://localhost:8000/v1/primitives/my-tenant

# Import from JSON Schema (using JWT token - created_by will be set)
curl -X POST \
  -H "Authorization: Bearer your-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "schema": {
      "$defs": {
        "EmailAddress": {
          "type": "string",
          "format": "email"
        }
      }
    },
    "import_all": true
  }' \
  http://localhost:8000/v1/primitives/my-tenant/import
```

## System Primitives

The following system primitives are pre-installed for all tenants:

1. **Email Address** - Valid email address (RFC 5322)
2. **UUID** - Universally unique identifier
3. **Percentage** - Number between 0 and 100
4. **URL** - Valid URL (RFC 3986)
5. **ISO Date** - Date in ISO 8601 format (YYYY-MM-DD)
6. **ISO DateTime** - Date-time in ISO 8601 format with timezone
7. **Positive Integer** - Integer greater than zero
8. **Phone Number** - International phone number (E.164 format)

## Security

- **Dual Authentication**: All API endpoints support both JWT tokens and API keys
  - **JWT Token**: Validates user identity and tenant membership via NextAuth session
  - **API Key**: Validates tenant-level access without user context
- **User Attribution**: When using JWT authentication, `created_by` field tracks the user who created the primitive
- **Tenant Isolation**: All primitives are scoped to tenants (users/keys can only access their tenant's primitives)
- **User-Tenant Validation**: JWT tokens verify the user belongs to the requested tenant via `tenant_users` table
- **System Primitive Protection**: System primitives cannot be modified or deleted
- **Soft Deletes**: Data integrity preserved with soft delete mechanism

### JWT Token Structure

The JWT token from NextAuth should contain:
- `user_id` or `sub`: The user's ID
- `email`: User's email (optional)
- `name`: User's name (optional)

The authentication module validates the token and checks that the user is a member of the requested tenant.

## Testing

To test the primitives feature:

1. Run the database migration:
   ```bash
   psql -d objectified -f objectified-db/scripts/20260122-120000.sql
   ```

2. Start the objectified-rest service:
   ```bash
   cd objectified-rest
   source venv/bin/activate  # or use uv
   uvicorn src.app.main:app --reload
   ```

3. Test with curl or your favorite HTTP client using the examples above

## Future Enhancements

- [ ] UI components for managing primitives
- [ ] Primitive preview and validation
- [ ] Sharing primitives between tenants (is_public flag)
- [ ] Primitive versioning
- [ ] Primitive templates and marketplace
- [ ] Integration with schema builder components
- [ ] Bulk import/export
- [ ] Primitive usage analytics
