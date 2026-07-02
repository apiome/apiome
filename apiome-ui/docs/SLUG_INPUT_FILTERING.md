# Slug Input Filtering Implementation

## Overview
Implemented real-time filtering of slug input fields to ensure they only accept valid slug characters (a-z, 0-9, and hyphens) as users type.

## Changes Made

### 1. Created Slug Utility Module
**File:** `src/app/utils/slug.ts`

Created a new utility module with the following functions:
- `filterSlugInput(value: string)`: Filters input to only allow `a-z0-9-` characters
- `generateSlug(name: string)`: Generates a URL-friendly slug from a name
- `isValidSlug(slug: string)`: Validates if a string is a valid slug

### 2. Updated Projects Page
**File:** `src/app/ade/dashboard/projects/page.tsx`

- Imported `filterSlugInput` and `generateSlug` from the new utility module
- Removed the local `generateSlug` function (now using the shared utility)
- Updated the Create Project dialog slug input to use `filterSlugInput(e.target.value)` instead of `e.target.value.toLowerCase()`
- Updated the Edit Project dialog slug input with the same filtering

### 3. Updated OpenAPI Import Dialog
**File:** `src/app/components/ade/dashboard/OpenAPIImportDialog.tsx`

- Imported `filterSlugInput` and `generateSlug` from the utility module
- Removed the local `generateSlug` function (now using the shared utility)
- Updated the Project Slug input to use `filterSlugInput(e.target.value)` instead of `e.target.value.toLowerCase()`

## Behavior

### Before
- Slug inputs would convert text to lowercase but allowed any characters
- Users could type invalid characters which would only be rejected on form submission

### After
- Slug inputs filter characters in real-time as users type
- Only lowercase letters (a-z), numbers (0-9), and hyphens (-) are allowed
- Invalid characters are silently removed as the user types
- The input helper text guides users: "URL-friendly identifier (lowercase letters, numbers, and dashes only)"

## Technical Details

### Filter Pattern
The `filterSlugInput` function uses the following logic:
```typescript
return value
  .toLowerCase()           // Convert to lowercase
  .replace(/[^a-z0-9-]/g, ''); // Remove any character that's not a-z, 0-9, or -
```

### Auto-generation Preservation
Both the Projects page and OpenAPI Import Dialog maintain the smart auto-generation behavior:
- When the name field changes, the slug is automatically generated if:
  - The slug field is empty, OR
  - The slug matches the previous auto-generated value
- Once the user manually edits the slug, auto-generation stops

## Files Modified
1. `/src/app/utils/slug.ts` (new file)
2. `/src/app/ade/dashboard/projects/page.tsx`
3. `/src/app/components/ade/dashboard/OpenAPIImportDialog.tsx`

## Testing
To test the implementation:
1. Navigate to Projects page
2. Click "New Project"
3. Try typing special characters, uppercase letters, or spaces in the Slug field
4. Verify that only lowercase letters, numbers, and hyphens appear
5. Repeat for the OpenAPI import dialog

## Future Considerations
- The `isValidSlug()` utility function is available for additional validation if needed
- The same pattern can be applied to any other slug input fields in the application
- Consider adding visual feedback (e.g., red border) when invalid characters are attempted

