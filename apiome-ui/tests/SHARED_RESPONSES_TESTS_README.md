# Shared Path Responses - Test Suite

This directory contains comprehensive tests for the shared path responses feature, which allows multiple operations to share the same response definitions.

## Test Structure

```
tests/
├── db/
│   └── helper-shared-path-responses.test.ts     # Database helper tests
├── components/
│   ├── PathResponseNode.test.tsx                # Response node component tests
│   └── OperationPropertiesPanel-responses.test.tsx  # Properties panel tests
├── integration/
│   └── paths-canvas-response-linking.test.tsx   # Canvas edge linking tests
└── e2e/
    └── SHARED_RESPONSES_E2E_PLAN.md            # E2E test plan
```

## Database Tests

### SQL Migration Tests
Located in: `apiome-db/scripts/test_shared_path_responses_migration.sql`

Tests database schema, constraints, indexes, and data migration.

**Run:**
```bash
cd apiome-db
psql -U postgres -d apiome_test -f scripts/test_shared_path_responses_migration.sql
```

**What it tests:**
- Table structure correctness
- Index creation
- Foreign key constraints
- Unique constraints
- Data migration accuracy
- Cascade delete behavior

### Helper Function Tests
Located in: `tests/db/helper-shared-path-responses.test.ts`

Tests all CRUD operations for shared responses.

**Run:**
```bash
yarn test:responses
```

**Coverage:**
```bash
yarn test:responses:coverage
```

**What it tests:**
- Creating shared responses
- Retrieving responses for paths
- Linking responses to operations
- Unlinking responses from operations
- Updating response details
- Deleting responses
- Edge cases and error handling

## Component Tests

### PathResponseNode Tests
Located in: `tests/components/PathResponseNode.test.tsx`

Tests the visual response node component.

**Run:**
```bash
yarn test:response-node
```

**What it tests:**
- Rendering different status codes (2XX, 3XX, 4XX, 5XX)
- Color coding based on status
- Icon display
- Delete button functionality
- Styling and CSS classes
- Accessibility features

### OperationPropertiesPanel Tests
Located in: `tests/components/OperationPropertiesPanel-responses.test.tsx`

Tests the response management UI in the properties panel.

**Run:**
```bash
yarn test tests/components/OperationPropertiesPanel-responses
```

**What it tests:**
- Loading and displaying responses
- Adding new responses
- Unlinking responses
- Form validation
- Error handling
- User interactions

## Integration Tests

### Canvas Response Linking Tests
Located in: `tests/integration/paths-canvas-response-linking.test.tsx`

Tests the full flow of linking responses via canvas edges.

**Run:**
```bash
yarn test:response-linking
```

**What it tests:**
- Loading responses on canvas
- Creating edges between operations and responses
- Deleting edges to unlink responses
- Multiple operations sharing same response
- Canvas refresh after operations
- Error handling

## Running All Tests

### Run All Response Tests
```bash
yarn test:all-responses
```

### Run All Tests with Coverage
```bash
yarn test:coverage
```

### Run Tests in Watch Mode
```bash
yarn test:watch
```

## Test Coverage Goals

- **Unit Tests**: 90%+ coverage
- **Integration Tests**: All major user flows
- **E2E Tests**: All user scenarios from test plan

### View Coverage Report
```bash
yarn test:coverage
# Open coverage/lcov-report/index.html in browser
```

## Writing New Tests

### Database Helper Test Template
```typescript
describe('Feature Name', () => {
  beforeAll(async () => {
    // Setup test data
  });

  afterAll(async () => {
    // Cleanup test data
  });

  it('should do something', async () => {
    const result = await helperFunction('param');
    const parsed = JSON.parse(result);
    
    expect(parsed.success).toBe(true);
    expect(parsed.data).toBeDefined();
  });
});
```

### Component Test Template
```typescript
describe('Component Name', () => {
  it('should render correctly', () => {
    render(<Component prop="value" />);
    
    expect(screen.getByText('Expected Text')).toBeInTheDocument();
  });

  it('should handle interaction', async () => {
    const mockCallback = jest.fn();
    render(<Component onAction={mockCallback} />);
    
    const button = screen.getByRole('button');
    fireEvent.click(button);
    
    expect(mockCallback).toHaveBeenCalled();
  });
});
```

## Continuous Integration

These tests are run automatically on:
- Pre-commit hooks
- Pull request creation
- Main branch pushes
- Release builds

## Troubleshooting

### Tests Failing Locally

1. **Database connection issues:**
   ```bash
   yarn test:setup  # Reset test database
   ```

2. **Stale snapshots:**
   ```bash
   yarn test -u  # Update snapshots
   ```

3. **Module resolution errors:**
   ```bash
   rm -rf node_modules .next
   yarn install
   ```

### Tests Pass Locally but Fail in CI

- Check environment variables
- Verify database migrations are applied
- Check timezone differences
- Verify all dependencies are installed

## Test Data

### Sample Test Data
```typescript
const testPath = '/api/users/{id}';
const testOperations = ['GET', 'POST', 'PUT', 'DELETE'];
const testResponses = [
  { code: '200', desc: 'Success' },
  { code: '404', desc: 'Not found' },
  { code: '500', desc: 'Server error' },
];
```

### Cleanup
All tests use transactions or cleanup hooks to ensure test data doesn't persist.

## Performance Testing

### Load Tests
```bash
# Run with many responses
yarn test:responses -- --testNamePattern="Load Test"
```

### Benchmark Tests
```bash
# Run with timing measurements
yarn test --verbose --testTimeout=30000
```

## Documentation

- [E2E Test Plan](./e2e/SHARED_RESPONSES_E2E_PLAN.md) - Comprehensive E2E testing scenarios
- [Database Migration](../../apiome-db/scripts/shared_path_responses_migration.sql) - SQL migration
- [Helper Functions](../../lib/db/helper-shared-path-responses.ts) - Database helper implementation

## Contributing

When adding new features to shared responses:

1. Write tests first (TDD approach)
2. Ensure all tests pass
3. Update this README if needed
4. Check coverage remains above 90%
5. Update E2E test plan with new scenarios

## Questions?

See the main project README or ask in the development channel.

