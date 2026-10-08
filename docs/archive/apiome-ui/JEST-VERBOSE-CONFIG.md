# Jest Verbose Configuration Guide

## Overview

Jest has been configured to provide verbose, detailed output showing the pass/fail status of each individual test, rather than just a summary of test results.

---

## Configuration Changes

### 1. **jest.config.ts Updates**

Added the following verbose output options:

```typescript
// Verbose output configuration
verbose: true,              // Shows each test individually
bail: false,                // Continues running tests after failures
notify: false,              // Disables desktop notifications
notifyMode: 'failure-change',

// Built-in reporter with verbose output
reporters: [
  [
    'default',
    {
      verbose: true,
    }
  ]
],
```

### 2. **package.json Script Updates**

New and updated test scripts:

| Script | Command | Purpose |
|--------|---------|---------|
| `test` | `jest --verbose` | Run all tests with verbose output |
| `test:watch` | `jest --watch --verbose` | Watch mode with verbose output |
| `test:coverage` | `jest --coverage --verbose` | Coverage report with verbose output |
| `test:verbose` | `jest --verbose --no-coverage` | Verbose without coverage data |
| `test:db-helper` | `jest db-helper --verbose` | Test only database helper tests with verbose output |
| `test:detailed` | `jest --verbose --no-coverage --forceExit` | Most detailed output (forces exit after tests) |
| `test:import` | `jest import-validation --verbose` | Test import validation with verbose output |

---

## What You'll See

### Before (Summary Output)
```
Test Suites: 5 passed, 5 total
Tests:       209 passed, 209 total
Snapshots:   0 total
Time:        0.641 s
```

### After (Verbose Output)
```
PASS tests/db-helper.test.ts
  Database Helper - User Functions
    ✓ getUserByEmail should return user (5 ms)
    ✓ getUserById should return user by ID (2 ms)
    ✓ updateUserName should update name (3 ms)
  Database Helper - Dashboard Functions
    ✓ getDashboardStats should return stats (2 ms)
    ✓ getRecentActivity should return recent activity (1 ms)
  ... [each test listed individually]

Test Suites: 5 passed, 5 total
Tests:       209 passed, 209 total
Snapshots:   0 total
Time:        0.641 s
```

---

## Using the Configuration

### Run All Tests Verbosely (Default)
```bash
yarn test
```

### Run Specific Test Suite Verbosely
```bash
yarn test:db-helper
```

### Run with Maximum Detail (No Coverage)
```bash
yarn test:detailed
```

### Watch Mode with Verbose Output
```bash
yarn test:watch
```

### Coverage Report with Verbose Output
```bash
yarn test:coverage
```

---

## Key Features

✅ **Individual Test Results**: Each test is listed with pass/fail status  
✅ **Hierarchical Display**: Tests grouped by describe blocks  
✅ **Timing Information**: Shows milliseconds for each test  
✅ **Detailed Failures**: Error messages shown immediately when tests fail  
✅ **Progress Tracking**: See which tests are running and their outcomes  

---

## Output Format

Each test is displayed in the following format:

```
✓ testName should do something (duration ms)
✕ failingTest should do something else (duration ms)
  ● Error message details
```

Test groups (describe blocks) are indented and hierarchical:

```
PASS tests/db-helper.test.ts
  Category Name
    Subcategory Name
      ✓ Individual test (time)
      ✓ Another test (time)
```

---

## Configuration Details

### verbose: true
Shows each test individually in the output. Without this, Jest would only show a summary.

### bail: false
Continues running all tests even if some fail. This is useful for seeing all failures in one run.

### reporters: ['default', { verbose: true }]
Uses Jest's default reporter with verbose mode enabled for detailed output.

---

## Benefits

1. **Transparency**: See exactly which tests pass and which fail
2. **Debugging**: Quickly identify failing tests without having to re-run
3. **Progress Tracking**: Monitor test execution in real-time
4. **CI/CD Integration**: Detailed logs for debugging in continuous integration
5. **Comprehensive Documentation**: Each test is documented in the output

---

## Disabling Verbose Mode

If you want to revert to summary-only output, you can:

1. Run with `--no-verbose` flag:
```bash
jest --no-verbose
```

2. Or modify `jest.config.ts`:
```typescript
verbose: false, // Change this line
```

---

## Example Output

```
PASS tests/db-helper.test.ts (2.345 s)
  Database Helper - User Functions
    ✓ getUserByEmail should return user by email (5 ms)
    ✓ getUserById should return user by ID (3 ms)
    ✓ updateUserName should update user name (4 ms)
    ✓ updateUserPassword should hash and update password (8 ms)
  Database Helper - Dashboard Functions
    ✓ getDashboardStats should return aggregated stats (6 ms)
    ✓ getRecentActivity should return recent activity (4 ms)
    ✓ getRecentActivity should return activity for user (5 ms)
  Database Helper - Tenant Functions
    ✓ getTenantUsers should return users in tenant (3 ms)
    ✓ getTenantsForUser should return user's tenants (4 ms)
    ✓ getTenantsAdministratedByUser should return admin tenants (5 ms)
    ✓ addTenantAdministrator user exists branch (6 ms)
    ... [more tests]

Test Suites: 5 passed, 5 total
Tests:       286 passed, 286 total
Snapshots:   0 total
Time:        3.456 s
```

---

**Configuration Complete!** Your Jest test runner now provides verbose, detailed output for each test step.

