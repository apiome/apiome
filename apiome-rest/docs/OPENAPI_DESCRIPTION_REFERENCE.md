# OpenAPI Description Feature - Quick Reference

## Overview
The OpenAPI code generator now uses the project's description from the database instead of generating a generic description.

## How It Works

### For Version-Level OpenAPI Specs
When generating an OpenAPI specification for a version (all classes):

```python
# The description in info.description comes from the project's description field
{
  "openapi": "3.1.0",
  "info": {
    "title": "{project_slug} API",
    "version": "{version_id}",
    "description": "{project.description}"  // ← From database
  },
  ...
}
```

### Default Behavior
If no description is provided (or it's empty/whitespace-only), the system defaults to:
```
"No description provided"
```

## API Endpoints Affected
1. **GET** `/v1/schema/{tenant_slug}/{project_slug}/{version_slug}`
   - Returns OpenAPI spec with project description
   
2. **GET** `/v1/swagger/{tenant_slug}/{project_slug}/{version_slug}`
   - Displays Swagger UI with project description

## Examples

### Example 1: Project with Description
**Database:**
```
Project: customer-management
Description: "API for managing customer records and relationships"
```

**Generated OpenAPI:**
```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "customer-management API",
    "version": "1.0.0",
    "description": "API for managing customer records and relationships"
  },
  ...
}
```

### Example 2: Project without Description
**Database:**
```
Project: prototype
Description: NULL
```

**Generated OpenAPI:**
```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "prototype API",
    "version": "0.1.0",
    "description": "No description provided"
  },
  ...
}
```

## Testing
Run the test suites to verify functionality:

```bash
# Unit tests for description logic
python3 test_description.py

# Integration tests with realistic scenarios
python3 test_integration_description.py
```

## Implementation Details

### Database Query
The `get_version_by_slugs()` method now includes:
```sql
SELECT v.id, v.version_id, v.visibility, v.published,
       p.description as project_description
FROM apiome.versions v
JOIN apiome.projects p ON v.project_id = p.id
...
```

### Generator Function
```python
def generate_openapi_spec(
    tenant_slug: str,
    project_slug: str,
    version_id: str,
    classes: List[Dict[str, Any]],
    all_properties: Dict[str, List[Dict[str, Any]]],
    project_description: Optional[str] = None  # ← New parameter
) -> Dict[str, Any]:
    # Uses project_description if provided and not empty/whitespace
    description = project_description if project_description and project_description.strip() else "No description provided"
    ...
```

## Notes
- Empty strings and whitespace-only strings are treated as "no description"
- The parameter is optional with a default of `None` for backward compatibility
- Class-level specs (single class endpoint) are not affected by this change

