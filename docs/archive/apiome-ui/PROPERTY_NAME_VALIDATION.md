# Property Name Validation Implementation

## Summary

Modified the PropertyDialog component to restrict property names to only contain alphanumeric characters and underscores (A-Za-z0-9_), with helpful text suggesting camelCase naming convention.

## Changes Made

### 1. Client-Side Input Filtering
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyDialog.tsx`

**Location**: Property Name TextField in PropertyDialog

**Implementation**:
```typescript
<TextField
  autoFocus
  margin="dense"
  label="Property Name"
  type="text"
  fullWidth
  required
  value={propertyName}
  onChange={(e) => {
    // Only allow A-Za-z0-9_ characters
    const filteredValue = e.target.value.replace(/[^A-Za-z0-9_]/g, '');
    setPropertyName(filteredValue);
  }}
  helperText="Only letters, numbers, and underscores are allowed. Suggest camelCase property names."
  sx={{ mb: 2 }}
/>
```

**Features**:
- Real-time input filtering: Non-valid characters are automatically removed as user types
- Helper text: Informs users of allowed characters and suggests camelCase naming convention
- Uses regex `/[^A-Za-z0-9_]/g` to strip invalid characters

### 2. Server-Side Validation
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/PropertyDialog.tsx`

**Location**: `handleSubmit` function

**Implementation**:
```typescript
const handleSubmit = async () => {
  if (!propertyName.trim()) {
    setPropertyError('Property name is required');
    return;
  }

  // Validate property name contains only A-Za-z0-9_
  if (!/^[A-Za-z0-9_]+$/.test(propertyName)) {
    setPropertyError('Property name can only contain letters, numbers, and underscores');
    return;
  }

  if (propertyType === '$ref' && !propertyRef) {
    setPropertyError('Schema reference is required when type is $ref');
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

## Naming Convention Guidance

The helper text suggests **camelCase** for property names, which is the standard convention for JSON properties:

### Valid Property Names (camelCase examples):
- `firstName`
- `lastName`
- `emailAddress`
- `isActive`
- `orderDate`
- `userId`
- `apiKey`
- `createdAt`

### Also Valid (other naming styles):
- `first_name` (snake_case)
- `FirstName` (PascalCase)
- `FIRST_NAME` (SCREAMING_SNAKE_CASE)
- `_privateProperty` (leading underscore)

### Invalid Property Names (will be filtered):
- `first-name` → `firstname`
- `email address` → `emailaddress`
- `user.id` → `userid`
- `order#123` → `order123`
- `is-active` → `isactive`

## Consistency with Class Names

Both Class Names and Property Names now have the same validation:
- **Class Names**: Recommend PascalCase (e.g., `UserAccount`, `OrderItem`)
- **Property Names**: Suggest camelCase (e.g., `userName`, `orderDate`)

Both enforce the same character restrictions: A-Za-z0-9_

## User Experience

1. **While Typing**: Invalid characters are silently removed
2. **Helper Text**: Always visible below the input field with naming suggestion
3. **Error Message**: Shown on submit if somehow invalid (fallback validation)
4. **Both Modes**: Works identically for "Add Property" and "Edit Property"

## Build Status

✅ TypeScript compilation successful
✅ Build completed without errors
✅ All validations in place (client + server)
✅ Consistent with class name validation

## Related Documentation

- See also: `/docs/CLASS_NAME_VALIDATION.md` for class name validation details

