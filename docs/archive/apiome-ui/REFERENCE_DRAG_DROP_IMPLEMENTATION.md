# Reference Drag-and-Drop Implementation

## Overview

References are now created via drag-and-drop from the Properties sidebar instead of a button on each class. This provides more flexibility for positioning references at both top-level and nested within object containers.

## Implementation Summary

### 1. Sidebar: Draggable "New Reference" Item
**File:** `src/app/components/ade/studio/StudioSideNav.tsx`

- Added a special "New Reference" draggable item in the Properties tab
- Appears above the properties list when not in read-only mode
- Drag payload: `{ type: 'new-reference' }`
- Visual styling: Green dashed border with "drag onto class or object" hint

### 2. Class Node: Drop Handling
**File:** `src/app/components/ade/studio/ClassNode.tsx`

#### Type Definition
```typescript
type ClassNodeData = {
  // ...existing properties...
  onCreateReference?: (classOrCompositeId: string) => void;
  // ...rest of properties...
};
```

#### Top-Level Drop Handler
```typescript
const handleDrop = (e: React.DragEvent) => {
  // ...existing code...
  if (dropData.type === 'new-reference' && typedData.onCreateReference) {
    // Create reference at top-level on this class
    typedData.onCreateReference(typedData.id);
  }
};
```

#### Nested Drop Handler (Object Containers)
```typescript
const handlePropertyDrop = (e: React.DragEvent, parentPropertyId: string) => {
  // ...existing code...
  if (dropData.type === 'new-reference' && typedData.onCreateReference) {
    // Create nested reference under the given parent property (object container)
    typedData.onCreateReference(`${typedData.id}|${parentPropertyId}`);
  }
};
```

### 3. Studio Page: Reference Dialog Integration
**File:** `src/app/ade/studio/page.tsx`

#### State Management
```typescript
const [referenceDialogOpen, setReferenceDialogOpen] = useState(false);
const [referenceTargetClassId, setReferenceTargetClassId] = useState<string>('');
```

#### Handler: Open Dialog
```typescript
const handleCreateReference = useCallback((classOrCompositeId: string) => {
  if (isReadOnly) return;
  
  // Support nested context: "classId|parentPropertyId"
  const [classId, parentId] = classOrCompositeId.split('|');
  setReferenceTargetClassId(classId);
  (window as any).__refParentId = parentId || null;
  setReferenceDialogOpen(true);
}, [isReadOnly]);
```

#### Handler: Submit Reference
```typescript
const handleReferenceSubmit = useCallback(async (referenceData: {
  name: string;
  description: string | null;
  isArray: boolean;
  targetClassId: string | null;
  minItems?: number;
  maxItems?: number;
  uniqueItems?: boolean;
}) => {
  // Build reference data with $ref or items.$ref
  const data: any = {};
  
  if (referenceData.isArray) {
    data.type = 'array';
    // Add array constraints
    if (referenceData.targetClassId) {
      data.items = { $ref: `#/components/schemas/${targetClassName}` };
    } else {
      data.items = {}; // Placeholder for later connection
    }
  } else {
    if (referenceData.targetClassId) {
      data.$ref = `#/components/schemas/${targetClassName}`;
    }
    // Empty object if no target - placeholder reference
  }
  
  const parentId: string | null = (window as any).__refParentId || null;
  
  // Create as class_property with property_id = NULL
  await addPropertyToClass(
    referenceTargetClassId,
    null, // No property_id - direct class property
    referenceData.name,
    referenceData.description,
    data,
    parentId
  );
}, [referenceTargetClassId, nodes, reloadClasses, triggerSidebarRefresh]);
```

#### Wire Up Callback
```typescript
const classesToNodes = async (classes: any[]): Promise<Node[]> => {
  return classes.map((cls) => ({
    // ...existing node config...
    data: {
      // ...existing data...
      onCreateReference: handleCreateReference,
      // ...rest of data...
    }
  }));
};
```

### 4. Reference Dialog
**File:** `src/app/components/ade/studio/ReferenceDialog.tsx`

- Prompts for reference name (required, alphanumeric + underscore)
- Optional description
- Array checkbox with constraints (min/max items, unique)
- Optional target class selection (dropdown of available classes)
- If no target selected, creates placeholder that can be connected later via canvas handles

### 5. Database Migration: Allow NULL property_id
**File:** `/apiome-db/scripts/20251114-191956.sql`

The database schema was updated to support NULL values for `property_id` in the `class_properties` table:

```sql
-- Remove NOT NULL constraint from property_id column
ALTER TABLE apiome.class_properties
ALTER COLUMN property_id DROP NOT NULL;

-- Add check constraint to ensure NULL property_id entries are references
ALTER TABLE apiome.class_properties
ADD CONSTRAINT class_properties_null_property_id_is_reference
CHECK (
    property_id IS NOT NULL 
    OR data::jsonb ? '$ref' 
    OR (data::jsonb->>'type' = 'array' AND data::jsonb->'items' ? '$ref')
);
```

**To apply this migration:**
```bash
cd /home/kenji/Development/apiome/apiome-db
psql -U kenji -d kenji -f scripts/20251114-191956.sql
```

### 6. Code: Support NULL property_id
**File:** `lib/db/helper.ts`

```typescript
export async function addPropertyToClass(
  classId: string, 
  propertyId: string | null,  // Now accepts NULL
  name: string, 
  description: string | null, 
  data: any, 
  parentId: string | null = null
) {
  // ...implementation creates class_property with property_id = NULL for references...
}
```

### 7. OpenAPI Import: Skip References in Property Library
**File:** `lib/db/helper.ts`

```typescript
// Helper: check if property data is a reference
const isReference = (data: any): boolean => {
  if (!data || typeof data !== 'object') return false;
  if (data.$ref) return true;
  if (data.type === 'array' && data.items?.$ref) return true;
  return false;
};

// Skip references when building property library
for (const p of allPropsFlat) {
  if (isReference(p.data)) continue; // Skip
  // ...normal property processing...
}

// Create references directly as class_properties with property_id = NULL
const linkProperties = async (classId: string, props: any[], parentId: string | null = null) => {
  for (const p of props || []) {
    let propertyId: string | null = null;
    
    if (isReference(p.data)) {
      propertyId = null; // Direct class property, not from library
    } else {
      propertyId = propertyIdByProjectName.get(projectName);
    }
    
    await client.query(
      `INSERT INTO apiome.class_properties (class_id, property_id, name, description, data, parent_id)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [classId, propertyId, p.name, p.description, JSON.stringify(p.data), parentId]
    );
  }
};
```

## User Workflow

### Creating a Top-Level Reference
1. Open the Properties tab in the sidebar
2. Drag the green "New Reference" item onto a class node
3. In the dialog:
   - Enter reference name (e.g., "account", "owner")
   - Optionally add description
   - Optionally check "Array of references" and set constraints
   - Optionally select target class, or leave empty to connect later
4. Click "Create Reference"
5. Reference appears on the class with a connection handle
6. If no target was selected, drag the handle to any class to set the `$ref`

### Creating a Nested Reference (Inside an Object)
1. Ensure the object property is expanded (click chevron)
2. Drag the green "New Reference" item onto the object property row
   - The row will highlight in green to indicate it's a valid drop target
3. Follow the same dialog steps as above
4. Reference is created as a nested property within that object

### Connecting References via Canvas
- All reference properties have a handle on the right side
- Drag from the handle to any class node to set/update the `$ref`
- Handles are colored blue when connected, gray when unconnected
- Dangling references (pointing to missing classes) show warning icons in the sidebar

## Benefits

1. **Flexible Positioning**: Can create references exactly where needed (top-level or nested)
2. **Consistent Model**: References are clearly class-specific relationships, not library items
3. **Visual Feedback**: Drop zones highlight in green; handles show connection status
4. **Deferred Connection**: Can create placeholder references and connect them later
5. **Import Consistency**: OpenAPI imports match the UI model (references aren't in property library)
6. **Clean Property Library**: Only contains reusable primitive types (string, number, etc.)

## Database Schema

### Properties Table (Reusable Library)
```
properties:
  - id, project_id, name, description, data
  - Contains only primitive types (string, number, boolean, object)
  - NO references ($ref types)
```

### Class Properties Table (Class-Specific)
```
class_properties:
  - id, class_id, property_id, name, description, data, parent_id
  - property_id = NULL for references (not linked to property library)
  - property_id = <uuid> for reusable properties
  - parent_id for nested properties (inside objects)
```

## Edge Cases Handled

1. **Read-only mode**: "New Reference" item doesn't appear; drop handlers are disabled
2. **Duplicate names**: Server validates unique names per parent context
3. **Nested depth**: Supports arbitrary nesting depth via recursive parent_id
4. **Missing target classes**: Warning badges appear in sidebar and canvas
5. **Array references**: Full support with min/max items, uniqueItems constraints
6. **OpenAPI import**: References are detected and created correctly, both top-level and nested

## Testing Checklist

- [ ] Drag "New Reference" onto class → dialog opens with correct class context
- [ ] Drag "New Reference" onto object property → dialog opens with correct parent context
- [ ] Create reference with no target → creates placeholder, handle is gray
- [ ] Connect handle to class → updates $ref, handle turns blue
- [ ] Create array reference with constraints → constraints saved in data
- [ ] Import OpenAPI with references → references created as class_properties with NULL property_id
- [ ] Import OpenAPI with nested references → nested references created correctly
- [ ] Read-only mode → "New Reference" hidden, drop handlers disabled
- [ ] Duplicate reference name → server rejects with clear error

## Related Documentation

- `OPENAPI_IMPORT_REFERENCE_HANDLING.md` - Detailed import behavior
- `NESTED_PROPERTIES_*.md` - Nested property system documentation
- `API_KEY_AUTHENTICATION.md` - API authentication for REST operations

