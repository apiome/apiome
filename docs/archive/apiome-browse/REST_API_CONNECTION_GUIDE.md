# REST API Connection Guide

## Issue
When accessing version pages like `http://localhost:3000/tenant/apiome/inline-2-application-deployment-api/1.0.0`, you may see an error loading the OpenAPI specification.

## Root Cause
The Apiome Browse application needs **two services** running:
1. **Browse Application** (Next.js) - Runs on port 3000/3001
2. **REST API** (Python/FastAPI) - Runs on port 8000

The REST API provides the OpenAPI/Arazzo/JSON Schema specifications that the browse application displays.

## Solution

### 1. Start the REST API Server

The REST API must be running for specifications to load:

```bash
# Navigate to the REST API directory
cd apiome-rest

# Start the server
python -m uvicorn app.main:app --reload
```

The server should start and show:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx] using StatReload
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### 2. Verify REST API is Running

Test the API is accessible:

```bash
curl http://localhost:8000/
```

You should see a response (likely JSON or HTML).

### 3. Test the Specification Endpoint

Try fetching a specific version:

```bash
curl http://localhost:8000/v1/schema/apiome/inline-2-application-deployment-api/1.0.0
```

This should return the OpenAPI JSON specification.

### 4. Configure Environment Variables

Ensure `.env.local` in the browse project has the correct REST API URL:

```env
# In apiome-browse/.env.local
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1
```

**Note**: The `NEXT_PUBLIC_` prefix is required for client-side access in Next.js.

### 5. Restart the Browse Application

After creating/updating `.env.local`:

```bash
# In apiome-browse directory
# Stop the dev server (Ctrl+C)
npm run dev
```

## Verification

1. ✅ REST API running: `http://localhost:8000`
2. ✅ Browse app running: `http://localhost:3000` or `http://localhost:3001`
3. ✅ Environment variable set: `NEXT_PUBLIC_REST_API_BASE_URL`
4. ✅ Can access version page without errors

## Improved Error Display

The SpecViewer component now shows:

- **API Status Check**: Automatically tests if REST API is reachable
- **Connection Warning**: Yellow banner if REST API is offline with fix instructions
- **Detailed Errors**: Better error messages showing HTTP status and response details
- **Console Logging**: Check browser console for detailed fetch logs

## Common Issues

### REST API not starting

**Error**: `ModuleNotFoundError: No module named 'app'`

**Solution**:
```bash
cd apiome-rest
pip install -r requirements.txt
# or
uv sync
```

### Port 8000 already in use

**Error**: `Address already in use`

**Solution**:
```bash
# Find process on port 8000
lsof -ti:8000

# Kill it
kill -9 $(lsof -ti:8000)

# Or use a different port
uvicorn app.main:app --reload --port 8001

# Then update .env.local
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8001/v1
```

### CORS errors in browser console

**Error**: `Access to fetch at 'http://localhost:8000/...' blocked by CORS policy`

**Solution**: The REST API should have CORS configured. Check `app/main.py` for:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Specification returns 404

**Error**: `Failed to load specification (404): Not Found`

**Possible causes**:
1. Version not published
2. Version visibility not set to 'public'
3. Incorrect tenant/project/version slug
4. Database not connected to REST API

**Check database**:
```sql
SELECT t.slug as tenant, p.slug as project, v.version_id, v.published, v.visibility
FROM apiome.versions v
JOIN apiome.projects p ON v.project_id = p.id  
JOIN apiome.tenants t ON p.tenant_id = t.id
WHERE t.slug = 'apiome'
  AND p.slug = 'inline-2-application-deployment-api'
  AND v.version_id = '1.0.0';
```

## Architecture

```
Browser
   ↓
Browse App (Next.js :3000)
   ↓ (fetches specs)
REST API (FastAPI :8000)
   ↓ (queries)
PostgreSQL Database
```

- **Browse App**: Server-side renders tenant/project/version lists from database
- **REST API**: Generates OpenAPI/Arazzo/JSON specs on-demand from database
- **Database**: Stores all version, class, and property data

## Status Indicators

The browse application now shows:

- 🟢 **Online**: REST API is accessible and healthy
- ⚠️ **Offline**: Cannot connect to REST API (shows fix instructions)
- 🔄 **Checking**: Initial connection test in progress
- ❌ **Error**: Specification fetch failed (shows detailed error)

## Next Steps

Once both services are running:

1. Browse to `http://localhost:3000` (or 3001)
2. Navigate to a version page
3. You should see three tabs: OpenAPI, Arazzo, JSON Schema
4. Each tab fetches and displays the specification
5. Use Copy/Download buttons to export specifications

## Files Created/Modified

- ✅ `.env.local` - Environment configuration with REST API URL
- ✅ `SpecViewer.tsx` - Enhanced with API health check and better errors
- ✅ `REST_API_CONNECTION_GUIDE.md` - This documentation

The browse application is now fully configured and will guide you through any connection issues! 🎉

