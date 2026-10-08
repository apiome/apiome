# Nested Properties Feature

## Overview

This document describes the implementation of nested properties support in the `class_properties` table, allowing properties of type "object" to contain inline child properties.

## Database Changes

### Migration Script: 20251112-182735.sql

The migration adds the following changes to the `class_properties` table:

#### 1. New Column: `parent_id`

- **Type**: `UUID`
- **Nullable**: Yes (NULL for top-level properties)
- **References**: `class_properties(id)` with `ON DELETE CASCADE`
- **Purpose**: Establishes a hierarchical relationship between properties, allowing nested structures

#### 2. Updated Unique Constraint

- **Old Constraint**: `class_properties_class_name_unique (class_id, name)`
- **New Constraint**: `class_properties_parent_name_unique (class_id, parent_id, name)`
- **Purpose**: Allows the same property name to exist at different nesting levels while ensuring uniqueness within the same parent

#### 3. New Index

- **Index**: `idx_class_properties_parent_id`
- **Purpose**: Optimizes queries that filter or join on parent_id

## Code Changes

### TypeScript (apiome-ui/lib/db/helper.ts)

#### Updated Functions:

1. **getPropertiesForClass(classId: string)**
   - Now includes `parent_id` in the SELECT query
   - Orders results by `parent_id NULLS FIRST, name ASC` to show top-level properties first

2. **addPropertyToClass(classId, propertyId, name, description, data, parentId)**
   - Added optional `parentId` parameter (defaults to `null`)
   - Updated unique constraint check to include `parent_id`
   - Inserts `parent_id` into the database

3. **updateClassProperty(classPropertyId, name, description, data)**
   - Returns `parent_id` in the result set

4. **Copy class properties (in version copy operation)**
   - Now preserves `parent_id` when copying properties between versions

5. **OpenAPI import**
   - Sets `parent_id` to `null` for imported top-level properties

### Python (apiome-rest/src/app/database.py)

#### Updated Functions:

1. **get_properties_for_class(class_id: str)**
   - Now includes `parent_id` in the SELECT query
   - Orders results by `parent_id NULLS FIRST, name ASC`

## Usage Example

### Creating Nested Properties

```typescript
// Create a parent property of type "object"
const parentResult = await addPropertyToClass(
  classId,
  propertyId,
  'address',
  'User address object',
  { type: 'object' },
  null // top-level property
);

const parentPropertyId = JSON.parse(parentResult).classProperty.id;

// Create child properties under the parent
await addPropertyToClass(
  classId,
  streetPropertyId,
  'street',
  'Street address',
  { type: 'string' },
  parentPropertyId // nested under 'address'
);

await addPropertyToClass(
  classId,
  cityPropertyId,
  'city',
  'City name',
  { type: 'string' },
  parentPropertyId // nested under 'address'
);
```

### Querying Nested Properties

```typescript
const propertiesJson = await getPropertiesForClass(classId);
const properties = JSON.parse(propertiesJson);

// Properties are ordered with top-level first (parent_id = null)
// Then child properties grouped by their parent_id
properties.forEach(prop => {
  if (prop.parent_id === null) {
    console.log(`Top-level: ${prop.name}`);
  } else {
    console.log(`  Child of ${prop.parent_id}: ${prop.name}`);
  }
});
```

## Benefits

1. **Hierarchical Structure**: Support complex nested object schemas directly in the database
2. **Reusability**: Parent properties can be reused across different classes
3. **Flexibility**: Same property names can exist at different nesting levels
4. **Data Integrity**: CASCADE deletion ensures child properties are removed when parent is deleted
5. **Performance**: Indexed parent_id column ensures efficient queries for nested structures

## Migration Notes

- The migration is idempotent - it can be run multiple times safely
- Existing top-level properties will have `parent_id = NULL`
- No data migration is required for existing properties
- The unique constraint change may fail if there are duplicate property names at the same level (unlikely in existing data)

## Future Enhancements

1. Add validation to prevent circular references (parent referencing child)
2. Add depth limit constraints to prevent overly deep nesting
3. Add helper functions to retrieve entire property trees
4. Add UI components to visualize and edit nested property structures
5. Add recursive queries to get full property hierarchy in a single database call

