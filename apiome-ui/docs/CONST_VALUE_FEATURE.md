# Constant Value Feature

## Overview

The "Constant Value" field has been added as an alternative to enum for properties that should only ever have one specific value. This is semantically clearer than using a single-item enum and is particularly useful for:

- **Discriminator fields**: Properties that identify object types in polymorphic structures
- **Fixed configuration values**: Properties that have a constant value across all instances
- **Type identifiers**: Properties that serve as type markers in JSON schemas

## Implementation

### UI Components

The constant value field has been added to the property form in three locations:

1. **PropertyFormFields.tsx**: The shared form component used by both PropertyDialog and ClassPropertyEditDialog
2. **PropertyDialog.tsx**: For adding/editing properties in the canvas
3. **ClassPropertyEditDialog.tsx**: For editing properties within a class

### Key Features

#### Mutual Exclusivity with Enum
- When a constant value is set, the enum field becomes disabled
- When enum values are added, the constant value is cleared
- This ensures properties use either `const` or `enum`, never both

#### Type Support
The constant value field supports the following property types:
- `string`
- `number`
- `integer`
- `boolean`

#### Value Handling
- String values are stored as-is
- Numeric values (number/integer) are parsed and stored as numbers
- Boolean values are parsed from the string "true" or "false"
- Complex values can be provided as JSON strings and will be parsed

#### Visual Feedback
When a constant value is set, an informational panel is displayed showing:
- The constant value that will be enforced
- A brief explanation of the const feature
- Use case examples (discriminator fields, fixed configuration)

### JSON Schema Output

When a property has a constant value, the resulting JSON Schema includes:

```json
{
  "type": "string",
  "const": "active"
}
```

For array properties:

```json
{
  "type": "array",
  "items": {
    "type": "string",
    "const": "status"
  }
}
```

### Drag and Drop Compatibility

The constant value is properly preserved when:
- Dragging properties between classes
- Copying property schemas
- Duplicating properties

All property data, including the `const` field, is serialized and transferred during drag operations.

## Usage Examples

### Example 1: Discriminator Field

For a polymorphic schema where you need to identify the object type:

```json
{
  "name": "objectType",
  "type": "string",
  "const": "User",
  "description": "Object type discriminator"
}
```

### Example 2: API Version

For a fixed API version identifier:

```json
{
  "name": "apiVersion",
  "type": "string",
  "const": "v1",
  "description": "API version identifier"
}
```

### Example 3: Boolean Flag

For a property that is always true:

```json
{
  "name": "enabled",
  "type": "boolean",
  "const": true,
  "description": "Feature is always enabled"
}
```

### Example 4: Numeric Constant

For a fixed numeric value:

```json
{
  "name": "maxRetries",
  "type": "integer",
  "const": 3,
  "description": "Maximum number of retries"
}
```

## OpenAPI 3.1 Compliance

The `const` keyword is part of JSON Schema and is fully supported in OpenAPI 3.1. It provides a more semantically correct way to express single-value constraints compared to a single-item enum.

### Comparison: `const` vs Single-Item `enum`

**Using `const` (recommended):**
```json
{
  "type": "string",
  "const": "active"
}
```

**Using single-item `enum` (less clear):**
```json
{
  "type": "string",
  "enum": ["active"]
}
```

Both are functionally equivalent, but `const` better expresses the intent that this is a constant value, not a selection from a list of options.

## Database Storage

The constant value is stored in the property's `data` JSONB field in the database, alongside other schema properties like `type`, `format`, `enum`, etc.

Example storage:

```json
{
  "type": "string",
  "const": "active",
  "description": "Status discriminator",
  "required": true
}
```

## Future Enhancements

Potential improvements for this feature:

1. **Validation**: Add real-time validation for boolean and numeric const values
2. **Autocomplete**: Suggest common constant values based on property name
3. **Templates**: Provide templates for common discriminator patterns
4. **Visual Indicator**: Add a visual badge on properties with const values in the class node view

