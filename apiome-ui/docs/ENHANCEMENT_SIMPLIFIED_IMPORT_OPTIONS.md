# Enhancement: Simplified Import Options - Project and Version Selection

## Overview
Simplified the Import Options in Step 3 (Preview) by:
1. Removing the "Target Project" dropdown (always creates a new project)
2. Implementing new version selection with two options: "Use version from specification" or "Manually enter version"
3. Adding version validation with strict regex pattern

## Date
December 23, 2024

## Changes Implemented

### 1. Removed Target Project Selection
**Before:**
- Dropdown with two options: "Create New Project" or "Import to Existing Project"
- Conditional project name input when "Create New Project" selected
- Confusing UX with unnecessary options

**After:**
- Always creates a new project (no dropdown)
- Direct project name input field
- Clearer, simpler workflow

**Rationale:** Import functionality always creates a new project, so the dropdown was redundant.

### 2. Implemented Smart Version Selection

**Two Radio Button Options:**

#### Option 1: "Use version from specification" (Default)
- Auto-populated with version from `info.version` in the OpenAPI spec
- Input field is **disabled** (read-only)
- Falls back to "1.0.0" if no version in spec
- Shown with helper text: "Using version 'X.X.X' from specification"

#### Option 2: "Manually enter version"
- Input field is **enabled** for user input
- Starts **empty** (no pre-populated value)
- Real-time validation as user types
- Helper text: "Allowed characters: 0-9, A-Z, a-z, . (dot), - (dash)"

### 3. Version Validation
**Strict Regex Pattern:** `/[^0-9A-Za-z.\-]/g`

**Allowed Characters:**
- `0-9` - Digits
- `A-Z` - Uppercase letters
- `a-z` - Lowercase letters
- `.` - Dot (period)
- `-` - Dash (hyphen)

**Validation Behavior:**
- Real-time sanitization as user types
- Invalid characters automatically removed
- No error messages needed (prevents invalid input)

**Valid Examples:**
- `1.0.0`
- `2.3.4-beta`
- `v1.2.3`
- `2024.12.23`
- `1.0.0-rc.1`
- `3.0.0-SNAPSHOT`

**Invalid Characters (Auto-removed):**
- Spaces
- Special characters: `!@#$%^&*()+=[]{}|;:'"<>,?/`
- Underscores `_`
- Forward/backslashes

## Implementation Details

### Updated ImportOptions Interface
```typescript
// Before
export interface ImportOptions {
  targetProject: string;      // 'new' or 'existing'
  targetVersion: string;
  // ...other options
}

// After
export interface ImportOptions {
  projectName: string;         // Direct project name
  versionSource: 'spec' | 'manual';  // Version selection method
  targetVersion: string;       // Version number
  // ...other options
}
```

### New State Management
```typescript
const [importOptions, setImportOptions] = useState<ImportOptions>({
  projectName: analysis.document?.info?.title || 'New Project',
  versionSource: 'spec',  // Default to spec version
  targetVersion: analysis.document?.info?.version || '1.0.0',
  autoLayout: true,
  createRelationships: true,
  applyNamingConvention: true,
  generateDocumentation: false,
  selectedSchemas: schemas.map(s => s.name)
});
```

### New Handlers

#### handleVersionSourceChange
```typescript
const handleVersionSourceChange = (source: 'spec' | 'manual') => {
  const specVersion = analysis.document?.info?.version || '1.0.0';
  const newOptions = {
    ...importOptions,
    versionSource: source,
    targetVersion: source === 'spec' ? specVersion : ''
  };
  setImportOptions(newOptions);
  onImportOptionsChange?.(newOptions);
};
```

**Behavior:**
- When switching to 'spec': Sets targetVersion to spec version
- When switching to 'manual': Clears targetVersion (empty string)
- Updates parent component via callback

#### handleVersionChange
```typescript
const handleVersionChange = (version: string) => {
  // Only allow: 0-9, A-Z, a-z, ., -
  const sanitized = version.replace(/[^0-9A-Za-z.\-]/g, '');
  const newOptions = { ...importOptions, targetVersion: sanitized };
  setImportOptions(newOptions);
  onImportOptionsChange?.(newOptions);
};
```

**Behavior:**
- Applies regex validation
- Removes invalid characters in real-time
- Updates state with sanitized value
- No error messages needed (preventive validation)

## UI/UX Design

### New Layout
```
┌─── Import Options ──────────────────────────────┐
│                                                 │
│ Project Name                                    │
│ ┌─────────────────────────────────────────────┐ │
│ │ Swagger Petstore                            │ │
│ └─────────────────────────────────────────────┘ │
│ A new project will be created with this name   │
│                                                 │
│ Version                                         │
│ ○ Use version from specification               │
│ ○ Manually enter version                       │
│                                                 │
│ ┌─────────────────────────────────────────────┐ │
│ │ 1.0.0                      [disabled/enabled]│ │
│ └─────────────────────────────────────────────┘ │
│ Using version "1.0.0" from specification        │
│ (or) Allowed characters: 0-9, A-Z, a-z, ., -   │
│                                                 │
│ ☑ Auto-layout imported schemas on canvas       │
│ ☑ Create relationships from $ref               │
│ ☑ Apply naming convention (PascalCase)         │
│ ☐ Generate documentation from descriptions     │
└─────────────────────────────────────────────────┘
```

### Visual States

#### State 1: Use version from specification (Default)
```
Version
◉ Use version from specification
○ Manually enter version

┌─────────────────────────────────┐
│ 1.0.0                 [disabled]│ ← Grayed out
└─────────────────────────────────┘
Using version "1.0.0" from specification
```

#### State 2: Manually enter version
```
Version
○ Use version from specification
◉ Manually enter version

┌─────────────────────────────────┐
│ 2.0.0-beta                      │ ← Active input
└─────────────────────────────────┘
Allowed characters: 0-9, A-Z, a-z, . (dot), - (dash)
```

### Color Scheme
- **Radio buttons**: Indigo accent color when selected
- **Disabled input**: Gray background, reduced opacity
- **Active input**: White/gray background, full opacity
- **Helper text**: Gray-500 for informational text
- **Full dark mode support**: All states adapt to theme

## Benefits

### For Users:
1. **Simpler workflow**: No confusing dropdown for project selection
2. **Clear intent**: Always creates a new project - no ambiguity
3. **Smart defaults**: Uses spec version automatically
4. **Flexibility**: Can manually override version if needed
5. **Validation**: Prevents invalid version formats
6. **Better UX**: Clear radio buttons vs dropdown

### For Developers:
1. **Less code**: Removed Select component and logic
2. **Simpler state**: Fewer conditional branches
3. **Clear validation**: Regex pattern is explicit and testable
4. **Better data model**: ImportOptions more semantic

## Files Modified

### 1. PreviewPanel.tsx

**Interface changes:**
```typescript
// Lines 15-23: Updated ImportOptions interface
export interface ImportOptions {
  projectName: string;              // NEW: Direct project name
  versionSource: 'spec' | 'manual'; // NEW: Version selection method
  targetVersion: string;            // CHANGED: Now validated
  // ...existing options
}
```

**State initialization:**
```typescript
// Lines 47-55: Updated initial state
const [importOptions, setImportOptions] = useState<ImportOptions>({
  projectName: analysis.document?.info?.title || 'New Project',
  versionSource: 'spec',
  targetVersion: analysis.document?.info?.version || '1.0.0',
  // ...
});
```

**New handlers:**
```typescript
// Lines 102-125: Added handlers
const handleVersionSourceChange = (source: 'spec' | 'manual') => {
  // ...logic
};

const handleVersionChange = (version: string) => {
  const sanitized = version.replace(/[^0-9A-Za-z.\-]/g, '');
  // ...logic
};
```

**UI changes:**
```typescript
// Lines 395-462: Replaced Target Project dropdown with:
// 1. Project Name input field
// 2. Version radio buttons
// 3. Version input with validation
```

**Removed imports:**
```typescript
// Line 5: Removed unused import
// - Select (no longer using Select component)
// Note: ChevronRight is still used in schema list for selected indicator
```

## Testing

### Manual Testing Checklist:
1. ✅ Open Preview step (Step 3)
2. ✅ Verify "Project Name" field shows spec title
3. ✅ Verify "Use version from specification" is selected by default
4. ✅ Verify version input is disabled and shows spec version
5. ✅ Click "Manually enter version" radio button
6. ✅ Verify version input becomes enabled and clears
7. ✅ Type valid version (e.g., "2.0.0-beta") - works
8. ✅ Try typing invalid characters (e.g., "2.0.0_beta@1") - auto-removed
9. ✅ Switch back to "Use version from specification" - re-populates
10. ✅ Verify helper text changes based on selection

### Validation Testing:
```
Input: "1.2.3" → Output: "1.2.3" ✅
Input: "v2.0.0" → Output: "v2.0.0" ✅
Input: "3.0.0-SNAPSHOT" → Output: "3.0.0-SNAPSHOT" ✅
Input: "2024.12.23" → Output: "2024.12.23" ✅
Input: "1.0.0_rc1" → Output: "1.0.0rc1" ✅ (underscore removed)
Input: "2.0 beta" → Output: "2.0beta" ✅ (space removed)
Input: "1.0.0@latest" → Output: "1.0.0latest" ✅ (@ removed)
```

## Edge Cases Handled

1. **No version in spec**: Falls back to "1.0.0"
2. **No title in spec**: Falls back to "New Project"
3. **Switching between sources**: Properly updates version
4. **Real-time validation**: Invalid chars removed as user types
5. **Empty manual version**: Allowed (will need server validation)
6. **Copy-paste invalid text**: Automatically sanitized

## Known Limitations

1. **No semantic validation**: Doesn't check if version makes sense (e.g., "......" is allowed)
2. **No version format enforcement**: Doesn't require specific format (e.g., semver)
3. **No duplicate check**: Doesn't check if version already exists
4. **Empty version allowed**: Manual entry can be left empty

**Note:** Server-side validation should enforce additional rules (semver format, uniqueness, etc.)

## Future Enhancements

Possible improvements:
- [ ] Semver validation (major.minor.patch format)
- [ ] Version increment buttons (+1 major, +1 minor, +1 patch)
- [ ] Version history/suggestions from existing versions
- [ ] Duplicate version warning
- [ ] Preview version format as user types
- [ ] Import to existing project (if requirement changes)

## Migration Notes

**For existing code using ImportOptions:**
- `targetProject` → Removed (always creates new)
- `newProjectName` → Now `projectName` in ImportOptions
- Added `versionSource` field
- `targetVersion` now has validation

**Import button logic should check:**
```typescript
if (!importOptions.projectName.trim()) {
  // Show error: Project name is required
}
if (!importOptions.targetVersion.trim()) {
  // Show error: Version is required
}
if (importOptions.selectedSchemas.length === 0) {
  // Show error: Select at least one schema
}
```

## References

- [Semantic Versioning](https://semver.org/)
- [OpenAPI Specification - Info Object](https://spec.openapis.org/oas/latest.html#info-object)
- Related: IMPORT_STEP3_IMPLEMENTATION.md
- Related: IMPLEMENTATION_SUMMARY_PREVIEW_ENHANCEMENTS.md

