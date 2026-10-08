# Visibility Toggle Feature for Published Versions

## Overview
Added the ability to change the visibility of published versions between "public" and "private" directly from the Published Versions dashboard page.

## Changes Made

### 1. Database Helper Function (`lib/db/helper.ts`)

Added `updateVersionVisibility()` function:

```typescript
export async function updateVersionVisibility(versionRecordId: string, visibility: 'public' | 'private')
```

**Features:**
- Updates the `visibility` column in `apiome.versions` table
- Only updates published versions (`published = true`)
- Excludes soft-deleted records
- Updates the `updated_at` timestamp
- Returns success/error response

**SQL:**
```sql
UPDATE apiome.versions 
SET visibility = $1, updated_at = CURRENT_TIMESTAMP
WHERE id = $2 AND deleted_at IS NULL AND published = true
```

### 2. UI Updates (`src/app/ade/dashboard/published/page.tsx`)

#### Added Informational Banner
- Blue informational box at the top of the page
- Explains the difference between public and private visibility:
  - **Public versions**: Globally visible, accessible without authentication
  - **Private versions**: Require an API Key to view
- Uses Info icon from lucide-react
- Styled for both light and dark modes

#### Made Visibility Chips Clickable
- Visibility chips are now interactive buttons
- Click to toggle between public and private
- Visual feedback:
  - Tooltip shows "Click to change to [opposite visibility]"
  - Hover effects (darker background on hover)
  - Disabled state while change is in progress
  - Cursor changes to pointer on hover

#### Visual Design
**Public Chip:**
- Green background (`bg-green-100` / `dark:bg-green-900/40`)
- Green text (`text-green-800` / `dark:text-green-200`)
- Globe icon
- Hover: Darker green (`hover:bg-green-200` / `dark:hover:bg-green-900/60`)

**Private Chip:**
- Gray background (`bg-gray-100` / `dark:bg-gray-700`)
- Gray text (`text-gray-800` / `dark:text-gray-200`)
- Lock icon
- Hover: Darker gray (`hover:bg-gray-200` / `dark:hover:bg-gray-600`)

#### State Management
- Added `changingVisibility` state to track which version is being updated
- Prevents multiple simultaneous updates
- Disables chip button while update is in progress
- Updates local state immediately on success for instant UI feedback

#### Error Handling
- Catches errors during update
- Shows alert with error message
- Console logs errors for debugging
- Resets loading state in finally block

### 3. Enhanced "No Tenant Selected" Message

Improved UX when no tenant is selected:
- Yellow warning box with better styling
- Lock icon for visual emphasis
- Clear explanation that publications need a tenant
- Direct link to Tenants page
- Styled button for navigation

## User Experience Flow

1. User navigates to Published Versions page
2. Sees informational banner explaining visibility types
3. Views table of published versions with visibility chips
4. Hovers over a visibility chip
   - Tooltip shows "Click to change to [opposite]"
   - Chip background darkens
5. Clicks chip to toggle visibility
   - Chip becomes disabled (prevents double-click)
   - Request sent to server
   - On success: Chip instantly updates to show new visibility
   - On error: Alert message shown
6. Can toggle back and forth as needed

## Technical Details

### API Request Flow
```
UI (page.tsx)
  → handleToggleVisibility()
  → updateVersionVisibility(versionId, newVisibility)
  → lib/db/helper.ts
  → Database UPDATE query
  → Response back to UI
  → Local state update
```

### State Updates
- Optimistic UI update after successful response
- Uses array map to update specific version:
```typescript
setVersions(versions.map(v => 
  v.id === version.id 
    ? { ...v, visibility: newVisibility }
    : v
));
```

### Loading State
- `changingVisibility` tracks the ID of version being updated
- Chip is disabled when `changingVisibility === version.id`
- Prevents race conditions and duplicate requests

## Accessibility

- Tooltips provide context for action
- Disabled state prevents interaction during update
- Visual feedback on hover and click
- Keyboard accessible (MUI Chip supports keyboard navigation)
- ARIA labels from Tooltip component

## Dark Mode Support

All elements fully support dark mode:
- Informational banner: Blue tones adapt to dark theme
- Chips: Appropriate contrast in both modes
- Hover states: Visible in both light and dark
- Tooltips: MUI handles dark mode automatically

## Security Considerations

- Only published versions can have visibility changed
- Soft-deleted versions are excluded
- Version ID must exist and be published
- No direct SQL injection risk (parameterized queries)
- Tenant isolation maintained (visibility is per-version)

## Search/Filter Feature

Added ability to filter published versions by:
- Project name
- Version ID
- Description
- Tenant name (if multiple tenants)

### Implementation Details

**Search Field:**
- Positioned below the informational banner
- Full-width TextField with search icon
- Real-time filtering as user types
- Placeholder: "Search by project name, version, or description..."
- Styled for both light and dark modes

**Filter Logic:**
- Case-insensitive search
- Matches any part of the searchable fields
- Shows "No Matching Versions" state when no results
- Maintains original data (non-destructive filter)

**User Feedback:**
- Count display shows: "Showing X of Y published versions"
- "(filtered by search)" indicator when filter is active
- Empty state with Search icon when no matches found
- Search field clears easily (standard TextField behavior)

## Future Enhancements

1. **Bulk Visibility Toggle**: Select multiple versions and change visibility at once
2. **Visibility History**: Track when and who changed visibility
3. **Confirmation Dialog**: Optional confirmation before changing public to private
4. **Visibility Rules**: Set default visibility for new publications
5. **Audit Log**: Record all visibility changes for compliance
6. **API Endpoint**: Allow visibility changes via API (with authentication)
7. **Advanced Filters**: Filter by visibility type (public/private), date range, or creator
8. **Save Filter Presets**: Save commonly used filter combinations

## Testing Checklist

- [ ] Click public chip - changes to private
- [ ] Click private chip - changes to public
- [ ] Tooltip shows correct text before click
- [ ] Chip is disabled during update
- [ ] Error handling works (test with invalid ID)
- [ ] Multiple rapid clicks don't cause issues
- [ ] Dark mode styling is correct
- [ ] Informational banner displays properly
- [ ] Page refreshes show correct visibility
- [ ] Database visibility column updates correctly
- [ ] Hover effects work in both light and dark mode

