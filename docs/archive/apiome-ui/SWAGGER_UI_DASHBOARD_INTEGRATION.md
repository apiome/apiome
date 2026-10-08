# Published Dashboard - Swagger UI Integration

## Summary

Added "Open Swagger" action to the published versions dashboard in the Apiome UI, allowing users to quickly access the interactive Swagger UI interface for any published version.

## Changes Made

### File: `apiome-ui/src/app/ade/dashboard/published/page.tsx`

#### 1. Added Import
- Added `FileText` icon from `lucide-react` for the Swagger action

#### 2. New Function: `getSwaggerUrl()`
```typescript
const getSwaggerUrl = (version: PublishedVersion): string => {
  const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
  return `${restApiBaseUrl}/${getAccessUrl(version)}/swagger`;
};
```
Constructs the Swagger UI URL for a given version.

#### 3. New Handler: `handleOpenSwagger()`
```typescript
const handleOpenSwagger = (version: PublishedVersion) => {
  const swaggerUrl = getSwaggerUrl(version);
  window.open(swaggerUrl, '_blank');
};
```
Opens the Swagger UI in a new browser tab.

#### 4. Updated RowActions Component
- Added `'openSwagger'` case to the switch statement in `handleChange()`
- Added `'Open Swagger'` to the labels mapping
- Added new MenuItem with purple FileText icon for "Open Swagger"

## User Experience

### Actions Dropdown
The actions dropdown for each published version now includes:
1. **Open URL** (External Link icon, blue) - Opens the raw JSON API endpoint
2. **Open Swagger** (File/Document icon, purple) - Opens the interactive Swagger UI ✨ NEW
3. **Copy URL** (Copy icon, blue) - Copies the API URL to clipboard
4. **Make Private/Public** (Lock/Globe icon) - Toggles visibility

### Visual Appearance
- Purple FileText icon for easy identification
- Consistent styling with other menu items
- Opens in new tab for convenient side-by-side viewing

## Integration with REST API

The UI now provides easy access to the Swagger UI endpoint created in the REST service:
```
/v1/{tenant-slug}/{project-slug}/{version-slug}/swagger
```

### Environment Configuration
Uses `NEXT_PUBLIC_REST_API_BASE_URL` environment variable to construct URLs:
- Production: Set to your production REST API URL
- Development: Defaults to `http://localhost:8000/v1`

## User Flow

1. Navigate to **Published Versions** dashboard
2. Find the version you want to explore
3. Click the **Actions** dropdown
4. Select **Open Swagger**
5. Swagger UI opens in a new tab with interactive schema visualization

## Benefits

✅ **Quick Access** - One-click access to Swagger UI from dashboard  
✅ **Consistency** - Same authentication flow (API keys for private versions)  
✅ **Convenience** - Opens in new tab, allowing side-by-side work  
✅ **Visual Clarity** - Purple FileText icon distinguishes from JSON endpoint  
✅ **Intuitive** - Natural addition to existing actions menu  

## Testing

To test the new feature:

1. **Start both services:**
   ```bash
   # Terminal 1 - REST API
   cd apiome-rest
   uv run uvicorn src.app.main:app --reload
   
   # Terminal 2 - UI
   cd apiome-ui
   npm run dev
   ```

2. **Navigate to Published Versions:**
   ```
   http://localhost:3000/ade/dashboard/published
   ```

3. **Click Actions → Open Swagger** for any published version

4. **Verify:**
   - Swagger UI opens in new tab
   - Schemas are displayed correctly
   - Private versions work with API keys
   - Public versions work without authentication

## Environment Variables

Make sure to set in `apiome-ui/.env.local`:
```env
NEXT_PUBLIC_REST_API_BASE_URL=http://localhost:8000/v1
```

For production:
```env
NEXT_PUBLIC_REST_API_BASE_URL=https://api.yourdomain.com/v1
```

## Files Modified

1. `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/dashboard/published/page.tsx`

## Screenshot of Changes

```
Actions Dropdown:
┌─────────────────────────┐
│ Select action           │
├─────────────────────────┤
│ 🔗 Open URL            │
│ 📄 Open Swagger        │ ← NEW!
│ 📋 Copy URL            │
│ 🔒 Make Private        │
└─────────────────────────┘
```

## Next Steps

Users can now:
1. Quickly access Swagger UI for schema exploration
2. Share Swagger URLs with team members
3. Use Swagger UI for API documentation
4. Test and understand complex nested structures visually

---

## Implementation Complete ✓

The published versions dashboard now seamlessly integrates with the Swagger UI endpoint, providing users with a professional, interactive way to explore and document their OpenAPI schemas directly from the dashboard.

