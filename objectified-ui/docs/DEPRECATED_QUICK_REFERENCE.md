# Deprecated Feature - Quick Reference

## Visual Indicators

### Class (Deprecated)
```
[OldClass] with [DEPRECATED] badge
└─ Strikethrough text
└─ Yellow badge in header
└─ Tooltip shows message
```

### Property (Deprecated)
```
oldProperty (strikethrough)
└─ Strikethrough text
└─ Gray color (#9ca3af)
└─ Tooltip shows message
```

## UI Locations

| What | Where | Control |
|------|-------|---------|
| **Class** | Double-click class → Design tab → Bottom | Checkbox + Message field |
| **Property** | Click edit (✏️) → Metadata section | Checkbox + Message field |

## Badge Colors

| Element | Background | Text | Border |
|---------|------------|------|--------|
| Class Badge | `#fef3c7` | `#92400e` | `#fbbf24` |
| Property Visual | Strikethrough + Gray (`#9ca3af`) | - | - |

## Data Structure

### Class Schema
```json
{
  "type": "object",
  "deprecated": true,
  "deprecationMessage": "Optional message here"
}
```

### Property Data
```json
{
  "type": "string",
  "deprecated": true,
  "deprecationMessage": "Optional message here"
}
```

## Quick Actions

### Mark Class as Deprecated
1. Double-click class
2. Scroll to bottom
3. Check "Mark as Deprecated"
4. Add message (optional)
5. Save

### Mark Property as Deprecated
1. Click edit (✏️)
2. Find "Metadata" section
3. Check "Deprecated"
4. Add message (optional)
5. Save

## OpenAPI Output

```json
{
  "deprecated": true,
  "deprecationMessage": "Use XYZ instead. Removed in v2.0."
}
```

## Best Practice Message Template

```
Use [NEW_ITEM] instead. [OLD_ITEM] will be removed in version [X.Y].
[Additional context about why/how to migrate]
```

## Files Modified

- `ClassNode.tsx` - Visual display
- `ClassEditDialog.tsx` - Class UI controls
- `PropertyFormFields.tsx` - Property UI controls

## Status

✅ Complete and Production Ready

## Date

December 11, 2024

