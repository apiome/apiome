# Auto-Refresh Projects List After Import

## Problem
After completing an import and closing the import dialog, the projects list was not automatically refreshed. Users had to manually refresh the page to see the newly imported project appear in the list.

## Solution
Implemented an `onSuccess` callback mechanism in the ImportDialog that triggers the projects list refresh when an import completes successfully.

## Implementation

### 1. Added onSuccess Callback to ImportDialog

**File:** `src/app/components/ade/dashboard/ImportDialog.tsx`

**Changes:**

1. **Added onSuccess prop to interface:**
```typescript
interface ImportDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;  // ← New optional callback
  tenantId: string;
  userId: string;
}
```

2. **Added success tracking state:**
```typescript
const [importSucceeded, setImportSucceeded] = useState(false);
```

3. **Updated handleClose to call onSuccess:**
```typescript
const handleClose = () => {
  // Call onSuccess callback if import completed successfully
  if (importSucceeded && onSuccess) {
    onSuccess();
  }
  
  // Reset all state
  setCurrentStep('source');
  setSelectedSource(null);
  setSelectedFile(null);
  setAnalysisResult(null);
  setImportOptions(null);
  setJobId(null);
  setImportSucceeded(false);
  onClose();
};
```

4. **Updated ImportExecutionPanel onDone callback to check status:**
```typescript
<ImportExecutionPanel 
  jobId={jobId} 
  onDone={() => {
    // Check import status to determine if it was successful
    getImportStatus(jobId).then((status) => {
      if (status.state === 'completed') {
        setImportSucceeded(true);
      }
    });
    setCurrentStep('done');
  }} 
/>
```

5. **Imported getImportStatus:**
```typescript
import { startImport, getImportStatus } from '../../../../../lib/db/import-actions';
```

### 2. Connected to Projects Page

**File:** `src/app/ade/dashboard/projects/page.tsx`

**Change:**
```typescript
<ImportDialog
  open={showNewImportDialog}
  onClose={() => setShowNewImportDialog(false)}
  onSuccess={handleImportSuccess}  // ← Added callback
  tenantId={currentTenantId}
  userId={currentUserId}
/>
```

The `handleImportSuccess` function already exists and calls `loadProjects()` to refresh the list.

## Flow

### Before Fix
```
1. User imports OpenAPI spec
2. Import completes successfully
3. User clicks "Close" button
4. Dialog closes
5. Projects list shows old data ❌
6. User must refresh page to see new project
```

### After Fix
```
1. User imports OpenAPI spec
2. Import completes successfully (state = 'completed')
3. importSucceeded flag is set to true ✅
4. User clicks "Close" button
5. handleClose detects importSucceeded = true
6. Calls onSuccess() callback
7. Projects list refreshes automatically ✅
8. Dialog closes
9. New project appears in list immediately ✅
```

## Edge Cases Handled

### 1. Failed Import
```typescript
if (status.state === 'completed') {  // Only set flag if completed
  setImportSucceeded(true);
}
```
- Failed or canceled imports do NOT trigger refresh
- User sees error in dialog, list unchanged

### 2. User Closes During Import
- importSucceeded remains false
- No refresh triggered (import not finished)
- Correct behavior: partial import shouldn't show

### 3. User Closes Without Starting Import
- importSucceeded remains false
- No refresh triggered
- No wasted API calls

### 4. Multiple Open/Close Cycles
- State reset on handleClose: `setImportSucceeded(false)`
- Each import tracked independently
- No state leakage between sessions

## State Management

### Success Flag Lifecycle
```
1. Dialog opens → importSucceeded = false
2. User goes through steps (source → upload → analyze → preview)
3. User clicks "Import →"
4. Import runs → ImportExecutionPanel monitors
5. Import completes → onDone callback fires
6. getImportStatus checks state
7. If state === 'completed' → importSucceeded = true
8. User clicks "Close"
9. handleClose checks importSucceeded
10. If true → onSuccess() called
11. State reset → importSucceeded = false
12. Dialog closes
```

## Testing

### Manual Test
```bash
yarn --cwd apiome/apiome-ui dev

# 1. Navigate to: ADE → Dashboard → Projects
# 2. Note current project count
# 3. Click "Import" button
# 4. Upload OpenAPI spec (e.g., test-property-reuse-same.yaml)
# 5. Follow wizard: Analyze → Preview → Import
# 6. Wait for import to complete (100%)
# 7. Click "Close" button
# 8. ✅ Verify projects list refreshes automatically
# 9. ✅ Verify new project appears in list
```

### Verification Points
1. **Import Success:** Status shows "COMPLETED" ✅
2. **Close Triggers Refresh:** List updates without page reload ✅
3. **Failed Import:** No refresh on failure ✅
4. **Cancel Import:** No refresh on cancel ✅
5. **Close During Import:** No refresh (import not finished) ✅

## Build Status
✅ **Build: PASSED**
- No TypeScript errors
- Only non-blocking style warnings
- All functionality compiles correctly

## Files Modified

1. `src/app/components/ade/dashboard/ImportDialog.tsx`
   - Added onSuccess prop to interface
   - Added importSucceeded state tracking
   - Updated handleClose to trigger callback
   - Modified ImportExecutionPanel onDone to check status
   - Imported getImportStatus function

2. `src/app/ade/dashboard/projects/page.tsx`
   - Added onSuccess={handleImportSuccess} to ImportDialog

## Related Components

- **ImportExecutionPanel** - Signals when import completes
- **import-actions.ts** - getImportStatus function
- **import-helper.ts** - Backend import orchestration
- **Projects page** - loadProjects function

## Benefits

✅ **Better UX:** Immediate feedback - new project appears
✅ **No manual refresh:** Automatic list update
✅ **Smart refresh:** Only refreshes on successful import
✅ **Clean state:** No refresh on failure/cancel
✅ **Minimal change:** Reuses existing handleImportSuccess function

## Date
December 24, 2025

---

## Summary
The projects list now automatically refreshes when the import dialog closes after a successful import. The refresh is only triggered for completed imports, not for failures or cancellations, providing optimal user experience without unnecessary API calls.

