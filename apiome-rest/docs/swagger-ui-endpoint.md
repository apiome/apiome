# Swagger UI Endpoint

## Overview

The REST API now includes a Swagger UI endpoint that provides an interactive interface to explore and visualize the OpenAPI schemas for your versions.

## Endpoint

```
GET /v1/{tenant-slug}/{project-slug}/{version-slug}/swagger
```

## Parameters

- **tenant-slug**: The slug identifier for the tenant
- **project-slug**: The slug identifier for the project
- **version-slug**: The version identifier (e.g., "1.0.0")

## Headers

- **X-API-Key** (optional): Required for private versions. Provide your API key to access private schemas.

## Response

Returns an HTML page with a fully interactive Swagger UI interface displaying the OpenAPI specification for all classes in the specified version.

## Features

- **Interactive Documentation**: View all schemas with expandable sections
- **Schema Visualization**: See all properties, types, and nested structures
- **Deep Linking**: Share specific sections by URL
- **Download Support**: Download the OpenAPI specification directly from the UI
- **Responsive Design**: Works on desktop and mobile devices

## Examples

### Public Version
```
GET /v1/acme-corp/inventory/1.0.0/swagger
```

### Private Version
```
GET /v1/acme-corp/inventory/2.0.0/swagger
X-API-Key: your-api-key-here
```

## Access Control

The Swagger UI endpoint respects the same access control rules as the JSON/YAML endpoints:

1. **Published Status**: Only published versions are accessible
2. **Visibility**: Public versions don't require authentication
3. **API Keys**: Private versions require a valid API key with access to the tenant
4. **Tenant Isolation**: API keys only work for their associated tenant

## HTTP Status Codes

- **200 OK**: Successfully displayed the Swagger UI
- **401 Unauthorized**: API key required for private version or invalid API key
- **403 Forbidden**: Version is not published
- **404 Not Found**: Version, project, or tenant not found

## Integration

The Swagger UI uses:
- **Swagger UI v5**: Latest version from CDN
- **Embedded Specification**: The OpenAPI spec is embedded directly in the HTML
- **No External Dependencies**: All JavaScript and CSS loaded from CDN

## Use Cases

1. **Documentation**: Share interactive documentation with API consumers
2. **Exploration**: Explore complex nested schemas visually
3. **Integration Testing**: Use the interface to understand data structures before integration
4. **Client Generation**: View schemas before generating client code
5. **Training**: Teach team members about the data model interactively

