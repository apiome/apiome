# OpenAPI Import Reference Handling

## Overview

The OpenAPI import functionality has been updated to handle reference properties differently from regular properties.

## Key Changes

### Before
- All properties (including those with `$ref`) were created in the project-level `properties` table
- This caused confusion because references are class-specific relationships, not reusable properties
- Reference properties would appear in the property library alongside primitive types

### After
- **Reference properties** (properties with `$ref` or `items.$ref`) are created directly as `class_properties` with `property_id = NULL`
- **Regular properties** (string, number, boolean, etc.) continue to use the property library for reusability
- References are now treated as class-specific relationships, not reusable components

## Implementation Details

### Detection
A property is considered a reference if:
```typescript
const isReference = (data: any): boolean => {
  if (!data || typeof data !== 'object') return false;
  if (data.$ref) return true; // Direct $ref
  if (data.type === 'array' && data.items?.$ref) return true; // Array of references
  return false;
};
```

### Property Creation
```typescript
// References are skipped when building the property library
for (const p of allPropsFlat) {
  if (isReference(p.data)) continue; // Skip references
  // ... normal property processing
}
```

### Class Property Linking
```typescript
const linkProperties = async (classId: string, props: any[], parentId: string | null = null) => {
  for (const p of props || []) {
    let propertyId: string | null = null;
    
    if (isReference(p.data)) {
      // References: property_id = NULL
      propertyId = null;
    } else {
      // Regular properties: use property library
      propertyId = propertyIdByProjectName.get(projectName);
    }
    
    await client.query(
      `INSERT INTO apiome.class_properties (class_id, property_id, name, description, data, parent_id)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [classId, propertyId, p.name.trim(), p.description?.trim() || null, JSON.stringify(p.data), parentId]
    );
  }
};
```

## Example

Given this OpenAPI schema:
```yaml
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: string
          format: uuid
        name:
          type: string
        account:
          $ref: '#/components/schemas/Account'
        tags:
          type: array
          items:
            $ref: '#/components/schemas/Tag'
```

**Import Result:**

**Properties Table (reusable):**
- `id` (string, uuid format)
- `name` (string)

**Class Properties (User class):**
- `id` → links to property `id`
- `name` → links to property `name`
- `account` → property_id = NULL, data = `{"$ref": "#/components/schemas/Account"}`
- `tags` → property_id = NULL, data = `{"type": "array", "items": {"$ref": "#/components/schemas/Tag"}}`

## UI Workflow

In the Studio UI, references are created via **drag-and-drop** from the Properties sidebar:

1. A special **"New Reference"** item appears in the Properties tab (when not in read-only mode)
2. Users can drag this item onto:
   - **A class node** (for top-level references)
   - **An object/array-of-object property** (for nested references within that container)
3. A dialog opens to configure the reference:
   - Name and description
   - Array settings (with min/max items, uniqueness)
   - Optional target class (can be set immediately or connected later via canvas handles)
4. The reference is created directly as a `class_property` with `property_id = NULL`

This workflow ensures references are treated as class-specific relationships, not reusable library items.

## Benefits

1. **Clearer Intent**: References are clearly distinguished from reusable properties
2. **Property Library Simplicity**: The property library only contains primitive types that make sense to reuse
3. **Consistent with UI**: Drag-and-drop workflow matches the conceptual model of references as relationships
4. **No $ref Type Confusion**: No more `$ref` type properties in the property library
5. **Flexible References**: References can be reconnected via canvas handles without affecting the property library
6. **Precise Positioning**: Drag-and-drop allows creating nested references exactly where needed

## Backward Compatibility

Existing data with `$ref` type properties in the property library will continue to work:
- The PropertyDialog treats them as "object" type for display
- They can still be used in classes
- New imports won't create more of these legacy entries

