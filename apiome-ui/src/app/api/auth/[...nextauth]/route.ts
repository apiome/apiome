import NextAuth from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import { NextAuthOptions } from 'next-auth';
import type { Provider } from 'next-auth/providers/index';
import type { NextRequest } from 'next/server';
import {
  credentialsAuthorize,
  signInForProvider,
  ICredentials,
} from '../../../../../lib/auth/credentials';
import {
  buildAuthCookieOverrides,
  canonicalizeCrossAppCallback,
  isAllowedCallbackUrl,
  isSafeRelativeCallbackPath,
} from '../../../../../lib/auth/cookie-options';
import {
  configuredOAuthProviders,
  resolveOAuthProviders,
} from '../../../../../lib/auth/nextauth-oauth-providers';
import { AUTH_ERROR_CODES, loginErrorRedirect } from '../../../../../lib/auth/account-resolution';
import {
  resolveActiveTenantForLogin,
  validateTenantSwitch,
} from '../../../../../lib/auth/post-login-routing';
import { resolveClientIp } from '../../../../../lib/auth/client-ip';
import { activatePendingMembershipForLogin } from '../../../../../lib/auth/membership-activation';
import { readLastActiveTenantId } from '../../../../../lib/auth/last-active-tenant';
import { isBetterAuthEngine } from '../../../../../lib/auth/auth-engine';

/**
 * Assemble the NextAuth options from a resolved OAuth provider list.
 *
 * Everything except the OAuth providers (secret, cookie scoping, the credentials provider, pages, and
 * all session/jwt callbacks) is identical for every caller; only the OAuth provider set varies between
 * the static env build ({@link authOptions}) and the per-request DB-over-env build
 * ({@link buildRequestAuthOptions}). Keeping one factory guarantees the two never drift (OLO-8.6).
 *
 * @param oauthProviders OAuth provider configs to register ahead of the credentials provider.
 * @returns The complete `NextAuthOptions` for this deployment.
 */
function makeAuthOptions(oauthProviders: Provider[]): NextAuthOptions {
  return {
  secret: process.env.NEXTAUTH_SECRET,
  // Scope session cookies to NEXTAUTH_COOKIE_DOMAIN so subdomain apps
  // (e.g. the studio) can share the login session.
  ...buildAuthCookieOverrides(),
  providers: [
    // Every OAuth provider comes from the provider registry (OLO-2.3): a provider is
    // registered only when its env vars are configured, so disabling one via env removes
    // its sign-in route along with its login/link buttons. Email trust is decided by the
    // resolution engine inside signInForProvider (OLO-1.3/1.4), not here. The list is resolved
    // per request (OLO-8.6) so a DB config change lands on the next sign-in without a redeploy.
    ...oauthProviders,
    CredentialsProvider({
      credentials: {},
      async authorize(credentials: any, req) {
        const credentialPayload = JSON.parse(credentials?.payload ?? '{}');
        // Per-IP brute-force budget (OLO-7.1): NextAuth hands authorize a plain
        // header object; resolveClientIp handles both that and Headers.
        const clientIp = resolveClientIp(req?.headers);
        return await credentialsAuthorize(credentialPayload as ICredentials, clientIp);
      }
    })
  ],
  pages: {
    signIn: '/login',
    error: '/login',
  },
  callbacks: {
    signIn: async function (payload: any) {
      const user = payload.user;
      const loginProvider = payload.account?.provider ?? '';

      if (!user) {
        // Defensive fallback: emit the stable, generic on-contract code (OLO-1.5/7.3) instead of
        // a free-text "account not found" phrase so the redirect can neither drift from the
        // contract nor hint at whether an account exists.
        return loginErrorRedirect(AUTH_ERROR_CODES.SIGN_IN_FAILED);
      }

      // Credentials sign-ins run the account gates; every OAuth provider flows through the shared
      // account-resolution engine (OLO-1.3); an unconfigured provider is refused with the stable
      // `provider-not-configured` code (OLO-1.5).
      return signInForProvider(loginProvider, payload);
    },
    async redirect({ url, baseUrl }) {
      // Default NextAuth behaviour only allows same-origin callback URLs.
      // Also allow subdomains covered by the shared session cookie so login
      // can return to e.g. the studio app. Relative paths go through the
      // shared safety check so backslash tricks (`/\evil.com`) cannot turn
      // into a cross-origin redirect (OLO-3.4).
      if (isSafeRelativeCallbackPath(url)) {
        return `${baseUrl}${url}`;
      }
      const canonical = canonicalizeCrossAppCallback(url);
      if (isAllowedCallbackUrl(canonical, baseUrl)) {
        return canonical;
      }
      return baseUrl;
    },
    // async redirect({ url, baseUrl }) {
    //     // Override the login, redirecting to the login page if properly set.
    //     if (url === '/login') {
    //         return baseUrl + '/login';
    //     }
    //
    //     // This flow moves to the tenants page after login succeeds.
    //     if (url === '/tenants') {
    //         return baseUrl + '/tenants';
    //     }
    //
    //     return baseUrl;
    // },
    async session(payload: any) {
      if (payload.token?.user_id) {
        payload.session.user.user_id = payload.token.user_id;
      }

      if (payload.token?.current_tenant_id) {
        payload.session.user.current_tenant_id = payload.token.current_tenant_id;
      }

      if (payload.token?.name) {
        payload.session.user.name = payload.token.name;
      }

      return payload.session;
    },
    async jwt(payload: any) {
      const token = payload.token;

      // If the trigger is "update", this indicates that the session payload has changed,
      // and the token should be updated accordingly.
      if (payload.trigger === 'update') {
        if (payload.session?.user?.name) {
          token.name = payload.session.user.name;
        }

        // The requested tenant comes from the client (the tenant switcher calls
        // update({ current_tenant_id })), so — like the login path — it must be
        // re-validated against the user's live memberships before it enters the
        // signed token (OLO-7.3 threat-model fix). Without this, a tampered
        // update() could point server-side, tenant-scoped queries at a tenant the
        // user does not belong to. validateTenantSwitch fails closed, so on any
        // lookup failure the current tenant is left unchanged.
        const requestedTenantId = payload.session?.current_tenant_id;
        if (requestedTenantId && token.user_id) {
          const validatedTenantId = await validateTenantSwitch(token.user_id, requestedTenantId);
          if (validatedTenantId) {
            token.current_tenant_id = validatedTenantId;
          }
        }
      }

      if (payload.user) {
        token.user_id = payload.user.id;
        // Seed the session's active tenant per the post-login routing rules
        // (OLO-3.3): prefer the signup one-time-code tenant, keep the previous
        // session's tenant when still a membership, else fall back to the user's
        // default tenant. Tenant-less users carry no current_tenant_id and meet
        // the first-tenant onboarding guard instead.
        const pendingTenant = (payload.user as { pending_tenant_id?: string }).pending_tenant_id;
        // A fresh login has no previous token, so the durable last-active
        // cookie (written by the tenant switcher, OLO-6.1) supplies the
        // candidate; pickActiveTenantId re-validates it against memberships.
        let lastActiveCookieTenant: string | null = null;
        if (!pendingTenant && !token.current_tenant_id) {
          try {
            lastActiveCookieTenant = await readLastActiveTenantId();
          } catch (error) {
            console.error('[nextauth] last-active tenant cookie read failed:', error);
          }
        }
        const activeTenant = await resolveActiveTenantForLogin(
          payload.user.id,
          pendingTenant ?? token.current_tenant_id ?? lastActiveCookieTenant
        );
        if (activeTenant) {
          token.current_tenant_id = activeTenant;
          // Invited-user path (OLO-4.4): first arrival in the inviting tenant
          // transitions a pending membership to active. Never throws — an
          // activation failure must not break the sign-in.
          await activatePendingMembershipForLogin(
            {
              user_id: payload.user.id,
              email: payload.user.email,
              name: payload.user.name,
            },
            activeTenant
          );
        } else {
          delete token.current_tenant_id;
        }
      }

      return token;
    },
  }
  };
}

/**
 * Static, env-derived auth options for server-side session reads.
 *
 * Imported across the app for `getServerSession(authOptions)`. Validating an existing session only
 * consults the secret, cookies, and jwt/session callbacks — never the OAuth providers list — so an
 * env build is correct here; the DB-over-env provider resolution (OLO-8.6) matters only when *starting*
 * a sign-in, which goes through the per-request handler below.
 */
export const authOptions: NextAuthOptions = makeAuthOptions(configuredOAuthProviders());

/** Route context NextAuth's App Router handler receives as its second argument. */
interface RouteHandlerContext {
  params: { nextauth: string[] } | Promise<{ nextauth: string[] }>;
}

/**
 * Build the auth options for a single sign-in request, resolving the OAuth providers from the
 * DB-over-env merged config (OLO-8.6). The 8.5 TTL cache keeps this off the per-login hot path, and a
 * DB outage degrades to env config rather than breaking sign-in.
 *
 * @returns The per-request `NextAuthOptions`.
 */
async function buildRequestAuthOptions(): Promise<NextAuthOptions> {
  return makeAuthOptions(await resolveOAuthProviders());
}

/**
 * NextAuth App Router handler as a function of the request (OLO-8.6): NextAuth v4 accepts
 * `NextAuth(req, ctx, options)`, so the options — and thus the enabled provider set — are rebuilt on
 * every request instead of frozen at module load. Toggling a provider's DB config therefore takes
 * effect on the next request (within the resolver's cache TTL) with no redeploy.
 */
async function handler(req: NextRequest, ctx: RouteHandlerContext) {
  // Better Auth parallel-run dispatch (OLO-10.2, migration design §4). This one `/api/auth/*`
  // catch-all serves whichever engine the AUTH_ENGINE flag selects. A second sibling catch-all
  // (`[...all]`) cannot coexist here — Next.js normalizes it to the same route structure as
  // `[...nextauth]` and the build fails with an "ambiguous route" error — and renaming this folder
  // would break ~110 importers of `authOptions`. So the flag-selected cutover is realized by
  // delegating here. With the default `next-auth` engine this route is byte-for-byte NextAuth; the
  // Better Auth instance and its (ESM, Node-only) dependencies are imported lazily only when the
  // flag is on, so the legacy path never loads them.
  if (isBetterAuthEngine()) {
    const { betterAuthHandler } = await import('../../../../../lib/auth/auth');
    return betterAuthHandler(req);
  }
  return NextAuth(req, ctx, await buildRequestAuthOptions());
}

export { handler as GET, handler as POST };
