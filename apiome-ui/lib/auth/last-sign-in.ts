/**
 * Record every completed sign-in on `users.last_login_at`, which the admin console's Users list
 * shows as **Last active**.
 *
 * Before this, only provider and SSO sign-ins wrote the column (`resolution-store.ts`), so an
 * account that signs in with email and password never had a last sign-in.
 *
 * The hook is a plugin, not part of `hooks.after` in `auth.ts`, because of the order Better Auth
 * runs after-hooks in: the `hooks.after` handler first, then each plugin's in `plugins` order. The
 * two-factor plugin deletes the session a password sign-in created and clears
 * `ctx.context.newSession` when it issues a challenge. So does `oauthTwoFactorChallengeHandler`
 * for a provider sign-in. Listed after `twoFactor`, this plugin sees a new session only when the
 * sign-in is complete, including the second factor's own verify endpoints.
 */

import { createAuthMiddleware } from 'better-auth/api';

import { updateUserLastLoginAt } from '../db/helper';

/** What the hook reads from the endpoint context. */
export interface LastSignInContext {
  context?: { newSession?: { user?: { id?: unknown } | null } | null } | null;
}

/** Injectable writer, for tests. */
export interface LastSignInDeps {
  recordUserLogin: (userId: string) => Promise<unknown>;
}

const defaultDeps: LastSignInDeps = { recordUserLogin: updateUserLastLoginAt };

/**
 * Record the sign-in when the endpoint issued a session that survived every other hook.
 *
 * @param ctx The endpoint context.
 * @param deps Injectable dependencies.
 * @returns Resolves once recorded. A write failure is logged by the writer and never fails sign-in.
 */
export async function recordCompletedSignIn(
  ctx: LastSignInContext | null | undefined,
  deps: LastSignInDeps = defaultDeps
): Promise<void> {
  const userId = ctx?.context?.newSession?.user?.id;
  if (typeof userId !== 'string' || userId === '') return;
  try {
    await deps.recordUserLogin(userId);
  } catch (error) {
    console.error('Error recording last sign-in:', error);
  }
}

/**
 * The plugin. Keep it after `twoFactor` in the `plugins` array.
 *
 * @returns The plugin object for the Better Auth `plugins` array.
 */
export function lastSignInPlugin() {
  return {
    id: 'apiome-last-sign-in',
    hooks: {
      after: [
        {
          matcher: () => true,
          handler: createAuthMiddleware(async (ctx) => {
            await recordCompletedSignIn(ctx as unknown as LastSignInContext);
          }),
        },
      ],
    },
  };
}
