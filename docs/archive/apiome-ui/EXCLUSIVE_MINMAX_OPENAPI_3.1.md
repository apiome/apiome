# Exclusive Minimum/Maximum - OpenAPI 3.1 Implementation

## Overview

Updated the property form to properly handle `exclusiveMinimum` and `exclusiveMaximum` according to OpenAPI 3.1 / JSON Schema draft 2020-12 specifications.

## Changes Made

### OpenAPI 3.0 (Old Behavior)
In OpenAPI 3.0, exclusive minimum/maximum were boolean modifiers:

```json
{
  "type": "number",
  "minimum": 0,
  "exclusiveMinimum": true
}
```

### OpenAPI 3.1 (New Behavior)
In OpenAPI 3.1 / JSON Schema draft 2020-12, `exclusiveMinimum` and `exclusiveMaximum` are numeric values:

```json
{
  "type": "number",
  "exclusiveMinimum": 0
}
```

## UI Changes

### Property Form Fields

The numeric constraints section now includes radio button options:

**Minimum Value:**
- **Inclusive (≥)** - Outputs `minimum` field
- **Exclusive (>)** - Outputs `exclusiveMinimum` field

**Maximum Value:**
- **Inclusive (≤)** - Outputs `maximum` field
- **Exclusive (<)** - Outputs `exclusiveMaximum` field

### Example Usage

#### Inclusive Minimum (value ≥ 0):
```json
{
  "type": "integer",
  "minimum": 0
}
```

#### Exclusive Minimum (value > 0):
```json
{
  "type": "integer",
  "exclusiveMinimum": 0
}
```

#### Inclusive Maximum (value ≤ 100):
```json
{
  "type": "integer",
  "maximum": 100
}
```

#### Exclusive Maximum (value < 100):
```json
{
  "type": "integer",
  "exclusiveMaximum": 100
}
```

#### Combined Example (0 < value < 100):
```json
{
  "type": "number",
  "exclusiveMinimum": 0,
  "exclusiveMaximum": 100
}
```

## Implementation Details

### Modified Files

1. **PropertyFormFields.tsx**
   - Updated `PropertyFormData` interface:
     - Changed `exclusiveMinimum?: boolean` to `minimumType?: 'inclusive' | 'exclusive'`
     - Changed `exclusiveMaximum?: boolean` to `maximumType?: 'inclusive' | 'exclusive'`
   - Updated UI to use radio buttons instead of checkboxes
   - Updated example generation logic

2. **PropertyDialog.tsx**
   - Updated `PropertyItem` interface to reflect numeric exclusive values
   - Updated property loading logic to detect whether constraints are exclusive or inclusive
   - Updated schema building functions to output correct fields based on type
   - Updated both `buildPropertyJsonSchema()` and `handleSubmit()` functions

### Backward Compatibility

When loading existing properties:
- If `exclusiveMinimum` field exists, it's loaded as an exclusive constraint
- If `minimum` field exists, it's loaded as an inclusive constraint
- Same logic applies to maximum constraints

## Testing

To test the implementation:

1. Create a new class in the studio
2. Add a numeric property (number or integer)
3. Set a minimum value and select "Exclusive (>)"
4. Verify the generated JSON Schema uses `exclusiveMinimum` instead of `minimum`
5. Repeat for maximum values
6. Edit an existing property to verify values load correctly

## Schema Validation

The generated schemas are now compliant with:
- OpenAPI 3.1.x
- JSON Schema draft 2020-12
- JSON Schema draft 2019-09

## Future Enhancements

Consider adding:
- Visual indicators showing the range (e.g., "(0, 100)" for exclusive)
- Validation warnings if both inclusive and exclusive are specified for same boundary
- Helper text explaining the difference between inclusive and exclusive

