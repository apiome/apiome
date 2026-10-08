# Custom Dialogs Testing Guide

## Manual Testing Steps

### 1. Test Project Deletion
**Location**: `/ade/dashboard/projects`

**Steps**:
1. Navigate to the Projects dashboard
2. Click the delete (trash) icon on any project
3. Verify custom confirmation dialog appears with:
   - Title: "Delete Project"
   - Red danger styling
   - "Delete" and "Cancel" buttons
4. Click "Cancel" - dialog should close, project remains
5. Click delete again and click "Delete" - project should be deleted
6. If deletion fails, verify custom error alert appears

### 2. Test Version Publishing
**Location**: `/ade/dashboard/versions`

**Steps**:
1. Navigate to the Versions dashboard
2. Select a project with unpublished versions
3. Click "Publish" on a version
4. Verify custom confirmation dialog appears with:
   - Title: "Publish Version"
   - Warning styling (yellow/orange)
   - Appropriate message
5. Test both "Cancel" and "Publish" actions
6. Try publishing without permissions - verify warning alert

### 3. Test Class Deletion in Studio
**Location**: `/ade/studio`

**Steps**:
1. Open the Studio
2. Select a project and version
3. Click delete on a class node
4. Verify custom confirmation dialog with:
   - Title: "Delete Class"
   - Red danger styling
   - Class name in message
5. Test deletion flow

### 4. Test Property Removal
**Location**: `/ade/studio` (Class nodes)

**Steps**:
1. In Studio, hover over a property in a class node
2. Click the trash icon next to a property
3. Verify custom confirmation dialog appears
4. Test removal flow

### 5. Test Clipboard Copy Success
**Location**: `/ade/studio` (Class edit dialog)

**Steps**:
1. Open a class for editing
2. Click the copy button
3. Verify custom success alert appears with:
   - Green success styling
   - Checkmark icon
   - Success message

### 6. Test Member Removal (Tenants)
**Location**: `/ade/dashboard/tenants`

**Steps**:
1. Navigate to Tenants
2. Expand a tenant's members
3. Try removing a regular member - verify standard warning
4. Try removing an admin member - verify enhanced warning with admin notice
5. Test the removal flow

### 7. Test Visibility Changes (Published)
**Location**: `/ade/dashboard/published`

**Steps**:
1. Navigate to Published Versions
2. Toggle visibility on a version
3. Verify custom confirmation dialog with:
   - Appropriate title
   - Clear explanation of visibility change
4. Test both public → private and private → public

### 8. Test Validation Alerts
**Location**: Various pages

**Steps**:
1. In Studio, try adding a class without selecting a version
2. Try editing a property without selecting a project
3. Try deleting in read-only mode
4. Verify all validation alerts use custom dialogs with warning styling

## Visual Checks

For each dialog, verify:
- ✅ Matches application theme (light/dark mode)
- ✅ Icons are appropriate for the variant
- ✅ Colors match the variant (red for danger, yellow for warning, etc.)
- ✅ Text is readable and properly aligned
- ✅ Buttons have proper hover states
- ✅ Dialog has proper shadow/elevation
- ✅ Dialog is centered on screen
- ✅ Background overlay is present

## Keyboard Testing

For each dialog:
- ✅ Press `Escape` - should close/cancel
- ✅ Press `Tab` - should move between buttons
- ✅ Press `Enter` - should trigger the focused button
- ✅ Focus trap keeps focus within dialog

## Responsive Testing

Test dialogs on:
- ✅ Desktop (1920x1080)
- ✅ Tablet (768x1024)
- ✅ Mobile (375x667)

Verify dialog scales appropriately and remains usable.

## Expected Results

### All Native Dialogs Replaced
No browser-native alert or confirm boxes should appear anywhere in the application.

### Consistent Appearance
All custom dialogs should have:
- Consistent styling
- Smooth animations
- Proper spacing and padding
- Material-UI design patterns

### Proper Functionality
- Confirmations should properly return true/false
- Alerts should properly await user acknowledgment
- All async operations should work correctly
- No console errors

## Common Issues to Check

1. **Async/Await**: Ensure all `confirm()` and `alert()` calls use `await`
2. **Dependencies**: Verify `alertDialog` and `confirmDialog` are in dependency arrays
3. **Error Handling**: Check that try/catch blocks properly show error alerts
4. **Success Messages**: Verify success operations show success-variant alerts

## Browser Compatibility

Test in:
- ✅ Chrome/Edge (Chromium)
- ✅ Firefox
- ✅ Safari

## Accessibility Testing

Use screen reader to verify:
- Dialog announces properly
- Buttons are labeled correctly
- Focus management works
- Escape key functionality

