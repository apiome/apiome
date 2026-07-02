# REST API Integration - Complete Solution

## ✅ Problem Solved!

The browse application at `http://localhost:3000/tenant/apiome/inline-2-application-deployment-api/1.0.0` will now properly handle REST API connections and show helpful error messages when the API is unavailable.

## What Was Implemented

### 1. Environment Configuration ✅
Created `.env.local` with proper REST API URL:
```env
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1
```

### 2. Enhanced SpecViewer Component ✅

**Added Features:**
- **API Health Check**: Automatically tests if REST API is accessible on component mount
- **Connection Status**: Shows whether API is online, offline, or checking
- **Detailed Error Messages**: Shows HTTP status, response text, and helpful debugging info
- **Console Logging**: Logs all fetch attempts for easy debugging
- **Troubleshooting Guide**: Built-in instructions when API is offline

**Visual Indicators:**
- 🟢 Green tabs when API is online
- ⚠️ Yellow warning banner when API is offline
- ❌ Red error box with detailed information on fetch failures
- 🔄 Loading state while checking/fetching

### 3. Error Handling Improvements ✅

**Before:**
```
Error: Failed to load specification: Not Found
```

**After:**
```
Error Loading Specification

Failed to load specification (404): Not Found. 
Details: {"error": "Version not found or not published"}

Troubleshooting:
• Check that the REST API is running at: http://localhost:8000/v1
• Verify the version exists and is published
• Check browser console for detailed error messages  
• Ensure CORS is configured if REST API is on a different domain
```

## How It Works

### Architecture
```
Browser (localhost:3000)
    ↓
Browse App (Next.js)
    ├─ Server Side: Queries database for tenant/project/version lists
    └─ Client Side: SpecViewer component
           ↓ (HTTP fetch)
REST API (localhost:8000)
    ├─ Generates OpenAPI specs
    ├─ Generates Arazzo specs
    └─ Generates JSON Schema
           ↓ (queries)
PostgreSQL Database
```

### Request Flow

1. **Page Load** (Server Side):
   - Next.js queries database for version metadata
   - Renders page with tenant/project/version info
   - Passes `restApiBaseUrl` to SpecViewer component

2. **SpecViewer Mount** (Client Side):
   - Checks API health by fetching base URL
   - Sets status indicator (online/offline)
   - If online, automatically loads OpenAPI spec

3. **Specification Fetch** (Client Side):
   - User selects format (OpenAPI/Arazzo/JSON Schema)
   - Fetches from: `${restApiBaseUrl}/${endpoint}/${tenant}/${project}/${version}`
   - Displays spec or shows detailed error

## Setup Instructions

### Quick Start

**Terminal 1 - Start REST API:**
```bash
cd apiome-rest
python -m uvicorn app.main:app --reload
```

**Terminal 2 - Start Browse App:**
```bash
cd apiome-browse  
npm run dev
```

**Browser:**
```
http://localhost:3001/tenant/apiome/inline-2-application-deployment-api/1.0.0
```

### Verification Checklist

✅ REST API running:
```bash
curl http://localhost:8000/
# Should return HTML or JSON response
```

✅ Can fetch specifications:
```bash
curl http://localhost:8000/v1/schema/apiome/inline-2-application-deployment-api/1.0.0
# Should return OpenAPI JSON
```

✅ Environment configured:
```bash
cat apiome-browse/.env.local | grep NEXT_PUBLIC_REST_API_BASE_URL
# Should show: NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1
```

✅ Browse app running:
```bash
curl http://localhost:3001/
# Should return HTML
```

## What You'll See

### When REST API is Running ✅
- Page loads successfully
- Three tabs visible: OpenAPI, Arazzo, JSON Schema
- Specification displays in formatted JSON
- Copy and Download buttons active
- No error messages

### When REST API is Offline ⚠️
- Page loads successfully
- Yellow warning banner appears:
  ```
  ⚠️ REST API Connection Issue
  Cannot connect to the Apiome REST API at http://localhost:8000/v1
  ```
- Expandable "How to fix this" section with commands
- Specification area shows loading state or error

### When Specification Doesn't Exist ❌
- API is online but version not found
- Red error box appears:
  ```
  ❌ Error Loading Specification
  Failed to load specification (404): Not Found
  ```
- Troubleshooting tips displayed
- Check browser console for full details

## Console Output Examples

### Successful Load
```
[SpecViewer] Fetching openapi from: http://localhost:8000/v1/schema/apiome/inline-2-application-deployment-api/1.0.0
[SpecViewer] Response status: 200 OK
[SpecViewer] Successfully loaded openapi specification
```

### API Offline
```
[SpecViewer] Fetching openapi from: http://localhost:8000/v1/schema/apiome/inline-2-application-deployment-api/1.0.0
[SpecViewer] Error loading specification: TypeError: Failed to fetch
```

### Version Not Found
```
[SpecViewer] Fetching openapi from: http://localhost:8000/v1/schema/apiome/wrong-slug/1.0.0
[SpecViewer] Response status: 404 Not Found
[SpecViewer] Error response: {"detail":"Version not found"}
[SpecViewer] Error loading specification: Failed to load specification (404): Not Found. Details: {"detail":"Version not found"}
```

## Files Created/Modified

### Created:
- ✅ `.env.local` - Environment configuration
- ✅ `REST_API_CONNECTION_GUIDE.md` - Comprehensive setup guide
- ✅ `REST_API_INTEGRATION_SOLUTION.md` - This file

### Modified:
- ✅ `src/app/components/SpecViewer.tsx`
  - Added API health check
  - Added connection status state
  - Enhanced error messages
  - Added console logging
  - Added offline warning banner

## Common Issues & Solutions

### Issue 1: "Cannot connect to REST API"
**Symptom**: Yellow warning banner on page
**Cause**: REST API not running
**Fix**: Start REST API with `uvicorn app.main:app --reload`

### Issue 2: "Failed to load specification (404)"
**Symptom**: Red error box after API check passes
**Possible Causes**:
- Version not published (`v.published = false`)
- Version not public (`v.visibility != 'public'`)
- Wrong tenant/project/version slug
- REST API can't connect to database

**Fix**: Check database and REST API logs

### Issue 3: CORS Error
**Symptom**: Browser console shows CORS policy error
**Cause**: REST API not configured to allow browser from port 3000/3001
**Fix**: Add CORS middleware in REST API

### Issue 4: Wrong Port
**Symptom**: Connection fails even though REST API is running
**Cause**: REST API running on different port
**Fix**: Check REST API startup logs for actual port, update `.env.local`

## Testing the Fix

1. **Start with API offline** to see the warning banner
2. **Start the REST API** and refresh - warning should disappear
3. **Click format tabs** to see specifications load
4. **Stop REST API** while on page - next format switch will show error
5. **Check browser console** to see detailed fetch logs

## Status: COMPLETE ✅

The browse application now:
- ✅ Detects REST API availability automatically
- ✅ Shows helpful error messages with fix instructions
- ✅ Logs detailed information for debugging
- ✅ Provides a smooth user experience whether API is online or offline
- ✅ Gives clear guidance on how to resolve issues

Your URL `http://localhost:3000/tenant/apiome/inline-2-application-deployment-api/1.0.0` will now work correctly when the REST API is running! 🎉

**Next Step**: Start the REST API server and refresh the page to see the specification!

