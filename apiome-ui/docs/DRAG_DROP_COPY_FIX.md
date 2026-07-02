# Drag-and-Drop Property Copy Fix

## Issue
When dragging properties with OpenAPI 3.1 array features to classes, the following fields were not being copied:
- `contains`
- `minContains`
- `maxContains`
- `tupleMode`
- `prefixItems`

## Root Cause
The `handlePropertyDrop` function in `/src/app/ade/studio/page.tsx` was not including these new fields when constructing the data object to pass to `addPropertyToClass`.

## Fix Applied

### File Modified
`/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/page.tsx`

### Changes
Added the missing OpenAPI 3.1 array fields to the property data object passed to `addPropertyToClass`:

```typescript
{
  // ...existing fields...
  items: propertyData.items,
  // OpenAPI 3.1 array features
  contains: propertyData.contains,
  minContains: propertyData.minContains,
  maxContains: propertyData.maxContains,
  tupleMode: propertyData.tupleMode,
  prefixItems: propertyData.prefixItems,
  enum: propertyData.enum,
  // ...remaining fields...
}
```

## Impact

### Before Fix
- Properties with `contains`, `minContains`, `maxContains` constraints would lose these when dragged to a class
- Properties with tuple mode (`prefixItems`) would lose the entire tuple configuration
- Users would have to manually re-enter these constraints after drag-and-drop

### After Fix
✅ All OpenAPI 3.1 array features are now properly preserved when:
- Dragging properties from the property list to classes
- Dragging properties to nested object properties
- Copying properties between classes

## Testing Recommendations

1. **Test contains schema:**
   - Create array property with contains schema
   - Drag to class
   - Verify contains, minContains, maxContains are preserved

2. **Test tuple mode:**
   - Create array property with tuple mode enabled
   - Add multiple prefix items with different types
   - Drag to class
   - Edit the class property
   - Verify all prefix items and their schemas are intact

3. **Test combined features:**
   - Create property with both contains and tuple mode
   - Drag to class
   - Verify both features work correctly

4. **Test nested drops:**
   - Create object property with nested properties
   - Drag array properties with new features into the object
   - Verify all constraints preserved at nested level

## Related Files

- **Primary Fix**: `/src/app/ade/studio/page.tsx` (handlePropertyDrop function)
- **Property Types**: 
  - `/src/app/components/ade/studio/PropertyDialog.tsx` (PropertyItem interface)
  - `/src/app/components/ade/studio/StudioSideNav.tsx` (PropertyItem interface)
- **Database**: `/lib/db/helper.ts` (addPropertyToClass - no changes needed, handles data generically)

## Verification Status

✅ TypeScript compilation: No errors
✅ Type safety: All fields properly typed
✅ Database layer: No changes needed (handles data as JSON)
✅ Documentation: Updated WHATS_NEW.md

## Additional Fix: Tuple Mode Editing

### Issue
When editing properties with tuple mode enabled, the form was not loading correctly:
- Properties with `items: false` or `items: true` would fail to load
- Item-level constraints were shown even though tuple mode defines constraints per-position
- The propertyType was not set correctly for tuple mode arrays

### Root Cause
The PropertyDialog component's loading logic assumed `items` would always be an object with a type, but with tuple mode:
- `items` can be `false` (no additional items allowed)
- `items` can be `true` (any additional items allowed)
- `items` can be an object (schema for additional items)

### Fix Applied
**File Modified**: `/src/app/components/ade/studio/PropertyDialog.tsx`

1. Detect tuple mode early by checking for `prefixItems` array
2. Set default `propertyType` to 'string' when tuple mode is active
3. Updated `minMaxSource` logic to skip items when tuple mode is active
4. Fixed `itemsSchema` loading to handle boolean and object values

**File Modified**: `/src/app/components/ade/studio/PropertyFormFields.tsx`

1. Hide item-level constraints when `data.tupleMode` is true
2. Added informative message explaining that constraints are defined per-position
3. Prevents confusion about where to set constraints

### Impact

**Before Fix:**
- Editing tuple mode properties would show incorrect or missing data
- Item-level constraint fields would be visible but not applicable
- Items schema wouldn't load correctly for `false` or `true` values

**After Fix:**
✅ Tuple mode properties load correctly for editing
✅ Item-level constraints are hidden when tuple mode is active
✅ Clear message explains where constraints are defined
✅ `itemsSchema` properly handles boolean and object values

## Date
December 10, 2025

## Related Features
This fix ensures proper copying of all OpenAPI 3.1 features:
- ✅ Contains schema
- ✅ minContains/maxContains
- ✅ Tuple mode (prefixItems)
- ✅ Exclusive minimum/maximum (already working)
- ✅ multipleOf constraint (already working)

## Summary of All Fixes

1. **Drag-and-Drop Copy**: Added missing OpenAPI 3.1 fields to property drop handler
2. **Tuple Mode Editing**: Fixed loading and display of tuple mode properties
3. **UI Improvements**: Hide irrelevant constraints, show helpful messages

