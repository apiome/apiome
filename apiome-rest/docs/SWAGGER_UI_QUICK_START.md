# Quick Start Guide: Swagger UI Endpoint

## What Was Added

A new endpoint that presents OpenAPI schemas in an interactive Swagger UI interface.

## The Endpoint

```
GET /v1/{tenant-slug}/{project-slug}/{version-slug}/swagger
```

## Quick Examples

### Example 1: Public Version
```bash
# Simply open in your browser:
http://localhost:8000/v1/acme-corp/customer-api/1.0.0/swagger
```

### Example 2: Private Version
For private versions, you need to include an API key. You can:

**Option A: Use curl to check access**
```bash
curl -H "X-API-Key: your-api-key-here" \
  http://localhost:8000/v1/acme-corp/internal-api/1.0.0/swagger
```

**Option B: Use a browser extension**
Install a browser extension like "ModHeader" to add the `X-API-Key` header, then visit the URL.

## What You'll See

When you open the Swagger UI endpoint in your browser, you'll see:

1. **Header Section**
   - API title (e.g., "customer-api API")
   - Version number
   - Description

2. **Schemas Section**
   - List of all classes in the version
   - Each class is expandable/collapsible
   - Click to view properties, types, and descriptions

3. **Interactive Features**
   - **Expand/Collapse**: Click on any schema to see details
   - **Nested Structures**: See object and array properties with their nested fields
   - **Type Information**: View data types, formats, and constraints
   - **Required Fields**: Clearly marked required properties
   - **Download**: Download the OpenAPI spec as JSON

## Visual Layout Example

```
┌─────────────────────────────────────────────────────┐
│  customer-api API                          v1.0.0   │
│  OpenAPI specification for acme-corp/...            │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Schemas                                            │
│                                                      │
│  ▼ Customer                                         │
│    type: object                                     │
│    Properties:                                      │
│      • id (string, required)                        │
│        - format: uuid                               │
│        - description: Unique customer identifier    │
│      • name (string, required)                      │
│      • email (string)                               │
│        - format: email                              │
│      ▼ address (object)                            │
│         Properties:                                 │
│           • street (string)                         │
│           • city (string)                           │
│           • zip (string)                            │
│                                                      │
│  ▶ Order                                           │
│                                                      │
│  ▶ Product                                         │
│                                                      │
└─────────────────────────────────────────────────────┘
```

## Compare with Other Endpoints

### JSON Endpoint (raw data)
```bash
curl http://localhost:8000/v1/acme-corp/customer-api/1.0.0
# Returns: JSON object with entire OpenAPI spec
```

### YAML Endpoint (raw data)
```bash
curl -H "Accept: application/yaml" \
  http://localhost:8000/v1/acme-corp/customer-api/1.0.0/Customer
# Returns: YAML formatted schema for single class
```

### Swagger UI Endpoint (visual interface)
```
http://localhost:8000/v1/acme-corp/customer-api/1.0.0/swagger
# Returns: Interactive HTML page with full visualization
```

## When to Use Each

| Endpoint | Use Case |
|----------|----------|
| JSON `/v1/.../...` | Programmatic access, API integration |
| YAML `/v1/.../.../ClassName` | Single class spec, human-readable |
| Swagger UI `/v1/.../swagger` | **Exploring schemas, documentation, training** |

## Try It Now

1. **Start the server:**
   ```bash
   cd apiome-rest
   uv run uvicorn src.app.main:app --reload
   ```

2. **Open your browser to:**
   ```
   http://localhost:8000/
   ```

3. **Note the available endpoints**, then navigate to a Swagger UI URL:
   ```
   http://localhost:8000/v1/YOUR-TENANT/YOUR-PROJECT/YOUR-VERSION/swagger
   ```

4. **Explore the schema** by clicking on different sections!

## Troubleshooting

### 404 Not Found
- Check that the tenant slug, project slug, and version slug are correct
- Verify the version exists in the database

### 403 Forbidden
- The version must be published
- Check version status in database

### 401 Unauthorized
- This is a private version - you need an API key
- Add `X-API-Key` header with a valid key
- Verify the API key has access to this tenant

### Blank Page
- Check browser console for errors
- Verify internet connection (CDN resources needed)
- Try a different browser

## Next Steps

- Share the Swagger UI URL with your team
- Use it for onboarding new developers
- Reference it in your API documentation
- Use it to understand complex nested structures before writing code

## Support

For more details, see:
- [swagger-ui-endpoint.md](./swagger-ui-endpoint.md) - Full documentation
- [SWAGGER_UI_IMPLEMENTATION.md](./SWAGGER_UI_IMPLEMENTATION.md) - Technical details
- [README.md](./README.md) - Complete API documentation

