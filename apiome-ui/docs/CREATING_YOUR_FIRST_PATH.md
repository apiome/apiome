# Creating Your First Path - Quick Start Guide

## Problem

You're seeing `"paths": {}` in the Code tab's OpenAPI output, which means no paths have been created yet for your version.

## Solution: Create a Test Path

Follow these steps to create your first path and verify the system works:

### Step 1: Navigate to Paths Tab

1. Open your application
2. Select your **Project** from the dropdown
3. Select your **Version** from the dropdown
4. Click on the **"Paths"** tab in the navigation

### Step 2: Create a New Path

1. In the Paths tab, look for the **sidebar** on the left
2. Click the **"+ New Path"** button (or similar)
3. Enter a path pattern:
   - Simple path: `/users`
   - Path with parameter: `/users/{userId}`
   - Nested path: `/api/v1/products`

4. Optionally add:
   - **Summary**: Brief description (e.g., "User operations")
   - **Description**: Detailed description

5. Click **"Create"** or **"Save"**

### Step 3: Add an Operation

Your path needs at least one operation (HTTP method):

1. Click on the path you just created in the canvas
2. In the properties panel, click **"Add Operation"**
3. Select an HTTP method:
   - **GET** - Retrieve data
   - **POST** - Create new resource
   - **PUT** - Update entire resource
   - **PATCH** - Partial update
   - **DELETE** - Remove resource

4. Fill in operation details:
   - **Summary**: What the operation does (e.g., "Get user by ID")
   - **Operation ID**: Unique identifier (e.g., "getUserById")
   - **Description**: Detailed description
   - **Tags**: Categorize the operation

5. Click **"Save"**

### Step 4: Add a Response

Every operation should have at least one response:

1. With the operation selected, scroll to the **"Responses"** section
2. Click **"Add Response"**
3. Enter a status code:
   - **200** - Success
   - **201** - Created
   - **400** - Bad Request
   - **404** - Not Found
   - **500** - Server Error

4. Add a description (e.g., "Successful response")
5. Optionally link a schema (class) for the response body
6. Click **"Save"**

### Step 5: Verify in Code Tab

1. Navigate to the **"Code"** tab
2. Select **OpenAPI** from the format dropdown
3. You should now see your path in the output:

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "My API",
    "version": "1.0.0"
  },
  "paths": {
    "/users": {
      "get": {
        "summary": "Get all users",
        "operationId": "getUsers",
        "responses": {
          "200": {
            "description": "Successful response"
          }
        }
      }
    }
  },
  "components": {
    "schemas": {}
  }
}
```

### Step 6: Check Browser Console

Open the browser DevTools (F12) and check the Console tab. You should see:

```
[Code Tab] Loading paths for version: <uuid>
[Paths Export] Found 1 paths in database
[Code Tab] Found 1 paths
[Paths Generator] Building path: /users with 1 operations
[Code Tab] Generated 1 OpenAPI path entries
[OpenAPI Generator] Template data paths count: 1
```

## Complete Example: REST API Endpoint

Here's a complete example for creating a full REST endpoint:

### Path: `/users/{userId}`

**Operations:**

1. **GET** - Get user by ID
   - Parameter: `userId` (path, required, type: string)
   - Response 200: User object
   - Response 404: Not found

2. **PUT** - Update user
   - Parameter: `userId` (path, required, type: string)
   - Request Body: User object (required)
   - Response 200: Updated user
   - Response 404: Not found

3. **DELETE** - Delete user
   - Parameter: `userId` (path, required, type: string)
   - Response 204: No content
   - Response 404: Not found

### Expected OpenAPI Output

```json
{
  "paths": {
    "/users/{userId}": {
      "get": {
        "summary": "Get user by ID",
        "operationId": "getUserById",
        "parameters": [
          {
            "name": "userId",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/User"
                }
              }
            }
          },
          "404": {
            "description": "User not found"
          }
        }
      },
      "put": {
        "summary": "Update user",
        "operationId": "updateUser",
        "parameters": [
          {
            "name": "userId",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/User"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "User updated",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/User"
                }
              }
            }
          },
          "404": {
            "description": "User not found"
          }
        }
      },
      "delete": {
        "summary": "Delete user",
        "operationId": "deleteUser",
        "parameters": [
          {
            "name": "userId",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "204": {
            "description": "User deleted"
          },
          "404": {
            "description": "User not found"
          }
        }
      }
    }
  }
}
```

## Troubleshooting

### Issue: Path created but not showing in Code tab

**Check:**
1. Same version selected in both tabs?
2. Did you click "Save"?
3. Does the path have at least one operation?
4. Does the operation have at least one response?

**Console logs to look for:**
```
[Paths Export] Found 1 paths in database
[Paths Generator] Building path: /users with 0 operations  ← Problem!
```

**Solution:** Add operations to your path.

### Issue: Operation created but no parameters/request body

This is normal - parameters and request bodies are optional. However:

- **Path parameters** (e.g., `{userId}`) should be defined as parameters
- **POST/PUT/PATCH** operations typically have request bodies
- All operations should have at least one response

### Issue: Changes not reflecting in Code tab

**Try:**
1. Refresh the page
2. Re-select the version in the Code tab dropdown
3. Check browser console for errors
4. Verify the path was saved (check Paths tab canvas)

## Next Steps

Once you've verified the system works with a test path:

1. **Design your API** - Plan your paths and operations
2. **Create paths systematically** - One path at a time
3. **Add details** - Parameters, request bodies, responses
4. **Use classes** - Link to existing schema classes for type safety
5. **Export** - Use the Code tab to generate OpenAPI specs
6. **Generate code** - Use the OpenAPI spec with code generators

## Resources

- **Debugging Guide**: `docs/PATHS_CODE_TAB_DEBUGGING.md`
- **SQL Diagnostics**: `apiome-db/scripts/diagnostic-paths-code-tab.sql`
- **Quick Check**: `apiome-db/scripts/quick-paths-check.sql`
- **Implementation Summary**: `docs/PATHS_CODE_TAB_IMPLEMENTATION_SUMMARY.md`

---

**Need help?** Check the browser console logs - they'll tell you exactly what's happening!
