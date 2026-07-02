# 🧪 Linked Accounts Feature - Testing Checklist

## ✅ Pre-Flight Checks (Completed)

- [x] Database table `external_auth_providers` created
- [x] All 13 columns present
- [x] 9 indexes created
- [x] 8 constraints enforced
- [x] Update trigger configured
- [x] Linked Accounts page created
- [x] Navigation menu updated
- [x] Helper functions implemented
- [x] GitHub OAuth configured
- [x] Next.js server running

## 🎯 Manual Testing Guide

### Test 1: First-Time GitHub Login (Auto-Link)

**Steps:**
1. Open: http://localhost:3000/login
2. Click "Sign in with GitHub"
3. Authorize the application on GitHub
4. Should be logged in and redirected

**Expected Results:**
- ✓ Successfully logged in
- ✓ GitHub account auto-linked to user
- ✓ Can access dashboard

**Verify in Database:**
```sql
SELECT 
    eap.provider,
    eap.provider_username,
    eap.provider_email,
    u.name,
    u.email,
    eap.created_at,
    eap.last_login_at
FROM apiome.external_auth_providers eap
JOIN apiome.users u ON eap.user_id = u.id
ORDER BY eap.created_at DESC;
```

---

### Test 2: View Linked Accounts

**Steps:**
1. While logged in, navigate to Dashboard
2. Click on "Linked Accounts" in the sidebar (under Account section)
3. Should see the linked accounts page

**Expected Results:**
- ✓ Page loads successfully
- ✓ GitHub account is listed
- ✓ Shows GitHub username/email
- ✓ Shows "Linked" date
- ✓ Shows "Last login" date
- ✓ "Unlink" button is visible

**Screenshot Location:**
`Dashboard → Account → Linked Accounts`

---

### Test 3: Subsequent Login with GitHub

**Steps:**
1. Log out from the application
2. Go to: http://localhost:3000/login
3. Click "Sign in with GitHub"
4. Should auto-login without re-authorization

**Expected Results:**
- ✓ Fast login (no re-authorization needed)
- ✓ Last login timestamp updated in database
- ✓ Redirected to dashboard

**Verify in Database:**
```sql
SELECT 
    provider,
    provider_username,
    last_login_at,
    created_at
FROM apiome.external_auth_providers
WHERE provider = 'github'
ORDER BY last_login_at DESC;
```

The `last_login_at` should be more recent than `created_at`.

---

### Test 4: Unlink GitHub Account

**Steps:**
1. Go to: Dashboard → Linked Accounts
2. Find your GitHub account in the list
3. Click the "Unlink" button
4. Confirm in the dialog

**Expected Results:**
- ✓ Confirmation dialog appears
- ✓ After confirming, account is removed from list
- ✓ Success message displayed
- ✓ GitHub account no longer appears in linked accounts

**Verify in Database:**
```sql
-- Should return 0 rows after unlinking
SELECT COUNT(*) FROM apiome.external_auth_providers WHERE provider = 'github';
```

---

### Test 5: Re-link After Unlinking

**Steps:**
1. After unlinking, stay on the Linked Accounts page
2. Click "Link" button next to GitHub
3. Authorize on GitHub (if needed)
4. Should redirect back with success

**Expected Results:**
- ✓ OAuth flow completes
- ✓ GitHub account re-appears in linked list
- ✓ Success message displayed
- ✓ Can still login with GitHub

---

### Test 6: Prevent Duplicate Links

**Steps:**
1. While logged in with a linked GitHub account
2. Open a private/incognito browser
3. Log in with a different Apiome account
4. Try to link the same GitHub account

**Expected Results:**
- ✓ Error message: "This provider account is already linked to another user"
- ✓ Account is NOT linked
- ✓ Original link remains intact

---

### Test 7: Prevent Multiple Links Per Provider

**Steps:**
1. Link GitHub account to your user
2. Try to link GitHub again (same or different GitHub account)

**Expected Results:**
- ✓ Error message: "You have already linked a github account"
- ✓ Only one GitHub link per user allowed

---

### Test 8: Navigation and UI

**Steps:**
1. Check the Dashboard sidebar
2. Verify "Linked Accounts" appears under "Account" section
3. Check it's between "Profile" and the "Administration" section

**Expected Results:**
- ✓ Menu item visible
- ✓ Icon displays correctly (Link icon)
- ✓ Highlights when active
- ✓ Proper spacing and styling

---

### Test 9: Empty State

**Steps:**
1. Create a new user without any linked accounts
2. Go to Linked Accounts page

**Expected Results:**
- ✓ Empty state message displayed
- ✓ "No linked accounts" message
- ✓ Suggestion to link an account
- ✓ Link icon displayed
- ✓ Available providers section still visible

---

### Test 10: Available Providers Display

**Steps:**
1. Go to Linked Accounts page
2. Scroll to "Available Providers" section

**Expected Results:**
- ✓ GitHub shows as available (with "Link" button)
- ✓ GitLab shows "Coming soon"
- ✓ Google/GCP shows "Coming soon"
- ✓ AWS shows "Coming soon"
- ✓ All have proper icons and styling

---

## 🔒 Security Testing

### Security Test 1: Server-Side Only Operations

**Verify:**
```bash
# Should NOT find any public REST endpoints
grep -r "export.*GET\|export.*POST" apiome-ui/src/app/api/auth/link/ 2>/dev/null || echo "✓ No public endpoints"
```

**Expected:**
- ✓ All database operations are server actions (`'use server'`)
- ✓ No public REST endpoints expose linking operations

---

### Security Test 2: User ID Validation

**Steps:**
1. Try to unlink another user's linked account
2. Modify the request to use a different linkedAccountId

**Expected Results:**
- ✓ Error: "Linked account not found or does not belong to you"
- ✓ Cannot unlink other users' accounts

---

### Security Test 3: Session Required

**Steps:**
1. Log out completely
2. Try to access: http://localhost:3000/ade/dashboard/linked-accounts

**Expected Results:**
- ✓ Redirected to login page
- ✓ Cannot access without authentication

---

## 📊 Database Integrity Tests

### Test 1: Foreign Key Cascade

**Test:**
```sql
-- Create test user
INSERT INTO apiome.users (name, email, password, verified, enabled)
VALUES ('Test Delete', 'test.delete@example.com', 'hash', true, true)
RETURNING id;

-- Link GitHub account (use the returned ID)
INSERT INTO apiome.external_auth_providers (user_id, provider, provider_user_id, provider_email)
VALUES ('USER_ID_FROM_ABOVE', 'github', 'test123', 'test.delete@example.com');

-- Delete the user
DELETE FROM apiome.users WHERE email = 'test.delete@example.com';

-- Check linked account was also deleted
SELECT COUNT(*) FROM apiome.external_auth_providers WHERE provider_email = 'test.delete@example.com';
-- Should return 0
```

**Expected:**
- ✓ Linked accounts are deleted when user is deleted (CASCADE)

---

### Test 2: Unique Constraints

**Test:**
```sql
-- Attempt to create duplicate link (same user, same provider)
-- This should FAIL
INSERT INTO apiome.external_auth_providers (user_id, provider, provider_user_id, provider_email)
VALUES ('existing-user-id', 'github', 'different-github-id', 'email@example.com');

INSERT INTO apiome.external_auth_providers (user_id, provider, provider_user_id, provider_email)
VALUES ('existing-user-id', 'github', 'another-github-id', 'email2@example.com');
```

**Expected:**
- ✓ Second INSERT fails with unique constraint violation
- ✓ Error mentions `external_auth_providers_user_id_provider_key`

---

## 🎨 UI/UX Testing

- [ ] Responsive design works on mobile
- [ ] Icons display correctly
- [ ] Colors match theme
- [ ] Buttons have hover states
- [ ] Loading states display properly
- [ ] Error messages are user-friendly
- [ ] Success messages are clear
- [ ] Confirmation dialogs work correctly
- [ ] Links open in correct location

---

## 🚀 Performance Testing

- [ ] Page loads quickly
- [ ] Database queries are efficient (check with EXPLAIN)
- [ ] No unnecessary re-renders
- [ ] Smooth animations/transitions

---

## 📝 Documentation Review

- [ ] Quick start guide is accurate
- [ ] Implementation summary is complete
- [ ] Architecture diagrams are clear
- [ ] Code examples work correctly
- [ ] SQL queries are valid

---

## ✅ Sign-Off

| Test Category | Status | Notes |
|--------------|--------|-------|
| Database Setup | ✅ PASS | All tables, indexes, constraints created |
| Helper Functions | ✅ PASS | All 6 functions implemented |
| UI Components | ✅ PASS | Page and navigation created |
| OAuth Configuration | ✅ PASS | GitHub OAuth configured |
| Security | ⏳ PENDING | Manual testing required |
| Integration | ⏳ PENDING | Manual testing required |

**Tested By:** _______________  
**Date:** _______________  
**Environment:** Development (localhost:3000)

---

## 🐛 Known Issues / Future Work

- [ ] Token encryption not yet implemented (⚠️ REQUIRED for production)
- [ ] GitLab OAuth not yet configured
- [ ] Google OAuth not yet configured
- [ ] AWS OAuth not yet configured
- [ ] Email notifications not implemented
- [ ] Audit logging not implemented

---

## 📞 Support

If you encounter issues:
1. Check browser console for errors
2. Check Next.js server logs
3. Run: `psql -U kenji -d kenji -f test-external-auth-providers.sql`
4. Review documentation in `apiome-db/docs/`

