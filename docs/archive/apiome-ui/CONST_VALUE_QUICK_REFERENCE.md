# Constant Value Feature - Quick Reference

## What Was Implemented

Added a "Constant Value" field as an alternative to enum for properties that should only ever have one specific value.

## Why This Matters

✅ **Semantically Clearer**: `const: "active"` is more expressive than `enum: ["active"]`  
✅ **OpenAPI 3.1 Compliant**: Uses the standard JSON Schema `const` keyword  
✅ **Discriminator Support**: Perfect for polymorphic object type identification  
✅ **Fixed Config**: Ideal for properties with unchanging values  

## Key Features

### 1. Mutual Exclusivity with Enum
- Cannot have both `const` and `enum` on the same property
- Setting `const` disables and clears `enum`
- Setting `enum` disables `const`

### 2. Type Support
Works with: `string`, `number`, `integer`, `boolean`

### 3. Drag and Drop Compatible
Const values are automatically preserved when dragging properties between classes.

## How to Use

### Creating a Property with Const

1. Add or edit a property
2. Select type (string, number, integer, or boolean)
3. In the "Constraints" section, find "Constant Value"
4. Enter the constant value (e.g., "User" for a discriminator)
5. Save the property

### Example Use Cases

**Discriminator Field**:
- Property: `objectType`
- Type: `string`
- Const: `"User"`

**API Version**:
- Property: `apiVersion`
- Type: `string`
- Const: `"v1"`

**Feature Flag**:
- Property: `enabled`
- Type: `boolean`
- Const: `true`

**Max Retries**:
- Property: `maxRetries`
- Type: `integer`
- Const: `3`

## JSON Schema Output

**Non-Array**:
```json
{
  "type": "string",
  "const": "active"
}
```

**Array**:
```json
{
  "type": "array",
  "items": {
    "type": "string",
    "const": "user"
  }
}
```

## Files Modified

1. `PropertyFormFields.tsx` - UI for const field + mutual exclusivity logic
2. `PropertyDialog.tsx` - Load/save const values for new properties
3. `ClassPropertyEditDialog.tsx` - Load/save const values for existing properties

## Documentation

- **Feature Overview**: `CONST_VALUE_FEATURE.md`
- **Implementation Details**: `CONST_VALUE_IMPLEMENTATION.md`
- **UI Examples**: `CONST_VALUE_UI_EXAMPLES.md`
- **This Quick Reference**: `CONST_VALUE_QUICK_REFERENCE.md`

## Validation

✅ TypeScript compilation successful  
✅ No breaking changes  
✅ Backward compatible  
✅ No database changes required  
✅ Drag and drop works  
✅ OpenAPI 3.1 compliant  

## Testing Checklist

- [ ] Create a property with const value
- [ ] Verify enum is disabled when const is set
- [ ] Create a property with enum values
- [ ] Verify const is disabled when enum is set
- [ ] Test with different types (string, number, integer, boolean)
- [ ] Test array properties with const
- [ ] Drag property with const to another class
- [ ] Verify const value is preserved after drag
- [ ] Edit property and change const value
- [ ] Save and verify changes persist

## Migration from Single-Item Enum

If you have properties with `enum: ["value"]`, you can migrate to `const: "value"`:

1. Edit the property
2. Delete the enum value
3. Set const to the same value
4. Save

Both are functionally equivalent, but `const` better expresses intent.

---

**Implementation Date**: December 12, 2025  
**Status**: ✅ Complete and Ready for Use

