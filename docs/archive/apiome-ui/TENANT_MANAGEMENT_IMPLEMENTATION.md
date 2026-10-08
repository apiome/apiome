# Tenant Management Implementation Guide

## Overview

A complete tenant management system has been implemented for the admin dashboard, allowing administrators to:
- Create new tenants
- Manage tenant details and status
- Assign users to tenants
- Designate tenant administrators
- View tenant statistics and user assignments

## Features

### 📊 Tenant Management
- **Create Tenants**: Create new organizational tenants with name, slug, and description
- **View All Tenants**: List all tenants with user/admin counts
- **Enable/Disable Tenants**: Toggle tenant active status
- **Delete Tenants**: Soft delete tenants

### 👥 User Assignment
- **Add Users**: Assign users to tenants
- **Remove Users**: Remove users from tenants
- **View Available Users**: See users not yet assigned to a tenant

### 🛡️ Administrator Management
- **Make Admin**: Promote tenant users to administrators
- **Remove Admin**: Demote administrators back to regular users
- **Admin Badges**: Visual indicators for admin status

## Architecture

### Server-Side Functions (admin-helper.ts)

All tenant operations use server-side functions:

```typescript
// Tenant CRUD
createTenant(name, description, slug, enabled)
updateTenant(tenantId, updates)
deleteTenant(tenantId)
getAllTenants()
getTenantStats()

// User Assignment
addUserToTenant(tenantId, userId)
removeUserFromTenant(tenantId, userId)
getTenantUsers(tenantId)
getUsersNotInTenant(tenantId)

// Administrator Management
addTenantAdministrator(tenantId, userId)
removeTenantAdministrator(tenantId, userId)
```

## Database Schema

### apiome.tenants
```sql
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    slug VARCHAR(255) NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### apiome.tenant_users
```sql
CREATE TABLE tenant_users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, user_id)
);
```

### apiome.tenant_administrators
```sql
CREATE TABLE tenant_administrators (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, user_id)
);
```

## UI Components

### Main Layout

```
┌─────────────────────────────────────────────────────┐
│  Tenant Management         [Create Tenant Button]  │
├──────────────────────┬──────────────────────────────┤
│  Statistics Cards    │                              │
│  (4 cards)           │                              │
├──────────────────────┴──────────────────────────────┤
│  Tenants List        │  Tenant Users                │
│  ┌────────────────┐  │  ┌────────────────────────┐  │
│  │ Tenant 1       │  │  │ User 1  [Admin] [×]   │  │
│  │ - 5 users      │  │  │ User 2         [+] [×] │  │
│  │ - 2 admins     │  │  │                        │  │
│  ├────────────────┤  │  └────────────────────────┘  │
│  │ Tenant 2       │  │                              │
│  └────────────────┘  │  [Add User Button]           │
└──────────────────────┴──────────────────────────────┘
```

### Features

1. **Statistics Dashboard**
   - Total tenants count
   - Total users across all tenants
   - Total administrators
   - Active tenants count

2. **Tenants List (Left Panel)**
   - List all tenants
   - Show user/admin counts
   - Enable/disable toggle
   - Delete button
   - Click to select and view users

3. **Tenant Users (Right Panel)**
   - Shows users for selected tenant
   - Admin badge for administrators
   - Toggle admin status button
   - Remove user button
   - Add user dialog

## User Flows

### Creating a Tenant

1. Click **"Create Tenant"** button
2. Fill in form:
   - **Name**: Display name (e.g., "Acme Corporation")
   - **Slug**: URL-friendly identifier (auto-generated, e.g., "acme-corporation")
   - **Description**: Optional description
3. Click **"Create Tenant"**
4. Tenant appears in list

### Assigning Users to Tenant

1. Select a tenant from the list
2. Click **"Add User"** button
3. View list of available users (not yet in tenant)
4. Click on a user to assign them
5. User appears in tenant users list

### Making a User an Administrator

1. Select a tenant
2. Find the user in the tenant users list
3. Click the shield icon (🛡️)
4. User gets "Admin" badge
5. User now has administrator permissions for this tenant

**Note**: Users must be assigned to a tenant before they can be made administrators.

### Removing a User from Tenant

1. Select a tenant
2. Find the user in the tenant users list
3. Click the remove icon (×)
4. Confirm removal
5. User removed from tenant (and admin status if applicable)

## Key Functions Explained

### createTenant()
Creates a new tenant with validation:
- Checks for duplicate slug
- Auto-generates UUID
- Sets default enabled=true
- Returns created tenant data

### addUserToTenant()
Assigns a user to a tenant:
- Validates tenant and user exist
- Checks user not already assigned
- Creates tenant_users entry
- Updates statistics

### addTenantAdministrator()
Promotes a user to admin:
- **Requires user to be tenant member first**
- Checks not already admin
- Creates tenant_administrators entry
- User gets admin privileges

### removeUserFromTenant()
Removes user from tenant:
- Removes from tenant_users
- **Also removes from tenant_administrators** (if admin)
- Cascade cleanup ensures data integrity

## Validation Rules

### Tenant Creation
- ✅ Name required
- ✅ Slug required and must be unique
- ✅ Slug format: lowercase letters, numbers, hyphens only
- ✅ Description optional

### User Assignment
- ✅ User must exist and not be deleted
- ✅ Tenant must exist and not be deleted
- ✅ User not already in tenant

### Administrator Assignment
- ✅ User must be tenant member first
- ✅ User not already an administrator
- ✅ Cannot make admin without tenant membership

## Security Features

### Admin-Only Access
- All functions require admin authentication
- Server-side validation on all operations
- No exposed API endpoints

### Data Integrity
- Foreign key constraints prevent orphaned records
- Cascade deletes clean up relationships
- Unique constraints prevent duplicates
- Soft deletes preserve historical data

### Tenant Isolation
- Users can belong to multiple tenants
- Tenant data is isolated by tenant_id
- Administrators have tenant-specific permissions

## Technical Details

### Slug Generation
Tenant slugs are auto-generated from names:
```typescript
function generateSlug(name: string) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}
```

Example: "Acme Corporation Inc." → "acme-corporation-inc"

### Statistics Queries
Real-time statistics using SQL aggregations:
```sql
SELECT 
  t.id,
  t.name,
  COUNT(DISTINCT tu.user_id) as user_count,
  COUNT(DISTINCT ta.user_id) as admin_count,
  COUNT(DISTINCT p.id) as project_count
FROM apiome.tenants t
LEFT JOIN apiome.tenant_users tu ON t.id = tu.tenant_id
LEFT JOIN apiome.tenant_administrators ta ON t.id = ta.tenant_id
LEFT JOIN apiome.projects p ON t.id = p.tenant_id
GROUP BY t.id, t.name
```

### Soft Deletes
Tenants are never permanently deleted:
```sql
UPDATE apiome.tenants 
SET deleted_at = CURRENT_TIMESTAMP, 
    enabled = false
WHERE id = $1
```

## Files Structure

```
lib/db/
└── admin-helper.ts           # Updated with tenant functions

src/app/admin/dashboard/
├── AdminSidebar.tsx          # Updated with Tenant Management item
└── tenants/
    ├── page.tsx              # Page wrapper
    └── TenantManagementClient.tsx  # Main UI component
```

## Error Handling

All operations return JSON with consistent format:

**Success:**
```json
{
  "success": true,
  "tenant": {...}
}
```

**Error:**
```json
{
  "success": false,
  "error": "Error message"
}
```

UI displays:
- 🟢 Green success banners
- 🔴 Red error banners
- ⚠️ Confirmation dialogs for destructive actions

## Usage Examples

### Example 1: Create a Tenant
```typescript
const result = await createTenant(
  'Acme Corporation',
  'A leading technology company',
  'acme-corporation',
  true
);
```

### Example 2: Assign User to Tenant
```typescript
const result = await addUserToTenant(
  tenantId,  // UUID of tenant
  userId     // UUID of user
);
```

### Example 3: Make User an Admin
```typescript
// First, ensure user is in tenant
await addUserToTenant(tenantId, userId);

// Then make them admin
const result = await addTenantAdministrator(tenantId, userId);
```

## Benefits

### For Administrators
- ✅ Easy tenant creation and management
- ✅ Visual user assignment
- ✅ Quick admin designation
- ✅ Real-time statistics

### For Users
- ✅ Multi-tenant support
- ✅ Clear admin indicators
- ✅ Organized by tenant

### For System
- ✅ Proper data isolation
- ✅ Scalable architecture
- ✅ Referential integrity
- ✅ Audit trails via timestamps

## Testing Checklist

- [ ] Create a new tenant
- [ ] Verify slug auto-generation
- [ ] Enable/disable tenant
- [ ] Delete tenant
- [ ] Add user to tenant
- [ ] Remove user from tenant
- [ ] Make user an administrator
- [ ] Remove admin status
- [ ] Try to make admin without tenant membership (should fail)
- [ ] Verify statistics update correctly
- [ ] Check user appears in correct tenant
- [ ] Verify admin badge displays correctly

## Future Enhancements

Potential additions:
- Tenant settings and configuration
- Tenant billing information
- Usage analytics per tenant
- Tenant branding/customization
- Bulk user assignment
- User roles within tenants
- Tenant templates
- Export tenant data

## Troubleshooting

### "User must be a member of the tenant first"
- Add user to tenant before making them admin
- Use "Add User" button first

### Slug already exists
- Try a different name or manually modify slug
- Slugs must be unique across all tenants

### User not appearing in available list
- User may already be in the tenant
- Check the tenant users list

### Statistics not updating
- Click refresh button
- Statistics are calculated in real-time from database

---

**Implementation Date**: December 5, 2024
**Status**: ✅ Complete and Functional
**Authentication**: Admin-only via session cookies
**Database**: Direct access via server functions
**UI**: Split-panel design with real-time updates

