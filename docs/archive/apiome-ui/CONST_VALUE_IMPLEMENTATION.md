# Constant Value Feature - Implementation Summary

## Date
December 12, 2025

## Overview
Implemented a "Constant Value" field as an alternative to enum for properties that should only ever have one specific value. This is more semantically clear than using a single-item enum and is particularly useful for discriminator values or fixed configuration.

## Changes Made

### 1. PropertyFormFields.tsx
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyFormFields.tsx`

#### Interface Updates
- Added `const?: string` field to `PropertyFormData` interface

#### UI Components Added
- New "Constant Value" section with:
  - Text/number input field for entering the constant value
  - Dynamic placeholder based on property type (string, number, integer, boolean)
  - Informational panel that displays when a const value is set
  - Helper text explaining the feature and use cases

#### Behavior Implemented
- Mutual exclusivity with enum:
  - When const is set, enum input is disabled
  - When const is set, adding enum values is prevented
  - When enum values exist, const field is disabled
  - Setting const clears enum, and vice versa
- Field is only shown for compatible types: string, number, integer, boolean
- Separate handling for array types (const applies to each item)

### 2. PropertyDialog.tsx
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyDialog.tsx`

#### Loading Property Data (useEffect)
- Added const field loading from property data
- Handles both string and complex values (JSON.parse for non-string const values)
- Correctly loads const from items schema for array types

#### Building JSON Schema (buildPropertyJsonSchema)
- Added const handling in JSON schema generation
- For array types: const is added to items schema
- For non-array types: const is added to root schema
- Implements mutual exclusivity: const takes precedence over enum
- Attempts to parse const value as JSON, falls back to string if parsing fails

#### Saving Property Data (handleSubmit)
- Added const handling when saving properties
- For array types: const is stored in items schema
- For non-array types: const is stored at property level
- Properly cleans up: deletes enum when const is set, deletes const when enum is set
- Preserves const value through property updates

### 3. ClassPropertyEditDialog.tsx
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`

#### Loading Property Data (useEffect)
- Added const field loading from class property data
- Handles both string and complex values with JSON.stringify/parse
- Correctly identifies const from items schema for array types

#### Saving Property Updates (handleSave)
- Added const/enum mutual exclusivity logic
- Const value is parsed as JSON when possible
- Properly deletes enum when const is set
- Properly deletes const when enum is set
- Stores const in correct schema location (items for arrays, root for non-arrays)

## Key Implementation Details

### Mutual Exclusivity Logic
```typescript
// When setting const, clear enum
if (formData.const && formData.const.trim()) {
  targetSchema.const = JSON.parse(formData.const);
  delete targetSchema.enum;
} else {
  delete targetSchema.const;
  if (formData.enum && formData.enum.length > 0) {
    targetSchema.enum = formData.enum;
  } else {
    delete targetSchema.enum;
  }
}
```

### Value Parsing
The implementation intelligently handles different value types:
- **Strings**: Used as-is
- **Numbers**: Parsed when the property type is number/integer
- **Booleans**: Parsed from string representation
- **JSON**: Complex values can be provided as JSON strings

### Drag and Drop Support
The const value is automatically preserved during drag and drop operations because:
1. It's part of the property's data schema
2. The entire data object is serialized during drag operations
3. No special handling is required - the existing drag/drop logic handles it

## Testing Recommendations

To verify the implementation works correctly:

1. **Create a property with const value**
   - Add a new property
   - Set type to "string"
   - Set const value to "active"
   - Verify enum field is disabled
   - Save and verify the const value appears in the JSON schema

2. **Test mutual exclusivity**
   - Create a property with enum values
   - Try to set a const value
   - Verify enum is cleared when const is set
   - Clear const and add enum values again

3. **Test different types**
   - Test with string const: "test"
   - Test with number const: 42
   - Test with integer const: 100
   - Test with boolean const: true

4. **Test array properties**
   - Create an array property
   - Set const value
   - Verify const is applied to items schema

5. **Test drag and drop**
   - Create a property with const value
   - Drag it to another class
   - Verify the const value is preserved

6. **Test property editing**
   - Edit an existing property with const
   - Modify the const value
   - Save and verify changes are persisted

## OpenAPI 3.1 Compliance

The implementation follows OpenAPI 3.1 / JSON Schema specifications:
- Uses the `const` keyword as defined in JSON Schema
- Properly serializes const values
- Maintains compatibility with existing enum functionality
- Generates valid OpenAPI 3.1 schemas

## Files Modified

1. `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyFormFields.tsx`
2. `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyDialog.tsx`
3. `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`

## Documentation Created

1. `/Users/kenji/Development/apiome/apiome-ui/docs/CONST_VALUE_FEATURE.md` - Comprehensive feature documentation

## Validation

- ✅ TypeScript compilation successful (no errors)
- ✅ All three property editing components updated
- ✅ Mutual exclusivity implemented
- ✅ Drag and drop compatibility maintained
- ✅ OpenAPI 3.1 compliant

## Notes

- The implementation uses existing infrastructure and doesn't require database schema changes
- The const value is stored in the property's `data` JSONB field
- No backend changes are required as the backend already stores arbitrary JSON schema properties
- The feature is backward compatible - existing properties without const values continue to work

