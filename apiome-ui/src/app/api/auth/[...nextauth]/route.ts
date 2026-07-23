import NextAuth from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import { NextAuthOptions } from 'next-auth';
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
import { configuredOAuthProviders } from '../../../../../lib/auth/nextauth-oauth-providers';
import { AUTH_ERROR_CODES, loginErrorRedirect } from '../../../../../lib/auth/account-resolution';
import {
  resolveActiveTenantForLogin,
  validateTenantSwitch,
} from '../../../../../lib/auth/post-login-routing';
import { resolveClientIp } from '../../../../../lib/auth/client-ip';
import { activatePendingMembershipForLogin } from '../../../../../lib/auth/membership-activation';
import { readLastActiveTenantId } from '../../../../../lib/auth/last-active-tenant';

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  // Scope session cookies to NEXTAUTH_COOKIE_DOMAIN so subdomain apps
  // (e.g. the studio) can share the login session.
  ...buildAuthCookieOverrides(),
  providers: [
    // Every OAuth provider comes from the provider registry (OLO-2.3): a provider is
    // registered only when its env vars are configured, so disabling one via env removes
    // its sign-in route along with its login/link buttons. Email trust is decided by the
    // resolution engine inside signInForProvider (OLO-1.3/1.4), not here.
    ...configuredOAuthProviders(),
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

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };
