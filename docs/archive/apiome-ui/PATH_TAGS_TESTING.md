# Path Tags Feature - Testing & Verification Guide

## Overview

Path tags enable operational grouping of API paths using project-defined tags. This feature allows organizing paths by domain, team, status, visibility, or any custom categorization.

## Database Schema

### Table: `apiome.path_tags`

Junction table linking API paths to project tags.

```sql
CREATE TABLE path_tags (
    id UUID PRIMARY KEY,
    path_id UUID REFERENCES api_paths(id) ON DELETE CASCADE,
    tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT path_tags_unique UNIQUE (path_id, tag_id)
);
```

**Key Features**:
- Many-to-many relationship between paths and tags
- Unique constraint prevents duplicate tag assignments
- Cascade delete: removing a path removes its tag assignments
- Cascade delete: removing a tag removes all its path assignments

## Migration & Setup

### Step 1: Apply Database Migration

```bash
# Navigate to the database scripts directory
cd /Users/kenji/Development/apiome/apiome-db/scripts

# Apply the migration (using your database connection method)
psql -U your_user -d apiome -f 20260101-120000.sql
```

### Step 2: Verify Schema

```sql
-- Check if table exists
\dt apiome.path_tags

-- Verify structure
\d apiome.path_tags

-- Check indices
\di apiome.path_tags*
```

### Step 3: Run Automated Tests

```bash
# Run the comprehensive test suite
psql -U your_user -d apiome -f /Users/kenji/Development/apiome/apiome-ui/tests/path-tags-test.sql
```

**Expected Output**:
```
NOTICE:  TEST 1: Assigning tags to path...
NOTICE:    ✓ Tags assigned successfully
NOTICE:  TEST 2: Querying tags for path...
NOTICE:    ✓ Tags query successful
NOTICE:  TEST 3: Testing unique constraint...
NOTICE:    ✓ Unique constraint working - duplicate prevented
NOTICE:  TEST 4: Testing tag replacement (transaction)...
NOTICE:    ✓ Tag replacement successful
NOTICE:  TEST 5: Removing a single tag...
NOTICE:    ✓ Tag removal successful
NOTICE:  TEST 6: Testing cascade delete...
NOTICE:    ✓ Cascade delete working correctly
```

## Code Implementation

### Database Functions (helper-paths.ts)

#### Get Tags for Path
```typescript
export async function getTagsForPath(pathId: string)
// Returns: Array of tag objects with metadata
```

#### Assign Tag to Path
```typescript
export async function assignTagToPath(pathId: string, tagId: string)
// Returns: Success response with path_tag details
```

#### Remove Tag from Path
```typescript
export async function removeTagFromPath(pathId: string, tagId: string)
// Returns: Success/error response
```

#### Set All Tags (Transactional Replace)
```typescript
export async function setPathTags(pathId: string, tagIds: string[])
// Returns: Updated list of tags
// Uses transaction: DELETE all + INSERT new
```

### Server Actions (actions.ts)

All functions exposed as server actions:
- `getTagsForPathAction(pathId)`
- `assignTagToPathAction(pathId, tagId)`
- `removeTagFromPathAction(pathId, tagId)`
- `setPathTagsAction(pathId, tagIds[])`

### UI Components

#### PropertiesPanel (Line 353)
Saves tags when user clicks Save:
```typescript
await setPathTagsAction(selectedNode.data.dbPathId, selectedTags);
```

#### PathsCanvas (Line 70)
Loads tags when paths are loaded:
```typescript
const tagsResult = await getTagsForPathAction(path.id);
const pathTags = JSON.parse(tagsResult);
pathTagIds = pathTags.map((pt: any) => pt.tag_id);
```

## Manual Testing Procedure

### 1. Create Test Tags

```sql
-- Create tags in your project
INSERT INTO apiome.tags (project_id, name, color, description)
VALUES 
    ('your-project-id', 'User Management', '#3B82F6', 'User domain operations'),
    ('your-project-id', 'Public API', '#10B981', 'Publicly accessible endpoints'),
    ('your-project-id', 'Beta', '#F59E0B', 'Beta features');
```

### 2. Test in UI

1. **Open Paths Canvas**
   - Navigate to Studio → Paths
   - Select a version

2. **Create or Select a Path**
   - Drag a path node to canvas or select existing path
   - Path properties panel opens

3. **Assign Tags**
   - Click on Tags dropdown
   - Select one or more tags
   - Click "Save Changes"

4. **Verify Persistence**
   - Refresh the page
   - Path should still have tags assigned
   - Tags should display as color-coded badges

5. **Verify Database**
   ```sql
   SELECT 
       ap.path,
       STRING_AGG(t.name, ', ') as tags
   FROM apiome.api_paths ap
   JOIN apiome.path_tags pt ON ap.id = pt.path_id
   JOIN apiome.tags t ON pt.tag_id = t.id
   WHERE ap.deleted_at IS NULL
   GROUP BY ap.id, ap.path;
   ```

### 3. Test Tag Removal

1. Select a path with tags
2. Deselect tags in the dropdown
3. Click "Save Changes"
4. Verify tags are removed in UI and database

### 4. Test Multiple Paths with Same Tag

1. Assign the same tag to multiple paths
2. Verify each path-tag relationship is unique
3. Query grouped paths by tag:
   ```sql
   SELECT 
       t.name as tag,
       COUNT(pt.path_id) as path_count,
       STRING_AGG(ap.path, ', ' ORDER BY ap.path) as paths
   FROM apiome.tags t
   JOIN apiome.path_tags pt ON t.id = pt.tag_id
   JOIN apiome.api_paths ap ON pt.path_id = ap.id
   WHERE ap.deleted_at IS NULL
   GROUP BY t.id, t.name
   ORDER BY path_count DESC;
   ```

## Common Use Cases

### Operational Grouping Examples

**By Domain**:
- "User Management" → /users, /users/{id}, /users/{id}/profile
- "Payment Processing" → /payments, /payments/{id}, /billing
- "Reporting" → /reports, /analytics, /exports

**By Team Ownership**:
- "Team A" → Endpoints owned by Team A
- "Team B" → Endpoints owned by Team B
- "Shared" → Endpoints shared across teams

**By Status**:
- "Beta" → Endpoints in beta testing
- "Stable" → Production-ready endpoints
- "Deprecated" → Endpoints being phased out

**By Visibility**:
- "Public API" → Publicly documented endpoints
- "Internal" → Internal-only endpoints
- "Partner" → Partner-accessible endpoints

## Troubleshooting

### Tags Not Saving

**Check**:
1. Verify `path_tags` table exists: `\dt apiome.path_tags`
2. Check database permissions: `GRANT SELECT, INSERT, DELETE ON path_tags TO apiome_app`
3. Verify path has `dbPathId` in node data
4. Check browser console for errors
5. Verify `setPathTagsAction` is being called (check network tab)

### Tags Not Loading

**Check**:
1. Verify tags exist in database: `SELECT * FROM apiome.path_tags WHERE path_id = 'your-path-id'`
2. Check `getTagsForPathAction` is being called during path load
3. Verify foreign keys are valid (path_id and tag_id exist)
4. Check browser console for parsing errors

### Duplicate Tag Error

**Expected Behavior**: 
- The unique constraint `path_tags_unique` prevents duplicate assignments
- `ON CONFLICT DO NOTHING` in assign function handles this gracefully

### Cascade Delete Not Working

**Verify**:
```sql
-- Check foreign key constraints
SELECT
    tc.constraint_name, 
    tc.table_name, 
    kcu.column_name,
    ccu.table_name AS foreign_table_name,
    ccu.column_name AS foreign_column_name,
    rc.delete_rule
FROM information_schema.table_constraints AS tc 
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.referential_constraints AS rc
    ON rc.constraint_name = tc.constraint_name
WHERE tc.table_schema = 'apiome'
    AND tc.table_name = 'path_tags'
    AND tc.constraint_type = 'FOREIGN KEY';
```

## Performance Considerations

### Indices

Three indices created for optimal performance:
- `idx_path_tags_path_id` - Fast lookup of tags for a path
- `idx_path_tags_tag_id` - Fast lookup of paths for a tag
- `idx_path_tags_created_at` - Audit trail queries

### Query Optimization

**Good** - Uses index:
```sql
SELECT * FROM path_tags WHERE path_id = 'uuid';
```

**Good** - Uses index:
```sql
SELECT * FROM path_tags WHERE tag_id = 'uuid';
```

**Optimal** - Join with denormalized data:
```sql
SELECT ap.*, STRING_AGG(t.name, ', ') as tag_names
FROM api_paths ap
LEFT JOIN path_tags pt ON ap.id = pt.path_id
LEFT JOIN tags t ON pt.tag_id = t.id
GROUP BY ap.id;
```

## Files Modified/Created

### Database
- `apiome-db/scripts/20260101-120000.sql` - Migration script
- `apiome-ui/tests/path-tags-test.sql` - Test suite

### Backend  
- `apiome-ui/lib/db/helper-paths.ts` - Database functions
- `apiome-ui/src/app/ade/studio/paths/actions.ts` - Server actions

### Frontend
- `apiome-ui/src/app/ade/studio/paths/components/PropertiesPanel.tsx` - Save tags
- `apiome-ui/src/app/ade/studio/paths/components/PathsCanvas.tsx` - Load tags

### Documentation
- `apiome-ui/public/WHATS_NEW.md` - Feature announcement
- This README

## Next Steps

1. Apply the database migration
2. Run the test suite
3. Restart the application
4. Test in the UI
5. Verify database persistence

## Support

If you encounter issues:
1. Check the test output for failures
2. Verify database schema matches expected structure
3. Check browser console for JavaScript errors
4. Verify network requests in browser DevTools
5. Check server logs for database errors

