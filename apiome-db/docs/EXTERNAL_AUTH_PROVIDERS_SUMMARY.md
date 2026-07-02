# External Authentication Providers - Implementation Summary

## What Was Created

### Migration Script
**File**: `apiome-db/scripts/20251121-external-auth-providers.sql`

Creates the `external_auth_providers` table to link OAuth provider accounts to master user accounts.

### Key Features

1. **Table Structure**: Stores OAuth provider account links with user accounts
2. **Multi-Provider Support**: Users can link multiple OAuth providers (GitHub, GitLab, AWS, GCP, etc.)
3. **Token Management**: Stores access/refresh tokens (encrypt in production!)
4. **Automatic Timestamps**: `updated_at` field auto-updates via trigger
5. **Unique Constraints**: 
   - One provider account per user per provider
   - Each provider account can only be linked to one user

### Table: `apiome.external_auth_providers`

```sql
id                  UUID PRIMARY KEY
user_id             UUID → apiome.users.id
provider            VARCHAR(50)       -- 'github', 'gitlab', 'aws', 'gcp', etc.
provider_user_id    VARCHAR(255)      -- User ID from provider
provider_email      VARCHAR(255)      -- Email from provider
provider_username   VARCHAR(255)      -- Username from provider
access_token        TEXT              -- OAuth access token (encrypt!)
refresh_token       TEXT              -- OAuth refresh token (encrypt!)
token_expires_at    TIMESTAMP         -- Token expiration
profile_data        JSONB             -- Additional provider data
created_at          TIMESTAMP
updated_at          TIMESTAMP         -- Auto-updated
last_login_at       TIMESTAMP
```

## Quick Start

### 1. Run Migration

```bash
psql -U your_user -d your_database -f apiome-db/scripts/20251121-external-auth-providers.sql
```

### 2. OAuth Login Flow

```
User clicks "Login with GitHub"
  ↓
Redirect to GitHub OAuth
  ↓
GitHub returns with code
  ↓
Exchange code for tokens
  ↓
Fetch user profile from GitHub
  ↓
Check if provider account exists in DB
  ├─ YES → Login existing user
  └─ NO  → Check if email exists
      ├─ YES → Link to existing user
      └─ NO  → Create new user + link
```

### 3. Common Queries

**Check if provider account exists:**
```sql
SELECT user_id FROM apiome.external_auth_providers
WHERE provider = 'github' AND provider_user_id = '12345678';
```

**Link provider to user:**
```sql
INSERT INTO apiome.external_auth_providers (
    user_id, provider, provider_user_id, provider_email,
    provider_username, last_login_at
) VALUES (
    '...user-uuid...', 'github', '12345678', 'user@example.com',
    'githubuser', CURRENT_TIMESTAMP
);
```

**Get user's linked providers:**
```sql
SELECT provider, provider_username, created_at, last_login_at
FROM apiome.external_auth_providers
WHERE user_id = '...user-uuid...'
ORDER BY created_at DESC;
```

**Update last login:**
```sql
UPDATE apiome.external_auth_providers
SET last_login_at = CURRENT_TIMESTAMP
WHERE provider = 'github' AND provider_user_id = '12345678';
```

## Security Checklist

- [ ] Encrypt `access_token` and `refresh_token` before storing
- [ ] Use HTTPS for all OAuth redirects
- [ ] Validate OAuth state parameter (CSRF protection)
- [ ] Implement token refresh logic
- [ ] Rate limit OAuth endpoints
- [ ] Log authentication attempts
- [ ] Send email notifications for new provider links
- [ ] Allow users to review/revoke linked accounts
- [ ] Implement session timeout
- [ ] Use secure random strings for state/nonce

## Supported Providers

| Provider | Identifier | OAuth Documentation |
|----------|-----------|---------------------|
| GitHub | `github` | https://docs.github.com/en/developers/apps/building-oauth-apps |
| GitLab | `gitlab` | https://docs.gitlab.com/ee/api/oauth2.html |
| Google/GCP | `google` | https://developers.google.com/identity/protocols/oauth2 |
| Microsoft Azure | `azure` | https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-auth-code-flow |
| AWS Cognito | `aws` | https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-app-integration.html |
| Bitbucket | `bitbucket` | https://support.atlassian.com/bitbucket-cloud/docs/use-oauth-on-bitbucket-cloud/ |

## Next Steps

1. **Backend Implementation**
   - Create OAuth routes (`/api/auth/oauth/{provider}`)
   - Implement callback handler (`/api/auth/oauth/{provider}/callback`)
   - Add token encryption/decryption utilities
   - Create provider-specific OAuth clients

2. **Frontend Implementation**
   - Add OAuth login buttons to login page
   - Create account settings page to link/unlink providers
   - Display linked providers in user profile
   - Add loading/error states for OAuth flow

3. **Testing**
   - Test first-time login with new email
   - Test first-time login with existing email
   - Test linking additional providers
   - Test token refresh flow
   - Test unlinking providers

4. **Documentation**
   - Document OAuth setup for each provider (client IDs, secrets)
   - Create user guide for linking accounts
   - Document API endpoints

## Rollback

```sql
SET search_path TO apiome, public;
DROP TRIGGER IF EXISTS trigger_update_external_auth_providers_updated_at ON external_auth_providers;
DROP FUNCTION IF EXISTS update_external_auth_providers_updated_at();
DROP TABLE IF EXISTS external_auth_providers CASCADE;
```

## Related Files

- Migration: `apiome-db/scripts/20251121-external-auth-providers.sql`
- Full Documentation: `apiome-db/docs/EXTERNAL_AUTH_PROVIDERS.md`
- Users Table: `apiome-db/scripts/20251026-012616.sql`

## Questions?

See the full documentation at `apiome-db/docs/EXTERNAL_AUTH_PROVIDERS.md` for:
- Detailed implementation examples
- Security best practices
- Code samples (Python/FastAPI, React/Next.js)
- Testing scenarios
- Future enhancements

