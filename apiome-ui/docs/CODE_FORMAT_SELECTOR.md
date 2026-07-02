# Code View Display Format Selector - Implementation

## Feature
Added a display format selector to the Code view in the Studio canvas, allowing users to switch between different specification formats. OpenAPI is selected by default, with a structure ready for additional formats.

## Problem Solved
Previously, the Code view only displayed OpenAPI specifications without any option to switch to other formats. This enhancement:
- Provides flexibility for future format additions
- Makes it clear that OpenAPI is the current format
- Sets up infrastructure for additional specification formats
- Improves user understanding of what they're viewing

## Implementation

### Files Changed
**File**: `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/page.tsx`

### Changes Made

#### 1. Added State for Display Format
```typescript
const [codeDisplayFormat, setCodeDisplayFormat] = useState<'openapi' | 'other'>('openapi');
```

#### 2. Added Format Selector Dropdown
```typescript
<select
  value={codeDisplayFormat}
  onChange={(e) => setCodeDisplayFormat(e.target.value as 'openapi' | 'other')}
  className="px-3 py-1.5 text-xs font-medium border..."
>
  <option value="openapi">OpenAPI</option>
  <option value="other" disabled>Other (Coming Soon)</option>
</select>
```

#### 3. Conditional Title and Description
```typescript
<h3 className="text-sm font-semibold...">
  {codeDisplayFormat === 'openapi' 
    ? 'OpenAPI 3.1.0 Specification' 
    : 'Other Format'}
</h3>
<p className="text-xs...">
  {codeDisplayFormat === 'openapi' 
    ? `Complete schema definition for ${selectedProject?.name} v${selectedVersion?.version_id}`
    : 'Additional format coming soon'}
</p>
```

#### 4. Conditional JSON/YAML Toggle
The JSON/YAML format toggle now only appears when OpenAPI is selected:
```typescript
{codeDisplayFormat === 'openapi' && (
  <div className="flex items-center border...">
    <button onClick={() => setCodeFormat('json')}>JSON</button>
    <button onClick={() => setCodeFormat('yaml')}>YAML</button>
  </div>
)}
```

#### 5. Conditional Copy/Export Buttons
Copy and Export buttons only appear when OpenAPI is selected:
```typescript
{codeDisplayFormat === 'openapi' && (
  <>
    <button>Copy</button>
    <button>Export</button>
  </>
)}
```

#### 6. Conditional Editor Content
```typescript
{codeDisplayFormat === 'openapi' ? (
  <Editor ... />  // Show OpenAPI spec
) : (
  <div>  // Show "Coming Soon" message
    <h3>Additional Format Coming Soon</h3>
    <p>More display formats will be available in a future update</p>
  </div>
)}
```

## User Interface

### Header Layout
```
┌──────────────────────────────────────────────────────────────┐
│ OpenAPI 3.1.0 Specification                                  │
│ Complete schema definition for Project v1.0                  │
│                                                               │
│ [OpenAPI ▼] [JSON] [YAML]              [Copy] [Export]      │
└──────────────────────────────────────────────────────────────┘
```

### Format Selector Dropdown
- **OpenAPI**: Active, shows OpenAPI specification
- **Other (Coming Soon)**: Disabled, placeholder for future formats

### Behavior by Format

#### OpenAPI Format (Default)
- ✅ Shows format selector dropdown
- ✅ Shows JSON/YAML toggle buttons
- ✅ Shows Copy and Export buttons
- ✅ Displays OpenAPI specification in Monaco Editor
- ✅ Title: "OpenAPI 3.1.0 Specification"
- ✅ Description: "Complete schema definition for [Project] v[Version]"

#### Other Format (Placeholder)
- ✅ Shows format selector dropdown
- ❌ Hides JSON/YAML toggle (not applicable)
- ❌ Hides Copy and Export buttons (no content)
- ✅ Shows "Coming Soon" message
- ✅ Title: "Other Format"
- ✅ Description: "Additional format coming soon"

## Benefits

✅ **Extensibility**: Easy to add new formats in the future  
✅ **Clear Default**: OpenAPI is obviously the selected format  
✅ **User Awareness**: Users know what format they're viewing  
✅ **Future Ready**: Infrastructure in place for additional formats  
✅ **Clean UX**: Appropriate buttons show/hide based on format  
✅ **Consistent**: Follows same pattern as other view controls  

## Future Extensions

When adding a new format (e.g., JSON Schema, GraphQL Schema, etc.):

1. **Update State Type**:
   ```typescript
   const [codeDisplayFormat, setCodeDisplayFormat] = 
     useState<'openapi' | 'jsonschema' | 'graphql'>('openapi');
   ```

2. **Add Dropdown Option**:
   ```typescript
   <option value="jsonschema">JSON Schema</option>
   <option value="graphql">GraphQL Schema</option>
   ```

3. **Add State for New Format**:
   ```typescript
   const [jsonSchemaSpec, setJsonSchemaSpec] = useState<string>('');
   ```

4. **Update Conditional Rendering**:
   ```typescript
   {codeDisplayFormat === 'openapi' ? (
     <Editor value={openApiSpec} />
   ) : codeDisplayFormat === 'jsonschema' ? (
     <Editor value={jsonSchemaSpec} />
   ) : (
     // GraphQL or others
   )}
   ```

5. **Add Generation Logic**:
   ```typescript
   // Generate JSON Schema from classes
   const generateJsonSchema = (classes) => { ... };
   ```

## Testing

To verify the feature works:

1. Open Studio page and select a project/version
2. Click on "Code" tab
3. Verify "OpenAPI" is selected in dropdown
4. Verify JSON/YAML toggle is visible
5. Verify Copy and Export buttons are visible
6. Click dropdown and see "Other (Coming Soon)" option
7. Verify it's disabled (can't select it)
8. OpenAPI spec should display correctly

## Edge Cases Handled

- ✅ Default to OpenAPI on initial load
- ✅ Disable future format options (not yet implemented)
- ✅ Hide irrelevant controls when non-OpenAPI selected
- ✅ Show appropriate "Coming Soon" message
- ✅ Maintain state when switching view modes

## Performance

- Minimal overhead (one additional state variable)
- Conditional rendering prevents unnecessary component mounting
- No impact on existing OpenAPI generation logic

## Documentation

Updated in `WHATS_NEW.md`:
- Added bullet point under "Enhanced Code view with display format selector"
- Notes about OpenAPI default and future formats

---

**Date**: November 29, 2025  
**Status**: ✅ Complete  
**Default**: OpenAPI format  
**Extensibility**: Ready for additional formats

