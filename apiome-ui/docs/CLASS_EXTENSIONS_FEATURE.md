# Class Extensions Feature

## Overview

The Class Extensions feature allows users to add arbitrary OpenAPI 3.1 compliant extension properties (x- prefixed) to class definitions. This feature enables custom metadata to be attached to classes for use by tools, documentation generators, and other consumers of the OpenAPI specification.

## Implementation

### Components

#### 1. ExtensionsEditor Component

**Location:** `/src/app/components/ade/studio/ExtensionsEditor.tsx`

A reusable React component for managing x- prefixed extension properties.

**Features:**
- Key-value editor interface
- Enforces x- prefix requirement on all keys
- Validates key format (alphanumeric, hyphens, underscores)
- Supports any valid JSON value (strings, numbers, booleans, objects, arrays)
- Prevents duplicate keys
- Sortable display (alphabetically by key)
- Add/remove functionality
- Visual feedback with Material-UI components

**Props:**
```typescript
interface ExtensionsEditorProps {
  value: Record<string, any>;        // Current extensions
  onChange: (extensions: Record<string, any>) => void;  // Change handler
  disabled?: boolean;                // Disable editing
  size?: 'small' | 'medium';        // Size variant
}
```

**Validation Rules:**
- Keys must start with `x-`
- Keys must match pattern: `^x-[a-zA-Z0-9_-]+$`
- Keys must be unique within the extensions
- Values must be non-empty
- Values are parsed as JSON if valid, otherwise stored as strings

#### 2. ClassEditDialog Integration

**Location:** `/src/app/components/ade/studio/ClassEditDialog.tsx`

The ClassEditDialog has been updated to support extensions:

**Changes Made:**

1. **Form State Addition:**
   - Added `extensions: {} as Record<string, any>` to form state

2. **Schema Loading:**
   - Extracts x- prefixed properties from schema on load
   - Populates extensions form field when editing existing classes

3. **Schema Building:**
   - Includes extensions in schema when saving
   - Properly serializes x- properties to JSONB

4. **UI Addition:**
   - Extensions section added after Deprecated section
   - Wrapped in styled Box with gray background
   - Disabled when in read-only mode

### Database Storage

Extensions are stored as part of the class schema in the `classes.schema` JSONB column. The x- prefixed properties are stored at the root level of the schema object, following the OpenAPI 3.1 specification.

**Example Schema with Extensions:**
```json
{
  "type": "object",
  "properties": {
    "name": { "type": "string" }
  },
  "x-internal-id": "ABC-123",
  "x-team-owner": "platform-team",
  "x-custom-metadata": {
    "version": "2.0",
    "legacy": false
  }
}
```

## Usage

### Adding Extensions to a Class

1. Open the Class Edit Dialog (create new or edit existing class)
2. Scroll to the "Extensions" section at the bottom of the form
3. Enter a key starting with `x-` (e.g., `x-internal-id`)
4. Enter a value in JSON format (e.g., `"ABC-123"` or `{"key": "value"}`)
5. Click "Add" button or press Enter
6. The extension appears in the list below
7. Save the class to persist extensions

### Removing Extensions

1. Locate the extension in the list
2. Click the delete icon (trash can) next to the extension
3. Save the class to persist the change

### Extension Value Types

Extensions support any valid JSON value:

- **Strings:** `"some text"` or just `some text`
- **Numbers:** `42` or `3.14`
- **Booleans:** `true` or `false`
- **Objects:** `{"key": "value", "nested": {"data": 123}}`
- **Arrays:** `["item1", "item2", "item3"]`
- **Null:** `null`

## Use Cases

### 1. Internal Metadata
```json
{
  "x-internal-id": "CLASS-001",
  "x-team-owner": "platform-team",
  "x-created-by": "user@example.com"
}
```

### 2. Code Generation Hints
```json
{
  "x-codegen-package": "com.example.models",
  "x-codegen-imports": ["java.time.Instant", "java.util.UUID"]
}
```

### 3. Documentation Extensions
```json
{
  "x-examples-url": "https://docs.example.com/classes/person",
  "x-changelog": {
    "2.0.0": "Added email validation",
    "1.0.0": "Initial release"
  }
}
```

### 4. Vendor-Specific Extensions
```json
{
  "x-amazon-apigateway-integration": {
    "type": "aws_proxy",
    "httpMethod": "POST"
  },
  "x-swagger-ui-order": 1
}
```

### 5. Testing & Mocking
```json
{
  "x-faker": "person.fullName",
  "x-mock-priority": "high",
  "x-test-data-source": "production-anonymized"
}
```

## OpenAPI 3.1 Compliance

This implementation follows the OpenAPI 3.1.0 specification for extensions:

- Extensions are prefixed with `x-`
- Extensions can be added to any object
- Extensions can have any valid JSON value
- Extensions are preserved in the generated OpenAPI documents

**Reference:** [OpenAPI Specification - Specification Extensions](https://spec.openapis.org/oas/v3.1.0#specification-extensions)

## Benefits

1. **Flexibility:** Add custom metadata without modifying core schema
2. **Tooling Support:** Enable custom tools to read/write metadata
3. **Documentation:** Enhance generated documentation with custom fields
4. **Code Generation:** Provide hints to code generators
5. **Integration:** Support vendor-specific extensions for API gateways, etc.
6. **Versioning:** Track class evolution with custom metadata

## Technical Details

### Type Safety

Extensions are typed as `Record<string, any>` to allow maximum flexibility while maintaining TypeScript type checking on the keys.

### Serialization

Extensions are serialized to JSON and stored in PostgreSQL's JSONB column type, which provides:
- Efficient storage
- Indexing capabilities (via GIN indexes)
- Query support
- Validation

### Validation

Client-side validation ensures:
- Keys start with `x-`
- Keys contain only valid characters
- No duplicate keys
- Values are non-empty

Server-side validation should also be implemented to ensure data integrity.

## Future Enhancements

Potential improvements for future versions:

1. **Extension Templates:** Pre-defined extension sets for common use cases
2. **Autocomplete:** Suggest common extension keys
3. **Schema Validation:** Validate extension values against JSON schemas
4. **Bulk Import/Export:** Import/export extensions as JSON
5. **Extension Search:** Search classes by extension values
6. **Extension Documentation:** Link to extension documentation/specs
7. **Extension Inheritance:** Inherit extensions from parent classes

## Examples

### Simple Extension
```json
{
  "x-internal-id": "USER-CLASS-001"
}
```

### Complex Extension
```json
{
  "x-metadata": {
    "owner": "platform-team",
    "created": "2025-01-15",
    "status": "stable",
    "tags": ["core", "v2"]
  }
}
```

### Multiple Extensions
```json
{
  "x-internal-id": "USER-CLASS-001",
  "x-team-owner": "platform-team",
  "x-api-version": "2.0",
  "x-deprecated-by": "UserV2",
  "x-migration-guide": "https://docs.example.com/migrate/user-v2"
}
```

## Testing Checklist

- [ ] Create new class with extensions
- [ ] Edit existing class to add extensions
- [ ] Remove extensions from class
- [ ] Verify extensions appear in OpenAPI JSON output
- [ ] Verify extensions appear in OpenAPI YAML output
- [ ] Test with various value types (string, number, boolean, object, array)
- [ ] Test validation (x- prefix required)
- [ ] Test duplicate key prevention
- [ ] Test in read-only mode (extensions should be visible but not editable)
- [ ] Test with long key names
- [ ] Test with nested object values
- [ ] Verify extensions persist after save/reload

## Migration

No database migration is required. Extensions are stored in the existing `classes.schema` JSONB column. Existing classes without extensions will continue to work normally.

