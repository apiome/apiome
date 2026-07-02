# Class Edit Dialog Enhancement

> **⚠️ SUPERSEDED**: This document describes an initial implementation that created duplicate code.  
> **See [CLASS_EDIT_REFACTOR.md](./CLASS_EDIT_REFACTOR.md) for the final, refactored implementation.**

## Summary
Enhanced the `ClassEditDialog` component to combine both editing capabilities and viewing modes (JSON/YAML/Example) into a single tabbed interface. This addresses the user request to unify the double-click behavior on class nodes with the edit class functionality.

## Changes Made

### 1. ClassEditDialog Component (`/src/app/components/ade/studio/ClassEditDialog.tsx`)

#### Added Features:
- **Tabbed Interface**: Added 4 tabs:
  - **Edit Tab**: Full form for editing class properties
  - **JSON Tab**: View class schema as JSON (OpenAPI format)
  - **YAML Tab**: View class schema as YAML (OpenAPI format)
  - **Example Tab**: Generate and view example payload from schema

#### Edit Tab Capabilities:
- Edit class name (alphanumeric and underscore only)
- Edit class description
- Configure composition/inheritance:
  - `allOf` (Inheritance) - must match all listed schemas
  - `anyOf` (Alternatives) - must match at least one listed schema
  - `oneOf` (Exclusive) - must match exactly one listed schema
- Configure discriminator:
  - Property name for polymorphic object handling
  - Automatic or manual mapping
- Configure additional properties:
  - Not specified (default)
  - Allow additional properties (true)
  - Disallow additional properties (false)

#### New State Management:
- `tabValue`: Tracks active tab (0=Edit, 1=JSON, 2=YAML, 3=Example)
- `formData`: Holds all editable class properties
- `saving`: Loading state during save operation

#### New Props:
- `onSave`: Optional callback function called after successful save

#### Form Validation:
- Class name is required
- Only alphanumeric characters and underscores allowed in class names
- Error messages displayed in Alert component

### 2. Studio Page Component (`/src/app/ade/studio/page.tsx`)

#### Updated ClassEditDialog Usage:
- Added `onSave` callback to refresh canvas and sidebar after editing:
  ```typescript
  onSave={() => {
    reloadClasses();
    triggerSidebarRefresh();
  }}
  ```

## User Experience Flow

### Before:
1. Double-clicking a class node → Opens view-only dialog with JSON/YAML/Example tabs
2. To edit class properties → Must use sidebar "Edit Class" button
3. Two separate interfaces for viewing and editing

### After:
1. Double-clicking a class node → Opens unified dialog with 4 tabs
2. **Edit tab** → Full form to modify class name, description, composition, discriminator, and additional properties
3. **JSON/YAML/Example tabs** → View generated OpenAPI schema and example payloads
4. Save button available in Edit tab (when not in read-only mode)
5. Cancel/Close button to exit without saving

## Technical Details

### Data Flow:
1. Dialog opens with `editingClassData` passed from parent
2. Form state initialized from existing class schema
3. User can switch between tabs without losing form changes
4. On save:
   - Form data validated
   - Schema reconstructed from form values
   - `updateClass` API called
   - On success: `onSave` callback fired, dialog closes
   - On error: Error message displayed in form

### Schema Reconstruction:
The form data is converted back into a JSON Schema structure:
```typescript
{
  type: 'object',
  properties: {},
  allOf: [...],        // if specified
  anyOf: [...],        // if specified
  oneOf: [...],        // if specified
  discriminator: {...}, // if specified
  additionalProperties: true/false // if specified
}
```

### Composition Selector:
- Uses MUI Autocomplete with multi-select
- Filters available classes (excludes current class)
- Displays selected classes as colored chips
- Different colors for different composition types:
  - `allOf`: primary (blue)
  - `anyOf`: info (light blue)
  - `oneOf`: secondary (purple)

## Read-Only Mode
When `isReadOnly={true}`:
- Edit tab is still accessible but all form fields are disabled
- "Read Only" badge displayed in dialog title
- Save button hidden
- Users can view configuration but cannot modify

## Future Enhancements
Possible improvements:
- Add validation for discriminator property existence in composed schemas
- Preview of how discriminator affects serialization
- Visual diff of changes before saving
- Undo/redo functionality
- Import/export class configuration
- Duplicate class functionality

## Testing Checklist
- [ ] Double-click class node opens dialog
- [ ] Edit tab shows correct class name and description
- [ ] Composition fields (allOf/anyOf/oneOf) populated correctly
- [ ] Discriminator settings displayed if configured
- [ ] Additional properties setting reflects schema
- [ ] Save button updates class successfully
- [ ] Canvas refreshes after save
- [ ] Sidebar refreshes after save
- [ ] JSON tab shows valid OpenAPI schema
- [ ] YAML tab shows valid OpenAPI schema
- [ ] Example tab generates valid example payload
- [ ] Refresh button in Example tab generates new examples
- [ ] Copy/Export buttons work in view tabs
- [ ] Read-only mode disables form fields
- [ ] Validation errors display correctly
- [ ] Dialog closes on cancel/close

