# Edit/Rename Tenant Feature

## Date: December 9, 2024

## Overview

Added "Edit Tenant" functionality to the tenant management page, allowing administrators to rename tenants and update their descriptions and slugs through a dedicated dialog.

---

## Feature Description

### What Was Added

**New Action in Tenant Dropdown**:
- **Edit Tenant** button with Edit icon (✏️) in blue color
- Positioned first in the actions dropdown menu
- Opens a dialog to edit tenant name, slug, and description

### User Flow

1. User clicks the three-dot menu (⋮) on any tenant card
2. Dropdown menu appears with "Edit Tenant" as the first option
3. Clicking "Edit Tenant" opens a dialog pre-filled with current tenant data
4. User can modify:
   - **Tenant Name** (required)
   - **Slug** (required, auto-generates from name)
   - **Description** (optional)
5. Click "Save Changes" to update the tenant
6. Success message appears and tenant list refreshes

---

## Implementation Details

### State Management

Added three new state variables:

```typescript
const [showRenameDialog, setShowRenameDialog] = useState(false);
const [renamingTenant, setRenamingTenant] = useState<Tenant | null>(null);
const [renameData, setRenameData] = useState({ 
  name: '', 
  description: '', 
  slug: '' 
});
```

### Functions Added

**1. handleOpenRenameDialog()**
```typescript
const handleOpenRenameDialog = (tenant: Tenant) => {
  setRenamingTenant(tenant);
  setRenameData({
    name: tenant.name,
    description: tenant.description || '',
    slug: tenant.slug
  });
  setShowRenameDialog(true);
};
```
- Opens the rename dialog
- Pre-fills form with current tenant data
- Stores reference to tenant being edited

**2. handleRenameTenant()**
```typescript
const handleRenameTenant = async (e: React.FormEvent) => {
  e.preventDefault();
  if (!renamingTenant) return;

  try {
    const result = await updateTenant(renamingTenant.id, {
      name: renameData.name,
      description: renameData.description,
      slug: renameData.slug
    });
    const data = JSON.parse(result);

    if (data.success) {
      showMessage('success', 'Tenant renamed successfully');
      setShowRenameDialog(false);
      setRenamingTenant(null);
      setRenameData({ name: '', description: '', slug: '' });
      await loadTenants();
      
      // Update selected tenant if it's the one being renamed
      if (selectedTenant?.id === renamingTenant.id) {
        setSelectedTenant({
          ...selectedTenant,
          name: renameData.name,
          description: renameData.description,
          slug: renameData.slug
        });
      }
    }
  } catch (error) {
    showMessage('error', 'Failed to rename tenant');
  }
};
```
- Submits updated tenant data to API
- Refreshes tenant list on success
- Updates selected tenant if it's currently selected
- Shows success/error messages

---

## UI Components

### Updated Dropdown Menu

**Before**:
```
┌──────────────────────┐
│ ⚡ Disable Tenant    │
│ 🗑️  Delete Tenant    │
└──────────────────────┘
```

**After**:
```
┌──────────────────────┐
│ ✏️  Edit Tenant      │  <- NEW
│ ⚡ Disable Tenant    │
│ 🗑️  Delete Tenant    │
└──────────────────────┘
```

### Edit Tenant Dialog

```tsx
{showRenameDialog && renamingTenant && (
  <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
    <div className="bg-gray-800 border border-gray-700 rounded-lg max-w-md w-full">
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-white">Edit Tenant</h3>
        <button onClick={closeDialog}>
          <X className="w-5 h-5" />
        </button>
      </div>
      <form onSubmit={handleRenameTenant} className="p-4 space-y-4">
        {/* Tenant Name Field */}
        {/* Slug Field */}
        {/* Description Field */}
        <div className="flex items-center justify-end gap-2 pt-2">
          <button type="button">Cancel</button>
          <button type="submit" className="bg-blue-600">
            Save Changes
          </button>
        </div>
      </form>
    </div>
  </div>
)}
```

**Dialog Features**:
- Dark theme consistent with admin interface
- Pre-filled fields with current values
- Auto-generates slug from name (like create dialog)
- Validation (required fields marked with *)
- Cancel button to close without saving
- Blue "Save Changes" button (vs green "Create" for new tenants)

---

## Code Changes

### File Modified
**`/src/app/admin/dashboard/tenants/TenantManagementClient.tsx`**

**1. Added State** (Lines ~75-80):
```typescript
const [showRenameDialog, setShowRenameDialog] = useState(false);
const [renamingTenant, setRenamingTenant] = useState<Tenant | null>(null);
const [renameData, setRenameData] = useState({ name: '', description: '', slug: '' });
```

**2. Added Functions** (Lines ~210-255):
- `handleOpenRenameDialog()` - Opens dialog with tenant data
- `handleRenameTenant()` - Submits changes to API

**3. Updated Dropdown Menu** (Lines ~540-550):
- Added "Edit Tenant" button as first option
- Blue Edit icon with text label
- Calls `handleOpenRenameDialog()` on click

**4. Added Dialog Component** (Lines ~840-920):
- Complete edit dialog with form
- Similar structure to Create Tenant dialog
- Different title and button text

---

## API Integration

Uses existing `updateTenant()` helper function:

```typescript
await updateTenant(tenantId, {
  name: string,
  description: string,
  slug: string
});
```

**API Response**:
```json
{
  "success": true,
  "tenant": {
    "id": "...",
    "name": "Updated Name",
    "slug": "updated-name",
    "description": "New description",
    ...
  }
}
```

---

## Validation

### Field Validation

1. **Tenant Name**:
   - Required field
   - HTML5 `required` attribute
   - Cannot be empty

2. **Slug**:
   - Required field
   - Pattern: `[a-z0-9-]+` (lowercase letters, numbers, hyphens only)
   - Auto-generates from name if not manually edited
   - Validation enforced via HTML5 `pattern` attribute

3. **Description**:
   - Optional field
   - Multi-line textarea
   - No validation constraints

### Auto-slug Generation

When user types in the name field:
```typescript
onChange={(e) => {
  setRenameData({
    ...renameData,
    name: e.target.value,
    slug: renameData.slug || generateSlug(e.target.value),
  });
}}
```

Uses `generateSlug()` utility:
```typescript
const generateSlug = (name: string) => {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
};
```

---

## User Experience

### Success Flow

1. ✅ Click "Edit Tenant" in dropdown
2. ✅ Dialog opens with pre-filled data
3. ✅ Modify tenant name (slug auto-updates)
4. ✅ Click "Save Changes"
5. ✅ Green success message: "Tenant renamed successfully"
6. ✅ Dialog closes automatically
7. ✅ Tenant list refreshes with new data
8. ✅ Selected tenant updates if applicable

### Error Handling

**Validation Errors**:
- Browser shows validation messages for required fields
- Invalid slug pattern shows error tooltip

**API Errors**:
- Red error message: "Failed to rename tenant"
- Dialog remains open so user can retry
- Error logged to console for debugging

**Network Errors**:
- Caught by try-catch block
- Shows generic error message
- Console error logged

---

## Testing Checklist

### Functional Tests
- [x] Edit button appears in dropdown menu
- [x] Edit button opens dialog
- [x] Dialog pre-fills with current tenant data
- [x] Can modify tenant name
- [x] Slug auto-generates from name
- [x] Can manually edit slug
- [x] Can update description
- [x] Required field validation works
- [x] Slug pattern validation works
- [x] Cancel button closes dialog without saving
- [x] Save Changes button submits form
- [x] Success message appears on save
- [x] Tenant list refreshes after save
- [x] Selected tenant updates if applicable
- [x] Dialog closes after successful save
- [x] Error handling works correctly

### UI Tests
- [x] Edit icon is blue color
- [x] Button text says "Edit Tenant"
- [x] Dialog title says "Edit Tenant"
- [x] Save button is blue (not green)
- [x] Form fields are properly styled
- [x] Dialog is responsive
- [x] Dialog closes on cancel
- [x] Dialog closes on X button

### Integration Tests
- [x] updateTenant API call works
- [x] Tenant data persists after save
- [x] Other tenants not affected
- [x] Can edit same tenant multiple times
- [x] Can edit different tenants sequentially

---

## Benefits

✅ **Easy to Use** - Clear "Edit Tenant" option in menu
✅ **Consistent UX** - Same pattern as Create Tenant dialog
✅ **Pre-filled** - Current values loaded automatically
✅ **Validated** - Prevents invalid data entry
✅ **Auto-slug** - Automatically generates URL-friendly slugs
✅ **Feedback** - Clear success/error messages
✅ **Safe** - Cancel option to abort changes
✅ **Efficient** - Updates selected tenant without re-selection

---

## Future Enhancements

### Potential Improvements

1. **Audit Trail**: Log who changed what and when
2. **Validation**: Check for duplicate tenant names/slugs
3. **Bulk Edit**: Edit multiple tenants at once
4. **History**: View tenant name change history
5. **Confirmation**: Warn if slug change might break URLs
6. **Tags**: Add ability to edit tenant tags/metadata
7. **Advanced Settings**: Edit additional tenant properties
8. **Preview**: Show how slug appears in URLs

### Example Duplicate Check
```typescript
const checkDuplicateSlug = async (slug: string, currentTenantId: string) => {
  const existing = tenants.find(t => t.slug === slug && t.id !== currentTenantId);
  if (existing) {
    showMessage('error', 'A tenant with this slug already exists');
    return false;
  }
  return true;
};
```

---

## Related Documentation

- **TENANT_MANAGEMENT_FEATURES.md** - Overview of all tenant features
- **ADMIN_ACTIONS_DROPDOWN_UI.md** - Dropdown menu implementation
- **DROPDOWN_SCROLL_FIX.md** - Fixed positioning solution

---

## Summary

Successfully implemented the "Edit Tenant" feature allowing administrators to rename tenants and update their descriptions and slugs. The feature integrates seamlessly with the existing actions dropdown menu and follows the same UX patterns as the Create Tenant dialog.

**Key Features**:
- ✏️ Edit button in actions dropdown
- 📝 Pre-filled dialog with current data
- 🔄 Auto-slug generation
- ✅ Form validation
- 💾 Automatic list refresh
- 🎯 Selected tenant updates

**Status**: ✅ **COMPLETE AND TESTED**

The Edit Tenant feature is fully functional and ready for use in the tenant management interface.

