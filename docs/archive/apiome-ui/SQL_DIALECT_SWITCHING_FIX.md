# SQL Dialect Switching Fix

## Problem
SQL generation works correctly on initial load, but switching between SQL dialects (PostgreSQL, MySQL, SQL Server, Oracle, SQLite) does not regenerate the SQL with the new dialect.

## Root Cause
**React Effect Race Condition**: Two `useEffect` hooks were conflicting with each other:

1. **Language Change Effect** - Monitors `generateLanguage` and cached code variables (`generatedSQLCode`, `generatedPythonCode`, `generatedTypeScriptCode`)
2. **SQL Dialect Change Effect** - Monitors `sqlDialect` and regenerates SQL

### The Race Condition Flow:
1. User changes SQL dialect from PostgreSQL → MySQL
2. **Dialect Effect** fires:
   - Generates new SQL with MySQL dialect
   - Calls `setGeneratedSQLCode(newSQLCode)` 
   - Calls `setGeneratedCode(newSQLCode)`
3. **Language Effect** ALSO fires (because `generatedSQLCode` changed):
   - Sees `generateLanguage === 'sql'` 
   - Calls `setGeneratedCode(generatedSQLCode)`
   - BUT `generatedSQLCode` might still be the OLD value due to React's batched state updates
4. **Result**: Old SQL code overwrites the new SQL code in the editor

## Solution
Modified the language change effect to use a `useRef` to track the previous language and **only** switch code when the language actually changes (not when cached code updates):

```typescript
// BEFORE (BROKEN - Stale Closure Problem)
useEffect(() => {
  if (generateLanguage === 'typescript' && generatedTypeScriptCode) {
    setGeneratedCode(generatedTypeScriptCode);
  } else if (generateLanguage === 'sql' && generatedSQLCode) {
    setGeneratedCode(generatedSQLCode);
  } else if (generateLanguage === 'python' && generatedPythonCode) {
    setGeneratedCode(generatedPythonCode);
  }
}, [generateLanguage]);
//  ^^^^^^^^^^^^^^^^^^
// Problem: Effect closure has stale values of cached code variables
// When SQL dialect changes and updates generatedSQLCode, this effect doesn't re-run
// so it still has the OLD value in its closure

// AFTER (FIXED - Track Previous Language)
const previousLanguageRef = useRef(generateLanguage);

useEffect(() => {
  // Only switch code if language actually changed (not on cached code updates)
  if (previousLanguageRef.current !== generateLanguage) {
    console.log('Language changed from', previousLanguageRef.current, 'to', generateLanguage);
    
    if (generateLanguage === 'typescript' && generatedTypeScriptCode) {
      setGeneratedCode(generatedTypeScriptCode);
    } else if (generateLanguage === 'sql' && generatedSQLCode) {
      setGeneratedCode(generatedSQLCode);
    } else if (generateLanguage === 'python' && generatedPythonCode) {
      setGeneratedCode(generatedPythonCode);
    }
    
    previousLanguageRef.current = generateLanguage;
  }
}, [generateLanguage, generatedPythonCode, generatedTypeScriptCode, generatedSQLCode]);
// ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
// Now includes cached variables so closure stays fresh
// But uses previousLanguageRef to only run when language actually changes
```

### Why This Works

**The Stale Closure Problem**:
When we only depended on `[generateLanguage]`, the effect closure captured the cached code variables at mount time and never updated. So even when `generatedSQLCode` changed, the effect was still reading the OLD value from its closure.

**The Solution**:
1. Include cached variables in dependencies so the effect closure stays fresh with current values
2. Use a `useRef` to track the previous language value
3. Only execute the language switch logic when `previousLanguageRef.current !== generateLanguage`
4. Update the ref after switching

**Result**:
- **Dialect changes** → `generatedSQLCode` updates → Effect re-runs → But `previousLanguageRef.current === generateLanguage` (both still 'sql') → Does nothing ✅
- **Language changes** → `generateLanguage` updates → Effect re-runs → `previousLanguageRef.current !== generateLanguage` → Switches to new language → Updates ref ✅

## Flow After Fix

### When User Changes Dialect:
1. User changes dialect selector: PostgreSQL → MySQL
2. **SQL Dialect Effect** fires:
   ```typescript
   useEffect(() => {
     if (generateLanguage === 'sql' && loadedClasses.length > 0) {
       const sqlCode = generateSQL(loadedClasses, sqlDialect, { ... });
       setGeneratedSQLCode(sqlCode);  // Update cache with MySQL SQL
       setGeneratedCode(sqlCode);      // Update editor with MySQL SQL ✅
     }
   }, [sqlDialect, generateLanguage, loadedClasses]);
   ```
3. **Language Change Effect** also fires (because `generatedSQLCode` changed):
   ```typescript
   useEffect(() => {
     if (previousLanguageRef.current !== generateLanguage) {  // 'sql' !== 'sql' = false
       // This block does NOT execute ✅
     }
   }, [generateLanguage, generatedPythonCode, generatedTypeScriptCode, generatedSQLCode]);
   ```
4. Editor displays new SQL with MySQL dialect ✅

### When User Changes Language:
1. User changes language selector: SQL → Python
2. **Language Change Effect** fires:
   ```typescript
   useEffect(() => {
     if (previousLanguageRef.current !== generateLanguage) {  // 'sql' !== 'python' = true
       if (generateLanguage === 'python' && generatedPythonCode) {
         setGeneratedCode(generatedPythonCode);  // Switch to Python ✅
       }
       previousLanguageRef.current = generateLanguage;  // Update ref to 'python'
     }
   }, [generateLanguage, generatedPythonCode, generatedTypeScriptCode, generatedSQLCode]);
   ```
3. Editor displays Python code ✅

## Files Modified

**`src/app/ade/studio/page.tsx`**
- Line ~1718-1738: Modified language change effect
- Added `previousLanguageRef` using `useRef` to track the previous language
- Added condition to only switch code when `previousLanguageRef.current !== generateLanguage`
- Re-added `generatedPythonCode`, `generatedTypeScriptCode`, `generatedSQLCode` to dependencies to prevent stale closures
- Updates ref after switching languages
- Line ~1740-1752: SQL dialect effect remains unchanged (regenerates SQL when dialect changes)

## Testing Checklist

✅ SQL generation works on initial load
✅ Switching SQL dialects regenerates SQL correctly
✅ PostgreSQL → MySQL shows MySQL-specific syntax
✅ MySQL → SQL Server shows SQL Server-specific syntax
✅ Switching back to previous dialect works correctly
✅ Switching to Python/TypeScript still works
✅ Switching back to SQL from Python/TypeScript shows latest SQL dialect
✅ No race conditions or flashing/flickering in editor
✅ TypeScript compilation passes

## Technical Notes

### Stale Closures in React Effects
When an effect doesn't include a state variable in its dependencies, the effect closure captures the value at creation time and never updates. This is called a "stale closure":

```typescript
// BAD - Stale closure
const [count, setCount] = useState(0);
useEffect(() => {
  console.log(count); // Always logs 0, even as count changes
}, []); // Empty dependencies = closure never updates

// GOOD - Fresh closure
useEffect(() => {
  console.log(count); // Always logs current value
}, [count]); // Effect closure updates when count changes
```

### Using useRef to Prevent Unnecessary Updates
`useRef` provides a way to store values that persist across renders without triggering re-renders:
- Updating a ref (`ref.current = newValue`) does NOT cause re-renders
- Perfect for tracking "previous" values to detect actual changes
- Common pattern: Track previous prop/state to only act on real changes

### React State Updates are Batched
React batches multiple `setState` calls together for performance:
```typescript
setGeneratedSQLCode(newSQL);  // Queued
setGeneratedCode(newSQL);      // Queued
// Both execute together, THEN effects run
```

### Effect Dependency Best Practices
- Include ALL variables that the effect reads to avoid stale closures
- Use `useRef` to store values that shouldn't trigger the effect
- Use conditional logic inside the effect to control when it executes

---

**Date**: December 8, 2024  
**Status**: ✅ FIXED

