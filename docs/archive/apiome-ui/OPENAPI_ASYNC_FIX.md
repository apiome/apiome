# OpenAPI Template System - Async/Await Fix

## Issue Summary

The error **"Unexpected token 'o', "[object Promise]" is not valid JSON"** occurred because the `renderTemplate` function was returning a Promise, but it wasn't being awaited in functions that called it.

## Root Cause

When `renderTemplate` was changed to be async (to properly support async operations), several calling functions were not updated to await the result. This meant they received `[object Promise]` instead of the rendered string, which caused JSON.parse() to fail.

## Changes Made

### 1. Fixed `generateOpenApiSpec` function
**File:** `src/app/utils/openapi.ts`

- Made the function `async`
- Changed return type from `string` to `Promise<string>`
- Added `await` to the `renderTemplate` call

```typescript
export async function generateOpenApiSpec(
  classes: any[],
  options?: { ... }
): Promise<string> {
  // ...
  const rendered = await renderTemplate(versionConfig.templateFile, templateData);
  return JSON.stringify(JSON.parse(rendered), null, 2);
}
```

### 2. Fixed `generateClassOpenApiSpec` function
**File:** `src/app/utils/openapi.ts`

- Made the function `async`
- Changed return type from `any` to `Promise<any>`
- Added `await` to the `renderTemplate` call

```typescript
export async function generateClassOpenApiSpec(
  classData: any,
  allClasses: any[],
  options?: { ... }
): Promise<any> {
  // ...
  const rendered = await renderTemplate(versionConfig.templateFile, templateData);
  return JSON.parse(rendered);
}
```

### 3. Updated test file
**File:** `tests/openapi-template-test.ts`

- Made test functions `async`
- Added `await` to all calls to `generateOpenApiSpec` and `generateClassOpenApiSpec`
- Wrapped the main test execution in an async IIFE
- Fixed import path to use Next.js path alias `@/app/utils/openapi`

## Verification

Created a verification script (`tests/verify-openapi-fix.mjs`) that confirms:
- ✅ Template renders successfully
- ✅ Result is a string, not a Promise
- ✅ Result is valid JSON
- ✅ All JSON structure is correct

## Impact

This fix ensures that:
1. OpenAPI specifications are generated correctly
2. No "[object Promise]" errors occur when parsing JSON
3. All async operations are properly awaited
4. Type signatures correctly reflect async behavior

## Testing

To verify the fix works:
```bash
node tests/verify-openapi-fix.mjs
```

Expected output:
```
✅ Template rendered successfully
✅ Result is a string, not a Promise
✅ Result is valid JSON
   - OpenAPI version: 3.1.0
   - API title: Test API
   - Schemas: Person

🎉 All checks passed! The fix is working correctly.
```

## Related Files

- `src/app/utils/openapi.ts` - Main OpenAPI generation functions
- `src/app/utils/template-loader.ts` - Template loading and rendering functions
- `src/app/utils/templates/openapi-spec.hbs` - Handlebars template for OpenAPI specs
- `tests/openapi-template-test.ts` - Test suite for OpenAPI generation
- `tests/verify-openapi-fix.mjs` - Verification script

## Date Fixed
December 11, 2025

