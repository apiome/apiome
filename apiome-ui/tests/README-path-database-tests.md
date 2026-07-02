# Path Database Tests Documentation

## Overview

This document describes the comprehensive test suite for path database table functionality in Apiome. These tests cover the version_path, path_operation, path_parameter, and path_response tables that store OpenAPI/REST API path definitions.

## Test File

**Location**: `/tests/path-database.test.ts`

## Database Tables Covered

### 1. `version_path`
Service paths associated with project versions (e.g., `/api/v1/users`, `/products/{id}`)

### 2. `path_operation`
HTTP operations for paths (GET, POST, PUT, DELETE, etc.)

### 3. `path_operation_description`
Detailed descriptions, summaries, and operation IDs for operations

### 4. `path_parameter`
Parameters for operations (query, path, header, cookie parameters)

### 5. `path_parameter_schema`
Schema definitions for parameters using class-property structure

### 6. `path_response`
Response definitions for operations (status codes, descriptions)

## Test Coverage

The test suite includes 29 tests covering the following areas:

### 1. Path Database Tables - version_path (11 tests)

#### getPathsForVersion (3 tests)
- ✅ Retrieve all paths for a version
- ✅ Return empty array when no paths exist
- ✅ Handle database errors

#### createPath (3 tests)
- ✅ Create a new path
- ✅ Create path without metadata
- ✅ Handle duplicate pathname errors (23505 constraint)

#### updatePath (2 tests)
- ✅ Update an existing path
- ✅ Handle non-existent paths

#### deletePath (2 tests)
- ✅ Delete a path
- ✅ Handle deletion of non-existent paths

#### getPathById (2 tests)
- ✅ Retrieve a single path by ID
- ✅ Return undefined for non-existent paths

### 2. Path Database Schema Validation (4 tests)

Tests validate the structure and constraints of path tables:

**Tests**:
- ✅ Validate path table constraints (unique: version_id + pathname)
- ✅ Validate path_operation table structure (unique: version_path_id + operation)
- ✅ Validate path_parameter table structure (unique: path_operation_id + name + in_location)
- ✅ Validate path_response table structure (unique: path_operation_id + status_code)

**Validated Elements**:
- Table names
- Column definitions
- Primary/foreign key relationships
- Unique constraints
- Valid values (HTTP methods, parameter locations, status codes)

### 3. Path Database Integration Scenarios (4 tests)

Tests demonstrate real-world usage patterns:

**Tests**:
- ✅ Support creating a complete REST API path
- ✅ Support multiple operations per path
- ✅ Validate cascade deletion behavior
- ✅ Handle metadata storage as JSONB

**Validated Workflows**:
```
Create Path → Add Operations → Add Parameters → Add Responses → Add Descriptions
/api/v1/users → GET, POST, PUT, DELETE → userId (path), limit (query) → 200, 404, 500
```

### 4. Path Database Error Handling (3 tests)

Tests error conditions and database constraints:

**Tests**:
- ✅ Handle constraint violations for duplicate paths (23505)
- ✅ Handle foreign key violations (23503)
- ✅ Handle null pathname errors (23502)

### 5. Path Database Performance Considerations (2 tests)

Tests performance optimization features:

**Tests**:
- ✅ Use indexes for common queries
- ✅ Order paths alphabetically for consistent display

**Indexes Validated**:
- `idx_version_path_version_id` - For fetching paths by version
- `idx_version_path_created_at` - For temporal queries
- `idx_path_operation_version_path_id` - For operation lookups
- `idx_path_parameter_path_operation_id` - For parameter queries
- `idx_path_response_path_operation_id` - For response lookups

### 6. Path Database OpenAPI Compatibility (5 tests)

Tests OpenAPI 3.0 specification compatibility:

**Tests**:
- ✅ Support OpenAPI path item object structure
- ✅ Support all HTTP methods
- ✅ Support parameter locations
- ✅ Support standard HTTP status codes

**OpenAPI Features Covered**:
- Path templates with parameters: `/users/{userId}`
- HTTP methods: GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD, TRACE
- Parameter locations: query, path, header, cookie
- Status codes: 2xx (success), 4xx (client errors), 5xx (server errors)

## Test Statistics

```
Test Suites: 1 passed, 1 total
Tests:       29 passed, 29 total
Time:        ~0.4s
```

## Running the Tests

```bash
# Run path database tests only
yarn test tests/path-database.test.ts

# Run with coverage
yarn test:coverage tests/path-database.test.ts

# Run specific test
yarn test tests/path-database.test.ts -t "should create a new path"
```

## Database Schema Structure

### version_path Table
```sql
CREATE TABLE version_path (
    id UUID PRIMARY KEY,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    pathname VARCHAR(255) NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(version_id, pathname)
);
```

### path_operation Table
```sql
CREATE TABLE path_operation (
    id UUID PRIMARY KEY,
    version_path_id UUID NOT NULL REFERENCES version_path(id) ON DELETE CASCADE,
    operation VARCHAR(50) NOT NULL,  -- HTTP method
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(version_path_id, operation)
);
```

### path_parameter Table
```sql
CREATE TABLE path_parameter (
    id UUID PRIMARY KEY,
    path_operation_id UUID NOT NULL REFERENCES path_operation(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    in_location VARCHAR(50) NOT NULL,  -- query, path, header, cookie
    summary VARCHAR(4096),
    description TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(path_operation_id, name, in_location)
);
```

### path_response Table
```sql
CREATE TABLE path_response (
    id UUID PRIMARY KEY,
    path_operation_id UUID NOT NULL REFERENCES path_operation(id) ON DELETE CASCADE,
    status_code VARCHAR(10) NOT NULL,  -- HTTP status code
    description TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    UNIQUE(path_operation_id, status_code)
);
```

## Test Patterns Used

### Mocking
- Database connection pool mocked with jest.fn()
- Query results mocked for various scenarios
- Error conditions simulated (constraints, foreign keys)

### Assertions
- Data retrieval validated
- CRUD operations verified
- Constraint enforcement checked
- Cascade deletion behavior tested
- OpenAPI compatibility confirmed

### Test Data Examples

#### Path Creation
```typescript
{
  version_id: 'version-1',
  pathname: '/api/v1/users',
  metadata: { 
    tags: ['user', 'authentication'],
    deprecated: false 
  }
}
```

#### Operation with Parameters
```typescript
{
  path: '/api/v1/users/{userId}',
  operation: 'GET',
  parameters: [
    {
      name: 'userId',
      in: 'path',
      required: true,
      schema: { type: 'string', format: 'uuid' }
    },
    {
      name: 'limit',
      in: 'query',
      required: false,
      schema: { type: 'integer', minimum: 1, maximum: 100 }
    }
  ],
  responses: {
    '200': {
      description: 'Successful response',
      content: {
        'application/json': {
          schema: { $ref: '#/components/schemas/User' }
        }
      }
    },
    '404': {
      description: 'User not found'
    }
  }
}
```

## Cascade Deletion Rules

The tests validate that cascading deletes work correctly:

1. **Delete version** → Deletes all version_path records
2. **Delete version_path** → Deletes all path_operation records
3. **Delete path_operation** → Deletes:
   - path_operation_description
   - path_parameter
   - path_response
4. **Delete path_parameter** → Deletes path_parameter_schema

This ensures referential integrity is maintained across the database.

## Error Handling Tested

- **23505**: Duplicate key violations
  - Duplicate pathname within same version
  - Duplicate operation for same path
  - Duplicate parameter name + location
  - Duplicate response status code

- **23503**: Foreign key violations
  - Non-existent version_id
  - Non-existent version_path_id
  - Non-existent path_operation_id

- **23502**: NOT NULL constraint violations
  - Missing pathname
  - Missing operation method

## Metadata Storage

All tables support JSONB metadata for flexible OpenAPI extension:

```typescript
// Path metadata
{
  tags: ['user', 'authentication'],
  deprecated: false,
  externalDocs: { url: 'https://example.com/docs' }
}

// Operation metadata
{
  summary: 'Get user by ID',
  operationId: 'getUserById',
  security: [{ bearerAuth: [] }],
  servers: [{ url: 'https://api.example.com' }]
}

// Parameter metadata
{
  required: true,
  schema: { type: 'string', format: 'uuid' },
  example: '550e8400-e29b-41d4-a716-446655440000',
  examples: {
    uuid1: { value: '550e8400-e29b-41d4-a716-446655440000' },
    uuid2: { value: '6ba7b810-9dad-11d1-80b4-00c04fd430c8' }
  }
}

// Response metadata
{
  content: {
    'application/json': {
      schema: { $ref: '#/components/schemas/User' }
    },
    'application/xml': {
      schema: { $ref: '#/components/schemas/User' }
    }
  },
  headers: {
    'X-Rate-Limit': { schema: { type: 'integer' } }
  }
}
```

## Future Enhancements

Potential areas for additional test coverage:

1. **Performance Tests**: Large numbers of paths per version
2. **Integration Tests**: Full path creation workflow with real database
3. **Migration Tests**: Schema upgrades and data migrations
4. **Validation Tests**: OpenAPI 3.0 specification compliance
5. **Import/Export Tests**: Bulk path operations from OpenAPI specs
6. **Security Tests**: Path-based access control and permissions

## Related Files

- Implementation: `/lib/db/helper-paths.ts`
- Database Schema: `/apiome-db/scripts/20260107-204300.sql`
- Class Templates: `/tests/class-templates.test.ts` (complementary tests)

