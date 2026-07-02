# Deprecated Feature - Quick Reference

## What Was Done

The deprecated feature was **already fully implemented** in the codebase. I've:
1. ✅ Verified the implementation at both class and property levels
2. ✅ Enhanced the property-level visual indicator by adding a "DEPR" badge
3. ✅ Created comprehensive documentation

## What's Available

### Class Level
- ✅ Deprecated checkbox in Class Edit Dialog
- ✅ Optional deprecation message field
- ✅ Visual indicators: strikethrough + "DEPRECATED" badge
- ✅ Stored in database (classes.schema JSONB)
- ✅ Exported to OpenAPI JSON/YAML

### Property Level  
- ✅ Deprecated checkbox in Property Form Fields
- ✅ Optional deprecation message field
- ✅ Visual indicators: strikethrough + gray text + "DEPR" badge (enhanced)
- ✅ Stored in database (class_properties.data JSONB)
- ✅ Exported to OpenAPI JSON/YAML

## How to Use

### Mark a Class as Deprecated
1. Double-click a class node on the canvas
2. Scroll to the yellow "Deprecated" section
3. Check "Mark as Deprecated"
4. (Optional) Add a deprecation message
5. Click "Save"

### Mark a Property as Deprecated
1. Click the edit icon (pencil) on a property
2. In the "Metadata Fields" section, check "Deprecated"
3. (Optional) Add a deprecation message
4. Click "Save"

## Visual Indicators

### Class Node (Deprecated)
```
┌─────────────────────────┐
│ OldClass [DEPRECATED]   │  ← Strikethrough + Yellow Badge
├─────────────────────────┤
│ Description text here   │
├─────────────────────────┤
│ * id: string            │
│ * name: string          │
└─────────────────────────┘
```

### Property (Deprecated)
```
┌─────────────────────────┐
│ User                    │
├─────────────────────────┤
│ * id: string            │
│ old_email [DEPR]: string│  ← Strikethrough + Gray + Badge
│ email: string           │
└─────────────────────────┘
```

## Database Schema

### Classes
```sql
-- Stored in classes.schema (JSONB)
{
  "type": "object",
  "deprecated": true,
  "deprecationMessage": "Use NewClass instead"
}
```

### Properties
```sql
-- Stored in class_properties.data (JSONB)
{
  "type": "string",
  "deprecated": true,
  "deprecationMessage": "Use newProp instead"
}
```

## OpenAPI Output

### Deprecated Class
```yaml
components:
  schemas:
    OldUser:
      type: object
      deprecated: true
      deprecationMessage: "Use User instead. Removal in v2.0"
      properties:
        id:
          type: string
```

### Deprecated Property
```yaml
components:
  schemas:
    User:
      type: object
      properties:
        old_email:
          type: string
          deprecated: true
          deprecationMessage: "Use email instead"
        email:
          type: string
          format: email
```

## Changes Made

### File Modified
- `src/app/components/ade/studio/ClassNode.tsx`
  - Added "DEPR" badge for deprecated properties (enhancement)
  - Badge appears next to property name with yellow background

### Files Created
- `docs/DEPRECATED_FEATURE.md` - Comprehensive documentation
- `docs/DEPRECATED_FEATURE_QUICK_REFERENCE.md` - This quick reference

### Implementation Details
The deprecated feature was already implemented with:
- Form controls in ClassEditDialog.tsx
- Form controls in PropertyFormFields.tsx  
- Visual indicators in ClassNode.tsx
- Schema building in both dialogs
- Database storage in JSONB columns
- OpenAPI export support

The only enhancement was adding the "DEPR" badge to properties for visual consistency with the class-level "DEPRECATED" badge.

## Testing

To test the feature:

1. **Start the development server**:
   ```bash
   cd /Users/kenji/Development/apiome/apiome-ui
   npm run dev
   ```

2. **Navigate to the Studio**:
   - Go to http://localhost:3000/ade/studio
   - Open or create a project

3. **Test Class Deprecation**:
   - Create a new class or edit existing one
   - Check the "Mark as Deprecated" checkbox
   - Add a message (optional)
   - Save and verify visual indicators

4. **Test Property Deprecation**:
   - Add or edit a property in a class
   - Check the "Deprecated" checkbox
   - Add a message (optional)
   - Save and verify visual indicators

5. **Export and Verify**:
   - Export the schema to JSON/YAML
   - Verify "deprecated" and "deprecationMessage" fields are present

## Summary

The deprecated feature you requested is **already fully implemented** in the codebase! Both class and property levels support:
- ✅ Deprecated toggle (checkbox)
- ✅ Optional deprecation message field
- ✅ Visual indicators on canvas (strikethrough + badges)
- ✅ OpenAPI 3.1 compliance
- ✅ Database persistence

The only addition made was enhancing the property-level visual indicator with a "DEPR" badge to match the class-level "DEPRECATED" badge for better visual consistency.

