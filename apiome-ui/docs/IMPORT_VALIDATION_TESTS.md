# Import Validation Test Suite

## Overview

The Import Validation Test Suite is a comprehensive testing framework that validates the integrity of the OpenAPI import functionality. It ensures that data is correctly imported, stored, and can be re-exported without loss or corruption.

## Architecture

### Test Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Import Validation Flow                    │
└─────────────────────────────────────────────────────────────┘

1. Parse OpenAPI YAML/JSON
   ↓
2. Import to Test Database (PostgreSQL/SQLite)
   ↓
3. Export Data from Database
   ↓
4. Validate Data Integrity
   ↓
5. Assert No Regressions

```

### Database Strategy

**Current:** PostgreSQL with test schema  
**Future:** SQLite for faster, isolated testing

The test suite creates an isolated `test_schema` that is:
- Created before all tests
- Cleared between individual tests
- Dropped after all tests complete

### Test Categories

#### 1. Basic Examples (01-09)
Tests fundamental OpenAPI 3.1 features:
- Numeric constraints (min/max, multipleOf)
- Array constraints (contains, minItems, maxItems)
- Object properties (required, additionalProperties)
- Constants and negation (const, not)
- Dependent schemas and required
- Nullable types
- Multiple examples
- Unevaluated properties/items

#### 2. Advanced Features (10-20)
Tests complex JSON Schema 2020-12 features:
- Conditional schemas (if/then/else)
- Property name constraints (pattern, length)
- Custom extensions (x-* properties)
- External documentation
- Discriminator mapping
- Deprecated features
- Prefix items (tuples)
- Enumeration handling
- Comprehensive feature combinations

#### 3. Composition Features (21-24)
Tests schema composition patterns:
- **allOf**: Inheritance and composition
- **oneOf**: Exclusive polymorphism
- **anyOf**: Flexible alternatives
- **Combined**: Multiple composition keywords

#### 4. Regression Tests (25-28)
Tests specific bug fixes and edge cases:
- Property conflict resolution
- Property signature deduplication
- Edge case handling
- Property reuse validation

#### 5. Data Integrity Tests
Validates that no data is lost during import/export:
- Schema structure preservation
- Property descriptions
- Extension properties (x-*)
- Relationship integrity
- Constraint preservation

#### 6. Smoke Tests
Imports all example files to ensure baseline functionality

## Running Tests

### Prerequisites

1. **PostgreSQL** (for now):
   ```bash
   # macOS
   brew install postgresql@16
   brew services start postgresql@16
   
   # Linux
   sudo apt-get install postgresql-16
   sudo systemctl start postgresql
   ```

2. **Create test database**:
   ```bash
   createdb apiome_test
   ```

3. **Install dependencies**:
   ```bash
   cd apiome-ui
   yarn install
   ```

### Run Tests

```bash
# Run all tests
yarn test

# Run import validation tests only
yarn test:import

# Run with coverage
yarn test:coverage

# Run in watch mode
yarn test:watch

# Run specific test file
yarn test import-validation

# Run specific test case
yarn test -t "should import 16-discriminator-mapping"

# Run with verbose output
yarn test --verbose

# Run in CI mode (no watch, single run)
yarn test --ci
```

### Environment Variables

Create `.env.test` with:

```env
TEST_POSTGRES_DB=apiome_test
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
NODE_ENV=test
```

## Test Structure

### Test File Organization

```
tests/
├── README.md                       # Test documentation
├── setup.ts                        # Jest setup
├── import-validation.test.ts       # Main test suite
└── ... (other test files)
```

### Adding New Tests

When adding a new example file:

1. **Add the file** to `examples/openapi/`:
   ```yaml
   # examples/openapi/29-new-feature.yaml
   openapi: 3.1.0
   info:
     title: New Feature Example
     version: 1.0.0
   components:
     schemas:
       NewFeature:
         type: object
         # ... schema definition
   ```

2. **Add specific test** (if demonstrating new feature):
   ```typescript
   test('should import 29-new-feature.yaml', async () => {
     const filePath = path.join(EXAMPLES_DIR, '29-new-feature.yaml');
     const result = await importOpenApiFile(filePath);

     expect(result.errors).toBe(0);
     
     const exported = await exportClasses(result.versionId);
     const feature = exported.find(c => c.name === 'NewFeature');
     
     expect(feature).toBeDefined();
     // Add feature-specific assertions
   });
   ```

3. **Smoke test automatically includes it** - no additional code needed!

## Validation Checks

### Import Phase
- ✅ File parsing (YAML/JSON)
- ✅ Schema validation
- ✅ Property extraction
- ✅ Relationship creation
- ✅ Error handling
- ✅ Warning tracking

### Export Phase
- ✅ Schema retrieval
- ✅ Property retrieval
- ✅ Relationship retrieval
- ✅ Data completeness

### Integrity Checks
- ✅ No data loss
- ✅ Type preservation
- ✅ Constraint preservation
- ✅ Description preservation
- ✅ Extension preservation
- ✅ Relationship preservation

## Continuous Integration

### GitHub Actions

The test suite runs automatically on:
- Push to `main` or `develop`
- Pull requests
- Manual workflow dispatch

See `.github/workflows/import-validation-tests.yml`

### CI Configuration

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_DB: apiome_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
```

### Coverage Reports

- **Codecov**: Automatic upload of coverage reports
- **Test Reporter**: Jest JUnit format results
- **PR Comments**: Coverage summary in PR comments

## Performance

### Current Performance

| Test Category | Files | Avg Time | Total Time |
|---------------|-------|----------|------------|
| Basic         | 9     | ~500ms   | ~4.5s      |
| Advanced      | 11    | ~600ms   | ~6.6s      |
| Composition   | 4     | ~700ms   | ~2.8s      |
| Regression    | 4     | ~500ms   | ~2s        |
| Smoke Test    | 28    | ~500ms   | ~14s       |
| **Total**     | **28**| **~500ms** | **~30s** |

### Optimization Strategies

1. **Parallel Test Execution**:
   ```bash
   yarn test --maxWorkers=4
   ```

2. **Test Isolation**:
   - Each test gets clean database
   - No test interdependencies
   - Parallel-safe execution

3. **Future: SQLite**:
   - In-memory database
   - 10x faster than PostgreSQL
   - No external dependencies

## Troubleshooting

### Common Issues

#### Database Connection Error

```
Error: connect ECONNREFUSED 127.0.0.1:5432
```

**Solution:**
```bash
# Check PostgreSQL is running
brew services list | grep postgresql

# Start PostgreSQL
brew services start postgresql@16

# Verify connection
psql -U postgres -c "SELECT 1"
```

#### Test Database Missing

```
Error: database "apiome_test" does not exist
```

**Solution:**
```bash
createdb apiome_test
```

#### Import Failures

```
Error: Failed to import schema
```

**Solution:**
1. Check example file syntax:
   ```bash
   yamllint examples/openapi/XX-file.yaml
   ```

2. Validate OpenAPI spec:
   ```bash
   npx @redocly/cli lint examples/openapi/XX-file.yaml
   ```

3. Review import logs in test output

#### Timeout Errors

```
Error: Timeout - Async callback was not invoked within the 5000 ms timeout
```

**Solution:**
- Increase timeout in `jest.config.ts`:
  ```typescript
  testTimeout: 60000, // 60 seconds
  ```

### Debug Mode

Run tests with debugging:

```bash
# Enable debug logging
DEBUG=* yarn test:import

# Run single test with verbose output
yarn test -t "should import 16-discriminator" --verbose

# Check database state during test
# (add breakpoint in test, inspect testDb)
```

## Future Enhancements

### Planned Improvements

1. **SQLite Migration**
   - In-memory testing
   - No external dependencies
   - 10x faster execution
   - Portable test database

2. **Snapshot Testing**
   - Store expected export results
   - Detect unintended changes
   - Visual diff of schemas

3. **Property Reuse Validation**
   - Verify signature-based deduplication
   - Check library property count
   - Validate cross-class property reuse

4. **Breaking Change Detection**
   - Compare schema versions
   - Detect breaking changes
   - Generate migration guides

5. **Performance Benchmarks**
   - Track import speed over time
   - Detect performance regressions
   - Optimize slow operations

6. **Visual Regression Testing**
   - Canvas layout validation
   - Node position checks
   - Edge rendering validation

## Contributing

### Adding Tests

1. Fork the repository
2. Create a feature branch
3. Add test cases to `import-validation.test.ts`
4. Run tests locally: `yarn test:import`
5. Ensure all tests pass
6. Submit a pull request

### Test Guidelines

- ✅ One assertion per test (when possible)
- ✅ Descriptive test names
- ✅ Clear error messages
- ✅ Fast execution (<1s per test)
- ✅ Isolated tests (no shared state)
- ✅ Comprehensive coverage

## Resources

- [Jest Documentation](https://jestjs.io/docs/getting-started)
- [OpenAPI 3.1 Specification](https://spec.openapis.org/oas/v3.1.0)
- [JSON Schema 2020-12](https://json-schema.org/draft/2020-12/json-schema-core)

---

**Last Updated**: December 24, 2025  
**Maintainer**: Engineering Team  
**Status**: ✅ Production Ready

