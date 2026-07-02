# OpenAPI Import Feature

## Overview

The OpenAPI Import feature allows users to create projects in Apiome by importing existing OpenAPI 3.x specifications. This feature automatically extracts schemas from the OpenAPI spec and creates classes and properties in the Apiome platform.

## How It Works

### User Flow

1. **Navigate to Projects**: Go to the Projects page in the dashboard
2. **Create New Project**: Click "New Project" button
3. **Choose Import Method**: Select the "From OpenAPI Import" tab
4. **Upload Specification**: 
   - Click "Start Import" to open the import dialog
   - Drag and drop or select an OpenAPI specification file (JSON or YAML)
5. **Review Classes**: 
   - Review the classes that will be imported
   - Select/deselect classes you want to include
   - See property counts and names for each class
6. **Enter Project Details**:
   - Provide project name, slug, and description
   - Set the initial version ID
   - Add version description
7. **Import**: Click "Import Project" to create the project with all selected classes and properties

### Technical Implementation

#### Files Created/Modified

1. **`src/app/utils/openapi-import.ts`**: Core parsing and validation logic
   - Parses OpenAPI 3.x specifications (JSON and YAML)
   - Extracts schemas from `components/schemas` section
   - Filters out unsupported inline object properties
   - Validates imported classes for duplicate properties

2. **`src/app/components/ade/dashboard/OpenAPIImportDialog.tsx`**: Import dialog component
   - Multi-step wizard interface (Upload → Review → Details)
   - Drag-and-drop file upload
   - Class selection with property preview
   - Auto-fills project details from OpenAPI metadata

3. **`lib/db/helper.ts`**: Database operations
   - Added `importProjectFromOpenAPI()` function
   - Creates project, version, properties, and classes in a single transaction
   - Reuses identical properties across multiple classes

4. **`src/app/ade/dashboard/projects/page.tsx`**: Projects page
   - Added tabbed interface for "From Scratch" vs "From OpenAPI Import"
   - Integrated OpenAPIImportDialog component

#### Data Flow

```
OpenAPI Spec File
    ↓
Parse & Extract Schemas
    ↓
Filter Out Unsupported Schemas
    ↓
User Selects Classes
    ↓
Transaction: Create Project → Version → Properties → Classes → Link Properties
```

#### Property Reuse Strategy

The import process intelligently reuses properties across classes:
- Properties with identical names and data schemas are stored once in the `properties` table
- Multiple classes can reference the same property via `class_properties` junction table
- This reduces data duplication and maintains consistency

### Supported Features

✅ **Supported**:
- OpenAPI 3.x specifications (JSON and YAML formats)
- Schema extraction from `components/schemas`
- Property types: string, number, integer, boolean, array
- Property formats: uuid, email, date-time, decimal, etc.
- Required field validation
- Enum values
- Schema descriptions
- Property references via `$ref`
- Array types with `$ref` items

❌ **Not Supported** (filtered out automatically):
- Schemas with inline object properties
- Schemas with nested objects that have inline properties
- Arrays of objects with inline properties

### Example Usage

#### Sample OpenAPI Specification

See `docs/sample-openapi.json` for a complete example with:
- Product schema with basic types
- Customer schema with references
- Address schema
- Order schema with enums and arrays
- OrderItem schema

#### Import Results

Importing the sample specification creates:
- **Project**: "Sample E-commerce API"
- **Version**: "1.0.0"
- **Classes**: Product, Customer, Address, Order, OrderItem (5 classes)
- **Properties**: ~25 unique properties (reused across classes where appropriate)

### Database Schema

The import creates records in these tables:
- `apiome.projects`: The project record
- `apiome.versions`: Initial version record
- `apiome.properties`: Unique property definitions
- `apiome.classes`: Class definitions with schemas
- `apiome.class_properties`: Links between classes and properties

### Error Handling

The import process handles various error scenarios:
- Invalid OpenAPI format
- Missing required fields
- Duplicate class/property names
- Database constraint violations
- Transaction rollback on any failure

### Validation Rules

1. **OpenAPI Version**: Must be 3.x
2. **Schema Requirement**: Must have `components/schemas` section
3. **Class Selection**: At least one class must be selected
4. **Property Uniqueness**: No duplicate property names within a class
5. **Project Naming**: Valid project name and slug required
6. **Version Format**: Semantic versioning (e.g., 1.0.0)

### Future Enhancements

Potential improvements for future versions:
- Support for OpenAPI 2.0 (Swagger) specifications
- Import additional metadata (examples, defaults)
- Support for `allOf`, `oneOf`, `anyOf` compositions
- Import API paths and operations
- Preview mode with diff comparison
- Merge import into existing projects
- Export modified specs back to OpenAPI format

## Testing

### Manual Testing

1. Use the provided `sample-openapi.json` file
2. Navigate to Projects page
3. Click "New Project" → "From OpenAPI Import" → "Start Import"
4. Upload the sample file
5. Verify all 5 classes are shown with correct property counts
6. Import and verify project creation in database

### Edge Cases

- Empty OpenAPI spec (no schemas)
- Schemas with inline objects (should be filtered)
- Duplicate property names (validation error)
- Invalid semantic version
- Large specifications (100+ schemas)

## Troubleshooting

### "No schemas found in OpenAPI specification"
- Ensure the spec has a `components.schemas` section
- Verify the file is valid JSON/YAML

### "No valid schemas found to import"
- All schemas may have inline object properties
- Check if schemas have `type: object` with nested `properties`

### Import fails with constraint violation
- Project slug may already exist
- Check for unique constraint conflicts in error message

### Classes imported but properties missing
- Check browser console for parsing errors
- Verify property data is valid JSON

## Related Documentation

- [Property Name Validation](./PROPERTY_NAME_VALIDATION.md)
- [Class Name Validation](./CLASS_NAME_VALIDATION.md)
- [OpenAPI Consolidation](./OPENAPI_CONSOLIDATION.md)

