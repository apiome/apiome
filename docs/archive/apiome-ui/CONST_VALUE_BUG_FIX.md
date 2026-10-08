# Constant Value Feature - Bug Fix

## Issue
The `const` field was not being copied when properties were dragged and dropped onto class nodes in the canvas.

## Root Cause
The `handlePropertyDrop` function in `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/page.tsx` was missing the `const` field in the property data object passed to `addPropertyToClass`.

## Solution
Added the `const` field to the property data object in `handlePropertyDrop`:

```typescript
{
  // ...existing fields...
  tupleMode: propertyData.tupleMode,
  prefixItems: propertyData.prefixItems,
  // Constant value (OpenAPI 3.1)
  const: propertyData.const,  // ← ADDED
  enum: propertyData.enum,
  default: propertyData.default,
  // ...remaining fields...
}
```

## Files Modified
- `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/page.tsx` (line ~433)

## Testing
To verify the fix works:

1. **Create a property with const value**
   - Go to Studio
   - Create a new property
   - Set type to "string"
   - Set const value to "test"
   - Save the property

2. **Drag to a class**
   - Drag the property to a class node on the canvas
   - The property should be added to the class

3. **Verify const is preserved**
   - Edit the property in the class (double-click or edit button)
   - Check that the const value "test" is still present
   - Verify enum is disabled (mutual exclusivity)

4. **Check in code view**
   - Switch to "Code" view
   - Verify the property schema includes `"const": "test"`

## Expected Behavior After Fix
When dragging a property with a const value to a class:
- ✅ The const value is preserved
- ✅ The enum field remains cleared (mutual exclusivity)
- ✅ The property data is complete and correct
- ✅ The JSON Schema output includes the const field

## Example Output
**Property in library:**
```json
{
  "type": "string",
  "const": "User",
  "description": "Object type discriminator"
}
```

**After dragging to class (should be identical):**
```json
{
  "type": "string",
  "const": "User",
  "description": "Object type discriminator"
}
```

## Status
✅ **FIXED** - Const values now properly copy when properties are added to class nodes

---
**Fix Date**: December 12, 2025  
**Reported By**: User  
**Fixed By**: GitHub Copilot

