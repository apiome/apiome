# Deprecated Feature Implementation

## Overview

Added support for marking classes and properties as deprecated, with visual indicators on the canvas and optional deprecation messages.

## Features Implemented

### 1. Class-Level Deprecation

**UI Location:** ClassEditDialog → Design tab → Bottom of form

- ✅ **Deprecated Toggle**: Checkbox to mark entire class as deprecated
- ✅ **Deprecation Message**: Optional multiline text field for context
- ✅ **Visual Indicator**: Class name shows strikethrough text and "DEPRECATED" badge in canvas header
- ✅ **Schema Integration**: Deprecated flag and message stored in class schema

### 2. Property-Level Deprecation

**UI Location:** PropertyFormFields → Metadata section

- ✅ **Deprecated Toggle**: Checkbox to mark individual properties as deprecated
- ✅ **Deprecation Message**: Optional multiline text field (shows when deprecated is checked)
- ✅ **Visual Indicators**:
  - Property name shows strikethrough text
  - "DEP" badge displayed next to property name
  - Grayed out text color
  - Tooltip shows deprecation message on hover
- ✅ **Schema Integration**: Deprecated flag and message stored in property data

## Visual Design

### Class Header (Deprecated)
```
┌─────────────────────────────────────────┐
│ 🔵 OldClass [DEPRECATED]  🗑️           │  ← Strikethrough + Yellow badge
├─────────────────────────────────────────┤
```

### Property Row (Deprecated)
```
  ⌄ oldProperty : string  ✏️ 🗑️
    ^               
    |                      
 Strikethrough + Grayed color
```

## Badge Styling

### Class Deprecated Badge
- Background: `#fef3c7` (light yellow)
- Text: `#92400e` (dark brown)
- Border: `#fbbf24` (golden yellow)
- Text: "DEPRECATED"

### Property Deprecated Visual
- Strikethrough text decoration
- Gray text color: `#9ca3af`
- Tooltip: Shows deprecation message or "Deprecated"

## Database Schema

### Classes
The deprecated information is stored in the `schema` JSONB column:

```json
{
  "type": "object",
  "deprecated": true,
  "deprecationMessage": "Use NewClass instead. Will be removed in v2.0.",
  "properties": { ... }
}
```

### Properties
The deprecated information is stored in the `data` JSONB column:

```json
{
  "type": "string",
  "deprecated": true,
  "deprecationMessage": "Use newProperty instead.",
  "description": "..."
}
```

## OpenAPI Output

### Deprecated Class
```json
{
  "components": {
    "schemas": {
      "OldClass": {
        "type": "object",
        "deprecated": true,
        "deprecationMessage": "Use NewClass instead.",
        "properties": { ... }
      }
    }
  }
}
```

### Deprecated Property
```json
{
  "properties": {
    "oldField": {
      "type": "string",
      "deprecated": true,
      "deprecationMessage": "Use newField instead.",
      "description": "Legacy field"
    }
  }
}
```

## OpenAPI 3.1 Compliance

The `deprecated` field is part of the OpenAPI 3.1 specification:
- ✅ Boolean field indicating deprecation
- ✅ Standard across schemas, parameters, and operations
- ✅ Commonly used by code generators to mark deprecated APIs

Note: `deprecationMessage` is a custom extension field (not in OpenAPI spec) but is a common practice for providing additional context.

## Usage Guide

### Marking a Class as Deprecated

1. Double-click the class on the canvas
2. In the ClassEditDialog, scroll to the bottom
3. Check "Mark as Deprecated"
4. (Optional) Enter a deprecation message explaining:
   - Why it's deprecated
   - What to use instead
   - When it will be removed
5. Save the class

### Marking a Property as Deprecated

1. Click the edit (✏️) button on a property
2. In the property dialog, scroll to the Metadata section
3. Check "Deprecated"
4. (Optional) Enter a deprecation message
5. Save the property

### Visual Feedback

- **Canvas**: Immediately shows strikethrough text and badges
- **OpenAPI Export**: Includes deprecated flags in generated specs
- **Tooltips**: Hover over badges to see deprecation messages

## Files Modified

### UI Components
1. ✅ `src/app/components/ade/studio/ClassNode.tsx`
   - Added deprecated badge to class header
   - Added deprecated badge and styling to property rows

2. ✅ `src/app/components/ade/studio/ClassEditDialog.tsx`
   - Added deprecated and deprecationMessage to formData state
   - Added UI controls (checkbox + text field)
   - Updated schema building to include deprecated fields

3. ✅ `src/app/components/ade/studio/PropertyFormFields.tsx`
   - Added deprecationMessage to PropertyFormData interface
   - Added conditional deprecation message field in UI

### Schema Generation
4. ✅ `src/app/utils/openapi.ts`
   - No changes needed - deprecated fields automatically pass through

## Testing Checklist

### Class Deprecation
- [ ] Mark a class as deprecated
- [ ] Verify "DEPRECATED" badge shows in canvas header
- [ ] Verify class name has strikethrough
- [ ] Add deprecation message
- [ ] Hover over badge to see tooltip with message
- [ ] Export OpenAPI spec
- [ ] Verify deprecated flag appears in schema

### Property Deprecation
- [ ] Mark a property as deprecated
- [ ] Verify "DEP" badge shows next to property name
- [ ] Verify property name has strikethrough
- [ ] Verify text color is grayed out
- [ ] Add deprecation message
- [ ] Hover over badge to see tooltip with message
- [ ] Export OpenAPI spec
- [ ] Verify deprecated flag appears in property

### Edge Cases
- [ ] Class without deprecation message (should work)
- [ ] Property without deprecation message (should work)
- [ ] Toggle deprecated off - visual indicators removed
- [ ] Nested properties can be deprecated independently
- [ ] Works in read-only mode (indicators show, controls disabled)

## Best Practices

### When to Use Deprecation

1. **Breaking Changes**: When planning to remove or change API structure
2. **Migration Path**: Provide time for consumers to update
3. **Documentation**: Always include a deprecation message explaining alternatives

### Deprecation Message Guidelines

Good deprecation messages include:
- ✅ **Why**: Reason for deprecation
- ✅ **Alternative**: What to use instead
- ✅ **Timeline**: When it will be removed (if known)

Example:
```
Use NewUserClass instead. This class will be removed in version 3.0.
The new class includes additional validation and better performance.
```

## Future Enhancements

Potential improvements for future versions:

1. **Deprecation Date**: Add date field to track when deprecated
2. **Removal Version**: Specify target version for removal
3. **Filter**: Add canvas filter to show/hide deprecated items
4. **Report**: Generate deprecation report for all deprecated items
5. **Warnings**: Show warning dialog when using deprecated items
6. **Migration Tools**: Auto-suggest replacements

## Date Implemented

December 11, 2024

## Status

✅ **COMPLETE** - Deprecated feature fully implemented for both classes and properties with visual indicators and optional messages.

