# PropertyFormFields Material UI to Radix UI Conversion Guide

## Summary

The PropertyFormFields component (2500+ lines) requires conversion from Material UI to Radix UI with Tailwind CSS.

## Quick Reference: Component Conversions

### 1. Box → div

**Before:**
```tsx
<Box sx={{ display: 'flex', gap: 2, p: 3 }}>
  Content
</Box>
```

**After:**
```tsx
<div className="flex gap-4 p-6">
  Content
</div>
```

### 2. TextField (single line) → Input + FormField

**Before:**
```tsx
<TextField
  label="Title"
  value={data.title || ''}
  onChange={(e) => onChange('title', e.target.value)}
  helperText="Display title"
  fullWidth
/>
```

**After:**
```tsx
<FormField label="Title" helperText="Display title">
  <Input
    value={data.title || ''}
    onChange={(e) => onChange('title', e.target.value)}
    className="w-full"
  />
</FormField>
```

### 3. TextField (multiline) → Textarea + FormField

**Before:**
```tsx
<TextField
  label="Description"
  multiline
  rows={2}
  value={data.description || ''}
  onChange={(e) => onChange('description', e.target.value)}
  helperText="What this represents"
/>
```

**After:**
```tsx
<FormField label="Description" helperText="What this represents">
  <Textarea
    rows={2}
    value={data.description || ''}
    onChange={(e) => onChange('description', e.target.value)}
  />
</FormField>
```

### 4. Typography → HTML elements

**Before:**
```tsx
<Typography variant="h3" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : '#1e293b' }}>
  Title
</Typography>
```

**After:**
```tsx
<h3 className={cn('font-semibold', isDark ? 'text-gray-100' : 'text-gray-900')}>
  Title
</h3>
```

### 5. IconButton → button

**Before:**
```tsx
<IconButton
  onClick={handleClick}
  size="small"
  sx={{ color: '#6366f1', '&:hover': { bgcolor: 'rgba(99, 102, 241, 0.1)' } }}
>
  <AddIcon fontSize="small" />
</IconButton>
```

**After:**
```tsx
<button
  onClick={handleClick}
  className="p-1 text-indigo-600 hover:bg-indigo-50 rounded transition-colors"
>
  <Plus className="h-4 w-4" />
</button>
```

### 6. Tooltip → Radix Tooltip

**Before:**
```tsx
<Tooltip title="Add example" arrow>
  <IconButton onClick={handleAdd}>
    <AddIcon />
  </IconButton>
</Tooltip>
```

**After:**
```tsx
<TooltipProvider>
  <Tooltip>
    <TooltipTrigger asChild>
      <button onClick={handleAdd}>
        <Plus className="h-5 w-5" />
      </button>
    </TooltipTrigger>
    <TooltipContent>
      <p>Add example</p>
    </TooltipContent>
  </Tooltip>
</TooltipProvider>
```

### 7. FormControlLabel + Checkbox → Checkbox + Label

**Before:**
```tsx
<FormControlLabel
  control={<Checkbox checked={data.required} onChange={(e) => onChange('required', e.target.checked)} />}
  label="Required"
/>
```

**After:**
```tsx
<div className="flex items-center gap-2">
  <Checkbox
    checked={data.required}
    onCheckedChange={(checked) => onChange('required', checked)}
  />
  <Label>Required</Label>
</div>
```

### 8. Radio → RadioGroup + RadioGroupItem

**Before:**
```tsx
<FormControlLabel
  control={<Radio checked={value === 'option1'} onChange={() => setValue('option1')} />}
  label="Option 1"
/>
<FormControlLabel
  control={<Radio checked={value === 'option2'} onChange={() => setValue('option2')} />}
  label="Option 2"
/>
```

**After:**
```tsx
<RadioGroup value={value} onValueChange={setValue}>
  <RadioGroupItem value="option1" label="Option 1" />
  <RadioGroupItem value="option2" label="Option 2" />
</RadioGroup>
```

### 9. Collapse → Collapsible

**Before:**
```tsx
<Collapse in={isOpen} timeout={300}>
  <div>Content</div>
</Collapse>
```

**After:**
```tsx
<Collapsible open={isOpen}>
  <CollapsibleContent className="transition-all duration-300">
    <div>Content</div>
  </CollapsibleContent>
</Collapsible>
```

### 10. List/ListItem → div

**Before:**
```tsx
<List>
  <ListItem>
    <ListItemText primary="Item 1" />
  </ListItem>
</List>
```

**After:**
```tsx
<div className="space-y-2">
  <div className="flex items-center gap-2">
    <span>Item 1</span>
  </div>
</div>
```

## Icon Replacements

Material Icons → Lucide React:

- `AddIcon` → `<Plus />`
- `DeleteIcon` → `<Trash2 />`
- `DragIndicatorIcon` → `<GripVertical />`
- `AutoAwesomeIcon` → `<Sparkles />`
- `SortByAlphaIcon` → `<SortAsc />`
- `OpenInNewIcon` → `<ExternalLink />`
- `InfoOutlinedIcon` → `<Info />`
- `TuneIcon` → `<Sliders />`
- `SettingsIcon` → `<Settings />`
- `CodeIcon` → `<Code />`

## Color Mode Hook

**Before:**
```tsx
const { mode: colorMode, systemMode } = useColorScheme();
const isDark = colorMode === 'dark' || (colorMode === 'system' && systemMode === 'dark');
```

**After:**
```tsx
const isDark = useDarkMode(); // Custom hook already added to the file
```

## Common Tailwind Class Mappings

| MUI sx Property | Tailwind Class |
|----------------|----------------|
| `display: 'flex'` | `flex` |
| `flexDirection: 'column'` | `flex-col` |
| `gap: 1` | `gap-2` (multiply by 2) |
| `p: 3` | `p-6` (multiply by 2) |
| `m: 2` | `m-4` (multiply by 2) |
| `bgcolor: '#fff'` | `bg-white` |
| `color: '#000'` | `text-black` |
| `borderRadius: 2` | `rounded-lg` |
| `fullWidth` | `w-full` |

## Step-by-Step Conversion Process

1. **Backup the file** ✅ (Already done - PropertyFormFields.tsx.backup)

2. **Update imports** ✅ (Already done)

3. **Convert components section by section:**
   - Start with the main container
   - Convert each section (Basic Info, Property Behavior, Constraints, etc.)
   - Test after each major section

4. **Replace all Material UI components** (In Progress)

5. **Test thoroughly:**
   - All form inputs work
   - Dark mode toggles correctly
   - Tooltips appear
   - Collapsible sections function
   - Drag-and-drop works
   - Validation shows errors

6. **Clean up:**
   - Remove unused imports
   - Remove sx props
   - Fix any TypeScript errors

## Status

- ✅ Created new Radix UI components (Collapsible, RadioGroup, FormField)
- ✅ Updated imports
- ✅ Converted SortableEnumItem component
- ✅ Converted SectionHeader component
- ✅ Started main container conversion
- ⏳ Need to convert remaining 2400+ lines

## Recommendation

Given the size and complexity, consider:

1. **Incremental conversion**: Convert and test one section at a time
2. **Component extraction**: Break large sections into smaller reusable components
3. **Pair programming**: Have someone review changes as you go
4. **Automated testing**: Add tests to catch regressions

The basic structure and patterns are now in place. The remaining work is systematic application of these patterns throughout the file.

