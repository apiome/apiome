# Fix: TypeScript Error with JSX in confirmDialog

## Issue
Build was failing with TypeScript error:
```
Type error: Type 'Element' is not assignable to type 'string'.
  message: (
    <div className="space-y-3">
      ...
    </div>
  )
```

The `confirmDialog` and `alertDialog` functions only accepted `string` for the `message` property, but the tenant editing code was passing JSX/ReactNode.

## Root Cause
The dialog system was originally designed to only accept string messages, but the tenant slug warning required rich JSX content (with styled elements, code blocks, and warning icons).

## Solution Applied

### 1. Updated Type Definitions

**DialogProvider.tsx** - Updated interfaces to accept ReactNode:
```typescript
interface ConfirmOptions {
  title?: string;
  message: string | ReactNode;  // Was: message: string;
  variant?: ConfirmDialogVariant;
  confirmLabel?: string;
  cancelLabel?: string;
}

interface AlertOptions {
  title?: string;
  message: string | ReactNode;  // Was: message: string;
  variant?: AlertDialogVariant;
  confirmLabel?: string;
}
```

### 2. Updated Dialog Components

**ConfirmDialog.tsx** - Updated to handle both strings and ReactNodes:
```typescript
interface ConfirmDialogProps {
  // ...
  message: string | React.ReactNode;  // Was: message: string;
  // ...
}

// Updated rendering logic:
<DialogContent>
  {typeof message === 'string' ? (
    <p className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
      {message}
    </p>
  ) : (
    <div className="text-gray-700 dark:text-gray-300">
      {message}
    </div>
  )}
</DialogContent>
```

**AlertDialog.tsx** - Same updates applied for consistency.

### 3. Fixed Type Assertions

**DialogProvider.tsx** - Added type assertions where passing message to components:
```typescript
message={confirmDialog.options.message as string | React.ReactNode}
```

## Impact

### Positive
- ✅ Enables rich, formatted content in dialog messages
- ✅ Maintains backward compatibility (still accepts plain strings)
- ✅ Allows for better UX with styled warnings and structured content
- ✅ TypeScript compilation now succeeds

### No Breaking Changes
- All existing code using string messages continues to work
- The conditional rendering handles both string and ReactNode appropriately

## Files Modified
1. `/src/app/components/providers/DialogProvider.tsx`
2. `/src/app/components/dialogs/ConfirmDialog.tsx`
3. `/src/app/components/dialogs/AlertDialog.tsx`

## Testing
The fix allows the tenant slug warning dialog to display:
- Structured layout with proper spacing
- Old → new value comparisons
- Styled warning boxes with icons
- Code-formatted slug display
- All while maintaining type safety

## Example Usage

### String message (still works):
```typescript
await confirmDialog({
  title: 'Delete Item?',
  message: 'Are you sure you want to delete this item?',
});
```

### JSX message (now works):
```typescript
await confirmDialog({
  title: 'Change Slug?',
  message: (
    <div className="space-y-3">
      <p>You are about to change the slug.</p>
      <div className="bg-yellow-50 p-3 rounded">
        <AlertTriangle className="h-5 w-5" />
        <p>Warning: This affects URLs</p>
      </div>
    </div>
  ),
});
```

