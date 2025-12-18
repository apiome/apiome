# Property Form Fields - Material UI to Radix UI Conversion

## Status

The PropertyFormFields component is in the process of being converted from Material UI to Radix UI.

## Completed

1. **New Radix UI Components Created:**
   - `Collapsible.tsx` - Wrapper for @radix-ui/react-collapsible
   - `RadioGroup.tsx` - Custom radio group component
   - `FormField.tsx` - Form field wrapper with label and helper text

2. **Imports Updated:**
   - Replaced Material UI imports with Radix UI and custom components
   - Added Lucide React icons to replace Material Icons
   - Added custom `useDarkMode` hook to replace MUI's `useColorScheme`

3. **Components Converted:**
   - `SortableEnumItem` - Converted from MUI ListItem to div with Tailwind
   - `SectionHeader` - Converted from MUI Box/Typography to div/headings with Tailwind
   - Main container structure started

## Remaining Work

The file is 2500+ lines and requires systematic conversion of:

### Material UI Components → Radix UI/HTML + Tailwind

1. **Box → div**
   - Replace `<Box sx={{...}}>` with `<div className={cn(...)}>
   - Convert `sx` prop styles to Tailwind classes

2. **TextField → Input/Textarea + FormField**
   - Single line: `<Input />` wrapped in `<FormField>`
   - Multi-line: `<Textarea />` wrapped in `<FormField>`
   - Extract label, helperText, error props to FormField

3. **Typography → HTML elements**
   - variant="h1-h6" → `<h1-h6>`
   - variant="body1/body2" → `<p>`
   - variant="caption" → `<span className="text-xs">`

4. **IconButton → button**
   - Replace with `<button className={cn(...)}>`
   - Add Tailwind classes for styling

5. **Tooltip → TooltipProvider + Tooltip + TooltipTrigger + TooltipContent**
   ```tsx
   <TooltipProvider>
     <Tooltip>
       <TooltipTrigger asChild>{trigger}</TooltipTrigger>
       <TooltipContent><p>{content}</p></TooltipContent>
     </Tooltip>
   </TooltipProvider>
   ```

6. **FormControlLabel + Checkbox → Custom component**
   ```tsx
   <div className="flex items-center gap-2">
     <Checkbox checked={...} onCheckedChange={...} />
     <Label>{label}</Label>
   </div>
   ```

7. **FormControlLabel + Radio → RadioGroup + RadioGroupItem**
   ```tsx
   <RadioGroup value={value} onValueChange={onChange}>
     <RadioGroupItem value="..." label="..." />
   </RadioGroup>
   ```

8. **Collapse → Collapsible**
   ```tsx
   <Collapsible open={condition}>
     <CollapsibleContent>
       {content}
     </CollapsibleContent>
   </Collapsible>
   ```

9. **List/ListItem → div**
   - List: `<div className="space-y-2">`
   - ListItem: `<div className="flex items-center gap-2">`

10. **InputAdornment → Custom wrapper**
    - Create wrapper divs with absolute positioning or flex layout

## Style Conversion Guide

### Common sx → Tailwind Mappings

```tsx
// Layout
display: 'flex' → className="flex"
flexDirection: 'column' → className="flex-col"
gap: 2 → className="gap-2"
p: 3 → className="p-6" (MUI spacing unit is 8px, Tailwind is 4px)

// Colors
bgcolor: '#fff' → className="bg-white"
color: '#000' → className="text-black"

// Borders
borderRadius: 2 → className="rounded-lg"
border: '1px solid #e2e8f0' → className="border border-gray-200"

// Sizing
fullWidth → className="w-full"

// Dark Mode
isDark ? '#xxx' : '#yyy' → className={isDark ? 'bg-gray-900' : 'bg-white'}
Or use: className="bg-white dark:bg-gray-900"
```

## Testing Checklist

After conversion, test:
- [ ] Form fields render correctly
- [ ] Dark mode works properly
- [ ] All input types (text, number, textarea) function
- [ ] Checkboxes and radio buttons work
- [ ] Tooltips appear on hover
- [ ] Collapsible sections expand/collapse
- [ ] Drag and drop for enum values works
- [ ] Form validation and error messages display
- [ ] All advanced features (tuple mode, extensions, etc.) work

## Notes

- The component uses @dnd-kit for drag-and-drop which is framework-agnostic and doesn't need conversion
- RegexTester, PrefixItemsEditor, and ExtensionsEditor components may also need conversion if they use Material UI
- Consider breaking this large component into smaller sub-components for better maintainability

## Next Steps

1. Convert remaining Box components to div
2. Convert all TextField components to Input/Textarea with FormField
3. Convert Typography components to appropriate HTML elements
4. Convert all interactive components (buttons, checkboxes, radios)
5. Test thoroughly
6. Consider refactoring into smaller components

