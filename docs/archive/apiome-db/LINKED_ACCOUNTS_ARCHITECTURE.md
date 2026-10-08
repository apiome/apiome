# Linked Accounts - System Architecture

## Database Relationships

```
┌─────────────────────┐
│    apiome.users        │
│  (Master Account)   │
├─────────────────────┤
│ id (UUID) PK        │
│ name                │
│ email (UNIQUE)      │
│ password            │
│ verified            │
│ enabled             │
│ created_at          │
│ updated_at          │
└──────────┬──────────┘
           │
           │ 1:N relationship
           │
           ▼
┌──────────────────────────────┐
│ apiome.external_auth_providers  │
│   (Linked OAuth Accounts)    │
├──────────────────────────────┤
│ id (UUID) PK                 │
│ user_id (FK) ────────────────┘
│ provider (VARCHAR)           
│ provider_user_id (VARCHAR)   
│ provider_email               
│ provider_username            
│ access_token (TEXT)          
│ refresh_token (TEXT)         
│ token_expires_at             
│ profile_data (JSONB)         
│ created_at                   
│ updated_at                   
│ last_login_at                
│                              
│ UNIQUE(user_id, provider)    
│ UNIQUE(provider, provider_user_id)
└──────────────────────────────┘
```

## OAuth Flow Diagram

### First-Time GitHub Login (Auto-Link)

```
┌──────────┐                    ┌──────────┐                    ┌─────────────┐
│  User    │                    │ Apiome│                   │   GitHub    │
│ (Browser)│                    │   System   │                   │    OAuth    │
└────┬─────┘                    └─────┬──────┘                   └──────┬──────┘
     │                                │                                  │
     │  Click "Login with GitHub"    │                                  │
     │───────────────────────────────>│                                  │
     │                                │                                  │
     │                                │  Redirect to GitHub OAuth        │
     │                                │─────────────────────────────────>│
     │                                │                                  │
     │              GitHub Authorization Page                            │
     │<──────────────────────────────────────────────────────────────────│
     │                                │                                  │
     │  User authorizes               │                                  │
     │───────────────────────────────────────────────────────────────────>│
     │                                │                                  │
     │                                │  Callback with auth code         │
     │                                │<─────────────────────────────────│
     │                                │                                  │
     │                                │  Exchange code for tokens        │
     │                                │─────────────────────────────────>│
     │                                │                                  │
     │                                │  Access token + profile data     │
     │                                │<─────────────────────────────────│
     │                                │                                  │
     │                                │ Check if GitHub account          │
     │                                │ exists in external_auth_providers│
     │                                │ (by provider + provider_user_id) │
     │                                │                                  │
     │                                │ NOT FOUND                        │
     │                                │                                  │
     │                                │ Check if user exists by email    │
     │                                │ in apiome.users                     │
     │                                │                                  │
     │                                │ FOUND → Auto-link:               │
     │                                │ INSERT INTO external_auth_providers│
     │                                │ (user_id, provider='github',     │
     │                                │  provider_user_id, tokens, ...)  │
     │                                │                                  │
     │                                │ Create session for user          │
     │                                │                                  │
     │  Redirect to Dashboard         │                                  │
     │<───────────────────────────────│                                  │
     │                                │                                  │
```

### Subsequent Login with Linked Account

```
┌──────────┐                    ┌──────────┐                    ┌─────────────┐
│  User    │                    │ Apiome│                   │   GitHub    │
│ (Browser)│                    │   System   │                   │    OAuth    │
└────┬─────┘                    └─────┬──────┘                   └──────┬──────┘
     │                                │                                  │
     │  Click "Login with GitHub"    │                                  │
     │───────────────────────────────>│                                  │
     │                                │                                  │
     │                                │  GitHub OAuth flow               │
     │<────────────────────────────────────────────────────────────────>│
     │                                │                                  │
     │                                │  Check if GitHub account exists  │
     │                                │  in external_auth_providers      │
     │                                │                                  │
     │                                │  FOUND → Get linked user_id      │
     │                                │                                  │
     │                                │  Update last_login_at            │
     │                                │                                  │
     │                                │  Create session for user         │
     │                                │                                  │
     │  Redirect to Dashboard         │                                  │
     │<───────────────────────────────│                                  │
     │                                │                                  │
```

### Manual Account Linking (From Dashboard)

```
┌──────────┐                    ┌──────────┐                    ┌─────────────┐
│  User    │                    │ Apiome│                   │   GitHub    │
│ (Logged  │                    │   System   │                   │    OAuth    │
│   In)    │                    │            │                   │             │
└────┬─────┘                    └─────┬──────┘                   └──────┬──────┘
     │                                │                                  │
     │  Navigate to Linked Accounts   │                                  │
     │───────────────────────────────>│                                  │
     │                                │                                  │
     │  Linked Accounts Page          │                                  │
     │  (Shows available providers)   │                                  │
     │<───────────────────────────────│                                  │
     │                                │                                  │
     │  Click "Link" for GitHub       │                                  │
     │───────────────────────────────>│                                  │
     │                                │                                  │
     │                                │  Redirect to GitHub OAuth        │
     │                                │─────────────────────────────────>│
     │                                │                                  │
     │  GitHub OAuth flow             │                                  │
     │<────────────────────────────────────────────────────────────────>│
     │                                │                                  │
     │                                │  Get current session user_id     │
     │                                │                                  │
     │                                │  Check if provider already linked│
     │                                │  for this user                   │
     │                                │                                  │
     │                                │  If NOT linked:                  │
     │                                │  INSERT INTO external_auth_providers│
     │                                │  (user_id, provider, ...)        │
     │                                │                                  │
     │  Redirect to Linked Accounts   │                                  │
     │  ?linked=true                  │                                  │
     │<───────────────────────────────│                                  │
     │                                │                                  │
     │  Success message displayed     │                                  │
     │                                │                                  │
```

### Account Unlinking

```
┌──────────┐                    ┌──────────┐
│  User    │                    │ Apiome│
│ (Logged  │                    │   System   │
│   In)    │                    │            │
└────┬─────┘                    └─────┬──────┘
     │                                │
     │  Navigate to Linked Accounts   │
     │───────────────────────────────>│
     │                                │
     │  Linked Accounts Page          │
     │  (Shows linked accounts)       │
     │<───────────────────────────────│
     │                                │
     │  Click "Unlink" for GitHub     │
     │───────────────────────────────>│
     │                                │
     │  Confirmation Dialog           │
     │<───────────────────────────────│
     │                                │
     │  User confirms                 │
     │───────────────────────────────>│
     │                                │
     │                                │  Verify ownership:
     │                                │  DELETE FROM external_auth_providers
     │                                │  WHERE id = ? AND user_id = ?
     │                                │
     │  Success message               │
     │<───────────────────────────────│
     │                                │
     │  Updated list (without GitHub) │
     │<───────────────────────────────│
     │                                │
```

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Dashboard Layout                          │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐│
│  │  DashboardSideNav    │  │       Main Content Area          ││
│  │                      │  │                                   ││
│  │  Account             │  │  /ade/dashboard/linked-accounts  ││
│  │  ├─ Profile          │  │                                   ││
│  │  └─ Linked Accounts ◄┼──┼─>  LinkedAccountsPage            ││
│  │                      │  │      │                            ││
│  │  Administration      │  │      ├─ List linked accounts     ││
│  │  ├─ Tenants          │  │      ├─ Link new providers       ││
│  │  └─ API Keys         │  │      └─ Unlink accounts          ││
│  │                      │  │                                   ││
│  │  Specifications      │  │      Uses:                        ││
│  │  ├─ Projects         │  │      • getLinkedAccountsForUser()││
│  │  ├─ Versions         │  │      • unlinkExternalAccount()   ││
│  │  └─ Published        │  │      • useDialog() confirmation  ││
│  └──────────────────────┘  └──────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Reading Linked Accounts

```
LinkedAccountsPage
       │
       │ useEffect()
       │
       ▼
getLinkedAccountsForUser(userId)
       │
       │ server-side function
       │
       ▼
SELECT * FROM apiome.external_auth_providers
WHERE user_id = ?
       │
       ▼
[ { provider: 'github', provider_username: '...', ... } ]
       │
       ▼
Display in UI
```

### Linking an Account

```
User clicks "Link GitHub"
       │
       ▼
Redirect to /api/auth/signin/github
       │
       ▼
GitHub OAuth flow
       │
       ▼
Callback to credentialsGithub()
       │
       ├─> Check existing link by provider_user_id
       │   FOUND → Login
       │   NOT FOUND ─┐
       │              ▼
       │        linkGithubAccount(userId, account, profile)
       │              │
       │              ▼
       │        INSERT INTO apiome.external_auth_providers
       │              │
       │              ▼
       └──────> Login successful
```

### Unlinking an Account

```
User clicks "Unlink"
       │
       ▼
Confirmation dialog
       │
       ▼
unlinkExternalAccount(userId, linkedAccountId)
       │
       │ server-side function
       │
       ▼
DELETE FROM apiome.external_auth_providers
WHERE id = ? AND user_id = ?
       │
       ▼
Success → Reload linked accounts list
```

## Security Layers

```
┌─────────────────────────────────────────────┐
│         Browser (Client-Side)               │
│  • User sees UI                             │
│  • Clicks buttons                           │
│  • Cannot access database directly          │
└─────────────────┬───────────────────────────┘
                  │
                  │ Server Actions ('use server')
                  │
                  ▼
┌─────────────────────────────────────────────┐
│      Next.js Server (Server-Side)           │
│  • Session validation                       │
│  • userId extraction from session           │
│  • Calls helper functions                   │
│  • NO PUBLIC REST ENDPOINTS                 │
└─────────────────┬───────────────────────────┘
                  │
                  │ Database queries with prepared statements
                  │
                  ▼
┌─────────────────────────────────────────────┐
│           PostgreSQL Database               │
│  • apiome.users table                          │
│  • apiome.external_auth_providers table        │
│  • Unique constraints enforced              │
│  • Foreign key cascades                     │
└─────────────────────────────────────────────┘
```

## Provider Configuration

```javascript
const providerConfigs = {
  github: {
    name: 'github',
    displayName: 'GitHub',
    icon: Github,
    color: '#24292e',
    available: true,  // ✓ Active
  },
  gitlab: {
    name: 'gitlab',
    displayName: 'GitLab',
    icon: GitBranch,
    color: '#fc6d26',
    available: false,  // Coming soon
  },
  google: {
    name: 'google',
    displayName: 'Google / GCP',
    icon: Cloud,
    color: '#4285f4',
    available: false,  // Coming soon
  },
  aws: {
    name: 'aws',
    displayName: 'AWS',
    icon: Cloud,
    color: '#ff9900',
    available: false,  // Coming soon
  },
};
```

## Error Handling

```
┌─────────────────────────────────────────────┐
│  User Action (Link/Unlink)                  │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  Try-Catch Block                            │
│  ├─ Success → JSON({ success: true })       │
│  └─ Error ──┐                               │
└─────────────┼───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│  Error Types                                │
│  ├─ Duplicate link → User-friendly message  │
│  ├─ Not found → User-friendly message       │
│  ├─ Database error → Generic error message  │
│  └─ Log error → console.error()             │
└─────────────┬───────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│  UI Display                                 │
│  • Error Alert (red)                        │
│  • User can retry                           │
└─────────────────────────────────────────────┘
```

## Session Management

```
User logs in via GitHub
       │
       ▼
credentialsGithub() validates
       │
       ▼
NextAuth creates session
       │
       ▼
Session contains:
{
  user: {
    user_id: "uuid-from-apiome.users",
    name: "User Name",
    email: "user@example.com",
    current_tenant_id: "uuid"
  },
  expires: "2024-12-31T..."
}
       │
       ▼
All subsequent requests
include this session
       │
       ▼
Functions extract userId
from session.user.user_id
```

This architecture ensures that the user_id from `apiome.users` is ALWAYS the source of truth, and OAuth provider data is supplemental authentication information stored in `external_auth_providers`.

