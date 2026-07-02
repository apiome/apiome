# Tests

## Import Validation Test Suite

The import validation test suite (`import-validation.test.ts`) ensures data integrity and prevents regressions in the import pipeline.

### Overview

This test suite:
- ✅ Imports all OpenAPI examples from `examples/openapi/`
- ✅ Re-exports the imported data from the database
- ✅ Validates data integrity (schemas, properties, relationships)
- ✅ Detects regressions in the import functionality
- ✅ Uses isolated test database for fast, reliable testing

### Running Tests

```bash
# Run all tests
yarn test

# Run import validation tests only
yarn test import-validation

# Run with coverage
yarn test --coverage

# Run in watch mode
yarn test --watch

# Run with verbose output
yarn test --verbose
```

### Test Categories

#### 1. Basic Examples
Tests fundamental import features:
- Numeric constraints
- Array constraints
- Object properties
- Constants and negation

#### 2. Advanced Features
Tests complex OpenAPI 3.1 features:
- Discriminator mapping
- Prefix items (tuples)
- Comprehensive features
- Conditional schemas

#### 3. Composition Features
Tests schema composition:
- allOf (inheritance)
- oneOf (polymorphism)
- anyOf (flexible composition)
- Combined composition

#### 4. Regression Tests
Tests specific bug fixes and edge cases:
- Property conflicts
- Property edge cases
- Mixed properties
- Property reuse

#### 5. Data Integrity Tests
Validates data preservation:
- Schema properties
- Property descriptions
- Extension properties (x-*)
- Relationship integrity

#### 6. Smoke Tests
Imports all examples to ensure none fail

### Test Database

The test suite uses a separate test database to avoid affecting production data:

**Environment Variables:**
```bash
TEST_POSTGRES_DB=apiome_test
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
```

**Database Schema:**
The test suite creates a `test_schema` with the necessary tables and automatically cleans up after tests.

### Adding New Tests

When adding new example files to `examples/openapi/`:

1. The smoke test will automatically include it
2. Add specific validation tests if the file demonstrates unique features
3. Follow the existing test structure:

```typescript
test('should import XX-feature-name.yaml', async () => {
  const filePath = path.join(EXAMPLES_DIR, 'XX-feature-name.yaml');
  const result = await importOpenApiFile(filePath);

  expect(result.errors).toBe(0);
  expect(result.classesCreated).toBeGreaterThan(0);

  // Export and validate specific features
  const exported = await exportClasses(result.versionId);
  // Add assertions...
});
```

### Continuous Integration

Add to CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Run Import Validation Tests
  run: |
    yarn install
    yarn test import-validation --ci
  env:
    TEST_POSTGRES_DB: apiome_test
```

### Troubleshooting

**Database connection errors:**
- Ensure PostgreSQL is running
- Check environment variables
- Verify test database exists

**Import failures:**
- Check example file syntax
- Review import logs
- Validate schema structure

**Test timeout:**
- Increase timeout in `jest.config.ts`
- Optimize import operations
- Check database performance

## Other Tests Directory

This directory contains test files for the Apiome UI utilities.

## Running Tests

The test files in this directory are excluded from the Next.js build process.

### TypeScript DTO Generator Test

To run the TypeScript DTO generator test:

```bash
npx ts-node tests/test-typescript-dto.ts
```

Or with Node.js directly:

```bash
node -r ts-node/register tests/test-typescript-dto.ts
```

## Test Files

- `test-typescript-dto.ts` - Tests the TypeScript DTO generator utility
  - Validates interface generation
  - Tests nested object handling
  - Verifies composition types (allOf, oneOf, anyOf)
  - Checks enum generation
  - Validates required vs optional properties

## Note

These test files are excluded from the TypeScript compilation in `tsconfig.json` to prevent them from being included in the Next.js build process.

