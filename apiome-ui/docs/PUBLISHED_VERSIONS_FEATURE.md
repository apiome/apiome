# Published Versions Dashboard Feature

## Overview
A new dashboard view that displays all published (locked) versions from the `apiome.versions` table, showing their visibility settings and access URLs.

## Implementation

### 1. Database Helper Function
**File**: `lib/db/helper.ts`

Added `getPublishedVersionsForTenant()` function that:
- Joins `versions`, `projects`, `tenants`, and `users` tables
- Filters for published versions (`published = true`)
- Returns comprehensive data including:
  - Version details (id, version_id, description, visibility, published_at)
  - Project information (project_id, project_name, project_slug)
  - Tenant information (tenant_id, tenant_name, tenant_slug)
  - Creator information (creator_name, creator_email)
- Excludes soft-deleted records
- Orders by published date (newest first)

```typescript
export async function getPublishedVersionsForTenant(tenantId: string)
```

### 2. Published Versions Page
**File**: `src/app/ade/dashboard/published/page.tsx`

Features:
- **Table Display**: Shows published versions in a clean, responsive table
- **Project/Version Info**: Displays project name, version ID (with lock icon), and description
- **Visibility Badge**: 
  - Green "Public" badge with globe icon for public versions
  - Gray "Private" badge with lock icon for private versions
- **Access URL**: Displays the API URL path in the format:
  ```
  {tenant-slug}/{project-slug}/{version-id}
  ```
- **Full URL Construction**: Constructs complete API URL:
  ```
  {origin}/api/{tenant-slug}/{project-slug}/{version-id}
  ```
- **Actions**:
  - Copy URL to clipboard (with visual feedback)
  - Open URL in new tab
- **Published Date**: Shows when the version was published and by whom
- **Dark Mode Support**: Fully styled for both light and dark themes

### 3. Navigation Integration
**File**: `src/app/components/ade/dashboard/DashboardSideNav.tsx`

Added "Published" menu item to the Specifications section:
- Icon: Eye (from lucide-react)
- Route: `/ade/dashboard/published`
- Positioned after "Versions"

## URL Format

The access URL follows the pattern:
```
/api/{tenant-slug}/{project-slug}/{version-id}
```

Example:
```
/api/acme-corp/customer-api/1.0.0
```

This allows for clean, hierarchical API endpoints that include:
1. **Tenant isolation**: Each tenant has their own namespace
2. **Project organization**: Projects are grouped under tenants
3. **Version specification**: Specific version of the API specification

## Features

### Empty States
1. **No Tenant Selected**: Prompts user to select a tenant
2. **No Published Versions**: Friendly message encouraging users to publish versions

### Loading States
- Shows loading indicator while fetching data
- Prevents interaction during data loading

### User Feedback
- Copy URL shows temporary "Copied!" tooltip
- Hover states on all interactive elements
- Clear visual hierarchy

### Accessibility
- Proper semantic HTML (table structure)
- Tooltips on action buttons
- Keyboard-accessible controls
- ARIA labels where needed

## Data Flow

1. User navigates to `/ade/dashboard/published`
2. Page component reads `current_tenant_id` from session
3. Calls `getPublishedVersionsForTenant(tenantId)`
4. Database query joins versions, projects, tenants, and users
5. Results are displayed in the table
6. User can copy or open URLs for API access

## Database Schema Dependencies

### Required Tables
- `apiome.versions` - Version records with `published` and `visibility` columns
- `apiome.projects` - Project records with `slug` column
- `apiome.tenants` - Tenant records with `slug` column
- `apiome.users` - User records for creator information

### Required Columns
- `versions.published` (boolean) - Marks version as published/locked
- `versions.visibility` (enum: 'public' | 'private') - Access control
- `versions.published_at` (timestamp) - When version was published
- `projects.slug` (varchar) - URL-friendly project identifier
- `tenants.slug` (varchar) - URL-friendly tenant identifier

## Styling

### Colors & Themes
- Light mode: Clean whites and grays
- Dark mode: Dark grays with proper contrast
- Accent colors: Blue for actions, green for public, gray for private
- Border colors adapt to theme

### Typography
- Headers: Bold, larger text
- Body: Standard readable size
- Code/URLs: Monospace font with background highlight
- Helper text: Smaller, muted color

### Layout
- Responsive table design
- Fixed header for easy scanning
- Proper spacing and padding
- Hover effects for interactivity

## Future Enhancements

1. **Filtering**: Add filters for visibility, project, or date range
2. **Search**: Search by project name or version ID
3. **Sorting**: Allow sorting by any column
4. **Bulk Actions**: Select multiple versions for batch operations
5. **Analytics**: Show usage statistics for each published version
6. **Version History**: Link to version comparison or changelog
7. **QR Code**: Generate QR codes for mobile access to API URLs
8. **Visibility Toggle**: Allow changing visibility from this view (if not locked)
9. **Export**: Export list as CSV or JSON

## Testing Checklist

- [ ] View loads with valid tenant selected
- [ ] Empty state shows when no published versions exist
- [ ] Table displays all published versions correctly
- [ ] Visibility badges show correct colors and icons
- [ ] Access URLs are formatted correctly
- [ ] Copy URL function works and shows feedback
- [ ] Open URL function opens in new tab
- [ ] Published dates format correctly
- [ ] Creator names display correctly
- [ ] Dark mode styles work properly
- [ ] Responsive design works on mobile
- [ ] Navigation highlight works on active page
- [ ] Loading state shows while fetching data
- [ ] Error handling works for failed API calls

## Security Considerations

- Only shows versions for the current tenant (tenant isolation)
- Respects soft-delete flags (deleted records not shown)
- Does not expose internal IDs in URLs (uses slugs)
- Full URLs only constructed client-side (not stored in DB)
- Visibility flag can control access at API level

## Performance

- Single database query with JOINs (efficient)
- No N+1 query problems
- Indexes on `published`, `deleted_at`, and foreign keys
- Minimal client-side processing
- Fast table rendering with React

