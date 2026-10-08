# Material UI to Radix UI Migration Status

**Last Updated**: December 17, 2025

## Overview

The Apiome UI Studio application uses Material UI for its complex form components. A full migration to Radix UI has been attempted but requires dedicated effort due to the size and complexity of the form components involved.

## Current Status

### Files Requiring Conversion

#### ClassEditDialog.tsx (2,077 lines) - **Active MUI Usage**

**Components Used**:
- Dialog, DialogTitle, DialogContent, DialogActions
- Tabs, Tab
- Box, Typography
- TextField, Textarea
- Autocomplete (for multi-select class references - 8+ instances)
- Chip (for multi-select tags)
- Checkbox, FormControlLabel
- Radio, RadioGroup  
- Alert
- Button

**Features Requiring Conversion**:
1. **Basic Information Section**: Class name, description, tags
2. **Schema Settings Section**: Additional properties (4 radio options + schema select), deprecation checkbox with message
3. **Pattern Properties Section**: Dynamic list with regex pattern + type select + optional schema reference
4. **Dependent Schemas Section**: Dynamic list with trigger property + schema reference
5. **Dependent Required Section**: Dynamic list with trigger property + comma-separated required fields
6. **Composition Section**: allOf/anyOf/oneOf multi-selects + discriminator configuration with mapping editor
7. **Conditional Schema Section**: Complex if/then/else rule builder (uses ConditionalSchemaBuilder)
8. **Documentation Section**: External docs URL + description, extensions editor
9. **Preview Tabs**: JSON, YAML, Example views with Monaco Editor

**Conversion Challenges**:
- MUI Autocomplete with multiple selection requires custom MultiSelect component
- Complex RadioGroup with conditional children
- Dynamic arrays with add/remove functionality
- Nested form sections with conditional rendering
- 20+ form state fields

#### PropertyFormFields.tsx (2,470 lines) - **Active MUI Usage**

Similar complexity to ClassEditDialog with type-specific constraint editors, enum drag-and-drop, tuple mode, contains schema, and more.

## Attempted Conversion

### What Was Tried

1. ✅ Created Radix UI imports for Dialog, Tabs, Button, Input, Textarea, Alert, Badge, Checkbox, Select
2. ✅ Created custom `useDarkMode` hook to replace MUI's `useColorScheme`
3. ✅ Created custom `MultiSelect` component to replace MUI Autocomplete multiple
4. ⚠️ Attempted to replace JSX components section by section
5. ❌ File became corrupted with mixed old/new code due to complexity

### Lessons Learned

1. **File is too large** for incremental patching - need complete rewrite
2. **Multiple MUI components** are deeply nested and interrelated
3. **Testing required** - each change needs verification that form logic still works
4. **Custom components needed** - MultiSelect, dynamic form arrays, conditional sections

## Recommended Approach

### Option 1: Keep Material UI for Forms (Current)
- ✅ Works perfectly
- ✅ All features functional
- ✅ No conversion effort needed
- ❌ Larger bundle size

### Option 2: Dedicated Migration Sprint (Future)
If full Radix UI is required, allocate 2-3 weeks for:

**Week 1**: Infrastructure
- Create all necessary Radix-based form components
- MultiSelect with tags
- Dynamic array form sections
- Radio groups with conditional children
- Test each component in isolation

**Week 2**: ClassEditDialog Conversion
- Convert section by section with testing
- Verify all form logic works
- Test OpenAPI schema generation
- Test save/load functionality

**Week 3**: PropertyFormFields Conversion
- Apply same approach
- Test all property types
- Verify constraint validation
- End-to-end testing

## Dependencies

### Currently Required (Material UI)
- `@mui/material`
- `@emotion/react`
- `@emotion/styled`

### Already Available (Radix UI)
- `@radix-ui/react-dialog`
- `@radix-ui/react-tabs`
- `@radix-ui/react-checkbox`
- `@radix-ui/react-select`
- `@radix-ui/react-radio-group`
- `@radix-ui/react-alert-dialog`

### Custom Components Needed
- MultiSelect (Autocomplete replacement)
- DynamicArraySection (for pattern properties, dependent schemas, etc.)
- ConditionalFormGroup (RadioGroup with conditional children)

## Summary

- **Current State**: Material UI working, Radix UI conversion attempted but requires dedicated sprint
- **Recommendation**: Keep Material UI for now; plan dedicated migration sprint if bundle size is critical
- **Effort Estimate**: 2-3 weeks for full conversion of both files (4,500+ lines)
- **Risk**: High - extensive form logic needs careful testing

