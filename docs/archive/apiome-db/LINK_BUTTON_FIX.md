# Link Button Fix - Implementation Summary

## Problem
Clicking the "Link" button next to GitHub in the Linked Accounts page was not working. The button would redirect to the dashboard without triggering the GitHub OAuth flow, and no database entry was created.

## Root Cause
The original implementation used a server-side redirect (`window.location.href`) that would navigate to an API endpoint which then redirected to the OAuth signin page. This approach had issues:

1. The redirect chain was breaking
2. The cookie wasn't being set before the OAuth flow started
3. NextAuth's internal flow wasn't being triggered properly

## Solution Implemented

### 1. Split the Flow into Two Steps

**Step 1: Set the Cookie (Server-Side API)**
- Endpoint: `/api/auth/link/[provider]/route.ts`
- Returns JSON response (not a redirect)
- Sets `oauth_link_intent` cookie with user info
- Returns success status to client

**Step 2: Trigger OAuth (Client-Side)**
- Use NextAuth's `signIn()` function from `next-auth/react`
- This properly initiates the GitHub OAuth flow
- The cookie is already set from Step 1
- OAuth callback can read the cookie and link the account

### 2. Updated Files

#### `/api/auth/link/[provider]/route.ts`
```typescript
// NOW: Returns JSON, sets cookie
export async function GET(request, { params }) {
  const session = await getServerSession(authOptions);
  const { provider } = await params;
  const userId = session.user.user_id;

  // Return JSON (not redirect)
  const response = NextResponse.json({
    success: true,
    provider,
    userId
  });

  // Set cookie
  response.cookies.set('oauth_link_intent', JSON.stringify({
    userId,
    provider,
    timestamp: Date.now()
  }), { /* options */ });

  return response;
}
```

#### `/ade/dashboard/linked-accounts/page.tsx`
```typescript
const handleLinkAccount = async (provider: string) => {
  // Step 1: Set the cookie
  const response = await fetch(`/api/auth/link/${provider}`, {
    method: 'GET',
    credentials: 'include', // Important!
  });

  if (!response.ok) {
    setErrorMessage('Failed to initiate account linking');
    return;
  }

  // Step 2: Trigger OAuth with signIn()
  signIn(provider, {
    callbackUrl: '/ade/dashboard/linked-accounts',
  });
};
```

### 3. Flow Diagram

```
User clicks "Link" button
         ↓
[1] Fetch /api/auth/link/github
         ↓
    Server sets oauth_link_intent cookie
         ↓
    Server returns { success: true }
         ↓
[2] Client calls signIn('github', {...})
         ↓
    NextAuth redirects to GitHub OAuth
         ↓
    User authorizes on GitHub
         ↓
    GitHub redirects back to callback
         ↓
    NextAuth signIn callback executes
         ↓
    Checks for oauth_link_intent cookie
         ↓
    Cookie found! This is a LINK operation
         ↓
    Calls linkGithubAccount(userId, account, profile)
         ↓
    Inserts into apiome.external_auth_providers
         ↓
    Redirects to /ade/dashboard/linked-accounts?linked=true
         ↓
    Success message displayed!
```

## Key Changes

### Before:
```typescript
// ❌ Direct redirect - doesn't work properly
const handleLinkAccount = (provider: string) => {
  window.location.href = `/api/auth/link/${provider}`;
};
```

### After:
```typescript
// ✅ Two-step process with proper cookie handling
const handleLinkAccount = async (provider: string) => {
  // Set cookie first
  await fetch(`/api/auth/link/${provider}`, { 
    credentials: 'include' 
  });
  
  // Then trigger OAuth
  signIn(provider, { 
    callbackUrl: '/ade/dashboard/linked-accounts' 
  });
};
```

## Testing Steps

1. **Open DevTools** (F12) - Network tab
2. **Login** to your account
3. **Navigate** to Dashboard → Linked Accounts
4. **Click** "Link" button next to GitHub
5. **Observe** in Network tab:
   - ✅ Call to `/api/auth/link/github` (Status 200)
   - ✅ Call to `/api/auth/signin/github` (Redirect to GitHub)
6. **Authorize** on GitHub
7. **Return** to Linked Accounts page
8. **Verify**:
   - ✅ Success message appears
   - ✅ GitHub account in list
   - ✅ Database entry created

## Debugging Tips

### If Link Button Does Nothing:
- Open browser console - check for JavaScript errors
- Check Network tab - verify `/api/auth/link/github` is called
- Check Next.js server logs for `[link/github]` messages

### If Redirects to Dashboard Without Linking:
- Check Application → Cookies in DevTools
- Verify `oauth_link_intent` cookie is set
- Check server logs for `[signIn] Handling GitHub account linking`

### If "Already Linked" Error:
- Account is already linked to another user
- Unlink it first, or use a different GitHub account

## Technical Details

### Cookie Settings:
```typescript
{
  httpOnly: true,              // Secure from JavaScript
  secure: NODE_ENV === 'production', // HTTPS only in prod
  maxAge: 600,                 // 10 minutes
  path: '/',                   // Available site-wide
  sameSite: 'lax'             // CSRF protection
}
```

### NextAuth Integration:
- Uses `getServerSession()` to verify authentication
- Uses `signIn()` from `next-auth/react` to trigger OAuth
- OAuth callback checks `checkLinkingIntent()` for cookie
- Returns to callbackUrl with success/error parameters

## Files Modified

1. ✅ `/api/auth/link/[provider]/route.ts` - Changed to return JSON
2. ✅ `/ade/dashboard/linked-accounts/page.tsx` - Two-step link process
3. ✅ `/lib/auth/credentials.ts` - Already had linking logic
4. ✅ `/api/auth/[...nextauth]/route.ts` - Already had callback logic

## Verification

Run the test script:
```bash
./apiome-db/scripts/test-link-button.sh
```

Expected output:
```
✓ Next.js server is running
✓ Link endpoint exists
✓ Endpoint returns JSON (correct)
✓ UI uses signIn() function
✓ UI fetches cookie endpoint first
✓ OAuth callback checks for linking intent
✅ All checks passed!
```

## Status

✅ **FIXED AND READY TO TEST**

The Link button now properly:
1. Sets the linking intent cookie
2. Triggers the GitHub OAuth flow
3. Links the account to the current user
4. Shows success message
5. Creates database entry

---

**Date:** November 21, 2025  
**Issue:** Link button not working  
**Solution:** Two-step process with proper cookie handling  
**Status:** ✅ Complete

