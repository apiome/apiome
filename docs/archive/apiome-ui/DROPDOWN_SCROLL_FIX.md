# Dropdown Menu Scrollable Container Fix

## Date: December 9, 2024

## Issue

The Actions dropdown menus in the Tenant Management page were being clipped by the scrollable container. The dropdown would appear cut off when the parent element had `overflow-y-auto` CSS property.

---

## Root Cause

**Original Implementation**:
```tsx
<div className="relative">
  <button>...</button>
  {open && (
    <div className="absolute right-0 mt-1 w-48 ...">
      {/* Dropdown content */}
    </div>
  )}
</div>
```

**Problem**: 
- Dropdown used `position: absolute` 
- Positioned relative to parent container
- Parent container had `max-h-[600px] overflow-y-auto`
- Absolute positioned elements are clipped by scrollable parents

---

## Solution

Changed dropdown positioning from `absolute` to `fixed` with dynamic coordinate calculation.

### Implementation

**1. Added State for Position**:
```typescript
const [dropdownPosition, setDropdownPosition] = useState<{ 
  top: number; 
  right: number 
} | null>(null);
```

**2. Calculate Position on Click**:
```typescript
<button
  onClick={(e) => {
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setDropdownPosition({
      top: rect.bottom + 4,  // 4px spacing below button
      right: window.innerWidth - rect.right  // distance from right viewport edge
    });
    setOpenDropdown(item.id);
  }}
>
  <MoreVertical className="w-4 h-4" />
</button>
```

**3. Apply Fixed Positioning**:
```tsx
{openDropdown === item.id && dropdownPosition && (
  <>
    <div className="fixed inset-0 z-10" onClick={() => setOpenDropdown(null)} />
    <div 
      className="fixed w-48 bg-gray-900 border border-gray-700 rounded-lg shadow-lg z-20"
      style={{
        top: `${dropdownPosition.top}px`,
        right: `${dropdownPosition.right}px`
      }}
    >
      {/* Dropdown content */}
    </div>
  </>
)}
```

---

## How It Works

### Position Calculation

1. **Get Button Coordinates**: 
   - `getBoundingClientRect()` returns button's position relative to viewport
   - Includes: `top`, `bottom`, `left`, `right`, `width`, `height`

2. **Calculate Top Position**:
   - Use `rect.bottom + 4` to position dropdown 4px below button
   - Always relative to viewport top

3. **Calculate Right Position**:
   - Use `window.innerWidth - rect.right` 
   - Calculates distance from right edge of viewport
   - Ensures dropdown aligns with button's right edge

4. **Apply with Fixed Positioning**:
   - `position: fixed` positions relative to viewport, not parent
   - Not affected by parent's `overflow` property
   - Always visible regardless of scroll position

### Visualization

```
Viewport
┌─────────────────────────────────────┐
│                                     │
│  Scrollable Container               │
│  ┌───────────────────────────┐     │
│  │ [Item 1]           [⋮]    │     │
│  │ [Item 2]           [⋮]    │     │
│  │ [Item 3]           [⋮] ───┼──┐  │
│  │                            │  │  │
│  │ (scroll here)              │  │  │
│  │                            │  │  │
│  └────────────────────────────┘  │  │
│                                  │  │
│         Dropdown Menu ───────────┘  │
│         ┌──────────────┐            │
│         │ Action 1     │  <- Fixed  │
│         │ Action 2     │     position
│         └──────────────┘            │
└─────────────────────────────────────┘
```

**Before (absolute)**: Dropdown clipped inside scrollable container
**After (fixed)**: Dropdown positioned relative to viewport, always visible

---

## Files Modified

### Tenant Management
**File**: `/src/app/admin/dashboard/tenants/TenantManagementClient.tsx`

**Changes**:
1. Added `useRef` import (though not ultimately needed)
2. Added `dropdownPosition` state
3. Updated tenant dropdown button to calculate position
4. Changed tenant dropdown from `absolute` to `fixed` with inline styles
5. Updated user dropdown button to calculate position  
6. Changed user dropdown from `absolute` to `fixed` with inline styles

---

## Benefits

✅ **No Clipping**: Dropdowns never cut off by scroll containers
✅ **Consistent Position**: Always appears in correct location
✅ **Viewport Aware**: Positioned relative to viewport, not parent
✅ **Scroll Independent**: Works regardless of scroll position
✅ **Better UX**: Users can always see full dropdown menu
✅ **Maintainable**: Clear, reusable pattern

---

## Testing

### Test Cases
- [x] Dropdown appears fully visible when triggered
- [x] Dropdown positioned correctly below button
- [x] Dropdown right-aligned with button
- [x] Works when scrolled to top of container
- [x] Works when scrolled to middle of container
- [x] Works when scrolled to bottom of container
- [x] Closes when clicking outside
- [x] Closes when clicking action
- [x] Multiple dropdowns don't conflict
- [x] Works on different screen sizes

### Verified In
- [x] Tenant list (scrollable area with `max-h-[600px]`)
- [x] User list within tenant (scrollable area with `max-h-[600px]`)

---

## Potential Improvements

### Future Enhancements
1. **Smart Positioning**: Check if dropdown would overflow viewport bottom, flip to show above button if needed
2. **Horizontal Overflow**: Check viewport width, adjust horizontal position if needed
3. **Animation**: Add smooth transition when opening
4. **Keyboard Navigation**: Support arrow keys to move between items
5. **Focus Management**: Auto-focus first item when opening

### Example Smart Positioning
```typescript
const calculatePosition = (rect: DOMRect, menuHeight: number) => {
  const spaceBelow = window.innerHeight - rect.bottom;
  const spaceAbove = rect.top;
  
  // Show above button if not enough space below
  const top = spaceBelow < menuHeight && spaceAbove > spaceBelow
    ? rect.top - menuHeight - 4  // Above button
    : rect.bottom + 4;            // Below button
    
  return { top, right: window.innerWidth - rect.right };
};
```

---

## New Feature: Edit Tenant

Added "Edit Tenant" action to the tenant actions dropdown menu (December 9, 2024).

**New Action**:
- **Edit Tenant** - Blue edit icon with "Edit Tenant" text
- Opens a dialog to rename tenant and update description/slug
- Positioned first in the dropdown menu for easy access

**Implementation**:
1. Added `showRenameDialog`, `renamingTenant`, and `renameData` state
2. Created `handleOpenRenameDialog()` to open dialog with current tenant data
3. Created `handleRenameTenant()` to submit changes via `updateTenant()`
4. Added "Edit Tenant" button to dropdown with Edit icon (blue color)
5. Created rename dialog similar to create dialog but with "Save Changes" button

**Tenant Actions Menu** (updated):
```
┌──────────────────────┐
│ ✏️  Edit Tenant      │  <- NEW
│ ⚡ Disable Tenant    │
│ 🗑️  Delete Tenant    │
└──────────────────────┘
```

---

## Related Issues

This same fix should be applied to any dropdown/popover that appears within scrollable containers:

- [x] Tenant management dropdowns - **FIXED**
- [x] Edit Tenant action - **ADDED**
- [ ] User management dropdowns - Consider if needed
- [ ] Any future dropdown implementations

---

## Summary

Successfully fixed the dropdown clipping issue by changing from `absolute` to `fixed` positioning with dynamic coordinate calculation. Dropdowns now always appear fully visible regardless of scroll position or parent container overflow settings.

**Status**: ✅ **FIXED AND TESTED**

The Actions dropdown menus in the Tenant Management page now work correctly in scrollable areas and are always fully visible to users.

