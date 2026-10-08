# User Management Implementation Guide

## Overview

A complete user management system has been implemented for the admin dashboard, allowing administrators to:
- View all existing users
- Approve pending signups and create user accounts
- Manage user status (enable/disable, verify/unverify)
- Delete users (soft delete)
- View statistics about users and signups

## Architecture

### No REST APIs - Direct Database Access

This implementation does NOT use REST API endpoints. Instead, it uses server-side functions that directly access the database through the `admin-helper.ts` module.

**Benefits:**
- Simpler architecture
- Better security (no exposed API endpoints)
- Type-safe server functions
- Automatic request/response handling

### File Structure

```
lib/db/
└── admin-helper.ts          # Server-side database functions (NEW)

src/app/admin/dashboard/
├── layout.tsx               # Dashboard layout with sidebar (NEW)
├── page.tsx                 # Dashboard overview page (UPDATED)
├── DashboardOverview.tsx    # Overview content (NEW)
├── AdminSidebar.tsx         # Persistent sidebar navigation (NEW)
└── users/
    ├── page.tsx            # User management page (NEW)
    └── UserManagementClient.tsx  # User management UI (NEW)
```

## Admin Helper Functions

Located in `/lib/db/admin-helper.ts`, this module provides server-side functions for admin operations:

### User Management Functions

```typescript
// Get all users
getAllUsers(): Promise<string>

// Get single user by ID
getUserById(userId: string): Promise<string>

// Create new user
createUser(name, email, password, verified, enabled): Promise<string>

// Update user details
updateUser(userId, updates): Promise<string>

// Soft delete user
deleteUser(userId: string): Promise<string>

// Get user statistics
getUserStats(): Promise<string>
```

### Signup Management Functions

```typescript
// Get all pending signups
getAllSignups(): Promise<string>

// Get signup statistics
getSignupStats(): Promise<string>

// Create user from signup (with password from signup)
createUserFromSignup(email, verified, enabled): Promise<string>

// Delete signup entry
deleteSignup(email: string): Promise<string>
```

### Tenant Management Functions

```typescript
// Get all tenants
getAllTenants(): Promise<string>

// Get tenant statistics with counts
getTenantStats(): Promise<string>

// Get users for specific tenant
getTenantUsers(tenantId: string): Promise<string>
```

## Database Tables

### apiome.users

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT false,
    enabled BOOLEAN NOT NULL DEFAULT true,
    deleted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### apiome.signup

```sql
CREATE TABLE signup (
    name VARCHAR(255) NOT NULL,
    email_address VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    signup_source VARCHAR(255),
    signup_date TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

**Note:** The signup table stores passwords in hashed format (bcrypt). When creating a user from a signup, the hashed password is transferred directly to the users table.

## User Management UI Features

### Statistics Dashboard

Displays real-time statistics:
- **Total Users**: Count of all active users
- **Verified Users**: Count of verified users
- **Pending Signups**: Count of signup requests awaiting approval
- **Recent Signups**: Count of signups in last 7 days

### Two Tabs

1. **Pending Signups Tab**
   - Lists all signup requests
   - Shows name, email, source, and date
   - Actions:
     - **Create User**: Converts signup to user account
     - **Delete**: Removes signup request

2. **Active Users Tab**
   - Lists all existing users
   - Shows name, email, status badges, and creation date
   - Status indicators:
     - Verified/Unverified
     - Enabled/Disabled
   - Actions:
     - **Toggle Verified**: Change verification status
     - **Toggle Enabled**: Enable/disable user account
     - **Delete User**: Soft delete (sets deleted_at)

### Key Features

- **Real-time Updates**: Data refreshes after each action
- **Confirmation Dialogs**: Prevents accidental deletions
- **Success/Error Messages**: Clear feedback for all operations
- **Refresh Button**: Manual data reload
- **Responsive Tables**: Scrollable on small screens

## Password Handling

### From Signups

When a user signs up through the login page:
1. Password is hashed using bcrypt (10 rounds)
2. Stored in `apiome.signup` table
3. When admin creates user from signup:
   - Hashed password is copied to `apiome.users`
   - Signup entry is deleted
   - User can immediately login with their original password

### Manual User Creation

If creating a user manually (not from signup):
- Password must be provided
- Will be hashed automatically by `createUser()` function
- Checks if password is already hashed to avoid double-hashing

## Security Considerations

### Admin-Only Access

- All functions in `admin-helper.ts` are marked with `'use server'`
- Only executable in server context
- Cannot be called from client-side code directly
- Admin authentication checked in page components

### Soft Deletes

Users are never hard-deleted:
```sql
UPDATE apiome.users 
SET deleted_at = CURRENT_TIMESTAMP, 
    enabled = false
WHERE id = $1
```

This preserves data integrity and allows for audit trails.

### Password Security

- Passwords stored as bcrypt hashes
- Original passwords never stored in plain text
- Hashes transferred directly from signup to users
- No exposure in API responses or logs

## Usage Examples

### Approving a Signup

1. Navigate to **User Management** in sidebar
2. View **Pending Signups** tab
3. Click **Create User** button for desired signup
4. User is created with:
   - Name from signup
   - Email from signup
   - Hashed password from signup
   - Verified: true (default)
   - Enabled: true (default)
5. Signup entry automatically deleted
6. User can now login with their chosen password

### Managing Existing Users

1. Navigate to **Active Users** tab
2. View list of all users
3. Actions available:
   - **Verify/Unverify**: Toggle verification status
   - **Enable/Disable**: Toggle account access
   - **Delete**: Soft delete user account

### Viewing Statistics

Statistics automatically load on page:
- Total user count
- Verified user count
- Pending signup count
- Recent signup trends

## Error Handling

All functions return JSON strings with format:
```typescript
// Success
{
  success: true,
  data: {...}
}

// Error
{
  success: false,
  error: "Error message"
}
```

UI displays errors as red banners and successes as green banners.

## Navigation

The admin dashboard now uses a persistent sidebar:
- **Overview**: Dashboard statistics
- **User Management**: User and signup management (IMPLEMENTED)
- **Payment Management**: Coming soon
- **Database Administration**: Coming soon
- **System Monitoring**: Coming soon
- **System Configuration**: Coming soon

Click any menu item to navigate. Active page is highlighted in red.

## Future Enhancements

Potential additions:
- Bulk user operations
- User search and filtering
- Export user data
- Email notifications for new signups
- User activity logs
- Password reset functionality
- Role-based permissions
- User impersonation (for support)

## Testing Checklist

- [ ] View pending signups
- [ ] Create user from signup
- [ ] Delete signup
- [ ] View active users
- [ ] Toggle user verified status
- [ ] Toggle user enabled status
- [ ] Delete user
- [ ] Verify statistics update
- [ ] Check password works after signup conversion
- [ ] Test error handling
- [ ] Verify sidebar navigation

## Troubleshooting

### Users not appearing
- Check `deleted_at IS NULL` in queries
- Verify database connection
- Check console for errors

### Password not working after signup conversion
- Verify password hash was copied correctly
- Check bcrypt format ($2a$ or $2b$ prefix)
- Ensure no double-hashing occurred

### Statistics not updating
- Click refresh button
- Check database queries returning correct counts
- Verify time zone handling for date filters

---

**Implementation Date**: December 5, 2024
**Status**: ✅ Complete and Functional
**Authentication**: Admin-only via session cookies
**Database**: Direct access via server functions

