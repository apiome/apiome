# Build Error Fix - currentProject/currentVersion Scope Issue

## Error Message
```
./src/app/ade/studio/page.tsx:1605:28
Type error: Cannot find name 'currentProject'.

  1603 |             // Generate fresh Python DTOs
  1604 |             const pythonCode = generatePythonDTOs(classesWithProperties, {
> 1605 |               projectName: currentProject?.name,
       |                            ^
  1606 |               version: currentVersion?.version_id,
  1607 |               description: `Data Transfer Objects for ${currentProject?.name || 'API'}`
  1608 |             });
Next.js build worker exited with code: 1 and signal: null
```

## Root Cause
The variables `currentProject` and `currentVersion` were declared inside the `if (viewMode === 'code')` block, making them unavailable in the subsequent `else if (viewMode === 'generate')` block.

### Before (Broken)
```typescript
if (viewMode === 'code') {
  const currentProject = projects.find(p => p.id === selectedProjectId);
  const currentVersion = versions.find(v => v.id === selectedVersionId);
  // ... use variables
} else if (viewMode === 'generate') {
  // ❌ currentProject and currentVersion not available here!
  generatePythonDTOs(classesWithProperties, {
    projectName: currentProject?.name,  // Error!
    version: currentVersion?.version_id  // Error!
  });
}
```

## Solution
Moved the variable declarations outside the if blocks so they're available to all branches.

### After (Fixed)
```typescript
// Get current project and version for metadata
const currentProject = projects.find(p => p.id === selectedProjectId);
const currentVersion = versions.find(v => v.id === selectedVersionId);

if (viewMode === 'code') {
  // ✅ Variables available here
  generateOpenApiSpec(classesWithProperties, {
    projectName: currentProject?.name,
    version: currentVersion?.version_id
  });
} else if (viewMode === 'generate') {
  // ✅ Variables available here too!
  generatePythonDTOs(classesWithProperties, {
    projectName: currentProject?.name,
    version: currentVersion?.version_id
  });
}
```

## Changes Made

**File**: `/src/app/ade/studio/page.tsx`

**Lines ~1568-1578**: Moved variable declarations

```typescript
// Before:
const classesWithProperties = await Promise.all(...);

if (viewMode === 'code') {
  const currentProject = projects.find(p => p.id === selectedProjectId);
  const currentVersion = versions.find(v => v.id === selectedVersionId);

// After:
const classesWithProperties = await Promise.all(...);

// Get current project and version for metadata
const currentProject = projects.find(p => p.id === selectedProjectId);
const currentVersion = versions.find(v => v.id === selectedVersionId);

if (viewMode === 'code') {
```

## Impact
- ✅ Build now succeeds
- ✅ Generate tab can access project/version metadata
- ✅ No functional changes, just scope fix
- ✅ All view modes (code, generate, mermaid) work correctly

## Verification

### Compilation Status
- ✅ No TypeScript errors
- ✅ Only pre-existing warnings remain
- ✅ Build completes successfully
- ✅ All functionality intact

### Affected Views
- ✅ Code view - Still works (variables in scope)
- ✅ Generate view - Now works (variables in scope)
- ✅ Mermaid view - Unaffected (doesn't use these variables)

## Related Files
This fix works in conjunction with:
- `src/app/utils/python-dto.ts` - Python DTO generator
- State variables: `generatedCode`, `generateLanguage`, `generateCopied`

## Status
✅ **FIXED** - Build error resolved, Generate tab fully functional

---

**Date**: December 7, 2025
**Issue**: Scope/visibility error
**Fix**: Variable hoisting
**Status**: ✅ Complete

