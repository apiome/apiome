# End-to-End Test Plan: Shared Path Responses

## Overview
This document outlines the end-to-end testing strategy for the shared path responses feature, which allows multiple operations to share the same response definitions.

## Test Environment Setup

### Prerequisites
1. Database with migration `shared_path_responses_migration.sql` applied
2. Test tenant, project, and version created
3. Test path created (e.g., `/api/users/{id}`)
4. Multiple operations created on the path (GET, POST, PUT)

### Database Setup
```sql
-- Run before E2E tests
BEGIN;

-- Create test data
INSERT INTO apiome.tenant (id, name) VALUES ('test-tenant-id', 'Test Tenant');
INSERT INTO apiome.project (id, tenant_id, name) VALUES ('test-project-id', 'test-tenant-id', 'Test Project');
INSERT INTO apiome.version (id, project_id, version) VALUES ('test-version-id', 'test-project-id', '1.0.0');
INSERT INTO apiome.version_path (id, version_id, pathname) VALUES ('test-path-id', 'test-version-id', '/api/users/{id}');

COMMIT;
```

## Test Scenarios

### Scenario 1: Creating Shared Responses
**Objective:** Verify that responses can be created and appear on the canvas

**Steps:**
1. Navigate to Paths page
2. Select the test path from sidebar
3. Click on GET operation node
4. In Operation Properties Panel, click "Add Response"
5. Enter status code: "200"
6. Enter description: "User retrieved successfully"
7. Click "Save"

**Expected Results:**
- Response is saved to `shared_path_response` table
- Link is created in `path_operation_response_link` table
- Response node appears on canvas at x:700
- Purple edge connects GET operation to 200 response
- Response shows in Operation Properties Panel
- Canvas refreshes automatically

**SQL Verification:**
```sql
SELECT * FROM apiome.shared_path_response WHERE status_code = '200';
SELECT * FROM apiome.path_operation_response_link WHERE shared_path_response_id = '<response-id>';
```

### Scenario 2: Sharing Response Across Multiple Operations
**Objective:** Verify that same response can be used by multiple operations

**Steps:**
1. With 200 response already created, click POST operation node
2. Click "Add Response"
3. Enter status code: "200" (same as before)
4. Enter any description
5. Click "Save"

**Expected Results:**
- No new response created in `shared_path_response`
- New link created in `path_operation_response_link`
- Purple edge appears from POST to existing 200 response node
- Same 200 response node now has edges from both GET and POST
- Both operations show the response in their properties

**SQL Verification:**
```sql
-- Should return 1 row (shared response)
SELECT COUNT(*) FROM apiome.shared_path_response WHERE status_code = '200';

-- Should return 2 rows (links to GET and POST)
SELECT COUNT(*) FROM apiome.path_operation_response_link 
WHERE shared_path_response_id = '<response-id>';
```

### Scenario 3: Linking via Canvas Edge
**Objective:** Verify that dragging edges creates database links

**Steps:**
1. Ensure PUT operation exists without 200 response
2. Hover over PUT operation node until handle appears
3. Click and drag from PUT operation handle
4. Drop on existing 200 response node

**Expected Results:**
- Edge appears connecting PUT to 200 response
- New link created in database
- PUT operation properties now shows 200 response
- No confirmation dialog (immediate save)

**SQL Verification:**
```sql
SELECT * FROM apiome.path_operation_response_link 
WHERE path_operation_id = '<put-operation-id>' 
AND shared_path_response_id = '<response-200-id>';
```

### Scenario 4: Unlinking via Properties Panel
**Objective:** Verify unlinking removes link but keeps shared response

**Steps:**
1. Click GET operation node
2. In properties panel, find 200 response
3. Click unlink/delete button next to 200 response
4. Confirm in dialog

**Expected Results:**
- Confirmation dialog says "unlink" not "delete"
- Dialog mentions "still be available for other operations"
- Link removed from database
- Edge from GET to 200 disappears
- 200 response node still visible (used by POST and PUT)
- GET properties no longer shows 200 response

**SQL Verification:**
```sql
-- Link should be gone
SELECT COUNT(*) FROM apiome.path_operation_response_link 
WHERE path_operation_id = '<get-operation-id>' 
AND shared_path_response_id = '<response-200-id>';
-- Should return 0

-- Response should still exist
SELECT COUNT(*) FROM apiome.shared_path_response 
WHERE id = '<response-200-id>';
-- Should return 1
```

### Scenario 5: Unlinking via Edge Deletion
**Objective:** Verify deleting edge removes link

**Steps:**
1. Click on purple edge from POST to 200 response
2. Press Delete key or right-click and delete

**Expected Results:**
- Edge disappears
- Link removed from database
- Response node still visible (used by PUT)
- POST properties no longer shows 200 response

### Scenario 6: Wildcard Status Codes
**Objective:** Verify wildcard responses work correctly

**Steps:**
1. Click GET operation
2. Add response with status code "2XX"
3. Add description "Any success response"
4. Save

**Expected Results:**
- 2XX response created as separate response
- Shows on canvas with green/success styling
- Can be linked to multiple operations
- Listed alongside specific status codes

### Scenario 7: Multiple Different Responses
**Objective:** Verify operations can have multiple different responses

**Steps:**
1. Click GET operation
2. Add response: 200 "Success"
3. Add response: 404 "Not found"
4. Add response: 500 "Server error"

**Expected Results:**
- All three responses appear on canvas
- All three have edges to GET operation
- Each response has appropriate color:
  - 200: Green (success)
  - 404: Orange (client error)
  - 500: Red (server error)
- All three listed in GET properties

### Scenario 8: Canvas Refresh After Changes
**Objective:** Verify canvas updates properly after operations

**Steps:**
1. Add response via properties panel
2. Observe canvas
3. Add response via edge drag
4. Observe canvas
5. Remove response via properties panel
6. Observe canvas

**Expected Results:**
- Canvas updates automatically after each operation
- No full page reload required
- Node positions maintained
- Edges render correctly after each change

### Scenario 9: Error Handling
**Objective:** Verify proper error handling

**Steps:**
1. Try to link response with invalid operation ID
2. Try to unlink non-existent link
3. Try to delete response while still linked
4. Try to create response with empty status code

**Expected Results:**
- Appropriate error messages shown
- UI state remains consistent
- No database corruption
- User can retry after fixing error

### Scenario 10: Cascade Delete
**Objective:** Verify database cascade behavior

**Steps:**
1. Create operation with linked responses
2. Delete the operation
3. Check database

**Expected Results:**
- Operation deleted
- Links in `path_operation_response_link` deleted (CASCADE)
- Shared responses remain (not deleted)
- Canvas updates correctly

**SQL Verification:**
```sql
-- Links should be gone
SELECT COUNT(*) FROM apiome.path_operation_response_link 
WHERE path_operation_id = '<deleted-operation-id>';
-- Should return 0

-- Responses should still exist
SELECT COUNT(*) FROM apiome.shared_path_response 
WHERE version_path_id = '<path-id>';
-- Should return original count
```

## Performance Tests

### Load Test 1: Many Responses
- Create 50 responses for a single path
- Verify canvas renders performantly
- Verify all responses load correctly

### Load Test 2: Many Links
- Create 10 operations
- Link 20 responses to each operation
- Verify edges render correctly
- Verify no UI lag

### Load Test 3: Concurrent Operations
- Multiple users adding/removing responses simultaneously
- Verify no race conditions
- Verify database consistency

## Automated Test Execution

### Run Database Tests
```bash
cd apiome-db
psql -U postgres -d apiome -f scripts/test_shared_path_responses_migration.sql
```

### Run Unit Tests
```bash
cd apiome-ui
yarn test helper-shared-path-responses
yarn test PathResponseNode
yarn test OperationPropertiesPanel-responses
```

### Run Integration Tests
```bash
yarn test paths-canvas-response-linking
```

### Run E2E Tests (Playwright)
```bash
yarn test:e2e paths-responses
```

## Test Coverage Goals

- Unit tests: 90%+ coverage
- Integration tests: All major flows covered
- E2E tests: All user scenarios covered
- Database tests: All constraints verified

## Regression Testing

After any changes to:
- Database schema
- Helper functions
- Canvas components
- Property panels

Run full test suite:
```bash
yarn test:all
```

## Known Issues / Edge Cases

1. **Very long status codes**: May need truncation in UI
2. **Special characters in descriptions**: Need proper escaping
3. **Rapid clicking**: Debouncing may be needed
4. **Network delays**: Loading states must be clear

## Success Criteria

✅ All database tests pass
✅ All unit tests pass (90%+ coverage)
✅ All integration tests pass
✅ All E2E scenarios complete successfully
✅ No memory leaks in canvas
✅ Performance under load acceptable
✅ No SQL injection vulnerabilities
✅ Proper error handling throughout

