# Operation ID Generation with Path Parameters

## Overview

The `generateOperationId` function now automatically generates meaningful operation IDs that include path parameters using "By" and "And" keywords.

## Naming Convention

### Without Parameters
- Path: `/api/users`
- Operation: `GET`
- **Result**: `getApiUsers`

### With Single Parameter
- Path: `/user/{userId}`
- Operation: `GET`
- **Result**: `getUserByUserid`

The keyword "**By**" is inserted before the first path parameter.

### With Multiple Parameters
- Path: `/user/{userId}/{tenantId}`
- Operation: `GET`
- **Result**: `getUserByUseridAndTenantid`

The keyword "**And**" is used to join additional path parameters.

## More Examples

### Complex Paths

```typescript
// Path: /api/groups/{groupId}/users/{userId}
// GET -> getApiGroupsUsersByGroupidAndUserid

// Path: /tenant/{tenantId}/project/{projectId}/version/{versionId}
// GET -> getTenantProjectVersionByTenantidAndProjectidAndVersionid

// Path: /organizations/{orgId}/teams/{teamId}/members
// GET -> getOrganizationsTeamsMembersByOrgidAndTeamid
```

### Different HTTP Verbs

```typescript
// Path: /user/{userId}
// POST   -> postUserByUserid
// PUT    -> putUserByUserid
// PATCH  -> patchUserByUserid
// DELETE -> deleteUserByUserid
```

## Implementation Details

The function:

1. **Splits the path** into segments
2. **Separates regular segments** from parameters (enclosed in `{}`)
3. **Converts regular segments** to camelCase
4. **Extracts parameter names** (removes curly braces)
5. **Converts parameter names** to proper casing (first letter capitalized)
6. **Joins parameters** with "And"
7. **Prepends "By"** before the first parameter
8. **Combines** verb + path + "By" + parameters

### Algorithm

```
Input:  "/user/{userId}/{tenantId}", "GET"

Step 1: Split path -> ["user", "{userId}", "{tenantId}"]
Step 2: Separate  -> regular: ["user"], params: ["userId", "tenantId"]
Step 3: CamelCase regular -> "User"
Step 4: CamelCase params  -> ["Userid", "Tenantid"]
Step 5: Join params       -> "UseridAndTenantid"
Step 6: Add "By"          -> "ByUseridAndTenantid"
Step 7: Combine           -> "get" + "User" + "ByUseridAndTenantid"

Output: "getUserByUseridAndTenantid"
```

## Special Handling

### Special Characters

Special characters in paths and parameter names are converted to proper camelCase while preserving existing camelCase patterns:

```typescript
// Path: /api_v2/user-profile
// Result: getApiV2UserProfile (preserves V2 capitalization)

// Path: /api-v2/user-profile  
// Result: getApiV2UserProfile (converts to proper camelCase)

// Path: /user/{user_id}
// Result: getUserByUserId (converts to camelCase)

// Path: /user/{user-id}
// Result: getUserByUserId (converts to camelCase)

// Path: /user/{userId}
// Result: getUserByUserId (preserves existing camelCase)
```

### Case Normalization

All-caps or all-lowercase strings are normalized to standard camelCase:

```typescript
// Path: /API/USERS/{USERID}
// Result: getApiUsersByUserid (all caps normalized)

// Path: /api/users/{userid}
// Result: getApiUsersByUserid (all lowercase normalized)
```

## Benefits

### 1. **Consistency**
Every operation with path parameters follows the same naming convention, making it easy to predict and understand operation IDs.

### 2. **Readability**
Operation IDs clearly indicate which parameters are required:
- `getUserByUserid` - obviously needs a userId
- `getUserByUseridAndTenantid` - needs both userId and tenantId

### 3. **Auto-Generation**
No need to manually specify operation IDs. The system generates appropriate IDs automatically based on the path structure.

### 4. **OpenAPI Compliance**
The generated IDs follow OpenAPI/Swagger best practices for operation naming with `operationId`.

## Testing

Comprehensive test suite included in `tests/utils/path-utils.test.ts`:

```bash
yarn test path-utils
```

All 9 test cases pass, covering:
- Paths without parameters
- Paths with single parameter
- Paths with multiple parameters
- Mixed regular and parameterized paths
- Different HTTP verbs
- Special characters handling
- Case normalization

## Usage in Application

When adding a new operation to the Paths canvas:

1. User selects a path (e.g., `/user/{userId}`)
2. User adds a GET operation
3. **System auto-generates**: `getUserByUserid`
4. User can see this in the Operation Properties Panel
5. User can modify if needed, but the default is already meaningful

## Migration Impact

Existing operations will keep their current operation IDs. The new naming convention only applies to:
- Newly created operations
- Operations that don't have a custom operation ID set

Users can update existing operations to use the new convention by:
1. Deleting the current operation ID
2. Clicking elsewhere (triggers regeneration)
3. The new convention will be applied

## Future Enhancements

Potential improvements for consideration:
- Option to customize the separator words ("By", "And")
- Support for query parameters in operation ID
- Smart pluralization (e.g., "getUsers" vs "getUser")
- Abbreviation support for long parameter names

