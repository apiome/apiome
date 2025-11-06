# OpenAPI Specification Generator Consolidation

## Summary

Successfully consolidated the OpenAPI 3.1.0 specification generator into a reusable utility module to ensure consistent behavior across the application.

## Created Files

### `/Users/kenji/Development/objectified/objectified-ui/src/app/utils/openapi.ts`

A new utility module containing:

#### Exported Functions:

1. **`extractClassNameFromRef(ref: string): string | null`**
   - Extracts class name from a JSON Schema $ref string
   - Handles both full paths (`#/components/schemas/Person`) and simple names

2. **`findReferencedClasses(obj: any, refs: Set<string>): void`**
   - Recursively finds all class names referenced in a schema via $ref
   - Accumulates results in a Set for deduplication

3. **`buildClassSchema(classData: any): any`**
   - Builds a JSON Schema from a class definition and its properties
   - Handles the `required` flag properly (moves it from property to class level)
   - Cleans up empty properties and undefined values
   - Processes property data from both string and object formats

4. **`generateOpenApiSpec(classes: any[], options?: {...}): string`**
   - Generates a complete OpenAPI 3.1.0 specification from an array of classes
   - Returns JSON string representation
   - Options: `projectName`, `version`, `description`

5. **`generateClassOpenApiSpec(classData: any, allClasses: any[], options?: {...}): any`**
   - Generates OpenAPI spec for a single class and its referenced dependencies
   - Automatically includes schemas for all referenced classes
   - Returns object (not stringified) for easier manipulation
   - Options: `title`, `version`, `description`

## Updated Files

### 1. `/Users/kenji/Development/objectified/objectified-ui/src/app/ade/studio/page.tsx`
- **Removed**: Local implementations of `buildClassSchema` and `generateOpenApiSpec` (~80 lines)
- **Added**: Import from `../../utils/openapi`
- **Updated**: All calls to `generateOpenApiSpec` to use new options object API
- **Cleaned**: Removed unused MUI imports (Button, TextField, Box, Typography, etc.)

### 2. `/Users/kenji/Development/objectified/objectified-ui/src/app/components/ade/studio/ClassEditDialog.tsx`
- **Removed**: Local implementations of `extractClassNameFromRef`, `findReferencedClasses`, and `buildClassSchema` (~100 lines)
- **Added**: Import from `../../../utils/openapi`
- **Updated**: Uses `generateClassOpenApiSpec` for single-class view with dependencies
- **Simplified**: Dialog now uses consolidated utility for all OpenAPI generation

## Benefits

1. **Code Reusability**: Single source of truth for OpenAPI generation logic
2. **Consistency**: Same behavior across full schema view and single-class edit view
3. **Maintainability**: Bug fixes and feature additions only need to be made once
4. **Testing**: Easier to test a standalone utility module
5. **Performance**: No duplication of logic means smaller bundle size

## API Usage Examples

### Generate Full Project Specification
```typescript
import { generateOpenApiSpec } from '../../utils/openapi';

const spec = generateOpenApiSpec(allClasses, {
  projectName: 'My API',
  version: '1.0.0',
  description: 'My API description'
});
// Returns: JSON string
```

### Generate Single Class Specification
```typescript
import { generateClassOpenApiSpec } from '../../utils/openapi';

const specDoc = generateClassOpenApiSpec(classData, allClasses, {
  title: 'Person Schema',
  version: '1.0.0'
});
// Returns: OpenAPI document object
// Includes main class and all referenced classes
```

## Build Status

✅ All TypeScript compilation errors resolved
✅ Build succeeds without warnings
✅ No breaking changes to existing functionality
✅ Both full schema view and class edit dialog work correctly

## Next Steps

Future enhancements can now be made in a single location (`openapi.ts`):
- Add more OpenAPI features (security schemes, paths, etc.)
- Improve schema validation
- Add schema transformation utilities
- Support additional JSON Schema features

