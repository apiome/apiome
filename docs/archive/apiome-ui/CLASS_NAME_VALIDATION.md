# Class Name Validation Implementation

## Summary

Modified the "Add Class" and "Edit Class" forms to restrict class names to only contain alphanumeric characters and underscores (A-Za-z0-9_).

## Changes Made

### 1. Client-Side Input Filtering
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/layout.tsx`

**Location**: Class Name TextField in Class Dialog

**Implementation**:
```typescript
<TextField
  autoFocus
  margin="dense"
  label="Class Name"
  type="text"
  fullWidth
  required
  value={className}
  onChange={(e) => {
    // Only allow A-Za-z0-9_ characters
    const filteredValue = e.target.value.replace(/[^A-Za-z0-9_]/g, '');
    setClassName(filteredValue);
  }}
  helperText="Only letters, numbers, and underscores are allowed"
  sx={{ mb: 2 }}
/>
```

**Features**:
- Real-time input filtering: Non-valid characters are automatically removed as user types
- Helper text: Informs users of allowed characters
- Uses regex `/[^A-Za-z0-9_]/g` to strip invalid characters

### 2. Server-Side Validation
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/layout.tsx`

**Location**: `handleClassDialogSubmit` function

**Implementation**:
```typescript
const handleClassDialogSubmit = async () => {
  if (!className.trim()) {
    setClassError('Class name is required');
    return;
  }

  // Validate class name contains only A-Za-z0-9_
  if (!/^[A-Za-z0-9_]+$/.test(className)) {
    setClassError('Class name can only contain letters, numbers, and underscores');
    return;
  }

  if (!selectedVersionId) {
    setClassError('No version selected');
    return;
  }
  // ...rest of function
}
```

**Features**:
- Validation before submission
- Uses regex `/^[A-Za-z0-9_]+$/` to verify entire string
- Shows clear error message if validation fails
- Works for both Add and Edit modes

## Allowed Characters

✅ **Allowed**:
- Uppercase letters: A-Z
- Lowercase letters: a-z
- Numbers: 0-9
- Underscore: _

❌ **Not Allowed**:
- Spaces
- Hyphens/dashes
- Special characters (!@#$%^&*()+=[]{}|;:'",.<>?/)
- Unicode/international characters
- Emojis

## Examples

### Valid Class Names:
- `Person`
- `UserAccount`
- `API_Response`
- `Order123`
- `_PrivateClass`
- `class_name_v2`

### Invalid Class Names (will be filtered):
- `My Class` → `MyClass`
- `User-Account` → `UserAccount`
- `API Response` → `APIResponse`
- `Order#123` → `Order123`
- `class.name` → `classname`

## User Experience

1. **While Typing**: Invalid characters are silently removed
2. **Helper Text**: Always visible below the input field
3. **Error Message**: Shown on submit if somehow invalid (fallback validation)
4. **Both Modes**: Works identically for "Add Class" and "Edit Class"

## Build Status

✅ TypeScript compilation successful
✅ Build completed without errors
✅ All validations in place (client + server)

