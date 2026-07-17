'use server';

import crypto from 'crypto';
import {
  createUser,
  createTenant,
  addUserToTenant,
  addTenantAdministrator,
  deleteUser,
  deleteTenant,
  provisionSampleProject,
} from '../db/admin-helper';
import { linkExternalAccount } from '../db/helper';
import {
  getOauthSignupPendingById,
  deleteOauthSignupPendingById,
  insertAuthOneTimeCode,
  insertFreeTierEntitlements,
} from '../db/oauth-signup';

const slugRegex = /^[a-z0-9-]+$/;

const generateSlug = (name: string) =>
  name
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');

function validateTenantSlug(slug: string): string | null {
  if (!slug?.trim()) return 'Tenant slug is required';
  const s = slug.trim().toLowerCase();
  if (s.length < 2) return 'Slug must be at least 2 characters';
  if (!slugRegex.test(s)) return 'Slug must contain only lowercase letters, numbers, and dashes';
  return null;
}

export type CompleteOAuthSignupResult =
  | { success: true; oneTimeCode: string }
  | { success: false; error: string };

/**
 * Completes OAuth self-signup: creates user, tenant, free-tier entitlements, links the provider, returns a one-time login code.
 */
export async function completeOAuthSignup(
  pendingId: string,
  displayName: string,
  tenantDisplayName: string,
  tenantSlugInput: string
): Promise<CompleteOAuthSignupResult> {
  const name = displayName?.trim();
  const orgName = tenantDisplayName?.trim();
  const slugRaw = tenantSlugInput?.trim() ? tenantSlugInput.trim().toLowerCase() : generateSlug(orgName || '');

  if (!name) return { success: false, error: 'Name is required' };
  if (!orgName) return { success: false, error: 'Organization name is required' };
  const slugErr = validateTenantSlug(slugRaw);
  if (slugErr) return { success: false, error: slugErr };

  const pending = await getOauthSignupPendingById(pendingId);
  if (!pending) {
    return { success: false, error: 'Signup session expired or invalid. Please start again from the login page.' };
  }

  const email = pending.email?.trim().toLowerCase();
  if (!email) {
    return { success: false, error: 'No email is available from the OAuth provider.' };
  }

  const account = pending.account_json || {};
  const profile = pending.profile_json || {};

  const randomPassword = `${crypto.randomBytes(32).toString('hex')}!Aa1`;

  const userRes = await createUser(name, email, randomPassword, true, true);
  const userParsed = JSON.parse(userRes);
  if (!userParsed.success || !userParsed.user?.id) {
    return { success: false, error: userParsed.error || 'Could not create user' };
  }

  const userId: string = userParsed.user.id;

  const accessToken = typeof account.access_token === 'string' ? account.access_token : null;
  const refreshToken = typeof account.refresh_token === 'string' ? account.refresh_token : null;
  const exp = account.expires_at;
  const tokenExpiresAt =
    typeof exp === 'number' ? new Date(exp * 1000) : exp instanceof Date ? exp : null;

  const providerUsername =
    (typeof profile.login === 'string' && profile.login) ||
    (typeof profile.username === 'string' && profile.username) ||
    null;

  const profileData = {
    name: typeof profile.name === 'string' ? profile.name : name,
    avatar_url:
      (typeof profile.avatar_url === 'string' && profile.avatar_url) ||
      (typeof (profile as { image_url?: string }).image_url === 'string' &&
        (profile as { image_url?: string }).image_url) ||
      (typeof profile.image === 'string' && profile.image) ||
      (typeof profile.picture === 'string' && profile.picture) ||
      null,
    profile_url:
      (typeof profile.html_url === 'string' && profile.html_url) ||
      (typeof profile.web_url === 'string' && profile.web_url) ||
      (typeof profile.url === 'string' && profile.url) ||
      null,
  };

  // Honour the provider's verified-email claim from the stored profile/account JSON (OIDC providers
  // set `email_verified`); default to unverified when no signal is present. See OLO-1.2 / 2.5.
  const verifiedRaw =
    (profile as { email_verified?: unknown }).email_verified ??
    (account as { email_verified?: unknown }).email_verified;
  const emailVerified =
    verifiedRaw === true ||
    (typeof verifiedRaw === 'string' && verifiedRaw.trim().toLowerCase() === 'true');

  const linkRes = await linkExternalAccount(
    userId,
    pending.provider,
    pending.provider_account_id,
    email,
    providerUsername,
    accessToken,
    refreshToken,
    tokenExpiresAt,
    profileData,
    emailVerified
  );
  const linkParsed = JSON.parse(linkRes);
  if (!linkParsed.success) {
    await deleteUser(userId);
    return { success: false, error: linkParsed.error || 'Could not link OAuth account' };
  }

  const tenantRes = await createTenant(orgName, '', slugRaw, true);
  const tenantParsed = JSON.parse(tenantRes);
  if (!tenantParsed.success || !tenantParsed.tenant?.id) {
    await deleteUser(userId);
    return { success: false, error: tenantParsed.error || 'Could not create organization' };
  }

  const tenantId: string = tenantParsed.tenant.id;

  const addMemberRes = await addUserToTenant(tenantId, userId);
  const addMemberParsed = JSON.parse(addMemberRes);
  if (!addMemberParsed.success) {
    await deleteTenant(tenantId);
    await deleteUser(userId);
    return { success: false, error: addMemberParsed.error || 'Could not add you to the organization' };
  }

  const addAdminRes = await addTenantAdministrator(tenantId, userId);
  const addAdminParsed = JSON.parse(addAdminRes);
  if (!addAdminParsed.success) {
    await deleteTenant(tenantId);
    await deleteUser(userId);
    return { success: false, error: addAdminParsed.error || 'Could not grant organization access' };
  }

  await insertFreeTierEntitlements(userId);

  // Best-effort: seed the curated sample project so the new tenant isn't empty. Never block signup
  // if this fails — the user/tenant are already committed and a fresh tenant can simply start empty.
  await provisionSampleProject(tenantId, userId);

  await deleteOauthSignupPendingById(pendingId);

  const oneTimeCode = await insertAuthOneTimeCode(userId, tenantId);
  return { success: true, oneTimeCode };
}
