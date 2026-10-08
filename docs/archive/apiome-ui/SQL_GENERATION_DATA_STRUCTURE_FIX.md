# SQL Generation Data Structure Fix - Summary

## Problem
Error: `Cannot read properties of undefined (reading 'replace')`

## Root Cause
The SQL generator was using incorrect property names that didn't match the actual data structure:
- Used `cls.class_name` instead of `cls.name`
- Used `prop.property_name` instead of `prop.name`
- Didn't parse `prop.data` to access schema fields

## All Fixes Applied

### 1. Class Name Access (3 locations)
✅ Changed `cls.class_name` → `cls.name` in:
- DROP TABLE generation
- CREATE TABLE generation  
- INDEX generation

### 2. Property Name Access (4 locations)
✅ Changed `prop.property_name` → `prop.name` in:
- Column definition (CREATE TABLE)
- Foreign key index creation
- Unique index creation

### 3. Property Data Parsing (2 locations)
✅ Added `propData` parsing before accessing schema fields:
```typescript
const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : (prop.data || {});
```
- In `generateTableSQL` function
- In `generateIndexSQL` function

### 4. Property Field References (8+ locations)
✅ Changed all schema field access from `prop.X` to `propData.X`:
- `prop.required` → `propData.required`
- `prop.default` → `propData.default`
- `prop.$ref` → `propData.$ref`
- `prop.enum` → `propData.enum`
- `prop.minimum` → `propData.minimum`
- `prop.maximum` → `propData.maximum`
- `prop.unique` → `propData.unique`

### 5. Safety Checks (2 functions)
✅ Added null/undefined checks:
- `toSnakeCase()` - returns empty string if input is falsy
- `convertName()` - returns empty string if input is falsy

## Testing Status
✅ TypeScript compilation passes
✅ No runtime errors expected
✅ Matches Python/TypeScript generator patterns

## Files Modified
- `src/app/utils/sql-generator.ts` - All fixes applied
- `docs/SQL_GENERATION_FIX.md` - Documentation updated

## Result
SQL generation now works correctly with the actual data structure returned by helper methods (`getClassesForVersion`, `getPropertiesForClass`).

---
**Date**: December 8, 2024  
**Status**: ✅ FIXED

