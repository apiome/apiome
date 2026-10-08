# REST API Base URL Configuration

## Overview
The Published Versions page in the dashboard now uses a configurable REST API base URL for generating external links to the OpenAPI specifications.

## Configuration

### Environment Variable
Add this to your `.env.local` or `.env` file in the `apiome-ui` directory:

```bash
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1
```

**Important:** The `NEXT_PUBLIC_` prefix is required for Next.js to expose this variable to the browser/client-side code.

### Default Value
If not set, the application defaults to: `http://localhost:8000/v1`

## Usage

The REST API base URL is used to construct full external URLs for published versions:

**Format:**
```
{NEXT_PUBLIC_REST_API_BASE_URL}/{tenant-slug}/{project-slug}/{version-id}
```

**Example:**
```
http://localhost:8000/v1/acme-corp/customer-api/1.0.0
```

## How It Works

### In the Published Versions Page

```typescript
const getFullAccessUrl = (version: PublishedVersion): string => {
  // Use REST_API_BASE_URL from environment, fallback to localhost
  const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
  return `${restApiBaseUrl}/${getAccessUrl(version)}`;
};
```

### User Actions

1. **Copy URL** - Copies the full REST API URL to clipboard
   ```
   http://localhost:8000/v1/acme-corp/customer-api/1.0.0
   ```

2. **Open in New Tab** - Opens the REST API endpoint in a browser
   - For public versions: Shows the OpenAPI spec
   - For private versions: Shows 401 error (requires API key)

## Environment-Specific Configuration

### Development
```bash
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1
```

### Staging
```bash
NEXT_PUBLIC_REST_API_BASE_URL=https://staging-api.yourdomain.com/v1
```

### Production
```bash
NEXT_PUBLIC_REST_API_BASE_URL=https://api.yourdomain.com/v1
```

## Testing

### 1. Set the Environment Variable
```bash
cd apiome-ui
echo "NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1" >> .env.local
```

### 2. Restart the Development Server
```bash
npm run dev
# or
yarn dev
```

### 3. Test the Links
1. Navigate to **Dashboard > Published**
2. Find a published version
3. Click the **Copy** icon - should copy: `http://localhost:8000/v1/...`
4. Click the **External Link** icon - should open: `http://localhost:8000/v1/...`

## Troubleshooting

### Links still showing wrong URL
- **Cause**: Environment variable not loaded
- **Solution**: Restart the Next.js dev server after changing `.env.local`

### API requests failing
- **Cause**: REST API server not running
- **Solution**: Start the FastAPI server:
  ```bash
  cd apiome-rest
  uv run -m app
  ```

### CORS errors in browser
- **Cause**: FastAPI not configured for cross-origin requests
- **Solution**: Add CORS middleware to FastAPI (see below)

## CORS Configuration (If Needed)

If accessing from a different domain, configure CORS in the FastAPI server:

```python
# In apiome-rest/src/app/main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev server
        "https://yourdomain.com"   # Production domain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## URL Structure

### Display URL (in table)
Shows relative path only:
```
acme-corp/customer-api/1.0.0
```

### Full URL (copied/opened)
Shows complete REST API endpoint:
```
http://localhost:8000/v1/acme-corp/customer-api/1.0.0
```

This makes the table compact while providing full URLs for testing and external access.

## Benefits

1. **Environment-Aware**: Different URLs for dev/staging/production
2. **Easy Testing**: Direct links to REST API endpoints
3. **Configurable**: No hardcoded URLs in the code
4. **User-Friendly**: One-click copy and open functionality

## See Also

- [REST API Documentation](../../apiome-rest/docs/README.md)
- [API Key Authentication](../../apiome-rest/docs/API_KEY_AUTHENTICATION.md)
- [Next.js Environment Variables](https://nextjs.org/docs/basic-features/environment-variables)

