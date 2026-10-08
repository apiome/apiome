# Import Dialog - Keep Progress Visible

## Change Summary

Modified the ImportDialog to keep it open after import completion so users can review the progress and logs.

## What Changed

### 1. Done State (Step 5) Content
**Before:**
```typescript
} else if (currentStep === 'done') {
  return (
    <div className="text-center py-24 text-gray-700 dark:text-gray-300">
      Import complete. You can close this dialog.
    </div>
  );
}
```

**After:**
```typescript
} else if (currentStep === 'done') {
  return jobId ? (
    <ImportExecutionPanel jobId={jobId} />
  ) : null;
}
```

**Benefit**: The ImportExecutionPanel remains visible showing:
- ✅ Final import status (completed)
- ✅ Full progress bar at 100%
- ✅ Live Progress section with all events
- ✅ Import Log with all import steps and messages
- ✅ Import Summary with project and version details

### 2. Footer Buttons
**Before:**
- Back button (to go to preview)
- Cancel button
- Step-specific buttons (Analyze, Next, Import)

**After:**
- For import/done states: Empty space on left, "Close" button on right
- For other states: Same as before

**Benefit**: Users can review the complete import results without being forced to close immediately.

## User Experience Flow

1. **Steps 1-3**: Select source → Upload → Analyze → Preview (with navigation buttons)
2. **Step 4 (Import)**: Progress bar updates in real-time, Live Progress and Import Log visible
3. **Step 5 (Done)**: Dialog stays open, ImportExecutionPanel shows final status with:
   - ✅ Status badge showing "COMPLETED"
   - ✅ 100% progress bar
   - ✅ All import events in Live Progress list
   - ✅ Complete Import Log with timestamps
   - ✅ Summary details (projectId, versionId)
4. **Close**: User clicks "Close" button when done reviewing

## Build Status
✅ Build: PASSED
✅ No TypeScript errors
✅ Dialog displays correctly in both import and done states

## Testing

```bash
yarn --cwd apiome/apiome-ui dev
# Navigate to: ADE → Dashboard → Projects → Import
# Upload: examples/02-array-contains.yaml
# Follow wizard through preview
# Click "Import →"
# Watch progress in real-time
# When complete, dialog stays open showing final results
# Review Import Log and Summary
# Click "Close" to dismiss
```

## Related Changes

This change works with:
- ImportExecutionPanel component (Step 4 UI)
- import-helper.ts server actions (orchestration)
- import-actions.ts (client-side wrapper)
- OpenAPI importer (data normalization)

All components properly handle the data flow from import start to completion.

