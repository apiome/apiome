# SwaggerHub Import Feature

## Overview

The SwaggerHub import feature allows users to import OpenAPI specifications directly from SwaggerHub, supporting both public and private APIs with API key authentication.

## Features

### 1. Public API Import
- Import public OpenAPI specifications from SwaggerHub without authentication
- Support for any public API on SwaggerHub
- Automatic fetching of latest version or specific version

### 2. Private API Import  
- Import private APIs using SwaggerHub API keys
- Secure API key input with show/hide toggle
- Clear error messages for authentication issues

### 3. Version Management
- Option to use latest version automatically
- Ability to specify exact version (e.g., 1.0.0, 2.1.0-rc.1)
- Support for semantic versioning formats

### 4. Validation
- Real-time validation of owner/organization names
- API name format validation
- Version format validation
- Clear error messages for invalid inputs

### 5. Test & Fetch
- Test connection before importing
- Preview API metadata (title, description, version)
- Format validation before analysis

## Usage

### Accessing SwaggerHub Import

1. Open the Import dialog
2. Select "SwaggerHub" from the import source options
3. The SwaggerHub import panel will be displayed

### Importing a Public API

1. **Enter Owner/Organization**: The SwaggerHub organization or user name (e.g., `swagger-api`)
2. **Enter API Name**: The API name (e.g., `petstore`)
3. **Select Version**: 
   - Check "Use latest version" to automatically fetch the latest
   - Uncheck and enter specific version (e.g., `1.0.0`)
4. Click **"Test & Fetch"** to validate and retrieve the specification
5. Review the metadata preview
6. Click **"Analyze →"** to proceed with import

### Importing a Private API

1. Follow steps 1-3 above
2. **Enter API Key**: In the "API Key (for private APIs)" section, enter your SwaggerHub API key
3. Click **"Test & Fetch"**
4. Continue with analysis and import

### Getting a SwaggerHub API Key

1. Log into your SwaggerHub account
2. Go to Account Settings → API Keys
3. Generate a new API key
4. Copy and paste into the import dialog

📚 [SwaggerHub API Key Documentation](https://support.smartbear.com/swaggerhub/docs/en/get-started/api-keys.html)

## Technical Details

### File Structure

```
apiome-ui/
├── src/app/
│   ├── components/ade/dashboard/
│   │   ├── ImportDialog.tsx           # Main import dialog (updated)
│   │   └── SwaggerHubImportPanel.tsx  # SwaggerHub import panel (new)
│   └── utils/
│       └── swaggerhub-import.ts       # SwaggerHub API utility (new)
└── tests/
    └── swaggerhub-import.test.ts      # Tests (new)
```

### API Endpoints

The utility communicates with the SwaggerHub API:

**Base URL**: `https://api.swaggerhub.com`

**Endpoints Used**:
- `GET /apis/{owner}/{api}/{version}` - Fetch specific API version
- `GET /apis/{owner}/{api}` - Get API info and latest version

### Authentication

For private APIs, authentication is handled via the `Authorization` header:

```typescript
headers: {
  'Authorization': 'YOUR_API_KEY_HERE'
}
```

### Validation Rules

#### Owner/Organization Name
- Required
- Format: Alphanumeric, hyphens, underscores only
- Regex: `/^[a-zA-Z0-9_-]+$/`
- Examples: `myorg`, `swagger-api`, `my_organization`

#### API Name
- Required
- Format: Alphanumeric, hyphens, underscores only
- Regex: `/^[a-zA-Z0-9_-]+$/`
- Examples: `petstore`, `user-api`, `my_service`

#### Version
- Optional (uses latest if not specified)
- Format: Alphanumeric, dots, hyphens, underscores
- Regex: `/^[a-zA-Z0-9._-]+$/`
- Examples: `1.0.0`, `2.1.0`, `1.0.0-rc.1`, `v2.3.4`

### Error Handling

The implementation handles various error scenarios:

| Error Code | Description | User Message |
|------------|-------------|--------------|
| 401 | Unauthorized | "Authentication failed. Please check your API key." |
| 403 | Forbidden | "Access denied. This API may be private or your API key lacks permissions." |
| 404 | Not Found | "API not found: {owner}/{api}/{version}" |
| Other | Network/Server | "Failed to fetch specification: {status} {statusText}" |

### State Management

The SwaggerHub import uses the following state variables in `ImportDialog.tsx`:

```typescript
const [swaggerHubContent, setSwaggerHubContent] = useState<string | null>(null);
const [swaggerHubFilename, setSwaggerHubFilename] = useState<string | null>(null);
const [swaggerHubMetadata, setSwaggerHubMetadata] = useState<FileMetadataPreview | null>(null);
```

### Integration Flow

```
User selects SwaggerHub
    ↓
SwaggerHubImportPanel displayed
    ↓
User enters owner, api, version (optional), API key (optional)
    ↓
Click "Test & Fetch"
    ↓
validateSwaggerHubOptions() validates inputs
    ↓
fetchFromSwaggerHub() calls SwaggerHub API
    ↓
Success: Display metadata preview
    ↓
Click "Analyze →"
    ↓
handleAnalyze() processes content
    ↓
Standard import flow continues
```

## Component Architecture

### SwaggerHubImportPanel

**Props**:
```typescript
interface SwaggerHubImportPanelProps {
  onSpecificationFetched: (content: string, filename: string, metadata?: FileMetadataPreview) => void;
}
```

**Features**:
- Real-time input validation
- Show/hide API key toggle
- Latest version checkbox
- Test & Fetch button with loading state
- Success/error result display
- Metadata preview

### swaggerhub-import.ts Utility

**Main Functions**:

1. `validateSwaggerHubOptions(options)` - Validates import options
2. `fetchFromSwaggerHub(options)` - Fetches specification from SwaggerHub
3. `searchSwaggerHubApis(query, apiKey?)` - Searches SwaggerHub APIs (future use)

**Interfaces**:

```typescript
interface SwaggerHubImportOptions {
  owner: string;
  api: string;
  version?: string;
  apiKey?: string;
}

interface SwaggerHubImportResult {
  success: boolean;
  content?: string;
  filename?: string;
  version?: string;
  error?: string;
  isPrivate?: boolean;
}
```

## Testing

### Test Coverage

The feature includes 24 tests covering:
- ✅ Input validation (13 tests)
- ✅ URL construction (2 tests)
- ✅ Import flow scenarios (5 tests)
- ✅ Version resolution (2 tests)
- ✅ API key handling (2 tests)

### Running Tests

```bash
yarn test swaggerhub-import
```

### Test Results

```
Test Suites: 1 passed
Tests:       24 passed
```

## Examples

### Example 1: Import Public Swagger Petstore API

```
Owner: swagger-api
API Name: petstore
Version: [Use latest version] ✓
API Key: [empty]
```

### Example 2: Import Specific Version

```
Owner: myorg
API Name: user-service
Version: 2.1.0
API Key: [empty]
```

### Example 3: Import Private API

```
Owner: mycompany
API Name: internal-api
Version: [Use latest version] ✓
API Key: abc123def456...
```

## Best Practices

1. **Use Latest Version**: For active development, use latest version to always get the most recent spec
2. **Specific Versions**: For production imports, specify exact versions for consistency
3. **API Key Security**: Never commit API keys to version control
4. **Public APIs**: Try without API key first for public APIs
5. **Error Messages**: Read error messages carefully - they indicate whether authentication is needed

## Troubleshooting

### "Authentication failed"
- Verify your API key is correct
- Check that the API key hasn't expired
- Ensure you copied the full key

### "API not found"
- Verify the owner/organization name is correct
- Check the API name spelling
- Confirm the version exists (or use latest)
- Ensure the API is published on SwaggerHub

### "Access denied"
- The API may be private - add an API key
- Your API key may lack permissions for this API
- Contact the API owner for access

### Invalid format errors
- Remove special characters from owner/API names
- Use only letters, numbers, hyphens, underscores
- Check version format (should be like 1.0.0)

## Future Enhancements

Potential improvements for future releases:

1. **Search functionality** - Search SwaggerHub APIs by keyword
2. **Organization browsing** - List APIs for an organization
3. **Favorites** - Save frequently used APIs
4. **Bulk import** - Import multiple APIs at once
5. **Version history** - View and compare different versions
6. **API key management** - Store and manage API keys securely

## Security Considerations

- API keys are handled in memory only
- No API keys are stored or logged
- HTTPS connections to SwaggerHub API
- Clear API key input on dialog close
- No credential persistence without explicit user consent

## Compliance

The SwaggerHub import feature complies with:
- SwaggerHub API Terms of Service
- OpenAPI Specification standards
- Data privacy regulations (no data storage)

---

**Version**: 1.0.0  
**Last Updated**: January 14, 2026  
**Maintained By**: Apiome Development Team

