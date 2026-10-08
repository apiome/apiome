# Class Tags - Quick Start Guide

## 1. Database Setup

Run the migration script:
```bash
psql -U your_user -d apiome -f apiome-db/scripts/20251207-120000.sql
```

## 2. Create Your First Tag

**Note**: Tags are canvas-only and managed entirely through the UI. There are no public REST endpoints.

### Via UI:
1. Open the Studio for your project/version
2. Click "Manage Tags" button
3. Click "Create New Tag"
4. Fill in name, color, and description
5. Click "Create"

## 3. Assign Tags to Classes

### Steps:
1. Double-click a class node in the Studio canvas
2. In the Edit dialog, find the "Tags" section
3. Select tags from the dropdown
4. Click "Save"

## 4. View Tagged Classes

Tags appear as colored chips on class nodes in the Studio canvas, just below the class description.

## Common Tag Examples

- **Domain Model** (primary) - Core business entities
- **API Resource** (info) - REST API endpoints
- **Authentication** (warning) - Auth-related classes
- **Infrastructure** (secondary) - Technical/utility classes
- **Deprecated** (error) - Classes marked for removal

## Available Colors
- default (gray)
- primary (blue-purple)
- secondary (purple)
- error (red)
- warning (orange)
- info (blue)
- success (green)

## Integration Code Snippet

```typescript
import { 
  getTagsForProject, 
  getTagsForClass, 
  assignTagToClass 
} from '@/lib/db/helper';

// Load project tags
const tagsJson = await getTagsForProject(projectId);
const projectTags = JSON.parse(tagsJson);

// Load class tags
const classTagsJson = await getTagsForClass(classId);
const classTags = JSON.parse(classTagsJson);

// Assign tag to class
const result = await assignTagToClass(classId, tagId);
const response = JSON.parse(result);
if (response.success) {
  console.log('Tag assigned!');
}
```

## Troubleshooting

**Tags not appearing?**
- Verify migration was run successfully
- Check that REST API server was restarted
- Ensure tags are loaded and passed to ClassNode components

**Can't create duplicate tag name?**
- Tag names must be unique within a project
- Use a different name or update the existing tag

**Tag deletions not reflecting?**
- Tag deletions cascade to remove all class assignments
- Refresh the page after deleting a tag

For detailed documentation, see: `apiome-db/docs/CLASS_TAGS_FEATURE.md`

