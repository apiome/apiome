# Using Response Body Schemas - User Guide

## Overview

You can now define custom schemas for operation responses using either:
- **Class References** - Link to existing classes you've defined
- **Inline Schemas** - Create free-form object schemas specific to this response
- **Multiple Content Types** - Support JSON, XML, and other media types

## Quick Start

### Step 1: Navigate to Paths Tab

1. Open your project and version
2. Click on the **Paths** tab
3. Select a path (e.g., `/users`)
4. Click on an operation (e.g., GET, POST)

### Step 2: Add a Response

1. In the **Operation Properties Panel** on the right, scroll to the **Responses** section
2. Click **Add Response**
3. Enter a status code (e.g., `200`, `201`, `404`)
4. Add a description (optional)
5. Click **Save**

### Step 3: Define Response Schema

You'll see the response listed with two options:

#### Option A: Use Class Reference

**When to use:** When the response returns a standard object you've already defined (e.g., User, Product)

1. Click **Class Reference** button
2. Select a class from the dropdown (e.g., "User")
3. The response will reference this class in the OpenAPI spec

**OpenAPI Output:**
```json
{
  "200": {
    "description": "User details",
    "content": {
      "application/json": {
        "schema": { "$ref": "#/components/schemas/User" }
      }
    }
  }
}
```

#### Option B: Use Inline Schema

**When to use:** When the response has custom fields not matching any existing class

1. Click **Inline Schema** button
2. Click **Add Property**
3. Enter property name (e.g., "status")
4. Select type (string, number, integer, boolean, array, object)
5. Click **Add**
6. Repeat for all properties

**Example: Status Response**
- Add property `status` (string)
- Add property `message` (string)
- Add property `code` (integer)

**OpenAPI Output:**
```json
{
  "200": {
    "description": "Operation status",
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "status": { "type": "string" },
            "message": { "type": "string" },
            "code": { "type": "integer" }
          }
        }
      }
    }
  }
}
```

## Advanced Features

### Multiple Content Types

**Use case:** API returns both JSON and XML

1. After defining your first content type (JSON), click **Add Content Type**
2. Select media type: `application/xml`
3. Define schema (class reference or inline)
4. Both content types will appear in tabs

**OpenAPI Output:**
```json
{
  "200": {
    "description": "User data",
    "content": {
      "application/json": {
        "schema": { "$ref": "#/components/schemas/User" }
      },
      "application/xml": {
        "schema": { "type": "object" }
      }
    }
  }
}
```

### Convert Class to Inline

**Use case:** Start with a class but need to customize it for this specific response

1. Start with **Class Reference** mode
2. Select your class
3. Click **Convert to Inline Schema**
4. All properties from the class are copied
5. Now you can add/remove properties specific to this response

### Nested Objects

**Use case:** Response has nested data structures

1. Add a parent property (e.g., "user") with type `object`
2. The property tree will show an expandable node
3. Add child properties under the parent

**Example: Nested User Response**
```json
{
  "data": {
    "type": "object",
    "properties": {
      "id": { "type": "string" },
      "profile": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "email": { "type": "string" }
        }
      }
    }
  }
}
```

## Common Response Patterns

### Success Response (200)

**Simple Success:**
```
Status: 200
Schema: Inline
Properties:
  - success (boolean)
  - data (object)
```

### Created Response (201)

**Resource Created:**
```
Status: 201
Schema: Class Reference → "User"
```

### Error Response (400/404/500)

**Error Object:**
```
Status: 400
Schema: Inline
Properties:
  - error (string)
  - message (string)
  - code (integer)
```

### List Response (200)

**Array of Items:**
```
Status: 200
Schema: Inline
Properties:
  - items (array)
  - total (integer)
  - page (integer)
```

## Best Practices

### 1. Reuse Classes When Possible

✅ **Good:**
```
GET /users/{id} → 200 response uses User class
POST /users → 201 response uses User class
```

❌ **Avoid:**
```
Creating separate inline schemas for each operation that returns the same User object
```

### 2. Use Inline Schemas for Wrappers

✅ **Good:**
```
Response with wrapper:
{
  "success": true,
  "data": { "$ref": "#/components/schemas/User" }
}
```

Use inline schema for the wrapper, reference class for the data.

### 3. Document with Descriptions

Always add descriptions to responses:
- `200` - "Successfully retrieved user details"
- `404` - "User not found"
- `500` - "Internal server error"

### 4. Define All Common Status Codes

For each operation, define:
- Success response (200, 201)
- Common errors (400, 404, 500)
- Specific errors as needed

## Troubleshooting

### Response Schema Not Showing in OpenAPI

**Check:**
1. Did you add at least one content type?
2. Did you select a class or add properties to inline schema?
3. Did you save the operation?

### Class Not Available in Dropdown

**Reason:** Classes must be defined for the same version

**Solution:**
1. Go to Canvas tab
2. Create the class
3. Return to Paths tab
4. The class will now appear in the dropdown

### Properties Not Appearing

**Reason:** Using class reference mode but properties show as empty

**Solution:** Class references don't show properties inline - they reference the class definition in components/schemas

### Can't Edit Property

**Current Limitation:** Properties can be added/deleted but not edited inline

**Workaround:**
1. Delete the property
2. Add it again with correct name/type

## Keyboard Shortcuts

(Future enhancement)

- `Ctrl/Cmd + N` - Add new property
- `Delete` - Delete selected property
- `Enter` - Save property dialog

## Tips & Tricks

### Tip 1: Start Simple

Begin with class references for standard resources (User, Product, etc.), then use inline schemas for special cases.

### Tip 2: Copy-Paste Pattern

Once you've defined an error response (400, 404, 500), you can reuse the same pattern across operations.

### Tip 3: Check Generated OpenAPI

Navigate to the **Code** tab to see the final OpenAPI specification and verify your schemas are correct.

### Tip 4: Test with Examples

(Coming soon) Add response examples to help document what the actual data looks like.

## See Also

- **Request Body Schemas** - Similar functionality for POST/PUT/PATCH request bodies
- **OpenAPI 3.1.0 Specification** - Full specification for response objects
- **Class Editor** - Define reusable schema classes

---

**Questions?** Check the technical documentation in `RESPONSE_BODY_SCHEMA_IMPLEMENTATION.md`
