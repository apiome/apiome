# Version Bump Strategy Fix

## Problem
When creating a new version through "copy from" with the bump strategy set to "patch", the system was incorrectly bumping the **minor** version instead of the **patch** version.

**Example of the bug:**
- Latest version: `1.2.3`
- Selected strategy: Patch (should create `1.2.4`)
- **Actual result**: `1.3.0` (minor bump)
- **Expected result**: `1.2.4` (patch bump)

## Root Cause
The `createVersion` function in `lib/db/helper.ts` was hardcoded to always call `bumpMinorVersion()` when auto-generating version IDs, regardless of the user's selected bump strategy.

```typescript
// OLD CODE - Always bumps minor version
if (!finalVersionId || finalVersionId.trim().length === 0) {
  const latestVersion = await getLatestVersionForProject(projectId);
  finalVersionId = latestVersion ? bumpMinorVersion(latestVersion) : '0.1.0';
}
```

## Solution

### 1. Added `bumpPatchVersion` Function
Created a new helper function to bump the patch version:

```typescript
function bumpPatchVersion(version: string): string {
  const parsed = parseSemanticVersion(version);
  if (!parsed) return '0.1.0';

  return `${parsed.major}.${parsed.minor}.${parsed.patch + 1}`;
}
```

This mirrors the existing `bumpMinorVersion` function but increments the patch number instead.

### 2. Updated `createVersion` Function Signature
Added a `bumpStrategy` parameter to accept the user's choice:

```typescript
export async function createVersion(
  projectId: string, 
  creatorId: string, 
  versionId: string | null, 
  description: string, 
  changeLog: string, 
  sourceVersionId?: string | null, 
  bumpStrategy?: 'patch' | 'minor'  // NEW PARAMETER
)
```

### 3. Updated Version Bumping Logic
Modified the auto-generation logic to respect the bump strategy:

```typescript
// NEW CODE - Respects user's bump strategy
if (!finalVersionId || finalVersionId.trim().length === 0) {
  const latestVersion = await getLatestVersionForProject(projectId);
  if (latestVersion) {
    // Use the provided bump strategy, default to 'patch' if not specified
    finalVersionId = (bumpStrategy === 'minor') 
      ? bumpMinorVersion(latestVersion) 
      : bumpPatchVersion(latestVersion);
  } else {
    finalVersionId = '0.1.0';
  }
}
```

### 4. Updated UI to Pass Strategy
Modified the versions page to pass the `bumpStrategy` when calling `createVersion`:

```typescript
const result = await createVersion(
  selectedProjectId,
  currentUserId,
  autoGenerate ? null : versionId,
  description,
  changeLog,
  sourceVersionId || null,
  autoGenerate ? bumpStrategy : undefined  // Pass the user's selection
);
```

## Changes Made

### Files Modified:
1. **`lib/db/helper.ts`**
   - Added `bumpPatchVersion()` function
   - Updated `createVersion()` to accept `bumpStrategy` parameter
   - Modified version bumping logic to use the strategy

2. **`src/app/ade/dashboard/versions/page.tsx`**
   - Updated `createVersion` call to pass `bumpStrategy`

## Behavior After Fix

### Patch Strategy (Default)
- Latest: `1.2.3` → New: `1.2.4`
- Latest: `2.0.5` → New: `2.0.6`
- Latest: `0.1.0` → New: `0.1.1`

### Minor Strategy
- Latest: `1.2.3` → New: `1.3.0`
- Latest: `2.0.5` → New: `2.1.0`
- Latest: `0.1.0` → New: `0.2.0`

### First Version (No Latest)
- Regardless of strategy → New: `0.1.0`

## Testing Checklist

- [x] Patch strategy creates correct version (e.g., 1.2.3 → 1.2.4)
- [x] Minor strategy creates correct version (e.g., 1.2.3 → 1.3.0)
- [x] Default strategy is patch when not specified
- [x] Manual version entry still works (ignores strategy)
- [x] Copy from source version works with correct bumping
- [x] First version creation defaults to 0.1.0
- [x] No errors when creating versions

## Semantic Versioning Reference

**MAJOR.MINOR.PATCH** (e.g., 2.1.3)

- **MAJOR**: Incompatible API changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

The fix now correctly implements this standard when auto-generating versions.

