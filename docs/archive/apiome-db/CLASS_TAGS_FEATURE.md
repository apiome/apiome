# Class Tags Feature

## Overview

The Class Tags feature allows users to organize and categorize classes within a project using customizable tags. Tags are project-scoped and can be applied to multiple classes, making it easier to filter, search, and understand the purpose of different classes in your schema.

**Note**: Tags are a canvas-only feature designed for internal organization. They are not exposed via public REST API endpoints and are managed entirely through the UI helper functions.

## Features

- **Tag Management**: Create, edit, and delete tags at the project level
- **Tag Assignment**: Assign multiple tags to each class
- **Visual Display**: Tags appear as color-coded chips on class nodes in the Studio canvas
- **Customizable Colors**: Choose from 7 predefined color themes for each tag
- **Tag Description**: Add optional descriptions to explain the purpose of each tag

## Database Schema

### Tables

#### `tags`
Stores tag definitions scoped to projects.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| project_id | UUID | Foreign key to projects table |
| name | VARCHAR(100) | Tag name (unique within project) |
| color | VARCHAR(50) | Color theme (default, primary, secondary, error, warning, info, success) |
| description | TEXT | Optional description |
| created_at | TIMESTAMP WITH TIME ZONE | Creation timestamp |
| updated_at | TIMESTAMP WITH TIME ZONE | Last update timestamp |

**Indexes**:
- `idx_tags_project_id` on `project_id`
- `idx_tags_name` on `name`
- `idx_tags_created_at` on `created_at`

**Constraints**:
- Unique constraint on `(project_id, name)`
- Foreign key to `projects(id)` with CASCADE delete

#### `class_tags`
Junction table linking classes to tags.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| class_id | UUID | Foreign key to classes table |
| tag_id | UUID | Foreign key to tags table |
| created_at | TIMESTAMP WITH TIME ZONE | Assignment timestamp |

**Indexes**:
- `idx_class_tags_class_id` on `class_id`
- `idx_class_tags_tag_id` on `tag_id`
- `idx_class_tags_created_at` on `created_at`

**Constraints**:
- Unique constraint on `(class_id, tag_id)`
- Foreign key to `classes(id)` with CASCADE delete
- Foreign key to `tags(id)` with CASCADE delete

## Python Database Layer

Tags are managed entirely through the Python database layer, which provides the following methods in `apiome-rest/src/app/database.py`:

### Tag Query Methods
- `get_tags_for_project(project_id)` - Get all tags for a project
- `get_tags_for_class(class_id)` - Get all tags assigned to a class
- `create_tag(project_id, name, color, description)` - Create a new tag
- `update_tag(tag_id, name, color, description)` - Update a tag
- `delete_tag(tag_id)` - Delete a tag (cascades to class assignments)
- `assign_tag_to_class(class_id, tag_id)` - Assign a tag to a class
- `remove_tag_from_class(class_id, tag_id)` - Remove a tag from a class

These methods are called by the UI helper functions in `apiome-ui/lib/db/helper.ts`.

## UI Components

### TagManager Component
**Location**: `apiome-ui/src/app/components/ade/studio/TagManager.tsx`

Dialog component for managing project tags.

**Props:**
- `open`: boolean - Dialog open state
- `onClose`: () => void - Close handler
- `projectId`: string - Current project ID
- `tags`: Tag[] - Array of project tags
- `onTagsChanged`: () => void - Callback when tags are modified

**Features:**
- Create new tags with name, color, and description
- Edit existing tags
- Delete tags (with confirmation)
- Visual color selector with chip preview

### ClassEditDialog Updates
**Location**: `apiome-ui/src/app/components/ade/studio/ClassEditDialog.tsx`

Added tag selection to the class edit dialog.

**New Props:**
- `projectId?`: string - Current project ID
- `projectTags?`: any[] - Array of available project tags

**Features:**
- Multi-select autocomplete for tag assignment
- Color-coded tag chips
- Automatically syncs tag assignments on save

### ClassNode Updates
**Location**: `apiome-ui/src/app/components/ade/studio/ClassNode.tsx`

Added tag display to class nodes on the canvas.

**New Data Field:**
- `tags?`: Array<{ id: string; tag_name: string; tag_color: string }> - Tags assigned to the class

**Features:**
- Displays tags as small color-coded chips below the class description
- Uses predefined color mapping for consistent visual appearance

## Helper Functions

### UI Database Helpers
**Location**: `apiome-ui/lib/db/helper.ts`

#### Tag Management
- `getTagsForProject(projectId: string)` - Get all tags for a project
- `getTagsForClass(classId: string)` - Get all tags assigned to a class
- `createTag(projectId, name, color, description)` - Create a new tag
- `updateTag(tagId, name?, color?, description?)` - Update a tag
- `deleteTag(tagId)` - Delete a tag

#### Tag Assignment
- `assignTagToClass(classId, tagId)` - Assign a tag to a class
- `removeTagFromClass(classId, tagId)` - Remove a tag from a class

All functions return JSON-stringified responses with `success` boolean and data or error message.

## Usage Example

### 1. Create Tags for a Project

```typescript
import { createTag } from '@/lib/db/helper';

// Create a "Domain Model" tag
const result = await createTag(
  projectId,
  'Domain Model',
  'primary',
  'Core business domain entities'
);

const response = JSON.parse(result);
if (response.success) {
  console.log('Tag created:', response.tag);
}
```

### 2. Assign Tags to a Class

```typescript
import { assignTagToClass } from '@/lib/db/helper';

// Assign the "Domain Model" tag to a User class
const result = await assignTagToClass(userClassId, domainModelTagId);

const response = JSON.parse(result);
if (response.success) {
  console.log('Tag assigned:', response.class_tag);
}
```

### 3. Display Tags in Studio

Tags are automatically loaded and displayed when:
1. Classes are fetched for the studio canvas
2. The ClassEditDialog is opened for a class
3. Tags are modified through the TagManager

The studio page should load project tags and class tags, then pass them to the relevant components:

```typescript
// In studio page.tsx
const [projectTags, setProjectTags] = useState([]);

// Load tags
useEffect(() => {
  const loadTags = async () => {
    const result = await getTagsForProject(projectId);
    setProjectTags(JSON.parse(result));
  };
  loadTags();
}, [projectId]);

// When creating nodes, include tags
const nodes = classes.map(cls => ({
  ...cls,
  data: {
    ...cls.data,
    tags: classTags[cls.id] || []
  }
}));

// Pass to ClassEditDialog
<ClassEditDialog
  projectId={projectId}
  projectTags={projectTags}
  // ... other props
/>
```

## Migration

To add the tags feature to an existing Apiome installation:

1. Run the migration script:
```bash
psql -U your_user -d your_database -f apiome-db/scripts/20251207-120000.sql
```

2. Restart the REST API server to load new endpoints
3. Refresh the UI to use updated components

## Future Enhancements

Potential improvements for the tags feature:

1. **Tag Filtering**: Add a filter toolbar in the Studio canvas to show/hide classes by selected tags
2. **Tag Colors**: Support custom hex colors instead of just predefined themes
3. **Tag Analytics**: Show tag usage statistics (number of classes per tag)
4. **Bulk Tag Operations**: Assign/remove tags from multiple classes at once
5. **Tag Import/Export**: Include tags in OpenAPI/project import/export
6. **Tag Search**: Search classes by tag name in the project
7. **Tag Hierarchies**: Support parent-child tag relationships
8. **Tag Templates**: Predefined tag sets for common use cases (e.g., REST CRUD, DDD patterns)

## Notes

- Tags are project-scoped, not version-scoped. This means tags are shared across all versions of a project.
- Deleting a tag automatically removes all assignments from classes (CASCADE delete).
- Tag names must be unique within a project.
- Tag colors are stored as string values that map to Material-UI color variants or can be extended to support hex colors.

