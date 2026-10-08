# Bug Fix: Copy Function for Classes with Inline Properties

## Problem
When creating a new project version and copying classes from a previous version, the copy function was not working properly for classes that contain inline properties (properties with `type: "object"` that contain nested properties identified by a `parent_id`).

The issue was in the `copyClassesFromVersion` function in `/lib/db/helper.ts`.

## Root Cause
The original implementation was directly copying the `parent_id` column from the source class properties to the new class properties:

```sql
INSERT INTO apiome.class_properties (class_id, property_id, name, description, data, parent_id)
SELECT $1, property_id, name, description, data, parent_id
FROM apiome.class_properties
WHERE class_id = $2
```

However, `parent_id` in the `class_properties` table is a self-referencing foreign key that points to the `id` column of another row in the same table. When properties are copied:
1. New `id` values are auto-generated for each inserted property
2. The copied `parent_id` values still reference the OLD property IDs from the source class
3. These old IDs don't exist in the new class context, breaking the parent-child relationships

## Solution
The fix implements a proper ID mapping strategy using a recursive breadth-first approach:

1. **Fetch all properties** from the source class (no specific ordering needed)
2. **Create an ID mapping** (`oldToNewIdMap`) to track the relationship between old property IDs and new property IDs
3. **Process properties recursively** level by level:
   - Start with top-level properties (parent_id = NULL)
   - For each property at the current level:
     - Resolve its parent's new ID from the mapping (if it has a parent)
     - Insert the property with the updated `parent_id` reference
     - Store the mapping of old ID → new ID
     - Recursively process all children of this property
4. This ensures that parent properties are always processed before their children, maintaining proper hierarchy

## Code Changes
File: `/Users/kenji/Development/apiome/apiome-ui/lib/db/helper.ts`

Function: `copyClassesFromVersion(sourceVersionId: string, targetVersionId: string)`

The single batch INSERT query was replaced with:
- A SELECT query to fetch all properties with their hierarchy
- A loop that inserts properties one at a time while maintaining ID mappings
- Proper resolution of parent_id references using the mapping

## Testing
To test this fix:
1. Create a project and version with a class containing inline/nested properties
2. Create a new version and copy from the previous version
3. Verify that the nested property structure is maintained correctly
4. Check that parent_id references point to valid property IDs in the new class

## Impact
This fix ensures data integrity for complex class structures with nested properties when copying classes between versions, which is critical for version management functionality.

