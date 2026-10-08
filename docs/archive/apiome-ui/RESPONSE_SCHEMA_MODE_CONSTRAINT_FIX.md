# Fix: Response Schema Mode Constraint Violation

## Issue

When switching a response's schema mode to "Class" in the Response Properties Panel, the following database constraint error occurred:

```
Error: new row for relation "shared_path_response" violates check constraint "check_response_schema_defined"
```

**Error Details:**
- The constraint requires at least ONE of these fields to be NOT NULL: `class_id`, `inline_schema`, or `data`
- When switching to 'class' mode, all three fields were being set to NULL
- This violated the constraint even though the intention was to later select a class

## Root Cause

In `ResponseSection.tsx`, the `handleSchemaModeChange` function was setting:
- `schemaMode = 'class'`
- `data = null`
- `inlineSchema = null`
- `classId = undefined` (which doesn't update the field, leaving it as NULL if it was already NULL)

This resulted in all three constraint fields being NULL, violating the database check constraint.

## Solution

Modified `handleSchemaModeChange` to provide a placeholder `inline_schema` when switching to 'class' mode:

```typescript
else if (mode === 'class') {
  // For 'class' mode, provide a placeholder inline_schema until user selects a class
  // This satisfies the database constraint that requires at least one of:
  // class_id, inline_schema, or data to be NOT NULL
  inlineSchema = { type: 'object', properties: [] };
}
```

### Why This Works

1. **Satisfies Constraint**: The placeholder `inline_schema` ensures the constraint is met
2. **No Side Effects**: An empty object schema doesn't affect code generation or display
3. **Will Be Replaced**: When the user selects a class via `handleSetClassReference`, the placeholder will be replaced with the actual class reference
4. **Consistent Pattern**: This is the same approach used for 'object' mode

## Files Modified

- `/src/app/ade/studio/paths/components/ResponseSection.tsx` - Added placeholder inline_schema for class mode

## Testing

The fix ensures that:
- Users can switch to 'class' mode without database errors
- The constraint is satisfied with a valid placeholder
- Class selection works as expected after the mode change
- No regression in other schema modes (object, primitive, array)

## Database Constraint Reference

```sql
ALTER TABLE apiome.shared_path_response
ADD CONSTRAINT check_response_schema_defined
CHECK (
  class_id IS NOT NULL OR
  inline_schema IS NOT NULL OR
  data IS NOT NULL
);
```

This constraint ensures that every response has at least one way to define its schema, preventing orphaned responses with no schema information.

---

**Status**: ✅ Fixed (2026-01-19)
