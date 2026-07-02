# Class Template Tests Documentation

## Overview

This document describes the comprehensive test suite for class template creation and parsing functionality in Apiome.

## Test File

**Location**: `/tests/class-templates.test.ts`

## Test Coverage

The test suite includes 30 tests covering the following areas:

### 1. Class Template Categories (2 tests)

Tests the categorization system for templates:

- **Expected Categories**:
  - Addresses, Common, Content, Integrations
  - Notifications, Orders, Payments, Products
  - Security, User & Auth
  - Analytics, Communication, Compliance
  - Marketplace, Scheduling, Support

**Tests**:
- ✅ Fetch all template categories
- ✅ Fetch categories filtered by tenant

### 2. Class Template Schema Validation (4 tests)

Validates OpenAPI schema structure and content:

**Sample Templates Tested**:
- **Address** (Addresses category): street, city, state, country, postalCode
- **User** (User & Auth category): id, email, username, createdAt
- **Product** (Products category): id, name, description, price, currency

**Tests**:
- ✅ Validate required fields in template schema
- ✅ Validate OpenAPI schema structure (type, properties)
- ✅ Validate property types (string, number, integer, boolean, array, object)
- ✅ Validate required fields exist in properties

### 3. Class Template CRUD Operations (11 tests)

#### getClassTemplates (3 tests)
- ✅ Retrieve all templates
- ✅ Filter templates by category
- ✅ Filter templates by tenant

#### searchClassTemplates (2 tests)
- ✅ Search templates by name
- ✅ Search templates by tags

#### createClassTemplate (2 tests)
- ✅ Create a new template
- ✅ Handle duplicate template names (23505 error)

#### updateClassTemplate (3 tests)
- ✅ Update a template
- ✅ Prevent updating system templates
- ✅ Prevent updating templates from other tenants

#### deleteClassTemplate (2 tests)
- ✅ Soft delete a template
- ✅ Prevent deleting system templates

### 4. Class Template Dependencies (6 tests)

Tests the dependency management between templates:

#### getTemplateDependencies (1 test)
- ✅ Retrieve dependencies for a template

#### addTemplateDependency (3 tests)
- ✅ Add a dependency
- ✅ Prevent duplicate dependencies (23505 error)
- ✅ Prevent self-referencing dependencies (23514 check constraint)

#### removeTemplateDependency (1 test)
- ✅ Remove a dependency

### 5. Class Template Usage (3 tests)

Tests the actual usage of templates to create classes:

**Tests**:
- ✅ Return error when template not found
- ✅ Handle existing class gracefully (skip with existing ID)
- ✅ Prevent infinite loops in dependencies

### 6. Class Template Schema Parsing (3 tests)

Tests JSON schema parsing capabilities:

**Tests**:
- ✅ Parse JSON schema correctly
- ✅ Handle complex nested schemas (user.profile.name structure)
- ✅ Handle $ref links in schemas (#/components/schemas/Address)

### 7. Class Template Integration (1 test)

Tests how multiple templates work together:

**Tests**:
- ✅ Create a complete order system from templates (Order depends on Address and User)

## Test Statistics

```
Test Suites: 1 passed, 1 total
Tests:       30 passed, 30 total
Time:        ~0.4-0.5s
Code Coverage: ~54% of helper-class-templates.ts
```

## Running the Tests

```bash
# Run class template tests only
yarn test tests/class-templates.test.ts

# Run with coverage
yarn test:coverage tests/class-templates.test.ts

# Run in watch mode
yarn test --watch tests/class-templates.test.ts
```

## Test Patterns Used

### Mocking
- Database connection pool mocked
- Individual query results mocked
- Error conditions simulated (duplicate keys, check constraints)

### Assertions
- Success/failure responses validated
- Error messages checked for correctness
- Data structure validation
- Permission checks verified

### Test Data
The tests use realistic sample schemas matching the suggested template categories:

```typescript
// Address Template Example
{
  type: 'object',
  required: ['street', 'city', 'country'],
  properties: {
    street: { type: 'string', description: 'Street address' },
    city: { type: 'string', description: 'City name' },
    state: { type: 'string', description: 'State or province' },
    country: { type: 'string', pattern: '^[A-Z]{2}$' },
    postalCode: { type: 'string', description: 'Postal/ZIP code' }
  }
}
```

## Error Handling Tested

- **23505**: Duplicate key violations (template names, dependencies)
- **23514**: Check constraint violations (self-referencing)
- **Not Found**: Missing templates or resources
- **Permission Denied**: Cross-tenant access, system template modifications
- **Circular Dependencies**: Infinite loop prevention

## Future Enhancements

Potential areas for additional test coverage:

1. **Performance Tests**: Large template sets, deep dependency chains
2. **Integration Tests**: Full end-to-end template usage with real database
3. **Validation Tests**: Schema validation against OpenAPI spec
4. **Migration Tests**: Template version upgrades
5. **Bulk Operations**: Multiple template operations in transactions

## Related Files

- Implementation: `/lib/db/helper-class-templates.ts`
- UI Component: `/src/app/components/ade/studio/ClassTemplateBrowserDialog.tsx`
- Database Schema: `/apiome-db/scripts/20260109-130000.sql` (class_templates table)

