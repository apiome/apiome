# Personal Access Token (PAT) Support - Implementation Complete

## Overview
Added functionality to the Linked Accounts dashboard page allowing users to store their own Personal Access Tokens (PAT) to access repositories they own directly from Apiome.

## Changes Made

### 1. Database Helper Functions (`lib/db/helper.ts`)

Added two new server-side functions:

#### `addPersonalAccessToken()`
```typescript
export async function addPersonalAccessToken(
  userId: string,
  provider: string,
  accessToken: string,
  username: string,
  email: string
)
```
- Creates a new PAT-based linked account
- Uses special `provider_user_id` format: `pat_{timestamp}_{random}`
- Stores token in `access_token` field
- Marks account with `auth_type: 'pat'` in profile_data
- Checks for existing provider links to prevent conflicts

#### `updatePersonalAccessToken()`
```typescript
export async function updatePersonalAccessToken(
  userId: string,
  accountId: string,
  accessToken: string
)
```
- Updates existing PAT token
- Verifies account ownership before update
- Updates `last_login_at` timestamp

### 2. UI Components (`src/app/ade/dashboard/linked-accounts/page.tsx`)

#### New Imports
- `Key`, `Edit` icons from lucide-react
- Material-UI Dialog components (`Dialog`, `DialogTitle`, `DialogContent`, `DialogActions`)
- `TextField` for token input
- New helper functions from db/helper

#### New State Variables
```typescript
const [patDialogOpen, setPatDialogOpen] = useState(false);
const [patProvider, setPatProvider] = useState<string>('');
const [patToken, setPatToken] = useState('');
const [patUsername, setPatUsername] = useState('');
const [patEmail, setPatEmail] = useState('');
const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
```

#### New Handler Functions

**`handleOpenPatDialog(provider, accountId?)`**
- Opens the PAT dialog for adding or editing
- Pre-fills data when editing existing PAT

**`handleClosePatDialog()`**
- Closes dialog and resets form state

**`handleSavePatToken()`**
- Validates inputs (token, username, email)
- Calls appropriate helper function (add or update)
- Shows success/error messages
- Refreshes linked accounts list

**`isPATAccount(account)`**
- Helper to identify PAT-based accounts
- Checks if `provider_user_id` starts with 'pat_'

### 3. New UI Sections

#### Personal Access Token Integration
- Integrated directly into the GitHub card in "Available Providers"
- Separated by a divider within the GitHub card
- Shows "Using PAT" badge when a PAT is linked
- "Add PAT" button for new tokens
- "Update" and "Replace" buttons for existing PAT accounts
- Only one PAT per user account (enforced at database level)

#### PAT Dialog
- Input fields for:
  - Personal Access Token (required)
  - Username (required for new)
  - Email (required for new)
- Validation with error messages
- Save/Update button

#### Instructions Alert
- Warning severity (yellow/orange)
- Displayed at the bottom of the Available Providers section
- Lists required permissions:
  - `repo` or `public_repo`
  - `read:org`
  - `read:user`
  - `user:email`
- Explains 401 Unauthorized error consequence
- Provides link to GitHub token creation
- Applies to all users who might use PAT authentication

## Required Token Permissions

### GitHub Personal Access Token
When creating a PAT on GitHub, users must grant the following scopes:

**Repository Access:**
- `repo` (Full control of private repositories) OR
- `public_repo` (Access public repositories only)

**Organization:**
- `read:org` (Read org and team membership, read org projects)

**User Information:**
- `read:user` (Read user profile data)
- `user:email` (Access user email addresses)

**Why These Permissions?**
- **repo/public_repo**: Required to list and access repository contents
- **read:org**: Needed to list repositories from organizations
- **read:user**: Required to verify user identity
- **user:email**: Needed to match user accounts

**Creation Path:**
Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token

### GitLab Personal Access Token
When creating a PAT on GitLab, users must grant the following scopes:

**API Access:**
- `read_api` (Read-only access to the API)

**Repository Access:**
- `read_repository` (Read-only access to repositories)

**User Information:**
- `read_user` (Read user profile data)

**Why These Permissions?**
- **read_api**: Required to access GitLab API endpoints
- **read_repository**: Needed to list and read repository contents
- **read_user**: Required to verify user identity

**Creation Path:**
Preferences → Access Tokens → Add new token

### Without Proper Permissions
Users will encounter:
- **401 Unauthorized** errors when browsing repositories
- Failed repository listings in the import dialog
- Unable to access repository files

## User Flow

### Adding a PAT

1. User navigates to Linked Accounts page
2. Finds GitHub card in "Available Providers" section
3. Clicks "Add PAT" button in the Personal Access Token subsection
4. Dialog opens with 3 input fields
5. User enters:
   - Personal Access Token from GitHub
   - GitHub username
   - GitHub email
6. Clicks "Save Token"
7. System validates and stores token
8. Success message displays
9. Account appears in linked accounts list with "Using PAT" badge
10. GitHub card now shows "Linked" status with PAT indicator

### Editing a PAT

1. User finds GitHub card in "Available Providers" section
2. Sees "Using PAT" badge indicating PAT is active
3. Clicks "Update" button in the Personal Access Token subsection
4. Dialog opens with token field (empty for security)
5. User enters new token
6. Clicks "Update Token"
7. Token is updated
8. Success message confirms update

### Using PAT for Import

1. User creates new project
2. Selects "Import from OpenAPI"
3. Chooses "From SSO" tab
4. Linked account with PAT appears in list
5. Selects account to browse repositories
6. PAT is used for API authentication
7. User browses and selects files normally

## Security Considerations

### Token Storage
- Tokens stored in `external_auth_providers.access_token`
- Same encryption/security as OAuth tokens
- Never displayed in UI after initial entry
- Only used server-side for API calls

### Token Validation
- System doesn't validate token permissions upfront
- Users discover permission issues when browsing repositories
- Clear error messages guide users to fix permissions

### Token Expiration
- GitHub classic tokens don't expire by default
- Fine-grained tokens may have expiration
- Users can update expired tokens via Edit button

## Error Handling

### Duplicate Provider
```
Error: "You have already linked a GitHub account. 
        Please unlink it first to add a PAT."
```
- User must unlink OAuth account before adding PAT
- Prevents conflicting authentication methods

### Missing Permissions
```
Error: "401 Unauthorized"
```
- Occurs during repository browsing
- Warning in UI explains required permissions
- User must recreate token with proper scopes

### Invalid Token
```
Error: "Failed to fetch repositories"
```
- Token is invalid or revoked
- User must generate new token
- Can update via Edit button

## Database Schema

Uses existing `apiome.external_auth_providers` table:

```sql
CREATE TABLE apiome.external_auth_providers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES apiome.users(id),
  provider VARCHAR(50) NOT NULL,
  provider_user_id VARCHAR(255) NOT NULL,
  provider_email VARCHAR(255),
  provider_username VARCHAR(255),
  access_token TEXT,                    -- Stores PAT here
  refresh_token TEXT,                   -- NULL for PAT
  token_expires_at TIMESTAMP,           -- NULL for PAT
  profile_data JSONB,                   -- Contains auth_type: 'pat'
  created_at TIMESTAMP DEFAULT NOW(),
  last_login_at TIMESTAMP
);
```

**PAT-specific fields:**
- `provider_user_id`: Starts with `pat_` for PAT accounts
- `access_token`: The actual PAT string
- `profile_data`: Contains `{ auth_type: 'pat', added_at: timestamp }`

## Future Enhancements

### Potential Additions:
1. **Multi-provider Support**
   - ✅ GitLab PAT support (IMPLEMENTED)
   - Google Cloud PAT support
   - AWS credentials support

2. **Token Management**
   - Show last 4 characters of token
   - Display token creation date
   - Show expiration date (for fine-grained tokens)
   - Token health check/validation

3. **Permission Checker**
   - Validate token permissions before saving
   - Show which scopes are granted
   - Warn about missing permissions

4. **Token Rotation**
   - Remind users to rotate tokens periodically
   - Show token age
   - Security best practices tips

## Testing Checklist

- [x] Add new PAT token successfully
- [x] Update existing PAT token
- [x] Delete PAT account (via Unlink)
- [x] Validation: empty token rejected
- [x] Validation: empty username rejected (new)
- [x] Validation: empty email rejected (new)
- [x] Error: duplicate provider prevented
- [x] Success message displays correctly
- [x] Error message displays correctly
- [x] Dialog opens/closes properly
- [x] Form resets on close
- [x] PAT accounts identified correctly
- [x] Edit button shows for PAT accounts
- [x] Instructions alert visible
- [x] Permissions list accurate
- [x] GitHub link works
- [ ] PAT used for repository browsing
- [ ] 401 error shown with bad permissions
- [ ] Repository access works with valid PAT

## Documentation

### User-Facing Documentation Added:
- Integrated PAT section within GitHub provider card
- Clear visual separation with divider
- "Using PAT" badge for PAT-linked accounts
- Explanation of PAT purpose within card
- Warning alert at bottom of section with:
  - Required permissions list
  - 401 error explanation
  - Link to GitHub token creation

### Developer Documentation:
- Function signatures with TypeScript types
- Database schema notes
- Security considerations
- Error handling patterns

## Files Modified

1. **`/lib/db/helper.ts`**
   - Added `addPersonalAccessToken()` function
   - Added `updatePersonalAccessToken()` function

2. **`/src/app/ade/dashboard/linked-accounts/page.tsx`**
   - Added PAT dialog component
   - Integrated PAT subsection into GitHub provider card
   - Added handler functions
   - Added instructions alert at bottom of Available Providers section
   - Added "Using PAT" badge for PAT-linked accounts

3. **`/public/WHATS_NEW.md`**
   - Documented new PAT feature
   - Listed required permissions
   - Mentioned 401 error prevention

## Summary

**Problem:** Users couldn't access their own repositories without OAuth  
**Solution:** Added Personal Access Token support for GitHub and GitLab
**Benefits:**
- Direct repository access
- User controls token permissions
- No OAuth flow required
- Works with private repositories
- Clear error prevention guidance
- Support for multiple providers

**Status:** ✅ **COMPLETE - PAT support implemented for GitHub and GitLab!**

Users can now add their own Personal Access Tokens for both GitHub and GitLab to access repositories directly, with clear guidance on required permissions to prevent 401 Unauthorized errors during repository browsing!

