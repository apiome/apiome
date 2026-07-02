# Import Flow - Step 3 (Preview & Mapping) Implementation

## Overview
Implemented Step 3 of the import flow as specified in FEATURE_ROADMAP.md section 4.11. This provides a comprehensive preview and mapping interface for selecting schemas to import, configuring import options, and creating or selecting target projects.

## Date
December 22, 2024

## Components Implemented

### 1. PreviewPanel Component (`PreviewPanel.tsx`)

A comprehensive preview and configuration panel that allows users to:
- Select which schemas to import
- Preview individual schema details
- Configure import options
- Create new projects or import to existing ones
- Set target version and import settings

#### Key Features:

##### Schema Selection Controls
- **Select All** button - Selects all schemas for import
- **Select None** button - Deselects all (except required dependencies)
- **Selection counter** - Shows "X of Y selected"
- **Search/Filter** - Real-time filtering of schema list
- **Checkboxes** - Individual schema selection using Radix UI Checkbox

##### Two-Panel Layout (Split View)

**Left Panel - Schemas to Import:**
- Scrollable list of all available schemas
- Each schema shows:
  - Checkbox for selection
  - Package icon (📦)
  - Schema name
  - Property count
- Click anywhere on row to preview (doesn't toggle checkbox)
- Selected schema highlighted with indigo background
- Hover effects for better UX

**Right Panel - Schema Preview:**
- Shows details of selected schema
- **Schema name** (large heading)
- **Description** (if available)
- **Properties list**:
  - Property name (monospace, indigo)
  - Property type (with intelligent type detection)
  - Required indicator (red, if required)
- **Type detection**:
  - `$ref → SchemaName` for references
  - `array<$ref → SchemaName>` for array refs
  - `array<type>` for array types
  - `enum` for enumerations
  - Base types (string, integer, etc.)

##### Import Options Section

**Target Project:**
- Dropdown selector with 2 options:
  - "+ Create New Project" - Creates a new project
  - "Import to Existing Project" - Uses existing project
- When "Create New Project" selected:
  - Shows text input for project name
  - Auto-populated with spec title (`info.title`)
  - Defaults to "New Project" if no title

**Target Version:**
- Text input for version number
- Auto-populated from spec version (`info.version`)
- Defaults to "1.0.0" if not specified
- "+ New Version" button for creating new versions

**Import Settings (4 checkboxes):**
1. ☑ **Auto-layout imported schemas on canvas**
   - Automatically arrange schemas using layout algorithm
   - Checked by default

2. ☑ **Create relationships from $ref**
   - Automatically create relationships based on schema references
   - Checked by default

3. ☑ **Apply naming convention (PascalCase)**
   - Convert schema names to PascalCase format
   - Checked by default

4. ☐ **Generate documentation from descriptions**
   - Create documentation based on schema descriptions
   - Unchecked by default

### 2. ImportOptions Interface

```typescript
interface ImportOptions {
  targetProject: string;        // 'new' or 'existing'
  targetVersion: string;         // e.g., '1.0.0'
  autoLayout: boolean;
  createRelationships: boolean;
  applyNamingConvention: boolean;
  generateDocumentation: boolean;
  selectedSchemas: string[];     // Array of schema names
}
```

### 3. ImportDialog Integration

Updated the ImportDialog to support Step 3:

#### New State:
```typescript
currentStep: 'source' | 'file-upload' | 'analysis' | 'preview'
importOptions: ImportOptions | null
```

#### Navigation Flow:
1. **Step 1**: Source selection
2. **Step 1a**: File upload → "Analyze →"
3. **Step 2**: Analysis results → "Next →"
4. **Step 3**: Preview & mapping → "Import →" ✓
5. **Step 4**: Import execution (TODO)
6. **Step 5**: Completion (TODO)

#### Step Indicator Updates:
- Step 1 shows ✓ (green) when on Step 2 or 3
- Step 2 shows ✓ (green) when on Step 3
- Step 3 highlights (indigo) when active
- Progress lines turn green when steps completed

#### Footer Buttons:
- **Preview step**: ← Back / Cancel / Import →
- **Import button**:
  - Disabled if no schemas selected
  - Logs import options when clicked (TODO: actual import)

## UI/UX Design

### Layout:
```
┌─────────────────────────────────────────────────────┐
│ [Select All] [Select None] [X of Y]  [🔍 Filter]   │
├────────────────────┬────────────────────────────────┤
│ Schemas (Left)     │ Schema Preview (Right)         │
│                    │                                │
│ ☑ 📦 Pet          │ Pet                            │
│    3 properties    │ ─────────────                  │
│ ☑ 📦 Category     │ Properties:                    │
│    2 properties    │ ├─ id: integer (required)     │
│ ☑ 📦 Tag          │ ├─ name: string (required)    │
│    2 properties    │ └─ status: enum               │
├────────────────────┴────────────────────────────────┤
│ Import Options                                      │
│ Target Project: [+ Create New Project        ▼]    │
│ Project Name: [Swagger Petstore            ]       │
│ Target Version: [1.0.0                     ]       │
│ ☑ Auto-layout  ☑ Create relationships              │
│ ☑ Apply naming ☐ Generate docs                     │
└─────────────────────────────────────────────────────┘
```

### Color Scheme:
- **Indigo/Purple**: Primary actions, selected items, checkboxes
- **Green**: Completed steps, success indicators
- **Gray**: Unselected, disabled items
- **White/Dark Gray**: Background (theme-dependent)

### Interactive Elements:
- **Checkboxes**: Radix UI with smooth animations
- **Dropdowns**: Radix UI Select with portal rendering
- **Search**: Real-time filtering
- **Hover states**: Visual feedback on all interactive elements
- **Selection highlight**: Indigo background for selected schema

## Technical Implementation

### Dependencies:
```json
{
  "@radix-ui/react-checkbox": "^1.x",
  "@radix-ui/react-select": "^2.x",
  "@radix-ui/react-icons": "^1.3.2",
  "lucide-react": "existing"
}
```

### State Management:
- Local state in PreviewPanel for UI (search, selection)
- Callback to parent for import options changes
- ImportDialog manages overall flow state

### Smart Features:

**1. Auto-selection**:
- All schemas selected by default
- Can deselect individual schemas
- Select All/None for bulk operations

**2. Project Name Auto-fill**:
- Extracts from `info.title` in spec
- Falls back to "New Project"
- User can edit the name

**3. Version Auto-fill**:
- Extracts from `info.version` in spec
- Falls back to "1.0.0"
- User can edit or create new version

**4. Type Detection**:
- Intelligent parsing of property types
- Shows references as `$ref → Target`
- Shows arrays with element types
- Shows enums, base types

**5. Search/Filter**:
- Case-insensitive search
- Filters schema list in real-time
- Preserves selection state

### Radix UI Components:

**Checkbox:**
```tsx
<Checkbox.Root
  checked={value}
  onCheckedChange={handler}
  className="w-5 h-5 rounded border-2 ..."
>
  <Checkbox.Indicator>
    <Check className="w-4 h-4 text-white" />
  </Checkbox.Indicator>
</Checkbox.Root>
```

**Select (Dropdown):**
```tsx
<Select.Root value={value} onValueChange={handler}>
  <Select.Trigger>...</Select.Trigger>
  <Select.Portal>
    <Select.Content>
      <Select.Viewport>
        <Select.Item value="...">
          <Select.ItemText>...</Select.ItemText>
          <Select.ItemIndicator>...</Select.ItemIndicator>
        </Select.Item>
      </Select.Viewport>
    </Select.Content>
  </Select.Portal>
</Select.Root>
```

## File Structure:
```
apiome-ui/
├── src/
│   └── app/
│       ├── components/
│       │   └── ade/
│       │       └── dashboard/
│       │           ├── ImportDialog.tsx (Updated)
│       │           ├── AnalysisPanel.tsx (Existing)
│       │           └── PreviewPanel.tsx (New)
│       └── utils/
│           └── openapi-analyzer.ts (Existing)
```

## Future Enhancements

### Planned for Step 3:
- [ ] **Conflict Resolution**: Detect and resolve schema conflicts
- [ ] **Diff View**: Show changes between existing and new schemas
- [ ] **Dependency Detection**: Auto-select required referenced schemas
- [ ] **Relationship Preview**: Show relationship graph
- [ ] **Existing Project List**: Fetch actual projects from API
- [ ] **Version Management**: Create and manage versions
- [ ] **Validation**: Pre-import validation checks

### Not Yet Implemented:
- Schema conflict detection
- Diff view modal for conflicts
- Merge/Replace/Skip/Rename options
- Dependency auto-selection
- Existing project dropdown population
- Version creation workflow

## Testing Recommendations

### Manual Testing:
1. ✅ Navigate through all steps (Source → Upload → Analyze → Preview)
2. ✅ Select/deselect schemas individually
3. ✅ Use Select All/Select None buttons
4. ✅ Filter schemas with search
5. ✅ Click schema to view preview
6. ✅ Toggle import options checkboxes
7. ✅ Switch between New/Existing project
8. ✅ Edit project name
9. ✅ Edit target version
10. ✅ Click Import button (check console for options)
11. ✅ Test back navigation
12. ✅ Verify dark mode appearance

### Edge Cases:
- [ ] Empty specification (no schemas)
- [ ] Very long schema names
- [ ] Schemas with no properties
- [ ] Schemas with many properties (scrolling)
- [ ] Special characters in schema names
- [ ] Missing info.title/version
- [ ] Circular references in schemas

### Integration Testing:
- [ ] State persistence across steps
- [ ] Back button behavior
- [ ] Import options callback
- [ ] Selected schemas synchronization
- [ ] Project name validation
- [ ] Version number validation

## Known Limitations

1. **No conflict detection**: Assumes all schemas are new
2. **No existing project list**: Dropdown has placeholder only
3. **No version management**: New version button is placeholder
4. **No dependency tracking**: Doesn't auto-select required schemas
5. **No validation**: Accepts any project name/version
6. **No relationship preview**: Can't see relationships before import
7. **Basic type detection**: May not handle all OpenAPI type variations

## Next Steps

### Step 4: Import Execution
- Progress tracking
- Live import status
- Error handling
- Rollback capability
- Import log

### Step 5: Import Complete
- Success summary
- Failed items report
- Next action options
- View on canvas
- Export report

## References

- FEATURE_ROADMAP.md - Section 4.11 Step 3 (Preview & Mapping Panel)
- [Radix UI Checkbox](https://www.radix-ui.com/primitives/docs/components/checkbox)
- [Radix UI Select](https://www.radix-ui.com/primitives/docs/components/select)
- [OpenAPI Specification](https://spec.openapis.org/oas/latest.html)

