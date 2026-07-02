# Implementation Summary: Tuple Mode (prefixItems) for OpenAPI 3.1.0

## Overview
Successfully implemented support for OpenAPI 3.1.0's `prefixItems` keyword, allowing users to define tuple-typed arrays with ordered, heterogeneous schemas.

## Implementation Date
December 10, 2025

## Changes Made

### 1. New Component: PrefixItemsEditor
**File:** `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PrefixItemsEditor.tsx`

- **Purpose:** Visual editor for managing tuple prefix items
- **Features:**
  - Add/remove prefix items for array positions
  - Drag-and-drop reordering using @dnd-kit
  - Type selection dropdown (string, number, integer, boolean, object, array, null, any)
  - JSON schema editor for each position with validation
  - Visual position indicators (0, 1, 2, etc.)
  - Helpful instructions and examples

### 2. Updated PropertyFormFields
**File:** `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyFormFields.tsx`

**Changes:**
- Added `tupleMode`, `prefixItems`, and `itemsSchema` to `PropertyFormData` interface
- Imported `PrefixItemsEditor` component
- Added new UI section in array constraints:
  - Checkbox toggle for "Tuple Mode (prefixItems)"
  - Integrated `PrefixItemsEditor` component (shown when tuple mode is enabled)
  - Text area for defining `items` schema for positions beyond prefix
  - Helper text explaining OpenAPI 3.1 compliance

**Location:** Added after contains/minContains/maxContains section, before Enum section

### 3. Updated PropertyDialog
**File:** `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyDialog.tsx`

**Changes to PropertyItem interface:**
- Added `tupleMode?: boolean`
- Added `prefixItems?: any[]`
- Added `items?: any`

**Changes to form loading logic (useEffect):**
- Load `tupleMode` from property data (true if prefixItems exists)
- Load `prefixItems` array from property data
- Load `itemsSchema` as JSON string if items is an object

**Changes to save logic (handleSubmit):**
- When tuple mode enabled and prefixItems exist:
  - Save `prefixItems` array to dataObject
  - Parse and save `itemsSchema` as `items` (defaults to `true` if empty)
- When tuple mode disabled:
  - Delete `prefixItems` from dataObject
  - Use regular items schema with full field preservation

**Changes to buildPropertyJsonSchema:**
- Check for tuple mode and generate `prefixItems` in schema
- Set `items` based on itemsSchema field
- Wrap regular items logic in else block for non-tuple arrays

### 4. Updated StudioSideNav
**File:** `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/StudioSideNav.tsx`

**Changes:**
- Added `tupleMode?: boolean` to PropertyItem interface
- Added `prefixItems?: any[]` to PropertyItem interface
- Added `items?: any` to PropertyItem interface

**Reason:** Ensures type compatibility between PropertyDialog and StudioSideNav

### 5. Documentation Updates

**Feature Roadmap:**
**File:** `/Users/kenji/Development/apiome/FEATURE_ROADMAP.md`

- Added "OpenAPI 3.1 Array Features" section with ✅ IMPLEMENTED marker
- Documented tuple mode, contains, minContains/maxContains, exclusive min/max
- Listed all features in the Advanced Property Editor section

**Feature Documentation:**
**File:** `/Users/kenji/Development/apiome/apiome-ui/docs/TUPLE_MODE_FEATURE.md`

- Comprehensive guide on using tuple mode
- Examples and use cases
- JSON Schema compliance notes
- Technical implementation details
- Migration notes and testing instructions

## Data Structure

### Form Data (PropertyFormData)
```typescript
{
  tupleMode?: boolean;
  prefixItems?: any[];
  itemsSchema?: string; // JSON string representation
}
```

### Property Data (saved to database)
```json
{
  "type": "array",
  "prefixItems": [
    { "type": "number", "minimum": -90, "maximum": 90 },
    { "type": "number", "minimum": -180, "maximum": 180 }
  ],
  "items": false,
  "minItems": 2,
  "maxItems": 2
}
```

## User Flow

1. User opens property dialog for an array property
2. User checks "Tuple Mode (prefixItems)" checkbox
3. User clicks "Add Position" to add prefix items
4. User configures each position:
   - Select type from dropdown
   - Edit JSON schema in text area
5. User defines items schema for additional positions (or set to `false`)
6. User saves the property
7. Property data includes `prefixItems` array and `items` schema

## OpenAPI 3.1.0 Compliance

The implementation follows the JSON Schema Draft 2020-12 specification used by OpenAPI 3.1.0:

- `prefixItems` is an array of schemas
- Each schema validates the array element at the corresponding index
- `items` validates all elements beyond the prefix
- `items: false` prevents additional items (strict tuple)
- `items: true` or undefined allows any additional items

## Testing Recommendations

1. **Basic tuple creation:**
   - Create array property
   - Enable tuple mode
   - Add 2-3 prefix items with different types
   - Save and verify in JSON view

2. **Strict tuple:**
   - Set items to `false`
   - Verify minItems/maxItems match prefix count

3. **Flexible tuple:**
   - Set items to `{"type": "string"}`
   - Verify additional items allowed

4. **Drag-and-drop:**
   - Reorder prefix items
   - Verify order is preserved in JSON

5. **Edit existing:**
   - Edit property with prefixItems
   - Verify data loads correctly
   - Modify and save
   - Verify changes persist

6. **Disable tuple mode:**
   - Enable tuple mode and add items
   - Disable tuple mode
   - Verify prefixItems removed, regular items preserved

## Backward Compatibility

- ✅ Existing array properties without prefixItems continue to work
- ✅ Regular items schema is preserved when not in tuple mode
- ✅ No breaking changes to existing functionality
- ✅ OpenAPI 3.0 tools will ignore prefixItems gracefully

## Known Issues / Limitations

None identified. All TypeScript compilation checks pass with only pre-existing warnings.

## Future Enhancements

Potential improvements for future iterations:

1. **Visual tuple preview:** Show example values that match the schema
2. **Tuple templates:** Pre-built patterns (coordinates, RGB, etc.)
3. **Import from examples:** Auto-generate from sample data
4. **Validation preview:** Real-time validation of sample data
5. **Position descriptions:** UI field for describing each position

## Related Features

This feature complements other OpenAPI 3.1 array features already implemented:

- ✅ Contains schema
- ✅ minContains/maxContains
- ✅ Exclusive minimum/maximum (numeric values, not boolean)
- ✅ multipleOf constraint

## Files Changed Summary

| File | Lines Changed | Type |
|------|--------------|------|
| PrefixItemsEditor.tsx | 260+ | New file |
| PropertyFormFields.tsx | ~60 | Modified |
| PropertyDialog.tsx | ~80 | Modified |
| StudioSideNav.tsx | ~5 | Modified |
| FEATURE_ROADMAP.md | ~15 | Modified |
| TUPLE_MODE_FEATURE.md | 200+ | New file |

## Verification Status

✅ TypeScript compilation: No errors
✅ Type compatibility: PropertyItem interfaces match across files
✅ Form data flow: Load and save logic implemented
✅ UI integration: Component integrated into PropertyFormFields
✅ Documentation: Feature documented in roadmap and guide

## Deployment Notes

- No database migrations required
- No API changes required
- Feature is opt-in (checkbox toggle)
- Safe to deploy to production

