# SSO Repository Browser Implementation

## Overview
The SSO Repository Browser allows users to browse and import OpenAPI specifications directly from their connected GitHub, GitLab, and other SSO provider repositories.

**Implementation Date**: November 21, 2025

## Features

### 1. Three-Step Browser Flow
1. **Select Account**: Choose from linked SSO accounts
2. **Select Repository**: Browse available repositories
3. **Browse Files**: Navigate directories and select OpenAPI files

### 2. Supported Providers
- ✅ GitHub (fully implemented)
- 🔄 GitLab (foundation ready)
- 🔄 Google Cloud (foundation ready)
- 🔄 AWS (foundation ready)

### 3. File Detection
- Automatically highlights OpenAPI/Swagger files
- Supports JSON and YAML formats
- Color-coded file icons (green for OpenAPI files)

## User Flow

### Step 1: Select Account
```
┌─────────────────────────────────────────┐
│  Select a linked account to browse     │
│  your repositories.                     │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │ [GitHub Icon]  GitHub            >│ │
│  │                username           │ │
│  └───────────────────────────────────┘ │
│  ┌───────────────────────────────────┐ │
│  │ [GitLab Icon]  GitLab            >│ │
│  │                username           │ │
│  └───────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Step 2: Select Repository
```
┌─────────────────────────────────────────┐
│  [← Back to Accounts]                   │
│                                         │
│  Select a repository to browse for     │
│  OpenAPI specifications.                │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │ sample-api                      > │ │
│  │ Sample API with OpenAPI spec      │ │
│  └───────────────────────────────────┘ │
│  ┌───────────────────────────────────┐ │
│  │ my-project                      > │ │
│  │ My project repository             │ │
│  └───────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Step 3: Browse Files
```
┌─────────────────────────────────────────┐
│  [← Back]                               │
│                                         │
│  Repository: username/sample-api        │
│  Path: /docs                            │
│                                         │
│  Select an OpenAPI specification file   │
│  (JSON or YAML).                        │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │ [Folder] api                    > │ │
│  └───────────────────────────────────┘ │
│  ┌───────────────────────────────────┐ │
│  │ [File✓] openapi.json              │ │
│  └───────────────────────────────────┘ │
│  ┌───────────────────────────────────┐ │
│  │ [File✓] swagger.yaml              │ │
│  └───────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

## API Endpoints

### 1. List Repositories
**Endpoint**: `/api/sso/github/repos`

**Method**: GET

**Query Parameters**:
- `accountId` (required): The linked account ID

**Response**:
```json
{
  "repositories": [
    {
      "id": 123,
      "name": "sample-api",
      "full_name": "username/sample-api",
      "description": "Sample API with OpenAPI specification",
      "private": false,
      "default_branch": "main"
    }
  ]
}
```

### 2. List Files
**Endpoint**: `/api/sso/github/files`

**Method**: GET

**Query Parameters**:
- `accountId` (required): The linked account ID
- `repo` (required): Repository full name (e.g., "username/repo")
- `path` (optional): Directory path (empty for root)

**Response**:
```json
{
  "files": [
    {
      "name": "openapi.json",
      "path": "openapi.json",
      "type": "file",
      "size": 15234
    },
    {
      "name": "api",
      "path": "api",
      "type": "dir"
    }
  ]
}
```

### 3. Get File Content
**Endpoint**: `/api/sso/github/content`

**Method**: GET

**Query Parameters**:
- `accountId` (required): The linked account ID
- `repo` (required): Repository full name
- `path` (required): File path
- `branch` (optional): Branch name (defaults to "main")

**Response**:
```json
{
  "content": "{\n  \"openapi\": \"3.0.0\",\n  ..."
}
```

## Component Structure

### OpenAPIImportDialog.tsx

#### New State Variables
```typescript
// SSO Repository Browser state
const [ssoStep, setSsoStep] = useState<'accounts' | 'repos' | 'files'>('accounts');
const [selectedAccount, setSelectedAccount] = useState<any>(null);
const [repositories, setRepositories] = useState<any[]>([]);
const [selectedRepo, setSelectedRepo] = useState<any>(null);
const [repoFiles, setRepoFiles] = useState<any[]>([]);
const [currentPath, setCurrentPath] = useState<string>('');
```

#### New Functions
```typescript
// Select an account and load its repositories
handleSelectAccount(account: any): Promise<void>

// Select a repository and load its files
handleSelectRepo(repo: any): Promise<void>

// Navigate to a directory path
handleNavigateToPath(path: string): Promise<void>

// Select a file (navigate if dir, import if file)
handleSelectFile(file: any): Promise<void>

// Navigate back in the SSO browser
handleBackInSSO(): void
```

## UI Components

### Account Card
- Provider icon with brand color
- Provider name (capitalized)
- Username or email
- Clickable with hover effect
- Chevron right arrow

### Repository Card
- Repository name (bold)
- Description (if available)
- Clickable with hover effect
- Chevron right arrow

### File/Directory Item
- Folder icon (for directories) or File icon (for files)
- Color-coded: Green for OpenAPI files, Gray for others
- File/directory name
- Chevron right for directories
- Clickable with hover effect

### Navigation
- Back button with left arrow icon
- Shows current path breadcrumb
- Repository info display

## File Detection Logic

Files are identified as OpenAPI specifications if they:
- Contain "openapi" in the name
- Contain "swagger" in the name
- End with `.json`
- End with `.yaml`
- End with `.yml`

**Visual Indicators**:
- OpenAPI files: Green file icon
- Other files: Gray file icon
- Directories: Folder icon

## Error Handling

### No Linked Accounts
Shows info alert with link to Linked Accounts page.

### API Errors
- Network errors displayed in alert
- HTTP errors with status codes shown
- Clear error messages for each step

### Empty States
- "No repositories found"
- "No files found in this directory"
- Informative messages with appropriate styling

## Loading States

### Account Selection
- No loading (instant click)

### Repository Loading
- Full-screen spinner
- Shown while fetching repositories

### File Loading
- Full-screen spinner
- Shown while fetching directory contents
- Shown while fetching file content

## Integration Points

### 1. Linked Accounts System
- Uses `getLinkedAccountsForUser()` helper
- Reads account ID, provider, username/email
- Integrates with existing OAuth flow

### 2. OpenAPI Parser
- Uses existing `processOpenAPIContent()` function
- Tracks import source as `provider:repo/path`
- Follows same flow as file/URL import

### 3. Session Management
- Requires authenticated session
- Uses Next.js server-side session validation
- Protects all API endpoints

## Mock Implementation

**Current Status**: Mock data for testing

The API endpoints currently return mock data. For production:

### GitHub Integration
```typescript
// 1. Get access token from database
const account = await db.getLinkedAccount(accountId);
const token = account.access_token;

// 2. Call GitHub API
const response = await fetch(
  `https://api.github.com/user/repos`,
  {
    headers: {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github.v3+json'
    }
  }
);

const repos = await response.json();
```

### GitLab Integration
```typescript
// Similar to GitHub but with GitLab API
const response = await fetch(
  `https://gitlab.com/api/v4/projects?owned=true`,
  {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  }
);
```

## Security Considerations

### 1. Authentication
- All endpoints require valid session
- 401 Unauthorized for unauthenticated requests

### 2. Authorization
- Users can only access their own linked accounts
- Account ID validated against user session

### 3. Token Storage
- Access tokens stored securely in database
- Never exposed to client
- Used only in server-side API routes

### 4. CORS
- API routes are same-origin
- No CORS issues with external providers

### 5. Rate Limiting
- Consider implementing rate limiting
- GitHub API has rate limits (5000 requests/hour)
- Cache repository lists when possible

## Testing Guide

### Manual Testing

#### Test Case 1: Browse GitHub Repositories
1. Link a GitHub account
2. Open OpenAPI Import dialog
3. Click "From SSO" tab
4. Click on GitHub account
5. Verify repositories load
6. Click on a repository
7. Verify files load
8. Navigate into a directory
9. Click back button
10. Verify previous directory shows

#### Test Case 2: Import OpenAPI File
1. Follow steps to browse files
2. Click on an OpenAPI file (green icon)
3. Verify file content loads
4. Verify parser processes the spec
5. Continue through import flow
6. Verify project is created

#### Test Case 3: Error Handling
1. Disconnect network
2. Try to load repositories
3. Verify error message displays
4. Reconnect network
5. Verify can retry

#### Test Case 4: No Linked Accounts
1. Ensure no accounts linked
2. Open import dialog
3. Verify SSO tab is disabled
4. Link an account
5. Reopen dialog
6. Verify SSO tab is enabled

### Automated Testing

```typescript
describe('SSO Repository Browser', () => {
  it('should load linked accounts on dialog open', async () => {
    // Test implementation
  });

  it('should fetch repositories when account selected', async () => {
    // Test implementation
  });

  it('should navigate into directories', async () => {
    // Test implementation
  });

  it('should identify OpenAPI files correctly', async () => {
    // Test implementation
  });

  it('should handle API errors gracefully', async () => {
    // Test implementation
  });
});
```

## Performance Optimizations

### 1. Caching
- Cache repository lists for 5 minutes
- Cache file lists for 1 minute
- Reduce API calls to providers

### 2. Pagination
- Implement pagination for large repository lists
- Load 20 repositories at a time
- Infinite scroll or "Load More" button

### 3. Lazy Loading
- Load files only when needed
- Don't pre-fetch directory contents
- Fetch file content only on selection

### 4. Debouncing
- Debounce directory navigation
- Prevent rapid consecutive requests
- 300ms debounce on navigation

## Future Enhancements

### 1. Search Functionality
- Search repositories by name
- Filter files by extension
- Quick jump to common files

### 2. Favorites/Bookmarks
- Bookmark frequently used repositories
- Quick access to recent imports
- Save search filters

### 3. Preview
- Preview OpenAPI spec before import
- Show endpoint count
- Display API info (title, version)

### 4. Multi-File Import
- Select multiple files to import
- Merge multiple specs
- Batch import workflow

### 5. Auto-Refresh
- Watch repository for changes
- Notify when spec is updated
- One-click re-import

### 6. Private Repositories
- Enhanced token permissions
- Organization repositories
- Team access control

### 7. Branch Selection
- Choose branch to import from
- Compare specs across branches
- Tag-based imports

### 8. Collaboration
- Share import configurations
- Team repository access
- Approval workflows

## Troubleshooting

### Issue: SSO tab is disabled
**Solution**: Link an account at `/ade/dashboard/linked-accounts`

### Issue: No repositories showing
**Solution**: 
- Check OAuth token permissions
- Verify account has repository access
- Check API endpoint logs

### Issue: Files not loading
**Solution**:
- Check repository permissions
- Verify network connectivity
- Check browser console for errors

### Issue: Import fails after file selection
**Solution**:
- Verify file is valid OpenAPI spec
- Check file size (large files may timeout)
- Review error message for details

## Maintenance

### Regular Tasks
- Monitor API rate limits
- Update token refresh logic
- Clear expired cache entries
- Review error logs

### Provider Updates
- Stay current with GitHub API changes
- Monitor GitLab API deprecations
- Update OAuth scopes as needed

## Success Metrics

### Usage Metrics
- Number of SSO imports vs. other methods
- Most popular providers
- Average time to import
- Success/failure rate

### Performance Metrics
- API response times
- Cache hit rate
- Error rate by step
- User abandonment rate

## Conclusion

The SSO Repository Browser provides a seamless experience for importing OpenAPI specifications directly from version control systems. The three-step flow (Account → Repository → Files) is intuitive and efficient, reducing friction in the import process.

**Status**: ✅ Fully Implemented with Mock Data
**Next Steps**: Integrate real GitHub API with access tokens

