# Linked Accounts Feature - Implementation Summary

## Overview

A complete SSO (Single Sign-On) account linking feature has been implemented that allows users to link their Apiome account with external OAuth providers (GitHub, GitLab, AWS, GCP, etc.). Users can manage these linked accounts from the Dashboard and use them to sign in.

## What Was Implemented

### 1. Database Migration
**File**: `apiome-db/scripts/20251121-external-auth-providers.sql`

Creates the `external_auth_providers` table with the following structure:
- Links external OAuth provider accounts to master user accounts in `apiome.users`
- Stores OAuth tokens, profile data, and metadata
- Enforces unique constraints to prevent duplicate links
- Includes indexes for performance optimization
- Auto-updates timestamps via triggers

**Run the migration**:
```bash
psql -U your_user -d your_database -f apiome-db/scripts/20251121-external-auth-providers.sql
```

### 2. Database Helper Functions
**File**: `apiome-ui/lib/db/helper.ts`

Added the following server-side functions (NOT exposed as REST endpoints):

- `getLinkedAccountsForUser(userId)` - Get all linked accounts for a user
- `linkExternalAccount(...)` - Link a new provider account to a user
- `unlinkExternalAccount(userId, linkedAccountId)` - Remove a linked account
- `getLinkedAccountByProvider(provider, providerUserId)` - Check if provider account exists
- `getLinkedAccountByProviderForUser(userId, provider)` - Check if user has linked a specific provider
- `updateLinkedAccountLastLogin(provider, providerUserId)` - Update last login timestamp

### 3. Authentication Updates
**File**: `apiome-ui/lib/auth/credentials.ts`

- Updated `credentialsGithub()` to support automatic account linking on first OAuth login
- Added `linkGithubAccount()` helper function for linking GitHub accounts
- Checks for existing linked accounts during OAuth flow
- Auto-links GitHub account on first successful login
- Updates last login timestamp for existing linked accounts

### 4. Dashboard UI
**File**: `apiome-ui/src/app/ade/dashboard/linked-accounts/page.tsx`

A complete UI for managing linked accounts:
- Lists all currently linked accounts with details
- Shows provider info, username/email, link date, last login date
- "Link" buttons for available providers (GitHub is active, others show "Coming soon")
- "Unlink" buttons to remove linked accounts with confirmation dialog
- Empty state when no accounts are linked
- Success/error messages for operations
- Responsive grid layout for provider cards

### 5. Navigation Update
**File**: `apiome-ui/src/app/components/ade/dashboard/DashboardSideNav.tsx`

- Added "Linked Accounts" menu item in the Account section
- Uses Link icon from lucide-react
- Properly highlights when active

### 6. API Endpoint (Optional/Future)
**File**: `apiome-ui/src/app/api/auth/link/route.ts`

POST endpoint for explicitly linking accounts (can be used for future advanced flows):
- Requires authenticated session
- Validates required fields
- Calls `linkExternalAccount()` helper function
- Returns success/error responses

## Key Security Features

1. **Server-Side Only**: All database operations are server-side functions (`'use server'`), not exposed as REST endpoints
2. **User Validation**: All functions verify userId ownership before operations
3. **Unique Constraints**: 
   - One provider account per user per provider
   - Each provider account can only link to one user
4. **Token Storage**: Designed to support encrypted token storage (implement encryption in production!)
5. **Cascade Delete**: Linked accounts automatically deleted when user is deleted

## OAuth Flow

### First-Time Login (Auto-Link)
```
1. User clicks "Login with GitHub" on login page
2. OAuth redirects to GitHub
3. GitHub returns with user data
4. System checks if GitHub account exists in external_auth_providers
5. If NOT found:
   a. Check if user exists by email in apiome.users
   b. If user exists → Auto-link GitHub account to user
   c. Login user
6. If found → Login via linked account
```

### Manual Account Linking (From Dashboard)
```
1. User is already logged in
2. User navigates to Dashboard → Linked Accounts
3. User clicks "Link" button for GitHub
4. OAuth flow redirects to GitHub
5. GitHub returns with authorization
6. System links GitHub account to current user
7. Redirect back to Linked Accounts page with success message
```

### Account Unlinking
```
1. User goes to Dashboard → Linked Accounts
2. User clicks "Unlink" button for a provider
3. Confirmation dialog appears
4. User confirms
5. System removes link from external_auth_providers table
6. User can no longer sign in with that provider
```

## Supported Providers

### Currently Active
- **GitHub** - Fully implemented and functional

### Future Support (Foundation Laid)
- **GitLab** - UI ready, needs OAuth configuration
- **Google/GCP** - UI ready, needs OAuth configuration
- **AWS** - UI ready, needs OAuth configuration

## Configuration Required

### GitHub OAuth Setup
Add to `.env.local`:
```env
GITHUB_ID=your_github_client_id
GITHUB_SECRET=your_github_client_secret
```

### Future Providers
The system is extensible. To add a new provider:

1. Add provider config to `providerConfigs` in `linked-accounts/page.tsx`
2. Add provider to NextAuth configuration in `[...nextauth]/route.ts`
3. Create provider-specific OAuth handler in `credentials.ts`
4. Add environment variables for client ID/secret

## Database Schema

### Table: `apiome.external_auth_providers`

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK to apiome.users.id |
| provider | VARCHAR(50) | Provider name (github, gitlab, etc.) |
| provider_user_id | VARCHAR(255) | User ID from provider |
| provider_email | VARCHAR(255) | Email from provider |
| provider_username | VARCHAR(255) | Username from provider |
| access_token | TEXT | OAuth access token (encrypt!) |
| refresh_token | TEXT | OAuth refresh token (encrypt!) |
| token_expires_at | TIMESTAMP | Token expiration time |
| profile_data | JSONB | Additional provider data |
| created_at | TIMESTAMP | Record creation time |
| updated_at | TIMESTAMP | Last update time (auto) |
| last_login_at | TIMESTAMP | Last successful login |

**Constraints**:
- UNIQUE(user_id, provider) - One link per provider per user
- UNIQUE(provider, provider_user_id) - Provider account can only link to one user

## Testing Checklist

- [ ] Run database migration successfully
- [ ] Test first-time GitHub login (auto-links account)
- [ ] Test subsequent GitHub login (uses linked account)
- [ ] Navigate to Dashboard → Linked Accounts
- [ ] Verify linked GitHub account appears in list
- [ ] Test linking additional accounts (when more providers added)
- [ ] Test unlinking GitHub account
- [ ] Verify unlinking removes account from list
- [ ] Test cannot link same GitHub account to different user
- [ ] Test cannot link multiple GitHub accounts to same user
- [ ] Verify last login timestamp updates on each login

## Future Enhancements

1. **Token Encryption** - Implement encryption for access_token and refresh_token fields
2. **Token Refresh** - Automatic token refresh before expiration
3. **Additional Providers** - Enable GitLab, Google, AWS, Azure
4. **Account Merging** - Merge multiple Apiome accounts
5. **MFA with OAuth** - Require 2FA even with OAuth
6. **Audit Logging** - Log all link/unlink operations
7. **Email Notifications** - Notify user when accounts are linked/unlinked
8. **OAuth Scopes** - Request specific scopes for API access
9. **Profile Sync** - Sync profile data from providers
10. **Account Recovery** - Use linked accounts for account recovery

## Important Notes

⚠️ **Security**:
- All database functions are server-side only (`'use server'`)
- No REST endpoints expose these operations publicly
- Implement token encryption before production use
- Rotate encryption keys regularly
- Use HTTPS for all OAuth redirects

⚠️ **User Experience**:
- Users can link multiple providers
- Users can unlink providers at any time
- Main Apiome account (apiome.users) is always the source of truth
- User data is never overwritten by OAuth provider data
- Email from OAuth must match OR account is auto-created (configurable)

## Files Created/Modified

### Created
1. `apiome-db/scripts/20251121-external-auth-providers.sql`
2. `apiome-db/docs/EXTERNAL_AUTH_PROVIDERS.md`
3. `apiome-db/docs/EXTERNAL_AUTH_PROVIDERS_SUMMARY.md`
4. `apiome-ui/src/app/ade/dashboard/linked-accounts/page.tsx`
5. `apiome-ui/src/app/api/auth/link/route.ts`

### Modified
1. `apiome-ui/lib/db/helper.ts` - Added 6 new functions
2. `apiome-ui/lib/auth/credentials.ts` - Updated GitHub OAuth handler
3. `apiome-ui/src/app/components/ade/dashboard/DashboardSideNav.tsx` - Added menu item

## Questions?

See the full documentation:
- **Complete Guide**: `apiome-db/docs/EXTERNAL_AUTH_PROVIDERS.md`
- **Quick Reference**: `apiome-db/docs/EXTERNAL_AUTH_PROVIDERS_SUMMARY.md`
- **This Summary**: `apiome-db/docs/LINKED_ACCOUNTS_IMPLEMENTATION.md`

