# External Authentication Providers Feature

## Overview

This feature enables users to link their Apiome accounts with external OAuth providers (GitHub, GitLab, AWS, GCP, Azure, etc.) for single sign-on (SSO) authentication. Users can click "Login with [Provider]" buttons on the login page to authenticate using their external accounts.

## Database Schema

### Table: `external_auth_providers`

Links external OAuth provider accounts to master user accounts in `apiome.users`.

#### Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key, auto-generated |
| `user_id` | UUID | Foreign key to `apiome.users.id` (master account) |
| `provider` | VARCHAR(50) | Provider name (e.g., 'github', 'gitlab', 'aws', 'gcp', 'azure') |
| `provider_user_id` | VARCHAR(255) | Unique user ID from the provider |
| `provider_email` | VARCHAR(255) | Email address from the provider |
| `provider_username` | VARCHAR(255) | Username from the provider |
| `access_token` | TEXT | OAuth access token (should be encrypted in production) |
| `refresh_token` | TEXT | OAuth refresh token (should be encrypted in production) |
| `token_expires_at` | TIMESTAMP | Access token expiration time |
| `profile_data` | JSONB | Additional profile data from provider |
| `created_at` | TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | Last update timestamp (auto-updated) |
| `last_login_at` | TIMESTAMP | Last successful login timestamp |

#### Constraints

- **UNIQUE(user_id, provider)**: A user can only link one account per provider
- **UNIQUE(provider, provider_user_id)**: A provider account can only be linked to one user
- **CASCADE DELETE**: When a user is deleted, all linked provider accounts are deleted

#### Indexes

- `idx_external_auth_providers_user_id` - Fast lookups by user
- `idx_external_auth_providers_provider` - Fast lookups by provider
- `idx_external_auth_providers_provider_email` - Fast lookups by provider email
- `idx_external_auth_providers_provider_user_id` - Fast lookups by provider and provider user ID
- `idx_external_auth_providers_created_at` - Sorting by creation date
- `idx_external_auth_providers_last_login_at` - Sorting by last login

## Migration

Run the migration script:

```sql
psql -U your_user -d your_database -f /path/to/20251121-external-auth-providers.sql
```

## Use Cases

### 1. First-Time OAuth Login (Account Linking)

When a user logs in with an OAuth provider for the first time:

1. User clicks "Login with GitHub" on the login page
2. OAuth flow redirects to GitHub for authentication
3. GitHub returns with user data (user_id, email, username, tokens)
4. System checks if `provider='github'` and `provider_user_id` exists in `external_auth_providers`
5. If not found, check if user with `provider_email` exists in `apiome.users`
   - **If yes**: Link the provider account to existing user
   - **If no**: Create new user in `apiome.users`, then link provider account
6. Insert record into `external_auth_providers`
7. Set session for the user

### 2. Subsequent OAuth Login

When a user logs in with a previously linked OAuth provider:

1. User clicks "Login with GitHub"
2. OAuth flow completes
3. System finds existing record in `external_auth_providers`
4. Update `last_login_at` and refresh tokens if needed
5. Set session for the linked user

### 3. Linking Additional Providers

When a logged-in user wants to link another provider:

1. User goes to account settings
2. Clicks "Link GitHub Account"
3. OAuth flow completes
4. System creates new record in `external_auth_providers` with current `user_id`
5. User can now login with either provider

## Example Queries

### Check if Provider Account Exists

```sql
SELECT user_id, provider, provider_email, provider_username, last_login_at
FROM apiome.external_auth_providers
WHERE provider = 'github' AND provider_user_id = '12345678';
```

### Link New Provider to Existing User

```sql
INSERT INTO apiome.external_auth_providers (
    user_id,
    provider,
    provider_user_id,
    provider_email,
    provider_username,
    access_token,
    refresh_token,
    token_expires_at,
    profile_data,
    last_login_at
) VALUES (
    'user-uuid-here',
    'github',
    '12345678',
    'user@example.com',
    'githubuser',
    'encrypted_access_token',
    'encrypted_refresh_token',
    CURRENT_TIMESTAMP + INTERVAL '1 hour',
    '{"name": "John Doe", "avatar_url": "https://..."}'::jsonb,
    CURRENT_TIMESTAMP
);
```

### Get All Linked Providers for a User

```sql
SELECT 
    provider,
    provider_email,
    provider_username,
    created_at,
    last_login_at
FROM apiome.external_auth_providers
WHERE user_id = 'user-uuid-here'
ORDER BY created_at DESC;
```

### Update Last Login Time

```sql
UPDATE apiome.external_auth_providers
SET last_login_at = CURRENT_TIMESTAMP
WHERE provider = 'github' AND provider_user_id = '12345678';
```

### Unlink Provider Account

```sql
DELETE FROM apiome.external_auth_providers
WHERE user_id = 'user-uuid-here' AND provider = 'github';
```

### Find User by Provider Email

```sql
SELECT u.id, u.name, u.email, u.verified, u.enabled
FROM apiome.users u
WHERE u.email = 'user@example.com' AND u.deleted_at IS NULL;
```

## Supported Providers

The system can support any OAuth 2.0 provider. Common providers include:

- **github** - GitHub
- **gitlab** - GitLab
- **google** - Google / GCP
- **azure** - Microsoft Azure / Azure DevOps
- **aws** - Amazon Web Services (via AWS Cognito)
- **bitbucket** - Bitbucket
- **linkedin** - LinkedIn
- **okta** - Okta
- **auth0** - Auth0

## Security Considerations

### Token Storage

**⚠️ IMPORTANT**: In production, you MUST encrypt tokens before storing them:

1. Use encryption at rest for the database
2. Encrypt `access_token` and `refresh_token` columns using application-level encryption
3. Consider using a secrets management service (AWS Secrets Manager, HashiCorp Vault, etc.)
4. Use environment-specific encryption keys
5. Rotate encryption keys periodically

### Token Refresh

- Check `token_expires_at` before using stored access tokens
- Implement token refresh logic using the `refresh_token`
- Update tokens in the database after refresh

### Account Security

- Require email verification before linking external accounts
- Implement rate limiting on OAuth endpoints
- Log all OAuth authentication attempts
- Allow users to review and revoke linked accounts
- Send email notifications when new providers are linked

### Privacy

- Store only necessary profile data in `profile_data` JSONB field
- Allow users to view what data is stored
- Provide option to delete stored profile data
- Comply with GDPR and other privacy regulations

## Implementation Flow

### Backend (Python/FastAPI Example)

```python
# After OAuth callback
async def handle_oauth_callback(provider: str, code: str, db: Session):
    # 1. Exchange code for tokens
    tokens = await exchange_oauth_code(provider, code)
    
    # 2. Fetch user profile from provider
    profile = await fetch_provider_profile(provider, tokens['access_token'])
    
    # 3. Check if provider account exists
    provider_account = db.query(ExternalAuthProvider).filter(
        ExternalAuthProvider.provider == provider,
        ExternalAuthProvider.provider_user_id == profile['id']
    ).first()
    
    if provider_account:
        # Existing account - login
        user = provider_account.user
        # Update tokens and last login
        provider_account.access_token = encrypt(tokens['access_token'])
        provider_account.refresh_token = encrypt(tokens['refresh_token'])
        provider_account.last_login_at = datetime.utcnow()
        db.commit()
    else:
        # New provider account - link or create user
        user = db.query(User).filter(User.email == profile['email']).first()
        
        if not user:
            # Create new user
            user = User(
                name=profile['name'],
                email=profile['email'],
                verified=True,  # Email verified by provider
                enabled=True,
                password=generate_random_password()  # Not used for OAuth
            )
            db.add(user)
            db.flush()
        
        # Link provider account
        provider_account = ExternalAuthProvider(
            user_id=user.id,
            provider=provider,
            provider_user_id=profile['id'],
            provider_email=profile['email'],
            provider_username=profile.get('username'),
            access_token=encrypt(tokens['access_token']),
            refresh_token=encrypt(tokens['refresh_token']),
            token_expires_at=datetime.utcnow() + timedelta(hours=1),
            profile_data=profile,
            last_login_at=datetime.utcnow()
        )
        db.add(provider_account)
        db.commit()
    
    # 4. Create session
    return create_session(user)
```

### Frontend (React/Next.js Example)

```tsx
// Login page with OAuth buttons
export default function LoginPage() {
  const handleOAuthLogin = (provider: string) => {
    // Redirect to OAuth authorization URL
    window.location.href = `/api/auth/oauth/${provider}`;
  };

  return (
    <div>
      <h1>Login</h1>
      
      {/* Traditional login form */}
      <form>
        <input type="email" placeholder="Email" />
        <input type="password" placeholder="Password" />
        <button type="submit">Login</button>
      </form>
      
      <div className="divider">OR</div>
      
      {/* OAuth login buttons */}
      <div className="oauth-buttons">
        <button onClick={() => handleOAuthLogin('github')}>
          <GitHubIcon /> Login with GitHub
        </button>
        <button onClick={() => handleOAuthLogin('gitlab')}>
          <GitLabIcon /> Login with GitLab
        </button>
        <button onClick={() => handleOAuthLogin('google')}>
          <GoogleIcon /> Login with Google
        </button>
      </div>
    </div>
  );
}
```

## Testing

### Test Scenarios

1. **First-time OAuth login with new email** - Should create new user
2. **First-time OAuth login with existing email** - Should link to existing user
3. **Subsequent OAuth login** - Should login existing user
4. **Link additional provider to account** - Should add second provider
5. **Attempt to link already-linked provider account** - Should fail (unique constraint)
6. **Token expiration handling** - Should refresh tokens automatically
7. **Provider account unlinking** - Should remove provider link but keep user

### Sample Test Data

```sql
-- Insert test user
INSERT INTO apiome.users (id, name, email, password, verified, enabled)
VALUES (
    '123e4567-e89b-12d3-a456-426614174000',
    'Test User',
    'test@example.com',
    '$2a$12$hashed_password',
    true,
    true
);

-- Link GitHub account
INSERT INTO apiome.external_auth_providers (
    user_id,
    provider,
    provider_user_id,
    provider_email,
    provider_username,
    profile_data
) VALUES (
    '123e4567-e89b-12d3-a456-426614174000',
    'github',
    '98765432',
    'test@example.com',
    'testuser',
    '{"name": "Test User", "avatar_url": "https://avatars.githubusercontent.com/u/98765432"}'::jsonb
);
```

## Rollback

If you need to rollback this migration:

```sql
SET search_path TO apiome, public;

-- Drop trigger first
DROP TRIGGER IF EXISTS trigger_update_external_auth_providers_updated_at ON external_auth_providers;

-- Drop function
DROP FUNCTION IF EXISTS update_external_auth_providers_updated_at();

-- Drop table
DROP TABLE IF EXISTS external_auth_providers CASCADE;
```

## Future Enhancements

1. **Multi-factor Authentication (MFA)** - Require MFA even with OAuth
2. **Provider Account Verification** - Additional verification steps for sensitive operations
3. **Account Merging** - Allow merging multiple accounts that share the same email
4. **Provider Rate Limiting** - Track failed OAuth attempts per provider
5. **Audit Logging** - Detailed audit trail of all OAuth authentication events
6. **Conditional Access** - Provider-specific access policies
7. **Token Rotation** - Automatic periodic token rotation
8. **Biometric Linking** - Link biometric authentication to OAuth accounts

