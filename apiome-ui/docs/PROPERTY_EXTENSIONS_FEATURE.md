# Property Extensions Feature

## Overview
Added support for custom x- prefixed extension properties at the property level in the Apiome ADE Studio. This feature allows users to add arbitrary metadata to properties following the OpenAPI 3.1 specification.

## Implementation Date
December 12, 2025

## Feature Description
Users can now add custom x- prefixed properties to any property in their schema. These extensions are stored as a JSON object and automatically merged into the schema output during OpenAPI spec generation.

The implementation follows the same pattern as the class-level extensions editor, providing a familiar and consistent user experience.

## Changes Made

### 1. PropertyFormFields Component
**File:** `/src/app/components/ade/studio/PropertyFormFields.tsx`

#### Changes:
- Added `extensions?: Record<string, any>` field to `PropertyFormData` interface
- Imported `ExtensionsEditor` component
- Added Extensions section to the form UI (placed at the bottom of the form in a highlighted box)
- The ExtensionsEditor is rendered with the property's extensions data

```typescript
// Extensions (x- prefixed properties)
extensions?: Record<string, any>;
```

### 2. PropertyDialog Component  
**File:** `/src/app/components/ade/studio/PropertyDialog.tsx`

#### Changes:
- **Loading Extensions (Edit Mode):** When opening a property in edit mode, the component now extracts all x- prefixed properties from the property data and populates the `extensions` field in `formData`
- **Saving Extensions:** Before submitting the property data:
  1. Removes any existing x- prefixed properties from `dataObject`
  2. Merges in the current extensions from `formData.extensions`
  3. This ensures clean replacement of extensions on each save

```typescript
// Extract extensions (x- prefixed properties)
const extensions: Record<string, any> = {};
Object.keys(property as any).forEach(key => {
  if (key.startsWith('x-')) {
    extensions[key] = (property as any)[key];
  }
});
```

### 3. ClassPropertyEditDialog Component
**File:** `/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`

#### Changes:
- **Loading Extensions:** Extracts x- prefixed properties from the property data when loading for editing
- **Saving Extensions:** Implements the same clean replacement strategy as PropertyDialog:
  1. Removes existing x- properties
  2. Merges in current extensions
- Uses the existing `propData` variable to avoid redeclaration

## User Interface

### Extensions Section
- **Location:** Bottom of the property form, after all other constraints
- **Visual Style:** Displayed in a highlighted box with `bgcolor: 'action.hover'` for visual separation
- **Component:** Uses the existing `ExtensionsEditor` component that was already implemented for class-level extensions

### ExtensionsEditor Features
- **Key-Value Editor:** Simple interface to add extension properties
- **Validation:** 
  - Keys must start with "x-"
  - Keys can only contain letters, numbers, hyphens, and underscores after "x-"
  - Prevents duplicate keys
- **Value Format:** Accepts valid JSON or plain text
  - Values are automatically parsed as JSON if valid
  - Falls back to string if not valid JSON
- **Display:** Shows all extensions in a list format with:
  - Key displayed in monospace font with primary color
  - Value displayed as JSON string
  - Delete button for each entry

## Data Flow

### Property Creation (Add Mode)
1. User opens PropertyDialog in add mode
2. User fills in property details and optionally adds extensions
3. On submit, extensions are merged into the property data object
4. Property is saved with extensions included in the data JSON field

### Property Editing (Edit Mode)
1. User opens PropertyDialog or ClassPropertyEditDialog in edit mode
2. Component extracts x- prefixed properties from loaded data
3. Extensions are displayed in the ExtensionsEditor
4. User can add, modify, or remove extensions
5. On save:
   - All existing x- properties are removed from the data object
   - New extensions are merged in
   - Updated property is saved

### Schema Output
When the OpenAPI spec is generated, the extensions are automatically included in the property schema because they're stored as part of the property's data object. The schema generation utilities will preserve these x- prefixed properties.

## Backend Compatibility
No backend changes were required. The existing `updateClassProperty` function in `helper.ts` already:
- Stores property data as JSON: `data = $3` where `$3 = JSON.stringify(data)`
- Preserves all fields in the data object, including x- prefixed properties

## Testing Recommendations

### Manual Testing Steps
1. **Add Property with Extensions:**
   - Create a new property
   - Add an extension like `x-custom-field: "value"`
   - Save and verify it appears in the OpenAPI output

2. **Edit Property Extensions:**
   - Open an existing property for editing
   - Add a new extension
   - Remove an existing extension
   - Modify an extension value
   - Save and verify changes are persisted

3. **Extension Validation:**
   - Try adding a key without "x-" prefix (should show error)
   - Try adding invalid characters in key (should show error)
   - Try adding various JSON value types (string, number, boolean, object, array)
   - Verify all types are correctly preserved

4. **Different Property Types:**
   - Test with simple properties (string, number, boolean)
   - Test with array properties
   - Test with object properties
   - Test with properties that have $ref
   - Verify extensions work correctly for all types

5. **OpenAPI Output:**
   - Add extensions to multiple properties
   - Generate OpenAPI spec (JSON and YAML)
   - Verify extensions appear in the correct locations in the schema

## Technical Notes

### Storage Format
Extensions are stored as regular properties within the property's data JSON object:
```json
{
  "type": "string",
  "minLength": 1,
  "maxLength": 100,
  "x-custom-field": "value",
  "x-internal-id": 12345,
  "x-metadata": {
    "category": "user-input",
    "validation": "strict"
  }
}
```

### OpenAPI 3.1 Compliance
This implementation follows the OpenAPI 3.1 specification for extension properties:
- Extensions can be added to any schema object
- Extension keys must start with "x-"
- Extension values can be any valid JSON value
- Extensions are preserved during schema generation and validation

## Future Enhancements

Potential improvements for future versions:
1. **Preset Extensions:** Provide common extension templates (e.g., `x-deprecated-in`, `x-related-to`)
2. **Bulk Import/Export:** Allow importing extensions from JSON
3. **Extension Documentation:** Add tooltips or help text for commonly used extensions
4. **Extension Search:** Add search/filter capabilities when many extensions exist
5. **Extension Validation:** Custom validation rules for specific extension patterns
6. **Visual Indicators:** Show icon/badge on properties that have extensions

## Related Files
- `/src/app/components/ade/studio/ExtensionsEditor.tsx` - Reusable extension editor component
- `/src/app/components/ade/studio/ClassEditDialog.tsx` - Class-level extensions implementation (reference)
- `/lib/db/helper.ts` - Backend property update function
- `/src/app/utils/openapi.ts` - OpenAPI spec generation (automatically includes extensions)

