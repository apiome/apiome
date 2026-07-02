# Quick Testing Guide - SSO Repository Browser

## Prerequisites
- Have at least one linked GitHub account
- If no accounts are linked, go to `/ade/dashboard/linked-accounts` and link one

## Test Flow (5 minutes)

### Test 1: Access the SSO Browser ✨

1. Navigate to **Projects** page (`/ade/dashboard/projects`)
2. Click **"Import from OpenAPI"** button
3. In the dialog, click the **"From SSO"** tab
4. **Expected**: You should see your linked accounts listed

### Test 2: Browse Repositories 📚

1. Click on your **GitHub** account card
2. **Expected**: 
   - Loading spinner appears briefly
   - Mock repositories are displayed:
     - "sample-api" - Sample API with OpenAPI specification
     - "my-project" - My project repository

### Test 3: Navigate Back to Accounts ⬅️

1. Click the **"← Back to Accounts"** button
2. **Expected**: Returns to account selection screen

### Test 4: Browse Repository Files 📁

1. Click on GitHub account again
2. Click on **"sample-api"** repository
3. **Expected**:
   - Loading spinner appears briefly
   - Files and directories are displayed:
     - 📁 `api` (directory - gray)
     - 📄 `openapi.json` (file - **green** for OpenAPI)
     - 📁 `docs` (directory - gray)
     - 📄 `swagger.yaml` (file - **green** for OpenAPI)

### Test 5: Navigate into Directory 📂

1. Click on the **`api`** directory (folder icon)
2. **Expected**: 
   - Breadcrumb shows "Path: /api"
   - Directory contents load (mock data will show similar files)

### Test 6: Navigate Back from Directory ⬅️

1. Click the **"← Back"** button
2. **Expected**: Returns to repository root (no path shown)

### Test 7: Import OpenAPI File 🎯

1. Ensure you're at repository root
2. Click on **`openapi.json`** (green file icon)
3. **Expected**:
   - Loading spinner appears
   - File content is fetched
   - Dialog proceeds to "Select Classes to Import" step
   - Shows "Sample API" specification
   - Source chip shows: "github:username/sample-api/openapi.json"

### Test 8: Complete Import ✅

1. Select classes to import
2. Click **"Next"** through the steps
3. Fill in project details
4. Click **"Import Project"**
5. **Expected**: Project is created successfully

## Visual Verification Checklist

### Account Selection Screen
- [ ] Provider icons show in brand colors (GitHub black)
- [ ] Account username/email is displayed
- [ ] Cards have hover effect (border changes to blue)
- [ ] Chevron (>) appears on right side

### Repository Selection Screen
- [ ] "Back to Accounts" button visible at top
- [ ] Repository names are bold
- [ ] Descriptions appear below names
- [ ] Cards have hover effect
- [ ] Chevron (>) appears on right side

### File Browser Screen
- [ ] "Back" button visible at top
- [ ] Repository info box shows repo name and path
- [ ] Folders have folder icon (📁)
- [ ] OpenAPI files have **green** file icon
- [ ] Other files have gray file icon
- [ ] Directories show chevron (>)
- [ ] Cards have hover effect

### Loading States
- [ ] Spinner appears when loading repositories
- [ ] Spinner appears when loading files
- [ ] Spinner appears when fetching file content
- [ ] UI is disabled during loading

## Error Cases to Test

### Test 9: No Linked Accounts ⚠️

1. Ensure no accounts are linked (or test with a fresh user)
2. Open Import dialog
3. Try to click "From SSO" tab
4. **Expected**: Tab is disabled (grayed out)

### Test 10: Back Navigation Edge Cases 🔄

1. Navigate: Account → Repo → Directory
2. Click Back → Should go to parent directory
3. Click Back again → Should go to repository list
4. Click Back again → Should go to account list

## Common Issues & Solutions

### Issue: SSO tab is disabled
**Fix**: Link an account at `/ade/dashboard/linked-accounts`

### Issue: No repositories showing
**Current**: Using mock data, so repositories should always appear
**Future**: Check OAuth token permissions

### Issue: Files not loading
**Current**: Using mock data, so files should always appear
**Future**: Check repository permissions

### Issue: Can't import file
**Current**: Mock data provides valid OpenAPI spec
**Check**: Verify file has green icon (indicates OpenAPI file)

## Mock Data Reference

The browser currently uses this mock data:

### Repositories
```
1. sample-api
   Description: Sample API with OpenAPI specification
   Default branch: main

2. my-project
   Description: My project repository
   Default branch: main
```

### Files (in any repository)
```
📁 api/          (directory)
📄 openapi.json  (OpenAPI file - green icon)
📁 docs/         (directory)
📄 swagger.yaml  (OpenAPI file - green icon)
```

### OpenAPI Content
```json
{
  "openapi": "3.0.0",
  "info": {
    "title": "Sample API",
    "version": "1.0.0",
    "description": "A sample API imported from GitHub"
  },
  "paths": {
    "/users": { ... }
  },
  "components": {
    "schemas": {
      "User": { ... }
    }
  }
}
```

## Expected Behavior Summary

| Action | Expected Result |
|--------|----------------|
| Click account | Load repositories |
| Click repository | Load files |
| Click directory | Navigate into directory |
| Click OpenAPI file | Import file |
| Click Back (in subdir) | Go to parent directory |
| Click Back (in root) | Go to repository list |
| Click Back to Accounts | Go to account list |

## Success Criteria

✅ All navigation flows work smoothly
✅ Visual indicators are correct (colors, icons)
✅ Loading states appear and disappear
✅ OpenAPI files are identified correctly
✅ Import completes successfully
✅ No console errors
✅ Source is tracked correctly

## Time Estimate

- Full test: **5 minutes**
- Quick smoke test: **2 minutes**
- Edge cases: **3 minutes**

## Browser DevTools Check

Open browser console and verify:
- [ ] No red errors
- [ ] API calls to `/api/sso/github/*` succeed
- [ ] Responses contain expected data
- [ ] No React warnings

## Next Steps After Testing

If everything works:
1. ✅ Mark feature as "Complete with Mock Data"
2. 📝 Document any issues found
3. 🚀 Plan real GitHub API integration
4. 🎨 Consider UI enhancements based on feedback

If issues are found:
1. 📝 Document the issue
2. 🔍 Check browser console for errors
3. 🛠️ Debug and fix
4. ✅ Re-test

---

**Happy Testing! 🎉**

