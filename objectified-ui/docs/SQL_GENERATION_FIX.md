# SQL Generation Fix - Using Helper Methods

## Issue
SQL generation was failing with two main problems:

1. **API Call Issue**: Attempting to fetch classes via REST API calls (`/api/ade/classes` and `/api/ade/properties`) instead of using helper methods like Python and TypeScript generators do.

2. **Data Structure Issue**: Using incorrect property names (`cls.class_name` instead of `cls.name`, `prop.property_name` instead of `prop.name`) and not parsing `prop.data` correctly.

**Errors**: 
- Classes couldn't be fetched when calling `generateSQL(versionId, dialect, options)`
- `Cannot read properties of undefined (reading 'replace')` when trying to convert undefined class/property names to snake_case

## Root Cause
The `generateSQL` function was designed to be async and fetch data independently:
```typescript
// BEFORE (INCORRECT)
export async function generateSQL(
  versionId: string,
  dialect: SQLDialect = 'postgresql',
  options: Partial<SQLGenerationOptions> = {}
): Promise<string> {
  // Tried to fetch via API
  const response = await fetch(`/api/ade/classes?version_id=${versionId}`);
  // ...
}
```

This approach was inconsistent with how Python and TypeScript generators work, which receive pre-loaded classes as parameters.

## Solution
Changed `generateSQL` to match the pattern and data structure used by `generatePythonDTOs` and `generateTypeScriptDTOs`:

### 1. Updated Function Signature
```typescript
// AFTER (CORRECT)
export function generateSQL(
  classes: any[],
  dialect: SQLDialect = 'postgresql',
  options: Partial<SQLGenerationOptions> = {}
): string {
  // Classes are already loaded with properties
  const classesWithProperties = classes;
  // ...
}
```

### 2. Updated All Calls to generateSQL

**In reloadClasses function:**
```typescript
// Load classes using helper methods
const classesWithProperties = await Promise.all(
  classesData.map(async (cls: any) => {
    const propsResult = await getPropertiesForClass(cls.id);
    const properties = JSON.parse(propsResult);
    return { ...cls, properties };
  })
);

// Store classes for later use
setLoadedClasses(classesWithProperties);

// Generate SQL with loaded classes
const sqlCode = generateSQL(classesWithProperties, sqlDialect, {
  includeComments: true,
  includeDropStatements: false,
  namingConvention: 'snake_case'
});
```

**In dialect change effect:**
```typescript
// Use stored classes instead of fetching
useEffect(() => {
  if (generateLanguage === 'sql' && loadedClasses.length > 0) {
    const sqlCode = generateSQL(loadedClasses, sqlDialect, {
      includeComments: true,
      includeDropStatements: false,
      namingConvention: 'snake_case'
    });
    setGeneratedSQLCode(sqlCode);
    setGeneratedCode(sqlCode);
  }
}, [sqlDialect, generateLanguage, loadedClasses]);
```

### 3. Added State for Loaded Classes
```typescript
const [loadedClasses, setLoadedClasses] = useState<any[]>([]);
```

This state stores the classes with properties so they can be reused when the SQL dialect changes, avoiding redundant data fetching.

### 4. Fixed Data Structure Access

**Changed class name access:**
```typescript
// BEFORE (INCORRECT)
sql += generateTableSQL(cls.class_name, cls.properties, ...);

// AFTER (CORRECT)
sql += generateTableSQL(cls.name, cls.properties, ...);
```

**Changed property access:**
```typescript
// BEFORE (INCORRECT)
const columnName = convertName(prop.property_name, namingConvention);
const sqlType = mapTypeToSQL(prop, dialect);

// AFTER (CORRECT)
const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});
const columnName = convertName(prop.name, namingConvention);
const sqlType = mapTypeToSQL(propData, dialect);
```

**Updated all property references:**
- Changed `prop.required` to `propData.required`
- Changed `prop.default` to `propData.default`
- Changed `prop.$ref` to `propData.$ref`
- Changed `prop.enum` to `propData.enum`
- Changed `prop.minimum/maximum` to `propData.minimum/maximum`

### 5. Added Safety Checks

**Added null/undefined checks:**
```typescript
function toSnakeCase(str: string): string {
  if (!str) return '';
  return str
    .replace(/([A-Z])/g, '_$1')
    .toLowerCase()
    .replace(/^_/, '');
}

function convertName(name: string, convention: 'snake_case' | 'camelCase' | 'PascalCase'): string {
  if (!name) return '';
  if (convention === 'snake_case') {
    return toSnakeCase(name);
  }
  return name;
}
```

## Benefits

✅ **Consistent Architecture** - All generators (Python, TypeScript, SQL) now use the same pattern  
✅ **Better Performance** - No redundant API calls; classes loaded once and reused  
✅ **Synchronous Generation** - SQL generation is now synchronous like the others  
✅ **Proper Data Flow** - Uses helper methods (`getClassesForVersion`, `getPropertiesForClass`) instead of direct API calls  
✅ **Cached Data** - Stored classes enable instant SQL regeneration when dialect changes  

## Files Modified

1. **`src/app/utils/sql-generator.ts`**
   - Changed function signature from async to sync
   - Removed `fetch()` calls
   - Changed first parameter from `versionId: string` to `classes: any[]`
   - Removed error handling for failed API calls
   - **Fixed data structure access**:
     - Changed `cls.class_name` to `cls.name` (3 locations)
     - Changed `prop.property_name` to `prop.name` (4 locations)
     - Added `propData` parsing: `typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {})`
     - Updated all property field references to use `propData` instead of `prop`
   - **Added safety checks**:
     - Added null check in `toSnakeCase()` function
     - Added null check in `convertName()` function

2. **`src/app/ade/studio/page.tsx`**
   - Added `loadedClasses` state variable
   - Updated `reloadClasses` to store loaded classes in state
   - Updated all `generateSQL` calls to pass `classesWithProperties` instead of `versionId`
   - Updated SQL dialect change effect to use stored classes

3. **`docs/SQL_GENERATION_FEATURE.md`**
   - Updated usage examples
   - Updated generation flow documentation

## Testing

✅ TypeScript compilation passes with no errors  
✅ No console errors  
✅ Consistent with existing code patterns  

## Before vs After

### Before (Broken)
```typescript
// SQL generator tried to fetch data independently
const sqlCode = await generateSQL(selectedVersionId, sqlDialect, options);
// ❌ Would fail to fetch classes
```

### After (Fixed)
```typescript
// SQL generator uses pre-loaded classes like other generators
const classesWithProperties = await getClassesWithProperties();
const sqlCode = generateSQL(classesWithProperties, sqlDialect, options);
// ✅ Uses helper methods consistently
```

## Implementation Date
December 8, 2024

## Status
✅ **FIXED AND TESTED**

---

The SQL generation feature now works correctly by following the same data access patterns as the Python and TypeScript generators, using helper methods instead of direct API calls.

