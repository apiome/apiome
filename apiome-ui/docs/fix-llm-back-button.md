# Fix: Back Button Navigation from LLM Import

## Problem
When using the AI-Powered Import (LLM) feature, clicking the "Back" button would lead to a "llm import view - Coming soon" placeholder page instead of returning to the import source selection screen.

## Root Cause

The import flow has multiple steps:
1. **source** - Select import source (File, URL, Clipboard, Git, AI Assistant)
2. **file-upload** - Upload/input the specification
3. **analysis** - View analysis results
4. **preview** - Preview import options
5. **import** - Execute import
6. **done** - Import complete

The LLM import flow is special:
- Clicking "AI Assistant" opens a separate dialog (`LLMImportDialog`)
- When a spec is generated and imported, it sets `selectedSource = 'llm'`
- It bypasses the 'file-upload' step and goes straight to 'analysis'

The issue occurred when clicking "Back" from the 'analysis' step:
- The old code would go to 'file-upload' step
- At 'file-upload' with `selectedSource = 'llm'`, there was no specific UI handler
- It fell through to a generic placeholder showing "Coming soon"

## Solution

Modified the `handleBack()` function to detect when backing from an LLM-sourced analysis and skip the 'file-upload' step entirely, going straight back to source selection.

### Code Change

**Before:**
```typescript
} else if (currentStep === 'analysis') {
  setCurrentStep('file-upload');
  setAnalysisResult(null);
}
```

**After:**
```typescript
} else if (currentStep === 'analysis') {
  // If the source was LLM, skip file-upload and go straight back to source selection
  if (selectedSource === 'llm') {
    setCurrentStep('source');
    setSelectedSource(null);
    setClipboardContent(null);
    setClipboardFilename(null);
  } else {
    setCurrentStep('file-upload');
  }
  setAnalysisResult(null);
}
```

## Flow Diagram

### Before (Broken)
```
AI Assistant → LLM Dialog → Import Spec → [analysis] 
                                             ↓ Back
                                          [file-upload] with source='llm'
                                             ↓
                                          "Coming soon" ❌
```

### After (Fixed)
```
AI Assistant → LLM Dialog → Import Spec → [analysis] 
                                             ↓ Back
                                          [source] ✅
```

## Benefits

1. **Intuitive Navigation**: Back button now works as users expect
2. **Clean State**: Properly resets state when backing from LLM import
3. **No Dead Ends**: Eliminates the confusing "Coming soon" placeholder
4. **Consistent UX**: Matches the behavior of other import sources

## Files Modified

- `/src/app/components/ade/dashboard/ImportDialog.tsx` - Updated `handleBack()` function

## Testing

✅ Build compiles successfully
✅ No TypeScript errors
✅ Backward compatible with other import sources

## User Impact

Users can now:
- Import a spec using AI Assistant
- Navigate through analysis and preview
- Click "Back" to return to source selection
- Choose a different import method or start a new AI conversation

The confusing "Coming soon" message no longer appears in the navigation flow.

