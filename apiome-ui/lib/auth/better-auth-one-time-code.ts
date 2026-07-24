/**
 * Better Auth one-time-code sign-in endpoint (OLO-10.13, #5008).
 *
 * Closes the gap #5007 deferred: the OAuth-signup completion (and any future invite handoff) signs
 * the freshly-created user in with a single-use credential code, but Better Auth ships no endpoint for
 * a code-only sign-in — so on the Better Auth engine the client compat layer previously no-op'd it
 * with a warning (`better-auth-client-compat.ts`).
 *
 * This plugin adds a minimal, self-contained endpoint that mirrors how Better Auth's own magic-link /
 * email-otp plugins log a user in after a non-password verification: consume the bearer secret, then
 * `internalAdapter.createSession(user.id)` + `setSessionCookie(ctx, { session, user })`. The one-time
 * code is the unguessable proof (issued server-side, 15-min TTL, deleted on first use —
 * `insertAuthOneTimeCode` / `consumeAuthOneTimeCode` in `lib/db/oauth-signup.ts`), so the endpoint is
 * safe to expose on the public `/api/auth/*` catch-all: without a valid, unconsumed code it does
 * nothing. This reuses the existing `auth_one_time_codes` table — no new token issuance or
 * key-management surface, exactly as the NextAuth credentials path consumes the same code
 * (`credentials.ts`).
 *
 * The endpoint returns the pending tenant id (when the code carried one) rather than writing the
 * last-active-tenant cookie itself: that cookie is app-owned (validated, named, scoped in
 * `last-active-tenant.ts`), so the thin server action that calls this endpoint
 * (`better-auth-one-time-code-actions.ts`) writes it — keeping tenant-cookie policy in app code while
 * this endpoint owns only session creation. `current_tenant_id` is then derived at read time from that
 * cookie (`better-auth-session-shape.ts`), matching the NextAuth `jwt`-callback path.
 */

import { createAuthEndpoint, APIError } from 'better-auth/api';
import { setSessionCookie } from 'better-auth/cookies';
import { z } from 'zod';
import { consumeAuthOneTimeCode } from '../db/oauth-signup';

/** Endpoint path under the Better Auth base path (`/api/auth`). */
export const ONE_TIME_CODE_VERIFY_PATH = '/one-time-code/verify';

/** Request body: the single-use code issued by the OAuth-signup completion. */
const verifyOneTimeCodeBodySchema = z.object({
  oneTimeCode: z.string().min(1).meta({ description: 'Single-use sign-in code from OAuth signup completion' }),
});

/** Shape returned to the caller on a successful code redemption. */
export interface VerifyOneTimeCodeResult {
  /** Always `true` on success (failures throw an `APIError`). */
  ok: true;
  /** The tenant the code was minted for, or `null` when it carried none. */
  tenantId: string | null;
}

/**
 * Better Auth plugin exposing `POST /api/auth/one-time-code/verify` (server: `auth.api.verifyOneTimeCode`).
 *
 * Registered in {@link file://./auth.ts} before `nextCookies()` (which must stay last so the session
 * cookie set here is forwarded from Next.js server actions).
 *
 * @returns The plugin object for the Better Auth `plugins` array.
 */
export function oneTimeCodePlugin() {
  return {
    id: 'one-time-code',
    endpoints: {
      verifyOneTimeCode: createAuthEndpoint(
        ONE_TIME_CODE_VERIFY_PATH,
        { method: 'POST', body: verifyOneTimeCodeBodySchema },
        async (ctx) => {
          // Atomically consume the code (single-use, TTL-checked). A missing/expired/used code yields
          // null — refuse without revealing which, exactly like the NextAuth path.
          const consumed = await consumeAuthOneTimeCode(ctx.body.oneTimeCode.trim());
          if (!consumed) {
            throw new APIError('UNAUTHORIZED', { message: 'Invalid or expired one-time code' });
          }

          const user = await ctx.context.internalAdapter.findUserById(consumed.userId);
          if (!user) {
            // The code pointed at a user that no longer exists — treat as an invalid code.
            throw new APIError('UNAUTHORIZED', { message: 'Invalid or expired one-time code' });
          }

          const session = await ctx.context.internalAdapter.createSession(user.id);
          if (!session) {
            throw new APIError('INTERNAL_SERVER_ERROR', { message: 'Failed to create session' });
          }
          await setSessionCookie(ctx, { session, user });

          const result: VerifyOneTimeCodeResult = { ok: true, tenantId: consumed.tenantId ?? null };
          return ctx.json(result);
        }
      ),
    },
  };
}
