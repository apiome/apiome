# Arazzo Specification Endpoints

## Overview

The Apiome REST API now supports Arazzo 1.0.1 workflow specification endpoints. Arazzo is a specification for describing sequences of API calls and their dependencies, making it ideal for defining API workflows and testing scenarios.

## New Endpoints

### 1. Get Version Arazzo Specification

**Endpoint:** `GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}`

**Description:** Retrieves the complete Arazzo workflow specification for all classes in a version.

**Parameters:**
- `tenant-slug` (path, required): The tenant identifier
- `project-slug` (path, required): The project identifier  
- `version-slug` (path, required): The version identifier (e.g., "1.0.0")
- `X-API-Key` (header, optional): API key for private versions
- `Accept` (header, optional): Content negotiation (application/json or application/yaml)

**Response Formats:**
- **JSON** (default): `application/json`
- **YAML**: Use Accept header with `application/yaml`, `application/x-yaml`, `text/yaml`, or `text/x-yaml`

**Example Request (JSON):**
```bash
curl -X GET "http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0" \
  -H "Accept: application/json"
```

**Example Request (YAML):**
```bash
curl -X GET "http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0" \
  -H "Accept: application/yaml"
```

**Example Request (Private Version):**
```bash
curl -X GET "http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0" \
  -H "X-API-Key: your-api-key-here" \
  -H "Accept: application/json"
```

**Example Response:**
```json
{
  "arazzo": "1.0.1",
  "info": {
    "title": "my-project Workflows",
    "version": "1.0.0",
    "description": "Generated Arazzo 1.0.1 workflow specification from Apiome Studio"
  },
  "sourceDescriptions": [
    {
      "name": "openapi-source",
      "type": "openapi",
      "url": "/v1/schema/my-tenant/my-project/1.0.0",
      "description": "OpenAPI specification containing schema definitions"
    }
  ],
  "workflows": [
    {
      "workflowId": "userWorkflow",
      "summary": "User CRUD Workflow",
      "description": "Operations for User",
      "steps": [
        {
          "stepId": "createUser",
          "description": "Create a new User",
          "operationId": "createUser",
          "parameters": [],
          "requestBody": {
            "contentType": "application/json",
            "payload": {
              "$ref": "#/components/schemas/User"
            }
          },
          "successCriteria": [
            {
              "condition": "$statusCode == 201",
              "type": "simple"
            }
          ],
          "outputs": {
            "userId": "$response.body.id"
          }
        },
        {
          "stepId": "getUser",
          "description": "Retrieve a User by ID",
          "operationId": "getUserById",
          "parameters": [
            {
              "name": "id",
              "in": "path",
              "value": "$steps.createUser.outputs.userId"
            }
          ],
          "successCriteria": [
            {
              "condition": "$statusCode == 200",
              "type": "simple"
            }
          ],
          "dependsOn": ["createUser"]
        },
        {
          "stepId": "updateUser",
          "description": "Update an existing User",
          "operationId": "updateUser",
          "parameters": [
            {
              "name": "id",
              "in": "path",
              "value": "$steps.createUser.outputs.userId"
            }
          ],
          "requestBody": {
            "contentType": "application/json",
            "payload": {
              "$ref": "#/components/schemas/User"
            }
          },
          "successCriteria": [
            {
              "condition": "$statusCode == 200",
              "type": "simple"
            }
          ],
          "dependsOn": ["createUser"]
        },
        {
          "stepId": "deleteUser",
          "description": "Delete a User",
          "operationId": "deleteUser",
          "parameters": [
            {
              "name": "id",
              "in": "path",
              "value": "$steps.createUser.outputs.userId"
            }
          ],
          "successCriteria": [
            {
              "condition": "$statusCode == 204",
              "type": "simple"
            }
          ],
          "dependsOn": ["updateUser"]
        }
      ]
    }
  ]
}
```

### 2. Get Class Arazzo Specification

**Endpoint:** `GET /v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}/{class-name}`

**Description:** Retrieves the Arazzo workflow specification for a single class.

**Parameters:**
- `tenant-slug` (path, required): The tenant identifier
- `project-slug` (path, required): The project identifier
- `version-slug` (path, required): The version identifier (e.g., "1.0.0")
- `class-name` (path, required): The name of the class
- `X-API-Key` (header, optional): API key for private versions
- `Accept` (header, optional): Content negotiation (application/json or application/yaml)

**Response Formats:**
- **JSON** (default): `application/json`
- **YAML**: Use Accept header with `application/yaml`, `application/x-yaml`, `text/yaml`, or `text/x-yaml`

**Example Request (JSON):**
```bash
curl -X GET "http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0/User" \
  -H "Accept: application/json"
```

**Example Request (YAML):**
```bash
curl -X GET "http://localhost:8000/v1/arazzo/my-tenant/my-project/1.0.0/User" \
  -H "Accept: application/yaml"
```

**Example Response:**
```json
{
  "arazzo": "1.0.1",
  "info": {
    "title": "User Workflow",
    "version": "1.0.0",
    "description": "Arazzo workflow specification for my-tenant/my-project/1.0.0/User"
  },
  "sourceDescriptions": [
    {
      "name": "openapi-source",
      "type": "openapi",
      "url": "/v1/schema/my-tenant/my-project/1.0.0/User",
      "description": "OpenAPI specification for User"
    }
  ],
  "workflows": [
    {
      "workflowId": "userWorkflow",
      "summary": "User CRUD Workflow",
      "description": "A user in the system",
      "steps": [
        // ... CRUD steps as shown above
      ]
    }
  ]
}
```

## Workflow Structure

Each class generates a single workflow with four standard CRUD steps:

1. **Create Step**: Creates a new instance and captures the ID
2. **Get Step**: Retrieves the instance using the captured ID (depends on create)
3. **Update Step**: Updates the instance using the captured ID (depends on create)
4. **Delete Step**: Deletes the instance using the captured ID (depends on update)

## Step Dependencies

The steps are chained with dependencies to ensure proper execution order:

```
createUser
    ↓
getUser
    ↓
updateUser
    ↓
deleteUser
```

## Source Descriptions

Each Arazzo specification includes a `sourceDescriptions` section that references the corresponding OpenAPI specification:

- For version-level specs: Points to `/v1/schema/{tenant}/{project}/{version}`
- For class-level specs: Points to `/v1/schema/{tenant}/{project}/{version}/{class}`

## Content Negotiation

Both endpoints support content negotiation via the `Accept` header:

| Accept Header | Response Format | Content-Type | Filename Pattern |
|--------------|-----------------|--------------|------------------|
| `application/json` or `*/*` | JSON | `application/json` | N/A |
| `application/yaml` | YAML | `application/x-yaml` | `{project}-workflows.yaml` or `{class}-workflow.yaml` |
| `application/x-yaml` | YAML | `application/x-yaml` | Same as above |
| `text/yaml` | YAML | `application/x-yaml` | Same as above |
| `text/x-yaml` | YAML | `application/x-yaml` | Same as above |

## Authentication & Authorization

Arazzo endpoints follow the same authentication rules as OpenAPI endpoints:

- **Public versions**: No authentication required
- **Private versions**: Require `X-API-Key` header
- API key must belong to the tenant being accessed

## Error Responses

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 401 | Missing or invalid API key (for private versions) |
| 403 | Version not published or insufficient permissions |
| 404 | Tenant, project, version, or class not found |

## Use Cases

### 1. API Testing
Use Arazzo workflows to define comprehensive API test scenarios that verify CRUD operations work correctly.

### 2. Documentation
Provide executable workflow documentation showing how to use your API endpoints in sequence.

### 3. Code Generation
Generate client code or test scripts from Arazzo workflows.

### 4. Integration Testing
Define complex multi-step integration test scenarios with dependencies between API calls.

### 5. API Orchestration
Use Arazzo specifications with workflow engines to orchestrate API operations.

## Integration with OpenAPI

Arazzo specifications reference OpenAPI schemas through the `$ref` syntax:

```json
"requestBody": {
  "contentType": "application/json",
  "payload": {
    "$ref": "#/components/schemas/User"
  }
}
```

The actual schema definitions are in the OpenAPI specification referenced in `sourceDescriptions`.

## Complete API Endpoint List

The root endpoint (`GET /`) now includes all available endpoints:

```json
{
  "message": "Apiome REST API",
  "version": "1.0.0",
  "endpoints": {
    "version_spec": "/v1/schema/{tenant-slug}/{project-slug}/{version-slug}",
    "class_spec": "/v1/schema/{tenant-slug}/{project-slug}/{version-slug}/{class-name}",
    "swagger_ui": "/v1/swagger/{tenant-slug}/{project-slug}/{version-slug}",
    "arazzo_spec": "/v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}",
    "class_arazzo_spec": "/v1/arazzo/{tenant-slug}/{project-slug}/{version-slug}/{class-name}"
  }
}
```

## Example Workflow: Complete CRUD Cycle

Here's how the generated Arazzo workflow executes:

1. **POST** to create endpoint → Returns 201 with `id` in response body
2. **GET** to retrieve endpoint with `id` from step 1 → Returns 200 with object
3. **PUT/PATCH** to update endpoint with `id` from step 1 → Returns 200
4. **DELETE** to delete endpoint with `id` from step 1 → Returns 204

Each step includes:
- **Success criteria**: Expected HTTP status code
- **Parameters**: Path/query parameters including those from previous steps
- **Request body**: Schema reference for POST/PUT operations
- **Outputs**: Values extracted from response (like IDs)
- **Dependencies**: Which previous steps must complete first

## Tools & Libraries

The Arazzo specifications generated by this API are compatible with:

- [Arazzo specification](https://spec.openapis.org/arazzo/latest.html) - Official Arazzo 1.0.1 spec
- API testing tools that support Arazzo
- Workflow engines that can execute Arazzo workflows
- Code generators that consume Arazzo specs

## Notes

- Generated workflows use standard CRUD operation patterns
- All workflows are independent (no cross-class dependencies)
- Output references use JSONPath syntax (`$response.body.id`)
- Success criteria use simple conditional expressions
- Schema references point to the corresponding OpenAPI specification

---

**Last Updated:** December 7, 2024  
**Arazzo Version:** 1.0.1  
**API Version:** 1.0.0

