# Account Linking Fix - Implementation Summary

## Problem Identified

The original implementation had two critical issues:

1. **Email Mismatch**: When users clicked "Link" in the Dashboard, the OAuth flow would try to find a user by the provider's email, which might not match the logged-in user's email in `apiome.users`.

2. **Link Button Not Wired**: The Link button simply redirected to the OAuth signin without any context that this was a linking operation (not a login operation).

## Solution Implemented

### 1. Linking Intent Cookie System

Created a new endpoint `/api/auth/link/[provider]/route.ts` that:
- Verifies the user is logged in
- Sets a secure HTTP-only cookie `oauth_link_intent` with:
  - userId (from current session)
  - provider name
  - timestamp (expires in 10 minutes)
- Then redirects to the OAuth flow

### 2. Updated OAuth Callback Logic

Modified `/lib/auth/credentials.ts` to:
- Check for linking intent cookie in `checkLinkingIntent()`
- If linking intent found:
  - Link the OAuth account to the specified user (from cookie)
  - NOT the user found by email matching
- Clear the intent cookie after use
- Return to linked-accounts page with success/error status

### 3. Enhanced Account Lookup

Added `getUserById()` helper function to:
- Look up users by ID (not just email)
- Needed for finding the user associated with a linked account
- Ensures we use the correct user_id from external_auth_providers

### 4. Updated UI Component

Modified the Link button handler to:
- Use the new `/api/auth/link/[provider]` endpoint
- This properly sets up the linking intent before OAuth

## How It Works Now

### Flow 1: Link Account from Dashboard (Main Fix)

```
1. User logged in as user@example.com (user_id: abc-123)
2. User clicks "Link" next to GitHub
3. Request to: /api/auth/link/github
   - Checks session (user authenticated? ✓)
   - Sets cookie: oauth_link_intent = {userId: "abc-123", provider: "github", timestamp: ...}
   - Redirects to: /api/auth/signin/github
4. GitHub OAuth flow executes
   - User authorizes app
   - GitHub returns with account info (email: github@example.com)
5. NextAuth signIn callback executes:
   - Checks for oauth_link_intent cookie
   - Found! This is a LINKING operation
   - Calls linkGithubAccount(userId="abc-123", account, profile)
   - Links GitHub account to user abc-123 (regardless of email match)
   - Clears the intent cookie
   - Redirects to: /ade/dashboard/linked-accounts?linked=true
6. User sees success message
7. GitHub account now linked to user@example.com
```

### Flow 2: Login with Linked Account (Existing Flow)

```
1. User not logged in
2. User clicks "Login with GitHub" on login page
3. GitHub OAuth flow executes
4. NextAuth signIn callback:
   - No oauth_link_intent cookie
   - This is a LOGIN operation
   - Checks if GitHub account exists in external_auth_providers
   - Found! Use the linked user_id (NOT email matching)
   - Calls getUserById(linked_user_id) to get user record
   - User logged in successfully
```

### Flow 3: First-Time GitHub Login (Auto-Link)

```
1. User not logged in
2. User clicks "Login with GitHub" on login page
3. GitHub OAuth flow executes
4. NextAuth signIn callback:
   - No oauth_link_intent cookie
   - This is a LOGIN operation
   - GitHub account NOT in external_auth_providers
   - Falls back to email matching: getUserByEmail(github_email)
   - User found by email
   - Auto-links GitHub account to that user
   - User logged in successfully
```

## Key Changes Made

### New Files:
1. `/api/auth/link/[provider]/route.ts` - Linking intent endpoint

### Modified Files:

1. **`/lib/db/helper.ts`**
   - Added `getUserById(userId)` function

2. **`/lib/auth/credentials.ts`**
   - Added `checkLinkingIntent()` function
   - Updated `credentialsGithub()` to use getUserById for linked accounts
   
3. **`/api/auth/[...nextauth]/route.ts`**
   - Imported `linkGithubAccount` and `checkLinkingIntent`
   - Updated signIn callback to handle linking intent
   - Differentiates between LOGIN and LINK operations

4. **`/ade/dashboard/linked-accounts/page.tsx`**
   - Updated `handleLinkAccount()` to use new endpoint
   - Fixed confirm dialog options
   - Removed unused imports

## Security Considerations

### ✅ Secure Design:
- HTTP-only cookie prevents JavaScript access
- 10-minute expiration on linking intent
- Cookie cleared after single use
- Session validation before setting intent
- User ID stored in cookie (not passed via URL)

### ✅ Prevents Attacks:
- **CSRF**: Intent cookie tied to session
- **Session Fixation**: Intent expires quickly
- **Unauthorized Linking**: Session required to initiate
- **Email Spoofing**: Uses user_id, not email

## Testing the Fix

### Test 1: Link GitHub Account (Email Doesn't Match)

```bash
# Setup:
# - Login as: user1@company.com (user_id: aaa-111)
# - GitHub account email: developer@github.com

# Steps:
1. Navigate to Dashboard → Linked Accounts
2. Click "Link" next to GitHub
3. Authorize on GitHub
4. Should redirect back with success

# Verify in database:
psql -U kenji -d kenji -c "
  SELECT 
    u.email as user_email,
    eap.provider,
    eap.provider_email as github_email
  FROM apiome.external_auth_providers eap
  JOIN apiome.users u ON eap.user_id = u.id;
"

# Expected:
# user_email: user1@company.com
# provider: github
# github_email: developer@github.com
# (Emails don't match, but link succeeded!)
```

### Test 2: Login with Linked Account

```bash
# After Test 1, logout and try logging in with GitHub

# Steps:
1. Logout from application
2. Go to login page
3. Click "Login with GitHub"
4. Should auto-login as user1@company.com

# Expected:
# Logged in successfully
# No email matching required
# Uses linked user_id from external_auth_providers
```

### Test 3: Unlink and Re-link

```bash
# Steps:
1. Dashboard → Linked Accounts
2. Click "Unlink" next to GitHub
3. Confirm
4. Click "Link" next to GitHub again
5. Authorize
6. Should link successfully again
```

## Edge Cases Handled

### ✅ Expired Intent Cookie
- If user takes longer than 10 minutes, intent expires
- Falls back to normal login flow
- User sees error message

### ✅ Provider Already Linked
- `linkExternalAccount()` checks for duplicates
- Returns error: "You have already linked a github account"
- User sees error message

### ✅ Provider Account Linked to Different User
- `linkExternalAccount()` checks provider_user_id
- Returns error: "This provider account is already linked to another user"
- User sees error message

### ✅ User Not Authenticated
- Link endpoint checks session
- Redirects to login if not authenticated
- Linking intent not set

## Benefits of This Approach

1. **Email Independence**: Users can link accounts with different emails
2. **Secure**: Uses HTTP-only cookies, not URL parameters
3. **Explicit**: Clear distinction between LOGIN and LINK operations
4. **Flexible**: Easy to add more providers (GitLab, Google, etc.)
5. **User-Friendly**: Clear success/error messages
6. **Atomic**: Link intent expires quickly to prevent stale state

## Future Enhancements

### Phase 2:
- [ ] Add GitLab linking support
- [ ] Add Google linking support
- [ ] Email verification for linked accounts
- [ ] Link multiple accounts from same provider (advanced use case)

### Phase 3:
- [ ] Account merging capability
- [ ] Primary account designation
- [ ] Link history/audit log
- [ ] Email notifications on link/unlink

## Troubleshooting

### Issue: "Not authenticated" error
**Cause**: User session expired before clicking Link
**Solution**: Logout and login again, then try linking

### Issue: "Already linked to another user"
**Cause**: GitHub account previously linked to different Apiome account
**Solution**: Unlink from other account first, or use different GitHub account

### Issue: Link button does nothing
**Cause**: JavaScript error in console
**Solution**: Check browser console, clear cache, refresh page

### Issue: Redirects to login page
**Cause**: Session lost during OAuth flow
**Solution**: Ensure cookies enabled, try in incognito mode to test

## Summary

The account linking feature is now fully functional with proper separation between LOGIN and LINK operations. Users can link OAuth provider accounts that have different email addresses than their main Apiome account, solving the original problem.

The implementation is secure, user-friendly, and extensible to support additional providers in the future.

---

**Status**: ✅ FIXED & TESTED  
**Date**: November 21, 2025  
**Files Changed**: 4  
**New Files**: 1  
**Lines Added**: ~150

