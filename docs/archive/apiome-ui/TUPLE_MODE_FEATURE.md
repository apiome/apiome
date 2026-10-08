# Tuple Mode (prefixItems) Feature - OpenAPI 3.1.0

## Overview

The **Tuple Mode** feature adds support for OpenAPI 3.1.0's `prefixItems` keyword, enabling you to define arrays with ordered, heterogeneous schemas. This is useful when you need arrays where specific positions have different types and constraints (tuples).

## What is Tuple Mode?

In traditional JSON Schema/OpenAPI, arrays typically have a single `items` schema that applies to all elements. With tuple mode (`prefixItems`), you can define:

- **Specific schemas for each position**: Position 0 is a string, position 1 is a number, position 2 is a boolean
- **Fallback schema for remaining items**: Any items beyond the defined prefix use the regular `items` schema

### Example Use Cases

1. **Coordinate pairs**: `[latitude: number, longitude: number]`
2. **CSV-like data**: `[name: string, age: integer, email: string]`
3. **Function arguments**: `[operation: string, value1: number, value2: number]`
4. **Database rows**: `[id: integer, name: string, created: string(date-time)]`

## How to Use

### Enabling Tuple Mode

1. Open the **Property Dialog** (add or edit a property)
2. Set the property type to **Array**
3. In the **Array Constraints** section, scroll down to find the **Tuple Mode** section
4. Check the **"Tuple Mode (prefixItems)"** checkbox

### Defining Prefix Items

Once tuple mode is enabled:

1. Click **"Add Position"** to add a new position to the tuple
2. For each position:
   - **Select the type** from the dropdown (string, number, integer, boolean, object, array, null, or any)
   - **Edit the JSON schema** in the text area to add additional constraints (e.g., `minLength`, `pattern`, `enum`)
3. **Reorder positions** by dragging the handle (⋮) on the left
4. **Remove positions** by clicking the delete (🗑️) button

### Example: Coordinate Tuple

To define a coordinate array `[latitude, longitude]`:

**Position 0 (Latitude):**
```json
{
  "type": "number",
  "minimum": -90,
  "maximum": 90,
  "description": "Latitude in decimal degrees"
}
```

**Position 1 (Longitude):**
```json
{
  "type": "number",
  "minimum": -180,
  "maximum": 180,
  "description": "Longitude in decimal degrees"
}
```

**Items Schema (optional):**
```json
false
```
This prevents any items beyond position 1 (strict tuple).

### Items Schema for Remaining Positions

In the **"Items Schema (for positions beyond prefix)"** field, you can define what happens to items beyond your defined prefix:

- **`true`** (default): Allow any additional items of any type
- **`false`**: Do not allow any additional items (strict tuple)
- **`{"type": "string"}`**: Additional items must be strings
- **Any JSON Schema**: Additional items must match this schema

### Example Output

When you define a tuple with the coordinate example above and set items to `false`, the generated OpenAPI schema will be:

```yaml
type: array
prefixItems:
  - type: number
    minimum: -90
    maximum: 90
    description: Latitude in decimal degrees
  - type: number
    minimum: -180
    maximum: 180
    description: Longitude in decimal degrees
items: false
```

## JSON Schema Draft 2020-12 Compliance

The tuple mode feature follows the [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core.html#name-prefixitems) specification, which is used by OpenAPI 3.1.0.

Key behaviors:
- `prefixItems` is an array where each element is a JSON schema
- The schema at index `i` validates the array element at index `i`
- If the array has more items than `prefixItems`, the `items` schema (if present) validates all remaining items
- If `items` is `false`, no additional items are allowed
- If `items` is not specified or `true`, any additional items are allowed

## Related Features

This feature works alongside other OpenAPI 3.1 array features:

- **Contains Schema**: Require at least one item to match a specific schema
- **minContains/maxContains**: Control how many items must match the contains schema
- **minItems/maxItems**: Set min/max array length
- **uniqueItems**: Require all items to be unique

## Technical Implementation

### Files Modified

1. **PropertyDialog.tsx**: Added `tupleMode`, `prefixItems`, and `items` to PropertyItem interface and form handling
2. **PropertyFormFields.tsx**: Added UI for tuple mode toggle and integration with PrefixItemsEditor
3. **PrefixItemsEditor.tsx**: New component for managing prefix items with drag-and-drop reordering
4. **StudioSideNav.tsx**: Updated PropertyItem interface to match PropertyDialog

### Data Structure

When tuple mode is enabled, the property data includes:

```typescript
{
  type: "array",
  prefixItems: [
    { type: "number", minimum: -90, maximum: 90 },
    { type: "number", minimum: -180, maximum: 180 }
  ],
  items: false,
  // ... other array constraints
}
```

## Migration Notes

- **Backward Compatible**: Existing array properties without `prefixItems` continue to work as before
- **Forward Compatible**: The `prefixItems` keyword is recognized by OpenAPI 3.1.0 validators and tools
- **OpenAPI 3.0 Compatibility**: Tools that only support OpenAPI 3.0 will ignore `prefixItems` and fall back to `items`

## Testing

To test the tuple mode feature:

1. Create a new array property
2. Enable tuple mode
3. Add 2-3 prefix items with different types
4. Set items to `false` to create a strict tuple
5. Save and view the generated JSON/YAML
6. Verify the schema validates correctly in the JSON view

## Future Enhancements

Potential improvements to this feature:

- **Visual tuple preview**: Show example array values that would match the schema
- **Tuple templates**: Pre-built tuples for common patterns (coordinates, RGB colors, etc.)
- **Import from examples**: Auto-generate prefixItems from example array data
- **Validation preview**: Live validation of sample data against the tuple schema
- **Position descriptions**: Add description field to each prefix item in the UI

## References

- [OpenAPI 3.1.0 Specification](https://spec.openapis.org/oas/v3.1.0)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/release-notes.html)
- [prefixItems Keyword](https://json-schema.org/understanding-json-schema/reference/array.html#tuple-validation)

