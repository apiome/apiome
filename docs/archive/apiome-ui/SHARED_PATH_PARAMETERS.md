# Shared Path Parameters Implementation

## Overview

Path parameters are now **shared and reusable** across multiple operations within the same path. This means when you define a parameter like `{userId}` for one operation, it can be reused by other operations on the same path without redefinition.

## Database Schema

### Tables

#### 1. `shared_path_parameter`
Stores the canonical definition of path parameters, scoped to a specific `version_path`.

```sql
CREATE TABLE apiome.shared_path_parameter (
    id UUID PRIMARY KEY,
    version_path_id UUID NOT NULL REFERENCES apiome.version_path(id),
    name VARCHAR(255) NOT NULL,
    in_location VARCHAR(50) NOT NULL, -- 'path', 'query', 'header', 'cookie'
    summary VARCHAR(4096),
    description TEXT,
    data JSONB NOT NULL, -- JSON Schema definition
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(version_path_id, name, in_location)
);
```

**Key Points:**
- One shared parameter per `(version_path_id, name, in_location)` combination
- Contains the JSON Schema definition in the `data` column
- Can be linked to multiple operations

#### 2. `path_operation_parameter_link`
Links shared parameters to specific operations (many-to-many relationship).

```sql
CREATE TABLE apiome.path_operation_parameter_link (
    id UUID PRIMARY KEY,
    path_operation_id UUID NOT NULL REFERENCES apiome.path_operation(id),
    shared_path_parameter_id UUID NOT NULL REFERENCES apiome.shared_path_parameter(id),
    metadata JSONB, -- For canvas position, styling, etc.
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(path_operation_id, shared_path_parameter_id)
);
```

**Key Points:**
- Links operations to shared parameters
- `metadata` stores canvas-specific data (position, styling)
- One link per operation-parameter pair

## User Experience Flow

### Adding a Parameter

1. User selects a path (e.g., `/v1/users/{userId}`)
2. User adds GET operation to canvas
3. User clicks GET operation → Operation Details panel opens
4. User clicks "+ Add Parameter"
5. User fills in parameter details (name, location, schema, etc.)
6. User clicks "Save"
7. **System checks if parameter already exists:**
   - If YES: Reuses existing shared parameter
   - If NO: Creates new shared parameter
8. System creates a link between the operation and the shared parameter
9. Canvas shows parameter node connected to the operation

### Reusing a Parameter

1. User adds POST operation to the same path
2. User clicks POST operation → Operation Details panel opens
3. User clicks "+ Add Parameter"
4. User enters the same parameter name (e.g., `userId`)
5. User clicks "Save"
6. **System finds existing shared parameter and reuses it**
7. Canvas shows the **same** parameter node now connected to **both** GET and POST operations

### Visual Representation

```
Canvas View:

┌─────────────────────────────────────────────┐
│                                             │
│  [GET] ────────┐                            │
│                │                            │
│                ├───→ {userId} (shared)      │
│                │                            │
│  [POST] ───────┘                            │
│                                             │
└─────────────────────────────────────────────┘
```

Both GET and POST operations share the same `{userId}` parameter definition.

## Benefits

### 1. **Consistency**
- Parameters are defined once and shared across operations
- Changes to a parameter affect all linked operations
- Reduces duplication and inconsistencies

### 2. **Efficiency**
- No need to redefine parameters for each operation
- System automatically detects existing parameters

### 3. **Maintenance**
- Update parameter schema in one place
- All operations using the parameter get the update
- Easy to see which operations use which parameters

### 4. **Canvas Clarity**
- Visual representation shows shared relationships
- Multiple edges from operations to the same parameter node
- Clear understanding of parameter reuse

## API Functions

### Creating/Linking Parameters

```typescript
// Create or get existing shared parameter
const paramResult = await createSharedPathParameter(
  versionPathId,        // The path (e.g., /v1/users/{userId})
  'userId',             // Parameter name
  'path',               // Location: path, query, header, cookie
  'User identifier',    // Summary
  'The unique ID...',   // Description
  { type: 'string', required: true, format: 'uuid' } // JSON Schema
);

// Link parameter to operation
const linkResult = await linkParameterToOperation(
  operationId,          // The operation (e.g., GET)
  sharedParameterId     // The shared parameter ID
);
```

### Querying Parameters

```typescript
// Get all parameters linked to an operation
const params = await getLinkedParametersForOperation(operationId);

// Get all shared parameters for a path
const allParams = await getSharedPathParameters(versionPathId);
```

### Unlinking Parameters

```typescript
// Remove link (doesn't delete the shared parameter)
await unlinkParameterFromOperation(operationId, sharedParameterId);
```

### Updating Parameters

```typescript
// Update affects ALL operations using this parameter
await updateSharedPathParameter(sharedParameterId, {
  summary: 'Updated summary',
  data: { type: 'string', format: 'uuid', required: true }
});
```

## Migration

The migration script (`20260110-111100.sql`) automatically:

1. Creates the new tables
2. Migrates existing `path_parameter` data to shared structure
3. Creates links between operations and shared parameters
4. Preserves all existing parameter definitions

**To run migration:**

```sql
-- Run the migration script
\i apiome-db/scripts/20260110-111100.sql

-- Verify migration
SELECT COUNT(*) FROM apiome.shared_path_parameter;
SELECT COUNT(*) FROM apiome.path_operation_parameter_link;

-- Optional: Drop old table after verification
-- DROP TABLE IF EXISTS apiome.path_parameter CASCADE;
```

## Important Notes

### Metadata vs Data

- **`data` column**: Contains JSON Schema definition (type, format, required, etc.)
- **`metadata` column**: Contains canvas-specific information (position, styling)

### Deletion Behavior

- **Unlinking**: Removes the link but keeps the shared parameter
- **Deleting**: Only allowed if the parameter has no links to any operations
- Parameters are automatically deleted when the parent path is deleted (CASCADE)

### Canvas Behavior

When dragging a connection from an operation to a parameter:
- The system creates a link in the database
- The canvas shows an edge between the operation and parameter nodes
- Multiple operations can connect to the same parameter node

## Schema Definition

The `data` field stores JSON Schema compliant definitions:

```json
{
  "type": "string",
  "format": "uuid",
  "required": true,
  "minLength": 36,
  "maxLength": 36,
  "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
}
```

Supported types:
- `string` (with formats: date, date-time, email, uri, uuid, etc.)
- `integer` (with min/max)
- `number` (with min/max)
- `boolean`
- `array` (with item type)

**Note**: Object types are NOT supported for path parameters.

