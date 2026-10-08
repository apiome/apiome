# CORS Configuration Fix

## Issue
Browser console shows:
```
Access to fetch at 'http://localhost:8000/v1/schema/...' from origin 'http://localhost:3000' 
has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present on the 
requested resource.
```

## Root Cause
The REST API server doesn't have CORS (Cross-Origin Resource Sharing) configured to allow requests from the browse application's origin (http://localhost:3000 or http://localhost:3001).

## Solution

### For FastAPI (apiome-rest)

Add CORS middleware to your FastAPI application:

**File**: `apiome-rest/app/main.py` or wherever your FastAPI app is initialized

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Add CORS middleware - ADD THIS SECTION
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev server (default)
        "http://localhost:3001",  # Next.js dev server (when 3000 is taken)
        # Add production origins here when deploying:
        # "https://your-production-domain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers
)

# ... rest of your app setup
```

### Quick Fix (Development Only)

For development, you can allow all origins:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ DEVELOPMENT ONLY - Don't use in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**⚠️ Warning**: `allow_origins=["*"]` is convenient for development but is a security risk in production. Always specify exact origins for production.

### After Adding CORS

1. **Restart the REST API server**:
   ```bash
   # Stop the server (Ctrl+C)
   # Start it again
   python -m uvicorn app.main:app --reload
   ```

2. **Refresh your browser**:
   - Hard refresh: Ctrl+Shift+R (Windows/Linux) or Cmd+Shift+R (Mac)
   - Or clear browser cache

3. **Verify it works**:
   - Open browser console (F12)
   - Navigate to version page
   - Should see `[SpecViewer] Successfully loaded openapi specification`
   - No CORS errors

## Testing CORS Configuration

### Test with curl (should work even without CORS)
```bash
curl http://localhost:8000/v1/schema/apiome/inline-2-application-deployment-api/1.0.0
```

### Test in browser console
```javascript
fetch('http://localhost:8000/v1/schema/apiome/inline-2-application-deployment-api/1.0.0')
  .then(r => r.json())
  .then(console.log)
  .catch(console.error)
```

If CORS is configured correctly, you should see the JSON response.

## Common CORS Configurations

### Development Setup
```python
allow_origins=[
    "http://localhost:3000",
    "http://localhost:3001",
]
```

### Production Setup
```python
import os

# Get allowed origins from environment variable
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Then set environment variable:
```bash
export CORS_ORIGINS="https://browse.yourdomain.com,https://app.yourdomain.com"
```

### Mixed (Dev + Prod)
```python
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
]

# Add production origins from environment
if prod_origins := os.getenv("CORS_ORIGINS"):
    ALLOWED_ORIGINS.extend(prod_origins.split(","))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Verification Checklist

✅ CORS middleware added to REST API  
✅ Browse app origin included in `allow_origins`  
✅ REST API server restarted  
✅ Browser cache cleared  
✅ No CORS errors in browser console  
✅ Specifications load successfully  

## Enhanced Error Detection

The SpecViewer component now:
- ✅ Detects CORS errors automatically
- ✅ Shows "🔧 CORS Fix Required" when CORS error detected
- ✅ Displays exact code to add to REST API
- ✅ Shows the origin that needs to be allowed
- ✅ Provides step-by-step fix instructions
- ✅ Auto-expands troubleshooting section for CORS errors

## Alternative: Proxy (Not Recommended)

You could use Next.js rewrites to proxy requests, but this is more complex and not recommended:

```javascript
// next.config.js
module.exports = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/:path*',
      },
    ]
  },
}
```

**Why not recommended**: 
- Requires changing API URLs in code
- Doesn't solve the problem for production
- CORS is the standard solution

## Status: READY FOR FIX

1. Add the CORS middleware code above to your REST API
2. Restart the REST API server
3. Refresh the browse application
4. Specifications should now load! 🎉

The browse application will now show a helpful CORS fix guide when it detects this specific error.

