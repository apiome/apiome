# Property Forms Consolidation

## Overview
The property editing forms in PropertyDialog and ClassPropertyEditDialog have been consolidated to use a shared `PropertyFormFields` component, eliminating code duplication and ensuring consistency.

## Changes Made

### New Component: PropertyFormFields
**Location**: `/src/app/components/ade/studio/PropertyFormFields.tsx`

A reusable component that renders all property constraint fields including:
- Description
- String constraints (minLength, maxLength, pattern, format)
- Number constraints (minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf)
- Array constraints (minItems, maxItems, uniqueItems)
- Enum values
- Default value
- Metadata (required, readOnly, writeOnly, deprecated, example)

#### Key Features:
- **Unified Data Structure**: Uses `PropertyFormData` interface for all form fields
- **Type-aware Rendering**: Shows only relevant constraints based on `baseType` (string, number, integer, etc.)
- **Array Support**: Displays appropriate help text for array item constraints
- **Consistent Sizing**: Supports `size` prop ('small' | 'medium') for different dialog sizes
- **Regex Testing**: Integrates `RegexTester` component for pattern validation
- **Mutual Exclusivity**: readOnly and writeOnly checkboxes mutually exclude each other
- **Flexible Display**: Can show/hide title and metadata fields via props

### Updated Components

#### ClassPropertyEditDialog
- **Before**: Had ~200 lines of duplicate constraint UI code
- **After**: Uses `PropertyFormFields` component with just ~10 lines
- **State Management**: Consolidated from 20+ individual state variables to a single `formData` object
- **Removed**: handleAddEnum, handleRemoveEnum functions (now in PropertyFormFields)
- **Maintained**: Class-specific features like additionalProperties control

#### PropertyDialog  
- **Before**: Had ~250 lines of duplicate constraint UI code
- **After**: Uses `PropertyFormFields` component with just ~10 lines
- **State Management**: Consolidated from 20+ individual state variables to a single `formData` object
- **Removed**: Duplicate enum handlers, duplicate constraint fields
- **Maintained**: Dialog-specific features like type selector and view mode switcher

## Benefits

### 1. Code Reduction
- Eliminated ~200 lines of duplicate code in ClassPropertyEditDialog
- Eliminated ~250 lines of duplicate code in PropertyDialog
- **Total**: ~450 lines of duplicate code removed

### 2. Consistency
- Both forms now use identical constraint UI
- No more checking both files for consistency
- Regex tester appears in the same location with same behavior
- Exclusive Minimum/Maximum checkboxes have consistent layout

### 3. Maintainability
- Single source of truth for property constraints UI
- Changes to constraint fields only need to be made once
- Easier to add new constraint types

### 4. Type Safety
- Shared `PropertyFormData` interface ensures type consistency
- TypeScript catches mismatches between forms

### 5. Testing
- Can write tests for PropertyFormFields once
- Tests apply to all forms using it

## PropertyFormData Interface

```typescript
export interface PropertyFormData {
  // Basic fields
  title?: string;
  description?: string;
  format?: string;
  pattern?: string;
  
  // String constraints
  minLength?: string;
  maxLength?: string;
  
  // Number constraints
  minimum?: string;
  maximum?: string;
  exclusiveMinimum?: boolean;
  exclusiveMaximum?: boolean;
  multipleOf?: string;
  
  // Array constraints
  minItems?: string;
  maxItems?: string;
  uniqueItems?: boolean;
  
  // Common constraints
  enum?: string[];
  default?: string;
  
  // Metadata
  required?: boolean;
  readOnly?: boolean;
  writeOnly?: boolean;
  deprecated?: boolean;
  example?: string;
}
```

## Usage Example

```typescript
const [formData, setFormData] = useState<PropertyFormData>({});

<PropertyFormFields
  baseType="string"          // or 'number', 'integer', 'object', etc.
  isArray={false}            // true if property is an array
  data={formData}            // form data object
  onChange={(field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  }}
  showMetadata={true}        // show required, readOnly, etc.
  showTitle={false}          // show title field
  size="small"               // 'small' or 'medium'
/>
```

## Migration Status

### Completed ✅
- **ClassPropertyEditDialog** - Migrated to PropertyFormFields
- **PropertyDialog** - Migrated to PropertyFormFields

### Result
Both property editing forms now use the shared `PropertyFormFields` component, eliminating all duplicate code and ensuring complete consistency.

## Testing Checklist

When using PropertyFormFields, verify:
- [ ] All constraint fields appear for the appropriate type
- [ ] Regex tester shows for string types with pattern
- [ ] Exclusive checkboxes appear below min/max fields
- [ ] Enum values can be added and removed
- [ ] readOnly and writeOnly are mutually exclusive
- [ ] Array constraints only show for array types
- [ ] Dark mode styling works correctly
- [ ] Form data saves and loads correctly

## Future Enhancements

Potential improvements to PropertyFormFields:
1. Add validation for numeric constraints (min < max)
2. Add format presets dropdown (email, date, uuid, etc.)
3. Add pattern presets (common regex patterns)
4. Improve enum UI with drag-and-drop reordering
5. Add constraint conflict detection (e.g., minLength > maxLength)
6. Add JSON schema preview

