# Import Path Fix - December 6, 2024

> **⚠️ NOTE**: This fix was part of an initial implementation that was later refactored.  
> See [CLASS_EDIT_REFACTOR.md](./CLASS_EDIT_REFACTOR.md) for the final implementation.

## Issue
Module resolution error when importing `updateClass` from `@/lib/db/helper`:
```
Module not found: Can't resolve '@/lib/db/helper'
```

## Root Cause
The `@/` alias in Next.js resolves to the `src/` directory, but the `lib/` folder is located at the project root level, not inside `src/`. Therefore, `@/lib/db/helper` was trying to resolve to `src/lib/db/helper` which doesn't exist.

## File Structure
```
apiome-ui/
├── src/
│   └── app/
│       └── components/
│           └── ade/
│               └── studio/
│                   └── ClassEditDialog.tsx
└── lib/
    └── db/
        └── helper.ts
```

## Solution
Changed the import in `ClassEditDialog.tsx` from:
```typescript
import { updateClass } from '@/lib/db/helper';
```

To relative path:
```typescript
import { updateClass } from '../../../../../lib/db/helper';
```

## Path Calculation
From `src/app/components/ade/studio/ClassEditDialog.tsx`:
- `../` → `src/app/components/ade/`
- `../../` → `src/app/components/`
- `../../../` → `src/app/`
- `../../../../` → `src/`
- `../../../../../` → project root
- `../../../../../lib/db/helper` → `lib/db/helper.ts` ✓

## Verification
This matches the import pattern used in other files:
- `ClassPropertyEditDialog.tsx`: `import { updateClassProperty } from '../../../../../lib/db/helper';`
- `layout.tsx`: `import { ..., updateClass, ... } from '../../../../lib/db/helper';`

## Status
✅ **RESOLVED** - Module can now be resolved correctly and the build completes without errors.

