import * as helper from '../db/helper';
import { upsertOauthSignupPending, consumeAuthOneTimeCode } from '../db/oauth-signup';

const bcrypt = require('bcrypt');

export interface ICredentials {
  email?: string;
  password?: string;
  oneTimeCode?: string;
}

/**
 * Helper function to link GitHub account during OAuth flow
 */
export const linkGithubAccount = async (userId: string, account: any, profile: any) => {
  try {
    const result = await helper.linkExternalAccount(
      userId,
      'github',
      account.providerAccountId || profile.id,
      profile.email,
      profile.login || profile.username,
      account.access_token || null,
      account.refresh_token || null,
      account.expires_at ? new Date(account.expires_at * 1000) : null,
      {
        name: profile.name,
        avatar_url: profile.avatar_url || profile.picture,
        profile_url: profile.html_url || profile.url,
      }
    );

    const response = JSON.parse(result);
    return response.success;
  } catch (error) {
    console.error('[linkGithubAccount] Error linking account:', error);
    return false;
  }
};

/**
 * Helper function to link GitLab account during OAuth flow
 */
export const linkGitlabAccount = async (userId: string, account: any, profile: any) => {
  try {
    const result = await helper.linkExternalAccount(
      userId,
      'gitlab',
      account.providerAccountId || profile.id,
      profile.email,
      profile.login || profile.username,
      account.access_token || null,
      account.refresh_token || null,
      account.expires_at ? new Date(account.expires_at * 1000) : null,
      {
        name: profile.name,
        avatar_url: profile.image_url || profile.avatar_url || profile.picture,
        profile_url: profile.web_url || profile.url,
      }
    );

    const response = JSON.parse(result);
    return response.success;
  } catch (error) {
    console.error('[linkGitlabAccount] Error linking account:', error);
    return false;
  }
};

/**
 * Check if this is a linking flow (user already logged in and clicking "Link" button)
 * Note: This function will be called from the OAuth callback
 */
export const checkLinkingIntent = async () => {
  try {
    const { cookies } = await import('next/headers');
    const cookieStore = await cookies();
    const linkIntent = cookieStore.get('oauth_link_intent');

    if (linkIntent && linkIntent.value) {
      try {
        const intent = JSON.parse(linkIntent.value);
        if (Date.now() - intent.timestamp < 600000) {
          cookieStore.delete('oauth_link_intent');
          return intent;
        }
        cookieStore.delete('oauth_link_intent');
      } catch {
        cookieStore.delete('oauth_link_intent');
      }
    }
  } catch {
    // Cookie store unavailable; treat as no intent
  }

  return null;
};

/**
 * Check if the user started OAuth from "Create account" (self-signup) mode.
 */
export const checkSignupIntent = async () => {
  try {
    const { cookies } = await import('next/headers');
    const cookieStore = await cookies();
    const raw = cookieStore.get('oauth_signup_intent');

    if (raw && raw.value) {
      try {
        const intent = JSON.parse(raw.value);
        if (Date.now() - intent.timestamp < 600000) {
          cookieStore.delete('oauth_signup_intent');
          return intent as { provider: string; timestamp: number };
        }
        cookieStore.delete('oauth_signup_intent');
      } catch {
        cookieStore.delete('oauth_signup_intent');
      }
    }
  } catch {
    // Cookie store unavailable
  }

  return null;
};

/*
 * Authorization steps:
 * 1. User is retrieved by e-mail address.
 * 2. Comparison is checked against user password and stored password using bcrypt.
 * 3. If the user login succeeds, the record is returned without the password field.
 * 4. Failure returns a null, which the next-auth `authorize()` handler will interpret as an invalid account.
 *
 * One-time codes (after OAuth signup completion) are also accepted.
 */
export const credentialsAuthorize = async (credentials: ICredentials) => {
  if (credentials.oneTimeCode?.trim()) {
    const consumed = await consumeAuthOneTimeCode(credentials.oneTimeCode.trim());
    if (!consumed) {
      return null;
    }
    const userResults = await helper.getUserById(consumed.userId);
    if (userResults.rowCount === 0) {
      return null;
    }
    const userResult = userResults.rows[0];
    delete userResult.password;
    return {
      ...userResult,
      pending_tenant_id: consumed.tenantId,
    };
  }

  const password = credentials.password;
  const email = credentials.email;
  if (!email || !password) {
    return null;
  }

  const results = await helper.getUserByEmail(email);

  if (results.rowCount > 0) {
    const userResult = results.rows[0];
    const hashPassword = userResult.password;

    if (userResult.password) {
      if (bcrypt.compareSync(password, hashPassword)) {
        delete userResult.password;

        return userResult;
      }

      return null;
    } else {
      return null;
    }
  }

  return null;
};

/*
 * Sign-in Steps:
 * 1. User must exist.
 *    If user is null, return 'User account not found'
 * 2. Enabled must be true.
 *    If not enabled, return 'Your account is currently disabled'
 * 3. Verified must be true.
 *    If not verified, return 'You have not yet verified your account e-mail address'
 *
 * If all passes, true is returned.
 */
export const credentialsSignIn = async (payload: any) => {
  const user = payload.user;

  if (!user.enabled) {
    return '/login?error=Your account is currently disabled';
  }

  if (!user.verified) {
    return '/login?error=You have not yet verified your account e-mail address';
  }

  if (user.id) {
    void helper.updateUserLastLoginAt(user.id).catch((error: any) => {
      console.error('[credentialsSignIn] Failed to update last login timestamp:', error);
    });
  }

  return true;
};

type OAuthSignInResult = boolean | string;

function resolveOAuthEmail(user: any, profile: any): string | null {
  const fromUser = typeof user?.email === 'string' && user.email.trim() ? user.email.trim().toLowerCase() : '';
  if (fromUser) return fromUser;
  const fromProfile = typeof profile?.email === 'string' && profile.email.trim() ? profile.email.trim().toLowerCase() : '';
  if (fromProfile) return fromProfile;
  return null;
}

/*
 * Sign-in Steps for GitHub OAuth:
 * 1. Check if this GitHub account is already linked to a user in external_auth_providers
 *    - If linked, login as that user
 * 2. If signup intent: new users go to pending signup; existing email → error redirect
 * 3. If not linked, check if user exists by email — initial login / auto-link
 * 4. User must be enabled and verified
 */
export const credentialsGithub = async (payload: any): Promise<OAuthSignInResult> => {
  const user = payload.user;
  const account = payload.account;
  const profile = payload.profile;

  if (account?.providerAccountId) {
    const linkedAccountResult = await helper.getLinkedAccountByProvider('github', account.providerAccountId);
    const linkedAccount = JSON.parse(linkedAccountResult);

    if (linkedAccount.found && linkedAccount.account) {
      const userResults = await helper.getUserById(linkedAccount.account.user_id);

      if (userResults.rowCount > 0) {
        const userResult = userResults.rows[0];

        if (!userResult.enabled) {
          return '/login?error=Your account is currently disabled';
        }

        if (!userResult.verified) {
          return '/login?error=You have not yet verified your account e-mail address';
        }

        await helper.updateLinkedAccountLastLogin('github', account.providerAccountId);

        payload.user.id = userResult.id;
        payload.user.email = userResult.email;
        payload.user.name = userResult.name;
        payload.user.enabled = userResult.enabled;
        payload.user.verified = userResult.verified;

        void helper.updateUserLastLoginAt(userResult.id).catch((error: any) => {
          console.error('[credentialsGithub] Failed to update last login timestamp:', error);
        });
        return true;
      }
    }
  }

  const signupIntent = await checkSignupIntent();
  const email = resolveOAuthEmail(user, profile);

  const results = email ? await helper.getUserByEmail(email) : { rowCount: 0, rows: [] as any[] };

  if (signupIntent?.provider === 'github') {
    if (!email) {
      return '/login?error=OAuthEmailRequired';
    }
    if (results.rowCount > 0) {
      return '/login?error=OAuthAccountExists';
    }
    if (!account?.providerAccountId) {
      return '/login?error=OAuthProfileIncomplete';
    }
    const { id } = await upsertOauthSignupPending(
      'github',
      account.providerAccountId,
      email,
      {
        access_token: account.access_token ?? null,
        refresh_token: account.refresh_token ?? null,
        expires_at: account.expires_at ?? null,
        providerAccountId: account.providerAccountId,
      },
      { ...(profile || {}), email }
    );
    return `/signup/oauth?token=${encodeURIComponent(id)}`;
  }

  if (results.rowCount > 0) {
    const userResult = results.rows[0];

    if (!userResult.enabled) {
      return '/login?error=Your account is currently disabled';
    }

    if (!userResult.verified) {
      return '/login?error=You have not yet verified your account e-mail address';
    }

    if (account?.providerAccountId) {
      await linkGithubAccount(userResult.id, account, profile || user);
    }

    payload.user.id = userResult.id;
    payload.user.email = userResult.email;
    payload.user.name = userResult.name;
    payload.user.enabled = userResult.enabled;
    payload.user.verified = userResult.verified;

    void helper.updateUserLastLoginAt(userResult.id).catch((error: any) => {
      console.error('[credentialsGithub] Failed to update last login timestamp:', error);
    });
    return true;
  }

  return false;
};

/*
 * Sign-in Steps for GitLab OAuth (same structure as GitHub).
 */
export const credentialsGitlab = async (payload: any): Promise<OAuthSignInResult> => {
  const user = payload.user;
  const account = payload.account;
  const profile = payload.profile;

  if (account?.providerAccountId) {
    const linkedAccountResult = await helper.getLinkedAccountByProvider('gitlab', account.providerAccountId);
    const linkedAccount = JSON.parse(linkedAccountResult);

    if (linkedAccount.found && linkedAccount.account) {
      const userResults = await helper.getUserById(linkedAccount.account.user_id);

      if (userResults.rowCount > 0) {
        const userResult = userResults.rows[0];

        if (!userResult.enabled) {
          return '/login?error=Your account is currently disabled';
        }

        if (!userResult.verified) {
          return '/login?error=You have not yet verified your account e-mail address';
        }

        await helper.updateLinkedAccountLastLogin('gitlab', account.providerAccountId);

        payload.user.id = userResult.id;
        payload.user.email = userResult.email;
        payload.user.name = userResult.name;
        payload.user.enabled = userResult.enabled;
        payload.user.verified = userResult.verified;

        void helper.updateUserLastLoginAt(userResult.id).catch((error: any) => {
          console.error('[credentialsGitlab] Failed to update last login timestamp:', error);
        });
        return true;
      }
    }
  }

  const signupIntent = await checkSignupIntent();
  const email = resolveOAuthEmail(user, profile);

  const results = email ? await helper.getUserByEmail(email) : { rowCount: 0, rows: [] as any[] };

  if (signupIntent?.provider === 'gitlab') {
    if (!email) {
      return '/login?error=OAuthEmailRequired';
    }
    if (results.rowCount > 0) {
      return '/login?error=OAuthAccountExists';
    }
    if (!account?.providerAccountId) {
      return '/login?error=OAuthProfileIncomplete';
    }
    const { id } = await upsertOauthSignupPending(
      'gitlab',
      account.providerAccountId,
      email,
      {
        access_token: account.access_token ?? null,
        refresh_token: account.refresh_token ?? null,
        expires_at: account.expires_at ?? null,
        providerAccountId: account.providerAccountId,
      },
      { ...(profile || {}), email }
    );
    return `/signup/oauth?token=${encodeURIComponent(id)}`;
  }

  if (results.rowCount > 0) {
    const userResult = results.rows[0];

    if (!userResult.enabled) {
      return '/login?error=Your account is currently disabled';
    }

    if (!userResult.verified) {
      return '/login?error=You have not yet verified your account e-mail address';
    }

    if (account?.providerAccountId) {
      await linkGitlabAccount(userResult.id, account, profile || user);
    }

    payload.user.id = userResult.id;
    payload.user.email = userResult.email;
    payload.user.name = userResult.name;
    payload.user.enabled = userResult.enabled;
    payload.user.verified = userResult.verified;

    void helper.updateUserLastLoginAt(userResult.id).catch((error: any) => {
      console.error('[credentialsGitlab] Failed to update last login timestamp:', error);
    });
    return true;
  }

  return false;
};
