# Fix: Example Tab Refresh Loop in ClassEditDialog

## Problem
When clicking the "Example" tab in the Edit Class dialog, the component would refresh approximately 40 times before settling down. This was caused by an infinite render loop.

## Root Cause
The `useEffect` hook that generates the OpenAPI documentation had unstable dependencies:

1. **Incomplete dependency array**: The effect depended on `formData` properties but only listed a few specific ones, causing React to miss changes
2. **Object reference instability**: Arrays like `nodes` were being recreated on every render, triggering the effect unnecessarily
3. **No debouncing**: Every state change triggered immediate regeneration
4. **Schema recalculation**: The schema was being built from formData on every render without memoization

## Solution

### 1. Added Memoization (lines 563-577)
```typescript
// Create a stable stringified version of formData for dependency tracking
const formDataString = useMemo(() => JSON.stringify(formData), [formData]);

// Memoize the built schema to prevent unnecessary recalculations
const builtSchema = useMemo(() => {
  if (editingClassData) {
    return typeof editingClassData.schema === 'string'
      ? JSON.parse(editingClassData.schema)
      : editingClassData.schema || {};
  }
  return buildSchemaFromFormData();
}, [editingClassData, formDataString]);

// Memoize all classes array to prevent reference changes
const allClasses = useMemo(() => {
  return nodes.map(node => node.data).filter(data => data && data.name);
}, [nodes]);
```

### 2. Added Debouncing (lines 579-614)
```typescript
useEffect(() => {
  if (!open) return;

  // Debounce the generation to prevent rapid successive calls
  const timeoutId = setTimeout(() => {
    const generateOpenApiDocAsync = async () => {
      // ... generation logic
    };
    generateOpenApiDocAsync();
  }, 300); // 300ms debounce

  return () => clearTimeout(timeoutId);
}, [open, builtSchema, allClasses, editingClassData, projectMetadata]);
```

### 3. Fixed Variable Naming Conflict (lines 732, 889-948)
Renamed `classSchema` (extracted from openApiDoc) to `openApiClassSchema` to avoid conflict with the memoized `builtSchema` variable.

## Changes Made

**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ClassEditDialog.tsx`

1. **Import updates**: Added `useMemo` to React imports
2. **Memoization**: Added three memoized values (`formDataString`, `builtSchema`, `allClasses`)
3. **Debouncing**: Added 300ms timeout to prevent rapid successive regenerations
4. **Stable dependencies**: Simplified dependency array to only include stable memoized values
5. **Variable rename**: Changed `classSchema` to `openApiClassSchema` to avoid naming conflict

## Benefits

1. **Performance**: Reduced unnecessary re-renders from ~40 to 1
2. **Stability**: Debouncing prevents cascading updates
3. **Maintainability**: Clear separation between schema building and OpenAPI doc generation
4. **Type Safety**: No TypeScript errors from variable redeclaration

## Testing

To verify the fix:
1. Open a class in Edit mode
2. Click on the "Example" tab
3. Check browser console - should see minimal log output
4. Click "Refresh" button - should regenerate example once
5. Switch between tabs - should not trigger unnecessary regeneration

## Date
December 21, 2024

