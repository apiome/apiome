# Deprecated Feature Documentation

## Overview

The Deprecated feature allows you to mark both **classes** and **properties** as deprecated, providing visual indicators and optional deprecation messages to inform users that certain schema elements should no longer be used.

## Implementation Status

✅ **Fully Implemented** - The deprecated feature is complete at both class and property levels.

## Features

### Class-Level Deprecation

Located in: `src/app/components/ade/studio/ClassEditDialog.tsx`

#### UI Controls
1. **Deprecated Checkbox**: Toggle to mark the entire class as deprecated
2. **Deprecation Message Field**: Optional text field that appears when deprecated is checked
   - Supports multiple lines
   - Placeholder suggests format: "e.g., Use NewClass instead. This will be removed in version 2.0."
   - Helper text: "Provide context about why it's deprecated and what to use instead"

#### Visual Indicators (on Canvas)
Located in: `src/app/components/ade/studio/ClassNode.tsx`

When a class is marked as deprecated, the following visual changes appear:
- **Class Name**: Displayed with strikethrough text decoration
- **"DEPRECATED" Badge**: Yellow warning badge displayed in the class header
  - Background: `#fef3c7` (light yellow)
  - Text color: `#92400e` (dark amber)
  - Border: `1px solid #fbbf24` (amber)
- **Tooltip**: Shows the deprecation message when hovering over the badge or class name

#### JSON Schema Output
```json
{
  "type": "object",
  "deprecated": true,
  "deprecationMessage": "Use NewClass instead. This will be removed in version 2.0."
}
```

### Property-Level Deprecation

Located in: `src/app/components/ade/studio/PropertyFormFields.tsx` and `PropertyDialog.tsx`

#### UI Controls
1. **Deprecated Checkbox**: Toggle to mark the property as deprecated
2. **Deprecation Message Field**: Optional text field that appears when deprecated is checked
   - Supports multiple lines
   - Helper text: "Provide context about why it's deprecated and what to use instead"
   - Background color changes to warning color when active

#### Visual Indicators (on Canvas)
Located in: `src/app/components/ade/studio/ClassNode.tsx`

When a property is marked as deprecated, the following visual changes appear:
- **Property Name**: Displayed with strikethrough text decoration
- **Text Color**: Changed to gray (`#9ca3af`) instead of black
- **"DEPR" Badge**: Small yellow warning badge displayed next to the property name
  - Background: `#fef3c7` (light yellow)
  - Text color: `#92400e` (dark amber)
  - Border: `1px solid #fbbf24` (amber)
  - Font size: `8px` (smaller than class badge)
- **Tooltip**: Shows the deprecation message when hovering over the property name

#### JSON Schema Output
```json
{
  "type": "string",
  "deprecated": true,
  "deprecationMessage": "Use newPropertyName instead. This will be removed in version 2.0."
}
```

## User Workflow

### Marking a Class as Deprecated

1. Double-click on a class node on the canvas, or right-click and select "Edit"
2. In the Class Edit Dialog, scroll to the "Deprecated" section (yellow background box)
3. Check the "Mark as Deprecated" checkbox
4. (Optional) Fill in the "Deprecation Message" field with context
5. Click "Save"
6. The class node on the canvas will immediately show:
   - Strikethrough on the class name
   - Yellow "DEPRECATED" badge in the header

### Marking a Property as Deprecated

1. Click the edit icon (pencil) next to a property in a class node
2. In the Property Dialog, scroll to the "Metadata Fields" section
3. Check the "Deprecated" checkbox
4. (Optional) Fill in the "Deprecation Message" field
5. Click "Save"
6. The property in the class node will immediately show:
   - Strikethrough on the property name
   - Gray text color
   - Small "DEPR" badge next to the name

## Technical Implementation

### Data Storage

#### Classes Table (PostgreSQL)
The deprecated information is stored in the `schema` JSONB column:
```sql
CREATE TABLE classes (
    id UUID PRIMARY KEY,
    version_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    schema JSONB NOT NULL,  -- Contains deprecated and deprecationMessage
    ...
);
```

#### Class Properties Table (PostgreSQL)
The deprecated information is stored in the `data` JSONB column:
```sql
CREATE TABLE class_properties (
    id UUID PRIMARY KEY,
    class_id UUID NOT NULL,
    property_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    data JSONB NOT NULL,  -- Contains deprecated and deprecationMessage
    ...
);
```

### TypeScript Interfaces

#### Class Schema
```typescript
interface ClassSchema {
  type: 'object';
  properties?: Record<string, any>;
  deprecated?: boolean;
  deprecationMessage?: string;
  // ... other schema properties
}
```

#### Property Form Data
```typescript
export interface PropertyFormData {
  // ... other fields
  deprecated?: boolean;
  deprecationMessage?: string;
}
```

### Form State Management

Both class and property dialogs use React `useState` hooks to manage form data:

```typescript
// Class Edit Dialog
const [formData, setFormData] = useState({
  name: '',
  description: '',
  deprecated: false,
  deprecationMessage: '',
  // ... other fields
});

// Property Dialog
const [formData, setFormData] = useState<PropertyFormData>({
  deprecated: false,
  deprecationMessage: '',
  // ... other fields
});
```

### Schema Building

#### Class Schema Builder
```typescript
const buildSchemaFromFormData = () => {
  const schema: any = { type: 'object', properties: {} };
  
  // ... other schema building
  
  if (formData.deprecated) {
    schema.deprecated = true;
    if (formData.deprecationMessage.trim()) {
      schema.deprecationMessage = formData.deprecationMessage.trim();
    }
  }
  
  return schema;
};
```

#### Property Schema Builder
```typescript
const buildPropertyJsonSchema = () => {
  const schema: any = {};
  
  // ... other schema building
  
  if (formData.deprecated) {
    schema.deprecated = formData.deprecated;
    if (formData.deprecationMessage && formData.deprecationMessage.trim()) {
      schema.deprecationMessage = formData.deprecationMessage.trim();
    }
  }
  
  return schema;
};
```

## OpenAPI 3.1 Compliance

The deprecated feature is fully compliant with OpenAPI 3.1.0 specification:

### Specification Reference
From OpenAPI 3.1.0 Schema Object:
- **deprecated**: `boolean` - Specifies that a schema is deprecated and SHOULD be transitioned out of usage.
- **deprecationMessage**: Not part of the official OpenAPI spec, but commonly used as a vendor extension

### Generated OpenAPI Output

#### Class Example
```yaml
components:
  schemas:
    OldUser:
      type: object
      deprecated: true
      deprecationMessage: "Use User instead. This will be removed in version 2.0."
      properties:
        id:
          type: string
        name:
          type: string
```

#### Property Example
```yaml
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
        old_email:
          type: string
          deprecated: true
          deprecationMessage: "Use email instead. This will be removed in version 2.0."
        email:
          type: string
          format: email
```

## Visual Design

### Color Palette
- **Warning Background**: `#fef3c7` (amber-100)
- **Warning Text**: `#92400e` (amber-800)
- **Warning Border**: `#fbbf24` (amber-400)
- **Strikethrough Color**: Inherits from parent text color
- **Grayed Text**: `#9ca3af` (gray-400)

### Badge Styling

#### Class Badge
```css
{
  fontSize: '10px',
  padding: '2px 5px',
  borderRadius: '3px',
  background: '#fef3c7',
  color: '#92400e',
  fontWeight: 600,
  border: '1px solid #fbbf24'
}
```

#### Property Badge
```css
{
  fontSize: '8px',
  padding: '1px 3px',
  borderRadius: '2px',
  background: '#fef3c7',
  color: '#92400e',
  fontWeight: 600,
  border: '1px solid #fbbf24',
  whiteSpace: 'nowrap'
}
```

## Testing Checklist

### Class Deprecation
- [ ] Create a new class
- [ ] Mark it as deprecated without a message
- [ ] Verify visual indicators appear (strikethrough + badge)
- [ ] Edit the class and add a deprecation message
- [ ] Verify tooltip shows the message
- [ ] Export to OpenAPI JSON/YAML and verify deprecated field is present
- [ ] Verify the deprecationMessage is included in the output

### Property Deprecation
- [ ] Create a class with multiple properties
- [ ] Mark one property as deprecated without a message
- [ ] Verify visual indicators appear (strikethrough + grayed text + badge)
- [ ] Edit the property and add a deprecation message
- [ ] Verify tooltip shows the message
- [ ] Export to OpenAPI JSON/YAML and verify deprecated field is present on the property
- [ ] Verify the deprecationMessage is included in the output

### Nested Properties
- [ ] Create a property with nested properties (object type)
- [ ] Mark a nested property as deprecated
- [ ] Verify the visual indicators work at any nesting level
- [ ] Verify the tooltip and badge appear correctly

### Read-Only Mode
- [ ] Open a class in read-only mode
- [ ] Verify the deprecated checkbox is disabled
- [ ] Verify the deprecation message field is disabled
- [ ] Verify visual indicators still appear for deprecated items

## Future Enhancements

### Potential Improvements
1. **Badge Customization**: Allow users to customize the badge text or color
2. **Deprecation Timeline**: Add a field to specify when the element will be removed (e.g., "Deprecated since: v1.5, Removed in: v2.0")
3. **Replacement Suggestion**: Add a dropdown to directly link to the replacement class/property
4. **Search/Filter**: Add ability to filter schema view to show only deprecated elements
5. **Deprecation Report**: Generate a report of all deprecated elements in a project/version
6. **Migration Tool**: Tool to help migrate from deprecated to new elements

## Related Files

### UI Components
- `src/app/components/ade/studio/ClassEditDialog.tsx` - Class edit dialog with deprecated controls
- `src/app/components/ade/studio/ClassNode.tsx` - Class node rendering with visual indicators
- `src/app/components/ade/studio/PropertyFormFields.tsx` - Property form fields with deprecated controls
- `src/app/components/ade/studio/PropertyDialog.tsx` - Property dialog with deprecated controls

### Database Helpers
- `lib/db/helper.ts` - Database operations for classes and properties

### OpenAPI Generation
- `app/utils/openapi.ts` - OpenAPI specification generation

## References

- [OpenAPI 3.1.0 Specification - Schema Object](https://spec.openapis.org/oas/v3.1.0#schema-object)
- [JSON Schema - deprecated keyword](https://json-schema.org/draft/2020-12/json-schema-validation.html#name-deprecated)
- [Material-UI Components](https://mui.com/material-ui/)
- [React Flow Documentation](https://reactflow.dev/)

