# Dashboard Metrics Implementation

## Overview
The home dashboard page (`/ade/dashboard`) has been enhanced to display meaningful user-specific metrics and recent activity, providing users with a comprehensive overview of their schema projects.

## Changes Made

### 1. Database Helper Functions (`lib/db/helper.ts`)

#### `getDashboardStats(userId: string)`
Retrieves comprehensive statistics for a user across all their tenants:

**Metrics Returned:**
- `total_tenants` - Number of tenants the user belongs to
- `admin_tenants` - Number of tenants the user administers
- `total_projects` - Total projects in user's tenants
- `created_projects` - Projects created by the user
- `total_versions` - Total versions in user's projects
- `created_versions` - Versions created by the user
- `published_versions` - Count of published versions
- `total_classes` - Total classes across all versions
- `total_properties` - Total properties in user's projects
- `total_class_properties` - Property instances in classes
- `last_activity` - Timestamp of most recent activity

#### `getRecentActivity(userId: string, limit: number = 10)`
Fetches the user's recent actions across:
- Project creation
- Version creation
- Class creation
- Property creation

Each activity includes:
- Type (project, version, class, property)
- ID and name
- Description
- Creation timestamp
- Tenant name and slug

### 2. Dashboard Page Updates (`src/app/ade/dashboard/page.tsx`)

#### New Features:

**Stats Cards Display**
- Five metric cards showing key statistics
- Each card displays:
  - Primary metric (large number)
  - Subtitle with additional context
  - Icon with distinctive color
- Cards show:
  1. Tenants (with admin count)
  2. Projects (with created count)
  3. Versions (with published count)
  4. Classes (schema definitions)
  5. Properties (with class property count)

**Recent Activity Feed**
- Displays last 10 user activities
- Shows activity type with appropriate icon
- Displays activity name and description
- Shows tenant association via chip
- Relative time display (e.g., "2 hours ago")
- Empty state when no activity exists

**UI Improvements:**
- Skeleton loading states during data fetch
- Responsive grid layout
- Color-coded icons for different entity types
- Clean, modern Material-UI design

#### Helper Functions:
- `getActivityIcon()` - Returns icon based on activity type
- `getActivityLabel()` - Returns formatted label for activity type
- `formatTimeAgo()` - Converts timestamps to relative time strings

### 3. TypeScript Interfaces

```typescript
interface DashboardStats {
  total_tenants: number;
  admin_tenants: number;
  total_projects: number;
  created_projects: number;
  total_versions: number;
  created_versions: number;
  published_versions: number;
  total_classes: number;
  total_properties: number;
  total_class_properties: number;
  last_activity: string | null;
}

interface RecentActivity {
  type: 'project' | 'version' | 'class' | 'property';
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  tenant_name: string;
  tenant_slug: string;
}
```

## Database Queries

The implementation uses optimized SQL queries with:
- Subqueries for different metrics
- JOIN operations for related data
- Proper indexing (existing indexes are utilized)
- Soft delete awareness (`deleted_at IS NULL` checks)
- Tenant isolation (only shows data from user's tenants)

## Performance Considerations

1. **Single Query for Stats**: All statistics are fetched in one database query using subqueries
2. **UNION ALL for Activity**: Recent activity uses UNION ALL to combine different entity types
3. **Proper Indexes**: Leverages existing database indexes on:
   - `tenant_users.user_id`
   - `tenant_administrators.user_id`
   - `projects.creator_id`, `projects.tenant_id`
   - `versions.creator_id`, `versions.project_id`
   - `classes.version_id`
   - `properties.project_id`
   - `created_at` columns for chronological ordering

## User Experience

**On Load:**
1. Skeleton loaders display while fetching data
2. Statistics and activity load in parallel
3. Data displays once fetched

**Information Architecture:**
- Welcome message with user's name
- Five stat cards at the top for quick overview
- Quick action buttons for common tasks
- Recent activity feed on the right side

**Visual Design:**
- Color-coded icons for different entity types
- Consistent spacing and typography
- Responsive layout adapts to screen size
- Empty states provide guidance

## Testing Recommendations

1. **Test with different user roles:**
   - User with no activity
   - User with multiple tenants
   - Admin users
   - Regular members

2. **Test edge cases:**
   - New user with zero metrics
   - User with deleted projects/versions
   - User with only published versions
   - User with nested properties

3. **Performance testing:**
   - Load with users having large datasets
   - Monitor query execution times
   - Check for N+1 query issues

## Future Enhancements

Potential improvements for future iterations:

1. **Interactive Charts:**
   - Line chart showing activity over time
   - Pie chart for entity type distribution
   
2. **Filtering:**
   - Filter activity by type
   - Filter by tenant
   - Date range selection

3. **More Metrics:**
   - API key usage statistics
   - Collaboration metrics (shared projects)
   - Schema complexity metrics

4. **Real-time Updates:**
   - WebSocket integration for live updates
   - Notifications for important events

5. **Export Functionality:**
   - Download activity report
   - Generate usage summary

## Related Files

- `/Users/kenji/Development/apiome/apiome-ui/lib/db/helper.ts`
- `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/dashboard/page.tsx`

## Dependencies

- Material-UI components
- Next.js 16.0.0
- next-auth for session management
- PostgreSQL database

## Maintenance Notes

- Database queries should be reviewed if schema changes
- Add new metrics by extending `getDashboardStats()` query
- Activity types can be extended by adding new UNION clauses
- Icon mapping may need updates for new entity types

## Troubleshooting

### Fixed Issues

#### Ambiguous Column Reference Error
**Error**: `column reference "created_at" is ambiguous`

**Cause**: In the last activity subquery of `getDashboardStats()`, when selecting `created_at` from `apiome.classes` with a JOIN to `apiome.versions`, both tables have a `created_at` column, causing ambiguity.

**Fix**: Qualified the column reference with the table alias:
```sql
-- Before (ambiguous)
SELECT created_at FROM apiome.classes c
JOIN apiome.versions v ON c.version_id = v.id

-- After (fixed)
SELECT c.created_at FROM apiome.classes c
JOIN apiome.versions v ON c.version_id = v.id
```

**Location**: `/Users/kenji/Development/apiome/apiome-ui/lib/db/helper.ts`, line ~94

**Prevention**: Always qualify column names with table aliases when using JOINs, especially for common column names like `created_at`, `updated_at`, `id`, etc.

