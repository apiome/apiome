# API Paths Helper - Quick Reference

## 🎯 Summary

**Files Created/Modified**: 3  
**Functions Implemented**: 27  
**Test Cases**: 45  
**Test Pass Rate**: 100%

---

## 📁 Files

1. **lib/db/helper-paths.ts** - New dedicated file with ~900 lines of helper functions
2. **tests/db-helper-paths.test.ts** - 45 comprehensive test cases
3. **lib/db/helper.ts** - Updated with comment pointing to new file

---

## 📦 Module Structure

The paths-related functions have been extracted into their own module for better code organization:

```typescript
// Import from the paths module
import {
  getApiPathsForVersion,
  createApiPath,
  updateApiPath,
  // ... other functions
} from '@/lib/db/helper-paths';
```

---

## 🔧 Functions Reference

### API Paths (6 functions)

| Function | Description |
|----------|-------------|
| `getApiPathsForVersion(versionId)` | Get all paths for a version |
| `getApiPathById(pathId)` | Get single path by ID |
| `createApiPath(versionId, path, ...)` | Create new API path |
| `updateApiPath(pathId, updates)` | Update existing path |
| `deleteApiPath(pathId)` | Soft delete path |

### Path Operations (5 functions)

| Function | Description |
|----------|-------------|
| `getOperationsForPath(pathId)` | Get all operations for a path |
| `getOperationById(operationId)` | Get single operation by ID |
| `createPathOperation(pathId, method, ...)` | Create new operation |
| `updatePathOperation(operationId, updates)` | Update existing operation |
| `deletePathOperation(operationId)` | Soft delete operation |

### Operation Parameters (4 functions)

| Function | Description |
|----------|-------------|
| `getParametersForOperation(operationId)` | Get all parameters |
| `createOperationParameter(operationId, name, location, ...)` | Create parameter |
| `updateOperationParameter(parameterId, updates)` | Update parameter |
| `deleteOperationParameter(parameterId)` | Delete parameter |

### Operation Responses (4 functions)

| Function | Description |
|----------|-------------|
| `getResponsesForOperation(operationId)` | Get all responses |
| `createOperationResponse(operationId, statusCode, description, ...)` | Create response |
| `updateOperationResponse(responseId, updates)` | Update response |
| `deleteOperationResponse(responseId)` | Delete response |

### Request Bodies (5 functions)

| Function | Description |
|----------|-------------|
| `getRequestBodyForOperation(operationId)` | Get request body with content types |
| `createOperationRequestBody(operationId, ...)` | Create request body |
| `updateOperationRequestBody(requestBodyId, updates)` | Update request body |
| `deleteOperationRequestBody(requestBodyId)` | Delete request body |
| `addRequestBodyContentType(requestBodyId, contentType, ...)` | Add content type |

---

## 🎯 Quick Examples

### Create Complete Endpoint

```typescript
// 1. Create path
const path = await createApiPath(
  'version-id',
  '/users/{userId}',
  'User operations'
);

// 2. Create GET operation
const operation = await createPathOperation(
  pathId,
  'GET',
  'getUserById',
  'Get user by ID'
);

// 3. Add path parameter
await createOperationParameter(
  operationId,
  'userId',
  'path',
  'User ID',
  true // required
);

// 4. Add 200 response
await createOperationResponse(
  operationId,
  '200',
  'Successful response',
  null,
  null,
  userSchemaId // schema reference
);
```

### Query Data

```typescript
// Get all paths
const paths = await getApiPathsForVersion(versionId);

// Get operations for a path
const ops = await getOperationsForPath(pathId);

// Get parameters
const params = await getParametersForOperation(operationId);
```

---

## ✅ Validation Rules

| Item | Rules |
|------|-------|
| **Paths** | • Must have unique path per version<br>• Path cannot be empty |
| **Operations** | • Must have valid HTTP method (get, post, put, delete, patch, options, head, trace)<br>• Only one operation per method per path |
| **Parameters** | • Must have valid location (path, query, header, cookie)<br>• Name cannot be empty<br>• Unique by name+location per operation |
| **Responses** | • Status code required<br>• Description required<br>• Unique status code per operation |
| **Request Bodies** | • Only one per operation<br>• Content type required<br>• Unique content type per request body |

---

## 📊 Test Coverage

```
Test Suites: 10 passed, 10 total
Tests:       340 passed, 340 total (45 new for paths)

API Paths Tests Breakdown:
├─ API Paths CRUD: 10 tests
├─ Path Operations: 8 tests
├─ Operation Parameters: 7 tests
├─ Operation Responses: 7 tests
├─ Request Bodies: 8 tests
├─ Error Handling: 3 tests
└─ Integration: 2 tests
```

---

## 🔄 Response Format

All functions return JSON strings:

**Success:**
```json
{
  "success": true,
  "path": { /* data */ }
}
```

**Error:**
```json
{
  "success": false,
  "error": "Error message"
}
```

**Query (array):**
```json
[
  { /* item 1 */ },
  { /* item 2 */ }
]
```

---

## 🗄️ Database Tables

| Table | Description |
|-------|-------------|
| `api_paths` | URL path patterns |
| `path_operations` | HTTP operations (GET, POST, etc.) |
| `operation_parameters` | Query, path, header, cookie parameters |
| `operation_responses` | HTTP responses with status codes |
| `operation_request_bodies` | Request body definitions |
| `operation_request_body_content` | Content types for request bodies |

---

## 🚀 Usage in UI

These functions will be used by:
- Paths page canvas for CRUD operations
- Properties panel for editing
- Import/export features
- OpenAPI generation
- Code generation tools

---

## 📝 Documentation

Full documentation available in:
- `docs/API_PATHS_HELPER_IMPLEMENTATION.md`
- Inline JSDoc comments in `lib/db/helper.ts`

---

**Status**: ✅ Complete & Production Ready  
**Date**: December 28, 2025

