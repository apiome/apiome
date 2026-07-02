# Advanced Import Validation Tests

## Overview

The advanced import validation test suite (`tests/import-advanced.test.ts`) goes beyond basic file validation to test the entire import/export pipeline:

1. **Load & Parse**: Validate OpenAPI specification files
2. **Extract Structure**: Extract schemas and their properties  
3. **Database Operations**: Create projects/versions and store data
4. **Schema Recreation**: Reconstruct OpenAPI schemas from database objects
5. **Round-Trip Validation**: Ensure specifications survive the import→store→export cycle

## Test Categories

### 1. OpenAPI File Loading (3 tests)
Tests that validate OpenAPI/Swagger files can be properly loaded and parsed:

- ✅ `should load and parse 01-numeric-constraints.yaml`
- ✅ `should load and parse 16-discriminator-mapping.yaml`
- ✅ `should load and parse 21-advanced-allof-inheritance.yaml`

### 2. Schema Structure Extraction (3 tests)
Tests that validate the structure of imported schemas:

- ✅ `should extract schemas from numeric constraints spec`
- ✅ `should extract discriminator configuration`
- ✅ `should extract composition patterns`

### 3. Database Operations (2 tests)
Tests that validate database integration:

- ✅ `should skip database tests if not available`
- ✅ `should create project and version when database available`

### 4. Schema Recreation (4 tests)
Tests that validate schemas can be recreated from database objects:

- ✅ `should recreate schema from database objects`
- ✅ `should include required fields in recreated schema`
- ✅ `should preserve composition keywords` (allOf, anyOf, oneOf)
- ✅ `should preserve discriminator configuration`

### 5. Schema Comparison (4 tests)
Tests that validate the comparison logic for detecting differences:

- ✅ `should detect matching schemas`
- ✅ `should detect schema differences`
- ✅ `should detect type mismatches in properties`
- ✅ `should detect composition differences`

### 6. Round-Trip Validation (2 tests)
Tests that validate the complete import→export cycle:

- ✅ `should round-trip numeric constraints spec` - Validates numeric constraints are preserved
- ✅ `should round-trip composition schemas` - Validates composition patterns are preserved

## Test Functions

### Loading & Parsing

```typescript
loadOpenApiSpec(filePath: string): { valid: boolean; document?: any; error?: string }
```

Loads a YAML/JSON file and parses it as an OpenAPI spec. Validates that:
- File is valid YAML/JSON
- Document has an `openapi` or `swagger` field
- Schemas are properly structured

### Importing & Storing

```typescript
importOpenApiSpec(specPath: string, projectName: string): { 
  success: boolean; 
  projectId?: string; 
  versionId?: string; 
  classCount?: number;
  error?: string;
}
```

Creates a project and version in the database. Supports:
- Project creation with slug and description
- Version creation and management
- Schema counting and extraction

### Schema Recreation

```typescript
recreateOpenApiSchema(classes: any[]): { 
  components: { schemas: Record<string, any> } 
}
```

Reconstructs OpenAPI schemas from database class objects. Handles:
- Type preservation
- Property extraction
- Required field reconstruction
- Composition keyword preservation (allOf, anyOf, oneOf)
- Discriminator preservation
- Extension properties (x-*)

### Schema Comparison

```typescript
compareSchemas(
  original: Record<string, any>,
  recreated: Record<string, any>,
  schemaName: string
): { match: boolean; differences: string[] }
```

Compares original and recreated schemas. Detects:
- Type mismatches
- Missing/extra properties
- Required field differences
- Composition keyword differences
- Discriminator differences
- Property-level type mismatches

## Usage

### Run All Import Tests

```bash
yarn test import
```

### Run Only Advanced Tests

```bash
yarn test import-advanced
```

### Run Specific Test

```bash
yarn test -t "should round-trip numeric constraints spec"
```

### Watch Mode

```bash
yarn test:watch import-advanced
```

### With Coverage

```bash
yarn test:coverage import-advanced
```

## Key Features

### 1. File Validation
- Validates YAML/JSON syntax
- Checks OpenAPI/Swagger compliance
- Verifies schema structure

### 2. Database Integration
- Creates projects and versions
- Gracefully handles missing PostgreSQL
- Maintains test isolation

### 3. Schema Recreation
- Preserves property types
- Maintains required fields
- Keeps composition patterns
- Preserves discriminators
- Keeps extension properties (x-*)

### 4. Comprehensive Comparison
- Type checking
- Property count verification
- Required field validation
- Composition keyword checking
- Property-level attribute comparison

### 5. Round-Trip Testing
- Numeric constraints spec validation
- Composition schema validation
- Property preservation
- Required field preservation

## Test Data

The tests use real OpenAPI examples from `examples/openapi/`:

| File | Purpose | Features Tested |
|------|---------|-----------------|
| 01-numeric-constraints.yaml | Numeric validation | min, max, multipleOf |
| 16-discriminator-mapping.yaml | Polymorphism | Discriminator, mapping |
| 21-advanced-allof-inheritance.yaml | Composition | allOf patterns |

## Database Requirements

Tests automatically detect if PostgreSQL is available:
- If available: Full database integration testing
- If unavailable: File validation tests only

To enable database tests:

```bash
# Ensure PostgreSQL is running
brew services start postgresql@16

# Create test database
createdb apiome_test

# Run tests
yarn test import-advanced
```

## Mock Data

Tests use mock database objects simulating what would be created during import:

```typescript
{
  id: 'class-1',
  name: 'User',
  description: 'User schema',
  schema: { type: 'object' },
  properties: [
    {
      id: 'prop-1',
      name: 'id',
      data: { type: 'string', format: 'uuid' },
      description: 'User ID',
    },
    // ... more properties
  ],
}
```

## Validation Logic

### Type Checking
Validates that property types are preserved during import/export:

```typescript
// Original
{ price: { type: 'number' } }

// Recreated
{ price: { type: 'number' } }  ✅ Match
{ price: { type: 'string' } }  ❌ Mismatch
```

### Required Fields
Ensures required properties are maintained:

```typescript
// Original
{ required: ['id', 'email'] }

// Recreated must have exact same required list
{ required: ['email', 'id'] }  ✅ Match (order doesn't matter)
{ required: ['id'] }            ❌ Missing 'email'
```

### Composition Patterns
Preserves allOf, anyOf, oneOf structures:

```typescript
// Original
{
  allOf: [
    { $ref: '#/components/schemas/Person' },
    { type: 'object', properties: { ... } }
  ]
}

// Recreated must have identical allOf
{ allOf: [...] }  ✅ Match
{ anyOf: [...] }  ❌ Different pattern
```

## Example Test Output

```
PASS tests/import-advanced.test.ts
  Advanced Import Validation Tests
    OpenAPI File Loading
      ✓ should load and parse 01-numeric-constraints.yaml (5 ms)
      ✓ should load and parse 16-discriminator-mapping.yaml (2 ms)
      ✓ should load and parse 21-advanced-allof-inheritance.yaml (4 ms)
    Schema Structure Extraction
      ✓ should extract schemas from numeric constraints spec (1 ms)
      ✓ should extract discriminator configuration (1 ms)
      ✓ should extract composition patterns (3 ms)
    Database Operations (if available)
      ✓ should skip database tests if not available
      ✓ should create project and version when database available (7 ms)
    Schema Recreation
      ✓ should recreate schema from database objects
      ✓ should include required fields in recreated schema
      ✓ should preserve composition keywords
      ✓ should preserve discriminator configuration (1 ms)
    Schema Comparison
      ✓ should detect matching schemas
      ✓ should detect schema differences
      ✓ should detect type mismatches in properties
      ✓ should detect composition differences
    Round-Trip Validation
      ✓ should round-trip numeric constraints spec (1 ms)
      ✓ should round-trip composition schemas (2 ms)

Test Suites: 1 passed
Tests: 18 passed
```

## Future Enhancements

### Additional Test Coverage
- [ ] Test allOf/anyOf/oneOf with complex scenarios
- [ ] Test nested object properties
- [ ] Test array type properties
- [ ] Test ref resolution
- [ ] Test property inheritance through composition

### Advanced Validation
- [ ] Test property constraint preservation (minLength, maxLength, pattern)
- [ ] Test enum preservation
- [ ] Test default value preservation
- [ ] Test format preservation (uuid, email, etc.)
- [ ] Test example values preservation

### Integration Tests
- [ ] Test full import pipeline with actual database
- [ ] Test import from multiple example files
- [ ] Test version comparison
- [ ] Test schema diffing
- [ ] Test breaking change detection

## Troubleshooting

### Database Connection Errors
If tests fail with database errors:

1. Check PostgreSQL is running: `brew services list`
2. Verify test database exists: `psql -l | grep apiome_test`
3. Check environment variables in `.env.test`

### Test Timeout
If tests timeout:

1. Increase timeout in `jest.config.ts`
2. Check database performance
3. Review test logs with `yarn test --verbose`

### Schema Mismatch
If round-trip tests fail:

1. Check console output for difference details
2. Verify file format with `yamllint examples/openapi/XX.yaml`
3. Run single test with verbose output: `yarn test -t "should round-trip" --verbose`

## Related Documentation

- [Import Validation Tests](./IMPORT_VALIDATION_TESTS.md) - Basic file validation
- [Import Validation Test Suite Summary](./IMPORT_TEST_SUITE_SUMMARY.md) - Setup and overview
- [Main Tests README](../tests/README.md) - Test suite overview

---

**Last Updated**: December 25, 2025  
**Status**: ✅ Production Ready  
**Tests Passing**: 18/18  
**Database**: Optional (graceful degradation)

