# Studio Code View Async Fix

## Issue Summary

When switching to the code view in the Studio, an error occurred because `generateOpenApiSpec` was being called without `await`, even though it had been converted to an async function.

## Root Cause

The `generateOpenApiSpec` function was updated to be async (to support async template rendering), but there were multiple places in the Studio page where it was still being called synchronously:

1. **Line ~299**: In the `reloadClasses` function
2. **Line ~1619**: In the `loadClasses` useEffect  
3. **Line ~1752**: In the `regenerateSpec` useEffect (when switching to code view)

Since the function returns `Promise<string>` instead of `string`, calling it without `await` caused:
- The state to be set to a Promise object instead of the actual string
- The UI to display `[object Promise]` instead of the OpenAPI spec
- JSON parsing errors when trying to convert between JSON/YAML formats

## Solution

Added `await` to all three calls to `generateOpenApiSpec`:

### 1. In `reloadClasses` callback (line ~299)
```typescript
const spec = await generateOpenApiSpec(classesWithProperties, {
  projectName: currentProject?.name,
  version: currentVersion?.version_id
});
setOpenApiSpec(spec);
```

### 2. In `loadClasses` useEffect (line ~1619)
```typescript
const spec = await generateOpenApiSpec(classesWithProperties, {
  projectName: currentProject?.name,
  version: currentVersion?.version_id
});
setOpenApiSpec(spec);
```

### 3. In `regenerateSpec` useEffect (line ~1752)
```typescript
const spec = await generateOpenApiSpec(classesWithProperties, {
  projectName: currentProject?.name,
  version: currentVersion?.version_id
});
setOpenApiSpec(spec);
```

## Note on Other Generators

The following functions are **synchronous** and do NOT need `await`:
- `generateArazzoSpec()` - Generates Arazzo workflow specs
- `generateJsonSchema()` - Generates JSON Schema documents
- `generatePythonDTOs()` - Generates Python DTOs
- `generateTypeScriptDTOs()` - Generates TypeScript DTOs
- `generateJavaPojos()` - Generates Java POJOs
- `generateSQL()` - Generates SQL DDL
- `generateGraphQL()` - Generates GraphQL schemas
- `generateScala()` - Generates Scala case classes

Only `generateOpenApiSpec()` uses async template rendering and requires `await`.

## Testing

To verify the fix:
1. Open the Studio
2. Select a project and version with classes
3. Switch to the "Code" view tab
4. The OpenAPI/Arazzo/JSON Schema specs should display correctly
5. Toggle between JSON and YAML formats - both should work
6. Copy and Export buttons should function correctly

## Changes Made

**File:** `src/app/ade/studio/page.tsx`

1. Added `await` to `generateOpenApiSpec` call in `reloadClasses` function
2. Added `await` to `generateOpenApiSpec` call in `loadClasses` useEffect
3. Added `await` to `generateOpenApiSpec` call in `regenerateSpec` useEffect

## Related Files

- `src/app/ade/studio/page.tsx` - Main Studio page (fixed)
- `src/app/utils/openapi.ts` - OpenAPI generation utilities (async)
- `src/app/utils/template-loader.ts` - Template rendering (async)
- `src/app/utils/arazzo.ts` - Arazzo generation (sync)
- `src/app/utils/jsonschema.ts` - JSON Schema generation (sync)

## Date Fixed
December 11, 2024

