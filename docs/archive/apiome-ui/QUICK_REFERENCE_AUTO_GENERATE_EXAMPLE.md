# Quick Reference: Auto-Generate Example Button

## Location
**Properties Form → Example Field → Upper Right Corner**

## Icon
**✨ Magic Wand (AutoAwesome)** - Blue colored

## Tooltip
**"Generate example based on property schema"**

## What It Does
Automatically generates a JSON example value based on:
- Property type (string, number, integer, boolean, object, array)
- Property format (email, date, uuid, etc.)
- Constraints (min, max, pattern, enum)
- Nested properties (for objects)

## Quick Examples

### Before Click
```
[Empty field or existing content]
```

### After Click (String with email format)
```json
"user@example.com"
```

### After Click (Object with nested properties)
```json
{
  "firstName": "example",
  "lastName": "example",
  "age": 0
}
```

### After Click (Integer with constraints: min=10, max=100)
```json
10
```

## Usage
1. Click the ✨ button
2. Example generates automatically
3. Edit if needed
4. Click again to regenerate

## Smart Features
- Uses enum values when available
- Respects min/max constraints
- Handles exclusive boundaries
- Generates format-specific values
- Builds nested object structures
- Wraps in arrays when needed

## File Modified
`/src/app/components/ade/studio/PropertyFormFields.tsx`

## Status
✅ Fully implemented and ready to use

