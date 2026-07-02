# OpenAPI Description Enhancement

## Summary
Updated the OpenAPI code generation to use the project description from the database instead of a hardcoded template. When no description is provided, it defaults to "No description provided".

## Changes Made

### 1. Database Module (`src/app/database.py`)
- **Modified**: `get_version_by_slugs()` method
- **Change**: Added `p.description as project_description` to the SELECT query to fetch the project's description field
- **Purpose**: Make the project description available to the OpenAPI generator

### 2. Main Application (`src/app/main.py`)
- **Modified**: Three endpoints that generate OpenAPI specifications:
  - `get_version_openapi_spec()` - REST API endpoint for OpenAPI spec
  - `get_class_openapi_spec()` - REST API endpoint for class-specific spec
  - `get_swagger_ui()` - Swagger UI display endpoint
- **Change**: All calls to `generate_openapi_spec()` now pass `version.get('project_description')` as the last parameter
- **Purpose**: Pass the project description from the database to the generator

### 3. OpenAPI Generator (`src/app/openapi_generator.py`)
- **Modified**: `generate_openapi_spec()` function
- **Changes**:
  - Added optional parameter `project_description: Optional[str] = None`
  - Added logic to use project description if provided and not empty/whitespace-only
  - Falls back to "No description provided" when description is None, empty, or whitespace-only
- **Purpose**: Generate OpenAPI specs with meaningful descriptions from the project data

## Behavior

### Before
- OpenAPI info.description was always: `"OpenAPI specification for {tenant_slug}/{project_slug}/{version_id}"`

### After
- OpenAPI info.description uses the project's description field from the database
- If no description exists (None, empty string, or whitespace), it defaults to: `"No description provided"`

## Test Coverage
Created comprehensive test suite (`test_description.py`) covering:
1. ✓ Valid project description is used
2. ✓ None defaults to "No description provided"
3. ✓ Empty string defaults to "No description provided"
4. ✓ Whitespace-only string defaults to "No description provided"
5. ✓ Omitted parameter defaults to "No description provided"

All tests pass successfully.

## Files Modified
- `/Users/kenji/Development/apiome/apiome-rest/src/app/database.py`
- `/Users/kenji/Development/apiome/apiome-rest/src/app/main.py`
- `/Users/kenji/Development/apiome/apiome-rest/src/app/openapi_generator.py`

## Files Created
- `/Users/kenji/Development/apiome/apiome-rest/test_description.py`

