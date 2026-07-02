# ClassEditDialog Async OpenAPI Fix

## Issue Summary

The error **"Cannot read properties of undefined (reading 'schemas')"** occurred in `ClassEditDialog.tsx` at line 325 when trying to access `openApiDoc.components.schemas`. This happened because `generateClassOpenApiSpec` was changed to be an async function, but the component was calling it synchronously during render.

## Root Cause

When the OpenAPI generation functions were updated to use `async/await` (to properly handle the async `renderTemplate` function), `generateClassOpenApiSpec` now returns a `Promise<any>` instead of the OpenAPI document directly.

The component was calling it like this:
```typescript
const openApiDoc = generateClassOpenApiSpec(...);  // Returns Promise, not the doc
const classSchema = openApiDoc.components.schemas[...];  // Error: openApiDoc is a Promise!
```

## Solution

Refactored the component to handle async OpenAPI generation properly:

### 1. Added State Management
```typescript
const [openApiDoc, setOpenApiDoc] = useState<any>(null);
const [loadingOpenApiDoc, setLoadingOpenApiDoc] = useState(false);
```

### 2. Created useEffect Hook for Async Generation
```typescript
useEffect(() => {
  const generateOpenApiDocAsync = async () => {
    if (!open) return;
    
    setLoadingOpenApiDoc(true);
    try {
      const doc = await generateClassOpenApiSpec(...);
      setOpenApiDoc(doc);
    } catch (error) {
      console.error('Failed to generate OpenAPI doc:', error);
      setOpenApiDoc(null);
    } finally {
      setLoadingOpenApiDoc(false);
    }
  };
  
  generateOpenApiDocAsync();
}, [open, editingClassData, formData fields, nodes]);
```

### 3. Added Null Safety Checks
Updated all code that accesses `openApiDoc` to handle the null/loading state:

```typescript
// Safe access with optional chaining
const classSchema = openApiDoc?.components?.schemas?.[previewClassData.name];

// Loading state in content generation
if (loadingOpenApiDoc || !openApiDoc) {
  schemaContent = '// Loading schema...';
}

// Disabled buttons while loading
disabled={loadingOpenApiDoc || !openApiDoc}
```

### 4. Created Helper Function for Schema Building
Extracted the schema building logic into a reusable helper function:

```typescript
const buildSchemaFromFormData = () => {
  const schema: any = { type: 'object', properties: {} };
  
  // Add composition types (allOf, anyOf, oneOf)
  // Add discriminator
  // Add additionalProperties
  
  return schema;
};
```

This helper is used both in:
- The preview OpenAPI generation (in useEffect)
- The save handler (when persisting to database)

### 5. Updated Button States
All action buttons (Copy, Export, Refresh) are now disabled while the OpenAPI doc is loading:
- JSON view buttons
- YAML view buttons  
- Example view buttons

## Changes Made

**File:** `src/app/components/ade/studio/ClassEditDialog.tsx`

1. Added state variables for `openApiDoc` and `loadingOpenApiDoc`
2. Created `buildSchemaFromFormData()` helper function
3. Added `useEffect` hook to generate OpenAPI doc asynchronously
4. Removed synchronous `generateClassOpenApiSpec` call from render
5. Added null checks with optional chaining for `openApiDoc` access
6. Updated all button `disabled` props to include loading state
7. Added loading message for schema content
8. Refactored `handleSave` to use the helper function (DRY principle)

## Dependencies

The useEffect regenerates the OpenAPI doc when any of these change:
- `open` - Dialog open state
- `editingClassData` - The class being edited
- `formData.name` - Class name
- `formData.description` - Class description
- `formData.allOf` - Composition: all of
- `formData.anyOf` - Composition: any of
- `formData.oneOf` - Composition: one of
- `formData.discriminatorProperty` - Discriminator property name
- `formData.discriminatorUseAuto` - Auto-generate discriminator mapping
- `formData.additionalProperties` - Additional properties setting
- `nodes` - All classes in the diagram

## User Experience Improvements

1. **Loading State**: Users see "Loading schema..." while the OpenAPI doc is being generated
2. **Disabled Actions**: Buttons are disabled during loading to prevent errors
3. **Real-time Preview**: OpenAPI doc updates as user changes form fields
4. **Error Handling**: Gracefully handles generation failures with console errors

## Testing

To verify the fix:
1. Open the Class Edit Dialog
2. The JSON/YAML/Example tabs should show "Loading schema..." briefly
3. Once loaded, the schema should display correctly
4. Changing form fields should trigger regeneration
5. No errors should appear in the console about undefined properties

## Related Files

- `src/app/components/ade/studio/ClassEditDialog.tsx` - Main component (fixed)
- `src/app/utils/openapi.ts` - OpenAPI generation utilities (async functions)
- `src/app/utils/template-loader.ts` - Template rendering (async)

## Date Fixed
December 11, 2024

