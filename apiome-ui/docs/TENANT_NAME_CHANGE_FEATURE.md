# Tenant Name and Slug Change Feature

## Overview
Administrators can now edit tenant names, slugs, and descriptions through the Tenants dashboard. The slug can be manually edited or will be auto-generated from the tenant name. When changing either the tenant name or slug, the system displays a comprehensive warning about potential impacts on published OpenAPI specifications.

## What Was Added

### Backend Changes (`lib/db/helper.ts`)
- **New Function: `updateTenant(tenantId, name, description, customSlug?)`**
  - Updates tenant name, slug, and description
  - Accepts optional `customSlug` parameter for manual slug control
  - If no custom slug provided, automatically generates slug from name
  - Validates that tenant name and slug are not empty
  - Validates slug format (lowercase alphanumeric and dashes only)
  - Checks for slug uniqueness (excluding the current tenant)
  - Returns the new slug in the response for confirmation
  - Updates the `updated_at` timestamp

### Frontend Changes (`src/app/ade/dashboard/tenants/page.tsx`)

#### New State Variables
- `showEditTenantModal`: Controls visibility of the edit dialog
- `editingTenant`: Stores the tenant being edited
- `tenantName`: Current value of tenant name input
- `tenantSlug`: Current value of tenant slug input
- `tenantDescription`: Current value of description input

#### New Functions
- **`handleEditTenant(tenant)`**: Opens the edit modal and populates it with current tenant data
- **`handleEditTenantSubmit()`**: Handles the submission of tenant changes
  - Validates tenant name is not empty
  - Detects if the name has changed
  - Shows a warning dialog if the name is changing (with slug impact warning)
  - Calls `updateTenant` API
  - Displays success message with new slug if name changed
  - Refreshes tenant data

#### UI Changes
- Added **Edit button** (pencil icon) in the Actions column for admin users
- Added **Edit Tenant Modal** with:
  - Tenant Name field (required)
  - Tenant Slug field (required, editable, auto-lowercased)
  - Description field (multiline, optional)
  - Information note about slug usage in URLs
  - Cancel and Save Changes buttons
  - Error message display
  - Helper text showing slug format requirements

#### Warning Dialog
**Only appears when the tenant slug changes.** When slug is modified, users see a comprehensive warning dialog that includes:
- List of changes being made (name and/or slug, showing old → new values)
- Yellow alert box with warning icon
- Clear explanation that changing the slug will affect published OpenAPI spec URLs
- Warning to update any external references or documentation
- Confirmation buttons ("Change Slug" and "Cancel")

**Note:** Changing only the tenant name (without changing the slug) does not trigger a warning, allowing seamless tenant renaming.

## User Flow

1. **Access**: Admin navigates to Tenants dashboard (`/ade/dashboard/tenants`)
2. **Initiate Edit**: Click the pencil icon next to a tenant (only visible to tenant administrators)
3. **Edit Form**: Modal opens with current tenant name, slug, and description
4. **Make Changes**: User modifies:
   - Tenant name (required)
   - Tenant slug (required, editable, lowercase alphanumeric and dashes only)
   - Description (optional)
5. **Submit**: User clicks "Save Changes"
6. **Slug Change Warning** (only if slug changed):
   - Warning dialog appears showing which fields changed
   - Lists old and new values for the slug (and name if also changed)
   - Warns about slug impact on OpenAPI spec URLs
   - User must confirm with "Change Slug" or cancel
   - **If only name changed:** No warning, updates immediately
7. **Success**: Tenant is updated
   - If slug changed: success message displays the new slug
   - If only name/description changed: silent success
8. **Data Refresh**: Tenant list automatically refreshes to show changes

## Technical Details

### Slug Generation/Validation
- **Manual Mode**: User can directly edit the slug field
  - Automatically converted to lowercase on input
  - Must match format: `^[a-z0-9-]+$` (lowercase letters, numbers, and dashes only)
- **Auto-generation** (if custom slug not provided):
  - Converts name to lowercase
  - Removes special characters (keeps only alphanumeric and spaces)
  - Replaces spaces/underscores with hyphens
  - Removes leading/trailing hyphens
  - Example: "My Company Inc." → "my-company-inc"

### Validation
- **Name**: Cannot be empty
- **Slug**: Cannot be empty
- **Slug Format**: Must contain only lowercase letters, numbers, and dashes
- **Slug Uniqueness**: Checks database to ensure no other tenant has the same slug

### Error Handling
- Displays validation errors in the modal
- Handles database constraint violations (duplicate slugs)
- Shows user-friendly error messages

## Impact on Published OpenAPI Specs

⚠️ **Important**: When a tenant's slug changes, any published OpenAPI specification URLs that include the tenant slug will be affected. For example:

**Before**: `https://api.example.com/specs/{old-slug}/project-name/1.0.0`
**After**: `https://api.example.com/specs/{new-slug}/project-name/1.0.0`

This is why the warning dialog is shown to ensure administrators understand the potential impact before proceeding with the name change.

## Database Schema
The feature uses the existing `apiome.tenants` table with columns:
- `id` (UUID, primary key)
- `name` (text)
- `slug` (text, unique)
- `description` (text, nullable)
- `updated_at` (timestamp with timezone)

## Security
- Only tenant administrators can edit tenant information
- Validation occurs on both client and server side
- Uses parameterized queries to prevent SQL injection

