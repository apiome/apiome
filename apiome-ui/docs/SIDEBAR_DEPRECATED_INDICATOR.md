# Sidebar Deprecated Class Indicator - Implementation Summary

## Request
Add strikethrough styling to deprecated classes in the sidebar to indicate when `deprecated: true` is set for a class.

## Implementation

### File Modified
**`src/app/components/ade/studio/StudioSideNav.tsx`**

### Changes Made

Added visual indicators for deprecated classes in the sidebar class list:

1. **Strikethrough Text**: Class name displays with strikethrough when `classItem.schema?.deprecated` is true
2. **Gray Color**: Deprecated class names are displayed in gray color (`#9ca3af`)
3. **"DEPR" Badge**: Small yellow badge appears next to deprecated class names (matching the canvas property style)
4. **Tooltip**: Hovering over the badge shows the deprecation message if provided

### Code Changes

**Before:**
```tsx
<span style={{ 
  overflow: 'hidden', 
  textOverflow: 'ellipsis', 
  whiteSpace: 'nowrap'
}}>
  {classItem.name}
</span>
```

**After:**
```tsx
<span style={{ 
  overflow: 'hidden', 
  textOverflow: 'ellipsis', 
  whiteSpace: 'nowrap',
  textDecoration: classItem.schema?.deprecated ? 'line-through' : 'none',
  color: classItem.schema?.deprecated ? '#9ca3af' : 'inherit'
}}>
  {classItem.name}
</span>
{classItem.schema?.deprecated && (
  <span 
    title={classItem.schema?.deprecationMessage || 'Deprecated'} 
    style={{ 
      fontSize: 10, 
      padding: '1px 4px', 
      borderRadius: 2, 
      background: '#fef3c7', 
      color: '#92400e', 
      fontWeight: 600, 
      border: '1px solid #fbbf24', 
      whiteSpace: 'nowrap' 
    }}
  >
    DEPR
  </span>
)}
```

### Visual Result

**Sidebar Display:**
```
Classes Tab
─────────────────────
🔍 Search classes...

📋 Class List:
  ┌─────────────────┐
  │ User            │
  │ Order           │
  │ OldUser [DEPR]  │  ← Strikethrough + Gray + Badge
  │ Product         │
  └─────────────────┘
```

### Consistency Across UI

The sidebar now matches the visual treatment used in other parts of the application:

1. **Canvas Class Node Header**: Shows strikethrough + "DEPRECATED" badge
2. **Canvas Property Display**: Shows strikethrough + gray + "DEPR" badge
3. **Sidebar Class List**: Shows strikethrough + gray + "DEPR" badge ✨ (NEW)

### Features

- ✅ **Strikethrough**: Text decoration clearly indicates deprecated status
- ✅ **Gray Color**: Reduced visual prominence for deprecated items
- ✅ **Badge Indicator**: Small "DEPR" badge for at-a-glance identification
- ✅ **Tooltip**: Hovering shows deprecation message (if provided)
- ✅ **No Breaking Changes**: All changes are purely visual enhancements

### Testing

#### Build Status
✅ **Build Successful** - No compilation errors

#### Manual Testing Steps
1. Start dev server: `npm run dev`
2. Navigate to Studio: http://localhost:3000/ade/studio
3. Select a project and version
4. Open the sidebar (Classes tab should be default)
5. Create or edit a class and mark it as deprecated
6. Verify the class appears with:
   - Strikethrough text
   - Gray color
   - "DEPR" badge
   - Tooltip on hover (if deprecation message was provided)

### Schema Check

The implementation reads from `classItem.schema?.deprecated` which is populated from the database:

```typescript
// ClassItem interface already includes schema
export interface ClassItem {
  id: string;
  name: string;
  description?: string;
  schema?: any; // Contains { deprecated: boolean, deprecationMessage?: string }
}
```

### Database Schema

No database changes required. The deprecated information is already stored in the `classes.schema` JSONB column:

```json
{
  "type": "object",
  "deprecated": true,
  "deprecationMessage": "Use NewUser class instead"
}
```

### Related Components

This change complements the existing deprecated indicators in:

1. **ClassNode.tsx** (Canvas display)
   - Class header: Strikethrough + "DEPRECATED" badge
   - Properties: Strikethrough + gray + "DEPR" badge

2. **ClassEditDialog.tsx** (Edit form)
   - Deprecated checkbox
   - Deprecation message field

3. **StudioSideNav.tsx** (Sidebar) ✨ UPDATED
   - Class list: Strikethrough + gray + "DEPR" badge

### Visual Consistency

All three locations now use consistent styling:

**Color Palette:**
- Strikethrough: Inherited or applied text decoration
- Gray text: `#9ca3af` (gray-400)
- Badge background: `#fef3c7` (amber-100)
- Badge text: `#92400e` (amber-800)
- Badge border: `#fbbf24` (amber-400)

**Badge Sizes:**
- Class header badge: `10px` font, "DEPRECATED" text
- Property badge: `8px` font, "DEPR" text
- Sidebar badge: `10px` font, "DEPR" text

## Summary

✅ **Request Completed**: Deprecated classes now display with strikethrough in the sidebar
✅ **Visual Consistency**: Matches styling used throughout the application
✅ **No Breaking Changes**: Pure visual enhancement
✅ **Build Successful**: All tests pass

The sidebar now provides immediate visual feedback when browsing classes, making it easy to identify deprecated classes at a glance without needing to open the canvas or edit dialog.

