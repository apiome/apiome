# Class Edit Dialog Refactor - Removing Duplication

## Problem
The initial implementation created duplicate edit forms:
1. Original edit form in `layout.tsx` (sidebar)
2. New duplicate edit form in `ClassEditDialog.tsx` (canvas)

This resulted in code duplication and maintenance overhead.

## Solution
Refactored to use a single source of truth:
- **ONE edit form** in `layout.tsx` (sidebar)
- Enhanced with tabs: Edit | JSON | YAML | Example
- Canvas double-click triggers the sidebar's dialog
- Removed the duplicate `ClassEditDialog` component entirely

## Changes Made

### 1. Enhanced layout.tsx (Sidebar Dialog)

#### Added Imports:
```typescript
import { Tabs, Tab } from '@mui/material';
import { Copy, Download, RefreshCw, Check } from 'lucide-react';
import YAML from 'yaml';
import jsf from 'json-schema-faker';
import { generateClassOpenApiSpec } from '../../utils/openapi';
```

#### Added State:
```typescript
const [classDialogTab, setClassDialogTab] = useState(0);
const [exampleRefreshKey, setExampleRefreshKey] = useState(0);
const [copied, setCopied] = useState(false);
```

#### Added Tabs to Dialog:
- **Tab 0 (Edit)**: Original edit form with all fields
- **Tab 1 (JSON)**: View OpenAPI schema in JSON format
- **Tab 2 (YAML)**: View OpenAPI schema in YAML format
- **Tab 3 (Example)**: Generate example payloads with refresh capability

#### Exposed Handler via Window:
```typescript
const handleClassEditRef = React.useRef<...>();
React.useEffect(() => {
  handleClassEditRef.current = handleClassEdit;
  (window as any).__studioHandleClassEdit = handleClassEdit;
}, [handleClassEdit]);
```

### 2. Updated page.tsx (Canvas)

#### Removed:
- `ClassEditDialog` component import
- `classEditDialogOpen` state
- `editingClassData` state
- `<ClassEditDialog>` JSX

#### Modified `handleClassEdit`:
```typescript
const handleClassEdit = useCallback(async (classData: any) => {
  console.log(isReadOnly ? 'Viewing class:' : 'Editing class:', classData);
  const sidebarHandler = (window as any).__studioHandleClassEdit;
  if (sidebarHandler) {
    const classItem = {
      id: classData.id,
      name: classData.name,
      description: classData.description || '',
      schema: classData.schema
    };
    await sidebarHandler(classItem);
  }
}, [isReadOnly]);
```

### 3. Dialog Behavior

#### Add Mode (unchanged):
- Shows only the Edit tab
- Save button creates new class

#### Edit Mode (enhanced):
- Shows 4 tabs: Edit | JSON | YAML | Example
- Tab 0: Full edit form (same as before)
- Tabs 1-3: View-only schema representations
- Save button only visible on Edit tab
- Close button on view tabs

## Features

### Edit Tab
- Edit class name (validated)
- Edit description
- Configure composition (allOf/anyOf/oneOf)
- Set discriminator
- Configure additional properties
- **Save** button to persist changes

### JSON Tab
- View complete OpenAPI 3.1.0 schema
- Copy to clipboard
- Export to file

### YAML Tab
- View complete OpenAPI 3.1.0 schema in YAML
- Copy to clipboard
- Export to file

### Example Tab
- Generate fake data from schema using json-schema-faker
- **Refresh** button to generate new examples
- Copy to clipboard
- Export to file
- Handles circular references gracefully

## User Experience

### Before:
```
Double-click node → Opens separate ClassEditDialog (duplicate form)
Sidebar Edit button → Opens layout.tsx dialog (original form)
= Two different dialogs with duplicate code
```

### After:
```
Double-click node → Opens sidebar's tabbed dialog
Sidebar Edit button → Opens sidebar's tabbed dialog  
= One unified dialog with Edit + View capabilities
```

## Technical Implementation

### Communication Pattern:
1. Canvas node is double-clicked
2. `handleClassEdit` in page.tsx is called
3. Calls global `__studioHandleClassEdit` function
4. Sidebar's `handleClassEdit` in layout.tsx is invoked
5. Dialog opens with tabs

### Tab Content Generation:
- Edit tab: Shows form fields from state
- View tabs: Generate content on-demand using IIFE
- OpenAPI spec generated from class schema
- References resolved for example generation

### State Management:
- Tab state: `classDialogTab` (0-3)
- Example refresh: `exampleRefreshKey` (incremented to regenerate)
- Copy status: `copied` (temporary visual feedback)

## Benefits

✅ **No Code Duplication**: Single edit form implementation
✅ **Consistent UX**: Same dialog from canvas or sidebar
✅ **Maintainability**: Changes only needed in one place
✅ **Feature Parity**: All features available from both entry points
✅ **Clean Architecture**: Clear separation of concerns

## Files Modified

1. `/src/app/ade/studio/layout.tsx`
   - Added tabs to class dialog
   - Added JSON/YAML/Example view logic
   - Exposed handleClassEdit via window

2. `/src/app/ade/studio/page.tsx`
   - Removed ClassEditDialog usage
   - Updated handleClassEdit to call sidebar handler
   - Removed duplicate state

3. `/src/app/components/ade/studio/ClassEditDialog.tsx`
   - ~~Can be safely deleted~~ (not deleted yet, but no longer used)

## Future Cleanup

The ClassEditDialog.tsx file can now be safely deleted as it's no longer used anywhere in the application. It was completely replaced by the enhanced dialog in layout.tsx.

---

**Date**: December 6, 2024  
**Refactor Type**: Eliminate Duplication  
**Status**: ✅ Complete

